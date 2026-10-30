"""Supervising training runs.

One run at a time, in a child process, with a status dict the admin page polls.
The shape is ``potato/publish/manager.py``'s -- an ``_status`` dict under a
lock, a ``start_*`` that refuses when something is already in flight, and a
``status()`` that hands back a copy -- with a subprocess where publish has a
thread body.

The subprocess is the point. Training pulls in torch, native CUDA kernels and
whatever a third-party trainer drags along; any of those can segfault or get
OOM-killed. In-process, that takes the annotation server with it and every
annotator loses their session. Out of process, the supervisor reads a
returncode of -9 and reports "your machine ran out of memory".

Cancellation goes to the process group, not the process, because trainers
spawn dataloader workers that would otherwise outlive their parent.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import hashlib
import hmac
import secrets
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from potato.training import store
from potato.training.base import ResourceLimits, TrainingSpec
from potato.training.events import (EVENT_TYPES, EXIT_CANCELLED,
                                    EXIT_MEANINGS, EXIT_OK, parse_line)

logger = logging.getLogger(__name__)

__all__ = ["TrainingManager", "init_training_manager", "get_training_manager",
           "clear_training_manager"]

#: How long a cancelled child gets to exit cleanly before SIGKILL.
DEFAULT_GRACE_SECONDS = 20

_IDLE_STATUS = {
    "state": "idle", "run_id": None, "trainer": None, "step": "",
    "phase": "", "current": 0, "total": 0, "eta_s": None,
    "metrics": {}, "warnings": [], "errors": [], "skip_reason": "",
}


class _EventSink:
    """Applies v1 protocol events to the status dict and the events file.

    One instance per run. The local worker's stdout loop and an external
    agent's ``/progress`` posts both feed it, so the two transports cannot
    drift apart in what they report.
    """

    def __init__(self, manager: "TrainingManager", events_path: str):
        self._manager = manager
        self._lock = threading.Lock()
        self._fh = open(events_path, "a")
        self.metrics: Dict[str, Any] = {}
        self.result: Optional[Dict[str, Any]] = None
        self.error: Optional[Dict[str, Any]] = None

    def apply(self, payload: Dict[str, Any]) -> None:
        if not isinstance(payload, dict) \
                or payload.get("event") not in EVENT_TYPES:
            return
        manager = self._manager
        with self._lock:
            if self._fh is not None:
                self._fh.write(json.dumps(payload) + "\n")
                self._fh.flush()

            kind = payload["event"]
            if kind == "status":
                manager._set(state=payload.get("state", "running"),
                             step=payload.get("step", ""))
            elif kind == "progress":
                manager._set(phase=payload.get("phase", ""),
                             current=payload.get("current", 0),
                             total=payload.get("total", 0),
                             eta_s=payload.get("eta_s"))
            elif kind == "metric":
                self.metrics["%s_%s" % (payload.get("split", ""),
                                        payload.get("name", ""))] = \
                    payload.get("value")
                manager._set(metrics=dict(self.metrics))
            elif kind == "log":
                if payload.get("level") in ("warning", "error"):
                    with manager._lock:
                        bucket = ("errors" if payload["level"] == "error"
                                  else "warnings")
                        manager._status[bucket] = (
                            manager._status[bucket]
                            + [payload.get("msg", "")])[-20:]
            elif kind == "result":
                self.result = payload
            elif kind == "error":
                self.error = payload

    def close(self) -> None:
        with self._lock:
            if self._fh is not None:
                self._fh.close()
                self._fh = None


@dataclass
class ExternalJob:
    """A run handed to an agent instead of a local subprocess.

    Lives in memory for the life of the run: there is one slot, and a job
    whose server restarted has lost the supervisor that would record it, so
    persisting it would only resurrect something nobody is watching.
    """

    run_id: str
    backend: str
    backend_type: str
    spec: Dict[str, Any]
    run_dir: str
    sink: _EventSink
    #: SHA-256 of the one-run token an auto-launched agent was given.
    launch_token_digest: str = ""
    state: str = "queued"          # queued | claimed | done
    claimed_by: str = ""
    agent_info: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    last_contact: float = 0.0
    cancel_requested: bool = False
    cancel_at: float = 0.0
    completion: Optional[Dict[str, Any]] = None
    done: threading.Event = field(default_factory=threading.Event)

    def accepts_launch_token(self, token: str) -> bool:
        if not self.launch_token_digest or not token:
            return False
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        return hmac.compare_digest(digest, self.launch_token_digest)

    def public(self) -> Dict[str, Any]:
        return {"job_id": self.run_id, "backend": self.backend,
                "state": self.state, "cancelled": self.cancel_requested,
                "spec": self.spec}


class TrainingManager:
    """Starts, supervises and records training runs."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config or {}
        self.logger = logging.getLogger(__name__)

        self._lock = threading.RLock()
        self._status: Dict[str, Any] = dict(_IDLE_STATUS)
        self._process: Optional[subprocess.Popen] = None
        self._supervisor: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._current_run: Optional[store.TrainingRun] = None
        self._last_finished_at: float = 0.0
        #: Annotation count at the last auto-triggered run, for the debounce.
        self._last_trained_count: int = 0
        #: The run an agent is working on, when the backend is not local.
        self._job: Optional[ExternalJob] = None
        self._launcher = None
        #: Set when an agent asks for work, so a long-poll wakes at once.
        self._job_posted = threading.Condition(self._lock)

        training = self.config.get("model_training", {}) or {}
        self.enabled = bool(training.get("enabled", False))
        self.retain_runs = int(training.get("retain_runs", 5))
        self.grace_seconds = int(training.get("grace_seconds",
                                              DEFAULT_GRACE_SECONDS))
        self.split_seed = int(training.get("split_seed", 0))
        self.split_spec = training.get("splits") or None
        self.aggregation = training.get("aggregation", "consensus")

    # ------------------------------------------------------------- plumbing

    @property
    def root(self) -> str:
        """Where runs live: ``<output_annotation_dir>/training``."""
        output_dir = self.config.get("output_annotation_dir", "annotation_output")
        return os.path.join(self.config.get("task_dir", "."), output_dir,
                            "training")

    def run_dir(self, run_id: str) -> str:
        return os.path.join(self.root, "runs", run_id)

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._status)

    def is_running(self) -> bool:
        with self._lock:
            return self._status["state"] not in ("idle", "success", "error",
                                                 "cancelled")

    def _set(self, **fields: Any) -> None:
        with self._lock:
            self._status.update(fields)

    def history(self, limit: int = 50) -> List[Dict[str, Any]]:
        return [run.to_dict() for run in store.list_runs(self.config, limit)]

    # ---------------------------------------------------------------- start

    def start_run(self, trainer: str, schema_names: Sequence[str],
                  params: Optional[Dict[str, Any]] = None,
                  trigger: str = "manual",
                  limits: Optional[ResourceLimits] = None,
                  backend: Optional[str] = None
                  ) -> Dict[str, Any]:
        """Build a bundle and launch a run.

        Returns ``{"started": bool, "run_id": ...}`` or
        ``{"started": False, "error": ...}``. Refuses rather than queues when
        a run is in flight: a queue is a real feature with real semantics
        (priority, eviction, persistence across restart) and pretending to
        have one by spawning a second child is worse than saying no.
        """
        if self.is_running():
            return {"started": False,
                    "error": "A training run is already in progress",
                    "run_id": self.status().get("run_id")}

        if not schema_names:
            return {"started": False, "error": "No schema selected"}

        # A scheme that does not exist, or that the trainer cannot learn, is
        # refused now: it used to start, build a bundle and then fail.
        from potato.training.config_check import run_problems
        problems = run_problems(self.config, trainer, schema_names)
        if problems:
            return {"started": False, "error": " ".join(problems),
                    "http_status": 400}

        from potato.training.registry import resolve_params
        try:
            params = resolve_params(self.config, trainer, params)
        except ValueError as exc:
            return {"started": False, "error": str(exc)}

        from potato.training.backends import (default_backend_name,
                                              load_backends)
        backend = backend or default_backend_name(self.config)
        backends = load_backends(self.config)
        if backend not in backends:
            return {"started": False,
                    "error": "No training backend named %r; configure it "
                             "under model_training.backends" % backend}
        from potato.training.registry import get_trainer_class
        try:
            local_only = bool(getattr(get_trainer_class(trainer), "local_only",
                                      False))
        except Exception:  # noqa: BLE001 - a broken trainer fails in the worker
            local_only = False
        if local_only and backends[backend].type != "local":
            return {"started": False,
                    "error": "%s runs only on the local backend: it calls a "
                             "model service from this server, with its "
                             "credentials. Choose backend 'local'." % trainer}

        run = store.TrainingRun(
            run_id=store.new_run_id(), trainer=trainer, backend=backend,
            schema_names=list(schema_names), status="building",
            trigger=trigger, split_seed=self.split_seed,
            params=dict(params or {}))

        try:
            store.record_run(self.config, run)
        except Exception as exc:
            self.logger.exception("Could not open a run record")
            return {"started": False, "error": str(exc)}

        self._current_run = run
        self._stop_event.clear()
        self._set(state="building", run_id=run.run_id, trainer=trainer,
                  step="building bundle", metrics={}, warnings=[], errors=[],
                  skip_reason="", phase="", current=0, total=0,
                  # The last run's write-back counts, which a failed run
                  # would otherwise keep reporting as its own.
                  writeback=None)

        self._supervisor = threading.Thread(
            target=self._supervise, args=(run,), name="training-%s" % run.run_id,
            daemon=True)
        self._supervisor.start()
        return {"started": True, "run_id": run.run_id}

    # ----------------------------------------------------- auto-retrain

    def _restore_retrain_baseline(self) -> None:
        """After a restart, count from now, not from zero.

        The counters live in memory. Starting from zero, the first save after
        a restart retrained whatever update_frequency said, and
        min_interval_s did not apply. When the store has an earlier run, its
        finish time is the interval's start and the annotations already
        there are the count's. A project with no run yet keeps zero: it
        trains once it has update_frequency annotations.
        """
        if getattr(self, "_baseline_restored", False):
            return
        self._baseline_restored = True
        try:
            runs = store.list_runs(self.config, limit=1)
            last = runs[0] if runs else None
        except Exception:  # noqa: BLE001
            last = None
        if last is None:
            return
        if last.finished_at and not self._last_finished_at:
            self._last_finished_at = float(last.finished_at)
        if not self._last_trained_count:
            try:
                self._last_trained_count = self._annotation_count()
            except Exception:  # noqa: BLE001
                logger.debug("Could not count annotations", exc_info=True)

    def maybe_auto_retrain(self) -> Dict[str, Any]:
        """Start a run if enough has changed since the last one.

        Called on the Flask request thread after every annotation save, so it
        has to be cheap and it has to be quiet. Every reason for *not* starting
        is recorded in the status dict rather than dropped, because the failure
        mode of a debounce is looking broken: an admin who sees nothing
        happening should be able to read "waiting: 3 more annotations" instead
        of guessing.

        Returns ``{"started": bool, "reason": str}``.
        """
        settings = ((self.config.get("model_training", {}) or {})
                    .get("auto_retrain", {}) or {})
        if not settings.get("enabled"):
            return self._skip("auto-retrain is off")

        trainer = settings.get("trainer")
        schemas = settings.get("schemas") or []
        if not trainer or not schemas:
            return self._skip("auto_retrain needs both a trainer and schemas")

        # The Training page and the API ask before running a trainer whose
        # licence needs confirming; a config-started run has to say so in
        # the config, or it would train an AGPL model nobody agreed to.
        from potato.training.registry import trainer_info
        info = trainer_info(trainer)
        if info is not None and info.licence_ack \
                and settings.get("accept_licence") is not True:
            return self._skip(
                "%s is licensed %s; set model_training.auto_retrain."
                "accept_licence: true to confirm" % (trainer, info.licence))

        if self.is_running():
            return self._skip("a run is already in progress")

        self._restore_retrain_baseline()
        min_interval = float(settings.get("min_interval_s", 600))
        since = time.time() - self._last_finished_at
        if self._last_finished_at and since < min_interval:
            return self._skip("waiting %d more second(s) since the last run"
                              % int(min_interval - since))

        every = int(settings.get("update_frequency", 25))
        try:
            total = self._annotation_count()
        except Exception:
            logger.debug("Could not count annotations", exc_info=True)
            return self._skip("could not count annotations")

        delta = total - self._last_trained_count
        if delta < every:
            return self._skip("waiting for %d more annotation(s)"
                              % (every - delta))

        # Claim the delta before launching, so two concurrent saves cannot both
        # trigger a run for the same annotations.
        with self._lock:
            if self._status["state"] not in ("idle", "success", "error",
                                             "cancelled"):
                return self._skip("a run started while this check was running")
            self._last_trained_count = total

        outcome = self.start_run(trainer, schemas,
                                 params=settings.get("params") or {},
                                 trigger="auto",
                                 backend=settings.get("backend"))
        if not outcome.get("started"):
            # Give the delta back so the next save can try again.
            with self._lock:
                self._last_trained_count = max(0, total - delta)
            return self._skip(outcome.get("error", "could not start"))

        self._set(skip_reason="")
        return {"started": True, "reason": "", "run_id": outcome["run_id"]}

    def _skip(self, reason: str) -> Dict[str, Any]:
        self._set(skip_reason=reason)
        return {"started": False, "reason": reason}

    def _annotation_count(self) -> int:
        from potato.user_state_management import get_user_state_manager

        return sum(len(user_state.get_all_annotations())
                   for user_state in get_user_state_manager().get_all_users())

    # ----------------------------------------------------------- supervision

    def _supervise(self, run: store.TrainingRun) -> None:
        """Build the bundle, launch the child, drain its output, record."""
        try:
            bundle_dir = os.path.join(self.run_dir(run.run_id), "bundle")
            workdir = os.path.join(self.run_dir(run.run_id), "artifacts")
            os.makedirs(workdir, exist_ok=True)

            spec = self._build(run, bundle_dir, workdir)
        except Exception as exc:
            self.logger.exception("Bundle build failed for %s", run.run_id)
            self._finish(run, "error", error=str(exc),
                         error_code="bundle_failed")
            return

        spec_path = os.path.join(self.run_dir(run.run_id), "spec.json")
        spec.write(spec_path)

        from potato.training.backends import load_backends
        backend = load_backends(self.config).get(run.backend)

        try:
            if backend is not None and backend.is_remote:
                self._run_external(run, spec, backend)
            else:
                run.status = "running"
                run.started_at = time.time()
                store.record_run(self.config, run)
                self._set(state="running", step="starting")
                self._launch_and_drain(run, spec_path)
        except Exception as exc:
            self.logger.exception("Training run %s failed", run.run_id)
            self._finish(run, "error", error=str(exc),
                         error_code="supervisor_failed")

    def _build(self, run: store.TrainingRun, bundle_dir: str,
               workdir: str) -> TrainingSpec:
        from potato.export.cli import build_export_context
        from potato.training.dataset import (build_bundle,
                                             schema_specs_from_config)

        config_path = self.config.get("__config_path__")
        if config_path:
            context = build_export_context(config_path)
        else:
            context = self._context_from_live_state()

        writeback = (self.config.get("model_training", {}) or {}).get("writeback") or {}
        bundle, stats, split_ids = build_bundle(
            context, bundle_dir, run.schema_names,
            split_spec=self.split_spec, split_seed=self.split_seed,
            aggregation=self.aggregation,
            include_unlabeled=bool(writeback.get("include_unlabeled", False)))

        store.record_run_items(self.config, run.run_id, split_ids)
        run.n_train = stats.splits.get("train", 0)
        run.n_val = stats.splits.get("val", 0)
        run.n_test = stats.splits.get("test", 0)
        run.bundle_digest = bundle.digest
        run.kinds = [s["kind"] for s in bundle.manifest.get("schemas", [])]
        store.record_run(self.config, run)

        if stats.warnings:
            self._set(warnings=list(stats.warnings))

        training = self.config.get("model_training", {}) or {}
        limits = ResourceLimits(
            max_wall_s=training.get("max_wall_seconds"),
            max_ram_mb=training.get("max_ram_mb"),
            device=training.get("device", "auto"),
            num_threads=training.get("num_threads"))

        params = dict(run.params or {})
        params.update(self._trainer_class(run.trainer, "server_params",
                                          self.config, run.schema_names,
                                          dict(run.params or {})) or {})
        return TrainingSpec(
            run_id=run.run_id, trainer=run.trainer,
            schemas=schema_specs_from_config(
                self.config, run.schema_names, bundle.manifest.get("labels")),
            bundle_dir=bundle_dir, workdir=workdir, params=params,
            seed=self.split_seed, limits=limits)

    def _trainer_class(self, name: str, hook: str, *args):
        """Call a trainer classmethod hook; None when the trainer will not
        import here (the worker reports that failure itself)."""
        from potato.training.registry import get_trainer_class
        try:
            return getattr(get_trainer_class(name), hook)(*args)
        except Exception:  # noqa: BLE001
            self.logger.debug("Trainer hook %s.%s failed", name, hook,
                              exc_info=True)
            return None

    def _context_from_live_state(self):
        """An ExportContext from the running server's managers.

        Used when the manager was initialized from a live config rather than a
        config path, which is the normal case inside the server.
        """
        import types

        from potato.item_state_management import get_item_state_manager
        from potato.export.cli import load_annotations_from_output_dir

        item_manager = get_item_state_manager()
        items = {}
        for iid in item_manager.get_instance_ids():
            item = item_manager.get_item(iid)
            if item is not None:
                items[str(iid)] = dict(item.item_data or {})

        output_dir = os.path.join(
            self.config.get("task_dir", "."),
            self.config.get("output_annotation_dir", "annotation_output"))
        annotations = load_annotations_from_output_dir(
            output_dir, self.config.get("annotation_schemes", []), self.config)

        return types.SimpleNamespace(
            config=self.config, annotations=annotations, items=items,
            schemas=self.config.get("annotation_schemes", []),
            output_dir=output_dir, phase_responses={})

    def _launch_and_drain(self, run: store.TrainingRun,
                          spec_path: str) -> None:
        run_dir = self.run_dir(run.run_id)
        events_path = os.path.join(run_dir, "events.jsonl")
        stdout_path = os.path.join(run_dir, "stdout.log")
        stderr_path = os.path.join(run_dir, "stderr.log")

        env = dict(os.environ)
        env.update(self._trainer_class(run.trainer, "run_environment",
                                       self.config, dict(run.params or {})) or {})
        env["PYTHONUNBUFFERED"] = "1"
        env.setdefault("MPLBACKEND", "Agg")
        cache = os.environ.get("POTATO_MODEL_CACHE")
        if cache:
            # Only diarization honoured this before. Pointing the Hugging Face
            # caches at it too means one variable covers an air-gapped
            # install's whole model story.
            env.setdefault("HF_HOME", cache)
            env.setdefault("TRANSFORMERS_CACHE", cache)
            env.setdefault("SENTENCE_TRANSFORMERS_HOME", cache)

        # sys.executable, never the `potato` console script: that entry point
        # resolves to flask_server:main, and not entering the server is the
        # entire reason this is a subprocess.
        argv = [sys.executable, "-m", "potato.training.worker",
                "--spec", spec_path]

        with open(stderr_path, "w") as stderr_fh:
            process = subprocess.Popen(
                argv, cwd=run_dir, env=env, stdout=subprocess.PIPE,
                stderr=stderr_fh, text=True, bufsize=1,
                # A new session gives a process group, so cancelling reaches
                # dataloader workers the trainer forked.
                start_new_session=True)

            with self._lock:
                self._process = process
            run.pid = process.pid
            store.record_run(self.config, run)

            deadline = None
            training = self.config.get("model_training", {}) or {}
            if training.get("max_wall_seconds"):
                deadline = time.time() + float(training["max_wall_seconds"])

            sink = _EventSink(self, events_path)
            try:
                with open(stdout_path, "w") as stdout_fh:
                    for line in process.stdout:
                        stdout_fh.write(line)
                        payload = parse_line(line)
                        if payload is None:
                            # A third-party progress bar must not kill a
                            # good run.
                            continue
                        sink.apply(payload)

                        if self._stop_event.is_set():
                            continue
                        if deadline and time.time() > deadline:
                            self.logger.warning(
                                "Run %s exceeded its wall-clock limit",
                                run.run_id)
                            self._wall_limited = run.run_id
                            self._terminate(process)
                            deadline = None
            finally:
                sink.close()

            returncode = process.wait()

        with self._lock:
            self._process = None

        self._record_completion(run, returncode, sink.result, sink.error,
                                sink.metrics)

    def _record_completion(self, run: store.TrainingRun, returncode: int,
                           result_event: Optional[Dict[str, Any]],
                           error_event: Optional[Dict[str, Any]],
                           metrics: Dict[str, Any]) -> None:
        """Decide what actually happened, from more than the exit code.

        An exit without a ``result`` event is a failure no matter how clean the
        code, because a trainer that exits 0 without reporting a result did not
        finish. A negative returncode is a signal: -9 is the OOM killer, which
        is the case the subprocess exists to survive.
        """
        if self._stop_event.is_set():
            self._finish(run, "cancelled", error="Cancelled by an operator",
                         error_code="cancelled")
            return

        if getattr(self, "_wall_limited", None) == run.run_id:
            # Stopped by the limit, and the worker then exits as if
            # cancelled; "exited with code 4 (cancelled)" named neither.
            limit = (self.config.get("model_training", {}) or {}).get(
                "max_wall_seconds")
            self._finish(run, "error", error_code="timeout",
                         error="Stopped: the run took longer than "
                               "model_training.max_wall_seconds (%s s)." % limit)
            return

        if returncode < 0:
            signame = signal.Signals(-returncode).name \
                if -returncode in [s.value for s in signal.Signals] else str(-returncode)
            if -returncode == signal.SIGKILL:
                message = ("The training process was killed, which usually "
                           "means the machine ran out of memory. Try a "
                           "smaller model or fewer items.")
                code = "killed"
            else:
                message = "The training process was terminated by %s" % signame
                code = "signal"
            self._finish(run, "error", error=message, error_code=code)
            return

        if error_event is not None:
            message = error_event.get("message", "Training failed")
            hint = error_event.get("install_hint")
            if hint:
                message = "%s\n%s" % (message, hint)
            self._finish(run, "error", error=message,
                         error_code=error_event.get("code", "error"))
            return

        if result_event is None:
            self._finish(
                run, "error",
                error=("The trainer exited with code %d (%s) without "
                       "reporting a result."
                       % (returncode,
                          EXIT_MEANINGS.get(returncode, "unknown"))),
                error_code="no_result")
            return

        merged = dict(metrics)
        merged.update(result_event.get("metrics") or {})
        self._finish(run, "success",
                     model_version=result_event.get("model_version", ""),
                     metrics=merged,
                     artifact_dir=os.path.join(self.run_dir(run.run_id),
                                               "artifacts"))
        self._after_success(run, result_event)

    def _after_success(self, run: store.TrainingRun,
                       result_event: Dict[str, Any]) -> None:
        """Ingest predictions and prune, once a run has really succeeded."""
        predictions_file = result_event.get("predictions_file")
        if predictions_file:
            path = os.path.join(self.run_dir(run.run_id), "artifacts",
                                predictions_file)
            try:
                from potato.training.writeback import ingest_predictions
                report = ingest_predictions(run, path, self.config)
                self._set(writeback=report.to_dict())
            except Exception:
                self.logger.exception("Write-back failed for run %s",
                                      run.run_id)

        try:
            store.prune_runs(self.config, self.retain_runs)
        except Exception:
            self.logger.debug("Pruning failed", exc_info=True)

    def _finish(self, run: store.TrainingRun, status: str, **fields) -> None:
        run.status = status
        run.finished_at = time.time()
        for key, value in fields.items():
            setattr(run, key, value)
        try:
            store.record_run(self.config, run)
        except Exception:
            self.logger.exception("Could not record run %s", run.run_id)

        self._last_finished_at = run.finished_at
        # "a run is already in progress" is not true any more.
        self._set(state=status, step="", skip_reason="",
                  metrics=fields.get("metrics", {}) or {},
                  errors=([fields["error"]] if fields.get("error") else []))

    # ------------------------------------------------------ external runs

    def _server_target(self) -> Tuple[str, int, str]:
        """``(host, port, scheme)`` an ssh forward should point at.

        The forward is opened on this machine, so a server listening on every
        interface is reached on loopback.
        """
        host = str(self.config.get("host") or "127.0.0.1")
        if host in ("0.0.0.0", "::", ""):
            host = "127.0.0.1"
        scheme = ("https" if self.config.get("ssl_cert")
                  and self.config.get("ssl_key") else "http")
        return host, int(self.config.get("port", 8000)), scheme

    def _run_external(self, run: store.TrainingRun, spec: TrainingSpec,
                      backend) -> None:
        """Hand a built run to an agent and wait for it to report back."""
        run_dir = self.run_dir(run.run_id)
        sink = _EventSink(self, os.path.join(run_dir, "events.jsonl"))
        job = ExternalJob(run_id=run.run_id, backend=backend.name,
                          backend_type=backend.type, spec=spec.to_dict(),
                          run_dir=run_dir, sink=sink)
        token = ""
        if backend.type == "ssh":
            # One token, one run. It reaches the agent on stdin, so it never
            # shows in `ps` on a shared machine, and it stops working when the
            # run ends.
            token = secrets.token_urlsafe(32)
            job.launch_token_digest = hashlib.sha256(
                token.encode("utf-8")).hexdigest()

        run.status = "queued"
        # The record defaults to this machine's name, which is wrong for every
        # remote run; the launcher or the claiming agent fills in the real one.
        run.host = (backend.host if backend.type == "ssh"
                    else "agent %s (not yet claimed)" % backend.name)
        store.record_run(self.config, run)
        with self._lock:
            self._job = job
            self._job_posted.notify_all()
        self._set(state="queued",
                  step=("connecting to %s" % backend.host
                        if backend.type == "ssh"
                        else "waiting for agent %r to ask for work"
                        % backend.name))

        launcher = None
        try:
            if backend.type == "ssh":
                from potato.training.launchers import LaunchError, SSHLauncher

                launcher = SSHLauncher(
                    backend, root=self.root,
                    log=lambda level, msg: sink.apply(
                        _log_event(level, msg)),
                    step=lambda text: self._set(step=text))
                with self._lock:
                    self._launcher = launcher
                try:
                    launcher.start(run.run_id, token, self._server_target())
                except Exception as exc:  # noqa: BLE001
                    message = str(exc) if isinstance(exc, LaunchError) \
                        else "%s: %s" % (type(exc).__name__, exc)
                    self._end_job(job, EXIT_CANCELLED
                                  if job.cancel_requested else 1,
                                  code="launch_failed", message=message)
                if launcher.host_description:
                    run.host = launcher.host_description
                    store.record_run(self.config, run)

            if not job.done.is_set():
                self._wait_for_job(job, backend, launcher)

            ok = bool(sink.result) and not sink.error \
                and not self._stop_event.is_set()
            if launcher is not None and ok and backend.fetch_artifacts:
                self._set(step="fetching artifacts")
                try:
                    launcher.fetch_artifacts(
                        run.run_id, os.path.join(run_dir, "artifacts"))
                except Exception as exc:  # noqa: BLE001
                    sink.apply(_log_event(
                        "warning", "Could not fetch the model artifacts "
                        "from %s: %s" % (backend.host, exc)))
        finally:
            if launcher is not None:
                try:
                    launcher.close(run.run_id)
                except Exception:
                    self.logger.debug("Launcher cleanup failed",
                                      exc_info=True)
            sink.close()
            with self._lock:
                self._job = None
                self._launcher = None

        completion = job.completion or {}
        if completion.get("code") and sink.error is None:
            sink.error = {"event": "error", "code": completion["code"],
                          "message": completion.get("message", "")}
        # An agent reports where it ran and where it left the model. The
        # run's host defaulted to this server's name, so `not run.host` never
        # let the agent's through, and the artifact_uri was dropped outright.
        if completion.get("host") and backend.type != "ssh":
            run.host = str(completion["host"])[:200]
        if completion.get("artifact_uri"):
            run.artifact_uri = str(completion["artifact_uri"])[:1000]
        self._record_completion(run, int(completion.get("returncode", 1)),
                                sink.result, sink.error, sink.metrics)

    def _wait_for_job(self, job: ExternalJob, backend, launcher) -> None:
        training = self.config.get("model_training", {}) or {}
        max_wall = training.get("max_wall_seconds")
        deadline = (time.time() + float(max_wall)) if max_wall else None

        while not job.done.wait(1.0):
            now = time.time()
            if job.cancel_requested:
                if job.state == "queued":
                    self._end_job(job, EXIT_CANCELLED)
                elif now - job.cancel_at > self.grace_seconds:
                    if launcher is not None:
                        launcher.kill_agent()
                    self._end_job(job, EXIT_CANCELLED)
                continue

            if launcher is not None and launcher.agent_exited():
                # Its last /complete may still be in flight.
                if job.done.wait(5.0):
                    break
                self._end_job(
                    job, 1, code="agent_exited",
                    message="The agent on %s exited (code %s) without "
                            "reporting a result. %s"
                            % (backend.host, launcher.agent_returncode(),
                               launcher.agent_stderr_tail()))
                continue

            if job.state == "claimed" and \
                    now - job.last_contact > backend.heartbeat_timeout_s:
                if launcher is not None:
                    launcher.kill_agent()
                self._end_job(
                    job, 1, code="backend_silent",
                    message="No word from the agent on %s for %d seconds"
                            % (backend.name, backend.heartbeat_timeout_s))
                continue

            if job.state == "queued" and backend.queue_timeout_s and \
                    now - job.created_at > float(backend.queue_timeout_s):
                self._end_job(
                    job, 1, code="no_agent",
                    message="No agent named %r asked for work within %d "
                            "seconds. Start one with: potato training agent"
                            % (backend.name, int(backend.queue_timeout_s)))
                continue

            if deadline and now > deadline:
                self.logger.warning("Run %s exceeded its wall-clock limit",
                                    job.run_id)
                deadline = None
                job.cancel_requested = True
                job.cancel_at = now
                job.completion = {"returncode": 1, "code": "timeout",
                                  "message": "The run exceeded "
                                             "model_training.max_wall_seconds"}

    def _end_job(self, job: ExternalJob, returncode: int, code: str = "",
                 message: str = "", **extra: Any) -> None:
        with self._lock:
            if job.done.is_set():
                return
            completion = dict(job.completion or {})
            completion.setdefault("returncode", returncode)
            if code:
                completion.setdefault("code", code)
                completion.setdefault("message", message)
            completion.update(extra)
            job.completion = completion
            job.state = "done"
            job.done.set()

    # Called by potato.training.protocol on the request thread.

    def current_job(self, run_id: Optional[str] = None
                    ) -> Optional[ExternalJob]:
        with self._lock:
            job = self._job
        if job is None or (run_id and job.run_id != run_id):
            return None
        return job

    def claim_job(self, backend_name: str, agent_info: Dict[str, Any],
                  wait_s: float = 0.0) -> Optional[ExternalJob]:
        """Give a polling agent the queued run for its backend, if any.

        Long-polls up to *wait_s* so an idle agent is told about a new run as
        soon as it is posted rather than on its next poll.
        """
        deadline = time.time() + max(0.0, min(float(wait_s), 60.0))
        with self._job_posted:
            while True:
                job = self._job
                if job is not None and job.state == "queued" \
                        and job.backend == backend_name \
                        and job.backend_type == "agent" \
                        and not job.cancel_requested:
                    self._mark_claimed(job, agent_info)
                    return job
                remaining = deadline - time.time()
                if remaining <= 0:
                    return None
                self._job_posted.wait(min(remaining, 5.0))

    def touch_job(self, job: ExternalJob,
                  agent_info: Optional[Dict[str, Any]] = None) -> None:
        """Record contact from the agent working on *job*."""
        with self._lock:
            if job.state == "queued":
                self._mark_claimed(job, agent_info or {})
            job.last_contact = time.time()

    def _mark_claimed(self, job: ExternalJob,
                      agent_info: Dict[str, Any]) -> None:
        job.state = "claimed"
        job.claimed_by = str(agent_info.get("host") or job.backend)
        job.agent_info = dict(agent_info or {})
        job.last_contact = time.time()
        run = self._current_run
        if run is not None and run.run_id == job.run_id:
            run.status = "running"
            run.started_at = time.time()
            if agent_info.get("host") and job.backend_type == "agent":
                run.host = str(agent_info["host"])[:200]
            try:
                store.record_run(self.config, run)
            except Exception:
                self.logger.debug("Could not record claim", exc_info=True)
        self._set(state="running",
                  step="running on %s" % job.claimed_by)

    def job_progress(self, job: ExternalJob,
                     events: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        self.touch_job(job)
        if not job.done.is_set():
            for payload in events:
                job.sink.apply(payload)
        return {"cancelled": bool(job.cancel_requested)}

    def complete_job(self, job: ExternalJob,
                     body: Dict[str, Any]) -> Dict[str, Any]:
        self.touch_job(job)
        for payload in body.get("events") or []:
            job.sink.apply(payload)
        try:
            returncode = int(body.get("returncode", 1))
        except (TypeError, ValueError):
            returncode = 1
        self._end_job(job, returncode,
                      host=str(body.get("host", ""))[:200],
                      artifact_uri=str(body.get("artifact_uri", ""))[:1000])
        return {"ok": True}

    # --------------------------------------------------------------- cancel

    def cancel(self, run_id: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            current = self._status.get("run_id")
            process = self._process
            job = self._job

        if process is None and job is None:
            return {"cancelled": False, "error": "No run is in progress"}
        if run_id and run_id != current:
            return {"cancelled": False,
                    "error": "Run %s is not the one in progress" % run_id}

        self._stop_event.set()
        if process is not None:
            self._terminate(process)
        if job is not None:
            # An agent is told in the response to its next /progress; there is
            # no inbound call to make, which is what lets it sit behind NAT.
            with self._lock:
                job.cancel_requested = True
                job.cancel_at = time.time()
                self._job_posted.notify_all()
            self._set(step="cancelling")
        return {"cancelled": True, "run_id": current}

    def _terminate(self, process: subprocess.Popen) -> None:
        """SIGTERM to the group, then SIGKILL after the grace period.

        The group, not the process: a trainer's dataloader workers are
        children of the child, and signalling only the child leaves them
        holding the GPU.
        """
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                process.terminate()
            except Exception:
                return

        def hard_kill():
            # The Timer has already waited out the grace period; all that is
            # left is to check whether the child took the hint.
            if process.poll() is not None:
                return
            self.logger.warning(
                "Training process %d did not stop within %ds; killing",
                process.pid, self.grace_seconds)
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass

        timer = threading.Timer(self.grace_seconds, hard_kill)
        timer.daemon = True
        timer.start()

    def shutdown(self) -> None:
        """Stop any in-flight run. Called at interpreter exit."""
        with self._lock:
            process = self._process
            job = self._job
            launcher = self._launcher
        if process is not None and process.poll() is None:
            self._stop_event.set()
            self._terminate(process)
        if job is not None:
            self._stop_event.set()
            job.cancel_requested = True
            job.cancel_at = time.time()
            if launcher is not None:
                try:
                    launcher.kill_agent()
                except Exception:
                    pass
            self._end_job(job, EXIT_CANCELLED)
        if self._supervisor and self._supervisor.is_alive():
            self._supervisor.join(timeout=5.0)


def _log_event(level: str, msg: str) -> Dict[str, Any]:
    from potato.training.events import event
    return event("log", level=level, msg=msg)


_TRAINING_MANAGER: Optional[TrainingManager] = None


def init_training_manager(config: Dict[str, Any]) -> TrainingManager:
    global _TRAINING_MANAGER
    _TRAINING_MANAGER = TrainingManager(config)

    import atexit
    atexit.register(_TRAINING_MANAGER.shutdown)
    return _TRAINING_MANAGER


def get_training_manager() -> Optional[TrainingManager]:
    return _TRAINING_MANAGER


def clear_training_manager() -> None:
    global _TRAINING_MANAGER
    if _TRAINING_MANAGER is not None:
        try:
            _TRAINING_MANAGER.shutdown()
        except Exception:
            pass
    _TRAINING_MANAGER = None

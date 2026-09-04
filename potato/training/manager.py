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
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from potato.training import store
from potato.training.base import ResourceLimits, TrainingSpec
from potato.training.events import (EXIT_MEANINGS, EXIT_OK, parse_line)

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
                  limits: Optional[ResourceLimits] = None
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

        run = store.TrainingRun(
            run_id=store.new_run_id(), trainer=trainer,
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
                  skip_reason="", phase="", current=0, total=0)

        self._supervisor = threading.Thread(
            target=self._supervise, args=(run,), name="training-%s" % run.run_id,
            daemon=True)
        self._supervisor.start()
        return {"started": True, "run_id": run.run_id}

    # ----------------------------------------------------- auto-retrain

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

        if self.is_running():
            return self._skip("a run is already in progress")

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
                                 trigger="auto")
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

        run.status = "running"
        run.started_at = time.time()
        store.record_run(self.config, run)
        self._set(state="running", step="starting")

        try:
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

        bundle, stats, split_ids = build_bundle(
            context, bundle_dir, run.schema_names,
            split_spec=self.split_spec, split_seed=self.split_seed,
            aggregation=self.aggregation)

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

        return TrainingSpec(
            run_id=run.run_id, trainer=run.trainer,
            schemas=schema_specs_from_config(
                self.config, run.schema_names, bundle.manifest.get("labels")),
            bundle_dir=bundle_dir, workdir=workdir, params=run.params,
            seed=self.split_seed, limits=limits)

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
            output_dir, self.config.get("annotation_schemes", []))

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

            result_event: Optional[Dict[str, Any]] = None
            error_event: Optional[Dict[str, Any]] = None
            metrics: Dict[str, Any] = {}

            with open(events_path, "w") as events_fh, \
                    open(stdout_path, "w") as stdout_fh:
                for line in process.stdout:
                    stdout_fh.write(line)
                    payload = parse_line(line)
                    if payload is None:
                        # A third-party progress bar must not kill a good run.
                        continue
                    events_fh.write(json.dumps(payload) + "\n")
                    events_fh.flush()

                    kind = payload["event"]
                    if kind == "status":
                        self._set(state=payload.get("state", "running"),
                                  step=payload.get("step", ""))
                    elif kind == "progress":
                        self._set(phase=payload.get("phase", ""),
                                  current=payload.get("current", 0),
                                  total=payload.get("total", 0),
                                  eta_s=payload.get("eta_s"))
                    elif kind == "metric":
                        metrics["%s_%s" % (payload.get("split", ""),
                                           payload.get("name", ""))] = \
                            payload.get("value")
                        self._set(metrics=dict(metrics))
                    elif kind == "log":
                        if payload.get("level") in ("warning", "error"):
                            with self._lock:
                                bucket = ("errors"
                                          if payload["level"] == "error"
                                          else "warnings")
                                self._status[bucket] = (
                                    self._status[bucket] + [payload.get("msg", "")])[-20:]
                    elif kind == "result":
                        result_event = payload
                    elif kind == "error":
                        error_event = payload

                    if self._stop_event.is_set():
                        continue
                    if deadline and time.time() > deadline:
                        self.logger.warning(
                            "Run %s exceeded its wall-clock limit", run.run_id)
                        self._terminate(process)
                        deadline = None

            returncode = process.wait()

        with self._lock:
            self._process = None

        self._record_completion(run, returncode, result_event, error_event,
                                metrics)

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
        self._set(state=status, step="",
                  metrics=fields.get("metrics", {}) or {},
                  errors=([fields["error"]] if fields.get("error") else []))

    # --------------------------------------------------------------- cancel

    def cancel(self, run_id: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            current = self._status.get("run_id")
            process = self._process

        if process is None:
            return {"cancelled": False, "error": "No run is in progress"}
        if run_id and run_id != current:
            return {"cancelled": False,
                    "error": "Run %s is not the one in progress" % run_id}

        self._stop_event.set()
        self._terminate(process)
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
        if process is not None and process.poll() is None:
            self._stop_event.set()
            self._terminate(process)
        if self._supervisor and self._supervisor.is_alive():
            self._supervisor.join(timeout=5.0)


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

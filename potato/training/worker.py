"""The training subprocess.

Run as ``python -m potato.training.worker --spec runs/<id>/spec.json``. It
reads a spec and a bundle off disk, fits a trainer, writes artifacts and
predictions, and reports progress as JSON Lines on stdout.

**It must not import Potato's server.** Not ``flask_server``, not ``routes``,
not ``item_state_management``. That boundary is what makes the rest work: the
extras gate can be enforced here because the parent never loads the training
library, a torch OOM kills this process instead of the annotation server, and
an external backend can be written by porting :func:`run` without pulling
Potato's web stack onto someone else's GPU box.

This file is also the reference implementation of the external-backend
protocol. Anyone writing a backend should read it rather than the spec prose.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import traceback
from typing import Any, Dict, List, Optional

# Import only from the leaf modules. `potato.training.__init__` pulls in the
# run store, which pulls in sqlite and the persistence layer -- none of which
# the child has any business touching, since the parent owns the database.
from potato.training.base import (BundleRef, MissingDependency, PredictItem,
                                  TrainerError, TrainingSpec)
from potato.training.events import (EXIT_BAD_SPEC, EXIT_CANCELLED,
                                    EXIT_MISSING_DEPENDENCY, EXIT_OK,
                                    EXIT_OOM, EXIT_UNEXPECTED, JsonlReporter)

#: Set by SIGTERM. The trainer sees it through `report.should_stop()` and is
#: expected to break out of its fit loop at the next checkpoint.
_STOP = {"requested": False}

PREDICTIONS_FILE = "predictions.jsonl"


def _install_signal_handlers() -> None:
    def handle(signum, frame):  # noqa: ARG001
        _STOP["requested"] = True

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, handle)
        except (ValueError, OSError):
            # No signal handling off the main thread; cancellation then falls
            # back to SIGKILL, which is why the parent has a grace period.
            pass


def _apply_limits(spec: TrainingSpec, report: JsonlReporter) -> None:
    """Best-effort resource caps inside the child.

    RAM is capped here rather than in the parent because the parent cannot
    limit a process it did not allocate for. Wall clock is the parent's job:
    a child wedged before it allocates anything would never hit an address
    limit.
    """
    limits = spec.limits

    if limits.num_threads:
        for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS",
                    "OPENBLAS_NUM_THREADS"):
            os.environ.setdefault(var, str(limits.num_threads))

    if limits.max_ram_mb:
        try:
            import resource
            soft = limits.max_ram_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (soft, soft))
            report.log("info", "Address space capped at %d MB"
                       % limits.max_ram_mb)
        except Exception as exc:  # noqa: BLE001
            report.log("warning", "Could not apply a memory limit: %s" % exc)


def _load_trainer(name: str, report: JsonlReporter):
    """Import the trainer for real.

    This is the authoritative extras gate. The parent's ``available()`` check
    is advisory -- it exists to grey out a button and is forbidden from
    importing anything heavy -- so the real answer only arrives here, on the
    far side of the process boundary.
    """
    from potato.training.registry import get_trainer_class

    try:
        return get_trainer_class(name)()
    except ImportError as exc:
        hint = ""
        try:
            from potato.training.registry import trainer_info
            info = trainer_info(name)
            hint = info.install_hint if info else ""
        except Exception:
            pass
        report.error("missing_dependency",
                     "Trainer %r could not be imported: %s" % (name, exc),
                     install_hint=hint)
        raise SystemExit(EXIT_MISSING_DEPENDENCY)
    except KeyError as exc:
        report.error("unknown_trainer", str(exc))
        raise SystemExit(EXIT_BAD_SPEC)


def _predict_items(bundle: BundleRef, splits: List[str]) -> List[PredictItem]:
    """Items to predict on, drawn from the named splits.

    Never the train split. Predicting onto data the model was fitted on
    produces a confident, meaningless prelabel, and if an annotator accepts it
    the error is laundered into the next round's training set. The parent
    enforces this too, against the run ledger; doing it in both places means
    neither one alone has to be right.
    """
    items = []
    for split in splits:
        if split == "train":
            continue
        for row in bundle.read_split(split):
            items.append(PredictItem(
                instance_id=row.get("instance_id", ""),
                text=row.get("text", ""),
                media=(bundle.resolve_media(row["media"])
                       if row.get("media") else None),
                data=row))
    return items


def run(spec: TrainingSpec, report: JsonlReporter) -> int:
    """Fit, predict, and report. Returns a process exit code."""
    report.status("running", "loading bundle")

    try:
        bundle = BundleRef.load(spec.bundle_dir)
    except Exception as exc:
        report.error("bad_bundle", str(exc))
        return EXIT_BAD_SPEC

    trainer = _load_trainer(spec.trainer, report)
    _apply_limits(spec, report)

    problems = trainer.validate(spec, bundle)
    if problems:
        report.error("validation_failed", "; ".join(problems))
        return EXIT_BAD_SPEC

    os.makedirs(spec.workdir, exist_ok=True)

    try:
        result = trainer.fit(spec, bundle, report)
    except MissingDependency as exc:
        report.error("missing_dependency", str(exc),
                     install_hint=exc.install_hint)
        return EXIT_MISSING_DEPENDENCY
    except MemoryError:
        report.error("out_of_memory",
                     "The trainer ran out of memory. Try a smaller batch "
                     "size, a smaller model, or fewer items.")
        return EXIT_OOM
    except TrainerError as exc:
        if _STOP["requested"]:
            report.status("cancelled", str(exc))
            return EXIT_CANCELLED
        report.error("fit_failed", str(exc))
        return EXIT_UNEXPECTED
    except Exception as exc:  # noqa: BLE001 - the boundary
        if _is_cuda_oom(exc):
            report.error("out_of_memory",
                         "The GPU ran out of memory: %s. Try a smaller batch "
                         "size or a smaller model." % exc)
            return EXIT_OOM
        report.error("fit_failed", "%s: %s" % (type(exc).__name__, exc))
        report.log("error", traceback.format_exc()[-4000:])
        return EXIT_UNEXPECTED

    if _STOP["requested"]:
        report.status("cancelled", "stopped after fitting")
        return EXIT_CANCELLED

    for path in result.artifact_paths:
        full = os.path.join(spec.workdir, path)
        size = os.path.getsize(full) if os.path.isfile(full) else None
        report.artifact(path, size)

    predictions_path = ""
    n_predictions = 0
    try:
        report.status("evaluating", "predicting on held-out items")
        items = _predict_items(bundle, ["val", "test"])
        if items:
            predictions_path = os.path.join(spec.workdir, PREDICTIONS_FILE)
            with open(predictions_path, "w") as fh:
                for record in trainer.predict(spec, spec.workdir, items,
                                              report):
                    fh.write(json.dumps(record.to_dict(),
                                        ensure_ascii=False) + "\n")
                    n_predictions += 1
            report.artifact(PREDICTIONS_FILE,
                            os.path.getsize(predictions_path))
    except Exception as exc:  # noqa: BLE001
        # A failed prediction pass does not invalidate the model that was
        # already fitted and written. Say so and finish.
        report.log("warning", "Prediction pass failed: %s" % exc)
        predictions_path = ""

    metrics = dict(result.metrics)
    try:
        extra = trainer.evaluate(spec, spec.workdir, bundle, "val", report)
        for name, value in (extra or {}).items():
            metrics[name] = value
            report.metric("val", name, value)
    except Exception as exc:  # noqa: BLE001
        report.log("warning", "Evaluation failed: %s" % exc)

    report.result("success", model_version=result.model_version,
                  metrics=metrics, label_order=result.label_order,
                  notes=result.notes,
                  predictions_file=(PREDICTIONS_FILE if predictions_path
                                    else ""),
                  n_predictions=n_predictions)
    return EXIT_OK


def _is_cuda_oom(exc: BaseException) -> bool:
    """Whether an exception is a GPU out-of-memory, without importing torch."""
    name = type(exc).__name__
    if name in ("OutOfMemoryError", "CudaOutOfMemoryError"):
        return True
    return "out of memory" in str(exc).lower()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m potato.training.worker",
        description="Run one Potato training job from a spec file.")
    parser.add_argument("--spec", required=True,
                        help="Path to the run's spec.json")
    args = parser.parse_args(argv)

    _install_signal_handlers()
    report = JsonlReporter(should_stop=lambda: _STOP["requested"])

    try:
        spec = TrainingSpec.read(args.spec)
    except Exception as exc:
        report.error("bad_spec", "Could not read %s: %s" % (args.spec, exc))
        return EXIT_BAD_SPEC

    try:
        return run(spec, report)
    except SystemExit as exc:
        return int(exc.code or 0)
    except KeyboardInterrupt:
        report.status("cancelled", "interrupted")
        return EXIT_CANCELLED


if __name__ == "__main__":
    sys.exit(main())

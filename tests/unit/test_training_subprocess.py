"""The training subprocess and the event protocol.

The subprocess exists for the failure cases, so those are what this file is
mostly about: a trainer that raises, one that gets cancelled, one that is
SIGKILLed by the OOM killer, and one whose dependencies are not installed.
Each has to arrive at the admin page as a specific, actionable message rather
than as a hung "running" state.
"""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import types

import pytest

from potato.training import registry, store
from potato.training.base import (BundleRef, FitResult, PredictItem,
                                  PredictionRecord, ProgressReporter, Trainer,
                                  TrainingSpec)
from potato.training.dataset import build_bundle, schema_specs_from_config
from potato.training.events import (EXIT_BAD_SPEC, EXIT_CANCELLED,
                                    EXIT_MISSING_DEPENDENCY, EXIT_OK,
                                    CollectingReporter, JsonlReporter, event,
                                    parse_line)

POS = ["this movie was great and I loved it", "a wonderful film, excellent",
       "so good, I enjoyed the movie", "great work, wonderful and charming",
       "I loved this excellent film", "a delight from start to finish"]
NEG = ["this movie was terrible and I hated it", "an awful film, really poor",
       "so bad, I disliked the movie", "poor work, awful and tedious",
       "I hated this dreadful film", "a chore from start to finish"]


def _project(tmp):
    config = {"task_dir": tmp, "annotation_task_name": "t",
              "output_annotation_dir": "annotation_output",
              "item_properties": {"id_key": "id", "text_key": "text"},
              "annotation_schemes": [
                  {"annotation_type": "radio", "name": "sentiment",
                   "description": "s", "labels": ["positive", "negative"]}]}
    items, annotations = {}, []
    for n, text in enumerate(POS + NEG):
        iid = "i%02d" % n
        items[iid] = {"id": iid, "text": text}
        label = "positive" if n < len(POS) else "negative"
        for user in ("alice", "bob"):
            annotations.append({"instance_id": iid, "user_id": user,
                                "labels": {"sentiment": {label: True}}})
    context = types.SimpleNamespace(
        config=config, annotations=annotations, items=items,
        schemas=config["annotation_schemes"], output_dir=tmp,
        phase_responses={})
    return config, context


@pytest.fixture
def built():
    """A tmpdir with a built bundle and a spec, ready to run."""
    with tempfile.TemporaryDirectory() as tmp:
        config, context = _project(tmp)
        run_dir = os.path.join(tmp, "run")
        bundle_dir = os.path.join(run_dir, "bundle")
        workdir = os.path.join(run_dir, "artifacts")
        os.makedirs(workdir, exist_ok=True)

        bundle, stats, split_ids = build_bundle(context, bundle_dir,
                                                ["sentiment"], split_seed=5)
        spec = TrainingSpec(
            run_id="r1", trainer="sklearn-text",
            schemas=schema_specs_from_config(config, ["sentiment"],
                                             bundle.manifest["labels"]),
            bundle_dir=bundle_dir, workdir=workdir,
            params={"min_instances": 4})
        spec_path = os.path.join(run_dir, "spec.json")
        spec.write(spec_path)
        yield types.SimpleNamespace(tmp=tmp, config=config, context=context,
                                    bundle=bundle, spec=spec,
                                    spec_path=spec_path, run_dir=run_dir,
                                    workdir=workdir, split_ids=split_ids)


def _worker(spec_path, cwd, timeout=300, env=None):
    environ = dict(os.environ)
    environ.update(env or {})
    return subprocess.run(
        [sys.executable, "-m", "potato.training.worker", "--spec", spec_path],
        capture_output=True, text=True, cwd=cwd, timeout=timeout, env=environ)


def _events(stdout):
    return [e for e in (parse_line(line) for line in stdout.splitlines())
            if e is not None]


class TestEventProtocol:
    def test_events_carry_a_version(self):
        assert event("status", state="running")["v"] == 1

    def test_an_unknown_event_type_is_refused(self):
        with pytest.raises(ValueError, match="Unknown event type"):
            event("nonsense")

    @pytest.mark.parametrize("line", [
        "", "   ", "not json at all", "Downloading: 42%",
        '{"not": "an event"}', '{"event": "nope"}', "[1,2,3]",
    ])
    def test_non_events_parse_to_none(self, line):
        """A third-party progress bar must not be mistaken for protocol."""
        assert parse_line(line) is None

    def test_a_real_event_parses(self):
        line = json.dumps(event("metric", split="val", name="f1", value=0.7))
        assert parse_line(line)["name"] == "f1"

    def test_the_reporter_throttles_progress(self):
        import io
        stream = io.StringIO()
        reporter = JsonlReporter(stream=stream, min_interval_s=10.0)
        for i in range(50):
            reporter.progress("fit", i, 100)
        # Only the first gets through; the rest are inside the interval.
        assert len(_events(stream.getvalue())) == 1

    def test_the_final_progress_is_never_throttled(self):
        import io
        stream = io.StringIO()
        reporter = JsonlReporter(stream=stream, min_interval_s=10.0)
        reporter.progress("fit", 1, 100)
        reporter.progress("fit", 100, 100)
        events = _events(stream.getvalue())
        assert events[-1]["current"] == 100

    def test_collecting_reporter_groups_by_type(self):
        reporter = CollectingReporter()
        reporter.status("running")
        reporter.log("info", "hello")
        reporter.log("warning", "careful")
        assert len(reporter.of_type("log")) == 2
        assert len(reporter.of_type("status")) == 1


class TestWorkerHappyPath:
    def test_a_run_succeeds_and_reports_a_result(self, built):
        result = _worker(built.spec_path, built.run_dir)
        assert result.returncode == EXIT_OK, result.stderr[-2000:]

        events = _events(result.stdout)
        kinds = [e["event"] for e in events]
        assert "status" in kinds and "artifact" in kinds and "result" in kinds

        final = [e for e in events if e["event"] == "result"][0]
        assert final["status"] == "success"
        assert final["model_version"]

    def test_the_model_and_card_are_written(self, built):
        _worker(built.spec_path, built.run_dir)
        assert os.path.isfile(os.path.join(built.workdir, "model.pkl"))
        assert os.path.isfile(os.path.join(built.workdir, "model_card.json"))

    def test_predictions_go_to_a_file_not_the_event_stream(self, built):
        """A large run would otherwise push megabytes through the pipe."""
        result = _worker(built.spec_path, built.run_dir)
        events = _events(result.stdout)

        assert not any("payload" in e for e in events)
        path = os.path.join(built.workdir, "predictions.jsonl")
        assert os.path.isfile(path)
        with open(path) as fh:
            records = [json.loads(line) for line in fh if line.strip()]
        assert records and "payload" in records[0]

    def test_predictions_never_cover_the_train_split(self, built):
        """The leak guard, enforced in the child as well as the parent."""
        _worker(built.spec_path, built.run_dir)
        with open(os.path.join(built.workdir, "predictions.jsonl")) as fh:
            predicted = {json.loads(line)["instance_id"]
                         for line in fh if line.strip()}
        assert not (predicted & set(built.split_ids["train"]))


class TestWorkerFailures:
    def test_a_bad_spec_path_exits_cleanly(self, built):
        result = _worker(os.path.join(built.tmp, "nope.json"), built.run_dir)
        assert result.returncode == EXIT_BAD_SPEC
        errors = [e for e in _events(result.stdout) if e["event"] == "error"]
        assert errors and errors[0]["code"] == "bad_spec"

    def test_a_missing_bundle_is_reported(self, built):
        spec = TrainingSpec.read(built.spec_path)
        broken = TrainingSpec(
            run_id=spec.run_id, trainer=spec.trainer, schemas=spec.schemas,
            bundle_dir=os.path.join(built.tmp, "no-bundle"),
            workdir=spec.workdir, params=spec.params)
        path = os.path.join(built.tmp, "broken.json")
        broken.write(path)

        result = _worker(path, built.run_dir)
        assert result.returncode == EXIT_BAD_SPEC
        errors = [e for e in _events(result.stdout) if e["event"] == "error"]
        assert errors[0]["code"] == "bad_bundle"

    def test_an_unknown_trainer_is_reported(self, built):
        spec = TrainingSpec.read(built.spec_path)
        broken = TrainingSpec(
            run_id=spec.run_id, trainer="no-such-trainer", schemas=spec.schemas,
            bundle_dir=spec.bundle_dir, workdir=spec.workdir)
        path = os.path.join(built.tmp, "unknown.json")
        broken.write(path)

        result = _worker(path, built.run_dir)
        assert result.returncode == EXIT_BAD_SPEC
        errors = [e for e in _events(result.stdout) if e["event"] == "error"]
        assert errors[0]["code"] == "unknown_trainer"

    def test_validation_failure_names_the_reason(self, built):
        spec = TrainingSpec.read(built.spec_path)
        strict = TrainingSpec(
            run_id=spec.run_id, trainer=spec.trainer, schemas=spec.schemas,
            bundle_dir=spec.bundle_dir, workdir=spec.workdir,
            params={"min_instances": 100000})
        path = os.path.join(built.tmp, "strict.json")
        strict.write(path)

        result = _worker(path, built.run_dir)
        assert result.returncode == EXIT_BAD_SPEC
        errors = [e for e in _events(result.stdout) if e["event"] == "error"]
        assert "at least" in errors[0]["message"]

    def test_no_result_event_means_failure_whatever_the_code(self):
        """Exit 0 without a result is not success."""
        from potato.training.manager import TrainingManager

        manager = TrainingManager({"task_dir": ".", "model_training": {}})
        run = store.TrainingRun(run_id="r", trainer="t")
        recorded = {}
        manager._finish = lambda r, status, **kw: recorded.update(
            {"status": status, **kw})

        manager._record_completion(run, 0, None, None, {})
        assert recorded["status"] == "error"
        assert recorded["error_code"] == "no_result"

    def test_sigkill_is_reported_as_out_of_memory(self):
        """returncode -9 is the OOM killer, and is why this runs out of process."""
        import signal

        from potato.training.manager import TrainingManager

        manager = TrainingManager({"task_dir": ".", "model_training": {}})
        run = store.TrainingRun(run_id="r", trainer="t")
        recorded = {}
        manager._finish = lambda r, status, **kw: recorded.update(
            {"status": status, **kw})

        manager._record_completion(run, -signal.SIGKILL, None, None, {})
        assert recorded["status"] == "error"
        assert recorded["error_code"] == "killed"
        assert "memory" in recorded["error"].lower()

    def test_an_install_hint_reaches_the_error(self):
        from potato.training.manager import TrainingManager

        manager = TrainingManager({"task_dir": ".", "model_training": {}})
        run = store.TrainingRun(run_id="r", trainer="t")
        recorded = {}
        manager._finish = lambda r, status, **kw: recorded.update(
            {"status": status, **kw})

        manager._record_completion(
            run, EXIT_MISSING_DEPENDENCY, None,
            {"event": "error", "code": "missing_dependency",
             "message": "no torch",
             "install_hint": 'pip install "potato-annotation[train-text]"'},
            {})
        assert "train-text" in recorded["error"]


class TestGarbageOnStdout:
    def test_stray_output_does_not_break_a_run(self, built):
        """A library that prints to stdout must not fail an otherwise fine run."""
        noisy = os.path.join(built.tmp, "noisy.py")
        with open(noisy, "w") as fh:
            fh.write(textwrap.dedent("""
                import sys
                print("Downloading model: 42%")
                print("{not json}")
                sys.argv = ["worker", "--spec", sys.argv[1]]
                from potato.training.worker import main
                sys.exit(main())
            """))

        result = subprocess.run(
            [sys.executable, noisy, built.spec_path],
            capture_output=True, text=True, cwd=built.run_dir, timeout=300)

        assert result.returncode == EXIT_OK, result.stderr[-2000:]
        finals = [e for e in _events(result.stdout) if e["event"] == "result"]
        assert finals and finals[0]["status"] == "success"


class TestCancellation:
    def test_sigterm_stops_a_slow_trainer(self, built):
        """The trainer polls should_stop() and leaves with the cancelled code."""
        slow = os.path.join(built.tmp, "slow_trainer.py")
        with open(slow, "w") as fh:
            fh.write(textwrap.dedent('''
                import time
                from potato.training.base import FitResult, Trainer

                class SlowTrainer(Trainer):
                    name = "slow-for-test"
                    kinds = ("nominal",)

                    def fit(self, spec, bundle, report):
                        for i in range(600):
                            if report.should_stop():
                                from potato.training.base import TrainerError
                                raise TrainerError("stopped")
                            report.progress("fit", i, 600)
                            time.sleep(0.05)
                        return FitResult(model_version="never")

                    def predict(self, spec, artifact_dir, items, report):
                        return iter(())
            '''))

        runner = os.path.join(built.tmp, "run_slow.py")
        with open(runner, "w") as fh:
            fh.write(textwrap.dedent("""
                import sys
                sys.path.insert(0, %r)
                from potato.training import registry
                import slow_trainer
                registry.register(slow_trainer.SlowTrainer)
                sys.argv = ["worker", "--spec", sys.argv[1]]
                from potato.training.worker import main
                sys.exit(main())
            """ % built.tmp))

        spec = TrainingSpec.read(built.spec_path)
        slow_spec = TrainingSpec(
            run_id=spec.run_id, trainer="slow-for-test", schemas=spec.schemas,
            bundle_dir=spec.bundle_dir, workdir=spec.workdir)
        slow_path = os.path.join(built.tmp, "slow.json")
        slow_spec.write(slow_path)

        process = subprocess.Popen(
            [sys.executable, runner, slow_path], stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, cwd=built.run_dir,
            start_new_session=True)
        try:
            time.sleep(3.0)
            process.terminate()
            stdout, stderr = process.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            process.kill()
            pytest.fail("the trainer ignored SIGTERM")

        assert process.returncode == EXIT_CANCELLED, stderr[-2000:]
        statuses = [e for e in _events(stdout)
                    if e["event"] == "status" and e.get("state") == "cancelled"]
        assert statuses, "no cancelled status was reported"


class TestWorkerIsolation:
    def test_the_worker_does_not_import_the_server(self):
        """
        The whole reason training is a subprocess. If the child pulls in the
        Flask app, the state managers come with it and the isolation is
        cosmetic.
        """
        result = subprocess.run(
            [sys.executable, "-c",
             "import sys; import potato.training.worker; "
             "bad=[m for m in ('potato.flask_server','potato.routes',"
             "'potato.item_state_management','flask') if m in sys.modules]; "
             "print(','.join(bad))"],
            capture_output=True, text=True, timeout=180)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "", (
            "the training worker imported: %s" % result.stdout.strip())

    def test_the_worker_has_a_help_screen(self):
        result = subprocess.run(
            [sys.executable, "-m", "potato.training.worker", "--help"],
            capture_output=True, text=True, timeout=180)
        assert result.returncode == 0
        assert "--spec" in result.stdout


class TestManagerStatus:
    def test_an_idle_manager_reports_idle(self):
        from potato.training.manager import TrainingManager
        manager = TrainingManager({"task_dir": "."})
        assert manager.status()["state"] == "idle"
        assert manager.is_running() is False

    def test_status_returns_a_copy(self):
        from potato.training.manager import TrainingManager
        manager = TrainingManager({"task_dir": "."})
        manager.status()["state"] = "tampered"
        assert manager.status()["state"] == "idle"

    def test_a_second_run_is_refused_not_queued(self):
        from potato.training.manager import TrainingManager
        manager = TrainingManager({"task_dir": "."})
        manager._set(state="running", run_id="first")

        outcome = manager.start_run("sklearn-text", ["sentiment"])
        assert outcome["started"] is False
        assert "already in progress" in outcome["error"]

    def test_starting_with_no_schema_is_refused(self):
        from potato.training.manager import TrainingManager
        manager = TrainingManager({"task_dir": "."})
        assert manager.start_run("sklearn-text", [])["started"] is False

    def test_cancelling_nothing_says_so(self):
        from potato.training.manager import TrainingManager
        manager = TrainingManager({"task_dir": "."})
        assert manager.cancel()["cancelled"] is False


class TestManagerEndToEnd:
    def test_a_full_run_through_the_manager(self, built):
        from potato.training.manager import TrainingManager

        config = dict(built.config)
        config["model_training"] = {"enabled": True}
        manager = TrainingManager(config)
        # The manager builds its own bundle from the live context.
        manager._context_from_live_state = lambda: built.context

        outcome = manager.start_run("sklearn-text", ["sentiment"],
                                    params={"min_instances": 4})
        assert outcome["started"] is True

        deadline = time.time() + 180
        while manager.is_running() and time.time() < deadline:
            time.sleep(0.2)

        status = manager.status()
        assert status["state"] == "success", status

        run = store.load_run(config, outcome["run_id"])
        assert run.status == "success"
        assert run.model_version
        assert run.n_train > 0
        assert store.training_split_ids(config, run.run_id)

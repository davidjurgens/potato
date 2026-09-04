"""The training run ledger.

What this guards is that runs are actually recorded. The thing it replaced --
``DatabaseStateManager`` -- had a method for every one of these operations and
all of them were ``pass``, so it logged "initialized successfully" and then
lost every metric it was handed. Tests that only asserted no exception was
raised would have passed against it.
"""

import os
import tempfile

import pytest

from potato.training import store


@pytest.fixture
def config():
    with tempfile.TemporaryDirectory() as tmp:
        yield {"task_dir": tmp, "annotation_task_name": "test_project"}


def _run(**kw):
    defaults = dict(run_id=store.new_run_id(), trainer="sklearn-text",
                    schema_names=["sentiment"], status="queued")
    defaults.update(kw)
    return store.TrainingRun(**defaults)


class TestRunIds:
    def test_ids_are_unique(self):
        assert len({store.new_run_id() for _ in range(200)}) == 200

    def test_ids_sort_chronologically(self):
        # Timestamp-first, so a directory listing is in run order.
        first = store.new_run_id()
        second = store.new_run_id()
        assert first[:15] <= second[:15]


class TestRunRoundTrip:
    def test_a_run_survives_a_round_trip(self, config):
        run = _run(status="success", n_train=40, n_val=10, split_seed=7,
                   metrics={"macro_f1": 0.71}, params={"C": 1.0},
                   model_version="sklearn-text-sentiment-abc")
        store.record_run(config, run)

        loaded = store.load_run(config, run.run_id)
        assert loaded is not None
        assert loaded.trainer == "sklearn-text"
        assert loaded.schema_names == ["sentiment"]
        assert loaded.metrics == {"macro_f1": 0.71}
        assert loaded.params == {"C": 1.0}
        assert loaded.n_train == 40
        assert loaded.split_seed == 7

    def test_recording_twice_updates_rather_than_duplicates(self, config):
        run = _run(status="running")
        store.record_run(config, run)
        run.status = "success"
        run.metrics = {"accuracy": 0.9}
        store.record_run(config, run)

        assert len(store.list_runs(config)) == 1
        assert store.load_run(config, run.run_id).status == "success"

    def test_unknown_status_is_refused(self, config):
        with pytest.raises(ValueError, match="Unknown run status"):
            store.record_run(config, _run(status="finished-ish"))

    def test_missing_run_is_none_not_an_error(self, config):
        assert store.load_run(config, "no-such-run") is None

    def test_duration_is_none_until_finished(self, config):
        run = _run(started_at=100.0)
        assert run.duration is None
        run.finished_at = 104.5
        assert run.duration == pytest.approx(4.5)

    def test_projects_do_not_see_each_other(self, config):
        other = dict(config, annotation_task_name="different_project")
        store.record_run(config, _run())
        assert store.list_runs(config) != []
        assert store.list_runs(other) == []


class TestListingAndLookup:
    def test_runs_come_back_newest_first(self, config):
        for i in range(3):
            store.record_run(config, _run(created_at=1000.0 + i))
        created = [r.created_at for r in store.list_runs(config)]
        assert created == sorted(created, reverse=True)

    def test_latest_run_filters_by_schema(self, config):
        store.record_run(config, _run(status="success", created_at=1.0,
                                      schema_names=["topic"]))
        wanted = _run(status="success", created_at=2.0,
                      schema_names=["sentiment"])
        store.record_run(config, wanted)

        assert store.latest_run(config, schema_name="sentiment").run_id == wanted.run_id
        assert store.latest_run(config, schema_name="nothing") is None

    def test_latest_run_ignores_failures(self, config):
        good = _run(status="success", created_at=1.0)
        store.record_run(config, good)
        store.record_run(config, _run(status="error", created_at=2.0))
        # A newer failed run must not shadow the model that actually works.
        assert store.latest_run(config).run_id == good.run_id


class TestSplitRecording:
    def test_splits_round_trip(self, config):
        run = _run()
        store.record_run(config, run)
        written = store.record_run_items(
            config, run.run_id, {"train": ["a", "b"], "val": ["c"]})

        assert written == 3
        assert store.run_item_splits(config, run.run_id) == {
            "a": "train", "b": "train", "c": "val"}

    def test_training_split_ids_returns_only_train(self, config):
        run = _run()
        store.record_run(config, run)
        store.record_run_items(config, run.run_id,
                               {"train": ["a", "b"], "val": ["c"],
                                "test": ["d"]})
        assert store.training_split_ids(config, run.run_id) == {"a", "b"}

    def test_empty_splits_write_nothing(self, config):
        assert store.record_run_items(config, "r", {}) == 0


class TestPredictions:
    def test_predictions_round_trip(self, config):
        store.record_predictions(config, "run-1", [
            ("i1", "sentiment", {"label": "pos", "confidence": 0.9}, 0.9),
            ("i2", "sentiment", {"label": "neg", "confidence": 0.4}, 0.4),
        ])
        loaded = {p["instance_id"]: p for p in store.load_predictions(config)}
        assert loaded["i1"]["payload"]["label"] == "pos"
        assert loaded["i2"]["confidence"] == pytest.approx(0.4)
        assert loaded["i1"]["run_id"] == "run-1"

    def test_a_newer_run_supersedes_an_older_prediction(self, config):
        store.record_predictions(config, "run-1",
                                 [("i1", "sentiment", {"label": "pos"}, 0.9)])
        store.record_predictions(config, "run-2",
                                 [("i1", "sentiment", {"label": "neg"}, 0.8)])

        preds = store.load_predictions(config)
        assert len(preds) == 1, "one prediction per (instance, schema)"
        assert preds[0]["run_id"] == "run-2"
        assert preds[0]["payload"]["label"] == "neg"

    def test_predictions_filter_by_run(self, config):
        store.record_predictions(config, "run-1",
                                 [("i1", "s", {"label": "a"}, 0.5)])
        store.record_predictions(config, "run-2",
                                 [("i2", "s", {"label": "b"}, 0.5)])
        assert len(store.load_predictions(config, run_id="run-1")) == 1

    def test_per_instance_lookup(self, config):
        store.record_predictions(config, "r", [
            ("i1", "sentiment", {"label": "pos"}, 0.9),
            ("i1", "topic", {"label": "sports"}, 0.7),
        ])
        assert store.predictions_for_instance(config, "i1") == {
            "sentiment": {"label": "pos"}, "topic": {"label": "sports"}}

    def test_retraction(self, config):
        store.record_predictions(config, "r", [("i1", "s", {"l": 1}, 0.5)])
        assert store.delete_predictions_for_run(config, "r") == 1
        assert store.load_predictions(config) == []


class TestRetention:
    def test_nothing_is_pruned_below_the_threshold(self, config):
        for i in range(3):
            store.record_run(config, _run(status="success", created_at=i))
        assert store.prune_runs(config, retain=5) == []

    def test_old_runs_are_pruned(self, config):
        runs = [_run(status="success", created_at=float(i)) for i in range(6)]
        for run in runs:
            store.record_run(config, run)

        deleted = store.prune_runs(config, retain=2)
        assert len(deleted) == 4
        assert len(store.list_runs(config)) == 2

    def test_a_run_with_live_predictions_is_never_pruned(self, config):
        old = _run(status="success", created_at=0.0)
        store.record_run(config, old)
        for i in range(1, 6):
            store.record_run(config, _run(status="success", created_at=float(i)))

        store.record_predictions(config, old.run_id,
                                 [("i1", "s", {"label": "x"}, 0.9)])

        # Deleting it would strand that prediction with a run id resolving to
        # nothing, which is the provenance question the ledger exists to
        # answer.
        deleted = store.prune_runs(config, retain=1)
        assert old.run_id not in deleted
        assert store.load_run(config, old.run_id) is not None

    def test_an_in_flight_run_is_never_pruned(self, config):
        running = _run(status="running", created_at=0.0)
        store.record_run(config, running)
        for i in range(1, 6):
            store.record_run(config, _run(status="success", created_at=float(i)))

        assert running.run_id not in store.prune_runs(config, retain=1)

    def test_deleting_a_run_takes_its_split_rows(self, config):
        run = _run(status="success")
        store.record_run(config, run)
        store.record_run_items(config, run.run_id, {"train": ["a"]})
        store.delete_run(config, run.run_id)
        assert store.run_item_splits(config, run.run_id) == {}


class TestBootWeight:
    def test_the_store_imports_no_ml_stack(self):
        """The ledger is on the boot path; it must stay stdlib + sqlite3."""
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-c",
             "import sys; import potato.training.store as s; "
             "bad = [m for m in ('torch', 'sklearn', 'transformers', "
             "'sentence_transformers') if m in sys.modules]; "
             "print(','.join(bad))"],
            capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "", (
            "potato.training.store pulled in: %s" % result.stdout.strip())

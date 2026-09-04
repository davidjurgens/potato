"""The trainer registry and the bundle builder.

The bundle is the contract between Potato and every trainer, local or remote,
so what matters here is that it is self-describing and that split membership is
stable. A bundle that reshuffles its splits between runs makes every metric
after the first one a measure of memorization.
"""

import json
import os
import subprocess
import sys
import tempfile
import types

import pytest

from potato.training import registry
from potato.training.base import (BundleRef, PredictItem, ProgressReporter,
                                  SchemaSpec, Trainer, TrainingSpec)
from potato.training.dataset import (build_bundle, detect_modality,
                                     schema_specs_from_config)

POS = ["this movie was great and I loved it", "a wonderful film, excellent",
       "so good, I enjoyed the movie", "great work, wonderful and charming",
       "I loved this excellent film", "a delight from start to finish"]
NEG = ["this movie was terrible and I hated it", "an awful film, really poor",
       "so bad, I disliked the movie", "poor work, awful and tedious",
       "I hated this dreadful film", "a chore from start to finish"]


def _config(tmp, annotation_type="radio", extra_scheme=None):
    schemes = [{"annotation_type": annotation_type, "name": "sentiment",
                "description": "How positive?",
                "labels": ["positive", "negative"]}]
    if extra_scheme:
        schemes.append(extra_scheme)
    return {"task_dir": tmp, "annotation_task_name": "test",
            "item_properties": {"id_key": "id", "text_key": "text"},
            "annotation_schemes": schemes}


def _context(tmp, config, n_users=2):
    items, annotations = {}, []
    for n, text in enumerate(POS + NEG):
        iid = "i%02d" % n
        items[iid] = {"id": iid, "text": text}
        label = "positive" if n < len(POS) else "negative"
        for user in ["alice", "bob", "carol"][:n_users]:
            annotations.append({"instance_id": iid, "user_id": user,
                                "labels": {"sentiment": {label: True}}})
    return types.SimpleNamespace(
        config=config, annotations=annotations, items=items,
        schemas=config["annotation_schemes"], output_dir=tmp,
        phase_responses={})


@pytest.fixture
def project():
    with tempfile.TemporaryDirectory() as tmp:
        config = _config(tmp)
        yield tmp, config, _context(tmp, config)


class TestRegistry:
    def test_the_builtin_trainer_is_registered(self):
        assert "sklearn-text" in registry.trainer_names()

    def test_listing_trainers_reports_availability(self):
        entries = {e["name"]: e for e in registry.list_trainers()}
        assert entries["sklearn-text"]["available"] is True
        assert entries["sklearn-text"]["kinds"]

    def test_an_unknown_trainer_names_the_known_ones(self):
        with pytest.raises(KeyError, match="sklearn-text"):
            registry.get_trainer_class("no-such-trainer")

    def test_capability_matching_uses_schema_kind(self):
        radio = {"annotation_type": "radio", "name": "s",
                 "labels": ["a", "b"]}
        matches = [t.name for t in registry.trainers_for_schema(radio)]
        assert "sklearn-text" in matches

    def test_free_text_has_no_trainer(self):
        """TEXT has no automatic target, so offering a trainer would lie."""
        assert registry.trainers_for_schema(
            {"annotation_type": "textbox", "name": "notes"}) == []

    def test_an_unknown_type_has_no_trainer(self):
        assert registry.trainers_for_schema(
            {"annotation_type": "not_a_real_type", "name": "x"}) == []

    def test_modality_filters_matches(self):
        radio = {"annotation_type": "radio", "name": "s"}
        assert registry.trainers_for_schema(radio, modality="text")
        assert not registry.trainers_for_schema(radio, modality="point_cloud")

    def test_register_and_unregister_round_trip(self):
        class Fake(Trainer):
            name = "fake-for-test"
            kinds = ("nominal",)

            def fit(self, spec, bundle, report):
                raise NotImplementedError

            def predict(self, spec, artifact_dir, items, report):
                raise NotImplementedError

        registry.register(Fake)
        try:
            assert "fake-for-test" in registry.trainer_names()
            assert registry.get_trainer_class("fake-for-test") is Fake
        finally:
            registry.unregister("fake-for-test")
        assert "fake-for-test" not in registry.trainer_names()


class TestBundleBuild:
    def test_a_bundle_has_a_manifest_and_splits(self, project):
        tmp, config, ctx = project
        dest = os.path.join(tmp, "bundle")
        bundle, stats, split_ids = build_bundle(ctx, dest, ["sentiment"],
                                                split_seed=1)

        assert os.path.isfile(os.path.join(dest, "manifest.json"))
        assert sum(stats.splits.values()) == stats.n_annotated
        assert bundle.labels("sentiment") == ["negative", "positive"]
        assert set(split_ids) <= {"train", "val", "test"}

    def test_split_ids_match_the_written_rows(self, project):
        tmp, config, ctx = project
        bundle, _, split_ids = build_bundle(
            ctx, os.path.join(tmp, "b"), ["sentiment"], split_seed=1)

        for split, ids in split_ids.items():
            written = [r["instance_id"] for r in bundle.read_split(split)]
            assert written == ids

    def test_no_instance_appears_in_two_splits(self, project):
        tmp, config, ctx = project
        _, _, split_ids = build_bundle(ctx, os.path.join(tmp, "b"),
                                       ["sentiment"], split_seed=3)
        seen = [iid for ids in split_ids.values() for iid in ids]
        assert len(seen) == len(set(seen))

    def test_splits_are_stable_across_builds(self, project):
        """The whole point: round two must hold out what round one held out."""
        tmp, config, ctx = project
        _, _, first = build_bundle(ctx, os.path.join(tmp, "b1"),
                                   ["sentiment"], split_seed=99)
        _, _, second = build_bundle(ctx, os.path.join(tmp, "b2"),
                                    ["sentiment"], split_seed=99)
        assert first == second

    def test_a_different_seed_gives_a_different_split(self, project):
        tmp, config, ctx = project
        _, _, a = build_bundle(ctx, os.path.join(tmp, "b1"), ["sentiment"],
                               split_seed=1)
        _, _, b = build_bundle(ctx, os.path.join(tmp, "b2"), ["sentiment"],
                               split_seed=2)
        assert a != b

    def test_adding_an_annotation_changes_the_digest(self, project):
        tmp, config, ctx = project
        first, _, _ = build_bundle(ctx, os.path.join(tmp, "b1"),
                                   ["sentiment"], split_seed=1)

        ctx.items["extra"] = {"id": "extra", "text": "a wonderful new film"}
        ctx.annotations.append({"instance_id": "extra", "user_id": "alice",
                                "labels": {"sentiment": {"positive": True}}})
        second, _, _ = build_bundle(ctx, os.path.join(tmp, "b2"),
                                    ["sentiment"], split_seed=1)

        assert first.digest != second.digest

    def test_an_unchanged_rebuild_keeps_the_digest(self, project):
        tmp, config, ctx = project
        first, _, _ = build_bundle(ctx, os.path.join(tmp, "b1"),
                                   ["sentiment"], split_seed=1)
        second, _, _ = build_bundle(ctx, os.path.join(tmp, "b2"),
                                    ["sentiment"], split_seed=1)
        assert first.digest == second.digest

    def test_labels_come_from_the_data_not_the_config(self, project):
        """A declared-but-unused label would be a class nothing can predict."""
        tmp, config, ctx = project
        config["annotation_schemes"][0]["labels"] = [
            "positive", "negative", "never_used"]
        bundle, _, _ = build_bundle(ctx, os.path.join(tmp, "b"), ["sentiment"],
                                    split_seed=1)
        assert "never_used" not in bundle.labels("sentiment")

    def test_a_project_with_no_annotations_says_so(self, project):
        tmp, config, _ = project
        empty = types.SimpleNamespace(
            config=config, annotations=[], items={"i0": {"id": "i0",
                                                         "text": "hi"}},
            schemas=config["annotation_schemes"], output_dir=tmp,
            phase_responses={})
        from potato.training.base import TrainerError
        with pytest.raises(TrainerError, match="No resolved annotations"):
            build_bundle(empty, os.path.join(tmp, "b"), ["sentiment"])

    def test_an_unknown_schema_name_is_refused(self, project):
        tmp, config, ctx = project
        from potato.training.base import TrainerError
        with pytest.raises(TrainerError, match="No annotation scheme"):
            build_bundle(ctx, os.path.join(tmp, "b"), ["not_a_scheme"])

    def test_a_single_annotator_falls_back_to_majority(self, project):
        tmp, config, _ = project
        ctx = _context(tmp, config, n_users=1)
        bundle, stats, _ = build_bundle(ctx, os.path.join(tmp, "b"),
                                        ["sentiment"], split_seed=1)
        assert stats.n_annotated == len(POS) + len(NEG)


class TestMedia:
    def test_media_is_symlinked_not_copied(self):
        """A large corpus must not be duplicated once per retained run."""
        with tempfile.TemporaryDirectory() as tmp:
            media_source = os.path.join(tmp, "images")
            os.makedirs(media_source)

            config = _config(tmp, annotation_type="radio")
            config["annotation_schemes"][0]["source_field"] = "image_url"

            items, annotations = {}, []
            for n in range(8):
                path = os.path.join(media_source, "img%d.png" % n)
                with open(path, "wb") as fh:
                    fh.write(b"\x89PNG" + bytes(64))
                iid = "i%d" % n
                items[iid] = {"id": iid, "text": "", "image_url": path}
                label = "positive" if n < 4 else "negative"
                annotations.append({"instance_id": iid, "user_id": "alice",
                                    "labels": {"sentiment": {label: True}}})

            ctx = types.SimpleNamespace(
                config=config, annotations=annotations, items=items,
                schemas=config["annotation_schemes"], output_dir=tmp,
                phase_responses={})

            dest = os.path.join(tmp, "bundle")
            bundle, stats, _ = build_bundle(ctx, dest, ["sentiment"],
                                            split_seed=1)

            assert stats.n_media_linked == 8
            assert stats.n_media_missing == 0

            linked = []
            for root, _dirs, files in os.walk(bundle.media_dir):
                linked.extend(os.path.join(root, f) for f in files)
            assert linked, "no media landed in the bundle"
            assert all(os.path.islink(p) for p in linked), \
                "media was copied instead of symlinked"

    def test_a_missing_media_file_is_counted_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp)
            config["annotation_schemes"][0]["source_field"] = "image_url"
            items, annotations = {}, []
            for n in range(6):
                iid = "i%d" % n
                items[iid] = {"id": iid, "text": "",
                              "image_url": "/nowhere/img%d.png" % n}
                label = "positive" if n < 3 else "negative"
                annotations.append({"instance_id": iid, "user_id": "alice",
                                    "labels": {"sentiment": {label: True}}})
            ctx = types.SimpleNamespace(
                config=config, annotations=annotations, items=items,
                schemas=config["annotation_schemes"], output_dir=tmp,
                phase_responses={})

            _, stats, _ = build_bundle(ctx, os.path.join(tmp, "b"),
                                       ["sentiment"], split_seed=1)
            assert stats.n_media_missing == 6

    def test_a_remote_url_is_passed_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp)
            config["annotation_schemes"][0]["source_field"] = "image_url"
            items = {"i0": {"id": "i0", "text": "",
                            "image_url": "https://example.invalid/a.png"},
                     "i1": {"id": "i1", "text": "",
                            "image_url": "https://example.invalid/b.png"}}
            annotations = [
                {"instance_id": "i0", "user_id": "a",
                 "labels": {"sentiment": {"positive": True}}},
                {"instance_id": "i1", "user_id": "a",
                 "labels": {"sentiment": {"negative": True}}}]
            ctx = types.SimpleNamespace(
                config=config, annotations=annotations, items=items,
                schemas=config["annotation_schemes"], output_dir=tmp,
                phase_responses={})

            bundle, stats, _ = build_bundle(ctx, os.path.join(tmp, "b"),
                                            ["sentiment"], split_seed=1)
            media = [r.get("media") for split in ("train", "val", "test")
                     for r in bundle.read_split(split)]
            assert any(m and m.startswith("https://") for m in media)


class TestModalityDetection:
    @pytest.mark.parametrize("annotation_type,expected", [
        ("radio", "text"),
        ("image_annotation", "image"),
        ("audio_annotation", "audio"),
        ("video_annotation", "video"),
        ("spatial_annotation", "point_cloud"),
    ])
    def test_modality_follows_the_schema_type(self, annotation_type, expected):
        assert detect_modality([{"annotation_type": annotation_type}]) == expected


class TestBundleRef:
    def test_a_missing_split_is_none_not_an_error(self, project):
        tmp, config, ctx = project
        bundle, _, _ = build_bundle(ctx, os.path.join(tmp, "b"), ["sentiment"],
                                    split_spec={"train": 1.0}, split_seed=1)
        assert bundle.split_path("test") is None
        assert list(bundle.read_split("test")) == []

    def test_loading_a_bundle_from_disk(self, project):
        tmp, config, ctx = project
        dest = os.path.join(tmp, "b")
        build_bundle(ctx, dest, ["sentiment"], split_seed=1)

        reloaded = BundleRef.load(dest)
        assert reloaded.labels("sentiment") == ["negative", "positive"]
        assert reloaded.modality == "text"

    def test_loading_a_directory_with_no_manifest_raises(self):
        from potato.training.base import TrainerError
        with tempfile.TemporaryDirectory() as tmp:
            with pytest.raises(TrainerError, match="No bundle manifest"):
                BundleRef.load(tmp)


class TestSpecSerialization:
    def test_a_spec_round_trips_through_json(self, project):
        tmp, config, _ = project
        spec = TrainingSpec(
            run_id="r1", trainer="sklearn-text",
            schemas=schema_specs_from_config(config, ["sentiment"]),
            bundle_dir="/b", workdir="/w", params={"a": 1}, seed=7)

        path = os.path.join(tmp, "spec.json")
        spec.write(path)
        reloaded = TrainingSpec.read(path)

        assert reloaded.run_id == spec.run_id
        assert reloaded.schemas[0].name == "sentiment"
        assert reloaded.schemas[0].kind == "nominal"
        assert reloaded.params == {"a": 1}
        assert reloaded.seed == 7

    def test_the_spec_carries_a_protocol_version(self, project):
        tmp, config, _ = project
        assert TrainingSpec(
            run_id="r", trainer="t",
            schemas=schema_specs_from_config(config, ["sentiment"]),
            bundle_dir="/b", workdir="/w").to_dict()["v"] == 1


class TestEndToEnd:
    def test_fit_then_predict(self, project):
        tmp, config, ctx = project
        dest = os.path.join(tmp, "bundle")
        bundle, _, _ = build_bundle(ctx, dest, ["sentiment"], split_seed=42)

        spec = TrainingSpec(
            run_id="r1", trainer="sklearn-text",
            schemas=schema_specs_from_config(
                config, ["sentiment"],
                {"sentiment": bundle.labels("sentiment")}),
            bundle_dir=dest, workdir=os.path.join(tmp, "artifacts"),
            params={"min_instances": 4})

        trainer = registry.get_trainer("sklearn-text")
        assert trainer.validate(spec, bundle) == []

        result = trainer.fit(spec, bundle, ProgressReporter())
        assert result.model_version
        assert result.metrics["train_accuracy"] > 0.8
        assert os.path.isfile(os.path.join(spec.workdir, "model.pkl"))

        predictions = list(trainer.predict(
            spec, spec.workdir,
            [PredictItem("x1", "a wonderful and excellent film, I loved it"),
             PredictItem("x2", "an awful tedious movie, I hated it")],
            ProgressReporter()))

        assert len(predictions) == 2
        by_id = {p.instance_id: p for p in predictions}
        assert by_id["x1"].payload["label"] == "positive"
        assert by_id["x2"].payload["label"] == "negative"
        assert 0.0 < by_id["x1"].confidence <= 1.0

    def test_validation_refuses_too_little_data(self, project):
        tmp, config, ctx = project
        dest = os.path.join(tmp, "bundle")
        bundle, _, _ = build_bundle(ctx, dest, ["sentiment"], split_seed=42)

        spec = TrainingSpec(
            run_id="r1", trainer="sklearn-text",
            schemas=schema_specs_from_config(config, ["sentiment"]),
            bundle_dir=dest, workdir=os.path.join(tmp, "a"),
            params={"min_instances": 10_000})

        problems = registry.get_trainer("sklearn-text").validate(spec, bundle)
        assert problems and "at least" in problems[0]

    def test_a_model_card_records_the_label_order(self, project):
        """Column order is what a classifier's output means."""
        tmp, config, ctx = project
        dest = os.path.join(tmp, "bundle")
        bundle, _, _ = build_bundle(ctx, dest, ["sentiment"], split_seed=42)
        spec = TrainingSpec(
            run_id="r1", trainer="sklearn-text",
            schemas=schema_specs_from_config(config, ["sentiment"]),
            bundle_dir=dest, workdir=os.path.join(tmp, "a"),
            params={"min_instances": 4})

        registry.get_trainer("sklearn-text").fit(spec, bundle,
                                                 ProgressReporter())
        with open(os.path.join(spec.workdir, "model_card.json")) as fh:
            card = json.load(fh)
        assert card["label_order"]
        assert card["labels_at_fit"] == bundle.labels("sentiment")
        assert "calibration" in card


class TestBootWeight:
    def test_naming_trainers_imports_no_ml_stack(self):
        """The registry is rendered on every admin page load."""
        result = subprocess.run(
            [sys.executable, "-c",
             "import sys; from potato.training import registry; "
             "registry.list_trainers(); "
             "bad = [m for m in ('torch','transformers','sentence_transformers')"
             " if m in sys.modules]; print(','.join(bad))"],
            capture_output=True, text=True, timeout=180)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "", (
            "listing trainers imported: %s" % result.stdout.strip())

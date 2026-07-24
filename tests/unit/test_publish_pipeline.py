"""Unit tests for the dataset-publishing pipeline, card, and archive.

Covers the preprocessing pipeline (privacy, aggregation, filtering, splits, PII
scrub), the dataset-card generator (frontmatter, per-column docs, Paper Mode reuse,
citation), and the local-archive target. HuggingFace/Zenodo network paths are covered
separately with mocks.
"""

import json
import os
import zipfile

import pytest
import yaml

from potato.publish import (generate_dataset_card, run_pipeline, write_archive)
from potato.publish.bundle import build_gold_rows
from tests.helpers.test_utils import create_test_directory


def build_publish_project(states, schemes=None, metadata=None, items=None,
                          data_items=5):
    """Write a config + data + per-annotator states; return the config path."""
    test_dir = create_test_directory("publish_pipeline")
    os.makedirs(os.path.join(test_dir, "data"), exist_ok=True)
    items = items or [{"id": f"i{k}", "text": f"item {k}"} for k in range(data_items)]
    with open(os.path.join(test_dir, "data", "items.json"), "w") as f:
        for it in items:
            f.write(json.dumps(it) + "\n")
    schemes = schemes or [
        {"annotation_type": "radio", "name": "sentiment",
         "description": "Overall sentiment", "labels": ["pos", "neg", "neu"]},
    ]
    config = {
        "annotation_task_name": "Test Dataset",
        "annotation_task_description": "A pilot dataset.",
        "output_annotation_dir": "out/",
        "data_files": ["data/items.json"],
        "item_properties": {"id_key": "id", "text_key": "text"},
        "annotation_schemes": schemes,
    }
    if metadata:
        config["dataset_metadata"] = metadata
    config_path = os.path.join(test_dir, "config.yaml")
    with open(config_path, "w") as f:
        yaml.dump(config, f)
    for user, labels in states.items():
        user_dir = os.path.join(test_dir, "out", user)
        os.makedirs(user_dir, exist_ok=True)
        state = {
            "user_id": user,
            "instance_id_to_label_to_value": {
                iid: [[{"schema": sch, "name": v}, v]]
                for iid, (sch, v) in labels.items()
            },
        }
        with open(os.path.join(user_dir, "user_state.json"), "w") as f:
            json.dump(state, f)
    return config_path


_TWO_ANNOTATORS = {
    "annotator_alice": {"i0": ("sentiment", "pos"), "i1": ("sentiment", "pos"),
                        "i2": ("sentiment", "neg"), "i3": ("sentiment", "neg")},
    "annotator_bob": {"i0": ("sentiment", "pos"), "i1": ("sentiment", "neg"),
                      "i2": ("sentiment", "neg"), "i3": ("sentiment", "neg")},
}


class TestPrivacy:
    def test_annotators_pseudonymized_by_default(self):
        cp = build_publish_project(_TWO_ANNOTATORS)
        bundle = run_pipeline(cp)
        users = {r["user_id"] for r in bundle.splits["annotations"]}
        assert users == {"A1", "A2"}
        # No real names leak anywhere in the annotations split.
        blob = json.dumps(bundle.splits["annotations"])
        assert "annotator_alice" not in blob and "annotator_bob" not in blob

    def test_anonymize_can_be_disabled(self):
        cp = build_publish_project(_TWO_ANNOTATORS)
        bundle = run_pipeline(cp, options={"anonymize": False})
        users = {r["user_id"] for r in bundle.splits["annotations"]}
        assert users == {"annotator_alice", "annotator_bob"}

    def test_internal_fields_stripped_from_items(self):
        items = [{"id": "i0", "text": "hi", "email": "a@b.com", "worker_id": "W1"}]
        cp = build_publish_project(
            {"u1": {"i0": ("sentiment", "pos")}}, items=items, data_items=0)
        bundle = run_pipeline(cp)
        item_row = bundle.splits["items"][0]
        assert "email" not in item_row and "worker_id" not in item_row


class TestAggregation:
    def test_majority_vote_and_n_annotators(self):
        cp = build_publish_project(_TWO_ANNOTATORS)
        bundle = run_pipeline(cp)
        gold = {r["instance_id"]: r for r in bundle.splits["gold"]}
        # i2/i3: both neg -> neg. i0: both pos -> pos.
        assert gold["i0"]["sentiment.pos"] == "pos"
        assert gold["i2"]["sentiment.neg"] == "neg"
        assert gold["i0"]["n_annotators"] == 2

    def test_mean_aggregation_numeric(self):
        rows = [
            {"instance_id": "i0", "user_id": "A1", "score": "4"},
            {"instance_id": "i0", "user_id": "A2", "score": "2"},
        ]
        gold = build_gold_rows(rows, aggregation="mean")
        assert gold[0]["score"] == pytest.approx(3.0)

    def test_gold_can_be_disabled(self):
        cp = build_publish_project(_TWO_ANNOTATORS)
        bundle = run_pipeline(cp, options={"include_gold": False})
        assert "gold" not in bundle.splits


class TestFiltersAndSplits:
    def test_min_annotators_filter(self):
        states = {
            "u1": {"i0": ("sentiment", "pos"), "i1": ("sentiment", "pos")},
            "u2": {"i0": ("sentiment", "pos")},   # only i0 is doubly annotated
        }
        cp = build_publish_project(states)
        bundle = run_pipeline(cp, options={"min_annotators": 2})
        instances = {r["instance_id"] for r in bundle.splits["annotations"]}
        assert instances == {"i0"}

    def test_train_test_split_is_deterministic_and_complete(self):
        cp = build_publish_project(_TWO_ANNOTATORS)
        opts = {"splits": {"train": 0.7, "test": 0.3}, "split_seed": 7}
        b1 = run_pipeline(cp, options=dict(opts))
        b2 = run_pipeline(cp, options=dict(opts))
        assert "train" in b1.splits and "test" in b1.splits
        # No instance appears in both partitions; deterministic across runs.
        train1 = {r["instance_id"] for r in b1.splits["train"]}
        test1 = {r["instance_id"] for r in b1.splits["test"]}
        assert train1.isdisjoint(test1)
        assert train1 == {r["instance_id"] for r in b2.splits["train"]}


class TestPIIScrub:
    def test_scrub_removes_emails(self):
        items = [{"id": "i0", "text": "reach me at joe@example.com or 555-123-4567"}]
        cp = build_publish_project(
            {"u1": {"i0": ("sentiment", "pos")}}, items=items, data_items=0)
        bundle = run_pipeline(cp, options={"scrub_pii": True})
        text = bundle.splits["items"][0]["text"]
        assert "joe@example.com" not in text and "[EMAIL]" in text


class TestDatasetCard:
    def _card(self, **opts):
        meta = {"license": "cc-by-4.0",
                "citation": "@article{x2026, title={X}, year={2026}}",
                "authors": [{"name": "Ada", "orcid": "0000"}]}
        cp = build_publish_project(_TWO_ANNOTATORS, metadata=meta)
        bundle = run_pipeline(cp, options=opts)
        return generate_dataset_card(bundle, repo_id="org/ds"), bundle

    def test_frontmatter_is_valid_yaml_with_expected_keys(self):
        card, _ = self._card()
        assert card.startswith("---\n")
        fm = card.split("---", 2)[1]
        data = yaml.safe_load(fm)
        assert data["license"] == "cc-by-4.0"
        assert "text-classification" in data["task_categories"]
        assert "potato-annotation" in data["tags"]

    def test_has_per_column_docs_and_sections(self):
        card, _ = self._card()
        assert "`sentiment`" in card and "Overall sentiment" in card
        for section in ("## Dataset Summary", "## Inter-Annotator Agreement",
                        "## Licensing Information", "## Citation Information"):
            assert section in card

    def test_agreement_numbers_match_metrics(self):
        card, bundle = self._card()
        alpha = bundle.stats["schemes"][0]["alpha"]
        assert f"{alpha:.3f}" in card

    def test_no_latex_leakage_in_card(self):
        card, _ = self._card()
        for token in (r"\emph", r"\citep", "$\\alpha$"):
            assert token not in card

    def test_citation_includes_user_and_potato(self):
        card, _ = self._card()
        assert "x2026" in card and "pei2022potato" in card


class TestArchive:
    def test_archive_contains_expected_files(self):
        cp = build_publish_project(_TWO_ANNOTATORS,
                                   metadata={"license": "cc-by-4.0"})
        bundle = run_pipeline(cp)
        bundle.card_markdown = generate_dataset_card(bundle)
        test_dir = create_test_directory("publish_archive")
        arch = write_archive(bundle, os.path.join(test_dir, "ds"), "zip")
        assert os.path.exists(arch)
        with zipfile.ZipFile(arch) as z:
            names = z.namelist()
            assert any(n.endswith("README.md") for n in names)
            assert any(n.endswith("LICENSE") for n in names)
            assert any(n.endswith(".zenodo.json") for n in names)
            assert any(n.endswith("data/gold.jsonl") for n in names)
            # The Paper Mode LaTeX report ships inside the archive.
            assert any(n.endswith("paper_report/paper.tex") for n in names)
            readme = z.read(next(n for n in names if n.endswith("README.md")))
            assert readme.decode() == bundle.card_markdown

    def test_cli_writes_archive(self, capsys):
        from potato.publish.__main__ import main
        cp = build_publish_project(_TWO_ANNOTATORS,
                                   metadata={"license": "cc-by-4.0"})
        test_dir = create_test_directory("publish_cli")
        out = os.path.join(test_dir, "cli_ds")
        rc = main([cp, "--target", "archive", "-o", out, "--scrub-pii",
                   "--aggregation", "majority"])
        assert rc == 0
        assert os.path.exists(out + ".zip")
        captured = capsys.readouterr()
        assert "splits:" in captured.out

    def test_cli_bad_config_returns_error(self):
        from potato.publish.__main__ import main
        assert main(["/nonexistent/config.yaml", "--target", "archive"]) == 1

    def test_zenodo_metadata_shape(self):
        from potato.publish.targets import zenodo_metadata
        cp = build_publish_project(
            _TWO_ANNOTATORS,
            metadata={"license": "cc-by-4.0", "keywords": ["nlp"],
                      "authors": [{"name": "Ada", "affiliation": "UM",
                                   "orcid": "0000-0001"}]})
        bundle = run_pipeline(cp)
        meta = zenodo_metadata(bundle)["metadata"]
        assert meta["upload_type"] == "dataset"
        assert meta["creators"][0]["name"] == "Ada"
        assert meta["creators"][0]["orcid"] == "0000-0001"
        assert meta["keywords"] == ["nlp"]

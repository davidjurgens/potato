"""Unit tests for judge_calibration report assembly + human-label extraction."""

import json
import os
from potato.judge_calibration.report import (
    extract_human_label,
    collect_metric_inputs,
    render_html,
)
from potato.judge_calibration.storage import ResultStore
from potato.judge_calibration.aggregation import aggregate


class FakeLabel:
    def __init__(self, schema, name):
        self.schema = schema
        self.name = name


class TestExtractHumanLabel:
    def test_radio_single(self):
        d = {FakeLabel("sent", "positive"): "true"}
        assert extract_human_label(d, "sent", "radio") == "positive"

    def test_other_schema_ignored(self):
        d = {FakeLabel("other", "x"): "true", FakeLabel("sent", "neg"): "true"}
        assert extract_human_label(d, "sent", "radio") == "neg"

    def test_unselected_value_skipped(self):
        d = {FakeLabel("sent", "positive"): "false", FakeLabel("sent", "negative"): "true"}
        assert extract_human_label(d, "sent", "radio") == "negative"

    def test_none_when_absent(self):
        d = {FakeLabel("other", "x"): "true"}
        assert extract_human_label(d, "sent", "radio") is None

    def test_multiselect_list(self):
        d = {FakeLabel("tags", "a"): "true", FakeLabel("tags", "b"): "true",
             FakeLabel("tags", "c"): "false"}
        assert extract_human_label(d, "tags", "multiselect") == ["a", "b"]


class FakeUser:
    def __init__(self, uid, ann):
        self.uid = uid
        self.ann = ann  # {iid: {Label: value}}

    def get_user_id(self):
        return self.uid

    def get_annotated_instance_ids(self):
        return set(self.ann.keys())

    def get_label_annotations(self, iid):
        return self.ann.get(iid, {})


class FakeUSM:
    def __init__(self, users):
        self._users = users

    def get_all_users(self):
        return self._users


def test_collect_metric_inputs(monkeypatch):
    store = ResultStore(state_dir=None)
    for iid, lab in [("i1", "pos"), ("i2", "neg")]:
        store.upsert(aggregate("m1", iid, "sent", "radio", [lab] * 3, 3), save=False)

    users = [FakeUser("h1", {
        "i1": {FakeLabel("sent", "pos"): "true"},
        "i2": {FakeLabel("sent", "neg"): "true"},
    })]
    monkeypatch.setattr(
        "potato.user_state_management.get_user_state_manager",
        lambda: FakeUSM(users),
    )

    schema_info = {"name": "sent", "annotation_type": "radio", "labels": ["pos", "neg"]}
    llm_modal, llm_conf, human = collect_metric_inputs(store, schema_info)
    assert llm_modal["m1"]["i1"] == "pos"
    assert human["h1"]["i2"] == "neg"


def test_render_html_smoke():
    report = {
        "generated_at": "now", "n_models": 1, "k_samples": 5, "n_labeled_items": 10,
        "schemas": {
            "sent": {
                "annotation_type": "radio", "n_gold": 5, "gold_strategy": "single",
                "per_model": {"m1": {"accuracy": 0.8, "f1_macro": 0.79,
                                     "calibration": {"ece": 0.1, "brier": 0.2}, "n": 5}},
                "iaa": {"cohen": {"mean_human_llm": 0.7, "mean_llm_llm": None,
                                  "mean_human_human": None},
                        "fleiss": {"kappa": 0.7}, "krippendorff": {"alpha": 0.7, "metric": "nominal"}},
            }
        },
    }
    html = render_html(report)
    assert "Judge Calibration Report" in html
    assert "0.8" in html
    assert "sent" in html

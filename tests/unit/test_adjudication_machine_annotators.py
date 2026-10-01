"""Declared machine raters in the adjudication queue.

``build_queue`` had no test coverage at all before this file, so the annotator
filter it applies -- which decides who is even eligible to be adjudicated --
was changed on the strength of a green suite that never called it.

The behaviour pinned here:

* A study that declares no machine rater gets exactly the queue it got before,
  because the filter is identity when every participant is a person.
* Machines stay out unless the study asks for them, which is the same
  precedent the existing ``adjudicator_users`` exclusion sets.
* When they are let in, the adjudicator is told which participants were
  machines and which versions produced the answers -- an adjudicator choosing
  between two labels needs to know one of them came from a tool.
"""

from __future__ import annotations

import tempfile
from unittest.mock import patch

import pytest

from potato.adjudication import AdjudicationDecision, AdjudicationManager
from potato.item_state_management import Label


# ---------------------------------------------------------------------------
# Fakes matching the containers build_queue actually reads
# ---------------------------------------------------------------------------

class FakeUserState:
    """Holds the flat ``{Label: value}`` container a real UserState holds."""

    def __init__(self, per_item, origin=None):
        self.instance_id_to_label_to_value = {
            iid: {Label(schema, name): value
                  for (schema, name), value in entries.items()}
            for iid, entries in per_item.items()
        }
        self.instance_id_to_span_to_value = {}
        self.instance_id_to_behavioral_data = {}
        if origin is not None:
            self.origin = origin


class FakeUSM:
    def __init__(self, states):
        self.states = states

    def get_user_state(self, uid):
        return self.states.get(uid)


class FakeItem:
    """generate_final_dataset calls get_data() on each item."""

    def get_data(self):
        return {"id": "i1", "text": "the food was good"}


class FakeISM:
    def __init__(self, iids, annotators):
        self._items = {i: FakeItem() for i in iids}
        self.instance_annotators = {i: set(annotators) for i in iids}

    def iter_items(self):
        return iter(self._items.items())


TOOL_A = {"kind": "tool", "id": "prokka", "version": "1.14.6"}
TOOL_B = {"kind": "tool", "id": "bakta", "version": "1.7"}


def _config(include_machines=False, min_human=0, **extra):
    cfg = {
        "adjudication": {
            "enabled": True,
            "adjudicator_users": ["adjudicator"],
            "min_annotations": 2,
            # Every item in the queue, so a test asserting on membership is
            # not silently filtered by the agreement threshold.
            "show_all_items": True,
            "include_machine_annotators": include_machines,
            "min_human_annotations": min_human,
        },
        "annotation_schemes": [
            {"name": "sentiment", "annotation_type": "radio",
             "labels": ["positive", "negative"]},
        ],
        "output_annotation_dir": tempfile.mkdtemp(),
        "item_properties": {"id_key": "id", "text_key": "text"},
    }
    cfg["adjudication"].update(extra)
    return cfg


def _build(config, states):
    """Run build_queue against fake state managers."""
    ism = FakeISM(["i1"], list(states))
    usm = FakeUSM(states)
    with patch("potato.user_state_management.get_user_state_manager",
               return_value=usm), \
         patch("potato.item_state_management.get_item_state_manager",
               return_value=ism):
        mgr = AdjudicationManager(config)
        mgr.build_queue()
        return mgr


def _people():
    return {
        "alice": FakeUserState({"i1": {("sentiment", "positive"): True}}),
        "bob": FakeUserState({"i1": {("sentiment", "negative"): True}}),
    }


def _people_and_tools():
    states = _people()
    states["prokka"] = FakeUserState(
        {"i1": {("sentiment", "negative"): True}}, origin=TOOL_A)
    states["bakta"] = FakeUserState(
        {"i1": {("sentiment", "negative"): True}}, origin=TOOL_B)
    return states


class TestConfigParsing:
    def test_defaults_preserve_existing_behaviour(self):
        mgr = AdjudicationManager(_config())
        assert mgr.adj_config.include_machine_annotators is False
        assert mgr.adj_config.min_human_annotations == 0

    def test_keys_are_read(self):
        mgr = AdjudicationManager(_config(include_machines=True, min_human=2))
        assert mgr.adj_config.include_machine_annotators is True
        assert mgr.adj_config.min_human_annotations == 2


class TestMachinesStayOutByDefault:
    def test_only_people_are_queued(self):
        mgr = _build(_config(), _people_and_tools())
        item = mgr.queue["i1"]
        assert set(item.annotations) == {"alice", "bob"}

    def test_no_origins_are_reported_when_machines_are_excluded(self):
        # Reporting origins for raters that were dropped would describe a
        # queue the adjudicator is not being shown.
        mgr = _build(_config(), _people_and_tools())
        assert mgr.queue["i1"].annotator_origins == {}

    def test_an_all_human_study_is_untouched(self):
        mgr = _build(_config(), _people())
        item = mgr.queue["i1"]
        assert set(item.annotations) == {"alice", "bob"}
        assert item.annotator_origins == {}
        assert "annotator_origins" not in item.to_dict()


class TestMachinesEnterWhenAsked:
    def test_tools_are_queued(self):
        mgr = _build(_config(include_machines=True), _people_and_tools())
        assert set(mgr.queue["i1"].annotations) == {
            "alice", "bob", "prokka", "bakta"}

    def test_the_adjudicator_is_told_which_were_machines(self):
        mgr = _build(_config(include_machines=True), _people_and_tools())
        origins = mgr.queue["i1"].annotator_origins
        assert set(origins) == {"prokka", "bakta"}
        assert "1.14.6" in origins["prokka"]
        assert "alice" not in origins

    def test_origins_reach_the_serialized_item(self):
        mgr = _build(_config(include_machines=True), _people_and_tools())
        assert "annotator_origins" in mgr.queue["i1"].to_dict()


class TestHumanFloor:
    def test_an_all_machine_item_is_allowed_by_default(self):
        """Several tools and no human is a valid queue: the adjudicator is
        the person in that design."""
        tools = {
            "prokka": FakeUserState(
                {"i1": {("sentiment", "positive"): True}}, origin=TOOL_A),
            "bakta": FakeUserState(
                {"i1": {("sentiment", "negative"): True}}, origin=TOOL_B),
        }
        mgr = _build(_config(include_machines=True, min_human=0), tools)
        assert "i1" in mgr.queue

    def test_requiring_a_human_drops_an_all_machine_item(self):
        tools = {
            "prokka": FakeUserState(
                {"i1": {("sentiment", "positive"): True}}, origin=TOOL_A),
            "bakta": FakeUserState(
                {"i1": {("sentiment", "negative"): True}}, origin=TOOL_B),
        }
        mgr = _build(_config(include_machines=True, min_human=1), tools)
        assert "i1" not in mgr.queue

    def test_a_mixed_item_satisfies_the_floor(self):
        mgr = _build(_config(include_machines=True, min_human=1),
                     _people_and_tools())
        assert "i1" in mgr.queue


class TestDecisionRecordsWhatItAdopted:
    """A later config edit must not change what a past decision meant."""

    def _decision(self, **kw):
        base = dict(
            instance_id="i1", adjudicator_id="adjudicator",
            timestamp="2026-09-16T00:00:00", label_decisions={"sentiment": "x"},
            span_decisions=[], source={"sentiment": "annotator_prokka"},
            confidence="high", notes="", error_taxonomy=[],
        )
        base.update(kw)
        return AdjudicationDecision(**base)

    def test_source_origins_defaults_to_empty(self):
        assert self._decision().source_origins == {}

    def test_source_origins_round_trips(self):
        d = self._decision(source_origins={"sentiment": "prokka 1.14.6 (tool)"})
        restored = AdjudicationDecision.from_dict(d.to_dict())
        assert restored.source_origins == {"sentiment": "prokka 1.14.6 (tool)"}

    def test_a_decision_written_before_the_field_existed_still_loads(self):
        raw = self._decision().to_dict()
        raw.pop("source_origins")
        assert AdjudicationDecision.from_dict(raw).source_origins == {}


class TestUnanimityNamesWhoAgreed:
    """Several tools agreeing is not unanimity in the human sense.

    Pipelines that share a reference database make the same mistake together,
    so their agreement is evidence about their inputs rather than about the
    answer. The value an all-human study writes is unchanged, because renaming
    it for every existing project would break the export contract for studies
    this feature does not concern.
    """

    def _final(self, states, include_machines=True):
        ism = FakeISM(["i1"], list(states))
        usm = FakeUSM(states)
        with patch("potato.user_state_management.get_user_state_manager",
                   return_value=usm), \
             patch("potato.item_state_management.get_item_state_manager",
                   return_value=ism):
            mgr = AdjudicationManager(
                _config(include_machines=include_machines))
            return mgr.generate_final_dataset()

    def _agreeing(self, origin=None):
        return FakeUserState({"i1": {("sentiment", "positive"): True}},
                             origin=origin)

    def test_people_agreeing_still_reads_unanimous(self):
        states = {"alice": self._agreeing(), "bob": self._agreeing()}
        assert self._final(states)[0]["source"] == "unanimous"

    def test_tools_agreeing_is_named_as_such(self):
        states = {"prokka": self._agreeing(TOOL_A),
                  "bakta": self._agreeing(TOOL_B)}
        assert self._final(states)[0]["source"] == "unanimous_machine"

    def test_a_person_and_a_tool_agreeing_is_named_as_such(self):
        states = {"alice": self._agreeing(), "prokka": self._agreeing(TOOL_A)}
        assert self._final(states)[0]["source"] == "unanimous_mixed"

    def test_disagreement_is_still_unresolved(self):
        states = {
            "alice": FakeUserState({"i1": {("sentiment", "positive"): True}}),
            "bob": FakeUserState({"i1": {("sentiment", "negative"): True}}),
        }
        assert self._final(states)[0]["source"] == "unresolved"


class TestExportCarriesOrigin:
    def test_absent_origin_exports_as_human(self):
        from potato.export.cli import _annotator_origin
        assert _annotator_origin({}, "i1") == {"kind": "human"}

    def test_a_machine_origin_is_exported(self):
        from potato.export.cli import _annotator_origin
        state = {"origin": {"kind": "tool", "id": "prokka", "version": "1.14.6"}}
        assert _annotator_origin(state, "i1")["id"] == "prokka"

    def test_an_empty_origin_dict_is_human(self):
        from potato.export.cli import _annotator_origin
        assert _annotator_origin({"origin": {}}, "i1") == {"kind": "human"}

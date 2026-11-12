"""``/admin/iaa`` must not report human-machine agreement as human reliability.

The scenario here is the one that motivated the feature. Four raters judge the
same items: two people who agree with each other, and two tools that agree with
each other and disagree with the people. That is what correlated error looks
like -- annotation pipelines sharing reference databases produce the same wrong
answer, so their agreement is evidence about their shared inputs rather than
about the truth.

Pooled over all four, the coefficient is low and a reader concludes the human
annotators are unreliable. They are not; they agree perfectly. The number moved
because two machines joined the matrix.

The fakes are imported from ``test_iaa_dispatcher_gathering`` rather than
rewritten. That module's ``TestStorageShapeIsReal`` checks its fake against a
real on-disk user state, so it is the one fake in the suite known to hold the
shape the product writes. A second copy here would be free to drift.
"""

from __future__ import annotations

import pytest

from potato.server_utils.iaa import dispatcher
from tests.unit.test_iaa_dispatcher_gathering import (
    FakeISM,
    FakeUserState,
    FakeUSM,
)

SCHEME = {
    "name": "call",
    "annotation_type": "radio",
    "description": "is this a gene",
    "labels": ["yes", "no"],
}

#: Humans agree with each other; tools agree with each other and contradict them.
PER_USER = {
    "alice": {"i1": {("call", "yes"): True}, "i2": {("call", "no"): True}},
    "bob": {"i1": {("call", "yes"): True}, "i2": {("call", "no"): True}},
    "prokka": {"i1": {("call", "no"): True}, "i2": {("call", "yes"): True}},
    "bakta": {"i1": {("call", "no"): True}, "i2": {("call", "yes"): True}},
}

MACHINES = {
    "prokka": {"kind": "tool", "id": "prokka", "version": "1.14.6"},
    "bakta": {"kind": "tool", "id": "bakta", "version": "1.7"},
}


def _states(declare_machines: bool):
    states = {uid: FakeUserState(items) for uid, items in PER_USER.items()}
    if declare_machines:
        for uid, origin in MACHINES.items():
            states[uid].origin = origin
    return states


def _report(declare_machines: bool):
    states = _states(declare_machines)
    ism = FakeISM(["i1", "i2"], list(PER_USER))
    return dispatcher.compute_overlap_iaa(
        ism, FakeUSM(states), {"annotation_schemes": [SCHEME]}
    )


def _agreement(block):
    """Krippendorff's alpha, which is what the nominal report headlines."""
    return block["schemas"]["call"]["metrics"]["alpha_nominal"]


class TestAllHumanIsUnchanged:
    """The regression that matters most: a study with no machines is untouched."""

    def _human_only_report(self):
        states = {
            uid: FakeUserState(items)
            for uid, items in PER_USER.items()
            if uid in ("alice", "bob")
        }
        ism = FakeISM(["i1", "i2"], ["alice", "bob"])
        return dispatcher.compute_overlap_iaa(
            ism, FakeUSM(states), {"annotation_schemes": [SCHEME]}
        )

    def test_the_report_keeps_exactly_its_old_keys(self):
        report = self._human_only_report()
        assert set(report) == {
            "schemas", "items", "n_overlap_items", "n_items_below_cap",
        }

    def test_no_partitions_block_is_added(self):
        # Partitioning a study that has nothing to partition would change every
        # existing consumer's payload for no gain.
        assert "partitions" not in self._human_only_report()

    def test_the_numbers_are_the_numbers(self):
        assert _agreement(self._human_only_report()) == 1.0


class TestUndeclaredMachinesContaminateTheHeadline:
    """The bug, reproduced. Delete the declaration and the number moves."""

    def test_undeclared_machines_are_counted_as_people(self):
        report = _report(declare_machines=False)
        assert "partitions" not in report
        # Four raters in one matrix, two of them tools, and nothing says so.
        assert report["schemas"]["call"]["metrics"]["n_annotators"] == 4

    def test_the_contaminated_headline_understates_human_agreement(self):
        contaminated = _agreement(_report(declare_machines=False))
        clean = _agreement(_report(declare_machines=True))
        assert contaminated < clean
        assert clean == 1.0


class TestDeclaredMachinesArePartitioned:
    def test_the_partitions_block_appears(self):
        report = _report(declare_machines=True)
        assert set(report["partitions"]) == {
            "human_human", "machine_machine", "pooled",
        }

    def test_the_headline_is_human_only(self):
        report = _report(declare_machines=True)
        assert _agreement(report) == 1.0
        assert report["schemas"]["call"]["metrics"]["n_annotators"] == 2

    def test_machines_agreeing_with_each_other_is_reported_separately(self):
        # Two tools sharing evidence agree perfectly. That is a fact about the
        # tools, and it belongs in its own partition rather than in either the
        # human figure or a pooled one.
        report = _report(declare_machines=True)
        machine = report["partitions"]["machine_machine"]
        assert _agreement(machine) == 1.0
        assert machine["schemas"]["call"]["metrics"]["n_annotators"] == 2

    def test_the_pooled_figure_is_still_available_and_still_lower(self):
        report = _report(declare_machines=True)
        pooled = report["partitions"]["pooled"]
        assert pooled["schemas"]["call"]["metrics"]["n_annotators"] == 4
        assert _agreement(pooled) < _agreement(report)

    def test_two_self_consistent_groups_pool_to_worse_than_chance(self):
        """Why the pooled figure cannot be the headline.

        The humans agree perfectly with each other and the tools agree
        perfectly with each other, so each group is a reliable rater set. Pooled
        into one matrix they score below zero -- worse than raters assigning
        labels at random. The pooled number describes the disagreement between
        two groups, and reporting it as the study's agreement would say the
        annotators are unreliable when neither group is.
        """
        report = _report(declare_machines=True)
        assert _agreement(report) == 1.0
        assert _agreement(report["partitions"]["machine_machine"]) == 1.0
        assert _agreement(report["partitions"]["pooled"]) < 0

    def test_the_report_says_which_figure_is_the_headline(self):
        report = _report(declare_machines=True)
        assert report["pooling"]["headline"] == "human_human"
        assert "human annotators only" in report["pooling"]["note"]

    def test_the_report_names_the_machines(self):
        report = _report(declare_machines=True)
        annotators = report["annotators"]
        assert annotators["n_human"] == 2
        assert annotators["machine"] == ["bakta", "prokka"]
        assert "1.14.6" in annotators["machine_detail"]["prokka"]


class TestPartitionsDoNotShareState:
    """Each partition writes per-item annotator counts, so they need own dicts."""

    def test_item_reports_are_distinct_objects(self):
        report = _report(declare_machines=True)
        human_items = report["partitions"]["human_human"]["items"]
        machine_items = report["partitions"]["machine_machine"]["items"]
        assert human_items is not machine_items

    def test_per_item_counts_are_per_partition(self):
        report = _report(declare_machines=True)
        human_items = report["partitions"]["human_human"]["items"]
        pooled_items = report["partitions"]["pooled"]["items"]
        assert human_items["i1"]["schemas"]["call"]["n_annotators"] == 2
        assert pooled_items["i1"]["schemas"]["call"]["n_annotators"] == 4

    def test_the_top_level_items_are_the_human_ones(self):
        # drift.py takes its overlap id list from report["items"], and the
        # windowed report it builds is a human-reliability trend.
        report = _report(declare_machines=True)
        assert report["items"]["i1"]["schemas"]["call"]["n_annotators"] == 2


class TestNewKeysAreAdditive:
    """drift.py stubs this function with a bare three-key dict in its own tests,
    so every reader has to tolerate the new keys being absent."""

    def test_a_report_without_partitions_is_readable(self):
        stub = {"schemas": {}, "items": {"x": {}}, "n_overlap_items": 1}
        assert stub.get("partitions") is None
        assert stub.get("pooling", {}).get("headline") is None

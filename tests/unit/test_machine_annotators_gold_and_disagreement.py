"""Machine raters and the two per-item consumers outside the agreement report.

**Gold auto-promotion.** Gold is the answer key later annotators are graded
against. Tools that share a reference database make the same mistake together,
so three of them agreeing is correlated error, not evidence, and must never be
enough to write the answer key.

**The disagreement score.** A score over everyone measures the distance between
people and tools as much as how contested an item is. ``kinds`` selects which
raters count; the default must stay ``"all"`` so no existing study's routing
moves.
"""

from unittest.mock import MagicMock, patch

import pytest

from potato.item_state_management import ItemStateManager, Label
from potato.quality_control import QualityControlManager

TOOL = {"kind": "tool", "id": "prokka", "version": "1.14.6"}
LLM = {"kind": "llm", "id": "gemma"}


@pytest.fixture
def qc(tmp_path):
    config = {
        "gold_standards": {
            "enabled": True,
            "auto_promote": {"enabled": True, "min_annotators": 3,
                             "agreement_threshold": 1.0},
        }
    }
    return QualityControlManager(config, str(tmp_path))


class TestMachineConsensusIsNeverGold:
    def test_three_agreeing_tools_do_not_promote(self, qc):
        for uid in ("prokka", "bakta", "pgap"):
            result = qc.record_item_annotation(
                "item_1", uid, {"product": "hypothetical"}, origin=TOOL)
            assert result is None
        assert qc.get_promoted_gold_standards() == []
        assert not qc.is_gold_standard("item_1")

    def test_machine_answers_are_not_even_recorded(self, qc):
        """Otherwise the candidate view reports tools as progress toward gold."""
        qc.record_item_annotation("item_1", "prokka", {"product": "x"}, origin=TOOL)
        qc.record_item_annotation("item_1", "gemma", {"product": "x"}, origin=LLM)
        assert "item_1" not in qc.item_annotations
        assert qc.get_promotion_candidates() == []

    def test_tools_do_not_make_up_a_human_shortfall(self, qc):
        """Two people plus a tool is two opinions toward a floor of three."""
        qc.record_item_annotation("item_1", "alice", {"product": "x"})
        qc.record_item_annotation("item_1", "bob", {"product": "x"})
        assert qc.record_item_annotation(
            "item_1", "prokka", {"product": "x"}, origin=TOOL) is None
        assert qc.get_promoted_gold_standards() == []

    def test_people_still_promote_on_their_own(self, qc):
        """The guard must refuse tools, not promotion."""
        qc.record_item_annotation("item_1", "prokka", {"product": "x"}, origin=TOOL)
        qc.record_item_annotation("item_1", "alice", {"product": "x"}, origin={})
        qc.record_item_annotation("item_1", "bob", {"product": "x"}, origin=None)
        result = qc.record_item_annotation("item_1", "carol", {"product": "x"},
                                           origin={"kind": "human"})
        assert result and result["promoted"]
        promoted = qc.get_promoted_gold_standards()
        assert [p["id"] for p in promoted] == ["item_1"]
        assert sorted(promoted[0]["source_annotators"]) == ["alice", "bob", "carol"]

    def test_omitting_origin_reads_as_a_person(self, qc):
        """The pre-existing call shape, unchanged for every existing caller."""
        for uid in ("u1", "u2", "u3"):
            result = qc.record_item_annotation("item_1", uid, {"product": "x"})
        assert result and result["promoted"]


def _user_state(label, origin):
    ustate = MagicMock()
    ustate.get_label_annotations.return_value = {Label("sentiment", label): True}
    ustate.get_span_annotations.return_value = {}
    # Set explicitly: a bare MagicMock attribute is not a mapping, and an
    # unreadable origin reads as machine by design.
    ustate.origin = origin
    return ustate


def _score(users, kinds):
    ism = ItemStateManager({"random_seed": 7})
    ism.add_item("item_1", {"text": "x"})
    usm = MagicMock()
    usm.get_user_state.side_effect = lambda uid: users.get(uid)
    with patch("potato.user_state_management.get_user_state_manager",
               return_value=usm):
        for uid in users:
            ism.register_annotator("item_1", uid)
        if kinds is None:
            return ism._calculate_disagreement_score("item_1")
        return ism._calculate_disagreement_score("item_1", kinds=kinds)


class TestDisagreementScoreByKind:
    # People agree with each other; the tools agree with each other; the two
    # groups disagree. Only the pooled score sees conflict.
    SPLIT = {
        "alice": _user_state("pos", {}),
        "bob": _user_state("pos", {}),
        "prokka": _user_state("neg", TOOL),
        "bakta": _user_state("neg", TOOL),
    }

    def test_pooled_score_sees_the_gap_between_groups(self):
        assert _score(self.SPLIT, "all") > 0.0

    def test_default_is_pooled(self):
        assert _score(self.SPLIT, None) == _score(self.SPLIT, "all")

    def test_humans_only_sees_no_conflict(self):
        assert _score(self.SPLIT, "human") == 0.0

    def test_machines_only_sees_no_conflict(self):
        assert _score(self.SPLIT, "machine") == 0.0

    def test_machines_only_sees_conflict_between_tools(self):
        users = {
            "alice": _user_state("pos", {}),
            "bob": _user_state("pos", {}),
            "prokka": _user_state("pos", TOOL),
            "bakta": _user_state("neg", TOOL),
        }
        assert _score(users, "machine") > 0.0
        assert _score(users, "human") == 0.0

    def test_one_rater_of_a_kind_is_no_disagreement(self):
        users = {
            "alice": _user_state("pos", {}),
            "prokka": _user_state("neg", TOOL),
        }
        assert _score(users, "human") == 0.0
        assert _score(users, "machine") == 0.0

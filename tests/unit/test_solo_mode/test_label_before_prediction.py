"""A human label submitted before the LLM has labeled that instance must be
kept, saved, and compared once the LLM's prediction arrives.

Previously record_human_label() returned early when no prediction existed:
only the instance id was kept (not the label), nothing was saved, the
comparison never happened, and Back showed the item as unlabeled.
"""

from potato.solo_mode.config import parse_solo_mode_config
from potato.solo_mode.manager import LLMPrediction, SoloModeManager

SCHEMES = [{"name": "frame", "annotation_type": "radio",
            "labels": ["Episodic", "Thematic"]}]


def _manager():
    cfg = parse_solo_mode_config({"solo_mode": {"enabled": True, "labeling_models": []},
                                  "annotation_schemes": SCHEMES})
    m = SoloModeManager(cfg, {"annotation_schemes": SCHEMES})
    m.saves = 0

    def _count_save(*a, **k):
        m.saves += 1
    m._save_state = _count_save
    return m


def _pred(iid, label):
    return LLMPrediction(instance_id=iid, schema_name="frame", predicted_label=label,
                         confidence_score=0.9, uncertainty_score=0.1,
                         prompt_version=1, model_name="m", reasoning="")


def test_label_without_prediction_is_kept_and_saved():
    m = _manager()
    assert m.record_human_label("i1", "frame", "Episodic", "u") is None
    assert m.get_human_label_for_instance("i1") == "Episodic"
    assert m.saves >= 1
    assert m.agreement_metrics.total_compared == 0


def test_disagreement_surfaces_when_prediction_arrives_later():
    m = _manager()
    m.record_human_label("i1", "frame", "Episodic", "u")
    m.set_llm_prediction("i1", "frame", _pred("i1", "Thematic"))
    assert m.agreement_metrics.total_compared == 1
    assert m.agreement_metrics.disagreements == 1
    assert m.get_pending_disagreements() == ["i1"]
    assert m.get_llm_prediction("i1", "frame").human_label == "Episodic"


def test_agreement_counted_once_when_prediction_arrives_later():
    m = _manager()
    m.record_human_label("i1", "frame", "Thematic", "u")
    m.set_llm_prediction("i1", "frame", _pred("i1", "Thematic"))
    # A later replacement prediction (e.g. re-annotation) is not compared
    # against the stale waiting label again.
    m.set_llm_prediction("i1", "frame", _pred("i1", "Thematic"))
    assert m.agreement_metrics.total_compared <= 1
    assert m.agreement_metrics.agreements == m.agreement_metrics.total_compared
    assert m.get_pending_disagreements() == []


def test_duplicate_prediction_keeps_the_human_comparison():
    """Two overlapping LLM calls for one item under the same prompt: the
    second must not erase the human's already-compared answer."""
    m = _manager()
    m.set_llm_prediction("i1", "frame", _pred("i1", "Episodic"))
    m.record_human_label("i1", "frame", "Episodic", "u")
    assert m.agreement_metrics.agreements == 1
    m.set_llm_prediction("i1", "frame", _pred("i1", "Episodic"))   # duplicate
    assert m.get_llm_prediction("i1", "frame").human_label == "Episodic"
    assert m.agreement_metrics.total_compared == 1
    assert m.agreement_metrics.agreements == 1


def test_duplicate_prediction_that_disagrees_surfaces_disagreement():
    m = _manager()
    m.set_llm_prediction("i1", "frame", _pred("i1", "Episodic"))
    m.record_human_label("i1", "frame", "Episodic", "u")
    m.set_llm_prediction("i1", "frame", _pred("i1", "Thematic"))   # duplicate
    assert m.agreement_metrics.total_compared == 1
    assert m.agreement_metrics.disagreements == 1
    assert m.get_pending_disagreements() == ["i1"]


def test_waiting_label_skipped_once_instance_flagged_for_relabel():
    m = _manager()
    m.record_human_label("i1", "frame", "Episodic", "u")
    m.human_labeled_ids.discard("i1")          # as a relabel flag does
    m.set_llm_prediction("i1", "frame", _pred("i1", "Thematic"))
    assert m.agreement_metrics.total_compared == 0

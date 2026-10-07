"""
Which item an annotator sees next, driven through the real assignment calls.

The earlier tests called the diversity manager's own loop, which the server
never runs; covered six strategies' top-up and not the other three; never
varied PYTHONHASHSEED; and gave solo mode one schema, so per-instance and
per-(instance, schema) bookkeeping could not diverge.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import potato.diversity_manager as dmod
import potato.item_state_management as ism_mod
from potato.diversity_manager import DiversityConfig, DiversityManager
from potato.item_state_management import Label, init_item_state_manager
from potato.user_state_management import InMemoryUserState

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def fresh_ism():
    previous = ism_mod.ITEM_STATE_MANAGER

    def make(config, ids):
        ism_mod.ITEM_STATE_MANAGER = None
        ism = init_item_state_manager(config)
        ism.add_items({i: {"id": i, "text": f"item {i}"} for i in ids})
        return ism
    yield make
    ism_mod.ITEM_STATE_MANAGER = previous


@pytest.fixture
def clustered():
    previous = dmod._DIVERSITY_MANAGER
    ids = [f"{c}{i}" for c in "ABC" for i in range(4)]
    dm = DiversityManager(DiversityConfig(enabled=False), {})
    dm.enabled = True
    dm.cluster_labels = {iid: "ABC".index(iid[0]) for iid in ids}
    dmod._DIVERSITY_MANAGER = dm
    yield ids
    dmod._DIVERSITY_MANAGER = previous


def _work_through(ism, user, calls=30):
    """Page through the study the way the server does: top up, annotate."""
    for _ in range(calls):
        ism.assign_instances_to_user(user)
        for iid in list(user.instance_id_ordering):
            if not user.has_annotated(iid):
                user.instance_id_to_label_to_value[iid] = {Label("s", "x"): "x"}


class TestDiversityRoundRobin:
    def test_served_items_alternate_clusters(self, fresh_ism, clustered):
        ism = fresh_ism({"assignment_strategy": "diversity_clustering",
                         "max_annotations_per_item": -1}, clustered)
        user = InMemoryUserState("u1", max_assignments=12)
        _work_through(ism, user)
        assert user.instance_id_ordering == [
            "A0", "B0", "C0", "A1", "B1", "C1", "A2", "B2", "C2", "A3", "B3", "C3"]

    def test_the_pick_within_a_cluster_ignores_hash_order(self):
        code = (
            "import logging; logging.disable(logging.CRITICAL)\n"
            "from potato.diversity_manager import DiversityManager, DiversityConfig\n"
            "dm = DiversityManager(DiversityConfig(enabled=False), {}); dm.enabled = True\n"
            "ids = [f'{c}{i}' for c in 'AB' for i in range(5)]\n"
            "dm.cluster_labels = {i: 'AB'.index(i[0]) for i in ids}\n"
            "print(dm.generate_diverse_ordering('u', ids, set()))\n")
        outs = {subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True,
                               text=True, env=dict(os.environ, PYTHONHASHSEED=str(seed))
                               ).stdout.strip().splitlines()[-1] for seed in (1, 2, 3)}
        assert len(outs) == 1


class TestTopUpNeverRepicksHeldItems:
    @pytest.mark.parametrize("strategy", ["diversity_clustering", "psychometric"])
    def test_every_item_reaches_the_annotator(self, fresh_ism, strategy):
        ids = [f"n{i:03d}" for i in range(30)]
        ism = fresh_ism({"assignment_strategy": strategy, "max_annotations_per_item": -1}, ids)
        user = InMemoryUserState("u1", max_assignments=30)
        phantom = 0
        for _ in range(40):
            before = len(user.get_assigned_instance_ids())
            if ism.assign_instances_to_user(user) and len(user.get_assigned_instance_ids()) == before:
                phantom += 1
        assert len(user.get_assigned_instance_ids()) == 30
        assert phantom == 0


def test_category_based_is_reproducible_under_any_hash_seed():
    code = (
        "import logging; logging.disable(logging.CRITICAL)\n"
        "import potato.item_state_management as mod\n"
        "from potato.item_state_management import init_item_state_manager\n"
        "from potato.user_state_management import InMemoryUserState\n"
        "mod.ITEM_STATE_MANAGER = None\n"
        "ism = init_item_state_manager({'assignment_strategy': 'category_based', 'random_seed': 7,"
        " 'max_annotations_per_item': -1, 'category_assignment': {'fallback': 'random'}})\n"
        "ism.add_items({f'n{i:02d}': {'id': f'n{i:02d}', 'text': 't'} for i in range(20)})\n"
        "u = InMemoryUserState('u1', max_assignments=20); ism.assign_instances_to_user(u)\n"
        "print(u.instance_id_ordering)\n")
    outs = {subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True,
                           env=dict(os.environ, PYTHONHASHSEED=str(seed))
                           ).stdout.strip().splitlines()[-1] for seed in (1, 2, 3)}
    assert len(outs) == 1


# ---------------------------------------------------------------------------
# Solo mode
# ---------------------------------------------------------------------------

def _solo():
    from potato.solo_mode.config import parse_solo_mode_config
    from potato.solo_mode.manager import SoloModeManager
    schemes = [{"name": "sentiment", "annotation_type": "radio", "labels": ["pos", "neg"]},
               {"name": "topic", "annotation_type": "radio", "labels": ["pos", "neg"]}]
    cfg = parse_solo_mode_config({"solo_mode": {"enabled": True, "labeling_models": []},
                                  "annotation_schemes": schemes})
    manager = SoloModeManager(cfg, {"annotation_schemes": schemes})
    manager._save_state = lambda *a, **k: None
    return manager, cfg


def _prediction(iid, schema, label, why="", version=1):
    from potato.solo_mode.manager import LLMPrediction
    return LLMPrediction(instance_id=iid, schema_name=schema, predicted_label=label,
                         confidence_score=0.9, uncertainty_score=0.1,
                         prompt_version=version, model_name="m", reasoning=why)


class TestSoloDisagreements:
    def test_an_agreeing_schema_does_not_clear_a_disagreeing_one(self):
        m, _ = _solo()
        m.predictions["i1"] = {"sentiment": _prediction("i1", "sentiment", "pos"),
                               "topic": _prediction("i1", "topic", "pos")}
        m.record_human_label("i1", "sentiment", "neg", "u")
        m.record_human_label("i1", "topic", "pos", "u")
        m.record_human_label("i1", "topic", "pos", "u")   # re-save
        assert "i1" in m.disagreement_ids

    def test_a_disagreement_is_offered_again_once_per_prompt(self, fresh_ism):
        m, _ = _solo()
        fresh_ism({}, ["i1", "i2"])
        m.predictions["i1"] = {"sentiment": _prediction("i1", "sentiment", "pos")}
        m.record_human_label("i1", "sentiment", "neg", "u")
        m.instance_selector.weights.disagreement = 1.0
        for name in ("low_confidence", "diverse", "random", "edge_case_rule",
                     "cartography", "llm_predicted"):
            setattr(m.instance_selector.weights, name, 0.0)
        assert m.get_next_instance_for_human("u") == "i1"
        assert m.get_next_instance_for_human("u") == "i2"   # reviewed under v1
        # A new prompt version produces a new answer, worth another look.
        m.predictions["i1"]["sentiment"] = _prediction("i1", "sentiment", "pos", version=2)
        assert m.get_next_instance_for_human("u") == "i1"

    def test_a_confusion_example_shows_its_own_schemas_reasoning(self):
        from potato.solo_mode.confusion_analyzer import ConfusionAnalyzer
        m, cfg = _solo()
        m.predictions["i1"] = {"topic": _prediction("i1", "topic", "pos", "topic-reasoning"),
                               "sentiment": _prediction("i1", "sentiment", "pos", "sentiment-reasoning")}
        m.record_human_label("i1", "sentiment", "neg", "u")
        cfg.confusion_analysis.min_instances_for_pattern = 1
        patterns = ConfusionAnalyzer({}, cfg).analyze(
            m.validation_tracker.get_comparison_history(), m.predictions)
        assert patterns[0].examples[0].llm_reasoning == "sentiment-reasoning"


class TestLabelingFunctions:
    def _fn(self, fid, label, keyword):
        from potato.solo_mode.labeling_functions import LabelingFunction
        return LabelingFunction(id=fid, pattern_text=keyword, condition="",
                                label=label, confidence=0.5,
                                extracted_from_reasoning=keyword)

    def test_a_keyword_is_a_whole_word(self):
        from potato.solo_mode.labeling_functions import LabelingFunctionApplier
        result = LabelingFunctionApplier().apply(
            "i1", "I know it is good", [self._fn("f1", "neg", "no")])
        assert result.abstained

    @pytest.mark.parametrize("order", [("pos", "neg"), ("neg", "pos")])
    def test_a_tie_abstains_whatever_the_order(self, order):
        from potato.solo_mode.labeling_functions import LabelingFunctionApplier
        fns = [self._fn(f"f{i}", label, "great") for i, label in enumerate(order)]
        assert LabelingFunctionApplier(vote_threshold=0.5).apply(
            "i1", "a great day", fns).abstained


class TestIclCapacity:
    def test_human_annotated_items_are_not_counted_as_unlabelled(self, fresh_ism):
        from potato.ai.icl_labeler import ICLLabeler
        fresh_ism({}, [f"i{k}" for k in range(10)])
        states = []
        for k in range(4):
            state = InMemoryUserState(f"u{k}")
            state.instance_id_to_label_to_value[f"i{k}"] = {Label("s", "x"): "x"}
            states.append(state)
        labeler = ICLLabeler.__new__(ICLLabeler)
        labeler.labeled_instance_ids = set()
        labeler.max_unlabeled_ratio = 0.5
        labeler.max_total_labels = None
        usm = SimpleNamespace(get_all_users=lambda: states,
                              get_user_state=lambda u: None)
        with patch("potato.user_state_management.get_user_state_manager", return_value=usm):
            remaining = labeler.get_remaining_label_capacity()
        assert remaining == 3   # 6 unlabelled * 0.5, none labelled yet


class TestActiveLearningColdStart:
    def test_the_llm_is_asked_about_the_schemas_labels(self, fresh_ism):
        from potato.active_learning_manager import ActiveLearningConfig, ActiveLearningManager
        ism = fresh_ism({}, ["i1", "i2"])
        manager = ActiveLearningManager.__new__(ActiveLearningManager)
        manager.logger = logging.getLogger("t")
        manager.schema_cycler = None
        manager.config = ActiveLearningConfig(
            schema_names=["topic"], cold_start_batch_size=2,
            project_config={"annotation_schemes": [
                {"name": "topic", "annotation_type": "radio",
                 "labels": [{"name": "sports"}, "politics"]}]})
        llm = MagicMock()
        llm.predict_instances.return_value = []
        with patch("potato.ai.llm_active_learning.create_llm_active_learning",
                   return_value=llm):
            try:
                manager._cold_start_reorder(ism)
            except Exception:
                pass
        assert llm.predict_instances.call_args.kwargs["label_options"] == ["sports", "politics"]

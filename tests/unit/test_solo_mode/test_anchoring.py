"""
Tests for blind-versus-shown agreement (solo_mode.suggestions).

Agreement measured while the LLM's suggestion is on screen is inflated by
anchoring, so the handoff gate reads blind agreement once there is enough.
"""

import pytest

from potato.solo_mode.anchoring import AnchoringTracker
from potato.solo_mode.config import SuggestionsConfig, parse_solo_mode_config
from potato.solo_mode.manager import LLMPrediction, SoloModeManager


SCHEMES = [{'name': 'sentiment', 'annotation_type': 'radio',
            'labels': ['positive', 'negative', 'neutral']}]


def _tracker(**kwargs):
    return AnchoringTracker(SuggestionsConfig(**kwargs), salt='study')


class TestBlindAssignment:

    def test_before_label_blinds_nothing(self):
        t = _tracker(display='before_label')
        assert not any(t.is_blind(f'i{k}') for k in range(200))

    def test_after_label_blinds_everything(self):
        t = _tracker(display='after_label')
        assert all(t.is_blind(f'i{k}') for k in range(200))

    def test_blind_sample_hits_roughly_the_rate(self):
        t = _tracker(display='blind_sample', blind_rate=0.25)
        blind = sum(t.is_blind(f'item-{k}') for k in range(4000))
        assert 0.22 < blind / 4000 < 0.28

    def test_blind_sample_is_deterministic_across_trackers(self):
        a = _tracker(display='blind_sample', blind_rate=0.3)
        b = _tracker(display='blind_sample', blind_rate=0.3)
        ids = [f'i{k}' for k in range(300)]
        assert [a.is_blind(i) for i in ids] == [b.is_blind(i) for i in ids]

    def test_salt_changes_which_items_are_blind(self):
        a = AnchoringTracker(SuggestionsConfig(display='blind_sample'), salt='one')
        b = AnchoringTracker(SuggestionsConfig(display='blind_sample'), salt='two')
        ids = [f'i{k}' for k in range(300)]
        assert [a.is_blind(i) for i in ids] != [b.is_blind(i) for i in ids]


class TestRecording:

    def test_buckets_and_gap(self):
        t = _tracker()
        for k in range(10):
            t.record(f's{k}:x', agrees=True, shown=True, accepted=k < 6)
        for k in range(10):
            t.record(f'b{k}:x', agrees=k < 6, shown=False)
        stats = t.stats()
        assert stats['shown']['agreement_rate'] == 1.0
        assert stats['blind']['agreement_rate'] == 0.6
        assert stats['gap'] == pytest.approx(0.4)
        assert stats['accept_rate'] == pytest.approx(0.6)

    def test_only_the_first_comparison_for_a_key_counts(self):
        t = _tracker()
        t.record('i1:x', agrees=False, shown=False)
        t.record('i1:x', agrees=True, shown=True)  # re-label after seeing it
        stats = t.stats()
        assert stats['blind'] == {'compared': 1, 'agreements': 0,
                                  'agreement_rate': 0.0}
        assert stats['shown']['compared'] == 0

    def test_accept_on_a_blind_item_is_not_counted(self):
        t = _tracker()
        t.record('i1:x', agrees=True, shown=False, accepted=True)
        assert t.stats()['accepted_with_button'] == 0

    def test_empty_stats_report_none_not_zero(self):
        stats = _tracker().stats()
        assert stats['blind']['agreement_rate'] is None
        assert stats['gap'] is None
        assert stats['accept_rate'] is None

    def test_round_trip(self):
        t = _tracker()
        t.record('i1:x', agrees=True, shown=True, accepted=True)
        t.record('i2:x', agrees=False, shown=False)
        t.mark_shown('i1')
        u = _tracker()
        u.load(t.to_dict())
        assert u.stats() == t.stats()
        assert u.was_shown('i1') and not u.was_shown('i2')
        u.record('i1:x', agrees=False, shown=False)
        assert u.stats()['blind']['compared'] == 1


class TestHandoffBasis:

    def test_before_label_falls_back_to_all(self):
        t = _tracker(display='before_label', minimum_blind_sample=3)
        assert t.handoff_basis() == 'all'

    @pytest.mark.parametrize('display', ['after_label', 'blind_sample'])
    def test_blinding_modes_wait_for_blind_items(self, display):
        t = _tracker(display=display, minimum_blind_sample=3)
        assert t.handoff_basis() == 'waiting'
        for k in range(3):
            t.record(f'b{k}:x', agrees=True, shown=False)
        assert t.handoff_basis() == 'blind'

    def test_before_label_switches_to_blind_when_enough_arrive(self):
        # Retroactive comparisons are blind even when nothing is withheld.
        t = _tracker(display='before_label', minimum_blind_sample=2)
        t.record('b1:x', agrees=True, shown=False)
        t.record('b2:x', agrees=True, shown=False)
        assert t.handoff_basis() == 'blind'


class TestConfig:

    def _parse(self, suggestions):
        return parse_solo_mode_config({'solo_mode': {
            'enabled': True,
            'labeling_models': [{'endpoint_type': 'openai', 'model': 'm'}],
            'suggestions': suggestions,
        }, 'annotation_schemes': SCHEMES})

    def test_defaults_keep_the_original_behaviour(self):
        s = self._parse({}).suggestions
        assert (s.display, s.blind_rate, s.minimum_blind_sample) == (
            'before_label', 0.2, 20)

    def test_valid_values(self):
        cfg = self._parse({'display': 'blind_sample', 'blind_rate': 0.5,
                           'minimum_blind_sample': 10})
        assert cfg.validate() == []

    @pytest.mark.parametrize('suggestions, fragment', [
        ({'display': 'sometimes'}, 'suggestions.display'),
        ({'blind_rate': 0}, 'blind_rate'),
        ({'blind_rate': 1.5}, 'blind_rate'),
        ({'blind_rate': 'half'}, 'blind_rate'),
        ({'minimum_blind_sample': 0}, 'minimum_blind_sample'),
        ({'minimum_blind_sample': True}, 'minimum_blind_sample'),
    ])
    def test_invalid_values(self, suggestions, fragment):
        errors = self._parse(suggestions).validate()
        assert any(fragment in e for e in errors), errors


class TestManagerHandoff:
    """The handoff reads blind agreement, so anchored agreement cannot end it."""

    def _manager(self, **suggestions):
        cfg = parse_solo_mode_config({'solo_mode': {
            'enabled': True, 'labeling_models': [],
            'thresholds': {'end_human_annotation_agreement': 0.9,
                           'minimum_validation_sample': 4},
            'suggestions': suggestions,
        }, 'annotation_schemes': SCHEMES})
        return SoloModeManager(cfg, {'annotation_schemes': SCHEMES})

    def _predict(self, mgr, iid, label='positive'):
        mgr.set_llm_prediction(iid, 'sentiment', LLMPrediction(
            instance_id=iid, schema_name='sentiment', predicted_label=label,
            confidence_score=0.9, uncertainty_score=0.1,
            prompt_version=1, model_name='m'))

    def _label(self, mgr, iid, label, visible, accepted=False):
        self._predict(mgr, iid)
        mgr.record_human_label(iid, 'sentiment', label, 'u',
                               suggestion_visible=visible,
                               accepted_suggestion=accepted)

    def test_anchored_agreement_does_not_hand_over(self):
        mgr = self._manager(display='blind_sample', minimum_blind_sample=4)
        # Perfect agreement while shown, poor agreement blind. Overall
        # agreement (41/44) clears the 0.9 threshold on its own.
        for k in range(40):
            self._label(mgr, f's{k}', 'positive', visible=True, accepted=True)
        for k in range(4):
            self._label(mgr, f'b{k}', 'positive' if k == 0 else 'negative',
                        visible=False)
        assert mgr.get_agreement_metrics().agreement_rate == pytest.approx(41 / 44)
        stats = mgr.get_anchoring_stats()
        assert stats['handoff_basis'] == 'blind'
        assert stats['blind']['agreement_rate'] == 0.25
        assert not mgr.should_end_human_annotation()

    def test_high_blind_agreement_hands_over(self):
        mgr = self._manager(display='blind_sample', minimum_blind_sample=4)
        for k in range(4):
            self._label(mgr, f'b{k}', 'positive', visible=False)
        assert mgr.should_end_human_annotation()

    def test_blinding_mode_waits_for_the_blind_sample(self):
        mgr = self._manager(display='blind_sample', minimum_blind_sample=4)
        for k in range(10):
            self._label(mgr, f's{k}', 'positive', visible=True)
        assert mgr.get_agreement_metrics().agreement_rate == 1.0
        # A corpus with plenty of blind items still to label: the handoff waits.
        from types import SimpleNamespace
        from unittest.mock import patch
        ids = [f's{k}' for k in range(10)] + [f'u{k}' for k in range(200)]
        with patch('potato.item_state_management.get_item_state_manager',
                   return_value=SimpleNamespace(instance_id_ordering=ids)):
            assert mgr.get_anchoring_stats()['handoff_basis'] == 'waiting'
            assert not mgr.should_end_human_annotation()

    def test_before_label_without_blind_items_keeps_old_gate(self):
        mgr = self._manager(display='before_label', minimum_blind_sample=4)
        for k in range(4):
            self._label(mgr, f's{k}', 'positive', visible=True)
        assert mgr.should_end_human_annotation()

    def test_unknown_visibility_stays_out_of_the_split(self):
        mgr = self._manager()
        self._predict(mgr, 'i1')
        mgr.record_human_label('i1', 'sentiment', 'positive', 'u')
        stats = mgr.get_anchoring_stats()
        assert stats['shown']['compared'] == stats['blind']['compared'] == 0

    def test_retroactive_comparison_is_blind_unless_a_suggestion_was_seen(self):
        mgr = self._manager()
        mgr._get_stored_human_label = lambda iid, schema: 'positive'
        # Human labels before any prediction exists.
        mgr.record_human_label('i1', 'sentiment', 'positive', 'u',
                               suggestion_visible=False)
        self._predict(mgr, 'i1')
        mgr._retroactive_compare('i1', 'sentiment')
        assert mgr.get_anchoring_stats()['blind']['compared'] == 1

        # A human who saw an earlier suggestion for the item is not blind.
        mgr.record_human_label('i2', 'sentiment', 'positive', 'u',
                               suggestion_visible=True)
        self._predict(mgr, 'i2')
        mgr._retroactive_compare('i2', 'sentiment')
        assert mgr.get_anchoring_stats()['shown']['compared'] == 1

    def test_state_survives_a_restart(self, tmp_path):
        cfg = parse_solo_mode_config({'solo_mode': {
            'enabled': True, 'labeling_models': [], 'state_dir': str(tmp_path),
            'suggestions': {'display': 'blind_sample'},
        }, 'annotation_schemes': SCHEMES})
        mgr = SoloModeManager(cfg, {'annotation_schemes': SCHEMES})
        self._label(mgr, 'b1', 'negative', visible=False)
        self._label(mgr, 's1', 'positive', visible=True, accepted=True)
        before = mgr.get_anchoring_stats()

        mgr2 = SoloModeManager(cfg, {'annotation_schemes': SCHEMES})
        mgr2.load_state()
        assert mgr2.get_anchoring_stats() == before


class TestSmallCorpus:
    """A corpus with fewer blind items than minimum_blind_sample must still end."""

    def test_basis_is_blind_short_when_the_minimum_cannot_be_reached(self):
        t = _tracker(display='blind_sample', minimum_blind_sample=5)
        t.record('b1:x', agrees=True, shown=False)
        assert t.handoff_basis(blind_items_left=4) == 'waiting'      # 1 + 4 reaches 5
        assert t.handoff_basis(blind_items_left=3) == 'blind_short'  # 1 + 3 cannot
        assert t.handoff_basis(blind_items_left=None) == 'waiting'   # unknown

    def test_gap_needs_enough_of_each(self):
        t = _tracker()
        for k in range(10):
            t.record(f's{k}:x', agrees=True, shown=True)
        t.record('b0:x', agrees=False, shown=False)
        assert t.stats()['gap'] is None
        for k in range(1, 5):
            t.record(f'b{k}:x', agrees=False, shown=False)
        assert t.stats()['gap'] == pytest.approx(1.0)

    def test_manager_hands_over_on_the_blind_items_there_are(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        mgr = TestManagerHandoff()._manager(display='blind_sample',
                                            minimum_blind_sample=5)
        h = TestManagerHandoff()
        for k in range(3):
            h._label(mgr, f's{k}', 'positive', visible=True)
        h._label(mgr, 'b0', 'positive', visible=False)
        # Every item is labelled, so no more blind comparisons can come.
        ism = SimpleNamespace(instance_id_ordering=['s0', 's1', 's2', 'b0'])
        with patch('potato.item_state_management.get_item_state_manager',
                   return_value=ism):
            assert mgr.get_anchoring_stats()['handoff_basis'] == 'blind_short'
            assert mgr.should_end_human_annotation()

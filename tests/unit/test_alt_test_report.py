"""
The alt-test on a live study: labels gathered from user states, machine vs humans.

Uses user states in the real storage shape (flat {Label: value}) so the
report reads labels exactly as /admin/iaa does.
"""

import random
from collections import defaultdict

import pytest

from potato.item_state_management import Label
from potato.server_utils import alt_test_report


class FakeUserState:
    def __init__(self, per_item, origin=None):
        self.store = {iid: {Label(schema, name): value
                            for (schema, name), value in entries.items()}
                      for iid, entries in per_item.items()}
        self.origin = origin

    def get_label_annotations(self, instance_id):
        return self.store.get(instance_id, {})

    def get_span_annotations(self, instance_id):
        return {}


class FakeUSM:
    def __init__(self, states):
        self.states = states

    def get_user_state(self, uid):
        return self.states.get(uid)

    def get_user_ids(self):
        return list(self.states)


class FakeISM:
    def __init__(self, states):
        self.instance_annotators = defaultdict(set)
        for uid, state in states.items():
            for iid in state.store:
                self.instance_annotators[iid].add(uid)


LABELS = ['positive', 'negative', 'neutral']
CONFIG = {'annotation_schemes': [
    {'name': 'sentiment', 'annotation_type': 'radio', 'labels': LABELS},
    {'name': 'quality', 'annotation_type': 'likert', 'size': 5},
    {'name': 'spans', 'annotation_type': 'span', 'labels': ['X']},
]}
LLM_ORIGIN = {'kind': 'llm', 'id': 'gemma', 'version': '4'}


def _study(machine_copies_majority, n_items=60, n_humans=4, seed=0):
    rng = random.Random(seed)
    truth = [rng.choice(LABELS) for _ in range(n_items)]
    states = {}
    for h in range(n_humans):
        per = {}
        for k, t in enumerate(truth):
            # Each human matches the truth 80% of the time.
            label = t if rng.random() < 0.8 else rng.choice(LABELS)
            per[f'i{k}'] = {('sentiment', label): True}
        states[f'human{h}'] = FakeUserState(per)
    per = {}
    for k, t in enumerate(truth):
        label = t if machine_copies_majority else rng.choice(LABELS)
        per[f'i{k}'] = {('sentiment', label): True}
    states['llm'] = FakeUserState(per, origin=LLM_ORIGIN)
    return FakeISM(states), FakeUSM(states)


def test_a_machine_that_tracks_the_truth_passes():
    ism, usm = _study(machine_copies_majority=True)
    report = alt_test_report.build_report(ism, usm, CONFIG, 'llm', 'sentiment')
    assert report['passed'] is True
    assert report['winning_rate'] >= 0.5
    assert report['metric'] == 'accuracy'
    assert report['annotator_origin']['kind'] == 'llm'
    assert report['n_annotators'] == 4


def test_a_random_machine_fails():
    ism, usm = _study(machine_copies_majority=False)
    report = alt_test_report.build_report(ism, usm, CONFIG, 'llm', 'sentiment')
    assert report['passed'] is False


def test_too_few_items_is_reported_not_scored():
    ism, usm = _study(machine_copies_majority=True, n_items=10)
    report = alt_test_report.build_report(ism, usm, CONFIG, 'llm', 'sentiment')
    assert report['passed'] is None
    assert report['insufficient']


def test_a_human_cannot_be_the_annotator_under_test():
    ism, usm = _study(machine_copies_majority=True)
    with pytest.raises(ValueError, match='not a declared machine'):
        alt_test_report.build_report(ism, usm, CONFIG, 'human0', 'sentiment')


def test_unscorable_scheme_is_refused():
    ism, usm = _study(machine_copies_majority=True)
    with pytest.raises(ValueError, match="'span'"):
        alt_test_report.build_report(ism, usm, CONFIG, 'llm', 'spans')


def test_likert_uses_the_numeric_metric():
    rng = random.Random(1)
    states = {}
    truth = [rng.randint(1, 5) for _ in range(40)]
    for h in range(3):
        states[f'h{h}'] = FakeUserState({
            f'i{k}': {('quality', str(max(1, min(5, t + rng.choice([-1, 0, 0, 1]))))): str(t)}
            for k, t in enumerate(truth)})
    states['llm'] = FakeUserState(
        {f'i{k}': {('quality', str(t)): str(t)} for k, t in enumerate(truth)},
        origin=LLM_ORIGIN)
    report = alt_test_report.build_report(FakeISM(states), FakeUSM(states),
                                          CONFIG, 'llm', 'quality')
    assert report['metric'] == 'neg_rmse'
    assert report['passed'] is True


def test_declared_machines_lists_only_machines():
    _, usm = _study(machine_copies_majority=True)
    assert set(alt_test_report.declared_machines(usm)) == {'llm'}

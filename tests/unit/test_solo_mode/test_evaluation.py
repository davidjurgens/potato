"""
Tests for gold-set evaluation, prompt trials and the sensitivity check.

Jobs run in a thread; the tests wait on the job rather than sleeping a fixed
time.
"""

import json
import time
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from potato.server_utils.config_module import ConfigSecurityError
from potato.solo_mode.config import parse_solo_mode_config
from potato.solo_mode.evaluation import (
    JobRegistry, load_gold, resolve_gold_path, score,
)
from potato.solo_mode.manager import PromptVersion, SoloModeManager


class TestScore:

    def test_accuracy_macro_f1_and_per_class(self):
        gold = {'1': 'pos', '2': 'pos', '3': 'neg', '4': 'neg'}
        pred = {'1': 'pos', '2': 'neg', '3': 'neg', '4': 'neg'}
        r = score(pred, gold, 'radio')
        assert r['accuracy'] == 0.75
        assert r['per_class']['pos'] == {'precision': 1.0, 'recall': 0.5,
                                         'f1': pytest.approx(2 / 3), 'support': 2}
        assert r['per_class']['neg']['precision'] == pytest.approx(2 / 3)
        assert r['macro_f1'] == pytest.approx((2 / 3 + 0.8) / 2)
        assert r['confusion'] == {'neg': {'neg': 2}, 'pos': {'pos': 1, 'neg': 1}}

    def test_a_failed_item_counts_as_wrong(self):
        r = score({'1': 'pos', '2': None}, {'1': 'pos', '2': 'pos'}, 'radio')
        assert r['accuracy'] == 0.5 and r['n_errors'] == 1
        assert r['confusion']['pos'] == {'pos': 1, '(no label)': 1}

    def test_invented_label_does_not_pad_macro_f1(self):
        r = score({'1': 'pos', '2': 'weird'}, {'1': 'pos', '2': 'pos'}, 'radio')
        assert r['per_class']['weird']['precision'] == 0.0
        assert r['macro_f1'] == pytest.approx(2 / 3)  # pos only

    def test_numbers_and_strings_compare_equal(self):
        assert score({'1': 3}, {'1': '3'}, 'likert')['accuracy'] == 1.0

    def test_multiselect(self):
        gold = {'1': ['a', 'b'], '2': '["a"]'}
        pred = {'1': '["b", "a"]', '2': 'a, c'}
        r = score(pred, gold, 'multiselect')
        assert r['accuracy'] == 0.5  # exact set match
        assert r['per_class']['c']['precision'] == 0.0
        assert r['micro_f1'] == pytest.approx(2 * 3 / (2 * 3 + 1 + 0))


class TestLoadGold:

    def test_json_jsonl_and_csv(self, tmp_path):
        (tmp_path / 'g.json').write_text(json.dumps([
            {'id': 1, 'label': 'pos'}, {'id': 2, 'label': ''}, {'label': 'x'}]))
        (tmp_path / 'g.jsonl').write_text('{"id": "a", "gold": "neg", "t": "hi"}\n')
        (tmp_path / 'g.csv').write_text('id,label\nc1,pos\n')
        items = load_gold('g.json', str(tmp_path))
        assert [(i.instance_id, i.label) for i in items] == [('1', 'pos')]
        items = load_gold('g.jsonl', str(tmp_path), label_key='gold', text_key='t')
        assert (items[0].label, items[0].text) == ('neg', 'hi')
        assert load_gold('g.csv', str(tmp_path))[0].instance_id == 'c1'

    def test_path_outside_the_project_is_refused(self, tmp_path):
        with pytest.raises(ConfigSecurityError):
            resolve_gold_path('/etc/passwd', str(tmp_path))


def _wait(registry_or_mgr, job_id, timeout=10):
    getter = (registry_or_mgr.get_job if hasattr(registry_or_mgr, 'get_job')
              else lambda j: registry_or_mgr.get(j).to_dict())
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = getter(job_id)
        if job['status'] != 'running':
            return job
        time.sleep(0.02)
    raise AssertionError('job did not finish')


class TestJobRegistry:

    def test_result_and_failure_are_reported(self):
        reg = JobRegistry()
        ok = reg.start('a', 1, lambda job: 42)
        assert _wait(reg, ok.id)['result'] == 42
        bad = reg.start('b', 1, lambda job: 1 / 0)
        failed = _wait(reg, bad.id)
        assert failed['status'] == 'failed' and 'division' in failed['error']

    def test_one_running_job_per_kind(self):
        reg = JobRegistry()
        import threading
        gate = threading.Event()
        first = reg.start('k', 1, lambda job: gate.wait(5))
        second = reg.start('k', 1, lambda job: None)
        assert second.id == first.id
        gate.set()
        _wait(reg, first.id)


SCHEMES = [{'name': 'sentiment', 'annotation_type': 'radio',
            'labels': ['pos', 'neg']}]
TEXTS = {'g1': 'great', 'g2': 'awful', 'g3': 'fine', 'u1': 'nice', 'u2': 'bad'}


def _manager(tmp_path, gold=True):
    (tmp_path / 'gold.json').write_text(json.dumps([
        {'id': 'g1', 'label': 'pos'}, {'id': 'g2', 'label': 'neg'},
        {'id': 'g3', 'label': 'pos'}]))
    sm = {'enabled': True,
          'labeling_models': [{'endpoint_type': 'openai', 'model': 'm'}]}
    if gold:
        sm['gold'] = {'file': 'gold.json'}
    cfg = parse_solo_mode_config({'solo_mode': sm, 'annotation_schemes': SCHEMES})
    mgr = SoloModeManager(cfg, {'annotation_schemes': SCHEMES, 'task_dir': str(tmp_path)})
    mgr.prompt_versions = [PromptVersion(1, 'Label sentiment v1', datetime(2026, 1, 1), 'user'),
                           PromptVersion(2, 'Label sentiment v2', datetime(2026, 1, 2), 'user')]
    mgr.current_prompt_version = 2
    mgr._get_instance_text = lambda iid: TEXTS.get(iid, '')
    return mgr


def _labeler(answers):
    """A labeling thread whose answer depends on the prompt and the text."""
    calls = []

    def label(iid, text, schema, endpoint=None, prompt_override=None):
        calls.append((iid, prompt_override))
        value = answers(prompt_override, text)
        return SimpleNamespace(label=value, confidence=0.8, reasoning='r',
                               error=None if value else 'no label')
    return SimpleNamespace(_label_instance=label,
                           _get_valid_labels=lambda s: ['pos', 'neg']), calls


class TestGoldEvaluation:

    def test_each_version_is_scored_with_its_own_prompt(self, tmp_path):
        mgr = _manager(tmp_path)
        # v1 calls everything positive; v2 gets "fine" wrong only.
        labeler, calls = _labeler(lambda prompt, text: (
            'pos' if 'v1' in prompt else {'great': 'pos', 'awful': 'neg',
                                           'fine': 'neg'}[text]))
        with patch.object(SoloModeManager, 'llm_labeling_thread', labeler):
            j1 = _wait(mgr, mgr.start_gold_evaluation(1).id)
            j2 = _wait(mgr, mgr.start_gold_evaluation().id)
        assert j1['result']['accuracy'] == pytest.approx(2 / 3)
        assert j2['result']['accuracy'] == pytest.approx(2 / 3)
        assert j2['result']['prompt_version'] == 2
        assert {p for _, p in calls} == {'Label sentiment v1', 'Label sentiment v2'}
        status = mgr.get_gold_status()
        assert status['configured'] and status['n_items'] == 3
        assert set(status['results_by_version']) == {'1', '2'}

    def test_no_gold_set_is_an_error(self, tmp_path):
        with pytest.raises(ValueError, match='gold'):
            _manager(tmp_path, gold=False).start_gold_evaluation()

    def test_unknown_version_is_an_error(self, tmp_path):
        with pytest.raises(ValueError, match='No prompt version 9'):
            _manager(tmp_path).start_gold_evaluation(9)

    def test_results_survive_a_restart(self, tmp_path):
        mgr = _manager(tmp_path)
        mgr.config.state_dir = str(tmp_path / 'state')
        labeler, _ = _labeler(lambda p, t: 'pos')
        with patch.object(SoloModeManager, 'llm_labeling_thread', labeler):
            _wait(mgr, mgr.start_gold_evaluation().id)
        again = _manager(tmp_path)
        again.config.state_dir = str(tmp_path / 'state')
        again.load_state()
        assert '2' in again.get_gold_status()['results_by_version']


class TestTrial:

    def test_trial_reports_rows_and_distribution(self, tmp_path):
        mgr = _manager(tmp_path)
        ism = SimpleNamespace(instance_id_ordering=list(TEXTS))
        mgr.human_labeled_ids = {'g1', 'g2', 'g3'}
        labeler, calls = _labeler(lambda p, t: 'neg' if t == 'bad' else 'pos')
        with patch('potato.item_state_management.get_item_state_manager',
                   return_value=ism), \
                patch.object(SoloModeManager, 'llm_labeling_thread', labeler):
            job = _wait(mgr, mgr.start_prompt_trial(5, 'Draft prompt').id)
        result = job['result']
        # Only unlabelled items are tried.
        assert {r['instance_id'] for r in result['rows']} == {'u1', 'u2'}
        assert result['label_distribution'] == {'pos': 1, 'neg': 1}
        assert {p for _, p in calls} == {'Draft prompt'}


class TestSensitivity:

    def test_paraphrases_are_labelled_and_compared(self, tmp_path):
        mgr = _manager(tmp_path)
        reviser = MagicMock()
        reviser.query.return_value = json.dumps([
            'Label the sentiment as pos or neg, version two of the prompt text',
            'Decide pos or neg for this sentiment, version three of the prompt'])
        labeler, _ = _labeler(lambda p, t: 'neg' if ('three' in p and t == 'great')
                              else ('pos' if t in ('great', 'fine') else 'neg'))
        with patch.object(SoloModeManager, 'llm_labeling_thread', labeler), \
                patch.object(mgr.prompt_manager, '_get_revision_endpoint',
                             return_value=reviser):
            job = _wait(mgr, mgr.start_sensitivity_check(2, 3).id)
        assert job['status'] == 'done', job['error']
        result = job['result']
        assert result['n_variants'] == 3
        assert result['flip_rate'] == pytest.approx(1 / 3)
        assert len(result['variants']) == 2

"""Solo-mode UX fixes: skippable contrast sets, one on-demand LLM call per
item (and the background batch yielding to it), and the in-prompt examples
block being clearly fenced off from the item to label."""

import threading
import time

from potato.solo_mode.config import parse_solo_mode_config
from potato.solo_mode.contrast_sets import ContrastPair, ContrastSetGenerator
from potato.solo_mode.llm_labeler import LabelingResult, format_icl_section
from potato.solo_mode.manager import SoloModeManager

SCHEMES = [{"name": "frame", "annotation_type": "radio",
            "labels": ["Episodic", "Thematic"]}]


def _pair(pid):
    return ContrastPair(id=pid, source_case_id="ec" + pid, label_a="Episodic",
                        label_b="Thematic", original_text="orig " + pid,
                        edited_text="", changed_span="", proposed_label="Thematic")


class TestContrastSkip:
    def _gen(self):
        g = ContrastSetGenerator({}, None)
        for pid in ("a", "b", "c"):
            g.pairs[pid] = _pair(pid)
        return g

    def test_skip_one_leaves_queue_but_is_not_reviewed(self):
        g = self._gen()
        assert g.skip_pair("a") == 1
        assert [p.id for p in g.get_unreviewed_pairs()] == ["b", "c"]
        assert g.get_reviewed_pairs() == []          # skipped teaches nothing
        assert g.get_status()["skipped"] == 1

    def test_skip_all_keeps_written_pairs_for_rules(self):
        g = self._gen()
        assert g.record_human_edit("a", "edited a", notes="why")
        assert g.skip_pair(None) == 2
        assert g.get_unreviewed_pairs() == []
        assert [p.id for p in g.get_reviewed_pairs()] == ["a"]


def _manager():
    cfg = parse_solo_mode_config({"solo_mode": {"enabled": True, "labeling_models": []},
                                  "annotation_schemes": SCHEMES})
    m = SoloModeManager(cfg, {"annotation_schemes": SCHEMES})
    m._save_state = lambda *a, **k: None
    m._get_instance_text = lambda iid: "text of " + iid
    return m


class _SlowLabeler:
    def __init__(self, delay=0.3):
        self.calls = 0
        self.delay = delay

    def _label_instance(self, instance_id, text, schema_name):
        self.calls += 1
        time.sleep(self.delay)
        return LabelingResult(instance_id=instance_id, schema_name=schema_name,
                              label="Thematic", confidence=0.9, uncertainty=0.1,
                              reasoning="r", prompt_version=1, model_name="m")


class TestOnDemand:
    def test_overlapping_requests_make_one_llm_call(self):
        m = _manager()
        labeler = _SlowLabeler()
        m._llm_labeling_thread = labeler
        out = []
        threads = [threading.Thread(target=lambda: out.append(
            m.get_or_create_llm_suggestion("i1"))) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(5)
        assert labeler.calls == 1
        assert all(o and o.get("label") == "Thematic" for o in out)

    def test_background_waits_while_on_demand_runs(self):
        m = _manager()
        m._llm_labeling_thread = _SlowLabeler(delay=0.4)
        t = threading.Thread(target=lambda: m.get_or_create_llm_suggestion("i1"))
        t.start()
        time.sleep(0.05)
        assert not m._on_demand_idle.is_set()
        start = time.time()
        m._wait_for_on_demand_idle(timeout=5)
        assert time.time() - start > 0.2           # actually waited
        assert m._on_demand_idle.is_set()
        t.join(5)


def test_icl_section_is_fenced_off():
    s = format_icl_section([{"text": "an example", "label": "Episodic"}])
    assert s.startswith("## Examples")
    assert "do not label these" in s
    assert 'Example 1 text: "an example"' in s
    assert "Label ONLY the text below" in s

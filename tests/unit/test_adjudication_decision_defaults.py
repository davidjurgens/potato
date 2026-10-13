"""A stored adjudication decision reloads with the confidence it was saved with.

``AdjudicationDecision.from_dict`` defaulted a missing confidence to "medium",
so a record saved without one reloaded -- into the page and into every export
built from the reloaded object -- as a choice nobody made.
"""

from potato.adjudication import AdjudicationDecision
from potato.routes import _adjudication_text_preview


def _record(**extra):
    base = {
        "instance_id": "item_1",
        "adjudicator_id": "lead",
        "timestamp": "2026-10-08T00:00:00",
        "label_decisions": {"sentiment": "positive"},
    }
    base.update(extra)
    return base


def test_missing_confidence_stays_missing():
    assert AdjudicationDecision.from_dict(_record()).confidence == ""


def test_saved_confidence_round_trips():
    d = AdjudicationDecision.from_dict(_record(confidence="low"))
    assert d.confidence == "low"
    assert AdjudicationDecision.from_dict(d.to_dict()).confidence == "low"


def test_queue_preview_is_one_plain_line():
    preview = _adjudication_text_preview(
        "<p>Speaker&nbsp;A:\n  <b>hello</b> &amp; welcome</p>")
    assert "<" not in preview and "\n" not in preview
    assert preview.startswith("Speaker")
    assert "hello & welcome" in preview


def test_queue_preview_is_truncated():
    preview = _adjudication_text_preview("word " * 100, limit=40)
    assert len(preview) == 40
    assert preview.endswith("\u2026")


def test_queue_preview_of_non_text_is_empty():
    assert _adjudication_text_preview(None) == ""
    assert _adjudication_text_preview({"a": 1}) == ""

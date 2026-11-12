"""
Smaller gate rules: the attention-check picker, language codes, and which
attention failures stand.
"""

import pytest

from potato.server_utils.i18n import resolve_language_code, resolve_ui_language


@pytest.mark.parametrize("code,expected", [
    ("pt-BR", "pt"), ("ES", "es"), ("zh_CN", "zh"), ("en", "en"), ("Fr-ca", "fr"),
    ("xx", None), ("../etc", None),
])
def test_language_tags_are_case_insensitive(code, expected):
    """RFC 5646 section 2.1.1: tags are case-insensitive."""
    assert resolve_language_code(code) == expected


def test_a_regional_tag_renders_in_its_language():
    spanish = resolve_ui_language("es", {"html_lang": "en", "next": "Next"})
    assert resolve_ui_language("ES", {"html_lang": "en", "next": "Next"}) == spanish
    assert spanish["html_lang"] != "en"


def _qc(tmp_name, block_threshold=2):
    import json
    import os
    from potato.quality_control import QualityControlManager
    from tests.helpers.test_utils import create_test_directory
    d = create_test_directory(tmp_name)
    with open(os.path.join(d, "attn.json"), "w") as f:
        json.dump([{"id": "a1", "text": "x", "expected_answer": {"s": "yes"}},
                   {"id": "a2", "text": "x", "expected_answer": {"s": "yes"}}], f)
    return QualityControlManager({
        "attention_checks": {"enabled": True, "items_file": "attn.json", "frequency": 1,
                             "failure_handling": {"warn_threshold": 1,
                                                  "block_threshold": block_threshold}},
        "output_annotation_dir": os.path.join(d, "out")}, d)


class TestAttentionPicker:
    def test_a_check_already_in_the_queue_is_not_picked(self):
        qc = _qc("tg2_picker")
        qc.user_items_since_attention["u"] = 5
        assert qc.get_attention_check_item("u", exclude={"a1"})["id"] == "a2"

    def test_when_nothing_fits_the_counter_is_kept(self):
        qc = _qc("tg2_picker_none")
        qc.user_items_since_attention["u"] = 5
        assert qc.get_attention_check_item("u", exclude={"a1", "a2"}) is None
        assert qc.user_items_since_attention["u"] == 5


class TestWhichFailuresStand:
    def test_a_misclick_corrected_before_any_verdict_counts_as_a_pass(self):
        qc = _qc("tg2_misclick", block_threshold=5)
        qc.qc_config.attention_warn_threshold = 5
        qc.validate_attention_response("u", "a1", {"s": "no"})
        assert qc.validate_attention_response("u", "a1", {"s": "yes"})["passed"]

    def test_a_failure_the_participant_was_told_about_stands(self):
        qc = _qc("tg2_told")
        first = qc.validate_attention_response("u", "a1", {"s": "no"})
        assert first.get("warning")
        assert not qc.validate_attention_response("u", "a1", {"s": "yes"})["passed"]

    def test_a_block_survives_a_restart(self):
        qc = _qc("tg2_block_persist")
        qc.validate_attention_response("u", "a1", {"s": "no"})
        qc.validate_attention_response("u", "a2", {"s": "no"})
        assert qc.is_user_blocked("u")
        reloaded = type(qc)(qc.config, qc.base_dir)
        assert "u" in reloaded.blocked_users and reloaded.is_user_blocked("u")

"""
Unit tests for the ``keystroke_logging`` config block.

The security-relevant assertion is
:meth:`TestClientConfig.test_detection_thresholds_never_reach_the_client` —
shipping thresholds to the browser would tell an annotator exactly how slowly to
paste in order to stay under the flag.
"""

import pytest

from potato.server_utils.config_module import (
    KEYSTROKE_LOGGING_DEFAULTS,
    ConfigValidationError,
    get_keystroke_client_config,
    get_keystroke_logging_config,
    validate_keystroke_logging_config,
)


class TestDefaults:
    def test_absent_block_is_disabled(self):
        """Upgrading Potato must not silently start recording annotators."""
        assert get_keystroke_logging_config({})["enabled"] is False
        assert KEYSTROKE_LOGGING_DEFAULTS["enabled"] is False

    def test_disclosure_defaults_on(self):
        assert get_keystroke_logging_config({})["disclose_to_annotators"] is True

    def test_absent_block_still_returns_an_indexable_dict(self):
        cfg = get_keystroke_logging_config({})
        assert cfg["detection"]["on_external_insert"] == "flag"
        assert cfg["pause_thresholds_ms"]

    def test_none_config_tolerated(self):
        assert get_keystroke_logging_config(None)["enabled"] is False

    def test_non_blocking_by_default(self):
        """Default is to record and let the researcher decide, not to block."""
        assert get_keystroke_logging_config({})["detection"]["on_external_insert"] == "flag"


class TestMerging:
    def test_partial_block_merges_over_defaults(self):
        cfg = get_keystroke_logging_config({"keystroke_logging": {"enabled": True}})
        assert cfg["enabled"] is True
        assert cfg["fidelity"] == "events"

    def test_detection_sub_block_merges_rather_than_replaces(self):
        cfg = get_keystroke_logging_config({
            "keystroke_logging": {"detection": {"calibrate": True}}})
        assert cfg["detection"]["calibrate"] is True
        assert cfg["detection"]["enabled"] is True
        assert cfg["detection"]["on_external_insert"] == "flag"

    def test_defaults_are_not_mutated_between_calls(self):
        a = get_keystroke_logging_config({"keystroke_logging": {"enabled": True}})
        a["detection"]["enabled"] = False
        assert get_keystroke_logging_config({})["detection"]["enabled"] is True


class TestValidation:
    def test_absent_block_passes(self):
        validate_keystroke_logging_config({})

    def test_valid_block_passes(self):
        validate_keystroke_logging_config({"keystroke_logging": {
            "enabled": True, "fidelity": "summary",
            "include_schemas": ["rationale"], "pause_thresholds_ms": [1000],
            "detection": {"enabled": True, "on_external_insert": "warn"},
        }})

    def test_non_mapping_rejected(self):
        with pytest.raises(ConfigValidationError, match="must be a mapping"):
            validate_keystroke_logging_config({"keystroke_logging": "yes"})

    @pytest.mark.parametrize("fidelity", ["off", "summary", "events"])
    def test_valid_fidelities(self, fidelity):
        validate_keystroke_logging_config(
            {"keystroke_logging": {"fidelity": fidelity}})

    def test_invalid_fidelity_rejected(self):
        with pytest.raises(ConfigValidationError, match="fidelity"):
            validate_keystroke_logging_config(
                {"keystroke_logging": {"fidelity": "everything"}})

    @pytest.mark.parametrize("key", ["enabled", "store_events",
                                     "classify_paste_source",
                                     "disclose_to_annotators"])
    def test_non_boolean_rejected(self, key):
        with pytest.raises(ConfigValidationError, match=key):
            validate_keystroke_logging_config({"keystroke_logging": {key: "yes"}})

    @pytest.mark.parametrize("key", ["include_schemas", "exclude_schemas"])
    def test_non_list_schemas_rejected(self, key):
        with pytest.raises(ConfigValidationError, match=key):
            validate_keystroke_logging_config({"keystroke_logging": {key: "rationale"}})

    def test_empty_pause_thresholds_rejected(self):
        with pytest.raises(ConfigValidationError, match="pause_thresholds_ms"):
            validate_keystroke_logging_config(
                {"keystroke_logging": {"pause_thresholds_ms": []}})

    def test_negative_pause_threshold_rejected(self):
        with pytest.raises(ConfigValidationError, match="positive integers"):
            validate_keystroke_logging_config(
                {"keystroke_logging": {"pause_thresholds_ms": [-1]}})

    def test_invalid_external_insert_action_rejected(self):
        with pytest.raises(ConfigValidationError, match="on_external_insert"):
            validate_keystroke_logging_config(
                {"keystroke_logging": {"detection": {"on_external_insert": "destroy"}}})

    def test_non_mapping_thresholds_rejected(self):
        with pytest.raises(ConfigValidationError, match="thresholds"):
            validate_keystroke_logging_config(
                {"keystroke_logging": {"detection": {"thresholds": [0.5]}}})

    def test_all_errors_reported_together(self):
        """A misconfigured block should not need three round trips to fix."""
        with pytest.raises(ConfigValidationError) as exc:
            validate_keystroke_logging_config({"keystroke_logging": {
                "fidelity": "nope", "enabled": "yes", "include_schemas": "x"}})
        message = str(exc.value)
        assert "fidelity" in message
        assert "enabled" in message
        assert "include_schemas" in message

    def test_silent_collection_warns(self, caplog):
        validate_keystroke_logging_config({"keystroke_logging": {
            "enabled": True, "disclose_to_annotators": False}})
        assert any("ethics approval" in r.message or "consent" in r.message
                   for r in caplog.records)

    def test_contradictory_store_events_warns(self, caplog):
        validate_keystroke_logging_config({"keystroke_logging": {
            "enabled": True, "fidelity": "summary", "store_events": True}})
        assert any("no raw event streams" in r.message for r in caplog.records)


class TestClientConfig:
    def test_detection_thresholds_never_reach_the_client(self):
        """Publishing thresholds would tell an annotator exactly how to stay
        under the flag."""
        client = get_keystroke_client_config({"keystroke_logging": {
            "enabled": True,
            "detection": {"thresholds": {"paste_dominant.pasted_fraction": 0.4}},
        }})
        assert "thresholds" not in client
        assert "detection" not in client
        assert "0.4" not in str(client)

    def test_client_gets_what_it_needs(self):
        client = get_keystroke_client_config({"keystroke_logging": {"enabled": True}})
        for key in ("enabled", "fidelity", "include_schemas", "exclude_schemas",
                    "classify_paste_source", "idle_session_ms",
                    "flush_interval_ms", "on_external_insert"):
            assert key in client

    def test_client_config_is_json_serializable(self):
        import json
        json.dumps(get_keystroke_client_config({"keystroke_logging": {"enabled": True}}))

    def test_disabled_project_reports_disabled(self):
        assert get_keystroke_client_config({})["enabled"] is False

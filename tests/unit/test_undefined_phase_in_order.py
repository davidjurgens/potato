"""A phase named in `phases.order` but never defined must not take the study down.

`potato validate --strict` said "OK — no issues found", the boot log said it had
skipped the phase, and then every request — `/` included — returned 500. The
phase loader dropped the phase from `phase_type_to_name_to_page` but left the
name in `phases.order`, and `/register` read that list directly to decide where
to park a new annotator. `get_phase_html_fname` then raised `KeyError: 'consent'`
on a phase with no page.

Only fatal in front of `annotation`: a trailing undefined phase was harmless,
because the annotator finished before reaching it.
"""

import logging
from collections import OrderedDict, defaultdict

import pytest

from potato.phase import UserPhase
from potato.server_utils.config_module import validate_phase_order
from potato.user_state_management import UserStateManager


class TestValidatorFlagsIt:
    def test_undefined_phase_warns(self, caplog):
        with caplog.at_level(logging.WARNING):
            validate_phase_order({"phases": {"order": ["consent", "annotation"]}})
        assert "consent" in caplog.text
        assert "phases.order" in caplog.text

    def test_defined_phase_is_quiet(self, caplog):
        with caplog.at_level(logging.WARNING):
            validate_phase_order({
                "phases": {
                    "order": ["consent", "annotation"],
                    "consent": {"type": "consent", "file_name": "consent.jsonl"},
                }
            })
        assert caplog.text == ""

    def test_annotation_needs_no_block(self, caplog):
        """`annotation` is sequenced through the order but owned by the annotate flow."""
        with caplog.at_level(logging.WARNING):
            validate_phase_order({"phases": {"order": ["annotation"]}})
        assert caplog.text == ""

    def test_a_list_of_phases_is_left_alone(self, caplog):
        with caplog.at_level(logging.WARNING):
            validate_phase_order({"phases": [{"name": "consent", "type": "consent"}]})
        assert caplog.text == ""


class TestSequenceSkipsUnregisteredPhases:
    """The sequence the server walks must only contain phases that have a page."""

    def _manager(self, config):
        manager = UserStateManager.__new__(UserStateManager)
        manager.config = config
        manager.phase_type_to_name_to_page = defaultdict(OrderedDict)
        manager._configured_phase_sequence_cache = None
        manager._configured_phase_index_cache = {}
        manager._phase_page_order_cache = {}
        manager._phase_page_index_cache = {}
        return manager

    def test_undefined_leading_phase_is_not_in_the_sequence(self):
        manager = self._manager({"phases": {"order": ["consent", "annotation"]}})
        assert manager._get_configured_phase_sequence() == [UserPhase.ANNOTATION]

    def test_invalidate_clears_a_sequence_cached_before_the_prune(self):
        config = {"phases": {"order": ["consent", "annotation"]}}
        manager = self._manager(config)
        manager.add_phase(UserPhase.CONSENT, "consent", "consent.html")
        config["phases"]["consent"] = {"type": "consent"}

        assert manager._get_configured_phase_sequence() == [
            UserPhase.CONSENT, UserPhase.ANNOTATION,
        ]

        # The loader drops an undefined name from the order after the sequence
        # may already have been derived, so the caches have to go with it.
        config["phases"]["order"] = ["annotation"]
        manager.invalidate_phase_caches()
        assert manager._get_configured_phase_sequence() == [UserPhase.ANNOTATION]

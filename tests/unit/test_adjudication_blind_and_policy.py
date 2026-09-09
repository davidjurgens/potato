"""Adjudication policy is enforced by the server, not by the browser.

Three settings were applied only in the client. The adjudicator is
simultaneously the party being constrained and the party holding the session,
which is the specific case where "the check is in the browser" stops being a
nitpick.

`show_annotator_names: false` was a display substitution
(`config.show_annotator_names ? userId : 'Annotator'`). Both API endpoints
shipped the addresses anyway, stating each one twice -- as the dict key and
again as `user_id` inside the value -- so the blind came off in the network
tab. Blind adjudication exists so the adjudicator's judgment is not colored by
who produced which answer; a blind that only survives not looking is not one.

`require_notes_on_override` and `require_confidence` were never consulted at
`/adjudicate/api/submit`. An override with empty notes returned
`{"status": "ok"}` and reached both export files unexplained, on exactly the
kind of item a reader will later want the reasoning for. A submission with no
confidence key at all was published as "medium", indistinguishable from a
considered choice, on a field researchers filter on.

The aliases have to be reversible. The UI records geometry decisions as
`{annotator, idx}` references, so whatever the API called an annotator is what
comes back on submit -- blind the payload without unblinding the picks and the
adjudicator's chosen boxes are dropped from the stored decision with only a
log line.
"""

import pytest

from potato.adjudication import (
    annotator_aliases, blind_annotator_signals, blind_item_dict,
    unblind_user_id)


USERS = ["ann1@example.com", "ann2@example.com", "ann3@example.com"]


class TestAliasesHideTheAddress:

    def test_no_alias_contains_a_real_id(self):
        aliases = annotator_aliases("i2", USERS)
        assert set(aliases) == set(USERS)
        for user_id, alias in aliases.items():
            assert user_id not in alias
            assert "@" not in alias

    def test_each_annotator_gets_a_distinct_alias(self):
        aliases = annotator_aliases("i2", USERS)
        assert len(set(aliases.values())) == len(USERS)

    def test_it_is_stable_for_one_item(self):
        """The panes group answers by annotator, and a decision may be
        submitted, reloaded and revised."""
        assert annotator_aliases("i2", USERS) == annotator_aliases("i2", USERS)

    def test_input_order_does_not_change_it(self):
        assert annotator_aliases("i2", USERS) == annotator_aliases(
            "i2", list(reversed(USERS)))

    def test_the_ordering_is_not_alphabetical_on_every_item(self):
        """Sorted addresses put the same person first on every item, which
        leaks the alphabet to anyone who reads two items."""
        firsts = {
            next(u for u, a in annotator_aliases(f"i{n}", USERS).items()
                 if a == "Annotator 1")
            for n in range(12)
        }
        assert len(firsts) > 1


class TestTheItemPayloadCarriesNoAddress:

    def _item(self):
        return {
            "instance_id": "i2",
            "annotations": {u: {"verdict": {"yes": "on"}} for u in USERS},
            "span_annotations": {u: [] for u in USERS},
            "behavioral_data": {u: {"total_time_ms": 1000} for u in USERS},
            "agreement_scores": {"verdict": 0.0},
            "num_annotators": 3,
        }

    def test_every_annotator_keyed_section_is_re_keyed(self):
        aliases = annotator_aliases("i2", USERS)
        blinded = blind_item_dict(self._item(), aliases)
        for key in ("annotations", "span_annotations", "behavioral_data"):
            assert set(blinded[key]) == set(aliases.values()), (
                f"{key} still keyed by annotator id")

    def test_no_address_survives_anywhere_in_the_payload(self):
        blinded = blind_item_dict(self._item(), annotator_aliases("i2", USERS))
        flat = repr(blinded)
        for user_id in USERS:
            assert user_id not in flat

    def test_the_answers_themselves_are_untouched(self):
        """Blinding must hide who, not what."""
        blinded = blind_item_dict(self._item(), annotator_aliases("i2", USERS))
        assert list(blinded["annotations"].values()) == [
            {"verdict": {"yes": "on"}}] * 3

    def test_schema_keyed_sections_are_left_alone(self):
        blinded = blind_item_dict(self._item(), annotator_aliases("i2", USERS))
        assert blinded["agreement_scores"] == {"verdict": 0.0}


class TestSignalsStateTheIdTwice:
    """Re-keying alone left the address in the body."""

    def test_the_inner_user_id_is_replaced_too(self):
        aliases = annotator_aliases("i2", USERS)
        signals = {u: {"user_id": u, "total_annotations": 5} for u in USERS}
        blinded = blind_annotator_signals(signals, aliases)
        assert set(blinded) == set(aliases.values())
        for alias, signal in blinded.items():
            assert signal["user_id"] == alias
        assert not any(u in repr(blinded) for u in USERS)

    def test_the_rest_of_the_signal_survives(self):
        blinded = blind_annotator_signals(
            {USERS[0]: {"user_id": USERS[0], "total_annotations": 5}},
            annotator_aliases("i2", USERS))
        assert list(blinded.values())[0]["total_annotations"] == 5


class TestTheAliasIsReversible:
    """Geometry picks come back carrying whatever the API called the
    annotator."""

    def test_an_alias_maps_back_to_the_address(self):
        aliases = annotator_aliases("i2", USERS)
        for user_id, alias in aliases.items():
            assert unblind_user_id(alias, aliases) == user_id

    def test_a_round_trip_survives(self):
        aliases = annotator_aliases("i2", USERS)
        assert unblind_user_id(aliases[USERS[1]], aliases) == USERS[1]

    def test_an_unknown_value_passes_through(self):
        """Names are unblinded only when blinding is on; a real id submitted
        under `show_annotator_names: true` must not be mangled."""
        assert unblind_user_id(USERS[0], annotator_aliases("i2", USERS)) == \
            USERS[0]

    def test_a_non_string_is_untouched(self):
        assert unblind_user_id(None, {}) is None
        assert unblind_user_id(3, {}) == 3


class TestSubmitPolicy:
    """`_adjudication_policy_error` is what the handler consults."""

    class Config:
        def __init__(self, notes_on_override=False, confidence=False):
            self.require_notes_on_override = notes_on_override
            self.require_confidence = confidence

    class Manager:
        def __init__(self, config):
            self.adj_config = config

    def _error(self, config, data):
        from potato.routes import _adjudication_policy_error

        return _adjudication_policy_error(self.Manager(config), data)

    def test_an_unexplained_override_is_refused(self):
        error = self._error(
            self.Config(notes_on_override=True),
            {"source": "override", "notes": "", "confidence": "high"})
        assert error and "override" in error.lower(), (
            'an override with empty notes returned {"status": "ok"} and '
            "reached both export files")

    def test_whitespace_is_not_a_note(self):
        assert self._error(self.Config(notes_on_override=True),
                           {"source": "override", "notes": "   "})

    def test_an_explained_override_is_allowed(self):
        assert self._error(
            self.Config(notes_on_override=True),
            {"source": "override", "notes": "annotators missed the negation",
             "confidence": "high"}) is None

    def test_a_non_override_needs_no_note(self):
        assert self._error(self.Config(notes_on_override=True),
                           {"source": "consensus", "notes": ""}) is None

    def test_the_dict_form_of_source_is_read(self):
        """`source` is per-schema in the payload the UI sends."""
        assert self._error(self.Config(notes_on_override=True),
                           {"source": {"verdict": "override"}, "notes": ""})

    def test_the_flag_off_allows_it(self):
        assert self._error(self.Config(notes_on_override=False),
                           {"source": "override", "notes": ""}) is None

    def test_a_missing_confidence_is_refused_when_required(self):
        error = self._error(self.Config(confidence=True), {"source": "consensus"})
        assert error and "confidence" in error.lower(), (
            "a submission with no confidence key was published as 'medium'")

    def test_an_empty_confidence_is_refused_when_required(self):
        assert self._error(self.Config(confidence=True), {"confidence": ""})

    def test_a_supplied_confidence_is_allowed(self):
        assert self._error(self.Config(confidence=True),
                           {"confidence": "low"}) is None

    def test_confidence_not_required_means_absent_is_fine(self):
        assert self._error(self.Config(confidence=False), {}) is None


class TestTheUiDoesNotInventAConfidence:
    """The select had `<option value="medium" selected>`, so an adjudicator who
    never looked at the control published a value they never chose."""

    def test_no_option_is_preselected(self):
        from pathlib import Path

        markup = Path("potato/templates/adjudication.html").read_text()
        block = markup.split('id="adj-confidence"', 1)[1].split("</select>")[0]
        selected = [line for line in block.splitlines() if "selected" in line]
        assert len(selected) == 1, "exactly one option may carry `selected`"
        assert 'value=""' in selected[0], (
            "a real confidence value is preselected, so an untouched control "
            "still submits one")

    def test_the_client_sends_no_fallback_value(self):
        """Driven by the value the expression produces, not by reading it: an
        absent element must yield the empty string, not 'medium'."""
        from pathlib import Path

        source = Path("potato/static/adjudication.js").read_text()
        line = [l for l in source.splitlines()
                if "confidence:" in l and "getElementById" in l]
        assert line, "the submit payload no longer builds confidence"
        assert "'medium'" not in line[0], (
            "the client substitutes a confidence the adjudicator never chose")

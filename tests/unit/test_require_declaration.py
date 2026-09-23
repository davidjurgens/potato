"""``machine_annotators.require_declaration``: who may write annotations.

The setting refuses dataset writes from a participant who is neither a declared
machine rater nor a listed person. Two things about it are easy to get wrong
and are pinned here.

**It is not enforced from a request header.** A header asserting "I am a
machine" is supplied by the caller, so honouring one would let anybody opt out
of being counted as a human annotator, which inverts the guarantee the setting
exists to provide. Origin is declared by the study or not at all.

**It refuses to run where it could not refuse anything.** Under open
registration every username that registers becomes a valid account, so there is
no list of people to compare a participant against. A guard in that position
reads as protection and provides none, so the config is rejected at load rather
than silently passing every write.
"""

from __future__ import annotations

import pytest

from potato.annotator_origin import parse_machine_annotators, undeclared_participant
from potato.server_utils.config_module import (
    ConfigValidationError,
    validate_machine_annotators_config,
)


ROSTER = parse_machine_annotators({
    "machine_annotators": {
        "enabled": True,
        "annotators": [{"id": "prokka", "kind": "tool"}],
    }
})


class TestWhoIsAccountedFor:
    def test_a_declared_machine_is_accounted_for(self):
        assert not undeclared_participant("prokka", ROSTER, ["alice"])

    def test_a_listed_person_is_accounted_for(self):
        assert not undeclared_participant("alice", ROSTER, ["alice"])

    def test_a_stranger_is_not(self):
        assert undeclared_participant("mallory", ROSTER, ["alice"])

    def test_usernames_are_compared_as_strings(self):
        assert not undeclared_participant(42, {}, [42])

    def test_an_empty_username_is_not_refused(self):
        # Nothing to check, and refusing here would turn a missing session into
        # a confusing roster error.
        assert not undeclared_participant("", ROSTER, ["alice"])

    def test_the_roster_alone_is_enough(self):
        assert not undeclared_participant("prokka", ROSTER, [])

    def test_the_people_list_alone_is_enough(self):
        assert not undeclared_participant("alice", {}, ["alice"])


class TestTheGuardRefusesToBeVacuous:
    def _validate(self, block, **rest):
        cfg = {"machine_annotators": block}
        cfg.update(rest)
        validate_machine_annotators_config(cfg)

    BLOCK = {
        "enabled": True,
        "require_declaration": True,
        "annotators": [{"id": "prokka", "kind": "tool"}],
    }

    def test_open_registration_is_refused(self):
        with pytest.raises(ConfigValidationError) as exc:
            self._validate(self.BLOCK, user_config={"allow_all_users": True,
                                                    "users": ["alice"]})
        assert "refuse nothing" in str(exc.value)

    def test_a_closed_study_with_no_roster_is_refused(self):
        with pytest.raises(ConfigValidationError):
            self._validate(self.BLOCK, user_config={"allow_all_users": False})

    def test_a_closed_study_with_an_inline_roster_passes(self):
        self._validate(self.BLOCK,
                       user_config={"allow_all_users": False,
                                    "users": ["alice", "bob"]})

    def test_users_given_as_objects_count_as_a_roster(self):
        # _parse_authorized_users accepts both shapes seen in the wild.
        self._validate(self.BLOCK,
                       user_config={"allow_all_users": False,
                                    "users": [{"username": "alice",
                                               "password": "x"}]})

    def test_a_roster_file_counts_even_though_it_is_not_read(self):
        """A validator has no business doing I/O, so this asks whether a roster
        is configured, not how many people it holds."""
        self._validate(self.BLOCK,
                       user_config={"allow_all_users": False},
                       authentication={"user_config_path": "users.jsonl"})

    def test_the_setting_off_needs_no_roster(self):
        self._validate({"enabled": True,
                        "annotators": [{"id": "prokka", "kind": "tool"}]})

    def test_the_block_disabled_is_not_validated(self):
        self._validate({"enabled": False, "require_declaration": True})

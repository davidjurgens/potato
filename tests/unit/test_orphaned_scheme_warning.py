"""Boot must say something when saved annotations name a scheme the config dropped.

Editing `annotation_schemes` after annotators have worked is silent in every
direction Potato reports on: an already-annotated item stays annotated whatever
it was annotated with, so the overview reads 100% complete while agreement
reports zero items for every configured scheme and the CSV export carries
columns named after schemes the config no longer has. The boot log is the one
place the operator is already looking, so the mismatch goes there.
"""

import logging

import pytest

from potato.flask_server import _warn_on_orphaned_schemes
from potato.item_state_management import Label


class _FakeUserState:
    def __init__(self, labels_by_instance):
        self.instance_id_to_label_to_value = labels_by_instance


class _FakeUserStateManager:
    def __init__(self, states):
        self._states = states

    def get_user_ids(self):
        return list(self._states)

    def get_user_state(self, user_id):
        return self._states.get(user_id)


def _usm(*schema_names, user="alice"):
    labels = {f"i{n}": {Label(schema, "yes"): "yes"}
              for n, schema in enumerate(schema_names)}
    return _FakeUserStateManager({user: _FakeUserState(labels)})


def _config(*scheme_names):
    return {"annotation_schemes": [{"name": n, "annotation_type": "radio"}
                                   for n in scheme_names]}


def _warnings(caplog):
    return [r.getMessage() for r in caplog.records
            if r.levelno >= logging.WARNING]


class TestOrphanedSchemeWarning:
    def test_renamed_scheme_is_named_with_its_count(self, caplog):
        with caplog.at_level(logging.WARNING, logger="potato.flask_server"):
            _warn_on_orphaned_schemes(_config("polarity"), _usm("sentiment"))
        messages = _warnings(caplog)
        assert len(messages) == 1
        assert "sentiment (1 answer(s))" in messages[0]
        assert "polarity" not in messages[0]

    def test_silent_when_stored_schemes_all_still_exist(self, caplog):
        with caplog.at_level(logging.WARNING, logger="potato.flask_server"):
            _warn_on_orphaned_schemes(_config("sentiment", "confidence"),
                                      _usm("sentiment"))
        assert _warnings(caplog) == []

    def test_adding_a_scheme_alone_is_not_a_mismatch(self, caplog):
        """A new question is a real problem -- nobody who finished will see it --
        but it is not one this check can distinguish from a task still filling
        up, so it must not fire."""
        with caplog.at_level(logging.WARNING, logger="potato.flask_server"):
            _warn_on_orphaned_schemes(_config("sentiment", "confidence"),
                                      _usm("sentiment"))
        assert _warnings(caplog) == []

    def test_counts_every_annotator_holding_the_orphan(self, caplog):
        states = {
            "alice": _FakeUserState({"i1": {Label("sentiment", "yes"): "yes"}}),
            "bob": _FakeUserState({"i1": {Label("sentiment", "no"): "no"},
                                   "i2": {Label("sentiment", "no"): "no"}}),
        }
        with caplog.at_level(logging.WARNING, logger="potato.flask_server"):
            _warn_on_orphaned_schemes(_config("polarity"),
                                      _FakeUserStateManager(states))
        assert "sentiment (3 answer(s))" in _warnings(caplog)[0]

    def test_several_orphans_are_reported_together(self, caplog):
        with caplog.at_level(logging.WARNING, logger="potato.flask_server"):
            _warn_on_orphaned_schemes(_config("polarity"),
                                      _usm("sentiment", "confidence"))
        message = _warnings(caplog)[0]
        assert "2 scheme(s)" in message
        assert "confidence" in message and "sentiment" in message

    @pytest.mark.parametrize("config", [{}, {"annotation_schemes": []},
                                        {"annotation_schemes": None}])
    def test_no_configured_schemes_means_no_opinion(self, caplog, config):
        """A phase-only config replaces the top-level scheme list, so an empty
        one is not evidence that anything was dropped."""
        with caplog.at_level(logging.WARNING, logger="potato.flask_server"):
            _warn_on_orphaned_schemes(config, _usm("sentiment"))
        assert _warnings(caplog) == []

    def test_no_annotations_yet(self, caplog):
        with caplog.at_level(logging.WARNING, logger="potato.flask_server"):
            _warn_on_orphaned_schemes(_config("polarity"),
                                      _FakeUserStateManager({}))
        assert _warnings(caplog) == []

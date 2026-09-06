"""
Don't tell an operator to enable a feature they are already running.

The assignment relaxation logs when it hands out items another annotator
holds but has not submitted, and the line ended "Enable instance_reclaim
to hand those back automatically instead." It printed that
unconditionally, including on a study with instance_reclaim enabled and
visibly working -- the operator is reading a log line about reclaim
while being told to turn reclaim on.
"""

from unittest.mock import MagicMock

import pytest

from potato.item_state_management import ItemStateManager


class _Manager:
    """The two attributes the log line reads, with the relaxation's
    surrounding machinery stubbed. Calling the real method keeps the
    test on the code that ships rather than a paraphrase of it."""

    def __init__(self, reclaim_enabled, assigned):
        self.reclaim_enabled = reclaim_enabled
        self.logger = MagicMock()
        self._holds_are_binding = True
        self._passes = [0, assigned]

    def _assign_pass(self, user_state):
        return self._passes.pop(0)


def _run(reclaim_enabled):
    mgr = _Manager(reclaim_enabled, assigned=2)
    user = MagicMock()
    user.user_id = "alice"
    ItemStateManager._assign_instances_to_user_inner(mgr, user)
    assert mgr.logger.info.called, "the relaxation did not log"
    call = mgr.logger.info.call_args
    return (call.args[0] % call.args[1:]) if len(call.args) > 1 else call.args[0]


def test_the_advice_is_dropped_when_reclaim_is_already_on():
    message = _run(reclaim_enabled=True)
    assert "Enable instance_reclaim" not in message, message
    assert "holds but has not submitted" in message


def test_the_advice_is_given_when_reclaim_is_off():
    message = _run(reclaim_enabled=False)
    assert "Enable instance_reclaim" in message, message

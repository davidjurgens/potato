"""
One definition of "is this a crowd deployment", read by everything that gates
on it.

`_crowd_backend` used to test only the legacy spellings -- a top-level
`prolific:`/`mturk:` block, or `login.type` -- and never
`crowdsourcing.provider`, which is the documented way to name a platform.
`validate_search_assignment_compat` carried a second inline copy of the same
legacy-only test, so the miss existed twice, one function away from itself.

Both gates are safety controls: the codebook force-lock stops paid annotators
reshaping a shared codebook, and the annotator_claim refusal stops
self-selection breaking payment and coverage on a HIT. A control that a
config-key spelling switches off is not a control.

The end-to-end proof that the codebook lock actually refuses a write lives in
tests/server/test_audit31_codebook_crowd_lock.py -- the resolver returning
"fixed" is the shadow, the 403 is the thing.
"""

import pytest

from potato.server_utils import config_module
from potato.server_utils.config_module import ConfigValidationError

LEGACY = [
    {"prolific": {"completion_code": "ABC123"}},
    {"mturk": {"aws_access_key_id": "x"}},
    {"login": {"type": "prolific"}},
    {"login": {"type": "mturk"}},
]

RECRUITED = [{"crowdsourcing": {"provider": name}} for name in (
    "prolific", "mturk", "connect", "sona", "microworkers",
    "clickworker", "generic", "url_direct")]

NOT_CROWD = [
    {},
    {"crowdsourcing": {"enabled": True}},          # block, but no provider
    {"crowdsourcing": {"provider": "expert"}},     # hired by name
    {"login": {"type": "standard"}},
]


@pytest.mark.parametrize("config", LEGACY + RECRUITED)
def test_a_crowd_deployment_is_recognized(config):
    assert config_module._crowd_backend(config) is True


@pytest.mark.parametrize("config", NOT_CROWD)
def test_a_non_crowd_deployment_is_not(config):
    assert config_module._crowd_backend(config) is False


def test_an_unknown_provider_counts_as_crowd():
    """Fails closed. A typo, or a provider added after this version, must
    not silently unlock a control -- it arrives locked and gets trusted
    deliberately."""
    assert config_module._crowd_backend(
        {"crowdsourcing": {"provider": "prolfic"}}) is True
    assert config_module._crowd_backend(
        {"crowdsourcing": {"provider": "some_future_platform"}}) is True


@pytest.mark.parametrize("spelling", [
    {"prolific": {"completion_code": "A"}},
    {"crowdsourcing": {"provider": "prolific"}},
])
def test_the_codebook_locks_under_either_spelling(spelling):
    config = {"codebook_mode": "open"}
    config.update(spelling)
    assert config_module.get_codebook_mode(config) == "fixed"


def test_an_expert_study_keeps_the_mode_it_asked_for():
    assert config_module.get_codebook_mode({
        "codebook_mode": "open",
        "crowdsourcing": {"provider": "expert"}}) == "open"


@pytest.mark.parametrize("spelling", [
    {"prolific": {"completion_code": "A"}},
    {"crowdsourcing": {"provider": "prolific"}},
])
def test_annotator_claim_is_refused_under_either_spelling(spelling):
    """The second gate, which had its own copy of the legacy-only test."""
    config = {"search": {"enabled": True, "annotator_claim": True},
              "assignment_strategy": "fixed_order"}
    config.update(spelling)
    with pytest.raises(ConfigValidationError) as excinfo:
        config_module.validate_search_assignment_compat(config)
    assert "crowdsourcing backend" in str(excinfo.value)


def test_annotator_claim_is_allowed_without_a_crowd_backend():
    config_module.validate_search_assignment_compat({
        "search": {"enabled": True, "annotator_claim": True},
        "assignment_strategy": "fixed_order"})

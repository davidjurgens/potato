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


class TestUrlDirectExposure:
    """`login.type: url_direct` with no provider is deliberately NOT
    force-locked: a public self-registration study is a legitimate design
    and locking it would change behaviour for someone paying nobody.

    But the crowd registry hands that config a LegacyUrlDirectProvider --
    Potato's own answer to "is this a crowd deployment" is yes -- and
    url_direct means anyone with the link self-registers. An open
    codebook there is reachable by a passer-by, which is a bigger opening
    than the Prolific case it sits next to. So it warns.
    """

    def _warnings(self, caplog):
        return [r.message for r in caplog.records
                if r.levelname == "WARNING"]

    def test_url_direct_with_an_open_codebook_warns(self, caplog):
        with caplog.at_level("WARNING"):
            config_module.validate_codebook_config({
                "codebook_mode": "open", "login": {"type": "url_direct"}})
        assert any("self-register" in m for m in self._warnings(caplog)), \
            self._warnings(caplog)

    def test_it_is_not_force_locked(self):
        """The warning must not have quietly become a lock -- that is the
        behaviour change this deliberately does not make."""
        assert config_module.get_codebook_mode({
            "codebook_mode": "open",
            "login": {"type": "url_direct"}}) == "open"

    def test_a_named_platform_gets_the_force_lock_message_instead(
            self, caplog):
        """One warning, not two: naming the provider force-locks, and the
        self-registration advice would then be telling the author to do
        what the server already did."""
        with caplog.at_level("WARNING"):
            config_module.validate_codebook_config({
                "codebook_mode": "open",
                "login": {"type": "url_direct"},
                "crowdsourcing": {"provider": "prolific"}})
        messages = self._warnings(caplog)
        assert any("force-locking" in m for m in messages), messages
        assert not any("self-register" in m for m in messages), messages

    def test_an_expert_invite_study_is_silent(self, caplog):
        """Experts reach a url_direct study through pre-authorized invite
        tokens, so 'anyone with the link' is not true of them."""
        with caplog.at_level("WARNING"):
            config_module.validate_codebook_config({
                "codebook_mode": "open",
                "login": {"type": "url_direct"},
                "crowdsourcing": {"provider": "expert"}})
        assert self._warnings(caplog) == []

    def test_a_fixed_codebook_is_silent(self, caplog):
        with caplog.at_level("WARNING"):
            config_module.validate_codebook_config({
                "codebook_mode": "fixed", "login": {"type": "url_direct"}})
        assert self._warnings(caplog) == []

    def test_a_standard_login_is_silent(self, caplog):
        with caplog.at_level("WARNING"):
            config_module.validate_codebook_config({
                "codebook_mode": "open", "login": {"type": "standard"}})
        assert self._warnings(caplog) == []

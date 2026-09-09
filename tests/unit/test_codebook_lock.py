"""The codebook force-lock does not fail open on a typo, and says when it fires.

The lock itself is enforced properly: every mutating codebook route calls
`_can_mutate`, which refuses `fixed` even for privileged users. These are the
two ways of reaching the wrong MODE.

FAILING OPEN ON A MISSING VALUE. `_crowd_backend` tested the provider for
truthiness, so `crowdsourcing:\\n  provider:` (which YAML reads as `None`) and
`provider: ""` both skipped the branch and resolved to `open` -- and a plain
annotator could then create a code in the shared codebook. Both spellings mean
"I was naming a crowd platform and the value is missing": a half-finished edit,
or a template whose substitution did not happen. The comment on
`_TRUSTED_CROWD_PROVIDERS` says an unrecognized provider name locks
deliberately, because "a security control that a typo can switch off is not a
control" -- and an absent value is the same kind of mistake.

SILENT WHEN THE MODE WAS NEVER WRITTEN. `validate_codebook_config` returned
early when neither `codebook_mode` nor `codebook.mode` was set, so the
force-lock warning fired only for an author who wrote the mode explicitly.
That is backwards. Someone who wrote `codebook_mode: open` and was overruled at
least knows the key exists; someone who never wrote it has nothing in their
config to connect the behaviour to -- and QDA is the workflow where an open
codebook is the documented default, so it is where the surprise is largest.
"""

import logging

import pytest

from potato.server_utils.config_module import (
    ConfigValidationError, get_codebook_mode, validate_codebook_config)


def qda(**crowdsourcing):
    config = {"qda_mode": {"enabled": True}}
    if crowdsourcing:
        config["crowdsourcing"] = crowdsourcing
    return config


class TestAMissingProviderValueLocks:

    @pytest.mark.parametrize("value", [None, "", "   ", "\t"])
    def test_an_absent_value_is_treated_as_a_crowd_backend(self, value):
        assert get_codebook_mode(qda(provider=value)) == "fixed", (
            "`provider:` with nothing after it resolved to an open codebook, "
            "so a plain annotator could create codes in the shared one")

    def test_an_unrecognized_name_still_locks(self):
        """Deliberate, and the reason the missing case must match it."""
        assert get_codebook_mode(qda(provider="prolfic")) == "fixed"

    def test_a_named_platform_locks(self):
        assert get_codebook_mode(qda(provider="prolific")) == "fixed"

    def test_expert_is_still_trusted(self):
        assert get_codebook_mode(qda(provider="expert")) == "open"

    @pytest.mark.parametrize("value", ["Expert", "  expert  ", "EXPERT"])
    def test_trust_survives_capitalisation_and_padding(self, value):
        assert get_codebook_mode(qda(provider=value)) == "open"

    def test_no_crowdsourcing_block_is_not_a_crowd_backend(self):
        """Absence of the block is different from a present-but-empty value:
        nobody was part-way through naming a platform."""
        assert get_codebook_mode(qda()) == "open"

    def test_an_empty_crowdsourcing_block_is_not_one_either(self):
        config = {"qda_mode": {"enabled": True}, "crowdsourcing": {}}
        assert get_codebook_mode(config) == "open"


class TestTheLockAnnouncesItself:

    def _warnings(self, config, caplog):
        with caplog.at_level(logging.WARNING):
            validate_codebook_config(config)
        return " ".join(r.getMessage() for r in caplog.records)

    def test_it_warns_when_the_mode_was_never_written(self, caplog):
        message = self._warnings(qda(provider="prolific"), caplog)
        assert "force-locking" in message, (
            "the author who never wrote the key has nothing in their config "
            "to connect the behaviour to")

    def test_it_says_the_mode_was_a_default(self, caplog):
        message = self._warnings(qda(provider="prolific"), caplog)
        assert "default" in message

    def test_it_still_warns_when_the_mode_was_written(self, caplog):
        config = qda(provider="prolific")
        config["codebook_mode"] = "open"
        message = self._warnings(config, caplog)
        assert "force-locking" in message and "requested" in message

    def test_a_missing_provider_value_warns_too(self, caplog):
        message = self._warnings(qda(provider=None), caplog)
        assert "force-locking" in message

    def test_no_crowd_backend_says_nothing(self, caplog):
        assert "force-locking" not in self._warnings(qda(), caplog)

    def test_an_already_fixed_mode_says_nothing(self, caplog):
        """Nothing was overruled, so there is nothing to report."""
        config = qda(provider="prolific")
        config["codebook_mode"] = "fixed"
        assert "force-locking" not in self._warnings(config, caplog)

    def test_a_non_qda_study_with_no_mode_says_nothing(self, caplog):
        """It resolves to `fixed` on its own; the lock changed nothing."""
        config = {"crowdsourcing": {"provider": "prolific"}}
        assert "force-locking" not in self._warnings(config, caplog)


class TestAnInvalidModeIsStillRefused:

    def test_an_unknown_mode_raises(self):
        config = {"codebook_mode": "sometimes"}
        with pytest.raises(ConfigValidationError, match="codebook_mode"):
            validate_codebook_config(config)

    def test_a_valid_mode_does_not(self):
        validate_codebook_config({"codebook_mode": "open"})

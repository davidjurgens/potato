"""Tests for the settings that decide whether a public host is safe.

Each of these guards a defect found while scoping one-command deployment. They
are grouped here rather than scattered because they share a theme: a setting the
operator believed was in effect that silently was not.
"""

import os
import sys
import tempfile

import pytest

import potato.server_utils.config_module as cm
from potato.server_utils.config_module import (
    ConfigValidationError,
    _substitute_llm_block_env_vars,
    init_config,
    validate_authentication_config,
)
from potato.server_utils.arg_utils import arguments
from potato.server_utils.session_config import configure_session, resolve_secret_key
from tests.helpers.test_utils import create_test_directory


EXAMPLE_CONFIG = "examples/classification/single-choice/config.yaml"


class _FakeApp:
    """Minimal stand-in — configure_session only sets two attributes."""


# =====================================================================
# 0.3 — Flask signing key
# =====================================================================


class TestSecretKeyResolution:
    def test_config_key_honored_without_persist_sessions(self, monkeypatch):
        """A configured key must be used even when persist_sessions is off.

        It was previously read only inside the persist_sessions branch, so an
        operator who set it and nothing else got a random per-process key.
        """
        monkeypatch.delenv("POTATO_SECRET_KEY", raising=False)
        app = _FakeApp()
        configure_session(app, {"secret_key": "from-config"})
        assert app.secret_key == "from-config"

    def test_env_key_honored_without_persist_sessions(self, monkeypatch):
        monkeypatch.setenv("POTATO_SECRET_KEY", "from-env")
        app = _FakeApp()
        configure_session(app, {})
        assert app.secret_key == "from-env"

    def test_config_beats_env(self, monkeypatch):
        monkeypatch.setenv("POTATO_SECRET_KEY", "from-env")
        app = _FakeApp()
        configure_session(app, {"secret_key": "from-config"})
        assert app.secret_key == "from-config"

    def test_no_key_yields_distinct_random_keys(self, monkeypatch):
        monkeypatch.delenv("POTATO_SECRET_KEY", raising=False)
        a, b = _FakeApp(), _FakeApp()
        configure_session(a, {})
        configure_session(b, {})
        assert a.secret_key != b.secret_key
        assert len(a.secret_key) == 64

    def test_persist_sessions_without_key_still_raises(self, monkeypatch):
        monkeypatch.delenv("POTATO_SECRET_KEY", raising=False)
        with pytest.raises(ValueError, match="persist_sessions"):
            configure_session(_FakeApp(), {"persist_sessions": True})

    def test_resolve_returns_none_when_unset(self, monkeypatch):
        monkeypatch.delenv("POTATO_SECRET_KEY", raising=False)
        assert resolve_secret_key({}) is None

    def test_session_lifetime_default_is_uniform(self, monkeypatch):
        """flask_server and routes used to disagree (2 days vs 7)."""
        monkeypatch.delenv("POTATO_SECRET_KEY", raising=False)
        app = _FakeApp()
        configure_session(app, {})
        assert app.permanent_session_lifetime.days == 2

    def test_session_lifetime_override(self, monkeypatch):
        monkeypatch.delenv("POTATO_SECRET_KEY", raising=False)
        app = _FakeApp()
        configure_session(app, {"session_lifetime_days": 30})
        assert app.permanent_session_lifetime.days == 30


# =====================================================================
# 0.4 — ${VAR} substitution for secrets
# =====================================================================


class TestSecretEnvSubstitution:
    def test_secret_key_is_substituted(self, monkeypatch):
        """The docs have long shown `secret_key: ${POTATO_SECRET_KEY}`.

        Without substitution that stored the literal string as the Flask signing
        key — a fixed, publicly documented value, i.e. session forgery.
        """
        monkeypatch.setenv("POTATO_SECRET_KEY", "real-secret")
        out = _substitute_llm_block_env_vars({"secret_key": "${POTATO_SECRET_KEY}"})
        assert out["secret_key"] == "real-secret"

    def test_admin_api_key_is_substituted(self, monkeypatch):
        monkeypatch.setenv("POTATO_ADMIN_API_KEY", "real-admin-key")
        out = _substitute_llm_block_env_vars({"admin_api_key": "${POTATO_ADMIN_API_KEY}"})
        assert out["admin_api_key"] == "real-admin-key"

    def test_oauth_client_secret_is_substituted(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_OAUTH_SECRET", "real-oauth-secret")
        cfg = {"authentication": {"providers": {
            "google": {"client_id": "public-id", "client_secret": "${GOOGLE_OAUTH_SECRET}"},
        }}}
        out = _substitute_llm_block_env_vars(cfg)
        google = out["authentication"]["providers"]["google"]
        assert google["client_secret"] == "real-oauth-secret"
        assert google["client_id"] == "public-id"

    def test_unrelated_keys_are_left_alone(self):
        cfg = {"annotation_task_name": "keep ${NOT_A_REAL_VAR} as-is"}
        out = _substitute_llm_block_env_vars(cfg)
        assert out["annotation_task_name"] == "keep ${NOT_A_REAL_VAR} as-is"

    def test_non_string_secret_is_not_touched(self):
        out = _substitute_llm_block_env_vars({"secret_key": None})
        assert out["secret_key"] is None

    def test_missing_authentication_block_is_fine(self):
        assert _substitute_llm_block_env_vars({}) == {}


# =====================================================================
# 0.6 — authentication.type vs .method
# =====================================================================


class TestAuthenticationTypeAlias:
    def test_type_is_promoted_to_method(self, caplog):
        """`type` appeared in our own docs and example config.

        It is not in the key allowlist, so it produced a generic warning and the
        method silently fell back to in_memory — on a public host, the worst
        possible failure mode.
        """
        cfg = {"authentication": {"type": "oauth", "providers": {
            "google": {"client_id": "x", "client_secret": "y"},
        }}}
        with caplog.at_level("WARNING"):
            validate_authentication_config(cfg)
        assert cfg["authentication"]["method"] == "oauth"
        assert "type" not in cfg["authentication"]
        assert any("authentication.method" in r.message for r in caplog.records)

    def test_explicit_method_wins_over_type(self):
        cfg = {"authentication": {"type": "oauth", "method": "in_memory"}}
        validate_authentication_config(cfg)
        assert cfg["authentication"]["method"] == "in_memory"

    def test_invalid_method_still_rejected(self):
        with pytest.raises(ConfigValidationError, match="authentication.method"):
            validate_authentication_config({"authentication": {"method": "telepathy"}})


# =====================================================================
# 0.7 / 0.8 — --ssl-cert / --ssl-key / --host
# =====================================================================


@pytest.fixture
def parsed_args():
    """Build args through the real parser so attribute names can't drift."""
    original_argv = sys.argv
    cwd = os.getcwd()

    def _build(extra):
        sys.argv = ["potato", "start", EXAMPLE_CONFIG] + extra
        return arguments()

    yield _build
    sys.argv = original_argv
    os.chdir(cwd)


def _init(parsed_args, extra):
    cm.config.clear()
    return init_config(parsed_args(extra))


class TestHostFlag:
    def test_host_flag_reaches_config(self, parsed_args):
        _init(parsed_args, ["--host", "127.0.0.1"])
        assert cm.config.get("host") == "127.0.0.1"

    def test_absent_host_leaves_config_unset(self, parsed_args):
        """run_server falls back to 0.0.0.0 when unset."""
        _init(parsed_args, [])
        assert cm.config.get("host") is None


class TestSSLFlags:
    def test_cert_without_key_is_rejected(self, parsed_args):
        """A half-configured pair used to be dropped, serving plaintext."""
        with pytest.raises(ConfigValidationError, match="must be given together"):
            _init(parsed_args, ["--ssl-cert", "/tmp/only-cert.pem"])

    def test_key_without_cert_is_rejected(self, parsed_args):
        with pytest.raises(ConfigValidationError, match="must be given together"):
            _init(parsed_args, ["--ssl-key", "/tmp/only-key.pem"])

    def test_missing_cert_file_is_rejected(self, parsed_args):
        with pytest.raises(ConfigValidationError, match="file not found"):
            _init(parsed_args, ["--ssl-cert", "/tmp/nope.pem",
                                "--ssl-key", "/tmp/nope-key.pem"])

    def test_valid_pair_reaches_config(self, parsed_args):
        cert = tempfile.NamedTemporaryFile(suffix=".pem", delete=False)
        cert.close()
        key = tempfile.NamedTemporaryFile(suffix=".pem", delete=False)
        key.close()
        try:
            _init(parsed_args, ["--ssl-cert", cert.name, "--ssl-key", key.name])
            assert cm.config.get("ssl_cert") == cert.name
            assert cm.config.get("ssl_key") == key.name
        finally:
            os.unlink(cert.name)
            os.unlink(key.name)

    def test_no_ssl_args_leaves_config_clean(self, parsed_args):
        _init(parsed_args, [])
        assert cm.config.get("ssl_cert") is None
        assert cm.config.get("ssl_key") is None


# =====================================================================
# 0.5 — no interactive prompt without a terminal
# =====================================================================


class TestNonInteractiveConfigSelection:
    """A directory holding several configs used to prompt on stdin.

    In a container there is no tty, so `input()` blocked forever producing no
    output — the deployment simply appeared to hang at boot.
    """

    def _make_project(self, name, config_names):
        project = create_test_directory(name)
        configs_dir = os.path.join(project, "configs")
        os.makedirs(configs_dir, exist_ok=True)
        for existing in os.listdir(configs_dir):
            os.unlink(os.path.join(configs_dir, existing))
        for config_name in config_names:
            with open(os.path.join(configs_dir, config_name), "w") as handle:
                handle.write("annotation_task_name: test\n")
        return project

    def test_multiple_configs_raise_instead_of_prompting(self, parsed_args):
        project = self._make_project("multi_config_project", ["a.yaml", "b.yaml"])
        cm.config.clear()
        sys.argv = ["potato", "start", project]
        with pytest.raises(ConfigValidationError) as excinfo:
            init_config(arguments())
        message = str(excinfo.value)
        assert "no terminal is attached" in message
        # The candidates must be listed, or the operator has nothing to act on.
        assert "a.yaml" in message and "b.yaml" in message

    def test_env_override_forces_non_interactive(self, parsed_args, monkeypatch):
        monkeypatch.setenv("POTATO_NONINTERACTIVE", "1")
        project = self._make_project("multi_config_env_project", ["x.yaml", "y.yaml"])
        cm.config.clear()
        sys.argv = ["potato", "start", project]
        with pytest.raises(ConfigValidationError, match="no terminal is attached"):
            init_config(arguments())

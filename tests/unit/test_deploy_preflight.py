"""Tests for deploy preflight, deployment state, and credential resolution.

Preflight is the gate between a config and a public URL. Two properties matter
most and are asserted repeatedly below:

* it must **not** rewrite access control. Deploy ships the config as written;
  quietly opening or closing a task would make the running study differ from the
  repo in a way nobody can see.
* it must **not** put a secret in the bundle. Generated keys travel as
  environment variables.
"""

import json
import os
import stat

import pytest
import yaml

from potato.deploy import credentials as creds
from potato.deploy.preflight import (
    Finding,
    generate_secrets,
    harden_config,
    render_report,
    run_preflight,
)
from potato.deploy.state import (
    DeploymentRecord,
    DeploymentStore,
    SecretStore,
    slugify,
)


def write_config(tmp_path, **overrides):
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "data" / "items.json").write_text('[{"id":"1","text":"hi"}]')
    cfg = {
        "task_dir": ".",
        "annotation_task_name": "test task",
        "data_files": ["data/items.json"],
        "output_annotation_dir": "annotation_output/",
        "item_properties": {"id_key": "id", "text_key": "text"},
        "annotation_schemes": [
            {"annotation_type": "radio", "name": "s", "description": "d",
             "labels": ["a", "b"]}
        ],
    }
    cfg.update(overrides)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg, sort_keys=False))
    return str(path)


def codes(report):
    return {f.code for f in report.findings}


# =====================================================================
# Errors that block a deploy
# =====================================================================


class TestBlockingFindings:
    def test_debug_mode_is_an_error(self, tmp_path):
        report = run_preflight(write_config(tmp_path, debug=True))
        assert "D002" in codes(report)
        assert not report.ok

    def test_inline_api_key_is_an_error(self, tmp_path):
        path = write_config(tmp_path, ai_support={
            "api_key": "sk-abcdefghijklmnopqrstuvwxyz0123456789"})
        report = run_preflight(path)
        assert "D006" in codes(report)
        assert not report.ok

    def test_env_reference_is_not_flagged_as_a_secret(self, tmp_path):
        path = write_config(tmp_path, ai_support={"api_key": "${OPENAI_API_KEY}"})
        report = run_preflight(path)
        assert "D006" not in codes(report)

    def test_missing_data_file_is_an_error(self, tmp_path):
        path = write_config(tmp_path, data_files=["data/absent.json"])
        report = run_preflight(path)
        assert "D004" in codes(report)
        assert not report.ok

    def test_authentication_type_typo_is_an_error(self, tmp_path):
        path = write_config(tmp_path, authentication={"type": "oauth"})
        report = run_preflight(path)
        assert "D010" in codes(report)

    def test_multiple_workers_is_an_error(self, tmp_path):
        """Two workers duplicate assignments and lose annotations."""
        path = write_config(tmp_path, server={"workers": 4})
        report = run_preflight(path)
        assert "D013" in codes(report)
        assert not report.ok

    def test_one_worker_is_fine(self, tmp_path):
        report = run_preflight(write_config(tmp_path, server={"workers": 1}))
        assert "D013" not in codes(report)

    def test_clean_config_passes(self, tmp_path):
        report = run_preflight(write_config(tmp_path))
        assert report.ok, [str(f) for f in report.errors]


# =====================================================================
# Access control is reported, never rewritten
# =====================================================================


class TestAccessControlIsReportedNotChanged:
    def test_open_registration_warns_but_does_not_block(self, tmp_path):
        report = run_preflight(write_config(tmp_path), public=True)
        assert "D003" in codes(report)
        assert report.ok, "open enrolment is the researcher's choice, not an error"

    def test_open_registration_not_flagged_for_private_target(self, tmp_path):
        report = run_preflight(write_config(tmp_path), public=False)
        assert "D003" not in codes(report)

    def test_closed_roster_is_not_flagged(self, tmp_path):
        path = write_config(tmp_path, user_config={
            "allow_all_users": False, "users": ["alice"]})
        report = run_preflight(path, public=True)
        assert "D003" not in codes(report)

    def test_oauth_is_not_flagged(self, tmp_path):
        path = write_config(tmp_path, authentication={
            "method": "oauth", "providers": {"google": {"client_id": "x"}}})
        report = run_preflight(path, public=True)
        assert "D003" not in codes(report)

    def test_passwordless_open_registration_says_so(self, tmp_path):
        path = write_config(tmp_path, require_no_password=True)
        report = run_preflight(path, public=True)
        finding = next(f for f in report.findings if f.code == "D003")
        assert "No password is required" in finding.message

    @pytest.mark.parametrize("key,value", [
        ("user_config", {"allow_all_users": False, "users": ["alice"]}),
        ("require_password", False),
        ("require_no_password", True),
        ("login", {"type": "url_direct"}),
        ("authentication", {"method": "oauth", "providers": {"google": {}}}),
    ])
    def test_harden_config_never_touches_access_control(self, key, value):
        original = {"task_dir": ".", key: value}
        hardened = harden_config(dict(original), provider="digitalocean")
        assert hardened[key] == value, f"harden_config modified {key}"

    def test_harden_config_does_not_add_access_keys(self):
        hardened = harden_config({"task_dir": "."}, provider="digitalocean")
        for key in ("user_config", "authentication", "login",
                    "require_password", "require_no_password"):
            assert key not in hardened, f"harden_config invented {key}"


# =====================================================================
# harden_config: the mechanical settings it *should* change
# =====================================================================


class TestHardenConfig:
    def test_disables_debug(self):
        assert harden_config({"task_dir": ".", "debug": True})["debug"] is False

    def test_drops_debug_phase(self):
        hardened = harden_config({"task_dir": ".", "debug_phase": "annotation"})
        assert "debug_phase" not in hardened

    def test_enables_persistent_sessions(self):
        assert harden_config({"task_dir": "."})["persist_sessions"] is True

    def test_forces_relative_task_dir(self):
        assert harden_config({"task_dir": "/somewhere/else"})["task_dir"] == "."

    def test_rewrites_absolute_output_dir(self):
        hardened = harden_config({"task_dir": ".",
                                  "output_annotation_dir": "/var/data/out"})
        assert not os.path.isabs(hardened["output_annotation_dir"])

    def test_keeps_relative_output_dir(self):
        hardened = harden_config({"task_dir": ".",
                                  "output_annotation_dir": "custom_out/"})
        assert hardened["output_annotation_dir"] == "custom_out/"

    def test_pins_workers_to_one(self):
        hardened = harden_config({"task_dir": ".", "server": {"workers": 8}})
        assert hardened["server"]["workers"] == 1

    def test_preserves_other_server_settings(self):
        hardened = harden_config({"task_dir": ".",
                                  "server": {"workers": 4, "host": "0.0.0.0"}})
        assert hardened["server"]["host"] == "0.0.0.0"

    def test_does_not_mutate_the_input(self):
        original = {"task_dir": ".", "debug": True, "server": {"workers": 4}}
        harden_config(original)
        assert original["debug"] is True
        assert original["server"]["workers"] == 4


# =====================================================================
# Secrets
# =====================================================================


class TestGeneratedSecrets:
    def test_secrets_are_distinct_and_long(self):
        gen = generate_secrets()
        assert gen.secret_key != gen.admin_api_key
        assert len(gen.secret_key) == 64
        assert len(gen.admin_api_key) >= 32

    def test_secrets_differ_between_runs(self):
        assert generate_secrets().secret_key != generate_secrets().secret_key

    def test_generated_secrets_never_enter_the_config(self, tmp_path):
        """They travel as env vars; a bundled secret is a published secret."""
        report = run_preflight(write_config(tmp_path))
        serialized = yaml.safe_dump(report.hardened_config)
        assert report.generated.secret_key not in serialized
        assert report.generated.admin_api_key not in serialized


# =====================================================================
# Exposure summary and rendering
# =====================================================================


class TestExposureSummary:
    def test_states_open_signin(self, tmp_path):
        report = run_preflight(write_config(tmp_path), public=True)
        assert any("Sign-in: open" in line for line in report.exposure)

    def test_states_restricted_signin_with_count(self, tmp_path):
        path = write_config(tmp_path, user_config={
            "allow_all_users": False, "users": ["alice", "bob"]})
        report = run_preflight(path, public=True)
        assert any("restricted to 2 named user" in line for line in report.exposure)

    def test_mentions_ai_data_egress(self, tmp_path):
        path = write_config(tmp_path, ai_support={"endpoint": "openai"})
        report = run_preflight(path)
        assert any("LLM provider" in line for line in report.exposure)

    def test_render_marks_blocked_configs(self, tmp_path):
        rendered = render_report(run_preflight(write_config(tmp_path, debug=True)))
        assert "BLOCKED" in rendered

    def test_render_marks_passing_configs(self, tmp_path):
        rendered = render_report(run_preflight(write_config(tmp_path)))
        assert "PASS" in rendered

    def test_report_serializes_to_json(self, tmp_path):
        report = run_preflight(write_config(tmp_path))
        json.dumps(report.to_dict())  # must not raise


class TestEphemeralFilesystem:
    def test_warns_without_backup(self, tmp_path):
        report = run_preflight(write_config(tmp_path), provider="huggingface",
                               ephemeral_fs=True)
        assert "D011" in codes(report)

    def test_quiet_with_backup_configured(self, tmp_path):
        path = write_config(tmp_path, huggingface_backup={
            "enabled": True, "repo_id": "me/notes"})
        report = run_preflight(path, provider="huggingface", ephemeral_fs=True)
        assert "D011" not in codes(report)

    def test_quiet_on_durable_filesystem(self, tmp_path):
        report = run_preflight(write_config(tmp_path), provider="digitalocean",
                               ephemeral_fs=False)
        assert "D011" not in codes(report)


# =====================================================================
# Deployment state
# =====================================================================


class TestDeploymentStore:
    def test_roundtrip(self, tmp_path):
        store = DeploymentStore(str(tmp_path / "config.yaml"))
        record = DeploymentRecord(name="study", provider="digitalocean",
                                  provider_ref={"droplet_id": 123},
                                  url="https://example.test")
        store.upsert(record)
        loaded = store.get("study")
        assert loaded.provider_ref["droplet_id"] == 123
        assert loaded.url == "https://example.test"

    def test_upsert_updates_rather_than_duplicates(self, tmp_path):
        store = DeploymentStore(str(tmp_path / "config.yaml"))
        store.upsert(DeploymentRecord(name="study", provider="do", status="pending"))
        store.upsert(DeploymentRecord(name="study", provider="do", status="running"))
        assert len(store.list()) == 1
        assert store.get("study").status == "running"

    def test_created_at_survives_update(self, tmp_path):
        store = DeploymentStore(str(tmp_path / "config.yaml"))
        first = store.upsert(DeploymentRecord(name="s", provider="do"))
        second = store.upsert(DeploymentRecord(name="s", provider="do"))
        assert second.created_at == first.created_at

    def test_missing_record_is_none(self, tmp_path):
        assert DeploymentStore(str(tmp_path / "config.yaml")).get("nope") is None

    def test_remove(self, tmp_path):
        store = DeploymentStore(str(tmp_path / "config.yaml"))
        store.upsert(DeploymentRecord(name="s", provider="do"))
        assert store.remove("s") is True
        assert store.remove("s") is False

    def test_corrupt_state_file_does_not_block(self, tmp_path):
        """Providers can find resources by tag; a bad file must not be fatal."""
        store = DeploymentStore(str(tmp_path / "config.yaml"))
        os.makedirs(store.state_dir, exist_ok=True)
        with open(store.path, "w") as handle:
            handle.write("{not json at all")

        assert store.list() == []
        store.upsert(DeploymentRecord(name="s", provider="do"))
        assert store.get("s") is not None
        assert os.path.exists(store.path + ".corrupt")

    def test_write_is_atomic_leaving_no_temp_files(self, tmp_path):
        store = DeploymentStore(str(tmp_path / "config.yaml"))
        store.upsert(DeploymentRecord(name="s", provider="do"))
        leftovers = [f for f in os.listdir(store.state_dir) if f.endswith(".tmp")]
        assert not leftovers

    def test_multiple_named_deployments_coexist(self, tmp_path):
        store = DeploymentStore(str(tmp_path / "config.yaml"))
        store.upsert(DeploymentRecord(name="pilot", provider="do"))
        store.upsert(DeploymentRecord(name="main", provider="render"))
        assert {r.name for r in store.list()} == {"pilot", "main"}


class TestSecretStore:
    def test_roundtrip_and_permissions(self, tmp_path):
        store = SecretStore(str(tmp_path / "config.yaml"))
        store.put("study", "admin_api_key", "s3cret")
        assert store.get("study", "admin_api_key") == "s3cret"
        mode = stat.S_IMODE(os.stat(store.path).st_mode)
        assert mode == 0o600, f"secret store is mode {oct(mode)}, must be 0600"

    def test_missing_key_is_none(self, tmp_path):
        assert SecretStore(str(tmp_path / "config.yaml")).get("a", "b") is None

    def test_forget_removes_a_deployment(self, tmp_path):
        store = SecretStore(str(tmp_path / "config.yaml"))
        store.put("study", "k", "v")
        store.forget("study")
        assert store.get("study", "k") is None


class TestSlugify:
    @pytest.mark.parametrize("raw,expected", [
        ("Sentiment Analysis", "sentiment-analysis"),
        ("  Spaces  Everywhere ", "spaces-everywhere"),
        ("Ünïcödé Tásk", "n-c-d-t-sk"),
        ("already-fine", "already-fine"),
        ("Multiple---Dashes", "multiple-dashes"),
    ])
    def test_slugify(self, raw, expected):
        assert slugify(raw) == expected

    def test_empty_falls_back(self):
        assert slugify("") == "potato-task"
        assert slugify("!!!") == "potato-task"

    def test_length_is_bounded(self):
        assert len(slugify("x" * 200)) <= 48


# =====================================================================
# Credentials
# =====================================================================


class TestCredentialResolution:
    def test_explicit_token_wins(self):
        token, source = creds.resolve_token(
            "digitalocean", explicit="explicit",
            environ={"DIGITALOCEAN_TOKEN": "from-env"})
        assert token == "explicit"
        assert source.description == "--token"

    def test_generic_env_var_beats_provider_specific(self):
        token, source = creds.resolve_token("digitalocean", environ={
            "POTATO_DEPLOY_TOKEN_DIGITALOCEAN": "generic",
            "DIGITALOCEAN_TOKEN": "specific"})
        assert token == "generic"

    def test_provider_specific_env_var(self):
        token, source = creds.resolve_token(
            "digitalocean", environ={"DIGITALOCEAN_TOKEN": "specific"})
        assert token == "specific"
        assert "DIGITALOCEAN_TOKEN" in source.description

    def test_alternate_env_var_names(self):
        token, _ = creds.resolve_token("fly", environ={"FLY_ACCESS_TOKEN": "t"})
        assert token == "t"

    def test_absent_token_returns_none_rather_than_raising(self):
        """plan and check must work with no credentials at all."""
        token, source = creds.resolve_token("digitalocean", environ={})
        assert token is None and source is None

    def test_require_token_raises_with_instructions(self):
        with pytest.raises(creds.CredentialError) as excinfo:
            creds.require_token("digitalocean", environ={})
        message = str(excinfo.value)
        assert "cloud.digitalocean.com" in message
        assert "DIGITALOCEAN_TOKEN" in message

    def test_unknown_provider_message_lists_known_ones(self):
        message = creds.missing_token_message("nowhere")
        assert "Unknown provider" in message
        assert "digitalocean" in message

    def test_local_provider_needs_no_token(self):
        assert creds.requires_credential("local") is False

    @pytest.mark.parametrize("provider", ["digitalocean", "huggingface", "render", "fly"])
    def test_real_providers_declare_a_console_url(self, provider):
        spec = creds.PROVIDER_CREDENTIALS[provider]
        assert spec.console_url.startswith("https://")
        assert spec.env_vars

    def test_redact_keeps_only_a_tail(self):
        assert creds.redact("supersecrettoken") == "*" * 12 + "oken"
        assert creds.redact(None) == "<unset>"
        assert creds.redact("ab") == "**"

    def test_redact_never_leaks_the_head(self):
        token = "dop_v1_deadbeef"
        assert token[:8] not in creds.redact(token)

    def test_describe_available_covers_every_provider(self):
        lines = creds.describe_available(environ={})
        assert len(lines) == len(creds.PROVIDER_CREDENTIALS)

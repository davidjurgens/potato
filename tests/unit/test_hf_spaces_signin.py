"""
Hugging Face Spaces: sign-in configuration, the deploy flags, and the
annotators' answers written as a dataset beside the backup.

The sign-in flow itself is driven through the routes in
tests/server/test_hf_oauth_flow.py.
"""

import json
import os

import pytest
import yaml

from potato.auth_backends.oauth_backend import OAuthBackend
from potato.deploy.providers.base import DeploySpec, ProviderError
from potato.deploy.providers.huggingface import (
    _inject_backup_config,
    _inject_hf_oauth_config,
    space_files,
)
from potato.server_utils.backup.hf_sink import _place
from potato.server_utils.backup.hub_responses import (
    annotator_filename,
    response_rows,
    write_hub_export,
)
from potato.server_utils.config_module import (
    ConfigValidationError,
    validate_authentication_config,
)
from tests.helpers.test_utils import cleanup_test_directory, create_test_directory

SPACE_ENV = ("OAUTH_CLIENT_ID", "OAUTH_CLIENT_SECRET", "OAUTH_SCOPES",
             "OPENID_PROVIDER_URL")


@pytest.fixture
def no_space(monkeypatch):
    for key in SPACE_ENV + ("SPACE_HOST",):
        monkeypatch.delenv(key, raising=False)


class TestRegistration:
    def test_outside_a_space_the_config_supplies_everything(self, no_space):
        kwargs = OAuthBackend._huggingface_kwargs({"client_id": "id", "client_secret": "s"})
        assert kwargs == {
            "server_metadata_url": "https://huggingface.co/.well-known/openid-configuration",
            "client_kwargs": {"scope": "openid profile"},
        }

    def test_a_space_fills_what_the_config_leaves_out(self, monkeypatch):
        monkeypatch.setenv("OAUTH_CLIENT_ID", "cid")
        monkeypatch.setenv("OAUTH_CLIENT_SECRET", "secret")
        monkeypatch.setenv("OAUTH_SCOPES", "openid profile email")
        monkeypatch.setenv("OPENID_PROVIDER_URL", "https://huggingface.co/")
        kwargs = OAuthBackend._huggingface_kwargs({})
        assert kwargs["client_id"] == "cid" and kwargs["client_secret"] == "secret"
        assert kwargs["client_kwargs"] == {"scope": "openid profile email"}
        assert kwargs["server_metadata_url"] == \
            "https://huggingface.co/.well-known/openid-configuration"

    def test_an_org_limit_adds_the_memberships_scope_once(self, no_space):
        assert OAuthBackend._huggingface_kwargs({"allowed_org": "lab"})["client_kwargs"] == \
            {"scope": "openid profile read-memberships"}
        listed = {"allowed_org": "lab", "scopes": ["openid", "read-memberships"]}
        assert OAuthBackend._huggingface_kwargs(listed)["client_kwargs"] == \
            {"scope": "openid read-memberships"}


class TestIdentityAndOrgs:
    def test_an_annotator_is_keyed_on_the_account_id(self):
        # A username can change or be re-registered by someone else; `sub`
        # is the id Hugging Face keeps across renames.
        profile = {"sub": "64f0c0ffee", "preferred_username": "ada"}
        keyed = OAuthBackend({"providers": {"huggingface": {}},
                              "user_identity_field": "sub"})
        assert keyed.extract_user_id(profile, "huggingface") == "64f0c0ffee"
        default = OAuthBackend({"providers": {"huggingface": {}}})
        assert default.extract_user_id(profile, "huggingface") == "64f0c0ffee"

    @pytest.mark.parametrize("profile,allowed", [
        ({"orgs": [{"preferred_username": "Lab"}]}, True),
        ({"organizations": [{"preferred_username": "lab"}]}, True),
        # The display name is free text an org's owners choose: an org with
        # the handle x123 displayed as "lab" must not pass.
        ({"orgs": [{"preferred_username": "x123", "name": "lab"}]}, False),
        ({"orgs": [{"preferred_username": "other"}]}, False),
        ({"orgs": ["lab"]}, False),
        ({"orgs": []}, False),
        ({}, False),                       # no memberships granted: refuse
    ])
    def test_org_membership(self, profile, allowed):
        ok, reason, _orgs = OAuthBackend.huggingface_org_check(profile, "lab")
        assert ok is allowed
        assert (reason == "") is allowed

    def test_an_org_can_be_named_by_its_id(self):
        profile = {"orgs": [{"sub": "65aa01", "preferred_username": "renamed-lab"}]}
        assert OAuthBackend.huggingface_org_check(profile, "65aa01")[0]


class TestValidation:
    def _auth(self, providers):
        return {"authentication": {"method": "oauth", "providers": providers},
                "secret_key": "x"}

    def test_an_empty_huggingface_entry_needs_the_spaces_credentials(self, no_space):
        with pytest.raises(ConfigValidationError, match="OAUTH_CLIENT_ID"):
            validate_authentication_config(self._auth({"huggingface": {}}))

    def test_in_a_space_it_validates(self, no_space, monkeypatch):
        monkeypatch.setenv("OAUTH_CLIENT_ID", "cid")
        monkeypatch.setenv("OAUTH_CLIENT_SECRET", "s")
        validate_authentication_config(self._auth({"huggingface": {}}))

    def test_outside_a_space_no_discovery_url_is_needed(self, no_space):
        validate_authentication_config(self._auth(
            {"huggingface": {"client_id": "id", "client_secret": "s"}}))

    def test_other_providers_still_need_their_credentials(self, monkeypatch):
        monkeypatch.setenv("OAUTH_CLIENT_ID", "cid")
        monkeypatch.setenv("OAUTH_CLIENT_SECRET", "s")
        with pytest.raises(ConfigValidationError, match="google.client_id"):
            validate_authentication_config(self._auth({"google": {}}))


@pytest.fixture
def workdir():
    path = create_test_directory("hf_spaces_signin")
    yield path
    cleanup_test_directory(path)


def _write_config(workdir, config):
    path = os.path.join(workdir, "config.yaml")
    with open(path, "w") as handle:
        yaml.safe_dump(config, handle)
    return path


class TestDeploy:
    def test_the_readme_turns_on_hf_oauth_and_the_org_limit(self):
        spec = DeploySpec(name="pilot", config_path="c.yaml",
                          extra={"hf_oauth": True, "hf_oauth_org": "lab"})
        front = space_files(spec)["README.md"].split("---")[1]
        meta = yaml.safe_load(front)
        assert meta["hf_oauth"] is True
        assert meta["hf_oauth_authorized_org"] == "lab"
        assert meta["hf_oauth_scopes"] == ["read-memberships"]
        assert meta["sdk"] == "docker" and meta["app_port"] == 7860

    def test_without_the_flag_the_readme_has_no_sign_in(self):
        meta = yaml.safe_load(space_files(DeploySpec(name="p", config_path="c.yaml"))
                              ["README.md"].split("---")[1])
        assert "hf_oauth" not in meta

    def test_the_config_signs_in_with_hugging_face(self, workdir):
        path = _write_config(workdir, {"annotation_task_name": "t"})
        _inject_hf_oauth_config(path, "lab")
        with open(path) as handle:
            auth = yaml.safe_load(handle)["authentication"]
        assert auth == {"user_identity_field": "sub", "method": "oauth",
                        "providers": {"huggingface": {"allowed_org": "lab"}}}

    def test_an_existing_oauth_config_keeps_its_providers(self, workdir):
        path = _write_config(workdir, {"authentication": {
            "method": "oauth", "user_identity_field": "email",
            "providers": {"google": {"client_id": "g", "client_secret": "s"}}}})
        _inject_hf_oauth_config(path, None)
        with open(path) as handle:
            auth = yaml.safe_load(handle)["authentication"]
        assert set(auth["providers"]) == {"google", "huggingface"}
        assert auth["user_identity_field"] == "email"

    def test_another_sign_in_method_is_refused(self, workdir):
        path = _write_config(workdir, {"authentication": {"method": "clerk"}})
        with pytest.raises(ProviderError, match="clerk"):
            _inject_hf_oauth_config(path, None)

    def test_the_deployed_backup_writes_responses(self, workdir):
        path = _write_config(workdir, {})
        _inject_backup_config(path, "me/pilot-annotations", 5)
        with open(path) as handle:
            sink = yaml.safe_load(handle)["backup"]["sinks"][0]
        assert sink["type"] == "huggingface" and sink["responses"] is True

    @pytest.mark.parametrize("flags, warned", [([], True), (["--hf-oauth"], False),
                                               (["--hf-oauth-org", "lab"], False)])
    def test_the_dry_run_knows_hf_oauth_closes_sign_in(self, capsys, monkeypatch, flags, warned):
        """potato-skill, 2.12.0 pack notes (P7): --hf-oauth --dry-run still
        warned D003 (anyone can register), though the bundled config signs in
        with Hugging Face."""
        from potato.deploy.cli import main
        monkeypatch.setenv("HF_TOKEN", "")
        config = os.path.join(os.path.dirname(__file__), "..", "..", "examples",
                              "classification", "single-choice", "config.yaml")
        main(["up", config, "--provider", "huggingface", "--dry-run"] + flags)
        assert ("[D003]" in capsys.readouterr().out) is warned

    def test_the_flag_is_refused_on_other_providers(self, capsys):
        from potato.deploy.cli import main
        code = main(["up", "config.yaml", "--provider", "render", "--hf-oauth"])
        assert code == 2
        assert "--provider huggingface" in capsys.readouterr().out


def _state(workdir, user, labels, spans=None):
    folder = os.path.join(workdir, "annotation_output", user)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "user_state.json"), "w") as handle:
        json.dump({"user_id": user,
                   "instance_id_to_label_to_value": labels,
                   "instance_id_to_span_to_value": spans or {}}, handle)


class TestResponses:
    @pytest.fixture
    def config(self, workdir):
        _state(workdir, "ada", {
            "a": [[{"schema": "sentiment", "name": "positive"}, "positive"]],
            "b": [[{"schema": "sentiment", "name": "negative"}, "negative"],
                  [{"schema": "topics", "name": "sport"}, "true"],
                  [{"schema": "topics", "name": "art"}, "true"]]},
            {"a": [[{"schema": "ner", "name": "PER", "start": 0, "end": 3,
                     "title": "PER"}, "PER"]]})
        _state(workdir, "grace@lab.org", {
            "a": [[{"schema": "sentiment", "name": "negative"}, "negative"]]})
        _state(workdir, "idle", {})
        return {"task_dir": workdir, "annotation_task_name": "Pilot",
                "output_annotation_dir": os.path.join(workdir, "annotation_output"),
                "annotation_schemes": [{"annotation_type": "radio", "name": "sentiment"}]}

    def test_one_row_per_item_and_scheme(self, config):
        rows = response_rows(config)
        assert set(rows) == {"ada", "grace@lab.org"}          # idle has no answers
        ada = {(r["instance_id"], r["scheme"]): r for r in rows["ada"]}
        assert set(ada) == {("a", "sentiment"), ("a", "ner"), ("b", "sentiment"),
                            ("b", "topics")}
        assert ada[("b", "topics")]["labels"] == ["sport", "art"]
        assert json.loads(ada[("b", "topics")]["value"]) == {"sport": "true", "art": "true"}
        assert ada[("a", "ner")]["kind"] == "spans"
        assert ada[("a", "ner")]["labels"] == ["PER"]
        columns = {tuple(sorted(r)) for user in rows.values() for r in user}
        assert columns == {("annotator", "instance_id", "kind", "labels", "scheme", "value")}

    def test_the_export_is_written_and_rewritten(self, config, workdir):
        dest = os.path.join(workdir, "hub")
        assert write_hub_export(config, dest, "me/pilot-annotations") == 5
        files = sorted(os.listdir(os.path.join(dest, "_responses")))
        assert files == sorted(["ada.responses.jsonl", annotator_filename("grace@lab.org")])
        card = open(os.path.join(dest, "README.md")).read()
        assert "path: _responses/*.responses.jsonl" in card
        assert 'load_dataset("me/pilot-annotations"' in card
        # An annotator who no longer has answers loses their file.
        _state(workdir, "grace@lab.org", {})
        write_hub_export(config, dest, "me/pilot-annotations")
        assert os.listdir(os.path.join(dest, "_responses")) == ["ada.responses.jsonl"]

    def test_datasets_reads_it_as_one_table(self, config, workdir):
        datasets = pytest.importorskip("datasets")
        dest = os.path.join(workdir, "hub")
        write_hub_export(config, dest, "me/pilot-annotations")
        table = datasets.load_dataset(dest, split="train")
        assert table.num_rows == 5
        assert sorted(set(table["annotator"])) == ["ada", "grace@lab.org"]

    def test_names_that_sanitize_alike_get_different_files(self):
        assert annotator_filename("a b") != annotator_filename("a_b")
        assert annotator_filename("ada") == "ada.responses.jsonl"
        assert "/" not in annotator_filename("../../etc")

    def test_restore_does_not_bring_the_export_back_as_data(self, workdir):
        source = os.path.join(workdir, "row.jsonl")
        open(source, "w").write("{}\n")
        out, snap = os.path.join(workdir, "out"), os.path.join(workdir, "snap")
        assert _place("_responses/ada.responses.jsonl", source, out, snap) == 0
        assert not os.path.exists(os.path.join(out, "_responses"))
        # A user whose id is the export's folder name is still restored.
        assert _place("_responses/user_state.json", source, out, snap) == 1

    def test_staging_folders_never_ride_along_with_the_output_dir(self, config,
                                                                   monkeypatch):
        # With output_annotation_dir: "." the output-dir scheduler watches the
        # whole task directory, staging folders included.
        import fnmatch
        import sys
        import types
        from potato.server_utils.backup.hf_sink import HuggingFaceSink
        monkeypatch.setenv("HF_TOKEN", "hf_x")
        made = []
        fake = types.ModuleType("huggingface_hub")
        fake.CommitScheduler = lambda **kwargs: made.append(kwargs) or object()
        monkeypatch.setitem(sys.modules, "huggingface_hub", fake)
        config = {**config, "output_annotation_dir": config["task_dir"]}
        assert HuggingFaceSink({"repo_id": "me/x", "responses": True}, config).start(5)
        output = next(k for k in made if k["folder_path"] == config["task_dir"])
        for staged in (".potato-hub/_responses/ada.responses.jsonl",
                       ".potato-backup/project.sqlite"):
            assert any(fnmatch.fnmatch(staged, pattern)
                       for pattern in output["ignore_patterns"]), staged

    def test_the_card_glob_cannot_reach_an_annotator_folder(self, config, workdir):
        # The annotation directory is mirrored to the same repo root, one
        # folder per user id. A user named like the export's folder must not
        # put their history file inside the dataset.
        import fnmatch
        _state(workdir, "_responses", {
            "a": [[{"schema": "sentiment", "name": "positive"}, "positive"]]})
        open(os.path.join(workdir, "annotation_output", "_responses",
                          "annotation_history.jsonl"), "w").write("{}\n")
        card = write_hub_export(config, os.path.join(workdir, "hub"), "me/x") and \
            open(os.path.join(workdir, "hub", "README.md")).read()
        glob = next(line.split("path: ")[1] for line in card.splitlines()
                    if "path: " in line)
        mirrored = [os.path.relpath(os.path.join(d, f),
                                    os.path.join(workdir, "annotation_output"))
                    for d, _, fs in os.walk(os.path.join(workdir, "annotation_output"))
                    for f in fs]
        assert mirrored and not [p for p in mirrored if fnmatch.fnmatch(p, glob)]

    def test_a_public_backup_says_it_publishes_the_answers(self, config, caplog,
                                                            monkeypatch):
        import sys
        import types
        from potato.server_utils.backup.hf_sink import HuggingFaceSink
        monkeypatch.setenv("HF_TOKEN", "hf_x")
        fake = types.ModuleType("huggingface_hub")
        fake.CommitScheduler = lambda **kwargs: object()
        monkeypatch.setitem(sys.modules, "huggingface_hub", fake)
        for private, warned in ((False, True), (True, False)):
            caplog.clear()
            sink = HuggingFaceSink({"repo_id": "me/x", "private": private,
                                    "responses": True}, config)
            assert sink.start(5)
            assert ("anyone can read them" in caplog.text) is warned
        assert os.path.isdir(os.path.join(config["task_dir"], ".potato-hub",
                                          "_responses"))

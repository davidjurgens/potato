"""
Depositing a snapshot on Zenodo: what is refused before anything is sent,
what is uploaded, the record kept beside the snapshots, and checking a
downloaded copy with ``verify --dir``.

Zenodo's REST calls are replaced on ``requests``; every call is recorded so a
refusal can be shown to have sent nothing.
"""

import json
import os
import shutil

import pytest
import yaml

from potato.snapshots import build, cli, deposit, store
from tests.unit.test_snapshots import T0, answer, project  # noqa: F401  (fixture)


class FakeZenodo:
    def __init__(self, monkeypatch, publish_doi="10.5281/zenodo.42"):
        import requests
        self.calls = []
        self.uploaded = {}
        self.publish_doi = publish_doi
        monkeypatch.setattr(requests, "post", self.post)
        monkeypatch.setattr(requests, "put", self.put)

    class Resp:
        def __init__(self, data):
            self._data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self._data

    def post(self, url, json=None, timeout=None, params=None):
        self.calls.append(("POST", url))
        if url.endswith("/actions/publish"):
            return self.Resp({"doi": self.publish_doi,
                              "links": {"html": "https://zenodo.org/records/42"}})
        return self.Resp({"id": 42, "links": {"bucket": "https://zenodo/api/files/b42",
                                              "html": "https://sandbox.zenodo.org/deposit/42"},
                          "metadata": {"prereserve_doi": {"doi": "10.5072/zenodo.42"}}})

    def put(self, url, data=None, json=None, timeout=None, params=None):
        self.calls.append(("PUT", url))
        if "/files/" in url:
            self.uploaded[url.rsplit("/", 1)[1]] = data.read()
        else:
            self.metadata = json
        return self.Resp({})


class TestRefusals:
    def test_annotator_ids_need_saying_so_and_nothing_is_sent(self, project, monkeypatch):
        build.create_snapshot(project, now=T0)
        zen = FakeZenodo(monkeypatch)
        with pytest.raises(deposit.DepositRefused) as caught:
            deposit.deposit_snapshot(project, token="t")
        assert "2 annotator id(s)" in str(caught.value) and "a, b" in str(caught.value)
        assert zen.calls == []

    def test_email_addresses_are_named(self, project, monkeypatch):
        answer(os.path.dirname(project), "pat@uni.edu", {"i0": "x"})
        build.create_snapshot(project, now=T0)
        check = deposit.check_snapshot(project)
        assert check["email_like_annotators"] == ["pat@uni.edu"]
        assert "1 of them email addresses (pat@uni.edu)" in deposit.refusals(check, False)[0]

    @pytest.mark.parametrize("block", [
        {"ai_support": {"ai_config": {"api_key": "sk-abcdefghijklmnopqrstuvwx"}}},
        {"admin_api_key": "a-long-literal-admin-key"},   # caught by its suffix
    ])
    def test_a_literal_credential_stops_it_whatever_the_flags(self, project, monkeypatch, block):
        config = yaml.safe_load(open(project))
        config.update(block)
        yaml.safe_dump(config, open(project, "w"))
        build.create_snapshot(project, now=T0)
        zen = FakeZenodo(monkeypatch)
        with pytest.raises(deposit.DepositRefused) as caught:
            deposit.deposit_snapshot(project, token="t", annotator_ids_public=True)
        assert "project/config.yaml" in str(caught.value) and "${ENV_VAR}" in str(caught.value)
        assert zen.calls == []

    def test_an_env_reference_is_not_a_credential(self, project):
        config = yaml.safe_load(open(project))
        config["admin_api_key"] = "${POTATO_ADMIN_KEY}"
        yaml.safe_dump(config, open(project, "w"))
        build.create_snapshot(project, now=T0)
        assert deposit.check_snapshot(project)["secrets"] == []


PEM = ("-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7\n"
       "-----END PRIVATE KEY-----\n")


def edit_config(project, **changes):
    config = yaml.safe_load(open(project))
    config.update(changes)
    yaml.safe_dump(config, open(project, "w"))


def write(project, name, text):
    path = os.path.join(os.path.dirname(project), name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        handle.write(text)


def bundle_names(project, manifest):
    import tarfile
    folder = store.snapshot_folder(project, manifest["id"])
    with tarfile.open(os.path.join(folder, "bundle.tar.gz")) as archive:
        return archive.getnames()


class TestWhatTheBundleHolds:
    """The audit's probe: key files, a JSON config with a key, and an
    annotator who only has a saved state."""

    def test_key_files_named_in_the_config_stay_out_of_the_snapshot(self, project):
        write(project, "tls/server.key", PEM)
        write(project, "saml/sp.key", PEM)
        edit_config(project, ssl_key="tls/server.key",
                    authentication={"saml": {"sp_key_file": "saml/sp.key"}})
        manifest = build.create_snapshot(project, now=T0)
        names = bundle_names(project, manifest)
        assert "project/tls/server.key" not in names and "project/saml/sp.key" not in names
        assert deposit.check_snapshot(project)["private_keys"] == []

    def test_a_private_key_under_any_other_name_stops_it(self, project, monkeypatch):
        write(project, "docs/notes.md", "setup notes\n" + PEM)
        edit_config(project, instructions_file="docs/notes.md")
        build.create_snapshot(project, now=T0)
        zen = FakeZenodo(monkeypatch)
        with pytest.raises(deposit.DepositRefused) as caught:
            deposit.deposit_snapshot(project, token="t", annotator_ids_public=True)
        assert "private key (project/docs/notes.md)" in str(caught.value)
        assert zen.calls == []

    def test_a_literal_key_in_a_json_config_stops_it(self, project):
        write(project, "ai.json", json.dumps({"api_key": "sk-ant-api03-abcdefghijklmnop"}))
        edit_config(project, ai_support={"enabled": True, "ai_config_file": "ai.json"})
        build.create_snapshot(project, now=T0)
        check = deposit.check_snapshot(project)
        assert check["secrets"] == ["project/ai.json: api_key"]
        assert "project/ai.json: api_key" in deposit.refusals(check, True)[0]

    @pytest.mark.parametrize("name,text", [
        ("extra.ini", "[ai]\napi_key = sk-ant-api03-BBBBBBBBBBBBBBBBBBBBBBBB\n"),
        ("layouts/custom.html", "<script>const key = 'hf_abcdefghijklmnopqrstuv';</script>\n"),
        ("headers.yaml", "auth: Bearer sk-proj-abcdefghijklmnopqrstuv\n"),   # inside a string
    ])
    def test_a_provider_key_in_any_other_file_stops_it(self, project, name, text):
        write(project, name, text)
        edit_config(project, html_layout=name)
        build.create_snapshot(project, now=T0)
        check = deposit.check_snapshot(project)
        assert check["provider_keys"] == [f"project/{name}"]
        assert any("shaped like a provider's API key" in r for r in deposit.refusals(check, True))

    def test_a_key_the_parsed_check_names_is_reported_once(self, project):
        write(project, "ai.json", json.dumps({"api_key": "sk-ant-api03-abcdefghijklmnop"}))
        edit_config(project, ai_support={"ai_config_file": "ai.json"})
        build.create_snapshot(project, now=T0)
        check = deposit.check_snapshot(project)
        assert check["secrets"] == ["project/ai.json: api_key"] and check["provider_keys"] == []

    def test_a_config_file_that_cannot_be_read_stops_it(self, project):
        write(project, "surveys/pre.yaml", "questions: [unclosed\n")
        edit_config(project, surveys=["surveys/pre.yaml"])
        build.create_snapshot(project, now=T0)
        check = deposit.check_snapshot(project)
        assert check["unreadable"] == ["project/surveys/pre.yaml (ParserError)"]
        assert any("could not be read" in r for r in deposit.refusals(check, True))

    def test_data_files_are_not_read_as_config(self, project):
        # A data item's `token` field is text, not a credential, even in a
        # .json file of JSON lines.
        write(project, "data/more.json",
              json.dumps({"id": "j0", "text": "x", "token": "an-ordinary-long-token"}) + "\n"
              + json.dumps({"id": "j1", "text": "y", "token": "another-long-token-x"}) + "\n")
        edit_config(project, data_files=["data/items.jsonl", "data/more.json"])
        build.create_snapshot(project, now=T0)
        check = deposit.check_snapshot(project)
        assert (check["secrets"], check["unreadable"]) == ([], [])

    def test_an_annotator_with_only_a_saved_state_is_counted(self, project):
        answer(os.path.dirname(project), "ghost@uni.edu", {})
        manifest = build.create_snapshot(project, now=T0)
        assert "project/annotation_output/ghost@uni.edu/user_state.json" in bundle_names(project, manifest)
        check = deposit.check_snapshot(project)
        assert check["annotators"] == ["a", "b", "ghost@uni.edu"]
        assert check["email_like_annotators"] == ["ghost@uni.edu"]
        refusal = deposit.refusals(check, False)[0]
        assert "3 annotator id(s)" in refusal and "consent and survey answers" in refusal


class TestDeposit:
    def test_the_files_metadata_and_record(self, project, monkeypatch):
        manifest = build.create_snapshot(project, now=T0)
        zen = FakeZenodo(monkeypatch)
        result = deposit.deposit_snapshot(project, token="t", annotator_ids_public=True)
        assert sorted(zen.uploaded) == sorted(list(deposit.DEPOSIT_FILES) + ["README.md"])
        folder = store.snapshot_folder(project, manifest["id"])
        with open(os.path.join(folder, "bundle.tar.gz"), "rb") as handle:
            assert zen.uploaded["bundle.tar.gz"] == handle.read()
        meta = zen.metadata["metadata"]
        assert meta["version"] == manifest["id"]
        assert meta["title"] == f"Snap (Potato snapshot {manifest['id']})"
        assert manifest["content_hash"] in meta["description"]
        # Sandbox draft by default: no publish call, the reserved DOI.
        assert zen.calls[0] == ("POST", "https://sandbox.zenodo.org/api/deposit/depositions")
        assert not any(url.endswith("/actions/publish") for _m, url in zen.calls)
        assert (result["doi"], result["published"], result["sandbox"]) == ("10.5072/zenodo.42", False, True)
        [listed] = store.list_snapshots(project)
        assert listed["deposits"][0]["deposition_id"] == 42

    def test_a_downloaded_copy_verifies_and_tampering_shows(self, project, monkeypatch, tmp_path):
        build.create_snapshot(project, now=T0)
        zen = FakeZenodo(monkeypatch)
        deposit.deposit_snapshot(project, token="t", annotator_ids_public=True)
        download = tmp_path / "download"
        download.mkdir()
        for name, content in zen.uploaded.items():
            (download / name).write_bytes(content)
        assert store.verify_folder(str(download))["ok"]
        (download / "annotations.jsonl").write_bytes(
            zen.uploaded["annotations.jsonl"].replace(b'"x"', b'"y"', 1))
        result = store.verify_folder(str(download))
        assert not result["ok"] and "annotations_sha256" in result["problems"][0]
        os.remove(download / "items.json")
        assert store.verify_folder(str(download))["problems"] == ["items.json is missing"]

    def test_only_a_published_production_doi_reaches_the_card(self, project, monkeypatch):
        from potato.publish.dataset_card import _citation_section
        from potato.publish.bundle import PublishBundle
        from potato.publish.config import DatasetMetadata

        build.create_snapshot(project, now=T0)
        FakeZenodo(monkeypatch)
        deposit.deposit_snapshot(project, token="t", annotator_ids_public=True)   # sandbox draft
        bundle = PublishBundle(splits={}, schemas=[], metadata=DatasetMetadata(pretty_name="Snap"), config={})
        bundle.snapshot = store.list_snapshots(project)[0]
        assert "doi.org" not in _citation_section(bundle)
        deposit.deposit_snapshot(project, token="t", sandbox=False, publish=True,
                                 annotator_ids_public=True)
        bundle.snapshot = store.list_snapshots(project)[0]
        assert "https://doi.org/10.5281/zenodo.42" in _citation_section(bundle)


class TestCli:
    def test_check_lists_and_sends_nothing(self, project, monkeypatch, capsys):
        build.create_snapshot(project, now=T0)
        zen = FakeZenodo(monkeypatch)
        assert cli.main(["deposit", project, "--check", "--annotator-ids-public"]) == 0
        out = capsys.readouterr().out
        assert "bundle.tar.gz" in out and "Nothing sent" in out
        assert cli.main(["deposit", project, "--check"]) == 1
        assert "refused: the deposit publishes 2 annotator id(s)" in capsys.readouterr().err
        assert zen.calls == []

    def test_deposit_then_show_and_verify_dir(self, project, monkeypatch, capsys, tmp_path):
        manifest = build.create_snapshot(project, now=T0)
        FakeZenodo(monkeypatch)
        assert cli.main(["deposit", project, "--annotator-ids-public", "--token", "t"]) == 0
        assert "DOI 10.5072/zenodo.42 (reserved" in capsys.readouterr().out
        assert cli.main(["show", project]) == 0
        assert "deposited     Zenodo sandbox, draft, 10.5072/zenodo.42" in capsys.readouterr().out
        copy = tmp_path / "copy"
        shutil.copytree(store.snapshot_folder(project, manifest["id"]), copy)
        assert cli.main(["verify", "--dir", str(copy)]) == 0
        out = capsys.readouterr().out
        assert f"{manifest['id']}: OK" in out
        # OK only says the files match the manifest beside them; the hash
        # says which snapshot it is.
        assert f"content hash {manifest['content_hash']}" in out and "Compare it" in out


class TestDeployPreflightSharesTheCheck:
    def test_suffix_names_count_but_env_names_do_not(self):
        from potato.deploy.preflight import literal_secrets
        config = {"admin_api_key": "a-long-literal-admin-key",
                  "trace_ingestion": {"langfuse": {"secret_key_env": "LANGFUSE_SECRET_KEY_NAME"}},
                  "ai_support": {"ai_config": {"max_tokens": "4096000000000"}},
                  "session_secret": "${SESSION_SECRET}",
                  "short_token": "abc"}
        assert literal_secrets(config) == ["admin_api_key"]


class TestRecord:
    def test_deposits_finishing_together_all_land(self, project):
        import threading
        manifest = build.create_snapshot(project, now=T0)
        errors = []

        def record(n):
            try:
                for i in range(20):
                    deposit._record(project, manifest["id"], {"deposition_id": f"{n}-{i}"})
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=record, args=(n,)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        root = build.project_paths(project)["snapshot_root"]
        assert len(deposit.read_deposits(root)[manifest["id"]]) == 80
        assert not [n for n in os.listdir(root) if n.endswith(".tmp")]

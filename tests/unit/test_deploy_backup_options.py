"""`deploy up` backup flags, the bundle store, and what reaches the bundle.

The bug these guard: `--hf-token` on Render or DigitalOcean exported HF_TOKEN
and wrote nothing into the bundled config, so the server never started a
backup, while Render's free-tier refusal counted the flag as a configured one.
"""

import argparse
import os
import tarfile

import pytest
import yaml

from potato.deploy import cli
from potato.deploy.backup_options import (
    BackupOptions,
    BackupOptionsError,
    apply_to_config,
    from_args,
)
from potato.deploy.bundle import KEEP_LIST_NAME, build_bundle
from potato.deploy.bundle_store import (
    S3_MAX_EXPIRY_SECONDS,
    BundleLocation,
    HuggingFaceBundleStore,
    S3BundleStore,
    file_sha256,
    publish,
    store_for,
)


def args(**kwargs):
    defaults = dict(backup=None, hf_token=None, hf_backup_repo=None, s3_bucket=None,
                    s3_prefix=None, s3_region=None, s3_endpoint=None,
                    backup_minutes=None)
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


class TestFromArgs:
    def test_no_flags_no_backup(self):
        assert not from_args(args(), "pilot", environ={}).enabled

    def test_hf_token_alone_still_means_an_hf_backup(self):
        """What it meant before --backup existed."""
        assert from_args(args(hf_token="hf_x"), "pilot", environ={}).kinds == ["hf"]

    def test_hf_token_in_the_environment_alone_does_not(self):
        """HF_TOKEN is often set for unrelated reasons."""
        assert not from_args(args(), "pilot", environ={"HF_TOKEN": "hf_x"}).enabled

    def test_s3_bucket_alone_means_an_s3_backup(self):
        assert from_args(args(s3_bucket="b"), "pilot", environ={}).kinds == ["s3"]

    def test_both(self):
        options = from_args(args(backup="hf,s3", s3_bucket="b"), "pilot",
                            environ={"HF_TOKEN": "hf_x"})
        assert options.kinds == ["hf", "s3"]

    def test_hf_without_a_token_is_refused(self):
        with pytest.raises(BackupOptionsError, match="--hf-token"):
            from_args(args(backup="hf"), "pilot", environ={})

    def test_s3_without_a_bucket_is_refused(self):
        with pytest.raises(BackupOptionsError, match="--s3-bucket"):
            from_args(args(backup="s3"), "pilot", environ={})

    def test_unknown_target_is_refused(self):
        with pytest.raises(BackupOptionsError, match="ftp"):
            from_args(args(backup="ftp"), "pilot", environ={})

    def test_s3_prefix_defaults_to_the_deployment_name(self):
        assert from_args(args(s3_bucket="b"), "pilot",
                         environ={}).s3_prefix == "potato/pilot"


class TestConfigAndSecrets:
    def options(self):
        return BackupOptions(kinds=["hf", "s3"], hf_token="hf_SECRET",
                             hf_repo="me/r", s3_bucket="b",
                             s3_access_key_id="AKIA_SECRET",
                             s3_secret_access_key="S3_SECRET")

    def test_no_credential_reaches_the_config(self):
        block = yaml.safe_dump(self.options().config_block())
        for secret in ("hf_SECRET", "AKIA_SECRET", "S3_SECRET"):
            assert secret not in block

    def test_credentials_travel_as_secrets(self):
        assert self.options().secrets() == {
            "HF_TOKEN": "hf_SECRET",
            "POTATO_S3_ACCESS_KEY_ID": "AKIA_SECRET",
            "POTATO_S3_SECRET_ACCESS_KEY": "S3_SECRET"}

    def test_the_block_replaces_the_legacy_one(self):
        config = apply_to_config({"huggingface_backup": {"enabled": True}},
                                 self.options())
        assert "huggingface_backup" not in config
        assert config["backup"]["restore_on_boot"] is True

    def test_the_server_reads_what_the_cli_writes(self):
        from potato.server_utils.backup import resolve_settings

        config = apply_to_config({}, self.options())
        settings = resolve_settings(config)
        assert [s["type"] for s in settings.sinks] == ["huggingface", "s3"]


class TestBundleStore:
    def test_hf_is_preferred_because_its_url_never_expires(self):
        options = BackupOptions(kinds=["s3", "hf"], hf_token="t", hf_repo="me/r",
                                s3_bucket="b")
        assert isinstance(store_for(options), HuggingFaceBundleStore)

    def test_s3_when_that_is_all_there_is(self):
        assert isinstance(store_for(BackupOptions(kinds=["s3"], s3_bucket="b")),
                          S3BundleStore)

    def test_no_backup_no_store(self):
        assert store_for(BackupOptions()) is None

    def test_hf_url_is_inside_the_bundle_directory(self):
        url = HuggingFaceBundleStore("me/r", "t").url_for("abc")
        assert url == ("https://huggingface.co/datasets/me/r/resolve/main/"
                       "_bundle/abc.tar.gz")

    def test_location_env(self):
        env = BundleLocation(url="u", sha256="s", token="t").env()
        assert env == {"POTATO_BUNDLE_URL": "u", "POTATO_BUNDLE_SHA256": "s",
                       "POTATO_BUNDLE_TOKEN": "t"}
        assert "POTATO_BUNDLE_TOKEN" not in BundleLocation(url="u", sha256="s").env()

    def test_s3_presigns_within_the_sigv4_limit(self, tmp_path, monkeypatch):
        seen = {}

        class FakeClient:
            def upload_file(self, path, bucket, key):
                seen["key"] = key

            def generate_presigned_url(self, op, Params, ExpiresIn):
                seen["expires"] = ExpiresIn
                return f"https://s3/{Params['Key']}?sig"

        monkeypatch.setattr(S3BundleStore, "client", lambda self: FakeClient())
        store = S3BundleStore("b", "potato/pilot", expires_seconds=10 ** 9)
        tarball = tmp_path / "x.tar.gz"
        tarball.write_bytes(b"x")
        location = store.put(str(tarball), "abc")
        assert seen["key"] == "potato/pilot/_bundle/abc.tar.gz"
        assert seen["expires"] == S3_MAX_EXPIRY_SECONDS
        assert location.url.endswith("?sig")


@pytest.fixture
def project(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "items.json").write_text('[{"id":"1","text":"hi"}]')
    config = {
        "task_dir": ".", "annotation_task_name": "backup test",
        "data_files": ["data/items.json"],
        "output_annotation_dir": "annotation_output/study/",
        "item_properties": {"id_key": "id", "text_key": "text"},
        "annotation_schemes": [{"annotation_type": "radio", "name": "s",
                                "description": "d", "labels": ["a", "b"]}],
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False))
    return str(path)


class TestPublishedBundle:
    def test_keep_list_names_the_collected_data(self, project, tmp_path):
        manifest = build_bundle(project, str(tmp_path / "out"))
        keep = (tmp_path / "out" / KEEP_LIST_NAME).read_text().split()
        assert "annotation_output" in keep
        assert "project.sqlite" in keep

    def test_tarball_carries_the_keep_list_and_a_stable_sha(self, project, tmp_path):
        manifest = build_bundle(project, str(tmp_path / "out"))

        class Recorder:
            def put(self, path, sha):
                with tarfile.open(path) as archive:
                    names = archive.getnames()
                return BundleLocation(url="u", sha256=sha), names

        first, names = publish(manifest, Recorder(), str(tmp_path / "dist"))
        second, _ = publish(manifest, Recorder(), str(tmp_path / "dist2"))
        assert KEEP_LIST_NAME in names
        assert first.sha256 == second.sha256
        assert first.sha256 == file_sha256(str(tmp_path / "dist" / "bundle.tar.gz"))


def _bundled_config(project, provider, name="backup-test"):
    path = os.path.join(os.path.dirname(project), ".potato", "bundle", provider,
                        name, "config.yaml")
    with open(path) as handle:
        return yaml.safe_load(handle)


class TestUpWritesTheBackup:
    @pytest.mark.parametrize("provider", ["render", "digitalocean"])
    def test_hf_token_configures_a_backup_on_every_provider(self, project,
                                                           provider, capsys):
        code = cli.main(["up", project, "--provider", provider, "--dry-run",
                         "--hf-token", "hf_SECRET_TOKEN",
                         "--hf-backup-repo", "me/backup-test-annotations"])
        assert code == cli.EXIT_OK
        config = _bundled_config(project, provider)
        sinks = config["backup"]["sinks"]
        assert sinks == [{"type": "huggingface",
                          "repo_id": "me/backup-test-annotations",
                          "repo_type": "dataset", "private": True}]
        assert config["backup"]["restore_on_boot"] is True
        assert "hf_SECRET_TOKEN" not in yaml.safe_dump(config)

    def test_s3_backup_reaches_the_bundle(self, project, capsys):
        cli.main(["up", project, "--provider", "render", "--dry-run",
                  "--backup", "s3", "--s3-bucket", "my-bucket",
                  "--s3-endpoint", "https://r2.example"])
        sink = _bundled_config(project, "render")["backup"]["sinks"][0]
        assert sink == {"type": "s3", "bucket": "my-bucket",
                        "prefix": "potato/backup-test",
                        "endpoint_url": "https://r2.example"}

    def test_render_plan_says_where_the_project_goes(self, project, capsys):
        cli.main(["up", project, "--provider", "render", "--dry-run",
                  "--hf-token", "hf_x", "--hf-backup-repo", "me/r"])
        out = capsys.readouterr().out
        assert "bundle.publish" in out
        assert "me/r" in out

    def test_preflight_stops_warning_once_a_backup_is_configured(self, project,
                                                                 capsys):
        cli.main(["up", project, "--provider", "render", "--dry-run"])
        assert "D011" in capsys.readouterr().out
        cli.main(["up", project, "--provider", "render", "--dry-run",
                  "--hf-token", "hf_x", "--hf-backup-repo", "me/r"])
        assert "D011" not in capsys.readouterr().out

    def test_bad_backup_flags_fail_before_anything_is_built(self, project, capsys):
        code = cli.main(["up", project, "--provider", "render", "--dry-run",
                         "--backup", "s3"])
        assert code == cli.EXIT_ERROR
        assert "--s3-bucket" in capsys.readouterr().out

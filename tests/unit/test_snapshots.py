"""
Citable snapshots: freezing, refusing duplicates, diffs, tags and integrity.

The project is built on disk the way a running server leaves it: a config, a
data file, and one user_state.json per annotator in the live-save shape.
"""

import json
import os
import sqlite3
import stat
import tarfile
from datetime import datetime, timezone

import pytest
import yaml

from potato.snapshots import build, cli, diff, store
from tests.helpers.test_utils import cleanup_test_directory, create_test_directory

T0 = datetime(2026, 10, 19, 12, 0, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 10, 19, 12, 5, 0, tzinfo=timezone.utc)
T2 = datetime(2026, 10, 19, 12, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
def project():
    root = create_test_directory("snapshots")
    os.makedirs(os.path.join(root, "data"))
    with open(os.path.join(root, "data", "items.jsonl"), "w") as handle:
        for i in range(4):
            handle.write(json.dumps({"id": f"i{i}", "text": f"t{i}"}) + "\n")
    config = {"annotation_task_name": "Snap", "task_dir": ".",
              "output_annotation_dir": "annotation_output/",
              "data_files": ["data/items.jsonl"],
              "item_properties": {"id_key": "id", "text_key": "text"},
              "annotation_schemes": [{"annotation_type": "radio", "name": "s",
                                      "description": "d", "labels": ["x", "y"]}]}
    path = os.path.join(root, "config.yaml")
    with open(path, "w") as handle:
        yaml.safe_dump(config, handle)
    # Units (x,x) (x,y) (y,y) (y,y): alpha 8/15, worked in test_fiftyone_project.
    answer(root, "a", dict(zip(["i0", "i1", "i2", "i3"], "xxyy")))
    answer(root, "b", dict(zip(["i0", "i1", "i2", "i3"], "xyyy")))
    with open(os.path.join(root, "annotation_output", "admin_api_key.txt"), "w") as handle:
        handle.write("secret")
    yield path
    for dirpath, dirnames, filenames in os.walk(root):
        for name in filenames:
            os.chmod(os.path.join(dirpath, name), stat.S_IRUSR | stat.S_IWUSR)
    cleanup_test_directory(root)


def answer(root, user, labels):
    folder = os.path.join(root, "annotation_output", user)
    os.makedirs(folder, exist_ok=True)
    state = {"user_id": user, "instance_id_to_label_to_value": {
        iid: [[{"schema": "s", "name": v}, v]] for iid, v in labels.items()}}
    with open(os.path.join(folder, "user_state.json"), "w") as handle:
        json.dump(state, handle)


def folder_of(config, manifest):
    return store.snapshot_folder(config, manifest["id"])


class TestCreate:
    def test_a_snapshot_is_frozen_and_counted(self, project):
        manifest = build.create_snapshot(project, note="first", now=T0)
        assert manifest["id"] == f"20261019-120000-{manifest['content_hash'][:8]}"
        assert manifest["counts"] == {"items": 4, "annotators": 2,
                                      "annotated_items": 4, "annotations": 8}
        assert manifest["agreement"]["schemes"][0]["alpha"] == pytest.approx(8 / 15)
        folder = folder_of(project, manifest)
        assert sorted(os.listdir(folder)) == ["annotations.jsonl", "bundle.tar.gz",
                                              "items.json", "manifest.json"]
        for name in os.listdir(folder):
            assert not os.stat(os.path.join(folder, name)).st_mode & stat.S_IWUSR

    def test_the_bundle_holds_the_project_but_not_the_api_key(self, project):
        db = sqlite3.connect(os.path.join(os.path.dirname(project), "project.sqlite"))
        db.execute("create table memos (body text)")
        db.commit()
        db.close()
        manifest = build.create_snapshot(project, now=T0)
        with tarfile.open(os.path.join(folder_of(project, manifest), "bundle.tar.gz")) as tar:
            names = set(tar.getnames())
        assert {"project/config.yaml", "project/data/items.jsonl",
                "project/annotation_output/a/user_state.json",
                "project/project.sqlite"} <= names
        assert not any(n.endswith("admin_api_key.txt") for n in names)

    def test_unchanged_content_is_not_snapshotted_twice(self, project):
        first = build.create_snapshot(project, now=T0)
        with pytest.raises(build.SnapshotUnchanged) as caught:
            build.create_snapshot(project, now=T1)
        assert caught.value.existing["id"] == first["id"]
        forced = build.create_snapshot(project, force=True, now=T1)
        assert forced["content_hash"] == first["content_hash"]
        assert forced["previous"] == first["id"]

    def test_a_database_rewrite_alone_is_not_a_change(self, project):
        """The server rewrites its SQLite files as it runs; their bytes are
        not what a citation is about."""
        path = os.path.join(os.path.dirname(project), "project.sqlite")
        db = sqlite3.connect(path)
        db.execute("create table memos (body text)")
        db.commit()
        build.create_snapshot(project, now=T0)
        db.execute("insert into memos values ('a note')")
        db.commit()
        db.close()
        with pytest.raises(build.SnapshotUnchanged):
            build.create_snapshot(project, now=T1)

    def test_two_snapshots_in_one_second_keep_their_order(self, project):
        """Found by the server suite: same-second snapshots sorted by the hash
        in their id, so `latest` could be the older one."""
        root = os.path.dirname(project)
        # Five distinct contents, all at T0: the chance their hashes happen to
        # sort in creation order is 1 in 120, so the old sort fails this.
        changes = [{"i0": "x"}, {"i0": "y"}, {"i1": "x"}, {"i1": "y"}, {"i2": "x"}]
        for n, labels in enumerate(changes):
            answer(root, "c", labels)
            build.create_snapshot(project, note=f"n{n}", now=T0)
        assert [s["note"] for s in store.list_snapshots(project)] == ["n4", "n3", "n2", "n1", "n0"]
        assert store.resolve(project, "latest")["sequence"] == 5

    def test_a_changed_answer_is_a_change(self, project):
        first = build.create_snapshot(project, now=T0)
        answer(os.path.dirname(project), "b", dict(zip(["i0", "i1", "i2", "i3"], "xxyy")))
        second = build.create_snapshot(project, now=T1)
        assert second["content_hash"] != first["content_hash"]


class TestStudyFiles:
    """Found by the potato-skill agent: a prestudy phase file was neither in
    the bundle nor in the hash, so editing the survey changed nothing."""

    def _with_phase(self, project):
        root = os.path.dirname(project)
        os.makedirs(os.path.join(root, "surveys"))
        with open(os.path.join(root, "surveys", "pre.jsonl"), "w") as handle:
            handle.write(json.dumps({"id": "age", "text": "Your age?"}) + "\n")
        with open(os.path.join(root, "layouts.yaml"), "w") as handle:
            yaml.safe_dump({"page": "pages/consent.html"}, handle)
        os.makedirs(os.path.join(root, "pages"))
        os.makedirs(os.path.join(root, "media"))
        with open(os.path.join(root, "pages", "consent.html"), "w") as handle:
            handle.write("<p>I agree</p>")
        config = yaml.safe_load(open(project))
        config["phases"] = {"order": ["prestudy", "annotation"],
                            "prestudy": {"type": "prestudy", "file": "surveys/pre.jsonl"}}
        config["custom_layouts"] = "layouts.yaml"
        config["media_directory"] = "media"
        yaml.safe_dump(config, open(project, "w"))
        return root

    def test_referenced_files_are_bundled_and_listed(self, project):
        self._with_phase(project)
        manifest = build.create_snapshot(project, now=T0)
        assert manifest["project_files"] == ["data/items.jsonl", "layouts.yaml",
                                             "pages/consent.html", "surveys/pre.jsonl"]
        assert manifest["referenced_directories"] == [
            os.path.join(os.path.dirname(project), "media")]
        with tarfile.open(os.path.join(folder_of(project, manifest), "bundle.tar.gz")) as tar:
            assert {"project/surveys/pre.jsonl", "project/pages/consent.html"} <= set(tar.getnames())
        assert store.verify_snapshot(project, "latest")["ok"]

    def test_editing_a_survey_is_a_change(self, project):
        root = self._with_phase(project)
        build.create_snapshot(project, now=T0)
        with open(os.path.join(root, "surveys", "pre.jsonl"), "w") as handle:
            handle.write(json.dumps({"id": "age", "text": "How old are you?"}) + "\n")
        second = build.create_snapshot(project, now=T1)  # no SnapshotUnchanged
        assert second["previous"]

    def test_a_file_outside_the_task_dir_is_kept_and_warned_about(self, project):
        root = os.path.dirname(project)
        outside = os.path.join(os.path.dirname(root), "snapshots_ext.jsonl")
        with open(outside, "w") as handle:
            handle.write(json.dumps({"id": "x9", "text": "ext"}) + "\n")
        try:
            config = yaml.safe_load(open(project))
            config["data_files"].append("../snapshots_ext.jsonl")
            yaml.safe_dump(config, open(project, "w"))
            manifest = build.create_snapshot(project, now=T0)
            assert "external/snapshots_ext.jsonl" in manifest["project_files"]
            assert "refuses to serve" in manifest["warnings"][0]
            assert manifest["counts"]["items"] == 5
            assert store.verify_snapshot(project, "latest")["ok"]
        finally:
            os.remove(outside)

    def test_a_create_already_in_progress_says_so(self, project):
        paths = build.project_paths(project)
        digest = build.content_hash(paths, build.annotation_records(paths), build.item_ids(paths))
        os.makedirs(os.path.join(paths["snapshot_root"], f"20261019-120000-{digest[:8]}.partial"))
        with pytest.raises(FileExistsError, match="is writing"):
            build.create_snapshot(project, now=T0)


HASH = "s4lt$0123456789abcdef0123456789abcdef"


def bundle_bytes(project, manifest):
    """Every member of the bundle, decompressed and concatenated."""
    out = b""
    with tarfile.open(os.path.join(folder_of(project, manifest), "bundle.tar.gz")) as tar:
        for member in tar.getmembers():
            handle = tar.extractfile(member)
            if handle:
                out += member.name.encode() + b"\0" + handle.read()
    return out


class TestCredentialsStayOut:
    """Found by the potato-skill agent: the config walk put the account
    roster, password hashes included, into the bundle."""

    def _roster(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write(json.dumps({"username": "a", "password": HASH}) + "\n")

    def test_an_explicit_user_config_path(self, project):
        root = os.path.dirname(project)
        self._roster(os.path.join(root, "secrets", "roster.jsonl"))
        config = yaml.safe_load(open(project))
        config["authentication"] = {"user_config_path": "secrets/roster.jsonl"}
        yaml.safe_dump(config, open(project, "w"))
        manifest = build.create_snapshot(project, now=T0)
        assert HASH.encode() not in bundle_bytes(project, manifest)
        assert "secrets/roster.jsonl" not in manifest["project_files"]
        assert any("roster.jsonl" in note for note in manifest["omitted"])
        self._roster(os.path.join(root, "secrets", "roster.jsonl"))  # rewritten: same content
        with open(os.path.join(root, "secrets", "roster.jsonl"), "a") as handle:
            handle.write(json.dumps({"username": "b", "password": HASH}) + "\n")
        with pytest.raises(build.SnapshotUnchanged):  # not in the content hash either
            build.create_snapshot(project, now=T1)

    def test_the_default_roster_inside_the_output_directory(self, project):
        # output_annotation_dir "annotation_output/": dirname is the folder itself
        self._roster(os.path.join(os.path.dirname(project), "annotation_output", "user_config.json"))
        manifest = build.create_snapshot(project, now=T0)
        assert HASH.encode() not in bundle_bytes(project, manifest)
        assert any("user_config.json" in note for note in manifest["omitted"])
        assert manifest["counts"]["annotators"] == 2  # the annotations are still there

    def test_the_default_roster_beside_a_subfolder_output(self, project):
        root = os.path.dirname(project)
        config = yaml.safe_load(open(project))
        config["output_annotation_dir"] = "out/run1"  # no slash: roster in out/
        config["notes_file"] = "out/user_config.json"  # and named by some key
        yaml.safe_dump(config, open(project, "w"))
        self._roster(os.path.join(root, "out", "user_config.json"))
        manifest = build.create_snapshot(project, now=T0)
        assert HASH.encode() not in bundle_bytes(project, manifest)

    def test_a_file_named_under_a_secret_key(self, project):
        root = os.path.dirname(project)
        os.makedirs(os.path.join(root, "keys"))
        with open(os.path.join(root, "keys", "openai.txt"), "w") as handle:
            handle.write(HASH)
        config = yaml.safe_load(open(project))
        config["ai_support"] = {"endpoint": {"api_key_file": "keys/openai.txt"}}
        yaml.safe_dump(config, open(project, "w"))
        manifest = build.create_snapshot(project, now=T0)
        assert HASH.encode() not in bundle_bytes(project, manifest)
        assert any("api_key_file" in note for note in manifest["omitted"])


class TestDiffTagsVerify:
    def test_diff_reports_items_annotations_and_the_alpha_change(self, project):
        root = os.path.dirname(project)
        build.create_snapshot(project, now=T0)
        answer(root, "b", dict(zip(["i0", "i1", "i2", "i3"], "xxyy")))  # i1 y -> x
        answer(root, "c", {"i0": "x"})
        with open(os.path.join(root, "data", "items.jsonl"), "a") as handle:
            handle.write(json.dumps({"id": "i4", "text": "t4"}) + "\n")
        build.create_snapshot(project, now=T1)
        old = store.load_snapshot(project, "20261019-120000")
        new = store.load_snapshot(project, "latest")
        result = diff.diff_snapshots(old, new)
        assert result["items"] == {"added": ["i4"], "removed": [], "n_added": 1, "n_removed": 0}
        assert result["annotators"] == {"added": ["c"], "removed": []}
        assert (result["annotations"]["n_added"], result["annotations"]["n_changed"],
                result["annotations"]["n_removed"]) == (1, 1, 0)
        assert result["annotations"]["changed"] == [{"annotator": "b", "item": "i1", "schema": "s"}]
        assert result["config_changed"] is False
        alpha = result["agreement"][0]
        assert alpha["alpha_before"] == pytest.approx(8 / 15)
        assert alpha["alpha_after"] == pytest.approx(1.0)
        assert alpha["change"] == pytest.approx(7 / 15)

    def test_refs_resolve_by_tag_prefix_and_latest(self, project):
        root = os.path.dirname(project)
        first = build.create_snapshot(project, tag="pilot", now=T0)
        answer(root, "c", {"i0": "x"})
        second = build.create_snapshot(project, now=T1)
        assert store.resolve(project, "pilot")["id"] == first["id"]
        assert store.resolve(project, "latest")["id"] == second["id"]
        assert store.resolve(project, "20261019-1205")["id"] == second["id"]
        with pytest.raises(LookupError, match="matches 2 snapshots"):
            store.resolve(project, "20261019")
        store.tag_snapshot(project, second["id"], "pilot")  # tags move
        assert store.resolve(project, "pilot")["id"] == second["id"]
        with pytest.raises(ValueError):
            store.tag_snapshot(project, "latest", "latest")

    def test_verify_passes_and_catches_tampering(self, project):
        manifest = build.create_snapshot(project, now=T0)
        assert store.verify_snapshot(project, "latest") == {
            "id": manifest["id"], "ok": True, "problems": [],
            "content_hash": manifest["content_hash"]}
        rows = os.path.join(folder_of(project, manifest), "annotations.jsonl")
        os.chmod(rows, stat.S_IRUSR | stat.S_IWUSR)
        with open(rows) as handle:
            text = handle.read()
        with open(rows, "w") as handle:
            handle.write(text.replace('"x"', '"y"', 1))
        result = store.verify_snapshot(project, "latest")
        assert result["ok"] is False
        assert "annotations.jsonl" in result["problems"][0]

    def test_verify_rehashes_the_content_from_the_bundle(self, project):
        """Rewrite annotations.jsonl and its recorded sha together: the file
        hashes now agree, but the content no longer hashes to content_hash."""
        import hashlib
        manifest = build.create_snapshot(project, now=T0)
        folder = folder_of(project, manifest)
        rows, meta = os.path.join(folder, "annotations.jsonl"), os.path.join(folder, "manifest.json")
        for path in (rows, meta):
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        text = open(rows).read().replace('"x"', '"y"', 1)
        open(rows, "w").write(text)
        data = json.load(open(meta))
        data["annotations_sha256"] = hashlib.sha256(text.encode()).hexdigest()
        json.dump(data, open(meta, "w"))
        result = store.verify_snapshot(project, "latest")
        assert result["problems"] == ["the config, data and annotations do not hash to content_hash"]


class TestCli:
    def test_create_list_show_diff_verify(self, project, capsys):
        assert cli.main(["create", project, "--note", "pilot round", "--tag", "v1"]) == 0
        assert cli.main(["create", project]) == 0
        assert "Nothing has changed" in capsys.readouterr().out
        assert cli.main(["list", project]) == 0
        out = capsys.readouterr().out
        assert "[v1]" in out and "4 items, 2 annotators, 8 answers  pilot round" in out
        assert cli.main(["show", project, "v1"]) == 0
        assert "alpha s: 0.533" in capsys.readouterr().out
        assert cli.main(["verify", project]) == 0
        assert cli.main(["diff", project, "v1", "v1"]) == 0
        assert "Same content." in capsys.readouterr().out
        assert cli.main(["show", project, "nope"]) == 2

    def test_the_command_runs_through_flask_server_as_a_script(self, project):
        """Run as `python potato/flask_server.py`, `potato` imports as a
        namespace package with no __version__; `from potato import
        __version__` made every create from the running server a 500."""
        import subprocess
        import sys
        repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        done = subprocess.run([sys.executable, os.path.join(repo, "potato", "flask_server.py"),
                               "snapshot", "create", project, "--note", "script"],
                              cwd=repo, capture_output=True, text=True, timeout=120)
        assert done.returncode == 0, done.stderr[-2000:]
        assert done.stdout.startswith("Snapshot ")
        assert store.resolve(project, "latest")["potato_version"][0].isdigit()


class TestPublishCitesTheSnapshot:
    def test_publishing_freezes_a_snapshot_and_the_card_names_it(self, project):
        from potato.publish.dataset_card import generate_dataset_card
        from potato.publish.manager import freeze_snapshot
        from potato.publish.preprocessing import run_pipeline

        snapshot, warning = freeze_snapshot(project, "archive")
        assert warning is None and snapshot["note"] == "published (archive)"
        again, _ = freeze_snapshot(project, "zenodo")  # nothing changed: same one
        assert again["id"] == snapshot["id"]
        bundle = run_pipeline(project)
        bundle.snapshot = snapshot
        card = generate_dataset_card(bundle)
        citation = card.split("## Citation Information", 1)[1]
        assert f"Potato snapshot `{snapshot['id']}`" in citation
        assert snapshot["content_hash"] in citation

    def test_a_failed_freeze_is_a_warning_not_a_failed_release(self, project):
        from potato.publish.manager import freeze_snapshot
        snapshot, warning = freeze_snapshot(project + ".missing", "archive")
        assert snapshot == {}
        assert warning.startswith("No snapshot was frozen for this release")

    def test_a_bad_tag_writes_nothing(self, project):
        with pytest.raises(ValueError):
            build.create_snapshot(project, tag="no spaces allowed", now=T0)
        assert store.list_snapshots(project) == []

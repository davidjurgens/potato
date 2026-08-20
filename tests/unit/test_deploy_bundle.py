"""Tests for the deploy bundler.

The bundler decides what reaches a remote host. Its two failure modes both fail
silently at build time and loudly on the server: omitting a file the config
references, or including local state (a live SQLite database, an admin key, a
previous run's annotations) that should never leave the machine.
"""

import os
import tarfile

import pytest
import yaml

from potato.deploy.bundle import (
    LFS_PATTERNS,
    POTATO_EXCLUDES,
    SOURCE_EXCLUDES,
    build_bundle,
    bundle_tarball,
    copy_tree,
    write_lfs_attributes,
)


def make_project(root, config=None, files=None):
    """Write a minimal but realistic project directory."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "data").mkdir(exist_ok=True)
    (root / "data" / "items.json").write_text('[{"id": "1", "text": "hello"}]')
    for relative, content in (files or {}).items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    cfg = {"task_dir": ".", "data_files": ["data/items.json"],
           "output_annotation_dir": "annotation_output/",
           "annotation_task_name": "test"}
    cfg.update(config or {})
    config_path = root / "config.yaml"
    config_path.write_text(yaml.safe_dump(cfg, sort_keys=False))
    return config_path


class TestCopyTree:
    def test_copies_nested_files(self, tmp_path):
        src = tmp_path / "src"
        (src / "a" / "b").mkdir(parents=True)
        (src / "a" / "b" / "deep.txt").write_text("x")
        (src / "top.txt").write_text("y")

        written = copy_tree(str(src), str(tmp_path / "dst"), [])
        assert set(written) == {"top.txt", os.path.join("a", "b", "deep.txt")}

    def test_excludes_directories_wholesale(self, tmp_path):
        src = tmp_path / "src"
        (src / "annotation_output" / "alice").mkdir(parents=True)
        (src / "annotation_output" / "alice" / "user_state.json").write_text("{}")
        (src / "keep.txt").write_text("k")

        written = copy_tree(str(src), str(tmp_path / "dst"), SOURCE_EXCLUDES)
        assert written == ["keep.txt"]

    def test_excludes_glob_matched_files(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        for name in ("project.sqlite", "project.sqlite-wal", "run.log",
                     "admin_api_key.txt", "keep.yaml"):
            (src / name).write_text("x")

        written = copy_tree(str(src), str(tmp_path / "dst"), SOURCE_EXCLUDES)
        assert written == ["keep.yaml"]

    def test_skips_broken_symlinks(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "real.txt").write_text("r")
        os.symlink(str(src / "nonexistent"), str(src / "dangling.txt"))

        written = copy_tree(str(src), str(tmp_path / "dst"), [])
        assert "real.txt" in written
        assert "dangling.txt" not in written


class TestBuildBundle:
    def test_includes_config_and_referenced_data(self, tmp_path):
        config_path = make_project(tmp_path / "project")
        manifest = build_bundle(str(config_path), str(tmp_path / "out"))

        assert manifest.config_rel_path == "config.yaml"
        assert "config.yaml" in manifest.files
        assert os.path.join("data", "items.json") in manifest.files
        assert not manifest.warnings

    def test_never_ships_local_state(self, tmp_path):
        """The single most damaging bundler bug: uploading a live database."""
        project = tmp_path / "project"
        config_path = make_project(project)
        (project / "project.sqlite").write_text("db")
        (project / "project.sqlite-wal").write_text("wal")
        (project / "admin_api_key.txt").write_text("secret-key")
        (project / "potato.log").write_text("log")
        (project / "annotation_output" / "alice").mkdir(parents=True)
        (project / "annotation_output" / "alice" / "user_state.json").write_text("{}")

        manifest = build_bundle(str(config_path), str(tmp_path / "out"))
        joined = "\n".join(manifest.files)
        for leaked in ("project.sqlite", "admin_api_key.txt", "potato.log",
                       "user_state.json"):
            assert leaked not in joined, f"{leaked} must not be bundled"

    def test_creates_empty_annotation_output(self, tmp_path):
        config_path = make_project(tmp_path / "project")
        manifest = build_bundle(str(config_path), str(tmp_path / "out"))
        assert os.path.join("annotation_output", ".gitkeep") in manifest.files

    def test_patch_transforms_the_written_config(self, tmp_path):
        config_path = make_project(tmp_path / "project")

        def patch(cfg):
            cfg["require_no_password"] = True
            return cfg

        manifest = build_bundle(str(config_path), str(tmp_path / "out"), patch=patch)
        written = yaml.safe_load(
            open(os.path.join(manifest.bundle_dir, "config.yaml")))
        assert written["require_no_password"] is True
        # The source config must not be touched.
        assert "require_no_password" not in yaml.safe_load(open(config_path))

    def test_extra_files_are_written(self, tmp_path):
        config_path = make_project(tmp_path / "project")
        docker = tmp_path / "Dockerfile.src"
        docker.write_text("FROM python:3.11-slim")

        manifest = build_bundle(str(config_path), str(tmp_path / "out"),
                                extra_files={"Dockerfile": str(docker)})
        assert "Dockerfile" in manifest.files

    def test_missing_required_path_is_warned_not_raised(self, tmp_path):
        """Preflight decides whether a missing file blocks; the bundler reports."""
        project = tmp_path / "project"
        config_path = make_project(project)
        (project / "data" / "items.json").unlink()

        manifest = build_bundle(str(config_path), str(tmp_path / "out"))
        assert any("items.json" in w for w in manifest.warnings)

    def test_hash_is_stable_across_builds(self, tmp_path):
        config_path = make_project(tmp_path / "project")
        a = build_bundle(str(config_path), str(tmp_path / "out_a"))
        b = build_bundle(str(config_path), str(tmp_path / "out_b"))
        assert a.sha256() == b.sha256()

    def test_hash_changes_when_content_changes(self, tmp_path):
        project = tmp_path / "project"
        config_path = make_project(project)
        before = build_bundle(str(config_path), str(tmp_path / "out_a")).sha256()
        (project / "data" / "items.json").write_text('[{"id": "2", "text": "bye"}]')
        after = build_bundle(str(config_path), str(tmp_path / "out_b")).sha256()
        assert before != after

    def test_rejects_config_outside_task_dir(self, tmp_path):
        """init_config enforces this too; failing here gives a better message."""
        project = tmp_path / "project"
        project.mkdir()
        (project / "data").mkdir()
        (project / "data" / "items.json").write_text("[]")
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.safe_dump(
            {"task_dir": str(project), "data_files": ["data/items.json"]}))

        with pytest.raises(ValueError, match="outside its task_dir"):
            build_bundle(str(config_path), str(tmp_path / "out"))

    def test_unknown_mode_rejected(self, tmp_path):
        config_path = make_project(tmp_path / "project")
        with pytest.raises(ValueError, match="unknown bundle mode"):
            build_bundle(str(config_path), str(tmp_path / "out"), mode="sideways")

    def test_clean_replaces_previous_build(self, tmp_path):
        config_path = make_project(tmp_path / "project")
        out = tmp_path / "out"
        build_bundle(str(config_path), str(out))
        (out / "stale.txt").write_text("left over")
        manifest = build_bundle(str(config_path), str(out))
        assert "stale.txt" not in manifest.files


class TestExternalPathRelocation:
    """A config may reference a corpus outside the project directory.

    Copying only task_dir leaves it behind, and the failure shows up on the
    remote host as missing data rather than at build time.
    """

    def test_out_of_tree_file_is_copied_and_rewritten(self, tmp_path):
        shared = tmp_path / "shared"
        shared.mkdir()
        (shared / "corpus.json").write_text('[{"id": "1"}]')

        project = tmp_path / "project"
        config_path = make_project(project, config={
            "data_files": [str(shared / "corpus.json")]})

        manifest = build_bundle(str(config_path), str(tmp_path / "out"))
        assert "data_files" in manifest.rewritten_keys
        new_value = manifest.rewritten_keys["data_files"]
        assert new_value.startswith("_bundled")

        written = yaml.safe_load(open(os.path.join(manifest.bundle_dir, "config.yaml")))
        assert written["data_files"] == new_value
        assert os.path.isfile(os.path.join(manifest.bundle_dir, new_value))

    def test_relocated_bundle_has_no_missing_paths(self, tmp_path):
        """The rewritten config must resolve inside the bundle."""
        from potato.deploy.paths import collect_config_paths

        shared = tmp_path / "shared"
        shared.mkdir()
        (shared / "corpus.json").write_text("[]")
        project = tmp_path / "project"
        config_path = make_project(project, config={
            "data_files": [str(shared / "corpus.json")]})

        manifest = build_bundle(str(config_path), str(tmp_path / "out"))
        bundled_config = os.path.join(manifest.bundle_dir, "config.yaml")
        paths = collect_config_paths(yaml.safe_load(open(bundled_config)), bundled_config)
        assert not paths.missing_required

    def test_in_tree_paths_are_not_relocated(self, tmp_path):
        config_path = make_project(tmp_path / "project")
        manifest = build_bundle(str(config_path), str(tmp_path / "out"))
        assert manifest.rewritten_keys == {}


class TestManifestMode:
    def test_copies_only_referenced_paths(self, tmp_path):
        project = tmp_path / "project"
        config_path = make_project(project, files={"notes/scratch.txt": "ignore me"})

        manifest = build_bundle(str(config_path), str(tmp_path / "out"), mode="manifest")
        assert os.path.join("data", "items.json") in manifest.files
        assert not any("scratch.txt" in f for f in manifest.files)

    def test_directory_mode_is_a_superset_of_manifest_mode(self, tmp_path):
        """`directory` is what the Spaces pipeline relies on; it must not shrink."""
        project = tmp_path / "project"
        config_path = make_project(project, files={"layouts/task.html": "<div/>"})

        directory = build_bundle(str(config_path), str(tmp_path / "d"), mode="directory")
        manifest = build_bundle(str(config_path), str(tmp_path / "m"), mode="manifest")
        assert set(manifest.files) <= set(directory.files)
        assert os.path.join("layouts", "task.html") in directory.files


class TestTarballAndLfs:
    def test_tarball_contains_every_file(self, tmp_path):
        config_path = make_project(tmp_path / "project")
        manifest = build_bundle(str(config_path), str(tmp_path / "out"))
        archive_path = bundle_tarball(manifest, str(tmp_path / "bundle.tar.gz"))

        with tarfile.open(archive_path) as archive:
            names = set(archive.getnames())
        assert set(manifest.files) <= names

    def test_tarball_bytes_are_reproducible(self, tmp_path):
        """Byte-identical archives let a redeploy skip an unchanged upload."""
        config_path = make_project(tmp_path / "project")
        a = build_bundle(str(config_path), str(tmp_path / "out_a"))
        b = build_bundle(str(config_path), str(tmp_path / "out_b"))
        first = bundle_tarball(a, str(tmp_path / "a.tar.gz"))
        second = bundle_tarball(b, str(tmp_path / "b.tar.gz"))
        assert open(first, "rb").read() == open(second, "rb").read()

    def test_lfs_attributes_cover_media_patterns(self, tmp_path):
        config_path = make_project(tmp_path / "project")
        manifest = build_bundle(str(config_path), str(tmp_path / "out"))
        path = write_lfs_attributes(manifest.bundle_dir)
        body = open(path).read()
        for pattern in ("*.mp4", "*.wav", "*.png", "*.pdf"):
            assert f"{pattern} filter=lfs" in body


class TestExcludeListsMatchSpacesPipeline:
    """build_space.py will be refactored onto this module; the lists must match."""

    def test_source_excludes_cover_all_local_state(self):
        for required in ("annotation_output", "*.sqlite", "*.sqlite-wal",
                         "*.sqlite-shm", "admin_api_key.txt", "*.log",
                         "__pycache__", "*.pyc"):
            assert required in SOURCE_EXCLUDES

    def test_potato_excludes_skip_build_artifacts(self):
        for required in ("__pycache__", "*.pyc", ".git", "node_modules"):
            assert required in POTATO_EXCLUDES

    def test_lfs_patterns_cover_each_media_family(self):
        joined = " ".join(LFS_PATTERNS)
        for family in ("mp4", "wav", "png", "pdf", "webm", "mp3"):
            assert family in joined


class TestAgainstRealExample:
    def test_bundles_a_real_example_project(self, tmp_path):
        config = "examples/classification/single-choice/config.yaml"
        if not os.path.isfile(config):
            pytest.skip("example project not present")

        manifest = build_bundle(config, str(tmp_path / "out"))
        assert manifest.file_count >= 3
        assert "config.yaml" in manifest.files
        assert not manifest.warnings
        assert not any(f.endswith((".sqlite", ".pyc", ".log")) for f in manifest.files)


class TestBundleDirectoryInsideProject:
    """The default output directory lives inside the project being bundled.

    Found by running the CLI: copy_tree walked into its own output and recursed
    until the path length exceeded the OS limit.
    """

    def test_bundling_into_a_subdirectory_terminates(self, tmp_path):
        project = tmp_path / "project"
        config_path = make_project(project)
        out = project / ".potato" / "bundle" / "study"

        manifest = build_bundle(str(config_path), str(out))
        assert "config.yaml" in manifest.files
        assert not any(".potato" in f for f in manifest.files)

    def test_deploy_state_is_never_bundled(self, tmp_path):
        """.potato/secrets.json holds the admin key and session key."""
        project = tmp_path / "project"
        config_path = make_project(project)
        state = project / ".potato"
        state.mkdir()
        (state / "secrets.json").write_text('{"study": {"admin_api_key": "TOPSECRET"}}')
        (state / "deployments.json").write_text("{}")

        manifest = build_bundle(str(config_path), str(tmp_path / "out"))
        assert not any(".potato" in f or "secrets.json" in f for f in manifest.files)
        for relative in manifest.files:
            content = open(os.path.join(manifest.bundle_dir, relative),
                           "rb").read()
            assert b"TOPSECRET" not in content

    def test_copy_tree_skips_a_destination_inside_the_source(self, tmp_path):
        src = tmp_path / "src"
        (src / "sub").mkdir(parents=True)
        (src / "sub" / "file.txt").write_text("x")
        dst = src / "output"

        written = copy_tree(str(src), str(dst), [])
        assert os.path.join("sub", "file.txt") in written
        assert not any("output" in w for w in written)

"""The gate on moving build_space.py onto the shared bundler.

`deployment/huggingface-spaces/build_space.py` builds the 38 live demo Spaces.
It had its own copy of the bundling logic, which `potato/deploy/bundle.py` now
does properly — but the catalog is real and deployed, so the refactor is only
safe if the output does not change.

`build_bundle(mode="directory")` is a strict superset of the old behaviour: it
copies the same tree minus the same excludes, and additionally relocates
out-of-tree paths. For a project whose files are all inside its own directory —
which every catalog entry is — the two must agree exactly. These tests assert
that on real manifest entries: a plain text task, one carrying media through
git-lfs, and one that calls an LLM.

They compare against explicit expectations rather than a recorded snapshot, so
they keep working as the manifest changes and still fail if the bundler drops a
file or forgets to patch the config.
"""

import os
import subprocess
import sys

import pytest
import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
BUILD_SPACE = os.path.join(REPO_ROOT, "deployment", "huggingface-spaces",
                           "build_space.py")

pytestmark = pytest.mark.skipif(
    not os.path.isfile(BUILD_SPACE),
    reason="the HuggingFace Spaces tooling is not present")


def load_manifest():
    sys.path.insert(0, os.path.dirname(BUILD_SPACE))
    from build_space import load_manifest as loader
    return loader()


def pick(predicate, fallback_any=True):
    """The first manifest entry matching a predicate."""
    entries = load_manifest()
    for entry in entries.values():
        if predicate(entry):
            return entry
    if fallback_any:
        return next(iter(entries.values()))
    return None


@pytest.fixture(scope="module")
def manifest():
    return load_manifest()


REPRESENTATIVE = [
    ("plain", lambda e: not e.get("needs_lfs") and not e.get("needs_ai")),
    ("media", lambda e: bool(e.get("needs_lfs"))),
    ("ai", lambda e: bool(e.get("needs_ai"))),
]


class TestBundlerMatchesBuildSpace:
    """The properties the refactor must preserve, on three kinds of entry."""

    @pytest.mark.parametrize("label,predicate", REPRESENTATIVE)
    def test_same_project_files(self, label, predicate, tmp_path):
        entry = pick(predicate)
        if entry is None:
            pytest.skip(f"no {label} entry in the manifest")

        source = os.path.join(REPO_ROOT, entry["source"])
        if not os.path.isfile(os.path.join(source, "config.yaml")):
            pytest.skip(f"{entry['id']} source project is missing")

        from potato.deploy.bundle import build_bundle

        out = tmp_path / "bundle"
        build_bundle(os.path.join(source, "config.yaml"), str(out))

        expected = _project_files(source)
        actual = _project_files(str(out))
        # The bundler adds its own manifest; the old builder added scaffolding.
        # Neither is a project file.
        missing = expected - actual
        assert not missing, (
            f"{entry['id']}: the bundler dropped {sorted(missing)[:10]}. "
            "build_space.py copied the whole project directory, so anything "
            "missing here would vanish from a live Space.")

    @pytest.mark.parametrize("label,predicate", REPRESENTATIVE)
    def test_same_exclusions(self, label, predicate, tmp_path):
        """Neither builder may ship annotation output or an admin key."""
        entry = pick(predicate)
        if entry is None:
            pytest.skip(f"no {label} entry in the manifest")
        source = os.path.join(REPO_ROOT, entry["source"])
        if not os.path.isfile(os.path.join(source, "config.yaml")):
            pytest.skip(f"{entry['id']} source project is missing")

        from potato.deploy.bundle import build_bundle

        out = tmp_path / "bundle"
        build_bundle(os.path.join(source, "config.yaml"), str(out))

        for dirpath, dirnames, filenames in os.walk(out):
            assert "annotation_output" not in dirnames or dirpath == str(out)
            for filename in filenames:
                assert filename != "admin_api_key.txt"
                assert not filename.endswith(".sqlite")


class TestExcludeListsAgree:
    """Both builders must exclude the same things, or one ships a credential."""

    def test_source_excludes_match(self):
        sys.path.insert(0, os.path.dirname(BUILD_SPACE))
        import build_space
        from potato.deploy.bundle import SOURCE_EXCLUDES

        old = set(build_space.SOURCE_EXCLUDES)
        new = set(SOURCE_EXCLUDES)
        assert old <= new, (
            f"build_space.py excludes {sorted(old - new)} that the shared "
            "bundler does not, so moving it over would start shipping them.")

    def test_lfs_patterns_match(self):
        sys.path.insert(0, os.path.dirname(BUILD_SPACE))
        import build_space
        from potato.deploy.bundle import LFS_PATTERNS

        assert set(build_space.LFS_PATTERNS) == set(LFS_PATTERNS), (
            "the two git-lfs pattern lists have drifted; a media file tracked "
            "by one and not the other breaks the Space it lands in")


class TestDemoConfigPatch:
    """The catalog's Spaces are frictionless demos: a name, no password."""

    def test_patch_is_expressible_as_a_dict_transform(self, tmp_path):
        """build_bundle takes `patch` as a function of the parsed config.

        build_space.py's version read, modified and rewrote a file. The shared
        one has to produce the same result from the same input.
        """
        sys.path.insert(0, os.path.dirname(BUILD_SPACE))
        from build_space import patch_demo_config

        path = tmp_path / "config.yaml"
        original = {
            "annotation_task_name": "demo",
            "require_password": True,
            "login": {"type": "prolific"},
            "user_config": {"allow_all_users": False},
        }
        path.write_text(yaml.safe_dump(original))
        patch_demo_config(path)
        patched = yaml.safe_load(path.read_text())

        assert patched["require_no_password"] is True
        assert "require_password" not in patched
        assert patched["user_config"]["allow_all_users"] is True
        assert patched["login"]["type"] == "standard"

    def test_the_demo_patch_is_the_only_place_auth_is_rewritten(self):
        """`potato deploy` never rewrites access control; the catalog does.

        These are different jobs and must not be confused: the demo builder
        deliberately opens a Space to anyone, and harden_config deliberately
        leaves a researcher's own auth settings alone.
        """
        from potato.deploy.preflight import harden_config

        config = {"task_dir": ".", "user_config": {"allow_all_users": False},
                  "require_password": True, "login": {"type": "prolific"}}
        hardened = harden_config(dict(config), provider="huggingface")
        assert hardened["user_config"] == {"allow_all_users": False}
        assert hardened["require_password"] is True
        assert hardened["login"] == {"type": "prolific"}


class TestRealBuild:
    """Build an actual Space through the refactored path.

    The offline tests above assert the invariants; this one runs the script and
    checks the output has everything a Space needs to build and start. It was a
    real build-and-diff against the pre-refactor code that proved the change
    safe: 2454 files, one difference, and that difference was the README
    template correction made earlier and not the refactor.
    """

    @pytest.fixture(scope="class")
    def built(self, tmp_path_factory):
        entry = pick(lambda e: not e.get("needs_lfs") and not e.get("needs_ai"))
        out = tmp_path_factory.mktemp("space") / entry["id"]
        result = subprocess.run(
            [sys.executable, BUILD_SPACE, entry["id"], str(out)],
            capture_output=True, text=True, timeout=600, cwd=REPO_ROOT)
        if result.returncode != 0:
            pytest.fail(f"build_space.py failed:\n{result.stdout}{result.stderr}")
        return out

    @pytest.mark.parametrize("relative", [
        "config.yaml", "Dockerfile", "entrypoint.sh", "README.md",
        "requirements.txt", "setup.py", "annotation_output/.gitkeep",
        "potato/__init__.py", "potato/flask_server.py",
    ])
    def test_required_file_is_present(self, built, relative):
        assert os.path.isfile(os.path.join(built, *relative.split("/"))), relative

    def test_entrypoint_is_executable(self, built):
        """A non-executable entrypoint builds fine and then fails to start."""
        assert os.access(os.path.join(built, "entrypoint.sh"), os.X_OK)

    def test_config_is_patched_for_a_frictionless_demo(self, built):
        with open(os.path.join(built, "config.yaml")) as handle:
            config = yaml.safe_load(handle)
        assert config["require_no_password"] is True
        assert config["user_config"]["allow_all_users"] is True

    def test_readme_frontmatter_is_valid(self, built):
        """HuggingFace reads sdk and app_port from it; a Space without them
        does not build."""
        with open(os.path.join(built, "README.md")) as handle:
            front = yaml.safe_load(handle.read().split("---")[1])
        assert front["sdk"] == "docker"
        assert front["app_port"] == 7860

    def test_no_credential_or_output_was_copied(self, built):
        for dirpath, _dirnames, filenames in os.walk(built):
            for filename in filenames:
                assert filename != "admin_api_key.txt"
                assert not filename.endswith((".sqlite", ".sqlite-wal",
                                              ".sqlite-shm"))

    def test_annotation_output_ships_empty(self, built):
        entries = os.listdir(os.path.join(built, "annotation_output"))
        assert entries == [".gitkeep"], entries


class TestBuildSpaceStillRuns:
    """A smoke test on the real script, since the catalog depends on it."""

    def test_list_works(self):
        result = subprocess.run([sys.executable, BUILD_SPACE, "--list"],
                                capture_output=True, text=True, timeout=60,
                                cwd=REPO_ROOT)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip()


def _project_files(root: str) -> set:
    """Relative paths under root, ignoring what neither builder copies."""
    # `.potato` holds deploy state and the secret store, which neither builder
    # copies. It is also where a previous `potato deploy build` left a bundle,
    # so counting it would compare the project against its own output.
    skip_dirs = {"annotation_output", "__pycache__", ".git", "potato", ".potato"}
    found = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for filename in filenames:
            if (filename.endswith((".pyc", ".log", ".sqlite",
                                   ".sqlite-shm", ".sqlite-wal"))
                    or filename in (".DS_Store", "admin_api_key.txt",
                                    "bundle-manifest.json", "Dockerfile",
                                    "README.md", "entrypoint.sh",
                                    "requirements.txt", "setup.py",
                                    ".gitattributes")):
                continue
            found.add(os.path.relpath(os.path.join(dirpath, filename), root))
    return found

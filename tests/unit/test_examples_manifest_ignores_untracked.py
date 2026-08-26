"""
The examples catalog must describe what is committed, not what is on disk.

`build_manifest` walks the filesystem, but its output is a checked-in artifact
that CI compares against a fresh build. Anything present only on the machine
that generated it therefore ships in the artifact and then fails the drift
check for everyone else.

This is not hypothetical. A scratch directory ignored through
`.git/info/exclude` -- which is local to one clone and invisible to everyone
else -- was picked up into the 2.8.1 manifest and broke the Docs & Generated
Specs workflow on every run afterwards.
"""

import os
import subprocess

import pytest

from potato.server_utils.examples_manifest import build_manifest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _git_available():
    try:
        subprocess.run(["git", "-C", REPO_ROOT, "rev-parse", "--git-dir"],
                       capture_output=True, timeout=10, check=True)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


@pytest.mark.skipif(not _git_available(), reason="not a git checkout")
class TestManifestDescribesTrackedExamplesOnly:
    def test_no_entry_is_git_ignored(self):
        manifest = build_manifest(REPO_ROOT)
        dirs = [e["dir"] for e in manifest["examples"]]
        assert dirs, "manifest is empty"

        result = subprocess.run(
            ["git", "-C", REPO_ROOT, "check-ignore", "--stdin"],
            input="\n".join(os.path.join(d, "config.yaml") for d in dirs),
            capture_output=True, text=True, timeout=60,
        )
        ignored = [line.strip() for line in (result.stdout or "").splitlines()
                   if line.strip()]
        assert not ignored, (
            "these examples are in the manifest but git ignores them, so the "
            "committed catalog depends on local state: %s" % ignored
        )

    def test_every_entry_has_a_tracked_config(self):
        manifest = build_manifest(REPO_ROOT)
        tracked = subprocess.run(
            ["git", "-C", REPO_ROOT, "ls-files", "examples/"],
            capture_output=True, text=True, timeout=60,
        ).stdout.splitlines()
        tracked_configs = {p for p in tracked if p.endswith("config.yaml")}

        missing = [
            e["dir"] for e in manifest["examples"]
            if os.path.join(e["dir"], "config.yaml") not in tracked_configs
        ]
        assert not missing, (
            "manifest entries whose config.yaml is not committed: %s" % missing
        )

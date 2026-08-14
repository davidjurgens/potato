"""
Versioned static assets must have their `?v=` bumped when their content changes.

Browsers cache `/static/foo.js?v=4` indefinitely. Editing `foo.js` without
touching the version means returning annotators keep running the OLD file —
they do not get the fix, and nothing in the test suite notices, because the
tests always load fresh.

This bit during Wave 0.1: `image-annotation.js` was edited while still served as
`?v=4`, so a browser with the previous copy cached kept the broken build. It is
also how `image-annotation.css` shipped an accessibility fix that a cached
client never received.

The guard is a manifest of content hashes. Change a versioned file and this test
fails until you bump its `?v=` and record the new hash.

To update after an intentional change:

    python tests/unit/test_static_asset_versions.py --update
"""

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "potato" / "templates" / "base_template_v2.html"
STATIC_DIR = REPO_ROOT / "potato" / "static"
MANIFEST = Path(__file__).with_name("static_asset_versions.json")

#: Matches url_for('static', filename='x.js')?v=N in the template.
VERSIONED = re.compile(
    r"""url_for\(\s*['"]static['"]\s*,\s*filename\s*=\s*['"](?P<file>[^'"]+)['"]\s*\)\s*\}\}\?v=(?P<version>\d+)""",
)


def versioned_assets():
    """{filename: version} for every ?v=-tagged static asset in the template."""
    text = TEMPLATE.read_text(encoding="utf-8")
    return {m.group("file"): m.group("version") for m in VERSIONED.finditer(text)}


def content_hash(filename: str) -> str:
    path = STATIC_DIR / filename
    if not path.exists():
        return "MISSING"
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def current_state():
    return {
        name: {"version": version, "sha256": content_hash(name)}
        for name, version in sorted(versioned_assets().items())
    }


def load_manifest():
    if not MANIFEST.exists():
        return {}
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


class TestVersionedAssets:
    def test_every_versioned_asset_exists(self):
        missing = [name for name in versioned_assets()
                   if not (STATIC_DIR / name).exists()]
        assert not missing, (
            f"base_template_v2.html references static files that do not exist: {missing}")

    def test_the_manifest_covers_every_versioned_asset(self):
        recorded = load_manifest()
        untracked = sorted(set(versioned_assets()) - set(recorded))
        assert not untracked, (
            f"New versioned asset(s) not in the manifest: {untracked}. "
            f"Run: python {Path(__file__).relative_to(REPO_ROOT)} --update")

    def test_changed_content_has_a_bumped_version(self):
        """
        The whole point. A file whose bytes changed but whose ?v= did not is a
        fix that returning users will never receive.
        """
        recorded = load_manifest()
        state = current_state()

        stale = []
        for name, now in state.items():
            was = recorded.get(name)
            if not was:
                continue  # covered by the manifest-coverage test
            if now["sha256"] != was["sha256"] and now["version"] == was["version"]:
                stale.append(
                    f"  {name}: content changed but ?v={now['version']} is unchanged")

        assert not stale, (
            "Static asset(s) edited without a cache-buster bump — cached browsers "
            "will keep the old file:\n" + "\n".join(stale) +
            f"\n\nBump ?v= in base_template_v2.html, then run: "
            f"python {Path(__file__).relative_to(REPO_ROOT)} --update")

    def test_the_manifest_is_current(self):
        """A manifest that lags reality cannot detect the next change."""
        recorded = load_manifest()
        state = current_state()
        drifted = sorted(n for n in state if recorded.get(n) != state[n])
        assert not drifted, (
            f"Manifest is out of date for: {drifted}. "
            f"Run: python {Path(__file__).relative_to(REPO_ROOT)} --update")


def _update():
    state = current_state()
    MANIFEST.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    print(f"Wrote {MANIFEST.relative_to(REPO_ROOT)} ({len(state)} assets)")
    return 0


if __name__ == "__main__":
    if "--update" in sys.argv:
        sys.exit(_update())
    print(__doc__)
    sys.exit(pytest.main([__file__, "-q"]))

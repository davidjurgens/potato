"""The wheel has to contain the templates the server renders.

`setup.py` used to declare `package_data={"potato": ["templates/*.html"]}`, a
single-level glob. Every template in a subdirectory -- `admin/` (13 files),
`solo/` (10), `judge_calibration/` (3), `corpus_map/` (1) -- was therefore
absent from the built wheel, so solo mode, the admin pages and judge
calibration were broken for anyone who installed Potato rather than running it
from a checkout. Nothing in the test suite noticed, because the suite runs
against the source tree.

`MANIFEST.in` now grafts the whole directory. That introduces the opposite
hazard: `potato/templates/generated/` is where the server writes per-task and
per-cohort templates at startup. It is gitignored, but MANIFEST.in does not
read .gitignore, so a release cut from a working tree would ship whatever
templates that maintainer's local tasks had produced -- 1,425 files, when this
was measured.

These tests build the real manifest rather than reading MANIFEST.in as text, so
they check what setuptools actually does with the directives.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = REPO_ROOT / "potato" / "templates"
GENERATED = TEMPLATES / "generated"

# Stands in for a maintainer's locally generated templates. The prune has to
# hold in a clean checkout too, where `generated/` is empty or missing, so the
# test creates the condition rather than waiting to encounter it.
CANARY = GENERATED / "Packaging-Canary-base_template_v2.html-cohortz"


@pytest.fixture(scope="module")
def manifest(tmp_path_factory):
    """The file list setuptools derives from MANIFEST.in, one line per path."""
    if not (REPO_ROOT / "setup.py").is_file():
        pytest.skip("not running from a source checkout")

    created_dir = not GENERATED.exists()
    GENERATED.mkdir(parents=True, exist_ok=True)
    CANARY.write_text("<!-- packaging canary -->\n")

    egg_base = tmp_path_factory.mktemp("egg")
    try:
        result = subprocess.run(
            [sys.executable, "setup.py", "-q", "egg_info", "--egg-base", str(egg_base)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            pytest.fail(f"egg_info failed:\n{result.stdout}\n{result.stderr}")

        sources = list(egg_base.glob("*.egg-info/SOURCES.txt"))
        assert sources, f"egg_info wrote no SOURCES.txt into {egg_base}"
        yield set(sources[0].read_text().splitlines())
    finally:
        CANARY.unlink(missing_ok=True)
        if created_dir:
            shutil.rmtree(GENERATED, ignore_errors=True)


def _tracked(pattern):
    """Paths git tracks, so the test follows the tree instead of a fixed list."""
    out = subprocess.run(
        ["git", "ls-files", pattern],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return [p for p in out if p]


class TestTemplatesAreShipped:
    def test_every_tracked_template_is_packaged(self, manifest):
        tracked = _tracked("potato/templates/**")
        assert tracked, "no templates tracked -- the glob is wrong, not the manifest"
        missing = sorted(set(tracked) - manifest)
        assert not missing, (
            f"{len(missing)} tracked template(s) would not ship in the wheel, "
            f"starting with: {missing[:5]}"
        )

    def test_the_subdirectories_are_the_reason_this_exists(self, manifest):
        """A single-level glob passes the test above only if no subdirectory has
        templates. Fail loudly if that stops being the case, rather than letting
        the guard quietly become vacuous."""
        nested = [p for p in _tracked("potato/templates/**") if p.count("/") > 2]
        assert nested, "no templates in subdirectories -- this guard no longer guards"
        assert set(nested) <= manifest


class TestRuntimeOutputIsNotShipped:
    def test_generated_templates_are_pruned(self, manifest):
        leaked = sorted(p for p in manifest if p.startswith("potato/templates/generated/"))
        assert not leaked, (
            "runtime-generated templates would ship in the release: "
            f"{leaked[:5]} ({len(leaked)} total)"
        )

    def test_the_canary_proves_the_prune_ran(self, manifest):
        """Without this, an empty `generated/` would make the test above pass
        whether or not the prune directive is present."""
        rel = str(CANARY.relative_to(REPO_ROOT))
        assert rel not in manifest


class TestOtherPackageDataSurvived:
    """The `templates/*.html` removal happened inside `package_data`, alongside
    entries the wheel still needs."""

    @pytest.mark.parametrize("path", [
        "potato/i18n/de.yaml",
        "potato/schemas/potato-config.schema.json",
        "potato/static/styles.css",
    ])
    def test_still_packaged(self, manifest, path):
        assert (REPO_ROOT / path).is_file(), f"{path} moved; update this test"
        assert path in manifest

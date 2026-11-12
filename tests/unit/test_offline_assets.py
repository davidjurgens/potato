"""
Offline / air-gapped asset loading.

Self-hosting is the reason a large share of users choose Potato at all, and
several of them cannot reach the public internet from the annotation machine.
Any front-end library we ship must therefore load from ``static/vendor`` first,
with a CDN only as a fallback for deployments that stripped that directory.

Two regressions this locks down:

* ``static/js/pdf-viewer.js`` loaded PDF.js straight from cdnjs even though
  ``static/vendor/pdfjs`` was already in the repo.
* ``templates/admin.html`` loaded Plotly from ``cdn.plot.ly``, so the embedding
  visualisation died with no network.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "potato"
STATIC = ROOT / "static"
TEMPLATES = ROOT / "templates"

# (human name, substring identifying the CDN copy, path prefix that must load
#  first, glob under potato/ proving the vendored copy is really on disk)
VENDORED = [
    (
        "PDF.js",
        "cdnjs.cloudflare.com/ajax/libs/pdf.js",
        "/static/vendor/pdfjs",
        "static/vendor/pdfjs/pdf.min.js",
    ),
    (
        "Plotly",
        "cdn.plot.ly/plotly",
        "/static/vendor/plotly-",
        "static/vendor/plotly-*.min.js",
    ),
]


def _source_files():
    """Hand-written front-end sources. Skips vendored libs and generated pages."""
    for path in list(STATIC.rglob("*.js")) + list(TEMPLATES.glob("*.html")):
        if "vendor" in path.parts or "generated" in path.parts:
            continue
        yield path


@pytest.mark.parametrize("name,cdn,local,disk", VENDORED)
def test_cdn_reference_is_always_preceded_by_the_local_path(name, cdn, local, disk):
    """A file may name the CDN only as a fallback, never as the first choice."""
    offenders = []
    for path in _source_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        cdn_at = text.find(cdn)
        if cdn_at == -1:
            continue
        local_at = text.find(local)
        if local_at == -1 or local_at > cdn_at:
            offenders.append(str(path.relative_to(ROOT)))

    assert not offenders, (
        f"{name} is vendored, but these files reach for the CDN without trying "
        f"{local} first: {offenders}. On an air-gapped install the feature dies."
    )


@pytest.mark.parametrize("name,cdn,local,disk", VENDORED)
def test_the_vendored_copy_actually_exists(name, cdn, local, disk):
    """A local-first path that points at nothing silently degrades to the CDN."""
    assert list(ROOT.glob(disk)), (
        f"{name}: nothing matches potato/{disk}, so every local-first load "
        f"falls through to {cdn} and offline installs stay broken."
    )

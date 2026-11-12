"""
protein_structure with engine: molstar, after a real `potato vendor fetch
molstar` into a vendor directory under tests/output: Mol* draws the example,
its selection follows the residue table, and pLDDT colouring is applied.
"""

import os

import pytest

pytest.importorskip("playwright.sync_api")

from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.test_utils import create_test_directory  # noqa: E402
from tests.playwright.test_protein_structure_ui import (  # noqa: E402
    SCRATCH, SWIFTSHADER, _close, _open)

pytestmark = pytest.mark.playwright


def test_molstar_engine_from_a_fetched_bundle(monkeypatch):
    """engine: molstar after a real `potato vendor fetch molstar`."""
    import subprocess
    import sys
    import yaml
    from tests.playwright.test_protein_structure_ui import EXAMPLE, REPO
    vendor = create_test_directory("molstar_vendor_ui")
    fetch = subprocess.run([sys.executable, "-m", "potato.vendoring.cli", "fetch", "molstar"],
                           capture_output=True, text=True, cwd=REPO, timeout=300,
                           env=dict(os.environ, POTATO_VENDOR_DIR=vendor))
    if fetch.returncode != 0:
        pytest.skip(f"could not fetch Mol*: {fetch.stderr[-200:]}")
    monkeypatch.setenv("POTATO_VENDOR_DIR", vendor)
    import shutil
    work = os.path.join(create_test_directory("molstar_ui"), "pbs")
    shutil.copytree(EXAMPLE, work, ignore=shutil.ignore_patterns("annotation_output", "*.sqlite*"))
    path = os.path.join(work, "config.yaml")
    with open(path) as f:
        config = yaml.safe_load(f)
    config["instance_display"]["fields"][1]["display_options"]["engine"] = "molstar"
    with open(path, "w") as f:
        yaml.safe_dump(config, f)
    srv = FlaskTestServer(config_file=path)
    if not srv.start():
        pytest.fail("could not start the Mol* config")
    try:
        p, browser, page = _open(srv, "ms_ui", SWIFTSHADER)
        try:
            if page.get_attribute(".potato-viewer", "data-viewer-state") == "no-webgl":
                pytest.skip("this Chromium build has no SwiftShader WebGL")
            assert page.get_attribute(".potato-viewer", "data-viewer-state") == "ready"
            assert any("/vendor-fetched/molstar-5.12.0/molstar.js" in u for u in page.requested)
            page.click(".pv-res[data-chain='A'][data-resi='8']")
            # Mol*'s own selection follows the scheme's.
            page.wait_for_function(
                "window.potatoViewers.structure.engine.plugin.managers.structure.selection.entries.size === 1")
            page.wait_for_function("""() => {
                const s = window.potatoViewers.structure.engine.plugin.managers.structure.hierarchy.current.structures[0];
                return s && s.components.every(c => c.representations.every(
                    r => r.cell.transform.params.colorTheme.name === 'plddt-confidence'));
            }""", timeout=10000)
            page.screenshot(path=os.path.join(SCRATCH, "protein_molstar.png"), full_page=True)
            assert not page.errors, page.errors
        finally:
            _close(p, browser)
    finally:
        srv.stop()

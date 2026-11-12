"""
protein_structure with WebGL (SwiftShader): 3Dmol.js draws a ten-residue
alanine helix written for this test, a click on a residue in the 3D view
selects it, and the residue table built from the model (for a URL the server
does not read) matches.
"""

import json
import os

import pytest

pytest.importorskip("playwright.sync_api")

from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.test_utils import create_test_directory  # noqa: E402
from tests.playwright.test_protein_structure_ui import (  # noqa: E402
    SCRATCH, SWIFTSHADER, _close, _generator, _open, _pressed)

pytestmark = pytest.mark.playwright


@pytest.fixture(scope="module")
def helix_server():
    gen = _generator()
    work = create_test_directory("protein_structure_helix")
    os.makedirs(os.path.join(work, "media"), exist_ok=True)
    os.makedirs(os.path.join(work, "data"), exist_ok=True)
    with open(os.path.join(work, "media", "ala10.pdb"), "w") as f:
        f.write(gen.to_pdb(gen.build_chain("A" * 10, "A"), "ALA10 HELIX"))
    with open(os.path.join(work, "data", "items.json"), "w") as f:
        json.dump([{"id": "helix", "text": "ten alanines", "structure": "ala10.pdb"},
                   {"id": "helix_url", "text": "same file by URL", "structure": "ala10.pdb"}], f)
    import yaml
    config = {
        "annotation_task_name": "Helix", "task_dir": work, "media_directory": "media",
        "output_annotation_dir": "annotation_output", "data_files": ["data/items.json"],
        "item_properties": {"id_key": "id", "text_key": "text"},
        "user_config": {"allow_all_users": True},
        "instance_display": {"fields": [{"key": "structure", "type": "protein_structure",
                                         "display_options": {"height": 360, "color_by": "spectrum"}}]},
        "annotation_schemes": [{"annotation_type": "viewer_selection", "name": "picked",
                                "description": "Pick residues", "viewer_field": "structure"}],
    }
    with open(os.path.join(work, "config.yaml"), "w") as f:
        yaml.safe_dump(config, f)
    srv = FlaskTestServer(config_file=os.path.join(work, "config.yaml"))
    if not srv.start():
        pytest.fail("could not start the helix config")
    yield srv
    srv.stop()


def _residue_on_screen(page, resi):
    return page.evaluate("""(resi) => {
        const gl = window.potatoViewers.structure.engine;
        const a = gl.getModel().selectedAtoms({resi: resi, atom: 'CA'})[0];
        return gl.modelToScreen({x: a.x, y: a.y, z: a.z});
    }""", resi)


def _coloured_pixels(page):
    from io import BytesIO
    import numpy as np
    from PIL import Image
    shot = page.locator(".potato-viewer .pv-stage").screenshot()
    img = np.asarray(Image.open(BytesIO(shot)).convert("RGB")).astype(int)
    background = img[2, 2]
    return int((np.abs(img - background).sum(axis=2) > 60).sum())


def test_3dmol_draws_and_a_click_in_3d_selects(helix_server):
    p, browser, page = _open(helix_server, "pv_gl", SWIFTSHADER)
    try:
        if page.get_attribute(".potato-viewer", "data-viewer-state") == "no-webgl":
            pytest.skip("this Chromium build has no SwiftShader WebGL")
        assert page.get_attribute(".potato-viewer", "data-viewer-state") == "ready"
        assert page.evaluate("window.potatoViewers.structure.engine.getModel().selectedAtoms({}).length") == 50
        assert _coloured_pixels(page) > 500, "the canvas is blank"
        before = _coloured_pixels(page)

        pt = _residue_on_screen(page, 5)
        page.mouse.click(pt["x"], pt["y"])
        page.wait_for_function("window.potatoViewers.structure.getSelection().items.length === 1")
        sel = page.evaluate("window.potatoViewers.structure.getSelection()")
        assert sel["items"][0]["resn"] == "ALA"
        clicked = sel["items"][0]["resi"]
        assert abs(clicked - 5) <= 1, sel          # the residue under the cursor
        assert _pressed(page) == [f"A:{clicked}"]
        assert "Selected ALA" in page.text_content(".pv-status")
        assert _coloured_pixels(page) > before, "the selected residue was not drawn as sticks"

        # The API: describe() and setSelection() repaint the table too.
        assert page.evaluate("window.potatoViewers.structure.describe({chain: 'A', resi: 2, resn: 'ALA'})") \
            == "ALA 2, chain A"
        page.evaluate("window.potatoViewers.structure.setSelection({items: [{chain: 'A', resi: 9, resn: 'ALA'}]})")
        assert _pressed(page) == ["A:9"]
        page.screenshot(path=os.path.join(SCRATCH, "protein_swiftshader.png"), full_page=True)
        assert not page.errors, page.errors
    finally:
        _close(p, browser)


def test_table_from_the_model_for_a_remote_url(helix_server):
    """A URL the server does not read: the adapter builds the table itself."""
    p, browser, page = _open(helix_server, "pv_url", SWIFTSHADER)
    try:
        if page.get_attribute(".potato-viewer", "data-viewer-state") == "no-webgl":
            pytest.skip("this Chromium build has no SwiftShader WebGL")
        html = page.evaluate("""async (base) => {
            const el = document.querySelector('.potato-viewer');
            const cfg = JSON.parse(el.getAttribute('data-viewer-config'));
            cfg.url = base + '/media/ala10.pdb'; cfg.tableFromModel = true; cfg.field = 'remote';
            const copy = el.cloneNode(false);
            copy.id = 'viewer-remote';
            copy.setAttribute('data-viewer-state', 'loading');   // cloned from a ready viewer
            copy.setAttribute('data-viewer-config', JSON.stringify(cfg));
            copy.innerHTML = '<div class="pv-main"><div class="pv-stage-wrap" style="height:200px">' +
                '<div class="pv-stage"></div><p class="pv-message"></p></div></div><p class="pv-status"></p>' +
                '<div class="pv-residues"><p class="pv-residues-note">Reading…</p><div class="pv-chains"></div></div>';
            document.body.appendChild(copy);
            window.PotatoViewerFramework.mount(copy);
            for (let i = 0; i < 100 && copy.getAttribute('data-viewer-state') !== 'ready'; i++) {
                await new Promise(r => setTimeout(r, 100));
            }
            return [copy.getAttribute('data-viewer-state'),
                    [...copy.querySelectorAll('.pv-res')].map(b => b.dataset.resi + b.dataset.resn)];
        }""", helix_server.base_url)
        state, cells = html
        assert state == "ready"
        assert cells == [f"{i}ALA" for i in range(1, 11)]
        # Its cells select like the server-rendered ones.
        page.click("#viewer-remote .pv-res[data-resi='4']")
        assert page.evaluate("window.potatoViewers.remote.getSelection().items") == [
            {"chain": "A", "resi": 4, "resn": "ALA"}]
    finally:
        _close(p, browser)


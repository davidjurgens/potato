"""
chemical_structure and the molecule display with RDKit.js, after a real
`potato vendor fetch rdkit` into a vendor directory under tests/output.

* the scheme computes the RDKit SMILES, InChI and InChIKey in the browser
  and shows the InChIKey;
* a molecule display with ``engine: rdkit`` draws a SMILES that writes a
  hydrogen as an atom ([H]) and lets that hydrogen be selected by its source
  index (0), while the OpenChemLib display of the same SMILES says why it
  cannot select atoms;
* ``highlight_field`` draws fixed highlights, and the ``highlightAtoms`` /
  ``atoms`` API a linked display would use works.
"""

import json
import os
import subprocess
import sys

import pytest
import yaml

pytest.importorskip("playwright.sync_api")

from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.test_utils import create_test_directory  # noqa: E402

pytestmark = pytest.mark.playwright

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRATCH = os.environ.get("POTATO_SCREENSHOT_DIR") or create_test_directory("chemical_structure_screens")

ITEMS = [{"id": "halomethane", "note": "Mark the hydrogen.",
          "smiles": "[H]C(Cl)(Br)F", "smiles_ocl": "[H]C(Cl)(Br)F", "predicted": [2]}]


@pytest.fixture(scope="module")
def rdkit_server():
    vendor = create_test_directory("rdkit_vendor_ui")
    fetch = subprocess.run([sys.executable, "-m", "potato.vendoring.cli", "fetch", "rdkit"],
                           capture_output=True, text=True, cwd=REPO, timeout=600,
                           env=dict(os.environ, POTATO_VENDOR_DIR=vendor))
    if fetch.returncode != 0:
        pytest.skip(f"could not fetch RDKit.js: {fetch.stderr[-300:]}")
    old = os.environ.get("POTATO_VENDOR_DIR")
    os.environ["POTATO_VENDOR_DIR"] = vendor
    work = create_test_directory("chemical_structure_rdkit_ui")
    with open(os.path.join(work, "items.json"), "w") as f:
        json.dump(ITEMS, f)
    config = {
        "annotation_task_name": "RDKit check", "task_dir": ".",
        "output_annotation_dir": "annotation_output", "data_files": ["items.json"],
        "item_properties": {"id_key": "id", "text_key": "note"},
        "user_config": {"allow_all_users": True},
        "instance_display": {"fields": [
            {"key": "smiles", "type": "molecule", "label": "RDKit",
             "display_options": {"engine": "rdkit", "highlight_field": "predicted",
                                 "show_atom_numbers": True}},
            {"key": "smiles_ocl", "type": "molecule", "label": "OpenChemLib",
             "display_options": {"engine": "openchemlib", "atom_list": True}},
        ]},
        "annotation_schemes": [
            {"annotation_type": "viewer_selection", "name": "site",
             "description": "Mark atoms", "viewer_field": "smiles"},
            {"annotation_type": "chemical_structure", "name": "drawn",
             "description": "Draw it", "prefill_field": "smiles", "rdkit": True},
        ],
    }
    path = os.path.join(work, "config.yaml")
    with open(path, "w") as f:
        yaml.safe_dump(config, f)
    srv = FlaskTestServer(config_file=path)
    if not srv.start():
        pytest.fail("could not start the RDKit test server")
    yield srv
    srv.stop()
    if old is None:
        os.environ.pop("POTATO_VENDOR_DIR", None)
    else:
        os.environ["POTATO_VENDOR_DIR"] = old


def test_rdkit_identifiers_engine_and_hydrogen_selection(rdkit_server, page):
    page.set_viewport_size({"width": 1400, "height": 1100})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    req = page.context.request
    base = rdkit_server.base_url
    req.post(f"{base}/register", form={"action": "signup", "email": "rd", "pass": "pass"})
    req.post(f"{base}/auth", form={"action": "login", "email": "rd", "pass": "pass"})
    page.goto(f"{base}/annotate")
    page.wait_for_function(
        "[...document.querySelectorAll('.potato-viewer')].every(v => v.dataset.viewerState === 'ready')",
        timeout=60000)
    page.wait_for_function("(() => { const v = document.querySelector('.chemical-structure-input').value;"
                           " return v && JSON.parse(v).inchikey; })()", timeout=60000)

    answer = json.loads(page.eval_on_selector(".chemical-structure-input", "e => e.value"))
    assert answer["inchikey"] == "YNKZSBSRKWVMEZ-UHFFFAOYSA-N"      # bromochlorofluoromethane
    assert answer["inchi"].startswith("InChI=1S/CHBrClF/")
    assert answer["toolkits"]["rdkit"].startswith("2026.03")
    assert page.text_content("form.chemical-structure .cs-inchikey") == answer["inchikey"]

    rd, ocl = page.query_selector_all(".potato-viewer")
    # RDKit keeps the written hydrogen as atom 0, so it can be selected.
    assert rd.eval_on_selector_all(".mv-atom", "els => els.map(e => e.textContent)") == [
        "H1", "C2", "Cl3", "Br4", "F5"]
    box = rd.query_selector(".mv-hit[data-atom='0']").bounding_box()
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    stored = json.loads(page.eval_on_selector(".viewer-selection-input", "e => e.value"))
    assert stored["items"] == [{"atom": 0, "element": "H"}]
    assert rd.eval_on_selector_all(".mv-atom[aria-pressed='true']", "els => els.map(e => e.textContent)") == ["H1"]
    # The fixed highlight from highlight_field (atom index 2, Cl).
    assert rd.eval_on_selector_all(".mv-fixed", "els => els.length") == 1
    # OpenChemLib folds [H] into carbon: no selectable atoms, and it says why.
    assert ocl.query_selector_all(".mv-atom") == []
    assert "[H]" in ocl.query_selector(".mv-atom-strip").text_content()

    # The API a linked display (peaks on a spectrum) would use.
    atoms = page.evaluate("window.potatoViewers['smiles'].atoms().map(a => a.element + a.number)")
    assert atoms == ["H1", "C2", "Cl3", "Br4", "F5"]
    page.evaluate("window.potatoViewers['smiles'].highlightAtoms([3, 4], '#1c7ed6')")
    assert rd.eval_on_selector_all(".mv-temp", "els => els.length") == 2
    page.evaluate("window.potatoViewers['smiles'].highlightAtoms([])")
    assert rd.eval_on_selector_all(".mv-temp", "els => els.length") == 0
    page.screenshot(path=os.path.join(SCRATCH, "chem_rdkit.png"), full_page=True)
    assert not errors, errors

"""
chemical_structure scheme, molecule display, answer keys and the chemistry
export (potato/chemistry, schemas/chemical_structure.py,
displays/molecule_display.py, export/chemistry_exporter.py).

Grading tests that need RDKit skip when the rdkit package is not installed;
the no-RDKit path is tested by hiding it.
"""

import csv
import json
import logging
import os
import shutil
import subprocess

import pytest

from potato import chemistry
from potato.chemistry import structures

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(REPO, "tests", "data", "chemistry")
HAS_RDKIT = chemistry.rdkit_python() is not None
needs_rdkit = pytest.mark.skipif(not HAS_RDKIT, reason="rdkit not installed")

ASPIRIN = "CC(=O)Oc1ccccc1C(=O)O"
ASPIRIN_KEY = "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"


def _answer(smiles=None, molfile=None, **extra):
    out = {}
    if smiles:
        out["smiles"] = smiles
    if molfile:
        out["molfile"] = molfile
    out.update(extra)
    return json.dumps(out)


# ---------------------------------------------------------------------------
# Structure text and files
# ---------------------------------------------------------------------------

class TestStructureText:
    def test_detects_molfile_and_smiles(self):
        with open(os.path.join(DATA, "ethanol_h.mol")) as f:
            mol = f.read()
        assert structures.detect_format(mol) == "molfile"
        assert structures.detect_format(ASPIRIN) == "smiles"
        assert structures.detect_format(ASPIRIN, "molfile") == "molfile"

    def test_check_structure_text(self):
        assert structures.check_structure_text("") == "there is no structure"
        assert "no spaces" in structures.check_structure_text("CCO and more")
        assert structures.check_structure_text(ASPIRIN) is None
        big = "C" * (chemistry.MAX_STRUCTURE_BYTES + 1)
        assert "byte limit" in structures.check_structure_text(big)

    def test_reads_first_sdf_record_and_first_smiles(self):
        sdf = structures.read_structure_file(os.path.join(DATA, "two_records.sdf"))
        assert sdf.rstrip().endswith("M  END")
        assert sdf.splitlines()[0] == "phenol" and "acetic" not in sdf
        assert structures.read_structure_file(os.path.join(DATA, "caffeine.smi")) == \
            "Cn1cnc2c1c(=O)n(C)c(=O)n2C"

    def test_structure_file_size_limit(self, tmp_path, monkeypatch):
        path = tmp_path / "big.mol"
        path.write_text("x" * 50)
        monkeypatch.setattr(structures, "MAX_STRUCTURE_BYTES", 10)
        with pytest.raises(ValueError, match="10-byte limit"):
            structures.read_structure_file(str(path))

    def test_parse_stored_accepts_text_dict_and_label_map(self):
        value = _answer(ASPIRIN, idcode="x")
        assert structures.parse_stored(value)["smiles"] == ASPIRIN
        assert structures.parse_stored({"drawn": value})["smiles"] == ASPIRIN
        assert structures.parse_stored("not json") == {}
        assert structures.parse_stored("") == {}


# ---------------------------------------------------------------------------
# Answer keys
# ---------------------------------------------------------------------------

class TestAnswerKeys:
    def test_is_answer_key(self):
        assert structures.is_answer_key({"smiles": "CCO"})
        assert structures.is_answer_key({"substructure": "C=O"})
        assert not structures.is_answer_key({"smiles": "CCO", "label": "x"})
        assert not structures.is_answer_key({"ignore_stereo": True})
        assert not structures.is_answer_key("CCO")       # bare text only via answer_field
        assert not structures.is_answer_key([{"type": "bbox"}])

    def test_validate_answer_key(self):
        assert structures.validate_answer_key({"smiles": "CCO"}, "k") == []
        assert structures.validate_answer_key("CCO", "k") == []
        assert "twice" in structures.validate_answer_key({"smiles": "C", "inchikey": "A" * 27}, "k")[0]
        assert "27-character" in structures.validate_answer_key({"inchikey": "ABC"}, "k")[0]
        assert "SMARTS" in structures.validate_answer_key({"substructure": [""]}, "k")[0]
        assert "needs a smiles" in " ".join(
            structures.validate_answer_key({"substructure": "C", "ignore_stereo": True}, "k"))

    @needs_rdkit
    def test_exact_structure_match_ignores_how_it_was_written(self):
        assert structures.grade(_answer("OC(=O)c1ccccc1OC(C)=O"), {"smiles": ASPIRIN}) == \
            (True, "same structure")
        ok, reason = structures.grade(_answer("CC(=O)Oc1ccccc1C(=O)N"), {"smiles": ASPIRIN})
        assert not ok and reason == "a different structure"
        assert structures.grade(_answer(ASPIRIN), {"inchikey": ASPIRIN_KEY})[0]
        # A bare SMILES key (an item's answer_field).
        assert structures.grade(_answer(ASPIRIN), ASPIRIN)[0]

    @needs_rdkit
    def test_stereo_matters_unless_ignored(self):
        l_ala, d_ala = "C[C@@H](C(=O)O)N", "C[C@H](C(=O)O)N"
        assert not structures.grade(_answer(d_ala), {"smiles": l_ala})[0]
        ok, reason = structures.grade(_answer(d_ala), {"smiles": l_ala, "ignore_stereo": True})
        assert ok

    @needs_rdkit
    def test_substructure_keys(self):
        key = {"substructure": ["c1ccccc1", "C(=O)[OH]"], "not_substructure": "C(=O)N"}
        assert structures.grade(_answer(ASPIRIN), key) == \
            (True, "contains c1ccccc1; contains C(=O)[OH]; has no C(=O)N")
        ok, reason = structures.grade(_answer("CC(=O)Oc1ccccc1C(=O)N"), key)
        assert not ok and "C(=O)[OH]" in reason
        ok, reason = structures.grade(_answer(ASPIRIN), {"substructure": "[[["})
        assert not ok and "not valid SMARTS" in reason

    @needs_rdkit
    def test_molfile_answers_are_read(self):
        with open(os.path.join(DATA, "ethanol_h.mol")) as f:
            mol = f.read()
        assert structures.grade(_answer(molfile=mol), {"smiles": "CCO"})[0]
        ids = structures.server_identifiers({"molfile": mol})
        assert ids["inchikey"] == "LFQSCWFLJHTTHZ-UHFFFAOYSA-N" and ids["rdkit_smiles"] == "CCO"

    def test_empty_answer_is_wrong(self):
        assert structures.grade("", {"smiles": "CCO"}) == (False, "no structure was drawn")

    def test_without_rdkit_only_browser_inchikeys_grade(self, monkeypatch, caplog):
        monkeypatch.setattr(structures, "rdkit_python", lambda: None)
        monkeypatch.setattr(structures, "_warned_missing", False)
        with caplog.at_level(logging.ERROR):
            ok, reason = structures.grade(_answer(ASPIRIN), {"smiles": ASPIRIN})
        assert not ok and "potato-annotation[chemistry]" in reason
        assert "rdkit Python package" in caplog.text
        assert structures.grade(_answer(ASPIRIN, inchikey=ASPIRIN_KEY), {"inchikey": ASPIRIN_KEY}) == \
            (True, "same InChIKey")
        assert not structures.grade(_answer(ASPIRIN), {"inchikey": ASPIRIN_KEY})[0]

    @needs_rdkit
    def test_a_forged_browser_inchikey_is_not_trusted_with_rdkit(self):
        forged = _answer("CCO", inchikey=ASPIRIN_KEY)
        assert not structures.grade(forged, {"inchikey": ASPIRIN_KEY})[0]


class TestGradingIntegration:
    @needs_rdkit
    def test_training_answers_use_the_structure_comparator(self):
        from potato.server_utils.training_grading import check_training_answer
        assert check_training_answer({"drawn": _answer("OC(=O)c1ccccc1OC(C)=O")},
                                     {"drawn": {"smiles": ASPIRIN}})
        assert not check_training_answer({"drawn": _answer("CCO")}, {"drawn": {"smiles": ASPIRIN}})

    @needs_rdkit
    def test_gold_standards_use_the_structure_comparator(self):
        from potato.quality_control import QualityControlManager
        qc = QualityControlManager.__new__(QualityControlManager)
        key = {"substructure": "C(=O)[OH]"}
        assert qc._value_matches(key, _answer(ASPIRIN))
        assert not qc._value_matches(key, _answer("CCO"))
        # Both payload shapes the annotation page and API clients send.
        assert qc._compare_responses({"drawn": key}, {"drawn:::drawn": _answer(ASPIRIN)})
        assert qc._compare_responses({"drawn": key}, {"drawn": _answer(ASPIRIN)})

    def test_answer_field_never_reaches_the_page(self):
        from potato.server_utils.schemas.cloze import strip_answer_fields
        config = {"annotation_schemes": [{"annotation_type": "chemical_structure", "name": "c",
                                          "description": "d", "answer_field": "truth"}]}
        out = strip_answer_fields(config, {"id": "1", "truth": ASPIRIN, "smiles": "CCO"})
        assert out == {"id": "1", "smiles": "CCO"}


# ---------------------------------------------------------------------------
# Scheme
# ---------------------------------------------------------------------------

def _scheme(**extra):
    return {"annotation_type": "chemical_structure", "name": "drawn",
            "description": "Draw", **extra}


class TestScheme:
    def test_validate_scheme(self):
        from potato.server_utils.schemas.chemical_structure import validate_scheme
        assert validate_scheme(_scheme(), "s") == []
        assert validate_scheme(_scheme(prefill_field="smi", prefill_format="smiles"), "s") == []
        errors = " | ".join(validate_scheme(_scheme(
            rdkit="yes", editor_height=100, prefill_format="xyz", allow_empty="no"), "s"))
        assert "s.rdkit must be auto, true or false" in errors
        assert "editor_height" in errors and "prefill_format must be one of" in errors
        assert "prefill_format needs prefill_field" in errors
        assert "allow_empty must be true or false" in errors
        assert "must differ" in validate_scheme(
            _scheme(prefill_field="x", answer_field="x"), "s")[0]
        # 1 == True in Python; it is still not a valid rdkit value.
        assert validate_scheme(_scheme(rdkit=1), "s")

    def test_generator_renders_config_and_hidden_input(self, monkeypatch):
        from potato.server_utils.schemas.chemical_structure import generate_chemical_structure_layout
        monkeypatch.setattr(chemistry, "rdkit_urls", lambda: None)
        html, keys = generate_chemical_structure_layout(_scheme(prefill_field="smi"))
        assert keys == []
        assert 'data-annotation-type="chemical_structure"' in html
        assert 'class="annotation-input chemical-structure-input"' in html
        assert 'label_name="drawn"' in html
        assert "Restore the given structure" in html
        assert "potato vendor fetch rdkit" in html
        assert "/static/vendor/openchemlib-9.25.0/openchemlib.js" in html

    def test_generator_passes_rdkit_urls_when_installed(self, monkeypatch):
        from potato.server_utils.schemas.chemical_structure import generate_chemical_structure_layout
        urls = {"js": "/vendor-fetched/rdkit-2026.3.6/dist/RDKit_minimal.js",
                "wasm": "/vendor-fetched/rdkit-2026.3.6/dist/RDKit_minimal.wasm"}
        monkeypatch.setattr(chemistry, "rdkit_urls", lambda: urls)
        html, _ = generate_chemical_structure_layout(_scheme())
        assert "RDKit_minimal.wasm" in html and "potato vendor fetch rdkit" not in html
        html, _ = generate_chemical_structure_layout(_scheme(rdkit=False))
        assert "RDKit_minimal" not in html

    def test_every_option_is_declared(self):
        from potato.server_utils.schemas.registry import schema_registry
        schema = schema_registry.get("chemical_structure")
        for key in ("prefill_field", "prefill_format", "answer_field", "rdkit", "require_valid",
                    "allow_empty", "editor_height", "show_identifiers", "instructions"):
            assert key in schema.optional_fields


class TestConfigValidation:
    def test_rdkit_true_without_the_bundle_names_the_fetch_command(self, monkeypatch, tmp_path):
        from potato.server_utils.config_module import ConfigValidationError, validate_single_annotation_scheme
        monkeypatch.setenv("POTATO_VENDOR_DIR", str(tmp_path))
        with pytest.raises(ConfigValidationError, match="potato vendor fetch rdkit"):
            validate_single_annotation_scheme(_scheme(rdkit=True), "annotation_schemes[0]")

    def test_rdkit_auto_without_the_bundle_warns(self, monkeypatch, tmp_path, caplog):
        from potato.server_utils.config_module import validate_single_annotation_scheme
        monkeypatch.setenv("POTATO_VENDOR_DIR", str(tmp_path))
        with caplog.at_level(logging.WARNING):
            validate_single_annotation_scheme(_scheme(), "annotation_schemes[0]")
        assert "potato vendor fetch rdkit" in caplog.text
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            validate_single_annotation_scheme(_scheme(rdkit=False), "annotation_schemes[0]")
        assert "RDKit.js" not in caplog.text

    def test_bad_option_is_a_startup_error(self):
        from potato.server_utils.config_module import ConfigValidationError, validate_single_annotation_scheme
        with pytest.raises(ConfigValidationError, match="editor_height"):
            validate_single_annotation_scheme(_scheme(editor_height="tall"), "annotation_schemes[0]")

    def test_vendor_fetch_for_config_includes_rdkit_true(self):
        from potato.vendoring.requirements import required_bundles
        assert "rdkit" in required_bundles({"annotation_schemes": [_scheme(rdkit=True)]})
        assert "rdkit" not in required_bundles({"annotation_schemes": [_scheme()]})

    def test_rdkit_bundle_is_pinned(self):
        from potato import vendoring
        bundle = vendoring.get("rdkit")
        assert bundle.license == "BSD-3-Clause"
        assert bundle.integrity.startswith("sha512-")
        assert set(bundle.include) == {"dist/RDKit_minimal.js", "dist/RDKit_minimal.wasm"}


# ---------------------------------------------------------------------------
# Molecule display
# ---------------------------------------------------------------------------

class TestMoleculeDisplay:
    def _display(self):
        from potato.server_utils.displays.molecule_display import MoleculeDisplay
        return MoleculeDisplay()

    def test_inline_smiles_and_molfile(self):
        d = self._display()
        cfg = d.client_config({"key": "m"}, "  " + ASPIRIN + " ", d.get_display_options({"key": "m"}))
        assert cfg["source"] == ASPIRIN and cfg["format"] == "smiles"
        with open(os.path.join(DATA, "ethanol_h.mol")) as f:
            mol = f.read()
        cfg = d.client_config({"key": "m"}, mol, d.get_display_options({"key": "m"}))
        assert cfg["format"] == "molfile" and cfg["source"] == mol
        assert "rdkitWasm" not in cfg

    def test_structure_file_from_media(self, tmp_path):
        from potato.server_utils.displays.viewer_display import ViewerDataError
        media = tmp_path / "media"
        media.mkdir()
        shutil.copy(os.path.join(DATA, "two_records.sdf"), media)
        config = {"media_directory": str(media), "task_dir": str(tmp_path)}
        from potato.server_utils import config_module
        old = dict(config_module.config)
        config_module.config.clear()
        config_module.config.update(config)
        try:
            d = self._display()
            cfg = d.client_config({"key": "m"}, "two_records.sdf", d.get_display_options({"key": "m"}))
            assert cfg["format"] == "molfile" and cfg["source"].startswith("phenol")
            with pytest.raises(ViewerDataError, match="not in the media directory"):
                d.client_config({"key": "m"}, "../../etc/passwd.mol", d.get_display_options({"key": "m"}))
        finally:
            config_module.config.clear()
            config_module.config.update(old)

    def test_bad_data_renders_a_message(self):
        html = self._display().render({"key": "m", "type": "molecule"}, "C C O")
        assert "pv-failed" in html and "cannot be shown" in html

    def test_render_has_viewer_markup_and_atom_list(self):
        html = self._display().render({"key": "m", "type": "molecule"}, ASPIRIN)
        assert 'data-viewer-kind="molecule"' in html and 'data-viewer-field="m"' in html
        assert 'class="mv-atom-strip"' in html

    def test_item_text_is_escaped(self):
        # A molfile's title line is item text: it must not close the attribute
        # or open markup.
        with open(os.path.join(DATA, "ethanol_h.mol")) as f:
            mol = f.read().replace("ethanol with explicit hydrogens",
                                   "x'><img src=x onerror=alert(1)></script>")
        html = self._display().render({"key": "m", "type": "molecule"}, mol)
        assert "<img" not in html and "</script>" not in html
        assert "&lt;img src=x onerror=alert(1)&gt;" in html
        bad = self._display().render({"key": "m", "type": "molecule"}, "<b>not a smiles</b> x")
        assert "<b>" not in bad and "cannot be shown" in bad

    def test_validate_options(self):
        from potato.server_utils.displays.viewer_display import validate_viewer_field
        field = {"key": "m", "type": "molecule",
                 "display_options": {"format": "pdb", "highlight_color": "red", "max_atoms": 0}}
        errors = " | ".join(validate_viewer_field(field, "f", check_bundles=False))
        assert "format must be one of" in errors and "hex colour" in errors and "max_atoms" in errors

    def test_rdkit_engine_needs_the_bundle(self, monkeypatch, tmp_path):
        from potato.server_utils.displays.viewer_display import validate_viewer_field
        monkeypatch.setenv("POTATO_VENDOR_DIR", str(tmp_path))
        field = {"key": "m", "type": "molecule", "display_options": {"engine": "rdkit"}}
        assert any("potato vendor fetch rdkit" in e for e in validate_viewer_field(field, "f"))

    def test_viewer_selection_binds_to_a_molecule_field(self):
        from potato.server_utils.displays.viewer_display import validate_viewer_config
        config = {"instance_display": {"fields": [{"key": "m", "type": "molecule"}]},
                  "annotation_schemes": [{"annotation_type": "viewer_selection", "name": "s",
                                          "description": "d", "viewer_field": "m"}]}
        assert validate_viewer_config(config) == []

    def test_selection_shape(self):
        from potato.server_utils.displays.viewer_display import validate_selection
        good = {"viewer": "molecule", "items": [{"atom": 3, "element": "O", "label": "site"}]}
        assert validate_selection("molecule", good, labels=["site"]) == []
        errors = validate_selection("molecule", {"items": [{"atom": -1}, {"atom": 2, "resi": 4}]})
        assert any("0-based atom index" in e for e in errors)
        assert any("unexpected key(s) resi" in e for e in errors)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

class TestExporter:
    def _context(self, annotations, schemes=None, items=None):
        from potato.export.base import ExportContext
        schemes = schemes or [
            {"annotation_type": "chemical_structure", "name": "drawn", "description": "d",
             "answer_field": "truth"},
            {"annotation_type": "viewer_selection", "name": "site", "description": "d",
             "viewer_field": "mol"}]
        config = {"instance_display": {"fields": [{"key": "mol", "type": "molecule"}]}}
        return ExportContext(config=config, annotations=annotations,
                             items=items or {"i1": {"truth": ASPIRIN}, "i2": {}},
                             schemas=schemes, output_dir="")

    def _rows(self, path):
        with open(path, newline="") as f:
            return list(csv.DictReader(f))

    @needs_rdkit
    def test_writes_structures_sdf_and_atoms(self, tmp_path):
        from potato.export.chemistry_exporter import ChemistryExporter
        with open(os.path.join(DATA, "ethanol_h.mol")) as f:
            ethanol = f.read()
        anns = [
            {"user_id": "a", "instance_id": "i1",
             "labels": {"drawn": {"drawn": _answer("OC(=O)c1ccccc1OC(C)=O", formula="C9H8O4",
                                                   changed=True)},
                        "site": {"site": json.dumps({"viewer": "molecule", "items": [
                            {"atom": 12, "element": "N", "label": "wrong element"}]})}}},
            {"user_id": "b", "instance_id": "i2",
             "labels": {"drawn": {"drawn": _answer("CCO", molfile=ethanol, changed=False,
                                                   inchikey="FROM-BROWSER")}}},
        ]
        exporter = ChemistryExporter()
        assert exporter.can_export(self._context(anns)) == (True, "")
        result = exporter.export(self._context(anns), str(tmp_path))
        assert result.success, result.errors
        rows = self._rows(tmp_path / "chemical_structures.csv")
        assert rows[0]["inchikey"] == ASPIRIN_KEY and rows[0]["identifiers_from"] == "server"
        assert rows[0]["answer_correct"] == "1" and rows[0]["changed"] == "1"
        assert rows[1]["inchikey"] == "FROM-BROWSER" and rows[1]["identifiers_from"] == "browser"
        assert rows[1]["answer_correct"] == "" and rows[1]["answer_reason"] == "this item has no answer key"
        sdf = (tmp_path / "chemical_structures.sdf").read_text()
        assert sdf.count("$$$$") == 1            # only the answer with a molfile
        assert ">  <instance_id>\ni2\n" in sdf
        from rdkit import Chem
        mols = [m for m in Chem.SDMolSupplier(str(tmp_path / "chemical_structures.sdf"))]
        assert len(mols) == 1 and mols[0].GetProp("user_id") == "b"
        atoms = self._rows(tmp_path / "molecule_atoms.csv")
        assert atoms == [{"user_id": "a", "instance_id": "i1", "schema": "site", "viewer_field": "mol",
                          "atom": "12", "number": "13", "element": "N", "label": "wrong element"}]

    def test_without_rdkit_identifiers_are_blank_with_a_warning(self, tmp_path, monkeypatch):
        import potato.chemistry as chem
        from potato.export.chemistry_exporter import ChemistryExporter
        monkeypatch.setattr(chem, "rdkit_python", lambda: None)
        anns = [{"user_id": "a", "instance_id": "i1", "labels": {"drawn": {"drawn": _answer("CCO")}}}]
        result = ChemistryExporter().export(self._context(anns), str(tmp_path))
        rows = self._rows(tmp_path / "chemical_structures.csv")
        assert rows[0]["inchikey"] == "" and rows[0]["identifiers_from"] == "none"
        assert any("potato-annotation[chemistry]" in w for w in result.warnings)

    def test_nothing_annotated_is_a_failure_with_a_reason(self, tmp_path):
        from potato.export.chemistry_exporter import ChemistryExporter
        result = ChemistryExporter().export(self._context([{"user_id": "a", "instance_id": "i1",
                                                            "labels": {}}]), str(tmp_path))
        assert not result.success and "No chemical structures" in result.errors[0]

    def test_cannot_export_without_a_chemistry_scheme(self):
        from potato.export.chemistry_exporter import ChemistryExporter
        ctx = self._context([{"user_id": "a"}], schemes=[{"annotation_type": "radio", "name": "r"}])
        assert ChemistryExporter().can_export(ctx)[0] is False


# ---------------------------------------------------------------------------
# Browser code
# ---------------------------------------------------------------------------

NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node not installed")
class TestBrowserScripts:
    SCRIPTS = ["chem-toolkits.js", "molecule-viewer.js", "chemical-structure.js"]

    def test_scripts_parse(self):
        for name in self.SCRIPTS:
            path = os.path.join(REPO, "potato", "static", "chemistry", name)
            res = subprocess.run([NODE, "--check", path], capture_output=True, text=True)
            assert res.returncode == 0, (name, res.stderr)

    def test_smiles_atoms_follow_the_written_order(self):
        path = os.path.join(REPO, "potato", "static", "chemistry", "chem-toolkits.js")
        script = (
            "global.window = {}; global.document = {documentElement: {getAttribute: () => null}};"
            f"require({json.dumps(path)});"
            "const f = window.PotatoChem.smilesAtoms;"
            "console.log(JSON.stringify(['[H]C(Cl)(Br)F', 'c1cc[nH]c1', 'OC(=O)[C@@H](N)C', '[2H]C',"
            " 'C1CC%10CC1', '[se]1cccc1', 'CBr'].map(s => f(s).map(a => a.element + (a.hydrogen ? '*' : '')))));")
        res = subprocess.run([NODE, "-e", script], capture_output=True, text=True)
        assert res.returncode == 0, res.stderr
        assert json.loads(res.stdout) == [
            ["H*", "C", "Cl", "Br", "F"],
            ["C", "C", "C", "N", "C"],
            ["O", "C", "O", "C", "N", "C"],
            ["H", "C"],
            ["C", "C", "C", "C", "C"],
            ["Se", "C", "C", "C", "C"],
            ["C", "Br"],
        ]

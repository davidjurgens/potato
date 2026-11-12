"""protein_structure: structure parsing (mmCIF, BinaryCIF, PDB), the residue
table, pLDDT bands, remote and missing files, and engine assets."""

import gzip
import html as html_module
import importlib.util
import json
import os
import re
import struct
from unittest.mock import patch

import pytest

from potato.media import structures
from potato.media.structures import Residue, StructureError, detect_format, read_residues
from potato.server_utils.displays.protein_structure_display import (
    PLDDT_BANDS, ProteinStructureDisplay, plddt_band)
from potato.server_utils.displays.registry import display_registry
from tests.helpers.test_utils import create_test_directory

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXAMPLE = os.path.join(REPO, "examples", "advanced", "protein-binding-site")


def _generator():
    spec = importlib.util.spec_from_file_location(
        "generate_structures", os.path.join(EXAMPLE, "generate_structures.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GEN = _generator()


@pytest.fixture
def media():
    root = create_test_directory("protein_structure_unit")
    media = os.path.join(root, "media")
    os.makedirs(os.path.join(media, "s"), exist_ok=True)
    atoms = GEN.build_chain("ALAHKA", "A") + [GEN.hetatm("HOH", "A", 201, "O", "O", (1.0, 1.0, 1.0)),
                                             GEN.hetatm("ZN", "A", 301, "ZN", "ZN", (2.0, 2.0, 2.0))]
    with open(os.path.join(media, "s", "m.cif"), "w") as f:
        f.write(GEN.to_mmcif(atoms, "T1", "test"))
    with open(os.path.join(media, "s", "m.pdb"), "w") as f:
        f.write(GEN.to_pdb(atoms))
    with open(os.path.join(media, "s", "m.cif.gz"), "wb") as f:
        f.write(gzip.compress(GEN.to_mmcif(atoms, "T1", "test").encode()))
    cfg = {"task_dir": root, "media_directory": "media"}
    with patch.dict("potato.server_utils.config_module.config", cfg, clear=False):
        yield media


def _render(field, value):
    return display_registry.render("protein_structure", field, value)


def _client_config(page):
    m = re.search(r"data-viewer-config='([^']*)'", page)
    return json.loads(html_module.unescape(m.group(1)))


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

class TestParsing:
    def test_mmcif_pdb_and_gzip_agree_and_drop_water(self, media):
        cif = read_residues(os.path.join(media, "s", "m.cif"))
        pdb = read_residues(os.path.join(media, "s", "m.pdb"))
        gz = read_residues(os.path.join(media, "s", "m.cif.gz"))
        assert cif == pdb == gz
        assert [r.resn for r in cif] == ["ALA", "LEU", "ALA", "HIS", "LYS", "ALA", "ZN"]
        assert all(r.resn != "HOH" for r in cif)
        assert cif[-1].het and not cif[0].het

    def test_mmcif_quoted_values_and_insertion_codes(self):
        text = """data_x
loop_
_atom_site.group_PDB
_atom_site.label_atom_id
_atom_site.label_comp_id
_atom_site.auth_asym_id
_atom_site.auth_seq_id
_atom_site.pdbx_PDB_ins_code
_atom_site.B_iso_or_equiv
_atom_site.pdbx_PDB_model_num
ATOM "C1'" DA  'A B' 5 ? 12.5 1
ATOM CA    GLY H   52 A 80 1
ATOM CA    GLY H   52 B 81 1
ATOM CA    SER H   53 . 82 1
ATOM CA    SER H   53 . 82 2
#
_other.key value
"""
        residues = structures.parse_mmcif(text)
        assert [(r.chain, r.resi, r.icode, r.resn) for r in residues] == [
            ("A B", 5, "", "DA"), ("H", 52, "A", "GLY"), ("H", 52, "B", "GLY"), ("H", 53, "", "SER")]
        assert residues[1].b == 80.0

    def test_pdb_reads_only_the_first_model(self):
        model = GEN.to_pdb(GEN.build_chain("AA", "A")).replace("END\n", "")
        text = "MODEL        1\n" + model + "ENDMDL\nMODEL        2\n" + \
            model.replace(" A   1", " A   9") + "ENDMDL\nEND\n"
        assert [r.resi for r in structures.parse_pdb(text)] == [1, 2]

    def test_not_a_structure(self, tmp_path):
        p = tmp_path / "x.cif"
        p.write_text("data_x\n_cell.length_a 10\n")
        with pytest.raises(StructureError, match="_atom_site"):
            read_residues(str(p))
        with pytest.raises(StructureError, match="not a structure file"):
            read_residues(str(tmp_path / "x.txt"))

    def test_detect_format(self):
        assert detect_format("a/b/AF-P1-F1-model_v4.cif") == ("cif", False)
        assert detect_format("x.bcif.gz") == ("bcif", True)
        assert detect_format("https://h/1abc.pdb?dl=1") == ("pdb", False)
        assert detect_format("x.mol2") == (None, False)

    def test_binarycif_every_encoding(self, tmp_path):
        msgpack = pytest.importorskip("msgpack")
        doc = _bcif_document(msgpack)
        p = tmp_path / "m.bcif"
        p.write_bytes(doc)
        residues = read_residues(str(p))
        assert [(r.chain, r.resi, r.resn) for r in residues] == [
            ("A", 1, "MET"), ("A", 2, "GLY"), ("A", 300, "LYS"), ("B", 7, "ZN")]
        assert residues[0].b == pytest.approx(91.25)
        assert residues[3].het and residues[0].icode == ""

    def test_cache_is_invalidated_by_a_changed_file(self, media):
        path = os.path.join(media, "s", "m.cif")
        first = structures.cached_residues(path)
        atoms = GEN.build_chain("GG", "Z")
        with open(path, "w") as f:
            f.write(GEN.to_mmcif(atoms, "T2", "changed") + "\n#\n")
        assert [r.chain for r in structures.cached_residues(path)] == ["Z", "Z"]
        assert first[0].chain == "A"


def _bcif_document(msgpack):
    """A BinaryCIF _atom_site encoded with each encoding the decoder knows."""
    def byte_array(values, code, type_id):
        return {"data": struct.pack(f"<{len(values)}{code}", *values),
                "encoding": [{"kind": "ByteArray", "type": type_id}]}

    def ints(values):
        delta = [values[0] - values[0]] + [values[i] - values[i - 1] for i in range(1, len(values))]
        rle = []
        for v in delta:
            if rle and rle[-2] == v:
                rle[-1] += 1
            else:
                rle += [v, 1]
        packed = []
        for v in rle:
            while v >= 127:
                packed.append(127)
                v -= 127
            while v <= -128:
                packed.append(-128)
                v += 128
            packed.append(v)
        return {"data": struct.pack(f"<{len(packed)}b", *packed), "encoding": [
            {"kind": "Delta", "origin": values[0], "srcType": 3},
            {"kind": "RunLength", "srcType": 3, "srcSize": len(values)},
            {"kind": "IntegerPacking", "byteCount": 1, "isUnsigned": False, "srcSize": len(rle)},
            {"kind": "ByteArray", "type": 1}]}

    def strings(values):
        table = list(dict.fromkeys(values))
        offsets, pos = [0], 0
        for s in table:
            pos += len(s)
            offsets.append(pos)
        idx = [table.index(v) for v in values]
        return {"data": struct.pack(f"<{len(idx)}i", *idx), "encoding": [{
            "kind": "StringArray", "dataEncoding": [{"kind": "ByteArray", "type": 3}],
            "stringData": "".join(table),
            "offsetEncoding": [{"kind": "ByteArray", "type": 3}],
            "offsets": struct.pack(f"<{len(offsets)}i", *offsets)}]}

    def floats(values):
        return {"data": struct.pack(f"<{len(values)}i", *[round(v * 100) for v in values]),
                "encoding": [{"kind": "FixedPoint", "factor": 100, "srcType": 33},
                             {"kind": "ByteArray", "type": 3}]}

    rows = [("ATOM", "N", "MET", "A", 1, 80.0), ("ATOM", "CA", "MET", "A", 1, 91.25),
            ("ATOM", "CA", "GLY", "A", 2, 90.0), ("ATOM", "CA", "LYS", "A", 300, 70.0),
            ("HETATM", "ZN", "ZN", "B", 7, 50.0), ("HETATM", "O", "HOH", "B", 8, 30.0)]
    n = len(rows)
    columns = [
        {"name": "group_PDB", "data": strings([r[0] for r in rows]), "mask": None},
        {"name": "label_atom_id", "data": strings([r[1] for r in rows]), "mask": None},
        {"name": "label_comp_id", "data": strings([r[2] for r in rows]), "mask": None},
        {"name": "auth_asym_id", "data": strings([r[3] for r in rows]), "mask": None},
        {"name": "auth_seq_id", "data": ints([r[4] for r in rows]), "mask": None},
        {"name": "B_iso_or_equiv", "data": floats([r[5] for r in rows]), "mask": None},
        {"name": "pdbx_PDB_ins_code", "data": strings([""] * n),
         "mask": byte_array([2] * n, "B", 4)},
        {"name": "pdbx_PDB_model_num", "data": ints([1] * n), "mask": None},
    ]
    doc = {"version": "0.3.0", "encoder": "test",
           "dataBlocks": [{"header": "TEST", "categories": [
               {"name": "_atom_site", "rowCount": n, "columns": columns}]}]}
    return msgpack.packb(doc, use_bin_type=True)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

class TestRender:
    def test_residue_table_and_config(self, media):
        page = _render({"key": "structure", "type": "protein_structure"}, "s/m.cif")
        cfg = _client_config(page)
        assert cfg["url"] == "/media/s/m.cif" and cfg["format"] == "cif"
        assert cfg["engine"] == "3dmol" and cfg["webgl"] == "webgl"
        assert cfg["assets"] == [{"type": "script", "src": "/static/vendor/3dmol-2.5.5/3Dmol-min.js"}]
        assert "_residues" not in cfg and cfg["tableFromModel"] is False
        cells = re.findall(r'<button type="button" class="pv-res[^"]*" data-chain="A" data-resi="(\d+)" '
                           r'data-resn="(\w+)"', page)
        assert cells == [("1", "ALA"), ("2", "LEU"), ("3", "ALA"), ("4", "HIS"), ("5", "LYS"),
                         ("6", "ALA"), ("301", "ZN")]
        assert 'aria-label="HIS 4, chain A"' in page
        # One tab stop per chain, so the table is not a hundred Tab presses.
        assert page.count('tabindex="0"') == 1
        assert 'data-viewer-kind="protein_structure"' in page and 'class="potato-viewer' in page

    def test_plddt_bands_legend_and_scale(self, media):
        assert [plddt_band(v) for v in (95, 90, 70.1, 70, 50.5, 50, 10)] == [0, 1, 1, 2, 2, 3, 3]
        assert plddt_band(0.93, scale=100) == 0
        assert [b[2] for b in PLDDT_BANDS] == ["#0053D6", "#65CBF3", "#FFDB13", "#FF7D45"]
        page = _render({"key": "s", "type": "protein_structure", "plddt": True}, "s/m.cif")
        assert 'class="pv-legend"' in page and 'data-band="1"' in page   # 90 is 'confident', not 'very high'
        assert _client_config(page)["plddtScale"] == 1.0
        # pLDDT written as 0-1 (as some predictors write it) is detected.
        atoms = GEN.build_chain("AAA", "A", plddt=[0.95, 0.6, 0.3])
        with open(os.path.join(media, "s", "unit.cif"), "w") as f:
            f.write(GEN.to_mmcif(atoms, "U", "unit"))
        page = _render({"key": "s", "type": "protein_structure", "plddt": True}, "s/unit.cif")
        assert _client_config(page)["plddtScale"] == 100.0
        assert re.findall(r'data-band="(\d)"', page) == ["0", "2", "3"]

    def test_remote_url_is_refused_unless_allowed(self, media):
        url = "https://alphafold.ebi.ac.uk/files/AF-P69905-F1-model_v4.cif"
        page = _render({"key": "s", "type": "protein_structure"}, url)
        assert "pv-failed" in page and "remote" in page and "allow_remote" in page
        assert _client_config(page)["error"]
        allowed = _render({"key": "s", "type": "protein_structure", "allow_remote": True}, url)
        cfg = _client_config(allowed)
        assert cfg["url"] == url and cfg["tableFromModel"] is True
        assert "Reading residues from the structure" in allowed

    def test_missing_file_and_unknown_format(self, media):
        page = _render({"key": "s", "type": "protein_structure"}, "s/nope.cif")
        assert "pv-failed" in page and "not in the media directory" in page
        with open(os.path.join(media, "s", "m.xyz"), "w") as f:
            f.write("x")
        page = _render({"key": "s", "type": "protein_structure"}, "s/m.xyz")
        assert "Cannot tell the format" in page
        page = _render({"key": "s", "type": "protein_structure"}, "../../etc/passwd.cif")
        assert "pv-failed" in page

    def test_unreadable_file_still_renders_the_viewer(self, media):
        with open(os.path.join(media, "s", "bad.cif"), "w") as f:
            f.write("data_bad\n")
        page = _render({"key": "s", "type": "protein_structure"}, "s/bad.cif")
        cfg = _client_config(page)
        assert "pv-failed" not in page and cfg["tableFromModel"] is True
        assert "residue table is unavailable" in page

    def test_table_limit(self, media):
        page = _render({"key": "s", "type": "protein_structure", "residue_table_limit": 3}, "s/m.cif")
        assert "more than the table shows" in page and "pv-res " not in page

    def test_molstar_assets_come_from_the_fetched_bundle(self, media):
        page = _render({"key": "s", "type": "protein_structure", "engine": "molstar"}, "s/m.cif")
        cfg = _client_config(page)
        assert [a["src"] for a in cfg["assets"]] == [
            "/vendor-fetched/molstar-5.12.0/molstar.css", "/vendor-fetched/molstar-5.12.0/molstar.js"]
        assert ProteinStructureDisplay().required_bundles({"engine": "molstar"}) == ["molstar"]
        assert ProteinStructureDisplay().required_bundles({}) == []

    def test_options_flat_or_nested_reach_the_page(self, media):
        nested = _render({"key": "s", "type": "protein_structure",
                          "display_options": {"color_by": "spectrum", "height": "30rem"}}, "s/m.cif")
        assert _client_config(nested)["colorBy"] == "spectrum" and "height: 30rem" in nested
        flat = _render({"key": "s", "type": "protein_structure", "pae_field": "pae"}, "s/m.cif")
        assert 'class="pv-side pv-pae"' in flat and _client_config(flat)["paeField"] == "pae"


class TestVendoredFile:
    def test_committed_3dmol_matches_its_pinned_hash(self):
        import base64
        import hashlib
        path = os.path.join(REPO, "potato", "static", "vendor", "3dmol-2.5.5", "3Dmol-min.js")
        digest = base64.b64encode(hashlib.sha256(open(path, "rb").read()).digest()).decode()
        assert digest == "98x4khrnLnYj6JzdERQ09Ywu/d0v/aHNISZEtAb7gBY="
        assert os.path.isfile(os.path.join(os.path.dirname(path), "LICENSE"))

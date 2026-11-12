#!/usr/bin/env python3
"""
Writes the synthetic structures for the protein-binding-site example.

Run from the repository root:
    python examples/advanced/protein-binding-site/generate_structures.py

Every model here is made up. Backbones are built from ideal bond lengths,
angles and (phi, psi) torsions; each residue gets its N, CA, C, O and, for
everything but glycine, a CB. There are no other side-chain atoms, so a
"histidine" is drawn as a stub. The B-factor column holds an invented pLDDT
so the confidence colouring has something to show.

The module is also imported by the tests (tests/playwright/), which build a
ten-residue alanine helix with :func:`build_chain` and :func:`to_pdb`.
"""

from __future__ import annotations

import math
import os
from typing import Dict, List, Sequence, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))

THREE = {"A": "ALA", "R": "ARG", "N": "ASN", "D": "ASP", "C": "CYS", "Q": "GLN",
         "E": "GLU", "G": "GLY", "H": "HIS", "I": "ILE", "L": "LEU", "K": "LYS",
         "M": "MET", "F": "PHE", "P": "PRO", "S": "SER", "T": "THR", "W": "TRP",
         "Y": "TYR", "V": "VAL"}

HELIX = (-57.0, -47.0)
EXTENDED = (-120.0, 130.0)

Vec = Tuple[float, float, float]


def _sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def _add(a, b): return (a[0] + b[0], a[1] + b[1], a[2] + b[2])
def _scale(a, s): return (a[0] * s, a[1] * s, a[2] * s)
def _dot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def _cross(a, b): return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
def _unit(a):
    n = math.sqrt(_dot(a, a))
    return (a[0] / n, a[1] / n, a[2] / n)


def place(a: Vec, b: Vec, c: Vec, bond: float, angle: float, torsion: float) -> Vec:
    """Atom d bonded to c, with angle b-c-d and torsion a-b-c-d (degrees)."""
    angle, torsion = math.radians(angle), math.radians(torsion)
    bc = _unit(_sub(c, b))
    n = _unit(_cross(_sub(b, a), bc))
    m = _cross(n, bc)
    d2 = (-bond * math.cos(angle), bond * math.sin(angle) * math.cos(torsion),
          bond * math.sin(angle) * math.sin(torsion))
    return _add(c, _add(_scale(bc, d2[0]), _add(_scale(m, d2[1]), _scale(n, d2[2]))))


def build_chain(sequence: str, chain: str, torsions: Sequence[Tuple[float, float]] = (),
                start: int = 1, plddt: Sequence[float] = (), offset: Vec = (0.0, 0.0, 0.0)
                ) -> List[Dict]:
    """Backbone (+CB) atoms for ``sequence``; one (phi, psi) per residue
    (default: alpha helix)."""
    atoms: List[Dict] = []
    n, ca, c = (0.0, 1.458, 0.0), (0.0, 0.0, 0.0), (1.525 * math.sin(math.radians(111.2)),
                                                    1.525 * math.cos(math.radians(111.2)), 0.0)
    for i, letter in enumerate(sequence):
        phi, psi = torsions[i] if i < len(torsions) else HELIX
        if i > 0:
            prev_n, prev_ca, prev_c = n, ca, c
            prev_psi = torsions[i - 1][1] if i - 1 < len(torsions) else HELIX[1]
            n = place(prev_n, prev_ca, prev_c, 1.329, 116.2, prev_psi)
            ca = place(prev_ca, prev_c, n, 1.458, 121.7, 180.0)
            c = place(prev_c, n, ca, 1.525, 111.2, phi)
        o = place(n, ca, c, 1.231, 120.5, psi + 180.0)
        resn = THREE[letter]
        b = plddt[i] if i < len(plddt) else 90.0
        residue = [("N", "N", n), ("CA", "C", ca), ("C", "C", c), ("O", "O", o)]
        if letter != "G":
            bb, cc = _sub(ca, n), _sub(c, ca)
            aa = _cross(bb, cc)
            cb = _add(ca, _add(_scale(aa, -0.58273431), _add(_scale(bb, 0.56802827), _scale(cc, -0.54067466))))
            residue.append(("CB", "C", cb))
        for name, element, xyz in residue:
            atoms.append({"group": "ATOM", "name": name, "element": element, "resn": resn,
                          "chain": chain, "resi": start + i, "seq": i + 1,
                          "xyz": _add(xyz, offset), "b": b})
    return atoms


def hetatm(resn: str, chain: str, resi: int, name: str, element: str, xyz: Vec, b: float = 90.0) -> Dict:
    return {"group": "HETATM", "name": name, "element": element, "resn": resn, "chain": chain,
            "resi": resi, "seq": None, "xyz": xyz, "b": b}


def to_pdb(atoms: List[Dict], title: str = "SYNTHETIC MODEL") -> str:
    lines = [f"HEADER    {title[:40]:<40}", "REMARK   1 SYNTHETIC COORDINATES, NOT AN EXPERIMENTAL STRUCTURE"]
    for serial, a in enumerate(atoms, start=1):
        x, y, z = a["xyz"]
        name = a["name"] if len(a["name"]) == 4 else f" {a['name']:<3}"
        lines.append(
            f"{a['group']:<6}{serial:>5} {name}{'':1}{a['resn']:>3} {a['chain']:1}{a['resi']:>4}{'':1}   "
            f"{x:>8.3f}{y:>8.3f}{z:>8.3f}{1.0:>6.2f}{a['b']:>6.2f}          {a['element']:>2}")
    lines.append("END")
    return "\n".join(lines) + "\n"


def to_mmcif(atoms: List[Dict], entry: str, title: str) -> str:
    """mmCIF with auth_* and label_* columns, and the ModelCIF local pLDDT
    table that AlphaFold DB files carry (Mol* colours by it)."""
    asym = {}
    for a in atoms:
        asym.setdefault(a["chain"], len(asym) + 1)
    out = [f"data_{entry}", "#", f"_entry.id {entry}", f"_struct.title '{title}'", "#",
           "loop_"]
    cols = ["group_PDB", "id", "type_symbol", "label_atom_id", "label_alt_id", "label_comp_id",
            "label_asym_id", "label_entity_id", "label_seq_id", "pdbx_PDB_ins_code",
            "Cartn_x", "Cartn_y", "Cartn_z", "occupancy", "B_iso_or_equiv", "auth_seq_id",
            "auth_comp_id", "auth_asym_id", "auth_atom_id", "pdbx_PDB_model_num"]
    out += [f"_atom_site.{c}" for c in cols]
    for serial, a in enumerate(atoms, start=1):
        x, y, z = a["xyz"]
        seq = "." if a["seq"] is None else str(a["seq"])
        out.append(" ".join([a["group"], str(serial), a["element"], a["name"], ".", a["resn"],
                             a["chain"], str(asym[a["chain"]]), seq, "?",
                             f"{x:.3f}", f"{y:.3f}", f"{z:.3f}", "1.00", f"{a['b']:.2f}",
                             str(a["resi"]), a["resn"], a["chain"], a["name"], "1"]))
    out += ["#", "loop_", "_ma_qa_metric.id", "_ma_qa_metric.mode", "_ma_qa_metric.name",
            "_ma_qa_metric.software_group_id", "_ma_qa_metric.type",
            "1 global pLDDT 1 pLDDT", "2 local pLDDT 1 pLDDT", "#", "loop_",
            "_ma_qa_metric_local.label_asym_id", "_ma_qa_metric_local.label_comp_id",
            "_ma_qa_metric_local.label_seq_id", "_ma_qa_metric_local.metric_id",
            "_ma_qa_metric_local.metric_value", "_ma_qa_metric_local.model_id",
            "_ma_qa_metric_local.ordinal_id"]
    seen, ordinal = set(), 0
    for a in atoms:
        if a["seq"] is None or (a["chain"], a["seq"]) in seen:
            continue
        seen.add((a["chain"], a["seq"]))
        ordinal += 1
        out.append(f"{a['chain']} {a['resn']} {a['seq']} 2 {a['b']:.2f} 1 {ordinal}")
    out.append("#")
    return "\n".join(out) + "\n"


def pae_png(path: str, n: int, low_until: int) -> None:
    """A synthetic predicted-aligned-error matrix as a PNG (needs Pillow):
    small errors within the confident region, large ones involving the tail."""
    from PIL import Image
    img = Image.new("RGB", (n, n))
    px = img.load()
    for i in range(n):
        for j in range(n):
            err = 2.0 + 0.4 * abs(i - j) ** 0.5
            if i < low_until or j < low_until:
                err = 18.0 + 6.0 * ((i * 7 + j * 3) % 5) / 5.0
            t = min(err / 30.0, 1.0)        # 0 Å dark green ... 30 Å white
            px[i, j] = (int(30 + 225 * t), int(110 + 145 * t), int(40 + 215 * t))
    img = img.resize((n * 8, n * 8), Image.NEAREST)
    img.save(path)


def main() -> None:
    media = os.path.join(HERE, "media", "structures")
    os.makedirs(media, exist_ok=True)

    # Item 1: a helix with two histidines and a glutamate facing a zinc ion,
    # and a short partner helix beside it.
    receptor = "MSEELLKHAEELIHKAEELLKR"
    plddt_a = [72, 80, 86] + [92] * 16 + [84, 76, 64]
    chain_a = build_chain(receptor, "A", plddt=plddt_a)
    partner = build_chain("GSKLEELLKK", "B", plddt=[66, 74, 84, 90, 91, 91, 90, 86, 70, 55],
                          offset=(9.5, 2.0, 3.0))
    his = [a["xyz"] for a in chain_a if a["resn"] == "HIS" and a["name"] == "CB"]
    centre = tuple(sum(v[k] for v in his) / len(his) for k in range(3))
    zinc = hetatm("ZN", "A", 101, "ZN", "ZN", (centre[0] + 3.0, centre[1], centre[2] + 1.0))
    complex_atoms = chain_a + partner + [zinc]
    with open(os.path.join(media, "zinc_site_complex.cif"), "w") as f:
        f.write(to_mmcif(complex_atoms, "SYNTH-ZN-0001", "Synthetic zinc site, two chains"))

    # Item 2: a predicted single chain with a disordered N-terminal tail.
    seq = "MPSTGKAAELLKEHLEKAVRYLEEAG"
    tail = 7
    torsions = [EXTENDED] * tail + [HELIX] * (len(seq) - tail)
    plddt = [38, 41, 44, 47, 52, 58, 66] + [91, 93, 94, 95, 95, 96, 96, 95, 94, 94, 93, 92,
                                            92, 91, 90, 88, 84, 79]
    model = build_chain(seq, "A", torsions=torsions, plddt=plddt)
    with open(os.path.join(media, "predicted_tail_model.cif"), "w") as f:
        f.write(to_mmcif(model, "SYNTH-PRED-0002", "Synthetic predicted model with a disordered tail"))
    pae_png(os.path.join(media, "predicted_tail_model_pae.png"), len(seq), tail)
    # The same complex in the legacy PDB format, for comparison.
    with open(os.path.join(media, "zinc_site_complex.pdb"), "w") as f:
        f.write(to_pdb(complex_atoms, "SYNTHETIC ZINC SITE"))
    print("wrote", sorted(os.listdir(media)))


if __name__ == "__main__":
    main()

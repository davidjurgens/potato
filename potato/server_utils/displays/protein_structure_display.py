"""
Protein structure display (``type: protein_structure``).

Shows a macromolecular structure as a cartoon, draws selected residues as
sticks, and lets the annotator toggle a residue by clicking it in the 3D view
or in the residue table under it. Pair it with a ``viewer_selection`` scheme
to store the selection (a binding site, an epitope, a disordered loop).

The item field holds a structure file: mmCIF (``.cif``), BinaryCIF
(``.bcif``) or PDB (``.pdb``), optionally gzipped, as a path inside the media
directory. An http(s) URL (an AlphaFold DB or RCSB file) is loaded only with
``allow_remote: true``; the browser fetches it, Potato does not.

Engines:

* ``3dmol`` (default): 3Dmol.js 2.5.5, BSD-3-Clause, committed under
  ``potato/static/vendor/3dmol-2.5.5/``. Needs WebGL.
* ``molstar``: Mol* 5.12.0, MIT, about 5 MB, so not committed. Install it with
  ``potato vendor fetch molstar``; ``potato validate`` names that command when
  a config asks for it and it is missing. Needs WebGL.

The residue table is rendered on the server from the file, so it works
without WebGL and without the library. Selections are lists of
``{chain, resi, resn}`` (``icode`` when the residue has an insertion code),
with chain and number as the file's ``auth_asym_id`` / ``auth_seq_id``.
"""

from __future__ import annotations

import html
import logging
from typing import Any, Dict, List, Optional

from .viewer_display import (ViewerAsset, ViewerDataError, ViewerDisplay,
                             ViewerEngine, resolve_source)

logger = logging.getLogger(__name__)

#: AlphaFold's pLDDT bands: (lower bound exclusive, name, colour).
PLDDT_BANDS = (
    (90.0, "Very high (pLDDT > 90)", "#0053D6"),
    (70.0, "Confident (90 ≥ pLDDT > 70)", "#65CBF3"),
    (50.0, "Low (70 ≥ pLDDT > 50)", "#FFDB13"),
    (float("-inf"), "Very low (pLDDT ≤ 50)", "#FF7D45"),
)

COLOR_MODES = ("chain", "spectrum", "secondary")
DEFAULT_TABLE_LIMIT = 3000


def plddt_band(value: Optional[float], scale: float = 1.0) -> Optional[int]:
    """Index into :data:`PLDDT_BANDS` for a B-factor read as pLDDT."""
    if value is None:
        return None
    v = value * scale
    for i, (lower, _name, _colour) in enumerate(PLDDT_BANDS):
        if v > lower:
            return i
    return len(PLDDT_BANDS) - 1


class ProteinStructureDisplay(ViewerDisplay):
    name = "protein_structure"
    description = "Protein structure (mmCIF, BinaryCIF, PDB) with residue selection"
    required_fields = ["key"]
    optional_fields = {
        **ViewerDisplay.COMMON_OPTIONS,
        "engine": "3dmol",
        "format": None,
        "color_by": "chain",
        "plddt": False,
        "pae_field": None,
        "show_ligands": True,
        "residue_table": True,
        "residue_table_limit": DEFAULT_TABLE_LIMIT,
    }
    default_engine = "3dmol"
    engines = {
        "3dmol": ViewerEngine(
            name="3dmol", label="3Dmol.js", webgl="webgl", licence="BSD-3-Clause",
            assets=(ViewerAsset("script", "vendor/3dmol-2.5.5/3Dmol-min.js"),)),
        "molstar": ViewerEngine(
            name="molstar", label="Mol*", webgl="webgl", licence="MIT",
            assets=(ViewerAsset("style", "molstar.css", bundle="molstar"),
                    ViewerAsset("script", "molstar.js", bundle="molstar"))),
    }
    selection_context = ()

    # -- options ----------------------------------------------------------------

    def validate_options(self, options: Dict[str, Any], path: str) -> List[str]:
        errors = []
        fmt = options.get("format")
        if fmt is not None and fmt not in ("cif", "bcif", "pdb"):
            errors.append(f"{path}.format must be cif, bcif or pdb (or left out to "
                          f"use the file extension), not {fmt!r}")
        if options.get("color_by") not in COLOR_MODES:
            errors.append(f"{path}.color_by must be one of {', '.join(COLOR_MODES)}")
        for key in ("plddt", "show_ligands", "residue_table"):
            if not isinstance(options.get(key), bool):
                errors.append(f"{path}.{key} must be true or false")
        limit = options.get("residue_table_limit")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            errors.append(f"{path}.residue_table_limit must be a positive integer")
        pae = options.get("pae_field")
        if pae is not None and (not isinstance(pae, str) or not pae):
            errors.append(f"{path}.pae_field must name an item field holding an image")
        return errors

    # -- rendering ----------------------------------------------------------------

    def client_config(self, field_config, data, options):
        from potato.media import structures
        if isinstance(data, dict):
            raise ViewerDataError(
                "A protein_structure field holds one structure file path or URL, "
                "not a mapping.")
        url, path = resolve_source(data, bool(options.get("allow_remote")),
                                   "structure file")
        fmt, gz = structures.detect_format(url)
        fmt = options.get("format") or fmt
        if fmt is None:
            raise ViewerDataError(
                f"Cannot tell the format of '{url.rsplit('/', 1)[-1]}'. Name the "
                f"file .cif, .bcif or .pdb (optionally .gz), or set format: on "
                f"the display.")
        residues: Optional[List[Any]] = None
        table_error = None
        if path is not None and options.get("residue_table", True):
            try:
                residues = structures.cached_residues(path, fmt)
            except (structures.StructureError, OSError) as e:
                table_error = str(e)
                logger.warning("protein_structure: could not read %s: %s", path, e)
        scale = 1.0
        if residues and options.get("plddt"):
            values = [r.b for r in residues if r.b is not None]
            if values and max(values) <= 1.0:
                scale = 100.0     # pLDDT written as 0-1 (some predictors do)
        return {
            "url": url,
            "format": fmt,
            "gzip": gz,
            "colorBy": options.get("color_by", "chain"),
            "plddt": bool(options.get("plddt")),
            "plddtScale": scale,
            "plddtBands": [{"min": b[0] if b[0] != float("-inf") else None,
                            "name": b[1], "color": b[2]} for b in PLDDT_BANDS],
            "showLigands": bool(options.get("show_ligands", True)),
            "paeField": options.get("pae_field") or None,
            "allowRemote": bool(options.get("allow_remote")),
            "residueTable": bool(options.get("residue_table", True)),
            # The adapter fills the table from the loaded model when the server
            # could not read the file (a remote URL, or a format problem).
            "tableFromModel": bool(options.get("residue_table", True)) and residues is None,
            "tableError": table_error,
            "tableLimit": int(options.get("residue_table_limit") or DEFAULT_TABLE_LIMIT),
            "_residues": residues,      # popped before serialising
        }

    def render_side(self, field_config, data, options, cfg) -> str:
        if not cfg.get("paeField"):
            return ""
        return ('<figure class="pv-side pv-pae" hidden>'
                '<img alt="Predicted aligned error (PAE) for this structure" loading="lazy">'
                '<figcaption>Predicted aligned error</figcaption></figure>')

    def render_extras(self, field_config, data, options, cfg) -> str:
        residues = cfg.pop("_residues", None)
        parts = []
        if cfg.get("plddt"):
            parts.append(self._legend())
        if cfg.get("residueTable"):
            parts.append(self._table(field_config, residues, cfg))
        return "".join(parts)

    def _legend(self) -> str:
        items = "".join(
            f'<li><span class="pv-swatch" style="background:{colour}"></span>{html.escape(name)}</li>'
            for _lo, name, colour in PLDDT_BANDS)
        return (f'<ul class="pv-legend" aria-label="Colour key: model confidence (pLDDT)">'
                f'{items}</ul>')

    def _table(self, field_config, residues, cfg) -> str:
        dom_id = self.field_id(field_config)
        head = (f'<div class="pv-residues-head"><span class="pv-residues-title" '
                f'id="{dom_id}-res-title">Residues</span>'
                f'<span class="pv-residues-hint">Click a residue to select it. '
                f'From the keyboard: Tab to a chain, arrow keys to move, Space to select.</span></div>')
        if residues is None:
            note = ("Reading residues from the structure…" if not cfg.get("tableError")
                    else f"The residue table is unavailable: {html.escape(cfg['tableError'])}")
            return (f'<div class="pv-residues" aria-labelledby="{dom_id}-res-title">{head}'
                    f'<p class="pv-residues-note">{note}</p><div class="pv-chains"></div></div>')
        limit = cfg.get("tableLimit") or DEFAULT_TABLE_LIMIT
        from potato.media.structures import chains
        if len(residues) > limit:
            return (f'<div class="pv-residues" aria-labelledby="{dom_id}-res-title">{head}'
                    f'<p class="pv-residues-note">This structure has {len(residues)} residues, '
                    f'more than the table shows ({limit}; see residue_table_limit). '
                    f'Select residues in the 3D view.</p></div>')
        scale = cfg.get("plddtScale", 1.0)
        out = [f'<div class="pv-residues" aria-labelledby="{dom_id}-res-title">', head,
               '<div class="pv-chains">']
        for chain, members in chains(residues).items():
            chain_id = f"{dom_id}-chain-{''.join(c if c.isalnum() else '_' for c in chain)}"
            label = f"Chain {chain}" if chain else "No chain ID"
            out.append(f'<div class="pv-chain" data-chain="{html.escape(chain, quote=True)}">'
                       f'<div class="pv-chain-name" id="{chain_id}">{html.escape(label)}'
                       f' <span class="pv-count">{len(members)} residues</span></div>'
                       f'<div class="pv-res-strip" role="group" aria-labelledby="{chain_id}">')
            for n, r in enumerate(members):
                number = f"{r.resi}{r.icode}"
                tick = n == 0 or r.resi % 10 == 0
                band = plddt_band(r.b, scale) if cfg.get("plddt") else None
                attrs = (f'data-chain="{html.escape(r.chain, quote=True)}" data-resi="{r.resi}" '
                         f'data-resn="{html.escape(r.resn, quote=True)}"'
                         + (f' data-icode="{html.escape(r.icode, quote=True)}"' if r.icode else "")
                         + (f' data-band="{band}"' if band is not None else ""))
                code = html.escape(r.resn if r.het or r.code == "X" else r.code)
                out.append(
                    f'<button type="button" class="pv-res{" pv-het" if r.het else ""}'
                    f'{" pv-tick" if tick else ""}" {attrs} aria-pressed="false" '
                    f'tabindex="{0 if n == 0 else -1}" '
                    f'aria-label="{html.escape(r.resn)} {number}, chain {html.escape(chain or "none")}" '
                    f'title="{html.escape(r.resn)} {number}">'
                    f'<span class="pv-res-code" aria-hidden="true">{code}</span>'
                    f'<span class="pv-res-num" aria-hidden="true">{number}</span></button>')
            out.append('</div></div>')
        out.append('</div></div>')
        return "".join(out)

    # -- selection shape -----------------------------------------------------------

    def validate_item(self, item, where):
        errors = []
        allowed = {"chain", "resi", "resn", "icode", "label"}
        extra = sorted(set(item) - allowed)
        if extra:
            errors.append(f"{where} has unexpected key(s) {', '.join(extra)}")
        chain = item.get("chain")
        if not isinstance(chain, str) or len(chain) > 8 or any(c.isspace() for c in chain):
            errors.append(f"{where}.chain must be a chain ID string (up to 8 characters, no spaces)")
        resi = item.get("resi")
        if isinstance(resi, bool) or not isinstance(resi, int):
            errors.append(f"{where}.resi must be an integer residue number")
        resn = item.get("resn")
        if not isinstance(resn, str) or not resn or len(resn) > 8 or not resn.isalnum():
            errors.append(f"{where}.resn must be a residue name such as HIS")
        icode = item.get("icode", "")
        if not isinstance(icode, str) or len(icode) > 1:
            errors.append(f"{where}.icode must be a single insertion-code character")
        return errors

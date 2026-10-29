"""
Molecule display (``type: molecule``).

Draws a small molecule from a SMILES string or a molfile and lets the
annotator select atoms, by clicking them in the drawing or in the atom list
under it (which also works from the keyboard). Pair it with a
``viewer_selection`` scheme to store the selection ("mark the reactive
site", "mark the atoms the recogniser got wrong").

The item field holds the structure inline (a SMILES string or molfile text)
or names a ``.mol``, ``.sdf`` (first record) or ``.smi`` file in the media
directory, which the server reads (size-limited) and sends inline.

Atom indices
------------

A selection item is ``{"atom": i, "element": "O"}``. ``i`` is the 0-based
position of the atom in the source **as written**: the order of atoms in the
SMILES string (bracketed hydrogens such as ``[H]`` count), or the order of
the molfile's atom block (molfile atom number = ``i + 1``). That is RDKit's
atom index for the same input read with ``removeHs=False``, and it does not
depend on which toolkit draws the picture. The page shows atoms by element
and molfile number ("O4").

Engines:

* ``openchemlib`` (default): OpenChemLib JS 9.25.0, BSD-3-Clause, committed.
* ``rdkit``: RDKit.js MinimalLib 2026.03.6, BSD-3-Clause, about 7 MB, fetched
  with ``potato vendor fetch rdkit``.

Neither needs WebGL. OpenChemLib folds bracketed hydrogens of a SMILES into
their neighbour, so with ``engine: openchemlib`` those hydrogens cannot be
selected and the display says so; give a molfile, or use ``engine: rdkit``.

Browser API (besides the shared ``getSelection`` / ``setSelection`` /
``onSelectionChange`` / ``describe``), on ``window.potatoViewers[field]``:
``atoms()`` lists ``{atom, element, number, x, y}``; ``highlightAtoms(list,
colour)`` draws a temporary highlight (an empty list clears it);
``onAtomHover(cb)`` reports the atom under the pointer or focus (or null).
"""

from __future__ import annotations

import html
import logging
from typing import Any, Dict, List

from .viewer_display import (ViewerAsset, ViewerDataError, ViewerDisplay,
                             ViewerEngine, resolve_source)

logger = logging.getLogger(__name__)

FORMATS = ("auto", "smiles", "molfile")


class MoleculeDisplay(ViewerDisplay):
    name = "molecule"
    description = "Small molecule from SMILES or molfile, with atom selection"
    required_fields = ["key"]
    optional_fields = {
        **ViewerDisplay.COMMON_OPTIONS,
        "engine": "openchemlib",
        "height": 320,
        "format": "auto",
        "show_atom_numbers": False,
        "atom_list": True,
        "highlight_field": None,
        "highlight_color": "#f59f00",
        "max_atoms": 500,
    }
    default_engine = "openchemlib"
    # The library loads through the adapter (an ES module for OpenChemLib, a
    # WebAssembly module for RDKit), so the framework itself loads nothing.
    engines = {
        "openchemlib": ViewerEngine(name="openchemlib", label="OpenChemLib",
                                    webgl=None, licence="BSD-3-Clause"),
        "rdkit": ViewerEngine(
            name="rdkit", label="RDKit.js", webgl=None, licence="BSD-3-Clause",
            assets=(ViewerAsset("script", "dist/RDKit_minimal.js", bundle="rdkit"),)),
    }
    selection_context = ()

    # -- options ----------------------------------------------------------------

    def validate_options(self, options: Dict[str, Any], path: str) -> List[str]:
        errors = []
        if options.get("format") not in FORMATS:
            errors.append(f"{path}.format must be one of {', '.join(FORMATS)}")
        for key in ("show_atom_numbers", "atom_list"):
            if not isinstance(options.get(key), bool):
                errors.append(f"{path}.{key} must be true or false")
        field = options.get("highlight_field")
        if field is not None and (not isinstance(field, str) or not field.strip()):
            errors.append(f"{path}.highlight_field must name an item field holding atom indices")
        colour = options.get("highlight_color")
        if not (isinstance(colour, str) and colour.startswith("#") and len(colour) in (4, 7)
                and all(c in "0123456789abcdefABCDEF" for c in colour[1:])):
            errors.append(f"{path}.highlight_color must be a hex colour such as #f59f00")
        limit = options.get("max_atoms")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 5000:
            errors.append(f"{path}.max_atoms must be a whole number from 1 to 5000")
        return errors

    # -- rendering ----------------------------------------------------------------

    def _structure_text(self, data: Any, options: Dict[str, Any]) -> str:
        from potato.chemistry import structures
        if isinstance(data, dict):
            raise ViewerDataError("A molecule field holds a SMILES string, a molfile, "
                                  "or a .mol/.sdf/.smi file name, not a mapping.")
        if structures.is_structure_path(data):
            _url, path = resolve_source(data, False, "structure file")
            try:
                return structures.read_structure_file(path)
            except (OSError, ValueError) as e:
                raise ViewerDataError(f"The structure file could not be read: {e}")
        text = data if isinstance(data, str) else ("" if data is None else str(data))
        problem = structures.check_structure_text(text)
        if problem:
            raise ViewerDataError(f"This item's molecule cannot be shown: {problem}.")
        return text if structures.looks_like_molfile(text) else text.strip()

    def client_config(self, field_config, data, options):
        from potato import chemistry
        from potato.chemistry import structures
        text = self._structure_text(data, options)
        fmt = structures.detect_format(text, options.get("format") or "auto")
        engine = options.get("engine") or self.default_engine
        cfg = {
            "source": text,
            "format": fmt,
            "showAtomNumbers": bool(options.get("show_atom_numbers")),
            "atomList": bool(options.get("atom_list", True)),
            "highlightField": options.get("highlight_field") or None,
            "highlightColor": options.get("highlight_color") or "#f59f00",
            "maxAtoms": int(options.get("max_atoms") or chemistry.DEFAULT_MAX_ATOMS),
            "oclUrl": chemistry.ocl_url(),
        }
        if engine == "rdkit":
            from potato import vendoring
            cfg["rdkitWasm"] = vendoring.static_url(chemistry.RDKIT_BUNDLE, chemistry.RDKIT_WASM)
        return cfg

    def render_extras(self, field_config, data, options, cfg) -> str:
        if not cfg.get("atomList"):
            return ""
        dom_id = self.field_id(field_config)
        return (f'<div class="mv-atoms" aria-labelledby="{dom_id}-atoms-title">'
                f'<div class="mv-atoms-head"><span class="mv-atoms-title" id="{dom_id}-atoms-title">'
                f'Atoms</span><span class="mv-atoms-hint">Click an atom in the drawing or here '
                f'to select it. From the keyboard: Tab to the list, arrow keys to move, '
                f'Space to select.</span></div>'
                f'<div class="mv-atom-strip" role="group" aria-labelledby="{dom_id}-atoms-title">'
                f'</div></div>')

    # -- selection shape -----------------------------------------------------------

    def validate_item(self, item, where):
        errors = []
        extra = sorted(set(item) - {"atom", "element", "label"})
        if extra:
            errors.append(f"{where} has unexpected key(s) {', '.join(extra)}")
        atom = item.get("atom")
        if isinstance(atom, bool) or not isinstance(atom, int) or atom < 0:
            errors.append(f"{where}.atom must be a 0-based atom index")
        element = item.get("element")
        if element is not None and (not isinstance(element, str) or not 1 <= len(element) <= 3
                                    or not element[0].isalpha()):
            errors.append(f"{where}.element must be an element symbol such as O")
        return errors


def describe_atom(item: Dict[str, Any]) -> str:
    """``O4`` for ``{"atom": 3, "element": "O"}`` (element + molfile number)."""
    return f"{html.escape(str(item.get('element') or '?'))}{int(item.get('atom', 0)) + 1}"

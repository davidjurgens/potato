"""
Chemistry support: the ``chemical_structure`` scheme and the ``molecule``
display.

Two browser toolkits:

* **OpenChemLib JS** 9.25.0 (BSD-3-Clause), committed under
  ``potato/static/vendor/openchemlib-9.25.0/``. It provides the structure
  editor, SMILES and molfile parsing and writing, the canonical SMILES and
  the OpenChemLib ID code, the molecular formula, valence checks and the
  default depiction. Everything works with it alone.
* **RDKit.js MinimalLib** 2026.03.6 (BSD-3-Clause), a 7 MB WebAssembly build
  that is fetched, not committed: ``potato vendor fetch rdkit``. With it the
  browser also computes the RDKit canonical SMILES, InChI and InChIKey,
  reports structures RDKit cannot sanitize, and the ``molecule`` display can
  draw with RDKit (``engine: rdkit``).

On the server, the optional ``rdkit`` Python package (``pip install
"potato-annotation[chemistry]"``) grades answer keys (gold items, training
answers, a scheme's ``answer_field``) and fills InChI, InChIKey and RDKit
SMILES into the export when the browser did not compute them. Answer keys
never go to the browser. Nothing here imports RDKit at module level.
"""

from __future__ import annotations

from typing import Optional

#: The committed OpenChemLib build (an ES module).
OCL_VERSION = "9.25.0"
OCL_STATIC_PATH = f"vendor/openchemlib-{OCL_VERSION}/openchemlib.js"

#: The fetchable RDKit.js bundle (potato/vendoring/manifest.py).
RDKIT_BUNDLE = "rdkit"
RDKIT_JS = "dist/RDKit_minimal.js"
RDKIT_WASM = "dist/RDKit_minimal.wasm"

#: The pip extra that brings the RDKit Python package.
PY_EXTRA_HINT = 'pip install "potato-annotation[chemistry]"'

#: Largest structure text (SMILES or molfile) read from an item or a file.
MAX_STRUCTURE_BYTES = 1_000_000
#: Largest molecule drawn by the molecule display.
DEFAULT_MAX_ATOMS = 500


def ocl_url() -> str:
    return "/static/" + OCL_STATIC_PATH


def rdkit_bundle_installed() -> bool:
    from potato import vendoring
    return vendoring.is_installed(RDKIT_BUNDLE)


def rdkit_urls() -> Optional[dict]:
    """``{"js": ..., "wasm": ...}`` when the RDKit.js bundle is installed."""
    if not rdkit_bundle_installed():
        return None
    from potato import vendoring
    return {"js": vendoring.static_url(RDKIT_BUNDLE, RDKIT_JS),
            "wasm": vendoring.static_url(RDKIT_BUNDLE, RDKIT_WASM)}


def rdkit_python():
    """The ``rdkit.Chem`` module, or None when the package is not installed."""
    try:
        from rdkit import Chem, RDLogger  # noqa: F401
    except ImportError:
        return None
    RDLogger.DisableLog("rdApp.*")
    return Chem

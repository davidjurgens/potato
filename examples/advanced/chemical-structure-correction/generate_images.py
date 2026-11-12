#!/usr/bin/env python3
"""
Render the source images for the chemical-structure-correction example.

Each image is a 2D drawing of the item's true structure, made with RDKit so
the example needs no copied figures. The recognised SMILES in
data/structures.json are hand-edited from the true ones to imitate optical
structure recognition errors (a wrong element, a lost group, flipped
stereo). Needs the rdkit package: pip install "potato-annotation[chemistry]".

    python examples/advanced/chemical-structure-correction/generate_images.py
"""

import json
import os

from rdkit import Chem
from rdkit.Chem.Draw import rdMolDraw2D

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    with open(os.path.join(HERE, "data", "structures.json"), encoding="utf-8") as f:
        items = json.load(f)
    os.makedirs(os.path.join(HERE, "media"), exist_ok=True)
    for item in items:
        mol = Chem.MolFromSmiles(item["true_smiles"])
        drawer = rdMolDraw2D.MolDraw2DCairo(420, 300)
        opts = drawer.drawOptions()
        opts.addStereoAnnotation = False
        opts.bondLineWidth = 2
        opts.fixedFontSize = 20
        opts.padding = 0.12
        drawer.DrawMolecule(mol)
        drawer.FinishDrawing()
        out = os.path.join(HERE, "media", item["page_image"])
        with open(out, "wb") as f:
            f.write(drawer.GetDrawingText())
        print("wrote", os.path.relpath(out, HERE))


if __name__ == "__main__":
    main()

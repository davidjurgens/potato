# Chemical structures

Two pieces cover small molecules:

- The `chemical_structure` annotation scheme gives the annotator a structure editor. They draw a structure, or correct one the item supplies: the output of optical structure recognition (OCSR) shown beside the source image, or a structure to check against a compound name. The answer is stored as a molfile V3000 with its canonical SMILES and, when RDKit.js is installed, its InChIKey.
- The `molecule` display draws a structure from a SMILES string or a molfile and lets the annotator select atoms, by clicking them in the drawing or in an atom list under it. Pair it with a `viewer_selection` scheme to store the selection ("mark the reactive site", "mark the atoms the recogniser got wrong").

## Overview

- **Editor:** OpenChemLib JS 9.25.0 (BSD-3-Clause), committed with Potato under `potato/static/vendor/openchemlib-9.25.0/`. It draws and edits on a canvas with a toolbar (bonds, rings, elements, charges, stereo wedges, erase, undo). A text box under it takes a pasted or typed SMILES string or molfile, which is also the keyboard route into the editor.
- **RDKit.js (optional):** RDKit's MinimalLib 2026.03.6 (BSD-3-Clause) is a 7 MB WebAssembly build, so it is not committed. Install it with `potato vendor fetch rdkit`. With it, the browser also computes the RDKit canonical SMILES, the InChI and the InChIKey, flags structures RDKit cannot sanitize, and the `molecule` display can draw with RDKit (`engine: rdkit`). Without it everything else works with OpenChemLib, and `potato validate` names the fetch command.
- **Answer keys (optional):** gold items, training answers and a scheme's `answer_field` are graded on the server with the `rdkit` Python package (`pip install "potato-annotation[chemistry]"`). Answer keys never go to the browser. The same package fills InChI and InChIKey into the export when the browser did not compute them.
- **No WebGL needed.** Both toolkits draw in 2D.

## Configuration

### Correcting a recognised structure

```yaml
media_directory: media

instance_display:
  layout:
    direction: horizontal
  fields:
    - key: page_image              # the figure from the source document
      type: image
      label: "Source image"
    - key: recognised_smiles       # what the recogniser produced
      type: molecule
      label: "Recognised structure"

annotation_schemes:
  - annotation_type: viewer_selection
    name: wrong_atoms
    description: "Mark the atoms the recogniser got wrong"
    viewer_field: recognised_smiles
    labels: ["wrong element", "wrong bond or charge", "wrong stereo"]

  - annotation_type: chemical_structure
    name: corrected
    description: "Correct the structure so it matches the source image"
    prefill_field: recognised_smiles
    answer_field: true_smiles      # graded in the export; never sent to the page
    label_requirement:
      required: true
```

```json
{"id": "fig1", "page_image": "fig1.png", "recognised_smiles": "CC(=O)Oc1ccccc1C(=O)N", "true_smiles": "CC(=O)Oc1ccccc1C(=O)O"}
```

### Drawing a structure from a name

```yaml
item_properties:
  id_key: id
  text_key: name                   # "2-acetoxybenzoic acid"

annotation_schemes:
  - annotation_type: chemical_structure
    name: drawn
    description: "Draw the structure this name describes"
    label_requirement:
      required: true
```

### chemical_structure options

| Option | Default | Description |
|---|---|---|
| `prefill_field` | none | Item field with a SMILES string or a molfile (or the name of a `.mol`, `.sdf` or `.smi` file in the media directory) the editor starts from |
| `prefill_format` | `auto` | `auto`, `smiles` or `molfile` |
| `answer_field` | none | Item field with an answer key (below). Removed from everything the page receives; graded in the `chemistry` export |
| `rdkit` | `auto` | `auto`: use RDKit.js when it is installed. `true`: require it (`potato validate` and server start fail without it). `false`: OpenChemLib only, and no warning |
| `require_valid` | `true` | A structure with a valence problem (or, with RDKit.js, one RDKit cannot sanitize) leaves the item incomplete. Enforced when the scheme is required (`label_requirement: {required: true}`) |
| `allow_empty` | `false` | An empty canvas is an acceptable answer |
| `editor_height` | `380` | Editor height in pixels, 240 to 900 |
| `show_identifiers` | `true` | Show SMILES, formula and InChIKey under the editor |
| `instructions` | none | Text under the question |

A pre-filled structure that the annotator leaves as it is becomes the saved answer, with `changed: false`, so a correct recognition needs no edit. Record the annotator's verdict with a separate question (a `radio` such as "Correct / Minor errors / Wrong structure") when you need to tell "looked at and accepted" from "skipped". **Restore the given structure** puts the pre-filled structure back.

### molecule display options

Options can be written under `display_options` or directly on the field.

| Option | Default | Description |
|---|---|---|
| `engine` | `openchemlib` | `openchemlib` or `rdkit` (after `potato vendor fetch rdkit`) |
| `height` | `320` | Height of the drawing: a number of pixels or a CSS length |
| `format` | `auto` | `auto`, `smiles` or `molfile` |
| `show_atom_numbers` | `false` | Draw each atom's molfile number beside it |
| `atom_list` | `true` | The list of atom buttons under the drawing (the keyboard route) |
| `highlight_field` | none | Item field with a list of 0-based atom indices drawn with a fixed highlight, for example a model's predicted site |
| `highlight_color` | `#f59f00` | Colour of those highlights |
| `max_atoms` | `500` | Larger molecules are not drawn; the display says so |

The item field holds the structure inline (a SMILES string or molfile text) or the name of a `.mol`, `.sdf` (first record) or `.smi` file in the media directory. The server reads the file (up to 1 MB) and sends its text to the page.

## Using the editor

- **Draw a bond:** click on an empty part of the canvas (a C–C bond), or drag from an atom to add a bond to a new atom. The toolbar on the left picks the bond type, a ring, an element or a charge first.
- **Change an element:** point at an atom and type its symbol (`o`, `n`, `s`, `c`, ...). The element buttons in the toolbar do the same with the mouse.
- **Erase and undo:** the toolbar has an eraser and an undo button.
- **Paste:** type or paste a SMILES string or a molfile in the text box and press **Load** (or Enter for a SMILES). Text OpenChemLib cannot read is refused and the drawing is kept.
- **Clear** empties the canvas.

Under the editor, the SMILES, formula and (with RDKit.js) InChIKey update as you draw. Valence problems ("C (atom 2) has 5 bonds; it allows 4.") are listed there and, with `require_valid`, keep the item from being submitted.

## Selecting atoms

Click an atom in the drawing to select it, click it again to remove it. In the atom list under the drawing, Tab moves to the list, the arrow keys (or Home and End) move between atoms, and Space or Enter toggles one. With `labels` on the `viewer_selection` scheme, pick the label first; new selections take it, and each listed atom can be relabelled or removed.

Atoms are named by element and molfile number: `O4` is the fourth atom of the source.

### Atom indices

A stored atom is `{"atom": i, "element": "O"}`. `i` is the 0-based position of the atom in the source **as written**: the order of atoms in the SMILES string, or the order of the molfile's atom block (so the molfile atom number is `i + 1`). That is RDKit's atom index for the same input read with `removeHs=False`, and it does not depend on which engine draws the picture.

OpenChemLib folds hydrogens written as atoms in a SMILES (`[H]C(Cl)(Br)F`) into their neighbour, so with `engine: openchemlib` such a SMILES cannot be used for selection: the display says so and offers no atoms. Give a molfile (OpenChemLib keeps a molfile's hydrogens and their numbers), or use `engine: rdkit`. Hydrogens that are only implied (`CCO`) are never selectable; select the heavy atom, or write the hydrogens into a molfile when individual hydrogens matter (as in NMR peak assignment).

## Answer keys

An answer key is a SMILES string or a mapping:

| Key | Meaning |
|---|---|
| `smiles`, `molfile` or `inchikey` | The same structure: the drawn structure's InChIKey equals the key's |
| `ignore_stereo: true` | Compare only the first InChIKey block (connectivity), so stereo is not checked |
| `substructure` | A SMARTS pattern (or a list of them) the drawn structure must contain |
| `not_substructure` | A SMARTS pattern (or a list) it must not contain |

An `answer_field` value may be a bare SMILES string. In a gold-standard file or a training item, write the mapping form under the scheme's name:

```json
{"id": "gold_1", "gold_label": {"corrected": {"smiles": "CC(=O)Oc1ccccc1C(=O)O"}}}
{"id": "train_1", "correct_answers": {"drawn": {"substructure": "C(=O)[OH]"}}}
```

Grading runs on the server with the `rdkit` Python package. Without it, only an `inchikey` key against an answer whose InChIKey RDKit.js computed in the browser can match, and the server logs once that the package is missing. That browser InChIKey comes from the annotator's machine; when the package is installed the server recomputes it from the stored molfile instead.

## Data format

The `chemical_structure` answer is one JSON object:

```json
{"molfile": "\nOCL MolfileCreator  2D\n\n  0  0  0 ... V3000\n...M  END\n",
 "smiles": "CC(Oc1ccccc1C(O)=O)=O",
 "idcode": "dklB@@QmR[fUxUZBBF@@",
 "formula": "C9H8O4",
 "rdkit_smiles": "CC(=O)Oc1ccccc1C(=O)O",
 "inchi": "InChI=1S/C9H8O4/c1-6(10)13-8-5-3-2-4-7(8)9(11)12/h2-5H,1H3,(H,11,12)",
 "inchikey": "BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
 "changed": true,
 "problems": [],
 "toolkits": {"openchemlib": "9.25.0", "rdkit": "2026.03.6"}}
```

`smiles` is OpenChemLib's canonical isomeric SMILES and `idcode` its canonical ID code; `rdkit_smiles`, `inchi` and `inchikey` are present only when RDKit.js ran. Canonical SMILES differ between toolkits, so compare structures across annotators by InChIKey or ID code, not by `smiles` against `rdkit_smiles`.

A `viewer_selection` on a molecule display stores:

```json
{"viewer": "molecule", "items": [{"atom": 12, "element": "N", "label": "wrong element"}]}
```

## Export

```bash
python -m potato.export --config config.yaml --format chemistry --output ./export/
```

writes `chemical_structures.csv` (one row per answer, with the answer-key result when the scheme has an `answer_field`), `chemical_structures.sdf` (each molfile with the row's fields as SD properties) and `molecule_atoms.csv` (one row per selected atom). The `identifiers_from` column says whether InChI and InChIKey came from the browser, from the server's `rdkit` package, or are missing. See [Export formats](../../data-export/export_formats.md).

## Browser API

Each molecule display registers `window.potatoViewers[field]` with the shared viewer API (`getSelection()`, `setSelection(sel)`, `onSelectionChange(cb)`, `describe(sel)`) and three more calls, for a display linked to atoms (such as a spectrum whose peaks are assigned to atoms):

- `atoms()` returns `[{atom, element, number, x, y}]`, with `x`, `y` in the drawing's coordinates.
- `highlightAtoms(list, colour)` draws a temporary highlight on those atom indices; `highlightAtoms([])` clears it.
- `onAtomHover(cb)` calls `cb(atomIndex)` when the pointer or keyboard focus reaches an atom, and `cb(null)` when it leaves; it returns an unsubscribe function.

## Troubleshooting

- **"RDKit.js is not installed" from `potato validate`:** run `potato vendor fetch rdkit`, or set `rdkit: false` on the scheme to run with OpenChemLib only. With `rdkit: true` it is an error rather than a warning. Restart the server after fetching.
- **The InChIKey column says "needs RDKit.js":** the bundle is not installed. Install it, or install the `rdkit` Python package so the export fills it in.
- **The molecule display offers no atoms:** the SMILES writes hydrogens as atoms; see [Atom indices](#atom-indices).
- **"This item's molecule cannot be shown":** the field holds text that is neither a molfile nor a single SMILES string (a SMILES has no spaces), or names a file outside the media directory.
- **The editor is empty on a training page:** the editor reads `prefill_field` from the current item's data, which the page fetches only in the annotation phase.
- **Answer keys are all graded wrong:** check the server log for the missing `rdkit` package message, and check that the gold or training answer uses the mapping form (`{"smiles": ...}`), not a bare string.

## Related

- [Chemistry guide](../../guides/chemistry.md): structure correction, name to structure, atom marking
- [Protein structures](protein_structures.md) and [Genome loci](genome_loci.md): the other viewer displays
- [Quality control](../../workflow/quality_control.md) for gold items, [Training phase](../../workflow/training_phase.md)
- Example: `examples/advanced/chemical-structure-correction/`

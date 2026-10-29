# Chemistry: structure correction, name to structure and atom marking

This guide sets up three common chemistry tasks with the [`chemical_structure` scheme and the `molecule` display](../annotation-types/science/chemical_structures.md):

1. checking and correcting structures produced by optical structure recognition (OCSR),
2. drawing the structure a compound name describes,
3. marking atoms on a structure (a reactive site, a pharmacophore, the atoms a model got wrong).

The runnable example is `examples/advanced/chemical-structure-correction/`:

```bash
python potato/flask_server.py start examples/advanced/chemical-structure-correction/config.yaml -p 8000
```

## Optional installs

Everything below runs with what Potato ships: the OpenChemLib editor and drawing. Two optional installs add more:

```bash
# RDKit.js in the browser: InChI and InChIKey, RDKit checks, engine: rdkit
potato vendor fetch rdkit

# The rdkit Python package on the server: grading answer keys,
# InChIKeys in the export when the browser had no RDKit.js
pip install "potato-annotation[chemistry]"
```

`potato validate` warns while RDKit.js is missing and names the fetch command. Restart the server after fetching.

## Preparing data

Each item needs the structure as a SMILES string or a molfile, inline or as a `.mol`, `.sdf` or `.smi` file in the media directory:

```json
{"id": "fig1", "page_image": "fig1.png",
 "recognised_smiles": "CC(=O)Oc1ccccc1C(=O)N",
 "true_smiles": "CC(=O)Oc1ccccc1C(=O)O"}
```

- Use a molfile when atom numbers matter outside Potato (they are the molfile's own numbers) or when individual hydrogens must be selectable.
- Keep known answers in their own field and name it in `answer_field`; the page never receives it.
- For OCSR, crop each figure to one structure and put the images in the media directory. The example's images are drawn from its SMILES by `generate_images.py`.

## Task 1: correcting OCSR output

The annotator sees the source image beside the recognised structure, marks the atoms that were misread, corrects the structure in the editor (which starts from the recognised SMILES), and gives a verdict:

```yaml
instance_display:
  layout:
    direction: horizontal
  fields:
    - key: page_image
      type: image
      label: "Source image"
    - key: recognised_smiles
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
    answer_field: true_smiles
    label_requirement:
      required: true

  - annotation_type: radio
    name: verdict
    description: "How good was the recognition?"
    labels: ["Correct", "Minor errors", "Wrong structure"]
    label_requirement:
      required: true
```

An untouched structure is saved with `changed: false`, so "the recognition was right" needs no edit. The verdict question separates that from an item the annotator did not check.

In the export, `answer_correct` says whether each corrected structure matches `true_smiles`, and `changed` whether the annotator edited it. Comparing the two finds both missed errors (unchanged and wrong) and introduced ones (changed and wrong).

## Task 2: name to structure

```yaml
item_properties:
  id_key: id
  text_key: name

annotation_schemes:
  - annotation_type: chemical_structure
    name: drawn
    description: "Draw the structure this name describes"
    answer_field: expected_smiles
    rdkit: auto
    label_requirement:
      required: true
```

Annotators can draw with the mouse or type a SMILES string into the text box and press Enter. To accept any correct stereo assignment, give the key as `{"smiles": "...", "ignore_stereo": true}`. To check only a feature of the answer (that the drawn structure has a carboxylic acid, say), use `{"substructure": "C(=O)[OH]"}`.

For a qualification step, put such keys in a training file (`correct_answers: {drawn: {smiles: ...}}`) or a gold-standard file (`gold_label: {drawn: {smiles: ...}}`). Both are graded on the server and need the `rdkit` Python package; see [Answer keys](../annotation-types/science/chemical_structures.md#answer-keys).

## Task 3: marking atoms

```yaml
instance_display:
  fields:
    - key: smiles
      type: molecule
      display_options:
        show_atom_numbers: true
        highlight_field: predicted_site     # optional: a model's atoms, drawn in amber

annotation_schemes:
  - annotation_type: viewer_selection
    name: reactive_site
    description: "Mark the atoms of the reactive site"
    viewer_field: smiles
    labels: ["electrophile", "nucleophile", "leaving group"]
    min_selections: 1
```

Annotators click atoms in the drawing, or Tab into the atom list and use the arrow keys and Space. Each stored atom is `{"atom": i, "element": "C", "label": "..."}` with `i` the 0-based position in the SMILES or molfile as written. `molecule_atoms.csv` in the `chemistry` export lists them one per row with the molfile number beside the index.

If the SMILES writes hydrogens as atoms (`[H]`), use `engine: rdkit` or a molfile; see [Atom indices](../annotation-types/science/chemical_structures.md#atom-indices).

## Agreement and export

```bash
python -m potato.export --config config.yaml --format chemistry --output ./export/
```

Compare structures between annotators by `inchikey` (or `idcode` when RDKit was not available anywhere). The SMILES columns are canonical within one toolkit only. The SD file reads with RDKit's `SDMolSupplier` (and other SD readers), with each row's fields as properties.

## Related

- [Chemical structures](../annotation-types/science/chemical_structures.md): every option, the data format and the browser API
- [Spectra and peak picking](../annotation-types/science/spectra.md): NMR, IR and mass spectra, peak lists and integrals
- [Structural biology](structural-biology.md): residue marking on protein structures
- [Quality control](../workflow/quality_control.md) and [Training phase](../workflow/training_phase.md)
- [Export formats](../data-export/export_formats.md)

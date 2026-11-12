# Protein structures

The `protein_structure` display shows a macromolecular structure in the browser and lets annotators select residues, either by clicking them in the 3D view or in a residue table under it. Pair it with a `viewer_selection` annotation scheme to store the selection: a binding site, an epitope, a disordered region, residues at an interface.

The display draws a cartoon, shows ligands as sticks (single-atom ions as spheres), and draws each selected residue as sticks in its label's colour. It can colour the cartoon by model confidence (pLDDT) and show a PAE image beside the structure.

## Overview

- **Formats:** mmCIF (`.cif`, `.mmcif`), BinaryCIF (`.bcif`) and PDB (`.pdb`, `.ent`), each optionally gzipped (`.gz`). mmCIF is the main format: from 2027-07-21 new PDB entries get 12-character IDs and are distributed as mmCIF only, so plan new projects around mmCIF files. The server reads BinaryCIF only when the `msgpack` package is installed (`pip install msgpack`); without it the residue table is unavailable, but the 3D view still works.
- **Engines:** `3dmol` (the default) uses 3Dmol.js 2.5.5 (BSD-3-Clause), which is committed with Potato. `molstar` uses Mol* 5.12.0 (MIT). Mol* is about 5 MB, so it is not committed; install it with `potato vendor fetch molstar`. Both need WebGL.
- **Without WebGL** the 3D view shows a message saying WebGL is off or unsupported, and the residue table still works. The 3D library is not downloaded in that case.
- **Residue table:** one row of residue buttons per chain, rendered by the server from the structure file. It is the keyboard route to a selection: Tab moves to a chain, the arrow keys move between residues, Home and End jump to the ends, Space or Enter toggles the residue. Water is left out.
- **Offline by default:** a structure is read from the media directory. A URL (an AlphaFold DB or RCSB file) is loaded only when the display sets `allow_remote: true`, and then the annotator's browser fetches it; the Potato server makes no outbound request.

## Configuration

```yaml
media_directory: media

instance_display:
  fields:
    - key: structure            # item field holding the file path
      type: protein_structure
      label: "Structure"
      display_options:
        engine: 3dmol
        height: 440
        plddt: true             # colour by B-factor read as pLDDT
        pae_field: pae          # item field holding a PAE image

annotation_schemes:
  - annotation_type: viewer_selection
    name: binding_site
    description: "Select the residues that form the binding site"
    viewer_field: structure
    labels: ["zinc ligand", "interface"]
    min_selections: 1
    max_selections: 12
    label_requirement:
      required: true
```

Each item names its structure file relative to `media_directory`:

```json
{"id": "model_1", "note": "...", "structure": "structures/model_1.cif", "pae": "structures/model_1_pae.png"}
```

### Display options

Options can be written under `display_options` or directly on the field.

| Option | Default | Description |
|---|---|---|
| `engine` | `3dmol` | `3dmol` or `molstar` (after `potato vendor fetch molstar`) |
| `height` | `420` | Height of the 3D view: a number of pixels or a CSS length |
| `format` | from the extension | `cif`, `bcif` or `pdb`, for a file whose name does not say |
| `color_by` | `chain` | `chain`, `spectrum` (N- to C-terminus) or `secondary` (secondary structure). Ignored when `plddt` is on |
| `plddt` | `false` | Colour the cartoon by the B-factor column read as pLDDT, in the four AlphaFold bands (below). Values written as 0-1 are detected and scaled |
| `pae_field` | none | An item field holding an image (for example a PAE plot) shown beside the structure |
| `show_ligands` | `true` | Draw HETATM groups other than water |
| `residue_table` | `true` | Show the residue table |
| `residue_table_limit` | `3000` | Above this many residues the table is replaced by a note and residues are selected in the 3D view |
| `allow_remote` | `false` | Let the browser load an http(s) URL named in the item |

### pLDDT colours

| Band | Colour |
|---|---|
| Very high: pLDDT > 90 | dark blue `#0053D6` |
| Confident: 90 ≥ pLDDT > 70 | light blue `#65CBF3` |
| Low: 70 ≥ pLDDT > 50 | yellow `#FFDB13` |
| Very low: pLDDT ≤ 50 | orange `#FF7D45` |

A legend is shown under the view, and each residue button in the table carries its band as a coloured bar. With `engine: molstar`, pLDDT colouring uses Mol*'s confidence theme, which reads the `ma_qa_metric_local` table that AlphaFold DB mmCIF files carry, not the B-factor column.

### viewer_selection options

| Option | Default | Description |
|---|---|---|
| `viewer_field` | required | The `instance_display` field key of the viewer |
| `labels` | none | Names for selections. The annotator picks a label first and new selections take it; each listed selection can be relabelled. A label can be `{name, color}` |
| `min_selections` | none | The item is incomplete until this many residues are selected. Enforced when the scheme is required (`label_requirement: {required: true}`) |
| `max_selections` | none | Selecting more is refused, with a message |
| `instructions` | none | Text under the question |

## Selecting residues

- **Click** a residue in the 3D view or in the residue table to select it; click it again to remove it. Hovering in the 3D view shows the residue (and its pLDDT) under the view.
- **Keyboard:** Tab to a chain in the residue table, use the arrow keys to move, Space to toggle. The label buttons are a radio group: arrow keys change the label for new selections.
- **The list** under the question shows each selection, with a menu to change its label and a Remove button.

Selections are restored when the annotator comes back to an item: the 3D view, the table and the list all show the saved state.

## Data format

The `viewer_selection` answer is stored as JSON under the scheme's name:

```json
{"viewer": "protein_structure",
 "items": [{"chain": "A", "resi": 8, "resn": "HIS", "label": "zinc ligand"},
           {"chain": "B", "resi": 3, "resn": "LYS", "label": "interface"}]}
```

`chain` and `resi` are the file's `auth_asym_id` and `auth_seq_id` (for PDB files, the chain and residue number columns), which is what 3Dmol.js and Mol* display. A residue with an insertion code adds `"icode": "A"`.

The server stores this JSON as the browser sends it. Neither saving nor exporting checks it. To check stored answers, call `potato.server_utils.displays.viewer_display.validate_selection("protein_structure", value)`, which returns a list of problems (empty when the answer is well formed).

There is no export format made for `viewer_selection`. The JSON above is the scheme's value in the `jsonl`, `csv` and `tsv` exports.

## Browser API

Every viewer display registers a small API, which `viewer_selection` uses and which page scripts can use too:

```javascript
const v = window.potatoViewers["structure"];   // the field key
v.getSelection();                // {viewer, items: [...]}
v.setSelection({items: [{chain: "A", resi: 57, resn: "HIS"}]});
const stop = v.onSelectionChange((sel, info) => console.log(info.source, sel));
v.describe({chain: "A", resi: 57, resn: "HIS"});   // "HIS 57, chain A"
```

`info.source` is `"user"` for a click in the viewer or the table and `"api"` for `setSelection`.

## Mol*

```bash
potato vendor fetch molstar
```

The bundle is pinned to Mol* 5.12.0 and checked against recorded SHA-256 hashes before it is installed. It goes in `potato/vendor_fetched/`, or under `$POTATO_VENDOR_DIR` when that is set. A config with `engine: molstar` fails `potato validate` and server start until the bundle is installed, and the error names the command. With Mol*, selected residues are shown with Mol*'s selection highlight rather than as sticks.

## AlphaFold DB and RCSB files

To load a prediction or an entry directly from its URL, set `allow_remote: true` and put the URL in the item. The browser fetches the file, so the annotators' machines need access to that host. The residue table is then built in the browser from the loaded model (3Dmol.js engine only). For offline or air-gapped studies, download the files into the media directory instead.

AlphaFold DB predictions are released under CC-BY-4.0, so a study that redistributes them, or figures made from them, must give attribution.

## Troubleshooting

- **"needs WebGL, which this browser has turned off or does not support"**: hardware acceleration is off, the GPU is blocklisted, or the browser runs in a virtual machine without GPU support. Annotators can still select residues in the residue table.
- **"is not in the media directory"**: the path in the item does not resolve under `media_directory`. Name files relative to it.
- **"remote files are turned off"**: the item holds a URL and `allow_remote` is not set.
- **"The residue table is unavailable"**: the server could not read the file (for example a BinaryCIF file without the `msgpack` package installed). The 3D view still loads and selection in it works.
- **"larger than 200 MB once decompressed"**: the server reads at most 200 MB of a structure file, after decompressing a `.gz` file, and stops there, so a small `.gz` file that expands to gigabytes costs the server at most 200 MB. The residue table is left out, and the 3D view still loads in the browser. The limit is `MAX_STRUCTURE_BYTES` in `potato/media/structures.py`; raise it there for larger structures.
- **`potato vendor fetch molstar` in a validate error**: the config uses `engine: molstar` and the bundle is not installed.

## Related

- [Structural biology guide](../../guides/structural-biology.md)
- [Genome loci](genome_loci.md)
- [Instance display](../instance_display.md)
- Example: `examples/advanced/protein-binding-site/`

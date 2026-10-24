# Structural Biology: Marking Residues on Structures

This guide covers studies where annotators mark residues on protein structures: binding sites, epitopes, interface residues, regions they judge disordered, or residues where a predicted model looks wrong. The structure is shown in a [`protein_structure`](../annotation-types/science/protein_structures.md) display and the residues are stored by a `viewer_selection` scheme. Other questions about the item (a rating, a free-text note) go in ordinary schemes beside it.

## Preparing structures

Put the files under the project's `media/` folder and name them in the data file relative to it.

- **mmCIF first.** From 2027-07-21 new PDB entries get 12-character IDs and are distributed as mmCIF only, and AlphaFold DB distributes mmCIF too. Use `.cif` (or `.bcif`, or either gzipped) for new projects; `.pdb` still works for older files and tool output.
- **Chains and numbers** in the stored selection are the file's author fields (`auth_asym_id`, `auth_seq_id`), the numbering 3Dmol.js and Mol* display. If your downstream analysis uses `label_seq_id` numbering, map it after export.
- **One model per file.** Only the first model of a multi-model file is read. Split NMR ensembles or prediction batches into one file per item.
- **Predicted models.** AlphaFold, ColabFold and similar tools write pLDDT into the B-factor column; set `plddt: true` to colour by it. A PAE plot saved as an image can be shown beside the structure with `pae_field`.

AlphaFold DB predictions are licensed CC-BY-4.0. A study that redistributes them, or publishes figures made from them, must credit the source.

## A binding-site task

```yaml
media_directory: media
data_files: [data/structures.json]
item_properties: {id_key: id, text_key: note}

instance_display:
  fields:
    - key: note
      type: text
    - key: structure
      type: protein_structure
      display_options:
        plddt: true
        pae_field: pae

annotation_schemes:
  - annotation_type: viewer_selection
    name: binding_site
    description: "Select the residues that form the binding site"
    viewer_field: structure
    labels: ["ligand contact", "interface"]
    min_selections: 1
    label_requirement: {required: true}

  - annotation_type: radio
    name: site_confidence
    description: "How clear is the site in this model?"
    labels: ["Clear", "Plausible", "Unsupported"]
```

`examples/advanced/protein-binding-site/` is a runnable version with two synthetic models:

```bash
python potato/flask_server.py start examples/advanced/protein-binding-site/config.yaml -p 8000
```

## Selecting residues

1. Pick the label for the next selections ("ligand contact", "interface").
2. Click residues in the 3D view, or in the residue table under it. Clicking again removes a residue. The table also works from the keyboard: Tab to a chain, arrow keys to move, Space to select.
3. Check the list under the question; each entry can be relabelled or removed.

On a machine without WebGL the 3D view is replaced by a message and the residue table is the way to select. If many of your annotators work on such machines, put the sequence context they need in the item note.

## Choosing an engine

| | 3Dmol.js (`engine: 3dmol`) | Mol* (`engine: molstar`) |
|---|---|---|
| Installed | committed with Potato | `potato vendor fetch molstar` (about 5 MB) |
| Licence | BSD-3-Clause | MIT |
| Selected residues | drawn as sticks in the label colour | Mol*'s selection highlight |
| pLDDT colouring | from the B-factor column | from `ma_qa_metric_local` (AlphaFold DB mmCIF files carry it) |
| Residue table for a remote URL | built from the loaded model | not available |

3Dmol.js is the default because it needs no install step. Mol* suits annotators who already work in its interface.

## Agreement and export

Each annotator's selection is stored as JSON (see [Protein structures: data format](../annotation-types/science/protein_structures.md#data-format)). To compare annotators, read the residue lists from the annotation output and compute set overlap per item (for example Jaccard over `(chain, resi)` pairs). Potato's agreement metrics compare label names, so they do not compare these residue lists.

## Related

- [Protein structures](../annotation-types/science/protein_structures.md)
- [Genome variant review](genomics-variant-review.md)

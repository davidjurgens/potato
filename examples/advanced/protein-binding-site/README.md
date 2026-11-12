# Protein binding-site residues

Annotators mark binding-site residues on two synthetic protein models in a
`protein_structure` display, with a `viewer_selection` scheme storing the
residues and a radio question for confidence.

```bash
python potato/flask_server.py start examples/advanced/protein-binding-site/config.yaml -p 8000
```

- `media/structures/*.cif` are synthetic mmCIF files: ideal backbone geometry
  with a CB atom per residue and no other side-chain atoms. The B-factor column
  holds an invented pLDDT. `zinc_site_complex.pdb` is the first model in the
  legacy PDB format.
- `media/structures/predicted_tail_model_pae.png` is a synthetic PAE image.
- `generate_structures.py` rebuilds all of them.

See [Protein structures](../../../docs/annotation-types/science/protein_structures.md).

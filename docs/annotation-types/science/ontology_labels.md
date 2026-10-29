# Ontology-backed labels

A `label_source` block on a `radio`, `multiselect`, `span` or `image_annotation`
scheme lets annotators pick labels from an ontology (Cell Ontology, GO, ChEBI,
UBERON, NCBITaxon, ENVO, or any other OBO ontology) instead of, or next to, a
fixed label list. The annotator types into a search box and picks a term. The
term is stored with its id, name, IRI and the ontology version:

```json
{"obo_id": "CL:0000236", "label": "B cell",
 "iri": "http://purl.obolibrary.org/obo/CL_0000236",
 "ontology_version": "cl/releases/2026-09-30"}
```

Terms come from one of two places:

- **`service: file`**: an OBO 1.4 file you put inside the task directory. This
  works offline and is the default choice.
- **`service: ols4`**: an [OLS4](https://www.ebi.ac.uk/ols4/) server, EBI's or
  your own. It is **off unless the scheme sets `allow_network: true`**,
  because every search sends the typed text to that server. Potato makes the
  request itself, so the annotator's browser only ever talks to Potato.

Potato does not ship any ontology file. Download the `.obo` release of the
ontology you need (for example `http://purl.obolibrary.org/obo/cl.obo`) and keep
it with your project.

## Configuration

```yaml
annotation_schemes:
  # Search only: no fixed list.
  - annotation_type: radio
    name: cell_type
    description: "Which cell type is described?"
    labels: []
    label_requirement:
      required: true
    label_source:
      ontology: cl
      service: file
      file: ontologies/cl.obo
      root: CL:0000000        # optional: only this term and its is_a descendants
      max_results: 20

  # A fixed option plus the search box.
  - annotation_type: multiselect
    name: other_cells
    description: "Which other cell types are mentioned?"
    labels: [None]
    label_source:
      ontology: cl
      service: file
      file: ontologies/cl.obo

  # Span labels from a subtree.
  - annotation_type: span
    name: cell_mentions
    description: "Highlight each cell type mention"
    labels: []
    label_source:
      ontology: cl
      service: file
      file: ontologies/cl.obo
      root: CL:0000738        # leukocyte and below

  # Image labels.
  - annotation_type: image_annotation
    name: cells_in_image
    description: "Box each cell and name its type"
    tools: [bbox, polygon]
    labels: []
    label_source:
      ontology: cl
      service: file
      file: ontologies/cl.obo
```

With `labels: []` (or no `labels` key) the search box is the only way to answer.
With a list, the fixed labels are shown as usual and the search box sits below
them; terms picked from the search are added as extra options. Fixed labels are
stored as plain label names, not as ontology terms.

OLS4:

```yaml
    label_source:
      ontology: cl                 # the OLS4 ontology id
      service: ols4
      allow_network: true          # required for ols4
      base_url: https://www.ebi.ac.uk/ols4/api   # optional, for a self-hosted OLS4
      root: CL:0000000             # optional, sent as childrenOf
      max_results: 20
      timeout_s: 5
```

### Options

| Key | Applies to | Default | Description |
|---|---|---|---|
| `ontology` | both | required | Short ontology name (`cl`, `go`). For OLS4 it is the ontology id sent to the server. Shown in the search box label. |
| `service` | both | required | `file` or `ols4`. |
| `file` | file | required | Path to an OBO 1.4 file, relative to `task_dir`. Must be inside `task_dir`. |
| `max_file_mb` | file | `300` | Files larger than this are refused at startup. |
| `root` | both | none | A term id. Only that term and the terms below it by `is_a` are offered. |
| `max_results` | both | `20` | Matches per search, 1 to 100. |
| `allow_network` | ols4 | `false` | Must be `true` for `service: ols4`. |
| `base_url` | ols4 | `https://www.ebi.ac.uk/ols4/api` | OLS4 API root. |
| `timeout_s` | ols4 | `5` | Seconds to wait for OLS4, 0.5 to 30. |

### Checked at startup

The server (and `potato validate`) refuses to start, naming the key, when:

- `service` is not `file` or `ols4`
- `label_source` is on a scheme type other than the four above
- the file is missing, outside `task_dir`, larger than `max_file_mb`, not OBO,
  or has no terms
- `root` is not a term in the file, or is obsolete
- `service: ols4` is set without `allow_network: true`
- a key is unknown, or belongs to the other service (`base_url` with `file`)

## The OBO reader

Potato reads OBO 1.4 with its own parser and needs no extra package. It reads the
`data-version`, `ontology` and `default-namespace` header tags and, in `[Term]`
stanzas, `id`, `name`, `namespace`, `synonym`, `def`, `is_a`, `alt_id` and
`is_obsolete`. Obsolete terms are left out of search and subtrees. A search for
an `alt_id` finds the primary term. `[Typedef]` stanzas and `relationship:` and
`intersection_of:` lines are ignored, so `root` follows `is_a` edges only.

`ontology_version` is the file's `data-version` header. A file without one gets
`sha256:` plus the first 12 hex digits of the file's hash.

OWL files are not read. Convert them to OBO with
[ROBOT](http://robot.obolibrary.org/convert):

```bash
robot convert --input cl.owl --output cl.obo
```

Most OBO Foundry ontologies also publish an `.obo` release next to the `.owl`.

Search matches the term id (`CL:0000236`, `CL_0000236` or an `alt_id`), then the
name (exact, then prefix, then every typed word as a word prefix), then
synonyms the same way, then substrings. A match found through a synonym shows
that synonym in the list.

## Picking a term

- Type at least two characters of a name, a synonym or an id.
- **Up** and **Down** move through the matches, **Enter** picks the highlighted
  one, **Escape** closes the list, and a second **Escape** clears the box.
  Clicking or tapping a match also picks it.
- **radio**: the picked term appears as a selected option. Picking another term
  replaces it.
- **multiselect**: each picked term appears as a ticked checkbox. Untick it to
  remove it.
- **span**: the picked term becomes the active span label; then highlight the
  text. The label above the highlight shows the term name.
- **image_annotation**: the picked term becomes a label button and the active
  label; then draw. Terms already used on the image appear as buttons when the
  page loads.

The list fits a phone screen and each match is a tap target at least 44 px
tall. Pocket Mode does not show the search box, so a task with a
`label_source` scheme always uses the regular annotation page.

## Stored data

| Scheme | Stored as |
|---|---|
| radio, multiselect | one label per term: the label name is the `obo_id`, the value is the JSON record shown at the top of this page |
| span | the span's label (`name`) is the `obo_id` |
| image_annotation | each shape's `label` is the `obo_id`, inside the usual `_data` JSON |

Spans and shapes store only the id. The `ontology_terms` export looks up the
name, IRI and version: in the `.obo` file for `service: file`, or, for
`service: ols4`, in `annotation_output/ontology_cache/<ontology>-ols4-terms.json`,
where the server keeps every term OLS4 has returned. For spans and shapes in
file mode the version written is the file's current one.

## Export

`--format ontology_terms` writes one row per picked term:

```bash
python -m potato.export --config config.yaml --format ontology_terms --output out/
```

`ontology_terms.csv` and `ontology_terms.jsonl` have the columns `user_id`,
`instance_id`, `schema`, `annotation_type`, `ontology`, `obo_id`, `label`, `iri`,
`ontology_version`, `start`, `end`, `text` (spans), `shape_index`, `shape_type`
(images) and `known`. `known` is `false` when the id is not in the current file
or cache, for example a term that a newer ontology release removed.

What the general exports write for these schemes:

| Format | radio / multiselect | span | image_annotation |
|---|---|---|---|
| `csv`, `tsv` | a column `<schema>.<obo_id>` holding the JSON record | `<schema>._spans`: JSON list with `name` = `obo_id` | `<schema>._data`: the shapes JSON, `label` = `obo_id` |
| `jsonl` | `labels: {schema: {obo_id: "<JSON record>"}}` | `spans` with `name` = `obo_id` | `labels.<schema>._data` |
| `parquet` | radio: the `obo_id`; multiselect: a list of `obo_id`s | as jsonl | as jsonl |

## Agreement

Agreement compares the `obo_id`: radio and multiselect compare label names,
spans compare `(start, end, name)`, and image shapes compare their `label`. Two
annotators who picked the same term agree even if their records carry different
`ontology_version` values. A parent and a child term (B cell and mature B cell)
count as different labels; there is no partial credit along the hierarchy.

## Troubleshooting

- **`label_source.file not found`**: the path is relative to `task_dir`, which is
  the directory of `config.yaml` when `task_dir: .`.
- **`... looks like OWL/RDF-XML, not OBO`**: convert the file with ROBOT (above).
- **`root ... is not a term`**: check the id against the file, including the
  prefix case (`CL:`, not `cl:`).
- **OLS4 searches fail with "did not answer within 5 s"**: raise `timeout_s`, or
  use a local file. Results are cached in memory for six hours, so repeated
  searches do not call OLS4 again.
- **The search box does not appear**: the scheme has no `label_source`, or the
  type is not one of the four supported ones (`potato validate` says which).
- **A span chip shows an id instead of a name after a restart**: in OLS4 mode
  the name comes from the term cache under `annotation_output/ontology_cache/`;
  if that directory was deleted, the id is shown until the term is searched
  again.

## Limitations

- OBO only; OWL needs converting.
- Fixed labels on the same scheme are stored as plain names, not terms.
- A span drawn with a term shows the neutral highlight colour after a reload;
  the label above it shows the term name.
- No partial agreement credit for related terms.

## Related

- [Entity linking](../text/entity_linking.md): attaches a knowledge-base id (Wikidata, UMLS) to a span whose label is a fixed category. `label_source` makes the label itself an ontology term.
- [Text spans](../text/text_annotation.md)
- [Hierarchical multiselect](../structured/hierarchical_multiselect.md): a fixed taxonomy written into the config.
- [Export formats](../../data-export/export_formats.md)
- Example project: `examples/classification/ontology-labels/` (a synthetic sample ontology, not real CL)

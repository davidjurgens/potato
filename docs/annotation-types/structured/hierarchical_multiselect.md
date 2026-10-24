# Hierarchical Multi-Label Selection

The hierarchical multiselect schema lets annotators pick labels out of a tree-structured taxonomy. Parent nodes can be expanded or collapsed, and selecting a parent optionally auto-selects or auto-deselects its children. An optional search box enables rapid navigation of large taxonomies.

## Overview

Flat multi-label checkboxes become unwieldy when label spaces have hundreds of entries organized into a hierarchy (e.g., ICD-10 diagnosis codes, product categories, scientific topics). The hierarchical multiselect schema:

- Renders the taxonomy as an expandable/collapsible tree
- Supports arbitrary nesting depth
- Optionally propagates selections up or down the hierarchy
- Has a search/filter box for large taxonomies
- Enforces an optional maximum selection limit

## Research Basis

- Silla, C. N., & Freitas, A. A. (2011). "A Survey of Hierarchical Classification Across Different Application Domains." *Data Mining and Knowledge Discovery 22*(1–2). Comprehensive review of hierarchical classification tasks in bioinformatics, text categorization, and image recognition — all requiring hierarchical annotation.
- Vens, C., Struyf, J., Schietgat, L., Džeroski, S., & Blockeel, H. (2008). "Decision Trees for Hierarchical Multi-label Classification." *Machine Learning 73*(2). Establishes the hierarchical multi-label classification problem formally and shows that hierarchical structure should be exploited in both annotation and modeling.

## Configuration

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `annotation_type` | — | Must be `hierarchical_multiselect` |
| `name` | — | Schema identifier (required) |
| `description` | — | Task instruction |
| `taxonomy` | — | Nested dict/list defining the label hierarchy (required) |
| `auto_select_children` | `false` | Selecting a parent auto-selects all its children |
| `auto_select_parent` | `false` | Selecting all children auto-selects the parent |
| `show_search` | `false` | Show a search/filter input above the tree |
| `max_selections` | `null` | Maximum number of labels that can be selected (null = unlimited) |
| `label_requirement.required` | `false` | Require at least one selection |

Only the boxes an annotator actually ticked are stored. Before v2.8.3 checking
one leaf silently ticked its whole ancestor chain regardless of
`auto_select_parent`, so a click on `Adjudication` stored `Annotation`,
`Process` and `Adjudication`. An analyst counting how often `Annotation` was
chosen could not tell a deliberate category-level choice from a leaf click three
levels below it. If you have data from an earlier build, ancestor entries
in it may not be choices anyone made.

### Taxonomy Format

The taxonomy is defined as a nested YAML structure where keys are parent labels and values are either a list of child labels (leaf nodes) or another nested dict:

```yaml
taxonomy:
  Sciences:
    Physics:
      - Classical Mechanics
      - Quantum Mechanics
      - Thermodynamics
    Biology:
      - Genetics
      - Ecology
      - Microbiology
  Humanities:
    - Literature
    - History
    - Philosophy
  Technology:
    Computer Science:
      - Machine Learning
      - Databases
      - Networking
    Engineering:
      - Civil Engineering
      - Electrical Engineering
```

### YAML Example — Topic Labeling

```yaml
annotation_schemes:
  - annotation_type: hierarchical_multiselect
    name: topic_hierarchy
    description: "Select all topics that apply to this article. You may select at multiple levels of specificity."
    auto_select_children: false
    auto_select_parent: false
    show_search: true
    max_selections: null
    taxonomy:
      Science:
        Physics:
          - Classical Mechanics
          - Quantum Mechanics
        Biology:
          - Genetics
          - Ecology
      Technology:
        - Artificial Intelligence
        - Cybersecurity
        - Robotics
      Politics:
        - Domestic Policy
        - Foreign Affairs
        - Elections
    label_requirement:
      required: true
```

### YAML Example — Medical Coding with Auto-Propagation

```yaml
annotation_schemes:
  - annotation_type: hierarchical_multiselect
    name: diagnosis_codes
    description: "Select all applicable ICD chapter categories. Selecting a chapter auto-selects its subcategories."
    auto_select_children: true
    auto_select_parent: false
    show_search: true
    max_selections: 5
    taxonomy:
      "Chapter I: Infectious Diseases":
        - "A00-A09 Intestinal infectious diseases"
        - "A15-A19 Tuberculosis"
        - "A20-A28 Bacterial zoonoses"
      "Chapter II: Neoplasms":
        - "C00-C14 Lip, oral cavity and pharynx"
        - "C15-C26 Digestive organs"
        - "C30-C39 Respiratory and intrathoracic organs"
```

### Taxonomy from a file

`taxonomy_file` loads the hierarchy from a CSV of codes, for a codebook
too long to write in the config:

```yaml
- annotation_type: hierarchical_multiselect
  name: topic
  description: Which topics does the text cover?
  taxonomy_file: codebooks/topics.csv
  show_codes: true
```

The CSV has the columns `code`, `label`, `parent` (the parent's code, empty
at the top level) and an optional `description`, used as the tooltip. A
JSON or YAML file holding the taxonomy mapping also works; its top level is
a mapping, as in the config. A file whose top level is a list stops the
config from loading, with an error that names the file. `show_codes:
true` shows each entry as `<code> <label>`. The answer stores each entry's
text, so two entries with the same text, such as an "Other" under two
topics, would be one answer. Such a file is refused unless `show_codes:
true` makes the entries distinct. Give `taxonomy` or `taxonomy_file`, not
both. See [Content analysis](../../guides/content-analysis.md).

## Output Format

Selected labels are stored as a comma-separated string of leaf and/or parent node names:

```json
{
  "topic_hierarchy": {
    "selected_labels": "Physics,Quantum Mechanics,Music"
  }
}
```

Labels appear in the order they were selected. Both parent and child labels can appear independently if selected independently (when `auto_select_children` is false).

## Use Cases

- **Medical coding** — ICD-10 or SNOMED-CT code assignment for clinical notes
- **Product categorization** — e-commerce taxonomy labeling for catalog data
- **Scientific literature** — multi-level topic annotation (field, subfield, method)
- **Legal document classification** — hierarchical legal code assignment
- **News article categorization** — section and subsection labeling
- **Ontology annotation** — labeling instances against WordNet, DBpedia, or custom ontologies

## Troubleshooting

**Tree is too deep to navigate:** The tree starts collapsed. Set `show_search: true` so annotators can search for the node they want instead of expanding branches.

**Auto-selection creates unexpected behavior:** When `auto_select_children: true`, deselecting a parent does not automatically deselect its children. Annotators must deselect children manually. Make this behavior explicit in the task instructions.

**Large taxonomies cause slow rendering:** For taxonomies with more than 500 nodes, enable `show_search: true` so annotators find nodes by search rather than by expanding the tree.

## Related Documentation

- [Multiselect / Checkbox](../schemas_and_templates.md#3-multiple-choice-multiselect) — flat multi-label checkbox schema
- [Conditional Logic](../../configuration/conditional_logic.md) — show/hide questions based on prior selections
- [Schema Gallery](../schemas_and_templates.md) — all annotation types with examples
- [Configuration Reference](../../configuration/configuration.md) — complete config options

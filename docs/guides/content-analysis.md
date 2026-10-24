# Content Analysis

A quantitative content analysis codes units (articles, posts, speeches,
headlines) against a codebook, with at least two coders on a sample, and
reports intercoder reliability per variable. In Potato:

- the codebook is a `hierarchical_multiselect` question loaded from a file
  (`taxonomy_file`), or ordinary radio and multiselect questions;
- `max_annotations_per_item: 2` (or more) gives each unit several coders;
- `--format reliability` writes the reliability table.

## A codebook from a file

```yaml
annotation_schemes:
  - annotation_type: hierarchical_multiselect
    name: topic
    description: Which topics does the headline cover?
    taxonomy_file: codebooks/topics.csv
    show_codes: true
    show_search: true
```

```csv
code,label,parent,description
1,Economy,,"Taxes, jobs, prices and the budget"
101,Taxes,1,
102,Jobs and wages,1,
2,Environment,,
201,Climate,2,Climate change and emissions
```

Each row is a code: `code`, `label`, `parent` (the parent's code, empty at
the top level) and an optional `description`, shown as the code's tooltip.
Order is kept. `show_codes: true` shows `101 Taxes` instead of `Taxes`. A
JSON or YAML file holding the taxonomy itself also works.

Published codebooks such as the Comparative Agendas Project topics or the
Manifesto Project categories can be written in this format for your own
use. Potato does not ship them: the Comparative Agendas Project codebook is
licensed CC BY-NC-SA, and the Manifesto Project's terms do not allow
redistribution.

## Reliability

```bash
python -m potato.export --config config.yaml --format reliability --output ./export/
```

`reliability.csv` and `reliability.md` (the same table in Markdown), one row
per question:

| Column | Meaning |
|---|---|
| `level` | Level of measurement: nominal (radio, select), ordinal (likert), interval (number, slider, VAS), MASI (multiselect and hierarchical multiselect, with partial credit for overlapping sets) |
| `alpha` | Krippendorff's alpha over the units coded by two or more coders |
| `ci95_low`, `ci95_high` | A percentile bootstrap interval, resampling units with replacement (`bootstrap` resamples, default 1000, seeded) |
| `percent_agreement` | Share of coder pairs on a unit that gave the same answer |
| `units`, `coders`, `pairable_values` | What the coefficient rests on |

The bootstrap resamples units; it is not the coincidence-based bootstrap of
Hayes and Krippendorff (2007). Krippendorff (2004) suggests relying on
variables with alpha of at least .800 and drawing tentative conclusions
down to .667. Potato reports the numbers and leaves that judgment to you.

`/admin/iaa` shows agreement while coding is in progress, and
[adjudication](../administration/adjudication.md) resolves the disagreements.

## Example

```bash
python potato/flask_server.py start examples/classification/codebook-content-analysis/config.yaml -p 8000
```

## Related

- [Hierarchical multiselect](../annotation-types/structured/hierarchical_multiselect.md)
- [Quality control and agreement](../workflow/quality_control.md)

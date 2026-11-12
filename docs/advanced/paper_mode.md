# Paper Mode: The Dataset That Writes Its Own Methods Section

Every dataset paper ends the same way: reconstructing annotator counts, agreement
statistics, label distributions, and timing from scattered output files, then
hand-formatting them into LaTeX. Paper Mode does it in one command:

```bash
python -m potato.paper examples/advanced/boundary-probing/config.yaml -o paper_export
```

Output — fully offline, no LLM, no server:

```
paper_export/
├── paper.tex        # compilable standalone; every section cut-paste-able
├── paper.bib        # citations for every metric used (+ Potato)
├── tables/*.csv     # each table as CSV, for your own styling
└── summary.json     # every computed number, machine-readable
```

`paper.tex` compiles as-is (`pdflatex paper && bibtex paper && pdflatex paper &&
pdflatex paper`), and every paragraph and table sits between markers so you can lift
sections directly into a manuscript:

```latex
%% === BLOCK: paragraph-annotation-methods ===
Annotators spent a median of 42 seconds per item (12.3 person-hours in total).
Inter-annotator agreement for \emph{politeness}, measured by Krippendorff's
$\alpha$ (nominal) \citep{krippendorff2004content} over the 214
multiply-annotated units, was $\alpha = 0.712$ (tentative agreement). ...
%% === END BLOCK: paragraph-annotation-methods ===
```

## What it generates

| Block | Content |
|-------|---------|
| `paragraph-dataset-description` | Item counts, schemes, labels, annotator/label totals — ready for a Data section |
| `paragraph-annotation-methods` | Timing, Krippendorff's α per scheme, mean pairwise Cohen's κ, all cited |
| `table-distribution-<scheme>` | booktabs label-distribution table per scheme, with totals |
| `table-annotators` | Items, labels, and median seconds/item per annotator (from behavioral logs) |
| `table-agreement` | α, mean κ, and interpretation per scheme (Krippendorff's 0.667/0.8 thresholds) |
| `paragraph-limitations` | Honest caveats with real numbers: single-annotated units, low-α schemes, small annotator pools |

## CLI options

| Flag | Default | Description |
|------|---------|-------------|
| `-o, --output-dir` | `paper_export` | Where to write the report |
| `--no-anonymize` | off | Keep real usernames; by default annotators become A1..An |

## Method notes

- Reads `{output_annotation_dir}/<user>/user_state.json` directly (resolved relative
  to the config file), so it works on archived projects without starting a server.
- Krippendorff's α (nominal) is computed with `simpledorff` — the same implementation
  as the admin dashboard — over units with 2+ annotations. Pairwise Cohen's κ is
  computed per annotator pair with 2+ shared items.
- Categorical schemes (radio, likert, multiselect, select, bws) get distributions and
  agreement; multiselect agreement treats each (item, label) checkbox as a
  binary-coded unit. Span/textbox schemes are listed as not covered.
- Timing comes from behavioral logs (`total_time_ms`, falling back to interaction
  timestamp spans, ignoring gaps over an hour).

## Related documentation

- [Admin Dashboard](../administration/admin_dashboard.md) — the live equivalents of these numbers
- [Quality Control](../workflow/quality_control.md) — gold standards and attention checks

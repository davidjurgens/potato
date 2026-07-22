# Publishing Datasets

Potato can package a finished annotation project into a well-documented, reusable
dataset and publish it to the **HuggingFace Hub**, deposit it on **Zenodo** for a
citable DOI, or produce a **self-contained local archive** — all from the admin
dashboard, with a rich README (dataset card) generated automatically.

The dataset card's data description (label distributions, inter-annotator agreement,
limitations) is produced by the same engine as [Paper Mode](#relationship-to-paper-mode),
so your published README and any methods section you write from `paper.tex` report the
**same numbers**.

## Quick start

1. Start your project and open the admin dashboard:
   ```bash
   python potato/flask_server.py start \
       examples/advanced/dataset-publishing/config.yaml -p 8000
   ```
2. Go to `http://localhost:8000/admin` and click **Publish Dataset**.
3. Choose a target, adjust preprocessing, review the auto-filled metadata, click
   **Preview README**, then **Publish**.

No configuration is required — publishing is always available to admins. The optional
`dataset_metadata:` and `publish:` config blocks below just pre-fill the wizard.

## What gets published

By default the dataset contains two data splits plus auxiliary splits:

| Split | Contents |
| :-- | :-- |
| `annotations` | one row per (instance, annotator) — raw, unaggregated labels |
| `gold` | one aggregated row per instance (majority vote / mean), with `n_annotators` |
| `spans` | one row per text span across all annotators |
| `items` | the source items that were annotated |
| `phase_responses` | survey / instruction / consent responses (**opt-in** — often PII) |

Columns follow Potato's tabular convention: each annotation scheme becomes
`scheme.label` columns (e.g. `sentiment.positive`).

A local archive additionally contains a `README.md` (the dataset card), a `LICENSE`,
a `.zenodo.json` metadata file, and a `paper_report/` folder with a cut-paste
`paper.tex` dataset report, its `paper.bib`, and per-table CSVs.

## Preprocessing options

All optional; sensible, privacy-preserving defaults are applied.

| Option | Default | Effect |
| :-- | :-- | :-- |
| `anonymize` | `true` | Map annotator ids to `A1..An`; strip internal fields (emails, worker/Prolific/MTurk ids, IPs). |
| `include_annotations` | `true` | Emit the raw per-annotator split. |
| `include_gold` | `true` | Emit the aggregated split. |
| `aggregation` | `majority` | `majority` (vote), `mean` (numeric columns), or `none`. |
| `min_annotators` | `1` | Keep only instances with at least this many annotators. |
| `include_spans` | `true` | Emit the spans split. |
| `include_items` | `true` | Emit the source-items split. |
| `include_phase_responses` | `false` | Include survey/phase responses (may contain PII). |
| `scrub_pii` | `false` | Replace emails/phone numbers in item text with `[EMAIL]`/`[PHONE]`. |
| `bundle_media` | `false` | Copy referenced image/audio/video files into the archive. |
| `splits` | none | Partition into `train`/`validation`/`test` by instance (see below). |
| `split_seed` | `42` | Seed for the deterministic per-instance split. |
| `data_format` | `jsonl` | Archive data format: `jsonl`, `csv`, or `parquet`. |

Train/val/test partitioning is deterministic and never splits one instance across
partitions.

## Privacy

Annotator anonymization is **on by default**: user ids become stable pseudonyms
(`A1`, `A2`, …) consistently across the data splits and the dataset card, and known
internal fields are removed. Survey/phase responses (which commonly hold demographics)
are **excluded by default**. Turn on `scrub_pii` to redact emails and phone numbers
from free-text item fields.

## Targets

### Local archive

Credential-free. Produces a `.zip` (or `.tar.gz`) you can download from the wizard.
This is also the exact payload uploaded to Zenodo.

### HuggingFace Hub

Provide a repository id (`your-org/dataset-name`) and an access token (or set the
`HF_TOKEN` environment variable). The splits are pushed as a `DatasetDict` and the
card as the repo README. Requires the extra dependencies:

```bash
pip install "potato-annotation[publish]"   # huggingface_hub + datasets + pyarrow
```

Load it back with:

```python
from datasets import load_dataset
ds = load_dataset("your-org/dataset-name")
print(ds["gold"][0])
```

### Zenodo

Provide a Zenodo token (or set `ZENODO_TOKEN`). By default the wizard targets the
**sandbox** (`sandbox.zenodo.org`) and creates an unpublished **draft** so you can
review it before minting a DOI. Switch the environment to production and the action to
**Publish** to mint a DOI. Zenodo needs no extra Python dependencies (it uses
`requests`, a core dependency).

## Command-line interface

Everything the wizard does is also available as a CLI — handy for scripting,
CI, or headless servers:

```bash
# Local archive (no account needed)
python -m potato.publish config.yaml --target archive -o my_dataset

# HuggingFace Hub
python -m potato.publish config.yaml --target huggingface \
    --repo-id your-org/dataset-name --token hf_xxx --private

# Zenodo — sandbox draft by default; mint a real DOI with --production --publish
python -m potato.publish config.yaml --target zenodo --token zzz
python -m potato.publish config.yaml --target zenodo --token zzz --production --publish
```

Preprocessing flags mirror the wizard, for example:

```bash
python -m potato.publish config.yaml --target archive \
    --aggregation majority --min-annotators 2 --splits 80/10/10 \
    --scrub-pii --data-format parquet --no-anonymize
```

Run `python -m potato.publish --help` for the full flag list. With no flags the
safe defaults apply (anonymize on, raw + aggregated splits, survey/PII excluded).
Tokens can also be supplied via the `HF_TOKEN` / `ZENODO_TOKEN` environment
variables instead of `--token`.

## Configuration reference

Both blocks are optional and only pre-fill the wizard.

```yaml
dataset_metadata:
  pretty_name: Movie Review Sentiment (Pilot)
  description: Short movie-review sentences labeled for sentiment.
  license: cc-by-4.0            # an SPDX id
  version: 1.0.0
  language: [en]
  keywords: [sentiment-analysis, movie-reviews]
  authors:
    - name: Ada Lovelace
      affiliation: University of Example
      orcid: 0000-0002-1825-0097
  citation: |
    @misc{my_dataset_2026, title={My Dataset}, author={Lovelace, Ada}, year={2026}}

publish:
  default_target: archive        # archive | huggingface | zenodo
  options:
    anonymize: true
    aggregation: majority
```

## Relationship to Paper Mode

Paper Mode (`python -m potato.paper config.yaml`) writes a cut-paste
LaTeX dataset report. Dataset publishing reuses Paper Mode's report model
(`potato/paper/report.py`) to render the README's data description in Markdown, and
ships the full LaTeX report inside the archive. Because both come from one model, the
README, the `paper.tex`, and the admin IAA page always agree.

## Troubleshooting

- **"Config file path unavailable"** — publish from a server started with a real config
  file (the manager reads the resolved config path from the running server).
- **HuggingFace import error** — install the extras: `pip install "potato-annotation[publish]"`.
- **Empty/low agreement** — agreement needs multiply-annotated instances; single-annotator
  items are reported but contribute no agreement signal.
- **Media not bundled** — `bundle_media` only copies files that exist under the project's
  `media_directory`; missing files are reported as warnings and skipped.

## Related documentation

- [Export Formats](export_formats.md) — COCO, YOLO, CoNLL, Parquet, and more
- [HuggingFace Hub Export](huggingface_export.md) — the underlying Hub push
- [Quality Control](../workflow/quality_control.md) — attention checks and gold standards
- [Crowdsourcing](../deployment/crowdsourcing.md) — collecting the annotations you publish
- [Admin Dashboard](../administration/admin_dashboard.md) — resolving disagreements before publishing

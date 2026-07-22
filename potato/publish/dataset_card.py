"""Generate a rich HuggingFace-style dataset card (README.md) for a bundle.

The body reuses Paper Mode's report (summary, annotation process, label
distributions, agreement, limitations) via ``paper.markdown.render_sections`` so the
README and any published ``paper.tex`` agree on every number and caveat. Around that
this module adds YAML frontmatter, per-column schema documentation over *all* schemes
(including spans/text/media that Paper Mode's tables skip), a privacy note,
licensing, and citation.
"""

from typing import Any, Dict, List

import yaml

from potato.paper import markdown as paper_md
from potato.paper import report as paper_report
from potato.publish.bundle import PublishBundle

# annotation_type -> HuggingFace task_category. Unmapped types contribute "other".
_TASK_CATEGORY = {
    "radio": "text-classification",
    "select": "text-classification",
    "multiselect": "text-classification",
    "likert": "text-classification",
    "multirate": "text-classification",
    "soft_label": "text-classification",
    "span": "token-classification",
    "error_span": "token-classification",
    "coreference": "token-classification",
    "text": "text-generation",
    "textbox": "text-generation",
    "text_edit": "text-generation",
    "extractive_qa": "question-answering",
    "image_annotation": "image-classification",
    "video_annotation": "video-classification",
    "audio_annotation": "audio-classification",
    "pairwise": "text-ranking",
    "ranking": "text-ranking",
    "bws": "text-ranking",
}


def _infer_task_categories(schemas: List[dict]) -> List[str]:
    cats = []
    for s in schemas:
        cat = _TASK_CATEGORY.get(s.get("annotation_type", ""), "other")
        if cat not in cats:
            cats.append(cat)
    return cats or ["other"]


def _size_category(n: int) -> str:
    if n < 1_000:
        return "n<1K"
    if n < 10_000:
        return "1K<n<10K"
    if n < 100_000:
        return "10K<n<100K"
    if n < 1_000_000:
        return "100K<n<1M"
    return "1M<n<10M"


def _frontmatter(bundle: PublishBundle) -> str:
    md = bundle.metadata
    largest = max((len(rows) for rows in bundle.splits.values()), default=0)
    data: Dict[str, Any] = {
        "annotations_creators": ["expert-generated"],
        "language_creators": ["found"],
        "task_categories": md.task_categories or _infer_task_categories(bundle.schemas),
        "size_categories": [_size_category(largest)],
        "tags": sorted(set(["potato-annotation"] + list(md.tags))),
        "pretty_name": md.pretty_name or "Potato Annotation Dataset",
    }
    if md.license:
        data["license"] = md.license
    if md.language:
        data["language"] = md.language
    dumped = yaml.safe_dump(data, sort_keys=True, allow_unicode=True,
                            default_flow_style=False).strip()
    return f"---\n{dumped}\n---"


def _schema_field_docs(schemas: List[dict]) -> str:
    """Document each annotation scheme as a dataset column."""
    lines = []
    for s in schemas:
        name = s.get("name", "?")
        ann_type = s.get("annotation_type", "unknown")
        desc = s.get("description", "").strip()
        labels = s.get("labels", []) or []
        label_names = [l["name"] if isinstance(l, dict) else str(l) for l in labels]
        line = f"- **`{name}`** (`{ann_type}`)"
        if desc:
            line += f" — {desc}"
        lines.append(line)
        if label_names:
            shown = ", ".join(f"`{l}`" for l in label_names[:15])
            if len(label_names) > 15:
                shown += f" … (+{len(label_names) - 15} more)"
            lines.append(f"  - Labels: {shown}")
    return "\n".join(lines) if lines else "_No annotation schemes defined._"


def _structure_section(bundle: PublishBundle) -> str:
    counts = bundle.split_row_counts()
    descriptions = {
        "annotations": "one row per (instance, annotator) — raw, unaggregated labels",
        "gold": "one aggregated row per instance (majority/mean), with `n_annotators`",
        "spans": "one row per text span across all annotators",
        "items": "the source items that were annotated",
        "phase_responses": "survey / instruction / consent responses",
        "train": "training partition (per-instance split)",
        "validation": "validation partition (per-instance split)",
        "test": "test partition (per-instance split)",
    }
    rows = ["| Split | Rows | Description |", "| :-- | --: | :-- |"]
    for name, count in counts.items():
        rows.append(f"| `{name}` | {count:,} | {descriptions.get(name, '')} |")
    table = "\n".join(rows)
    return (f"{table}\n\n### Data Fields\n\n"
            f"Each annotation scheme becomes one or more columns "
            f"(`scheme.label`):\n\n{_schema_field_docs(bundle.schemas)}")


def _usage_snippet(bundle: PublishBundle, repo_id: str) -> str:
    split = "gold" if "gold" in bundle.splits else \
        next(iter(bundle.splits), "annotations")
    return (
        "```python\n"
        "from datasets import load_dataset\n\n"
        f'ds = load_dataset("{repo_id or "your-org/your-dataset"}")\n'
        f'print(ds["{split}"][0])\n'
        "```")


def _citation_section(bundle: PublishBundle) -> str:
    parts = []
    if getattr(bundle.metadata, "citation", ""):
        parts.append("If you use this dataset, please cite:\n\n"
                      "```bibtex\n" + bundle.metadata.citation.strip() + "\n```")
    parts.append("This dataset was created with Potato:\n\n"
                 "```bibtex\n" + paper_report.BIB.strip() + "\n```")
    return "\n\n".join(parts)


def generate_dataset_card(bundle: PublishBundle,
                          repo_id: str = "",
                          target: str = "archive") -> str:
    md = bundle.metadata
    title = md.pretty_name or bundle.config.get("annotation_task_name",
                                                "Potato Annotation Dataset")

    parts = [_frontmatter(bundle), f"# {title}"]
    if md.description:
        parts.append(md.description)

    # --- Paper Mode report sections (numbers shared with paper.tex) ------------
    if bundle.stats and bundle.stats.get("schemes") is not None:
        sections = paper_md.render_sections(bundle.stats)
        parts += [
            "## Dataset Summary", sections["summary"],
            "## Dataset Structure", _structure_section(bundle),
            "## Annotation Process", sections["annotation_process"],
            "## Label Distributions", sections["label_distributions"],
            "## Inter-Annotator Agreement", sections["agreement"],
            "## Annotators", sections["annotators"],
        ]
        if sections["skipped_note"]:
            parts += ["### Other Schemes", sections["skipped_note"]]
        parts += ["## Considerations for Using the Data", sections["limitations"]]
    else:
        parts += ["## Dataset Structure", _structure_section(bundle)]

    # --- privacy / sensitive info ---------------------------------------------
    privacy = ("Annotator identifiers have been pseudonymized (`A1`, `A2`, …) and "
               "internal fields (emails, worker IDs, IP addresses) removed."
               if anonymize_note(bundle) else
               "Annotator identifiers in this dataset are **not** pseudonymized.")
    parts += ["## Personal and Sensitive Information", privacy]

    # --- usage -----------------------------------------------------------------
    parts += ["## Usage", _usage_snippet(bundle, repo_id)]

    # --- licensing & citation --------------------------------------------------
    license_text = (f"This dataset is released under the `{md.license}` license."
                    if md.license else
                    "No license was specified for this dataset. Consider adding one "
                    "before sharing (e.g. `cc-by-4.0`).")
    parts += ["## Licensing Information", license_text,
              "## Citation Information", _citation_section(bundle)]

    parts += ["---",
              "*This dataset card was generated by "
              "[Potato](https://github.com/davidjurgens/potato).*"]
    return "\n\n".join(parts) + "\n"


def anonymize_note(bundle: PublishBundle) -> bool:
    """True when the annotations split looks pseudonymized (or is absent)."""
    ann = bundle.splits.get("annotations")
    if not ann:
        return True
    return all(str(r.get("user_id", "")).startswith("A") for r in ann)

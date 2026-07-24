"""Configuration for dataset publishing.

``PublishConfig`` reads two optional config blocks:

- ``dataset_metadata:`` — descriptive metadata for the dataset card / Zenodo deposit
  (license, authors, citation, keywords, version, ...). All optional; the admin
  wizard can override any field at publish time.
- ``publish:`` — feature/runtime options (default target, default preprocessing
  toggles). Also all optional.

Nothing here requires the feature to be enabled: publishing works from an admin
screen with no config at all, using sensible defaults.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Author:
    name: str
    affiliation: str = ""
    orcid: str = ""

    @classmethod
    def from_any(cls, value: Any) -> "Author":
        if isinstance(value, str):
            return cls(name=value)
        if isinstance(value, dict):
            return cls(
                name=str(value.get("name", "")).strip(),
                affiliation=str(value.get("affiliation", "")).strip(),
                orcid=str(value.get("orcid", "")).strip(),
            )
        return cls(name=str(value))


@dataclass
class DatasetMetadata:
    """Descriptive metadata rendered into the card and Zenodo/`.zenodo.json`."""

    pretty_name: str = ""
    description: str = ""
    license: str = ""                       # SPDX id, e.g. "cc-by-4.0"
    language: List[str] = field(default_factory=list)
    authors: List[Author] = field(default_factory=list)
    citation: str = ""                      # BibTeX string (author-supplied)
    keywords: List[str] = field(default_factory=list)
    version: str = "1.0.0"
    funding: str = ""
    related_links: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    task_categories: List[str] = field(default_factory=list)  # else inferred

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "DatasetMetadata":
        data = data or {}

        def _as_list(v):
            if v is None:
                return []
            return list(v) if isinstance(v, (list, tuple)) else [v]

        return cls(
            pretty_name=str(data.get("pretty_name", "")).strip(),
            description=str(data.get("description", "")).strip(),
            license=str(data.get("license", "")).strip(),
            language=[str(x) for x in _as_list(data.get("language"))],
            authors=[Author.from_any(a) for a in _as_list(data.get("authors"))],
            citation=str(data.get("citation", "")).strip(),
            keywords=[str(x) for x in _as_list(data.get("keywords"))],
            version=str(data.get("version", "1.0.0")).strip() or "1.0.0",
            funding=str(data.get("funding", "")).strip(),
            related_links=[str(x) for x in _as_list(data.get("related_links"))],
            tags=[str(x) for x in _as_list(data.get("tags"))],
            task_categories=[str(x) for x in _as_list(data.get("task_categories"))],
        )

    def merge_overrides(self, overrides: Optional[dict]) -> "DatasetMetadata":
        """Return a copy with any non-empty override fields applied.

        Used to fold admin-wizard form values over config defaults without
        persisting the form values back to disk.
        """
        if not overrides:
            return self
        merged = DatasetMetadata.from_dict({
            "pretty_name": self.pretty_name,
            "description": self.description,
            "license": self.license,
            "language": self.language,
            "authors": [a.__dict__ for a in self.authors],
            "citation": self.citation,
            "keywords": self.keywords,
            "version": self.version,
            "funding": self.funding,
            "related_links": self.related_links,
            "tags": self.tags,
            "task_categories": self.task_categories,
        })
        supplied = DatasetMetadata.from_dict(overrides)
        for f in ("pretty_name", "description", "license", "citation", "version",
                  "funding"):
            val = getattr(supplied, f)
            if val:
                setattr(merged, f, val)
        for f in ("language", "authors", "keywords", "related_links", "tags",
                  "task_categories"):
            val = getattr(supplied, f)
            if val:
                setattr(merged, f, val)
        return merged


# Default preprocessing options. Chosen so the safest, most reusable dataset is
# produced with no configuration: privacy on, both raw + aggregated splits, no
# survey/PII leakage.
DEFAULT_OPTIONS: Dict[str, Any] = {
    "anonymize": True,          # map annotator ids -> A1..An, strip internal fields
    "include_annotations": True,  # raw per-annotator split
    "include_gold": True,         # aggregated (majority/mean) split
    "include_spans": True,
    "include_items": True,
    "include_phase_responses": False,  # surveys are usually PII -> opt in
    "aggregation": "majority",    # majority | mean | none
    "min_annotators": 1,          # keep instances with >= this many annotators
    "splits": None,               # e.g. {"train":0.8,"validation":0.1,"test":0.1}
    "split_seed": 42,
    "scrub_pii": False,           # regex email/phone scrub of item text
    "bundle_media": False,        # copy referenced media into the archive
    "data_format": "jsonl",       # jsonl | csv | parquet (archive file format)
}


@dataclass
class PublishConfig:
    metadata: DatasetMetadata
    default_target: str = "archive"     # archive | huggingface | zenodo
    options: Dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_OPTIONS))

    @classmethod
    def from_config(cls, config: dict) -> "PublishConfig":
        config = config or {}
        publish = config.get("publish", {}) or {}
        metadata = DatasetMetadata.from_dict(config.get("dataset_metadata"))
        # Fall back to the task name/description for the card title/summary.
        if not metadata.pretty_name:
            metadata.pretty_name = str(
                config.get("annotation_task_name", "")).strip()
        if not metadata.description:
            metadata.description = str(
                config.get("annotation_task_description")
                or config.get("task_description", "")).strip()

        options = dict(DEFAULT_OPTIONS)
        options.update(publish.get("options", {}) or {})
        return cls(
            metadata=metadata,
            default_target=str(publish.get("default_target", "archive")).strip()
            or "archive",
            options=options,
        )


def resolve_options(base: Dict[str, Any],
                    overrides: Optional[dict]) -> Dict[str, Any]:
    """Merge request-time option overrides over the configured defaults.

    Coerces the common string-boolean/number forms that arrive from an HTML form
    so the pipeline always sees real Python types.
    """
    opts = dict(base)
    for k, v in (overrides or {}).items():
        if k not in opts:
            opts[k] = v
            continue
        default = opts[k]
        if isinstance(default, bool):
            opts[k] = v if isinstance(v, bool) else \
                str(v).strip().lower() in ("true", "1", "yes", "on")
        elif isinstance(default, int) and not isinstance(default, bool):
            try:
                opts[k] = int(v)
            except (TypeError, ValueError):
                pass
        else:
            opts[k] = v
    return opts

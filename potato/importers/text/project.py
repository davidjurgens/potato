"""
Turn a :class:`~potato.importers.text.base.TextImportResult` into a runnable
Potato project.

The CV side does the same job inside ``potato/importers/cli.py``. This lives in
its own module rather than beside it because the two produce different
projects -- an ``image_annotation`` scheme over image URLs versus a ``span``
scheme over text -- and the only thing they would actually share is the
directory layout.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from potato.server_utils.config_schema import SCHEMA_URL

from .base import TextImportResult

logger = logging.getLogger(__name__)

SCHEMA_MODELINE = f"# yaml-language-server: $schema={SCHEMA_URL}"

#: The pre-annotation field the generated config reads. Matching the CV
#: importer's choice keeps one convention across both halves.
PREDICTION_FIELD = "predictions"


def build_config(schema_name: str, result: TextImportResult,
                 data_file: str, task_name: str) -> dict:
    """Generate a runnable config for an imported text project."""
    schemes: List[dict] = []

    if result.labels:
        schemes.append({
            "annotation_type": "span",
            "name": schema_name,
            "description": "Correct the imported spans",
            "labels": [dict(label) for label in result.labels],
        })

    # Document-level schemes the importer derived (doccano categories, Prodigy
    # verdicts). Appended after the span scheme so the text-level task reads
    # first, which is the order the source tools present them in.
    schemes.extend(dict(scheme) for scheme in result.document_schemes)

    return {
        "port": 8000,
        "annotation_task_name": task_name,
        "task_dir": ".",
        "output_annotation_dir": "annotation_output/",
        "data_files": [data_file],
        "item_properties": {
            "id_key": "id",
            "text_key": "text",
        },
        "user_config": {
            "allow_all_users": True,
            "users": [],
        },
        "site_dir": "default",
        # Imported codings arrive as pre-annotations: every annotator sees them
        # as a starting point and their corrections replace them on save. They
        # are deliberately NOT written into anyone's user_state, which would
        # make imported work indistinguishable from human work and fabricate
        # agreement between annotators who never opened the item.
        "pre_annotation": {
            "enabled": True,
            "field": PREDICTION_FIELD,
            "allow_modification": True,
        },
        "annotation_schemes": schemes,
    }


def write_data_file(path: Path, result: TextImportResult,
                    schema_name: str) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for document in result.documents:
            row: Dict[str, object] = {
                "id": document.instance_id,
                "text": document.text,
            }
            row.update(document.extra)

            predictions: Dict[str, object] = {}
            if document.spans:
                predictions[schema_name] = [
                    span.as_client_span(schema_name) for span in document.spans
                ]
            for scheme_name, value in document.labels.items():
                predictions[scheme_name] = value
            if predictions:
                row[PREDICTION_FIELD] = predictions

            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_project(result: TextImportResult, output_dir: str, schema_name: str,
                  source: str, config_only: bool = False,
                  stem: Optional[str] = None) -> List[str]:
    """
    Write the data file, config and README. Returns the paths written.
    """
    output = Path(output_dir)
    (output / "data").mkdir(parents=True, exist_ok=True)

    stem = stem or Path(source).stem or "imported"
    data_rel = os.path.join("data", f"{stem}.json")
    written: List[str] = []

    if not config_only:
        data_path = output / data_rel
        write_data_file(data_path, result, schema_name)
        written.append(str(data_path))

    task_name = f"{stem} (imported)"
    config_path = output / "config.yaml"
    config = build_config(schema_name, result, data_rel, task_name)
    with config_path.open("w", encoding="utf-8") as handle:
        # The modeline first: it is what switches on live validation in an
        # editor and tells a coding agent where the contract is.
        handle.write(SCHEMA_MODELINE + "\n")
        yaml.safe_dump(config, handle, sort_keys=False, default_flow_style=False,
                       allow_unicode=True)
    written.append(str(config_path))

    readme_path = output / "README.md"
    if readme_path.exists():
        logger.info("README.md already exists; leaving it alone")
    else:
        _write_readme(readme_path, result, source, schema_name)
        written.append(str(readme_path))

    return written


def _write_readme(path: Path, result: TextImportResult, source: str,
                  schema_name: str) -> None:
    stats = result.stats
    path.write_text(f"""# Imported text annotation project

Generated by `potato import` from `{Path(source).name}`.

- **Documents:** {stats.get('num_documents', 0)}
- **Spans:** {stats.get('num_spans', 0)}
- **Codes:** {stats.get('num_codes', 0)}

## Run it

```bash
python potato/flask_server.py start config.yaml -p 8000
```

## Notes

- Imported codings are *pre-annotations*. Every annotator sees them as a
  starting point, and they are only stored once someone saves -- so an item
  nobody opened exports as empty rather than as agreement that never happened.
- Offsets are 0-based Unicode code points with an exclusive end, and the text
  in `data/` is what they index. Where the source format could not record
  spacing exactly (CoNLL, in particular), the stored text is the reconstruction
  the offsets refer to.

## Export back out

```bash
python -m potato.export -c config.yaml -f qdpx -o ./export/
python -m potato.export -c config.yaml -f conll_2003 -o ./export/
```
""", encoding="utf-8")

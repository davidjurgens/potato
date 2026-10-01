"""The annotator-origin columns written by the per-annotator exporters.

Every annotation record carries ``_origin`` (see ``export/cli.py``): a person,
or a declared tool or language model with its version. The csv, tsv, jsonl,
parquet and HuggingFace exporters write one row per annotator per item, and
without a column saying which rows came from a machine a reader of the file
cannot keep them out of an agreement statistic or a training set.

The columns appear only when at least one record in the export is from a
machine rater. A study that never declared one exports exactly what it did
before, and a study that did gets the columns on every row, humans included,
so the file can be filtered on them.
"""

import json
from typing import Any, Dict, Iterable

from potato.annotator_origin import HUMAN, origin_of

#: The rater's kind: ``human``, ``tool`` or ``llm``.
ORIGIN_COLUMN = "annotator_origin"

#: The full declaration as JSON (tool, model, version, database version, run
#: date). Empty for a person, who has nothing more to record.
ORIGIN_DETAIL_COLUMN = "annotator_origin_detail"


def record_origin(ann: Dict[str, Any]) -> Dict[str, Any]:
    """The origin of one annotation record. A record without one is a person."""
    return origin_of(ann.get("_origin"))


def origin_in_use(annotations: Iterable[Dict[str, Any]]) -> bool:
    """True when any record in the export came from a machine rater."""
    return any(record_origin(ann).get("kind") != HUMAN for ann in annotations)


def origin_fields(ann: Dict[str, Any]) -> Dict[str, str]:
    """The two flat columns for one record."""
    origin = record_origin(ann)
    kind = str(origin.get("kind") or HUMAN)
    detail = "" if kind == HUMAN else json.dumps(origin, sort_keys=True)
    return {ORIGIN_COLUMN: kind, ORIGIN_DETAIL_COLUMN: detail}

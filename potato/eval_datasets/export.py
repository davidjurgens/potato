"""
Dataset -> fine-tuning format export (SFT / DPO).

Converts curated dataset examples into the same JSONL record shapes the
trajectory-correction exporter emits, so dataset-curated data feeds the same
SFT/DPO pipelines:

  SFT: {"prompt": <inputs>, "completion": <reference_outputs>}
  DPO: {"prompt": <inputs>, "chosen": <reference_outputs>, "rejected": <rejected>}

For DPO the "rejected" output is read from ``example.metadata['rejected']`` (or
``metadata['outputs']`` as a fallback — the actual/worse model output). Examples
lacking the required field are skipped (and counted), never silently emitted.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from potato.eval_datasets.models import Example


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for k in ("output", "text", "content", "answer", "final_answer", "completion"):
            if k in value and isinstance(value[k], str):
                return value[k]
        return json.dumps(value, ensure_ascii=False)
    return json.dumps(value, ensure_ascii=False)


def _prompt_text(example: Example) -> str:
    return _as_text(example.inputs)


def to_sft_records(examples: List[Example]) -> Tuple[List[Dict[str, str]], int]:
    """Return (records, skipped). Skips examples without reference_outputs."""
    records, skipped = [], 0
    for ex in examples:
        if ex.reference_outputs is None:
            skipped += 1
            continue
        records.append({
            "prompt": _prompt_text(ex),
            "completion": _as_text(ex.reference_outputs),
        })
    return records, skipped


def to_dpo_records(examples: List[Example]) -> Tuple[List[Dict[str, str]], int]:
    """Return (records, skipped). Needs reference_outputs (chosen) + a rejected."""
    records, skipped = [], 0
    for ex in examples:
        rejected = ex.metadata.get("rejected", ex.metadata.get("outputs"))
        if ex.reference_outputs is None or rejected is None:
            skipped += 1
            continue
        records.append({
            "prompt": _prompt_text(ex),
            "chosen": _as_text(ex.reference_outputs),
            "rejected": _as_text(rejected),
        })
    return records, skipped


def to_jsonl(records: List[Dict[str, str]]) -> str:
    return "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + ("\n" if records else "")


def export_examples(examples: List[Example], fmt: str) -> Tuple[str, int]:
    """Export to a JSONL string. Returns (jsonl, skipped_count)."""
    fmt = (fmt or "").lower()
    if fmt == "sft":
        records, skipped = to_sft_records(examples)
    elif fmt == "dpo":
        records, skipped = to_dpo_records(examples)
    else:
        raise ValueError(f"Unknown export format: {fmt!r} (use 'sft' or 'dpo')")
    return to_jsonl(records), skipped

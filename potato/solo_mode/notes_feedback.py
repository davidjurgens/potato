"""
Turn accumulated human rationale notes into codebook-edit proposals.

Annotators leave free-text notes explaining a validation or disagreement
resolution (see ``annotation_notes.py``). This module periodically groups
those notes by the label/code they explain, asks the revision-model LLM
whether the note pattern suggests a specific codebook edit (a tighter
definition, a missing exclusion rule, etc.), and — if so — stages it via
the *existing* LLM-propose/human-confirm flow
(``potato.codebook.changelog.propose_change``, op="update_fields").
Nothing changes until a human confirms the proposal in the tray, exactly
like every other model-authored codebook edit.
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_MIN_NOTES_PER_LABEL = 2  # don't bother the LLM over a single stray note

_PROMPT_TEMPLATE = """You are helping refine an annotation codebook entry \
based on rationale notes annotators left while labeling.

Code: "{code_name}"
Current definition: {definition}
Current include rule: {clarification}
Current exclude rule: {negative_clarification}

Annotator notes about this code:
{notes_text}

Do these notes reveal a specific, concrete gap in the code's definition or \
rules (e.g. an edge case not covered, an ambiguity, a missing exclusion)? \
If yes, propose a tightened version of ONLY the fields that need to change. \
If the notes don't point to a specific fix, don't propose anything.

Respond with JSON:
{{
    "should_propose": <true|false>,
    "rationale": "<one sentence citing what in the notes motivated this>",
    "definition": "<revised definition, or omit/null if unchanged>",
    "clarification": "<revised include rule, or omit/null if unchanged>",
    "negative_clarification": "<revised exclude rule, or omit/null if unchanged>"
}}
"""


def _parse_json(response: Any) -> Dict[str, Any]:
    if isinstance(response, dict):
        return response
    if hasattr(response, "model_dump"):
        return response.model_dump()
    content = str(response).strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", content)
    if match:
        content = match.group(1).strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {}


def _group_by_label(notes: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    grouped: Dict[str, List[str]] = defaultdict(list)
    for row in notes:
        label = row.get("label")
        if label:
            grouped[label].append(row["note"])
    return grouped


def suggest_from_notes(
    task_dir: str, project: str, *, endpoint: Any, since: float = 0.0,
    actor: str = "notes_feedback_llm",
) -> List[Dict[str, Any]]:
    """Analyze recent notes and submit any resulting codebook-edit
    proposals. Returns the list of created proposal records. Best-effort
    per label: one label's LLM/parse failure doesn't stop the others.
    """
    from potato.solo_mode import annotation_notes
    from potato.codebook import changelog
    from potato.codebook.codebook import Codebook

    notes = annotation_notes.recent_notes(task_dir, project, since=since)
    grouped = _group_by_label(notes)

    created: List[Dict[str, Any]] = []
    if not grouped:
        return created

    cb = Codebook.load(task_dir, project)
    by_name = {d.get("name"): d for d in cb.details_in_order()}

    for label, label_notes in grouped.items():
        if len(label_notes) < _MIN_NOTES_PER_LABEL:
            continue
        code = by_name.get(label)
        if not code:
            continue  # note's label doesn't match a current code name
        try:
            prompt = _PROMPT_TEMPLATE.format(
                code_name=label,
                definition=code.get("definition") or "(none yet)",
                clarification=code.get("clarification") or "(none yet)",
                negative_clarification=(
                    code.get("negative_clarification") or "(none yet)"),
                notes_text="\n".join(f"- {n}" for n in label_notes),
            )
            response = endpoint.query(prompt)
            parsed = _parse_json(response)
            if not parsed.get("should_propose"):
                continue
            payload: Dict[str, Any] = {"code_id": code["id"]}
            for field in ("definition", "clarification",
                          "negative_clarification"):
                val = parsed.get(field)
                if val:
                    payload[field] = val
            if len(payload) <= 1:  # only code_id — nothing to change
                continue
            payload["rationale"] = parsed.get("rationale", "")
            prop = changelog.propose_change(
                task_dir, project=project, op="update_fields",
                payload=payload, actor=actor, actor_kind="model")
            created.append(prop)
        except Exception:
            logger.warning(
                "notes-feedback proposal generation failed for label %r",
                label, exc_info=True)
            continue

    return created

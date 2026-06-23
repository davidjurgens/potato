"""
Run-tree data model for the Potato tracing SDK.

A ``Run`` is one node (a chain/llm/tool/retriever call). Nested runs form a tree
via ``parent_run_id``. The tree serializes to the LangSmith-format payload that
Potato's trace-ingestion webhook already accepts
(``{"runs": [...], "project_name": ...}``), so no server changes are needed.

This module is dependency-light (stdlib only) so importing the SDK never pulls
Flask or the ML stack.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def new_run_id() -> str:
    return uuid.uuid4().hex


def safe_serialize(obj: Any) -> Any:
    """Best-effort JSON-safe conversion (mirrors the LangChain callback)."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): safe_serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [safe_serialize(v) for v in obj]
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return str(obj)


@dataclass
class Run:
    """One node in a trace's run tree."""

    name: str
    run_type: str = "chain"  # chain | llm | tool | retriever
    id: str = field(default_factory=new_run_id)
    parent_run_id: Optional[str] = None
    inputs: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    status: str = "running"  # running | success | error
    error: Optional[str] = None
    latency: Optional[float] = None
    tags: List[str] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)  # e.g. token usage

    def to_payload(self) -> Dict[str, Any]:
        out = {
            "id": self.id,
            "parent_run_id": self.parent_run_id,
            "run_type": self.run_type,
            "name": self.name,
            "inputs": safe_serialize(self.inputs),
            "outputs": safe_serialize(self.outputs),
            "status": self.status,
            "latency": self.latency,
            "tags": list(self.tags),
        }
        if self.error:
            out["error"] = self.error
        if self.extra:
            out["extra"] = safe_serialize(self.extra)
        return out


def build_payload(runs: List[Run], root_id: Optional[str], project_name: str) -> Dict[str, Any]:
    """Assemble the LangSmith-format webhook payload, root run first."""
    ordered = sorted(runs, key=lambda r: 0 if r.id == root_id else 1)
    payload: Dict[str, Any] = {"runs": [r.to_payload() for r in ordered]}
    if project_name:
        payload["project_name"] = project_name
    return payload

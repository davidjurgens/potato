"""
Codebook distillation pipeline — living document -> model prompt.

The codebook is authored for humans (rich, possibly long). A *distiller*
compresses the relevant slice into a prompt string the model sees, so the
human codebook literally becomes the model's guidance. This module ships:

- ``DistillerConfig`` — what to include (block types, doc sections, scope)
  and which ``procedure`` to run; built from
  ``config['codebook']['distiller']``.
- ``Procedure`` — a pluggable step. The default ``concat`` assembles the
  selected blocks into a prompt. ``llm_summarize`` and
  ``select_icl_examples`` ship as registered **stubs** (they return the
  concat output today) so the full pipeline — summarization, ICL example
  selection on top of the codebook's internal state — can be added later
  with no caller changes.
- ``CodebookDistiller`` — caches the distilled string by
  ``(project, content_revision)`` and rebuilds when content changes
  (wired to the codebook change-listener alongside the ICL label sync).

The distilled string is *additive* context appended at the prompt site; it
never feeds ``Codebook.labels()`` (labels stay authoritative).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from potato.codebook import blocks as _blocks
from potato.codebook.codebook import Codebook

logger = logging.getLogger(__name__)

# Default: the meaning-bearing + illustrative slice, in reading order.
_DEFAULT_INCLUDE = ("short_def", "definition", "use_when", "avoid_when",
                    "example", "counter_example")
_DEFAULT_DOC_SECTIONS = ("preamble", "general_instructions")


@dataclass
class DistillerConfig:
    include_types: tuple = _DEFAULT_INCLUDE
    include_doc_sections: tuple = _DEFAULT_DOC_SECTIONS
    scope: str = "per_code"          # 'per_code' | 'whole_doc'
    procedure: str = "concat"
    max_chars: Optional[int] = None  # soft cap on the distilled output

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "DistillerConfig":
        raw = {}
        cb = config.get("codebook")
        if isinstance(cb, dict) and isinstance(cb.get("distiller"), dict):
            raw = cb["distiller"]
        return cls(
            include_types=tuple(
                raw.get("include") or raw.get("include_types")
                or _DEFAULT_INCLUDE),
            include_doc_sections=tuple(
                raw.get("include_doc_sections") or _DEFAULT_DOC_SECTIONS),
            scope=raw.get("scope") or "per_code",
            procedure=raw.get("procedure") or "concat",
            max_chars=raw.get("max_chars"),
        )


@dataclass
class DistillContext:
    """Everything a procedure may need — including a free-form
    ``internal_state`` bag where a future procedure (ICL selection,
    summarization) can stash model handles / instance pools."""
    task_dir: str
    project: str
    codebook: Codebook
    code_blocks: Dict[str, List[Dict[str, Any]]]
    doc_blocks: Dict[str, List[Dict[str, Any]]]
    config: DistillerConfig
    internal_state: Dict[str, Any] = field(default_factory=dict)


# ---- procedure registry --------------------------------------------------

# A Procedure is `(DistillContext) -> str`.
_PROCEDURES: Dict[str, Callable[[DistillContext], str]] = {}


def register_procedure(
    name: str, proc: Callable[[DistillContext], str]
) -> None:
    _PROCEDURES[name] = proc


def get_procedure(name: str) -> Callable[[DistillContext], str]:
    if name not in _PROCEDURES:
        logger.warning(
            "unknown distiller procedure %r; falling back to 'concat'",
            name)
        return _PROCEDURES["concat"]
    return _PROCEDURES[name]


def _heading(block_type: str, custom_label: Optional[str]) -> str:
    if block_type == "custom":
        return custom_label or "Note"
    return _blocks.BLOCK_TYPES.get(block_type, {}).get("heading", block_type)


def _render_blocks(
    block_list: List[Dict[str, Any]], include_types: tuple
) -> List[str]:
    lines: List[str] = []
    for b in block_list:
        bt = b.get("block_type")
        if bt not in include_types:
            continue
        body = (b.get("body_md") or "").strip()
        if not body:
            continue
        lines.append(f"{_heading(bt, b.get('custom_label'))}: {body}")
    return lines


def concat_procedure(ctx: DistillContext) -> str:
    """Default: assemble the included blocks into a readable guidance
    block. Per-code sections plus any included document-level sections."""
    cfg = ctx.config
    parts: List[str] = []

    for sect in cfg.include_doc_sections:
        sec_lines = _render_blocks(
            ctx.doc_blocks.get(sect, []), tuple(_blocks.BLOCK_TYPES))
        if sec_lines:
            title = _blocks.DOC_SECTION_TITLES.get(sect, sect)
            parts.append(f"## {title}\n" + "\n".join(sec_lines))

    if cfg.scope == "per_code":
        def walk(node: Dict[str, Any]) -> None:
            lines = _render_blocks(
                ctx.code_blocks.get(node["id"], []), cfg.include_types)
            if lines:
                parts.append(f"### {node['name']}\n" + "\n".join(lines))
            for child in node.get("children", []):
                walk(child)
        for root in ctx.codebook.as_tree():
            walk(root)

    out = "\n\n".join(parts).strip()
    if cfg.max_chars and len(out) > cfg.max_chars:
        out = out[:cfg.max_chars].rstrip() + "\n…(truncated)"
    return out


def _stub(ctx: DistillContext) -> str:
    # Forward-looking seam: today identical to concat. A real
    # implementation would call a model / select ICL examples using
    # ctx.internal_state, then return the refined prompt.
    return concat_procedure(ctx)


register_procedure("concat", concat_procedure)
register_procedure("llm_summarize", _stub)
register_procedure("select_icl_examples", _stub)


# ---- the distiller -------------------------------------------------------

class CodebookDistiller:
    """Distills the living codebook into a prompt string, cached by the
    project's content revision so it rebuilds only when content changes."""

    def __init__(self, config: Optional[DistillerConfig] = None):
        self.config = config or DistillerConfig()
        self._cache: Dict[str, Any] = {}  # project -> (content_rev, text)

    def _build_context(
        self, task_dir: str, project: str
    ) -> DistillContext:
        cb = Codebook.load(task_dir, project)
        code_blocks = {
            c["id"]: _blocks.list_blocks(
                task_dir, project, code_id=c["id"])
            for c in cb._codes
        }
        doc_blocks = {
            sect: _blocks.list_blocks(task_dir, project, section=sect)
            for sect in _blocks.DOC_SECTIONS
        }
        return DistillContext(
            task_dir=task_dir, project=project, codebook=cb,
            code_blocks=code_blocks, doc_blocks=doc_blocks,
            config=self.config)

    def distill(self, task_dir: str, project: str) -> str:
        # Key on BOTH revisions so any change rebuilds: content edits bump
        # content_revision; a structural rename/move bumps the structural
        # revision (and changes code names the distiller renders).
        from potato.codebook import revision as _rev
        key = (
            _blocks.current_content_revision(task_dir, project),
            _rev.current_revision(task_dir, project),
        )
        cached = self._cache.get(project)
        if cached and cached[0] == key:
            return cached[1]
        ctx = self._build_context(task_dir, project)
        text = get_procedure(self.config.procedure)(ctx)
        self._cache[project] = (key, text)
        return text

    def invalidate(self, project: Optional[str] = None) -> None:
        if project is None:
            self._cache.clear()
        else:
            self._cache.pop(project, None)


# Process-wide default distiller, lazily reconfigured from config.
_DEFAULT_DISTILLER: Optional[CodebookDistiller] = None


def get_default_distiller(
    config: Optional[Dict[str, Any]] = None
) -> CodebookDistiller:
    global _DEFAULT_DISTILLER
    if _DEFAULT_DISTILLER is None:
        cfg = (DistillerConfig.from_config(config)
               if config else DistillerConfig())
        _DEFAULT_DISTILLER = CodebookDistiller(cfg)
    return _DEFAULT_DISTILLER


def distill_for_config(config: Dict[str, Any]) -> str:
    """Convenience used at the prompt site: distill the current codebook
    for the live config (task_dir + project)."""
    task_dir = config.get("task_dir", ".")
    project = config.get("annotation_task_name") or "default"
    return get_default_distiller(config).distill(task_dir, project)

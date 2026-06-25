"""
Codebook markdown round-trip + safe renderer.

Pure module: no DB, no Flask. Two responsibilities:

1. **Round-trip** between a scope's *typed blocks* and a markdown
   fragment that uses a heading-convention grammar (``### Use when`` …).
   This is the freeform-first contract: content is authored/pasted as
   markdown, parsed into typed blocks; any heading we can't classify
   becomes a ``custom`` block (flagged ``classified=False`` so the UI can
   prompt the user to type it) with its original heading preserved in
   ``custom_label`` — lossless. The invariant
   ``markdown_to_blocks(blocks_to_markdown(b)) == b`` (over the persisted
   fields block_type/custom_label/body_md) is guarded by
   ``tests/unit/test_codebook_markdown_roundtrip.py``.

2. **Render** markdown to sanitized HTML for human reading. A tiny
   vendored renderer (no third-party dependency) feeds the existing
   ``sanitize_html`` allowlist — that allowlist is the XSS trust boundary,
   so raw ``body_md`` is NEVER injected into the DOM directly.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from potato.codebook.blocks import BLOCK_TYPES

# ---- heading <-> type maps (derived from the vocabulary) ----------------

TYPE_TO_HEADING: Dict[str, str] = {
    k: v["heading"] for k, v in BLOCK_TYPES.items()}


def _norm_heading(s: str) -> str:
    """Normalize a heading for matching: lowercase, hyphens/underscores to
    spaces, collapse whitespace, drop a trailing colon."""
    s = (s or "").strip().rstrip(":")
    s = s.replace("-", " ").replace("_", " ")
    return " ".join(s.split()).lower()


# normalized-heading -> canonical block_type (canonical + aliases)
_HEADING_TO_TYPE: Dict[str, str] = {}
for _t, _meta in BLOCK_TYPES.items():
    if _t == "custom":
        continue
    _HEADING_TO_TYPE[_norm_heading(_meta["heading"])] = _t
    for _alias in _meta.get("aliases", []):
        _HEADING_TO_TYPE[_norm_heading(_alias)] = _t


def classify_heading(heading: str) -> str:
    """Return the canonical block_type for a heading, or 'custom'."""
    return _HEADING_TO_TYPE.get(_norm_heading(heading), "custom")


# ---- serialize: blocks -> markdown --------------------------------------

def blocks_to_markdown(blocks: List[Dict[str, Any]], *, level: int = 3) -> str:
    """Serialize one scope's ordered blocks to a markdown fragment using
    `level`-deep ATX headings (### by default)."""
    hashes = "#" * level
    parts: List[str] = []
    for b in blocks:
        btype = b.get("block_type") or "custom"
        if btype == "custom":
            heading = b.get("custom_label") or BLOCK_TYPES["custom"]["heading"]
        else:
            heading = TYPE_TO_HEADING.get(btype, btype)
        parts.append(f"{hashes} {heading}")
        body = (b.get("body_md") or "").strip("\n")
        if body:
            parts.append("")
            parts.append(body)
        parts.append("")
    return "\n".join(parts).rstrip("\n") + "\n"


# ---- parse: markdown -> blocks ------------------------------------------

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


def markdown_to_blocks(md: str, *, level: int = 3) -> List[Dict[str, Any]]:
    """Parse a markdown fragment into typed blocks. Headings at exactly
    `level` (### by default) delimit blocks. Text before the first heading,
    if non-empty, becomes an implicit `definition` block flagged
    classified=False (freeform-first: a heading-less paste is treated as a
    definition the user can re-type). Unknown headings -> custom blocks
    flagged classified=False, original heading kept in custom_label."""
    lines = (md or "").splitlines()
    blocks: List[Dict[str, Any]] = []
    preamble: List[str] = []
    cur: Dict[str, Any] | None = None
    body: List[str] = []

    def flush() -> None:
        nonlocal cur, body
        if cur is not None:
            cur["body_md"] = "\n".join(body).strip("\n")
            blocks.append(cur)
        cur, body = None, []

    started = False
    for line in lines:
        m = _HEADING_RE.match(line)
        if m and len(m.group(1)) == level:
            started = True
            flush()
            heading = m.group(2).strip()
            btype = classify_heading(heading)
            if btype == "custom":
                cur = {
                    "block_type": "custom",
                    "custom_label": heading,
                    "body_md": "",
                    "classified": False,
                }
            else:
                cur = {
                    "block_type": btype,
                    "custom_label": None,
                    "body_md": "",
                    "classified": True,
                }
        elif not started:
            preamble.append(line)
        else:
            body.append(line)
    flush()

    pre_text = "\n".join(preamble).strip()
    if pre_text:
        blocks.insert(0, {
            "block_type": "definition",
            "custom_label": None,
            "body_md": pre_text,
            "classified": False,
        })
    return blocks


# ---- render: markdown -> safe HTML --------------------------------------

_INLINE_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*([^*]+)\*\*|__([^_]+)__")
_ITALIC = re.compile(r"(?<!\*)\*(?!\*)([^*]+)\*(?!\*)|(?<!_)_(?!_)([^_]+)_(?!_)")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_PLAIN_URL = re.compile(r"^https?://[^\s<>\"']+$")


def _render_inline(text: str) -> str:
    """Apply inline markdown to one line of *raw* text. We deliberately do
    NOT HTML-escape here: the rendered string is passed through
    `sanitize_html`, which is the single escaping trust boundary. Escaping
    here too would double-escape legitimate content (`a & b` -> `a &amp; b`
    -> rendered literally)."""
    out = text

    def code_sub(m: "re.Match[str]") -> str:
        return f"<code>{m.group(1)}</code>"

    out = _INLINE_CODE.sub(code_sub, out)

    def link_sub(m: "re.Match[str]") -> str:
        label, url = m.group(1), m.group(2)
        if not _PLAIN_URL.match(url) and not url.startswith(("/", "#", "mailto:")):
            # Unknown/unsafe scheme: render as plain text (sanitizer would
            # also strip it, but be explicit).
            return f"{label} ({url})"
        return f'<a href="{url}" target="_blank">{label}</a>'

    out = _LINK.sub(link_sub, out)

    def bold_sub(m: "re.Match[str]") -> str:
        return f"<strong>{m.group(1) or m.group(2)}</strong>"

    out = _BOLD.sub(bold_sub, out)

    def italic_sub(m: "re.Match[str]") -> str:
        return f"<em>{m.group(1) or m.group(2)}</em>"

    out = _ITALIC.sub(italic_sub, out)
    return out


def _to_html(md: str) -> str:
    """Block-level markdown -> HTML. Handles headings, fenced code,
    blockquotes, ordered/unordered lists, horizontal rules, paragraphs."""
    lines = (md or "").split("\n")
    html_parts: List[str] = []
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        stripped = line.strip()

        # blank
        if not stripped:
            i += 1
            continue

        # fenced code block
        if stripped.startswith("```"):
            i += 1
            code_lines: List[str] = []
            while i < n and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1  # closing fence
            # Raw code; sanitize_html escapes any tag-like content.
            code = "\n".join(code_lines)
            html_parts.append(f"<pre><code>{code}</code></pre>")
            continue

        # horizontal rule
        if re.match(r"^(\*\s*){3,}$|^(-\s*){3,}$|^(_\s*){3,}$", stripped):
            html_parts.append("<hr>")
            i += 1
            continue

        # heading
        hm = _HEADING_RE.match(line)
        if hm:
            lvl = min(len(hm.group(1)), 6)
            html_parts.append(
                f"<h{lvl}>{_render_inline(hm.group(2).strip())}</h{lvl}>")
            i += 1
            continue

        # blockquote
        if stripped.startswith(">"):
            quote: List[str] = []
            while i < n and lines[i].strip().startswith(">"):
                quote.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            inner = " ".join(_render_inline(q) for q in quote if q.strip())
            html_parts.append(f"<blockquote><p>{inner}</p></blockquote>")
            continue

        # unordered list
        if re.match(r"^\s*[-*+]\s+", line):
            items: List[str] = []
            while i < n and re.match(r"^\s*[-*+]\s+", lines[i]):
                items.append(re.sub(r"^\s*[-*+]\s+", "", lines[i]))
                i += 1
            lis = "".join(f"<li>{_render_inline(it)}</li>" for it in items)
            html_parts.append(f"<ul>{lis}</ul>")
            continue

        # ordered list
        if re.match(r"^\s*\d+[.)]\s+", line):
            items = []
            while i < n and re.match(r"^\s*\d+[.)]\s+", lines[i]):
                items.append(re.sub(r"^\s*\d+[.)]\s+", "", lines[i]))
                i += 1
            lis = "".join(f"<li>{_render_inline(it)}</li>" for it in items)
            html_parts.append(f"<ol>{lis}</ol>")
            continue

        # paragraph (consume until blank / block boundary)
        para: List[str] = []
        while i < n and lines[i].strip() and not _is_block_start(lines[i]):
            para.append(lines[i].strip())
            i += 1
        text = "<br>".join(_render_inline(p) for p in para)
        html_parts.append(f"<p>{text}</p>")

    return "\n".join(html_parts)


def _is_block_start(line: str) -> bool:
    stripped = line.strip()
    return bool(
        stripped.startswith("```")
        or stripped.startswith(">")
        or _HEADING_RE.match(line)
        or re.match(r"^\s*[-*+]\s+", line)
        or re.match(r"^\s*\d+[.)]\s+", line)
        or re.match(r"^(\*\s*){3,}$|^(-\s*){3,}$|^(_\s*){3,}$", stripped)
    )


def render_markdown(md: str) -> str:
    """Render markdown to sanitized HTML (string). The sanitizer is the
    XSS trust boundary; callers may mark the result safe for templating."""
    from potato.server_utils.html_sanitizer import sanitize_html
    return str(sanitize_html(_to_html(md)))

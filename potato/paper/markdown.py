"""Markdown rendering of the shared dataset report model.

Renders the same description / methods / limitations prose and distribution /
agreement / annotator tables as :mod:`potato.paper.latex`, but as GitHub-flavored
Markdown for a HuggingFace-style dataset card. Because both renderers consume the
one model in :mod:`potato.paper.report`, the README and the cut-paste ``paper.tex``
report agree on every number and caveat.

The dataset-publishing feature (``potato/publish/dataset_card.py``) wraps
:func:`render_sections` with YAML frontmatter, per-column schema docs, licensing, and
citation.
"""

from typing import Any, Dict, List

from potato.paper import report

# Characters that would otherwise be interpreted as Markdown syntax inside prose or
# table cells. Labels/annotator names are user-provided, so escape defensively.
_MD_SPECIALS = "\\`*_[]|<>"


def md_escape(text: Any) -> str:
    out = []
    for ch in str(text):
        if ch in _MD_SPECIALS:
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


class MarkdownStyle(report.Style):
    """Render the report's inline markup as GitHub-flavored Markdown."""

    def escape(self, text: Any) -> str:
        return md_escape(text)

    def emph(self, text: Any) -> str:
        return "*" + md_escape(text) + "*"

    def smallcaps(self, text: Any) -> str:
        # No small-caps in Markdown; render the task name as bold for prominence.
        return "**" + md_escape(text) + "**"

    def citep(self, key: str) -> str:
        return "(" + report.CITATIONS.get(key, key) + ")"

    def citet(self, key: str) -> str:
        return report.CITATIONS_TEXTUAL.get(key, key)

    def alpha(self) -> str:
        return "α"

    def kappa(self) -> str:
        return "κ"

    def math(self, latex: str, plain: str) -> str:
        return plain

    def num(self, value, digits: int) -> str:
        return "—" if value is None else f"{value:.{digits}f}"

    def pct(self, value: float) -> str:
        return f"{value:.1f}%"

    def endash(self) -> str:
        return "–"


_STYLE = MarkdownStyle()

_ALIGN_SEP = {"l": ":--", "r": "--:", "c": ":-:"}


def table_to_markdown(rt: report.RenderedTable) -> str:
    """Render a RenderedTable as a Markdown pipe table with a caption line."""
    def _row(cells: List[str]) -> str:
        # Cells are already Style-rendered; guard any stray pipes.
        return "| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |"

    sep = "| " + " | ".join(_ALIGN_SEP.get(a, ":--") for a in rt.align) + " |"
    lines = [_row(rt.header), sep]
    lines += [_row(r) for r in rt.rows]
    if rt.total_row:
        lines.append(_row(rt.total_row))
    table = "\n".join(lines)
    # Caption already carries its own inline emphasis from the Style, so it is
    # emitted as a plain paragraph (wrapping it in *...* would break the nested
    # emphasis on scheme names).
    return f"{table}\n\n{rt.caption}"


def render_sections(metrics: Dict[str, Any]) -> Dict[str, str]:
    """Return the report as named Markdown fragments the card can arrange.

    Keys: ``summary``, ``annotation_process``, ``label_distributions``,
    ``agreement``, ``annotators``, ``limitations``, ``skipped_note`` (the last is
    an empty string when every scheme is categorical).
    """
    dist_tables = report.distribution_tables(metrics, _STYLE)
    dist_md = "\n\n".join(table_to_markdown(t) for t in dist_tables) \
        if dist_tables else "_No categorical schemes to summarize._"

    skipped = report.skipped_schemes_note(metrics)
    skipped_md = ""
    if skipped:
        skipped_md = (f"The following non-categorical schemes are part of this "
                      f"dataset but are not summarized in the tables above: {skipped}.")

    return {
        "summary": report.description_paragraph(metrics, _STYLE),
        "annotation_process": report.methods_paragraph(metrics, _STYLE),
        "label_distributions": dist_md,
        "agreement": table_to_markdown(report.agreement_table(metrics, _STYLE)),
        "annotators": table_to_markdown(report.annotator_table(metrics, _STYLE)),
        "limitations": report.limitations_paragraph(metrics, _STYLE),
        "skipped_note": skipped_md,
    }


def render_markdown(metrics: Dict[str, Any]) -> str:
    """Compose the full report body as Markdown with H2 section headings."""
    s = render_sections(metrics)
    parts = [
        "## Dataset Summary",
        s["summary"],
        "## Annotation Process",
        s["annotation_process"],
        "## Label Distributions",
        s["label_distributions"],
        "## Inter-Annotator Agreement",
        s["agreement"],
        "## Annotators",
        s["annotators"],
        "## Limitations",
        s["limitations"],
    ]
    if s["skipped_note"]:
        parts += ["## Other Schemes", s["skipped_note"]]
    return "\n\n".join(parts) + "\n"

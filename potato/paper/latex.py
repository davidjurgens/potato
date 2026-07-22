"""LaTeX report rendering for Paper Mode.

Produces a standalone compilable ``paper.tex`` whose sections are delimited by
``%% === BLOCK: name ===`` markers so individual paragraphs and tables can be
cut-pasted straight into a manuscript, plus ``paper.bib`` and one CSV per table.
Pure string templating — no LLM, no network.

The dataset description, methods, limitations, and tables come from the
format-neutral model in :mod:`potato.paper.report`; this module only supplies the
LaTeX :class:`~potato.paper.report.Style` and assembles the document. The Markdown
dataset card (:mod:`potato.paper.markdown`) renders the same model.
"""

import csv
import json
import os
from typing import Any, Dict, List, Optional

from potato.paper import report
from potato.paper.report import BIB as _BIB

_LATEX_SPECIALS = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def latex_escape(text: Any) -> str:
    result = []
    for ch in str(text):
        result.append(_LATEX_SPECIALS.get(ch, ch))
    return "".join(result)


def _fmt(value: Optional[float], digits: int = 2, dash: str = "--") -> str:
    if value is None:
        return dash
    return f"{value:.{digits}f}"


class LatexStyle(report.Style):
    """Render the report's inline markup as LaTeX (matches the original output)."""

    def escape(self, text: Any) -> str:
        return latex_escape(text)

    def emph(self, text: Any) -> str:
        return r"\emph{" + latex_escape(text) + "}"

    def smallcaps(self, text: Any) -> str:
        return r"\textsc{" + latex_escape(text) + "}"

    def citep(self, key: str) -> str:
        return r"\citep{" + key + "}"

    def citet(self, key: str) -> str:
        return r"\citet{" + key + "}"

    def alpha(self) -> str:
        return r"$\alpha$"

    def kappa(self) -> str:
        return r"$\kappa$"

    def math(self, latex: str, plain: str) -> str:
        return "$" + latex + "$"

    def num(self, value: Optional[float], digits: int) -> str:
        return _fmt(value, digits)

    def pct(self, value: float) -> str:
        return f"{value:.1f}" + r"\%"

    def endash(self) -> str:
        return "--"


_STYLE = LatexStyle()


def _block(name: str, body: str) -> str:
    return (f"%% === BLOCK: {name} ===\n{body.rstrip()}\n"
            f"%% === END BLOCK: {name} ===\n")


def _booktabs(caption: str, label: str, header: List[str],
              rows: List[List[str]], align: str,
              total_row: Optional[List[str]] = None) -> str:
    lines = [
        r"\begin{table}[t]",
        r"\centering",
        rf"\begin{{tabular}}{{{align}}}",
        r"\toprule",
        " & ".join(header) + r" \\",
        r"\midrule",
    ]
    lines += [" & ".join(row) + r" \\" for row in rows]
    if total_row:
        lines.append(r"\midrule")
        lines.append(" & ".join(total_row) + r" \\")
    lines += [
        r"\bottomrule",
        r"\end{tabular}",
        rf"\caption{{{caption}}}",
        rf"\label{{{label}}}",
        r"\end{table}",
    ]
    return "\n".join(lines)


def _write_csv(path: str, header: List[str], rows: List[List[Any]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def _table_block(rt: report.RenderedTable, tables_dir: str) -> str:
    """Render a RenderedTable as a booktabs block and write its sidecar CSV."""
    table = _booktabs(
        caption=rt.caption,
        label=f"tab:{rt.label}",
        header=rt.header,
        rows=rt.rows,
        align=rt.align,
        total_row=rt.total_row,
    )
    _write_csv(os.path.join(tables_dir, rt.csv_name), rt.csv_header, rt.csv_rows)
    return _block(f"table-{rt.name}", table)


def render_report(metrics: Dict[str, Any], output_dir: str) -> Dict[str, str]:
    """Write paper.tex, paper.bib, tables/*.csv, summary.json. Returns paths."""
    os.makedirs(output_dir, exist_ok=True)
    tables_dir = os.path.join(output_dir, "tables")
    os.makedirs(tables_dir, exist_ok=True)

    blocks = [
        _block("paragraph-dataset-description",
               "% Dataset description — cut-paste into your Data section\n"
               + report.description_paragraph(metrics, _STYLE)),
        _block("paragraph-annotation-methods",
               "% Annotation methods — cut-paste into your Methods section\n"
               + report.methods_paragraph(metrics, _STYLE)),
    ]
    for rt in report.distribution_tables(metrics, _STYLE):
        blocks.append(_table_block(rt, tables_dir))
    blocks.append(_table_block(report.annotator_table(metrics, _STYLE), tables_dir))
    blocks.append(_table_block(report.agreement_table(metrics, _STYLE), tables_dir))
    blocks.append(_block("paragraph-limitations",
                         "% Limitations — cut-paste into your Limitations section\n"
                         + report.limitations_paragraph(metrics, _STYLE)))
    skipped = report.skipped_schemes_note(metrics)
    if skipped:
        blocks.append(f"% NOTE: non-categorical schemes not covered by these "
                      f"tables: {skipped}\n")

    document = "\n".join([
        "% Generated by Potato Paper Mode (python -m potato.paper).",
        "% Every %% === BLOCK === section below is independently cut-paste-able.",
        "% Compile standalone with: pdflatex paper && bibtex paper && pdflatex paper && pdflatex paper",
        r"\documentclass{article}",
        r"\usepackage{booktabs}",
        r"\usepackage[round]{natbib}",
        r"\usepackage[hidelinks]{hyperref}",
        rf"\title{{Dataset Report: {latex_escape(metrics['task_name'])}}}",
        r"\author{Generated by Potato}",
        r"\begin{document}",
        r"\maketitle",
        "",
        r"\section{Dataset}",
        "",
        "\n".join(blocks),
        "",
        r"\bibliographystyle{plainnat}",
        r"\bibliography{paper}",
        r"\end{document}",
        "",
    ])

    paths = {
        "tex": os.path.join(output_dir, "paper.tex"),
        "bib": os.path.join(output_dir, "paper.bib"),
        "summary": os.path.join(output_dir, "summary.json"),
        "tables_dir": tables_dir,
    }
    with open(paths["tex"], "w", encoding="utf-8") as f:
        f.write(document)
    with open(paths["bib"], "w", encoding="utf-8") as f:
        f.write(_BIB)
    with open(paths["summary"], "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)
    return paths

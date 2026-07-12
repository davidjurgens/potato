"""LaTeX report rendering for Paper Mode.

Produces a standalone compilable ``paper.tex`` whose sections are delimited by
``%% === BLOCK: name ===`` markers so individual paragraphs and tables can be
cut-pasted straight into a manuscript, plus ``paper.bib`` and one CSV per table.
Pure string templating — no LLM, no network.
"""

import csv
import json
import os
from typing import Any, Dict, List, Optional

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


# --------------------------------------------------------------------- prose --


def _description_paragraph(m: Dict[str, Any]) -> str:
    schemes = m["schemes"]
    scheme_bits = []
    for s in schemes:
        labels = ", ".join(latex_escape(l) for l in s["distribution"])
        scheme_bits.append(
            f"\\emph{{{latex_escape(s['name'])}}} "
            f"({latex_escape(s['annotation_type'])}; labels: {labels})")
    total = (f"{m['n_total_items']:,} items, of which {m['n_annotated_instances']:,} "
             f"have been annotated"
             if m["n_total_items"] else
             f"{m['n_annotated_instances']:,} annotated items")
    text = (
        f"The \\textsc{{{latex_escape(m['task_name'])}}} dataset comprises {total}. "
        f"Annotations were collected with Potato \\citep{{pei2022potato}} under "
        f"{len(schemes)} annotation scheme{'s' if len(schemes) != 1 else ''}: "
        + "; ".join(scheme_bits) + ". "
        f"In total, {m['n_annotators']} annotator{'s' if m['n_annotators'] != 1 else ''} "
        f"produced {m['n_label_records']:,} label decisions "
        f"(mean {m['mean_annotations_per_instance']} labels per annotated item)."
    )
    return text


def _methods_paragraph(m: Dict[str, Any]) -> str:
    parts = []
    timing = m["timing"]
    if timing["median_seconds_per_item"] is not None:
        hours = timing["total_person_hours"]
        effort = (f"{hours:.1f} person-hours" if hours >= 1
                  else f"{hours * 60:.0f} person-minutes")
        parts.append(
            f"Annotators spent a median of {timing['median_seconds_per_item']:.0f} "
            f"seconds per item ({effort} in total).")
    for s in m["schemes"]:
        if s["alpha"] is not None:
            parts.append(
                f"Inter-annotator agreement for \\emph{{{latex_escape(s['name'])}}}, "
                f"measured by Krippendorff's $\\alpha$ (nominal) "
                f"\\citep{{krippendorff2004content}} over the "
                f"{s['multi_annotated_units']:,} multiply-annotated units, "
                f"was $\\alpha = {s['alpha']:.3f}$ ({s['alpha_interpretation']}).")
        kappa = s["pairwise_kappa"]
        if kappa["mean"] is not None:
            parts.append(
                f"Mean pairwise Cohen's $\\kappa$ \\citep{{cohen1960coefficient}} "
                f"across the {kappa['n_pairs']} annotator pair"
                f"{'s' if kappa['n_pairs'] != 1 else ''} with overlapping items was "
                f"${kappa['mean']:.3f}$ (range {kappa['min']:.3f}--{kappa['max']:.3f}).")
    if not parts:
        parts.append(
            "No multiply-annotated items were available yet, so agreement "
            "statistics could not be computed.")
    parts.append(
        "Agreement coefficients and their interpretation thresholds follow "
        "\\citet{artstein2008inter}.")
    return " ".join(parts)


def _limitations_paragraph(m: Dict[str, Any]) -> str:
    parts = []
    single = m["instances_single_annotated"]
    if single:
        parts.append(
            f"{single:,} (item, scheme) units carry a single annotation and thus "
            f"contribute no agreement signal; conclusions about their reliability "
            f"rest on the agreement observed over the multiply-annotated subset.")
    low = [s for s in m["schemes"]
           if s["alpha"] is not None and s["alpha"] < 0.667]
    for s in low:
        parts.append(
            f"Agreement on \\emph{{{latex_escape(s['name'])}}} "
            f"($\\alpha = {s['alpha']:.3f}$) falls below Krippendorff's 0.667 "
            f"threshold for tentative conclusions; labels from this scheme should "
            f"be treated as perspectives rather than ground truth.")
    if m["n_annotators"] < 3:
        parts.append(
            f"With only {m['n_annotators']} annotator"
            f"{'s' if m['n_annotators'] != 1 else ''}, chance-corrected agreement "
            f"estimates are unstable and generalization across annotator "
            f"populations cannot be assessed.")
    if not parts:
        parts.append(
            "Standard caveats for annotated corpora apply: labels reflect the "
            "annotator pool and guidelines used, and may not generalize to other "
            "populations or label definitions.")
    return " ".join(parts)


# ------------------------------------------------------------------- tables --


def _distribution_tables(m: Dict[str, Any], tables_dir: str) -> List[str]:
    blocks = []
    for s in m["schemes"]:
        total = s["total_labels"]
        rows = [[latex_escape(label), f"{count:,}", f"{100.0 * count / total:.1f}\\%"]
                for label, count in s["distribution"].items()]
        table = _booktabs(
            caption=f"Label distribution for the "
                    f"\\emph{{{latex_escape(s['name'])}}} scheme.",
            label=f"tab:dist-{s['name']}",
            header=["Label", "Count", "Share"],
            rows=rows,
            align="lrr",
            total_row=["Total", f"{total:,}", "100.0\\%"],
        )
        blocks.append(_block(f"table-distribution-{s['name']}", table))
        _write_csv(os.path.join(tables_dir, f"distribution_{s['name']}.csv"),
                   ["label", "count", "share_pct"],
                   [[label, count, round(100.0 * count / total, 1)]
                    for label, count in s["distribution"].items()])
    return blocks


def _annotator_table(m: Dict[str, Any], tables_dir: str) -> str:
    rows = []
    for a in m["annotators"]:
        rows.append([
            latex_escape(a["annotator"]),
            f"{a['items']:,}",
            f"{a['labels']:,}",
            _fmt(a["median_seconds"], 1),
        ])
    table = _booktabs(
        caption="Annotator statistics. Median time is per item, in seconds, "
                "from behavioral logs where available.",
        label="tab:annotators",
        header=["Annotator", "Items", "Labels", "Median s/item"],
        rows=rows,
        align="lrrr",
    )
    _write_csv(os.path.join(tables_dir, "annotators.csv"),
               ["annotator", "items", "labels", "median_seconds_per_item"],
               [[a["annotator"], a["items"], a["labels"], a["median_seconds"]]
                for a in m["annotators"]])
    return _block("table-annotators", table)


def _agreement_table(m: Dict[str, Any], tables_dir: str) -> str:
    rows = []
    for s in m["schemes"]:
        kappa = s["pairwise_kappa"]
        rows.append([
            latex_escape(s["name"]),
            f"{s['multi_annotated_units']:,}",
            _fmt(s["alpha"], 3),
            _fmt(kappa["mean"], 3),
            latex_escape(s["alpha_interpretation"]),
        ])
    table = _booktabs(
        caption="Inter-annotator agreement per scheme: Krippendorff's $\\alpha$ "
                "(nominal) over multiply-annotated units and mean pairwise "
                "Cohen's $\\kappa$. Interpretation follows "
                "Krippendorff's thresholds (0.667 / 0.8).",
        label="tab:agreement",
        header=["Scheme", "Units ($\\geq 2$ ann.)", "$\\alpha$",
                "Mean $\\kappa$", "Interpretation"],
        rows=rows,
        align="lrrrl",
    )
    _write_csv(os.path.join(tables_dir, "agreement.csv"),
               ["scheme", "multi_annotated_units", "krippendorff_alpha",
                "mean_pairwise_kappa", "interpretation"],
               [[s["name"], s["multi_annotated_units"], s["alpha"],
                 s["pairwise_kappa"]["mean"], s["alpha_interpretation"]]
                for s in m["schemes"]])
    return _block("table-agreement", table)


# ----------------------------------------------------------------- document --

_BIB = r"""@inproceedings{pei2022potato,
  title     = {POTATO: The Portable Text Annotation Tool},
  author    = {Pei, Jiaxin and Ananthasubramaniam, Aparna and Wang, Xingyao and
               Zhou, Naitian and Dedeloudis, Apostolos and Sargent, Jackson and
               Jurgens, David},
  booktitle = {Proceedings of the 2022 Conference on Empirical Methods in
               Natural Language Processing: System Demonstrations},
  year      = {2022},
  url       = {https://aclanthology.org/2022.emnlp-demos.33/}
}

@book{krippendorff2004content,
  title     = {Content Analysis: An Introduction to Its Methodology},
  author    = {Krippendorff, Klaus},
  edition   = {2nd},
  publisher = {Sage},
  year      = {2004}
}

@article{cohen1960coefficient,
  title   = {A coefficient of agreement for nominal scales},
  author  = {Cohen, Jacob},
  journal = {Educational and Psychological Measurement},
  volume  = {20},
  number  = {1},
  pages   = {37--46},
  year    = {1960}
}

@article{artstein2008inter,
  title   = {Inter-coder agreement for computational linguistics},
  author  = {Artstein, Ron and Poesio, Massimo},
  journal = {Computational Linguistics},
  volume  = {34},
  number  = {4},
  pages   = {555--596},
  year    = {2008}
}
"""


def render_report(metrics: Dict[str, Any], output_dir: str) -> Dict[str, str]:
    """Write paper.tex, paper.bib, tables/*.csv, summary.json. Returns paths."""
    os.makedirs(output_dir, exist_ok=True)
    tables_dir = os.path.join(output_dir, "tables")
    os.makedirs(tables_dir, exist_ok=True)

    blocks = [
        _block("paragraph-dataset-description",
               "% Dataset description — cut-paste into your Data section\n"
               + _description_paragraph(metrics)),
        _block("paragraph-annotation-methods",
               "% Annotation methods — cut-paste into your Methods section\n"
               + _methods_paragraph(metrics)),
    ]
    blocks += _distribution_tables(metrics, tables_dir)
    blocks.append(_annotator_table(metrics, tables_dir))
    blocks.append(_agreement_table(metrics, tables_dir))
    blocks.append(_block("paragraph-limitations",
                         "% Limitations — cut-paste into your Limitations section\n"
                         + _limitations_paragraph(metrics)))
    if metrics["skipped_schemes"]:
        names = ", ".join(f"{s['name']} ({s['annotation_type']})"
                          for s in metrics["skipped_schemes"])
        blocks.append(f"% NOTE: non-categorical schemes not covered by these "
                      f"tables: {names}\n")

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

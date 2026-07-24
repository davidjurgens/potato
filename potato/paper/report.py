"""Format-neutral dataset report model shared by Paper Mode and dataset cards.

Paper Mode emits a cut-paste LaTeX report; the dataset-publishing feature emits a
HuggingFace-style Markdown README. Both need to describe the *same* dataset with the
*same* numbers and the *same* caveats. This module holds that single source of truth:
the prose paragraphs (description / methods / limitations) and the tables
(distribution / annotator / agreement) are built here once, parameterised by a
:class:`Style` that renders inline bits (emphasis, citations, math symbols, percent,
dashes) for a target format.

- ``potato/paper/latex.py`` renders with :class:`LatexStyle` (byte-identical to the
  original hand-written LaTeX).
- ``potato/paper/markdown.py`` renders with :class:`MarkdownStyle`.

Also hosts :func:`anonymize` (annotator -> ``A1..An``) so Paper Mode and the publish
pipeline share one implementation, and the ``BIB`` block of citations.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# --------------------------------------------------------------------- styles --


class Style:
    """Render inline markup for a target format.

    Subclasses map the small set of typographic constructs the report needs onto a
    concrete syntax. Prose/table logic in this module calls only these methods, so a
    new output format is a new Style, not new report logic.
    """

    def escape(self, text: Any) -> str:
        """Escape user-provided text (labels, names) for the target format."""
        return str(text)

    def emph(self, text: Any) -> str:
        """Emphasise (scheme names)."""
        raise NotImplementedError

    def smallcaps(self, text: Any) -> str:
        """Small-caps / prominent (the task name)."""
        raise NotImplementedError

    def citep(self, key: str) -> str:
        """Parenthetical citation."""
        raise NotImplementedError

    def citet(self, key: str) -> str:
        """Textual citation."""
        raise NotImplementedError

    def alpha(self) -> str:
        """Krippendorff's alpha symbol."""
        raise NotImplementedError

    def kappa(self) -> str:
        """Cohen's kappa symbol."""
        raise NotImplementedError

    def math(self, latex: str, plain: str) -> str:
        """An inline math fragment (renderer picks the LaTeX or plain form)."""
        raise NotImplementedError

    def num(self, value: Optional[float], digits: int) -> str:
        """A numeric cell; None renders as the format's not-available dash."""
        raise NotImplementedError

    def pct(self, value: float) -> str:
        """A percentage (value already scaled to 0-100)."""
        raise NotImplementedError

    def endash(self) -> str:
        """Range separator, e.g. between kappa min and max."""
        raise NotImplementedError


# ------------------------------------------------------------------- tables --


@dataclass
class RenderedTable:
    """A table whose display cells are already Style-rendered strings.

    ``caption``/``header``/``rows``/``total_row`` are rendered for the target format;
    ``csv_header``/``csv_rows`` carry the raw, unescaped values for the sidecar CSV
    that Paper Mode writes (unchanged from the original).
    """

    name: str                    # block id suffix, e.g. "distribution-sentiment"
    caption: str
    header: List[str]
    rows: List[List[str]]
    align: str
    label: str = ""              # cross-ref label suffix, e.g. "dist-sentiment"
    total_row: Optional[List[str]] = None
    csv_name: str = ""
    csv_header: List[str] = field(default_factory=list)
    csv_rows: List[List[Any]] = field(default_factory=list)


# ------------------------------------------------------------------ prose --


def description_paragraph(m: Dict[str, Any], s: Style) -> str:
    schemes = m["schemes"]
    scheme_bits = []
    for sc in schemes:
        # Declared labels, not observed ones: a label nobody picked is still part of
        # the scheme, and falling back to the observed distribution would print a
        # free-text scheme's raw answers as if they were its label set.
        declared = sc.get("labels") or []
        detail = s.escape(sc["annotation_type"])
        if declared:
            detail += "; labels: " + ", ".join(s.escape(l) for l in declared)
        scheme_bits.append(f"{s.emph(sc['name'])} ({detail})")
    total = (f"{m['n_total_items']:,} items, of which {m['n_annotated_instances']:,} "
             f"have been annotated"
             if m["n_total_items"] else
             f"{m['n_annotated_instances']:,} annotated items")
    return (
        f"The {s.smallcaps(m['task_name'])} dataset comprises {total}. "
        f"Annotations were collected with Potato {s.citep('pei2022potato')} under "
        f"{len(schemes)} annotation scheme{'s' if len(schemes) != 1 else ''}: "
        + "; ".join(scheme_bits) + ". "
        f"In total, {m['n_annotators']} annotator{'s' if m['n_annotators'] != 1 else ''} "
        f"produced {m['n_label_records']:,} label decisions "
        f"(mean {m['mean_annotations_per_instance']} labels per annotated item)."
    )


def methods_paragraph(m: Dict[str, Any], s: Style) -> str:
    parts = []
    timing = m["timing"]
    if timing["median_seconds_per_item"] is not None:
        hours = timing["total_person_hours"]
        effort = (f"{hours:.1f} person-hours" if hours >= 1
                  else f"{hours * 60:.0f} person-minutes")
        parts.append(
            f"Annotators spent a median of {timing['median_seconds_per_item']:.0f} "
            f"seconds per item ({effort} in total).")
    for sc in m["schemes"]:
        if sc["alpha"] is not None:
            alpha_eq = s.math("\\alpha = %.3f" % sc["alpha"],
                              "α = %.3f" % sc["alpha"])
            parts.append(
                f"Inter-annotator agreement for {s.emph(sc['name'])}, "
                f"measured by Krippendorff's {s.alpha()} (nominal) "
                f"{s.citep('krippendorff2004content')} over the "
                f"{sc['multi_annotated_units']:,} multiply-annotated units, "
                f"was {alpha_eq} ({sc['alpha_interpretation']}).")
        kappa = sc["pairwise_kappa"]
        if kappa["mean"] is not None:
            kappa_mean = s.math("%.3f" % kappa["mean"], "%.3f" % kappa["mean"])
            parts.append(
                f"Mean pairwise Cohen's {s.kappa()} "
                f"{s.citep('cohen1960coefficient')} "
                f"across the {kappa['n_pairs']} annotator pair"
                f"{'s' if kappa['n_pairs'] != 1 else ''} with overlapping items was "
                f"{kappa_mean} "
                f"(range {kappa['min']:.3f}{s.endash()}{kappa['max']:.3f}).")
    if not parts:
        parts.append(
            "No multiply-annotated items were available yet, so agreement "
            "statistics could not be computed.")
    parts.append(
        f"Agreement coefficients and their interpretation thresholds follow "
        f"{s.citet('artstein2008inter')}.")
    return " ".join(parts)


def limitations_paragraph(m: Dict[str, Any], s: Style) -> str:
    parts = []
    single = m["instances_single_annotated"]
    if single:
        parts.append(
            f"{single:,} (item, scheme) units carry a single annotation and thus "
            f"contribute no agreement signal; conclusions about their reliability "
            f"rest on the agreement observed over the multiply-annotated subset.")
    low = [sc for sc in m["schemes"]
           if sc["alpha"] is not None and sc["alpha"] < 0.667]
    for sc in low:
        alpha_eq = s.math("\\alpha = %.3f" % sc["alpha"], "α = %.3f" % sc["alpha"])
        parts.append(
            f"Agreement on {s.emph(sc['name'])} "
            f"({alpha_eq}) "
            f"falls below Krippendorff's 0.667 threshold for tentative conclusions; "
            f"labels from this scheme should be treated as perspectives rather than "
            f"ground truth.")
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


# ------------------------------------------------------------------ tables --


def distribution_counts(scheme: Dict[str, Any]) -> List[Any]:
    """Observed counts, plus any declared label that was never chosen (count 0).

    Dropping an unused label would hide it from the report entirely, so a reader
    could not tell it was on offer — and a dead or starved option is exactly the
    class-imbalance signal a dataset report should show. Labels seen in the data but
    absent from the config are kept as well, never discarded.
    """
    dist = scheme["distribution"]
    rows = list(dist.items())   # already ordered most-common first
    for label in (scheme.get("labels") or []):
        if label not in dist:
            rows.append((label, 0))
    return rows


def distribution_tables(m: Dict[str, Any], s: Style) -> List[RenderedTable]:
    tables = []
    for sc in m["schemes"]:
        total = sc["total_labels"]
        counts = distribution_counts(sc)
        rows = [[s.escape(label), f"{count:,}", s.pct(100.0 * count / total)]
                for label, count in counts]
        tables.append(RenderedTable(
            name=f"distribution-{sc['name']}",
            caption=f"Label distribution for the {s.emph(sc['name'])} scheme.",
            header=["Label", "Count", "Share"],
            rows=rows,
            align="lrr",
            label=f"dist-{sc['name']}",
            total_row=["Total", f"{total:,}", s.pct(100.0)],
            csv_name=f"distribution_{sc['name']}.csv",
            csv_header=["label", "count", "share_pct"],
            csv_rows=[[label, count, round(100.0 * count / total, 1)]
                      for label, count in counts],
        ))
    return tables


def annotator_table(m: Dict[str, Any], s: Style) -> RenderedTable:
    rows = [[s.escape(a["annotator"]), f"{a['items']:,}", f"{a['labels']:,}",
             s.num(a["median_seconds"], 1)]
            for a in m["annotators"]]
    return RenderedTable(
        name="annotators",
        caption="Annotator statistics. Median time is per item, in seconds, "
                "from behavioral logs where available.",
        header=["Annotator", "Items", "Labels", "Median s/item"],
        rows=rows,
        align="lrrr",
        label="annotators",
        csv_name="annotators.csv",
        csv_header=["annotator", "items", "labels", "median_seconds_per_item"],
        csv_rows=[[a["annotator"], a["items"], a["labels"], a["median_seconds"]]
                  for a in m["annotators"]],
    )


def agreement_table(m: Dict[str, Any], s: Style) -> RenderedTable:
    geq2 = s.math("\\geq 2", "≥2")
    rows = []
    for sc in m["schemes"]:
        kappa = sc["pairwise_kappa"]
        rows.append([
            s.escape(sc["name"]),
            f"{sc['multi_annotated_units']:,}",
            s.num(sc["alpha"], 3),
            s.num(kappa["mean"], 3),
            s.escape(sc["alpha_interpretation"]),
        ])
    return RenderedTable(
        name="agreement",
        caption=f"Inter-annotator agreement per scheme: Krippendorff's {s.alpha()} "
                f"(nominal) over multiply-annotated units and mean pairwise "
                f"Cohen's {s.kappa()}. Interpretation follows "
                f"Krippendorff's thresholds (0.667 / 0.8).",
        header=["Scheme", f"Units ({geq2} ann.)",
                s.alpha(), f"Mean {s.kappa()}", "Interpretation"],
        rows=rows,
        align="lrrrl",
        label="agreement",
        csv_name="agreement.csv",
        csv_header=["scheme", "multi_annotated_units", "krippendorff_alpha",
                    "mean_pairwise_kappa", "interpretation"],
        csv_rows=[[sc["name"], sc["multi_annotated_units"], sc["alpha"],
                   sc["pairwise_kappa"]["mean"], sc["alpha_interpretation"]]
                  for sc in m["schemes"]],
    )


def skipped_schemes_note(m: Dict[str, Any]) -> Optional[str]:
    """Plain-text note naming non-categorical schemes the tables can't cover."""
    if not m["skipped_schemes"]:
        return None
    return ", ".join(f"{sc['name']} ({sc['annotation_type']})"
                     for sc in m["skipped_schemes"])


# --------------------------------------------------------------- anonymize --


def anon_map(names) -> Dict[str, str]:
    """Stable annotator -> ``A1..An`` mapping, ordered by sorted username.

    The single source of the pseudonym scheme so Paper Mode's report and the
    dataset-publishing splits agree on which annotator is which.
    """
    return {name: f"A{i + 1}" for i, name in enumerate(sorted(set(names)))}


def anonymize(project):
    """Replace annotator names with A1..An (stable by sorted order).

    Shared by Paper Mode's CLI and the dataset-publishing pipeline so the two use
    one mapping. Mutates and returns ``project``.
    """
    mapping = anon_map(project.annotators)
    for record in project.records:
        record.annotator = mapping[record.annotator]
    project.annotators = sorted(mapping.values())
    project.timings = {mapping[k]: v for k, v in project.timings.items()
                       if k in mapping}
    return project


# ---------------------------------------------------------------- citations --

# Human-readable inline forms for Markdown (LaTeX uses \citep/\citet keys directly).
CITATIONS = {
    "pei2022potato": "Pei et al., 2022",
    "krippendorff2004content": "Krippendorff, 2004",
    "cohen1960coefficient": "Cohen, 1960",
    "artstein2008inter": "Artstein and Poesio, 2008",
}

CITATIONS_TEXTUAL = {
    "artstein2008inter": "Artstein and Poesio (2008)",
    "pei2022potato": "Pei et al. (2022)",
    "krippendorff2004content": "Krippendorff (2004)",
    "cohen1960coefficient": "Cohen (1960)",
}

BIB = r"""@inproceedings{pei2022potato,
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

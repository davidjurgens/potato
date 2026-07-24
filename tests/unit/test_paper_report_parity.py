"""Parity tests for the shared Paper Mode report model.

The LaTeX report (``paper.tex``) and the Markdown dataset card both render from the
one model in :mod:`potato.paper.report`. These tests pin that the two agree on the
numbers and that the Markdown carries no LaTeX leakage — so a published README and a
paper's methods section can never quietly disagree.
"""

import os
import re

from potato.paper.collect import collect_project
from potato.paper.latex import render_report
from potato.paper.markdown import MarkdownStyle, render_markdown, render_sections
from potato.paper.metrics import compute_metrics
from potato.paper import report as report_mod
from tests.helpers.test_utils import create_test_directory
from tests.unit.test_paper_mode import build_project


def _metrics_for(states, schemes=None):
    test_dir = create_test_directory("paper_parity")
    config_path = build_project(test_dir, states, schemes=schemes)
    return compute_metrics(collect_project(config_path)), test_dir


class TestMarkdownRender:
    def test_sections_present(self):
        metrics, _ = _metrics_for({
            "u1": {"i0": "Pos", "i1": "Pos", "i2": "Neg"},
            "u2": {"i0": "Pos", "i1": "Neg", "i2": "Neg"},
        })
        md = render_markdown(metrics)
        for heading in ("## Dataset Summary", "## Annotation Process",
                        "## Label Distributions", "## Inter-Annotator Agreement",
                        "## Annotators", "## Limitations"):
            assert heading in md
        # Pipe table rendered
        assert "| Label | Count | Share |" in md
        assert "| :-- | --: | --: |" in md

    def test_no_latex_leakage(self):
        """The card must not contain raw LaTeX commands or math delimiters."""
        metrics, _ = _metrics_for({
            "u1": {"i0": "Pos", "i1": "Pos", "i2": "Neg"},
            "u2": {"i0": "Pos", "i1": "Neg", "i2": "Neg"},
        })
        md = render_markdown(metrics)
        for token in (r"\emph", r"\textsc", r"\citep", r"\citet", r"\alpha",
                      r"\kappa", r"\geq", r"\%", "$"):
            assert token not in md, f"LaTeX token leaked into Markdown: {token!r}"
        # Human-readable symbols and citations instead
        assert "α" in md and "κ" in md
        assert "(Pei et al., 2022)" in md

    def test_unused_label_shown_in_markdown(self):
        metrics, _ = _metrics_for({
            "u1": {"i0": "Pos", "i1": "Pos"},
            "u2": {"i0": "Pos", "i1": "Pos"},
        })
        md = render_markdown(metrics)
        # Declared-but-unused "Neg" appears with a zero row (mirrors the .tex).
        assert re.search(r"\|\s*Neg\s*\|\s*0\s*\|\s*0\.0%\s*\|", md)


class TestLatexMarkdownParity:
    def test_numbers_match_across_formats(self):
        """Every alpha/kappa/count that appears in the .tex must appear in the .md."""
        states = {
            "u1": {"i0": "Pos", "i1": "Pos", "i2": "Neg", "i3": "Neg"},
            "u2": {"i0": "Pos", "i1": "Pos", "i2": "Neg", "i3": "Pos"},
        }
        metrics, test_dir = _metrics_for(states)
        paths = render_report(metrics, os.path.join(test_dir, "paper_export"))
        tex = open(paths["tex"]).read()
        md = render_markdown(metrics)

        scheme = metrics["schemes"][0]
        alpha_str = f"{scheme['alpha']:.3f}"
        kappa_str = f"{scheme['pairwise_kappa']['mean']:.3f}"
        # The same rounded numbers surface in both renderings.
        assert alpha_str in tex and alpha_str in md
        assert kappa_str in tex and kappa_str in md
        # Distribution counts match.
        assert "Pos" in md and "Neg" in md
        assert str(scheme["distribution"]["Pos"]) in md

    def test_skipped_schemes_noted_in_both(self):
        metrics, test_dir = _metrics_for(
            {"u1": {"i0": "Pos"}, "u2": {"i0": "Pos"}},
            schemes=[
                {"annotation_type": "radio", "name": "sentiment",
                 "description": "d", "labels": ["Pos", "Neg"]},
                {"annotation_type": "span", "name": "spans",
                 "description": "d", "labels": ["X"]},
            ])
        paths = render_report(metrics, os.path.join(test_dir, "paper_export"))
        tex = open(paths["tex"]).read()
        md = render_markdown(metrics)
        assert "spans" in tex and "spans" in md


class TestStyleContract:
    def test_markdown_style_num_handles_none(self):
        s = MarkdownStyle()
        assert s.num(None, 3) == "—"
        assert s.num(0.5, 3) == "0.500"
        assert s.pct(62.5) == "62.5%"

    def test_render_sections_keys(self):
        metrics, _ = _metrics_for({"u1": {"i0": "Pos"}, "u2": {"i0": "Pos"}})
        sections = render_sections(metrics)
        assert set(sections) >= {"summary", "annotation_process",
                                 "label_distributions", "agreement",
                                 "annotators", "limitations", "skipped_note"}

    def test_anonymize_is_shared(self):
        """report.anonymize is the single implementation Paper Mode's CLI uses."""
        from potato.paper.__main__ import anonymize as main_anon
        assert main_anon is report_mod.anonymize

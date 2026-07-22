"""
Paper Mode: the dataset that writes its own methods section.

``python -m potato.paper <config.yaml>`` reads an annotation project's output
directory and emits a cut-paste-able LaTeX report — dataset description,
label-distribution / annotator / agreement tables (booktabs), timing stats,
and a limitations paragraph with real numbers — plus a BibTeX file and CSVs
of every table. Fully offline: no server, no LLM, no network.
"""

from potato.paper.collect import ProjectData, collect_project
from potato.paper.latex import render_report
from potato.paper.markdown import render_markdown, render_sections
from potato.paper.metrics import compute_metrics
from potato.paper.report import anonymize

__all__ = ["ProjectData", "collect_project", "compute_metrics", "render_report",
           "render_markdown", "render_sections", "anonymize"]

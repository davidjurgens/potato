"""CLI for Paper Mode.

Usage:
    python -m potato.paper <config.yaml> [-o OUTPUT_DIR] [--no-anonymize]

Reads the project's config + annotation output directory and writes a
cut-paste-able LaTeX dataset report (paper.tex, paper.bib, tables/*.csv,
summary.json). Fully offline.
"""

import argparse
import sys

from potato.paper.collect import collect_project
from potato.paper.latex import render_report
from potato.paper.metrics import compute_metrics
from potato.paper.report import anonymize


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m potato.paper",
        description="Generate a cut-paste LaTeX dataset report from a Potato project.",
    )
    parser.add_argument("config", help="Path to the project's config.yaml")
    parser.add_argument("-o", "--output-dir", default="paper_export",
                        help="Directory for paper.tex/paper.bib/tables (default: paper_export)")
    parser.add_argument("--no-anonymize", action="store_true",
                        help="Keep real annotator usernames instead of A1..An")
    args = parser.parse_args(argv)

    project = collect_project(args.config)
    if not project.records:
        print("No annotations found. Checked "
              f"'{project.config.get('output_annotation_dir', 'annotation_output')}' "
              "relative to the config file — has anyone annotated yet?",
              file=sys.stderr)
        return 1
    if not args.no_anonymize:
        project = anonymize(project)

    metrics = compute_metrics(project)
    paths = render_report(metrics, args.output_dir)

    print(f"Dataset report for '{metrics['task_name']}':")
    print(f"  {metrics['n_annotators']} annotators, "
          f"{metrics['n_annotated_instances']} annotated items, "
          f"{metrics['n_label_records']} label decisions")
    for scheme in metrics["schemes"]:
        alpha = scheme["alpha"]
        alpha_str = f"alpha={alpha:.3f} ({scheme['alpha_interpretation']})" \
            if alpha is not None else "alpha not computable yet"
        print(f"  [{scheme['name']}] {alpha_str}")
    print("Wrote:")
    print(f"  {paths['tex']}")
    print(f"  {paths['bib']}")
    print(f"  {paths['tables_dir']}/*.csv")
    print(f"  {paths['summary']}")
    print("Compile with: pdflatex paper && bibtex paper && pdflatex paper && pdflatex paper")
    return 0


if __name__ == "__main__":
    sys.exit(main())

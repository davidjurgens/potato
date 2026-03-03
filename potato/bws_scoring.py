"""
Best-Worst Scaling Score Estimation

Computes item scores from BWS annotations using three methods:
1. Counting: score = (best_count - worst_count) / appearances  (no dependencies)
2. Bradley-Terry: pairwise comparison model via choix  (requires choix)
3. Plackett-Luce: partial ranking model via choix  (requires choix)

Usage as library:
    from potato.bws_scoring import BwsScorer
    scorer = BwsScorer(annotations, pool_items, id_key)
    scores = scorer.counting()

Usage as CLI:
    python -m potato.bws_scoring --config config.yaml --method counting
"""

import argparse
import csv
import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class BwsScorer:
    """Compute BWS scores from annotations."""

    def __init__(
        self,
        annotations: List[Dict[str, Any]],
        pool_items: List[Dict[str, Any]],
        id_key: str,
        text_key: str = "text",
    ):
        """
        Args:
            annotations: List of annotation dicts, each with:
                - "instance_id": tuple instance ID (e.g. "bws_tuple_0001")
                - "bws_items": list of {source_id, text, position}
                - "best": position label (e.g. "B")
                - "worst": position label (e.g. "D")
                - "annotator": username
            pool_items: Original pool items
            id_key: Key for item IDs in pool_items
            text_key: Key for item text in pool_items
        """
        self.annotations = annotations
        self.pool_items = pool_items
        self.id_key = id_key
        self.text_key = text_key

        # Build item index
        self.item_ids = [str(item[id_key]) for item in pool_items]
        self.item_texts = {
            str(item[id_key]): str(item.get(text_key, ""))
            for item in pool_items
        }
        self.item_id_to_idx = {iid: idx for idx, iid in enumerate(self.item_ids)}

    def _resolve_annotation(
        self, ann: Dict[str, Any]
    ) -> Optional[Tuple[str, str, List[str]]]:
        """Resolve an annotation to (best_source_id, worst_source_id, all_source_ids).

        Returns None if annotation is incomplete.
        """
        best_pos = ann.get("best")
        worst_pos = ann.get("worst")
        bws_items = ann.get("bws_items", [])

        if not best_pos or not worst_pos or not bws_items:
            return None

        pos_to_id = {item["position"]: item["source_id"] for item in bws_items}
        best_id = pos_to_id.get(best_pos)
        worst_id = pos_to_id.get(worst_pos)

        if not best_id or not worst_id:
            return None

        all_ids = [item["source_id"] for item in bws_items]
        return best_id, worst_id, all_ids

    def counting(self) -> Dict[str, Dict[str, Any]]:
        """Counting method: score = (best_count - worst_count) / appearances.

        Returns dict mapping item_id to {score, best_count, worst_count, appearances, text}.
        """
        best_counts = {iid: 0 for iid in self.item_ids}
        worst_counts = {iid: 0 for iid in self.item_ids}
        appearances = {iid: 0 for iid in self.item_ids}

        for ann in self.annotations:
            resolved = self._resolve_annotation(ann)
            if not resolved:
                continue

            best_id, worst_id, all_ids = resolved
            for iid in all_ids:
                if iid in appearances:
                    appearances[iid] += 1
            if best_id in best_counts:
                best_counts[best_id] += 1
            if worst_id in worst_counts:
                worst_counts[worst_id] += 1

        scores = {}
        for iid in self.item_ids:
            app = appearances[iid]
            if app > 0:
                score = (best_counts[iid] - worst_counts[iid]) / app
            else:
                score = 0.0

            scores[iid] = {
                "score": score,
                "best_count": best_counts[iid],
                "worst_count": worst_counts[iid],
                "appearances": app,
                "text": self.item_texts.get(iid, ""),
            }

        return scores

    def bradley_terry(self) -> Dict[str, Dict[str, Any]]:
        """Bradley-Terry model via choix.

        Converts each BWS annotation to pairwise comparisons:
        - Best item beats every other item (K-1 comparisons)
        - Every item beats the worst item (K-1 comparisons)
        """
        try:
            import choix
        except ImportError:
            raise ImportError(
                "Bradley-Terry scoring requires the 'choix' package. "
                "Install it with: pip install choix"
            )

        n_items = len(self.item_ids)
        comparisons = []

        for ann in self.annotations:
            resolved = self._resolve_annotation(ann)
            if not resolved:
                continue

            best_id, worst_id, all_ids = resolved
            best_idx = self.item_id_to_idx.get(best_id)
            worst_idx = self.item_id_to_idx.get(worst_id)

            if best_idx is None or worst_idx is None:
                continue

            # Best beats all others
            for iid in all_ids:
                idx = self.item_id_to_idx.get(iid)
                if idx is not None and idx != best_idx:
                    comparisons.append((best_idx, idx))

            # All others beat worst
            for iid in all_ids:
                idx = self.item_id_to_idx.get(iid)
                if idx is not None and idx != worst_idx:
                    comparisons.append((idx, worst_idx))

        if not comparisons:
            return {
                iid: {"score": 0.0, "text": self.item_texts.get(iid, "")}
                for iid in self.item_ids
            }

        params = choix.ilsr_pairwise(n_items, comparisons, alpha=0.01)

        scores = {}
        for iid in self.item_ids:
            idx = self.item_id_to_idx[iid]
            scores[iid] = {
                "score": float(params[idx]),
                "text": self.item_texts.get(iid, ""),
            }

        return scores

    def plackett_luce(self) -> Dict[str, Dict[str, Any]]:
        """Plackett-Luce model via choix.

        Converts BWS to partial rankings:
        Each annotation yields top-1 (best) selections, processed via ilsr_top1.
        """
        try:
            import choix
        except ImportError:
            raise ImportError(
                "Plackett-Luce scoring requires the 'choix' package. "
                "Install it with: pip install choix"
            )

        n_items = len(self.item_ids)
        # Use pairwise comparisons to approximate partial rankings
        # Best > middle items, middle items > worst
        comparisons = []

        for ann in self.annotations:
            resolved = self._resolve_annotation(ann)
            if not resolved:
                continue

            best_id, worst_id, all_ids = resolved
            best_idx = self.item_id_to_idx.get(best_id)
            worst_idx = self.item_id_to_idx.get(worst_id)

            if best_idx is None or worst_idx is None:
                continue

            middle_ids = [
                iid for iid in all_ids if iid != best_id and iid != worst_id
            ]

            # Best beats all middle items
            for iid in middle_ids:
                idx = self.item_id_to_idx.get(iid)
                if idx is not None:
                    comparisons.append((best_idx, idx))

            # All middle items beat worst
            for iid in middle_ids:
                idx = self.item_id_to_idx.get(iid)
                if idx is not None:
                    comparisons.append((idx, worst_idx))

            # Best beats worst
            comparisons.append((best_idx, worst_idx))

        if not comparisons:
            return {
                iid: {"score": 0.0, "text": self.item_texts.get(iid, "")}
                for iid in self.item_ids
            }

        params = choix.ilsr_pairwise(n_items, comparisons, alpha=0.01)

        scores = {}
        for iid in self.item_ids:
            idx = self.item_id_to_idx[iid]
            scores[iid] = {
                "score": float(params[idx]),
                "text": self.item_texts.get(iid, ""),
            }

        return scores

    def score(self, method: str = "counting") -> Dict[str, Dict[str, Any]]:
        """Compute scores using the specified method."""
        if method == "counting":
            return self.counting()
        elif method == "bradley_terry":
            return self.bradley_terry()
        elif method == "plackett_luce":
            return self.plackett_luce()
        else:
            raise ValueError(
                f"Unknown scoring method: {method}. "
                "Use 'counting', 'bradley_terry', or 'plackett_luce'."
            )


def write_scores(
    scores: Dict[str, Dict[str, Any]],
    output_path: str,
) -> None:
    """Write scores to a TSV file.

    Output columns: item_id, text, score, best_count, worst_count, appearances, rank
    """
    # Sort by score descending
    sorted_items = sorted(scores.items(), key=lambda x: x[1]["score"], reverse=True)

    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(
            ["item_id", "text", "score", "best_count", "worst_count", "appearances", "rank"]
        )
        for rank, (item_id, data) in enumerate(sorted_items, 1):
            writer.writerow([
                item_id,
                data.get("text", ""),
                f"{data['score']:.6f}",
                data.get("best_count", ""),
                data.get("worst_count", ""),
                data.get("appearances", ""),
                rank,
            ])

    logger.info(f"Wrote BWS scores to {output_path}")


def collect_annotations_from_output(
    output_dir: str, bws_schema_name: str, config: dict
) -> List[Dict[str, Any]]:
    """Collect BWS annotations from Potato's output directory.

    Reads annotation files and reconstructs BWS annotation records.
    """
    annotations = []
    pool_items_by_tuple = {}

    # Get pool items from config
    bws_pool = config.get("_bws_pool_items", [])
    id_key = config["item_properties"]["id_key"]

    # We need to read the saved annotations from the output dir
    # Potato saves annotations as {output_dir}/{annotator}.jsonl
    if not os.path.isdir(output_dir):
        logger.warning(f"Output directory not found: {output_dir}")
        return annotations

    for fname in os.listdir(output_dir):
        if not fname.endswith(".jsonl"):
            continue

        annotator = fname.replace(".jsonl", "")
        fpath = os.path.join(output_dir, fname)

        with open(fpath, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue

                instance_id = record.get("id")
                ann_data = record.get("annotation", {})

                # Look for BWS schema annotations
                best_val = None
                worst_val = None
                for schema_name, schema_ann in ann_data.items():
                    if schema_name == bws_schema_name:
                        best_val = schema_ann.get("best")
                        worst_val = schema_ann.get("worst")
                        break

                if not best_val or not worst_val:
                    continue

                # Get BWS items from the instance data
                bws_items = record.get("_bws_items", [])

                annotations.append({
                    "instance_id": instance_id,
                    "bws_items": bws_items,
                    "best": best_val,
                    "worst": worst_val,
                    "annotator": annotator,
                })

    return annotations


def main():
    """CLI entry point for BWS scoring."""
    parser = argparse.ArgumentParser(
        description="Compute BWS scores from Potato annotation output"
    )
    parser.add_argument(
        "--config", required=True, help="Path to Potato config YAML file"
    )
    parser.add_argument(
        "--method",
        default="counting",
        choices=["counting", "bradley_terry", "plackett_luce"],
        help="Scoring method (default: counting)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output TSV file path (default: {output_dir}/bws_scores.tsv)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    # Load config
    import yaml

    with open(args.config, "r") as f:
        config = yaml.safe_load(f)

    output_dir = config.get("output_annotation_dir", "annotation_output")
    id_key = config["item_properties"]["id_key"]
    text_key = config["item_properties"]["text_key"]

    # Find BWS schema name
    bws_schema_name = None
    for scheme in config.get("annotation_schemes", []):
        if scheme.get("annotation_type") == "bws":
            bws_schema_name = scheme["name"]
            break

    if not bws_schema_name:
        print("Error: No BWS annotation scheme found in config", file=sys.stderr)
        sys.exit(1)

    # Load pool items from data files
    pool_items = []
    for data_file in config.get("data_files", []):
        if isinstance(data_file, dict):
            data_file = data_file.get("path")
        if not data_file:
            continue

        with open(data_file, "r") as f:
            if data_file.endswith(".json"):
                pool_items.extend(json.load(f))
            else:
                for line in f:
                    line = line.strip()
                    if line:
                        pool_items.append(json.loads(line))

    # Collect annotations
    annotations = collect_annotations_from_output(output_dir, bws_schema_name, config)

    if not annotations:
        print("No BWS annotations found in output directory", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(annotations)} BWS annotations for {len(pool_items)} pool items")

    # Score
    scorer = BwsScorer(annotations, pool_items, id_key, text_key)
    scores = scorer.score(args.method)

    # Write output
    output_path = args.output or os.path.join(output_dir, "bws_scores.tsv")
    write_scores(scores, output_path)
    print(f"Scores written to {output_path}")


if __name__ == "__main__":
    main()

"""
Adjudication Export CLI

Generate final datasets by merging unanimous agreements and adjudication decisions.

Usage:
    python -m potato.adjudication_export --config config.yaml --output final_dataset.jsonl
    python -m potato.adjudication_export --config config.yaml --output final.csv --format csv
    python -m potato.adjudication_export --config config.yaml --output final.json --format json
"""

import argparse
import csv
import json
import os
import sys
import logging

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="Export adjudicated dataset from Potato annotation project"
    )
    parser.add_argument(
        "--config", required=True,
        help="Path to the Potato config YAML file"
    )
    parser.add_argument(
        "--output", required=True,
        help="Output file path"
    )
    parser.add_argument(
        "--format", choices=["jsonl", "json", "csv"], default="jsonl",
        help="Output format (default: jsonl)"
    )
    parser.add_argument(
        "--include-unresolved", action="store_true",
        help="Include items without adjudication or consensus"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Verbose output"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    # Load config
    from potato.server_utils.config_module import init_config, config
    try:
        init_config(args.config)
    except Exception as e:
        print(f"Error loading config: {e}", file=sys.stderr)
        sys.exit(1)

    # Initialize state managers
    from potato.item_state_management import init_item_state_manager
    from potato.user_state_management import init_user_state_manager

    init_user_state_manager(config)
    init_item_state_manager(config)

    # Load data (this loads items and user annotations from disk)
    # We need a minimal load - just items and user states
    from potato.flask_server import load_instance_data, load_user_data
    load_instance_data(config)
    load_user_data(config)

    # Initialize adjudication manager
    from potato.adjudication import init_adjudication_manager
    adj_mgr = init_adjudication_manager(config)

    if not adj_mgr or not adj_mgr.adj_config.enabled:
        print("Adjudication is not enabled in this config.", file=sys.stderr)
        sys.exit(1)

    # Build queue to compute agreements
    adj_mgr.build_queue()

    # Generate final dataset
    results = adj_mgr.generate_final_dataset()

    # Filter unresolved if not requested
    if not args.include_unresolved:
        results = [r for r in results if r.get("source") != "unresolved"]

    # Write output
    output_path = args.output
    fmt = args.format

    if fmt == "jsonl":
        with open(output_path, "w") as f:
            for item in results:
                f.write(json.dumps(item) + "\n")

    elif fmt == "json":
        with open(output_path, "w") as f:
            json.dump(results, f, indent=2)

    elif fmt == "csv":
        if not results:
            print("No results to export.", file=sys.stderr)
            sys.exit(0)

        # Flatten for CSV
        fieldnames = set()
        flat_results = []
        for item in results:
            flat = {
                "instance_id": item["instance_id"],
                "source": item.get("source", ""),
            }
            # Flatten labels
            labels = item.get("labels", {})
            for schema, value in labels.items():
                if isinstance(value, dict):
                    flat[schema] = json.dumps(value)
                else:
                    flat[schema] = value

            # Add provenance fields
            if "adjudicator" in item:
                flat["adjudicator"] = item["adjudicator"]
            if "confidence" in item:
                flat["confidence"] = item["confidence"]
            if "num_annotators" in item:
                flat["num_annotators"] = item["num_annotators"]

            fieldnames.update(flat.keys())
            flat_results.append(flat)

        # Sort fieldnames for consistent output
        fieldnames = sorted(fieldnames)

        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(flat_results)

    # Summary
    total = len(results)
    unanimous = sum(1 for r in results if r.get("source") == "unanimous")
    adjudicated = sum(1 for r in results if r.get("source") == "adjudicated")
    unresolved = sum(1 for r in results if r.get("source") == "unresolved")

    print(f"\nExport complete: {output_path}")
    print(f"  Total items: {total}")
    print(f"  Unanimous:   {unanimous}")
    print(f"  Adjudicated: {adjudicated}")
    if args.include_unresolved:
        print(f"  Unresolved:  {unresolved}")
    print(f"  Format:      {fmt}")


if __name__ == "__main__":
    main()

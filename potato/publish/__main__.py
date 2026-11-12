"""Command-line interface for dataset publishing.

    # Local archive (no account needed)
    python -m potato.publish config.yaml --target archive -o my_dataset

    # HuggingFace Hub
    python -m potato.publish config.yaml --target huggingface --repo-id org/name --token hf_xxx

    # Zenodo (sandbox draft by default; add --publish --production to mint a DOI)
    python -m potato.publish config.yaml --target zenodo --token zzz

Preprocessing flags mirror the admin wizard. With no flags, the safe defaults
(anonymize on, raw + aggregated splits, survey/PII excluded) apply.
"""

import argparse
import os
import sys

from potato.publish.config import DEFAULT_OPTIONS
from potato.publish.dataset_card import generate_dataset_card
from potato.publish.preprocessing import run_pipeline


def _parse_splits(spec):
    if not spec:
        return None
    parts = [float(p) for p in spec.split("/")]
    if len(parts) == 3:
        return {"train": parts[0], "validation": parts[1], "test": parts[2]}
    if len(parts) == 2:
        return {"train": parts[0], "test": parts[1]}
    raise argparse.ArgumentTypeError(
        "splits must be 'train/val/test' or 'train/test', e.g. 80/10/10")


def _build_parser():
    p = argparse.ArgumentParser(
        prog="python -m potato.publish",
        description="Package and publish a Potato annotation project as a dataset.")
    p.add_argument("config", help="Path to the project's config.yaml")
    p.add_argument("--target", choices=["archive", "huggingface", "zenodo"],
                   default=None, help="Publishing target (default: config or archive)")
    p.add_argument("-o", "--output",
                   help="Archive path (archive target) — extension added automatically")

    # metadata overrides
    p.add_argument("--title", help="Dataset title (overrides config)")
    p.add_argument("--license", help="License id, e.g. cc-by-4.0")
    p.add_argument("--version", help="Dataset version")

    # preprocessing
    g = p.add_argument_group("preprocessing")
    g.add_argument("--no-anonymize", action="store_true",
                   help="Keep real annotator ids (default: anonymize to A1..An)")
    g.add_argument("--aggregation", choices=["majority", "mean", "none"],
                   help="Gold aggregation method (default: majority)")
    g.add_argument("--min-annotators", type=int,
                   help="Keep only instances with at least N annotators")
    g.add_argument("--no-gold", action="store_true", help="Omit the aggregated split")
    g.add_argument("--no-annotations", action="store_true",
                   help="Omit the raw per-annotator split")
    g.add_argument("--no-spans", action="store_true", help="Omit the spans split")
    g.add_argument("--no-items", action="store_true", help="Omit the source-items split")
    g.add_argument("--include-phase", action="store_true",
                   help="Include survey/phase responses (may contain PII)")
    g.add_argument("--scrub-pii", action="store_true",
                   help="Redact emails/phone numbers from item text")
    g.add_argument("--bundle-media", action="store_true",
                   help="Copy referenced media files into the archive")
    g.add_argument("--splits", type=_parse_splits, default=None,
                   help="Train/val/test split, e.g. 80/10/10")
    g.add_argument("--split-seed", type=int, help="Seed for the split (default: 42)")
    g.add_argument("--data-format", choices=["jsonl", "csv", "parquet"],
                   help="Archive data format (default: jsonl)")

    # target credentials
    p.add_argument("--repo-id", help="HuggingFace repo id (org/name)")
    p.add_argument("--token", help="HuggingFace or Zenodo token (or use the env var)")
    p.add_argument("--private", action="store_true", help="HuggingFace: private repo")
    p.add_argument("--production", action="store_true",
                   help="Zenodo: use production instead of the sandbox")
    p.add_argument("--publish", action="store_true",
                   help="Zenodo: publish (mint a DOI) instead of leaving a draft")
    return p


def _options_from_args(args):
    """Build the pipeline options dict, applying only flags the user set."""
    opts = {}
    if args.no_anonymize:
        opts["anonymize"] = False
    if args.aggregation:
        opts["aggregation"] = args.aggregation
    if args.min_annotators is not None:
        opts["min_annotators"] = args.min_annotators
    if args.no_gold:
        opts["include_gold"] = False
    if args.no_annotations:
        opts["include_annotations"] = False
    if args.no_spans:
        opts["include_spans"] = False
    if args.no_items:
        opts["include_items"] = False
    if args.include_phase:
        opts["include_phase_responses"] = True
    if args.scrub_pii:
        opts["scrub_pii"] = True
    if args.bundle_media:
        opts["bundle_media"] = True
    if args.splits:
        opts["splits"] = args.splits
    if args.split_seed is not None:
        opts["split_seed"] = args.split_seed
    if args.data_format:
        opts["data_format"] = args.data_format
    return opts


def _metadata_from_args(args):
    md = {}
    if args.title:
        md["pretty_name"] = args.title
    if args.license:
        md["license"] = args.license
    if args.version:
        md["version"] = args.version
    return md


def main(argv=None):
    args = _build_parser().parse_args(argv)
    if not os.path.exists(args.config):
        print(f"Config not found: {args.config}", file=sys.stderr)
        return 1

    from potato.publish.config import PublishConfig
    import yaml
    with open(args.config) as f:
        raw_config = yaml.safe_load(f) or {}
    pub_cfg = PublishConfig.from_config(raw_config)
    target = args.target or pub_cfg.default_target

    options = _options_from_args(args)
    metadata = _metadata_from_args(args)

    print(f"Building dataset from {args.config} …")
    bundle = run_pipeline(args.config, options=options, metadata_overrides=metadata)
    if not any(bundle.splits.values()):
        print("No annotations found to publish.", file=sys.stderr)
        return 1
    bundle.card_markdown = generate_dataset_card(
        bundle, repo_id=(args.repo_id or ""), target=target)

    counts = ", ".join(f"{n}={c}" for n, c in bundle.split_row_counts().items())
    print(f"  splits: {counts}")
    for w in bundle.warnings:
        print(f"  warning: {w}")

    from potato.publish import targets as tgt
    if target == "huggingface":
        if not args.repo_id:
            print("--repo-id is required for --target huggingface", file=sys.stderr)
            return 1
        print(f"Pushing to HuggingFace: {args.repo_id} …")
        result = tgt.push_to_huggingface(bundle, repo_id=args.repo_id,
                                         token=args.token, private=args.private)
        print(f"Published: {result['url']}")
    elif target == "zenodo":
        print("Depositing to Zenodo "
              f"({'production' if args.production else 'sandbox'}) …")
        result = tgt.deposit_to_zenodo(bundle, token=args.token,
                                       sandbox=not args.production,
                                       publish=args.publish)
        if result.get("doi"):
            print(f"DOI: {result['doi']}")
        print(f"URL: {result.get('url') or result.get('draft_url')}")
    else:  # archive
        out = args.output or (bundle.metadata.pretty_name or "dataset") \
            .replace("/", "_").replace(" ", "_")
        fmt = "gztar" if str(out).endswith((".tar.gz", ".tgz")) else "zip"
        base = out[:-7] if out.endswith(".tar.gz") else \
            (out[:-4] if out.endswith((".zip", ".tgz")) else out)
        path = tgt.write_archive(bundle, base, archive_format=fmt,
                                 data_format=options.get("data_format", "jsonl"))
        print(f"Wrote archive: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

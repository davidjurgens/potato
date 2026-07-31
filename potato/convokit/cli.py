"""
``potato convokit`` — turn a ConvoKit corpus into a Potato data file.

    potato convokit conversations-gone-awry-corpus -o data/awry.jsonl
    potato convokit ~/.convokit/saved-corpora/friends-corpus --unit utterance -o data/f.jsonl
    potato convokit switchboard-corpus --dry-run
    potato convokit --list-corpora

A corpus can be named (downloaded and cached where ConvoKit itself caches, so an
existing install shares the cache), or given as a directory or ``.zip`` already on
disk. A path that exists always wins over a manifest name.

``--dry-run`` reports what was read — conversation and utterance counts, whether
the corpus uses the legacy key names, which metadata was dropped or skipped, and
how many reply-to links dangled or cycled — without writing anything. It is the
quickest answer to "why is my thread flat".

Output defaults to JSON Lines rather than a JSON array, and that default matters:
Potato's export CLI reads data files line by line, so a pretty-printed array
exports with no items at all and the ConvoKit exporter would lose the provenance
it needs to map annotations back onto the corpus.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .config_gen import SuggestOptions, generate_config
from .download import (
    ConvoKitDownloadError,
    DEFAULT_MAX_BYTES,
    corpus_versions,
    default_data_dir,
    list_corpora,
    resolve,
)
from .items import ItemBuildError, ItemOptions, build_items
from .reader import ConvoKitReadError, DEFAULT_DROPPED_META, read_corpus

logger = logging.getLogger(__name__)

__all__ = ["build_parser", "main"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="potato convokit",
        description="Convert a ConvoKit corpus into a Potato data file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  potato convokit conversations-gone-awry-corpus -o data/awry.jsonl\n"
            "  potato convokit wikipedia-politeness-corpus --unit utterance "
            "--context-window 0 -o data/pol.jsonl\n"
            "  potato convokit ./my-corpus --dry-run\n"
            "  potato convokit --list-corpora\n"
        ),
    )

    parser.add_argument(
        "corpus",
        nargs="?",
        help="Corpus name (downloaded), or a path to a corpus directory or .zip",
    )

    out = parser.add_argument_group("output")
    out.add_argument("-o", "--output", help="Where to write the data file")
    out.add_argument(
        "--format",
        choices=["jsonl", "json"],
        default="jsonl",
        help=(
            "jsonl (default) writes one item per line. json writes an array, which "
            "Potato's export CLI cannot read back — only use it for inspection."
        ),
    )
    out.add_argument(
        "--emit-config",
        metavar="PATH",
        help="Also write a starter config.yaml built from the corpus's own metadata",
    )
    out.add_argument(
        "--print-config",
        action="store_true",
        help="Print the starter config to stdout instead of writing it",
    )

    shape = parser.add_argument_group("item shape")
    shape.add_argument(
        "--unit",
        choices=["conversation", "utterance"],
        default="conversation",
        help="One item per conversation (default) or per utterance",
    )
    shape.add_argument(
        "--context-window",
        type=int,
        default=2,
        metavar="K",
        help="utterance unit: turns of preceding context (default: 2)",
    )
    shape.add_argument(
        "--context-after",
        type=int,
        default=None,
        metavar="K",
        help="utterance unit: turns of following context (default: same as --context-window)",
    )
    shape.add_argument(
        "--context-mode",
        choices=["ancestors", "linear", "auto"],
        default="auto",
        help=(
            "auto (default) walks the reply chain for threaded corpora and takes "
            "adjacent turns for linear ones"
        ),
    )
    shape.add_argument(
        "--order",
        choices=["thread", "chronological"],
        default="thread",
        help="thread (default) keeps replies next to what they reply to",
    )
    shape.add_argument("--field", default="conversation", help="Key for the turns list")
    shape.add_argument(
        "--tree-field",
        default="conversation_tree",
        help="Key for the nested tree ('' to omit and halve the file size)",
    )
    shape.add_argument("--text-field", default="text", help="Key for the flat text rendering")
    shape.add_argument(
        "--raw-ids",
        action="store_true",
        help="Use bare ConvoKit ids as item ids, without a convo:/utt: prefix",
    )
    shape.add_argument(
        "--no-turn-meta",
        action="store_true",
        help="Omit per-turn metadata (smaller files; disables per-turn meta chips)",
    )
    shape.add_argument(
        "--promote-meta",
        default="",
        metavar="A,B",
        help="Lift these scalar metadata fields to top-level item keys",
    )

    select = parser.add_argument_group("selection")
    select.add_argument("--max-conversations", type=int, help="Read at most this many conversations")
    select.add_argument("--max-items", type=int, help="Emit at most this many items")
    select.add_argument("--sample", type=int, metavar="N", help="Randomly sample N items")
    select.add_argument("--seed", type=int, default=0, help="Seed for --sample (default: 0)")
    select.add_argument(
        "--split",
        help="Keep only conversations whose 'split' metadata matches (e.g. train)",
    )
    select.add_argument(
        "--filter",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Repeatable. KEY is convo.<field> or utt.<field>",
    )

    meta = parser.add_argument_group("metadata")
    meta.add_argument(
        "--keep-meta", default="", metavar="A,B", help="Keep these normally-dropped fields"
    )
    meta.add_argument(
        "--drop-meta",
        default="",
        metavar="A,B",
        help=f"Replace the default drop list ({', '.join(sorted(DEFAULT_DROPPED_META))})",
    )
    meta.add_argument(
        "--load-binary-meta",
        action="store_true",
        help=(
            "Unpickle -bin.p metadata sidecars. Off by default: unpickling data "
            "downloaded from the internet executes arbitrary code."
        ),
    )
    meta.add_argument(
        "--load-info",
        action="append",
        default=[],
        metavar="FIELD[:OBJTYPE]",
        help="Merge an info.<FIELD>.jsonl overlay. Repeatable.",
    )

    net = parser.add_argument_group("download")
    net.add_argument("--data-dir", help=f"Corpus cache (default: {default_data_dir()})")
    net.add_argument("--no-download", action="store_true", help="Never fetch; local paths only")
    net.add_argument("--force-download", action="store_true", help="Re-download even if cached")
    net.add_argument("--refresh", action="store_true", help="Refetch the corpus manifest")
    net.add_argument(
        "--max-download-bytes",
        type=int,
        default=DEFAULT_MAX_BYTES,
        help=f"Refuse downloads larger than this (default: {DEFAULT_MAX_BYTES})",
    )
    net.add_argument(
        "--allow-host",
        action="append",
        default=[],
        metavar="HOST",
        help="Additional host to accept downloads from. Repeatable.",
    )

    parser.add_argument("--list-corpora", action="store_true", help="List downloadable corpora")
    parser.add_argument(
        "--dry-run", action="store_true", help="Report what would be produced; write nothing"
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="Only report errors")

    return parser


def _csv(value: str) -> List[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def _parse_filters(raw: Sequence[str]) -> List[Tuple[str, str, str]]:
    """``convo.split=train`` -> ``("conversation", "split", "train")``."""
    out: List[Tuple[str, str, str]] = []
    for entry in raw:
        if "=" not in entry:
            raise ItemBuildError(
                f"--filter expects KEY=VALUE, got {entry!r} "
                "(for example: --filter convo.split=train)"
            )
        key, _, value = entry.partition("=")
        scope, _, name = key.strip().partition(".")
        if scope in ("convo", "conversation"):
            out.append(("conversation", name, value.strip()))
        elif scope in ("utt", "utterance"):
            out.append(("utterance", name, value.strip()))
        else:
            raise ItemBuildError(
                f"--filter key must start with 'convo.' or 'utt.', got {key!r}"
            )
    return out


def _matches(actual: Any, expected: str) -> bool:
    """Compare loosely — filters come from a shell, so everything arrives a string."""
    if isinstance(actual, bool):
        return str(actual).lower() == expected.lower()
    return str(actual) == expected


def _apply_filters(corpus, filters, split: Optional[str]) -> Tuple[int, int]:
    """Drop non-matching conversations/utterances in place. Returns what was removed."""
    convo_filters = [(n, v) for scope, n, v in filters if scope == "conversation"]
    utt_filters = [(n, v) for scope, n, v in filters if scope == "utterance"]
    if split:
        convo_filters.append(("split", split))

    dropped_convos = 0
    if convo_filters:
        for convo_id in list(corpus.conversations):
            meta = corpus.conversations[convo_id].meta
            if not all(_matches(meta.get(n), v) for n, v in convo_filters):
                for uid in corpus.conversations[convo_id].utterance_ids:
                    corpus.utterances.pop(uid, None)
                del corpus.conversations[convo_id]
                dropped_convos += 1

    dropped_utts = 0
    if utt_filters:
        for uid in list(corpus.utterances):
            meta = corpus.utterances[uid].meta
            if not all(_matches(meta.get(n), v) for n, v in utt_filters):
                convo = corpus.conversations.get(corpus.utterances[uid].conversation_id)
                if convo and uid in convo.utterance_ids:
                    convo.utterance_ids.remove(uid)
                del corpus.utterances[uid]
                dropped_utts += 1

    return dropped_convos, dropped_utts


def _report(corpus, items: List[Dict[str, Any]], opts: ItemOptions) -> str:
    dangling = sum(i.get("_convokit", {}).get("dangling_reply_to", 0) for i in items)
    cycles = sum(i.get("_convokit", {}).get("broken_cycles", 0) for i in items)
    turns = sum(len(i.get(opts.field_name, ())) for i in items)
    depths = [t.get("depth", 0) for i in items for t in i.get(opts.field_name, ())]

    lines = [
        f"corpus:         {corpus.name}"
        + (f" (version {corpus.version})" if corpus.version is not None else ""),
        f"path:           {corpus.path}",
        f"key format:     {'LEGACY (user/root/users.json)' if corpus.legacy else 'modern'}",
        f"read:           {len(corpus.utterances)} utterances, "
        f"{len(corpus.conversations)} conversations, {len(corpus.speakers)} speakers",
        f"items:          {len(items)} ({opts.unit} unit), {turns} turns total",
        f"max reply depth: {max(depths) if depths else 0}",
    ]
    if corpus.dropped_meta_fields:
        lines.append(f"dropped meta:   {', '.join(sorted(corpus.dropped_meta_fields))}")
    if corpus.skipped_binary_fields:
        lines.append(f"skipped binary: {', '.join(sorted(corpus.skipped_binary_fields))}")
    if dangling:
        lines.append(f"dangling reply-to: {dangling} (treated as thread roots)")
    if cycles:
        lines.append(f"reply cycles:   {cycles} (broken by re-rooting)")
    if corpus.warnings:
        lines.append("warnings:")
        for warning in corpus.warnings[:10]:
            lines.append(f"  - {warning}")
        if len(corpus.warnings) > 10:
            lines.append(f"  ... and {len(corpus.warnings) - 10} more")
    return "\n".join(lines)


def _write_items(path: str, items: List[Dict[str, Any]], fmt: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        if fmt == "json":
            json.dump(items, f, indent=1, ensure_ascii=False)
            f.write("\n")
        else:
            for item in items:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.ERROR if args.quiet else logging.INFO,
        format="%(message)s",
    )

    try:
        if args.list_corpora:
            return _list_corpora(args)

        if not args.corpus:
            parser.error("a corpus name or path is required (or use --list-corpora)")
        if not args.output and not args.dry_run and not args.print_config:
            parser.error("-o/--output is required (or use --dry-run)")

        return _convert(args)

    except (ConvoKitReadError, ConvoKitDownloadError, ItemBuildError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


def _list_corpora(args) -> int:
    urls = list_corpora(data_dir=args.data_dir, refresh=args.refresh)
    try:
        versions = corpus_versions(data_dir=args.data_dir)
    except ConvoKitDownloadError:
        versions = {}
    print(f"{len(urls)} ConvoKit corpora available:\n")
    for name in sorted(urls):
        version = versions.get(name)
        suffix = f"  (v{version})" if version is not None else ""
        print(f"  {name}{suffix}")
    print(
        "\nDynamically-resolved names (subreddit-*, wikiconv-*, supreme-<year>) are "
        "not listed and must be fetched with ConvoKit itself; see "
        "'potato convokit --help'."
    )
    return 0


def _convert(args) -> int:
    corpus_dir = resolve(
        args.corpus,
        data_dir=args.data_dir,
        allow_download=not args.no_download,
        force=args.force_download,
        refresh=args.refresh,
        max_bytes=args.max_download_bytes,
        allow_hosts=tuple(args.allow_host),
        quiet=args.quiet,
    )

    drop_meta = _csv(args.drop_meta) or list(DEFAULT_DROPPED_META)
    corpus = read_corpus(
        corpus_dir,
        load_binary_meta=args.load_binary_meta,
        drop_meta=drop_meta,
        keep_meta=_csv(args.keep_meta),
        info_fields=args.load_info or None,
        max_conversations=args.max_conversations,
    )

    filters = _parse_filters(args.filter)
    dropped_convos, dropped_utts = _apply_filters(corpus, filters, args.split)
    if dropped_convos or dropped_utts:
        logger.info(
            "Filters removed %d conversation(s) and %d utterance(s)",
            dropped_convos,
            dropped_utts,
        )

    opts = ItemOptions(
        unit=args.unit,
        field_name=args.field,
        tree_field=args.tree_field or None,
        text_field=args.text_field,
        id_prefix=not args.raw_ids,
        order=args.order,
        context_before=args.context_window,
        context_after=(
            args.context_window if args.context_after is None else args.context_after
        ),
        context_mode=args.context_mode,
        promote_meta=_csv(args.promote_meta),
        include_turn_meta=not args.no_turn_meta,
    )

    items = build_items(corpus, opts, limit=args.max_items)

    if args.sample is not None and args.sample < len(items):
        rng = random.Random(args.seed)
        items = rng.sample(items, args.sample)

    if args.dry_run:
        print(_report(corpus, items, opts))
        print("\n(dry run — nothing written)")
        return 0

    if args.output:
        _write_items(args.output, items, args.format)
        if not args.quiet:
            print(_report(corpus, items, opts))
            print(f"\nwrote {len(items)} items to {args.output}")

    if args.emit_config or args.print_config:
        data_ref = (
            os.path.basename(args.output) if args.output else "data/items.jsonl"
        )
        if args.emit_config and args.output:
            # Reference the data file relative to the config's own directory.
            data_ref = os.path.relpath(
                os.path.abspath(args.output),
                os.path.dirname(os.path.abspath(args.emit_config)) or ".",
            )
        config_text = generate_config(
            corpus,
            opts,
            data_ref,
            suggest_opts=SuggestOptions(),
        )
        if args.print_config:
            print("\n" + config_text)
        if args.emit_config:
            parent = os.path.dirname(os.path.abspath(args.emit_config))
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(args.emit_config, "w", encoding="utf-8") as f:
                f.write(config_text)
            if not args.quiet:
                print(f"wrote starter config to {args.emit_config}")

    return 0


if __name__ == "__main__":   # pragma: no cover
    sys.exit(main(sys.argv[1:]))

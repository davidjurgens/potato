"""
``potato transcripts`` — turn a folder of transcripts into a Potato data file.

The normalizer can read a transcript in any supported format, but a Potato task
needs a *data file*: one row per item, with an id and the content to annotate.
Producing that by hand for two hundred interviews is the tedious step this
command removes.

    potato transcripts ./whisper_out --media-dir ./audio -o data/interviews.json
    potato transcripts './captions/*.vtt' --media-url-prefix https://cdn.example.org/ \\
        -o data/talks.json
    potato transcripts ./whisper_out --dry-run

``--dry-run`` reports what each file was detected as without writing anything,
which is also the fastest way to answer "why did my transcript come out as one
big bubble" — if the detected format is ``plain text``, the timings were never
found.

Media is paired to transcripts **by basename**: ``talk_01.srt`` finds
``talk_01.mp3`` in ``--media-dir``. Transcripts that name their own media (SPoRC
rows, an EAF media descriptor) keep it unless a pairing overrides it.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

from potato.server_utils.transcripts import (
    TRANSCRIPT_EXTENSIONS,
    TranscriptError,
    detect_format,
    normalize_transcript,
)

#: Extensions scanned when the input is a directory. ``.txt`` is excluded here —
#: it is accepted when a file is named explicitly, but scanning a folder for it
#: would sweep up READMEs and notes.
SCAN_EXTENSIONS = frozenset(TRANSCRIPT_EXTENSIONS - {".txt"})

#: Media files a transcript can be paired with, in preference order.
MEDIA_EXTENSIONS = (
    ".mp3", ".wav", ".m4a", ".ogg", ".oga", ".opus", ".flac", ".aac",
    ".mp4", ".webm", ".mov", ".mkv",
)


# ---------------------------------------------------------------------------
# Input discovery
# ---------------------------------------------------------------------------

def collect_inputs(patterns: Sequence[str], *, recursive: bool = False) -> List[str]:
    """Expand paths, directories, and globs into a sorted list of files.

    Duplicates are removed (a file can match more than one pattern) and the
    result is sorted so the output data file is stable across runs — item order
    should not depend on filesystem iteration order.
    """
    found: List[str] = []

    for pattern in patterns:
        if os.path.isdir(pattern):
            walk = "**/*" if recursive else "*"
            candidates = glob.glob(os.path.join(pattern, walk), recursive=recursive)
            found.extend(
                path for path in candidates
                if os.path.isfile(path)
                and os.path.splitext(path)[1].lower() in SCAN_EXTENSIONS
            )
        elif os.path.isfile(pattern):
            found.append(pattern)
        else:
            found.extend(
                path for path in glob.glob(pattern, recursive=recursive)
                if os.path.isfile(path)
            )

    return sorted(set(os.path.normpath(p) for p in found))


def item_id_for(path: str, *, prefix: str = "") -> str:
    """Derive an item id from a filename.

    Whisper writes ``interview_01.mp3.json`` for ``interview_01.mp3``, and
    WhisperX adds suffixes, so trailing media extensions are stripped too —
    otherwise ids read as ``interview_01.mp3``.
    """
    stem = os.path.basename(path)
    stem, _ext = os.path.splitext(stem)
    root, inner_ext = os.path.splitext(stem)
    if inner_ext.lower() in MEDIA_EXTENSIONS:
        stem = root
    return f"{prefix}{stem}"


def find_media(
    transcript_path: str,
    media_dir: Optional[str],
    url_prefix: Optional[str],
) -> Optional[str]:
    """Locate the media that goes with a transcript.

    ``--media-url-prefix`` wins when both are given, since a URL prefix means
    the annotator's browser fetches media from somewhere other than disk.
    """
    stem = item_id_for(transcript_path)

    if url_prefix:
        if media_dir:
            local = _media_in_dir(stem, media_dir)
            if local:
                return url_prefix.rstrip("/") + "/" + os.path.basename(local)
        # No directory to confirm an extension against — assume mp3, the
        # overwhelmingly common case for hosted speech audio.
        return url_prefix.rstrip("/") + "/" + stem + ".mp3"

    if media_dir:
        return _media_in_dir(stem, media_dir)

    return None


def _media_in_dir(stem: str, media_dir: str) -> Optional[str]:
    for ext in MEDIA_EXTENSIONS:
        candidate = os.path.join(media_dir, stem + ext)
        if os.path.isfile(candidate):
            return candidate
    return None


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------

def convert_file(
    path: str,
    *,
    media_dir: Optional[str] = None,
    url_prefix: Optional[str] = None,
    id_prefix: str = "",
    field: str = "conversation",
    speaker_key: str = "speaker",
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """Convert one transcript file into an item dict plus a report.

    Returns ``(item, report)``; ``item`` is ``None`` when nothing usable came
    out, in which case the report explains why. The report is what ``--dry-run``
    prints and is deliberately produced on every run, not only dry ones, so the
    summary at the end can flag files that yielded nothing.
    """
    report: Dict[str, Any] = {
        "path": path,
        "format": "unreadable",
        "turns": 0,
        "speakers": [],
        "duration": 0.0,
        "media": None,
        "error": None,
    }

    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            content = handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        report["error"] = str(exc)
        return None, report

    report["format"] = detect_format(content)

    try:
        normalized = normalize_transcript(content, speaker_key=speaker_key)
    except TranscriptError as exc:
        report["error"] = str(exc)
        return None, report

    turns = normalized.get("turns") or []
    report["turns"] = len(turns)
    report["speakers"] = sorted(
        {t["speaker"] for t in turns if t.get("speaker")}
    )
    report["duration"] = max((t.get("end") or 0.0) for t in turns) if turns else 0.0

    if not turns:
        report["error"] = "no turns parsed"
        return None, report

    # Explicit pairing beats whatever the transcript named for itself.
    media = find_media(path, media_dir, url_prefix) or normalized.get("audio")
    report["media"] = media

    payload: Dict[str, Any] = {"turns": turns}
    if media:
        payload["audio"] = media

    item = {
        "id": item_id_for(path, prefix=id_prefix),
        field: payload,
    }
    return item, report


def write_output(items: List[Dict[str, Any]], output: str, fmt: str) -> None:
    parent = os.path.dirname(os.path.abspath(output))
    if parent:
        os.makedirs(parent, exist_ok=True)

    with open(output, "w", encoding="utf-8") as handle:
        if fmt == "jsonl":
            for item in items:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")
        else:
            json.dump(items, handle, ensure_ascii=False, indent=2)
            handle.write("\n")


def config_stanza(output: str, field: str) -> str:
    """A ready-to-paste config fragment for the file just written."""
    return f"""# Add to your config.yaml:

data_files:
  - "{output}"

item_properties:
  id_key: id
  text_key: {field}

instance_display:
  fields:
    - key: {field}
      type: audio_dialogue
      label: "Transcript"
      span_target: true
      display_options:
        show_timestamps: true
        allow_speaker_assignment: auto
"""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="potato transcripts",
        description=(
            "Convert ASR output and subtitle files into a Potato data file. "
            "Supports Whisper/WhisperX/whisper.cpp JSON and TSV, SRT, WebVTT, "
            "SubStation Alpha, TTML, YouTube json3/srv, AWS Transcribe, "
            "Deepgram, AssemblyAI, Rev.ai, CTM, Praat TextGrid, and ELAN EAF."
        ),
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        help="Transcript files, directories, or glob patterns.",
    )
    parser.add_argument(
        "-o", "--output",
        help="Where to write the data file. Required unless --dry-run.",
    )
    parser.add_argument(
        "--format",
        choices=["json", "jsonl"],
        default="json",
        help="Output format (default: json).",
    )
    parser.add_argument(
        "--media-dir",
        help="Directory of audio/video files to pair with transcripts by basename.",
    )
    parser.add_argument(
        "--media-url-prefix",
        help="Base URL for media, e.g. https://cdn.example.org/audio.",
    )
    parser.add_argument(
        "--field",
        default="conversation",
        help="Item field the transcript is stored under (default: conversation).",
    )
    parser.add_argument(
        "--id-prefix",
        default="",
        help="String prepended to every generated item id.",
    )
    parser.add_argument(
        "--speaker-key",
        default="speaker",
        help="Source key holding the speaker label (default: speaker).",
    )
    parser.add_argument(
        "-r", "--recursive",
        action="store_true",
        help="Recurse into subdirectories when scanning a directory.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report the detected format and turn count per file; write nothing.",
    )
    parser.add_argument(
        "--emit-config",
        action="store_true",
        help="Also print a config.yaml fragment for the generated data file.",
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Suppress the per-file report.",
    )
    return parser


def _format_report(report: Dict[str, Any]) -> str:
    name = os.path.basename(report["path"])
    if report["error"] and not report["turns"]:
        return f"  {name:<40} {report['format']:<24} SKIPPED ({report['error']})"

    speakers = report["speakers"]
    if speakers:
        shown = ", ".join(speakers[:3])
        if len(speakers) > 3:
            shown += f", +{len(speakers) - 3}"
        speaker_note = f"{len(speakers)} speaker(s): {shown}"
    else:
        speaker_note = "undiarized"

    return (
        f"  {name:<40} {report['format']:<24} "
        f"{report['turns']:>4} turns  {report['duration']:>7.1f}s  {speaker_note}"
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.dry_run and not args.output:
        parser.error("-o/--output is required unless --dry-run is given")

    paths = collect_inputs(args.inputs, recursive=args.recursive)
    if not paths:
        print("No transcript files matched.", file=sys.stderr)
        return 1

    items: List[Dict[str, Any]] = []
    reports: List[Dict[str, Any]] = []

    for path in paths:
        item, report = convert_file(
            path,
            media_dir=args.media_dir,
            url_prefix=args.media_url_prefix,
            id_prefix=args.id_prefix,
            field=args.field,
            speaker_key=args.speaker_key,
        )
        reports.append(report)
        if item is not None:
            items.append(item)

    if not args.quiet:
        print(f"Scanned {len(paths)} file(s):")
        for report in reports:
            print(_format_report(report))

    skipped = [r for r in reports if r["error"]]
    total_turns = sum(r["turns"] for r in reports)
    without_media = [r for r in reports if not r["media"] and not r["error"]]

    print(
        f"\n{len(items)} item(s), {total_turns} turn(s)."
        + (f" {len(skipped)} file(s) skipped." if skipped else "")
    )
    if without_media:
        # Worth saying plainly: turns render, but there is nothing to play.
        print(
            f"{len(without_media)} item(s) have no media. "
            "Pass --media-dir or --media-url-prefix to enable playback."
        )

    if args.dry_run:
        print("\nDry run — nothing written.")
        return 0 if items else 1

    if not items:
        print("Nothing to write.", file=sys.stderr)
        return 1

    write_output(items, args.output, args.format)
    print(f"Wrote {args.output}")

    if args.emit_config:
        print()
        print(config_stanza(args.output, args.field))

    return 0


if __name__ == "__main__":
    sys.exit(main())

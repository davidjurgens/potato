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

With no transcript at all, ``--transcribe`` runs Whisper on the local machine
over a folder of audio or video and produces the data file in one step::

    potato transcripts ./interviews --transcribe --asr-model small.en \\
        -o data/interviews.json

That needs ``pip install "potato-annotation[transcribe]"``. Each transcript is
written beside its media as ``<name>.whisper.json`` and reused on later runs.
Whisper reports what was said, not who said it, so every turn arrives
undiarized and the annotator assigns speakers.

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
    AUDIO_EXTENSIONS,
    TRANSCRIPT_EXTENSIONS,
    DiarizationError,
    TranscriptError,
    TranscriptionError,
    assign_speakers,
    cache_path_for,
    detect_format,
    diarize_file,
    looks_like_media,
    normalize_transcript,
    transcribe_file,
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

#: Suffix :func:`potato.server_utils.transcripts.cache_path_for` writes. A
#: directory scan skips these: on the second run of ``--transcribe`` over a
#: folder of audio, the cache sits beside the media and would otherwise be
#: collected as a transcript in its own right, duplicating every item.
CACHE_SUFFIX = ".whisper.json"


def is_cache_file(path: str) -> bool:
    """Whether *path* is a transcription cache written by a previous run."""
    return os.path.basename(path).lower().endswith(CACHE_SUFFIX)


def collect_inputs(
    patterns: Sequence[str],
    *,
    recursive: bool = False,
    include_media: bool = False,
) -> List[str]:
    """Expand paths, directories, and globs into a sorted list of files.

    Duplicates are removed (a file can match more than one pattern) and the
    result is sorted so the output data file is stable across runs — item order
    should not depend on filesystem iteration order.

    Args:
        include_media: Also pick up audio and video files when scanning a
            directory. Only useful with ``--transcribe``; without it a folder
            of mp3s would be collected and then skipped as unreadable.
    """
    found: List[str] = []
    scan_for = SCAN_EXTENSIONS | AUDIO_EXTENSIONS if include_media else SCAN_EXTENSIONS

    for pattern in patterns:
        if os.path.isdir(pattern):
            walk = "**/*" if recursive else "*"
            candidates = glob.glob(os.path.join(pattern, walk), recursive=recursive)
            found.extend(
                path for path in candidates
                if os.path.isfile(path)
                and os.path.splitext(path)[1].lower() in scan_for
                and not is_cache_file(path)
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

def _write_cache(cache: str, payload: Dict[str, Any]) -> None:
    parent = os.path.dirname(os.path.abspath(cache))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(cache, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


#: Transcription options recorded in the cache, and compared against on reuse.
#: ``device`` and ``compute_type`` are deliberately excluded: they change how
#: the same model is executed, not which model produced the text, and
#: re-decoding an hour of audio because someone moved to a GPU would be a poor
#: trade.
_ASR_SIGNATURE_KEYS = ("model", "language", "vad_filter", "word_timestamps")


def _signature(options: Dict[str, Any], keys) -> Dict[str, Any]:
    return {key: options.get(key) for key in keys}


def transcribe_media(
    path: str,
    *,
    options: Dict[str, Any],
    diarize: Optional[Dict[str, Any]] = None,
    cache_dir: Optional[str] = None,
    reuse_cache: bool = True,
) -> Tuple[Dict[str, Any], bool]:
    """Transcribe (and optionally diarize) *path*, returning ``(payload, from_cache)``.

    The result is written next to the media (or into *cache_dir*) so a second
    run over the same folder costs nothing. Transcription is by far the slowest
    step in any pipeline that uses it, and re-running the command after
    changing an unrelated flag is the normal case, not the exception.

    **The cache records the settings that produced it, and is only reused when
    they still match.** Without that, switching ``--asr-model`` from ``tiny.en``
    to ``large-v3`` would hand back the tiny transcript and report success,
    which is the worst kind of caching bug: silent, and invisible in the output.
    The same applies to ``--diarize`` settings, tracked separately so changing
    the speaker count re-diarizes without re-decoding the audio.

    A cached transcript produced without ``--diarize`` is likewise reused when
    speaker labels are asked for later: only the diarization runs.
    """
    cache = cache_path_for(path, cache_dir)
    asr_signature = _signature(options, _ASR_SIGNATURE_KEYS)
    diarize_signature = dict(diarize) if diarize is not None else None

    payload: Optional[Dict[str, Any]] = None
    from_cache = False

    if reuse_cache and os.path.isfile(cache):
        try:
            with open(cache, "r", encoding="utf-8-sig") as handle:
                candidate = json.load(handle)
        except (OSError, ValueError):
            # A truncated or hand-edited cache should cost one re-run, not the
            # whole command.
            candidate = None
        if isinstance(candidate, dict) and candidate.get("asr") == asr_signature:
            payload = candidate
            from_cache = True

    if payload is None:
        payload = transcribe_file(path, **options)
        payload["asr"] = asr_signature
        from_cache = False

    # `is not None`, not truthiness: an empty options dict means "diarize with
    # every default", and testing it as a boolean silently skips the work.
    if diarize is not None and payload.get("diarization") != diarize_signature:
        turns = diarize_file(path, **diarize)
        payload["segments"] = assign_speakers(payload.get("segments") or [], turns)
        payload["diarization"] = diarize_signature
        payload["speakers"] = sorted({t["speaker"] for t in turns})
        from_cache = False

    if not from_cache:
        _write_cache(cache, payload)

    return payload, from_cache


def convert_file(
    path: str,
    *,
    media_dir: Optional[str] = None,
    url_prefix: Optional[str] = None,
    id_prefix: str = "",
    field: str = "conversation",
    speaker_key: str = "speaker",
    transcribe: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """Convert one transcript file into an item dict plus a report.

    Returns ``(item, report)``; ``item`` is ``None`` when nothing usable came
    out, in which case the report explains why. The report is what ``--dry-run``
    prints and is deliberately produced on every run, not only dry ones, so the
    summary at the end can flag files that yielded nothing.

    Args:
        transcribe: When set and *path* is an audio or video file, run local
            ASR over it and treat the result as the transcript. The dict holds
            the keyword arguments for
            :func:`potato.server_utils.transcripts.transcribe_file`, plus
            ``cache_dir`` and ``reuse_cache``.
    """
    report: Dict[str, Any] = {
        "path": path,
        "format": "unreadable",
        "turns": 0,
        "speakers": [],
        "duration": 0.0,
        "media": None,
        "error": None,
        "transcribed": False,
        "cached": False,
    }

    is_media = looks_like_media(path)

    if is_media and not transcribe:
        report["format"] = "audio/video"
        report["error"] = "media file; pass --transcribe to run local ASR"
        return None, report

    if is_media:
        options = dict(transcribe)
        cache_dir = options.pop("cache_dir", None)
        reuse_cache = options.pop("reuse_cache", True)
        diarize = options.pop("diarize", None)
        try:
            content, from_cache = transcribe_media(
                path, options=options, diarize=diarize, cache_dir=cache_dir,
                reuse_cache=reuse_cache)
        except (TranscriptionError, DiarizationError) as exc:
            report["format"] = "audio/video"
            report["error"] = str(exc)
            return None, report
        report["transcribed"] = True
        report["cached"] = from_cache
    else:
        try:
            with open(path, "r", encoding="utf-8-sig") as handle:
                content = handle.read()
        except (OSError, UnicodeDecodeError) as exc:
            report["error"] = str(exc)
            return None, report

    if is_media:
        report["format"] = (
            "local ASR + diarization"
            if transcribe.get("diarize") is not None else "local ASR")
    else:
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

    # A file we transcribed ourselves is its own media, and we know its real
    # extension -- find_media() would guess ``.mp3`` from the basename under a
    # URL prefix, which is wrong for every wav and m4a in the folder.
    if is_media:
        media = (url_prefix.rstrip("/") + "/" + os.path.basename(path)
                 if url_prefix else path)
    else:
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
            "Deepgram, AssemblyAI, Rev.ai, CTM, Praat TextGrid, and ELAN EAF. "
            "With --transcribe it also reads raw audio and video, running "
            "Whisper locally."
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
        "--transcribe",
        action="store_true",
        help=(
            "Run local speech-to-text over audio and video inputs instead of "
            'requiring an existing transcript. Needs pip install '
            '"potato-annotation[transcribe]".'
        ),
    )
    parser.add_argument(
        "--asr-model",
        default="base",
        help=(
            "Whisper model size, or a path to a CTranslate2 model directory "
            "(default: base). Larger is slower and more accurate: tiny, base, "
            "small, medium, large-v3. The .en variants are English-only and "
            "better than the multilingual model of the same size on English."
        ),
    )
    parser.add_argument(
        "--asr-language",
        help="ISO language code, e.g. en. Omit to auto-detect per file.",
    )
    parser.add_argument(
        "--asr-device",
        default="cpu",
        choices=["cpu", "cuda"],
        help="Device to decode on (default: cpu).",
    )
    parser.add_argument(
        "--asr-word-timestamps",
        action="store_true",
        help="Also record per-word timings. Roughly 20%% slower.",
    )
    parser.add_argument(
        "--asr-no-vad",
        action="store_true",
        help=(
            "Decode every second of audio, including what Silero VAD would "
            "have dropped as non-speech. VAD is on by default because it cuts "
            "the text Whisper hallucinates over silence, but it also drops "
            "quiet or whispered speech, and it does so without saying so. "
            "Reach for this when a transcript comes back shorter than the "
            "recording."
        ),
    )
    parser.add_argument(
        "--diarize",
        action="store_true",
        help=(
            "Also label who is speaking, locally. Whisper produces no speaker "
            "labels of its own; this runs a separate segmentation and "
            "speaker-embedding model. Two model files download once (~47 MB)."
        ),
    )
    parser.add_argument(
        "--num-speakers",
        type=int,
        help=(
            "Fix the speaker count. A two-person interview diarizes markedly "
            "better told there are two people. Omit to infer it."
        ),
    )
    parser.add_argument(
        "--diarize-threshold",
        type=float,
        default=0.5,
        help=(
            "Clustering distance when the speaker count is inferred "
            "(default: 0.5). Raise it when one person is split across several "
            "labels; lower it when two people are merged into one."
        ),
    )
    parser.add_argument(
        "--diarize-segmentation-model",
        help="Path to an ONNX segmentation model, instead of downloading one.",
    )
    parser.add_argument(
        "--diarize-embedding-model",
        help="Path to an ONNX speaker-embedding model, instead of downloading one.",
    )
    parser.add_argument(
        "--asr-cache",
        help=(
            "Directory for transcription output (default: beside each media "
            "file). Transcripts are reused on later runs."
        ),
    )
    parser.add_argument(
        "--asr-no-cache",
        action="store_true",
        help="Re-transcribe even when a cached transcript exists.",
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

    if report.get("cached"):
        speaker_note += ", cached"

    return (
        f"  {name:<40} {report['format']:<24} "
        f"{report['turns']:>4} turns  {report['duration']:>7.1f}s  {speaker_note}"
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.dry_run and not args.output:
        parser.error("-o/--output is required unless --dry-run is given")

    if args.diarize and not args.transcribe:
        parser.error(
            "--diarize applies to --transcribe. Diarizing an existing "
            "transcript would need its audio, and a transcript file does not "
            "carry any.")

    paths = collect_inputs(
        args.inputs, recursive=args.recursive, include_media=args.transcribe)
    if not paths:
        print("No transcript files matched.", file=sys.stderr)
        return 1

    transcribe: Optional[Dict[str, Any]] = None
    if args.transcribe:
        # Fail before the first file rather than after the first decode
        # attempt: the message names the extra to install, and there is no
        # point reporting it once per file.
        from potato.server_utils.transcripts import transcription_available
        if not transcription_available():
            print(
                'Local transcription needs faster-whisper: pip install '
                '"potato-annotation[transcribe]"',
                file=sys.stderr,
            )
            return 1
        transcribe = {
            "model": args.asr_model,
            "language": args.asr_language,
            "device": args.asr_device,
            "compute_type": "float16" if args.asr_device == "cuda" else "int8",
            "word_timestamps": args.asr_word_timestamps,
            "vad_filter": not args.asr_no_vad,
            "cache_dir": args.asr_cache,
            "reuse_cache": not args.asr_no_cache,
            "diarize": None,
        }
        if args.diarize:
            from potato.server_utils.transcripts import diarization_available
            if not diarization_available():
                print(
                    'Local diarization needs sherpa-onnx: pip install '
                    '"potato-annotation[transcribe]"',
                    file=sys.stderr,
                )
                return 1
            transcribe["diarize"] = {
                "num_speakers": args.num_speakers,
                "threshold": args.diarize_threshold,
                "segmentation_model": args.diarize_segmentation_model,
                "embedding_model": args.diarize_embedding_model,
            }

    items: List[Dict[str, Any]] = []
    reports: List[Dict[str, Any]] = []

    for path in paths:
        if transcribe and looks_like_media(path) and not args.quiet:
            # Decoding an hour of audio is minutes of silence otherwise. Say
            # nothing for a cached file: announcing work that will not happen
            # is how a fast run gets read as a slow one.
            cached = transcribe["reuse_cache"] and os.path.isfile(
                cache_path_for(path, transcribe["cache_dir"]))
            if not cached:
                print(f"  transcribing {os.path.basename(path)} ...", flush=True)
        item, report = convert_file(
            path,
            media_dir=args.media_dir,
            url_prefix=args.media_url_prefix,
            id_prefix=args.id_prefix,
            field=args.field,
            speaker_key=args.speaker_key,
            transcribe=transcribe,
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
        if any(r.get("transcribed") and not r.get("cached") for r in reports):
            # Be exact about it. Transcription caches *are* written on a dry
            # run -- throwing away minutes of decoding to honour the letter of
            # the flag would make --dry-run useless with --transcribe.
            print("\nDry run — no data file written "
                  "(transcripts were cached beside the media).")
        else:
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

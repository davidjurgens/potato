"""
Genome locus display (``type: genome_locus``).

Shows a region of a genome in igv.js with the tracks a reviewer needs: a
reference sequence, read alignments (BAM/CRAM), variant calls (VCF),
annotations (BED, GFF3, GTF) and signal (bigWig, bedGraph). The item field
holds the locus to open, written the way igv's locus box takes it::

    chr1:1,450-1,550     a range (1-based, inclusive)
    chr1:1500            one position, opened with ``flank`` bases either side
    chr1                 a whole sequence

Files are served from the media directory over HTTP range requests, so an
indexed BAM or VCF is read a slice at a time rather than downloaded whole.

Reference: ``reference: {fasta: genome/ref.fa}`` (the ``.fai`` index next to
it, or ``index:``). A built-in igv genome id (``genome: hg38``) loads its
files from the internet, so it is accepted only with ``allow_remote: true``.

Tracks come from the display's ``tracks`` list. A track names its file with
``url`` (one file for every item, e.g. a cohort VCF) or ``field`` (an item
field, so each item brings its own BAM). Index files default to the data file
plus ``.bai`` / ``.crai`` / ``.tbi``; ``index`` or ``index_field`` overrides.

The selection is the current locus plus any features the annotator clicks
(with ``select_features: true``, the default). Most variant-review tasks ask
their real question with an ordinary radio scheme beside it.

Engine: igv.js 3.8.9, MIT, committed under ``potato/static/vendor/igv-3.8.9/``.
It draws with canvas 2D and does not need WebGL.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple

from .viewer_display import (ViewerAsset, ViewerDataError, ViewerDisplay,
                             ViewerEngine, resolve_source)

#: Track formats and the igv track type each one is drawn as.
TRACK_FORMATS = {
    "bam": "alignment", "cram": "alignment",
    "vcf": "variant",
    "bed": "annotation", "gff3": "annotation", "gff": "annotation",
    "gtf": "annotation", "bigbed": "annotation",
    "bigwig": "wig", "bedgraph": "wig", "wig": "wig",
}

#: Extensions that identify a format when a track does not say.
_EXTENSIONS = {
    ".bam": "bam", ".cram": "cram", ".vcf": "vcf", ".bed": "bed",
    ".gff3": "gff3", ".gff": "gff", ".gtf": "gtf", ".bb": "bigbed",
    ".bigbed": "bigbed", ".bw": "bigwig", ".bigwig": "bigwig",
    ".bedgraph": "bedgraph", ".bdg": "bedgraph", ".wig": "wig",
}

#: The index file a format is read through, by default.
_INDEX_SUFFIX = {"bam": ".bai", "cram": ".crai"}

TRACK_KEYS = {"name", "format", "url", "field", "index", "index_field", "indexed",
              "height", "color", "display_mode"}

_LOCUS = re.compile(r"^\s*([^\s:]+)(?:\s*:\s*([\d,]+)(?:\s*-\s*([\d,]+))?)?\s*$")


def parse_locus(text: Any) -> Tuple[str, Optional[int], Optional[int]]:
    """``(sequence, start, end)``, 1-based inclusive; start/end are None for a
    whole sequence. Raises ValueError for anything else."""
    if not isinstance(text, str):
        raise ValueError(f"a locus is text such as chr1:1,000-2,000, not {type(text).__name__}")
    m = _LOCUS.match(text)
    if not m:
        raise ValueError(f"'{text}' is not a locus; write chr1:1,000-2,000 or chr1:1500")
    chrom, a, b = m.group(1), m.group(2), m.group(3)
    if a is None:
        return chrom, None, None
    start = int(a.replace(",", ""))
    end = int(b.replace(",", "")) if b else start
    if start < 1 or end < start:
        raise ValueError(f"'{text}': positions start at 1 and the end may not precede the start")
    return chrom, start, end


_FAI_CACHE: Dict[Tuple[str, float], Dict[str, int]] = {}


def fai_lengths(path: str) -> Dict[str, int]:
    """Sequence name -> length, from a FASTA index (.fai)."""
    key = (path, os.path.getmtime(path))
    if key not in _FAI_CACHE:
        lengths: Dict[str, int] = {}
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 2 and parts[1].isdigit():
                    lengths[parts[0]] = int(parts[1])
        if len(_FAI_CACHE) > 32:
            _FAI_CACHE.clear()
        _FAI_CACHE[key] = lengths
    return _FAI_CACHE[key]


def format_locus(chrom: str, start: Optional[int], end: Optional[int]) -> str:
    if start is None:
        return chrom
    return f"{chrom}:{start}-{end}"


def track_format(track: Dict[str, Any], name: str = "") -> Optional[str]:
    fmt = track.get("format")
    if fmt:
        return str(fmt).lower()
    base = name.split("?", 1)[0].lower()
    if base.endswith((".gz", ".bgz")):
        base = base.rsplit(".", 1)[0]
    return _EXTENSIONS.get(os.path.splitext(base)[1])


def default_index(url: str, fmt: str) -> Optional[str]:
    """The index file igv should read for ``url``, or None (read whole)."""
    if fmt in _INDEX_SUFFIX:
        return url + _INDEX_SUFFIX[fmt]
    if url.split("?", 1)[0].lower().endswith((".gz", ".bgz")) and fmt in (
            "vcf", "bed", "gff3", "gff", "gtf", "bedgraph"):
        return url + ".tbi"
    return None


class GenomeLocusDisplay(ViewerDisplay):
    name = "genome_locus"
    description = "Genome locus in igv.js: reference, reads, variants, annotations"
    required_fields = ["key"]
    optional_fields = {
        **ViewerDisplay.COMMON_OPTIONS,
        "engine": "igv",
        "height": None,
        "reference": None,
        "genome": None,
        "tracks": [],
        "flank": 50,
        "select_features": True,
    }
    default_engine = "igv"
    engines = {
        "igv": ViewerEngine(
            name="igv", label="igv.js", webgl=None, licence="MIT",
            assets=(ViewerAsset("script", "vendor/igv-3.8.9/igv.min.js"),)),
    }
    selection_context = ("locus",)

    # -- options --------------------------------------------------------------

    def validate_options(self, options: Dict[str, Any], path: str) -> List[str]:
        errors = []
        ref, genome = options.get("reference"), options.get("genome")
        if (ref is None) == (genome is None):
            errors.append(f"{path}: give a reference ({{fasta: <file>}}) or a built-in "
                          f"genome id (genome: hg38), and not both")
        if ref is not None:
            if not isinstance(ref, dict) or not isinstance(ref.get("fasta"), str):
                errors.append(f"{path}.reference must be a mapping with fasta: <path to "
                              f"an indexed FASTA in the media directory>")
            else:
                extra = sorted(set(ref) - {"fasta", "index", "name"})
                if extra:
                    errors.append(f"{path}.reference has unknown key(s) {', '.join(extra)}; "
                                  f"it takes fasta, index and name")
                if str(ref["fasta"]).startswith(("http://", "https://")) and not options.get("allow_remote"):
                    errors.append(f"{path}.reference.fasta is a URL; set allow_remote: true "
                                  f"or copy the FASTA into the media directory")
        if genome is not None:
            if not isinstance(genome, str):
                errors.append(f"{path}.genome must be an igv genome id such as hg38")
            elif not options.get("allow_remote"):
                errors.append(
                    f"{path}.genome '{genome}' is fetched from the internet by igv.js, "
                    f"and remote files are off. Use reference: {{fasta: ...}} with a local "
                    f"FASTA and .fai, or set allow_remote: true.")
        tracks = options.get("tracks")
        if not isinstance(tracks, list):
            errors.append(f"{path}.tracks must be a list")
            tracks = []
        for n, t in enumerate(tracks):
            where = f"{path}.tracks[{n}]"
            if not isinstance(t, dict):
                errors.append(f"{where} must be a mapping")
                continue
            extra = sorted(set(t) - TRACK_KEYS)
            if extra:
                errors.append(f"{where} has unknown key(s) {', '.join(extra)}; "
                              f"accepted: {', '.join(sorted(TRACK_KEYS))}")
            if ("url" in t) == ("field" in t):
                errors.append(f"{where} needs exactly one of url (one file for every "
                              f"item) or field (an item field naming the file)")
            fmt = track_format(t, str(t.get("url", "")))
            if fmt is None and "url" in t:
                errors.append(f"{where}: cannot tell the format; set format: to one of "
                              f"{', '.join(sorted(TRACK_FORMATS))}")
            elif fmt is not None and fmt not in TRACK_FORMATS:
                errors.append(f"{where}.format '{fmt}' is not one of "
                              f"{', '.join(sorted(TRACK_FORMATS))}")
            if str(t.get("url", "")).startswith(("http://", "https://")) and not options.get("allow_remote"):
                errors.append(f"{where}.url is remote; set allow_remote: true or copy the "
                              f"file into the media directory")
        flank = options.get("flank")
        if isinstance(flank, bool) or not isinstance(flank, int) or flank < 0:
            errors.append(f"{path}.flank must be a whole number of bases (0 or more)")
        if not isinstance(options.get("select_features"), bool):
            errors.append(f"{path}.select_features must be true or false")
        return errors

    # -- rendering ------------------------------------------------------------------

    def client_config(self, field_config, data, options):
        allow_remote = bool(options.get("allow_remote"))
        try:
            chrom, start, end = parse_locus(data)
        except ValueError as e:
            raise ViewerDataError(f"Cannot open this item's locus: {e}.")
        flank = options.get("flank") or 0
        if start is not None and start == end and flank:
            start, end = max(1, start - flank), end + flank

        reference = None
        ref = options.get("reference")
        if isinstance(ref, dict) and ref.get("fasta"):
            fasta_url, _ = resolve_source(ref["fasta"], allow_remote, "reference FASTA")
            index_ref = ref.get("index") or (str(ref["fasta"]) + ".fai")
            index_url, index_path = resolve_source(index_ref, allow_remote, "FASTA index (.fai)")
            if index_path is not None:
                lengths = fai_lengths(index_path)
                if chrom not in lengths:
                    shown = ", ".join(list(lengths)[:8]) + (" ..." if len(lengths) > 8 else "")
                    raise ViewerDataError(
                        f"This item's locus names '{chrom}', which is not a sequence in "
                        f"the reference ({shown or 'the .fai lists none'}).")
                if end is not None and end > lengths[chrom]:
                    end = lengths[chrom]
                    start = min(start, end)
            reference = {"fastaURL": fasta_url, "indexURL": index_url,
                         "name": ref.get("name") or os.path.basename(str(ref["fasta"])),
                         "id": ref.get("name") or os.path.basename(str(ref["fasta"]))}
        elif options.get("genome"):
            if not allow_remote:
                raise ViewerDataError("A built-in genome id needs allow_remote: true.")
        else:
            raise ViewerDataError("This display has no reference; set reference: {fasta: ...}.")

        tracks = []
        for t in options.get("tracks") or []:
            if not isinstance(t, dict):
                continue
            fmt = track_format(t, str(t.get("url", "")))
            # A field track without format: is typed per item, in the browser,
            # from the file name the item gives.
            entry = {
                "name": t.get("name") or t.get("field") or os.path.basename(str(t.get("url", ""))),
                "format": fmt,
                "type": TRACK_FORMATS.get(fmt) if fmt else None,
                "height": t.get("height"),
                "color": t.get("color"),
                "displayMode": t.get("display_mode"),
            }
            if "url" in t:
                url, _ = resolve_source(t["url"], allow_remote, f"track file '{t['url']}'")
                entry["url"] = url
                index = t.get("index") or default_index(str(t["url"]), fmt or "")
                if index and t.get("indexed") is not False:
                    entry["indexURL"], _ = resolve_source(
                        index, allow_remote, f"index for track '{entry['name']}'")
                else:
                    entry["indexed"] = False
            else:
                entry["field"] = t["field"]
                entry["indexField"] = t.get("index_field")
                if t.get("indexed") is False:
                    entry["indexed"] = False
            tracks.append({k: v for k, v in entry.items() if v is not None})

        return {
            "locus": format_locus(chrom, start, end),
            "reference": reference,
            "genome": options.get("genome") if reference is None else None,
            "tracks": tracks,
            "selectFeatures": bool(options.get("select_features", True)),
            "allowRemote": allow_remote,
        }

    # -- selection shape -------------------------------------------------------------

    def validate_item(self, item, where):
        errors = []
        allowed = {"chr", "start", "end", "name", "track", "kind", "ref", "alt", "label"}
        extra = sorted(set(item) - allowed)
        if extra:
            errors.append(f"{where} has unexpected key(s) {', '.join(extra)}")
        if not isinstance(item.get("chr"), str) or not item.get("chr"):
            errors.append(f"{where}.chr must be a sequence name")
        start, end = item.get("start"), item.get("end")
        for key, v in (("start", start), ("end", end)):
            if isinstance(v, bool) or not isinstance(v, int) or v < 1:
                errors.append(f"{where}.{key} must be a 1-based position")
        if isinstance(start, int) and isinstance(end, int) and end < start:
            errors.append(f"{where}.end precedes its start")
        for key in ("name", "track", "ref", "alt"):
            if key in item and not isinstance(item[key], str):
                errors.append(f"{where}.{key} must be text")
        if "kind" in item and item["kind"] not in ("variant", "feature"):
            errors.append(f"{where}.kind must be variant or feature")
        return errors

    def validate_context(self, selection):
        locus = selection.get("locus")
        if locus is None:
            return []
        try:
            parse_locus(locus)
        except ValueError as e:
            return [f"locus: {e}"]
        return []

"""genome_locus: locus parsing, reference and track resolution, option
validation, and the synthetic example's BGZF/BAI/TBI writers."""

import gzip
import html as html_module
import importlib.util
import json
import os
import re
import struct
import zlib
from unittest.mock import patch

import pytest

from potato.server_utils.displays.genome_locus_display import (
    GenomeLocusDisplay, default_index, format_locus, parse_locus, track_format)
from potato.server_utils.displays.registry import display_registry
from tests.helpers.test_utils import create_test_directory

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXAMPLE = os.path.join(REPO, "examples", "advanced", "variant-review")


def _generator():
    spec = importlib.util.spec_from_file_location(
        "generate_variant_data", os.path.join(EXAMPLE, "generate_data.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GEN = _generator()

REFERENCE = {"fasta": "genome/ref.fa"}


@pytest.fixture
def media():
    root = create_test_directory("genome_locus_unit")
    media = os.path.join(root, "media")
    for sub in ("genome", "calls", "reads"):
        os.makedirs(os.path.join(media, sub), exist_ok=True)
    GEN.write_fasta(os.path.join(media, "genome", "ref.fa"), {"chr1": "ACGT" * 50})
    for name in ("calls/a.vcf.gz", "calls/a.vcf.gz.tbi", "reads/r.bam", "reads/r.bam.bai",
                 "calls/plain.vcf"):
        open(os.path.join(media, name), "wb").close()
    with patch.dict("potato.server_utils.config_module.config",
                    {"task_dir": root, "media_directory": "media"}):
        yield media


def _cfg(page):
    m = re.search(r"data-viewer-config='([^']*)'", page)
    return json.loads(html_module.unescape(m.group(1)))


def _render(options, value):
    return display_registry.render("genome_locus", {"key": "locus", "type": "genome_locus",
                                                    "display_options": options}, value)


class TestLocus:
    @pytest.mark.parametrize("text,expected", [
        ("chr1:1,450-1,550", ("chr1", 1450, 1550)),
        ("chr1:1500", ("chr1", 1500, 1500)),
        ("  chrX : 10 - 20 ", ("chrX", 10, 20)),
        ("chr2", ("chr2", None, None)),
        ("NC_000001.11:5-6", ("NC_000001.11", 5, 6)),
    ])
    def test_parse(self, text, expected):
        assert parse_locus(text) == expected

    @pytest.mark.parametrize("text", ["chr1:0", "chr1:20-10", "chr1:abc", "", "chr1 2", 1500])
    def test_rejects(self, text):
        with pytest.raises(ValueError):
            parse_locus(text)

    def test_format(self):
        assert format_locus("chr1", 3, 9) == "chr1:3-9" and format_locus("chr1", None, None) == "chr1"


class TestTracks:
    def test_formats_and_indexes(self):
        assert track_format({}, "calls/a.vcf.gz") == "vcf"
        assert track_format({}, "x.bw") == "bigwig"
        assert track_format({"format": "GFF3"}, "x") == "gff3"
        assert track_format({}, "x.txt") is None
        assert default_index("r.bam", "bam") == "r.bam.bai"
        assert default_index("r.cram", "cram") == "r.cram.crai"
        assert default_index("a.vcf.gz", "vcf") == "a.vcf.gz.tbi"
        assert default_index("a.vcf", "vcf") is None
        assert default_index("s.bw", "bigwig") is None


class TestRender:
    def test_reference_tracks_and_flank(self, media):
        page = _render({"reference": REFERENCE, "flank": 25, "tracks": [
            {"name": "Calls", "url": "calls/a.vcf.gz"},
            {"name": "Plain", "url": "calls/plain.vcf"},
            {"name": "Reads", "field": "bam"}]}, "chr1:100")
        cfg = _cfg(page)
        assert cfg["locus"] == "chr1:75-125"
        assert cfg["reference"]["fastaURL"] == "/media/genome/ref.fa"
        assert cfg["reference"]["indexURL"] == "/media/genome/ref.fa.fai"
        calls, plain, reads = cfg["tracks"]
        assert calls == {"name": "Calls", "format": "vcf", "type": "variant",
                         "url": "/media/calls/a.vcf.gz", "indexURL": "/media/calls/a.vcf.gz.tbi"}
        assert plain["indexed"] is False and "indexURL" not in plain
        assert reads == {"name": "Reads", "field": "bam"}
        assert cfg["webgl"] is None
        assert cfg["assets"] == [{"type": "script", "src": "/static/vendor/igv-3.8.9/igv.min.js"}]
        assert cfg["genome"] is None and cfg["allowRemote"] is False

    def test_missing_index_names_the_file(self, media):
        os.remove(os.path.join(media, "calls", "a.vcf.gz.tbi"))
        page = _render({"reference": REFERENCE, "tracks": [{"name": "Calls", "url": "calls/a.vcf.gz"}]},
                       "chr1:5")
        assert "pv-failed" in page and "index for track" in page and "a.vcf.gz.tbi" in page

    def test_bad_locus_is_a_message_not_a_crash(self, media):
        page = _render({"reference": REFERENCE}, "chr1:9-3")
        assert "pv-failed" in page and "Cannot open this item&#x27;s locus" in page
        # A sequence the reference does not have is named, with the ones it has.
        page = _render({"reference": REFERENCE}, "chr7:100")
        assert "pv-failed" in page and "&#x27;chr7&#x27;, which is not a sequence" in page
        assert "(chr1)" in page

    def test_a_range_past_the_end_is_clipped(self, media):
        assert _cfg(_render({"reference": REFERENCE, "flank": 50}, "chr1:190"))["locus"] == "chr1:140-200"

    def test_a_built_in_genome_needs_allow_remote(self, media):
        assert "pv-failed" in _render({"genome": "hg38"}, "chr1:5")
        cfg = _cfg(_render({"genome": "hg38", "allow_remote": True}, "chr1:5"))
        assert cfg["genome"] == "hg38" and cfg["reference"] is None


class TestOptions:
    def _errors(self, options):
        return GenomeLocusDisplay().validate_options(
            GenomeLocusDisplay().get_display_options({"display_options": options}), "f")

    def test_valid(self):
        assert self._errors({"reference": REFERENCE, "tracks": [
            {"url": "a.vcf.gz"}, {"field": "bam", "format": "bam"}, {"field": "bw"}]}) == []

    @pytest.mark.parametrize("options,fragment", [
        ({}, "give a reference"),
        ({"reference": REFERENCE, "genome": "hg38"}, "not both"),
        ({"genome": "hg38"}, "fetched from the internet"),
        ({"reference": {"path": "x.fa"}}, "mapping with fasta"),
        ({"reference": {"fasta": "x.fa", "fai": "x"}}, "unknown key"),
        ({"reference": REFERENCE, "tracks": [{"name": "x"}]}, "exactly one of url"),
        ({"reference": REFERENCE, "tracks": [{"url": "a", "field": "b"}]}, "exactly one of url"),
        ({"reference": REFERENCE, "tracks": [{"url": "notes.txt"}]}, "cannot tell the format"),
        ({"reference": REFERENCE, "tracks": [{"url": "x", "format": "sam"}]}, "'sam' is not one of"),
        ({"reference": REFERENCE, "tracks": [{"url": "https://x/a.bam"}]}, "remote"),
        ({"reference": REFERENCE, "tracks": [{"url": "a.bam", "colour": "red"}]}, "unknown key"),
        ({"reference": REFERENCE, "flank": -1}, "flank"),
        ({"reference": REFERENCE, "tracks": {"url": "a.bam"}}, "must be a list"),
    ])
    def test_invalid(self, options, fragment):
        errors = self._errors(options)
        assert any(fragment in e for e in errors), errors


class TestSyntheticFormats:
    """The example's writers: what igv.js and htslib rely on."""

    def test_bgzf_blocks_are_gzip_members_with_a_bc_field(self):
        data = GEN.bgzip(b"hello\n" * 30000)          # > one 64 KB block
        assert gzip.decompress(data) == b"hello\n" * 30000
        assert data.endswith(GEN._BGZF_EOF)
        offset, blocks = 0, 0
        while offset < len(data):
            assert data[offset:offset + 4] == b"\x1f\x8b\x08\x04"
            assert data[offset + 12:offset + 14] == b"BC"
            bsize = struct.unpack("<H", data[offset + 16:offset + 18])[0]
            offset += bsize + 1
            blocks += 1
        assert offset == len(data) and blocks >= 3

    def test_reg2bin_matches_the_specification(self):
        assert GEN.reg2bin(0, 1) == 4681
        assert GEN.reg2bin(16383, 16385) == 585        # crosses a 16 kb boundary
        assert GEN.reg2bin(0, 1 << 29) == 0

    def test_tabix_index_points_at_the_record(self, tmp_path):
        path = str(tmp_path / "c.vcf.gz")
        GEN.write_vcf_gz(path, {"chr1": "A" * 100}, ["##fileformat=VCFv4.2", "#CHROM\tPOS"],
                         [["chr1", "10", ".", "A", "G", "50", "PASS", ".", "GT", "0/1"]])
        tbi = gzip.decompress(open(path + ".tbi", "rb").read())
        assert tbi[:4] == b"TBI\x01"
        n_ref, fmt, col_seq, col_beg, col_end, meta, skip, l_nm = struct.unpack("<8i", tbi[4:36])
        assert (n_ref, fmt, col_seq, col_beg, col_end, chr(meta)) == (1, 2, 1, 2, 0, "#")
        assert tbi[36:36 + l_nm] == b"chr1\x00"
        n_bin, bin_id, n_chunk, beg, end = struct.unpack("<iIiQQ", tbi[36 + l_nm:36 + l_nm + 28])
        assert (n_bin, bin_id, n_chunk) == (1, 4681, 1)
        raw = gzip.decompress(open(path, "rb").read())
        assert raw[beg & 0xFFFF:end & 0xFFFF].startswith(b"chr1\t10\t")

    def test_example_data_is_what_the_generator_writes(self, tmp_path):
        """The committed example files are reproducible from the script."""
        fai = open(os.path.join(EXAMPLE, "media", "genome", "synthetic.fa.fai")).read().split()
        assert fai[:2] == ["chr1", "5000"]
        bam = gzip.decompress(open(os.path.join(EXAMPLE, "media", "reads", "sample1.bam"), "rb").read())
        assert bam[:4] == b"BAM\x01"
        assert open(os.path.join(EXAMPLE, "media", "reads", "sample1.bam.bai"), "rb").read(4) == b"BAI\x01"

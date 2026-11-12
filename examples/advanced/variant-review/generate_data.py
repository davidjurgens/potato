#!/usr/bin/env python3
"""
Writes the synthetic genome, reads and variant calls for the variant-review
example.

Run from the repository root:
    python examples/advanced/variant-review/generate_data.py

Everything is made up and seeded, so the output is the same on every run:

* ``media/genome/synthetic.fa`` (+ ``.fai``): two random sequences, chr1 and
  chr2, with a poly-A run in chr1.
* ``media/reads/sample1.bam`` (+ ``.bai``): simulated 100 bp single-end reads
  around each call. Two calls are supported by the reads; two are not (one
  appears only on reverse-strand reads at low base quality, one sits in the
  poly-A run).
* ``media/calls/sample1.vcf.gz`` (+ ``.tbi``): the four calls, bgzipped and
  tabix-indexed.
* ``media/annotation/regions.bed``: two made-up gene spans and the poly-A run.

The BGZF, BAM, BAI and TBI writers are written out here (no pysam or htslib
needed). They follow the SAM/BAM and tabix specifications
(https://samtools.github.io/hts-specs/) closely enough for igv.js, pysam and
samtools to read the files, but they write only what this example needs:
sorted single-end reads, one sample, small sequences.
"""

from __future__ import annotations

import json
import os
import random
import struct
import zlib
from typing import Dict, List, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
MEDIA = os.path.join(HERE, "media")

# ---------------------------------------------------------------------------
# BGZF
# ---------------------------------------------------------------------------

_BGZF_EOF = bytes.fromhex("1f8b08040000000000ff0600424302001b0003000000000000000000")
_BLOCK_MAX = 0xFF00


def _bgzf_block(data: bytes) -> bytes:
    comp = zlib.compressobj(6, zlib.DEFLATED, -15)
    body = comp.compress(data) + comp.flush()
    bsize = len(body) + 25          # header (18) + body + trailer (8) - 1
    header = (b"\x1f\x8b\x08\x04" + b"\x00" * 4 + b"\x00\xff" + struct.pack("<H", 6)
              + b"BC" + struct.pack("<HH", 2, bsize))
    return header + body + struct.pack("<II", zlib.crc32(data) & 0xFFFFFFFF, len(data))


class BgzfWriter:
    """Accumulates bytes into BGZF blocks and reports virtual offsets."""

    def __init__(self):
        self.out = bytearray()
        self.buf = bytearray()

    def tell(self) -> int:
        return (len(self.out) << 16) | len(self.buf)

    def write(self, data: bytes) -> None:
        self.buf += data
        while len(self.buf) >= _BLOCK_MAX:
            self.out += _bgzf_block(bytes(self.buf[:_BLOCK_MAX]))
            del self.buf[:_BLOCK_MAX]

    def flush(self) -> None:
        if self.buf:
            self.out += _bgzf_block(bytes(self.buf))
            self.buf = bytearray()

    def close(self) -> bytes:
        self.flush()
        return bytes(self.out) + _BGZF_EOF


def bgzip(data: bytes) -> bytes:
    w = BgzfWriter()
    w.write(data)
    return w.close()


# ---------------------------------------------------------------------------
# Binning index shared by BAI and TBI
# ---------------------------------------------------------------------------

def reg2bin(beg: int, end: int) -> int:
    end -= 1
    if beg >> 14 == end >> 14: return ((1 << 15) - 1) // 7 + (beg >> 14)
    if beg >> 17 == end >> 17: return ((1 << 12) - 1) // 7 + (beg >> 17)
    if beg >> 20 == end >> 20: return ((1 << 9) - 1) // 7 + (beg >> 20)
    if beg >> 23 == end >> 23: return ((1 << 6) - 1) // 7 + (beg >> 23)
    if beg >> 26 == end >> 26: return ((1 << 3) - 1) // 7 + (beg >> 26)
    return 0


class BinIndex:
    """Bins, chunks and the 16 kb linear index for one reference sequence."""

    def __init__(self):
        self.bins: Dict[int, List[List[int]]] = {}
        self.linear: Dict[int, int] = {}

    def add(self, beg: int, end: int, vstart: int, vend: int) -> None:
        chunks = self.bins.setdefault(reg2bin(beg, end), [])
        if chunks and chunks[-1][1] == vstart:
            chunks[-1][1] = vend          # contiguous: extend the last chunk
        else:
            chunks.append([vstart, vend])
        for window in range(beg >> 14, ((end - 1) >> 14) + 1):
            if window not in self.linear or vstart < self.linear[window]:
                self.linear[window] = vstart

    def pack(self) -> bytes:
        out = struct.pack("<i", len(self.bins))
        for b in sorted(self.bins):
            chunks = self.bins[b]
            out += struct.pack("<Ii", b, len(chunks))
            for s, e in chunks:
                out += struct.pack("<QQ", s, e)
        n = (max(self.linear) + 1) if self.linear else 0
        out += struct.pack("<i", n)
        last = 0
        for w in range(n):
            last = self.linear.get(w, last)
            out += struct.pack("<Q", last)
        return out


# ---------------------------------------------------------------------------
# FASTA
# ---------------------------------------------------------------------------

def write_fasta(path: str, seqs: Dict[str, str], width: int = 60) -> None:
    fai = []
    with open(path, "w", newline="\n") as f:
        offset = 0
        for name, seq in seqs.items():
            header = f">{name}\n"
            f.write(header)
            offset += len(header)
            fai.append(f"{name}\t{len(seq)}\t{offset}\t{width}\t{width + 1}")
            for i in range(0, len(seq), width):
                line = seq[i:i + width] + "\n"
                f.write(line)
                offset += len(line)
    with open(path + ".fai", "w", newline="\n") as f:
        f.write("\n".join(fai) + "\n")


# ---------------------------------------------------------------------------
# BAM
# ---------------------------------------------------------------------------

_SEQ_CODE = {c: i for i, c in enumerate("=ACMGRSVTWYHKDBN")}
_CIGAR_CODE = {"M": 0, "I": 1, "D": 2, "N": 3, "S": 4, "H": 5, "P": 6, "=": 7, "X": 8}


def _ref_len(cigar: List[Tuple[int, str]]) -> int:
    return sum(n for n, op in cigar if op in "MDN=X")


def bam_record(ref_id: int, pos: int, name: str, flag: int, mapq: int,
               cigar: List[Tuple[int, str]], seq: str, qual: List[int]) -> bytes:
    rname = name.encode() + b"\x00"
    end = pos + _ref_len(cigar)
    packed_cigar = b"".join(struct.pack("<I", n << 4 | _CIGAR_CODE[op]) for n, op in cigar)
    codes = [_SEQ_CODE[c] for c in seq]
    if len(codes) % 2:
        codes.append(0)
    packed_seq = bytes(codes[i] << 4 | codes[i + 1] for i in range(0, len(codes), 2))
    body = (struct.pack("<iiBBHHHiiii", ref_id, pos, len(rname), mapq, reg2bin(pos, end),
                        len(cigar), flag, len(seq), -1, -1, 0)
            + rname + packed_cigar + packed_seq + bytes(qual))
    return struct.pack("<i", len(body)) + body


def write_bam(path: str, seqs: Dict[str, str], reads: List[Dict]) -> None:
    names = list(seqs)
    text = "@HD\tVN:1.6\tSO:coordinate\n" + "".join(
        f"@SQ\tSN:{n}\tLN:{len(seqs[n])}\n" for n in names) + \
        "@RG\tID:sample1\tSM:sample1\n@PG\tID:generate_data.py\tPN:potato-example\n"
    w = BgzfWriter()
    header = b"BAM\x01" + struct.pack("<i", len(text)) + text.encode() + struct.pack("<i", len(names))
    for n in names:
        header += struct.pack("<i", len(n) + 1) + n.encode() + b"\x00" + struct.pack("<i", len(seqs[n]))
    w.write(header)
    w.flush()                     # reads start on a block boundary
    indexes = [BinIndex() for _ in names]
    for r in sorted(reads, key=lambda r: (names.index(r["chr"]), r["pos"])):
        ref_id = names.index(r["chr"])
        start = w.tell()
        w.write(bam_record(ref_id, r["pos"], r["name"], r["flag"], 60, r["cigar"], r["seq"], r["qual"]))
        indexes[ref_id].add(r["pos"], r["pos"] + _ref_len(r["cigar"]), start, w.tell())
    with open(path, "wb") as f:
        f.write(w.close())
    with open(path + ".bai", "wb") as f:
        f.write(b"BAI\x01" + struct.pack("<i", len(names)) + b"".join(i.pack() for i in indexes))


# ---------------------------------------------------------------------------
# VCF + tabix
# ---------------------------------------------------------------------------

def write_vcf_gz(path: str, seqs: Dict[str, str], header: List[str], rows: List[List[str]]) -> None:
    names = list(seqs)
    w = BgzfWriter()
    w.write(("\n".join(header) + "\n").encode())
    indexes = {n: BinIndex() for n in names}
    for row in rows:
        start = w.tell()
        w.write(("\t".join(row) + "\n").encode())
        beg = int(row[1]) - 1
        indexes[row[0]].add(beg, beg + len(row[3]), start, w.tell())
    with open(path, "wb") as f:
        f.write(w.close())
    used = [n for n in names if indexes[n].bins]
    nm = b"".join(n.encode() + b"\x00" for n in used)
    tbi = (b"TBI\x01" + struct.pack("<iiiiiii", len(used), 2, 1, 2, 0, ord("#"), 0)
           + struct.pack("<i", len(nm)) + nm + b"".join(indexes[n].pack() for n in used))
    with open(path + ".tbi", "wb") as f:
        f.write(bgzip(tbi))


# ---------------------------------------------------------------------------
# The example
# ---------------------------------------------------------------------------

#: (chr, 1-based position, ref, alt, id, story)
CALLS = [
    ("chr1", 1201, None, "G", "call_1", "supported"),
    ("chr1", 2051, None, "T", "call_2", "reverse_low_quality"),
    ("chr1", 3302, None, "-", "call_3", "homopolymer"),
    ("chr2", 801, None, "A", "call_4", "homozygous"),
]


def main() -> None:
    rng = random.Random(20261023)
    seqs = {"chr1": "".join(rng.choice("ACGT") for _ in range(5000)),
            "chr2": "".join(rng.choice("ACGT") for _ in range(3000))}
    # A poly-A run at chr1:3291-3310 (1-based) for the indel call.
    s = seqs["chr1"]
    seqs["chr1"] = s[:3290] + "A" * 20 + s[3310:]

    for sub in ("genome", "reads", "calls", "annotation"):
        os.makedirs(os.path.join(MEDIA, sub), exist_ok=True)
    write_fasta(os.path.join(MEDIA, "genome", "synthetic.fa"), seqs)

    calls = []
    for chrom, pos, _ref, alt, cid, story in CALLS:
        ref = seqs[chrom][pos - 1]
        if alt == "-":                      # deletion of one A in the run
            ref, alt = seqs[chrom][pos - 2:pos], seqs[chrom][pos - 2]
            pos -= 1
        elif alt == ref:
            alt = {"A": "G", "C": "T", "G": "A", "T": "C"}[ref]
        calls.append((chrom, pos, ref, alt, cid, story))

    reads = []
    alt_count: Dict[str, int] = {}
    for chrom, pos, ref, alt, cid, story in calls:
        seq = seqs[chrom]
        for i in range(36):
            length = 100
            start = rng.randint(max(0, pos - 95), pos - 6)       # 0-based
            reverse = i % 2 == 1
            carries = {"supported": i % 3 != 0, "homozygous": True,
                       "reverse_low_quality": reverse and i % 4 == 1,
                       "homopolymer": i % 4 == 0}[story]
            qual = [rng.randint(30, 38) for _ in range(length)]
            alt_count[cid] = alt_count.get(cid, 0) + (1 if carries else 0)
            if carries and len(ref) == 1:
                off = pos - 1 - start
                read = seq[start:start + off] + alt + seq[start + off + 1:start + length]
                if story == "reverse_low_quality":
                    qual[off] = 11
                cigar = [(length, "M")]
            elif carries:                   # one-base deletion
                off = pos - start              # first deleted base (0-based in read)
                read = seq[start:start + off] + seq[start + off + 1:start + length + 1]
                cigar = [(off, "M"), (1, "D"), (length - off, "M")]
            else:
                read = seq[start:start + length]
                cigar = [(length, "M")]
            reads.append({"chr": chrom, "pos": start, "name": f"{cid}_r{i:02d}",
                          "flag": 16 if reverse else 0, "cigar": cigar,
                          "seq": read[:length], "qual": qual[:length]})
    write_bam(os.path.join(MEDIA, "reads", "sample1.bam"), seqs, reads)

    header = ["##fileformat=VCFv4.2", "##source=potato-example-generate_data.py"]
    header += [f"##contig=<ID={n},length={len(v)}>" for n, v in seqs.items()]
    header += ['##INFO=<ID=DP,Number=1,Type=Integer,Description="Read depth">',
               '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">',
               '##FORMAT=<ID=AD,Number=R,Type=Integer,Description="Allelic depths">',
               "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tsample1"]
    rows = []
    qual = {"supported": "812", "reverse_low_quality": "38", "homopolymer": "64", "homozygous": "1290"}
    for chrom, pos, ref, alt, cid, story in calls:
        a = alt_count[cid]
        r = 36 - a
        gt = "1/1" if story == "homozygous" else "0/1"
        rows.append([chrom, str(pos), cid, ref, alt, qual[story], "PASS", f"DP={r + a}",
                     "GT:AD", f"{gt}:{r},{a}"])
    write_vcf_gz(os.path.join(MEDIA, "calls", "sample1.vcf.gz"), seqs, header, rows)

    with open(os.path.join(MEDIA, "annotation", "regions.bed"), "w", newline="\n") as f:
        f.write("chr1\t900\t2400\tGENE_A\t0\t+\n"
                "chr1\t3290\t3310\tpolyA_run\t0\t.\n"
                "chr2\t500\t1500\tGENE_B\t0\t-\n")

    items = []
    for chrom, pos, ref, alt, cid, story in calls:
        items.append({"id": cid, "locus": f"{chrom}:{pos}",
                      "note": f"{cid}: {ref}>{alt} at {chrom}:{pos:,}. Is this call real?",
                      "bam": "reads/sample1.bam"})
    with open(os.path.join(HERE, "data", "calls.json"), "w") as f:
        json.dump(items, f, indent=2)
        f.write("\n")
    print("wrote", len(reads), "reads and", len(rows), "calls")


if __name__ == "__main__":
    main()

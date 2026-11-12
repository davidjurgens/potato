# Variant call review

Annotators judge four synthetic variant calls as real, artifact or uncertain
in a `genome_locus` display (igv.js) with the reference, the call set, the
reads and a region track. A `viewer_selection` scheme records the locus the
annotator was looking at and any call or region they clicked.

```bash
python potato/flask_server.py start examples/advanced/variant-review/config.yaml -p 8000
```

All data is synthetic and made by `generate_data.py` (no pysam or htslib
needed):

| File | What it is |
|---|---|
| `media/genome/synthetic.fa` + `.fai` | Two random sequences, chr1 (5 kb, with a poly-A run) and chr2 (3 kb) |
| `media/reads/sample1.bam` + `.bai` | 144 simulated 100 bp single-end reads, 36 per call |
| `media/calls/sample1.vcf.gz` + `.tbi` | Four calls, bgzipped and tabix-indexed |
| `media/annotation/regions.bed` | Two made-up gene spans and the poly-A run |

Two calls are supported by the reads (`call_1` heterozygous, `call_4`
homozygous). `call_2` is carried only by reverse-strand reads at base quality
11, and `call_3` is a one-base deletion inside the poly-A run.

See [Genome loci](../../../docs/annotation-types/science/genome_loci.md).

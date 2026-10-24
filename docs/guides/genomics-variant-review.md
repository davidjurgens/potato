# Genomics: Reviewing Variant Calls

This guide covers manual review of variant calls: an annotator looks at the reads under each call and decides whether it is real, an artifact, or uncertain. Each item is one call. The locus is shown in a [`genome_locus`](../annotation-types/science/genome_loci.md) display (igv.js), and the decision is an ordinary `radio` scheme. Optional questions record what the annotator saw and which call or region they based it on.

## Preparing the files

Put everything under the project's `media/` folder. igv.js reads indexed files through HTTP range requests, so each data file needs its index beside it.

| File | Index | Typical commands |
|---|---|---|
| Reference FASTA | `.fai` | `samtools faidx ref.fa` |
| Reads (BAM / CRAM) | `.bai` / `.crai` | `samtools sort -o s.bam in.bam && samtools index s.bam` |
| Calls (VCF) | `.tbi` | `bgzip calls.vcf && tabix -p vcf calls.vcf.gz` |
| Regions (BED / GFF3) | `.tbi`, or none for a small uncompressed file | `bgzip regions.bed && tabix -p bed regions.bed.gz` |

Use the reference the reads were aligned to, with the same sequence names (`chr1` and `1` are different sequences to igv). For a review set drawn from a large cohort, slice the BAMs to the regions under review (`samtools view -b in.bam chr1:1000-2000 > slice.bam`) so the media folder stays small.

Make the data file one row per call, with the locus and the per-sample files:

```json
{"id": "call_1", "locus": "chr1:1201", "note": "C>G at chr1:1,201", "bam": "reads/sample1.bam"}
```

## The task

```yaml
media_directory: media
data_files: [data/calls.json]
item_properties: {id_key: id, text_key: note}

instance_display:
  fields:
    - key: note
      type: text
    - key: locus
      type: genome_locus
      display_options:
        reference: {fasta: genome/ref.fa}
        flank: 60
        tracks:
          - {name: "Calls", url: calls/cohort.vcf.gz}
          - {name: "Reads", field: bam, height: 260}
          - {name: "Regions", url: annotation/regions.bed}

annotation_schemes:
  - annotation_type: radio
    name: call_review
    description: "Is this variant call real?"
    labels: ["Real", "Artifact", "Uncertain"]
    label_requirement: {required: true}

  - annotation_type: multiselect
    name: evidence_seen
    description: "What did you see in the reads?"
    humanize_labels: false
    labels:
      - "Alt allele on both strands"
      - "Alt allele on one strand only"
      - "Low base quality at the alt"
      - "In a homopolymer or repeat"
      - "Alt allele near read ends"

  - annotation_type: viewer_selection
    name: evidence
    description: "Evidence (optional): click the call or region you based this on"
    viewer_field: locus
    max_selections: 4
```

`examples/advanced/variant-review/` is a runnable version with a synthetic genome, 144 simulated reads and four calls:

```bash
python potato/flask_server.py start examples/advanced/variant-review/config.yaml -p 8000
```

Two of its calls are supported by the reads. One is carried only by reverse-strand reads at low base quality, and one is a one-base deletion inside a poly-A run, so the example shows each answer.

## Reviewing a call

1. Read the call in the note, then look at the reads at the centre of the view. igv colours a mismatching base in the reads; the coverage bar shows the allele fractions.
2. Pan (drag) or zoom (buttons, wheel, or a locus typed into igv's search box) as needed.
3. Answer the radio question. Optionally tick what they saw, and click the call or a region to record it as evidence; selected calls are shaded in the view.

The keyboard shortcuts on the radio labels (1, 2, 3) work while igv is on the page.

## Results

The radio and multiselect answers export like any other scheme. The `viewer_selection` answer is JSON with the locus the annotator last viewed and the clicked calls or features, positions 1-based inclusive (see [Genome loci: data format](../annotation-types/science/genome_loci.md#data-format)). To find calls reviewers disagree on, group the `call_review` answers by item id.

## Offline use

With a local `reference` and local tracks the page loads nothing from outside the Potato server, so the task runs on an air-gapped network. igv's built-in genome ids (`genome: hg38`) and http(s) track URLs fetch from the internet and need `allow_remote: true` on the display.

## Related

- [Genome loci](../annotation-types/science/genome_loci.md)
- [Structural biology](structural-biology.md)

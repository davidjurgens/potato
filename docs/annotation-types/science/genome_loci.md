# Genome loci

The `genome_locus` display opens a region of a genome in igv.js with the tracks a reviewer needs: the reference sequence, read alignments, variant calls, annotations and signal. Its usual job is variant review, where an annotator looks at the reads under a call and answers an ordinary radio question such as "real / artifact / uncertain". A `viewer_selection` scheme can also record the locus the annotator was viewing and any calls or features they clicked.

## Overview

- **Engine:** igv.js 3.8.9 (MIT, with DOMPurify under Apache-2.0 or MPL-2.0 bundled in), committed with Potato. It draws with canvas 2D, so it does not need WebGL.
- **Files** are served from the media directory. The `/media/` route answers HTTP range requests, so igv.js reads an indexed BAM, CRAM, VCF or FASTA a slice at a time instead of downloading it. Gzipped files are sent as their compressed bytes (no `Content-Encoding` header), which is what a tabix-indexed `.vcf.gz` or `.bed.gz` needs.
- **Reference:** an indexed FASTA in the media directory (`.fa` with its `.fai`). igv's built-in genome ids (`hg38`, `mm39`, ...) download their files from the internet, so they are accepted only with `allow_remote: true`.
- **Locus:** read from the item field the display is bound to.
- **Offline by default:** with the default options, the page loads nothing from outside the Potato server.

## Configuration

```yaml
media_directory: media

instance_display:
  fields:
    - key: locus                 # item field holding the locus
      type: genome_locus
      label: "Locus"
      display_options:
        reference:
          fasta: genome/synthetic.fa     # .fai next to it
          name: synthetic
        flank: 60
        tracks:
          - name: "Calls"
            url: calls/sample1.vcf.gz    # same file for every item; .tbi next to it
          - name: "Reads"
            field: bam                   # an item field names the file
            height: 260
          - name: "Regions"
            url: annotation/regions.bed

annotation_schemes:
  - annotation_type: radio
    name: call_review
    description: "Is this variant call real?"
    labels: ["Real", "Artifact", "Uncertain"]
    label_requirement:
      required: true

  - annotation_type: viewer_selection
    name: evidence
    description: "Evidence (optional): click the call or region you based this on"
    viewer_field: locus
    max_selections: 4
```

An item:

```json
{"id": "call_1", "locus": "chr1:1201", "note": "C>G at chr1:1,201", "bam": "reads/sample1.bam"}
```

### Locus

The item field takes the forms igv's locus box takes. Positions are 1-based and inclusive.

| Value | Opens |
|---|---|
| `chr1:1,450-1,550` | that range |
| `chr1:1500` | position 1500 with `flank` bases on each side |
| `chr1` | the whole sequence |

When the reference is local, the sequence name is checked against the `.fai`, and an item naming a sequence the reference lacks shows a message listing the sequences it has. A range past the end of a sequence is clipped.

### Display options

| Option | Default | Description |
|---|---|---|
| `reference` | none | `{fasta: <path>, index: <path>, name: <label>}`. `index` defaults to the FASTA path plus `.fai` |
| `genome` | none | An igv genome id. Needs `allow_remote: true`. Give `reference` or `genome`, not both |
| `tracks` | `[]` | Track list (below) |
| `flank` | `50` | Bases shown either side of a one-position locus |
| `select_features` | `true` | Clicking a call on a variant track or a feature on an annotation track toggles it in the selection, instead of opening igv's popup |
| `height` | none | Leave unset: igv grows with its tracks |
| `allow_remote` | `false` | Allow http(s) URLs for the reference and tracks, and genome ids |

### Tracks

| Key | Description |
|---|---|
| `name` | Track label |
| `url` | A file in the media directory, the same for every item |
| `field` | An item field holding the file, so each item brings its own (give `url` or `field`) |
| `format` | `bam`, `cram`, `vcf`, `bed`, `gff3`, `gff`, `gtf`, `bigbed`, `bigwig`, `bedgraph`, `wig`. Taken from the file extension when left out |
| `index` / `index_field` | The index file. Defaults: `.bai` for BAM, `.crai` for CRAM, `.tbi` for a gzipped VCF, BED, GFF or bedGraph. An uncompressed VCF or BED is read whole |
| `indexed` | `false` to read a file whole even when it is compressed |
| `height`, `color`, `display_mode` | Passed to igv (`display_mode`: `COLLAPSED`, `EXPANDED`, `SQUISHED`) |

A missing file or index named by `url` (or the reference) is reported on the page with its name. For a `field` track, the browser checks the item's value before loading it. An empty value, a path outside the media directory (`/etc/hosts`, `../x.bam`), a value that is not a path (`javascript:...`), a remote URL when `allow_remote` is off, or a name whose format cannot be told keeps the track off the view. A line under the viewer names the track and the reason, and it stays there while the annotator works. A file that passes the check but fails to load is reported by igv in the track. `potato validate` checks the option shapes.

## Panning, zooming and selecting

The annotator can pan by dragging, zoom with the buttons or the mouse wheel, and type a locus into igv's search box. With `select_features` on, clicking a call or a feature selects it; it is shaded in the view and listed under the `viewer_selection` question, where it can be removed. Opening an item does not count as an answer; only the annotator's own panning, zooming and clicking change the stored selection.

## Data format

The `viewer_selection` answer is JSON:

```json
{"viewer": "genome_locus",
 "locus": "chr1:1141-1261",
 "items": [{"chr": "chr1", "start": 1201, "end": 1201, "kind": "variant",
            "name": "call_1", "ref": "C", "alt": "G", "track": "Calls"}]}
```

`locus` is the view the annotator last left the item at. `start` and `end` are 1-based and inclusive; a BED feature `chr1 900 2400` is stored as `start: 901, end: 2400`. `kind` is `variant` for a call and `feature` for an annotation-track feature. The radio answer is stored like any other radio scheme. See [Protein structures](protein_structures.md#browser-api) for the browser API the viewer exposes. There is no export format made for `viewer_selection`; the JSON is the scheme's value in the `jsonl`, `csv` and `tsv` exports.

## Preparing files

- **FASTA:** `samtools faidx ref.fa` writes `ref.fa.fai`.
- **BAM:** sort and index: `samtools sort -o s.bam in.bam && samtools index s.bam`.
- **VCF / BED / GFF:** compress with `bgzip` (not plain `gzip`) and index with `tabix -p vcf calls.vcf.gz` (or `-p bed`, `-p gff`). Small files can stay uncompressed.

## Troubleshooting

- **A track is empty or igv reports a file error:** check that the index sits next to the data file with the default name, or set `index:`. A `.vcf.gz` made with plain `gzip` cannot be indexed; recompress with `bgzip`.
- **"not a sequence in the reference":** the locus names a sequence the `.fai` does not list (for example `1` against a reference that uses `chr1`).
- **"fetched from the internet by igv.js":** a `genome:` id was given without `allow_remote: true`.
- **Reads look wrong after a proxy:** a reverse proxy that adds `Content-Encoding` or strips `Range` breaks indexed reads. Serve `/media/` unchanged.

## Related

- [Variant review guide](../../guides/genomics-variant-review.md)
- [Protein structures](protein_structures.md)
- [Instance display](../instance_display.md)
- Example: `examples/advanced/variant-review/`

# Bringing a Project Into Potato

You do not have to start over. Potato reads the export formats of most tools
you might be leaving, and turns one into a runnable project in a single
command.

```bash
python -m potato.importers --input <your-export> --output-dir my-project/
python potato/flask_server.py start my-project/config.yaml -p 8000
```

The importer writes a data file, a `config.yaml` with the right schema already
declared, and a README. Your existing annotations arrive as **pre-annotations**:
every annotator sees them as a starting point, and their corrections replace
them on save.

---

## Supported formats

| Coming from | Format | Notes |
|---|---|---|
| **brat** | `.ann` + `.txt` | Directory of file pairs. Discontinuous mentions survive; relations do not yet |
| **doccano** | JSONL | Sequence labelling and document classification |
| **Prodigy** | `db-out` JSONL | Rejected tasks are dropped by default — see below |
| CoNLL corpora | CoNLL-2003, CoNLL-U | Column format or 10-column UD, NER from the tag column or `MISC` |
| **NVivo, ATLAS.ti, MAXQDA, Quirkos, QDA Miner** | REFI-QDA `.qdpx` | Codebook hierarchy, codings and annotator identity |
| **CVAT** | XML 1.1 | |
| **V7 / Darwin** | JSON v2 | |
| **Labelbox** | NDJSON | |
| COCO | JSON | Polygons, RLE (compressed and not), crowd regions, keypoints |
| YOLO, Pascal VOC, LabelMe, VIA, KITTI, MOT, DAVIS, Cityscapes, Open Images, WebDataset, HuggingFace | various | |

List them at any time:

```bash
python -m potato.importers --list-formats
```

The format is detected from the file, so `--input-format` is only needed when
detection cannot decide.

---

## Text annotation

### brat

Point at the directory; the importer pairs each `.ann` with its `.txt`.

```bash
python -m potato.importers --input ./my-corpus/ --output-dir potato-project/
```

Offsets are Unicode code points with an exclusive end. That is brat's
convention and Potato's, so nothing is converted.

Discontinuous mentions (`T1<TAB>LOC 0 3;17 21<TAB>New York`) keep their extra
fragments. Relations (`R`) and events (`E`) are reported in the warnings rather
than imported: brat relations reference `T` ids that have to be resolved to
Potato span ids first, and getting that wrong would silently reattach a
relation to the wrong span.

### doccano

```bash
python -m potato.importers --input export.jsonl --output-dir potato-project/
```

Span entries are read in all three shapes doccano has emitted across versions
(`[start, end, label]`, `start_offset`/`end_offset`, and `start`/`end`), so an
older export works. Document categories become their own multiselect scheme.

### Prodigy

```bash
python -m potato.importers --input db-out.jsonl --output-dir potato-project/
```

Tasks answered `reject` or `ignore` are not imported by default. A rejection is
a human saying the annotations are wrong, and importing it as approved work
turns that into positive signal. Pass `--prodigy-keep-rejected` to bring them
in anyway. The `answer` field becomes a radio scheme, so the verdict survives
either way.

### CoNLL

```bash
python -m potato.importers --input eng.train --output-dir potato-project/
```

CoNLL is token-based: it records what the tokens are and what tag each carries,
never where they sat in a string. So the text is **reconstructed** before any
character offset exists, and how faithfully depends on what the file kept:

- **CoNLL-U with `# text =`.** Exact, because the sentence string is in the
  file.
- **CoNLL-U without it.** Rebuilt from tokens. `SpaceAfter=No` in `MISC` is
  honoured.
- **CoNLL-2003.** Tokens joined with single spaces. The format records no
  spacing at all, so `"Dr. Smith"` and `"Dr.  Smith"` produce the same file.

The reconstruction is what gets stored, so the spans line up with what
annotators see. The loss happens upstream, in what CoNLL records.

`--conll-document-unit` decides what counts as one annotation item: `auto`
(the default) follows `-DOCSTART-` and `# newdoc` markers and falls back to one
item per sentence, which is how most NER corpora are distributed.

---

## Qualitative projects (REFI-QDA)

`.qdpx` is the interchange format NVivo, ATLAS.ti, MAXQDA, Quirkos and QDA
Miner all read and write.

```bash
python -m potato.importers --input project.qdpx --output-dir potato-project/
```

The codebook comes across with its hierarchy (each code keeps its parent),
along with descriptions, colours, the codings themselves, and which annotator
made each one.

Exporting back out:

```bash
python -m potato.export -c config.yaml -f qdpx -o ./export/
```

!!! warning "ATLAS.ti supports one level of subcode"
    REFI-QDA lets codes nest to any depth and so does Potato, but ATLAS.ti
    flattens or drops anything past a single level on import — without telling
    the researcher it happened. Export with `flatten_subcodes` to control that
    yourself: every code is re-parented to the top level and renamed
    `Parent > Child > Grandchild`, which loses the tree but keeps every code
    legible.

    Potato warns you when your codebook is deep enough for this to matter.

### The offset trap

REFI-QDA 1.5 §10.2 says selections are "defined by the first and the last
character (Unicode codepoint)", which makes `endPosition` **inclusive** where
Potato's `end` is exclusive. Exporting tools have not all read that the same
way, and a file written with an exclusive end loses its last character on
import.

Potato measures both readings against the source text and uses the one that
fits. It warns when a file contradicts the spec, and
`--qdpx-end-position inclusive|exclusive` forces the reading if you need to.

---

## Computer vision

```bash
# A single annotation file
python -m potato.importers --input instances_val2017.json \
    --image-dir /data/val2017 --image-url-prefix /media \
    --output-dir potato-project/

# A directory dataset (YOLO, KITTI, VOC, ...)
python -m potato.importers --input ./yolo-dataset/ --output-dir potato-project/

# Straight from the HuggingFace Hub
python -m potato.importers --hf-dataset cppe-5 --output-dir potato-project/
```

COCO files are read as-is: polygons, uncompressed RLE, compressed RLE strings
and crowd regions all work without preprocessing. Category IDs survive the
round trip, so an export keeps the original (often sparse) numbering.

Full detail, including per-format caveats, is in
[Import CLI](../tools/import_cli.md) and the
[CV Format Matrix](../data-export/format_matrix.md).

---

## Verifying an import

Imported annotations are pre-annotations, so an item nobody has opened exports
as empty. That keeps machine output from being counted as human work, and it
also makes an import hard to check end to end.

`--seed-user` writes the imported annotations as one annotator's saved work so
you can export immediately and diff:

```bash
python -m potato.importers --input ./corpus/ --output-dir p/ --seed-user check
python -m potato.export -c p/config.yaml -f conll_2003 -o p/export/
```

!!! danger "`--seed-user` fabricates an annotator"
    It exists to verify the round trip without a human opening every item.
    Never include a seeded user in agreement or adjudication analysis.

---

## Known gaps

Each of these produces a warning on the import rather than a silence:

- **brat relations and events.** Reported in the warnings.
- **Sub-token spans through CoNLL.** A span covering `Paris` inside the token
  `Paris.` comes back as the whole token, since a file with sub-token spans is
  one no other CoNLL tool can read.
- **Whitespace, through CoNLL-2003.** The format does not record it.
- **Non-text QDA sources.** Picture, PDF, audio and video sources in a `.qdpx`
  are not imported yet; text sources are.
- **Uncoded selections in a `.qdpx`.** A highlight with no code attached has
  nothing to import. Counted in the warnings.

---

## Related

- [Import CLI](../tools/import_cli.md) — every flag
- [Export Formats](../data-export/export_formats.md) — going the other way
- [Qualitative Data Analysis](../advanced/qda.md) — what Potato does once a QDA
  project is in

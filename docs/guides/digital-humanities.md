# Digital humanities formats

Potato reads and writes four interchange formats used in digital humanities
projects:

| Format | Import | Export | Typical source |
|---|---|---|---|
| IIIF Presentation API 3 (and 2.x) manifests | `-f iiif` | `-f iiif_annotations` | Library and museum image collections, Mirador, Universal Viewer |
| W3C Web Annotation (JSON-LD) | `-f web_annotation` | `-f web_annotation` | Annotorious, Mirador, Hypothesis |
| PAGE XML | `-f page_xml` | `-f page_xml` | Transkribus, eScriptorium, OCR-D |
| TEI P5 | `-f tei` | `-f tei` | Scholarly editions, corpora |

Each importer writes a runnable project (a `config.yaml`, a data file and the
media it needs). The source's annotations come in as pre-annotations, which an
annotator sees as a starting point and which are stored only once someone saves.
Each exporter writes back to the format the data came from.

```bash
potato import -i <file or folder> -o <project folder> [-f <format>]
python potato/flask_server.py start <project folder>/config.yaml -p 8000
python -m potato.export -c <project folder>/config.yaml -f <format> -o <output folder>
```

The format is detected from the file when `-f` is left out. Exporter options are
passed with `--option key=value`.

**Local files are copied only from the input folder.** An importer copies a
local image or text into the project's `media/` folder only when the file is
inside the input folder (the folder you import, or the folder that holds the
file you import) or a folder you name with `--image-dir` or `--texts`. PAGE XML
also accepts the folder above a `page/` folder, where Transkribus puts the
images. Any other reference (an absolute path, a `file://` URI, a `../` path or a
symlink that leads out of the folder) is skipped: the file is not copied, the
import prints a warning that names it, and the summary counts it under "files
outside the input folder". The server publishes `media/`, so this stops an
imported file from pulling something like `/etc/hosts` into the project. Move
the file into the input folder and import again. The IIIF importer takes no
`--image-dir`, so a manifest's images have to be in the manifest's folder.

## IIIF manifests

### Import

```bash
potato import -f iiif -i manifest.json -o book-project
potato import -f iiif -i https://example.org/iiif/book1/manifest.json -o book-project
```

The input is a manifest file, a folder holding one, or an http(s) URL. A URL is
the only input that makes the importer use the network: it fetches the manifest
and any annotation pages the manifest references by URL. For a local manifest,
referenced pages are read from files of the same name beside it; pages that
are not there are listed in the import summary and left out.

Each Canvas becomes one item:

- **Image.** The painting annotation's body `id`. When the body has no usable
  `id`, or `--iiif-size` is given and the body has an Image service, the
  importer requests the image from that service as `{service}/full/{size}/0/default.jpg`. The default
  size is `!2000,2000`, which fits the image in a 2000-pixel square. Local
  manifests may name image files by relative path or `file://` URI; those files
  are copied into the project's `media/` folder.
- **Text.** The manifest label, the canvas label and the manifest and canvas
  `metadata`, shown above the image (an `instance_display` text field).
- **Fields.** `canvas_id`, `canvas_width`, `canvas_height`, `image_width`,
  `image_height`, `label`, `metadata`, `manifest_id`, `iiif_manifest` (the copy of
  the manifest kept under `iiif/`) and `iiif_version`.
- **Pre-annotations.** Annotation pages on the canvas, embedded or referenced,
  are read with the Web Annotation importer below and become shapes on an
  `image_annotation` scheme named `regions`. Their labels come from the
  annotations' tags.

Annotations on a canvas use canvas coordinates. Potato stores shapes relative to
the image, so a canvas whose `width`/`height` differ from the image's pixel size
still lines up.

Presentation 2.x manifests (`sequences`, `canvases`, `images`, `otherContent`)
are read on a best-effort basis.

### Export

```bash
python -m potato.export -c book-project/config.yaml -f iiif_annotations -o out \
    --option base_url=https://example.org/iiif-out/
```

The exporter writes one annotation page per annotated canvas to
`out/annotations/<canvas>.json`, and a copy of the manifest to
`out/manifest.json` with a reference to each page added to its canvas
(`annotations` in Presentation 3, `otherContent` as `sc:AnnotationList` in 2.x).
Open the copied manifest in Mirador or Universal Viewer to see the annotations.

| Shape | Target |
|---|---|
| Box | `<canvas id>#xywh=x,y,w,h` |
| Polygon, polyline, ellipse, freehand | `SpecificResource` with an `SvgSelector` whose `viewBox` is the canvas |
| Landmark | `SpecificResource` with a `PointSelector` |
| Radio, multiselect or text answer | the canvas, with a `TextualBody` (`classifying` or `commenting`) |

Coordinates are scaled from the image to the canvas `width` and `height`.
Each annotation's `creator` is the Potato user who drew it.

| Option | Default | Meaning |
|---|---|---|
| `base_url` | none | Where `out/` will be served from. Page ids become `<base_url>annotations/<canvas>.json`. Without it they are relative paths, which a viewer resolves only when it loads the manifest from the same folder. |
| `embed` | `false` | `true` puts the annotation pages inside the manifest copy, so nothing else needs hosting. |

Masks have no IIIF form and are left out; the export summary counts them.

### Serving images over the IIIF Image API

Potato also serves its own deep-zoom media over the IIIF Image API 3.0
(`/media/iiif/<path>/info.json` and `/<region>/<size>/<rotation>/<quality>.<fmt>`);
see [Deep zoom](../annotation-types/multimedia/deep_zoom.md). That is separate
from the manifest import above.

Example project: `examples/image/iiif-manifest/` (two generated folios, one with
annotations already on it).

## W3C Web Annotation

### Import

```bash
potato import -f web_annotation -i annotations.jsonld -o project --texts documents/
```

Accepted shapes: an `AnnotationCollection` with embedded `AnnotationPage`s, an
`AnnotationPage`, a JSON list of annotations or pages, a single `Annotation`,
the Hypothesis API search response (`{"rows": [...]}`), and IIIF 2.x
`sc:AnnotationList` files.

| Target | Becomes |
|---|---|
| `TextQuoteSelector` and/or `TextPositionSelector` | a span on a `span` scheme |
| `FragmentSelector` `xywh=pixel:` or `xywh=percent:`, or a `#xywh=` fragment on the target | a box on an `image_annotation` scheme |
| `SvgSelector` with a polygon, polyline, rect, circle, ellipse or path | a polygon, polyline, box or ellipse |
| `PointSelector` | a landmark |
| the whole resource | a `radio` answer (a `multiselect` when one person gave several), from `tagging` / `classifying` bodies; or a `text` answer from `describing` / `commenting` bodies |

The label of a span or region is the first `tagging`, `classifying` or
`identifying` body. When there is none, a comment of up to 40 characters is used
as the label (Mirador and Hypothesis users often type the label as a comment).

Annotations are grouped into items by target. A Potato export's
`potato:instance` and `potato:schema` keys are honoured, so an exported project
imports with its item ids and scheme names.

**Text targets.** A span needs the text it was drawn on. The importer looks for
it in `--texts`, which is either a folder of text files named after the last path
segment of each target (`story.txt` for `https://example.org/docs/story.txt`), or
a JSONL / JSON file of rows with `text` and one of `source`, `id`, `url`, `uri` or
`iri`. When `--texts` has no entry, a target that is a local file path is read
directly. Annotations whose text cannot be found are counted and left out.

When a position and a quote disagree, or the position is missing, the span is
found again by its quote, with `prefix` and `suffix` choosing between repeated
occurrences. Positions are accepted against either the source text or the text
as Potato displays it (with whitespace runs collapsed), whichever the quote
confirms. Offsets in the project are code points into the displayed text.

**Image targets.** Rows in `--texts` may also carry `width` and `height` (or
`image_width`, `image_height`) for an image target. Pixel regions need the image
size; it is taken from those rows, from the image file when it is local (or in
`--image-dir`), or from an SVG selector's `viewBox` on the same image. Percent
regions need no size. Pixel regions on an image of unknown size are left out with
a warning rather than placed at a guessed scale.

**People.** Each annotation's `creator` (its `nickname`, `name` or the last part
of its `id`; for Hypothesis the account name) becomes that person's answer. With
`--keep-annotators` those answers are written as each person's saved work. Every
annotation is also written as a pre-annotation. A creator of type `Software` is
recorded as the model that made the suggestion.

### Export

`-f web_annotation` writes `web_annotations.jsonld`, one `AnnotationCollection`
of every span, region and answer. See
[Export formats](../data-export/export_formats.md).

## PAGE XML: HTR line correction and layout correction

### Import

```bash
potato import -f page_xml -i transkribus-export/ -o htr-project                 # lines (default)
potato import -f page_xml -i transkribus-export/ -o layout-project --page-xml-mode regions
```

The input is one `.xml` file or a folder, searched recursively, so a Transkribus
export with its `page/` subfolder works. Each `PcGts > Page` names its image in
`imageFilename`; the image is looked for beside the XML, one folder up and in
`--image-dir`, and copied into `media/`. The 2013-07-15 and 2019-07-15 schema
versions are read, including the older `<Coords><Point x= y=/></Coords>` form.

**Lines mode** (`--page-xml-mode lines`, the default). One item per `TextLine`,
in the page's `ReadingOrder` where it has one. The annotator sees the line cropped
out of the page with the `image_region` display and corrects the recognised text
in a `text_edit` scheme, which starts from the line's `TextEquiv/Unicode` and
shows a word diff against it. The item fields are `htr_text`, `line_image` (the
crop), `line_id`, `region_id`, `line_number`, `page`, `page_xml` and, when the
recogniser stored one, `htr_confidence`.

**Regions mode** (`--page-xml-mode regions`). One item per page. Every region
and text line comes in as a polygon on an `image_annotation` scheme named
`layout`. Text regions are labelled with their `type` (`paragraph`, `heading`,
`marginalia`, ...; `text` when the type is missing), other regions with their
element name (`image` for `ImageRegion`, `table`, `graphic`, ...), text lines
with `line`. Each shape keeps its element id in `attributes.page_xml_id`.

A copy of each XML file is kept in the project under `page_xml/`; the exporter
writes into that copy.

### The `image_region` display

`image_region` shows one rectangle of a larger image. The browser downloads the
page image once and crops it with CSS, so moving between the lines of one page
does not download it again.

```yaml
instance_display:
  fields:
    - key: line_image
      type: image_region
      label: Line
      padding: 12
```

The field value is an object:

```json
{"image": "/media/page-001.png", "width": 2480, "height": 3508,
 "region": [412, 980, 1630, 96],
 "polygon": [[412, 980], [2042, 984], [2040, 1076], [410, 1072]]}
```

`region` is `[x, y, width, height]` in image pixels; when it is missing, the
polygon's bounding box is used. `width` and `height` are the image's size, which
the crop needs. Without them the whole image is shown with a note. Media
references are not resolved inside this object, so `image` should be a URL the
browser can load (the PAGE XML importer writes `/media/<file>`).

| Option | Default | Meaning |
|---|---|---|
| `padding` | `8` | Image pixels shown around the region on each side, clamped to the image. |
| `outline` | `true` | Draw the polygon (or the rectangle) over the crop. |
| `show_page` | `true` | A "Show the whole image" disclosure below the crop, with the region outlined on the full page. |
| `max_scale` | `2.0` | The crop is never drawn wider than this many times its size in pixels. |
| `alt_text` | `""` | Accessible name of the crop (`Image region` when empty). |

### Export

```bash
python -m potato.export -c htr-project/config.yaml -f page_xml -o out
```

The exporter opens the project's copy of each file, changes only what was
corrected, and writes `out/page_xml/<the source's relative path>`. Everything
else (metadata, reading order, styles, custom attributes, the schema version and
its namespace) is written back as it was, and `Metadata/LastChange` is updated.

- **Lines.** The line's `TextEquiv/Unicode` (and `PlainText`, when present) is
  set to the corrected text and the recogniser's `conf` is removed. When the
  text changed, the line's `Word` elements no longer match it and are removed;
  `--option keep_words=true` keeps them. A region with its own `TextEquiv` gets
  its lines' texts joined by newlines.
- **Layout.** A shape that came from the file updates that element's `Coords`,
  and a text region's `type` follows a changed label. A shape the annotator drew
  becomes a new `TextLine` when labelled `line` (placed in the text region that
  contains its centre) or a new `TextRegion` otherwise. An element the annotator
  deleted is removed, together with its `ReadingOrder` reference.

Lines and pages nobody annotated are left unchanged. With several annotators,
each one's files go into a folder named after them; `--option annotator=<name>`
exports one person's corrections.

Example project: `examples/text/htr-line-correction/` (a generated page image with
five lines and a PAGE XML file whose recognised text has errors to correct).

## TEI P5

### Import

```bash
potato import -f tei -i edition/ -o tei-project              # one item per block
potato import -f tei -i letters.xml -o tei-project --tei-unit div
```

The importer reads `<text><body>` of each file (`<text>` itself when there is no
`<body>`).

| `--tei-unit` | One item per |
|---|---|
| `p` (default) | `<p>`, `<ab>`, `<head>`, `<lg>` (its `<l>` lines joined by newlines), and `<l>` outside any `<lg>` |
| `div` | innermost `<div>`, its blocks separated by newlines |
| `s` | `<s>` (paragraphs when the file has no `<s>`) |
| `l` | verse line |

Inline `<persName>`, `<placeName>`, `<orgName>`, `<geogName>`, `<name>`, `<date>`
and `<time>` become spans labelled with the element name. `<rs type="ship">` is
labelled `ship` (`rs` without a `type`). Spans written in
`<standOff><listAnnotation>` with `string-range(id, offset, length)` targets,
which is how the TEI exporter writes spans that cannot nest, are read too.

The item text is a reading text:

- `<choice>` takes `<reg>`, `<corr>` or `<expan>` over `<orig>`, `<sic>` or `<abbr>`;
- `<del>`, `<note>`, `<fw>` and `<figDesc>` are left out;
- `<lb/>` is a newline, or nothing with `break="no"`;
- `<gap/>` is `[...]`;
- whitespace from the XML layout is collapsed.

An element's `xml:id` becomes the item id; otherwise ids are
`<file>-<number>`. The `teiHeader` title is kept as the `title` field, and
`source_file` and `tei_unit` are kept too.

### Export

```bash
python -m potato.export -c tei-project/config.yaml -f tei -o out
```

Each item becomes `<p xml:id="<instance id>">` with its text as the annotation
page showed it (newlines as `<lb/>`), grouped into one TEI document per
`source_file` (`out/tei/<name>.xml`). A span is wrapped in its label when the
label is a TEI name element (`persName`, `placeName`, `orgName`, `geogName`,
`name`, `date`, `time`), and in `<rs type="LABEL">` otherwise.

XML elements must nest. A span that crosses another goes into
`<standOff><listAnnotation>` as an `<annotation>` targeting
`#string-range(<p id>,<offset>,<length>)`, counted in the `<p>`'s string value
(an `<lb/>` adds no characters). The export summary reports how many spans went
there. With several annotators each gets a folder; `--option annotator=<name>`
writes one.

The exporter builds a new document from the project and does not edit the
source file, so header metadata other than the title, and markup that was not a
span, are not carried over.

## Troubleshooting

**"no text for ...: pass texts"** (Web Annotation). The annotations select text
in documents the importer cannot see. Pass `--texts` with the documents.

**Regions are missing after a Web Annotation import.** Pixel regions need the
image size. Add `width` and `height` to `--texts` rows, or pass `--image-dir`
with the images.

**IIIF canvases show no image.** The image is loaded by the browser from the
URL in the manifest. Check the URL opens in the browser, or re-import with
`--iiif-size` to request a smaller copy from the Image service.

**"annotation page ... is referenced, not embedded"** (IIIF). The manifest is
local and points at annotation pages by URL. Save each page beside the manifest
under the last part of its URL, or import from the manifest's URL.

**A PAGE XML page shows no image.** The importer looks for `imageFilename`
beside the XML and one folder up. Pass `--image-dir` with the folder that holds
the images.

**TEI spans are off by some characters.** Check whether the text contains
markup the importer leaves out or rewrites (`<note>`, `<choice>`, `<del>`); the
item text is the reading text, and the offsets index it.

## Related documentation

- [Import CLI](../tools/import_cli.md)
- [Export formats](../data-export/export_formats.md)
- [Instance display](../annotation-types/instance_display.md)
- [Deep zoom](../annotation-types/multimedia/deep_zoom.md)
- [Image annotation](../annotation-types/multimedia/image_annotation.md)

# Multi-Page PDF Anchors & Cross-Page Linking

Annotate multi-page PDFs by creating **anchors** on any page and **linking**
them together — including across pages. Two kinds of anchors are supported and
are freely linkable in any combination:

- **Text spans** — highlight text on a page.
- **Region (bbox) anchors** — draw a box around a non-text region such as a
  figure, table, or image.

Links (text↔text, text↔region, region↔region) are drawn as SVG arcs over a
single overlay that spans the whole page stack, so a link between page 1 and
page 3 is drawn as one continuous arc.

This is enabled with the PDF display's `annotation_mode: link`.

> For plain single-field PDF text/region annotation without linking, see
> [Format Support → PDF](../format_support.md). This page covers the linking mode.

## Quick start

Two runnable examples ship with Potato — launch either from the repo root and
compare:

```bash
# Continuous scroll: all pages stacked, arcs drawn across the scroll
python potato/flask_server.py start examples/advanced/pdf-link-scroll/config.yaml -p 8000

# Paginated: one page at a time, page-thumbnail browser + pin-navigate
python potato/flask_server.py start examples/advanced/pdf-link-paginated/config.yaml -p 8000
```

## Configuration

```yaml
instance_display:
  fields:
    - key: pdf
      type: pdf
      label: "Document"
      display_options:
        annotation_mode: link       # enable anchors + cross-page linking
        view_mode: scroll           # "scroll" (all pages) or "paginated" (page browser)
        max_height: 720
        zoom: page-width            # auto | page-fit | page-width | <number>
        enable_text_anchors: true   # allow text-span anchors
        enable_region_anchors: true # allow region (bbox) anchors
        thumbnail_sidebar: true     # page-thumbnail browser (paginated view)
        anchor_schema: pdf_anchors  # schema recorded on saved anchors
        link_schema: pdf_links      # schema recorded on saved links

        # Labels applied to text spans and region boxes
        anchor_labels:
          - name: claim
            color: "#dc2626"
          - name: figure
            color: "#2563eb"
          - name: citation
            color: "#059669"

        # Relationship types between anchors
        link_types:
          - name: refers_to
            directed: true          # draws an arrowhead
            color: "#dc2626"
            allowed_source_labels: [claim]     # optional constraints
            allowed_target_labels: [figure]
          - name: same_as
            directed: false
            color: "#7c3aed"
```

The `pdf` field value is a URL or a local path served via the `/media/` route
(set `media_directory:` in the config and reference `/media/<file>.pdf`).

### Display options

| Option | Default | Description |
|--------|---------|-------------|
| `annotation_mode` | `span` | Set to `link` for this mode |
| `view_mode` | `scroll` | `scroll` stacks all pages; `paginated` shows one page + a thumbnail browser |
| `zoom` | `auto` | `auto`, `page-fit`, `page-width`, or a numeric scale |
| `enable_text_anchors` | `true` | Allow highlighting text as anchors |
| `enable_region_anchors` | `true` | Allow drawing region boxes as anchors |
| `thumbnail_sidebar` | `true` | Show the page-thumbnail browser (paginated view) |
| `anchor_labels` | — | List of labels (`name` or `{name, color}`) for anchors |
| `link_types` | `[{name: related_to}]` | Relationship types; each supports `directed`, `color`, `max_spans`, `allowed_source_labels`, `allowed_target_labels` |
| `anchor_schema` / `link_schema` | `pdf_anchors` / `pdf_links` | Schema names recorded on saved annotations |

## Using the interface

1. **Pick a label** in the toolbar.
2. **Text anchor:** select text on a page.
   **Region anchor:** click **Draw region**, then drag a box on a page.
3. **Link:** click **Link mode**, choose a link type, then click two anchors
   (on the same or different pages). For a directed link the first click is the
   source. Directed links with `allowed_source_labels` / `allowed_target_labels`
   enforce those constraints.
4. In **scroll** view all pages are visible, so cross-page arcs draw directly.
   In **paginated** view, use the thumbnail browser to navigate; if a link's
   other endpoint is on a page that isn't currently rendered, an off-page stub
   (`→ p.N`) is shown until you navigate to make both endpoints visible.
5. Hover an anchor and click **×** to delete it (its links are removed too);
   click an arc to delete a link.

## How it persists

Anchors and links use Potato's existing storage — no new data model:

- Each anchor is a `SpanAnnotation` whose geometry rides in `format_coords`:
  `{"format": "pdf", "anchor_kind": "text"|"region", "page": N,
  "bbox": [x, y, w, h] (normalized 0–1), "start": s, "end": e}`.
- Each link is a `SpanLink` referencing anchor ids, with `anchor_pages` and
  `anchor_kinds` stored in `properties`.

Everything round-trips through `/updateinstance`, `/api/spans/<id>` and
`/api/links/<id>` and restores on reload.

## Scanned / image-only PDFs (OCR)

Region anchors work on any PDF. Text anchors need a text layer; scanned PDFs
have none. Enable **opt-in** OCR directly on the PDF field: words are extracted
server-side (Tesseract) and handed to the client to build a selectable text
layer over the page image, so text-span anchors work on scanned pages too. It is
**off by default** because it is slow to initialize and requires `pytesseract`
plus the `tesseract` binary.

```yaml
- key: pdf
  type: pdf
  display_options:
    annotation_mode: link
    ocr: auto        # false (default) | true (always OCR) | auto (only pages with no embedded text)
    ocr_dpi: 200     # rasterization DPI (higher = slower/sharper)
    ocr_lang: eng    # Tesseract language
```

With `auto`, pages that already have an embedded text layer use it (fast) and
only image-only pages are OCR'd. OCR runs when the instance is rendered, so
initial load is slower for scanned documents.

## Offline / air-gapped deployments

PDF.js is vendored at `potato/static/vendor/pdfjs/` and loaded locally, so this
mode works without internet access (it falls back to a CDN only if the local
copy is missing).

## Related

- [Format Support](../format_support.md) — single-field PDF/document display
- [Span Linking](span_linking.md) — arc-based linking for plain text spans

# PDF Cross-Page Linking — Scroll View

All PDF pages are stacked in one scrollable container. Highlight text spans and
draw region boxes on any page, then link anchors across pages — the arc is drawn
as one continuous curve down the scroll.

## Run

```bash
python potato/flask_server.py start examples/advanced/pdf-link-scroll/config.yaml -p 8000
```

Open http://localhost:8000, register/sign in, then:

1. Pick a label (`claim`, `figure`, `citation`).
2. Select text for a text anchor, or click **Draw region** and drag a box.
3. Click **Link mode**, choose a link type, and click two anchors on different
   pages. (`refers_to` is directed and constrained to `claim → figure`.)

See also the paginated variant: `examples/advanced/pdf-link-paginated/`, and the
full guide at
[docs/annotation-types/text/pdf_cross_page_linking.md](../../../docs/annotation-types/text/pdf_cross_page_linking.md).

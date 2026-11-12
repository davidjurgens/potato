# PDF Cross-Page Linking — Paginated View

One page is shown at a time with a page-thumbnail browser. Link anchors across
pages with the **pin-navigate** flow. Best for long documents.

## Run

```bash
python potato/flask_server.py start examples/advanced/pdf-link-paginated/config.yaml -p 8000
```

Open http://localhost:8000, register/sign in, then:

1. Pick a label and create an anchor (select text, or **Draw region** + drag).
2. Click **Link mode** and click a source anchor.
3. Click a page **thumbnail** on the left to jump to another page.
4. Click the target anchor there — the link is created. While the other endpoint
   is on a page you're not viewing, an off-page stub (`→ p.N`) is shown; navigate
   back to see both endpoints.

See also the scroll variant: `examples/advanced/pdf-link-scroll/`, and the full
guide at
[docs/annotation-types/text/pdf_cross_page_linking.md](../../../docs/annotation-types/text/pdf_cross_page_linking.md).

# IIIF manifest import

A Presentation 3 manifest over two generated folio images. The canvases are
1200 x 1600 and the images 600 x 800. Folio 1r already has two annotations in
canvas coordinates, a box around the initial and a polygon around the ruled
text block; they land on the initial and the text block only if the importer
scales canvas coordinates to the image. Each canvas
is one item, with the manifest and canvas metadata shown above the image.

```bash
# from the repository root
python potato/flask_server.py start examples/image/iiif-manifest/config.yaml -p 8000

# the regions as IIIF annotation pages, attached to a copy of the manifest
python -m potato.export -c examples/image/iiif-manifest/config.yaml -f iiif_annotations \
    -o /tmp/iiif-out --option embed=true
```

Open `/tmp/iiif-out/manifest.json` in a IIIF viewer to see the annotations. The
image ids in this manifest are relative file paths so the example runs offline;
a published manifest uses URLs.

`source/` holds the input manifest and images. The project was made with:

```bash
potato import -f iiif -i examples/image/iiif-manifest/source/manifest.json -o examples/image/iiif-manifest
```

See [Digital humanities formats](../../../docs/guides/digital-humanities.md).

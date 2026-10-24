# HTR line correction from PAGE XML

A generated page image with five text lines, and a PAGE XML file whose
recognised text has errors in it (`rnaster`, `arived`, `barels`, a comma for a
full stop, `shilling`). Each line is one item: the line is cropped out of the
page with the `image_region` display, and its recognised text is pre-filled in a
`text_edit` box for correction.

```bash
# from the repository root
python potato/flask_server.py start examples/text/htr-line-correction/config.yaml -p 8000

# after correcting some lines: the PAGE XML with the corrections written in
python -m potato.export -c examples/text/htr-line-correction/config.yaml -f page_xml -o /tmp/htr-out
```

`source/` holds the input as Transkribus lays it out (`letter.png` beside a
`page/` folder with `letter.xml`). The project was made with:

```bash
potato import -f page_xml -i examples/text/htr-line-correction/source -o examples/text/htr-line-correction
```

`--page-xml-mode regions` imports the same file as one page with every region
and line as a polygon, for layout correction. See
[Digital humanities formats](../../../docs/guides/digital-humanities.md).

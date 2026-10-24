"""
Synthetic digital-humanities fixtures: a page image with text drawn on it and
its PAGE XML, a IIIF manifest over generated folio images, a TEI file.

Everything here is made up for the tests and the examples; nothing is copied
from a real edition or collection.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

PAGE_NS = "http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15"

#: (region id, region type, [(line id, true text, recognised text)])
PAGE_REGIONS = [
    ("r1", "heading", [("r1l1", "Letter to the harbour master", "Letter to the harbour rnaster")]),
    ("r2", "paragraph", [
        ("r2l1", "The ship Margaret arrived on the ninth", "The ship Margaret arived on the ninth"),
        ("r2l2", "of March with forty barrels of salt", "of March with forty barels of salt"),
        ("r2l3", "and a cargo of timber from Riga.", "and a cargo of timber from Riga,"),
    ]),
    ("r3", "marginalia", [("r3l1", "paid 3 shillings", "paid 3 shilling")]),
]

PAGE_WIDTH, PAGE_HEIGHT = 1000, 700


def _font(size: int):
    from PIL import ImageFont
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def line_boxes() -> Dict[str, Tuple[int, int, int, int]]:
    """Where each line is drawn: line id -> (x, y, w, h) in page pixels."""
    boxes = {}
    boxes["r1l1"] = (120, 60, 640, 56)
    for i, lid in enumerate(("r2l1", "r2l2", "r2l3")):
        boxes[lid] = (120, 190 + i * 90, 760, 56)
    boxes["r3l1"] = (650, 520, 300, 46)
    return boxes


#: A distinct colour behind each line, so a crop can be checked by its pixels.
LINE_COLOURS = {"r1l1": (255, 236, 179), "r2l1": (200, 230, 255), "r2l2": (210, 245, 210),
                "r2l3": (255, 215, 225), "r3l1": (230, 220, 255)}


def make_page_image(path: Path) -> Tuple[int, int]:
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (PAGE_WIDTH, PAGE_HEIGHT), (250, 247, 238))
    draw = ImageDraw.Draw(img)
    boxes = line_boxes()
    for _rid, _rtype, lines in PAGE_REGIONS:
        for lid, truth, _htr in lines:
            x, y, w, h = boxes[lid]
            draw.rectangle([x, y, x + w, y + h], fill=LINE_COLOURS[lid])
            draw.text((x + 10, y + 8), truth, fill=(40, 30, 20), font=_font(34 if lid != "r3l1" else 28))
    img.save(path)
    return img.size


def _rect(x, y, w, h) -> str:
    return f"{x},{y} {x + w},{y} {x + w},{y + h} {x},{y + h}"


def page_xml_text(image_name: str = "letter.png", with_words: bool = True) -> str:
    boxes = line_boxes()
    regions = []
    region_boxes = {"r1": (100, 40, 700, 100), "r2": (100, 170, 820, 290), "r3": (630, 500, 340, 90)}
    for rid, rtype, lines in PAGE_REGIONS:
        rx, ry, rw, rh = region_boxes[rid]
        line_xml = []
        for lid, _truth, htr in lines:
            x, y, w, h = boxes[lid]
            words = ""
            if with_words:
                words = "".join(
                    f'<Word id="{lid}w{i}"><Coords points="{_rect(x + i * 10, y, 8, h)}"/>'
                    f'<TextEquiv><Unicode>{tok}</Unicode></TextEquiv></Word>'
                    for i, tok in enumerate(htr.split()[:2]))
            line_xml.append(
                f'<TextLine id="{lid}" custom="readingOrder {{index:0;}}">'
                f'<Coords points="{_rect(x, y, w, h)}"/>'
                f'<Baseline points="{x},{y + h - 10} {x + w},{y + h - 10}"/>{words}'
                f'<TextEquiv conf="0.87"><Unicode>{htr}</Unicode></TextEquiv></TextLine>')
        region_text = "\n".join(h for _l, _t, h in lines)
        regions.append(
            f'<TextRegion id="{rid}" type="{rtype}"><Coords points="{_rect(rx, ry, rw, rh)}"/>'
            + "".join(line_xml)
            + f'<TextEquiv><Unicode>{region_text}</Unicode></TextEquiv></TextRegion>')
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<PcGts xmlns="{PAGE_NS}" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="{PAGE_NS} {PAGE_NS}/pagecontent.xsd">
  <Metadata>
    <Creator>synthetic fixture</Creator>
    <Created>2026-01-01T00:00:00</Created>
    <LastChange>2026-01-01T00:00:00</LastChange>
    <!-- kept by the exporter -->
  </Metadata>
  <Page imageFilename="{image_name}" imageWidth="{PAGE_WIDTH}" imageHeight="{PAGE_HEIGHT}">
    <ReadingOrder><OrderedGroup id="ro1"><RegionRefIndexed index="0" regionRef="r1"/><RegionRefIndexed index="1" regionRef="r2"/><RegionRefIndexed index="2" regionRef="r3"/></OrderedGroup></ReadingOrder>
    {"".join(regions)}
    <ImageRegion id="img1"><Coords points="{_rect(860, 40, 110, 110)}"/></ImageRegion>
  </Page>
</PcGts>
"""


def make_page_xml(folder: Path, transkribus_layout: bool = False) -> Path:
    """letter.png + letter.xml (in page/ when ``transkribus_layout``). Returns the XML path."""
    folder.mkdir(parents=True, exist_ok=True)
    make_page_image(folder / "letter.png")
    xml_dir = folder / "page" if transkribus_layout else folder
    xml_dir.mkdir(parents=True, exist_ok=True)
    xml = xml_dir / "letter.xml"
    xml.write_text(page_xml_text(), encoding="utf-8")
    return xml


# ---------------------------------------------------------------------------
# IIIF
# ---------------------------------------------------------------------------

FOLIOS = [("f1r", "Folio 1r", (196, 120, 60)), ("f1v", "Folio 1v", (60, 110, 160))]
IMAGE_SIZE = (600, 800)       # pixels of the generated images
CANVAS_SIZE = (1200, 1600)    # canvas coordinates: twice the image


def make_folio_image(path: Path, title: str, colour) -> None:
    from PIL import Image, ImageDraw
    w, h = IMAGE_SIZE
    img = Image.new("RGB", (w, h), (244, 236, 216))
    draw = ImageDraw.Draw(img)
    draw.rectangle([40, 40, w - 40, h - 40], outline=(150, 120, 90), width=3)
    # An initial at image (60, 60)-(160, 160) = canvas (120, 120)-(320, 320).
    draw.rectangle([60, 60, 160, 160], fill=colour)
    draw.text((85, 70), title[-2], fill=(255, 255, 255), font=_font(70))
    for i in range(12):
        y = 200 + i * 42
        draw.line([(70, y), (w - 70, y)], fill=(120, 100, 80), width=2)
    draw.text((180, 90), title, fill=(60, 40, 20), font=_font(30))
    img.save(path)


def iiif_manifest(base: str = "https://example.org/iiif/book1", local_images: bool = True,
                  with_annotations: bool = True) -> dict:
    """A Presentation 3 manifest over the generated folios.

    Image bodies are relative file paths when ``local_images`` (so the
    importer copies them), else URLs on a IIIF Image service.
    """
    cw, ch = CANVAS_SIZE
    canvases = []
    for n, (slug, label, _c) in enumerate(FOLIOS, start=1):
        cid = f"{base}/canvas/{slug}"
        body = {"id": f"images/{slug}.png" if local_images else f"https://images.example.org/iiif/{slug}/full/max/0/default.jpg",
                "type": "Image", "format": "image/png",
                "width": IMAGE_SIZE[0], "height": IMAGE_SIZE[1]}
        if not local_images:
            body["service"] = [{"id": f"https://images.example.org/iiif/{slug}", "type": "ImageService3",
                                "profile": "level1"}]
        canvas = {
            "id": cid, "type": "Canvas", "width": cw, "height": ch,
            "label": {"en": [label]},
            "metadata": [{"label": {"en": ["Folio"]}, "value": {"none": [slug]}}],
            "items": [{"id": f"{cid}/page/p1", "type": "AnnotationPage", "items": [{
                "id": f"{cid}/annotation/painting", "type": "Annotation", "motivation": "painting",
                "body": body, "target": cid}]}],
        }
        if with_annotations and n == 1:
            canvas["annotations"] = [{"id": f"{cid}/annotations/existing", "type": "AnnotationPage", "items": [
                {"id": f"{cid}/annotations/existing/a1", "type": "Annotation", "motivation": "tagging",
                 "body": {"type": "TextualBody", "value": "initial", "purpose": "tagging"},
                 "target": f"{cid}#xywh=120,120,200,200"},
                {"id": f"{cid}/annotations/existing/a2", "type": "Annotation", "motivation": "tagging",
                 "body": {"type": "TextualBody", "value": "text block", "purpose": "tagging"},
                 "target": {"type": "SpecificResource", "source": cid, "selector": {
                     "type": "SvgSelector",
                     "value": f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {cw} {ch}">'
                              '<polygon points="140,380 1060,380 1060,1440 140,1440"/></svg>'}}},
            ]}]
        canvases.append(canvas)
    return {
        "@context": "http://iiif.io/api/presentation/3/context.json",
        "id": f"{base}/manifest.json", "type": "Manifest",
        "label": {"en": ["Account book (synthetic)"]},
        "summary": {"en": ["Two generated folios for trying IIIF import and export."]},
        "metadata": [{"label": {"en": ["Date"]}, "value": {"none": ["1750"]}},
                     {"label": {"en": ["Shelfmark"]}, "value": {"none": ["MS Synthetic 1"]}}],
        "items": canvases,
    }


def iiif_manifest_v2(base: str = "https://example.org/iiif/book2") -> dict:
    cw, ch = CANVAS_SIZE
    canvases = []
    for slug, label, _c in FOLIOS:
        cid = f"{base}/canvas/{slug}"
        canvases.append({
            "@id": cid, "@type": "sc:Canvas", "label": label, "width": cw, "height": ch,
            "images": [{"@type": "oa:Annotation", "motivation": "sc:painting", "on": cid,
                        "resource": {"@id": f"images/{slug}.png", "@type": "dctypes:Image",
                                     "width": IMAGE_SIZE[0], "height": IMAGE_SIZE[1]}}],
            "otherContent": [{"@id": f"{base}/list/{slug}.json", "@type": "sc:AnnotationList"}],
        })
    return {"@context": "http://iiif.io/api/presentation/2/context.json",
            "@id": f"{base}/manifest.json", "@type": "sc:Manifest", "label": "Ledger (synthetic, v2)",
            "metadata": [{"label": "Date", "value": "1801"}],
            "sequences": [{"@type": "sc:Sequence", "canvases": canvases}]}


def iiif_list_v2(base: str = "https://example.org/iiif/book2", slug: str = "f1r") -> dict:
    cid = f"{base}/canvas/{slug}"
    return {"@context": "http://iiif.io/api/presentation/2/context.json",
            "@id": f"{base}/list/{slug}.json", "@type": "sc:AnnotationList",
            "resources": [{"@type": "oa:Annotation", "motivation": ["oa:commenting"],
                           "resource": {"@type": "dctypes:Text", "chars": "<p>initial</p>"},
                           "on": f"{cid}#xywh=120,120,200,200"}]}


def make_iiif(folder: Path, version: int = 3) -> Path:
    """Generated folio images and a manifest over them. Returns the manifest path."""
    (folder / "images").mkdir(parents=True, exist_ok=True)
    for slug, label, colour in FOLIOS:
        make_folio_image(folder / "images" / f"{slug}.png", label, colour)
    manifest = folder / "manifest.json"
    if version == 3:
        manifest.write_text(json.dumps(iiif_manifest(), indent=1), encoding="utf-8")
    else:
        manifest.write_text(json.dumps(iiif_manifest_v2(), indent=1), encoding="utf-8")
        (folder / "f1r.json").write_text(json.dumps(iiif_list_v2(), indent=1), encoding="utf-8")
    return manifest


# ---------------------------------------------------------------------------
# TEI
# ---------------------------------------------------------------------------

TEI_TEXT = """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader>
    <fileDesc>
      <titleStmt><title>Harbour letters (synthetic)</title></titleStmt>
      <publicationStmt><p>Test fixture.</p></publicationStmt>
      <sourceDesc><p>Made up for the tests.</p></sourceDesc>
    </fileDesc>
  </teiHeader>
  <text>
    <body>
      <div type="letter">
        <head>To <persName ref="#hm">the harbour master</persName></head>
        <p xml:id="p1">The ship <rs type="ship">Margaret</rs> came into
          <placeName>Leith</placeName> on <date when="1750-03-09">9 March 1750</date>,
          sent by <orgName>the   Baltic   Company</orgName>.<note>A later hand adds: late.</note></p>
        <p>Paid to <persName>John <choice><abbr>Smyth</abbr><expan>Smith</expan></choice></persName>
          for <choice><sic>fourty</sic><corr>forty</corr></choice> barrels.</p>
      </div>
      <div type="poem">
        <lg>
          <l>The tide comes in at <placeName>Dunbar</placeName>,</l>
          <l>the gulls go out to sea.</l>
        </lg>
      </div>
    </body>
  </text>
</TEI>
"""


def make_tei(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "letters.xml"
    path.write_text(TEI_TEXT, encoding="utf-8")
    return path

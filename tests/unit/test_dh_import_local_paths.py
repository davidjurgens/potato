"""Audit 97 V1: an import file must not copy local files from outside its input.

PAGE XML ``imageFilename``, a Web Annotation ``source`` and a IIIF canvas
image are data from whoever made the export. The importers copied whatever
they named into the project's ``media/``, which the server publishes:
``imageFilename="/etc/hosts"`` published the machine's hosts file. Absolute
paths, ``file://`` URIs, ``../`` and symlinks out of the input are refused,
with a warning that names the reference.
"""

import json
import os
from pathlib import Path

import pytest

from potato.importers.projects.iiif import IIIFImporter
from potato.importers.projects.page_xml import PageXMLImporter
from potato.importers.projects.web_annotation import WebAnnotationImporter
from tests.helpers import dh_fixtures as fx
from tests.helpers.test_utils import create_test_directory

SECRET = "secret-local-file-contents"


@pytest.fixture
def dirs():
    root = Path(create_test_directory("dh_local_paths"))
    outside = root / "outside"
    outside.mkdir()
    secret = outside / "secret.png"
    secret.write_text(SECRET)
    (outside / "secret.txt").write_text(SECRET)
    src = root / "src"
    src.mkdir()
    return src, outside, secret


def _copied(result):
    return {os.path.realpath(p) for p in result.media_files.values()}


def _refused(result):
    return [w for w in result.warnings if "outside the input folder" in w]


def _page(src, image_name):
    xml = src / "letter.xml"
    xml.write_text(fx.page_xml_text(image_name=image_name), encoding="utf-8")
    return xml


@pytest.mark.parametrize("kind", ["absolute", "file_uri", "dotdot", "symlink"])
def test_page_xml_image_outside_the_input_is_not_copied(dirs, kind):
    src, outside, secret = dirs
    if kind == "absolute":
        name = str(secret)
    elif kind == "file_uri":
        name = secret.as_uri()
    elif kind == "dotdot":
        name = "../outside/secret.png"
    else:
        (src / "link.png").symlink_to(secret)
        name = "link.png"
    _page(src, name)
    result = PageXMLImporter().parse_path(src, {})
    assert os.path.realpath(secret) not in _copied(result)
    assert _refused(result), result.warnings


def test_page_xml_image_inside_the_input_is_still_copied(dirs):
    src, _outside, _secret = dirs
    fx.make_page_image(src / "letter.png")
    _page(src, "letter.png")
    result = PageXMLImporter().parse_path(src, {})
    assert os.path.realpath(src / "letter.png") in _copied(result)
    assert not _refused(result)


def test_page_xml_image_dir_is_allowed(dirs):
    src, outside, _secret = dirs
    fx.make_page_image(outside / "letter.png")
    _page(src, "letter.png")
    result = PageXMLImporter().parse_path(src, {"image_dir": str(outside)})
    assert os.path.realpath(outside / "letter.png") in _copied(result)


def _web_annotation(src, source, selector):
    doc = {"@context": "http://www.w3.org/ns/anno.jsonld", "id": "urn:a1", "type": "Annotation",
           "body": {"type": "TextualBody", "value": "tag", "purpose": "tagging"},
           "target": {"source": source, "selector": selector}}
    path = src / "annotations.jsonld"
    path.write_text(json.dumps(doc))
    return path


def test_web_annotation_image_source_outside_the_input_is_not_copied(dirs):
    src, _outside, secret = dirs
    path = _web_annotation(src, secret.as_uri(),
                           {"type": "FragmentSelector", "value": "xywh=1,1,5,5"})
    result = WebAnnotationImporter().parse_path(path, {})
    assert os.path.realpath(secret) not in _copied(result)
    assert _refused(result), result.warnings


def test_web_annotation_text_source_outside_the_input_is_not_read(dirs):
    src, outside, _secret = dirs
    path = _web_annotation(src, (outside / "secret.txt").as_uri(),
                           {"type": "TextQuoteSelector", "exact": "local"})
    result = WebAnnotationImporter().parse_path(path, {})
    assert all(SECRET not in json.dumps(item.fields) for item in result.items)
    assert _refused(result), result.warnings


@pytest.mark.parametrize("body_id", ["file_uri", "dotdot"])
def test_iiif_canvas_image_outside_the_input_is_not_copied(dirs, body_id):
    src, _outside, secret = dirs
    manifest = fx.iiif_manifest(with_annotations=False)
    ref = secret.as_uri() if body_id == "file_uri" else "../outside/secret.png"
    for canvas in manifest["items"]:
        canvas["items"][0]["items"][0]["body"]["id"] = ref
    path = src / "manifest.json"
    path.write_text(json.dumps(manifest))
    result = IIIFImporter().parse_path(path, {})
    assert os.path.realpath(secret) not in _copied(result)
    assert _refused(result), result.warnings
    # The IIIF importer takes no --image-dir, so the advice must not name it.
    assert all("--image-dir" not in w and "manifest" in w for w in _refused(result)), \
        _refused(result)
    assert result.skipped["files outside the input folder"] == len(manifest["items"])


# ---------------------------------------------------------------------------
# Audit 97 V1, re-verify: the audio importers and the writer
# ---------------------------------------------------------------------------

RAVEN = ("Selection\tView\tChannel\tBegin Time (s)\tEnd Time (s)\t"
         "Low Freq (Hz)\tHigh Freq (Hz)\tAnnotation\n"
         "1\tSpectrogram 1\t1\t0.1\t0.5\t100\t2000\tcall\n")
TEXTGRID = '''File type = "ooTextFile"
Object class = "TextGrid"

xmin = 0
xmax = 1
tiers? <exists>
size = 1
item []:
    item [1]:
        class = "IntervalTier"
        name = "words"
        xmin = 0
        xmax = 1
        intervals: size = 1
        intervals [1]:
            xmin = 0
            xmax = 1
            text = "hello"
'''


def _secret_audio(outside):
    audio = outside / "s.wav"
    audio.write_bytes(b"RIFF" + b"SECRETAUDIO" * 8)
    return audio


@pytest.mark.parametrize("fmt, table, body", [
    ("raven", "rec.txt", RAVEN),
    ("audacity_labels", "rec.txt", "0.1\t0.5\tcall\n"),
])
def test_linked_audio_out_of_the_input_is_not_copied(dirs, fmt, table, body, capsys):
    """potato-skill's repro: rec.wav -> outside/s.wav inside the input folder
    printed "wrote .../media/rec.wav", and the copy held the outside file."""
    from potato.importers.cli import main
    src, outside, _ = dirs
    (src / table).write_text(body)
    os.symlink(_secret_audio(outside), src / "rec.wav")
    out = src.parent / f"out_{fmt}"
    assert main(["-i", str(src), "-f", fmt, "-o", str(out)]) == 0
    assert not (out / "media" / "rec.wav").exists()
    printed = capsys.readouterr().out
    assert "outside the input folder" in printed
    rows = [json.loads(line) for f in (out / "data").glob("*.jsonl") for line in f.open()]
    assert rows and all(not r.get("audio_url") for r in rows)


def test_linked_media_beside_a_textgrid_is_not_copied(dirs):
    from potato.importers.projects.textgrid import TextGridImporter
    from potato.importers.projects.writer import write_project
    src, outside, _ = dirs
    (src / "rec.TextGrid").write_text(TEXTGRID)
    os.symlink(_secret_audio(outside), src / "rec.wav")
    result = TextGridImporter().parse_path(src, {})
    assert not result.media_files and _refused(result)
    out = src.parent / "out_tg"
    write_project(result, str(out), source=str(src))
    assert not (out / "media" / "rec.wav").exists()


def test_a_linked_table_out_of_the_input_is_not_read(dirs):
    from potato.importers.projects.bioacoustics import RavenImporter
    src, outside, _ = dirs
    (src / "ok.txt").write_text(RAVEN)
    (outside / "leak.txt").write_text(RAVEN.replace("call", SECRET))
    os.symlink(outside / "leak.txt", src / "leak.txt")
    result = RavenImporter().parse_path(src, {})
    assert SECRET not in json.dumps([i.fields for i in result.items] + [i.responses for i in result.items])
    assert any("leak.txt links to a file outside" in w for w in result.warnings)


def test_the_writer_refuses_media_from_outside_the_input(dirs):
    """The check at the copy, for any importer that forgets its own."""
    from potato.importers.projects.base import ProjectImportResult
    from potato.importers.projects.writer import write_project
    src, outside, secret = dirs
    result = ProjectImportResult(source_format="test", text_key="text")
    result.media_files["media/x.png"] = str(secret)
    (src / "in.png").write_text("fine")
    result.media_files["media/in.png"] = str(src / "in.png")
    out = src.parent / "out_writer"
    write_project(result, str(out), source=str(src / "export.json"))
    assert not (out / "media" / "x.png").exists()
    assert (out / "media" / "in.png").read_text() == "fine"
    assert result.skipped["files outside the input folder"] == 1


def test_a_link_in_the_texts_folder_is_not_read(dirs):
    src, outside, _ = dirs
    texts = src / "texts"
    texts.mkdir()
    os.symlink(outside / "secret.txt", texts / "letter.txt")
    anno = src / "annos.json"
    anno.write_text(json.dumps({
        "@context": "http://www.w3.org/ns/anno.jsonld", "type": "Annotation",
        "body": {"type": "TextualBody", "value": "a note", "purpose": "commenting"},
        "target": {"source": "letter.txt",
                   "selector": {"type": "TextPositionSelector", "start": 0, "end": 3}}}))
    result = WebAnnotationImporter().parse_path(anno, {"texts": str(texts)})
    assert SECRET not in json.dumps([i.fields for i in result.items])
    assert any("letter.txt links to a file outside the texts folder" in w for w in result.warnings)

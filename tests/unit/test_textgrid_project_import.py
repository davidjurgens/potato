"""potato import of Praat TextGrid / ELAN EAF files as tiered annotations."""

import json
import os
import wave
from pathlib import Path

import yaml

from potato.importers import projects
from potato.importers.projects.writer import write_project
from potato.export.textgrid_exporter import TextGridExporter
from potato.export.base import ExportContext
from tests.helpers.test_utils import create_test_directory

LONG_TG = '''File type = "ooTextFile"
Object class = "TextGrid"

xmin = 0
xmax = 1.5
tiers? <exists>
size = 2
item []:
    item [1]:
        class = "IntervalTier"
        name = "words"
        xmin = 0
        xmax = 1.5
        intervals: size = 3
        intervals [1]:
            xmin = 0
            xmax = 0.4
            text = "hello"
        intervals [2]:
            xmin = 0.4
            xmax = 0.6
            text = ""
        intervals [3]:
            xmin = 0.6
            xmax = 1.5
            text = "world ""quoted"""
    item [2]:
        class = "IntervalTier"
        name = "phones"
        xmin = 0
        xmax = 1.5
        intervals: size = 2
        intervals [1]:
            xmin = 0
            xmax = 0.2
            text = "h"
        intervals [2]:
            xmin = 0.2
            xmax = 0.4
            text = "e"
'''


def _wav(path):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 8000)


def _source(name):
    d = Path(create_test_directory(name))
    src = d / "src"
    src.mkdir()
    (src / "clip01.TextGrid").write_text(LONG_TG, encoding="utf-16")
    _wav(src / "clip01.wav")
    return d, src


def test_detected_and_parsed_with_utf16():
    _, src = _source("tg_import_parse")
    assert projects.detect(str(src)) == "textgrid"
    result = projects.IMPORTERS["textgrid"].parse_path(src)
    scheme = result.schemes[0]
    assert scheme["annotation_type"] == "tiered_annotation"
    tiers = {t["name"]: t for t in scheme["tiers"]}
    assert set(tiers) == {"words", "phones"}
    # Few distinct values: those become the tier's labels
    assert tiers["phones"]["labels"] == ["e", "h"]
    item = result.items[0]
    assert item.instance_id == "clip01" and item.fields["audio_url"] == "/media/clip01.wav"
    words = item.predictions["tiers"]["annotations"]["words"]
    assert [w["start_time"] for w in words] == [0.0, 600.0]
    assert words[1]["label"] == 'world "quoted"'
    assert result.media_files == {"media/clip01.wav": str(src / "clip01.wav")}


def test_written_project_copies_media_and_round_trips_through_the_exporter():
    d, src = _source("tg_import_write")
    out = d / "project"
    result = projects.IMPORTERS["textgrid"].parse_path(src)
    write_project(result, str(out), source=str(src))
    assert (out / "media" / "clip01.wav").exists()
    config = yaml.safe_load((out / "config.yaml").read_text())
    assert config["pre_annotation"]["enabled"] is True
    row = json.loads((out / "data" / "src.jsonl").read_text().splitlines()[0])
    stored = row["predictions"]["tiers"]

    ctx = ExportContext(config=config, annotations=[
        {"instance_id": "clip01", "labels": {"tiers": json.dumps(stored)}}],
        items={"clip01": row}, schemas=config["annotation_schemes"], output_dir=str(out))
    res = TextGridExporter().export(ctx, str(out / "export"))
    assert res.success, res.errors
    text = Path(res.files_written[0]).read_text()
    assert 'text = "hello"' in text and 'name = "phones"' in text


EAF_EDGE = '''<?xml version="1.0" encoding="UTF-8"?>
<ANNOTATION_DOCUMENT>
  <HEADER MEDIA_FILE="" TIME_UNITS="milliseconds"/>
  <TIME_ORDER>
    <TIME_SLOT TIME_SLOT_ID="ts1" TIME_VALUE="0"/>
    <TIME_SLOT TIME_SLOT_ID="ts2"/>
    <TIME_SLOT TIME_SLOT_ID="ts3" TIME_VALUE="2000"/>
    <TIME_SLOT TIME_SLOT_ID="ts4" TIME_VALUE="1500"/>
  </TIME_ORDER>
  <TIER TIER_ID="words@A" PARTICIPANT="A">
    <ANNOTATION><ALIGNABLE_ANNOTATION ANNOTATION_ID="a1" TIME_SLOT_REF1="ts1" TIME_SLOT_REF2="ts2">
      <ANNOTATION_VALUE>hello</ANNOTATION_VALUE></ALIGNABLE_ANNOTATION></ANNOTATION>
    <ANNOTATION><ALIGNABLE_ANNOTATION ANNOTATION_ID="a2" TIME_SLOT_REF1="ts2" TIME_SLOT_REF2="ts3">
      <ANNOTATION_VALUE>world</ANNOTATION_VALUE></ALIGNABLE_ANNOTATION></ANNOTATION>
    <ANNOTATION><ALIGNABLE_ANNOTATION ANNOTATION_ID="a3" TIME_SLOT_REF1="ts1" TIME_SLOT_REF2="ts4">
      <ANNOTATION_VALUE>overlap</ANNOTATION_VALUE></ALIGNABLE_ANNOTATION></ANNOTATION>
  </TIER>
  <TIER TIER_ID="gloss@A" PARTICIPANT="A" PARENT_REF="words@A">
    <ANNOTATION><REF_ANNOTATION ANNOTATION_ID="r1" ANNOTATION_REF="a1">
      <ANNOTATION_VALUE>greeting</ANNOTATION_VALUE></REF_ANNOTATION></ANNOTATION>
  </TIER>
  <TIER TIER_ID="notes" PARTICIPANT="A"/>
</ANNOTATION_DOCUMENT>
'''


def test_eaf_edges_are_kept_and_reported():
    """Audit 96 L7: an unaligned slot became 0 s, a participant's tiers merged,
    an empty tier vanished, PARENT_REF was dropped, and overlaps went unsaid."""
    d = Path(create_test_directory("eaf_edges"))
    src = d / "src"
    src.mkdir()
    (src / "s1.eaf").write_text(EAF_EDGE, encoding="utf-8")
    _wav(src / "s1.wav")
    result = projects.IMPORTERS["eaf"].parse_path(src)
    tiers = {t["name"]: t for t in result.schemes[0]["tiers"]}
    assert set(tiers) == {"words@A", "gloss@A", "notes"}
    assert tiers["gloss@A"]["tier_type"] == "dependent"
    assert tiers["gloss@A"]["parent_tier"] == "words@A"
    words = {a["label"] if a["value"] == "" else a["value"]: a
             for a in result.items[0].predictions["tiers"]["annotations"]["words@A"]}
    world = words["world"]
    assert world["start_time"] == 1000.0 and world["end_time"] == 2000.0
    warnings = " ".join(result.warnings)
    assert "1 time slot(s) had no time" in warnings
    assert "overlapping segment(s) in tier 'words@A'" in warnings
    write_project(result, str(d / "out"), source=str(src))
    from potato.server_utils.config_module import load_and_validate_config
    load_and_validate_config(str(d / "out" / "config.yaml"), str(d / "out"))

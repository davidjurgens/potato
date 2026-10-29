"""
TextGrid and EAF files survive import -> annotation -> export.

Each case below was a loss found by round-tripping real files: the export kept
only the first annotator, wrote point tiers as zero-length intervals, escaped
quotes C-style and doubled backslashes, cut the grid at the last label,
pointed ELAN children at ids that did not exist, renamed linguistic types to
ones the file never defined, and gave ELAN the server's /media/ path.
"""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from potato.export.base import ExportContext
from potato.export.eaf_exporter import EAFExporter
from potato.export.textgrid_exporter import TextGridExporter
from potato.importers import projects
from potato.server_utils.transcripts.align import parse_textgrid, textgrid_point_tiers
from tests.helpers.test_utils import create_test_directory

TG = '''File type = "ooTextFile"
Object class = "TextGrid"

xmin = 0
xmax = 3
tiers? <exists>
size = 2
item []:
    item [1]:
        class = "IntervalTier"
        name = "words"
        xmin = 0
        xmax = 3
        intervals: size = 4
        intervals [1]:
            xmin = 0
            xmax = 0.4
            text = ""
        intervals [2]:
            xmin = 0.4
            xmax = 1.1
            text = "Marianna"
        intervals [3]:
            xmin = 1.1
            xmax = 1.9
            text = "made ""the"" m\\aerm"
        intervals [4]:
            xmin = 1.9
            xmax = 3
            text = ""
    item [2]:
        class = "TextTier"
        name = "tones"
        xmin = 0
        xmax = 3
        points: size = 2
        points [1]:
            number = 0.7
            mark = "H*"
        points [2]:
            number = 1.6
            mark = "L-L%"
'''

EAF = '''<?xml version="1.0" encoding="UTF-8"?>
<ANNOTATION_DOCUMENT AUTHOR="" DATE="2026-10-28T00:00:00" FORMAT="3.0" VERSION="3.0">
<HEADER MEDIA_FILE="" TIME_UNITS="milliseconds"><MEDIA_DESCRIPTOR MEDIA_URL="file:///rec01.wav" MIME_TYPE="audio/x-wav" RELATIVE_MEDIA_URL="./rec01.wav"/></HEADER>
<TIME_ORDER><TIME_SLOT TIME_SLOT_ID="ts1" TIME_VALUE="300"/><TIME_SLOT TIME_SLOT_ID="ts2" TIME_VALUE="1500"/><TIME_SLOT TIME_SLOT_ID="ts3" TIME_VALUE="1600"/><TIME_SLOT TIME_SLOT_ID="ts4" TIME_VALUE="2800"/></TIME_ORDER>
<TIER LINGUISTIC_TYPE_REF="utt" PARTICIPANT="A" TIER_ID="tx@A">
<ANNOTATION><ALIGNABLE_ANNOTATION ANNOTATION_ID="a1" TIME_SLOT_REF1="ts1" TIME_SLOT_REF2="ts2"><ANNOTATION_VALUE>evlerimizde</ANNOTATION_VALUE></ALIGNABLE_ANNOTATION></ANNOTATION>
<ANNOTATION><ALIGNABLE_ANNOTATION ANNOTATION_ID="a2" TIME_SLOT_REF1="ts3" TIME_SLOT_REF2="ts4"><ANNOTATION_VALUE>geldiler</ANNOTATION_VALUE></ALIGNABLE_ANNOTATION></ANNOTATION>
</TIER>
<TIER LINGUISTIC_TYPE_REF="assoc" PARENT_REF="tx@A" PARTICIPANT="A" TIER_ID="ft@A">
<ANNOTATION><REF_ANNOTATION ANNOTATION_ID="a3" ANNOTATION_REF="a1"><ANNOTATION_VALUE>in our houses</ANNOTATION_VALUE></REF_ANNOTATION></ANNOTATION>
<ANNOTATION><REF_ANNOTATION ANNOTATION_ID="a4" ANNOTATION_REF="a2"><ANNOTATION_VALUE>they came</ANNOTATION_VALUE></REF_ANNOTATION></ANNOTATION>
</TIER>
<LINGUISTIC_TYPE GRAPHIC_REFERENCES="false" LINGUISTIC_TYPE_ID="utt" TIME_ALIGNABLE="true"/>
<LINGUISTIC_TYPE CONSTRAINTS="Symbolic_Association" GRAPHIC_REFERENCES="false" LINGUISTIC_TYPE_ID="assoc" TIME_ALIGNABLE="false"/>
<CONSTRAINT DESCRIPTION="1-1 association with a parent annotation" STEREOTYPE="Symbolic_Association"/>
</ANNOTATION_DOCUMENT>
'''


def _import(name, filename, text):
    d = Path(create_test_directory(name))
    src = d / "src"
    src.mkdir()
    (src / filename).write_text(text, encoding="utf-8")
    (src / filename).with_suffix(".wav").write_bytes(b"RIFF")   # copied as the media
    fmt = projects.detect(str(src))
    return d, projects.IMPORTERS[fmt].parse_path(src)


def _context(result, out, answers_by_user):
    item = result.items[0]
    fields = dict(item.fields)
    anns = [{"instance_id": item.instance_id, "user_id": user,
             "labels": {"tiers": json.dumps(data)}}
            for user, data in answers_by_user.items()]
    return ExportContext(config={"task_dir": str(out)}, annotations=anns,
                         items={item.instance_id: fields}, schemas=result.schemes,
                         output_dir=str(out))


# -- TextGrid ------------------------------------------------------------------

def test_point_tiers_import_as_point_tiers():
    _, result = _import("tg_rt_import", "spk01.TextGrid", TG)
    tiers = {t["name"]: t for t in result.schemes[0]["tiers"]}
    assert tiers["tones"].get("point") is True and not tiers["words"].get("point")
    tones = result.items[0].predictions["tiers"]["annotations"]["tones"]
    assert [(t["start_time"], t["end_time"], t["label"]) for t in tones] == [
        (700.0, 700.0, "H*"), (1600.0, 1600.0, "L-L%")]
    assert result.items[0].fields["duration"] == 3.0


def test_textgrid_round_trip_keeps_points_quotes_backslashes_and_length():
    d, result = _import("tg_rt_export", "spk01.TextGrid", TG)
    stored = result.items[0].predictions["tiers"]
    res = TextGridExporter().export(_context(result, d, {"alice": stored}), str(d / "out"))
    assert res.success, res.errors
    text = Path(res.files_written[0]).read_text()

    assert 'class = "TextTier"' in text and "number = 0.7" in text
    assert 'text = "made ""the"" m\\aerm"' in text
    assert "\\\\" not in text
    assert text.splitlines()[4] == "xmax = 3.0"
    # The written file reads back as what went in.
    again = parse_textgrid(text)
    assert textgrid_point_tiers(text) == ["tones"]
    assert {(s["speaker"], s["start"], s["end"], s["text"]) for s in again} == {
        ("words", 0.4, 1.1, "Marianna"), ("words", 1.1, 1.9, 'made "the" m\\aerm'),
        ("tones", 0.7, 0.7, "H*"), ("tones", 1.6, 1.6, "L-L%")}


def test_short_format_writes_points_too():
    d, result = _import("tg_rt_short", "spk01.TextGrid", TG)
    stored = result.items[0].predictions["tiers"]
    res = TextGridExporter().export(_context(result, d, {"alice": stored}), str(d / "out"),
                                    {"format": "short"})
    text = Path(res.files_written[0]).read_text()
    assert '"TextTier"\n"tones"' in text
    assert {(s["speaker"], s["start"]) for s in parse_textgrid(text) if s["speaker"] == "tones"} \
        == {("tones", 0.7), ("tones", 1.6)}


def test_short_format_ends_with_a_newline():
    """Without it praatio read the last TextTier as empty."""
    d, result = _import("tg_rt_nl", "spk01.TextGrid", TG)
    stored = result.items[0].predictions["tiers"]
    for fmt in ("short", "long"):
        res = TextGridExporter().export(_context(result, d, {"alice": stored}),
                                        str(d / ("out_" + fmt)), {"format": fmt})
        assert Path(res.files_written[0]).read_text().endswith("\n")


def test_overlapping_intervals_are_named():
    """Praat refuses an interval tier whose intervals overlap; the export said nothing."""
    d, result = _import("tg_rt_overlap", "spk01.TextGrid", TG)
    stored = json.loads(json.dumps(result.items[0].predictions["tiers"]))
    words = stored["annotations"]["words"]
    words[1]["start_time"] = words[0]["end_time"] - 200.0
    res = TextGridExporter().export(_context(result, d, {"alice": stored}), str(d / "out"))
    (warning,) = [w for w in res.warnings if "overlap" in w]
    assert "tier 'words'" in warning and "(alice)" in warning
    clean = TextGridExporter().export(
        _context(result, d, {"alice": result.items[0].predictions["tiers"]}), str(d / "out2"))
    assert not any("overlap" in w for w in clean.warnings)


def test_every_annotator_gets_a_file():
    d, result = _import("tg_rt_two", "spk01.TextGrid", TG)
    stored = result.items[0].predictions["tiers"]
    bob = json.loads(json.dumps(stored))
    bob["annotations"]["words"][0]["start_time"] = 500.0
    res = TextGridExporter().export(
        _context(result, d, {"alice": stored, "bob": bob}), str(d / "out"))
    names = sorted(Path(p).name for p in res.files_written)
    assert names == ["spk01_alice_tiers.TextGrid", "spk01_bob_tiers.TextGrid"]
    bob_text = Path(d / "out" / "spk01_bob_tiers.TextGrid").read_text()
    assert "xmin = 0.5" in bob_text


def test_saved_media_duration_sets_the_grid_length():
    d, result = _import("tg_rt_media", "spk01.TextGrid", TG)
    stored = dict(result.items[0].predictions["tiers"], media_duration=4.25)
    result.items[0].fields.pop("duration")
    res = TextGridExporter().export(_context(result, d, {"alice": stored}), str(d / "out"))
    assert Path(res.files_written[0]).read_text().splitlines()[4] == "xmax = 4.25"


# -- EAF -----------------------------------------------------------------------

def _eaf_round_trip(name, answers=None):
    d, result = _import(name, "rec01.eaf", EAF)
    stored = result.items[0].predictions["tiers"]
    res = EAFExporter().export(_context(result, d, answers or {"alice": stored}), str(d / "out"))
    assert res.success, res.errors
    return result, res, ET.parse(res.files_written[0]).getroot()


def test_eaf_import_keeps_constraint_participant_and_parents():
    _, result = _import("eaf_rt_import", "rec01.eaf", EAF)
    tiers = {t["name"]: t for t in result.schemes[0]["tiers"]}
    assert tiers["ft@A"]["constraint_type"] == "symbolic_association"
    assert tiers["ft@A"]["participant"] == "A" and tiers["ft@A"]["linguistic_type"] == "assoc"
    anns = result.items[0].predictions["tiers"]["annotations"]
    by_id = {a["id"]: a for a in anns["tx@A"]}
    assert [by_id[a["parent_id"]]["label"] for a in anns["ft@A"]] == [
        "evlerimizde", "geldiler"]


def test_eaf_children_reference_parents_that_exist():
    _, res, root = _eaf_round_trip("eaf_rt_refs")
    ids = {}
    for tier in root.iter("TIER"):
        for ann in tier.iter("ALIGNABLE_ANNOTATION"):
            ids[ann.get("ANNOTATION_ID")] = ann.find("ANNOTATION_VALUE").text
    refs = {r.find("ANNOTATION_VALUE").text: r.get("ANNOTATION_REF")
            for r in root.iter("REF_ANNOTATION")}
    assert {v: ids[ref] for v, ref in refs.items()} == {
        "in our houses": "evlerimizde", "they came": "geldiler"}


def test_eaf_tiers_keep_their_types_and_participant():
    _, _, root = _eaf_round_trip("eaf_rt_types")
    tiers = {t.get("TIER_ID"): t for t in root.iter("TIER")}
    assert tiers["ft@A"].get("LINGUISTIC_TYPE_REF") == "assoc"
    assert tiers["ft@A"].get("PARTICIPANT") == "A" and tiers["tx@A"].get("PARTICIPANT") == "A"
    types = {lt.get("LINGUISTIC_TYPE_ID"): lt for lt in root.iter("LINGUISTIC_TYPE")}
    # Every type a tier names is defined, with its constraint.
    assert {t.get("LINGUISTIC_TYPE_REF") for t in tiers.values()} <= set(types)
    assert types["assoc"].get("CONSTRAINTS") == "Symbolic_Association"
    assert types["assoc"].get("TIME_ALIGNABLE") == "false"
    assert types["utt"].get("TIME_ALIGNABLE") == "true"


def test_eaf_media_points_at_the_file_not_the_server():
    _, _, root = _eaf_round_trip("eaf_rt_media")
    media = root.find("HEADER/MEDIA_DESCRIPTOR")
    assert media is not None
    assert media.get("RELATIVE_MEDIA_URL") == "./rec01.wav"
    assert media.get("MEDIA_URL") == "file:///rec01.wav"   # not the server's /media/ path


def test_eaf_media_under_the_task_dir_gets_its_absolute_url():
    from potato.export.eaf_exporter import EAFExporter as E
    d = Path(create_test_directory("eaf_rt_media_abs"))
    (d / "media").mkdir()
    (d / "media" / "rec01.wav").write_bytes(b"RIFF")
    absolute, relative = E._media_urls("/media/rec01.wav", str(d))
    assert absolute == "file://" + str((d / "media" / "rec01.wav").resolve()).replace(" ", "%20")
    assert relative == "./rec01.wav"
    assert E._media_urls("https://x.org/a.wav", str(d)) == ("https://x.org/a.wav", "")


def test_time_aligned_dependent_tiers_are_alignable():
    d = Path(create_test_directory("eaf_rt_included"))
    schema = {"annotation_type": "tiered_annotation", "name": "tiers", "source_field": "audio_url",
              "tiers": [{"name": "utt"},
                        {"name": "word", "tier_type": "dependent", "parent_tier": "utt",
                         "constraint_type": "included_in"}]}
    data = {"annotations": {
        "utt": [{"id": "u1", "tier": "utt", "start_time": 0, "end_time": 2000, "label": "hi there"}],
        "word": [{"id": "w1", "tier": "word", "start_time": 0, "end_time": 900, "label": "hi",
                  "parent_id": "u1"}]}}
    ctx = ExportContext(config={}, annotations=[
        {"instance_id": "r", "user_id": "a", "labels": {"tiers": json.dumps(data)}}],
        items={"r": {"audio_url": ""}}, schemas=[schema], output_dir=str(d))
    res = EAFExporter().export(ctx, str(d / "out"))
    root = ET.parse(res.files_written[0]).getroot()
    word = next(t for t in root.iter("TIER") if t.get("TIER_ID") == "word")
    assert word.find("ANNOTATION/ALIGNABLE_ANNOTATION") is not None
    assert word.find("ANNOTATION/REF_ANNOTATION") is None

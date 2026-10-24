"""Audit 97, bioacoustics / camera-trap / structure / geo findings.

V3   Raven and Audacity imports swapped inverted times into a zero-length box,
     dropped unreadable rows without a word, and a bad Audacity line came out
     as "no Audacity label tracks files at ...".
V4   Camera-trap exports wrote the detector's score as the classifier's.
V5   A small .cif.gz that inflates to hundreds of MB was read whole.
V6   Junk spectrogram prefill entries reached the stored answer.
V7   A per-item basemap skipped the basemap rules.
V9   One bad MegaDetector conf aborted the import with no location.
V10  "Triaged empty but has a box": the exports disagreed.
V11  Raven export with no sample_rate left High Freq empty; MegaDetector
     bboxes outside 0..1 passed silently; -100 Hz became null silently.
"""

import csv
import gzip
import json
import os
import wave

import pytest

from potato.export.base import ExportContext
from potato.export.registry import export_registry
from potato.importers import projects
from potato.server_utils import acoustic_tables as t
from tests.helpers.test_utils import create_test_directory

RAVEN_HEADER = ("Selection\tView\tChannel\tBegin Time (s)\tEnd Time (s)\t"
                "Low Freq (Hz)\tHigh Freq (Hz)\tAnnotation\n")


def _wav(path, seconds=1.0, rate=22050):
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))


# ---------------------------------------------------------------------------
# V3 / V11 (negative Hz): parsing
# ---------------------------------------------------------------------------

class TestAcousticParsing:

    def test_raven_inverted_times_are_swapped_not_collapsed(self):
        boxes = t.parse_raven(RAVEN_HEADER + "1\tSpectrogram 1\t1\t2.4\t1.8\t100\t200\tx\n")
        assert (boxes[0]["start_s"], boxes[0]["end_s"]) == (1.8, 2.4)

    def test_audacity_inverted_times_are_swapped_not_collapsed(self):
        (box,) = t.parse_audacity("2.4\t1.8\tx\n")
        assert (box["start_s"], box["end_s"]) == (1.8, 2.4)

    def test_birdnet_csv_inverted_times_are_swapped(self):
        text = ("Start (s),End (s),Scientific name,Common name,Confidence\n"
                "6.0,3.0,Turdus migratorius,American Robin,0.9\n")
        (box,) = t.parse_birdnet_csv(text)
        assert (box["start_s"], box["end_s"]) == (3.0, 6.0)

    def test_unreadable_raven_rows_are_named(self):
        problems = []
        text = (RAVEN_HEADER + "1\tSpectrogram 1\t1\t3,5\t4\t100\t200\tcomma\n"
                "2\tSpectrogram 1\t1\tabc\t4\t100\t200\tword\n"
                "3\tSpectrogram 1\t1\t5\t6\t100\t200\tok\n")
        boxes = t.parse_raven(text, problems=problems)
        assert [b["label"] for b in boxes] == ["ok"]
        assert len(problems) == 2
        assert "line 2 (selection 1)" in problems[0] and "'3,5'" in problems[0]
        assert "line 3 (selection 2)" in problems[1] and "'abc'" in problems[1]

    def test_negative_frequency_is_refused_with_a_problem(self):
        problems = []
        (box,) = t.parse_raven(RAVEN_HEADER + "1\tSpectrogram 1\t1\t1\t2\t-100\t900\tx\n",
                               problems=problems)
        assert box["low_hz"] is None and box["high_hz"] == 900.0
        assert len(problems) == 1 and "-100" in problems[0] and "negative" in problems[0]

    def test_bad_audacity_line_is_located_not_fatal(self):
        problems = []
        boxes = t.parse_audacity("1\t2\ta\n3,5\t4\tb\n5\t6\tc\n", problems=problems)
        assert [b["label"] for b in boxes] == ["a", "c"]
        assert problems and problems[0].startswith("line 2:")


class TestAcousticImportReport:

    def test_raven_import_counts_and_names_skipped_rows(self):
        d = create_test_directory("audit97_raven_skips")
        _wav(os.path.join(d, "rec.wav"))
        with open(os.path.join(d, "rec.Table.1.selections.txt"), "w") as f:
            f.write(RAVEN_HEADER + "1\tSpectrogram 1\t1\t3,5\t4\t100\t200\tbad\n"
                    "2\tSpectrogram 1\t1\t1\t2\t100\t200\tgood\n")
        result = projects.IMPORTERS["raven"].parse_path(d, {})
        assert [b["label"] for b in result.items[0].predictions["calls"]] == ["good"]
        assert sum(result.skipped.values()) == 1
        assert any("rec.Table.1.selections.txt, line 2" in w and "'3,5'" in w
                   for w in result.warnings)

    def test_audacity_file_with_a_bad_line_says_where(self):
        d = create_test_directory("audit97_audacity_bad")
        _wav(os.path.join(d, "rec.wav"))
        path = os.path.join(d, "rec.txt")
        # More bad lines than good: not taken as a label track, but the
        # message names the file and the line instead of "no files".
        with open(path, "w") as f:
            f.write("1.0\t2.0\tok\n3,5\t4\tx\n4,5\t5\ty\n")
        with pytest.raises(ValueError) as exc:
            projects.IMPORTERS["audacity_labels"].parse_path(path, {})
        assert "rec.txt" in str(exc.value) and "line 2" in str(exc.value)
        assert "no Audacity" not in str(exc.value)

    def test_audacity_file_with_one_bad_line_imports_with_a_warning(self):
        d = create_test_directory("audit97_audacity_one_bad")
        _wav(os.path.join(d, "rec.wav"))
        path = os.path.join(d, "rec.txt")
        with open(path, "w") as f:
            f.write("1.0\t2.0\tok\n3,5\t4\tx\n")
        result = projects.IMPORTERS["audacity_labels"].parse_path(path, {})
        assert [b["label"] for b in result.items[0].predictions["calls"]] == ["ok"]
        assert any("rec.txt, line 2" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# V11: Raven export uses Nyquist when it can be known
# ---------------------------------------------------------------------------

def _spectro_context(task_dir, item, scheme_extra=None):
    scheme = {"annotation_type": "spectrogram_annotation", "name": "calls",
              "source_field": "audio_url", "labels": ["call"]}
    scheme.update(scheme_extra or {})
    boxes = [{"start_s": 0.1, "end_s": 0.4, "low_hz": None, "high_hz": None, "label": "call"}]
    return ExportContext(
        config={"task_dir": task_dir}, schemas=[scheme], output_dir="",
        items={"rec": item},
        annotations=[{"instance_id": "rec", "user_id": "u", "spans": {},
                      "labels": {"calls": {"_data": json.dumps(boxes)}}}])


def _raven_high(res):
    with open(res.files_written[0]) as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    return rows[0]["High Freq (Hz)"]


class TestRavenNyquist:

    def test_wav_header_gives_nyquist_without_sample_rate(self):
        d = create_test_directory("audit97_raven_nyquist")
        os.makedirs(os.path.join(d, "media"), exist_ok=True)
        _wav(os.path.join(d, "media", "rec.wav"), rate=22050)
        ctx = _spectro_context(d, {"recording": "rec.wav", "audio_url": "/media/rec.wav"})
        res = export_registry.export("raven", ctx, os.path.join(d, "out"), {})
        assert _raven_high(res) == "11025"
        assert not res.warnings

    def test_no_way_to_know_warns(self):
        d = create_test_directory("audit97_raven_unknown")
        ctx = _spectro_context(d, {"recording": "rec.mp3", "audio_url": "/media/rec.mp3"})
        res = export_registry.export("raven", ctx, os.path.join(d, "out"), {})
        assert _raven_high(res) == ""
        assert any("High Freq" in w and "max_freq" in w for w in res.warnings)

    def test_max_freq_still_used(self):
        d = create_test_directory("audit97_raven_maxfreq")
        ctx = _spectro_context(d, {"recording": "rec.mp3", "audio_url": "/media/rec.mp3"},
                               {"max_freq": 8000})
        res = export_registry.export("raven", ctx, os.path.join(d, "out"), {})
        assert _raven_high(res) == "8000"


# ---------------------------------------------------------------------------
# V4 / V9 / V10 / V11: camera traps
# ---------------------------------------------------------------------------

MD = {
    "info": {"format_version": "1.4", "detector": "md_v5a.0.0.pt"},
    "detection_categories": {"1": "animal", "2": "person"},
    "classification_categories": {"5": "Puma concolor"},
    "images": [
        {"file": "IMG_0100.JPG", "detections": [
            {"category": "1", "conf": 0.96, "bbox": [0.1, 0.1, 0.2, 0.2],
             "classifications": [["5", 0.91]]}]},
        {"file": "IMG_0101.JPG", "detections": [
            {"category": "1", "conf": "hi", "bbox": [0.1, 0.1, 0.2, 0.2]},
            {"category": "1", "conf": 0.83, "bbox": [0.8, 0.8, 0.5, 0.5],
             "classifications": [["5", 0.78]]}]},
    ],
}


@pytest.fixture
def md_result():
    d = create_test_directory("audit97_md")
    path = os.path.join(d, "md.json")
    with open(path, "w") as f:
        json.dump(MD, f)
    return d, projects.IMPORTERS["megadetector"].parse_path(path, {})


def _ctx(result, triage="animal"):
    annotations, items = [], {}
    for item in result.items:
        items[item.instance_id] = dict(item.fields, id=item.instance_id)
        boxes = json.loads(json.dumps(item.predictions["detections"]))
        annotations.append({"instance_id": item.instance_id, "user_id": "rev", "spans": {},
                            "labels": {"triage": {triage: triage}},
                            "image_annotations": {"detections": boxes}})
    return ExportContext(config={}, annotations=annotations, items=items,
                         schemas=result.schemes, output_dir="")


class TestCameraTraps:

    def test_bad_conf_is_located_and_skipped(self, md_result):
        _, result = md_result
        assert len(result.items) == 2
        assert any("md.json: images[1] (IMG_0101.JPG) detections[0]" in w and "'hi'" in w
                   for w in result.warnings)
        assert result.skipped["detections with a conf or bbox that is not a number"] == 1

    def test_bbox_outside_the_image_is_warned_and_kept(self, md_result):
        _, result = md_result
        assert len(result.items[1].predictions["detections"]) == 1
        assert any("images[1] (IMG_0101.JPG) detections[1]" in w and "outside" in w
                   for w in result.warnings)

    def test_import_keeps_the_classifier_score(self, md_result):
        _, result = md_result
        box = result.items[0].predictions["detections"][0]
        assert box["confidence"] == 0.96
        assert box["attributes"] == {"classification_confidence": 0.91}

    def test_megadetector_export_writes_the_classifier_score(self, md_result):
        d, result = md_result
        res = export_registry.export("megadetector", _ctx(result), os.path.join(d, "md"), {})
        data = json.load(open(res.files_written[0]))
        det = {i["file"]: i["detections"] for i in data["images"]}
        assert det["IMG_0100.JPG"][0]["conf"] == 0.96
        assert det["IMG_0100.JPG"][0]["classifications"] == [["1", 0.91]]
        assert det["IMG_0101.JPG"][0]["classifications"] == [["1", 0.78]]

    def test_camtrap_dp_writes_the_classifier_score(self, md_result):
        d, result = md_result
        out = os.path.join(d, "dp")
        export_registry.export("camtrap_dp", _ctx(result), out, {})
        with open(os.path.join(out, "observations.csv")) as f:
            rows = list(csv.DictReader(f))
        assert [r["classificationProbability"] for r in rows] == ["0.91", "0.78"]

    def test_edited_box_has_no_model_classification_score(self, md_result):
        d, result = md_result
        ctx = _ctx(result)
        ctx.annotations[0]["image_annotations"]["detections"][0]["edited"] = True
        res = export_registry.export("megadetector", ctx, os.path.join(d, "md_e"), {})
        data = json.load(open(res.files_written[0]))
        first = data["images"][0]["detections"][0]
        assert first["conf"] == 1.0 and first["classifications"] == [["1", 1.0]]

    @pytest.mark.parametrize("fmt", ["megadetector", "camtrap_dp", "darwin_core", "darwin"])
    def test_triaged_empty_with_a_box_keeps_the_box_and_warns(self, md_result, fmt):
        d, result = md_result
        res = export_registry.export(fmt, _ctx(result, triage="empty"), os.path.join(d, fmt), {})
        assert res.success
        (warning,) = [w for w in res.warnings if "triaged empty" in w]
        assert "IMG_0100.JPG (rev)" in warning and "keeps the boxes" in warning
        if fmt == "megadetector":
            data = json.load(open(res.files_written[0]))
            assert all(len(i["detections"]) == 1 for i in data["images"])
        if fmt == "camtrap_dp":
            with open(os.path.join(d, fmt, "observations.csv")) as f:
                rows = list(csv.DictReader(f))
            assert [r["observationType"] for r in rows] == ["animal", "animal"]
            assert all("triaged empty" in r["observationComments"] for r in rows)
        if fmt == "darwin_core":
            with open(res.files_written[0]) as f:
                rows = list(csv.DictReader(f))
            assert len(rows) == 2 and all("triaged empty" in r["identificationRemarks"] for r in rows)


# ---------------------------------------------------------------------------
# V5: structures
# ---------------------------------------------------------------------------

class TestStructureSizeCap:

    def test_gzip_bomb_is_refused_at_the_cap(self, monkeypatch):
        from potato.media import structures
        d = create_test_directory("audit97_gzip_bomb")
        path = os.path.join(d, "bomb.cif.gz")
        with gzip.open(path, "wb") as f:
            for _ in range(8):
                f.write(b"#" * (1 << 20))          # 8 MB of comment
        monkeypatch.setattr(structures, "MAX_STRUCTURE_BYTES", 2 * 1024 * 1024)
        seen = []
        real = structures.gzip.GzipFile.read

        def spy(self, size=-1):
            seen.append(size)
            return real(self, size)
        monkeypatch.setattr(structures.gzip.GzipFile, "read", spy)
        with pytest.raises(structures.StructureError, match="larger than 2 MB"):
            structures.read_residues(path)
        # Read as a stream, in bounded chunks, never all at once.
        assert seen and all(0 < s <= 2 * 1024 * 1024 + 1 for s in seen)
        assert len(seen) <= 3

    def test_plain_file_over_the_cap_is_refused(self, monkeypatch):
        from potato.media import structures
        d = create_test_directory("audit97_big_cif")
        path = os.path.join(d, "big.cif")
        with open(path, "wb") as f:
            f.write(b"#" * 4096)
        monkeypatch.setattr(structures, "MAX_STRUCTURE_BYTES", 1024)
        with pytest.raises(structures.StructureError, match="larger than"):
            structures.read_residues(path)

    def test_refusal_is_cached(self, monkeypatch):
        from potato.media import structures
        d = create_test_directory("audit97_cached_refusal")
        path = os.path.join(d, "bomb2.cif.gz")
        with gzip.open(path, "wb") as f:
            f.write(b"#" * (1 << 20))
        monkeypatch.setattr(structures, "MAX_STRUCTURE_BYTES", 1024)
        calls = []
        real = structures.read_residues
        monkeypatch.setattr(structures, "read_residues",
                            lambda p, fmt=None: calls.append(p) or real(p, fmt))
        for _ in range(3):
            with pytest.raises(structures.StructureError):
                structures.cached_residues(path)
        assert len(calls) == 1

    def test_small_gzip_still_reads(self):
        from potato.media import structures
        d = create_test_directory("audit97_small_gz")
        path = os.path.join(d, "ok.pdb.gz")
        line = ("ATOM      1  CA  ALA A   1      11.104  13.207   2.100  1.00 20.00           C\n")
        with gzip.open(path, "wb") as f:
            f.write(line.encode())
        (res,) = structures.read_residues(path)
        assert (res.chain, res.resi, res.resn) == ("A", 1, "ALA")


# ---------------------------------------------------------------------------
# V6: spectrogram prefill
# ---------------------------------------------------------------------------

def test_clean_prefill_drops_junk_and_names_it():
    boxes, dropped = t.clean_prefill(
        ["a", "junk", {"start_s": 1.0, "end_s": 0.5, "label": "x"}, {"start_s": "q"}])
    assert [(b["start_s"], b["end_s"]) for b in boxes] == [(0.5, 1.0)]
    assert dropped == ["#1 'a'", "#2 'junk'", "#4 an object without numeric times"]
    assert t.clean_prefill(json.dumps(["a"])) == ([], ["#1 'a'"])


# ---------------------------------------------------------------------------
# V7: per-item basemaps
# ---------------------------------------------------------------------------

class TestItemBasemap:
    SCHEME = {"annotation_type": "geo_annotation", "name": "where",
              "basemap": {"geojson": "maps/r.geojson"}, "basemap_field": "map"}

    def test_external_tiles_without_attribution_are_refused(self):
        from potato.geo.scheme import check_item_basemap
        reason = check_item_basemap(self.SCHEME, {"tiles": "https://evil.example/{z}/{x}/{y}.png"})
        assert reason and "attribution" in reason

    def test_unconfigured_external_host_is_refused(self):
        from potato.geo.scheme import check_item_basemap
        reason = check_item_basemap(self.SCHEME, {"tiles": "https://evil.example/{z}/{x}/{y}.png",
                                                  "attribution": "x"})
        assert reason and "evil.example" in reason
        assert "evil.example" in check_item_basemap(self.SCHEME, "https://evil.example/a.geojson")

    def test_configured_host_and_local_files_pass(self):
        from potato.geo.scheme import check_item_basemap
        scheme = dict(self.SCHEME, basemap={"tiles": "https://t.example.org/{z}/{x}/{y}.png",
                                            "attribution": "a"})
        assert check_item_basemap(scheme, {"tiles": "https://t.example.org/b/{z}/{x}/{y}.png",
                                           "attribution": "b"}) is None
        assert check_item_basemap(self.SCHEME, {"image": "/media/a.png",
                                                "extent": [0, 0, 1, 1]}) is None
        assert check_item_basemap(self.SCHEME, {"type": "FeatureCollection",
                                                "features": []}) is None

    def test_screen_removes_the_value_and_records_why(self):
        from potato.geo.scheme import REFUSED_KEY, screen_item_basemaps
        config = {"annotation_schemes": [self.SCHEME]}
        record = {"id": "x", "map": {"tiles": "https://evil.example/{z}/{x}/{y}.png"}}
        out = screen_item_basemaps(config, record)
        assert "map" not in out and "attribution" in out[REFUSED_KEY]["map"]
        assert record["map"]                      # the stored item is untouched
        fine = {"id": "y", "map": {"image": "/media/a.png", "extent": [0, 0, 1, 1]}}
        assert screen_item_basemaps(config, fine) is fine

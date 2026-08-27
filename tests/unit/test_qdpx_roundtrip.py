"""
REFI-QDA (.qdpx) export and import.

``.qdpx`` is how a qualitative project moves between NVivo, ATLAS.ti, MAXQDA
and Quirkos. Potato mentioned it nowhere, so a researcher with a coded project
had no way to bring it in -- the codebook, memos and cross-tabs we already
have were unreachable to anyone who had started work somewhere else.

The offset convention is the whole risk. REFI-QDA 1.5 §10.2 says selections are
"defined by the first and the last character (Unicode codepoint)", which makes
``endPosition`` INCLUSIVE where Potato's ``end`` is exclusive. An off-by-one
there does not raise; it shifts every coding in the project by one character.
So these tests read the XML attribute values directly rather than only
checking that a round trip converges -- a reader and writer that are both
wrong in the same direction converge perfectly.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest

from potato.export.base import ExportContext
from potato.export.qdpx_exporter import QDPXExporter
from potato.importers.text.qdpx_importer import QDPXImporter, _infer_end_convention

TEXT = "Barack Obama visited Paris in April."
#      0123456789...
#      "Barack Obama" = [0, 12)   "Paris" = [21, 26)


def make_context(schemas=None, spans=None, labels=None, text=TEXT):
    schemas = schemas or [{
        "annotation_type": "span",
        "name": "codes",
        "description": "codes",
        "labels": [{"name": "PER"}, {"name": "LOC"}],
    }]
    annotation = {
        "instance_id": "doc1",
        "user_id": "alice",
        "labels": labels or {},
        "spans": {"codes": spans if spans is not None else [
            {"name": "PER", "start": 0, "end": 12},
            {"name": "LOC", "start": 21, "end": 26},
        ]},
    }
    return ExportContext(
        config={"annotation_task_name": "Interview study",
                "item_properties": {"text_key": "text"}},
        annotations=[annotation],
        items={"doc1": {"id": "doc1", "text": text}},
        schemas=schemas,
        output_dir="",
    )


def export(tmp_path, context, options=None):
    result = QDPXExporter().export(context, str(tmp_path), options)
    assert result.success, result.errors
    return Path(result.files_written[0]), result


def read_project(archive_path):
    with zipfile.ZipFile(archive_path) as archive:
        return ET.fromstring(archive.read("project.qde")), archive.namelist()


def local(element):
    return element.tag.rsplit("}", 1)[-1]


def find_all(root, name):
    return [e for e in root.iter() if local(e) == name]


# ------------------------------------------------------------------- layout


class TestArchiveLayout:
    def test_it_is_a_zip_holding_project_qde_and_sources(self, tmp_path):
        path, _ = export(tmp_path, make_context())
        _root, names = read_project(path)
        assert "project.qde" in names
        assert any(n.startswith("sources/") and n.endswith(".txt")
                   for n in names), (
            "REFI-QDA §8.3 requires embedded sources under sources/; without "
            "them the selections point at text the importing tool cannot find")

    def test_the_source_is_utf8(self, tmp_path):
        path, _ = export(tmp_path, make_context(text="Le café à Paris"))
        with zipfile.ZipFile(path) as archive:
            member = next(n for n in archive.namelist()
                          if n.startswith("sources/"))
            assert archive.read(member).decode("utf-8") == "Le café à Paris"

    def test_sources_are_referenced_with_the_internal_scheme(self, tmp_path):
        """
        A bare filename is read as an external path, and the importing tool
        then asks the user to locate a file that is already in the archive.
        """
        path, _ = export(tmp_path, make_context())
        root, _ = read_project(path)
        source = find_all(root, "TextSource")[0]
        assert source.get("plainTextPath", "").startswith("internal://")

    def test_two_exports_of_the_same_project_are_identical(self, tmp_path):
        """
        GUIDs are required on every element. Random ones would satisfy the
        schema while making every line of two unchanged exports differ, which
        destroys the cheapest way to see what an edit actually did.
        """
        first, _ = export(tmp_path / "a", make_context())
        second, _ = export(tmp_path / "b", make_context())
        assert read_project(first)[0] is not None
        with zipfile.ZipFile(first) as a, zipfile.ZipFile(second) as b:
            assert a.read("project.qde") == b.read("project.qde")


# ------------------------------------------------------------------ offsets


class TestEndPositionIsInclusive:
    def test_end_position_names_the_last_character(self, tmp_path):
        """
        REFI-QDA 1.5 §10.2. Potato's end is exclusive, so a span of [0, 12)
        must be written as endPosition="11".
        """
        path, _ = export(tmp_path, make_context())
        root, _ = read_project(path)
        selections = {s.get("name"): s for s in find_all(root, "PlainTextSelection")}
        per = selections["Barack Obama"]
        assert per.get("startPosition") == "0"
        assert per.get("endPosition") == "11", (
            "endPosition must be the index of the LAST character. Writing 12 "
            "here makes every ATLAS.ti/NVivo import one character long.")

    def test_import_puts_it_back(self, tmp_path):
        path, _ = export(tmp_path, make_context())
        result = QDPXImporter().parse_path(path)
        document = result.documents[0]
        assert [(s.label, document.text[s.start:s.end]) for s in document.spans] == [
            ("PER", "Barack Obama"), ("LOC", "Paris")]

    def test_the_round_trip_converges_exactly(self, tmp_path):
        path, _ = export(tmp_path, make_context())
        document = QDPXImporter().parse_path(path).documents[0]
        assert document.text == TEXT
        assert [(s.start, s.end, s.label) for s in document.spans] == [
            (0, 12, "PER"), (21, 26, "LOC")]

    def test_a_one_character_span_survives(self, tmp_path):
        """The degenerate case an inclusive/exclusive mix-up turns into zero."""
        path, _ = export(tmp_path, make_context(
            spans=[{"name": "PER", "start": 0, "end": 1}]))
        root, _ = read_project(path)
        assert find_all(root, "PlainTextSelection")[0].get("endPosition") == "0"
        document = QDPXImporter().parse_path(path).documents[0]
        assert (document.spans[0].start, document.spans[0].end) == (0, 1)

    def test_non_bmp_characters_do_not_shift_offsets(self, tmp_path):
        """
        The spec counts Unicode CODE POINTS, which is what Python indexes.
        A tool counting UTF-16 code units would put this span two characters
        late, because each emoji is a surrogate pair there.
        """
        text = "\U0001F600\U0001F600 Paris"
        start, end = text.index("Paris"), text.index("Paris") + 5
        path, _ = export(tmp_path, make_context(
            spans=[{"name": "LOC", "start": start, "end": end}], text=text))
        document = QDPXImporter().parse_path(path).documents[0]
        assert document.text[document.spans[0].start:document.spans[0].end] == "Paris"


class TestConventionInference:
    def test_a_spec_conformant_file_reads_as_inclusive(self):
        assert _infer_end_convention([(0, 11, "Barack Obama", TEXT)]) == "inclusive"

    def test_an_exclusive_file_is_detected(self):
        assert _infer_end_convention([(0, 12, "Barack Obama", TEXT)]) == "exclusive"

    def test_no_evidence_is_reported_as_unknown(self):
        assert _infer_end_convention([(0, 11, "", TEXT)]) == "unknown"

    def test_an_exclusive_file_imports_correctly_and_says_so(self, tmp_path):
        """
        Exporters have not all read §10.2 the same way. A file written with an
        exclusive end loses its last character under the spec's reading, so
        the reading is measured against the text rather than assumed.
        """
        path = tmp_path / "exclusive.qde"
        path.write_text(f"""<?xml version="1.0" encoding="utf-8"?>
<Project xmlns="urn:QDA-XML:project:1.0" name="p">
  <CodeBook><Codes>
    <Code guid="g-per" name="PER" isCodable="true"/>
  </Codes></CodeBook>
  <Sources>
    <TextSource guid="s1" name="doc1">
      <PlainTextContent>{TEXT}</PlainTextContent>
      <PlainTextSelection guid="sel1" name="Barack Obama"
                          startPosition="0" endPosition="12">
        <Coding guid="c1"><CodeRef targetGUID="g-per"/></Coding>
      </PlainTextSelection>
    </TextSource>
  </Sources>
</Project>
""", encoding="utf-8")
        result = QDPXImporter().parse_path(path)
        span = result.documents[0].spans[0]
        assert result.documents[0].text[span.start:span.end] == "Barack Obama"
        assert any("EXCLUSIVELY" in w for w in result.warnings)
        assert result.stats["end_position"] == "exclusive"

    def test_the_override_wins_over_inference(self, tmp_path):
        path, _ = export(tmp_path, make_context())
        result = QDPXImporter().parse_path(path, {"qdpx_end_position": "exclusive"})
        assert result.stats["end_position"] == "exclusive"
        # Read one character short, which is the point of forcing it.
        span = result.documents[0].spans[0]
        assert result.documents[0].text[span.start:span.end] == "Barack Obam"


# ----------------------------------------------------------------- codebook


NESTED = [{
    "annotation_type": "hierarchical_multiselect",
    "name": "codes",
    "description": "codes",
    "labels": [{
        "name": "Emotion",
        "children": [{
            "name": "Negative",
            "children": [{"name": "Anger", "description": "explicit anger"}],
        }],
    }],
}]


class TestCodebook:
    def test_codes_nest(self, tmp_path):
        path, _ = export(tmp_path, make_context(schemas=NESTED, spans=[]))
        root, _ = read_project(path)
        emotion = next(c for c in find_all(root, "Code")
                       if c.get("name") == "Emotion")
        negative = next(c for c in emotion if local(c) == "Code")
        assert negative.get("name") == "Negative"
        anger = next(c for c in negative if local(c) == "Code")
        assert anger.get("name") == "Anger"

    def test_is_codable_is_always_set(self, tmp_path):
        """Required by the schema; a missing one fails validation outright."""
        path, _ = export(tmp_path, make_context(schemas=NESTED, spans=[]))
        root, _ = read_project(path)
        codes = find_all(root, "Code")
        assert codes and all(c.get("isCodable") == "true" for c in codes)

    def test_deep_nesting_warns_about_atlas_ti(self, tmp_path):
        """
        ATLAS.ti supports ONE level of subcode. A three-deep codebook exported
        faithfully is a codebook it mangles, with nothing telling the
        researcher that happened.
        """
        _path, result = export(tmp_path, make_context(schemas=NESTED, spans=[]))
        assert any("ATLAS.ti" in w for w in result.warnings)

    def test_flatten_subcodes_produces_a_flat_codebook(self, tmp_path):
        path, result = export(tmp_path, make_context(schemas=NESTED, spans=[]),
                              {"flatten_subcodes": True})
        root, _ = read_project(path)
        codes = find_all(root, "Code")
        assert all(not [c for c in code if local(c) == "Code"] for code in codes), (
            "flatten_subcodes must leave no nested Code elements")
        assert "Emotion > Negative > Anger" in {c.get("name") for c in codes}
        assert not any("ATLAS.ti" in w for w in result.warnings)
        assert result.stats["flattened"] is True

    def test_descriptions_and_colours_survive(self, tmp_path):
        schemas = [{
            "annotation_type": "span", "name": "codes", "description": "d",
            "labels": [{"name": "PER", "description": "a person",
                        "color": "#FF0000"}],
        }]
        path, _ = export(tmp_path, make_context(schemas=schemas, spans=[]))
        root, _ = read_project(path)
        code = find_all(root, "Code")[0]
        assert code.get("color") == "#FF0000"
        assert find_all(code, "Description")[0].text == "a person"

    def test_the_codebook_survives_the_round_trip(self, tmp_path):
        path, _ = export(tmp_path, make_context(schemas=NESTED, spans=[]))
        result = QDPXImporter().parse_path(path)
        by_name = {c["name"]: c for c in result.labels}
        assert by_name["Anger"]["parent"] == "Negative"
        assert by_name["Negative"]["parent"] == "Emotion"
        assert by_name["Anger"]["description"] == "explicit anger"


# -------------------------------------------------------------------- misc


class TestAnnotatorsAndDocumentCodes:
    def test_annotators_become_users(self, tmp_path):
        path, _ = export(tmp_path, make_context())
        root, _ = read_project(path)
        assert [u.get("name") for u in find_all(root, "User")] == ["alice"]

    def test_a_selection_records_who_coded_it(self, tmp_path):
        path, _ = export(tmp_path, make_context())
        root, _ = read_project(path)
        user_guid = find_all(root, "User")[0].get("guid")
        selection = find_all(root, "PlainTextSelection")[0]
        assert selection.get("creatingUser") == user_guid

    def test_the_importer_reads_the_annotator_back(self, tmp_path):
        path, _ = export(tmp_path, make_context())
        result = QDPXImporter().parse_path(path)
        assert result.documents[0].spans[0].annotator == "alice"
        assert result.annotators == ["alice"]

    def test_document_level_labels_code_the_whole_source(self, tmp_path):
        schemas = [
            {"annotation_type": "span", "name": "codes", "description": "d",
             "labels": [{"name": "PER"}]},
            {"annotation_type": "radio", "name": "tone", "description": "d",
             "labels": [{"name": "positive"}, {"name": "negative"}]},
        ]
        context = make_context(schemas=schemas, spans=[],
                               labels={"tone": {"negative": "negative"}})
        path, _ = export(tmp_path, context)
        root, _ = read_project(path)
        source = find_all(root, "TextSource")[0]
        codings = [c for c in source if local(c) == "Coding"]
        assert len(codings) == 1, (
            "A code on the whole document is a Coding on the TextSource, not "
            "on a selection")
        result = QDPXImporter().parse_path(path)
        assert result.documents[0].extra["document_codes"] == ["negative"]


class TestRefusesWhatItCannotDo:
    def test_a_config_with_no_codeable_scheme_is_refused_up_front(self):
        context = make_context(schemas=[{"annotation_type": "textbox",
                                         "name": "notes", "description": "d"}])
        can, reason = QDPXExporter().can_export(context)
        assert not can and "codeable" in reason

    def test_a_span_whose_label_is_not_in_the_codebook_is_reported(self, tmp_path):
        _path, result = export(tmp_path, make_context(
            spans=[{"name": "GHOST", "start": 0, "end": 6}]))
        assert any("GHOST" in w for w in result.warnings)

    def test_an_item_with_annotations_but_no_text_is_reported(self, tmp_path):
        context = make_context()
        context.items = {"doc1": {"id": "doc1"}}
        _path, result = export(tmp_path, context)
        assert any("no text" in w for w in result.warnings)

    def test_an_out_of_range_selection_is_dropped_on_import(self, tmp_path):
        path = tmp_path / "bad.qde"
        path.write_text("""<?xml version="1.0" encoding="utf-8"?>
<Project xmlns="urn:QDA-XML:project:1.0" name="p">
  <CodeBook><Codes><Code guid="g" name="X" isCodable="true"/></Codes></CodeBook>
  <Sources>
    <TextSource guid="s1" name="doc1">
      <PlainTextContent>short</PlainTextContent>
      <PlainTextSelection guid="sel" startPosition="0" endPosition="900">
        <Coding guid="c"><CodeRef targetGUID="g"/></Coding>
      </PlainTextSelection>
    </TextSource>
  </Sources>
</Project>
""", encoding="utf-8")
        result = QDPXImporter().parse_path(path)
        assert result.documents[0].spans == []
        assert any("does not fit" in w for w in result.warnings)

    def test_a_non_project_xml_is_rejected_with_a_useful_message(self, tmp_path):
        path = tmp_path / "wrong.qde"
        path.write_text('<?xml version="1.0"?><CodeBook/>', encoding="utf-8")
        with pytest.raises(ValueError, match="CodeBook"):
            QDPXImporter().parse_path(path)


class TestDetection:
    def test_a_qdpx_archive_is_detected(self, tmp_path):
        from potato.importers.text.registry import text_import_registry

        path, _ = export(tmp_path, make_context())
        assert text_import_registry.detect_path(path) == "qdpx"

    def test_a_plain_zip_is_not(self, tmp_path):
        from potato.importers.text.registry import text_import_registry

        path = tmp_path / "photos.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("a.txt", "hello")
        assert text_import_registry.detect_path(path) is None

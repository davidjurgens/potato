"""Every key a stored span carries reaches `spans.parquet`, or is named.

`_build_span_rows` wrote a fixed seven-key row against a span that carries up
to twelve. `target_field` was the one that broke the file: it says which
display field the drag was in, it varies WITHIN a scheme, and nothing else
recovers it — the span id is schema+label+offsets, so the same words marked in
two fields produced byte-identical rows.

This file has two kinds of test and the second is the point.

The first kind pins the columns that were missing, which is what any regression
test does. The second asks a question no fixed list of assertions can: does
`SpanAnnotation` carry a key the row builder does not place? That is the check
that survives the next key being added — and the next one is likely to be span
provenance, since image shapes now carry `source` and `confidence`.

The reason this went unnoticed through an earlier pass over the same builder is
worth stating: an empty column looks like a bug and gets fixed, and an absent
column looks like a decision and does not.
"""

import inspect
import json

import pytest

pytest.importorskip("pyarrow")

from potato.export.base import ExportContext  # noqa: E402
from potato.export.parquet_exporter import ParquetExporter  # noqa: E402
from potato.item_state_management import SpanAnnotation  # noqa: E402


def _annotation(spans):
    return {
        "instance_id": "m1",
        "user_id": "spanner",
        "labels": {},
        "spans": {"evidence": spans},
    }


def _rows(spans, warnings=None):
    return ParquetExporter()._build_span_rows(
        [_annotation(spans)], None, warnings)


class TestTheKeyThatVariesWithinAScheme:
    def test_two_fields_do_not_produce_identical_rows(self):
        """The falsifying case, stated in one assertion.

        A scheme pinned to one display field still records in the others, so
        one scheme's spans land in several fields. The same words marked in two
        of them differ in exactly one attribute on disk, and that attribute was
        not exported.
        """
        span = {"schema": "evidence", "name": "Evidence", "title": "Evidence",
                "start": 4, "end": 20, "id": "evidence_Evidence_4_20"}
        rows = _rows([
            {**span, "target_field": "headline"},
            {**span, "target_field": "body"},
        ])

        assert rows[0] != rows[1], (
            "two spans in different display fields exported as identical rows; "
            "the field the drag was in is not recoverable from anything else "
            "in the file")
        assert {row["target_field"] for row in rows} == {"headline", "body"}

    def test_a_span_with_no_target_field_gets_an_empty_one(self):
        # Absent is normal: a single-field page records no target. It must be a
        # column with "" rather than a missing key, or pyarrow infers the
        # schema from row one and drops it for the whole file.
        rows = _rows([{"schema": "evidence", "name": "Evidence",
                       "start": 0, "end": 3}])
        assert rows[0]["target_field"] == ""


class TestTheRestOfTheStoredSpan:
    def test_a_discontinuous_span_keeps_its_other_parts(self):
        # Exported as its first range alone, the annotation is not merely
        # missing a column: it is a different annotation.
        parts = [{"start": 30, "end": 34}]
        rows = _rows([{"schema": "evidence", "name": "Evidence",
                       "start": 0, "end": 3, "additional_parts": parts}])
        assert json.loads(rows[0]["additional_parts"]) == parts

    def test_a_pdf_span_keeps_its_page_and_box(self):
        coords = {"format": "pdf", "page": 1, "bbox": [1.0, 2.0, 3.0, 4.0]}
        rows = _rows([{"schema": "evidence", "name": "Evidence",
                       "start": 0, "end": 3, "format_coords": coords}])
        assert json.loads(rows[0]["format_coords"]) == coords

    def test_an_entity_link_survives(self):
        rows = _rows([{"schema": "evidence", "name": "Evidence",
                       "start": 0, "end": 3, "kb_id": "Q42",
                       "kb_source": "wikidata", "kb_label": "Douglas Adams"}])
        assert rows[0]["kb_id"] == "Q42"
        assert rows[0]["kb_source"] == "wikidata"
        assert rows[0]["kb_label"] == "Douglas Adams"


class TestNothingIsDroppedSilently:
    """The guard that survives the next key.

    A fixed list of assertions can only test the keys someone thought of. This
    asks the stored shape what it carries.
    """

    def _every_key_a_span_can_store(self):
        """Every key `SpanAnnotation.to_dict()` can emit.

        SCOPE: this is the key set of a span serialized by the CURRENT
        `SpanAnnotation`. `_build_span_rows` consumes span dicts read off disk,
        which is a superset — a state file written by an older Potato can carry
        a key this class no longer emits. That divergence is what the runtime
        warning in the builder is for; this check covers the forward direction
        only, which is where a newly added key would be lost.

        Built by constructing one with every optional argument set to a truthy
        value, because `to_dict` omits falsy optionals — a span built with
        defaults would report a shape half its real size and this test would
        pass on nothing.
        """
        signature = inspect.signature(SpanAnnotation.__init__)
        kwargs = {}
        for name, param in signature.parameters.items():
            if name == "self":
                continue
            if name in ("start", "end"):
                kwargs[name] = 1
            elif name == "format_coords":
                kwargs[name] = {"format": "pdf"}
            elif name == "additional_parts":
                kwargs[name] = [{"start": 2, "end": 3}]
            else:
                kwargs[name] = f"x-{name}"
        keys = set(SpanAnnotation(**kwargs).to_dict())
        assert len(keys) >= 8, (
            f"only {len(keys)} keys came back from a fully-populated span; the "
            f"construction above has stopped populating it and this test is "
            f"measuring nothing")
        return keys

    def test_the_row_builder_places_every_stored_key(self):
        stored = self._every_key_a_span_can_store()
        span = {key: 1 for key in stored}
        span.update({"start": 0, "end": 3, "name": "Evidence"})

        row = _rows([span])[0]
        exporter = ParquetExporter()
        unplaced = {key for key in stored
                    if not exporter._span_key_is_placed(key, row)}

        assert not unplaced, (
            f"a stored span can carry {sorted(unplaced)} and spans.parquet has "
            f"no column for them. Add a column, or add the key to "
            f"ParquetExporter.SPAN_KEYS_NOT_COLUMNS with a reason — an absent "
            f"column reads as a design decision, which is how target_field "
            f"survived a previous pass over this builder.")

    def test_an_unplaced_key_is_reported_at_export_time(self):
        # The runtime half. A key that arrives in real data without a column
        # must say so rather than vanish.
        warnings = []
        _rows([{"schema": "evidence", "name": "Evidence", "start": 0, "end": 3,
                "some_future_key": "value"}], warnings)
        assert any("some_future_key" in w for w in warnings), warnings

    def test_an_ordinary_span_produces_no_warning(self):
        # A warning on every export teaches nobody anything.
        warnings = []
        _rows([{"schema": "evidence", "name": "Evidence", "title": "Evidence",
                "start": 0, "end": 3, "id": "evidence_Evidence_0_3",
                "target_field": "body"}], warnings)
        assert warnings == []


class TestNoExemptionOutlivesItsSubject:
    """An entry with no subject is not inert; it is a standing permission.

    `SPAN_KEYS_NOT_COLUMNS` held `label` and `value` for an hour after this
    file was written. Neither is produced by `SpanAnnotation.to_dict()` and
    neither was actually dropped — both are read as fallbacks and land in real
    columns. So the entries did no work, and on the day something started
    writing a `value` key on a span it would have been silently exempted from
    the completeness check above and never reached parquet. That is the same
    shape as an exemption for a typo'd config key that skips validation of the
    block containing the typo it was written for: dormant, and it activates on
    exactly the case it names.
    """

    def test_every_deliberate_drop_names_a_key_a_span_can_carry(self):
        stored = TestNothingIsDroppedSilently()._every_key_a_span_can_store()
        # An empty drop list makes `orphans` empty and this test pass having
        # checked nothing -- the same well-formed answer to a smaller question
        # that the orphan entries themselves were.
        assert ParquetExporter.SPAN_KEYS_NOT_COLUMNS, (
            "the drop list is empty, so this test cannot fail. Delete it, or "
            "restore the entry it was written for")
        orphans = sorted(ParquetExporter.SPAN_KEYS_NOT_COLUMNS - stored)
        assert not orphans, (
            f"SPAN_KEYS_NOT_COLUMNS exempts {orphans}, which a stored span "
            f"cannot carry. Remove them: an exemption with no subject is a "
            f"standing permission that activates the day one appears.")

    @pytest.mark.parametrize("stored_key,column,expected", [
        ("id", "span_id", "s-1"),
        ("name", "label", "Evidence"),
        ("label", "label", "Evidence"),
        ("title", "title", "Evidence"),
        ("value", "text", "the words"),
        ("text", "text", "the words"),
    ])
    def test_every_alias_actually_reaches_its_column(self, stored_key, column,
                                                     expected):
        """Driven, not asserted from the table.

        `SPAN_KEY_COLUMNS` tells the completeness check that a key reaches the
        file under another name. If the fallback read that made that true is
        ever removed, the table would keep vouching for it and the key would
        vanish — the exemption outliving its subject again, one level along.
        """
        span = {"schema": "evidence", "start": 0, "end": 3,
                stored_key: expected}
        assert _rows([span])[0][column] == expected

    def test_the_alias_table_covers_only_keys_the_builder_reads(self):
        # The other direction: an alias for a key nothing reads would vouch for
        # a column that is never populated.
        assert len(ParquetExporter.SPAN_KEY_COLUMNS) >= 5, (
            f"only {len(ParquetExporter.SPAN_KEY_COLUMNS)} aliases; an empty "
            f"or gutted table makes this loop body never run and the test "
            f"pass vacuously")
        for stored_key, column in ParquetExporter.SPAN_KEY_COLUMNS.items():
            span = {"schema": "evidence", "start": 0, "end": 3,
                    stored_key: "probe-value"}
            assert _rows([span])[0][column] == "probe-value", (
                f"SPAN_KEY_COLUMNS says {stored_key!r} reaches the {column!r} "
                f"column, and it does not")


class TestTheFileItself:
    def test_the_written_parquet_carries_the_column(self, tmp_path):
        """Driven through the real exporter to the real file.

        The rows above are what the builder returns; this is what a reader
        opens. `pa.Table.from_pylist` infers its schema from the first row
        alone, so a column present in every row dict can still be absent from
        the file.
        """
        pa = pytest.importorskip("pyarrow")
        pq = pytest.importorskip("pyarrow.parquet")

        span = {"schema": "evidence", "name": "Evidence", "title": "Evidence",
                "start": 4, "end": 20, "id": "evidence_Evidence_4_20"}
        context = ExportContext(
            config={},
            annotations=[_annotation([
                {**span, "target_field": "headline"},
                {**span, "target_field": "body"},
            ])],
            items={"m1": {"id": "m1", "headline": "the price I expected",
                          "body": "the price I expected"}},
            schemas=[{"annotation_type": "span", "name": "evidence",
                      "labels": ["Evidence"]}],
            output_dir=str(tmp_path),
        )
        result = ParquetExporter().export(context, str(tmp_path))
        assert result.success, result.errors

        table = pq.read_table(str(tmp_path / "spans.parquet"))
        assert "target_field" in table.column_names
        assert set(table.column("target_field").to_pylist()) == {"headline", "body"}

        rows = table.to_pylist()
        assert rows[0] != rows[1]

"""
Getting data in: is the item the annotator sees the row the researcher wrote?

Every test here feeds a real file through the real loader: ``data_files``,
``data_sources`` (with and without partial loading), the live database
poller, the watched directory, and the brat, CoNLL, ConvoKit and transcript
importers. The earlier tests checked each piece on hand-built inputs: clean
ASCII, LF line endings, ids without leading zeros, no quotes in TSV, batches
too small to fill, and no id used twice.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tests.helpers.test_utils import create_test_directory


def _fresh_dir(name):
    path = create_test_directory(name)
    shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path)
    return path


def _write(directory, name, content):
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(content)
    return path


@pytest.fixture
def boot():
    """Load a config through flask_server.load_instance_data, as boot does."""
    import potato.flask_server as fs
    from potato.data_sources import clear_data_source_manager
    from potato.item_state_management import (
        clear_item_state_manager, get_item_state_manager, init_item_state_manager)
    from potato.user_state_management import clear_user_state_manager, init_user_state_manager

    saved = dict(fs.config)

    def load(extra, out_dir):
        clear_data_source_manager()
        clear_item_state_manager()
        clear_user_state_manager()
        cfg = {"item_properties": {"id_key": "id", "text_key": "text"},
               "task_dir": out_dir, "annotation_task_name": "t",
               "annotation_schemes": [], "output_annotation_dir": out_dir,
               "data_cache": {"enabled": False}}
        cfg.update(extra)
        fs.config.clear()
        fs.config.update(cfg)
        init_item_state_manager(cfg)
        init_user_state_manager(cfg)
        fs.load_instance_data(cfg)
        ism = get_item_state_manager()
        return {i: ism.get_item(i).get_data() for i in ism.get_instance_ids()}

    yield load
    clear_data_source_manager()
    clear_item_state_manager()
    clear_user_state_manager()
    fs.config.clear()
    fs.config.update(saved)


# ---------------------------------------------------------------------------
# data_files: CSV and TSV
# ---------------------------------------------------------------------------

class TestDelimitedFilesKeepCellsVerbatim:
    def test_csv_ids_and_text_are_not_reinterpreted(self, boot):
        d = _fresh_dir("tg2_csv_verbatim")
        path = _write(d, "items.csv", "id,text,ctx\n007,NA,\n008,None,null\n009,1.50,x\n")
        items = boot({"data_files": [path]}, d)
        assert list(items) == ["007", "008", "009"]
        assert [items[i]["text"] for i in items] == ["NA", "None", "1.50"]
        assert items["008"]["ctx"] == "null"
        json.dumps(items)  # no float NaN anywhere

    def test_a_blank_id_is_refused_rather_than_turning_ids_into_floats(self, boot):
        d = _fresh_dir("tg2_csv_blank_id")
        path = _write(d, "items.csv", "id,text\n1,a\n2,b\n,c\n")
        with pytest.raises(ValueError, match="Empty ID"):
            boot({"data_files": [path]}, d)

    def test_a_quote_in_a_tsv_cell_is_text(self, boot):
        d = _fresh_dir("tg2_tsv_quotes")
        path = _write(d, "items.tsv",
                      'id\ttext\n1\t"quoted start\n2\tsecond\n3\t"third" ok\n')
        items = boot({"data_files": [path]}, d)
        assert {i: v["text"] for i, v in items.items()} == {
            "1": '"quoted start', "2": "second", "3": '"third" ok'}

    def test_a_quoted_csv_cell_keeps_its_comma_and_newline(self, boot):
        d = _fresh_dir("tg2_csv_quoted")
        path = _write(d, "items.csv", 'id,text\n1,"a, b\nc"\n2,ok\n')
        items = boot({"data_files": [path]}, d)
        assert items["1"]["text"] == "a, b\nc"

    def test_a_byte_order_mark_is_ignored_in_jsonl(self, boot):
        d = _fresh_dir("tg2_bom_jsonl")
        path = _write(d, "items.jsonl", '﻿{"id":"r1","text":"first"}\n')
        assert list(boot({"data_files": [path]}, d)) == ["r1"]


# ---------------------------------------------------------------------------
# data_sources
# ---------------------------------------------------------------------------

class TestDataSourcesMatchDataFiles:
    def test_one_csv_loads_the_same_through_either_key(self, boot):
        d = _fresh_dir("tg2_ds_same_csv")
        path = _write(d, "items.csv", "id,text\n007,NA\n")
        via_files = boot({"data_files": [path]}, d)
        via_sources = boot({"data_sources": [{"type": "file", "path": path}]}, d)
        assert {i: v["text"] for i, v in via_sources.items()} == \
            {i: v["text"] for i, v in via_files.items()} == {"007": "NA"}

    def test_a_byte_order_mark_does_not_drop_the_first_row(self, boot):
        d = _fresh_dir("tg2_ds_bom")
        path = _write(d, "items.jsonl",
                      '﻿{"id":"r1","text":"first"}\n{"id":"r2","text":"second"}\n')
        assert list(boot({"data_sources": [{"type": "file", "path": path}]}, d)) == ["r1", "r2"]

    def test_a_malformed_line_stops_the_boot(self, boot):
        d = _fresh_dir("tg2_ds_bad_line")
        path = _write(d, "items.jsonl",
                      '{"id":"a","text":"x"}\n{"id":"b","text":"y",}\n{"id":"c","text":"z"}\n')
        with pytest.raises(ValueError, match="line 2"):
            boot({"data_sources": [{"type": "file", "path": path}]}, d)

    def test_an_id_in_two_sources_stops_the_boot(self, boot):
        d = _fresh_dir("tg2_ds_dup")
        one = _write(d, "one.jsonl", '{"id":1,"text":"from file one"}\n')
        two = _write(d, "two.jsonl", '{"id":"1","text":"from file two"}\n')
        with pytest.raises(ValueError, match="Duplicate instance ID '1'"):
            boot({"data_sources": [{"type": "file", "path": one},
                                   {"type": "file", "path": two}]}, d)


class TestPartialLoading:
    PARTIAL = {"partial_loading": {"enabled": True, "initial_count": 3, "batch_size": 3}}

    def _source(self, d, rows):
        path = _write(d, "items.jsonl", "\n".join(json.dumps(r) for r in rows) + "\n")
        return {"data_sources": [{"type": "file", "path": path, "id": "src"}], **self.PARTIAL}

    def test_a_row_without_an_id_does_not_end_the_source(self, boot):
        from potato.data_sources import get_data_source_manager
        d = _fresh_dir("tg2_partial_noid")
        rows = [{"id": f"r{i}", "text": f"t{i}"} for i in range(10)]
        rows[4] = {"text": "no id"}
        boot(self._source(d, rows), d)
        manager = get_data_source_manager()
        manager.load_more("src")  # rows 3-5; row 4 has no id
        manager.load_more("src")  # rows 6-8
        manager.load_more("src")  # row 9
        from potato.item_state_management import get_item_state_manager
        ids = set(get_item_state_manager().get_instance_ids())
        assert ids == {f"r{i}" for i in range(10)} - {"r4"}

    def test_a_restart_reloads_every_row_an_earlier_run_loaded(self, boot):
        from potato.data_sources import get_data_source_manager
        d = _fresh_dir("tg2_partial_restart")
        rows = [{"id": f"r{i}", "text": f"t{i}"} for i in range(10)]
        cfg = self._source(d, rows)
        boot(cfg, d)
        get_data_source_manager().load_more("src")
        assert set(boot(cfg, d)) == {f"r{i}" for i in range(6)}
        assert set(boot(cfg, d)) == {f"r{i}" for i in range(6)}


# ---------------------------------------------------------------------------
# Live database ingestion
# ---------------------------------------------------------------------------

def _live_worker(d, rows, **live):
    from sqlalchemy import create_engine, text
    from potato.data_sources.base import SourceConfig
    from potato.data_sources.live_ingestion import LiveCursorStore, LiveIngestionWorker
    from potato.data_sources.sources.database_source import DatabaseSource

    db = os.path.join(d, "live.db")
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as c:
        c.execute(text("CREATE TABLE instances "
                       "(id INTEGER PRIMARY KEY, seq INTEGER, text TEXT, created_at TEXT)"))
        for row in rows:
            c.execute(text("INSERT INTO instances VALUES (:id, :seq, :t, :c)"), row)
    engine.dispose()
    block = {"enabled": True, "poll_interval_seconds": 1, "cursor_column": "created_at"}
    block.update(live)
    source = DatabaseSource(SourceConfig.from_dict({
        "type": "database", "id": "live", "connection_string": f"sqlite:///{db}",
        "query": "SELECT id, seq, text, created_at FROM instances",
        "live_ingestion": block}))
    pool = {}

    def ingest(item):
        key = str(item["id"])
        if key in pool:
            return "duplicate"
        pool[key] = item
        return "added"

    worker = LiveIngestionWorker(source, source.live_config,
                                 LiveCursorStore(os.path.join(d, "state")), ingest)
    return worker, pool


class TestLiveIngestion:
    BASE = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)

    def test_an_overlap_window_fuller_than_a_batch_still_finishes(self):
        d = _fresh_dir("tg2_live_overlap")
        rows = [{"id": i, "seq": i, "t": f"row {i}",
                 "c": (self.BASE + timedelta(seconds=i)).isoformat()} for i in range(1, 21)]
        worker, pool = _live_worker(d, rows, batch_size=5, overlap_seconds=10)
        calls = [0]
        fetch = worker._fetch_and_ingest

        def counted(*a, **k):
            calls[0] += 1
            assert calls[0] < 50, "prime() is re-reading the same batch"
            return fetch(*a, **k)
        worker._fetch_and_ingest = counted
        assert worker.prime() == 20
        assert len(pool) == 20

    def test_paging_resumes_on_the_tiebreaker_column(self):
        # Every row shares a timestamp, and seq runs opposite to id. Resuming
        # with the id in place of seq skips or repeats rows.
        d = _fresh_dir("tg2_live_tiebreak")
        stamp = self.BASE.isoformat()
        rows = [{"id": i, "seq": 13 - i, "t": f"row {i}", "c": stamp} for i in range(1, 13)]
        worker, pool = _live_worker(d, rows, batch_size=4, tiebreaker_column="seq")
        assert worker.prime() == 12
        assert sorted(pool, key=int) == [str(i) for i in range(1, 13)]


# ---------------------------------------------------------------------------
# Watched directory
# ---------------------------------------------------------------------------

@pytest.fixture
def watched():
    from potato.item_state_management import (
        clear_item_state_manager, get_item_state_manager, init_item_state_manager)
    from potato.directory_watcher import DirectoryWatcher

    def make(d):
        cfg = {"item_properties": {"id_key": "id", "text_key": "text"},
               "data_directory": d, "annotation_schemes": []}
        clear_item_state_manager()
        init_item_state_manager(cfg)
        ism = get_item_state_manager()
        return DirectoryWatcher(cfg, ism), ism
    yield make
    clear_item_state_manager()


class TestWatchedDirectory:
    def test_a_repeated_id_keeps_the_first_row(self, watched):
        d = _fresh_dir("tg2_watch_dup")
        _write(d, "a.jsonl", '{"id":1,"text":"batch one"}\n')
        _write(d, "b.jsonl", '{"id":"1","text":"batch two"}\n'
                             '{"id":"x","text":"first x"}\n{"id":"x","text":"second x"}\n')
        watcher, ism = watched(d)
        watcher.load_directory()
        assert ism.get_item("1").get_data()["text"] == "batch one"
        assert ism.get_item("x").get_data()["text"] == "first x"

    def test_csv_cells_are_verbatim(self, watched):
        d = _fresh_dir("tg2_watch_csv")
        _write(d, "c.csv", "id,text\n0042,NA\n")
        watcher, ism = watched(d)
        watcher.load_directory()
        assert ism.get_item("0042").get_data()["text"] == "NA"

    def test_an_annotated_items_text_is_not_replaced(self, watched):
        d = _fresh_dir("tg2_watch_annotated")
        path = _write(d, "a.jsonl", '{"id":"i1","text":"Paris is nice"}\n')
        watcher, ism = watched(d)
        watcher.load_directory()
        ism.instance_annotators["i1"].add("u1")
        _write(d, "a.jsonl", '{"id":"i1","text":"Completely different"}\n')
        os.utime(path, (1, 1))
        watcher.force_rescan()
        assert ism.get_item("i1").get_data()["text"] == "Paris is nice"


# ---------------------------------------------------------------------------
# Importers
# ---------------------------------------------------------------------------

class TestBrat:
    def test_offsets_index_a_crlf_file_as_written(self):
        from potato.importers.text.brat_importer import BratImporter
        d = Path(_fresh_dir("tg2_brat_crlf"))
        text = "Line one.\r\nBarack Obama visited Paris.\r\n"
        start = text.index("Paris")
        (d / "doc.txt").write_bytes(text.encode())
        (d / "doc.ann").write_bytes(f"T1\tLOC {start} {start + 5}\tParis\n".encode())
        result = BratImporter().parse_path(d)
        doc = result.documents[0]
        span = doc.spans[0]
        assert doc.text[span.start:span.end] == "Paris"
        assert "\r" not in doc.text
        assert result.warnings == []

    def test_same_named_files_in_two_folders_get_two_ids(self):
        from potato.importers.text.brat_importer import BratImporter
        d = Path(_fresh_dir("tg2_brat_ids"))
        for split in ("train", "dev"):
            (d / split).mkdir()
            (d / split / "doc1.txt").write_text(f"{split} text\n")
            (d / split / "doc1.ann").write_text("T1\tX 0 3\t" + f"{split}"[:3] + "\n")
        ids = [doc.instance_id for doc in BratImporter().parse_path(d).documents]
        assert len(set(ids)) == 2


class TestCoNLL:
    def test_a_hashtag_token_is_a_token(self):
        from potato.importers.text.conll_importer import CoNLLImporter
        d = Path(_fresh_dir("tg2_conll_hash"))
        path = d / "wnut.conll"
        path.write_text("Watching\tO\n#WorldCup\tB-event\nin\tO\nParis\tB-location\n\n")
        doc = CoNLLImporter().parse_path(path).documents[0]
        assert doc.text == "Watching #WorldCup in Paris"
        assert [(s.label, s.text) for s in doc.spans] == [
            ("event", "#WorldCup"), ("location", "Paris")]

    def test_comments_are_still_comments(self):
        from potato.importers.text.conll_importer import CoNLLImporter
        d = Path(_fresh_dir("tg2_conll_comment"))
        path = d / "c.conll"
        path.write_text("# sent_id = s1\n# text = Hi Bob\nHi\tO\nBob\tB-PER\n\n")
        doc = CoNLLImporter().parse_path(path).documents[0]
        assert doc.instance_id == "s1"
        assert [(s.label, s.text) for s in doc.spans] == [("PER", "Bob")]

    def test_an_iob1_entity_does_not_cross_a_sentence_boundary(self):
        from potato.importers.text.conll_importer import CoNLLImporter
        d = Path(_fresh_dir("tg2_conll_iob1"))
        path = d / "iob1.conll"
        path.write_text("-DOCSTART- -X- O O\n\nHe NNP I-NP O\nflew VBD I-VP O\n"
                        "to TO I-PP O\nParis NNP I-NP I-LOC\n\n"
                        "London NNP I-NP I-LOC\nwas VBD I-VP O\n\n")
        doc = CoNLLImporter().parse_path(path).documents[0]
        assert [s.text for s in doc.spans] == ["Paris", "London"]


def test_convokit_keeps_late_turns_of_admitted_conversations():
    from potato.convokit.reader import read_corpus
    d = _fresh_dir("tg2_convokit")
    rows = [{"id": "a1", "conversation_id": "A", "speaker": "s", "text": "A first", "reply_to": None},
            {"id": "b1", "conversation_id": "B", "speaker": "s", "text": "B first", "reply_to": None},
            {"id": "a2", "conversation_id": "A", "speaker": "s", "text": "A reply", "reply_to": "a1"}]
    _write(d, "utterances.jsonl", "\n".join(json.dumps(r) for r in rows) + "\n")
    for name in ("speakers.json", "conversations.json", "corpus.json", "index.json"):
        _write(d, name, "{}")
    corpus = read_corpus(d, max_conversations=1)
    assert {k: v.utterance_ids for k, v in corpus.conversations.items()} == {"A": ["a1", "a2"]}


def test_transcripts_with_one_name_in_two_folders_get_two_ids():
    from potato.transcript_cli import main
    d = Path(_fresh_dir("tg2_transcripts"))
    srt = "1\n00:00:00,000 --> 00:00:02,000\nAlice: Hello.\n"
    (d / "a").mkdir()
    (d / "b").mkdir()
    (d / "a" / "int01.srt").write_text(srt)
    (d / "b" / "int01.srt").write_text(srt)
    out = d / "out.json"
    assert main([str(d / "a"), str(d / "b"), "-o", str(out), "--quiet"]) == 0
    ids = [item["id"] for item in json.loads(out.read_text())]
    assert len(ids) == 2 and len(set(ids)) == 2


def test_an_importer_refuses_to_write_a_repeated_id():
    from potato.importers.text.base import ImportedDocument, TextImportResult
    from potato.importers.text.project import write_data_file
    d = Path(_fresh_dir("tg2_import_dup"))
    result = TextImportResult(documents=[ImportedDocument("doc1", "a"),
                                         ImportedDocument("doc1", "b")])
    with pytest.raises(ValueError, match="doc1"):
        write_data_file(d / "data.jsonl", result, "ner")

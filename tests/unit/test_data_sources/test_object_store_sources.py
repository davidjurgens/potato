"""
Object-store sources: one object or a prefix of objects, and live ingestion
of new objects under a prefix.

The shared logic runs against an in-memory store. S3 runs through botocore's
Stubber, which checks every request and response against the real S3 API
model; GCS and Azure run the real SDKs against local fakes of their APIs
(test_cloud_sdks_against_fakes.py).
"""

import io
import json
from datetime import datetime, timedelta, timezone

import pytest

from potato.data_sources.base import SourceConfig, SourceType
from potato.data_sources.live_ingestion import (
    LiveCursorStore, LiveIngestionConfig, LiveIngestionWorker,
)
from potato.data_sources.sources.object_store import ObjectInfo, ObjectStoreSource, tiebreak
from tests.helpers.test_utils import cleanup_test_directory, create_test_directory

T0 = datetime(2026, 10, 19, 10, 0, tzinfo=timezone.utc)


def jsonl(*ids):
    return "".join(json.dumps({"id": i, "text": f"text {i}"}) + "\n" for i in ids).encode()


class MemoryStore(ObjectStoreSource):
    """The base class's logic over a dict: key -> (modified, bytes)."""

    def __init__(self, objects, **config):
        super().__init__(SourceConfig(SourceType.S3, "mem", {"bucket": "b", **config}))
        self.objects = dict(objects)
        self.reads = []

    def is_available(self):
        return True

    def _uri(self, key):
        return f"mem://b/{key}"

    def _list_objects(self, prefix):
        return [ObjectInfo(k, m, len(c)) for k, (m, c) in self.objects.items() if k.startswith(prefix)]

    def _read_object(self, key):
        self.reads.append(key)
        return self.objects[key][1], ""


OBJECTS = {
    "in/b.jsonl": (T0, jsonl("b1", "b2", "b3")),
    "in/a.jsonl": (T0, jsonl("a1")),
    "in/c.csv": (T0 + timedelta(minutes=5), b"id,text\nc1,hello\n"),
    "in/notes.txt": (T0, b"not data"),
    "other/x.jsonl": (T0, jsonl("x1")),
}
LIVE = {"enabled": True, "batch_size": 100}


def ids(rows):
    return [r.item["id"] for r in rows]


class TestReading:
    def test_one_object(self):
        store = MemoryStore(OBJECTS, key="in/b.jsonl")
        assert [i["id"] for i in store.read_items()] == ["b1", "b2", "b3"]

    def test_a_prefix_reads_every_data_file_in_key_order(self):
        store = MemoryStore(OBJECTS, prefix="in/")
        assert [i["id"] for i in store.read_items()] == ["a1", "b1", "b2", "b3", "c1"]
        assert "in/notes.txt" not in store.reads

    def test_key_or_prefix_and_live_needs_a_prefix(self):
        assert any("'key'" in e for e in MemoryStore(OBJECTS).validate_config())
        assert any("not both" in e for e in MemoryStore(OBJECTS, key="k", prefix="p").validate_config())
        store = MemoryStore(OBJECTS, key="in/a.jsonl", live_ingestion=LIVE)
        assert any("needs 'prefix'" in e for e in store.validate_config())
        assert store.supports_live_ingestion() is False


class TestReadSince:
    def test_rows_in_modified_key_index_order(self):
        store = MemoryStore(OBJECTS, prefix="in/", live_ingestion=LIVE)
        rows = list(store.read_since())
        assert ids(rows) == ["a1", "b1", "b2", "b3", "c1"]
        assert rows[1].tiebreak_value == tiebreak("in/b.jsonl", 0)
        assert rows[-1].cursor_value == T0 + timedelta(minutes=5)

    def test_a_batch_that_stops_mid_object_resumes_at_the_next_row(self):
        store = MemoryStore(OBJECTS, prefix="in/", live_ingestion=LIVE)
        first = list(store.read_since(limit=3))
        assert ids(first) == ["a1", "b1", "b2"]
        last = first[-1]
        rest = list(store.read_since(cursor=last.cursor_value, tiebreaker=last.tiebreak_value))
        assert ids(rest) == ["b3", "c1"]

    def test_a_cursor_without_a_tiebreaker_is_strictly_after(self):
        store = MemoryStore(OBJECTS, prefix="in/", live_ingestion=LIVE)
        assert ids(store.read_since(cursor=T0)) == ["c1"]
        assert ids(store.read_since(cursor=T0.isoformat())) == ["c1"]  # a decoded string cursor

    def test_objects_newer_than_the_safety_lag_wait(self):
        recent = {"in/new.jsonl": (datetime.now(timezone.utc), jsonl("n1")), **OBJECTS}
        store = MemoryStore(recent, prefix="in/", live_ingestion={**LIVE, "safety_lag_seconds": 60})
        assert "n1" not in ids(store.read_since())


class TestWorker:
    @pytest.fixture
    def worker(self):
        folder = create_test_directory("object_store_live")
        store = MemoryStore(OBJECTS, prefix="in/", live_ingestion=LIVE)
        pool = {}

        def ingest(item):
            if item["id"] in pool:
                return "duplicate"
            pool[item["id"]] = item
            return "added"

        config = LiveIngestionConfig.from_dict(LIVE)
        yield store, pool, LiveIngestionWorker(store, config, LiveCursorStore(folder), ingest)
        cleanup_test_directory(folder)

    def test_new_objects_arrive_and_reuploads_are_deduped(self, worker):
        store, pool, live = worker
        live.prime()
        assert sorted(pool) == ["a1", "b1", "b2", "b3", "c1"]
        store.objects["in/d.jsonl"] = (T0 + timedelta(minutes=9), jsonl("d1", "d2"))
        live.poll_once()
        assert {"d1", "d2"} <= set(pool)
        # Uploaded again with one new row: the old rows come back and are dropped.
        store.objects["in/d.jsonl"] = (T0 + timedelta(minutes=12), jsonl("d1", "d2", "d3"))
        outcome = live.poll_once()
        assert "d3" in pool and len(pool) == 8
        assert outcome is not None


class TestS3:
    """botocore's Stubber: every call is checked against the S3 API model."""

    @pytest.fixture
    def s3(self):
        boto3 = pytest.importorskip("boto3")
        from botocore.response import StreamingBody
        from botocore.stub import Stubber

        from potato.data_sources.sources.s3_source import S3Source
        source = S3Source(SourceConfig(SourceType.S3, "s3", {
            "bucket": "data", "prefix": "in/", "live_ingestion": LIVE}))
        client = boto3.client("s3", region_name="us-east-1", aws_access_key_id="x",
                              aws_secret_access_key="y")
        source._client = client
        stub = Stubber(client)

        def body(content):
            return StreamingBody(io.BytesIO(content), len(content))
        return source, stub, body

    def test_a_prefix_through_the_real_api_shapes(self, s3):
        source, stub, body = s3
        stub.add_response("list_objects_v2", {"Contents": [
            {"Key": "in/", "LastModified": T0, "Size": 0},
            {"Key": "in/b.jsonl", "LastModified": T0, "Size": 10},
            {"Key": "in/a.csv", "LastModified": T0, "Size": 10}], "IsTruncated": False},
            {"Bucket": "data", "Prefix": "in/"})
        stub.add_response("get_object", {"Body": body(b"id,text\na1,x\n"), "ContentType": "text/csv"},
                          {"Bucket": "data", "Key": "in/a.csv"})
        stub.add_response("get_object", {"Body": body(jsonl("b1")), "ContentType": "application/json"},
                          {"Bucket": "data", "Key": "in/b.jsonl"})
        with stub:
            assert [i["id"] for i in source.read_items()] == ["a1", "b1"]
            stub.assert_no_pending_responses()

    def test_a_missing_object_says_which(self, s3):
        source, stub, _body = s3
        source._key, source._prefix = "in/gone.jsonl", ""
        stub.add_client_error("get_object", service_error_code="NoSuchKey", http_status_code=404)
        with stub, pytest.raises(ValueError, match="s3://data/in/gone.jsonl"):
            list(source.read_items())


class TestConfigValidation:
    def _validate(self, source):
        from potato.server_utils.config_module import validate_data_sources_config
        validate_data_sources_config({"data_sources": [source]})

    def test_the_new_types_validate(self):
        self._validate({"type": "gcs", "bucket": "b", "prefix": "in/"})
        self._validate({"type": "azure_blob", "container": "c", "key": "k.jsonl",
                        "connection_string": "UseDevelopmentStorage=true"})
        self._validate({"type": "s3", "bucket": "b", "prefix": "in/",
                        "live_ingestion": {"enabled": True}})

    def test_mistakes_are_named(self):
        from potato.server_utils.config_module import ConfigValidationError
        with pytest.raises(ConfigValidationError, match="needs 'prefix'"):
            self._validate({"type": "gcs", "bucket": "b", "key": "k.jsonl",
                            "live_ingestion": {"enabled": True}})
        with pytest.raises(ConfigValidationError, match="'connection_string' or 'account_url'"):
            self._validate({"type": "azure_blob", "container": "c", "prefix": "p/"})
        with pytest.raises(ConfigValidationError, match="does not support 'live_ingestion'"):
            self._validate({"type": "url", "url": "https://x.org/d.jsonl",
                            "live_ingestion": {"enabled": True}})

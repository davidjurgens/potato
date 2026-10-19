"""
The GCS and Azure sources through their real SDKs, against local fakes of the
services' HTTP APIs.

The fakes answer only the requests these sources make (listing a prefix,
reading an object's metadata, downloading it), in the wire format each
service documents: GCS's JSON API (reached through STORAGE_EMULATOR_HOST, the
SDK's own emulator switch) and Azure Blob's REST API (XML listing, ranged
download). So the request shapes, pagination parameters and the parsing of
timestamps are the SDKs' own, not assumed.

The sources are read directly: validate_config() refuses loopback endpoints
on purpose (see test_azure_refuses_a_loopback_endpoint).
"""

import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from potato.data_sources.base import SourceConfig, SourceType

OBJECTS = {
    "in/a.jsonl": b'{"id": "a1", "text": "x"}\n',
    "in/b.csv": b"id,text\nb1,y\n",
    "in/readme.md": b"# not data",
}
UPDATED_ISO = "2026-10-19T10:00:00.000Z"
UPDATED_HTTP = "Mon, 19 Oct 2026 10:00:00 GMT"


def serve(handler):
    server = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def send(handler, status, body, content_type, extra=None):
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    for key, value in (extra or {}).items():
        handler.send_header(key, value)
    handler.end_headers()
    handler.wfile.write(body)


class GCSFake(BaseHTTPRequestHandler):
    requests = []

    def _meta(self, name):
        return {"kind": "storage#object", "name": name, "bucket": "data",
                "size": str(len(OBJECTS[name])), "updated": UPDATED_ISO,
                "contentType": "text/csv" if name.endswith(".csv") else "application/x-ndjson",
                "generation": "1", "metageneration": "1"}

    def do_GET(self):
        GCSFake.requests.append(self.path)
        url = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(url.query)
        if url.path == "/storage/v1/b/data/o":
            prefix = query.get("prefix", [""])[0]
            offset = query.get("startOffset", [""])[0]  # inclusive, per the JSON API
            items = [self._meta(n) for n in sorted(OBJECTS)
                     if n.startswith(prefix) and n >= offset]
            return send(self, 200, json.dumps({"kind": "storage#objects", "items": items}).encode(),
                        "application/json")
        for base in ("/storage/v1/b/data/o/", "/download/storage/v1/b/data/o/"):
            if url.path.startswith(base):
                name = urllib.parse.unquote(url.path[len(base):])
                if name not in OBJECTS:
                    return send(self, 404, b'{"error": {"code": 404}}', "application/json")
                if "alt" in query:
                    return send(self, 200, OBJECTS[name], "application/octet-stream")
                return send(self, 200, json.dumps(self._meta(name)).encode(), "application/json")
        send(self, 404, b"{}", "application/json")

    def log_message(self, *args):
        pass


class AzureFake(BaseHTTPRequestHandler):
    requests = []

    def do_GET(self):
        AzureFake.requests.append(self.path)
        url = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(url.query)
        headers = {"x-ms-version": "2025-01-05"}
        if query.get("comp") == ["list"]:
            prefix = query.get("prefix", [""])[0]
            blobs = "".join(
                f"<Blob><Name>{n}</Name><Properties><Last-Modified>{UPDATED_HTTP}</Last-Modified>"
                f"<Etag>0x1</Etag><Content-Length>{len(c)}</Content-Length>"
                f"<Content-Type>text/plain</Content-Type><BlobType>BlockBlob</BlobType>"
                f"</Properties></Blob>" for n, c in OBJECTS.items() if n.startswith(prefix))
            body = ('<?xml version="1.0" encoding="utf-8"?><EnumerationResults '
                    'ServiceEndpoint="http://127.0.0.1/acct/" ContainerName="data">'
                    f"<Prefix>{prefix}</Prefix><Blobs>{blobs}</Blobs><NextMarker /></EnumerationResults>")
            return send(self, 200, body.encode(), "application/xml", headers)
        name = urllib.parse.unquote(url.path.split("/data/", 1)[1])
        if name not in OBJECTS:
            # Shaped like the service's own error body; the SDK's error
            # handler reads the Message element.
            return send(self, 404, b'<?xml version="1.0" encoding="utf-8"?><Error><Code>BlobNotFound'
                                   b'</Code><Message>The specified blob does not exist.</Message></Error>',
                        "application/xml", {**headers, "x-ms-error-code": "BlobNotFound"})
        content = OBJECTS[name]
        start, end = (self.headers.get("x-ms-range") or "bytes=0-").split("=")[1].split("-")
        start, end = int(start), min(int(end or len(content) - 1), len(content) - 1)
        part = content[start:end + 1]
        send(self, 206, part, "text/csv" if name.endswith(".csv") else "application/x-ndjson", {
            **headers, "Content-Range": f"bytes {start}-{start + len(part) - 1}/{len(content)}",
            "Last-Modified": UPDATED_HTTP, "ETag": '"0x1"', "x-ms-blob-type": "BlockBlob"})

    def log_message(self, *args):
        pass


@pytest.fixture
def gcs(monkeypatch):
    pytest.importorskip("google.cloud.storage")
    from potato.data_sources.sources.gcs_source import GCSSource
    server = serve(GCSFake)
    GCSFake.requests = []
    monkeypatch.setenv("STORAGE_EMULATOR_HOST", f"http://127.0.0.1:{server.server_port}")

    def make(**config):
        return GCSSource(SourceConfig(SourceType.GCS, "g", {"bucket": "data", "anonymous": True, **config}))
    yield make
    server.shutdown()


@pytest.fixture
def azure():
    pytest.importorskip("azure.storage.blob")
    from potato.data_sources.sources.azure_blob_source import AzureBlobSource
    server = serve(AzureFake)
    AzureFake.requests = []

    def make(**config):
        return AzureBlobSource(SourceConfig(SourceType.AZURE_BLOB, "a", {
            "container": "data", "account_url": f"http://127.0.0.1:{server.server_port}/acct", **config}))
    yield make
    server.shutdown()


class TestGCS:
    def test_a_prefix_through_the_sdk(self, gcs):
        source = gcs(prefix="in/")
        assert [i["id"] for i in source.read_items()] == ["a1", "b1"]
        assert GCSFake.requests[0].startswith("/storage/v1/b/data/o?")
        assert "prefix=in%2F" in GCSFake.requests[0]
        assert not any("readme" in r for r in GCSFake.requests)

    def test_live_rows_carry_the_objects_time(self, gcs):
        rows = list(gcs(prefix="in/", live_ingestion={"enabled": True}).read_since())
        assert [(r.item["id"], r.cursor_value.isoformat()) for r in rows] == [
            ("a1", "2026-10-19T10:00:00+00:00"), ("b1", "2026-10-19T10:00:00+00:00")]

    def test_key_ordered_polling_starts_after_the_last_key(self, gcs):
        from potato.data_sources.sources.object_store import tiebreak
        source = gcs(prefix="in/", live_ingestion={"enabled": True, "listing": "after_last_key"})
        rows = list(source.read_since(tiebreaker=tiebreak("in/a.jsonl", 0, 1)))
        assert [r.item["id"] for r in rows] == ["b1"]
        listing = next(r for r in GCSFake.requests if r.startswith("/storage/v1/b/data/o?"))
        assert "startOffset=in%2Fa.jsonl" in listing

    def test_a_missing_object_says_which(self, gcs):
        with pytest.raises(ValueError, match="gs://data/in/gone.jsonl"):
            list(gcs(key="in/gone.jsonl").read_items())


class TestAzure:
    def test_a_prefix_through_the_sdk(self, azure):
        source = azure(prefix="in/")
        assert [i["id"] for i in source.read_items()] == ["a1", "b1"]
        assert AzureFake.requests[0] == "/acct/data?restype=container&comp=list&prefix=in%2F"

    def test_live_rows_carry_the_blobs_time(self, azure):
        rows = list(azure(prefix="in/", live_ingestion={"enabled": True}).read_since())
        assert [r.cursor_value.isoformat() for r in rows] == ["2026-10-19T10:00:00+00:00"] * 2

    def test_a_missing_blob_says_which(self, azure):
        with pytest.raises(ValueError, match="azure://data/in/gone.jsonl"):
            list(azure(key="in/gone.jsonl").read_items())

    def test_azure_refuses_a_loopback_endpoint(self, azure):
        errors = azure(prefix="in/").validate_config()
        assert any("blocked IP 127.0.0.1" in e for e in errors)
        from potato.data_sources.sources.azure_blob_source import AzureBlobSource
        via_string = AzureBlobSource(SourceConfig(SourceType.AZURE_BLOB, "a", {
            "container": "c", "prefix": "p/",
            "connection_string": "AccountName=x;BlobEndpoint=http://127.0.0.1:10000/x;"}))
        assert any("BlobEndpoint" in e for e in via_string.validate_config())

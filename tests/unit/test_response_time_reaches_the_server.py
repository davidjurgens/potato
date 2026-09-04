"""`attention_checks.min_response_time` needs a response time to compare against.

The server derived one from `client_timestamp`, a field `annotation.js` never
sent — so the guard was unreachable on the annotation path. Driven with
`min_response_time: 8` and answers submitted in one to two seconds, the log held
no "responded to attention check ... in Xs" line at all. And `client_timestamp`
is the moment the request was *sent*, so subtracting it from server time would
have measured network latency rather than how long the annotator looked at the
item.

Both halves have to stay wired: the client stamps when the instance appeared and
sends the elapsed seconds, and the server reads that field rather than
recomputing one.
"""

from pathlib import Path

import pytest

ANNOTATION_JS = Path(__file__).resolve().parents[2] / "potato" / "static" / "annotation.js"
ROUTES_PY = Path(__file__).resolve().parents[2] / "potato" / "routes.py"


@pytest.fixture(scope="module")
def annotation_js():
    return ANNOTATION_JS.read_text(encoding="utf-8")


def test_the_instance_display_time_is_stamped(annotation_js):
    assert "displayedAt: Date.now()" in annotation_js, (
        "loadCurrentInstance must stamp when the instance appeared, or there is "
        "nothing to measure the response time from"
    )


def test_both_save_paths_send_the_response_time(annotation_js):
    """`saveAnnotations` and `flushPendingSave` build their payloads separately."""
    assert annotation_js.count("response_time_seconds: currentInstanceResponseSeconds()") == 2


def test_both_save_paths_send_a_client_timestamp(annotation_js):
    assert annotation_js.count("client_timestamp: new Date().toISOString()") == 2


def test_the_server_reads_the_field_rather_than_deriving_one():
    routes = ROUTES_PY.read_text(encoding="utf-8")
    assert 'request.json.get("response_time_seconds")' in routes
    assert "datetime.datetime.now() - client_timestamp" not in routes, (
        "that subtraction measures network latency, not reading time"
    )

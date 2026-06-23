"""
End-to-end: a @traceable agent run is captured by the SDK, POSTed to a live
Potato server's trace-ingestion webhook, and ingested as an item.
"""

import time

import pytest
import requests

import potato_trace
from potato_trace import tracer
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager


@pytest.fixture(scope="class", autouse=True)
def flask_server(request):
    annotation_schemes = [{
        "annotation_type": "radio", "name": "ok",
        "description": "ok?", "labels": ["yes", "no"],
    }]
    extra = {"trace_ingestion": {"enabled": True, "api_key": "", "notify_annotators": False}}
    with TestConfigManager(
        "trace_capture", annotation_schemes,
        additional_config=extra, admin_api_key="test-admin-api-key",
    ) as test_config:
        server = FlaskTestServer(port=9063, config_file=test_config.config_path)
        if not server.start():
            pytest.fail("Failed to start server")
        request.cls.server = server
        yield server
        server.stop()


class TestTraceCaptureRoundtrip:
    def test_traced_agent_run_is_ingested(self):
        base = self.server.base_url

        # Point the SDK at the live server (real client, real HTTP).
        tracer._default_client = None
        potato_trace.configure(potato_url=base, project_name="roundtrip")

        @potato_trace.traceable(run_type="tool")
        def search(q):
            return f"results for {q}"

        @potato_trace.traceable
        def agent(task):
            return search(task)

        agent("find the weather")
        potato_trace.flush(timeout=15)

        # Verify ingestion via the status endpoint (requires login).
        s = requests.Session()
        s.post(f"{base}/register", data={"email": "u@test.com", "pass": "pw"})
        s.post(f"{base}/auth", data={"email": "u@test.com", "pass": "pw"})

        processed = 0
        for _ in range(20):
            r = s.get(f"{base}/api/traces/status")
            if r.status_code == 200:
                # counts are nested under "stats"
                processed = r.json().get("stats", {}).get("processed", 0)
                if processed >= 1:
                    break
            time.sleep(0.5)
        assert processed >= 1, "trace was not ingested"

    def test_disabled_client_is_safe_noop(self):
        # No URL configured -> tracing is a no-op and must not raise.
        tracer._default_client = None
        potato_trace.configure(potato_url="")

        @potato_trace.traceable
        def f(x):
            return x + 1

        assert f(1) == 2
        potato_trace.flush(timeout=1)

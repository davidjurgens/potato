"""
Tests for ``potato/preview_render.py``.

The parts worth pinning are the ones that were wrong the first time: which
directory the server is started from, and which browser complaints count as
signal.

The actual browser drive is covered by one end-to-end test that is skipped when
Playwright is absent. It boots a real server, so it is slow -- but it is the
only thing that proves the console-error path works at all, and a mocked version
would only prove the mock works.
"""

import json
import os

import pytest

from potato.preview_render import (
    PHASES,
    CaptureResult,
    _is_background,
    capture_task,
    find_free_port,
    playwright_available,
    server_cwd,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXAMPLE = os.path.join(
    REPO_ROOT, "examples", "classification", "single-choice", "config.yaml"
)


class TestServerCwd:
    """The server refuses configs outside its working directory.

    `init_config()` runs the config path through `validate_path_security()`
    against the cwd, so picking the wrong one makes a perfectly good config
    unpreviewable -- which is what happened to every config outside a Potato
    checkout.
    """

    def test_config_inside_cwd_keeps_cwd(self):
        """Repo examples set `task_dir: .` and expect to run from the root."""
        assert server_cwd(EXAMPLE) == os.getcwd()

    def test_config_outside_cwd_uses_its_own_directory(self, tmp_path):
        config = tmp_path / "config.yaml"
        config.write_text("annotation_task_name: x\n")
        assert server_cwd(str(config)) == str(tmp_path)

    def test_result_is_always_absolute(self, tmp_path):
        config = tmp_path / "config.yaml"
        config.write_text("annotation_task_name: x\n")
        assert os.path.isabs(server_cwd(str(config)))


class TestFindFreePort:
    def test_returns_a_bindable_port(self):
        import socket

        port = find_free_port()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", port))

    def test_raises_when_the_range_is_exhausted(self):
        with pytest.raises(RuntimeError):
            find_free_port(start=80, span=0)


class TestBackgroundClassification:
    """Optional subsystems poll unconditionally and 503 when switched off.

    Every annotation page produces nine of these. Counting them as errors would
    mean every config looks broken, which is the same as no signal at all.
    """

    @pytest.mark.parametrize("url", [
        "http://127.0.0.1:9080/api/codebook/version",
        "http://127.0.0.1:9080/api/memos?instance_id=item_1",
        "http://127.0.0.1:9080/api/search",
        "http://127.0.0.1:9080/qda/status",
    ])
    def test_known_background_endpoints(self, url):
        assert _is_background(url)

    @pytest.mark.parametrize("url", [
        "http://127.0.0.1:9080/annotate",
        "http://127.0.0.1:9080/static/annotation.js",
        "http://127.0.0.1:9080/media/missing.png",
        "http://127.0.0.1:9080/api/current_instance",
    ])
    def test_real_failures_are_not_background(self, url):
        assert not _is_background(url)


class TestCaptureResult:
    def test_clean_requires_a_successful_render(self):
        assert not CaptureResult(ok=False).clean

    def test_clean_ignores_background_errors(self):
        result = CaptureResult(
            ok=True, background_errors=[{"url": "/api/codebook", "status": 503}]
        )
        assert result.clean

    def test_page_errors_make_it_unclean(self):
        assert not CaptureResult(ok=True, page_errors=["boom"]).clean

    def test_http_errors_make_it_unclean(self):
        result = CaptureResult(
            ok=True, http_errors=[{"url": "/media/missing.png", "status": 404}]
        )
        assert not result.clean

    def test_to_dict_is_json_serializable(self):
        result = CaptureResult(ok=True, url="http://x", console_errors=["a"])
        json.dumps(result.to_dict())

    def test_to_dict_omits_html_by_default(self):
        result = CaptureResult(ok=True, html="<html></html>")
        assert "html" not in result.to_dict()
        assert "html" in result.to_dict(include_html=True)

    def test_summary_names_the_failure(self):
        result = CaptureResult(ok=True, page_errors=["labels is not iterable"])
        assert "labels is not iterable" in result.summary()


class TestGuardRails:
    def test_unknown_phase_is_rejected(self):
        with pytest.raises(ValueError):
            capture_task(EXAMPLE, phase="not_a_phase")

    def test_missing_config_returns_a_result_rather_than_raising(self):
        result = capture_task(os.path.join(REPO_ROOT, "no_such_config.yaml"))
        assert not result.ok
        assert "not found" in result.message

    def test_annotation_is_a_valid_phase(self):
        assert "annotation" in PHASES


@pytest.mark.skipif(not playwright_available(), reason="Playwright not installed")
class TestEndToEnd:
    """Boots a real server and drives a real browser."""

    @pytest.fixture(scope="class")
    def captured(self, tmp_path_factory):
        out = tmp_path_factory.mktemp("preview") / "shot.png"
        return capture_task(EXAMPLE, out_path=str(out))

    def test_renders_the_shipped_example(self, captured):
        assert captured.ok, captured.summary()

    def test_writes_a_png(self, captured):
        assert captured.png_path and os.path.isfile(captured.png_path)
        with open(captured.png_path, "rb") as f:
            assert f.read(8) == b"\x89PNG\r\n\x1a\n", "not a PNG"

    def test_returns_the_rendered_html(self, captured):
        assert captured.html and "annotation_schema" in captured.html

    def test_a_working_example_is_clean(self, captured):
        assert captured.clean, (
            "The shipped single-choice example reports browser errors:\n"
            + captured.summary()
        )

    def test_a_plain_task_makes_no_failed_requests_at_all(self, captured):
        """Not just clean -- silent.

        Memos, search-and-claim and the codebook tray used to load on every
        annotation page and probe their own APIs to discover they were off,
        so a config with none of those features still produced nine failed
        requests per page view. They are gated server-side now, and
        `background_errors` is the only place that would still show them:
        `clean` deliberately ignores it, so a regression here would be
        invisible to every other assertion in this file.
        """
        assert captured.background_errors == [], (
            "The single-choice example still calls optional subsystems:\n"
            + "\n".join(
                f"  {e['status']} {e['url']}" for e in captured.background_errors
            )
        )

    def test_catches_an_uncaught_exception(self, tmp_path):
        """The whole point: a valid config whose page throws anyway."""
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / "items.json").write_text(
            json.dumps([{"id": "1", "text": "hello"}])
        )
        (tmp_path / "config.yaml").write_text(
            "annotation_task_name: Broken JS Probe\n"
            "task_dir: .\n"
            "output_annotation_dir: ./out\n"
            "data_files: [data/items.json]\n"
            "item_properties:\n"
            "  id_key: id\n"
            "  text_key: text\n"
            "custom_footer_html: '<script>window.setTimeout(function(){ "
            "JSON.parse(\"{oops\"); }, 50);</script>'\n"
            "annotation_schemes:\n"
            "  - annotation_type: radio\n"
            "    name: q1\n"
            "    description: pick one\n"
            "    labels: [a, b]\n"
        )

        result = capture_task(str(tmp_path / "config.yaml"))
        assert result.ok, "the page should still render"
        assert not result.clean
        assert result.page_errors, (
            "a JSON.parse failure on load produced no page error; the console "
            "listener is not attached"
        )

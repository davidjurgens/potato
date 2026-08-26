"""
Render a task config in a real browser and report what happened.

`potato validate` proves a config is well-formed and `potato preview` shows the
widgets a config declares, but neither can tell you the page threw
`labels is not iterable` on load. That failure class -- the config is valid, the
server serves it, and the interface is broken anyway -- lives entirely in the
browser, and it is where the annotation UI actually goes wrong: canvases,
timelines, deep-zoom viewers and span managers are all built by JavaScript after
the HTML arrives.

So this boots the real server on a free port, drives a headless browser at the
annotation page, and returns a screenshot *together with* everything the browser
complained about. The console errors matter more than the image: they turn "it
looks wrong" into a specific exception, which is the difference between an agent
that can fix its own config and one that cannot.

Why not the existing pieces:

  * `preview_cli --format html` builds a standalone page from the scheme
    generators. It uses none of the real base template, CSS, `instance_display`,
    layout or JS, so a screenshot of it verifies widget markup and nothing about
    the page an annotator sees.
  * `scripts/screenshot_batch2.py` works, but is driven by a hand-maintained
    name-to-path table and depends on Selenium, which is test-only. It now
    imports its server lifecycle from here.

Playwright is optional (`pip install potato-annotation[preview]`). Without it
you still get the server-rendered HTML and a clear message, never a hard failure.

Usage:
    from potato.preview_render import capture_task
    result = capture_task("config.yaml", out_path="preview.png")
    print(result.console_errors)
"""

from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# The annotation form wrapper emitted by the real template. Its presence is what
# distinguishes "the page rendered" from "the server returned a login redirect".
DEFAULT_WAIT_FOR = ".annotation_schema"

# stderr from the most recent server that failed to boot. A module-level slot
# because the Popen object is gone by the time the caller wants to explain why.
_LAST_STARTUP_LOG: Dict[str, str] = {}

# Phases `--debug-phase` accepts.
PHASES = ("consent", "instructions", "training", "annotation", "poststudy")

# The page each phase actually serves. `--debug-phase` puts the user *in* that
# phase, and every other phase's route then redirects back to where the user
# is supposed to be -- so asking for `/annotate` while parked on the
# instructions phase is a redirect loop, not a page. Rendering a phase means
# navigating to that phase's own route.
PHASE_ROUTES = {
    "consent": "/consent",
    "instructions": "/instructions",
    "training": "/training",
    "annotation": "/annotate",
    "poststudy": "/poststudy",
}

# `.annotation_schema` is the annotation form wrapper. Phase pages render
# through a different path and need not contain one -- an instructions page is
# often prose and a Next button -- so waiting for it there would time out on a
# page that rendered perfectly.
PHASE_WAIT_FOR = {
    "annotation": DEFAULT_WAIT_FOR,
    "training": DEFAULT_WAIT_FOR,
}
PHASE_PAGE_WAIT_FOR = "body"

# Optional subsystems. A task that enables one of these polls it, and some of
# those polls are probes that expect a refusal -- the codebook tray asks
# /api/codebook/admin/proposals to find out whether the annotator may curate,
# and a plain annotator gets a 403 by design. Reporting those as errors would
# bury the one that matters, so they are collected separately rather than
# dropped. A task that enables none of them should reach zero here: the three
# universal sidebars are gated server-side, and they used to account for nine
# failed requests on every annotation page.
_BACKGROUND_ENDPOINTS = (
    "/api/codebook",
    "/api/memos",
    "/api/search",
    "/api/cases",
    "/api/sessions",
    "/qda/",
    "/solo/api/",
)

# Console text for a failed subresource. The URL lives in the message location,
# not the text, so these are matched here and reported through `http_errors`,
# where the URL is available and can be classified.
_RESOURCE_ERROR_PREFIX = "Failed to load resource"


def _is_background(url: str) -> bool:
    return any(endpoint in url for endpoint in _BACKGROUND_ENDPOINTS)


@dataclass
class CaptureResult:
    """What a render attempt produced.

    `ok` means the page loaded and the wait-for selector appeared. It says
    nothing about whether the page is *correct* -- read `console_errors` for
    that, which is the whole point of this module.
    """

    ok: bool
    url: str = ""
    png_path: Optional[str] = None
    console_errors: List[str] = field(default_factory=list)
    console_messages: List[Dict[str, str]] = field(default_factory=list)
    page_errors: List[str] = field(default_factory=list)
    http_errors: List[Dict[str, Any]] = field(default_factory=list)
    background_errors: List[Dict[str, Any]] = field(default_factory=list)
    html: Optional[str] = None
    server_log: str = ""
    message: str = ""

    @property
    def clean(self) -> bool:
        """Rendered with nothing the browser objected to.

        Ignores `background_errors`: those come from optional subsystems the
        task switched on, including probes that expect to be refused, so they
        say nothing about whether the config is right.
        """
        return (
            self.ok
            and not self.console_errors
            and not self.page_errors
            and not self.http_errors
        )

    def to_dict(self, include_html: bool = False) -> dict:
        out = {
            "ok": self.ok,
            "clean": self.clean,
            "url": self.url,
            "png_path": self.png_path,
            "console_errors": self.console_errors,
            "page_errors": self.page_errors,
            "http_errors": self.http_errors,
            "background_errors": self.background_errors,
            "message": self.message,
        }
        if include_html:
            out["html"] = self.html
        return out

    def summary(self) -> str:
        """One-screen human summary."""
        lines = []
        if not self.ok:
            lines.append(f"FAILED — {self.message}")
        elif self.clean:
            lines.append("Rendered cleanly — no browser errors.")
        else:
            lines.append(
                f"Rendered with {len(self.console_errors)} console error(s) and "
                f"{len(self.page_errors)} uncaught exception(s)."
            )
        if self.png_path:
            lines.append(f"Screenshot: {self.png_path}")
        for err in self.page_errors:
            lines.append(f"  uncaught: {err}")
        for err in self.console_errors:
            lines.append(f"  console.error: {err}")
        for req in self.http_errors:
            lines.append(f"  HTTP {req['status']}: {req['url']}")
        if self.background_errors:
            lines.append(
                f"  ({len(self.background_errors)} request(s) to optional "
                f"subsystems failed; expected when those features are off)"
            )
        return "\n".join(lines)


def find_free_port(start: int = 9080, span: int = 200) -> int:
    """A port nothing is listening on.

    Binds the way the server binds -- no SO_REUSEADDR -- because a probe that
    sets it will happily hand back a port already in use, and the symptom shows
    up later as an unrelated test hitting the wrong server.
    """
    for port in range(start, start + span):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No free port in range {start}-{start + span}")


def server_cwd(config_path: str) -> str:
    """Directory to run the server from, for a config at `config_path`.

    `init_config()` runs the config path through `validate_path_security()`
    against the *current working directory* and refuses anything outside it, so
    the cwd has to contain the config. Running from Potato's own source tree
    therefore worked only for configs that happened to live inside it -- which
    is exactly not the case an agent authoring a task in its own project hits.

    A repository checkout is the one place to keep running from the root: the
    shipped examples set `task_dir: .` and are documented as being started from
    there.
    """
    config_dir = os.path.dirname(os.path.abspath(config_path)) or os.getcwd()

    cwd = os.getcwd()
    if os.path.commonpath([config_dir, cwd]) == os.path.abspath(cwd):
        return cwd
    return config_dir


def _task_name(config_path: str) -> Optional[str]:
    """`annotation_task_name` from a config, or None if it cannot be read."""
    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            return (yaml.safe_load(f) or {}).get("annotation_task_name")
    except Exception:
        return None


def _serving_task_name(port: int) -> Optional[str]:
    """Which task the server on `port` has loaded, or None if it cannot say.

    `/admin/health` reports the task name and needs an API key -- except in
    debug mode, which is how every preview server runs, so it answers here and
    nowhere else. None means "cannot tell yet", which is different from a
    mismatch and is treated as "keep waiting".
    """
    import json
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/admin/health", timeout=2
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return (payload.get("config") or {}).get("annotation_task_name")
    except Exception:
        return None


def start_server(
    config_path: str,
    port: int,
    phase: str = "annotation",
    timeout: float = 60.0,
    cwd: Optional[str] = None,
):
    """Launch a debug server for `config_path`. Returns Popen, or None.

    Debug mode is what makes this usable unattended: it skips login and
    `--debug-phase` jumps straight past consent and instructions, so the
    browser lands on the annotation page without anyone clicking through.
    """
    working_dir = cwd or server_cwd(config_path)
    config_arg = os.path.relpath(os.path.abspath(config_path), working_dir)

    # `python -m potato` rather than a path into the source tree, so this works
    # the same from an installed wheel as from a checkout.
    cmd = [
        sys.executable, "-m", "potato",
        "start",
        config_arg,
        "-p", str(port),
        "--debug",
        "--debug-phase", phase,
        # Loopback explicitly. This is a throwaway server for one screenshot,
        # so it has no reason to listen on anything else -- and debug on a
        # non-loopback bind is refused, since debug narrows admin auth and
        # exposes the interactive debugger.
        "--host", "127.0.0.1",
    ]

    # DEVNULL on stdout: a verbose config can fill the 64KB pipe buffer and
    # deadlock the child before it ever finishes booting.
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        cwd=working_dir,
    )

    import urllib.error
    import urllib.request

    expected = _task_name(config_path)

    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            stderr = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
            logger.error("Preview server exited during startup: %s", stderr[-2000:])
            _LAST_STARTUP_LOG["text"] = stderr
            return None
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2):
                pass
        except urllib.error.HTTPError:
            pass
        except (urllib.error.URLError, OSError):
            time.sleep(0.4)
            continue

        # Something is listening. Establish that it is *ours* before handing
        # the port to a browser. `find_free_port` probes and releases, so any
        # other process -- most often a second preview running concurrently --
        # can take the port in between, and /health deliberately reports
        # nothing identifying. Without this check the renderer attaches to a
        # stranger's task, screenshots it, finds no console errors, and reports
        # a clean render of a config it never loaded.
        serving = _serving_task_name(port)
        if serving is None:
            # Ours is still booting: the port answers /health from the
            # half-built app before the config is in place. Keep waiting.
            time.sleep(0.4)
            continue
        if expected is not None and serving != expected:
            logger.error(
                "Port %s is serving %r, not %r -- another server took it. "
                "Not rendering someone else's task.", port, serving, expected)
            _LAST_STARTUP_LOG["text"] = (
                f"Port {port} was already serving the task {serving!r}."
            )
            stop_server(proc)
            return None
        return proc

    logger.error("Preview server did not become ready within %ss", timeout)
    stop_server(proc)
    return None


def stop_server(proc) -> None:
    """Terminate a preview server, escalating to kill if it will not go."""
    if not proc:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def playwright_available() -> bool:
    """True when Playwright can actually drive a browser.

    Checks for a browser *binary*, not just the Python package. They install
    separately: `requirements-test.txt` pulls in pytest-playwright, so CI had
    the import succeed and every render fail with "Browser failed to open the
    page". A skip guard that answers the wrong question is worse than none,
    because it turns "this environment cannot run these" into a red build.

    The probe runs in a subprocess. Resolving the executable path goes through
    the sync API, which raises if called from inside an asyncio loop -- and the
    render path this guards *is* async, so probing in-process would report
    "no browser" precisely when a browser was about to be used.
    """
    global _BROWSER_PRESENT
    if _BROWSER_PRESENT is not None:
        return _BROWSER_PRESENT

    try:
        import playwright  # noqa: F401
    except ImportError:
        _BROWSER_PRESENT = False
        return False

    probe = (
        "import os,sys\n"
        "from playwright.sync_api import sync_playwright\n"
        "with sync_playwright() as p:\n"
        "    sys.exit(0 if os.path.exists(p.chromium.executable_path) else 1)\n"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True, timeout=60,
        )
        _BROWSER_PRESENT = result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        _BROWSER_PRESENT = False
    return _BROWSER_PRESENT


#: Probing spawns a subprocess, so the answer is cached for the process.
_BROWSER_PRESENT = None


PLAYWRIGHT_HINT = (
    "No Playwright browser is available, so no screenshot was taken. The\n"
    "package and the browser install separately; you need both:\n"
    "    pip install 'potato-annotation[preview]' && playwright install chromium"
)


async def _drive_browser(
    url: str,
    phase: str,
    out_path: Optional[str],
    width: int,
    height: int,
    wait_for: str,
    settle_ms: int,
) -> CaptureResult:
    import asyncio

    from potato.web_playwright import PlaywrightSession

    result = CaptureResult(ok=False, url=url)
    session = PlaywrightSession(width=width, height=height)

    if not await session.start(url):
        # A redirect loop here means the phase does not exist for this task:
        # `--debug-phase X` parks the user in X, every route redirects toward
        # where the user is supposed to be, and with no X page configured the
        # bounce never terminates. Saying "browser failed" sends people looking
        # at Playwright, which is the wrong end entirely.
        if phase != "annotation":
            result.message = (
                f"No {phase!r} page to render. `--phase {phase}` parks an "
                f"annotator in that phase, and this task does not configure "
                f"one, so the server redirects endlessly. Add the phase (see "
                f"`phases` and `surveyflow`) or render a phase the task has.\n"
                f"Note that `annotation_instructions` is the banner on the "
                f"annotation page, not an instructions phase."
            )
        else:
            result.message = "Browser failed to open the page"
        return result

    try:
        found = await session.wait_for_selector(wait_for, timeout_ms=15000)

        # The form appearing is not the end of the story. Canvas viewers, span
        # managers and timeline widgets initialize after DOM ready, and their
        # failures land here -- returning as soon as the selector resolves
        # raced past exactly the errors this exists to catch.
        if settle_ms > 0:
            await asyncio.sleep(settle_ms / 1000)

        result.html = await session.content()

        if out_path:
            png = await session.screenshot()
            if png:
                os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
                with open(out_path, "wb") as f:
                    f.write(png)
                result.png_path = os.path.abspath(out_path)

        # A "Failed to load resource" console line duplicates an entry in
        # failed_requests but without the URL, so it is reported there instead.
        result.console_errors = [
            e for e in session.console_errors
            if not e.startswith(_RESOURCE_ERROR_PREFIX)
        ]
        result.console_messages = list(session.console_messages)
        result.page_errors = list(session.page_errors)
        result.http_errors = [
            r for r in session.failed_requests if not _is_background(r["url"])
        ]
        result.background_errors = [
            r for r in session.failed_requests if _is_background(r["url"])
        ]
        result.ok = found
        if not found:
            result.message = (
                f"The page loaded but {wait_for!r} never appeared, so the "
                f"annotation form did not render"
            )
        return result
    finally:
        await session.stop()


def capture_task(
    config_file: str,
    *,
    phase: str = "annotation",
    out_path: Optional[str] = None,
    width: int = 1280,
    height: int = 900,
    wait_for: Optional[str] = None,
    port: Optional[int] = None,
    settle_ms: int = 1200,
) -> CaptureResult:
    """Boot `config_file`, open it in a browser, and report what the browser saw.

    Args:
        config_file: Path to the task config.
        phase: Workflow phase to jump to. One of PHASES.
        out_path: Where to write the PNG. None skips the screenshot.
        width, height: Viewport size.
        wait_for: CSS selector that marks a successful render. Defaults to the
            annotation form wrapper on annotation and training pages, and to
            `body` on the other phase pages, which need not contain a form --
            an instructions page is often prose and a Next button.
        port: Fixed port, otherwise one is found.
        settle_ms: How long to keep listening after the form appears, so
            errors thrown by late-initializing widgets are caught.

    Returns:
        CaptureResult. Never raises for the ordinary failures -- a missing
        browser, a server that will not boot, a page that will not render -- so
        a caller can always report something useful.

    Safe to call from inside an event loop: the work moves to a thread.
    """
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        # Already inside an event loop -- the MCP server calls this from one.
        # asyncio.run() refuses to nest, so hand the whole job to a worker
        # thread with a loop of its own.
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(
                _capture_task_sync,
                config_file, phase, out_path, width, height, wait_for, port,
                settle_ms,
            ).result()

    return _capture_task_sync(
        config_file, phase, out_path, width, height, wait_for, port, settle_ms
    )


def _capture_task_sync(
    config_file: str,
    phase: str,
    out_path: Optional[str],
    width: int,
    height: int,
    wait_for: str,
    port: Optional[int],
    settle_ms: int,
) -> CaptureResult:
    """The body of capture_task, always on a thread with no running loop."""
    import asyncio

    if phase not in PHASES:
        raise ValueError(f"phase must be one of {PHASES}, got {phase!r}")
    if wait_for is None:
        wait_for = PHASE_WAIT_FOR.get(phase, PHASE_PAGE_WAIT_FOR)

    if not os.path.isfile(config_file):
        return CaptureResult(ok=False, message=f"Config file not found: {config_file}")

    chosen_port = port or find_free_port()
    proc = start_server(config_file, chosen_port, phase=phase)
    if proc is None:
        startup_log = _LAST_STARTUP_LOG.get("text", "")
        if "was already serving the task" in startup_log:
            # A port collision, not a bad config. Saying "run validate" here
            # sends people to check a config that is fine.
            message = (
                f"{startup_log.strip()} Another preview or server holds that "
                f"port, so nothing was rendered. Retry -- a free port is "
                f"chosen each time -- or pass an explicit `port=`."
            )
        else:
            message = (
                "The server did not start with this config. Run "
                f"`potato validate {config_file}` for the reason, and read "
                f"`server_log` below for the boot error -- validation does not "
                f"catch everything the server checks at startup."
            )
        return CaptureResult(ok=False, message=message, server_log=startup_log)

    url = f"http://127.0.0.1:{chosen_port}{PHASE_ROUTES.get(phase, '/annotate')}"

    try:
        if not playwright_available():
            html = _fetch(url)
            return CaptureResult(
                ok=html is not None,
                url=url,
                html=html,
                message=PLAYWRIGHT_HINT,
            )
        return asyncio.run(
            _drive_browser(url, phase, out_path, width, height, wait_for, settle_ms)
        )
    except Exception as e:  # pragma: no cover - defensive
        logger.exception("Preview render failed")
        return CaptureResult(ok=False, url=url, message=f"Render failed: {e}")
    finally:
        stop_server(proc)


def _fetch(url: str) -> Optional[str]:
    """Server-rendered HTML, so a Playwright-less run still returns something."""
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return response.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as e:
        logger.debug("Could not fetch %s: %s", url, e)
        return None

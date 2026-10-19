"""
Dark mode across the example projects: no visible text below 3:1.

test_dark_mode.py checks the page shell. That passed while 11 of 16 example
pages had unreadable text, because the component stylesheets and the display
and schema generators set light background literals that the dark tokens never
reached: a document's own paragraphs rendered #fafafa on #ffffff. So this
serves one example per display and schema family and measures every visible
element that holds text against the nearest opaque background behind it.

Each example runs as `potato start --debug --debug-phase annotation`, which
signs in a debug user and skips the phases, from the repository root (the
examples resolve task_dir against it).
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

EXAMPLES = [
    "examples/advanced/all-annotation-types",     # the common schemas
    "examples/image/document-bbox",               # document display
    "examples/agent-traces/web-agent-review",     # web agent trace display
    "examples/agent-traces/agent-scorecard",      # agent scorecard schema
    "examples/audio/tiered-annotation",           # tiered audio
    "examples/audio/audio-dialogue-sporc",        # audio dialogue + span links
    "examples/video/mask-propagation",            # video tracking
    "examples/advanced/annotation-telemetry",     # image toolbar
    "examples/span/coreference",                  # coreference
    "examples/conversation/convokit-tree",        # conversation tree
]

AUDIT = r"""
() => {
  function parse(c){const m=c.match(/rgba?\(([^)]+)\)/); if(!m) return null;
    const p=m[1].split(',').map(x=>parseFloat(x)); return {r:p[0],g:p[1],b:p[2],a:p.length>3?p[3]:1};}
  function lum(c){const f=v=>{v/=255;return v<=0.03928?v/12.92:Math.pow((v+0.055)/1.055,2.4)};
    return 0.2126*f(c.r)+0.7152*f(c.g)+0.0722*f(c.b);}
  function bgOf(el){while(el){const c=parse(getComputedStyle(el).backgroundColor);
    if(c&&c.a>0.5) return c; el=el.parentElement;} return {r:255,g:255,b:255,a:1};}
  const low=[];
  for(const el of document.querySelectorAll('body *')){
    const r=el.getBoundingClientRect(); if(r.width<2||r.height<2) continue;
    const cs=getComputedStyle(el);
    if(cs.visibility==='hidden'||cs.display==='none'||parseFloat(cs.opacity)===0) continue;
    const fg=parse(cs.color); if(!fg||fg.a<0.05) continue;   // e.g. a PDF text layer
    if(![...el.childNodes].some(n=>n.nodeType===3&&n.textContent.trim())) continue;
    const bg=bgOf(el); const a=lum(fg), b=lum(bg);
    const ratio=(Math.max(a,b)+0.05)/(Math.min(a,b)+0.05);
    if(ratio<3) low.push(`${ratio.toFixed(2)} ${el.tagName.toLowerCase()}.${
      String(el.className).trim().split(/\s+/).slice(0,2).join('.')} ${cs.color} on rgb(${bg.r},${bg.g},${bg.b})`);
  }
  return [...new Set(low)];
}
"""


def _free_port():
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@pytest.fixture
def example_url(request):
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "potato/flask_server.py", "start",
         f"{request.param}/config.yaml", "-p", str(port),
         "--debug", "--debug-phase", "annotation"],
        cwd=REPO, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                socket.create_connection(("localhost", port), timeout=1).close()
                break
            except OSError:
                time.sleep(0.5)
        else:
            pytest.fail(f"{request.param} did not start")
        yield f"http://localhost:{port}/annotate"
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.mark.playwright
@pytest.mark.parametrize("example_url", EXAMPLES, indirect=True,
                         ids=[e.split("/")[-1] for e in EXAMPLES])
def test_no_unreadable_text_in_dark_mode(browser_instance, example_url):
    context = browser_instance.new_context(viewport={"width": 1280, "height": 900},
                                           color_scheme="dark")
    try:
        page = context.new_page()
        page.goto(example_url, wait_until="load", timeout=60_000)
        page.wait_for_timeout(2000)
        assert page.evaluate("document.documentElement.dataset.theme") == "dark"
        low = page.evaluate(AUDIT)
        assert not low, "text below 3:1 in dark mode:\n" + "\n".join(low[:15])
    finally:
        context.close()


# Canvases paint resolved colours, which the DOM check above cannot see and
# light-dark() cannot reach: the tiered-annotation tier rows stayed a white
# band on the dark page. Each visible canvas is screenshotted and its mean
# brightness must sit in the dark half. A light canvas averages about 245.
CANVAS_EXAMPLES = [
    "examples/audio/tiered-annotation",
    "examples/agent-traces/world-model-rollouts",
    "examples/embodied/lerobot-episode",
]


@pytest.mark.playwright
@pytest.mark.parametrize("example_url", CANVAS_EXAMPLES, indirect=True,
                         ids=[e.split("/")[-1] for e in CANVAS_EXAMPLES])
def test_canvases_are_dark_in_dark_mode(browser_instance, example_url):
    import io

    from PIL import Image, ImageStat

    context = browser_instance.new_context(viewport={"width": 1280, "height": 900},
                                           color_scheme="dark")
    try:
        page = context.new_page()
        page.goto(example_url, wait_until="load", timeout=60_000)
        page.wait_for_timeout(2500)
        measured = []
        for canvas in page.locator("canvas").all():
            box = canvas.bounding_box()
            if not box or box["width"] < 40 or box["height"] < 20 or not canvas.is_visible():
                continue
            image = Image.open(io.BytesIO(canvas.screenshot())).convert("L")
            measured.append(ImageStat.Stat(image).mean[0])
        assert measured, "no visible canvas to measure"
        assert max(measured) < 128, f"light canvas in dark mode, mean brightness {measured}"
    finally:
        context.close()


@pytest.mark.playwright
@pytest.mark.parametrize("example_url", CANVAS_EXAMPLES[:1], indirect=True,
                         ids=["tiered-annotation"])
def test_canvases_repaint_when_the_theme_flips(browser_instance, example_url):
    import io

    from PIL import Image, ImageStat

    context = browser_instance.new_context(viewport={"width": 1280, "height": 900},
                                           color_scheme="dark")
    try:
        page = context.new_page()
        page.goto(example_url, wait_until="load", timeout=60_000)
        page.wait_for_timeout(2500)

        def brightest():
            values = []
            for canvas in page.locator("canvas").all():
                box = canvas.bounding_box()
                if box and box["width"] >= 40 and box["height"] >= 20 and canvas.is_visible():
                    image = Image.open(io.BytesIO(canvas.screenshot())).convert("L")
                    values.append(ImageStat.Stat(image).mean[0])
            return max(values)

        assert brightest() < 128
        page.locator("[data-theme-toggle]").click()          # to light
        page.wait_for_timeout(300)
        assert brightest() > 200
    finally:
        context.close()

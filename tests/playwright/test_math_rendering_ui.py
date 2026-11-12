"""
Math rendering (top-level ``math`` block, KaTeX) in a real browser.

What is checked, each against the page rather than the config:

* math in a text display field and in process_reward steps renders to KaTeX
  output, ``\\$`` stays a literal dollar sign, and "$5 and $7" stays text;
* a span-target field keeps its LaTeX source, and a real mouse drag over it
  makes a span whose offsets count the source characters;
* ``\\href{javascript:...}``, ``\\url``, ``\\htmlClass``, ``\\includegraphics``
  and HTML typed inside math produce no link, image, class or script;
* the legacy item text renders when no text-selection scheme reads it, and is
  left alone when one does;
* process_reward clicks on a rendered step survive Next / Previous;
* dark mode text colour, no console errors, and no sideways scroll on a
  phone-width viewport.

Screenshots go to the scratch directory named by POTATO_SCREENSHOT_DIR when it
is set, so they can be looked at; nothing is asserted from them.
"""

import json
import os

import pytest

pytest.importorskip("playwright.sync_api")

from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.mobile import layout_problems  # noqa: E402
from tests.helpers.port_manager import find_free_port  # noqa: E402
from tests.helpers.test_utils import (  # noqa: E402
    create_test_config,
    create_test_data_file,
    create_test_directory,
)

pytestmark = pytest.mark.playwright

SHOT_DIR = os.environ.get("POTATO_SCREENSHOT_DIR")

SPAN_SOURCE = "We know $a^2+b^2=c^2$ holds for right triangles."

ITEMS = [
    {
        "id": "m1",
        "statement": ("Let $f(x) = x^2$ on $\\RR$, so $$\\int_0^1 f(x)\\,dx = \\tfrac13.$$ "
                      "A pen costs \\$5 and a book costs \\$7; $5 and $7 stay prices."),
        "html_statement": "<p>Plain <b>HTML</b> with $e^{i\\pi} + 1 = 0$.</p>",
        "annotated": SPAN_SOURCE,
        "steps": ["First, $\\alpha = 1$.", "Then $$\\beta = \\frac{1}{2}.$$", "So $\\alpha > \\beta$."],
    },
    {
        "id": "m2",
        "statement": ("A $\\href{javascript:window.__pwned=1}{click me}$ "
                      "B $\\url{javascript:window.__pwned=2}$ "
                      "C $\\htmlClass{pwned}{x}$ "
                      "D $\\includegraphics{x.png}$ "
                      "E $x<img src=x onerror=\"window.__pwned=3\">$ "
                      "F $\\text{<script>window.__pwned=4</script>}$ "
                      "G $y = 2$ "
                      # Not math: closes the page's JSON data element if the
                      # server writes item data into it unescaped.
                      "</script><script>window.__pwned=8</script>"),
        "html_statement": ("<p>H $\\href{javascript:window.__pwned=5}{x}$ and "
                           "<a href=\"javascript:window.__pwned=6\">a link</a> "
                           "<b onmouseover=\"window.__pwned=7\">bold</b> I $z^2$</p>"),
        "annotated": "Nothing to see: $q$.",
        "steps": ["Only $\\gamma$."],
    },
]

INSTANCE_DISPLAY = {
    "fields": [
        {"key": "statement", "type": "text", "label": "Statement"},
        {"key": "html_statement", "type": "html", "label": "HTML statement"},
        {"key": "annotated", "type": "text", "label": "Annotate", "span_target": True},
    ],
}

SCHEMES = [
    {"annotation_type": "span", "name": "terms", "description": "Mark terms",
     "labels": ["term"]},
    {"annotation_type": "process_reward", "name": "steps_grade",
     "description": "Grade the steps", "steps_key": "steps", "mode": "per_step"},
]


def _start(name, schemes, items, **kwargs):
    test_dir = create_test_directory(name)
    data_file = create_test_data_file(test_dir, items, filename="math.jsonl")
    config_file = create_test_config(test_dir, schemes, data_files=[data_file], **kwargs)
    srv = FlaskTestServer(port=find_free_port(), config_file=config_file)
    if not srv.start():
        pytest.fail(f"Failed to start {name} server")
    return srv


@pytest.fixture(scope="module")
def server():
    srv = _start(
        "pw_math_rendering", SCHEMES, ITEMS,
        # text_key feeds the hidden legacy #text-content, which sanitizes rather
        # than escapes; the payload field stays out of it.
        item_properties={"id_key": "id", "text_key": "annotated"},
        additional_config={
            "instance_display": INSTANCE_DISPLAY,
            "math": {"enabled": True, "macros": {"\\RR": "\\mathbb{R}"}},
        })
    yield srv
    srv.stop()


LEGACY_ITEMS = [{"id": "l1", "text": "Legacy $x^{2}$ and \\$3."},
                {"id": "l2", "text": "Second $y$."}]
RADIO = {"annotation_type": "radio", "name": "ok", "description": "OK?", "labels": ["yes", "no"]}


def _login(page, server, user):
    req = page.context.request
    req.post(f"{server.base_url}/register", form={"email": user, "pass": "pw"})
    req.post(f"{server.base_url}/auth", form={"email": user, "pass": "pw"})


def _collect_console(page):
    problems = []
    page.on("console", lambda m: problems.append(f"{m.type}: {m.text}")
            if m.type == "error" else None)
    page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
    return problems


def _open(page, server):
    page.goto(f"{server.base_url}/annotate")
    page.wait_for_selector(".prm-step-card .potato-math", timeout=15000)


def _field(page, key):
    return page.locator(f'.display-field[data-field-key="{key}"]')


def _shot(page, name):
    if SHOT_DIR:
        os.makedirs(SHOT_DIR, exist_ok=True)
        page.screenshot(path=os.path.join(SHOT_DIR, name), full_page=True)


def test_math_renders_and_dollars_stay_text(server, page):
    problems = _collect_console(page)
    _login(page, server, "math_render")
    _open(page, server)

    statement = _field(page, "statement")
    rendered = statement.locator(".potato-math")
    # f(x) = x^2, \RR, the display integral.
    assert rendered.count() == 3
    assert statement.locator(".potato-math-display .katex-display").count() == 1
    # KaTeX produced its HTML and MathML trees, with the macro expanded.
    assert statement.locator(".katex-html").count() == 3
    assert statement.locator("annotation[encoding='application/x-tex']").first.text_content() == "f(x) = x^2"
    assert "mathbb" not in statement.inner_text()
    # \$5 and \$7 are literal dollars; "$5 and $7" is not math.
    assert statement.locator(".potato-math-literal").count() == 2
    text = statement.inner_text()
    assert "A pen costs $5 and a book costs $7; $5 and $7 stay prices." in text
    # The glyphs are visible, not zero-sized.
    box = rendered.nth(2).bounding_box()
    assert box and box["width"] > 40 and box["height"] > 10

    # Steps rendered in the browser by process_reward get math too.
    steps = page.locator(".prm-step-text")
    assert steps.count() == 3
    assert steps.nth(0).locator(".potato-math").count() == 1
    assert steps.nth(1).locator(".potato-math-display").count() == 1
    assert page.locator(".potato-math-error").count() == 0
    _shot(page, "math_light.png")
    assert not problems, problems


def test_span_target_keeps_source_and_spans_count_source_chars(server, page):
    _login(page, server, "math_span")
    _open(page, server)
    target = page.locator("#text-content-annotated")
    assert target.locator(".potato-math").count() == 0
    assert target.inner_text().strip().startswith(SPAN_SOURCE)
    page.wait_for_function("() => window.spanManager && window.spanManager.fieldStrategies "
                           "&& window.spanManager.fieldStrategies['annotated']", timeout=15000)

    page.locator('#terms_term').click()
    # Drag over "$a^2+b^2=c^2$" with the mouse.
    start = SPAN_SOURCE.index("$")
    end = SPAN_SOURCE.index("$", start + 1) + 1
    box = page.evaluate(
        """([s, e]) => {
            const host = document.getElementById('text-content-annotated');
            const walker = document.createTreeWalker(host, NodeFilter.SHOW_TEXT);
            let n; while ((n = walker.nextNode()) && n.nodeValue.indexOf('$a^2') < 0) {}
            const base = n.nodeValue.indexOf('We know');
            const r1 = document.createRange(); r1.setStart(n, base + s); r1.setEnd(n, base + s + 1);
            const r2 = document.createRange(); r2.setStart(n, base + e - 1); r2.setEnd(n, base + e);
            const a = r1.getBoundingClientRect(), b = r2.getBoundingClientRect();
            return {x1: a.left + 1, y1: a.top + a.height / 2, x2: b.right - 1, y2: b.top + b.height / 2};
        }""", [start, end])
    page.mouse.move(box["x1"], box["y1"])
    page.mouse.down()
    page.mouse.move(box["x2"], box["y2"], steps=8)
    page.mouse.up()
    page.wait_for_function("() => window.spanManager.getSpans().length > 0", timeout=5000)
    spans = page.evaluate("() => window.spanManager.getSpans()")
    assert len(spans) == 1
    span = spans[0]
    # Offsets index the LaTeX source: "$a^2+b^2=c^2$" is 13 code points.
    assert (span["start"], span["end"]) == (start, end)
    assert SPAN_SOURCE[span["start"]:span["end"]] == "$a^2+b^2=c^2$"


def test_untrusted_commands_and_html_do_nothing(server, page):
    problems = _collect_console(page)
    missing = []
    page.on("response", lambda r: missing.append(r.url) if r.status == 404 else None)
    _login(page, server, "math_xss")
    _open(page, server)
    page.click("#next-btn")
    page.wait_for_selector(".potato-math[data-tex='y = 2'] .katex", timeout=15000)
    page.wait_for_timeout(300)

    found = page.evaluate("""() => {
        const area = document.querySelector('.instance-area');
        const maths = [...area.querySelectorAll('.potato-math')];
        return {
            pwned: window.__pwned === undefined ? null : window.__pwned,
            links: maths.reduce((n, m) => n + m.querySelectorAll('a, [href]').length, 0),
            images: maths.reduce((n, m) => n + m.querySelectorAll('img, image').length, 0),
            scripts: maths.reduce((n, m) => n + m.querySelectorAll('script').length, 0),
            pwnedClass: area.querySelectorAll('.pwned').length,
            handlers: maths.reduce((n, m) => n + [...m.querySelectorAll('*')].filter(
                el => [...el.attributes].some(a => a.name.startsWith('on'))).length, 0),
            count: maths.length,
            html_links: [...area.querySelectorAll('.display-type-html a')].map(a => a.getAttribute('href')),
        };
    }""")
    assert found["pwned"] is None
    assert found["links"] == 0 and found["images"] == 0 and found["scripts"] == 0
    assert found["handlers"] == 0 and found["pwnedClass"] == 0
    # The sanitizer already removed the javascript: link in the HTML field.
    assert all(not (h or "").lower().startswith("javascript") for h in found["html_links"])
    # G and I still render: one bad expression does not stop the rest.
    statement = _field(page, "statement")
    assert statement.locator(".potato-math[data-tex='y = 2'] .katex-html").count() == 1
    assert _field(page, "html_statement").locator(".potato-math[data-tex='z^2'] .katex").count() == 1
    # The HTML typed inside math is shown as characters.
    assert "<img" in statement.inner_text() or statement.locator(
        ".potato-math-error").filter(has_text="<img").count() == 1
    assert not problems, (problems, missing)


def test_step_grade_survives_navigation(server, page):
    _login(page, server, "math_persist")
    _open(page, server)
    card = page.locator(".prm-step-card").nth(1)
    card.locator(".prm-btn-correct").click()
    page.wait_for_timeout(1600)        # autosave debounce
    page.click("#next-btn")
    page.wait_for_selector(".prm-step-card", timeout=15000)
    page.click("#prev-btn")
    page.wait_for_selector(".prm-step-card .potato-math", timeout=15000)
    card = page.locator(".prm-step-card").nth(1)
    assert "prm-correct" in (card.get_attribute("class") or "")
    assert card.locator(".prm-btn-correct.selected").count() == 1
    # The rendered math is back too, on a fresh page.
    assert card.locator(".potato-math-display .katex").count() == 1

    saved = page.context.request.get(
        f"{server.base_url}/get_annotations?instance_id=m1").json()
    blob = json.dumps(saved)
    assert "steps_grade" in blob


def test_dark_mode_and_phone_width(server, page):
    _login(page, server, "math_dark")
    page.emulate_media(color_scheme="dark")
    _open(page, server)
    colours = page.evaluate("""() => {
        const m = document.querySelector('.display-field[data-field-key="statement"] .katex');
        const bg = getComputedStyle(document.body).backgroundColor;
        return {fg: getComputedStyle(m).color, bg};
    }""")

    def lum(rgb):
        parts = [int(float(x)) for x in rgb[rgb.index("(") + 1:rgb.index(")")].split(",")[:3]]
        def ch(c):
            c = c / 255
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        r, g, b = (ch(c) for c in parts)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    hi, lo = sorted((lum(colours["fg"]), lum(colours["bg"])), reverse=True)
    assert (hi + 0.05) / (lo + 0.05) >= 4.5, colours
    _shot(page, "math_dark.png")

    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(300)
    assert not layout_problems(page, reachable=["#next-btn"])
    _shot(page, "math_phone_dark.png")


# The servers below are started one at a time: FlaskTestServer runs in this
# process and every server shares the config singleton, so two live servers
# would both answer with the config of whichever started last.

def test_legacy_item_text_renders_without_a_span_scheme(page):
    srv = _start("pw_math_legacy_plain", [RADIO], LEGACY_ITEMS,
                 additional_config={"math": {"enabled": True}})
    try:
        _login(page, srv, "math_legacy_plain")
        page.goto(f"{srv.base_url}/annotate")
        page.wait_for_selector("#text-content .potato-math .katex", timeout=15000)
        tc = page.locator("#text-content")
        assert tc.locator(".potato-math").count() == 1
        assert tc.locator(".potato-math-literal").count() == 1
        assert "and $3." in tc.inner_text()
    finally:
        srv.stop()


def test_legacy_item_text_left_alone_with_a_span_scheme(page):
    span = {"annotation_type": "span", "name": "marks", "description": "Mark", "labels": ["m"]}
    srv = _start("pw_math_legacy_span", [RADIO, span], LEGACY_ITEMS,
                 additional_config={"math": {"enabled": True}})
    try:
        _login(page, srv, "math_legacy_span")
        page.goto(f"{srv.base_url}/annotate")
        page.wait_for_selector("#text-content", timeout=15000)
        # KaTeX is on the page and still leaves the span target alone.
        page.wait_for_function("() => window.PotatoMath && window.PotatoMath._settings()",
                               timeout=10000)
        assert page.locator("#text-content .potato-math").count() == 0
        assert "Legacy $x^{2}$ and \\$3." in page.locator("#text-content").inner_text()
    finally:
        srv.stop()


def test_math_off_loads_nothing(page):
    """Without `math.enabled`, the page loads no KaTeX and shows source."""
    srv = _start("pw_math_off",
                 [{"annotation_type": "radio", "name": "ok", "description": "OK?",
                   "labels": ["yes", "no"]}],
                 [{"id": "o1", "text": "Costs $x^2$ dollars."}, {"id": "o2", "text": "b"}])
    try:
        _login(page, srv, "math_off")
        page.goto(f"{srv.base_url}/annotate")
        page.wait_for_selector("#text-content", timeout=15000)
        assert page.locator("script[src*='katex']").count() == 0
        assert page.locator("#potato-math-config").count() == 0
        assert "Costs $x^2$ dollars." in page.locator("#text-content").inner_text()
    finally:
        srv.stop()


def test_trajectory_eval_steps_and_thoughts(page):
    scheme = {"annotation_type": "trajectory_eval", "name": "traj", "description": "Rate steps",
              "steps_key": "steps", "step_text_key": "text"}
    items = [{"id": "t1", "text": "Proof", "steps": [
        {"text": "Assume $\\sqrt{2} = p/q$ in lowest terms.",
         "thought": "Then $p^2 = 2q^2$."}]},
        {"id": "t2", "text": "b", "steps": [{"text": "$x$"}]}]
    srv = _start("pw_math_traj", [scheme], items, additional_config={"math": {"enabled": True}})
    try:
        problems = _collect_console(page)
        _login(page, srv, "math_traj")
        page.goto(f"{srv.base_url}/annotate")
        page.wait_for_selector(".traj-step-text .potato-math .katex", timeout=15000)
        assert page.locator(".traj-step-text .potato-math").count() == 1
        assert page.locator(".traj-step-thought .potato-math[data-tex='p^2 = 2q^2']").count() == 1
        # The step's own controls are untouched.
        assert page.locator(".traj-step-card .traj-correctness-btn").count() >= 2
        assert not problems, problems
    finally:
        srv.stop()


def test_dialogue_and_agent_trace_displays(page):
    turns = [{"speaker": "Student", "text": "Is $\\sum 1/n^2 = \\pi^2/6$?"},
             {"speaker": "Tutor", "text": "Yes: $$\\zeta(2) = \\frac{\\pi^2}{6}.$$"}]
    trace = [{"speaker": "Agent", "text": "Compute $2^{10}$."},
             {"speaker": "Tool", "text": "1024 (cost \\$0)"}]
    items = [{"id": "d1", "chat": turns, "trace": trace, "t": "x"},
             {"id": "d2", "chat": turns, "trace": trace, "t": "y"}]
    srv = _start("pw_math_dialogue", [RADIO], items,
                 item_properties={"id_key": "id", "text_key": "t"},
                 additional_config={
                     "math": {"enabled": True},
                     "instance_display": {"fields": [
                         {"key": "chat", "type": "dialogue", "label": "Chat"},
                         {"key": "trace", "type": "agent_trace", "label": "Trace"}]}})
    try:
        problems = _collect_console(page)
        _login(page, srv, "math_dialogue")
        page.goto(f"{srv.base_url}/annotate")
        page.wait_for_selector('.display-field[data-field-key="chat"] .potato-math .katex',
                               timeout=15000)
        chat = _field(page, "chat")
        assert chat.locator(".potato-math-inline").count() == 1
        assert chat.locator(".potato-math-display .katex-display").count() == 1
        trace_field = _field(page, "trace")
        assert trace_field.locator(".potato-math[data-tex='2^{10}']").count() == 1
        assert trace_field.locator(".potato-math-literal").count() == 1
        assert not problems, problems
    finally:
        srv.stop()


def test_cot_trace_with_inline_step_rewards(page):
    # cot_segmentation output shape: dicts with text and index.
    steps = [{"index": 0, "text": "Let $n = 2k$."}, {"index": 1, "text": "Then $$n^2 = 4k^2.$$"}]
    items = [{"id": "c1", "q": "Show $n^2$ is even.", "cot_steps": steps},
             {"id": "c2", "q": "b", "cot_steps": steps}]
    scheme = {"annotation_type": "process_reward", "name": "prm", "description": "Rate",
              "steps_key": "cot_steps", "step_text_key": "text", "mode": "per_step",
              "inline_with_trace": True}
    srv = _start("pw_math_cot", [scheme], items,
                 item_properties={"id_key": "id", "text_key": "q"},
                 additional_config={
                     "math": {"enabled": True},
                     "instance_display": {"fields": [
                         {"key": "q", "type": "text", "label": "Problem"},
                         {"key": "cot_steps", "type": "cot_trace", "label": "Reasoning"}]}})
    try:
        problems = _collect_console(page)
        _login(page, srv, "math_cot")
        page.goto(f"{srv.base_url}/annotate")
        page.wait_for_selector(".prm-step-card.prm-inline", timeout=15000)
        trace = _field(page, "cot_steps")
        page.wait_for_selector('.display-field[data-field-key="cot_steps"] .potato-math .katex',
                               timeout=15000)
        assert trace.locator(".potato-math").count() == 2
        # The inline reward controls still work on a rendered step.
        card = trace.locator(".prm-step-card.prm-inline").nth(1)
        card.locator(".prm-btn-correct").click()
        assert card.locator(".prm-btn-correct.selected").count() == 1
        assert not problems, problems
    finally:
        srv.stop()

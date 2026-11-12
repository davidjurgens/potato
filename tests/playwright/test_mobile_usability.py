"""The regular annotate page, used from a phone.

Each test drives a real example as an iPhone 13 (390x664, touch, mobile
User-Agent; see tests/helpers/mobile.py) and pins one finding from the phone
sweep in plans/mobile-usability.md: nested scrolling, the three-row header,
touch targets under 44px, the multirate table hiding columns, the "desktop
recommended" banner, keyboard hints, and span highlighting having no touch
path at all.
"""

import os
import shutil

import pytest

pytest.importorskip("playwright.sync_api")

from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.mobile import layout_problems, mobile_page  # noqa: E402
from tests.helpers.test_utils import create_test_directory  # noqa: E402

pytestmark = pytest.mark.playwright

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PHONE = "iPhone 13"


@pytest.fixture(scope="module")
def example(request):
    name = request.param
    work = os.path.join(create_test_directory("mobile_usability"),
                        name.replace("/", "__"))
    shutil.copytree(os.path.join(REPO, "examples", name), work,
                    ignore=shutil.ignore_patterns(
                        "annotation_output", "*.sqlite*", "test_config_port_*"))
    srv = FlaskTestServer(config_file=os.path.join(work, "config.yaml"))
    if not srv.start():
        pytest.fail(f"could not start {name}")
    yield srv
    srv.stop()


def on_example(*names):
    return pytest.mark.parametrize("example", names, indirect=True)


def _open(server, user="phone_user"):
    cm = mobile_page(PHONE, server.base_url)
    page = cm.__enter__()
    req = page.context.request
    req.post(f"{server.base_url}/register",
             form={"action": "signup", "email": user, "pass": "pass"})
    req.post(f"{server.base_url}/auth",
             form={"action": "login", "email": user, "pass": "pass"})
    page.goto("/annotate")
    page.wait_for_selector(".annotation-form")
    page.wait_for_timeout(600)
    return cm, page


class _Page:
    def __init__(self, server, user="phone_user"):
        self.server, self.user = server, user

    def __enter__(self):
        self.cm, page = _open(self.server, self.user)
        return page

    def __exit__(self, *exc):
        return self.cm.__exit__(*exc)


def _inner_scrollers(page):
    """Elements that scroll vertically inside the page, other than fields."""
    return page.evaluate("""() => [...document.querySelectorAll('body *')].filter(e => {
        if (e.matches('textarea, select, input')) return false;
        const s = getComputedStyle(e);
        return /(auto|scroll)/.test(s.overflowY) && e.scrollHeight > e.clientHeight + 5
               && e.getBoundingClientRect().height > 0;
    }).map(e => `${e.tagName.toLowerCase()}.${[...e.classList].slice(0, 2).join('.')} `
                + `${e.clientHeight}/${e.scrollHeight}`)""")


def _hit_size(page, selector):
    """Smallest (width, height) over every visible match: its box, grown by a
    ::before hit area when the element has one."""
    return page.evaluate("""(sel) => {
        let w = Infinity, h = Infinity;
        for (const el of document.querySelectorAll(sel)) {
            const r = el.getBoundingClientRect();
            if (!r.width || !r.height) continue;
            const b = getComputedStyle(el, '::before');
            let grow = 0;
            if (b.content !== 'none' && b.position === 'absolute') {
                grow = -2 * (parseFloat(b.top) || 0);
            }
            w = Math.min(w, r.width + grow);
            h = Math.min(h, r.height + grow);
        }
        return [w, h];
    }""", selector)


# ---------------------------------------------------------------------------
# Scrolling and space
# ---------------------------------------------------------------------------

@on_example("image/image-annotation", "classification/dialogue-classification")
def test_the_task_scrolls_with_the_page_not_inside_it(example):
    with _Page(example) as page:
        scrollers = _inner_scrollers(page)
        assert not scrollers, "nested scroll areas on a phone: " + ", ".join(scrollers)


@on_example("classification/single-choice")
def test_header_is_at_most_two_rows(example):
    with _Page(example) as page:
        height = page.evaluate(
            "document.querySelector('.potato-navbar').getBoundingClientRect().height")
        assert height <= 112, f"header is {height}px tall on a 664px screen"
        assert not layout_problems(page, [".logout-btn", "#progress-counter"])
        wraps = page.evaluate("""() => { const b = document.querySelector('.status-badge');
            return b.getBoundingClientRect().height > parseFloat(getComputedStyle(b).lineHeight) * 1.5; }""")
        assert not wraps, "the status badge wraps onto two lines"


# ---------------------------------------------------------------------------
# Touch targets
# ---------------------------------------------------------------------------

@on_example("classification/single-choice")
def test_option_rows_are_44px(example):
    with _Page(example) as page:
        w, h = _hit_size(page, ".shadcn-radio-label")
        assert h >= 44, f"radio option rows are {h}px tall"


@on_example("classification/likert")
def test_likert_targets_and_end_labels(example):
    with _Page(example) as page:
        w, h = _hit_size(page, ".shadcn-likert-button")
        assert min(w, h) >= 44, f"likert hit area is {w}x{h}px"
        inside = page.evaluate("""() => { const card = document.querySelector('.shadcn-likert-container').getBoundingClientRect();
            return [...document.querySelectorAll('.shadcn-likert-endpoint')].every(e => {
                const r = e.getBoundingClientRect(); return r.left >= card.left - 1 && r.right <= card.right + 1; }); }""")
        assert inside, "a likert end label runs outside its card"
        # And tapping the enlarged area selects.
        page.locator(".shadcn-likert-button").nth(3).tap()
        assert page.evaluate("document.querySelectorAll('.shadcn-likert-input')[3].checked")


@on_example("classification/multirate")
def test_multirate_shows_every_rating_as_a_tappable_row(example):
    with _Page(example) as page:
        assert not layout_problems(page, [])
        info = page.evaluate("""() => {
            const vw = window.innerWidth;
            const choices = [...document.querySelectorAll('tbody .shadcn-multirate-choice')];
            return {n: choices.length,
                    hidden: choices.filter(c => { const r = c.getBoundingClientRect();
                        return !r.width || r.right > vw + 1 || r.left < -1; }).length,
                    minH: Math.min(...choices.map(c => c.getBoundingClientRect().height)),
                    texts: choices.slice(0, 5).map(c => c.innerText.trim())}; }""")
        assert info["n"] and info["hidden"] == 0, info
        assert info["minH"] >= 44, info
        assert info["texts"][0], "the rating names are not shown on a phone"
        widths = page.evaluate("""() => [document.querySelector('.shadcn-multirate-table').getBoundingClientRect().width,
            document.querySelector('.annotation_schema').getBoundingClientRect().width]""")
        assert widths[0] >= widths[1] * 0.9, f"multirate uses {widths[0]}px of {widths[1]}px"
        page.locator("tbody .shadcn-multirate-choice").nth(4).tap()
        assert page.evaluate(
            "document.querySelectorAll('tbody .shadcn-multirate-radio')[4].checked")


@on_example("classification/ranking")
def test_ranking_arrows_are_44px_and_reorder(example):
    with _Page(example) as page:
        w, h = _hit_size(page, ".ranking-down")
        assert min(w, h) >= 44, f"ranking arrows are {w}x{h}px"
        first = page.locator(".ranking-item .ranking-label").first.inner_text()
        page.locator(".ranking-down").first.tap()
        assert page.locator(".ranking-item .ranking-label").nth(1).inner_text() == first


@on_example("classification/slider")
def test_slider_has_a_44px_touch_band(example):
    with _Page(example) as page:
        w, h = _hit_size(page, ".custom-slider-input")
        assert h >= 44, f"the slider's touch band is {h}px tall"


# ---------------------------------------------------------------------------
# Banner and desktop-only chrome
# ---------------------------------------------------------------------------

@on_example("classification/pairwise-comparison")
def test_no_desktop_warning_on_a_touch_friendly_task(example):
    with _Page(example) as page:
        page.wait_for_timeout(800)
        assert page.locator("#device-routing-banner").count() == 0
        # Keyboard hints are hidden on a phone.
        assert page.evaluate("""() => [...document.querySelectorAll('.pairwise-tile-shortcut')]
            .every(e => getComputedStyle(e).display === 'none')""")


@on_example("span/span-linking")
def test_desktop_warning_still_shows_where_touch_is_unverified_and_scrolls_away(example):
    with _Page(example) as page:
        page.wait_for_selector("#device-routing-banner")
        position = page.evaluate(
            "getComputedStyle(document.getElementById('device-routing-banner')).position")
        assert position not in ("sticky", "fixed")


@on_example("image/image-annotation")
def test_no_keyboard_notice_on_a_phone(example):
    with _Page(example) as page:
        page.wait_for_timeout(800)
        assert page.locator(".keybinding-notice").count() == 0


@on_example("image/image-annotation")
def test_image_toolbar_is_touch_sized(example):
    with _Page(example) as page:
        for sel in (".label-btn", ".zoom-btn", ".edit-btn"):
            w, h = _hit_size(page, f".image-annotation-container {sel}")
            assert min(w, h) >= 44, f"{sel} is {w}x{h}px"
        w, h = _hit_size(page, ".image-annotation-container .label-visibility-toggle")
        assert min(w, h) >= 36, f"visibility toggle is {w}x{h}px"


# ---------------------------------------------------------------------------
# Span highlighting by touch
# ---------------------------------------------------------------------------

@on_example("span/span-labeling")
def test_a_span_can_be_highlighted_by_touch(example):
    with _Page(example) as page:
        page.locator(".shadcn-span-label").first.tap()
        # A long-press selection: select the first word of the text.
        page.evaluate("""() => {
            const root = document.getElementById('instance-text');
            const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT,
                {acceptNode: n => n.textContent.trim().length > 3 ? 1 : 3});
            const node = walker.nextNode();
            const start = node.textContent.search(/\\S/);
            const range = document.createRange();
            range.setStart(node, start);
            range.setEnd(node, start + 4);
            const sel = window.getSelection();
            sel.removeAllRanges(); sel.addRange(range);
        }""")
        button = page.locator("#span-touch-highlight")
        button.wait_for(state="visible", timeout=3000)
        assert "Highlight as" in button.inner_text()
        before = page.evaluate("window.spanManager.getSpans ? window.spanManager.getSpans().length : document.querySelectorAll('.span-overlay-pure, .span-overlay').length")
        button.tap()
        page.wait_for_timeout(500)
        after = page.evaluate("window.spanManager.getSpans ? window.spanManager.getSpans().length : document.querySelectorAll('.span-overlay-pure, .span-overlay').length")
        assert after == before + 1, f"spans {before} -> {after}"
        assert button.is_hidden()

        # Stored, not just drawn: the server has the span.
        instance_id = page.evaluate("document.getElementById('instance_id').value")
        page.wait_for_timeout(1500)  # autosave debounce
        stored = page.context.request.get(
            f"{example.base_url}/get_annotations?instance_id={instance_id}").json()
        spans = stored.get("span_annotations") or {}
        assert any("certain" in key for key in spans), stored

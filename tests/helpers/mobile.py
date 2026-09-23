"""Open Potato pages as a phone or tablet, and check they still fit.

Resizing a desktop browser is not a mobile test. It keeps the desktop
User-Agent, so the server never routes the phone to ``/pocket``
(``routes.py`` ``annotate()``), and it keeps a mouse, so ``device-routing.js``
never takes its touch branch. macOS Chrome also refuses to make a window
narrower than roughly 500px. Playwright's device descriptors set all four at
once -- viewport, User-Agent, touch and pixel density -- which is what a phone
actually sends.

Usage::

    from tests.helpers.mobile import PHONES, mobile_page, layout_problems

    with mobile_page("iPhone 13", server.base_url) as page:
        page.goto(server.base_url + "/adjudicate")
        assert not layout_problems(page, reachable=[".logout-btn"])

``layout_problems`` returns a list of human-readable findings rather than a
bool, so a failing test says which element pushed the page sideways.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Dict, Iterator, List, Optional, Sequence

#: The two phones every mobile test runs on: the narrowest common iPhone
#: viewport and a typical Android one. Names are Playwright device keys.
PHONES = ("iPhone 13", "Pixel 7")

#: A portrait tablet, for pages that should keep a side-by-side layout.
TABLET = "iPad (gen 7)"


@contextmanager
def mobile_page(device: str, base_url: Optional[str] = None,
                extra_headers: Optional[Dict[str, str]] = None,
                headless: bool = True) -> Iterator["object"]:
    """A Playwright page emulating ``device``.

    ``extra_headers`` is sent on every request, which is how a test reaches an
    admin page: ``{"X-API-Key": server.admin_api_key}``. The context's request
    client shares cookies with the page, so a test can log in with
    ``page.context.request.post(...)`` before navigating.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            options = dict(p.devices[device])
            if base_url:
                options["base_url"] = base_url
            if extra_headers:
                options["extra_http_headers"] = dict(extra_headers)
            context = browser.new_context(**options)
            try:
                yield context.new_page()
            finally:
                context.close()
        finally:
            browser.close()


_PROBLEMS_JS = r"""
([reachable, vw]) => {
    const out = [];
    const doc = document.documentElement;
    if (doc.scrollWidth > vw + 1) {
        // Name the widest offenders, deepest first, so the message points at
        // the element to fix rather than at <body>.
        const wide = [];
        for (const el of document.body.querySelectorAll('*')) {
            const r = el.getBoundingClientRect();
            if (r.width === 0 || r.height === 0) continue;
            if (r.right > vw + 1) {
                const style = getComputedStyle(el);
                if (style.position === 'fixed' && r.left >= vw) continue;
                let clipped = false;
                for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) {
                    const s = getComputedStyle(a);
                    if (/(auto|scroll|hidden|clip)/.test(s.overflowX)) { clipped = true; break; }
                }
                if (!clipped) wide.push({el, right: r.right});
            }
        }
        const leaves = wide.filter(w => !wide.some(o => o !== w && w.el.contains(o.el)));
        const describe = (el) => {
            let s = el.tagName.toLowerCase();
            if (el.id) s += '#' + el.id;
            if (el.classList.length) s += '.' + [...el.classList].slice(0, 3).join('.');
            return s;
        };
        out.push(`page scrolls sideways: ${doc.scrollWidth}px wide in a ${vw}px viewport` +
                 (leaves.length ? `; widest: ${leaves.slice(0, 4).map(w => describe(w.el) +
                 ' (right ' + Math.round(w.right) + ')').join(', ')}` : ''));
    }
    for (const sel of reachable) {
        const el = document.querySelector(sel);
        if (!el) { out.push(`${sel}: not on the page`); continue; }
        const r = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        if (r.width === 0 || r.height === 0 || style.visibility === 'hidden' || style.display === 'none') {
            out.push(`${sel}: not visible`);
        } else if (r.left < -1 || r.right > vw + 1) {
            out.push(`${sel}: off-screen horizontally (left ${Math.round(r.left)}, right ${Math.round(r.right)}, viewport ${vw})`);
        }
    }
    return out;
}
"""


def layout_problems(page, reachable: Sequence[str] = ()) -> List[str]:
    """What is wrong with the current page at this device's width, or [].

    Measured against the DEVICE width, not ``window.innerWidth``. A mobile
    browser whose content overflows zooms out to fit it, and the layout
    viewport -- ``innerWidth`` -- grows to the content's width, so a check
    against it compares the page with itself and passes. That is how the first
    version of this helper let a 599px-wide adjudication page through on a
    390px phone.

    Two checks:

    * the page must not scroll sideways -- the document may be no wider than
      the viewport. Content inside a container that scrolls or clips on its
      own (a wide table in an ``overflow-x: auto`` wrapper) is allowed.
    * every selector in ``reachable`` must exist, be visible, and sit within
      the viewport horizontally. Vertical position is not checked: scrolling
      down to Submit is fine, scrolling sideways to Logout is not.
    """
    width = (page.viewport_size or {}).get("width")
    if not width:
        width = page.evaluate("screen.width")
    return page.evaluate(_PROBLEMS_JS, [list(reachable), width])

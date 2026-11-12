"""
Dark mode on annotator pages, in a real browser.

What is checked is what an annotator sees: the theme the page paints with,
the colours of the surfaces they read on, and whether their choice survives
Next, Previous and a reload. The theme is decided by an inline script before
the first paint (templates/_theme_head.html), so none of this exists outside
a browser.
"""

import pytest

from tests.playwright.test_base import BasePlaywrightTest

SCHEMES = [{"annotation_type": "radio", "name": "sentiment",
            "description": "Sentiment", "labels": ["positive", "negative"]}]


def _luminance(css_rgb):
    parts = [float(x) for x in css_rgb[css_rgb.index("(") + 1:-1].split(",")[:3]]

    def channel(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(v) for v in parts)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(fg, bg):
    hi, lo = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _theme(page):
    return page.evaluate("document.documentElement.dataset.theme")


def _surfaces(page):
    return page.evaluate("""() => {
        const card = getComputedStyle(document.querySelector('#task_layout'));
        const legend = getComputedStyle(document.querySelector('.shadcn-radio-title, legend'));
        return {body: getComputedStyle(document.body).backgroundColor,
                card: card.backgroundColor, legend: legend.color};
    }""")


@pytest.fixture
def dark_os_page(browser_instance):
    context = browser_instance.new_context(viewport={"width": 1280, "height": 900},
                                           color_scheme="dark")
    page = context.new_page()
    yield page
    context.close()


@pytest.fixture(scope="module")
def forced_light_server():
    from tests.playwright.conftest import _make_server
    srv = _make_server(SCHEMES, extra_config={"ui": {"theme": "light"}})
    yield srv
    srv.stop()


@pytest.mark.playwright
class TestDarkMode(BasePlaywrightTest):

    def test_a_dark_os_gets_a_dark_page_that_reads(self, dark_os_page, server):
        page = dark_os_page
        self.register_and_login(page, server)
        assert _theme(page) == "dark"
        colours = _surfaces(page)
        assert _luminance(colours["body"]) < 0.02
        # The card was hard-coded white; text on it then vanished.
        assert _luminance(colours["card"]) < 0.05
        assert _contrast(colours["legend"], colours["card"]) >= 7

    def test_a_light_os_gets_the_light_page(self, page, server):
        self.register_and_login(page, server)
        assert _theme(page) == "light"
        assert _luminance(_surfaces(page)["card"]) > 0.9

    def test_the_annotators_choice_survives_navigation_and_reload(self, dark_os_page,
                                                                  server):
        page = dark_os_page
        self.register_and_login(page, server)
        toggle = page.locator("[data-theme-toggle]")
        assert toggle.get_attribute("aria-pressed") == "true"
        toggle.click()
        assert _theme(page) == "light"
        self.click_next(page)
        page.wait_for_selector("#main-content", state="visible")
        assert _theme(page) == "light"
        self.click_prev(page)
        page.wait_for_selector("#main-content", state="visible")
        assert _theme(page) == "light"
        page.reload()
        assert _theme(page) == "light"
        assert page.locator("[data-theme-toggle]").get_attribute("aria-pressed") == "false"

    def test_the_toggle_works_from_the_keyboard(self, page, server):
        self.register_and_login(page, server)
        toggle = page.locator("[data-theme-toggle]")
        toggle.focus()
        page.keyboard.press("Enter")
        assert _theme(page) == "dark"
        assert page.evaluate("getComputedStyle(document.activeElement).outlineStyle") == "solid"

    def test_until_a_choice_the_page_follows_the_os(self, dark_os_page, server):
        page = dark_os_page
        self.register_and_login(page, server)
        page.emulate_media(color_scheme="light")
        page.wait_for_function("document.documentElement.dataset.theme === 'light'")
        page.locator("[data-theme-toggle]").click()          # chooses dark
        page.emulate_media(color_scheme="light")
        page.wait_for_timeout(200)
        assert _theme(page) == "dark"

    def test_the_login_page_follows_the_theme_and_has_the_toggle(self, dark_os_page,
                                                                 server):
        page = dark_os_page
        page.goto(f"{server.base_url}/")
        assert _theme(page) == "dark"
        assert page.locator("[data-theme-toggle]").is_visible()
        card = page.evaluate(
            "getComputedStyle(document.querySelector('.potato-page-card')).backgroundColor")
        assert _luminance(card) < 0.05

    # Last on purpose: test servers run in-process and share one config, so
    # once this server starts, the default server above renders with
    # ui.theme: light too.
    def test_a_study_can_force_one_theme(self, dark_os_page, forced_light_server):
        page = dark_os_page
        page.add_init_script("localStorage.setItem('potato-theme', 'dark')")
        self.register_and_login(page, forced_light_server)
        assert _theme(page) == "light"
        assert page.locator("[data-theme-toggle]").count() == 0

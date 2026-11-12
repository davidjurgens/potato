"""
The two structured shapes a pairwise scheme accepts, driven in a browser.

Audit 25: only the regex-parse path worked. `items_key` pointing at a field of
its own, and a {left, right} pair on the item, both rendered two label buttons
and no candidates at all -- the text an annotator is supposed to compare was
nowhere on the page, and the config validated.

The cause was a load-order dependency. The only code that consulted
`items_key` read `window.currentInstanceData`, which is assigned in exactly one
place: inside `populateDynamicSchemaContent`, for the dynamic-schema family. A
pairwise-only page never ran that function at all, and a page that did ran the
pairwise setup first. The item is on the page the whole time in
<script id="instance_data">.

The existing coverage in test_pairwise_content.py cannot see this: it sets
`text_key` and `items_key` to the same field with `list_as_text`, so the
rendered text carries "A. ... B. ..." and the regex path answers.

These assertions look for the candidate STRINGS. Counting boxes passes on two
empty ones.
"""

import time
import unittest

import pytest
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    cleanup_test_directory,
    create_test_config,
    create_test_data_file,
    create_test_directory,
)


# Distinctive enough that finding them in the page body cannot be an accident.
LEFT_TEXT = "ZQLEFTCANDIDATE the first thing to compare"
RIGHT_TEXT = "ZQRIGHTCANDIDATE the second thing to compare"
PAIR_LEFT = "ZQLEFTKEY the left-hand answer"
PAIR_RIGHT = "ZQRIGHTKEY the right-hand answer"


class TestPairwiseStructuredShapes(unittest.TestCase):
    """items_key and {left, right}, each on a page with nothing else."""

    @classmethod
    def setUpClass(cls):
        schemes = [{
            "annotation_type": "pairwise",
            "name": "preference",
            "description": "Which is better?",
            "mode": "binary",
            "items_key": "candidates",
            "labels": ["A", "B"],
        }]
        data = [
            # `text_key` is `prompt`, so the rendered text holds no candidates
            # and none of the text-parsing methods can answer.
            {"id": "1", "prompt": "Which reply is better?",
             "candidates": [LEFT_TEXT, RIGHT_TEXT]},
            {"id": "2", "prompt": "Pick a side.",
             "left": PAIR_LEFT, "right": PAIR_RIGHT},
        ]

        port = find_free_port(preferred_port=9878)
        cls.test_dir = create_test_directory("audit25_pairwise_shapes")
        cls.data_file = create_test_data_file(cls.test_dir, data)
        cls.config_file = create_test_config(
            cls.test_dir, schemes, data_files=[cls.data_file], port=port,
            item_properties={"id_key": "id", "text_key": "prompt"},
            user_config={"allow_all_users": True, "users": []},
        )

        cls.server = FlaskTestServer(port=port, debug=False,
                                     config_file=cls.config_file)
        assert cls.server.start_server(), "Failed to start Flask server"
        cls.server._wait_for_server_ready(timeout=15)

        options = ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1400,1000")
        cls.driver = webdriver.Chrome(options=options)
        cls.driver.implicitly_wait(5)
        cls._login()

    @classmethod
    def _login(cls):
        cls.driver.get(f"{cls.server.base_url}/")
        WebDriverWait(cls.driver, 10).until(
            EC.presence_of_element_located((By.NAME, "email")))
        cls.driver.find_element(By.NAME, "email").send_keys("pairshapes")
        try:
            cls.driver.find_element(By.NAME, "pass").send_keys("pw")
        except Exception:
            pass
        cls.driver.find_element(
            By.CSS_SELECTOR, "button[type='submit']").click()
        time.sleep(2)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "driver"):
            cls.driver.quit()
        if hasattr(cls, "server"):
            cls.server.stop_server()
        if hasattr(cls, "test_dir"):
            cleanup_test_directory(cls.test_dir)

    def _open_annotation_page(self, instance_id=None):
        """Land on a NAMED item when it matters.

        The two items here carry different shapes and different prompts, and
        the cursor is wherever the previous test left it, so a test that does
        not say which item it wants asserts against whichever it gets.
        """
        self.driver.get(f"{self.server.base_url}/annotate")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR,
                                            ".annotation-form.pairwise")))
        time.sleep(1.5)
        if instance_id is None:
            return
        for button in ("prev-btn", "next-btn"):
            for _ in range(4):
                current = self.driver.find_element(
                    By.ID, "instance_id").get_attribute("value")
                if current == instance_id:
                    return
                controls = self.driver.find_elements(By.ID, button)
                if not controls:
                    break   # Previous is absent on the first item.
                controls[0].click()
                time.sleep(1.5)
        raise AssertionError(f"could not reach instance {instance_id}")

    def _box_texts(self):
        return [box.text.strip()
                for box in self.driver.find_elements(
                    By.CLASS_NAME, "pairwise-item-box")]

    def test_items_key_renders_both_candidates(self):
        self._open_annotation_page("1")
        boxes = self._box_texts()
        assert any(LEFT_TEXT in text for text in boxes), (
            f"the first candidate is not on the page; boxes were {boxes}")
        assert any(RIGHT_TEXT in text for text in boxes), (
            f"the second candidate is not on the page; boxes were {boxes}")

    def test_left_right_pair_renders_both_candidates(self):
        self._open_annotation_page("2")
        boxes = self._box_texts()
        assert any(PAIR_LEFT in text for text in boxes), (
            f"the left candidate is not on the page; boxes were {boxes}")
        assert any(PAIR_RIGHT in text for text in boxes), (
            f"the right candidate is not on the page; boxes were {boxes}")

    def test_the_prompt_stays_when_the_candidates_come_from_elsewhere(self):
        """`text_key` is the question here, not a copy of the candidates.

        The code that hides the main text was written for the shape where the
        text IS the pair, and hiding it unconditionally took the question away
        from the annotator being asked it.
        """
        self._open_annotation_page("1")
        assert self._box_texts(), "no candidates rendered to test against"
        container = self.driver.find_element(By.ID, "instance-text")
        assert container.is_displayed(), (
            "the prompt was hidden even though the candidates came from a "
            "different field")
        assert "Which reply is better?" in container.text

    def test_the_tiles_announce_a_role_and_a_selected_state(self):
        """A div with tabindex and a CSS class is not a control.

        Found in the audit pass over this widget: a screen reader had two
        unlabelled focusable things and no way to hear which was chosen.
        """
        self._open_annotation_page("1")
        tiles = self.driver.find_elements(By.CLASS_NAME, "pairwise-tile")
        assert len(tiles) >= 2
        for tile in tiles:
            assert tile.get_attribute("role") == "radio"
            assert tile.get_attribute("aria-checked") in ("true", "false")
        group = self.driver.find_element(
            By.CLASS_NAME, "pairwise-selection-container")
        assert group.get_attribute("role") == "radiogroup"
        assert group.get_attribute("aria-labelledby")

        tiles[0].click()
        time.sleep(0.5)
        states = [t.get_attribute("aria-checked")
                  for t in self.driver.find_elements(
                      By.CLASS_NAME, "pairwise-tile")]
        assert states.count("true") == 1, states
        assert states[0] == "true", states

    def test_the_focus_ring_is_visible(self):
        """A tile takes focus, so a keyboard user has to be able to see it.

        The rule set `outline: none` and relied on a 20%-alpha halo that
        measures 1.32:1 against the card. WCAG 1.4.11 asks for 3:1 on a focus
        indicator. Measured through the browser because a style that is
        overridden, or that never applies, still reads correct in the sheet.
        """
        self._open_annotation_page("1")
        style = self.driver.execute_script(
            "const t = document.querySelector('.pairwise-tile');"
            "t.focus();"
            "const cs = getComputedStyle(t);"
            "return [cs.outlineStyle, cs.outlineWidth, cs.outlineColor];")
        assert style[0] != "none", f"the focused tile has no outline: {style}"
        assert style[1] not in ("0px", ""), style


class TestPairwiseTextIsAlsoTheCandidates(unittest.TestCase):
    """The other half of the hide rule: text that IS the pair gets hidden.

    With `list_as_text`, the rendered text carries the candidates, so leaving
    it on screen shows the same two strings twice -- and the heading above it
    has to go with it.
    """

    @classmethod
    def setUpClass(cls):
        schemes = [{
            "annotation_type": "pairwise",
            "name": "preference",
            "description": "Which is better?",
            "mode": "binary",
            "items_key": "responses",
            "labels": ["A", "B"],
        }]
        data = [{"id": "1", "responses": [LEFT_TEXT, RIGHT_TEXT]}]

        port = find_free_port(preferred_port=9880)
        cls.test_dir = create_test_directory("audit25_pairwise_text_is_pair")
        cls.data_file = create_test_data_file(cls.test_dir, data)
        cls.config_file = create_test_config(
            cls.test_dir, schemes, data_files=[cls.data_file], port=port,
            item_properties={"id_key": "id", "text_key": "responses"},
            user_config={"allow_all_users": True, "users": []},
            list_as_text={"text_list_prefix_type": "alphabet"},
        )
        cls.server = FlaskTestServer(port=port, debug=False,
                                     config_file=cls.config_file)
        assert cls.server.start_server(), "Failed to start Flask server"
        cls.server._wait_for_server_ready(timeout=15)

        options = ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1400,1000")
        cls.driver = webdriver.Chrome(options=options)
        cls.driver.implicitly_wait(5)
        cls.driver.get(f"{cls.server.base_url}/")
        WebDriverWait(cls.driver, 10).until(
            EC.presence_of_element_located((By.NAME, "email")))
        cls.driver.find_element(By.NAME, "email").send_keys("pairtextpair")
        try:
            cls.driver.find_element(By.NAME, "pass").send_keys("pw")
        except Exception:
            pass
        cls.driver.find_element(
            By.CSS_SELECTOR, "button[type='submit']").click()
        time.sleep(2)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "driver"):
            cls.driver.quit()
        if hasattr(cls, "server"):
            cls.server.stop_server()
        if hasattr(cls, "test_dir"):
            cleanup_test_directory(cls.test_dir)

    def test_the_duplicate_text_and_its_heading_are_both_hidden(self):
        """The heading is a sibling of the container, not a child.

        Hiding the container alone left "Text to Annotate:" standing over
        empty space. Two of the three sites that hide the container tried to
        hide the heading with `h5.mb-3`, a selector that has matched nothing
        since the heading became `h5.instance-text-heading`.
        """
        self.driver.get(f"{self.server.base_url}/annotate")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR,
                                            ".annotation-form.pairwise")))
        time.sleep(1.5)
        boxes = [b.text.strip() for b
                 in self.driver.find_elements(By.CLASS_NAME,
                                              "pairwise-item-box")]
        assert any(LEFT_TEXT in text for text in boxes), boxes

        container = self.driver.find_element(By.ID, "instance-text")
        assert not container.is_displayed(), (
            "the candidates are shown twice")
        headings = self.driver.find_elements(
            By.CLASS_NAME, "instance-text-heading")
        assert headings, "expected the heading in the DOM to test against"
        for heading in headings:
            assert not heading.is_displayed(), (
                "the 'Text to Annotate' heading is still visible above the "
                "hidden text container")

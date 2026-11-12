"""
Two dynamic schemas populated from the item, driven in a browser.

Audit 25, both minor findings, both on the same kind of page:

* conjoint renders `profiles_per_set` cards, decided once for the scheme, while
  the data decides per item. Two profiles under the default of three left an
  "Option 3" whose every attribute read as an em dash -- with a live "Choose
  this" radio under it, so an annotator could record a preference for nothing.

* error_span hides the main text container, deliberately, because its own
  container IS the interactive text. It never hid the heading above it, so the
  page showed "Text to Annotate:" over empty space.
"""

import time
import unittest

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


# The scheme renders `profiles_per_set` cards, which defaults to 3. Item 1
# supplies fewer, item 2 supplies more: both directions have to be on the page
# or the assertions below hold whether or not the fix is present.
TWO_PROFILES = [{"Price": "$10", "Speed": "Fast"},
                {"Price": "$25", "Speed": "Slow"}]
FOUR_PROFILES = TWO_PROFILES + [{"Price": "$40", "Speed": "Instant"},
                                {"Price": "$60", "Speed": "Immediate"}]


class TestConjointCardsAndErrorSpanHeading(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        schemes = [
            {
                "annotation_type": "conjoint",
                "name": "choice",
                "description": "Which option would you pick?",
                "profiles_field": "profiles",
                "profiles_per_set": 3,
            },
            {
                "annotation_type": "error_span",
                "name": "errors",
                "description": "Mark any errors",
                "error_types": [{"name": "accuracy"}, {"name": "fluency"}],
            },
        ]
        data = [
            {"id": "1", "text": "A sentence to mark errors in.",
             "profiles": TWO_PROFILES},
            {"id": "2", "text": "Another sentence to mark errors in.",
             "profiles": FOUR_PROFILES},
        ]

        port = find_free_port(preferred_port=9879)
        cls.test_dir = create_test_directory("audit25_conjoint_error_span")
        cls.data_file = create_test_data_file(cls.test_dir, data)
        cls.config_file = create_test_config(
            cls.test_dir, schemes, data_files=[cls.data_file], port=port,
            item_properties={"id_key": "id", "text_key": "text"},
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

        cls.driver.get(f"{cls.server.base_url}/")
        WebDriverWait(cls.driver, 10).until(
            EC.presence_of_element_located((By.NAME, "email")))
        cls.driver.find_element(By.NAME, "email").send_keys("conjointprobe")
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

    def _open(self, instance_id="1"):
        """Land on a NAMED item.

        Which item `/annotate` returns depends on the assignment order and on
        where the previous test left the cursor, and the two items here are
        deliberately different: a test that does not say which one it wants
        asserts against whichever it happens to get.
        """
        self.driver.get(f"{self.server.base_url}/annotate")
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME,
                                            "conjoint-profile-card")))
        # Rewind first: the cursor is wherever the previous test left it, and
        # Next does not wrap past the last item.
        for button in ("prev-btn", "next-btn"):
            for _ in range(4):
                time.sleep(1.2)
                current = self.driver.find_element(
                    By.ID, "instance_id").get_attribute("value")
                if current == instance_id:
                    return
                controls = self.driver.find_elements(By.ID, button)
                if not controls:
                    break   # Previous is absent on the first item.
                controls[0].click()
        raise AssertionError(
            f"could not reach instance {instance_id}; saw {current!r}")

    def test_no_card_is_left_empty(self):
        """Two profiles under a scheme that renders three.

        Counting cards is the assertion because the defect WAS the third card,
        and checking the two filled ones for their values passes either way.
        """
        self._open()
        cards = self.driver.find_elements(By.CLASS_NAME, "conjoint-profile-card")
        assert len(cards) == 2, (
            f"expected one card per profile, found {len(cards)}: "
            f"{[c.text for c in cards]}")

    def test_no_radio_selects_an_empty_profile(self):
        """The em-dash card carried a working radio.

        The count is 3 because "None of these" is a radio too, and it is the
        one legitimate choice that is not a profile.
        """
        self._open()
        empty = [cell for cell
                 in self.driver.find_elements(By.CLASS_NAME,
                                              "conjoint-attr-value")
                 if cell.text.strip() in ("—", "")]
        assert not empty, (
            f"{len(empty)} attribute cells have no value; an annotator can "
            "still pick the card they are on")
        radios = self.driver.find_elements(By.CLASS_NAME, "conjoint-radio")
        assert len(radios) == 3, (
            f"expected 2 profile radios plus 'None of these', found "
            f"{len(radios)}")

    def test_an_item_with_more_profiles_than_cards_says_so(self):
        """The other direction is a silent cap.

        Dropping the third profile with nothing on screen leaves an annotator
        comparing two of three believing they saw the set.
        """
        self._open("2")
        notices = self.driver.find_elements(
            By.CLASS_NAME, "conjoint-truncation-notice")
        assert notices, "the dropped profile is not mentioned anywhere"
        assert notices[0].is_displayed()
        assert "3 of 4" in notices[0].text, notices[0].text

    def test_error_span_leaves_no_dangling_heading(self):
        """error_span hides the container and used to leave the heading."""
        self._open()
        text_container = self.driver.find_element(By.ID, "instance-text")
        assert not text_container.is_displayed(), (
            "error_span did not hide the duplicate text container, so this "
            "test would pass without exercising the heading at all")
        headings = self.driver.find_elements(
            By.CLASS_NAME, "instance-text-heading")
        assert headings, "expected the heading in the DOM to test against"
        for heading in headings:
            assert not heading.is_displayed(), (
                "'Text to Annotate:' is still visible above the hidden "
                "text container")

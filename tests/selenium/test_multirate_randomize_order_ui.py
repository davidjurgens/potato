"""multirate with randomize_order: the rows move, and answers stay on their row.

randomize_order used to shuffle the rating scale's names and then reorder the
rows by them. No row matched, so every annotator saw the configured order
while the scale was recorded as the order shown. The rows are what is
randomized now, so this drives the real page: the shown order is the recorded
one, a rating lands on the row that was clicked, and both survive Next and
Previous.
"""

import time
import unittest

import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import TestConfigManager

ROWS = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta"]
SCHEME = {"annotation_type": "multirate", "name": "mr", "description": "Rate these",
          "options": ROWS, "labels": ["1", "2", "3"], "randomize_order": True}


class TestMultirateRandomizeOrderUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = TestConfigManager("multirate_randomize_ui", [SCHEME], num_instances=3)
        cls.config.__enter__()
        cls.port = find_free_port()
        cls.server = FlaskTestServer(port=cls.port, debug=False,
                                     config_file=cls.config.config_path)
        assert cls.server.start_server(), "Failed to start Flask server"
        cls.server._wait_for_server_ready(timeout=15)
        cls.chrome_options = ChromeOptions()
        for arg in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
                    "--disable-gpu", "--window-size=1280,1000"):
            cls.chrome_options.add_argument(arg)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "server"):
            cls.server.stop_server()
        cls.config.__exit__(None, None, None)

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)

    def tearDown(self):
        self.driver.quit()

    def _login(self, user):
        d = self.driver
        d.get(f"{self.server.base_url}/")
        WebDriverWait(d, 10).until(EC.presence_of_element_located((By.ID, "login-email")))
        d.find_element(By.ID, "login-email").send_keys(user)
        pw = d.find_elements(By.ID, "login-pass")
        if pw:
            pw[0].send_keys("pw")
        d.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        WebDriverWait(d, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input.shadcn-multirate-radio")))

    def _shown_rows(self):
        return self.driver.execute_script("""
            var seen = [];
            document.querySelectorAll('input.shadcn-multirate-radio').forEach(function (i) {
                var n = i.getAttribute('label_name');
                if (seen.indexOf(n) < 0) seen.push(n);
            });
            return seen;""")

    def _instance_id(self):
        return self.driver.execute_script(
            "var e = document.getElementById('instance_id'); return e ? e.value : null;")

    def _checked(self):
        return self.driver.execute_script("""
            var out = {};
            document.querySelectorAll('input.shadcn-multirate-radio:checked').forEach(function (i) {
                out[i.getAttribute('label_name')] = i.value;
            });
            return out;""")

    def _rate(self, row, value):
        radio = self.driver.find_element(
            By.CSS_SELECTOR, f'input.shadcn-multirate-radio[label_name="{row}"][value="{value}"]')
        # A real click on the radio's own cell, as an annotator would.
        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", radio)
        radio.click()

    def test_rows_are_shuffled_per_annotator(self):
        orders = set()
        for n in range(4):
            self.driver.delete_all_cookies()
            self._login(f"mr_order_{n}_{int(time.time() * 1000)}")
            shown = self._shown_rows()
            self.assertEqual(sorted(shown), sorted(ROWS))
            orders.add(tuple(shown))
        # Six rows, four annotators: a shuffle that never moves anything
        # gives one order every time.
        self.assertGreater(len(orders), 1, f"every annotator saw {orders}")

    def test_ratings_stay_on_their_row_across_navigation(self):
        user = f"mr_persist_{int(time.time() * 1000)}"
        self._login(user)
        d = self.driver
        first_order = self._shown_rows()
        instance_id = self._instance_id()
        # The bottom row and the top row, whatever they are for this annotator.
        self._rate(first_order[-1], "3")
        self._rate(first_order[0], "1")
        time.sleep(1.5)   # save debounce
        expected = {first_order[-1]: "3", first_order[0]: "1"}
        self.assertEqual(self._checked(), expected)

        d.execute_script("document.getElementById('next-btn').click();")
        WebDriverWait(d, 10).until(lambda drv: self._instance_id() != instance_id)
        time.sleep(1.0)
        d.execute_script("document.getElementById('prev-btn').click();")
        WebDriverWait(d, 10).until(lambda drv: self._instance_id() == instance_id)
        time.sleep(1.5)

        self.assertEqual(self._shown_rows(), first_order,
                         "an item must keep the order it was first shown in")
        self.assertEqual(self._checked(), expected,
                         "each rating must come back on the row it was given to")

        session = requests.Session()
        for cookie in d.get_cookies():
            session.cookies.set(cookie["name"], cookie["value"])
        stored = session.get(f"{self.server.base_url}/get_annotations",
                             params={"instance_id": instance_id}).json()
        text = str(stored)
        for row, value in expected.items():
            self.assertIn(row, text)
        self.assertNotIn(first_order[2], text)


class TestMultirateTwoColumnOrderUI(TestMultirateRandomizeOrderUI):
    """num_columns: 2 puts two items in each row. Moving whole rows left the
    pair inside each row in configured order, so the page read differently
    from the order recorded for it."""

    @classmethod
    def setUpClass(cls):
        global SCHEME
        cls._one_column = SCHEME
        SCHEME = dict(cls._one_column, display_config={"num_columns": 2})
        cls.config = TestConfigManager("multirate_randomize_2col_ui", [SCHEME], num_instances=3)
        cls.config.__enter__()
        cls.port = find_free_port()
        cls.server = FlaskTestServer(port=cls.port, debug=False,
                                     config_file=cls.config.config_path)
        assert cls.server.start_server(), "Failed to start Flask server"
        cls.server._wait_for_server_ready(timeout=15)
        cls.chrome_options = ChromeOptions()
        for arg in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
                    "--disable-gpu", "--window-size=1280,1000"):
            cls.chrome_options.add_argument(arg)

    @classmethod
    def tearDownClass(cls):
        global SCHEME
        SCHEME = cls._one_column
        super().tearDownClass()

    def _reading_order(self):
        """Item labels as laid out on screen: top to bottom, then left to right."""
        return self.driver.execute_script("""
            var cells = [];
            document.querySelectorAll('.shadcn-multirate-table tbody td').forEach(function (td) {
                if (td.classList.contains('shadcn-radio-cell') || !td.textContent.trim()) return;
                var r = td.getBoundingClientRect();
                cells.push({name: td.textContent.trim(), top: Math.round(r.top), left: r.left});
            });
            cells.sort(function (a, b) { return a.top - b.top || a.left - b.left; });
            return cells.map(function (c) { return c.name; });""")

    def test_the_screen_reads_in_the_recorded_order(self):
        from potato.user_state_management import get_user_state_manager
        orders = set()
        for n in range(3):
            self.driver.delete_all_cookies()
            user = f"mr2_{n}_{int(time.time() * 1000)}"
            self._login(user)
            shown = self._reading_order()
            recorded = get_user_state_manager().get_user_state(user) \
                .get_presentation_order(self._instance_id())["mr"]
            self.assertEqual(shown, recorded)
            orders.add(tuple(shown))
        self.assertGreater(len(orders), 1, f"every annotator saw {orders}")

    def test_every_items_label_is_styled_as_a_label(self):
        """The label style keyed on td:first-child, so the second item in
        each row was centred and not bold."""
        self._login(f"mr2_style_{int(time.time() * 1000)}")
        styles = self.driver.execute_script("""
            var out = [];
            document.querySelectorAll('.shadcn-multirate-table tbody td').forEach(function (td) {
                if (td.classList.contains('shadcn-radio-cell') || !td.textContent.trim()) return;
                var cs = getComputedStyle(td);
                out.push([td.textContent.trim(), cs.textAlign, cs.fontWeight]);
            });
            return out;""")
        self.assertEqual(len(styles), len(ROWS))
        self.assertEqual({(align, weight) for _n, align, weight in styles},
                         {(styles[0][1], styles[0][2])}, styles)


if __name__ == "__main__":
    unittest.main()

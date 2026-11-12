"""
A study with more than one span scheme recorded spans under the wrong scheme.

Audit 27. Three text fields, three span schemes each pinned to its own field
with `target_field`. With only `mark_gamma` armed, a drag inside the gamma
field stored:

    schema        mark_beta      <- wrong
    target_field  gamma          <- right
    [14, 27)                     <- right

The offsets and the field are correct and the scheme name is not, which is the
worst combination: nothing about the stored file looks wrong. A study
separating "mark the symptom" from "mark the treatment" gets both under one
scheme name, so per-scheme agreement, adjudication and export are all computed
over a mislabeled set.

Two paths produced it, and both are fixed here.

`getSelectedLabel` returned `this.selectedLabel` whenever one was set, without
checking that the armed scheme owns the field under the cursor. Clicking a
label chip calls `selectLabel` -- including clicking one to turn it OFF -- so
`currentSchema` holds whichever chip was touched last, which is how an
explicitly unchecked `mark_beta` ended up on a gamma span.

Its fallback then took the first checked checkbox in the DOCUMENT, across every
scheme on the page. Span labels render checked by default, so with three
schemes all three are armed before the annotator touches anything and "first"
is just DOM order: three spans in three different fields all stored under
`mark_alpha`.

Why 27 audit rounds missed it: every span study either of us had built had
exactly one span scheme, where the schema is trivially right whatever the code
picks. This is the degenerate-configuration axis inverted -- the defect needs
MORE than the minimum, not less.
"""

import json
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

FIELDS = ("alpha", "beta", "gamma")


class TestMultipleSpanSchemes(unittest.TestCase):

    EXPECTED_SCHEMES = "mark_alpha,mark_beta,mark_gamma"

    @classmethod
    def setUpClass(cls):
        schemes = [{
            "annotation_type": "span",
            "name": f"mark_{field}",
            "description": f"Mark {field}",
            "target_field": field,
            "labels": [f"{field} hit"],
        } for field in FIELDS]
        # Four items, not one. Saving a span completes a single-item study, so
        # the next test navigates to a "Thank You" page and waits out its
        # timeout -- the same fixture-consumed-by-the-previous-test trap that
        # cost a run on the brush tests.
        data = [{
            "id": str(n),
            "alpha": "AAAA the first field runs here",
            "beta": "BBBB with its own offsets here",
            "gamma": "GGGG before this  three spaces here",
        } for n in range(1, 5)]
        port = find_free_port(preferred_port=9891)
        cls.test_dir = create_test_directory("audit27_multi_span")
        cls.data_file = create_test_data_file(cls.test_dir, data)
        cls.config_file = create_test_config(
            cls.test_dir, schemes, data_files=[cls.data_file], port=port,
            item_properties={"id_key": "id", "text_key": "alpha"},
            user_config={"allow_all_users": True, "users": []},
            additional_config={"instance_display": {"fields": [
                {"key": f, "type": "text", "span_target": True}
                for f in FIELDS]}},
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
        cls.driver.find_element(By.NAME, "email").send_keys("multispan")
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

    def _open(self):
        """Land on instance 1, whatever the previous test left behind.

        The spans are read back from `/api/spans/1`, so a test that annotates
        whichever item the cursor happens to be on would assert against an
        empty list and pass for the wrong reason.
        """
        self.driver.get(f"{self.server.base_url}/annotate")
        WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, ".annotation-form.span")))
        # FlaskTestServer runs in-process and the managers are singletons, so a
        # server left alive by another module can answer on this port with its
        # own study. Say that plainly here rather than letting it surface as a
        # timeout hunting for a field that was never on the page.
        served = self.driver.execute_script(
            "return [...document.querySelectorAll('.annotation-form.span')]"
            ".map(f => f.getAttribute('data-schema-name')).sort().join(',');")
        assert served == self.EXPECTED_SCHEMES, (
            f"this port served {served!r}, not this test's study "
            f"({self.EXPECTED_SCHEMES!r}) -- another module's server is "
            f"holding the singletons")
        for _ in range(5):
            time.sleep(1.0)
            current = self.driver.find_element(
                By.ID, "instance_id").get_attribute("value")
            if current == "1":
                return
            previous = self.driver.find_elements(By.ID, "prev-btn")
            if not previous:
                break
            previous[0].click()
        raise AssertionError("could not get back to instance 1")

    def _arm_only(self, schema):
        """Leave one scheme checked. Clicking a chip to turn it OFF still runs
        `selectLabel`, which is the path that put an unchecked scheme's name on
        another field's span."""
        self.driver.execute_script("""
          document.querySelectorAll(
              '.annotation-form.span input[type=checkbox]').forEach(box => {
            const owner = box.closest('.annotation-form.span')
                             .getAttribute('data-schema-name');
            if (owner !== arguments[0] && box.checked) box.click();
          });
        """, schema)
        time.sleep(0.4)

    def _drag_in(self, field, start, end):
        self.driver.execute_script("""
          const el = document.getElementById('text-content-' + arguments[0]);
          const range = document.createRange();
          range.setStart(el.firstChild, arguments[1]);
          range.setEnd(el.firstChild, arguments[2]);
          const sel = window.getSelection();
          sel.removeAllRanges(); sel.addRange(range);
          el.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
        """, field, start, end)
        time.sleep(1.2)

    def _stored(self):
        raw = self.driver.execute_script("""
          return new Promise(resolve => fetch('/api/spans/1')
            .then(r => r.json()).then(j => resolve(JSON.stringify(j))));
        """)
        return json.loads(raw).get("spans", [])

    def _clear(self):
        self.driver.execute_script("""
          return new Promise(resolve => fetch('/updateinstance', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({instance_id: '1', annotations: {},
                                  span_annotations: []})
          }).then(() => resolve(true)));
        """)
        time.sleep(0.5)

    def test_a_span_belongs_to_the_scheme_that_owns_its_field(self):
        """The finding. Only `mark_gamma` armed, drag in the gamma field."""
        self._open()
        self._clear()
        self._arm_only("mark_gamma")
        self._drag_in("gamma", 14, 27)

        spans = self._stored()
        assert len(spans) == 1, spans
        assert spans[0]["target_field"] == "gamma", spans
        assert spans[0]["schema"] == "mark_gamma", (
            f"stored under {spans[0]['schema']!r} for a span in the gamma "
            f"field: {spans[0]}")

    def test_each_field_gets_its_own_scheme_with_everything_armed(self):
        """The default state: every label checked, nothing touched.

        Three spans in three fields used to land under whichever scheme came
        first in the DOM, each with the correct target_field.
        """
        self._open()
        self._clear()
        for field, start, end in (("alpha", 10, 20),
                                  ("beta", 5, 15),
                                  ("gamma", 14, 27)):
            self._drag_in(field, start, end)

        spans = self._stored()
        assert len(spans) == 3, spans
        by_field = {s["target_field"]: s["schema"] for s in spans}
        assert by_field == {f: f"mark_{f}" for f in FIELDS}, by_field

    def test_the_offsets_were_never_the_problem(self):
        """A control, and the reason this was invisible: the geometry is right,
        so the stored file reads as clean."""
        self._open()
        self._clear()
        self._drag_in("gamma", 14, 27)
        spans = self._stored()
        assert spans[0]["start"] == 14 and spans[0]["end"] == 27, spans


class TestOneSchemeAcrossSeveralFields(unittest.TestCase):
    """The control for the fix: one span scheme, three span-target fields.

    The auditor drove this shape as soon as the routing rule was written down,
    and it is the case that must NOT change. The field a span belongs to comes
    from where the drag was, not from configuration, so a single scheme naming
    no `target_field` still records against the right field every time.

    It is also the argument against making `target_field` restrict. If naming a
    field meant "only this field", an author who pinned their one scheme to one
    field would silently lose every drag in the others -- and silently-wrong
    span data is exactly what the routing fix exists to prevent. Routing
    degrades to the best available scheme; restricting degrades to nothing
    recorded.
    """

    @classmethod
    def setUpClass(cls):
        schemes = [{
            "annotation_type": "span",
            "name": "marks",
            "description": "Mark anything",
            "labels": ["hit"],
        }]
        data = [{
            "id": str(n),
            "alpha": "AAAA the first field runs here",
            "beta": "BBBB with its own offsets here",
            "gamma": "GGGG before this  three spaces here",
        } for n in range(1, 5)]
        port = find_free_port(preferred_port=9892)
        cls.test_dir = create_test_directory("audit27_one_scheme_many_fields")
        cls.data_file = create_test_data_file(cls.test_dir, data)
        cls.config_file = create_test_config(
            cls.test_dir, schemes, data_files=[cls.data_file], port=port,
            item_properties={"id_key": "id", "text_key": "alpha"},
            user_config={"allow_all_users": True, "users": []},
            additional_config={"instance_display": {"fields": [
                {"key": f, "type": "text", "span_target": True}
                for f in FIELDS]}},
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
        cls.driver.find_element(By.NAME, "email").send_keys("onescheme")
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

    EXPECTED_SCHEMES = "marks"

    # The four helpers are the same gestures as the class above.
    _open = TestMultipleSpanSchemes._open
    _drag_in = TestMultipleSpanSchemes._drag_in
    _stored = TestMultipleSpanSchemes._stored
    _clear = TestMultipleSpanSchemes._clear

    def test_one_scheme_records_the_field_the_drag_was_in(self):
        self._open()
        self._clear()
        for field, start, end in (("alpha", 10, 20),
                                  ("beta", 5, 15),
                                  ("gamma", 14, 27)):
            self._drag_in(field, start, end)

        spans = self._stored()
        assert len(spans) == 3, spans
        assert {s["target_field"] for s in spans} == set(FIELDS), spans
        assert {s["schema"] for s in spans} == {"marks"}, spans

    def test_the_offsets_are_each_fields_own(self):
        """Each field indexes its own text, so the same offsets in different
        fields must not collapse onto one field's string."""
        self._open()
        self._clear()
        self._drag_in("alpha", 10, 20)
        self._drag_in("gamma", 14, 27)
        by_field = {s["target_field"]: (s["start"], s["end"])
                    for s in self._stored()}
        assert by_field["alpha"] == (10, 20), by_field
        assert by_field["gamma"] == (14, 27), by_field

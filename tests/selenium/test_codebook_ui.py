#!/usr/bin/env python3
"""
Selenium test for the universal Codebook tray.

Verifies the tray only appears when a codebook is enabled, that seeded
codes render, that the on-the-fly composer is shown in `open` mode, and
that adding a code reflects in the tray without a reload.
"""

import os
import time
import unittest
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options as ChromeOptions


def _chrome():
    o = ChromeOptions()
    for a in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
              "--disable-gpu", "--window-size=1600,1000"):
        o.add_argument(a)
    return o


def _login(driver, wait, base_url, uid):
    driver.get(f"{base_url}/")
    wait.until(EC.presence_of_element_located((By.ID, "login-email")))
    f = driver.find_element(By.ID, "login-email")
    f.clear()
    f.send_keys(uid)
    driver.find_element(By.CSS_SELECTOR, "#login-content form").submit()
    wait.until(EC.presence_of_element_located((By.ID, "instance_id")))


_CB_SCHEME = [{
    "name": "code", "description": "Codebook scheme",
    "annotation_type": "radio", "codebook": True,
    "labels": ["seed-a", "seed-b"],
}]


class TestCodebookTrayOpenMode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.helpers.flask_test_setup import FlaskTestServer
        from tests.helpers.port_manager import find_free_port
        from tests.helpers.test_utils import (
            create_test_data_file, create_test_config)
        tests_dir = Path(__file__).parent.parent
        cls.test_dir = os.path.join(
            tests_dir, "output", f"cb_ui_{int(time.time())}")
        os.makedirs(cls.test_dir, exist_ok=True)
        data_file = create_test_data_file(
            cls.test_dir, [{"id": "c1", "text": "an instance"}])
        cls.config_file = create_test_config(
            cls.test_dir, _CB_SCHEME, data_files=[data_file],
            annotation_task_name="Codebook UI Test",
            require_password=False,
            additional_config={"codebook_mode": "open"})
        cls.port = find_free_port()
        cls.server = FlaskTestServer(
            port=cls.port, debug=False, config_file=cls.config_file)
        assert cls.server.start_server(), "server did not start"
        cls.server._wait_for_server_ready(timeout=10)
        cls.chrome_options = _chrome()

    @classmethod
    def tearDownClass(cls):
        from tests.helpers.test_utils import cleanup_test_directory
        if hasattr(cls, "server"):
            cls.server.stop_server()
        if hasattr(cls, "test_dir"):
            cleanup_test_directory(cls.test_dir)

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.driver.implicitly_wait(5)
        self.wait = WebDriverWait(self.driver, 15)
        _login(self.driver, self.wait, self.server.base_url,
               f"coder_{int(time.time()*1000)}")

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def test_tray_lists_seeded_codes_and_adds_one(self):
        self.wait.until(EC.element_to_be_clickable(
            (By.ID, "cb-panel-toggle"))).click()
        tree = self.wait.until(EC.visibility_of_element_located(
            (By.ID, "cb-tree")))
        self.wait.until(EC.text_to_be_present_in_element(
            (By.ID, "cb-tree"), "seed-a"))
        self.assertIn("seed-b", tree.text)
        # open mode -> composer visible
        composer = self.driver.find_element(By.ID, "cb-composer")
        self.assertTrue(composer.is_displayed())
        # add on the fly
        name = self.driver.find_element(By.ID, "cb-new-name")
        name.clear()
        name.send_keys("runtime-code")
        self.driver.find_element(By.ID, "cb-add-btn").click()
        self.wait.until(EC.text_to_be_present_in_element(
            (By.ID, "cb-tree"), "runtime-code"))

    def test_duplicate_shows_inline_error(self):
        self.wait.until(EC.element_to_be_clickable(
            (By.ID, "cb-panel-toggle"))).click()
        self.wait.until(EC.text_to_be_present_in_element(
            (By.ID, "cb-tree"), "seed-a"))
        name = self.driver.find_element(By.ID, "cb-new-name")
        name.clear()
        name.send_keys("seed-a")
        self.driver.find_element(By.ID, "cb-add-btn").click()
        err = self.wait.until(EC.visibility_of_element_located(
            (By.ID, "cb-error")))
        self.assertIn("already exists", err.text.lower())


_CB_MULTI = [{
    "name": "themes", "description": "Themes",
    "annotation_type": "multiselect", "codebook": True,
    "labels": ["seed-a", "seed-b"],
}]


class TestCodebookOnTheFlyNavBack(unittest.TestCase):
    """The persistence risk area (CLAUDE.md): add a code mid-session,
    use it, navigate away and back via full reloads, and verify the
    runtime code survives in the form AND its selection is restored."""

    @classmethod
    def setUpClass(cls):
        from tests.helpers.flask_test_setup import FlaskTestServer
        from tests.helpers.port_manager import find_free_port
        from tests.helpers.test_utils import (
            create_test_data_file, create_test_config)
        tests_dir = Path(__file__).parent.parent
        cls.test_dir = os.path.join(
            tests_dir, "output", f"cb_nav_{int(time.time())}")
        os.makedirs(cls.test_dir, exist_ok=True)
        data_file = create_test_data_file(cls.test_dir, [
            {"id": "n1", "text": "first instance"},
            {"id": "n2", "text": "second instance"},
        ])
        cls.config_file = create_test_config(
            cls.test_dir, _CB_MULTI, data_files=[data_file],
            annotation_task_name="Codebook NavBack",
            require_password=False,
            additional_config={"codebook_mode": "open"})
        cls.port = find_free_port()
        cls.server = FlaskTestServer(
            port=cls.port, debug=False, config_file=cls.config_file)
        assert cls.server.start_server(), "server did not start"
        cls.server._wait_for_server_ready(timeout=10)
        cls.chrome_options = _chrome()

    @classmethod
    def tearDownClass(cls):
        from tests.helpers.test_utils import cleanup_test_directory
        if hasattr(cls, "server"):
            cls.server.stop_server()
        if hasattr(cls, "test_dir"):
            cleanup_test_directory(cls.test_dir)

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.driver.implicitly_wait(5)
        # 30s (not 20): the runtime-code *restore* is an async chain
        # (reconcile -> /version -> /get_annotations -> set checked);
        # under heavy back-to-back-suite machine load it needs headroom
        # so this CLAUDE.md persistence gate stays deterministic.
        self.wait = WebDriverWait(self.driver, 30)
        _login(self.driver, self.wait, self.server.base_url,
               f"navcoder_{int(time.time()*1000)}")

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def _cb(self, value):
        return self.driver.find_element(
            By.CSS_SELECTOR,
            "form#themes input.annotation-input[value='%s']" % value)

    def test_runtime_code_survives_nav_and_restores(self):
        d, w = self.driver, self.wait
        # add a code via the tray
        w.until(EC.element_to_be_clickable(
            (By.ID, "cb-panel-toggle"))).click()
        w.until(EC.text_to_be_present_in_element(
            (By.ID, "cb-tree"), "seed-a"))
        nm = d.find_element(By.ID, "cb-new-name")
        nm.clear()
        nm.send_keys("runtime-x")
        d.find_element(By.ID, "cb-add-btn").click()
        # reconciled into the form on the current instance (no reload)
        w.until(lambda x: x.find_elements(
            By.CSS_SELECTOR,
            "form#themes input.annotation-input[value='runtime-x']"))
        # select an existing seed + the runtime code on instance 1
        self._cb("seed-a").click()
        self._cb("runtime-x").click()
        time.sleep(2)  # autosave debounce
        # Next (full reload) -> instance 2: runtime code reconciled again
        d.find_element(By.ID, "next-btn").click()
        w.until(lambda x: x.find_elements(
            By.CSS_SELECTOR,
            "form#themes input.annotation-input[value='runtime-x']"))
        # Previous (full reload) -> back to instance 1
        d.find_element(By.ID, "prev-btn").click()
        # runtime option present again (client reconcile on stale tmpl)
        w.until(lambda x: x.find_elements(
            By.CSS_SELECTOR,
            "form#themes input.annotation-input[value='runtime-x']"))
        # and BOTH selections restored (seed via server HTML, runtime
        # via the async codebook restore path). Exception-safe poll:
        # during a reload the element is briefly absent/stale, which
        # must not abort the wait.
        def _selected(value):
            def _check(_):
                try:
                    return self._cb(value).is_selected()
                except Exception:
                    return False
            return _check
        w.until(_selected("seed-a"))
        w.until(_selected("runtime-x"))


_CB_SPAN = [{
    "name": "spans", "description": "Span codes",
    "annotation_type": "span", "codebook": True,
    "labels": ["seed-x"],
}]


class TestInVivoCodingNavBack(unittest.TestCase):
    """(D) in-vivo coding, persistence risk area (CLAUDE.md): select
    text, press the in-vivo key, create a code from the selection, and
    verify the span persists AND the runtime code reconciles back as a
    usable span label across Next/Prev full reloads."""

    @classmethod
    def setUpClass(cls):
        from tests.helpers.flask_test_setup import FlaskTestServer
        from tests.helpers.port_manager import find_free_port
        from tests.helpers.test_utils import (
            create_test_data_file, create_test_config)
        tests_dir = Path(__file__).parent.parent
        cls.test_dir = os.path.join(
            tests_dir, "output", f"cb_iv_{int(time.time())}")
        os.makedirs(cls.test_dir, exist_ok=True)
        data_file = create_test_data_file(cls.test_dir, [
            {"id": "v1", "text": "the quick brown fox jumps over"},
            {"id": "v2", "text": "a second instance of plain text"},
        ])
        cls.config_file = create_test_config(
            cls.test_dir, _CB_SPAN, data_files=[data_file],
            annotation_task_name="InVivo NavBack",
            require_password=False,
            additional_config={"codebook_mode": "open"})
        cls.port = find_free_port()
        cls.server = FlaskTestServer(
            port=cls.port, debug=False, config_file=cls.config_file)
        assert cls.server.start_server(), "server did not start"
        cls.server._wait_for_server_ready(timeout=10)
        cls.chrome_options = _chrome()

    @classmethod
    def tearDownClass(cls):
        from tests.helpers.test_utils import cleanup_test_directory
        if hasattr(cls, "server"):
            cls.server.stop_server()
        if hasattr(cls, "test_dir"):
            cleanup_test_directory(cls.test_dir)

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.driver.implicitly_wait(5)
        self.wait = WebDriverWait(self.driver, 20)
        _login(self.driver, self.wait, self.server.base_url,
               f"ivcoder_{int(time.time()*1000)}")

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def _wait_span_mgr(self):
        self.wait.until(lambda d: d.execute_script(
            "return !!(window.spanManager "
            "&& window.spanManager.isInitialized);"))

    def _select_and_invivo_key(self):
        # Select the first ~9 chars of the instance text, then fire the
        # in-vivo key on document (exactly what a real keypress does).
        res = self.driver.execute_script("""
            const host = document.getElementById('text-content')
                || document.querySelector('[id^="text-content-"]');
            if (!host) return 'no-host';
            let tn = null;
            for (const n of host.childNodes) {
                if (n.nodeType === 3 && n.textContent.trim()) {tn=n;break;}
            }
            if (!tn) return 'no-text-node';
            const r = document.createRange();
            r.setStart(tn, 0); r.setEnd(tn, 9);
            const s = window.getSelection();
            s.removeAllRanges(); s.addRange(r);
            document.dispatchEvent(new KeyboardEvent(
                'keydown', {key: 'i', bubbles: true}));
            return s.toString();
        """)
        self.assertTrue(res and res not in ("no-host", "no-text-node"),
                        f"selection failed: {res}")

    def _has_span_option(self, value):
        def _check(_):
            try:
                return bool(self.driver.find_elements(
                    By.CSS_SELECTOR,
                    "form#spans input.shadcn-span-checkbox"
                    "[value='%s']" % value))
            except Exception:
                return False
        return _check

    def test_invivo_creates_code_span_and_survives_nav(self):
        d, w = self.driver, self.wait
        self._wait_span_mgr()
        self._select_and_invivo_key()
        # composer popover opens, pre-filled from the selection
        w.until(EC.visibility_of_element_located((By.ID, "cb-invivo")))
        nm = d.find_element(By.ID, "cb-iv-name")
        self.assertTrue(nm.get_attribute("value").strip())
        nm.clear()
        nm.send_keys("fox phrase")
        d.find_element(By.ID, "cb-iv-go").click()
        # new code becomes a usable span label on this instance
        w.until(self._has_span_option("fox phrase"))
        # and a span was actually created + saved
        w.until(lambda x: x.execute_script(
            "return (window.spanManager.getSpans()||[])"
            ".some(s => s.label === 'fox phrase');"))
        time.sleep(2)  # autosave / debounce settle
        # Next (full reload) -> v2
        d.find_element(By.ID, "next-btn").click()
        w.until(self._has_span_option("fox phrase"))
        # Previous (full reload) -> back to v1
        d.find_element(By.ID, "prev-btn").click()
        # runtime code reconciled back as a span label...
        w.until(self._has_span_option("fox phrase"))
        # ...and the span overlay restored from the server.
        def _span_restored(_):
            try:
                return self.driver.execute_script(
                    "return (window.spanManager.getSpans()||[])"
                    ".some(s => s.label === 'fox phrase');")
            except Exception:
                return False
        w.until(_span_restored)


class TestCodebookTrayDisabled(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.helpers.flask_test_setup import FlaskTestServer
        from tests.helpers.port_manager import find_free_port
        from tests.helpers.test_utils import (
            create_test_data_file, create_test_config)
        tests_dir = Path(__file__).parent.parent
        cls.test_dir = os.path.join(
            tests_dir, "output", f"cb_ui_off_{int(time.time())}")
        os.makedirs(cls.test_dir, exist_ok=True)
        data_file = create_test_data_file(
            cls.test_dir, [{"id": "c1", "text": "x"}])
        cls.config_file = create_test_config(
            cls.test_dir,
            [{"name": "l", "description": "d",
              "annotation_type": "radio", "labels": ["a", "b"]}],
            data_files=[data_file], annotation_task_name="Codebook Off",
            require_password=False)  # no codebook scheme/config
        cls.port = find_free_port()
        cls.server = FlaskTestServer(
            port=cls.port, debug=False, config_file=cls.config_file)
        assert cls.server.start_server(), "server did not start"
        cls.server._wait_for_server_ready(timeout=10)
        cls.chrome_options = _chrome()

    @classmethod
    def tearDownClass(cls):
        from tests.helpers.test_utils import cleanup_test_directory
        if hasattr(cls, "server"):
            cls.server.stop_server()
        if hasattr(cls, "test_dir"):
            cleanup_test_directory(cls.test_dir)

    def setUp(self):
        self.driver = webdriver.Chrome(options=self.chrome_options)
        self.wait = WebDriverWait(self.driver, 15)
        _login(self.driver, self.wait, self.server.base_url, "nocb")

    def tearDown(self):
        if hasattr(self, "driver"):
            self.driver.quit()

    def test_toggle_hidden_when_codebook_disabled(self):
        time.sleep(1.5)  # allow the enable-probe to resolve
        toggle = self.driver.find_element(By.ID, "cb-panel-toggle")
        self.assertFalse(
            toggle.is_displayed(),
            "Codebook toggle must stay hidden when no codebook is enabled")


if __name__ == "__main__":
    unittest.main()


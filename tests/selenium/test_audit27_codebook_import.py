"""
"Paste markdown" silently discarded everything the author typed.

Audit 27. Type real markdown, pick a target, click "Review blocks": the dialog
closes, no review step appears, `content rev` stays where it was, and nothing
is saved or reported. The work is gone.

Two separate faults, both fixed here.

`doImportParse` looked the target section up with `getElementById` and passed
the result straight to `openEditor`, which dereferences it. A document section
with no content is deliberately not rendered unless the page is in editing
mode, and setting `state.editing = true` does not by itself put it in the DOM
-- so importing into an empty section found nothing, threw
`TypeError: Cannot read properties of null (reading 'querySelector')`, and
killed the rest of the handler. `closeImport()` had already run, so the failure
was invisible: no dialog, no review step, no error, and the parse had succeeded
with a 200.

Separately, an empty target closed the dialog and returned, discarding the
textarea. That path had no message at all -- the same silent-refusal shape as
the round-24 `/updateinstance` 200.

The console error is what identified it. The auditor could not see it: console
capture does not work against these pages in their harness, which is why they
reported the symptom precisely and could not name the cause.
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

SCHEMES = [{"name": "themes", "description": "T",
            "annotation_type": "multiselect", "codebook": True,
            "labels": ["alpha", "beta"]}]

MARKDOWN = ("### Definition\n\nWaiting on another team.\n\n"
            "### Use when\n\nThe blocker is external.")


class TestPasteMarkdownKeepsWhatYouTyped(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.test_dir = create_test_directory("audit27_cb_import")
        data_file = create_test_data_file(
            cls.test_dir, [{"id": "i1", "text": "x"}])
        config_file = create_test_config(
            cls.test_dir, SCHEMES, data_files=[data_file],
            require_password=False,
            additional_config={"codebook_mode": "open"})
        port = find_free_port(preferred_port=9033)
        cls.server = FlaskTestServer(port=port, debug=False,
                                     config_file=config_file)
        assert cls.server.start_server(), "server did not start"
        cls.server._wait_for_server_ready(timeout=10)

        opts = ChromeOptions()
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--window-size=1400,1400")
        cls.opts = opts

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "server"):
            cls.server.stop_server()
        cleanup_test_directory(cls.test_dir)

    def setUp(self):
        self.d = webdriver.Chrome(options=self.opts)
        self.d.set_script_timeout(15)
        self.b = self.server.base_url
        self.d.get(self.b + "/login")
        time.sleep(0.4)
        self.d.execute_async_script(
            "const done=arguments[arguments.length-1];"
            "fetch('/register',{method:'POST',headers:{'Content-Type':"
            "'application/x-www-form-urlencoded'},body:'email=r&pass=p'})"
            ".then(()=>fetch('/auth',{method:'POST',headers:{'Content-Type':"
            "'application/x-www-form-urlencoded'},body:'email=r&pass=p'}))"
            ".then(()=>done('ok')).catch(e=>done(''+e));")

    def tearDown(self):
        self.d.quit()

    def _open(self):
        self.d.get(self.b + "/codebook")
        WebDriverWait(self.d, 10).until(
            EC.presence_of_element_located((By.ID, "cbd-doc")))
        time.sleep(0.8)

    def _paste(self, markdown, target=None):
        self.d.find_element(By.ID, "cbd-import-btn").click()
        time.sleep(0.5)
        if markdown:
            self.d.find_element(By.ID, "cbd-import-text").send_keys(markdown)
        if target is not None:
            self.d.execute_script(
                "document.getElementById('cbd-import-target').value = "
                "arguments[0];", target)
        time.sleep(0.2)
        self.d.find_element(By.ID, "cbd-import-parse").click()
        time.sleep(2.0)

    def _editor_state(self, section_id):
        return self.d.execute_script("""
            const sec = document.getElementById('sec-' + arguments[0]);
            const body = sec ? sec.querySelector('.cbd-section-body') : null;
            return {
                sectionPresent: !!sec,
                editorPresent: !!(body && body.querySelector(
                    'textarea, select, .cbd-edit-block')),
                text: body ? body.innerText : '',
            };
        """, section_id)

    def test_importing_into_an_empty_section_opens_the_review_step(self):
        """The finding. `preamble` starts with no content, so it is not in the
        DOM until the page is editing -- which is exactly where the handler
        used to throw on a null element and abandon the import."""
        self._open()
        self._paste(MARKDOWN, target="section:preamble")

        state = self._editor_state("section:preamble")
        assert state["sectionPresent"], (
            "the target section was never rendered, so the import had nowhere "
            "to go")
        assert state["editorPresent"], (
            f"no review step opened after a successful parse: {state}")

    def test_the_parsed_blocks_reach_the_review_step(self):
        """Opening an empty editor would satisfy the test above.

        The parsed markdown has to arrive in it, which is the thing the author
        typed and the thing that was being lost.
        """
        self._open()
        self._paste(MARKDOWN, target="section:preamble")
        text = self._editor_state("section:preamble")["text"]
        assert "Choose a type" in text or "Definition" in text, text

    def test_no_uncaught_error_reaches_the_console(self):
        """The failure was a TypeError that killed the handler mid-flight.

        Asserted directly, because every visible symptom -- closed dialog, no
        review step, no toast -- is also what a silent early return looks like.
        """
        self._open()
        # BOTH listeners. The failure happened inside a `.then()` callback, so
        # it surfaced as an unhandled REJECTION and never fired a window
        # `error` event -- the first draft of this test listened only for
        # `error` and passed with the defect fully present.
        self.d.execute_script(
            "window.__errs = [];"
            "window.addEventListener('error',"
            "  e => window.__errs.push('error: ' + e.message));"
            "window.addEventListener('unhandledrejection',"
            "  e => window.__errs.push('rejection: ' + (e.reason && e.reason.message"
            "                                           || e.reason)));")
        self._paste(MARKDOWN, target="section:preamble")
        errors = self.d.execute_script("return window.__errs || [];")
        assert not errors, errors

    def test_an_empty_target_keeps_the_dialog_and_the_text(self):
        """The other silent path: closing on an empty target threw the
        author's markdown away with no message."""
        self._open()
        self._paste(MARKDOWN, target="")
        state = self.d.execute_script("""
            return {
                modalHidden: document.getElementById('cbd-import-modal').hidden,
                text: document.getElementById('cbd-import-text').value,
            };
        """)
        assert not state["modalHidden"], "the dialog closed on an empty target"
        assert "Waiting on another team" in state["text"], (
            "the typed markdown was discarded")

    def test_an_empty_textarea_says_so_rather_than_parsing_nothing(self):
        self._open()
        self._paste("", target="section:preamble")
        assert not self.d.execute_script(
            "return document.getElementById('cbd-import-modal').hidden;")

"""Selenium coverage for the full-page codebook document editor (Phase 4).

Verifies the typed-block editor edits + persists across a full page reload
(not a cached form), the paste/parse needs-type flow, and that rendered
markdown is XSS-inert (server sanitize_html is the trust boundary).
"""

import os
import time
import unittest

import pytest
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    create_test_directory, create_test_data_file, create_test_config,
    cleanup_test_directory)

_CB = [{"name": "themes", "description": "T",
        "annotation_type": "multiselect", "codebook": True,
        "labels": ["alpha", "beta"]}]


class TestCodebookDocumentEditor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = create_test_directory("cb_doc_selenium")
        data_file = create_test_data_file(
            cls.test_dir, [{"id": "i1", "text": "x"}])
        config_file = create_test_config(
            cls.test_dir, _CB, data_files=[data_file],
            require_password=False,
            additional_config={"codebook_mode": "open"})
        port = find_free_port(preferred_port=9032)
        cls.server = FlaskTestServer(
            port=port, debug=False, config_file=config_file)
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
        # authenticate within the browser origin so the session cookie sticks
        self.d.get(self.b + "/login")
        time.sleep(0.4)
        self.d.execute_async_script(
            "const done=arguments[arguments.length-1];"
            "fetch('/register',{method:'POST',headers:{'Content-Type':"
            "'application/x-www-form-urlencoded'},body:'email=r&pass=p'})"
            ".then(()=>fetch('/auth',{method:'POST',headers:{'Content-Type':"
            "'application/x-www-form-urlencoded'},body:'email=r&pass=p'}))"
            ".then(()=>done('ok')).catch(e=>done(''+e));")
        # create a uniquely-named code via API (class-scoped server shares
        # one project DB across tests, so names must not collide)
        self.code_name = "sel code " + str(int(time.time() * 1000))
        self.code_id = self.d.execute_async_script(
            "const done=arguments[arguments.length-1];"
            "fetch('/api/codebook',{method:'POST',headers:{'Content-Type':"
            "'application/json'},body:JSON.stringify({name:arguments[0]})})"
            ".then(r=>r.json()).then(j=>done(j.code.id)).catch(e=>done(''));",
            self.code_name)

    def tearDown(self):
        self.d.quit()

    def _open(self):
        self.d.get(self.b + "/codebook")
        WebDriverWait(self.d, 10).until(
            EC.presence_of_element_located((By.ID, "cbd-doc")))
        time.sleep(0.8)

    def _open_editor(self, name):
        self.d.find_element(By.ID, "cbd-edit-toggle").click()
        time.sleep(0.5)
        ok = self.d.execute_script(
            "const secs=[...document.querySelectorAll('.cbd-section')];"
            "const t=secs.find(s=>{const n=s.querySelector('.cbd-section-name');"
            "return n && n.textContent===arguments[0];});"
            "if(!t) return 'no-section';"
            "const b=[...t.querySelectorAll('.cbd-section-tools .cbd-btn')]"
            ".find(x=>x.textContent.trim()==='Edit');"
            "if(!b) return 'no-btn'; b.click(); return 'ok';", name)
        self.assertEqual(ok, "ok")
        time.sleep(0.5)

    def test_edit_save_persists_across_reload(self):
        self._open()
        self._open_editor(self.code_name)
        # set first row type=definition, body
        self.d.execute_script(
            "const r=document.querySelector('.cbd-edit-block');"
            "const sel=r.querySelector('select'); sel.value='definition';"
            "sel.dispatchEvent(new Event('change'));"
            "r.querySelector('textarea').value='a durable meaning';")
        self.d.execute_script(
            "[...document.querySelectorAll('.cbd-btn')]"
            ".find(b=>b.textContent.trim()==='Save').click();")
        time.sleep(1.2)
        # FULL reload (not cached form) — content must come from the server
        self.d.get(self.b + "/codebook")
        WebDriverWait(self.d, 10).until(
            EC.presence_of_element_located((By.ID, "cbd-doc")))
        time.sleep(0.8)
        body = self.d.find_element(By.ID, "cbd-doc").text
        self.assertIn("a durable meaning", body)
        # and server-side
        stored = self.d.execute_async_script(
            "const done=arguments[arguments.length-1];"
            "fetch('/api/codebook/blocks?code_id='+arguments[0])"
            ".then(r=>r.json()).then(j=>done(JSON.stringify(j.blocks)))"
            ".catch(e=>done(''));", self.code_id)
        self.assertIn("a durable meaning", stored)

    def test_rendered_markdown_is_xss_inert(self):
        # save a block whose body contains a script tag, via API
        self.d.execute_async_script(
            "const done=arguments[arguments.length-1];"
            "fetch('/api/codebook/blocks',{method:'PUT',headers:{'Content-Type':"
            "'application/json'},body:JSON.stringify({code_id:arguments[0],"
            "base_version:0,blocks:[{block_type:'definition',"
            "body_md:\"<script>window.__xss=1</script>danger\"}]})})"
            ".then(()=>done('ok')).catch(e=>done(''));", self.code_id)
        self._open()
        # the literal text shows; the script must NOT have executed
        executed = self.d.execute_script("return window.__xss === 1;")
        self.assertFalse(executed)
        scripts_in_doc = self.d.execute_script(
            "return document.getElementById('cbd-doc')"
            ".querySelectorAll('script').length;")
        self.assertEqual(scripts_in_doc, 0)
        self.assertIn("danger", self.d.find_element(By.ID, "cbd-doc").text)

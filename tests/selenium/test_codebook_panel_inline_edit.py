"""Selenium coverage for the in-annotation codebook panel inline edit
(Phase 5): open the tray, edit a code's definition via the per-code pencil,
save, and confirm it persisted server-side.
"""

import time
import unittest

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


class TestCodebookPanelInlineEdit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = create_test_directory("cb_panel_selenium")
        data_file = create_test_data_file(
            cls.test_dir, [{"id": "i1", "text": "an excerpt to code"}])
        config_file = create_test_config(
            cls.test_dir, _CB, data_files=[data_file],
            require_password=False,
            additional_config={"codebook_mode": "open",
                               "debug": True,
                               "debug_phase": "annotation"})
        port = find_free_port(preferred_port=9034)
        cls.server = FlaskTestServer(
            port=port, debug=False, config_file=config_file)
        assert cls.server.start_server(), "server did not start"
        cls.server._wait_for_server_ready(timeout=10)
        opts = ChromeOptions()
        for a in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-gpu", "--window-size=1400,1100"):
            opts.add_argument(a)
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
            "'application/x-www-form-urlencoded'},body:'email=p&pass=p'})"
            ".then(()=>fetch('/auth',{method:'POST',headers:{'Content-Type':"
            "'application/x-www-form-urlencoded'},body:'email=p&pass=p'}))"
            ".then(()=>done('ok')).catch(e=>done(''+e));")
        self.code_name = "panel code " + str(int(time.time() * 1000))
        self.code_id = self.d.execute_async_script(
            "const done=arguments[arguments.length-1];"
            "fetch('/api/codebook',{method:'POST',headers:{'Content-Type':"
            "'application/json'},body:JSON.stringify({name:arguments[0]})})"
            ".then(r=>r.json()).then(j=>done(j.code.id)).catch(e=>done(''));",
            self.code_name)

    def tearDown(self):
        self.d.quit()

    def test_panel_inline_definition_persists(self):
        self.assertTrue(self.code_id, "code was not created")
        self.d.get(self.b + "/annotate")
        time.sleep(2.0)
        # reveal + open the codebook tray
        self.d.execute_script(
            "var t=document.getElementById('cb-panel-toggle');"
            "if(t){t.hidden=false;t.click();}")
        WebDriverWait(self.d, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".cb-node-edit")))
        time.sleep(0.6)
        # click the pencil for our code
        opened = self.d.execute_script(
            "const rows=[...document.querySelectorAll('.cb-node-row')];"
            "const r=rows.find(x=>{const n=x.querySelector('.cb-name');"
            "return n && n.textContent===arguments[0];});"
            "if(!r) return 'no-row';"
            "const b=r.querySelector('.cb-node-edit'); if(!b) return 'no-btn';"
            "b.click(); return 'ok';", self.code_name)
        self.assertEqual(opened, "ok")
        time.sleep(0.6)
        # type a definition and save
        self.d.execute_script(
            "const ta=document.querySelector('.cb-inline-edit .cb-inline-ta');"
            "ta.value='panel-authored meaning';")
        self.d.execute_script(
            "document.querySelector('.cb-inline-save').click();")
        time.sleep(1.4)
        # confirm persisted server-side
        stored = self.d.execute_async_script(
            "const done=arguments[arguments.length-1];"
            "fetch('/api/codebook/blocks?code_id='+arguments[0])"
            ".then(r=>r.json()).then(j=>done(JSON.stringify(j.blocks)))"
            ".catch(e=>done(''));", self.code_id)
        self.assertIn("panel-authored meaning", stored)
        self.assertIn("definition", stored)

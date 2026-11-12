"""
The annotation-page codebook tray shows what each code MEANS, in a browser.

Audit 27 (e): the tray listed bare code names, so reading a definition meant
leaving the annotation page for /codebook -- at the moment the annotator was
deciding whether the code applied.

Driven rather than asserted against the source, for two reasons this file
exists to catch:

- the definition arrives from the server but the client never renders it;
- the client renders it once and then serves a stale copy out of
  sessionStorage, because editing prose bumps only `content_revision` and the
  cache used to compare the structural revision alone. That one is invisible
  on a first load and only appears on the second, so the test navigates twice.
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
        "labels": [
            {"name": "delay", "color": "#4682b4",
             "description": "The agent stalled before acting."},
            {"name": "workaround",
             "tooltip": "The agent routed around a blocked tool."},
        ]}]


class TestCodebookTrayDefinitions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = create_test_directory("cb_tray_defs_selenium")
        data_file = create_test_data_file(
            cls.test_dir, [{"id": "i1", "text": "an excerpt to code"},
                           {"id": "i2", "text": "a second excerpt"}])
        config_file = create_test_config(
            cls.test_dir, _CB, data_files=[data_file],
            require_password=False,
            additional_config={"codebook_mode": "open",
                               "debug": True,
                               "debug_phase": "annotation"})
        port = find_free_port(preferred_port=9038)
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
            "'application/x-www-form-urlencoded'},body:'email=t&pass=t'})"
            ".then(()=>fetch('/auth',{method:'POST',headers:{'Content-Type':"
            "'application/x-www-form-urlencoded'},body:'email=t&pass=t'}))"
            ".then(()=>done('ok')).catch(e=>done(''+e));")

    def tearDown(self):
        self.d.quit()

    def _open_tray(self):
        self.d.get(self.b + "/annotate")
        time.sleep(2.0)
        self.d.execute_script(
            "var t=document.getElementById('cb-panel-toggle');"
            "if(t){t.hidden=false;t.click();}")
        WebDriverWait(self.d, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".cb-node-row")))
        time.sleep(0.8)

    def _visible_def_for(self, name):
        """The definition text an annotator can actually read next to
        `name`. `.text` is visibility-aware, so a clamped-to-nothing or
        display:none line reads as empty here rather than passing."""
        return self.d.execute_script(
            "const rows=[...document.querySelectorAll('.cb-node')];"
            "const li=rows.find(x=>{const n=x.querySelector('.cb-name');"
            "return n && n.textContent===arguments[0];});"
            "if(!li) return '__no-row__';"
            "const p=li.querySelector(':scope > .cb-def');"
            "if(!p) return '';"
            "const cs=getComputedStyle(p);"
            "if(cs.display==='none'||cs.visibility==='hidden') return '';"
            "return p.textContent.trim();", name)

    def test_seeded_definitions_are_readable_in_the_tray(self):
        self._open_tray()
        self.assertEqual(self._visible_def_for("delay"),
                         "The agent stalled before acting.")
        self.assertEqual(self._visible_def_for("workaround"),
                         "The agent routed around a blocked tool.")

    def test_an_edited_definition_survives_the_session_cache(self):
        """Second load, definition changed, no structural change. The
        client caches the tray in sessionStorage; if it keys freshness on
        the structural revision alone this shows the old wording."""
        # Its own code: these tests share one server, and rewriting a
        # seeded code here would decide what a later test reads.
        name = "cache probe"
        self.d.get(self.b + "/annotate")
        time.sleep(1.0)
        code_id = self.d.execute_async_script(
            "const done=arguments[arguments.length-1];"
            "fetch('/api/codebook',{method:'POST',headers:{'Content-Type':"
            "'application/json'},body:JSON.stringify({name:arguments[0]})})"
            ".then(r=>r.json()).then(j=>done(j.code?j.code.id:''))"
            ".catch(e=>done(''));", name)
        self.assertTrue(code_id, "probe code was not created")

        # Warm the cache with the code ALREADY present, so the only thing
        # that changes below is prose. Creating the code bumps the
        # structural revision, and warming before it would invalidate the
        # cache for that reason instead -- which is a test that passes
        # whether or not the content revision is checked at all.
        self._open_tray()
        self.assertEqual(self._visible_def_for(name), "")

        wrote = self.d.execute_async_script(
            "const done=arguments[arguments.length-1];"
            "fetch('/api/codebook/blocks?scope_kind=code&scope_id='"
            "+arguments[0]).then(r=>r.json()).then(j=>"
            "fetch('/api/codebook/blocks',{method:'PUT',headers:"
            "{'Content-Type':'application/json'},body:JSON.stringify({"
            "scope_kind:'code',scope_id:arguments[0],"
            "base_version:j.scope_version,blocks:[{block_type:'short_def',"
            "body_md:'Rewritten after the annotators asked.'}]})}))"
            ".then(r=>done(r.status)).catch(e=>done(''+e));", code_id)
        self.assertEqual(wrote, 200, wrote)

        # Navigate for real -- same session, so the cache is still warm.
        self._open_tray()
        self.assertEqual(self._visible_def_for(name),
                         "Rewritten after the annotators asked.")

    def test_every_code_in_a_small_codebook_is_visible_without_scrolling(self):
        """The panel column had no bounds: the code list was `flex: 1`
        with a 0 basis and the curate block below it was unbounded at
        ~500px. On a live study that squeezed the list to about one row
        (it still scrolled, so it looked fine -- it just read as a
        codebook with one code in it); definitions made each row taller
        and took it from one visible code to none.

        In this fixture the same missing bound shows up as the composer
        being pushed off the bottom instead, which is what
        `test_the_add_a_code_button_stays_reachable` catches. The two
        assertions here are the invariant the fix is FOR rather than the
        symptom it was found by."""
        # A laptop-height window, which is where the squeeze bites: on a
        # very tall screen every section fits and the bug is invisible.
        self.d.set_window_size(1400, 700)
        self._open_tray()
        counts = self.d.execute_script(
            "const tree=document.getElementById('cb-tree');"
            "const a=document.getElementById('cb-admin-section');"
            "const tr=tree.getBoundingClientRect();"
            "const nodes=[...tree.querySelectorAll('.cb-node')];"
            "return {total:nodes.length,"
            " treeH:tr.height, adminH:a.getBoundingClientRect().height,"
            " visible:nodes.filter(n=>{const r=n.getBoundingClientRect();"
            "  return r.top>=tr.top-1 && r.bottom<=tr.bottom+1;}).length};")
        self.assertGreaterEqual(counts["total"], 3)
        self.assertEqual(
            counts["visible"], counts["total"],
            "codes are cut off in a tray tall enough to hold them all")
        self.assertGreaterEqual(
            counts["treeH"], counts["adminH"],
            "the code list gets less of the panel than the curate block "
            f"({counts['treeH']}px vs {counts['adminH']}px)")

    def test_the_add_a_code_button_stays_reachable(self):
        """Giving the list a height floor must not push the composer off
        the bottom of the panel."""
        self.d.set_window_size(1400, 700)
        self._open_tray()
        self.d.execute_script(
            "const a=document.getElementById('cb-admin-section');"
            "if(a) a.hidden=false;")
        reachable = self.d.execute_script(
            "const p=document.getElementById('cb-panel')"
            ".getBoundingClientRect();"
            "const b=document.querySelector('#cb-composer .cb-primary');"
            "if(!b) return null;"
            "const r=b.getBoundingClientRect();"
            "return r.height>0 && r.bottom<=p.bottom+1 && r.top>=p.top-1;")
        self.assertTrue(reachable, "the Add button is off the panel")

    def test_a_child_codes_definition_is_indented_under_its_parent(self):
        """--cb-depth drives the tree indent. Nothing set it, so a child
        code and its definition sat flush with the root codes and the
        hierarchy was unreadable."""
        self._open_tray()
        parent_id = self.d.execute_script(
            "const rows=[...document.querySelectorAll('.cb-node-row')];"
            "const r=rows.find(x=>{const n=x.querySelector('.cb-name');"
            "return n && n.textContent==='delay';});"
            "return r ? r.getAttribute('data-code-id') : '';")
        made = self.d.execute_async_script(
            "const done=arguments[arguments.length-1];"
            "fetch('/api/codebook',{method:'POST',headers:{'Content-Type':"
            "'application/json'},body:JSON.stringify({name:'delay: startup',"
            "parent_id:arguments[0]})}).then(r=>r.json())"
            ".then(j=>done(j.code?j.code.id:'')).catch(e=>done(''));",
            parent_id)
        self.assertTrue(made, "child code was not created")

        self._open_tray()
        indents = self.d.execute_script(
            "const out={};"
            "document.querySelectorAll('.cb-node-row').forEach(r=>{"
            "const n=r.querySelector('.cb-name');"
            "if(n) out[n.textContent]=parseFloat("
            "getComputedStyle(r).paddingLeft);});"
            "return out;")
        self.assertIn("delay: startup", indents)
        self.assertGreater(indents["delay: startup"], indents["delay"],
                           "a child code renders flush with its parent")

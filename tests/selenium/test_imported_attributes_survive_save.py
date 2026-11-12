"""
Do imported per-object attributes survive an annotator's save?

`potato import -f cvat` puts each shape's <attribute> elements on the object as
`attributes`, and the CVAT exporter writes them back out. The browser used to
rebuild restored shapes from type/label/color plus provenance only, so the
first save of an imported item stored the shape without them and the export
lost them with no warning.

Driven end to end through the real import CLI, a real browser drag (trusted
events), Next/Previous navigation, the server's stored copy, and the CVAT
exporter. The unit-level guard is tests/jest/shape-attributes.test.js.
"""

import json
import os
import subprocess
import sys
import time
import unittest
import xml.etree.ElementTree as ET

import yaml
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import cleanup_test_directory, create_test_directory

W, H = 400, 300
USER = "attrprobe"


def _cvat_xml(names):
    images = "".join(
        f'<image id="{i}" name="{name}" width="{W}" height="{H}">'
        f'<box label="car" xtl="100" ytl="80" xbr="260" ybr="200" occluded="0">'
        f'<attribute name="occlusion">partial</attribute>'
        f'<attribute name="truncated">0.4</attribute>'
        f'</box></image>'
        for i, name in enumerate(names))
    return (
        "<annotations><version>1.1</version><meta><task><labels>"
        "<label><name>car</name><color>#ff6b6b</color></label>"
        f"</labels></task></meta>{images}</annotations>")


class TestImportedAttributesSurviveSave(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from PIL import Image
        from potato.importers.cli import main as import_main

        cls.test_dir = create_test_directory("imported_attributes_survive_save")
        project = os.path.join(cls.test_dir, "project")
        media = os.path.join(project, "media")
        os.makedirs(media, exist_ok=True)
        # Three items, so saving the first does not finish the study.
        names = [f"img_{n}.png" for n in range(1, 4)]
        for name in names:
            Image.new("RGB", (W, H), (40, 90, 150)).save(os.path.join(media, name))
        xml_path = os.path.join(cls.test_dir, "annotations.xml")
        with open(xml_path, "w") as f:
            f.write(_cvat_xml(names))

        assert import_main([
            "-i", xml_path, "-f", "cvat", "-o", project,
            "--image-dir", media, "--image-url-prefix", "/media/",
            "--schema-name", "objects",
        ]) == 0

        cls.config_file = os.path.join(project, "config.yaml")
        with open(cls.config_file) as f:
            config = yaml.safe_load(f)
        port = find_free_port(preferred_port=9893)
        config.update({
            "port": port,
            "task_dir": project,
            "media_directory": "media",
            "require_password": False,
        })
        with open(cls.config_file, "w") as f:
            yaml.safe_dump(config, f)
        cls.project = project

        cls.server = FlaskTestServer(port=port, debug=False,
                                     config_file=cls.config_file)
        assert cls.server.start_server(), "Failed to start Flask server"
        cls.server._wait_for_server_ready(timeout=15)

        options = ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1400,1100")
        cls.driver = webdriver.Chrome(options=options)
        cls.driver.implicitly_wait(5)

        cls.driver.get(f"{cls.server.base_url}/")
        WebDriverWait(cls.driver, 10).until(
            EC.presence_of_element_located((By.NAME, "email")))
        cls.driver.find_element(By.NAME, "email").send_keys(USER)
        try:
            cls.driver.find_element(By.NAME, "pass").send_keys("pw")
        except Exception:
            pass
        cls.driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        time.sleep(2)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "driver"):
            cls.driver.quit()
        if hasattr(cls, "server"):
            cls.server.stop_server()
        if hasattr(cls, "test_dir"):
            cleanup_test_directory(cls.test_dir)

    def _wait_for_shapes(self):
        WebDriverWait(self.driver, 15).until(lambda d: d.execute_script(
            "const c = document.querySelector('.image-annotation-container');"
            "return !!(c && c.annotationManager && c.annotationManager.image"
            " && c.annotationManager.canvas.getObjects()"
            "      .some(o => o.annotationData));"))

    def _current_instance(self):
        return self.driver.execute_script(
            "const el = document.getElementById('instance_id');"
            "return el ? el.value : null;")

    def _stored_objects(self, instance_id):
        raw = self.driver.execute_async_script(
            "const done = arguments[arguments.length - 1];"
            "fetch('/get_annotations?instance_id=' + encodeURIComponent(arguments[0]))"
            "  .then(r => r.text()).then(done).catch(e => done('ERR ' + e));",
            instance_id)
        data = json.loads(raw)
        found = []

        def walk(node):
            if isinstance(node, dict):
                if node.get("type") == "bbox" and "label" in node:
                    found.append(node)
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)
            elif isinstance(node, str) and node.startswith("["):
                try:
                    walk(json.loads(node))
                except ValueError:
                    pass

        walk(data)
        return found

    def test_attributes_survive_a_drag_and_navigation(self):
        self.driver.get(f"{self.server.base_url}/annotate")
        self._wait_for_shapes()
        first = self._current_instance()

        # Where the box is on screen, relative to the canvas element's centre,
        # which is where Selenium 4 measures offsets from.
        offset = self.driver.execute_script("""
            const m = document.querySelector('.image-annotation-container').annotationManager;
            const obj = m.canvas.getObjects().find(o => o.annotationData);
            const c = obj.getCenterPoint();
            const p = fabric.util.transformPoint(c, m.canvas.viewportTransform);
            const el = m.canvas.upperCanvasEl;
            const r = el.getBoundingClientRect();
            return [p.x - r.width / 2, p.y - r.height / 2];
        """)
        upper = self.driver.find_element(By.CSS_SELECTOR, ".upper-canvas")
        (ActionChains(self.driver)
            .move_to_element_with_offset(upper, int(offset[0]), int(offset[1]))
            .click_and_hold().move_by_offset(12, 6).move_by_offset(12, 6)
            .release().perform())
        time.sleep(2)  # autosave debounce

        self.driver.find_element(By.ID, "next-btn").click()
        WebDriverWait(self.driver, 15).until(
            lambda d: self._current_instance() not in (None, first))
        self.driver.find_element(By.ID, "prev-btn").click()
        WebDriverWait(self.driver, 15).until(
            lambda d: self._current_instance() == first)
        self._wait_for_shapes()

        # Visual state: the restored shape on the canvas still carries them.
        on_canvas = self.driver.execute_script(
            "const m = document.querySelector('.image-annotation-container').annotationManager;"
            "return m.canvas.getObjects().find(o => o.annotationData).annotationData;")
        self.assertEqual(on_canvas.get("attributes"),
                         {"occlusion": "partial", "truncated": "0.4"})

        # Server state: the save after the drag kept them.
        stored = self._stored_objects(first)
        self.assertTrue(stored, "no stored bbox for the edited item")
        self.assertTrue(stored[0].get("edited"),
                        "the drag never reached the server, so this proves nothing")
        self.assertEqual(stored[0].get("attributes"),
                         {"occlusion": "partial", "truncated": "0.4"})

        # Export: the CVAT exporter writes them back as <attribute> elements.
        out_dir = os.path.join(self.test_dir, "export_cvat")
        result = subprocess.run(
            [sys.executable, "-m", "potato.export", "-c", self.config_file,
             "-f", "cvat", "-o", out_dir],
            capture_output=True, text=True, cwd=self.project)
        self.assertEqual(result.returncode, 0, result.stderr)
        xml_files = [os.path.join(root, f)
                     for root, _, files in os.walk(out_dir)
                     for f in files if f.endswith(".xml")]
        self.assertTrue(xml_files, f"no CVAT XML written: {result.stdout}")
        tree = ET.parse(xml_files[0])
        image = next(i for i in tree.iter("image") if i.get("name", "").endswith(first.split("/")[-1])
                     or i.get("id") == first or first in i.get("name", ""))
        attrs = {a.get("name"): a.text for a in image.iter("attribute")}
        self.assertEqual(attrs, {"occlusion": "partial", "truncated": "0.4"})

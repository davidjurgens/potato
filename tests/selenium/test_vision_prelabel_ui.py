"""Model predictions shown on the vision schemes that took prelabels in
group 3: microscopy ROIs, map features, grounding regions, GUI step
verdicts and region captions.

Each item carries a prediction in its ``predictions`` field, the place
training write-back puts it. The test opens the item as an annotator with no
answer of their own and reads what each widget shows, not the hidden input:
an ROI in the list, a feature in the map's list with Accept suggestions
offered, an expression marked as answered or not present, a selected
verdict button, a caption next to its region.
"""

import importlib.util
import json
import os
import time
import unittest

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (cleanup_test_directory, create_test_config,
                                      create_test_data_file, create_test_directory)

_SHOT = ("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' "
         "width='200' height='120'><rect width='200' height='120' fill='%23eee'/></svg>")
BOX = {"type": "bbox", "label": "damaged",
       "coordinates": {"x": 0.1, "y": 0.1, "width": 0.3, "height": 0.3}}


def _write_media(test_dir):
    from PIL import Image
    media = os.path.join(test_dir, "media")
    os.makedirs(media, exist_ok=True)
    Image.new("RGB", (120, 60), (40, 90, 40)).save(os.path.join(media, "map.png"))
    Image.new("RGB", (160, 120), (200, 200, 200)).save(os.path.join(media, "photo.png"))
    spec = importlib.util.spec_from_file_location(
        "mic_gen", os.path.join(os.path.dirname(__file__), "..", "..", "examples",
                                "image", "multichannel-microscopy", "generate_data.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.write_tiff(os.path.join(media, "stack.ome.tif"),
                      os.path.join(media, "stack_cells.tif"), size=64, timepoints=2)


def _chrome():
    options = ChromeOptions()
    for flag in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
                 "--window-size=1600,2400"):
        options.add_argument(flag)
    return webdriver.Chrome(options=options)


class _Base(unittest.TestCase):
    schemes = []
    item = {}
    #: A second item keeps the study open once the first is answered.
    more_items = []
    preferred_port = 9861

    @classmethod
    def setUpClass(cls):
        cls.test_dir = create_test_directory(cls.__name__.lower())
        _write_media(cls.test_dir)
        data_file = create_test_data_file(cls.test_dir, [cls.item] + cls.more_items)
        port = find_free_port(preferred_port=cls.preferred_port)
        cls.config_file = create_test_config(
            cls.test_dir, cls.schemes, data_files=[data_file], port=port,
            item_properties={"id_key": "id", "text_key": "text"},
            user_config={"allow_all_users": True, "users": []},
            additional_config={"media_directory": "media",
                               "pre_annotation": {"enabled": True, "field": "predictions"}})
        cls.server = FlaskTestServer(port=port, debug=False, config_file=cls.config_file)
        assert cls.server.start_server(), "server failed to start"
        cls.server._wait_for_server_ready(timeout=15)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "server"):
            cls.server.stop_server()
        cleanup_test_directory(cls.test_dir)

    def setUp(self):
        self.driver = _chrome()
        self.addCleanup(self.driver.quit)
        d = self.driver
        d.get(f"{self.server.base_url}/")
        WebDriverWait(d, 10).until(EC.presence_of_element_located((By.NAME, "email")))
        d.find_element(By.NAME, "email").send_keys("viewer_%d" % int(time.time() * 1000))
        try:
            d.find_element(By.NAME, "pass").send_keys("pw")
        except Exception:
            pass
        d.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        # Login lands on the item. Loading /annotate again would unload the
        # page, and leaving a page that showed prelabels adopts them.
        WebDriverWait(d, 15).until(EC.visibility_of_element_located((By.ID, "main-content")))

    def wait_for(self, check, timeout=10):
        deadline = time.time() + timeout
        value = None
        while time.time() < deadline:
            value = check()
            if value:
                return value
            time.sleep(0.25)
        return value

    def assertNothingStored(self, instance_id):
        stored = self.driver.execute_async_script(
            "var done = arguments[arguments.length - 1];"
            "fetch('/get_annotations?instance_id=' + arguments[0], {credentials: 'same-origin'})"
            ".then(r => r.json()).then(done, e => done(String(e)));", instance_id)
        self.assertIsInstance(stored, dict, stored)
        self.assertFalse(any(stored.get(key) for key in
                             ("label_annotations", "label_values", "span_annotations")),
                         stored)

    def console_errors(self):
        try:
            return [e["message"] for e in self.driver.get_log("browser")
                    if e.get("level") == "SEVERE" and "favicon" not in e["message"]]
        except Exception:
            return []


class TestVisionPrelabels(_Base):
    schemes = [
        {"annotation_type": "image_annotation", "name": "canvas", "description": "Regions",
         "labels": ["referent"], "tools": ["bbox"], "source_field": "photo"},
        {"annotation_type": "grounding_eval", "name": "ground",
         "description": "Where does each phrase point?", "region_type": "box"},
        {"annotation_type": "gui_trajectory", "name": "gui", "description": "Judge each step",
         "steps_key": "steps"},
        {"annotation_type": "geo_annotation", "name": "fields", "description": "Fields",
         "task": "draw", "tools": ["polygon", "point"],
         "labels": [{"name": "Field"}, {"name": "Water"}], "basemap_field": "map"},
        {"annotation_type": "microscopy", "name": "cells", "description": "Mark damage",
         "image_key": "stack", "tools": ["bbox", "polygon", "landmark"],
         "labels": [{"name": "damaged"}]},
    ]
    ring = [[10.2, 40.2], [10.8, 40.2], [10.8, 40.8], [10.2, 40.8], [10.2, 40.2]]
    item = {
        "id": "v1", "text": "one item, five schemes", "photo": "/media/photo.png",
        "expressions": ["the grey square", "the unicorn"],
        "steps": [{"action": "click save", "x": 0.5, "y": 0.5, "screenshot": _SHOT},
                  {"action": "type name", "x": 0.2, "y": 0.2, "screenshot": _SHOT}],
        "map": {"image": "/media/map.png", "extent": [10.0, 40.0, 12.0, 41.0]},
        "stack": "stack.ome.tif",
        "predictions": {
            "ground": {"regions": {"0": [dict(BOX, label="referent", source="ai")]},
                       "absent": ["1"]},
            "gui": [{"index": 0, "verdict": "correct", "point": {"x": 0.5, "y": 0.5},
                     "confidence": 0.9},
                    {"index": 1, "verdict": "wrong_element", "point": {"x": 0.7, "y": 0.7},
                     "confidence": 0.8}],
            "fields": {"type": "FeatureCollection", "features": [
                {"type": "Feature", "id": "f0",
                 "geometry": {"type": "Polygon", "coordinates": [ring]},
                 "properties": {"label": "Field", "tool": "polygon", "text": "",
                                "source": "model", "confidence": 0.7}}]},
            "cells": {"image": {"width": 64, "height": 64},
                      "rois": [dict(BOX, z=0, t=1, source="ai", confidence=0.6)]},
        },
    }

    more_items = [{"id": "v2", "text": "nothing predicted", "photo": "/media/photo.png",
                   "expressions": ["the grey square"], "steps": [],
                   "map": {"image": "/media/map.png", "extent": [10.0, 40.0, 12.0, 41.0]},
                   "stack": "stack.ome.tif"}]

    def test_every_scheme_shows_its_prediction(self):
        d = self.driver
        WebDriverWait(d, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".gt-card")))

        verdicts = self.wait_for(lambda: d.execute_script(
            "return Array.from(document.querySelectorAll('.gt-vbtn.selected'))"
            ".map(b => [b.dataset.idx, b.dataset.v]);"))
        self.assertEqual(sorted(map(tuple, verdicts or [])),
                         [("0", "correct"), ("1", "wrong_element")])

        states = self.wait_for(lambda: d.execute_script(
            "return Array.from(document.querySelectorAll('.grounding-item'))"
            ".map(i => i.className);"))
        self.assertEqual(len(states), 2, states)
        self.assertIn("state-located", states[0])
        self.assertIn("state-absent", states[1])

        features = self.wait_for(lambda: d.execute_script(
            "var f = document.querySelector('form[data-schema-name=\"fields\"]');"
            "return f && f.querySelector('.geo-accept') ? "
            "f.querySelectorAll('.geo-features li, .geo-features .geo-feature').length : 0;"))
        self.assertTrue(features, "the map offers no suggested features")

        rois = self.wait_for(lambda: d.execute_script(
            "var l = document.querySelector('.mic-roi-list');"
            "return l ? l.querySelectorAll('li').length : 0;"), timeout=20)
        self.assertEqual(rois, 1)
        plane = d.execute_script(
            "var c = document.querySelector('.mic-roi-count'); return c && c.textContent;")
        self.assertEqual(plane, "(1)")
        self.assertEqual(self.console_errors(), [])

    def test_looking_at_prelabels_stores_nothing(self):
        """The page saved on arrival: grounding_eval wrote a blank answer that
        carried its region type (so it was not blank), then captured the
        canvas while annotation.js cleared it; the image tool coloured the
        prelabel's shapes; and the server's JSON differed from the widget's in
        spacing. Each made an untouched item look edited, the save stored the
        prelabels as the annotator's answer, and a one-item study ended on
        arrival."""
        d = self.driver
        self.wait_for(lambda: d.execute_script(
            "return document.querySelectorAll('.grounding-item').length"))
        time.sleep(2.5)       # past the 800 ms autosave debounce, twice over
        self.assertNothingStored("v1")

    def test_rejecting_every_suggestion_is_an_answer(self):
        """Deleting the map's only suggestion left the input empty, an empty
        input is not saved, and the suggestion came back on reload (audit
        102). It is now saved as an empty collection."""
        d = self.driver
        form = 'form[data-schema-name="fields"]'
        button = self.wait_for(lambda: d.execute_script(
            "return document.querySelector('%s .geo-feature .geo-delete');" % form))
        self.assertTrue(button)
        # A script click: at this page height the action bar sits over the
        # list, and the test is about what is saved, not the click.
        d.execute_script("arguments[0].click()", button)
        time.sleep(2.5)
        stored = d.execute_async_script(
            "var done = arguments[arguments.length - 1];"
            "fetch('/get_annotations?instance_id=v1', {credentials: 'same-origin'})"
            ".then(r => r.json()).then(done, e => done(String(e)));")
        answer = json.loads((stored.get("label_values") or {}).get("fields", {}).get("fields", "null"))
        self.assertEqual(answer, {"type": "FeatureCollection", "features": []})
        d.refresh()
        WebDriverWait(d, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".gt-card")))
        time.sleep(3)
        self.assertEqual(d.execute_script(
            "return document.querySelectorAll('%s .geo-feature').length;" % form), 0)
        self.assertFalse(d.execute_script(
            "return !!document.querySelector('%s .geo-accept');" % form))

    def test_untouched_map_suggestions_are_not_an_answer(self):
        """Suggested features wait for Accept: the map's hidden input stays
        empty until the annotator takes them, unlike the other prelabels."""
        d = self.driver
        self.wait_for(lambda: d.execute_script(
            "return !!document.querySelector('form[data-schema-name=\"fields\"] .geo-accept');"))
        value = d.execute_script(
            "return document.querySelector('form[data-schema-name=\"fields\"] "
            ".geo-annotation-input').value;")
        self.assertEqual(value, "")


class TestCaptionPrelabel(_Base):
    preferred_port = 9871
    schemes = [
        {"annotation_type": "image_annotation", "name": "canvas", "description": "Regions",
         "labels": ["object"], "tools": ["bbox", "polygon"], "source_field": "photo"},
        {"annotation_type": "region_caption", "name": "captions",
         "description": "Describe each region"},
    ]
    region = {"type": "bbox", "label": "object",
              "coordinates": {"x": 0.2, "y": 0.2, "width": 0.4, "height": 0.4}}
    outline = {"type": "polygon", "label": "object", "coordinates": [
        {"x": 0.7, "y": 0.7}, {"x": 0.9, "y": 0.7}, {"x": 0.8, "y": 0.9}]}
    item = {"id": "c1", "text": "caption me", "photo": "/media/photo.png",
            "predictions": {"canvas": [region, outline],
                            # The caption model covered one of the canvas
                            # model's two regions (audit 102, R1).
                            "captions": {"captions": [
                                {"region": region, "caption": "a grey square"}]}}}

    def test_the_caption_shows_beside_its_region(self):
        d = self.driver
        caption = self.wait_for(lambda: d.execute_script(
            "var t = document.querySelector('.region-caption-container textarea, "
            "[data-annotation-type=\"region_caption\"] textarea'); return t && t.value;"))
        self.assertEqual(caption, "a grey square")
        self.assertEqual(self.console_errors(), [])

    def test_looking_at_the_caption_prelabel_stores_nothing(self):
        """region_caption wrote an empty caption list before its canvas
        loaded; the autosave check took that as the arrival value, so the
        prelabel filling it in read as an edit and was stored, the canvas
        with it (audit 102)."""
        d = self.driver
        self.wait_for(lambda: d.execute_script(
            "var t = document.querySelector('[data-annotation-type=\"region_caption\"] "
            "textarea'); return t && t.value;"))
        time.sleep(2.5)
        self.assertNothingStored("c1")

    def test_deleting_an_uncaptioned_region_is_saved(self):
        """With the canvas skipped as a companion and uncaptioned regions
        left out of the caption comparison, deleting the polygon nobody had
        captioned changed nothing the autosave looked at (audit 102, R9)."""
        d = self.driver
        self.wait_for(lambda: d.execute_script(
            "var c = document.querySelector('.image-annotation-container');"
            "return c && c.annotationManager && c.annotationManager.getAnnotationHandles().length == 2;"))
        # The prelabel lists the box first and the polygon second.
        d.execute_script("document.querySelector('.image-annotation-container')"
                         ".annotationManager.deleteAnnotation(1);")
        time.sleep(2.5)
        stored = d.execute_async_script(
            "var done = arguments[arguments.length - 1];"
            "fetch('/get_annotations?instance_id=c1', {credentials: 'same-origin'})"
            ".then(r => r.json()).then(done, e => done(String(e)));")
        canvas = json.loads(((stored or {}).get("label_values") or {}).get("canvas", {})
                            .get("_data", "[]"))
        self.assertEqual([shape["type"] for shape in canvas], ["bbox"])


if __name__ == "__main__":
    unittest.main()

"""A volume-unet prediction shown on a volume_annotation scheme.

The item's ``predictions`` field holds painted masks in the stored shape. The
page draws them on the slice views, stores nothing while the annotator only
looks, and stores the masks with the annotator's own brush stroke.
"""

import json
import os
import time

import pytest
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from tests.selenium.test_vision_prelabel_ui import _Base

nib = pytest.importorskip("nibabel")
np = pytest.importorskip("numpy")
pytest.importorskip("pydicom")

SIZE = 24


def _block():
    from potato.media.volume_masks import masks_from_volume
    mask = np.zeros((SIZE, SIZE, SIZE), bool)
    mask[6:14, 6:14, :] = True
    return masks_from_volume(mask)


class TestVolumePrelabel(_Base):
    preferred_port = 9875
    schemes = [{"annotation_type": "volume_annotation", "name": "seg",
                "description": "Paint the lesion", "source_field": "volume",
                "labels": [{"name": "Lesion"}], "tools": ["navigate", "brush", "eraser"]}]
    item = {"id": "c1", "text": "case 1", "volume": "vol.nii.gz", "predictions": {
        "seg": {"shape": [SIZE, SIZE, SIZE], "labels": ["Lesion"], "masks": {"Lesion": _block()},
                "prefilled_from": "model"}}}
    more_items = [{"id": "c2", "text": "case 2", "volume": "vol.nii.gz"}]

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        data = np.random.default_rng(0).normal(100, 10, (SIZE, SIZE, SIZE)).astype("float32")
        nib.save(nib.Nifti1Image(data, np.eye(4)),
                 os.path.join(cls.test_dir, "media", "vol.nii.gz"))

    def painted(self):
        """Mask pixels on the axial view's overlay: the label's colour
        (#e6553a, drawn at alpha 110), not the yellow and white crosshairs,
        which are on the overlay whether or not anything is painted."""
        return self.driver.execute_script("""
            const view = document.querySelector('.vol-view[data-axis="axial"] .vol-overlay');
            if (!view || !view.width) return -1;
            const data = view.getContext('2d').getImageData(0, 0, view.width, view.height).data;
            let n = 0;
            for (let i = 0; i < data.length; i += 4) {
                if (data[i + 3] >= 60 && data[i] - data[i + 1] > 80) n++;
            }
            return n;""")

    def stored(self, instance_id):
        return self.driver.execute_async_script(
            "var done = arguments[arguments.length - 1];"
            "fetch('/get_annotations?instance_id=' + arguments[0], {credentials: 'same-origin'})"
            ".then(r => r.json()).then(done, e => done(String(e)));", instance_id)

    def test_the_prediction_is_drawn_and_nothing_is_stored(self):
        d = self.driver
        WebDriverWait(d, 20).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, ".vol-view[data-axis='axial'] .vol-overlay")))
        self.assertGreater(self.wait_for(lambda: self.painted() > 0 and self.painted(), 20), 0)
        time.sleep(1.5)
        self.assertNothingStored("c1")
        self.assertEqual(self.console_errors(), [])

    def test_a_brush_stroke_stores_the_masks_and_they_come_back(self):
        d = self.driver
        WebDriverWait(d, 20).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, ".vol-view[data-axis='axial'] .vol-overlay")))
        before = self.wait_for(lambda: self.painted() > 0 and self.painted(), 20)
        d.find_element(By.CSS_SELECTOR, ".tool-btn[data-tool='brush']").click()
        d.find_element(By.CSS_SELECTOR, ".vol-label-btn[data-label='Lesion']").click()
        stage = d.find_element(By.CSS_SELECTOR, ".vol-view[data-axis='axial'] .vol-stage")
        w, h = stage.size["width"], stage.size["height"]
        ActionChains(d).move_to_element_with_offset(stage, int(w * 0.3), int(h * 0.3)) \
            .click_and_hold().move_by_offset(int(w * 0.1), int(h * 0.1)).release().perform()
        time.sleep(1.5)
        self.assertGreater(self.painted(), before)
        stored = self.stored("c1")
        self.assertIn("Lesion", json.dumps(stored))
        d.find_element(By.ID, "next-btn").click()
        time.sleep(2)
        d.find_element(By.ID, "prev-btn").click()
        WebDriverWait(d, 20).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, ".vol-view[data-axis='axial'] .vol-overlay")))
        self.assertGreaterEqual(self.wait_for(lambda: self.painted() > 0 and self.painted(), 20),
                                before)

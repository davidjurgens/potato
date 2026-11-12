"""A video-track prediction shown on a tracking video_annotation scheme.

The prediction has normalized boxes only (the server cannot know the
annotator's canvas pixels). The page must put them in its own pixels and
draw them, list the track, and store nothing while the annotator only looks.
"""

import os
import shutil
import subprocess
import time

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from potato.training.tracking import track_payload
from tests.selenium.test_vision_prelabel_ui import _Base

if not shutil.which("ffmpeg"):
    pytest.skip("ffmpeg absent", allow_module_level=True)

PAYLOAD = track_payload([{"label": "box", "keyframes": [
    [0, 0.25, 0.25, 0.5, 0.5, 0.9], [39, 0.25, 0.25, 0.5, 0.5, 0.9]]}], 10, 4.0, 160, 120, "m1")
PAYLOAD["tracks"]["track_1"]["color"] = "#ff0000"


class TestTrackPrelabel(_Base):
    preferred_port = 9877
    schemes = [{"annotation_type": "video_annotation", "name": "trk", "description": "Track it",
                "mode": "tracking", "labels": ["box"], "video_fps": 10,
                "source_field": "video_url"}]
    item = {"id": "v1", "text": "clip", "video_url": "/media/clip.mp4",
            "predictions": {"trk": PAYLOAD}}
    more_items = [{"id": "v2", "text": "clip 2", "video_url": "/media/clip.mp4"}]

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        "testsrc=duration=4:size=160x120:rate=10", "-pix_fmt", "yuv420p",
                        "-c:v", "libx264", os.path.join(cls.test_dir, "media", "clip.mp4")],
                       check=True)

    def red_pixels(self):
        return self.driver.execute_script("""
            const c = document.querySelector('.tracking-overlay, canvas.tracking-canvas, '
                + '.video-annotation-container canvas');
            if (!c || !c.width) return -1;
            const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
            let n = 0;
            for (let i = 0; i < d.length; i += 4) if (d[i+3] > 0 && d[i] > 200 && d[i+1] < 80) n++;
            return n;""")

    def test_the_track_is_listed_drawn_and_not_stored(self):
        d = self.driver
        WebDriverWait(d, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, "video")))
        WebDriverWait(d, 20).until(lambda drv: drv.execute_script(
            "const v = document.querySelector('video'); return v && v.readyState >= 1;"))
        listed = self.wait_for(lambda: d.execute_script(
            "return document.body.innerText.includes('track_1') "
            "|| Array.from(document.querySelectorAll('[class*=track]')).some("
            "e => /box/.test(e.textContent));"), 15)
        self.assertTrue(listed, "the predicted track is not listed")
        self.assertGreater(self.wait_for(lambda: self.red_pixels() > 0 and self.red_pixels(), 15)
                           or 0, 0)
        time.sleep(1.5)
        self.assertNothingStored("v1")

    def box_on_picture(self):
        """The red box's left edge as a fraction of the video picture on the
        page (the overlay keeps its pixel size when the page reflows)."""
        return self.driver.execute_script("""
            const v = document.querySelector('video'), c = document.querySelector('.tracking-overlay');
            if (!v || !c || !c.width || !v.videoWidth) return null;
            const cr = c.getBoundingClientRect(), vr = v.getBoundingClientRect();
            const sx = c.width / cr.width;
            const s = Math.min(vr.width / v.videoWidth, vr.height / v.videoHeight);
            const pw = v.videoWidth * s, px = vr.left + (vr.width - pw) / 2;
            const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
            let left = null;
            for (let i = 0; i < d.length; i += 4) {
                if (d[i+3] > 0 && d[i] > 200 && d[i+1] < 80 && d[i+2] < 80) {
                    const x = (i / 4) % c.width;
                    if (left === null || x < left) left = x;
                }
            }
            return left === null ? null : (cr.left + left / sx - px) / pw;""")

    def test_the_track_box_follows_a_resize(self):
        """Audit 105 P3: the box was put in canvas pixels once and stayed
        there after the window was resized (0.14 of the picture, not 0.25)."""
        d = self.driver
        WebDriverWait(d, 20).until(lambda drv: drv.execute_script(
            "const v = document.querySelector('video');"
            "return v && v.videoWidth > 0 && v.readyState >= 2;"))
        before = self.wait_for(self.box_on_picture, 15)
        self.assertIsNotNone(before)
        self.assertAlmostEqual(before, 0.25, delta=0.03)
        d.set_window_size(900, 1400)
        time.sleep(2)
        after = self.wait_for(self.box_on_picture, 10)
        self.assertIsNotNone(after)
        self.assertAlmostEqual(after, 0.25, delta=0.03)

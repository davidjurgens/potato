"""A whisper-asr correction suggestion shown on a speech_transcript scheme.

The item carries the prediction in its ``predictions`` field, where training
write-back puts it. The page shows it in the turn's correction box with the
error type selected, stores nothing while the annotator only looks, and
stores the annotator's edit of it.
"""

import json
import time

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from tests.selenium.test_vision_prelabel_ui import _Base


class TestTranscriptPrelabel(_Base):
    preferred_port = 9871
    schemes = [{"annotation_type": "speech_transcript", "name": "st",
                "description": "Correct the transcript"}]
    item = {"id": "a1", "text": "talk", "audio": "/media/talk.wav", "segments": [
        {"start": 0.0, "end": 1.0, "speaker": "A", "text": "the bat sat"},
        {"start": 1.0, "end": 2.0, "speaker": "B", "text": "on the mat"}],
        "predictions": {"st": [{"index": 0, "start": 0.0, "end": 1.0,
                                "errors": ["asr_error"], "correction": "the cat sat",
                                "source": "ai", "confidence": 0.8},
                               {"index": 9, "correction": "no such turn"}]}}
    more_items = [{"id": "a2", "text": "talk 2", "audio": "/media/talk.wav", "segments": [
        {"start": 0.0, "end": 1.0, "speaker": "A", "text": "hello"}]}]

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import os
        import wave
        with wave.open(os.path.join(cls.test_dir, "media", "talk.wav"), "wb") as fh:
            fh.setnchannels(1)
            fh.setsampwidth(2)
            fh.setframerate(8000)
            fh.writeframes(b"\x00\x00" * 16000)

    def corrections(self):
        return self.driver.execute_script(
            "return Array.from(document.querySelectorAll('.st-correction'))"
            ".map(i => i.value);")

    def stored(self, instance_id):
        return self.driver.execute_async_script(
            "var done = arguments[arguments.length - 1];"
            "fetch('/get_annotations?instance_id=' + arguments[0], {credentials: 'same-origin'})"
            ".then(r => r.json()).then(done, e => done(String(e)));", instance_id)

    def test_the_suggestion_fills_its_turn_and_nothing_is_stored(self):
        d = self.driver
        WebDriverWait(d, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".st-card")))
        self.assertEqual(self.wait_for(self.corrections), ["the cat sat", ""])
        selected = d.execute_script(
            "return Array.from(document.querySelectorAll('.st-ebtn.selected'))"
            ".map(b => [b.dataset.idx, b.dataset.e]);")
        self.assertEqual(selected, [["0", "asr_error"]])
        self.assertIn("st-flagged", d.find_element(
            By.CSS_SELECTOR, ".st-card[data-idx='0']").get_attribute("class"))
        time.sleep(1.5)
        self.assertNothingStored("a1")
        self.assertEqual(self.console_errors(), [])

    def test_an_edited_suggestion_is_stored_and_comes_back(self):
        d = self.driver
        WebDriverWait(d, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".st-correction")))
        self.wait_for(self.corrections)
        box = d.find_elements(By.CSS_SELECTOR, ".st-correction")[0]
        box.clear()
        box.send_keys("the cat sat down")
        time.sleep(1.5)
        d.find_element(By.ID, "next-btn").click()
        WebDriverWait(d, 10).until(lambda drv: self.corrections() == [""])
        d.find_element(By.ID, "prev-btn").click()
        WebDriverWait(d, 10).until(lambda drv: len(self.corrections()) == 2)
        self.assertEqual(self.corrections()[0], "the cat sat down")
        stored = self.stored("a1")
        self.assertIn("the cat sat down", json.dumps(stored), stored)

    def test_a_cleared_suggestion_stays_cleared(self):
        """Audit 103 A-P1a: clearing the suggestion saved nothing, so it came
        back on the next visit."""
        d = self.driver
        WebDriverWait(d, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".st-correction")))
        self.wait_for(self.corrections)
        box = d.find_elements(By.CSS_SELECTOR, ".st-correction")[0]
        box.click()
        box.send_keys(Keys.COMMAND, "a")
        box.send_keys(Keys.CONTROL, "a")
        box.send_keys(Keys.BACKSPACE)
        d.find_element(By.CSS_SELECTOR, ".st-card[data-idx='0'] .st-ebtn.selected").click()
        time.sleep(1.5)
        d.find_element(By.ID, "next-btn").click()
        WebDriverWait(d, 10).until(lambda drv: self.corrections() == [""])
        d.find_element(By.ID, "prev-btn").click()
        WebDriverWait(d, 10).until(lambda drv: len(self.corrections()) == 2)
        time.sleep(0.5)
        self.assertEqual(self.corrections(), ["", ""])
        self.assertEqual(d.find_elements(By.CSS_SELECTOR, ".st-ebtn.selected"), [])
        d.refresh()
        WebDriverWait(d, 10).until(lambda drv: len(self.corrections()) == 2)
        self.assertEqual(self.corrections(), ["", ""])


class TestTwoTranscriptSchemes(_Base):
    """Audit 103 A-P1b: each scheme painted cards by index across the page,
    so one scheme's flags showed on the other's cards."""
    preferred_port = 9873
    schemes = [{"annotation_type": "speech_transcript", "name": "st", "description": "ASR"},
               {"annotation_type": "speech_transcript", "name": "st2", "description": "TTS",
                "segments_key": "tts"}]
    turns = [{"start": 0.0, "end": 1.0, "text": "one"}, {"start": 1.0, "end": 2.0, "text": "two"}]
    item = {"id": "b1", "text": "talk", "segments": turns, "tts": turns, "predictions": {
        "st": [{"index": 0, "errors": ["asr_error"], "correction": "won"},
               {"index": 1, "errors": ["disfluency"], "correction": "too"}],
        "st2": [{"index": 1, "errors": ["asr_error"], "correction": "to"}]}}
    more_items = [{"id": "b2", "text": "x", "segments": turns, "tts": turns}]

    def selected(self, schema):
        return self.driver.execute_script(
            "return Array.from(document.querySelectorAll("
            "'form[data-schema-name=\"' + arguments[0] + '\"] .st-ebtn.selected'))"
            ".map(b => b.dataset.idx + ':' + b.dataset.e);", schema)

    def test_each_scheme_paints_its_own_cards(self):
        d = self.driver
        WebDriverWait(d, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".st-card")))
        self.assertEqual(sorted(self.wait_for(lambda: self.selected("st"))),
                         ["0:asr_error", "1:disfluency"])
        self.assertEqual(self.selected("st2"), ["1:asr_error"])
        d.find_element(By.CSS_SELECTOR,
                       "form[data-schema-name='st2'] .st-card[data-idx='0'] .st-ebtn").click()
        time.sleep(0.3)
        self.assertEqual(sorted(self.selected("st")), ["0:asr_error", "1:disfluency"])
        self.assertEqual(sorted(self.selected("st2")), ["0:asr_error", "1:asr_error"])
        flagged = d.execute_script(
            "return Array.from(document.querySelectorAll('form[data-schema-name=\"st\"] "
            ".st-card.st-flagged')).length;")
        self.assertEqual(flagged, 2)

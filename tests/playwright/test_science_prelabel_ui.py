"""
Model predictions on the science schemes, in a real browser: a peak-cnn
prediction as review suggestions on a spectrum, signal-cnn intervals as
pre-annotations on a recording, and an episode-model answer pre-filled on
the episode timeline. Each is read from the item's ``predictions`` field,
as write-back stores it, through ``pre_annotation``.

For each: the page shows the prediction as the model's, stores nothing
while the annotator only looks, and stores what the annotator accepts,
which survives navigating away and back.
"""

import json
import math
import os

import pytest

pytest.importorskip("playwright.sync_api")

from tests.helpers.test_utils import create_test_directory  # noqa: E402
from tests.playwright.test_base import BasePlaywrightTest  # noqa: E402
from tests.playwright.viewer_keys import keys_reserved_for, keys_taken_page_wide  # noqa: E402

pytestmark = pytest.mark.playwright

PRELABELS = {"pre_annotation": {"enabled": True, "field": "predictions"}}


def _spectrum(centres):
    xs = [i * 10.0 / 1999 for i in range(2000)]
    ys = [sum(math.exp(-0.5 * ((x - c) / 0.03) ** 2) for c in centres) + 0.01 for x in xs]
    return {"x": xs, "y": ys, "x_units": "PPM", "kind": "nmr"}


def _stored(page, server, instance_id):
    return page.evaluate(
        "async ([u, i]) => (await fetch(u + '/get_annotations?instance_id=' + i,"
        " {credentials: 'same-origin'})).json()", [server.base_url, instance_id])


def _wait_instance(page, instance_id):
    page.wait_for_function(
        "document.getElementById('instance_id').value === %s" % json.dumps(instance_id),
        timeout=15000)


class TestSpectrumModelSuggestions(BasePlaywrightTest):
    SCHEMES = [{"annotation_type": "peak_picking", "name": "picks",
                "description": "Pick the peaks", "viewer_field": "spectrum"}]

    @pytest.fixture
    def spectrum_server(self, make_server):
        prediction = {"peaks": [{"x": 2.0, "confidence": 0.91}, {"x": 6.0, "confidence": 0.62}],
                      "x_range": [0, 10], "source": "model"}
        return make_server(self.SCHEMES, items=[
            {"id": "sp1", "text": "first", "spectrum": _spectrum([2.0, 6.0]),
             "predictions": {"picks": prediction}},
            {"id": "sp2", "text": "second", "spectrum": _spectrum([4.0])}],
            extra_config=dict(PRELABELS, instance_display={"fields": [
                {"key": "spectrum", "type": "spectrum",
                 "display_options": {"prepick": True}}]}))

    def _open(self, page, server):
        page.errors = []
        page.on("pageerror", lambda e: page.errors.append(str(e)))
        self.register_and_login(page, server)
        page.goto(f"{server.base_url}/annotate")
        page.wait_for_function(
            "document.querySelector('.potato-viewer')"
            " && document.querySelector('.potato-viewer').getAttribute('data-viewer-state')"
            " === 'ready'", timeout=30000)
        page.wait_for_timeout(300)

    def _suggestions(self, page):
        return page.eval_on_selector_all(".pp-suggestions .pp-sugg .pp-pos",
                                         "els => els.map(e => e.textContent.trim())")

    def _rows(self, page):
        return page.eval_on_selector_all(
            ".pp-peak-table tbody tr",
            "rows => rows.map(r => [r.cells[0].textContent.trim(),"
            " r.querySelector('.pp-source').textContent.trim()])")

    def test_model_peaks_are_suggestions_marked_as_the_model_s(self, page, spectrum_server):
        self._open(page, spectrum_server)
        suggestions = self._suggestions(page)
        assert len(suggestions) == 2 and all(s.endswith("· model") for s in suggestions)
        page.wait_for_timeout(1500)
        stored = _stored(page, spectrum_server, "sp1")
        assert not any(stored.get(k) for k in ("label_annotations", "label_values")), stored
        assert page.errors == []

    def test_an_accepted_model_peak_is_stored_as_the_model_s_and_comes_back(
            self, page, spectrum_server):
        self._open(page, spectrum_server)
        page.locator(".pp-suggestions .pp-accept").first.click()
        page.wait_for_timeout(1500)
        rows = self._rows(page)
        assert len(rows) == 1 and rows[0][1] == "model"
        stored = json.loads(_stored(page, spectrum_server, "sp1")["label_values"]["picks"]["picks"])
        assert [(i["x"], i["source"]) for i in stored["items"]] == [(6, "model")], stored
        page.click("#next-btn")
        _wait_instance(page, "sp2")
        # No prediction on the second item: the detector's suggestions.
        page.wait_for_function(
            "document.querySelector('.potato-viewer').getAttribute('data-viewer-state') === 'ready'")
        assert not any(s.endswith("· model") for s in self._suggestions(page))
        page.click("#prev-btn")
        _wait_instance(page, "sp1")
        page.wait_for_function(
            "document.querySelector('.pp-peak-table tbody tr')", timeout=15000)
        assert self._rows(page) == rows
        # The other model peak is still waiting for review.
        assert len(self._suggestions(page)) == 1
        assert page.errors == []


class TestSignalModelIntervals(BasePlaywrightTest):
    SCHEMES = [{"annotation_type": "interval_label", "name": "segs",
                "description": "Mark artefacts", "signal_field": "signal", "mode": "free",
                "labels": [{"name": "artefact", "key_value": "1"},
                           {"name": "spindle", "key_value": "2"}]}]

    @pytest.fixture
    def signal_server(self, make_server):
        signal = {"sampling_rate": 20, "channels": [
            {"name": "Fz", "unit": "uV", "data": [math.sin(k / 3.0) for k in range(600)]}]}
        prediction = {"intervals": [
            {"start": 2.0, "end": 5.0, "label": "artefact", "channel": None,
             "source": "model", "confidence": 0.8},
            {"start": 7.0, "end": 8.0, "label": "unknown", "channel": None}],
            "events": [], "source": "model"}
        return make_server(self.SCHEMES, items=[
            {"id": "r1", "text": "first", "signal": signal, "predictions": {"segs": prediction}},
            {"id": "r2", "text": "second", "signal": signal}],
            extra_config=dict(PRELABELS, instance_display={"fields": [
                {"key": "signal", "type": "time_series",
                 "display_options": {"window": 30}}]}))

    def _rows(self, page):
        return page.eval_on_selector_all(
            "form.interval-label .il-list tbody tr",
            "rows => rows.map(r => [...r.cells].slice(0, 3).map(c => c.textContent.trim()))")

    def _open(self, page, server):
        page.errors = []
        page.on("pageerror", lambda e: page.errors.append(str(e)))
        self.register_and_login(page, server)
        page.goto(f"{server.base_url}/annotate")
        page.wait_for_function(
            "[...document.querySelectorAll('form.interval-label')]"
            ".every(f => f.getAttribute('data-il-ready'))", timeout=30000)

    def test_every_key_the_plot_takes_is_reserved(self, page, signal_server):
        # keybinding_allocator keeps sequential label keys off these; a key the
        # plot takes that is not listed would go to a label and do nothing.
        self._open(page, signal_server)
        assert keys_taken_page_wide(page) - keys_reserved_for(self.SCHEMES[0]) == set()

    def test_model_intervals_are_pre_annotations_from_the_model(self, page, signal_server):
        self._open(page, signal_server)
        page.wait_for_function("document.querySelector('form.interval-label .il-list tbody tr')",
                               timeout=15000)
        # The unknown label is left out; the artefact says where it came from.
        assert self._rows(page) == [["0:02.0–0:05.0", "artefact · from the model", "all"]]
        assert page.eval_on_selector("form.interval-label .il-row",
                                     "r => r.classList.contains('il-from-model')")
        assert page.errors == []

    def test_model_intervals_are_saved_with_the_first_change_and_come_back(
            self, page, signal_server):
        self._open(page, signal_server)
        page.wait_for_function("document.querySelector('form.interval-label .il-list tbody tr')",
                               timeout=15000)
        assert "from the model" in page.text_content("form.interval-label .il-pre-text")
        # The first change: a spindle dragged from 10 s to 12 s.
        page.keyboard.press("2")
        page.evaluate("window.PotatoTimeSeries.get('signal').u.over.scrollIntoView({block: 'center'})")
        x = lambda t: page.evaluate(  # noqa: E731
            "t => { const p = window.PotatoTimeSeries.get('signal');"
            " return p.u.over.getBoundingClientRect().x + p.u.valToPos(t, 'x'); }", t)
        y = page.evaluate("(() => { const r = window.PotatoTimeSeries.get('signal').u.over"
                          ".getBoundingClientRect(); return r.y + r.height / 2; })()")
        page.mouse.move(x(10.0), y)
        page.mouse.down()
        page.mouse.move(x(11.0), y, steps=4)
        page.mouse.move(x(12.0), y, steps=4)
        page.mouse.up()
        page.wait_for_timeout(1500)
        assert not page.is_visible("form.interval-label .il-pre")
        page.click("#next-btn")
        _wait_instance(page, "r2")
        assert self._rows(page) == []
        page.click("#prev-btn")
        _wait_instance(page, "r1")
        page.wait_for_function("document.querySelector('form.interval-label .il-list tbody tr')",
                               timeout=15000)
        rows = self._rows(page)
        assert [r[1] for r in rows] == ["artefact · from the model", "spindle"], rows
        stored = json.loads(_stored(page, signal_server, "r1")["label_values"]["segs"]["segs"])
        assert [(iv["label"], iv.get("source")) for iv in stored["intervals"]] == [
            ("artefact", "model"), ("spindle", None)], stored


class TestEpisodeModelAnswer(BasePlaywrightTest):
    SCHEMES = [{"annotation_type": "episode_annotation", "name": "review",
                "description": "Mark the phases", "source_field": "episode",
                "layers": ["phases", "outcome", "reward"],
                "phases": [{"name": "reach", "key_value": "1"}, {"name": "grasp", "key_value": "2"}],
                "outcomes": ["success", "failure"], "reward_range": [0.0, 1.0]}]

    @pytest.fixture
    def episode_server(self, make_server):
        media = create_test_directory("episode_prelabel_media")
        for name in ("ep0", "ep1"):
            os.makedirs(os.path.join(media, name), exist_ok=True)
            with open(os.path.join(media, name, "episode.json"), "w") as fh:
                json.dump({"episode_id": name, "fps": 10, "num_frames": 50, "series": [
                    {"name": "gripper", "values": [0.0] * 25 + [1.0] * 25}]}, fh)
        prediction = {"phases": [{"start": 0.0, "end": 2.5, "label": "reach"},
                                 {"start": 2.5, "end": 5.0, "label": "grasp"},
                                 {"start": 1.0, "end": 2.0, "label": "dance"}],
                      "outcome": {"result": "success", "cause": ""},
                      "reward": [{"t": 0.0, "value": 0.1}, {"t": 5.0, "value": 0.9}],
                      "instructions": []}
        return make_server(self.SCHEMES, items=[
            {"id": "ep0", "text": "first", "episode": "ep0/episode.json",
             "predictions": {"review": prediction}},
            {"id": "ep1", "text": "second", "episode": "ep1/episode.json"}],
            extra_config=dict(PRELABELS, media_directory=media))

    def _open(self, page, server):
        page.errors = []
        page.on("pageerror", lambda e: page.errors.append(str(e)))
        self.register_and_login(page, server)
        page.goto(f"{server.base_url}/annotate")
        page.wait_for_function(
            "(() => { const c = document.querySelector('.episode-annotation-container');"
            " return c && c.annotationManager && c.annotationManager.episode; })()",
            timeout=30000)

    def _manager(self, page):
        return page.evaluate(
            "(() => { const m = document.querySelector('.episode-annotation-container')"
            ".annotationManager; return {phases: m.phases, outcome: m.outcome,"
            " reward: m.reward}; })()")

    def test_the_model_s_answer_is_pre_filled_and_not_stored(self, page, episode_server):
        self._open(page, episode_server)
        state = self._manager(page)
        assert [p["label"] for p in state["phases"]] == ["reach", "grasp"]
        assert state["outcome"]["result"] == "success" and len(state["reward"]) == 2
        assert page.eval_on_selector(
            ".episode-outcome input[value='success']", "r => r.checked")
        page.wait_for_timeout(1500)
        stored = _stored(page, episode_server, "ep0")
        assert not any(stored.get(k) for k in ("label_annotations", "label_values")), stored
        assert page.errors == []

    def test_an_edited_model_answer_is_stored_and_comes_back(self, page, episode_server):
        self._open(page, episode_server)
        page.check(".episode-outcome input[value='failure']")
        page.wait_for_timeout(1500)
        page.click("#next-btn")
        _wait_instance(page, "ep1")
        assert self._manager(page)["phases"] == []
        page.click("#prev-btn")
        _wait_instance(page, "ep0")
        page.wait_for_function(
            "(() => { const c = document.querySelector('.episode-annotation-container');"
            " return c && c.annotationManager && c.annotationManager.episode; })()",
            timeout=30000)
        state = self._manager(page)
        assert state["outcome"]["result"] == "failure"
        assert [p["label"] for p in state["phases"]] == ["reach", "grasp"]
        assert page.eval_on_selector(".episode-outcome input[value='failure']", "r => r.checked")

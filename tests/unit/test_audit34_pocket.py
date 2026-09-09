"""Pocket mode: what it renders, what it stores, and what it says about work
it has not sent.

Rounds 34 and 35, all measured in Chrome at phone width before being
reproduced here.

The recurring shape is the one the whole session has been about: the phone
surface reports a state it is not in. "Syncing" against a server that is
refusing. "All caught up" over two unsent saves. A bare 1-5 where the desktop
shows anchors. And, most seriously, an annotator who receives no quality
control at all while `items_since_attention` counts every save they make.
"""

import json
import os

import pytest


# ----------------------------------------------------------------------
# 1. The capable-types set is a real list of real types
# ----------------------------------------------------------------------

def test_every_pocket_capable_type_exists():
    """`textbox` was in the set and is not one of the registry's annotation
    types; the free-text type is `text`, which is also there. Harmless until
    someone reads the set as the list of what works, which is its only job."""
    from potato.pocket.config import POCKET_CAPABLE_TYPES
    from potato.server_utils.schemas.registry import schema_registry

    known = set(schema_registry.get_supported_types())
    unknown = sorted(POCKET_CAPABLE_TYPES - known)
    assert not unknown, (
        f"POCKET_CAPABLE_TYPES names {unknown}, which the schema registry does "
        "not have. A dead entry here reads as a supported type.")


def test_the_free_text_type_is_still_capable():
    """Dropping the dead name must not drop the working one alongside it."""
    from potato.pocket.config import POCKET_CAPABLE_TYPES

    assert "text" in POCKET_CAPABLE_TYPES


# ----------------------------------------------------------------------
# 2. The likert reaches the phone whole
# ----------------------------------------------------------------------

LIKERT = {
    "annotation_type": "likert",
    "name": "confidence_scale",
    "description": "How sure are you?",
    "size": 5,
    "min_label": "Not at all",
    "max_label": "Certain",
}


def test_the_anchors_are_sent_to_the_client():
    """Potato *requires* min_label and max_label on a likert -- a config
    without them fails validate -- and the desktop page renders both. The
    phone spec forwarded min/max/size and neither anchor, so the same scheme
    meant one thing on /annotate and another on /pocket."""
    from potato.pocket.routes import _scheme_spec

    spec = _scheme_spec(LIKERT)
    assert spec["min_label"] == "Not at all"
    assert spec["max_label"] == "Certain"


def test_the_spec_still_carries_what_it_carried_before():
    from potato.pocket.routes import _scheme_spec

    spec = _scheme_spec(LIKERT)
    assert spec["size"] == 5
    assert spec["name"] == "confidence_scale"
    assert spec["description"] == "How sure are you?"


class TestTheLikertOnThePhone:
    """Boots the real module with one likert item and clicks scale point 3."""

    def test_the_anchors_are_rendered(self):
        """The phone drew five bare numbered buttons. An unlabeled 1-5 means a
        different thing to each annotator, and the desktop shows both ends of
        the same scheme."""
        r = _harness("likert")
        assert r["legend"] is not None, (
            "no anchor row was rendered, so the scale has no ends")
        assert "Not at all" in r["legend"] and "Certain" in r["legend"], (
            r["legend"])

    def test_the_ends_are_announced(self):
        """A screen reader reading "1, 2, 3, 4, 5" has the same problem the
        sighted annotator has."""
        r = _harness("likert")
        assert "Not at all" in r["aria_labels"][0], r["aria_labels"]
        assert "Certain" in r["aria_labels"][-1], r["aria_labels"]

    def test_the_points_are_still_numbered(self):
        r = _harness("likert")
        assert r["button_labels"] == ["1", "2", "3", "4", "5"]

    def test_it_stores_the_label_name_the_desktop_stores(self):
        """Not a spelling difference, a KEY difference. `likert.py` writes
        `Label(schema, "3")`; pocket wrote `Label(schema, "scale_3")`. Two
        annotators picking the same scale point on the two surfaces produced
        two different labels, so agreement read them as having answered
        different questions rather than agreeing."""
        r = _harness("likert")
        assert r["sent_annotations"] == {"confidence_scale:3": "3"}, (
            f"the phone posted {r['sent_annotations']}; the annotation page "
            "posts confidence_scale:3 for the same click")


# ----------------------------------------------------------------------
# 3. The queue tells the truth
# ----------------------------------------------------------------------

def _harness(scenario):
    """Run pocket.js under node against a stub DOM and return what it did.

    Grepping the source for `visibilitychange` passes a rename and fails a
    refactor, which is backwards, and it cannot tell whether the listener does
    anything. This boots the real module, fires the real listener, and reads
    the resulting chip text and queue -- so the assertions below are about
    behaviour. The Chrome pass drives the same paths against a real browser;
    this one runs in CI.
    """
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")

    here = os.path.dirname(os.path.abspath(__file__))
    harness = os.path.join(os.path.dirname(here), "helpers", "pocket_harness.js")
    out = subprocess.run([node, harness, scenario], capture_output=True,
                         text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    payload = json.loads(out.stdout.strip().splitlines()[-1])
    assert "error" not in payload, payload["error"]
    return payload


class TestTheQueueDoesNotMisreportItself:
    """Driven, not grepped: the module boots, the tab becomes visible, and we
    read what it says."""

    def test_a_refusal_stops_the_retry_and_says_what_fixes_it(self):
        """A 401 and a lost connection were the same event: every non-2xx
        became one Error and the record stayed queued. A restart of a default
        config produces it -- no secret_key, so the session does not survive --
        and the chip read "Syncing 2 saves…" indefinitely while the annotator
        was never told to sign in again."""
        r = _harness("refused")
        assert r["chip"]["blocked"] is True, r["chip"]
        assert "sign in" in r["chip"]["text"].lower(), r["chip"]["text"]
        assert "syncing" not in r["chip"]["text"].lower(), (
            "the chip still claims the saves are on their way to a server "
            "that is refusing them")

    def test_a_refusal_keeps_the_work(self):
        """Nothing is discarded: the records drain after signing in."""
        r = _harness("refused")
        assert r["queue_length"] == 2

    def test_the_card_render_time_reaches_the_server(self):
        """`min_response_time` is read from `response_time_seconds` on the
        request body. pocket.js sent instance_id, annotations and
        span_annotations only, so an attention check served to a phone could
        not fail on time -- and would show on the admin page as PASSED."""
        r = _harness("refused")
        assert "response_time_seconds" in r["sent_keys"], r["sent_keys"]
        assert r["sent_response_time"] == 4.25

    def test_coming_back_to_the_tab_drains_the_queue(self):
        """The only triggers were the browser's `online` event and a
        successful save. A phone that keeps its network and loses the server
        never fires `online`, and an annotator at the end of their batch has
        no next save to piggyback on, so there was no way back without a
        reload."""
        r = _harness("flush_succeeds")
        assert r["visibility_listeners"] >= 1, (
            "nothing listens for the tab becoming visible")
        assert r["queue_length"] == 0, (
            "the queue survived a visibilitychange against a working server")

    def test_there_is_also_a_timer(self):
        """Because the outage may heal while the tab is already in front of
        them."""
        r = _harness("triggers")
        assert r["interval_count"] >= 1
        assert r["interval_ms"] >= 5000, (
            f"a {r['interval_ms']}ms flush loop is a busy-wait on a phone")

    def test_all_caught_up_is_not_shown_over_unsent_work(self):
        """With batch_size 3 on a six-item study, finishing the third item
        rendered "Every item in your queue is annotated" while the header said
        "4 of 6" and two saves were unsent. That is the sentence someone reads
        before closing the tab."""
        r = _harness("done_with_queue")
        assert "all caught up" not in r["main"].lower(), r["main"]
        assert "2 answers still to send" in r["main"], r["main"]
        assert "nothing is lost" in r["main"].lower()

    def test_all_caught_up_is_shown_when_it_is_true(self):
        r = _harness("done_empty")
        assert "All caught up" in r["main"], r["main"]

    def test_the_end_screen_updates_when_the_queue_drains(self):
        """Found by this harness rather than by the audit: the count stayed at
        "2 answers still to send" after both had gone."""
        r = _harness("flush_succeeds")
        assert r["queue_length"] == 0
        assert "still to send" not in r["main"], r["main"]
        assert "All caught up" in r["main"], r["main"]


# ----------------------------------------------------------------------
# 4. Quality control reaches the phone
# ----------------------------------------------------------------------

class TestQualityControlOnThePhone:

    def _qc(self, attention_frequency=3, gold_frequency=None, task=None):
        from potato.quality_control import QualityControlManager
        from tests.helpers.test_utils import create_test_directory

        task_dir = create_test_directory(task or "audit35_qc")
        checks = os.path.join(task_dir, "checks.json")
        with open(checks, "w", encoding="utf-8") as fh:
            json.dump([{"id": "chk1", "text": "Pick Sarcastic.",
                        "expected_answer": {"sarcasm": "Sarcastic"}}], fh)
        config = {
            "output_annotation_dir": os.path.join(task_dir, "out"),
            "annotation_schemes": [
                {"annotation_type": "radio", "name": "sarcasm",
                 "labels": ["Sarcastic", "Sincere"]}],
            "attention_checks": {"enabled": True, "items_file": checks,
                                 "frequency": attention_frequency},
        }
        if gold_frequency:
            gold = os.path.join(task_dir, "gold.json")
            with open(gold, "w", encoding="utf-8") as fh:
                json.dump([{"id": "g1", "text": "Obvious.",
                            "gold_label": {"sarcasm": "Sincere"}}], fh)
            config["gold_standards"] = {"enabled": True, "items_file": gold,
                                        "frequency": gold_frequency,
                                        "mode": "mixed"}
        return QualityControlManager(config, task_dir)

    def _bound(self, qc, requested, username="phone", monkeypatch=None):
        import potato.quality_control as qc_mod
        from potato.pocket import routes as pocket_routes

        monkeypatch.setattr(qc_mod, "get_quality_control_manager",
                            lambda: qc)
        return pocket_routes._bound_batch_to_qc_frequency(username, requested)

    def test_the_batch_is_capped_so_the_frequency_holds(self, monkeypatch):
        """The injector adds ONE item and resets the counter, so a phone that
        prefetches 25 gets one check per 25 items whatever `frequency` says.
        Capping the batch is what makes the configured number true."""
        qc = self._qc(attention_frequency=3)
        assert self._bound(qc, 25, monkeypatch=monkeypatch) == 3

    def test_a_partly_used_allowance_shortens_the_batch(self, monkeypatch):
        qc = self._qc(attention_frequency=3, task="audit35_partly")
        qc.user_items_since_attention["phone"] = 2
        assert self._bound(qc, 25, monkeypatch=monkeypatch) == 1

    def test_the_tighter_of_the_two_frequencies_wins(self, monkeypatch):
        qc = self._qc(attention_frequency=5, gold_frequency=2,
                      task="audit35_two")
        assert self._bound(qc, 25, monkeypatch=monkeypatch) == 2

    def test_a_small_request_is_not_enlarged(self, monkeypatch):
        qc = self._qc(attention_frequency=10, task="audit35_small")
        assert self._bound(qc, 4, monkeypatch=monkeypatch) == 4

    def test_no_quality_control_leaves_the_batch_alone(self, monkeypatch):
        import potato.quality_control as qc_mod
        from potato.pocket import routes as pocket_routes

        monkeypatch.setattr(qc_mod, "get_quality_control_manager",
                            lambda: None)
        assert pocket_routes._bound_batch_to_qc_frequency("phone", 25) == 25

    def test_a_frequencyless_config_leaves_the_batch_alone(self, monkeypatch):
        """Probability-based injection has no rate to hold the batch to."""
        qc = self._qc(attention_frequency=None, task="audit35_prob")
        qc.qc_config.attention_probability = 0.1
        assert self._bound(qc, 25, monkeypatch=monkeypatch) == 25

    def test_the_batch_route_asks_for_an_injection(self, monkeypatch):
        """The call itself: the injector had exactly one caller and it was
        inside /annotate."""
        from potato.pocket import routes as pocket_routes
        from potato.server_utils import quality_control_injection as qci

        called = {}
        monkeypatch.setattr(
            qci, "inject_quality_control_item_if_needed",
            lambda u, s, c: called.setdefault("args", (u, s, c)))

        pocket_routes._inject_quality_control("phone", object())
        assert "args" in called, (
            "the phone batch never asked for a quality-control item, so an "
            "annotator on the phone is never checked")

    def test_the_injector_is_not_reached_through_potato_routes(self):
        """It has to live somewhere a blueprint can import at request time.

        `potato.routes` registers its views with `@app.route` at import, so
        importing it from inside a request on a LIVE server raises "View
        function mapping is overwriting an existing endpoint function" -- which
        the try/except then turns into a feature that is silently inert. Every
        unit test still passed, because in a test process nothing has
        registered the app yet. Found by driving a real server.
        """
        import inspect

        from potato.pocket import routes as pocket_routes

        source = inspect.getsource(pocket_routes._inject_quality_control)
        assert "from potato.routes import" not in source, (
            "the phone reaches the injector through potato.routes, which "
            "cannot be imported from a blueprint on a running server")

    def test_a_failing_injection_does_not_break_the_batch(self, monkeypatch):
        """An annotator who cannot be served a check must still be served
        their work."""
        from potato.pocket import routes as pocket_routes
        from potato.server_utils import quality_control_injection as qci

        def _boom(u, s, c):
            raise RuntimeError("no item store")

        monkeypatch.setattr(
            qci, "inject_quality_control_item_if_needed", _boom)
        pocket_routes._inject_quality_control("phone", object())  # no raise


# ----------------------------------------------------------------------
# 5. validate says what boot says
# ----------------------------------------------------------------------

def _validate(name, config_extra):
    import yaml
    from potato.validate_cli import validate_config_file
    from tests.helpers.test_utils import create_test_directory

    task_dir = create_test_directory(f"audit34_cfg_{name}")
    data_path = os.path.join(task_dir, "items.json")
    with open(data_path, "w", encoding="utf-8") as fh:
        json.dump([{"id": "s1", "text": "well that went great"}], fh)

    config = {
        "port": 8000, "annotation_task_name": "audit34",
        "task_dir": task_dir, "data_files": [data_path],
        "item_properties": {"id_key": "id", "text_key": "text"},
        "output_annotation_dir": os.path.join(task_dir, "out"),
        "annotation_schemes": [
            {"annotation_type": "radio", "name": "sarcasm",
             "description": "Sarcasm?", "labels": ["Sarcastic", "Sincere"]}],
    }
    config.update(config_extra)
    path = os.path.join(task_dir, "cfg.yaml")
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(config, fh)
    report = validate_config_file(path)
    assert report.ok, report.errors
    return report


def _pocket_warnings(report):
    return [w for w in report.other_warnings if "pocket" in w.lower()]


def test_an_uncapable_pocket_task_is_reported():
    """`pocket.enabled: true` with a span scheme validates clean; only the
    boot log says /pocket will explain rather than degrade, and the author
    finds out from a phone."""
    report = _validate("uncapable", {
        "pocket": {"enabled": True},
        "annotation_schemes": [
            {"annotation_type": "radio", "name": "sarcasm",
             "description": "Sarcasm?", "labels": ["Sarcastic", "Sincere"]},
            {"annotation_type": "span", "name": "cue",
             "description": "Mark the cue",
             "labels": ["cue"]}],
    })
    warnings = _pocket_warnings(report)
    assert warnings, report.other_warnings
    assert "cue" in warnings[0], warnings[0]


def test_a_capable_pocket_task_is_quiet():
    report = _validate("capable", {"pocket": {"enabled": True}})
    assert not _pocket_warnings(report), report.other_warnings


def test_pocket_off_is_quiet():
    report = _validate("off", {
        "pocket": {"enabled": False},
        "annotation_schemes": [
            {"annotation_type": "span", "name": "cue",
             "description": "Mark the cue", "labels": ["cue"]}],
    })
    assert not _pocket_warnings(report), report.other_warnings

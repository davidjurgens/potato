"""
Server integration tests for the single-select persistence fix (GH #167).

Drives a real Flask server through every workflow phase, changing a single-select
answer on each, and asserts that exactly one value survives — the final one — while the
behavioral revision trail still records that the annotator changed their mind.

The payloads posted here are byte-for-byte what ``static/annotation.js``
``saveAnnotations()`` sends, including the ``__phase_page__`` sentinel instance id used
for every non-annotation page.
"""

import json
import os
import time

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_data_file,
    create_test_directory,
    create_test_config,
    cleanup_test_directory,
)

PORT = 9167

ANNOTATION_SCHEMES = [
    {
        "annotation_type": "radio",
        "name": "veracity",
        "description": "Is this claim true?",
        "labels": ["True", "False", "Unverifiable"],
    },
    {
        "annotation_type": "likert",
        "name": "confidence",
        "description": "How confident are you?",
        "min_label": "Not confident",
        "max_label": "Very confident",
        "size": 5,
    },
    {
        "annotation_type": "multiselect",
        "name": "tags",
        "description": "Applicable tags",
        "labels": ["politics", "health", "science"],
    },
]

# Mirrors the annotation schemes so each phase page exercises both a likert and a radio.
SURVEY_QUESTIONS = [
    {
        "id": "1",
        "name": "familiarity",
        "description": "How familiar are you with this topic?",
        "annotation_type": "likert",
        "min_label": "Not at all",
        "max_label": "Expert",
        "size": 5,
    },
    {
        "id": "2",
        "name": "native_language",
        "description": "Is English your native language?",
        "annotation_type": "radio",
        "labels": ["Yes", "No"],
    },
]


@pytest.fixture(scope="module")
def server():
    """A server with consent, instructions, training, prestudy and poststudy phases."""
    test_dir = create_test_directory("single_select_persistence")
    try:
        create_test_data_file(
            test_dir,
            [{"id": f"item_{i}", "text": f"Claim {i}"} for i in range(1, 4)],
        )

        # Gold answers so the training phase actually engages. Without
        # `training.enabled` plus a data_file the /training route silently
        # auto-advances, and a test would exercise the next phase instead.
        with open(os.path.join(test_dir, "training_data.json"), "w") as f:
            json.dump({"training_instances": [{
                "id": "train_1",
                "text": "A practice claim",
                "correct_answers": {"veracity": "True"},
                "explanation": "It is true.",
            }]}, f)

        surveys = os.path.join(test_dir, "surveys")
        os.makedirs(surveys, exist_ok=True)
        for page in ("consent", "instructions", "training", "prestudy", "poststudy"):
            with open(os.path.join(surveys, f"{page}.json"), "w") as f:
                json.dump(SURVEY_QUESTIONS, f)

        config_file = create_test_config(
            test_dir,
            ANNOTATION_SCHEMES,
            data_files=["test_data.jsonl"],
            annotation_task_name="Single Select Persistence",
            phases={
                "order": ["consent", "instructions", "training", "prestudy",
                          "annotation", "poststudy"],
                "consent": {"type": "consent", "file": "surveys/consent.json"},
                "instructions": {"type": "instructions",
                                 "file": "surveys/instructions.json"},
                "training": {"type": "training", "file": "surveys/training.json"},
                "prestudy": {"type": "prestudy", "file": "surveys/prestudy.json"},
                "poststudy": {"type": "poststudy", "file": "surveys/poststudy.json"},
            },
            additional_config={
                "export_include_phase_data": True,
                "output_annotation_format": "csv",
                "training": {
                    "enabled": True,
                    "data_file": "training_data.json",
                    "passing_criteria": {"min_correct": 1},
                    "allow_retry": True,
                },
            },
        )

        srv = FlaskTestServer(port=PORT, config_file=config_file)
        if not srv.start():
            pytest.fail("Failed to start test server")
        srv.test_dir = test_dir
        yield srv
        srv.stop()
    finally:
        cleanup_test_directory(test_dir)


def _session(server, user):
    s = requests.Session()
    s.post(f"{server.base_url}/register",
           data={"email": user, "pass": "pw", "action": "signup"})
    s.post(f"{server.base_url}/auth",
           data={"email": user, "pass": "pw", "action": "login"})
    return s


def _save(session, server, instance_id, annotations):
    """Post exactly what saveAnnotations() sends."""
    return session.post(
        f"{server.base_url}/updateinstance",
        json={"instance_id": instance_id, "annotations": annotations,
              "span_annotations": []},
    )


def _user_state(server, user):
    out = os.path.join(server.test_dir, "output")
    for d in sorted(os.listdir(out)):
        path = os.path.join(out, d, "user_state.json")
        if os.path.exists(path) and user.split("@")[0] in d:
            with open(path) as f:
                return json.load(f)
    return None


def _labels_for(entries, schema):
    """Stored (label_name, value) pairs for one schema in a serialized label list."""
    return [(e[0]["name"], e[1]) for e in entries
            if isinstance(e, list) and isinstance(e[0], dict)
            and e[0].get("schema") == schema]


def _phase_labels(state, phase, schema):
    pages = (state.get("phase_to_page_to_label_to_value") or {}).get(phase) or {}
    found = []
    for entries in pages.values():
        if isinstance(entries, list):
            found.extend(_labels_for(entries, schema))
    return found


def _advance(session, server, route):
    """Move past a phase page.

    The training phase only advances on a CORRECT answer, and it grades from STORED
    annotations rather than the submitted form — so the answer has to be saved the way
    the browser saves it (autosave to /updateinstance) before the submit is posted.
    That is what the real Next button does: flush, save, then POST.
    """
    if route == "training":
        _save(session, server, "__phase_page__", {"veracity:True": "True"})
    return session.post(f"{server.base_url}/{route}", data={},
                        allow_redirects=False)


class TestAnnotationPhase:
    """The reported symptom: likert accumulates, radio does not."""

    def test_changed_likert_stores_one_value(self, server):
        s = _session(server, "annphase@test.com")
        # Walk to the annotation phase.
        for route in ("consent", "instructions", "training", "prestudy"):
            _advance(s, server, route)
        s.get(f"{server.base_url}/annotate")

        assert _save(s, server, "item_1", {"confidence:5": "5"}).status_code == 200
        time.sleep(0.1)
        assert _save(s, server, "item_1", {"confidence:4": "4"}).status_code == 200

        anns = s.get(f"{server.base_url}/get_annotations",
                     params={"instance_id": "item_1"}).json()
        stored = anns.get("label_annotations", {}).get("confidence", [])
        assert stored == ["4"], f"expected one likert value, got {stored}"

    def test_changed_radio_stores_one_value(self, server):
        s = _session(server, "annradio@test.com")
        for route in ("consent", "instructions", "training", "prestudy"):
            _advance(s, server, route)
        s.get(f"{server.base_url}/annotate")

        _save(s, server, "item_1", {"veracity:True": "True"})
        time.sleep(0.1)
        _save(s, server, "item_1", {"veracity:False": "False"})

        anns = s.get(f"{server.base_url}/get_annotations",
                     params={"instance_id": "item_1"}).json()
        assert anns.get("label_annotations", {}).get("veracity", []) == ["False"]

    def test_multiselect_keeps_every_selection(self, server):
        """The fix must not turn checkboxes into radios."""
        s = _session(server, "annmulti@test.com")
        for route in ("consent", "instructions", "training", "prestudy"):
            _advance(s, server, route)
        s.get(f"{server.base_url}/annotate")

        _save(s, server, "item_1",
              {"tags:politics": "politics", "tags:health": "health"})

        anns = s.get(f"{server.base_url}/get_annotations",
                     params={"instance_id": "item_1"}).json()
        assert sorted(anns.get("label_annotations", {}).get("tags", [])) == [
            "health", "politics"]

    def test_multiselect_deselection_still_removes(self, server):
        """Complete-set semantics: a checkbox absent from the payload is deselected."""
        s = _session(server, "anndeselect@test.com")
        for route in ("consent", "instructions", "training", "prestudy"):
            _advance(s, server, route)
        s.get(f"{server.base_url}/annotate")

        _save(s, server, "item_1",
              {"tags:politics": "politics", "tags:health": "health"})
        time.sleep(0.1)
        _save(s, server, "item_1", {"tags:politics": "politics"})

        anns = s.get(f"{server.base_url}/get_annotations",
                     params={"instance_id": "item_1"}).json()
        assert anns.get("label_annotations", {}).get("tags", []) == ["politics"]


# Each phase page, with the route that advances past it. This is the half of #167 that
# affected EVERY single-select type, radio included — not just likert.
#
# `training` is the worst case: the phase is explicitly retry-oriented
# (`allow_retry: true`), so an annotator is *expected* to change their answer and every
# retry would have added another stored label.
PHASE_CASES = [
    ("consent", "consent"),
    ("instructions", "instructions"),
    ("training", "training"),
    ("prestudy", "prestudy"),
]


class TestPhasePages:

    @pytest.mark.parametrize("phase,route", PHASE_CASES)
    def test_changed_survey_answers_store_one_value(self, server, phase, route):
        """Both a likert and a radio, on every pre-annotation phase page."""
        s = _session(server, f"phase_{phase}@test.com")
        # Advance to the phase under test.
        for earlier, earlier_route in PHASE_CASES:
            if earlier == phase:
                break
            _advance(s, server, earlier_route)
        s.get(f"{server.base_url}/")

        _save(s, server, "__phase_page__",
              {"familiarity:5": "5", "native_language:Yes": "Yes"})
        time.sleep(0.1)
        _save(s, server, "__phase_page__",
              {"familiarity:4": "4", "native_language:No": "No"})

        state = _user_state(server, f"phase_{phase}@test.com")
        assert state is not None, "user_state.json was never written"

        # Guard against the test silently exercising the wrong phase (phases can
        # auto-advance when their gating config is absent).
        stored_phases = set(state.get("phase_to_page_to_label_to_value") or {})
        assert phase in stored_phases, (
            f"expected answers under '{phase}' but state holds {stored_phases}; "
            f"the user was not in the phase under test")

        likert = _phase_labels(state, phase, "familiarity")
        radio = _phase_labels(state, phase, "native_language")
        assert likert == [("4", "4")], f"{phase} likert stored {likert}"
        assert radio == [("No", "No")], f"{phase} radio stored {radio}"

    def test_poststudy_answers_store_one_value(self, server):
        """Poststudy is reached only after annotation, so it gets its own walk."""
        s = _session(server, "poststudy@test.com")
        for _phase, route in PHASE_CASES:
            _advance(s, server, route)

        s.get(f"{server.base_url}/annotate")
        # Annotate every assigned item, advancing with the POST that triggers
        # completion detection, until the queue is exhausted and the server moves the
        # user into poststudy.
        for item in ("item_1", "item_2", "item_3"):
            _save(s, server, item, {"veracity:True": "True", "confidence:3": "3"})
            s.post(f"{server.base_url}/annotate",
                   json={"action": "next_instance", "instance_id": item},
                   allow_redirects=True)

        # Confirm the user really is on the poststudy page before saving, so a failure
        # to reach it shows up as a clear error rather than a vacuous pass. The
        # rendered page is the signal here: the phase transition happens in memory and
        # is not flushed to user_state.json until the next save.
        page = s.get(f"{server.base_url}/").text
        assert "How familiar are you with this topic?" in page, (
            "user did not reach the poststudy page; the answers below would land in "
            "the wrong phase and the test would prove nothing")

        _save(s, server, "__phase_page__", {"familiarity:2": "2"})
        time.sleep(0.1)
        _save(s, server, "__phase_page__", {"familiarity:1": "1"})

        state = _user_state(server, "poststudy@test.com")
        assert _phase_labels(state, "poststudy", "familiarity") == [("1", "1")]


class TestRevisionTrailPreserved:
    """The final answer is unambiguous, but the fact that it changed is not lost."""

    def test_behavioral_trail_records_both_values(self, server):
        s = _session(server, "trail@test.com")
        for _phase, route in PHASE_CASES:
            _advance(s, server, route)
        s.get(f"{server.base_url}/annotate")

        # What interaction_tracker.js posts alongside each save.
        for old_label, old_value, new_label, new_value in (
            (None, None, "5", "5"),
            ("5", "5", "4", "4"),
        ):
            s.post(f"{server.base_url}/api/track_annotation_change", json={
                "instance_id": "item_2",
                "schema_name": "confidence",
                "label_name": new_label,
                "old_label": old_label,
                "old_value": old_value,
                "new_value": new_value,
                "action": "select",
                "source": "user",
            })
            _save(s, server, "item_2", {f"confidence:{new_label}": new_value})
            time.sleep(0.05)

        # Exactly one stored answer...
        anns = s.get(f"{server.base_url}/get_annotations",
                     params={"instance_id": "item_2"}).json()
        assert anns.get("label_annotations", {}).get("confidence", []) == ["4"]

        # ...but the trail still shows 5 -> 4.
        bd = s.get(f"{server.base_url}/api/behavioral_data/item_2").json()
        changes = bd.get("annotation_changes") or bd.get(
            "behavioral_data", {}).get("annotation_changes", [])
        confidence = [c for c in changes if c.get("schema_name") == "confidence"]
        assert [c["new_value"] for c in confidence] == ["5", "4"]
        assert confidence[1]["old_value"] == "5", (
            "old_value must record the superseded answer, not null")
        assert confidence[1]["old_label"] == "5"

    def test_phase_and_page_are_stamped(self, server):
        """Every survey page shares the __phase_page__ bucket, so records need the
        phase/page to be attributable at all."""
        s = _session(server, "trailphase@test.com")
        s.get(f"{server.base_url}/")

        s.post(f"{server.base_url}/api/track_annotation_change", json={
            "instance_id": "__phase_page__",
            "schema_name": "familiarity",
            "label_name": "3",
            "new_value": "3",
            "action": "select",
            "source": "user",
        })

        bd = s.get(f"{server.base_url}/api/behavioral_data/__phase_page__").json()
        changes = bd.get("annotation_changes") or bd.get(
            "behavioral_data", {}).get("annotation_changes", [])
        assert changes, "no annotation change was recorded"
        assert changes[-1]["phase"] == "consent"
        assert changes[-1]["page"] is not None


class TestExportIsUnambiguous:

    def test_phase_responses_carry_a_sequence_column(self, server):
        from potato.export.cli import load_phase_responses_from_output_dir

        s = _session(server, "export@test.com")
        _save(s, server, "__phase_page__",
              {"familiarity:3": "3", "native_language:Yes": "Yes"})

        rows = load_phase_responses_from_output_dir(
            os.path.join(server.test_dir, "output"))
        assert rows, "no phase responses were loaded"
        assert all("sequence" in r for r in rows)
        # Sequence restarts per page and is contiguous.
        by_page = {}
        for r in rows:
            by_page.setdefault((r["user_id"], r["phase"], r["page"]), []).append(
                r["sequence"])
        for seqs in by_page.values():
            assert seqs == list(range(len(seqs)))

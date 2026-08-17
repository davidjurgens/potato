"""
The canvas and timeline schemas must autosave, not wait for navigation.

Nine schemas answer through a single hidden `.annotation-data-input` rather
than through `handleInputChange`: image, video, audio, tiered, spatial,
episode, grounding_eval, region_caption and rollout_evaluation. Their values
were collected in exactly one place — inside `saveAnnotations()` — which runs
when the annotator navigates. Assigning `input.value` fires no event, and the
class had no listener, so drawing scheduled nothing.

Measured in a real browser before the fix: four shapes drawn, five seconds
elapsed, `/get_annotations` empty, and no save timer pending — so the
`beforeunload` flush, which returns early unless `textSaveTimer` is set, had
nothing to flush either. Closing the tab lost the work.

It hid from the whole suite because every persistence test navigates, and
navigation saves explicitly. These are structural assertions rather than
behavioural ones deliberately: the behaviour is covered by
`tests/playwright/test_annotation_autosave.py`, and what this file protects is
the *wiring*, so the tenth schema to adopt the mechanism cannot quietly ship
without it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
STATIC = REPO_ROOT / "potato" / "static"
SCHEMAS = REPO_ROOT / "potato" / "server_utils" / "schemas"

#: schema module -> the client that owns its `.annotation-data-input`.
#: Adding a schema that renders the class without adding it here fails
#: `test_every_data_input_schema_is_listed`.
OWNERS = {
    "image_annotation.py": "image-annotation.js",
    "video_annotation.py": "video-annotation.js",
    "audio_annotation.py": "audio-annotation.js",
    "tiered_annotation.py": "tiered-annotation.js",
    "spatial_annotation.py": "pointcloud/pc-viewer.js",
    "episode_annotation.py": "episode-timeline.js",
    "grounding_eval.py": "grounding-eval.js",
    "region_caption.py": "region-caption.js",
    "rollout_evaluation.py": "rollout-eval.js",
}

CHANGE_DISPATCH = re.compile(
    r"dispatchEvent\(\s*new Event\(\s*['\"]change['\"]", re.S)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def schemas_rendering_data_input():
    """Schema modules that render a `.annotation-data-input`."""
    found = []
    for path in sorted(SCHEMAS.glob("*.py")):
        if "annotation-data-input" in read(path):
            found.append(path.name)
    return found


class TestEveryOwnerAnnouncesItsChanges:
    @pytest.mark.parametrize("schema,client", sorted(OWNERS.items()))
    def test_client_dispatches_a_change_event(self, schema, client):
        """
        Writing the value must be announced, or the shared autosave is blind.

        Three clients already dispatched before the fix — onto a class with no
        listener, so it was a no-op. That near-miss is why this asserts the
        dispatch and `test_annotation_js_listens` asserts the other half; a
        test for either one alone passes on a mechanism that does nothing.
        """
        source = read(STATIC / client)
        assert CHANGE_DISPATCH.search(source), (
            f"{client} writes an .annotation-data-input but never dispatches a "
            f"change event, so annotation.js cannot autosave it and the work "
            f"reaches the server only if the annotator navigates.")

    def test_every_data_input_schema_is_listed(self):
        """A new blob schema has to declare its client here."""
        rendered = set(schemas_rendering_data_input())
        listed = set(OWNERS)
        unlisted = sorted(rendered - listed)
        assert not unlisted, (
            f"These schemas render an .annotation-data-input but are not in "
            f"OWNERS, so nothing checks that their client autosaves: {unlisted}")

    def test_the_owner_table_is_not_stale(self):
        """And a schema that stopped using the mechanism should leave."""
        rendered = set(schemas_rendering_data_input())
        stale = sorted(set(OWNERS) - rendered)
        assert not stale, (
            f"OWNERS lists schemas that no longer render an "
            f"annotation-data-input: {stale}")


class TestTheSharedHalf:
    def test_annotation_js_listens(self):
        source = read(STATIC / "annotation.js")
        assert "setupAnnotationDataAutosave" in source
        assert re.search(
            r"querySelectorAll\(\s*['\"]input\.annotation-data-input['\"]",
            source), (
            "nothing subscribes to the class the managers dispatch on")

    def test_the_listener_is_actually_installed(self):
        """
        Defining the function is not wiring it up.

        It has to hang off `setupInputEventListeners`, which is the one both
        render paths call — annotation pages through `generateAnnotationForms`
        and phase pages directly. Wiring it anywhere reached by only one of
        them is how a feature ends up working on half the workflow.
        """
        source = read(STATIC / "annotation.js")
        start = source.index("function setupInputEventListeners")
        end = source.index("\nfunction ", start + 1)
        assert "setupAnnotationDataAutosave()" in source[start:end], (
            "setupAnnotationDataAutosave is never called from "
            "setupInputEventListeners, so no listener is ever attached")

    def test_both_render_paths_reach_the_wiring(self):
        source = read(STATIC / "annotation.js")
        callers = source.count("setupInputEventListeners();")
        assert callers >= 2, (
            "setupInputEventListeners is called from fewer than both render "
            "paths, so autosave would work on only half the workflow")

    def test_the_scheduler_shares_the_unload_timer(self):
        """
        `flushPendingSave` returns early unless `textSaveTimer` is set.

        A private timer here would look correct and still lose everything when
        the tab closed, which is the exact shape of the original bug.
        """
        source = read(STATIC / "annotation.js")
        start = source.index("function scheduleAnnotationDataSave")
        body = source[start:start + 600]
        assert "textSaveTimer" in body, (
            "scheduleAnnotationDataSave must use textSaveTimer, the handle "
            "flushPendingSave checks on beforeunload")

    def test_both_payload_builders_collect_the_inputs(self):
        """
        `saveAnnotations` collected them; `flushPendingSave` did not.

        So the unload path posted an answer with the canvas schemas absent —
        which the server reads as cleared, not as unmentioned.
        """
        source = read(STATIC / "annotation.js")
        for fn in ("flushPendingSave", "saveAnnotations"):
            start = source.index(f"function {fn}")
            body = source[start:start + 6000]
            assert "collectAnnotationDataInputs" in body, (
                f"{fn} builds an /updateinstance payload without collecting "
                f"the .annotation-data-input values")

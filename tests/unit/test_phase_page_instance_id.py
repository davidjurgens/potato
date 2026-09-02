"""Behavioral tracking on phase pages.

Phase pages -- consent, instructions, training, prestudy and poststudy surveys
-- have no instance: the annotation template leaves the id empty and the client
posts null. Behavioral data is bucketed by instance id, so those pages all share
one `__phase_page__` bucket and are told apart by the `phase`/`page` fields
stamped server-side.

Three of the five tracking endpoints did not do that:

  * `track_annotation_change` returned 400 for a null id, so no answer changed
    on any survey or training page was ever recorded. Its own phase-stamping
    block -- written for exactly those pages -- sat below the guard, unreachable.
  * `track_ai_usage` had the same guard.
  * `track_interactions` had no normalization at all, which created a second
    behavioral-data bucket keyed literally "null" beside the real one.

`track_typing` and `track_annotation_telemetry` each carried their own copy of
the fallback. This is now one function.
"""

import pytest

from potato.interaction_tracking import (
    PHASE_PAGE_SENTINEL,
    normalize_instance_id,
)


class TestNormalizeInstanceId:
    @pytest.mark.parametrize("missing", [
        None,          # what the JSON body actually carries
        "",            # an empty template variable
        "null",        # str(null) on the way through
        "None",        # str(None) on the way through
        "undefined",   # a JS value that never got set
    ])
    def test_missing_ids_become_the_sentinel(self, missing):
        assert normalize_instance_id(missing) == PHASE_PAGE_SENTINEL

    @pytest.mark.parametrize("real", ["coref_001", "1", "instance-42"])
    def test_real_ids_pass_through(self, real):
        assert normalize_instance_id(real) == real

    def test_a_numeric_id_becomes_its_string(self):
        assert normalize_instance_id(123) == "123"

    def test_the_sentinel_is_stable(self):
        """Already-normalized input must not be normalized differently."""
        assert normalize_instance_id(PHASE_PAGE_SENTINEL) == PHASE_PAGE_SENTINEL

    def test_the_sentinel_matches_what_the_client_sends(self):
        """annotation.js builds a synthetic instance with this exact id."""
        assert PHASE_PAGE_SENTINEL == "__phase_page__"

    def test_an_id_that_merely_contains_null_is_not_missing(self):
        assert normalize_instance_id("nullable_item_3") == "nullable_item_3"


class TestEndpointsUseIt:
    """Source guard: the three endpoints must normalize before their guard.

    A guard that rejects a null id ahead of the fallback puts the endpoint back
    where it started, and the symptom -- a 400 per keystroke on a survey page --
    is invisible unless someone reads the request log.
    """

    @pytest.fixture(scope="class")
    def routes_source(self):
        from pathlib import Path
        import potato
        return (Path(potato.__file__).parent / "routes.py").read_text()

    def _body(self, source, name):
        start = source.index(f"\ndef {name}(")
        end = source.index("\n@app.route", start + 1) if "\n@app.route" in source[start:] \
            else len(source)
        return source[start:min(end, start + 6000)]

    @pytest.mark.parametrize("endpoint", [
        "track_annotation_change",
        "track_ai_usage",
        "track_interactions",
    ])
    def test_endpoint_normalizes(self, routes_source, endpoint):
        body = self._body(routes_source, endpoint)
        assert "normalize_instance_id(" in body, (
            f"{endpoint} no longer normalizes its instance id, so phase-page "
            "behavioral data is either rejected or bucketed under 'null'."
        )

    @pytest.mark.parametrize("endpoint", ["track_annotation_change", "track_ai_usage"])
    def test_endpoint_does_not_reject_a_missing_instance_id(self, routes_source, endpoint):
        body = self._body(routes_source, endpoint)
        assert "if not instance_id or" not in body, (
            f"{endpoint} rejects a missing instance id again. Phase pages have "
            "none by design."
        )

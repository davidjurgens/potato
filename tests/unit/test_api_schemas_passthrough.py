"""Tests for the /api/schemas endpoint schema-config passthrough.

Regression tests for the fix that makes ``/api/schemas`` forward every
schema-configured key (mode, steps_key, verdict_options, size, etc.)
instead of an explicit allowlist. Without these tests the route can
silently regress for any schema type added after likert/slider/textbox.
"""
import json
from unittest.mock import patch, MagicMock

import pytest
from flask import Flask


@pytest.fixture
def client(monkeypatch):
    """Build a minimal Flask test client that calls the real route."""
    from potato import routes

    app = Flask(__name__)
    app.config['TESTING'] = True
    app.secret_key = 'test'

    # Register the route against the test app
    app.add_url_rule(
        "/api/schemas",
        "get_annotation_schemas",
        routes.get_annotation_schemas,
        methods=["GET"],
    )

    return app, routes


def _patch_config(routes_module, schemas):
    """Swap `routes.config.get` so the route sees `schemas` as annotation_schemes."""
    fake = MagicMock()
    fake.get.side_effect = lambda key, *args: schemas if key == 'annotation_schemes' else None
    return patch.object(routes_module, 'config', fake)


class TestApiSchemasPassthrough:
    def test_likert_size_and_minmax_labels_round_trip(self, client):
        app, routes_module = client
        schemas = [{
            "name": "quality",
            "annotation_type": "likert",
            "description": "Rate it",
            "size": 7,
            "min_label": "Bad",
            "max_label": "Great",
        }]
        with _patch_config(routes_module, schemas):
            with app.test_client() as c:
                resp = c.get("/api/schemas")
        assert resp.status_code == 200
        body = resp.get_json()
        entry = body["quality"]
        assert entry["size"] == 7
        assert entry["min_label"] == "Bad"
        assert entry["max_label"] == "Great"

    def test_slider_min_max_round_trip(self, client):
        app, routes_module = client
        schemas = [{
            "name": "score",
            "annotation_type": "slider",
            "min_value": -5,
            "max_value": 5,
        }]
        with _patch_config(routes_module, schemas):
            with app.test_client() as c:
                resp = c.get("/api/schemas")
        entry = resp.get_json()["score"]
        assert entry["min_value"] == -5
        assert entry["max_value"] == 5

    def test_process_reward_mode_and_steps_key_surface(self, client):
        """Previously dropped -- now forwarded verbatim."""
        app, routes_module = client
        schemas = [{
            "name": "step_rewards",
            "annotation_type": "process_reward",
            "mode": "first_error",
            "steps_key": "structured_turns",
        }]
        with _patch_config(routes_module, schemas):
            with app.test_client() as c:
                resp = c.get("/api/schemas")
        entry = resp.get_json()["step_rewards"]
        assert entry["mode"] == "first_error"
        assert entry["steps_key"] == "structured_turns"

    def test_code_review_verdicts_categories_ratings_surface(self, client):
        app, routes_module = client
        schemas = [{
            "name": "review",
            "annotation_type": "code_review",
            "verdict_options": ["approve", "request_changes"],
            "comment_categories": ["bug", "style"],
            "file_rating_dimensions": ["correctness"],
        }]
        with _patch_config(routes_module, schemas):
            with app.test_client() as c:
                resp = c.get("/api/schemas")
        entry = resp.get_json()["review"]
        assert entry["verdict_options"] == ["approve", "request_changes"]
        assert entry["comment_categories"] == ["bug", "style"]
        assert entry["file_rating_dimensions"] == ["correctness"]

    def test_reserved_keys_are_not_duplicated(self, client):
        """`type`, `name`, `description`, `labels` are returned via their
        dedicated top-level fields; they must not also appear under their
        raw config key to avoid conflicts."""
        app, routes_module = client
        schemas = [{
            "name": "x",
            "annotation_type": "radio",
            "description": "D",
            "labels": [{"name": "a"}, {"name": "b"}],
            # annotation_id would normally come from schema builder; strip it
            "annotation_id": 99,
        }]
        with _patch_config(routes_module, schemas):
            with app.test_client() as c:
                resp = c.get("/api/schemas")
        entry = resp.get_json()["x"]
        # Top-level fields are flat, not nested under their raw key
        assert entry["type"] == "radio"
        assert entry["name"] == "x"
        assert entry["description"] == "D"
        assert entry["labels"] == ["a", "b"]
        # annotation_id is internal runtime state, not part of the API surface
        assert "annotation_id" not in entry

    def test_underscore_prefixed_keys_dropped(self, client):
        app, routes_module = client
        schemas = [{
            "name": "x",
            "annotation_type": "radio",
            "labels": [{"name": "a"}],
            "_internal_debug": "do_not_leak",
        }]
        with _patch_config(routes_module, schemas):
            with app.test_client() as c:
                resp = c.get("/api/schemas")
        entry = resp.get_json()["x"]
        assert "_internal_debug" not in entry

    def test_unknown_schema_types_still_passthrough_config(self, client):
        """Forward-compat guarantee -- any future schema type's config is preserved."""
        app, routes_module = client
        schemas = [{
            "name": "future_schema",
            "annotation_type": "hypothetical_new_type",
            "custom_knob": [1, 2, 3],
            "nested": {"a": 1, "b": "two"},
        }]
        with _patch_config(routes_module, schemas):
            with app.test_client() as c:
                resp = c.get("/api/schemas")
        entry = resp.get_json()["future_schema"]
        assert entry["type"] == "hypothetical_new_type"
        assert entry["custom_knob"] == [1, 2, 3]
        assert entry["nested"] == {"a": 1, "b": "two"}

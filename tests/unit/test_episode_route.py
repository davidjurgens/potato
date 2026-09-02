"""
``GET /api/episode/<path>`` — the manifest the timeline consumes.

Driven through a real Flask test client, because what breaks is the wiring, the
media prefix and the content type, and a direct call to the handler exercises
none of them.
"""

from __future__ import annotations

import json

import pytest

flask = pytest.importorskip("flask")

from potato.episodes import routes as episode_routes  # noqa: E402


@pytest.fixture
def client(tmp_path):
    media = tmp_path / "media"
    media.mkdir()

    app = flask.Flask(__name__)
    app.config["TESTING"] = True
    episode_routes.register_episode_routes(app, {
        "media_directory": str(media),
        "task_dir": str(tmp_path),
    })
    with app.test_client() as c:
        yield c, media


def write_episode(media, name="ep0", **overrides):
    payload = {
        "episode_id": name,
        "fps": 20,
        "num_frames": 4,
        "instruction": "pick the block",
        "streams": [{"name": "wrist", "url": "video/wrist.webm",
                     "kind": "wrist"}],
        "series": [{"name": "gripper", "unit": "m",
                    "values": [0.06, 0.03, 0.01, 0.06]}],
    }
    payload.update(overrides)
    directory = media / "episodes" / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "episode.json").write_text(json.dumps(payload),
                                            encoding="utf-8")
    return f"episodes/{name}/episode.json"


class TestManifest:
    def test_serves_the_manifest_as_json(self, client):
        c, media = client
        path = write_episode(media)
        resp = c.get(f"/api/episode/{path}")
        assert resp.status_code == 200
        assert resp.mimetype == "application/json"

        payload = resp.get_json()
        assert payload["episode_id"] == "ep0"
        assert payload["fps"] == 20
        assert payload["num_frames"] == 4
        assert payload["duration"] == pytest.approx(0.2)
        assert payload["instruction"] == "pick the block"

    def test_stream_urls_are_fetchable(self, client):
        # A relative URL resolves against the page and 404s in a way that looks
        # like a missing file rather than a mangled path.
        c, media = client
        path = write_episode(media)
        payload = c.get(f"/api/episode/{path}").get_json()
        assert payload["streams"][0]["url"] == (
            "/media/episodes/ep0/video/wrist.webm")

    def test_series_carry_their_precomputed_range(self, client):
        c, media = client
        path = write_episode(media)
        series = c.get(f"/api/episode/{path}").get_json()["series"][0]
        assert series["min"] == pytest.approx(0.01)
        assert series["max"] == pytest.approx(0.06)
        assert series["num_frames"] == 4

    def test_long_series_are_downsampled(self, client):
        # A ten-minute episode at 50 Hz is 30,000 numbers per channel; a
        # fourteen-joint arm is 420,000, drawn into lanes a few hundred pixels
        # wide.
        c, media = client
        path = write_episode(
            media, num_frames=5000,
            series=[{"name": "a", "values": [float(i) for i in range(5000)]}])
        payload = c.get(f"/api/episode/{path}?max_samples=200").get_json()
        assert len(payload["series"][0]["values"]) < 260
        assert payload["series"][0]["num_frames"] == 5000

    def test_a_ragged_series_produces_a_warning_not_an_error(self, client):
        c, media = client
        path = write_episode(
            media, num_frames=10,
            series=[{"name": "a", "values": [1.0, 2.0]}])
        payload = c.get(f"/api/episode/{path}").get_json()
        assert payload["warnings"]
        assert any("2 samples" in w for w in payload["warnings"])


class TestListing:
    def test_a_single_episode_source_lists_one(self, client):
        c, media = client
        path = write_episode(media)
        assert c.get(f"/api/episodes/{path}").get_json()["episodes"] == [0]


class TestFailures:
    def test_a_missing_episode_is_a_404(self, client):
        c, _media = client
        assert c.get("/api/episode/nope/episode.json").status_code == 404

    def test_an_unrecognised_source_lists_what_was_looked_for(self, client):
        # 415, not 500: the file is fine and we cannot read it, and the message
        # has to name the next step rather than a stack trace.
        c, media = client
        (media / "junk.txt").write_text("nothing episode-shaped here")
        resp = c.get("/api/episode/junk.txt")
        assert resp.status_code == 415
        assert "LeRobot" in resp.get_json()["error"]

    def test_a_json_file_with_no_episode_keys_says_exactly_that(self, client):
        # Distinct from the message above on purpose: "this is not an episode
        # format" sends the user looking for a converter, when the real problem
        # is a manifest missing one key.
        c, media = client
        (media / "junk.json").write_text('{"hello": 1}')
        resp = c.get("/api/episode/junk.json")
        assert resp.status_code == 415
        error = resp.get_json()["error"]
        assert "streams" in error and "series" in error

    def test_traversal_is_refused(self, client):
        c, _media = client
        resp = c.get("/api/episode/..%2f..%2fetc%2fpasswd")
        assert resp.status_code in (403, 404)

    def test_malformed_json_is_reported_not_swallowed(self, client):
        c, media = client
        directory = media / "episodes" / "bad"
        directory.mkdir(parents=True)
        (directory / "episode.json").write_text("{not json")
        resp = c.get("/api/episode/episodes/bad/episode.json")
        assert resp.status_code == 415
        assert "JSON" in resp.get_json()["error"]


class TestWiring:
    def test_routes_are_registered_by_name(self):
        class FakeApp:
            def __init__(self):
                self.rules = []

            def add_url_rule(self, rule, endpoint, view, **kwargs):
                self.rules.append(rule)

        app = FakeApp()
        episode_routes.register_episode_routes(app, {})
        assert "/api/episode/<path:filepath>" in app.rules
        assert "/api/episodes/<path:filepath>" in app.rules

    def test_configure_routes_actually_calls_the_registration(self):
        """A bare @app.route decorator 404s under `potato start`."""
        from pathlib import Path
        source = Path("potato/routes.py").read_text()
        assert "register_episode_routes(app, config)" in source

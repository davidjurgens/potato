"""
/annotate/grid: items from the annotator's own assignment, saved through
/updateinstance.

The page reads its tiles from the server and posts each label back to
/updateinstance exactly as grid-view.js does. These tests drive it the same
way: parse the tiles out of the HTML, post the same payload, and check what the
server then knows -- whose items they are, that both sides of the bookkeeping
were written, and that agreement counts grid labels.
"""

import os

import pytest
import requests
from bs4 import BeautifulSoup

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    cleanup_test_directory, create_test_config, create_test_data_file,
    create_test_directory,
)

SCHEME = {"annotation_type": "radio", "name": "sentiment",
          "description": "Sentiment?", "labels": ["pos", "neg"]}
ADMIN_KEY = "grid-admin-key"


def _server(name, items, extra):
    test_dir = create_test_directory(name)
    data_file = create_test_data_file(test_dir, items)
    port = find_free_port(preferred_port=9898)
    config_file = create_test_config(
        test_dir, [SCHEME], data_files=[data_file], port=port,
        additional_config=dict({"admin_api_key": ADMIN_KEY}, **extra))
    server = FlaskTestServer(port=port, debug=False, config_file=config_file)
    if not server.start():
        pytest.fail("Failed to start server")
    return server, test_dir


def _login(server, name):
    session = requests.Session()
    session.post(f"{server.base_url}/register", data={"email": name, "pass": "pw"})
    session.post(f"{server.base_url}/auth", data={"email": name, "pass": "pw"})
    session.get(f"{server.base_url}/annotate")
    return session


def _grid(server, session):
    response = session.get(f"{server.base_url}/annotate/grid")
    assert response.status_code == 200, response.text[:300]
    soup = BeautifulSoup(response.text, "html.parser")
    return [t["data-instance-id"] for t in soup.select(".grid-tile")], response.text


def _save(server, session, instance_id, label):
    """The request grid-view.js sends for one tile."""
    response = session.post(f"{server.base_url}/updateinstance", json={
        "instance_id": instance_id,
        "annotations": {f"sentiment:{label}": label},
        "cleared_schemas": [], "span_annotations": [],
        "source_view": "grid",
    })
    assert response.status_code == 200, response.text
    assert response.json().get("status") != "error", response.text


ITEMS = [{"id": f"i{n}", "text": f"Item number {n}"} for n in range(1, 7)]


class TestAssignment:
    @pytest.fixture
    def capped(self, request):
        server, test_dir = _server(
            f"grid_assignment_{request.node.name}", ITEMS,
            {"max_annotations_per_item": 1,
             "grid_view": {"enabled": True, "scheme": "sentiment", "page_size": 4}})
        yield server
        server.stop()
        cleanup_test_directory(test_dir)

    def test_a_page_is_topped_up_from_the_assignment(self, capped):
        tiles, _ = _grid(capped, _login(capped, "alice"))
        assert len(tiles) == 4

    def test_items_at_their_cap_are_not_offered_again(self, capped):
        """With one annotator per item, what alice saved is not bob's to label."""
        alice = _login(capped, "alice")
        a_tiles, _ = _grid(capped, alice)
        for iid in a_tiles:
            _save(capped, alice, iid, "pos")
        b_tiles, _ = _grid(capped, _login(capped, "bob"))
        assert b_tiles and not set(a_tiles) & set(b_tiles), (a_tiles, b_tiles)
        assert set(b_tiles) == {i["id"] for i in ITEMS} - set(a_tiles)

    def test_saved_items_leave_the_grid_and_it_refills(self, capped):
        alice = _login(capped, "alice")
        tiles, _ = _grid(capped, alice)
        for iid in tiles[:3]:
            _save(capped, alice, iid, "pos")
        remaining, html = _grid(capped, alice)
        assert not set(tiles[:3]) & set(remaining)
        assert remaining[0] == tiles[3]
        assert len(remaining) == 3        # i4 plus the two items left in the pool
        assert "3 annotated" in html
        stored = alice.get(f"{capped.base_url}/get_annotations",
                           params={"instance_id": tiles[0]}).json()
        assert stored["label_annotations"]["sentiment"] == ["pos"]


class TestAgreement:
    @pytest.fixture(scope="class")
    def overlapping(self):
        server, test_dir = _server(
            "grid_agreement", ITEMS[:4],
            {"max_annotations_per_item": 2,
             "grid_view": {"enabled": True, "scheme": "sentiment", "page_size": 4}})
        yield server
        server.stop()
        cleanup_test_directory(test_dir)

    def test_agreement_counts_grid_labels(self, overlapping):
        answers = {"alice": ["pos", "pos", "neg", "neg"], "bob": ["pos", "neg", "neg", "neg"]}
        for name, labels in answers.items():
            session = _login(overlapping, name)
            tiles, _ = _grid(overlapping, session)
            assert sorted(tiles) == ["i1", "i2", "i3", "i4"]
            for iid in tiles:
                _save(overlapping, session, iid, labels[int(iid[1:]) - 1])
        report = requests.get(f"{overlapping.base_url}/admin/api/agreement",
                              headers={"X-API-Key": ADMIN_KEY}).json()
        sentiment = report["by_schema"]["sentiment"]
        # Values: pos x3, neg x5 (n=8). Do = 2/8; De = (3*5*2)/(8*7). The
        # endpoint rounds to four places.
        assert sentiment["krippendorff_alpha"] == pytest.approx(1 - (2 / 8) / (30 / 56), abs=1e-4)


class TestSafety:
    @pytest.fixture(scope="class")
    def disabled(self):
        server, test_dir = _server("grid_disabled", ITEMS[:2], {})
        yield server
        server.stop()
        cleanup_test_directory(test_dir)

    @pytest.fixture(scope="class")
    def hostile(self):
        items = [{"id": "x1", "text": "<script>window.pwned=1</script><b>bold</b>"}]
        server, test_dir = _server(
            "grid_xss", items,
            {"grid_view": {"enabled": True, "scheme": "sentiment", "page_size": 4}})
        yield server
        server.stop()
        cleanup_test_directory(test_dir)

    def test_a_disabled_grid_redirects_to_the_annotation_page(self, disabled):
        session = _login(disabled, "carol")
        response = session.get(f"{disabled.base_url}/annotate/grid", allow_redirects=False)
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/annotate")

    def test_item_text_is_escaped(self, hostile):
        _tiles, html = _grid(hostile, _login(hostile, "dave"))
        assert "<script>window.pwned" not in html
        assert "&lt;script&gt;" in html


class TestAttentionChecks:
    """The grid delivers attention checks and scores them like the normal page.

    Found by the potato-skill agent: the grid served regular items only, so a
    study using attention checks to catch speed-clicking lost them in the view
    built for fast clicking.
    """

    @pytest.fixture
    def checked(self, request):
        import json as _json
        test_dir = create_test_directory(f"grid_attention_{request.node.name}")
        data_file = create_test_data_file(
            test_dir, [{"id": f"h{n:02d}", "text": f"Headline {n}"} for n in range(1, 13)])
        with open(os.path.join(test_dir, "attn.json"), "w") as f:
            _json.dump([{"id": f"check{k}", "text": "Please choose neg",
                         "expected_answer": {"sentiment": "neg"}} for k in range(1, 6)], f)
        port = find_free_port(preferred_port=9898)
        config_file = create_test_config(
            test_dir, [SCHEME], data_files=[data_file], port=port,
            additional_config={
                "grid_view": {"enabled": True, "scheme": "sentiment", "page_size": 6},
                "attention_checks": {"enabled": True, "items_file": "attn.json", "frequency": 3,
                                     "failure_handling": {"warn_threshold": 1,
                                                          "block_threshold": 2}}})
        server = FlaskTestServer(port=port, debug=False, config_file=config_file)
        if not server.start():
            pytest.fail("Failed to start server")
        yield server
        server.stop()
        cleanup_test_directory(test_dir)

    def test_checks_appear_at_the_configured_frequency(self, checked):
        tiles, _ = _grid(checked, _login(checked, "erin"))
        checks = [i for i, iid in enumerate(tiles) if iid.startswith("check")]
        regular = [iid for iid in tiles if not iid.startswith("check")]
        assert len(regular) == 6
        # One after every three regular items: positions 3 and 7.
        assert checks == [3, 7], tiles

    def test_failing_checks_in_the_grid_blocks_the_annotator(self, checked):
        session = _login(checked, "frank")
        tiles, _ = _grid(checked, session)
        responses = []
        for iid in tiles:
            response = session.post(f"{checked.base_url}/updateinstance", json={
                "instance_id": iid, "annotations": {"sentiment:pos": "pos"},
                "cleared_schemas": [], "span_annotations": [], "source_view": "grid"})
            responses.append(response.json().get("status"))
        assert "blocked" in responses, responses
        redirected = session.get(f"{checked.base_url}/annotate/grid", allow_redirects=False)
        assert redirected.status_code == 302
        assert redirected.headers["Location"].endswith("/annotate")

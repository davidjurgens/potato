"""
The rendered ``/admin/iaa?format=html`` page over a grounding project.

The arithmetic is covered by ``tests/unit/test_iaa_grounding.py``. This file
covers the half that was missing entirely: ``grounding_eval`` was not in the
dispatcher's type table, so it classified as UNSUPPORTED and was **skipped**.
No grounding project ever produced an agreement number, on the page or in the
API, and nothing said so — the schema simply did not appear.

That is the failure mode this file exists for, so the first assertion is the
blunt one: the schema is present at all.
"""

import json
import re

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import (
    cleanup_test_directory,
    create_test_config,
    create_test_data_file,
    create_test_directory,
)

SCHEMA = "grounding"
ADMIN_KEY = "iaa-grounding-test-key"
ITEM_IDS = [f"scene_{i}" for i in range(3)]

EXPRESSIONS = ["the red mug", "the cat on the left", "the missing umbrella"]


def _box(x, y, size=0.2):
    return {"type": "bbox", "label": "referent",
            "coordinates": {"x": x, "y": y, "width": size, "height": size}}


@pytest.fixture(scope="module")
def server():
    test_dir = create_test_directory("iaa_grounding_page")
    data = [{"id": iid, "text": f"scene {i}",
             "image": "https://example.invalid/scene.png",
             "expressions": EXPRESSIONS}
            for i, iid in enumerate(ITEM_IDS)]
    data_file = create_test_data_file(test_dir, data)
    config_file = create_test_config(
        test_dir,
        annotation_schemes=[{
            # grounding_eval binds expressions to regions drawn by a companion
            # image_annotation scheme; declared alone it renders and collects
            # nothing, and the config validator refuses it.
            "annotation_type": "image_annotation",
            "name": "regions",
            "description": "Draw the regions",
            "tools": ["bbox"],
            "labels": ["referent"],
        }, {
            "annotation_type": "grounding_eval",
            "name": SCHEMA,
            "description": "Draw the region each expression refers to",
            "expressions_field": "expressions",
            "region_type": "box",
        }],
        data_files=[data_file],
        item_properties={"id_key": "id", "text_key": "text"},
        annotation_task_name="Grounding IAA page",
        require_password=False,
        admin_api_key=ADMIN_KEY,
        num_annotators_per_item={"default": 2},
    )
    srv = FlaskTestServer(port=find_free_port(preferred_port=9083),
                          debug=False, config_file=config_file)
    assert srv.start_server(), "Failed to start Flask server"
    srv._wait_for_server_ready(timeout=15)
    yield srv
    srv.stop_server()
    cleanup_test_directory(test_dir)


def _annotate(server, user, drift):
    """
    Ground two expressions and declare the third absent.

    ``drift`` shifts one annotator's boxes so the two agree at a loose IoU
    threshold and disagree at a tight one — the reason the report sweeps rather
    than quoting a single number. The third expression is marked not-present by
    both, which is what makes the detection alpha defined at all: without a
    single "absent" anywhere, every answer is identical and alpha has no
    variation to correct against.
    """
    session = requests.Session()
    session.post(f"{server.base_url}/register",
                 data={"email": user, "pass": "pw", "action": "signup"})
    session.post(f"{server.base_url}/auth", data={"email": user, "pass": "pw"})
    session.get(f"{server.base_url}/annotate")
    for instance_id in ITEM_IDS:
        session.get(f"{server.base_url}/annotate",
                    params={"instance_id": instance_id})
        value = {
            "regions": {
                "expr-0": [_box(0.10 + drift, 0.10 + drift)],
                "expr-1": [_box(0.50 + drift, 0.50 + drift)],
            },
            "absent": ["expr-2"],
            "verdicts": {},
            "region_type": "box",
        }
        response = session.post(
            f"{server.base_url}/updateinstance",
            json={"instance_id": instance_id,
                  "annotations": {f"{SCHEMA}:::_data": json.dumps(value)}})
        assert response.status_code == 200, response.text


@pytest.fixture(scope="module")
def page(server):
    _annotate(server, "ground_alice", 0.0)
    _annotate(server, "ground_bob", 0.04)
    response = requests.get(f"{server.base_url}/admin/iaa",
                            params={"format": "html"},
                            headers={"X-API-Key": ADMIN_KEY})
    assert response.status_code == 200, response.text
    assert response.text.lstrip().startswith("<!doctype html>"), (
        "the route fell back to JSON, so the template raised")
    return response.text


@pytest.fixture(scope="module")
def report(server, page):
    response = requests.get(f"{server.base_url}/admin/iaa",
                            headers={"X-API-Key": ADMIN_KEY})
    return response.json()


def _cells(html):
    """Every metric row as ``{name: cell text}``."""
    body = re.sub(r"\s+", " ", html)
    out = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", body):
        columns = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row)
        if len(columns) == 2:
            name = re.sub(r"<[^>]+>", "", columns[0]).strip()
            value = re.sub(r"<[^>]+>", " ", columns[1]).strip()
            out[name] = re.sub(r"\s+", " ", value)
    return out


class TestTheSchemaIsNoLongerSkipped:
    def test_grounding_eval_appears_in_the_report(self, report):
        """Before the wiring, this key was simply absent."""
        assert SCHEMA in report["schemas"], (
            f"grounding_eval was skipped; schemas present: "
            f"{list(report['schemas'])}")
        assert report["schemas"][SCHEMA]["kind"] == "grounding"

    def test_the_json_is_the_nested_report(self, report):
        metrics = report["schemas"][SCHEMA]["metrics"]
        assert isinstance(metrics["detection"], dict)
        assert isinstance(metrics["localization"], dict)
        assert isinstance(metrics["coverage"], dict)
        assert isinstance(metrics["sweep"], list)


class TestTheNumbersAreRight:
    def test_detection_agreement_is_perfect(self, report):
        """Both annotators located the same two and declined the same one."""
        detection = report["schemas"][SCHEMA]["metrics"]["detection"]
        assert detection["percent_agreement"] == pytest.approx(1.0)
        assert detection["alpha"] == pytest.approx(1.0)

    def test_localization_is_high_but_not_perfect(self, report):
        """The 0.04 drift must show up as a real, sub-1.0 overlap."""
        localization = report["schemas"][SCHEMA]["metrics"]["localization"]
        assert 0.4 < localization["mean_iou"] < 1.0
        assert localization["n_pairs_compared"] == len(ITEM_IDS) * 2

    def test_coverage_is_complete(self, report):
        coverage = report["schemas"][SCHEMA]["metrics"]["coverage"]
        assert coverage["answered_fraction"] == pytest.approx(1.0)
        assert coverage["n_unanswered_excluded"] == 0


class TestTheNumbersReachThePage:
    def test_grouped_metrics_are_rendered_not_na(self, page):
        cells = _cells(page)
        for name in ("detection.alpha", "localization.mean_iou",
                     "coverage.answered_fraction"):
            assert name in cells, f"{name} is missing from the page: {list(cells)}"
            assert cells[name] not in ("n/a", ""), (
                f"{name} rendered as {cells[name]!r} — the nested report is not "
                f"being flattened")

    def test_the_iou_sweep_renders_as_a_table(self, page):
        assert "IoU threshold" in page, (
            "the sweep did not render; sweep_parameter_label is missing")

    def test_no_count_is_banded_as_agreement(self, page):
        """
        The regression that made `n_items_skipped: 0` render as "weak
        agreement" in red: banding applied to anything numeric. A count of
        compared pairs must carry no band at all.
        """
        body = re.sub(r"\s+", " ", page)
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", body):
            if "n_pairs_compared" in row or "n_expression_pairs" in row:
                assert "weak" not in row and "strong" not in row, (
                    f"a count was banded as an agreement score: {row[:200]}")

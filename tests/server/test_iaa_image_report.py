"""
The /admin/iaa report over an image annotation project, end to end.

Two annotators draw on the same images through the real ``/updateinstance``
route, then the real admin route computes the report. This is the integration
the unit tests cannot cover: route registration, the overlap-sample gate, the
flat ``{Label: value}`` storage container, and the geometry aggregator all have
to line up.

Historically this endpoint reported ``"unsupported"`` for image schemas — and,
because ``_gather_labels`` looked the schema up by name in a Label-keyed dict,
NaN over zero items for every other schema too.
"""

import json

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

SCHEMA = "objects"
ADMIN_KEY = "iaa-image-test-key"


def box(x, y, w=0.2, h=0.2, label="car"):
    return {"type": "bbox", "label": label, "color": "#f00",
            "coordinates": {"x": x, "y": y, "width": w, "height": h}}


def _start_server(name, preferred_port):
    """
    A two-annotator image project.

    The cap is 2 and *only* 2: an item that has reached its cap is complete, so
    a third annotator is never assigned it, is never moved into the annotation
    phase, and their saves land in a phase-page container instead of on the
    instance. Testing agreement and disagreement therefore needs two servers,
    not four annotators on one — a subtlety worth stating, because the naive
    version silently reports only the first pair.
    """
    test_dir = create_test_directory(name)
    data = [{"id": f"img_{i}", "text": f"image {i}",
             "image_url": f"http://example.invalid/{i}.jpg"} for i in range(4)]
    data_file = create_test_data_file(test_dir, data)
    config_file = create_test_config(
        test_dir,
        annotation_schemes=[{
            "annotation_type": "image_annotation",
            "name": SCHEMA,
            "description": "Objects",
            "tools": ["bbox"],
            "labels": [{"name": "car", "color": "#f00"},
                       {"name": "sign", "color": "#0f0"}],
        }],
        data_files=[data_file],
        item_properties={"id_key": "id", "text_key": "text"},
        annotation_task_name="IAA Image Report",
        require_password=False,
        admin_api_key=ADMIN_KEY,
        # Every item gets both annotators, so every item is an overlap item.
        num_annotators_per_item={"default": 2},
    )

    srv = FlaskTestServer(port=find_free_port(preferred_port=preferred_port),
                          debug=False, config_file=config_file)
    assert srv.start_server(), "Failed to start Flask server"
    srv._wait_for_server_ready(timeout=15)
    return srv, test_dir


@pytest.fixture(scope="module")
def server():
    srv, test_dir = _start_server("iaa_image_agree", 9077)
    yield srv
    srv.stop_server()
    cleanup_test_directory(test_dir)


@pytest.fixture(scope="module")
def disagree_server():
    srv, test_dir = _start_server("iaa_image_disagree", 9078)
    yield srv
    srv.stop_server()
    cleanup_test_directory(test_dir)


def login(server, user):
    s = requests.Session()
    s.post(f"{server.base_url}/register",
           data={"email": user, "pass": "pw", "action": "signup"})
    s.post(f"{server.base_url}/auth", data={"email": user, "pass": "pw"})
    s.get(f"{server.base_url}/annotate")
    return s


ITEM_IDS = [f"img_{i}" for i in range(4)]


def annotate_all(server, user, objects_for_item):
    """Save geometry on every item, driving by known instance id."""
    session = login(server, user)
    saved = []
    for instance_id in ITEM_IDS:
        session.get(f"{server.base_url}/annotate",
                    params={"instance_id": instance_id})
        r = session.post(
            f"{server.base_url}/updateinstance",
            json={"instance_id": instance_id,
                  "annotations": {
                      f"{SCHEMA}:::_data":
                          json.dumps(objects_for_item(instance_id))}},
        )
        assert r.status_code == 200, f"save failed for {instance_id}: {r.text}"
        saved.append(instance_id)
    return saved


def fetch_report(server):
    r = requests.get(f"{server.base_url}/admin/iaa",
                     headers={"X-API-Key": ADMIN_KEY})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def agreeing_report(server):
    """Both annotators draw the same box on every item they are assigned."""
    def same(instance_id):
        return [box(0.10, 0.10), box(0.60, 0.60, label="sign")]

    annotate_all(server, "iaa_alice", same)
    annotate_all(server, "iaa_bob", same)
    return fetch_report(server)


class TestReportIsReachable:
    def test_route_is_registered(self, server):
        """A bare @app.route never reaches the app create_app() builds."""
        r = requests.get(f"{server.base_url}/admin/iaa",
                         headers={"X-API-Key": ADMIN_KEY})
        assert r.status_code != 404

    def test_requires_the_admin_key(self, server):
        assert requests.get(f"{server.base_url}/admin/iaa").status_code == 403
        assert requests.get(f"{server.base_url}/admin/iaa",
                            headers={"X-API-Key": "wrong"}).status_code == 403


class TestImageSchemaIsReported:
    def test_schema_appears_with_the_geometry_kind(self, agreeing_report):
        schemas = agreeing_report["schemas"]
        assert SCHEMA in schemas, f"image schema missing from report: {schemas}"
        assert schemas[SCHEMA]["kind"] == "geometry"

    def test_metrics_are_real_numbers_not_nulls(self, agreeing_report):
        metrics = agreeing_report["schemas"][SCHEMA]["metrics"]
        for key in ("mean_agreement", "mean_matched_iou", "detection_f1",
                    "mean_object_count_diff"):
            assert key in metrics, f"{key} missing from {metrics}"
        assert metrics["n_annotators"] >= 2, metrics
        assert metrics["n_items"] >= 1, metrics

    def test_identical_geometry_reports_high_agreement(self, agreeing_report):
        metrics = agreeing_report["schemas"][SCHEMA]["metrics"]
        assert metrics["mean_agreement"] == pytest.approx(1.0, abs=1e-6)
        assert metrics["detection_f1"] == pytest.approx(1.0, abs=1e-6)


class TestDisagreementIsVisible:
    """The control: the report must be able to produce a low number too.

    Without this, every assertion above is satisfied by a stub that returns 1.0.
    """

    @pytest.fixture(scope="class")
    def disagreeing_report(self, disagree_server):
        annotate_all(disagree_server, "iaa_carol", lambda iid: [box(0.05, 0.05)])
        annotate_all(disagree_server, "iaa_dave", lambda iid: [box(0.75, 0.75)])
        return fetch_report(disagree_server)

    def test_disjoint_geometry_reports_zero_agreement(self, disagreeing_report):
        metrics = disagreeing_report["schemas"][SCHEMA]["metrics"]
        assert metrics["n_annotators"] == 2, metrics
        assert metrics["n_items"] == 4, metrics
        assert metrics["mean_agreement"] == pytest.approx(0.0, abs=1e-6)
        assert metrics["detection_f1"] == pytest.approx(0.0, abs=1e-6)

    def test_the_two_servers_disagree_with_each_other(self, agreeing_report,
                                                      disagreeing_report):
        """Same code path, opposite inputs, opposite answers."""
        agree = agreeing_report["schemas"][SCHEMA]["metrics"]["mean_agreement"]
        disagree = disagreeing_report["schemas"][SCHEMA]["metrics"]["mean_agreement"]
        assert agree > disagree


class TestJsonIsValid:
    """NaN is not valid JSON, and an undefined metric here is routine."""

    def test_response_parses_with_a_strict_json_parser(self, server):
        import simplejson

        r = requests.get(f"{server.base_url}/admin/iaa",
                         headers={"X-API-Key": ADMIN_KEY})
        # simplejson rejects the bare NaN token, exactly as the browser's
        # JSON.parse does. Flask's own encoder emits it happily.
        simplejson.loads(r.text)

    def test_undefined_metrics_are_null_not_nan(self, disagree_server):
        """Before any annotation, every metric is undefined."""
        r = requests.get(f"{disagree_server.base_url}/admin/iaa",
                         headers={"X-API-Key": ADMIN_KEY})
        assert "NaN" not in r.text, "bare NaN in JSON breaks strict parsers"

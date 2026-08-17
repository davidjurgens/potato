"""
The rendered ``/admin/iaa?format=html`` page over a rollout project.

The JSON side of a rollout report is covered by ``tests/unit/test_rollout_agreement.py``.
This file covers the half that was broken: a rollout report is *nested* — four
groups of metrics behind a sweep over the matching tolerance — and the page
formatted only top-level numbers. Every real number rendered as ``n/a``, and
the one number that did render, ``n_items_skipped: 0``, rendered as **"weak
agreement"** in red, because the banding rule was ``value < 0.2`` applied to
whatever happened to be numeric.

So these assertions are about the HTML, not the arithmetic: the JSON was always
right and the page never showed it.
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

SCHEMA = "rollouts"
ADMIN_KEY = "iaa-rollout-test-key"
ITEM_IDS = [f"scene_{i}" for i in range(3)]


def _streams():
    return [
        {"id": "real", "url": "real.webm", "role": "real", "name": "Recording"},
        {"id": "gen_a", "url": "a.webm", "role": "model", "name": "Model A"},
        {"id": "gen_b", "url": "b.webm", "role": "model", "name": "Model B"},
    ]


@pytest.fixture(scope="module")
def server():
    test_dir = create_test_directory("iaa_rollout_page")
    data = [{"id": iid, "text": f"scenario {i}", "streams": _streams()}
            for i, iid in enumerate(ITEM_IDS)]
    data_file = create_test_data_file(test_dir, data)
    config_file = create_test_config(
        test_dir,
        annotation_schemes=[{
            "annotation_type": "rollout_evaluation",
            "name": SCHEMA,
            "description": "Where does each rollout stop making sense?",
            "manifest_field": "streams",
            "fps": 25,
        }],
        data_files=[data_file],
        item_properties={"id_key": "id", "text_key": "text"},
        annotation_task_name="Rollout IAA page",
        require_password=False,
        admin_api_key=ADMIN_KEY,
        num_annotators_per_item={"default": 2},
    )
    srv = FlaskTestServer(port=find_free_port(preferred_port=9081),
                          debug=False, config_file=config_file)
    assert srv.start_server(), "Failed to start Flask server"
    srv._wait_for_server_ready(timeout=15)
    yield srv
    srv.stop_server()
    cleanup_test_directory(test_dir)


def _annotate(server, user, offset):
    """
    Mark one break per item, ``offset`` seconds later than the other annotator.

    0.2 s apart is inside the 0.25 s tolerance and outside the 0.04 s one, so
    the sweep has something to show: the same annotations agree at a loose
    window and disagree at a tight one, which is the whole reason the sweep is
    reported instead of a single number.
    """
    session = requests.Session()
    session.post(f"{server.base_url}/register",
                 data={"email": user, "pass": "pw", "action": "signup"})
    session.post(f"{server.base_url}/auth", data={"email": user, "pass": "pw"})
    session.get(f"{server.base_url}/annotate")
    for index, instance_id in enumerate(ITEM_IDS):
        session.get(f"{server.base_url}/annotate",
                    params={"instance_id": instance_id})
        value = {
            "violations": [{"stream_id": "gen_a", "t": 2.0 + index + offset,
                            "type": "gravity_violation",
                            "severity": "major" if offset else "minor"}],
            "clean": ["real", "gen_b"],
            "preference": {"winner": "gen_b"},
            "counterfactual": {"verdict": "plausible"},
        }
        response = session.post(
            f"{server.base_url}/updateinstance",
            json={"instance_id": instance_id,
                  "annotations": {f"{SCHEMA}:::_data": json.dumps(value)}})
        assert response.status_code == 200, response.text


@pytest.fixture(scope="module")
def page(server):
    _annotate(server, "roll_alice", 0.0)
    _annotate(server, "roll_bob", 0.2)
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


class TestTheReportIsComputed:
    def test_the_rollout_schema_is_in_the_json(self, report):
        assert SCHEMA in report["schemas"]
        assert report["schemas"][SCHEMA]["kind"] == "rollout"

    def test_the_json_is_still_the_nested_report(self, report):
        """Presentation is the HTML path only; the API shape is unchanged."""
        metrics = report["schemas"][SCHEMA]["metrics"]
        assert isinstance(metrics["detection"], dict)
        assert isinstance(metrics["sweep"], list)


class TestTheNumbersReachThePage:
    def test_grouped_metrics_are_rendered(self, page):
        cells = _cells(page)
        assert "localization.sigma" in cells, (
            "nested groups never reached the page — this is the original bug")
        assert re.match(r"^-?\d+\.\d{3}", cells["localization.sigma"])

    def test_the_page_is_not_mostly_na(self, page):
        """
        The symptom, stated as a proportion: before the fix, of the eight
        top-level keys in a rollout report, six were dicts and printed "n/a".
        """
        cells = _cells(page)
        metric_cells = {k: v for k, v in cells.items() if "." in k}
        assert metric_cells, "no dotted metric rows at all"
        na = [k for k, v in metric_cells.items() if v.startswith("n/a")]
        assert len(na) < len(metric_cells) / 2, f"still mostly n/a: {na}"

    def test_counts_are_not_labelled_as_agreement(self, page):
        """`n_items_skipped: 0` was rendered as "weak agreement" in red."""
        cells = _cells(page)
        assert "weak" not in cells.get("n_items_skipped", "")
        assert "agreement" not in cells.get("n_items_skipped", "")

    def test_coverage_is_not_labelled_as_agreement(self, page):
        """Full coverage means everyone answered, not that they agreed."""
        cells = _cells(page)
        value = cells.get("coverage.answered_fraction", "")
        assert value.startswith("1.000")
        assert "agreement" not in value

    def test_an_undefined_alpha_shows_its_reason(self, page):
        """
        Every annotator picked the same winner, so alpha is undefined for a
        stated reason. Printing "n/a" says the opposite of the reason.
        """
        cells = _cells(page)
        preference = cells.get("preference.alpha", "")
        assert "no variation" in preference, preference
        assert not preference.startswith("n/a")


class TestTheSweep:
    def test_the_sweep_is_a_table(self, page):
        assert 'class="admin-table iaa-sweep-table"' in page
        assert "matching window (s)" in page

    def test_the_headline_row_is_marked(self, page):
        assert "iaa-sweep-headline" in page

    def test_tightening_the_window_changes_the_answer(self, report):
        """
        The reason the sweep exists. Marks 0.2 s apart match at 0.25 s and do
        not match at 0.04 s, so the two rows must disagree — if they did not,
        the sweep would be five copies of one number.
        """
        sweep = {row["tolerance"]: row
                 for row in report["schemas"][SCHEMA]["metrics"]["sweep"]}
        tight = sweep[0.04]["localization"]["n_matched_pairs"]
        loose = sweep[0.25]["localization"]["n_matched_pairs"]
        assert tight == 0
        assert loose == len(ITEM_IDS)


class TestTheOtherSchemasStillRender:
    def test_the_page_carries_its_scale_legend(self, page):
        assert "κ-family scale" in page
        assert "Coverage:" in page

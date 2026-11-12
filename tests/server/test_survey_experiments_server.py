"""A list experiment over HTTP: the control group's page does not contain the
sensitive statement, the treatment group's does, and the export estimates
the difference in means from saved counts."""

import csv
import os

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    cleanup_test_directory, create_test_config, create_test_data_file, create_test_directory)

SENSITIVE = "I have driven after drinking in the last year."


@pytest.fixture(scope="module")
def le_server(request):
    d = create_test_directory("survey_experiments_server")
    data = create_test_data_file(d, [{"id": "q1", "text": "Survey"}])
    config = create_test_config(
        d, annotation_schemes=[{
            "annotation_type": "list_experiment", "name": "lists",
            "description": "How many of these are true for you?",
            "items": ["I own a bicycle.", "I went to a concert this year.", "I read a paper daily."],
            "sensitive_item": SENSITIVE,
            "treatment": {"factor": "list_group", "level": "treatment"}}],
        data_files=[data],
        additional_config={"conditions": {"factors": {"list_group": ["control", "treatment"]},
                                          "assignment": "round_robin"}})
    server = FlaskTestServer(config=config)
    if not server.start():
        pytest.fail("Failed to start Flask test server")
    server.test_dir = d
    server.config_path = config
    request.addfinalizer(lambda: (server.stop(), cleanup_test_directory(d)))
    return server


def test_gating_and_estimate(le_server):
    base = le_server.base_url
    seen = {}
    counts = {"control": [1, 2], "treatment": [3, 2]}
    for i in range(4):
        s = requests.Session()
        name = f"le_{i}"
        s.post(f"{base}/register", data={"action": "signup", "email": name, "pass": "p"}, timeout=5)
        s.post(f"{base}/auth", data={"action": "login", "email": name, "pass": "p"}, timeout=5)
        html = s.get(f"{base}/annotate", timeout=5).text
        group = "treatment" if SENSITIVE in html else "control"
        assert "data-condition-only" not in html
        seen.setdefault(group, 0)
        count = counts[group][seen[group]]
        seen[group] += 1
        r = s.post(f"{base}/updateinstance", json={"instance_id": "q1",
                   "annotations": {"lists:::number": str(count)}, "span_annotations": []}, timeout=5)
        assert r.status_code == 200
    assert seen == {"control": 2, "treatment": 2}

    from potato.export.cli import build_export_context
    from potato.export.survey_experiment_exporter import SurveyExperimentExporter
    ctx = build_export_context(le_server.config_path)
    out = os.path.join(le_server.test_dir, "export")
    assert SurveyExperimentExporter().export(ctx, out).success
    row = next(csv.DictReader(open(os.path.join(out, "survey_experiments.csv"))))
    assert float(row["estimate"]) == pytest.approx(2.5 - 1.5)
    assert row["n_treatment"] == "2" and row["n_control"] == "2"

"""
/admin/api/agreement over two annotators, asserting the numbers.

Audit 25 found that this endpoint had never produced a single number. It calls
simpledorff, and it called the wrong one of two similarly named functions: the
kwargs it passes belong to ``calculate_krippendorffs_alpha_for_df``, and the
bare ``calculate_krippendorffs_alpha`` takes an experiment-by-annotator table
and one metric. The TypeError was the first statement in the per-schema ``try``,
so Cohen's and Fleiss' kappa were never reached either.

Nothing showed it with one annotator, which is why it survived: an earlier
branch returns "No items with 2+ annotators" and the call never runs. The
existing tests for this endpoint all assert a status code and stop, so a 200
carrying ``{"error": "..."}`` for every schema read as a pass.

The data and the expected alphas are the auditor's, hand-computed against
simpledorff directly.
"""

import time

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager


# Eight items, two annotators. Agreement is deliberately partial in both
# schemas: a test whose annotators agree everywhere passes with any measure
# that returns 1.0, including a broken one.
ELIGIBILITY = {
    "a1": ["eligible", "ineligible", "ineligible", "ineligible",
           "nei", "eligible", "nei", "nei"],
    "a2": ["eligible", "ineligible", "ineligible", "eligible",
           "nei", "eligible", "ineligible", "nei"],
}
CERTAINTY = {
    "a1": [4, 5, 5, 4, 3, 5, 2, 1],
    "a2": [4, 5, 4, 3, 4, 5, 3, 1],
}

EXPECTED_ELIGIBILITY_ALPHA = 0.6471   # nominal
EXPECTED_CERTAINTY_ALPHA = 0.8649     # interval


@pytest.fixture(scope="module")
def agreement_server():
    schemes = [
        {
            "annotation_type": "radio",
            "name": "eligibility",
            "description": "Is this patient eligible?",
            "labels": ["eligible", "ineligible", "nei"],
        },
        {
            "annotation_type": "likert",
            "name": "certainty",
            "description": "How certain are you?",
            "size": 5,
            "min_label": "not at all",
            "max_label": "completely",
        },
    ]
    with TestConfigManager(
        "audit25_agreement",
        schemes,
        num_instances=8,
        num_annotators_per_item=2,
    ) as cfg:
        server = FlaskTestServer(port=9047, config_file=cfg.config_path,
                                 debug=True)
        if not server.start():
            pytest.fail("Failed to start server")
        _annotate_everything(server)
        yield server
        server.stop()


def _annotate_everything(server):
    """Put both annotators through all eight items."""
    for annotator in ("a1", "a2"):
        session = requests.Session()
        session.post(f"{server.base_url}/register",
                     data={"email": f"{annotator}@lab.org", "pass": "pw"})
        session.post(f"{server.base_url}/auth",
                     data={"email": f"{annotator}@lab.org", "pass": "pw"})
        session.get(f"{server.base_url}/annotate")

        for index in range(8):
            instance_id = str(index + 1)
            response = session.post(
                f"{server.base_url}/updateinstance",
                json={
                    "instance_id": instance_id,
                    # Flat `schema:::label`. The nested shape stores nothing
                    # and now earns a 400.
                    "annotations": {
                        f"eligibility:::{ELIGIBILITY[annotator][index]}": "true",
                        f"certainty:::{CERTAINTY[annotator][index]}": "true",
                    },
                },
            )
            assert response.status_code == 200, response.text
        time.sleep(0.2)


def _agreement(server):
    response = requests.get(f"{server.base_url}/admin/api/agreement")
    assert response.status_code == 200, response.text
    return response.json()


class TestAgreementMetricsProduceNumbers:

    def test_every_schema_reports_an_alpha_rather_than_an_error(
            self, agreement_server):
        by_schema = _agreement(agreement_server)["by_schema"]
        for name in ("eligibility", "certainty"):
            assert "error" not in by_schema[name], (
                f"{name} reported an error instead of a number: "
                f"{by_schema[name]}")
            assert "krippendorff_alpha" in by_schema[name]

    def test_nominal_alpha_matches_the_hand_computed_value(
            self, agreement_server):
        """The label NAME is the answer, not the stored value.

        Reading the value gave True for every annotator on every categorical
        schema. Anything that compares values rather than names cannot land on
        0.6471 -- six of eight items agree, and unanimity would be 1.0 or NaN.
        """
        eligibility = _agreement(agreement_server)["by_schema"]["eligibility"]
        assert eligibility["metric_type"] == "nominal"
        assert eligibility["items_evaluated"] == 8
        assert eligibility["krippendorff_alpha"] == pytest.approx(
            EXPECTED_ELIGIBILITY_ALPHA, abs=1e-4)

    def test_interval_alpha_matches_the_hand_computed_value(
            self, agreement_server):
        """A rating has to reach the interval metric as a number.

        The shared normalizer stringifies every answer, which is correct for
        nominal comparison and raises TypeError inside interval_metric, so a
        likert schema stayed broken even after the call itself was fixed.
        """
        certainty = _agreement(agreement_server)["by_schema"]["certainty"]
        assert certainty["metric_type"] == "interval"
        assert certainty["krippendorff_alpha"] == pytest.approx(
            EXPECTED_CERTAINTY_ALPHA, abs=1e-4)

    def test_kappas_are_reached_for_categorical_schemas(self, agreement_server):
        """They sit after the alpha call inside the same try.

        Reporting them is the point of this assertion: with the alpha call
        raising, no kappa was ever computed for any study.
        """
        eligibility = _agreement(agreement_server)["by_schema"]["eligibility"]
        assert "kappa_error" not in eligibility, eligibility.get("kappa_error")
        assert isinstance(eligibility.get("cohen_kappa"), dict)
        assert isinstance(eligibility.get("fleiss_kappa"), dict)
        assert eligibility["cohen_kappa"].get("mean_kappa") is not None
        assert eligibility["fleiss_kappa"].get("kappa") is not None

    def test_overall_is_populated(self, agreement_server):
        """`overall` is built by filtering for schemas that carry an alpha.

        With every schema erroring, it stayed {} -- the shape the dashboard
        reads, so the page rendered blank rather than saying anything failed.
        """
        overall = _agreement(agreement_server)["overall"]
        assert overall.get("schemas_evaluated") == 2
        expected = (EXPECTED_ELIGIBILITY_ALPHA + EXPECTED_CERTAINTY_ALPHA) / 2
        assert overall["average_krippendorff_alpha"] == pytest.approx(
            expected, abs=1e-3)
        assert overall.get("average_cohen_kappa") is not None
        assert overall.get("average_fleiss_kappa") is not None

    def test_one_annotator_per_item_is_not_counted_as_overlap(
            self, agreement_server):
        """A multiselect chooses several names at once.

        Those used to be appended as separate rows, so one person clearing two
        checkboxes satisfied a two-annotator overlap on their own. Here the
        radio picks one name, so the count is the annotator count.
        """
        by_schema = _agreement(agreement_server)["by_schema"]
        assert by_schema["eligibility"]["total_annotations"] == 16

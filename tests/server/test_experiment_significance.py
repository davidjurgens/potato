"""Server integration test: experiment-compare paired significance badges (D7)."""

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager


@pytest.fixture(scope="class", autouse=True)
def flask_server(request):
    schemes = [{"annotation_type": "radio", "name": "ok",
                "description": "ok?", "labels": ["yes", "no"]}]
    extra = {"datasets": {"enabled": True, "storage": "file"}}
    with TestConfigManager("exp_sig", schemes,
                           additional_config=extra,
                           admin_api_key="test-admin-api-key") as test_config:
        server = FlaskTestServer(port=9073, config_file=test_config.config_path)
        if not server.start():
            pytest.fail("Failed to start server")

        # Seed two experiments in-process: A clearly beats baseline B on every
        # example, so the paired delta must be flagged significant.
        from potato.eval_datasets.manager import get_datasets_manager
        from potato.experiments.models import Experiment, ExperimentResult
        mgr = get_datasets_manager()
        assert mgr is not None

        def mk(eid, name, score):
            return Experiment(
                id=eid, dataset_name="d", dataset_version="1", name=name,
                aggregate_scores={"acc": score}, example_count=8,
                results=[ExperimentResult(example_id=f"e{i}", scores={"acc": score})
                         for i in range(8)])

        mgr.experiments.save(mk("exp-base", "Baseline", 0.0))
        mgr.experiments.save(mk("exp-new", "New", 1.0))

        request.cls.server = server
        yield server
        server.stop()


class TestExperimentSignificance:
    def _admin(self):
        s = requests.Session()
        s.headers.update({"X-API-Key": self.server.admin_api_key})
        return s, self.server.base_url

    def test_compare_page_renders_significance(self):
        s, base = self._admin()
        r = s.get(f"{base}/datasets/experiments/compare?ids=exp-base,exp-new")
        assert r.status_code == 200, r.text
        # baseline first, so delta vs baseline is +1.000 and significant
        assert "ec-sig" in r.text
        assert "significant" in r.text
        assert "95% CI" in r.text

    def test_compare_admin_guarded(self):
        r = requests.get(f"{self.server.base_url}/datasets/experiments/compare?ids=exp-base,exp-new")
        assert r.status_code in (401, 403)

"""
Server tests for required annotation enforcement:
verifying that forward navigation is blocked when required schemas aren't satisfied.
"""
import pytest
import requests
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager


class TestRequiredAnnotation:
    """Test server-side required annotation blocking."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        annotation_schemes = [
            {
                "annotation_type": "radio",
                "name": "required_radio",
                "labels": ["yes", "no"],
                "description": "Required question",
                "required": True,
            },
            {
                "annotation_type": "radio",
                "name": "optional_radio",
                "labels": ["a", "b"],
                "description": "Optional question",
            },
        ]
        with TestConfigManager(
            "required_annot_test", annotation_schemes, num_items=3
        ) as test_config:
            server = FlaskTestServer(port=9044, config_file=test_config.config_path)
            if not server.start():
                pytest.fail("Failed to start server")
            request.cls.server = server
            yield server
            server.stop()

    def _login(self, username="req_test_user"):
        s = requests.Session()
        s.post(
            f"{self.server.base_url}/register",
            data={"email": username, "pass": "pw"},
        )
        # Ensure we're on the annotate page
        s.get(f"{self.server.base_url}/annotate")
        return s

    def test_next_blocked_without_required_annotation(self):
        """next_instance should return 400 when required schema is not annotated."""
        s = self._login("req_block_user")
        r = s.post(
            f"{self.server.base_url}/annotate",
            json={"action": "next_instance"},
        )
        assert r.status_code == 400
        data = r.json()
        assert data["status"] == "validation_error"
        assert "required_radio" in data["unsatisfied_schemas"]

    def test_next_allowed_after_annotating_required(self):
        """next_instance should succeed after the required schema is annotated."""
        s = self._login("req_allow_user")
        # Annotate the required schema using the colon-separated format
        s.post(
            f"{self.server.base_url}/updateinstance",
            json={
                "instance_id": "1",
                "annotations": {"required_radio:yes": True},
            },
        )
        # Now next_instance should work
        r = s.post(
            f"{self.server.base_url}/annotate",
            json={"action": "next_instance"},
        )
        assert r.status_code == 200

    def test_go_to_forward_blocked(self):
        """go_to with a forward index should be blocked without required annotation."""
        s = self._login("req_goto_user")
        r = s.post(
            f"{self.server.base_url}/annotate",
            json={"action": "go_to", "go_to": 1},
        )
        assert r.status_code == 400

    def test_jump_to_unannotated_blocked(self):
        """jump_to_unannotated should be blocked without required annotation."""
        s = self._login("req_jump_user")
        r = s.post(
            f"{self.server.base_url}/annotate",
            json={"action": "jump_to_unannotated"},
        )
        assert r.status_code == 400

    def test_optional_schema_does_not_block(self):
        """Optional schemas should not block navigation even when unannotated."""
        s = self._login("req_opt_user")
        # Only annotate the required schema, leave optional empty
        s.post(
            f"{self.server.base_url}/updateinstance",
            json={
                "instance_id": "1",
                "annotations": {"required_radio:no": True},
            },
        )
        r = s.post(
            f"{self.server.base_url}/annotate",
            json={"action": "next_instance"},
        )
        assert r.status_code == 200

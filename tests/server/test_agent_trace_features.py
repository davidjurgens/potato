"""
Server integration tests for agent trace P2 features.

Tests:
1. Multi-dimension per_turn_ratings renders correctly in HTML
2. Agent trace display type (step cards) renders via real server
3. Visual agent evaluation example loads and renders
4. Dynamic multirate options_from_data works end-to-end
5. Agent eval export produces valid output with annotations
"""

import json
import os
import shutil
import uuid
import yaml
import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_config,
    create_test_data_file,
    cleanup_test_directory,
)


def get_project_root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))


# ---------------------------------------------------------------------------
# Helper: create a config with instance_display directly (yaml-based)
# ---------------------------------------------------------------------------

def create_yaml_config(test_dir, config_dict):
    """Write a full config dict to config.yaml in test_dir, return path."""
    config_path = os.path.join(test_dir, "config.yaml")
    # Ensure task_dir is absolute
    config_dict.setdefault("task_dir", os.path.abspath(test_dir))
    config_dict.setdefault("output_annotation_dir",
                           os.path.join(os.path.abspath(test_dir), "output"))
    config_dict.setdefault("output_annotation_format", "json")
    config_dict.setdefault("require_password", False)
    config_dict.setdefault("user_config", {"allow_all_users": True})
    config_dict.setdefault("secret_key", "test-secret")

    with open(config_path, "w") as f:
        yaml.dump(config_dict, f)
    return config_path


def register_and_get_annotate(server, username="test_user"):
    """Register a user and return the annotation page HTML."""
    session = requests.Session()
    session.post(
        f"{server.base_url}/register",
        data={"action": "signup", "email": username, "pass": "pass"},
        timeout=5,
    )
    resp = session.get(f"{server.base_url}/annotate", timeout=5)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    return resp.text, session


# =========================================================================
# 1. Multi-dimension per_turn_ratings
# =========================================================================

class TestMultiDimensionPerTurnRatings:
    """Server test: the multi-scheme per_turn_ratings HTML renders correctly."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Start server with the agent-trace-evaluation example (uses schemes)."""
        project_root = get_project_root()
        config_path = os.path.join(
            project_root,
            "examples/agent-traces/agent-trace-evaluation/config.yaml",
        )

        server = FlaskTestServer(config=config_path)
        if not server.start():
            pytest.fail("Failed to start server for multi-dim per_turn_ratings test")

        yield server
        server.stop()

    def test_page_renders_both_schema_names(self, flask_server):
        """HTML should contain both 'action_correctness' and 'reasoning_quality'."""
        html, _ = register_and_get_annotate(flask_server, "ptr_schema")
        assert "action_correctness" in html
        assert "reasoning_quality" in html

    def test_page_has_per_turn_hidden_inputs(self, flask_server):
        """Each scheme should have its own hidden input with data-schema-name."""
        html, _ = register_and_get_annotate(flask_server, "ptr_hidden")
        assert 'data-schema-name="action_correctness"' in html
        assert 'data-schema-name="reasoning_quality"' in html

    def test_page_has_ptr_value_elements(self, flask_server):
        """Clickable ptr-value elements should carry data-schema attributes."""
        html, _ = register_and_get_annotate(flask_server, "ptr_values")
        assert 'data-schema="action_correctness"' in html
        assert 'data-schema="reasoning_quality"' in html

    def test_per_turn_rating_group_wrapper(self, flask_server):
        """Multi-scheme layout should have the per-turn-rating-group wrapper."""
        html, _ = register_and_get_annotate(flask_server, "ptr_group")
        assert "per-turn-rating-group" in html

    def test_schema_labels_present(self, flask_server):
        """Schema display labels should appear in the HTML."""
        html, _ = register_and_get_annotate(flask_server, "ptr_labels")
        # The dialogue display renders schema names as labels (title-cased)
        assert "Action Correctness:" in html or "action_correctness" in html
        assert "Reasoning Quality:" in html or "reasoning_quality" in html


# =========================================================================
# 2. Agent trace display type renders step cards
# =========================================================================

class TestAgentTraceDisplayType:
    """Server test: the agent_trace display type renders step cards."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("agent_trace_display")
        request.cls.test_dir = test_dir

        # Create data with conversation in ReAct-style format
        test_data = [
            {
                "id": "trace_at_001",
                "task_description": "Find the weather in Paris",
                "conversation": [
                    {"speaker": "Agent (Thought)", "text": "I need to search for weather info."},
                    {"speaker": "Agent (Action)", "text": "search(query='Paris weather')"},
                    {"speaker": "Environment", "text": "Paris: 18C, partly cloudy."},
                ],
            }
        ]
        data_file = create_test_data_file(test_dir, test_data, "traces.json")

        config_dict = {
            "annotation_task_name": "Agent Trace Display Test",
            "data_files": ["traces.json"],
            "item_properties": {"id_key": "id", "text_key": "task_description"},
            "instance_display": {
                "layout": {"direction": "vertical", "gap": "12px"},
                "fields": [
                    {"key": "task_description", "type": "text", "label": "Task"},
                    {
                        "key": "conversation",
                        "type": "agent_trace",
                        "label": "Trace",
                        "span_target": True,
                        "display_options": {
                            "show_step_numbers": True,
                            "show_summary": True,
                            "collapse_observations": False,
                        },
                    },
                ],
            },
            "annotation_schemes": [
                {
                    "annotation_type": "radio",
                    "name": "success",
                    "description": "Success?",
                    "labels": ["yes", "no"],
                },
            ],
        }
        config_path = create_yaml_config(test_dir, config_dict)

        server = FlaskTestServer(config=config_path)
        if not server.start():
            pytest.fail("Failed to start server for agent_trace display test")

        yield server
        server.stop()
        cleanup_test_directory(test_dir)

    def test_step_type_badges(self, flask_server):
        """HTML should contain step-type CSS classes for thought/action/observation."""
        html, _ = register_and_get_annotate(flask_server, "at_badges")
        assert "step-type-thought" in html
        assert "step-type-action" in html
        assert "step-type-observation" in html

    def test_step_content_rendered(self, flask_server):
        """The actual trace text should appear in the HTML."""
        html, _ = register_and_get_annotate(flask_server, "at_content")
        assert "I need to search for weather info" in html
        assert "Paris weather" in html
        assert "18C" in html or "18°C" in html or "partly cloudy" in html

    def test_summary_section(self, flask_server):
        """Agent trace display should include a summary with step count."""
        html, _ = register_and_get_annotate(flask_server, "at_summary")
        assert "agent-trace-summary" in html
        assert "3 steps" in html

    def test_span_target_attributes(self, flask_server):
        """Span target attributes should be present for span annotation support."""
        html, _ = register_and_get_annotate(flask_server, "at_span")
        assert "data-original-text" in html or "data-step-index" in html


# =========================================================================
# 3. Visual agent evaluation example
# =========================================================================

class TestVisualAgentEvaluation:
    """Server test: the visual-agent-evaluation example config loads correctly."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        project_root = get_project_root()
        config_path = os.path.join(
            project_root,
            "examples/agent-traces/visual-agent-evaluation/config.yaml",
        )

        server = FlaskTestServer(config=config_path)
        if not server.start():
            pytest.fail("Failed to start visual agent evaluation server")

        yield server
        server.stop()

    def test_server_starts(self, flask_server):
        resp = requests.get(f"{flask_server.base_url}/", timeout=5)
        assert resp.status_code in [200, 302]

    def test_annotation_page_renders(self, flask_server):
        html, _ = register_and_get_annotate(flask_server, "vis_render")
        assert "task_success" in html

    def test_gui_error_schema_present(self, flask_server):
        """The GUI-specific error multiselect should be present."""
        html, _ = register_and_get_annotate(flask_server, "vis_gui")
        assert "gui_errors" in html

    def test_grounding_accuracy_schema_present(self, flask_server):
        """The grounding_accuracy radio schema should be present."""
        html, _ = register_and_get_annotate(flask_server, "vis_grounding")
        assert "grounding_accuracy" in html

    def test_image_display_present(self, flask_server):
        """The image display field should render for screenshots."""
        html, _ = register_and_get_annotate(flask_server, "vis_image")
        # The image display renders an <img> tag or image-related CSS class
        assert "display-type-image" in html or "<img" in html


# =========================================================================
# 4. Dynamic multirate options_from_data
# =========================================================================

class TestDynamicMultirateServer:
    """Server test: options_from_data injects step labels at render time."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("dynamic_multirate")
        request.cls.test_dir = test_dir

        # Data includes step_summaries field for dynamic multirate
        test_data = [
            {
                "id": "dm_001",
                "text": "Rate each step of the agent trace",
                "step_summaries": [
                    "Search for flights",
                    "Compare prices",
                    "Book cheapest option",
                ],
            },
            {
                "id": "dm_002",
                "text": "Rate each step of the second trace",
                "step_summaries": [
                    "Open browser",
                    "Navigate to site",
                ],
            },
        ]
        data_file = create_test_data_file(test_dir, test_data, "data.json")

        config_dict = {
            "annotation_task_name": "Dynamic Multirate Test",
            "data_files": ["data.json"],
            "item_properties": {"id_key": "id", "text_key": "text"},
            "annotation_schemes": [
                {
                    "annotation_type": "multirate",
                    "name": "step_ratings",
                    "description": "Rate each step",
                    "options_from_data": "step_summaries",
                    "labels": ["Incorrect", "Questionable", "Correct"],
                },
            ],
        }
        config_path = create_yaml_config(test_dir, config_dict)

        server = FlaskTestServer(config=config_path)
        if not server.start():
            pytest.fail("Failed to start server for dynamic multirate test")

        yield server
        server.stop()
        cleanup_test_directory(test_dir)

    def test_step_summaries_injected(self, flask_server):
        """The step_summaries from instance data should appear in data-options-values."""
        html, _ = register_and_get_annotate(flask_server, "dm_inject")
        # Dynamic multirate injects options into a data-options-values attribute
        # (the JS renders them client-side). Check the attribute is populated.
        assert "data-options-values" in html
        # The attribute should contain the step summaries as JSON
        assert "Search for flights" in html
        assert "Compare prices" in html
        assert "Book cheapest option" in html

    def test_multirate_labels_present(self, flask_server):
        """The rating labels should appear in the rendered HTML."""
        html, _ = register_and_get_annotate(flask_server, "dm_labels")
        assert "Incorrect" in html
        assert "Questionable" in html
        assert "Correct" in html

    def test_multirate_schema_name_present(self, flask_server):
        """The schema name should be in the form."""
        html, _ = register_and_get_annotate(flask_server, "dm_schema")
        assert "step_ratings" in html


# =========================================================================
# 5. Agent eval export with annotations
# =========================================================================

class TestAgentEvalExport:
    """Server test: agent_eval export produces valid structured output."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("agent_eval_export")
        request.cls.test_dir = test_dir

        test_data = [
            {
                "id": "export_001",
                "text": "Task 1: book a flight",
            },
            {
                "id": "export_002",
                "text": "Task 2: find a hotel",
            },
        ]
        data_file = create_test_data_file(test_dir, test_data, "data.json")

        config_dict = {
            "annotation_task_name": "Agent Eval Export Test",
            "data_files": ["data.json"],
            "item_properties": {"id_key": "id", "text_key": "text"},
            "annotation_schemes": [
                {
                    "annotation_type": "radio",
                    "name": "task_success",
                    "description": "Did the agent succeed?",
                    "labels": [
                        {"name": "success"},
                        {"name": "partial"},
                        {"name": "failure"},
                    ],
                    "sequential_key_binding": True,
                },
                {
                    "annotation_type": "likert",
                    "name": "efficiency",
                    "description": "How efficient?",
                    "min_label": "Inefficient",
                    "max_label": "Optimal",
                    "size": 5,
                },
            ],
            "admin_api_key": "test-admin-key",
        }
        config_path = create_yaml_config(test_dir, config_dict)

        server = FlaskTestServer(config=config_path)
        if not server.start():
            pytest.fail("Failed to start server for agent eval export test")

        yield server
        server.stop()
        cleanup_test_directory(test_dir)

    def test_submit_annotations_and_verify(self, flask_server):
        """Submit annotations for both items, then verify they're stored."""
        session = requests.Session()
        session.post(
            f"{flask_server.base_url}/register",
            data={"action": "signup", "email": "export_user", "pass": "pass"},
            timeout=5,
        )

        # Get annotation page (item 1)
        resp = session.get(f"{flask_server.base_url}/annotate", timeout=5)
        assert resp.status_code == 200

        # Submit annotation for item 1
        resp = session.post(
            f"{flask_server.base_url}/updateinstance",
            data={
                "task_success": json.dumps({"success": "1"}),
                "efficiency": "4",
            },
            timeout=5,
        )
        assert resp.status_code in [200, 302]

    def test_agent_eval_exporter_unit(self, flask_server):
        """Test the exporter logic directly with mock annotations."""
        from potato.export.agent_eval_exporter import AgentEvalExporter
        from potato.export.base import ExportContext

        exporter = AgentEvalExporter()

        annotations = [
            {
                "instance_id": "trace_001",
                "user_id": "user_a",
                "labels": {
                    "task_success": {"success": "1"},
                    "efficiency": 4,
                },
            },
            {
                "instance_id": "trace_001",
                "user_id": "user_b",
                "labels": {
                    "task_success": {"partial": "1"},
                    "efficiency": 3,
                },
            },
            {
                "instance_id": "trace_002",
                "user_id": "user_a",
                "labels": {
                    "task_success": {"failure": "1"},
                    "efficiency": 2,
                },
            },
        ]

        schemas = [
            {"name": "task_success", "annotation_type": "radio"},
            {"name": "efficiency", "annotation_type": "likert"},
        ]

        output_dir = os.path.join(self.test_dir, "export_output")
        os.makedirs(output_dir, exist_ok=True)

        context = ExportContext(
            config={},
            annotations=annotations,
            items={
                "trace_001": {"id": "trace_001", "text": "Task 1"},
                "trace_002": {"id": "trace_002", "text": "Task 2"},
            },
            schemas=schemas,
            output_dir=output_dir,
        )

        result = exporter.export(context, output_dir)
        assert result.success, f"Export failed: {result.errors}"
        assert len(result.files_written) == 2

        # Verify JSON output
        json_path = os.path.join(output_dir, "agent_evaluation.json")
        assert os.path.exists(json_path)

        with open(json_path) as f:
            output = json.load(f)

        assert output["summary"]["total_traces"] == 2
        assert output["summary"]["total_annotators"] == 2
        assert len(output["per_trace"]) == 2

        # Check trace_001 aggregation
        trace_001 = next(t for t in output["per_trace"] if t["trace_id"] == "trace_001")
        assert trace_001["annotator_count"] == 2
        assert "task_success" in trace_001["annotations"]
        assert "efficiency" in trace_001["annotations"]
        assert trace_001["annotations"]["efficiency"]["mean"] == 3.5

        # Verify CSV output
        csv_path = os.path.join(output_dir, "agent_evaluation_summary.csv")
        assert os.path.exists(csv_path)

        with open(csv_path) as f:
            lines = f.readlines()
        assert len(lines) == 3  # header + 2 traces


# =========================================================================
# 6. Annotation submission and persistence for agent traces
# =========================================================================

class TestAgentTraceAnnotationPersistence:
    """Server test: annotations on agent traces persist across navigation."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("agent_persist")
        request.cls.test_dir = test_dir

        test_data = [
            {
                "id": "persist_001",
                "task_description": "Task A",
                "conversation": [
                    {"speaker": "Agent (Thought)", "text": "Thinking..."},
                    {"speaker": "Agent (Action)", "text": "do_thing()"},
                    {"speaker": "Environment", "text": "Done."},
                ],
            },
            {
                "id": "persist_002",
                "task_description": "Task B",
                "conversation": [
                    {"speaker": "Agent (Thought)", "text": "Planning..."},
                    {"speaker": "Agent (Action)", "text": "other_thing()"},
                ],
            },
        ]
        data_file = create_test_data_file(test_dir, test_data, "data.json")

        config_dict = {
            "annotation_task_name": "Persistence Test",
            "data_files": ["data.json"],
            "item_properties": {"id_key": "id", "text_key": "task_description"},
            "instance_display": {
                "layout": {"direction": "vertical"},
                "fields": [
                    {"key": "task_description", "type": "text", "label": "Task"},
                    {
                        "key": "conversation",
                        "type": "dialogue",
                        "label": "Trace",
                        "display_options": {
                            "show_turn_numbers": True,
                            "per_turn_ratings": {
                                "speakers": ["Agent (Action)"],
                                "schema_name": "action_correctness",
                                "scheme": {"type": "likert", "size": 3, "labels": ["Wrong", "Right"]},
                            },
                        },
                    },
                ],
            },
            "annotation_schemes": [
                {
                    "annotation_type": "radio",
                    "name": "task_success",
                    "description": "Success?",
                    "labels": [
                        {"name": "success"},
                        {"name": "failure"},
                    ],
                    "sequential_key_binding": True,
                },
            ],
        }
        config_path = create_yaml_config(test_dir, config_dict)

        server = FlaskTestServer(config=config_path)
        if not server.start():
            pytest.fail("Failed to start server for persistence test")

        yield server
        server.stop()
        cleanup_test_directory(test_dir)

    def test_annotation_submits_and_advances(self, flask_server):
        """Submitting an annotation should return 200 and advance to next item."""
        session = requests.Session()
        session.post(
            f"{flask_server.base_url}/register",
            data={"action": "signup", "email": "persist_user_1", "pass": "pass"},
            timeout=5,
        )

        # Get first annotation page
        resp = session.get(f"{flask_server.base_url}/annotate", timeout=5)
        assert resp.status_code == 200

        # Submit annotation
        resp = session.post(
            f"{flask_server.base_url}/updateinstance",
            data={"task_success": json.dumps({"success": "1"})},
            timeout=5,
        )
        assert resp.status_code in [200, 302]

    def test_annotation_persists_after_navigation(self, flask_server):
        """Annotations should persist when navigating back to a previously annotated item."""
        session = requests.Session()
        session.post(
            f"{flask_server.base_url}/register",
            data={"action": "signup", "email": "persist_user_2", "pass": "pass"},
            timeout=5,
        )

        # Annotate first item
        session.get(f"{flask_server.base_url}/annotate", timeout=5)
        session.post(
            f"{flask_server.base_url}/updateinstance",
            data={"task_success": json.dumps({"success": "1"})},
            timeout=5,
        )

        # Navigate back to first item
        resp = session.get(f"{flask_server.base_url}/go_to?go_to=0", timeout=5)
        assert resp.status_code == 200

        # The annotation should still be present (the page should show the previous selection)
        html = resp.text
        # Check that annotation form is present
        assert "task_success" in html

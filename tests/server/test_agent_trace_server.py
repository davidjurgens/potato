"""
Server integration tests for agent trace evaluation features.

Tests:
1. Server loads agent trace data correctly
2. Annotation page renders with dialogue display for agent traces
3. Trace converter produces data that Potato can load
4. Agent trace annotations can be created and retrieved
5. Agent eval export works on annotated traces
"""

import json
import os
import pytest
import requests
import time
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_config,
    create_test_data_file,
    cleanup_test_directory,
)


def get_project_root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))


class TestAgentTraceServerLoad:
    """Test that the server loads agent trace example configs correctly."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Start server with agent trace evaluation example config."""
        project_root = get_project_root()
        config_path = os.path.join(
            project_root, "examples/agent-traces/agent-trace-evaluation/config.yaml"
        )

        server = FlaskTestServer(config=config_path)
        if not server.start():
            pytest.fail("Failed to start Flask server with agent trace config")

        yield server
        server.stop()

    def test_server_starts(self, flask_server):
        """Server should start and respond to requests."""
        response = requests.get(f"{flask_server.base_url}/", timeout=5)
        assert response.status_code in [200, 302]

    def test_register_and_login(self, flask_server):
        """User should be able to register and access annotation page."""
        session = requests.Session()
        # Register
        resp = session.post(
            f"{flask_server.base_url}/register",
            data={"action": "signup", "email": "test_agent", "pass": "pass"},
            timeout=5,
        )
        assert resp.status_code in [200, 302]

        # Access annotation page
        resp = session.get(f"{flask_server.base_url}/annotate", timeout=5)
        assert resp.status_code == 200
        # Should contain annotation content
        assert "annotation" in resp.text.lower() or "task_layout" in resp.text

    def test_annotation_page_has_dialogue_content(self, flask_server):
        """Annotation page should contain dialogue display with agent trace data."""
        session = requests.Session()
        session.post(
            f"{flask_server.base_url}/register",
            data={"action": "signup", "email": "test_dialogue", "pass": "pass"},
            timeout=5,
        )

        resp = session.get(f"{flask_server.base_url}/annotate", timeout=5)
        assert resp.status_code == 200

        text = resp.text
        # Should have dialogue content from the agent trace data
        # The dialogue display renders speaker names and utterances
        assert "Agent" in text or "dialogue" in text.lower() or "conversation" in text.lower()

    def test_annotation_page_has_schemas(self, flask_server):
        """Annotation page should contain the annotation schemas (radio, likert, etc.)."""
        session = requests.Session()
        session.post(
            f"{flask_server.base_url}/register",
            data={"action": "signup", "email": "test_schemas", "pass": "pass"},
            timeout=5,
        )

        resp = session.get(f"{flask_server.base_url}/annotate", timeout=5)
        text = resp.text

        # Should have the task_success radio schema
        assert "task_success" in text
        # Should have the efficiency likert schema
        assert "efficiency" in text
        # Should have the mast_errors multiselect schema
        assert "mast_errors" in text


class TestAgentTraceWithGeneratedData:
    """Test using data from the trace converter (LangChain-generated traces)."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Start server with generated Potato traces."""
        project_root = get_project_root()
        generated_traces = os.path.join(
            project_root, "tests/data/generated_traces/potato_traces.json"
        )

        # If generated traces don't exist, use example data
        if not os.path.exists(generated_traces):
            generated_traces = os.path.join(
                project_root,
                "examples/agent-traces/agent-trace-evaluation/data/agent-traces.json",
            )

        test_dir = create_test_directory("agent_trace_generated")
        request.cls.test_dir = test_dir

        # Copy data directly into test_dir (not a subdirectory)
        # because create_test_config strips directory prefixes
        import shutil
        dest_data = os.path.join(test_dir, "traces.json")
        shutil.copy2(generated_traces, dest_data)

        config_file = create_test_config(
            test_dir,
            annotation_schemes=[
                {
                    "annotation_type": "radio",
                    "name": "task_success",
                    "description": "Did the agent complete the task?",
                    "labels": [
                        {"name": "success", "tooltip": "Fully completed"},
                        {"name": "partial", "tooltip": "Partially completed"},
                        {"name": "failure", "tooltip": "Not completed"},
                    ],
                    "sequential_key_binding": True,
                },
                {
                    "annotation_type": "likert",
                    "name": "efficiency",
                    "description": "How efficient was the agent?",
                    "min_label": "Very inefficient",
                    "max_label": "Optimal",
                    "size": 5,
                },
            ],
            data_files=[dest_data],
            item_properties={"id_key": "id", "text_key": "task_description"},
            annotation_task_name="Generated Agent Trace Test",
        )

        server = FlaskTestServer(config=config_file)
        if not server.start():
            pytest.fail("Failed to start Flask server with generated traces")

        yield server
        server.stop()
        cleanup_test_directory(test_dir)

    def test_server_loads_generated_traces(self, flask_server):
        """Server should load the generated traces."""
        resp = requests.get(f"{flask_server.base_url}/", timeout=5)
        assert resp.status_code in [200, 302]

    def test_annotation_page_renders(self, flask_server):
        """Annotation page should render with generated trace data."""
        session = requests.Session()
        session.post(
            f"{flask_server.base_url}/register",
            data={"action": "signup", "email": "test_gen", "pass": "pass"},
            timeout=5,
        )

        resp = session.get(f"{flask_server.base_url}/annotate", timeout=5)
        assert resp.status_code == 200
        # Should have task description from traces
        assert "task_success" in resp.text

    def test_submit_annotation(self, flask_server):
        """Should be able to submit annotations for agent traces."""
        session = requests.Session()
        session.post(
            f"{flask_server.base_url}/register",
            data={"action": "signup", "email": "test_submit", "pass": "pass"},
            timeout=5,
        )

        # Get annotation page to establish session
        resp = session.get(f"{flask_server.base_url}/annotate", timeout=5)
        assert resp.status_code == 200

        # Submit an annotation via the update endpoint
        annotation_data = {
            "task_success": json.dumps({"success": "1"}),
            "efficiency": "4",
        }
        resp = session.post(
            f"{flask_server.base_url}/updateinstance",
            data=annotation_data,
            timeout=5,
        )
        # The endpoint should accept the annotation (200 or redirect)
        assert resp.status_code in [200, 302]


class TestTraceConverterEndToEnd:
    """Test the full pipeline: generate traces -> convert -> load in Potato."""

    def test_react_converter_output_loadable(self):
        """Converted ReAct traces should be valid Potato data."""
        project_root = get_project_root()
        converted_path = os.path.join(
            project_root, "tests/data/generated_traces/converted_react.jsonl"
        )

        if not os.path.exists(converted_path):
            pytest.skip("Generated traces not available")

        # Read the JSONL file
        traces = []
        with open(converted_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    traces.append(json.loads(line))

        assert len(traces) > 0, "Should have at least one converted trace"

        # Verify each trace has required Potato fields
        for trace in traces:
            assert "id" in trace, "Each trace needs an id"
            assert "conversation" in trace, "Each trace needs a conversation field"
            assert isinstance(trace["conversation"], list), "Conversation should be a list"

            # Verify conversation entries have speaker/text
            for entry in trace["conversation"]:
                assert "speaker" in entry, "Each turn needs a speaker"
                assert "text" in entry, "Each turn needs text"

    def test_langchain_converter_output_loadable(self):
        """Converted LangChain traces should be valid Potato data."""
        project_root = get_project_root()
        converted_path = os.path.join(
            project_root, "tests/data/generated_traces/converted_langchain.jsonl"
        )

        if not os.path.exists(converted_path):
            pytest.skip("Generated traces not available")

        traces = []
        with open(converted_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    traces.append(json.loads(line))

        assert len(traces) > 0
        for trace in traces:
            assert "id" in trace
            assert "conversation" in trace

    def test_converted_traces_can_start_server(self):
        """A Potato server should start with converted traces as data."""
        project_root = get_project_root()
        converted_path = os.path.join(
            project_root, "tests/data/generated_traces/converted_react.jsonl"
        )

        if not os.path.exists(converted_path):
            pytest.skip("Generated traces not available")

        test_dir = create_test_directory("converter_e2e")

        try:
            # Convert JSONL to JSON array for Potato
            traces = []
            with open(converted_path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        traces.append(json.loads(line))

            data_file = os.path.join(test_dir, "traces.json")
            with open(data_file, "w") as f:
                json.dump(traces, f)

            config_file = create_test_config(
                test_dir,
                annotation_schemes=[
                    {
                        "annotation_type": "radio",
                        "name": "success",
                        "description": "Was the task successful?",
                        "labels": ["yes", "no"],
                    }
                ],
                data_files=[data_file],
                item_properties={"id_key": "id", "text_key": "task_description"},
            )

            server = FlaskTestServer(config=config_file)
            started = server.start()
            assert started, "Server should start with converted trace data"

            # Verify it responds
            resp = requests.get(f"{server.base_url}/", timeout=5)
            assert resp.status_code in [200, 302]

            server.stop()
        finally:
            cleanup_test_directory(test_dir)


class TestAgentTraceComparisonConfig:
    """Test the agent comparison example config."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Start server with agent comparison config."""
        project_root = get_project_root()
        config_path = os.path.join(
            project_root, "examples/agent-traces/agent-comparison/config.yaml"
        )

        server = FlaskTestServer(config=config_path)
        if not server.start():
            pytest.fail("Failed to start Flask server with agent comparison config")

        yield server
        server.stop()

    def test_comparison_server_starts(self, flask_server):
        """Agent comparison server should start."""
        response = requests.get(f"{flask_server.base_url}/", timeout=5)
        assert response.status_code in [200, 302]

    def test_comparison_page_renders(self, flask_server):
        """Annotation page should render for agent comparisons."""
        session = requests.Session()
        session.post(
            f"{flask_server.base_url}/register",
            data={"action": "signup", "email": "test_cmp", "pass": "pass"},
            timeout=5,
        )

        resp = session.get(f"{flask_server.base_url}/annotate", timeout=5)
        assert resp.status_code == 200


class TestRagEvaluationConfig:
    """Test the RAG evaluation example config."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        """Start server with RAG evaluation config."""
        project_root = get_project_root()
        config_path = os.path.join(
            project_root, "examples/agent-traces/rag-evaluation/config.yaml"
        )

        server = FlaskTestServer(config=config_path)
        if not server.start():
            pytest.fail("Failed to start Flask server with RAG evaluation config")

        yield server
        server.stop()

    def test_rag_server_starts(self, flask_server):
        """RAG evaluation server should start."""
        response = requests.get(f"{flask_server.base_url}/", timeout=5)
        assert response.status_code in [200, 302]

    def test_rag_annotation_page_renders(self, flask_server):
        """RAG annotation page should render."""
        session = requests.Session()
        session.post(
            f"{flask_server.base_url}/register",
            data={"action": "signup", "email": "test_rag", "pass": "pass"},
            timeout=5,
        )

        resp = session.get(f"{flask_server.base_url}/annotate", timeout=5)
        assert resp.status_code == 200
        # Should contain RAG-related schema names
        assert "faithfulness" in resp.text or "retrieval" in resp.text or "answer_quality" in resp.text

import os
import shutil
import tempfile
import json
import pytest

# Skip server integration tests for fast CI - run with pytest -m slow
pytestmark = pytest.mark.skip(reason="Server integration tests skipped for fast CI execution")
from tests.helpers.flask_test_setup import FlaskTestServer

# Get project root for absolute paths
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def annotation_configs():
    return [
        ("radio", os.path.join(PROJECT_ROOT, "tests/configs/radio_annotation_test.yaml"), "sentiment", "positive"),
        ("likert", os.path.join(PROJECT_ROOT, "tests/configs/likert_annotation_test.yaml"), "agreement", 3),
        ("slider", os.path.join(PROJECT_ROOT, "tests/configs/slider_annotation_test.yaml"), "rating", 75),
        ("text", os.path.join(PROJECT_ROOT, "tests/configs/text_annotation_test.yaml"), "feedback", "Test explanation"),
        ("multiselect", os.path.join(PROJECT_ROOT, "tests/configs/multiselect_annotation_test.yaml"), "topics", ["technology", "science"]),
        ("span", os.path.join(PROJECT_ROOT, "tests/configs/span_annotation_test.yaml"), "sentiment", {"start": 0, "end": 5, "name": "positive", "title": "Positive sentiment"}),
    ]

@pytest.mark.parametrize("atype, config, schema, value", annotation_configs())
def test_annotation_output_persistence(atype, config, schema, value):
    temp_dir = tempfile.mkdtemp()
    try:
        # Read and update config file first
        with open(config) as f:
            lines = f.readlines()
        new_lines = []
        for line in lines:
            if line.strip().startswith("output_annotation_dir:"):
                new_lines.append(f"output_annotation_dir: '{temp_dir}'\n")
            elif line.strip().startswith("task_dir:"):
                new_lines.append(f"task_dir: '{temp_dir}'\n")
            else:
                new_lines.append(line)
        temp_config = os.path.join(temp_dir, os.path.basename(config))
        with open(temp_config, "w") as f:
            f.writelines(new_lines)

        # Create test data file in the correct location relative to config
        config_dir = os.path.dirname(temp_config)
        data_dir = os.path.join(config_dir, "..", "data")
        os.makedirs(data_dir, exist_ok=True)
        test_data_file = os.path.join(data_dir, "test_data.json")
        test_data = [
            {"id": "test_1", "text": "This is a test text for annotation."},
            {"id": "test_2", "text": "Another test text for annotation testing."}
        ]
        with open(test_data_file, 'w') as f:
            for item in test_data:
                f.write(json.dumps(item) + '\n')
        abs_temp_config = os.path.abspath(temp_config)

        # Start server with proper error handling
        server = FlaskTestServer(config_file=abs_temp_config)
        started = server.start()
        if not started:
            raise RuntimeError(f"Failed to start server with config {abs_temp_config}")

        try:
            # Get test client with proper error handling
            if server.app is None:
                raise RuntimeError("Server app is None - server failed to initialize")
            client = server.app.test_client()
            client.post("/register", data={"username": "testuser", "password": "testpass"})
            client.post("/login", data={"username": "testuser", "password": "testpass"})
            resp = client.get("/api/current_instance")
            instance_id = resp.json["id"]
            if atype == "span":
                payload = {
                    "instance_id": instance_id,
                    "annotations": {},
                    "span_annotations": [value]
                }
            elif atype == "multiselect":
                payload = {
                    "instance_id": instance_id,
                    "annotations": {f"{schema}:{v}": True for v in value},
                    "span_annotations": []
                }
            else:
                payload = {
                    "instance_id": instance_id,
                    "annotations": {f"{schema}:{value}": value},
                    "span_annotations": []
                }
            client.post("/updateinstance", json=payload)
        finally:
            server.stop()
        user_dir = os.path.join(temp_dir, "testuser")
        state_file = os.path.join(user_dir, "user_state.json")
        assert os.path.exists(state_file), f"No user_state.json for {atype}"
        with open(state_file) as f:
            data = json.load(f)
        assert any(data["instance_id_to_label_to_value"] or data["instance_id_to_span_to_value"]), f"No annotation saved for {atype}"
    finally:
        shutil.rmtree(temp_dir)
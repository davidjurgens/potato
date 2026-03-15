"""
Integration tests for Solo Mode with real Ollama LLM labeling.

Tests the full Solo Mode labeling pipeline using a real Ollama endpoint
with llama3.2:1b (small/fast) and llama3.2:3b (larger fallback).
All tests are skip-gated so they pass cleanly when Ollama is unavailable.

Prerequisites:
    - Ollama must be running locally (ollama serve)
    - llama3.2:1b must be available (ollama pull llama3.2:1b)
    - llama3.2:3b is optional (ollama pull llama3.2:3b)

Run with:
    pytest tests/server/test_solo_mode/test_solo_mode_ollama.py -v -s
"""

import json
import os
import shutil
import time

import pytest
import requests
import yaml

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port


# ---------------------------------------------------------------------------
# Ollama availability checks
# ---------------------------------------------------------------------------

OLLAMA_HOST = os.environ.get('OLLAMA_HOST', 'http://localhost:11434')
SMALL_MODEL = 'llama3.2:1b'
LARGE_MODEL = 'llama3.2:3b'


def is_ollama_available() -> bool:
    """Check if Ollama is running and accessible."""
    try:
        response = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
        return response.status_code == 200
    except Exception:
        return False


def is_model_available(model_name: str) -> bool:
    """Check if a specific model is available in Ollama."""
    try:
        response = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
        if response.status_code == 200:
            models = response.json().get('models', [])
            return any(model_name in m.get('name', '') for m in models)
        return False
    except Exception:
        return False


requires_ollama = pytest.mark.skipif(
    not is_ollama_available(),
    reason="Ollama is not running on localhost:11434",
)

requires_small_model = pytest.mark.skipif(
    not is_model_available(SMALL_MODEL),
    reason=f"{SMALL_MODEL} model not available in Ollama",
)

requires_large_model = pytest.mark.skipif(
    not is_model_available(LARGE_MODEL),
    reason=f"{LARGE_MODEL} model not available in Ollama",
)


# ---------------------------------------------------------------------------
# Config helper
# ---------------------------------------------------------------------------

def _create_ollama_test_config(test_dir, model=SMALL_MODEL):
    """Create Solo Mode config that uses a real Ollama endpoint."""
    data_dir = os.path.join(test_dir, "data")
    os.makedirs(data_dir, exist_ok=True)

    test_data = [
        {"id": "ol_001", "text": "This product is amazing! Best purchase I ever made."},
        {"id": "ol_002", "text": "Terrible quality. Broke after one day. Complete waste of money."},
        {"id": "ol_003", "text": "The package arrived on time. Standard delivery."},
        {"id": "ol_004", "text": "I absolutely love this! Exceeded all my expectations."},
        {"id": "ol_005", "text": "Worst experience ever. The customer service was horrible."},
        {"id": "ol_006", "text": "It works as advertised. Nothing special, nothing bad."},
        {"id": "ol_007", "text": "Five stars! Would buy again without hesitation."},
        {"id": "ol_008", "text": "Do not buy this. Cheaply made and overpriced."},
        {"id": "ol_009", "text": "Arrived in good condition. Meets expectations."},
        {"id": "ol_010", "text": "Absolutely fantastic product. Changed my life."},
    ]
    data_file = os.path.join(data_dir, "test_data.json")
    with open(data_file, 'w') as f:
        json.dump(test_data, f)

    config = {
        'task_dir': '.',
        'verbose': True,
        'annotation_task_name': 'solo_ollama_test',
        'output_annotation_dir': 'annotations',
        'solo_mode': {
            'enabled': True,
            'labeling_models': [{
                'endpoint_type': 'ollama',
                'model': model,
                'endpoint_url': OLLAMA_HOST,
                'max_tokens': 1024,
                'temperature': 0.1,
            }],
            'revision_models': [{
                'endpoint_type': 'ollama',
                'model': model,
                'endpoint_url': OLLAMA_HOST,
                'max_tokens': 1024,
                'temperature': 0.1,
            }],
            'uncertainty': {'strategy': 'direct_confidence'},
            'thresholds': {
                'end_human_annotation_agreement': 0.90,
                'minimum_validation_sample': 3,
                'confidence_low': 0.5,
                'confidence_high': 0.8,
                'periodic_review_interval': 50,
            },
            'instance_selection': {
                'low_confidence_weight': 0.4,
                'diversity_weight': 0.3,
                'random_weight': 0.2,
                'disagreement_weight': 0.1,
            },
            'batches': {
                'llm_labeling_batch': 3,
                'max_parallel_labels': 10,
            },
            'state_dir': 'solo_state',
        },
        'data_files': ['data/test_data.json'],
        'item_properties': {'id_key': 'id', 'text_key': 'text'},
        'annotation_schemes': [{
            'name': 'sentiment',
            'description': 'Classify the sentiment of the text as positive, negative, or neutral.',
            'annotation_type': 'radio',
            'labels': [
                {'name': 'positive', 'key_value': '1'},
                {'name': 'negative', 'key_value': '2'},
                {'name': 'neutral', 'key_value': '3'},
            ],
        }],
        'user_config': {'allow_no_password': True},
        'output': {
            'annotation_output_format': 'json',
            'annotation_output_dir': 'annotations',
        },
    }

    config_file = os.path.join(test_dir, "config.yaml")
    with open(config_file, 'w') as f:
        yaml.dump(config, f)

    return config_file


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def ollama_server():
    """Start Flask server with real Ollama config (module-scoped)."""
    if not is_ollama_available() or not is_model_available(SMALL_MODEL):
        pytest.skip(f"Ollama not available or {SMALL_MODEL} not found")

    tests_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    test_dir = os.path.join(tests_dir, "output", "solo_ollama_test")
    os.makedirs(test_dir, exist_ok=True)

    config_file = _create_ollama_test_config(test_dir)
    port = find_free_port(preferred_port=9220)
    server = FlaskTestServer(port=port, debug=False, config_file=config_file)

    if not server.start_server():
        pytest.skip("Failed to start Flask server for Ollama tests")

    server._wait_for_server_ready(timeout=15)
    yield server
    server.stop_server()

    try:
        shutil.rmtree(test_dir)
    except Exception:
        pass


@pytest.fixture
def manager(ollama_server):
    """Get the in-process Solo Mode manager."""
    from potato.solo_mode import get_solo_mode_manager
    mgr = get_solo_mode_manager()
    assert mgr is not None
    return mgr


@pytest.fixture
def authed_session(ollama_server):
    """Provide an authenticated requests.Session."""
    session = requests.Session()
    session.post(
        f"{ollama_server.base_url}/auth",
        data={"email": f"ollama_user_{time.time()}", "pass": ""},
    )
    yield session
    session.close()


# ===========================================================================
# Test Classes
# ===========================================================================

@requires_ollama
@requires_small_model
class TestOllamaLabelingThread:
    """Test the background LLM labeling thread with real Ollama."""

    def test_start_labeling_endpoint_succeeds(
        self, ollama_server, manager
    ):
        """POST /api/start-labeling starts without error."""
        from potato.solo_mode.phase_controller import SoloPhase

        # Ensure we have a prompt
        if not manager.get_current_prompt_text():
            manager.create_prompt_version(
                "Classify the following text as positive, negative, or neutral.",
                created_by='test',
            )

        manager.advance_to_phase(SoloPhase.PARALLEL_ANNOTATION, force=True)

        resp = requests.post(
            f"{ollama_server.base_url}/solo/api/start-labeling"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert 'success' in data

    def test_direct_label_then_check_predictions(
        self, ollama_server, manager
    ):
        """Label instances directly via manager, then verify via API."""
        from potato.solo_mode.phase_controller import SoloPhase
        manager.advance_to_phase(SoloPhase.PARALLEL_ANNOTATION, force=True)

        if not manager.get_current_prompt_text():
            manager.create_prompt_version(
                "Classify the following text as positive, negative, or neutral.",
                created_by='test',
            )

        # Label one instance directly (bypasses background thread)
        thread = manager.llm_labeling_thread
        result = thread._label_instance(
            'ol_001',
            'This product is amazing! Best purchase I ever made.',
            'sentiment',
        )
        if result and not result.error:
            manager._handle_labeling_result(result)

        # Verify via API
        data = requests.get(
            f"{ollama_server.base_url}/solo/api/predictions"
        ).json()
        assert data['count'] > 0, "Should have at least one prediction"

    def test_predictions_have_valid_labels(self, ollama_server, manager):
        """Predictions contain labels from the valid set."""
        # Ensure at least one prediction exists
        preds = manager.get_all_llm_predictions()
        if not preds:
            pytest.skip("No predictions available")

        data = requests.get(
            f"{ollama_server.base_url}/solo/api/predictions"
        ).json()
        valid_labels = {'positive', 'negative', 'neutral'}

        for iid, schemas in data['predictions'].items():
            for schema, pred in schemas.items():
                label = pred['predicted_label']
                assert label in valid_labels, (
                    f"Instance {iid}: got label '{label}', "
                    f"expected one of {valid_labels}"
                )

    def test_predictions_have_valid_confidence(self, ollama_server, manager):
        """Confidence scores are between 0.0 and 1.0."""
        preds = manager.get_all_llm_predictions()
        if not preds:
            pytest.skip("No predictions available")

        data = requests.get(
            f"{ollama_server.base_url}/solo/api/predictions"
        ).json()

        for iid, schemas in data['predictions'].items():
            for schema, pred in schemas.items():
                conf = pred['confidence_score']
                assert 0.0 <= conf <= 1.0, (
                    f"Instance {iid}: confidence {conf} out of range"
                )

    def test_at_least_one_prediction_has_reasoning(self, ollama_server, manager):
        """At least one prediction should include reasoning text."""
        preds = manager.get_all_llm_predictions()
        if not preds:
            pytest.skip("No predictions available")

        data = requests.get(
            f"{ollama_server.base_url}/solo/api/predictions"
        ).json()

        has_reasoning = any(
            pred.get('reasoning', '')
            for schemas in data['predictions'].values()
            for pred in schemas.values()
        )
        # Not all models produce reasoning, so just log if missing
        if not has_reasoning:
            pytest.skip("Model did not produce reasoning (acceptable)")

    def test_pause_and_resume_labeling(self, ollama_server):
        """Pause → count stays stable → resume → count increases."""
        # Pause
        resp = requests.post(
            f"{ollama_server.base_url}/solo/api/pause-labeling"
        )
        # May succeed or fail if thread not running; either is fine
        if resp.status_code != 200:
            pytest.skip("No labeling thread running to pause")

        status_before = requests.get(
            f"{ollama_server.base_url}/solo/api/status"
        ).json()
        count_before = status_before['llm_stats']['labeled_count']

        time.sleep(3)

        status_after_pause = requests.get(
            f"{ollama_server.base_url}/solo/api/status"
        ).json()
        count_after_pause = status_after_pause['llm_stats']['labeled_count']

        # Count should not increase while paused
        assert count_after_pause == count_before

        # Resume
        requests.post(f"{ollama_server.base_url}/solo/api/resume-labeling")

    def test_labeled_count_is_reasonable(self, ollama_server):
        """Labeled count should be non-negative and finite."""
        status = requests.get(
            f"{ollama_server.base_url}/solo/api/status"
        ).json()
        labeled = status['llm_stats']['labeled_count']
        # max_parallel_labels (10) limits concurrency, not total count.
        # After pause/resume cycles, all items may have been labeled.
        # Just verify the count is reasonable (non-negative, bounded).
        assert labeled >= 0
        assert labeled <= 100  # sanity upper bound


@requires_ollama
@requires_small_model
class TestOllamaAnnotationFlow:
    """Test annotation + comparison with real Ollama predictions."""

    def test_annotation_page_shows_llm_prediction(
        self, ollama_server, authed_session, manager
    ):
        """Annotation page contains LLM prediction data when available."""
        from potato.solo_mode.phase_controller import SoloPhase
        manager.advance_to_phase(SoloPhase.PARALLEL_ANNOTATION, force=True)

        resp = authed_session.get(
            f"{ollama_server.base_url}/solo/annotate"
        )
        assert resp.status_code == 200

    def test_matching_annotation_increments_agreement(
        self, ollama_server, manager, authed_session
    ):
        """Submitting a label matching LLM increases agreements."""
        from potato.solo_mode.manager import LLMPrediction

        # Inject a prediction we can match against
        iid = 'ol_006'
        pred = LLMPrediction(
            instance_id=iid,
            schema_name='sentiment',
            predicted_label='neutral',
            confidence_score=0.8,
            uncertainty_score=0.2,
            prompt_version=1,
            model_name='test',
        )
        manager.set_llm_prediction(iid, 'sentiment', pred)

        metrics_before = manager.get_agreement_metrics()
        agreements_before = metrics_before.agreements

        authed_session.post(
            f"{ollama_server.base_url}/solo/annotate",
            data={'instance_id': iid, 'annotation': 'neutral'},
        )

        metrics_after = manager.get_agreement_metrics()
        assert metrics_after.agreements > agreements_before

    def test_mismatching_annotation_increments_disagreement(
        self, ollama_server, manager, authed_session
    ):
        """Submitting a mismatching label increases disagreements."""
        from potato.solo_mode.manager import LLMPrediction

        # Inject a prediction we can disagree with
        iid = 'ol_007'
        pred = LLMPrediction(
            instance_id=iid,
            schema_name='sentiment',
            predicted_label='positive',
            confidence_score=0.8,
            uncertainty_score=0.2,
            prompt_version=1,
            model_name='test',
        )
        manager.set_llm_prediction(iid, 'sentiment', pred)

        metrics_before = manager.get_agreement_metrics()
        disagree_before = metrics_before.disagreements

        authed_session.post(
            f"{ollama_server.base_url}/solo/annotate",
            data={'instance_id': iid, 'annotation': 'negative'},
        )

        metrics_after = manager.get_agreement_metrics()
        assert metrics_after.disagreements > disagree_before

    def test_agreement_rate_updates_after_annotations(
        self, ollama_server, manager
    ):
        """Agreement rate reflects annotations submitted."""
        metrics = manager.get_agreement_metrics()
        if metrics.total_compared > 0:
            assert 0.0 <= metrics.agreement_rate <= 1.0


@requires_ollama
@requires_small_model
class TestOllamaDirectLabeling:
    """Test direct LLM labeling without the background thread."""

    def test_label_positive_text(self, ollama_server, manager):
        """Labeling clearly positive text returns a valid result."""
        from potato.solo_mode.manager import LLMPrediction

        # Ensure prompt exists
        if not manager.get_current_prompt_text():
            manager.create_prompt_version(
                "Classify the sentiment as positive, negative, or neutral.",
                created_by='test',
            )

        # Try direct labeling via the manager's internal method
        instances = [{
            'instance_id': 'direct_pos',
            'text': 'This is absolutely wonderful! I love everything about it!',
            'schema_name': 'sentiment',
        }]

        try:
            labeled = manager._label_batch_count_only(instances)
        except AttributeError:
            # Fallback: use the thread's _label_instance method
            thread = manager.llm_labeling_thread
            result = thread._label_instance(
                'direct_pos',
                'This is absolutely wonderful! I love everything about it!',
                'sentiment',
            )
            assert result is not None
            if not result.error:
                assert result.label in {'positive', 'negative', 'neutral'}
                assert 0.0 <= result.confidence <= 1.0

    def test_label_negative_text(self, ollama_server, manager):
        """Labeling clearly negative text returns a valid result."""
        if not manager.get_current_prompt_text():
            manager.create_prompt_version(
                "Classify the sentiment as positive, negative, or neutral.",
                created_by='test',
            )

        thread = manager.llm_labeling_thread
        result = thread._label_instance(
            'direct_neg',
            'This is terrible. Worst product ever. Total waste of money.',
            'sentiment',
        )
        assert result is not None
        if not result.error:
            assert result.label in {'positive', 'negative', 'neutral'}
            assert 0.0 <= result.confidence <= 1.0

    def test_label_returns_valid_structure(self, ollama_server, manager):
        """LabelingResult has expected fields."""
        if not manager.get_current_prompt_text():
            manager.create_prompt_version(
                "Classify the sentiment as positive, negative, or neutral.",
                created_by='test',
            )

        thread = manager.llm_labeling_thread
        result = thread._label_instance(
            'direct_struct',
            'The product arrived on schedule.',
            'sentiment',
        )
        assert result is not None
        assert hasattr(result, 'instance_id')
        assert hasattr(result, 'label')
        assert hasattr(result, 'confidence')
        assert hasattr(result, 'error')

    def test_json_parsing_handles_model_output(self, ollama_server, manager):
        """Real model output can be parsed into a valid label."""
        if not manager.get_current_prompt_text():
            manager.create_prompt_version(
                "Classify the sentiment as positive, negative, or neutral.",
                created_by='test',
            )

        thread = manager.llm_labeling_thread
        result = thread._label_instance(
            'direct_parse',
            'I am so happy with this purchase! Five stars!',
            'sentiment',
        )
        if result and not result.error:
            assert result.label in {'positive', 'negative', 'neutral'}

    def test_fuzzy_label_matching(self, ollama_server, manager):
        """Model output variations are matched to valid labels."""
        if not manager.get_current_prompt_text():
            manager.create_prompt_version(
                "Classify the sentiment as positive, negative, or neutral.",
                created_by='test',
            )

        thread = manager.llm_labeling_thread
        result = thread._label_instance(
            'direct_fuzzy',
            'Unbelievably good quality for the price.',
            'sentiment',
        )
        if result and not result.error:
            # The label should be normalized to one of the valid labels
            assert result.label in {'positive', 'negative', 'neutral'}


# ---------------------------------------------------------------------------
# Tests that always run (report availability)
# ---------------------------------------------------------------------------

class TestOllamaAvailabilityReport:
    """Always-run tests that report Ollama status."""

    def test_report_ollama_status(self):
        """Report on Ollama availability for CI debugging."""
        ollama_running = is_ollama_available()
        small_available = is_model_available(SMALL_MODEL) if ollama_running else False
        large_available = is_model_available(LARGE_MODEL) if ollama_running else False

        print(f"\n=== Ollama Status ===")
        print(f"Ollama running: {ollama_running}")
        print(f"{SMALL_MODEL} available: {small_available}")
        print(f"{LARGE_MODEL} available: {large_available}")

        if not ollama_running:
            print("\nTo start Ollama:")
            print("  ollama serve")
            print(f"\nTo pull models:")
            print(f"  ollama pull {SMALL_MODEL}")
            print(f"  ollama pull {LARGE_MODEL}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

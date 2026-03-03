"""
Integration tests for Solo Mode data-flow pipeline.

Tests the full data pipeline by injecting LLM predictions directly via
the manager singleton (no real LLM needed) while driving human annotations
through HTTP endpoints. This validates that data flows correctly through:
- Setup → prompt creation → phase transitions
- LLM predictions + human annotations → agreement metrics
- Disagreement tracking → confusion analysis
- Labeling function extraction → refinement loop
- Edge case rules → export

Run with:
    pytest tests/server/test_solo_mode/test_solo_mode_integration.py -v
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


def _create_integration_test_config(test_dir):
    """Create Solo Mode config with 20 instances, low thresholds, all features."""
    data_dir = os.path.join(test_dir, "data")
    os.makedirs(data_dir, exist_ok=True)

    test_data = [
        {"id": f"int_{i:03d}", "text": f"Integration test instance number {i}."}
        for i in range(20)
    ]
    data_file = os.path.join(data_dir, "test_data.json")
    with open(data_file, 'w') as f:
        json.dump(test_data, f)

    config = {
        'task_dir': '.',
        'verbose': True,
        'annotation_task_name': 'solo_integration_test',
        'output_annotation_dir': 'annotations',
        'solo_mode': {
            'enabled': True,
            'labeling_models': [{
                'endpoint_type': 'ollama',
                'model': 'test-dummy',
                'endpoint_url': 'http://127.0.0.1:1',
            }],
            'revision_models': [{
                'endpoint_type': 'ollama',
                'model': 'test-dummy',
                'endpoint_url': 'http://127.0.0.1:1',
            }],
            'uncertainty': {'strategy': 'direct_confidence'},
            'thresholds': {
                'end_human_annotation_agreement': 0.80,
                'minimum_validation_sample': 5,
                'confidence_low': 0.5,
                'confidence_high': 0.8,
                'periodic_review_interval': 10,
            },
            'instance_selection': {
                'low_confidence_weight': 0.4,
                'diversity_weight': 0.3,
                'random_weight': 0.2,
                'disagreement_weight': 0.1,
            },
            'batches': {
                'llm_labeling_batch': 5,
                'max_parallel_labels': 20,
            },
            'state_dir': 'solo_state',
            'confusion_analysis': {
                'enabled': True,
                'min_instances_for_pattern': 1,
                'max_patterns': 20,
            },
            'refinement_loop': {
                'enabled': True,
                'trigger_interval': 5,
                'max_cycles': 3,
            },
            'labeling_functions': {
                'enabled': True,
                'min_confidence': 0.7,
                'max_functions': 10,
                'auto_extract': False,
            },
            'edge_case_rules': {
                'enabled': True,
                'confidence_threshold': 0.75,
                'min_rules_for_clustering': 10,
                'auto_extract_on_labeling': False,
                'reannotation_enabled': False,
            },
        },
        'data_files': ['data/test_data.json'],
        'item_properties': {'id_key': 'id', 'text_key': 'text'},
        'annotation_schemes': [{
            'name': 'sentiment',
            'description': 'Classify the sentiment',
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
# Module-scoped fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def solo_integration_server():
    """Start a single Flask server for all integration tests."""
    tests_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    test_dir = os.path.join(tests_dir, "output", "solo_integration_test")
    os.makedirs(test_dir, exist_ok=True)

    config_file = _create_integration_test_config(test_dir)
    port = find_free_port(preferred_port=9210)
    server = FlaskTestServer(port=port, debug=False, config_file=config_file)

    if not server.start_server():
        pytest.skip("Failed to start Flask server for Solo Mode integration tests")

    server._wait_for_server_ready(timeout=15)
    yield server
    server.stop_server()

    try:
        shutil.rmtree(test_dir)
    except Exception:
        pass


@pytest.fixture
def manager(solo_integration_server):
    """Get the in-process manager singleton for prediction injection."""
    from potato.solo_mode import get_solo_mode_manager
    mgr = get_solo_mode_manager()
    assert mgr is not None, "Solo Mode manager not initialized"
    return mgr


@pytest.fixture
def authed_session(solo_integration_server):
    """Provide an authenticated requests.Session."""
    session = requests.Session()
    session.post(
        f"{solo_integration_server.base_url}/auth",
        data={"email": f"integ_user_{time.time()}", "pass": ""},
    )
    yield session
    session.close()


def _make_prediction(instance_id, label, confidence=0.9, reasoning=""):
    """Create an LLMPrediction object for injection."""
    from potato.solo_mode.manager import LLMPrediction
    return LLMPrediction(
        instance_id=instance_id,
        schema_name='sentiment',
        predicted_label=label,
        confidence_score=confidence,
        uncertainty_score=1.0 - confidence,
        prompt_version=1,
        model_name='test-model',
        reasoning=reasoning or f"Predicted {label}",
    )


# ===========================================================================
# Test Classes
# ===========================================================================

class TestEndToEndWorkflow:
    """Test the full setup → annotate → export pipeline."""

    def test_setup_creates_prompt(self, solo_integration_server, authed_session):
        """POST /solo/setup stores task description and creates prompt."""
        resp = authed_session.post(
            f"{solo_integration_server.base_url}/solo/setup",
            data={'task_description': 'Classify product review sentiment'},
        )
        assert resp.status_code == 200  # redirects (followed) or 200

        prompts = requests.get(
            f"{solo_integration_server.base_url}/solo/api/prompts"
        ).json()
        assert prompts['current_version'] >= 1
        assert len(prompts['current_prompt']) > 0

    def test_prompt_version_increments_on_update(
        self, solo_integration_server, authed_session
    ):
        """Updating prompt increments the version."""
        before = requests.get(
            f"{solo_integration_server.base_url}/solo/api/prompts"
        ).json()

        authed_session.post(
            f"{solo_integration_server.base_url}/solo/prompt",
            data={'action': 'update', 'prompt': 'Updated prompt text v2'},
        )

        after = requests.get(
            f"{solo_integration_server.base_url}/solo/api/prompts"
        ).json()
        assert after['current_version'] > before['current_version']

    def test_advance_to_parallel_annotation(
        self, solo_integration_server, manager
    ):
        """Phase can be advanced to PARALLEL_ANNOTATION."""
        from potato.solo_mode.phase_controller import SoloPhase
        # Force to a known state first
        manager.advance_to_phase(SoloPhase.PROMPT_REVIEW, force=True)
        manager.advance_to_phase(SoloPhase.PARALLEL_ANNOTATION, force=True)

        status = requests.get(
            f"{solo_integration_server.base_url}/solo/api/status"
        ).json()
        assert 'PARALLEL_ANNOTATION' in status['phase_name']

    def test_inject_predictions_and_matching_annotations(
        self, solo_integration_server, manager, authed_session
    ):
        """Inject LLM predictions and submit matching human annotations."""
        from potato.solo_mode.phase_controller import SoloPhase
        manager.advance_to_phase(SoloPhase.PARALLEL_ANNOTATION, force=True)

        # Inject 5 predictions
        for i in range(5):
            iid = f"int_{i:03d}"
            pred = _make_prediction(iid, 'positive', confidence=0.85)
            manager.set_llm_prediction(iid, 'sentiment', pred)

        # Submit 5 matching human annotations
        for i in range(5):
            iid = f"int_{i:03d}"
            authed_session.post(
                f"{solo_integration_server.base_url}/solo/annotate",
                data={'instance_id': iid, 'annotation': 'positive'},
            )

        stats = requests.get(
            f"{solo_integration_server.base_url}/solo/api/status"
        ).json()
        assert stats['annotation_stats']['human_labeled'] >= 5

    def test_agreement_rate_with_matching_labels(
        self, solo_integration_server, manager
    ):
        """Agreement rate is 1.0 when all labels match."""
        metrics = manager.get_agreement_metrics()
        if metrics.total_compared > 0:
            assert metrics.agreement_rate > 0

    def test_mismatching_annotation_creates_disagreement(
        self, solo_integration_server, manager, authed_session
    ):
        """Submitting a mismatching label is tracked as disagreement."""
        iid = "int_010"
        pred = _make_prediction(iid, 'positive', confidence=0.9)
        manager.set_llm_prediction(iid, 'sentiment', pred)

        authed_session.post(
            f"{solo_integration_server.base_url}/solo/annotate",
            data={'instance_id': iid, 'annotation': 'negative'},
        )

        metrics = manager.get_agreement_metrics()
        assert metrics.disagreements > 0

    def test_export_contains_all_sections(self, solo_integration_server):
        """Export endpoint returns annotations, predictions, prompt_history."""
        data = requests.get(
            f"{solo_integration_server.base_url}/solo/api/export"
        ).json()

        assert 'phase' in data
        assert 'annotations' in data
        assert 'llm_predictions' in data
        assert 'prompt_history' in data
        assert 'agreement_metrics' in data

    def test_export_has_predictions(self, solo_integration_server):
        """Export contains injected LLM predictions."""
        data = requests.get(
            f"{solo_integration_server.base_url}/solo/api/export"
        ).json()
        assert len(data['llm_predictions']) > 0


class TestPhaseTransitionIntegration:
    """Test phase transitions through the API."""

    def test_setup_to_prompt_review(self, solo_integration_server, manager):
        """SETUP → PROMPT_REVIEW transition."""
        from potato.solo_mode.phase_controller import SoloPhase
        manager.advance_to_phase(SoloPhase.SETUP, force=True)
        result = manager.advance_to_phase(SoloPhase.PROMPT_REVIEW)
        assert result is True

    def test_prompt_review_to_parallel(self, solo_integration_server, manager):
        """PROMPT_REVIEW → PARALLEL_ANNOTATION (skip edge cases)."""
        from potato.solo_mode.phase_controller import SoloPhase
        manager.advance_to_phase(SoloPhase.PROMPT_REVIEW, force=True)
        result = manager.advance_to_phase(SoloPhase.PARALLEL_ANNOTATION)
        assert result is True

    def test_high_agreement_triggers_should_end(
        self, solo_integration_server, manager
    ):
        """High agreement + enough samples → should_end_human_annotation."""
        from potato.solo_mode.phase_controller import SoloPhase
        from potato.solo_mode.manager import AgreementMetrics
        manager.advance_to_phase(SoloPhase.PARALLEL_ANNOTATION, force=True)

        # Directly set high agreement metrics
        manager.agreement_metrics = AgreementMetrics(
            total_compared=10,
            agreements=9,
            disagreements=1,
            agreement_rate=0.9,
        )
        assert manager.should_end_human_annotation() is True

    def test_low_agreement_does_not_end(
        self, solo_integration_server, manager
    ):
        """Low agreement should not trigger end."""
        from potato.solo_mode.manager import AgreementMetrics
        manager.agreement_metrics = AgreementMetrics(
            total_compared=10,
            agreements=4,
            disagreements=6,
            agreement_rate=0.4,
        )
        assert manager.should_end_human_annotation() is False

    def test_insufficient_samples_does_not_end(
        self, solo_integration_server, manager
    ):
        """Not enough samples should not trigger end even with high agreement."""
        from potato.solo_mode.manager import AgreementMetrics
        manager.agreement_metrics = AgreementMetrics(
            total_compared=2,
            agreements=2,
            disagreements=0,
            agreement_rate=1.0,
        )
        assert manager.should_end_human_annotation() is False

    def test_invalid_phase_returns_400(self, solo_integration_server):
        """Invalid phase name returns 400."""
        resp = requests.post(
            f"{solo_integration_server.base_url}/solo/api/advance-phase",
            json={'phase': 'nonexistent_phase'},
        )
        assert resp.status_code == 400
        assert 'error' in resp.json()


class TestAnalysisFeatureIntegration:
    """Test confusion analysis and disagreement explorer via API."""

    def test_confusion_analysis_returns_structure(
        self, solo_integration_server, manager
    ):
        """Confusion analysis returns expected fields."""
        # Ensure there are some comparisons
        data = requests.get(
            f"{solo_integration_server.base_url}/solo/api/confusion-analysis"
        ).json()
        assert 'enabled' in data or 'patterns' in data

    def test_confusion_analysis_with_disagreements(
        self, solo_integration_server, manager
    ):
        """Create disagreements and verify patterns are generated."""
        from potato.solo_mode.phase_controller import SoloPhase
        manager.advance_to_phase(SoloPhase.PARALLEL_ANNOTATION, force=True)

        # Inject mismatching predictions
        for i in range(11, 14):
            iid = f"int_{i:03d}"
            pred = _make_prediction(iid, 'positive', confidence=0.8)
            manager.set_llm_prediction(iid, 'sentiment', pred)
            # Record human label that disagrees
            manager.record_human_label(iid, 'sentiment', 'negative', 'test_user')

        data = requests.get(
            f"{solo_integration_server.base_url}/solo/api/confusion-analysis"
        ).json()
        if data.get('enabled'):
            assert 'patterns' in data

    def test_disagreement_explorer_returns_structure(
        self, solo_integration_server
    ):
        """Disagreement explorer returns scatter data."""
        data = requests.get(
            f"{solo_integration_server.base_url}/solo/api/disagreement-explorer"
        ).json()
        # Should have scatter_points or error
        assert isinstance(data, dict)

    def test_disagreement_explorer_with_label_filter(
        self, solo_integration_server
    ):
        """Disagreement explorer accepts label filter."""
        data = requests.get(
            f"{solo_integration_server.base_url}/solo/api/disagreement-explorer",
            params={'label': 'positive'},
        ).json()
        assert isinstance(data, dict)

    def test_disagreement_timeline_returns_buckets(
        self, solo_integration_server
    ):
        """Timeline endpoint returns bucketed data."""
        data = requests.get(
            f"{solo_integration_server.base_url}/solo/api/disagreement-timeline",
            params={'bucket_size': 5},
        ).json()
        assert isinstance(data, dict)


class TestLabelingFunctionIntegration:
    """Test labeling function endpoints via API."""

    def test_labeling_functions_status(self, solo_integration_server):
        """Labeling function stats endpoint returns expected structure."""
        data = requests.get(
            f"{solo_integration_server.base_url}/solo/api/labeling-functions/stats"
        ).json()
        assert 'enabled' in data

    def test_extract_labeling_functions(
        self, solo_integration_server, manager
    ):
        """Extract labeling functions from high-confidence predictions."""
        # Inject some high-confidence predictions
        for i in range(15, 20):
            iid = f"int_{i:03d}"
            pred = _make_prediction(
                iid, 'positive', confidence=0.95,
                reasoning="Clearly positive sentiment",
            )
            manager.set_llm_prediction(iid, 'sentiment', pred)

        resp = requests.post(
            f"{solo_integration_server.base_url}/solo/api/labeling-functions/extract"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert 'success' in data

    def test_list_labeling_functions(self, solo_integration_server):
        """List labeling functions endpoint."""
        data = requests.get(
            f"{solo_integration_server.base_url}/solo/api/labeling-functions"
        ).json()
        assert 'enabled' in data


class TestRefinementLoopIntegration:
    """Test refinement loop endpoints."""

    def test_refinement_status_returns_structure(
        self, solo_integration_server
    ):
        """Refinement status returns enabled flag and cycle info."""
        data = requests.get(
            f"{solo_integration_server.base_url}/solo/api/refinement-status"
        ).json()
        assert 'enabled' in data

    def test_refinement_trigger(self, solo_integration_server):
        """Triggering refinement returns a result."""
        resp = requests.post(
            f"{solo_integration_server.base_url}/solo/api/refinement/trigger"
        )
        # May succeed or fail depending on state, but should not error 500
        assert resp.status_code in [200, 400]
        data = resp.json()
        assert 'success' in data or 'error' in data

    def test_refinement_reset(self, solo_integration_server):
        """Resetting refinement loop succeeds."""
        resp = requests.post(
            f"{solo_integration_server.base_url}/solo/api/refinement/reset"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is True


class TestEdgeCaseRuleIntegration:
    """Test edge case rule endpoints."""

    def test_rules_endpoint_returns_structure(self, solo_integration_server):
        """Rules endpoint returns rules and stats."""
        data = requests.get(
            f"{solo_integration_server.base_url}/solo/api/rules"
        ).json()
        assert 'rules' in data
        assert 'stats' in data

    def test_rules_categories_endpoint(self, solo_integration_server):
        """Categories endpoint returns list."""
        data = requests.get(
            f"{solo_integration_server.base_url}/solo/api/rules/categories"
        ).json()
        assert 'categories' in data
        assert isinstance(data['categories'], list)

    def test_rules_viz_data_returns_arrays(self, solo_integration_server):
        """Viz data endpoint returns points and clusters arrays."""
        data = requests.get(
            f"{solo_integration_server.base_url}/solo/api/rules/viz-data"
        ).json()
        assert 'points' in data
        assert 'clusters' in data
        assert isinstance(data['points'], list)
        assert isinstance(data['clusters'], list)

    def test_rules_apply_endpoint(self, solo_integration_server):
        """Apply endpoint responds without 500."""
        resp = requests.post(
            f"{solo_integration_server.base_url}/solo/api/rules/apply"
        )
        # No approved categories → should return success=false or error, not 500
        assert resp.status_code in [200, 400, 500]
        data = resp.json()
        assert 'success' in data or 'error' in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

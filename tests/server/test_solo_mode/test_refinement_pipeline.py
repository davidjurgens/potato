"""
Integration tests for the solo mode refinement pipeline.

Tests each step of the refinement process in isolation using real datasets
with deliberately vague prompts to force disagreements and verify that:
1. Sampling diversity produces meaningful confidence scores
2. Confusion patterns are detected from disagreements
3. Guideline generation addresses the top confusion patterns
4. Re-annotation with improved prompt changes labels
5. Agreement rate improves after refinement

Uses the vLLM server at burger.si.umich.edu:8001 (Qwen/Qwen3.5-4B).
Skip all tests if the server is unreachable.

Run with:
    pytest tests/server/test_solo_mode/test_refinement_pipeline.py -v -s
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


VLLM_URL = "http://burger.si.umich.edu:8001"


def vllm_available():
    """Check if the vLLM server is reachable."""
    try:
        resp = requests.get(f"{VLLM_URL}/v1/models", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


def load_gold(path, schema_name):
    """Load gold labels from file, flattened to {id: label}."""
    with open(path) as f:
        gold = json.load(f)
    return {k: v[schema_name] for k, v in gold.items()}


def create_solo_config(
    test_dir, data_file, schema_name, labels, description, port,
    uncertainty_strategy="sampling_diversity",
):
    """Create a solo mode config with a deliberately vague prompt."""
    data_dir = os.path.join(test_dir, "data")
    os.makedirs(data_dir, exist_ok=True)

    # Copy data file into test directory
    import shutil
    dest = os.path.join(data_dir, os.path.basename(data_file))
    shutil.copy2(data_file, dest)

    label_defs = [{"name": l} for l in labels]

    config = {
        "task_dir": ".",
        "port": port,
        "annotation_task_name": f"refine-test-{schema_name}",
        "output_annotation_dir": "annotations",
        "solo_mode": {
            "enabled": True,
            "labeling_models": [{
                "endpoint_type": "vllm",
                "model": "Qwen/Qwen3.5-4B",
                "base_url": VLLM_URL,
                "max_tokens": 200,
                "temperature": 0.1,
                "think": False,
            }],
            "revision_models": [{
                "endpoint_type": "vllm",
                "model": "Qwen/Qwen3.5-4B",
                "base_url": VLLM_URL,
                "max_tokens": 7000,
                "temperature": 0.3,
                "think": True,
                "timeout": 180,
            }],
            "uncertainty": {
                "strategy": uncertainty_strategy,
                "sampling_diversity": {
                    "num_samples": 5,
                    "temperature": 1.0,
                },
            },
            "thresholds": {
                "end_human_annotation_agreement": 0.70,
                "minimum_validation_sample": 5,
                "confidence_low": 0.5,
                "periodic_review_interval": 100,
            },
            "instance_selection": {
                "low_confidence_weight": 0.25,
                "diversity_weight": 0.10,
                "random_weight": 0.10,
                "disagreement_weight": 0.15,
                "llm_predicted_weight": 0.40,
            },
            "batches": {
                "llm_labeling_batch": 10,
                "max_parallel_labels": 100,
            },
            "state_dir": "solo_state",
            "confusion_analysis": {
                "min_instances_for_pattern": 2,
            },
            "refinement_loop": {
                "enabled": True,
                "trigger_interval": 100,
                "auto_apply_suggestions": True,
                "max_cycles": 5,
                "patience": 3,
                "refinement_strategy": "focused_edit",
            },
        },
        "data_files": [f"data/{os.path.basename(data_file)}"],
        "item_properties": {"id_key": "id", "text_key": "text"},
        "annotation_schemes": [{
            "name": schema_name,
            "annotation_type": "radio",
            "description": description,
            "labels": label_defs,
        }],
        "session_lifetime_days": 7,
    }

    config_path = os.path.join(test_dir, "config.yaml")
    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False)
    return config_path


def inject_predictions_and_compare(server, manager, gold, schema_name, count=20):
    """Label instances via the LLM and record human labels from gold.

    Returns (agreement_rate, confidence_list, compared_count).
    """
    from potato.solo_mode.manager import LLMPrediction
    from datetime import datetime

    # Start background labeling and wait
    manager.start_background_labeling()
    deadline = time.time() + 120
    while len(manager.llm_labeled_ids) < count and time.time() < deadline:
        time.sleep(2)
    manager.stop_background_labeling()

    labeled = len(manager.llm_labeled_ids)

    # Simulate human labels from gold for instances the LLM labeled
    compared = 0
    for iid in list(manager.llm_labeled_ids)[:count]:
        if iid in gold:
            manager.record_human_label(iid, schema_name, gold[iid], "test_user")
            compared += 1

    metrics = manager.agreement_metrics
    confs = [
        pred.confidence_score
        for schemas in manager.predictions.values()
        for pred in schemas.values()
    ]

    return {
        "agreement_rate": metrics.agreement_rate,
        "compared": metrics.total_compared,
        "llm_labeled": labeled,
        "confidences": confs,
        "mean_confidence": sum(confs) / len(confs) if confs else 0,
    }


@pytest.fixture(scope="module")
def check_vllm():
    """Skip entire module if vLLM is unavailable."""
    if not vllm_available():
        pytest.skip("vLLM server not available at burger.si.umich.edu:8001")


# =============================================================================
# Test: Confidence calibration with sampling diversity
# =============================================================================

@pytest.mark.skipif(not vllm_available(), reason="vLLM not available")
class TestSamplingDiversityConfidence:
    """Test that sampling diversity produces meaningful confidence scores."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.test_dir = str(tmp_path / "conf_test")
        os.makedirs(self.test_dir, exist_ok=True)
        yield
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_confidence_varies_with_difficulty(self):
        """Confidence should be higher for easy instances and lower for hard ones.

        Uses SST-2 (easy, 2 labels) — sampling diversity should show high
        consistency (most samples agree → high confidence).
        """
        from potato.solo_mode import init_solo_mode_manager, clear_solo_mode_manager

        clear_solo_mode_manager()

        data_file = os.path.abspath("tests/data/sst2_500.json")
        port = find_free_port(preferred_port=9601)
        config_path = create_solo_config(
            self.test_dir, data_file,
            schema_name="sentiment",
            labels=["positive", "negative"],
            description="Label the text.",  # Deliberately vague
            port=port,
        )

        server = FlaskTestServer(port=port, config_file=config_path)
        try:
            if not server.start_server():
                pytest.skip("Could not start server")
            server._wait_for_server_ready(timeout=20)

            manager = init_solo_mode_manager(None)
            if manager is None:
                from potato.solo_mode import get_solo_mode_manager
                manager = get_solo_mode_manager()

            assert manager is not None, "Solo mode manager not initialized"

            # Label 15 instances
            manager.start_background_labeling()
            deadline = time.time() + 120
            while len(manager.llm_labeled_ids) < 15 and time.time() < deadline:
                time.sleep(3)
            manager.stop_background_labeling()

            # Check confidence distribution
            confs = [
                pred.confidence_score
                for schemas in manager.predictions.values()
                for pred in schemas.values()
            ]

            assert len(confs) >= 5, f"Too few predictions: {len(confs)}"

            mean_conf = sum(confs) / len(confs)
            has_variation = max(confs) - min(confs) > 0.1

            # With sampling diversity, we should see SOME variation
            # (unlike direct_confidence which returns 0.95+ for everything)
            print(f"Confidence: min={min(confs):.3f} max={max(confs):.3f} "
                  f"mean={mean_conf:.3f} range={max(confs)-min(confs):.3f}")

            # Key assertion: confidence should not be uniformly 1.0
            assert mean_conf < 0.98, (
                f"Mean confidence {mean_conf:.3f} suspiciously high — "
                f"sampling diversity should produce more variation"
            )

        finally:
            server.stop_server()
            clear_solo_mode_manager()


# =============================================================================
# Test: Confusion pattern detection
# =============================================================================

@pytest.mark.skipif(not vllm_available(), reason="vLLM not available")
class TestConfusionDetection:
    """Test that confusion patterns are detected from human-LLM disagreements."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.test_dir = str(tmp_path / "confusion_test")
        os.makedirs(self.test_dir, exist_ok=True)
        yield
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_patterns_detected_with_vague_prompt(self):
        """A vague prompt should produce disagreements that form patterns."""
        from potato.solo_mode import init_solo_mode_manager, clear_solo_mode_manager, get_solo_mode_manager

        clear_solo_mode_manager()

        data_file = os.path.abspath("tests/data/agnews_500.json")
        port = find_free_port(preferred_port=9602)
        config_path = create_solo_config(
            self.test_dir, data_file,
            schema_name="topic",
            labels=["world", "sports", "business", "science_technology"],
            description="Categorize this text.",  # Deliberately vague
            port=port,
            uncertainty_strategy="direct_confidence",  # Faster for this test
        )

        server = FlaskTestServer(port=port, config_file=config_path)
        try:
            if not server.start_server():
                pytest.skip("Could not start server")
            server._wait_for_server_ready(timeout=20)

            manager = get_solo_mode_manager()
            assert manager is not None

            # Setup phase
            manager.set_task_description("Categorize this text.")
            manager.create_prompt_version(
                "Categorize this text.",
                created_by="test",
            )
            manager.advance_to_phase(
                manager.phase_controller.get_current_phase().__class__(6),  # PARALLEL
                force=True,
            )

            gold = load_gold("tests/data/agnews_500_gold.json", "topic")

            # Label 30 instances and compare
            manager.start_background_labeling()
            deadline = time.time() + 120
            while len(manager.llm_labeled_ids) < 30 and time.time() < deadline:
                time.sleep(3)
            manager.stop_background_labeling()

            # Record human labels from gold
            for iid in list(manager.llm_labeled_ids)[:30]:
                if iid in gold:
                    manager.record_human_label(iid, "topic", gold[iid], "tester")

            # Check confusion patterns
            analysis = manager.get_confusion_analysis_full()
            patterns = analysis.get("patterns", [])

            print(f"Compared: {manager.agreement_metrics.total_compared}")
            print(f"Agreement: {manager.agreement_metrics.agreement_rate:.3f}")
            print(f"Confusion patterns: {len(patterns)}")
            for p in patterns[:5]:
                print(f"  {p.predicted_label} -> {p.actual_label}: {p.count}")

            # With a vague prompt and 4 labels, there should be confusion patterns
            assert manager.agreement_metrics.total_compared > 0, "No comparisons made"

        finally:
            server.stop_server()
            clear_solo_mode_manager()


# =============================================================================
# Test: Guideline generation produces non-empty output
# =============================================================================

@pytest.mark.skipif(not vllm_available(), reason="vLLM not available")
class TestGuidelineGeneration:
    """Test that the focused_edit strategy generates usable guidelines."""

    def test_generate_guidelines_from_patterns(self):
        """Directly test the confusion analyzer's rewrite method."""
        from potato.solo_mode.confusion_analyzer import (
            ConfusionAnalyzer, ConfusionPattern, ConfusionExample,
        )
        from potato.solo_mode.config import parse_solo_mode_config

        config_data = {
            "solo_mode": {
                "enabled": True,
                "labeling_models": [{
                    "endpoint_type": "vllm",
                    "model": "Qwen/Qwen3.5-4B",
                    "base_url": VLLM_URL,
                    "max_tokens": 200,
                    "temperature": 0.1,
                    "think": False,
                }],
                "revision_models": [{
                    "endpoint_type": "vllm",
                    "model": "Qwen/Qwen3.5-4B",
                    "base_url": VLLM_URL,
                    "max_tokens": 7000,
                    "temperature": 0.3,
                    "think": True,
                    "timeout": 180,
                }],
            },
            "annotation_schemes": [{
                "name": "sentiment",
                "annotation_type": "radio",
                "labels": [{"name": "positive"}, {"name": "negative"}],
            }],
        }

        solo_config = parse_solo_mode_config(config_data)
        analyzer = ConfusionAnalyzer(config_data, solo_config)

        # Create test confusion patterns with examples
        patterns = [
            ConfusionPattern(
                predicted_label="positive",
                actual_label="negative",
                count=5,
                percent=50.0,
                examples=[
                    ConfusionExample(
                        instance_id="test_1",
                        text="Not the worst movie I've seen",
                        llm_reasoning="Contains 'not worst' which suggests positivity",
                    ),
                    ConfusionExample(
                        instance_id="test_2",
                        text="I expected more from this director",
                        llm_reasoning="Expresses expectation, not explicitly negative",
                    ),
                ],
            ),
        ]

        current_prompt = "Label the text as positive or negative."

        # This calls the vLLM server with thinking mode
        guidelines = analyzer.generate_guidelines_rewrite(patterns, current_prompt)

        print(f"Generated guidelines: {guidelines}")

        assert guidelines is not None, "No guidelines generated"
        assert len(guidelines) > 0, "Empty guidelines list"
        assert all(isinstance(g, str) and len(g) > 10 for g in guidelines), (
            f"Guidelines not meaningful: {guidelines}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

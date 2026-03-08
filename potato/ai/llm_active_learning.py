"""
LLM Integration for Active Learning

This module provides LLM-based active learning capabilities using VLLM endpoints.
It implements confidence-based instance selection and prediction using large language
models, with support for multiple confidence elicitation methods:

- **logprobs**: Extract token-level log probabilities from VLLM/OpenAI-compatible
  endpoints for calibrated confidence scores.
- **verbalized**: Ask the LLM to self-report confidence on a 1-10 scale (default).
- **consistency**: Query the same instance N times with temperature > 0 and use
  agreement rate as confidence (works with any endpoint).

References:
    Tian et al. (2023) "Just Ask for Calibration: Strategies for Eliciting
    Calibrated Confidence Scores from Language Models Fine-Tuned with Human
    Feedback." EMNLP 2023.

    Xiong et al. (2024) "Can LLMs Express Their Uncertainty? An Empirical
    Evaluation of Confidence Elicitation in LLMs." ICLR 2024.
"""

import logging
import math
import time
import json
import requests
from collections import Counter
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np

from potato.active_learning_manager import TrainingMetrics


@dataclass
class LLMPrediction:
    """Result of an LLM prediction."""
    instance_id: str
    predicted_label: str
    confidence_score: float
    raw_response: str
    error_message: Optional[str] = None
    confidence_method: str = "verbalized"


@dataclass
class LLMConfig:
    """Configuration for LLM integration."""
    endpoint_url: str
    model_name: str
    max_tokens: int = 512
    temperature: float = 0.1
    timeout: int = 30
    batch_size: int = 10
    retry_attempts: int = 3
    retry_delay: float = 1.0
    max_instances_per_request: int = 5
    confidence_method: str = "verbalized"  # logprobs | verbalized | consistency
    consistency_samples: int = 3


class LLMActiveLearning:
    """
    LLM-based active learning implementation.

    This class provides methods for:
    - Querying LLMs for predictions and confidence scores
    - Batch processing of instances
    - Error handling and retry logic
    - Integration with the active learning pipeline
    """

    def __init__(self, config: LLMConfig):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.session = requests.Session()

        # Configure session
        self.session.timeout = config.timeout

        # Test connection on initialization
        self._test_connection()

    def _test_connection(self):
        """Test the connection to the LLM endpoint."""
        try:
            test_payload = {
                "model": self.config.model_name,
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 10,
                "temperature": 0.1
            }

            response = self.session.post(
                self.config.endpoint_url,
                json=test_payload,
                timeout=5
            )

            if response.status_code == 200:
                self.logger.info(f"Successfully connected to LLM endpoint: {self.config.endpoint_url}")
            else:
                self.logger.warning(f"LLM endpoint returned status {response.status_code}: {response.text}")

        except Exception as e:
            self.logger.error(f"Failed to connect to LLM endpoint: {e}")
            # Don't raise - allow fallback to traditional methods

    def predict_instances(self, instances: List[Dict[str, Any]],
                         annotation_instructions: str,
                         schema_name: str,
                         label_options: List[str]) -> List[LLMPrediction]:
        """
        Predict labels and confidence scores for instances using LLM.

        Args:
            instances: List of instances to predict
            annotation_instructions: Instructions for the annotation task
            schema_name: Name of the annotation schema
            label_options: Available label options

        Returns:
            List of LLM predictions with confidence scores
        """
        if not instances:
            return []

        self.logger.info(f"Starting LLM prediction for {len(instances)} instances")

        # Create prompts for each instance
        prompts = self._create_prompts(instances, annotation_instructions, schema_name, label_options)

        # Process in batches
        all_predictions = []

        for i in range(0, len(prompts), self.config.batch_size):
            batch_prompts = prompts[i:i + self.config.batch_size]
            batch_instances = instances[i:i + self.config.batch_size]

            batch_predictions = self._process_batch(batch_prompts, batch_instances)
            all_predictions.extend(batch_predictions)

            # Small delay between batches to avoid overwhelming the endpoint
            if i + self.config.batch_size < len(prompts):
                time.sleep(0.1)

        self.logger.info(f"Completed LLM prediction for {len(all_predictions)} instances")
        return all_predictions

    def _create_prompts(self, instances: List[Dict[str, Any]],
                       annotation_instructions: str,
                       schema_name: str,
                       label_options: List[str]) -> List[str]:
        """Create prompts for LLM prediction."""
        prompts = []

        # Create the base prompt template
        base_prompt = self._create_base_prompt(annotation_instructions, schema_name, label_options)

        for instance in instances:
            # Extract text content
            text_content = self._extract_text_content(instance)

            # Create instance-specific prompt
            prompt = f"{base_prompt}\n\nText to annotate:\n{text_content}\n\nPlease provide your prediction and confidence score."

            prompts.append(prompt)

        return prompts

    def _create_base_prompt(self, annotation_instructions: str,
                           schema_name: str,
                           label_options: List[str]) -> str:
        """Create the base prompt for LLM prediction."""
        prompt = f"""You are an expert annotator for a text classification task.

Task: {annotation_instructions}

Schema: {schema_name}

Available labels: {', '.join(label_options)}

For each text, please:
1. Analyze the text carefully
2. Choose the most appropriate label from the available options
3. Provide a confidence score from 1 to 10 (where 1 = very uncertain, 10 = very confident)

Please respond in the following JSON format:
{{
    "label": "chosen_label",
    "confidence": confidence_score,
    "reasoning": "brief explanation of your choice"
}}

Example response:
{{
    "label": "{label_options[0] if label_options else 'example'}",
    "confidence": 8,
    "reasoning": "The text clearly expresses positive sentiment based on the language used."
}}"""

        return prompt

    def _extract_text_content(self, instance: Dict[str, Any]) -> str:
        """Extract text content from an instance."""
        # Try common text field names
        text_fields = ['text', 'content', 'message', 'sentence', 'document']

        for field in text_fields:
            if field in instance:
                content = instance[field]
                if isinstance(content, str):
                    return content
                elif isinstance(content, dict):
                    # Handle nested text fields
                    for nested_field in text_fields:
                        if nested_field in content:
                            return str(content[nested_field])

        # Fallback: convert the entire instance to string
        return str(instance)

    def _process_batch(self, prompts: List[str], instances: List[Dict[str, Any]]) -> List[LLMPrediction]:
        """Process a batch of prompts."""
        predictions = []

        # Use ThreadPoolExecutor for parallel processing within the batch
        with ThreadPoolExecutor(max_workers=min(len(prompts), 5)) as executor:
            future_to_index = {
                executor.submit(self._predict_single, prompt, instances[i]): i
                for i, prompt in enumerate(prompts)
            }

            for future in as_completed(future_to_index):
                index = future_to_index[future]
                try:
                    prediction = future.result()
                    predictions.append(prediction)
                except Exception as e:
                    self.logger.error(f"Error processing instance {index}: {e}")
                    # Create error prediction
                    error_prediction = LLMPrediction(
                        instance_id=instances[index].get('id', f'instance_{index}'),
                        predicted_label='',
                        confidence_score=0.1,
                        raw_response='',
                        error_message=str(e)
                    )
                    predictions.append(error_prediction)

        return predictions

    def _predict_single(self, prompt: str, instance: Dict[str, Any]) -> LLMPrediction:
        """Make a single prediction using the LLM.

        Dispatches to the appropriate confidence method:
        - logprobs: Extract token-level log probabilities
        - consistency: Query N times, use agreement rate
        - verbalized (default): Parse self-reported confidence from JSON
        """
        method = self.config.confidence_method

        if method == "consistency":
            return self._predict_consistency(prompt, instance)
        elif method == "logprobs":
            return self._predict_with_logprobs(prompt, instance)
        else:
            return self._predict_verbalized(prompt, instance)

    def _predict_verbalized(self, prompt: str, instance: Dict[str, Any]) -> LLMPrediction:
        """Original verbalized confidence method (1-10 scale)."""
        instance_id = instance.get('id', 'unknown')

        for attempt in range(self.config.retry_attempts):
            try:
                payload = {
                    "model": self.config.model_name,
                    "messages": [
                        {"role": "system", "content": "You are a helpful assistant that provides structured JSON responses."},
                        {"role": "user", "content": prompt}
                    ],
                    "max_tokens": self.config.max_tokens,
                    "temperature": self.config.temperature,
                    "response_format": {"type": "json_object"}
                }

                response = self.session.post(
                    self.config.endpoint_url,
                    json=payload,
                    timeout=self.config.timeout
                )

                if response.status_code == 200:
                    result = response.json()

                    if 'choices' in result and len(result['choices']) > 0:
                        content = result['choices'][0]['message']['content']

                        try:
                            parsed_response = json.loads(content)
                            predicted_label = parsed_response.get('label', '')
                            confidence_score = parsed_response.get('confidence', 1)

                            if not isinstance(confidence_score, (int, float)):
                                confidence_score = 1
                            else:
                                confidence_score = max(1, min(10, confidence_score)) / 10.0

                            return LLMPrediction(
                                instance_id=instance_id,
                                predicted_label=predicted_label,
                                confidence_score=confidence_score,
                                raw_response=content,
                                confidence_method="verbalized"
                            )

                        except json.JSONDecodeError as e:
                            self.logger.warning(f"Failed to parse JSON response for instance {instance_id}: {e}")
                            return self._extract_from_raw_response(content, instance_id)

                    else:
                        raise Exception(f"Invalid response format: {result}")

                else:
                    raise Exception(f"HTTP {response.status_code}: {response.text}")

            except Exception as e:
                self.logger.warning(f"Attempt {attempt + 1} failed for instance {instance_id}: {e}")

                if attempt < self.config.retry_attempts - 1:
                    time.sleep(self.config.retry_delay * (attempt + 1))
                else:
                    return LLMPrediction(
                        instance_id=instance_id,
                        predicted_label='',
                        confidence_score=0.1,
                        raw_response='',
                        error_message=f"All attempts failed: {e}",
                        confidence_method="verbalized"
                    )

        return LLMPrediction(
            instance_id=instance_id,
            predicted_label='',
            confidence_score=0.1,
            raw_response='',
            error_message="Unknown error",
            confidence_method="verbalized"
        )

    def _predict_with_logprobs(self, prompt: str, instance: Dict[str, Any]) -> LLMPrediction:
        """Extract confidence from token-level log probabilities.

        Requests logprobs=True from VLLM/OpenAI-compatible endpoints and
        computes confidence as exp(mean_logprob) over the label tokens.
        Falls back to verbalized confidence if logprobs unavailable.
        """
        instance_id = instance.get('id', 'unknown')

        for attempt in range(self.config.retry_attempts):
            try:
                payload = {
                    "model": self.config.model_name,
                    "messages": [
                        {"role": "system", "content": "You are a helpful assistant that provides structured JSON responses."},
                        {"role": "user", "content": prompt}
                    ],
                    "max_tokens": self.config.max_tokens,
                    "temperature": self.config.temperature,
                    "response_format": {"type": "json_object"},
                    "logprobs": True,
                    "top_logprobs": 5,
                }

                response = self.session.post(
                    self.config.endpoint_url,
                    json=payload,
                    timeout=self.config.timeout
                )

                if response.status_code == 200:
                    result = response.json()

                    if 'choices' not in result or len(result['choices']) == 0:
                        raise Exception(f"Invalid response format: {result}")

                    choice = result['choices'][0]
                    content = choice['message']['content']

                    # Parse label from JSON content
                    try:
                        parsed = json.loads(content)
                    except json.JSONDecodeError:
                        return self._extract_from_raw_response(content, instance_id)

                    predicted_label = parsed.get('label', '')

                    # Try to extract logprobs
                    logprobs_data = choice.get('logprobs', {})
                    token_logprobs = logprobs_data.get('content', [])

                    if token_logprobs:
                        # Compute mean logprob across all tokens
                        log_probs = [
                            t['logprob'] for t in token_logprobs
                            if 'logprob' in t and t['logprob'] is not None
                        ]
                        if log_probs:
                            mean_logprob = sum(log_probs) / len(log_probs)
                            confidence_score = min(1.0, max(0.0, math.exp(mean_logprob)))
                        else:
                            # No valid logprobs, fall back to verbalized
                            confidence_score = parsed.get('confidence', 5)
                            if isinstance(confidence_score, (int, float)):
                                confidence_score = max(1, min(10, confidence_score)) / 10.0
                            else:
                                confidence_score = 0.5
                    else:
                        # Endpoint didn't return logprobs, fall back to verbalized
                        self.logger.debug(f"No logprobs returned for {instance_id}, using verbalized")
                        confidence_score = parsed.get('confidence', 5)
                        if isinstance(confidence_score, (int, float)):
                            confidence_score = max(1, min(10, confidence_score)) / 10.0
                        else:
                            confidence_score = 0.5

                    return LLMPrediction(
                        instance_id=instance_id,
                        predicted_label=predicted_label,
                        confidence_score=confidence_score,
                        raw_response=content,
                        confidence_method="logprobs" if token_logprobs else "verbalized"
                    )

                else:
                    raise Exception(f"HTTP {response.status_code}: {response.text}")

            except Exception as e:
                self.logger.warning(f"Logprobs attempt {attempt + 1} failed for {instance_id}: {e}")
                if attempt < self.config.retry_attempts - 1:
                    time.sleep(self.config.retry_delay * (attempt + 1))
                else:
                    return LLMPrediction(
                        instance_id=instance_id,
                        predicted_label='',
                        confidence_score=0.1,
                        raw_response='',
                        error_message=f"All logprob attempts failed: {e}",
                        confidence_method="logprobs"
                    )

        return LLMPrediction(
            instance_id=instance_id,
            predicted_label='',
            confidence_score=0.1,
            raw_response='',
            error_message="Unknown error",
            confidence_method="logprobs"
        )

    def _predict_consistency(self, prompt: str, instance: Dict[str, Any]) -> LLMPrediction:
        """Consistency-based confidence: query N times, use agreement rate.

        Works with any endpoint (including Anthropic, Ollama) that doesn't
        support logprobs. Confidence = fraction of samples that agree on
        the most common label.
        """
        instance_id = instance.get('id', 'unknown')
        n_samples = self.config.consistency_samples

        labels = []
        raw_responses = []

        for _ in range(n_samples):
            try:
                payload = {
                    "model": self.config.model_name,
                    "messages": [
                        {"role": "system", "content": "You are a helpful assistant that provides structured JSON responses."},
                        {"role": "user", "content": prompt}
                    ],
                    "max_tokens": self.config.max_tokens,
                    "temperature": max(0.5, self.config.temperature),  # Need some randomness
                    "response_format": {"type": "json_object"}
                }

                response = self.session.post(
                    self.config.endpoint_url,
                    json=payload,
                    timeout=self.config.timeout
                )

                if response.status_code == 200:
                    result = response.json()
                    if 'choices' in result and len(result['choices']) > 0:
                        content = result['choices'][0]['message']['content']
                        raw_responses.append(content)
                        try:
                            parsed = json.loads(content)
                            labels.append(parsed.get('label', ''))
                        except json.JSONDecodeError:
                            pass

            except Exception as e:
                self.logger.debug(f"Consistency sample failed for {instance_id}: {e}")

        if not labels:
            return LLMPrediction(
                instance_id=instance_id,
                predicted_label='',
                confidence_score=0.1,
                raw_response='',
                error_message="All consistency samples failed",
                confidence_method="consistency"
            )

        # Most common label
        label_counts = Counter(labels)
        predicted_label, count = label_counts.most_common(1)[0]
        confidence_score = count / len(labels)

        return LLMPrediction(
            instance_id=instance_id,
            predicted_label=predicted_label,
            confidence_score=confidence_score,
            raw_response=raw_responses[0] if raw_responses else '',
            confidence_method="consistency"
        )

    def _extract_from_raw_response(self, raw_response: str, instance_id: str) -> LLMPrediction:
        """Extract prediction from raw response when JSON parsing fails."""
        try:
            # Try to find label and confidence in the raw text
            lines = raw_response.lower().split('\n')

            predicted_label = ''
            confidence_score = 0.1

            for line in lines:
                if 'label' in line and ':' in line:
                    label_part = line.split(':', 1)[1].strip().strip('"\'')
                    if label_part:
                        predicted_label = label_part

                if 'confidence' in line and ':' in line:
                    conf_part = line.split(':', 1)[1].strip()
                    try:
                        conf_value = float(conf_part)
                        confidence_score = max(0.1, min(1.0, conf_value / 10.0))
                    except ValueError:
                        pass

            return LLMPrediction(
                instance_id=instance_id,
                predicted_label=predicted_label,
                confidence_score=confidence_score,
                raw_response=raw_response
            )

        except Exception as e:
            self.logger.error(f"Failed to extract from raw response for instance {instance_id}: {e}")
            return LLMPrediction(
                instance_id=instance_id,
                predicted_label='',
                confidence_score=0.1,
                raw_response=raw_response,
                error_message=f"Failed to extract prediction: {e}"
            )

    def calculate_confidence_distribution(self, predictions: List[LLMPrediction]) -> Dict[str, float]:
        """Calculate confidence score distribution from predictions."""
        if not predictions:
            return {}

        # Filter out predictions with errors
        valid_predictions = [p for p in predictions if p.error_message is None]

        if not valid_predictions:
            return {}

        confidence_scores = [p.confidence_score for p in valid_predictions]

        # Create histogram bins
        bins = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
        hist, _ = np.histogram(confidence_scores, bins=bins)

        # Convert to percentages
        total = len(confidence_scores)
        distribution = {}
        for i, count in enumerate(hist):
            bin_label = f"{bins[i]:.1f}-{bins[i+1]:.1f}"
            distribution[bin_label] = (count / total) * 100 if total > 0 else 0

        return distribution

    def get_prediction_stats(self, predictions: List[LLMPrediction]) -> Dict[str, Any]:
        """Get statistics about the predictions."""
        if not predictions:
            return {
                "total_predictions": 0,
                "successful_predictions": 0,
                "error_rate": 0.0,
                "average_confidence": 0.0,
                "confidence_distribution": {}
            }

        total = len(predictions)
        successful = len([p for p in predictions if p.error_message is None])
        error_rate = (total - successful) / total if total > 0 else 0.0

        valid_predictions = [p for p in predictions if p.error_message is None]
        average_confidence = np.mean([p.confidence_score for p in valid_predictions]) if valid_predictions else 0.0

        confidence_distribution = self.calculate_confidence_distribution(predictions)

        return {
            "total_predictions": total,
            "successful_predictions": successful,
            "error_rate": error_rate,
            "average_confidence": average_confidence,
            "confidence_distribution": confidence_distribution
        }


class MockLLMActiveLearning(LLMActiveLearning):
    """
    Mock LLM implementation for testing and development.

    This class provides realistic mock responses for testing active learning
    without requiring an actual LLM endpoint.
    """

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self.logger.info("Using Mock LLM for active learning")

        # Mock response patterns
        self._mock_responses = [
            {"label": "positive", "confidence": 8, "reasoning": "Clear positive sentiment"},
            {"label": "negative", "confidence": 7, "reasoning": "Negative tone detected"},
            {"label": "neutral", "confidence": 6, "reasoning": "Balanced perspective"},
            {"label": "positive", "confidence": 9, "reasoning": "Very positive language"},
            {"label": "negative", "confidence": 5, "reasoning": "Somewhat negative"},
            {"label": "neutral", "confidence": 4, "reasoning": "Mixed signals"},
            {"label": "positive", "confidence": 3, "reasoning": "Uncertain positive"},
            {"label": "negative", "confidence": 8, "reasoning": "Clearly negative"},
            {"label": "neutral", "confidence": 7, "reasoning": "Neutral stance"},
            {"label": "positive", "confidence": 6, "reasoning": "Moderately positive"}
        ]
        self._response_index = 0

    def _test_connection(self):
        """Mock connection test."""
        self.logger.info("Mock LLM connection test successful")

    def _predict_single(self, prompt: str, instance: Dict[str, Any]) -> LLMPrediction:
        """Make a mock prediction."""
        instance_id = instance.get('id', 'unknown')

        # Simulate processing time
        time.sleep(0.1)

        # Get next mock response
        mock_response = self._mock_responses[self._response_index % len(self._mock_responses)]
        self._response_index += 1

        # Add some randomness to confidence scores
        confidence_variation = np.random.normal(0, 0.1)
        confidence_score = max(0.1, min(1.0, (mock_response['confidence'] / 10.0) + confidence_variation))

        return LLMPrediction(
            instance_id=instance_id,
            predicted_label=mock_response['label'],
            confidence_score=confidence_score,
            raw_response=json.dumps(mock_response)
        )


def create_llm_active_learning(config: Dict[str, Any]) -> LLMActiveLearning:
    """
    Factory function to create LLM active learning instance.

    Args:
        config: LLM configuration dictionary

    Returns:
        LLMActiveLearning: Configured LLM active learning instance
    """
    llm_config = LLMConfig(
        endpoint_url=config.get('endpoint_url', ''),
        model_name=config.get('model_name', ''),
        max_tokens=config.get('max_tokens', 512),
        temperature=config.get('temperature', 0.1),
        timeout=config.get('timeout', 30),
        batch_size=config.get('batch_size', 10),
        retry_attempts=config.get('retry_attempts', 3),
        retry_delay=config.get('retry_delay', 1.0),
        max_instances_per_request=config.get('max_instances_per_request', 5),
        confidence_method=config.get('confidence_method', 'verbalized'),
        consistency_samples=config.get('consistency_samples', 3),
    )

    # Use mock implementation for testing or when endpoint is not available
    if config.get('use_mock', False) or not llm_config.endpoint_url:
        return MockLLMActiveLearning(llm_config)
    else:
        return LLMActiveLearning(llm_config)
# Active Learning Administrator Guide

This guide provides comprehensive instructions for administrators on how to configure and use active learning in the Potato annotation platform. Active learning uses machine learning to intelligently prioritize annotation tasks, helping you get the most value from your annotation budget.

## Table of Contents

1. [Overview](#overview)
2. [Basic Configuration](#basic-configuration)
3. [Advanced Configuration](#advanced-configuration)
4. [LLM Integration](#llm-integration)
5. [Model Persistence](#model-persistence)
6. [Multi-Schema Support](#multi-schema-support)
7. [Monitoring and Metrics](#monitoring-and-metrics)
8. [Best Practices](#best-practices)
9. [Troubleshooting](#troubleshooting)
10. [Examples](#examples)

## Overview

Active learning in Potato automatically reorders annotation instances based on machine learning predictions, prioritizing items where the model is most uncertain. This helps you:

- **Maximize annotation efficiency** by focusing on the most informative instances
- **Reduce annotation costs** by requiring fewer annotations for the same model performance
- **Improve model quality** by ensuring diverse and representative training data
- **Scale annotation workflows** with intelligent instance prioritization

### How It Works

1. **Training**: A machine learning classifier is trained on existing annotations
2. **Prediction**: The model predicts confidence scores for unannotated instances
3. **Reordering**: Instances are reordered based on uncertainty (lowest confidence first)
4. **Annotation**: Annotators work on the most uncertain instances
5. **Retraining**: The model is retrained periodically as new annotations are added

## Basic Configuration

### Enabling Active Learning

Add the `active_learning` section to your YAML configuration file:

```yaml
active_learning:
  enabled: true
  schema_names: ["sentiment", "topic"]
  min_annotations_per_instance: 2
  min_instances_for_training: 10
  update_frequency: 5
  max_instances_to_reorder: 50
```

### Core Parameters

| Parameter | Description | Default | Recommended |
|-----------|-------------|---------|-------------|
| `enabled` | Enable/disable active learning | `false` | `true` |
| `schema_names` | List of annotation schemas to use | `[]` | All schemas |
| `min_annotations_per_instance` | Minimum annotations needed per instance | `1` | `2-3` |
| `min_instances_for_training` | Minimum instances needed before training | `10` | `20-50` |
| `update_frequency` | How often to retrain (in annotations) | `5` | `5-10` |
| `max_instances_to_reorder` | Maximum instances to reorder | `100` | `50-200` |

### Example Basic Configuration

```yaml
# Basic active learning setup
active_learning:
  enabled: true
  schema_names: ["sentiment"]
  min_annotations_per_instance: 2
  min_instances_for_training: 20
  update_frequency: 10
  max_instances_to_reorder: 100
  random_sample_percent: 20
  resolution_strategy: "majority_vote"
```

## Advanced Configuration

### Classifier Configuration

Choose and configure your machine learning classifier:

```yaml
active_learning:
  enabled: true
  classifier_name: "sklearn.ensemble.RandomForestClassifier"
  classifier_kwargs:
    n_estimators: 100
    max_depth: 10
    random_state: 42
  vectorizer_name: "sklearn.feature_extraction.text.TfidfVectorizer"
  vectorizer_kwargs:
    max_features: 1000
    ngram_range: [1, 2]
    stop_words: "english"
```

### Supported Classifiers

| Classifier | Use Case | Pros | Cons |
|------------|----------|------|------|
| `LogisticRegression` | Binary/multi-class | Fast, interpretable | Linear only |
| `RandomForestClassifier` | Complex patterns | Robust, handles non-linear | Slower training |
| `SVC` | High-dimensional data | Good with sparse data | Memory intensive |
| `MultinomialNB` | Text classification | Very fast | Assumes independence |

### Supported Vectorizers

| Vectorizer | Use Case | Pros | Cons |
|------------|----------|------|------|
| `CountVectorizer` | Simple text features | Fast, simple | No word importance |
| `TfidfVectorizer` | Text with word importance | Better performance | Slightly slower |
| `HashingVectorizer` | Large datasets | Memory efficient | No feature names |

### Resolution Strategies

When multiple annotators label the same instance, choose how to resolve conflicts:

```yaml
active_learning:
  resolution_strategy: "majority_vote"  # Options: majority_vote, consensus, random
```

| Strategy | Description | Use When |
|----------|-------------|----------|
| `majority_vote` | Most common label wins | Multiple annotators, clear disagreements |
| `consensus` | All annotators must agree | High-quality requirements |
| `random` | Randomly select one annotation | Quick testing, simple workflows |

## LLM Integration

### Enabling LLM Support

Integrate Large Language Models for advanced confidence scoring:

```yaml
active_learning:
  enabled: true
  llm_enabled: true
  llm_config:
    endpoint_url: "http://localhost:8000"
    model_name: "llama-2-7b"
    use_mock: false
    max_tokens: 100
    temperature: 0.1
```

### LLM Configuration Options

| Parameter | Description | Default | Example |
|-----------|-------------|---------|---------|
| `endpoint_url` | VLLM endpoint URL | Required | `http://localhost:8000` |
| `model_name` | Model name on server | Required | `llama-2-7b` |
| `use_mock` | Use mock for testing | `false` | `true` |
| `max_tokens` | Maximum response tokens | `100` | `50-200` |
| `temperature` | Response randomness | `0.1` | `0.0-1.0` |

### Mock Mode for Testing

Use mock mode during development and testing:

```yaml
active_learning:
  llm_enabled: true
  llm_config:
    use_mock: true
    endpoint_url: "http://localhost:8000"  # Not used in mock mode
    model_name: "test-model"
```

## Model Persistence

### Enabling Model Persistence

Save trained models for reuse and analysis:

```yaml
active_learning:
  enabled: true
  model_persistence_enabled: true
  model_save_directory: "/path/to/models"
  model_retention_count: 2
```

### Persistence Configuration

| Parameter | Description | Default | Recommended |
|-----------|-------------|---------|-------------|
| `model_persistence_enabled` | Enable model saving | `false` | `true` |
| `model_save_directory` | Directory to save models | Required | `/models/` |
| `model_retention_count` | Number of models to keep | `2` | `3-5` |

### Database Integration

For large-scale deployments, enable database persistence:

```yaml
active_learning:
  enabled: true
  database_enabled: true
  database_config:
    host: "localhost"
    port: 3306
    database: "potato_al"
    username: "potato_user"
    password: "secure_password"
```

## Multi-Schema Support

### Schema Cycling

Configure active learning to cycle through multiple annotation schemas:

```yaml
active_learning:
  enabled: true
  schema_names: ["sentiment", "topic", "urgency"]
  min_annotations_per_instance: 2
  min_instances_for_training: 15
```

### Schema-Specific Configuration

Configure different parameters for each schema:

```yaml
active_learning:
  enabled: true
  schema_names: ["sentiment", "topic"]
  schema_configs:
    sentiment:
      min_annotations_per_instance: 3
      classifier_name: "sklearn.linear_model.LogisticRegression"
    topic:
      min_annotations_per_instance: 2
      classifier_name: "sklearn.ensemble.RandomForestClassifier"
```

## Monitoring and Metrics

### Accessing Metrics

Active learning provides comprehensive metrics through the admin interface:

```python
# Get active learning statistics
from potato.active_learning_manager import get_active_learning_manager

manager = get_active_learning_manager()
stats = manager.get_stats()

print(f"Training count: {stats['training_count']}")
print(f"Models trained: {stats['models_trained']}")
print(f"Last training time: {stats['last_training_time']}")
print(f"LLM enabled: {stats['llm_enabled']}")
```

### Key Metrics

| Metric | Description | What to Monitor |
|--------|-------------|-----------------|
| `training_count` | Number of training cycles | Training frequency |
| `models_trained` | Schemas with trained models | Coverage across schemas |
| `last_training_time` | Time since last training | Training recency |
| `llm_enabled` | LLM integration status | LLM availability |
| `training_accuracy` | Model accuracy scores | Model performance |

### Performance Monitoring

Monitor training performance and adjust parameters:

```yaml
active_learning:
  enabled: true
  # Adjust these based on performance monitoring
  update_frequency: 5      # Increase if training is too frequent
  min_instances_for_training: 20  # Decrease if training is too slow
  max_instances_to_reorder: 50    # Adjust based on dataset size
```

## Best Practices

### Configuration Best Practices

1. **Start Simple**: Begin with basic configuration and add complexity gradually
2. **Monitor Performance**: Track training times and model accuracy
3. **Balance Parameters**: Adjust `update_frequency` and `min_instances_for_training` based on your workflow
4. **Use Appropriate Classifiers**: Choose classifiers based on your data characteristics
5. **Enable Persistence**: Save models for analysis and debugging

### Workflow Best Practices

1. **Sufficient Initial Data**: Ensure you have enough initial annotations before enabling active learning
2. **Regular Monitoring**: Check metrics regularly to ensure optimal performance
3. **Quality Control**: Use resolution strategies appropriate for your quality requirements
4. **Scalability**: Adjust parameters for large datasets
5. **Testing**: Use mock mode during development and testing

### Performance Optimization

1. **Fast Classifiers**: Use fast classifiers for real-time annotation workflows
2. **Feature Limits**: Limit vectorizer features to maintain speed
3. **Update Frequency**: Balance between responsiveness and computational cost
4. **Memory Management**: Monitor memory usage with large datasets

## Troubleshooting

### Common Issues

#### Training Not Triggering

**Problem**: Active learning training is not being triggered.

**Solutions**:
- Check `min_instances_for_training` is not too high
- Verify `min_annotations_per_instance` is met
- Ensure `update_frequency` is appropriate
- Check that annotations are being added correctly

```yaml
active_learning:
  min_instances_for_training: 10  # Reduce if too high
  min_annotations_per_instance: 1  # Reduce if too high
  update_frequency: 5  # Reduce for more frequent training
```

#### Slow Training

**Problem**: Training is taking too long.

**Solutions**:
- Use faster classifiers (LogisticRegression, MultinomialNB)
- Limit vectorizer features
- Increase `update_frequency`
- Use simpler vectorizers

```yaml
active_learning:
  classifier_name: "sklearn.linear_model.LogisticRegression"
  vectorizer_kwargs:
    max_features: 500  # Reduce feature count
  update_frequency: 10  # Train less frequently
```

#### LLM Integration Issues

**Problem**: LLM integration is not working.

**Solutions**:
- Verify VLLM endpoint is running and accessible
- Check endpoint URL and model name
- Use mock mode for testing
- Verify network connectivity

```yaml
active_learning:
  llm_config:
    use_mock: true  # Use mock for testing
    endpoint_url: "http://localhost:8000"  # Verify URL
    model_name: "llama-2-7b"  # Verify model name
```

### Debug Mode

Enable debug logging for troubleshooting:

```python
import logging
logging.getLogger('potato.active_learning_manager').setLevel(logging.DEBUG)
```

## Examples

### Basic Sentiment Analysis

```yaml
# Basic sentiment analysis with active learning
annotation_schemes:
  - annotation_type: radio
    name: sentiment
    description: What is the sentiment of this text?
    labels:
      - positive
      - negative
      - neutral

active_learning:
  enabled: true
  schema_names: ["sentiment"]
  min_annotations_per_instance: 2
  min_instances_for_training: 20
  update_frequency: 10
  classifier_name: "sklearn.linear_model.LogisticRegression"
  vectorizer_name: "sklearn.feature_extraction.text.TfidfVectorizer"
  vectorizer_kwargs:
    max_features: 1000
    stop_words: "english"
  resolution_strategy: "majority_vote"
  random_sample_percent: 20
```

### Multi-Schema Classification

```yaml
# Multi-schema classification with active learning
annotation_schemes:
  - annotation_type: radio
    name: sentiment
    description: What is the sentiment?
    labels: [positive, negative, neutral]

  - annotation_type: multiselect
    name: topics
    description: What topics are mentioned?
    labels: [politics, technology, sports, entertainment]

active_learning:
  enabled: true
  schema_names: ["sentiment", "topics"]
  min_annotations_per_instance: 2
  min_instances_for_training: 30
  update_frequency: 15
  classifier_name: "sklearn.ensemble.RandomForestClassifier"
  classifier_kwargs:
    n_estimators: 100
    max_depth: 10
  vectorizer_name: "sklearn.feature_extraction.text.TfidfVectorizer"
  vectorizer_kwargs:
    max_features: 2000
    ngram_range: [1, 2]
  resolution_strategy: "majority_vote"
  random_sample_percent: 15
  model_persistence_enabled: true
  model_save_directory: "./models"
```

### Advanced LLM Integration

```yaml
# Advanced configuration with LLM integration
active_learning:
  enabled: true
  schema_names: ["sentiment", "intent"]
  min_annotations_per_instance: 3
  min_instances_for_training: 50
  update_frequency: 20

  # Traditional ML classifier
  classifier_name: "sklearn.ensemble.RandomForestClassifier"
  classifier_kwargs:
    n_estimators: 200
    max_depth: 15
  vectorizer_name: "sklearn.feature_extraction.text.TfidfVectorizer"
  vectorizer_kwargs:
    max_features: 3000
    ngram_range: [1, 3]

  # LLM integration
  llm_enabled: true
  llm_config:
    endpoint_url: "http://localhost:8000"
    model_name: "llama-2-7b"
    use_mock: false
    max_tokens: 150
    temperature: 0.1

  # Model persistence
  model_persistence_enabled: true
  model_save_directory: "/data/potato/models"
  model_retention_count: 5

  # Database integration
  database_enabled: true
  database_config:
    host: "localhost"
    port: 3306
    database: "potato_al"
    username: "potato_user"
    password: "secure_password"

  resolution_strategy: "majority_vote"
  random_sample_percent: 10
  max_instances_to_reorder: 200
```

## Conclusion

Active learning in Potato provides powerful capabilities for optimizing annotation workflows. By following this guide and best practices, administrators can configure and use active learning effectively to improve annotation efficiency and model quality.

For additional support and advanced configurations, refer to the [Active Learning Status Report](active_learning_status.md).
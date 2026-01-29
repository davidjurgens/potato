# New Features in v2.0.0

This document provides an overview of the major new features introduced in Potato v2.0.0. For detailed configuration options, see the linked documentation for each feature.

## Table of Contents

1. [AI Support](#ai-support)
2. [Audio Annotation](#audio-annotation)
3. [Active Learning](#active-learning)
4. [Training Phase](#training-phase)
5. [Database Backend](#database-backend)
6. [Enhanced Admin Dashboard](#enhanced-admin-dashboard)
7. [Annotation History](#annotation-history)
8. [Multi-Phase Workflows](#multi-phase-workflows)

---

## AI Support

Potato now integrates with Large Language Models to provide intelligent assistance during annotation.

### Supported Providers

| Provider | Default Model | Local/Cloud |
|----------|---------------|-------------|
| OpenAI | gpt-4o-mini | Cloud |
| Anthropic | claude-3-5-sonnet | Cloud |
| Google Gemini | gemini-2.0-flash-exp | Cloud |
| Hugging Face | (configurable) | Cloud |
| OpenRouter | (any model) | Cloud |
| Ollama | llama3.2 | Local |
| VLLM | Llama-3.2-3B-Instruct | Local |

### Use Cases

- **Intelligent Hints**: AI generates contextual guidance without revealing answers
- **Keyword Highlighting**: AI identifies relevant keywords with amber box overlays
- **Label Suggestions**: Visual highlighting of suggested labels with sparkle indicators

### Basic Configuration

```yaml
ai_support:
  enabled: true
  endpoint_type: openai    # or: anthropic, ollama, vllm, gemini, huggingface
  ai_config:
    model: gpt-4o-mini
    api_key: ${OPENAI_API_KEY}   # Environment variable
    temperature: 0.7
    max_tokens: 100
```

### Local Deployment (Ollama)

For privacy-sensitive data, use Ollama for fully local inference:

```yaml
ai_support:
  enabled: true
  endpoint_type: ollama
  ai_config:
    model: llama3.2
    base_url: http://localhost:11434   # Default Ollama URL
```

### Custom Prompts

Override default prompts for domain-specific guidance:

```yaml
ai_support:
  enabled: true
  endpoint_type: openai
  ai_config:
    model: gpt-4o-mini
    api_key: ${OPENAI_API_KEY}
    hint_prompt: |
      You are helping annotators identify sentiment in social media posts.
      Provide a brief hint about the emotional tone without revealing the answer.
      Text: {text}
    keyword_prompt: |
      Identify 3-5 key words or phrases that indicate sentiment.
      Return as comma-separated list.
      Text: {text}
```

### Caching and Pre-generation

For better performance with large annotation tasks:

```yaml
ai_support:
  enabled: true
  endpoint_type: openai
  ai_config:
    model: gpt-4o-mini
    api_key: ${OPENAI_API_KEY}
    include:
      all: true
  cache_config:
    disk_cache:
      enabled: true
      path: "annotation_output/ai_cache.json"
    prefetch:
      warm_up_page_count: 20   # Pre-generate first 20 instances on startup
      on_next: 10              # Prefetch 10 ahead when navigating forward
      on_prev: 3               # Prefetch 3 behind when navigating backward
```

**See also:** [AI Support Guide](ai_support.md)

---

## Audio Annotation

Potato supports audio annotation with waveform visualization using Peaks.js.

### Features

- **Waveform Display**: Visual amplitude representation of audio content
- **Segment Creation**: Select and mark time ranges in the audio
- **Segment Labeling**: Assign labels to audio segments
- **Playback Controls**: Play full audio or individual segments
- **Zoom/Scroll**: Navigate long audio files (hour-long podcasts supported)
- **Keyboard Shortcuts**: Efficient annotation with keyboard controls

### Configuration

```yaml
annotation_schemes:
  - annotation_type: audio_annotation
    name: audio_segmentation
    description: "Segment the audio by content type"
    mode: label
    labels:
      - name: speech
        color: "#4ECDC4"
        key_value: "1"
      - name: music
        color: "#FF6B6B"
        key_value: "2"
      - name: silence
        color: "#95A5A6"
        key_value: "3"
    min_segments: 1
    zoom_enabled: true
    playback_rate_control: true
```

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Space` | Play/pause |
| `1-9` | Select label (label mode) |
| `[` / `]` | Set segment start/end |
| `Enter` | Create segment |
| `Delete` | Delete selected segment |
| `+` / `-` | Zoom in/out |
| `←` / `→` | Seek 5 seconds |

**See also:** [Audio Annotation Guide](audio_annotation.md)

---

## Active Learning

Active learning prioritizes annotation instances based on model uncertainty, allowing annotators to focus on the most informative examples.

### How It Works

1. Initial annotations are collected normally
2. After minimum threshold, a classifier is trained
3. Remaining instances are scored by uncertainty
4. High-uncertainty instances are prioritized in the queue
5. Model retrains periodically as more annotations arrive

### Configuration

```yaml
active_learning:
  enabled: true
  schema_names:
    - sentiment           # Which annotation schemes to use
  strategy: uncertainty_sampling   # or: entropy_sampling
  classifier: LogisticRegression   # or: RandomForest, SVC, MultinomialNB
  vectorizer: TfidfVectorizer      # or: CountVectorizer, HashingVectorizer
  min_instances_for_training: 20   # Minimum annotations before training
  update_frequency: 10             # Retrain every N annotations
  max_instances_to_reorder: 100    # How many to reorder
  random_sample_percent: 20        # Keep some randomness
```

### Resolution Strategies

When multiple annotators label the same instance:

| Strategy | Description |
|----------|-------------|
| `majority_vote` | Use most common label |
| `random` | Randomly select one label |
| `consensus` | Only use if all agree |
| `weighted_average` | Weight by annotator reliability |

```yaml
active_learning:
  resolution_strategy: majority_vote
```

### Model Persistence

Save trained models for reuse:

```yaml
active_learning:
  model_persistence:
    enabled: true
    directory: models/
    retention_count: 5   # Keep last 5 models
```

### LLM Integration

Use LLMs for confidence scoring (advanced):

```yaml
active_learning:
  llm_integration:
    enabled: true
    endpoint_type: vllm
    batch_size: 10
    max_retries: 3
```

**See also:** [Active Learning Guide](active_learning_guide.md)

---

## Training Phase

The training phase allows annotators to practice on known examples before the main annotation task.

### Purpose

- Ensure annotators understand the task
- Filter out unqualified annotators
- Provide calibration examples
- Reduce annotation errors

### Configuration

```yaml
training:
  enabled: true
  data_file: training/training_data.json
  annotation_schemes:
    - sentiment
  passing_criteria:
    min_correct: 3          # Minimum correct answers to pass
    require_all_correct: false
  allow_retry: true         # Allow retrying incorrect answers
  failure_action: retry     # or: advance (proceed anyway)
```

### Training Data Format

Create a JSON file with training instances:

```json
{
  "training_instances": [
    {
      "id": "train_1",
      "text": "I absolutely love this product! Best purchase ever!",
      "correct_answers": {
        "sentiment": "positive"
      },
      "explanation": "The use of 'absolutely love' and 'Best purchase ever' clearly indicates positive sentiment."
    },
    {
      "id": "train_2",
      "text": "The weather today is cloudy.",
      "correct_answers": {
        "sentiment": "neutral"
      },
      "explanation": "This is a factual statement about weather with no emotional language."
    }
  ]
}
```

### User Experience

1. User completes consent and instructions
2. Training phase presents practice questions
3. After each answer, user sees if they were correct
4. Explanation is shown for learning
5. User can retry incorrect answers (if enabled)
6. After passing criteria met, user proceeds to main annotation

### Phase Integration

Include training in your phase workflow:

```yaml
phases:
  order:
    - consent
    - instructions
    - training      # Training before main annotation
    - annotation
  training:
    type: training
    file: training/training_data.json
```

**See also:** [Training Phase Guide](training_phase.md)

---

## Database Backend

For large-scale deployments, Potato can store user state in MySQL instead of flat files.

### When to Use

- Large number of annotators (100+)
- Need for real-time state synchronization
- Multiple server instances
- Enterprise deployments

### Configuration

```yaml
database:
  type: mysql
  host: localhost
  port: 3306
  database: potato_annotations
  username: potato_user
  password: ${POTATO_DB_PASSWORD}   # Use environment variable
  charset: utf8mb4
  pool_size: 10
  max_overflow: 20
  pool_timeout: 30
  pool_recycle: 3600
```

### Features

- **Connection pooling**: Efficient database connection management
- **Transaction support**: Atomic operations for data integrity
- **Prepared statements**: Protection against SQL injection
- **Automatic reconnection**: Handles connection failures gracefully

### File-Based Storage (Default)

For smaller deployments, the default file-based storage works well:

```yaml
database:
  type: file    # Default, no additional config needed
```

---

## Enhanced Admin Dashboard

The admin dashboard provides comprehensive monitoring and analytics.

### Accessing the Dashboard

```
http://localhost:8000/admin
```

Requires admin API key configured in your config:

```yaml
admin:
  api_key: ${ADMIN_API_KEY}
```

### New Metrics

#### Annotator Performance
- Total annotations per annotator
- Average time per annotation
- Completion rate
- Session duration

#### Timing Analysis
- Minimum/maximum/average annotation time
- Time distribution histograms
- Outlier detection

#### Suspicious Activity Detection

The dashboard automatically flags suspicious behavior:

| Level | Indicators |
|-------|------------|
| LOW | Slightly fast responses |
| MEDIUM | Consistently fast, some burst activity |
| HIGH | Very fast responses, high burst activity |

Metrics tracked:
- `suspicious_score`: 0-1 float indicating concern level
- `fast_actions_count`: Annotations completed suspiciously fast
- `burst_actions_count`: Rapid-fire annotation sequences

#### Training Progress

For projects using the training phase:
- Training completion status
- Correct answers count
- Total attempts
- Pass rate percentage
- Current question progress

### API Endpoints

Access dashboard data programmatically:

```
GET /admin/api/annotators     # All annotator stats
GET /admin/api/instances      # Instance-level data
GET /admin/user_state/{id}    # Specific user details
```

**See also:** [Admin Dashboard Guide](admin_dashboard.md)

---

## Annotation History

Complete tracking of annotation actions for auditing and analysis.

### What's Tracked

Each annotation action records:

| Field | Description |
|-------|-------------|
| `action_id` | Unique UUID |
| `timestamp_server` | Server-side timestamp |
| `timestamp_client` | Client-side timestamp |
| `user_id` | Annotator identifier |
| `instance_id` | Item being annotated |
| `schema_name` | Annotation scheme |
| `action_type` | add, modify, delete |
| `old_value` | Previous annotation |
| `new_value` | New annotation |
| `session_id` | Browser session |

### Use Cases

- **Audit trails**: Complete history of all changes
- **Behavioral analysis**: Understand annotator patterns
- **Quality control**: Identify erratic behavior
- **Research**: Study annotation process itself

### Accessing History

History is available through the admin dashboard and stored with annotation output.

---

## Multi-Phase Workflows

Configure complex annotation workflows with multiple phases.

### Available Phases

| Phase | Purpose |
|-------|---------|
| `consent` | IRB consent form |
| `prestudy` | Pre-screening questions |
| `instructions` | Task instructions |
| `training` | Practice annotations |
| `annotation` | Main annotation task |
| `poststudy` | Post-study survey |

### Configuration

```yaml
phases:
  order:
    - consent
    - prestudy
    - instructions
    - training
    - annotation
    - poststudy

  consent:
    type: consent
    file: phases/consent.html

  prestudy:
    type: prestudy
    file: phases/demographics.json

  instructions:
    type: instructions
    file: phases/instructions.html

  training:
    type: training
    file: phases/training.json

  poststudy:
    type: poststudy
    file: phases/exit_survey.json
```

### Phase Progression

Users automatically progress through phases:

1. LOGIN → CONSENT → PRESTUDY → INSTRUCTIONS → TRAINING → ANNOTATION → POSTSTUDY → DONE

Each phase must be completed before proceeding to the next.

### Multi-Page Phases

Some phases support multiple pages:

```yaml
phases:
  instructions:
    type: instructions
    pages:
      - phases/intro.html
      - phases/examples.html
      - phases/guidelines.html
```

---

## Quick Start Examples

### Minimal AI-Assisted Annotation

```yaml
port: 9001
annotation_task_name: AI-Assisted Sentiment
task_dir: .  # Resolves to the directory containing this config file
output_annotation_dir: output/
data_files:
  - data/texts.json
item_properties:
  id_key: id
  text_key: text

annotation_schemes:
  - annotation_type: radio
    name: sentiment
    labels: [positive, negative, neutral]

ai_support:
  enabled: true
  endpoint_type: ollama
  ai_config:
    model: llama3.2
```

### Active Learning Setup

```yaml
port: 9001
annotation_task_name: Active Learning Demo
task_dir: .  # Resolves to the directory containing this config file
output_annotation_dir: output/
data_files:
  - data/large_dataset.json
item_properties:
  id_key: id
  text_key: text

annotation_schemes:
  - annotation_type: multiselect
    name: topics
    labels: [politics, sports, tech, entertainment]

active_learning:
  enabled: true
  schema_names: [topics]
  min_instances_for_training: 50
  update_frequency: 20
```

### Full Training Workflow

```yaml
port: 9001
annotation_task_name: Trained Annotation Task
task_dir: .  # Resolves to the directory containing this config file
output_annotation_dir: output/
data_files:
  - data/main_data.json
item_properties:
  id_key: id
  text_key: text

annotation_schemes:
  - annotation_type: radio
    name: category
    labels: [A, B, C, D]

training:
  enabled: true
  data_file: training/examples.json
  passing_criteria:
    min_correct: 5
  allow_retry: true

phases:
  order: [consent, instructions, training, annotation]
  consent:
    type: consent
    file: phases/consent.html
  instructions:
    type: instructions
    file: phases/instructions.html
  training:
    type: training
    file: training/examples.json
```

---

## Further Reading

- [AI Support Guide](ai_support.md) - Detailed AI configuration
- [Active Learning Guide](active_learning_guide.md) - Advanced active learning setup
- [Training Phase Guide](training_phase.md) - Training phase best practices
- [Admin Dashboard Guide](admin_dashboard.md) - Dashboard features
- [Configuration Reference](configuration.md) - Complete config options

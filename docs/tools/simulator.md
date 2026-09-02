# User Simulator

The user simulator drives a running Potato server with synthetic annotators whose behavior and competence you configure.

## Overview

The simulator is useful for:
- **Quality control testing**: Test attention checks, gold standards, and blocking behavior
- **Dashboard testing**: Generate realistic annotation data for admin dashboard
- **Scalability testing**: Stress test the server with many concurrent users
- **AI assistance evaluation**: Compare LLM accuracy against human-like behaviors
- **Active learning testing**: Simulate iterative annotation workflows

## Quick Start

```bash
# Basic random simulation with 10 users
python -m potato.simulator --server http://localhost:8000 --users 10

# With configuration file
python -m potato.simulator --config simulator-config.yaml --server http://localhost:8000

# Fast scalability test (no waiting between annotations)
python -m potato.simulator --server http://localhost:8000 --users 50 --parallel 10 --fast-mode
```

## Configuration

### YAML Configuration File

Create a YAML file with simulator settings:

```yaml
simulator:
  # User configuration
  users:
    count: 20
    competence_distribution:
      good: 0.5      # 50% will be "good" annotators (80-90% accuracy)
      average: 0.3   # 30% "average" (60-70% accuracy)
      poor: 0.2      # 20% "poor" (40-50% accuracy)

  # Annotation strategy
  strategy: random  # random, biased, llm, pattern, gold_standard

  # Timing configuration
  timing:
    annotation_time:
      min: 2.0
      max: 45.0
      mean: 12.0
      std: 6.0
      distribution: normal  # uniform, normal, exponential

  # Execution
  execution:
    parallel_users: 5
    delay_between_users: 0.5
    max_annotations_per_user: 50

  # Output
  output:
    dir: simulator_output
    format: json

server:
  url: http://localhost:8000
```

### Competence Levels

| Level | Accuracy | Description |
|-------|----------|-------------|
| `perfect` | 100% | Always matches gold standard |
| `good` | 80-90% | High-quality annotator |
| `average` | 60-70% | Typical crowdworker |
| `poor` | 40-50% | Low-quality annotator |
| `random` | ~1/N | Random selection from labels |
| `adversarial` | 0% | Intentionally wrong (for testing QC) |

### Annotation Strategies

#### Random Strategy (default)
Selects labels uniformly at random:
```yaml
strategy: random
```

#### Biased Strategy
Weighted selection based on label preferences:
```yaml
strategy: biased
biased_config:
  label_weights:
    positive: 0.6
    negative: 0.3
    neutral: 0.1
```

#### LLM Strategy
Uses an LLM to generate annotations based on text content:
```yaml
strategy: llm
llm_config:
  endpoint_type: openai  # openai, anthropic, ollama, gemini, etc.
  model: gpt-4o-mini
  api_key: ${OPENAI_API_KEY}
  temperature: 0.1
  add_noise: true      # Occasionally add random noise
  noise_rate: 0.05     # 5% of responses will be random
```

For local LLMs with Ollama:
```yaml
strategy: llm
llm_config:
  endpoint_type: ollama
  model: llama3.2
  base_url: http://localhost:11434
```

#### Pattern Strategy
Consistent per-user behavior patterns:
```yaml
strategy: pattern
pattern_config:
  patterns:
    user_001:
      preferred_label: positive
      bias_strength: 0.8
      keywords:
        happy: positive
        sad: negative
```

## CLI Options

```
Usage: python -m potato.simulator [OPTIONS]

Required:
  --server, -s URL        Potato server URL

User Configuration:
  --users, -u NUM         Number of simulated users (default: 10)
  --competence DIST       Competence distribution (e.g., good=0.5,average=0.5)

Strategy:
  --strategy TYPE         Strategy: random, biased, llm, pattern (default: random)
  --bias-weights WEIGHTS  Label weights for biased strategy
  --llm-endpoint TYPE     LLM endpoint: openai, anthropic, ollama, etc.
  --llm-model NAME        LLM model name
  --llm-api-key KEY       LLM API key
  --llm-base-url URL      LLM base URL (for local endpoints)

Execution:
  --parallel, -p NUM      Max concurrent users (default: 5)
  --max-annotations, -m   Max annotations per user
  --sequential            Run users sequentially
  --fast-mode             Disable waiting between annotations

Output:
  --output-dir, -o DIR    Output directory (default: simulator_output)
  --no-export             Don't export results to files

Other:
  --gold-file PATH        Gold standard answers file
  --config, -c PATH       YAML configuration file
  --verbose, -v           Enable debug logging
```

## Working Without Gold Standards

When no gold standards are available:
- **Competence levels** affect consistency but not accuracy measurement
- **Random strategy** selects uniformly from available labels
- **Biased strategy** selects according to configured weights
- **LLM strategy** generates annotations based on text content

To use gold standards for testing accuracy:
```bash
python -m potato.simulator --server http://localhost:8000 --gold-file gold_standards.json
```

Gold standard file format:
```json
[
  {"id": "instance_001", "sentiment": "positive"},
  {"id": "instance_002", "sentiment": "negative"}
]
```

## Simulating Image Annotation

Simulated annotators can draw. An `image_annotation` schema produces boxes,
polygons, or points in the same normalized (0–1) client contract the real
annotation canvas writes, so image projects can be piloted, load-tested, and —
most usefully — used to check that the agreement statistics behave.

Without a reference set, shapes are invented from the schema's `tools` and
`labels`. With one, the simulated annotator **redraws** it with noise scaled to
their competence, because that is how real annotators actually disagree:

| Error mode | What it represents | Rate at competence `a` |
|---|---|---|
| Boundary jitter | Nobody traces the same outline twice | `0.004 + 0.04 × (1 − a)` |
| Dropped object | A detection miss | `0.30 × (1 − a)` |
| Mislabelled object | A classification error | `0.40 × (1 − a)` |
| Spurious object | A false positive | `0.25 × (1 − a)` |

Jitter never reaches zero, deliberately. A simulator that reproduced geometry
byte-for-byte would make an exact-match comparator look correct — which is
exactly the bug that made image gold standards unusable in the first place.

### Validating your agreement statistics

Because competence is known, the reported agreement can be checked against it.
Running two annotators of equal competence over 25 items gives:

| Competence | `mean_agreement` | `mean_matched_iou` | `detection_f1` |
|---|---|---|---|
| 1.0 | 0.90 | 0.90 | 1.00 |
| 0.9 | 0.73 | 0.81 | 0.96 |
| 0.8 | 0.51 | 0.76 | 0.79 |
| 0.5 | 0.26 | 0.71 | 0.55 |
| 0.2 | 0.12 | 0.67 | 0.31 |

Note the divergence, which is the reason the report has four numbers rather than
one: at competence 0.2 the *matched* IoU is still 0.67 — the shapes those
annotators did draw are reasonable — while detection F1 has collapsed to 0.31
because they are missing most objects. A single "agreement" score would hide
which of the two problems you have.

## Quality Control Testing

Test attention check detection:
```yaml
simulator:
  users:
    count: 10
    competence_distribution:
      adversarial: 1.0  # All users will fail
  quality_control:
    attention_check_fail_rate: 0.5  # 50% fail attention checks
    respond_fast_rate: 0.3          # 30% suspiciously fast responses
```

## Output Files

After simulation, results are exported to the output directory:

- `summary_{timestamp}.json` - Aggregate statistics
- `user_results_{timestamp}.json` - Per-user detailed results
- `annotations_{timestamp}.csv` - All annotations in flat format

### Summary Example
```json
{
  "user_count": 20,
  "total_annotations": 400,
  "total_time_seconds": 125.3,
  "attention_checks": {
    "passed": 18,
    "failed": 2,
    "pass_rate": 0.9
  },
  "gold_standards": {
    "correct": 35,
    "incorrect": 5,
    "accuracy": 0.875
  }
}
```

## Programmatic Usage

```python
from potato.simulator import SimulatorManager, SimulatorConfig

# Create configuration
config = SimulatorConfig(
    user_count=10,
    strategy="random",
    competence_distribution={"good": 0.5, "average": 0.5}
)

# Create and run simulator
manager = SimulatorManager(config, "http://localhost:8000")
results = manager.run_parallel(max_annotations_per_user=20)

# Print summary
manager.print_summary()

# Export results
manager.export_results()
```

## Integration with Tests

The simulator can be used in pytest fixtures:

```python
import pytest
from potato.simulator import SimulatorManager, SimulatorConfig

@pytest.fixture
def simulated_annotations(flask_test_server):
    """Generate simulated annotations for testing."""
    config = SimulatorConfig(user_count=5, strategy="random")
    manager = SimulatorManager(config, flask_test_server.base_url)
    return manager.run_parallel(max_annotations_per_user=10)

def test_dashboard_shows_annotations(simulated_annotations, flask_test_server):
    """Verify dashboard shows simulated data."""
    # Check admin API
    response = requests.get(f"{flask_test_server.base_url}/admin/api/overview")
    assert response.json()["total_annotations"] > 0
```

## Example Configurations

See example configuration files in:
- `examples/simulator-configs/simulator-random.yaml`
- `examples/simulator-configs/simulator-biased.yaml`
- `examples/simulator-configs/simulator-ollama.yaml`

## Troubleshooting

### Login failures
- Ensure the server allows anonymous registration or has `require_password: false`
- Check server logs for authentication errors

### No instances available
- Verify data files are loaded correctly
- Check assignment strategy settings

### LLM strategy not working
- Verify API key is set (via config or environment variable)
- For Ollama, ensure the server is running at the configured URL
- Check model name is correct

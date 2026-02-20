# User Simulator

The User Simulator enables automated testing of the Potato annotation platform by simulating multiple users with configurable behaviors and competence levels.

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

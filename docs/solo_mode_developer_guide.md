# Solo Mode Developer Guide

This guide covers the architecture, extension points, and development practices for Solo Mode.

## Architecture Overview

```
potato/solo_mode/
├── __init__.py                 # Public API exports
├── config.py                   # SoloModeConfig dataclass
├── manager.py                  # SoloModeManager singleton (orchestrator)
├── phase_controller.py         # Phase state machine
├── routes.py                   # Flask routes (/solo/*)
├── prompt_manager.py           # Prompt versioning and synthesis
├── prompt_optimizer.py         # DSPy-style optimization
├── instance_selector.py        # Weighted instance selection
├── disagreement_resolver.py    # Human-LLM conflict handling
├── validation_tracker.py       # Agreement metrics
├── llm_labeler.py              # Background LLM worker
├── edge_case_synthesizer.py    # Generate boundary examples
└── uncertainty/                # Pluggable uncertainty estimation
    ├── __init__.py
    ├── base.py                 # UncertaintyEstimator ABC
    ├── factory.py              # Strategy factory
    ├── direct_confidence.py
    ├── direct_uncertainty.py
    ├── token_entropy.py
    └── sampling_diversity.py
```

## Core Components

### SoloModeManager (`manager.py`)

The central singleton that coordinates all Solo Mode operations. Access via:

```python
from potato.solo_mode import get_solo_mode_manager, init_solo_mode_manager

# Initialize (done once at startup)
manager = init_solo_mode_manager(config_dict)

# Get existing instance
manager = get_solo_mode_manager()
```

**Key responsibilities:**
- Phase transitions
- LLM prediction storage
- Agreement tracking
- Instance selection coordination
- Background labeling control

**Thread safety:** All public methods use `self._lock` for thread-safe access. When adding new methods that access shared state, always acquire the lock:

```python
def my_new_method(self):
    with self._lock:
        # Access shared state here
        pass
```

**Adding new functionality:**

1. Add method to `SoloModeManager` class
2. If it accesses shared state, use `with self._lock:`
3. If it's part of the public API, export from `__init__.py`
4. Add unit tests in `tests/unit/test_solo_mode/`

### Phase Controller (`phase_controller.py`)

Manages the phase state machine with transition validation.

```python
from potato.solo_mode import SoloPhase, SoloPhaseController

# Phase enum values (in order)
SoloPhase.SETUP
SoloPhase.PROMPT_REVIEW
SoloPhase.EDGE_CASE_SYNTHESIS
SoloPhase.EDGE_CASE_LABELING
SoloPhase.PROMPT_VALIDATION
SoloPhase.PARALLEL_ANNOTATION
SoloPhase.DISAGREEMENT_RESOLUTION
SoloPhase.ACTIVE_ANNOTATION
SoloPhase.PERIODIC_REVIEW
SoloPhase.AUTONOMOUS_LABELING
SoloPhase.FINAL_VALIDATION
SoloPhase.COMPLETED
```

**Transition rules** are defined in `PHASE_TRANSITIONS` dict. To add a new phase:

1. Add to `SoloPhase` enum
2. Add transition rules to `PHASE_TRANSITIONS`
3. Update routes to handle the new phase
4. Add template if needed

**State persistence:** Phase state is saved to `{state_dir}/phase_state.json`. The controller handles save/load automatically.

### Routes (`routes.py`)

Flask blueprint mounted at `/solo`. All routes use two decorators:

```python
@solo_mode_bp.route('/my-route')
@login_required      # Checks session['username']
@solo_mode_required  # Checks manager is initialized
def my_route():
    manager = get_solo_mode_manager()
    # ...
```

**Adding a new route:**

1. Add route function with decorators
2. Get manager via `get_solo_mode_manager()`
3. Get user via `session.get('username', 'anonymous')`
4. Use `render_template('solo/my_template.html', ...)` for pages
5. Use `jsonify({...})` for API endpoints

**Error handling pattern:**

```python
try:
    ism = get_item_state_manager()
    item = ism.get_item(instance_id)
except ValueError as e:
    logger.error(f"Descriptive message: {e}")
    return render_template('solo/error.html', message='User-friendly message')
```

Never silently swallow exceptions. Always log and provide user feedback.

---

## Extending Uncertainty Estimation

To add a new uncertainty estimation strategy:

### 1. Create the estimator class

```python
# potato/solo_mode/uncertainty/my_estimator.py

from .base import UncertaintyEstimator
from potato.ai.ai_endpoint import BaseAIEndpoint

class MyUncertaintyEstimator(UncertaintyEstimator):
    """My custom uncertainty estimation strategy."""

    def __init__(self, config: dict = None):
        self.config = config or {}

    def estimate_uncertainty(
        self,
        instance_id: str,
        text: str,
        prompt: str,
        endpoint: BaseAIEndpoint
    ) -> float:
        """
        Estimate uncertainty for an instance.

        Returns:
            Float between 0.0 (certain) and 1.0 (uncertain)
        """
        # Your implementation here
        response = endpoint.query(prompt + "\n\nText: " + text)
        uncertainty = self._parse_uncertainty(response)
        return uncertainty

    def supports_endpoint(self, endpoint: BaseAIEndpoint) -> bool:
        """Check if this strategy works with the given endpoint."""
        # Return True if compatible, False otherwise
        return True

    def _parse_uncertainty(self, response: str) -> float:
        # Parse your uncertainty value
        pass
```

### 2. Register in factory

```python
# potato/solo_mode/uncertainty/factory.py

from .my_estimator import MyUncertaintyEstimator

class UncertaintyEstimatorFactory:
    _estimators = {
        'direct_confidence': DirectConfidenceEstimator,
        'direct_uncertainty': DirectUncertaintyEstimator,
        'token_entropy': TokenEntropyEstimator,
        'sampling_diversity': SamplingDiversityEstimator,
        'my_strategy': MyUncertaintyEstimator,  # Add here
    }
```

### 3. Add config validation

```python
# potato/server_utils/config_module.py

# In validate_solo_mode_config():
valid_strategies = [
    'direct_confidence', 'direct_uncertainty',
    'token_entropy', 'sampling_diversity',
    'my_strategy'  # Add here
]
```

### 4. Add tests

```python
# tests/unit/test_solo_mode/test_uncertainty_estimators.py

class TestMyUncertaintyEstimator:
    def test_estimate_returns_float(self):
        estimator = MyUncertaintyEstimator()
        result = estimator.estimate_uncertainty(
            instance_id="test",
            text="Sample text",
            prompt="Label this",
            endpoint=mock_endpoint
        )
        assert 0.0 <= result <= 1.0
```

---

## Adding New Annotation Type Support

Disagreement detection is type-specific. To support a new annotation type:

### 1. Add to DisagreementDetector

```python
# potato/solo_mode/disagreement_resolver.py

class DisagreementDetector:
    def detect(
        self,
        annotation_type: str,
        human_label: Any,
        llm_label: Any
    ) -> Tuple[bool, Optional[str]]:

        # Add your type handler
        if annotation_type == 'my_new_type':
            return self._detect_my_new_type(human_label, llm_label)

        # ... existing handlers ...

    def _detect_my_new_type(
        self,
        human: Any,
        llm: Any
    ) -> Tuple[bool, Optional[str]]:
        """Detect disagreement for my_new_type annotations."""
        # Return (is_disagreement, disagreement_type)
        if human != llm:
            return True, 'label_mismatch'
        return False, None
```

### 2. Add tests

```python
# tests/server/test_solo_mode/test_solo_mode_workflow.py

def test_detector_my_new_type_agreement(self):
    detector = DisagreementDetector(thresholds)
    is_disagreement, dtype = detector.detect('my_new_type', 'A', 'A')
    assert not is_disagreement

def test_detector_my_new_type_disagreement(self):
    detector = DisagreementDetector(thresholds)
    is_disagreement, dtype = detector.detect('my_new_type', 'A', 'B')
    assert is_disagreement
    assert dtype == 'label_mismatch'
```

---

## Testing

### Test Directory Structure

```
tests/
├── unit/test_solo_mode/           # Fast, isolated unit tests
│   ├── test_phase_controller.py
│   ├── test_uncertainty_estimators.py
│   └── test_validation_tracker.py
├── server/test_solo_mode/         # Integration tests with Flask
│   ├── test_solo_mode_api.py
│   └── test_solo_mode_workflow.py
└── selenium/test_solo_mode/       # Browser UI tests
    ├── test_base_solo.py          # Base class with Ollama skip
    └── test_solo_mode_ui.py       # UI interaction tests
```

### Running Tests

```bash
# Unit tests (fast, no external deps)
pytest tests/unit/test_solo_mode/ -v

# Workflow tests (uses mocks)
pytest tests/server/test_solo_mode/test_solo_mode_workflow.py -v

# Selenium tests (requires Ollama + Chrome)
pytest tests/selenium/test_solo_mode/ -v

# With custom Ollama endpoint
OLLAMA_HOST=http://my-server:11434 OLLAMA_MODEL=llama3 \
    pytest tests/selenium/test_solo_mode/ -v
```

### Writing Unit Tests

```python
import pytest
from potato.solo_mode import (
    SoloModeManager,
    init_solo_mode_manager,
    clear_solo_mode_manager,
)

class TestMyFeature:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        """Clear singleton before each test."""
        clear_solo_mode_manager()
        self.state_dir = str(tmp_path / "solo_state")
        yield
        clear_solo_mode_manager()

    def _create_config(self):
        return {
            'solo_mode': {
                'enabled': True,
                'labeling_models': [...],
                'state_dir': self.state_dir,
            },
            'annotation_schemes': [...],
        }

    def test_my_feature(self):
        config = self._create_config()
        manager = init_solo_mode_manager(config)

        result = manager.my_new_method()

        assert result == expected
```

### Writing Selenium Tests

```python
from tests.selenium.test_solo_mode.test_base_solo import BaseSoloModeSeleniumTest
from selenium.webdriver.common.by import By

class TestMyUIFeature(BaseSoloModeSeleniumTest):
    """Tests for my UI feature."""

    def test_button_click(self):
        self.login_user()
        self.navigate_to_solo_annotate()

        # Click button
        btn = self.wait_for_element_clickable(By.ID, "my-button")
        btn.click()

        # Verify result
        result = self.wait_for_element(By.ID, "result")
        assert "expected" in result.text

    def test_keyboard_shortcut(self):
        self.login_user()
        self.navigate_to_solo_annotate()

        # Press key
        self.press_key("1")

        # Verify selection
        selected = self.driver.find_element(By.CSS_SELECTOR, ".selected")
        assert selected is not None
```

---

## Templates

Templates are in `potato/templates/solo/`. They extend `base_solo.html`.

### Template Blocks

```html
{% extends "solo/base_solo.html" %}

{% block title %}My Page - Solo Mode{% endblock %}

{% block content %}
<!-- Main content -->
{% endblock %}

{% block stats %}
{{ super() }}  <!-- Include parent stats -->
<!-- Additional stats -->
{% endblock %}

{% block sidebar_extra %}
<!-- Extra sidebar content -->
{% endblock %}

{% block extra_js %}
<script>
// Page-specific JavaScript
</script>
{% endblock %}
```

### Common Patterns

**Displaying labels:**
```html
{% for label in labels %}
<button class="label-btn" data-label="{{ label }}">{{ label }}</button>
{% endfor %}
```

**Keyboard shortcuts (use `loop.index` not `enumerate`):**
```html
{% for label in labels[:9] %}
<div>
    <kbd>{{ loop.index }}</kbd> {{ label }}
</div>
{% endfor %}
```

**Conditional content:**
```html
{% if llm_prediction %}
<div class="prediction">{{ llm_prediction.label }}</div>
{% endif %}
```

---

## Common Pitfalls

### 1. Forgetting Thread Safety

```python
# WRONG - race condition
def get_count(self):
    return len(self.items)

# RIGHT - use lock
def get_count(self):
    with self._lock:
        return len(self.items)
```

### 2. Using Wrong Session Key

```python
# WRONG - Solo Mode routes use 'username'
user_id = session.get('user_id')

# RIGHT
user_id = session.get('username', 'anonymous')
```

### 3. Import Inside Request Handler

```python
# WRONG - imports on every request
def my_route():
    from potato.item_state_management import get_item_state_manager

# RIGHT - import at module level
from potato.item_state_management import get_item_state_manager

def my_route():
    ism = get_item_state_manager()
```

### 4. Silent Exception Handling

```python
# WRONG - swallows all errors
except Exception:
    return default_value

# RIGHT - log and handle specifically
except ValueError as e:
    logger.error(f"Descriptive message: {e}")
    return render_template('error.html', message='User-friendly error')
```

### 5. Non-Atomic Check-Then-Act

```python
# WRONG - race condition between check and action
if manager.should_do_something():
    manager.do_something()

# RIGHT - atomic operation
manager.check_and_do_something()  # Holds lock for both
```

---

## Debugging

### Enable Debug Logging

```python
import logging
logging.getLogger('potato.solo_mode').setLevel(logging.DEBUG)
```

### Check Manager State

```python
manager = get_solo_mode_manager()

# Phase info
print(manager.get_current_phase())
print(manager.phase_controller.get_status())

# Metrics
print(manager.get_agreement_metrics())
print(manager.get_annotation_stats())

# Predictions
print(manager.get_all_llm_predictions())
```

### API Status Endpoint

```bash
curl http://localhost:8000/solo/api/status | jq
```

---

## Performance Considerations

1. **LLM Batch Size**: Increase `llm_labeling_batch` for better throughput, decrease for lower latency.

2. **Parallel Labels Limit**: `max_parallel_labels` prevents LLM from getting too far ahead of human.

3. **Uncertainty Strategy**: `direct_confidence` is fastest, `sampling_diversity` is slowest but most accurate.

4. **State Persistence**: State is saved after each operation. For high-frequency operations, consider batching saves.

---

## Related Documentation

- [Solo Mode User Guide](solo_mode.md) - End-user documentation
- [AI Support](ai_support.md) - AI endpoint configuration
- [Testing Guide](../CLAUDE.md#test-infrastructure) - General testing patterns

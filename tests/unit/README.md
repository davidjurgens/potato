# Unit Test Documentation

## Overview

Unit tests in `tests/unit/` verify individual functions and classes in isolation using mocking. They run quickly and provide fast feedback during development.

## Test Categories

### 1. Configuration & CLI Tests

These tests verify configuration parsing, validation, and CLI argument handling.

#### `test_arg_utils.py` - CLI Argument Defaults
Tests that CLI argument defaults allow config file values to take precedence.

**Why this matters:** A bug was discovered where `--require-password` had `default=True`, which always overrode the config file setting.

```python
class TestArgumentDefaults:
    def test_require_password_default_is_none(self):
        """require_password should default to None to allow config file override."""
        parser = self._create_parser()
        args = parser.parse_args([])
        assert args.require_password is None
```

**Key tests:**
- `test_require_password_default_is_none` - Ensures config file can set password requirement
- `test_require_password_explicit_true/false` - CLI flag properly overrides config
- `test_port_default_is_none` - Port can be set via config file

#### `test_config_validation.py` - Configuration Validation
Tests that configuration files are properly validated.

```python
def test_invalid_annotation_type_rejected():
    """Unknown annotation types should be rejected."""
    config = {"annotation_schemes": [{"annotation_type": "unknown_type"}]}
    with pytest.raises(ValueError):
        validate_config(config)
```

#### `test_config_security_validation.py` - Path Security
Tests that file paths are validated for security (no directory traversal).

### 2. Schema & Annotation Type Tests

#### `test_schema_registry_integration.py` - Registry Integration
Verifies that all annotation types are properly registered in the schema registry.

**Why this matters:** A bug was discovered where `front_end.py` used a hardcoded dict that didn't include `audio_annotation` and `image_annotation`.

```python
class TestSchemaRegistryCompleteness:
    def test_all_config_types_registered(self):
        """All annotation types in config_module.valid_types should be in registry."""
        config_valid_types = [
            'radio', 'multiselect', 'likert', 'text', 'slider', 'span',
            'select', 'number', 'multirate', 'pure_display', 'video',
            'image_annotation', 'audio_annotation', 'video_annotation'
        ]
        registry_types = schema_registry.get_supported_types()
        for annotation_type in config_valid_types:
            assert annotation_type in registry_types
```

**Key tests:**
- `test_all_config_types_registered` - No annotation types missing from registry
- `test_front_end_handles_audio_annotation` - Catches hardcoded dict bugs
- `test_unknown_type_raises_valueerror` - Proper error for invalid types

#### `test_annotation_schemas.py` - Schema Generation
Tests individual schema generators produce valid HTML.

### 3. Data Processing Tests

#### `test_displayed_text.py` - Text Normalization & List Formatting
Tests the `get_displayed_text()` function that handles both string and list inputs.

**Why this matters:** A bug was discovered where passing a list (for pairwise comparison) caused a crash.

```python
class TestGetDisplayedTextList:
    def test_list_with_alphabet_prefix_default(self, mock_config):
        """List input should use alphabet prefix by default."""
        result = get_displayed_text(["First item", "Second item"])
        assert "<b>A.</b>" in result
        assert "<b>B.</b>" in result
```

**Key tests:**
- `test_simple_string_returned` - Basic string handling
- `test_list_with_alphabet_prefix_default` - Pairwise comparison formatting
- `test_list_with_number_prefix` - Number prefixes (1., 2., 3.)
- `test_empty_list` - Edge case handling

### 4. State Management Tests

#### `test_user_state.py` & `test_user_state_management.py`
Tests user state tracking, phase progression, and annotation storage.

```python
def test_user_completes_training_phase():
    """User should advance to annotation phase after completing training."""
    user_state = UserState(user_id="test_user")
    user_state.complete_training()
    assert user_state.current_phase == "annotation"
```

### 5. Span Annotation Tests

Multiple test files cover span annotation functionality:

- `test_span_annotations.py` - Core span logic
- `test_span_persistence.py` - Span data persistence
- `test_span_overlay_positioning.py` - UI positioning calculations
- `test_span_offset_calculation.py` - Character offset calculations

## Writing Unit Tests

### Basic Pattern

```python
"""
Tests for [module/function name].

These tests verify that [specific functionality].
"""

import pytest
from unittest.mock import patch, MagicMock


class TestMyFunction:
    """Test [function name] functionality."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test fixtures."""
        # Setup code here
        yield
        # Teardown code here

    def test_basic_functionality(self):
        """[Function] should [expected behavior]."""
        from potato.module import my_function

        result = my_function(input_value)

        assert result == expected_value

    def test_edge_case(self):
        """[Function] should handle [edge case]."""
        from potato.module import my_function

        result = my_function(edge_case_input)

        assert result == expected_for_edge_case
```

### Using Mocks

```python
from unittest.mock import patch, MagicMock

class TestWithMocks:
    @pytest.fixture(autouse=True)
    def mock_config(self):
        """Mock the config module for testing."""
        mock_config = MagicMock()
        mock_config.get.return_value = {}
        with patch('potato.flask_server.config', mock_config):
            yield mock_config

    def test_with_mock_config(self, mock_config):
        """Test with specific config values."""
        mock_config.get.side_effect = lambda key, default=None: {
            "some_setting": True,
            "another_setting": "value"
        }.get(key, default)

        # Test code that uses config
```

### Testing Exceptions

```python
def test_invalid_input_raises_error(self):
    """Invalid input should raise ValueError with helpful message."""
    with pytest.raises(ValueError) as exc_info:
        my_function(invalid_input)

    assert "expected_message" in str(exc_info.value)
```

## Test Patterns for Common Bugs

### 1. CLI Argument Override Bugs

Test that CLI defaults are `None` to allow config file override:

```python
def test_argument_default_allows_config_override(self):
    """[argument] should default to None to allow config override."""
    parser = create_parser()
    args = parser.parse_args([])

    # Default must be None, not True/False
    assert args.my_argument is None
```

### 2. Hardcoded Dict Bugs

Test that registries/dicts include all expected types:

```python
def test_all_types_in_registry(self):
    """All valid types should be in the registry."""
    valid_types = ['type1', 'type2', 'type3']
    registry_types = get_registry_types()

    for t in valid_types:
        assert t in registry_types, f"Missing type: {t}"
```

### 3. Input Type Handling

Test that functions handle all expected input types:

```python
def test_handles_string_input(self):
    """Function should handle string input."""
    result = my_function("string input")
    assert isinstance(result, str)

def test_handles_list_input(self):
    """Function should handle list input."""
    result = my_function(["item1", "item2"])
    assert "item1" in result
```

## Running Unit Tests

```bash
# Run all unit tests
pytest tests/unit/ -v

# Run specific test file
pytest tests/unit/test_arg_utils.py -v

# Run specific test class
pytest tests/unit/test_arg_utils.py::TestArgumentDefaults -v

# Run specific test method
pytest tests/unit/test_arg_utils.py::TestArgumentDefaults::test_require_password_default_is_none -v

# Run with debug output
pytest tests/unit/ -v -s

# Run with coverage
pytest tests/unit/ --cov=potato --cov-report=html
```

## Best Practices

### 1. Isolation
- Mock external dependencies
- Don't rely on global state
- Each test should be independent

### 2. Clear Names
- Test method names should describe what is being tested
- Use docstrings to explain why the test matters

### 3. Arrange-Act-Assert
```python
def test_something(self):
    # Arrange - set up test data
    input_data = create_test_data()

    # Act - call the function under test
    result = function_under_test(input_data)

    # Assert - verify the result
    assert result == expected_value
```

### 4. Test Edge Cases
- Empty inputs
- None values
- Invalid types
- Boundary conditions

### 5. Document Bug Prevention
If a test exists to prevent a regression, document it:

```python
def test_prevents_regression_issue_123(self):
    """Prevents regression of issue #123.

    Bug: [description of bug]
    Fix: [how it was fixed]
    """
```

## Fixtures

### Common Fixtures (conftest.py)

```python
# tests/unit/conftest.py

import pytest
from unittest.mock import MagicMock

@pytest.fixture
def mock_config():
    """Provide a mock config object."""
    config = MagicMock()
    config.get.return_value = {}
    return config

@pytest.fixture
def sample_annotation_scheme():
    """Provide a sample annotation scheme."""
    return {
        "annotation_type": "radio",
        "name": "test_scheme",
        "description": "Test description",
        "labels": ["Option A", "Option B"]
    }
```

## File Naming Convention

- `test_<module_name>.py` - Tests for a specific module
- `test_<feature>_<aspect>.py` - Tests for a specific aspect of a feature
- Example: `test_span_overlay_positioning.py`

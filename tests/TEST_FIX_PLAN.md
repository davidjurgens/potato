# Test Fix Plan

This document outlines the root causes and fixes for test failures in the potato annotation platform test suite.

## Summary

| Test Category | Failing Tests | Root Cause | Priority |
|--------------|---------------|------------|----------|
| Unit - Config Validation | 2 | Test configs missing required fields | Medium |
| Unit - Security Validation | 1 | Path security rejects temp files | Medium |
| Unit - Frontend Span | 2 | Tests don't match implementation | Low |
| Server - Flask Integration | 6 | Config file location security check | High |
| Server - Annotation Workflow | 5 | Config file location security check | High |
| Server - Annotation Types | 7 | Config file location security check | High |

---

## Root Cause Analysis

### 1. Config File Location Security Validation

**Location**: `potato/server_utils/config_module.py:782-788`

**Issue**: The new security validation requires config files to be located inside their `task_dir`:

```python
if 'task_dir' in temp_config_data:
    task_dir = temp_config_data['task_dir']
    config_file_abs = os.path.abspath(config_file)
    task_dir_abs = os.path.abspath(task_dir)
    if not config_file_abs.startswith(task_dir_abs):
        raise ConfigValidationError(f"Configuration file must be in the task_dir...")
```

**Affected Tests**: 18 server tests that use configs from `tests/configs/` but have `task_dir` pointing to `output/...`

**Example Error**:
```
ConfigValidationError: Configuration file must be in the task_dir.
Config file is at '/Users/.../tests/configs/multirate-annotation.yaml'
but task_dir is '/Users/.../output/multirate-annotation'
```

---

### 2. Test Config Files Missing Required Fields

**Location**: `tests/configs/span-debug-test.yaml` and `tests/configs/active-learning-test.yaml`

**Issue**: These configs are missing required fields that the stricter validation now requires.

**Missing Fields in `span-debug-test.yaml`**:
- `item_properties`
- `data_files`
- `task_dir`
- `output_annotation_dir`
- `annotation_task_name`
- `alert_time_each_instance`

**Issue in `active-learning-test.yaml`**:
- Uses `data_file` (singular) instead of `data_files` (list)
- Missing several required fields

---

### 3. Path Security Rejects Temp Files

**Location**: `tests/unit/test_config_security_validation.py::test_debug_mode_config`

**Issue**: Test creates files in system temp directory, which fails `validate_path_security()` because temp paths are outside the project directory.

---

### 4. Frontend Span Tests Don't Match Implementation

**Location**: `tests/unit/test_frontend_span.py`

**Issues**:
1. Tests expect `class SpanManager` but implementation uses functional programming
2. Tests expect `/api/colors` endpoint call that doesn't exist in the code

---

## Fix Strategies

### Strategy A: Test Fixture Approach (Recommended)

Create a test fixture that:
1. Copies config files to a temp directory
2. Updates the `task_dir` to match the temp directory
3. Creates necessary data files in the temp structure

**Pros**: Tests run with real configs, catches integration issues
**Cons**: More complex fixture setup

### Strategy B: Mock Security Validation

Use `unittest.mock.patch` to bypass security validation in tests:

```python
@patch('potato.server_utils.config_module.validate_path_security')
def test_config_loading(self, mock_security):
    mock_security.return_value = None  # Skip validation
    # ... test code
```

**Pros**: Simpler, faster tests
**Cons**: Doesn't test security validation in integration

### Strategy C: Create Test-Specific Configs

Create configs in `tests/configs/` that have `task_dir: "."` (same directory as config):

```yaml
task_dir: "."
output_annotation_dir: "./output"
data_files:
  - ./test_data.json
```

**Pros**: Configs are self-contained
**Cons**: Requires restructuring test configs

---

## Implementation Plan

### Phase 1: Fix Server Tests (Strategy A + B hybrid)

1. **Create `tests/helpers/test_config_utils.py`**:
   ```python
   def setup_test_config(config_path: str, temp_dir: str) -> str:
       """
       Copy config to temp dir and update paths.
       Returns path to copied config.
       """
       # Copy config to temp_dir
       # Update task_dir to temp_dir
       # Create required directories
       # Copy/create data files
       return new_config_path
   ```

2. **Update test fixtures** to use `setup_test_config()`

3. **For unit tests only**, patch security validation:
   ```python
   @pytest.fixture
   def bypass_security():
       with patch('potato.server_utils.config_module.validate_path_security'):
           yield
   ```

### Phase 2: Fix Config Files

1. **Update `span-debug-test.yaml`** with required fields:
   ```yaml
   item_properties:
     id_key: "id"
     text_key: "text"
   data_files:
     - test_data.json
   task_dir: "."
   output_annotation_dir: "./output"
   annotation_task_name: "span-debug-test"
   alert_time_each_instance: 10
   ```

2. **Update `active-learning-test.yaml`**:
   - Change `data_file` to `data_files` (list)
   - Add missing required fields

### Phase 3: Fix Frontend Span Tests

1. **Update `test_frontend_span.py`** to match actual implementation:
   - Remove tests for `SpanManager` class
   - Test actual functional API instead
   - Remove `/api/colors` endpoint test

2. Or **Delete** these tests if they're testing unimplemented features

### Phase 4: Fix Path Security Test

1. **Update `test_debug_mode_config`** to create temp files within the project:
   ```python
   def test_debug_mode_config(self, temp_dir, valid_config):
       # Create data file in temp_dir/data (not system temp)
       data_path = os.path.join(temp_dir, "data", "test.json")
       # Update config to point to this path
   ```

---

## Detailed Fix List

### Unit Tests (5 failures)

| Test | Fix |
|------|-----|
| `test_config_file_validates[span-debug-test.yaml]` | Update config with required fields |
| `test_config_file_validates[active-learning-test.yaml]` | Fix `data_file` -> `data_files`, add missing fields |
| `test_debug_mode_config` | Create temp files in project directory |
| `test_span_manager_initialization` | Update to test functional API |
| `test_span_manager_api_calls` | Remove or update to match implementation |

### Server Tests (18 failures)

| Test File | Fix Approach |
|-----------|--------------|
| `test_flask_integration.py` (6 tests) | Use `setup_test_config()` fixture |
| `test_annotation_workflow.py` (5 tests) | Use `setup_test_config()` fixture |
| `test_annotation_types.py` (7 tests) | Use `setup_test_config()` fixture |

---

## Implementation Order

1. **Week 1**: Create `setup_test_config()` helper and update 3 server test files
2. **Week 2**: Fix config files (`span-debug-test.yaml`, `active-learning-test.yaml`)
3. **Week 2**: Fix path security test
4. **Week 3**: Evaluate and fix/remove frontend span tests

---

## Verification

After implementing fixes, run:

```bash
# Unit tests
python -m pytest tests/unit/ -v

# Server tests
python -m pytest tests/server/test_flask_integration.py tests/server/test_annotation_workflow.py tests/server/test_annotation_types.py -v

# Full suite
python -m pytest tests/ -v
```

Expected: All tests pass with no failures.

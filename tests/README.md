# Potato Test Suite

This directory contains comprehensive tests for the Potato annotation platform, covering both backend functionality and frontend user interface testing.

## Recent Bugs and Their Tests

This section documents bugs that were discovered and the tests created to prevent regressions.

| Bug | Root Cause | Test File | Key Test |
|-----|------------|-----------|----------|
| `require_password` config ignored | argparse `default=True` overrode config file | `test_arg_utils.py` | `test_require_password_default_is_none` |
| `get_displayed_text` crash on lists | Function only handled strings, not pairwise lists | `test_displayed_text.py` | `test_list_with_alphabet_prefix_default` |
| `audio_annotation` type not recognized | `front_end.py` used hardcoded dict, not registry | `test_schema_registry_integration.py` | `test_front_end_handles_audio_annotation` |
| `image_annotation` type not recognized | Same hardcoded dict issue | `test_schema_registry_integration.py` | `test_front_end_handles_image_annotation` |
| Firefox form restoration bug | Browser preserved checkbox state across pages | `test_comprehensive_span_annotation_firefox.py` | `test_checkbox_cleared_on_navigation` |
| Radio button persistence issue | Different HTML name pattern vs checkbox | `test_annotation_persistence_frontend.py` | `test_radio_persists_within_instance` |
| Span annotation overlays not rendering | `sanitize_html` returned plain string, causing Jinja2 double-escape | `test_html_sanitizer.py` | `test_jinja2_does_not_double_escape` |
| Span overlay position mismatch | `data-original-text` had HTML instead of plain text; `getTextPositions` assumed single text node | `test_span_overlay_text_positions.py` | `test_plain_text_preserved_in_attribute` |
| Span overlay invisible (width=0) | Template whitespace in `#text-content` caused DOM textContent to differ from `data-original-text`; position offsets mapped to whitespace | `span-overlay-creation.test.js` | `CRITICAL: data-original-text must match DOM textContent exactly` |

### Test-Driven Bug Prevention

When fixing a bug:
1. Write a test that reproduces the bug (should fail before fix)
2. Fix the bug
3. Verify the test passes
4. Document the bug/test relationship in this table

## Test File Security Policy

**IMPORTANT: All test configuration and data files must reside within the `tests/` directory.**

- **Temporary files**: Must be created in `tests/output/` or its subdirectories
- **Config files**: Must be within `tests/` directory structure
- **Data files**: Must be within `tests/` directory structure
- **Path validation**: All file paths in configs must be relative to `task_dir` or within `tests/`
- **No system temp directories**: Do NOT use `/tmp`, `/var`, or system temp directories for test files

This is required for path security and to ensure tests run in all environments.

## Test Utilities

Use the `tests/helpers/test_utils.py` module for creating secure test configurations:

```python
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_data_file,
    create_test_config,
    create_span_annotation_config,
    create_comprehensive_annotation_config,
    TestConfigManager
)

# Example: Create a span annotation test
test_dir = create_test_directory("my_span_test")
config_file, data_file = create_span_annotation_config(test_dir)

# Example: Using context manager for automatic cleanup
with TestConfigManager("my_test", annotation_schemes) as test_config:
    # Use test_config.config_path, test_config.data_path
    pass  # Automatic cleanup on exit
```

## Test Structure

### Server Tests (`tests/server/`)
Server tests use the `FlaskTestServer` class to test against real Flask server instances. These are integration tests that verify actual HTTP endpoints and server behavior.

**📖 [Server Test Documentation](server/README.md)** - Complete guide to server testing
**📋 [Quick Reference](server/QUICK_REFERENCE.md)** - Common patterns and code snippets
**📝 [Test Template](server/test_template.py)** - Template for creating new server tests

**Key Server Test Files:**
- **`test_backend_state.py`** - User and item state management
- **`test_annotation_workflow.py`** - Complete annotation process testing
- **`test_multi_phase_workflow.py`** - Phase transitions and consent workflows
- **`test_agreement_workflow.py`** - Multi-annotator agreement testing
- **`test_assignment_strategies.py`** - Different assignment algorithms
- **`test_annotation_types.py`** - Various annotation scheme testing
- **`test_error_handling_workflow.py`** - Error scenarios and recovery
- **`test_robust_span_annotation.py`** - Span annotation edge cases

### Selenium Tests (`tests/selenium/`)
Frontend tests using Selenium WebDriver to test the user interface and browser interactions.

**📖 [Selenium Test Documentation](selenium/README.md)** - Complete guide to Selenium testing

**Key Selenium Test Files:**
- **`test_frontend_span_system.py`** - Span annotation UI testing
- **`test_user_state_contract.py`** - User state contract verification
- **`test_api_contract.py`** - API contract testing via frontend
- **`test_multirate_annotation.py`** - Multi-rate annotation UI testing

### Unit Tests (`tests/unit/`)
Pure unit tests that test individual functions and classes without external dependencies. These tests use mocking to isolate components.

**📖 [Unit Test Documentation](unit/README.md)** - Complete guide to unit testing

**Key Unit Test Files:**

#### Configuration & CLI
- **`test_config_validation.py`** - Configuration file validation
- **`test_config_security_validation.py`** - Path security validation
- **`test_arg_utils.py`** - CLI argument parsing and defaults (prevents config override bugs)
- **`test_malicious_configs.py`** - Security tests for malicious configs

#### Schema & Annotation Types
- **`test_annotation_schemas.py`** - Schema validation and generation
- **`test_schema_registry_integration.py`** - Registry completeness and front_end integration
- **`test_image_annotation_schema.py`** - Image annotation schema
- **`test_audio_annotation_schema.py`** - Audio annotation schema
- **`test_video_annotation_schema.py`** - Video annotation schema
- **`test_video_schema.py`** - Video display schema

#### State Management
- **`test_user_state.py`** - User state management logic
- **`test_user_state_management.py`** - User state manager
- **`test_database_user_state.py`** - Database-backed user state

#### Data Processing
- **`test_displayed_text.py`** - Text normalization and pairwise list formatting
- **`test_annotation_api.py`** - Annotation API functions
- **`test_annotation_history.py`** - Annotation history tracking
- **`test_timestamp_tracking.py`** - Timestamp tracking for annotations

#### Span Annotation
- **`test_span_annotations.py`** - Span annotation logic
- **`test_span_persistence.py`** - Span persistence
- **`test_span_overlay_positioning.py`** - Span overlay positioning
- **`test_span_offset_calculation.py`** - Span offset calculations

#### AI Integration
- **`test_ai_endpoints.py`** - AI endpoint implementations
- **`test_ai_help_wrapper.py`** - AI help wrapper
- **`test_icl_prompt_builder.py`** - In-context learning prompts
- **`test_icl_labeler.py`** - ICL labeler

#### Utilities
- **`test_preview_cli.py`** - Preview CLI tool
- **`test_migrate_cli.py`** - Migration CLI tool
- **`test_prolific_integration.py`** - Prolific integration

### Integration Tests (`tests/integration/`)
End-to-end tests using real Flask servers and Selenium browsers. These tests verify complete user journeys from registration to annotation completion.

**📖 [Integration Test Documentation](integration/README.md)** - Complete guide to integration testing

**Key Integration Test Files:**
- **`base.py`** - IntegrationTestServer and BaseIntegrationTest classes
- **`test_smoke.py`** - Critical path tests (server startup, home page, registration)
- **`test_workflows.py`** - Complete user journey tests
- **`test_annotation_types_e2e.py`** - End-to-end annotation type tests
- **`test_persistence.py`** - State preservation tests
- **`test_edge_cases.py`** - Boundary condition tests

### Jest Frontend Tests (`tests/jest/`)
JavaScript unit tests for frontend functionality using jsdom.

**📖 [Jest Test Documentation](jest/README.md)** - Complete guide to Jest testing

**Key Jest Test Files:**
- **`annotation-functions.test.js`** - Core annotation functions (updateAnnotation, validation)
- **`span-manager-simple.test.js`** - Span manager functionality (initialization, CRUD, rendering)
- **`interval-rendering-structure.test.js`** - DOM structure for span rendering
- **`setup.js`** - Test setup and mocks

### Test Infrastructure
- **`tests/helpers/flask_test_setup.py`** - FlaskTestServer class and test utilities
- **`tests/helpers/port_manager.py`** - Reliable port allocation with retry logic (prevents TOCTOU race conditions)
- **`tests/helpers/test_utils.py`** - Test configuration and data file utilities
- **`tests/selenium/test_base.py`** - BaseSeleniumTest class for Selenium tests
- **`tests/integration/base.py`** - IntegrationTestServer class for E2E tests
- **`tests/integration/conftest.py`** - Integration test fixtures and known issue tracking
- **`tests/jest/setup.js`** - Jest test environment setup
- **`tests/conftest.py`** - Pytest fixtures and shared test setup
- **`tests/configs/`** - Test configuration files
- **`tests/data/`** - Test data files

## Test Architecture

### Server Tests (Integration)
- **FlaskTestServer**: Real Flask server instance for testing
- **Production Mode**: Tests run against production server (not debug mode)
- **Admin Authentication**: Automatic admin API key for admin endpoints
- **Session Management**: Full user session and authentication testing
- **Config Management**: File-based and dict-based configuration testing

### Selenium Tests (UI Integration)
- **BaseSeleniumTest**: Base class with automatic user registration/login
- **Headless Chrome**: Browser runs in headless mode for CI compatibility
- **Production Server**: Tests against real Flask server (not debug mode)
- **User Isolation**: Each test gets unique user account
- **Session Persistence**: Maintains user sessions across requests

### Unit Tests (Isolated)
- **Mock Interfaces**: No external dependencies
- **Fast Execution**: Quick feedback for development
- **Pure Functions**: Test individual components in isolation

## Annotation Types Tested

The test suite covers all major annotation types supported by Potato:

1. **Likert Scale** (`likert`) - Rating scales with radio buttons
2. **Checkbox/Multiselect** (`multiselect`) - Multiple choice selections
3. **Slider** (`slider`) - Range-based ratings
4. **Span Annotation** (`span`) - Text highlighting and labeling
5. **Radio Buttons** (`radio`) - Single choice selections
6. **Text Input** (`text`) - Free text responses
7. **Multirate** (`multirate`) - Rating matrices
8. **Select Dropdown** (`select`) - Dropdown selections
9. **Number Input** (`number`) - Numeric inputs
10. **Pure Display** (`pure_display`) - Information-only displays

## Running Tests

### Prerequisites

1. Install test dependencies:
```bash
pip install -r requirements-test.txt
```

2. For Selenium tests, install ChromeDriver:
```bash
# On macOS with Homebrew
brew install chromedriver

# Or download from https://chromedriver.chromium.org/
```

### Running All Tests

```bash
# Run all Python tests
pytest

# Run all tests (Python + Jest)
npm run test:all

# Run with coverage report
pytest --cov=potato --cov-report=html
```

### Running Jest Tests

```bash
# Run all Jest tests
npm run test:jest

# Run Jest with watch mode
npm run test:jest:watch

# Run Jest with coverage
npm run test:jest:coverage
```

### Running Specific Test Categories

```bash
# Run only server tests (integration)
pytest tests/server/ -v

# Run only Selenium tests (UI)
pytest tests/selenium/ -v

# Run only unit tests (isolated)
pytest tests/unit/ -v

# Run specific test file
pytest tests/server/test_backend_state.py -v

# Run specific test class
pytest tests/server/test_backend_state.py::TestBackendState -v

# Run specific test method
pytest tests/server/test_backend_state.py::TestBackendState::test_health_check -v

# Run with debug output
pytest tests/server/ -v -s
```

### Test Categories by Type

```bash
# Integration tests (server + Selenium)
pytest tests/server/ tests/selenium/ -v

# Unit tests only
pytest tests/unit/ -v

# All tests except Selenium (faster)
pytest tests/server/ tests/unit/ -v

# All tests except server (faster)
pytest tests/selenium/ tests/unit/ -v
```

## Creating New Tests

### Server Tests
1. **Use the template**: Copy `tests/server/test_template.py`
2. **Follow patterns**: See `tests/server/QUICK_REFERENCE.md`
3. **Use FlaskTestServer**: Always use the FlaskTestServer class
4. **Test production mode**: Server runs in production mode (`debug=False`)
5. **Use unique ports**: Each test class should use a different port

### Selenium Tests
1. **Inherit from BaseSeleniumTest**: Automatic user registration/login
2. **Use headless mode**: Chrome runs in headless mode
3. **Test production server**: Tests against real Flask server
4. **Follow UI patterns**: See `tests/selenium/README.md`

### Unit Tests
1. **No external dependencies**: Use mocks for external services
2. **Fast execution**: Keep tests quick for development feedback
3. **Pure functions**: Test individual components in isolation

## Test Data

Tests use various data sources:
- **Server tests**: Create temporary test data files
- **Selenium tests**: Use `tests/configs/` and `tests/data/`
- **Unit tests**: Use mock data or simple test fixtures

## Test Output

- **HTML Reports**: Generated in `test-results/report.html`
- **Coverage Reports**: Generated in `test-results/coverage/`
- **Console Output**: Verbose test results with pass/fail status

## Continuous Integration

The test suite is designed to work with CI/CD pipelines:
- **Unit tests**: Fast feedback for development
- **Server tests**: Integration validation
- **Selenium tests**: UI validation (can be run separately)
- **Coverage reporting**: Code quality metrics

## Test Consolidation Recommendations

The test suite has grown organically and contains significant duplication, particularly in span and persistence tests. Below are recommendations for future consolidation:

### Span Tests (~41 files)

**Current state:** Span annotation tests are spread across unit, server, and selenium directories with significant overlap.

**Recommended consolidation into 3 files:**

| Target File | Purpose | Source Files |
|-------------|---------|--------------|
| `tests/unit/test_span_schema.py` | Schema generation, HTML output, offset calculations | `test_span_annotations.py`, `test_span_schema_loading.py`, `test_span_integration.py`, `test_span_offset_*.py`, `test_span_overlap_*.py` |
| `tests/server/test_span_e2e.py` | Full workflow tests, API endpoints | `test_span_annotation_workflow.py`, `test_robust_span_annotation.py`, `test_span_schema_api.py`, `test_span_persistence_bug.py` |
| `tests/selenium/test_span_browser.py` | Browser interactions, overlay rendering | All selenium `test_*span*.py` files |

### Persistence Tests (~15 files)

**Current state:** Persistence tests exist in multiple directories with overlapping coverage.

**Recommended consolidation:**
- Keep `tests/selenium/test_annotation_type_persistence.py` (5 passing tests)
- Merge other persistence tests into `tests/integration/test_persistence.py`
- Remove clearly redundant bug-specific tests once functionality is verified

### Port Allocation

**Infrastructure improvement completed:**
- `tests/helpers/port_manager.py` provides reliable port allocation with retry logic
- Mitigates TOCTOU race conditions in parallel test execution
- Used by both `FlaskTestServer` and `IntegrationTestServer`

### Known Issues

Some configs are marked as expected failures in `tests/integration/conftest.py`:
- `simple-audio-annotation`, `simple-best-worst-scaling`, `simple-image-annotation`: Missing `site_dir` field
- `simple-pairwise-comparison`: TypeError in annotation type
- `two-sliders`: Server startup timeout
- `category-assignment-example`, `icl-labeling-example`, `quality-control-example`: Missing data files

## Troubleshooting

### Server Test Issues
- **Port conflicts**: Use unique ports for each test class
- **File paths**: Ensure data files use absolute paths or are relative to project root
- **Admin endpoints**: FlaskTestServer automatically adds admin API key
- **Session management**: Use proper session handling for user endpoints

### Selenium Test Issues
- **ChromeDriver**: Ensure ChromeDriver is installed and in PATH
- **Browser compatibility**: Check Chrome browser version compatibility
- **Headless mode**: Tests run in headless mode for CI environments
- **User authentication**: BaseSeleniumTest handles user registration/login

### Unit Test Issues
- **Import paths**: Ensure `potato` module is in Python path
- **Dependencies**: Check that all dependencies are installed
- **Mock setup**: Verify mock objects are properly configured

## Documentation

- **[Server Test Guide](server/README.md)** - Complete server testing documentation
- **[Selenium Test Guide](selenium/README.md)** - Complete Selenium testing documentation
- **[Quick Reference](server/QUICK_REFERENCE.md)** - Common test patterns and code snippets
- **[Test Template](server/test_template.py)** - Template for new server tests
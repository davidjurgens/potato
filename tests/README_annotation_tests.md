# Annotation Schema Test Suite

This directory contains comprehensive Selenium-based tests for all annotation schema types supported by the Potato annotation framework.

## Overview

The test suite covers:

1. **Individual Annotation Types**: Tests for each schema type in isolation
2. **Multiple Schemas**: Tests with multiple annotation schemas per instance
3. **Multi-Annotator**: Tests simulating concurrent annotators
4. **Navigation & Persistence**: Tests for data persistence across navigation
5. **Validation**: Tests for Next button state and required field validation

## Test Files

### 1. `test_all_annotation_types_selenium.py`
Main test file containing tests for all individual annotation types and multi-schema scenarios.

**Test Classes:**
- `TestIndividualAnnotationTypes`: Tests for each schema type
- `TestMultipleSchemas`: Tests with multiple schemas per instance
- `TestMultiAnnotator`: Tests for concurrent annotators

**Individual Annotation Types Tested:**
- Radio button annotation
- Text input annotation (textbox and textarea)
- Multiselect annotation
- Likert scale annotation
- Number input annotation
- Slider annotation
- Select dropdown annotation

### 2. `test_multirate_annotation_selenium.py`
Specialized tests for multirate annotation (rating multiple items on the same scale).

**Test Classes:**
- `TestMultirateAnnotation`: Tests for multirate functionality

**Features Tested:**
- Multiple rating scales per instance
- Required field validation
- Rating value storage and retrieval

### 3. `test_span_annotation_selenium.py`
Comprehensive tests for span annotation (text highlighting) - the most complex annotation type.

**Test Classes:**
- `TestSpanAnnotation`: Tests for span highlighting functionality

**Features Tested:**
- Basic span annotation interface
- Text selection and highlighting
- Multiple span types/labels
- Navigation persistence
- Undo/redo functionality

## Annotation Schema Types

### 1. Radio Button Annotation
- **Purpose**: Single-choice selection from multiple options
- **Test Focus**: Radio group behavior, validation, Next button state
- **Config Example**: See `configs/radio-annotation.yaml`

### 2. Text Input Annotation
- **Purpose**: Free text input (single-line and multi-line)
- **Test Focus**: Textbox vs textarea behavior, validation
- **Config Example**: See `configs/text-annotation.yaml`

### 3. Multiselect Annotation
- **Purpose**: Multiple-choice selection from options
- **Test Focus**: Checkbox behavior, multiple selections, free response
- **Config Example**: See `configs/multiselect-annotation.yaml`

### 4. Likert Scale Annotation
- **Purpose**: Rating on a predefined scale
- **Test Focus**: Scale selection, validation
- **Config Example**: See `configs/likert-annotation.yaml`

### 5. Number Input Annotation
- **Purpose**: Numeric input with constraints
- **Test Focus**: Number validation, min/max constraints
- **Config Example**: See `configs/number-annotation.yaml`

### 6. Slider Annotation
- **Purpose**: Visual slider for rating
- **Test Focus**: Slider interaction, value capture
- **Config Example**: See `configs/slider-annotation.yaml`

### 7. Select Dropdown Annotation
- **Purpose**: Dropdown selection from options
- **Test Focus**: Dropdown interaction, option selection
- **Config Example**: See `configs/select-annotation.yaml`

### 8. Multirate Annotation
- **Purpose**: Rating multiple items on the same scale
- **Test Focus**: Multiple rating inputs, scale consistency
- **Config Example**: See `configs/multirate-annotation.yaml`

### 9. Span Annotation (Highlight)
- **Purpose**: Text highlighting and span labeling
- **Test Focus**: Text selection, visual feedback, span management
- **Config Example**: See `configs/span-annotation.yaml`

## Test Verification Points

All tests verify the following key aspects:

### 1. Next Button State
- ✅ Next button is disabled when required fields are empty
- ✅ Next button is enabled when all required fields are filled
- ✅ Next button state updates correctly as fields are filled/cleared

### 2. Data Storage
- ✅ All annotation data is correctly stored by the server
- ✅ Data format matches expected schema
- ✅ Data persists across page refreshes

### 3. Navigation Persistence
- ✅ Annotations persist when navigating to next instance
- ✅ Annotations reappear when navigating back to previous instance
- ✅ No data loss during navigation

### 4. Multi-Annotator Support
- ✅ Multiple annotators can work concurrently
- ✅ Each annotator's data is stored separately
- ✅ No cross-contamination between annotators

## Running the Tests

### Prerequisites
- Python 3.7+
- Chrome browser installed
- ChromeDriver in PATH
- Required Python packages: `selenium`, `pytest`

### Running All Tests
```bash
# Run all tests
python tests/run_all_annotation_tests.py

# Run specific test category
python tests/run_all_annotation_tests.py radio
python tests/run_all_annotation_tests.py text
python tests/run_all_annotation_tests.py span
```

### Running Individual Test Files
```bash
# Run main test suite
pytest tests/test_all_annotation_types_selenium.py -v

# Run multirate tests
pytest tests/test_multirate_annotation_selenium.py -v

# Run span annotation tests
pytest tests/test_span_annotation_selenium.py -v
```

### Running Specific Test Classes
```bash
# Run only individual annotation type tests
pytest tests/test_all_annotation_types_selenium.py::TestIndividualAnnotationTypes -v

# Run only multi-schema tests
pytest tests/test_all_annotation_types_selenium.py::TestMultipleSchemas -v

# Run only multi-annotator tests
pytest tests/test_all_annotation_types_selenium.py::TestMultiAnnotator -v
```

### Running Specific Test Methods
```bash
# Run specific annotation type test
pytest tests/test_all_annotation_types_selenium.py::TestIndividualAnnotationTypes::test_radio_annotation -v

# Run specific multirate test
pytest tests/test_multirate_annotation_selenium.py::TestMultirateAnnotation::test_multirate_annotation -v

# Run specific span test
pytest tests/test_span_annotation_selenium.py::TestSpanAnnotation::test_span_annotation_basic -v
```

## Test Configuration

Each test uses self-contained configuration that includes:

- **Port**: Unique port for each test to avoid conflicts
- **Task Directory**: Separate output directory for each test
- **Data Files**: Test data with sample text instances
- **Annotation Schemes**: Complete schema definitions
- **User Configuration**: Allow all users for testing

## Test Data

All tests use the same test data with three sample text instances:

1. **AI/Technology text**: "The new artificial intelligence model achieved remarkable results..."
2. **Emotional text**: "I'm feeling incredibly sad today because my beloved pet passed away..."
3. **Political text**: "The political debate was heated and intense, with candidates passionately arguing..."

This diverse test data allows testing different annotation scenarios across various content types.

## Debugging Tests

### Common Issues
1. **ChromeDriver not found**: Ensure ChromeDriver is in PATH
2. **Port conflicts**: Each test uses unique ports (9001-9034)
3. **Template caching**: Tests automatically regenerate templates
4. **Timing issues**: Tests include appropriate waits for UI elements

### Debug Mode
Tests run in debug mode by default. To see browser interaction:
```bash
# Remove --headless option in test files to see browser
pytest tests/test_all_annotation_types_selenium.py -v -s
```

### Logging
Tests include comprehensive logging to help debug issues:
- Server startup/shutdown logs
- User registration/login logs
- Annotation submission logs
- Data storage verification logs

## Test Results

The test runner provides a comprehensive summary including:
- Total test runs
- Success/failure counts
- Success rate percentage
- Detailed error messages for failed tests
- Overall pass/fail status

## Contributing

When adding new annotation schema types:

1. Add test methods to `TestIndividualAnnotationTypes`
2. Create self-contained config for the new schema
3. Test all verification points (Next button, storage, persistence)
4. Add to the test runner categories
5. Update this documentation

## Notes

- **Span Annotation**: Most complex due to text selection requirements
- **Text Annotation**: Tests both textbox and textarea behaviors
- **Multirate**: Unique due to multiple rating scales per instance
- **Multi-Annotator**: Tests concurrent access and data isolation
- **Navigation**: Critical for real-world usage scenarios
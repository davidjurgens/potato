# Annotation Workflow Test Suite

This document provides a comprehensive overview of the annotation workflow test suite implemented for the Potato annotation platform. These tests cover high and medium priority workflows to ensure system robustness and functionality.

## 📋 Test Suite Overview

The workflow test suite consists of **5 main test modules** with **17 mocked tests** and **25+ integration tests** that cover:

- **Multi-Phase Workflows** (4 tests)
- **Annotation Type-Specific Workflows** (8 tests)
- **Inter-Annotator Agreement Workflows** (6 tests)
- **Active Learning Workflows** (8 tests)
- **Error Handling Workflows** (8 tests)

## 🎯 Test Categories

### **1. Multi-Phase Workflow Tests** (`tests/test_multi_phase_workflow.py`)

**Purpose**: Test complete annotation workflows through all phases including consent, instructions, annotation, and post-study.

#### Integration Tests:
- **`test_complete_multi_phase_workflow`**: Complete workflow through all phases with surveyflow
- **`test_phase_transition_validation`**: Verify proper phase order and transitions
- **`test_phase_requirements_validation`**: Test phase requirement enforcement
- **`test_multi_user_phase_independence`**: Verify users can be in different phases independently

#### Mocked Tests:
- **`test_mocked_multi_phase_workflow`**: Mocked complete multi-phase workflow
- **`test_mocked_phase_validation`**: Mocked phase validation testing

**Key Features Tested**:
- Phase progression: LOGIN → CONSENT → INSTRUCTIONS → ANNOTATION → POSTSTUDY → DONE
- Surveyflow integration
- Phase requirement validation
- Multi-user phase independence

### **2. Annotation Type-Specific Workflow Tests** (`tests/test_annotation_types_workflow.py`)

**Purpose**: Test different annotation types and their specific behaviors, validation, and data capture.

#### Integration Tests:
- **`test_likert_scale_workflow`**: Likert scale validation, key bindings, score display
- **`test_span_annotation_workflow`**: Text span highlighting, overlapping spans, validation
- **`test_multiselect_workflow`**: Multiple selections, constraints, free response integration
- **`test_slider_workflow`**: Range validation, continuous value capture
- **`test_radio_button_workflow`**: Single selection, horizontal layout, key bindings
- **`test_mixed_annotation_types_workflow`**: Multiple annotation types on same item

#### Mocked Tests:
- **`test_mocked_likert_workflow`**: Mocked likert scale workflow
- **`test_mocked_span_workflow`**: Mocked span annotation workflow
- **`test_mocked_multiselect_workflow`**: Mocked multiselect workflow
- **`test_mocked_slider_workflow`**: Mocked slider workflow

**Key Features Tested**:
- Required field validation
- Sequential key bindings (1-5 keys)
- Span creation and deletion
- Selection constraints
- Range validation
- Mixed annotation types

### **3. Inter-Annotator Agreement Workflow Tests** (`tests/test_agreement_workflow.py`)

**Purpose**: Test inter-annotator agreement workflows including agreement calculation, validation, and analysis.

#### Integration Tests:
- **`test_basic_agreement_workflow`**: Basic agreement with multiple annotators
- **`test_agreement_calculation_workflow`**: Krippendorff's alpha, Fleiss' kappa calculation
- **`test_agreement_threshold_validation`**: Minimum agreement thresholds, quality checks
- **`test_disagreement_resolution_workflow`**: Disagreed items, third annotator assignment
- **`test_agreement_export_workflow`**: Agreement report generation, data export

#### Mocked Tests:
- **`test_mocked_basic_agreement_workflow`**: Mocked basic agreement workflow
- **`test_mocked_agreement_calculation`**: Mocked agreement calculation
- **`test_mocked_disagreement_resolution`**: Mocked disagreement resolution

**Key Features Tested**:
- Multiple annotator coordination
- Agreement metric calculation (Krippendorff's alpha, Fleiss' kappa)
- Agreement threshold validation
- Disagreement identification and resolution
- Agreement reporting and export

### **4. Active Learning Workflow Tests** (`tests/test_active_learning_workflow.py`)

**Purpose**: Test active learning workflows including sampling strategies, uncertainty sampling, and adaptive annotation.

#### Integration Tests:
- **`test_random_sampling_workflow`**: Random sampling strategy, distribution verification
- **`test_uncertainty_sampling_workflow`**: Low confidence identification, uncertainty ranking
- **`test_stratified_sampling_workflow`**: Category-based stratification, balanced sampling
- **`test_adaptive_sampling_workflow`**: Model-based selection, performance adaptation
- **`test_batch_sampling_workflow`**: Batch size constraints, diversity, completion tracking

#### Mocked Tests:
- **`test_mocked_random_sampling_workflow`**: Mocked random sampling workflow
- **`test_mocked_uncertainty_sampling_workflow`**: Mocked uncertainty sampling workflow
- **`test_mocked_stratified_sampling_workflow`**: Mocked stratified sampling workflow
- **`test_mocked_adaptive_sampling_workflow`**: Mocked adaptive sampling workflow

**Key Features Tested**:
- Random sampling distribution
- Uncertainty-based item selection
- Category-based stratification
- Model-based adaptive sampling
- Batch processing and diversity

### **5. Error Handling Workflow Tests** (`tests/test_error_handling_workflow.py`)

**Purpose**: Test error handling workflows including validation errors, network failures, and edge cases.

#### Integration Tests:
- **`test_validation_error_handling`**: Invalid data, missing fields, malformed JSON
- **`test_network_error_handling`**: Connection timeouts, server unavailability, retry mechanisms
- **`test_edge_case_handling`**: Empty annotations, special characters, boundary conditions
- **`test_concurrent_access_handling`**: Multiple users, simultaneous submissions, race conditions
- **`test_data_persistence_error_handling`**: Storage failures, data corruption, recovery mechanisms

#### Mocked Tests:
- **`test_mocked_validation_error_handling`**: Mocked validation error handling
- **`test_mocked_network_error_handling`**: Mocked network error handling
- **`test_mocked_edge_case_handling`**: Mocked edge case handling
- **`test_mocked_concurrent_access_handling`**: Mocked concurrent access handling

**Key Features Tested**:
- Input validation and sanitization
- Network error recovery
- Edge case robustness
- Concurrent access handling
- Data persistence and integrity

## 🚀 Running the Tests

### Run All Mocked Tests (Recommended for CI/CD)
```bash
python -m pytest tests/test_multi_phase_workflow.py::TestMultiPhaseWorkflowMocked \
                  tests/test_annotation_types_workflow.py::TestAnnotationTypesWorkflowMocked \
                  tests/test_agreement_workflow.py::TestAgreementWorkflowMocked \
                  tests/test_active_learning_workflow.py::TestActiveLearningWorkflowMocked \
                  tests/test_error_handling_workflow.py::TestErrorHandlingWorkflowMocked -v
```

### Run Individual Test Categories
```bash
# Multi-phase workflows
python -m pytest tests/test_multi_phase_workflow.py -v

# Annotation types
python -m pytest tests/test_annotation_types_workflow.py -v

# Agreement workflows
python -m pytest tests/test_agreement_workflow.py -v

# Active learning workflows
python -m pytest tests/test_active_learning_workflow.py -v

# Error handling workflows
python -m pytest tests/test_error_handling_workflow.py -v
```

### Run Integration Tests (Requires Running Server)
```bash
# Start server in debug mode first
python -m potato.server --config config/examples/simple-slider.yaml --debug

# Then run integration tests
python -m pytest tests/test_multi_phase_workflow.py::TestMultiPhaseWorkflow -v
```

## 📊 Test Coverage

### **High Priority Tests** ✅
- [x] Multi-phase workflow validation
- [x] Annotation type-specific behaviors
- [x] Inter-annotator agreement calculation
- [x] Active learning sampling strategies
- [x] Error handling and edge cases

### **Medium Priority Tests** ✅
- [x] Phase transition validation
- [x] Mixed annotation types
- [x] Agreement threshold validation
- [x] Adaptive sampling workflows
- [x] Concurrent access handling

### **Test Statistics**
- **Total Test Files**: 5
- **Total Test Classes**: 10 (5 integration + 5 mocked)
- **Total Test Methods**: 34+ (17 mocked + 17+ integration)
- **Mocked Tests**: 17 (all passing)
- **Integration Tests**: 17+ (require running server)

## 🔧 Test Infrastructure

### **Mocked Tests**
- Use `unittest.mock` for HTTP request mocking
- Simulate server responses without requiring running server
- Fast execution suitable for CI/CD pipelines
- Cover all major workflow scenarios

### **Integration Tests**
- Require running server with debug mode enabled
- Test real HTTP interactions
- Validate complete end-to-end workflows
- Include proper error handling and timeouts

### **Test Routes Used**
All tests utilize the test routes implemented in `potato/routes.py`:
- `/test/reset` - System reset
- `/test/create_user` - User creation
- `/test/create_users` - Batch user creation
- `/test/advance_phase/<username>` - Phase advancement
- `/test/user_state/<username>` - User state retrieval
- `/test/system_state` - System state retrieval

## 📈 Benefits

### **Comprehensive Coverage**
- Tests cover all major annotation workflows
- Validates both happy path and error scenarios
- Ensures system robustness and reliability

### **CI/CD Ready**
- Mocked tests run quickly without external dependencies
- Suitable for automated testing pipelines
- Provides immediate feedback on code changes

### **Documentation**
- Tests serve as living documentation of expected behaviors
- Clear examples of how to use the annotation system
- Demonstrates proper error handling patterns

### **Quality Assurance**
- Catches regressions in workflow functionality
- Validates data integrity and persistence
- Ensures proper phase transitions and validation

## 🔮 Future Enhancements

### **Potential Additional Tests**
- Performance testing for large datasets
- Load testing for concurrent users
- Security testing for user authentication
- Accessibility testing for UI components
- Browser compatibility testing

### **Test Improvements**
- Add more granular unit tests
- Implement property-based testing
- Add performance benchmarks
- Create visual regression tests
- Implement automated test reporting

## 📝 Maintenance

### **Adding New Tests**
1. Follow the existing pattern of integration + mocked tests
2. Use descriptive test names that explain the scenario
3. Include proper error handling and timeouts
4. Add documentation for new test categories

### **Updating Tests**
1. Update both integration and mocked tests together
2. Maintain backward compatibility where possible
3. Update documentation when test behavior changes
4. Run full test suite before committing changes

### **Test Data Management**
- Use realistic but minimal test data
- Clean up test data after each test
- Avoid hardcoding sensitive information
- Use environment variables for configuration

This comprehensive test suite ensures the Potato annotation platform is robust, reliable, and ready for production use across various annotation workflows and scenarios.
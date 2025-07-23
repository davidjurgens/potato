# Annotation Workflow Integration Tests

This document describes the comprehensive annotation workflow tests that demonstrate complete annotation workflows using the new test routes.

## Overview

The `tests/test_annotation_workflow_integration.py` file contains tests that verify the entire annotation system from data creation to completion. These tests use the new test routes (`/test/*`) to create users, submit annotations, and verify system state.

## Test Structure

### TestAnnotationWorkflowIntegration

Real integration tests that require a running server:

1. **`test_complete_annotation_workflow`** - Complete workflow demonstration:
   - Creates 2 users in ANNOTATION phase
   - Submits annotations from both users
   - Verifies all items have annotations
   - Checks system state throughout the process

2. **`test_annotation_workflow_with_verification`** - Detailed step-by-step verification:
   - Tests each step of the annotation process
   - Verifies user states and assignments
   - Checks annotation recording

3. **`test_annotation_workflow_error_handling`** - Error scenario testing:
   - Tests error responses when debug mode is disabled
   - Verifies proper error handling for invalid requests

4. **`test_annotation_workflow_performance`** - Performance testing:
   - Creates multiple users (5) simultaneously
   - Submits many annotations quickly
   - Measures performance metrics

### TestAnnotationWorkflowMocked

Mocked tests that don't require a server:

1. **`test_mocked_complete_workflow`** - Complete workflow with mocked responses:
   - Tests the same workflow as the real integration test
   - Uses mocked HTTP responses
   - Verifies all assertions pass

2. **`test_mocked_workflow_error_scenarios`** - Error scenarios with mocked responses:
   - Tests error handling with mocked error responses
   - Verifies proper error message handling

## Usage Examples

### Running Mocked Tests (No Server Required)

```bash
# Run all mocked tests
python -m pytest tests/test_annotation_workflow_integration.py::TestAnnotationWorkflowMocked -v

# Run specific mocked test
python -m pytest tests/test_annotation_workflow_integration.py::TestAnnotationWorkflowMocked::test_mocked_complete_workflow -v
```

### Running Integration Tests (Server Required)

```bash
# Start the server first
python -m potato.server --config config/examples/simple-slider.yaml --debug

# In another terminal, run integration tests
python -m pytest tests/test_annotation_workflow_integration.py::TestAnnotationWorkflowIntegration -v

# Run specific integration test
python -m pytest tests/test_annotation_workflow_integration.py::TestAnnotationWorkflowIntegration::test_complete_annotation_workflow -v
```

## Test Workflow Steps

The complete annotation workflow test demonstrates:

1. **System Reset** - Clears all existing data
2. **User Creation** - Creates 2 annotators with assignments
3. **State Verification** - Checks initial system and user states
4. **Annotation Submission** - Both users submit annotations for their assigned items
5. **Final Verification** - Verifies all items have the expected number of annotations

## Expected Results

### Successful Workflow

- 2 users created successfully
- Each user assigned 5 items (total 10 items)
- Each item receives 2 annotations (one from each user)
- System state shows correct totals
- All verification steps pass

### Error Scenarios

- Proper error responses when debug mode is disabled
- Graceful handling of invalid requests
- Clear error messages for debugging

## Integration with Existing Tests

These workflow tests complement the existing test suite:

- **Config validation tests** - Ensure proper configuration
- **Server integration tests** - Verify server functionality
- **Backend state tests** - Check state management
- **Workflow tests** - Demonstrate complete user workflows

## Debugging

### Common Issues

1. **Server not running** - Tests will skip with "Server not running" message
2. **Debug mode disabled** - User creation routes return 403 errors
3. **Timeout issues** - Increase timeout values in test configuration
4. **Data conflicts** - Use `/test/reset` to clear existing data

### Debug Output

Tests include detailed print statements showing:
- User creation status
- Assignment counts
- Annotation submission results
- System state summaries
- Performance metrics

## Extending the Tests

To add new workflow tests:

1. **Add to TestAnnotationWorkflowIntegration** for real server tests
2. **Add to TestAnnotationWorkflowMocked** for mocked tests
3. **Use existing patterns** for consistency
4. **Include proper error handling** and timeouts
5. **Add documentation** for new test scenarios

## Related Files

- `tests/test_annotation_workflow_integration.py` - Main test file
- `docs/test_routes.md` - Documentation for test routes
- `potato/routes.py` - Test route implementations
- `tests/test_backend_state.py` - Backend state tests
# Testing Documentation Summary

An index of the testing documentation, and the shortest path into it for
someone who has not written a Potato test before.

## Where the documentation is

### Main documentation

1. **[Testing Strategy](TESTING_STRATEGY.md)** - Overall testing approach and principles
2. **[Main README](README.md)** - Overview of all test types and how to run them
3. **[Server Test Guide](server/README.md)** - Complete guide to server integration testing
4. **[Selenium Test Guide](selenium/README.md)** - Complete guide to frontend testing

### Quick references

1. **[Server Quick Reference](server/QUICK_REFERENCE.md)** - Common patterns and code snippets for server tests
2. **[Server Test Template](server/test_template.py)** - Template for creating new server tests

### Test infrastructure

1. **[FlaskTestServer](helpers/flask_test_setup.py)** - Core server testing infrastructure
2. **[BaseSeleniumTest](selenium/test_base.py)** - Core Selenium testing infrastructure

## Quick Start Guide

### For New Developers

1. **Start with the Testing Strategy**: Read `TESTING_STRATEGY.md` to understand the overall approach
2. **Review the Main README**: Check `README.md` for an overview of all test types
3. **Choose Your Test Type**:
   - **Server Tests**: Use `server/README.md` and `server/QUICK_REFERENCE.md`
   - **Selenium Tests**: Use `selenium/README.md`
   - **Unit Tests**: Use standard pytest patterns

### For Creating New Tests

#### Server Tests
1. **Copy the template**: `cp tests/server/test_template.py tests/server/test_my_feature.py`
2. **Follow the patterns**: See `tests/server/QUICK_REFERENCE.md`
3. **Use FlaskTestServer**: Always use the FlaskTestServer class
4. **Test production mode**: Server runs in production mode (`debug=False`)

#### Selenium Tests
1. **Inherit from BaseSeleniumTest**: Automatic user registration/login
2. **Follow UI patterns**: See `tests/selenium/README.md`
3. **Use headless mode**: Chrome runs in headless mode for CI compatibility

### For Running Tests

```bash
# All tests
pytest

# Server tests only
pytest tests/server/ -v

# Selenium tests only
pytest tests/selenium/ -v

# Unit tests only
pytest tests/unit/ -v

# Specific test file
pytest tests/server/test_backend_state.py -v

# With debug output
pytest tests/server/ -v -s
```

## Key Concepts

### Testing Pyramid
- **Unit Tests** (base): Fast, isolated, high coverage
- **Integration Tests** (middle): Medium speed, server endpoints
- **E2E Tests** (top): Slow, complete user workflows

### Test Infrastructure
- **FlaskTestServer**: Real Flask server for integration testing
- **BaseSeleniumTest**: Complete browser environment for UI testing
- **Production Mode**: Tests run against production server (not debug)

### Authentication
- **Server Tests**: Use production endpoints for user registration/login
- **Selenium Tests**: Automatic user registration/login via BaseSeleniumTest
- **Admin Endpoints**: FlaskTestServer automatically adds admin API key

## Common Patterns

### Server Test Pattern
```python
@pytest.fixture(scope="class", autouse=True)
def flask_server(self, request):
    """Create Flask test server."""
    # Create test data and config
    # Start server
    yield server
    # Cleanup

def test_feature(self, flask_server):
    """Test feature functionality."""
    # Test using production endpoints
    # Verify results
```

### Selenium Test Pattern
```python
class TestMyFeature(BaseSeleniumTest):
    """Test my feature."""

    def test_feature(self):
        """Test feature functionality."""
        # User is already authenticated
        # Navigate and interact
        # Verify results
```

## Conventions

Group tests for one feature in one file and name them after the behavior they
check, not the function they call, so a failure report reads as a sentence.
Write down in the docstring what the test is setting up, because the setup is
usually the part a later reader cannot reconstruct.

Every test has to pass when run alone and when run in any order, which in
practice means clearing the singletons and cleaning up whatever the test
created. Use data that looks like real data but is small enough to reason
about, and cover the failure path as well as the success path.

Keep unit tests under a second. Give integration tests a timeout long enough
for a real server start but short enough that a hang fails rather than stalls
the suite, give every server test class its own port, and run Chrome headless
so the browser tests work in CI.

## Troubleshooting

### Common Issues
1. **Port conflicts**: Use unique ports for each test class
2. **File paths**: Ensure data files use absolute paths or are relative to project root
3. **Authentication**: Check that admin API key is being sent for admin endpoints
4. **Session management**: Ensure proper session handling for user endpoints

### Debug Mode
```bash
# Run with verbose output
pytest tests/server/ -v -s

# Add debug prints
print(f"Server URL: {flask_server.base_url}")
print(f"Response status: {response.status_code}")
```

## Integration with CI/CD

### Test Execution Strategy
1. **Unit Tests**: Run first for quick feedback
2. **Integration Tests**: Run after unit tests pass
3. **E2E Tests**: Run last, since they are the slowest and the most brittle

### CI/CD Pipeline
```yaml
stages:
  - unit_tests      # Fast unit tests
  - integration     # Server integration tests
  - e2e_tests       # Selenium tests (optional)
  - coverage        # Coverage reporting
```

## Coverage Goals

- **Unit Tests**: 80%+ line coverage
- **Integration Tests**: 60%+ endpoint coverage
- **E2E Tests**: 20%+ user workflow coverage

## Future Enhancements

### Planned Improvements
1. **Parallel Test Execution**: Enhanced support for running tests in parallel
2. **Test Data Factories**: Reusable test data generation
3. **Performance Testing**: Load testing and performance benchmarks
4. **Visual Regression Testing**: Automated visual testing
5. **API Contract Testing**: Automated API contract validation

### Monitoring and Metrics
1. **Test Execution Times**: Track and optimize test performance
2. **Flaky Test Detection**: Identify and fix unreliable tests
3. **Coverage Trends**: Monitor coverage over time
4. **Test Quality Metrics**: Track test maintainability and reliability

## Getting Help

### Documentation References
- **Server Testing**: `tests/server/README.md`
- **Selenium Testing**: `tests/selenium/README.md`
- **Quick Reference**: `tests/server/QUICK_REFERENCE.md`
- **Test Template**: `tests/server/test_template.py`

### Code Examples
- **Server Tests**: See existing tests in `tests/server/`
- **Selenium Tests**: See existing tests in `tests/selenium/`
- **Unit Tests**: See existing tests in `tests/unit/`

### Infrastructure Code
- **FlaskTestServer**: `tests/helpers/flask_test_setup.py`
- **BaseSeleniumTest**: `tests/selenium/test_base.py`

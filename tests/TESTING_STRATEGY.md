# Potato Testing Strategy

## Overview

The Potato annotation platform uses a comprehensive testing strategy that combines unit tests, integration tests, and end-to-end tests to ensure reliability, maintainability, and confidence in the codebase.

## Testing Pyramid

Our testing approach follows the testing pyramid principle:

```
    /\
   /  \     E2E Tests (Selenium)
  /____\    - Few, slow, expensive
 /      \
/________\   Integration Tests (Server)
- Medium number, medium speed
/          \
/____________\ Unit Tests
- Many, fast, cheap
```

### 1. Unit Tests (Base)
- **Location**: `tests/unit/`
- **Purpose**: Test individual functions and classes in isolation
- **Speed**: Fast (< 1 second per test)
- **Scope**: Single function/class
- **Dependencies**: Mocked external dependencies
- **Coverage**: High (80%+ target)

### 2. Integration Tests (Middle)
- **Location**: `tests/server/`
- **Purpose**: Test Flask server endpoints and workflows
- **Speed**: Medium (1-10 seconds per test)
- **Scope**: HTTP endpoints and server behavior
- **Dependencies**: Real Flask server instance
- **Coverage**: Medium (key workflows and edge cases)

### 3. End-to-End Tests (Top)
- **Location**: `tests/selenium/`
- **Purpose**: Test complete user workflows through the browser
- **Speed**: Slow (10-60 seconds per test)
- **Scope**: Full user journey
- **Dependencies**: Real browser and server
- **Coverage**: Low (critical user paths)

## Test Categories

### Backend Testing

#### Unit Tests (`tests/unit/`)
- **Annotation Type Validation**: Test annotation scheme validation logic
- **Configuration Validation**: Test config file parsing and validation
- **User State Logic**: Test user state management functions
- **Data Processing**: Test data loading and processing functions

#### Server Integration Tests (`tests/server/`)
- **HTTP Endpoints**: Test all Flask routes and endpoints
- **Authentication**: Test user registration, login, and session management
- **Annotation Workflows**: Test complete annotation submission and retrieval
- **State Management**: Test user and item state persistence
- **Error Handling**: Test error scenarios and recovery
- **Assignment Strategies**: Test different item assignment algorithms
- **Multi-Phase Workflows**: Test consent, instructions, and annotation phases

### Frontend Testing

#### Selenium Tests (`tests/selenium/`)
- **User Interface**: Test UI elements and interactions
- **User Workflows**: Test complete user journeys
- **Browser Compatibility**: Test cross-browser behavior
- **Responsive Design**: Test mobile and desktop layouts
- **JavaScript Functionality**: Test client-side features

## Testing Principles

### 1. Test Isolation
- Each test should be independent and not rely on other tests
- Tests should not share state or data
- Use unique identifiers for test data and users
- Clean up resources after each test

### 2. Production-Like Environment
- Server tests run in production mode (`debug=False`)
- Use real Flask server instances, not test clients
- Test against actual HTTP endpoints
- Use real template files and static assets

### 3. Authentication Testing
- Test both authenticated and unauthenticated access
- Use production authentication endpoints
- Test session management and persistence
- Verify proper access control

### 4. Error Handling
- Test both success and failure scenarios
- Verify proper error responses and status codes
- Test edge cases and invalid inputs
- Ensure graceful degradation

### 5. Performance Considerations
- Keep unit tests fast (< 1 second)
- Use appropriate timeouts for integration tests
- Minimize external dependencies
- Use headless mode for browser tests

## Test Infrastructure

### FlaskTestServer Class
The `FlaskTestServer` class provides a complete Flask server environment for integration testing:

- **Production Mode**: Runs server in production mode (`debug=False`)
- **Admin Authentication**: Automatically adds admin API key headers
- **Session Management**: Handles user sessions and authentication
- **Config Management**: Supports both dict and file-based configurations
- **Cleanup**: Proper server shutdown and resource cleanup

### BaseSeleniumTest Class
The `BaseSeleniumTest` class provides a complete browser testing environment:

- **Automatic Setup**: User registration, login, and browser setup
- **Headless Mode**: Chrome runs in headless mode for CI compatibility
- **Session Management**: Maintains user sessions across requests
- **Cleanup**: Proper browser cleanup and resource management

## Test Data Management

### Temporary Data
- Server tests create temporary test data files
- Data is cleaned up after each test
- Use unique identifiers to avoid conflicts
- Test with realistic data sizes and formats

### Configuration Files
- Use test-specific configuration files
- Test various configuration scenarios
- Validate configuration validation logic
- Test error handling for invalid configs

### Mock Data
- Unit tests use mock data and objects
- Mock external dependencies (databases, APIs)
- Use realistic but controlled test data
- Avoid hardcoded test data in production code

## Continuous Integration

### Test Execution Strategy
1. **Unit Tests**: Run first for quick feedback
2. **Integration Tests**: Run after unit tests pass
3. **E2E Tests**: Run last for comprehensive validation

### CI/CD Pipeline
```yaml
# Example CI pipeline
stages:
  - unit_tests      # Fast unit tests
  - integration     # Server integration tests
  - e2e_tests       # Selenium tests (optional)
  - coverage        # Coverage reporting
```

### Parallel Execution
- Unit tests can run in parallel
- Server tests use unique ports to avoid conflicts
- Selenium tests can run in parallel with different browsers

## Coverage Goals

### Code Coverage Targets
- **Unit Tests**: 80%+ line coverage
- **Integration Tests**: 60%+ endpoint coverage
- **E2E Tests**: 20%+ user workflow coverage

### Coverage Types
- **Line Coverage**: Percentage of code lines executed
- **Branch Coverage**: Percentage of code branches executed
- **Function Coverage**: Percentage of functions called
- **Endpoint Coverage**: Percentage of HTTP endpoints tested

## Quality Assurance

### Test Quality Metrics
- **Test Reliability**: Tests should be stable and not flaky
- **Test Maintainability**: Tests should be easy to understand and modify
- **Test Performance**: Tests should run efficiently
- **Test Coverage**: Tests should cover critical functionality

### Code Quality
- **Test Documentation**: All tests should be well-documented
- **Test Naming**: Test names should be descriptive and clear
- **Test Organization**: Tests should be logically organized
- **Test Patterns**: Use consistent patterns across test files

## Best Practices

### Writing Tests
1. **Arrange-Act-Assert**: Use clear test structure
2. **Descriptive Names**: Use descriptive test and function names
3. **Single Responsibility**: Each test should test one thing
4. **Edge Cases**: Test both success and failure scenarios
5. **Realistic Data**: Use realistic but controlled test data

### Test Maintenance
1. **Regular Review**: Review and update tests regularly
2. **Refactoring**: Refactor tests when code changes
3. **Documentation**: Keep test documentation up to date
4. **Performance**: Monitor test performance and optimize

### Debugging Tests
1. **Debug Output**: Use print statements for debugging
2. **Verbose Mode**: Run tests with `-v -s` flags
3. **Isolation**: Run individual tests to isolate issues
4. **Logs**: Check server and browser logs for errors

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

## Conclusion

The Potato testing strategy provides comprehensive coverage across all layers of the application, from individual functions to complete user workflows. This multi-layered approach ensures that the platform is reliable, maintainable, and ready for production use.

By following these testing principles and using the provided infrastructure, developers can confidently add new features and make changes to the codebase while maintaining high quality and reliability.
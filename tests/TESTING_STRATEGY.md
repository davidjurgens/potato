# Potato Testing Strategy

Potato's tests are in three tiers: unit tests under `tests/unit/`, server
integration tests under `tests/server/`, and browser tests under
`tests/selenium/`. Each tier trades speed for realism, and the suite is shaped
so that most of the checking happens in the fast tier.

## Testing pyramid

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
`FlaskTestServer` starts a real Flask server for a test class:

- **Production Mode**: Runs server in production mode (`debug=False`)
- **Admin Authentication**: Automatically adds admin API key headers
- **Session Management**: Handles user sessions and authentication
- **Config Management**: Supports both dict and file-based configurations
- **Cleanup**: Proper server shutdown and resource cleanup

### BaseSeleniumTest Class
`BaseSeleniumTest` sets up the browser and gets a user logged in:

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
3. **E2E Tests**: Run last, since they are the slowest and the most brittle

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

## Writing a test

Structure each test as arrange, act, assert, and let it check one thing, so a
failure names the defect rather than a region of code. Name tests and helpers
after the behavior under test. Cover the failure path alongside the success
path, and use data that resembles real data at a size you can hold in your head.

A flaky test costs more than no test, because it teaches people to re-run
rather than to read. When production code changes, change the tests with it in
the same commit; a test that has drifted from the code it guards is worse than
absent, since it still reports green.

### Debugging a failure

Run the single test in isolation first (`pytest path::Class::test -v -s`), which
separates a real failure from an ordering or port collision. `-s` lets `print`
through. When the failure is in a server or browser test, the server log and the
browser console usually say more than the assertion did.

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

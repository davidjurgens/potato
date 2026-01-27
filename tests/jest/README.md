# Jest Frontend Tests

## Overview

Jest tests in `tests/jest/` verify JavaScript functionality in isolation. These tests run in jsdom (a simulated DOM environment) and are useful for testing:

- Core annotation logic
- DOM manipulation functions
- Data transformation utilities
- Event handling
- State management

## Test Files

| File | Description |
|------|-------------|
| `annotation-functions.test.js` | Core annotation functions (`updateAnnotation`, `whetherNone`, `onlyOne`, validation) |
| `span-manager-simple.test.js` | Span manager functionality (initialization, annotation CRUD, rendering) |
| `interval-rendering-structure.test.js` | DOM structure for interval-based span rendering |

## Setup

### Dependencies

```bash
npm install
```

### Configuration

Jest configuration is in `package.json`:

```json
{
  "jest": {
    "testEnvironment": "jsdom",
    "setupFilesAfterEnv": ["<rootDir>/tests/jest/setup.js"],
    "testMatch": ["**/tests/jest/**/*.test.js"]
  }
}
```

### Setup File (`setup.js`)

The setup file provides:
- Global `fetch` mock
- DOM structure for annotation interface
- Mock `window.config`
- jQuery mock (if needed)
- Helper functions: `resetMocks()`, `createMockResponse()`, `simulateTextSelection()`

## Running Tests

```bash
# Run all Jest tests
npm run test:jest

# Run with watch mode (re-run on file changes)
npm run test:jest:watch

# Run with coverage report
npm run test:jest:coverage

# Run specific test file
npx jest tests/jest/annotation-functions.test.js
```

## Writing Jest Tests

### Basic Pattern

```javascript
/**
 * Tests for [module/function name]
 */

describe('FunctionName', () => {
  beforeEach(() => {
    // Setup before each test
    resetMocks();
    // Reset DOM state
  });

  afterEach(() => {
    // Cleanup after each test
    fetch.mockClear();
  });

  test('should do something', () => {
    // Arrange
    const input = 'test';

    // Act
    const result = myFunction(input);

    // Assert
    expect(result).toBe('expected');
  });
});
```

### Mocking Fetch

```javascript
test('should handle API call', async () => {
  // Mock successful response
  global.fetch.mockImplementation(() =>
    Promise.resolve({
      ok: true,
      json: () => Promise.resolve({ data: 'test' })
    })
  );

  await myAsyncFunction();

  expect(fetch).toHaveBeenCalledWith('/api/endpoint', expect.any(Object));
});

test('should handle API error', async () => {
  // Mock error response
  global.fetch.mockImplementation(() =>
    Promise.reject(new Error('Network error'))
  );

  await myAsyncFunction();

  // Verify error handling
  expect(console.error).toHaveBeenCalled();
});
```

### DOM Manipulation Tests

```javascript
test('should update DOM element', () => {
  // Get element from setup.js DOM
  const element = document.getElementById('annotation-forms');

  // Manipulate
  element.innerHTML = '<input type="checkbox" value="test" />';

  // Verify
  const checkbox = element.querySelector('input[type="checkbox"]');
  expect(checkbox).toBeTruthy();
  expect(checkbox.value).toBe('test');
});
```

### Testing Event Handlers

```javascript
test('should handle click event', () => {
  const checkbox = document.createElement('input');
  checkbox.type = 'checkbox';
  checkbox.className = 'test-class';
  document.getElementById('annotation-forms').appendChild(checkbox);

  // Simulate click
  checkbox.click();

  // Verify state
  expect(checkbox.checked).toBe(true);
});
```

## jsdom Limitations

Jest uses jsdom, which has limitations compared to a real browser:

### No Layout Engine

```javascript
// In jsdom, getClientRects() returns empty array
const range = document.createRange();
range.setStart(textNode, 0);
range.setEnd(textNode, 5);
const rects = range.getClientRects(); // Returns empty DOMRectList

// Solution: Test the logic, not the layout
test('handles empty rects gracefully', () => {
  const rects = getCharRangeBoundingRect(element, 0, 5);
  expect(Array.isArray(rects)).toBe(true);
  // Don't assert on length - jsdom returns []
});
```

### No CSS Application

```javascript
// External CSS doesn't apply in jsdom
const element = document.getElementById('my-element');
const style = window.getComputedStyle(element);
// style properties may be empty

// Solution: Test inline styles or don't test CSS
element.style.backgroundColor = 'red';
expect(element.style.backgroundColor).toBe('red');
```

### No Visual Rendering

```javascript
// Things that won't work:
// - Screenshots
// - Element positions (getBoundingClientRect returns 0s)
// - Scroll behavior
// - Viewport testing
```

## Test Categories

### 1. Annotation Functions (`annotation-functions.test.js`)

Tests core annotation logic:

- `updateAnnotation()` - Updates annotation state
- `whetherNone()` - "None of the above" checkbox logic
- `onlyOne()` - Exclusive selection logic
- `escapeHtml()` - XSS prevention
- `validateRequiredFields()` - Form validation

### 2. Span Manager (`span-manager-simple.test.js`)

Tests span annotation functionality:

- Initialization and color loading
- Annotation loading and saving
- Span creation and deletion
- Label selection
- Span rendering with boundary algorithm

### 3. DOM Structure (`interval-rendering-structure.test.js`)

Tests the two-layer span rendering structure:

- Text content layer (z-index: 1)
- Span overlays layer (z-index: 2)
- Pointer events configuration
- Overlay element structure

## Mocking Patterns

### Mock SpanManager

```javascript
class MockSpanManager {
  constructor() {
    this.currentInstanceId = null;
    this.annotations = { spans: [] };
    this.colors = {};
    this.selectedLabel = null;
  }

  async initialize() {
    // Mock initialization
  }

  async loadAnnotations(instanceId) {
    // Mock loading
  }
}
```

### Mock Fetch Response

```javascript
global.fetch.mockImplementation(() =>
  Promise.resolve({
    ok: true,
    status: 200,
    json: () => Promise.resolve({ spans: [] })
  })
);
```

### Mock Selection

```javascript
window.getSelection = jest.fn(() => ({
  rangeCount: 1,
  getRangeAt: jest.fn(() => ({
    startOffset: 0,
    endOffset: 5
  })),
  toString: () => 'hello'
}));
```

## Best Practices

1. **Reset State**: Always reset mocks and DOM between tests
2. **Mock External Dependencies**: Don't rely on actual API calls
3. **Test Logic, Not Layout**: jsdom doesn't have a layout engine
4. **Use Helper Functions**: Leverage `setup.js` helpers
5. **Document Limitations**: Note jsdom limitations in test comments
6. **Keep Tests Fast**: Jest tests should run in <1 second total

## Integration with CI

```yaml
# Example GitHub Actions
- name: Run Jest tests
  run: npm run test:jest

- name: Run Jest with coverage
  run: npm run test:jest:coverage
```

## Coverage

Run with coverage to identify untested code:

```bash
npm run test:jest:coverage
```

Coverage reports are generated for files in `potato/static/**/*.js`.

/**
 * Jest setup file for frontend JavaScript testing
 * This file runs before each test and sets up the test environment
 */

// Mock fetch globally
global.fetch = jest.fn();

// Mock DOM elements that might not exist in jsdom
document.body.innerHTML = `
  <div id="instance-text" class="p-3 border rounded" style="background-color: var(--light-bg); min-height: 100px; position: relative;">
    <!-- Text content layer (for selection) -->
    <div id="text-content" class="text-content" style="position: relative; z-index: 1; pointer-events: auto;">
      I am absolutely thrilled about the new technology announcement! This is going to revolutionize how we work. The possibilities are endless and I can't wait to see what the future holds.
    </div>
    <!-- Span overlays layer -->
    <div id="span-overlays" class="span-overlays" style="position: absolute; top: 0; left: 0; right: 0; bottom: 0; z-index: 2; pointer-events: none;">
      <!-- Spans will be rendered here as overlays -->
    </div>
  </div>
  <div id="annotation-forms"></div>
  <div id="progress-counter">0/10</div>
  <div id="loading-state" style="display: none;">Loading...</div>
  <div id="error-state" style="display: none;">
    <div id="error-message-text"></div>
  </div>
  <div id="main-content">
    <div id="status"></div>
  </div>
  <input id="instance_id" type="hidden" value="1" />
  <button id="prev-btn">Previous</button>
  <button id="next-btn">Next</button>
  <button id="go-to-btn">Go To</button>
  <input id="go_to" type="number" />
  <div id="span-label-selector" style="display: none;">
    <div id="label-buttons"></div>
  </div>
`;

// Mock window.config
window.config = {
  username: 'test_user',
  api_key: 'test_api_key'
};

// Mock jQuery if needed
if (typeof $ === 'undefined') {
  global.$ = jest.fn((selector) => {
    const element = document.querySelector(selector);
    return {
      closest: jest.fn(() => element),
      text: jest.fn(() => element ? element.textContent : ''),
      html: jest.fn(() => element ? element.innerHTML : ''),
      val: jest.fn(() => element ? element.value : ''),
      attr: jest.fn(() => element ? element.getAttribute : ''),
      on: jest.fn(),
      off: jest.fn(),
      trigger: jest.fn(),
      length: element ? 1 : 0,
      [0]: element
    };
  });
}

// Mock console methods to reduce noise in tests
global.console = {
  ...console,
  log: jest.fn(),
  warn: jest.fn(),
  error: jest.fn(),
  debug: jest.fn()
};

// Helper function to reset mocks between tests
global.resetMocks = () => {
  fetch.mockClear();
  console.log.mockClear();
  console.warn.mockClear();
  console.error.mockClear();
  console.debug.mockClear();
};

// Helper function to create a mock response
global.createMockResponse = (data, status = 200) => {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status: status,
    json: () => Promise.resolve(data),
    text: () => Promise.resolve(JSON.stringify(data))
  });
};

// Helper function to simulate user selection
global.simulateTextSelection = (start, end) => {
  const textElement = document.getElementById('instance-text');
  const textNode = textElement.firstChild;

  const range = document.createRange();
  range.setStart(textNode, start);
  range.setEnd(textNode, end);

  const selection = window.getSelection();
  selection.removeAllRanges();
  selection.addRange(range);

  return selection.toString();
};

// Helper function to clear selection
global.clearSelection = () => {
  window.getSelection().removeAllRanges();
};

// Mock window.getSelection
Object.defineProperty(window, 'getSelection', {
  writable: true,
  value: jest.fn(() => ({
    rangeCount: 0,
    getRangeAt: jest.fn(),
    removeAllRanges: jest.fn(),
    addRange: jest.fn(),
    toString: jest.fn(() => ''),
    isCollapsed: true
  }))
});

// Mock document.createRange
document.createRange = jest.fn(() => ({
  setStart: jest.fn(),
  setEnd: jest.fn(),
  getBoundingClientRect: jest.fn(() => ({
    left: 0,
    top: 0,
    right: 100,
    bottom: 20
  }))
}));

// Mock window.getSelection
window.getSelection = jest.fn(() => ({
  rangeCount: 0,
  getRangeAt: jest.fn(),
  removeAllRanges: jest.fn(),
  addRange: jest.fn(),
  toString: jest.fn(() => ''),
  isCollapsed: true
}));

// Setup before each test
beforeEach(() => {
  resetMocks();

  // Reset DOM state
  const textElement = document.getElementById('instance-text');
  const textContent = document.getElementById('text-content');
  const spanOverlays = document.getElementById('span-overlays');

  if (textElement && textContent) {
    textContent.innerHTML = 'I am absolutely thrilled about the new technology announcement! This is going to revolutionize how we work. The possibilities are endless and I can\'t wait to see what the future holds.';
  }

  if (spanOverlays) {
    spanOverlays.innerHTML = '';
  }

  // Clear any existing spans using parentNode.removeChild
  const spans = document.querySelectorAll('.span-highlight');
  spans.forEach(span => {
    if (span.parentNode) {
      span.parentNode.removeChild(span);
    }
  });

  // Reset global variables
  if (window.spanManager) {
    window.spanManager.annotations = {spans: []};
    window.spanManager.currentInstanceId = null;
  }
});

// Cleanup after each test
afterEach(() => {
  resetMocks();
});
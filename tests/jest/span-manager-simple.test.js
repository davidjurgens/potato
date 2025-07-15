/**
 * Jest tests for span manager functionality
 * Tests the core span management logic in isolation
 */

// Mock SpanManager class
class MockSpanManager {
  constructor() {
    this.currentInstanceId = null;
    this.annotations = {spans: []};
    this.colors = {};
    this.selectedLabel = null;
    this.isInitialized = false;
    this.retryCount = 0;
    this.maxRetries = 3;
  }

  async initialize() {
    try {
      await this.loadColors();
      this.isInitialized = true;
    } catch (error) {
      if (this.retryCount < this.maxRetries) {
        this.retryCount++;
        setTimeout(() => this.initialize(), 1000);
      }
    }
  }

  async loadColors() {
    try {
      const response = await fetch('/api/colors');
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      this.colors = await response.json();
    } catch (error) {
      // Fallback colors
      this.colors = {
        'positive': '#d4edda',
        'negative': '#f8d7da',
        'neutral': '#d1ecf1',
        'span': '#ffeaa7'
      };
    }
  }

  async loadAnnotations(instanceId) {
    if (!instanceId) return;

    try {
      const response = await fetch(`/api/spans/${instanceId}`);

      if (!response.ok) {
        if (response.status === 404) {
          this.annotations = {spans: []};
          return;
        }
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      this.annotations = await response.json();
      this.currentInstanceId = instanceId;
    } catch (error) {
      this.annotations = {spans: []};
    }
  }

  async createAnnotation(spanText, start, end, label) {
    if (!this.currentInstanceId) {
      return false;
    }

    try {
      const response = await fetch('/updateinstance', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          type: 'span',
          schema: 'sentiment',
          state: [
            {
              name: label,
              start: start,
              end: end,
              title: label,
              value: spanText
            }
          ],
          instance_id: this.currentInstanceId
        })
      });

      if (response.ok) {
        await this.loadAnnotations(this.currentInstanceId);
        return true;
      }
      return false;
    } catch (error) {
      return false;
    }
  }

  async deleteSpan(annotationId) {
    if (!this.currentInstanceId) {
      return false;
    }

    try {
      const spanToDelete = this.annotations.spans.find(span => span.id === annotationId);
      if (!spanToDelete) {
        return false;
      }

      const response = await fetch('/updateinstance', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          type: 'span',
          schema: 'sentiment',
          state: [
            {
              name: spanToDelete.label,
              start: spanToDelete.start,
              end: spanToDelete.end,
              title: spanToDelete.label,
              value: null
            }
          ],
          instance_id: this.currentInstanceId
        })
      });

      if (response.ok) {
        await this.loadAnnotations(this.currentInstanceId);
        return true;
      }
      return false;
    } catch (error) {
      return false;
    }
  }

  selectLabel(label) {
    this.selectedLabel = label;
  }

  getAnnotations() {
    return this.annotations;
  }

  getSpans() {
    if (!this.annotations || !this.annotations.spans) {
      return [];
    }
    return this.annotations.spans;
  }

  clearAnnotations() {
    this.annotations = {spans: []};
  }

  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  renderSpans() {
    const textContainer = document.getElementById('instance-text');
    if (!textContainer || !this.annotations.spans || this.annotations.spans.length === 0) {
      return;
    }

    const originalText = textContainer.textContent || textContainer.innerText;
    if (!originalText) {
      return;
    }

    // Create boundary list
    const boundaries = [];
    this.annotations.spans.forEach(annotation => {
      boundaries.push({
        position: annotation.start,
        type: 'start',
        annotation: annotation
      });
      boundaries.push({
        position: annotation.end,
        type: 'end',
        annotation: annotation
      });
    });

    // Sort boundaries by position
    boundaries.sort((a, b) => a.position - b.position);

    // Build HTML using boundary algorithm
    let html = '';
    let currentPos = 0;
    let openSpans = [];

    boundaries.forEach(boundary => {
      // Add text before this boundary
      if (boundary.position > currentPos) {
        html += this.escapeHtml(originalText.substring(currentPos, boundary.position));
      }

      if (boundary.type === 'start') {
        // Open a new span
        const backgroundColor = this.colors[boundary.annotation.label] || '#f0f0f0';
        const spanHtml = `<span class="span-highlight"
            data-annotation-id="${boundary.annotation.id}"
            data-label="${boundary.annotation.label}"
            style="background-color: ${backgroundColor}">
            <span class="span-delete">×</span>
            <span class="span-label">${boundary.annotation.label}</span>`;
        html += spanHtml;
        openSpans.push(boundary.annotation);
      } else {
        // Close a span
        html += '</span>';
        const index = openSpans.findIndex(span => span.id === boundary.annotation.id);
        if (index !== -1) {
          openSpans.splice(index, 1);
        }
      }

      currentPos = boundary.position;
    });

    // Add remaining text
    if (currentPos < originalText.length) {
      html += this.escapeHtml(originalText.substring(currentPos));
    }

    // Close any remaining open spans
    openSpans.forEach(() => {
      html += '</span>';
    });

    // Update container
    textContainer.innerHTML = html;
  }
}

describe('SpanManager', () => {
  let spanManager;

  beforeEach(() => {
    spanManager = new MockSpanManager();
    global.fetch.mockClear();
    // Mock fetch responses
    global.fetch.mockImplementation(() =>
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          'positive': '#d4edda',
          'negative': '#f8d7da',
          'neutral': '#d1ecf1'
        })
      })
    );
  });

  afterEach(() => {
    if (window.spanManager) {
      delete window.spanManager;
    }
    global.fetch.mockClear();
  });

  describe('Initialization', () => {
    test('should initialize with default values', () => {
      expect(spanManager.currentInstanceId).toBeNull();
      expect(spanManager.annotations).toEqual({spans: []});
      expect(spanManager.colors).toEqual({});
      expect(spanManager.selectedLabel).toBeNull();
      expect(spanManager.isInitialized).toBe(false);
    });

    test('should initialize successfully', async () => {
      await spanManager.initialize();

      expect(spanManager.isInitialized).toBe(true);
      expect(spanManager.colors).toEqual({
        'positive': '#d4edda',
        'negative': '#f8d7da',
        'neutral': '#d1ecf1'
      });
    });

    test('should use fallback colors on API failure', async () => {
      global.fetch.mockImplementation(() =>
        Promise.reject(new Error('API error'))
      );

      await spanManager.initialize();

      expect(spanManager.isInitialized).toBe(true);
      expect(spanManager.colors).toEqual({
        'positive': '#d4edda',
        'negative': '#f8d7da',
        'neutral': '#d1ecf1',
        'span': '#ffeaa7'
      });
    });
  });

  describe('Annotation Loading', () => {
    test('should load annotations successfully', async () => {
      const mockAnnotations = {
        spans: [
          {
            id: '1',
            label: 'positive',
            start: 0,
            end: 10,
            schema: 'sentiment'
          }
        ]
      };

      global.fetch.mockImplementation(() =>
        Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockAnnotations)
        })
      );

      await spanManager.loadAnnotations('1');

      expect(spanManager.currentInstanceId).toBe('1');
      expect(spanManager.annotations).toEqual(mockAnnotations);
    });

    test('should handle 404 (no annotations) gracefully', async () => {
      global.fetch.mockImplementation(() =>
        Promise.resolve({
          ok: false,
          status: 404
        })
      );

      await spanManager.loadAnnotations('1');

      expect(spanManager.annotations).toEqual({spans: []});
    });

    test('should handle API errors gracefully', async () => {
      global.fetch.mockImplementation(() =>
        Promise.reject(new Error('API error'))
      );

      await spanManager.loadAnnotations('1');

      expect(spanManager.annotations).toEqual({spans: []});
    });
  });

  describe('Span Creation', () => {
    beforeEach(async () => {
      await spanManager.initialize();
      spanManager.currentInstanceId = '1';
      global.fetch.mockClear(); // Reset fetch after initialization
    });

    test('should create span annotation successfully', async () => {
      global.fetch.mockImplementation(() =>
        Promise.resolve({
          ok: true,
          json: () => Promise.resolve({success: true})
        })
      );

      const result = await spanManager.createAnnotation('test text', 0, 9, 'positive');

      expect(result).toBe(true);
      expect(global.fetch).toHaveBeenCalledWith('/updateinstance', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          type: 'span',
          schema: 'sentiment',
          state: [
            {
              name: 'positive',
              start: 0,
              end: 9,
              title: 'positive',
              value: 'test text'
            }
          ],
          instance_id: '1'
        })
      });
    });

    test('should require instance ID for span creation', async () => {
      spanManager.currentInstanceId = null;
      global.fetch.mockClear(); // Reset fetch after initialization

      const result = await spanManager.createAnnotation('test text', 0, 9, 'positive');

      expect(result).toBe(false);
      expect(global.fetch).not.toHaveBeenCalled();
    });
  });

  describe('Span Deletion', () => {
    beforeEach(async () => {
      await spanManager.initialize();
      spanManager.currentInstanceId = '1';
      spanManager.annotations = {
        spans: [
          {
            id: '1',
            label: 'positive',
            start: 0,
            end: 10,
            schema: 'sentiment'
          }
        ]
      };
      global.fetch.mockClear(); // Reset fetch after initialization
    });

    test('should delete span annotation successfully', async () => {
      global.fetch.mockImplementation(() =>
        Promise.resolve({
          ok: true,
          json: () => Promise.resolve({success: true})
        })
      );

      const result = await spanManager.deleteSpan('1');

      expect(result).toBe(true);
      expect(global.fetch).toHaveBeenCalledWith('/updateinstance', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          type: 'span',
          schema: 'sentiment',
          state: [
            {
              name: 'positive',
              start: 0,
              end: 10,
              title: 'positive',
              value: null
            }
          ],
          instance_id: '1'
        })
      });
    });

    test('should handle span not found', async () => {
      global.fetch.mockClear(); // Reset fetch after initialization
      const result = await spanManager.deleteSpan('nonexistent');

      expect(result).toBe(false);
      expect(global.fetch).not.toHaveBeenCalled();
    });
  });

  describe('Utility Methods', () => {
    test('should escape HTML correctly', () => {
      const htmlString = '<script>alert("xss")</script>';
      const escaped = spanManager.escapeHtml(htmlString);

      expect(escaped).toBe('&lt;script&gt;alert("xss")&lt;/script&gt;');
    });

    test('should get annotations correctly', () => {
      spanManager.annotations = {spans: [{id: '1', label: 'positive'}]};

      const annotations = spanManager.getAnnotations();

      expect(annotations).toEqual({spans: [{id: '1', label: 'positive'}]});
    });

    test('should get spans correctly', () => {
      spanManager.annotations = {spans: [{id: '1', label: 'positive'}]};

      const spans = spanManager.getSpans();

      expect(spans).toEqual([{id: '1', label: 'positive'}]);
    });

    test('should return empty array when no spans', () => {
      spanManager.annotations = {spans: []};

      const spans = spanManager.getSpans();

      expect(spans).toEqual([]);
    });

    test('should clear annotations', () => {
      spanManager.annotations = {spans: [{id: '1', label: 'positive'}]};

      spanManager.clearAnnotations();

      expect(spanManager.annotations).toEqual({spans: []});
    });
  });

  describe('Label Selection', () => {
    test('should select label correctly', () => {
      spanManager.selectLabel('positive');

      expect(spanManager.selectedLabel).toBe('positive');
    });
  });

  describe('Span Rendering', () => {
    beforeEach(async () => {
      await spanManager.initialize();

      // Setup DOM
      document.body.innerHTML = `
        <div id="instance-text">I am absolutely thrilled about the new technology.</div>
      `;
    });

    test('should render spans using boundary algorithm', () => {
      spanManager.annotations = {
        spans: [
          {
            id: '1',
            label: 'positive',
            start: 0,
            end: 10,
            schema: 'sentiment'
          }
        ]
      };

      spanManager.renderSpans();

      const textContainer = document.getElementById('instance-text');
      const spanElements = textContainer.querySelectorAll('.span-highlight');

      expect(spanElements.length).toBe(1);
      expect(spanElements[0].getAttribute('data-label')).toBe('positive');
      expect(spanElements[0].getAttribute('data-annotation-id')).toBe('1');
    });

    test('should handle overlapping spans', () => {
      spanManager.annotations = {
        spans: [
          {
            id: '1',
            label: 'positive',
            start: 0,
            end: 10,
            schema: 'sentiment'
          },
          {
            id: '2',
            label: 'negative',
            start: 5,
            end: 15,
            schema: 'sentiment'
          }
        ]
      };

      spanManager.renderSpans();

      const textContainer = document.getElementById('instance-text');
      const spanElements = textContainer.querySelectorAll('.span-highlight');

      expect(spanElements.length).toBe(2);
    });

    test('should not render when no spans', () => {
      spanManager.annotations = {spans: []};

      spanManager.renderSpans();

      const textContainer = document.getElementById('instance-text');
      const spanElements = textContainer.querySelectorAll('.span-highlight');

      expect(spanElements.length).toBe(0);
      expect(textContainer.textContent).toContain('I am absolutely thrilled');
    });
  });
});
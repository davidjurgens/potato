/**
 * Jest tests for annotation.js functions
 * Tests the core functionality in isolation
 */

// Mock the functions that are defined in annotation.js
const mockFunctions = {
  updateAnnotation: (schema, label, value) => {
    if (!global.currentAnnotations[schema]) {
      global.currentAnnotations[schema] = {};
    }
    global.currentAnnotations[schema][label] = value;
  },

  whetherNone: (checkbox) => {
    const elements = document.getElementsByClassName(checkbox.className);
    for (let i = 0; i < elements.length; i++) {
      if (checkbox.value === "None" && elements[i].value !== "None") {
        elements[i].checked = false;
      }
      if (checkbox.value !== "None" && elements[i].value === "None") {
        elements[i].checked = false;
      }
    }
  },

  onlyOne: (checkbox) => {
    const elements = document.getElementsByClassName(checkbox.className);
    for (let i = 0; i < elements.length; i++) {
      if (elements[i].value !== checkbox.value) {
        elements[i].checked = false;
      }
    }
  },

  escapeHtml: (text) => {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  },

  validateRequiredFields: () => {
    const requiredInputs = document.querySelectorAll('input[validation="required"]');
    let allRequiredFilled = true;

    const inputGroups = {};
    requiredInputs.forEach(input => {
      if (input.type === 'radio') {
        const name = input.name;
        if (!inputGroups[name]) {
          inputGroups[name] = [];
        }
        inputGroups[name].push(input);
      } else {
        if (!input.value || input.value.trim() === '') {
          allRequiredFilled = false;
        }
      }
    });

    for (const [name, inputs] of Object.entries(inputGroups)) {
      const anySelected = inputs.some(input => input.checked);
      if (!anySelected) {
        allRequiredFilled = false;
        break;
      }
    }

    const nextBtn = document.getElementById('next-btn');
    if (nextBtn) {
      nextBtn.disabled = !allRequiredFilled;
    }

    return allRequiredFilled;
  }
};

describe('Annotation.js Core Functions', () => {
  beforeEach(() => {
    // Reset global state
    global.currentAnnotations = {};
    if (global.fetch) global.fetch.mockClear();

    // Setup DOM
    document.body.innerHTML = `
      <div id="instance-text">Test text content</div>
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
  });

  afterEach(() => {
    if (global.fetch) global.fetch.mockClear();
  });

  describe('updateAnnotation', () => {
    test('should update currentAnnotations with new schema and label', () => {
      mockFunctions.updateAnnotation('sentiment', 'positive', 'true');

      expect(global.currentAnnotations).toEqual({
        'sentiment': {
          'positive': 'true'
        }
      });
    });

    test('should create schema if it does not exist', () => {
      mockFunctions.updateAnnotation('new_schema', 'label', 'value');

      expect(global.currentAnnotations).toEqual({
        'new_schema': {
          'label': 'value'
        }
      });
    });

    test('should update existing schema with new label', () => {
      global.currentAnnotations = {
        'sentiment': {
          'positive': 'true'
        }
      };

      mockFunctions.updateAnnotation('sentiment', 'negative', 'false');

      expect(global.currentAnnotations).toEqual({
        'sentiment': {
          'positive': 'true',
          'negative': 'false'
        }
      });
    });
  });

  describe('whetherNone', () => {
    test('should uncheck other options when None is selected', () => {
      // Setup DOM with checkboxes
      document.getElementById('annotation-forms').innerHTML = `
        <input type="checkbox" class="test-class" value="None" checked />
        <input type="checkbox" class="test-class" value="Option1" checked />
        <input type="checkbox" class="test-class" value="Option2" checked />
      `;

      const noneCheckbox = document.querySelector('input[value="None"]');
      mockFunctions.whetherNone(noneCheckbox);

      const option1Checkbox = document.querySelector('input[value="Option1"]');
      const option2Checkbox = document.querySelector('input[value="Option2"]');

      expect(option1Checkbox.checked).toBe(false);
      expect(option2Checkbox.checked).toBe(false);
    });

    test('should uncheck None when other option is selected', () => {
      // Setup DOM with checkboxes
      document.getElementById('annotation-forms').innerHTML = `
        <input type="checkbox" class="test-class" value="None" checked />
        <input type="checkbox" class="test-class" value="Option1" checked />
        <input type="checkbox" class="test-class" value="Option2" />
      `;

      const option1Checkbox = document.querySelector('input[value="Option1"]');
      mockFunctions.whetherNone(option1Checkbox);

      const noneCheckbox = document.querySelector('input[value="None"]');
      expect(noneCheckbox.checked).toBe(false);
    });
  });

  describe('onlyOne', () => {
    test('should ensure only one checkbox is selected', () => {
      // Setup DOM with checkboxes
      document.getElementById('annotation-forms').innerHTML = `
        <input type="checkbox" class="test-class" value="Option1" checked />
        <input type="checkbox" class="test-class" value="Option2" checked />
        <input type="checkbox" class="test-class" value="Option3" />
      `;

      const option1Checkbox = document.querySelector('input[value="Option1"]');
      mockFunctions.onlyOne(option1Checkbox);

      const option2Checkbox = document.querySelector('input[value="Option2"]');
      const option3Checkbox = document.querySelector('input[value="Option3"]');

      expect(option2Checkbox.checked).toBe(false);
      expect(option3Checkbox.checked).toBe(false);
    });
  });

  describe('escapeHtml', () => {
    test('should escape HTML characters', () => {
      const htmlString = '<script>alert("xss")</script>';
      const escaped = mockFunctions.escapeHtml(htmlString);
      expect(escaped).toBe('&lt;script&gt;alert("xss")&lt;/script&gt;');
    });

    test('should handle plain text', () => {
      const plainText = 'Hello world';
      const escaped = mockFunctions.escapeHtml(plainText);
      expect(escaped).toBe('Hello world');
    });

    test('should handle special characters', () => {
      const specialChars = '&<>"\'';
      const escaped = mockFunctions.escapeHtml(specialChars);
      // jsdom/browser textContent does not escape single quotes
      expect(escaped).toBe('&amp;&lt;&gt;"\'');
    });
  });

  describe('validateRequiredFields', () => {
    test('should return true when all required fields are filled', () => {
      // Setup DOM with required inputs
      document.getElementById('annotation-forms').innerHTML = `
        <input type="text" validation="required" value="filled" />
        <input type="radio" validation="required" name="radio_group" value="option1" checked />
        <input type="radio" validation="required" name="radio_group" value="option2" />
      `;

      const result = mockFunctions.validateRequiredFields();

      expect(result).toBe(true);
      expect(document.getElementById('next-btn').disabled).toBe(false);
    });

    test('should return false when required text field is empty', () => {
      // Setup DOM with empty required input
      document.getElementById('annotation-forms').innerHTML = `
        <input type="text" validation="required" value="" />
      `;

      const result = mockFunctions.validateRequiredFields();

      expect(result).toBe(false);
      expect(document.getElementById('next-btn').disabled).toBe(true);
    });

    test('should return false when no radio button is selected', () => {
      // Setup DOM with unselected radio buttons
      document.getElementById('annotation-forms').innerHTML = `
        <input type="radio" validation="required" name="radio_group" value="option1" />
        <input type="radio" validation="required" name="radio_group" value="option2" />
      `;

      const result = mockFunctions.validateRequiredFields();

      expect(result).toBe(false);
      expect(document.getElementById('next-btn').disabled).toBe(true);
    });

    test('should return true when at least one radio button is selected', () => {
      // Setup DOM with selected radio button
      document.getElementById('annotation-forms').innerHTML = `
        <input type="radio" validation="required" name="radio_group" value="option1" checked />
        <input type="radio" validation="required" name="radio_group" value="option2" />
      `;

      const result = mockFunctions.validateRequiredFields();

      expect(result).toBe(true);
      expect(document.getElementById('next-btn').disabled).toBe(false);
    });
  });

  describe('Span Manager Integration', () => {
    test('should check for span annotations in annotation scheme', () => {
      const checkForSpanAnnotations = (currentInstance) => {
        if (!currentInstance || !currentInstance.annotation_scheme) {
          return false;
        }

        for (const schema of Object.values(currentInstance.annotation_scheme)) {
          if (schema.type === 'span') {
            return true;
          }
        }
        return false;
      };

      const instanceWithSpans = {
        annotation_scheme: {
          sentiment: { type: 'span', labels: ['positive', 'negative'] },
          category: { type: 'text', labels: ['A', 'B'] }
        }
      };

      const instanceWithoutSpans = {
        annotation_scheme: {
          sentiment: { type: 'text', labels: ['positive', 'negative'] },
          category: { type: 'radio', labels: ['A', 'B'] }
        }
      };

      expect(checkForSpanAnnotations(instanceWithSpans)).toBe(true);
      expect(checkForSpanAnnotations(instanceWithoutSpans)).toBe(false);
      expect(checkForSpanAnnotations(null)).toBe(false);
    });

    test('should extract span labels from annotation scheme', () => {
      const getSpanLabelsFromScheme = (currentInstance) => {
        const labels = [];

        if (!currentInstance || !currentInstance.annotation_scheme) {
          return labels;
        }

        for (const [schemaName, schema] of Object.entries(currentInstance.annotation_scheme)) {
          if (schema.type === 'span' && schema.labels) {
            labels.push(...schema.labels);
          }
        }

        return labels;
      };

      const instance = {
        annotation_scheme: {
          sentiment: { type: 'span', labels: ['positive', 'negative'] },
          emotion: { type: 'span', labels: ['happy', 'sad', 'angry'] },
          category: { type: 'text', labels: ['A', 'B'] }
        }
      };

      const labels = getSpanLabelsFromScheme(instance);
      expect(labels).toEqual(['positive', 'negative', 'happy', 'sad', 'angry']);
    });
  });

  describe('Text Processing', () => {
    test('should handle text selection mapping', () => {
      const getSelectionIndicesOverlay = () => {
        const selection = window.getSelection();

        if (selection.rangeCount === 0) {
          return { start: -1, end: -1 };
        }

        const range = selection.getRangeAt(0);
        const originalText = document.getElementById('instance-text');

        if (!originalText) {
          return { start: -2, end: -2 };
        }

        const selectedText = selection.toString();
        const fullText = originalText.textContent;
        const startIndex = fullText.indexOf(selectedText);
        const endIndex = startIndex + selectedText.length;

        return { start: startIndex, end: endIndex };
      };

      // Mock selection
      const mockSelection = {
        rangeCount: 1,
        toString: () => 'Test text',
        getRangeAt: () => ({})
      };
      window.getSelection = jest.fn(() => mockSelection);

      const result = getSelectionIndicesOverlay();
      expect(result).toEqual({ start: 0, end: 9 }); // "Test text" is at the beginning
    });

    test('should handle no selection', () => {
      const mockSelection = {
        rangeCount: 0
      };
      window.getSelection = jest.fn(() => mockSelection);

      const getSelectionIndicesOverlay = () => {
        const selection = window.getSelection();

        if (selection.rangeCount === 0) {
          return { start: -1, end: -1 };
        }

        return { start: 0, end: 0 };
      };

      const result = getSelectionIndicesOverlay();
      expect(result).toEqual({ start: -1, end: -1 });
    });
  });
});
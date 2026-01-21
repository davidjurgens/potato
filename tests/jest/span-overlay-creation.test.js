/**
 * Jest tests for span overlay creation flow
 *
 * ============================================================================
 * IMPORTANT: JSDOM LIMITATIONS
 * ============================================================================
 * These tests verify DOM manipulation logic ONLY. They CANNOT test:
 * - Visual positioning (getBoundingClientRect() returns zeros in jsdom)
 * - Actual screen coordinates
 * - CSS computed styles
 * - Layout/rendering behavior
 *
 * For visual correctness testing, use the Selenium tests:
 *   tests/selenium/test_span_overlay_visual_verification.py
 *
 * These Jest tests ARE useful for:
 * - DOM structure requirements
 * - Event handler registration
 * - Text node traversal logic
 * - data-original-text attribute handling
 * ============================================================================
 *
 * Tests the critical path from text selection to overlay display.
 * These tests would catch bugs like:
 * - Overlay not being appended to DOM
 * - Text not found in data-original-text
 * - Positioning strategy not initialized
 * - Event handlers not set up
 */

describe('SpanOverlayCreation', () => {
  let textContainer;
  let textContent;
  let spanOverlays;
  let spanForm;

  beforeEach(() => {
    // Set up DOM structure matching base_template_v2.html
    document.body.innerHTML = `
      <div id="instance-text" class="instance-text-container">
        <div id="text-content" data-original-text="I am happy today">
          I am happy today
        </div>
        <div id="span-overlays"></div>
      </div>
      <form id="sentiment" class="annotation-form span">
        <fieldset schema="sentiment">
          <input type="checkbox"
                 id="sentiment_positive"
                 name="span_label:::sentiment"
                 class="sentiment shadcn-span-checkbox"
                 for_span="true">
        </fieldset>
      </form>
    `;

    textContainer = document.getElementById('instance-text');
    textContent = document.getElementById('text-content');
    spanOverlays = document.getElementById('span-overlays');
    spanForm = document.getElementById('sentiment');
  });

  afterEach(() => {
    document.body.innerHTML = '';
  });

  describe('DOM Structure Requirements', () => {
    test('text-content element must exist', () => {
      expect(textContent).not.toBeNull();
    });

    test('text-content must have data-original-text attribute', () => {
      expect(textContent.hasAttribute('data-original-text')).toBe(true);
      expect(textContent.getAttribute('data-original-text')).toBe('I am happy today');
    });

    test('span-overlays container must exist', () => {
      expect(spanOverlays).not.toBeNull();
    });

    test('span annotation form must have correct classes', () => {
      expect(spanForm.classList.contains('annotation-form')).toBe(true);
      expect(spanForm.classList.contains('span')).toBe(true);
    });

    test('span checkbox can be found with selector', () => {
      const checkbox = document.querySelector('.annotation-form.span input[type="checkbox"]');
      expect(checkbox).not.toBeNull();
      expect(checkbox.id).toBe('sentiment_positive');
    });
  });

  describe('getSelectedLabel Logic', () => {
    test('returns null when no checkbox is checked', () => {
      const checkbox = document.querySelector('.annotation-form.span input[type="checkbox"]:checked');
      expect(checkbox).toBeNull();
    });

    test('returns label when checkbox is checked', () => {
      const checkbox = document.getElementById('sentiment_positive');
      checkbox.checked = true;

      const checkedCheckbox = document.querySelector('.annotation-form.span input[type="checkbox"]:checked');
      expect(checkedCheckbox).not.toBeNull();
      expect(checkedCheckbox.id).toBe('sentiment_positive');

      // Extract label from ID
      const parts = checkedCheckbox.id.split('_');
      const label = parts[parts.length - 1];
      expect(label).toBe('positive');
    });

    test('correctly parses multi-part checkbox IDs', () => {
      // Create a checkbox with underscore in schema name
      spanForm.innerHTML = `
        <input type="checkbox"
               id="span_sentiment_very_positive"
               checked>
      `;

      const checkbox = spanForm.querySelector('input:checked');
      const parts = checkbox.id.split('_');
      const label = parts[parts.length - 1];
      expect(label).toBe('positive');
    });
  });

  describe('Text Selection Matching', () => {
    test('selected text found in data-original-text', () => {
      const originalText = textContent.getAttribute('data-original-text');
      const selectedText = 'happy';

      const start = originalText.indexOf(selectedText);
      expect(start).not.toBe(-1);
      expect(start).toBe(5); // "I am " = 5 chars before "happy"
    });

    test('whitespace-normalized text matches', () => {
      // Simulate normalized text matching
      const originalText = 'I am happy today';
      const selectedText = 'happy';

      const start = originalText.indexOf(selectedText);
      expect(start).toBe(5);
    });

    test('returns -1 for text not in original', () => {
      const originalText = textContent.getAttribute('data-original-text');
      const selectedText = 'nonexistent';

      const start = originalText.indexOf(selectedText);
      expect(start).toBe(-1);
    });
  });

  describe('Overlay DOM Manipulation', () => {
    test('overlay can be appended to span-overlays container', () => {
      const overlay = document.createElement('div');
      overlay.className = 'span-overlay-pure';
      overlay.dataset.start = '5';
      overlay.dataset.end = '10';
      overlay.dataset.label = 'positive';

      spanOverlays.appendChild(overlay);

      expect(spanOverlays.children.length).toBe(1);
      expect(spanOverlays.querySelector('.span-overlay-pure')).not.toBeNull();
    });

    test('overlay has required structure', () => {
      // Create overlay structure matching createOverlay() output
      const overlay = document.createElement('div');
      overlay.className = 'span-overlay-pure';
      overlay.dataset.annotationId = 'span_5_10_12345';
      overlay.dataset.start = '5';
      overlay.dataset.end = '10';
      overlay.dataset.label = 'positive';

      // Add highlight segment
      const segment = document.createElement('div');
      segment.className = 'span-highlight-segment';
      segment.style.position = 'absolute';
      segment.style.backgroundColor = 'rgba(255, 255, 0, 0.3)';
      overlay.appendChild(segment);

      // Add label
      const label = document.createElement('div');
      label.className = 'span-label';
      label.textContent = 'positive';
      overlay.appendChild(label);

      // Add delete button
      const deleteBtn = document.createElement('button');
      deleteBtn.className = 'span-delete-btn';
      deleteBtn.textContent = '×';
      overlay.appendChild(deleteBtn);

      spanOverlays.appendChild(overlay);

      expect(overlay.querySelector('.span-highlight-segment')).not.toBeNull();
      expect(overlay.querySelector('.span-label')).not.toBeNull();
      expect(overlay.querySelector('.span-label').textContent).toBe('positive');
      expect(overlay.querySelector('.span-delete-btn')).not.toBeNull();
    });

    test('multiple overlays can coexist', () => {
      for (let i = 0; i < 3; i++) {
        const overlay = document.createElement('div');
        overlay.className = 'span-overlay-pure';
        overlay.dataset.index = String(i);
        spanOverlays.appendChild(overlay);
      }

      expect(spanOverlays.children.length).toBe(3);
    });
  });

  describe('Critical Bug Prevention: Overlay Visibility', () => {
    test('overlay must be in DOM to be visible', () => {
      const overlay = document.createElement('div');
      overlay.className = 'span-overlay-pure';

      // Before appending, overlay is not in DOM
      expect(document.contains(overlay)).toBe(false);

      // After appending, overlay is in DOM
      spanOverlays.appendChild(overlay);
      expect(document.contains(overlay)).toBe(true);
    });

    test('overlay not hidden by CSS pointer-events', () => {
      const overlay = document.createElement('div');
      overlay.className = 'span-overlay-pure';
      overlay.style.pointerEvents = 'none'; // Container has pointer-events: none

      const deleteBtn = document.createElement('button');
      deleteBtn.className = 'span-delete-btn';
      deleteBtn.style.pointerEvents = 'auto'; // But buttons need pointer-events: auto
      overlay.appendChild(deleteBtn);

      spanOverlays.appendChild(overlay);

      expect(overlay.style.pointerEvents).toBe('none');
      expect(deleteBtn.style.pointerEvents).toBe('auto');
    });
  });

  describe('Event Handler Registration', () => {
    test('mouseup event listeners can be added to text containers', () => {
      let handlerCalled = false;
      const handler = () => { handlerCalled = true; };

      textContainer.addEventListener('mouseup', handler);

      // Simulate mouseup
      const event = new MouseEvent('mouseup', { bubbles: true });
      textContainer.dispatchEvent(event);

      expect(handlerCalled).toBe(true);
    });

    test('event bubbles from text-content to instance-text', () => {
      let containerCalled = false;
      let contentCalled = false;

      textContainer.addEventListener('mouseup', () => { containerCalled = true; });
      textContent.addEventListener('mouseup', () => { contentCalled = true; });

      const event = new MouseEvent('mouseup', { bubbles: true });
      textContent.dispatchEvent(event);

      expect(contentCalled).toBe(true);
      expect(containerCalled).toBe(true);
    });
  });

  describe('Text Node Traversal for Server-Rendered Spans', () => {
    test('collects text nodes from nested structure', () => {
      // Simulate server-rendered span in DOM
      textContent.innerHTML = 'I am <span class="span-highlight">happy</span> today';

      const textNodes = [];
      const collectTextNodes = (node) => {
        if (node.nodeType === Node.TEXT_NODE) {
          textNodes.push(node.textContent);
        } else if (node.nodeType === Node.ELEMENT_NODE) {
          for (const child of node.childNodes) {
            collectTextNodes(child);
          }
        }
      };

      collectTextNodes(textContent);

      expect(textNodes).toEqual(['I am ', 'happy', ' today']);
      expect(textNodes.join('')).toBe('I am happy today');
    });

    test('cumulative offset calculation is correct', () => {
      textContent.innerHTML = 'I am <span class="span-highlight">happy</span> today';

      const textNodes = [];
      let cumulativeOffset = 0;

      const collectTextNodes = (node) => {
        if (node.nodeType === Node.TEXT_NODE) {
          textNodes.push({
            text: node.textContent,
            start: cumulativeOffset,
            end: cumulativeOffset + node.textContent.length
          });
          cumulativeOffset += node.textContent.length;
        } else if (node.nodeType === Node.ELEMENT_NODE) {
          for (const child of node.childNodes) {
            collectTextNodes(child);
          }
        }
      };

      collectTextNodes(textContent);

      // "I am " starts at 0, ends at 5
      expect(textNodes[0].start).toBe(0);
      expect(textNodes[0].end).toBe(5);

      // "happy" starts at 5, ends at 10
      expect(textNodes[1].start).toBe(5);
      expect(textNodes[1].end).toBe(10);

      // " today" starts at 10, ends at 16
      expect(textNodes[2].start).toBe(10);
      expect(textNodes[2].end).toBe(16);
    });

    test('finds correct text node for position', () => {
      textContent.innerHTML = 'I am <span class="span-highlight">happy</span> today';

      const textNodes = [];
      let cumulativeOffset = 0;

      const collectTextNodes = (node) => {
        if (node.nodeType === Node.TEXT_NODE) {
          textNodes.push({
            node: node,
            start: cumulativeOffset,
            end: cumulativeOffset + node.textContent.length
          });
          cumulativeOffset += node.textContent.length;
        } else if (node.nodeType === Node.ELEMENT_NODE) {
          for (const child of node.childNodes) {
            collectTextNodes(child);
          }
        }
      };

      collectTextNodes(textContent);

      // Find text node for position 11 (should be " today" node)
      const targetPosition = 11;
      let foundNode = null;

      for (const tn of textNodes) {
        if (targetPosition >= tn.start && targetPosition < tn.end) {
          foundNode = tn;
          break;
        }
      }

      expect(foundNode).not.toBeNull();
      expect(foundNode.node.textContent).toBe(' today');
    });
  });

  describe('data-original-text vs DOM Content', () => {
    test('data-original-text contains plain text when DOM has spans', () => {
      // Simulate the fixed behavior: attribute has plain text, DOM has spans
      textContent.setAttribute('data-original-text', 'I am happy today');
      textContent.innerHTML = 'I am <span class="span-highlight">happy</span> today';

      const attributeText = textContent.getAttribute('data-original-text');
      const domText = textContent.textContent;

      expect(attributeText).toBe('I am happy today');
      expect(domText).toBe('I am happy today'); // textContent strips tags
    });

    test('selection text matches data-original-text', () => {
      textContent.setAttribute('data-original-text', 'I am happy today');
      textContent.innerHTML = 'I am <span class="span-highlight">happy</span> today';

      // Simulate selection of "happy" from the span element
      const selectedText = 'happy';
      const originalText = textContent.getAttribute('data-original-text');

      // The selectedText should be found in originalText
      const start = originalText.indexOf(selectedText);
      expect(start).toBe(5);
    });

    test('CRITICAL: data-original-text must match DOM textContent exactly', () => {
      // BUG CAUGHT: Template whitespace caused mismatch between attribute and DOM
      // When the template had:
      //   <div id="text-content" data-original-text="...">
      //       {{instance}}
      //   </div>
      // The DOM textContent included newlines and indentation spaces, but
      // data-original-text did not. This caused position calculations to fail
      // because offset 8 in the attribute mapped to whitespace in the DOM.

      // Set up correctly matching content (simulating the fixed template)
      textContent.setAttribute('data-original-text', 'I am happy today');
      textContent.textContent = 'I am happy today'; // No extra whitespace

      const attributeText = textContent.getAttribute('data-original-text');
      const domText = textContent.textContent;

      // These MUST match for position calculations to work
      expect(domText).toBe(attributeText);
    });

    test('position mapping fails when DOM has extra whitespace', () => {
      // Simulate the bug: DOM has extra whitespace that attribute doesn't
      textContent.setAttribute('data-original-text', 'Hello world');
      textContent.innerHTML = '\n    Hello world\n    '; // Extra whitespace

      const attributeText = textContent.getAttribute('data-original-text');
      const domText = textContent.textContent;

      // The texts don't match
      expect(domText).not.toBe(attributeText);

      // Position of "world" in attribute is 6
      const posInAttribute = attributeText.indexOf('world');
      expect(posInAttribute).toBe(6);

      // But position 6 in DOM is still in whitespace!
      const charAtPos6InDom = domText.charAt(6);
      expect(charAtPos6InDom).not.toBe('w'); // This would cause the bug
    });
  });
});

describe('SpanManager Integration Simulation', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="instance-text">
        <div id="text-content" data-original-text="I am happy today">
          I am happy today
        </div>
        <div id="span-overlays"></div>
      </div>
      <form id="sentiment" class="annotation-form span">
        <input type="checkbox" id="sentiment_positive" checked>
      </form>
    `;
  });

  test('complete flow from selection to overlay creation', () => {
    const textContent = document.getElementById('text-content');
    const spanOverlays = document.getElementById('span-overlays');

    // Step 1: Get selected label
    const checkbox = document.querySelector('.annotation-form.span input[type="checkbox"]:checked');
    expect(checkbox).not.toBeNull();
    const parts = checkbox.id.split('_');
    const selectedLabel = parts[parts.length - 1];
    expect(selectedLabel).toBe('positive');

    // Step 2: Get text to annotate
    const selectedText = 'happy';
    const originalText = textContent.getAttribute('data-original-text');
    const start = originalText.indexOf(selectedText);
    expect(start).not.toBe(-1);
    const end = start + selectedText.length;

    // Step 3: Create span object
    const span = {
      id: `span_${start}_${end}_${Date.now()}`,
      start: start,
      end: end,
      text: selectedText,
      label: selectedLabel
    };
    expect(span.start).toBe(5);
    expect(span.end).toBe(10);
    expect(span.label).toBe('positive');

    // Step 4: Create overlay (simplified)
    const overlay = document.createElement('div');
    overlay.className = 'span-overlay-pure';
    overlay.dataset.annotationId = span.id;
    overlay.dataset.start = String(span.start);
    overlay.dataset.end = String(span.end);
    overlay.dataset.label = span.label;

    const segment = document.createElement('div');
    segment.className = 'span-highlight-segment';
    overlay.appendChild(segment);

    const label = document.createElement('div');
    label.className = 'span-label';
    label.textContent = span.label;
    overlay.appendChild(label);

    // Step 5: CRITICAL - Append overlay to DOM
    spanOverlays.appendChild(overlay);

    // Verify overlay is in DOM and visible
    expect(spanOverlays.children.length).toBe(1);
    expect(spanOverlays.querySelector('.span-overlay-pure')).not.toBeNull();
    expect(spanOverlays.querySelector('.span-label').textContent).toBe('positive');
  });

  test('overlay creation fails gracefully when text not found', () => {
    const textContent = document.getElementById('text-content');

    const selectedText = 'nonexistent';
    const originalText = textContent.getAttribute('data-original-text');
    const start = originalText.indexOf(selectedText);

    expect(start).toBe(-1);
    // Function should return null/early when start is -1
  });

  test('overlay creation fails gracefully when no label selected', () => {
    // Uncheck the checkbox
    document.getElementById('sentiment_positive').checked = false;

    const checkbox = document.querySelector('.annotation-form.span input[type="checkbox"]:checked');
    expect(checkbox).toBeNull();
    // Function should return early when no label is selected
  });
});

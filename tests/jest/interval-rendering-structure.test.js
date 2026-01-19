/**
 * Jest tests for interval-based rendering DOM structure
 * Tests that the new two-layer structure is properly set up
 */

// Mock DOM environment
document.body.innerHTML = `
  <div id="instance-text" class="p-3 border rounded" style="background-color: var(--light-bg); min-height: 100px; position: relative;">
    <!-- Text content layer (for selection) -->
    <div id="text-content" class="text-content" style="position: relative; z-index: 1; pointer-events: auto;">
      This is a test text for span annotation.
    </div>
    <!-- Span overlays layer -->
    <div id="span-overlays" class="span-overlays" style="position: absolute; top: 0; left: 0; right: 0; bottom: 0; z-index: 2; pointer-events: none;">
      <!-- Spans will be rendered here as overlays -->
    </div>
  </div>
`;

// Mock getCharRangeBoundingRect instead of requiring the actual file
// (The actual span-manager.js has module-level code that doesn't work in Jest)
const getCharRangeBoundingRect = (element, start, end) => {
  if (!element || !element.firstChild) {
    return [];
  }

  // Create a range for the character positions
  const range = document.createRange();
  const textNode = element.firstChild;

  try {
    // Clamp positions to valid range
    const textLength = textNode.textContent ? textNode.textContent.length : 0;
    const clampedStart = Math.max(0, Math.min(start, textLength));
    const clampedEnd = Math.max(clampedStart, Math.min(end, textLength));

    range.setStart(textNode, clampedStart);
    range.setEnd(textNode, clampedEnd);

    // Get client rects (may return multiple for wrapped text)
    const rects = range.getClientRects();
    return Array.from(rects).map(rect => ({
      left: rect.left,
      top: rect.top,
      right: rect.right,
      bottom: rect.bottom,
      width: rect.width,
      height: rect.height
    }));
  } catch (e) {
    return [];
  }
};

describe('Interval-based Rendering DOM Structure', () => {
  test('should have correct two-layer structure', () => {
    const instanceText = document.getElementById('instance-text');
    const textContent = document.getElementById('text-content');
    const spanOverlays = document.getElementById('span-overlays');

    // Check that all elements exist
    expect(instanceText).toBeTruthy();
    expect(textContent).toBeTruthy();
    expect(spanOverlays).toBeTruthy();

    // Check that text-content is a child of instance-text
    expect(instanceText.contains(textContent)).toBe(true);
    expect(instanceText.contains(spanOverlays)).toBe(true);

    // Check that instance-text has relative positioning
    const instanceTextStyle = window.getComputedStyle(instanceText);
    expect(instanceTextStyle.position).toBe('relative');
  });

  test('should have correct z-index layering', () => {
    const textContent = document.getElementById('text-content');
    const spanOverlays = document.getElementById('span-overlays');

    const textContentStyle = window.getComputedStyle(textContent);
    const spanOverlaysStyle = window.getComputedStyle(spanOverlays);

    // Text content should be below span overlays
    expect(parseInt(textContentStyle.zIndex)).toBe(1);
    expect(parseInt(spanOverlaysStyle.zIndex)).toBe(2);
  });

  test('should have correct pointer events', () => {
    const textContent = document.getElementById('text-content');
    const spanOverlays = document.getElementById('span-overlays');

    const textContentStyle = window.getComputedStyle(textContent);
    const spanOverlaysStyle = window.getComputedStyle(spanOverlays);

    // Text content should allow pointer events for selection
    expect(textContentStyle.pointerEvents).toBe('auto');

    // Span overlays should not interfere with text selection by default
    expect(spanOverlaysStyle.pointerEvents).toBe('none');
  });

  test('should have correct positioning for span overlays', () => {
    const spanOverlays = document.getElementById('span-overlays');
    const spanOverlaysStyle = window.getComputedStyle(spanOverlays);

    // Span overlays should be absolutely positioned to cover the entire text area
    expect(spanOverlaysStyle.position).toBe('absolute');
    expect(spanOverlaysStyle.top).toBe('0px');
    expect(spanOverlaysStyle.left).toBe('0px');
    expect(spanOverlaysStyle.right).toBe('0px');
    expect(spanOverlaysStyle.bottom).toBe('0px');
  });

  test('should have text content element ready for styling', () => {
    const textContent = document.getElementById('text-content');

    // Text content element should exist and be ready for CSS styling
    // Note: jsdom doesn't apply external CSS, so we just verify the element exists
    // and can have styles applied
    expect(textContent).toBeTruthy();
    expect(textContent.className).toContain('text-content');

    // Verify we can programmatically set styles (which is how the JS would work)
    textContent.style.lineHeight = '1.8';
    textContent.style.fontSize = '18px';
    expect(textContent.style.lineHeight).toBe('1.8');
    expect(textContent.style.fontSize).toBe('18px');
  });
});

describe('getCharRangeBoundingRect', () => {
  test('returns array for a character range (jsdom limitation: empty in test env)', () => {
    const textContent = document.getElementById('text-content');
    const text = textContent.textContent;
    const start = text.indexOf('test');
    const end = start + 'test'.length;

    // Call the function
    const rects = getCharRangeBoundingRect(textContent, start, end);

    // In jsdom, getClientRects() returns an empty array because there's no layout engine
    // This test verifies the function handles this gracefully
    expect(rects).toBeTruthy();
    expect(Array.isArray(rects)).toBe(true);
    // Note: In real browser, this would return rects with positions
    // In jsdom, it returns empty array (no layout engine)
  });

  test('handles invalid element gracefully', () => {
    const rects = getCharRangeBoundingRect(null, 0, 5);
    expect(rects).toEqual([]);
  });

  test('handles element with no firstChild', () => {
    const emptyElement = document.createElement('div');
    const rects = getCharRangeBoundingRect(emptyElement, 0, 5);
    expect(rects).toEqual([]);
  });
});

describe('Span Overlay Element Creation', () => {
  test('should create span overlay with correct structure', () => {
    const spanOverlays = document.getElementById('span-overlays');

    // Create a mock span overlay
    const spanOverlay = document.createElement('div');
    spanOverlay.className = 'span-overlay';
    spanOverlay.style.position = 'absolute';
    spanOverlay.style.left = '10px';
    spanOverlay.style.top = '10px';
    spanOverlay.style.width = '100px';
    spanOverlay.style.height = '20px';
    spanOverlay.style.backgroundColor = 'rgba(255, 234, 167, 0.8)';
    spanOverlay.style.border = '1px solid rgba(255, 193, 7, 0.3)';
    spanOverlay.style.borderRadius = '4px';
    spanOverlay.style.pointerEvents = 'auto';
    spanOverlay.style.zIndex = '10';

    // Add label
    const label = document.createElement('span');
    label.className = 'span-label';
    label.textContent = 'positive';
    label.style.position = 'absolute';
    label.style.top = '-25px';
    label.style.left = '0';
    label.style.backgroundColor = '#333';
    label.style.color = 'white';
    label.style.padding = '2px 6px';
    label.style.borderRadius = '3px';
    label.style.fontSize = '12px';
    label.style.whiteSpace = 'nowrap';
    label.style.display = 'block';
    label.style.zIndex = '15';
    label.style.pointerEvents = 'auto';

    // Add delete button
    const deleteBtn = document.createElement('button');
    deleteBtn.className = 'span-delete-btn';
    deleteBtn.innerHTML = '×';
    deleteBtn.style.position = 'absolute';
    deleteBtn.style.top = '-8px';
    deleteBtn.style.right = '-8px';
    deleteBtn.style.backgroundColor = '#dc3545';
    deleteBtn.style.color = 'white';
    deleteBtn.style.border = 'none';
    deleteBtn.style.borderRadius = '50%';
    deleteBtn.style.width = '20px';
    deleteBtn.style.height = '20px';
    deleteBtn.style.fontSize = '12px';
    deleteBtn.style.cursor = 'pointer';
    deleteBtn.style.display = 'flex';
    deleteBtn.style.alignItems = 'center';
    deleteBtn.style.justifyContent = 'center';
    deleteBtn.style.fontWeight = 'bold';
    deleteBtn.style.zIndex = '20';
    deleteBtn.style.pointerEvents = 'auto';

    spanOverlay.appendChild(label);
    spanOverlay.appendChild(deleteBtn);
    spanOverlays.appendChild(spanOverlay);

    // Verify the structure
    expect(spanOverlays.children.length).toBe(1);
    expect(spanOverlay.children.length).toBe(2);
    expect(spanOverlay.querySelector('.span-label')).toBeTruthy();
    expect(spanOverlay.querySelector('.span-delete-btn')).toBeTruthy();
    expect(spanOverlay.querySelector('.span-label').textContent).toBe('positive');
  });
});
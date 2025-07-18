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

const { getCharRangeBoundingRect } = require('../../potato/static/span-manager.js');

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

  test('should have text content with proper styling', () => {
    const textContent = document.getElementById('text-content');
    const textContentStyle = window.getComputedStyle(textContent);

    // Text content should have proper text styling
    expect(textContentStyle.lineHeight).toBe('1.8');
    expect(textContentStyle.fontSize).toBe('18px');
    expect(textContentStyle.whiteSpace).toBe('pre-wrap');
    expect(textContentStyle.wordWrap).toBe('break-word');
  });
});

describe('getCharRangeBoundingRect', () => {
  test('returns bounding rects for a character range', () => {
    const textContent = document.getElementById('text-content');
    // "I am absolutely thrilled about the new technology announcement!..."
    // Let's get the bounding rect for the word "thrilled"
    const text = textContent.textContent;
    const start = text.indexOf('thrilled');
    const end = start + 'thrilled'.length;
    const rects = getCharRangeBoundingRect(textContent, start, end);
    expect(rects).toBeTruthy();
    expect(Array.isArray(rects)).toBe(true);
    expect(rects.length).toBeGreaterThan(0);
    // Each rect should have left, top, right, bottom
    for (const rect of rects) {
      expect(rect).toHaveProperty('left');
      expect(rect).toHaveProperty('top');
      expect(rect).toHaveProperty('right');
      expect(rect).toHaveProperty('bottom');
    }
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
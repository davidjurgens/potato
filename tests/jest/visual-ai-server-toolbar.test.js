/**
 * Results reach the page when the toolbar was rendered by the server.
 *
 * The image and video schemes render `.ai-toolbar` and an empty
 * `.ai-tooltip-container` server-side. `_createUI()` found the toolbar and
 * returned early, so `this.tooltipContainer` stayed null and `_addStyles()`
 * never ran. Every hint, classification and error is written into the tooltip
 * container behind `if (!this.tooltipContainer) return;`, so the request went
 * out, the server answered 200, and nothing appeared. The buttons were also
 * unstyled.
 *
 * The markup below mirrors `_generate_ai_toolbar` in
 * potato/server_utils/schemas/image_annotation.py (`_generate_video_ai_toolbar` renders
 * the same structure).
 */

const fs = require('fs');
const path = require('path');

const SRC = path.join(__dirname, '..', '..', 'potato', 'static',
                      'visual_ai_assistant.js');

function loadManager() {
    const source = fs.readFileSync(SRC, 'utf8');
    const module_ = { exports: {} };
    // eslint-disable-next-line no-new-func
    (new Function('module', 'exports', source))(module_, module_.exports);
    return module_.exports;
}

const VisualAIAssistantManager = loadManager();

const SERVER_MARKUP = `
<div class="image-annotation-container">
    <div class="image-annotation-toolbar"></div>
    <div class="ai-toolbar">
        <div class="ai-toolbar-group">
            <span class="ai-toolbar-label">AI Assist:</span>
            <button type="button" class="ai-btn" data-action="hint">Hint</button>
            <button type="button" class="ai-btn" data-action="detect">Detect</button>
            <button type="button" class="ai-btn" data-action="classification">Classify</button>
        </div>
        <div class="ai-suggestion-controls" style="display: none;">
            <span class="suggestion-count">0 suggestions</span>
        </div>
        <div class="ai-loading-indicator" style="display: none;">
            <span class="spinner"></span> Loading...
        </div>
    </div>
    <div class="ai-tooltip-container" style="display: none;"></div>
</div>`;

// setup.js installs a jest.fn() fetch and silent console methods globally.
function respondWith(body) {
    fetch.mockImplementation(() => Promise.resolve({
        ok: true, json: () => Promise.resolve(body),
    }));
}

const settle = () => new Promise(resolve => setTimeout(resolve, 0));

let manager;
let tooltip;

beforeEach(() => {
    document.head.innerHTML = '';
    document.body.innerHTML = SERVER_MARKUP;
    const container = document.querySelector('.image-annotation-container');
    manager = new VisualAIAssistantManager({
        annotationType: 'image_annotation',
        annotationId: 0,
        annotationManager: { container },
    });
    tooltip = document.querySelector('.ai-tooltip-container');
});

function click(action) {
    document.querySelector(`.ai-btn[data-action="${action}"]`).click();
}

test('adopts the server-rendered toolbar without duplicating it', () => {
    expect(document.querySelectorAll('.ai-toolbar')).toHaveLength(1);
    expect(document.querySelectorAll('.ai-tooltip-container')).toHaveLength(1);
    expect(manager.tooltipContainer).toBe(tooltip);
});

test('styles the server-rendered buttons', () => {
    expect(document.getElementById('visual-ai-styles')).not.toBeNull();
});

test('a hint appears in the tooltip', async () => {
    respondWith({ hint: 'Look at the upper left corner.' });
    click('hint');
    await settle();
    expect(tooltip.style.display).toBe('block');
    expect(tooltip.textContent).toContain('Look at the upper left corner.');
});

test('a classification appears in the tooltip', async () => {
    respondWith({ suggested_label: 'cat', confidence: 0.95, reasoning: 'Whiskers.' });
    click('classification');
    await settle();
    expect(tooltip.style.display).toBe('block');
    expect(tooltip.textContent).toContain('cat');
    expect(tooltip.textContent).toContain('95%');
    expect(tooltip.textContent).toContain('Whiskers.');
});

test('a server error appears in the tooltip', async () => {
    respondWith({ error: "This endpoint does not support 'detect'" });
    click('detect');
    await settle();
    expect(tooltip.style.display).toBe('block');
    expect(tooltip.textContent).toContain("does not support 'detect'");
});

test('the close button hides the tooltip', async () => {
    respondWith({ hint: 'x' });
    click('hint');
    await settle();
    tooltip.querySelector('.close-btn').click();
    expect(tooltip.style.display).toBe('none');
});

test('a server toolbar without a tooltip container still shows results', async () => {
    document.querySelector('.ai-tooltip-container').remove();
    const container = document.querySelector('.image-annotation-container');
    const m = new VisualAIAssistantManager({
        annotationType: 'image_annotation', annotationId: 0,
        annotationManager: { container },
    });
    respondWith({ hint: 'still here' });
    await m.requestSuggestion('hint');
    expect(m.tooltipContainer.textContent).toContain('still here');
    expect(m.tooltipContainer.style.display).toBe('block');
});

test('a created tooltip sits directly under the toolbar, not below the image', () => {
    document.querySelector('.ai-tooltip-container').remove();
    const container = document.querySelector('.image-annotation-container');
    const m = new VisualAIAssistantManager({
        annotationType: 'image_annotation', annotationId: 0,
        annotationManager: { container },
    });
    expect(m.toolbar.nextElementSibling).toBe(m.tooltipContainer);
});

test('the tooltip is in the flow, not pinned to the bottom of the container', () => {
    const css = document.getElementById('visual-ai-styles').textContent;
    const rule = css.slice(css.indexOf('.ai-tooltip-container {'));
    const body = rule.slice(0, rule.indexOf('}'));
    expect(body).not.toMatch(/position:\s*absolute/);
    expect(body).not.toMatch(/top:\s*100%/);
});

/**
 * ai_assistant_manager.js and visual_ai_assistant.js on one page.
 *
 * Classic scripts share one global scope. ai_assistant_manager.js declares
 * `function aiTextToSafeHtml`; visual_ai_assistant.js declared
 * `const aiTextToSafeHtml = window.aiTextToSafeHtml || ...`. Re-declaring an
 * existing global with `const` is a SyntaxError, so the second file never ran:
 * on every image or video project with AI support, VisualAIAssistantManager did
 * not exist and the suggestion panel never appeared. The page logged
 * "Identifier 'aiTextToSafeHtml' has already been declared" and carried on.
 *
 * Each file is fine on its own, which is why per-file checks (node --check,
 * a jsdom test of either script) never caught it. This loads both, in page
 * order, into one context, the way the browser does.
 */

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const STATIC = path.join(__dirname, '..', '..', 'potato', 'static');
const read = name => fs.readFileSync(path.join(STATIC, name), 'utf8');

function pageContext() {
    const ctx = vm.createContext({
        console: { log() {}, warn() {}, error() {}, debug() {}, info() {} },
        document: window.document,
        setTimeout, clearTimeout, setInterval, clearInterval,
        fetch: () => Promise.reject(new Error('no network in this test')),
    });
    ctx.window = ctx;
    return ctx;
}

function load(ctx, name) {
    new vm.Script(read(name), { filename: name }).runInContext(ctx);
}

test('both scripts load into one page', () => {
    const ctx = pageContext();
    load(ctx, 'ai_assistant_manager.js');
    expect(() => load(ctx, 'visual_ai_assistant.js')).not.toThrow();
    expect(vm.runInContext('typeof VisualAIAssistantManager', ctx)).toBe('function');
});

test('the visual assistant uses the shared escaper when it exists', () => {
    const ctx = pageContext();
    load(ctx, 'ai_assistant_manager.js');
    load(ctx, 'visual_ai_assistant.js');
    // The shared one renders the model's inline markdown; the fallback would not.
    expect(vm.runInContext("aiTextToSafeHtml('**bold**')", ctx)).toBe('<strong>bold</strong>');
});

test('on its own, the visual assistant still escapes', () => {
    const ctx = pageContext();
    load(ctx, 'visual_ai_assistant.js');
    expect(vm.runInContext('typeof VisualAIAssistantManager', ctx)).toBe('function');
    expect(vm.runInContext("aiTextToSafeHtml('<img src=x onerror=alert(1)>')", ctx))
        .toBe('&lt;img src=x onerror=alert(1)&gt;');
});

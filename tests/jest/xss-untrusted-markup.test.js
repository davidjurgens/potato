/**
 * Untrusted values rendered with innerHTML stay text.
 *
 * Usernames, item fields, annotator-entered values, KB results and model
 * output reached innerHTML raw, or through an escaper that left quotes alone
 * and was then used inside an attribute. Each test renders the real code with
 * a hostile value and checks the DOM it produced: no injected element, no
 * injected attribute, and the value reads back unchanged.
 */

const fs = require('fs');
const path = require('path');

const STATIC = path.join(__dirname, '../../potato/static');

// A value that breaks out of a double-quoted attribute, and one that makes a
// tag in element text. Either one executing would mean an injected handler.
const ATTR_BREAK = 'x" onmouseover="window.__pwned=1" data-x="';
const TAG = '<img src=x onerror="window.__pwned=1">';
const BOTH = ATTR_BREAK + TAG + "'";

/**
 * Load a classic script in the global scope. A top-level `class` in eval code
 * stays local to that eval, so the names a test needs are copied to window.
 */
function loadScript(rel, ...exportNames) {
  const src = fs.readFileSync(path.join(STATIC, rel), 'utf8');
  const exports = exportNames.map((n) => `window.${n} = ${n};`).join('\n');
  // eslint-disable-next-line no-eval
  (0, eval)(src + '\n' + exports);
}

/** One function's source out of a large file (same idea as the conjoint tests). */
function extractFunction(source, name) {
  const start = source.indexOf(`function ${name}(`);
  if (start === -1) throw new Error(`${name}() not found`);
  const open = source.indexOf('{', start);
  let depth = 0;
  for (let j = open; j < source.length; j++) {
    if (source[j] === '{') depth++;
    else if (source[j] === '}') {
      depth--;
      if (depth === 0) return source.slice(start, j + 1);
    }
  }
  throw new Error(`unbalanced braces reading ${name}()`);
}

/** Every attribute named on* anywhere under root. */
function handlerAttrs(root) {
  const found = [];
  root.querySelectorAll('*').forEach((el) => {
    for (const a of el.attributes) {
      if (a.name.toLowerCase().startsWith('on')) found.push(el.tagName + '[' + a.name + ']');
    }
  });
  return found;
}

function render(html) {
  const div = document.createElement('div');
  div.innerHTML = html;
  return div;
}

describe('AdjudicationForms (adjudicator page)', () => {
  beforeAll(() => loadScript('adjudication-forms.js'));
  const F = () => window.AdjudicationForms;

  test('escapeHtml escapes quotes for attribute use', () => {
    const div = render('<span title="' + F().escapeHtml(BOTH) + '">' + F().escapeHtml(BOTH) + '</span>');
    expect(handlerAttrs(div)).toEqual([]);
    expect(div.querySelector('img')).toBeNull();
    expect(div.querySelector('span').getAttribute('title')).toBe(BOTH);
    expect(div.textContent).toBe(BOTH);
  });

  test.each([
    ['likert', { annotation_type: 'likert', name: 's', min_value: 1, max_value: 5 }, '3'],
    ['text', { annotation_type: 'text', name: 's' }, 'some text'],
    ['radio', { annotation_type: 'radio', name: 's', labels: ['a', 'b'] }, 'a'],
  ])('a hostile username stays text in the %s form', (_kind, schema, value) => {
    const annotations = { [BOTH]: { s: value } };
    const html = F().renderForm(schema, annotations, {}, {}, {}, null);
    const div = render(html);
    expect(handlerAttrs(div)).toEqual([]);
    expect(div.querySelector('img')).toBeNull();
    const tagged = div.querySelectorAll('[data-annotator]');
    expect(tagged.length).toBeGreaterThan(0);
    tagged.forEach((el) => expect(el.getAttribute('data-annotator')).toBe(BOTH));
  });

  test('image shape coordinates only ever render as numbers', () => {
    const objects = [
      { type: 'bbox', label: 'car', coordinates: { x: '0.1" onmouseover="window.__pwned=1', y: 0.2, width: 0.3, height: 0.4 } },
      { type: 'polygon', label: 'car', coordinates: [{ x: '1"><script>window.__pwned=1</script>', y: 0 }, { x: 0.5, y: 0.5 }] },
      { type: 'point', label: 'car', coordinates: { x: 0.5, y: '"/><img src=x onerror=1>' } },
    ];
    const schema = { annotation_type: 'image_annotation', name: 'img' };
    const html = F().renderForm(schema, { [BOTH]: { img: JSON.stringify(objects) } }, {}, {}, {}, '/a.png');
    const div = render(html);
    expect(handlerAttrs(div)).toEqual([]);
    expect(div.querySelector('script')).toBeNull();
    expect(div.querySelectorAll('img').length).toBe(1);        // the preview itself
    const rect = div.querySelector('rect.adj-shape');
    expect(rect.getAttribute('x')).toBe('0');                  // non-numeric -> 0
    expect(rect.getAttribute('width')).toBe('0.3');
  });
});

describe('SoloDashboard (solo-mode dashboard)', () => {
  beforeAll(() => loadScript('js/solo-dashboard.js', 'SoloDashboard'));

  test('model labels in inline handlers reach the handler unchanged', () => {
    const SoloDashboard = window.SoloDashboard;
    document.body.insertAdjacentHTML('beforeend', '<table><tbody id="confusion-patterns-body"></tbody></table>');
    const dash = Object.create(SoloDashboard.prototype);
    const predicted = "it's\"); window.__pwned=1; //";
    const actual = BOTH;
    dash._renderPatternsTable([{ predicted_label: predicted, actual_label: actual, count: 1, percent: 5 }]);
    const tbody = document.getElementById('confusion-patterns-body');
    expect(tbody.querySelector('img')).toBeNull();
    const btn = tbody.querySelector('button.suggest-btn');
    const calls = [];
    window.soloDashboard = { suggestGuideline: (a, b) => calls.push([a, b]) };
    // The handler source is what the browser would run on click.
    // eslint-disable-next-line no-new-func
    new Function(btn.getAttribute('onclick'))();
    expect(window.__pwned).toBeUndefined();
    expect(calls).toEqual([[predicted, actual]]);
  });

  test('rule text in a title attribute cannot add attributes', () => {
    const dash = Object.create(window.SoloDashboard.prototype);
    // A <span>, not the real <td>: a <td> outside a table is dropped by the
    // parser and would make this pass vacuously.
    const div = render('<span title="' + dash._esc(BOTH) + '"></span>');
    expect(handlerAttrs(div)).toEqual([]);
    expect(div.querySelector('span').getAttribute('title')).toBe(BOTH);
  });
});

describe('EmbeddingVizManager (admin dashboard)', () => {
  beforeAll(() => loadScript('js/embedding-viz.js', 'EmbeddingVizManager'));

  test('instance id, majority label and image preview stay inert', () => {
    const Manager = window.EmbeddingVizManager;
    document.body.insertAdjacentHTML('beforeend', '<div id="embedding-viz-preview"></div>');
    const viz = Object.create(Manager.prototype);
    viz.data = { label_colors: {} };
    viz.updatePreviewPanel({
      instance_id: BOTH, label: TAG, preview_type: 'image',
      preview: 'a.png" onerror="window.__pwned=1', annotation_count: 1,
    });
    const panel = document.getElementById('embedding-viz-preview');
    expect(handlerAttrs(panel)).toEqual([]);
    expect(panel.querySelectorAll('img').length).toBe(1);
    expect(panel.querySelector('img').getAttribute('src')).toBe('a.png" onerror="window.__pwned=1');
    expect(panel.querySelector('strong').textContent).toBe(BOTH);
  });
});

describe('Agent trace viewers (annotation page)', () => {
  test('web agent step coordinates from item data stay text', () => {
    loadScript('web-agent-viewer.js');
    const viewer = Object.create(window.WebAgentViewer.prototype);
    viewer.detailsPanel = document.createElement('div');
    viewer._updateDetails({ action_type: 'click', coordinates: { x: TAG, y: 1 } }, 0);
    expect(viewer.detailsPanel.querySelector('img')).toBeNull();
    expect(viewer.detailsPanel.querySelector('.step-coords').textContent).toContain(TAG);
  });

  test('live agent action type from the model stays text', () => {
    loadScript('live-agent-viewer.js');
    const viewer = Object.create(window.LiveAgentViewer.prototype);
    viewer.stepDetailsContent = document.createElement('div');
    viewer._updateStepDetails({ action_type: TAG });
    expect(viewer.stepDetailsContent.querySelector('img')).toBeNull();
    expect(viewer.stepDetailsContent.textContent).toContain(TAG);
  });
});

/**
 * Closure-private escapers. The modules expose no renderer to call, so the
 * test lifts the helper's own source out of the file and runs it.
 */
// Template paths are relative to STATIC: ../templates/<file>.
const DASH_ESC = /function esc\(s\) \{[\s\S]*?\n    \}/;

describe.each([
  ['codebook.js', /function esc\(s\) \{[\s\S]*?\n    \}/, 'esc'],
  ['search.js', /function esc\(s\) \{[\s\S]*?\n    \}/, 'esc'],
  ['multi-document-event.js', /function esc\(s\) \{[\s\S]*?\n  \}/, 'esc'],
  ['corpus-map.js', /const esc = \(v\) =>[\s\S]*?;\n/, 'esc'],
  ['entity-linking.js', /function escapeHtml\(text\) \{[\s\S]*?\n    \}/, 'escapeHtml'],
  ['../templates/psychometrics_dashboard.html', DASH_ESC, 'esc'],
  ['../templates/truth_serum_dashboard.html', DASH_ESC, 'esc'],
  ['../templates/boundary_dashboard.html', DASH_ESC, 'esc'],
  ['../templates/thinkaloud_review.html', DASH_ESC, 'esc'],
])('%s escaper', (file, pattern, name) => {
  test('escapes quotes, so an attribute value cannot break out', () => {
    const src = fs.readFileSync(path.join(STATIC, file), 'utf8');
    const m = src.match(pattern);
    expect(m).not.toBeNull();
    // eslint-disable-next-line no-new-func
    const esc = new Function(m[0] + '\nreturn ' + name + ';')();
    const div = render('<b data-v="' + esc(BOTH) + '">' + esc(BOTH) + '</b>');
    expect(handlerAttrs(div)).toEqual([]);
    expect(div.querySelector('img')).toBeNull();
    expect(div.querySelector('b').getAttribute('data-v')).toBe(BOTH);
  });
});

describe('extractive QA restore (annotation page)', () => {
  test('a passage holding markup is restored as text', () => {
    const src = fs.readFileSync(path.join(STATIC, 'annotation.js'), 'utf8');
    const state = {};
    // eslint-disable-next-line no-new-func
    const restore = new Function('currentAnnotations', 'debugLog',
      extractFunction(src, 'restoreExtractiveQaAnnotations') +
      '\nreturn restoreExtractiveQaAnnotations;')(state, () => {});
    document.body.insertAdjacentHTML('beforeend', `
      <form class="shadcn-extractive-qa-container" data-schema-name="qa">
        <span id="qa-answer-text"></span>
        <div id="qa-passage"></div>
        <input type="hidden" class="eqa-data-input" label_name="answer">
      </form>`);
    const passage = 'Paris ' + TAG + ' is the capital';
    document.getElementById('qa-passage').textContent = passage;
    state.qa = { answer: JSON.stringify({ answer_text: 'Paris', start: 0, end: 5 }) };
    restore();
    const container = document.getElementById('qa-passage');
    expect(container.querySelector('img')).toBeNull();
    expect(container.textContent).toBe(passage);
    expect(container.querySelector('.eqa-highlight').textContent).toBe('Paris');
  });
});

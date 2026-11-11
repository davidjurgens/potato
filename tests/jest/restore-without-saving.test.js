/**
 * Showing a stored answer is not answering.
 *
 * annotation.js's restore pass redraws a scheme from the answer the page
 * holds: its own on load, or a teammate's in a live session. Three schemes
 * got that wrong, found by the live-session sweep:
 *
 * - text_edit and trajectory_edit redrew through their input handlers, which
 *   mark the input modified and fire `change`, so every load (and every
 *   teammate's edit shown live) was saved back as this annotator's edit.
 *   trajectory_edit also rewrote the stored answer with an entry for every
 *   text box, edited or not.
 * - hierarchical_multiselect checked a teammate's nested labels but left
 *   their branches collapsed, where a reload opens them.
 *
 * The schemes' scripts are generated inline by Python, so these tests render
 * them with python and run them next to the restore functions from
 * annotation.js.
 */

const fs = require('fs');
const path = require('path');
const {execFileSync} = require('child_process');

const REPO = path.join(__dirname, '..', '..');
const ANNOTATION_JS = fs.readFileSync(path.join(REPO, 'potato', 'static', 'annotation.js'), 'utf8');

function render(module, fn, scheme) {
    const code = `
import json, sys
from potato.server_utils.schemas.${module} import ${fn}
html, _ = ${fn}(json.loads(sys.argv[1]))
sys.stdout.write(html)
`;
    return execFileSync('python', ['-c', code, JSON.stringify(scheme)],
        {cwd: REPO, encoding: 'utf8', stdio: ['pipe', 'pipe', 'ignore']});
}

function extractFunction(name) {
    const start = ANNOTATION_JS.indexOf(`function ${name}(`);
    if (start === -1) throw new Error(`${name}() not found in annotation.js`);
    const open = ANNOTATION_JS.indexOf('{', start);
    let depth = 0;
    for (let j = open; j < ANNOTATION_JS.length; j++) {
        if (ANNOTATION_JS[j] === '{') depth++;
        else if (ANNOTATION_JS[j] === '}' && --depth === 0) return ANNOTATION_JS.slice(start, j + 1);
    }
    throw new Error(`unbalanced braces reading ${name}()`);
}

/** annotation.js's restore functions, run against ``answers``. */
function restorer(names, answers) {
    const body = names.map(extractFunction).join('\n');
    return new Function('answers', `
        const currentAnnotations = answers;
        function debugLog() {}
        ${body}
        return {${names.join(', ')}};
    `)(answers);
}

/** Put the scheme in the page and run its inline script. */
function mount(html, before = '') {
    const scripts = [];
    document.body.innerHTML = before + html.replace(/<script>([\s\S]*?)<\/script>/g, (_m, s) => {
        scripts.push(s);
        return '';
    });
    scripts.forEach((s) => new Function(s)());
}

let changes;
const record = (e) => changes.push(e.target);
beforeEach(() => {
    document.body.innerHTML = '';
    changes = [];
    document.addEventListener('change', record, true);
});
afterEach(() => document.removeEventListener('change', record, true));

describe('text_edit', () => {
    const SCHEME = {annotation_type: 'text_edit', name: 'post_edit', description: 'Fix it.',
                    source_field: 'text'};
    const STORED = JSON.stringify({edited_text: 'the cat sat down', original_text: 'the cat sat',
                                   edit_distance_chars: 5, edit_distance_words: 1});

    function page() {
        mount(render('text_edit', 'generate_text_edit_layout', SCHEME));
        document.getElementById('post_edit-source-text').textContent = 'the cat sat';
        changes.length = 0;
    }

    test('restoring a stored edit shows it without saving it', () => {
        page();
        const {restoreTextEditAnnotations} = restorer(['restoreTextEditAnnotations'],
            {post_edit: {post_edit: STORED}});
        restoreTextEditAnnotations();
        expect(document.querySelector('.text-edit-textarea').value).toBe('the cat sat down');
        expect(document.getElementById('post_edit-word-dist').textContent).toBe('1');
        expect(changes).toEqual([]);
    });

    test('typing still saves', () => {
        page();
        const editor = document.querySelector('.text-edit-textarea');
        editor.value = 'the dog sat';
        window.textEditOnInput('post_edit');
        expect(changes).toHaveLength(1);
        expect(document.querySelector('.text-edit-data-input').getAttribute('data-modified')).toBe('true');
    });
});

describe('trajectory_edit', () => {
    const SCHEME = {annotation_type: 'trajectory_edit', name: 'fixed', description: 'Correct the trace.'};
    const INSTANCE = {steps: [{action: 'search(queyr)'}, {action: 'open(page)'}]};
    const STORED = JSON.stringify({
        steps: [{step_index: 0, field: 'action', original_text: 'search(queyr)',
                 edited_text: 'search(query)', edited: true, edit_distance_chars: 2,
                 edit_distance_words: 1, reason: ''}],
        final_answer: null, n_steps_edited: 1, total_edit_distance: 2,
    });

    function page(stored = '') {
        const holder = `<div data-instance-json='${JSON.stringify(INSTANCE)}'></div>`;
        mount(render('trajectory_edit', 'generate_trajectory_edit_layout', SCHEME)
            .replace('value="">', `value='${stored}'${stored ? ' data-server-set="true"' : ''}>`), holder);
        return document.querySelector('.trajectory-edit-data-input');
    }

    test('a page that loads a stored edit shows it without saving it', () => {
        const input = page(STORED);
        expect(document.querySelector('.trajedit-textarea[data-step="0"]').value).toBe('search(query)');
        expect(document.getElementById('fixed-n-edited').textContent).toBe('1');
        expect(changes).toEqual([]);
        expect(input.value).toBe(STORED);
    });

    test("restoring a teammate's edit shows it without saving or rewriting it", () => {
        const input = page();
        changes.length = 0;
        const {restoreTrajectoryEditAnnotations} = restorer(['restoreTrajectoryEditAnnotations'],
            {fixed: {fixed: STORED}});
        restoreTrajectoryEditAnnotations();
        expect(document.querySelector('.trajedit-textarea[data-step="0"]').value).toBe('search(query)');
        expect(changes).toEqual([]);
        // Not rebuilt with an entry for the step nobody edited.
        expect(JSON.parse(input.value).steps).toHaveLength(1);
    });

    test('typing still saves', () => {
        page();
        changes.length = 0;
        const ta = document.querySelector('.trajedit-textarea[data-step="1"]');
        ta.value = 'open(other)';
        ta.dispatchEvent(new Event('input', {bubbles: true}));
        expect(changes).toHaveLength(1);
    });
});

describe('hierarchical_multiselect', () => {
    const SCHEME = {annotation_type: 'hierarchical_multiselect', name: 'topics', description: 'Topics.',
                    taxonomy: {Science: {Biology: ['Genetics', 'Ecology'], Physics: []}, Arts: []}};

    test("a teammate's nested label is shown with its branches open, as on a reload", () => {
        mount(render('hierarchical_multiselect', 'generate_hierarchical_multiselect_layout', SCHEME));
        const {restoreHierarchicalAnnotations} = restorer(
            ['splitKnownValues', 'restoreHierarchicalAnnotations'], {topics: {selected_labels: 'Genetics'}});
        restoreHierarchicalAnnotations();
        const genetics = document.querySelector('.hier-checkbox[value="Genetics"]');
        expect(genetics.checked).toBe(true);
        let branch = genetics.closest('.hier-children');
        const opened = [];
        while (branch) {
            expect(branch.style.display).toBe('block');
            const toggle = branch.closest('.hier-node').querySelector(':scope > .hier-node-row .hier-toggle');
            expect(toggle.getAttribute('aria-expanded')).toBe('true');
            opened.push(branch.closest('.hier-node').querySelector('.hier-label-text').textContent.trim());
            branch = branch.closest('.hier-node').parentElement.closest('.hier-children');
        }
        expect(opened).toEqual(['Biology', 'Science']);
    });

    test('a page that loads a nested label says its branches are expanded', () => {
        const html = render('hierarchical_multiselect', 'generate_hierarchical_multiselect_layout', SCHEME);
        mount(html.replace(/(hier-selected-input"[^>]*?)value=""/, '$1value="Genetics"'));
        const biology = document.querySelector('.hier-checkbox[value="Genetics"]')
            .closest('.hier-children').closest('.hier-node');
        expect(biology.querySelector(':scope > .hier-node-row .hier-toggle').getAttribute('aria-expanded'))
            .toBe('true');
    });
});

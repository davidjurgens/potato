/**
 * conversation-tree.js wrote values nothing read, and read values nothing wrote.
 *
 * `savePathData()` set a hidden input that carried no `annotation-input` class,
 * so `syncAnnotationsFromDOM` never collected it and `tree_annotation` stored
 * nothing under any configuration. Nothing restored either half on a revisit,
 * so returning to an annotated tree showed an empty path over stored answers --
 * and the first click then overwrote them.
 */

const fs = require('fs');
const path = require('path');

const SOURCE = path.join(__dirname, '..', '..', 'potato', 'static', 'conversation-tree.js');

let src;
beforeAll(() => { src = fs.readFileSync(SOURCE, 'utf8'); });

function page({path: storedPath = '', nodes = ''} = {}) {
    document.body.innerHTML = `
      <form id="thread" class="tree-ann-container annotation-form"
            data-tree-ann-config='${JSON.stringify({
                schemaName: 'thread',
                nodeScheme: {annotation_type: 'likert'},
                pathSelection: {enabled: true, description: 'pick'},
                branchComparison: {enabled: false},
            })}'>
        <div class="tree-ann-node-panel" id="thread_node_panel" style="display:none">
          <strong id="thread_active_node"></strong>
          <button type="button" id="thread_close_panel">x</button>
          <div class="tree-ann-node-panel-body" id="thread_node_panel_body"></div>
        </div>
        <div class="tree-ann-selected-path" id="thread_selected_path"></div>
        <button type="button" id="thread_clear_path">Clear</button>
        <input type="hidden" class="annotation-input tree-ann-node-input"
               id="thread_node_annotations" value='${nodes}'>
        <input type="hidden" class="annotation-input tree-ann-path-input"
               id="thread_selected_path_data" value='${storedPath}'>
      </form>
      <div class="conv-tree-root">
        <div class="conv-tree-node" data-node-id="a">
          <span class="conv-tree-speaker">alex</span>
          <span class="conv-tree-node-text">root</span>
        </div>
        <div class="conv-tree-node" data-node-id="b">
          <span class="conv-tree-speaker">sam</span>
          <span class="conv-tree-node-text">reply</span>
        </div>
      </div>`;
}

/** Run the module the way the page does. */
function boot() {
    new Function(src)();
}

const node = id => document.querySelector(`.conv-tree-node[data-node-id="${id}"]`);
const pathInput = () => document.getElementById('thread_selected_path_data');
const nodeInput = () => document.getElementById('thread_node_annotations');

describe('the values it writes are the ones the page collects', () => {
    beforeEach(() => { page(); boot(); });

    test('clicking a node records it on the path input', () => {
        node('b').click();
        expect(JSON.parse(pathInput().value)).toEqual(['b']);
    });

    test('the input is flagged modified, so it counts as an answer', () => {
        node('b').click();
        expect(pathInput().getAttribute('data-modified')).toBe('true');
    });

    test('it dispatches change, which is what triggers the autosave', () => {
        let fired = 0;
        pathInput().addEventListener('change', () => { fired++; });
        node('b').click();
        expect(fired).toBe(1);
    });

    test('clearing the path empties the input rather than storing "[]"', () => {
        node('b').click();
        document.getElementById('thread_clear_path').click();
        expect(pathInput().value).toBe('');
    });

    test('clicking a node twice takes it off the path again', () => {
        node('b').click();
        node('b').click();
        expect(pathInput().value).toBe('');
        expect(node('b').classList.contains('on-path')).toBe(false);
    });
});

describe('what the server sent back is adopted before anything is clicked', () => {
    test('a stored path is restored to the input and to the tree', () => {
        page({path: '["b","a"]'});
        boot();

        expect(node('b').classList.contains('on-path')).toBe(true);
        expect(node('a').classList.contains('on-path')).toBe(true);
        expect(document.getElementById('thread_selected_path').textContent)
            .toBe('b → a');
    });

    test('restoring does not mark the input modified', () => {
        // Arriving at an item is not answering it.
        page({path: '["b"]'});
        boot();
        expect(pathInput().getAttribute('data-modified')).toBeNull();
    });

    test('nodes that already carry an answer are marked', () => {
        page({nodes: '{"b":{"node_quality":"4"}}'});
        boot();

        expect(node('b').classList.contains('has-annotation')).toBe(true);
        expect(node('a').classList.contains('has-annotation')).toBe(false);
    });

    test('a malformed stored value does not take the tree down with it', () => {
        page({path: 'not json', nodes: '{{{'});
        expect(() => boot()).not.toThrow();
        expect(document.querySelectorAll('.conv-tree-node.selectable').length).toBe(2);
    });

    test('clicking after a restore extends the stored path rather than replacing it', () => {
        page({path: '["a"]'});
        boot();
        node('b').click();
        expect(JSON.parse(pathInput().value)).toEqual(['a', 'b']);
    });
});

describe('the node panel', () => {
    beforeEach(() => { page(); boot(); });

    test('opens on a node click and names the node', () => {
        node('b').click();
        expect(document.getElementById('thread_node_panel').style.display).toBe('block');
        expect(document.getElementById('thread_active_node').textContent)
            .toContain('reply');
    });

    test('says so when the scheme has no node_scheme', () => {
        // No template rendered, because there is nothing to render.
        node('b').click();
        expect(document.getElementById('thread_node_panel_body').textContent)
            .toMatch(/nothing to annotate/i);
    });

    test('says so when the question form failed to load', () => {
        // The two are different problems and used to look identical: an empty
        // box under the words "Node annotation type: likert".
        document.body.insertAdjacentHTML('beforeend',
            '<template id="segment-questions-template-thread"></template>');
        node('b').click();
        expect(document.getElementById('thread_node_panel_body').textContent)
            .toMatch(/could not be loaded/i);
    });
});

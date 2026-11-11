/**
 * Live sessions: tree_annotation shows a teammate's path and node answers
 * without a reload (conversation-tree.js registers the applier), and the node
 * panel keeps one listener per node shown.
 *
 * The form is tree_annotation.py's own output (with a likert node_scheme, so
 * it carries the segment-questions <template>); the tree is the conversation
 * tree display's node markup.
 */

const { loadStatic, bootCollab, applyTeam, watchSaves, countChanges } = require('./misc-collab-harness');

const FORM = `
    <form id="thread" class="tree-ann-container annotation-form"
         action="javascript:void(0)"
         data-annotation-type="tree_annotation"
         data-schema-name="thread"
         data-annotation-id="thread"
         data-tree-ann-config='{&quot;schemaName&quot;: &quot;thread&quot;, &quot;nodeScheme&quot;: {&quot;annotation_type&quot;: &quot;likert&quot;, &quot;name&quot;: &quot;q&quot;, &quot;description&quot;: &quot;q&quot;, &quot;size&quot;: 3, &quot;min_label&quot;: &quot;a&quot;, &quot;max_label&quot;: &quot;b&quot;}, &quot;pathSelection&quot;: {&quot;enabled&quot;: true, &quot;description&quot;: &quot;pick&quot;, &quot;emptyText&quot;: &quot;No path selected. Click on nodes in the tree to build a path.&quot;}, &quot;branchComparison&quot;: {&quot;enabled&quot;: false}}'
         data-grid-columns="1">

        <div class="tree-ann-header">
            <h4 class="tree-ann-title">Tree</h4>
        </div>

        
        <div class="tree-ann-node-mode">
            <p class="tree-ann-hint">Click a node in the tree above to annotate it.
            Node annotation type: <strong>likert</strong></p>
        </div>
        

        <!-- Node Annotation Panel (shown when a node is selected) -->
        <div class="tree-ann-node-panel" id="thread_node_panel"
             style="display:none">
            <div class="tree-ann-node-panel-header">
                <span class="tree-ann-node-panel-title">Annotating node: <strong id="thread_active_node"></strong></span>
                <button type="button" class="tree-ann-btn tree-ann-close-panel"
                        id="thread_close_panel">&times;</button>
            </div>
            <div class="tree-ann-node-panel-body" id="thread_node_panel_body">
            </div>
        </div>

        
        <div class="tree-ann-path-selection">
            <h5 class="tree-ann-section-title">Path Selection</h5>
            <p class="tree-ann-path-desc">pick</p>
            <div class="tree-ann-selected-path" id="thread_selected_path">
                <span class="tree-ann-no-path">No path selected. Click on nodes in the tree to build a path.</span>
            </div>
            <button type="button" class="tree-ann-btn tree-ann-clear-path"
                    id="thread_clear_path">Clear Path</button>
        </div>
        

        <template id="segment-questions-template-thread" class="segment-questions-template"><div class="segment-question" data-segment-scheme="q">
    <form id="q" class="annotation-form likert shadcn-likert-container" action="javascript:void(0)" data-annotation-id="thread_segment_0" data-annotation-type="likert" data-schema-name="q" data-grid-columns="1">
        
        <fieldset schema="q">
            <legend class="shadcn-likert-title">q</legend>
            <div class="shadcn-likert-scale" style="max-width: min(100%, calc(300px + 3 * 40px + 250px));">
                <div class="shadcn-likert-endpoint">a</div>
                <div class="shadcn-likert-options">
                    <div class="shadcn-likert-track"></div>
    
                    <div class="shadcn-likert-option">
                        <input class="q shadcn-likert-input annotation-input"
                               type="radio"
                               id="q_1_radio"
                               name="q"
                               value="1"
                               schema="q"
                               label_name="1"
                               selection_constraint="single"
                               validation=""
                               
                               onclick="onlyOne(this);registerAnnotation(this);">
                        <label class="shadcn-likert-button" for="q_1_radio"></label>
                        <span class="shadcn-likert-label">1</span>
                    </div>
        
                    <div class="shadcn-likert-option">
                        <input class="q shadcn-likert-input annotation-input"
                               type="radio"
                               id="q_2_radio"
                               name="q"
                               value="2"
                               schema="q"
                               label_name="2"
                               selection_constraint="single"
                               validation=""
                               
                               onclick="onlyOne(this);registerAnnotation(this);">
                        <label class="shadcn-likert-button" for="q_2_radio"></label>
                        <span class="shadcn-likert-label">2</span>
                    </div>
        
                    <div class="shadcn-likert-option">
                        <input class="q shadcn-likert-input annotation-input"
                               type="radio"
                               id="q_3_radio"
                               name="q"
                               value="3"
                               schema="q"
                               label_name="3"
                               selection_constraint="single"
                               validation=""
                               
                               onclick="onlyOne(this);registerAnnotation(this);">
                        <label class="shadcn-likert-button" for="q_3_radio"></label>
                        <span class="shadcn-likert-label">3</span>
                    </div>
        
                </div>
                <div class="shadcn-likert-endpoint">b</div>
            </div>
    
        </fieldset></form>
    </div></template>

        <!-- The two values this scheme collects.
             \`class="annotation-input"\` is what makes syncAnnotationsFromDOM read
             them; without it conversation-tree.js wrote to inputs nothing ever
             looked at, and the scheme stored nothing under any configuration.
             Both start empty rather than at "{}" / "[]", so an untouched tree
             is unanswered rather than answered with a blank. -->
        <input type="hidden" class="annotation-input tree-ann-node-input"
               name="thread:::node_annotations"
               id="thread_node_annotations"
               schema="thread" label_name="node_annotations"
               validation="" value="">
        <input type="hidden" class="annotation-input tree-ann-path-input"
               name="thread:::selected_path"
               id="thread_selected_path_data"
               schema="thread" label_name="selected_path"
               validation="" value="">
    </form>
    `;

const TREE = `<div class="conv-tree"><div class="conv-tree-root">
    <div class="conv-tree-node" data-node-id="a"><span class="conv-tree-speaker">alex</span>
        <span class="conv-tree-node-text">root</span>
        <div class="conv-tree-children">
            <div class="conv-tree-node" data-node-id="b"><span class="conv-tree-speaker">sam</span>
                <span class="conv-tree-node-text">reply</span></div>
            <div class="conv-tree-node" data-node-id="c"><span class="conv-tree-speaker">kim</span>
                <span class="conv-tree-node-text">other</span></div>
        </div>
    </div></div></div>`;

let client, calls;

function boot(path, nodes) {
    document.body.innerHTML = '<input type="hidden" id="instance_id" value="item-1">' + TREE + FORM;
    [['thread_selected_path_data', path], ['thread_node_annotations', nodes]].forEach(([id, v]) => {
        if (!v) return;
        const h = document.getElementById(id);
        h.value = v;
        h.setAttribute('data-server-set', 'true');
    });
    delete window.SegmentQuestions;
    delete window.potatoCollabWidgets;
    loadStatic('segment-questions.js');
    loadStatic('conversation-tree.js');
    ({ client, calls } = bootCollab());
}

const node = (id) => document.querySelector(`.conv-tree-node[data-node-id="${id}"]`);
const onPath = () => ['a', 'b', 'c'].filter((id) => node(id).classList.contains('on-path'));
const answered = () => ['a', 'b', 'c'].filter((id) => node(id).classList.contains('has-annotation'));
const pathText = () => document.getElementById('thread_selected_path').textContent.trim();
const panelRadio = (v) => document.querySelector(`#thread_node_panel_body input[type="radio"][value="${v}"]`);
// A click on a nested node also reaches its ancestors; the handlers stop it.
const clickNode = (id) => node(id).querySelector('.conv-tree-node-text').click();

describe('tree_annotation live applier', () => {
    test('the page draws its own answer first', () => {
        boot('["a","b"]', '{"a":{"q":"1"}}');
        expect(onPath()).toEqual(['a', 'b']);
        expect(answered()).toEqual(['a']);
    });

    test("a teammate's answer replaces the path and the marks", () => {
        boot('["a","b"]', '{"a":{"q":"1"}}');
        const shown = applyTeam(client, 'thread', {
            selected_path: '["c"]', node_annotations: '{"c":{"q":"3"}}',
        });
        expect(shown.has('L:thread:::selected_path')).toBe(true);
        expect(shown.has('L:thread:::node_annotations')).toBe(true);
        expect(onPath()).toEqual(['c']);
        expect(answered()).toEqual(['c']);
        expect(pathText()).toBe('c');
    });

    test('no answer clears the path and every mark', () => {
        boot('["a","b"]', '{"a":{"q":"1"}}');
        applyTeam(client, 'thread', null, ['selected_path', 'node_annotations']);
        expect(onPath()).toEqual([]);
        expect(answered()).toEqual([]);
        expect(pathText()).toMatch(/No path selected/);
    });

    test('a cleared path reads as the page reads with no path on load', () => {
        boot('', '');
        const onLoad = pathText();
        expect(onLoad).toBe('No path selected. Click on nodes in the tree to build a path.');
        boot('["a","b"]', '');
        applyTeam(client, 'thread', null, ['selected_path', 'node_annotations']);
        expect(pathText()).toBe(onLoad);
        // Emptying the path by hand says the same.
        boot('', '');
        clickNode('b');
        expect(pathText()).toBe('b');
        clickNode('b');
        expect(pathText()).toBe(onLoad);
    });

    test('an open node panel shows the teammate answer for that node', () => {
        boot('', '{"b":{"q":"1"}}');
        clickNode('b');
        expect(panelRadio('1').checked).toBe(true);
        applyTeam(client, 'thread', { selected_path: '["b"]', node_annotations: '{"b":{"q":"3"}}' });
        expect(panelRadio('3').checked).toBe(true);
        expect(panelRadio('1').checked).toBe(false);
    });

    test('applying saves nothing; twice, one click is one path step', () => {
        boot('["a"]', '');
        const watch = watchSaves(calls);
        const path = document.getElementById('thread_selected_path_data');
        const nodes = document.getElementById('thread_node_annotations');
        const changes = countChanges(path);
        const nodeChanges = countChanges(nodes);
        const team = { selected_path: '["b"]', node_annotations: '{"b":{"q":"2"}}' };
        applyTeam(client, 'thread', team);
        applyTeam(client, 'thread', team);
        expect(changes.n + nodeChanges.n).toBe(0);
        expect(path.hasAttribute('data-modified')).toBe(false);
        expect(watch.posts()).toHaveLength(0);
        expect(watch.saveAnnotations).not.toHaveBeenCalled();
        clickNode('c');
        expect(changes.n).toBe(1);
        expect(JSON.parse(path.value)).toEqual(['b', 'c']);
    });
});

describe('the node panel', () => {
    test("answering one node never writes another node's answer", () => {
        // Every render bound SegmentQuestions' listeners on the one panel
        // body, so the panel for node a kept collecting after node b opened.
        boot('', '');
        clickNode('b');
        clickNode('c');
        panelRadio('3').click();
        expect(JSON.parse(document.getElementById('thread_node_annotations').value)).toEqual({ c: { q: '3' } });
        expect(answered()).toEqual(['c']);
    });
});

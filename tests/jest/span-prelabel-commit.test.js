/**
 * Span prelabels the annotator keeps are stored as theirs.
 *
 * /api/spans hands the span manager a model's spans, flagged `prelabel`,
 * while the annotator has none of their own on the item. Before, the page
 * showed them as markup the span manager did not hold: they could not be
 * edited, and Next stored none of them, though every other type stores its
 * untouched prelabel (audit 98, D7).
 */

const { SpanManager } = require('../../potato/static/span-core.js');

function ok(body = {}) {
    return Promise.resolve({ok: true, status: 200, json: async () => body,
                            text: async () => JSON.stringify(body)});
}

function manager(spans) {
    const m = new SpanManager();
    m.renderSpans = jest.fn();
    m.clearAllStateAndOverlays = jest.fn();
    m.loadAnnotations = jest.fn();
    m.currentInstanceId = 's1';
    m.currentSchema = 'people';
    m.annotations = {spans};
    return m;
}

const PRELABEL = [
    {id: 'p1', schema: 'people', label: 'PERSON', start: 0, end: 12, prelabel: true},
    {id: 'p2', schema: 'people', label: 'PERSON', start: 17, end: 32, prelabel: true},
];

beforeEach(() => {
    global.fetch = jest.fn(() => ok());
});

test('commitPrelabels stores every kept prelabel in one request', async () => {
    const m = manager(PRELABEL.map(s => ({...s})));
    await m.commitPrelabels();
    expect(global.fetch).toHaveBeenCalledTimes(1);
    const body = JSON.parse(global.fetch.mock.calls[0][1].body);
    expect(body).toMatchObject({type: 'span', schema: 'people', instance_id: 's1'});
    expect(body.state.map(s => [s.start, s.end, s.value])).toEqual([[0, 12, 1], [17, 32, 1]]);
    expect(m.annotations.spans.every(s => !s.prelabel)).toBe(true);
    await m.commitPrelabels();
    expect(global.fetch).toHaveBeenCalledTimes(1);   // nothing left to store
});

test('saving a span of their own stores the kept prelabels first', async () => {
    const m = manager(PRELABEL.map(s => ({...s})));
    await m.saveSpan({label: 'PERSON', schema: 'people', start: 36, end: 42, id: 'own'});
    const bodies = global.fetch.mock.calls.map(c => JSON.parse(c[1].body));
    expect(bodies[0].state.length).toBe(2);           // the prelabels
    expect(bodies[1].state[0]).toMatchObject({start: 36, end: 42});
});

test('deleting a prelabel span never reaches the server', async () => {
    document.body.innerHTML = '<div id="span-overlays"></div>';
    const m = manager(PRELABEL.map(s => ({...s})));
    await m.deleteSpan('p1');
    expect(global.fetch).not.toHaveBeenCalled();
    expect(m.annotations.spans.map(s => s.id)).toEqual(['p2']);
    await m.commitPrelabels();
    const body = JSON.parse(global.fetch.mock.calls[0][1].body);
    expect(body.state.map(s => s.start)).toEqual([17]);
});

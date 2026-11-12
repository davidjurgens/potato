/**
 * audio_annotation in a live collaborative session (collab.js applyWidget).
 *
 * The session client used to redraw a teammate's segments itself, through
 * the widget's first-load path: every restored segment saved, fired a change
 * and took the selection, a cleared answer was written back as
 * '{"segments":[]}', and max_segments could refuse a teammate's segment. The
 * widget now registers its own applier, which replaces the segments without
 * saving.
 *
 * The REAL audio-annotation.js and collab.js run here (Peaks is stubbed).
 */

const fs = require('fs');
const path = require('path');

const STATIC = path.join(__dirname, '..', '..', 'potato', 'static');

const MARKUP = `
    <input id="instance_id" type="hidden" value="i1">
    <form id="calls" class="annotation-form audio-annotation" action="javascript:void(0)"
          data-annotation-type="audio_annotation" data-schema-name="calls">
        <div class="audio-annotation-container" data-schema="calls">
            <div id="overview-calls"></div><div id="waveform-calls"></div>
            <audio id="audio-calls"></audio>
            <div id="segments-calls"></div>
        </div>
        <input type="hidden" class="annotation-data-input" id="input-calls" name="calls" value="">
    </form>`;

const seg = (id, start, end, label, extra) => Object.assign(
    { id, start_time: start, end_time: end, label, annotations: {} }, extra || {});

let peaksSegments;
let manager;
let changes;
let client;

function boot(answer, config) {
    document.body.innerHTML = MARKUP;
    window.fetch = jest.fn(() => Promise.resolve({ ok: true, status: 200,
        json: () => Promise.resolve({ events: [], cursor: 0 }), clone() { return this; } }));
    window.potatoCollab = { sid: 'RED', me: 'ben', instance_id: 'i1', rev: 1, cursor: 0,
                            team_user: 'team-red', transport: 'poll', poll_interval_ms: 100000, base: '' };
    delete window.potatoCollabClient;
    delete window.potatoCollabWidgets;
    jest.isolateModules(() => require('../../potato/static/audio-annotation.js'));
    // eslint-disable-next-line no-new-func
    new Function(fs.readFileSync(path.join(STATIC, 'collab.js'), 'utf8'))();
    client = window.potatoCollabClient;
    window.fetch.mockClear = () => {};   // jest's resetMocks reaches the wrapped fetch

    const container = document.querySelector('.audio-annotation-container');
    manager = new window.AudioAnnotationManager({
        container, waveformId: 'waveform-calls', overviewId: 'overview-calls',
        audioId: 'audio-calls', segmentListId: 'segments-calls',
        config: Object.assign({ schemaName: 'calls', labels: [{ name: 'song', color: '#2563eb' }] }, config || {}),
    });
    container.audioAnnotationManager = manager;
    peaksSegments = new Map();
    manager.peaks = { segments: {
        add: (o) => { peaksSegments.set(o.id, o); return o; },
        getSegment: (id) => peaksSegments.get(id) && { update() {}, color: '#000' },
        removeById: (id) => peaksSegments.delete(id),
    } };
    manager.inputEl = document.getElementById('input-calls');
    if (answer) {
        manager.inputEl.value = JSON.stringify({ segments: answer });
        manager._loadExistingAnnotations();
    }
    changes = 0;
    manager.inputEl.addEventListener('change', () => { changes += 1; });
}

function apply(answer) {
    const value = answer ? JSON.stringify({ segments: answer }) : undefined;
    return client.applyKeys(new Set(['L:calls:::_data']), value ? { 'L:calls:::_data': value } : {});
}

test("a teammate's segments replace this page's, with their answers", () => {
    boot([seg('a', 0, 1, 'song')]);
    const shown = apply([seg('b', 2, 3, 'song', { annotations: { q: 'yes' } }), seg('c', 4, 5, 'song')]);
    expect(shown.has('L:calls:::_data')).toBe(true);
    expect(manager.segments.map((s) => s.id)).toEqual(['b', 'c']);
    expect([...peaksSegments.keys()]).toEqual(['b', 'c']);
    expect(manager.segments[0].annotations).toEqual({ q: 'yes' });
    expect(document.getElementById('segments-calls').textContent).not.toBe('');
});

test('applying saves nothing and leaves the selection alone', () => {
    boot([seg('a', 0, 1, 'song'), seg('k', 6, 7, 'song')]);
    manager.selectSegment('k');
    const save = jest.spyOn(manager, '_saveData');
    apply([seg('k', 6, 7, 'song'), seg('b', 2, 3, 'song')]);
    expect(save).not.toHaveBeenCalled();
    expect(changes).toBe(0);
    expect(manager.activeSegmentId).toBe('k');
});

test('a cleared answer clears the segments and the input', () => {
    boot([seg('a', 0, 1, 'song')]);
    apply(null);
    expect(manager.segments).toEqual([]);
    expect(peaksSegments.size).toBe(0);
    expect(manager.inputEl.value).toBe('');
    expect(manager.activeSegmentId).toBe(null);
});

test("max_segments does not refuse a teammate's segments", () => {
    boot([seg('a', 0, 1, 'song')], { maxSegments: 1 });
    apply([seg('a', 0, 1, 'song'), seg('b', 2, 3, 'song')]);
    expect(manager.segments.map((s) => s.id)).toEqual(['a', 'b']);
});

test('applying twice duplicates nothing', () => {
    boot();
    const answer = [seg('b', 2, 3, 'song')];
    apply(answer);
    apply(answer);
    expect(manager.segments).toHaveLength(1);
    expect(peaksSegments.size).toBe(1);
});

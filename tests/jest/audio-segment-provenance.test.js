/**
 * A model's audio segments keep their provenance through the widget.
 *
 * Before: a prelabel segment arrived with source "ai", ai_model and
 * confidence, and the save kept only id, times and label, so an accepted
 * model segment was stored as if the annotator had drawn it. Image shapes
 * kept theirs (audit 98, D16).
 */

require('../../potato/static/audio-annotation.js');
const AudioAnnotationManager = window.AudioAnnotationManager;

function manager() {
    document.body.innerHTML = `
        <div class="audio-annotation-container" data-schema="calls">
            <div id="overview-calls"></div><div id="waveform-calls"></div>
            <audio id="audio-calls"></audio>
        </div>`;
    const m = new AudioAnnotationManager({
        container: document.querySelector('.audio-annotation-container'),
        waveformId: 'waveform-calls', overviewId: 'overview-calls',
        audioId: 'audio-calls', config: {schemaName: 'calls'},
    });
    m.peaks = {segments: {
        add: () => ({}),
        getSegment: () => ({update() {}, color: '#000'}),
        removeById() {},
    }};
    m.inputEl = document.createElement('input');
    return m;
}

const MODEL = {id: 'model_0', start_time: 0.5, end_time: 1.25, label: 'beep',
               source: 'ai', ai_model: 'hf-audio-tagger-calls-r1',
               confidence: 0.91};

test('an accepted model segment is saved with where it came from', () => {
    const m = manager();
    m.deserialize({segments: [MODEL]});
    const saved = m.serialize().segments[0];
    expect(saved).toMatchObject({source: 'ai', ai_model: MODEL.ai_model,
                                 confidence: 0.91});
    expect(saved.edited).toBeUndefined();
    m._saveData();
    expect(JSON.parse(m.inputEl.value).segments[0].source).toBe('ai');
});

test('a prelabel loaded from the page is saved back whole, every segment', () => {
    // Audit 98 re-verify: createSegment saved before provenance was copied,
    // so the last (or only) segment reached the input without it.
    const m = manager();
    const second = {...MODEL, id: 'model_1', start_time: 2, end_time: 3,
                    label: 'music', annotations: {q: 'yes'}};
    m.inputEl.value = JSON.stringify({segments: [MODEL, second]});
    m._loadExistingAnnotations();
    const stored = JSON.parse(m.inputEl.value).segments;
    expect(stored.map(s => [s.id, s.source, s.confidence])).toEqual(
        [['model_0', 'ai', 0.91], ['model_1', 'ai', 0.91]]);
    expect(stored[1].annotations).toEqual({q: 'yes'});
});

test('relabelling a model segment marks it edited', () => {
    const m = manager();
    m.deserialize({segments: [MODEL]});
    m.updateSegmentLabel('model_0', 'chirp');
    expect(m.serialize().segments[0]).toMatchObject({source: 'ai', edited: true,
                                                     label: 'chirp'});
});

test('moving a model segment marks it edited; a human segment is not', () => {
    const m = manager();
    m.deserialize({segments: [MODEL, {id: 'h1', start_time: 2, end_time: 3,
                                      label: 'beep'}]});
    m._onSegmentDragEnd({segment: {id: 'model_0', startTime: 0.4, endTime: 1.25}});
    m._onSegmentDragEnd({segment: {id: 'h1', startTime: 2.1, endTime: 3}});
    const [model, human] = m.serialize().segments;
    expect(model.edited).toBe(true);
    expect(human.edited).toBeUndefined();
    expect(human.source).toBeUndefined();
});

/**
 * The video half of per-class show/hide.
 *
 * Image and video share the state (label-visibility.js) and the label-button
 * markup; each supplies only the function that hides its own artifacts. For
 * video that means removing segments from the Peaks *view* while leaving them
 * in `this.segments`, so a hidden class is still saved and exported.
 */

const VideoAnnotationManager = require('../../potato/static/video-annotation.js');

/** A fake Peaks segments collection that behaves like the real one. */
function fakePeaks() {
    const onTimeline = new Map();
    return {
        segments: {
            add: (s) => onTimeline.set(s.id, s),
            removeById: (id) => onTimeline.delete(id),
            getSegment: (id) => onTimeline.get(id) || null,
        },
        _ids: () => [...onTimeline.keys()],
    };
}

function makeManager(segments) {
    const m = Object.create(VideoAnnotationManager.prototype);
    m.segments = segments;
    m.keyframes = [];
    m.frameAnnotations = {};
    m.tracks = {};
    m.peaks = fakePeaks();
    m.activeAnnotationId = null;
    m.config = {};
    m._updateAnnotationList = jest.fn();
    m._formatTime = (t) => String(t);

    // Everything starts on the timeline, as it would after creation.
    segments.forEach(s => m.peaks.segments.add({
        id: s.id, startTime: s.startTime, endTime: s.endTime,
        labelText: s.label, color: s.color, editable: true,
    }));
    return m;
}

const SEGMENTS = [
    {id: 's1', startTime: 0, endTime: 1, label: 'speech', color: '#f00',
     startFrame: 0, endFrame: 30},
    {id: 's2', startTime: 1, endTime: 2, label: 'music', color: '#0f0',
     startFrame: 30, endFrame: 60},
    {id: 's3', startTime: 2, endTime: 3, label: 'speech', color: '#f00',
     startFrame: 60, endFrame: 90},
];

describe('applyLabelVisibility', () => {
    test('removes every segment of a hidden label from the timeline', () => {
        const m = makeManager(SEGMENTS.map(s => ({...s})));
        m.applyLabelVisibility(new Set(['speech']));
        expect(m.peaks._ids()).toEqual(['s2']);
    });

    test('hidden segments are still stored, so they still save and export', () => {
        const m = makeManager(SEGMENTS.map(s => ({...s})));
        m.applyLabelVisibility(new Set(['speech']));
        expect(m.segments).toHaveLength(3);
    });

    test('showing a class again restores its segments to the timeline', () => {
        const m = makeManager(SEGMENTS.map(s => ({...s})));
        m.applyLabelVisibility(new Set(['speech']));
        m.applyLabelVisibility(new Set());

        expect(m.peaks._ids().sort()).toEqual(['s1', 's2', 's3']);
    });

    test('restored segments keep their timing, label, and colour', () => {
        const m = makeManager(SEGMENTS.map(s => ({...s})));
        m.applyLabelVisibility(new Set(['music']));
        m.applyLabelVisibility(new Set());

        const restored = m.peaks.segments.getSegment('s2');
        expect(restored).toMatchObject({
            id: 's2', startTime: 1, endTime: 2, labelText: 'music', color: '#0f0',
        });
    });

    test('re-applying the same state does not duplicate segments', () => {
        const m = makeManager(SEGMENTS.map(s => ({...s})));
        m.applyLabelVisibility(new Set(['speech']));
        m.applyLabelVisibility(new Set(['speech']));
        expect(m.peaks._ids()).toEqual(['s2']);
    });

    test('the annotation list is refreshed so it matches the timeline', () => {
        // A hidden class still listed reads as "the timeline lost my segment".
        const m = makeManager(SEGMENTS.map(s => ({...s})));
        m._updateAnnotationList.mockClear();
        m.applyLabelVisibility(new Set(['speech']));
        expect(m._updateAnnotationList).toHaveBeenCalled();
    });

    test('works before Peaks is ready', () => {
        const m = makeManager(SEGMENTS.map(s => ({...s})));
        m.peaks = null;
        expect(() => m.applyLabelVisibility(new Set(['speech']))).not.toThrow();
        expect(m.segments).toHaveLength(3);
    });
});

describe('the annotation list', () => {
    test('omits segments whose class is hidden', () => {
        const m = makeManager(SEGMENTS.map(s => ({...s})));
        delete m._updateAnnotationList;

        const list = document.createElement('div');
        list.className = 'annotation-list';
        document.body.appendChild(list);
        m.annotationListEl = list;

        m.hiddenLabels = new Set(['speech']);
        m._updateAnnotationList();

        expect(list.innerHTML).toContain('music');
        expect(list.innerHTML).not.toContain('speech');
        document.body.innerHTML = '';
    });
});

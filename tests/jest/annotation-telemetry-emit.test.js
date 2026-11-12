/**
 * The emitter side: what image-annotation.js reports, and — more importantly —
 * what it must NOT report.
 *
 * Shape creation is derived by diffing two serialized states rather than by
 * instrumenting each commit site. That choice is what keeps the measurement
 * correct as tools are added (twelve tools all end in `_saveState`), but it
 * puts the whole burden on the diff being right about three things:
 *
 *   - the very first save is a baseline, not work
 *   - restoring stored annotations is not the annotator drawing them
 *   - undo/redo restore state without going through _saveState at all
 *
 * Get any of those wrong and a returning annotator appears to have drawn a
 * dozen shapes in zero milliseconds, which is precisely the pattern the
 * rubber-stamping screen looks for. A false positive here accuses someone.
 */

// mask-buffer.js first: image-annotation.js resolves MaskBuffer at load,
// mirroring the script order the template guarantees in the browser.
require('../../potato/static/mask-buffer.js');
const ImageAnnotationManager = require('../../potato/static/image-annotation.js');

/** A manager stripped to the parts the telemetry path touches. */
function makeManager(annotations) {
    const m = Object.create(ImageAnnotationManager.prototype);
    m.config = { schemaName: 'objects' };
    m.history = [];
    m.historyIndex = -1;
    m.maxHistory = 50;
    m.masks = {};
    m._hydrating = false;
    m.state = annotations ? annotations.slice() : [];
    // The one thing _saveState reads. Returning a JSON string matches the real
    // _serializeAnnotations contract.
    m._serializeAnnotations = () => JSON.stringify(m.state);
    return m;
}

/** Capture every emitted event without loading the tracker. */
function captureEmits() {
    const events = [];
    global.window = global.window || {};
    window.recordAnnotationTelemetry = (schema, action, detail) => {
        events.push(Object.assign({ schema, action }, detail || {}));
    };
    return events;
}

describe('image-annotation telemetry emission', () => {
    let emitted;

    beforeEach(() => {
        emitted = captureEmits();
    });

    afterEach(() => {
        delete window.recordAnnotationTelemetry;
    });

    // -----------------------------------------------------------------
    describe('baseline and hydration', () => {
        test('the first save reports nothing', () => {
            const m = makeManager([{ type: 'bbox', coordinates: { x: 0, y: 0, width: 1, height: 1 } }]);
            m._saveState();
            expect(emitted).toEqual([]);
        });

        test('restored annotations are not reported as drawn', () => {
            // Six boxes appearing at once with no elapsed time is exactly what
            // "hasty" looks for. This is the false positive that would accuse
            // an annotator for coming back to their own work.
            const m = makeManager([]);
            m._saveState();                       // baseline: empty canvas

            m.state = Array.from({ length: 6 }, () => ({
                type: 'bbox', coordinates: { x: 0, y: 0, width: 1, height: 1 },
            }));
            m._hydrating = true;
            m._saveState();
            m._hydrating = false;

            expect(emitted).toEqual([]);
        });

        test('drawing after a hydration is still reported', () => {
            const m = makeManager([]);
            m._saveState();
            m._hydrating = true;
            m.state = [{ type: 'bbox', coordinates: {} }];
            m._saveState();
            m._hydrating = false;

            m.state = [...m.state, { type: 'bbox', coordinates: {} }];
            m._saveState();

            expect(emitted).toHaveLength(1);
            expect(emitted[0]).toMatchObject({ action: 'shape_add', shape: 'bbox' });
        });
    });

    // -----------------------------------------------------------------
    describe('shape deltas', () => {
        function seeded(initial) {
            const m = makeManager(initial);
            m._saveState();          // baseline
            emitted.length = 0;
            return m;
        }

        test('an added shape reports its kind and vertex count', () => {
            const m = seeded([]);
            m.state = [{ type: 'polygon', coordinates: [{}, {}, {}, {}, {}] }];
            m._saveState();
            expect(emitted).toEqual([{
                schema: 'objects', action: 'shape_add', shape: 'polygon', value: 5,
            }]);
        });

        test('a bbox reports four corners even though it stores extents', () => {
            const m = seeded([]);
            m.state = [{ type: 'bbox', coordinates: { x: 0, y: 0, width: 1, height: 1 } }];
            m._saveState();
            expect(emitted[0].value).toBe(4);
        });

        test('a mask reports zero vertices, because it has none', () => {
            const m = seeded([]);
            m.state = [{ type: 'mask', rle: { counts: [0, 4], size: [2, 2] } }];
            m._saveState();
            expect(emitted[0]).toMatchObject({ shape: 'mask', value: 0 });
        });

        test('a cuboid sums both faces', () => {
            const m = seeded([]);
            m.state = [{
                type: 'cuboid_2d',
                coordinates: { front: [{}, {}, {}, {}], back: [{}, {}, {}, {}] },
            }];
            m._saveState();
            expect(emitted[0].value).toBe(8);
        });

        test('a removed shape is reported as a removal', () => {
            const m = seeded([{ type: 'bbox', coordinates: {} },
                              { type: 'bbox', coordinates: {} }]);
            m.state = m.state.slice(0, 1);
            m._saveState();
            expect(emitted).toEqual([{
                schema: 'objects', action: 'shape_remove', shape: 'bbox',
            }]);
        });

        test('several shapes added at once each get an event', () => {
            const m = seeded([]);
            m.state = [
                { type: 'bbox', coordinates: {} },
                { type: 'bbox', coordinates: {} },
                { type: 'polygon', coordinates: [{}, {}, {}] },
            ];
            m._saveState();
            expect(emitted.map(e => e.shape).sort()).toEqual(['bbox', 'bbox', 'polygon']);
        });

        test('adding one kind while removing another reports both', () => {
            const m = seeded([{ type: 'bbox', coordinates: {} }]);
            m.state = [{ type: 'mask', rle: {} }];
            m._saveState();
            const byAction = Object.fromEntries(
                emitted.map(e => [e.action, e.shape]));
            expect(byAction).toEqual({ shape_add: 'mask', shape_remove: 'bbox' });
        });

        test('a save that changes nothing reports nothing', () => {
            // Editing a shape in place must not read as create-and-destroy.
            const m = seeded([{ type: 'bbox', coordinates: {} }]);
            m._saveState();
            expect(emitted).toEqual([]);
        });

        test('a malformed state reports nothing rather than throwing', () => {
            // Throwing here would happen inside the save path and lose the
            // annotation itself.
            const m = seeded([]);
            m._serializeAnnotations = () => 'not json at all';
            expect(() => m._saveState()).not.toThrow();
            expect(emitted).toEqual([]);
        });
    });

    // -----------------------------------------------------------------
    describe('history', () => {
        test('undo and redo report themselves and no shape deltas', () => {
            // _restoreState does not call _saveState, so the shapes that
            // reappear must not read as freshly drawn.
            const m = makeManager([]);
            m.history = ['[]', '[{"type":"bbox","coordinates":{}}]'];
            m.historyIndex = 1;
            m._restoreState = () => {};

            m.undo();
            m.redo();

            expect(emitted.map(e => e.action)).toEqual(['undo', 'redo']);
        });

        test('undo at the beginning reports nothing', () => {
            const m = makeManager([]);
            m.history = ['[]'];
            m.historyIndex = 0;
            m._restoreState = () => {};
            m.undo();
            expect(emitted).toEqual([]);
        });

        test('redo at the end reports nothing', () => {
            const m = makeManager([]);
            m.history = ['[]'];
            m.historyIndex = 0;
            m._restoreState = () => {};
            m.redo();
            expect(emitted).toEqual([]);
        });
    });

    // -----------------------------------------------------------------
    describe('tool switching', () => {
        function toolManager() {
            const m = makeManager([]);
            m.currentTool = null;
            m.samTool = null;
            m.canvas = {
                isDrawingMode: false,
                freeDrawingBrush: {},
                defaultCursor: 'default',
            };
            m.maskCanvas = { style: {} };
            m._showMaskCanvas = () => {};
            m._hasMasks = () => false;
            m.polygonPoints = [];
            m.keypointPoints = [];
            m.cuboidFront = null;
            return m;
        }

        test('a switch reports the tool it moved to', () => {
            const m = toolManager();
            m.setTool('brush');
            expect(emitted).toEqual([{
                schema: 'objects', action: 'tool', meta: { tool: 'brush' },
            }]);
        });

        test('re-selecting the armed tool is not a switch', () => {
            const m = toolManager();
            m.setTool('brush');
            emitted.length = 0;
            m.setTool('brush');
            expect(emitted).toEqual([]);
        });

        test('clearing the tool reports select rather than null', () => {
            const m = toolManager();
            m.setTool('brush');
            emitted.length = 0;
            m.setTool(null);
            expect(emitted[0].meta).toEqual({ tool: 'select' });
        });
    });

    // -----------------------------------------------------------------
    describe('missing tracker', () => {
        test('every emitting path is a no-op when telemetry never loaded', () => {
            delete window.recordAnnotationTelemetry;
            const m = makeManager([]);
            m._saveState();
            m.state = [{ type: 'bbox', coordinates: {} }];
            expect(() => m._saveState()).not.toThrow();
        });
    });
});

/**
 * Mask state lifecycle — the operations that treat "the canvas" as "the state".
 *
 * Masks are not fabric objects. They live in `this.masks` and paint to their own
 * overlay canvas, so every method that clears or counts by walking
 * canvas.getObjects() silently misses them. Three shipped in that state:
 *
 *   clearAnnotations()   ran on every instance switch (annotation.js calls it
 *                        from clearAllFormInputs) and left the previous image's
 *                        brush strokes in place, which then re-serialized into
 *                        the next image's hidden input.
 *   _restoreState()      cleared fabric objects only, so undo could shrink a
 *                        stroke (its entry got overwritten) but never remove
 *                        one — a label absent from the target state was simply
 *                        never written back.
 *   getAnnotationCount() reported 0 for a mask-only image, so the count display
 *                        read "0 annotations" over visible paint and any
 *                        min_annotations rule rejected a fully segmented image.
 *
 * Also covers addAnnotation(), which visual_ai_assistant.js has always called
 * and which was never written, and the freeform path:created binding.
 */

// mask-buffer.js first: image-annotation.js resolves MaskBuffer at load,
// mirroring the script order the template guarantees in the browser.
require('../../potato/static/mask-buffer.js');
const ImageAnnotationManager = require('../../potato/static/image-annotation.js');

/** Build a MaskBuffer with the given flat pixel indices switched on. */
function maskBuffer(width, height, onIndices) {
    const buffer = new MaskBuffer(width, height);
    onIndices.forEach(i => buffer.set(i));
    return buffer;
}

/** A manager with just enough state to exercise the lifecycle methods. */
function makeManager(masks, objects) {
    const m = Object.create(ImageAnnotationManager.prototype);
    m.masks = masks || {};
    m.maskImgWidth = 4;
    m.maskImgHeight = 3;
    m.config = {};
    m.currentTool = 'brush';
    m.currentLabel = 'road';
    m.currentColor = '#ff0000';
    m.history = [];
    m.historyIndex = -1;
    m.maxHistory = 50;
    m.inputId = 'input-seg';

    const objs = objects ? objects.slice() : [];
    m.image = { width: 4, height: 3, scaleX: 1, scaleY: 1, left: 0, top: 0 };
    m.canvas = {
        getObjects: () => objs,
        remove: (o) => {
            const i = objs.indexOf(o);
            if (i >= 0) objs.splice(i, 1);
        },
        add: (o) => objs.push(o),
        renderAll: () => {},
    };

    // Rendering and the DOM are not what these tests are about.
    m._renderAllMasks = jest.fn();
    m._showMaskCanvas = jest.fn();
    m._updateMaskData = jest.fn();
    return m;
}

describe('clearAnnotations', () => {
    test('drops masks, so strokes do not leak into the next instance', () => {
        const m = makeManager({ road: { label: 'road', color: '#ff0000', buffer: maskBuffer(4, 3, [1, 2]) } });

        m.clearAnnotations();

        expect(Object.keys(m.masks)).toHaveLength(0);
        // The overlay must be repainted and hidden, or the cleared pixels stay
        // on screen over the next image.
        expect(m._renderAllMasks).toHaveBeenCalled();
        expect(m._showMaskCanvas).toHaveBeenCalledWith(false);
    });

    test('leaves nothing for the serializer to re-emit', () => {
        const m = makeManager({ road: { label: 'road', color: '#ff0000', buffer: maskBuffer(4, 3, [1, 2]) } });
        m.clearAnnotations();
        expect(JSON.parse(m._serializeAnnotations())).toEqual([]);
    });

    test('removes EVERY shape, not every other one', () => {
        // fabric's getObjects() returns its live internal array and remove()
        // splices it, so iterating the array directly skipped alternate
        // elements -- and this runs on every instance switch, so the survivors
        // were attributed to the next image.
        const m = makeManager({}, [
            { annotationData: { type: 'bbox', label: 'a' } },
            { annotationData: { type: 'bbox', label: 'b' } },
            { annotationData: { type: 'bbox', label: 'c' } },
        ]);

        m.clearAnnotations();

        expect(m.canvas.getObjects()).toHaveLength(0);
        expect(m.getAnnotationCount()).toBe(0);
    });
});

describe('_restoreState (undo/redo)', () => {
    test('removes a mask that is absent from the restored state', () => {
        const m = makeManager({ road: { label: 'road', color: '#ff0000', buffer: maskBuffer(4, 3, [1, 2]) } });
        m._hasMasks = () => Object.keys(m.masks).length > 0;

        // Undo back to a state that predates the stroke.
        m._restoreState(JSON.stringify([]));

        expect(Object.keys(m.masks)).toHaveLength(0);
    });

    test('restores a mask that IS present in the state', () => {
        const m = makeManager({});
        m._hasMasks = () => Object.keys(m.masks).length > 0;

        const state = JSON.stringify([{
            type: 'mask',
            label: 'road',
            color: '#ff0000',
            rle: { counts: [1, 2, 9], size: [3, 4] },
        }]);
        m._restoreState(state);

        expect(Object.keys(m.masks)).toEqual(['road']);
    });

    test('swapping between two mask states does not accumulate both', () => {
        const m = makeManager({});
        m._hasMasks = () => Object.keys(m.masks).length > 0;

        m._restoreState(JSON.stringify([
            { type: 'mask', label: 'road', color: '#ff0000', rle: { counts: [1, 2, 9], size: [3, 4] } },
        ]));
        m._restoreState(JSON.stringify([
            { type: 'mask', label: 'sky', color: '#00ff00', rle: { counts: [0, 3, 9], size: [3, 4] } },
        ]));

        // Without the reset, 'road' survived and every undo grew the set.
        expect(Object.keys(m.masks)).toEqual(['sky']);
    });
});

describe('getAnnotationCount', () => {
    test('counts masks as well as shapes', () => {
        const m = makeManager(
            { road: { label: 'road', color: '#ff0000', buffer: maskBuffer(4, 3, [1, 2]) } },
            [{ annotationData: { type: 'bbox', label: 'car', color: '#0000ff' } }],
        );
        expect(m.getAnnotationCount()).toBe(2);
    });

    test('a mask-only image does not report zero', () => {
        const m = makeManager({ road: { label: 'road', color: '#ff0000', buffer: maskBuffer(4, 3, [0]) } });
        expect(m.getAnnotationCount()).toBe(1);
    });

    test('an all-empty mask buffer is not counted', () => {
        // Matches the serializer, which emits no entry for an empty buffer.
        const m = makeManager({ road: { label: 'road', color: '#ff0000', buffer: maskBuffer(4, 3, []) } });
        expect(m.getAnnotationCount()).toBe(0);
    });
});

describe('addAnnotation', () => {
    test('accepts a contract-shaped bbox and stores it', () => {
        const m = makeManager({});
        m._saveState = jest.fn();
        m._updateAnnotationData = jest.fn();
        m._createAnnotationObject = jest.fn((ann) => {
            m.canvas.add({ annotationData: { type: ann.type, label: ann.label, color: ann.color } });
        });

        const ok = m.addAnnotation({
            type: 'bbox',
            label: 'car',
            color: '#0000ff',
            coordinates: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 },
        });

        expect(ok).toBe(true);
        expect(m._createAnnotationObject).toHaveBeenCalled();
        expect(m._updateAnnotationData).toHaveBeenCalled();
    });

    test('rejects the {bbox: ...} shape visual_ai_assistant used to send', () => {
        // The AI accept path passed `bbox`, not `coordinates`. _createAnnotationObject
        // reads ann.coordinates.x and would have thrown on undefined; rejecting here
        // keeps the failure loud and local instead of exporting a [0,0,0,0] box.
        const m = makeManager({});
        m._createAnnotationObject = jest.fn();

        const ok = m.addAnnotation({
            type: 'bbox',
            label: 'car',
            bbox: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 },
        });

        expect(ok).toBe(false);
        expect(m._createAnnotationObject).not.toHaveBeenCalled();
    });

    test('accepts a mask with rle and rejects one without', () => {
        const m = makeManager({});
        m._saveState = jest.fn();
        m._updateAnnotationData = jest.fn();

        expect(m.addAnnotation({
            type: 'mask',
            label: 'road',
            color: '#ff0000',
            rle: { counts: [1, 2, 9], size: [3, 4] },
        })).toBe(true);
        expect(Object.keys(m.masks)).toEqual(['road']);

        expect(m.addAnnotation({ type: 'mask', label: 'sky', color: '#00ff00' })).toBe(false);
    });

    test('refuses to add before an image is loaded', () => {
        const m = makeManager({});
        m.image = null;
        expect(m.addAnnotation({ type: 'bbox', label: 'car', coordinates: {} })).toBe(false);
    });
});

describe('keyboard shortcuts', () => {
    /**
     * The key handler reads config.toolKeys instead of a hardcoded switch, so a
     * profile change is a config change. Before this, the letters were baked
     * into image-annotation.js while the tooltips and docs claimed others --
     * brush/fill/eraser advertised "(M)/(G)/(E)" with no handler at all.
     */
    function armKeyboard(toolKeys, tools) {
        const m = makeManager();
        m.config = {
            schemaName: 'seg', tools, toolKeys,
            commonKeys: {select: 'v', brush_size_down: '[', brush_size_up: ']'},
            labels: [],
        };
        m.brushSize = 20;
        m._selectTool = jest.fn();
        m._isElementVisible = () => true;
        m.deleteSelected = jest.fn();
        m.zoom = jest.fn();
        m.zoomFit = jest.fn();
        m.setBrushSize = jest.fn((s) => { m.brushSize = s; });

        const container = document.createElement('div');
        container.className = 'image-annotation-container';
        container.setAttribute('data-schema', 'seg');
        document.body.appendChild(container);

        m._setupKeyboardShortcuts();
        return m;
    }

    afterEach(() => { document.body.innerHTML = ''; });

    function press(key) {
        document.dispatchEvent(new KeyboardEvent('keydown', {key, bubbles: true}));
    }

    test.each([
        ['INPUT', () => Object.assign(document.createElement('input'), {type: 'text'})],
        ['TEXTAREA', () => document.createElement('textarea')],
        ['SELECT', () => document.createElement('select')],
        ['contenteditable', () => {
            const el = document.createElement('div');
            Object.defineProperty(el, 'isContentEditable', {value: true});
            return el;
        }],
    ])('never steals keys from a %s', (_name, makeTarget) => {
        // This handler is on `document`. Without the guard, an annotator
        // writing a comment beside the image had their typing mangled: Space
        // and Backspace were swallowed by preventDefault, `h` hid a class,
        // and `r`/`b`/`p` silently switched tools.
        const m = armKeyboard({brush: 'b', bbox: 'r'}, ['brush', 'bbox']);
        const target = makeTarget();
        document.body.appendChild(target);

        target.dispatchEvent(new KeyboardEvent('keydown', {key: 'b', bubbles: true}));
        target.dispatchEvent(new KeyboardEvent('keydown', {key: 'r', bubbles: true}));

        expect(m._selectTool).not.toHaveBeenCalled();
    });

    test('Backspace in a text field does not delete the annotation', () => {
        const m = armKeyboard({bbox: 'r'}, ['bbox']);
        const input = document.createElement('textarea');
        document.body.appendChild(input);

        input.dispatchEvent(new KeyboardEvent('keydown', {key: 'Backspace', bubbles: true}));

        expect(m.deleteSelected).not.toHaveBeenCalled();
    });

    test('typing 0 or - in a text field does not zoom the canvas', () => {
        const m = armKeyboard({bbox: 'r'}, ['bbox']);
        const input = document.createElement('input');
        document.body.appendChild(input);

        input.dispatchEvent(new KeyboardEvent('keydown', {key: '0', bubbles: true}));
        input.dispatchEvent(new KeyboardEvent('keydown', {key: '-', bubbles: true}));

        expect(m.zoomFit).not.toHaveBeenCalled();
        expect(m.zoom).not.toHaveBeenCalled();
    });

    test('typing [ or ] in a text field does not resize the brush', () => {
        const m = armKeyboard({brush: 'b'}, ['brush']);
        const input = document.createElement('input');
        document.body.appendChild(input);

        input.dispatchEvent(new KeyboardEvent('keydown', {key: ']', bubbles: true}));

        expect(m.brushSize).toBe(20);
    });

    test('shortcuts still work when focus is not in a field', () => {
        // The guard must not disable the feature it protects.
        const m = armKeyboard({brush: 'b', bbox: 'r'}, ['brush', 'bbox']);
        document.body.dispatchEvent(new KeyboardEvent('keydown', {key: 'b', bubbles: true}));
        expect(m._selectTool).toHaveBeenCalledWith('brush');
    });

    test('v7 profile: b arms the brush, r arms the box', () => {
        const m = armKeyboard({brush: 'b', bbox: 'r'}, ['brush', 'bbox']);
        press('b');
        expect(m._selectTool).toHaveBeenCalledWith('brush');
        press('r');
        expect(m._selectTool).toHaveBeenCalledWith('bbox');
    });

    test('legacy profile: b arms the box instead', () => {
        const m = armKeyboard({bbox: 'b', brush: 'm'}, ['bbox', 'brush']);
        press('b');
        expect(m._selectTool).toHaveBeenCalledWith('bbox');
        press('m');
        expect(m._selectTool).toHaveBeenCalledWith('brush');
    });

    test('a key for a tool the schema does not enable does nothing', () => {
        const m = armKeyboard({brush: 'b', bbox: 'r'}, ['bbox']);
        press('b');
        expect(m._selectTool).not.toHaveBeenCalled();
    });

    test('v drops to select/move mode', () => {
        const m = armKeyboard({bbox: 'r'}, ['bbox']);
        press('v');
        // setTool(null) is already "no drawing tool armed".
        expect(m._selectTool).toHaveBeenCalledWith(null);
    });

    test('[ and ] resize the brush', () => {
        const m = armKeyboard({brush: 'b'}, ['brush']);
        press(']');
        expect(m.brushSize).toBeGreaterThan(20);
        const grown = m.brushSize;
        press('[');
        expect(m.brushSize).toBeLessThan(grown);
    });

    test('brush size stays within the slider range', () => {
        const m = armKeyboard({brush: 'b'}, ['brush']);
        for (let i = 0; i < 60; i++) press(']');
        expect(m.brushSize).toBeLessThanOrEqual(100);
        for (let i = 0; i < 80; i++) press('[');
        expect(m.brushSize).toBeGreaterThanOrEqual(1);
    });
});

describe('accessibility state', () => {
    /**
     * The tool and label buttons render with aria-pressed and their CLICK
     * handlers maintained it, but the keyboard/programmatic path did not -- so
     * a screen reader driven by the shortcut keys heard every tool report "not
     * pressed" regardless of which was armed (WCAG 4.1.2).
     */
    function withButtons(kind, values) {
        const m = makeManager();
        m.config = {schemaName: 'seg', tools: values, labels: []};
        m.setTool = jest.fn();

        const container = document.createElement('div');
        container.className = 'image-annotation-container';
        container.setAttribute('data-schema', 'seg');
        values.forEach(v => {
            const b = document.createElement('button');
            b.className = kind === 'tool' ? 'tool-btn' : 'label-btn';
            b.dataset[kind === 'tool' ? 'tool' : 'label'] = v;
            b.setAttribute('aria-pressed', 'false');
            container.appendChild(b);
        });
        document.body.appendChild(container);
        return {m, container};
    }

    afterEach(() => { document.body.innerHTML = ''; });

    test('_selectTool marks exactly one tool button pressed', () => {
        const {m, container} = withButtons('tool', ['bbox', 'brush']);
        m._selectTool('brush');

        const state = [...container.querySelectorAll('.tool-btn')].map(
            b => [b.dataset.tool, b.getAttribute('aria-pressed')]);
        expect(state).toEqual([['bbox', 'false'], ['brush', 'true']]);
    });

    test('switching tools clears the previous pressed state', () => {
        const {m, container} = withButtons('tool', ['bbox', 'brush']);
        m._selectTool('brush');
        m._selectTool('bbox');

        const pressed = [...container.querySelectorAll('.tool-btn')]
            .filter(b => b.getAttribute('aria-pressed') === 'true')
            .map(b => b.dataset.tool);
        expect(pressed).toEqual(['bbox']);
    });

    test('select/move mode leaves no tool pressed', () => {
        const {m, container} = withButtons('tool', ['bbox', 'brush']);
        m._selectTool('brush');
        m._selectTool(null);

        const pressed = [...container.querySelectorAll('.tool-btn')]
            .filter(b => b.getAttribute('aria-pressed') === 'true');
        expect(pressed).toHaveLength(0);
    });

    test('_updateLabelButtonState marks exactly one label pressed', () => {
        const {m, container} = withButtons('label', ['road', 'sky']);
        m._updateLabelButtonState('sky');

        const state = [...container.querySelectorAll('.label-btn')].map(
            b => [b.dataset.label, b.getAttribute('aria-pressed')]);
        expect(state).toEqual([['road', 'false'], ['sky', 'true']]);
    });
});

describe('keybinding notice', () => {
    afterEach(() => {
        document.body.innerHTML = '';
        localStorage.clear();
    });

    function noticeManager(profile, tools, toolKeys) {
        const m = makeManager();
        m.config = {schemaName: 'seg', keybindingProfile: profile, tools, toolKeys};
        const container = document.createElement('div');
        container.className = 'image-annotation-container';
        container.setAttribute('data-schema', 'seg');
        document.body.appendChild(container);
        return {m, container};
    }

    const V7 = {bbox: 'r', brush: 'b', fill: 'f', polygon: 'p'};

    test('names only the keys that actually moved', () => {
        const {m, container} = noticeManager('v7', ['bbox', 'polygon'], V7);
        m._maybeShowKeybindingNotice();

        const text = container.querySelector('.keybinding-notice').textContent;
        expect(text).toContain('bbox: B → R');
        // polygon is P in both profiles; listing it would be noise.
        expect(text).not.toContain('polygon');
    });

    test('is not shown on the legacy profile', () => {
        const {m, container} = noticeManager(
            'legacy', ['bbox'], {bbox: 'b', brush: 'm'});
        m._maybeShowKeybindingNotice();
        expect(container.querySelector('.keybinding-notice')).toBeNull();
    });

    test('dismissing it persists and it does not return', () => {
        const {m, container} = noticeManager('v7', ['bbox'], V7);
        m._maybeShowKeybindingNotice();
        container.querySelector('.keybinding-notice-dismiss').click();

        expect(container.querySelector('.keybinding-notice')).toBeNull();
        m._maybeShowKeybindingNotice();
        expect(container.querySelector('.keybinding-notice')).toBeNull();
    });

    test('builds DOM nodes rather than parsing markup', () => {
        const {m, container} = noticeManager('v7', ['bbox'], V7);
        m._maybeShowKeybindingNotice();
        const note = container.querySelector('.keybinding-notice');

        // Real elements, not a string that happened to parse.
        expect(note.querySelector('strong')).not.toBeNull();
        expect(note.querySelectorAll('code').length).toBeGreaterThan(0);
        expect(note.querySelector('button.keybinding-notice-dismiss')).not.toBeNull();
    });
});

describe('copyFromPrevious', () => {
    /**
     * Carry-over routes every copied object through addAnnotation(), so the
     * client contract is enforced on this path too -- a malformed object from
     * an older save is rejected here rather than silently exported as a
     * [0,0,0,0] box later.
     */
    function copyManager(response) {
        const m = makeManager();
        m.config = {schemaName: 'seg', tools: ['bbox'], labels: []};
        m._saveState = jest.fn();
        m._updateAnnotationData = jest.fn();
        m._announce = jest.fn();
        m._createAnnotationObject = jest.fn((ann) => {
            m.canvas.add({annotationData: {type: ann.type, label: ann.label}});
        });
        // setup.js already installs a global fetch mock and clears it between
        // tests; set its implementation rather than replacing the mock, or
        // resetMocks() loses its handle and every later suite breaks.
        global.fetch.mockImplementation(() => Promise.resolve({
            ok: response.ok !== false,
            status: response.status || 200,
            json: () => Promise.resolve(response.body || {}),
        }));
        return m;
    }

    const BBOX = {type: 'bbox', label: 'car', color: '#f00',
                  coordinates: {x: 0.1, y: 0.1, width: 0.2, height: 0.2}};
    const MASK = {type: 'mask', label: 'road', color: '#0f0',
                  rle: {counts: [1, 2, 9], size: [3, 4]}};

    afterEach(() => { global.fetch.mockReset(); });

    test('adds every object the server returns', async () => {
        const m = copyManager({body: {instance_id: 'img_1', objects: [BBOX, MASK]}});
        const result = await m.copyFromPrevious();

        expect(result.added).toBe(2);
        expect(result.sourceInstance).toBe('img_1');
        expect(Object.keys(m.masks)).toEqual(['road']);
    });

    test('requests the right schema', async () => {
        const m = copyManager({body: {objects: []}});
        await m.copyFromPrevious();
        expect(global.fetch.mock.calls[0][0]).toContain('schema=seg');
    });

    test('an empty previous image is not an error', async () => {
        const m = copyManager({body: {objects: [], reason: 'no_previous'}});
        const result = await m.copyFromPrevious();

        expect(result.added).toBe(0);
        expect(result.reason).toBe('no_previous');
    });

    test('rejects objects that violate the client contract', async () => {
        // The pre-0.1 shape: `bbox` where the contract wants `coordinates`.
        const m = copyManager({body: {objects: [
            BBOX, {type: 'bbox', label: 'x', bbox: {x: 0, y: 0, width: 1, height: 1}},
        ]}});
        const result = await m.copyFromPrevious();

        expect(result.added).toBe(1);
        expect(result.skipped).toBe(1);
    });

    test('appends by default and replaces only when asked', async () => {
        const m = copyManager({body: {objects: [BBOX]}});
        m.canvas.add({annotationData: {type: 'bbox', label: 'existing'}});

        await m.copyFromPrevious(false);
        expect(m.getAnnotationCount()).toBe(2);

        await m.copyFromPrevious(true);
        expect(m.getAnnotationCount()).toBe(1);
    });

    test('a network failure degrades quietly instead of throwing', async () => {
        const m = makeManager();
        m.config = {schemaName: 'seg', tools: [], labels: []};
        global.fetch.mockImplementation(() => Promise.reject(new Error('offline')));

        const result = await m.copyFromPrevious();
        expect(result).toEqual({added: 0, skipped: 0, reason: 'network_error'});
    });

    test('announces the result, since the canvas is silent to screen readers', async () => {
        const m = copyManager({body: {objects: [BBOX]}});
        await m.copyFromPrevious();
        expect(m._announce).toHaveBeenCalledWith(
            expect.stringContaining('Copied 1 annotation'));
    });
});

describe('_hexToRgb', () => {
    /**
     * Mask colour is read through this on every composite repaint. It used to
     * match ONLY six-digit hex and fall through to red for everything else, so
     * a label declared `color: "#0f0"` painted a red mask while its button and
     * its bounding boxes — styled by CSS, not by this — rendered green.
     */
    function rgb(value) {
        const m = Object.create(ImageAnnotationManager.prototype);
        return m._hexToRgb(value);
    }

    test.each([
        ['#ff0000', {r: 255, g: 0, b: 0}],
        ['#00ff00', {r: 0, g: 255, b: 0}],
        ['#0000ff', {r: 0, g: 0, b: 255}],
        ['ff0000', {r: 255, g: 0, b: 0}],       // no leading hash
        ['#FF8000', {r: 255, g: 128, b: 0}],    // uppercase
    ])('reads six-digit %s', (value, expected) => {
        expect(rgb(value)).toEqual(expected);
    });

    test.each([
        ['#f00', {r: 255, g: 0, b: 0}],
        ['#0f0', {r: 0, g: 255, b: 0}],
        ['#00f', {r: 0, g: 0, b: 255}],
        ['#abc', {r: 170, g: 187, b: 204}],
    ])('expands the shorthand %s', (value, expected) => {
        expect(rgb(value)).toEqual(expected);
    });

    test('drops the alpha byte of an eight-digit colour', () => {
        // Overlay opacity is a schema option; a per-colour alpha would fight it.
        expect(rgb('#0000ff80')).toEqual({r: 0, g: 0, b: 255});
    });

    test('an unreadable colour still paints red, but says so', () => {
        // The fallback is unchanged on purpose — altering it would silently
        // restyle existing projects — but it must not be silent.
        const warn = jest.spyOn(console, 'warn').mockImplementation(() => {});
        expect(rgb('rebeccapurple')).toEqual({r: 255, g: 0, b: 0});
        expect(rgb('rgb(0, 0, 255)')).toEqual({r: 255, g: 0, b: 0});
        expect(rgb(undefined)).toEqual({r: 255, g: 0, b: 0});
        expect(warn).toHaveBeenCalledWith(expect.stringContaining('cannot read the colour'));
        warn.mockRestore();
    });

    test('a repeated colour is parsed once', () => {
        // Called once per mask per composite repaint, which is once per
        // mousemove while painting.
        const m = Object.create(ImageAnnotationManager.prototype);
        expect(m._hexToRgb('#123456')).toBe(m._hexToRgb('#123456'));
    });
});

describe('applyLabelVisibility', () => {
    /**
     * The image half of per-class show/hide. Masks are not fabric objects, so
     * obj.visible cannot reach them -- they have to be skipped at render time
     * instead. That split is the recurring hazard in this file.
     */
    let realCreateElement;

    /** Every ImageData the renderer wrote into the mask composite. */
    let composited;

    beforeEach(() => {
        // jsdom has no 2D context, and the renderer composites all masks into
        // one offscreen canvas. We want the REAL renderer here so the mask-skip
        // logic is what is under test, so stub just enough of the context and
        // record what it was asked to paint.
        composited = [];
        realCreateElement = document.createElement.bind(document);
        jest.spyOn(document, 'createElement').mockImplementation((tag) => {
            const el = realCreateElement(tag);
            if (tag === 'canvas') {
                el.getContext = () => ({
                    createImageData: (w, h) => ({
                        data: new Uint8ClampedArray(w * h * 4), width: w, height: h,
                    }),
                    putImageData: (img, x, y) => composited.push({img, x, y}),
                    clearRect: jest.fn(),
                });
            }
            return el;
        });
    });

    /**
     * The distinct opaque colours the renderer actually painted, as hex.
     *
     * Counting drawImage calls is no longer a test of anything: every mask goes
     * into ONE composite, so exactly one draw happens whether a class is hidden
     * or not. The colours in that composite are what distinguishes them.
     */
    function paintedColors() {
        const seen = new Set();
        for (const {img} of composited) {
            for (let i = 0; i < img.data.length; i += 4) {
                if (img.data[i + 3] === 0) continue;
                seen.add('#' + [0, 1, 2]
                    .map(k => img.data[i + k].toString(16).padStart(2, '0')).join(''));
            }
        }
        return [...seen].sort();
    }

    afterEach(() => {
        document.createElement.mockRestore();
    });

    function visManager() {
        const m = makeManager(
            {road: {label: 'road', color: '#f00', buffer: maskBuffer(4, 3, [1, 2])},
             sky:  {label: 'sky',  color: '#00f', buffer: maskBuffer(4, 3, [5, 6])}},
            [{annotationData: {type: 'bbox', label: 'car'}, visible: true},
             {annotationData: {type: 'bbox', label: 'road'}, visible: true}],
        );
        m.canvas.getActiveObject = () => null;
        m.canvas.discardActiveObject = jest.fn();
        // The real _renderAllMasks reads the viewport to place the overlay.
        m.canvas.getZoom = () => 1;
        m.canvas.viewportTransform = [1, 0, 0, 1, 0, 0];
        // Exercise the real renderer's skip logic.
        delete m._renderAllMasks;
        m.maskCtx = {
            clearRect: jest.fn(), drawImage: jest.fn(), globalAlpha: 1,
        };
        m.maskCanvas = {width: 4, height: 3};
        m.maskOpacity = 0.5;
        return m;
    }

    test('hides fabric objects of the hidden label only', () => {
        const m = visManager();
        m.applyLabelVisibility(new Set(['road']));

        const byLabel = {};
        m.canvas.getObjects().forEach(o => { byLabel[o.annotationData.label] = o.visible; });
        expect(byLabel).toEqual({car: true, road: false});
    });

    test('a hidden object is also unselectable', () => {
        // Otherwise the annotator can drag or delete something invisible.
        const m = visManager();
        m.applyLabelVisibility(new Set(['road']));

        const hidden = m.canvas.getObjects().find(o => o.annotationData.label === 'road');
        expect(hidden.selectable).toBe(false);
        expect(hidden.evented).toBe(false);
    });

    test('hidden masks are skipped at render time', () => {
        const m = visManager();
        composited.length = 0;
        m.applyLabelVisibility(new Set(['road']));

        // road is #ff0000 and sky is #0000ff. Only sky may reach the canvas.
        expect(paintedColors()).toEqual(['#0000ff']);
        expect(m.maskCtx.drawImage).toHaveBeenCalled();
    });

    test('hiding every class paints nothing at all', () => {
        const m = visManager();
        composited.length = 0;
        m.applyLabelVisibility(new Set(['road', 'sky']));

        expect(paintedColors()).toEqual([]);
        expect(m.maskCtx.drawImage).not.toHaveBeenCalled();
    });

    test('showing everything again restores objects and masks', () => {
        const m = visManager();
        m.applyLabelVisibility(new Set(['road', 'sky']));
        composited.length = 0;

        m.applyLabelVisibility(new Set());

        expect(m.canvas.getObjects().every(o => o.visible)).toBe(true);
        // Both classes are back in the composite, not just the one that was
        // never hidden.
        expect(paintedColors()).toEqual(['#0000ff', '#ff0000']);
    });

    test('a repeat render with nothing changed repaints no tiles', () => {
        // The whole point of tracking dirty tiles: a render that follows no
        // edit must not rebuild the composite.
        const m = visManager();
        m._renderAllMasks();
        composited.length = 0;
        m._renderAllMasks();
        expect(composited).toHaveLength(0);
    });

    test('an edit repaints only the tile it touched', () => {
        const m = visManager();
        m._renderAllMasks();
        composited.length = 0;
        m.masks.road.buffer.setAt(3, 2);
        m._renderAllMasks();
        expect(composited).toHaveLength(1);
    });

    test('deleting a mask clears its pixels from the composite', () => {
        // A deleted mask has no tiles left to mark dirty, so nothing would
        // repaint over its pixels. The composite is keyed on which masks are
        // present so that a delete forces a full repaint instead.
        const m = visManager();
        m._renderAllMasks();
        delete m.masks.road;
        composited.length = 0;
        m._renderAllMasks();

        expect(paintedColors()).toEqual(['#0000ff']);
    });

    test('recolouring a mask repaints it in the new colour', () => {
        const m = visManager();
        m._renderAllMasks();
        m.masks.road.color = '#00ff00';
        composited.length = 0;
        m._renderAllMasks();

        expect(paintedColors()).toEqual(['#0000ff', '#00ff00']);
    });

    test('hiding never removes annotations from what gets saved', () => {
        // Presentation only: a hidden class must still export.
        const m = visManager();
        m._getObjectCoordinates = () => ({x: 0, y: 0, width: 1, height: 1});
        m.applyLabelVisibility(new Set(['road', 'sky']));

        const saved = JSON.parse(m._serializeAnnotations());
        expect(saved.map(a => a.label).sort()).toEqual(['car', 'road', 'road', 'sky']);
    });

    test('deselects the active object when its class is hidden', () => {
        const m = visManager();
        const active = m.canvas.getObjects()[1];
        m.canvas.getActiveObject = () => active;

        m.applyLabelVisibility(new Set(['road']));
        expect(m.canvas.discardActiveObject).toHaveBeenCalled();
    });

    test('an imported per-instance mask hides under its real label', () => {
        // Instance masks are keyed "label#instance", so keying visibility off
        // the store key would leave them stubbornly visible.
        const m = visManager();
        m.masks = {'road#0': {label: 'road', color: '#f00', buffer: maskBuffer(4, 3, [1])}};
        m.applyLabelVisibility(new Set(['road']));
        expect(m.maskCtx.drawImage).not.toHaveBeenCalled();
    });
});

describe('handleResize', () => {
    /**
     * The canvas took `container.clientWidth` once at construction and never
     * looked again: narrowing the window clipped it, widening left dead space,
     * and rotating a tablet did the same. Resizing must also not cost the
     * annotator any work, which is the real risk — everything on the canvas is
     * positioned in absolute canvas pixels and has to be re-laid-out.
     */
    function resizeManager(containerWidth) {
        const m = makeManager(
            {road: {label: 'road', color: '#f00', buffer: maskBuffer(4, 3, [1, 2])}},
            [],
        );
        let width = 400;
        m.canvas.getWidth = () => width;
        m.canvas.getHeight = () => 600;
        m.canvas.setWidth = (w) => { width = w; };
        m.canvas.getZoom = () => 1;
        m.canvas.viewportTransform = [1, 0, 0, 1, 0, 0];
        m.canvas.getActiveObject = () => null;
        m.canvas.discardActiveObject = jest.fn();
        m.image = {width: 200, height: 100, scaleX: 1, scaleY: 1, left: 0, top: 0,
                   set(props) { Object.assign(this, props); }};
        m._resizeMaskCanvas = jest.fn();
        m._updateAnnotationData = jest.fn();
        m._resizeContainer = {clientWidth: containerWidth};
        return m;
    }

    test('resizes the canvas to the container width', () => {
        const m = resizeManager(900);
        m.handleResize();
        expect(m.canvas.getWidth()).toBe(900);
    });

    test('refits the image to the new width', () => {
        const m = resizeManager(900);
        m.handleResize();
        // 200x100 image in a 900x600 canvas: capped at scale 1, centred.
        expect(m.image.scaleX).toBe(1);
        expect(m.image.left).toBe((900 - 200) / 2);
    });

    test('scales the image down when the container shrinks', () => {
        const m = resizeManager(100);
        m.handleResize();
        expect(m.image.scaleX).toBeCloseTo(0.5);  // 100 / 200
    });

    test('annotations survive the resize', () => {
        const m = resizeManager(900);
        m.canvas.add({annotationData: {type: 'bbox', label: 'car', color: '#00f'}});
        m._getObjectCoordinates = () => ({x: 0.1, y: 0.1, width: 0.2, height: 0.2});
        m._createAnnotationObject = (ann) => {
            m.canvas.add({annotationData: {type: ann.type, label: ann.label, color: ann.color}});
        };

        m.handleResize();

        const labels = m.canvas.getObjects()
            .filter(o => o.annotationData).map(o => o.annotationData.label);
        expect(labels).toEqual(['car']);
    });

    test('masks survive the resize', () => {
        const m = resizeManager(900);
        m.handleResize();
        expect(Object.keys(m.masks)).toEqual(['road']);
    });

    test('rewrites the hidden input after rebuilding', () => {
        // Removing the old objects fires `object:removed`, whose handler writes
        // the momentarily-empty canvas to the input. Nothing in the restore
        // path writes it back, so without an explicit rewrite the annotations
        // stay on screen while the field the save path reads says "[]" — a
        // resize would silently discard the annotator's work on the next save.
        const m = resizeManager(900);
        m.handleResize();
        expect(m._updateAnnotationData).toHaveBeenCalled();
    });

    test('a no-op resize does no work', () => {
        // ResizeObserver fires for changes that do not affect our width.
        const m = resizeManager(400);  // same as the current canvas width
        const spy = jest.spyOn(m, '_serializeAnnotations');
        m.handleResize();
        expect(spy).not.toHaveBeenCalled();
    });

    test('a zero-width container is ignored', () => {
        // A hidden container reports 0; resizing to it would destroy the layout.
        const m = resizeManager(0);
        m.handleResize();
        expect(m.canvas.getWidth()).toBe(400);
    });

    test('hidden classes stay hidden after a resize', () => {
        const m = resizeManager(900);
        m.labelVisibility = {hiddenLabels: () => new Set(['road'])};
        m.applyLabelVisibility = jest.fn();

        m.handleResize();

        expect(m.applyLabelVisibility).toHaveBeenCalledWith(new Set(['road']));
    });

    test('the armed tool is preserved', () => {
        const m = resizeManager(900);
        m.currentTool = 'polygon';
        m.handleResize();
        expect(m.currentTool).toBe('polygon');
    });

    test('destroy() disconnects the observer', () => {
        // The observer holds the container; leaking one per instance switch
        // would accumulate across a long annotation session.
        const m = resizeManager(900);
        const disconnect = jest.fn();
        m._resizeObserver = {disconnect};
        m.destroy();
        expect(disconnect).toHaveBeenCalled();
        expect(m._resizeObserver).toBeNull();
    });
});

describe('_handleFreeformPath', () => {
    test('claims the path from the event so the serializer can see it', () => {
        const m = makeManager({});
        m._saveState = jest.fn();
        m._updateAnnotationData = jest.fn();
        m._colorWithAlpha = () => 'rgba(255,0,0,0.1)';

        const path = { type: 'path', set: jest.fn() };
        m._handleFreeformPath({ path });

        // _serializeAnnotations filters on annotationData; without it the stroke
        // was drawn and then dropped on save.
        expect(path.annotationData).toEqual({
            type: 'freeform', label: 'road', color: '#ff0000',
        });
        expect(m._updateAnnotationData).toHaveBeenCalled();
    });

    test('discards a stroke drawn with no label selected', () => {
        const m = makeManager({});
        m.currentLabel = null;
        const path = { type: 'path', set: jest.fn() };
        m.canvas.add(path);

        m._handleFreeformPath({ path });

        expect(path.annotationData).toBeUndefined();
        expect(m.canvas.getObjects()).not.toContain(path);
    });
});

describe('viewport transform', () => {
    /**
     * Masks paint to their own overlay canvas, positioned from the fabric
     * viewport transform, while drawing converts pointer coordinates back the
     * other way. If those two calculations ever disagree, painted pixels land
     * somewhere other than where the annotator clicked — and the error is
     * invisible until someone looks at a zoomed screenshot.
     *
     * Verified empirically in a real browser at zoom 0.25-8 with several pans:
     * the round trip is exact. This pins that, since the two directions live in
     * different methods and could drift apart in a refactor.
     */
    function viewportManager(zoom, panX, panY) {
        const m = makeManager();
        m.image = {width: 400, height: 300, scaleX: 0.5, scaleY: 0.5, left: 30, top: 20};
        m.canvas.getZoom = () => zoom;
        m.canvas.viewportTransform = [zoom, 0, 0, zoom, panX, panY];
        return m;
    }

    const CASES = [
        [1, 0, 0], [0.25, 0, 0], [4, 0, 0],
        [1, 120, -60], [2, -300, 200], [8, 45, 45],
    ];

    test.each(CASES)('screen->image->screen is the identity at zoom %s pan %s,%s',
        (zoom, panX, panY) => {
            const m = viewportManager(zoom, panX, panY);

            for (let sx = 40; sx < 300; sx += 61) {
                for (let sy = 30; sy < 240; sy += 53) {
                    const img = m._screenToImageCoords(sx, sy);
                    if (!img) continue;  // outside the image is a valid answer

                    // The forward transform _renderAllMasks uses to place the
                    // overlay, written out explicitly.
                    const backX = (img.x * m.image.scaleX + m.image.left) * zoom + panX;
                    const backY = (img.y * m.image.scaleY + m.image.top) * zoom + panY;

                    // Tolerance covers only the floor() quantization in
                    // _screenToImageCoords, scaled by the current zoom.
                    const tolerance = Math.max(1, m.image.scaleX * zoom) + 0.001;
                    expect(Math.abs(backX - sx)).toBeLessThanOrEqual(tolerance);
                    expect(Math.abs(backY - sy)).toBeLessThanOrEqual(tolerance);
                }
            }
        });

    test('points outside the image return null rather than bogus coordinates', () => {
        const m = viewportManager(1, 0, 0);
        // Far left of the image, which starts at x=30.
        expect(m._screenToImageCoords(-500, -500)).toBeNull();
    });
});

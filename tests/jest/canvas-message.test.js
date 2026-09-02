/**
 * Canvas messages: wrapping, resize, and the DOM twin.
 *
 * `_showCanvasMessage` is the only thing an annotator sees when an image will
 * not load, and it had three problems at once:
 *
 *   1. fabric.Text does not wrap, so any message longer than the canvas ran off
 *      the right edge — losing exactly the half that says what to do.
 *   2. The canvas is constructed at the element's backing-store width and
 *      narrowed by the ResizeObserver a moment later, so a message laid out at
 *      construction was laid out for a canvas twice its final size.
 *   3. Painted text is pixels. A screen-reader user got an empty drawing
 *      surface and no explanation for the one thing that most needed one.
 */

require('../../potato/static/mask-buffer.js');
const ImageAnnotationManager = require('../../potato/static/image-annotation.js');

/** A fabric.Canvas stand-in that records what was added and at what size. */
function fakeCanvas(width, height) {
    const objects = [];
    return {
        objects,
        _width: width,
        _height: height,
        getWidth() { return this._width; },
        getHeight() { return this._height; },
        setWidth(w) { this._width = w; },
        clear() { objects.length = 0; },
        setBackgroundColor(color, cb) { if (cb) cb(); },
        add(obj) { objects.push(obj); },
        renderAll() {},
        getObjects() { return objects.slice(); },
    };
}

function makeManager(canvasId, canvas) {
    const m = Object.create(ImageAnnotationManager.prototype);
    m.canvasId = canvasId;
    m.canvas = canvas;
    return m;
}

const LONG = 'No image URL for this item. Check that the item data has an '
    + 'image URL under text_key or source_field.';

beforeEach(() => {
    document.body.innerHTML = `
        <div class="image-annotation-container" data-schema="od">
            <canvas id="canvas-od"></canvas>
        </div>`;
    global.fabric = {
        Textbox: function (text, opts) { Object.assign(this, opts, {text, type: 'textbox'}); },
        Text: function (text, opts) { Object.assign(this, opts, {text, type: 'text'}); },
    };
});

describe('_showCanvasMessage', () => {
    test('uses a Textbox so the message wraps', () => {
        const canvas = fakeCanvas(398, 600);
        makeManager('canvas-od', canvas)._showCanvasMessage(LONG);

        expect(canvas.objects).toHaveLength(1);
        expect(canvas.objects[0].type).toBe('textbox');
    });

    test('the textbox fits inside the canvas', () => {
        const canvas = fakeCanvas(398, 600);
        makeManager('canvas-od', canvas)._showCanvasMessage(LONG);

        expect(canvas.objects[0].width).toBeLessThanOrEqual(398);
    });

    test('a very narrow canvas still gets a usable width', () => {
        // Below the 48px gutter the arithmetic would go negative.
        const canvas = fakeCanvas(60, 200);
        makeManager('canvas-od', canvas)._showCanvasMessage(LONG);

        expect(canvas.objects[0].width).toBeGreaterThan(0);
    });

    test('the message is remembered for the next resize', () => {
        const canvas = fakeCanvas(398, 600);
        const manager = makeManager('canvas-od', canvas);
        manager._showCanvasMessage(LONG);

        expect(manager._canvasMessage).toBe(LONG);
    });
});

describe('the DOM twin', () => {
    test('a role=alert element carries the same text', () => {
        makeManager('canvas-od', fakeCanvas(398, 600))._showCanvasMessage(LONG);

        const region = document.querySelector('.image-annotation-message');
        expect(region).not.toBeNull();
        expect(region.getAttribute('role')).toBe('alert');
        expect(region.textContent).toBe(LONG);
    });

    test('it is screen-reader only, so the message does not read twice', () => {
        makeManager('canvas-od', fakeCanvas(398, 600))._showCanvasMessage(LONG);

        expect(document.querySelector('.image-annotation-message').className)
            .toContain('sr-only');
    });

    test('a second message replaces the first rather than stacking', () => {
        const manager = makeManager('canvas-od', fakeCanvas(398, 600));
        manager._showCanvasMessage('First problem.');
        manager._showCanvasMessage('Second problem.');

        const regions = document.querySelectorAll('.image-annotation-message');
        expect(regions).toHaveLength(1);
        expect(regions[0].textContent).toBe('Second problem.');
    });

    test('_clearCanvasMessage removes it', () => {
        const manager = makeManager('canvas-od', fakeCanvas(398, 600));
        manager._showCanvasMessage(LONG);
        manager._clearCanvasMessage();

        expect(document.querySelector('.image-annotation-message')).toBeNull();
        expect(manager._canvasMessage).toBeNull();
    });
});

describe('handleResize with a message on screen', () => {
    test('re-wraps the message for the new width', () => {
        const canvas = fakeCanvas(796, 600);
        const manager = makeManager('canvas-od', canvas);
        manager._showCanvasMessage(LONG);
        const wideWidth = canvas.objects[0].width;

        manager._resizeContainer = {clientWidth: 398};
        manager.handleResize();

        expect(canvas.getWidth()).toBe(398);
        expect(canvas.objects).toHaveLength(1);
        expect(canvas.objects[0].width).toBeLessThan(wideWidth);
        expect(canvas.objects[0].width).toBeLessThanOrEqual(398);
    });

    test('does not run the image relayout path, which has no image to relayout', () => {
        const canvas = fakeCanvas(796, 600);
        const manager = makeManager('canvas-od', canvas);
        manager._showCanvasMessage(LONG);

        manager._resizeContainer = {clientWidth: 398};
        manager._serializeAnnotations = () => { throw new Error('should not be called'); };

        expect(() => manager.handleResize()).not.toThrow();
    });
});

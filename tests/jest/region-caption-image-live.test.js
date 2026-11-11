/**
 * region_caption over a real image canvas: showing an answer is not saving it.
 *
 * Two paths announced a restore as an edit:
 *
 *   ImageAnnotationManager.deserialize()  dropped `_hydrating` before writing
 *                        the hidden input, so a teammate's live answer
 *                        (applyRemoteAnswer) fired an unsuppressed `change`,
 *                        and region_caption, listening to the canvas, saved
 *                        it as this member's own captions.
 *   RegionCaptionManager init            synced on finding the canvas without
 *                        `quiet`, writing `{"captions":[]}` over an unanswered
 *                        item and firing `change` on every page load.
 *
 * The image manager is the real class with its drawing layer stubbed: shapes
 * are plain objects on a fake fabric canvas, which is all the restore and
 * listener paths touch.
 */

global.fabric = { Point: function () {}, Rect: function () {}, util: { transformPoint: (p) => p } };
require('../../potato/static/mask-buffer.js');
const ImageAnnotationManager = require('../../potato/static/image-annotation.js');
require('../../potato/static/region-caption.js');

const BOX = (x) => ({ type: 'bbox', label: 'thing', coordinates: { x, y: 0.1, width: 0.2, height: 0.2 } });

function imageManager(shapes) {
    const m = Object.create(ImageAnnotationManager.prototype);
    m.masks = {};
    m.config = { schemaName: 'img' };
    m.history = [];
    m.historyIndex = -1;
    m.maxHistory = 50;
    m.inputId = 'input-img';
    m._annotationChangeListeners = [];
    m._hydrating = false;
    const objects = [];
    m.image = { width: 4, height: 3, scaleX: 1, scaleY: 1, left: 0, top: 0 };
    m.canvas = {
        getObjects: () => objects,
        remove: (o) => { const i = objects.indexOf(o); if (i >= 0) objects.splice(i, 1); },
        add: (o) => objects.push(o),
        renderAll: () => {},
        getActiveObject: () => null,
        getElement: () => ({ closest: () => null }),
    };
    m._renderAllMasks = jest.fn();
    m._showMaskCanvas = jest.fn();
    m._syncMaskCanvasForTool = jest.fn();
    m._createAnnotationObject = (ann) => objects.push({ annotationData: ann });
    m._serializeAnnotations = () => JSON.stringify(objects.map((o) => o.annotationData));
    (shapes || []).forEach((s) => m._createAnnotationObject(s));
    return m;
}

function page(captionAnswer, shapes) {
    document.body.innerHTML = `
        <div class="image-annotation-container" data-schema="img"></div>
        <input type="hidden" id="input-img" value="">
        <div class="region-caption-container" data-schema="rc">
          <ol id="region-caption-list-rc"></ol>
          <p id="region-caption-progress-rc"></p>
          <span id="region-caption-announce-rc"></span>
          <input type="hidden" id="input-rc" value="">
        </div>`;
    const imageInput = document.getElementById('input-img');
    const captionInput = document.getElementById('input-rc');
    if (captionAnswer) captionInput.value = JSON.stringify(captionAnswer);
    const image = imageManager(shapes);
    imageInput.value = image._serializeAnnotations();
    document.querySelector('.image-annotation-container').annotationManager = image;
    const box = document.querySelector('.region-caption-container');
    const captions = new RegionCaptionManager(box, { schemaName: 'rc' });
    const changes = { image: 0, caption: 0 };
    imageInput.addEventListener('change', () => { changes.image += 1; });
    captionInput.addEventListener('change', () => { changes.caption += 1; });
    captions.init();
    return { image, captions, imageInput, captionInput, changes };
}

describe("a teammate's regions arriving on the canvas", () => {
    test('save neither the image answer nor the captions', () => {
        const R1 = BOX(0.1);
        const p = page({ captions: [{ region: R1, caption: 'mine' }] }, [R1]);
        p.changes.image = 0;
        p.changes.caption = 0;

        p.image.applyRemoteAnswer(JSON.stringify([R1, BOX(0.6)]));

        expect(p.changes.image).toBe(0);
        expect(p.changes.caption).toBe(0);
        expect(p.captionInput.hasAttribute('data-modified')).toBe(false);
        // The list still follows the canvas.
        expect(p.captions.entries.map((e) => e.caption)).toEqual(['mine', '']);
        expect(JSON.parse(p.imageInput.value)).toHaveLength(2);
    });

    test('a cleared canvas saves nothing either', () => {
        const R1 = BOX(0.1);
        const p = page({ captions: [{ region: R1, caption: 'mine' }] }, [R1]);
        p.changes.caption = 0;

        p.image.applyRemoteAnswer(null);

        expect(p.changes.image).toBe(0);
        expect(p.changes.caption).toBe(0);
        expect(p.captions.entries).toEqual([]);
    });

    test('a shape this member draws still saves', () => {
        const p = page(null, []);
        p.image.canvas.add({ annotationData: BOX(0.3) });
        p.image._updateAnnotationData();
        expect(p.changes.image).toBe(1);
        expect(p.changes.caption).toBe(1);
        expect(p.captionInput.getAttribute('data-modified')).toBe('true');
    });
});

describe('loading the page', () => {
    test('an unanswered item with no regions writes and announces nothing', () => {
        const p = page(null, []);
        expect(p.changes.caption).toBe(0);
        expect(p.captionInput.value).toBe('');
        expect(p.captionInput.hasAttribute('data-modified')).toBe(false);
    });

    test('a stored answer that matches the canvas is shown, not saved again', () => {
        const R1 = BOX(0.1);
        const p = page({ captions: [{ region: R1, caption: 'mine' }] }, [R1]);
        expect(p.changes.caption).toBe(0);
        expect(p.captionInput.hasAttribute('data-modified')).toBe(false);
        expect(document.querySelector('#region-caption-list-rc textarea').value).toBe('mine');
    });

    test('regions the stored answer lacks (a prelabel) are saved', () => {
        const p = page(null, [BOX(0.1)]);
        expect(p.changes.caption).toBe(1);
        expect(p.captionInput.getAttribute('data-modified')).toBe('true');
        expect(JSON.parse(p.captionInput.value).captions).toHaveLength(1);
    });
});

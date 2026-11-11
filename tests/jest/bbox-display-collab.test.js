/**
 * Live collaborative sessions: the PDF and document bounding-box displays.
 *
 * These are displays, not schemes. Their boxes ride in a hidden
 * `input.annotation-data-input[name=<field key>]`, saved as
 * `<field key>:::_data` (server key `L:<field key>:::_data`), and there is no
 * form with data-schema-name / data-annotation-type for collab.js to find.
 * Each display registers collab.js's per-scheme hook,
 * `potatoCollabAppliers[<field key>]`, which collab.js consults before it
 * looks for a form, and the modules gain a replace-style `reload`.
 *
 * The bbox canvas is mocked: it records the label text of each box drawn
 * since its last clear, which is what the annotator sees.
 */

const fs = require('fs');
const path = require('path');

global.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
HTMLCanvasElement.prototype.getContext = function () {
    if (this._ctx) return this._ctx;
    const drawn = [];
    this._drawn = drawn;
    this._ctx = {
        clearRect() { drawn.length = 0; },
        fillText(text) { drawn.push(text); },
        measureText: (t) => ({ width: String(t).length * 6 }),
        strokeRect() {}, fillRect() {}, setLineDash() {}, beginPath() {}, stroke() {},
    };
    return this._ctx;
};

/** pdf_display.py _render_pdfjs_bbox, field key "pdf" (controls trimmed). */
const PDF_MARKUP = `
  <div class="pdf-display pdf-viewer-paginated pdf-bbox-mode" data-field-key="pdf" data-pdf-source="docs/a.pdf" data-view-mode="paginated" data-annotation-mode="bounding_box" data-initial-page="1" data-zoom="page-fit" data-bbox-min-size="10" data-show-bbox-labels="true" style="max-height: 700px">
    <div class="pdf-controls pdf-bbox-controls">
      <div class="pdf-navigation">
        <button type="button" class="pdf-first-btn">&#x23EA;</button>
        <button type="button" class="pdf-prev-btn">&#x25C0;</button>
        <span class="pdf-page-info">Page <input type="number" class="pdf-page-input" min="1" value="1" /> of <span class="pdf-total-pages">-</span></span>
        <button type="button" class="pdf-next-btn">&#x25B6;</button>
        <button type="button" class="pdf-last-btn">&#x23E9;</button>
      </div>
      <div class="pdf-bbox-tools">
        <button type="button" class="pdf-bbox-draw-btn active">Draw</button>
        <button type="button" class="pdf-bbox-select-btn">Select</button>
        <button type="button" class="pdf-bbox-delete-btn">Delete</button>
      </div>
    </div>
    <div class="pdf-canvas-container pdf-bbox-container">
      <canvas class="pdf-canvas"></canvas>
      <canvas class="pdf-bbox-canvas" title="Draw bounding boxes here"></canvas>
      <div class="pdf-bbox-list" style="display: none;"></div>
    </div>
    <div class="pdf-bbox-info">
      <div class="pdf-bbox-count">Boxes on page: <span class="count">0</span></div>
      <div class="pdf-bbox-total">Total boxes: <span class="count">0</span></div>
    </div>
    <div class="pdf-error" style="display: none;"></div>
    <input type="hidden" class="annotation-data-input" name="pdf" id="input-pdf" value="VALUE">
  </div>`;

/** document_display.py _render_bbox_mode, field key "document". */
const DOC_MARKUP = `
  <div class="document-display document-theme-default document-bbox-mode" data-field-key="document" data-annotation-mode="bounding_box" data-bbox-min-size="10" data-show-bbox-labels="true" style="position: relative">
    <div class="document-bbox-toolbar">
      <div class="document-bbox-tools">
        <button type="button" class="document-bbox-draw-btn active">Draw</button>
        <button type="button" class="document-bbox-select-btn">Select</button>
        <button type="button" class="document-bbox-delete-btn">Delete</button>
      </div>
      <div class="document-bbox-info"><span class="document-bbox-count">Boxes: <span class="count">0</span></span></div>
    </div>
    <div class="document-bbox-container">
      <div class="document-content document-bbox-content"><p>Hello</p></div>
      <canvas class="document-bbox-canvas"></canvas>
      <input type="hidden" class="annotation-data-input" name="document" id="input-document" value="VALUE">
    </div>
  </div>`;

const esc = (v) => (v ? JSON.stringify(v).replace(/"/g, '&quot;') : '');

function box(id, label, page, x) {
    return { id, page, label, bbox: [x || 0.1, 0.1, 0.2, 0.2], bbox_pixels: [10, 10, 20, 20] };
}

const KINDS = {
    pdf: {
        key: 'pdf', file: 'pdf-bbox.js', api: 'PDFBoundingBox', markup: PDF_MARKUP,
        canvas: '.pdf-bbox-canvas',
        counts: () => [document.querySelector('.pdf-bbox-count .count').textContent,
                       document.querySelector('.pdf-bbox-total .count').textContent],
        countsFor: (onPage, total) => [String(onPage), String(total)],
    },
    document: {
        key: 'document', file: 'document-bbox.js', api: 'DocumentBoundingBox', markup: DOC_MARKUP,
        canvas: '.document-bbox-canvas',
        counts: () => [document.querySelector('.document-bbox-count .count').textContent],
        countsFor: (onPage, total) => [String(total)],
    },
};

function makePage(kind, stored) {
    document.body.innerHTML = kind.markup.replace('VALUE', esc(stored));
    delete window[kind.api];
    delete window.potatoCollabAppliers;
    jest.isolateModules(() => { require(`../../potato/static/${kind.file}`); });
    window.fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }));
    window.saveAnnotations = jest.fn();
    return document.getElementById(`input-${kind.key}`);
}

/** What collab.js does for a scheme with a per-scheme applier. */
function applyTeammate(kind, value) {
    const input = document.getElementById(`input-${kind.key}`);
    const json = value === null ? '' : JSON.stringify(value);
    input.value = json;
    input.setAttribute('value', json);
    const applier = (window.potatoCollabAppliers || {})[kind.key];
    if (typeof applier !== 'function') return false;
    return applier(kind.key, json || null, input) === true;
}

const labelsDrawn = (kind) => document.querySelector(kind.canvas)._drawn.slice();

Object.values(KINDS).forEach((kind) => {
    describe(`${kind.api} live applier`, () => {
        test('a teammate answer replaces the boxes drawn and counted', () => {
            makePage(kind, [box('b1', 'title', 1)]);
            expect(labelsDrawn(kind)).toEqual(['title']);
            expect(applyTeammate(kind, [box('b2', 'figure', 1), box('b3', 'table', 1, 0.5)])).toBe(true);
            expect(labelsDrawn(kind)).toEqual(['figure', 'table']);
            expect(kind.counts()).toEqual(kind.countsFor(2, 2));
            expect(window[kind.api].getAllBoxes(document.querySelector(`[data-field-key="${kind.key}"]`))
                .map((b) => b.id)).toEqual(['b2', 'b3']);
        });

        test('null clears every box', () => {
            makePage(kind, [box('b1', 'title', 1), box('b2', 'figure', 1)]);
            expect(applyTeammate(kind, null)).toBe(true);
            expect(labelsDrawn(kind)).toEqual([]);
            expect(kind.counts()).toEqual(kind.countsFor(0, 0));
        });

        test('applying saves nothing', () => {
            const input = makePage(kind, [box('b1', 'title', 1)]);
            const changed = jest.fn();
            input.addEventListener('change', changed);
            expect(applyTeammate(kind, [box('b2', 'figure', 1)])).toBe(true);
            expect(window.fetch).not.toHaveBeenCalled();
            expect(window.saveAnnotations).not.toHaveBeenCalled();
            expect(changed).not.toHaveBeenCalled();
            expect(input.hasAttribute('data-modified')).toBe(false);
        });

        test('applying twice does not duplicate', () => {
            makePage(kind, null);
            const answer = [box('b1', 'title', 1)];
            applyTeammate(kind, answer);
            applyTeammate(kind, answer);
            expect(labelsDrawn(kind)).toEqual(['title']);
            expect(kind.counts()).toEqual(kind.countsFor(1, 1));
        });

        test('reload is public, by field key or element', () => {
            makePage(kind, [box('b1', 'title', 1)]);
            const input = document.getElementById(`input-${kind.key}`);
            input.value = '';
            expect(window[kind.api].reload(kind.key)).toBe(true);
            expect(labelsDrawn(kind)).toEqual([]);
        });
    });
});

describe('PDF boxes on other pages', () => {
    test('a box on page 2 counts in the total and is not drawn on page 1', () => {
        makePage(KINDS.pdf, null);
        applyTeammate(KINDS.pdf, [box('b1', 'title', 1), box('b2', 'figure', 2)]);
        expect(labelsDrawn(KINDS.pdf)).toEqual(['title']);
        expect(KINDS.pdf.counts()).toEqual(['1', '2']);
    });
});

describe('collab.js reaches the displays', () => {
    const SOURCE = path.join(__dirname, '..', '..', 'potato', 'static', 'collab.js');

    function bootCollab() {
        window.potatoCollab = { sid: 'RED', me: 'ben', instance_id: 'c1', rev: 4, cursor: 10,
                                team_user: 'team-red', transport: 'poll', poll_interval_ms: 100000, base: '' };
        delete window.potatoSaveHooks;
        delete window.potatoNavigation;
        delete window.potatoCollabClient;
        // eslint-disable-next-line no-new-func
        new Function(fs.readFileSync(SOURCE, 'utf8'))();
        return window.potatoCollabClient;
    }

    beforeEach(() => { jest.useFakeTimers(); });
    afterEach(() => {
        jest.useRealTimers();
        window.fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }));
    });

    Object.values(KINDS).forEach((kind) => {
        test(`${kind.api}: a teammate's L:${kind.key}:::_data is shown live`, () => {
            makePage(kind, [box('b1', 'title', 1)]);
            const client = bootCollab();
            const key = `L:${kind.key}:::_data`;
            const shown = client.applyKeys(new Set([key]),
                                           { [key]: JSON.stringify([box('b9', 'caption', 1)]) });
            expect(shown.has(key)).toBe(true);
            expect(labelsDrawn(kind)).toEqual(['caption']);
            expect(document.getElementById(`input-${kind.key}`).getAttribute('data-server-set')).toBe('true');
        });
    });
});

/**
 * Event triggers and arguments printed as "?" because the text was read from
 * the wrong element.
 *
 * `getSpanText()` sliced `document.getElementById('text-content').dataset
 * .originalText` by the span's offsets. Under `instance_display` that legacy
 * node still exists but holds the item's `text_key` -- usually a title or an id
 * -- while the spans were drawn on `#text-content-<field>`. Slicing a short
 * string at offsets 14-22 returns "", so every trigger and argument rendered as
 * "?" from the moment it was created, and `trigger_text` was stored empty.
 *
 * The audit reported this as a timing problem: the list rendering before the
 * overlays were restored. That is a second, real cause -- fixed by storing each
 * argument's text at creation, and by redrawing the list when the spans arrive.
 * These cover the text source.
 */

const fs = require('fs');
const path = require('path');

const SOURCE = path.join(__dirname, '..', '..', 'potato', 'static', 'event-annotation.js');

/** The two methods under test, lifted off the class. */
function loadMethods() {
    const src = fs.readFileSync(SOURCE, 'utf8');
    function extract(name) {
        const start = src.indexOf(`\n    ${name}(`);
        if (start === -1) throw new Error(`${name}() not found`);
        const open = src.indexOf('{', start);
        let depth = 0;
        for (let j = open; j < src.length; j++) {
            if (src[j] === '{') depth++;
            else if (src[j] === '}') {
                depth--;
                if (depth === 0) return src.slice(start, j + 1);
            }
        }
        throw new Error(`unbalanced braces in ${name}()`);
    }
    return new Function(`return {${extract('getSpanText')},${extract('resolveOriginalText')}};`)();
}

const PASSAGE = 'The trial assigned renal denervation or a sham procedure to 535 patients.';

let mgr;
beforeAll(() => { mgr = loadMethods(); });

function overlay({start, end, inField}) {
    const el = document.createElement('span');
    el.dataset.start = String(start);
    el.dataset.end = String(end);
    if (inField) document.getElementById('span-overlays-passage').appendChild(el);
    else document.body.appendChild(el);
    return el;
}

describe('under instance_display', () => {
    beforeEach(() => {
        document.body.innerHTML = `
          <div class="display-field" data-span-target="true">
            <div class="display-field-content">
              <div class="text-content" id="text-content-passage"
                   data-original-text="${PASSAGE}">${PASSAGE}</div>
              <div id="span-overlays-passage"></div>
            </div>
          </div>
          <div id="instance-text" style="display: none;">
            <div id="text-content" data-original-text="trial">trial</div>
          </div>`;
    });

    test('the text comes from the field the spans were drawn on', () => {
        expect(mgr.resolveOriginalText(overlay({start: 19, end: 36, inField: true})))
            .toBe(PASSAGE);
    });

    test('an argument gets its real text, not ""', () => {
        expect(mgr.getSpanText(overlay({start: 19, end: 36, inField: true})))
            .toBe('renal denervation');
    });

    test('a trigger gets its real text', () => {
        expect(mgr.getSpanText(overlay({start: 10, end: 18, inField: true})))
            .toBe('assigned');
    });

    test('an overlay outside the overlay container still resolves', () => {
        // A single span-target field is unambiguous.
        expect(mgr.getSpanText(overlay({start: 19, end: 36, inField: false})))
            .toBe('renal denervation');
    });

    test('the legacy node is not used when it holds the item title', () => {
        // Slicing "trial" at 19..36 is "", which is what printed as "?".
        expect(mgr.getSpanText(overlay({start: 19, end: 36, inField: true})))
            .not.toBe('');
    });
});

describe('the legacy layout still works', () => {
    beforeEach(() => {
        document.body.innerHTML = `
          <div id="instance-text">
            <div id="text-content" data-original-text="${PASSAGE}">${PASSAGE}</div>
          </div>`;
    });

    test('text comes from #text-content when there is no instance_display', () => {
        expect(mgr.getSpanText(overlay({start: 19, end: 36, inField: false})))
            .toBe('renal denervation');
    });
});

describe('fallbacks', () => {
    test('the overlay own text is used when no original text exists', () => {
        document.body.innerHTML = '<div id="host"></div>';
        const el = document.createElement('span');
        el.dataset.start = '0';
        el.dataset.end = '5';
        el.textContent = 'fallback text';
        document.getElementById('host').appendChild(el);

        expect(mgr.getSpanText(el)).toBe('fallback text');
    });

    test('highlight segments win over the raw overlay text', () => {
        document.body.innerHTML = '<div id="host"></div>';
        const el = document.createElement('span');
        el.dataset.start = '0';
        el.dataset.end = '5';
        el.innerHTML = '<span class="span-highlight-segment">renal</span>' +
                       '<span class="span-label">LABEL</span>';
        document.getElementById('host').appendChild(el);

        expect(mgr.getSpanText(el)).toBe('renal');
    });
});

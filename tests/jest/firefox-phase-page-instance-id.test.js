/**
 * The Firefox-only instance_id fix must not blank the synthetic
 * '__phase_page__' id that consent, instructions and survey pages use.
 *
 * aggressiveFirefoxInstanceIdFix() runs 200ms after load in Firefox. On a
 * phase page it found no id in the scripts or the URL and called
 * applyInstanceIdFix(input, null), which set currentInstance.id to null.
 * saveAnnotations() then returned early, the required answers never reached
 * the server, and the next page request failed with HTTP 400.
 */

const fs = require('fs');
const path = require('path');

const SOURCE = path.join(__dirname, '..', '..', 'potato', 'static', 'annotation.js');

function extractFunction(source, name) {
    const start = source.indexOf(`function ${name}(`);
    if (start === -1) throw new Error(`${name}() not found in annotation.js`);
    const open = source.indexOf('{', start);
    let depth = 0;
    for (let j = open; j < source.length; j++) {
        if (source[j] === '{') depth++;
        else if (source[j] === '}') {
            depth--;
            if (depth === 0) return source.slice(start, j + 1);
        }
    }
    throw new Error(`unbalanced braces reading ${name}()`);
}

const FIREFOX_UA = 'Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0';

function load(instance) {
    const src = fs.readFileSync(SOURCE, 'utf8');
    const body = ['aggressiveFirefoxInstanceIdFix', 'applyInstanceIdFix']
        .map((name) => extractFunction(src, name)).join('\n');
    return new Function('instance', `
        let currentInstance = instance;
        function debugLog() {}
        ${body}
        return {
            aggressiveFirefoxInstanceIdFix,
            applyInstanceIdFix,
            currentId: () => currentInstance.id,
        };
    `)(instance);
}

describe('Firefox instance_id fix on phase pages', () => {
    let uaSpy;

    beforeEach(() => {
        jest.useFakeTimers();
        uaSpy = jest.spyOn(window.navigator, 'userAgent', 'get').mockReturnValue(FIREFOX_UA);
        document.body.innerHTML = '<input type="hidden" id="instance_id" value="">';
        global.fetch = jest.fn();
    });

    afterEach(() => {
        uaSpy.mockRestore();
        jest.useRealTimers();
        delete window.config;
        delete window.currentInstance;
    });

    test('keeps the __phase_page__ id on a consent page', () => {
        window.config = { is_annotation_page: false };
        const instance = { id: '__phase_page__', text: '', displayed_text: '' };
        window.currentInstance = instance;
        const api = load(instance);

        api.aggressiveFirefoxInstanceIdFix();
        jest.advanceTimersByTime(500);

        expect(api.currentId()).toBe('__phase_page__');
        expect(window.currentInstance.id).toBe('__phase_page__');
        expect(global.fetch).not.toHaveBeenCalled();
    });

    test('applyInstanceIdFix never sets a null or empty id', () => {
        const instance = { id: 'item_7' };
        window.currentInstance = instance;
        const api = load(instance);
        const input = document.getElementById('instance_id');
        input.value = 'item_7';

        api.applyInstanceIdFix(input, null);
        api.applyInstanceIdFix(input, '');

        expect(api.currentId()).toBe('item_7');
        expect(input.value).toBe('item_7');
    });

    test('still corrects the id on an annotation page', () => {
        window.config = { is_annotation_page: true };
        document.body.innerHTML = '<input type="hidden" id="instance_id" value="stale">'
            + '<script>var x = {instance_id: "item_9"};</script>';
        const instance = { id: 'stale' };
        window.currentInstance = instance;
        const api = load(instance);

        api.aggressiveFirefoxInstanceIdFix();
        jest.advanceTimersByTime(500);

        expect(api.currentId()).toBe('item_9');
        expect(document.getElementById('instance_id').value).toBe('item_9');
    });
});

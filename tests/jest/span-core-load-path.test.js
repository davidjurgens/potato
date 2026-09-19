/**
 * What the annotation page waits on before it drops "Loading annotation
 * interface".
 *
 * loadCurrentInstance() awaits spanManager.loadAnnotations(), and that method
 * used to make three requests in a row: /api/current_instance (to learn an id
 * the page already had in #instance_id), /api/spans, then
 * /api/keyword_highlights. On an 80 ms link each one was ~160 ms of the
 * loading screen, on every task type, spans or not.
 *
 * Separately, the 1 s initialization retry fired whenever initialize() had not
 * finished, which over a real network it never had: two initializations ran
 * side by side and bound every selection listener twice.
 */

const { SpanManager } = require('../../potato/static/span-core.js');

function deferred() {
    let resolve;
    const promise = new Promise(r => { resolve = r; });
    return { promise, resolve };
}

function jsonResponse(body, status = 200) {
    return Promise.resolve({
        ok: status >= 200 && status < 300,
        status,
        statusText: String(status),
        json: async () => body,
        text: async () => JSON.stringify(body),
    });
}

/** A manager whose rendering is stubbed out; the network is what is under test. */
function manager() {
    const m = new SpanManager();
    m.renderSpans = jest.fn();
    m.clearAllStateAndOverlays = jest.fn();
    return m;
}

let requested;
let keywordReply;

beforeEach(() => {
    requested = [];
    keywordReply = null;
    document.getElementById('instance_id').value = 'item_7';
    window.config = { is_annotation_page: true };
    global.fetch = jest.fn((url) => {
        requested.push(String(url));
        if (String(url).startsWith('/api/current_instance')) {
            return jsonResponse({ instance_id: 'item_7' });
        }
        if (String(url).startsWith('/api/spans/')) {
            return jsonResponse({ spans: [] });
        }
        if (String(url).startsWith('/api/keyword_highlights/')) {
            return keywordReply ? keywordReply.promise : jsonResponse({}, 404);
        }
        return jsonResponse({}, 404);
    });
});

afterEach(() => { jest.restoreAllMocks(); });

describe('loading the rendered instance', () => {
    test('asks only for its spans', async () => {
        await manager().loadAnnotations('item_7');
        expect(requested.filter(u => u.startsWith('/api/current_instance'))).toEqual([]);
        expect(requested).toContain('/api/spans/item_7');
    });

    test('still makes the id current', async () => {
        const m = manager();
        await m.loadAnnotations('item_7');
        expect(m.currentInstanceId).toBe('item_7');
        expect(m.lastKnownInstanceId).toBe('item_7');
    });

    test('clears overlays belonging to a previous instance', async () => {
        const m = manager();
        m.currentInstanceId = 'item_6';
        await m.loadAnnotations('item_7');
        expect(m.clearAllStateAndOverlays).toHaveBeenCalled();
    });

    test('does not wait for keyword highlights', async () => {
        keywordReply = deferred();   // never answered during the test
        const m = manager();
        await expect(Promise.race([
            m.loadAnnotations('item_7').then(() => 'loaded'),
            new Promise(r => setTimeout(() => r('blocked'), 200)),
        ])).resolves.toBe('loaded');
        expect(requested).toContain('/api/keyword_highlights/item_7');
        keywordReply.resolve({ ok: false, status: 404 });
    });
});

describe('anything else still asks the server', () => {
    test('a page that is not the annotation page', async () => {
        window.config = { is_annotation_page: false };
        await manager().loadAnnotations('item_7');
        expect(requested[0]).toBe('/api/current_instance');
    });

    test('an id other than the one rendered', async () => {
        await manager().loadAnnotations('item_3');
        expect(requested[0]).toBe('/api/current_instance');
    });

    test('no id at all', async () => {
        await manager().loadAnnotations(undefined);
        expect(requested[0]).toBe('/api/current_instance');
    });
});

describe('initialize()', () => {
    test('concurrent calls share one run', async () => {
        const m = manager();
        const gate = deferred();
        m.initializeNow = jest.fn(() => gate.promise);

        const first = m.initialize();
        const second = m.initialize();   // the 1 s retry, mid-initialization
        expect(m.initializeNow).toHaveBeenCalledTimes(1);
        expect(second).toBe(first);

        gate.resolve(true);
        await first;
    });

    test('a later call after a finished run starts a new one', async () => {
        const m = manager();
        m.initializeNow = jest.fn(async () => false);
        await m.initialize();
        await m.initialize();
        expect(m.initializeNow).toHaveBeenCalledTimes(2);
    });

    test('a failed run does not wedge later calls', async () => {
        const m = manager();
        m.initializeNow = jest.fn()
            .mockImplementationOnce(async () => { throw new Error('boom'); })
            .mockImplementationOnce(async () => true);
        await expect(m.initialize()).rejects.toThrow('boom');
        await expect(m.initialize()).resolves.toBe(true);
    });
});

describe('keyword highlights aborted by leaving the page', () => {
    // Keyword highlights load in the background, so Next is often clicked
    // while one is in flight. The browser aborts it with a TypeError
    // ("Failed to fetch"), which is not an error.
    function failKeywords() {
        global.fetch.mockImplementation((url) => {
            if (String(url).startsWith('/api/keyword_highlights/')) {
                return Promise.reject(new TypeError('Failed to fetch'));
            }
            return jsonResponse({ spans: [] });
        });
    }

    const keywordErrors = () => console.error.mock.calls.filter(
        c => String(c[0]).includes('keyword highlights'));

    test('is not logged once the page is being left', async () => {
        const m = manager();
        failKeywords();
        window.dispatchEvent(new Event('beforeunload'));
        await m.loadKeywordHighlights('item_7');
        expect(keywordErrors()).toEqual([]);
    });

    test('is still logged while the page is in use', async () => {
        const m = manager();
        failKeywords();
        await m.loadKeywordHighlights('item_7');
        expect(keywordErrors()).toHaveLength(1);
    });

    test('a server error is logged even while leaving', async () => {
        const m = manager();
        global.fetch.mockImplementation(() => jsonResponse({}, 500));
        window.dispatchEvent(new Event('pagehide'));
        await m.loadKeywordHighlights('item_7');
        expect(keywordErrors()).toHaveLength(1);
    });
});

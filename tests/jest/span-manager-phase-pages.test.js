/**
 * SpanManager on a page that has no instance.
 *
 * `/api/current_instance` has a phase guard: on consent, instructions, training
 * and the survey pages there is no instance, so it 404s. That is the endpoint
 * working. SpanManager initialised on those pages anyway, threw on the 404 and
 * logged two `console.error` lines every time — so every phase page opened with
 * red in the console, and the errors that mean something were buried under
 * errors that do not.
 */

const fs = require('fs');
const path = require('path');

const SOURCE = path.join(__dirname, '..', '..', 'potato', 'static', 'span-core.js');

/** Pull one class method out of a script that cannot be imported. */
function extractMethod(source, name) {
    const start = source.indexOf(`    async ${name}(`);
    if (start === -1) throw new Error(`${name}() not found in span-core.js`);
    const open = source.indexOf('{', start);
    let depth = 0;
    for (let j = open; j < source.length; j++) {
        if (source[j] === '{') depth++;
        else if (source[j] === '}') {
            depth--;
            if (depth === 0) return source.slice(open, j + 1);
        }
    }
    throw new Error(`unbalanced braces reading ${name}()`);
}

let fetchCurrentInstanceIdFromServer;

beforeAll(() => {
    const body = extractMethod(fs.readFileSync(SOURCE, 'utf8'),
                               'fetchCurrentInstanceIdFromServer');
    // eslint-disable-next-line no-new-func
    fetchCurrentInstanceIdFromServer = new Function(`return async function () ${body};`)();
});

function manager() {
    return {
        currentInstanceId: null,
        lastKnownInstanceId: null,
        cleared: 0,
        clearAllStateAndOverlays() { this.cleared++; },
    };
}

function respond(status, body) {
    global.fetch = jest.fn().mockResolvedValue({
        ok: status >= 200 && status < 300,
        status,
        json: async () => body,
    });
}

let errors;
beforeEach(() => {
    errors = [];
    jest.spyOn(console, 'error').mockImplementation((...a) => errors.push(a.join(' ')));
    window.config = {debug: false};
});
afterEach(() => { jest.restoreAllMocks(); });

describe('a page with no instance', () => {
    test('404 yields null without logging an error', async () => {
        respond(404, {});
        const m = manager();

        await expect(fetchCurrentInstanceIdFromServer.call(m)).resolves.toBeNull();
        expect(errors).toEqual([]);
    });

    test('the manager is left with no instance id', async () => {
        respond(404, {});
        const m = manager();
        m.currentInstanceId = 'stale';

        await fetchCurrentInstanceIdFromServer.call(m);
        expect(m.currentInstanceId).toBeNull();
    });
});

describe('a real failure is still a failure', () => {
    test('500 is reported', async () => {
        respond(500, {});

        await expect(fetchCurrentInstanceIdFromServer.call(manager())).resolves.toBeNull();
        expect(errors.join(' ')).toMatch(/500/);
    });
});

describe('the annotation page is unaffected', () => {
    test('200 returns the instance id', async () => {
        respond(200, {instance_id: 'a01'});
        const m = manager();

        await expect(fetchCurrentInstanceIdFromServer.call(m)).resolves.toBe('a01');
        expect(m.currentInstanceId).toBe('a01');
        expect(errors).toEqual([]);
    });

    test('a changed instance still clears the previous overlays', async () => {
        respond(200, {instance_id: 'a02'});
        const m = manager();
        m.currentInstanceId = 'a01';

        await fetchCurrentInstanceIdFromServer.call(m);
        expect(m.cleared).toBe(1);
    });
});

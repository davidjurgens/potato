/**
 * Shared harness for the live-session applier tests of the survey,
 * experiment, linguistics, graph and viewer schemes (*-collab.test.js).
 *
 * It boots the REAL collab.js and drives its applyKeys(), so each test goes
 * through the same lookup a session page uses: the scheme's form (or #id),
 * its data-annotation-type, the hidden inputs collab.js writes, and then the
 * widget's registered applier.
 */

const fs = require('fs');
const path = require('path');

const STATIC = path.join(__dirname, '..', '..', 'potato', 'static');

/** Run a static file the way the page does (a classic script). */
function loadStatic(rel) {
    // eslint-disable-next-line no-new-func
    new Function(fs.readFileSync(path.join(STATIC, rel), 'utf8'))();
}

/**
 * Boot collab.js. `respond(url, init)` answers every fetch made after this
 * (widgets' own reads included); it returns a JSON-able body or a Response-
 * like object. Every request is recorded in `calls`.
 */
function bootCollab(respond) {
    const calls = [];
    window.fetch = jest.fn((input, init) => {
        const url = typeof input === 'string' ? input : (input && input.url) || String(input);
        calls.push({ url, init: init || {} });
        const body = respond ? respond(url, init || {}) : undefined;
        if (body && typeof body.json === 'function') return Promise.resolve(body);
        return Promise.resolve({
            ok: true, status: 200,
            json: () => Promise.resolve(body === undefined ? {} : body),
            text: () => Promise.resolve(''),
            clone() { return this; },
        });
    });
    window.potatoCollab = {
        sid: 'S1', me: 'ben', instance_id: 'item-1', rev: 1, cursor: 0,
        team_user: 'team-red', transport: 'poll', poll_interval_ms: 1e9, base: '',
    };
    delete window.potatoCollabClient;
    delete window.potatoSaveHooks;
    delete window.potatoNavigation;
    loadStatic('collab.js');
    // The shared jest setup calls mockClear on fetch between tests.
    window.fetch.mockClear = () => {};
    return { client: window.potatoCollabClient, calls };
}

/**
 * Apply a team answer to one scheme through collab.js, as a teammate's save
 * would. `labels` is the scheme's whole answer {label: value}, or null for
 * no answer; `names` lists label names that changed (defaults to the
 * answer's own, plus `also`). Returns the set of keys shown live.
 */
function applyTeam(client, schema, labels, names) {
    const answer = {};
    Object.keys(labels || {}).forEach((l) => { answer[`L:${schema}:::${l}`] = labels[l]; });
    const changed = new Set((names || Object.keys(labels || {})).map((l) => `L:${schema}:::${l}`));
    return client.applyKeys(changed, answer);
}

/** Saves the page must not make while applying. */
function watchSaves(calls) {
    const saveAnnotations = jest.fn();
    window.saveAnnotations = saveAnnotations;
    global.saveAnnotations = saveAnnotations;
    const mark = calls.length;
    return {
        saveAnnotations,
        posts: () => calls.slice(mark).filter((c) => /updateinstance/.test(c.url)
            || ((c.init.method || 'GET').toUpperCase() !== 'GET' && !/\/collab\//.test(c.url))),
    };
}

/** Count `change` events a hidden input fires. */
function countChanges(el) {
    const counter = { n: 0 };
    el.addEventListener('change', () => { counter.n += 1; });
    return counter;
}

function flush() {
    return new Promise((resolve) => setTimeout(resolve, 0));
}

module.exports = { loadStatic, bootCollab, applyTeam, watchSaves, countChanges, flush, STATIC };

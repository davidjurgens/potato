/**
 * The notes sidebar honours `show_sidebar_by_default` — and honours a close.
 *
 * The flag was parsed, defaulted to true, and served from /qda/status, but no
 * client code read it, so the sidebar was always collapsed. The server side is
 * covered by tests/server/test_memos_sidebar_default.py; this covers the half
 * that was missing entirely, the client acting on what it is told.
 *
 * Potato navigation is a full page reload, so "open by default" runs again on
 * every item. Without a memory of the annotator's close, the panel would keep
 * reappearing after being dismissed — which is why the dismissal cases matter
 * as much as the opening one.
 */

function buildPage() {
    document.body.innerHTML = `
        <input type="hidden" id="instance_id" value="inst-1">
        <button type="button" id="memo-panel-toggle" hidden></button>
        <div id="memo-panel" hidden>
            <button type="button" id="memo-panel-close"></button>
            <div id="memo-list"></div>
            <textarea id="memo-new-body"></textarea>
            <div id="memo-anchor-wrap" hidden></div>
            <select id="memo-visibility"><option value="private">private</option></select>
            <button type="button" id="memo-add-btn"></button>
        </div>`;
}

/** Load memos.js fresh, with the listing endpoint answering `body`. */
function loadClient(body) {
    jest.resetModules();
    window.config = { is_annotation_page: true };
    global.fetch = jest.fn(() => Promise.resolve({
        status: 200,
        json: () => Promise.resolve(body),
    }));
    require('../../potato/static/memos.js');
    return window.MemoPanel.reload();
}

const panel = () => document.getElementById('memo-panel');
const toggle = () => document.getElementById('memo-panel-toggle');

beforeEach(() => {
    sessionStorage.clear();
    buildPage();
});

describe('when the project asks for it', () => {
    test('the sidebar starts open', async () => {
        await loadClient({ memos: [], open_by_default: true });
        expect(panel().hidden).toBe(false);
        expect(toggle().hidden).toBe(true);
    });
});

describe('when it does not', () => {
    test('the sidebar starts collapsed, with its opener showing', async () => {
        await loadClient({ memos: [], open_by_default: false });
        expect(panel().hidden).toBe(true);
        expect(toggle().hidden).toBe(false);
    });

    test('an older server that says nothing keeps the old behaviour', async () => {
        await loadClient({ memos: [] });
        expect(panel().hidden).toBe(true);
    });
});

describe('closing it means closing it', () => {
    test('a dismissal survives the next page load', async () => {
        await loadClient({ memos: [], open_by_default: true });
        expect(panel().hidden).toBe(false);

        document.getElementById('memo-panel-close').click();
        expect(panel().hidden).toBe(true);

        // Next item: a full reload, same tab.
        buildPage();
        await loadClient({ memos: [], open_by_default: true });
        expect(panel().hidden).toBe(true);
        expect(toggle().hidden).toBe(false);
    });

    test('re-opening it by hand clears the dismissal', async () => {
        await loadClient({ memos: [], open_by_default: true });
        document.getElementById('memo-panel-close').click();
        toggle().click();
        expect(panel().hidden).toBe(false);

        buildPage();
        await loadClient({ memos: [], open_by_default: true });
        expect(panel().hidden).toBe(false);
    });
});

describe('a project with memos switched off entirely', () => {
    test('503 leaves the panel and its opener alone', async () => {
        jest.resetModules();
        window.config = { is_annotation_page: true };
        global.fetch = jest.fn(() => Promise.resolve({ status: 503 }));
        require('../../potato/static/memos.js');
        await window.MemoPanel.reload();
        expect(panel().hidden).toBe(true);
        expect(toggle().hidden).toBe(true);
    });
});

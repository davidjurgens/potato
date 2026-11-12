/**
 * The memo composer starts on the project's default visibility
 * (annotation_ui.visibility, rendered as data-default-visibility), even when
 * the browser restored the select to the last item's choice.
 *
 * The edit-then-add path is covered in the browser by
 * tests/selenium/test_memos_ui.py.
 */

function buildPage(defaultVisibility, restoredValue) {
    document.body.innerHTML = `
        <input type="hidden" id="instance_id" value="inst-1">
        <button type="button" id="memo-panel-toggle" hidden></button>
        <div id="memo-panel" hidden>
            <button type="button" id="memo-panel-close"></button>
            <div id="memo-list"></div>
            <textarea id="memo-new-body"></textarea>
            <select id="memo-new-visibility" data-default-visibility="${defaultVisibility}">
                <option value="private">Private</option>
                <option value="shared">Shared</option>
            </select>
            <button type="button" id="memo-add-btn"></button>
        </div>`;
    document.getElementById('memo-new-visibility').value = restoredValue;
}

function loadClient() {
    jest.resetModules();
    window.config = { is_annotation_page: true };
    global.fetch = jest.fn(() => Promise.resolve({
        status: 200,
        json: () => Promise.resolve({ memos: [] }),
    }));
    require('../../potato/static/memos.js');
    return window.MemoPanel.reload();
}

const select = () => document.getElementById('memo-new-visibility');

beforeEach(() => sessionStorage.clear());

test('a shared default wins over a restored private choice', async () => {
    buildPage('shared', 'private');
    await loadClient();
    expect(select().value).toBe('shared');
});

test('a private default wins over a restored shared choice', async () => {
    buildPage('private', 'shared');
    await loadClient();
    expect(select().value).toBe('private');
});

test('an unrecognised default falls back to private', async () => {
    buildPage('everyone', 'shared');
    await loadClient();
    expect(select().value).toBe('private');
});

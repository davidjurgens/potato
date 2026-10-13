/**
 * Audio annotation: what the annotator sees when the audio does not load, and
 * the help panel's remembered state.
 *
 * Before: a failed load printed "Failed to load audio waveform. Please try
 * refreshing the page." into the page-wide status line (unstyled, above the
 * instructions, gone after three seconds), blamed a transient fault for a file
 * that was missing or unreachable, and left play/zoom/segment live over two
 * empty grey boxes.
 */

require('../../potato/static/audio-annotation.js');
const AudioAnnotationManager = window.AudioAnnotationManager;

function setup() {
    document.body.innerHTML = `
        <div class="audio-annotation-container" data-schema="seg">
            <div id="overview-seg" class="overview-container"></div>
            <div id="waveform-seg" class="waveform-container"></div>
            <div class="audio-annotation-toolbar">
                <button type="button" class="playback-btn" data-action="play">Play</button>
                <button type="button" class="zoom-btn" data-action="zoom-in">+</button>
                <button type="button" class="segment-btn" data-action="set-start">[</button>
                <select class="playback-rate-select"><option value="1">1x</option></select>
                <button type="button" class="label-btn" data-label="speech">speech</button>
                <div class="help-toggle">
                    <button type="button" class="help-toggle-btn" aria-expanded="true">Help</button>
                </div>
            </div>
            <div class="help-panel">usage</div>
            <audio id="audio-seg"></audio>
        </div>`;
    const container = document.querySelector('.audio-annotation-container');
    return new AudioAnnotationManager({
        container,
        waveformId: 'waveform-seg',
        overviewId: 'overview-seg',
        audioId: 'audio-seg',
        config: {schemaName: 'seg'},
    });
}

describe('load failure', () => {
    test('names the HTTP status the server actually returned', async () => {
        const m = setup();
        global.fetch.mockResolvedValueOnce(
            {ok: false, status: 502, statusText: 'Bad Gateway', body: null});
        const reason = await m._describeLoadFailure('/api/audio/proxy?url=x');
        expect(reason).toContain('HTTP 502 Bad Gateway');
        expect(reason).not.toMatch(/refresh/i);
    });

    test('does not guess a cause when the file cannot be reached', async () => {
        const m = setup();
        global.fetch.mockRejectedValueOnce(new TypeError('Failed to fetch'));
        const reason = await m._describeLoadFailure('https://elsewhere.example/a.mp3');
        expect(reason).toBe('The audio file could not be reached from this browser.');
        expect(reason).not.toMatch(/CORS/);
    });

    test('blames the format only when the server delivered the file', async () => {
        const m = setup();
        global.fetch.mockResolvedValueOnce({ok: true, status: 206, body: null});
        Object.defineProperty(m.audioEl, 'error', {value: {code: 4}, configurable: true});
        const reason = await m._describeLoadFailure('/a.weird');
        expect(reason).toMatch(/cannot play its format/);
    });

    test('shows the reason inside the waveform pane, as an alert', () => {
        const m = setup();
        m.showLoadFailure('The audio file could not be loaded: the server answered HTTP 404.');
        const box = document.querySelector('#waveform-seg .audio-load-error');
        expect(box).not.toBeNull();
        expect(box.getAttribute('role')).toBe('alert');
        expect(box.textContent).toContain('HTTP 404');
    });

    test('disables the controls that need audio, and leaves the labels alone', () => {
        const m = setup();
        m.showLoadFailure('x');
        for (const sel of ['.playback-btn', '.zoom-btn', '.segment-btn', '.playback-rate-select']) {
            expect(document.querySelector(sel).disabled).toBe(true);
        }
        expect(document.querySelector('.label-btn').disabled).toBe(false);
    });

    test('keyboard shortcuts stand down once the load has failed', () => {
        const m = setup();
        m.togglePlayPause = jest.fn();
        m.showLoadFailure('x');
        m._handleKeydown({key: ' ', target: document.body, preventDefault() {}});
        expect(m.togglePlayPause).not.toHaveBeenCalled();
    });
});

describe('help panel', () => {
    afterEach(() => localStorage.clear());

    test('starts open and remembers being closed', () => {
        let m = setup();
        m.setupHelpToggle();
        const panel = () => document.querySelector('.help-panel');
        const btn = () => document.querySelector('.help-toggle-btn');
        expect(panel().classList.contains('collapsed')).toBe(false);

        btn().click();
        expect(panel().classList.contains('collapsed')).toBe(true);
        expect(btn().getAttribute('aria-expanded')).toBe('false');

        // The next item renders the page afresh.
        m = setup();
        m.setupHelpToggle();
        expect(panel().classList.contains('collapsed')).toBe(true);
        expect(btn().getAttribute('aria-expanded')).toBe('false');
    });

    test('still toggles when storage throws', () => {
        const getItem = jest.spyOn(Storage.prototype, 'getItem')
            .mockImplementation(() => { throw new Error('denied'); });
        const setItem = jest.spyOn(Storage.prototype, 'setItem')
            .mockImplementation(() => { throw new Error('denied'); });
        const m = setup();
        m.setupHelpToggle();
        document.querySelector('.help-toggle-btn').click();
        expect(document.querySelector('.help-panel').classList.contains('collapsed')).toBe(true);
        getItem.mockRestore();
        setItem.mockRestore();
    });
});

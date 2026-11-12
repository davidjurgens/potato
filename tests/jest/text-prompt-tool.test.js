/**
 * The prompt box: what happens between typing a phrase and seeing suggestions.
 *
 * The model is stubbed here. What is being checked is the wiring that a live
 * run showed to be fragile — every defect below was found by running it, not
 * by reading it:
 *
 *  * the tool must not bind its own click handler (the manager owns it, and a
 *    second listener fires the detector twice per press);
 *  * the assistant is attached to the container AFTER the manager is built, so
 *    resolving it once at construction finds nothing;
 *  * results must reach the review panel rather than the annotation store.
 */

const { TextPromptTool } = require('../../potato/static/segmentation/text-prompt-tool.js');

function container(withAssistant = true) {
    const rendered = [];
    const el = {
        _nodes: {},
        querySelector(selector) { return this._nodes[selector] || null; },
    };
    el._nodes['.text-prompt-input'] = { value: 'cat, dog' };
    el._nodes['.text-prompt-run'] = { disabled: false, textContent: 'Find' };
    el._nodes['.text-prompt-status'] = { textContent: '', dataset: {} };
    if (withAssistant) {
        el.aiAssistant = {
            _renderDetections(dets) { rendered.push(dets); },
        };
    }
    el.rendered = rendered;
    return el;
}

function manager(image = { naturalWidth: 640, naturalHeight: 480 }) {
    return { image: image ? { getElement: () => image } : null };
}

function session(result) {
    return {
        calls: [],
        isReady: () => true,
        statusMessage: () => 'the detector could not start',
        async detect(source, width, height, phrases) {
            this.calls.push({ width, height, phrases });
            return typeof result === 'function' ? result() : result;
        },
    };
}

function tool(options = {}) {
    const c = options.container || container();
    const t = new TextPromptTool(Object.assign({
        container: c, manager: manager(), session: session([]),
    }, options, { container: c }));
    t.attach();
    return t;
}

describe('reading the prompt', () => {
    test('commas separate phrases', () => {
        expect(tool().phrases()).toEqual(['cat', 'dog']);
    });

    test('whitespace and empty entries are dropped', () => {
        const c = container();
        c._nodes['.text-prompt-input'].value = ' cat ,, , dog  ';
        expect(tool({ container: c }).phrases()).toEqual(['cat', 'dog']);
    });
});

describe('attaching', () => {
    test('it binds no listeners of its own', () => {
        // The manager owns the click, because pressing Find is what triggers
        // the download that builds this tool. A listener here would run the
        // detector a second time on every press.
        const c = container();
        c._nodes['.text-prompt-run'].addEventListener = jest.fn();
        c._nodes['.text-prompt-input'].addEventListener = jest.fn();
        tool({ container: c });
        expect(c._nodes['.text-prompt-run'].addEventListener).not.toHaveBeenCalled();
        expect(c._nodes['.text-prompt-input'].addEventListener).not.toHaveBeenCalled();
    });
});

describe('running', () => {
    test('an empty prompt asks for one rather than calling the model', async () => {
        const c = container();
        c._nodes['.text-prompt-input'].value = '   ';
        const s = session([]);
        const t = tool({ container: c, session: s });
        expect(await t.run()).toBe(null);
        expect(s.calls).toHaveLength(0);
        expect(c._nodes['.text-prompt-status'].textContent).toMatch(/Type what/);
    });

    test('it passes the image size the model needs', async () => {
        const s = session([]);
        const t = tool({ session: s });
        await t.run();
        expect(s.calls[0]).toMatchObject({ width: 640, height: 480,
                                           phrases: ['cat', 'dog'] });
    });

    test('with no image it says so instead of throwing', async () => {
        const c = container();
        const t = new TextPromptTool({
            container: c, manager: { image: null }, session: session([]),
        });
        t.attach();
        expect(await t.run()).toBe(null);
        expect(c._nodes['.text-prompt-status'].textContent).toMatch(/No image/);
    });

    test('detections go to the review panel, never straight to the canvas', async () => {
        const c = container();
        const t = tool({
            container: c,
            session: session([{ label: 'cat', confidence: 0.9,
                                bbox: { x: 0.1, y: 0.1, width: 0.2, height: 0.2 } }]),
        });
        await t.run();
        expect(c.rendered).toHaveLength(1);
        expect(c.rendered[0][0].label).toBe('cat');
        expect(c._nodes['.text-prompt-status'].textContent).toMatch(/1 suggestion —/);
    });

    test('the count is singular for one and plural for several', async () => {
        const c = container();
        const two = [
            { label: 'cat', confidence: 0.9, bbox: { x: 0, y: 0, width: 0.1, height: 0.1 } },
            { label: 'dog', confidence: 0.8, bbox: { x: 0.2, y: 0.2, width: 0.1, height: 0.1 } },
        ];
        await tool({ container: c, session: session(two) }).run();
        expect(c._nodes['.text-prompt-status'].textContent).toMatch(/2 suggestions/);
    });

    test('finding nothing is reported, not left silent', async () => {
        const c = container();
        await tool({ container: c, session: session([]) }).run();
        expect(c._nodes['.text-prompt-status'].textContent).toMatch(/Nothing matched/);
        expect(c.rendered).toHaveLength(0);
    });

    test('a model failure shows the session\'s own message', async () => {
        const c = container();
        await tool({ container: c, session: session(null) }).run();
        expect(c._nodes['.text-prompt-status'].textContent)
            .toMatch(/could not start/);
        expect(c._nodes['.text-prompt-status'].dataset.kind).toBe('error');
    });

    test('the button reports progress and is re-enabled afterwards', async () => {
        const c = container();
        const button = c._nodes['.text-prompt-run'];
        let sawBusy = false;
        const t = tool({
            container: c,
            session: session(() => {
                sawBusy = button.disabled && /Finding/.test(button.textContent);
                return [];
            }),
        });
        await t.run();
        expect(sawBusy).toBe(true);
        expect(button.disabled).toBe(false);
        expect(button.textContent).toBe('Find');
    });

    test('a second press while running is ignored', async () => {
        const s = session(async () => { await new Promise(r => setTimeout(r, 30)); return []; });
        const t = tool({ session: s });
        const first = t.run();
        const second = await t.run();
        await first;
        expect(second).toBe(null);
        expect(s.calls).toHaveLength(1);
    });
});

describe('finding the review panel', () => {
    test('the assistant is resolved late, not cached at construction', async () => {
        // The schema bootstrap attaches the assistant AFTER building the
        // manager, so a tool built in between sees nothing at construction.
        const c = container(false);
        const t = tool({
            container: c,
            session: session([{ label: 'cat', confidence: 0.9,
                                bbox: { x: 0, y: 0, width: 0.1, height: 0.1 } }]),
        });
        const rendered = [];
        c.aiAssistant = { _renderDetections: (d) => rendered.push(d) };
        await t.run();
        expect(rendered).toHaveLength(1);
    });

    test('with no panel at all it says so rather than dropping results', async () => {
        const c = container(false);
        await tool({
            container: c,
            session: session([{ label: 'cat', confidence: 0.9,
                                bbox: { x: 0, y: 0, width: 0.1, height: 0.1 } }]),
        }).run();
        expect(c._nodes['.text-prompt-status'].textContent).toMatch(/no review panel/);
        expect(c._nodes['.text-prompt-status'].dataset.kind).toBe('error');
    });
});

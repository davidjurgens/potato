/**
 * The VLM critique review queue.
 *
 * The behaviour worth pinning is not the rendering, it is the restraint: no
 * verdict may change an annotation without a button press, an index that no
 * longer refers to the reviewed shape must refuse to act, and a "possibly
 * missed" hint must never become an annotation. Each of those is one edit
 * away from being wrong in a way no test would otherwise notice.
 */

const fs = require('fs');
const path = require('path');

const SOURCE = fs.readFileSync(
    path.join(__dirname, '../../potato/static/annotation_critique.js'), 'utf8');

/** A stand-in for ImageAnnotationManager recording what was asked of it. */
function makeManager(objects = [], instanceId = 'street_1') {
    const container = document.createElement('div');
    container.className = 'image-annotation-container';
    document.body.appendChild(container);

    // The page's hidden instance_id input, which the review reads so the
    // server is told which image to fetch rather than guessing.
    const idInput = document.createElement('input');
    idInput.type = 'hidden';
    idInput.id = 'instance_id';
    idInput.value = instanceId;
    document.body.appendChild(idInput);

    return {
        container,
        config: { schemaName: 'objects' },
        calls: [],
        _objects: objects.slice(),
        _serializeAnnotations() {
            return JSON.stringify(this._objects);
        },
        getAnnotationHandles() {
            return this._objects.map((o, i) => ({
                index: i, kind: 'object', label: o.label, type: o.type,
            }));
        },
        focusAnnotation(index) {
            this.calls.push(['focus', index]);
            return true;
        },
        relabelAnnotation(index, label) {
            this.calls.push(['relabel', index, label]);
            this._objects[index].label = label;
            return true;
        },
        deleteAnnotation(index) {
            this.calls.push(['delete', index]);
            this._objects.splice(index, 1);
            return true;
        },
        canvas: {
            add: jest.fn(),
            remove: jest.fn(),
            requestRenderAll: jest.fn(),
        },
        image: { left: 0, top: 0, width: 100, height: 100, scaleX: 1, scaleY: 1 },
    };
}

function box(label) {
    return { type: 'bbox', label, coordinates: { x: 0, y: 0, width: 0.1, height: 0.1 } };
}

function response(overrides = {}) {
    return Object.assign({
        instance_id: 'i1',
        schema: 'objects',
        verdicts: [],
        missed: [],
        summary: { reviewed: 0, confirmed: 0, flagged: 0, uncertain: 0,
                   errors: 0, missed: 0, skipped: 0, by_verdict: {},
                   caveat: 'A model\'s opinions, not ground truth.' },
        model: 'test-vlm',
    }, overrides);
}

function verdict(index, over = {}) {
    return Object.assign({
        index, label: 'cat', verdict: 'wrong_label', boundary: 'tight',
        suggested_label: 'dog', confidence: 0.9,
        rationale: 'It has a long snout.', flagged: true, error: '',
    }, over);
}

// The shared setup.js installs a global fetch mock and calls fetch.mockClear()
// around every test, so these helpers REPLACE its implementation rather than
// reassigning `global.fetch` — deleting it would break the shared teardown for
// every test after the first.
function mockFetch(payload, ok = true, status = 200) {
    global.fetch.mockImplementation(() => Promise.resolve({
        ok, status, json: () => Promise.resolve(payload),
    }));
}

function mockFetchFailure(message) {
    global.fetch.mockImplementation(() => Promise.reject(new Error(message)));
}

beforeAll(() => {
    // eslint-disable-next-line no-eval
    eval(SOURCE);
    global.fabric = {
        Rect: function (opts) { Object.assign(this, opts); },
    };
});

afterEach(() => {
    document.body.innerHTML = '';
    delete window.recordAnnotationTelemetry;
    global.fetch.mockReset();
});

function click(panel, action) {
    const button = panel.querySelector(`button[data-critique-action="${action}"]`);
    if (!button) throw new Error(`no ${action} button`);
    button.click();
    return button;
}

describe('requesting a critique', () => {
    test('posts the annotations currently on the canvas', async () => {
        const manager = makeManager([box('cat')]);
        mockFetch(response());
        const review = new AnnotationCritiqueReview(manager);
        await review.run();

        expect(global.fetch).toHaveBeenCalledTimes(1);
        const [url, options] = global.fetch.mock.calls[0];
        expect(url).toBe('/api/critique_annotations');
        expect(options.method).toBe('POST');
        const body = JSON.parse(options.body);
        expect(body.schema).toBe('objects');
        expect(body.objects).toHaveLength(1);
    });

    test('names the instance rather than letting the server guess', async () => {
        // The boxes come from the canvas. If the server fell back to its own
        // current-instance pointer and the two disagreed, the model would be
        // shown one image and handed another image's geometry.
        const manager = makeManager([box('cat')], 'street_3');
        mockFetch(response());
        const review = new AnnotationCritiqueReview(manager);
        await review.run();

        const body = JSON.parse(global.fetch.mock.calls[0][1].body);
        expect(body.instance_id).toBe('street_3');
    });

    test('a server error is shown, not swallowed', async () => {
        const manager = makeManager([box('cat')]);
        mockFetch({ error: 'No vision model configured' }, false, 503);
        const review = new AnnotationCritiqueReview(manager);
        await review.run();

        expect(review.panel.textContent).toContain('No vision model configured');
        expect(review.panel.querySelector('[role="alert"]')).toBeTruthy();
    });

    test('a network failure is shown, not swallowed', async () => {
        const manager = makeManager([box('cat')]);
        mockFetchFailure('offline');
        const review = new AnnotationCritiqueReview(manager);
        await review.run();

        expect(review.panel.textContent).toContain('offline');
    });

    test('overlapping runs do not double-fetch', async () => {
        const manager = makeManager([box('cat')]);
        mockFetch(response());
        const review = new AnnotationCritiqueReview(manager);
        const first = review.run();
        await review.run();  // ignored: still loading
        await first;
        expect(global.fetch).toHaveBeenCalledTimes(1);
    });
});

describe('what the queue shows', () => {
    test('the count that matters leads', async () => {
        const manager = makeManager([box('cat'), box('cat')]);
        mockFetch(response({
            verdicts: [verdict(0), verdict(1, { verdict: 'confirmed', flagged: false })],
            summary: Object.assign(response().summary, { reviewed: 2, confirmed: 1, flagged: 1 }),
        }));
        const review = new AnnotationCritiqueReview(manager);
        await review.run();

        expect(review.panel.querySelector('.critique-heading').textContent)
            .toContain('1 to look at');
    });

    test('confirmations are collapsed rather than celebrated', async () => {
        const manager = makeManager([box('cat')]);
        mockFetch(response({
            verdicts: [verdict(0, { verdict: 'confirmed', flagged: false })],
        }));
        const review = new AnnotationCritiqueReview(manager);
        await review.run();

        const disclosure = review.panel.querySelector('.critique-disclosure');
        expect(disclosure).toBeTruthy();
        expect(disclosure.getAttribute('aria-expanded')).toBe('false');
        expect(review.panel.querySelector('.critique-quiet').hidden).toBe(true);

        disclosure.click();
        expect(disclosure.getAttribute('aria-expanded')).toBe('true');
        expect(review.panel.querySelector('.critique-quiet').hidden).toBe(false);
    });

    test('the caveat is always rendered', async () => {
        const manager = makeManager([box('cat')]);
        mockFetch(response({ verdicts: [verdict(0)] }));
        const review = new AnnotationCritiqueReview(manager);
        await review.run();

        expect(review.panel.querySelector('.critique-caveat').textContent)
            .toContain('not ground truth');
    });

    test('a clean pass does not claim the annotations are correct', async () => {
        const manager = makeManager([box('cat')]);
        mockFetch(response({
            verdicts: [verdict(0, { verdict: 'confirmed', flagged: false })],
        }));
        const review = new AnnotationCritiqueReview(manager);
        await review.run();

        const text = review.panel.querySelector('.critique-clean').textContent;
        expect(text).toContain('not proof');
    });

    test('unflagged verdicts get no destructive buttons', async () => {
        const manager = makeManager([box('cat')]);
        mockFetch(response({
            verdicts: [verdict(0, { verdict: 'confirmed', flagged: false })],
        }));
        const review = new AnnotationCritiqueReview(manager);
        await review.run();

        const quiet = review.panel.querySelector('.critique-quiet');
        expect(quiet.querySelector('[data-critique-action="delete"]')).toBeNull();
        expect(quiet.querySelector('[data-critique-action="relabel"]')).toBeNull();
    });

    test('a relabel button only appears when the suggestion differs', async () => {
        const manager = makeManager([box('cat')]);
        mockFetch(response({
            verdicts: [verdict(0, { suggested_label: 'cat',
                                    verdict: 'loose_boundary' })],
        }));
        const review = new AnnotationCritiqueReview(manager);
        await review.run();

        expect(review.panel.querySelector('[data-critique-action="relabel"]'))
            .toBeNull();
        expect(review.panel.querySelector('[data-critique-action="delete"]'))
            .toBeTruthy();
    });

    test('the model that judged is named', async () => {
        const manager = makeManager([box('cat')]);
        mockFetch(response({ verdicts: [verdict(0)] }));
        const review = new AnnotationCritiqueReview(manager);
        await review.run();

        expect(review.panel.textContent).toContain('test-vlm');
    });
});

describe('acting on a finding', () => {
    async function open(overrides) {
        const manager = makeManager([box('cat'), box('cat')]);
        mockFetch(response(Object.assign({ verdicts: [verdict(0)] }, overrides)));
        const review = new AnnotationCritiqueReview(manager);
        await review.run();
        return { manager, review };
    }

    test('nothing changes until a button is pressed', async () => {
        const { manager } = await open();
        expect(manager.calls).toEqual([]);
    });

    test('relabel applies the suggested label', async () => {
        const { manager, review } = await open();
        click(review.panel, 'relabel');
        expect(manager.calls).toContainEqual(['relabel', 0, 'dog']);
    });

    test('delete removes the annotation', async () => {
        const { manager, review } = await open();
        click(review.panel, 'delete');
        expect(manager.calls).toContainEqual(['delete', 0]);
    });

    test('show selects it on the canvas without changing it', async () => {
        const { manager, review } = await open();
        click(review.panel, 'show');
        expect(manager.calls).toEqual([['focus', 0]]);
    });

    test('keeping it as is changes nothing', async () => {
        const { manager, review } = await open();
        click(review.panel, 'dismiss');
        expect(manager.calls).toEqual([]);
    });

    test('a handled card is disabled so it cannot be applied twice', async () => {
        const { manager, review } = await open();
        const button = click(review.panel, 'relabel');
        expect(button.disabled).toBe(true);
        button.click();
        expect(manager.calls.filter(c => c[0] === 'relabel')).toHaveLength(1);
    });

    test('deleting warns that the remaining indices no longer line up', async () => {
        const { review } = await open();
        click(review.panel, 'delete');
        const notice = review.panel.querySelector('.critique-stale');
        expect(notice.hidden).toBe(false);
        expect(notice.textContent).toContain('renumbered');
    });
});

describe('a canvas that changed since the review ran', () => {
    test('refuses to act, because the index now points at another shape', async () => {
        const manager = makeManager([box('cat'), box('cat')]);
        mockFetch(response({ verdicts: [verdict(0)] }));
        const review = new AnnotationCritiqueReview(manager);
        await review.run();

        // The annotator drew something else while the model was thinking.
        manager._objects.push(box('cat'));

        click(review.panel, 'relabel');
        expect(manager.calls).toEqual([]);
        expect(review.panel.querySelector('.critique-stale').hidden).toBe(false);
    });

    test('dismissing is still allowed, since it touches nothing', async () => {
        const manager = makeManager([box('cat')]);
        mockFetch(response({ verdicts: [verdict(0)] }));
        const review = new AnnotationCritiqueReview(manager);
        await review.run();
        manager._objects.push(box('cat'));

        const button = click(review.panel, 'dismiss');
        expect(button.disabled).toBe(true);
    });
});

describe('possibly-missed objects', () => {
    const missed = {
        label: 'dog', bbox: [0.1, 0.2, 0.3, 0.4], confidence: 0.9,
        rationale: 'A dog on the left.',
    };

    test('are shown with the reason they cannot be accepted', async () => {
        const manager = makeManager([]);
        mockFetch(response({ missed: [missed] }));
        const review = new AnnotationCritiqueReview(manager);
        await review.run();

        expect(review.panel.textContent).toContain('Possibly missed');
        expect(review.panel.querySelector('.critique-note').textContent)
            .toContain('not annotations you can accept');
    });

    test('offer no way to turn a guessed box into an annotation', async () => {
        const manager = makeManager([]);
        mockFetch(response({ missed: [missed] }));
        const review = new AnnotationCritiqueReview(manager);
        await review.run();

        expect(review.panel.querySelector('[data-critique-action="accept"]'))
            .toBeNull();
        expect(review.panel.querySelector('[data-critique-action="add"]'))
            .toBeNull();
    });

    test('the hint overlay carries no annotationData, so nothing serializes it',
        async () => {
            const manager = makeManager([]);
            mockFetch(response({ missed: [missed] }));
            const review = new AnnotationCritiqueReview(manager);
            await review.run();

            click(review.panel, 'hint');
            expect(manager.canvas.add).toHaveBeenCalledTimes(1);
            const added = manager.canvas.add.mock.calls[0][0];
            expect(added.annotationData).toBeUndefined();
            expect(added.selectable).toBe(false);
            expect(added.excludeFromExport).toBe(true);
        });
});

describe('telemetry', () => {
    test('each flagged finding is reported as a suggestion when shown', async () => {
        const seen = [];
        window.recordAnnotationTelemetry = (schema, action, detail) =>
            seen.push([schema, action, detail.meta.src]);

        const manager = makeManager([box('cat'), box('cat')]);
        mockFetch(response({ verdicts: [verdict(0), verdict(1)] }));
        const review = new AnnotationCritiqueReview(manager);
        await review.run();

        expect(seen.filter(e => e[1] === 'ai_suggest')).toHaveLength(2);
        expect(seen[0]).toEqual(['objects', 'ai_suggest', 'critique']);
    });

    test('acting on one is an accept and dismissing is a reject', async () => {
        const seen = [];
        window.recordAnnotationTelemetry = (schema, action) => seen.push(action);

        const manager = makeManager([box('cat'), box('cat')]);
        mockFetch(response({ verdicts: [verdict(0), verdict(1)] }));
        const review = new AnnotationCritiqueReview(manager);
        await review.run();

        review.panel.querySelectorAll('[data-critique-action="relabel"]')[0].click();
        expect(seen).toContain('ai_accept');

        review.panel.querySelectorAll('[data-critique-action="dismiss"]')[1].click();
        expect(seen).toContain('ai_reject');
    });

    test('absent telemetry does not break the queue', async () => {
        const manager = makeManager([box('cat')]);
        mockFetch(response({ verdicts: [verdict(0)] }));
        const review = new AnnotationCritiqueReview(manager);
        await review.run();

        expect(() => click(review.panel, 'relabel')).not.toThrow();
        expect(manager.calls).toContainEqual(['relabel', 0, 'dog']);
    });
});

describe('accessibility fixes from the audit', () => {
    test('the finding list keeps list semantics despite list-style:none', async () => {
        // Safari drops a <ul>'s implicit role when list-style is none, so
        // VoiceOver announces loose text instead of "list, N items".
        const manager = makeManager([box('cat')]);
        mockFetch(response({ verdicts: [verdict(0)] }));
        const review = new AnnotationCritiqueReview(manager);
        await review.run();

        const list = review.panel.querySelector('.critique-list');
        expect(list.getAttribute('role')).toBe('list');
        expect(list.querySelector('.critique-card').getAttribute('role'))
            .toBe('listitem');
    });

    test('acting on a finding does not drop keyboard focus to the body',
        async () => {
            const manager = makeManager([box('cat'), box('cat')]);
            mockFetch(response({ verdicts: [verdict(0), verdict(1)] }));
            const review = new AnnotationCritiqueReview(manager);
            await review.run();

            const first = review.panel.querySelector(
                '[data-critique-action="relabel"]');
            first.focus();
            expect(document.activeElement).toBe(first);
            first.click();

            // In a real browser, disabling the focused button drops focus to
            // <body>; jsdom leaves it on the disabled element instead. Both
            // are broken, and asserting "not body" alone passes in jsdom even
            // with the fix removed — so assert the property that holds in
            // either engine: focus must end up somewhere still usable.
            const active = document.activeElement;
            expect(active).not.toBe(document.body);
            expect(active.disabled).toBeFalsy();
            expect(review.panel.contains(active)).toBe(true);
        });

    test('focus is left alone when the action came from a mouse', async () => {
        const manager = makeManager([box('cat'), box('cat')]);
        mockFetch(response({ verdicts: [verdict(0), verdict(1)] }));
        const review = new AnnotationCritiqueReview(manager);
        await review.run();

        document.body.focus();
        review.panel.querySelector('[data-critique-action="dismiss"]').click();
        expect(document.activeElement).toBe(document.body);
    });

    test('the disclosure names what it controls', async () => {
        const manager = makeManager([box('cat')]);
        mockFetch(response({
            verdicts: [verdict(0, { verdict: 'confirmed', flagged: false })],
        }));
        const review = new AnnotationCritiqueReview(manager);
        await review.run();

        const toggle = review.panel.querySelector('.critique-disclosure');
        const body = review.panel.querySelector('.critique-quiet');
        expect(toggle.getAttribute('aria-controls')).toBe(body.id);
        expect(body.id).toBeTruthy();
    });

    test('per-card results speak through the one shared live region',
        async () => {
            // Up to 24 simultaneous role=status regions is an AT pathology,
            // and a hidden one unhidden in the same tick announces unreliably.
            const manager = makeManager([box('cat'), box('cat')]);
            mockFetch(response({ verdicts: [verdict(0), verdict(1)] }));
            const review = new AnnotationCritiqueReview(manager);
            await review.run();

            const cardResults = review.panel.querySelectorAll(
                '.critique-card-result');
            expect(cardResults.length).toBeGreaterThan(0);
            cardResults.forEach(r => expect(r.getAttribute('role')).toBeNull());

            review.panel.querySelector('[data-critique-action="show"]').click();
            expect(manager.container.querySelector('.critique-announcer')
                .textContent).toContain('Selected on the canvas');
        });

    test('reduced motion suppresses the smooth scroll', async () => {
        const manager = makeManager([box('cat')]);
        mockFetch(response({ verdicts: [verdict(0)] }));
        const review = new AnnotationCritiqueReview(manager);
        await review.run();

        const seen = [];
        review.panel.scrollIntoView = (opts) => seen.push(opts.behavior);

        window.matchMedia = () => ({ matches: true });
        review._reveal();
        window.matchMedia = () => ({ matches: false });
        review._reveal();

        expect(seen).toEqual(['auto', 'smooth']);
    });
});

describe('the panel itself', () => {
    test('announces the result through a live region that predates it', async () => {
        // A live region must exist before its content changes to be announced.
        // Replacing the loading line is a node removal, which announces nothing.
        const manager = makeManager([box('cat')]);
        mockFetch(response({
            verdicts: [verdict(0)],
            summary: Object.assign(response().summary, { reviewed: 1, flagged: 1 }),
        }));
        const review = new AnnotationCritiqueReview(manager);
        await review.run();

        const announcer = manager.container.querySelector('.critique-announcer');
        expect(announcer).toBeTruthy();
        expect(announcer.getAttribute('aria-live')).toBe('polite');
        expect(announcer.textContent).toContain('to look at');
        // Outside the panel body, which is wiped on every render.
        expect(review.panel.contains(announcer)).toBe(false);
    });

    test('an error is announced too', async () => {
        const manager = makeManager([box('cat')]);
        mockFetch({ error: 'No vision model configured' }, false, 503);
        const review = new AnnotationCritiqueReview(manager);
        await review.run();

        expect(manager.container.querySelector('.critique-announcer').textContent)
            .toContain('No vision model configured');
    });

    test('brings itself into view, since it renders below a tall canvas', async () => {
        const manager = makeManager([box('cat')]);
        mockFetch(response({ verdicts: [verdict(0)] }));
        const review = new AnnotationCritiqueReview(manager);
        const scrolled = jest.fn();
        const realCreate = document.createElement.bind(document);
        await review.run();
        review.panel.scrollIntoView = scrolled;
        review._reveal();
        expect(scrolled).toHaveBeenCalled();
    });

    test('is labelled for assistive technology', async () => {
        const manager = makeManager([box('cat')]);
        mockFetch(response({ verdicts: [verdict(0)] }));
        const review = new AnnotationCritiqueReview(manager);
        await review.run();

        expect(review.panel.getAttribute('aria-label')).toBeTruthy();
        expect(review.panel.querySelector('.critique-close')
            .getAttribute('aria-label')).toBeTruthy();
    });

    test('closes without touching the annotations', async () => {
        const manager = makeManager([box('cat')]);
        mockFetch(response({ verdicts: [verdict(0)] }));
        const review = new AnnotationCritiqueReview(manager);
        await review.run();

        click(review.panel, 'close');
        expect(review.panel.isConnected).toBe(false);
        expect(manager.calls).toEqual([]);
    });

    test('is built without innerHTML, so a rationale cannot inject markup',
        async () => {
            const manager = makeManager([box('cat')]);
            mockFetch(response({
                verdicts: [verdict(0, {
                    rationale: '<img src=x onerror="window.__pwned=1">',
                })],
            }));
            const review = new AnnotationCritiqueReview(manager);
            await review.run();

            expect(review.panel.querySelector('img')).toBeNull();
            expect(window.__pwned).toBeUndefined();
            expect(review.panel.textContent).toContain('onerror');
        });

    test('the source never assigns innerHTML', () => {
        expect(SOURCE).not.toMatch(/\.innerHTML\s*=/);
    });
});

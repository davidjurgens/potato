/**
 * Per-class show/hide — the shared module behind image, video, and span.
 *
 * The state is the part worth sharing: it persists per project + schema so a
 * hidden class stays hidden as the annotator moves between items, rather than
 * resetting on every one. Each modality supplies only the function that knows
 * how to hide its own artifacts.
 */

const LabelVisibilityManager = require('../../potato/static/label-visibility.js');

function buildContainer(labels) {
    const container = document.createElement('div');
    labels.forEach(name => {
        const btn = document.createElement('button');
        btn.className = 'label-btn';
        btn.dataset.label = name;
        const dot = document.createElement('span');
        dot.className = 'label-color-dot';
        btn.appendChild(dot);
        container.appendChild(btn);
    });
    document.body.appendChild(container);
    return container;
}

function makeManager(labels, opts = {}) {
    const container = buildContainer(labels);
    const onChange = jest.fn();
    const vis = new LabelVisibilityManager({
        schemaName: opts.schemaName || 'objects',
        projectKey: opts.projectKey || 'proj',
        container,
        onChange,
    });
    return {vis, container, onChange};
}

afterEach(() => {
    document.body.innerHTML = '';
    localStorage.clear();
});

describe('visibility state', () => {
    test('everything is visible to start', () => {
        const {vis} = makeManager(['car', 'road']);
        expect(vis.isVisible('car')).toBe(true);
        expect(vis.hiddenLabels().size).toBe(0);
    });

    test('toggling hides and shows one class', () => {
        const {vis} = makeManager(['car', 'road']);
        vis.toggle('car');
        expect(vis.isVisible('car')).toBe(false);
        expect(vis.isVisible('road')).toBe(true);

        vis.toggle('car');
        expect(vis.isVisible('car')).toBe(true);
    });

    test('solo shows only one class, and repeating it restores the rest', () => {
        // One key both isolates and un-isolates, so the annotator never has to
        // remember which state they are in.
        const {vis} = makeManager(['car', 'road', 'sky']);

        vis.solo('car');
        expect([...vis.hiddenLabels()].sort()).toEqual(['road', 'sky']);

        vis.solo('car');
        expect(vis.hiddenLabels().size).toBe(0);
    });

    test('un-soloing restores what was hidden before, not everything', () => {
        // Un-soloing should undo the solo, not silently discard classes the
        // annotator had deliberately hidden beforehand.
        const {vis} = makeManager(['car', 'road', 'sky']);
        vis.toggle('sky');

        vis.solo('car');
        expect([...vis.hiddenLabels()].sort()).toEqual(['road', 'sky']);

        vis.solo('car');
        expect([...vis.hiddenLabels()]).toEqual(['sky']);
    });

    test('solo on a different class re-isolates rather than restoring', () => {
        const {vis} = makeManager(['car', 'road', 'sky']);
        vis.solo('car');
        vis.solo('road');
        expect([...vis.hiddenLabels()].sort()).toEqual(['car', 'sky']);
    });

    test('showAll clears everything', () => {
        const {vis} = makeManager(['car', 'road']);
        vis.toggle('car');
        vis.toggle('road');
        vis.showAll();
        expect(vis.hiddenLabels().size).toBe(0);
    });
});

describe('persistence', () => {
    test('hidden classes survive a new manager for the same project+schema', () => {
        const first = makeManager(['car', 'road']);
        first.vis.toggle('car');
        document.body.innerHTML = '';

        // A fresh instance is what happens on the next item.
        const second = makeManager(['car', 'road']);
        expect(second.vis.isVisible('car')).toBe(false);
    });

    test('state is scoped per schema', () => {
        const a = makeManager(['car'], {schemaName: 'objects'});
        a.vis.toggle('car');
        document.body.innerHTML = '';

        const b = makeManager(['car'], {schemaName: 'other'});
        expect(b.vis.isVisible('car')).toBe(true);
    });

    test('state is scoped per project', () => {
        const a = makeManager(['car'], {projectKey: 'proj-a'});
        a.vis.toggle('car');
        document.body.innerHTML = '';

        const b = makeManager(['car'], {projectKey: 'proj-b'});
        expect(b.vis.isVisible('car')).toBe(true);
    });

    test('a corrupt stored value starts visible rather than blank', () => {
        // A broken preference must never make annotations look absent.
        localStorage.setItem('potato.labelVisibility.proj.objects', 'not json');
        const {vis} = makeManager(['car']);
        expect(vis.isVisible('car')).toBe(true);
    });
});

describe('the toggle control', () => {
    test('adds one eye per label', () => {
        const {container} = makeManager(['car', 'road']);
        expect(container.querySelectorAll('.label-visibility-toggle')).toHaveLength(2);
    });

    test('clicking the eye does not also arm the label for drawing', () => {
        // Selecting a label and hiding it are different intentions; conflating
        // them would make the common action risky.
        const {container} = makeManager(['car']);
        const btn = container.querySelector('.label-btn');
        const onLabelClick = jest.fn();
        btn.addEventListener('click', onLabelClick);

        container.querySelector('.label-visibility-toggle').click();

        expect(onLabelClick).not.toHaveBeenCalled();
    });

    test('the eye carries its own pressed state and a describing label', () => {
        const {container, vis} = makeManager(['car']);
        const eye = container.querySelector('.label-visibility-toggle');

        expect(eye.getAttribute('aria-pressed')).toBe('false');
        expect(eye.getAttribute('aria-label')).toBe('Hide car annotations');

        vis.toggle('car');
        expect(eye.getAttribute('aria-pressed')).toBe('true');
        expect(eye.getAttribute('aria-label')).toBe('Show car annotations');
    });

    test('the label button reflects hidden state with a class', () => {
        const {container, vis} = makeManager(['car']);
        const btn = container.querySelector('.label-btn');

        vis.toggle('car');
        expect(btn.classList.contains('label-hidden')).toBe(true);

        vis.toggle('car');
        expect(btn.classList.contains('label-hidden')).toBe(false);
    });

    test('the eye is keyboard operable', () => {
        const {container, vis} = makeManager(['car']);
        const eye = container.querySelector('.label-visibility-toggle');
        expect(eye.getAttribute('tabindex')).toBe('0');

        eye.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));
        expect(vis.isVisible('car')).toBe(false);
    });
});

describe('notifying the modality', () => {
    test('onChange fires on construction so the initial state is applied', () => {
        // Restoring hidden classes from storage has to reach the renderer, or
        // the toolbar and the canvas disagree on first paint.
        localStorage.setItem('potato.labelVisibility.proj.objects', '["car"]');
        const {onChange} = makeManager(['car', 'road']);

        expect(onChange).toHaveBeenCalled();
        expect([...onChange.mock.calls[0][0]]).toEqual(['car']);
    });

    test('onChange receives the full hidden set on every change', () => {
        const {vis, onChange} = makeManager(['car', 'road']);
        onChange.mockClear();

        vis.toggle('car');
        vis.toggle('road');

        expect([...onChange.mock.calls.at(-1)[0]].sort()).toEqual(['car', 'road']);
    });

    test('the caller gets a copy, not the live set', () => {
        const {vis, onChange} = makeManager(['car']);
        vis.toggle('car');
        const handed = onChange.mock.calls.at(-1)[0];
        handed.clear();
        expect(vis.isVisible('car')).toBe(false);
    });
});

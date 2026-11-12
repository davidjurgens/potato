/**
 * The magic-wand tool's interaction state.
 *
 * The model is mocked here — deliberately, and with the limits of that stated
 * up front. A mock accepts any tensor shape, which is exactly how an earlier
 * `sam-session.js` shipped emitting two of six required decoder inputs and
 * passed its whole suite. So the CONTRACT is tested against real weights in
 * `tests/unit/test_sam_model_pipeline.py` and across the language boundary in
 * `test_sam_js_python_bridge.py`; what is tested here is the part those cannot
 * see: what happens between clicks.
 */

const { SAMTool } = require('../../potato/static/segmentation/sam-tool.js');

function fakeSession(result) {
    return {
        ready: true,
        segmentCalls: [],
        cleared: 0,
        isReady() { return this.ready; },
        statusMessage() { return 'model missing'; },
        async encodeImage() { return {}; },
        async segment(prompts) {
            this.segmentCalls.push(JSON.parse(JSON.stringify(prompts)));
            return typeof result === 'function' ? result(prompts) : result;
        },
        clearRefinement() { this.cleared++; },
        reset() {},
    };
}

function fakeManager() {
    return {
        activeLabel: 'cat',
        added: [],
        previews: [],
        addAnnotation(obj) { this.added.push(obj); return obj; },
        setSegmentationPreview(p) { this.previews.push(p); },
        // Mirrors the real manager: masks are keyed "label#instance".
        _nextInstanceIndex(label) {
            return this.added.filter(a => a.label === label).length;
        },
    };
}

const MASK = { rle: { counts: [0, 4], size: [2, 2] }, bbox: { x: 0, y: 0, width: 2, height: 2 }, score: 0.9, area: 4 };

describe('prompt accumulation', () => {
    test('a click adds a foreground point', async () => {
        const tool = new SAMTool({ session: fakeSession(MASK), manager: fakeManager() });
        await tool.addPoint(10, 20);
        expect(tool.points).toEqual([[10, 20, 1]]);
    });

    test('shift-click adds a background point', async () => {
        const tool = new SAMTool({ session: fakeSession(MASK), manager: fakeManager() });
        await tool.addPoint(10, 20, true);
        expect(tool.points).toEqual([[10, 20, 0]]);
    });

    test('clicks accumulate so a second refines the first', async () => {
        const session = fakeSession(MASK);
        const tool = new SAMTool({ session, manager: fakeManager() });
        await tool.addPoint(10, 20);
        await tool.addPoint(30, 40, true);
        expect(session.segmentCalls[1].points).toEqual([[10, 20, 1], [30, 40, 0]]);
    });

    test('a tiny drag is treated as a click, not a degenerate box', async () => {
        /**
         * A 2px drag is a click that wobbled. Sending it as a box gives SAM a
         * degenerate prompt and a mask that looks like a random fragment.
         */
        const session = fakeSession(MASK);
        const tool = new SAMTool({ session, manager: fakeManager() });
        await tool.setBox(10, 10, 2, 2);
        expect(tool.box).toBeNull();
        expect(tool.points).toEqual([[10, 10, 1]]);
    });

    test('a real drag becomes a box', async () => {
        const tool = new SAMTool({ session: fakeSession(MASK), manager: fakeManager() });
        await tool.setBox(10, 10, 50, 40);
        expect(tool.box).toEqual([10, 10, 50, 40]);
    });

    test('a box dragged up-left is normalised to positive extents', async () => {
        const tool = new SAMTool({ session: fakeSession(MASK), manager: fakeManager() });
        await tool.setBox(100, 100, -50, -40);
        expect(tool.box).toEqual([50, 60, 50, 40]);
    });
});

describe('undo', () => {
    test('it removes the most recent point', async () => {
        const tool = new SAMTool({ session: fakeSession(MASK), manager: fakeManager() });
        await tool.addPoint(1, 1);
        await tool.addPoint(2, 2);
        await tool.undoPoint();
        expect(tool.points).toEqual([[1, 1, 1]]);
    });

    test('it drops the refinement chain', async () => {
        /**
         * The chain is built from the PREVIOUS mask. Undoing a point while
         * keeping it would refine against a mask that point helped produce, so
         * the undo would not fully undo.
         */
        const session = fakeSession(MASK);
        const tool = new SAMTool({ session, manager: fakeManager() });
        await tool.addPoint(1, 1);
        await tool.addPoint(2, 2);
        const before = session.cleared;
        await tool.undoPoint();
        expect(session.cleared).toBeGreaterThan(before);
    });

    test('undo with only a box clears the box', async () => {
        const tool = new SAMTool({ session: fakeSession(MASK), manager: fakeManager() });
        await tool.setBox(0, 0, 50, 50);
        await tool.undoPoint();
        expect(tool.box).toBeNull();
    });

    test('undo on an empty prompt is harmless', async () => {
        const tool = new SAMTool({ session: fakeSession(MASK), manager: fakeManager() });
        await expect(tool.undoPoint()).resolves.toBeNull();
    });
});

describe('preview and accept', () => {
    test('a successful decode produces a preview, not an annotation', async () => {
        /** The tool that only ever commits is the one people abandon. */
        const manager = fakeManager();
        const tool = new SAMTool({ session: fakeSession(MASK), manager });
        await tool.addPoint(5, 5);
        expect(tool.hasPreview()).toBe(true);
        expect(manager.added).toHaveLength(0);
    });

    test('accept commits through addAnnotation', async () => {
        /**
         * Never builds the object by hand: routing through addAnnotation is
         * what enforces the client coordinate contract on this path too.
         */
        const manager = fakeManager();
        const tool = new SAMTool({ session: fakeSession(MASK), manager });
        await tool.addPoint(5, 5);
        tool.accept('dog');
        expect(manager.added).toHaveLength(1);
        expect(manager.added[0].type).toBe('mask');
        expect(manager.added[0].label).toBe('dog');
        expect(manager.added[0].rle).toEqual(MASK.rle);
    });

    test('the committed mask declares iscrowd 0', async () => {
        /**
         * Masks default to crowd. Without this, a COCO export merges every
         * segmented instance of a class into one region.
         */
        const manager = fakeManager();
        const tool = new SAMTool({ session: fakeSession(MASK), manager });
        await tool.addPoint(5, 5);
        tool.accept('cat');
        expect(manager.added[0].iscrowd).toBe(0);
    });

    test('each accepted mask gets its own instance index', async () => {
        /**
         * Masks are keyed "label#instance". Without a distinct index every
         * accept lands on the bare label key and overwrites the last, so
         * segmenting three cats stored one. Found in a real browser; the
         * mocked session cannot see it, so the fake manager mirrors the
         * real one's allocator.
         */
        const manager = fakeManager();
        const tool = new SAMTool({ session: fakeSession(MASK), manager });
        for (const xy of [[5, 5], [50, 50], [90, 90]]) {
            await tool.addPoint(xy[0], xy[1]);
            tool.accept('cat');
        }
        expect(manager.added.map(a => a.instance)).toEqual([0, 1, 2]);
    });

    test('confidence above 1 is clamped for display', async () => {
        /** iou_predictions is a regression head, not a probability; it
         *  routinely exceeds 1 and "confidence 102%" reads as broken. */
        const messages = [];
        const tool = new SAMTool({
            session: fakeSession({ ...MASK, score: 1.017 }),
            manager: fakeManager(),
            onStatus: (m) => messages.push(m),
        });
        await tool.addPoint(5, 5);
        expect(messages.join(' ')).toContain('confidence 100%');
        expect(messages.join(' ')).not.toContain('102%');
    });

    test('accept clears the prompt so the next click starts fresh', async () => {
        const manager = fakeManager();
        const tool = new SAMTool({ session: fakeSession(MASK), manager });
        await tool.addPoint(5, 5);
        tool.accept();
        expect(tool.points).toEqual([]);
        expect(tool.hasPreview()).toBe(false);
    });

    test('accept with no preview commits nothing', async () => {
        const manager = fakeManager();
        const tool = new SAMTool({ session: fakeSession(MASK), manager });
        expect(tool.accept('cat')).toBeNull();
        expect(manager.added).toHaveLength(0);
    });

    test('it falls back to the manager active label', async () => {
        const manager = fakeManager();
        const tool = new SAMTool({ session: fakeSession(MASK), manager });
        await tool.addPoint(5, 5);
        tool.accept();
        expect(manager.added[0].label).toBe('cat');
    });
});

describe('empty results are reported, not committed', () => {
    const EMPTY = { rle: null, bbox: null, score: 0.1, area: 0 };

    test('a click on nothing leaves no preview', async () => {
        const tool = new SAMTool({ session: fakeSession(EMPTY), manager: fakeManager() });
        await tool.addPoint(5, 5);
        expect(tool.hasPreview()).toBe(false);
    });

    test('it says so rather than failing silently', async () => {
        const messages = [];
        const tool = new SAMTool({
            session: fakeSession(EMPTY),
            manager: fakeManager(),
            onStatus: (m, kind) => messages.push(kind),
        });
        await tool.addPoint(5, 5);
        expect(messages).toContain('empty');
    });

    test('an empty result never becomes an annotation', async () => {
        const manager = fakeManager();
        const tool = new SAMTool({ session: fakeSession(EMPTY), manager });
        await tool.addPoint(5, 5);
        tool.accept('cat');
        expect(manager.added).toHaveLength(0);
    });
});

describe('failures surface the session message', () => {
    test('a decode failure reports an error', async () => {
        const messages = [];
        const session = fakeSession(null);
        const tool = new SAMTool({
            session, manager: fakeManager(),
            onStatus: (m, kind) => messages.push({ m, kind }),
        });
        await tool.addPoint(5, 5);
        expect(messages.some(x => x.kind === 'error')).toBe(true);
        expect(messages.some(x => x.m === 'model missing')).toBe(true);
    });

    test('a failure leaves no stale preview behind', async () => {
        const session = fakeSession(MASK);
        const tool = new SAMTool({ session, manager: fakeManager() });
        await tool.addPoint(5, 5);
        expect(tool.hasPreview()).toBe(true);

        session.segment = async () => null;
        await tool.addPoint(6, 6);
        expect(tool.hasPreview()).toBe(false);
    });
});

describe('preview rendering is delegated', () => {
    test('the manager paints, not the tool', async () => {
        /**
         * A second painter with its own transform maths is how the old
         * segmentation manager drifted out of alignment under zoom.
         */
        const manager = fakeManager();
        const tool = new SAMTool({ session: fakeSession(MASK), manager });
        await tool.addPoint(5, 5);
        const last = manager.previews[manager.previews.length - 1];
        expect(last.rle).toEqual(MASK.rle);
        expect(last.points).toEqual([[5, 5, 1]]);
    });

    test('clearing pushes a null preview so the canvas repaints', () => {
        const manager = fakeManager();
        const tool = new SAMTool({ session: fakeSession(MASK), manager });
        tool.clear();
        expect(manager.previews[manager.previews.length - 1]).toBeNull();
    });
});

describe('item switching', () => {
    test('reset drops the prompt and the encoded key', async () => {
        const tool = new SAMTool({ session: fakeSession(MASK), manager: fakeManager() });
        await tool.addPoint(5, 5);
        tool._encodedKey = 'a.jpg';
        tool.reset();
        expect(tool.points).toEqual([]);
        expect(tool._encodedKey).toBeNull();
        expect(tool.hasPreview()).toBe(false);
    });

    test('prepare re-encodes when the image changes', async () => {
        const session = fakeSession(MASK);
        let encoded = 0;
        session.encodeImage = async () => { encoded++; return {}; };
        const tool = new SAMTool({ session, manager: fakeManager() });
        await tool.prepare('a.jpg', {}, 10, 10);
        await tool.prepare('a.jpg', {}, 10, 10);
        expect(encoded).toBe(1);
        await tool.prepare('b.jpg', {}, 10, 10);
        expect(encoded).toBe(2);
    });

    test('a failed encode reports and does not mark the image ready', async () => {
        const session = fakeSession(MASK);
        session.encodeImage = async () => null;
        const messages = [];
        const tool = new SAMTool({
            session, manager: fakeManager(),
            onStatus: (m, kind) => messages.push(kind),
        });
        const ok = await tool.prepare('a.jpg', {}, 10, 10);
        expect(ok).toBe(false);
        expect(messages).toContain('error');
        expect(tool._encodedKey).toBeNull();
    });
});

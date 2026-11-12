/**
 * Audit 6: the widget-side half of nine defects, pinned.
 *
 * Each block below is one thing an annotator did that the study then recorded
 * wrongly, or a control that did nothing when they used it. They are grouped by
 * the file that owned the defect rather than by feature, because the fix is in
 * the file and that is where a regression would land.
 */

describe('region_caption: min_length is a rule, not decoration', () => {
    require('../../potato/static/region-caption.js');
    const Manager = global.RegionCaptionManager;

    function makeManager(config) {
        document.body.innerHTML = `
            <div class="region-caption-container" data-schema="caps">
              <ol id="region-caption-list-caps"></ol>
              <p id="region-caption-progress-caps"></p>
              <span id="region-caption-announce-caps"></span>
              <input type="hidden" id="input-caps" value="">
            </div>`;
        const container = document.querySelector('.region-caption-container');
        return new Manager(container, Object.assign({ schemaName: 'caps' }, config));
    }

    test('a caption under the floor does not count as described', () => {
        // `min_length: 10` was computed by the schema, shipped to the client
        // and read by nobody: "box" counted and the panel said "All 2 regions
        // described."
        const m = makeManager({ minLength: 10 });
        m.entries = [
            { key: 'a', caption: 'box', region: {} },
            { key: 'b', caption: 'a red bicycle leaning on a wall', region: {} },
        ];
        expect(m.undescribed()).toEqual([0]);
    });

    test('with no floor configured, any non-blank caption counts', () => {
        const m = makeManager({});
        m.entries = [
            { key: 'a', caption: 'box', region: {} },
            { key: 'b', caption: '   ', region: {} },
        ];
        expect(m.undescribed()).toEqual([1]);
    });

    test('the progress line says what the floor is', () => {
        const m = makeManager({ minLength: 10 });
        m.entries = [{ key: 'a', caption: 'box', region: {} }];
        m._renderProgress();
        expect(document.getElementById('region-caption-progress-caps').textContent)
            .toContain('at least 10 characters');
    });
});

describe('tiered_annotation: transcript seeding does not answer for the annotator', () => {
    require('../../potato/static/tiered-annotation.js');
    const Manager = global.TieredAnnotationManager;

    function seed(tierLabels, turns) {
        document.body.innerHTML =
            `<div id="instance-json-data" data-instance-json='${JSON.stringify({
                _transcripts: { segments: { turns: turns } },
            })}'></div>`;
        const m = Object.create(Manager.prototype);
        m.config = {
            transcriptField: 'segments',
            transcriptTier: 'utterance',
            tiers: [{ name: 'utterance', labels: tierLabels }],
        };
        m.annotations = { utterance: [] };
        m._syncAnnotationsToPeaks = () => {};
        m._seedFromTranscript();
        return m.annotations.utterance;
    }

    const TURNS = [
        { turn_id: 't1', start: 0, end: 1, text: 'hello', speaker: 'agent' },
        { turn_id: 't2', start: 1, end: 2, text: 'hi', speaker: 'Caller' },
    ];

    test("a turn's own speaker becomes its label when the tier offers it", () => {
        const seeded = seed(
            [{ name: 'Caller', color: '#111' }, { name: 'agent', color: '#222' }],
            TURNS);
        expect(seeded.map(a => a.label)).toEqual(['agent', 'Caller']);
        // The record must not contradict itself: label and speaker agree.
        seeded.forEach(a => expect(a.label).toBe(a.speaker));
    });

    test('speaker matching ignores case and surrounding space', () => {
        const seeded = seed([{ name: 'Agent' }, { name: 'Caller' }],
                            [{ turn_id: 't1', start: 0, end: 1, speaker: ' AGENT ' }]);
        expect(seeded[0].label).toBe('Agent');
    });

    test('an unmatched speaker is left unlabelled rather than given labels[0]', () => {
        // The defect: every turn was seeded with tier.labels[0], so two
        // utterances whose speaker was "agent" were labelled "Caller" and
        // there was no way to fix it in the UI.
        const seeded = seed([{ name: 'Caller', color: '#111' }], TURNS);
        expect(seeded[0].label).toBe('');
        expect(seeded[1].label).toBe('Caller');
    });
});

describe('image_annotation: a box cannot be stored outside the picture', () => {
    // The rest of the manager needs fabric and a canvas; the clamp does not,
    // so it is lifted out of the file and called directly.
    const src = require('fs').readFileSync(
        require('path').join(__dirname,
            '../../potato/static/image-annotation.js'), 'utf8');
    const body = src.match(/_pointerInImage\(pointer\) \{([\s\S]*?)\n    \}/)[1];
    const clamp = new Function('pointer', body);

    // The reported geometry: an 831x600 canvas holding a 640x420 image,
    // centred, so ~96px of dead margin on each side.
    const ctx = { image: { left: 95.5, top: 90, width: 640, height: 420,
                           scaleX: 1, scaleY: 1 } };

    test('a drag starting in the dead margin is pulled onto the image', () => {
        // Before this, such a drag stored {x: -0.046, y: -0.0007} and the
        // region_caption panel read it back as "Region 1 — at -5%, 0%".
        expect(clamp.call(ctx, { x: 0, y: 0 })).toEqual({ x: 95.5, y: 90 });
    });

    test('a drag running off the far edge stops at the far edge', () => {
        expect(clamp.call(ctx, { x: 900, y: 700 })).toEqual({ x: 735.5, y: 510 });
    });

    test('a pointer already on the image is untouched', () => {
        expect(clamp.call(ctx, { x: 300, y: 200 })).toEqual({ x: 300, y: 200 });
    });

    test('a zoomed image clamps to its scaled bounds, not its natural size', () => {
        const zoomed = { image: { left: 10, top: 10, width: 640, height: 420,
                                  scaleX: 0.5, scaleY: 0.5 } };
        expect(clamp.call(zoomed, { x: 999, y: 999 })).toEqual({ x: 330, y: 220 });
    });

    test('both drag tools run their pointer through it', () => {
        // The clamp only helps if every drag entry point calls it, so pin the
        // call at the top of each of the four.
        ['_startBbox', '_updateBbox', '_startEllipse', '_updateEllipse']
            .forEach((fn) => {
                const at = src.indexOf('\n    ' + fn + '(pointer) {');
                expect(at).toBeGreaterThan(-1);
                expect(src.slice(at, at + 260))
                    .toContain('pointer = this._pointerInImage(pointer)');
            });
    });
});

describe('peaks-driven widgets call APIs this build actually has', () => {
    const fs = require('fs');
    const path = require('path');
    const read = (f) => fs.readFileSync(
        path.join(__dirname, '../../potato/static/', f), 'utf8');
    /* Comments in these files quote the broken calls by name, so the checks
       below run against code only. */
    const code = (f) => read(f)
        .replace(/\/\*[\s\S]*?\*\//g, '')
        .replace(/^\s*\/\/.*$/gm, '');

    test('zoom is expressed in seconds read off the view, never view.getZoom', () => {
        // The bundled build puts getZoom on the zoom CONTROLLER. Calling it on
        // the view threw "view.getZoom is not a function" and the zoom buttons
        // did nothing on both widgets. The controller's own zoomIn/zoomOut are
        // no good either: they step an index the view never updates, so the
        // first press of a fitted timeline is a no-op.
        ['audio-annotation.js', 'video-annotation.js'].forEach((f) => {
            const src = code(f);
            expect(src).not.toMatch(/getZoom/);
            expect(src).not.toMatch(/peaks\.zoom\.zoom(In|Out)\(/);
            expect(src).toContain('_zoomByFactor(0.5)');
            expect(src).toContain('_zoomByFactor(2)');
            // The three public view methods it is allowed to use.
            expect(src).toContain('view.getStartTime()');
            expect(src).toContain('view.getEndTime()');
            expect(src).toContain('view.setZoom({ seconds: next })');
        });
    });

    test('tiered_annotation listens on the peaks instance, not on the views', () => {
        // `zoomview.on(...)` threw, and the throw escaped into _initPeaks's
        // try/catch — so auto-scroll, the initial zoom, both refits and the
        // zoom-range sync were all skipped on every load.
        const src = code('tiered-annotation.js');
        expect(src).not.toMatch(/zoomview\.on\(/);
        expect(src).not.toMatch(/overview\.on\(/);
        ["this.peaks.on('zoomview.dblclick'",
         "this.peaks.on('overview.click'",
         "this.peaks.on('overview.dblclick'",
        ].forEach(s => expect(src).toContain(s));
    });

    test('the bundled peaks build really lacks the old APIs', () => {
        // The claim above is about THIS bundle, so check the bundle.
        const bundle = read('peaks.min.js');
        expect(bundle).toContain('sn.prototype.getZoom');   // the controller
        expect(bundle).not.toContain('rn.prototype.getZoom'); // not the view
        expect(bundle).not.toContain('rn.prototype.on');
    });
});

describe('audio/video annotation declare what is still missing', () => {
    const fs = require('fs');
    const path = require('path');
    const read = (f) => fs.readFileSync(
        path.join(__dirname, '../../potato/static/', f), 'utf8');

    // Exercised through the real method, on a bare object, so the count logic
    // is pinned rather than the text around it.
    function shortfall(managerSrc, segments, minSegments) {
        document.body.innerHTML = `
            <form class="annotation-form" data-schema-name="seg">
              <input type="hidden" id="i" class="annotation-data-input" value="x">
            </form>`;
        const body = managerSrc.match(
            /_declareCompleteness\(\) \{([\s\S]*?)\n    \}/)[1];
        const fn = new Function(body);
        const ctx = {
            inputEl: document.getElementById('i'),
            segments: segments,
            config: { minSegments: minSegments },
        };
        fn.call(ctx);
        return document.querySelector('form')
            .getAttribute('data-incomplete-reason');
    }

    ['audio-annotation.js', 'video-annotation.js'].forEach((file) => {
        test(`${file}: min_segments is enforced, not merely shipped`, () => {
            const src = read(file);
            // The defect: minSegments reached the browser and nothing read it,
            // so one segment satisfied `min_segments: 2`.
            expect(shortfall(src, [{ label: 'a' }], 2))
                .toBe('1 of 2 segments marked');
            expect(shortfall(src, [{ label: 'a' }, { label: 'b' }], 2)).toBeNull();
        });

        test(`${file}: an unlabelled segment is not an answered one`, () => {
            const src = read(file);
            expect(shortfall(src, [{ label: 'a' }, { label: '' }], 0))
                .toBe('1 segment with no label');
        });

        test(`${file}: no min_segments and every segment labelled is complete`, () => {
            const src = read(file);
            expect(shortfall(src, [{ label: 'a' }], 0)).toBeNull();
        });
    });
});

describe('rollout_evaluation reports the real duration', () => {
    const src = require('fs').readFileSync(
        require('path').join(__dirname,
            '../../potato/static/rollout-eval.js'), 'utf8');

    test('_onMetadata re-describes the set once durations are known', () => {
        // _describe ran once with the server payload, whose duration is 0
        // because nothing server-side probes the files, so the sentence read
        // "3 rollouts, 0.00 s." for three six-second clips forever.
        const body = src.match(/_onMetadata\(\) \{([\s\S]*?)\n        \}/)[1];
        expect(body).toContain('this._describe(this.set)');
        // ...and before the spread warning, which deliberately overwrites it.
        expect(body.indexOf('this._describe(this.set)'))
            .toBeLessThan(body.indexOf('Panels differ in length'));
    });
});

describe('multi_document_event stores the per-annotator answer', () => {
    const src = require('fs').readFileSync(
        require('path').join(__dirname,
            '../../potato/static/multi-document-event.js'), 'utf8');

    test('syncHidden stamps data-modified, which is what makes it readable', () => {
        // Without both halves — the annotation-input class from the schema and
        // data-modified from here — syncAnnotationsFromDOM skips the input and
        // instance_id_to_label_to_value stayed {}.
        const body = src.match(/syncHidden\(\) \{([\s\S]*?)\n    \}/)[1];
        expect(body).toContain("setAttribute(\"data-modified\", \"true\")");
        expect(body).toContain('mine.length ? JSON.stringify(mine)');
        // Emptying a document that had memberships must not read as untouched.
        expect(body).toContain('this.hidden.value ? "[]" : ""');
    });
});

describe('a video with no audio track is not an error', () => {
    const src = require('fs').readFileSync(
        require('path').join(__dirname,
            '../../potato/static/video-annotation.js'), 'utf8');

    test('the EncodingError case is logged as a warning, not an error', () => {
        // A clip with no audio track has no waveform to draw, and everything
        // else on the widget works. At console.error it was indistinguishable
        // from the tiered_annotation initialiser genuinely giving up, and an
        // audit spent time telling the two apart.
        const block = src.slice(src.indexOf('const silent = /EncodingError'));
        expect(block.slice(0, 900)).toContain('console.warn');
        expect(block.slice(0, 900)).toContain('No decodable audio track');
    });

    test('a genuine failure is still an error', () => {
        const block = src.slice(src.indexOf('const silent = /EncodingError'));
        expect(block.slice(0, 900)).toContain('console.error');
        expect(block.slice(0, 900)).toContain('Peaks.js failed to');
    });

    test('the test that sorts them apart matches the real message', () => {
        // Lifted out of the file so the regex itself is exercised, not a copy.
        const pattern = new RegExp(
            src.match(/const silent = (\/[^;]+\/i)\.test/)[1]
               .replace(/^\/|\/i$/g, ''), 'i');
        expect(pattern.test('EncodingError: Unable to decode audio data')).toBe(true);
        expect(pattern.test('Unable to decode audio data')).toBe(true);
        expect(pattern.test('TypeError: view.getZoom is not a function')).toBe(false);
        expect(pattern.test('NetworkError when fetching the waveform')).toBe(false);
    });
});

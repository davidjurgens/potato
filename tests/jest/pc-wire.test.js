/**
 * PNT1 parsing and point colouring.
 *
 * The buffers here are built byte by byte in the test rather than produced by
 * the Python writer, so this is a genuine cross-language check of the format:
 * if the two ends disagree about a field order or an offset, one of these
 * fails. `tests/unit/test_pointcloud_readers.py` asserts the same layout from
 * the other side.
 */

const wire = require('../../potato/static/pointcloud/pc-wire.js');

/** Build a PNT1 buffer the way potato/media/pointcloud.py:to_wire does. */
function buildWire(header, positions, colors, intensity, indices) {
    const json = new TextEncoder().encode(JSON.stringify(header));
    const n = header.count;
    const size = 8 + json.length + n * 12
        + (colors ? n * 3 : 0) + (intensity ? n * 4 : 0)
        + (indices ? n * 4 : 0);
    const buf = new ArrayBuffer(size);
    const bytes = new Uint8Array(buf);
    const view = new DataView(buf);

    bytes[0] = 80; bytes[1] = 78; bytes[2] = 84; bytes[3] = 49;   // "PNT1"
    view.setUint32(4, json.length, true);
    bytes.set(json, 8);

    let off = 8 + json.length;
    for (let i = 0; i < positions.length; i++) {
        view.setFloat32(off + i * 4, positions[i], true);
    }
    off += n * 12;
    if (colors) {
        bytes.set(colors, off);
        off += n * 3;
    }
    if (intensity) {
        for (let i = 0; i < intensity.length; i++) {
            view.setFloat32(off + i * 4, intensity[i], true);
        }
        off += n * 4;
    }
    if (indices) {
        for (let i = 0; i < indices.length; i++) {
            view.setUint32(off + i * 4, indices[i], true);
        }
    }
    return buf;
}

function simpleHeader(count, extra) {
    return Object.assign({
        version: 1, count,
        has_colors: false, has_intensity: false,
        source_format: 'kitti_bin', original_count: count, bounds: null,
    }, extra || {});
}

describe('parseWire', () => {
    test('reads positions', () => {
        const buf = buildWire(simpleHeader(2), [1, 2, 3, 4, 5, 6]);
        const parsed = wire.parseWire(buf);
        expect(parsed.count).toBe(2);
        expect(Array.from(parsed.positions)).toEqual([1, 2, 3, 4, 5, 6]);
        expect(parsed.colors).toBeNull();
        expect(parsed.intensity).toBeNull();
    });

    test('reads colors and intensity at the declared offsets', () => {
        // An offset that is one field out still produces a plausible cloud, so
        // the values are chosen to be distinguishable rather than round.
        const buf = buildWire(
            simpleHeader(2, { has_colors: true, has_intensity: true }),
            [1, 2, 3, 4, 5, 6],
            [255, 0, 0, 0, 128, 64],
            [0.25, 0.75]);
        const parsed = wire.parseWire(buf);
        expect(Array.from(parsed.colors)).toEqual([255, 0, 0, 0, 128, 64]);
        expect(Array.from(parsed.intensity)).toEqual([0.25, 0.75]);
    });

    test('positions survive a header length that breaks 4-byte alignment', () => {
        // `new Float32Array(buffer, offset)` throws unless offset % 4 === 0,
        // and the header is JSON of whatever length it happens to be. Padding
        // the source_format shifts the data by one byte at a time.
        for (let pad = 0; pad < 4; pad++) {
            const header = simpleHeader(1, { source_format: 'x'.repeat(pad) });
            const parsed = wire.parseWire(buildWire(header, [1.5, 2.5, 3.5]));
            expect(Array.from(parsed.positions)).toEqual([1.5, 2.5, 3.5]);
        }
    });

    test('a foreign buffer is refused by name', () => {
        const buf = new ArrayBuffer(32);
        new Uint8Array(buf).set([78, 79, 80, 69]);   // "NOPE"
        expect(() => wire.parseWire(buf)).toThrow(/PNT1/);
    });

    test('a truncated buffer is refused rather than read as zero points', () => {
        expect(() => wire.parseWire(new ArrayBuffer(4))).toThrow(/truncated/);
    });

    test('an empty cloud parses to zero points', () => {
        const parsed = wire.parseWire(buildWire(simpleHeader(0), []));
        expect(parsed.count).toBe(0);
        expect(parsed.positions.length).toBe(0);
    });
});

describe('describeCloud', () => {
    test('says when the cloud was decimated, and by how much', () => {
        // An annotator who does not know the cloud was thinned will draw boxes
        // around gaps that are artefacts of the sampling.
        const text = wire.describeCloud(
            { count: 500000, original_count: 2000000 });
        expect(text).toMatch(/500,000/);
        expect(text).toMatch(/2,000,000/);
        expect(text).toMatch(/sampled/);
    });

    test('says nothing about sampling when nothing was dropped', () => {
        const text = wire.describeCloud({ count: 1234, original_count: 1234 });
        expect(text).toBe('1,234 points.');
        expect(text).not.toMatch(/sampled/);
    });

    test('a missing original_count is not read as zero', () => {
        expect(wire.describeCloud({ count: 10 })).toBe('10 points.');
    });
});

describe('colorize', () => {
    const parsed = (count, positions, colors, intensity) => ({
        count,
        positions: new Float32Array(positions),
        colors: colors ? new Uint8Array(colors) : null,
        intensity: intensity ? new Float32Array(intensity) : null,
    });

    test('rgb mode scales bytes to 0..1', () => {
        const out = wire.colorize('rgb', parsed(1, [0, 0, 0], [255, 0, 51]));
        expect(out[0]).toBeCloseTo(1);
        expect(out[1]).toBeCloseTo(0);
        expect(out[2]).toBeCloseTo(0.2);
    });

    test('rgb mode returns null when the file has no colour', () => {
        // Null, not black: the caller has to be able to fall back and say why,
        // rather than render a black cloud that looks like a failed load.
        expect(wire.colorize('rgb', parsed(1, [0, 0, 0]))).toBeNull();
    });

    test('intensity mode returns null when the file has no intensity', () => {
        expect(wire.colorize('intensity', parsed(1, [0, 0, 0]))).toBeNull();
    });

    test('uniform mode paints every point the same', () => {
        const out = wire.colorize('uniform', parsed(2, [0, 0, 0, 1, 1, 1]),
                                  { r: 0.1, g: 0.2, b: 0.3 });
        // Float32 rounding, so closeTo rather than exact equality.
        [0.1, 0.2, 0.3, 0.1, 0.2, 0.3].forEach((want, i) => {
            expect(out[i]).toBeCloseTo(want, 6);
        });
    });

    test('height mode varies with z and nothing else', () => {
        const out = wire.colorize('height', parsed(3,
            [0, 0, 0, 100, 100, 0, 0, 0, 10]));
        // Points 0 and 1 differ only in x and y, so they must match.
        expect([out[0], out[1], out[2]]).toEqual([out[3], out[4], out[5]]);
        expect([out[0], out[1], out[2]]).not.toEqual([out[6], out[7], out[8]]);
    });

    test('height mode is the fallback and never returns null', () => {
        expect(wire.colorize('height', parsed(1, [0, 0, 0]))).not.toBeNull();
        expect(wire.colorize('anything-else', parsed(1, [0, 0, 0]))).not.toBeNull();
    });
});

describe('percentileRange', () => {
    test('one outlier does not flatten the range', () => {
        // The reason for percentiles rather than min/max: a single stray return
        // from a reflective surface compresses everything else into one colour
        // and the cloud renders as a flat sheet.
        const values = new Float32Array(1000);
        for (let i = 0; i < 999; i++) values[i] = i / 999;
        values[999] = 1e6;
        const [lo, hi] = wire.percentileRange(values, 1000);
        expect(hi).toBeLessThan(2);
        expect(lo).toBeLessThan(0.1);
    });

    test('an empty array has a usable range', () => {
        expect(wire.percentileRange(new Float32Array(0), 0)).toEqual([0, 1]);
    });

    test('a constant field does not divide by zero', () => {
        const out = wire.colorize('height', {
            count: 3, positions: new Float32Array([0, 0, 5, 1, 1, 5, 2, 2, 5]),
            colors: null, intensity: null,
        });
        expect(Array.from(out).every(Number.isFinite)).toBe(true);
    });
});

describe('ramp', () => {
    test('is continuous at the stops', () => {
        for (const t of [0, 0.25, 0.5, 0.75, 1]) {
            const before = wire.ramp(Math.max(0, t - 1e-6));
            const after = wire.ramp(Math.min(1, t + 1e-6));
            before.forEach((v, i) => expect(Math.abs(v - after[i])).toBeLessThan(0.01));
        }
    });

    test('stays in gamut', () => {
        for (let t = 0; t <= 1; t += 0.05) {
            wire.ramp(t).forEach((v) => {
                expect(v).toBeGreaterThanOrEqual(0);
                expect(v).toBeLessThanOrEqual(1);
            });
        }
    });

    test('the ends are distinct', () => {
        expect(wire.ramp(0)).not.toEqual(wire.ramp(1));
    });
});

describe('hexToRgb01', () => {
    test.each([
        ['#ff0000', [1, 0, 0]],
        ['#00ff00', [0, 1, 0]],
        ['#0f0', [0, 1, 0]],
        ['#0000ff80', [0, 0, 1]],
    ])('reads %s', (hex, expected) => {
        const rgb = wire.hexToRgb01(hex);
        expect([rgb.r, rgb.g, rgb.b].map((v) => Math.round(v * 100) / 100))
            .toEqual(expected);
    });

    test('matches the image manager rather than inventing a second rule', () => {
        // Shorthand hex silently painted red in the 2D manager for a long time.
        // Repeating that here would produce a cloud whose boxes are the wrong
        // colour while its label buttons are right.
        expect(wire.hexToRgb01('#0f0')).toEqual(wire.hexToRgb01('#00ff00'));
    });

    test('an unreadable colour falls back to red, as 2D does', () => {
        expect(wire.hexToRgb01('rebeccapurple')).toEqual({ r: 1, g: 0, b: 0 });
        expect(wire.hexToRgb01(undefined)).toEqual({ r: 1, g: 0, b: 0 });
    });
});

describe('framing', () => {
    test('uses the header bounds without walking the points', () => {
        const frame = wire.framing({ bounds: [[-10, -10, 0], [10, 10, 4]] }, null);
        expect(frame.center).toEqual([0, 0, 2]);
        expect(frame.radius).toBe(10);
    });

    test('falls back to the points when bounds are absent', () => {
        const frame = wire.framing({}, {
            count: 2, positions: new Float32Array([0, 0, 0, 4, 0, 0]),
        });
        expect(frame.center).toEqual([2, 0, 0]);
        expect(frame.radius).toBe(2);
    });

    test('an empty cloud still gives the camera something to look at', () => {
        // A radius of zero puts the camera inside the origin and the viewer
        // opens on a black screen that looks like a failed load.
        const frame = wire.framing({}, { count: 0, positions: new Float32Array(0) });
        expect(frame.center).toEqual([0, 0, 0]);
        expect(frame.radius).toBeGreaterThan(0);
    });

    test('a single point still gives a usable radius', () => {
        const frame = wire.framing({ bounds: [[5, 5, 5], [5, 5, 5]] }, null);
        expect(frame.center).toEqual([5, 5, 5]);
        expect(frame.radius).toBeGreaterThan(0);
    });
});

describe('the index channel', () => {
    test('reads source indices when the header declares them', () => {
        const buf = buildWire(
            simpleHeader(3, { has_indices: true }),
            [0, 0, 0, 1, 1, 1, 2, 2, 2], null, null, [7, 19, 4000000000]);
        const parsed = wire.parseWire(buf);
        expect(Array.from(parsed.indices)).toEqual([7, 19, 4000000000]);
    });

    test('is positioned after intensity, not before it', () => {
        // Getting this order wrong reads intensity floats as indices and
        // produces plausible-looking garbage rather than an error.
        const buf = buildWire(
            simpleHeader(2, { has_intensity: true, has_indices: true }),
            [0, 0, 0, 1, 1, 1], null, [0.25, 0.5], [11, 22]);
        const parsed = wire.parseWire(buf);
        expect(Array.from(parsed.intensity)).toEqual([0.25, 0.5]);
        expect(Array.from(parsed.indices)).toEqual([11, 22]);
    });

    test('absent indices mean the identity mapping', () => {
        const parsed = wire.parseWire(buildWire(simpleHeader(2), [0, 0, 0, 1, 1, 1]));
        expect(parsed.indices).toBeNull();
        expect(wire.sourceIndex(parsed, 0)).toBe(0);
        expect(wire.sourceIndex(parsed, 1)).toBe(1);
    });

    test('sourceIndex resolves through the channel when present', () => {
        // This is what a segment_3d annotation stores. Falling back to the
        // buffer position when a mapping exists would offset every per-point
        // label by the decimation stride.
        const buf = buildWire(simpleHeader(2, { has_indices: true }),
                              [0, 0, 0, 1, 1, 1], null, null, [500, 1000]);
        const parsed = wire.parseWire(buf);
        expect(wire.sourceIndex(parsed, 0)).toBe(500);
        expect(wire.sourceIndex(parsed, 1)).toBe(1000);
    });
});

describe('a shared colour range', () => {
    function heightCloud(zs) {
        const positions = [];
        zs.forEach((z, i) => positions.push(i, 0, z));
        return wire.parseWire(buildWire(simpleHeader(zs.length), positions));
    }

    test('two buffers with different spreads colour consistently', () => {
        // Under level-of-detail loading each node is coloured on its own. With
        // per-node percentiles a flat node and a tall node would map the SAME
        // height to different colours, showing as a hard seam along the octree
        // boundary that reads as a rendering fault.
        const range = [0, 10];
        const flat = wire.colorize('height', heightCloud([5, 5, 5]), null, range);
        const tall = wire.colorize('height', heightCloud([0, 5, 10]), null, range);
        expect(Array.from(flat.slice(0, 3)))
            .toEqual(Array.from(tall.slice(3, 6)));
    });

    test('without a shared range they disagree', () => {
        // The control: the same two buffers, the same point at height 5,
        // colours differently when each computes its own percentiles. Without
        // this the assertion above could pass on a ramp that ignored its input.
        const flat = wire.colorize('height', heightCloud([5, 5, 5]));
        const tall = wire.colorize('height', heightCloud([0, 5, 10]));
        expect(Array.from(flat.slice(0, 3)))
            .not.toEqual(Array.from(tall.slice(3, 6)));
    });

    test('scalarFor exposes what the ramp reads', () => {
        expect(Array.from(wire.scalarFor('height', heightCloud([1, 2, 3]))))
            .toEqual([1, 2, 3]);
        expect(wire.scalarFor('intensity', heightCloud([1]))).toBeNull();
    });
});

/**
 * Depth viewer: buffer parsing, the cursor lookup, and URL building.
 *
 * The buffers here are built byte by byte rather than produced by the Python
 * writer, so this is a real cross-language check of the DPT1 layout —
 * `tests/unit/test_depth.py` asserts the same layout from the other side.
 */

const DepthViewer = require('../../potato/static/depth-viewer.js');

/** Build a DPT1 buffer the way potato/media/depth.py:to_wire does. */
function buildWire(header, values) {
    const json = new TextEncoder().encode(JSON.stringify(header));
    const buf = new ArrayBuffer(8 + json.length + values.length * 4);
    const bytes = new Uint8Array(buf);
    const view = new DataView(buf);

    bytes[0] = 68; bytes[1] = 80; bytes[2] = 84; bytes[3] = 49;   // "DPT1"
    view.setUint32(4, json.length, true);
    bytes.set(json, 8);
    values.forEach((v, i) => {
        view.setFloat32(8 + json.length + i * 4, v, true);
    });
    return buf;
}

function header(width, height) {
    return { version: 1, width, height, units: 'm', scale: 1.0,
             source_format: 'npy' };
}

describe('parseDepthWire', () => {
    test('reads the grid and its dimensions', () => {
        const parsed = DepthViewer.parseDepthWire(
            buildWire(header(2, 2), [1, 2, 3, 4]));
        expect(parsed.width).toBe(2);
        expect(parsed.height).toBe(2);
        expect(Array.from(parsed.values)).toEqual([1, 2, 3, 4]);
    });

    test('carries NaN through rather than coercing it', () => {
        // A sentinel of 0 would contribute a real number to every statistic
        // and paint a surface across every hole in the sensor's coverage.
        const parsed = DepthViewer.parseDepthWire(
            buildWire(header(2, 1), [NaN, 2]));
        expect(Number.isNaN(parsed.values[0])).toBe(true);
        expect(parsed.values[1]).toBe(2);
    });

    test('rejects a buffer that is not DPT1', () => {
        const buf = buildWire(header(1, 1), [1]);
        new Uint8Array(buf)[0] = 80;    // "P", making it PPT1
        expect(() => DepthViewer.parseDepthWire(buf)).toThrow(/DPT1/);
    });

    test('rejects a truncated buffer', () => {
        expect(() => DepthViewer.parseDepthWire(new ArrayBuffer(4)))
            .toThrow(/truncated/);
    });

    test('survives a header length that leaves the data unaligned', () => {
        // The header is whatever the JSON needs, so the float array can start
        // on an odd offset. `new Float32Array(buffer, offset)` throws a bare
        // RangeError when offset % 4 !== 0.
        const padded = Object.assign(header(1, 1), { pad: 'x' });
        const parsed = DepthViewer.parseDepthWire(buildWire(padded, [7.5]));
        expect(parsed.values[0]).toBeCloseTo(7.5, 5);
    });
});

describe('depthAt', () => {
    const parsed = () => DepthViewer.parseDepthWire(
        // 4x2 grid; row 0 is 1..4, row 1 is 5..8.
        buildWire(header(4, 2), [1, 2, 3, 4, 5, 6, 7, 8]));

    test('maps fractional position to the right cell', () => {
        const p = parsed();
        expect(DepthViewer.depthAt(p, 0.01, 0.01)).toBe(1);
        expect(DepthViewer.depthAt(p, 0.99, 0.01)).toBe(4);
        expect(DepthViewer.depthAt(p, 0.01, 0.99)).toBe(5);
        expect(DepthViewer.depthAt(p, 0.99, 0.99)).toBe(8);
    });

    test('the far edge does not fall off the end', () => {
        // u = 1 floors to exactly `width`, which is one past the last column.
        expect(DepthViewer.depthAt(parsed(), 1, 1)).toBe(8);
    });

    test('outside the image is null, not a clamped edge value', () => {
        // Clamping would report the border pixel's depth for a cursor that is
        // not over the image at all.
        expect(DepthViewer.depthAt(parsed(), -0.1, 0.5)).toBeNull();
        expect(DepthViewer.depthAt(parsed(), 1.1, 0.5)).toBeNull();
    });

    test('a hole reads as no measurement', () => {
        const p = DepthViewer.parseDepthWire(buildWire(header(1, 1), [NaN]));
        expect(DepthViewer.depthAt(p, 0.5, 0.5)).toBeNull();
    });

    test('an empty parse is null rather than a throw', () => {
        expect(DepthViewer.depthAt(null, 0.5, 0.5)).toBeNull();
    });
});

describe('formatDepth', () => {
    test('says so plainly where there is no measurement', () => {
        // Not a blank and not a zero: an annotator who reads a hole as zero
        // metres will treat a gap as a surface.
        expect(DepthViewer.formatDepth(null)).toMatch(/No measurement/);
    });

    test('switches unit below a metre', () => {
        expect(DepthViewer.formatDepth(0.25)).toBe('25.0 cm');
    });

    test('two decimals in the ordinary range', () => {
        expect(DepthViewer.formatDepth(3.14159)).toBe('3.14 m');
    });

    test('drops the decimals at long range where they are noise', () => {
        expect(DepthViewer.formatDepth(1234.5)).toBe('1235 m');
    });
});

describe('buildUrl', () => {
    test('omits parameters that are not set', () => {
        expect(DepthViewer.buildUrl('a/d.npy', { scale: null, colormap: '' }))
            .toBe('/media/depth/a/d.npy');
    });

    test('includes a zero window bound', () => {
        // `if (!value)` would drop `window_min: 0`, which is a legitimate near
        // plane and the one an annotator sets first.
        expect(DepthViewer.buildUrl('d.npy', { window_min: 0 }))
            .toBe('/media/depth/d.npy?window_min=0');
    });

    test('renders a true flag as 1 and drops a false one', () => {
        expect(DepthViewer.buildUrl('d.npy', { invert: true }))
            .toBe('/media/depth/d.npy?invert=1');
        expect(DepthViewer.buildUrl('d.npy', { invert: false }))
            .toBe('/media/depth/d.npy');
    });

    test('escapes values', () => {
        expect(DepthViewer.buildUrl('d.npy', { colormap: 'a b' }))
            .toBe('/media/depth/d.npy?colormap=a%20b');
    });
});

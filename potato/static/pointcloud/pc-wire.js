/**
 * PNT1 wire format and point colouring — the parts with no three.js in them.
 *
 * Split out for the same reason `sam-preprocess.js` is separate from
 * `sam-session.js`: this is where the arithmetic that can be silently wrong
 * lives, and it can only be tested if it does not need a WebGL context. jsdom
 * has no WebGL, so anything touching three.js is untestable in the Jest suite
 * and has to be verified in a real browser instead. Keeping the two apart means
 * the maths is covered by fast tests and only the rendering needs a browser.
 *
 * The format is produced by `potato/media/pointcloud.py`; see `to_wire` there.
 * Layout, all little-endian:
 *
 *     "PNT1"        4 bytes
 *     header_len    uint32
 *     header        header_len bytes of UTF-8 JSON
 *     positions     float32 * 3N   (x, y, z interleaved)
 *     colors        uint8   * 3N   (optional)
 *     intensity     float32 * N    (optional)
 *     indices       uint32  * N    (optional, source-file index per point)
 */
(function (root) {
    'use strict';

    const MAGIC = 'PNT1';

    /**
     * Parse a PNT1 buffer into typed-array views.
     *
     * The arrays are **views onto the original buffer**, not copies, so a
     * multi-million-point cloud is not duplicated in memory on the way to the
     * GPU. That is the whole reason the server interleaves xyz: a three.js
     * BufferGeometry position attribute takes this array as-is.
     *
     * `positions` is byte-aligned by construction — the header length is
     * whatever the JSON needs, so the float32 array can start on an odd offset.
     * When it does, the data is copied into an aligned array rather than
     * throwing, because `new Float32Array(buffer, offset)` requires offset % 4
     * to be zero and the failure is otherwise a bare RangeError.
     */
    function parseWire(buffer) {
        const bytes = new Uint8Array(buffer);
        if (bytes.length < 8) throw new Error('point cloud buffer is truncated');

        const magic = String.fromCharCode(bytes[0], bytes[1], bytes[2], bytes[3]);
        if (magic !== MAGIC) {
            throw new Error(
                `expected a ${MAGIC} point cloud buffer, got "${magic}"`);
        }

        const view = new DataView(buffer);
        const headerLen = view.getUint32(4, true);
        const headerText = new TextDecoder('utf-8').decode(
            bytes.subarray(8, 8 + headerLen));
        const header = JSON.parse(headerText);

        const count = header.count | 0;
        let offset = 8 + headerLen;

        const positions = readFloat32(buffer, offset, count * 3);
        offset += count * 12;

        let colors = null;
        if (header.has_colors) {
            colors = new Uint8Array(buffer, offset, count * 3);
            offset += count * 3;
        }

        let intensity = null;
        if (header.has_intensity) {
            intensity = readFloat32(buffer, offset, count);
            offset += count * 4;
        }

        // Source-file index per point. Absent means the identity mapping — see
        // the "why there is an index channel" note in the Python module. This
        // is what a `segment_3d` annotation stores, so that a per-point label
        // still means the same points after the decimation cap changes or the
        // viewer switches to level-of-detail loading.
        let indices = null;
        if (header.has_indices) {
            indices = readUint32(buffer, offset, count);
        }

        return { header, count, positions, colors, intensity, indices };
    }

    /**
     * The source index of the `i`-th point of a parsed buffer.
     *
     * One function rather than `parsed.indices ? parsed.indices[i] : i` spelled
     * out at every call site, because getting that fallback wrong produces
     * annotations that are off by a stride and look plausible.
     */
    function sourceIndex(parsed, i) {
        if (!parsed) return i;
        return parsed.indices ? parsed.indices[i] : i;
    }

    /** A Float32Array view, copying only when the offset is not 4-aligned. */
    function readFloat32(buffer, offset, length) {
        if (length <= 0) return new Float32Array(0);
        if (offset % 4 === 0) return new Float32Array(buffer, offset, length);
        const copy = new Uint8Array(length * 4);
        copy.set(new Uint8Array(buffer, offset, length * 4));
        return new Float32Array(copy.buffer);
    }

    /** As `readFloat32`, for the uint32 index channel. */
    function readUint32(buffer, offset, length) {
        if (length <= 0) return new Uint32Array(0);
        if (offset % 4 === 0) return new Uint32Array(buffer, offset, length);
        const copy = new Uint8Array(length * 4);
        copy.set(new Uint8Array(buffer, offset, length * 4));
        return new Uint32Array(copy.buffer);
    }

    /**
     * What the viewer tells the annotator about the cloud it is showing.
     *
     * A decimated cloud presented without saying so is a cloud the annotator
     * believes is complete — and they will draw boxes around gaps that are
     * artefacts of the decimation rather than of the scene.
     */
    function describeCloud(header) {
        const shown = header.count | 0;
        const total = (header.original_count | 0) || shown;
        const points = shown.toLocaleString();
        if (total > shown) {
            return `Showing ${points} of ${total.toLocaleString()} points ` +
                   `(evenly sampled to keep the viewer responsive).`;
        }
        return `${points} points.`;
    }

    /**
     * Per-point RGB in [0, 1], as a Float32Array of 3N, for a colour mode.
     *
     * Returns null when the mode cannot be satisfied — no RGB in the file for
     * "rgb", no intensity for "intensity" — so the caller can fall back and say
     * why, instead of rendering a uniformly black cloud that looks like a
     * failed load.
     *
     * `range` pins the [lo, hi] the ramp normalizes against. Under
     * level-of-detail loading each node is coloured separately, and letting
     * every node compute its own percentiles would give neighbouring nodes
     * different colour scales — visible as hard seams along octree boundaries
     * that read as a rendering fault rather than as an artefact of the scale.
     * The caller derives one range from the root node, which is itself a
     * uniform sample of the whole scene, and passes it to every node.
     */
    function colorize(mode, parsed, uniform, range) {
        const { count, positions, colors, intensity } = parsed;
        const out = new Float32Array(count * 3);

        if (mode === 'rgb') {
            if (!colors) return null;
            for (let i = 0; i < count * 3; i++) out[i] = colors[i] / 255;
            return out;
        }

        if (mode === 'uniform') {
            const rgb = uniform || { r: 0.8, g: 0.8, b: 0.85 };
            for (let i = 0; i < count; i++) {
                out[i * 3] = rgb.r;
                out[i * 3 + 1] = rgb.g;
                out[i * 3 + 2] = rgb.b;
            }
            return out;
        }

        const values = scalarFor(mode, parsed);
        if (!values) return null;
        return rampFrom(values, count, out, range);
    }

    /**
     * The scalar a colour mode ramps over, or null when the data is absent.
     *
     * Exposed so a caller can compute a shared percentile range before
     * colouring anything.
     */
    function scalarFor(mode, parsed) {
        const { count, positions, intensity } = parsed;
        if (mode === 'intensity') return intensity || null;
        // height: the default, and the one that always works. Z is up in every
        // format we read.
        const heights = new Float32Array(count);
        for (let i = 0; i < count; i++) heights[i] = positions[i * 3 + 2];
        return heights;
    }

    /**
     * Map a scalar per point through a blue-green-yellow-red ramp.
     *
     * Normalized against the 2nd and 98th percentile rather than min/max: a
     * single stray return from a reflective surface, or one point at the
     * sensor origin, otherwise compresses the entire useful range into one
     * colour and the cloud renders as a flat sheet.
     */
    function rampFrom(values, count, out, range) {
        const [lo, hi] = (range && range.length === 2)
            ? range : percentileRange(values, count);
        const span = hi - lo || 1;
        for (let i = 0; i < count; i++) {
            const t = Math.min(1, Math.max(0, (values[i] - lo) / span));
            const rgb = ramp(t);
            out[i * 3] = rgb[0];
            out[i * 3 + 1] = rgb[1];
            out[i * 3 + 2] = rgb[2];
        }
        return out;
    }

    /** [2nd, 98th] percentile of a scalar array. */
    function percentileRange(values, count) {
        if (count === 0) return [0, 1];
        // Sampled for large clouds: sorting two million floats to pick two
        // percentiles costs more than the render it is preparing for, and the
        // estimate from a stride sample is indistinguishable at this precision.
        const stride = Math.max(1, Math.floor(count / 20000));
        const sample = [];
        for (let i = 0; i < count; i += stride) sample.push(values[i]);
        sample.sort((a, b) => a - b);
        const at = (q) => sample[Math.min(sample.length - 1,
                                          Math.floor(q * (sample.length - 1)))];
        return [at(0.02), at(0.98)];
    }

    /** Blue -> cyan -> green -> yellow -> red, t in [0, 1]. */
    function ramp(t) {
        const stops = [
            [0.0, [0.05, 0.10, 0.55]],
            [0.25, [0.00, 0.65, 0.75]],
            [0.50, [0.10, 0.75, 0.25]],
            [0.75, [0.95, 0.85, 0.10]],
            [1.0, [0.85, 0.15, 0.10]],
        ];
        for (let i = 1; i < stops.length; i++) {
            if (t <= stops[i][0]) {
                const [t0, c0] = stops[i - 1];
                const [t1, c1] = stops[i];
                const f = (t - t0) / (t1 - t0 || 1);
                return [c0[0] + (c1[0] - c0[0]) * f,
                        c0[1] + (c1[1] - c0[1]) * f,
                        c0[2] + (c1[2] - c0[2]) * f];
            }
        }
        return stops[stops.length - 1][1];
    }

    /** {r, g, b} in [0, 1] from a hex colour, mirroring the image manager's. */
    function hexToRgb01(hex) {
        const text = typeof hex === 'string' ? hex.trim() : '';
        const m = /^#?([a-f\d]{3}|[a-f\d]{6}|[a-f\d]{8})$/i.exec(text);
        if (!m) return { r: 1, g: 0, b: 0 };
        const body = m[1];
        const pick = body.length === 3
            ? [body[0] + body[0], body[1] + body[1], body[2] + body[2]]
            : [body.slice(0, 2), body.slice(2, 4), body.slice(4, 6)];
        return {
            r: parseInt(pick[0], 16) / 255,
            g: parseInt(pick[1], 16) / 255,
            b: parseInt(pick[2], 16) / 255,
        };
    }

    /**
     * The centre and radius of a cloud, for framing the camera on load.
     *
     * Uses the header's bounds when present — the server already walked every
     * point, so recomputing here would be a second full pass for the same
     * answer.
     */
    function framing(header, parsed) {
        let bounds = header.bounds;
        if (!bounds) {
            if (!parsed || parsed.count === 0) {
                return { center: [0, 0, 0], radius: 1 };
            }
            const lo = [Infinity, Infinity, Infinity];
            const hi = [-Infinity, -Infinity, -Infinity];
            for (let i = 0; i < parsed.count; i++) {
                for (let a = 0; a < 3; a++) {
                    const v = parsed.positions[i * 3 + a];
                    if (v < lo[a]) lo[a] = v;
                    if (v > hi[a]) hi[a] = v;
                }
            }
            bounds = [lo, hi];
        }
        const [lo, hi] = bounds;
        const center = [0, 1, 2].map((a) => (lo[a] + hi[a]) / 2);
        const radius = Math.max(
            0.5, Math.max(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]) / 2);
        return { center, radius };
    }

    const api = {
        MAGIC, parseWire, describeCloud, colorize, scalarFor, ramp,
        percentileRange, hexToRgb01, framing, sourceIndex,
    };

    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    if (root) root.PointCloudWire = api;
})(typeof window !== 'undefined' ? window
    : (typeof globalThis !== 'undefined' ? globalThis : null));

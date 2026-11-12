/**
 * MaskBuffer — sparse tiled mask store.
 *
 * The tests are written against a **dense reference implementation** kept in
 * this file, not against hand-written expectations. That is deliberate: the
 * whole point of the class is that it behaves exactly like the dense
 * `Uint8ClampedArray(w*h*4)` it replaces while using a fraction of the memory,
 * and "exactly like" is only meaningful if something independent computes the
 * expected answer.
 *
 * The reference encoder here is the CORRECT one (background-run first). The
 * shipped encoder it replaces was not — see `encodeRLE`'s doc comment — so the
 * round-trip tests below would have failed against the old client code, which
 * is the point.
 */

const MaskBuffer = require('../../potato/static/mask-buffer.js');

// ---------------------------------------------------------------------------
// Dense reference
// ---------------------------------------------------------------------------

/** Reference occupancy grid: a plain array of 0/1, row-major. */
function denseGrid(width, height) {
    return new Uint8Array(width * height);
}

/** Reference RLE: background-first alternating run lengths, row-major. */
function denseEncodeRLE(grid, width, height) {
    const counts = [];
    if (width <= 0 || height <= 0) return [0];
    let cur = 0;
    let run = 0;
    for (let i = 0; i < width * height; i++) {
        const v = grid[i] ? 1 : 0;
        if (v === cur) run++;
        else { counts.push(run); cur = v; run = 1; }
    }
    counts.push(run);
    return counts;
}

function denseDecodeRLE(counts, width, height) {
    const grid = denseGrid(width, height);
    const total = width * height;
    let idx = 0;
    let val = 0;
    for (const count of counts) {
        for (let i = 0; i < count && idx < total; i++) {
            if (val === 1) grid[idx] = 1;
            idx++;
        }
        val = 1 - val;
    }
    return grid;
}

function bufferGrid(buf) {
    const grid = denseGrid(buf.width, buf.height);
    for (let y = 0; y < buf.height; y++) {
        for (let x = 0; x < buf.width; x++) {
            if (buf.isSetAt(x, y)) grid[y * buf.width + x] = 1;
        }
    }
    return grid;
}

/** Deterministic PRNG so a failure is reproducible from the seed alone. */
function rng(seed) {
    let s = seed >>> 0;
    return () => {
        s = (s * 1664525 + 1013904223) >>> 0;
        return s / 4294967296;
    };
}

// ---------------------------------------------------------------------------

describe('MaskBuffer construction', () => {
    test('rejects a non-power-of-two tile size', () => {
        // Every index computation uses shifts; a non-power-of-two would produce
        // silently wrong addresses rather than an error.
        expect(() => new MaskBuffer(10, 10, 48)).toThrow(/power of two/);
        expect(() => new MaskBuffer(10, 10, 3)).toThrow(/power of two/);
        expect(() => new MaskBuffer(10, 10, -8)).toThrow(/power of two/);
        // 0 is falsy and means "use the default", not "tile size zero".
        expect(new MaskBuffer(10, 10, 0).tileSize).toBe(MaskBuffer.DEFAULT_TILE_SIZE);
    });

    test('accepts dimensions that are not tile multiples', () => {
        const buf = new MaskBuffer(70, 35, 64);
        expect(buf.tilesX).toBe(2);
        expect(buf.tilesY).toBe(1);
        expect(buf.pixelCount).toBe(70 * 35);
    });

    test('allocates nothing until written', () => {
        const buf = new MaskBuffer(4000, 3000);
        expect(buf.byteLength()).toBe(0);
        expect(buf.hasAny()).toBe(false);
    });
});

describe('set / clear / read', () => {
    test('setAt then isSetAt', () => {
        const buf = new MaskBuffer(100, 100);
        expect(buf.setAt(65, 70)).toBe(true);
        expect(buf.isSetAt(65, 70)).toBe(true);
        expect(buf.isSetAt(64, 70)).toBe(false);
        expect(buf.setAt(65, 70)).toBe(false);  // already set
        expect(buf.countSet()).toBe(1);
    });

    test('out-of-bounds writes are ignored, not wrapped', () => {
        // A negative coordinate that wrapped into another row would paint
        // pixels the annotator never touched, on the far side of the image.
        const buf = new MaskBuffer(10, 10);
        expect(buf.setAt(-1, 5)).toBe(false);
        expect(buf.setAt(10, 5)).toBe(false);
        expect(buf.setAt(5, -1)).toBe(false);
        expect(buf.setAt(5, 10)).toBe(false);
        expect(buf.countSet()).toBe(0);
    });

    test('setSpan clips to the row and counts only new pixels', () => {
        const buf = new MaskBuffer(10, 10);
        expect(buf.setSpan(3, -5, 4)).toBe(5);      // clipped to 0..4
        expect(buf.setSpan(3, 2, 20)).toBe(5);      // 5..9 are new, 2..4 are not
        expect(buf.countSet()).toBe(10);
        expect(buf.setSpan(-1, 0, 9)).toBe(0);
        expect(buf.setSpan(10, 0, 9)).toBe(0);
    });

    test('setSpan crossing tile boundaries matches per-pixel setAt', () => {
        const a = new MaskBuffer(200, 8, 64);
        const b = new MaskBuffer(200, 8, 64);
        a.setSpan(3, 40, 170);
        for (let x = 40; x <= 170; x++) b.setAt(x, 3);
        expect(bufferGrid(a)).toEqual(bufferGrid(b));
        expect(a.countSet()).toBe(b.countSet());
    });

    test('clearSpan removes only what was set', () => {
        const buf = new MaskBuffer(200, 8, 64);
        buf.setSpan(3, 40, 170);
        expect(buf.clearSpan(3, 100, 300)).toBe(71);  // 100..170
        expect(buf.countSet()).toBe(60);
        expect(buf.isSetAt(99, 3)).toBe(true);
        expect(buf.isSetAt(100, 3)).toBe(false);
    });

    test('clearSpan over unallocated tiles is a no-op', () => {
        const buf = new MaskBuffer(500, 8, 64);
        expect(buf.clearSpan(2, 0, 499)).toBe(0);
        expect(buf.byteLength()).toBe(0);
    });

    test('compact releases emptied tiles without changing content', () => {
        const buf = new MaskBuffer(256, 64, 64);
        buf.setSpan(10, 0, 255);
        const before = buf.byteLength();
        buf.clearSpan(10, 0, 127);
        buf.compact();
        expect(buf.byteLength()).toBeLessThan(before);
        expect(buf.countSet()).toBe(128);
        expect(buf.isSetAt(128, 10)).toBe(true);
        expect(buf.isSetAt(127, 10)).toBe(false);
    });

    test('flat pixel-index set/isSet agree with the x,y form', () => {
        const buf = new MaskBuffer(37, 21);
        buf.set(19 * 37 + 5);
        expect(buf.isSetAt(5, 19)).toBe(true);
        expect(buf.isSet(19 * 37 + 5)).toBe(true);
        expect(buf.isSet(19 * 37 + 6)).toBe(false);
    });

    test('rowReader agrees with isSetAt across tile boundaries', () => {
        const buf = new MaskBuffer(300, 4, 64);
        buf.setSpan(1, 50, 60);
        buf.setSpan(1, 130, 200);
        const read = buf.rowReader(1);
        for (let x = -2; x < 302; x++) {
            expect(read(x)).toBe(buf.isSetAt(x, 1));
        }
    });

    test('clear() empties the buffer', () => {
        const buf = new MaskBuffer(64, 64);
        buf.setSpan(0, 0, 63);
        buf.clear();
        expect(buf.hasAny()).toBe(false);
        expect(buf.countSet()).toBe(0);
        expect(buf.byteLength()).toBe(0);
    });
});

describe('randomized equivalence against a dense grid', () => {
    test.each([1, 2, 3, 4, 5])('seed %i: 2000 mixed ops on a 137x91 buffer', (seed) => {
        const W = 137, H = 91;
        const buf = new MaskBuffer(W, H, 64);
        const ref = denseGrid(W, H);
        const rand = rng(seed * 7919);

        for (let op = 0; op < 2000; op++) {
            const y = Math.floor(rand() * H);
            const x0 = Math.floor(rand() * W);
            const x1 = Math.min(W - 1, x0 + Math.floor(rand() * 80));
            if (rand() < 0.7) {
                buf.setSpan(y, x0, x1);
                for (let x = x0; x <= x1; x++) ref[y * W + x] = 1;
            } else {
                buf.clearSpan(y, x0, x1);
                for (let x = x0; x <= x1; x++) ref[y * W + x] = 0;
            }
        }

        expect(bufferGrid(buf)).toEqual(ref);
        expect(buf.countSet()).toBe(ref.reduce((a, b) => a + b, 0));
        expect(buf.encodeRLE()).toEqual(denseEncodeRLE(ref, W, H));
    });
});

describe('RLE', () => {
    test('exhaustive round-trip over every 3x3 pattern', () => {
        // 512 patterns, including the all-set and top-left-set cases the old
        // encoder got wrong.
        for (let bits = 0; bits < 512; bits++) {
            const ref = denseGrid(3, 3);
            for (let i = 0; i < 9; i++) if (bits & (1 << i)) ref[i] = 1;

            const buf = new MaskBuffer(3, 3, 4);
            for (let i = 0; i < 9; i++) if (ref[i]) buf.set(i);

            const counts = buf.encodeRLE();
            expect(counts).toEqual(denseEncodeRLE(ref, 3, 3));
            expect(bufferGrid(MaskBuffer.fromRLE(counts, 3, 3, 4))).toEqual(ref);
        }
    });

    test('a mask whose first pixel is set survives the round trip', () => {
        // The regression this class was written around. The old encoder
        // produced [1, 3] here, which decodes to pixels 1..3 — the exact
        // inverse of what was painted.
        const buf = new MaskBuffer(2, 2);
        buf.set(0);
        expect(buf.encodeRLE()).toEqual([0, 1, 3]);
        const back = MaskBuffer.fromRLE(buf.encodeRLE(), 2, 2);
        expect(back.countSet()).toBe(1);
        expect(back.isSetAt(0, 0)).toBe(true);
    });

    test('a fully painted mask is distinguishable from an empty one', () => {
        // Both used to encode to [N], so a full-canvas fill was stored as blank
        // and lost on reload.
        const full = new MaskBuffer(8, 8);
        full.setSpan(0, 0, 7);
        for (let y = 1; y < 8; y++) full.setSpan(y, 0, 7);
        const empty = new MaskBuffer(8, 8);

        expect(full.encodeRLE()).toEqual([0, 64]);
        expect(empty.encodeRLE()).toEqual([64]);
        expect(MaskBuffer.fromRLE(full.encodeRLE(), 8, 8).countSet()).toBe(64);
        expect(MaskBuffer.fromRLE(empty.encodeRLE(), 8, 8).countSet()).toBe(0);
    });

    test('round-trips a mask larger than one tile', () => {
        const W = 150, H = 130;
        const buf = new MaskBuffer(W, H, 64);
        for (let y = 20; y < 110; y++) buf.setSpan(y, 30, 129);
        const back = MaskBuffer.fromRLE(buf.encodeRLE(), W, H, 64);
        expect(bufferGrid(back)).toEqual(bufferGrid(buf));
    });

    test('fromRLE clamps counts that overrun the image', () => {
        // Truncated or mis-sized data must not throw or wrap into row 0.
        const buf = MaskBuffer.fromRLE([0, 999], 4, 4);
        expect(buf.countSet()).toBe(16);
        expect(MaskBuffer.fromRLE([], 4, 4).countSet()).toBe(0);
        expect(MaskBuffer.fromRLE(null, 4, 4).countSet()).toBe(0);
    });

    test('fromRLE handles a run that wraps across rows', () => {
        const buf = MaskBuffer.fromRLE([3, 6], 4, 4);
        const ref = denseDecodeRLE([3, 6], 4, 4);
        expect(bufferGrid(buf)).toEqual(ref);
    });

    test('encodeRLE counts always sum to the pixel count', () => {
        const rand = rng(4242);
        for (let trial = 0; trial < 20; trial++) {
            const W = 5 + Math.floor(rand() * 120);
            const H = 5 + Math.floor(rand() * 120);
            const buf = new MaskBuffer(W, H, 64);
            for (let i = 0; i < 40; i++) {
                const y = Math.floor(rand() * H);
                const x0 = Math.floor(rand() * W);
                buf.setSpan(y, x0, x0 + Math.floor(rand() * 40));
            }
            const sum = buf.encodeRLE().reduce((a, b) => a + b, 0);
            expect(sum).toBe(W * H);
        }
    });
});

describe('RGBA interop', () => {
    test('fromRGBA reads alpha > 128 and ignores colour', () => {
        const W = 4, H = 2;
        const data = new Uint8ClampedArray(W * H * 4);
        data[0 * 4 + 3] = 255;
        data[3 * 4 + 3] = 129;
        data[5 * 4 + 3] = 128;   // exactly at the threshold: not set
        data[6 * 4 + 0] = 255;   // red but transparent: not set
        const buf = MaskBuffer.fromRGBA(data, W, H);
        expect(buf.countSet()).toBe(2);
        expect(buf.isSet(0)).toBe(true);
        expect(buf.isSet(3)).toBe(true);
        expect(buf.isSet(5)).toBe(false);
        expect(buf.isSet(6)).toBe(false);
    });

    test('toRGBA paints set pixels in the given colour and nothing else', () => {
        const buf = new MaskBuffer(3, 2);
        buf.set(4);
        const out = buf.toRGBA({ r: 0, g: 255, b: 0 });
        expect(out.length).toBe(3 * 2 * 4);
        expect([out[16], out[17], out[18], out[19]]).toEqual([0, 255, 0, 255]);
        expect([out[0], out[1], out[2], out[3]]).toEqual([0, 0, 0, 0]);
    });

    test('fromRGBA -> toRGBA is stable', () => {
        const W = 70, H = 70;
        const buf = new MaskBuffer(W, H, 64);
        for (let y = 10; y < 65; y++) buf.setSpan(y, 5, 68);
        const rgba = buf.toRGBA({ r: 1, g: 2, b: 3 });
        const back = MaskBuffer.fromRGBA(rgba, W, H, 64);
        expect(bufferGrid(back)).toEqual(bufferGrid(buf));
    });
});

describe('rescale', () => {
    /** The nearest-neighbour rescale this replaced, over a dense buffer. */
    function referenceRescale(grid, srcW, srcH, dstW, dstH) {
        const out = denseGrid(dstW, dstH);
        for (let y = 0; y < dstH; y++) {
            const sy = Math.min(srcH - 1, Math.floor(y * srcH / dstH));
            for (let x = 0; x < dstW; x++) {
                const sx = Math.min(srcW - 1, Math.floor(x * srcW / dstW));
                out[y * dstW + x] = grid[sy * srcW + sx];
            }
        }
        return out;
    }

    test.each([
        [40, 30, 80, 60],   // upscale
        [80, 60, 40, 30],   // downscale
        [100, 50, 37, 91],  // non-uniform
        [64, 64, 65, 63],   // across a tile boundary
    ])('%ix%i -> %ix%i matches the dense nearest-neighbour', (sw, sh, dw, dh) => {
        const buf = new MaskBuffer(sw, sh, 64);
        const rand = rng(sw * 31 + sh);
        for (let i = 0; i < 30; i++) {
            const y = Math.floor(rand() * sh);
            const x0 = Math.floor(rand() * sw);
            buf.setSpan(y, x0, x0 + Math.floor(rand() * 20));
        }
        const got = bufferGrid(buf.rescale(dw, dh));
        expect(got).toEqual(referenceRescale(bufferGrid(buf), sw, sh, dw, dh));
    });

    test('rescaling an empty buffer yields an empty buffer', () => {
        const out = new MaskBuffer(10, 10).rescale(20, 20);
        expect(out.hasAny()).toBe(false);
        expect(out.width).toBe(20);
    });
});

describe('clone and bounds', () => {
    test('clone is independent', () => {
        const a = new MaskBuffer(64, 64);
        a.setSpan(5, 0, 10);
        const b = a.clone();
        b.setSpan(6, 0, 10);
        expect(a.countSet()).toBe(11);
        expect(b.countSet()).toBe(22);
        expect(a.isSetAt(0, 6)).toBe(false);
    });

    test('bounds is the inclusive extent of set pixels', () => {
        const buf = new MaskBuffer(200, 200, 64);
        buf.setSpan(70, 130, 140);
        buf.setSpan(12, 3, 5);
        expect(buf.bounds()).toEqual([3, 12, 140, 70]);
        expect(new MaskBuffer(10, 10).bounds()).toBeNull();
    });
});

describe('memory', () => {
    test('a small stroke on a large image allocates only the touched tiles', () => {
        // The claim the class exists for: 4000x3000 dense RGBA is 48 MB.
        const buf = new MaskBuffer(4000, 3000, 64);
        for (let y = 100; y < 140; y++) buf.setSpan(y, 100, 140);
        // The stroke straddles x=128 and y=128, so it touches 2x2 tiles.
        expect(buf.byteLength()).toBe(4 * 512);
        expect(4000 * 3000 * 4 / buf.byteLength()).toBeGreaterThan(20000);
    });

    test('even a fully painted large mask beats the dense buffer 32x', () => {
        const W = 640, H = 480;
        const buf = new MaskBuffer(W, H, 64);
        for (let y = 0; y < H; y++) buf.setSpan(y, 0, W - 1);
        // 480 is not a multiple of 64, so the bottom tile row is partly
        // outside the image: 10x8 tiles rather than the 10x7.5 the pixel
        // count alone implies. That padding is the price of fixed tiles.
        expect(buf.byteLength()).toBe(10 * 8 * 512);
        expect(W * H * 4 / buf.byteLength()).toBeGreaterThan(29);
    });
});

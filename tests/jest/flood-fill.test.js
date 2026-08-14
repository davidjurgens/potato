/**
 * Span-based flood fill.
 *
 * The fill was rewritten from a per-pixel 4-neighbour stack (~4N pushes for an
 * N-pixel region, which locked the tab on multi-megapixel images) to a span
 * fill that walks each horizontal run and seeds only where a run begins.
 *
 * A rewrite like that is only safe if the OUTPUT is identical, so these tests
 * compare it against a reference implementation of the old algorithm across
 * shapes that break naive fills: concavities, diagonal gaps, holes, single-pixel
 * channels, and regions touching every edge. Spot-checking a filled square
 * would not have caught a span fill that leaks through a diagonal.
 */

const fs = require('fs');
const path = require('path');

require('../../potato/static/mask-buffer.js');  // sets window.MaskBuffer

const SRC = path.join(__dirname, '..', '..', 'potato', 'static', 'image-annotation.js');
eval(fs.readFileSync(SRC, 'utf8'));

/** The pre-rewrite algorithm, kept verbatim as the oracle. */
function referenceFill(maskData, pixels, width, height, startX, startY, mode,
                       tolerance, color, maxPixels) {
    const startPix = startY * width + startX;
    if (mode === 'empty' && maskData[startPix * 4 + 3] > 128) return 0;

    let targetR = 0, targetG = 0, targetB = 0;
    if (mode === 'region') {
        const si = startPix * 4;
        targetR = pixels[si]; targetG = pixels[si + 1]; targetB = pixels[si + 2];
    }

    const visited = new Uint8Array(width * height);
    const stack = [startPix];
    let filled = 0;

    while (stack.length > 0) {
        const pix = stack.pop();
        if (visited[pix]) continue;
        visited[pix] = 1;

        const px = pix % width;
        const py = (pix - px) / width;
        const di = pix * 4;

        if (mode === 'region') {
            if (Math.abs(pixels[di] - targetR) > tolerance ||
                Math.abs(pixels[di + 1] - targetG) > tolerance ||
                Math.abs(pixels[di + 2] - targetB) > tolerance) continue;
        } else if (maskData[di + 3] > 128) {
            continue;
        }

        maskData[di] = color.r;
        maskData[di + 1] = color.g;
        maskData[di + 2] = color.b;
        maskData[di + 3] = 255;
        filled++;

        if (px + 1 < width) stack.push(pix + 1);
        if (px - 1 >= 0) stack.push(pix - 1);
        if (py + 1 < height) stack.push(pix + width);
        if (py - 1 >= 0) stack.push(pix - width);

        if (filled >= maxPixels) break;
    }
    return filled;
}

function makeManager(width, height, opts = {}) {
    const m = Object.create(ImageAnnotationManager.prototype);
    m.maskImgWidth = width;
    m.maskImgHeight = height;
    m.config = Object.assign({ fillTolerance: 32, fillMaxPixels: 4000000 }, opts);
    return m;
}

/**
 * The live representation. The oracle above keeps the dense RGBA array it was
 * written against — deliberately, since a reference that shares the new storage
 * would only prove the new storage agrees with itself.
 */
function blankMask(width, height, color = '#ff0000') {
    return { buffer: new MaskBuffer(width, height), color: color };
}

/** Occupancy as a flat 0/1 array — what actually got filled. */
function filledSet(data) {
    const out = [];
    for (let i = 0; i < data.length; i += 4) out.push(data[i + 3] > 128 ? 1 : 0);
    return out;
}

function bufferFilledSet(buffer) {
    const out = new Array(buffer.width * buffer.height).fill(0);
    buffer.forEachSetPixel((pix) => { out[pix] = 1; });
    return out;
}

/**
 * Run both implementations on identical input and compare.
 *
 * `maskSetup(paint, width, height)` receives a `paint(x, y)` callback so one
 * description of the pre-painted pixels drives both representations.
 */
function compare(width, height, startX, startY, mode, buildPixels, maskSetup) {
    const pixels = buildPixels ? buildPixels(width, height) : null;

    const mineMask = blankMask(width, height);
    const refData = new Uint8ClampedArray(width * height * 4);
    if (maskSetup) {
        maskSetup((x, y) => {
            mineMask.buffer.setAt(x, y);
            refData[(y * width + x) * 4 + 3] = 255;
        }, width, height);
    }

    const m = makeManager(width, height);
    const mineCount = m._floodFillFrom(mineMask, startX, startY, mode, pixels);
    const refCount = referenceFill(refData, pixels, width, height,
                                   startX, startY, mode, 32,
                                   { r: 255, g: 0, b: 0 }, 4000000);

    return {
        mine: bufferFilledSet(mineMask.buffer),
        ref: filledSet(refData),
        mineCount, refCount,
    };
}

/** A grid of colours from a string map: '.' = white, '#' = black. */
function pixelsFromMap(map) {
    const rows = map.trim().split('\n').map(r => r.trim());
    const height = rows.length;
    const width = rows[0].length;
    const px = new Uint8ClampedArray(width * height * 4);
    rows.forEach((row, y) => {
        for (let x = 0; x < width; x++) {
            const i = (y * width + x) * 4;
            const v = row[x] === '#' ? 0 : 255;
            px[i] = v; px[i + 1] = v; px[i + 2] = v; px[i + 3] = 255;
        }
    });
    return { px, width, height };
}

describe('span fill matches the per-pixel fill exactly', () => {
    test('an open region in empty mode', () => {
        const r = compare(20, 15, 5, 5, 'empty', null, null);
        expect(r.mine).toEqual(r.ref);
        expect(r.mineCount).toBe(20 * 15);
        expect(r.mineCount).toBe(r.refCount);
    });

    test('empty mode stops at already-painted pixels', () => {
        // A vertical wall of paint down the middle.
        const r = compare(20, 15, 2, 2, 'empty', null, (paint, w, h) => {
            for (let y = 0; y < h; y++) paint(10, y);
        });
        expect(r.mine).toEqual(r.ref);
        expect(r.mineCount).toBe(r.refCount);
        expect(r.mineCount).toBe(10 * 15);  // left of the wall only
    });

    test('a concave region — a U shape', () => {
        const { px, width, height } = pixelsFromMap(`
            ####################
            #..................#
            #..####....####....#
            #..####....####....#
            #..####....####....#
            #..####....####....#
            #..................#
            ####################
        `);
        const r = compare(width, height, 1, 1, 'region', () => px, null);
        expect(r.mine).toEqual(r.ref);
        expect(r.mineCount).toBe(r.refCount);
    });

    test('a region with an enclosed hole it must not reach', () => {
        const { px, width, height } = pixelsFromMap(`
            ....................
            ....................
            ....########........
            ....#......#........
            ....#......#........
            ....########........
            ....................
            ....................
        `);
        const r = compare(width, height, 0, 0, 'region', () => px, null);
        expect(r.mine).toEqual(r.ref);
        // The interior of the box is unreachable from outside.
        const idx = (y, x) => y * width + x;
        expect(r.mine[idx(3, 6)]).toBe(0);
        expect(r.mine[idx(0, 0)]).toBe(1);
    });

    test('a diagonal gap must NOT leak (4-connectivity)', () => {
        // The only "opening" is corner-to-corner, which a 4-connected fill
        // cannot pass. A span fill that seeded diagonals would leak here.
        const { px, width, height } = pixelsFromMap(`
            ##########
            #....#####
            #...#..###
            #..#...###
            ####...###
            ##########
        `);
        const r = compare(width, height, 1, 1, 'region', () => px, null);
        expect(r.mine).toEqual(r.ref);
        const idx = (y, x) => y * width + x;
        expect(r.mine[idx(1, 1)]).toBe(1);
        expect(r.mine[idx(3, 6)]).toBe(0);
    });

    test('a single-pixel-wide channel', () => {
        const { px, width, height } = pixelsFromMap(`
            ##########
            #........#
            ########.#
            #........#
            #.########
            #........#
            ##########
        `);
        const r = compare(width, height, 1, 1, 'region', () => px, null);
        expect(r.mine).toEqual(r.ref);
        expect(r.mineCount).toBe(r.refCount);
    });

    test('a region touching every edge', () => {
        const { px, width, height } = pixelsFromMap(`
            ..........
            .########.
            .#......#.
            .########.
            ..........
        `);
        const r = compare(width, height, 0, 0, 'region', () => px, null);
        expect(r.mine).toEqual(r.ref);
        expect(r.mineCount).toBe(r.refCount);
    });

    test('starting in a corner', () => {
        for (const [sx, sy] of [[0, 0], [19, 0], [0, 14], [19, 14]]) {
            const r = compare(20, 15, sx, sy, 'empty', null, null);
            expect(r.mine).toEqual(r.ref);
        }
    });

    test('a one-pixel image', () => {
        const r = compare(1, 1, 0, 0, 'empty', null, null);
        expect(r.mine).toEqual(r.ref);
        expect(r.mineCount).toBe(1);
    });

    test('a single-row image', () => {
        const r = compare(30, 1, 15, 0, 'empty', null, null);
        expect(r.mine).toEqual(r.ref);
        expect(r.mineCount).toBe(30);
    });

    test('a single-column image', () => {
        const r = compare(1, 30, 0, 15, 'empty', null, null);
        expect(r.mine).toEqual(r.ref);
        expect(r.mineCount).toBe(30);
    });

    test('random noise regions, many seeds', () => {
        // Deterministic pseudo-random so a failure is reproducible.
        let seed = 12345;
        const rand = () => {
            seed = (seed * 1103515245 + 12345) & 0x7fffffff;
            return seed / 0x7fffffff;
        };
        const width = 40, height = 30;
        const px = new Uint8ClampedArray(width * height * 4);
        for (let i = 0; i < width * height; i++) {
            const v = rand() < 0.45 ? 0 : 255;
            px[i * 4] = v; px[i * 4 + 1] = v; px[i * 4 + 2] = v; px[i * 4 + 3] = 255;
        }
        for (let t = 0; t < 25; t++) {
            const sx = Math.floor(rand() * width);
            const sy = Math.floor(rand() * height);
            const r = compare(width, height, sx, sy, 'region', () => px, null);
            expect({ seed: [sx, sy], set: r.mine }).toEqual({ seed: [sx, sy], set: r.ref });
            expect(r.mineCount).toBe(r.refCount);
        }
    });

    test('tolerance is honoured identically on a gradient', () => {
        const width = 30, height = 20;
        const px = new Uint8ClampedArray(width * height * 4);
        for (let y = 0; y < height; y++) {
            for (let x = 0; x < width; x++) {
                const i = (y * width + x) * 4;
                const v = Math.min(255, x * 9);
                px[i] = v; px[i + 1] = v; px[i + 2] = v; px[i + 3] = 255;
            }
        }
        const r = compare(width, height, 0, 10, 'region', () => px, null);
        expect(r.mine).toEqual(r.ref);
        // tolerance 32 over a 9-per-column ramp reaches ~4 columns.
        expect(r.mineCount).toBeGreaterThan(0);
        expect(r.mineCount).toBeLessThan(width * height);
        expect(r.mineCount).toBe(r.refCount);
    });
});

describe('the pixel cap', () => {
    test('stops at fillMaxPixels and warns', () => {
        const width = 40, height = 40;
        const mask = blankMask(width, height);
        const m = makeManager(width, height, { fillMaxPixels: 100 });
        const warn = jest.spyOn(console, 'warn').mockImplementation(() => {});

        const filled = m._floodFillFrom(mask, 0, 0, 'empty', null);

        expect(filled).toBe(100);
        expect(warn).toHaveBeenCalledWith(
            expect.stringContaining('fill stopped at 100 pixels'));
        warn.mockRestore();
    });

    test('a capped fill leaves the rest of the mask untouched', () => {
        const width = 40, height = 40;
        const mask = blankMask(width, height);
        const m = makeManager(width, height, { fillMaxPixels: 50 });
        jest.spyOn(console, 'warn').mockImplementation(() => {});

        m._floodFillFrom(mask, 0, 0, 'empty', null);
        expect(mask.buffer.countSet()).toBe(50);
        console.warn.mockRestore();
    });
});

describe('it fills with the mask colour', () => {
    test('every filled pixel renders in the mask colour at full alpha', () => {
        // Colour is no longer stored per pixel — the buffer holds occupancy and
        // the mask carries the colour — so the check is that RENDERING the
        // filled buffer produces the mask's colour everywhere.
        const mask = blankMask(6, 4, '#00ff00');
        const m = makeManager(6, 4);
        m._floodFillFrom(mask, 0, 0, 'empty', null);
        const rgba = mask.buffer.toRGBA({ r: 0, g: 255, b: 0 });
        for (let i = 0; i < rgba.length; i += 4) {
            expect([rgba[i], rgba[i + 1], rgba[i + 2], rgba[i + 3]])
                .toEqual([0, 255, 0, 255]);
        }
    });
});

describe('performance characteristics', () => {
    test('a large open fill completes without exhausting the stack', () => {
        // 1000x1000 = 1M pixels. The per-pixel version pushed ~4M entries.
        const width = 1000, height = 1000;
        const mask = blankMask(width, height);
        const m = makeManager(width, height);
        const filled = m._floodFillFrom(mask, 500, 500, 'empty', null);
        expect(filled).toBe(width * height);
    });
});

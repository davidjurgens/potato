/**
 * MaskBuffer — sparse, tiled occupancy store for brush and fill masks.
 *
 * ## Why this exists
 *
 * A mask used to be a dense `Uint8ClampedArray(width * height * 4)`: one RGBA
 * pixel per image pixel, per label. On a 12 MP photo that is **48 MB for a
 * single mask**, allocated the moment the annotator's brush first touches the
 * image, whether they paint one stroke or the whole frame. Ten labels is half a
 * gigabyte of mostly-zero bytes, and the render path copied the entire buffer
 * on every mousemove.
 *
 * Three properties of the data make that representation wasteful:
 *
 *   1. **It is one bit of information per pixel.** A pixel is in the mask or it
 *      is not. The RGB channels only ever held the mask's own colour, which is
 *      already on the mask object — they were 24 bits of duplication per pixel.
 *   2. **It is sparse.** A segmented object covers a small fraction of the
 *      frame, so most tiles are never written at all.
 *   3. **Edits are local.** A brush stroke touches a handful of 64x64 tiles;
 *      repainting the whole image to show it is wasted work.
 *
 * So: 1 bit per pixel, in 64x64 tiles allocated on first write, with a dirty
 * set so the render path repaints only what changed.
 *
 * ## Measured
 *
 * Ten classes, one 40x40 brush dab each, and the per-mousemove render cost
 * (median of 9, node 22 on an M-series Mac):
 *
 *              mask data                canvas          render/move
 *      1 MP    38.1 MB ->  16.0 KB      3.8 MB          0.017 ms
 *      3 MP   114.4 MB ->  16.0 KB     11.4 MB          0.018 ms
 *     12 MP   457.8 MB ->  16.0 KB     45.8 MB          0.013 ms
 *
 * Two separate things happened, and it is worth keeping them apart:
 *
 *   - **Mask data** stopped scaling with image area at all. It is now
 *     proportional to what was painted, not to what could have been.
 *   - **Canvas** stopped scaling with the class count. The renderer composites
 *     every mask into ONE offscreen surface, so that column is the same for one
 *     class or for ten. The old code allocated a full-size temp canvas *per
 *     mask, per mousemove*, and threw it away again.
 *
 * The canvas is an irreducible cost of drawing at natural resolution, so the
 * honest summary is that resident cost went from O(classes x pixels) to
 * O(pixels) — roughly 458 MB to 46 MB for ten classes on a 12 MP photo — and
 * that per-frame allocation churn went away.
 *
 * What did **not** change materially is bulk work: painting a stroke and
 * encoding a whole mask to RLE are within noise of the dense versions, since
 * both are dominated by touching every pixel once.
 *
 * ## Why this is not a drop-in
 *
 * The roadmap assumed a sparse store could hide "behind the same `this.masks`
 * API so no call site changes". It cannot. Twenty-odd call sites indexed
 * `mask.data[i + 3]` directly, and preserving that indexing over a tiled store
 * needs a Proxy whose trap fires on **every pixel access** — slower than the
 * dense buffer it replaces, which is the opposite of the goal.
 *
 * This class therefore exposes explicit accessors, and the field was renamed
 * `mask.data` -> `mask.buffer` so that any call site left behind fails loudly
 * instead of silently reading `undefined`.
 *
 * ## Row-oriented API
 *
 * `setSpan` / `clearSpan` / `rowReader` exist because the callers are all
 * row-shaped — a scanline fill walks runs, a brush circle is a stack of rows —
 * and a span does one tile lookup per 64 pixels instead of one per pixel. The
 * per-pixel `setAt` / `isSetAt` are there for correctness, not for hot loops.
 *
 * ## RLE
 *
 * `encodeRLE` emits Potato's documented wire format: run lengths alternating
 * background-first, row-major. See the note on `encodeRLE` for the bug this
 * replaced.
 */
(function (root) {
    'use strict';

    const DEFAULT_TILE = 64;

    class MaskBuffer {
        /**
         * @param {number} width  image width in pixels
         * @param {number} height image height in pixels
         * @param {number} [tileSize] power of two, default 64
         */
        constructor(width, height, tileSize) {
            this.width = Math.max(0, width | 0);
            this.height = Math.max(0, height | 0);

            const ts = tileSize || DEFAULT_TILE;
            if (ts <= 0 || (ts & (ts - 1)) !== 0) {
                // Every index computation uses shifts and masks, which are only
                // equivalent to divide/modulo for powers of two.
                throw new Error(`MaskBuffer tileSize must be a power of two, got ${ts}`);
            }
            this.tileSize = ts;
            this.tileShift = Math.round(Math.log2(ts));
            this.tileMask = ts - 1;
            this.tilesX = Math.ceil(this.width / ts);
            this.tilesY = Math.ceil(this.height / ts);
            this.bytesPerTile = (ts * ts) >> 3;

            /** @type {Map<number, Uint8Array>} tile index -> bitmap */
            this.tiles = new Map();
            this._setCount = 0;

            // Which tiles the renderer still has to repaint. The canvas
            // itself belongs to the renderer, which composites every mask into
            // one shared surface — see paintTileInto.
            this._dirtyTiles = new Set();
            this._allDirty = true;
        }

        get pixelCount() {
            return this.width * this.height;
        }

        // ---------------------------------------------------------------
        // Writes
        // ---------------------------------------------------------------

        /** Mark one pixel. Returns true if it was not already set. */
        setAt(x, y) {
            if (x < 0 || y < 0 || x >= this.width || y >= this.height) return false;
            const ti = (y >> this.tileShift) * this.tilesX + (x >> this.tileShift);
            let tile = this.tiles.get(ti);
            if (!tile) {
                tile = new Uint8Array(this.bytesPerTile);
                this.tiles.set(ti, tile);
            }
            const bit = ((y & this.tileMask) << this.tileShift) | (x & this.tileMask);
            const byte = bit >> 3;
            const m = 1 << (bit & 7);
            if (tile[byte] & m) return false;
            tile[byte] |= m;
            this._setCount++;
            this._markDirty(ti);
            return true;
        }

        /** Unmark one pixel. Returns true if it had been set. */
        clearAt(x, y) {
            if (x < 0 || y < 0 || x >= this.width || y >= this.height) return false;
            const ti = (y >> this.tileShift) * this.tilesX + (x >> this.tileShift);
            const tile = this.tiles.get(ti);
            if (!tile) return false;
            const bit = ((y & this.tileMask) << this.tileShift) | (x & this.tileMask);
            const byte = bit >> 3;
            const m = 1 << (bit & 7);
            if (!(tile[byte] & m)) return false;
            tile[byte] &= ~m;
            this._setCount--;
            this._markDirty(ti);
            return true;
        }

        /**
         * Mark the inclusive run [x0, x1] on row y. Returns how many pixels
         * changed from unset to set.
         *
         * One tile lookup per 64 columns rather than per pixel — the whole
         * reason the callers were reshaped to be row-oriented.
         */
        setSpan(y, x0, x1) {
            if (y < 0 || y >= this.height) return 0;
            let x = Math.max(0, x0);
            const end = Math.min(this.width - 1, x1);
            if (x > end) return 0;

            const shift = this.tileShift;
            const tm = this.tileMask;
            const rowBits = (y & tm) << shift;
            const tileRow = (y >> shift) * this.tilesX;
            let changed = 0;

            while (x <= end) {
                const tx = x >> shift;
                const ti = tileRow + tx;
                let tile = this.tiles.get(ti);
                if (!tile) {
                    tile = new Uint8Array(this.bytesPerTile);
                    this.tiles.set(ti, tile);
                }
                const tileEnd = Math.min(end, ((tx + 1) << shift) - 1);
                for (; x <= tileEnd; x++) {
                    const bit = rowBits | (x & tm);
                    const byte = bit >> 3;
                    const m = 1 << (bit & 7);
                    if (!(tile[byte] & m)) {
                        tile[byte] |= m;
                        changed++;
                    }
                }
                this._markDirty(ti);
            }

            this._setCount += changed;
            return changed;
        }

        /** Unmark the inclusive run [x0, x1] on row y. Returns pixels cleared. */
        clearSpan(y, x0, x1) {
            if (y < 0 || y >= this.height) return 0;
            let x = Math.max(0, x0);
            const end = Math.min(this.width - 1, x1);
            if (x > end) return 0;

            const shift = this.tileShift;
            const tm = this.tileMask;
            const rowBits = (y & tm) << shift;
            const tileRow = (y >> shift) * this.tilesX;
            let changed = 0;

            while (x <= end) {
                const tx = x >> shift;
                const ti = tileRow + tx;
                const tile = this.tiles.get(ti);
                const tileEnd = Math.min(end, ((tx + 1) << shift) - 1);
                if (!tile) {
                    // Nothing allocated here, so nothing to erase.
                    x = tileEnd + 1;
                    continue;
                }
                for (; x <= tileEnd; x++) {
                    const bit = rowBits | (x & tm);
                    const byte = bit >> 3;
                    const m = 1 << (bit & 7);
                    if (tile[byte] & m) {
                        tile[byte] &= ~m;
                        changed++;
                    }
                }
                this._markDirty(ti);
            }

            this._setCount -= changed;
            return changed;
        }

        /** Drop every set pixel, keeping the dimensions. */
        clear() {
            if (this.tiles.size === 0 && this._setCount === 0) return;
            this.tiles.clear();
            this._setCount = 0;
            this._allDirty = true;
            this._dirtyTiles.clear();
        }

        /**
         * Release tiles that no longer hold any pixel.
         *
         * Not done inside clearAt/clearSpan: proving a tile is empty means
         * scanning its 512 bytes, which is far too much to pay per erased
         * pixel. Callers run this once at the end of an erase gesture.
         */
        compact() {
            for (const [ti, tile] of Array.from(this.tiles.entries())) {
                let any = false;
                for (let i = 0; i < tile.length; i++) {
                    if (tile[i] !== 0) { any = true; break; }
                }
                if (!any) {
                    this.tiles.delete(ti);
                    this._markDirty(ti);
                }
            }
        }

        // ---------------------------------------------------------------
        // Reads
        // ---------------------------------------------------------------

        isSetAt(x, y) {
            if (x < 0 || y < 0 || x >= this.width || y >= this.height) return false;
            const tile = this.tiles.get(
                (y >> this.tileShift) * this.tilesX + (x >> this.tileShift));
            if (!tile) return false;
            const bit = ((y & this.tileMask) << this.tileShift) | (x & this.tileMask);
            return (tile[bit >> 3] & (1 << (bit & 7))) !== 0;
        }

        /** Flat row-major pixel index form of isSetAt. */
        isSet(pix) {
            if (this.width <= 0) return false;
            const y = (pix / this.width) | 0;
            return this.isSetAt(pix - y * this.width, y);
        }

        /** Flat row-major pixel index form of setAt. */
        set(pix) {
            if (this.width <= 0) return false;
            const y = (pix / this.width) | 0;
            return this.setAt(pix - y * this.width, y);
        }

        hasAny() {
            return this._setCount > 0;
        }

        countSet() {
            return this._setCount;
        }

        /**
         * A reader for one row that caches the tile between calls.
         *
         * The scanline fill probes the rows above and below a run column by
         * column; without this each probe is a Map lookup, and the Map lookup
         * dominated everything else in profiling.
         *
         * @returns {(x: number) => boolean}
         */
        rowReader(y) {
            if (y < 0 || y >= this.height) return () => false;
            const shift = this.tileShift;
            const tm = this.tileMask;
            const rowBits = (y & tm) << shift;
            const tileRow = (y >> shift) * this.tilesX;
            const width = this.width;
            const tiles = this.tiles;
            let cachedTx = -1;
            let cachedTile = null;
            return (x) => {
                if (x < 0 || x >= width) return false;
                const tx = x >> shift;
                if (tx !== cachedTx) {
                    cachedTx = tx;
                    cachedTile = tiles.get(tileRow + tx) || null;
                }
                if (!cachedTile) return false;
                const bit = rowBits | (x & tm);
                return (cachedTile[bit >> 3] & (1 << (bit & 7))) !== 0;
            };
        }

        /**
         * Call cb(pixelIndex) for every set pixel. Tile order, not raster
         * order — callers that need raster order use encodeRLE.
         */
        forEachSetPixel(cb) {
            const shift = this.tileShift;
            const size = this.tileSize;
            for (const [ti, tile] of this.tiles) {
                const tx = ti % this.tilesX;
                const ty = (ti / this.tilesX) | 0;
                const x0 = tx << shift;
                const y0 = ty << shift;
                const tw = Math.min(size, this.width - x0);
                const th = Math.min(size, this.height - y0);
                for (let ly = 0; ly < th; ly++) {
                    const rowBits = ly << shift;
                    const rowBase = (y0 + ly) * this.width + x0;
                    for (let lx = 0; lx < tw; lx++) {
                        const bit = rowBits | lx;
                        if (tile[bit >> 3] & (1 << (bit & 7))) {
                            cb(rowBase + lx);
                        }
                    }
                }
            }
        }

        /** Inclusive [x0, y0, x1, y1] of set pixels, or null when empty. */
        bounds() {
            if (this._setCount === 0) return null;
            let minX = this.width, minY = this.height, maxX = -1, maxY = -1;
            const shift = this.tileShift;
            const size = this.tileSize;
            for (const [ti, tile] of this.tiles) {
                const x0 = (ti % this.tilesX) << shift;
                const y0 = ((ti / this.tilesX) | 0) << shift;
                const tw = Math.min(size, this.width - x0);
                const th = Math.min(size, this.height - y0);
                for (let ly = 0; ly < th; ly++) {
                    const rowBits = ly << shift;
                    for (let lx = 0; lx < tw; lx++) {
                        const bit = rowBits | lx;
                        if (!(tile[bit >> 3] & (1 << (bit & 7)))) continue;
                        const x = x0 + lx, y = y0 + ly;
                        if (x < minX) minX = x;
                        if (x > maxX) maxX = x;
                        if (y < minY) minY = y;
                        if (y > maxY) maxY = y;
                    }
                }
            }
            return maxX < 0 ? null : [minX, minY, maxX, maxY];
        }

        // ---------------------------------------------------------------
        // Serialization
        // ---------------------------------------------------------------

        /**
         * Row-major run lengths, alternating and **starting with background**.
         *
         * This is the format `cv_utils.decode_rle` documents and every exporter
         * reads, and it is what the client's own SAM-preview decoder assumes.
         * The previous encoder did not honour it: it started counting at
         * `currentVal = 0, count = 0` and suppressed the leading zero-length
         * run, so a mask whose **first pixel was set** emitted its foreground
         * run first and every subsequent run was read with the wrong polarity.
         *
         *     painted pixel 0 of a 2x2 mask  ->  [1, 3]
         *     decoded back                   ->  pixels 1, 2, 3 painted
         *
         * A fully painted mask encoded to `[N]`, which is indistinguishable
         * from an empty one — so a full-canvas fill was stored as blank and
         * silently lost on reload. Emitting the leading `0` fixes both.
         *
         * Masks *already saved* by the old encoder cannot be repaired
         * automatically: `[1, 3]` is a legitimate encoding of "pixel 0 clear,
         * pixels 1-3 set", so there is no signal to distinguish a corrupted
         * mask from a correct one. Only masks touching the top-left pixel were
         * ever affected.
         */
        encodeRLE() {
            const counts = [];
            const w = this.width;
            const h = this.height;
            if (w <= 0 || h <= 0) return [0];

            const shift = this.tileShift;
            const tm = this.tileMask;
            let cur = 0;
            let run = 0;

            for (let y = 0; y < h; y++) {
                const rowBits = (y & tm) << shift;
                const tileRow = (y >> shift) * this.tilesX;
                let x = 0;
                while (x < w) {
                    const tx = x >> shift;
                    const tileEnd = Math.min(w - 1, ((tx + 1) << shift) - 1);
                    const tile = this.tiles.get(tileRow + tx);
                    if (!tile) {
                        // Unallocated tile: the whole span is background, so
                        // skip it wholesale instead of testing 64 bits.
                        const n = tileEnd - x + 1;
                        if (cur === 0) {
                            run += n;
                        } else {
                            counts.push(run);
                            cur = 0;
                            run = n;
                        }
                        x = tileEnd + 1;
                        continue;
                    }
                    for (; x <= tileEnd; x++) {
                        const bit = rowBits | (x & tm);
                        const v = (tile[bit >> 3] & (1 << (bit & 7))) ? 1 : 0;
                        if (v === cur) {
                            run++;
                        } else {
                            counts.push(run);
                            cur = v;
                            run = 1;
                        }
                    }
                }
            }
            counts.push(run);
            return counts;
        }

        /** Build a buffer from background-first row-major run lengths. */
        static fromRLE(counts, width, height, tileSize) {
            const buf = new MaskBuffer(width, height, tileSize);
            const total = buf.pixelCount;
            let idx = 0;
            let val = 0;
            for (const count of (counts || [])) {
                if (idx >= total) break;
                const n = Math.min(count, total - idx);
                if (val === 1) {
                    let remaining = n;
                    while (remaining > 0) {
                        const y = (idx / width) | 0;
                        const x = idx - y * width;
                        const take = Math.min(remaining, width - x);
                        buf.setSpan(y, x, x + take - 1);
                        idx += take;
                        remaining -= take;
                    }
                } else {
                    idx += n;
                }
                val = 1 - val;
            }
            return buf;
        }

        // ---------------------------------------------------------------
        // Interop
        // ---------------------------------------------------------------

        /** Set every pixel whose alpha exceeds 128 in a dense RGBA buffer. */
        static fromRGBA(data, width, height, tileSize) {
            const buf = new MaskBuffer(width, height, tileSize);
            for (let y = 0; y < height; y++) {
                const rowBase = y * width;
                let x = 0;
                while (x < width) {
                    if (data[(rowBase + x) * 4 + 3] > 128) {
                        const start = x;
                        while (x < width && data[(rowBase + x) * 4 + 3] > 128) x++;
                        buf.setSpan(y, start, x - 1);
                    } else {
                        x++;
                    }
                }
            }
            return buf;
        }

        /**
         * Dense RGBA rendering in one flat array.
         *
         * Kept for tests and for anything that genuinely needs a contiguous
         * buffer; the live render path uses paintTileInto(), which repaints only
         * the tiles that changed.
         *
         * @param {{r:number,g:number,b:number}} rgb
         */
        toRGBA(rgb) {
            const out = new Uint8ClampedArray(this.pixelCount * 4);
            const r = rgb ? rgb.r : 255;
            const g = rgb ? rgb.g : 255;
            const b = rgb ? rgb.b : 255;
            this.forEachSetPixel((pix) => {
                const i = pix * 4;
                out[i] = r;
                out[i + 1] = g;
                out[i + 2] = b;
                out[i + 3] = 255;
            });
            return out;
        }

        clone() {
            const copy = new MaskBuffer(this.width, this.height, this.tileSize);
            for (const [ti, tile] of this.tiles) {
                copy.tiles.set(ti, new Uint8Array(tile));
            }
            copy._setCount = this._setCount;
            return copy;
        }

        /** Nearest-neighbour resample into a new buffer. */
        rescale(dstW, dstH) {
            const out = new MaskBuffer(dstW, dstH, this.tileSize);
            if (this.width <= 0 || this.height <= 0) return out;
            for (let y = 0; y < dstH; y++) {
                const sy = Math.min(this.height - 1, Math.floor(y * this.height / dstH));
                const read = this.rowReader(sy);
                let x = 0;
                while (x < dstW) {
                    const sx = Math.min(this.width - 1, Math.floor(x * this.width / dstW));
                    if (read(sx)) {
                        const start = x;
                        x++;
                        while (x < dstW &&
                               read(Math.min(this.width - 1,
                                             Math.floor(x * this.width / dstW)))) {
                            x++;
                        }
                        out.setSpan(y, start, x - 1);
                    } else {
                        x++;
                    }
                }
            }
            return out;
        }

        // ---------------------------------------------------------------
        // Rendering
        // ---------------------------------------------------------------

        _markDirty(ti) {
            if (this._allDirty) return;
            this._dirtyTiles.add(ti);
        }

        /**
         * Whether every tile needs repainting (new buffer, or bulk change).
         */
        isAllDirty() {
            return this._allDirty;
        }

        /** Tile indices changed since the last `clearDirty()`. */
        dirtyTiles() {
            return this._dirtyTiles;
        }

        /** Mark the whole buffer as needing repaint (e.g. after a recolour). */
        markAllDirty() {
            this._allDirty = true;
            this._dirtyTiles.clear();
        }

        clearDirty() {
            this._allDirty = false;
            this._dirtyTiles.clear();
        }

        /**
         * Paint this buffer's set pixels within one tile into an ImageData
         * covering that tile, in `rgb`.
         *
         * The caller owns the ImageData and the canvas. That is deliberate:
         * **the renderer composites every mask into one shared canvas**, not
         * one canvas per mask. A canvas at natural resolution costs four bytes
         * per pixel of backing store — 48 MB on a 12 MP image — so a canvas per
         * class would hand straight back the memory the tiles just saved, and
         * ten classes would be worse than the dense buffers this replaced.
         *
         * Unset pixels are left untouched rather than written transparent, so
         * masks layer correctly when several overlap in one tile.
         *
         * @param {{data: Uint8ClampedArray}} img ImageData for the tile
         * @param {number} ti tile index
         * @param {number} tw tile width in pixels (clipped at the image edge)
         * @param {number} th tile height in pixels
         * @param {{r:number,g:number,b:number}} rgb
         */
        paintTileInto(img, ti, tw, th, rgb) {
            const tile = this.tiles.get(ti);
            if (!tile) return;
            const shift = this.tileShift;
            const data = img.data;
            const r = rgb.r, g = rgb.g, b = rgb.b;
            for (let ly = 0; ly < th; ly++) {
                const rowBits = ly << shift;
                const outRow = ly * tw;
                for (let lx = 0; lx < tw; lx++) {
                    const bit = rowBits | lx;
                    if (!(tile[bit >> 3] & (1 << (bit & 7)))) continue;
                    const p = (outRow + lx) * 4;
                    data[p] = r;
                    data[p + 1] = g;
                    data[p + 2] = b;
                    data[p + 3] = 255;
                }
            }
        }

        /** Geometry of tile `ti`: [x0, y0, width, height], clipped to the image. */
        tileRect(ti) {
            const shift = this.tileShift;
            const x0 = (ti % this.tilesX) << shift;
            const y0 = ((ti / this.tilesX) | 0) << shift;
            return [x0, y0,
                    Math.min(this.tileSize, this.width - x0),
                    Math.min(this.tileSize, this.height - y0)];
        }

        /** Approximate heap cost in bytes, for telemetry and debugging. */
        byteLength() {
            return this.tiles.size * this.bytesPerTile;
        }
    }

    MaskBuffer.DEFAULT_TILE_SIZE = DEFAULT_TILE;

    if (typeof module !== 'undefined' && module.exports) {
        module.exports = MaskBuffer;
    }
    if (root) {
        root.MaskBuffer = MaskBuffer;
    }
})(typeof window !== 'undefined' ? window : (typeof globalThis !== 'undefined' ? globalThis : null));

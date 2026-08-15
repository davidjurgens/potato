/**
 * Depth map viewer: window, colormap, overlay, and a readout in metres.
 *
 * The colourised image comes from the server (`/media/depth/...`) because a
 * browser cannot decode a 16-bit PNG into usable values — `drawImage` of a
 * mode-I PNG crushes it to 8 bits before any JavaScript sees it. The **raw
 * floats** come down separately as a DPT1 buffer, because a colormap is not
 * injective at 8 bits and the distance under the cursor cannot be recovered
 * from the picture.
 *
 * The arithmetic (buffer parsing, pixel lookup, URL building, formatting) is
 * exported as statics so Jest can drive it without a DOM. The rest is wiring.
 */
(function (root) {
    'use strict';

    const MAGIC = 'DPT1';

    /**
     * Parse a DPT1 buffer.
     *
     * Layout mirrors `potato/media/depth.py:to_wire`. NaN means "no
     * measurement" — carried through rather than coerced, because a sentinel
     * of 0 would contribute a real number to every statistic and paint a wall
     * across every hole in the sensor's coverage.
     */
    function parseDepthWire(buffer) {
        const bytes = new Uint8Array(buffer);
        if (bytes.length < 8) throw new Error('depth buffer is truncated');
        const magic = String.fromCharCode(bytes[0], bytes[1], bytes[2], bytes[3]);
        if (magic !== MAGIC) {
            throw new Error(`expected a ${MAGIC} depth buffer, got "${magic}"`);
        }

        const view = new DataView(buffer);
        const headerLen = view.getUint32(4, true);
        const header = JSON.parse(
            new TextDecoder('utf-8').decode(bytes.subarray(8, 8 + headerLen)));

        const count = (header.width | 0) * (header.height | 0);
        const offset = 8 + headerLen;
        let values;
        if (offset % 4 === 0) {
            values = new Float32Array(buffer, offset, count);
        } else {
            const copy = new Uint8Array(count * 4);
            copy.set(new Uint8Array(buffer, offset, count * 4));
            values = new Float32Array(copy.buffer);
        }
        return { header, width: header.width | 0, height: header.height | 0,
                 values };
    }

    /**
     * Depth in metres at a fractional position, or null where there is none.
     *
     * `u` and `v` are in [0, 1] across the displayed image, so the caller does
     * not have to know the pixel dimensions — which is the point, because the
     * image is scaled to fit and a caller working in element pixels gets it
     * wrong the first time the layout changes.
     */
    function depthAt(parsed, u, v) {
        if (!parsed || !parsed.width || !parsed.height) return null;
        if (!(u >= 0 && u <= 1 && v >= 0 && v <= 1)) return null;
        const col = Math.min(parsed.width - 1, Math.floor(u * parsed.width));
        const row = Math.min(parsed.height - 1, Math.floor(v * parsed.height));
        const value = parsed.values[row * parsed.width + col];
        return Number.isFinite(value) ? value : null;
    }

    /**
     * What the readout says.
     *
     * "No measurement here" rather than a blank or a zero: a hole in a depth
     * map is a fact about the sensor, and an annotator who reads it as zero
     * metres will treat a gap as a surface.
     */
    function formatDepth(metres) {
        if (metres === null || metres === undefined) {
            return 'No measurement here';
        }
        if (metres < 1) return `${(metres * 100).toFixed(1)} cm`;
        if (metres < 100) return `${metres.toFixed(2)} m`;
        return `${metres.toFixed(0)} m`;
    }

    /** The render URL for a window and colormap. Omitted values stay omitted. */
    function buildUrl(path, params) {
        const query = [];
        Object.keys(params || {}).forEach((key) => {
            const value = params[key];
            if (value === null || value === undefined || value === '') return;
            if (value === false) return;
            query.push(`${encodeURIComponent(key)}=`
                       + `${encodeURIComponent(value === true ? 1 : value)}`);
        });
        const base = `/media/depth/${path}`;
        return query.length ? `${base}?${query.join('&')}` : base;
    }

    class DepthViewer {
        constructor(element) {
            this.element = element;
            this.config = JSON.parse(
                element.getAttribute('data-depth-config') || '{}');
            this.stage = element.querySelector('.depth-stage');
            this.overlay = element.querySelector('.depth-overlay');
            this.rgb = element.querySelector('.depth-rgb');
            this.readout = element.querySelector('.depth-readout-value');
            this.loading = element.querySelector('.depth-loading');
            this.parsed = null;
            this.info = null;
            this._renderTimer = null;
        }

        async init() {
            this._attachRgb();
            await this._loadInfo();
            this._bindControls();
            this._bindReadout();
            this._render();
            // Deliberately after the first render: the picture is what the
            // annotator is waiting for, and a two-megabyte float buffer would
            // delay it for a readout they have not asked for yet.
            this._loadRaw();
        }

        /**
         * Underlay the RGB frame from a sibling display field.
         *
         * Read out of the DOM rather than passed through the config, because a
         * display renderer is only handed its **own** field's value — one
         * config string cannot name a different photograph per item, and the
         * image field has already rendered the right one.
         */
        _attachRgb() {
            const field = this.config.rgbField;
            if (!field || !this.rgb) return;
            const sibling = document.querySelector(
                `[data-field-key="${cssEscape(field)}"] img`);
            if (!sibling || !sibling.src) return;
            this.rgb.src = sibling.src;
            this.rgb.hidden = false;
        }

        async _loadInfo() {
            try {
                const response = await fetch(
                    buildUrl(this.config.path,
                             { info: 1, scale: this.config.depthScale }),
                    { credentials: 'same-origin' });
                if (!response.ok) {
                    const detail = await this._errorText(response);
                    this._fail(detail);
                    return;
                }
                this.info = await response.json();
            } catch (err) {
                this._fail(`Could not read the depth map: ${err.message}`);
                return;
            }

            const near = this.element.querySelector('.depth-near');
            const far = this.element.querySelector('.depth-far');
            // Seeded from the 2nd/98th percentile, not min/max: one stray
            // return otherwise compresses everything real into one colour and
            // the map opens looking blank.
            if (near && this.info.p2 !== null) near.value = round(this.info.p2);
            if (far && this.info.p98 !== null) far.value = round(this.info.p98);

            if (this.info.invalid_fraction > 0.5) {
                this._note(
                    `${Math.round(this.info.invalid_fraction * 100)}% of this `
                    + `map has no measurement (shown in magenta).`);
            }
        }

        async _loadRaw() {
            try {
                const response = await fetch(
                    buildUrl(this.config.path,
                             { raw: 1, scale: this.config.depthScale }),
                    { credentials: 'same-origin' });
                if (!response.ok) return;
                this.parsed = parseDepthWire(await response.arrayBuffer());
            } catch (_err) {
                // The picture still works; only the readout is lost. Saying
                // so beats replacing a usable view with an error.
                this._note('Depth values unavailable; the readout is off.');
            }
        }

        _render() {
            if (!this.overlay) return;
            const near = this._value('.depth-near');
            const far = this._value('.depth-far');
            const colormap = this._selected('.depth-colormap')
                || this.config.colormap;

            this.overlay.src = buildUrl(this.config.path, {
                scale: this.config.depthScale,
                window_min: near,
                window_max: far,
                colormap,
                invert: this.config.invert,
            });
            this.overlay.style.opacity = this.rgb && !this.rgb.hidden
                ? String(this._opacity()) : '1';
            if (this.loading) this.loading.hidden = true;
        }

        _scheduleRender() {
            // Typing "12.5" into the far field would otherwise fire three
            // renders, and each one is a server-side colourisation.
            if (this._renderTimer) clearTimeout(this._renderTimer);
            this._renderTimer = setTimeout(() => {
                this._renderTimer = null;
                this._render();
            }, 250);
        }

        _bindControls() {
            ['.depth-near', '.depth-far'].forEach((sel) => {
                const el = this.element.querySelector(sel);
                if (el) el.addEventListener('input', () => this._scheduleRender());
            });
            const cmap = this.element.querySelector('.depth-colormap');
            if (cmap) cmap.addEventListener('change', () => this._render());

            const opacity = this.element.querySelector('.depth-opacity');
            if (opacity) {
                opacity.addEventListener('input', () => {
                    // Local, not a re-render: opacity is a CSS property and
                    // re-fetching the image to change it would be absurd.
                    this.overlay.style.opacity = String(this._opacity());
                });
            }

            const reset = this.element.querySelector('.depth-reset');
            if (reset) {
                reset.addEventListener('click', () => {
                    const near = this.element.querySelector('.depth-near');
                    const far = this.element.querySelector('.depth-far');
                    if (near && this.info) near.value = round(this.info.p2);
                    if (far && this.info) far.value = round(this.info.p98);
                    this._render();
                });
            }
        }

        _bindReadout() {
            if (!this.stage || !this.readout) return;
            this.stage.addEventListener('mousemove', (e) => {
                const rect = this.overlay.getBoundingClientRect();
                if (!rect.width || !rect.height) return;
                const u = (e.clientX - rect.left) / rect.width;
                const v = (e.clientY - rect.top) / rect.height;
                if (!this.parsed) {
                    this.readout.textContent = 'Loading depth values…';
                    return;
                }
                this.readout.textContent = formatDepth(depthAt(this.parsed, u, v));
            });
            this.stage.addEventListener('mouseleave', () => {
                this.readout.textContent = '—';
            });
        }

        _value(selector) {
            const el = this.element.querySelector(selector);
            if (!el || el.value === '') return null;
            const n = Number(el.value);
            return Number.isFinite(n) ? n : null;
        }

        _selected(selector) {
            const el = this.element.querySelector(selector);
            return el ? el.value : null;
        }

        _opacity() {
            const el = this.element.querySelector('.depth-opacity');
            if (!el) return this.config.overlayOpacity;
            return Math.max(0, Math.min(1, Number(el.value) / 100));
        }

        async _errorText(response) {
            try {
                return (await response.json()).error || `HTTP ${response.status}`;
            } catch (_e) {
                return `HTTP ${response.status}`;
            }
        }

        _fail(message) {
            if (this.loading) {
                this.loading.hidden = false;
                this.loading.textContent = message;
                this.loading.classList.add('depth-error');
            }
        }

        _note(message) {
            let note = this.element.querySelector('.depth-note');
            if (!note) {
                note = document.createElement('p');
                note.className = 'depth-note';
                this.element.appendChild(note);
            }
            note.textContent = message;
        }
    }

    function round(v) {
        return Math.round(v * 100) / 100;
    }

    /** Quote a value for an attribute selector. `CSS.escape` where available. */
    function cssEscape(value) {
        if (typeof CSS !== 'undefined' && CSS.escape) return CSS.escape(value);
        return String(value).replace(/["\\]/g, '\\$&');
    }

    function initAll() {
        document.querySelectorAll('.depth-display').forEach((el) => {
            if (el.depthViewer) return;
            const viewer = new DepthViewer(el);
            el.depthViewer = viewer;
            viewer.init();
        });
    }

    DepthViewer.parseDepthWire = parseDepthWire;
    DepthViewer.depthAt = depthAt;
    DepthViewer.formatDepth = formatDepth;
    DepthViewer.buildUrl = buildUrl;
    DepthViewer.initAll = initAll;

    if (typeof module !== 'undefined' && module.exports) {
        module.exports = DepthViewer;
    }
    if (root) {
        root.DepthViewer = DepthViewer;
        if (typeof document !== 'undefined') {
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', initAll);
            } else {
                initAll();
            }
        }
    }
})(typeof window !== 'undefined' ? window
    : (typeof globalThis !== 'undefined' ? globalThis : null));

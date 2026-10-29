/*
 * volume_annotation: three linked slice views of a 3D medical volume, with
 * per-label brush masks, boxes and polygons.
 *
 * The server renders slices (potato/media/volumes.py); this file paints the
 * overlays and keeps the annotation. Voxel indices (i, j, k) are in the
 * volume's canonical RAS+ orientation and every view maps screen pixels to
 * them exactly as volumes.py documents:
 *
 *   axial    (k fixed): row r -> j = nJ-1-r, column c -> i = nI-1-c
 *   coronal  (j fixed): row r -> k = nK-1-r, column c -> i = nI-1-c
 *   sagittal (i fixed): row r -> k = nK-1-r, column c -> j = nJ-1-c
 *
 * Masks are kept per label as a map from axial slice k to a Uint8Array of
 * nJ*nI (row j, column i), and stored run-length encoded in the same layout
 * (see volume_masks.py). Painting on a coronal or sagittal view writes into
 * the axial slices it crosses.
 */
(function (root) {
    'use strict';

    // -- run-length encoding (mirrors potato/media/volume_masks.py) --------

    function rleEncode(arr) {
        const counts = [];
        let current = 0, run = 0;
        for (let n = 0; n < arr.length; n++) {
            const v = arr[n] ? 1 : 0;
            if (v === current) { run++; continue; }
            counts.push(run);
            current = v;
            run = 1;
        }
        counts.push(run);
        return counts;
    }

    function rleDecode(counts, size) {
        const out = new Uint8Array(size);
        let pos = 0, value = 0;
        for (const c of counts || []) {
            if (value) out.fill(1, pos, Math.min(size, pos + c));
            pos += c;
            value = 1 - value;
        }
        return out;
    }

    function hexToRgb(hex) {
        const m = /^#?([0-9a-f]{6})$/i.exec(String(hex || ''));
        const n = m ? parseInt(m[1], 16) : 0xe6553a;
        return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
    }

    /** Ray casting: whether (x, y) is inside the polygon ``points``. */
    function polygonContains(points, x, y) {
        let inside = false;
        for (let a = 0, b = points.length - 1; a < points.length; b = a++) {
            const [xa, ya] = points[a], [xb, yb] = points[b];
            if ((ya > y) !== (yb > y) && x < (xb - xa) * (y - ya) / (yb - ya) + xa) {
                inside = !inside;
            }
        }
        return inside;
    }

    class VolumeAnnotationManager {
        constructor(container, inputId, config) {
            this.container = container;
            this.input = document.getElementById(inputId);
            this.config = config;
            this.labels = config.labels || [];
            this.label = this.labels.length ? this.labels[0].name : null;
            this.tool = 'navigate';
            this.masks = {};          // label -> Map(k -> Uint8Array)
            this.shapes = [];         // {label, axis, index, type, points: [[i,j,k]...]}
            this.history = [];
            this.views = {};
            this.cursor = {i: 0, j: 0, k: 0};
            this.window = {center: 40, width: 400};
            this._hydrating = false;
            this.prefilledFrom = null;
        }

        // -- startup -------------------------------------------------------

        async init() {
            this.path = this._volumePath();
            if (!this.path) {
                this._status(`This item has no "${this.config.sourceField}" field naming a volume.`, 'error');
                return;
            }
            const response = await fetch(this._url({info: 1, schema: this.config.schema}));
            const info = await response.json().catch(() => ({}));
            if (!response.ok) {
                this._status(info.error || `The volume could not be loaded (${response.status}).`, 'error');
                return;
            }
            this.info = info;
            [this.nI, this.nJ, this.nK] = info.shape;
            [this.dI, this.dJ, this.dK] = info.spacing;
            this.cursor = {i: Math.floor(this.nI / 2), j: Math.floor(this.nJ / 2),
                           k: Math.floor(this.nK / 2)};
            this._setupWindows(info.windows || []);
            this._renderTags(info.tags || {});
            this._bindToolbar();
            this._buildViews();
            this._restoreFromInput();
            if (!this._hasAnything() && this.config.prefillField) {
                await this._prefill();
            }
            this._selectLabel(this.label);
            this._selectTool('navigate');
            this._refreshAll();
            document.addEventListener('potato:themechange', () => this._refreshOverlays());
            window.addEventListener('resize', () => this._layout());
        }

        _record() {
            try {
                const el = document.querySelector('[data-instance-json]');
                return el ? JSON.parse(el.getAttribute('data-instance-json')) || {} : {};
            } catch (err) {
                return {};
            }
        }

        _volumePath() {
            const value = this._record()[this.config.sourceField || 'volume'];
            return typeof value === 'string' && value.trim() ? value.trim() : null;
        }

        _url(params) {
            const query = new URLSearchParams(params).toString();
            const path = this.path.split('/').map(encodeURIComponent).join('/');
            return `/media/volume/${path}?${query}`;
        }

        _status(text, kind) {
            const el = this.container.querySelector('.vol-status');
            if (!el) return;
            el.textContent = text || '';
            if (kind) el.setAttribute('data-kind', kind); else el.removeAttribute('data-kind');
        }

        _setupWindows(windows) {
            // The schema's own presets first: a NIfTI file has no modality
            // header to pick CT or MR presets from.
            windows = (this.config.windowPresets || []).concat(windows);
            this.windows = windows;
            const select = this.container.querySelector('.vol-window-select');
            if (!select) return;
            select.innerHTML = '';
            windows.forEach((w, n) => {
                const option = document.createElement('option');
                option.value = String(n);
                option.textContent = `${w.name} (${Math.round(w.center)}/${Math.round(w.width)})`;
                select.appendChild(option);
            });
            let chosen = 0;
            if (this.config.defaultWindow) {
                const found = windows.findIndex(w => w.name.toLowerCase()
                    === String(this.config.defaultWindow).toLowerCase());
                if (found >= 0) chosen = found;
            }
            select.value = String(chosen);
            if (windows[chosen]) this.window = {center: windows[chosen].center, width: windows[chosen].width};
            select.addEventListener('change', () => {
                const w = windows[Number(select.value)];
                if (w) {
                    this.window = {center: w.center, width: w.width};
                    this._refreshImages();
                }
            });
        }

        _renderTags(tags) {
            const list = this.container.querySelector('.vol-tags');
            if (!list) return;
            const entries = Object.entries(tags);
            list.hidden = entries.length === 0;
            list.innerHTML = '';
            for (const [key, value] of entries) {
                const dt = document.createElement('dt');
                dt.textContent = key.replace(/([a-z])([A-Z])/g, '$1 $2');
                const dd = document.createElement('dd');
                dd.textContent = value;
                list.append(dt, dd);
            }
        }

        _bindToolbar() {
            this.container.querySelectorAll('[data-tool]').forEach(button => {
                button.addEventListener('click', () => this._selectTool(button.dataset.tool));
            });
            this.container.querySelectorAll('.vol-label-btn').forEach(button => {
                button.addEventListener('click', () => this._selectLabel(button.dataset.label));
            });
            const interp = this.container.querySelector('[data-action="interpolate"]');
            if (interp) interp.addEventListener('click', () => this.interpolate());
            const undo = this.container.querySelector('[data-action="undo"]');
            if (undo) undo.addEventListener('click', () => this.undo());
            this.brushInput = this.container.querySelector('.vol-brush-size');
            this.container.addEventListener('keydown', event => this._onKey(event));
        }

        _selectTool(tool) {
            if (!(this.config.tools || []).includes(tool)) return;
            this.tool = tool;
            this._polygon = null;
            this.container.querySelectorAll('[data-tool]').forEach(b =>
                b.setAttribute('aria-pressed', b.dataset.tool === tool ? 'true' : 'false'));
            this.container.setAttribute('data-active-tool', tool);
            this._refreshOverlays();
        }

        _selectLabel(name) {
            if (!this.labels.some(l => l.name === name)) return;
            this.label = name;
            this.container.querySelectorAll('.vol-label-btn').forEach(b =>
                b.setAttribute('aria-pressed', b.dataset.label === name ? 'true' : 'false'));
        }

        _onKey(event) {
            if (event.target.matches('input, select, textarea')) return;
            const key = event.key;
            if ((event.ctrlKey || event.metaKey) && key.toLowerCase() === 'z') {
                event.preventDefault();
                this.undo();
                return;
            }
            if (event.ctrlKey || event.metaKey || event.altKey) return;
            const view = this._focusedView();
            if (view && (key === 'ArrowUp' || key === 'ArrowDown' || key === 'PageUp' || key === 'PageDown')) {
                event.preventDefault();
                this._step(view.axis, (key === 'ArrowUp' || key === 'PageUp') ? 1 : -1);
                return;
            }
            if (key === 'Escape' && this._polygon) { this._polygon = null; this._refreshOverlays(); return; }
            if (key === 'Enter' && this._polygon) { this._closePolygon(); event.preventDefault(); return; }
            if (key === 'i') { this.interpolate(); return; }
            for (const [tool, k] of Object.entries(this.config.toolKeys || {})) {
                if (k === key) { this._selectTool(tool); return; }
            }
            const label = this.labels.find(l => l.key_value && String(l.key_value) === key);
            if (label) this._selectLabel(label.name);
        }

        _focusedView() {
            const active = document.activeElement;
            for (const view of Object.values(this.views)) {
                if (view.stage === active || view.stage.contains(active)) return view;
            }
            return this.views.axial || Object.values(this.views)[0];
        }

        // -- views ---------------------------------------------------------

        _dims(axis) {
            // [columns, rows, column mm, row mm, slice count]
            if (axis === 'axial') return [this.nI, this.nJ, this.dI, this.dJ, this.nK];
            if (axis === 'coronal') return [this.nI, this.nK, this.dI, this.dK, this.nJ];
            return [this.nJ, this.nK, this.dJ, this.dK, this.nI];
        }

        _index(axis) {
            return axis === 'axial' ? this.cursor.k : axis === 'coronal' ? this.cursor.j : this.cursor.i;
        }

        _setIndex(axis, value) {
            const [, , , , count] = this._dims(axis);
            const v = Math.max(0, Math.min(count - 1, Math.round(value)));
            if (axis === 'axial') this.cursor.k = v;
            else if (axis === 'coronal') this.cursor.j = v;
            else this.cursor.i = v;
        }

        _buildViews() {
            this.container.querySelectorAll('.vol-view').forEach(el => {
                const axis = el.dataset.axis;
                const view = {
                    axis, el,
                    stage: el.querySelector('.vol-stage'),
                    image: el.querySelector('.vol-image'),
                    overlay: el.querySelector('.vol-overlay'),
                    slider: el.querySelector('.vol-slider'),
                    label: el.querySelector('.vol-slice-label'),
                    img: new Image(),
                };
                const [, , , , count] = this._dims(axis);
                view.slider.max = String(count - 1);
                view.slider.addEventListener('input', () => {
                    this._setIndex(axis, Number(view.slider.value));
                    this._refreshView(view);
                    this._refreshCrosshairs();
                });
                view.img.onload = () => this._drawImage(view);
                view.stage.addEventListener('wheel', event => {
                    event.preventDefault();
                    this._step(axis, event.deltaY < 0 ? 1 : -1);
                }, {passive: false});
                view.overlay.addEventListener('pointerdown', e => this._pointerDown(view, e));
                view.overlay.addEventListener('pointermove', e => this._pointerMove(view, e));
                view.overlay.addEventListener('pointerup', e => this._pointerUp(view, e));
                view.overlay.addEventListener('pointercancel', e => this._pointerUp(view, e));
                view.overlay.addEventListener('dblclick', () => { if (this._polygon) this._closePolygon(); });
                view.overlay.addEventListener('contextmenu', e => e.preventDefault());
                this.views[axis] = view;
            });
            this._layout();
        }

        _layout() {
            for (const view of Object.values(this.views)) {
                const [cols, rows, cmm, rmm] = this._dims(view.axis);
                const available = Math.max(160, view.stage.clientWidth || 300);
                const aspect = (rows * rmm) / (cols * cmm);
                const width = Math.round(available);
                const height = Math.round(available * aspect);
                for (const canvas of [view.image, view.overlay]) {
                    canvas.width = width;
                    canvas.height = height;
                    canvas.style.height = `${height}px`;
                }
                view.stage.style.height = `${height}px`;
                if (view.img.complete && view.img.naturalWidth) this._drawImage(view);
            }
            this._refreshOverlays();
        }

        _step(axis, delta) {
            this._setIndex(axis, this._index(axis) + delta);
            const view = this.views[axis];
            if (view) this._refreshView(view);
            this._refreshCrosshairs();
        }

        _refreshAll() {
            for (const view of Object.values(this.views)) this._refreshView(view);
        }

        _refreshImages() {
            clearTimeout(this._imageTimer);
            this._imageTimer = setTimeout(() => {
                for (const view of Object.values(this.views)) this._loadImage(view);
            }, 60);
        }

        _refreshOverlays() {
            for (const view of Object.values(this.views)) this._drawOverlay(view);
        }

        _refreshCrosshairs() { this._refreshOverlays(); }

        _refreshView(view) {
            const index = this._index(view.axis);
            const [, , , , count] = this._dims(view.axis);
            view.slider.value = String(index);
            view.label.textContent = `${index + 1} / ${count}`;
            this._loadImage(view);
            this._drawOverlay(view);
        }

        _loadImage(view) {
            view.img.src = this._url({axis: view.axis, index: this._index(view.axis),
                                      wc: this.window.center.toFixed(1),
                                      ww: this.window.width.toFixed(1)});
        }

        _drawImage(view) {
            const ctx = view.image.getContext('2d');
            ctx.imageSmoothingEnabled = false;
            ctx.fillStyle = '#000';
            ctx.fillRect(0, 0, view.image.width, view.image.height);
            ctx.drawImage(view.img, 0, 0, view.image.width, view.image.height);
        }

        // -- coordinates ---------------------------------------------------

        _toVoxel(view, col, row) {
            const index = this._index(view.axis);
            if (view.axis === 'axial') return [this.nI - 1 - col, this.nJ - 1 - row, index];
            if (view.axis === 'coronal') return [this.nI - 1 - col, index, this.nK - 1 - row];
            return [index, this.nJ - 1 - col, this.nK - 1 - row];
        }

        _toScreen(view, i, j, k) {
            if (view.axis === 'axial') return [this.nI - 1 - i, this.nJ - 1 - j];
            if (view.axis === 'coronal') return [this.nI - 1 - i, this.nK - 1 - k];
            return [this.nJ - 1 - j, this.nK - 1 - k];
        }

        _eventCell(view, event) {
            const rect = view.overlay.getBoundingClientRect();
            const [cols, rows] = this._dims(view.axis);
            const col = (event.clientX - rect.left) / rect.width * cols;
            const row = (event.clientY - rect.top) / rect.height * rows;
            return [col, row];
        }

        // -- masks ---------------------------------------------------------

        _slice(label, k, create) {
            let map = this.masks[label];
            if (!map) {
                if (!create) return null;
                map = this.masks[label] = new Map();
            }
            let plane = map.get(k);
            if (!plane && create) {
                plane = new Uint8Array(this.nI * this.nJ);
                map.set(k, plane);
            }
            return plane || null;
        }

        _snapshot() {
            const copy = {};
            for (const [label, map] of Object.entries(this.masks)) {
                copy[label] = new Map([...map].map(([k, plane]) => [k, plane.slice()]));
            }
            this.history.push({masks: copy, shapes: JSON.parse(JSON.stringify(this.shapes))});
            if (this.history.length > 30) this.history.shift();
        }

        undo() {
            const last = this.history.pop();
            if (!last) return;
            this.masks = last.masks;
            this.shapes = last.shapes;
            this._refreshOverlays();
            this._save();
        }

        _paint(view, col, row, erase) {
            if (!this.label) return;
            const radius = Number(this.brushInput ? this.brushInput.value : this.config.brushSize) || 2;
            const [, , cmm, rmm] = this._dims(view.axis);
            const unit = Math.min(cmm, rmm);
            const rc = radius * unit / cmm, rr = radius * unit / rmm;
            const [cols, rows] = this._dims(view.axis);
            for (let r = Math.floor(row - rr); r <= Math.ceil(row + rr); r++) {
                if (r < 0 || r >= rows) continue;
                for (let c = Math.floor(col - rc); c <= Math.ceil(col + rc); c++) {
                    if (c < 0 || c >= cols) continue;
                    const dc = (c + 0.5 - col) / rc, dr = (r + 0.5 - row) / rr;
                    if (dc * dc + dr * dr > 1) continue;
                    const [i, j, k] = this._toVoxel(view, c, r);
                    const plane = this._slice(this.label, k, !erase);
                    if (plane) plane[j * this.nI + i] = erase ? 0 : 1;
                }
            }
        }

        _pointerDown(view, event) {
            view.stage.focus();
            const [col, row] = this._eventCell(view, event);
            if (event.button === 2) {
                this._windowDrag = {x: event.clientX, y: event.clientY,
                                    center: this.window.center, width: this.window.width};
                view.overlay.setPointerCapture(event.pointerId);
                return;
            }
            if (event.button !== 0) return;
            if (this.tool === 'navigate') {
                const [i, j, k] = this._toVoxel(view, Math.floor(col), Math.floor(row));
                this.cursor = {i, j, k};
                this._refreshAll();
                return;
            }
            if (this.tool === 'brush' || this.tool === 'eraser') {
                this._snapshot();
                this._painting = view;
                view.overlay.setPointerCapture(event.pointerId);
                this._paint(view, col, row, this.tool === 'eraser');
                this._drawOverlay(view);
                return;
            }
            if (this.tool === 'box') {
                this._box = {view, start: [col, row], end: [col, row]};
                view.overlay.setPointerCapture(event.pointerId);
                return;
            }
            if (this.tool === 'polygon') {
                if (!this._polygon || this._polygon.view !== view) {
                    this._polygon = {view, index: this._index(view.axis), points: []};
                }
                this._polygon.points.push([col, row]);
                this._drawOverlay(view);
            }
        }

        _pointerMove(view, event) {
            if (this._windowDrag) {
                const dx = event.clientX - this._windowDrag.x;
                const dy = event.clientY - this._windowDrag.y;
                const scale = Math.max(1, this._windowDrag.width) / 200;
                this.window = {center: this._windowDrag.center - dy * scale,
                               width: Math.max(1, this._windowDrag.width + dx * scale)};
                this._refreshImages();
                return;
            }
            const [col, row] = this._eventCell(view, event);
            if (this._painting === view) {
                this._paint(view, col, row, this.tool === 'eraser');
                this._drawOverlay(view);
            } else if (this._box && this._box.view === view) {
                this._box.end = [col, row];
                this._drawOverlay(view);
            }
        }

        _pointerUp(view) {
            if (this._windowDrag) { this._windowDrag = null; return; }
            if (this._painting === view) {
                this._painting = null;
                this._refreshOverlays();
                this._save();
            }
            if (this._box && this._box.view === view) {
                const {start, end} = this._box;
                this._box = null;
                if (Math.abs(end[0] - start[0]) >= 1 && Math.abs(end[1] - start[1]) >= 1) {
                    this._snapshot();
                    this.shapes.push(this._shape(view, 'box', [start, end]));
                    this._renderShapeList();
                    this._save();
                }
                this._drawOverlay(view);
            }
        }

        _closePolygon() {
            const poly = this._polygon;
            this._polygon = null;
            if (poly && poly.points.length >= 3 && this.label) {
                this._snapshot();
                // A closed polygon paints its region into the label's mask on
                // this slice. Stored as a shape, it reached neither the NIfTI
                // nor the DICOM SEG mask nor Dice, though on a segmentation
                // scheme it reads as a way to paint a region.
                this._fillPolygon(poly.view, poly.points);
                this._save();
            }
            this._refreshOverlays();
        }

        /** Set every cell whose centre is inside ``points`` (screen cells). */
        _fillPolygon(view, points) {
            const [cols, rows] = this._dims(view.axis);
            const xs = points.map(p => p[0]), ys = points.map(p => p[1]);
            const c0 = Math.max(0, Math.floor(Math.min(...xs)));
            const c1 = Math.min(cols - 1, Math.ceil(Math.max(...xs)));
            const r0 = Math.max(0, Math.floor(Math.min(...ys)));
            const r1 = Math.min(rows - 1, Math.ceil(Math.max(...ys)));
            let filled = 0;
            for (let r = r0; r <= r1; r++) {
                const y = r + 0.5;
                for (let c = c0; c <= c1; c++) {
                    if (!polygonContains(points, c + 0.5, y)) continue;
                    const [i, j, k] = this._toVoxel(view, c, r);
                    const plane = this._slice(this.label, k, true);
                    plane[j * this.nI + i] = 1;
                    filled++;
                }
            }
            return filled;
        }

        _shape(view, type, screenPoints) {
            return {
                label: this.label, axis: view.axis, index: this._index(view.axis), type,
                points: screenPoints.map(([c, r]) => {
                    const [i, j, k] = this._toVoxel(view, c, r);
                    return [Math.round(i * 100) / 100, Math.round(j * 100) / 100,
                            Math.round(k * 100) / 100];
                }),
            };
        }

        _renderShapeList() {
            const list = this.container.querySelector('.vol-shapes');
            if (!list) return;
            list.innerHTML = '';
            this.shapes.forEach((shape, n) => {
                const item = document.createElement('li');
                const go = document.createElement('button');
                go.type = 'button';
                go.className = 'vol-shape-go';
                go.textContent = `${shape.label}: ${shape.type} on ${shape.axis} ${shape.index + 1}`;
                go.addEventListener('click', () => {
                    this._setIndex(shape.axis, shape.index);
                    this._refreshAll();
                });
                const remove = document.createElement('button');
                remove.type = 'button';
                remove.className = 'vol-shape-remove';
                remove.textContent = 'Remove';
                remove.setAttribute('aria-label', `Remove ${go.textContent}`);
                remove.addEventListener('click', () => {
                    this._snapshot();
                    this.shapes.splice(n, 1);
                    this._renderShapeList();
                    this._refreshOverlays();
                    this._save();
                });
                item.append(go, remove);
                list.appendChild(item);
            });
        }

        // -- overlays ------------------------------------------------------

        _drawOverlay(view) {
            const canvas = view.overlay;
            const ctx = canvas.getContext('2d');
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            const [cols, rows] = this._dims(view.axis);
            const index = this._index(view.axis);
            const sx = canvas.width / cols, sy = canvas.height / rows;

            // Masks, drawn at voxel resolution then scaled.
            const image = new ImageData(cols, rows);
            let any = false;
            for (const label of this.labels) {
                const map = this.masks[label.name];
                if (!map || !map.size) continue;
                const [red, green, blue] = hexToRgb(label.color);
                for (let r = 0; r < rows; r++) {
                    for (let c = 0; c < cols; c++) {
                        const [i, j, k] = this._toVoxel(view, c, r);
                        const plane = map.get(k);
                        if (!plane || !plane[j * this.nI + i]) continue;
                        const p = (r * cols + c) * 4;
                        image.data[p] = red; image.data[p + 1] = green; image.data[p + 2] = blue;
                        image.data[p + 3] = 110;
                        any = true;
                    }
                }
            }
            if (any) {
                const scratch = this._scratch || (this._scratch = document.createElement('canvas'));
                scratch.width = cols; scratch.height = rows;
                scratch.getContext('2d').putImageData(image, 0, 0);
                ctx.imageSmoothingEnabled = false;
                ctx.drawImage(scratch, 0, 0, canvas.width, canvas.height);
            }

            // Boxes and polygons on this slice.
            ctx.lineWidth = 2;
            for (const shape of this.shapes) {
                if (shape.axis !== view.axis || shape.index !== index) continue;
                const label = this.labels.find(l => l.name === shape.label);
                ctx.strokeStyle = label ? label.color : '#e6553a';
                const pts = shape.points.map(([i, j, k]) => this._toScreen(view, i, j, k));
                ctx.beginPath();
                if (shape.type === 'box') {
                    const [a, b] = pts;
                    ctx.rect(Math.min(a[0], b[0]) * sx, Math.min(a[1], b[1]) * sy,
                             Math.abs(b[0] - a[0]) * sx, Math.abs(b[1] - a[1]) * sy);
                } else {
                    pts.forEach(([c, r], n) => n ? ctx.lineTo(c * sx, r * sy) : ctx.moveTo(c * sx, r * sy));
                    ctx.closePath();
                }
                ctx.stroke();
            }
            if (this._box && this._box.view === view) {
                const {start, end} = this._box;
                ctx.setLineDash([4, 3]);
                ctx.strokeStyle = '#ffffff';
                ctx.strokeRect(Math.min(start[0], end[0]) * sx, Math.min(start[1], end[1]) * sy,
                               Math.abs(end[0] - start[0]) * sx, Math.abs(end[1] - start[1]) * sy);
                ctx.setLineDash([]);
            }
            if (this._polygon && this._polygon.view === view) {
                ctx.strokeStyle = '#ffffff';
                ctx.beginPath();
                this._polygon.points.forEach(([c, r], n) =>
                    n ? ctx.lineTo(c * sx, r * sy) : ctx.moveTo(c * sx, r * sy));
                ctx.stroke();
            }

            // Crosshair: where the other two views cut this one.
            const [ci, cj, ck] = [this.cursor.i, this.cursor.j, this.cursor.k];
            const [hc, hr] = this._toScreen(view, ci, cj, ck);
            ctx.strokeStyle = 'rgba(250, 204, 21, 0.55)';
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo((hc + 0.5) * sx, 0); ctx.lineTo((hc + 0.5) * sx, canvas.height);
            ctx.moveTo(0, (hr + 0.5) * sy); ctx.lineTo(canvas.width, (hr + 0.5) * sy);
            ctx.stroke();
        }

        // -- interpolation and prefill --------------------------------------

        async interpolate() {
            const map = this.masks[this.label];
            if (!map || map.size < 2) {
                this._status(`Paint ${this.label} on at least two axial slices to interpolate between them.`);
                return;
            }
            const slices = {};
            for (const [k, plane] of map) if (plane.some(v => v)) slices[k] = rleEncode(plane);
            const response = await fetch('/media/volume-tools/interpolate', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({shape: [this.nI, this.nJ, this.nK], slices}),
            });
            const body = await response.json().catch(() => ({}));
            if (!response.ok) {
                this._status(body.error || 'Interpolation failed.', 'error');
                return;
            }
            const filled = Object.entries(body.filled || {});
            // Outlines that do not overlap blend to nothing in the middle;
            // say so rather than leaving an unexplained hole.
            const gaps = (body.gaps || []).map(g => {
                const span = g.empty.length > 1
                    ? `${g.empty[0] + 1}–${g.empty[g.empty.length - 1] + 1}` : `${g.empty[0] + 1}`;
                return `slice${g.empty.length > 1 ? 's' : ''} ${span} left empty: the outlines `
                    + `on ${g.from + 1} and ${g.to + 1} do not overlap; paint one between them`;
            });
            if (!filled.length) {
                this._status(gaps.length ? `Nothing filled: ${gaps.join('; ')}.`
                    : 'Nothing to fill: the painted slices have no gaps between them.');
                return;
            }
            this._snapshot();
            for (const [k, counts] of filled) {
                map.set(Number(k), rleDecode(counts, this.nI * this.nJ));
            }
            this._status(`Filled ${filled.length} slice${filled.length === 1 ? '' : 's'} of ${this.label}. `
                + (gaps.length ? `${gaps.join('; ')}. ` : '') + 'Undo removes them.');
            this._refreshOverlays();
            this._save();
        }

        async _prefill() {
            const rtstruct = this._record()[this.config.prefillField];
            if (typeof rtstruct !== 'string' || !rtstruct) return;
            const query = new URLSearchParams({volume: this.path, rtstruct,
                                               schema: this.config.schema});
            const response = await fetch(`/media/volume-tools/prefill?${query}`);
            const body = await response.json().catch(() => ({}));
            if (!response.ok) {
                this._status(body.error || 'The RTSTRUCT could not be loaded.', 'error');
                return;
            }
            this._loadMasks(body.masks || {});
            this.prefilledFrom = 'rtstruct';
            const note = (body.unmatched || []).length
                ? ` Not loaded (no label of that name): ${body.unmatched.join(', ')}.` : '';
            this._status(`Started from the item's RTSTRUCT.${note}`);
            // Written but not announced: opening an item is not answering it.
            // The value goes with the next save (Next, or any edit).
            this._hydrating = true;
            try { this._save(); } finally { this._hydrating = false; }
        }

        // -- persistence ---------------------------------------------------

        _loadMasks(stored) {
            for (const [label, slices] of Object.entries(stored || {})) {
                if (!this.labels.some(l => l.name === label)) continue;
                const map = this.masks[label] = new Map();
                for (const [k, counts] of Object.entries(slices || {})) {
                    map.set(Number(k), rleDecode(counts, this.nI * this.nJ));
                }
            }
        }

        _hasAnything() {
            return this.shapes.length > 0
                || Object.values(this.masks).some(map => [...map.values()].some(p => p.some(v => v)));
        }

        _restoreFromInput() {
            if (!this.input || !this.input.value) return;
            this._hydrating = true;
            try {
                const data = JSON.parse(this.input.value);
                this._loadMasks(data.masks || {});
                this.shapes = Array.isArray(data.shapes) ? data.shapes : [];
                this.prefilledFrom = data.prefilled_from || null;
                this._renderShapeList();
            } catch (err) {
                console.warn('[volume] stored annotation could not be read', err);
            } finally {
                this._hydrating = false;
            }
        }

        serialize() {
            const masks = {};
            for (const [label, map] of Object.entries(this.masks)) {
                const slices = {};
                for (const [k, plane] of [...map].sort((a, b) => a[0] - b[0])) {
                    if (plane.some(v => v)) slices[String(k)] = rleEncode(plane);
                }
                if (Object.keys(slices).length) masks[label] = slices;
            }
            const out = {volume: this.path, shape: [this.nI, this.nJ, this.nK],
                         labels: this.labels.map(l => l.name), masks, shapes: this.shapes};
            if (this.prefilledFrom) out.prefilled_from = this.prefilledFrom;
            return out;
        }

        _save() {
            if (!this.input) return;
            this.input.value = JSON.stringify(this.serialize());
            this.input.setAttribute('data-modified', 'true');
            if (!this._hydrating) {
                this.input.dispatchEvent(new Event('change', {bubbles: true}));
            }
        }
    }

    root.VolumeAnnotationManager = VolumeAnnotationManager;
    root.VolumeAnnotationRLE = {encode: rleEncode, decode: rleDecode};
})(typeof window !== 'undefined' ? window : globalThis);

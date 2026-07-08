/**
 * PDF Link Mode
 *
 * Multi-page PDF annotation with two kinds of linkable *anchors*:
 *   - text spans  (highlight text on a page)
 *   - region bboxes (draw a box around a figure/image/non-text region)
 * Anchors on any pages can be linked together (text<->text, text<->region,
 * region<->region), including across pages, and the links are drawn as SVG
 * arcs over a single overlay spanning the whole page stack.
 *
 * Self-contained: it loads PDF.js, renders every page (scroll) or a browsable
 * page (paginated), and persists through the standard endpoints:
 *   - anchors  -> POST /updateinstance {span_annotations:[...]}  (+ /api/spans)
 *   - links    -> POST /updateinstance {link_annotations:[...]}  (+ /api/links)
 * Anchor geometry rides in SpanAnnotation.format_coords
 *   {format:'pdf', anchor_kind, page, bbox:[x,y,w,h] normalized 0-1, start, end}
 * so it round-trips without any new backend model (see routes.update_instance).
 */
(function () {
    'use strict';

    // PDF.js is vendored locally so PDF annotation works on offline / air-gapped
    // deployments; the CDN is only a fallback if the local copy is missing.
    const PDFJS_LOCAL = '/static/vendor/pdfjs';
    const PDFJS_CDN = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174';

    // Distinct, consistent colors for anchor labels (hash-based, matches the
    // palette philosophy in pdf-bbox.js so the two modes feel related).
    const LABEL_COLORS = [
        '#e74c3c', '#3498db', '#2ecc71', '#9b59b6', '#f39c12', '#1abc9c',
        '#e91e63', '#00bcd4', '#ff5722', '#607d8b', '#8bc34a', '#673ab7',
    ];
    const _labelColorCache = {};
    function labelColor(label, override) {
        if (override) return override;
        if (!label) return '#0066cc';
        if (_labelColorCache[label]) return _labelColorCache[label];
        let hash = 0;
        for (let i = 0; i < label.length; i++) {
            hash = ((hash << 5) - hash) + label.charCodeAt(i);
            hash = hash & hash;
        }
        const c = LABEL_COLORS[Math.abs(hash) % LABEL_COLORS.length];
        _labelColorCache[label] = c;
        return c;
    }

    function uid(prefix) {
        // Avoids Date.now/random determinism concerns are irrelevant client-side,
        // but keep ids readable and unique enough within an instance.
        return `${prefix}_${Math.random().toString(36).slice(2, 10)}${(performance.now() | 0)}`;
    }

    function _injectScript(src) {
        return new Promise((resolve, reject) => {
            const s = document.createElement('script');
            s.src = src;
            s.onload = () => resolve();
            s.onerror = () => reject(new Error('Failed to load ' + src));
            document.head.appendChild(s);
        });
    }

    let _pdfjsLoading = null;
    function loadPDFJS() {
        if (window.pdfjsLib) return Promise.resolve();
        if (_pdfjsLoading) return _pdfjsLoading;
        _pdfjsLoading = (async () => {
            // Prefer the vendored copy; fall back to the CDN if it 404s.
            try {
                await _injectScript(`${PDFJS_LOCAL}/pdf.min.js`);
                window.pdfjsLib.GlobalWorkerOptions.workerSrc = `${PDFJS_LOCAL}/pdf.worker.min.js`;
            } catch (localErr) {
                console.warn('[PdfLinkMode] local PDF.js unavailable, using CDN', localErr);
                await _injectScript(`${PDFJS_CDN}/pdf.min.js`);
                window.pdfjsLib.GlobalWorkerOptions.workerSrc = `${PDFJS_CDN}/pdf.worker.min.js`;
            }
        })();
        return _pdfjsLoading;
    }

    class PdfLinkMode {
        constructor(container) {
            this.container = container;
            this.fieldKey = container.dataset.fieldKey || 'pdf';
            this.pdfSource = container.dataset.pdfSource || '';
            this.viewMode = container.dataset.viewMode || 'scroll';
            this.zoom = container.dataset.zoom || 'auto';

            let cfg = {};
            try { cfg = JSON.parse(container.dataset.linkConfig || '{}'); } catch (e) { cfg = {}; }
            this.anchorSchema = cfg.anchor_schema || 'pdf_anchors';
            this.linkSchema = cfg.link_schema || 'pdf_links';
            this.anchorLabels = (cfg.anchor_labels && cfg.anchor_labels.length)
                ? cfg.anchor_labels : [{ name: 'anchor' }];
            this.linkTypes = (cfg.link_types && cfg.link_types.length)
                ? cfg.link_types : [{ name: 'related_to', directed: false }];
            this.enableText = cfg.enable_text_anchors !== false;
            this.enableRegion = cfg.enable_region_anchors !== false;
            this.showSidebar = !!cfg.thumbnail_sidebar && this.viewMode === 'paginated';

            // OCR word layer for scanned PDFs (keyed by page number as string):
            // [{text, start, end, bbox:[x0,top,x1,bottom] in PDF points}].
            this.ocrPages = {};
            try { this.ocrPages = JSON.parse(container.dataset.ocrPages || '{}'); }
            catch (e) { this.ocrPages = {}; }

            // DOM refs
            this.toolbarEl = container.querySelector('.pdf-link-toolbar');
            this.bodyEl = container.querySelector('.pdf-link-body');
            this.sidebarEl = container.querySelector('.pdf-thumbnail-sidebar');
            this.scrollEl = container.querySelector('.pdf-pages-scroll');
            this.stackEl = container.querySelector('.pdf-pages-stack');
            this.overlaySvg = container.querySelector('.pdf-link-overlay');
            this.loadingEl = container.querySelector('.pdf-loading');
            this.errorEl = container.querySelector('.pdf-error');

            // State
            this.pdfDoc = null;
            this.totalPages = 0;
            this.currentPage = 1;               // paginated: page currently shown
            this.pages = {};                    // pageNum -> page render record
            this.anchors = new Map();           // id -> anchor
            this.links = [];                    // [{id, schema, link_type, span_ids, direction, properties}]
            this.currentLabel = this.anchorLabels[0].name;
            this.currentLinkType = this.linkTypes[0].name;
            this.linkModeOn = false;
            this.selectedForLink = [];          // anchor ids selected to link
            this.pinnedSource = null;           // paginated pin-navigate source anchor id
            this.regionArmed = false;           // region-draw tool armed

            this.init();
        }

        async init() {
            try {
                this.buildToolbar();
                await loadPDFJS();
                await this.loadDocument();
                await this.loadAnchors();
                await this.loadLinks();
                this.wireGlobalEvents();
                this.showLoading(false);
            } catch (err) {
                console.error('[PdfLinkMode] init failed:', err);
                this.showError(err.message || String(err));
            }
        }

        // ---- instance / persistence helpers ----
        getInstanceId() {
            return (document.getElementById('instance_id') || {}).value || '';
        }

        showLoading(show) {
            if (this.loadingEl) this.loadingEl.style.display = show ? 'flex' : 'none';
        }

        showError(msg) {
            this.showLoading(false);
            if (this.errorEl) {
                this.errorEl.textContent = 'PDF error: ' + msg;
                this.errorEl.style.display = 'block';
            }
        }

        // ---- document + page rendering ----
        async loadDocument() {
            this.showLoading(true);
            const task = window.pdfjsLib.getDocument(this.pdfSource);
            this.pdfDoc = await task.promise;
            this.totalPages = this.pdfDoc.numPages;

            this.stackEl.innerHTML = '';
            this.pages = {};

            if (this.viewMode === 'paginated') {
                await this.renderPage(this.currentPage);
                if (this.showSidebar) this.renderThumbnails();
            } else {
                for (let p = 1; p <= this.totalPages; p++) {
                    await this.renderPage(p);
                }
            }
            this.renderAllAnchors();
            this.renderArcs();
        }

        _pageScale(page, containerWidth) {
            const vp = page.getViewport({ scale: 1 });
            switch (this.zoom) {
                case 'page-width':
                case 'auto':
                    return Math.max(0.2, (containerWidth - 24) / vp.width);
                case 'page-fit': {
                    const h = this.scrollEl.clientHeight || 600;
                    return Math.min((containerWidth - 24) / vp.width, h / vp.height);
                }
                default: {
                    const f = parseFloat(this.zoom);
                    return isNaN(f) ? 1.0 : f;
                }
            }
        }

        async renderPage(pageNum) {
            const page = await this.pdfDoc.getPage(pageNum);
            const cw = this.scrollEl.clientWidth || 700;
            const scale = this._pageScale(page, cw);
            const viewport = page.getViewport({ scale });

            // Per-page container: canvas + text layer + region draw layer + anchor overlay
            let rec = this.pages[pageNum];
            if (!rec) {
                const pc = document.createElement('div');
                pc.className = 'pdf-page-container';
                pc.dataset.page = String(pageNum);
                pc.innerHTML =
                    '<div class="pdf-page-number">Page ' + pageNum + '</div>' +
                    '<div class="pdf-page-inner">' +
                    '<canvas class="pdf-page-canvas"></canvas>' +
                    '<div class="pdf-text-layer" data-page="' + pageNum + '"></div>' +
                    '<div class="pdf-region-layer" data-page="' + pageNum + '"></div>' +
                    '<div class="pdf-anchor-overlay" data-page="' + pageNum + '"></div>' +
                    '</div>';
                // keep pages ordered in scroll mode
                const after = Object.keys(this.pages)
                    .map(Number).filter(n => n < pageNum).sort((a, b) => b - a)[0];
                if (after && this.pages[after]) {
                    this.pages[after].container.after(pc);
                } else {
                    this.stackEl.appendChild(pc);
                }
                rec = {
                    container: pc,
                    inner: pc.querySelector('.pdf-page-inner'),
                    canvas: pc.querySelector('.pdf-page-canvas'),
                    textLayer: pc.querySelector('.pdf-text-layer'),
                    regionLayer: pc.querySelector('.pdf-region-layer'),
                    overlay: pc.querySelector('.pdf-anchor-overlay'),
                };
                this.pages[pageNum] = rec;
                this._wirePageInteractions(pageNum, rec);
            }

            const canvas = rec.canvas;
            canvas.width = viewport.width;
            canvas.height = viewport.height;
            rec.inner.style.width = viewport.width + 'px';
            rec.inner.style.height = viewport.height + 'px';
            rec.width = viewport.width;
            rec.height = viewport.height;
            rec.scale = scale;

            await page.render({ canvasContext: canvas.getContext('2d'), viewport }).promise;

            if (this.enableText) this._renderTextLayer(page, viewport, rec);

            // geometry changed -> reposition anchors + arcs for this page
            this._renderAnchorsForPage(pageNum);
            document.dispatchEvent(new CustomEvent('pdf:pagerendered',
                { detail: { page: pageNum, scale, viewport } }));
        }

        async _renderTextLayer(page, viewport, rec) {
            const tc = await page.getTextContent();
            rec.textLayer.innerHTML = '';
            rec.textLayer.style.width = viewport.width + 'px';
            rec.textLayer.style.height = viewport.height + 'px';

            const pageNum = Number(rec.container.dataset.page);
            // Scanned / image-only PDFs have no embedded text; fall back to the
            // server-provided OCR word layer so text anchors still work.
            if ((!tc.items || !tc.items.length) && this.ocrPages[String(pageNum)]) {
                this._buildOcrTextLayer(rec, pageNum);
                return;
            }

            const frag = document.createDocumentFragment();
            // Running per-page char offset so text anchors get stable offsets
            // even when server-side pdfplumber extraction is absent (risk R2).
            let offset = 0;
            tc.items.forEach((item) => {
                const tx = window.pdfjsLib.Util.transform(viewport.transform, item.transform);
                const span = document.createElement('span');
                span.textContent = item.str;
                span.style.left = tx[4] + 'px';
                span.style.top = tx[5] + 'px';
                span.style.fontSize = Math.abs(tx[0]) + 'px';
                span.style.fontFamily = item.fontName || 'sans-serif';
                span.dataset.wordStart = String(offset);
                span.dataset.wordEnd = String(offset + item.str.length);
                offset += item.str.length + 1; // +1 for the implicit whitespace between items
                frag.appendChild(span);
            });
            rec.textLayer.appendChild(frag);
            rec._textOffsetEnd = offset;
        }

        _buildOcrTextLayer(rec, pageNum) {
            // OCR words are in PDF points; canvas pixels = point * page scale.
            const scale = rec.scale || 1;
            const words = this.ocrPages[String(pageNum)] || [];
            const frag = document.createDocumentFragment();
            words.forEach(w => {
                const [x0, top, x1, bottom] = w.bbox;
                const span = document.createElement('span');
                span.textContent = w.text;
                span.style.left = (x0 * scale) + 'px';
                span.style.top = (top * scale) + 'px';
                span.style.width = ((x1 - x0) * scale) + 'px';
                span.style.height = ((bottom - top) * scale) + 'px';
                span.style.fontSize = Math.max(6, (bottom - top) * scale * 0.9) + 'px';
                span.dataset.wordStart = String(w.start);
                span.dataset.wordEnd = String(w.end);
                span.classList.add('pdf-ocr-word');
                frag.appendChild(span);
            });
            rec.textLayer.appendChild(frag);
            rec.textLayer.classList.add('pdf-text-layer-ocr');
        }

        // ---- interactions per page: text selection + region drawing ----
        _wirePageInteractions(pageNum, rec) {
            // Text selection -> text anchor
            if (this.enableText) {
                rec.textLayer.addEventListener('mouseup', () => {
                    if (this.regionArmed) return;
                    // let the browser finish the selection
                    setTimeout(() => this._createTextAnchorFromSelection(pageNum, rec), 0);
                });
            }
            // Region drawing on the region layer (armed via toolbar)
            if (this.enableRegion) {
                this._wireRegionDraw(pageNum, rec);
            }
            // Anchor click (link mode) via delegation on the overlay
            rec.overlay.addEventListener('click', (e) => {
                const el = e.target.closest('.pdf-anchor');
                if (el) this._onAnchorClick(el.dataset.anchorId, e);
            });
        }

        _wireRegionDraw(pageNum, rec) {
            const layer = rec.regionLayer;
            let start = null;
            let rubber = null;
            const toLocal = (e) => {
                const r = rec.inner.getBoundingClientRect();
                return {
                    x: Math.min(Math.max(e.clientX - r.left, 0), rec.width),
                    y: Math.min(Math.max(e.clientY - r.top, 0), rec.height),
                };
            };
            layer.addEventListener('mousedown', (e) => {
                if (!this.regionArmed) return;
                e.preventDefault();
                start = toLocal(e);
                rubber = document.createElement('div');
                rubber.className = 'pdf-region-rubber';
                rubber.style.borderColor = labelColor(this.currentLabel, this._labelOverride(this.currentLabel));
                layer.appendChild(rubber);
            });
            layer.addEventListener('mousemove', (e) => {
                if (!start || !rubber) return;
                const p = toLocal(e);
                const x = Math.min(start.x, p.x), y = Math.min(start.y, p.y);
                const w = Math.abs(p.x - start.x), h = Math.abs(p.y - start.y);
                rubber.style.left = x + 'px';
                rubber.style.top = y + 'px';
                rubber.style.width = w + 'px';
                rubber.style.height = h + 'px';
            });
            const finish = (e) => {
                if (!start || !rubber) return;
                const p = toLocal(e);
                const x = Math.min(start.x, p.x), y = Math.min(start.y, p.y);
                const w = Math.abs(p.x - start.x), h = Math.abs(p.y - start.y);
                rubber.remove();
                rubber = null; start = null;
                if (w < 6 || h < 6) return; // ignore tiny drags
                const bbox = [x / rec.width, y / rec.height, w / rec.width, h / rec.height];
                this.addAnchor({
                    id: uid('anchor'), kind: 'region', page: pageNum,
                    label: this.currentLabel, start: 0, end: 0, bbox,
                }, true);
            };
            layer.addEventListener('mouseup', finish);
            layer.addEventListener('mouseleave', (e) => { if (start) finish(e); });
        }

        _createTextAnchorFromSelection(pageNum, rec) {
            const sel = window.getSelection();
            if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return;
            const range = sel.getRangeAt(0);
            if (!rec.textLayer.contains(range.commonAncestorContainer)) return;

            // Union bbox of the selection rects, in page-local pixels -> normalized.
            const innerRect = rec.inner.getBoundingClientRect();
            const rects = Array.from(range.getClientRects());
            if (!rects.length) return;
            let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
            rects.forEach(r => {
                minX = Math.min(minX, r.left - innerRect.left);
                minY = Math.min(minY, r.top - innerRect.top);
                maxX = Math.max(maxX, r.right - innerRect.left);
                maxY = Math.max(maxY, r.bottom - innerRect.top);
            });
            const bbox = [
                Math.max(0, minX) / rec.width,
                Math.max(0, minY) / rec.height,
                Math.max(2, maxX - minX) / rec.width,
                Math.max(2, maxY - minY) / rec.height,
            ];

            // Per-page char offsets from the enclosing word spans (metadata; the
            // bbox above is the authoritative render geometry).
            const startSpan = (range.startContainer.nodeType === Node.TEXT_NODE
                ? range.startContainer.parentElement : range.startContainer).closest('[data-word-start]');
            const endSpan = (range.endContainer.nodeType === Node.TEXT_NODE
                ? range.endContainer.parentElement : range.endContainer).closest('[data-word-start]');
            const start = startSpan ? parseInt(startSpan.dataset.wordStart, 10) : 0;
            const end = endSpan ? parseInt(endSpan.dataset.wordEnd, 10) : start;

            sel.removeAllRanges();
            this.addAnchor({
                id: uid('anchor'), kind: 'text', page: pageNum,
                label: this.currentLabel, start, end, bbox,
            }, true);
        }

        // ---- anchor store + rendering ----
        _labelOverride(name) {
            const l = this.anchorLabels.find(a => a.name === name);
            return l && l.color;
        }

        addAnchor(anchor, persist) {
            this.anchors.set(anchor.id, anchor);
            this._renderAnchorsForPage(anchor.page);
            if (persist) this.saveAnchor(anchor);
        }

        removeAnchor(id) {
            const a = this.anchors.get(id);
            if (!a) return;
            this.anchors.delete(id);
            // cascade: drop links that reference it locally; server cascades too
            this.links = this.links.filter(l => !l.span_ids.includes(id));
            this._renderAnchorsForPage(a.page);
            this.renderArcs();
            this.deleteAnchor(id);
        }

        renderAllAnchors() {
            Object.keys(this.pages).forEach(p => this._renderAnchorsForPage(Number(p)));
        }

        _renderAnchorsForPage(pageNum) {
            const rec = this.pages[pageNum];
            if (!rec) return;
            rec.overlay.innerHTML = '';
            this.anchors.forEach(a => {
                if (a.page !== pageNum) return;
                const color = labelColor(a.label, this._labelOverride(a.label));
                const el = document.createElement('div');
                el.className = 'pdf-anchor pdf-anchor-' + a.kind;
                el.dataset.anchorId = a.id;
                el.style.left = (a.bbox[0] * rec.width) + 'px';
                el.style.top = (a.bbox[1] * rec.height) + 'px';
                el.style.width = (a.bbox[2] * rec.width) + 'px';
                el.style.height = (a.bbox[3] * rec.height) + 'px';
                el.style.borderColor = color;
                el.style.background = this._rgba(color, a.kind === 'text' ? 0.25 : 0.12);
                if (this.selectedForLink.includes(a.id)) el.classList.add('selected');
                if (this.pinnedSource === a.id) el.classList.add('pinned');

                const tag = document.createElement('span');
                tag.className = 'pdf-anchor-label';
                tag.textContent = a.label;
                tag.style.background = color;
                el.appendChild(tag);

                const del = document.createElement('button');
                del.type = 'button';
                del.className = 'pdf-anchor-del';
                del.textContent = '×';
                del.title = 'Delete anchor';
                del.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.removeAnchor(a.id);
                });
                el.appendChild(del);
                rec.overlay.appendChild(el);
            });
        }

        _rgba(hex, alpha) {
            const h = hex.replace('#', '');
            const r = parseInt(h.substring(0, 2), 16);
            const g = parseInt(h.substring(2, 4), 16);
            const b = parseInt(h.substring(4, 6), 16);
            return `rgba(${r},${g},${b},${alpha})`;
        }

        // ---- anchor persistence ----
        _anchorFormatCoords(a) {
            return {
                format: 'pdf', anchor_kind: a.kind, page: a.page,
                bbox: a.bbox, start: a.start, end: a.end,
            };
        }

        async saveAnchor(a) {
            const instanceId = this.getInstanceId();
            if (!instanceId) return;
            const span = {
                schema: this.anchorSchema, name: a.label, label: a.label, title: a.label,
                start: a.start, end: a.end, value: a.label, id: a.id,
                target_field: this.fieldKey, format_coords: this._anchorFormatCoords(a),
            };
            try {
                await fetch('/updateinstance', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ instance_id: instanceId, annotations: {}, span_annotations: [span] }),
                });
            } catch (e) { console.error('[PdfLinkMode] saveAnchor failed', e); }
        }

        async deleteAnchor(id) {
            const instanceId = this.getInstanceId();
            if (!instanceId) return;
            // value:null -> id-based delete + orphaned-link cascade (routes.py)
            const span = { schema: this.anchorSchema, name: 'deleted', start: 0, end: 0, id: id, value: null };
            try {
                await fetch('/updateinstance', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ instance_id: instanceId, annotations: {}, span_annotations: [span] }),
                });
            } catch (e) { console.error('[PdfLinkMode] deleteAnchor failed', e); }
        }

        async loadAnchors() {
            const instanceId = this.getInstanceId();
            if (!instanceId) return;
            try {
                const resp = await fetch(`/api/spans/${instanceId}`);
                if (!resp.ok) return;
                const data = await resp.json();
                (data.spans || []).forEach(s => {
                    const fc = s.format_coords;
                    if (!fc || fc.format !== 'pdf') return;
                    this.anchors.set(s.id, {
                        id: s.id, kind: fc.anchor_kind || 'text', page: fc.page || 1,
                        label: s.label || s.name, start: fc.start ?? s.start,
                        end: fc.end ?? s.end, bbox: fc.bbox || [0, 0, 0.1, 0.03],
                    });
                });
                this.renderAllAnchors();
            } catch (e) { console.error('[PdfLinkMode] loadAnchors failed', e); }
        }

        // ---- linking ----
        _linkTypeConfig(name) {
            return this.linkTypes.find(t => t.name === name) || { name, directed: false };
        }

        _onAnchorClick(anchorId, evt) {
            if (!this.linkModeOn) return;
            if (evt) evt.stopPropagation();
            const a = this.anchors.get(anchorId);
            if (!a) return;
            const cfg = this._linkTypeConfig(this.currentLinkType);

            // Source/target label constraints for directed links.
            const isFirst = this.selectedForLink.length === 0;
            if (cfg.directed && isFirst && cfg.allowed_source_labels && cfg.allowed_source_labels.length) {
                if (!cfg.allowed_source_labels.includes(a.label)) {
                    this._flash(`Source must be: ${cfg.allowed_source_labels.join(', ')}`);
                    return;
                }
            }
            if (cfg.directed && !isFirst && cfg.allowed_target_labels && cfg.allowed_target_labels.length) {
                if (!cfg.allowed_target_labels.includes(a.label)) {
                    this._flash(`Target must be: ${cfg.allowed_target_labels.join(', ')}`);
                    return;
                }
            }

            const i = this.selectedForLink.indexOf(anchorId);
            if (i >= 0) this.selectedForLink.splice(i, 1);
            else this.selectedForLink.push(anchorId);
            this._renderAnchorsForPage(a.page);
            this._updateToolbarState();

            const maxSpans = cfg.max_spans || 2;
            if (this.selectedForLink.length >= maxSpans) this.createLink();
        }

        createLink() {
            if (this.selectedForLink.length < 2) {
                this._flash('Select at least two anchors to link');
                return;
            }
            const cfg = this._linkTypeConfig(this.currentLinkType);
            const ids = this.selectedForLink.slice();
            const pages = ids.map(id => (this.anchors.get(id) || {}).page);
            const kinds = ids.map(id => (this.anchors.get(id) || {}).kind);
            const link = {
                id: uid('link'), schema: this.linkSchema, link_type: this.currentLinkType,
                span_ids: ids, direction: cfg.directed ? 'directed' : 'undirected',
                properties: {
                    color: cfg.color || labelColor(this.currentLinkType),
                    anchor_pages: pages, anchor_kinds: kinds,
                },
            };
            this.links.push(link);
            this.selectedForLink = [];
            this.pinnedSource = null;
            this.renderAllAnchors();
            this.renderArcs();
            this._updateToolbarState();
            this.saveLink(link);
        }

        async saveLink(link) {
            const instanceId = this.getInstanceId();
            if (!instanceId) return;
            try {
                await fetch('/updateinstance', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ instance_id: instanceId, annotations: {}, link_annotations: [link] }),
                });
            } catch (e) { console.error('[PdfLinkMode] saveLink failed', e); }
        }

        async deleteLink(linkId) {
            const instanceId = this.getInstanceId();
            this.links = this.links.filter(l => l.id !== linkId);
            this.renderArcs();
            if (!instanceId) return;
            try {
                await fetch(`/api/links/${instanceId}/${linkId}`, { method: 'DELETE' });
            } catch (e) { console.error('[PdfLinkMode] deleteLink failed', e); }
        }

        async loadLinks() {
            const instanceId = this.getInstanceId();
            if (!instanceId) return;
            try {
                const resp = await fetch(`/api/links/${instanceId}`);
                if (!resp.ok) return;
                const data = await resp.json();
                this.links = (data.links || []).filter(l => l.schema === this.linkSchema);
                this.renderArcs();
            } catch (e) { console.error('[PdfLinkMode] loadLinks failed', e); }
        }

        // ---- arc overlay (cross-page) ----
        _anchorCenter(anchorId) {
            const a = this.anchors.get(anchorId);
            if (!a) return null;
            const rec = this.pages[a.page];
            if (!rec) return null; // page not rendered (paginated, off-page)
            const el = rec.overlay.querySelector(`.pdf-anchor[data-anchor-id="${anchorId}"]`);
            if (!el) return null;
            const scRect = this.scrollEl.getBoundingClientRect();
            const r = el.getBoundingClientRect();
            return {
                x: r.left - scRect.left + this.scrollEl.scrollLeft + r.width / 2,
                y: r.top - scRect.top + this.scrollEl.scrollTop + r.height / 2,
                page: a.page,
            };
        }

        renderArcs() {
            const svg = this.overlaySvg;
            if (!svg) return;
            // size overlay to the full scrollable content
            svg.setAttribute('width', this.stackEl.scrollWidth);
            svg.setAttribute('height', this.stackEl.scrollHeight);
            svg.style.width = this.stackEl.scrollWidth + 'px';
            svg.style.height = this.stackEl.scrollHeight + 'px';
            // clear everything except <defs>
            Array.from(svg.querySelectorAll('.pdf-arc, .pdf-arc-label, .pdf-arc-label-bg, .pdf-arc-stub'))
                .forEach(n => n.remove());

            this.links.forEach(link => {
                const cfg = this._linkTypeConfig(link.link_type);
                const color = (link.properties && link.properties.color) || cfg.color || labelColor(link.link_type);
                const pts = link.span_ids.map(id => this._anchorCenter(id));
                const known = pts.filter(Boolean);

                if (link.span_ids.length === 2) {
                    const [p1, p2] = pts;
                    if (p1 && p2) {
                        this._drawArc(p1, p2, color, link, cfg.directed);
                    } else if (known.length === 1) {
                        // Paginated: one endpoint off-page -> stub + page indicator
                        const vis = known[0];
                        const missIdx = pts[0] ? 1 : 0;
                        const missPage = (link.properties && link.properties.anchor_pages || [])[missIdx];
                        this._drawStub(vis, color, link, missPage);
                    }
                } else if (known.length >= 2) {
                    // N-ary: connect each known endpoint to their centroid
                    const cx = known.reduce((s, p) => s + p.x, 0) / known.length;
                    const cy = known.reduce((s, p) => s + p.y, 0) / known.length;
                    known.forEach(p => this._line(p.x, p.y, cx, cy, color, link));
                    this._dot(cx, cy, color, link);
                }
            });
        }

        _drawArc(p1, p2, color, link, directed) {
            const svg = this.overlaySvg;
            const dx = p2.x - p1.x, dy = p2.y - p1.y;
            const dist = Math.hypot(dx, dy) || 1;
            // control point offset perpendicular to the segment for a gentle curve
            const bow = Math.min(80, Math.max(24, dist * 0.2));
            const mx = (p1.x + p2.x) / 2, my = (p1.y + p2.y) / 2;
            const nx = -dy / dist, ny = dx / dist;
            const cxp = mx + nx * bow, cyp = my + ny * bow;

            const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            path.setAttribute('d', `M ${p1.x} ${p1.y} Q ${cxp} ${cyp} ${p2.x} ${p2.y}`);
            path.setAttribute('fill', 'none');
            path.setAttribute('stroke', color);
            path.setAttribute('stroke-width', '2.5');
            path.setAttribute('class', 'pdf-arc');
            path.dataset.linkId = link.id;
            path.style.color = color;
            if (directed) path.setAttribute('marker-end', 'url(#pdf-link-arrowhead)');
            path.style.cursor = 'pointer';
            path.addEventListener('click', () => {
                if (window.confirm(`Delete link "${link.link_type}"?`)) this.deleteLink(link.id);
            });
            svg.appendChild(path);

            const lx = cxp, ly = cyp - 4;
            const label = link.link_type;
            const bg = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
            const wApprox = label.length * 7 + 8;
            bg.setAttribute('x', lx - wApprox / 2);
            bg.setAttribute('y', ly - 11);
            bg.setAttribute('width', wApprox);
            bg.setAttribute('height', 15);
            bg.setAttribute('rx', 3);
            bg.setAttribute('fill', 'white');
            bg.setAttribute('class', 'pdf-arc-label-bg');
            svg.appendChild(bg);
            const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
            text.setAttribute('x', lx);
            text.setAttribute('y', ly);
            text.setAttribute('text-anchor', 'middle');
            text.setAttribute('fill', color);
            text.setAttribute('class', 'pdf-arc-label');
            text.textContent = label;
            svg.appendChild(text);
        }

        _drawStub(p, color, link, missPage) {
            const svg = this.overlaySvg;
            const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            path.setAttribute('d', `M ${p.x} ${p.y} l 26 -26`);
            path.setAttribute('stroke', color);
            path.setAttribute('stroke-width', '2');
            path.setAttribute('fill', 'none');
            path.setAttribute('class', 'pdf-arc-stub');
            path.style.color = color;
            path.setAttribute('marker-end', 'url(#pdf-link-arrowhead)');
            svg.appendChild(path);
            const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
            text.setAttribute('x', p.x + 30);
            text.setAttribute('y', p.y - 26);
            text.setAttribute('fill', color);
            text.setAttribute('class', 'pdf-arc-label');
            text.textContent = missPage ? `${link.link_type} → p.${missPage}` : link.link_type;
            svg.appendChild(text);
        }

        _line(x1, y1, x2, y2, color, link) {
            const l = document.createElementNS('http://www.w3.org/2000/svg', 'line');
            l.setAttribute('x1', x1); l.setAttribute('y1', y1);
            l.setAttribute('x2', x2); l.setAttribute('y2', y2);
            l.setAttribute('stroke', color); l.setAttribute('stroke-width', '2');
            l.setAttribute('class', 'pdf-arc'); l.dataset.linkId = link.id;
            this.overlaySvg.appendChild(l);
        }

        _dot(x, y, color, link) {
            const c = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
            c.setAttribute('cx', x); c.setAttribute('cy', y); c.setAttribute('r', 5);
            c.setAttribute('fill', color); c.setAttribute('class', 'pdf-arc');
            c.dataset.linkId = link.id;
            this.overlaySvg.appendChild(c);
        }

        // ---- thumbnails (paginated) ----
        async renderThumbnails() {
            if (!this.sidebarEl) return;
            this.sidebarEl.innerHTML = '';
            for (let p = 1; p <= this.totalPages; p++) {
                const thumb = document.createElement('div');
                thumb.className = 'pdf-thumb';
                thumb.dataset.page = String(p);
                if (p === this.currentPage) thumb.classList.add('active');
                const canvas = document.createElement('canvas');
                thumb.appendChild(canvas);
                const num = document.createElement('div');
                num.className = 'pdf-thumb-num';
                num.textContent = String(p);
                thumb.appendChild(num);
                thumb.addEventListener('click', () => this.goToPage(p));
                this.sidebarEl.appendChild(thumb);
                try {
                    const page = await this.pdfDoc.getPage(p);
                    const vp = page.getViewport({ scale: 1 });
                    const scale = 120 / vp.width;
                    const tvp = page.getViewport({ scale });
                    canvas.width = tvp.width; canvas.height = tvp.height;
                    await page.render({ canvasContext: canvas.getContext('2d'), viewport: tvp }).promise;
                } catch (e) { /* thumb best-effort */ }
            }
            this._badgeThumbs();
        }

        _badgeThumbs() {
            if (!this.sidebarEl) return;
            const pagesWithAnchors = new Set();
            this.anchors.forEach(a => pagesWithAnchors.add(a.page));
            this.sidebarEl.querySelectorAll('.pdf-thumb').forEach(t => {
                const p = Number(t.dataset.page);
                t.classList.toggle('has-anchor', pagesWithAnchors.has(p));
            });
        }

        async goToPage(pageNum) {
            if (pageNum < 1 || pageNum > this.totalPages) return;
            this.currentPage = pageNum;
            if (this.viewMode === 'paginated') {
                this.stackEl.innerHTML = '';
                this.pages = {};
                await this.renderPage(pageNum);
                this.renderAllAnchors();
                this.renderArcs();
                if (this.sidebarEl) {
                    this.sidebarEl.querySelectorAll('.pdf-thumb').forEach(t =>
                        t.classList.toggle('active', Number(t.dataset.page) === pageNum));
                }
            } else {
                const rec = this.pages[pageNum];
                if (rec) rec.container.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
        }

        // ---- toolbar ----
        buildToolbar() {
            const tb = this.toolbarEl;
            if (!tb) return;
            tb.innerHTML = '';

            // Anchor label selector
            const labelGroup = document.createElement('div');
            labelGroup.className = 'pdf-tb-group';
            labelGroup.appendChild(this._label('Label:'));
            const labelSel = document.createElement('select');
            labelSel.className = 'pdf-tb-label-select';
            this.anchorLabels.forEach(l => {
                const o = document.createElement('option');
                o.value = l.name; o.textContent = l.name; labelSel.appendChild(o);
            });
            labelSel.addEventListener('change', e => { this.currentLabel = e.target.value; });
            labelGroup.appendChild(labelSel);
            tb.appendChild(labelGroup);

            // Region draw toggle
            if (this.enableRegion) {
                const regionBtn = document.createElement('button');
                regionBtn.type = 'button';
                regionBtn.className = 'pdf-tb-btn pdf-tb-region';
                regionBtn.textContent = '□ Draw region';
                regionBtn.addEventListener('click', () => {
                    this.regionArmed = !this.regionArmed;
                    if (this.regionArmed) this.linkModeOn = false;
                    this._updateToolbarState();
                });
                tb.appendChild(regionBtn);
                this._regionBtn = regionBtn;
            }
            if (this.enableText) {
                const hint = document.createElement('span');
                hint.className = 'pdf-tb-hint';
                hint.textContent = 'Select text to add a text anchor';
                tb.appendChild(hint);
                this._textHint = hint;
            }

            // Link controls
            const linkGroup = document.createElement('div');
            linkGroup.className = 'pdf-tb-group pdf-tb-link-group';
            const linkBtn = document.createElement('button');
            linkBtn.type = 'button';
            linkBtn.className = 'pdf-tb-btn pdf-tb-link';
            linkBtn.textContent = '→ Link mode';
            linkBtn.addEventListener('click', () => {
                this.linkModeOn = !this.linkModeOn;
                if (this.linkModeOn) this.regionArmed = false;
                this.selectedForLink = [];
                this.renderAllAnchors();
                this._updateToolbarState();
            });
            linkGroup.appendChild(linkBtn);
            this._linkBtn = linkBtn;

            const linkSel = document.createElement('select');
            linkSel.className = 'pdf-tb-linktype-select';
            this.linkTypes.forEach(t => {
                const o = document.createElement('option');
                o.value = t.name;
                o.textContent = t.name + (t.directed ? ' →' : '');
                linkSel.appendChild(o);
            });
            linkSel.addEventListener('change', e => { this.currentLinkType = e.target.value; });
            linkGroup.appendChild(linkSel);

            const createBtn = document.createElement('button');
            createBtn.type = 'button';
            createBtn.className = 'pdf-tb-btn pdf-tb-create';
            createBtn.textContent = 'Create link';
            createBtn.addEventListener('click', () => this.createLink());
            linkGroup.appendChild(createBtn);

            const clearBtn = document.createElement('button');
            clearBtn.type = 'button';
            clearBtn.className = 'pdf-tb-btn pdf-tb-clear';
            clearBtn.textContent = 'Clear';
            clearBtn.addEventListener('click', () => {
                this.selectedForLink = []; this.pinnedSource = null;
                this.renderAllAnchors(); this._updateToolbarState();
            });
            linkGroup.appendChild(clearBtn);

            this._selCount = document.createElement('span');
            this._selCount.className = 'pdf-tb-selcount';
            linkGroup.appendChild(this._selCount);

            tb.appendChild(linkGroup);
            this._updateToolbarState();
        }

        _label(t) {
            const s = document.createElement('span');
            s.className = 'pdf-tb-text';
            s.textContent = t;
            return s;
        }

        _updateToolbarState() {
            if (this._regionBtn) this._regionBtn.classList.toggle('active', this.regionArmed);
            if (this._linkBtn) this._linkBtn.classList.toggle('active', this.linkModeOn);
            this.container.classList.toggle('link-mode-active', this.linkModeOn);
            this.container.classList.toggle('region-arm-active', this.regionArmed);
            if (this._selCount) {
                this._selCount.textContent = this.linkModeOn
                    ? `${this.selectedForLink.length} selected` : '';
            }
            this._badgeThumbs();
        }

        _flash(msg) {
            let el = this.container.querySelector('.pdf-link-flash');
            if (!el) {
                el = document.createElement('div');
                el.className = 'pdf-link-flash';
                this.container.appendChild(el);
            }
            el.textContent = msg;
            el.classList.add('show');
            clearTimeout(this._flashTimer);
            this._flashTimer = setTimeout(() => el.classList.remove('show'), 2200);
        }

        // ---- global events ----
        wireGlobalEvents() {
            let resizeTimer = null;
            this._onResize = () => {
                clearTimeout(resizeTimer);
                resizeTimer = setTimeout(async () => {
                    // Re-render at new width so geometry stays correct (risk R3).
                    if (this.viewMode === 'paginated') {
                        await this.renderPage(this.currentPage);
                    } else {
                        for (let p = 1; p <= this.totalPages; p++) {
                            if (this.pages[p]) await this.renderPage(p);
                        }
                    }
                    this.renderAllAnchors();
                    this.renderArcs();
                }, 200);
            };
            window.addEventListener('resize', this._onResize);
            this.scrollEl.addEventListener('scroll', () => {
                // arcs are positioned within the stack; nothing to recompute on
                // scroll, but keep a hook for future sticky indicators.
            });
        }
    }

    function initPdfLinkModes() {
        document.querySelectorAll('.pdf-display.pdf-link-mode[data-pdf-source]').forEach(c => {
            if (c._pdfLinkMode) return;
            c._pdfLinkMode = new PdfLinkMode(c);
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initPdfLinkModes);
    } else {
        initPdfLinkModes();
    }
    document.addEventListener('potato:content-loaded', initPdfLinkModes);

    window.PdfLinkMode = PdfLinkMode;
    window.initPdfLinkModes = initPdfLinkModes;
})();

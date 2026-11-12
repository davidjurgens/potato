/*
 * fits_cutout viewer adapter: FITS cutouts side by side, with shared zoom,
 * pan and crosshair, an RA/Dec readout, and an optional light curve.
 *
 * The server has already read the FITS files (astropy) and sends, per panel,
 * a PNG URL plus a WCS description (potato/science/converters/fits.py):
 *   wcs.grid    unit vectors sampled across the cutout, interpolated here to
 *               give the sky position under the cursor (any projection);
 *   wcs.crpix / wcs.cd / wcs.crval
 *               the cutout's linear TAN WCS, used to place the crosshair on a
 *               panel whose pixels are not aligned with the one under the
 *               pointer;
 *   wcs.origin  {x0, y0, step}: cutout pixel -> pixel of the original image.
 *
 * Gestures: hover moves the crosshair; a click or tap pins it (Escape or a
 * second click unpins); drag pans when zoomed in; Ctrl/Cmd + wheel (or a
 * trackpad pinch) zooms at the pointer. A focused cutout takes the arrow keys
 * (move the crosshair one pixel), + and - (zoom) and 0 (reset).
 *
 * The light curve uses the vendored Plotly, loaded only when the item has
 * one. Magnitudes are drawn brighter-up (reversed axis); upper limits are open
 * downward triangles.
 */
(function () {
    'use strict';
    var FW = window.PotatoViewerFramework;
    if (!FW) { return; }

    var ZOOMS = [1, 1.5, 2, 3, 4, 6, 8, 12, 16];
    var BAND_COLORS = {u: '#7048e8', g: '#2f9e44', r: '#e03131', i: '#e8590c', z: '#1c7ed6',
        y: '#5c7cfa', j: '#ae3ec9', h: '#c2255c', k: '#862e9c', c: '#0c8599', o: '#f08c00'};
    var FALLBACK = ['#1c7ed6', '#e8590c', '#2f9e44', '#ae3ec9', '#0c8599', '#c2255c'];

    function el(tag, cls, attrs) {
        var n = document.createElement(tag);
        if (cls) { n.className = cls; }
        Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
        return n;
    }
    function rad(d) { return d * Math.PI / 180; }
    function deg(r) { return r * 180 / Math.PI; }
    function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

    // ------------------------------------------------------------------
    // Coordinates
    // ------------------------------------------------------------------

    /* Sky position at screen fraction (u, v) of a panel, from its grid. */
    function skyAt(wcs, u, v) {
        if (!wcs || !wcs.grid) { return null; }
        var g = wcs.grid, gx = (g.nx - 1) * clamp(u, 0, 1), gy = (g.ny - 1) * clamp(1 - v, 0, 1);
        var i0 = Math.min(g.nx - 2, Math.floor(gx)), j0 = Math.min(g.ny - 2, Math.floor(gy));
        var fx = gx - i0, fy = gy - j0, out = [0, 0, 0];
        [[0, 0, (1 - fx) * (1 - fy)], [1, 0, fx * (1 - fy)], [0, 1, (1 - fx) * fy], [1, 1, fx * fy]]
            .forEach(function (c) {
                var k = ((j0 + c[1]) * g.nx + (i0 + c[0])) * 3;
                out[0] += c[2] * g.xyz[k]; out[1] += c[2] * g.xyz[k + 1]; out[2] += c[2] * g.xyz[k + 2];
            });
        var n = Math.sqrt(out[0] * out[0] + out[1] * out[1] + out[2] * out[2]);
        if (!n) { return null; }
        var lon = deg(Math.atan2(out[1], out[0]));
        if (lon < 0) { lon += 360; }
        return {lon: lon, lat: deg(Math.asin(clamp(out[2] / n, -1, 1)))};
    }

    /* Screen fraction of a sky position on a panel (gnomonic, linear WCS). */
    function fracOf(panel, sky) {
        var w = panel.wcs, m = panel.meta;
        if (!w || !w.cd || !sky || !/-TAN/.test(w.ctype[0] || '')) { return null; }
        var a0 = rad(w.crval[0]), d0 = rad(w.crval[1]), a = rad(sky.lon), d = rad(sky.lat);
        var cosc = Math.sin(d0) * Math.sin(d) + Math.cos(d0) * Math.cos(d) * Math.cos(a - a0);
        if (cosc <= 0) { return null; }
        var xi = deg(Math.cos(d) * Math.sin(a - a0) / cosc);
        var eta = deg((Math.cos(d0) * Math.sin(d) - Math.sin(d0) * Math.cos(d) * Math.cos(a - a0)) / cosc);
        var c = w.cd, det = c[0][0] * c[1][1] - c[0][1] * c[1][0];
        if (!det) { return null; }
        var px = w.crpix[0] + (c[1][1] * xi - c[0][1] * eta) / det;
        var py = w.crpix[1] + (-c[1][0] * xi + c[0][0] * eta) / det;
        return {u: (px - 0.5) / m.width, v: 1 - (py - 0.5) / m.height};
    }

    /* FITS pixel (1-based) of the original image under screen fraction (u, v). */
    function pixelAt(panel, u, v) {
        var m = panel.meta, o = (panel.wcs && panel.wcs.origin) ||
            {x0: m.region.x0 - 1, y0: m.region.y0 - 1, step: m.region.step};
        return {x: o.x0 + u * m.width * o.step + 0.5, y: o.y0 + (1 - v) * m.height * o.step + 0.5};
    }

    function sexagesimal(value, hours) {
        var sign = value < 0 ? '-' : (hours ? '' : '+');
        var v = Math.abs(value) / (hours ? 15 : 1);
        var places = hours ? 2 : 1, scale = Math.pow(10, places);
        var total = Math.round(v * 3600 * scale) / scale;
        var h = Math.floor(total / 3600), mnt = Math.floor((total - h * 3600) / 60);
        var s = total - h * 3600 - mnt * 60;
        var ss = s.toFixed(places);
        if (s < 10) { ss = '0' + ss; }
        return sign + (h < 10 ? '0' : '') + h + ':' + (mnt < 10 ? '0' : '') + mnt + ':' + ss;
    }

    function formatSky(wcs, sky) {
        var names = wcs.axes || ['RA', 'Dec'];
        if (wcs.sexagesimal) {
            return names[0] + ' ' + sexagesimal(sky.lon, true) + '  ' + names[1] + ' ' +
                sexagesimal(sky.lat, false) + '  (' + sky.lon.toFixed(5) + '°, ' +
                (sky.lat >= 0 ? '+' : '') + sky.lat.toFixed(5) + '°)';
        }
        return names[0] + ' ' + sky.lon.toFixed(5) + '°  ' + names[1] + ' ' +
            (sky.lat >= 0 ? '+' : '') + sky.lat.toFixed(5) + '°';
    }

    // ------------------------------------------------------------------
    // The viewer
    // ------------------------------------------------------------------

    function Cutouts(ctx) {
        this.ctx = ctx;
        this.cfg = ctx.config;
        this.zoom = {s: 1, tx: 0, ty: 0};
        this.cross = null;          // {panel index, u, v} under the pointer
        this.pinned = null;
        this.panels = [];
    }

    Cutouts.prototype.build = function () {
        var self = this, cfg = this.cfg, stage = this.ctx.stage;
        var root = el('div', 'fc-root');
        if (cfg.panelSize) { root.style.setProperty('--fc-panel-max', cfg.panelSize); }
        var shown = cfg.panels.filter(function (p) { return p.src; });
        var toolbar = el('div', 'fc-toolbar', {role: 'toolbar', 'aria-label': 'Cutout zoom'});
        [['zoom-out', '−', 'Zoom out'], ['zoom-in', '+', 'Zoom in'], ['reset', 'Reset', 'Reset zoom and crosshair']]
            .forEach(function (b) {
                var btn = el('button', 'fc-btn', {type: 'button', 'data-fc': b[0], 'aria-label': b[2], title: b[2]});
                btn.textContent = b[1];
                btn.addEventListener('click', function () { self.button(b[0]); });
                toolbar.appendChild(btn);
            });
        this.zoomLabel = el('span', 'fc-zoom-level');
        this.zoomLabel.textContent = '1×';
        toolbar.insertBefore(this.zoomLabel, toolbar.children[1]);
        if (!shown.length) { toolbar.hidden = true; }
        root.appendChild(toolbar);

        var grid = el('div', 'fc-panels', {'data-count': String(cfg.panels.length)});
        cfg.panels.forEach(function (p, index) {
            var fig = el('figure', 'fc-panel', {'data-panel': p.key});
            var frame = el('div', 'fc-frame');
            var cap = el('figcaption', 'fc-caption');
            cap.textContent = p.label || '';
            if (!p.src) {
                frame.classList.add('fc-frame-error');
                var msg = el('p', 'fc-panel-error', {role: 'note'});
                msg.textContent = p.error || 'This image could not be shown.';
                frame.appendChild(msg);
                fig.appendChild(frame);
                fig.appendChild(cap);
                grid.appendChild(fig);
                self.panels.push({cfg: p, frame: frame, ok: false});
                return;
            }
            frame.style.aspectRatio = p.meta.width + ' / ' + p.meta.height;
            frame.setAttribute('tabindex', '0');
            frame.setAttribute('role', 'img');
            frame.setAttribute('aria-label', (p.label ? p.label + ' cutout, ' : 'Cutout, ') +
                p.meta.width + ' by ' + p.meta.height + ' pixels' +
                (p.wcs ? '. Arrow keys move the crosshair; plus and minus zoom.' : ''));
            var img = el('img', 'fc-img', {alt: '', draggable: 'false'});
            var crossH = el('div', 'fc-cross fc-cross-h', {'aria-hidden': 'true'});
            var crossV = el('div', 'fc-cross fc-cross-v', {'aria-hidden': 'true'});
            crossH.hidden = crossV.hidden = true;     // until there is a point to mark
            frame.appendChild(img);
            frame.appendChild(crossH);
            frame.appendChild(crossV);
            if (cfg.compass && p.wcs && p.wcs.north && p.wcs.east) {
                frame.appendChild(compass(p.wcs));
            }
            fig.appendChild(frame);
            fig.appendChild(cap);
            grid.appendChild(fig);
            var panel = {cfg: p, frame: frame, img: img, crossH: crossH, crossV: crossV, ok: true, index: index};
            self.panels.push(panel);
            self.bindPanel(panel);
        });
        root.appendChild(grid);

        this.readout = el('p', 'fc-readout');
        root.appendChild(this.readout);
        this.idleReadout();
        stage.appendChild(root);
        this.root = root;
        if (!cfg.aligned && shown.length > 1) {
            var note = el('p', 'fc-note', {role: 'note'});
            note.textContent = 'These cutouts are not on one pixel grid; the crosshair follows the ' +
                'sky position where the WCS allows it.';
            root.insertBefore(note, this.readout);
        }

        return Promise.all(this.panels.filter(function (p) { return p.ok; }).map(function (p) {
            return new Promise(function (resolve) {
                p.img.onload = function () { resolve(); };
                p.img.onerror = function () {
                    p.ok = false;
                    p.frame.classList.add('fc-frame-error');
                    var msg = el('p', 'fc-panel-error', {role: 'note'});
                    msg.textContent = 'The cutout image did not load.';
                    p.frame.appendChild(msg);
                    resolve();
                };
                p.img.src = p.cfg.src;
            });
        }));
    };

    function compass(wcs) {
        var ns = 'http://www.w3.org/2000/svg';
        var svg = document.createElementNS(ns, 'svg');
        svg.setAttribute('class', 'fc-compass');
        svg.setAttribute('viewBox', '-20 -20 40 40');
        svg.setAttribute('aria-hidden', 'true');
        [['N', wcs.north], ['E', wcs.east]].forEach(function (d) {
            var x = d[1][0] * 12, y = d[1][1] * 12;
            var line = document.createElementNS(ns, 'line');
            line.setAttribute('x1', '0'); line.setAttribute('y1', '0');
            line.setAttribute('x2', String(x)); line.setAttribute('y2', String(y));
            svg.appendChild(line);
            var t = document.createElementNS(ns, 'text');
            t.setAttribute('x', String(d[1][0] * 17)); t.setAttribute('y', String(d[1][1] * 17 + 3));
            t.setAttribute('text-anchor', 'middle');
            t.textContent = d[0];
            svg.appendChild(t);
        });
        return svg;
    }

    Cutouts.prototype.fracFromEvent = function (panel, e) {
        // The image fills the frame inside its border.
        var f = panel.frame, r = f.getBoundingClientRect();
        var fx = (e.clientX - r.left - f.clientLeft) / (f.clientWidth || r.width);
        var fy = (e.clientY - r.top - f.clientTop) / (f.clientHeight || r.height);
        var z = this.zoom;
        return {fx: fx, fy: fy, u: (fx - z.tx) / z.s, v: (fy - z.ty) / z.s};
    };

    Cutouts.prototype.bindPanel = function (panel) {
        var self = this, frame = panel.frame, drag = null;
        frame.addEventListener('pointermove', function (e) {
            if (drag && drag.id === e.pointerId) {
                var dx = e.clientX - drag.x, dy = e.clientY - drag.y;
                if (Math.abs(dx) + Math.abs(dy) > 3) { drag.moved = true; }
                if (drag.moved && self.zoom.s > 1) {
                    self.zoom.tx = drag.tx + dx / frame.clientWidth;
                    self.zoom.ty = drag.ty + dy / frame.clientHeight;
                    self.applyZoom();
                }
                return;
            }
            if (e.pointerType === 'mouse' && !self.pinned) {
                var f = self.fracFromEvent(panel, e);
                self.setCross({index: panel.index, u: f.u, v: f.v});
            }
        });
        frame.addEventListener('pointerleave', function (e) {
            if (e.pointerType === 'mouse' && !self.pinned && !drag) { self.setCross(null); }
        });
        frame.addEventListener('pointerdown', function (e) {
            if (e.button !== undefined && e.button !== 0) { return; }
            drag = {id: e.pointerId, x: e.clientX, y: e.clientY, tx: self.zoom.tx, ty: self.zoom.ty, moved: false};
            if (self.zoom.s > 1) {
                try { frame.setPointerCapture(e.pointerId); } catch (err) { /* old browsers */ }
                frame.classList.add('fc-dragging');
            }
        });
        function end(e) {
            if (!drag || drag.id !== e.pointerId) { return; }
            var tap = !drag.moved;
            drag = null;
            frame.classList.remove('fc-dragging');
            if (tap && e.type === 'pointerup') {
                var f = self.fracFromEvent(panel, e);
                var here = {index: panel.index, u: f.u, v: f.v};
                if (self.pinned && e.pointerType === 'mouse') {
                    self.pinned = null;
                    self.setCross(here);
                } else {
                    self.pinned = here;
                    self.setCross(here);
                }
            }
        }
        frame.addEventListener('pointerup', end);
        frame.addEventListener('pointercancel', end);
        frame.addEventListener('wheel', function (e) {
            if (!(e.ctrlKey || e.metaKey)) { return; }
            e.preventDefault();
            var f = self.fracFromEvent(panel, e);
            self.zoomBy(e.deltaY < 0 ? 1 : -1, f.fx, f.fy);
        }, {passive: false});
        frame.addEventListener('keydown', function (e) {
            var cross = self.pinned || self.cross || {index: panel.index, u: 0.5, v: 0.5};
            if (cross.index !== panel.index) { cross = self.translate(cross, panel.index) || {index: panel.index, u: 0.5, v: 0.5}; }
            var m = panel.cfg.meta, du = 1 / m.width, dv = 1 / m.height, handled = true;
            if (e.key === 'ArrowLeft') { cross = {index: panel.index, u: cross.u - du, v: cross.v}; }
            else if (e.key === 'ArrowRight') { cross = {index: panel.index, u: cross.u + du, v: cross.v}; }
            else if (e.key === 'ArrowUp') { cross = {index: panel.index, u: cross.u, v: cross.v - dv}; }
            else if (e.key === 'ArrowDown') { cross = {index: panel.index, u: cross.u, v: cross.v + dv}; }
            else if (e.key === '+' || e.key === '=') { self.zoomBy(1, 0.5, 0.5); }
            else if (e.key === '-' || e.key === '_') { self.zoomBy(-1, 0.5, 0.5); }
            else if (e.key === '0') { self.button('reset'); }
            else if (e.key === 'Escape') { self.pinned = null; self.setCross(null); }
            else { handled = false; }
            if (!handled) { return; }
            e.preventDefault();
            e.stopPropagation();
            if (/^Arrow/.test(e.key)) {
                cross.u = clamp(cross.u, 0, 1 - 1e-9);
                cross.v = clamp(cross.v, 0, 1 - 1e-9);
                self.pinned = cross;
                self.setCross(cross);
            }
        });
        frame.addEventListener('focus', function () {
            // Keyboard focus only: a click focuses too, and pins where it lands.
            var keyboard = true;
            try { keyboard = frame.matches(':focus-visible'); } catch (err) { /* old browsers */ }
            if (keyboard && !self.pinned) {
                self.pinned = {index: panel.index, u: 0.5, v: 0.5};
                self.setCross(self.pinned);
            }
        });
    };

    /* The same place on another panel: the same fraction when the cutouts
       share a pixel grid, otherwise through the sky position. */
    Cutouts.prototype.translate = function (cross, index) {
        if (cross.index === index || this.cfg.aligned) { return {index: index, u: cross.u, v: cross.v}; }
        var from = this.panels[cross.index], to = this.panels[index];
        var sky = from && from.ok ? skyAt(from.cfg.wcs, cross.u, cross.v) : null;
        var f = sky ? fracOf(to.cfg, sky) : null;
        return f ? {index: index, u: f.u, v: f.v} : null;
    };

    Cutouts.prototype.setCross = function (cross) {
        var self = this, z = this.zoom;
        this.cross = cross;
        this.panels.forEach(function (p) {
            if (!p.ok) { return; }
            var at = cross && self.cfg.crosshair ? self.translate(cross, p.index) : null;
            var show = at && at.u >= 0 && at.u <= 1 && at.v >= 0 && at.v <= 1;
            p.crossH.hidden = p.crossV.hidden = !show;
            p.frame.classList.toggle('fc-active', !!(cross && cross.index === p.index));
            if (show) {
                var x = (z.tx + at.u * z.s) * 100, y = (z.ty + at.v * z.s) * 100;
                p.crossV.style.left = x + '%';
                p.crossH.style.top = y + '%';
                // A gap where the lines cross, so the crosshair does not cover
                // the source it points at.
                p.crossH.style.setProperty('--fc-gap-at', x + '%');
                p.crossV.style.setProperty('--fc-gap-at', y + '%');
            }
        });
        if (!cross) { this.idleReadout(); return; }
        var panel = this.panels[cross.index];
        if (!panel || !panel.ok || cross.u < 0 || cross.u > 1 || cross.v < 0 || cross.v > 1) {
            this.idleReadout();
            return;
        }
        var px = pixelAt(panel.cfg, cross.u, cross.v);
        var parts = [];
        var sky = skyAt(panel.cfg.wcs, cross.u, cross.v);
        if (sky) { parts.push(formatSky(panel.cfg.wcs, sky)); }
        parts.push('x ' + px.x.toFixed(1) + '  y ' + px.y.toFixed(1));
        if (panel.cfg.label) { parts.push(panel.cfg.label); }
        this.readout.textContent = parts.join('  ·  ');
        this.readout.classList.add('fc-readout-live');
        this.readout.classList.toggle('fc-readout-pinned', !!this.pinned);
    };

    Cutouts.prototype.idleReadout = function () {
        var first = this.panels.filter(function (p) { return p.ok; })[0];
        this.readout.classList.remove('fc-readout-live', 'fc-readout-pinned');
        if (!first) { this.readout.textContent = ''; return; }
        var w = first.cfg.wcs;
        var text = 'Point at a cutout for its coordinates.';
        if (w && w.center) {
            text = 'Centre ' + formatSky(w, {lon: w.center[0], lat: w.center[1]}) + '  ·  ' +
                w.pixel_scale_arcsec[0].toFixed(2) + '″/px. Point at a cutout for coordinates.';
        }
        this.readout.textContent = text;
    };

    Cutouts.prototype.applyZoom = function () {
        var z = this.zoom;
        z.tx = clamp(z.tx, 1 - z.s, 0);
        z.ty = clamp(z.ty, 1 - z.s, 0);
        this.panels.forEach(function (p) {
            if (p.ok) {
                p.img.style.transform = 'translate(' + (z.tx * 100) + '%, ' + (z.ty * 100) + '%) scale(' + z.s + ')';
                p.frame.classList.toggle('fc-zoomed', z.s > 1);
            }
        });
        this.zoomLabel.textContent = (Math.round(z.s * 10) / 10) + '×';
        this.root.setAttribute('data-zoom', String(z.s));
        this.setCross(this.cross);
    };

    Cutouts.prototype.zoomBy = function (dir, fx, fy) {
        var z = this.zoom, i = ZOOMS.indexOf(z.s);
        if (i < 0) { i = 0; }
        var next = ZOOMS[clamp(i + dir, 0, ZOOMS.length - 1)];
        if (next === z.s) { return; }
        // Keep the image point under (fx, fy) where it is.
        var u = (fx - z.tx) / z.s, v = (fy - z.ty) / z.s;
        z.s = next;
        z.tx = fx - u * next;
        z.ty = fy - v * next;
        this.applyZoom();
    };

    Cutouts.prototype.button = function (what) {
        if (what === 'zoom-in') { this.zoomBy(1, 0.5, 0.5); }
        else if (what === 'zoom-out') { this.zoomBy(-1, 0.5, 0.5); }
        else {
            this.zoom = {s: 1, tx: 0, ty: 0};
            this.pinned = null;
            this.applyZoom();
            this.setCross(null);
        }
    };

    Cutouts.prototype.status = function () {
        var shown = this.panels.filter(function (p) { return p.ok; });
        if (!shown.length) { this.ctx.status(''); return; }
        var m = shown[0].cfg.meta, w = shown[0].cfg.wcs;
        var bits = [shown.length + (shown.length === 1 ? ' cutout' : ' cutouts'),
            m.width + ' × ' + m.height + ' px'];
        if (w) { bits.push(w.pixel_scale_arcsec[0].toFixed(2) + '″/px'); }
        bits.push(m.interval + ', ' + m.stretch);
        var notes = [];
        shown.forEach(function (p) {
            (p.cfg.meta.notes || []).forEach(function (n) {
                var t = (p.cfg.label ? p.cfg.label + ': ' : '') + n;
                if (notes.indexOf(t) < 0) { notes.push(t); }
            });
        });
        this.ctx.status(bits.join(' · ') + (notes.length ? '. ' + notes.join('; ') + '.' : ''));
    };

    // ------------------------------------------------------------------
    // Light curve
    // ------------------------------------------------------------------

    function token(name, fallback) {
        var v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
        return v || fallback;
    }

    function bandColor(name, n) {
        var key = String(name).toLowerCase().replace(/^(ztf|lsst|sdss|ps1)[_-]?/, '');
        return BAND_COLORS[key] || FALLBACK[n % FALLBACK.length];
    }

    function lightCurveLayout(lc) {
        var fg = token('--foreground', '#09090b'), muted = token('--muted-foreground', '#71717a');
        var grid = token('--border', '#e4e4e7');
        var axis = {color: fg, gridcolor: grid, linecolor: grid, zerolinecolor: grid,
            tickfont: {color: muted}};
        var layout = {
            margin: {l: 56, r: 16, t: 12, b: 44},
            paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
            font: {family: getComputedStyle(document.body).fontFamily, size: 12, color: fg},
            // Plain numbers: an MJD is not 60.6k.
            xaxis: Object.assign({title: {text: lc.timeLabel, font: {color: fg}}, tickformat: 'd',
                hoverformat: '.3f'}, axis),
            yaxis: Object.assign({title: {text: lc.units === 'mag' ? 'Magnitude' : 'Flux', font: {color: fg}},
                autorange: lc.units === 'mag' ? 'reversed' : true}, axis),
            legend: {orientation: 'h', y: 1.02, yanchor: 'bottom', x: 0, font: {color: fg}},
            showlegend: true,
            hovermode: 'closest',
            shapes: [], annotations: []
        };
        // A short light curve (one night, one point) gets a 10-day window, so
        // whole-day ticks do not repeat.
        var times = [];
        lc.bands.forEach(function (b) { times = times.concat(b.t, b.limit_t); });
        if (typeof lc.epoch === 'number') { times.push(lc.epoch); }
        if (times.length) {
            var lo = Math.min.apply(null, times), hi = Math.max.apply(null, times);
            if (hi - lo < 10) {
                var mid = (lo + hi) / 2;
                layout.xaxis.range = [mid - 5, mid + 5];
                layout.xaxis.autorange = false;
            }
        }
        if (typeof lc.epoch === 'number') {
            layout.shapes.push({type: 'line', xref: 'x', yref: 'paper', x0: lc.epoch, x1: lc.epoch,
                y0: 0, y1: 1, line: {color: muted, width: 1, dash: 'dot'}});
            // Inside the plot, beside the line: above it the label collides
            // with the legend on a narrow screen.
            layout.annotations.push({x: lc.epoch, xref: 'x', y: 1, yref: 'paper', yanchor: 'top',
                xanchor: 'left', xshift: 4, text: 'this image', showarrow: false,
                font: {size: 11, color: muted}});
        }
        return layout;
    }

    function lightCurveTraces(lc) {
        var traces = [];
        lc.bands.forEach(function (b, n) {
            var color = bandColor(b.name, n);
            if (b.t.length) {
                traces.push({type: 'scatter', mode: 'markers', name: b.name, legendgroup: b.name,
                    x: b.t, y: b.y, marker: {color: color, size: 7},
                    error_y: {type: 'data', array: b.err, visible: true, color: color, thickness: 1.2, width: 3},
                    hovertemplate: b.name + ' %{y:.3f} ± %{error_y.array:.3f}<br>' + lc.timeLabel +
                        ' %{x:.3f}<extra></extra>'});
            }
            if (b.limit_t.length) {
                traces.push({type: 'scatter', mode: 'markers', name: b.name + ' limit',
                    legendgroup: b.name, showlegend: !b.t.length,
                    x: b.limit_t, y: b.limit_y,
                    marker: {color: color, size: 8, symbol: 'triangle-down-open', line: {width: 1.5}},
                    hovertemplate: b.name + ' fainter than %{y:.2f}<br>' + lc.timeLabel +
                        ' %{x:.3f}<extra></extra>'});
            }
        });
        return traces;
    }

    function drawLightCurve(ctx) {
        var lc = ctx.config.lightCurve;
        var box = ctx.element.querySelector('.fc-lightcurve');
        if (!lc || !box) { return Promise.resolve(); }
        return FW.loadAssets([{type: 'script', src: ctx.config.plotly}]).then(function () {
            if (!window.Plotly) { throw new Error('Plotly did not load'); }
            return window.Plotly.newPlot(box, lightCurveTraces(lc), lightCurveLayout(lc), {
                displaylogo: false, responsive: true,
                // On a touch screen the mode bar never hides and covers the legend.
                displayModeBar: window.matchMedia && window.matchMedia('(pointer: coarse)').matches
                    ? false : 'hover',
                modeBarButtonsToRemove: ['select2d', 'lasso2d', 'autoScale2d', 'toggleSpikelines']
            });
        }).then(function () {
            box.setAttribute('data-plotted', 'true');
            document.addEventListener('potato:themechange', function () {
                if (box.isConnected && window.Plotly) {
                    window.Plotly.relayout(box, lightCurveLayout(lc));
                }
            });
        }).catch(function (err) {
            console.warn('light curve not drawn', err);
            box.classList.add('fc-lightcurve-failed');
            box.textContent = 'The light curve could not be drawn. Its points are in the table below.';
        });
    }

    // ------------------------------------------------------------------

    FW.register('fits_cutout', {
        context: [],
        describe: function () { return ''; },
        start: function (ctx) {
            var viewer = new Cutouts(ctx);
            ctx.viewer.cutouts = viewer;
            return viewer.build().then(function () {
                viewer.status();
                drawLightCurve(ctx);
            });
        }
    });
})();

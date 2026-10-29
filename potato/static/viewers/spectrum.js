/*
 * spectrum viewer adapter (Plotly).
 *
 * Draws one spectrum (NMR, IR, MS ...) parsed on the server, with:
 *   - Pick mode: a click picks the peak under the pointer (snapped to the
 *     local maximum, or minimum for transmittance), a click on a picked peak
 *     removes it, a click on a suggested peak accepts it; dragging zooms.
 *   - Pan mode: dragging pans.
 *   - Integrate mode (when the display allows it): dragging across the
 *     spectrum adds an integrated region; a click inside a region removes it.
 *   - Double-click or "Reset view" zooms back out. Zooming in fetches
 *     full-resolution points for the visible range from /api/spectrum/range.
 *
 * Selection (window.potatoViewers[field]):
 *   {viewer: 'spectrum',
 *    items: [{kind: 'peak', x, y, source: 'auto'|'manual', width?, fields?},
 *            {kind: 'region', from, to, integral, fields?}],
 *    rejected: [x, ...]}
 *
 * Besides the shared API the viewer object carries `viewer.spectrum`, used by
 * the peak_picking scheme (peak-picking.js) and available to other schemes:
 *   format(x), units, suggestions(), pendingSuggestions(), accept(s),
 *   reject(s), restore(x), addPeakAt(x), relative(region), zoomTo(a, b),
 *   setAllowManual(bool), setMode(mode)
 */
(function () {
    'use strict';
    var FW = window.PotatoViewerFramework;
    if (!FW || FW.__spectrum) { return; }
    FW.__spectrum = true;

    function num(v) {
        var n = typeof v === 'number' ? v : parseFloat(v);
        return isFinite(n) ? n : null;
    }

    function keyX(x) { return Number(x).toPrecision(9); }

    function copyFields(src, out) {
        if (!src.fields || typeof src.fields !== 'object') { return; }
        var f = {}, any = false;
        Object.keys(src.fields).forEach(function (k) {
            var v = src.fields[k];
            if (v !== null && v !== undefined && v !== '') { f[k] = String(v); any = true; }
        });
        if (any) { out.fields = f; }
    }

    function normalizeItem(item) {
        if (!item || typeof item !== 'object') { return null; }
        var out;
        if (item.kind === 'region') {
            var a = num(item.from), b = num(item.to);
            if (a === null || b === null || a === b) { return null; }
            out = {kind: 'region', from: Math.min(a, b), to: Math.max(a, b)};
            var integral = num(item.integral);
            if (integral !== null) { out.integral = integral; }
        } else {
            var x = num(item.x);
            if (x === null) { return null; }
            out = {kind: 'peak', x: x};
            var y = num(item.y);
            if (y !== null) { out.y = y; }
            out.source = item.source === 'auto' ? 'auto' : 'manual';
            var w = num(item.width);
            if (w !== null && w >= 0) { out.width = w; }
        }
        copyFields(item, out);
        return out;
    }

    function key(item) {
        return item.kind === 'region' ? 'r:' + keyX(item.from) + ':' + keyX(item.to) : 'p:' + keyX(item.x);
    }

    function trim(x) { return String(Number(Number(x).toFixed(4))); }

    function describe(item) {
        if (!item) { return ''; }
        var fields = item.fields ? Object.keys(item.fields).map(function (k) { return item.fields[k]; }) : [];
        var extra = fields.length ? ' (' + fields.join(', ') + ')' : '';
        if (item.kind === 'region') { return 'region ' + trim(item.from) + '–' + trim(item.to) + extra; }
        return 'peak at ' + trim(item.x) + (item.source === 'auto' ? ', suggested' : '') + extra;
    }

    function describeContext(sel) {
        var n = sel && Array.isArray(sel.rejected) ? sel.rejected.length : 0;
        return n ? n + ' suggestion' + (n === 1 ? '' : 's') + ' rejected' : '';
    }

    // ------------------------------------------------------------------
    // Colours from the page's theme tokens
    // ------------------------------------------------------------------

    function rgba(colour, alpha) {
        var c = String(colour || '').trim();
        var m = /^#([0-9a-f]{3})$/i.exec(c);
        if (m) { c = '#' + m[1].split('').map(function (h) { return h + h; }).join(''); }
        m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})/i.exec(c);
        if (m) {
            return 'rgba(' + parseInt(m[1], 16) + ',' + parseInt(m[2], 16) + ',' + parseInt(m[3], 16) + ',' + alpha + ')';
        }
        m = /^rgba?\(([^)]+)\)/i.exec(c);
        if (m) {
            var p = m[1].split(',').slice(0, 3).map(function (s) { return s.trim(); });
            return 'rgba(' + p.join(',') + ',' + alpha + ')';
        }
        return c;
    }

    function theme(element) {
        var cs = getComputedStyle(element);
        function v(name, fallback) {
            var val = cs.getPropertyValue(name).trim();
            return val || fallback;
        }
        return {
            fg: v('--sp-line', '#09090b'),
            muted: v('--muted-foreground', '#71717a'),
            grid: v('--sp-grid', '#e4e4e7'),
            card: v('--card', '#ffffff'),
            peak: v('--sp-peak', '#6e56cf'),
            suggest: v('--sp-suggest', '#c2410c'),
            region: v('--sp-region', '#6e56cf'),
            font: cs.fontFamily || 'sans-serif'
        };
    }

    // ------------------------------------------------------------------
    // Toolbar
    // ------------------------------------------------------------------

    var MODES = [
        {id: 'pick', label: 'Pick', hint: 'Click a peak to pick it. Click a picked peak to remove it. Drag to zoom.'},
        {id: 'pan', label: 'Pan', hint: 'Drag to move along the spectrum.'},
        {id: 'integrate', label: 'Integrate', hint: 'Drag across a multiplet to integrate it. Click inside a region to remove it.'}
    ];

    function buildToolbar(ctx) {
        var cfg = ctx.config;
        var bar = document.createElement('div');
        bar.className = 'sp-toolbar';
        bar.setAttribute('role', 'toolbar');
        bar.setAttribute('aria-label', 'Spectrum tools');
        var group = document.createElement('div');
        group.className = 'sp-modes';
        MODES.forEach(function (m) {
            if (m.id === 'integrate' && !cfg.integrate) { return; }
            var b = document.createElement('button');
            b.type = 'button';
            b.className = 'sp-btn sp-mode';
            b.setAttribute('data-mode', m.id);
            b.setAttribute('aria-pressed', m.id === 'pick' ? 'true' : 'false');
            b.textContent = m.label;
            b.disabled = true;
            group.appendChild(b);
        });
        bar.appendChild(group);
        var reset = document.createElement('button');
        reset.type = 'button';
        reset.className = 'sp-btn sp-reset';
        reset.textContent = 'Reset view';
        reset.disabled = true;
        bar.appendChild(reset);
        var hint = document.createElement('p');
        hint.className = 'sp-hint';
        hint.textContent = MODES[0].hint;
        bar.appendChild(hint);
        ctx.element.insertBefore(bar, ctx.element.firstChild);
        return bar;
    }

    // ------------------------------------------------------------------
    // The viewer
    // ------------------------------------------------------------------

    function instanceId() {
        var input = document.getElementById('instance_id');
        return input ? input.value : '';
    }

    function Spectrum(ctx) {
        this.ctx = ctx;
        this.cfg = ctx.config;
        this.viewer = ctx.viewer;
        this.gd = ctx.stage;
        this.mode = 'pick';
        this.allowManual = true;
        this.overview = {x: this.cfg.x || [], y: this.cfg.y || []};
        this.detail = null;
        this.toolbar = ctx.element.querySelector('.sp-toolbar');
        var ys = this.overview.y;
        var lo = Infinity, hi = -Infinity;
        for (var i = 0; i < ys.length; i++) { if (ys[i] < lo) { lo = ys[i]; } if (ys[i] > hi) { hi = ys[i]; } }
        this.yLo = isFinite(lo) ? lo : 0;
        this.yHi = isFinite(hi) ? hi : 1;
        this.units = this.cfg.xUnits || '';
    }

    Spectrum.prototype.format = function (x) {
        var d = typeof this.cfg.decimals === 'number' ? this.cfg.decimals : 3;
        return Number(x).toFixed(d);
    };

    Spectrum.prototype.points = function () {
        if (!this.detail) { return this.overview; }
        var o = this.overview, d = this.detail, xs = [], ys = [], i;
        for (i = 0; i < o.x.length && o.x[i] < d.from; i++) { xs.push(o.x[i]); ys.push(o.y[i]); }
        for (i = 0; i < d.x.length; i++) { xs.push(d.x[i]); ys.push(d.y[i]); }
        for (i = 0; i < o.x.length; i++) { if (o.x[i] > d.to) { xs.push(o.x[i]); ys.push(o.y[i]); } }
        return {x: xs, y: ys};
    };

    /* y of the drawn spectrum at x (linear interpolation). */
    Spectrum.prototype.valueAt = function (x) {
        var p = this.points(), xs = p.x, ys = p.y;
        if (!xs.length) { return 0; }
        if (x <= xs[0]) { return ys[0]; }
        if (x >= xs[xs.length - 1]) { return ys[ys.length - 1]; }
        var lo = 0, hi = xs.length - 1;
        while (hi - lo > 1) { var mid = (lo + hi) >> 1; if (xs[mid] <= x) { lo = mid; } else { hi = mid; } }
        var t = (x - xs[lo]) / ((xs[hi] - xs[lo]) || 1);
        return ys[lo] + t * (ys[hi] - ys[lo]);
    };

    /* The point a click at x picks: the local extreme within `tol` x units
       (snap on), or the curve at x. For sticks, the nearest stick. */
    Spectrum.prototype.snap = function (x, tol) {
        var p = this.points(), xs = p.x, ys = p.y, best = -1, i;
        if (this.cfg.sticks) {
            var bestD = Infinity;
            for (i = 0; i < xs.length; i++) {
                var dd = Math.abs(xs[i] - x);
                if (dd < bestD) { bestD = dd; best = i; }
            }
            return best >= 0 && bestD <= tol * 1.5 ? {x: xs[best], y: ys[best]} : null;
        }
        if (!this.cfg.snap) { return {x: x, y: this.valueAt(x)}; }
        var down = this.cfg.direction === 'min';
        for (i = 0; i < xs.length; i++) {
            if (xs[i] < x - tol || xs[i] > x + tol) { continue; }
            if (best < 0 || (down ? ys[i] < ys[best] : ys[i] > ys[best])) { best = i; }
        }
        return best >= 0 ? {x: xs[best], y: ys[best]} : {x: x, y: this.valueAt(x)};
    };

    Spectrum.prototype.selection = function () { return this.viewer.getSelection(); };

    Spectrum.prototype.suggestions = function () { return (this.cfg.suggestions || []).slice(); };

    Spectrum.prototype.suggestionState = function (s, sel) {
        sel = sel || this.selection();
        var k = keyX(s.x);
        if ((sel.rejected || []).some(function (r) { return keyX(r) === k; })) { return 'rejected'; }
        if (sel.items.some(function (it) { return it.kind === 'peak' && keyX(it.x) === k; })) { return 'accepted'; }
        return 'pending';
    };

    Spectrum.prototype.pendingSuggestions = function (sel) {
        var self = this;
        sel = sel || this.selection();
        return this.suggestions().filter(function (s) { return self.suggestionState(s, sel) === 'pending'; });
    };

    function suggestionItem(s) {
        var item = {kind: 'peak', x: s.x, y: s.y, source: 'auto'};
        if (typeof s.width === 'number') { item.width = s.width; }
        if (s.label) { item.fields = {label: String(s.label)}; }
        return item;
    }

    Spectrum.prototype.accept = function (list) {
        var sel = this.selection(), self = this;
        [].concat(list).forEach(function (s) {
            var k = keyX(s.x);
            sel.rejected = (sel.rejected || []).filter(function (r) { return keyX(r) !== k; });
            if (!sel.items.some(function (it) { return it.kind === 'peak' && keyX(it.x) === k; })) {
                sel.items.push(suggestionItem(s));
            }
        });
        this.viewer.userChange(sel);
    };

    Spectrum.prototype.reject = function (list) {
        var sel = this.selection();
        sel.rejected = sel.rejected || [];
        [].concat(list).forEach(function (s) {
            var k = keyX(s.x);
            sel.items = sel.items.filter(function (it) { return !(it.kind === 'peak' && keyX(it.x) === k); });
            if (!sel.rejected.some(function (r) { return keyX(r) === k; })) { sel.rejected.push(s.x); }
        });
        this.viewer.userChange(sel);
    };

    Spectrum.prototype.restore = function (x) {
        var sel = this.selection(), k = keyX(x);
        sel.rejected = (sel.rejected || []).filter(function (r) { return keyX(r) !== k; });
        this.viewer.userChange(sel);
    };

    Spectrum.prototype.addPeakAt = function (x, tol) {
        var span = Math.abs((this.cfg.xRange || [0, 1])[1] - (this.cfg.xRange || [0, 1])[0]) || 1;
        var pt = this.snap(x, tol === undefined ? span / 400 : tol);
        if (!pt) { return null; }
        var sugg = this.suggestions().filter(function (s) { return keyX(s.x) === keyX(pt.x); })[0];
        if (sugg) { this.accept(sugg); return suggestionItem(sugg); }
        var item = {kind: 'peak', x: pt.x, y: pt.y, source: 'manual'};
        if (this.viewer.hasItem(item)) { return item; }
        var sel = this.selection();
        sel.items.push(item);
        this.viewer.userChange(sel);
        return item;
    };

    /* A region's integral relative to the first region (1.00). */
    Spectrum.prototype.relative = function (region, sel) {
        sel = sel || this.selection();
        var first = sel.items.filter(function (it) { return it.kind === 'region'; })[0];
        if (!first || typeof first.integral !== 'number' || !first.integral ||
                typeof region.integral !== 'number') { return null; }
        return region.integral / first.integral;
    };

    Spectrum.prototype.setAllowManual = function (on) { this.allowManual = !!on; };

    Spectrum.prototype.setMode = function (mode) {
        if (mode === 'integrate' && !this.cfg.integrate) { return; }
        this.mode = mode;
        var bar = this.toolbar;
        if (bar) {
            bar.querySelectorAll('.sp-mode').forEach(function (b) {
                b.setAttribute('aria-pressed', b.getAttribute('data-mode') === mode ? 'true' : 'false');
            });
            var hint = bar.querySelector('.sp-hint');
            var m = MODES.filter(function (x) { return x.id === mode; })[0];
            if (hint && m) { hint.textContent = m.hint; }
        }
        if (window.Plotly && this.gd.layout) {
            window.Plotly.relayout(this.gd, {dragmode: mode === 'integrate' ? 'select' : mode === 'pan' ? 'pan' : 'zoom'});
        }
    };

    Spectrum.prototype.resetView = function () {
        this.detail = null;
        this.paint(this.selection());
        window.Plotly.relayout(this.gd, {'xaxis.autorange': this.cfg.reversed ? 'reversed' : true,
                                         'yaxis.autorange': true});
    };

    Spectrum.prototype.zoomTo = function (a, b) {
        var lo = Math.min(a, b), hi = Math.max(a, b);
        window.Plotly.relayout(this.gd, {'xaxis.range': this.cfg.reversed ? [hi, lo] : [lo, hi]});
    };

    Spectrum.prototype.fetchRange = function (a, b) {
        var url = this.cfg.rangeUrl + '?instance_id=' + encodeURIComponent(instanceId()) +
            '&field=' + encodeURIComponent(this.cfg.field) + '&x0=' + a + '&x1=' + b;
        return fetch(url, {credentials: 'same-origin'}).then(function (r) {
            if (!r.ok) { throw new Error('HTTP ' + r.status); }
            return r.json();
        });
    };

    /* Trapezoid integral on the drawn points: the fallback when the server
       cannot be asked (it integrates every original point). */
    Spectrum.prototype.localIntegral = function (a, b) {
        var p = this.points(), xs = p.x, ys = p.y, sum = 0;
        for (var i = 1; i < xs.length; i++) {
            var x0 = Math.max(a, xs[i - 1]), x1 = Math.min(b, xs[i]);
            if (x1 <= x0) { continue; }
            sum += (x1 - x0) * (this.valueAt(x0) + this.valueAt(x1)) / 2;
        }
        return sum;
    };

    Spectrum.prototype.addRegion = function (a, b) {
        var self = this, lo = Math.min(a, b), hi = Math.max(a, b);
        if (!(hi > lo)) { return Promise.resolve(null); }
        var done = function (integral) {
            var sel = self.selection();
            var region = {kind: 'region', from: lo, to: hi, integral: integral};
            sel.items.push(region);
            self.viewer.userChange(sel);
            return region;
        };
        return this.fetchRange(lo, hi).then(function (r) { return done(r.integral); })
            .catch(function () { return done(self.localIntegral(lo, hi)); });
    };

    Spectrum.prototype.markerY = function (item) {
        var pad = (this.yHi - this.yLo) * 0.045;
        var y = typeof item.y === 'number' ? item.y : this.valueAt(item.x);
        return this.cfg.direction === 'min' ? y - pad : y + pad;
    };

    /* Annotation text is HTML-ish in Plotly: escape what the annotator typed. */
    function escapeText(text) {
        return String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    function labelOf(item) {
        if (item.fields) {
            var v = Object.keys(item.fields).map(function (k) { return item.fields[k]; }).filter(Boolean);
            if (v.length) { return v.join(' · '); }
        }
        return item.label || '';
    }

    // Integrate mode uses Plotly's box select, which would fade every marker
    // outside the box; markers keep their look.
    var KEEP = {marker: {opacity: 1}};

    Spectrum.prototype.traces = function (sel) {
        var cfg = this.cfg, t = this.colours, self = this, p = this.points();
        var lineX = p.x, lineY = p.y;
        if (cfg.sticks) {
            lineX = []; lineY = [];
            for (var i = 0; i < p.x.length; i++) {
                lineX.push(p.x[i], p.x[i], null);
                lineY.push(0, p.y[i], null);
            }
        }
        var fmt = '%{x:.' + (cfg.decimals || 0) + 'f}';
        var peaks = sel.items.filter(function (it) { return it.kind === 'peak'; });
        var pending = this.pendingSuggestions(sel);
        var down = cfg.direction === 'min';
        return [
            {x: lineX, y: lineY, type: 'scatter', mode: 'lines', name: 'spectrum',
             line: {color: t.fg, width: cfg.sticks ? 1.6 : 1.1}, connectgaps: false,
             hovertemplate: fmt + ', %{y:.4g}<extra></extra>'},
            {x: pending.map(function (s) { return s.x; }),
             y: pending.map(function (s) { return self.markerY(s); }),
             type: 'scatter', mode: 'markers', name: 'suggested',
             marker: {symbol: down ? 'triangle-up-open' : 'triangle-down-open', size: 12,
                      color: t.suggest, line: {width: 2, color: t.suggest}},
             hovertemplate: 'suggested ' + fmt + ': click to accept<extra></extra>',
             selectedpoints: null, selected: KEEP, unselected: KEEP},
            {x: peaks.map(function (it) { return it.x; }),
             y: peaks.map(function (it) { return self.markerY(it); }),
             type: 'scatter', mode: 'markers', name: 'peaks',
             marker: {symbol: down ? 'triangle-up' : 'triangle-down', size: 12, color: t.peak,
                      line: {width: 1, color: t.card}},
             hovertemplate: 'peak ' + fmt + '<extra></extra>', cliponaxis: false,
             selectedpoints: null, selected: KEEP, unselected: KEEP}
        ];
    };

    Spectrum.prototype.layout = function (sel) {
        var cfg = this.cfg, t = this.colours, self = this;
        var regions = sel.items.filter(function (it) { return it.kind === 'region'; });
        var down = cfg.direction === 'min';
        var axis = function (title) {
            // Titles can come from the file's units or the config: Plotly reads
            // tags in title text, so they are escaped like peak labels.
            return {title: {text: escapeText(title || ''), standoff: 8}, gridcolor: t.grid, linecolor: t.grid,
                    zeroline: false, ticks: 'outside', tickcolor: t.grid, color: t.fg,
                    automargin: true};
        };
        var x = axis(cfg.xLabel);
        x.autorange = cfg.reversed ? 'reversed' : true;
        var y = axis(cfg.yLabel);
        y.exponentformat = 'SI';
        // A new datarevision every paint: Plotly.react otherwise skipped
        // redrawing the peak labels when only their text changed.
        this._revision = (this._revision || 0) + 1;
        return {
            uirevision: 'spectrum',
            datarevision: this._revision,
            selections: [],
            margin: {l: 56, r: 12, t: 28, b: 44},
            paper_bgcolor: t.card, plot_bgcolor: t.card,
            font: {color: t.fg, family: t.font, size: 12},
            xaxis: x, yaxis: y,
            dragmode: this.mode === 'integrate' ? 'select' : this.mode === 'pan' ? 'pan' : 'zoom',
            selectdirection: 'h',
            hovermode: 'x', hoverdistance: -1, spikedistance: -1,
            hoverlabel: {bgcolor: t.card, bordercolor: t.grid, font: {color: t.fg}},
            showlegend: false,
            shapes: regions.map(function (r) {
                return {type: 'rect', xref: 'x', yref: 'paper', x0: r.from, x1: r.to, y0: 0, y1: 1,
                        fillcolor: rgba(t.region, 0.14), line: {width: 1, color: rgba(t.region, 0.5)},
                        layer: 'below'};
            }),
            // Peak labels are annotations, not trace text: Plotly.react did
            // not redraw a scatter trace's text when only the text changed.
            annotations: sel.items.filter(function (it) { return it.kind === 'peak' && labelOf(it); })
                .map(function (it) {
                    return {x: it.x, xref: 'x', y: self.markerY(it), yref: 'y', text: escapeText(labelOf(it)),
                            showarrow: false, yshift: down ? -14 : 14, font: {size: 11, color: t.fg},
                            bgcolor: rgba(t.card, 0.85)};
                }).concat(regions.map(function (r) {
                var rel = self.relative(r, sel);
                return {x: (r.from + r.to) / 2, xref: 'x', y: 1, yref: 'paper', yanchor: 'bottom',
                        text: rel === null ? '∫' : '∫ ' + rel.toFixed(2), showarrow: false,
                        font: {size: 11, color: t.fg}};
            }))
        };
    };

    Spectrum.prototype.paint = function (sel) {
        if (!window.Plotly) { return; }
        this.colours = theme(this.ctx.element);
        window.Plotly.react(this.gd, this.traces(sel), this.layout(sel), PLOT_CONFIG);
    };

    var PLOT_CONFIG = {displayModeBar: false, responsive: true, scrollZoom: false,
                       doubleClick: 'reset', displaylogo: false, showTips: false};

    /* Data x under a mouse event, and how many x units `px` pixels span. */
    Spectrum.prototype.eventX = function (event, px) {
        var fl = this.gd._fullLayout, xa = fl && fl.xaxis;
        var drag = this.gd.querySelector('.nsewdrag');
        if (!xa || !drag || !event) { return null; }
        var bb = drag.getBoundingClientRect();
        var pos = event.clientX - bb.left;
        if (pos < 0 || pos > bb.width || event.clientY < bb.top || event.clientY > bb.bottom) { return null; }
        var x = xa.p2l(pos);
        return {x: x, tol: Math.abs(xa.p2l(pos + (px || 8)) - x)};
    };

    Spectrum.prototype.onClick = function (ev) {
        var e = ev && ev.event;
        var at = this.eventX(e, 9);
        if (!at) { return; }
        var sel = this.selection();
        if (this.mode === 'integrate') {
            var inside = sel.items.filter(function (it) {
                return it.kind === 'region' && at.x >= it.from && at.x <= it.to;
            })[0];
            if (inside) { this.viewer.toggleItem(inside); }
            return;
        }
        if (this.mode !== 'pick') { return; }
        var nearest = function (list, getX) {
            var best = null, bestD = Infinity;
            list.forEach(function (it) {
                var d = Math.abs(getX(it) - at.x);
                if (d < bestD) { bestD = d; best = it; }
            });
            return bestD <= at.tol ? best : null;
        };
        var hit = nearest(sel.items.filter(function (it) { return it.kind === 'peak'; }),
                          function (it) { return it.x; });
        if (hit) { this.viewer.toggleItem(hit); return; }
        var sugg = nearest(this.pendingSuggestions(sel), function (s) { return s.x; });
        if (sugg) { this.accept(sugg); return; }
        if (!this.allowManual) {
            this.ctx.status('Only suggested peaks can be picked in this task.');
            return;
        }
        var added = this.addPeakAt(at.x, at.tol);
        if (!added) { this.ctx.status('No peak there: click on or next to a line.'); }
    };

    Spectrum.prototype.onSelected = function (ev) {
        if (this.mode !== 'integrate' || !ev || !ev.range || !ev.range.x) { return; }
        var r = ev.range.x;
        var self = this;
        // The repaint that adds the region also clears Plotly's own selection
        // box (layout.selections is always empty) and its dimming.
        window.Plotly.restyle(this.gd, {selectedpoints: [null]});
        this.addRegion(r[0], r[1]).then(function (region) {
            if (!region) { self.paint(self.selection()); }
        });
    };

    Spectrum.prototype.onRelayout = function (ev) {
        var cfg = this.cfg, self = this;
        if (!ev) { return; }
        if (ev['xaxis.autorange'] !== undefined) {
            if (this.detail) { this.detail = null; this.paint(this.selection()); }
            return;
        }
        var a = ev['xaxis.range[0]'], b = ev['xaxis.range[1]'];
        if (a === undefined && Array.isArray(ev['xaxis.range'])) { a = ev['xaxis.range'][0]; b = ev['xaxis.range'][1]; }
        if (a === undefined || b === undefined || !(cfg.totalPoints > cfg.shownPoints)) { return; }
        clearTimeout(this._zoomTimer);
        this._zoomTimer = setTimeout(function () {
            var lo = Math.min(a, b), hi = Math.max(a, b);
            self.fetchRange(lo, hi).then(function (r) {
                self.detail = {from: lo, to: hi, x: r.x, y: r.y};
                self.paint(self.selection());
                self.ctx.status(r.points > r.x.length ? '' : 'Showing every point in this range.');
            }).catch(function () { /* keep the overview */ });
        }, 250);
    };

    Spectrum.prototype.start = function () {
        var self = this, Plotly = window.Plotly;
        if (!Plotly) { return Promise.reject(new Error('Plotly did not load')); }
        this.colours = theme(this.ctx.element);
        var sel = this.selection();
        return Plotly.newPlot(this.gd, this.traces(sel), this.layout(sel), PLOT_CONFIG).then(function () {
            // Plotly reports a tap on a touch screen as a click too.
            self.gd.on('plotly_click', function (ev) { self.onClick(ev); });
            self.gd.on('plotly_selected', function (ev) { self.onSelected(ev); });
            self.gd.on('plotly_relayout', function (ev) { self.onRelayout(ev); });
            self.viewer.addPainter(function (s) { self.paint(s); });
            var bar = self.toolbar;
            if (bar) {
                bar.querySelectorAll('button').forEach(function (b) { b.disabled = false; });
                bar.querySelectorAll('.sp-mode').forEach(function (b) {
                    b.addEventListener('click', function () { self.setMode(b.getAttribute('data-mode')); });
                });
                bar.querySelector('.sp-reset').addEventListener('click', function () { self.resetView(); });
            }
            // Repaint when the page switches between light and dark.
            var repaint = function () { self.paint(self.selection()); };
            new MutationObserver(repaint).observe(document.documentElement,
                {attributes: true, attributeFilter: ['data-theme', 'class']});
            var info = [];
            if (self.cfg.title) { info.push(self.cfg.title); }
            if (self.cfg.totalPoints > self.cfg.shownPoints) {
                info.push(self.cfg.totalPoints.toLocaleString('en-US') + ' points, ' +
                          self.cfg.shownPoints.toLocaleString('en-US') + ' drawn until you zoom in');
            }
            self.ctx.status(info.join(' · '));
        });
    };

    FW.register('spectrum', {
        key: key,
        normalizeItem: normalizeItem,
        describe: describe,
        describeContext: describeContext,
        context: ['rejected'],
        init: function (ctx) {
            if (!ctx.element.querySelector('.sp-toolbar')) { buildToolbar(ctx); }
            // Before Plotly loads, so a bound scheme can list the suggestions
            // (and accept them from the keyboard) while the plot is drawn.
            var sp = new Spectrum(ctx);
            ctx.viewer.spectrum = sp;
            ctx.viewer.engine = sp;
            document.dispatchEvent(new CustomEvent('potato:spectrum-init', {
                detail: {field: ctx.viewer.field, viewer: ctx.viewer}}));
        },
        start: function (ctx) {
            return ctx.viewer.spectrum.start();
        }
    });
})();

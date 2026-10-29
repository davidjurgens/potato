/*
 * time_series display: the uPlot adapter for the viewer framework.
 *
 * The page never holds the recording. For the visible range it asks
 *   GET /api/signals/window?instance_id=&field=&start=&end=&px=
 * and draws what comes back: raw samples ({t, v}) when the window is short,
 * otherwise each pixel bucket's minimum and maximum ({t, lo, hi}), drawn as a
 * zig-zag so the envelope looks like the dense signal. Responses are cached
 * here (and by the browser for five minutes).
 *
 * Each plot is a controller at window.PotatoTimeSeries.get(field):
 *   getView() -> {start, end}           setView(start, end)
 *   step(+1 | -1)                        zoom(factor[, centre])
 *   setEpochMode(seconds | null)         epoch(k) / epochIndex() / epochCount()
 *   setOverlays({intervals, events}[, layer])  each with color, label, channel, selected
 *   setOverviewMarks([{start, end, color}][, layer])
 *   on('view' | 'brush' | 'click', cb)   brush: {start, end, channel}
 *                                        click: {time, channel, x}
 *   channelNames(), timeLabel(t), meta
 * PotatoTimeSeries.whenReady(field, cb) calls back once the plot exists.
 * Events on document: 'potato:time-series-ready' {field, plot}.
 */
(function () {
    'use strict';
    if (window.PotatoTimeSeries) { return; }

    var plots = {};
    var waiting = {};

    function el(tag, attrs, children) {
        var node = document.createElement(tag);
        Object.keys(attrs || {}).forEach(function (k) {
            if (k === 'text') { node.textContent = attrs[k]; }
            else if (k === 'className') { node.className = attrs[k]; }
            else if (k.indexOf('on') === 0) { node.addEventListener(k.slice(2), attrs[k]); }
            else { node.setAttribute(k, attrs[k]); }
        });
        (children || []).forEach(function (c) { if (c) { node.appendChild(c); } });
        return node;
    }

    function token(name, fallback) {
        var v = getComputedStyle(document.documentElement).getPropertyValue(name);
        return (v && v.trim()) || fallback;
    }

    function instanceId() {
        var input = document.getElementById('instance_id');
        return input ? input.value : '';
    }

    // ------------------------------------------------------------------
    // Time labels
    // ------------------------------------------------------------------

    function pad2(n) { return (n < 10 ? '0' : '') + n; }

    function elapsed(t, decimals) {
        var sign = t < 0 ? '-' : '';
        t = Math.abs(t);
        var h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60);
        var s = t - h * 3600 - m * 60;
        var ss = decimals ? s.toFixed(decimals) : String(Math.floor(s + 1e-9));
        if (parseFloat(ss) < 10) { ss = '0' + ss; }
        return sign + (h ? h + ':' + pad2(m) : String(m)) + ':' + ss;
    }

    function Plot(ctx) {
        var cfg = ctx.config;
        this.ctx = ctx;
        this.cfg = cfg;
        this.field = cfg.field;
        this.element = ctx.element;
        this.meta = {channels: cfg.channels, tStart: cfg.tStart, tEnd: cfg.tEnd,
                     startTime: cfg.startTime, format: cfg.format};
        this.stacked = cfg.layout !== 'overlay';
        this.gain = 1;
        this.ranges = {};
        this.cache = [];
        this.token = 0;
        this.handlers = {view: [], brush: [], click: []};
        this.overlays = {intervals: [], events: []};
        this.marks = [];
        this.epochLength = null;
        var span = Math.min(cfg.window || 30, cfg.tEnd - cfg.tStart);
        this.view = {start: cfg.tStart, end: cfg.tStart + span};
        this.lastData = null;
    }

    Plot.prototype.timeLabel = function (t, span) {
        var cfg = this.cfg;
        span = span === undefined ? (this.view.end - this.view.start) : span;
        var fmt = cfg.timeFormat;
        if (fmt === 'auto') { fmt = cfg.timeUnit === 's' ? 'elapsed' : 'number'; }
        if (fmt === 'clock' && cfg.startTime) {
            var base = Date.parse(cfg.startTime.length <= 19 ? cfg.startTime + 'Z' : cfg.startTime);
            if (!isNaN(base)) {
                var d = new Date(base + t * 1000);
                var s = pad2(d.getUTCHours()) + ':' + pad2(d.getUTCMinutes()) + ':' + pad2(d.getUTCSeconds());
                if (span < 10) { s += '.' + String(d.getUTCMilliseconds()).padStart(3, '0').slice(0, 2); }
                return s;
            }
        }
        if (fmt === 'number') {
            var digits = span < 1 ? 4 : span < 100 ? 2 : span < 10000 ? 1 : 0;
            return t.toFixed(digits) + (cfg.timeUnit && cfg.timeUnit !== 's' ? '' : ' s');
        }
        return elapsed(t, span < 10 ? 2 : span < 120 ? 1 : 0);
    };

    // ------------------------------------------------------------------
    // Layout and drawing
    // ------------------------------------------------------------------

    Plot.prototype.channelNames = function () {
        return this.meta.channels.map(function (c) { return c.name; });
    };

    Plot.prototype.laneCentre = function (i) { return this.meta.channels.length - 1 - i; };

    /* The channel under a y position (CSS pixels from the plot's top), or null. */
    Plot.prototype.channelAtY = function (y) {
        if (!this.u) { return null; }
        if (!this.stacked) { return this.meta.channels.length === 1 ? this.meta.channels[0].name : null; }
        var v = this.u.posToVal(y, 'y');
        var n = this.meta.channels.length;
        var i = n - 1 - Math.round(v);
        if (i < 0 || i >= n) { return null; }
        return this.meta.channels[i].name;
    };

    Plot.prototype.colors = function () {
        var dark = document.documentElement.getAttribute('data-theme') === 'dark';
        return {
            fg: token('--foreground', dark ? '#fafafa' : '#09090b'),
            muted: token('--muted-foreground', dark ? '#a1a1aa' : '#71717a'),
            border: token('--border', dark ? '#3f3f46' : '#e4e4e7'),
            card: token('--card', dark ? '#18181b' : '#ffffff'),
            trace: dark ? '#d4d4d8' : '#27272a',
            palette: ['#0072B2', '#E69F00', '#009E73', '#D55E00', '#CC79A7', '#56B4E9', '#8C6D1F', '#6C757D'],
            dark: dark
        };
    };

    Plot.prototype.build = function () {
        var self = this, cfg = this.cfg, stage = this.ctx.stage;
        var n = this.meta.channels.length;
        var col = this.colors();
        this.col = col;
        var narrow = (stage.clientWidth || 600) < 520;
        var longest = this.meta.channels.reduce(function (m, c) {
            return Math.max(m, String(c.label || c.name).length);
        }, 4);
        var ySize = this.stacked ? Math.min(narrow ? 64 : 150, 14 + longest * 7) : (narrow ? 48 : 64);
        var series = [{}];
        this.meta.channels.forEach(function (c, i) {
            var colour = c.color || (self.stacked ? col.trace : col.palette[i % col.palette.length]);
            var s = {label: c.label || c.name, stroke: colour, width: 1, spanGaps: false,
                     points: {show: cfg.draw === 'points', size: 4, fill: colour, stroke: colour}};
            if (cfg.draw === 'points') { s.paths = function () { return null; }; }
            series.push(s);
        });
        var axisFont = '11px system-ui, -apple-system, Segoe UI, sans-serif';
        var opts = {
            width: Math.max(200, stage.clientWidth || 600),
            height: cfg.plotHeight,
            pxAlign: 0,
            legend: {show: !this.stacked && n > 1},
            cursor: {drag: {x: false, y: false}, points: {show: false}, y: false},
            select: {show: false},
            scales: {
                x: {time: false, auto: false, range: function () { return [self.view.start, self.view.end]; }},
                y: this.stacked ? {auto: false, range: [-0.5, n - 0.5]}
                                : {auto: true, dir: cfg.invertY ? -1 : 1,
                                   range: function (u, mn, mx) { return self.overlayRange(mn, mx); }}
            },
            series: series,
            axes: [
                {stroke: col.muted, font: axisFont, grid: {stroke: col.border, width: 1},
                 ticks: {stroke: col.border}, size: 34,
                 values: function (u, splits) {
                     var span = self.view.end - self.view.start;
                     return splits.map(function (t) { return self.timeLabel(t, span); });
                 }},
                this.stacked ? {
                    stroke: col.fg, font: axisFont, size: ySize, gap: 4,
                    grid: {stroke: col.border, width: 1}, ticks: {show: false},
                    splits: function () {
                        var out = [];
                        for (var i = 0; i < n; i++) { out.push(self.laneCentre(i)); }
                        return out;
                    },
                    values: function (u, splits) {
                        return splits.map(function (v) {
                            var c = self.meta.channels[n - 1 - Math.round(v)];
                            var name = c ? String(c.label || c.name) : '';
                            var max = Math.max(4, Math.floor((ySize - 10) / 7));
                            return name.length > max ? name.slice(0, max - 1) + '…' : name;
                        });
                    }
                } : {stroke: col.muted, font: axisFont, size: ySize,
                     grid: {stroke: col.border, width: 1}, ticks: {stroke: col.border},
                     label: this.meta.channels.length === 1 ? (this.meta.channels[0].unit || '') : '',
                     labelSize: 14, labelFont: axisFont}
            ],
            hooks: {draw: [function (u) { self.drawOverlays(u); }]}
        };
        var empty = [[]];
        for (var i = 0; i < n; i++) { empty.push([]); }
        this.u = new window.uPlot(opts, empty, stage);
        this.bindPointer();
    };

    Plot.prototype.overlayRange = function (mn, mx) {
        var lo = Infinity, hi = -Infinity, self = this;
        this.meta.channels.forEach(function (c) {
            var r = c.range || (self.cfg.amplitude === 'recording' ? self.ranges[c.name] : null);
            if (r) { lo = Math.min(lo, r[0]); hi = Math.max(hi, r[1]); }
        });
        if (!isFinite(lo)) { lo = mn; hi = mx; }
        if (lo === null || hi === null || !isFinite(lo) || !isFinite(hi)) { return [0, 1]; }
        if (hi <= lo) { lo -= 1; hi += 1; }
        var mid = (lo + hi) / 2, half = (hi - lo) / 2 / this.gain * 1.08;
        return [mid - half, mid + half];
    };

    Plot.prototype.drawOverlays = function (u) {
        var c = u.ctx, self = this, dpr = window.devicePixelRatio || 1;
        var top = u.bbox.top, height = u.bbox.height, left = u.bbox.left, width = u.bbox.width;
        c.save();
        c.beginPath();
        c.rect(left, top, width, height);
        c.clip();
        // uPlot leaves the axis text alignment on the context.
        c.textAlign = 'left';
        var laneBand = function (name) {
            if (!name || !self.stacked) { return [top, height]; }
            var i = self.channelNames().indexOf(name);
            if (i < 0) { return [top, height]; }
            var y0 = u.valToPos(self.laneCentre(i) + 0.5, 'y', true);
            var y1 = u.valToPos(self.laneCentre(i) - 0.5, 'y', true);
            return [Math.min(y0, y1), Math.abs(y1 - y0)];
        };
        (this.overlays.intervals || []).forEach(function (iv) {
            if (iv.end <= self.view.start + 1e-9 || iv.start >= self.view.end - 1e-9) { return; }
            var x0 = u.valToPos(iv.start, 'x', true), x1 = u.valToPos(iv.end, 'x', true);
            var band = laneBand(iv.channel);
            c.globalAlpha = iv.selected ? 0.32 : 0.18;
            c.fillStyle = iv.color || '#0072B2';
            c.fillRect(x0, band[0], Math.max(1, x1 - x0), band[1]);
            c.globalAlpha = 1;
            c.strokeStyle = iv.color || '#0072B2';
            c.lineWidth = (iv.selected ? 2.5 : 1) * dpr;
            if (iv.dashed) { c.setLineDash([4 * dpr, 3 * dpr]); }
            c.strokeRect(x0, band[0] + 0.5, Math.max(1, x1 - x0), band[1] - 1);
            c.setLineDash([]);
            if (x1 - Math.max(x0, left) > 30 * dpr && iv.label) {
                c.font = (11 * dpr) + 'px system-ui, sans-serif';
                c.fillStyle = self.col.fg;
                c.textBaseline = 'top';
                c.fillText(iv.label, Math.max(x0, left) + 5 * dpr, band[0] + 4 * dpr, x1 - Math.max(x0, left) - 10 * dpr);
            }
        });
        (this.overlays.events || []).forEach(function (ev) {
            if (ev.time < self.view.start || ev.time > self.view.end) { return; }
            var x = u.valToPos(ev.time, 'x', true);
            var band = laneBand(ev.channel);
            c.strokeStyle = ev.color || '#D55E00';
            c.lineWidth = (ev.selected ? 3 : 1.5) * dpr;
            c.beginPath();
            c.moveTo(x, band[0]);
            c.lineTo(x, band[0] + band[1]);
            c.stroke();
            c.fillStyle = ev.color || '#D55E00';
            c.beginPath();
            c.moveTo(x - 5 * dpr, band[0]);
            c.lineTo(x + 5 * dpr, band[0]);
            c.lineTo(x, band[0] + 7 * dpr);
            c.closePath();
            c.fill();
            if (ev.label) {
                c.font = (11 * dpr) + 'px system-ui, sans-serif';
                c.fillStyle = self.col.fg;
                c.textBaseline = 'top';
                c.fillText(ev.label, x + 6 * dpr, band[0] + 2 * dpr);
            }
        });
        c.restore();
    };

    // ------------------------------------------------------------------
    // Pointer: brush and click (mouse, pen and touch alike)
    // ------------------------------------------------------------------

    Plot.prototype.bindPointer = function () {
        var self = this, over = this.u.over;
        var brush = el('div', {className: 'ts-brush', 'aria-hidden': 'true'});
        brush.hidden = true;
        over.appendChild(brush);
        var down = null;
        over.style.touchAction = 'pan-y';
        over.addEventListener('pointerdown', function (e) {
            if (e.button !== 0) { return; }
            var r = over.getBoundingClientRect();
            down = {x: e.clientX - r.left, y: e.clientY - r.top, id: e.pointerId, moved: false};
            try { over.setPointerCapture(e.pointerId); } catch (err) { /* old browsers */ }
            self.ctx.stage.focus({preventScroll: true});
        });
        over.addEventListener('pointermove', function (e) {
            if (!down || e.pointerId !== down.id) { return; }
            var r = over.getBoundingClientRect();
            var x = Math.max(0, Math.min(r.width, e.clientX - r.left));
            if (Math.abs(x - down.x) > 4) { down.moved = true; }
            if (!down.moved) { return; }
            var chan = self.brushChannel(down.y);
            brush.hidden = false;
            brush.style.left = Math.min(x, down.x) + 'px';
            brush.style.width = Math.abs(x - down.x) + 'px';
            var band = self.bandFor(chan);
            brush.style.top = band[0] + 'px';
            brush.style.height = band[1] + 'px';
            e.preventDefault();
        });
        var finish = function (e) {
            if (!down || e.pointerId !== down.id) { return; }
            var r = over.getBoundingClientRect();
            var x = Math.max(0, Math.min(r.width, e.clientX - r.left));
            var d = down;
            down = null;
            brush.hidden = true;
            if (e.type === 'pointercancel') { return; }
            if (d.moved) {
                var a = self.u.posToVal(Math.min(x, d.x), 'x'), b = self.u.posToVal(Math.max(x, d.x), 'x');
                self.emit('brush', {start: Math.max(self.meta.tStart, a), end: Math.min(self.meta.tEnd, b),
                                    channel: self.brushChannel(d.y), pointerChannel: self.channelAtY(d.y)});
            } else {
                self.emit('click', {time: self.u.posToVal(d.x, 'x'), channel: self.channelAtY(d.y),
                                    x: d.x, y: d.y});
            }
        };
        over.addEventListener('pointerup', finish);
        over.addEventListener('pointercancel', finish);
    };

    /* Which channel a brush started at y applies to: decided by the scheme's
       scope (set with setBrushScope): 'all' -> null, 'channel' -> the lane. */
    Plot.prototype.brushChannel = function (y) {
        return this.brushScope === 'channel' ? this.channelAtY(y) : null;
    };

    Plot.prototype.setBrushScope = function (scope) { this.brushScope = scope; };

    Plot.prototype.bandFor = function (name) {
        var u = this.u;
        var h = u.over.clientHeight;
        if (!name || !this.stacked) { return [0, h]; }
        var i = this.channelNames().indexOf(name);
        var y0 = u.valToPos(this.laneCentre(i) + 0.5, 'y'), y1 = u.valToPos(this.laneCentre(i) - 0.5, 'y');
        return [Math.min(y0, y1), Math.abs(y1 - y0)];
    };

    // ------------------------------------------------------------------
    // Data
    // ------------------------------------------------------------------

    Plot.prototype.px = function () {
        var w = this.u ? this.u.over.clientWidth : this.ctx.stage.clientWidth;
        return Math.max(100, Math.min(4000, Math.round(w || 800)));
    };

    Plot.prototype.load = function () {
        var self = this, v = this.view, px = this.px();
        var key = v.start.toFixed(6) + '|' + v.end.toFixed(6) + '|' + px;
        var hit = null;
        this.cache.forEach(function (c) { if (c.key === key) { hit = c.data; } });
        if (hit) { this.apply(hit); return Promise.resolve(hit); }
        var mine = ++this.token;
        var url = this.cfg.api + '?instance_id=' + encodeURIComponent(instanceId()) +
            '&field=' + encodeURIComponent(this.field) + '&start=' + v.start + '&end=' + v.end + '&px=' + px +
            '&channels=' + encodeURIComponent(this.channelNames().join(','));
        this.element.setAttribute('data-ts-loading', 'true');
        return fetch(url, {credentials: 'same-origin'}).then(function (r) {
            if (!r.ok) {
                return r.json().catch(function () { return {}; }).then(function (body) {
                    throw new Error(body.error || ('HTTP ' + r.status));
                });
            }
            return r.json();
        }).then(function (data) {
            self.cache.push({key: key, data: data});
            if (self.cache.length > 40) { self.cache.shift(); }
            if (mine === self.token) {
                self.element.removeAttribute('data-ts-loading');
                self.apply(data);
            }
            return data;
        }).catch(function (err) {
            if (mine === self.token) {
                self.element.removeAttribute('data-ts-loading');
                self.ctx.status('Could not load the signal: ' + err.message);
            }
            throw err;
        });
    };

    function insertGaps(xs, ys, gaps) {
        (gaps || []).forEach(function (g) {
            var mid = (g[0] + g[1]) / 2, lo = 0, hi = xs.length;
            while (lo < hi) { var m = (lo + hi) >> 1; if (xs[m] < mid) { lo = m + 1; } else { hi = m; } }
            xs.splice(lo, 0, mid);
            ys.splice(lo, 0, null);
        });
    }

    Plot.prototype.apply = function (data) {
        var self = this, n = this.meta.channels.length;
        Object.keys(data.ranges || {}).forEach(function (k) { self.ranges[k] = data.ranges[k]; });
        var byName = {};
        (data.channels || []).forEach(function (c) { byName[c.name] = c; });
        var tables = [];
        var winRanges = {};
        this.meta.channels.forEach(function (meta, i) {
            var c = byName[meta.name] || {t: [], v: []};
            var xs = [], ys = [];
            if (c.v) {
                xs = c.t.slice();
                ys = c.v.slice();
            } else if (c.lo) {
                var w = (data.end - data.start) / data.px;
                for (var k = 0; k < c.t.length; k++) {
                    xs.push(c.t[k] - w / 4, c.t[k] + w / 4);
                    ys.push(c.lo[k], c.hi[k]);
                }
            }
            var lo = Infinity, hi = -Infinity;
            ys.forEach(function (y) { if (y !== null) { if (y < lo) { lo = y; } if (y > hi) { hi = y; } } });
            winRanges[meta.name] = isFinite(lo) ? [lo, hi] : null;
            insertGaps(xs, ys, c.gaps);
            tables.push([xs, ys, i]);
        });
        this.windowRanges = winRanges;
        if (this.stacked) {
            tables.forEach(function (tb) {
                var meta = self.meta.channels[tb[2]];
                var r = meta.range || (self.cfg.amplitude === 'recording' ? self.ranges[meta.name] : null) ||
                        winRanges[meta.name] || [0, 1];
                var mid = (r[0] + r[1]) / 2, half = Math.max(1e-12, (r[1] - r[0]) / 2);
                var centre = self.laneCentre(tb[2]), k = 0.45 * self.gain / half;
                tb[1] = tb[1].map(function (y) {
                    if (y === null) { return null; }
                    var z = (y - mid) * k;
                    return centre + (z > 0.62 ? 0.62 : z < -0.62 ? -0.62 : z);
                });
            });
        }
        var aligned = window.uPlot.join(tables.map(function (tb) { return [tb[0], tb[1]]; }));
        this.lastData = data;
        this.u.setData(aligned, false);
        this.u.setScale('x', {min: this.view.start, max: this.view.end});
        this.element.setAttribute('data-ts-view', this.view.start.toFixed(3) + '-' + this.view.end.toFixed(3));
        this.element.setAttribute('data-ts-state', 'drawn');
        this.drawOverview();
    };

    // ------------------------------------------------------------------
    // View
    // ------------------------------------------------------------------

    Plot.prototype.clamp = function (start, end) {
        var t0 = this.meta.tStart, t1 = this.meta.tEnd, span = end - start;
        var minSpan = 0.05;
        this.meta.channels.forEach(function (c) { if (c.rate) { minSpan = Math.max(minSpan, 16 / c.rate); } });
        span = Math.max(Math.min(span, t1 - t0), Math.min(minSpan, t1 - t0));
        if (start < t0) { start = t0; }
        if (start + span > t1) { start = t1 - span; }
        return {start: start, end: start + span};
    };

    Plot.prototype.getView = function () { return {start: this.view.start, end: this.view.end}; };

    Plot.prototype.setView = function (start, end) {
        this.view = this.clamp(start, end);
        if (this.u) {
            this.u.setScale('x', {min: this.view.start, max: this.view.end});
            this.load().catch(function () { /* reported in the status line */ });
        }
        this.updateReadout();
        this.emit('view', this.getView());
        return this.getView();
    };

    Plot.prototype.step = function (dir) {
        if (this.epochLength) { return this.epoch(this.epochIndex() + dir); }
        var span = this.view.end - this.view.start;
        return this.setView(this.view.start + dir * span, this.view.end + dir * span);
    };

    Plot.prototype.pan = function (fraction) {
        var span = this.view.end - this.view.start;
        return this.setView(this.view.start + fraction * span, this.view.end + fraction * span);
    };

    Plot.prototype.zoom = function (factor, centre) {
        if (this.epochLength) { return this.getView(); }
        var v = this.view, c = centre === undefined ? (v.start + v.end) / 2 : centre;
        var span = (v.end - v.start) * factor;
        return this.setView(c - (c - v.start) * factor, c - (c - v.start) * factor + span);
    };

    Plot.prototype.fit = function () {
        if (this.epochLength) { return this.getView(); }
        return this.setView(this.meta.tStart, this.meta.tEnd);
    };

    Plot.prototype.setGain = function (g) {
        this.gain = Math.max(0.05, Math.min(50, g));
        if (this.lastData) { this.apply(this.lastData); }
        if (!this.stacked && this.u) { this.u.redraw(true, true); }
    };

    Plot.prototype.epochCount = function () {
        if (!this.epochLength) { return 0; }
        return Math.max(1, Math.ceil((this.meta.tEnd - this.meta.tStart) / this.epochLength - 1e-9));
    };

    Plot.prototype.epochIndex = function () {
        if (!this.epochLength) { return 0; }
        return Math.max(0, Math.min(this.epochCount() - 1,
            Math.round((this.view.start - this.meta.tStart) / this.epochLength)));
    };

    Plot.prototype.epochBounds = function (k) {
        var s = this.meta.tStart + k * this.epochLength;
        return {start: s, end: Math.min(this.meta.tEnd, s + this.epochLength)};
    };

    Plot.prototype.epoch = function (k) {
        k = Math.max(0, Math.min(this.epochCount() - 1, k));
        var b = this.epochBounds(k);
        // The last epoch may be short; keep the width so the scale stays put.
        this.view = {start: b.start, end: b.start + this.epochLength};
        if (this.u) {
            this.u.setScale('x', {min: this.view.start, max: this.view.end});
            this.load().catch(function () { /* reported in the status line */ });
        }
        this.updateReadout();
        this.emit('view', this.getView());
        return this.getView();
    };

    Plot.prototype.setEpochMode = function (seconds) {
        this.epochLength = seconds || null;
        this.element.classList.toggle('ts-epoch-mode', !!this.epochLength);
        if (this.epochLength) { this.epoch(this.epochIndex()); }
    };

    Plot.prototype.updateReadout = function () {
        if (!this.readout) { return; }
        var v = this.view, span = v.end - v.start;
        var text = this.timeLabel(v.start, span) + ' – ' + this.timeLabel(Math.min(v.end, this.meta.tEnd), span) +
            ' of ' + this.timeLabel(this.meta.tEnd, this.meta.tEnd - this.meta.tStart);
        if (this.epochLength) { text = 'Epoch ' + (this.epochIndex() + 1) + ' of ' + this.epochCount() + ' · ' + text; }
        this.readout.textContent = text;
        this.ctx.stage.setAttribute('aria-label', 'Signal plot, ' + this.meta.channels.length +
            ' channel' + (this.meta.channels.length === 1 ? '' : 's') + ', showing ' + text +
            '. Arrow keys move, plus and minus zoom.');
        this.drawOverview();
    };

    // ------------------------------------------------------------------
    // Overlays, overview strip
    // ------------------------------------------------------------------

    /* Overlays and marks are kept per layer (one per interval_label scheme),
       so two schemes on one plot do not erase each other. */
    Plot.prototype.setOverlays = function (o, layer) {
        this.layers = this.layers || {};
        this.layers[layer || '_'] = {intervals: (o && o.intervals) || [], events: (o && o.events) || []};
        var all = {intervals: [], events: []}, layers = this.layers;
        Object.keys(layers).forEach(function (k) {
            all.intervals = all.intervals.concat(layers[k].intervals);
            all.events = all.events.concat(layers[k].events);
        });
        this.overlays = all;
        if (this.u) { this.u.redraw(false, false); }
    };

    Plot.prototype.setOverviewMarks = function (marks, layer) {
        this.markLayers = this.markLayers || {};
        this.markLayers[layer || '_'] = marks || [];
        var all = [], ml = this.markLayers;
        Object.keys(ml).forEach(function (k) { all = all.concat(ml[k]); });
        this.marks = all;
        this.drawOverview();
    };

    Plot.prototype.drawOverview = function () {
        var cv = this.overviewCanvas;
        if (!cv) { return; }
        var dpr = window.devicePixelRatio || 1;
        var w = cv.clientWidth, h = cv.clientHeight;
        if (!w || !h) { return; }
        if (cv.width !== Math.round(w * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
        var c = cv.getContext('2d'), col = this.colors();
        var t0 = this.meta.tStart, t1 = this.meta.tEnd, span = (t1 - t0) || 1;
        var X = function (t) { return (t - t0) / span * cv.width; };
        c.clearRect(0, 0, cv.width, cv.height);
        c.fillStyle = col.dark ? '#27272a' : '#f4f4f5';
        c.fillRect(0, 0, cv.width, cv.height);
        var env = this.overviewEnvelope;
        if (env) {
            c.strokeStyle = col.muted;
            c.globalAlpha = 0.7;
            c.lineWidth = 1;
            c.beginPath();
            var r = env.range, mid = (r[0] + r[1]) / 2, half = Math.max(1e-12, (r[1] - r[0]) / 2);
            for (var i = 0; i < env.t.length; i++) {
                if (env.lo[i] === null) { continue; }
                var x = X(env.t[i]);
                var y0 = cv.height / 2 - (env.lo[i] - mid) / half * cv.height * 0.42;
                var y1 = cv.height / 2 - (env.hi[i] - mid) / half * cv.height * 0.42;
                c.moveTo(x, Math.max(0, Math.min(cv.height, y0)));
                c.lineTo(x, Math.max(0, Math.min(cv.height, y1)));
            }
            c.stroke();
            c.globalAlpha = 1;
        }
        var bar = Math.max(4 * dpr, cv.height * 0.3);
        this.marks.forEach(function (m) {
            c.fillStyle = m.color || '#0072B2';
            c.fillRect(X(m.start), cv.height - bar, Math.max(1, X(m.end) - X(m.start)), bar);
        });
        var v = this.view;
        c.strokeStyle = col.fg;
        c.lineWidth = 2 * dpr;
        c.strokeRect(X(v.start) + dpr, dpr, Math.max(2 * dpr, X(v.end) - X(v.start) - 2 * dpr), cv.height - 2 * dpr);
    };

    Plot.prototype.loadOverview = function () {
        var self = this, cv = this.overviewCanvas;
        if (!cv) { return; }
        var first = this.meta.channels[0];
        var px = Math.max(100, Math.min(2000, Math.round(cv.clientWidth || 600)));
        var url = this.cfg.api + '?instance_id=' + encodeURIComponent(instanceId()) +
            '&field=' + encodeURIComponent(this.field) + '&start=' + this.meta.tStart + '&end=' + this.meta.tEnd +
            '&px=' + px + '&channels=' + encodeURIComponent(first.name);
        fetch(url, {credentials: 'same-origin'}).then(function (r) { return r.ok ? r.json() : null; })
            .then(function (data) {
                if (!data || !data.channels || !data.channels[0]) { return; }
                var c = data.channels[0];
                var lo = c.lo || c.v, hi = c.hi || c.v;
                var range = first.range || (data.ranges || {})[first.name] || [0, 1];
                self.overviewEnvelope = {t: c.t, lo: lo, hi: hi, range: range};
                self.drawOverview();
            }).catch(function () { /* the strip still shows the marks */ });
    };

    // ------------------------------------------------------------------
    // Events
    // ------------------------------------------------------------------

    Plot.prototype.on = function (name, cb) {
        var list = this.handlers[name];
        if (!list) { return function () {}; }
        list.push(cb);
        return function () {
            var i = list.indexOf(cb);
            if (i >= 0) { list.splice(i, 1); }
        };
    };

    Plot.prototype.emit = function (name, detail) {
        (this.handlers[name] || []).slice().forEach(function (cb) {
            try { cb(detail); } catch (e) { console.error(e); }
        });
    };

    // ------------------------------------------------------------------
    // Controls
    // ------------------------------------------------------------------

    function button(label, title, onclick, cls) {
        return el('button', {type: 'button', className: 'ts-btn' + (cls ? ' ' + cls : ''),
                             'aria-label': title, title: title, onclick: onclick, text: label});
    }

    Plot.prototype.controls = function () {
        var self = this;
        var bar = el('div', {className: 'ts-toolbar', role: 'toolbar', 'aria-label': 'Signal view'});
        bar.appendChild(button('‹‹', 'Previous window', function () { self.step(-1); }, 'ts-prev'));
        bar.appendChild(button('››', 'Next window', function () { self.step(1); }, 'ts-next'));
        bar.appendChild(button('−', 'Zoom out', function () { self.zoom(2); }, 'ts-zoom ts-zoom-out'));
        bar.appendChild(button('+', 'Zoom in', function () { self.zoom(0.5); }, 'ts-zoom ts-zoom-in'));
        bar.appendChild(button('All', 'Show the whole recording', function () { self.fit(); }, 'ts-zoom ts-fit'));
        bar.appendChild(button('A−', 'Lower amplitude', function () { self.setGain(self.gain / 1.5); }, 'ts-gain'));
        bar.appendChild(button('A+', 'Higher amplitude', function () { self.setGain(self.gain * 1.5); }, 'ts-gain'));
        this.readout = el('span', {className: 'ts-readout', 'aria-live': 'polite'});
        bar.appendChild(this.readout);
        return bar;
    };

    Plot.prototype.bindKeys = function () {
        var self = this, stage = this.ctx.stage;
        stage.setAttribute('tabindex', '0');
        stage.addEventListener('keydown', function (e) {
            if (e.altKey || e.ctrlKey || e.metaKey) { return; }
            var handled = true;
            if (e.key === 'ArrowRight') { if (e.shiftKey) { self.pan(0.1); } else { self.step(1); } }
            else if (e.key === 'ArrowLeft') { if (e.shiftKey) { self.pan(-0.1); } else { self.step(-1); } }
            else if (e.key === '+' || e.key === '=') { self.zoom(0.5); }
            else if (e.key === '-' || e.key === '_') { self.zoom(2); }
            else if (e.key === 'Home') { if (self.epochLength) { self.epoch(0); } else { self.setView(self.meta.tStart, self.meta.tStart + (self.view.end - self.view.start)); } }
            else if (e.key === 'End') { if (self.epochLength) { self.epoch(self.epochCount() - 1); } else { self.setView(self.meta.tEnd - (self.view.end - self.view.start), self.meta.tEnd); } }
            else { handled = false; }
            if (handled) {
                // Arrow keys would otherwise move to the next instance.
                e.preventDefault();
                e.stopPropagation();
            }
        });
        stage.addEventListener('wheel', function (e) {
            if (!(e.ctrlKey || e.metaKey || e.shiftKey)) { return; }
            e.preventDefault();
            if (e.shiftKey && !e.ctrlKey && !e.metaKey) {
                self.pan((e.deltaY || e.deltaX) > 0 ? 0.1 : -0.1);
            } else {
                var r = self.u.over.getBoundingClientRect();
                var c = self.u.posToVal(e.clientX - r.left, 'x');
                self.zoom(e.deltaY > 0 ? 1.25 : 0.8, c);
            }
        }, {passive: false});
    };

    Plot.prototype.bindOverview = function (cv) {
        var self = this, dragging = false;
        var jump = function (e) {
            var r = cv.getBoundingClientRect();
            var f = Math.max(0, Math.min(1, (e.clientX - r.left) / (r.width || 1)));
            var t = self.meta.tStart + f * (self.meta.tEnd - self.meta.tStart);
            if (self.epochLength) {
                self.epoch(Math.floor((t - self.meta.tStart) / self.epochLength));
            } else {
                var span = self.view.end - self.view.start;
                self.setView(t - span / 2, t + span / 2);
            }
        };
        cv.addEventListener('pointerdown', function (e) {
            dragging = true;
            try { cv.setPointerCapture(e.pointerId); } catch (err) { /* old browsers */ }
            jump(e);
        });
        cv.addEventListener('pointermove', function (e) { if (dragging && !self.epochLength) { jump(e); } });
        cv.addEventListener('pointerup', function () { dragging = false; });
        cv.addEventListener('pointercancel', function () { dragging = false; });
    };

    Plot.prototype.watchSize = function () {
        var self = this, stage = this.ctx.stage, timer = null;
        if (!window.ResizeObserver) { return; }
        var last = stage.clientWidth;
        new ResizeObserver(function () {
            var w = stage.clientWidth;
            if (!w || Math.abs(w - last) < 2) { return; }
            last = w;
            clearTimeout(timer);
            timer = setTimeout(function () {
                self.u.setSize({width: Math.max(200, w), height: self.cfg.plotHeight});
                self.load().catch(function () { /* reported */ });
                self.drawOverview();
            }, 120);
        }).observe(stage);
        new MutationObserver(function () {
            // Theme switch: rebuild the axes' colours by recreating the plot.
            var data = self.lastData;
            self.u.destroy();
            self.ctx.stage.querySelectorAll('.ts-brush').forEach(function (b) { b.remove(); });
            self.build();
            if (data) { self.apply(data); }
            self.drawOverview();
        }).observe(document.documentElement, {attributes: true, attributeFilter: ['data-theme']});
    };

    // ------------------------------------------------------------------
    // Adapter
    // ------------------------------------------------------------------

    var adapter = {
        context: [],
        key: function (item) { return JSON.stringify(item); },
        describe: function () { return ''; },
        init: function (ctx) {
            var plot = new Plot(ctx);
            ctx.plot = plot;
            var main = ctx.element.querySelector('.pv-main');
            ctx.element.insertBefore(plot.controls(), main);
            if (ctx.config.overview) {
                var cv = el('canvas', {className: 'ts-overview', 'aria-hidden': 'true'});
                var wrap = el('div', {className: 'ts-overview-wrap'}, [cv]);
                wrap.title = 'Whole recording: click to jump';
                main.parentNode.insertBefore(wrap, main.nextSibling);
                plot.overviewCanvas = cv;
                plot.bindOverview(cv);
            }
            plot.updateReadout();
        },
        start: function (ctx) {
            var plot = ctx.plot;
            ctx.stage.style.height = ctx.config.plotHeight + 'px';
            plot.build();
            plot.bindKeys();
            plot.watchSize();
            plots[plot.field] = plot;
            var done = plot.load().then(function () {
                plot.loadOverview();
                plot.updateReadout();
            });
            // The plot exists (axes, overlays, API) before its first data arrives.
            (waiting[plot.field] || []).forEach(function (cb) { try { cb(plot); } catch (e) { console.error(e); } });
            delete waiting[plot.field];
            document.dispatchEvent(new CustomEvent('potato:time-series-ready', {detail: {field: plot.field, plot: plot}}));
            return done;
        }
    };

    function register() { window.PotatoViewerFramework.register('time_series', adapter); }
    if (window.PotatoViewerFramework) { register(); }
    else { document.addEventListener('DOMContentLoaded', register); }

    window.PotatoTimeSeries = {
        get: function (field) { return plots[field] || null; },
        whenReady: function (field, cb) {
            if (plots[field] && plots[field].element.isConnected) { cb(plots[field]); return; }
            (waiting[field] = waiting[field] || []).push(cb);
        },
        _plots: plots
    };
})();

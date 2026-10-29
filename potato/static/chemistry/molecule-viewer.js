/*
 * molecule viewer adapter (OpenChemLib by default, RDKit.js on request).
 *
 * Selection items are atoms: {atom, element}, where atom is the 0-based
 * position in the source as written (SMILES order, or the molfile atom
 * block; molfile number = atom + 1). The annotator toggles an atom by
 * clicking it in the drawing or in the atom list under it; the list also
 * works from the keyboard. Selected atoms get a disc in their label colour.
 *
 * Extra API on window.potatoViewers[field] (for linked displays, such as
 * peaks on a spectrum assigned to atoms):
 *   atoms()                    -> [{atom, element, number, x, y}]
 *   highlightAtoms(list, col)  -> temporary highlight; [] clears it
 *   onAtomHover(cb)            -> cb(atomIndex | null); returns unsubscribe
 */
(function () {
    'use strict';
    var FW = window.PotatoViewerFramework;
    var CHEM = window.PotatoChem;
    if (!FW || !CHEM || FW.__molecule) { return; }
    FW.__molecule = true;

    var SVG_NS = 'http://www.w3.org/2000/svg';
    var SELECTED = '#c2255c';   // matches viewer_selection's first label colour

    function normalizeItem(item) {
        if (!item || typeof item !== 'object') { return null; }
        var atom = typeof item.atom === 'number' ? item.atom : parseInt(item.atom, 10);
        if (!isFinite(atom) || atom < 0) { return null; }
        var out = {atom: atom};
        if (item.element) { out.element = String(item.element); }
        return out;
    }

    function key(item) { return String(item.atom); }

    function describe(item) {
        if (!item) { return ''; }
        var text = (item.element || 'atom ') + (item.atom + 1);
        return item.label ? text + ' (' + item.label + ')' : text;
    }

    function el(tag, attrs) {
        var node = document.createElementNS(SVG_NS, tag);
        Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
        return node;
    }

    // ------------------------------------------------------------------

    function stageSize(ctx) {
        var wrap = ctx.element.querySelector('.pv-stage-wrap');
        var w = Math.max(240, Math.round((wrap && wrap.clientWidth) || 480));
        var h = Math.max(180, Math.round((wrap && wrap.clientHeight) || ctx.config.height || 320));
        return {width: w, height: h};
    }

    function loadToolkit(ctx) {
        if (ctx.config.engine === 'rdkit') { return CHEM.loadRDKit(ctx.config.rdkitWasm); }
        return CHEM.loadOCL(ctx.config.oclUrl);
    }

    function draw(ctx, state) {
        var size = stageSize(ctx);
        var result = CHEM.depict(ctx.config.engine, state.toolkit, ctx.config.source,
                                 ctx.config.format, size);
        if (result.atomCount > (ctx.config.maxAtoms || 500)) {
            throw new Error('this molecule has ' + result.atomCount + ' atoms, more than the display ' +
                'draws (' + ctx.config.maxAtoms + '; see max_atoms)');
        }
        var svg = result.svg;
        svg.setAttribute('class', 'mv-svg');
        svg.setAttribute('width', '100%');
        svg.setAttribute('height', '100%');
        svg.setAttribute('viewBox', '0 0 ' + size.width + ' ' + size.height);
        svg.setAttribute('focusable', 'false');
        svg.setAttribute('aria-hidden', 'true');
        // Layers: highlight discs under the drawing, hit targets over it.
        var under = el('g', {'class': 'mv-under'});
        svg.insertBefore(under, svg.firstChild);
        var over = el('g', {'class': 'mv-hits'});
        svg.appendChild(over);
        var numbers = el('g', {'class': 'mv-numbers'});
        if (ctx.config.showAtomNumbers) { svg.appendChild(numbers); }
        var bond = typicalBond(result.atoms);
        var radius = Math.max(7, Math.min(16, bond * 0.38));
        state.radius = radius;
        state.atoms = result.atoms;
        state.byIndex = {};
        result.atoms.forEach(function (a) {
            if (a.atom === null) { return; }
            state.byIndex[a.atom] = a;
            var hit = el('circle', {cx: a.x, cy: a.y, r: radius, 'class': 'mv-hit',
                                    'data-atom': a.atom});
            over.appendChild(hit);
            if (ctx.config.showAtomNumbers) {
                var t = el('text', {x: a.x + radius * 0.7, y: a.y - radius * 0.55, 'class': 'mv-num'});
                t.textContent = String(a.atom + 1);
                numbers.appendChild(t);
            }
        });
        ctx.stage.innerHTML = '';
        ctx.stage.appendChild(svg);
        state.svg = svg;
        state.under = under;
        if (result.note) { ctx.status(result.note); }
        buildList(ctx, state, result);
        return result;
    }

    function typicalBond(atoms) {
        // The nearest-neighbour distance of a few atoms: a bond length.
        var best = [];
        var pts = atoms.slice(0, 40);
        pts.forEach(function (a, i) {
            var d = Infinity;
            pts.forEach(function (b, j) {
                if (i === j) { return; }
                var dd = Math.hypot(a.x - b.x, a.y - b.y);
                if (dd > 1 && dd < d) { d = dd; }
            });
            if (isFinite(d)) { best.push(d); }
        });
        if (!best.length) { return 30; }
        best.sort(function (x, y) { return x - y; });
        return best[Math.floor(best.length / 2)];
    }

    function paint(ctx, state, sel) {
        if (!state.under) { return; }
        var viewer = ctx.viewer;
        state.under.innerHTML = '';
        var picked = {};
        (sel.items || []).forEach(function (it) { picked[it.atom] = it; });
        (state.fixed || []).forEach(function (idx) {
            var a = state.byIndex[idx];
            if (!a || picked[idx]) { return; }
            state.under.appendChild(el('circle', {cx: a.x, cy: a.y, r: state.radius * 1.05,
                'class': 'mv-fixed', fill: ctx.config.highlightColor}));
        });
        (state.temp || []).forEach(function (idx) {
            var a = state.byIndex[idx];
            if (!a) { return; }
            state.under.appendChild(el('circle', {cx: a.x, cy: a.y, r: state.radius * 1.25,
                'class': 'mv-temp', fill: state.tempColor || ctx.config.highlightColor}));
        });
        Object.keys(picked).forEach(function (k) {
            var a = state.byIndex[k];
            if (!a) { return; }
            var colour = viewer.colorFor(picked[k]) || SELECTED;
            state.under.appendChild(el('circle', {cx: a.x, cy: a.y, r: state.radius,
                'class': 'mv-selected', fill: colour}));
        });
        if (state.svg) {
            state.svg.querySelectorAll('.mv-hit').forEach(function (c) {
                c.classList.toggle('mv-on', !!picked[c.getAttribute('data-atom')]);
            });
        }
        var strip = ctx.element.querySelector('.mv-atom-strip');
        if (strip) {
            strip.querySelectorAll('.mv-atom').forEach(function (btn) {
                var it = picked[btn.getAttribute('data-atom')];
                btn.setAttribute('aria-pressed', it ? 'true' : 'false');
                var colour = it ? (viewer.colorFor(it) || SELECTED) : null;
                if (colour) { btn.style.setProperty('--mv-sel', colour); }
                else { btn.style.removeProperty('--mv-sel'); }
            });
        }
    }

    // ------------------------------------------------------------------
    // Atom list (keyboard route)
    // ------------------------------------------------------------------

    function buildList(ctx, state, result) {
        var strip = ctx.element.querySelector('.mv-atom-strip');
        if (!strip) { return; }
        strip.innerHTML = '';
        var first = true;
        result.atoms.forEach(function (a) {
            if (a.atom === null) { return; }
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'mv-atom' + (a.element === 'C' ? '' : ' mv-hetero');
            btn.setAttribute('data-atom', a.atom);
            btn.setAttribute('data-element', a.element);
            btn.setAttribute('aria-pressed', 'false');
            btn.setAttribute('tabindex', first ? '0' : '-1');
            btn.setAttribute('aria-label', a.element + ', atom ' + (a.atom + 1));
            // Element and number in separate spans: in a monospace face "O3"
            // reads as "03".
            var sym = document.createElement('span');
            sym.className = 'mv-el';
            sym.textContent = a.element;
            var num = document.createElement('span');
            num.className = 'mv-n';
            num.textContent = String(a.atom + 1);
            btn.appendChild(sym);
            btn.appendChild(num);
            strip.appendChild(btn);
            first = false;
        });
        if (!strip.children.length) {
            var p = document.createElement('p');
            p.className = 'mv-atoms-note';
            p.textContent = result.note || 'No atoms can be selected in this drawing.';
            strip.appendChild(p);
        }
    }

    function wireList(ctx, state) {
        var strip = ctx.element.querySelector('.mv-atom-strip');
        if (!strip || strip.__mvWired) { return; }
        strip.__mvWired = true;
        strip.addEventListener('click', function (e) {
            var btn = e.target.closest && e.target.closest('.mv-atom');
            if (!btn) { return; }
            rove(strip, btn);
            toggle(ctx, state, +btn.getAttribute('data-atom'));
        });
        strip.addEventListener('keydown', function (e) {
            var btn = e.target.closest && e.target.closest('.mv-atom');
            if (!btn) { return; }
            var cells = Array.prototype.slice.call(strip.querySelectorAll('.mv-atom'));
            var i = cells.indexOf(btn), next = null;
            if (e.key === 'ArrowRight' || e.key === 'ArrowDown') { next = cells[i + 1]; }
            else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') { next = cells[i - 1]; }
            else if (e.key === 'Home') { next = cells[0]; }
            else if (e.key === 'End') { next = cells[cells.length - 1]; }
            else { return; }
            // The page binds the arrow keys to previous/next item.
            e.preventDefault();
            e.stopPropagation();
            if (next) { rove(strip, next); next.focus(); }
        });
        strip.addEventListener('focusin', function (e) {
            var btn = e.target.closest && e.target.closest('.mv-atom');
            hover(state, btn ? +btn.getAttribute('data-atom') : null);
        });
        strip.addEventListener('focusout', function () { hover(state, null); });
    }

    function rove(strip, btn) {
        strip.querySelectorAll('.mv-atom[tabindex="0"]').forEach(function (b) { b.setAttribute('tabindex', '-1'); });
        btn.setAttribute('tabindex', '0');
    }

    function toggle(ctx, state, index) {
        var a = state.byIndex[index];
        if (!a) { return; }
        ctx.viewer.toggleItem({atom: a.atom, element: a.element});
    }

    function hover(state, index) {
        if (state.hovered === index) { return; }
        state.hovered = index;
        if (state.svg) {
            state.svg.querySelectorAll('.mv-hit.mv-hover').forEach(function (c) { c.classList.remove('mv-hover'); });
            if (index !== null && index !== undefined) {
                var c = state.svg.querySelector('.mv-hit[data-atom="' + index + '"]');
                if (c) { c.classList.add('mv-hover'); }
            }
        }
        state.hoverListeners.slice().forEach(function (cb) {
            try { cb(index === undefined ? null : index); } catch (e) { console.error(e); }
        });
    }

    function wireDrawing(ctx, state) {
        ctx.stage.addEventListener('click', function (e) {
            var hit = e.target.closest && e.target.closest('.mv-hit');
            if (hit) { toggle(ctx, state, +hit.getAttribute('data-atom')); }
        });
        ctx.stage.addEventListener('pointerover', function (e) {
            var hit = e.target.closest && e.target.closest('.mv-hit');
            hover(state, hit ? +hit.getAttribute('data-atom') : null);
        });
        ctx.stage.addEventListener('pointerleave', function () { hover(state, null); });
    }

    function extendApi(ctx, state) {
        var viewer = ctx.viewer;
        viewer.atoms = function () {
            return (state.atoms || []).filter(function (a) { return a.atom !== null; })
                .map(function (a) {
                    return {atom: a.atom, element: a.element, number: a.atom + 1, x: a.x, y: a.y};
                });
        };
        viewer.highlightAtoms = function (list, colour) {
            state.temp = (list || []).map(Number).filter(function (n) { return isFinite(n); });
            state.tempColor = colour || null;
            paint(ctx, state, viewer.getSelection());
        };
        viewer.onAtomHover = function (cb) {
            state.hoverListeners.push(cb);
            return function () {
                state.hoverListeners = state.hoverListeners.filter(function (f) { return f !== cb; });
            };
        };
    }

    function fixedHighlights(ctx, state) {
        var field = ctx.config.highlightField;
        if (!field) { return Promise.resolve(); }
        return ctx.instanceData().then(function (data) {
            var raw = data ? data[field] : null;
            if (typeof raw === 'string') {
                try { raw = JSON.parse(raw); } catch (e) { raw = raw.split(/[\s,]+/); }
            }
            state.fixed = (Array.isArray(raw) ? raw : []).map(Number).filter(function (n) {
                return isFinite(n) && n >= 0;
            });
        }).catch(function () { state.fixed = []; });
    }

    FW.register('molecule', {
        context: [],
        key: key,
        normalizeItem: normalizeItem,
        describe: describe,
        init: function (ctx) {
            var state = {hoverListeners: [], fixed: [], temp: []};
            ctx.__mv = state;
            extendApi(ctx, state);
            wireList(ctx, state);
            wireDrawing(ctx, state);
        },
        start: function (ctx) {
            var state = ctx.__mv;
            ctx.status('');
            return Promise.all([loadToolkit(ctx), fixedHighlights(ctx, state)]).then(function (r) {
                state.toolkit = r[0];
                draw(ctx, state);
                ctx.viewer.addPainter(function (sel) { paint(ctx, state, sel); });
                // Redraw on a theme switch (element colours) and on a resize
                // that changes the drawing's shape.
                var redraw = function () {
                    try { draw(ctx, state); paint(ctx, state, ctx.viewer.getSelection()); }
                    catch (e) { console.error('molecule redraw failed', e); }
                };
                new MutationObserver(redraw).observe(document.documentElement,
                    {attributes: true, attributeFilter: ['data-theme']});
                if (window.ResizeObserver) {
                    var last = stageSize(ctx), timer = null;
                    new ResizeObserver(function () {
                        var now = stageSize(ctx);
                        if (Math.abs(now.width - last.width) < 24 && Math.abs(now.height - last.height) < 24) { return; }
                        last = now;
                        clearTimeout(timer);
                        timer = setTimeout(redraw, 120);
                    }).observe(ctx.element.querySelector('.pv-stage-wrap'));
                }
            });
        }
    });
})();

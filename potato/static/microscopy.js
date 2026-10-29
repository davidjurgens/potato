/*
 * Multichannel microscopy (annotation_type: microscopy).
 *
 * The image is shown with OpenSeadragon from tiles the server composites
 * (potato/science/microscopy.py): the page sends the visible channels with
 * their colours and contrast limits, plus the z-slice and time point, in each
 * tile URL. Changing any of them opens a new tile source over the old one and
 * drops the old one once the new one has loaded, so the image never blanks.
 *
 * Annotations live in one overlay positioned in IMAGE pixels: the overlay's
 * CSS transform is read from OpenSeadragon (where image points (0,0) and
 * (W,0) land on screen), never computed from zoom and pan.
 *   - ROIs (rectangle, polygon, point) are SVG, stored in image_annotation's
 *     region format (fractions of the full-resolution image), plus z and t.
 *   - Cells come from the label image: the server sends it as a raster of ids
 *     (/api/microscopy/labels), clicks are hit-tested against it here, and
 *     the cell fill is drawn into a canvas of the raster's size.
 *
 * The answer is JSON in the scheme's hidden input; see
 * potato/server_utils/schemas/microscopy.py for its shape.
 */
(function () {
    'use strict';
    if (window.PotatoMicroscopy) { return; }

    var STATES = new WeakMap();
    var SVGNS = 'http://www.w3.org/2000/svg';
    var TOOL_NAMES = {pan: 'Pan / select cell', bbox: 'Rectangle', polygon: 'Polygon', landmark: 'Point'};
    var TOOL_KEYS = {pan: 'v', bbox: 'r', polygon: 'p', landmark: 'o'};

    function el(tag, attrs, children) {
        var node = document.createElement(tag);
        Object.keys(attrs || {}).forEach(function (k) {
            var v = attrs[k];
            if (v === undefined || v === null || v === false) { return; }
            if (k === 'text') { node.textContent = v; }
            else if (k === 'className') { node.className = v; }
            else if (k.indexOf('on') === 0) { node.addEventListener(k.slice(2), v); }
            else { node.setAttribute(k, v === true ? '' : v); }
        });
        (children || []).forEach(function (c) { if (c) { node.appendChild(c); } });
        return node;
    }

    function svg(tag, attrs) {
        var node = document.createElementNS(SVGNS, tag);
        Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
        return node;
    }

    function instanceId() {
        var input = document.getElementById('instance_id');
        return input ? input.value : '';
    }

    function hexToRgb(hex) {
        var h = String(hex || '').replace('#', '');
        return [parseInt(h.slice(0, 2), 16) || 0, parseInt(h.slice(2, 4), 16) || 0,
                parseInt(h.slice(4, 6), 16) || 0];
    }

    function fmt(value) {
        var n = Number(value);
        if (!isFinite(n)) { return ''; }
        return Math.abs(n) >= 100 || n === Math.round(n) ? String(Math.round(n)) : n.toPrecision(3);
    }

    function storageGet(key) {
        try { return JSON.parse(window.sessionStorage.getItem(key) || 'null'); } catch (e) { return null; }
    }

    function storageSet(key, value) {
        try { window.sessionStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* private mode */ }
    }

    function readStored(form) {
        var h = form.querySelector('.microscopy-input');
        if (h && h.value) {
            try { return JSON.parse(h.value) || {}; } catch (e) { return {}; }
        }
        return {};
    }

    function api(state, path, extra) {
        var q = 'schema=' + encodeURIComponent(state.cfg.schema) +
                '&instance_id=' + encodeURIComponent(state.instance);
        return path + '?' + q + (extra ? '&' + extra : '');
    }

    // ------------------------------------------------------------------
    // Setup
    // ------------------------------------------------------------------

    function setup(form) {
        var prior = STATES.get(form);
        if (prior && prior.instance === instanceId()) { return; }
        if (prior && prior.viewer) { try { prior.viewer.destroy(); } catch (e) { /* gone */ } }
        var cfg = JSON.parse(form.getAttribute('data-microscopy-config') || '{}');
        var stored = readStored(form);
        var state = {
            form: form, cfg: cfg, instance: instanceId(), root: form.querySelector('.mic-root'),
            input: form.querySelector('.microscopy-input'),
            rois: Array.isArray(stored.rois) ? stored.rois.slice() : [],
            cells: Array.isArray(stored.cells) ? stored.cells.slice() : [],
            info: null, viewer: null, tool: 'pan', z: 0, t: 0, channels: [],
            label: (cfg.labels[0] || {}).name || '', raster: null, rasters: {},
            selectedCell: null, selectedRoi: -1, drawing: null, renderSeq: 0
        };
        STATES.set(form, state);
        if (!state.instance) {
            status(state, 'This question needs an item with a microscopy image; it cannot be ' +
                          'shown on this page.', true);
            return;
        }
        if (typeof window.OpenSeadragon === 'undefined') {
            status(state, 'The image viewer did not load (OpenSeadragon is missing). Reload the page.', true);
            return;
        }
        fetch(api(state, '/api/microscopy/info'), {credentials: 'same-origin'}).then(function (r) {
            return r.json().then(function (body) {
                if (!r.ok) { throw new Error(body && body.error ? body.error : 'HTTP ' + r.status); }
                return body;
            });
        }).then(function (info) {
            if (STATES.get(form) !== state) { return; }
            state.info = info;
            state.z = Math.min(info.size_z - 1, Math.floor((info.size_z - 1) / 2));
            if (state.rois.length) {
                state.z = Math.min(info.size_z - 1, state.rois[state.rois.length - 1].z || 0);
                state.t = Math.min(info.size_t - 1, state.rois[state.rois.length - 1].t || 0);
            }
            state.channels = info.channels.map(function (c) { return Object.assign({}, c); });
            restoreView(state);
            build(state);
            openViewer(state);
            declare(state);
        }).catch(function (err) {
            console.warn('[microscopy]', err);
            status(state, 'The image could not be opened: ' + err.message, true);
        });
    }

    function status(state, text, isError) {
        state.root.innerHTML = '';
        state.root.appendChild(el('p', {className: isError ? 'mic-error' : 'mic-status',
                                        role: isError ? 'alert' : 'status', text: text}));
    }

    function viewKey(state) { return 'potato-microscopy:' + state.cfg.schema; }

    /** Contrast and visibility carry over from item to item in one session. */
    function restoreView(state) {
        var saved = storageGet(viewKey(state));
        if (!saved || !Array.isArray(saved.channels)) { return; }
        state.channels.forEach(function (c) {
            var match = saved.channels.filter(function (s) { return s.name === c.name; })[0];
            if (!match) { return; }
            c.visible = !!match.visible;
            if (/^#[0-9a-f]{6}$/i.test(match.color)) { c.color = match.color; }
            if (isFinite(match.start) && isFinite(match.end) && match.end > match.start) {
                c.start = Math.max(c.min, match.start);
                c.end = Math.min(c.max, match.end);
            }
        });
    }

    function saveView(state) {
        storageSet(viewKey(state), {channels: state.channels.map(function (c) {
            return {name: c.name, visible: c.visible, color: c.color, start: c.start, end: c.end};
        })});
    }

    // ------------------------------------------------------------------
    // Layout
    // ------------------------------------------------------------------

    function build(state) {
        var cfg = state.cfg, info = state.info, root = state.root;
        root.innerHTML = '';
        var tools = ['pan'].concat(cfg.tools || []);
        var toolbar = el('div', {className: 'mic-toolbar', role: 'toolbar',
                                 'aria-label': 'Drawing tools'});
        tools.forEach(function (tool) {
            toolbar.appendChild(el('button', {type: 'button', className: 'mic-tool',
                'data-tool': tool, 'aria-pressed': tool === state.tool ? 'true' : 'false',
                title: TOOL_NAMES[tool] + ' (' + TOOL_KEYS[tool].toUpperCase() + ')',
                text: TOOL_NAMES[tool],
                onclick: function () { setTool(state, tool); }}));
        });
        if ((cfg.tools || []).length) {
            var select = el('select', {className: 'mic-class', 'aria-label': 'Class for new regions'});
            cfg.labels.forEach(function (l) {
                select.appendChild(el('option', {value: l.name, text: l.name}));
            });
            select.value = state.label;
            select.addEventListener('change', function () { state.label = select.value; });
            toolbar.appendChild(el('label', {className: 'mic-class-label'},
                [document.createTextNode('Region class '), select]));
        }

        var host = el('div', {className: 'mic-viewer', tabindex: '0', role: 'application',
                              'aria-label': 'Microscopy image. Drag to pan, scroll to zoom.',
                              style: 'height:' + cfg.height + 'px'});
        var hint = el('p', {className: 'mic-hint', 'aria-live': 'polite'});
        var finish = el('button', {type: 'button', className: 'mic-finish', hidden: true,
                                   text: 'Finish polygon', onclick: function () { finishPolygon(state); }});
        var planes = el('div', {className: 'mic-planes'});
        [['z', 'Z-slice', info.size_z], ['t', 'Time point', info.size_t]].forEach(function (p) {
            if (p[2] <= 1) { return; }
            var id = 'mic-' + cfg.schema + '-' + p[0];
            var out = el('output', {className: 'mic-plane-value', 'for': id});
            var range = el('input', {type: 'range', id: id, className: 'mic-plane mic-plane-' + p[0],
                                     min: '0', max: String(p[2] - 1), step: '1',
                                     value: String(state[p[0]])});
            out.textContent = (state[p[0]] + 1) + ' / ' + p[2];
            range.addEventListener('input', function () {
                state[p[0]] = parseInt(range.value, 10);
                out.textContent = (state[p[0]] + 1) + ' / ' + p[2];
                cancelDrawing(state);
                scheduleRender(state);
                loadRaster(state);
                drawRois(state);
            });
            planes.appendChild(el('label', {className: 'mic-plane-row', 'for': id},
                [document.createTextNode(p[1] + ' '), range, out]));
        });

        var main = el('div', {className: 'mic-main'}, [toolbar, host, el('div', {className: 'mic-under'},
            [hint, finish]), planes]);

        var side = el('div', {className: 'mic-side'});
        side.appendChild(buildChannels(state));
        if ((cfg.tools || []).length) {
            side.appendChild(el('section', {className: 'mic-section mic-rois'}, [
                el('h4', {className: 'mic-heading'}, [el('span', {text: 'Regions '}),
                    el('span', {className: 'mic-count mic-roi-count'})]),
                el('ul', {className: 'mic-list mic-roi-list'})]));
        }
        side.appendChild(buildCellPanel(state));

        root.appendChild(el('div', {className: 'mic-layout'}, [main, side]));
        state.host = host;
        state.hint = hint;
        state.finish = finish;
        host.addEventListener('keydown', function (e) { onKey(state, e); });
        host.addEventListener('pointermove', function (e) { onPointerMove(state, e); });
        updateHint(state);
        listRois(state);
        listCells(state);
    }

    function buildChannels(state) {
        var section = el('section', {className: 'mic-section mic-channels'},
                         [el('h4', {className: 'mic-heading', text: 'Channels'})]);
        state.channels.forEach(function (c) {
            var row = el('div', {className: 'mic-channel', 'data-channel': String(c.index)});
            var id = 'mic-' + state.cfg.schema + '-ch' + c.index;
            var box = el('input', {type: 'checkbox', className: 'mic-ch-visible', id: id});
            box.checked = !!c.visible;
            box.addEventListener('change', function () {
                c.visible = box.checked;
                row.classList.toggle('mic-channel-off', !c.visible);
                changed(state);
            });
            var colour = el('input', {type: 'color', className: 'mic-ch-color', value: c.color,
                                      'aria-label': c.name + ' colour'});
            colour.addEventListener('input', function () { c.color = colour.value; changed(state); });
            var step = (state.info.dtype.indexOf('float') === 0) ? String((c.max - c.min) / 1000 || 0.001) : '1';
            function slider(which, text) {
                var input = el('input', {type: 'range', className: 'mic-ch-' + which, min: String(c.min),
                                         max: String(c.max), step: step, value: String(c[which]),
                                         'aria-label': c.name + ' ' + text});
                var out = el('output', {className: 'mic-ch-value', text: fmt(c[which])});
                input.addEventListener('input', function () {
                    var v = parseFloat(input.value);
                    if (which === 'start' && v >= c.end) { v = c.end - parseFloat(step); input.value = v; }
                    if (which === 'end' && v <= c.start) { v = c.start + parseFloat(step); input.value = v; }
                    c[which] = v;
                    out.textContent = fmt(v);
                    changed(state);
                });
                return el('label', {className: 'mic-ch-limit'}, [el('span', {className: 'mic-ch-limit-name', text: text}), input, out]);
            }
            var reset = el('button', {type: 'button', className: 'mic-ch-reset', text: 'Reset',
                                      'aria-label': 'Reset ' + c.name,
                onclick: function () {
                    var original = state.info.channels.filter(function (o) { return o.index === c.index; })[0];
                    Object.assign(c, {start: original.start, end: original.end, color: original.color,
                                      visible: original.visible});
                    var fresh = buildChannels(state);
                    section.replaceWith(fresh);
                    changed(state);
                }});
            row.appendChild(el('div', {className: 'mic-ch-head'}, [
                el('label', {className: 'mic-ch-name', 'for': id}, [box, el('span', {text: c.name})]),
                colour, reset]));
            row.appendChild(slider('start', 'Min'));
            row.appendChild(slider('end', 'Max'));
            row.classList.toggle('mic-channel-off', !c.visible);
            section.appendChild(row);
        });
        return section;
    }

    function buildCellPanel(state) {
        var section = el('section', {className: 'mic-section mic-cells'});
        var hasLabels = !!state.info.label_image;
        section.appendChild(el('h4', {className: 'mic-heading'}, [el('span', {text: 'Cells '}),
            el('span', {className: 'mic-count mic-cell-count'})]));
        if (!hasLabels) {
            section.appendChild(el('p', {className: 'mic-note',
                text: 'This image has no label image, so cells cannot be selected.'}));
            return section;
        }
        var selected = el('div', {className: 'mic-selected', 'aria-live': 'polite',
                                  text: 'Click a cell in the image to select it.'});
        var picker = el('div', {className: 'mic-cell-classes', role: 'group',
                                'aria-label': 'Class for the selected cell'});
        state.cfg.cellLabels.forEach(function (l, i) {
            picker.appendChild(el('button', {type: 'button', className: 'mic-cell-class',
                'data-class': l.name, disabled: true,
                title: i < 9 ? 'Key ' + (i + 1) : null,
                onclick: function () { assignCell(state, l.name); }},
                [el('span', {className: 'mic-swatch', style: 'background:' + l.color}),
                 document.createTextNode(l.name)]));
        });
        var byId = el('input', {type: 'number', min: '1', className: 'mic-cell-id',
                                'aria-label': 'Cell id', placeholder: 'id'});
        var go = el('button', {type: 'button', className: 'mic-cell-go', text: 'Select',
            onclick: function () { selectCell(state, parseInt(byId.value, 10), true); }});
        byId.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') { e.preventDefault(); go.click(); }
        });
        section.appendChild(selected);
        section.appendChild(picker);
        section.appendChild(el('div', {className: 'mic-cell-find'},
            [el('label', {text: 'Cell id '}, [byId]), go]));
        section.appendChild(el('ul', {className: 'mic-list mic-cell-list'}));
        return section;
    }

    // ------------------------------------------------------------------
    // Viewer
    // ------------------------------------------------------------------

    function renderSpec(state) {
        return state.channels.filter(function (c) { return c.visible; }).map(function (c) {
            return c.index + ':' + c.color.replace('#', '') + ':' + c.start + ':' + c.end;
        }).join(';');
    }

    function tileSource(state) {
        var dzi = state.info.dzi;
        var query = 'ch=' + encodeURIComponent(renderSpec(state)) + '&z=' + state.z + '&t=' + state.t +
                    '&v=' + encodeURIComponent(state.info.version);
        var base = '/api/microscopy/tile/';
        return {
            width: dzi.width, height: dzi.height, tileSize: dzi.tile_size,
            tileOverlap: dzi.overlap, minLevel: 0, maxLevel: dzi.max_level,
            getTileUrl: function (level, x, y) {
                return api(state, base + level + '/' + x + '_' + y + '.jpg', query);
            }
        };
    }

    function openViewer(state) {
        var viewer = window.OpenSeadragon({
            element: state.host,
            prefixUrl: '',
            tileSources: tileSource(state),
            // Potato draws its own controls; OpenSeadragon's need sprites that
            // are not vendored.
            showNavigationControl: false,
            // The 2D canvas drawer: no WebGL needed, and tiles stay readable
            // by getImageData for tests.
            drawer: 'canvas',
            animationTime: 0.4,
            springStiffness: 12,
            maxZoomPixelRatio: 8,
            minZoomImageRatio: 0.5,
            visibilityRatio: 0.5,
            constrainDuringPan: true,
            gestureSettingsMouse: {clickToZoom: false, dblClickToZoom: false},
            gestureSettingsTouch: {clickToZoom: false, dblClickToZoom: false},
            crossOriginPolicy: false
        });
        state.viewer = viewer;
        var layer = el('div', {className: 'mic-overlay'});
        var canvas = el('canvas', {className: 'mic-cell-layer'});
        var shapes = svg('svg', {'class': 'mic-shapes', width: String(state.info.width),
                                 height: String(state.info.height),
                                 viewBox: '0 0 ' + state.info.width + ' ' + state.info.height});
        layer.appendChild(canvas);
        layer.appendChild(shapes);
        layer.style.width = state.info.width + 'px';
        layer.style.height = state.info.height + 'px';
        state.layer = layer;
        state.canvas = canvas;
        state.svg = shapes;
        viewer.addHandler('open', function () {
            viewer.canvas.appendChild(layer);
            sync(state);
            drawRois(state);
            loadRaster(state);
            state.form.setAttribute('data-mic-ready', 'true');
        });
        viewer.addHandler('open-failed', function (e) {
            status(state, 'The image could not be opened: ' + (e.message || 'tile source failed'), true);
        });
        ['update-viewport', 'animation', 'animation-finish', 'resize'].forEach(function (name) {
            viewer.addHandler(name, function () { sync(state); });
        });
        viewer.addHandler('canvas-click', function (e) { onClick(state, e); });
        viewer.addHandler('canvas-double-click', function (e) {
            if (state.tool === 'polygon') { e.preventDefaultAction = true; finishPolygon(state); }
        });
        viewer.addHandler('canvas-press', function (e) { onPress(state, e); });
        viewer.addHandler('canvas-drag', function (e) { onDrag(state, e); });
        viewer.addHandler('canvas-release', function (e) { onRelease(state, e); });
    }

    /** Image pixel -> viewer element pixel, through OpenSeadragon. */
    function toElement(state, x, y) {
        var W = state.info.width;
        return state.viewer.viewport.viewportToViewerElementCoordinates(
            new window.OpenSeadragon.Point(x / W, y / W));
    }

    function toImage(state, point) {
        var W = state.info.width;
        var vp = state.viewer.viewport.viewerElementToViewportCoordinates(point);
        return {x: vp.x * W, y: vp.y * W};
    }

    function pixelsPerImagePixel(state) {
        var a = toElement(state, 0, 0), b = toElement(state, state.info.width, 0);
        return (b.x - a.x) / state.info.width;
    }

    function sync(state) {
        if (!state.viewer || !state.layer) { return; }
        var origin = toElement(state, 0, 0);
        var scale = pixelsPerImagePixel(state);
        if (!isFinite(scale) || scale <= 0) { return; }
        state.layer.style.transform = 'matrix(' + scale + ',0,0,' + scale + ',' + origin.x + ',' + origin.y + ')';
        state.svg.style.setProperty('--mic-stroke', String(2 / scale));
        state.svg.style.setProperty('--mic-point-r', String(6 / scale));
        state.scale = scale;
    }

    function changed(state) {
        saveView(state);
        scheduleRender(state);
    }

    function scheduleRender(state) {
        clearTimeout(state.renderTimer);
        state.renderTimer = setTimeout(function () { swapSource(state); }, 120);
    }

    function swapSource(state) {
        var viewer = state.viewer;
        if (!viewer) { return; }
        var seq = ++state.renderSeq;
        state.form.setAttribute('data-mic-rendering', 'true');
        viewer.addTiledImage({
            tileSource: tileSource(state),
            success: function (event) {
                var item = event.item;
                function done() {
                    if (seq !== state.renderSeq) {
                        if (viewer.world.getIndexOfItem(item) !== -1) { viewer.world.removeItem(item); }
                        return;
                    }
                    for (var i = viewer.world.getItemCount() - 1; i >= 0; i--) {
                        var other = viewer.world.getItemAt(i);
                        if (other !== item) { viewer.world.removeItem(other); }
                    }
                    state.form.setAttribute('data-mic-rendering', 'false');
                    state.form.setAttribute('data-mic-render-seq', String(seq));
                }
                if (item.getFullyLoaded()) { done(); }
                else {
                    item.addHandler('fully-loaded-change', function handler(e) {
                        if (e.fullyLoaded) { item.removeHandler('fully-loaded-change', handler); done(); }
                    });
                }
            }
        });
    }

    // ------------------------------------------------------------------
    // Tools and pointer handling
    // ------------------------------------------------------------------

    function setTool(state, tool) {
        cancelDrawing(state);
        state.tool = tool;
        state.root.querySelectorAll('.mic-tool').forEach(function (b) {
            b.setAttribute('aria-pressed', b.getAttribute('data-tool') === tool ? 'true' : 'false');
        });
        state.host.classList.toggle('mic-drawing', tool !== 'pan');
        updateHint(state);
    }

    function updateHint(state) {
        var text = {
            pan: state.info.label_image ? 'Drag to pan, scroll to zoom. Click a cell to select it.'
                                        : 'Drag to pan, scroll to zoom.',
            bbox: 'Drag to draw a rectangle.',
            polygon: 'Click to add points. Click the first point, double-click or press Enter to finish; Escape cancels.',
            landmark: 'Click to place a point.'
        }[state.tool];
        state.hint.textContent = text;
        state.finish.hidden = !(state.tool === 'polygon' && state.drawing && state.drawing.points.length >= 3);
    }

    function onPress(state, e) {
        if (state.tool !== 'bbox') { return; }
        var p = toImage(state, e.position);
        state.drawing = {type: 'bbox', start: p, end: p};
    }

    function onDrag(state, e) {
        if (state.tool === 'pan') { return; }
        // Drawing tools keep the image still.
        e.preventDefaultAction = true;
        if (state.tool === 'bbox' && state.drawing) {
            state.drawing.end = toImage(state, e.position);
            drawTemp(state);
        }
    }

    function onRelease(state, e) {
        if (state.tool !== 'bbox' || !state.drawing) { return; }
        var d = state.drawing;
        state.drawing = null;
        drawTemp(state);
        var x0 = clampX(state, Math.min(d.start.x, d.end.x)), x1 = clampX(state, Math.max(d.start.x, d.end.x));
        var y0 = clampY(state, Math.min(d.start.y, d.end.y)), y1 = clampY(state, Math.max(d.start.y, d.end.y));
        if ((x1 - x0) * state.scale < 4 || (y1 - y0) * state.scale < 4) { return; }
        var W = state.info.width, H = state.info.height;
        addRoi(state, {type: 'bbox', coordinates: {x: x0 / W, y: y0 / H, width: (x1 - x0) / W,
                                                   height: (y1 - y0) / H}});
    }

    function clampX(state, x) { return Math.max(0, Math.min(state.info.width, x)); }
    function clampY(state, y) { return Math.max(0, Math.min(state.info.height, y)); }

    function insideImage(state, p) {
        return p.x >= 0 && p.y >= 0 && p.x <= state.info.width && p.y <= state.info.height;
    }

    function onClick(state, e) {
        if (!e.quick) { return; }
        var p = toImage(state, e.position);
        state.host.focus({preventScroll: true});
        if (state.tool === 'landmark') {
            if (!insideImage(state, p)) { return; }
            addRoi(state, {type: 'landmark', coordinates: {x: p.x / state.info.width, y: p.y / state.info.height}});
        } else if (state.tool === 'polygon') {
            if (!insideImage(state, p)) { return; }
            if (!state.drawing) { state.drawing = {type: 'polygon', points: []}; }
            var pts = state.drawing.points;
            if (pts.length >= 3) {
                var first = toElement(state, pts[0].x, pts[0].y);
                if (Math.hypot(first.x - e.position.x, first.y - e.position.y) < 10) {
                    finishPolygon(state);
                    return;
                }
            }
            var last = pts[pts.length - 1];
            if (last && Math.hypot(last.x - p.x, last.y - p.y) * state.scale < 3) { return; }
            pts.push(p);
            drawTemp(state);
            updateHint(state);
        } else if (state.tool === 'pan') {
            pickCell(state, p);
        }
    }

    function onPointerMove(state, e) {
        if (!state.drawing || state.drawing.type !== 'polygon' || !state.viewer) { return; }
        var rect = state.host.getBoundingClientRect();
        state.drawing.cursor = toImage(state, new window.OpenSeadragon.Point(e.clientX - rect.left,
                                                                           e.clientY - rect.top));
        drawTemp(state);
    }

    function finishPolygon(state) {
        var d = state.drawing;
        if (!d || d.type !== 'polygon') { return; }
        state.drawing = null;
        drawTemp(state);
        updateHint(state);
        if (d.points.length < 3) { return; }
        var W = state.info.width, H = state.info.height;
        addRoi(state, {type: 'polygon', coordinates: d.points.map(function (p) {
            return {x: p.x / W, y: p.y / H};
        })});
    }

    function cancelDrawing(state) {
        if (!state.drawing) { return; }
        state.drawing = null;
        drawTemp(state);
        if (state.hint) { updateHint(state); }
    }

    function onKey(state, e) {
        if (e.target !== state.host) { return; }
        var handled = true;
        if (e.key === 'Escape') { cancelDrawing(state); }
        else if (e.key === 'Enter') { finishPolygon(state); }
        else if (e.key === 'Backspace' && state.drawing && state.drawing.points) {
            state.drawing.points.pop(); drawTemp(state); updateHint(state);
        } else if ((e.key === 'Delete' || e.key === 'Backspace') && state.selectedRoi >= 0) {
            removeRoi(state, state.selectedRoi);
        } else if (/^[1-9]$/.test(e.key) && state.selectedCell) {
            var l = state.cfg.cellLabels[parseInt(e.key, 10) - 1];
            if (l) { assignCell(state, l.name); } else { handled = false; }
        } else {
            handled = false;
            Object.keys(TOOL_KEYS).forEach(function (tool) {
                if (e.key.toLowerCase() === TOOL_KEYS[tool] && !e.ctrlKey && !e.metaKey && !e.altKey &&
                        (tool === 'pan' || (state.cfg.tools || []).indexOf(tool) !== -1)) {
                    setTool(state, tool);
                    handled = true;
                }
            });
        }
        if (handled) {
            // Potato's own label shortcuts must not also fire.
            e.preventDefault();
            e.stopPropagation();
        }
    }

    // ------------------------------------------------------------------
    // ROIs
    // ------------------------------------------------------------------

    function labelColour(state, name, list) {
        var entry = (list || state.cfg.labels).filter(function (l) { return l.name === name; })[0];
        return entry ? entry.color : '#888888';
    }

    function addRoi(state, roi) {
        roi.label = state.label;
        roi.color = labelColour(state, state.label);
        roi.z = state.z;
        roi.t = state.t;
        state.rois.push(roi);
        state.selectedRoi = state.rois.length - 1;
        save(state);
        drawRois(state);
        listRois(state);
    }

    function removeRoi(state, index) {
        state.rois.splice(index, 1);
        state.selectedRoi = -1;
        save(state);
        drawRois(state);
        listRois(state);
    }

    function roiNode(state, roi, selected) {
        var W = state.info.width, H = state.info.height, c = roi.coordinates, node;
        if (roi.type === 'bbox') {
            node = svg('rect', {x: c.x * W, y: c.y * H, width: c.width * W, height: c.height * H});
        } else if (roi.type === 'polygon') {
            node = svg('polygon', {points: c.map(function (p) { return (p.x * W) + ',' + (p.y * H); }).join(' ')});
        } else {
            node = svg('circle', {cx: c.x * W, cy: c.y * H});
        }
        node.setAttribute('class', 'mic-roi mic-roi-' + roi.type + (selected ? ' mic-roi-selected' : ''));
        node.style.setProperty('--mic-roi-color', roi.color || labelColour(state, roi.label));
        return node;
    }

    function drawRois(state) {
        if (!state.svg) { return; }
        Array.prototype.slice.call(state.svg.querySelectorAll('.mic-roi')).forEach(function (n) { n.remove(); });
        state.rois.forEach(function (roi, i) {
            if ((roi.z || 0) !== state.z || (roi.t || 0) !== state.t) { return; }
            state.svg.appendChild(roiNode(state, roi, i === state.selectedRoi));
        });
        drawTemp(state);
    }

    function drawTemp(state) {
        if (!state.svg) { return; }
        var old = state.svg.querySelector('.mic-temp');
        if (old) { old.remove(); }
        var d = state.drawing;
        if (!d) { return; }
        var node;
        if (d.type === 'bbox') {
            node = svg('rect', {x: Math.min(d.start.x, d.end.x), y: Math.min(d.start.y, d.end.y),
                                width: Math.abs(d.end.x - d.start.x), height: Math.abs(d.end.y - d.start.y)});
        } else {
            var pts = d.points.concat(d.cursor ? [d.cursor] : []);
            node = svg('polyline', {points: pts.map(function (p) { return p.x + ',' + p.y; }).join(' ')});
        }
        node.setAttribute('class', 'mic-temp');
        node.style.setProperty('--mic-roi-color', labelColour(state, state.label));
        state.svg.appendChild(node);
    }

    function listRois(state) {
        var list = state.root.querySelector('.mic-roi-list');
        if (!list) { return; }
        list.innerHTML = '';
        state.root.querySelector('.mic-roi-count').textContent = '(' + state.rois.length + ')';
        if (!state.rois.length) {
            list.appendChild(el('li', {className: 'mic-empty', text: 'None drawn yet.'}));
        }
        state.rois.forEach(function (roi, i) {
            var where = [];
            if (state.info.size_z > 1) { where.push('z ' + ((roi.z || 0) + 1)); }
            if (state.info.size_t > 1) { where.push('t ' + ((roi.t || 0) + 1)); }
            var select = el('select', {className: 'mic-roi-label', 'aria-label': 'Class of region ' + (i + 1)});
            state.cfg.labels.forEach(function (l) { select.appendChild(el('option', {value: l.name, text: l.name})); });
            select.value = roi.label;
            select.addEventListener('change', function () {
                roi.label = select.value;
                roi.color = labelColour(state, roi.label);
                save(state); drawRois(state); listRois(state);
            });
            list.appendChild(el('li', {className: 'mic-item' + (i === state.selectedRoi ? ' mic-item-selected' : ''),
                                       'data-index': String(i)}, [
                el('span', {className: 'mic-swatch', style: 'background:' + (roi.color || labelColour(state, roi.label))}),
                el('button', {type: 'button', className: 'mic-roi-go',
                    text: TOOL_NAMES[roi.type] + ' ' + (i + 1) + (where.length ? ' (' + where.join(', ') + ')' : ''),
                    onclick: function () { showRoi(state, i); }}),
                select,
                el('button', {type: 'button', className: 'mic-remove', text: '\u00d7',
                              'aria-label': 'Delete region ' + (i + 1), title: 'Delete',
                              onclick: function () { removeRoi(state, i); }})]));
        });
    }

    function showRoi(state, index) {
        var roi = state.rois[index];
        state.selectedRoi = index;
        var planeChanged = (roi.z || 0) !== state.z || (roi.t || 0) !== state.t;
        state.z = roi.z || 0;
        state.t = roi.t || 0;
        ['z', 't'].forEach(function (axis) {
            var range = state.root.querySelector('.mic-plane-' + axis);
            if (range) {
                range.value = String(state[axis]);
                range.dispatchEvent(new Event('input'));
            }
        });
        if (!planeChanged) { drawRois(state); }
        listRois(state);
    }

    // ------------------------------------------------------------------
    // Cells
    // ------------------------------------------------------------------

    function loadRaster(state) {
        if (!state.info || !state.info.label_image) { return; }
        var key = state.z + ':' + state.t;
        if (state.rasters[key]) { state.raster = state.rasters[key]; drawCells(state); return; }
        var url = api(state, '/api/microscopy/labels', 'z=' + state.z + '&t=' + state.t);
        fetch(url, {credentials: 'same-origin'}).then(function (r) {
            if (!r.ok) {
                return r.json().then(function (b) { throw new Error(b.error || ('HTTP ' + r.status)); });
            }
            var w = parseInt(r.headers.get('X-Label-Width'), 10);
            var h = parseInt(r.headers.get('X-Label-Height'), 10);
            var bytes = parseInt(r.headers.get('X-Label-Bytes'), 10);
            var scale = parseFloat(r.headers.get('X-Label-Scale'));
            return r.arrayBuffer().then(function (buf) {
                var ids = bytes === 4 ? new Uint32Array(buf) : new Uint16Array(buf);
                if (ids.length !== w * h) { throw new Error('label raster has the wrong size'); }
                return {width: w, height: h, scale: scale, ids: ids, edges: edges(ids, w, h)};
            });
        }).then(function (raster) {
            state.rasters[key] = raster;
            if (key === state.z + ':' + state.t) {
                state.raster = raster;
                drawCells(state);
                state.form.setAttribute('data-mic-labels', key);
            }
        }).catch(function (err) {
            console.warn('[microscopy] label image', err);
            state.hint.textContent = 'The cell outlines could not be loaded: ' + err.message;
        });
    }

    function edges(ids, w, h) {
        var out = new Uint8Array(w * h);
        for (var y = 0; y < h; y++) {
            for (var x = 0; x < w; x++) {
                var i = y * w + x, v = ids[i];
                if (!v) { continue; }
                if (x === 0 || x === w - 1 || y === 0 || y === h - 1 ||
                    ids[i - 1] !== v || ids[i + 1] !== v || ids[i - w] !== v || ids[i + w] !== v) {
                    out[i] = 1;
                }
            }
        }
        return out;
    }

    function cellAt(state, p) {
        var r = state.raster;
        if (!r || !insideImage(state, p)) { return 0; }
        var x = Math.min(r.width - 1, Math.floor(p.x / r.scale));
        var y = Math.min(r.height - 1, Math.floor(p.y / r.scale));
        return r.ids[y * r.width + x] || 0;
    }

    function pickCell(state, p) {
        if (!state.info.label_image) { return; }
        if (!state.raster) { state.hint.textContent = 'Cell outlines are still loading.'; return; }
        var id = cellAt(state, p);
        selectCell(state, id, false);
    }

    function cellPresent(state, id) {
        var r = state.raster;
        if (!r) { return false; }
        for (var i = 0; i < r.ids.length; i++) { if (r.ids[i] === id) { return true; } }
        return false;
    }

    function selectCell(state, id, fromInput) {
        var box = state.root.querySelector('.mic-selected');
        if (!id || (fromInput && !cellPresent(state, id))) {
            state.selectedCell = null;
            box.textContent = id ? 'There is no cell ' + id + ' in this plane.' : 'No cell there.';
        } else {
            state.selectedCell = id;
            var current = findCell(state, id);
            box.textContent = 'Cell ' + id + ' selected' + (current ? ' (' + current['class'] + ')' : '') +
                              '. Choose its class.';
        }
        state.root.querySelectorAll('.mic-cell-class').forEach(function (b) {
            b.disabled = !state.selectedCell;
            var current = state.selectedCell && findCell(state, state.selectedCell);
            b.setAttribute('aria-pressed', current && current['class'] === b.getAttribute('data-class') ? 'true' : 'false');
        });
        drawCells(state);
    }

    function findCell(state, id) {
        return state.cells.filter(function (c) { return c.label_id === id; })[0] || null;
    }

    function assignCell(state, className) {
        var id = state.selectedCell;
        if (!id) { return; }
        var existing = findCell(state, id);
        if (existing) {
            existing['class'] = className;
            existing.z = state.z;
            existing.t = state.t;
        } else {
            state.cells.push({label_id: id, 'class': className, z: state.z, t: state.t});
        }
        save(state);
        selectCell(state, id, false);
        listCells(state);
    }

    function unassignCell(state, id) {
        state.cells = state.cells.filter(function (c) { return c.label_id !== id; });
        save(state);
        if (state.selectedCell === id) { selectCell(state, id, false); }
        listCells(state);
        drawCells(state);
    }

    function listCells(state) {
        var list = state.root.querySelector('.mic-cell-list');
        var count = state.root.querySelector('.mic-cell-count');
        if (count) { count.textContent = '(' + state.cells.length + ')'; }
        if (!list) { return; }
        list.innerHTML = '';
        state.cells.slice().sort(function (a, b) { return a.label_id - b.label_id; }).forEach(function (c) {
            list.appendChild(el('li', {className: 'mic-item', 'data-cell': String(c.label_id)}, [
                el('span', {className: 'mic-swatch',
                            style: 'background:' + labelColour(state, c['class'], state.cfg.cellLabels)}),
                el('button', {type: 'button', className: 'mic-cell-go',
                              text: 'Cell ' + c.label_id + ': ' + c['class'],
                              onclick: function () { selectCell(state, c.label_id, false); }}),
                el('button', {type: 'button', className: 'mic-remove', text: '\u00d7',
                              'aria-label': 'Remove the class from cell ' + c.label_id, title: 'Remove',
                              onclick: function () { unassignCell(state, c.label_id); }})]));
        });
    }

    function drawCells(state) {
        var r = state.raster, canvas = state.canvas;
        if (!r || !canvas) { return; }
        if (canvas.width !== r.width || canvas.height !== r.height) {
            canvas.width = r.width;
            canvas.height = r.height;
            canvas.style.width = (r.width * r.scale) + 'px';
            canvas.style.height = (r.height * r.scale) + 'px';
        }
        var colours = {};
        state.cells.forEach(function (c) {
            colours[c.label_id] = hexToRgb(labelColour(state, c['class'], state.cfg.cellLabels));
        });
        var ctx = canvas.getContext('2d');
        var image = ctx.createImageData(r.width, r.height);
        var data = image.data, ids = r.ids, edge = r.edges, selected = state.selectedCell;
        for (var i = 0; i < ids.length; i++) {
            var id = ids[i];
            if (!id) { continue; }
            var o = i * 4, rgb = colours[id];
            if (id === selected) {
                if (edge[i]) { data[o] = 255; data[o + 1] = 221; data[o + 2] = 0; data[o + 3] = 255; }
                else { data[o] = 255; data[o + 1] = 255; data[o + 2] = 255; data[o + 3] = 70; }
            } else if (rgb) {
                data[o] = rgb[0]; data[o + 1] = rgb[1]; data[o + 2] = rgb[2];
                data[o + 3] = edge[i] ? 255 : 115;
            } else if (edge[i]) {
                data[o] = 255; data[o + 1] = 255; data[o + 2] = 255; data[o + 3] = 110;
            }
        }
        ctx.putImageData(image, 0, 0);
    }

    // ------------------------------------------------------------------
    // Answer
    // ------------------------------------------------------------------

    function save(state) {
        var h = state.input;
        var has = state.rois.length || state.cells.length;
        var data = {image: {width: state.info.width, height: state.info.height},
                    rois: state.rois, cells: state.cells,
                    label_image: state.info.label_image || null};
        h.value = has ? JSON.stringify(data) : '';
        h.setAttribute('data-modified', 'true');
        h.dispatchEvent(new Event('change', {bubbles: true}));
        declare(state);
    }

    function declare(state) {
        var reasons = [];
        if (state.cfg.minRois && state.rois.length < state.cfg.minRois) {
            reasons.push('draw at least ' + state.cfg.minRois + ' region' + (state.cfg.minRois > 1 ? 's' : ''));
        }
        if (state.cfg.minCells && state.cells.length < state.cfg.minCells) {
            reasons.push('classify at least ' + state.cfg.minCells + ' cell' + (state.cfg.minCells > 1 ? 's' : ''));
        }
        if (reasons.length) { state.form.setAttribute('data-incomplete-reason', reasons.join('; ')); }
        else { state.form.removeAttribute('data-incomplete-reason'); }
    }

    function init() {
        document.querySelectorAll('form.microscopy').forEach(setup);
    }

    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); }
    else { init(); }
    document.addEventListener('instanceChanged', init);
    document.addEventListener('potato:instance-ready', init);

    window.PotatoMicroscopy = {
        init: init,
        state: function (form) { return STATES.get(form || document.querySelector('form.microscopy')); }
    };
})();

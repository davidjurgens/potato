/*
 * Geographic annotation on a map (annotation_type: geo_annotation).
 *
 * Tasks:
 *   draw             points, lines, polygons and freehand polygons, each with a
 *                    label and (feature_text) a typed name
 *   pin              one point per label
 *   classify_region  click regions of the basemap outline to label them
 *
 * The map is OpenLayers (window.ol, vendored). The basemap is what the
 * project configured: a GeoJSON outline (embedded in data-geo-basemap or at a
 * URL), a georeferenced image, a GeoTIFF (geotiff.js is loaded on demand) or
 * XYZ tiles from a configured URL. Nothing else is fetched.
 *
 * The answer is the scheme's hidden input: a GeoJSON FeatureCollection in
 * EPSG:4326, written with OpenLayers' right-hand rule and 7 decimals, then
 * longitudes wrapped into -180..180. Completeness is declared on the form's
 * data-incomplete-reason, which validateRequiredFields reads.
 */
(function () {
    'use strict';
    if (window.PotatoGeoAnnotation) { return; }

    var STATES = new WeakMap();
    var GEO = 'EPSG:4326';
    var TOOL_NAMES = {select: 'Select / move', point: 'Point', line: 'Line', polygon: 'Polygon',
                      freehand: 'Freehand'};
    var TOOL_HINTS = {
        select: 'Click a feature to select it; drag its outline to reshape it. Delete removes it.',
        point: 'Click the map to place a point.',
        line: 'Click to add points; double-click the last point to finish. Backspace undoes a point, Esc cancels.',
        polygon: 'Click to add corners; click the first corner or double-click to finish. Backspace undoes a corner, Esc cancels.',
        freehand: 'Press and drag to draw the outline; release to finish.'
    };
    var KIND_NAMES = {point: 'Point', line: 'Line', polygon: 'Area', freehand: 'Area'};

    // geotiff.js sits next to the OpenLayers build; find it from this script's URL.
    var SCRIPT_SRC = (document.currentScript && document.currentScript.src) || '';
    var GEOTIFF_SRC = SCRIPT_SRC ? SCRIPT_SRC.replace(/geo-annotation\.js(\?.*)?$/, 'vendor/geotiff-3.0.5/geotiff.js')
        : '/static/vendor/geotiff-3.0.5/geotiff.js';
    var geotiffPromise = null;

    function loadGeoTIFF() {
        if (window.GeoTIFF) { return Promise.resolve(); }
        if (!geotiffPromise) {
            geotiffPromise = new Promise(function (resolve, reject) {
                var s = document.createElement('script');
                s.src = GEOTIFF_SRC;
                s.onload = function () { resolve(); };
                s.onerror = function () { reject(new Error('geotiff.js did not load')); };
                document.head.appendChild(s);
            });
        }
        return geotiffPromise;
    }

    // ------------------------------------------------------------------
    // Small helpers
    // ------------------------------------------------------------------

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

    function parseAttr(form, name) {
        var raw = form.getAttribute(name);
        if (!raw) { return null; }
        try { return JSON.parse(raw); } catch (e) { console.error('[geo] bad ' + name, e); return null; }
    }

    function instanceId() {
        var input = document.getElementById('instance_id');
        return input ? input.value : '';
    }

    function token(name, fallback) {
        var v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
        return v || fallback;
    }

    function rgba(hex, alpha) {
        var h = String(hex || '#777777').replace('#', '');
        if (h.length === 3) { h = h.split('').map(function (c) { return c + c; }).join(''); }
        var n = parseInt(h, 16);
        if (isNaN(n)) { return hex; }
        return 'rgba(' + ((n >> 16) & 255) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + alpha + ')';
    }

    function wrapLon(lon) {
        if (lon >= -180 && lon <= 180) { return lon; }
        return ((((lon + 180) % 360) + 360) % 360) - 180;
    }

    function round7(v) { return Math.round(v * 1e7) / 1e7; }

    function mapCoords(coords, fn) {
        if (typeof coords[0] === 'number') { return fn(coords); }
        return coords.map(function (c) { return mapCoords(c, fn); });
    }

    function mapGeometry(geom, fn) {
        if (!geom) { return geom; }
        if (geom.type === 'GeometryCollection') {
            return {type: geom.type, geometries: (geom.geometries || []).map(function (g) { return mapGeometry(g, fn); })};
        }
        return {type: geom.type, coordinates: mapCoords(geom.coordinates, fn)};
    }

    function asFeatureCollection(obj) {
        if (!obj) { return null; }
        if (typeof obj === 'string') {
            try { obj = JSON.parse(obj); } catch (e) { return null; }
        }
        if (Array.isArray(obj)) { return {type: 'FeatureCollection', features: obj}; }
        if (obj.type === 'FeatureCollection') { return obj; }
        if (obj.type === 'Feature') { return {type: 'FeatureCollection', features: [obj]}; }
        if (obj.type && obj.coordinates) {
            return {type: 'FeatureCollection', features: [{type: 'Feature', geometry: obj, properties: {}}]};
        }
        return null;
    }

    function swapped(fc) {
        return {type: 'FeatureCollection', features: (fc.features || []).map(function (f) {
            return Object.assign({}, f, {geometry: mapGeometry(f.geometry, function (p) {
                return [p[1], p[0]].concat(p.slice(2));
            })});
        })};
    }

    function formatLonLat(lonlat) {
        var lon = lonlat[0], lat = lonlat[1];
        return Math.abs(lat).toFixed(4) + '° ' + (lat >= 0 ? 'N' : 'S') + ', ' +
               Math.abs(lon).toFixed(4) + '° ' + (lon >= 0 ? 'E' : 'W');
    }

    function hasWebGL() {
        try {
            var c = document.createElement('canvas');
            return !!(c.getContext('webgl2') || c.getContext('webgl'));
        } catch (e) { return false; }
    }

    // ------------------------------------------------------------------
    // Setup
    // ------------------------------------------------------------------

    function setup(form) {
        var prior = STATES.get(form);
        if (prior && prior.instance === instanceId()) { return; }
        if (prior && prior.map) { prior.map.setTarget(null); }
        var cfg = parseAttr(form, 'data-geo-config') || {};
        var mapEl = form.querySelector('.geo-map');
        var state = {
            form: form, cfg: cfg, instance: instanceId(), mapEl: mapEl,
            toolbar: form.querySelector('.geo-toolbar'), list: form.querySelector('.geo-features'),
            status: form.querySelector('.geo-status'), input: form.querySelector('.geo-annotation-input'),
            labels: cfg.labels || [], colors: {}, nextId: 1, tool: null, map: null,
            assign: {}, regionIndex: {}, activePin: null, drawing: false, selectedId: null
        };
        state.labels.forEach(function (l) { state.colors[l.name] = l.color; });
        state.currentLabel = state.labels.length ? state.labels[0].name : '';
        STATES.set(form, state);
        if (!window.ol) {
            fail(state, 'The map library did not load. Reload the page; if it happens again, tell the researcher.');
            return;
        }
        var needItem = cfg.basemap_field || (cfg.preannotation_field && !storedAnswer(state));
        var itemPromise = needItem ? fetch('/api/instance_data', {credentials: 'same-origin'})
            .then(function (r) { return r.ok ? r.json() : {}; }).catch(function () { return {}; })
            : Promise.resolve({});
        itemPromise.then(function (item) {
            if (STATES.get(form) !== state) { return null; }
            state.item = item || {};
            // The server refused this item's own basemap (an unconfigured
            // external server, tiles without attribution ...): say so
            // instead of drawing whatever is left.
            var refused = cfg.basemap_field && state.item._geo_basemap_refused &&
                state.item._geo_basemap_refused[cfg.basemap_field];
            if (refused) {
                fail(state, 'The map for this item was not loaded (' + refused +
                     '). Tell the researcher.');
                return null;
            }
            return resolveBasemap(state);
        }).then(function (basemap) {
            if (STATES.get(form) !== state || !basemap) { return; }
            build(state, basemap);
        }).catch(function (err) {
            console.error('[geo]', err);
            fail(state, 'The map for this item could not be loaded. Reload the page; if it happens ' +
                 'again, tell the researcher.');
        });
    }

    function fail(state, message) {
        state.mapEl.innerHTML = '';
        state.mapEl.appendChild(el('p', {className: 'geo-error', role: 'alert', text: message}));
    }

    /* The hidden input's value counts only when the server set it or this
       page wrote it: browsers restore hidden inputs across reloads. */
    function storedAnswer(state) {
        var h = state.input;
        if (!h || !h.value) { return null; }
        if (h.getAttribute('data-server-set') !== 'true' && h.getAttribute('data-modified') !== 'true') {
            return null;
        }
        return asFeatureCollection(h.value);
    }

    /* Merge the scheme's basemap with the item's (basemap_field), and fetch
       any GeoJSON outline given by URL. */
    function resolveBasemap(state) {
        var cfg = state.cfg;
        var base = Object.assign({}, cfg.basemap || {});
        var inline = parseAttr(state.form, 'data-geo-basemap');
        var itemValue = cfg.basemap_field ? state.item[cfg.basemap_field] : null;
        if (itemValue) {
            if (typeof itemValue === 'string') {
                if (/\.(tiff?|cog)(\?|$)/i.test(itemValue)) { base = {geotiff: itemValue}; }
                else { base = Object.assign(base, {geojson_url: itemValue}); inline = null; }
            } else if (itemValue.type === 'FeatureCollection' || itemValue.type === 'Feature') {
                inline = asFeatureCollection(itemValue);
            } else if (typeof itemValue === 'object') {
                if (itemValue.tiles || itemValue.image || itemValue.geotiff) {
                    ['tiles', 'image', 'geotiff', 'extent', 'attribution'].forEach(function (k) { delete base[k]; });
                }
                Object.keys(itemValue).forEach(function (k) {
                    if (k === 'geojson') {
                        if (typeof itemValue.geojson === 'string') { base.geojson_url = itemValue.geojson; inline = null; }
                        else { inline = asFeatureCollection(itemValue.geojson); }
                    } else { base[k] = itemValue[k]; }
                });
            }
        }
        var outline = inline ? Promise.resolve(inline) : (base.geojson_url
            ? fetch(base.geojson_url, {credentials: /^https?:|^\/\//.test(base.geojson_url) ? 'omit' : 'same-origin'})
                .then(function (r) { if (!r.ok) { throw new Error('basemap ' + r.status); } return r.json(); })
            : Promise.resolve(null));
        return outline.then(function (gj) {
            var fc = asFeatureCollection(gj);
            if (fc && cfg.coordinate_order === 'latlon' && !inline) { fc = swapped(fc); }
            base.outline = fc;
            return base;
        });
    }

    // ------------------------------------------------------------------
    // Map
    // ------------------------------------------------------------------

    function build(state, basemap) {
        var cfg = state.cfg, ol = window.ol;
        var proj = cfg.projection || 'EPSG:3857';
        state.proj = proj;
        state.format = new ol.format.GeoJSON();
        state.mapEl.innerHTML = '';
        state.theme = {
            border: token('--border', '#d4d4d8'), muted: token('--muted', '#f4f4f5'),
            mutedFg: token('--muted-foreground', '#71717a'), card: token('--card', '#ffffff'),
            fg: token('--foreground', '#09090b'), bg: token('--background', '#ffffff'),
            primary: token('--primary', '#6e56cf')
        };
        var layers = [];
        var extent = null;
        if (basemap.tiles) {
            layers.push(new ol.layer.Tile({source: new ol.source.XYZ({
                url: basemap.tiles, attributions: basemap.attribution || undefined,
                maxZoom: basemap.max_zoom || 19, projection: 'EPSG:3857'})}));
        } else if (basemap.image && basemap.extent) {
            layers.push(new ol.layer.Image({source: new ol.source.ImageStatic({
                url: basemap.image, projection: GEO, imageExtent: basemap.extent,
                attributions: basemap.attribution || undefined})}));
            extent = ol.proj.transformExtent(basemap.extent, GEO, proj);
        }
        // Region / outline layer.
        state.regionSource = new ol.source.Vector({wrapX: false});
        if (basemap.outline) {
            var idProp = basemap.region_id_property || 'id';
            var feats = state.format.readFeatures(basemap.outline, {dataProjection: GEO, featureProjection: proj});
            feats.forEach(function (f, i) {
                var p = f.getProperties();
                var rid = (p[idProp] !== undefined && p[idProp] !== null && p[idProp] !== '') ? p[idProp]
                    : (f.getId() !== undefined ? f.getId() : 'r' + i);
                f.setId(String(rid));
                f.set('__name', p[basemap.region_name_property || 'name'] || '');
                state.regionIndex[String(rid)] = f;
            });
            state.regionSource.addFeatures(feats);
            if (feats.length) { extent = state.regionSource.getExtent(); }
        }
        state.regionLayer = new ol.layer.Vector({source: state.regionSource, declutter: true,
            style: function (f, res) { return regionStyle(state, f, res); }});
        layers.push(state.regionLayer);
        state.source = new ol.source.Vector({wrapX: false});
        state.layer = new ol.layer.Vector({source: state.source,
            style: function (f) { return featureStyle(state, f); }});
        layers.push(state.layer);

        var controls = (ol.control.defaults.defaults || ol.control.defaults)({
            attributionOptions: {collapsible: false}, rotate: false});
        controls.push(new ol.control.ScaleLine());
        state.map = new ol.Map({target: state.mapEl, layers: layers, controls: controls,
            view: new ol.View({projection: proj, center: [0, 0], zoom: 2, maxZoom: 20})});

        var geotiffReady = Promise.resolve(null);
        if (basemap.geotiff) {
            if (!hasWebGL()) {
                note(state, 'This browser cannot draw the GeoTIFF basemap (WebGL is unavailable). ' +
                     'You can still annotate on the outline.');
            } else {
                geotiffReady = loadGeoTIFF().then(function () {
                    var src = new ol.source.GeoTIFF({sources: [{url: basemap.geotiff}], convertToRGB: 'auto', interpolate: false});
                    var layer = new ol.layer.WebGLTile({source: src});
                    state.map.getLayers().insertAt(0, layer);
                    return src.getView().then(function (v) {
                        if (!v || !v.extent) { return null; }
                        var ext = ol.proj.transformExtent(v.extent, v.projection || proj, proj);
                        // Edge tiles are padded with zeros; clip them to the image.
                        layer.setExtent(ext);
                        return ext;
                    });
                }).catch(function (err) {
                    console.error('[geo] GeoTIFF', err);
                    note(state, 'The GeoTIFF basemap could not be loaded.');
                    return null;
                });
            }
        }

        restore(state);
        geotiffReady.then(function (tiffExtent) {
            if (STATES.get(state.form) !== state) { return; }
            fitView(state, extent || tiffExtent);
        });
        buildControls(state);
        bindMap(state);
        declare(state);
        state.form.setAttribute('data-geo-ready', 'true');
        state.form.dispatchEvent(new CustomEvent('geo:ready', {bubbles: true}));
    }

    function note(state, text) {
        var p = state.form.querySelector('.geo-note');
        if (!p) {
            p = el('p', {className: 'geo-note', role: 'note'});
            state.mapEl.parentNode.insertBefore(p, state.mapEl.nextSibling);
        }
        p.textContent = text;
    }

    function fitView(state, extent) {
        var ol = window.ol, view = state.map.getView(), cfg = state.cfg;
        if (cfg.center) {
            view.setCenter(ol.proj.fromLonLat(cfg.center, state.proj));
            view.setZoom(typeof cfg.zoom === 'number' ? cfg.zoom : 5);
            return;
        }
        var ext = extent;
        if ((!ext || ol.extent.isEmpty(ext)) && state.source.getFeatures().length) { ext = state.source.getExtent(); }
        if (ext && !ol.extent.isEmpty(ext) && isFinite(ext[0])) {
            view.fit(ext, {padding: [16, 16, 16, 16], maxZoom: 16});
            if (typeof cfg.zoom === 'number') { view.setZoom(cfg.zoom); }
        } else {
            view.setZoom(typeof cfg.zoom === 'number' ? cfg.zoom : 2);
        }
    }

    // ------------------------------------------------------------------
    // Styles
    // ------------------------------------------------------------------

    function regionStyle(state, f, resolution) {
        var ol = window.ol, t = state.theme, cfg = state.cfg;
        var label = cfg.task === 'classify_region' ? state.assign[f.getId()] : null;
        var hover = state.hoverId === f.getId();
        var fill = label ? rgba(state.colors[label], 0.55) : rgba(t.card, cfg.task === 'classify_region' ? 0.9 : 0.75);
        var name = f.get('__name');
        var showName = name && (cfg.task === 'classify_region' || resolution < 4000);
        return new ol.style.Style({
            fill: new ol.style.Fill({color: fill}),
            stroke: new ol.style.Stroke({color: hover ? t.primary : t.mutedFg, width: hover ? 2.5 : 1}),
            text: showName ? new ol.style.Text({text: String(name), font: '12px system-ui, sans-serif',
                fill: new ol.style.Fill({color: t.fg}), stroke: new ol.style.Stroke({color: t.bg, width: 3}),
                overflow: true}) : undefined
        });
    }

    function featureStyle(state, f) {
        var ol = window.ol, t = state.theme;
        var color = state.colors[f.get('label')] || '#7F7F7F';
        var selected = state.selectedId && f.getId() === state.selectedId;
        var geomType = f.getGeometry() ? f.getGeometry().getType() : '';
        var text = f.get('text') || '';
        if (state.cfg.task === 'pin') {
            text = String(pinIndex(state, f.get('label')) + 1);
        }
        var styles = [];
        if (selected && geomType !== 'Point') {
            styles.push(new ol.style.Style({stroke: new ol.style.Stroke({color: t.bg, width: 7})}));
        }
        styles.push(new ol.style.Style({
            fill: new ol.style.Fill({color: rgba(color, selected ? 0.4 : 0.25)}),
            stroke: new ol.style.Stroke({color: color, width: selected ? 4 : (geomType === 'LineString' ? 3 : 2),
                lineDash: selected ? [8, 4] : undefined}),
            image: new ol.style.Circle({radius: state.cfg.task === 'pin' ? 10 : (selected ? 9 : 7),
                fill: new ol.style.Fill({color: color}),
                stroke: new ol.style.Stroke({color: selected ? t.fg : '#ffffff', width: selected ? 3 : 2})}),
            text: text ? new ol.style.Text({text: text, font: (state.cfg.task === 'pin' ? '600 12px' : '600 13px') +
                    ' system-ui, sans-serif',
                fill: new ol.style.Fill({color: state.cfg.task === 'pin' ? '#ffffff' : t.fg}),
                // A boxed name reads over the region names underneath.
                backgroundFill: state.cfg.task === 'pin' ? undefined : new ol.style.Fill({color: rgba(t.card, 0.92)}),
                backgroundStroke: state.cfg.task === 'pin' ? undefined : new ol.style.Stroke({color: color, width: 1}),
                padding: state.cfg.task === 'pin' ? undefined : [2, 4, 2, 4],
                offsetY: geomType === 'Point' && state.cfg.task !== 'pin' ? -18 : 0,
                overflow: true}) : undefined
        }));
        return styles;
    }

    // ------------------------------------------------------------------
    // Answer: restore and save
    // ------------------------------------------------------------------

    function restore(state) {
        var cfg = state.cfg, stored = storedAnswer(state), fromPre = false;
        if (!stored && cfg.preannotation_field && state.item) {
            stored = asFeatureCollection(state.item[cfg.preannotation_field]);
            if (stored && cfg.coordinate_order === 'latlon') { stored = swapped(stored); }
            fromPre = !!stored;
        }
        if (!stored) { return; }
        if (cfg.task === 'classify_region') {
            (stored.features || []).forEach(function (f) {
                var p = f.properties || {};
                if (p.region !== undefined && p.label) { state.assign[String(p.region)] = p.label; }
            });
            state.regionSource.changed();
            return;
        }
        var feats;
        try {
            feats = state.format.readFeatures(stored, {dataProjection: GEO, featureProjection: state.proj});
        } catch (e) {
            console.error('[geo] stored answer unreadable', e);
            return;
        }
        feats.forEach(function (f) {
            var id = f.getId();
            var m = typeof id === 'string' && /^f(\d+)$/.exec(id);
            if (!m || state.source.getFeatureById(id)) {
                f.setId('f' + state.nextId);
            }
            if (fromPre) { f.set('source', 'preannotation'); }
            if (!f.get('tool')) { f.set('tool', toolOf(f)); }
            if (state.cfg.task === 'pin' && f.getGeometry().getType() !== 'Point') { return; }
            state.source.addFeature(f);
            var n = parseInt(String(f.getId()).slice(1), 10);
            if (n >= state.nextId) { state.nextId = n + 1; }
        });
        // Suggestions are not an answer until the annotator edits one of
        // them or presses "Accept suggestions": an item nobody looked at must
        // not count as labelled.
        state.pendingPre = fromPre && state.source.getFeatures().length > 0;
    }

    function toolOf(f) {
        var t = f.getGeometry() ? f.getGeometry().getType() : '';
        if (t === 'Point' || t === 'MultiPoint') { return 'point'; }
        if (t === 'LineString' || t === 'MultiLineString') { return 'line'; }
        return 'polygon';
    }

    function orderedFeatures(state) {
        return state.source.getFeatures().slice().sort(function (a, b) {
            return parseInt(String(a.getId()).slice(1), 10) - parseInt(String(b.getId()).slice(1), 10);
        });
    }

    function answerObject(state) {
        var cfg = state.cfg;
        if (cfg.task === 'classify_region') {
            var ids = Object.keys(state.assign).filter(function (k) { return state.assign[k]; });
            ids.sort(function (a, b) { return regionOrder(state, a) - regionOrder(state, b); });
            return {type: 'FeatureCollection', features: ids.map(function (rid) {
                var f = state.regionIndex[rid];
                return {type: 'Feature', geometry: null, properties: {
                    region: rid, region_name: f ? (f.get('__name') || '') : '', label: state.assign[rid]}};
            })};
        }
        var obj = state.format.writeFeaturesObject(orderedFeatures(state), {
            dataProjection: GEO, featureProjection: state.proj, rightHanded: true, decimals: 7});
        obj.features.forEach(function (f) {
            f.geometry = mapGeometry(f.geometry, function (p) {
                return [round7(wrapLon(p[0])), round7(Math.max(-90, Math.min(90, p[1])))].concat(p.slice(2));
            });
            var props = f.properties || {};
            Object.keys(props).forEach(function (k) { if (k.indexOf('__') === 0) { delete props[k]; } });
            f.properties = props;
        });
        return obj;
    }

    function regionOrder(state, rid) {
        var keys = Object.keys(state.regionIndex);
        var i = keys.indexOf(rid);
        return i < 0 ? keys.length : i;
    }

    function save(state) {
        var obj = answerObject(state);
        var h = state.input;
        state.touched = true;
        state.pendingPre = false;
        h.value = obj.features.length ? JSON.stringify(obj) : '';
        h.setAttribute('data-modified', 'true');
        h.dispatchEvent(new Event('change', {bubbles: true}));
        h.dispatchEvent(new Event('input', {bubbles: true}));
        declare(state);
    }

    function declare(state) {
        var cfg = state.cfg, reasons = [];
        if (state.pendingPre) {
            reasons.push('check the suggested features: edit them, or press Accept suggestions');
        }
        if (cfg.task === 'draw') {
            var feats = state.source.getFeatures();
            var min = typeof cfg.min_features === 'number' ? cfg.min_features : (cfg.required ? 1 : 0);
            if (feats.length < min) {
                reasons.push(min === 1 ? 'draw at least one feature on the map'
                    : 'draw at least ' + min + ' features on the map (' + feats.length + ' so far)');
            }
            if (cfg.feature_text && cfg.feature_text.required) {
                var unnamed = feats.filter(function (f) { return !String(f.get('text') || '').trim(); }).length;
                if (unnamed) { reasons.push(unnamed === 1 ? 'one feature has no name'
                    : unnamed + ' features have no name'); }
            }
        } else if (cfg.task === 'pin') {
            var missing = state.labels.filter(function (l) { return !pinFor(state, l.name); })
                .map(function (l) { return l.name; });
            if (missing.length) { reasons.push('place a pin for: ' + missing.join(', ')); }
            if (cfg.feature_text && cfg.feature_text.required) {
                var blank = state.source.getFeatures().filter(function (f) { return !String(f.get('text') || '').trim(); });
                if (blank.length) { reasons.push('name every pin'); }
            }
        } else {
            var total = Object.keys(state.regionIndex).length;
            var done = Object.keys(state.assign).filter(function (k) { return state.assign[k]; }).length;
            if (cfg.require_all_regions && done < total) {
                reasons.push('label every region (' + done + ' of ' + total + ' done)');
            } else if (cfg.required && !done) {
                reasons.push('label at least one region');
            }
        }
        if (reasons.length) { state.form.setAttribute('data-incomplete-reason', reasons.join('; ')); }
        else { state.form.removeAttribute('data-incomplete-reason'); }
    }

    // ------------------------------------------------------------------
    // Controls
    // ------------------------------------------------------------------

    function setStatus(state, text) { if (state.status) { state.status.textContent = text; } }

    function labelSelect(state, value, aria, onchange, className) {
        var sel = el('select', {className: className || 'geo-label-select', 'aria-label': aria, onchange: onchange});
        var names = state.labels.map(function (l) { return l.name; });
        if (value && names.indexOf(value) < 0) { names.push(value); }
        names.forEach(function (n) {
            var o = el('option', {value: n, text: n});
            if (n === value) { o.selected = true; }
            sel.appendChild(o);
        });
        return sel;
    }

    function buildControls(state) {
        var cfg = state.cfg, bar = state.toolbar;
        bar.innerHTML = '';
        if (cfg.task === 'draw') {
            bar.appendChild(el('label', {className: 'geo-field'}, [
                el('span', {text: 'Label for new features'}),
                labelSelect(state, state.currentLabel, 'Label for new features', function () {
                    state.currentLabel = this.value;
                }, 'geo-current-label')]));
            var tools = el('div', {className: 'geo-tools', role: 'group', 'aria-label': 'Drawing tool'});
            ['select'].concat(cfg.tools || []).forEach(function (t) {
                tools.appendChild(el('button', {type: 'button', className: 'geo-tool', 'data-tool': t,
                    'aria-pressed': 'false', text: TOOL_NAMES[t],
                    onclick: function () { setTool(state, t); }}));
            });
            bar.appendChild(tools);
            var actions = el('div', {className: 'geo-actions'});
            if ((cfg.tools || []).indexOf('point') >= 0) {
                actions.appendChild(el('button', {type: 'button', className: 'geo-action geo-add-centre',
                    text: 'Add point at map centre', onclick: function () { addPointAtCentre(state); }}));
            }
            actions.appendChild(el('button', {type: 'button', className: 'geo-action geo-undo', text: 'Undo last point',
                disabled: true, onclick: function () { if (state.draw) { state.draw.removeLastPoint(); } }}));
            actions.appendChild(el('button', {type: 'button', className: 'geo-action geo-finish', text: 'Finish shape',
                disabled: true, onclick: function () { if (state.draw) { state.draw.finishDrawing(); } }}));
            actions.appendChild(el('button', {type: 'button', className: 'geo-action geo-delete-selected',
                text: 'Delete selected', disabled: true, onclick: function () { deleteSelected(state); }}));
            bar.appendChild(actions);
            bar.appendChild(el('p', {className: 'geo-hint'}));
            var first = (cfg.tools || []).indexOf('freehand') >= 0 ? 'freehand' : ((cfg.tools || [])[0] || 'select');
            setTool(state, first);
        } else if (cfg.task === 'pin') {
            bar.appendChild(el('p', {className: 'geo-hint',
                text: 'Choose a pin below, then click the map to place it. Drag a pin to move it.'}));
            state.activePin = firstUnplaced(state);
            setPinMode(state);
        } else {
            var group = el('div', {className: 'geo-tools', role: 'group', 'aria-label': 'Label to assign'});
            state.labels.forEach(function (l) {
                group.appendChild(el('button', {type: 'button', className: 'geo-tool geo-assign',
                    'data-label': l.name, 'aria-pressed': 'false', onclick: function () {
                        state.currentLabel = l.name; refreshToolbar(state);
                    }}, [el('span', {className: 'geo-swatch', style: 'background:' + l.color, 'aria-hidden': 'true'}),
                         document.createTextNode(l.name)]));
            });
            group.appendChild(el('button', {type: 'button', className: 'geo-tool geo-assign', 'data-label': '',
                'aria-pressed': 'false', text: 'Erase', onclick: function () {
                    state.currentLabel = ''; refreshToolbar(state);
                }}));
            bar.appendChild(group);
            bar.appendChild(el('p', {className: 'geo-hint',
                text: 'Choose a label, then click regions on the map, or use the list below. ' +
                      'Clicking a region again with the same label clears it.'}));
            refreshToolbar(state);
        }
        renderList(state);
    }

    function refreshToolbar(state) {
        var cfg = state.cfg;
        state.toolbar.querySelectorAll('.geo-tool').forEach(function (b) {
            var on = cfg.task === 'classify_region' ? b.getAttribute('data-label') === state.currentLabel
                : b.getAttribute('data-tool') === state.tool;
            b.setAttribute('aria-pressed', on ? 'true' : 'false');
        });
        if (cfg.task !== 'draw') { return; }
        var full = typeof cfg.max_features === 'number' && state.source.getFeatures().length >= cfg.max_features;
        state.toolbar.querySelectorAll('.geo-tool').forEach(function (b) {
            b.disabled = full && b.getAttribute('data-tool') !== 'select';
        });
        var centre = state.toolbar.querySelector('.geo-add-centre');
        if (centre) { centre.disabled = full; }
        state.toolbar.querySelector('.geo-undo').disabled = !state.drawing;
        state.toolbar.querySelector('.geo-finish').disabled = !state.drawing;
        state.toolbar.querySelector('.geo-delete-selected').disabled = !state.selectedId;
        var hint = state.toolbar.querySelector('.geo-hint');
        hint.textContent = full ? 'The most features this question takes is ' + cfg.max_features +
            '. Delete one to draw another.' : TOOL_HINTS[state.tool] || '';
    }

    function clearInteractions(state) {
        ['draw', 'modify', 'select', 'snap', 'snapRegions', 'pinModify'].forEach(function (k) {
            if (state[k]) { state.map.removeInteraction(state[k]); state[k] = null; }
        });
        state.drawing = false;
    }

    function addSnap(state) {
        if (!state.cfg.snapping) { return; }
        var ol = window.ol;
        state.snap = new ol.interaction.Snap({source: state.source});
        state.map.addInteraction(state.snap);
        if (state.regionSource.getFeatures().length) {
            state.snapRegions = new ol.interaction.Snap({source: state.regionSource});
            state.map.addInteraction(state.snapRegions);
        }
    }

    function setTool(state, tool) {
        var ol = window.ol, cfg = state.cfg;
        var full = typeof cfg.max_features === 'number' && state.source.getFeatures().length >= cfg.max_features;
        if (full && tool !== 'select') { tool = 'select'; }
        clearInteractions(state);
        state.tool = tool;
        if (tool === 'select') {
            state.select = new ol.interaction.Select({layers: [state.layer], style: null, hitTolerance: 6});
            state.select.on('select', function (e) {
                var f = e.selected[0];
                selectFeature(state, f ? f.getId() : null, false);
            });
            state.map.addInteraction(state.select);
            state.modify = new ol.interaction.Modify({features: state.select.getFeatures()});
            state.modify.on('modifyend', function (e) {
                e.features.forEach(function (f) { f.unset('source'); });
                save(state);
                setStatus(state, 'Shape changed.');
            });
            state.map.addInteraction(state.modify);
            if (state.selectedId) {
                var sel = state.source.getFeatureById(state.selectedId);
                if (sel) { state.select.getFeatures().push(sel); }
            }
        } else {
            var type = {point: 'Point', line: 'LineString', polygon: 'Polygon', freehand: 'Polygon'}[tool];
            state.draw = new ol.interaction.Draw({source: state.source, type: type, freehand: tool === 'freehand',
                stopClick: true});
            state.draw.on('drawstart', function () { state.drawing = true; refreshToolbar(state); });
            state.draw.on('drawabort', function () { state.drawing = false; refreshToolbar(state); });
            state.draw.on('drawend', function (e) {
                state.drawing = false;
                var f = e.feature;
                f.setId('f' + state.nextId++);
                f.set('label', state.currentLabel);
                f.set('tool', tool);
                if (cfg.feature_text) { f.set('text', ''); }
                // drawend fires before the feature is added to the source.
                setTimeout(function () {
                    save(state);
                    renderList(state, cfg.feature_text ? {id: f.getId(), field: 'text'} : null);
                    setStatus(state, featureName(state, f) + ' added (' + (state.currentLabel || 'no label') + ').');
                    if (typeof cfg.max_features === 'number' && state.source.getFeatures().length >= cfg.max_features) {
                        setTool(state, 'select');
                    } else {
                        refreshToolbar(state);
                    }
                }, 0);
            });
            state.map.addInteraction(state.draw);
        }
        addSnap(state);
        refreshToolbar(state);
    }

    function featureName(state, f) {
        var n = String(f.getId()).slice(1);
        var kind = KIND_NAMES[f.get('tool')] || 'Feature';
        return kind + ' ' + n;
    }

    function selectFeature(state, id, zoom) {
        state.selectedId = id || null;
        if (state.select) {
            var coll = state.select.getFeatures();
            coll.clear();
            var f = id ? state.source.getFeatureById(id) : null;
            if (f) { coll.push(f); }
        }
        if (zoom && id) {
            var feat = state.source.getFeatureById(id);
            if (feat) {
                state.map.getView().fit(feat.getGeometry().getExtent(),
                    {padding: [40, 40, 40, 40], maxZoom: Math.max(state.map.getView().getZoom() || 0, 8),
                     duration: 0});
            }
        }
        state.layer.changed();
        state.list.querySelectorAll('.geo-feature').forEach(function (row) {
            row.classList.toggle('geo-selected', row.getAttribute('data-feature-id') === state.selectedId);
        });
        refreshToolbar(state);
    }

    function deleteFeature(state, id) {
        var f = state.source.getFeatureById(id);
        if (!f) { return; }
        var name = state.cfg.task === 'pin' ? 'Pin for ' + f.get('label') : featureName(state, f);
        if (state.select) { state.select.getFeatures().remove(f); }
        state.source.removeFeature(f);
        if (state.selectedId === id) { state.selectedId = null; }
        save(state);
        if (state.cfg.task === 'pin') {
            state.activePin = f.get('label');
            setPinMode(state);
        } else if (state.cfg.task === 'draw' && state.tool === 'select') {
            refreshToolbar(state);
        }
        renderList(state);
        setStatus(state, name + ' deleted.');
    }

    function deleteSelected(state) { if (state.selectedId) { deleteFeature(state, state.selectedId); } }

    function addPointAtCentre(state) {
        var ol = window.ol, cfg = state.cfg;
        if (typeof cfg.max_features === 'number' && state.source.getFeatures().length >= cfg.max_features) { return; }
        var f = new ol.Feature({geometry: new ol.geom.Point(state.map.getView().getCenter())});
        f.setId('f' + state.nextId++);
        f.set('label', state.currentLabel);
        f.set('tool', 'point');
        if (cfg.feature_text) { f.set('text', ''); }
        state.source.addFeature(f);
        save(state);
        renderList(state);
        setStatus(state, featureName(state, f) + ' added at the map centre (' + (state.currentLabel || 'no label') + ').');
        if (typeof cfg.max_features === 'number' && state.source.getFeatures().length >= cfg.max_features) {
            setTool(state, 'select');
        } else { refreshToolbar(state); }
    }

    // --- pins ---------------------------------------------------------

    function pinIndex(state, label) {
        for (var i = 0; i < state.labels.length; i++) { if (state.labels[i].name === label) { return i; } }
        return -1;
    }

    function pinFor(state, label) {
        var found = null;
        state.source.getFeatures().forEach(function (f) { if (f.get('label') === label) { found = f; } });
        return found;
    }

    function firstUnplaced(state) {
        for (var i = 0; i < state.labels.length; i++) {
            if (!pinFor(state, state.labels[i].name)) { return state.labels[i].name; }
        }
        return null;
    }

    function setPinMode(state) {
        var ol = window.ol;
        clearInteractions(state);
        state.pinModify = new ol.interaction.Modify({source: state.source, hitDetection: state.layer});
        state.pinModify.on('modifyend', function (e) {
            e.features.forEach(function (f) { f.unset('source'); });
            save(state);
            renderList(state);
            setStatus(state, 'Pin moved.');
        });
        state.map.addInteraction(state.pinModify);
        addSnap(state);
    }

    function placePin(state, label, coordinate) {
        var ol = window.ol;
        var f = pinFor(state, label);
        if (f) {
            f.getGeometry().setCoordinates(coordinate);
            f.unset('source');
        } else {
            f = new ol.Feature({geometry: new ol.geom.Point(coordinate)});
            f.setId('f' + state.nextId++);
            f.set('label', label);
            f.set('tool', 'point');
            if (state.cfg.feature_text) { f.set('text', ''); }
            state.source.addFeature(f);
        }
        save(state);
        state.activePin = firstUnplaced(state);
        renderList(state, state.cfg.feature_text ? {id: f.getId(), field: 'text'} : null);
        setStatus(state, 'Pinned "' + label + '" at ' + formatLonLat(ol.proj.toLonLat(coordinate, state.proj)) + '.' +
                  (state.activePin ? ' Next: ' + state.activePin + '.' : ''));
    }

    // --- regions ------------------------------------------------------

    function assignRegion(state, rid, label, fromMap) {
        var prev = state.assign[rid] || '';
        var next = label;
        if (fromMap && label && prev === label) { next = ''; }
        if (next) { state.assign[rid] = next; } else { delete state.assign[rid]; }
        state.regionSource.changed();
        save(state);
        var f = state.regionIndex[rid];
        var name = (f && f.get('__name')) || rid;
        setStatus(state, next ? name + ': ' + next + '.' : name + ': label cleared.');
        if (fromMap) { renderList(state); }
    }

    // ------------------------------------------------------------------
    // Feature list (the keyboard route to everything the map does)
    // ------------------------------------------------------------------

    function renderList(state, focus) {
        var cfg = state.cfg, box = state.list;
        var active = document.activeElement;
        var keep = focus || (active && box.contains(active) ? {
            id: active.closest('[data-feature-id]') && active.closest('[data-feature-id]').getAttribute('data-feature-id'),
            field: active.getAttribute('data-field')} : null);
        box.innerHTML = '';
        if (cfg.task === 'classify_region') { renderRegionList(state, box); }
        else if (cfg.task === 'pin') { renderPinList(state, box); }
        else { renderDrawList(state, box); }
        if (keep && keep.id) {
            var row = box.querySelector('[data-feature-id="' + CSS.escape(keep.id) + '"]');
            var target = row && (keep.field ? row.querySelector('[data-field="' + keep.field + '"]') : null);
            if (target && !target.disabled) { target.focus(); }
        }
    }

    function textField(state, f, label) {
        var ft = state.cfg.feature_text;
        if (!ft) { return null; }
        var id = state.form.id + '-text-' + f.getId();
        return el('label', {className: 'geo-text', 'for': id}, [
            el('span', {text: ft.prompt + (ft.required ? '' : ' (optional)')}),
            el('input', {type: 'text', id: id, className: 'geo-feature-text', 'data-field': 'text',
                value: f.get('text') || '', placeholder: ft.placeholder || null,
                'aria-label': ft.prompt + ' for ' + label, maxlength: '200',
                oninput: function () {
                    f.set('text', this.value);
                    f.unset('source');
                    save(state);
                }})]);
    }

    function renderDrawList(state, box) {
        var feats = orderedFeatures(state);
        box.appendChild(el('h3', {className: 'geo-list-title', text: 'Features on the map (' + feats.length + ')'}));
        if (state.pendingPre) {
            box.appendChild(el('p', {className: 'geo-suggest'}, [
                document.createTextNode('The features marked "suggested" were drawn in advance. Edit or delete ' +
                    'them, or accept them as they are. '),
                el('button', {type: 'button', className: 'geo-accept', text: 'Accept suggestions',
                    onclick: function () {
                        save(state);
                        renderList(state);
                        setStatus(state, 'Suggestions accepted.');
                    }})]));
        }
        if (!feats.length) {
            box.appendChild(el('p', {className: 'geo-empty', text: 'Nothing drawn yet. Choose a tool above and draw on the map.'}));
            return;
        }
        var ul = el('ul', {className: 'geo-feature-list'});
        feats.forEach(function (f) {
            var name = featureName(state, f);
            var color = state.colors[f.get('label')] || '#7F7F7F';
            var li = el('li', {className: 'geo-feature' + (f.getId() === state.selectedId ? ' geo-selected' : ''),
                'data-feature-id': f.getId()}, [
                el('span', {className: 'geo-swatch', style: 'background:' + color, 'aria-hidden': 'true'}),
                el('span', {className: 'geo-feature-name', text: name +
                    (f.get('source') === 'preannotation' ? ' (suggested)' : '')}),
                labelSelect(state, f.get('label'), 'Label for ' + name, function () {
                    f.set('label', this.value);
                    f.unset('source');
                    save(state);
                    renderList(state, {id: f.getId(), field: 'label'});
                }, 'geo-feature-label'),
                textField(state, f, name),
                el('span', {className: 'geo-row-buttons'}, [
                    el('button', {type: 'button', className: 'geo-show', 'data-field': 'show', text: 'Show',
                        'aria-label': 'Show ' + name + ' on the map', onclick: function () {
                            if (state.tool !== 'select') { setTool(state, 'select'); }
                            selectFeature(state, f.getId(), true);
                        }}),
                    el('button', {type: 'button', className: 'geo-delete', 'data-field': 'delete', text: 'Delete',
                        'aria-label': 'Delete ' + name, onclick: function () { deleteFeature(state, f.getId()); }})
                ])
            ]);
            li.querySelector('.geo-feature-label').setAttribute('data-field', 'label');
            ul.appendChild(li);
        });
        box.appendChild(ul);
    }

    function renderPinList(state, box) {
        var ol = window.ol;
        var ul = el('ul', {className: 'geo-feature-list geo-pin-list', 'aria-label': 'Pins'});
        state.labels.forEach(function (l, i) {
            var f = pinFor(state, l.name);
            var where = f ? formatLonLat(ol.proj.toLonLat(f.getGeometry().getCoordinates(), state.proj)) : 'Not placed';
            var active = state.activePin === l.name;
            var li = el('li', {className: 'geo-feature' + (active ? ' geo-active' : ''),
                'data-feature-id': f ? f.getId() : 'pin-' + i, 'data-label': l.name}, [
                el('span', {className: 'geo-pin-badge', style: 'background:' + l.color, text: String(i + 1),
                    'aria-hidden': 'true'}),
                el('span', {className: 'geo-feature-name'}, [
                    el('strong', {text: l.name}), el('span', {className: 'geo-where', text: where})]),
                f ? textField(state, f, l.name) : null,
                el('span', {className: 'geo-row-buttons'}, [
                    el('button', {type: 'button', className: 'geo-place', 'data-field': 'place',
                        'aria-pressed': active ? 'true' : 'false',
                        text: active ? 'Click the map…' : (f ? 'Move' : 'Place'),
                        'aria-label': (f ? 'Move' : 'Place') + ' the pin for ' + l.name, onclick: function () {
                            state.activePin = l.name;
                            renderList(state, {id: li.getAttribute('data-feature-id'), field: 'place'});
                            setStatus(state, 'Click the map to place "' + l.name + '".');
                        }}),
                    el('button', {type: 'button', className: 'geo-place-centre', 'data-field': 'centre',
                        text: 'Use map centre', 'aria-label': 'Place the pin for ' + l.name + ' at the map centre',
                        onclick: function () { placePin(state, l.name, state.map.getView().getCenter()); }}),
                    el('button', {type: 'button', className: 'geo-delete', 'data-field': 'delete', text: 'Remove',
                        disabled: !f, 'aria-label': 'Remove the pin for ' + l.name, onclick: function () {
                            if (f) { deleteFeature(state, f.getId()); }
                        }})
                ])
            ]);
            ul.appendChild(li);
        });
        box.appendChild(ul);
    }

    function renderRegionList(state, box) {
        var ids = Object.keys(state.regionIndex);
        var done = ids.filter(function (k) { return state.assign[k]; }).length;
        box.appendChild(el('h3', {className: 'geo-list-title', text: 'Regions (' + done + ' of ' + ids.length + ' labelled)'}));
        var wrap = el('div', {className: 'geo-region-scroll'});
        var ul = el('ul', {className: 'geo-feature-list geo-region-list'});
        ids.forEach(function (rid) {
            var f = state.regionIndex[rid];
            var name = f.get('__name') || rid;
            var sel = el('select', {className: 'geo-region-label', 'data-field': 'label',
                'aria-label': 'Label for ' + name, onchange: function () {
                    assignRegion(state, rid, this.value, false);
                    var h = box.querySelector('.geo-list-title');
                    var n = Object.keys(state.assign).filter(function (k) { return state.assign[k]; }).length;
                    if (h) { h.textContent = 'Regions (' + n + ' of ' + ids.length + ' labelled)'; }
                    sw.style.background = state.assign[rid] ? state.colors[state.assign[rid]] : 'transparent';
                    sw.classList.toggle('geo-swatch-empty', !state.assign[rid]);
                }});
            sel.appendChild(el('option', {value: '', text: '— none —'}));
            state.labels.forEach(function (l) {
                var o = el('option', {value: l.name, text: l.name});
                if (state.assign[rid] === l.name) { o.selected = true; }
                sel.appendChild(o);
            });
            var sw = el('span', {className: 'geo-swatch' + (state.assign[rid] ? '' : ' geo-swatch-empty'),
                'aria-hidden': 'true',
                style: 'background:' + (state.assign[rid] ? state.colors[state.assign[rid]] : 'transparent')});
            ul.appendChild(el('li', {className: 'geo-feature', 'data-feature-id': rid}, [
                sw, el('span', {className: 'geo-feature-name', text: name}), sel]));
        });
        wrap.appendChild(ul);
        box.appendChild(wrap);
    }

    // ------------------------------------------------------------------
    // Map events and keys
    // ------------------------------------------------------------------

    function bindMap(state) {
        var map = state.map, cfg = state.cfg;
        map.on('singleclick', function (e) {
            if (cfg.task === 'pin') {
                if (state.activePin) { placePin(state, state.activePin, e.coordinate); }
                else { setStatus(state, 'Every pin is placed. Drag a pin to move it, or press Move in the list.'); }
            } else if (cfg.task === 'classify_region') {
                var hit = null;
                map.forEachFeatureAtPixel(e.pixel, function (f) { hit = f; return true; },
                    {layerFilter: function (l) { return l === state.regionLayer; }});
                if (hit) { assignRegion(state, hit.getId(), state.currentLabel, true); }
            }
        });
        if (cfg.task === 'classify_region') {
            map.on('pointermove', function (e) {
                if (e.dragging) { return; }
                var hit = null;
                map.forEachFeatureAtPixel(e.pixel, function (f) { hit = f; return true; },
                    {layerFilter: function (l) { return l === state.regionLayer; }});
                var id = hit ? hit.getId() : null;
                if (id !== state.hoverId) {
                    state.hoverId = id;
                    state.regionSource.changed();
                    state.mapEl.style.cursor = id ? 'pointer' : '';
                }
            });
        }
        state.mapEl.addEventListener('keydown', function (e) {
            if (e.target !== state.mapEl) { return; }
            if (cfg.task === 'draw') {
                if (e.key === 'Escape' && state.draw && state.drawing) { state.draw.abortDrawing(); e.preventDefault(); }
                else if (e.key === 'Backspace' && state.draw && state.drawing) { state.draw.removeLastPoint(); e.preventDefault(); }
                else if (e.key === 'Enter' && state.draw && state.drawing) { state.draw.finishDrawing(); e.preventDefault(); }
                else if ((e.key === 'Delete' || e.key === 'Backspace') && state.selectedId) {
                    deleteSelected(state); e.preventDefault();
                }
            } else if (cfg.task === 'pin' && e.key === 'Enter' && state.activePin) {
                placePin(state, state.activePin, state.map.getView().getCenter());
                e.preventDefault();
            }
        });
    }

    /* Keys used on the map (pan, zoom, finish, delete) must not also reach
       Potato's page shortcuts: arrow keys there move to another item. */
    var MAP_KEYS = /^(Arrow(Left|Right|Up|Down)|\+|-|=|_|Delete|Backspace|Escape|Enter)$/;
    function guardKeys(e) {
        var form = e.target && e.target.closest && e.target.closest('form.geo-annotation');
        if (!form || !MAP_KEYS.test(e.key)) { return; }
        var tag = e.target.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || e.target.classList.contains('geo-map')) {
            e.stopPropagation();
        }
    }

    function init() {
        document.querySelectorAll('form.geo-annotation').forEach(function (form) {
            if (!form.__geoGuard) {
                form.addEventListener('keydown', guardKeys);
                form.addEventListener('keyup', guardKeys);
                form.__geoGuard = true;
            }
            setup(form);
        });
    }

    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); }
    else { init(); }
    document.addEventListener('instanceChanged', init);
    document.addEventListener('potato:instance-ready', function () {
        // annotation.js clears hidden inputs it did not see the server set
        // while it loads the item. A map that finished first (pre-annotations
        // written into the input) has its answer wiped; write it back.
        document.querySelectorAll('form.geo-annotation').forEach(function (form) {
            var state = STATES.get(form);
            if (state && state.map && state.instance === instanceId() && !state.input.value &&
                    state.input.getAttribute('data-server-set') !== 'true' && state.touched) {
                var obj = answerObject(state);
                if (obj.features.length) { save(state); }
            }
        });
        init();
    });

    window.PotatoGeoAnnotation = {
        init: init,
        /* For tests and the debugger: the map and the answer of one scheme. */
        state: function (schema) {
            var form = document.querySelector('form.geo-annotation[data-schema-name="' + schema + '"]');
            return form ? STATES.get(form) : null;
        }
    };
})();

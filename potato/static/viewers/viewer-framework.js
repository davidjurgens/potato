/*
 * Viewer displays: the shared loader, WebGL check and selection API.
 *
 * Every `.potato-viewer` element rendered by a ViewerDisplay subclass
 * (potato/server_utils/displays/viewer_display.py) is mounted here. Mounting
 *
 *   1. registers a selection API object at window.potatoViewers[field]:
 *        getSelection()          -> {viewer, items: [...], <context>}
 *        setSelection(sel)       -> repaint the viewer and its controls
 *        onSelectionChange(cb)   -> cb(selection, {source: 'user' | 'api'}),
 *                                   returns an unsubscribe function
 *        describe(selOrItem)     -> short human-readable text
 *   2. runs the adapter's init() (controls that need no library, such as the
 *      protein residue table),
 *   3. checks WebGL when the engine needs it, and shows a message instead of
 *      a blank canvas when it is missing,
 *   4. loads the engine's library (committed under /static/vendor/ or a
 *      fetched bundle under /vendor-fetched/), once per page, and runs the
 *      adapter's start().
 *
 * Adapters (protein-structure.js, genome-locus.js) register with
 * PotatoViewerFramework.register(kind, adapter). An adapter is
 *   {key(item), normalizeItem(item), describe(item), context: [...],
 *    init(ctx), start(ctx) -> Promise}
 *
 * Events on document: 'potato:viewer-registered' and 'potato:viewer-ready'
 * ({field, viewer, rendered}); on the element: 'potato:viewer-selection'.
 */
(function () {
    'use strict';
    if (window.PotatoViewerFramework) { return; }

    var adapters = {};
    var assetPromises = {};
    var handles = new WeakMap();
    window.potatoViewers = window.potatoViewers || {};

    function clone(value) { return JSON.parse(JSON.stringify(value)); }

    // ------------------------------------------------------------------
    // Library loading
    // ------------------------------------------------------------------

    function loadAsset(asset) {
        if (assetPromises[asset.src]) { return assetPromises[asset.src]; }
        assetPromises[asset.src] = new Promise(function (resolve, reject) {
            var node;
            if (asset.type === 'style') {
                node = document.createElement('link');
                node.rel = 'stylesheet';
                node.href = asset.src;
            } else {
                node = document.createElement('script');
                node.src = asset.src;
                node.async = false;
            }
            node.onload = function () { resolve(); };
            node.onerror = function () {
                delete assetPromises[asset.src];
                reject(new Error('Could not load ' + asset.src));
            };
            document.head.appendChild(node);
        });
        return assetPromises[asset.src];
    }

    function loadAssets(list) {
        return (list || []).reduce(function (p, asset) {
            return p.then(function () { return loadAsset(asset); });
        }, Promise.resolve());
    }

    // ------------------------------------------------------------------
    // WebGL
    // ------------------------------------------------------------------

    var webglLevel;
    function webglSupport() {
        if (webglLevel !== undefined) { return webglLevel; }
        webglLevel = null;
        try {
            if (document.createElement('canvas').getContext('webgl2')) { webglLevel = 'webgl2'; }
        } catch (e) { /* treated as unsupported */ }
        if (!webglLevel) {
            try {
                var c = document.createElement('canvas');
                if (c.getContext('webgl') || c.getContext('experimental-webgl')) { webglLevel = 'webgl'; }
            } catch (e) { /* treated as unsupported */ }
        }
        return webglLevel;
    }

    function hasWebgl(required) {
        if (!required) { return true; }
        var level = webglSupport();
        return required === 'webgl2' ? level === 'webgl2' : !!level;
    }

    // ------------------------------------------------------------------
    // Media references and the item's other fields
    // ------------------------------------------------------------------

    /* The browser-side twin of potato.media.paths.media_href: a bare or
       media/ path is served from /media/, a rooted path is left alone, and an
       http(s) URL is allowed only when the display turned remote files on. */
    function resolveMedia(ref, allowRemote) {
        var text = String(ref || '').trim();
        if (!text) { return null; }
        if (/^(https?:)?\/\//i.test(text)) { return allowRemote ? text : null; }
        if (/^(data|blob):/i.test(text) || text.charAt(0) === '/') { return text; }
        return '/media/' + text.replace(/^media\//, '').replace(/^\/+/, '');
    }

    var instanceDataPromise = null;
    function instanceData() {
        if (!instanceDataPromise) {
            instanceDataPromise = fetch('/api/instance_data', {credentials: 'same-origin'})
                .then(function (r) {
                    if (!r.ok) { throw new Error('instance data: HTTP ' + r.status); }
                    return r.json();
                });
        }
        return instanceDataPromise;
    }

    // ------------------------------------------------------------------
    // The selection API
    // ------------------------------------------------------------------

    function Viewer(field, kind, element) {
        this.field = field;
        this.kind = kind;
        this.element = element;
        this.state = 'loading';
        this._selection = {viewer: kind, items: []};
        this._listeners = [];
        this._painters = [];
        this._labelColors = {};
    }

    Viewer.prototype._adapter = function () { return adapters[this.kind] || {}; };

    Viewer.prototype._normalize = function (sel) {
        var adapter = this._adapter();
        var out = {viewer: this.kind, items: []};
        var src = sel && typeof sel === 'object' ? sel : {};
        var current = this._selection;
        (adapter.context || []).forEach(function (k) {
            if (src[k] !== undefined && src[k] !== null) { out[k] = src[k]; }
            else if (current[k] !== undefined) { out[k] = current[k]; }
        });
        var seen = {};
        (Array.isArray(src.items) ? src.items : []).forEach(function (item) {
            var norm = adapter.normalizeItem ? adapter.normalizeItem(item) : item;
            if (!norm) { return; }
            if (item && typeof item.label === 'string' && item.label) { norm.label = item.label; }
            var k = adapter.key ? adapter.key(norm) : JSON.stringify(norm);
            if (seen[k]) { return; }
            seen[k] = true;
            out.items.push(norm);
        });
        return out;
    };

    Viewer.prototype.getSelection = function () { return clone(this._selection); };

    Viewer.prototype.setSelection = function (sel) {
        this._selection = this._normalize(sel);
        this._paint();
        this._emit('api');
        return this.getSelection();
    };

    Viewer.prototype.onSelectionChange = function (cb) {
        var self = this;
        this._listeners.push(cb);
        return function () {
            self._listeners = self._listeners.filter(function (f) { return f !== cb; });
        };
    };

    Viewer.prototype.describe = function (sel) {
        var adapter = this._adapter();
        var one = function (item) { return adapter.describe ? adapter.describe(item) : JSON.stringify(item); };
        if (sel && Array.isArray(sel.items)) {
            var parts = sel.items.map(one);
            if (adapter.describeContext) {
                var ctx = adapter.describeContext(sel);
                if (ctx) { parts.unshift(ctx); }
            }
            return parts.length ? parts.join('; ') : 'nothing selected';
        }
        return one(sel || {});
    };

    /* Colours for labelled items, set by the viewer_selection scheme. */
    Viewer.prototype.setLabelColors = function (map) {
        this._labelColors = map || {};
        this._paint();
    };
    Viewer.prototype.colorFor = function (item) {
        return (item && item.label && this._labelColors[item.label]) || null;
    };

    // --- for adapters ---------------------------------------------------

    Viewer.prototype.addPainter = function (fn) {
        this._painters.push(fn);
        try { fn(this._selection); } catch (e) { console.error(e); }
    };

    Viewer.prototype.keyOf = function (item) {
        var adapter = this._adapter();
        var norm = adapter.normalizeItem ? adapter.normalizeItem(item) : item;
        return norm ? (adapter.key ? adapter.key(norm) : JSON.stringify(norm)) : null;
    };

    Viewer.prototype.hasItem = function (item) {
        var k = this.keyOf(item), self = this;
        return this._selection.items.some(function (it) { return self.keyOf(it) === k; });
    };

    /* A change the annotator made in the viewer. */
    Viewer.prototype.userChange = function (sel) {
        this._selection = this._normalize(sel);
        this._paint();
        this._emit('user');
    };

    Viewer.prototype.toggleItem = function (item) {
        var k = this.keyOf(item), self = this;
        if (!k) { return; }
        var items = this._selection.items.filter(function (it) { return self.keyOf(it) !== k; });
        if (items.length === this._selection.items.length) { items.push(item); }
        var next = clone(this._selection);
        next.items = items;
        this.userChange(next);
    };

    Viewer.prototype.setContext = function (key, value) {
        if (this._selection[key] === value) { return; }
        var next = clone(this._selection);
        next[key] = value;
        this.userChange(next);
    };

    Viewer.prototype._paint = function () {
        var sel = this._selection;
        this._painters.forEach(function (fn) {
            try { fn(sel); } catch (e) { console.error('viewer repaint failed', e); }
        });
    };

    Viewer.prototype._emit = function (source) {
        var sel = this.getSelection();
        this._listeners.slice().forEach(function (cb) {
            try { cb(sel, {source: source}); } catch (e) { console.error(e); }
        });
        this.element.dispatchEvent(new CustomEvent('potato:viewer-selection', {
            bubbles: true, detail: {field: this.field, selection: sel, source: source}}));
    };

    // ------------------------------------------------------------------
    // Mounting
    // ------------------------------------------------------------------

    function setState(viewer, state) {
        viewer.state = state;
        viewer.element.setAttribute('data-viewer-state', state);
    }

    function showMessage(element, text, kind) {
        var wrap = element.querySelector('.pv-stage-wrap') || element;
        var msg = wrap.querySelector('.pv-message');
        if (!msg) {
            msg = document.createElement('p');
            wrap.appendChild(msg);
        }
        msg.className = 'pv-message' + (kind ? ' pv-' + kind : '');
        msg.setAttribute('role', kind === 'error' ? 'alert' : 'status');
        msg.textContent = text;
        msg.hidden = !text;
        return msg;
    }

    function announceReady(viewer, rendered) {
        document.dispatchEvent(new CustomEvent('potato:viewer-ready', {
            detail: {field: viewer.field, viewer: viewer, rendered: rendered}}));
    }

    function mount(element) {
        if (handles.has(element)) { return handles.get(element); }
        var cfg;
        try { cfg = JSON.parse(element.getAttribute('data-viewer-config') || '{}'); }
        catch (e) { cfg = {error: 'The viewer configuration could not be read.'}; }
        var viewer = new Viewer(cfg.field || '', cfg.kind || element.getAttribute('data-viewer-kind'), element);
        handles.set(element, viewer);
        window.potatoViewers[viewer.field] = viewer;
        document.dispatchEvent(new CustomEvent('potato:viewer-registered', {
            detail: {field: viewer.field, viewer: viewer}}));

        if (cfg.error) {
            setState(viewer, 'error');
            announceReady(viewer, false);
            return viewer;
        }
        var adapter = adapters[viewer.kind];
        if (!adapter) {
            setState(viewer, 'error');
            showMessage(element, 'This page has no viewer for "' + viewer.kind + '".', 'error');
            announceReady(viewer, false);
            return viewer;
        }
        var statusEl = element.querySelector('.pv-status');
        var ctx = {
            element: element,
            stage: element.querySelector('.pv-stage'),
            config: cfg,
            viewer: viewer,
            status: function (text) { if (statusEl) { statusEl.textContent = text || ''; } },
            message: function (text, kind) { return showMessage(element, text, kind); },
            resolveMedia: function (ref) { return resolveMedia(ref, !!cfg.allowRemote); },
            instanceData: instanceData
        };
        try {
            if (adapter.init) { adapter.init(ctx); }
        } catch (e) {
            console.error('viewer init failed', e);
        }
        if (!hasWebgl(cfg.webgl)) {
            setState(viewer, 'no-webgl');
            showMessage(element, (cfg.engineLabel || 'This viewer') +
                ' needs ' + (cfg.webgl === 'webgl2' ? 'WebGL 2' : 'WebGL') +
                ', which this browser has turned off or does not support, so the 3D view ' +
                'cannot be drawn.' + (adapter.fallbackHint ? ' ' + adapter.fallbackHint : ''),
                'fallback');
            announceReady(viewer, false);
            return viewer;
        }
        loadAssets(cfg.assets).then(function () {
            return adapter.start(ctx);
        }).then(function () {
            setState(viewer, 'ready');
            showMessage(element, '', null);
            announceReady(viewer, true);
        }).catch(function (err) {
            console.error('viewer failed to start', err);
            setState(viewer, 'error');
            showMessage(element, 'The viewer could not load: ' +
                (err && err.message ? err.message : String(err)), 'error');
            announceReady(viewer, false);
        });
        return viewer;
    }

    function init() {
        document.querySelectorAll('.potato-viewer[data-viewer-kind]').forEach(mount);
    }

    function register(kind, adapter) { adapters[kind] = adapter; }

    window.PotatoViewerFramework = {
        register: register,
        mount: mount,
        init: init,
        webglSupport: webglSupport,
        loadAssets: loadAssets,
        resolveMedia: resolveMedia,
        get: function (field) { return window.potatoViewers[field] || null; }
    };

    // Adapters are separate scripts loaded after this one; mount once the
    // document (and with it every adapter) has loaded.
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); }
    else { setTimeout(init, 0); }
    document.addEventListener('instanceChanged', init);
    document.addEventListener('potato:instance-ready', init);
})();

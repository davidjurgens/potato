/**
 * Live collaborative session client (the annotation page, in a session).
 *
 * Loaded only when the server renders the page for a session; it reads
 * `window.potatoCollab` (set by the template) and does five jobs:
 *
 * 1. Routing. The page's own reads and writes about this item go to the
 *    team's answer: data requests get an `X-Potato-Collab` header, saves get
 *    a `collab` field in the body (a beacon cannot carry headers), and
 *    Next/Previous go through the session's navigate endpoint.
 * 2. Sync. It polls the session's events (or listens, when server push is
 *    on) and shows a teammate's change on this item without a reload.
 *    `base_rev` -- the revision this page reflects -- only moves past a
 *    change once it is on screen, so the server can tell what *this*
 *    member changed when they save.
 * 3. Following. In follow mode a member goes where the leader goes, until
 *    they move by hand; a banner takes them back.
 * 4. Presence. Who is here, on which item, editing which scheme.
 * 5. The side rail: Activity (who changed what, with undo), Team, Notes
 *    (personal, only the author sees them) and Discussion (the team's).
 * 6. The rest of working together: sign-off ("ready"), blind-first answers
 *    and their reveal, quick polls, @mentions, the leader's scroll and
 *    playback for followers, catch-up after time away, and a queue for
 *    saves made while offline.
 */
(function () {
    'use strict';

    const cfg = window.potatoCollab;
    if (!cfg || !cfg.sid) return;

    const base = cfg.base || '';
    const cssEscape = (window.CSS && typeof window.CSS.escape === 'function')
        ? (v) => window.CSS.escape(v) : (v) => String(v).replace(/["\\\]\[]/g, '\\$&');
    const apiUrl = (path) => `${base}/collab/api/${encodeURIComponent(cfg.sid)}${path}`;
    const itemUrl = (iid) => `${base}/collab/s/${encodeURIComponent(cfg.sid)}/i/${encodeURIComponent(iid)}`;
    // The same URL again is a reload to the browser, which puts back what the
    // form fields held. A fresh query makes it a plain load of the server's answer.
    const freshUrl = (iid) => `${itemUrl(iid)}?v=${Date.now().toString(36)}`;

    const state = {
        baseRev: Number(cfg.rev) || 0,
        cursor: Number(cfg.cursor) || 0,
        session: null,
        presence: [],
        mySaveIds: new Set(),
        inflightSaves: 0,
        pendingRemote: [],      // edit events for this item, not yet on screen
        stale: {},              // snapshot key -> rev this page still shows
        keyBase: {},            // key -> newer rev shown after a refused save
        history: [],
        polling: null,
        stream: null,
        lastFocus: null,
        toastTimer: null,
    };

    // ------------------------------------------------------------------
    // 1. Routing

    // Data routes that are about the item on the page. Everything else
    // (tracking, the annotator's own paradata) stays the member's.
    const OWNED_PATHS = [
        /^\/get_annotations(\?|$)/,
        /^\/api\/spans\//,
        /^\/api\/links\//,
        /^\/api\/events\//,
        /^\/api\/current_instance(\?|$)/,
        /^\/api\/instance_data/,
        /^\/api\/entity_linking\/update_span/,
        /^\/api\/image_annotations\/previous/,
        /^\/api\/signals\//,
        /^\/api\/spectrum\//,
        /^\/api\/grounding\//,
    ];

    function pathOf(input) {
        try {
            const url = new URL(typeof input === 'string' ? input : input.url, window.location.href);
            if (url.origin !== window.location.origin) return null;
            let path = url.pathname;
            if (base && path.startsWith(base)) path = path.slice(base.length) || '/';
            return path + url.search;
        } catch (e) {
            return null;
        }
    }

    function isOwnedPath(path) {
        return !!path && OWNED_PATHS.some((re) => re.test(path));
    }

    const nativeFetch = window.fetch.bind(window);
    window.fetch = function (input, init) {
        const path = pathOf(input);
        if (isOwnedPath(path)) {
            init = Object.assign({}, init || {});
            const headers = new Headers(init.headers || (typeof input !== 'string' && input.headers) || {});
            headers.set('X-Potato-Collab', cfg.sid);
            init.headers = headers;
        }
        if (path && /^\/updateinstance(\?|$)/.test(path)) {
            return trackedSave(input, init);
        }
        return nativeFetch(input, init);
    };

    /**
     * Saves sent straight to /updateinstance by span, link, event and other
     * managers (not through saveAnnotations) carry no session either; add it
     * so they reach the team's answer instead of being refused as a stray
     * write to a team item.
     */
    function withSession(init) {
        if (!init || typeof init.body !== 'string') return init;
        let body;
        try { body = JSON.parse(init.body); } catch (e) { return init; }
        if (!body || typeof body !== 'object' || Array.isArray(body) || body.collab) return init;
        return Object.assign({}, init, { body: JSON.stringify(window.potatoSaveHooks.decorate(body)) });
    }

    async function trackedSave(input, init) {
        if (cfg.role === 'observer' || retired) {
            // Read-only: nothing to save, and no error to show for it.
            const body = { status: 'success', observer: true };
            return typeof Response === 'function'
                ? new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
                : { ok: true, status: 200, json: () => Promise.resolve(body), clone() { return this; } };
        }
        init = withSession(init);
        state.inflightSaves += 1;
        try {
            let response;
            try {
                response = await nativeFetch(input, init);
            } catch (networkError) {
                queueOffline(input, init);
                throw networkError;
            }
            if (response.status === 401) {
                // Signed out (a server restart does it): keep the change
                // for when this member is back, and say why nothing saves.
                queueOffline(input, init);
                stopPolling();
                signedOut(401);
                return response;
            }
            try {
                const body = await response.clone().json();
                if (body && body.collab) onSaveResult(body.collab);
            } catch (e) { /* not JSON: nothing to learn */ }
            return response;
        } finally {
            state.inflightSaves -= 1;
            if (state.inflightSaves === 0) scheduleApply();
        }
    }

    window.potatoNavigation = { endpoint: apiUrl('/navigate') };

    window.potatoSaveHooks = {
        decorate(payload) {
            // This save carries everything typed or drawn so far.
            dirtySince = 0;
            dirtyInputs.clear();
            const saveId = `${cfg.me}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
            state.mySaveIds.add(saveId);
            payload.collab = {
                sid: cfg.sid,
                base_rev: state.baseRev,
                save_id: saveId,
                stale: Object.assign({}, state.keyBase, state.stale),
            };
            // A page that showed this member's own answer says so: once the
            // item is open to the team, its saves are not the team's.
            if (cfg.blind) payload.collab.rendered_blind = true;
            return payload;
        },
    };

    function setBaseRev(rev) {
        state.baseRev = rev;
        Object.keys(state.keyBase).forEach((k) => {
            if (state.keyBase[k] <= rev) delete state.keyBase[k];
        });
    }

    function onSaveResult(info) {
        if (info.rejected && !info.partial) { onRejected(info); return; }
        if (info.blind) return;
        // Nothing between the page's base and this save: the page is now
        // exactly the server's answer, and can move its base with it.
        if (typeof info.rev_before === 'number' && info.rev_before === state.baseRev
                && typeof info.rev === 'number') {
            setBaseRev(info.rev);
        }
        (info.overwrote || []).forEach((o) => {
            showToast(`You replaced ${o.user}'s change to ${keyLabel(o.key)}.`);
        });
        // The rest of the save went in; the refused values are a teammate's.
        if (info.rejected) onRejected(info);
    }

    // ------------------------------------------------------------------
    // 2. Sync

    // An edit on this page that no save has picked up yet. Set by the
    // annotator's own input -- and by the change event a drawing widget fires
    // to request its autosave -- never by the restore events used to show a
    // teammate's change; cleared when a save captures the page's answer.
    // (annotation.js's own save timer is not a usable signal: it is left set
    // after it fires.)
    let dirtySince = 0;
    // The inputs behind dirtySince, so a "pending edit" that has since gone
    // back to what the page arrived with can be dropped instead of saved.
    const dirtyInputs = new Set();
    let retired = false;
    function arrivedValue(input) {
        if (input._arrivedWith !== undefined) return input._arrivedWith;
        const rendered = input.getAttribute ? input.getAttribute('data-arrived-value') : null;
        return rendered === null ? undefined : rendered;
    }
    function onLocalInput(event) {
        if (applyingRemote) return;
        if (event.detail && event.detail.potatoRestore) return;
        const target = event.target;
        if (!target || !target.closest || target.closest('#collab-rail, #collab-bar')) return;
        // A widget announces its answer with a synthetic change event on its
        // hidden input, including while it sets itself up (table_grid writes
        // its default size, region_caption an empty caption list). Only a
        // value that differs from what the page arrived with is an edit.
        if (!event.isTrusted && target.type === 'hidden') {
            const arrived = arrivedValue(target);
            if (sameBlob(target.value, arrived === undefined ? '' : arrived)) return;
        }
        dirtyInputs.add(target);
        if (!dirtySince) dirtySince = Date.now();
    }

    /** An unsaved edit is still there: some input it touched differs from arrival. */
    function editStillThere() {
        for (const input of dirtyInputs) {
            const arrived = arrivedValue(input);
            if (arrived === undefined || !input.isConnected || !sameBlob(input.value, arrived)) return true;
        }
        return false;
    }

    function sameBlob(a, b) {
        // Empty in any shape: '', [], {}, or an object of empty fields
        // ({"captions": []}, what a widget writes before anything is in it).
        const isEmpty = (v) => v === null || v === undefined || v === ''
            || (Array.isArray(v) && !v.length)
            || (typeof v === 'object' && !Array.isArray(v) && Object.values(v).every(isEmpty));
        const norm = (v) => {
            if (!v) return null;
            try {
                const parsed = JSON.parse(v);
                if (parsed && typeof parsed === 'object' && isEmpty(parsed)) return null;
                return JSON.stringify(parsed);
            } catch (e) { return v; }
        };
        return norm(a) === norm(b);
    }
    document.addEventListener('input', onLocalInput, true);
    document.addEventListener('change', onLocalInput, true);

    function localEditPending() {
        try {
            /* global pendingInputChanges */
            if (typeof pendingInputChanges !== 'undefined' && pendingInputChanges.size > 0) return true;
        } catch (e) { /* annotation.js not loaded */ }
        return dirtySince > 0 || state.inflightSaves > 0;
    }

    let applyTimer = null;
    function scheduleApply() {
        clearTimeout(applyTimer);
        applyTimer = setTimeout(applyPending, 50);
    }

    async function applyPending() {
        if (!state.pendingRemote.length) return;
        // Applying over an edit that has not been saved would show the
        // teammate's value and then save it back as this member's. Wait for
        // the save; it carries the old base, so the server merges it right.
        if (dirtySince && state.inflightSaves === 0 && !editStillThere()) {
            // What looked like an edit was a widget writing the value the
            // page arrived with (a default, then annotation.js clearing it).
            dirtySince = 0;
            dirtyInputs.clear();
        }
        if (localEditPending()) {
            // An edit no autosave picked up (some widgets only save on
            // navigation): save it, so the teammate's change can follow.
            if (dirtySince && Date.now() - dirtySince > 4000 && state.inflightSaves === 0
                    && typeof saveAnnotations === 'function') {
                saveAnnotations({ background: true });
            }
            applyTimer = setTimeout(applyPending, 300);
            return;
        }
        const events = state.pendingRemote.splice(0);
        let answer;
        try {
            const r = await nativeFetch(apiUrl(`/item/${encodeURIComponent(cfg.instance_id)}`),
                                        { credentials: 'same-origin' });
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            answer = (await r.json()).answer || {};
        } catch (e) {
            state.pendingRemote.unshift(...events);
            applyTimer = setTimeout(applyPending, 2000);
            return;
        }
        const keys = new Set();
        let lastRev = state.baseRev;
        events.forEach((e) => {
            (e.data.ops || []).forEach((op) => keys.add(op.key));
            lastRev = Math.max(lastRev, Number(e.data.rev) || 0);
        });
        const shown = withRemoteApply(() => applyKeys(keys, answer));
        // Keys no widget could show stay at the revision the page shows.
        keys.forEach((key) => {
            if (!shown.has(key) && !(key in state.stale)) state.stale[key] = state.baseRev;
        });
        setBaseRev(lastRev);
        updateStaleBanner();
        flashChanged(events);
    }

    /**
     * conflict_policy: reject. The save (or part of it, when ``partial``) was
     * refused because a teammate changed the same thing first. Show their
     * value; the refused keys are based on the revision now shown, so a later
     * change to them by this member is a change, not a stale copy.
     */
    async function onRejected(info) {
        const keys = new Set((info.conflicts || []).map((c) => c.key));
        const names = [...new Set((info.conflicts || []).map((c) => c.user).filter(Boolean))];
        showToast(`${info.partial ? 'Partly saved' : 'Not saved'}: `
                  + `${names.length ? names.join(', ') : 'a teammate'} changed `
                  + `${[...keys].map(keyLabel).join(', ')} first. Your page now shows their answer`
                  + `${info.partial ? ' there; your other changes are saved.' : '.'}`);
        try {
            const r = await nativeFetch(apiUrl(`/item/${encodeURIComponent(cfg.instance_id)}`),
                                        { credentials: 'same-origin' });
            const body = await r.json();
            const expanded = new Set();
            keys.forEach((k) => {
                expanded.add(k);
                if (k.startsWith('L:') && k.indexOf(':::') < 0) {
                    Object.keys(body.answer || {}).forEach((a) => {
                        if (a.startsWith(k + ':::')) expanded.add(a);
                    });
                }
                state.keyBase[k] = body.rev;
            });
            withRemoteApply(() => applyKeys(expanded, body.answer || {}));
        } catch (e) { /* the next poll brings it */ }
        if (info.partial) return;
        // Whatever was edited after the refused save still needs saving.
        if (typeof saveAnnotations === 'function') {
            setTimeout(() => saveAnnotations({ background: true }), 300);
        }
    }

    // Widgets announce a value put on screen for a teammate with the same
    // change event as an edit; while one is being applied, it is not an edit.
    let applyingRemote = false;
    function withRemoteApply(fn) {
        applyingRemote = true;
        try { return fn(); } finally { applyingRemote = false; }
    }

    /** Put the answer's value for each key on screen; return the keys shown. */
    function applyKeys(keys, answer) {
        const shown = new Set();
        const bySchema = new Map();         // schema -> its changed L: keys
        let spans = false, links = false, evts = false;
        keys.forEach((key) => {
            if (key.startsWith('L:')) {
                const schema = key.slice(2).split(':::')[0];
                if (!bySchema.has(schema)) bySchema.set(schema, []);
                bySchema.get(schema).push(key);
            } else if (key.startsWith('S:')) spans = true;
            else if (key.startsWith('K:')) links = true;
            else if (key.startsWith('E:')) evts = true;
        });

        const native = {};
        bySchema.forEach((schemaKeys, schema) => {
            const labels = schemeAnswer(schema, answer);
            if (hasWidget(schema) || schemaKeys.some((k) => k.endsWith(':::_data'))) {
                if (applyWidget(schema, labels)) schemaKeys.forEach((k) => shown.add(k));
            } else if (nativeCanShow(schema, labels)) {
                native[schema] = labels;
                schemaKeys.forEach((k) => shown.add(k));
            }
            // Otherwise the scheme's widget keeps its own copy of the answer
            // and cannot be told: setting its input would leave the widget
            // showing (and later saving) the old answer. It gets the banner.
        });
        if (Object.keys(native).length) {
            if (typeof window.potatoApplyRemoteLabels === 'function') {
                window.potatoApplyRemoteLabels(native);
            } else {
                Object.keys(native).forEach((schema) => {
                    bySchema.get(schema).forEach((k) => shown.delete(k));
                });
            }
        }
        if (spans && reloadManager(window.spanManager)) {
            keys.forEach((k) => { if (k.startsWith('S:')) shown.add(k); });
        }
        if (links && reloadAll(linkManagers())) {
            keys.forEach((k) => { if (k.startsWith('K:')) shown.add(k); });
        }
        if (evts && reloadAll(Object.values(window.eventAnnotationManagers || {}))) {
            keys.forEach((k) => { if (k.startsWith('E:')) shown.add(k); });
        }
        return shown;
    }

    /** The scheme's whole answer as ``{label: value}``, or null for none. */
    function schemeAnswer(schema, answer) {
        const out = {};
        Object.keys(answer || {}).forEach((k) => {
            if (!k.startsWith('L:')) return;
            const [s, l] = k.slice(2).split(':::');
            if (s === schema && l !== undefined) out[l] = answer[k];
        });
        return Object.keys(out).length ? out : null;
    }

    function schemeForm(schema) {
        // Most schemes render a <form>; some (point cloud, volume) a <div>
        // carrying the same two attributes.
        return document.querySelector(`form[data-schema-name="${cssEscape(schema)}"]`)
            || document.getElementById(schema)
            || document.querySelector(`[data-schema-name="${cssEscape(schema)}"][data-annotation-type]`);
    }

    function schemeType(schema) {
        const form = schemeForm(schema);
        return form ? form.getAttribute('data-annotation-type') : null;
    }

    function widgetFor(schema) {
        const perSchema = (window.potatoCollabAppliers || {})[schema];
        if (typeof perSchema === 'function') return { legacy: perSchema };
        const type = schemeType(schema);
        const registry = window.potatoCollabWidgets || {};
        const widget = type && registry[type];
        if (widget && typeof widget.apply === 'function') return widget;
        const any = (window.potatoCollabAppliers || {})['*'];
        if (typeof any === 'function') return { legacy: any };
        return null;
    }

    function hasWidget(schema) {
        const perSchema = (window.potatoCollabAppliers || {})[schema];
        if (typeof perSchema === 'function') return true;
        const type = schemeType(schema);
        return !!(type && (window.potatoCollabWidgets || {})[type]);
    }

    // Schemes whose hidden input annotation.js's restore pass redraws in
    // full (populateInputValues). It skips an empty value, so a teammate
    // clearing one of these is not shown live. card_sort is not here: its
    // restore cannot rebuild a group the teammate made.
    const REDRAWN_FROM_INPUT = new Set([
        'text_edit', 'extractive_qa', 'error_span', 'trajectory_eval', 'trajectory_edit',
        'ranking', 'hierarchical_multiselect', 'pairwise', 'bws',
    ]);

    /**
     * Can annotation.js's shared applier show this scheme? Native inputs
     * (radio, checkbox, text, range, select, number) show any value. A hidden
     * input belongs to a widget with its own state: only the schemes the
     * restore pass redraws, and only with a value.
     */
    function nativeCanShow(schema, labels) {
        const form = schemeForm(schema);
        const scope = form || document;
        const inputs = Array.from(scope.querySelectorAll('.annotation-input'))
            .filter((el) => el.getAttribute('schema') === schema);
        if (!inputs.length) return false;
        const hidden = inputs.some((el) => (el.type || '').toLowerCase() === 'hidden');
        if (!hidden) return true;
        if (!REDRAWN_FROM_INPUT.has(schemeType(schema))) return false;
        return !!labels && Object.values(labels).every((v) => v !== '' && v !== null && v !== undefined);
    }

    /** Put a value in a widget's hidden input the way the server renders it. */
    function setStored(input, value) {
        const json = value === undefined || value === null ? '' : String(value);
        input.value = json;
        input.setAttribute('value', json);
        input.removeAttribute('data-modified');
        if (json) input.setAttribute('data-server-set', 'true');
        else input.removeAttribute('data-server-set');
        input._arrivedWith = json;
    }

    /**
     * A scheme whose widget keeps its own state: put the answer in its hidden
     * inputs, then ask the widget to redraw from it. Widgets register
     * ``window.potatoCollabWidgets[annotation_type] = {apply(ctx)}``; ``ctx``
     * is ``{schema, form, input, inputs, value, labels}`` (``value`` the
     * ``_data`` JSON or null, ``labels`` the scheme's whole answer or null),
     * and ``apply`` returns true once the answer is on screen. The older
     * ``potatoCollabAppliers[schema](schema, value, input)`` still works.
     */
    function applyWidget(schema, labels) {
        const widget = widgetFor(schema);
        if (!widget) return false;
        const form = schemeForm(schema);
        const input = document.querySelector(`input.annotation-data-input[name="${cssEscape(schema)}"]`);
        const inputs = Array.from((form || document).querySelectorAll('input.annotation-input[type="hidden"]'))
            .filter((el) => el.getAttribute('schema') === schema);
        const value = labels && labels._data !== undefined ? labels._data : null;
        try {
            if (input) setStored(input, value);
            inputs.forEach((el) => setStored(el, labels ? labels[el.getAttribute('label_name')] : null));
            const shown = widget.legacy
                ? widget.legacy(schema, value || null, input) === true
                : widget.apply({ schema, form, input, inputs, value: value || null, labels }) === true;
            // What the widget wrote back is now what "unchanged" looks like.
            if (shown) {
                if (input) input._arrivedWith = input.value;
                inputs.forEach((el) => { el._arrivedWith = el.value; });
            }
            return shown;
        } catch (e) {
            console.warn('[collab] live update failed for', schema, e);
            return false;
        }
    }

    function linkManagers() {
        const managers = Object.values(window.spanLinkManagers || {});
        document.querySelectorAll('.coref-container').forEach((el) => {
            if (el._coreferenceManager) managers.push(el._coreferenceManager);
        });
        return managers;
    }

    function reloadAll(managers) {
        if (!managers.length) return false;
        return managers.every((m) => reloadManager(m));
    }

    function reloadManager(manager) {
        if (!manager) return false;
        for (const name of ['reload', 'loadAnnotations', 'refresh']) {
            if (typeof manager[name] === 'function') {
                try {
                    const result = manager[name](cfg.instance_id);
                    if (result && typeof result.catch === 'function') result.catch(() => {});
                    return true;
                } catch (e) {
                    console.warn('[collab] could not reload', name, e);
                    return false;
                }
            }
        }
        return false;
    }

    function updateStaleBanner() {
        const n = Object.keys(state.stale).length;
        const banner = document.getElementById('collab-stale');
        if (!banner) return;
        banner.hidden = n === 0;
        const text = banner.querySelector('[data-role="text"]');
        if (text) {
            text.textContent = n === 1
                ? 'A teammate changed an answer on this item. Reload to see it.'
                : `Teammates changed ${n} answers on this item. Reload to see them.`;
        }
        if (n > 0) scheduleIdleReload();
    }

    let idleReloadTimer = null;
    let lastInteraction = Date.now();
    ['pointerdown', 'keydown', 'wheel'].forEach((type) => {
        document.addEventListener(type, () => { lastInteraction = Date.now(); }, true);
    });

    function scheduleIdleReload() {
        clearTimeout(idleReloadTimer);
        idleReloadTimer = setTimeout(() => {
            if (!Object.keys(state.stale).length) return;
            if (Date.now() - lastInteraction < 8000 || localEditPending()) {
                scheduleIdleReload();
                return;
            }
            reloadItem();
        }, 8000);
    }

    async function reloadItem() {
        try {
            if (typeof saveAnnotations === 'function') await saveAnnotations({ background: true });
        } catch (e) { /* the save reports its own failure */ }
        window.location.replace(freshUrl(cfg.instance_id));
    }

    function handleEvents(events) {
        let leaderMoved = null;
        events.forEach((e) => {
            if (e.type === 'edit') state.history.push(e);
            if (e.type === 'edit' && e.data.instance_id === cfg.instance_id
                    && Number(e.data.rev) > state.baseRev) {
                if (e.data.save_id && state.mySaveIds.has(e.data.save_id)) {
                    // This page's own save: already on screen.
                    if (Number(e.data.rev) === state.baseRev + 1) state.baseRev = Number(e.data.rev);
                    else state.pendingRemote.push(e);
                } else {
                    state.pendingRemote.push(e);
                }
                (e.data.overwrote || []).forEach((o) => {
                    if (o.user === cfg.me && e.user !== cfg.me) {
                        showToast(`${e.user} replaced your change to ${keyLabel(o.key)}.`, {
                            action: 'Undo theirs', onAction: () => revert(e.seq),
                        });
                    }
                });
            }
            if (e.type === 'viewing' && state.session && e.user === state.session.leader) {
                leaderMoved = e.data.instance_id;
            }
            if (e.type === 'summon' && e.user !== cfg.me && e.data.instance_id !== cfg.instance_id) {
                showToast(`${e.user} asks everyone to look at item ${itemPosition(e.data.instance_id)}.`, {
                    action: 'Go', onAction: () => go(e.data.instance_id, true),
                });
            }
            if (e.type === 'message') {
                appendChat(e);
                if (e.user !== cfg.me && !teamPaneVisible()) markUnread(1);
                if ((e.data.mentions || []).includes(cfg.me)) {
                    showToast(`${e.user} mentioned you: “${clip(e.data.text, 80)}”`, {
                        action: 'Open chat', onAction: () => { setRail(true); selectTab('team'); },
                    });
                }
            }
            if (e.type === 'discussion') {
                if (e.data.instance_id === cfg.instance_id) { notesReadAt = 0; maybeRefreshNotes(); }
                if ((e.data.mentions || []).includes(cfg.me)) {
                    const here = e.data.instance_id === cfg.instance_id;
                    showToast(`${e.user} mentioned you on item ${itemPosition(e.data.instance_id)}: `
                              + `“${clip(e.data.excerpt, 80)}”`, {
                        action: here ? 'Open discussion' : 'Go to it',
                        onAction: () => {
                            if (here) { setRail(true); selectTab('discussion'); }
                            else { rememberTab('discussion'); go(e.data.instance_id, false); }
                        },
                    });
                }
            }
            if (e.type === 'revealed' && e.data.instance_id === cfg.instance_id && cfg.blind) {
                // The team's answer is open now; this page still shows our own.
                announce('Everyone is done. Showing the team answer.');
                retired = true;   // this page holds our own answer, not the team's
                setTimeout(() => window.location.replace(freshUrl(cfg.instance_id)), 600);
            }
            if (e.type === 'poll_opened' && e.user !== cfg.me) {
                const here = e.data.instance_id === cfg.instance_id;
                showToast(`${e.user} asks: ${clip(e.data.question, 80)}`, here ? null : {
                    action: 'Go to it', onAction: () => go(e.data.instance_id, false),
                });
            }
            if (e.type === 'message' || e.type === 'edit') maybeRefreshNotes();
            if (e.type === 'session_closed') showToast('The leader ended this session.');
        });
        if (state.pendingRemote.length) scheduleApply();
        if (leaderMoved) maybeFollow(leaderMoved);
        renderActivity();
        renderStage();
        renderPoll();
    }

    async function poll() {
        try {
            const r = await nativeFetch(apiUrl(`/events?since=${state.cursor}`),
                                        { credentials: 'same-origin' });
            if (r.status === 401 || r.status === 403) { stopPolling(); signedOut(r.status); return; }
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            consume(await r.json());
            pollDelay = currentInterval();
        } catch (e) {
            pollDelay = Math.min((pollDelay || currentInterval()) * 2, 15000);
        }
        state.polling = setTimeout(poll, pollDelay);
    }

    let pollDelay = 0;
    function currentInterval() {
        return document.visibilityState === 'hidden'
            ? (cfg.hidden_poll_interval_ms || 5000) : (cfg.poll_interval_ms || 1000);
    }

    function consume(page) {
        if (page.state) state.session = page.state;
        if (page.presence) { state.presence = page.presence; followView(); }
        maybeRefreshNotes();
        const events = page.events || [];
        keepRecent(events);
        state.cursor = page.cursor != null ? page.cursor : state.cursor + events.length;
        handleEvents(events);
        renderSessionBar();
        renderTeam();
        rememberSeen();
        flushOffline();
    }

    function stopPolling() {
        clearTimeout(state.polling);
        state.polling = null;
        if (state.stream) { state.stream.close(); state.stream = null; }
    }

    function startStream() {
        if (cfg.transport !== 'sse' || typeof EventSource === 'undefined') return false;
        const source = new EventSource(apiUrl(`/stream?since=${state.cursor}`));
        state.stream = source;
        source.addEventListener('batch', (msg) => {
            try { consume(JSON.parse(msg.data)); } catch (e) { /* skip a bad frame */ }
        });
        source.onerror = () => {
            // Over the stream cap, or the stream ended: the browser retries;
            // if it keeps failing, fall back to polling.
            if (source.readyState === EventSource.CLOSED) {
                state.stream = null;
                if (!state.polling) poll();
            }
        };
        return true;
    }

    // ------------------------------------------------------------------
    // 3. Following

    function me() {
        return state.session && state.session.me;
    }

    function maybeFollow(target) {
        const mine = me();
        if (!state.session || state.session.mode !== 'follow' || !mine || !mine.following) return;
        if (state.session.leader === cfg.me || target === cfg.instance_id) return;
        go(target, true);
    }

    async function go(iid, follow) {
        try {
            if (typeof saveAnnotations === 'function' && !localEditIsEmpty()) {
                await saveAnnotations({ background: true });
            }
        } catch (e) { /* reported by the save */ }
        try {
            const r = await nativeFetch(apiUrl('/navigate'), {
                method: 'POST', credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(follow ? { action: 'follow' } : { action: 'go_to', go_to: iid }),
            });
            const body = await r.json();
            window.location.replace(body.url || itemUrl(iid));
        } catch (e) {
            window.location.replace(itemUrl(iid));
        }
    }

    function localEditIsEmpty() {
        return !localEditPending();
    }

    function itemPosition(iid) {
        const ids = (state.session && state.session.item_ids) || [];
        const i = ids.indexOf(iid);
        return i >= 0 ? `${i + 1}` : iid;
    }

    // ------------------------------------------------------------------
    // 4. Presence

    function focusedScheme() {
        const el = document.activeElement;
        if (!el || el === document.body) return null;
        const holder = el.closest('[data-schema-name]') || el.closest('[schema]');
        if (holder) return holder.getAttribute('data-schema-name') || holder.getAttribute('schema');
        return el.getAttribute && el.getAttribute('schema');
    }

    let presenceTimer = null;
    function sendPresence() {
        clearTimeout(presenceTimer);
        const focus = focusedScheme();
        state.lastFocus = focus;
        const body = { instance_id: cfg.instance_id, focus: focus };
        if (amLeading()) body.view = currentView();
        nativeFetch(apiUrl('/presence'), {
            method: 'POST', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        }).catch(() => {});
        presenceTimer = setTimeout(sendPresence, 15000);
    }

    document.addEventListener('focusin', () => {
        if (focusedScheme() !== state.lastFocus) sendPresence();
    });

    // ------------------------------------------------------------------
    // Actions

    async function post(path, body) {
        const r = await nativeFetch(apiUrl(path), {
            method: 'POST', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body || {}),
        });
        let data = {};
        try { data = await r.json(); } catch (e) { /* empty body */ }
        if (!r.ok) throw new Error(data.error || data.message || `HTTP ${r.status}`);
        return data;
    }

    async function revert(seq) {
        try {
            await post('/revert', { seq: seq });
            poll();
        } catch (e) {
            showToast(`Could not undo that change: ${e.message}`);
        }
    }

    // ------------------------------------------------------------------
    // 5. UI

    function el(id) { return document.getElementById(id); }

    function esc(text) {
        return String(text == null ? '' : text).replace(/[&<>"']/g,
            (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    }

    function keyLabel(key) {
        if (key.startsWith('L:')) {
            const [schema, label] = key.slice(2).split(':::');
            return label && label !== '_data' ? `${schema} (${label})` : schema;
        }
        if (key.startsWith('S:')) return 'a span';
        return 'an annotation';
    }

    function timeAgo(ts) {
        const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
        if (s < 10) return 'just now';
        if (s < 60) return `${s}s ago`;
        if (s < 3600) return `${Math.round(s / 60)}m ago`;
        return new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }

    function renderSessionBar() {
        const bar = el('collab-bar');
        if (!bar || !state.session) return;
        const s = state.session;
        const mine = s.me || {};
        const position = itemPosition(cfg.instance_id);
        const leaderView = s.leader_view;
        const away = s.mode === 'follow' && s.leader && s.leader !== cfg.me
            && leaderView && leaderView !== cfg.instance_id;
        el('collab-bar-name').textContent = s.name;
        el('collab-bar-where').textContent = `Item ${position} of ${s.item_ids.length}`;
        const follow = el('collab-bar-follow');
        if (s.mode !== 'follow' || !s.leader) {
            follow.textContent = 'Free mode: everyone moves on their own';
        } else if (s.leader === cfg.me) {
            follow.textContent = 'You are leading';
        } else if (mine.following && !away) {
            follow.textContent = `Following ${s.leader}`;
        } else {
            follow.textContent = `${s.leader} is on item ${itemPosition(leaderView)}`;
        }
        const back = el('collab-bar-return');
        back.hidden = !(away && !mine.following) && !(away && mine.following === false);
        back.textContent = `Go to ${s.leader}'s item`;
        const summon = el('collab-bar-summon');
        summon.hidden = s.leader !== cfg.me && s.mode === 'follow';

        const here = el('collab-bar-here');
        const onItem = state.presence.filter((p) => p.instance_id === cfg.instance_id && p.user !== cfg.me);
        here.innerHTML = onItem.length
            ? onItem.map((p) => `<span class="collab-avatar" title="${esc(p.user)}${p.focus ? ' · editing ' + esc(p.focus) : ''}">${esc(initials(p.user))}</span>`).join('')
            : '';
        here.setAttribute('aria-label', onItem.length
            ? `Also on this item: ${onItem.map((p) => p.user).join(', ')}` : 'No one else on this item');
        markEditing(onItem);
    }

    function initials(name) {
        const parts = String(name).split(/[\s._-]+/).filter(Boolean);
        return (parts.length > 1 ? parts[0][0] + parts[1][0] : String(name).slice(0, 2)).toUpperCase();
    }

    /** Badge each scheme a teammate is working in ("ana is editing"). */
    function markEditing(onItem) {
        document.querySelectorAll('.collab-editing-badge').forEach((b) => b.remove());
        document.querySelectorAll('.collab-has-badge').forEach((f) => f.classList.remove('collab-has-badge'));
        // Answering on your own: where a teammate is working is a hint too.
        const here = ((state.session || {}).items || {})[cfg.instance_id];
        if (here && here.blind) return;
        onItem.forEach((p) => {
            if (!p.focus) return;
            const form = document.querySelector(`[data-schema-name="${cssEscape(p.focus)}"]`);
            if (!form) return;
            const badge = document.createElement('span');
            badge.className = 'collab-editing-badge';
            badge.textContent = `${p.user} is editing`;
            form.classList.add('collab-has-badge');
            form.appendChild(badge);
        });
    }

    function renderActivity() {
        const list = el('collab-activity-list');
        if (!list) return;
        const scope = (el('collab-activity-scope') || {}).value || 'item';
        const rows = state.history
            .filter((e) => scope === 'all' || e.data.instance_id === cfg.instance_id)
            .slice(-200).reverse();
        if (!rows.length) {
            list.innerHTML = `<li class="collab-empty">${scope === 'all'
                ? 'No changes in this session yet.'
                : 'No changes to this item yet. Edits by anyone on the team show up here.'}</li>`;
            return;
        }
        list.innerHTML = rows.map((e) => {
            const lines = (e.data.summary && e.data.summary.length ? e.data.summary : ['changed the answer']);
            const who = e.user ? esc(e.user)
                : (e.data.via === 'reveal' ? 'Agreed before discussion' : 'Session');
            const how = e.data.via === 'poll' ? ' <span class="collab-muted">(poll result)</span>' : '';
            const where = scope === 'all' ? ` <span class="collab-muted">· item ${esc(itemPosition(e.data.instance_id))}</span>` : '';
            const undone = e.data.reverts ? ' <span class="collab-muted">(undo)</span>' : '';
            const canUndo = state.session && state.session.me && state.session.me.role !== 'observer'
                && state.session.status === 'open';
            return `<li class="collab-change">
                <div class="collab-change-head"><strong>${who}</strong>${undone}${how}${where}
                  <time datetime="${new Date(e.ts * 1000).toISOString()}">${esc(timeAgo(e.ts))}</time></div>
                <ul class="collab-change-lines">${lines.map((l) => `<li>${esc(l)}</li>`).join('')}</ul>
                ${canUndo ? `<button type="button" class="collab-link" data-undo="${e.seq}">Undo</button>` : ''}
            </li>`;
        }).join('');
    }

    function renderTeam() {
        const list = el('collab-team-list');
        if (!list || !state.session) return;
        const s = state.session;
        const byUser = {};
        state.presence.forEach((p) => { byUser[p.user] = p; });
        list.innerHTML = s.members.filter((m) => m.active).map((m) => {
            const p = byUser[m.username];
            const where = m.viewing ? `item ${esc(itemPosition(m.viewing))}` : 'not on an item';
            const role = m.username === s.leader ? 'leader' : m.role;
            const editing = p && p.focus ? ` · editing ${esc(p.focus)}` : '';
            const online = p ? 'online' : 'away';
            const handover = s.leader === cfg.me && m.username !== cfg.me && m.role !== 'observer'
                ? `<button type="button" class="collab-link" data-lead="${esc(m.username)}">Make leader</button>` : '';
            return `<li class="collab-member">
                <span class="collab-avatar ${online}" aria-hidden="true">${esc(initials(m.username))}</span>
                <span class="collab-member-text"><span><strong>${esc(m.username)}</strong>${m.username === cfg.me ? ' (you)' : ''}</span>
                  <span class="collab-muted">${esc(role)} · ${where}${editing} · ${online}</span></span>
                ${handover}
            </li>`;
        }).join('');
        const mode = el('collab-mode');
        if (mode) {
            mode.value = s.mode;
            mode.disabled = !!s.leader && s.leader !== cfg.me;
        }
    }

    function teamPaneVisible() {
        const rail = el('collab-rail');
        const pane = el('collab-pane-team');
        return !!(rail && !rail.hidden && pane && !pane.hidden);
    }

    let unread = 0;
    function markUnread(n) {
        unread = n ? unread + n : 0;
        const toggle = el('collab-rail-toggle');
        if (!toggle) return;
        toggle.textContent = unread ? `Session panel (${unread} new)` : 'Session panel';
    }

    // Notes and the team's discussion live in the memos store, not the event
    // log; while the panel shows them, re-read them now and then.
    let notesReadAt = 0;
    function maybeRefreshNotes() {
        const rail = el('collab-rail');
        if (!rail || rail.hidden) return;
        const onNotes = ['collab-pane-notes', 'collab-pane-discussion'].some((id) => el(id) && !el(id).hidden);
        if (onNotes && Date.now() - notesReadAt > 10000) {
            notesReadAt = Date.now();
            loadNotes();
        }
    }

    function appendChat(e) {
        const list = el('collab-chat-list');
        if (!list) return;
        const empty = list.querySelector('.collab-empty');
        if (empty) empty.remove();
        const li = document.createElement('li');
        li.innerHTML = `<strong>${esc(e.user)}</strong> <span class="collab-muted">${esc(timeAgo(e.ts))}</span><div>${highlightMentions(e.data.text, e.data.mentions)}</div>`;
        if ((e.data.mentions || []).includes(cfg.me)) li.classList.add('collab-mentions-me');
        list.appendChild(li);
        list.scrollTop = list.scrollHeight;
    }

    function highlightMentions(text, mentions) {
        let html = esc(text);
        (mentions || []).forEach((name) => {
            const re = new RegExp(`@${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`, 'gi');
            html = html.replace(re, (m) => `<mark class="collab-mention">${m}</mark>`);
        });
        return html;
    }

    function flashChanged(events) {
        const names = new Set();
        events.forEach((e) => (e.data.ops || []).forEach((op) => {
            if (op.key.startsWith('L:')) names.add(op.key.slice(2).split(':::')[0]);
        }));
        names.forEach((schema) => {
            const form = document.querySelector(`[data-schema-name="${cssEscape(schema)}"]`);
            if (!form) return;
            form.classList.remove('collab-remote-change');
            void form.offsetWidth;
            form.classList.add('collab-remote-change');
        });
        const who = [...new Set(events.map((e) => e.user))].join(', ');
        if (who) announce(`${who} changed this item.`);
    }

    function announce(text) {
        const live = el('collab-live');
        if (live) live.textContent = text;
    }

    function showToast(text, opts) {
        const toast = el('collab-toast');
        if (!toast) return;
        toast.querySelector('[data-role="text"]').textContent = text;
        const action = toast.querySelector('[data-role="action"]');
        action.hidden = !(opts && opts.action);
        action.onclick = null;
        if (opts && opts.action) {
            action.textContent = opts.action;
            action.onclick = () => { toast.hidden = true; opts.onAction(); };
        }
        toast.querySelector('[data-role="close"]').onclick = () => { toast.hidden = true; };
        toast.hidden = false;
        clearTimeout(state.toastTimer);
        // A toast that offers an action stays until it is used or dismissed:
        // "undo theirs" has to be there when the annotator gets to it.
        if (!(opts && opts.action)) {
            state.toastTimer = setTimeout(() => { toast.hidden = true; }, 6000);
        }
    }

    // ---- notes and discussion (memos API) ----

    async function loadNotes() {
        try {
            const r = await nativeFetch(`${base}/api/memos?instance_id=${encodeURIComponent(cfg.instance_id)}`,
                                        { credentials: 'same-origin' });
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            const memos = (await r.json()).memos || [];
            renderMemoList('collab-notes-list', memos.filter((m) => m.visibility === 'personal' && !m.parent_id),
                'No notes on this item yet.');
            renderMemoList('collab-discussion-list',
                memos.filter((m) => m.team_id === cfg.team_user),
                'No discussion on this item yet.');
        } catch (e) {
            ['collab-notes-list', 'collab-discussion-list'].forEach((id) => {
                const list = el(id);
                if (list) list.innerHTML = `<li class="collab-empty">Could not load notes (${esc(e.message)}).</li>`;
            });
        }
    }

    function renderMemoList(id, memos, emptyText) {
        const list = el(id);
        if (!list) return;
        list.innerHTML = memos.length ? memos.map((m) => `<li class="collab-note">
                <div class="collab-change-head"><strong>${esc(m.created_by)}</strong>
                  <time datetime="${new Date(m.created_at * 1000).toISOString()}">${esc(timeAgo(m.created_at))}</time></div>
                <div class="collab-note-body">${esc(m.body)}</div>
                ${m.can_delete ? `<button type="button" class="collab-link" data-memo-del="${esc(m.id)}">Delete</button>` : ''}
            </li>`).join('')
            : `<li class="collab-empty">${esc(emptyText)}</li>`;
    }

    async function addMemo(kind) {
        const box = el(kind === 'personal' ? 'collab-note-input' : 'collab-discussion-input');
        const body = (box.value || '').trim();
        if (!body) return;
        try {
            if (kind === 'personal') {
                const r = await nativeFetch(`${base}/api/memos`, {
                    method: 'POST', credentials: 'same-origin',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ instance_id: cfg.instance_id, body: body,
                                           visibility: 'personal' }),
                });
                if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || `HTTP ${r.status}`);
            } else {
                // Through the session, so teammates hear of it (and @mentions).
                await post('/discuss', { instance_id: cfg.instance_id, body: body });
            }
            box.value = '';
            loadNotes();
        } catch (e) {
            showToast(`Could not save the note: ${e.message}`);
        }
    }

    async function deleteMemo(id) {
        try {
            await nativeFetch(`${base}/api/memos/${encodeURIComponent(id)}`,
                              { method: 'DELETE', credentials: 'same-origin' });
        } finally {
            loadNotes();
        }
    }

    // ---- rail ----

    const RAIL_KEY = 'potato-collab-rail';

    function setRail(open) {
        const rail = el('collab-rail');
        const toggle = el('collab-rail-toggle');
        if (!rail || !toggle) return;
        rail.hidden = !open;
        toggle.setAttribute('aria-expanded', String(open));
        document.body.classList.toggle('potato-rail-open', open);
        try { sessionStorage.setItem(RAIL_KEY, open ? '1' : '0'); } catch (e) { /* storage off */ }
        if (open) {
            loadNotes();
            if (teamPaneVisible()) markUnread(0);
        }
    }

    function rememberTab(name) {
        try {
            sessionStorage.setItem(RAIL_KEY, '1');
            sessionStorage.setItem(RAIL_KEY + '-tab', name);
        } catch (e) { /* storage off */ }
    }

    function selectTab(name) {
        document.querySelectorAll('#collab-rail [role="tab"]').forEach((tab) => {
            const on = tab.dataset.tab === name;
            tab.setAttribute('aria-selected', String(on));
            tab.tabIndex = on ? 0 : -1;
            el(tab.getAttribute('aria-controls')).hidden = !on;
        });
        if (name === 'team') markUnread(0);
        if (name === 'notes' || name === 'discussion') { notesReadAt = 0; maybeRefreshNotes(); }
        try { sessionStorage.setItem(RAIL_KEY + '-tab', name); } catch (e) { /* storage off */ }
    }

    function wireUi() {
        const toggle = el('collab-rail-toggle');
        if (toggle) toggle.addEventListener('click', () => setRail(el('collab-rail').hidden));
        const close = el('collab-rail-close');
        if (close) close.addEventListener('click', () => { setRail(false); toggle && toggle.focus(); });

        const tabs = Array.from(document.querySelectorAll('#collab-rail [role="tab"]'));
        tabs.forEach((tab, i) => {
            tab.addEventListener('click', () => selectTab(tab.dataset.tab));
            tab.addEventListener('keydown', (e) => {
                if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
                const next = tabs[(i + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
                selectTab(next.dataset.tab);
                next.focus();
                e.preventDefault();
            });
        });

        document.addEventListener('click', (e) => {
            const undo = e.target.closest('[data-undo]');
            if (undo) revert(Number(undo.dataset.undo));
            const lead = e.target.closest('[data-lead]');
            if (lead) post('/leader', { username: lead.dataset.lead }).then(poll, (err) => showToast(err.message));
            const del = e.target.closest('[data-memo-del]');
            if (del) deleteMemo(del.dataset.memoDel);
        });

        const scope = el('collab-activity-scope');
        if (scope) scope.addEventListener('change', renderActivity);
        const mode = el('collab-mode');
        if (mode) mode.addEventListener('change', () => post('/mode', { mode: mode.value })
            .then(poll, (err) => showToast(err.message)));

        const back = el('collab-bar-return');
        if (back) back.addEventListener('click', () => go(null, true));
        const summon = el('collab-bar-summon');
        if (summon) summon.addEventListener('click', () => post('/summon', { instance_id: cfg.instance_id })
            .then(() => showToast('Asked the team to come to this item.'), (err) => showToast(err.message)));
        const reload = el('collab-stale-reload');
        if (reload) reload.addEventListener('click', reloadItem);

        const chat = el('collab-chat-form');
        if (chat) chat.addEventListener('submit', (e) => {
            e.preventDefault();
            const input = el('collab-chat-input');
            const text = (input.value || '').trim();
            if (!text) return;
            post('/message', { text: text }).then(() => { input.value = ''; poll(); },
                                                 (err) => showToast(err.message));
        });
        const noteForm = el('collab-note-form');
        if (noteForm) noteForm.addEventListener('submit', (e) => { e.preventDefault(); addMemo('personal'); });
        const discForm = el('collab-discussion-form');
        if (discForm) discForm.addEventListener('submit', (e) => { e.preventDefault(); addMemo('team'); });

        wireExtras();

        let open = false, tab = 'activity';
        try {
            open = sessionStorage.getItem(RAIL_KEY) === '1';
            tab = sessionStorage.getItem(RAIL_KEY + '-tab') || 'activity';
        } catch (e) { /* storage off */ }
        selectTab(tab);
        setRail(open);
    }

    async function loadHistory() {
        // The whole session's edits, for the Activity tab's "all items" view.
        try {
            const r = await nativeFetch(apiUrl('/events?since=0'), { credentials: 'same-origin' });
            if (!r.ok) return;
            const page = await r.json();
            const all = page.events || [];
            // Up to the cursor the page was rendered at, events are history:
            // the page already shows their effect. After it, they are news.
            keepRecent(all.slice(0, Number(cfg.cursor) || 0));
            const seen = all.slice(0, Number(cfg.cursor) || 0);
            state.history = seen.filter((e) => e.type === 'edit');
            seen.filter((e) => e.type === 'message').forEach(appendChat);
            state.cursor = Number(cfg.cursor) || 0;
            consume({ events: all.slice(state.cursor), cursor: page.cursor,
                      state: page.state, presence: page.presence });
            renderActivity();
        } catch (e) { /* the poll will fill it in */ }
    }

    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible' && !state.stream) {
            clearTimeout(state.polling);
            poll();
        }
    });

    function start() {
        if (cfg.role === 'observer') makeReadOnly();
        wireUi();
        const seenBefore = loadSeen();  // read before the first poll moves it
        loadHistory().then(() => {
            catchUp(seenBefore, 'Since you were last here');
            if (!startStream()) poll();
        });
        sendPresence();
        watchView();
        loadReveal();
        flushOffline();
    }

    // ------------------------------------------------------------------
    // 6. Working together: stage, sign-off, blind first, polls

    function clip(text, n) {
        const t = String(text == null ? '' : text);
        return t.length > n ? `${t.slice(0, n - 1)}…` : t;
    }

    function editorsOf(s) {
        return (s.members || []).filter((m) => m.active && m.role !== 'observer').map((m) => m.username);
    }

    function canEdit() {
        const s = state.session;
        const mine = me();
        return !!(s && mine && mine.role !== 'observer' && s.status === 'open');
    }

    let formLocked = false;
    function lockForm(on) {
        if (formLocked === on) return;
        formLocked = on;
        document.querySelectorAll('#annotation-forms, .instance-text-container').forEach((node) => {
            if (on) node.setAttribute('inert', ''); else node.removeAttribute('inert');
        });
        document.body.classList.toggle('collab-form-locked', on);
    }

    function makeReadOnly() {
        document.body.classList.add('collab-observer');
        lockForm(true);
    }

    function renderStage() {
        const s = state.session;
        const stage = el('collab-bar-stage');
        if (!s || !stage) return;
        const st = (s.items || {})[cfg.instance_id] || {};
        const editors = editorsOf(s);
        const done = el('collab-blind-done');
        const reveal = el('collab-reveal');
        const sign = el('collab-signoff');
        const editing = canEdit();
        if (cfg.role === 'observer') {
            stage.hidden = false;
            stage.textContent = 'Watching (read-only)';
        } else if (st.blind) {
            const finished = st.blind_done || [];
            const mine = finished.includes(cfg.me);
            stage.hidden = false;
            stage.textContent = mine
                ? `Your answer is in · waiting for ${Math.max(0, editors.length - finished.length)} more`
                : `Answer on your own first · ${finished.length} of ${editors.length} done`;
            if (done) done.hidden = !editing || mine;
            if (reveal) reveal.hidden = !(editing && (s.leader === cfg.me || !s.leader));
            if (sign) sign.hidden = true;
            lockForm(mine);
            return;
        } else if (s.require_signoff) {
            const ready = st.ready || [];
            const mine = ready.includes(cfg.me);
            stage.hidden = false;
            stage.textContent = st.signed_off ? 'Everyone marked this ready'
                : `${ready.length} of ${editors.length} ready`;
            if (sign) {
                sign.hidden = !editing;
                sign.setAttribute('aria-pressed', String(mine));
                sign.textContent = mine ? 'Ready ✓' : 'Mark ready';
            }
        } else {
            stage.hidden = true;
            if (sign) sign.hidden = true;
        }
        if (done) done.hidden = true;
        if (reveal) reveal.hidden = true;
    }

    async function toggleReady() {
        const st = ((state.session || {}).items || {})[cfg.instance_id] || {};
        const ready = !(st.ready || []).includes(cfg.me);
        try {
            // Ready means ready with what is on this page: save it first.
            if (ready && localEditPending() && typeof saveAnnotations === 'function') {
                await saveAnnotations({ background: true });
            }
            await post('/signoff', { instance_id: cfg.instance_id, ready: ready });
            poll();
        } catch (e) {
            showToast(`Could not mark it: ${e.message}`);
        }
    }

    async function finishBlind() {
        try {
            if (typeof saveAnnotations === 'function') await saveAnnotations({ background: true });
            await post('/blind_done', { instance_id: cfg.instance_id });
            poll();
        } catch (e) {
            showToast(`Could not hand in your answer: ${e.message}`);
        }
    }

    // ---- the reveal ----

    async function loadReveal() {
        if (!cfg.blind_first || cfg.blind) return;
        try {
            const r = await nativeFetch(apiUrl(`/item/${encodeURIComponent(cfg.instance_id)}`),
                                        { credentials: 'same-origin' });
            if (!r.ok) return;
            renderReveal((await r.json()).reveal);
        } catch (e) { /* nothing to show */ }
    }

    function renderReveal(rv) {
        const panel = el('collab-revealed');
        if (!panel) return;
        const units = (rv && rv.units) || {};
        if (!Object.keys(units).length) { panel.hidden = true; return; }
        panel.hidden = false;
        const people = rv.answered || [];
        el('collab-revealed-agreement').textContent = rv.agreement == null
            ? 'Only one answer came in'
            : `Agreed on ${Math.round(rv.agreement * 100)}% of questions`;
        const polls = new Set((cfg.single_select || []).map((s) => s.name));
        const rows = Object.keys(units).sort().map((unit) => {
            const u = units[unit];
            const schema = unit.startsWith('L:') ? unit.slice(2) : null;
            const verdict = u.agree ? '<span class="collab-agree">Agreed</span>'
                : (schema && polls.has(schema) && canEdit()
                    ? `<button type="button" class="collab-link" data-poll-schema="${esc(schema)}">Ask the team</button>`
                    : `<span class="collab-muted">${u.detail === 'placement' ? 'Differs in placement' : 'Differs'}</span>`);
            return `<tr><th scope="row">${esc(u.title)}</th>${people.map((p) =>
                `<td>${esc((u.answers || {})[p] || '—')}</td>`).join('')}<td>${verdict}</td></tr>`;
        }).join('');
        el('collab-revealed-body').innerHTML = `<table class="collab-table">
            <thead><tr><th scope="col">Question</th>${people.map((p) =>
                `<th scope="col">${esc(p)}</th>`).join('')}<th scope="col"><span class="collab-visually-hidden">Agreement</span></th></tr></thead>
            <tbody>${rows}</tbody></table>`;
        let hidden = false;
        try { hidden = sessionStorage.getItem('potato-collab-reveal-hidden') === '1'; } catch (e) { /* off */ }
        setRevealHidden(hidden);
    }

    function setRevealHidden(hidden) {
        const body = el('collab-revealed-body');
        const toggle = el('collab-revealed-toggle');
        if (!body || !toggle) return;
        body.hidden = hidden;
        toggle.textContent = hidden ? 'Show' : 'Hide';
        toggle.setAttribute('aria-expanded', String(!hidden));
        try { sessionStorage.setItem('potato-collab-reveal-hidden', hidden ? '1' : '0'); } catch (e) { /* off */ }
    }

    // ---- quick polls ----

    let pollSignature = '';
    const dismissedPolls = new Set();

    function renderPoll() {
        const card = el('collab-poll');
        const s = state.session;
        if (!card || !s) return;
        const polls = (s.polls || []).filter((p) => p.instance_id === cfg.instance_id);
        const poll = polls.find((p) => p.open)
            || polls.filter((p) => !p.open && !dismissedPolls.has(p.poll_id))
                .sort((a, b) => b.opened_at - a.opened_at)[0];
        const editors = editorsOf(s);
        const sig = JSON.stringify([poll, editors.length, canEdit(), s.leader]);
        if (sig === pollSignature) return;
        pollSignature = sig;
        // A re-render replaces the buttons; keep a keyboard user's place.
        const focused = card.contains(document.activeElement) ? document.activeElement : null;
        const refocus = focused && ['vote', 'pollClose', 'pollDismiss'].map((k) =>
            (focused.dataset[k] !== undefined ? [k, focused.dataset[k]] : null)).find(Boolean);
        setTimeout(() => {
            if (!refocus) return;
            const attr = refocus[0].replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`);
            const again = card.querySelector(`[data-${attr}="${cssEscape(refocus[1])}"]`);
            if (again) again.focus();
        }, 0);
        if (!poll) { card.hidden = true; card.innerHTML = ''; return; }
        card.hidden = false;
        const closer = poll.opened_by === cfg.me || s.leader === cfg.me;
        const title = `<div class="collab-poll-head"><strong>${esc(poll.opened_by)} asks:</strong> ${esc(poll.question)}</div>`;
        if (poll.open) {
            const options = poll.options.map((o) => `<button type="button" class="collab-button collab-poll-option"
                    data-vote="${esc(o)}" aria-pressed="${poll.my_vote === o}" ${canEdit() ? '' : 'disabled'}>${esc(o)}</button>`).join('');
            card.innerHTML = `${title}
                <div class="collab-poll-options" role="group" aria-label="Your vote">${options}</div>
                <div class="collab-poll-foot"><span class="collab-muted">${poll.voted.length} of ${editors.length} voted · votes stay hidden until the poll closes</span>
                ${closer ? `<button type="button" class="collab-link" data-poll-close="${esc(poll.poll_id)}">Close</button>` : ''}
                ${closer && poll.schema ? `<button type="button" class="collab-link" data-poll-close="${esc(poll.poll_id)}" data-apply="1">Close and use the winner</button>` : ''}</div>`;
            return;
        }
        const counts = poll.counts || {};
        const total = Object.values(counts).reduce((a, b) => a + b, 0) || 1;
        const bars = poll.options.map((o) => {
            const n = counts[o] || 0;
            const who = Object.entries(poll.votes || {}).filter(([, v]) => v === o).map(([u]) => u);
            return `<li><span class="collab-poll-label">${esc(o)}${o === poll.winner ? ' ✓' : ''}</span>
                <span class="collab-poll-bar" style="--share:${Math.round((n / total) * 100)}%"></span>
                <span class="collab-muted">${n}${who.length ? ` · ${esc(who.join(', '))}` : ''}</span></li>`;
        }).join('');
        const verdict = poll.winner ? `Result: ${esc(poll.winner)}${poll.applied ? ' (applied)' : ''}` : 'No single winner';
        card.innerHTML = `${title}<ul class="collab-poll-results">${bars}</ul>
            <div class="collab-poll-foot"><span>${verdict}</span>
            ${poll.schema && poll.winner && !poll.applied && canEdit()
                ? `<button type="button" class="collab-link" data-poll-close="${esc(poll.poll_id)}" data-apply="1">Use ${esc(poll.winner)}</button>` : ''}
            <button type="button" class="collab-link" data-poll-dismiss="${esc(poll.poll_id)}">Dismiss</button></div>`;
    }

    async function startPoll(body) {
        try {
            await post('/poll', Object.assign({ instance_id: cfg.instance_id }, body));
            poll();
        } catch (e) {
            showToast(`Could not start the poll: ${e.message}`);
        }
    }

    function fillPollForm() {
        const select = el('collab-poll-schema');
        if (!select) return;
        select.innerHTML = (cfg.single_select || []).map((s) =>
            `<option value="${esc(s.name)}">${esc(s.name)} (${esc(s.options.join(', '))})</option>`).join('')
            + '<option value="">A question of my own</option>';
        const custom = el('collab-poll-custom');
        const sync = () => { custom.hidden = select.value !== ''; };
        select.addEventListener('change', sync);
        sync();
    }

    // ------------------------------------------------------------------
    // 7. The leader's view: scroll position and media playheads

    let applyingView = false;
    let viewPausedUntil = 0;
    let lastViewAt = 0;
    let viewTimer = null;

    function syncOn() {
        try { return sessionStorage.getItem('potato-collab-sync') !== '0'; } catch (e) { return true; }
    }

    function amLeading() {
        const s = state.session;
        return !!(s && cfg.sync_view && s.mode === 'follow' && s.leader === cfg.me);
    }

    function isFollowingHere() {
        const s = state.session;
        const mine = me();
        return !!(s && cfg.sync_view && s.mode === 'follow' && s.leader && s.leader !== cfg.me
                  && mine && mine.following && s.leader_view === cfg.instance_id && syncOn());
    }

    function mediaElements() {
        return Array.from(document.querySelectorAll('#main-content audio, #main-content video'));
    }

    function currentView() {
        const doc = document.documentElement;
        const max = Math.max(1, doc.scrollHeight - window.innerHeight);
        return {
            scroll: Math.max(0, Math.min(1, window.scrollY / max)),
            media: mediaElements().map((m, i) => ({
                index: i, time: m.currentTime || 0, paused: !!m.paused, rate: m.playbackRate || 1,
            })),
        };
    }

    function viewChanged() {
        if (!amLeading() || viewTimer) return;
        viewTimer = setTimeout(() => { viewTimer = null; sendPresence(); }, 400);
    }

    function userTouchedView() {
        // A follower who scrolls or plays on their own is left alone for a bit.
        if (!applyingView && isFollowingHere()) viewPausedUntil = Date.now() + 15000;
    }

    function watchView() {
        window.addEventListener('scroll', viewChanged, { passive: true });
        ['play', 'pause', 'seeked', 'ratechange'].forEach((type) => {
            document.addEventListener(type, (e) => {
                const tag = e.target && e.target.tagName;
                if (tag !== 'AUDIO' && tag !== 'VIDEO') return;
                if (!applyingView) userTouchedView();
                viewChanged();
            }, true);
        });
        ['wheel', 'touchmove'].forEach((type) => {
            window.addEventListener(type, (e) => { if (e.isTrusted) userTouchedView(); }, { passive: true });
        });
        // While the leader's media plays, keep the playhead fresh for followers.
        setInterval(() => {
            if (amLeading() && mediaElements().some((m) => !m.paused)) sendPresence();
        }, 3000);
    }

    function followView() {
        if (!isFollowingHere() || Date.now() < viewPausedUntil) return;
        const s = state.session;
        const p = state.presence.find((x) => x.user === s.leader && x.instance_id === cfg.instance_id);
        if (!p || !p.view || p.view.at === lastViewAt) return;
        lastViewAt = p.view.at;
        applyView(p.view);
    }

    function applyView(view) {
        applyingView = true;
        try {
            if (typeof view.scroll === 'number') {
                const doc = document.documentElement;
                const max = Math.max(0, doc.scrollHeight - window.innerHeight);
                window.scrollTo({ top: Math.round(view.scroll * max), behavior: 'auto' });
            }
            const media = mediaElements();
            (view.media || []).forEach((v) => {
                const m = media[v.index];
                if (!m) return;
                if (m.playbackRate !== v.rate) m.playbackRate = v.rate;
                // A paused leader's time is exact; a playing one's is up to a
                // poll old, so only a real drift is corrected.
                const tolerance = v.paused ? 0.25 : 1.5;
                if (Math.abs((m.currentTime || 0) - v.time) > tolerance) m.currentTime = v.time;
                if (v.paused && !m.paused) m.pause();
                if (!v.paused && m.paused) {
                    const started = m.play();
                    if (started && typeof started.catch === 'function') started.catch(() => {});
                }
            });
        } finally {
            setTimeout(() => { applyingView = false; }, 800);
        }
    }

    // ------------------------------------------------------------------
    // 8. Catch-up, and saves made while offline

    const SEEN_KEY = `potato-collab-seen-${cfg.sid}-${cfg.me}`;
    const OFFLINE_KEY = `potato-collab-offline-${cfg.sid}-${cfg.me}`;
    const recent = [];

    function loadSeen() {
        try {
            const v = Number(localStorage.getItem(SEEN_KEY));
            return v > 0 ? v : null;
        } catch (e) { return null; }
    }

    function rememberSeen() {
        try { localStorage.setItem(SEEN_KEY, String(state.cursor)); } catch (e) { /* off */ }
    }

    function keepRecent(events) {
        events.forEach((e) => recent.push(e));
        if (recent.length > 1000) recent.splice(0, recent.length - 1000);
    }

    /** "5 changes by ana, 2 by ben · 3 messages" for others' events. */
    function summarizeAway(events, who) {
        const changes = {};
        let messages = 0, notes = 0, reveals = 0;
        events.forEach((e) => {
            if (e.user === who) return;
            if (e.type === 'edit') {
                const name = e.user || 'agreement';
                changes[name] = (changes[name] || 0) + 1;
            } else if (e.type === 'message') messages += 1;
            else if (e.type === 'discussion') notes += 1;
            else if (e.type === 'revealed') reveals += 1;
        });
        const parts = [];
        const people = Object.entries(changes).sort((a, b) => b[1] - a[1]);
        if (people.length) {
            parts.push(people.map(([u, n], i) => (i === 0
                ? `${n} change${n === 1 ? '' : 's'} by ${u}` : `${n} by ${u}`)).join(', '));
        }
        if (messages) parts.push(`${messages} message${messages === 1 ? '' : 's'}`);
        if (notes) parts.push(`${notes} comment${notes === 1 ? '' : 's'}`);
        if (reveals) parts.push(`${reveals} item${reveals === 1 ? '' : 's'} revealed`);
        return { count: events.filter((e) => e.user !== who && ['edit', 'message', 'discussion', 'revealed']
            .includes(e.type)).length, text: parts.join(' · ') };
    }

    function catchUp(since, prefix) {
        if (since == null || since >= state.cursor) return;
        const missed = recent.filter((e) => e.seq > since);
        const summary = summarizeAway(missed, cfg.me);
        if (!summary.count) return;
        showToast(`${prefix}: ${summary.text}.`, {
            action: 'Show activity',
            onAction: () => {
                setRail(true);
                selectTab('activity');
                const scope = el('collab-activity-scope');
                if (scope) { scope.value = 'all'; renderActivity(); }
            },
        });
    }

    let hiddenAt = null, cursorAtHide = 0;
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'hidden') {
            hiddenAt = Date.now();
            cursorAtHide = state.cursor;
        } else if (hiddenAt && Date.now() - hiddenAt > 60000) {
            const since = cursorAtHide;
            hiddenAt = null;
            // After the poll that the visibility change starts.
            setTimeout(() => catchUp(since, 'While you were away'), 1500);
        } else {
            hiddenAt = null;
        }
    });

    function readOffline() {
        try { return JSON.parse(localStorage.getItem(OFFLINE_KEY) || '[]'); } catch (e) { return []; }
    }

    function writeOffline(queue) {
        try {
            if (queue.length) localStorage.setItem(OFFLINE_KEY, JSON.stringify(queue));
            else localStorage.removeItem(OFFLINE_KEY);
        } catch (e) { /* storage off: the save is lost, as it would be anyway */ }
        renderOffline(queue);
    }

    // Set when the server stops knowing this member (a restart signs
    // everyone out; a leader can remove a member). The page then no longer
    // updates or saves, and says so instead of looking alive.
    let lockedOut = 0;

    function renderOffline(queue) {
        const banner = el('collab-offline');
        if (!banner) return;
        const text = banner.querySelector('[data-role="text"]');
        const link = banner.querySelector('[data-role="signin"]');
        const n = queue.length;
        const unsent = n === 1 ? 'one unsent change' : `${n} unsent changes`;
        if (lockedOut) {
            banner.hidden = false;
            text.textContent = lockedOut === 401
                ? `You are signed out, so this page no longer updates or saves.${n ? ` Your ${unsent} will be sent when you are back.` : ''}`
                : `You are no longer in this session, so this page no longer updates or saves.${n ? ` Your ${unsent} were not sent.` : ''}`;
            if (link) link.hidden = lockedOut !== 401;
            return;
        }
        if (link) link.hidden = true;
        banner.hidden = !n;
        text.textContent = n === 1
            ? 'Offline: one unsent change will be sent when you reconnect.'
            : `Offline: ${n} unsent changes will be sent when you reconnect.`;
    }

    function signedOut(status) {
        lockedOut = status;
        renderOffline(readOffline());
    }

    /**
     * A save the network dropped. Kept per item (the latest save carries all
     * of the page's answer) and sent again later; it still names the revision
     * it was made on, so the server merges it like any late save.
     */
    function queueOffline(input, init) {
        if (!init || typeof init.body !== 'string') return;
        let body;
        try { body = JSON.parse(init.body); } catch (e) { return; }
        if (!body || body.instance_id == null) return;
        const url = typeof input === 'string' ? input : input.url;
        const queue = readOffline().filter((q) => q.instance_id !== String(body.instance_id));
        queue.push({ url: url, instance_id: String(body.instance_id), body: init.body, at: Date.now() });
        writeOffline(queue);
    }

    let flushing = false;
    async function flushOffline() {
        if (flushing) return;
        const queue = readOffline();
        renderOffline(queue);
        if (!queue.length) return;
        flushing = true;
        try {
            for (const item of queue) {
                const r = await nativeFetch(item.url, {
                    method: 'POST', credentials: 'same-origin',
                    headers: { 'Content-Type': 'application/json' }, body: item.body,
                });
                if (r.status === 401 || r.status === 403) {
                    // Kept: sent once this member is back in the session.
                    stopPolling();
                    signedOut(r.status);
                    break;
                }
                writeOffline(readOffline().filter((q) => !(q.instance_id === item.instance_id && q.at === item.at)));
                if (!r.ok) {
                    const msg = (await r.json().catch(() => ({}))).message || `HTTP ${r.status}`;
                    showToast(`A change made while offline was not saved: ${msg}`);
                } else if (item.instance_id === String(cfg.instance_id)) {
                    poll();
                }
            }
        } catch (e) {
            /* still offline */
        } finally {
            flushing = false;
        }
    }
    window.addEventListener('online', flushOffline);

    // ------------------------------------------------------------------
    // Mentions

    function mentionsIn(text, members) {
        const byLower = {};
        (members || []).forEach((m) => { byLower[String(m).toLowerCase()] = m; });
        const found = [];
        String(text || '').replace(/(^|[^\w@])@([\w.\-]+)/g, (all, pre, raw) => {
            for (const candidate of [raw, raw.replace(/[.\-]+$/, '')]) {
                const name = byLower[candidate.toLowerCase()];
                if (name && !found.includes(name)) { found.push(name); break; }
            }
            return all;
        });
        return found;
    }

    function wireExtras() {
        const done = el('collab-blind-done');
        if (done) done.addEventListener('click', finishBlind);
        const reveal = el('collab-reveal');
        if (reveal) reveal.addEventListener('click', () => post('/reveal', { instance_id: cfg.instance_id })
            .then(poll, (err) => showToast(err.message)));
        const sign = el('collab-signoff');
        if (sign) sign.addEventListener('click', toggleReady);
        const toggle = el('collab-revealed-toggle');
        if (toggle) toggle.addEventListener('click', () => setRevealHidden(!el('collab-revealed-body').hidden));
        const replay = el('collab-replay-link');
        if (replay) replay.href = `${base}/collab/s/${encodeURIComponent(cfg.sid)}/replay?instance_id=${encodeURIComponent(cfg.instance_id)}`;

        const syncWrap = el('collab-sync-wrap');
        const sync = el('collab-sync');
        if (sync) {
            sync.checked = syncOn();
            sync.addEventListener('change', () => {
                try { sessionStorage.setItem('potato-collab-sync', sync.checked ? '1' : '0'); } catch (e) { /* off */ }
                if (sync.checked) { viewPausedUntil = 0; lastViewAt = 0; followView(); }
            });
        }
        if (syncWrap) syncWrap.hidden = !cfg.sync_view;

        fillPollForm();
        const form = el('collab-poll-form');
        if (form) form.addEventListener('submit', (e) => {
            e.preventDefault();
            const schema = el('collab-poll-schema').value;
            if (schema) { startPoll({ schema: schema }); return; }
            const options = el('collab-poll-options').value.split(',').map((o) => o.trim()).filter(Boolean);
            startPoll({ question: el('collab-poll-question').value.trim(), options: options });
        });
        const pollStart = el('collab-poll-start');
        if (pollStart && cfg.role === 'observer') pollStart.hidden = true;

        document.addEventListener('click', (e) => {
            const vote = e.target.closest('[data-vote]');
            if (vote) {
                const current = ((state.session && state.session.polls) || [])
                    .find((p) => p.open && p.instance_id === cfg.instance_id);
                if (current) post(`/poll/${encodeURIComponent(current.poll_id)}/vote`, { option: vote.dataset.vote })
                    .then(poll, (err) => showToast(err.message));
            }
            const close = e.target.closest('[data-poll-close]');
            if (close) post(`/poll/${encodeURIComponent(close.dataset.pollClose)}/close`, { apply: !!close.dataset.apply })
                .then(poll, (err) => showToast(err.message));
            const dismiss = e.target.closest('[data-poll-dismiss]');
            if (dismiss) { dismissedPolls.add(dismiss.dataset.pollDismiss); pollSignature = ''; renderPoll(); }
            const ask = e.target.closest('[data-poll-schema]');
            if (ask) startPoll({ schema: ask.dataset.pollSchema });
        });
    }

    // Exposed for tests and for widgets that want to know.
    window.potatoCollabClient = {
        state: state, isOwnedPath: isOwnedPath, pathOf: pathOf, handleEvents: handleEvents,
        applyKeys: applyKeys, hasWidget: hasWidget, onSaveResult: onSaveResult, consume: consume,
        mentionsIn: mentionsIn, summarizeAway: summarizeAway, offlineQueue: readOffline,
        flushOffline: flushOffline, applyView: applyView, currentView: currentView,
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }
})();

/*
 * Codebook tray + on-the-fly add + revision provenance.
 *
 * Self-gating: probes GET /api/codebook. 200 => enabled (reveal the
 * toggle); 401/503 => stay hidden. `can_add` decides whether the
 * composer is shown (codebook_mode extensible/open or privileged).
 *
 * Durability: the annotation template is built once at server start, so
 * a code added mid-session is NOT in the reloaded form. We reconcile
 * client-side on every annotation page load — append any codebook label
 * missing from each codebook-backed form. To avoid re-downloading the
 * whole codebook every navigation, we poll the cheap /version endpoint
 * and only re-fetch the full codebook (cached in sessionStorage) when
 * the revision has moved.
 *
 * Provenance: each annotation is stamped server-side with the codebook
 * revision in effect. On revisit, an instance labeled under an older
 * revision shows a dismissible banner, and the tray lists a review
 * worklist of the annotator's stale instances with jump-to.
 */
(function () {
    "use strict";

    var API = "/api/codebook";
    var dismissed = {};          // instance_id -> true (banner dismissed)

    function el(id) { return document.getElementById(id); }

    function esc(s) {
        var d = document.createElement("div");
        d.textContent = s == null ? "" : String(s);
        return d.innerHTML;
    }

    function project() {
        return (window.config && window.config.annotation_task_name)
            || "default";
    }
    function cacheKey() { return "cb_cache:" + project(); }

    function readCache() {
        try { return JSON.parse(sessionStorage.getItem(cacheKey())); }
        catch (e) { return null; }
    }
    function writeCache(data) {
        try {
            sessionStorage.setItem(cacheKey(), JSON.stringify({
                revision: data.revision, labels: data.labels,
                tree: data.tree, schemes: data.schemes,
                mode: data.mode, can_add: data.can_add,
            }));
        } catch (e) { /* sessionStorage full/disabled — fall back to net */ }
    }

    // ---- tray rendering --------------------------------------------------

    function renderTree(nodes) {
        if (!nodes || !nodes.length) return "";
        return nodes.map(function (n) {
            var dot = n.color
                ? '<span class="cb-dot" style="background:'
                  + esc(n.color) + '"></span>'
                : "";
            return '<li class="cb-node">'
                + '<div class="cb-node-row">' + dot
                + '<span class="cb-name">' + esc(n.name) + "</span></div>"
                + (n.children && n.children.length
                    ? '<ul class="cb-children">'
                      + renderTree(n.children) + "</ul>"
                    : "")
                + "</li>";
        }).join("");
    }

    var MODE_HINT = {
        open: "You can add and organize codes.",
        extensible: "You can add new codes.",
    };

    function renderTray(data) {
        var box = el("cb-tree");
        if (box) {
            var tree = (data && data.tree) || [];
            box.innerHTML = tree.length
                ? '<ul class="cb-root">' + renderTree(tree) + "</ul>"
                : '<div class="cb-empty">No codes yet.</div>';
        }
        var composer = el("cb-composer");
        if (composer) composer.hidden = !(data && data.can_add);
        var hint = el("cb-mode-hint");
        if (hint && data) hint.textContent = MODE_HINT[data.mode] || "";
    }

    // ---- form reconciliation (append missing codebook options) ----------

    function slug(s) {
        return String(s).replace(/[^a-zA-Z0-9_-]/g, "_");
    }

    function optionValues(form) {
        var vals = {};
        form.querySelectorAll(
            "input.annotation-input, input.shadcn-span-checkbox"
        ).forEach(function (i) { vals[i.value] = true; });
        return vals;
    }

    // Span schemes (annotation_type: span, codebook: true) render a
    // different option shape (.shadcn-span-option / .shadcn-span-checkbox,
    // no .annotation-input, an inline changeSpanLabel onclick). The label
    // palette must still gain runtime codes so they are usable as span
    // labels; span *persistence* itself is overlay-based and independent
    // of the palette.
    function reconcileSpanForm(form, tmpl, labels) {
        var schema = form.getAttribute("data-schema-name") || form.id;
        var have = optionValues(form);
        var parent = tmpl.parentElement;
        var tInput = tmpl.querySelector("input");
        var targetField = tInput
            ? (tInput.getAttribute("data-target-field") || "") : "";

        labels.forEach(function (name) {
            if (have[name]) return;          // idempotent
            var node = tmpl.cloneNode(true);
            var input = node.querySelector("input");
            var label = node.querySelector("label");
            if (!input || !label) return;
            var newId = schema + "__cb__" + slug(name);
            input.value = name;
            input.id = newId;
            input.checked = false;
            input.removeAttribute("data-key");
            // label/title carry the code name; color is hash-derived in
            // SpanManager (getSpanColor) so '' here is correct.
            input.setAttribute(
                "onclick",
                "onlyOne(this); changeSpanLabel(this, "
                + JSON.stringify(schema) + ", " + JSON.stringify(name)
                + ", " + JSON.stringify(name) + ", '', "
                + JSON.stringify(targetField) + ");");
            label.setAttribute("for", newId);
            var swatch = label.querySelector("span");
            if (swatch) {
                swatch.textContent = name;
                swatch.style.backgroundColor = "";   // no borrowed color
            } else {
                label.textContent = name;
            }
            parent.appendChild(node);
            have[name] = true;
        });
    }

    function reconcileForm(form, labels) {
        var span = form.querySelector(".shadcn-span-option");
        if (span) return reconcileSpanForm(form, span, labels);
        var radio = form.querySelector(".shadcn-radio-option");
        var multi = form.querySelector(".shadcn-multiselect-item");
        var tmpl = radio || multi;
        if (!tmpl) return;            // unsupported scheme type — skip
        var isCheckbox = !!multi;
        var schema = form.getAttribute("data-schema-name") || form.id;
        var have = optionValues(form);
        var parent = tmpl.parentElement;

        labels.forEach(function (name) {
            if (have[name]) return;  // already an option (idempotent)
            var node = tmpl.cloneNode(true);
            var input = node.querySelector("input");
            var label = node.querySelector("label");
            if (!input || !label) return;
            var newId = schema + "__cb__" + slug(name);
            input.value = name;
            input.id = newId;
            input.checked = false;
            input.removeAttribute("data-key");
            input.setAttribute("label_name", newId);
            if (isCheckbox) input.setAttribute("name", schema + ":::" + name);
            label.setAttribute("for", newId);
            label.textContent = name;   // drops any keybinding badge
            parent.appendChild(node);
            have[name] = true;
        });
    }

    function selectedValues(labelAnnos, schema) {
        // get_label_annotations returns {schema: <list|value>}; be
        // defensive about the item shape (string or {label/name/value}).
        var raw = labelAnnos && labelAnnos[schema];
        if (raw == null) return {};
        var arr = Array.isArray(raw) ? raw : [raw];
        var out = {};
        arr.forEach(function (it) {
            if (it == null) return;
            if (typeof it === "string" || typeof it === "number") {
                out[String(it)] = true;
            } else if (typeof it === "object") {
                var v = it.label != null ? it.label
                    : (it.name != null ? it.name : it.value);
                if (v != null) out[String(v)] = true;
            }
        });
        return out;
    }

    function restoreRuntimeSelections(schemes, instanceId) {
        if (!instanceId) return;
        fetch("/get_annotations?instance_id="
              + encodeURIComponent(instanceId))
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (data) {
                if (!data || !data.label_annotations) return;
                schemes.forEach(function (schema) {
                    var form = document.querySelector(
                        'form[data-schema-name="' + cssEsc(schema) + '"]')
                        || document.getElementById(schema);
                    if (!form) return;
                    // Saved annotations come back keyed by the Label
                    // *name*, which equals the input's `label_name`
                    // (that is what saveAnnotations sends). Match on
                    // label_name, not value, so a code name with odd
                    // characters still round-trips.
                    var sel = selectedValues(
                        data.label_annotations, schema);
                    form.querySelectorAll("input.annotation-input")
                        .forEach(function (input) {
                            var key = input.getAttribute("label_name");
                            if (key && sel[key] && !input.checked) {
                                input.checked = true;
                                input.setAttribute(
                                    "data-server-set", "true");
                                if (typeof registerAnnotation
                                        === "function") {
                                    try { registerAnnotation(input); }
                                    catch (e) { /* non-fatal */ }
                                }
                            }
                        });
                });
            })
            .catch(function () { /* restore is best-effort */ });
    }

    function cssEsc(s) {
        return String(s).replace(/["\\]/g, "\\$&");
    }

    function reconcileForms(data, instanceId) {
        var schemes = (data && data.schemes) || [];
        var labels = (data && data.labels) || [];
        if (!schemes.length || !labels.length) return;
        schemes.forEach(function (schema) {
            var form = document.querySelector(
                'form[data-schema-name="' + cssEsc(schema) + '"]')
                || document.getElementById(schema);
            if (form) reconcileForm(form, labels);
        });
        restoreRuntimeSelections(schemes, instanceId);
    }

    // ---- provenance banner + review worklist ----------------------------

    function instanceId() {
        var e = el("instance_id");
        return e ? (e.value || e.textContent || "").trim() : "";
    }

    function renderBanner(p) {
        var bar = el("cb-stale-banner");
        if (!bar) return;
        if (!p || !p.stale || dismissed[p.instance_id]) {
            bar.hidden = true;
            return;
        }
        var added = p.codes_added_since || [];
        var msg = added.length
            ? added.length + " code" + (added.length > 1 ? "s" : "")
              + " added since you labeled this: " + added.join(", ")
            : "The codebook changed since you labeled this "
              + "(renamed / recolored / reorganized).";
        bar.innerHTML =
            '<span class="cb-stale-msg">' + esc(msg) + "</span>"
            + '<button type="button" id="cb-stale-dismiss" '
            + 'class="cb-stale-x" aria-label="Dismiss">&times;</button>';
        bar.hidden = false;
        var x = el("cb-stale-dismiss");
        if (x) x.addEventListener("click", function () {
            dismissed[p.instance_id] = true;
            bar.hidden = true;
        });
    }

    function renderWorklist(items) {
        var box = el("cb-worklist");
        var head = el("cb-worklist-head");
        if (!box) return;
        items = items || [];
        if (head) head.textContent = "Review (" + items.length + ")";
        if (!items.length) {
            box.innerHTML =
                '<div class="cb-empty">Nothing to review.</div>';
            return;
        }
        box.innerHTML = items.map(function (it) {
            var added = (it.codes_added_since || []);
            var sub = added.length
                ? esc(added.join(", "))
                : "codebook changed";
            var btn = it.index == null ? ""
                : '<button type="button" class="cb-go" data-idx="'
                  + it.index + '">Go</button>';
            return '<div class="cb-wl-item">'
                + '<div class="cb-wl-id">' + esc(it.instance_id)
                + "</div>"
                + '<div class="cb-wl-sub">' + sub + "</div>"
                + btn + "</div>";
        }).join("");
        box.querySelectorAll(".cb-go").forEach(function (b) {
            b.addEventListener("click", function () {
                var idx = parseInt(b.getAttribute("data-idx"), 10);
                if (!isNaN(idx)
                        && typeof navigateToInstance === "function") {
                    navigateToInstance(idx);
                }
            });
        });
    }

    function refreshProvenance() {
        var iid = instanceId();
        if (iid) {
            fetch(API + "/provenance?instance_id="
                  + encodeURIComponent(iid))
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(renderBanner)
                .catch(function () { /* banner is best-effort */ });
        }
        fetch(API + "/stale")
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                renderWorklist(d && d.stale);
            })
            .catch(function () { /* worklist is best-effort */ });
    }

    // ---- load orchestration ---------------------------------------------

    function fetchFull() {
        return fetch(API).then(function (r) {
            return r.ok ? r.json() : null;
        }).then(function (data) {
            if (data) { writeCache(data); }
            return data;
        });
    }

    // Reconcile + restore off the sessionStorage cache *immediately*
    // (no network on the critical path), then poll the cheap /version
    // in the background and, only if the revision moved, full-fetch and
    // reconcile again (idempotent). This keeps the runtime-code restore
    // deterministic after a full-reload navigation instead of racing a
    // multi-round-trip chain.
    function syncCodebook(instanceId) {
        var cache = readCache();
        if (cache) {
            renderTray(cache);
            reconcileForms(cache, instanceId);  // each load = stale tmpl
        }
        return fetch(API + "/version")
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (v) {
                if (v && cache && cache.revision === v.revision) {
                    return cache;            // cache fresh — done
                }
                return fetchFull().then(function (data) {
                    if (data) {
                        renderTray(data);
                        reconcileForms(data, instanceId);
                    }
                    return data;
                });
            })
            .catch(function () { return cache || null; });
    }

    function onInstance() {
        if (!el("cb-panel")) return;
        syncCodebook(instanceId());
        refreshProvenance();
    }

    // ---- composer (add a code) ------------------------------------------

    function addCode() {
        var input = el("cb-new-name");
        var name = (input && input.value || "").trim();
        var err = el("cb-error");
        if (err) { err.hidden = true; err.textContent = ""; }
        if (!name) { if (input) input.focus(); return; }
        var btn = el("cb-add-btn");
        if (btn) btn.disabled = true;
        fetch(API, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: name }),
        }).then(function (r) {
            return r.json().then(function (b) {
                return { ok: r.ok, body: b };
            });
        }).then(function (res) {
            if (btn) btn.disabled = false;
            if (!res.ok) {
                if (err) {
                    err.textContent = res.body && res.body.error
                        ? res.body.error : "Could not add code.";
                    err.hidden = false;
                }
                return;
            }
            if (input) input.value = "";
            // Force a full refresh + immediate in-place reconcile so the
            // new code is usable on the current instance without reload.
            fetchFull().then(function (data) {
                if (data) {
                    renderTray(data);
                    reconcileForms(data, instanceId());
                }
                refreshProvenance();
            });
        }).catch(function () {
            if (btn) btn.disabled = false;
            if (err) {
                err.textContent = "Could not add code.";
                err.hidden = false;
            }
        });
    }

    // ---- in-vivo coding (D): select text -> key -> code from selection --
    // Reuses the (B) create path + the existing span create/save/overlay
    // pipeline: capture the selection Range, create (or reuse) the code,
    // reconcile the palette, then replay the Range through SpanManager so
    // zero span logic is duplicated here.

    var INVIVO_CAP = 60;
    var iv = null;        // popover root (built lazily)
    var ivState = null;   // { range, schema, field, chosen }

    // Mirrors potato/codebook/similar.py derive_code_name — keep in sync.
    function deriveName(text) {
        var s = String(text || "").replace(/\s+/g, " ").trim();
        if (s.length <= INVIVO_CAP) return s;
        var head = s.slice(0, INVIVO_CAP).replace(/\s\S*$/, "");
        return (head || s.slice(0, INVIVO_CAP)).trim();
    }

    function invivoKey() {
        var c = readCache();
        var k = c && c.invivo_key;
        return (k || "i").toString().slice(0, 1).toLowerCase();
    }

    function codebookSpanForm() {
        var forms = document.querySelectorAll("form.annotation-form.span");
        for (var i = 0; i < forms.length; i++) {
            if (forms[i].querySelector(".shadcn-span-option")) {
                return forms[i];
            }
        }
        return null;
    }

    function activeSelectionInInstance() {
        var sel = window.getSelection && window.getSelection();
        if (!sel || !sel.rangeCount || sel.isCollapsed) return null;
        if (!sel.toString().trim()) return null;
        var node = sel.getRangeAt(0).startContainer;
        var elx = node.nodeType === 3 ? node.parentElement : node;
        if (!elx || !elx.closest) return null;
        var host = elx.closest(
            '[id^="text-content-"], #instance-text, #text-content');
        return host ? sel : null;
    }

    function fieldOfSelection(sel) {
        var node = sel.getRangeAt(0).startContainer;
        var elx = node.nodeType === 3 ? node.parentElement : node;
        var host = elx && elx.closest
            ? elx.closest('[id^="text-content-"]') : null;
        return host ? host.id.replace("text-content-", "") : "";
    }

    function buildPopover() {
        if (iv) return iv;
        iv = document.createElement("div");
        iv.id = "cb-invivo";
        iv.className = "cb-invivo";
        iv.setAttribute("role", "dialog");
        iv.setAttribute("aria-label",
            "Create a code from the selected text");
        iv.hidden = true;
        iv.innerHTML =
            '<div class="cb-iv-quote" id="cb-iv-quote"></div>' +
            '<input id="cb-iv-name" class="cb-iv-input" type="text" ' +
                'autocomplete="off" spellcheck="false" ' +
                'aria-label="New code name" />' +
            '<div id="cb-iv-sim" class="cb-iv-sim" hidden></div>' +
            '<div id="cb-iv-err" class="cb-error" hidden ' +
                'role="alert"></div>' +
            '<div class="cb-iv-actions">' +
                '<button type="button" id="cb-iv-cancel" ' +
                    'class="cb-iv-cancel">Cancel</button>' +
                '<button type="button" id="cb-iv-go" ' +
                    'class="cb-primary">Create &amp; code</button>' +
            '</div>';
        document.body.appendChild(iv);
        el("cb-iv-cancel").addEventListener("click", closeInvivo);
        el("cb-iv-go").addEventListener("click", commitInvivo);
        var nm = el("cb-iv-name");
        nm.addEventListener("keydown", function (e) {
            if (e.key === "Enter") {
                e.preventDefault(); commitInvivo();
            } else if (e.key === "Escape") {
                e.preventDefault(); closeInvivo();
            }
        });
        var simT;
        nm.addEventListener("input", function () {
            if (ivState) ivState.chosen = null;
            updateGoLabel();
            clearTimeout(simT);
            simT = setTimeout(fetchSimilar, 220);
        });
        return iv;
    }

    function truncate(s, n) {
        s = String(s || "").replace(/\s+/g, " ").trim();
        return s.length > n ? s.slice(0, n - 1).trim() + "…" : s;
    }

    // Reflect what the primary action will actually do so "Create" never
    // lies when the name resolves to an existing code.
    function updateGoLabel() {
        var go = el("cb-iv-go");
        if (!go || !ivState) return;
        var nm = el("cb-iv-name");
        var name = (nm && nm.value || "").trim().toLowerCase();
        var reuse = !!ivState.chosen;
        if (!reuse && name) {
            var cache = readCache();
            var labels = (cache && cache.labels) || [];
            reuse = labels.some(function (l) {
                return String(l).trim().toLowerCase() === name;
            });
        }
        go.textContent = reuse ? "Apply code" : "Create & code";
    }

    function positionPopover(rect) {
        var pad = 8, w = 320;
        var de = document.documentElement;
        var left = Math.max(pad, Math.min(
            rect.left + window.scrollX,
            window.scrollX + de.clientWidth - w - pad));
        // Flip above the selection if it would overflow the fold.
        var h = iv.offsetHeight || 0;
        var below = rect.bottom + pad + h <= de.clientHeight;
        var top = below
            ? rect.bottom + window.scrollY + pad
            : Math.max(pad + window.scrollY,
                       rect.top + window.scrollY - pad - h);
        iv.style.top = top + "px";
        iv.style.left = left + "px";
    }

    function closeInvivo() {
        if (iv) iv.hidden = true;
        ivState = null;
    }

    function showIvErr(msg) {
        var e = el("cb-iv-err");
        if (e) { e.textContent = msg; e.hidden = false; }
    }

    function renderSimilar(matches) {
        var box = el("cb-iv-sim");
        if (!box) return;
        if (!matches || !matches.length) {
            box.hidden = true; box.innerHTML = ""; return;
        }
        box.hidden = false;
        box.innerHTML = '<span class="cb-iv-sim-label">Similar existing '
            + 'code' + (matches.length > 1 ? "s" : "")
            + ' — reuse instead?</span>';
        matches.forEach(function (m) {
            var b = document.createElement("button");
            b.type = "button";
            b.className = "cb-iv-chip";
            b.textContent = m;
            b.addEventListener("click", function () {
                var nm = el("cb-iv-name");
                nm.value = m;
                if (ivState) ivState.chosen = m;
                box.querySelectorAll(".cb-iv-chip").forEach(
                    function (c) {
                        c.classList.toggle("cb-iv-chip-on", c === b);
                    });
                updateGoLabel();
                nm.focus();
            });
            box.appendChild(b);
        });
    }

    function fetchSimilar() {
        var nm = el("cb-iv-name");
        var q = (nm && nm.value || "").trim();
        if (!q) { renderSimilar([]); return; }
        fetch(API + "/similar?name=" + encodeURIComponent(q))
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) { renderSimilar(d && d.matches); })
            .catch(function () { /* suggestion is best-effort */ });
    }

    function openInvivo(sel, form) {
        buildPopover();
        var range = sel.getRangeAt(0).cloneRange();
        var rect = range.getBoundingClientRect();
        var raw = sel.toString();
        ivState = {
            range: range,
            schema: form.getAttribute("data-schema-name") || form.id,
            field: fieldOfSelection(sel),
            chosen: null,
        };
        // Quote shows the *selected text* for context; the input holds
        // the editable derived code name.
        el("cb-iv-quote").textContent = "“" + truncate(raw, 140) + "”";
        var nm = el("cb-iv-name");
        nm.value = deriveName(raw);
        el("cb-iv-err").hidden = true;
        renderSimilar([]);
        updateGoLabel();
        iv.hidden = false;
        positionPopover(rect);
        nm.focus();
        nm.select();
        fetchSimilar();
    }

    function applySpan(name) {
        var sm = window.spanManager;
        if (!sm || !ivState) return;
        try {
            sm.selectLabel(name, ivState.schema, ivState.field);
            var s = window.getSelection();
            s.removeAllRanges();
            s.addRange(ivState.range);
            sm.handleTextSelection({});
            s.removeAllRanges();
        } catch (e) { /* code is created; span apply is best-effort */ }
    }

    function afterCode(name) {
        fetchFull().then(function (data) {
            if (data) {
                renderTray(data);
                reconcileForms(data, instanceId());
            }
            applySpan(name);
            refreshProvenance();
            closeInvivo();
        });
    }

    function commitInvivo() {
        if (!ivState) return;
        var nm = el("cb-iv-name");
        var name = (nm && nm.value || "").trim();
        var errEl = el("cb-iv-err");
        if (errEl) errEl.hidden = true;
        if (!name) { if (nm) nm.focus(); return; }
        // Reuse an existing code? (chip-picked, or exact normalized hit)
        var existing = ivState.chosen;
        if (!existing) {
            var cache = readCache();
            var labels = (cache && cache.labels) || [];
            for (var i = 0; i < labels.length; i++) {
                if (String(labels[i]).trim().toLowerCase()
                        === name.toLowerCase()) {
                    existing = labels[i]; break;
                }
            }
        }
        if (existing) { afterCode(existing); return; }
        var go = el("cb-iv-go");
        if (go) go.disabled = true;
        fetch(API, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: name }),
        }).then(function (r) {
            return r.json().then(function (b) {
                return { ok: r.ok, status: r.status, body: b };
            });
        }).then(function (res) {
            if (go) go.disabled = false;
            if (!res.ok) {
                if (res.status === 409) { afterCode(name); return; }
                showIvErr(res.body && res.body.error
                    ? res.body.error : "Could not add code.");
                return;
            }
            afterCode(name);
        }).catch(function () {
            if (go) go.disabled = false;
            showIvErr("Could not add code.");
        });
    }

    function onGlobalKeydown(e) {
        if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey) {
            return;
        }
        if (iv && !iv.hidden) return;   // popover owns its own keys
        var t = e.target, tag = t && t.tagName;
        if (tag === "INPUT" || tag === "TEXTAREA"
            || (t && t.isContentEditable)) return;
        if ((e.key || "").toLowerCase() !== invivoKey()) return;
        var form = codebookSpanForm();
        if (!form) return;
        var sel = activeSelectionInInstance();
        if (!sel) return;
        e.preventDefault();
        openInvivo(sel, form);
    }

    function closePanel() {
        var panel = el("cb-panel");
        var toggle = el("cb-panel-toggle");
        if (panel) panel.hidden = true;
        if (toggle) { toggle.hidden = false; toggle.focus(); }
    }

    function wire() {
        var toggle = el("cb-panel-toggle");
        var panel = el("cb-panel");
        var close = el("cb-panel-close");
        if (toggle && panel) {
            toggle.addEventListener("click", function () {
                panel.hidden = false;
                toggle.hidden = true;
                onInstance();
                var n = el("cb-new-name");
                if (n && !el("cb-composer").hidden) n.focus();
            });
        }
        if (close) close.addEventListener("click", closePanel);
        if (panel) {
            panel.addEventListener("keydown", function (e) {
                if (e.key === "Escape") {
                    e.preventDefault(); closePanel();
                }
            });
        }
        // In-vivo coding: global key, active whenever a codebook span
        // scheme exists (wire() runs only when the codebook is enabled).
        document.addEventListener("keydown", onGlobalKeydown);

        var add = el("cb-add-btn");
        if (add) add.addEventListener("click", addCode);
        var input = el("cb-new-name");
        if (input) {
            input.addEventListener("keydown", function (e) {
                if (e.key === "Enter") {
                    e.preventDefault(); addCode();
                }
            });
        }
    }

    // Hook annotation.js calls on every instance load (after a full
    // navigation reload too) so reconcile + banner stay correct.
    window.CodebookPanel = { onInstance: onInstance };

    function init() {
        if (!window.config || !window.config.is_annotation_page) return;
        if (!el("cb-panel")) return;
        fetch(API).then(function (r) {
            if (r.status === 200) {
                var t = el("cb-panel-toggle");
                if (t) t.hidden = false;
                wire();
                return r.json();
            }
            return null;
        }).then(function (data) {
            if (!data) return;
            writeCache(data);
            renderTray(data);
            reconcileForms(data, instanceId());
            refreshProvenance();
        }).catch(function () { /* leave hidden */ });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();

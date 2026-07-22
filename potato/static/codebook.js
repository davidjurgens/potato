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
                can_edit: data.can_edit,
            }));
        } catch (e) { /* sessionStorage full/disabled — fall back to net */ }
    }

    // ---- tray rendering --------------------------------------------------

    function renderTree(nodes, canEdit) {
        if (!nodes || !nodes.length) return "";
        return nodes.map(function (n) {
            var dot = n.color
                ? '<span class="cb-dot" style="background:'
                  + esc(n.color) + '"></span>'
                : "";
            var editBtn = canEdit
                ? '<button type="button" class="cb-detail-toggle" '
                  + 'data-id="' + esc(n.id) + '" '
                  + 'aria-label="Edit ' + esc(n.name) + '" '
                  + 'aria-expanded="false">Edit</button>'
                : "";
            return '<li class="cb-node" data-id="' + esc(n.id) + '">'
                + '<div class="cb-node-row">' + dot
                + '<span class="cb-name">' + esc(n.name) + "</span>"
                + editBtn + "</div>"
                + (canEdit
                    ? '<div class="cb-detail" id="cb-detail-'
                      + esc(n.id) + '" hidden></div>'
                    : "")
                + (n.children && n.children.length
                    ? '<ul class="cb-children">'
                      + renderTree(n.children, canEdit) + "</ul>"
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
            var canEdit = !!(data && data.can_edit);
            box.innerHTML = tree.length
                ? '<ul class="cb-root">' + renderTree(tree, canEdit)
                  + "</ul>"
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

    var staleDismissBound = false;
    var staleInstance = null;

    function renderBanner(p) {
        var bar = el("cb-stale-banner");
        var msgEl = el("cb-stale-msg");
        if (!bar || !msgEl) return;
        // Bind the persistent dismiss control exactly once — the banner
        // is stable structure (the message <span> is the live region),
        // never re-injected, so the control is never re-announced.
        if (!staleDismissBound) {
            var x = el("cb-stale-dismiss");
            if (x) x.addEventListener("click", function () {
                if (staleInstance) dismissed[staleInstance] = true;
                bar.hidden = true;
            });
            staleDismissBound = true;
        }
        if (!p || !p.stale || dismissed[p.instance_id]) {
            bar.hidden = true;
            return;
        }
        var added = p.codes_added_since || [];
        staleInstance = p.instance_id;
        msgEl.textContent = added.length
            ? added.length + " code" + (added.length > 1 ? "s" : "")
              + " added since you labeled this: " + added.join(", ")
            : "The codebook changed since you labeled this "
              + "(renamed / recolored / reorganized).";
        bar.hidden = false;
    }

    function renderWorklist(items) {
        var box = el("cb-worklist");
        var head = el("cb-worklist-head");
        var section = el("cb-worklist-section");
        if (!box) return;
        items = items || [];
        if (head) head.textContent = "Review (" + items.length + ")";
        // The empty worklist is the common case — collapse the whole
        // section so it adds no resting chrome to the tray.
        if (section) section.hidden = !items.length;
        if (!items.length) {
            box.innerHTML =
                '<div class="cb-empty">Nothing to review.</div>';
            return;
        }
        box.innerHTML = '<ul class="cb-worklist-list">'
            + items.map(function (it) {
            var added = (it.codes_added_since || []);
            var sub = added.length
                ? esc(added.join(", "))
                : "codebook changed";
            var btn = (it.index == null && !it.instance_id) ? ""
                : '<button type="button" class="cb-go"'
                  + (it.index == null ? ""
                      : ' data-idx="' + it.index + '"')
                  + ' data-iid="' + esc(it.instance_id) + '">Go</button>';
            return '<li class="cb-wl-item">'
                + '<div class="cb-wl-id">' + esc(it.instance_id)
                + "</div>"
                + '<div class="cb-wl-sub">' + sub + "</div>"
                + btn + "</li>";
        }).join("") + "</ul>";
        box.querySelectorAll(".cb-go").forEach(function (b) {
            b.addEventListener("click", function () {
                var idx = parseInt(b.getAttribute("data-idx"), 10);
                if (!isNaN(idx)
                        && typeof navigateToInstance === "function") {
                    navigateToInstance(idx);
                    return;
                }
                // Solo mode has no AJAX navigateToInstance — fall back to
                // a full-page jump by instance id.
                var iid = b.getAttribute("data-iid");
                var base = window.config && window.config.solo_annotate_url;
                if (iid && base) {
                    window.location.href = base + "?instance_id="
                        + encodeURIComponent(iid);
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
        refreshAdmin();
    }

    // ---- admin curation (Phase 2 C): merge / split / proposals ----------
    // Admin status is probed once via the gated endpoint (200 -> show
    // the section, 403 -> stay hidden) — same self-gating pattern as the
    // codebook toggle itself.

    var ADMIN_API = API + "/admin";
    var adminProbed = false, adminOK = false;

    function flatCodes() {
        var c = readCache();
        var tree = (c && c.tree) || [];
        var out = [];
        (function walk(nodes, depth) {
            nodes.forEach(function (n) {
                out.push({ id: n.id,
                           name: (depth ? "— " : "") + n.name });
                if (n.children) walk(n.children, depth + 1);
            });
        })(tree, 0);
        return out;
    }

    function fillCodeSelect(sel, codes, placeholder) {
        if (!sel) return;
        var cur = sel.value;
        sel.innerHTML = '<option value="">' + esc(placeholder)
            + "</option>"
            + codes.map(function (c) {
                return '<option value="' + esc(c.id) + '">'
                    + esc(c.name) + "</option>";
            }).join("");
        if (cur) sel.value = cur;
    }

    function codeNameMap() {
        var c = readCache();
        var map = {};
        (function walk(nodes) {
            (nodes || []).forEach(function (n) {
                map[n.id] = n.name;
                if (n.children) walk(n.children);
            });
        })((c && c.tree) || []);
        return map;
    }

    function codeName(id) {
        if (!id) return "?";
        var nm = codeNameMap()[id];
        return nm != null ? nm : String(id).slice(0, 8);
    }

    // Human, reviewable sentence — an admin must understand what they
    // are confirming, not decode uuids.
    function describeProposal(p) {
        var q = function (s) { return "«" + esc(s) + "»"; };
        var pay = p.payload || {};
        switch (p.op) {
        case "merge":
            return "Merge " + q(codeName(pay.src_id)) + " into "
                + q(codeName(pay.dst_id));
        case "split":
            var dest = pay.new_name
                ? " → " + q(pay.new_name)
                : (pay.target_id
                    ? " → " + q(codeName(pay.target_id)) : "");
            return "Split " + q(codeName(pay.src_id)) + " by "
                + esc(pay.annotator || "?") + dest;
        case "rename":
            return "Rename " + q(codeName(pay.code_id)) + " → "
                + q(pay.new_name || "?");
        case "recolor":
            return "Recolour " + q(codeName(pay.code_id));
        case "move":
            return "Move " + q(codeName(pay.code_id));
        case "delete":
            return "Delete " + q(codeName(pay.code_id));
        case "update_fields":
            var fields = Object.keys(pay).filter(function (k) {
                return k !== "code_id" && k !== "rationale";
            });
            return "Update " + q(codeName(pay.code_id)) + " ("
                + esc(fields.join(", ")) + ")"
                + (pay.rationale ? " — " + esc(pay.rationale) : "");
        default:
            return esc(p.op);
        }
    }

    function adminStatus(msg) {
        var s = el("cb-admin-status");
        if (s) { s.textContent = msg || ""; }
    }

    var _statusT;
    function flashStatus(msg) {
        adminStatus(msg);
        clearTimeout(_statusT);
        _statusT = setTimeout(function () { adminStatus(""); }, 4000);
    }

    function adminErr(msg) {
        var e = el("cb-admin-error");
        adminStatus("");
        if (e) {
            e.textContent = msg || "";
            e.hidden = !msg;
            if (msg && e.focus) {
                try { e.focus(); } catch (x) { /* non-fatal */ }
            }
        }
    }

    function afterAdminOp(okMsg) {
        var e = el("cb-admin-error");
        if (e) { e.textContent = ""; e.hidden = true; }
        flashStatus(okMsg || "Done.");
        fetchFull().then(function (data) {
            if (data) {
                renderTray(data);
                reconcileForms(data, instanceId());
            }
            refreshProvenance();
            populateAdmin();
        });
    }

    function _adminButtons() {
        var sec = el("cb-admin-section");
        return sec ? sec.querySelectorAll(
            ".cb-primary, .cb-go, .cb-iv-cancel") : [];
    }

    function postAdmin(path, body, onok) {
        adminStatus("");
        var btns = _adminButtons();
        btns.forEach(function (b) { b.disabled = true; });
        var done = function () {
            btns.forEach(function (b) { b.disabled = false; });
        };
        fetch(ADMIN_API + path, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body || {}),
        }).then(function (r) {
            return r.json().then(function (b) {
                return { ok: r.ok, body: b };
            });
        }).then(function (res) {
            done();
            if (!res.ok) {
                adminErr(res.body && res.body.error
                    ? res.body.error : "Action failed.");
                return;
            }
            onok(res.body);
        }).catch(function () {
            done();
            adminErr("Action failed.");
        });
    }

    function renderProposals(items) {
        var box = el("cb-proposals");
        if (!box) return;
        items = items || [];
        if (!items.length) {
            box.innerHTML =
                '<div class="cb-empty">No pending proposals.</div>';
            return;
        }
        box.innerHTML = '<ul class="cb-prop-list">'
            + items.map(function (p) {
            return '<li class="cb-prop-item">'
                + '<div class="cb-prop-desc">'
                + describeProposal(p) + "</div>"
                + '<div class="cb-prop-actions">'
                + '<button type="button" class="cb-go" '
                + 'data-confirm="' + esc(p.id) + '">Confirm</button>'
                + '<button type="button" class="cb-iv-cancel" '
                + 'data-reject="' + esc(p.id) + '">Reject</button>'
                + "</div></li>";
        }).join("") + "</ul>";
        box.querySelectorAll("[data-confirm]").forEach(function (b) {
            b.addEventListener("click", function () {
                postAdmin("/proposals/"
                    + encodeURIComponent(b.getAttribute("data-confirm"))
                    + "/confirm", null, function () {
                        afterAdminOp("Proposal confirmed.");
                    });
            });
        });
        box.querySelectorAll("[data-reject]").forEach(function (b) {
            b.addEventListener("click", function () {
                postAdmin("/proposals/"
                    + encodeURIComponent(b.getAttribute("data-reject"))
                    + "/reject", null, function () {
                        flashStatus("Proposal rejected.");
                        populateAdmin();
                    });
            });
        });
    }

    var CHANGES_CAP = 20;

    function renderChanges(items) {
        var box = el("cb-changes");
        if (!box) return;
        var all = (items || []).slice().reverse();   // newest first
        if (!all.length) {
            box.innerHTML = '<li class="cb-empty">No changes yet.</li>';
            return;
        }
        var shown = all.slice(0, CHANGES_CAP);
        var note = all.length > CHANGES_CAP
            ? '<li class="cb-empty">Showing latest ' + CHANGES_CAP
              + "</li>"
            : "";
        box.innerHTML = note + shown.map(function (c) {
            var from = c.old_value == null ? "" : esc(c.old_value);
            var to = c.new_value == null ? "" : (" → "
                + esc(c.new_value));
            return '<li class="cb-chg-item"><span class="cb-chg-op">'
                + esc(c.op) + '</span> ' + from + to
                + ' <span class="cb-chg-by">'
                + esc(c.actor) + "</span></li>";
        }).join("");
    }

    function populateAdmin() {
        var codes = flatCodes();
        fillCodeSelect(el("cb-merge-src"), codes, "merge from…");
        fillCodeSelect(el("cb-merge-dst"), codes, "into…");
        fillCodeSelect(el("cb-split-src"), codes, "split…");
        fetch(ADMIN_API + "/proposals")
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) { renderProposals(d && d.proposals); })
            .catch(function () { /* best-effort */ });
        fetch(ADMIN_API + "/changes")
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) { renderChanges(d && d.changes); })
            .catch(function () { /* best-effort */ });
    }

    function refreshAdmin() {
        var sec = el("cb-admin-section");
        if (!sec) return;
        if (adminProbed) {
            if (adminOK) populateAdmin();
            return;
        }
        adminProbed = true;
        fetch(ADMIN_API + "/proposals").then(function (r) {
            adminOK = r.status === 200;
            sec.hidden = !adminOK;
            if (adminOK) populateAdmin();
        }).catch(function () { sec.hidden = true; });
    }

    function wireAdmin() {
        var m = el("cb-merge-btn");
        if (m) m.addEventListener("click", function () {
            var s = el("cb-merge-src").value;
            var d = el("cb-merge-dst").value;
            if (!s || !d) { adminErr("Pick both codes."); return; }
            postAdmin("/merge", { src_id: s, dst_id: d }, afterAdminOp);
        });
        var sp = el("cb-split-btn");
        if (sp) sp.addEventListener("click", function () {
            var body = {
                src_id: el("cb-split-src").value,
                annotator: (el("cb-split-annotator").value || "").trim(),
                new_name: (el("cb-split-name").value || "").trim(),
            };
            if (!body.src_id || !body.annotator) {
                adminErr("Pick a code and an annotator."); return;
            }
            postAdmin("/split", body, function () {
                el("cb-split-name").value = "";
                el("cb-split-annotator").value = "";
                afterAdminOp();
            });
        });
        var notesBtn = el("cb-notes-suggest-btn");
        if (notesBtn) notesBtn.addEventListener("click", function () {
            postAdmin("/suggest-from-notes", {}, function (body) {
                var n = (body && body.proposals && body.proposals.length)
                    || 0;
                afterAdminOp(n
                    ? n + " new proposal" + (n > 1 ? "s" : "")
                      + " from notes."
                    : "No new proposals from recent notes.");
            });
        });
    }

    // ---- rich-field detail editor (definition/clarification/examples) ---
    // Backend already supports this (PATCH /api/codebook/<id> with any of
    // RICH_FIELDS); this section is the missing frontend for it. One
    // inline panel per code, built on demand from GET /api/codebook/<id>.

    var RICH_TEXT_FIELDS = [
        { key: "definition", label: "Definition" },
        { key: "clarification", label: "Include" },
        { key: "negative_clarification", label: "Exclude" },
    ];

    function escAttr(s) {
        return esc(s).replace(/"/g, "&quot;");
    }

    function exampleRowHtml(kind, idx, ex) {
        ex = ex || {};
        return '<div class="cb-ex-row" data-idx="' + idx + '">'
            + '<input type="text" class="cb-admin-input cb-ex-text" '
            + 'data-kind="' + kind + '" placeholder="Example text" '
            + 'value="' + escAttr(ex.text) + '" />'
            + '<input type="text" class="cb-admin-input cb-ex-why" '
            + 'data-kind="' + kind + '" placeholder="Why (optional)" '
            + 'value="' + escAttr(ex.why) + '" />'
            + '<button type="button" class="cb-iv-cancel cb-ex-remove" '
            + '>Remove</button>'
            + "</div>";
    }

    function renderExampleList(kind, label, items) {
        items = items && items.length ? items : [{}];
        return '<div class="cb-ex-group" data-kind="' + kind + '">'
            + '<div class="cb-admin-label">' + esc(label) + "</div>"
            + '<div class="cb-ex-rows">'
            + items.map(function (ex, i) {
                return exampleRowHtml(kind, i, ex);
            }).join("")
            + "</div>"
            + '<button type="button" class="cb-go cb-ex-add" '
            + 'data-kind="' + kind + '">+ Add example</button>'
            + "</div>";
    }

    function ruleRowHtml(idx, rule) {
        return '<div class="cb-rule-row" data-idx="' + idx + '">'
            + '<input type="text" class="cb-admin-input cb-rule-text" '
            + 'placeholder="Do NOT apply when…" '
            + 'value="' + escAttr(rule) + '" />'
            + '<button type="button" class="cb-iv-cancel cb-rule-remove"'
            + '>Remove</button>'
            + "</div>";
    }

    function renderRuleList(items) {
        items = items && items.length ? items : [""];
        return '<div class="cb-rule-group">'
            + '<div class="cb-admin-label">Exclusion rules</div>'
            + '<div class="cb-rule-rows">'
            + items.map(function (r, i) {
                return ruleRowHtml(i, r);
            }).join("")
            + "</div>"
            + '<button type="button" class="cb-go cb-rule-add"'
            + '>+ Add rule</button>'
            + "</div>";
    }

    function renderDetailForm(container, code) {
        var html = "";
        RICH_TEXT_FIELDS.forEach(function (f) {
            html += '<label class="cb-admin-label" for="cb-fld-'
                + esc(code.id) + "-" + f.key + '">' + f.label + "</label>"
                + '<textarea class="cb-admin-input cb-detail-textarea" '
                + 'id="cb-fld-' + esc(code.id) + "-" + f.key + '" '
                + 'data-field="' + f.key + '" rows="2">'
                + esc(code[f.key] || "") + "</textarea>";
        });
        html += renderExampleList(
            "positive_examples", "Positive examples",
            code.positive_examples || []);
        html += renderExampleList(
            "negative_examples",
            "Negative examples (looks similar, but is NOT)",
            code.negative_examples || []);
        html += renderRuleList(code.exclusion_rules || []);
        html += '<div class="cb-detail-actions">'
            + '<button type="button" class="cb-primary cb-detail-save">'
            + "Save</button>"
            + '<button type="button" class="cb-iv-cancel cb-detail-hist">'
            + "History</button>"
            + "</div>"
            + '<div class="cb-detail-status" aria-live="polite"></div>'
            + '<div class="cb-detail-history" hidden></div>';
        container.innerHTML = html;
    }

    function readDetailForm(container) {
        var payload = {};
        RICH_TEXT_FIELDS.forEach(function (f) {
            var t = container.querySelector(
                'textarea[data-field="' + f.key + '"]');
            payload[f.key] = t ? t.value.trim() : "";
        });
        ["positive_examples", "negative_examples"].forEach(function (kind) {
            var group = container.querySelector(
                '.cb-ex-group[data-kind="' + kind + '"]');
            var rows = group
                ? group.querySelectorAll(".cb-ex-row") : [];
            var out = [];
            rows.forEach(function (row) {
                var text = row.querySelector(".cb-ex-text").value.trim();
                var why = row.querySelector(".cb-ex-why").value.trim();
                if (text) out.push({ text: text, why: why });
            });
            payload[kind] = out;
        });
        var rules = [];
        container.querySelectorAll(".cb-rule-text").forEach(function (i) {
            var v = i.value.trim();
            if (v) rules.push(v);
        });
        payload.exclusion_rules = rules;
        return payload;
    }

    function detailStatus(container, msg) {
        var s = container.querySelector(".cb-detail-status");
        if (s) s.textContent = msg || "";
    }

    function openDetail(id, panel, toggleBtn) {
        panel.innerHTML = '<div class="cb-empty">Loading…</div>';
        panel.hidden = false;
        if (toggleBtn) toggleBtn.setAttribute("aria-expanded", "true");
        fetch(API + "/" + encodeURIComponent(id))
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                if (!d || !d.code) {
                    panel.innerHTML =
                        '<div class="cb-error">Could not load code.'
                        + "</div>";
                    return;
                }
                renderDetailForm(panel, d.code);
            })
            .catch(function () {
                panel.innerHTML =
                    '<div class="cb-error">Could not load code.</div>';
            });
    }

    function closeDetail(panel, toggleBtn) {
        panel.hidden = true;
        panel.innerHTML = "";
        if (toggleBtn) toggleBtn.setAttribute("aria-expanded", "false");
    }

    function saveDetail(id, panel) {
        var btn = panel.querySelector(".cb-detail-save");
        var payload = readDetailForm(panel);
        if (btn) btn.disabled = true;
        detailStatus(panel, "Saving…");
        fetch(API + "/" + encodeURIComponent(id), {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        }).then(function (r) {
            return r.json().then(function (b) {
                return { ok: r.ok, body: b };
            });
        }).then(function (res) {
            if (btn) btn.disabled = false;
            if (!res.ok) {
                detailStatus(panel, (res.body && res.body.error)
                    || "Could not save.");
                return;
            }
            detailStatus(panel, "Saved.");
            if (res.body && res.body.code) {
                renderDetailForm(panel, res.body.code);
                detailStatus(panel, "Saved.");
            }
            refreshProvenance();
        }).catch(function () {
            if (btn) btn.disabled = false;
            detailStatus(panel, "Could not save.");
        });
    }

    function renderHistory(box, rows) {
        rows = rows || [];
        if (!rows.length) {
            box.innerHTML = '<div class="cb-empty">No history yet.</div>';
            return;
        }
        box.innerHTML = '<ul class="cb-changes-list">'
            + rows.slice().reverse().map(function (c) {
                var from = c.old_value == null ? "" : esc(c.old_value);
                var to = c.new_value == null ? "" : (" → "
                    + esc(c.new_value));
                return '<li class="cb-chg-item"><span class="cb-chg-op">'
                    + esc(c.op) + "</span> " + from + to
                    + ' <span class="cb-chg-by">' + esc(c.actor)
                    + "</span></li>";
            }).join("") + "</ul>";
    }

    function toggleHistory(id, panel) {
        var box = panel.querySelector(".cb-detail-history");
        if (!box) return;
        if (!box.hidden) { box.hidden = true; return; }
        box.hidden = false;
        box.innerHTML = '<div class="cb-empty">Loading…</div>';
        fetch(API + "/" + encodeURIComponent(id) + "/history")
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) { renderHistory(box, d && d.history); })
            .catch(function () {
                box.innerHTML =
                    '<div class="cb-error">Could not load history.'
                    + "</div>";
            });
    }

    function wireDetailEditor() {
        var tree = el("cb-tree");
        if (!tree) return;
        tree.addEventListener("click", function (e) {
            var t = e.target;
            var toggle = t.closest(".cb-detail-toggle");
            if (toggle) {
                var id = toggle.getAttribute("data-id");
                var panel = el("cb-detail-" + id);
                if (!panel) return;
                if (panel.hidden) openDetail(id, panel, toggle);
                else closeDetail(panel, toggle);
                return;
            }
            var save = t.closest(".cb-detail-save");
            if (save) {
                var li = t.closest(".cb-node");
                var pnl = li && li.querySelector(".cb-detail");
                if (li && pnl) saveDetail(li.getAttribute("data-id"), pnl);
                return;
            }
            var hist = t.closest(".cb-detail-hist");
            if (hist) {
                var li2 = t.closest(".cb-node");
                var pnl2 = li2 && li2.querySelector(".cb-detail");
                if (li2 && pnl2) {
                    toggleHistory(li2.getAttribute("data-id"), pnl2);
                }
                return;
            }
            var addEx = t.closest(".cb-ex-add");
            if (addEx) {
                var group = addEx.closest(".cb-ex-group");
                var rows = group && group.querySelector(".cb-ex-rows");
                if (rows) {
                    var idx = rows.children.length;
                    rows.insertAdjacentHTML("beforeend",
                        exampleRowHtml(addEx.getAttribute("data-kind"),
                            idx, {}));
                }
                return;
            }
            var rmEx = t.closest(".cb-ex-remove");
            if (rmEx) {
                var row = rmEx.closest(".cb-ex-row");
                if (row) row.remove();
                return;
            }
            var addRule = t.closest(".cb-rule-add");
            if (addRule) {
                var rrows = addRule.parentElement.querySelector(
                    ".cb-rule-rows");
                if (rrows) {
                    rrows.insertAdjacentHTML(
                        "beforeend", ruleRowHtml(rrows.children.length, ""));
                }
                return;
            }
            var rmRule = t.closest(".cb-rule-remove");
            if (rmRule) {
                var rrow = rmRule.closest(".cb-rule-row");
                if (rrow) rrow.remove();
            }
        });
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
    var ivReturn = null;  // element to restore focus to on close

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
        iv.setAttribute("aria-modal", "true");
        iv.setAttribute("aria-label",
            "Create a code from the selected text");
        iv.hidden = true;
        iv.innerHTML =
            '<div class="cb-iv-quote" id="cb-iv-quote"></div>' +
            '<input id="cb-iv-name" class="cb-iv-input" type="text" ' +
                'autocomplete="off" spellcheck="false" ' +
                'aria-label="New code name" ' +
                'aria-describedby="cb-iv-quote" />' +
            '<div id="cb-iv-sim" class="cb-iv-sim" hidden ' +
                'aria-live="polite"></div>' +
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
        // Modal dialog: Esc closes from anywhere inside; Tab is trapped
        // so keyboard focus can't fall behind the popover.
        iv.addEventListener("keydown", function (e) {
            if (e.key === "Escape") {
                e.preventDefault(); closeInvivo(); return;
            }
            if (e.key !== "Tab") return;
            var f = ivFocusables();
            if (!f.length) return;
            var first = f[0], last = f[f.length - 1];
            if (e.shiftKey && document.activeElement === first) {
                e.preventDefault(); last.focus();
            } else if (!e.shiftKey && document.activeElement === last) {
                e.preventDefault(); first.focus();
            }
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

    function ivFocusables() {
        if (!iv) return [];
        return Array.prototype.filter.call(
            iv.querySelectorAll("input, button"),
            function (n) { return !n.disabled && n.offsetParent !== null; });
    }

    function closeInvivo() {
        if (iv) iv.hidden = true;
        ivState = null;
        // Restore focus so the annotator isn't dropped onto <body>
        // mid-coding (WCAG 2.4.3).
        var back = ivReturn;
        ivReturn = null;
        if (back && back.focus) {
            try { back.focus(); } catch (e) { /* non-fatal */ }
        }
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
        // Where focus returns on close. The opener is a keypress over a
        // text selection (no focused control), so prefer the codebook
        // toggle; fall back to whatever was focused, else body.
        var ae = document.activeElement;
        ivReturn = (ae && ae !== document.body && ae.focus) ? ae
            : (el("cb-panel-toggle") || document.body);
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
        wireAdmin();
        wireDetailEditor();

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

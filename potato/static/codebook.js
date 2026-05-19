/*
 * Codebook tray.
 *
 * Self-gating: probes GET /api/codebook. 200 => enabled (reveal the
 * toggle); 401/503 => stay hidden. The response's `can_add` flag
 * decides whether the on-the-fly composer is shown (codebook_mode
 * extensible/open, or a privileged user). Adding a code refreshes the
 * tray; a page reload picks up new labels in the annotation form.
 */
(function () {
    "use strict";

    var API = "/api/codebook";

    function el(id) { return document.getElementById(id); }

    function esc(s) {
        var d = document.createElement("div");
        d.textContent = s == null ? "" : String(s);
        return d.innerHTML;
    }

    function renderTree(nodes, depth) {
        if (!nodes || !nodes.length) return "";
        return nodes.map(function (n) {
            var dot = n.color
                ? '<span class="cb-dot" style="background:'
                  + esc(n.color) + '"></span>'
                : "";
            return '<li class="cb-node">'
                + '<div class="cb-node-row" style="--cb-depth:' + depth
                + '">' + dot
                + '<span class="cb-name">' + esc(n.name) + "</span></div>"
                + (n.children && n.children.length
                    ? '<ul class="cb-children">'
                      + renderTree(n.children, depth + 1) + "</ul>"
                    : "")
                + "</li>";
        }).join("");
    }

    var MODE_HINT = {
        open: "You can add and organize codes.",
        extensible: "You can add new codes.",
    };

    function render(data) {
        var box = el("cb-tree");
        if (box) {
            var tree = (data && data.tree) || [];
            box.innerHTML = tree.length
                ? '<ul class="cb-root">' + renderTree(tree, 0) + "</ul>"
                : '<div class="cb-empty">No codes yet.</div>';
        }
        var composer = el("cb-composer");
        if (composer) composer.hidden = !(data && data.can_add);
        var hint = el("cb-mode-hint");
        if (hint && data) {
            hint.textContent = MODE_HINT[data.mode] || "";
        }
    }

    function load() {
        return fetch(API)
            .then(function (r) {
                return r.ok ? r.json() : null;
            })
            .then(function (data) { if (data) render(data); return data; });
    }

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
            return r.json().then(function (body) {
                return { ok: r.ok, body: body };
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
            load();
        }).catch(function () {
            if (btn) btn.disabled = false;
            if (err) {
                err.textContent = "Could not add code.";
                err.hidden = false;
            }
        });
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
                load();
                var n = el("cb-new-name");
                if (n && !el("cb-composer").hidden) n.focus();
            });
        }
        if (close) close.addEventListener("click", closePanel);
        if (panel) {
            panel.addEventListener("keydown", function (e) {
                if (e.key === "Escape") { e.preventDefault(); closePanel(); }
            });
        }
        var add = el("cb-add-btn");
        if (add) add.addEventListener("click", addCode);
        var input = el("cb-new-name");
        if (input) {
            input.addEventListener("keydown", function (e) {
                if (e.key === "Enter") { e.preventDefault(); addCode(); }
            });
        }
    }

    function init() {
        if (!window.config || !window.config.is_annotation_page) return;
        if (!el("cb-panel")) return;
        // Enable-probe: 200 => enabled+authed; anything else => hidden.
        fetch(API).then(function (r) {
            if (r.status === 200) {
                var t = el("cb-panel-toggle");
                if (t) t.hidden = false;
                wire();
            }
        }).catch(function () { /* leave hidden */ });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();

/*
 * Universal Memos sidebar.
 *
 * Memos persist immediately via /api/memos and Potato navigation is a
 * full page reload, so correctness just requires (re)loading memos for
 * the displayed instance on init. A window.MemoPanel.reload() hook is
 * exposed so that if navigation ever becomes AJAX, the panel can be
 * refreshed from the instance lifecycle without stale state.
 */
(function () {
    "use strict";

    var API = "/api/memos";
    var state = { instanceId: null, memos: [], editingId: null, enabled: false };

    function el(id) { return document.getElementById(id); }

    function currentInstanceId() {
        var input = el("instance_id");
        return input ? input.value : null;
    }

    function esc(s) {
        var d = document.createElement("div");
        d.textContent = s == null ? "" : String(s);
        return d.innerHTML;
    }

    function selectionInText() {
        // Returns {start,end,field,quote} if there is a non-empty selection
        // inside the instance text, else null.
        var sel = window.getSelection();
        if (!sel || sel.isCollapsed || sel.rangeCount === 0) return null;
        var container = document.getElementById("text-content");
        if (!container) return null;
        var range = sel.getRangeAt(0);
        if (!container.contains(range.startContainer) ||
            !container.contains(range.endContainer)) return null;
        var pre = range.cloneRange();
        pre.selectNodeContents(container);
        pre.setEnd(range.startContainer, range.startOffset);
        var start = pre.toString().length;
        var quote = sel.toString();
        if (!quote.trim()) return null;
        return { start: start, end: start + quote.length, field: "text", quote: quote };
    }

    function api(method, path, body) {
        return fetch(API + path, {
            method: method,
            headers: { "Content-Type": "application/json" },
            body: body ? JSON.stringify(body) : undefined,
        });
    }

    function render() {
        var list = el("memo-list");
        if (!list) return;
        if (!state.memos.length) {
            list.innerHTML = '<div class="memo-empty">No notes on this instance yet.</div>';
            return;
        }
        var me = (window.config && window.config.username) || null;
        list.innerHTML = state.memos.map(function (m) {
            var own = m.created_by === me;
            var vis = m.visibility === "shared" ? "shared" : "private";
            var anchorBadge = m.anchor
                ? '<span class="memo-badge anchor" title="Attached to a text selection">quote</span>'
                : "";
            var actions = own
                ? '<span class="memo-actions">'
                  + '<button data-act="edit" data-id="' + m.id + '">Edit</button>'
                  + '<button data-act="del" data-id="' + m.id + '">Delete</button>'
                  + "</span>"
                : "";
            return '<div class="memo-item">'
                + '<div class="memo-body">' + esc(m.body) + "</div>"
                + '<div class="memo-meta">'
                + "<span>" + esc(m.created_by) + "</span>"
                + '<span class="memo-badge ' + vis + '">' + vis + "</span>"
                + anchorBadge + actions
                + "</div></div>";
        }).join("");
        list.querySelectorAll("button[data-act]").forEach(function (b) {
            b.addEventListener("click", function () {
                var id = b.getAttribute("data-id");
                if (b.getAttribute("data-act") === "del") return doDelete(id);
                return startEdit(id);
            });
        });
    }

    function load() {
        state.instanceId = currentInstanceId();
        if (!state.instanceId) return Promise.resolve();
        return api("GET", "?instance_id=" + encodeURIComponent(state.instanceId))
            .then(function (res) {
                if (res.status === 503) { state.enabled = false; return null; }
                state.enabled = true;
                var t = el("memo-panel-toggle");
                if (t) t.hidden = false;
                return res.json();
            })
            .then(function (data) {
                if (!data) return;
                state.memos = data.memos || [];
                render();
            })
            .catch(function () { /* network: leave panel as-is */ });
    }

    function resetComposer() {
        state.editingId = null;
        var body = el("memo-new-body");
        if (body) body.value = "";
        var anchorWrap = el("memo-anchor-wrap");
        if (anchorWrap) anchorWrap.hidden = true;
        var btn = el("memo-add-btn");
        if (btn) btn.textContent = "Add note";
    }

    function startEdit(id) {
        var m = state.memos.filter(function (x) { return x.id === id; })[0];
        if (!m) return;
        state.editingId = id;
        el("memo-new-body").value = m.body;
        el("memo-new-visibility").value = m.visibility;
        el("memo-add-btn").textContent = "Save";
        el("memo-new-body").focus();
    }

    function doDelete(id) {
        api("DELETE", "/" + encodeURIComponent(id)).then(function () {
            load();
        });
    }

    function submit() {
        var bodyEl = el("memo-new-body");
        var body = (bodyEl && bodyEl.value || "").trim();
        if (!body) return;
        var visibility = el("memo-new-visibility").value;
        if (state.editingId) {
            api("PATCH", "/" + encodeURIComponent(state.editingId),
                { body: body, visibility: visibility })
                .then(function () { resetComposer(); load(); });
            return;
        }
        var payload = {
            instance_id: state.instanceId,
            body: body,
            visibility: visibility,
        };
        var anchorCheck = el("memo-anchor-check");
        if (anchorCheck && anchorCheck.checked && state._pendingAnchor) {
            payload.anchor = {
                start: state._pendingAnchor.start,
                end: state._pendingAnchor.end,
                field: state._pendingAnchor.field,
            };
        }
        api("POST", "", payload).then(function (res) {
            if (res.ok) { resetComposer(); load(); }
        });
    }

    function wireSelectionAffordance() {
        document.addEventListener("selectionchange", function () {
            var wrap = el("memo-anchor-wrap");
            if (!wrap) return;
            var s = selectionInText();
            state._pendingAnchor = s;
            if (s) {
                wrap.hidden = false;
                el("memo-anchor-quote").textContent =
                    s.quote.length > 60 ? s.quote.slice(0, 60) + "…" : s.quote;
            } else {
                wrap.hidden = true;
            }
        });
    }

    function wire() {
        var toggle = el("memo-panel-toggle");
        var panel = el("memo-panel");
        var close = el("memo-panel-close");
        if (toggle && panel) {
            toggle.addEventListener("click", function () {
                panel.hidden = false;
                toggle.hidden = true;
                render();
            });
        }
        if (close && panel && toggle) {
            close.addEventListener("click", function () {
                panel.hidden = true;
                toggle.hidden = false;
            });
        }
        var add = el("memo-add-btn");
        if (add) add.addEventListener("click", submit);
        wireSelectionAffordance();
    }

    function init() {
        if (!window.config || !window.config.is_annotation_page) return;
        if (!el("memo-panel")) return;
        wire();
        load();
    }

    window.MemoPanel = { reload: load };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();

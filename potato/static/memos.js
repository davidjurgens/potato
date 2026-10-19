/*
 * Universal Memos sidebar: notes, threads of replies, and issues.
 *
 * Memos persist immediately via /api/memos and Potato navigation is a
 * full page reload, so correctness just requires (re)loading memos for
 * the displayed instance on init. A window.MemoPanel.reload() hook is
 * exposed so that if navigation ever becomes AJAX, the panel can be
 * refreshed from the instance lifecycle without stale state.
 *
 * A thread is a first memo (the root) plus its replies. An issue is a root
 * with a status, open or resolved. The server sends `can_*` flags with each
 * memo saying what this user may do; it checks every action again anyway.
 */
(function () {
    "use strict";

    var API = "/api/memos";
    var state = { instanceId: null, memos: [], editingId: null, enabled: false,
                  replyingTo: null, assigningId: null };

    // Navigation is a full page reload, so "open by default" would otherwise
    // re-open the panel on every item, overriding an annotator who closed it.
    // The dismissal is remembered for the tab session only.
    var DISMISSED = "potato.memoPanel.dismissed";

    function el(id) { return document.getElementById(id); }

    function dismissed() {
        try { return sessionStorage.getItem(DISMISSED) === "1"; }
        catch (e) { return false; }   // storage blocked: treat as not dismissed
    }

    function setDismissed(value) {
        try {
            if (value) sessionStorage.setItem(DISMISSED, "1");
            else sessionStorage.removeItem(DISMISSED);
        } catch (e) { /* storage blocked: the default just applies each load */ }
    }

    // The panel is fixed and 360px wide. Without this the page kept its full
    // width underneath it and the panel covered the Next button.
    function setRail(open) {
        document.body.classList.toggle("potato-rail-open", !!open);
    }

    function openPanel() {
        var panel = el("memo-panel"), toggle = el("memo-panel-toggle");
        if (!panel || !toggle) return;
        panel.hidden = false;
        toggle.hidden = true;
        setRail(true);
    }

    function currentInstanceId() {
        var input = el("instance_id");
        return input ? input.value : null;
    }

    function esc(s) {
        var d = document.createElement("div");
        d.textContent = s == null ? "" : String(s);
        return d.innerHTML;
    }

    // For attribute values: esc() leaves quotes alone, which is fine in text
    // and breaks out of value="...".
    function escAttr(s) {
        return esc(s).replace(/"/g, "&quot;").replace(/'/g, "&#39;");
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

    // ---- shapes ---------------------------------------------------------
    //
    // Drawn shapes carry no stored id, so an issue raised on one records the
    // shape as it was drawn (scheme, type, label, normalised coordinates) and
    // finds it again by geometry.

    function imageManagers() {
        var out = [];
        document.querySelectorAll(".image-annotation-container").forEach(function (c) {
            var m = c.annotationManager;
            if (m && m.canvas) out.push({ manager: m, schema: c.getAttribute("data-schema") });
        });
        return out;
    }

    function selectedShape() {
        var found = null;
        imageManagers().forEach(function (entry) {
            if (found) return;
            var obj = entry.manager.canvas.getActiveObject && entry.manager.canvas.getActiveObject();
            if (!obj || !obj.annotationData || typeof entry.manager._getObjectCoordinates !== "function") return;
            var coords = entry.manager._getObjectCoordinates(obj);
            if (!coords) return;
            found = { schema: entry.schema, type: obj.annotationData.type,
                      label: obj.annotationData.label, coordinates: coords };
        });
        return found;
    }

    function sameGeometry(a, b) {
        var close = function (x, y) { return Math.abs(Number(x) - Number(y)) < 1e-3; };
        if (Array.isArray(a) && Array.isArray(b)) {
            return a.length === b.length && a.every(function (p, i) {
                return close(p.x, b[i].x) && close(p.y, b[i].y);
            });
        }
        if (a && b && typeof a === "object" && typeof b === "object") {
            return ["x", "y", "width", "height"].every(function (k) {
                return a[k] === undefined || close(a[k], b[k]);
            });
        }
        return false;
    }

    function showShape(shape) {
        var hit = null;
        imageManagers().forEach(function (entry) {
            if (hit || entry.schema !== shape.schema) return;
            entry.manager.canvas.getObjects().forEach(function (obj) {
                if (hit || !obj.annotationData || obj.annotationData.type !== shape.type) return;
                if (sameGeometry(entry.manager._getObjectCoordinates(obj), shape.coordinates)) {
                    hit = { entry: entry, obj: obj };
                }
            });
        });
        if (!hit) {
            flash("That shape is no longer on this image as it was drawn.");
            return;
        }
        hit.entry.manager.canvas.setActiveObject(hit.obj);
        hit.entry.manager.canvas.requestRenderAll();
        var container = document.querySelector(
            '.image-annotation-container[data-schema="' + shape.schema + '"]');
        if (container && container.scrollIntoView) container.scrollIntoView({ block: "nearest" });
    }

    function shapeName(shape) {
        var type = { bbox: "box", polygon: "polygon", polyline: "line" }[shape.type] || shape.type;
        return (shape.label ? shape.label + " " : "") + type;
    }

    // ---- server ---------------------------------------------------------

    function api(method, path, body) {
        return fetch(API + path, {
            method: method,
            headers: { "Content-Type": "application/json" },
            body: body ? JSON.stringify(body) : undefined,
        });
    }

    function flash(message) {
        var status = el("memo-status");
        if (!status) return;
        status.textContent = message;
        status.hidden = !message;
    }

    // Report a refused action instead of failing silently.
    function send(method, path, body) {
        return api(method, path, body).then(function (res) {
            if (res.ok) { flash(""); return res; }
            return res.json().catch(function () { return {}; }).then(function (data) {
                flash(data.error || ("The server refused that (HTTP " + res.status + ")."));
                throw new Error("refused");
            });
        });
    }

    // ---- rendering ------------------------------------------------------

    function anchorBadge(m) {
        if (!m.anchor) return "";
        if (m.anchor.shape) {
            return '<button type="button" class="memo-badge anchor memo-shape-link" data-act="shape" data-id="'
                + esc(m.id) + '" title="Select this shape on the image">'
                + esc(shapeName(m.anchor.shape)) + "</button>";
        }
        return '<span class="memo-badge anchor" title="Attached to a text selection">quote</span>';
    }

    function statusBadge(m) {
        if (!m.status) return "";
        var label = m.status === "resolved" ? "Resolved" : "Open issue";
        return '<span class="memo-badge status-' + esc(m.status) + '">' + label + "</span>";
    }

    function renderMemo(m, isReply) {
        var actions = [];
        if (!isReply) actions.push('<button type="button" data-act="reply" data-id="' + esc(m.id) + '">Reply</button>');
        if (m.can_resolve) {
            actions.push(m.status === "resolved"
                ? '<button type="button" data-act="reopen" data-id="' + esc(m.id) + '">Reopen</button>'
                : '<button type="button" data-act="resolve" data-id="' + esc(m.id) + '">Resolve</button>');
        }
        if (m.can_assign) actions.push('<button type="button" data-act="assign" data-id="' + esc(m.id) + '">Assign</button>');
        if (m.can_edit) actions.push('<button type="button" data-act="edit" data-id="' + esc(m.id) + '">Edit</button>');
        if (m.can_delete) actions.push('<button type="button" data-act="del" data-id="' + esc(m.id) + '">Delete</button>');
        var vis = m.visibility === "shared" ? "shared" : "private";
        var assignee = m.assignee
            ? '<span class="memo-assignee">assigned to ' + esc(m.assignee) + "</span>" : "";
        var resolved = m.status === "resolved" && m.resolved_by
            ? '<span class="memo-assignee">resolved by ' + esc(m.resolved_by) + "</span>" : "";
        return '<div class="memo-' + (isReply ? "reply" : "body-wrap") + '">'
            + '<div class="memo-body">' + esc(m.body) + "</div>"
            + '<div class="memo-meta">'
            + "<span>" + esc(m.created_by) + "</span>"
            + (isReply ? "" : '<span class="memo-badge ' + vis + '">' + vis + "</span>")
            + statusBadge(m) + anchorBadge(m) + assignee + resolved
            + (actions.length ? '<span class="memo-actions">' + actions.join("") + "</span>" : "")
            + "</div></div>";
    }

    function render() {
        var list = el("memo-list");
        if (!list) return;
        if (!state.memos.length) {
            list.innerHTML = '<div class="memo-empty">No notes on this instance yet.</div>';
            return;
        }
        var replies = {};
        state.memos.forEach(function (m) {
            if (m.parent_id) (replies[m.parent_id] = replies[m.parent_id] || []).push(m);
        });
        list.innerHTML = state.memos.filter(function (m) { return !m.parent_id; }).map(function (root) {
            var thread = (replies[root.id] || []).map(function (r) { return renderMemo(r, true); }).join("");
            var replyBox = state.replyingTo === root.id
                ? '<div class="memo-inline-form"><label class="memo-sr" for="memo-reply-' + esc(root.id)
                  + '">Reply</label><textarea id="memo-reply-' + esc(root.id)
                  + '" class="memo-reply-input" placeholder="Reply to this thread&hellip;"></textarea>'
                  + '<div class="memo-inline-row"><button type="button" class="memo-primary" data-act="send-reply" data-id="'
                  + esc(root.id) + '">Send reply</button><button type="button" data-act="cancel" data-id="'
                  + esc(root.id) + '">Cancel</button></div></div>'
                : "";
            var assignBox = state.assigningId === root.id
                ? '<div class="memo-inline-form"><label for="memo-assign-' + esc(root.id)
                  + '">Assign to (username, empty to clear)</label><input type="text" id="memo-assign-'
                  + esc(root.id) + '" value="' + escAttr(root.assignee || "") + '">'
                  + '<div class="memo-inline-row"><button type="button" class="memo-primary" data-act="save-assign" data-id="'
                  + esc(root.id) + '">Save</button><button type="button" data-act="cancel" data-id="'
                  + esc(root.id) + '">Cancel</button></div></div>'
                : "";
            return '<div class="memo-item' + (root.status === "open" ? " is-open-issue" : "")
                + (root.status === "resolved" ? " is-resolved" : "") + '">'
                + renderMemo(root, false)
                + (thread ? '<div class="memo-thread">' + thread + "</div>" : "")
                + replyBox + assignBox + "</div>";
        }).join("");
        list.querySelectorAll("button[data-act]").forEach(function (b) {
            b.addEventListener("click", function () { act(b.getAttribute("data-act"), b.getAttribute("data-id")); });
        });
        var focus = state.replyingTo && el("memo-reply-" + state.replyingTo)
            || state.assigningId && el("memo-assign-" + state.assigningId);
        if (focus) focus.focus();
    }

    function byId(id) {
        return state.memos.filter(function (x) { return x.id === id; })[0];
    }

    function act(action, id) {
        var path = "/" + encodeURIComponent(id);
        if (action === "del") return send("DELETE", path).then(load, function () {});
        if (action === "edit") return startEdit(id);
        if (action === "shape") { var m = byId(id); if (m && m.anchor) showShape(m.anchor.shape); return; }
        if (action === "reply") { state.replyingTo = id; state.assigningId = null; return render(); }
        if (action === "assign") { state.assigningId = id; state.replyingTo = null; return render(); }
        if (action === "cancel") { state.replyingTo = null; state.assigningId = null; return render(); }
        if (action === "resolve" || action === "reopen") {
            return send("PATCH", path, { status: action === "resolve" ? "resolved" : "open" })
                .then(function () { load(); loadAssigned(); }, function () {});
        }
        if (action === "send-reply") {
            var input = el("memo-reply-" + id);
            var body = (input && input.value || "").trim();
            if (!body) return;
            return send("POST", path + "/reply", { body: body })
                .then(function () { state.replyingTo = null; load(); }, function () {});
        }
        if (action === "save-assign") {
            var who = el("memo-assign-" + id);
            return send("PATCH", path, { assignee: who ? who.value : "" })
                .then(function () { state.assigningId = null; load(); loadAssigned(); }, function () {});
        }
    }

    // The GET currently outstanding, as {iid, promise}. init() and
    // annotation.js's loadCurrentInstance() both call load() on a page load
    // and used to fetch the same instance's notes twice. Sharing only an
    // *in-flight* request keeps the refreshes after an add, edit or delete
    // honest -- those run once the first one has settled, so they never fold
    // into it.
    var inFlight = null;

    function load() {
        var iid = currentInstanceId();
        if (!iid) return Promise.resolve();
        if (inFlight && inFlight.iid === iid) return inFlight.promise;
        state.instanceId = iid;
        var pending = api("GET", "?instance_id=" + encodeURIComponent(iid))
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
                if (data.open_by_default && !dismissed()) openPanel();
            })
            .catch(function () { /* network: leave panel as-is */ })
            .then(function () {
                if (inFlight && inFlight.promise === pending) inFlight = null;
            });
        inFlight = { iid: iid, promise: pending };
        return pending;
    }

    // Open issues assigned to this annotator, on any item. The count sits on
    // the Notes button, so an assignment is seen even with the panel closed.
    function loadAssigned() {
        return api("GET", "/issues?status=open&assignee=me")
            .then(function (res) { return res.ok ? res.json() : null; })
            .then(function (data) {
                if (data) renderAssigned(data.issues || []);
            })
            .catch(function () { /* network: leave as-is */ });
    }

    function renderAssigned(issues) {
        var box = el("memo-assigned"), count = el("memo-assigned-count");
        var here = currentInstanceId();
        if (count) {
            count.hidden = !issues.length;
            count.textContent = issues.length ? " \u00b7 " + issues.length + " assigned to you" : "";
        }
        if (!box) return;
        box.hidden = !issues.length;
        if (!issues.length) { box.innerHTML = ""; return; }
        box.innerHTML = '<h3 class="memo-assigned-title">Assigned to you (' + issues.length + ')</h3>' +
            '<ul class="memo-assigned-list">' + issues.map(function (m) {
                var text = String(m.body || "");
                if (text.length > 90) text = text.slice(0, 89) + "\u2026";
                var where;
                if (m.instance_id === here) {
                    where = '<span class="memo-assigned-where">This item</span>';
                } else if (typeof m.position === "number") {
                    where = '<button type="button" class="memo-assigned-go" data-pos="' + m.position +
                        '">Go to item ' + (m.position + 1) + '</button>';
                } else {
                    where = '<span class="memo-assigned-where">Item ' + esc(m.instance_id) +
                        ' (not in your queue)</span>';
                }
                return '<li><span class="memo-assigned-text">' + esc(text) + '</span>' +
                    '<span class="memo-assigned-meta">from ' + esc(m.created_by) + ' \u00b7 ' + where + '</span></li>';
            }).join("") + '</ul>';
        box.querySelectorAll(".memo-assigned-go").forEach(function (b) {
            b.addEventListener("click", function () {
                var pos = parseInt(b.getAttribute("data-pos"), 10);
                if (typeof window.navigateToInstance === "function") window.navigateToInstance(pos);
            });
        });
    }

    function resetComposer() {
        state.editingId = null;
        var body = el("memo-new-body");
        if (body) body.value = "";
        ["memo-anchor-wrap", "memo-shape-wrap"].forEach(function (id) {
            var wrap = el(id);
            if (wrap) wrap.hidden = true;
        });
        var issue = el("memo-new-issue");
        if (issue) issue.checked = false;
        var assignee = el("memo-new-assignee");
        if (assignee) { assignee.value = ""; }
        var assignWrap = el("memo-new-assignee-wrap");
        if (assignWrap) assignWrap.hidden = true;
        var btn = el("memo-add-btn");
        if (btn) btn.textContent = "Add note";
    }

    function startEdit(id) {
        var m = byId(id);
        if (!m) return;
        state.editingId = id;
        el("memo-new-body").value = m.body;
        if (!m.parent_id) el("memo-new-visibility").value = m.visibility;
        el("memo-add-btn").textContent = "Save";
        el("memo-new-body").focus();
    }

    function submit() {
        var bodyEl = el("memo-new-body");
        var body = (bodyEl && bodyEl.value || "").trim();
        if (!body) return;
        var visibility = el("memo-new-visibility").value;
        if (state.editingId) {
            var editing = byId(state.editingId);
            var patch = editing && editing.parent_id ? { body: body } : { body: body, visibility: visibility };
            send("PATCH", "/" + encodeURIComponent(state.editingId), patch)
                .then(function () { resetComposer(); load(); }, function () {});
            return;
        }
        var payload = {
            instance_id: state.instanceId,
            body: body,
            visibility: visibility,
        };
        var issue = el("memo-new-issue");
        if (issue && issue.checked) {
            payload.issue = true;
            var assignee = el("memo-new-assignee");
            if (assignee && assignee.value.trim()) payload.assignee = assignee.value.trim();
        }
        var shapeCheck = el("memo-shape-check");
        var anchorCheck = el("memo-anchor-check");
        if (shapeCheck && shapeCheck.checked && state._pendingShape) {
            payload.anchor = { shape: state._pendingShape };
        } else if (anchorCheck && anchorCheck.checked && state._pendingAnchor) {
            payload.anchor = {
                start: state._pendingAnchor.start,
                end: state._pendingAnchor.end,
                field: state._pendingAnchor.field,
            };
        }
        send("POST", "", payload).then(function () { resetComposer(); load(); loadAssigned(); }, function () {});
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

    // A shape becomes selected by a click or a key on the canvas; look then.
    // Typing in the panel itself must not clear what was picked on the image.
    function wireShapeAffordance() {
        var update = function (event) {
            var panel = el("memo-panel");
            if (panel && event && panel.contains(event.target)) return;
            var wrap = el("memo-shape-wrap");
            if (!wrap) return;
            var shape = selectedShape();
            state._pendingShape = shape;
            if (shape) {
                wrap.hidden = false;
                el("memo-shape-name").textContent = shapeName(shape);
            } else {
                wrap.hidden = true;
                var check = el("memo-shape-check");
                if (check) check.checked = false;
            }
        };
        document.addEventListener("mouseup", function (e) { setTimeout(function () { update(e); }, 0); });
        document.addEventListener("keyup", update);
    }

    function wire() {
        var toggle = el("memo-panel-toggle");
        var panel = el("memo-panel");
        var close = el("memo-panel-close");
        if (toggle && panel) {
            toggle.addEventListener("click", function () {
                openPanel();
                setDismissed(false);
                render();
            });
        }
        if (close && panel && toggle) {
            close.addEventListener("click", function () {
                panel.hidden = true;
                toggle.hidden = false;
                setRail(false);
                // Closing it means closing it, not closing it until the next item.
                setDismissed(true);
            });
        }
        var add = el("memo-add-btn");
        if (add) add.addEventListener("click", submit);
        var issue = el("memo-new-issue");
        var assignWrap = el("memo-new-assignee-wrap");
        if (issue && assignWrap) {
            issue.addEventListener("change", function () { assignWrap.hidden = !issue.checked; });
        }
        wireSelectionAffordance();
        wireShapeAffordance();
    }

    function init() {
        if (!window.config || !window.config.is_annotation_page) return;
        if (!el("memo-panel")) return;
        wire();
        load().then(function () { if (state.enabled) loadAssigned(); });
    }

    window.MemoPanel = { reload: load, reloadAssigned: loadAssigned, _sameGeometry: sameGeometry };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();

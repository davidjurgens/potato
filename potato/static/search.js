/*
 * Annotator search-and-claim sidebar.
 *
 * Self-gating: on init it probes GET /api/search with no query. The
 * endpoint returns 400 ("q required") when annotator search-and-claim
 * is enabled and the user is authenticated, and 403/401/503 otherwise.
 * The toggle is only revealed on 400, so the feature stays invisible
 * unless search.annotator_claim is on.
 */
(function () {
    "use strict";

    var API = "/api/search";

    function el(id) { return document.getElementById(id); }

    function esc(s) {
        var d = document.createElement("div");
        d.textContent = s == null ? "" : String(s);
        return d.innerHTML;
    }

    function renderResults(data) {
        var box = el("search-results");
        if (!box) return;
        var hits = (data && data.results) || [];
        if (!hits.length) {
            box.innerHTML = '<div class="search-empty">No matches.</div>';
            return;
        }
        box.innerHTML = hits.map(function (h) {
            return '<div class="search-item">'
                + '<div class="search-snippet">' + esc(h.snippet) + "</div>"
                + '<div class="search-row">'
                + '<span class="search-id">' + esc(h.instance_id) + "</span>"
                + '<button class="search-claim" data-id="'
                + esc(h.instance_id) + '">Claim</button>'
                + "</div></div>";
        }).join("");
        box.querySelectorAll(".search-claim").forEach(function (b) {
            b.addEventListener("click", function () { claim(b); });
        });
    }

    function claim(btn) {
        var id = btn.getAttribute("data-id");
        btn.disabled = true;
        fetch(API + "/claim", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ instance_id: id }),
        }).then(function (r) {
            if (!r.ok) { btn.disabled = false; return; }
            var span = document.createElement("span");
            span.className = "search-claimed";
            span.textContent = "✓ In your queue";
            btn.replaceWith(span);
        }).catch(function () { btn.disabled = false; });
    }

    function doSearch() {
        var input = el("search-q");
        var q = (input && input.value || "").trim();
        if (!q) return;
        fetch(API + "?q=" + encodeURIComponent(q) + "&limit=50")
            .then(function (r) { return r.ok ? r.json() : { results: [] }; })
            .then(renderResults)
            .catch(function () { renderResults({ results: [] }); });
    }

    function wire() {
        var toggle = el("search-panel-toggle");
        var panel = el("search-panel");
        var close = el("search-panel-close");
        if (toggle && panel) {
            toggle.addEventListener("click", function () {
                panel.hidden = false;
                toggle.hidden = true;
                var q = el("search-q");
                if (q) q.focus();
            });
        }
        if (close && panel && toggle) {
            close.addEventListener("click", function () {
                panel.hidden = true;
                toggle.hidden = false;
            });
        }
        var go = el("search-go");
        if (go) go.addEventListener("click", doSearch);
        var input = el("search-q");
        if (input) {
            input.addEventListener("keydown", function (e) {
                if (e.key === "Enter") { e.preventDefault(); doSearch(); }
            });
        }
    }

    function init() {
        if (!window.config || !window.config.is_annotation_page) return;
        if (!el("search-panel")) return;
        // Enable-probe: 400 => enabled+authed; anything else => stay hidden.
        fetch(API).then(function (r) {
            if (r.status === 400) {
                var t = el("search-panel-toggle");
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

/* Codebook full-page document view controller.
 *
 * Read view renders server-sanitized `body_html` (the XSS trust boundary is
 * server-side render_markdown -> sanitize_html). Edit view is a typed-block
 * editor: every block carries a type; pasted/imported markdown is parsed by
 * the server and any unclassifiable block must be typed before saving.
 * Saves are optimistic (base_version); a 409 surfaces a diff to rebase.
 *
 * Namespaced onto window.CodebookDoc (the template already set .project).
 */
(function () {
  "use strict";

  var NS = (window.CodebookDoc = window.CodebookDoc || {});
  var API = "/api/codebook";

  var state = {
    doc: null,
    canEdit: false,
    editing: false,
    blockTypes: [],
    semanticKeys: {},
    openEditors: {}, // scopeKey -> editor controller
  };

  // ---- small DOM helpers --------------------------------------------------
  function $(id) { return document.getElementById(id); }
  function ce(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function scopeKey(kind, id) { return kind + ":" + id; }

  function toast(msg, warn) {
    var t = $("cbd-toast");
    t.textContent = msg;
    t.classList.toggle("is-warn", !!warn);
    // Errors must interrupt (assertive); successes stay polite so they
    // don't talk over the user mid-action.
    t.setAttribute("role", warn ? "alert" : "status");
    t.setAttribute("aria-live", warn ? "assertive" : "polite");
    t.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(function () { t.hidden = true; }, 2600);
  }

  // ---- dialog/overlay focus management ------------------------------------
  // Shared by the import modal and the history drawer: move focus in on open,
  // trap Tab inside, and restore focus to the invoker on close.
  var FOCUSABLE =
    'a[href],button:not([disabled]),textarea,input:not([disabled]),' +
    'select:not([disabled]),[tabindex]:not([tabindex="-1"])';

  function openDialog(el, focusEl) {
    el._returnFocus = document.activeElement;
    el.hidden = false;
    var f = focusEl || el.querySelector(FOCUSABLE);
    if (f) f.focus();
  }
  function closeDialog(el) {
    el.hidden = true;
    var ret = el._returnFocus;
    el._returnFocus = null;
    if (ret && ret.focus) ret.focus();
  }
  function trapTab(el, e) {
    if (e.key !== "Tab") return;
    var f = el.querySelectorAll(FOCUSABLE);
    if (!f.length) return;
    var first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault(); last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault(); first.focus();
    }
  }

  // ---- API ----------------------------------------------------------------
  function api(method, path, body) {
    var opts = {
      method: method,
      credentials: "same-origin",
      headers: { "Accept": "application/json" },
    };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    return fetch(API + path, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        return { ok: r.ok, status: r.status, body: j };
      });
    });
  }

  // ---- load + render ------------------------------------------------------
  function load(opts) {
    var keepY = opts && opts.keepScroll ? window.scrollY : null;
    return api("GET", "/document").then(function (res) {
      if (!res.ok) {
        $("cbd-loading").textContent =
          (res.body && res.body.error) || "Could not load the codebook.";
        return;
      }
      state.doc = res.body;
      state.canEdit = !!res.body.can_edit_content;
      state.blockTypes = res.body.block_types || [];
      state.semanticKeys = {};
      state.blockTypes.forEach(function (bt) {
        if (bt.semantic) state.semanticKeys[bt.key] = true;
      });
      render();
      if (keepY != null) window.scrollTo(0, keepY);
    });
  }

  function render() {
    var doc = state.doc;
    $("cbd-loading").hidden = true;
    var root = $("cbd-doc");
    root.hidden = false;
    root.textContent = "";

    if (state.canEdit) {
      $("cbd-edit-toggle").hidden = false;
      $("cbd-import-btn").hidden = false;
    }
    var rev = $("cbd-rev");
    rev.hidden = false;
    rev.textContent = "content rev " + (doc.content_revision || 0);

    document.body.classList.toggle("cbd-editing", state.editing);

    var toc = $("cbd-toc");
    toc.textContent = "";

    // document-level sections (only those with content, unless editing)
    var docGroup = ce("div", "cbd-toc-group");
    var docHead = ce("div", "cbd-toc-group-h", "Document");
    docGroup.appendChild(docHead);
    var anyDoc = false;
    (doc.doc_sections || []).forEach(function (sec) {
      var has = (sec.blocks || []).length > 0;
      if (!has && !state.editing) return;
      anyDoc = true;
      root.appendChild(renderSection({
        kind: "section", id: sec.section, title: sec.title,
        isDoc: true, blocks: sec.blocks, version: sec.scope_version,
      }));
      docGroup.appendChild(tocLink(sec.title, scopeKey("section", sec.section), 0));
    });
    if (anyDoc) toc.appendChild(docGroup);

    // codes
    var codeGroup = ce("div", "cbd-toc-group");
    codeGroup.appendChild(ce("div", "cbd-toc-group-h", "Codes"));
    (doc.codes || []).forEach(function (c) {
      root.appendChild(renderSection({
        kind: "code", id: c.id, title: c.name, color: c.color,
        depth: c.depth || 0, blocks: c.blocks, version: c.scope_version,
      }));
      codeGroup.appendChild(tocLink(c.name, scopeKey("code", c.id), c.depth || 0));
    });
    toc.appendChild(codeGroup);

    populateImportTargets();
    setupScrollSpy();
  }

  // Highlight the TOC entry for the section currently in view.
  function setupScrollSpy() {
    if (state._spy) { state._spy.disconnect(); state._spy = null; }
    if (!("IntersectionObserver" in window)) return;
    var links = {};
    Array.prototype.forEach.call(
      document.querySelectorAll(".cbd-toc-link"), function (a) {
        links[a.getAttribute("href")] = a;
      });
    state._spy = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        var a = links["#" + en.target.id];
        if (!a) return;
        Array.prototype.forEach.call(
          document.querySelectorAll(".cbd-toc-link.is-active"),
          function (x) { x.classList.remove("is-active"); });
        a.classList.add("is-active");
      });
    }, { rootMargin: "-20% 0px -70% 0px" });
    Array.prototype.forEach.call(
      document.querySelectorAll(".cbd-section"),
      function (sec) { state._spy.observe(sec); });
  }

  function tocLink(label, key, depth) {
    var a = ce("a", "cbd-toc-link", label);
    a.href = "#sec-" + key;
    a.setAttribute("data-depth", String(depth || 0));
    a.addEventListener("click", function (e) {
      e.preventDefault();
      var el = document.getElementById("sec-" + key);
      if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    return a;
  }

  function renderSection(s) {
    var sec = ce("section", "cbd-section");
    sec.id = "sec-" + scopeKey(s.kind, s.id);
    sec.setAttribute("data-scope-kind", s.kind);
    sec.setAttribute("data-scope-id", s.id);
    sec._scope = s;

    var head = ce("div", "cbd-section-head");
    if (s.kind === "code" && s.color) {
      var sw = ce("span", "cbd-swatch");
      sw.style.backgroundColor = s.color;
      head.appendChild(sw);
    }
    var name = ce("h2", "cbd-section-name" + (s.isDoc ? " is-doc" : ""), s.title);
    head.appendChild(name);

    if (state.canEdit) {
      var tools = ce("div", "cbd-section-tools");
      var editBtn = ce("button", "cbd-btn cbd-btn-ghost cbd-btn-sm", "Edit");
      editBtn.addEventListener("click", function () { openEditor(sec, s); });
      var histBtn = ce("button", "cbd-btn cbd-btn-ghost cbd-btn-sm", "History");
      histBtn.addEventListener("click", function () { openHistory(s); });
      tools.appendChild(editBtn);
      tools.appendChild(histBtn);
      head.appendChild(tools);
    }
    sec.appendChild(head);

    var body = ce("div", "cbd-section-body");
    body.appendChild(renderBlocks(s.blocks));
    sec.appendChild(body);
    return sec;
  }

  function renderBlocks(blocks) {
    var wrap = ce("div", "cbd-blocks");
    if (!blocks || !blocks.length) {
      wrap.appendChild(ce("div", "cbd-empty-scope", state.canEdit
        ? "No content yet — use Edit to add a definition."
        : "No content yet."));
      return wrap;
    }
    blocks.forEach(function (b) {
      var isSem = !!state.semanticKeys[b.block_type];
      var bl = ce("div", "cbd-block" + (isSem ? " is-semantic" : ""));
      var label = ce("div", "cbd-block-label", headingFor(b));
      if (isSem) {
        // The "•" marker is visual-only; give AT users the meaning, and a
        // hover tooltip for sighted users.
        label.title = "Editing this changes meaning and flags re-review";
        label.appendChild(ce("span", "cbd-sr-only",
          " (changes here trigger re-review)"));
      }
      bl.appendChild(label);
      var body = ce("div", "cbd-block-body");
      body.innerHTML = b.body_html || ""; // server-sanitized
      bl.appendChild(body);
      wrap.appendChild(bl);
    });
    return wrap;
  }

  function headingFor(b) {
    if (b.block_type === "custom") return b.custom_label || "Note";
    var bt = state.blockTypes.filter(function (x) { return x.key === b.block_type; })[0];
    return bt ? bt.heading : b.block_type;
  }

  // ---- editor -------------------------------------------------------------
  function openEditor(sec, s, seedBlocks) {
    var key = scopeKey(s.kind, s.id);
    var body = sec.querySelector(".cbd-section-body");
    body.textContent = "";
    var editor = buildEditor(s, seedBlocks || s.blocks, body);
    state.openEditors[key] = editor;
    body.appendChild(editor.el);
    editor.focusFirst();
  }

  function buildEditor(s, blocks, mountBody) {
    var key = scopeKey(s.kind, s.id);
    var version = s.version || 0;
    var wrap = ce("div", "cbd-editor");
    var conflictBox = null;
    var rowsHost = ce("div", "cbd-editor-rows");
    wrap.appendChild(rowsHost);

    var rows = [];
    function addRow(b, focus) {
      var row = makeRow(b || { block_type: "", body_md: "", classified: true });
      rows.push(row);
      rowsHost.appendChild(row.el);
      if (focus) row.focus();
    }
    (blocks || []).forEach(function (b) { addRow(b); });
    if (!rows.length) addRow({ block_type: "definition", body_md: "" }, false);

    // footer
    var foot = ce("div", "cbd-edit-foot");
    var addBtn = ce("button", "cbd-btn cbd-btn-ghost cbd-btn-sm", "+ Add block");
    addBtn.addEventListener("click", function () { addRow(null, true); });
    var minorLabel = ce("label", "cbd-minor");
    var minorChk = document.createElement("input");
    minorChk.type = "checkbox";
    minorLabel.appendChild(minorChk);
    minorLabel.appendChild(document.createTextNode("Minor edit (no re-review)"));
    var spacer = ce("span", "cbd-edit-spacer");
    var cancelBtn = ce("button", "cbd-btn cbd-btn-ghost cbd-btn-sm", "Cancel");
    cancelBtn.addEventListener("click", function () { closeEditor(s); });
    var saveBtn = ce("button", "cbd-btn cbd-btn-primary cbd-btn-sm", "Save");
    saveBtn.addEventListener("click", doSave);
    foot.appendChild(addBtn);
    foot.appendChild(minorLabel);
    foot.appendChild(spacer);
    foot.appendChild(cancelBtn);
    foot.appendChild(saveBtn);
    wrap.appendChild(foot);

    function collect() {
      return rows.filter(function (r) { return !r.removed; })
        .map(function (r) { return r.value(); });
    }
    function hasUnTyped() {
      return rows.some(function (r) { return !r.removed && r.needsType(); });
    }

    function doSave() {
      if (hasUnTyped()) {
        toast("Give every block a type before saving.", true);
        return;
      }
      var payload = {
        scope_kind: s.kind, scope_id: s.id,
        base_version: version, minor: minorChk.checked,
        blocks: collect(),
      };
      if (s.kind === "code") payload.code_id = s.id;
      else payload.section = s.id;
      saveBtn.disabled = true;
      api("PUT", "/blocks", payload).then(function (res) {
        saveBtn.disabled = false;
        if (res.ok) {
          if (res.body.queued) {
            toast("Edit submitted for admin review.");
          } else {
            toast(res.body.semantic ? "Saved (flagged for re-review)." : "Saved.");
          }
          load({ keepScroll: true }); // refresh versions, keep the user's place
          return;
        }
        if (res.status === 409) {
          showConflict(res.body);
          return;
        }
        toast((res.body && res.body.error) || "Save failed.", true);
      });
    }

    function showConflict(body) {
      if (conflictBox) conflictBox.remove();
      conflictBox = ce("div", "cbd-conflict");
      conflictBox.appendChild(ce("div", null,
        "Someone else changed this section (now version " +
        body.current_version + "). Review their version, then reload to rebase."));
      var pre = ce("pre");
      pre.textContent = body.current_md || "";
      conflictBox.appendChild(pre);
      var reload = ce("button", "cbd-btn cbd-btn-ghost cbd-btn-sm", "Reload latest");
      reload.addEventListener("click", function () {
        version = body.current_version;
        s.version = body.current_version;
        s.blocks = body.current_blocks || [];
        openEditor(mountBody.closest(".cbd-section"), s);
      });
      conflictBox.appendChild(reload);
      wrap.insertBefore(conflictBox, rowsHost);
    }

    return {
      el: wrap,
      focusFirst: function () { if (rows[0]) rows[0].focus(); },
    };
  }

  function makeRow(b) {
    var row = { removed: false };
    var el = ce("div", "cbd-edit-block");
    var head = ce("div", "cbd-edit-row");

    var sel = document.createElement("select");
    sel.setAttribute("aria-label", "Block type");
    var optBlank = ce("option", null, "Choose a type…");
    optBlank.value = "";
    sel.appendChild(optBlank);
    state.blockTypes.forEach(function (bt) {
      var o = ce("option", null, bt.heading + (bt.semantic ? " (re-review)" : ""));
      o.value = bt.key;
      sel.appendChild(o);
    });
    sel.value = b.block_type || "";

    var customInput = document.createElement("input");
    customInput.type = "text";
    customInput.placeholder = "Custom heading";
    customInput.setAttribute("aria-label", "Custom heading");
    customInput.value = b.custom_label || "";
    customInput.style.display = (b.block_type === "custom") ? "" : "none";

    var needsBadge = ce("span", "cbd-needs-type", "Pick a type");
    var unclassified = (b.classified === false);
    needsBadge.style.display = unclassified ? "" : "none";

    function syncCustom() {
      customInput.style.display = (sel.value === "custom") ? "" : "none";
    }
    // Keep the body field's accessible name tied to its chosen type so AT
    // announces "Definition content" rather than a nameless textarea.
    function syncTaLabel() {
      var heading = "Block";
      var bt = state.blockTypes.filter(
        function (x) { return x.key === sel.value; })[0];
      if (bt) heading = bt.heading;
      else if (sel.value === "custom") heading = customInput.value || "Custom";
      ta.setAttribute("aria-label", heading + " content (markdown)");
    }
    sel.addEventListener("change", function () {
      needsBadge.style.display = "none";
      unclassified = false;
      syncCustom();
      syncTaLabel();
    });
    customInput.addEventListener("input", syncTaLabel);

    var spacer = ce("span", "cbd-edit-spacer");
    var rm = ce("button", "cbd-btn cbd-btn-ghost cbd-btn-sm", "Remove");
    rm.addEventListener("click", function () {
      row.removed = true;
      el.remove();
    });

    head.appendChild(sel);
    head.appendChild(customInput);
    head.appendChild(needsBadge);
    head.appendChild(spacer);
    head.appendChild(rm);
    el.appendChild(head);

    var ta = document.createElement("textarea");
    ta.className = "cbd-textarea";
    ta.rows = 3;
    ta.value = b.body_md || "";
    ta.placeholder = "Markdown…";
    el.appendChild(ta);
    syncTaLabel();

    row.el = el;
    row.focus = function () { sel.value ? ta.focus() : sel.focus(); };
    row.needsType = function () {
      return unclassified || !sel.value;
    };
    row.value = function () {
      var v = { block_type: sel.value || "custom", body_md: ta.value };
      if (v.block_type === "custom") v.custom_label = customInput.value || "Note";
      return v;
    };
    return row;
  }

  function closeEditor(s) {
    var key = scopeKey(s.kind, s.id);
    delete state.openEditors[key];
    // re-render just by reloading the doc (cheap; keeps versions correct)
    load();
  }

  // ---- import / paste markdown -------------------------------------------
  function populateImportTargets() {
    var sel = $("cbd-import-target");
    if (!sel) return;
    sel.textContent = "";
    (state.doc.doc_sections || []).forEach(function (sec) {
      var o = ce("option", null, "Document · " + sec.title);
      o.value = "section:" + sec.section;
      sel.appendChild(o);
    });
    (state.doc.codes || []).forEach(function (c) {
      var o = ce("option", null, "Code · " + c.name);
      o.value = "code:" + c.id;
      sel.appendChild(o);
    });
  }

  function openImport() {
    $("cbd-import-text").value = "";
    openDialog($("cbd-import-modal"), $("cbd-import-text"));
  }
  function closeImport() { closeDialog($("cbd-import-modal")); }

  function doImportParse() {
    var md = $("cbd-import-text").value;
    var target = $("cbd-import-target").value || "";
    if (!target) { closeImport(); return; }
    var parts = target.split(":");
    var kind = parts[0], id = parts.slice(1).join(":");
    api("POST", "/parse", { markdown: md }).then(function (res) {
      if (!res.ok) { toast("Parse failed.", true); return; }
      closeImport();
      // ensure editing mode, find/refresh the section, open its editor seeded
      state.editing = true;
      // locate scope object from current doc
      var s = findScope(kind, id);
      if (!s) { toast("Pick a valid target.", true); return; }
      var sec = document.getElementById("sec-" + scopeKey(kind, id));
      // merge parsed blocks after existing ones
      var seed = (s.blocks || []).concat(res.body.blocks || []);
      document.body.classList.add("cbd-editing");
      openEditor(sec, s, seed);
      sec.scrollIntoView({ behavior: "smooth", block: "start" });
      if ((res.body.blocks || []).some(function (b) { return b.classified === false; })) {
        toast("Some blocks need a type — pick one before saving.", true);
      }
    });
  }

  function findScope(kind, id) {
    if (kind === "section") {
      var sec = (state.doc.doc_sections || []).filter(function (x) { return x.section === id; })[0];
      return sec ? { kind: "section", id: id, title: sec.title, isDoc: true, blocks: sec.blocks, version: sec.scope_version } : null;
    }
    var c = (state.doc.codes || []).filter(function (x) { return x.id === id; })[0];
    return c ? { kind: "code", id: id, title: c.name, color: c.color, depth: c.depth, blocks: c.blocks, version: c.scope_version } : null;
  }

  // ---- history + restore --------------------------------------------------
  function openHistory(s) {
    var drawer = $("cbd-history");
    $("cbd-history-title").textContent = "History · " + s.title;
    var bodyHost = $("cbd-history-body");
    bodyHost.textContent = "Loading…";
    openDialog(drawer, $("cbd-history-close"));
    api("GET", "/history?scope_kind=" + encodeURIComponent(s.kind) +
      "&scope_id=" + encodeURIComponent(s.id)).then(function (res) {
      bodyHost.textContent = "";
      var rows = (res.body && res.body.history) || [];
      if (!rows.length) { bodyHost.appendChild(ce("div", "cbd-empty-scope", "No saved versions yet.")); return; }
      rows.forEach(function (snap, idx) {
        bodyHost.appendChild(renderSnap(s, snap, idx === 0));
      });
    });
  }

  function renderSnap(s, snap, isCurrent) {
    var box = ce("div", "cbd-snap");
    var meta = ce("div", "cbd-snap-meta");
    meta.appendChild(ce("span", "cbd-snap-actor", snap.actor || "unknown"));
    var when = new Date((snap.created_at || 0) * 1000);
    meta.appendChild(ce("span", null, isNaN(when) ? "" : when.toLocaleString()));
    if (snap.semantic) meta.appendChild(ce("span", "cbd-snap-sem", "semantic"));
    if (isCurrent) meta.appendChild(ce("span", null, "· current"));
    box.appendChild(meta);

    var tools = ce("div", "cbd-snap-tools");
    var viewBtn = ce("button", "cbd-btn cbd-btn-ghost cbd-btn-sm", "View");
    viewBtn.addEventListener("click", function () {
      api("GET", "/history/" + snap.id).then(function (res) {
        var existing = box.querySelector(".cbd-diff");
        if (existing) { existing.remove(); return; }
        var pre = ce("pre", "cbd-diff");
        pre.textContent = (res.body && res.body.snapshot_md) || "(empty)";
        box.appendChild(pre);
      });
    });
    tools.appendChild(viewBtn);
    if (state.canEdit && !isCurrent) {
      var restoreBtn = ce("button", "cbd-btn cbd-btn-ghost cbd-btn-sm", "Restore");
      restoreBtn.addEventListener("click", function () {
        api("POST", "/restore", { snapshot_id: snap.id }).then(function (res) {
          if (res.ok) { toast("Restored."); closeDialog($("cbd-history")); load(); }
          else if (res.status === 409) { toast("Changed since — reopen history.", true); }
          else { toast((res.body && res.body.error) || "Restore failed.", true); }
        });
      });
      tools.appendChild(restoreBtn);
    }
    box.appendChild(tools);
    return box;
  }

  // ---- wiring -------------------------------------------------------------
  function wire() {
    $("cbd-edit-toggle").addEventListener("click", function () {
      state.editing = !state.editing;
      this.setAttribute("aria-pressed", state.editing ? "true" : "false");
      this.textContent = state.editing ? "Done" : "Edit";
      load();
    });
    $("cbd-import-btn").addEventListener("click", openImport);
    $("cbd-import-close").addEventListener("click", closeImport);
    $("cbd-import-cancel").addEventListener("click", closeImport);
    $("cbd-import-parse").addEventListener("click", doImportParse);
    $("cbd-history-close").addEventListener("click", function () {
      closeDialog($("cbd-history"));
    });
    // Keyboard handling for the open overlay: trap Tab, and let Escape close
    // only the topmost layer (modal sits above the drawer).
    document.addEventListener("keydown", function (e) {
      var modal = $("cbd-import-modal"), drawer = $("cbd-history");
      var top = !modal.hidden ? modal : (!drawer.hidden ? drawer : null);
      if (!top) return;
      if (e.key === "Tab") { trapTab(top, e); return; }
      if (e.key === "Escape") { e.preventDefault(); closeDialog(top); }
    });
  }

  NS.reload = load;
  document.addEventListener("DOMContentLoaded", function () {
    wire();
    load();
  });
})();

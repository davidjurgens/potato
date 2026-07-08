/*
 * Multi-Document Event Annotation
 *
 * Drives the `multi_document_event` schema form. The authoritative store is the
 * server-side Event Registry (/corpus/api/*), keyed by event id and document id.
 * This manager fetches state for the CURRENT document on load and on every
 * navigation, so switching documents can never lose data (it is already
 * persisted server-side). The schema's hidden input is only a lightweight mirror
 * of memberships; we read its value on init (never hardcoded defaults) to stay
 * compatible with the standard persistence pipeline.
 *
 * console.log/debug/info are suppressed unless ui_debug — use warn/error.
 */
(function () {
  "use strict";

  const API = {
    template: "/corpus/api/event_template",
    events: (docId) => `/corpus/api/events?doc_id=${encodeURIComponent(docId)}`,
    create: "/corpus/api/event",
    slot: (id) => `/corpus/api/event/${encodeURIComponent(id)}/slot`,
    title: (id) => `/corpus/api/event/${encodeURIComponent(id)}/title`,
    member: (id) => `/corpus/api/event/${encodeURIComponent(id)}/member`,
    evidence: (id) => `/corpus/api/event/${encodeURIComponent(id)}/evidence`,
    evidenceDel: (id, i) => `/corpus/api/event/${encodeURIComponent(id)}/evidence/${i}`,
    del: (id) => `/corpus/api/event/${encodeURIComponent(id)}`,
  };

  window.mdeManagers = window.mdeManagers || {};

  async function apiJSON(url, opts) {
    const res = await fetch(url, {
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      ...opts,
    });
    if (!res.ok) {
      const msg = `MDE API ${url} -> ${res.status}`;
      console.error(msg);
      throw new Error(msg);
    }
    return res.status === 204 ? null : res.json();
  }

  function esc(s) {
    const d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  }

  // Character offsets of the current selection within `root` (its textContent).
  function selectionOffsets(root) {
    const sel = window.getSelection();
    if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return null;
    const range = sel.getRangeAt(0);
    if (!root.contains(range.commonAncestorContainer)) return null;
    const pre = range.cloneRange();
    pre.selectNodeContents(root);
    pre.setEnd(range.startContainer, range.startOffset);
    const start = pre.toString().length;
    const text = range.toString();
    if (!text) return null;
    return { start, end: start + text.length, text };
  }

  function findSpanTargetRoot(node) {
    let el = node && node.nodeType === 3 ? node.parentElement : node;
    while (el && el !== document.body) {
      if (el.matches && el.matches('.display-field[data-span-target="true"]')) return el;
      if (el.id && el.id.indexOf("text-content") === 0) return el;
      el = el.parentElement;
    }
    // Fallback: first span-target field on the page.
    return document.querySelector('.display-field[data-span-target="true"]')
        || document.getElementById("instance-text")
        || document.getElementById("text-content");
  }

  class MDEManager {
    constructor(container) {
      this.container = container;
      this.schemeName = container.dataset.schemeName || container.id;
      this.allowCreate = container.dataset.allowCreate === "true";
      try {
        this.slots = JSON.parse(container.dataset.slots || "[]");
      } catch (e) {
        this.slots = [];
        console.error("MDE: bad slots JSON", e);
      }
      this.hidden = container.querySelector('input[type="hidden"]');
      this.listEl = container.querySelector('[data-role="event-list"]');
      this.editorEl = container.querySelector('[data-role="editor"]');
      this.editorTitleEl = container.querySelector('[data-role="editor-title"]');
      this.membershipEl = container.querySelector('[data-role="membership-toggle"]');
      this.slotsEl = container.querySelector('[data-role="slots"]');
      this.hintEl = container.querySelector('[data-role="cite-hint"]');
      this.hintSlotEl = container.querySelector('[data-role="cite-slot"]');

      this.events = [];
      this.activeEventId = null;
      this.pendingCiteSlot = null;
      // Serialize mutating writes so each picks up the freshest version stamp.
      // This prevents same-user field edits from racing into spurious optimistic-
      // lock conflicts, while a genuinely concurrent OTHER annotator still 409s.
      this._writeChain = Promise.resolve();

      this._bindStatic();
      this.init();
    }

    getDocId() {
      const inp = document.getElementById("instance_id");
      if (inp && inp.value) return inp.value;
      return (window.currentInstance && window.currentInstance.id) || "";
    }

    // Run write operations one-at-a-time (FIFO) so each reads the latest stamp.
    _enqueue(fn) {
      const next = this._writeChain.then(fn, fn);
      // Swallow errors on the chain so one failure doesn't wedge the queue.
      this._writeChain = next.catch(() => {});
      return next;
    }

    _bindStatic() {
      const createBtn = this.container.querySelector('[data-role="create-event"]');
      if (createBtn) createBtn.addEventListener("click", () => this.createEvent());

      const cancelCite = this.container.querySelector('[data-role="cite-cancel"]');
      if (cancelCite) cancelCite.addEventListener("click", () => this.cancelCite());

      if (this.membershipEl) {
        this.membershipEl.addEventListener("change", () => this.toggleMembership());
      }

      // Re-sync whenever the annotator navigates to another document.
      const idInput = document.getElementById("instance_id");
      if (idInput) {
        idInput.addEventListener("change", () => this.refresh());
        idInput.addEventListener("input", () => this.refresh());
      }

      // Evidence capture: a selection made while a slot is pending is cited.
      document.addEventListener("mouseup", () => {
        if (!this.pendingCiteSlot) return;
        const root = findSpanTargetRoot(
          (window.getSelection() || {}).anchorNode
        );
        if (!root) return;
        const off = selectionOffsets(root);
        if (off) this.citeEvidence(this.pendingCiteSlot, off);
      });
    }

    async init() {
      try {
        const tpl = await apiJSON(API.template);
        if (tpl && Array.isArray(tpl.slots) && tpl.slots.length) {
          this.slots = tpl.slots;
        }
        if (typeof tpl.allow_annotator_create === "boolean") {
          this.allowCreate = tpl.allow_annotator_create;
        }
      } catch (e) {
        // Template endpoint optional; fall back to embedded slots.
      }
      // Persistence-safe: honor any server-restored hidden value as a hint.
      // (Authoritative data still comes from the API refresh below.)
      this.refresh();
    }

    async refresh() {
      const docId = this.getDocId();
      if (!docId) return;
      try {
        const data = await apiJSON(API.events(docId));
        this.events = (data && data.events) || [];
      } catch (e) {
        this.events = [];
      }
      // Keep the active event only if it still exists.
      if (this.activeEventId && !this.events.find((e) => e.id === this.activeEventId)) {
        this.activeEventId = null;
      }
      this.renderList();
      this.renderEditor();
      this.syncHidden();
    }

    renderList() {
      if (!this.listEl) return;
      const docId = this.getDocId();
      if (!this.events.length) {
        this.listEl.innerHTML = '<p class="mde-empty">No events yet. Create one to begin.</p>';
        return;
      }
      this.listEl.innerHTML = this.events
        .map((ev) => {
          const isMember = ev.member_doc_ids.indexOf(docId) !== -1;
          const active = ev.id === this.activeEventId ? " mde-active" : "";
          const label = ev.title || "Untitled event";
          return `
          <div class="mde-event-row${active}" data-event-id="${esc(ev.id)}">
            <button type="button" class="mde-event-open" data-role="open" data-id="${esc(ev.id)}">
              ${esc(label)}
            </button>
            <span class="mde-event-meta">${ev.member_doc_ids.length} docs${
            isMember ? " · this doc" : ""
          }${ev.provenance === "seeded" ? " · seeded" : ""}</span>
            <button type="button" class="mde-event-del" data-role="del" data-id="${esc(ev.id)}"
                    title="Delete event">×</button>
          </div>`;
        })
        .join("");

      this.listEl.querySelectorAll('[data-role="open"]').forEach((b) =>
        b.addEventListener("click", () => this.openEvent(b.dataset.id))
      );
      this.listEl.querySelectorAll('[data-role="del"]').forEach((b) =>
        b.addEventListener("click", () => this.deleteEvent(b.dataset.id))
      );
    }

    renderEditor() {
      if (!this.editorEl) return;
      const ev = this.events.find((e) => e.id === this.activeEventId);
      if (!ev) {
        this.editorEl.style.display = "none";
        return;
      }
      this.editorEl.style.display = "";
      const docId = this.getDocId();
      if (this.editorTitleEl) {
        this.editorTitleEl.value = ev.title || "";
        if (!this.editorTitleEl._bound) {
          this.editorTitleEl.addEventListener("change", () =>
            this.saveTitle(this.editorTitleEl.value)
          );
          this.editorTitleEl._bound = true;
        }
      }
      if (this.membershipEl) {
        this.membershipEl.checked = ev.member_doc_ids.indexOf(docId) !== -1;
      }

      this.slotsEl.innerHTML = this.slots
        .map((slot) => {
          const val = ev.slot_values[slot.name] || "";
          const cites = (ev.evidence || []).filter((c) => c.slot_name === slot.name);
          const citeHtml = cites
            .map(
              (c, i) => `
            <li class="mde-cite" data-idx="${ev.evidence.indexOf(c)}">
              <span class="mde-cite-doc">${esc(c.doc_id)}</span>
              <span class="mde-cite-text">"${esc(c.quoted_text)}"</span>
              <button type="button" class="mde-cite-del" data-role="cite-del"
                      data-idx="${ev.evidence.indexOf(c)}" title="Remove citation">×</button>
            </li>`
            )
            .join("");
          return `
          <div class="mde-slot" data-slot="${esc(slot.name)}">
            <label class="mde-slot-label" title="${esc(slot.description || "")}">
              ${esc(slot.name)}
            </label>
            <div class="mde-slot-row">
              <input type="text" class="mde-slot-input" data-slot="${esc(slot.name)}"
                     value="${esc(val)}" placeholder="${esc(slot.description || "")}">
              <button type="button" class="mde-cite-btn" data-role="cite" data-slot="${esc(slot.name)}">
                Cite
              </button>
            </div>
            <ul class="mde-cite-list">${citeHtml}</ul>
          </div>`;
        })
        .join("");

      this.slotsEl.querySelectorAll(".mde-slot-input").forEach((inp) => {
        inp.addEventListener("change", () => this.saveSlot(inp.dataset.slot, inp.value));
      });
      this.slotsEl.querySelectorAll('[data-role="cite"]').forEach((b) =>
        b.addEventListener("click", () => this.beginCite(b.dataset.slot))
      );
      this.slotsEl.querySelectorAll('[data-role="cite-del"]').forEach((b) =>
        b.addEventListener("click", () => this.removeEvidence(parseInt(b.dataset.idx, 10)))
      );
    }

    syncHidden() {
      if (!this.hidden) return;
      const docId = this.getDocId();
      const mine = this.events
        .filter((e) => e.member_doc_ids.indexOf(docId) !== -1)
        .map((e) => e.id);
      this.hidden.value = mine.length ? JSON.stringify(mine) : "";
      // Let the standard pipeline persist the per-instance mirror.
      this.hidden.dispatchEvent(new Event("change", { bubbles: true }));
    }

    // ---- actions ---------------------------------------------------------
    async createEvent() {
      if (!this.allowCreate) return;
      try {
        const ev = await apiJSON(API.create, {
          method: "POST",
          body: JSON.stringify({ title: "", doc_id: this.getDocId() }),
        });
        this.activeEventId = ev.id;
        await this.refresh();
        // Focus the inline title field so the annotator can name it immediately.
        const t = this.editorEl && this.editorEl.querySelector('[data-role="editor-title"]');
        if (t) t.focus();
      } catch (e) {
        /* logged in apiJSON */
      }
    }

    saveTitle(title) {
      return this._enqueue(() => this._saveTitle(title));
    }

    async _saveTitle(title) {
      if (!this.activeEventId) return;
      try {
        const updated = await apiJSON(API.title(this.activeEventId), {
          method: "POST",
          body: JSON.stringify({ title }),
        });
        const ev = this.events.find((e) => e.id === this.activeEventId);
        if (ev) {
          ev.title = title;
          // Keep the local version stamp fresh, or the next slot save would send
          // a stale version and hit a spurious optimistic-lock conflict.
          ev.updated_at = updated.updated_at;
        }
        this.renderList();
      } catch (e) {}
    }

    openEvent(id) {
      this.activeEventId = id;
      this.renderList();
      this.renderEditor();
    }

    async deleteEvent(id) {
      if (!window.confirm("Delete this event? This cannot be undone.")) return;
      try {
        await apiJSON(API.del(id), { method: "DELETE" });
        if (this.activeEventId === id) this.activeEventId = null;
        await this.refresh();
      } catch (e) {}
    }

    async toggleMembership() {
      if (!this.activeEventId) return;
      const attach = this.membershipEl.checked;
      try {
        await apiJSON(API.member(this.activeEventId), {
          method: "POST",
          body: JSON.stringify({ doc_id: this.getDocId(), attach }),
        });
        await this.refresh();
      } catch (e) {}
    }

    saveSlot(slot, value) {
      return this._enqueue(() => this._saveSlot(slot, value));
    }

    async _saveSlot(slot, value) {
      if (!this.activeEventId) return;
      const ev = this.events.find((e) => e.id === this.activeEventId);
      const expected = ev ? ev.updated_at : undefined;
      const res = await fetch(API.slot(this.activeEventId), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ slot, value, expected_updated_at: expected }),
      });
      if (res.status === 409) {
        // Another annotator edited this event first — refresh to their version.
        console.warn("MDE: slot save conflict; refreshing event");
        window.alert(
          "Another annotator changed this event while you were editing. " +
            "Reloading the latest version."
        );
        await this.refresh();
        return;
      }
      if (!res.ok) {
        console.error(`MDE slot save -> ${res.status}`);
        return;
      }
      const updated = await res.json();
      // Keep the local version stamp fresh so the next save isn't a false conflict.
      if (ev) {
        ev.slot_values[slot] = value;
        ev.updated_at = updated.updated_at;
      }
    }

    beginCite(slot) {
      this.pendingCiteSlot = slot;
      if (this.hintEl) {
        this.hintEl.style.display = "";
        if (this.hintSlotEl) this.hintSlotEl.textContent = slot;
      }
    }

    cancelCite() {
      this.pendingCiteSlot = null;
      if (this.hintEl) this.hintEl.style.display = "none";
    }

    async citeEvidence(slot, off) {
      const eventId = this.activeEventId;
      this.cancelCite();
      if (!eventId) return;
      try {
        await apiJSON(API.evidence(eventId), {
          method: "POST",
          body: JSON.stringify({
            slot,
            doc_id: this.getDocId(),
            start: off.start,
            end: off.end,
            text: off.text,
          }),
        });
        await this.refresh();
      } catch (e) {}
    }

    async removeEvidence(index) {
      if (!this.activeEventId || isNaN(index)) return;
      try {
        await apiJSON(API.evidenceDel(this.activeEventId, index), { method: "DELETE" });
        await this.refresh();
      } catch (e) {}
    }
  }

  function initAll() {
    document.querySelectorAll(".mde-container").forEach((c) => {
      const key = c.dataset.schemeName || c.id;
      if (!key || window.mdeManagers[key]) return;
      window.mdeManagers[key] = new MDEManager(c);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initAll);
  } else {
    initAll();
  }
})();

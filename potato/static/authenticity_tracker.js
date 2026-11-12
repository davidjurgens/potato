/**
 * Authenticity Tracker - page-level paradata for every task type.
 *
 * Records, per view of an item, whether the annotator left the page, copied the
 * item, pasted text that did not come from the page, and whether the browser
 * shows signs of automation. Counts, durations and maxima only: copied and
 * pasted text is compared against the page in memory and then discarded, never
 * stored or sent.
 *
 * The client keeps running totals for the current view and posts the whole
 * snapshot each time, so a retried or duplicated post replaces rather than
 * double-counts. Flags are computed server-side (potato/authenticity.py);
 * thresholds are never sent to the page.
 *
 * Loaded only when `authenticity.enabled`; configured by window.authenticityConfig.
 */
class AuthenticityTracker {
    constructor(config) {
        const cfg = config || {};
        this.flushIntervalMs = cfg.flush_interval_ms || 10000;
        this.minAwayMs = cfg.min_away_ms || 1000;
        this.trackPointer = cfg.track_pointer !== false;
        this.debugMode = false;

        this.currentInstanceId = null;
        this.hiddenSince = null;
        this.blurSince = null;
        this.awayIsLinked = false;
        this.ownLinkAt = 0;
        this.lastPageCopy = null;     // normalized text of the last in-page copy (memory only)
        this.lastSelection = '';

        // Pointer state persists across items: the cursor does not move just
        // because the item changed.
        this.lastPointer = null;
        this.lastMoveCounted = 0;
        this.lastDownPos = null;
        this.movesSinceDown = 0;
        this.lastDpr = window.devicePixelRatio || 1;
        this.loadedAt = Date.now();
        this.lastSent = 0;

        this.startView();

        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => this.init());
        } else {
            this.init();
        }
    }

    init() {
        if (this.isInitialized) return;
        this.isInitialized = true;

        document.addEventListener('visibilitychange', () => this.onVisibilityChange());
        window.addEventListener('blur', () => this.onWindowBlur());
        window.addEventListener('focus', () => this.onWindowFocus());

        document.addEventListener('copy', (e) => this.onCopy(e, false), true);
        document.addEventListener('cut', (e) => this.onCopy(e, true), true);
        document.addEventListener('paste', (e) => this.onPaste(e), true);
        document.addEventListener('contextmenu', (e) => this.onContextMenu(e), true);
        document.addEventListener('selectionchange', () => this.onSelectionChange());
        document.addEventListener('click', (e) => this.onClick(e), true);

        // Event types Potato itself never synthesizes (it dispatches only
        // input/change/click), so an untrusted one came from somewhere else.
        ['pointerdown', 'mousedown', 'keydown'].forEach((type) => {
            document.addEventListener(type, (e) => {
                if (e.isTrusted === false) this.bump('untrusted_events');
            }, true);
        });
        document.addEventListener('pointerdown', (e) => this.onPointerDown(e), true);
        if (this.trackPointer) {
            document.addEventListener('pointermove', (e) => this.onPointerMove(e),
                                      { capture: true, passive: true });
        }

        let resizeTimer = null;
        window.addEventListener('resize', () => {
            clearTimeout(resizeTimer);
            resizeTimer = setTimeout(() => this.onResize(), 250);
        });

        window.addEventListener('pagehide', () => this.flush(true));
        this.flushTimer = setInterval(() => this.flush(false), this.flushIntervalMs);

        this._hookInstanceChange();
        // Report once straight away: an item answered with no report at all is
        // itself a signal (scripts blocked or the page modified), and that is
        // only distinguishable from a fast answer if the first post is prompt.
        setTimeout(() => this.flush(false, true), 1500);
        setTimeout(() => this.flush(false, true), 5500);

        if (this.debugMode) console.log('[AuthenticityTracker] Initialized');
    }

    /** End the current view (if any) and start counting a new one. */
    startView() {
        this.viewId = this._randomId();
        this.viewStart = Date.now();
        this.itemCopiedAt = null;
        this.itemCopyChars = 0;
        this.awayStartedAt = null;
        this.dirty = true;
        const screenW = (window.screen && window.screen.availWidth) || 0;
        this.s = {
            elapsed_ms: 0,
            hidden_events: 0, hidden_ms: 0,
            blur_events: 0, blur_ms: 0,
            linked_away_events: 0, linked_away_ms: 0,
            item_copy_events: 0, item_copy_chars: 0,
            other_copy_events: 0, cut_events: 0,
            item_select_events: 0, item_context_menu_events: 0,
            paste_events: 0, external_paste_events: 0, external_paste_words: 0,
            item_paste_events: 0,
            resize_events: 0, zoom_changes: 0,
            pointer_moves: 0, pointer_distance_px: 0,
            mouse_clicks: 0, teleport_clicks: 0,
            untrusted_events: 0,
            max_away_ms: 0,
            max_external_paste_words: 0,
            max_away_after_item_copy_ms: 0,
            // [gap_ms, away_ms, copy_chars] per absence after an item copy.
            copy_away_pairs: [],
            max_paste_words_after_item_copy: 0,
            webdriver: navigator.webdriver === true,
            touch_input: false,
            large_screen: screenW >= 1200,
        };
        const ratio = this._windowRatio();
        if (ratio) this.s.min_window_ratio = ratio;
    }

    _hookInstanceChange() {
        const it = window.interactionTracker;
        if (!it || it.__authenticityHooked) return;
        const original = it.setInstanceId.bind(it);
        const self = this;
        it.setInstanceId = function (instanceId) {
            if (instanceId !== self.currentInstanceId) {
                if (self.currentInstanceId === null || self.currentInstanceId === undefined) {
                    // First id of the page: what was counted while it loaded
                    // belongs to this item.
                    self.currentInstanceId = instanceId;
                } else {
                    // Last post of the outgoing view: ask the server to persist it.
                    self.flush(false, true, true);
                    self.currentInstanceId = instanceId;
                    self.startView();
                }
                self.flush(false, true);
            }
            return original(instanceId);
        };
        it.__authenticityHooked = true;
        this.currentInstanceId = it.currentInstanceId;
    }

    bump(key, by = 1) {
        this.s[key] = (this.s[key] || 0) + by;
        this.dirty = true;
    }

    // ---------------------------------------------------------------
    // Leaving the page
    // ---------------------------------------------------------------

    onVisibilityChange() {
        if (document.hidden) {
            if (this.hiddenSince === null) this._beginAway();
            this.hiddenSince = Date.now();
            // Leaving is the moment most likely to be the last one: report now.
            this.flush(true);
        } else if (this.hiddenSince !== null) {
            this._endAway(Date.now() - this.hiddenSince, 'hidden');
            this.hiddenSince = null;
            this.blurSince = null;
        }
    }

    onWindowBlur() {
        // Focus moving into an embedded iframe (a video player, say) blurs the
        // window without the annotator going anywhere.
        const active = document.activeElement;
        if (active && active.tagName === 'IFRAME') return;
        if (this.blurSince === null && this.hiddenSince === null) {
            this._beginAway();
            this.blurSince = Date.now();
        }
    }

    onWindowFocus() {
        if (this.blurSince !== null) {
            // Switching tabs fires both visibilitychange and blur; count it once.
            if (this.hiddenSince === null) {
                this._endAway(Date.now() - this.blurSince, 'blur');
            }
            this.blurSince = null;
        }
    }

    _beginAway() {
        // Switching tabs fires blur and then visibilitychange; the absence
        // began at the first of them.
        if (this.blurSince === null && this.hiddenSince === null) {
            this.awayStartedAt = Date.now();
        }
        // A page the task itself opened (codebook, instructions) is not leaving
        // the task.
        this.awayIsLinked = (Date.now() - this.ownLinkAt) < 3000;
        // The cursor may be somewhere else entirely when the annotator returns.
        this.lastDownPos = null;
    }

    _endAway(durationMs, kind) {
        if (durationMs < this.minAwayMs) return;
        if (this.awayIsLinked) {
            this.bump('linked_away_events');
            this.bump('linked_away_ms', durationMs);
            return;
        }
        if (kind === 'hidden') {
            this.bump('hidden_events');
            this.bump('hidden_ms', durationMs);
        } else {
            this.bump('blur_events');
            this.bump('blur_ms', durationMs);
        }
        this.s.max_away_ms = Math.max(this.s.max_away_ms, durationMs);
        if (this.itemCopiedAt !== null) {
            this.s.max_away_after_item_copy_ms =
                Math.max(this.s.max_away_after_item_copy_ms, durationMs);
            const started = this.awayStartedAt !== null ? this.awayStartedAt
                : Date.now() - durationMs;
            this._recordCopyAway(Math.max(0, started - this.itemCopiedAt),
                                 durationMs, this.itemCopyChars);
        }
    }

    /** Keep the pair; when full, it replaces the shortest absence held. */
    _recordCopyAway(gapMs, awayMs, copyChars) {
        const pairs = this.s.copy_away_pairs;
        const pair = [Math.round(gapMs), Math.round(awayMs), copyChars];
        if (pairs.length < 20) {
            pairs.push(pair);
        } else {
            let shortest = 0;
            pairs.forEach((p, i) => { if (p[1] < pairs[shortest][1]) shortest = i; });
            if (awayMs > pairs[shortest][1]) pairs[shortest] = pair;
        }
    }

    onClick(e) {
        const link = e.target && e.target.closest && e.target.closest('a[href]');
        if (link && (link.target === '_blank' || e.ctrlKey || e.metaKey || e.button === 1)) {
            this.ownLinkAt = Date.now();
        }
    }

    // ---------------------------------------------------------------
    // Copy / paste / selection
    // ---------------------------------------------------------------

    _norm(s) {
        return (s || '').toLowerCase().replace(/\s+/g, ' ').trim();
    }

    _itemRoot() {
        return document.querySelector('.instance-area') || document.getElementById('instance-text');
    }

    _itemText() {
        const parts = [];
        const tc = document.getElementById('text-content');
        if (tc && tc.dataset && tc.dataset.originalText) parts.push(tc.dataset.originalText);
        const root = this._itemRoot();
        if (root) parts.push(root.innerText || root.textContent || '');
        return this._norm(parts.join(' '));
    }

    _inItem(node) {
        const root = this._itemRoot();
        if (!root || !node) return false;
        const el = node.nodeType === 1 ? node : node.parentElement;
        return !!(el && root.contains(el));
    }

    _selectedText() {
        const active = document.activeElement;
        if (active && (active.tagName === 'TEXTAREA' || active.tagName === 'INPUT')) {
            try {
                const v = active.value || '';
                return v.substring(active.selectionStart || 0, active.selectionEnd || 0);
            } catch (err) { /* input type without selection API */ }
        }
        const sel = document.getSelection && document.getSelection();
        return sel ? sel.toString() : '';
    }

    onCopy(e, isCut) {
        if (isCut) this.bump('cut_events');
        const text = this._selectedText();
        const needle = this._norm(text);
        this.lastPageCopy = needle || null;
        const sel = document.getSelection && document.getSelection();
        const fromItem = (sel && sel.rangeCount && this._inItem(sel.anchorNode))
            || (needle.length >= 12 && this._itemText().indexOf(needle) !== -1);
        if (fromItem && needle) {
            this.bump('item_copy_events');
            this.bump('item_copy_chars', needle.length);
            this.itemCopiedAt = Date.now();
            this.itemCopyChars = needle.length;
        } else if (!isCut) {
            this.bump('other_copy_events');
        }
    }

    onPaste(e) {
        let text = '';
        try {
            text = (e.clipboardData || window.clipboardData).getData('text') || '';
        } catch (err) { /* clipboard unavailable */ }
        this.bump('paste_events');
        const needle = this._norm(text);
        if (!needle) return;
        const words = needle.split(' ').filter(Boolean).length;

        // From this page? The item, the annotator's own earlier copy, or text
        // already in one of the page's fields.
        if (needle.length >= 12 && this._itemText().indexOf(needle) !== -1) {
            this.bump('item_paste_events');
            return;
        }
        if (this.lastPageCopy && this.lastPageCopy === needle) return;
        let inFields = false;
        document.querySelectorAll('textarea, input[type="text"]').forEach((el) => {
            if (!inFields && this._norm(el.value).indexOf(needle) !== -1) inFields = true;
        });
        if (inFields) return;

        this.bump('external_paste_events');
        this.bump('external_paste_words', words);
        this.s.max_external_paste_words = Math.max(this.s.max_external_paste_words, words);
        if (this.itemCopiedAt !== null) {
            this.s.max_paste_words_after_item_copy =
                Math.max(this.s.max_paste_words_after_item_copy, words);
        }
    }

    onContextMenu(e) {
        if (this._inItem(e.target)) this.bump('item_context_menu_events');
    }

    onSelectionChange() {
        clearTimeout(this.selectionTimer);
        this.selectionTimer = setTimeout(() => {
            const sel = document.getSelection && document.getSelection();
            if (!sel || !sel.rangeCount || !this._inItem(sel.anchorNode)) return;
            const text = this._norm(sel.toString());
            if (text.length >= 20 && text !== this.lastSelection) {
                this.lastSelection = text;
                this.bump('item_select_events');
            }
        }, 400);
    }

    // ---------------------------------------------------------------
    // Pointer, window, automation
    // ---------------------------------------------------------------

    onPointerMove(e) {
        if (e.pointerType && e.pointerType !== 'mouse') return;
        if (!e.isTrusted) return;
        this.movesSinceDown += 1;
        const now = Date.now();
        if (this.lastPointer) {
            const dx = e.clientX - this.lastPointer.x;
            const dy = e.clientY - this.lastPointer.y;
            this.s.pointer_distance_px += Math.round(Math.sqrt(dx * dx + dy * dy));
        }
        this.lastPointer = { x: e.clientX, y: e.clientY };
        // Sampled count, so a fast mouse on a high-rate device does not dominate.
        if (now - this.lastMoveCounted >= 50) {
            this.lastMoveCounted = now;
            this.s.pointer_moves += 1;
        }
        // Not marked dirty: movement alone would post (and rewrite the
        // annotator's saved state) every flush interval for as long as the
        // mouse moves. The totals ride on the next post that has a reason to
        // go -- a real event, the 30 s heartbeat, an item change or leaving.
    }

    onPointerDown(e) {
        if (!e.isTrusted) return;
        if (e.pointerType === 'touch' || e.pointerType === 'pen') {
            this.s.touch_input = true;
            this.dirty = true;
            return;
        }
        if (e.pointerType !== 'mouse') return;
        this.bump('mouse_clicks');
        const pos = { x: e.clientX, y: e.clientY };
        if (this.trackPointer && this.lastDownPos && this.movesSinceDown === 0) {
            const dx = pos.x - this.lastDownPos.x;
            const dy = pos.y - this.lastDownPos.y;
            if (Math.abs(dx) > 5 || Math.abs(dy) > 5) this.bump('teleport_clicks');
        }
        this.lastDownPos = pos;
        this.lastPointer = pos;
        this.movesSinceDown = 0;
    }

    _windowRatio() {
        const screenW = (window.screen && window.screen.availWidth) || 0;
        const outer = window.outerWidth || 0;
        if (!screenW || !outer) return null;
        return Math.round((outer / screenW) * 1000) / 1000;
    }

    onResize() {
        const dpr = window.devicePixelRatio || 1;
        if (Math.abs(dpr - this.lastDpr) > 0.01) {
            // Browser zoom changes devicePixelRatio and fires resize.
            this.lastDpr = dpr;
            this.bump('zoom_changes');
            return;
        }
        this.bump('resize_events');
        const ratio = this._windowRatio();
        if (ratio && (!this.s.min_window_ratio || ratio < this.s.min_window_ratio)) {
            this.s.min_window_ratio = ratio;
        }
    }

    // ---------------------------------------------------------------
    // Transport
    // ---------------------------------------------------------------

    _randomId() {
        try {
            if (window.crypto && crypto.getRandomValues) {
                const a = new Uint32Array(3);
                crypto.getRandomValues(a);
                return Array.from(a, (n) => n.toString(36)).join('');
            }
        } catch (e) { /* fall through */ }
        return Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
    }

    snapshot() {
        this.s.elapsed_ms = Date.now() - this.viewStart;
        return Object.assign({}, this.s);
    }

    /**
     * Post the current view's snapshot.
     * @param {boolean} isFinal - page is going away; use sendBeacon
     * @param {boolean} force - send even if nothing changed
     * @param {boolean} endOfView - last post for this view (item change)
     */
    flush(isFinal, force, endOfView) {
        // Annotation pages learn their instance id shortly after load. Until
        // then a post would land in the phase-page bucket, so wait a little;
        // pages that never get an id (consent, surveys) are phase pages.
        if (this.currentInstanceId == null && !isFinal
                && Date.now() - this.loadedAt < 5000) {
            return;
        }
        // Heartbeat every 30s keeps elapsed time current on a quiet page.
        const stale = Date.now() - this.lastSent >= 30000 && !document.hidden;
        if (!this.dirty && !isFinal && !force && !stale) return;
        this.dirty = false;
        this.lastSent = Date.now();
        const payload = JSON.stringify({
            instance_id: this.currentInstanceId,
            view_id: this.viewId,
            snapshot: this.snapshot(),
            // The server buffers writes of ordinary posts; a final one is
            // written straight away, since nothing may follow it.
            final: !!(isFinal || endOfView),
            tracker_version: 1,
        });
        if (this.debugMode) console.log('[AuthenticityTracker] flush', payload);
        if (isFinal && navigator.sendBeacon) {
            navigator.sendBeacon('/api/track_authenticity',
                                 new Blob([payload], { type: 'application/json' }));
            return;
        }
        try {
            fetch('/api/track_authenticity', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: payload,
                keepalive: true,
            }).catch(() => { this.dirty = true; });
        } catch (e) {
            this.dirty = true;
        }
    }
}

if (typeof window !== 'undefined') {
    window.AuthenticityTracker = AuthenticityTracker;
    window.authenticityTracker = new AuthenticityTracker(window.authenticityConfig || {});
}
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { AuthenticityTracker };
}

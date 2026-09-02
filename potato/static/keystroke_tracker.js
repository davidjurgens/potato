/**
 * Keystroke Tracker - content-blind typing dynamics for free-text fields.
 *
 * Records HOW a free-text response was produced, never WHAT was typed. Each
 * event carries a timestamp, an input type, a key *class* (letter/digit/punct/
 * space/backspace/nav...), the caret position and the change in field length.
 * That is enough to reconstruct pauses, bursts, revisions and paste sizes; it is
 * not enough to reconstruct the text.
 *
 * Why `beforeinput`/`input` rather than `keydown`
 * -----------------------------------------------
 * `InputEvent.inputType` is the only reliable way to tell typing from pasting,
 * dropping, IME composition, dictation, autofill and undo. Paste, drop,
 * dictation and autofill mutate the field WITHOUT firing keydown at all, so a
 * keydown-only tracker is blind to exactly the cases this feature exists to
 * detect. `keydown`/`keyup` are still listened to, but only to count physical
 * keystrokes and measure dwell — and the gap between "characters that appeared"
 * and "keys actually pressed" is the single strongest signal we collect.
 *
 * Listeners are delegated on `document` in the capture phase because
 * annotation.js re-renders the instance DOM on every navigation; per-element
 * binding would silently stop working after the first Next click.
 *
 * See docs/advanced/keystroke_logging.md and potato/typing_dynamics.py.
 */
class KeystrokeTracker {
    constructor(config) {
        const cfg = config || {};
        this.enabled = cfg.enabled !== false;
        this.fidelity = cfg.fidelity || 'events';
        this.includeSchemas = cfg.include_schemas || [];
        this.excludeSchemas = cfg.exclude_schemas || [];
        this.classifyPaste = cfg.classify_paste_source !== false;
        this.idleSessionMs = cfg.idle_session_ms || 30000;
        this.flushIntervalMs = cfg.flush_interval_ms || 5000;
        this.onExternalInsert = cfg.on_external_insert || 'flag';
        this.maxEventsPerSession = cfg.max_events_per_session || 20000;
        this.debugMode = false;

        // Active sessions keyed by "schema:::label". A field gets a session when
        // it is focused and keeps it until blur, instance change, idle timeout
        // or unload.
        this.sessions = {};
        // Sessions that have ended and are waiting to be sent.
        this.pending = [];

        // Per-session salt so a paste hash is comparable within a session but
        // cannot be matched against a rainbow table of known text.
        this.salt = Math.floor(Math.random() * 0x7fffffff).toString(36);

        this.currentInstanceId = null;
        this.hiddenSince = null;
        this.windowBlurSince = null;
        this.isVirtualKeyboard = this._detectVirtualKeyboard();

        // Set by keydown, consumed by the next input event. If an input arrives
        // with nothing pending, no physical key produced it — that is a silent
        // insertion.
        this.pendingKey = null;
        this.keyDownAt = {};
        // Set by the paste handler, consumed by the following beforeinput.
        this.pendingPaste = null;

        if (this.enabled && this.fidelity !== 'off') {
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', () => this.init());
            } else {
                this.init();
            }
        }
    }

    init() {
        if (this.isInitialized) return;
        this.isInitialized = true;

        document.addEventListener('focusin', (e) => this.onFocusIn(e), true);
        document.addEventListener('focusout', (e) => this.onFocusOut(e), true);
        document.addEventListener('keydown', (e) => this.onKeyDown(e), true);
        document.addEventListener('keyup', (e) => this.onKeyUp(e), true);
        document.addEventListener('beforeinput', (e) => this.onBeforeInput(e), true);
        document.addEventListener('input', (e) => this.onInput(e), true);
        document.addEventListener('paste', (e) => this.onPaste(e), true);
        document.addEventListener('cut', (e) => this.onCut(e), true);
        document.addEventListener('drop', (e) => this.onDrop(e), true);
        document.addEventListener('compositionstart', (e) => this.onComposition(e, true), true);
        document.addEventListener('compositionend', (e) => this.onComposition(e, false), true);

        // Time away from the tab, which is how off-screen composition shows up.
        document.addEventListener('visibilitychange', () => this.onVisibilityChange());
        window.addEventListener('blur', () => this.onWindowBlur());
        window.addEventListener('focus', () => this.onWindowFocus());

        window.addEventListener('beforeunload', () => this.flush(true));
        window.addEventListener('pagehide', () => this.flush(true));

        this.flushTimer = setInterval(() => this.tick(), this.flushIntervalMs);

        // Both trackers must cut their sessions on the same boundary, otherwise
        // a session would straddle two instances and be attributed to whichever
        // id happened to be current at flush time.
        this._hookInstanceChange();

        if (this.debugMode) console.log('[KeystrokeTracker] Initialized');
    }

    /**
     * Wrap interactionTracker.setInstanceId so instance navigation ends every
     * open session before the id changes.
     */
    _hookInstanceChange() {
        const it = window.interactionTracker;
        if (!it || it.__keystrokeHooked) return;
        const original = it.setInstanceId.bind(it);
        const self = this;
        it.setInstanceId = function (instanceId) {
            self.endAllSessions('instance_change');
            self.currentInstanceId = instanceId;
            self.flush(false);
            return original(instanceId);
        };
        it.__keystrokeHooked = true;
        this.currentInstanceId = it.currentInstanceId;
    }

    _detectVirtualKeyboard() {
        // No reliable API exists. Soft keyboards fire `input` without a usable
        // `keydown`, which would otherwise read as silent insertion, so the
        // detector needs to know when to suppress keystroke-count heuristics.
        try {
            if (navigator.userAgentData && typeof navigator.userAgentData.mobile === 'boolean') {
                return navigator.userAgentData.mobile;
            }
        } catch (e) { /* userAgentData unavailable */ }
        return /Mobi|Android|iPhone|iPad|iPod|Tablet/i.test(navigator.userAgent || '');
    }

    // ---------------------------------------------------------------
    // Field identification
    // ---------------------------------------------------------------

    /**
     * Decide whether an element is a free-text annotation field we should log,
     * and return its identity.
     *
     * Identity comes from the `schema` / `label_name` attributes that
     * generate_element_identifier() stamps on every annotation input
     * (server_utils/schemas/identifier_utils.py), so this works uniformly for
     * the `text` schema, free-response boxes inside radio/multiselect, and the
     * rationale/notes textareas in text_edit, pairwise, trajectory_eval etc.
     *
     * @returns {{key: string, schema: string, label: string}|null}
     */
    getFieldIdentity(element) {
        if (!element || !element.tagName) return null;

        const tag = element.tagName.toLowerCase();
        const type = (element.getAttribute('type') || 'text').toLowerCase();
        if (tag !== 'textarea' && !(tag === 'input' && type === 'text')) return null;

        // Never log credential-like fields, whatever else they match.
        if (type === 'password' || element.autocomplete === 'current-password') return null;
        if (element.dataset && element.dataset.keystrokeLogging === 'off') return null;

        let schema = element.getAttribute('schema');
        let label = element.getAttribute('label_name');

        if (!schema || !label) {
            const name = element.getAttribute('name') || '';
            if (name.indexOf(':::') !== -1) {
                const parts = name.split(':::');
                schema = schema || parts[0];
                label = label || parts[1];
            }
        }
        if (!schema) {
            // Free-text controls that write into a hidden blob (text_edit's
            // editor, pairwise rationale) carry the schema on an ancestor form.
            const form = element.closest('[data-schema-name]');
            if (form) {
                schema = form.dataset.schemaName;
                label = label || element.id || tag;
            }
        }
        if (!schema || !label) return null;

        if (this.excludeSchemas.length && this.excludeSchemas.indexOf(schema) !== -1) return null;
        if (this.includeSchemas.length && this.includeSchemas.indexOf(schema) === -1) return null;

        return { key: schema + ':::' + label, schema: schema, label: label };
    }

    // ---------------------------------------------------------------
    // Classification helpers (pure — exported for unit testing)
    // ---------------------------------------------------------------

    /**
     * Map a KeyboardEvent key to a content-blind class.
     * The key itself is never recorded, only which family it belongs to.
     */
    classifyKey(key) {
        if (!key) return 'unknown';
        if (key.length === 1) {
            if (key === ' ') return 'space';
            if (key >= '0' && key <= '9') return 'digit';
            if (/[a-z]/i.test(key) || key.charCodeAt(0) > 127) return 'letter';
            return 'punct';
        }
        switch (key) {
            case 'Enter': return 'enter';
            case 'Backspace': return 'bksp';
            case 'Delete': return 'del';
            case 'ArrowLeft': case 'ArrowRight': case 'ArrowUp': case 'ArrowDown':
            case 'Home': case 'End': case 'PageUp': case 'PageDown':
                return 'nav';
            case 'Shift': case 'Control': case 'Alt': case 'Meta':
            case 'CapsLock': case 'AltGraph':
                return 'mod';
            case 'Tab': case 'Escape':
                return 'func';
            default:
                return /^F\d+$/.test(key) ? 'func' : 'unknown';
        }
    }

    /** Normalize an inputType to the vocabulary the server knows. */
    classifyInputType(inputType) {
        const known = [
            'insertText', 'insertReplacementText', 'insertFromPaste',
            'insertFromDrop', 'insertCompositionText', 'insertLineBreak',
            'insertParagraph', 'deleteContentBackward', 'deleteContentForward',
            'deleteWordBackward', 'deleteWordForward', 'deleteByCut',
            'deleteByDrag', 'historyUndo', 'historyRedo',
        ];
        return known.indexOf(inputType) !== -1 ? inputType : 'other';
    }

    /**
     * Where did pasted text come from?
     *
     * Only the resulting label is kept — never the pasted text. `self` and
     * `instance_text` are legitimate (quoting the passage, moving your own
     * draft); `external` is the one that matters.
     *
     * @returns {'self'|'instance_text'|'ai_suggestion'|'external'|'unknown'}
     */
    classifyPasteSource(text, fieldValue) {
        if (!this.classifyPaste || !text) return 'unknown';
        const norm = (s) => (s || '').toLowerCase().replace(/\s+/g, ' ').trim();
        const needle = norm(text);
        // Very short pastes are not reliably attributable.
        if (needle.length < 12) return 'unknown';

        if (norm(fieldValue).indexOf(needle) !== -1) return 'self';

        const collect = (selector) => {
            let out = '';
            document.querySelectorAll(selector).forEach((el) => {
                out += ' ' + (el.innerText || el.textContent || '');
            });
            return norm(out);
        };

        try {
            if (collect('.ai-suggestion, .ai-assistant-panel, .ai-suggestion-text')
                    .indexOf(needle) !== -1) {
                return 'ai_suggestion';
            }
            if (collect('#instance-text, .instance-text, #instance, .instance-display')
                    .indexOf(needle) !== -1) {
                return 'instance_text';
            }
        } catch (e) { /* selector unsupported in this DOM */ }

        return 'external';
    }

    /**
     * Short salted hash. Lets an analyst see that the same text was pasted into
     * several fields or by several annotators without any way to recover it.
     */
    hashText(text) {
        const input = this.salt + '|' + (text || '');
        let h = 0x811c9dc5;
        for (let i = 0; i < input.length; i++) {
            h ^= input.charCodeAt(i);
            h = (h + ((h << 1) + (h << 4) + (h << 7) + (h << 8) + (h << 24))) >>> 0;
        }
        return h.toString(36);
    }

    // ---------------------------------------------------------------
    // Session lifecycle
    // ---------------------------------------------------------------

    getSession(element, identity) {
        const existing = this.sessions[identity.key];
        if (existing) return existing;
        const session = {
            key: identity.key,
            schema: identity.schema,
            label: identity.label,
            instanceId: this.currentInstanceId,
            startedAt: Date.now(),
            lastActivity: Date.now(),
            events: [],
            prevLength: (element.value || '').length,
            startLength: (element.value || '').length,
            compositions: 0,
            truncated: false,
        };
        this.sessions[identity.key] = session;
        this.addEvent(session, { input_type: 'focus', pos: 0, delta: 0 });
        return session;
    }

    addEvent(session, event) {
        if (!session) return;
        if (session.events.length >= this.maxEventsPerSession) {
            // Guard against a pathological page; recorded rather than silent so
            // an analyst can see the stream is incomplete.
            session.truncated = true;
            return;
        }
        session.events.push({
            t_ms: Date.now() - session.startedAt,
            input_type: event.input_type || 'other',
            key_class: event.key_class || 'unknown',
            pos: event.pos || 0,
            delta: event.delta || 0,
            meta: event.meta || {},
        });
        session.lastActivity = Date.now();
    }

    endSession(key, reason) {
        const session = this.sessions[key];
        if (!session) return;
        delete this.sessions[key];
        session.endedAt = Date.now();
        session.endReason = reason;
        // A session with nothing but the synthetic focus event says nothing.
        if (session.events.length <= 1 && session.finalLength === session.startLength) {
            return;
        }
        this.pending.push(session);
    }

    endAllSessions(reason) {
        Object.keys(this.sessions).forEach((key) => {
            // prevLength is maintained on every input event, so it is the last
            // observed field length. Re-querying the DOM here would be wrong:
            // annotation.js clears the inputs as part of switching instances,
            // so by the time this runs the element may already read empty.
            this.sessions[key].finalLength = this.sessions[key].prevLength;
            this.endSession(key, reason);
        });
    }

    /** Periodic housekeeping: close idle sessions, then send whatever is due. */
    tick() {
        const now = Date.now();
        Object.keys(this.sessions).forEach((key) => {
            const s = this.sessions[key];
            if (now - s.lastActivity > this.idleSessionMs) {
                s.finalLength = s.prevLength;
                this.endSession(key, 'idle');
            }
        });
        this.flush(false);
    }

    // ---------------------------------------------------------------
    // Event handlers
    // ---------------------------------------------------------------

    onFocusIn(e) {
        const identity = this.getFieldIdentity(e.target);
        if (!identity) return;
        this.getSession(e.target, identity);
    }

    onFocusOut(e) {
        const identity = this.getFieldIdentity(e.target);
        if (!identity) return;
        const session = this.sessions[identity.key];
        if (session) {
            session.finalLength = (e.target.value || '').length;
            this.endSession(identity.key, 'blur');
        }
        this.flush(false);
    }

    onKeyDown(e) {
        const identity = this.getFieldIdentity(e.target);
        if (!identity) return;
        const cls = this.classifyKey(e.key);
        this.keyDownAt[e.key] = Date.now();
        // Held for the input event that this keystroke is about to produce.
        this.pendingKey = { cls: cls, at: Date.now(), trusted: e.isTrusted };

        // Keys that never produce an input event still matter: navigation is how
        // a writer moves back into the text to revise.
        if (cls === 'nav') {
            const session = this.sessions[identity.key];
            if (session) {
                this.addEvent(session, {
                    input_type: 'keydown',
                    key_class: cls,
                    pos: e.target.selectionStart || 0,
                    delta: 0,
                });
            }
            this.pendingKey = null;
        }
    }

    onKeyUp(e) {
        const down = this.keyDownAt[e.key];
        if (down) {
            this.lastDwellMs = Date.now() - down;
            delete this.keyDownAt[e.key];
        }
    }

    onBeforeInput(e) {
        const identity = this.getFieldIdentity(e.target);
        if (!identity) return;

        // Caret position must be read here: after the mutation, selectionStart
        // has already moved past the inserted text.
        this.pendingBefore = {
            key: identity.key,
            pos: e.target.selectionStart || 0,
            inputType: e.inputType,
            trusted: e.isTrusted,
        };

        if (this.onExternalInsert === 'block' &&
            (e.inputType === 'insertFromPaste' || e.inputType === 'insertFromDrop')) {
            e.preventDefault();
            this._notifyBlocked(e.target);
        }
    }

    onInput(e) {
        const identity = this.getFieldIdentity(e.target);
        if (!identity) return;
        const session = this.getSession(e.target, identity);

        const newLength = (e.target.value || '').length;
        const delta = newLength - session.prevLength;
        session.prevLength = newLength;

        const before = (this.pendingBefore && this.pendingBefore.key === identity.key)
            ? this.pendingBefore : null;
        this.pendingBefore = null;

        const inputType = this.classifyInputType(
            (before && before.inputType) || e.inputType || 'other'
        );

        // The key class is only claimed if a keydown fired moments ago. When
        // text appears with no recent keydown, key_class stays "unknown" and the
        // server counts it as a silent insertion — which is the whole point.
        let keyClass = 'unknown';
        if (this.pendingKey && (Date.now() - this.pendingKey.at) < 250) {
            keyClass = this.pendingKey.cls;
        }
        this.pendingKey = null;

        const meta = {};
        const trusted = (before ? before.trusted : e.isTrusted);
        if (trusted === false) meta.is_trusted = false;
        if (this.lastDwellMs) { meta.dwell_ms = this.lastDwellMs; this.lastDwellMs = null; }

        if (inputType === 'insertFromPaste' && this.pendingPaste) {
            meta.paste_source = this.pendingPaste.source;
            meta.paste_hash = this.pendingPaste.hash;
            this.pendingPaste = null;
        }
        if (inputType === 'insertCompositionText') {
            meta.composing = true;
            session.compositions += 1;
        }

        this.addEvent(session, {
            input_type: inputType,
            key_class: keyClass,
            pos: before ? before.pos : (e.target.selectionStart || 0),
            delta: delta,
            meta: meta,
        });
    }

    onPaste(e) {
        const identity = this.getFieldIdentity(e.target);
        if (!identity) return;
        let text = '';
        try {
            text = (e.clipboardData || window.clipboardData).getData('text') || '';
        } catch (err) { /* clipboard unreadable; length stays 0 */ }

        // Classified here, while the clipboard is still readable. Only the label
        // and hash survive — the text is never stored or transmitted.
        this.pendingPaste = {
            source: this.classifyPasteSource(text, e.target.value),
            hash: text ? this.hashText(text) : null,
            length: text.length,
        };

        if (this.onExternalInsert === 'warn') {
            this._notifyWarn(e.target, this.pendingPaste);
        }
    }

    onCut(e) {
        const identity = this.getFieldIdentity(e.target);
        if (!identity) return;
        const session = this.sessions[identity.key];
        if (session) {
            this.addEvent(session, {
                input_type: 'deleteByCut',
                pos: e.target.selectionStart || 0,
                delta: 0,
            });
        }
    }

    onDrop(e) {
        const identity = this.getFieldIdentity(e.target);
        if (!identity) return;
        this.pendingPaste = { source: 'external', hash: null, length: 0 };
    }

    onComposition(e, starting) {
        const identity = this.getFieldIdentity(e.target);
        if (!identity) return;
        const session = this.sessions[identity.key];
        if (session && !starting) session.compositions += 1;
    }

    onVisibilityChange() {
        if (document.hidden) {
            this.hiddenSince = Date.now();
        } else if (this.hiddenSince) {
            this._recordAway(Date.now() - this.hiddenSince);
            this.hiddenSince = null;
        }
    }

    onWindowBlur() {
        if (this.windowBlurSince === null) this.windowBlurSince = Date.now();
    }

    onWindowFocus() {
        if (this.windowBlurSince !== null) {
            // Only count it if visibilitychange did not already record this gap;
            // switching tabs fires both, switching applications fires only blur.
            if (this.hiddenSince === null) {
                this._recordAway(Date.now() - this.windowBlurSince);
            }
            this.windowBlurSince = null;
        }
    }

    /**
     * Attribute time away to every open session. The server pairs it with the
     * next insertion, which is what makes "left the tab, came back, pasted a
     * paragraph" visible.
     */
    _recordAway(durationMs) {
        if (durationMs < 1000) return;
        Object.keys(this.sessions).forEach((key) => {
            this.addEvent(this.sessions[key], {
                input_type: 'blur',
                pos: 0,
                delta: 0,
                meta: { blur_ms: durationMs },
            });
        });
    }

    _notifyWarn(element, paste) {
        if (paste && (paste.source === 'self' || paste.source === 'instance_text')) return;
        if (typeof window.showToast === 'function') {
            window.showToast('This response is being recorded as pasted rather than typed.');
        } else if (this.debugMode) {
            console.log('[KeystrokeTracker] paste warning', paste);
        }
    }

    _notifyBlocked(element) {
        if (typeof window.showToast === 'function') {
            window.showToast('Pasting is disabled for this field. Please type your response.');
        }
    }

    // ---------------------------------------------------------------
    // Transport
    // ---------------------------------------------------------------

    /**
     * Send completed sessions to the server.
     * @param {boolean} isFinal - page is going away; use sendBeacon
     */
    flush(isFinal) {
        if (isFinal) {
            // Close everything still open so an unload does not lose the
            // session the annotator was in the middle of.
            Object.keys(this.sessions).forEach((key) => {
                this.sessions[key].finalLength = this.sessions[key].prevLength;
                this.endSession(key, 'unload');
            });
        }
        if (!this.pending.length) return;

        const sessions = this.pending.map((s) => ({
            schema_name: s.schema,
            label_name: s.label,
            instance_id: s.instanceId || this.currentInstanceId,
            started_at: s.startedAt / 1000,
            ended_at: (s.endedAt || Date.now()) / 1000,
            final_chars: (s.finalLength !== undefined ? s.finalLength : s.prevLength),
            start_chars: s.startLength,
            end_reason: s.endReason,
            truncated: s.truncated,
            virtual_keyboard: this.isVirtualKeyboard,
            events: s.events,
        }));
        this.pending = [];

        const payload = JSON.stringify({
            instance_id: this.currentInstanceId,
            sessions: sessions,
        });

        if (this.debugMode) console.log('[KeystrokeTracker] Flushing', sessions);

        if (isFinal) {
            const blob = new Blob([payload], { type: 'application/json' });
            navigator.sendBeacon('/api/track_typing', blob);
        } else {
            fetch('/api/track_typing', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: payload,
            }).catch((e) => {
                if (this.debugMode) {
                    console.warn('[KeystrokeTracker] Failed to send typing data:', e);
                }
            });
        }
    }

    setDebugMode(enabled) {
        this.debugMode = enabled;
        console.log(`[KeystrokeTracker] Debug mode: ${enabled ? 'enabled' : 'disabled'}`);
    }

    destroy() {
        if (this.flushTimer) clearInterval(this.flushTimer);
        this.flush(true);
    }
}

// Config is injected by base_template_v2.html from the server-side
// `keystroke_logging` block; absent config means the feature is off.
window.keystrokeTracker = new KeystrokeTracker(window.keystrokeConfig || { enabled: false });
window.KeystrokeTracker = KeystrokeTracker;

/**
 * Annotation Telemetry - content-blind drawing dynamics for geometry schemas.
 *
 * Records HOW an annotation was produced, never WHAT was drawn. Each event
 * carries a timestamp, an action, a geometry kind and one integer of context.
 * That is enough to reconstruct pace, revision, inspection and AI-accept
 * latency; it is not enough to reconstruct a single coordinate.
 *
 * Why this listens rather than being called
 * -----------------------------------------
 * The annotation managers dispatch a `potato:annotation-telemetry` CustomEvent
 * and know nothing else about this file. That decoupling is the point:
 *
 *   - telemetry can be switched off, or fail to load entirely, and every
 *     drawing tool keeps working;
 *   - video, span and future modalities join by emitting the same event, with
 *     no changes here;
 *   - both sides are testable in isolation — the emitter against a recorded
 *     event list, this file against a synthetic one.
 *
 * The alternative, calling a global from twenty places inside
 * image-annotation.js, is how `segmentation-tools.js` became 319 lines of dead
 * code that still loaded on every page.
 *
 * See docs/administration/annotation_telemetry.md and
 * potato/annotation_telemetry.py.
 */
class AnnotationTelemetryTracker {
    constructor(config) {
        const cfg = config || {};
        this.enabled = cfg.enabled === true;
        this.fidelity = cfg.fidelity || 'events';
        this.includeSchemas = cfg.include_schemas || [];
        this.excludeSchemas = cfg.exclude_schemas || [];
        this.flushIntervalMs = cfg.flush_interval_ms || 10000;
        // A hard ceiling so a stuck mousemove loop cannot grow the buffer
        // without bound. Truncation is recorded, never silent.
        this.maxEventsPerSession = cfg.max_events_per_session || 20000;
        this.debugMode = false;

        // Open sessions keyed by schema name. A schema gets a session on its
        // first event and keeps it until instance change or unload.
        this.sessions = {};
        // Sessions that have ended and are waiting to be sent.
        this.pending = [];

        this.currentInstanceId = null;

        if (this.enabled && this.fidelity !== 'off') {
            this.init();
        }
    }

    init() {
        document.addEventListener(
            'potato:annotation-telemetry', (e) => this.onTelemetry(e));

        window.addEventListener('beforeunload', () => this.flush(true));
        window.addEventListener('pagehide', () => this.flush(true));

        this.flushTimer = setInterval(() => this.flush(false), this.flushIntervalMs);

        // Both behavioural trackers must cut their sessions on the same
        // boundary, otherwise a session straddles two instances and is
        // attributed to whichever id happened to be current at flush time.
        this._hookInstanceChange();

        if (this.debugMode) console.log('[AnnotationTelemetry] Initialized');
    }

    /**
     * Wrap interactionTracker.setInstanceId so instance navigation ends every
     * open session before the id changes.
     */
    _hookInstanceChange() {
        const it = window.interactionTracker;
        if (!it || it.__telemetryHooked) return;
        const original = it.setInstanceId.bind(it);
        const self = this;
        it.setInstanceId = function (instanceId) {
            self.endAllSessions('instance_change');
            self.currentInstanceId = instanceId;
            self.flush(false);
            return original(instanceId);
        };
        it.__telemetryHooked = true;
        this.currentInstanceId = it.currentInstanceId;
    }

    /**
     * Whether a schema is in scope. `include_schemas` is a whitelist when
     * non-empty; `exclude_schemas` always wins.
     */
    tracks(schema) {
        if (!schema) return false;
        if (this.excludeSchemas.indexOf(schema) !== -1) return false;
        if (this.includeSchemas.length &&
            this.includeSchemas.indexOf(schema) === -1) return false;
        return true;
    }

    onTelemetry(e) {
        const d = (e && e.detail) || {};
        if (!this.tracks(d.schema)) return;
        if (!d.action) return;

        const session = this._session(d.schema);
        if (session.events.length >= this.maxEventsPerSession) {
            session.truncated = true;
            return;
        }

        const event = {
            t_ms: Math.max(0, Math.round(Date.now() - session.startedAt)),
            action: String(d.action),
            shape: d.shape ? String(d.shape) : 'unknown',
            // Rounded here rather than server-side: the wire format is integers,
            // and a float would be silently truncated by the packer instead of
            // rounded, biasing every zoom level down.
            value: Math.round(Number(d.value) || 0),
        };
        if (d.meta && typeof d.meta === 'object') event.meta = d.meta;

        session.events.push(event);
        session.lastAt = Date.now();
    }

    _session(schema) {
        if (!this.sessions[schema]) {
            const now = Date.now();
            this.sessions[schema] = {
                schema: schema,
                // Captured at session start, NOT at flush: the instance may
                // have changed by then, and this is the id the work belongs to.
                instanceId: this.currentInstanceId,
                startedAt: now,
                lastAt: now,
                truncated: false,
                events: [],
            };
        }
        return this.sessions[schema];
    }

    endSession(schema, reason) {
        const session = this.sessions[schema];
        if (!session) return;
        delete this.sessions[schema];
        // A session with no events is not worth a row; it just means the
        // annotator opened an image and moved on.
        if (!session.events.length) return;
        session.endedAt = session.lastAt;
        session.endReason = reason;
        this.pending.push(session);
    }

    endAllSessions(reason) {
        Object.keys(this.sessions).forEach((schema) => {
            this.endSession(schema, reason);
        });
    }

    /**
     * Send completed sessions to the server.
     * @param {boolean} isFinal - page is going away; use sendBeacon
     */
    flush(isFinal) {
        if (isFinal) {
            // Close everything still open so an unload does not lose the
            // session the annotator was in the middle of.
            this.endAllSessions('unload');
        }
        if (!this.pending.length) return;

        const sessions = this.pending.map((s) => ({
            schema_name: s.schema,
            instance_id: s.instanceId || this.currentInstanceId,
            started_at: s.startedAt / 1000,
            ended_at: (s.endedAt || Date.now()) / 1000,
            end_reason: s.endReason,
            truncated: s.truncated,
            events: s.events,
        }));
        this.pending = [];

        const payload = JSON.stringify({
            instance_id: this.currentInstanceId,
            sessions: sessions,
        });

        if (this.debugMode) console.log('[AnnotationTelemetry] Flushing', sessions);

        if (isFinal) {
            const blob = new Blob([payload], { type: 'application/json' });
            navigator.sendBeacon('/api/track_annotation_telemetry', blob);
        } else {
            fetch('/api/track_annotation_telemetry', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: payload,
            }).catch((e) => {
                if (this.debugMode) {
                    console.warn('[AnnotationTelemetry] Failed to send:', e);
                }
            });
        }
    }

    setDebugMode(enabled) {
        this.debugMode = enabled;
        console.log(`[AnnotationTelemetry] Debug mode: ${enabled ? 'enabled' : 'disabled'}`);
    }

    destroy() {
        if (this.flushTimer) clearInterval(this.flushTimer);
        this.flush(true);
    }
}

/**
 * The emitter side, exposed globally so any modality can report an interaction
 * without importing anything or checking whether telemetry is switched on.
 *
 * Dispatching unconditionally is deliberate. The cost of an unheard CustomEvent
 * is negligible, and gating the emit on a global that may not have loaded yet
 * is exactly the kind of ordering dependency that makes a feature work in
 * development and silently do nothing in production.
 */
window.recordAnnotationTelemetry = function (schema, action, detail) {
    if (!schema || !action) return;
    try {
        const d = detail || {};
        document.dispatchEvent(new CustomEvent('potato:annotation-telemetry', {
            detail: {
                schema: schema,
                action: action,
                shape: d.shape,
                value: d.value,
                meta: d.meta,
            },
        }));
    } catch (e) {
        // Telemetry must never break annotation, so an environment without a
        // working CustomEvent constructor loses the measurement and nothing
        // else.
        //
        // This does NOT catch a listener that throws: per the DOM spec an
        // exception inside a listener is *reported*, not propagated back to
        // dispatchEvent's caller, so it never reaches here. That isolation is
        // the platform's guarantee rather than this try/catch's, and saying
        // otherwise would credit this block with a protection it does not
        // provide.
    }
};

// Config is injected by base_template_v2.html from the server-side
// `annotation_telemetry` block; absent config means the feature is off.
window.annotationTelemetryTracker = new AnnotationTelemetryTracker(
    window.annotationTelemetryConfig || { enabled: false });
window.AnnotationTelemetryTracker = AnnotationTelemetryTracker;

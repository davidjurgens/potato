/**
 * Interaction Tracker - Captures user interactions for behavioral analysis
 *
 * This module tracks user interactions with the annotation interface including:
 * - Clicks on annotation elements
 * - Focus changes between elements
 * - Scroll depth
 * - Keyboard shortcuts
 * - Navigation events
 * - AI assistance usage
 * - Annotation changes
 *
 * Events are batched and sent periodically to minimize network overhead.
 * Uses sendBeacon API for reliable delivery on page unload.
 */
class InteractionTracker {
    constructor() {
        this.events = [];
        this.focusStartTime = {};
        this.focusTime = {};
        this.scrollDepthMax = 0;
        this.currentInstanceId = null;
        this.previousInstanceId = null;
        this.flushInterval = 5000; // Flush every 5 seconds
        this.lastFlush = Date.now();
        this.isInitialized = false;
        this.debugMode = false;

        // Don't auto-init - wait for explicit init call or DOMContentLoaded
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => this.init());
        } else {
            this.init();
        }
    }

    init() {
        if (this.isInitialized) return;
        this.isInitialized = true;

        // Track clicks on annotation elements
        document.addEventListener('click', (e) => this.trackClick(e), true);

        // Track focus changes
        document.addEventListener('focusin', (e) => this.trackFocusIn(e), true);
        document.addEventListener('focusout', (e) => this.trackFocusOut(e), true);

        // Track scroll depth
        window.addEventListener('scroll', () => this.trackScroll(), { passive: true });

        // Track keyboard shortcuts
        document.addEventListener('keydown', (e) => this.trackKeypress(e), true);

        // Flush on page unload
        window.addEventListener('beforeunload', () => this.flush(true));
        window.addEventListener('pagehide', () => this.flush(true));

        // Periodic flush
        this.flushTimer = setInterval(() => this.flush(false), this.flushInterval);

        if (this.debugMode) {
            console.log('[InteractionTracker] Initialized');
        }
    }

    /**
     * Set the current instance ID and notify about navigation
     * @param {string} instanceId - The new instance ID
     */
    setInstanceId(instanceId) {
        if (this.debugMode) {
            console.log(`[InteractionTracker] setInstanceId: ${instanceId}`);
        }

        // Flush events for previous instance
        if (this.currentInstanceId && this.currentInstanceId !== instanceId) {
            this.flush(true);
        }

        this.previousInstanceId = this.currentInstanceId;
        this.currentInstanceId = instanceId;

        // Reset scroll depth for new instance
        this.scrollDepthMax = 0;

        this.addEvent('navigation', 'instance_load', {
            instance_id: instanceId,
            from_instance: this.previousInstanceId
        });
    }

    /**
     * Track click events
     * @param {Event} e - Click event
     */
    trackClick(e) {
        const target = this.getTargetIdentifier(e.target);
        if (target) {
            this.addEvent('click', target, {
                x: e.clientX,
                y: e.clientY,
            });
        }
    }

    /**
     * Track focus entering an element
     * @param {Event} e - Focus event
     */
    trackFocusIn(e) {
        const target = this.getTargetIdentifier(e.target);
        if (target) {
            this.focusStartTime[target] = Date.now();
            this.addEvent('focus_in', target);
        }
    }

    /**
     * Track focus leaving an element
     * @param {Event} e - Focus event
     */
    trackFocusOut(e) {
        const target = this.getTargetIdentifier(e.target);
        if (target && this.focusStartTime[target]) {
            const duration = Date.now() - this.focusStartTime[target];
            this.focusTime[target] = (this.focusTime[target] || 0) + duration;
            delete this.focusStartTime[target];
            this.addEvent('focus_out', target, { duration_ms: duration });
        }
    }

    /**
     * Track scroll depth
     */
    trackScroll() {
        const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
        const scrollHeight = document.documentElement.scrollHeight - window.innerHeight;
        const scrollPercent = scrollHeight > 0 ? (scrollTop / scrollHeight) * 100 : 0;
        this.scrollDepthMax = Math.max(this.scrollDepthMax, scrollPercent);
    }

    /**
     * Track keyboard shortcuts
     * @param {Event} e - Keydown event
     */
    trackKeypress(e) {
        // Track annotation-related keypresses (number keys for keybindings)
        if (e.key >= '0' && e.key <= '9') {
            this.addEvent('keypress', `key:${e.key}`, {
                ctrl: e.ctrlKey,
                alt: e.altKey,
                shift: e.shiftKey,
            });
        }

        // Track navigation shortcuts
        if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
            this.addEvent('keypress', `nav:${e.key}`, {
                ctrl: e.ctrlKey,
                alt: e.altKey,
            });
        }

        // Track save shortcut (Ctrl/Cmd + S)
        if ((e.ctrlKey || e.metaKey) && e.key === 's') {
            this.addEvent('keypress', 'save:shortcut');
        }
    }

    /**
     * Track AI assistance request
     * @param {string} schemaName - The schema requesting AI help
     */
    trackAIRequest(schemaName) {
        this.addEvent('ai_request', `schema:${schemaName}`);

        // Also track via dedicated AI endpoint
        this.sendAIUsage('request', schemaName);
    }

    /**
     * Track AI assistance response
     * @param {string} schemaName - The schema that received help
     * @param {Array} suggestions - AI suggestions provided
     */
    trackAIResponse(schemaName, suggestions) {
        this.addEvent('ai_response', `schema:${schemaName}`, {
            suggestion_count: suggestions ? suggestions.length : 0,
            suggestions: suggestions
        });

        this.sendAIUsage('response', schemaName, { suggestions });
    }

    /**
     * Track user accepting AI suggestion
     * @param {string} schemaName - The schema
     * @param {string} acceptedValue - The value accepted
     */
    trackAIAccept(schemaName, acceptedValue) {
        this.addEvent('ai_accept', `schema:${schemaName}`, {
            accepted: acceptedValue
        });

        this.sendAIUsage('accept', schemaName, { accepted_value: acceptedValue });
    }

    /**
     * Track user rejecting AI suggestion
     * @param {string} schemaName - The schema
     */
    trackAIReject(schemaName) {
        this.addEvent('ai_reject', `schema:${schemaName}`);

        this.sendAIUsage('reject', schemaName);
    }

    /**
     * Track annotation change
     * @param {string} schemaName - Schema name
     * @param {string} labelName - Label name
     * @param {string} action - Action type (select, deselect, update, clear)
     * @param {*} oldValue - Previous value
     * @param {*} newValue - New value
     * @param {string} source - What triggered the change (user, ai_accept, keyboard, prefill)
     */
    trackAnnotationChange(schemaName, labelName, action, oldValue, newValue, source = 'user') {
        this.addEvent('annotation_change', `schema:${schemaName}`, {
            label: labelName,
            action: action,
            old_value: oldValue,
            new_value: newValue,
            source: source,
        });

        // Also send to dedicated annotation change endpoint for persistence
        this.sendAnnotationChange(schemaName, labelName, action, oldValue, newValue, source);
    }

    /**
     * Track navigation between instances
     * @param {string} action - Navigation action (next, prev, jump)
     * @param {string} fromInstance - Previous instance ID
     * @param {string} toInstance - New instance ID
     */
    trackNavigation(action, fromInstance, toInstance) {
        this.addEvent('navigation', action, {
            from_instance: fromInstance,
            to_instance: toInstance,
        });
    }

    /**
     * Track save action
     * @param {string} instanceId - Instance being saved
     */
    trackSave(instanceId) {
        this.addEvent('save', `instance:${instanceId || this.currentInstanceId}`);
    }

    /**
     * Track when an annotation becomes stale due to display logic changes.
     * Stale annotations are annotations for schemas that were hidden because
     * conditions changed (e.g., user changed a parent answer).
     *
     * @param {string} schemaName - Schema that became stale
     * @param {*} value - The value that is now stale
     * @param {string} reason - Why the schema became hidden (condition not met)
     */
    trackStaleAnnotation(schemaName, value, reason) {
        this.addEvent('annotation_stale', `schema:${schemaName}`, {
            stale_value: value,
            reason: reason,
            timestamp: new Date().toISOString()
        });
    }

    /**
     * Track display logic visibility changes.
     * @param {string} schemaName - Schema whose visibility changed
     * @param {boolean} visible - New visibility state
     * @param {string} reason - Reason for visibility change
     */
    trackDisplayLogicChange(schemaName, visible, reason) {
        this.addEvent('display_logic_change', `schema:${schemaName}`, {
            visible: visible,
            reason: reason,
            timestamp: new Date().toISOString()
        });
    }

    /**
     * Get a unique identifier for an element
     * @param {Element} element - DOM element
     * @returns {string|null} - Element identifier or null
     */
    getTargetIdentifier(element) {
        if (!element || !element.closest) return null;

        // Check for annotation labels (checkbox/radio inputs or their labels)
        const labelInput = element.closest('input[type="checkbox"], input[type="radio"]');
        if (labelInput) {
            const name = labelInput.name || '';
            const value = labelInput.value || '';
            if (name) {
                return `label:${name}:${value}`;
            }
        }

        // Check for label wrapper with data attributes
        const labelWrapper = element.closest('[data-label-name]');
        if (labelWrapper) {
            return `label:${labelWrapper.dataset.labelName}`;
        }

        // Check for schema elements
        const schema = element.closest('[data-schema-name]');
        if (schema) {
            return `schema:${schema.dataset.schemaName}`;
        }

        // Check for annotation schema containers
        const schemaContainer = element.closest('.annotation-schema');
        if (schemaContainer) {
            const schemaName = schemaContainer.id || schemaContainer.dataset.schema;
            if (schemaName) {
                return `schema:${schemaName}`;
            }
        }

        // Check for navigation buttons
        if (element.id === 'next_instance_button' || element.closest('#next_instance_button')) {
            return 'nav:next';
        }
        if (element.id === 'prev_instance_button' || element.closest('#prev_instance_button')) {
            return 'nav:prev';
        }
        if (element.id === 'save_button' || element.closest('#save_button')) {
            return 'nav:save';
        }

        // Check for AI assistant elements
        if (element.closest('.ai-assistant-button')) return 'ai:request';
        if (element.closest('.ai-suggestion')) return 'ai:suggestion';
        if (element.closest('.ai-assistant-panel')) return 'ai:panel';

        // Check for span annotation
        if (element.closest('.annotation-span')) return 'span:click';
        if (element.closest('.span-label-option')) return 'span:label';

        // Check for text inputs (textbox schemas)
        const textInput = element.closest('input[type="text"], textarea');
        if (textInput && textInput.name) {
            return `textbox:${textInput.name}`;
        }

        // Check for slider elements
        const slider = element.closest('input[type="range"]');
        if (slider && slider.name) {
            return `slider:${slider.name}`;
        }

        return null;
    }

    /**
     * Add an event to the queue
     * @param {string} eventType - Type of event
     * @param {string} target - Target identifier
     * @param {Object} metadata - Additional metadata
     */
    addEvent(eventType, target, metadata = {}) {
        const event = {
            event_type: eventType,
            timestamp: Date.now() / 1000,  // Unix timestamp in seconds
            client_timestamp: Date.now(),   // Milliseconds for latency analysis
            target: target,
            instance_id: this.currentInstanceId,
            metadata: metadata,
        };

        this.events.push(event);

        if (this.debugMode) {
            console.log('[InteractionTracker] Event:', event);
        }

        // Auto-flush if buffer is large
        if (this.events.length >= 50) {
            this.flush(false);
        }
    }

    /**
     * Flush events to the server
     * @param {boolean} isFinal - Whether this is a final flush (page unload)
     */
    async flush(isFinal) {
        if (this.events.length === 0 && Object.keys(this.focusTime).length === 0) {
            return;
        }

        const payload = {
            instance_id: this.currentInstanceId,
            events: [...this.events],
            focus_time: { ...this.focusTime },
            scroll_depth: this.scrollDepthMax,
        };

        // Clear local buffers
        this.events = [];
        this.focusTime = {};

        if (this.debugMode) {
            console.log('[InteractionTracker] Flushing:', payload);
        }

        if (isFinal) {
            // Use sendBeacon for reliable delivery on page unload
            const blob = new Blob([JSON.stringify(payload)], { type: 'application/json' });
            navigator.sendBeacon('/api/track_interactions', blob);
        } else {
            try {
                await fetch('/api/track_interactions', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
            } catch (e) {
                if (this.debugMode) {
                    console.warn('[InteractionTracker] Failed to send interaction data:', e);
                }
            }
        }

        this.lastFlush = Date.now();
    }

    /**
     * Send AI usage event to dedicated endpoint
     * @param {string} eventType - Event type
     * @param {string} schemaName - Schema name
     * @param {Object} data - Additional data
     */
    async sendAIUsage(eventType, schemaName, data = {}) {
        try {
            await fetch('/api/track_ai_usage', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    instance_id: this.currentInstanceId,
                    schema_name: schemaName,
                    event_type: eventType,
                    ...data,
                }),
            });
        } catch (e) {
            if (this.debugMode) {
                console.warn('[InteractionTracker] Failed to send AI usage data:', e);
            }
        }
    }

    /**
     * Send annotation change to dedicated endpoint
     */
    async sendAnnotationChange(schemaName, labelName, action, oldValue, newValue, source) {
        try {
            await fetch('/api/track_annotation_change', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    instance_id: this.currentInstanceId,
                    schema_name: schemaName,
                    label_name: labelName,
                    action: action,
                    old_value: oldValue,
                    new_value: newValue,
                    source: source,
                }),
            });
        } catch (e) {
            if (this.debugMode) {
                console.warn('[InteractionTracker] Failed to send annotation change:', e);
            }
        }
    }

    /**
     * Enable or disable debug mode
     * @param {boolean} enabled - Whether debug mode is enabled
     */
    setDebugMode(enabled) {
        this.debugMode = enabled;
        console.log(`[InteractionTracker] Debug mode: ${enabled ? 'enabled' : 'disabled'}`);
    }

    /**
     * Clean up tracker resources
     */
    destroy() {
        if (this.flushTimer) {
            clearInterval(this.flushTimer);
        }
        this.flush(true);
    }
}

// Create global instance
window.interactionTracker = new InteractionTracker();

// Expose for debugging
window.InteractionTracker = InteractionTracker;

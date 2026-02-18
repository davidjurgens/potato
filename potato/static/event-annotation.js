/**
 * Event Annotation Manager
 *
 * Handles the creation, management, and visualization of N-ary events
 * with triggers and typed arguments in the Potato annotation platform.
 */

class EventAnnotationManager {
    constructor(schemaName, spanSchemaName) {
        this.schemaName = schemaName;
        this.spanSchemaName = spanSchemaName;
        this.events = [];
        this.isEventMode = false;

        // State machine: idle -> select_type -> select_trigger -> assign_arguments
        this.state = 'idle';
        this.currentEventType = null;
        this.currentEventConfig = null;
        this.triggerSpan = null;
        this.arguments = {}; // Maps role -> span data
        this.currentRole = null;

        // DOM element references
        this.container = document.getElementById(schemaName);
        this.triggerSection = null;
        this.argumentsSection = null;
        this.argumentsPanel = null;
        this.triggerDisplay = null;
        this.eventList = null;
        this.createButton = null;
        this.cancelButton = null;
        this.showArcsCheckbox = null;
        this.eventDataInput = null;

        // Arc rendering
        this.arcsContainer = null;
        this.arcSpacer = null;
        this.textWrapper = null;

        this.init();
    }

    init() {
        console.log('[EventAnnotationManager] init() called for schema:', this.schemaName);

        if (!this.container) {
            console.warn(`EventAnnotationManager: Container not found for schema ${this.schemaName}`);
            return;
        }

        // Get DOM references
        this.triggerSection = this.container.querySelector('.event-trigger-section');
        this.argumentsSection = this.container.querySelector('.event-arguments-section');
        this.argumentsPanel = document.getElementById(`${this.schemaName}_arguments_panel`);
        this.triggerDisplay = document.getElementById(`${this.schemaName}_trigger_display`);
        this.eventList = document.getElementById(`${this.schemaName}_event_list`);
        this.createButton = document.getElementById(`${this.schemaName}_create_event`);
        this.cancelButton = document.getElementById(`${this.schemaName}_cancel_event`);
        this.showArcsCheckbox = document.getElementById(`${this.schemaName}_show_arcs`);
        this.eventDataInput = document.getElementById(`${this.schemaName}_event_data`);

        // Parse event type configurations
        this.parseEventTypeConfigs();

        // Set up event listeners
        this.setupEventListeners();

        // Create arc rendering container
        this.createArcsContainer();

        // Load existing events if any
        this.loadExistingEvents();

        console.log(`[EventAnnotationManager] Initialization complete for schema: ${this.schemaName}`);
    }

    parseEventTypeConfigs() {
        this.eventTypeConfigs = {};
        const eventTypes = this.container.querySelectorAll('.event-type');
        eventTypes.forEach(et => {
            const typeName = et.dataset.eventType;
            const triggerLabels = et.dataset.triggerLabels ? et.dataset.triggerLabels.split(',').filter(Boolean) : [];
            let argsList = [];
            try {
                argsList = JSON.parse(et.dataset.arguments || '[]');
            } catch (e) {
                console.error(`[EventAnnotationManager] Failed to parse arguments for ${typeName}:`, e);
            }
            this.eventTypeConfigs[typeName] = {
                color: et.dataset.color || '#dc2626',
                triggerLabels: triggerLabels,
                arguments: argsList
            };
        });
        console.log('[EventAnnotationManager] Event type configs:', this.eventTypeConfigs);
    }

    setupEventListeners() {
        // Event type selection
        const eventTypeRadios = this.container.querySelectorAll('.event-type-radio');
        eventTypeRadios.forEach(radio => {
            radio.addEventListener('change', (e) => {
                this.selectEventType(e.target.value);
            });
        });

        // Create button
        if (this.createButton) {
            this.createButton.addEventListener('click', () => this.createEvent());
        }

        // Cancel button
        if (this.cancelButton) {
            this.cancelButton.addEventListener('click', () => this.cancelEventCreation());
        }

        // Escape key cancels event creation
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.isEventMode) {
                e.preventDefault();
                this.cancelEventCreation();
            }
        });

        // Show arcs toggle
        if (this.showArcsCheckbox) {
            this.showArcsCheckbox.addEventListener('change', (e) => {
                this.toggleArcsVisibility(e.target.checked);
            });
        }

        // Listen for span clicks when in event mode
        document.addEventListener('click', (e) => {
            if (!this.isEventMode) return;

            // Check if clicked on a span overlay
            let spanOverlay = e.target.closest('.span-overlay-pure, .span-overlay, .span-overlay-ai, .span-highlight');
            if (!spanOverlay) {
                const segment = e.target.closest('.span-highlight-segment');
                if (segment) {
                    spanOverlay = segment.closest('.span-overlay-pure, .span-overlay, .span-overlay-ai');
                }
            }

            if (spanOverlay && spanOverlay.dataset.annotationId) {
                e.preventDefault();
                e.stopPropagation();
                e.stopImmediatePropagation();
                this.handleSpanClick(spanOverlay);
            }
        }, true);
    }

    selectEventType(eventType) {
        console.log(`[EventAnnotationManager] Selecting event type: ${eventType}`);
        this.currentEventType = eventType;
        this.currentEventConfig = this.eventTypeConfigs[eventType];
        this.state = 'select_trigger';
        this.enterEventMode();
        this.updateUI();
    }

    enterEventMode() {
        this.isEventMode = true;

        // Add visual indicator
        this.container.classList.add('event-mode-active');
        document.body.classList.add('event-annotation-mode-active');

        // Get color for current event type
        const eventColor = this.currentEventConfig?.color || '#dc2626';
        document.body.style.setProperty('--current-event-color', eventColor);

        // Enable span selection
        const spanOverlays = document.querySelectorAll('.span-overlay-pure, .span-overlay, .span-overlay-ai, .span-highlight');
        spanOverlays.forEach(overlay => {
            overlay.classList.add('event-selectable');
            overlay.style.setProperty('--current-event-color', eventColor);
            overlay.style.pointerEvents = 'auto';
            overlay.style.cursor = 'pointer';
        });

        // Also enable segments
        const segments = document.querySelectorAll('.span-highlight-segment');
        segments.forEach(segment => {
            segment.style.pointerEvents = 'auto';
            segment.style.cursor = 'pointer';
        });
    }

    exitEventMode() {
        this.isEventMode = false;
        this.state = 'idle';

        this.container.classList.remove('event-mode-active');
        document.body.classList.remove('event-annotation-mode-active');
        document.body.style.removeProperty('--current-event-color');

        // Remove span selection
        const spanOverlays = document.querySelectorAll('.span-overlay-pure, .span-overlay, .span-overlay-ai, .span-highlight');
        spanOverlays.forEach(overlay => {
            overlay.classList.remove('event-selectable');
            overlay.classList.remove('event-trigger-selected');
            overlay.classList.remove('event-argument-selected');
            overlay.style.pointerEvents = 'none';
            overlay.style.cursor = '';
            overlay.style.removeProperty('--current-event-color');
        });

        const segments = document.querySelectorAll('.span-highlight-segment');
        segments.forEach(segment => {
            segment.style.pointerEvents = 'none';
            segment.style.cursor = '';
        });

        // Deselect radio
        const eventTypeRadios = this.container.querySelectorAll('.event-type-radio');
        eventTypeRadios.forEach(radio => radio.checked = false);

        this.resetEventState();
    }

    resetEventState() {
        this.currentEventType = null;
        this.currentEventConfig = null;
        this.triggerSpan = null;
        this.arguments = {};
        this.currentRole = null;
    }

    cancelEventCreation() {
        this.exitEventMode();
        this.updateUI();
    }

    handleSpanClick(spanOverlay) {
        const spanData = this.extractSpanData(spanOverlay);
        console.log(`[EventAnnotationManager] Span clicked:`, spanData);

        if (this.state === 'select_trigger') {
            this.selectTrigger(spanOverlay, spanData);
        } else if (this.state === 'assign_arguments' && this.currentRole) {
            this.assignArgument(spanOverlay, spanData);
        }
    }

    extractSpanData(spanOverlay) {
        return {
            id: spanOverlay.dataset.annotationId,
            label: spanOverlay.dataset.label,
            text: this.getSpanText(spanOverlay),
            start: parseInt(spanOverlay.dataset.start),
            end: parseInt(spanOverlay.dataset.end)
        };
    }

    getSpanText(spanOverlay) {
        const start = parseInt(spanOverlay.dataset.start);
        const end = parseInt(spanOverlay.dataset.end);

        // Get the original plain text from the data-original-text attribute
        // This is the text that span offsets are based on
        const textContent = document.getElementById('text-content');
        if (textContent && textContent.dataset.originalText) {
            return textContent.dataset.originalText.substring(start, end);
        }

        // Fallback: try to get text from the span overlay's own text content
        // This gets the actual visible text within the span
        const segments = spanOverlay.querySelectorAll('.span-highlight-segment');
        if (segments.length > 0) {
            return Array.from(segments).map(s => s.textContent).join('');
        }

        // Last fallback: use the span overlay's text content directly
        return spanOverlay.textContent || '';
    }

    selectTrigger(spanOverlay, spanData) {
        // Check if trigger label constraint is satisfied
        const triggerLabels = this.currentEventConfig?.triggerLabels || [];
        if (triggerLabels.length > 0 && !triggerLabels.includes(spanData.label)) {
            console.warn(`[EventAnnotationManager] Span label ${spanData.label} not allowed as trigger. Allowed: ${triggerLabels.join(', ')}`);
            return;
        }

        // Clear previous trigger selection
        const prevTrigger = document.querySelector('.event-trigger-selected');
        if (prevTrigger) {
            prevTrigger.classList.remove('event-trigger-selected');
        }

        // Mark this span as trigger
        spanOverlay.classList.add('event-trigger-selected');
        this.triggerSpan = spanData;
        this.state = 'assign_arguments';
        this.updateUI();
    }

    assignArgument(spanOverlay, spanData) {
        if (!this.currentRole) return;

        // Check entity type constraint
        const roleConfig = this.currentEventConfig?.arguments.find(a => a.role === this.currentRole);
        const entityTypes = roleConfig?.entity_types || [];
        if (entityTypes.length > 0 && !entityTypes.includes(spanData.label)) {
            console.warn(`[EventAnnotationManager] Span label ${spanData.label} not allowed for role ${this.currentRole}. Allowed: ${entityTypes.join(', ')}`);
            return;
        }

        // Store argument
        this.arguments[this.currentRole] = spanData;
        spanOverlay.classList.add('event-argument-selected');
        this.currentRole = null;
        this.updateUI();
        this.checkCanCreate();
    }

    selectRole(role) {
        this.currentRole = role;
        this.updateUI();
    }

    removeArgument(role) {
        // Find and unmark the span
        const spanData = this.arguments[role];
        if (spanData) {
            const overlay = document.querySelector(`[data-annotation-id="${spanData.id}"]`);
            if (overlay) {
                overlay.classList.remove('event-argument-selected');
            }
        }
        delete this.arguments[role];
        this.updateUI();
        this.checkCanCreate();
    }

    checkCanCreate() {
        // Check if all required arguments are filled
        const args = this.currentEventConfig?.arguments || [];
        const requiredRoles = args.filter(a => a.required).map(a => a.role);
        const filledRoles = Object.keys(this.arguments);

        const canCreate = this.triggerSpan &&
                         requiredRoles.every(role => filledRoles.includes(role));

        if (this.createButton) {
            this.createButton.disabled = !canCreate;
        }

        return canCreate;
    }

    createEvent() {
        if (!this.checkCanCreate()) return;

        console.log(`[EventAnnotationManager] createEvent() called`);
        console.log(`[EventAnnotationManager] Events BEFORE create: ${this.events.length}`, this.events.map(e => e.id));

        // IMPORTANT: Cache span positions BEFORE exiting event mode
        // While in event mode, spans are visible and correctly positioned
        // After exitEventMode, there may be layout delays
        this.cacheSpanPositions();

        // Build event data
        const eventData = {
            id: `event_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
            schema: this.schemaName,
            event_type: this.currentEventType,
            trigger_span_id: this.triggerSpan.id,
            arguments: Object.entries(this.arguments).map(([role, span]) => ({
                role: role,
                span_id: span.id
            })),
            properties: {
                color: this.currentEventConfig?.color || '#dc2626',
                trigger_text: this.triggerSpan.text,
                trigger_label: this.triggerSpan.label
            }
        };

        // Check if this event already exists (prevent duplicates)
        const existingEventIndex = this.events.findIndex(e =>
            e.trigger_span_id === eventData.trigger_span_id &&
            e.event_type === eventData.event_type
        );

        if (existingEventIndex >= 0) {
            console.warn(`[EventAnnotationManager] Event with same trigger and type already exists, updating instead of adding`);
            this.events[existingEventIndex] = eventData;
        } else {
            // Add to events list
            this.events.push(eventData);
        }
        console.log(`[EventAnnotationManager] Created event: ${eventData.id}, total events: ${this.events.length}`);
        console.log(`[EventAnnotationManager] Events AFTER create:`, this.events.map(e => e.id));

        // Update hidden input
        this.updateEventDataInput();

        // Sync to backend
        this.syncToBackend();

        // Exit event mode
        this.exitEventMode();
        this.updateUI();

        // Use delayed rendering since cached positions didn't work
        // The spans need time to settle after exitEventMode
        this.renderArcsWithDelay();
    }

    /**
     * Render arcs with a delay to allow DOM to settle.
     * Uses requestAnimationFrame to ensure we render after the browser has painted.
     */
    renderArcsWithDelay(attempt = 0) {
        console.log(`[EventAnnotationManager] renderArcsWithDelay attempt ${attempt}`);
        console.log(`[EventAnnotationManager] Current events count: ${this.events.length}`);

        // Use requestAnimationFrame to wait for next paint
        requestAnimationFrame(() => {
            // Then use another RAF to ensure layout is complete
            requestAnimationFrame(() => {
                // Add a small timeout to allow any CSS transitions to complete
                setTimeout(() => {
                    this.tryRenderArcs(attempt);
                }, 50);
            });
        });
    }

    tryRenderArcs(attempt) {
        const maxAttempts = 15;

        if (this.events.length === 0) {
            console.log(`[EventAnnotationManager] No events to render`);
            return;
        }

        // Force a reflow by scrolling the instance text into view
        const instanceText = document.getElementById('instance-text');
        if (instanceText && attempt === 0) {
            instanceText.scrollIntoView({ behavior: 'instant', block: 'center' });
            // Force synchronous reflow
            void instanceText.offsetHeight;
        }

        // Check if spans have valid positions
        const lastEvent = this.events[this.events.length - 1];
        const triggerOverlay = document.querySelector(`[data-annotation-id="${lastEvent.trigger_span_id}"]`);

        if (!triggerOverlay) {
            console.warn(`[EventAnnotationManager] Trigger overlay not found: ${lastEvent.trigger_span_id}`);
            if (attempt < maxAttempts) {
                setTimeout(() => this.tryRenderArcs(attempt + 1), 100);
            }
            return;
        }

        // Force reflow on the overlay
        void triggerOverlay.offsetHeight;

        // Get position using segments if available
        let hasValidPosition = false;
        let measureRect = null;
        const segments = triggerOverlay.querySelectorAll('.span-highlight-segment');

        if (segments.length > 0) {
            const segRect = segments[0].getBoundingClientRect();
            measureRect = segRect;
            console.log(`[EventAnnotationManager] Attempt ${attempt}: Segment rect: w=${segRect.width}, h=${segRect.height}, top=${segRect.top}`);
            // Valid if has non-zero size (top can be negative if scrolled)
            hasValidPosition = segRect.width > 0 && segRect.height > 0;
        } else {
            const rect = triggerOverlay.getBoundingClientRect();
            measureRect = rect;
            console.log(`[EventAnnotationManager] Attempt ${attempt}: Overlay rect: w=${rect.width}, h=${rect.height}, top=${rect.top}`);
            hasValidPosition = rect.width > 0 && rect.height > 0;
        }

        // Also check if textWrapper has valid dimensions
        if (hasValidPosition && this.textWrapper) {
            const wrapperRect = this.textWrapper.getBoundingClientRect();
            console.log(`[EventAnnotationManager] TextWrapper rect: w=${wrapperRect.width}, h=${wrapperRect.height}`);
            if (wrapperRect.width === 0 || wrapperRect.height === 0) {
                hasValidPosition = false;
            }
        }

        if (hasValidPosition) {
            console.log(`[EventAnnotationManager] Valid positions found, rendering arcs`);
            this.renderArcs(false);
        } else if (attempt < maxAttempts) {
            const delay = attempt < 3 ? 100 : (attempt < 6 ? 200 : 300);
            console.log(`[EventAnnotationManager] Position not valid yet, retry in ${delay}ms...`);
            setTimeout(() => this.tryRenderArcs(attempt + 1), delay);
        } else {
            console.warn(`[EventAnnotationManager] Max attempts reached, rendering anyway`);
            this.renderArcs(false);
        }
    }

    /**
     * Cache span positions while they're correctly laid out.
     * This is called before exitEventMode to capture positions when spans are visible.
     */
    cacheSpanPositions() {
        this._cachedPositions = {};

        console.log(`[EventAnnotationManager] cacheSpanPositions called, textWrapper exists: ${!!this.textWrapper}`);

        if (!this.textWrapper) {
            console.warn('[EventAnnotationManager] textWrapper not available for caching');
            // Try to find it
            const instanceText = document.getElementById('instance-text');
            if (instanceText) {
                this.textWrapper = instanceText.querySelector('.event-annotation-text-wrapper');
                console.log(`[EventAnnotationManager] Found textWrapper: ${!!this.textWrapper}`);
            }
        }

        if (!this.textWrapper) {
            console.error('[EventAnnotationManager] Cannot cache positions - no textWrapper');
            return;
        }

        // Cache all span overlay positions
        const overlays = document.querySelectorAll('[data-annotation-id]');
        console.log(`[EventAnnotationManager] Found ${overlays.length} overlays to cache`);

        overlays.forEach(overlay => {
            const id = overlay.dataset.annotationId;
            if (id) {
                const rect = overlay.getBoundingClientRect();
                const wrapperRect = this.textWrapper.getBoundingClientRect();

                console.log(`[EventAnnotationManager] Overlay ${id}: rect =`, rect, 'wrapperRect =', wrapperRect);

                if (rect.width > 0 && wrapperRect.width > 0) {
                    this._cachedPositions[id] = {
                        left: rect.left - wrapperRect.left,
                        right: rect.right - wrapperRect.left,
                        centerX: (rect.left + rect.right) / 2 - wrapperRect.left,
                        width: rect.width
                    };
                    console.log(`[EventAnnotationManager] Cached position for ${id}:`, this._cachedPositions[id]);
                } else {
                    console.warn(`[EventAnnotationManager] Zero-width rect for ${id}, skipping cache`);
                }
            }
        });

        console.log(`[EventAnnotationManager] Cached ${Object.keys(this._cachedPositions).length} span positions`);
    }

    /**
     * Attempt to render arcs, retrying if positions aren't ready yet.
     * This handles the timing issue where getBoundingClientRect() returns 0
     * before the DOM has fully laid out.
     */
    renderArcsWhenReady(retries = 0, maxRetries = 15) {
        // Use requestAnimationFrame to wait for next paint, then check positions
        requestAnimationFrame(() => {
            // Force a reflow by reading offsetHeight
            if (this.textWrapper) {
                void this.textWrapper.offsetHeight;
            }

            // Wait one more frame for the paint to complete
            requestAnimationFrame(() => {
                // Check if we can get valid positions
                if (this.events.length > 0) {
                    const firstEvent = this.events[0];
                    const triggerOverlay = document.querySelector(`[data-annotation-id="${firstEvent.trigger_span_id}"]`);

                    if (triggerOverlay && this.textWrapper) {
                        const rect = triggerOverlay.getBoundingClientRect();
                        const wrapperRect = this.textWrapper.getBoundingClientRect();

                        console.log(`[EventAnnotationManager] renderArcsWhenReady check: triggerRect =`, rect);
                        console.log(`[EventAnnotationManager] renderArcsWhenReady check: wrapperRect =`, wrapperRect);

                        // If position is still invalid (left=0 usually means not laid out), retry
                        if (rect.width === 0 || wrapperRect.width === 0 || (rect.left === 0 && retries < 5)) {
                            if (retries < maxRetries) {
                                console.log(`[EventAnnotationManager] Positions not ready, retry ${retries + 1}/${maxRetries}`);
                                // Use setTimeout for subsequent retries to avoid tight loop
                                setTimeout(() => this.renderArcsWhenReady(retries + 1, maxRetries), 50);
                                return;
                            } else {
                                console.warn('[EventAnnotationManager] Max retries reached, rendering anyway');
                            }
                        }
                    }
                }

                console.log('[EventAnnotationManager] Rendering arcs now');
                this.renderArcs();
            });
        });
    }

    updateEventDataInput() {
        if (this.eventDataInput) {
            this.eventDataInput.value = JSON.stringify(this.events);
        }
    }

    async syncToBackend() {
        const instanceId = window.currentInstanceId || this.getInstanceId();
        if (!instanceId) {
            console.error('[EventAnnotationManager] No instance ID found');
            return;
        }

        console.log(`[EventAnnotationManager] syncToBackend() called`);
        console.log(`[EventAnnotationManager] Syncing ${this.events.length} events to backend for instance ${instanceId}`);
        console.log('[EventAnnotationManager] Event IDs being sent:', this.events.map(e => e.id));
        console.log('[EventAnnotationManager] Full event data:', JSON.stringify(this.events, null, 2));

        try {
            const response = await fetch('/updateinstance', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    instance_id: instanceId,
                    event_annotations: this.events
                })
            });

            if (!response.ok) {
                console.error('[EventAnnotationManager] Failed to sync events:', response.status);
                const text = await response.text();
                console.error('[EventAnnotationManager] Response:', text);
            } else {
                const data = await response.json();
                console.log('[EventAnnotationManager] Sync successful, response:', data);
            }
        } catch (error) {
            console.error('[EventAnnotationManager] Error syncing events:', error);
        }
    }

    getInstanceId() {
        // Try various ways to get instance ID
        // The template uses 'instance_id' as the hidden input ID
        const idElem = document.getElementById('instance_id');
        if (idElem) return idElem.value || idElem.textContent;

        // Fallback to other common patterns
        const altIdElem = document.getElementById('current_instance_id');
        if (altIdElem) return altIdElem.value || altIdElem.textContent;

        const instanceText = document.getElementById('instance-text');
        if (instanceText && instanceText.dataset.instanceId) return instanceText.dataset.instanceId;

        return null;
    }

    async loadExistingEvents() {
        const instanceId = window.currentInstanceId || this.getInstanceId();
        if (!instanceId) {
            console.warn('[EventAnnotationManager] No instance ID for loading events');
            return;
        }

        // Prevent loading if we've already loaded for this instance
        if (this._loadedForInstance === instanceId && this.events.length > 0) {
            console.log(`[EventAnnotationManager] Already loaded events for instance ${instanceId}, skipping`);
            return;
        }

        console.log(`[EventAnnotationManager] loadExistingEvents() called for instance: ${instanceId}`);
        console.log(`[EventAnnotationManager] Events BEFORE load: ${this.events.length}`, this.events.map(e => e.id));

        try {
            const response = await fetch(`/api/events/${instanceId}`);
            if (response.ok) {
                const data = await response.json();
                console.log(`[EventAnnotationManager] Server returned:`, JSON.stringify(data));
                if (data.events && data.events.length > 0) {
                    console.log(`[EventAnnotationManager] Server event IDs:`, data.events.map(e => e.id));

                    // Deduplicate events by ID
                    const seenIds = new Set();
                    const uniqueEvents = [];
                    for (const event of data.events) {
                        if (!seenIds.has(event.id)) {
                            seenIds.add(event.id);
                            uniqueEvents.push(event);
                        } else {
                            console.warn(`[EventAnnotationManager] Duplicate event ID found: ${event.id}`);
                        }
                    }

                    this.events = uniqueEvents;
                    this._loadedForInstance = instanceId;
                    this.updateEventDataInput();
                    this.updateUI();
                    this.renderArcs();
                    console.log(`[EventAnnotationManager] Loaded ${this.events.length} unique events`);
                } else {
                    console.log(`[EventAnnotationManager] No events returned from server`);
                    this.events = [];
                    this._loadedForInstance = instanceId;
                }
            } else {
                console.log(`[EventAnnotationManager] Server returned status: ${response.status}`);
            }
        } catch (error) {
            console.error('[EventAnnotationManager] Error loading events:', error);
        }
    }

    async deleteEvent(eventId) {
        const instanceId = window.currentInstanceId || this.getInstanceId();
        if (!instanceId) return;

        try {
            const response = await fetch(`/api/events/${instanceId}/${eventId}`, {
                method: 'DELETE'
            });

            if (response.ok) {
                this.events = this.events.filter(e => e.id !== eventId);
                this.updateEventDataInput();
                this.updateUI();
                this.renderArcs();
            }
        } catch (error) {
            console.error('[EventAnnotationManager] Error deleting event:', error);
        }
    }

    updateUI() {
        // Update trigger section visibility
        if (this.triggerSection) {
            this.triggerSection.style.display =
                (this.state === 'select_trigger' || this.state === 'assign_arguments') ? 'block' : 'none';
        }

        // Update arguments section visibility
        if (this.argumentsSection) {
            this.argumentsSection.style.display =
                this.state === 'assign_arguments' ? 'block' : 'none';
        }

        // Update trigger display
        this.updateTriggerDisplay();

        // Update arguments panel
        this.updateArgumentsPanel();

        // Update event list
        this.updateEventList();

        // Check if create button should be enabled
        this.checkCanCreate();
    }

    updateTriggerDisplay() {
        if (!this.triggerDisplay) return;

        if (this.triggerSpan) {
            const color = this.currentEventConfig?.color || '#dc2626';
            this.triggerDisplay.innerHTML = `
                <div class="event-trigger-chip" style="--event-color: ${color}">
                    <span class="trigger-icon">T</span>
                    <span class="trigger-text">${this.escapeHtml(this.triggerSpan.text)}</span>
                    <span class="trigger-label">${this.escapeHtml(this.triggerSpan.label)}</span>
                </div>
            `;
        } else if (this.state === 'select_trigger') {
            this.triggerDisplay.innerHTML = '<p class="no-trigger-message">Click on a span to set it as the event trigger</p>';
        } else {
            this.triggerDisplay.innerHTML = '';
        }
    }

    updateArgumentsPanel() {
        if (!this.argumentsPanel) return;

        const args = this.currentEventConfig?.arguments || [];
        if (args.length === 0) {
            this.argumentsPanel.innerHTML = '<p class="no-arguments-message">No arguments defined for this event type</p>';
            return;
        }

        const color = this.currentEventConfig?.color || '#dc2626';
        let html = '';

        for (const arg of args) {
            const role = arg.role;
            const required = arg.required;
            const entityTypes = arg.entity_types || [];
            const filledSpan = this.arguments[role];
            const isActive = this.currentRole === role;

            html += `<div class="event-argument-row ${filledSpan ? 'filled' : ''} ${isActive ? 'active' : ''}"
                         data-role="${this.escapeHtml(role)}">
                <div class="event-role-button ${isActive ? 'active' : ''}"
                     style="--event-color: ${color}"
                     onclick="window.eventAnnotationManagers['${this.schemaName}'].selectRole('${this.escapeHtml(role)}')">
                    <span class="role-name">${this.escapeHtml(role)}</span>
                    ${required ? '<span class="required-indicator">*</span>' : ''}
                </div>`;

            if (filledSpan) {
                html += `
                    <div class="event-argument-chip" style="--event-color: ${color}">
                        <span class="argument-text">${this.escapeHtml(filledSpan.text)}</span>
                        <span class="argument-label">${this.escapeHtml(filledSpan.label)}</span>
                        <button class="argument-remove-btn" onclick="window.eventAnnotationManagers['${this.schemaName}'].removeArgument('${this.escapeHtml(role)}')">x</button>
                    </div>`;
            } else if (entityTypes.length > 0) {
                html += `<span class="entity-type-hint">(${entityTypes.join(', ')})</span>`;
            }

            html += '</div>';
        }

        this.argumentsPanel.innerHTML = html;
    }

    updateEventList() {
        if (!this.eventList) return;

        if (this.events.length === 0) {
            this.eventList.innerHTML = '<p class="no-events-message">No events created yet</p>';
            return;
        }

        let html = '';
        for (const event of this.events) {
            const config = this.eventTypeConfigs[event.event_type] || {};
            const color = event.properties?.color || config.color || '#dc2626';

            html += `
                <div class="event-item" data-event-id="${event.id}" style="--event-color: ${color}">
                    <div class="event-item-header">
                        <span class="event-type-badge" style="background-color: ${color}">${this.escapeHtml(event.event_type)}</span>
                        <button class="event-delete-btn" onclick="window.eventAnnotationManagers['${this.schemaName}'].deleteEvent('${event.id}')" title="Delete event">
                            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <line x1="18" y1="6" x2="6" y2="18"></line>
                                <line x1="6" y1="6" x2="18" y2="18"></line>
                            </svg>
                        </button>
                    </div>
                    <div class="event-item-details">
                        <div class="event-trigger-info">
                            <span class="trigger-role">Trigger:</span>
                            <span class="trigger-value">${this.escapeHtml(event.properties?.trigger_text || '?')}</span>
                        </div>`;

            for (const arg of event.arguments || []) {
                const spanText = this.getSpanTextById(arg.span_id);
                html += `
                    <div class="event-argument-info">
                        <span class="argument-role">${this.escapeHtml(arg.role)}:</span>
                        <span class="argument-value">${this.escapeHtml(spanText || '?')}</span>
                    </div>`;
            }

            html += `</div></div>`;
        }

        this.eventList.innerHTML = html;
    }

    getSpanTextById(spanId) {
        const overlay = document.querySelector(`[data-annotation-id="${spanId}"]`);
        if (overlay) {
            return this.getSpanText(overlay);
        }
        return null;
    }

    createArcsContainer() {
        console.log(`[EventAnnotationManager] createArcsContainer() called`);

        const showArcs = this.container.dataset.showArcs !== 'false';
        console.log(`[EventAnnotationManager] showArcs: ${showArcs}, dataset.showArcs: ${this.container.dataset.showArcs}`);

        if (!showArcs) {
            console.log(`[EventAnnotationManager] showArcs is false, skipping container creation`);
            return;
        }

        const instanceText = document.getElementById('instance-text');
        console.log(`[EventAnnotationManager] instanceText found: ${!!instanceText}`);

        if (!instanceText) {
            console.warn(`[EventAnnotationManager] instance-text element not found!`);
            return;
        }

        // Check if wrapper already exists
        const existingWrapper = instanceText.querySelector('.event-annotation-text-wrapper');
        if (existingWrapper) {
            this.textWrapper = existingWrapper;
            this.arcSpacer = instanceText.querySelector('.event-annotation-arc-spacer');
            this.arcsContainer = instanceText.querySelector('.event-annotation-arcs-container');
            return;
        }

        // Store config
        this.arcPosition = this.container.dataset.arcPosition || 'above';
        this.instanceText = instanceText;

        // Create wrapper structure
        this.textWrapper = document.createElement('div');
        this.textWrapper.className = 'event-annotation-text-wrapper';
        this.textWrapper.style.cssText = 'position: relative;';

        while (instanceText.firstChild) {
            this.textWrapper.appendChild(instanceText.firstChild);
        }

        this.arcSpacer = document.createElement('div');
        this.arcSpacer.className = 'event-annotation-arc-spacer';
        this.arcSpacer.style.cssText = `
            position: relative;
            width: 100%;
            height: 80px;
            min-height: 80px;
        `;

        this.arcsContainer = document.createElement('div');
        this.arcsContainer.id = `${this.schemaName}_arcs`;
        this.arcsContainer.className = 'event-annotation-arcs-container';
        this.arcsContainer.style.cssText = `
            position: absolute;
            bottom: 0;
            left: 0;
            width: 100%;
            height: 100%;
            pointer-events: none;
            overflow: visible;
            z-index: 100;
        `;

        this.arcSpacer.appendChild(this.arcsContainer);
        instanceText.appendChild(this.arcSpacer);
        instanceText.appendChild(this.textWrapper);
    }

    renderArcs(useCachedPositions = false) {
        console.log(`[EventAnnotationManager] ========== renderArcs START ==========`);
        console.log(`[EventAnnotationManager] useCachedPositions=${useCachedPositions}`);
        console.log(`[EventAnnotationManager] arcsContainer exists: ${!!this.arcsContainer}`);
        console.log(`[EventAnnotationManager] textWrapper exists: ${!!this.textWrapper}`);
        console.log(`[EventAnnotationManager] events count: ${this.events.length}`);

        if (!this.arcsContainer) {
            console.error(`[EventAnnotationManager] No arcsContainer - cannot render`);
            return;
        }

        // Clear existing arcs
        this.arcsContainer.innerHTML = '';
        console.log(`[EventAnnotationManager] Cleared arcsContainer`);

        if (this.events.length === 0) {
            console.log(`[EventAnnotationManager] No events to render`);
            this.updateArcSpacerHeight(0);
            return;
        }

        // Build SVG for event arcs
        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('class', 'event-arcs-svg');
        svg.style.cssText = 'position: absolute; top: 0; left: 0; width: 100%; height: 100%; overflow: visible;';

        // Add defs for markers
        const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');

        // Create arrow marker for each event type color
        const colors = new Set(this.events.map(e => e.properties?.color || '#dc2626'));
        for (const color of colors) {
            const marker = document.createElementNS('http://www.w3.org/2000/svg', 'marker');
            marker.setAttribute('id', `event-arrow-${color.replace('#', '')}`);
            marker.setAttribute('markerWidth', '8');
            marker.setAttribute('markerHeight', '6');
            marker.setAttribute('refX', '7');
            marker.setAttribute('refY', '3');
            marker.setAttribute('orient', 'auto');
            const polygon = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
            polygon.setAttribute('points', '0 0, 8 3, 0 6');
            polygon.setAttribute('fill', color);
            marker.appendChild(polygon);
            defs.appendChild(marker);
        }

        svg.appendChild(defs);

        let maxHeight = 0;
        const baseY = 60; // Start position for arcs

        for (let eventIndex = 0; eventIndex < this.events.length; eventIndex++) {
            const event = this.events[eventIndex];
            const color = event.properties?.color || '#dc2626';
            const levelOffset = eventIndex * 25; // Stack events vertically

            // Get trigger position
            console.log(`[EventAnnotationManager] Looking for trigger: ${event.trigger_span_id}`);
            const triggerOverlay = document.querySelector(`[data-annotation-id="${event.trigger_span_id}"]`);
            if (!triggerOverlay) {
                console.warn(`[EventAnnotationManager] Trigger overlay not found: ${event.trigger_span_id}`);
                continue;
            }

            console.log(`[EventAnnotationManager] Found trigger overlay, getting position (cached=${useCachedPositions})`);
            const triggerRect = this.getSpanPosition(triggerOverlay, useCachedPositions);
            if (!triggerRect) {
                console.warn(`[EventAnnotationManager] Could not get trigger position`);
                continue;
            }
            console.log(`[EventAnnotationManager] Trigger position: centerX=${triggerRect.centerX}`);

            const triggerX = triggerRect.centerX;
            const triggerY = baseY - levelOffset;

            // Draw hub at trigger
            const hub = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
            hub.setAttribute('cx', triggerX);
            hub.setAttribute('cy', triggerY);
            hub.setAttribute('r', '6');
            hub.setAttribute('fill', color);
            hub.setAttribute('class', 'event-hub');
            hub.setAttribute('data-event-id', event.id);
            svg.appendChild(hub);

            // Draw label for event type
            const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
            label.setAttribute('x', triggerX);
            label.setAttribute('y', triggerY - 12);
            label.setAttribute('text-anchor', 'middle');
            label.setAttribute('font-size', '10');
            label.setAttribute('fill', color);
            label.setAttribute('class', 'event-type-label');
            label.textContent = event.event_type;
            svg.appendChild(label);

            maxHeight = Math.max(maxHeight, triggerY + 20);

            // Draw spokes to arguments
            for (const arg of event.arguments || []) {
                const argOverlay = document.querySelector(`[data-annotation-id="${arg.span_id}"]`);
                if (!argOverlay) continue;

                const argRect = this.getSpanPosition(argOverlay, useCachedPositions);
                if (!argRect) continue;

                const argX = argRect.centerX;
                const argY = triggerY + 30; // Connect to bottom of hub area

                // Draw arc from hub to argument
                const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                const midY = (triggerY + argY) / 2 - 10;
                const d = `M ${triggerX} ${triggerY + 6} Q ${(triggerX + argX) / 2} ${midY} ${argX} ${argY}`;
                path.setAttribute('d', d);
                path.setAttribute('stroke', color);
                path.setAttribute('stroke-width', '1.5');
                path.setAttribute('fill', 'none');
                path.setAttribute('marker-end', `url(#event-arrow-${color.replace('#', '')})`);
                path.setAttribute('class', 'event-arc');
                path.setAttribute('data-event-id', event.id);
                path.setAttribute('data-role', arg.role);
                svg.appendChild(path);

                // Draw role label
                const roleLabel = document.createElementNS('http://www.w3.org/2000/svg', 'text');
                roleLabel.setAttribute('x', argX);
                roleLabel.setAttribute('y', argY + 12);
                roleLabel.setAttribute('text-anchor', 'middle');
                roleLabel.setAttribute('font-size', '9');
                roleLabel.setAttribute('fill', color);
                roleLabel.setAttribute('class', 'event-role-label');
                roleLabel.textContent = arg.role;
                svg.appendChild(roleLabel);
            }
        }

        this.arcsContainer.appendChild(svg);
        this.updateArcSpacerHeight(maxHeight + 20);

        // Log what was rendered
        const hubsRendered = svg.querySelectorAll('.event-hub').length;
        const arcsRendered = svg.querySelectorAll('.event-arc').length;
        console.log(`[EventAnnotationManager] ========== renderArcs COMPLETE ==========`);
        console.log(`[EventAnnotationManager] Hubs rendered: ${hubsRendered}`);
        console.log(`[EventAnnotationManager] Arcs rendered: ${arcsRendered}`);
        console.log(`[EventAnnotationManager] maxHeight: ${maxHeight}`);
    }

    getSpanPosition(overlay, useCached = false) {
        if (!overlay) {
            console.warn('[EventAnnotationManager] getSpanPosition: missing overlay');
            return null;
        }

        const spanId = overlay.dataset?.annotationId;

        // Try cached position first if requested
        if (useCached && spanId && this._cachedPositions && this._cachedPositions[spanId]) {
            console.log(`[EventAnnotationManager] Using cached position for ${spanId}`);
            return this._cachedPositions[spanId];
        }

        if (!this.textWrapper) {
            console.warn('[EventAnnotationManager] getSpanPosition: missing textWrapper');
            return null;
        }

        // The overlay container might have zero dimensions
        // Get dimensions from the visible segment children instead
        let rect = overlay.getBoundingClientRect();

        if (rect.width === 0 || rect.height === 0) {
            // Try to get bounds from child segments
            const segments = overlay.querySelectorAll('.span-highlight-segment, .span-segment');
            if (segments.length > 0) {
                // Calculate bounding box of all segments
                let minLeft = Infinity, maxRight = -Infinity;
                let minTop = Infinity, maxBottom = -Infinity;

                segments.forEach(seg => {
                    const segRect = seg.getBoundingClientRect();
                    if (segRect.width > 0) {
                        minLeft = Math.min(minLeft, segRect.left);
                        maxRight = Math.max(maxRight, segRect.right);
                        minTop = Math.min(minTop, segRect.top);
                        maxBottom = Math.max(maxBottom, segRect.bottom);
                    }
                });

                if (minLeft !== Infinity) {
                    rect = {
                        left: minLeft,
                        right: maxRight,
                        top: minTop,
                        bottom: maxBottom,
                        width: maxRight - minLeft,
                        height: maxBottom - minTop
                    };
                    console.log(`[EventAnnotationManager] Using segment bounds for ${spanId}:`, rect);
                }
            }
        }

        const wrapperRect = this.textWrapper.getBoundingClientRect();

        // Check for invalid positions
        if (rect.width === 0 || wrapperRect.width === 0) {
            console.warn(`[EventAnnotationManager] getSpanPosition: zero-width rect for ${spanId}`);
            return null;
        }

        const pos = {
            left: rect.left - wrapperRect.left,
            right: rect.right - wrapperRect.left,
            centerX: (rect.left + rect.right) / 2 - wrapperRect.left,
            width: rect.width
        };

        return pos;
    }

    updateArcSpacerHeight(height) {
        if (!this.arcSpacer) return;
        const totalHeight = Math.max(40, height + 20);
        this.arcSpacer.style.height = `${totalHeight}px`;
        this.arcSpacer.style.minHeight = `${totalHeight}px`;
    }

    toggleArcsVisibility(visible) {
        if (this.arcsContainer) {
            this.arcsContainer.style.display = visible ? 'block' : 'none';
        }
        if (this.arcSpacer) {
            this.arcSpacer.style.display = visible ? 'block' : 'none';
        }
    }

    escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Global registry for event annotation managers
window.eventAnnotationManagers = window.eventAnnotationManagers || {};

// Initialize event annotation managers when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    console.log('[EventAnnotationManager] DOMContentLoaded fired');

    const containers = document.querySelectorAll('.event-annotation-container');
    console.log(`[EventAnnotationManager] Found ${containers.length} containers`);

    containers.forEach(container => {
        const schemaName = container.id;
        const spanSchema = container.dataset.spanSchema;
        if (schemaName) {
            // Check if already initialized
            if (window.eventAnnotationManagers[schemaName]) {
                console.warn(`[EventAnnotationManager] Manager for ${schemaName} already exists, skipping initialization`);
                return;
            }
            console.log(`[EventAnnotationManager] Initializing manager for schema: ${schemaName}`);
            window.eventAnnotationManagers[schemaName] = new EventAnnotationManager(schemaName, spanSchema);
        }
    });
});

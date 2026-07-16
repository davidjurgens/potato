/**
 * Span Link Manager
 *
 * Handles the creation, management, and visualization of links/relationships
 * between spans in the Potato annotation platform.
 */

class SpanLinkManager {
    constructor(schemaName, spanSchemaName) {
        this.schemaName = schemaName;
        this.spanSchemaName = spanSchemaName;
        this.selectedSpans = [];
        this.currentLinkType = null;
        this.links = [];
        this.isLinkMode = false;
        this.linkTypeConfig = {};

        // DOM element references
        this.container = document.getElementById(schemaName);
        this.selectedSpansDisplay = document.getElementById(`${schemaName}_selected_spans`);
        this.linkList = document.getElementById(`${schemaName}_link_list`);
        this.createButton = document.getElementById(`${schemaName}_create_link`);
        this.clearButton = document.getElementById(`${schemaName}_clear_selection`);
        this.showArcsCheckbox = document.getElementById(`${schemaName}_show_arcs`);
        this.linkDataInput = document.getElementById(`${schemaName}_link_data`);

        // Arc rendering
        this.arcsContainer = null;

        this.init();
    }

    init() {
        console.log('[SpanLinkManager] init() called for schema:', this.schemaName);

        if (!this.container) {
            console.warn(`SpanLinkManager: Container not found for schema ${this.schemaName}`);
            return;
        }

        // Parse link type configurations
        this.parseLinkTypeConfigs();
        console.log('[SpanLinkManager] Link type configs:', this.linkTypeConfig);

        // Set up event listeners
        this.setupEventListeners();

        // Create arc rendering container
        this.createArcsContainer();

        // Set up observer to re-render arcs when spans are added/removed
        this.setupSpanObserver();

        // Load existing links if any
        this.loadExistingLinks();

        // Render the initial guidance ("highlight spans first…") into the panel.
        this.updateUI();

        console.log(`[SpanLinkManager] Initialization complete for schema: ${this.schemaName}`);
        console.log('[SpanLinkManager] Post-init state:', {
            hasArcsContainer: !!this.arcsContainer,
            hasArcSpacer: !!this.arcSpacer,
            hasTextWrapper: !!this.textWrapper
        });
    }

    /**
     * Set up MutationObserver to watch for span overlay changes.
     * Re-renders arcs when spans are added, removed, or modified.
     */
    setupSpanObserver() {
        const targetNode = this.textWrapper || document.getElementById('instance-text');
        if (!targetNode) return;

        // Debounce re-renders to avoid excessive updates
        let renderTimeout = null;
        const debouncedRender = () => {
            if (renderTimeout) clearTimeout(renderTimeout);
            renderTimeout = setTimeout(() => {
                if (this.links.length > 0) {
                    console.log('[SpanLinkManager] Span change detected, re-rendering arcs');
                    this.renderArcs();
                }
                // Refresh the panel so the guidance/slots track how many spans
                // exist (e.g. "highlight first" -> "choose a link type").
                this.updateUI();
                // Keep spans clickable if they were highlighted while already in
                // link mode (so a follow-up link can select them).
                if (this.isLinkMode) this.makeOverlaysSelectable();
            }, 100);
        };

        this.spanObserver = new MutationObserver((mutations) => {
            // Check if any mutation involves span overlays
            const hasSpanChanges = mutations.some(mutation => {
                // Check added nodes
                for (const node of mutation.addedNodes) {
                    if (node.nodeType === Node.ELEMENT_NODE) {
                        if (node.classList?.contains('span-overlay-pure') ||
                            node.classList?.contains('span-overlay') ||
                            node.querySelector?.('.span-overlay-pure, .span-overlay')) {
                            return true;
                        }
                    }
                }
                // Check removed nodes
                for (const node of mutation.removedNodes) {
                    if (node.nodeType === Node.ELEMENT_NODE) {
                        if (node.classList?.contains('span-overlay-pure') ||
                            node.classList?.contains('span-overlay')) {
                            return true;
                        }
                    }
                }
                return false;
            });

            if (hasSpanChanges) {
                debouncedRender();
            }
        });

        this.spanObserver.observe(targetNode, {
            childList: true,
            subtree: true
        });
    }

    parseLinkTypeConfigs() {
        const linkTypes = this.container.querySelectorAll('.span-link-type');
        linkTypes.forEach(lt => {
            const name = lt.dataset.linkType;
            this.linkTypeConfig[name] = {
                directed: lt.dataset.directed === 'true',
                maxSpans: parseInt(lt.dataset.maxSpans) || 2,
                color: lt.dataset.color || '#dc2626',
                sourceLabels: lt.dataset.sourceLabels ? lt.dataset.sourceLabels.split(',').filter(Boolean) : [],
                targetLabels: lt.dataset.targetLabels ? lt.dataset.targetLabels.split(',').filter(Boolean) : []
            };
        });
    }

    setupEventListeners() {
        // Link type selection
        const linkTypeRadios = this.container.querySelectorAll('.span-link-type-radio');
        linkTypeRadios.forEach(radio => {
            radio.addEventListener('change', (e) => {
                this.currentLinkType = e.target.value;
                this.enterLinkMode();
                this.updateUI();
            });
        });

        // Create button
        if (this.createButton) {
            this.createButton.addEventListener('click', () => this.createLink());
        }

        // Clear button - exits link mode entirely so user can create new spans
        if (this.clearButton) {
            this.clearButton.addEventListener('click', () => this.exitLinkMode());
        }

        // Escape key exits link mode
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.isLinkMode) {
                e.preventDefault();
                this.exitLinkMode();
            }
        });

        // Show arcs toggle
        if (this.showArcsCheckbox) {
            this.showArcsCheckbox.addEventListener('change', (e) => {
                this.toggleArcsVisibility(e.target.checked);
            });
        }

        // Reposition simple connector arcs when the layout reflows.
        window.addEventListener('resize', () => {
            clearTimeout(this._arcResizeTimer);
            this._arcResizeTimer = setTimeout(() => {
                if (this.simpleArcs && this.links.length) this.renderSimpleConnectors();
            }, 150);
        });

        // Listen for span clicks when in link mode - use capture phase
        document.addEventListener('click', (e) => {
            if (!this.isLinkMode) return;

            console.log('[SpanLinkManager] Click detected in link mode, target:', e.target.className);

            // Check if clicked on a span overlay or any element inside it
            // This handles clicks on .span-highlight-segment, .span-label, .span-controls, etc.
            let spanOverlay = e.target.closest('.span-overlay-pure, .span-overlay, .span-overlay-ai, .span-highlight');

            // Also check if we clicked on a segment inside an overlay
            if (!spanOverlay) {
                const segment = e.target.closest('.span-highlight-segment');
                if (segment) {
                    spanOverlay = segment.closest('.span-overlay-pure, .span-overlay, .span-overlay-ai');
                }
            }

            if (spanOverlay && spanOverlay.dataset.annotationId) {
                console.log('[SpanLinkManager] Found span overlay:', spanOverlay.className,
                    'annotationId:', spanOverlay.dataset.annotationId,
                    'label:', spanOverlay.dataset.label,
                    'start:', spanOverlay.dataset.start,
                    'end:', spanOverlay.dataset.end);
                e.preventDefault();
                e.stopPropagation();
                e.stopImmediatePropagation();
                this.handleSpanClick(spanOverlay);
            } else {
                console.log('[SpanLinkManager] No valid span overlay found at click target');
            }
        }, true);

        // Also listen on mousedown to prevent text selection while in link mode
        document.addEventListener('mousedown', (e) => {
            if (!this.isLinkMode) return;

            const spanOverlay = e.target.closest('.span-overlay-pure, .span-overlay, .span-overlay-ai, .span-highlight, .span-highlight-segment');
            if (spanOverlay) {
                e.preventDefault();
            }
        }, true);
    }

    createArcsContainer() {
        console.log('[SpanLinkManager] createArcsContainer() called');

        // Check if arc visualization is enabled
        const showArcs = this.container.dataset.showArcs !== 'false';
        console.log('[SpanLinkManager] showArcs:', showArcs);
        if (!showArcs) {
            console.log('[SpanLinkManager] Arc visualization disabled');
            return;
        }

        // instance_display / multi-field displays (audio_dialogue, dialogue,
        // multi_agent_discussion, …) render text into a per-field
        // ``text-content-{field}`` container, not the legacy flat ``#instance-text``.
        // The spacer/dependency-arc model reflows a single paragraph and does not
        // fit a scrollable chat-bubble layout, so use a lightweight SVG connector
        // overlay drawn directly between the linked span overlays instead.
        const fieldHost = document.querySelector('.text-content[id^="text-content-"]');
        if (fieldHost && fieldHost.offsetParent !== null) {
            this.arcHost = fieldHost;
            this.simpleArcs = true;
            this.ensureSimpleArcSvg();
            console.log('[SpanLinkManager] Using simple connector arcs over', fieldHost.id);
            return;
        }

        // Find the instance text container to place arcs relative to it
        const instanceText = document.getElementById('instance-text');
        console.log('[SpanLinkManager] instanceText element:', instanceText);
        if (!instanceText) {
            console.error('[SpanLinkManager] No instance-text element found!');
            return;
        }

        // Check if wrapper structure already exists (e.g., from previous initialization)
        const existingWrapper = instanceText.querySelector('.span-link-text-wrapper');
        if (existingWrapper) {
            console.log('[SpanLinkManager] Wrapper structure already exists, reusing');
            this.textWrapper = existingWrapper;
            this.arcSpacer = instanceText.querySelector('.span-link-arc-spacer');
            this.arcsContainer = instanceText.querySelector('.span-link-arcs-container');
            return;
        }

        // Store configuration for later use
        this.arcPosition = this.container.dataset.arcPosition || 'above';
        this.multiLineMode = this.container.dataset.multiLineMode || 'bracket';
        this.instanceText = instanceText;

        if (this.arcPosition === 'above') {
            if (this.multiLineMode === 'single_line') {
                // Single-line mode: display text on one line with horizontal scroll
                instanceText.style.whiteSpace = 'nowrap';
                instanceText.style.overflowX = 'auto';
                instanceText.classList.add('dependency-single-line-mode');
            } else {
                // Bracket mode: wrapped text with bracket-style arcs for multi-line
                instanceText.classList.add('dependency-bracket-mode');
            }
        }

        // Create a wrapper structure for reliable arc positioning:
        // 1. Arc spacer div (takes up vertical space for arcs)
        // 2. Text wrapper (contains the actual text content)
        // 3. Arc SVG overlay (positioned absolutely over the spacer)

        // Wrap existing content in a text wrapper
        this.textWrapper = document.createElement('div');
        this.textWrapper.className = 'span-link-text-wrapper';
        this.textWrapper.style.cssText = 'position: relative;';

        // Move all existing children into the wrapper
        while (instanceText.firstChild) {
            this.textWrapper.appendChild(instanceText.firstChild);
        }

        // Create spacer div for arc area (will be sized dynamically)
        this.arcSpacer = document.createElement('div');
        this.arcSpacer.className = 'span-link-arc-spacer';
        this.arcSpacer.style.cssText = `
            position: relative;
            width: 100%;
            height: 100px;
            min-height: 100px;
        `;

        // Create SVG container for arcs - inside the spacer
        this.arcsContainer = document.createElement('div');
        this.arcsContainer.id = `${this.schemaName}_arcs`;
        this.arcsContainer.className = 'span-link-arcs-container';
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

        // Assemble the structure
        this.arcSpacer.appendChild(this.arcsContainer);
        instanceText.appendChild(this.arcSpacer);
        instanceText.appendChild(this.textWrapper);

        console.log('[SpanLinkManager] Created arc container structure with spacer');
    }

    /**
     * Dynamically update the arc spacer height based on required arc height
     */
    updateArcSpacerHeight(requiredHeight) {
        if (!this.arcSpacer) return;

        // Add margin for labels (25px) and buffer (15px)
        const totalHeight = requiredHeight + 40;

        console.log(`[SpanLinkManager] Setting arc spacer height: ${totalHeight}px (arc height: ${requiredHeight}px)`);

        this.arcSpacer.style.height = `${totalHeight}px`;
        this.arcSpacer.style.minHeight = `${totalHeight}px`;
    }

    enterLinkMode() {
        this.isLinkMode = true;
        this.clearSelection();

        // Get the color for the current link type
        const linkColor = this.linkTypeConfig[this.currentLinkType]?.color || '#6E56CF';

        // Add visual indicator that link mode is active
        this.container.classList.add('link-mode-active');

        // Add body class to indicate link mode is active (used to disable span annotation)
        document.body.classList.add('span-link-mode-active');

        // Set the link color as a CSS variable on the body for use in selection styles
        document.body.style.setProperty('--current-link-color', linkColor);

        // Make every current span overlay clickable.
        this.makeOverlaysSelectable(linkColor);

        console.log(`[SpanLinkManager] Entered link mode with type: ${this.currentLinkType}`);
    }

    /**
     * Enable pointer events + selectable styling on all span overlays. Called on
     * enterLinkMode AND whenever spans change while in link mode, so spans
     * highlighted *after* entering link mode are still clickable (otherwise a
     * second link can't select the freshly-created spans).
     */
    makeOverlaysSelectable(linkColor) {
        const color = linkColor || this.linkTypeConfig[this.currentLinkType]?.color || '#6E56CF';
        document.querySelectorAll('.span-overlay-pure, .span-overlay, .span-overlay-ai, .span-highlight')
            .forEach(overlay => {
                overlay.classList.add('link-selectable');
                overlay.style.setProperty('--current-link-color', color);
                overlay.style.pointerEvents = 'auto';
                overlay.style.cursor = 'pointer';
            });
        document.querySelectorAll('.span-highlight-segment').forEach(segment => {
            segment.style.pointerEvents = 'auto';
            segment.style.cursor = 'pointer';
        });
    }

    exitLinkMode() {
        this.isLinkMode = false;
        this.container.classList.remove('link-mode-active');

        // Remove body class and CSS variable
        document.body.classList.remove('span-link-mode-active');
        document.body.style.removeProperty('--current-link-color');

        // Remove visual indicators and reset pointer events
        const spanOverlays = document.querySelectorAll('.span-overlay-pure, .span-overlay, .span-overlay-ai, .span-highlight');
        spanOverlays.forEach(overlay => {
            overlay.classList.remove('link-selectable');
            overlay.classList.remove('link-selected');
            // Reset pointer events to original state
            overlay.style.pointerEvents = 'none';
            overlay.style.cursor = '';
            // Remove color variable
            overlay.style.removeProperty('--current-link-color');
        });

        // Reset pointer events on segments
        const segments = document.querySelectorAll('.span-highlight-segment');
        segments.forEach(segment => {
            segment.style.pointerEvents = 'none';
            segment.style.cursor = '';
        });

        // Deselect radio
        const linkTypeRadios = this.container.querySelectorAll('.span-link-type-radio');
        linkTypeRadios.forEach(radio => radio.checked = false);

        this.currentLinkType = null;
        this.clearSelection();
    }

    /**
     * Extract the actual text content for a span using its start/end offsets
     */
    getSpanText(spanOverlay) {
        const start = parseInt(spanOverlay.dataset.start);
        const end = parseInt(spanOverlay.dataset.end);

        if (isNaN(start) || isNaN(end)) {
            console.warn('Span overlay missing start/end offsets');
            return '(unknown)';
        }

        // Slice the exact text the offsets were measured against. The
        // positioning strategy that produced them owns that text, so ask it
        // rather than re-deriving it here: a local re-walk silently drifts out
        // of sync with the offset basis (it used to whitespace-collapse, which
        // shifted every snippet by the whitespace preceding the span).
        // ``data-target-field`` picks the right per-field strategy in
        // multi-field displays (audio_dialogue / dialogue / MAD); flat tasks
        // fall through to the single positioningStrategy.
        const strategies = (window.spanManager && window.spanManager.fieldStrategies) || {};
        const strategy = strategies[spanOverlay.dataset.targetField] ||
            (window.spanManager && window.spanManager.positioningStrategy);
        if (strategy && typeof strategy.getCanonicalText === 'function') {
            const slice = strategy.getCanonicalText().substring(start, end);
            if (slice.trim()) return slice.trim();
        }

        // Get the original text - span-core.js stores it in #text-content's data-original-text
        const textContent = document.getElementById('text-content');
        if (textContent && textContent.hasAttribute('data-original-text')) {
            const originalText = textContent.getAttribute('data-original-text');
            // Strip HTML tags and normalize whitespace like span-core does
            const cleanText = originalText.replace(/<[^>]*>/g, '').replace(/\s+/g, ' ').trim();
            console.log(`[SpanLinkManager] getSpanText: start=${start}, end=${end}, text="${cleanText.substring(start, end)}"`);
            return cleanText.substring(start, end);
        }

        // Fallback: try to get from spanManager if available
        if (window.spanManager && typeof window.spanManager.getCanonicalText === 'function') {
            const canonicalText = window.spanManager.getCanonicalText();
            console.log(`[SpanLinkManager] getSpanText from spanManager: start=${start}, end=${end}, text="${canonicalText.substring(start, end)}"`);
            return canonicalText.substring(start, end);
        }

        // Last resort fallback
        const instanceText = document.getElementById('instance-text');
        if (instanceText) {
            const rawText = instanceText.textContent.replace(/\s+/g, ' ').trim();
            console.log(`[SpanLinkManager] getSpanText fallback: start=${start}, end=${end}, text="${rawText.substring(start, end)}"`);
            return rawText.substring(start, end);
        }

        return '(unknown)';
    }

    /**
     * The overlay's ``data-label`` is sometimes a stale "unknown" (the real
     * label is baked into the deterministic annotation id, e.g.
     * ``highlights_answer_958_980``). Recover the true label so the typed
     * source/target slots match — otherwise every directed link silently fails.
     */
    resolveSpanLabel(spanOverlay) {
        const raw = spanOverlay.dataset.label;
        if (raw && raw !== 'unknown') return raw;
        const id = spanOverlay.dataset.annotationId || spanOverlay.dataset.spanId || '';
        const known = new Set();
        Object.values(this.linkTypeConfig).forEach(cfg => {
            (cfg.sourceLabels || []).forEach(l => known.add(l));
            (cfg.targetLabels || []).forEach(l => known.add(l));
        });
        // Longest match first so "answer" wins over a hypothetical "ans".
        const match = [...known].sort((a, b) => b.length - a.length)
            .find(l => id.includes('_' + l + '_') || id.endsWith('_' + l));
        return match || raw || 'unknown';
    }

    handleSpanClick(spanOverlay) {
        const spanId = spanOverlay.dataset.spanId || spanOverlay.dataset.annotationId;
        const spanLabel = this.resolveSpanLabel(spanOverlay);

        if (!spanId) {
            console.warn('Span overlay has no span ID');
            return;
        }

        // Get the actual span text
        const spanText = this.getSpanText(spanOverlay);
        console.log(`[SpanLinkManager] Span clicked: ${spanLabel} = "${spanText}"`);

        if (!this.currentLinkType) {
            this.showConstraintError('Pick a link type above to start linking.');
            return;
        }

        // Clicking an already-selected span removes it (frees its slot).
        const existingIndex = this.selectedSpans.findIndex(s => s.id === spanId);
        if (existingIndex >= 0) {
            this.selectedSpans.splice(existingIndex, 1);
            spanOverlay.classList.remove('link-selected');
            this.updateUI();
            return;
        }

        const config = this.linkTypeConfig[this.currentLinkType] || {};
        const typed = config.directed && (config.sourceLabels.length || config.targetLabels.length);

        const maxSpans = config.maxSpans || 2;

        if (typed) {
            // Directed link: one SOURCE + up to (maxSpans-1) TARGETS (an n-ary
            // event has one trigger and several arguments). Slot-filling is by
            // span TYPE and order-independent — a clicked span drops into the
            // first open slot its label fits.
            const hasSource = this.selectedSpans.some(s => s.role === 'source');
            const targetCount = this.selectedSpans.filter(s => s.role === 'target').length;
            const maxTargets = Math.max(1, maxSpans - 1);
            const fitsSource = !config.sourceLabels.length || config.sourceLabels.includes(spanLabel);
            const fitsTarget = !config.targetLabels.length || config.targetLabels.includes(spanLabel);

            let role = null;
            if (fitsSource && !hasSource) role = 'source';
            else if (fitsTarget && targetCount < maxTargets) role = 'target';

            if (!role) {
                const needSource = !hasSource;
                const wanted = (needSource ? config.sourceLabels : config.targetLabels).join(' or ');
                const slotName = needSource ? 'source' : 'target';
                let msg;
                if (!needSource && targetCount >= maxTargets) {
                    msg = `All ${maxTargets} target slot${maxTargets > 1 ? 's are' : ' is'} full — remove one to change it.`;
                } else {
                    msg = wanted
                        ? `The ${slotName} needs a “${wanted}” span — “${spanLabel}” doesn’t fit that slot.`
                        : `That span doesn’t fit an open slot.`;
                }
                this.showConstraintError(msg);
                return;
            }
            this.selectedSpans.push({ id: spanId, label: spanLabel, text: spanText, element: spanOverlay, role });
        } else {
            // Undirected / n-ary group: fill the next open slot up to maxSpans.
            if (this.selectedSpans.length >= maxSpans) {
                this.showConstraintError(`This link connects up to ${maxSpans} spans — remove one to change it.`);
                return;
            }
            this.selectedSpans.push({ id: spanId, label: spanLabel, text: spanText, element: spanOverlay });
        }

        spanOverlay.classList.add('link-selected');
        this.updateUI();
    }

    /** Ordered spans for the current link (source before target on directed links). */
    orderedSelection() {
        const config = this.linkTypeConfig[this.currentLinkType] || {};
        if (!config.directed) return this.selectedSpans.slice();
        const byRole = (r) => this.selectedSpans.filter(s => s.role === r);
        const rest = this.selectedSpans.filter(s => !s.role);
        return [...byRole('source'), ...byRole('target'), ...rest];
    }

    showConstraintError(message) {
        // Show a temporary error message
        const existingError = this.container.querySelector('.constraint-error');
        if (existingError) existingError.remove();

        const errorDiv = document.createElement('div');
        errorDiv.className = 'constraint-error';
        errorDiv.setAttribute('role', 'alert');
        errorDiv.textContent = message;
        this.container.querySelector('.span-link-selection').appendChild(errorDiv);

        setTimeout(() => errorDiv.remove(), 3000);
    }

    selectSpanForLink(spanId) {
        const spanOverlay = document.querySelector(
            `.span-overlay-pure[data-annotation-id="${spanId}"], ` +
            `.span-overlay[data-annotation-id="${spanId}"], ` +
            `.span-highlight[data-annotation-id="${spanId}"]`
        );
        if (spanOverlay) {
            this.handleSpanClick(spanOverlay);
        }
    }

    clearSelection() {
        this.selectedSpans.forEach(span => {
            if (span.element) {
                span.element.classList.remove('link-selected');
            }
        });
        this.selectedSpans = [];
        this.updateUI();
    }

    async createLink() {
        if (!this.currentLinkType || this.selectedSpans.length < 2) {
            console.warn('Cannot create link: need link type and at least 2 spans');
            return;
        }

        const config = this.linkTypeConfig[this.currentLinkType] || {};

        // Source-before-target order for directed links (slots can be filled in
        // any click order, so normalize here).
        const ordered = this.orderedSelection();

        // Extract span positions for repair matching on reload
        const spanPositions = ordered.map(s => {
            if (s.element) {
                return {
                    start: parseInt(s.element.dataset.start),
                    end: parseInt(s.element.dataset.end)
                };
            }
            return null;
        });

        const link = {
            id: `link_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
            schema: this.schemaName,
            link_type: this.currentLinkType,
            span_ids: ordered.map(s => s.id),
            direction: config.directed ? 'directed' : 'undirected',
            properties: {
                color: config.color,
                span_labels: ordered.map(s => s.label),
                span_texts: ordered.map(s => s.text.substring(0, 30)),
                span_positions: spanPositions  // For fallback matching when span IDs change
            }
        };

        // Add to local list
        this.links.push(link);

        // Save to backend
        await this.saveLink(link);

        // Update UI
        this.updateLinkList();
        this.renderArcs();

        // Finish this link and return to "ready to link" so the annotator can
        // immediately start another: exit link mode (unchecks the radio + clears
        // selection) so re-selecting a link type fires a fresh `change` and
        // re-enables the current spans. Without this the user is stuck in link
        // mode with a checked radio and can't start a second link.
        this.exitLinkMode();

        console.log('Created link:', link);
    }

    async saveLink(link) {
        const instanceId = document.getElementById('instance_id')?.value;
        if (!instanceId) {
            console.error('No instance ID found');
            return;
        }

        try {
            const response = await fetch('/updateinstance', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    instance_id: instanceId,
                    annotations: {},  // Required for frontend format detection
                    link_annotations: [link]
                })
            });

            if (!response.ok) {
                throw new Error(`HTTP error ${response.status}`);
            }

            console.log('Link saved successfully');
        } catch (error) {
            console.error('Error saving link:', error);
        }
    }

    async deleteLink(linkId) {
        const instanceId = document.getElementById('instance_id')?.value;
        if (!instanceId) return;

        // Remove from local list
        this.links = this.links.filter(l => l.id !== linkId);

        try {
            const response = await fetch(`/api/links/${instanceId}/${linkId}`, {
                method: 'DELETE'
            });

            if (!response.ok) {
                throw new Error(`HTTP error ${response.status}`);
            }

            console.log('Link deleted successfully');
        } catch (error) {
            console.error('Error deleting link:', error);
        }

        // Update UI
        this.updateLinkList();
        this.renderArcs();
    }

    async loadExistingLinks() {
        const instanceId = document.getElementById('instance_id')?.value;
        console.log('[SpanLinkManager] loadExistingLinks called, instanceId:', instanceId);
        if (!instanceId) {
            console.warn('[SpanLinkManager] No instance ID, skipping load');
            return;
        }

        try {
            console.log('[SpanLinkManager] Fetching links from API...');
            const response = await fetch(`/api/links/${instanceId}`);
            if (!response.ok) {
                throw new Error(`HTTP error ${response.status}`);
            }

            const data = await response.json();
            this.links = data.links || [];

            // Update UI
            this.updateLinkList();

            console.log(`[SpanLinkManager] Loaded ${this.links.length} existing links:`, this.links);

            // Render arcs after waiting for spans to be created
            // Span overlays are created asynchronously by span-manager.js
            if (this.links.length > 0) {
                console.log('[SpanLinkManager] Starting waitForSpansAndRender...');
                this.waitForSpansAndRender();
            } else {
                console.log('[SpanLinkManager] No links to render');
            }
        } catch (error) {
            console.error('[SpanLinkManager] Error loading links:', error);
        }
    }

    /**
     * Try to repair orphaned link span_ids by matching with current spans.
     * This handles the case where spans were recreated with new UUIDs.
     * Uses span positions (start/end) and labels for precise matching.
     */
    repairOrphanedLinks() {
        const currentSpanIds = new Set(Object.keys(this.getSpanPositions()));
        let repaired = false;

        this.links.forEach(link => {
            const orphanedIds = link.span_ids.filter(id => !currentSpanIds.has(id));

            if (orphanedIds.length > 0) {
                console.log('[SpanLinkManager] Found orphaned span IDs in link:', orphanedIds);

                // Get all current spans from DOM
                const allOverlays = document.querySelectorAll(
                    '.span-overlay-pure, .span-overlay, .span-overlay-ai, .span-highlight'
                );

                // Build lookup by position (start, end, label) for precise matching
                const spansByPosition = new Map();
                allOverlays.forEach(overlay => {
                    const start = overlay.dataset.start;
                    const end = overlay.dataset.end;
                    const label = overlay.dataset.label;
                    const id = overlay.dataset.annotationId || overlay.dataset.spanId;
                    if (start && end && label && id) {
                        const key = `${start}_${end}_${label}`;
                        spansByPosition.set(key, id);
                    }
                });

                // Get stored span metadata
                const spanPositions = link.properties?.span_positions || [];
                const spanLabels = link.properties?.span_labels || [];

                const repairs = [];
                orphanedIds.forEach(orphanedId => {
                    const orphanedIdx = link.span_ids.indexOf(orphanedId);
                    const position = spanPositions[orphanedIdx];
                    const label = spanLabels[orphanedIdx];

                    // Try to match by position and label first (most precise)
                    if (position && label) {
                        const key = `${position.start}_${position.end}_${label}`;
                        const newId = spansByPosition.get(key);

                        if (newId && !link.span_ids.includes(newId)) {
                            console.log(`[SpanLinkManager] Repairing by position: ${orphanedId} -> ${newId} (${key})`);
                            repairs.push({ old: orphanedId, new: newId });
                            return;
                        }
                    }

                    // Fallback: match by label only if position matching fails
                    if (label) {
                        for (const overlay of allOverlays) {
                            const overlayId = overlay.dataset.annotationId || overlay.dataset.spanId;
                            const overlayLabel = overlay.dataset.label;

                            if (overlayLabel === label &&
                                !link.span_ids.includes(overlayId) &&
                                !repairs.some(r => r.new === overlayId)) {
                                console.log(`[SpanLinkManager] Repairing by label fallback: ${orphanedId} -> ${overlayId} (label: ${label})`);
                                repairs.push({ old: orphanedId, new: overlayId });
                                break;
                            }
                        }
                    }
                });

                // Apply repairs
                repairs.forEach(repair => {
                    const idx = link.span_ids.indexOf(repair.old);
                    if (idx !== -1) {
                        link.span_ids[idx] = repair.new;
                        repaired = true;
                    }
                });
            }
        });

        if (repaired) {
            console.log('[SpanLinkManager] Links repaired, re-rendering');
        }

        return repaired;
    }

    /**
     * Wait for span overlays to exist, then render arcs.
     * This handles the timing issue where span-manager.js creates spans asynchronously.
     */
    waitForSpansAndRender() {
        console.log('[SpanLinkManager] waitForSpansAndRender() called');

        if (this.links.length === 0) {
            console.log('[SpanLinkManager] No links to render');
            return;
        }

        // Get the span IDs we need to render
        const neededSpanIds = new Set();
        this.links.forEach(link => {
            link.span_ids.forEach(id => neededSpanIds.add(id));
        });

        console.log('[SpanLinkManager] Waiting for spans:', [...neededSpanIds]);

        // Check if spans exist
        const checkSpans = () => {
            const positions = this.getSpanPositions();
            const foundIds = Object.keys(positions);
            const allFound = [...neededSpanIds].every(id => foundIds.includes(id));

            console.log(`[SpanLinkManager] Span check: found ${foundIds.length} spans, need ${neededSpanIds.size}, allFound=${allFound}`);
            console.log('[SpanLinkManager] Found span IDs:', foundIds);
            console.log('[SpanLinkManager] Needed span IDs:', [...neededSpanIds]);

            if (allFound || foundIds.length > 0) {
                console.log('[SpanLinkManager] Spans found, rendering arcs');
                // Try to repair orphaned links before rendering
                this.repairOrphanedLinks();
                this.renderArcs();
                return true;
            }
            return false;
        };

        // Try immediately
        console.log('[SpanLinkManager] Attempting immediate span check...');
        if (checkSpans()) {
            console.log('[SpanLinkManager] Immediate check succeeded');
            return;
        }

        console.log('[SpanLinkManager] Immediate check failed, starting retry loop');

        // Retry with delays (spans might be loading async)
        const delays = [100, 250, 500, 1000, 2000];
        let attempt = 0;

        const retry = () => {
            if (attempt >= delays.length) {
                console.warn('[SpanLinkManager] Gave up waiting for spans after all retries');
                console.log('[SpanLinkManager] Final span overlay count:', document.querySelectorAll('.span-overlay-pure, .span-overlay').length);
                // Render anyway to show the link list even if arcs can't be drawn
                this.renderArcs();
                return;
            }

            setTimeout(() => {
                console.log(`[SpanLinkManager] Retry attempt ${attempt + 1}/${delays.length} after ${delays[attempt]}ms`);
                if (!checkSpans()) {
                    attempt++;
                    retry();
                } else {
                    console.log('[SpanLinkManager] Retry succeeded on attempt', attempt + 1);
                }
            }, delays[attempt]);
        };

        retry();
    }

    /**
     * Escape HTML to prevent XSS
     */
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    /**
     * Truncate text with ellipsis
     */
    truncateText(text, maxLength = 25) {
        if (!text) return '';
        const escaped = this.escapeHtml(text);
        if (text.length <= maxLength) return escaped;
        return this.escapeHtml(text.substring(0, maxLength)) + '...';
    }

    /** Count of highlighted span overlays currently on the page. */
    spanOverlayCount() {
        return document.querySelectorAll(
            '.span-overlay-pure, .span-overlay, .span-overlay-ai, .span-highlight').length;
    }

    updateUI() {
        if (this.selectedSpansDisplay) {
            this.selectedSpansDisplay.innerHTML = this.renderSlotsOrGuidance();
        }

        // Create enables once every required slot is filled.
        if (this.createButton) {
            this.createButton.disabled = !this.canCreateLink();
        }

        if (this.linkDataInput) {
            this.linkDataInput.value = JSON.stringify(this.links);
        }
    }

    canCreateLink() {
        if (!this.currentLinkType) return false;
        const config = this.linkTypeConfig[this.currentLinkType] || {};
        if (config.directed && (config.sourceLabels.length || config.targetLabels.length)) {
            // Need the source and at least one target (extra target slots are optional).
            return this.selectedSpans.some(s => s.role === 'source') &&
                   this.selectedSpans.some(s => s.role === 'target');
        }
        return this.selectedSpans.length >= 2;
    }

    /**
     * Slot descriptors { role, labels, filled, head, optional } for the current
     * link type. Directed links have one SOURCE + (maxSpans-1) TARGET slots
     * (n-ary events); undirected links have maxSpans generic slots.
     */
    linkSlots() {
        const config = this.linkTypeConfig[this.currentLinkType] || {};
        const maxSpans = config.maxSpans || 2;

        if (config.directed && (config.sourceLabels.length || config.targetLabels.length)) {
            const slots = [{
                role: 'source', head: 'From', labels: config.sourceLabels,
                filled: this.selectedSpans.find(s => s.role === 'source'),
            }];
            const targets = this.selectedSpans.filter(s => s.role === 'target');
            const nTargets = Math.max(1, maxSpans - 1);
            for (let i = 0; i < nTargets; i++) {
                slots.push({
                    role: 'target',
                    head: nTargets > 1 ? `To ${i + 1}` : 'To',
                    labels: config.targetLabels,
                    filled: targets[i],
                    optional: i >= 1,   // first target required, rest optional
                });
            }
            return slots;
        }

        // Undirected / n-ary group.
        return Array.from({ length: maxSpans }, (_, i) => ({
            role: null, head: `Span ${i + 1}`, labels: [],
            filled: this.selectedSpans[i],
            optional: i >= 2,   // first two required for a link, rest optional
        }));
    }

    renderSlotsOrGuidance() {
        // Not linking yet — guide the two prerequisites in order.
        if (!this.isLinkMode || !this.currentLinkType) {
            if (this.spanOverlayCount() === 0) {
                return '<p class="span-link-guide"><span class="span-link-step">1</span>' +
                    'Highlight spans first: pick a label above the transcript (e.g. ' +
                    '<strong>question</strong> / <strong>answer</strong>) and drag across the text. ' +
                    'Then <span class="span-link-step">2</span> choose a link type here to connect them.</p>';
            }
            return '<p class="span-link-guide"><span class="span-link-step">2</span>' +
                'Choose a <strong>link type</strong> above to start connecting your highlighted spans.</p>';
        }

        // In link mode — show the slots to fill (order-independent).
        const slots = this.linkSlots();
        const noSpans = this.spanOverlayCount() === 0;
        const slotsHtml = slots.map((slot) => {
            const heading = slot.head + (slot.optional ? '<span class="span-link-slot-opt"> (optional)</span>' : '');
            const want = slot.labels && slot.labels.length
                ? slot.labels.map(l => `<span class="span-link-slot-type">${this.escapeHtml(l)}</span>`).join(' / ')
                : '<span class="span-link-slot-type">any span</span>';
            if (slot.filled) {
                const txt = (slot.filled.text || '').trim();
                const quoted = txt ? `<span class="selected-span-text">“${this.truncateText(txt, 22)}”</span>` : '';
                return `<div class="span-link-slot is-filled" data-role="${slot.role || ''}">
                        <span class="span-link-slot-head">${heading}</span>
                        <span class="span-link-slot-fill"><span class="selected-span-label">${this.escapeHtml(slot.filled.label)}</span>
                        ${quoted}</span>
                        <button type="button" class="remove-span-btn" title="Remove"
                            onclick="window.spanLinkManagers['${this.schemaName}'].deselectSpan('${slot.filled.id}')">&times;</button>
                    </div>`;
            }
            return `<div class="span-link-slot is-empty" data-role="${slot.role || ''}">
                    <span class="span-link-slot-head">${heading}</span>
                    <span class="span-link-slot-hint">${noSpans ? 'highlight' : 'click'} a ${want} span</span>
                </div>`;
        }).join('');

        const hint = noSpans
            ? '<p class="span-link-guide span-link-guide-sub">No highlighted spans yet — press <kbd>Esc</kbd> to exit and highlight some first.</p>'
            : (this.canCreateLink()
                ? '<p class="span-link-guide span-link-guide-sub">Ready — click <strong>Create Link</strong> (or keep adding to optional slots).</p>'
                : '<p class="span-link-guide span-link-guide-sub">Click a highlighted span to drop it into its slot (any order).</p>');

        return `<div class="span-link-slots">${slotsHtml}</div>${hint}`;
    }

    deselectSpan(spanId) {
        const span = this.selectedSpans.find(s => s.id === spanId);
        if (span && span.element) {
            span.element.classList.remove('link-selected');
        }
        this.selectedSpans = this.selectedSpans.filter(s => s.id !== spanId);
        this.updateUI();
    }

    updateLinkList() {
        if (!this.linkList) return;

        if (this.links.length === 0) {
            this.linkList.innerHTML = '<p class="no-links-message">No links created yet</p>';
            return;
        }

        const esc = (s) => this.escapeHtml ? this.escapeHtml(s) : String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

        const linksHtml = this.links.map((link, li) => {
            const config = this.linkTypeConfig[link.link_type] || {};
            const color = config.color || '#dc2626';
            const directed = link.direction === 'directed' || config.directed;
            const arrow = directed ? '→' : '↔';
            const labels = link.properties?.span_labels || [];
            const texts = link.properties?.span_texts || [];
            const ids = link.span_ids || [];
            const num = li + 1;

            // One chip per linked span: role dot + label + quoted snippet.
            const chips = ids.map((id, i) => {
                const label = labels[i] || this.resolveSpanLabel(this.overlayById(id) || {dataset: {}}) || 'span';
                const text = (texts[i] || '').trim();
                const snippet = text ? `<span class="link-chip-text">“${this.truncateText(text, 26)}”</span>` : '';
                const roleCls = directed ? (i === 0 ? 'is-source' : 'is-target') : '';
                return `<span class="link-chip ${roleCls}">${esc(label)}${snippet}</span>`;
            }).join(`<span class="link-arrow" aria-hidden="true">${arrow}</span>`);

            return `
                <div class="link-item" data-link-id="${esc(link.id)}" style="--link-color: ${color}"
                     tabindex="0" role="button"
                     aria-label="Link ${num}: ${esc(link.link_type)}. Click to locate its spans in the transcript."
                     onclick="window.spanLinkManagers['${this.schemaName}'].flashLink('${esc(link.id)}')"
                     onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();window.spanLinkManagers['${this.schemaName}'].flashLink('${esc(link.id)}')}">
                    <span class="link-num-badge" style="background:${color}">${num}</span>
                    <div class="link-info">
                        <span class="link-type-badge" style="background-color:${color}">${esc(link.link_type)} <span class="link-arrow-in-badge">${arrow}</span></span>
                        <span class="link-spans">${chips}</span>
                    </div>
                    <button type="button" class="delete-link-btn"
                            onclick="event.stopPropagation();window.spanLinkManagers['${this.schemaName}'].deleteLink('${esc(link.id)}')"
                            title="Delete this link" aria-label="Delete link ${num}">
                        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none"
                             stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <polyline points="3 6 5 6 21 6"></polyline>
                            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                        </svg>
                    </button>
                </div>
            `;
        }).join('');

        this.linkList.innerHTML = linksHtml;
    }

    /**
     * Scroll the first span of a link into view and pulse all its spans, so the
     * annotator can see which highlights a listed link connects.
     */
    flashLink(linkId) {
        const link = this.links.find(l => l.id === linkId);
        if (!link) return;
        const overlays = (link.span_ids || []).map(id => this.overlayById(id)).filter(Boolean);
        if (!overlays.length) return;
        const color = (this.linkTypeConfig[link.link_type] || {}).color || '#f59e0b';
        const firstSeg = overlays[0].querySelector('.span-highlight-segment') || overlays[0];
        if (firstSeg.scrollIntoView) firstSeg.scrollIntoView({ behavior: 'smooth', block: 'center' });
        overlays.forEach(ov => {
            ov.querySelectorAll('.span-highlight-segment').forEach(seg => {
                seg.style.setProperty('--link-color', color);
                seg.classList.add('span-link-flash');
                setTimeout(() => seg.classList.remove('span-link-flash'), 1400);
            });
        });
        // Also emphasize the connector briefly.
        if (this.simpleArcSvg) {
            this.simpleArcSvg.classList.add('span-link-arcs-emphasis');
            setTimeout(() => this.simpleArcSvg.classList.remove('span-link-arcs-emphasis'), 1400);
        }
    }

    // ---- Simple connector arcs for instance_display / bubble layouts --------

    ensureSimpleArcSvg() {
        if (!this.arcHost) return null;
        const SVGNS = 'http://www.w3.org/2000/svg';
        let svg = this.arcHost.querySelector(':scope > svg.span-link-simple-arcs');
        if (!svg) {
            svg = document.createElementNS(SVGNS, 'svg');
            svg.setAttribute('class', 'span-link-simple-arcs');
            svg.style.cssText =
                'position:absolute;inset:0;width:100%;height:100%;pointer-events:none;overflow:visible;z-index:6;';
            this.arcHost.appendChild(svg);
        }
        this.simpleArcSvg = svg;
        return svg;
    }

    overlayById(id) {
        return document.querySelector(
            `.span-overlay-pure[data-annotation-id="${CSS.escape(id)}"],` +
            `.span-overlay[data-annotation-id="${CSS.escape(id)}"],` +
            `.span-overlay-ai[data-annotation-id="${CSS.escape(id)}"],` +
            `.span-highlight[data-annotation-id="${CSS.escape(id)}"]`);
    }

    /**
     * A span overlay's own box is 0×0 — its geometry lives in the
     * ``.span-highlight-segment`` children (same reason ``getSpanPositions``
     * reads segments). Return the segment-union rect relative to ``arcHost``,
     * or null if the span isn't currently laid out.
     */
    spanRectRel(id) {
        const overlay = this.overlayById(id);
        if (!overlay) return null;
        const hostRect = this.arcHost.getBoundingClientRect();
        const segs = overlay.querySelectorAll('.span-highlight-segment');
        let l = Infinity, t = Infinity, r = -Infinity, b = -Infinity;
        segs.forEach(seg => {
            const sr = seg.getBoundingClientRect();
            if (sr.width > 0 && sr.height > 0) {
                l = Math.min(l, sr.left); t = Math.min(t, sr.top);
                r = Math.max(r, sr.right); b = Math.max(b, sr.bottom);
            }
        });
        if (l === Infinity) {
            const or = overlay.getBoundingClientRect();
            if (or.width === 0 && or.height === 0) return null;
            l = or.left; t = or.top; r = or.right; b = or.bottom;
        }
        return { x: l - hostRect.left, y: t - hostRect.top, w: r - l, h: b - t };
    }

    renderSimpleConnectors() {
        const svg = this.ensureSimpleArcSvg();
        if (!svg) return;
        svg.innerHTML =
            '<defs><marker id="ln-arrow" markerWidth="10" markerHeight="8" refX="8" refY="4" orient="auto">' +
            '<polygon points="0 0, 10 4, 0 8" fill="context-stroke"></polygon></marker></defs>';

        if (!this.links.length) return;
        const midX = this.arcHost.getBoundingClientRect().width / 2;

        this.links.forEach((link, li) => {
            const color = (this.linkTypeConfig[link.link_type] || {}).color || '#dc2626';
            const directed = link.direction === 'directed';
            const ids = link.span_ids || [];
            const num = li + 1;
            const a = this.spanRectRel(ids[0]);
            if (a) this.drawSpanBadge(svg, a, midX, num, color);
            if (!a) return;
            for (let i = 1; i < ids.length; i++) {
                const b = this.spanRectRel(ids[i]);
                if (!b) continue;
                this.drawConnector(svg, a, b, color, directed, midX);
                this.drawSpanBadge(svg, b, midX, num, color);
            }
        });
    }

    /**
     * Route the connector vertically *between* the two spans, bulging toward the
     * pane's horizontal center. Staying inside the [sy, ty] band avoids the
     * scroll-pane clipping an "above the top span" hump would suffer, and the
     * bulge stays within host width so ``overflow-x:hidden`` doesn't cut it.
     */
    drawConnector(svg, a, b, color, directed, midX) {
        const SVGNS = 'http://www.w3.org/2000/svg';
        // Anchor on the edge of each span that faces the pane center.
        const anchor = (r) => {
            const cx = r.x + r.w / 2;
            const x = cx <= midX ? r.x + r.w : r.x;   // right edge if left of center, else left edge
            return { x, y: r.y + r.h / 2, side: cx <= midX ? 1 : -1 };
        };
        const s = anchor(a), t = anchor(b);
        // Bulge control x: push toward center, a little past it, clamped in-bounds.
        const bulge = Math.min(60, 24 + Math.abs(t.y - s.y) / 6);
        const cxS = Math.max(6, Math.min(midX * 2 - 6, s.x + s.side * bulge));
        const cxT = Math.max(6, Math.min(midX * 2 - 6, t.x + t.side * bulge));
        const path = document.createElementNS(SVGNS, 'path');
        path.setAttribute('d', `M ${s.x} ${s.y} C ${cxS} ${s.y}, ${cxT} ${t.y}, ${t.x} ${t.y}`);
        path.setAttribute('fill', 'none');
        path.setAttribute('stroke', color);
        path.setAttribute('stroke-width', '2');
        path.setAttribute('stroke-linecap', 'round');
        // Keep the connector semi-transparent so it reads as an overlay and does
        // not obscure the transcript text it crosses.
        path.setAttribute('opacity', '0.45');
        if (directed) path.setAttribute('marker-end', 'url(#ln-arrow)');
        svg.appendChild(path);
    }

    /**
     * A numbered chip pinned to a linked span, on its center-facing edge. This
     * is the scroll-proof identity marker: even when a link's partner span is
     * scrolled out of view, the badge shows this span belongs to link #N.
     */
    drawSpanBadge(svg, r, midX, num, color) {
        const SVGNS = 'http://www.w3.org/2000/svg';
        const cx = r.x + r.w / 2;
        const bx = cx <= midX ? r.x + r.w + 9 : r.x - 9;
        const by = r.y + r.h / 2;
        const g = document.createElementNS(SVGNS, 'g');
        g.setAttribute('class', 'span-link-badge');
        const circ = document.createElementNS(SVGNS, 'circle');
        circ.setAttribute('cx', bx); circ.setAttribute('cy', by); circ.setAttribute('r', '8');
        circ.setAttribute('fill', color);
        circ.setAttribute('stroke', '#fff'); circ.setAttribute('stroke-width', '1.5');
        const txt = document.createElementNS(SVGNS, 'text');
        txt.setAttribute('x', bx); txt.setAttribute('y', by + 0.5);
        txt.setAttribute('text-anchor', 'middle');
        txt.setAttribute('dominant-baseline', 'central');
        txt.setAttribute('font-size', '10'); txt.setAttribute('font-weight', '700');
        txt.setAttribute('fill', '#fff');
        txt.textContent = String(num);
        g.appendChild(circ); g.appendChild(txt);
        svg.appendChild(g);
    }

    renderArcs() {
        if (this.simpleArcs) {
            if (this.showArcsEnabled === false) return;
            this.renderSimpleConnectors();
            return;
        }
        console.log('[SpanLinkManager] renderArcs() called');
        console.log('[SpanLinkManager] arcsContainer exists:', !!this.arcsContainer);
        console.log('[SpanLinkManager] arcSpacer exists:', !!this.arcSpacer);
        console.log('[SpanLinkManager] textWrapper exists:', !!this.textWrapper);
        console.log('[SpanLinkManager] links count:', this.links.length);

        if (!this.arcsContainer) {
            console.error('[SpanLinkManager] No arcsContainer! createArcsContainer may have failed');
            return;
        }

        // Clear existing arcs
        this.arcsContainer.innerHTML = '';

        if (this.links.length === 0) {
            // Reset to minimum spacer height when no links
            console.log('[SpanLinkManager] No links, resetting spacer height');
            this.updateArcSpacerHeight(60);
            return;
        }

        // Get span positions relative to text wrapper
        const spanPositions = this.getSpanPositions();
        console.log('[SpanLinkManager] Span positions:', spanPositions);
        console.log('[SpanLinkManager] Links to render:', this.links);

        // First pass: calculate maximum arc height needed
        let maxArcHeight = 60; // minimum
        this.links.forEach(link => {
            const spanIds = link.span_ids;
            if (spanIds.length >= 2) {
                const pos1 = spanPositions[spanIds[0]];
                const pos2 = spanPositions[spanIds[1]];
                if (pos1 && pos2) {
                    const x1 = pos1.x + pos1.width / 2;
                    const x2 = pos2.x + pos2.width / 2;
                    // Arc height is proportional to horizontal distance
                    const arcHeight = Math.max(40, Math.min(Math.abs(x2 - x1) / 2, 120));
                    maxArcHeight = Math.max(maxArcHeight, arcHeight);
                }
            }
        });

        // Update arc spacer height
        this.updateArcSpacerHeight(maxArcHeight);

        // Get spacer height for positioning arcs from bottom of spacer
        const spacerHeight = parseInt(this.arcSpacer.style.height) || (maxArcHeight + 40);

        // Create SVG sized to fit the spacer
        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('width', '100%');
        svg.setAttribute('height', spacerHeight);
        svg.style.cssText = 'position: absolute; bottom: 0; left: 0; pointer-events: none; overflow: visible;';

        // Add arrow marker definition
        const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
        defs.innerHTML = `
            <marker id="link-arrowhead" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
                <polygon points="0 0, 10 3.5, 0 7" fill="currentColor" />
            </marker>
        `;
        svg.appendChild(defs);

        // Draw arcs for each link
        // Arcs start at bottom of spacer (y = spacerHeight) and curve upward
        this.links.forEach(link => {
            const config = this.linkTypeConfig[link.link_type] || {};
            const color = config.color || '#dc2626';
            const spanIds = link.span_ids;

            if (spanIds.length < 2) return;

            // Binary link - draw arc
            if (spanIds.length === 2) {
                const pos1 = spanPositions[spanIds[0]];
                const pos2 = spanPositions[spanIds[1]];

                console.log('[SpanLinkManager] Drawing arc between:', spanIds[0], pos1, 'and', spanIds[1], pos2);

                if (!pos1 || !pos2) {
                    console.log('[SpanLinkManager] Missing position, skipping arc');
                    return;
                }

                // X positions from span centers
                const x1 = pos1.x + pos1.width / 2;
                const x2 = pos2.x + pos2.width / 2;

                // Y positions: arcs start at bottom of spacer and curve up
                const anchorY = spacerHeight; // Bottom of spacer where arcs connect to text

                console.log('[SpanLinkManager] Arc coordinates: x1=', x1, 'x2=', x2, 'anchorY=', anchorY, 'spacerHeight=', spacerHeight);

                const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');

                // Check if spans are on different lines (Y positions differ significantly)
                const sameLineThreshold = 10; // pixels
                const isMultiLine = Math.abs(pos2.y - pos1.y) > sameLineThreshold;

                // Get multi-line mode from config
                const multiLineMode = this.container.dataset.multiLineMode || 'bracket';

                let pathD;
                let labelY;
                let labelX = (x1 + x2) / 2;

                if (isMultiLine && multiLineMode === 'bracket') {
                    // Bracket-style arc for multi-line: goes up, across at top, then down
                    const cornerRadius = 8;
                    const topY = 20; // Position near top of spacer

                    const goingRight = x2 > x1;

                    if (goingRight) {
                        pathD = `M ${x1} ${anchorY}
                                 L ${x1} ${topY + cornerRadius}
                                 Q ${x1} ${topY}, ${x1 + cornerRadius} ${topY}
                                 L ${x2 - cornerRadius} ${topY}
                                 Q ${x2} ${topY}, ${x2} ${topY + cornerRadius}
                                 L ${x2} ${anchorY}`;
                    } else {
                        pathD = `M ${x1} ${anchorY}
                                 L ${x1} ${topY + cornerRadius}
                                 Q ${x1} ${topY}, ${x1 - cornerRadius} ${topY}
                                 L ${x2 + cornerRadius} ${topY}
                                 Q ${x2} ${topY}, ${x2} ${topY + cornerRadius}
                                 L ${x2} ${anchorY}`;
                    }

                    labelY = topY - 5;
                    labelX = (x1 + x2) / 2;
                } else {
                    // Same-line arc: simple quadratic bezier curve
                    const midX = (x1 + x2) / 2;
                    const arcHeight = Math.max(40, Math.min(Math.abs(x2 - x1) / 2, 120));
                    const controlY = anchorY - arcHeight; // Control point above anchor

                    pathD = `M ${x1} ${anchorY} Q ${midX} ${controlY} ${x2} ${anchorY}`;
                    labelY = controlY - 5;
                    labelX = midX;
                }

                path.setAttribute('d', pathD);
                path.setAttribute('fill', 'none');
                path.setAttribute('stroke', color);
                path.setAttribute('stroke-width', '2.5');
                path.setAttribute('class', 'span-link-arc');
                path.dataset.linkId = link.id;

                if (config.directed) {
                    path.setAttribute('marker-end', 'url(#link-arrowhead)');
                    path.style.color = color;
                }

                svg.appendChild(path);

                // Add label on arc if showLabels is enabled
                const showLabels = this.container.dataset.showLabels !== 'false';
                if (showLabels && link.link_type) {
                    // Create a unique path ID for textPath reference
                    const pathId = `arc-path-${link.id}`;
                    path.setAttribute('id', pathId);

                    // labelX and labelY were already calculated above for both modes

                    // Create text element for the label
                    const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
                    text.setAttribute('x', labelX);
                    text.setAttribute('y', labelY);
                    text.setAttribute('text-anchor', 'middle');
                    text.setAttribute('class', 'span-link-label');
                    text.setAttribute('fill', color);
                    text.style.fontSize = '11px';
                    text.style.fontWeight = '500';
                    text.style.pointerEvents = 'none';
                    text.textContent = link.link_type;

                    // Add background rect for readability
                    const bbox = { width: link.link_type.length * 7 + 6, height: 14 };
                    const bgRect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
                    bgRect.setAttribute('x', labelX - bbox.width / 2);
                    bgRect.setAttribute('y', labelY - 10);
                    bgRect.setAttribute('width', bbox.width);
                    bgRect.setAttribute('height', bbox.height);
                    bgRect.setAttribute('fill', 'white');
                    bgRect.setAttribute('rx', '3');
                    bgRect.setAttribute('class', 'span-link-label-bg');
                    bgRect.style.pointerEvents = 'none';

                    svg.appendChild(bgRect);
                    svg.appendChild(text);
                }
            } else {
                // N-ary link - connect to central point
                const validPositions = spanIds.map(id => spanPositions[id]).filter(Boolean);
                if (validPositions.length < 2) return;

                const centerX = validPositions.reduce((sum, p) => sum + p.x + p.width / 2, 0) / validPositions.length;
                const centerY = spacerHeight / 2; // Center of spacer

                spanIds.forEach(spanId => {
                    const pos = spanPositions[spanId];
                    if (!pos) return;

                    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
                    line.setAttribute('x1', pos.x + pos.width / 2);
                    line.setAttribute('y1', spacerHeight); // Bottom of spacer
                    line.setAttribute('x2', centerX);
                    line.setAttribute('y2', centerY);
                    line.setAttribute('stroke', color);
                    line.setAttribute('stroke-width', '2');
                    line.setAttribute('class', 'span-link-arc');
                    line.dataset.linkId = link.id;
                    svg.appendChild(line);
                });

                const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
                circle.setAttribute('cx', centerX);
                circle.setAttribute('cy', centerY);
                circle.setAttribute('r', '5');
                circle.setAttribute('fill', color);
                circle.setAttribute('class', 'span-link-node');
                circle.dataset.linkId = link.id;
                svg.appendChild(circle);
            }
        });

        this.arcsContainer.appendChild(svg);
    }

    getSpanPositions() {
        const positions = {};

        // Get positions relative to text wrapper (not instance-text)
        const referenceContainer = this.textWrapper || document.getElementById('instance-text');
        console.log('[SpanLinkManager] getSpanPositions: referenceContainer:', referenceContainer?.className || referenceContainer?.id);
        if (!referenceContainer) {
            console.warn('[SpanLinkManager] getSpanPositions: No reference container!');
            return positions;
        }

        const containerRect = referenceContainer.getBoundingClientRect();
        console.log('[SpanLinkManager] getSpanPositions: containerRect:', containerRect);

        // Count span overlays
        const allOverlays = document.querySelectorAll('.span-overlay-pure, .span-overlay, .span-overlay-ai, .span-highlight');
        console.log('[SpanLinkManager] getSpanPositions: Total overlays found:', allOverlays.length);

        document.querySelectorAll('.span-overlay-pure, .span-overlay, .span-overlay-ai, .span-highlight').forEach(overlay => {
            const spanId = overlay.dataset.spanId || overlay.dataset.annotationId;
            if (!spanId) return;

            // The overlay container may have zero dimensions - get bounds from highlight segments
            const segments = overlay.querySelectorAll('.span-highlight-segment');
            let rect;

            if (segments.length > 0) {
                // Calculate bounding box from all segments (handles multi-line spans)
                let minLeft = Infinity, minTop = Infinity, maxRight = -Infinity, maxBottom = -Infinity;
                segments.forEach(segment => {
                    const segRect = segment.getBoundingClientRect();
                    if (segRect.width > 0 && segRect.height > 0) {
                        minLeft = Math.min(minLeft, segRect.left);
                        minTop = Math.min(minTop, segRect.top);
                        maxRight = Math.max(maxRight, segRect.right);
                        maxBottom = Math.max(maxBottom, segRect.bottom);
                    }
                });

                if (minLeft !== Infinity) {
                    rect = {
                        left: minLeft,
                        top: minTop,
                        right: maxRight,
                        bottom: maxBottom,
                        width: maxRight - minLeft,
                        height: maxBottom - minTop
                    };
                }
            }

            // Fallback to overlay bounds if no segments found
            if (!rect) {
                rect = overlay.getBoundingClientRect();
            }

            if (rect.width > 0 && rect.height > 0) {
                positions[spanId] = {
                    x: rect.left - containerRect.left,
                    y: rect.top - containerRect.top,
                    width: rect.width,
                    height: rect.height
                };
            }
        });

        return positions;
    }

    toggleArcsVisibility(visible) {
        this.showArcsEnabled = visible;
        if (this.arcsContainer) {
            this.arcsContainer.style.display = visible ? 'block' : 'none';
        }
        if (this.simpleArcSvg) {
            this.simpleArcSvg.style.display = visible ? '' : 'none';
        }
        if (this.simpleArcs && visible) this.renderSimpleConnectors();
    }
}

// Global registry of span link managers
window.spanLinkManagers = window.spanLinkManagers || {};

// Initialize span link managers when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    const linkContainers = document.querySelectorAll('.span-link-container');
    linkContainers.forEach(container => {
        const schemaName = container.id;
        const spanSchemaName = container.dataset.spanSchema;
        if (schemaName && spanSchemaName) {
            window.spanLinkManagers[schemaName] = new SpanLinkManager(schemaName, spanSchemaName);
        }
    });
});

// Re-render arcs on window resize
window.addEventListener('resize', function() {
    Object.values(window.spanLinkManagers || {}).forEach(manager => {
        manager.renderArcs();
    });
});

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

        // Enable pointer events and highlight clickable spans
        const spanOverlays = document.querySelectorAll('.span-overlay-pure, .span-overlay, .span-overlay-ai, .span-highlight');
        console.log(`[SpanLinkManager] Found ${spanOverlays.length} span overlays to make selectable`);
        spanOverlays.forEach(overlay => {
            overlay.classList.add('link-selectable');
            // Set the link color on each overlay for CSS to use
            overlay.style.setProperty('--current-link-color', linkColor);
            // Enable pointer events so we can click on them
            overlay.style.pointerEvents = 'auto';
            overlay.style.cursor = 'pointer';
        });

        // Also enable pointer events on highlight segments inside overlays
        const segments = document.querySelectorAll('.span-highlight-segment');
        segments.forEach(segment => {
            segment.style.pointerEvents = 'auto';
            segment.style.cursor = 'pointer';
        });

        console.log(`[SpanLinkManager] Entered link mode with type: ${this.currentLinkType}`);
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

    handleSpanClick(spanOverlay) {
        const spanId = spanOverlay.dataset.spanId || spanOverlay.dataset.annotationId;
        const spanLabel = spanOverlay.dataset.label;

        if (!spanId) {
            console.warn('Span overlay has no span ID');
            return;
        }

        // Get the actual span text
        const spanText = this.getSpanText(spanOverlay);
        console.log(`[SpanLinkManager] Span clicked: ${spanLabel} = "${spanText}"`);

        // Validate span label constraints
        if (this.currentLinkType && this.linkTypeConfig[this.currentLinkType]) {
            const config = this.linkTypeConfig[this.currentLinkType];
            const isFirst = this.selectedSpans.length === 0;

            // Check source label constraint for first span (directed links)
            if (isFirst && config.directed && config.sourceLabels.length > 0) {
                if (!config.sourceLabels.includes(spanLabel)) {
                    console.log(`Span label ${spanLabel} not allowed as source`);
                    this.showConstraintError(`Source must be: ${config.sourceLabels.join(', ')}`);
                    return;
                }
            }

            // Check target label constraint for subsequent spans (directed links)
            if (!isFirst && config.directed && config.targetLabels.length > 0) {
                if (!config.targetLabels.includes(spanLabel)) {
                    console.log(`Span label ${spanLabel} not allowed as target`);
                    this.showConstraintError(`Target must be: ${config.targetLabels.join(', ')}`);
                    return;
                }
            }
        }

        // Toggle selection
        const existingIndex = this.selectedSpans.findIndex(s => s.id === spanId);
        if (existingIndex >= 0) {
            // Deselect
            this.selectedSpans.splice(existingIndex, 1);
            spanOverlay.classList.remove('link-selected');
        } else {
            // Check max spans limit
            const maxSpans = this.linkTypeConfig[this.currentLinkType]?.maxSpans || 2;
            if (this.selectedSpans.length >= maxSpans) {
                this.showConstraintError(`Maximum ${maxSpans} spans for this link type`);
                return;
            }

            // Select - use extracted text, not textContent
            this.selectedSpans.push({
                id: spanId,
                label: spanLabel,
                text: spanText,
                element: spanOverlay
            });
            spanOverlay.classList.add('link-selected');
        }

        this.updateUI();
    }

    showConstraintError(message) {
        // Show a temporary error message
        const existingError = this.container.querySelector('.constraint-error');
        if (existingError) existingError.remove();

        const errorDiv = document.createElement('div');
        errorDiv.className = 'constraint-error';
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

        // Extract span positions for repair matching on reload
        const spanPositions = this.selectedSpans.map(s => {
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
            span_ids: this.selectedSpans.map(s => s.id),
            direction: config.directed ? 'directed' : 'undirected',
            properties: {
                color: config.color,
                span_labels: this.selectedSpans.map(s => s.label),
                span_texts: this.selectedSpans.map(s => s.text.substring(0, 30)),
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
        this.clearSelection();

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

    updateUI() {
        // Update selected spans display
        if (this.selectedSpansDisplay) {
            if (this.selectedSpans.length === 0) {
                const instruction = this.isLinkMode
                    ? '<p class="link-mode-instruction">Click on <strong>highlighted spans</strong> to select them for linking. Press <kbd>Esc</kbd> or click "Exit Link Mode" to create new spans.</p>'
                    : '<p class="no-selection-message">Select a link type to start linking spans</p>';
                this.selectedSpansDisplay.innerHTML = instruction;
            } else {
                const spansHtml = this.selectedSpans.map((span, index) => {
                    const config = this.linkTypeConfig[this.currentLinkType] || {};
                    let roleLabel = '';
                    if (config.directed) {
                        roleLabel = index === 0 ? '<span class="span-role">(source)</span>' : '<span class="span-role">(target)</span>';
                    }
                    const displayText = this.truncateText(span.text, 25);
                    return `
                        <div class="selected-span-item" data-span-id="${span.id}">
                            <span class="selected-span-label">${this.escapeHtml(span.label)}</span>
                            <span class="selected-span-text">"${displayText}"</span>
                            ${roleLabel}
                            <button type="button" class="remove-span-btn" onclick="window.spanLinkManagers['${this.schemaName}'].deselectSpan('${span.id}')">&times;</button>
                        </div>
                    `;
                }).join('');
                this.selectedSpansDisplay.innerHTML = spansHtml;
            }
        }

        // Update create button state
        if (this.createButton) {
            const minSpans = 2;
            this.createButton.disabled = !this.currentLinkType || this.selectedSpans.length < minSpans;
        }

        // Update hidden input with link data
        if (this.linkDataInput) {
            this.linkDataInput.value = JSON.stringify(this.links);
        }
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

        const linksHtml = this.links.map(link => {
            const config = this.linkTypeConfig[link.link_type] || {};
            const spanTexts = link.properties?.span_texts || link.span_ids;
            const directionIcon = config.directed ? '→' : '↔';

            return `
                <div class="link-item" data-link-id="${link.id}" style="--link-color: ${config.color || '#dc2626'}">
                    <div class="link-info">
                        <span class="link-type-badge" style="background-color: ${config.color || '#dc2626'}">${link.link_type}</span>
                        <span class="link-spans">
                            ${spanTexts.join(` <span class="link-direction">${directionIcon}</span> `)}
                        </span>
                    </div>
                    <button type="button" class="delete-link-btn" onclick="window.spanLinkManagers['${this.schemaName}'].deleteLink('${link.id}')"
                            title="Delete link">
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

    renderArcs() {
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
        if (this.arcsContainer) {
            this.arcsContainer.style.display = visible ? 'block' : 'none';
        }
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

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
        if (!this.container) {
            console.warn(`SpanLinkManager: Container not found for schema ${this.schemaName}`);
            return;
        }

        // Parse link type configurations
        this.parseLinkTypeConfigs();

        // Set up event listeners
        this.setupEventListeners();

        // Create arc rendering container
        this.createArcsContainer();

        // Load existing links if any
        this.loadExistingLinks();

        console.log(`SpanLinkManager initialized for schema: ${this.schemaName}`);
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

        // Clear button
        if (this.clearButton) {
            this.clearButton.addEventListener('click', () => this.clearSelection());
        }

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
        // Check if arc visualization is enabled
        const showArcs = this.container.dataset.showArcs !== 'false';
        if (!showArcs) return;

        // Find the instance text container to place arcs relative to it
        const instanceText = document.getElementById('instance-text');
        if (!instanceText) return;

        // Create SVG container for arcs
        this.arcsContainer = document.createElement('div');
        this.arcsContainer.id = `${this.schemaName}_arcs`;
        this.arcsContainer.className = 'span-link-arcs-container';
        this.arcsContainer.style.cssText = `
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            pointer-events: none;
            overflow: visible;
            z-index: 100;
        `;

        // Make instance-text position relative if not already
        const instanceTextStyle = window.getComputedStyle(instanceText);
        if (instanceTextStyle.position === 'static') {
            instanceText.style.position = 'relative';
        }

        instanceText.appendChild(this.arcsContainer);
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

        const link = {
            id: `link_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
            schema: this.schemaName,
            link_type: this.currentLinkType,
            span_ids: this.selectedSpans.map(s => s.id),
            direction: config.directed ? 'directed' : 'undirected',
            properties: {
                color: config.color,
                span_labels: this.selectedSpans.map(s => s.label),
                span_texts: this.selectedSpans.map(s => s.text.substring(0, 30))
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
        if (!instanceId) return;

        try {
            const response = await fetch(`/api/links/${instanceId}`);
            if (!response.ok) {
                throw new Error(`HTTP error ${response.status}`);
            }

            const data = await response.json();
            this.links = data.links || [];

            // Update UI
            this.updateLinkList();
            this.renderArcs();

            console.log(`Loaded ${this.links.length} existing links`);
        } catch (error) {
            console.error('Error loading links:', error);
        }
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
                    ? '<p class="link-mode-instruction">Click on the <strong>colored highlights in the text above</strong> to select spans for linking</p>'
                    : '<p class="no-selection-message">Select a link type, then click on highlighted spans in the text</p>';
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
        if (!this.arcsContainer) return;

        // Clear existing arcs
        this.arcsContainer.innerHTML = '';

        if (this.links.length === 0) return;

        // Get span positions
        const spanPositions = this.getSpanPositions();

        // Create SVG
        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.style.cssText = 'position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; overflow: visible;';

        // Add arrow marker definition
        const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
        defs.innerHTML = `
            <marker id="link-arrowhead" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
                <polygon points="0 0, 10 3.5, 0 7" fill="currentColor" />
            </marker>
        `;
        svg.appendChild(defs);

        // Draw arcs for each link
        this.links.forEach(link => {
            const config = this.linkTypeConfig[link.link_type] || {};
            const color = config.color || '#dc2626';
            const spanIds = link.span_ids;

            if (spanIds.length < 2) return;

            // Binary link - draw arc
            if (spanIds.length === 2) {
                const pos1 = spanPositions[spanIds[0]];
                const pos2 = spanPositions[spanIds[1]];

                if (!pos1 || !pos2) return;

                const x1 = pos1.x + pos1.width / 2;
                const y1 = pos1.y;
                const x2 = pos2.x + pos2.width / 2;
                const y2 = pos2.y;

                const midX = (x1 + x2) / 2;
                const arcHeight = Math.min(Math.abs(x2 - x1) / 3, 40);

                const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                path.setAttribute('d', `M ${x1} ${y1} Q ${midX} ${y1 - arcHeight} ${x2} ${y2}`);
                path.setAttribute('fill', 'none');
                path.setAttribute('stroke', color);
                path.setAttribute('stroke-width', '2');
                path.setAttribute('class', 'span-link-arc');
                path.dataset.linkId = link.id;

                if (config.directed) {
                    path.setAttribute('marker-end', 'url(#link-arrowhead)');
                    path.style.color = color;
                }

                svg.appendChild(path);
            } else {
                // N-ary link - connect to central point
                const validPositions = spanIds.map(id => spanPositions[id]).filter(Boolean);
                if (validPositions.length < 2) return;

                const centerX = validPositions.reduce((sum, p) => sum + p.x + p.width / 2, 0) / validPositions.length;
                const centerY = Math.min(...validPositions.map(p => p.y)) - 25;

                spanIds.forEach(spanId => {
                    const pos = spanPositions[spanId];
                    if (!pos) return;

                    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
                    line.setAttribute('x1', pos.x + pos.width / 2);
                    line.setAttribute('y1', pos.y);
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
        const instanceText = document.getElementById('instance-text');
        if (!instanceText) return positions;

        const containerRect = instanceText.getBoundingClientRect();

        document.querySelectorAll('.span-overlay-pure, .span-overlay, .span-overlay-ai, .span-highlight').forEach(overlay => {
            const spanId = overlay.dataset.spanId || overlay.dataset.annotationId;
            if (!spanId) return;

            const rect = overlay.getBoundingClientRect();
            positions[spanId] = {
                x: rect.left - containerRect.left,
                y: rect.top - containerRect.top,
                width: rect.width,
                height: rect.height
            };
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

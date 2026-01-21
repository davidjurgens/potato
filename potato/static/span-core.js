/**
 * Span Annotation Core - Positioning and Overlay Management
 *
 * This module provides unified text positioning for span annotations.
 */

// Debug logging utility - respects the debug setting from server config
function spanCoreDebugLog(...args) {
    if (window.config && window.config.debug) {
        console.log(...args);
    }
}

function spanCoreDebugWarn(...args) {
    if (window.config && window.config.debug) {
        console.warn(...args);
    }
}

/**
 * Get font metrics for positioning calculations
 */
function getFontMetrics(container) {
    const computedStyle = window.getComputedStyle(container);
    const fontSize = parseFloat(computedStyle.fontSize);
    const fontFamily = computedStyle.fontFamily;
    const lineHeight = parseFloat(computedStyle.lineHeight) || fontSize * 1.2;

    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    ctx.font = `${fontSize}px ${fontFamily}`;

    const testChars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ';
    const charWidths = {};

    for (let char of testChars) {
        charWidths[char] = ctx.measureText(char).width;
    }

    const totalWidth = Object.values(charWidths).reduce((sum, width) => sum + width, 0);
    const averageCharWidth = totalWidth / Object.keys(charWidths).length;

    return {
        fontSize,
        fontFamily,
        lineHeight,
        averageCharWidth,
        charWidths,
        containerPadding: {
            top: parseFloat(computedStyle.paddingTop) || 0,
            left: parseFloat(computedStyle.paddingLeft) || 0,
            right: parseFloat(computedStyle.paddingRight) || 0,
            bottom: parseFloat(computedStyle.paddingBottom) || 0
        }
    };
}

/**
 * Unified Positioning Strategy for Text Span Annotation
 */
class UnifiedPositioningStrategy {
    constructor(container) {
        this.container = container;
        this.fontMetrics = null;
        this.canonicalText = null;
        this.isInitialized = false;
    }

    async initialize() {
        await this.waitForElements();
        await this.waitForFontMetrics();
        this.canonicalText = this.getCanonicalText();
        this.fontMetrics = this.getFontMetrics();
        this.isInitialized = true;
    }

    async waitForElements() {
        return new Promise((resolve) => {
            const check = () => {
                if (this.container && this.container.textContent && this.container.textContent.trim()) {
                    resolve();
                } else {
                    setTimeout(check, 50);
                }
            };
            check();
        });
    }

    async waitForFontMetrics() {
        return new Promise((resolve) => {
            if (document.fonts && document.fonts.ready) {
                document.fonts.ready.then(() => {
                    setTimeout(resolve, 200);
                });
            } else {
                setTimeout(resolve, 800);
            }
        });
    }

    getCanonicalText() {
        if (this.container.hasAttribute('data-original-text')) {
            const originalText = this.container.getAttribute('data-original-text');
            const cleanText = originalText.replace(/<[^>]*>/g, '').trim();
            return this.normalizeText(cleanText);
        }
        const textContent = this.container.textContent || '';
        return this.normalizeText(textContent);
    }

    normalizeText(text) {
        return text.replace(/\s+/g, ' ').trim();
    }

    getFontMetrics() {
        return getFontMetrics(this.container);
    }

    createSpanFromSelection(selection, options = {}) {
        if (!this.isInitialized) {
            return null;
        }

        const selectedText = selection.toString().trim();
        if (!selectedText) {
            return null;
        }

        let canonicalText = this.getCanonicalText();

        const textElement = document.getElementById('text-content');
        if (textElement) {
            const storedText = textElement.getAttribute('data-original-text');
            if (storedText) {
                canonicalText = storedText;
            }
        }

        const start = canonicalText.indexOf(selectedText);
        if (start === -1) {
            console.warn('[SpanCore] Selected text not found in canonical text');
            return null;
        }

        const end = start + selectedText.length;
        return this.createSpanWithAlgorithm(start, end, selectedText, options);
    }

    createSpanWithAlgorithm(start, end, text, options = {}) {
        if (!this.isInitialized) {
            return null;
        }

        const canonicalText = this.getCanonicalText();
        if (start < 0 || end > canonicalText.length || start >= end) {
            console.warn('[SpanCore] Invalid span positions:', { start, end, textLength: canonicalText.length });
            return null;
        }

        const positions = this.getTextPositions(start, end, text);
        if (!positions || positions.length === 0) {
            return null;
        }

        // Validate positions
        const invalidPositions = positions.filter(p =>
            p.x < -1000 || p.y < -1000 || p.width <= 0 || p.height <= 0 ||
            p.x > 10000 || p.y > 10000 || p.width > 5000 || p.height > 500
        );
        if (invalidPositions.length > 0) {
            console.warn('[SpanCore] Some positions look invalid:', invalidPositions);
        }

        const span = {
            id: `span_${start}_${end}_${Date.now()}`,
            start: start,
            end: end,
            text: text,
            label: 'unknown',
            color: null
        };

        // Pass options (including color) to createOverlay
        const overlay = this.createOverlay(span, positions, options);
        if (!overlay) {
            return null;
        }

        return { span, overlay, positions };
    }

    getTextPositions(start, end, text) {
        const textElement = document.getElementById('text-content');
        if (!textElement) {
            return null;
        }

        let actualText = textElement.getAttribute('data-original-text');
        const domTextContent = textElement.textContent || textElement.innerText || '';

        if (!actualText) {
            actualText = domTextContent;
        }

        const targetStart = actualText.indexOf(text);
        if (targetStart === -1) {
            return null;
        }

        const targetEnd = targetStart + text.length;
        const range = document.createRange();

        // Collect all text nodes with their cumulative offsets
        const textNodes = [];
        let cumulativeOffset = 0;

        const collectTextNodes = (node) => {
            if (node.nodeType === Node.TEXT_NODE) {
                textNodes.push({
                    node: node,
                    text: node.textContent,
                    start: cumulativeOffset,
                    end: cumulativeOffset + node.textContent.length
                });
                cumulativeOffset += node.textContent.length;
            } else if (node.nodeType === Node.ELEMENT_NODE) {
                for (const child of node.childNodes) {
                    collectTextNodes(child);
                }
            }
        };

        collectTextNodes(textElement);

        if (textNodes.length === 0) {
            return null;
        }

        // Find the text nodes containing start and end positions
        let startNode = null, startOffset = 0;
        let endNode = null, endOffset = 0;

        for (const tn of textNodes) {
            if (startNode === null && targetStart >= tn.start && targetStart < tn.end) {
                startNode = tn.node;
                startOffset = targetStart - tn.start;
            }
            if (targetEnd > tn.start && targetEnd <= tn.end) {
                endNode = tn.node;
                endOffset = targetEnd - tn.start;
            }
        }

        try {
            range.setStart(startNode, startOffset);
            range.setEnd(endNode, endOffset);
        } catch (error) {
            console.error('[SpanCore] Error setting range:', error);
            return null;
        }

        const rects = range.getClientRects();
        if (rects.length === 0) {
            return null;
        }

        // Use #instance-text rect for correct positioning
        // Overlays are positioned relative to #instance-text, not #text-content
        const instanceText = document.getElementById('instance-text');
        const containerRect = instanceText ? instanceText.getBoundingClientRect() : textElement.getBoundingClientRect();

        const positions = Array.from(rects).map((rect) => ({
            x: rect.left - containerRect.left,
            y: rect.top - containerRect.top,
            width: rect.width,
            height: rect.height
        }));

        return positions;
    }

    createOverlay(span, positions, options = {}) {
        if (!positions || positions.length === 0) return null;

        const { isAiSpan = false, color = 'rgba(255, 255, 0, 0.3)' } = options;

        // Padding values for visual breathing room around text
        const HORIZONTAL_PADDING = 3;  // px on each side
        const VERTICAL_PADDING = 2;    // px on top and bottom

        const overlay = document.createElement('div');
        overlay.className = isAiSpan ? 'span-overlay-ai' : 'span-overlay-pure';
        overlay.dataset.annotationId = span.id;
        overlay.dataset.start = span.start;
        overlay.dataset.end = span.end;
        overlay.dataset.label = span.label;
        if (isAiSpan) {
            overlay.dataset.isAiSpan = 'true';
        }

        overlay.style.position = 'absolute';
        overlay.style.pointerEvents = 'none';
        overlay.style.zIndex = isAiSpan ? '999' : '1000';

        positions.forEach((pos) => {
            const segment = document.createElement('div');
            segment.className = 'span-highlight-segment';
            segment.style.position = 'absolute';
            // Add padding: position starts earlier, dimensions are larger
            segment.style.left = `${pos.x - HORIZONTAL_PADDING}px`;
            segment.style.top = `${pos.y - VERTICAL_PADDING}px`;
            segment.style.width = `${pos.width + 2 * HORIZONTAL_PADDING}px`;
            segment.style.height = `${pos.height + 2 * VERTICAL_PADDING}px`;

            if (isAiSpan) {
                // AI spans use a box/border style instead of background highlight
                segment.style.backgroundColor = 'transparent';
                segment.style.border = `2px solid ${color}`;
                segment.style.borderRadius = '3px';
                segment.style.boxShadow = `0 0 4px ${color}`;
            } else {
                segment.style.backgroundColor = color;
                segment.style.border = `1px solid ${color.replace('0.3', '0.8')}`;
                segment.style.borderRadius = '4px';
            }
            segment.style.pointerEvents = 'none';
            overlay.appendChild(segment);
        });

        if (!isAiSpan) {
            // Regular spans get labels and delete buttons
            // Position label and delete button together above the segment start
            const segmentLeft = positions[0].x - HORIZONTAL_PADDING;
            const segmentTop = positions[0].y - VERTICAL_PADDING;

            // Create a container for label + delete button so they stay together
            const controlsContainer = document.createElement('div');
            controlsContainer.className = 'span-controls';
            controlsContainer.style.position = 'absolute';
            controlsContainer.style.left = `${segmentLeft}px`;
            controlsContainer.style.top = `${Math.max(0, segmentTop - 20)}px`;
            controlsContainer.style.display = 'flex';
            controlsContainer.style.alignItems = 'center';
            controlsContainer.style.gap = '4px';
            controlsContainer.style.pointerEvents = 'auto';
            controlsContainer.style.zIndex = '10';

            const label = document.createElement('div');
            label.className = 'span-label';
            label.textContent = span.label;
            // Override CSS positioning to work in flex container
            label.style.position = 'static';
            label.style.top = 'auto';
            label.style.left = 'auto';
            label.style.backgroundColor = 'rgba(0, 0, 0, 0.85)';
            label.style.color = 'white';
            label.style.padding = '2px 6px';
            label.style.borderRadius = '3px';
            label.style.fontSize = '11px';
            label.style.fontWeight = '500';
            label.style.whiteSpace = 'nowrap';
            label.style.display = 'block';
            controlsContainer.appendChild(label);

            const deleteBtn = document.createElement('button');
            deleteBtn.className = 'span-delete-btn';
            deleteBtn.textContent = '×';
            deleteBtn.style.backgroundColor = 'rgba(220, 53, 69, 0.9)';
            deleteBtn.style.color = 'white';
            deleteBtn.style.border = 'none';
            deleteBtn.style.borderRadius = '50%';
            deleteBtn.style.width = '16px';
            deleteBtn.style.height = '16px';
            deleteBtn.style.minWidth = '16px';
            deleteBtn.style.minHeight = '16px';
            deleteBtn.style.padding = '0';
            deleteBtn.style.margin = '0';
            deleteBtn.style.fontSize = '12px';
            deleteBtn.style.fontFamily = 'Arial, sans-serif';
            deleteBtn.style.fontWeight = 'bold';
            deleteBtn.style.lineHeight = '1';
            deleteBtn.style.textAlign = 'center';
            deleteBtn.style.cursor = 'pointer';
            deleteBtn.style.display = 'flex';
            deleteBtn.style.alignItems = 'center';
            deleteBtn.style.justifyContent = 'center';
            deleteBtn.style.flexShrink = '0';
            // Reset any CSS positioning that might interfere
            deleteBtn.style.position = 'static';
            deleteBtn.style.top = 'auto';
            deleteBtn.style.right = 'auto';
            deleteBtn.style.left = 'auto';
            deleteBtn.onclick = (e) => {
                e.stopPropagation();
                // Immediately remove this overlay from DOM for instant visual feedback
                const overlayElement = e.target.closest('.span-overlay-pure');
                if (overlayElement) {
                    overlayElement.remove();
                }
                // Then process the server-side delete
                if (window.spanManager) {
                    window.spanManager.deleteSpan(span.id);
                }
            };
            controlsContainer.appendChild(deleteBtn);

            overlay.appendChild(controlsContainer);
        }

        return overlay;
    }

    validateSpan(span) {
        if (!this.isInitialized) return false;
        const { start, end, text } = span;
        if (start >= end || start < 0 || end > this.canonicalText.length) return false;
        const coveredText = this.canonicalText.substring(start, end);
        return coveredText === text;
    }
}

/**
 * Frontend Span Manager for Potato Annotation Platform
 */
class SpanManager {
    constructor() {
        this.annotations = { spans: [] };
        this.colors = {};
        this.selectedLabel = null;
        this.currentSchema = null;
        this.isInitialized = false;
        this.currentInstanceId = null;
        this.lastKnownInstanceId = null;
        this.positioningStrategy = null;
        this.schemas = {};

        // AI span state tracking
        this.aiSpans = new Map(); // Map<annotationId, Array<overlayElement>>

        // Admin keyword highlight state tracking
        this.keywordHighlights = []; // Array of keyword highlight overlay elements
    }

    // ==================== SCHEMA STATE MANAGEMENT ====================

    /**
     * Set the current schema with validation and logging.
     * This is the ONLY place currentSchema should be modified.
     *
     * @param {string} schema - The schema name to set
     * @param {string} source - Where this call originated (for debugging)
     * @returns {boolean} - Whether the schema was set successfully
     */
    setCurrentSchema(schema, source = 'unknown') {
        if (!schema) {
            console.warn(`[SpanManager] setCurrentSchema called with empty schema from ${source}`);
            return false;
        }

        // Validate schema exists if we have schemas loaded
        if (Object.keys(this.schemas).length > 0 && !this.schemas[schema]) {
            console.warn(`[SpanManager] Schema '${schema}' not found in loaded schemas. Source: ${source}. Available: ${Object.keys(this.schemas).join(', ')}`);
            // Still set it - might be valid but not yet loaded
        }

        const oldSchema = this.currentSchema;
        this.currentSchema = schema;

        if (oldSchema !== schema) {
            console.debug(`[SpanManager] Schema changed: '${oldSchema}' -> '${schema}' (source: ${source})`);
        }

        return true;
    }

    // ==================== AI SPAN METHODS ====================

    /**
     * Insert AI-suggested span highlights for keywords
     * @param {Array} keywords - Array of keyword objects with {label, start, end, text, reasoning}
     * @param {string} annotationId - The annotation ID these AI spans belong to
     */
    insertAiSpans(keywords, annotationId) {
        if (!keywords || !Array.isArray(keywords) || keywords.length === 0) {
            return;
        }

        this.deleteOneAiSpan(annotationId);

        const spanOverlays = document.getElementById('span-overlays');
        if (!spanOverlays) {
            return;
        }

        const createdOverlays = [];

        keywords.forEach((keyword) => {
            const { label, start, end, text, reasoning } = keyword;

            if (!this.positioningStrategy || !this.positioningStrategy.isInitialized) {
                return;
            }

            const positions = this.positioningStrategy.getTextPositions(start, end, text);
            if (!positions || positions.length === 0) {
                return;
            }

            const span = {
                id: `ai_span_${annotationId}_${start}_${end}_${Date.now()}`,
                start: start,
                end: end,
                text: text,
                label: label || 'keyword'
            };

            const aiColor = 'rgba(245, 158, 11, 0.8)';
            const overlay = this.positioningStrategy.createOverlay(span, positions, {
                isAiSpan: true,
                color: aiColor
            });

            if (overlay) {
                overlay.dataset.aiAnnotationId = annotationId;
                overlay.title = reasoning || `AI suggested: "${text}"`;
                spanOverlays.appendChild(overlay);
                createdOverlays.push(overlay);
            }
        });

        if (createdOverlays.length > 0) {
            this.aiSpans.set(annotationId, createdOverlays);
        }
    }

    /**
     * Clear all AI span highlights
     */
    clearAiSpans() {
        const spanOverlays = document.getElementById('span-overlays');
        if (spanOverlays) {
            const aiOverlays = spanOverlays.querySelectorAll('.span-overlay-ai');
            aiOverlays.forEach(overlay => overlay.remove());
        }
        this.aiSpans.clear();
    }

    /**
     * Check if AI spans exist for a specific annotation
     */
    inAiSpans(annotationId) {
        return this.aiSpans.has(annotationId) && this.aiSpans.get(annotationId).length > 0;
    }

    /**
     * Delete AI spans for a specific annotation
     */
    deleteOneAiSpan(annotationId) {
        const overlays = this.aiSpans.get(annotationId);
        if (overlays && overlays.length > 0) {
            overlays.forEach(overlay => {
                if (overlay && overlay.parentNode) {
                    overlay.remove();
                }
            });
        }
        this.aiSpans.delete(annotationId);
    }

    // ==================== CORE SPAN MANAGER METHODS ====================

    async fetchCurrentInstanceIdFromServer() {
        try {
            const response = await fetch('/api/current_instance');
            if (!response.ok) {
                throw new Error(`Failed to fetch current instance: ${response.status}`);
            }
            const data = await response.json();
            const serverInstanceId = data.instance_id;

            if (this.currentInstanceId !== serverInstanceId && this.currentInstanceId !== null) {
                this.clearAllStateAndOverlays();
            }

            this.currentInstanceId = serverInstanceId;
            this.lastKnownInstanceId = serverInstanceId;

            return serverInstanceId;
        } catch (error) {
            console.error('[SpanManager] Error fetching current instance ID:', error);
            return null;
        }
    }

    async initialize() {
        try {
            const serverInstanceId = await this.fetchCurrentInstanceIdFromServer();
            if (!serverInstanceId) {
                console.error('[SpanManager] Failed to get server instance ID during initialization');
                return false;
            }

            const textContent = document.getElementById('text-content');
            if (textContent) {
                this.positioningStrategy = new UnifiedPositioningStrategy(textContent);
                await this.positioningStrategy.initialize();
            }

            await this.loadSchemas();
            await this.loadColors();
            this.setupEventListeners();
            await this.loadAnnotations(serverInstanceId);

            this.isInitialized = true;
            return true;
        } catch (error) {
            console.error('[SpanManager] Initialization failed:', error);
            this.isInitialized = false;
            return false;
        }
    }

    async loadColors() {
        try {
            const response = await fetch('/api/colors');
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            this.colors = await response.json();
        } catch (error) {
            console.warn('[SpanManager] Error loading colors, using defaults:', error.message);
            // Fallback colors - visible purple for better visibility
            const defaultColors = {
                'positive': 'rgba(110, 86, 207, 0.4)',  // Purple
                'negative': 'rgba(239, 68, 68, 0.4)',   // Red
                'neutral': 'rgba(113, 113, 122, 0.4)',  // Gray
                'span': 'rgba(110, 86, 207, 0.4)'       // Purple
            };
            // Structure as { schemaName: { labelName: color } } to match server format
            this.colors = {
                'sentiment': defaultColors,
                'emotion': defaultColors,
                'entity': defaultColors,
                'topic': defaultColors,
                'span': defaultColors
            };
        }
    }

    async loadSchemas() {
        try {
            const response = await fetch('/api/schemas');
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            this.schemas = await response.json();

            if (!this.currentSchema && Object.keys(this.schemas).length > 0) {
                this.setCurrentSchema(Object.keys(this.schemas)[0], 'loadSchemas');
            }

            return this.schemas;
        } catch (error) {
            console.warn('[SpanManager] Error loading schemas:', error.message);
            return this.extractSchemaFromForms();
        }
    }

    extractSchemaFromForms() {
        const spanForms = document.querySelectorAll('.annotation-form.span');
        if (spanForms.length > 0) {
            const firstSpanForm = spanForms[0];
            const fieldset = firstSpanForm.querySelector('fieldset');
            if (fieldset && fieldset.getAttribute('schema')) {
                return fieldset.getAttribute('schema');
            }
        }
        return null;
    }

    setupEventListeners() {
        const textContainer = document.getElementById('instance-text');
        const textContent = document.getElementById('text-content');

        if (textContainer) {
            textContainer.addEventListener('mouseup', () => this.handleTextSelection());
            textContainer.addEventListener('keyup', () => this.handleTextSelection());
        }
        if (textContent) {
            textContent.addEventListener('mouseup', () => this.handleTextSelection());
            textContent.addEventListener('keyup', () => this.handleTextSelection());
        }

        document.addEventListener('click', (e) => {
            if (e.target.classList.contains('span-delete')) {
                e.stopPropagation();
                const annotationId = e.target.closest('.span-highlight').dataset.annotationId;
                this.deleteSpan(annotationId);
            }
        });
    }

    selectLabel(label, schema = null) {
        this.selectedLabel = label;
        if (schema) {
            this.setCurrentSchema(schema, 'selectLabel');
        }
    }

    getSelectedLabel() {
        // FIRST: Use the label set by selectLabel() if available
        // This is set by changeSpanLabel() when a checkbox is clicked,
        // and is more reliable than querying the DOM
        if (this.selectedLabel && this.currentSchema) {
            return this.selectedLabel;
        }

        // FALLBACK: Try to find checked span checkbox (for legacy code paths)
        const checkedCheckbox = document.querySelector('.annotation-form.span input[type="checkbox"]:checked');

        if (checkedCheckbox) {
            const checkboxId = checkedCheckbox.id;
            const parts = checkboxId.split('_');
            if (parts.length >= 2) {
                // ID format is "schemaName_labelName" - extract both
                const label = parts[parts.length - 1];
                // Schema name is everything before the last underscore
                // (handles multi-word schema names like "emotion_spans")
                const schemaName = parts.slice(0, -1).join('_');

                // Update currentSchema to match the selected checkbox's schema
                if (schemaName) {
                    this.setCurrentSchema(schemaName, 'getSelectedLabel');
                }

                return label;
            }
            return checkedCheckbox.value;
        }

        return this.selectedLabel;
    }

    async loadAnnotations(instanceId) {
        try {
            const serverInstanceId = await this.fetchCurrentInstanceIdFromServer();
            if (serverInstanceId !== instanceId) {
                instanceId = serverInstanceId;
            }

            const textContent = document.getElementById('text-content');
            const existingSpans = textContent ? textContent.querySelectorAll('.span-highlight') : [];
            const hasServerRenderedSpans = existingSpans.length > 0;

            const response = await fetch(`/api/spans/${instanceId}`);

            if (!response.ok) {
                if (response.status === 404) {
                    this.annotations = { spans: [] };
                    if (!hasServerRenderedSpans) {
                        this.clearAllStateAndOverlays();
                        this.renderSpans();
                    }
                    return Promise.resolve();
                }
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const responseData = await response.json();
            this.annotations = responseData;

            if (this.annotations && this.annotations.text && textContent) {
                const plainText = this.annotations.text.replace(/<[^>]*>/g, '').trim();
                textContent.setAttribute('data-original-text', plainText);
            }

            if (this.annotations.spans && this.annotations.spans.length > 0) {
                const firstSpan = this.annotations.spans[0];
                if (firstSpan.schema && !this.currentSchema) {
                    this.setCurrentSchema(firstSpan.schema, 'loadAnnotations');
                }
            }

            this.renderSpans();

            // Load admin keyword highlights after span annotations
            await this.loadKeywordHighlights(instanceId);

        } catch (error) {
            console.error('[SpanManager] Error loading annotations:', error);
            throw error;
        }
    }

    getSpans() {
        return this.annotations?.spans || [];
    }

    getSpanColor(label) {
        // Diagnostic logging for color lookup failures
        if (!this.currentSchema) {
            console.warn(`[SpanManager] getSpanColor: No currentSchema set for label '${label}'. Using fallback color.`);
            return 'rgba(110, 86, 207, 0.4)';
        }

        if (!this.colors || Object.keys(this.colors).length === 0) {
            console.warn(`[SpanManager] getSpanColor: Colors not loaded for label '${label}'. Using fallback color.`);
            return 'rgba(110, 86, 207, 0.4)';
        }

        if (!this.colors[this.currentSchema]) {
            console.warn(`[SpanManager] getSpanColor: Schema '${this.currentSchema}' not found in colors. Available schemas: ${Object.keys(this.colors).join(', ')}. Using fallback color.`);
            return 'rgba(110, 86, 207, 0.4)';
        }

        const schemaColors = this.colors[this.currentSchema];
        if (!schemaColors[label]) {
            console.warn(`[SpanManager] getSpanColor: Label '${label}' not found in schema '${this.currentSchema}'. Available labels: ${Object.keys(schemaColors).join(', ')}. Using fallback color.`);
            return 'rgba(110, 86, 207, 0.4)';
        }

        const color = schemaColors[label];
        if (color.startsWith('(')) {
            return `rgba${color.replace(')', ', 0.4)')}`;
        }
        return color;
    }

    clearAllStateAndOverlays() {
        const spanOverlays = document.getElementById('span-overlays');
        if (spanOverlays) {
            // Clear regular overlays but preserve AI spans
            const regularOverlays = spanOverlays.querySelectorAll('.span-overlay-pure:not(.span-overlay-ai)');
            regularOverlays.forEach(overlay => overlay.remove());
        }

        this.annotations = { spans: [] };
        // Don't clear currentSchema - keep it for consistency
    }

    renderSpans() {
        const textContent = document.getElementById('text-content');
        const spanOverlays = document.getElementById('span-overlays');

        if (!textContent || !spanOverlays) {
            return;
        }

        // Clear existing regular overlays (preserve AI spans)
        const regularOverlays = spanOverlays.querySelectorAll('.span-overlay-pure:not(.span-overlay-ai)');
        regularOverlays.forEach(overlay => overlay.remove());

        const spans = this.getSpans();
        if (!spans || spans.length === 0) {
            return;
        }

        const sortedSpans = [...spans].sort((a, b) => a.start - b.start);
        sortedSpans.forEach((span, index) => {
            this.renderSpanOverlay(span, index, textContent, spanOverlays);
        });
    }

    renderSpanOverlay(span, layerIndex, textContent, spanOverlays) {
        if (!this.positioningStrategy || !this.positioningStrategy.isInitialized) {
            return;
        }

        const positions = this.positioningStrategy.getTextPositions(span.start, span.end, span.text);
        if (!positions || positions.length === 0) {
            return;
        }

        const color = this.getSpanColor(span.label);
        const overlay = this.positioningStrategy.createOverlay(span, positions, {
            isAiSpan: false,
            color: color
        });

        if (overlay) {
            spanOverlays.appendChild(overlay);
        }
    }

    handleTextSelection() {
        const selection = window.getSelection();

        if (!selection.rangeCount || selection.isCollapsed) {
            return;
        }

        const selectedLabel = this.getSelectedLabel();
        if (!selectedLabel) {
            return;
        }

        if (!this.positioningStrategy || !this.positioningStrategy.isInitialized) {
            return;
        }

        // Get color BEFORE creating the overlay so it's created with the correct color
        const color = this.getSpanColor(selectedLabel);

        // Pass color to createSpanFromSelection so overlay is created with correct color
        const result = this.positioningStrategy.createSpanFromSelection(selection, {
            color: color
        });
        if (!result) {
            return;
        }

        const { span, overlay } = result;
        span.label = selectedLabel;
        span.schema = this.currentSchema;

        if (overlay) {
            // Update the label text to match the selected label
            const label = overlay.querySelector('.span-label');
            if (label) {
                label.textContent = selectedLabel;
            }

            // Append the overlay to the DOM so it's visible immediately
            const spanOverlays = document.getElementById('span-overlays');
            if (spanOverlays) {
                spanOverlays.appendChild(overlay);
            }
        }

        // Add span to local state
        if (!this.annotations.spans) {
            this.annotations.spans = [];
        }
        this.annotations.spans.push(span);

        this.saveSpan(span);
        selection.removeAllRanges();
    }

    async saveSpan(span) {
        try {
            const postData = {
                type: "span",
                schema: span.schema || this.currentSchema,
                state: [{
                    name: span.label,
                    start: span.start,
                    end: span.end,
                    title: span.label,
                    value: 1
                }],
                instance_id: this.currentInstanceId
            };

            const response = await fetch('/updateinstance', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(postData)
            });

            if (response.ok) {
                await this.loadAnnotations(this.currentInstanceId);
            } else {
                console.error('[SpanManager] Failed to save span:', await response.text());
            }
        } catch (error) {
            console.error('[SpanManager] Error saving span:', error);
        }
    }

    async deleteSpan(spanId) {
        const span = this.annotations.spans?.find(s => s.id === spanId);

        // Immediately remove the overlay from DOM for instant visual feedback
        // This ensures overlay is removed even if server reload has issues
        const spanOverlays = document.getElementById('span-overlays');
        if (spanOverlays) {
            const overlayToRemove = spanOverlays.querySelector(
                `.span-overlay-pure[data-annotation-id="${spanId}"]`
            );
            if (overlayToRemove) {
                overlayToRemove.remove();
            }
        }

        // Also remove from local state immediately
        if (this.annotations.spans) {
            this.annotations.spans = this.annotations.spans.filter(s => s.id !== spanId);
        }

        if (!span) {
            // Even if span not found in state, we already removed the overlay visually
            return;
        }

        try {
            const postData = {
                type: "span",
                schema: span.schema || this.currentSchema,
                state: [{
                    name: span.label,
                    start: span.start,
                    end: span.end,
                    title: span.label,
                    value: null
                }],
                instance_id: this.currentInstanceId
            };

            const response = await fetch('/updateinstance', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(postData)
            });

            if (response.ok) {
                // Reload to sync with server state
                await this.loadAnnotations(this.currentInstanceId);
            } else {
                console.error('[SpanManager] Failed to delete span:', await response.text());
                // Reload anyway to get correct state from server
                await this.loadAnnotations(this.currentInstanceId);
            }
        } catch (error) {
            console.error('[SpanManager] Error deleting span:', error);
            // Reload to ensure UI matches server state
            await this.loadAnnotations(this.currentInstanceId);
        }
    }

    onInstanceChange(newInstanceId) {
        // Clear AI spans and keyword highlights on instance change
        this.clearAiSpans();
        this.clearKeywordHighlights();

        if (newInstanceId && newInstanceId !== this.currentInstanceId) {
            this.clearAllStateAndOverlays();
            this.currentInstanceId = newInstanceId;
            this.loadAnnotations(newInstanceId);
        }
    }

    calculateOverlapDepths(spans) {
        if (!spans || spans.length === 0) return [];

        const result = spans.map(span => ({
            span,
            depth: 0,
            heightMultiplier: 1.0
        }));

        for (let i = 0; i < spans.length; i++) {
            let maxOverlap = 0;
            for (let j = 0; j < i; j++) {
                if (spans[j].end > spans[i].start && spans[j].start < spans[i].end) {
                    maxOverlap = Math.max(maxOverlap, result[j].depth + 1);
                }
            }
            result[i].depth = maxOverlap;
            result[i].heightMultiplier = 1.0 / (maxOverlap + 1);
        }

        return result;
    }

    applyOverlapStyling(spanElements, overlapData) {
        spanElements.forEach((element, index) => {
            if (overlapData[index]) {
                const { depth, heightMultiplier } = overlapData[index];
                element.style.setProperty('--overlap-depth', depth);
                element.style.setProperty('--height-multiplier', heightMultiplier);
            }
        });
    }

    // ==================== KEYWORD HIGHLIGHT METHODS ====================

    /**
     * Load admin-defined keyword highlights for the current instance.
     * These are displayed using the same visual system as AI keyword suggestions
     * (bounding boxes around keywords).
     */
    async loadKeywordHighlights(instanceId) {
        try {
            const response = await fetch(`/api/keyword_highlights/${instanceId}`);

            if (!response.ok) {
                if (response.status === 404) {
                    return;
                }
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();
            const keywords = data.keywords || [];

            if (keywords.length === 0) {
                return;
            }

            this.insertKeywordHighlights(keywords);

        } catch (error) {
            console.error('[SpanManager] Error loading keyword highlights:', error);
        }
    }

    /**
     * Insert admin keyword highlights using the same visual system as AI spans.
     * @param {Array} keywords - Array of keyword objects with {label, start, end, text, reasoning, schema, color}
     */
    insertKeywordHighlights(keywords) {
        if (!keywords || !Array.isArray(keywords) || keywords.length === 0) {
            return;
        }

        // Clear any existing admin keyword highlights
        this.clearKeywordHighlights();

        const spanOverlays = document.getElementById('span-overlays');
        if (!spanOverlays) {
            return;
        }

        const createdOverlays = [];

        keywords.forEach((keyword) => {
            const { label, start, end, text, reasoning, schema, color } = keyword;

            if (!this.positioningStrategy || !this.positioningStrategy.isInitialized) {
                return;
            }

            const positions = this.positioningStrategy.getTextPositions(start, end, text);
            if (!positions || positions.length === 0) {
                return;
            }

            const span = {
                id: `keyword_${start}_${end}_${Date.now()}`,
                start: start,
                end: end,
                text: text,
                label: label || 'keyword'
            };

            const keywordColor = color || 'rgba(245, 158, 11, 0.8)';
            const overlay = this.positioningStrategy.createOverlay(span, positions, {
                isAiSpan: true,
                color: keywordColor
            });

            if (overlay) {
                overlay.dataset.keywordHighlight = 'true';
                overlay.dataset.schema = schema || '';
                overlay.dataset.label = label || '';
                overlay.title = reasoning || `Keyword: "${text}" → ${label}`;
                overlay.classList.add('keyword-highlight-overlay');
                spanOverlays.appendChild(overlay);
                createdOverlays.push(overlay);
            }
        });

        this.keywordHighlights = createdOverlays;
    }

    /**
     * Clear all admin keyword highlight overlays.
     */
    clearKeywordHighlights() {
        const spanOverlays = document.getElementById('span-overlays');
        if (spanOverlays) {
            const keywordOverlays = spanOverlays.querySelectorAll('.keyword-highlight-overlay');
            keywordOverlays.forEach(overlay => overlay.remove());
        }

        this.keywordHighlights = [];
    }
}

// Initialize global span manager
window.spanManager = new SpanManager();

/**
 * Initialize the span manager.
 * Called once when DOM is ready, with a single retry fallback.
 */
function initializeSpanManager() {
    if (window.spanManager && !window.spanManager.isInitialized) {
        window.spanManager.initialize().catch((error) => {
            console.error('[SpanManager] Initialization failed:', error);
        });
    }
}

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeSpanManager);
} else {
    // DOM already loaded, initialize immediately
    initializeSpanManager();
}

// Single retry fallback after 1 second
// Handles edge cases where text-content isn't populated yet on initial load
// (e.g., content loaded via AJAX after DOMContentLoaded)
setTimeout(() => {
    if (window.spanManager && !window.spanManager.isInitialized) {
        console.debug('[SpanManager] Retry initialization after 1s timeout');
        initializeSpanManager();
    }
}, 1000);

// Export for testing
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { SpanManager, UnifiedPositioningStrategy, getFontMetrics };
}

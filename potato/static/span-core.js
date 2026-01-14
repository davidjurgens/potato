console.log('[DEBUG] span-core.js file loaded!');

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
        console.log('[UNIFIED] Initializing positioning strategy');
        await this.waitForElements();
        await this.waitForFontMetrics();
        this.canonicalText = this.getCanonicalText();
        this.fontMetrics = this.getFontMetrics();
        this.isInitialized = true;
        console.log('[UNIFIED] Positioning strategy initialized');
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

    createSpanFromSelection(selection) {
        if (!this.isInitialized) return null;

        const selectedText = selection.toString().trim();
        if (!selectedText) return null;

        let canonicalText = this.getCanonicalText();
        const textElement = document.getElementById('text-content');
        if (textElement) {
            const storedText = textElement.getAttribute('data-original-text');
            if (storedText) {
                canonicalText = storedText;
            }
        }

        const start = canonicalText.indexOf(selectedText);
        if (start === -1) return null;

        const end = start + selectedText.length;
        return this.createSpanWithAlgorithm(start, end, selectedText);
    }

    createSpanWithAlgorithm(start, end, text) {
        if (!this.isInitialized) return null;

        const canonicalText = this.getCanonicalText();
        if (start < 0 || end > canonicalText.length || start >= end) return null;

        const positions = this.getTextPositions(start, end, text);
        if (!positions || positions.length === 0) return null;

        const span = {
            id: `span_${start}_${end}_${Date.now()}`,
            start: start,
            end: end,
            text: text,
            label: 'unknown',
            color: null
        };

        const overlay = this.createOverlay(span, positions);
        if (!overlay) return null;

        return { span, overlay, positions };
    }

    getTextPositions(start, end, text) {
        const textElement = document.getElementById('text-content');
        if (!textElement) return null;

        let actualText = textElement.getAttribute('data-original-text');
        if (!actualText) {
            actualText = textElement.textContent || textElement.innerText || '';
        }

        const targetStart = actualText.indexOf(text);
        if (targetStart === -1) return null;

        const targetEnd = targetStart + text.length;

        const range = document.createRange();
        let textNode = textElement.firstChild;
        if (!textNode || textNode.nodeType !== Node.TEXT_NODE) {
            textNode = Array.from(textElement.childNodes).find(
                node => node.nodeType === Node.TEXT_NODE
            );
            if (!textNode) return null;
        }

        try {
            range.setStart(textNode, targetStart);
            range.setEnd(textNode, targetEnd);
        } catch (error) {
            console.error('[UNIFIED] Error setting range:', error);
            return null;
        }

        const rects = range.getClientRects();
        if (rects.length === 0) return null;

        const containerRect = textElement.getBoundingClientRect();

        const positions = Array.from(rects).map(rect => ({
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
            segment.style.left = `${pos.x}px`;
            segment.style.top = `${pos.y}px`;
            segment.style.width = `${pos.width}px`;
            segment.style.height = `${pos.height}px`;

            if (isAiSpan) {
                // AI spans use a box/border style instead of background highlight
                segment.style.backgroundColor = 'transparent';
                segment.style.border = `2px solid ${color}`;
                segment.style.borderRadius = '3px';
                segment.style.boxShadow = `0 0 4px ${color}`;
            } else {
                segment.style.backgroundColor = color;
                segment.style.border = `1px solid ${color.replace('0.3', '0.8')}`;
                segment.style.borderRadius = '2px';
            }
            segment.style.pointerEvents = 'none';
            overlay.appendChild(segment);
        });

        if (!isAiSpan) {
            // Regular spans get labels and delete buttons
            const label = document.createElement('div');
            label.className = 'span-label';
            label.textContent = span.label;
            label.style.position = 'absolute';
            label.style.left = `${positions[0].x}px`;
            label.style.top = `${positions[0].y - 20}px`;
            label.style.backgroundColor = 'rgba(0, 0, 0, 0.8)';
            label.style.color = 'white';
            label.style.padding = '2px 6px';
            label.style.borderRadius = '3px';
            label.style.fontSize = '12px';
            label.style.pointerEvents = 'none';
            overlay.appendChild(label);

            const deleteBtn = document.createElement('button');
            deleteBtn.className = 'span-delete-btn';
            deleteBtn.textContent = '×';
            deleteBtn.style.position = 'absolute';
            deleteBtn.style.left = `${positions[0].x + positions[0].width}px`;
            deleteBtn.style.top = `${positions[0].y - 20}px`;
            deleteBtn.style.backgroundColor = 'rgba(255, 0, 0, 0.8)';
            deleteBtn.style.color = 'white';
            deleteBtn.style.border = 'none';
            deleteBtn.style.borderRadius = '50%';
            deleteBtn.style.width = '20px';
            deleteBtn.style.height = '20px';
            deleteBtn.style.fontSize = '14px';
            deleteBtn.style.cursor = 'pointer';
            deleteBtn.style.pointerEvents = 'auto';
            deleteBtn.onclick = () => {
                if (window.spanManager) {
                    window.spanManager.deleteSpan(span.id);
                }
            };
            overlay.appendChild(deleteBtn);
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
        console.log('[SpanManager] Constructor called');
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
    }

    // ==================== AI SPAN METHODS ====================

    /**
     * Insert AI-suggested span highlights for keywords
     * @param {Array} keywords - Array of keyword objects with {label, start, end, text, reasoning}
     * @param {string} annotationId - The annotation ID these AI spans belong to
     */
    insertAiSpans(keywords, annotationId) {
        console.log('[SpanManager] insertAiSpans called:', { keywords, annotationId });

        if (!keywords || !Array.isArray(keywords) || keywords.length === 0) {
            console.warn('[SpanManager] No keywords provided for AI spans');
            return;
        }

        // Clear existing AI spans for this annotation first
        this.deleteOneAiSpan(annotationId);

        const spanOverlays = document.getElementById('span-overlays');
        if (!spanOverlays) {
            console.error('[SpanManager] span-overlays element not found');
            return;
        }

        const createdOverlays = [];

        keywords.forEach((keyword, index) => {
            const { label, start, end, text, reasoning } = keyword;

            console.log(`[SpanManager] Creating AI span for keyword ${index}:`, { label, start, end, text });

            // Get positions for this keyword
            if (!this.positioningStrategy || !this.positioningStrategy.isInitialized) {
                console.warn('[SpanManager] Positioning strategy not initialized');
                return;
            }

            const positions = this.positioningStrategy.getTextPositions(start, end, text);
            if (!positions || positions.length === 0) {
                console.warn('[SpanManager] Could not get positions for AI span:', text);
                return;
            }

            // Create AI span with box styling
            const span = {
                id: `ai_span_${annotationId}_${start}_${end}_${Date.now()}`,
                start: start,
                end: end,
                text: text,
                label: label || 'keyword'
            };

            // Use a distinctive color for AI highlights (gold/amber box)
            const aiColor = 'rgba(245, 158, 11, 0.8)'; // Amber color
            const overlay = this.positioningStrategy.createOverlay(span, positions, {
                isAiSpan: true,
                color: aiColor
            });

            if (overlay) {
                overlay.dataset.aiAnnotationId = annotationId;
                overlay.title = reasoning || `AI suggested: "${text}"`;
                spanOverlays.appendChild(overlay);
                createdOverlays.push(overlay);
                console.log('[SpanManager] AI span overlay created successfully');
            }
        });

        // Store the created overlays
        if (createdOverlays.length > 0) {
            this.aiSpans.set(annotationId, createdOverlays);
            console.log(`[SpanManager] Stored ${createdOverlays.length} AI spans for annotation ${annotationId}`);
        }
    }

    /**
     * Clear all AI span highlights
     */
    clearAiSpans() {
        console.log('[SpanManager] clearAiSpans called');

        const spanOverlays = document.getElementById('span-overlays');
        if (spanOverlays) {
            // Remove all AI span overlays from DOM
            const aiOverlays = spanOverlays.querySelectorAll('.span-overlay-ai');
            aiOverlays.forEach(overlay => {
                overlay.remove();
            });
            console.log(`[SpanManager] Removed ${aiOverlays.length} AI span overlays from DOM`);
        }

        // Clear the tracking map
        this.aiSpans.clear();
        console.log('[SpanManager] AI spans map cleared');
    }

    /**
     * Check if AI spans exist for a specific annotation
     * @param {string} annotationId - The annotation ID to check
     * @returns {boolean} True if AI spans exist for this annotation
     */
    inAiSpans(annotationId) {
        const exists = this.aiSpans.has(annotationId) && this.aiSpans.get(annotationId).length > 0;
        console.log(`[SpanManager] inAiSpans(${annotationId}):`, exists);
        return exists;
    }

    /**
     * Delete AI spans for a specific annotation
     * @param {string} annotationId - The annotation ID to delete AI spans for
     */
    deleteOneAiSpan(annotationId) {
        console.log(`[SpanManager] deleteOneAiSpan called for annotation: ${annotationId}`);

        const overlays = this.aiSpans.get(annotationId);
        if (overlays && overlays.length > 0) {
            overlays.forEach(overlay => {
                if (overlay && overlay.parentNode) {
                    overlay.remove();
                }
            });
            console.log(`[SpanManager] Removed ${overlays.length} AI span overlays for annotation ${annotationId}`);
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
        console.log('[SpanManager] initialize called');

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
                console.log('[SpanManager] Positioning strategy initialized');
            }

            await this.loadSchemas();
            await this.loadColors();
            this.setupEventListeners();
            await this.loadAnnotations(serverInstanceId);

            this.isInitialized = true;
            console.log('[SpanManager] Initialization completed successfully');
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
            console.log('[SpanManager] Colors loaded:', this.colors);
        } catch (error) {
            console.error('[SpanManager] Error loading colors:', error);
            this.colors = {
                'positive': '#d4edda',
                'negative': '#f8d7da',
                'neutral': '#d1ecf1',
                'span': '#ffeaa7'
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
            console.log('[SpanManager] Schemas loaded from server:', this.schemas);

            if (!this.currentSchema && Object.keys(this.schemas).length > 0) {
                this.currentSchema = Object.keys(this.schemas)[0];
            }

            return this.schemas;
        } catch (error) {
            console.error('[SpanManager] Error loading schemas:', error);
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
        console.log('[SpanManager] selectLabel called:', { label, schema });
        this.selectedLabel = label;
        if (schema) {
            this.currentSchema = schema;
        }
    }

    getSelectedLabel() {
        const checkedCheckbox = document.querySelector('.annotation-form.span input[type="checkbox"]:checked');
        if (checkedCheckbox) {
            const checkboxId = checkedCheckbox.id;
            const parts = checkboxId.split('_');
            if (parts.length >= 2) {
                return parts[parts.length - 1];
            }
            return checkedCheckbox.value;
        }
        return this.selectedLabel;
    }

    async loadAnnotations(instanceId) {
        console.log('[SpanManager] loadAnnotations called with instanceId:', instanceId);

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
                    this.currentSchema = firstSpan.schema;
                }
            }

            this.renderSpans();

        } catch (error) {
            console.error('[SpanManager] Error loading annotations:', error);
            throw error;
        }
    }

    getSpans() {
        return this.annotations?.spans || [];
    }

    getSpanColor(label) {
        if (this.colors && this.currentSchema && this.colors[this.currentSchema]) {
            const schemaColors = this.colors[this.currentSchema];
            if (schemaColors[label]) {
                const color = schemaColors[label];
                if (color.startsWith('(')) {
                    return `rgba${color.replace(')', ', 0.4)')}`;
                }
                return color;
            }
        }
        return 'rgba(255, 234, 167, 0.5)';
    }

    clearAllStateAndOverlays() {
        console.log('[SpanManager] clearAllStateAndOverlays called');

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
        console.log('[SpanManager] renderSpans called');

        const textContent = document.getElementById('text-content');
        const spanOverlays = document.getElementById('span-overlays');

        if (!textContent || !spanOverlays) {
            console.error('[SpanManager] Required DOM elements not found');
            return;
        }

        // Clear existing regular overlays (preserve AI spans)
        const regularOverlays = spanOverlays.querySelectorAll('.span-overlay-pure:not(.span-overlay-ai)');
        regularOverlays.forEach(overlay => overlay.remove());

        const spans = this.getSpans();
        if (!spans || spans.length === 0) {
            console.log('[SpanManager] No spans to render');
            return;
        }

        const sortedSpans = [...spans].sort((a, b) => a.start - b.start);

        sortedSpans.forEach((span, index) => {
            this.renderSpanOverlay(span, index, textContent, spanOverlays);
        });
    }

    renderSpanOverlay(span, layerIndex, textContent, spanOverlays) {
        if (!this.positioningStrategy || !this.positioningStrategy.isInitialized) {
            console.error('[SpanManager] Positioning strategy not available');
            return;
        }

        const positions = this.positioningStrategy.getTextPositions(span.start, span.end, span.text);
        if (!positions || positions.length === 0) {
            console.warn('[SpanManager] Could not get positions for span:', span);
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
        if (!selection.rangeCount || selection.isCollapsed) return;

        const selectedLabel = this.getSelectedLabel();
        if (!selectedLabel) {
            console.log('[SpanManager] No label selected, ignoring text selection');
            return;
        }

        if (!this.positioningStrategy || !this.positioningStrategy.isInitialized) {
            console.error('[SpanManager] Positioning strategy not initialized');
            return;
        }

        const result = this.positioningStrategy.createSpanFromSelection(selection);
        if (!result) return;

        const { span, overlay } = result;
        span.label = selectedLabel;
        span.schema = this.currentSchema;

        const color = this.getSpanColor(selectedLabel);
        if (overlay) {
            const label = overlay.querySelector('.span-label');
            if (label) {
                label.textContent = selectedLabel;
            }
            overlay.style.setProperty('--span-color', color);
        }

        this.saveSpan(span);
        selection.removeAllRanges();
    }

    async saveSpan(span) {
        console.log('[SpanManager] saveSpan called:', span);

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
                console.log('[SpanManager] Span saved successfully');
                await this.loadAnnotations(this.currentInstanceId);
            } else {
                console.error('[SpanManager] Failed to save span:', await response.text());
            }
        } catch (error) {
            console.error('[SpanManager] Error saving span:', error);
        }
    }

    async deleteSpan(spanId) {
        console.log('[SpanManager] deleteSpan called:', spanId);

        const span = this.annotations.spans?.find(s => s.id === spanId);
        if (!span) {
            console.warn('[SpanManager] Span not found:', spanId);
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
                console.log('[SpanManager] Span deleted successfully');
                await this.loadAnnotations(this.currentInstanceId);
            } else {
                console.error('[SpanManager] Failed to delete span:', await response.text());
            }
        } catch (error) {
            console.error('[SpanManager] Error deleting span:', error);
        }
    }

    onInstanceChange(newInstanceId) {
        console.log('[SpanManager] onInstanceChange called:', newInstanceId);

        // Clear AI spans on instance change
        this.clearAiSpans();

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
}

// Initialize global span manager
window.spanManager = new SpanManager();
console.log('[DEBUG] spanManager created');

// Robust initialization function
function initializeSpanManager() {
    console.log('[DEBUG] initializeSpanManager called');
    if (window.spanManager && !window.spanManager.isInitialized) {
        window.spanManager.initialize().then(() => {
            console.log('[DEBUG] Span manager initialization completed successfully');
        }).catch((error) => {
            console.error('[DEBUG] Span manager initialization failed:', error);
        });
    }
}

// Initialize on DOM ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeSpanManager);
} else {
    initializeSpanManager();
}

// Additional initialization on window load
window.addEventListener('load', initializeSpanManager);

// Fallback initialization with retry mechanism
setTimeout(() => {
    if (window.spanManager && !window.spanManager.isInitialized) {
        initializeSpanManager();
    }
}, 1000);

// Export for testing
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { SpanManager, UnifiedPositioningStrategy, getFontMetrics };
}

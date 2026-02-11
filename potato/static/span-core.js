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
 * Centralized Z-Index Management
 * All overlay z-index values defined in one place for consistency.
 * Higher values appear on top of lower values.
 */
const OVERLAY_Z_INDEX = {
    // Base layers (defined in HTML template)
    TEXT_CONTENT: 1,           // #text-content
    OVERLAY_CONTAINER: 2,      // #span-overlays container

    // Overlay types (higher = on top)
    ADMIN_KEYWORD: 100,        // Admin-defined keyword highlights (dashed border)
    AI_KEYWORD: 110,           // AI-suggested keyword highlights (solid border)
    USER_SPAN: 120,            // User-created span annotations (filled)

    // Interactive elements (must be above overlays)
    SPAN_CONTROLS: 200,        // Label + delete button
    TOOLTIP: 300               // Hover tooltips
};

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
        // For code displays (pre/code elements), preserve newlines for accurate positioning
        // Check if we're inside a code display
        if (this.container && (
            this.container.closest('.code-display') ||
            this.container.closest('.code-simple') ||
            this.container.querySelector('pre')
        )) {
            // Only normalize multiple spaces to single space, keep newlines
            return text.replace(/[ \t]+/g, ' ').trim();
        }
        // For regular text, normalize all whitespace
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

        // Calculate offset directly from the selection range by walking the DOM
        // This avoids text normalization mismatches between indexOf and DOM text
        const offsets = this.getOffsetsFromSelection(selection);
        if (!offsets) {
            console.warn('[SpanCore] Could not calculate offsets from selection');
            return null;
        }

        console.log('[SpanCore] createSpanFromSelection: container=' + (this.container ? this.container.id : 'NULL') + ' start=' + offsets.start + ' end=' + offsets.end + ' selected="' + selectedText + '"');

        return this.createSpanWithAlgorithm(offsets.start, offsets.end, selectedText, options);
    }

    /**
     * Calculate character offsets from a selection by walking the DOM tree.
     * This gives us the exact position in the raw DOM text, avoiding normalization issues.
     */
    getOffsetsFromSelection(selection) {
        if (!selection.rangeCount) return null;

        const range = selection.getRangeAt(0);
        const startContainer = range.startContainer;
        const endContainer = range.endContainer;
        const startOffset = range.startOffset;
        const endOffset = range.endOffset;

        // Walk through text nodes to find cumulative offset
        const textNodes = [];
        let cumulativeOffset = 0;

        const collectTextNodes = (node) => {
            if (node.nodeType === Node.TEXT_NODE) {
                textNodes.push({
                    node: node,
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
        collectTextNodes(this.container);

        // Find the offset for start and end
        let absoluteStart = null;
        let absoluteEnd = null;

        for (const tn of textNodes) {
            if (tn.node === startContainer) {
                absoluteStart = tn.start + startOffset;
            }
            if (tn.node === endContainer) {
                absoluteEnd = tn.start + endOffset;
            }
        }

        // Handle case where start/end containers are element nodes
        if (absoluteStart === null && startContainer.nodeType === Node.ELEMENT_NODE) {
            // startOffset is the index of the child node
            if (startOffset < startContainer.childNodes.length) {
                const childNode = startContainer.childNodes[startOffset];
                for (const tn of textNodes) {
                    if (tn.node === childNode || tn.node.parentNode === childNode) {
                        absoluteStart = tn.start;
                        break;
                    }
                }
            }
        }

        if (absoluteEnd === null && endContainer.nodeType === Node.ELEMENT_NODE) {
            if (endOffset > 0 && endOffset <= endContainer.childNodes.length) {
                const childNode = endContainer.childNodes[endOffset - 1];
                for (const tn of textNodes) {
                    if (tn.node === childNode || tn.node.parentNode === childNode) {
                        absoluteEnd = tn.end;
                        break;
                    }
                }
            }
        }

        if (absoluteStart === null || absoluteEnd === null) {
            console.warn('[SpanCore] Could not find absolute offsets for selection', {
                startContainer: startContainer.nodeName,
                endContainer: endContainer.nodeName,
                startOffset,
                endOffset
            });
            return null;
        }

        return { start: absoluteStart, end: absoluteEnd };
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
        // Use this.container (the element passed to the strategy constructor)
        // instead of hardcoded #text-content, so multi-field mode works
        const textElement = this.container || document.getElementById('text-content');
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

        // Use the text element itself for positioning reference
        // This ensures consistency with overlay positioning which is inside the text element
        const containerRect = textElement.getBoundingClientRect();

        const positions = Array.from(rects).map((rect) => ({
            x: rect.left - containerRect.left,
            y: rect.top - containerRect.top,
            width: rect.width,
            height: rect.height
        }));

        return positions;
    }

    /**
     * Get screen positions for text at specific character offsets.
     * Unlike getTextPositions(), this uses the provided offsets directly
     * instead of searching for the text with indexOf().
     *
     * @param {number} start - Start character offset in the text
     * @param {number} end - End character offset in the text
     * @returns {Array<{x, y, width, height}>|null} Screen positions relative to container, or null on error
     */
    getPositionsFromOffsets(start, end) {
        // Use this.container instead of hardcoded #text-content
        const textElement = this.container || document.getElementById('text-content');
        if (!textElement) {
            console.warn('[SpanCore] getPositionsFromOffsets: text-content element not found');
            return null;
        }

        // Collect text nodes with cumulative offsets
        const textNodes = [];
        let cumulativeOffset = 0;

        const collectTextNodes = (node) => {
            if (node.nodeType === Node.TEXT_NODE) {
                textNodes.push({
                    node: node,
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
            console.warn('[SpanCore] getPositionsFromOffsets: no text nodes found');
            return null;
        }

        // Find nodes containing start and end positions
        let startNode = null, startOffset = 0;
        let endNode = null, endOffset = 0;

        for (const tn of textNodes) {
            // Find start node
            if (startNode === null && start >= tn.start && start < tn.end) {
                startNode = tn.node;
                startOffset = start - tn.start;
            }
            // Find end node (can be same as start node)
            if (end > tn.start && end <= tn.end) {
                endNode = tn.node;
                endOffset = end - tn.start;
            }
        }

        if (!startNode || !endNode) {
            console.warn('[SpanCore] getPositionsFromOffsets: could not find text nodes for offsets', { start, end, totalLength: cumulativeOffset });
            return null;
        }

        // Create range and get bounding rectangles
        const range = document.createRange();
        try {
            range.setStart(startNode, startOffset);
            range.setEnd(endNode, endOffset);
        } catch (e) {
            console.error('[SpanCore] getPositionsFromOffsets: error setting range:', e);
            return null;
        }

        const rects = range.getClientRects();
        if (rects.length === 0) {
            console.warn('[SpanCore] getPositionsFromOffsets: no client rects returned');
            return null;
        }

        // Convert to positions relative to the text element container itself
        // This ensures consistency with overlay positioning which is also relative to text-content
        const containerRect = textElement.getBoundingClientRect();

        return Array.from(rects).map(rect => ({
            x: rect.left - containerRect.left,
            y: rect.top - containerRect.top,
            width: rect.width,
            height: rect.height
        }));
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
        if (span.schema) {
            overlay.dataset.schema = span.schema;
        }
        if (span.target_field) {
            overlay.dataset.targetField = span.target_field;
        }
        if (isAiSpan) {
            overlay.dataset.isAiSpan = 'true';
        }

        overlay.style.position = 'absolute';
        overlay.style.pointerEvents = 'none';
        overlay.style.zIndex = isAiSpan ? OVERLAY_Z_INDEX.AI_KEYWORD : OVERLAY_Z_INDEX.USER_SPAN;

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
        this.selectedTargetField = '';
        this.currentSchema = null;
        this.isInitialized = false;
        this.currentInstanceId = null;
        this.lastKnownInstanceId = null;
        this.positioningStrategy = null;
        this.schemas = {};

        // Multi-span support: per-field positioning strategies
        this.fieldStrategies = {}; // { fieldKey: UnifiedPositioningStrategy }

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
    /**
     * Insert AI keyword highlights with bordered (unfilled) overlays
     * @param {Array} highlights - Array of {label, start, end, text, schema}
     * @param {string} annotationId - The annotation ID
     */
    insertAiKeywordHighlights(highlights, annotationId) {
        console.log('[SpanManager] insertAiKeywordHighlights called:', { highlights, annotationId });

        if (!highlights || !Array.isArray(highlights) || highlights.length === 0) {
            console.log('[SpanManager] No highlights to insert');
            return;
        }

        this.deleteOneAiSpan(annotationId);

        const spanOverlays = document.getElementById('span-overlays');
        if (!spanOverlays) {
            console.log('[SpanManager] span-overlays element not found');
            return;
        }

        const createdOverlays = [];

        highlights.forEach((highlight) => {
            const { label, start, end, text, schema } = highlight;

            if (!this.positioningStrategy || !this.positioningStrategy.isInitialized) {
                console.warn('[SpanManager] Positioning strategy not initialized');
                return;
            }

            // Use getPositionsFromOffsets() which respects the provided offsets
            // instead of getTextPositions() which does indexOf() and ignores offsets
            const positions = this.positioningStrategy.getPositionsFromOffsets(start, end);
            if (!positions || positions.length === 0) {
                console.warn('[SpanManager] No positions found for highlight:', { start, end, text });
                return;
            }

            // Get color for this label from schema colors
            const color = this.getAiKeywordColor(label, schema);

            const span = {
                id: `ai_keyword_${annotationId}_${start}_${end}_${Date.now()}`,
                start: start,
                end: end,
                text: text,
                label: label
            };

            // Create bordered overlay (not filled)
            const overlay = this.createBorderedOverlay(span, positions, color);

            if (overlay) {
                overlay.dataset.aiAnnotationId = annotationId;
                overlay.title = `${label}: "${text}"`;
                spanOverlays.appendChild(overlay);
                createdOverlays.push(overlay);
            }
        });

        if (createdOverlays.length > 0) {
            this.aiSpans.set(annotationId, createdOverlays);
        }
    }

    /**
     * Create a bordered (unfilled) overlay for keyword highlighting.
     * Used for AI keyword highlights and admin keyword highlights.
     */
    createBorderedOverlay(span, positions, color) {
        // Padding for visual breathing room
        const HORIZONTAL_PADDING = 2;
        const VERTICAL_PADDING = 1;

        const overlay = document.createElement('div');
        overlay.className = 'span-overlay ai-keyword-overlay';
        overlay.dataset.spanId = span.id;
        overlay.dataset.label = span.label;
        overlay.style.position = 'absolute';
        overlay.style.pointerEvents = 'none';
        overlay.style.zIndex = OVERLAY_Z_INDEX.AI_KEYWORD;

        positions.forEach((pos) => {
            const segment = document.createElement('div');
            segment.className = 'span-segment ai-keyword-segment';
            segment.style.position = 'absolute';
            // FIX: Use correct property names (x, y not left, top)
            segment.style.left = `${pos.x - HORIZONTAL_PADDING}px`;
            segment.style.top = `${pos.y - VERTICAL_PADDING}px`;
            segment.style.width = `${pos.width + 2 * HORIZONTAL_PADDING}px`;
            segment.style.height = `${pos.height + 2 * VERTICAL_PADDING}px`;
            segment.style.border = `2px solid ${color}`;
            segment.style.borderRadius = '3px';
            segment.style.backgroundColor = 'transparent';
            segment.style.pointerEvents = 'none';
            segment.style.boxSizing = 'border-box';
            overlay.appendChild(segment);
        });

        return overlay;
    }

    /**
     * Get color for AI keyword highlight based on label
     */
    getAiKeywordColor(label, schemaName) {
        // Try to get from loaded colors (with case-insensitive fallback)
        if (this.colors && schemaName && this.colors[schemaName]) {
            const schemaColors = this.colors[schemaName];
            // Try exact match first
            if (schemaColors[label]) {
                const color = schemaColors[label];
                if (color.startsWith('(')) {
                    return `rgba${color.replace(')', ', 0.8)')}`;
                }
                return color;
            }
            // Try case-insensitive match
            const lowerLabel = label.toLowerCase();
            for (const [key, color] of Object.entries(schemaColors)) {
                if (key.toLowerCase() === lowerLabel) {
                    if (color.startsWith('(')) {
                        return `rgba${color.replace(')', ', 0.8)')}`;
                    }
                    return color;
                }
            }
        }

        // Fallback colors for common labels (case-insensitive)
        const fallbackColors = {
            'positive': 'rgba(34, 197, 94, 0.8)',   // green
            'negative': 'rgba(239, 68, 68, 0.8)',   // red
            'neutral': 'rgba(156, 163, 175, 0.8)', // gray
            'yes': 'rgba(34, 197, 94, 0.8)',        // green
            'no': 'rgba(239, 68, 68, 0.8)',         // red
            'maybe': 'rgba(245, 158, 11, 0.8)',     // amber
        };

        const lowerLabel = label.toLowerCase();
        return fallbackColors[lowerLabel] || 'rgba(245, 158, 11, 0.8)';
    }

    insertAiSpans(keywords, annotationId) {
        console.log('[SpanManager] insertAiSpans called:', { keywords, annotationId });

        if (!keywords || !Array.isArray(keywords) || keywords.length === 0) {
            console.log('[SpanManager] No keywords to insert, returning early');
            return;
        }

        this.deleteOneAiSpan(annotationId);

        const spanOverlays = document.getElementById('span-overlays');
        if (!spanOverlays) {
            console.log('[SpanManager] span-overlays element not found - keyword highlighting only works with span annotation type');
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

            // Set up event listeners early (before async strategy init that might block)
            this.setupEventListeners();

            // Check for instance_display span target fields first
            const spanTargetFields = document.querySelectorAll('.display-field[data-span-target="true"]');
            console.log('[SpanManager] init: found', spanTargetFields.length, 'span target fields');
            if (spanTargetFields.length > 0) {
                // Multi-span / instance_display mode
                for (const field of spanTargetFields) {
                    const fieldKey = field.dataset.fieldKey;
                    const textContent = field.querySelector('.text-content');
                    console.log('[SpanManager] init: field', fieldKey, 'textContent=', textContent?.id);
                    if (textContent && fieldKey) {
                        // Ensure text content has position: relative for overlay positioning
                        // This is critical: overlays are positioned relative to textContent itself
                        if (!textContent.style.position || textContent.style.position === 'static') {
                            textContent.style.position = 'relative';
                        }

                        // Create span-overlays container for this field if not present
                        // Append INSIDE textContent so positions are relative to the same container
                        let overlaysEl = textContent.querySelector('.span-overlays-field');
                        if (!overlaysEl) {
                            overlaysEl = document.createElement('div');
                            overlaysEl.className = 'span-overlays-field';
                            overlaysEl.id = `span-overlays-${fieldKey}`;
                            overlaysEl.style.cssText = 'position: absolute; top: 0; left: 0; right: 0; bottom: 0; pointer-events: none; z-index: 2;';
                            textContent.appendChild(overlaysEl);
                        }

                        const strategy = new UnifiedPositioningStrategy(textContent);
                        await strategy.initialize();
                        this.fieldStrategies[fieldKey] = strategy;
                        console.log('[SpanManager] init: strategy ready for', fieldKey);
                    }
                }
                // Use the first field as the default positioning strategy
                const firstKey = Object.keys(this.fieldStrategies)[0];
                if (firstKey) {
                    this.positioningStrategy = this.fieldStrategies[firstKey];
                }
            } else {
                // Legacy single-field mode
                const textContent = document.getElementById('text-content');
                if (textContent) {
                    this.positioningStrategy = new UnifiedPositioningStrategy(textContent);
                    await this.positioningStrategy.initialize();
                }
            }

            await this.loadSchemas();
            await this.loadColors();
            this.setupResizeHandler();
            this.setupOverlayInteractions();
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
                'positive': 'rgba(110, 86, 207, 0.15)',  // Purple
                'negative': 'rgba(239, 68, 68, 0.15)',   // Red
                'neutral': 'rgba(113, 113, 122, 0.15)',  // Gray
                'span': 'rgba(110, 86, 207, 0.15)'       // Purple
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

        // Also listen on instance_display span target fields
        const spanTargetFields = document.querySelectorAll('.display-field[data-span-target="true"]');
        for (const field of spanTargetFields) {
            field.addEventListener('mouseup', () => this.handleTextSelection());
            field.addEventListener('keyup', () => this.handleTextSelection());
        }

        document.addEventListener('click', (e) => {
            if (e.target.classList.contains('span-delete')) {
                e.stopPropagation();
                const annotationId = e.target.closest('.span-highlight').dataset.annotationId;
                this.deleteSpan(annotationId);
            }
        });
    }

    selectLabel(label, schema = null, targetField = null) {
        this.selectedLabel = label;
        this.selectedTargetField = targetField || '';
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

            // Find the text content element - may be legacy #text-content or instance_display fields
            let textContent = document.getElementById('text-content');
            if (!textContent || textContent.closest('[style*="display: none"]')) {
                // Try instance_display span target fields
                const firstField = Object.keys(this.fieldStrategies)[0];
                if (firstField) {
                    textContent = document.getElementById(`text-content-${firstField}`);
                }
            }
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

            // Get response text first to debug JSON parsing issues
            const responseText = await response.text();
            let responseData;
            try {
                responseData = JSON.parse(responseText);
            } catch (jsonError) {
                console.error('[SpanManager] JSON parse error for /api/spans/', instanceId);
                console.error('[SpanManager] Response text (first 500 chars):', responseText.substring(0, 500));
                throw new Error(`JSON parse error: ${jsonError.message}`);
            }
            this.annotations = responseData;

            // Only update data-original-text on legacy #text-content, not on per-field elements
            // Per-field elements already have correct data-original-text from server rendering
            if (this.annotations && this.annotations.text && textContent) {
                const hasFieldStrategies = Object.keys(this.fieldStrategies).length > 0;
                if (!hasFieldStrategies) {
                    const plainText = this.annotations.text.replace(/<[^>]*>/g, '').trim();
                    textContent.setAttribute('data-original-text', plainText);
                }
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
            return 'rgba(110, 86, 207, 0.15)';
        }

        if (!this.colors || Object.keys(this.colors).length === 0) {
            console.warn(`[SpanManager] getSpanColor: Colors not loaded for label '${label}'. Using fallback color.`);
            return 'rgba(110, 86, 207, 0.15)';
        }

        if (!this.colors[this.currentSchema]) {
            console.warn(`[SpanManager] getSpanColor: Schema '${this.currentSchema}' not found in colors. Available schemas: ${Object.keys(this.colors).join(', ')}. Using fallback color.`);
            return 'rgba(110, 86, 207, 0.15)';
        }

        const schemaColors = this.colors[this.currentSchema];
        if (!schemaColors[label]) {
            console.warn(`[SpanManager] getSpanColor: Label '${label}' not found in schema '${this.currentSchema}'. Available labels: ${Object.keys(schemaColors).join(', ')}. Using fallback color.`);
            return 'rgba(110, 86, 207, 0.15)';
        }

        const color = schemaColors[label];
        if (color.startsWith('(')) {
            return `rgba${color.replace(')', ', 0.15)')}`;
        }
        return color;
    }

    clearAllStateAndOverlays() {
        // Clear legacy overlay container
        const spanOverlays = document.getElementById('span-overlays');
        if (spanOverlays) {
            const regularOverlays = spanOverlays.querySelectorAll('.span-overlay-pure:not(.span-overlay-ai)');
            regularOverlays.forEach(overlay => overlay.remove());
        }

        // Clear per-field overlay containers (multi-span mode)
        for (const fieldKey of Object.keys(this.fieldStrategies)) {
            const fieldOverlays = document.getElementById(`span-overlays-${fieldKey}`);
            if (fieldOverlays) {
                const regularOverlays = fieldOverlays.querySelectorAll('.span-overlay-pure:not(.span-overlay-ai)');
                regularOverlays.forEach(overlay => overlay.remove());
            }
        }

        this.annotations = { spans: [] };
        // Don't clear currentSchema - keep it for consistency
    }

    renderSpans() {
        const hasFieldStrategies = Object.keys(this.fieldStrategies).length > 0;

        if (hasFieldStrategies) {
            // Multi-field mode: clear and render per-field
            for (const fieldKey of Object.keys(this.fieldStrategies)) {
                const overlaysEl = document.getElementById(`span-overlays-${fieldKey}`);
                if (overlaysEl) {
                    const regularOverlays = overlaysEl.querySelectorAll('.span-overlay-pure:not(.span-overlay-ai)');
                    regularOverlays.forEach(overlay => overlay.remove());
                }
            }

            const spans = this.getSpans();
            if (!spans || spans.length === 0) return;

            const sortedSpans = [...spans].sort((a, b) => a.start - b.start);
            sortedSpans.forEach((span, index) => {
                const fieldKey = span.target_field || '';
                const strategy = this.fieldStrategies[fieldKey] || this.positioningStrategy;
                const overlaysEl = document.getElementById(`span-overlays-${fieldKey}`) || document.getElementById('span-overlays');
                if (strategy && overlaysEl) {
                    this.renderSpanOverlay(span, index, null, overlaysEl, strategy);
                }
            });
        } else {
            // Legacy single-field mode
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
    }

    renderSpanOverlay(span, layerIndex, textContent, spanOverlays, strategy = null) {
        const activeStrategy = strategy || this.positioningStrategy;
        if (!activeStrategy || !activeStrategy.isInitialized) {
            return;
        }

        // Use getPositionsFromOffsets (offset-based) instead of getTextPositions (text-search-based)
        // This is critical for multi-field mode where the API might return text from the wrong field
        const positions = activeStrategy.getPositionsFromOffsets(span.start, span.end);
        if (!positions || positions.length === 0) {
            return;
        }

        const color = this.getSpanColor(span.label);
        const overlay = activeStrategy.createOverlay(span, positions, {
            isAiSpan: false,
            color: color
        });

        if (overlay) {
            spanOverlays.appendChild(overlay);
        }
    }

    handleTextSelection() {
        const selection = window.getSelection();

        console.warn('[SpanManager] handleTextSelection ENTRY: rangeCount=' + selection.rangeCount + ' isCollapsed=' + selection.isCollapsed + ' selectedLabel=' + this.selectedLabel + ' currentSchema=' + this.currentSchema);

        if (!selection.rangeCount || selection.isCollapsed) {
            return;
        }

        const selectedLabel = this.getSelectedLabel();
        if (!selectedLabel) {
            console.warn('[SpanManager] handleTextSelection: no selectedLabel, returning');
            return;
        }

        // Detect which field the selection is in and pick the right positioning strategy
        let targetField = this.selectedTargetField || '';
        let strategy = this.positioningStrategy;
        let overlaysContainer = document.getElementById('span-overlays');

        const hasFieldStrategies = Object.keys(this.fieldStrategies).length > 0;
        console.warn('[SpanManager] handleTextSelection: fieldStrategies=', Object.keys(this.fieldStrategies), 'selectedLabel=', selectedLabel);

        if (selection.rangeCount > 0) {
            const startNode = selection.getRangeAt(0).startContainer;
            const el = startNode.nodeType === Node.TEXT_NODE ? startNode.parentElement : startNode;
            const textContentEl = el ? el.closest('[id^="text-content-"]') : null;
            console.warn('[SpanManager] handleTextSelection: textContentEl=', textContentEl?.id, 'el=', el?.id || el?.className);
            if (textContentEl) {
                const fieldKey = textContentEl.id.replace('text-content-', '');
                if (fieldKey && this.fieldStrategies[fieldKey]) {
                    targetField = fieldKey;
                    strategy = this.fieldStrategies[fieldKey];
                    overlaysContainer = document.getElementById(`span-overlays-${fieldKey}`);
                }
            }
        }

        if (!strategy || !strategy.isInitialized) {
            console.warn('[SpanManager] handleTextSelection: strategy not ready, targetField=' + targetField);
            return;
        }

        console.warn('[SpanManager] handleTextSelection: using strategy for field=' + targetField + ' container=' + (strategy.container ? strategy.container.id : 'NULL') + ' overlays=' + (overlaysContainer ? overlaysContainer.id : 'NULL'));

        // Get color BEFORE creating the overlay so it's created with the correct color
        const color = this.getSpanColor(selectedLabel);

        // Pass color to createSpanFromSelection so overlay is created with correct color
        const result = strategy.createSpanFromSelection(selection, {
            color: color
        });
        if (!result) {
            console.warn('[SpanManager] handleTextSelection: createSpanFromSelection returned null for field=' + targetField);
            return;
        }

        const { span, overlay } = result;
        span.label = selectedLabel;
        span.schema = this.currentSchema;
        span.target_field = targetField;

        if (overlay) {
            // Update the label text to match the selected label
            const label = overlay.querySelector('.span-label');
            if (label) {
                label.textContent = selectedLabel;
            }

            // Append the overlay to the correct container
            if (overlaysContainer) {
                overlaysContainer.appendChild(overlay);
                console.warn('[SpanManager] handleTextSelection: overlay appended to ' + overlaysContainer.id + ' for field=' + targetField);
            } else {
                console.warn('[SpanManager] handleTextSelection: no overlaysContainer for field=' + targetField);
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
                    value: 1,
                    target_field: span.target_field || ''
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

            // Use getPositionsFromOffsets() which respects the provided offsets
            const positions = this.positioningStrategy.getPositionsFromOffsets(start, end);
            if (!positions || positions.length === 0) {
                console.warn('[SpanManager] No positions found for admin keyword:', { start, end, text });
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
                isAiSpan: true,  // Use bordered style
                color: keywordColor
            });

            if (overlay) {
                overlay.dataset.keywordHighlight = 'true';
                overlay.dataset.schema = schema || '';
                overlay.dataset.label = label || '';
                overlay.title = reasoning || `Keyword: "${text}" → ${label}`;
                overlay.classList.add('keyword-highlight-overlay');
                // Admin keywords use a lower z-index than AI keywords
                overlay.style.zIndex = OVERLAY_Z_INDEX.ADMIN_KEYWORD;
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

    // ==================== RESIZE HANDLING ====================

    /**
     * Setup resize handler to reposition overlays when window resizes.
     * Uses debouncing to avoid performance issues during resize.
     */
    setupResizeHandler() {
        let resizeTimeout = null;
        const DEBOUNCE_MS = 150;

        const handleResize = () => {
            if (resizeTimeout) {
                clearTimeout(resizeTimeout);
            }
            resizeTimeout = setTimeout(() => {
                this.repositionAllOverlays();
            }, DEBOUNCE_MS);
        };

        window.addEventListener('resize', handleResize);

        // Also observe container size changes (for dynamic layouts)
        if (typeof ResizeObserver !== 'undefined') {
            const instanceText = document.getElementById('instance-text');
            if (instanceText) {
                const resizeObserver = new ResizeObserver(handleResize);
                resizeObserver.observe(instanceText);
            }
        }

        spanCoreDebugLog('[SpanManager] Resize handler initialized');
    }

    /**
     * Reposition all overlays based on current text positions.
     * Called after resize to ensure overlays stay aligned with text.
     */
    repositionAllOverlays() {
        spanCoreDebugLog('[SpanManager] Repositioning all overlays');

        // Re-render user span overlays
        this.renderSpans();

        // Re-render admin keyword highlights
        if (this.currentInstanceId) {
            this.loadKeywordHighlights(this.currentInstanceId);
        }

        // Clear AI keyword overlays on resize since they're temporary
        // User can re-click the keyword button to regenerate
        this.clearAiSpans();
    }

    // ==================== UNIFIED OVERLAY INTERACTIONS ====================

    /**
     * Setup unified interaction handlers for all overlay types.
     * Provides consistent hover effects and click behavior.
     */
    setupOverlayInteractions() {
        const spanOverlays = document.getElementById('span-overlays');
        if (!spanOverlays) return;

        // Use event delegation for hover effects
        spanOverlays.addEventListener('mouseenter', (e) => {
            const segment = e.target.closest('.span-highlight-segment, .span-segment');
            if (segment) {
                this.handleSegmentHover(segment, true);
            }
        }, true);

        spanOverlays.addEventListener('mouseleave', (e) => {
            const segment = e.target.closest('.span-highlight-segment, .span-segment');
            if (segment) {
                this.handleSegmentHover(segment, false);
            }
        }, true);

        spanCoreDebugLog('[SpanManager] Overlay interactions initialized');
    }

    /**
     * Handle hover state for overlay segments.
     * @param {Element} segment - The segment element
     * @param {boolean} isHovering - Whether mouse is entering or leaving
     */
    handleSegmentHover(segment, isHovering) {
        const overlay = segment.closest('.span-overlay, .span-overlay-pure, .span-overlay-ai, .ai-keyword-overlay, .keyword-highlight-overlay');
        if (!overlay) return;

        if (isHovering) {
            // Highlight all segments of the same overlay
            overlay.querySelectorAll('.span-highlight-segment, .span-segment').forEach(seg => {
                seg.style.filter = 'brightness(0.85)';
            });

            // Show tooltip if available (for AI/keyword overlays without controls)
            const tooltipText = overlay.title || overlay.dataset.label;
            const hasControls = overlay.querySelector('.span-controls');
            if (tooltipText && !hasControls) {
                this.showOverlayTooltip(segment, tooltipText);
            }
        } else {
            // Remove highlight
            overlay.querySelectorAll('.span-highlight-segment, .span-segment').forEach(seg => {
                seg.style.filter = '';
            });
            this.hideOverlayTooltip();
        }
    }

    /**
     * Show tooltip near a segment.
     * @param {Element} segment - The segment to position tooltip near
     * @param {string} text - The tooltip text
     */
    showOverlayTooltip(segment, text) {
        const spanOverlays = document.getElementById('span-overlays');
        if (!spanOverlays) return;

        let tooltip = document.getElementById('overlay-tooltip');
        if (!tooltip) {
            tooltip = document.createElement('div');
            tooltip.id = 'overlay-tooltip';
            tooltip.className = 'overlay-tooltip';
            tooltip.style.cssText = `
                position: absolute;
                background: rgba(0, 0, 0, 0.85);
                color: white;
                padding: 4px 8px;
                border-radius: 4px;
                font-size: 12px;
                pointer-events: none;
                z-index: ${OVERLAY_Z_INDEX.TOOLTIP};
                white-space: nowrap;
                max-width: 300px;
                overflow: hidden;
                text-overflow: ellipsis;
            `;
            spanOverlays.appendChild(tooltip);
        }

        const rect = segment.getBoundingClientRect();
        const containerRect = document.getElementById('instance-text').getBoundingClientRect();

        tooltip.textContent = text;
        tooltip.style.left = `${rect.left - containerRect.left}px`;
        tooltip.style.top = `${Math.max(0, rect.top - containerRect.top - 28)}px`;
        tooltip.style.display = 'block';
    }

    /**
     * Hide the overlay tooltip.
     */
    hideOverlayTooltip() {
        const tooltip = document.getElementById('overlay-tooltip');
        if (tooltip) {
            tooltip.style.display = 'none';
        }
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

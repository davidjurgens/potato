/**
 * Frontend Span Manager for Potato Annotation Platform
 * Handles span annotation rendering, interaction, and API communication
 */

class SpanManager {
    constructor() {
        this.currentInstanceId = null;
        this.annotations = {spans: []};
        this.colors = {};
        this.selectedLabel = null;
        this.isInitialized = false;
        this.retryCount = 0;
        this.maxRetries = 3;
    }

    /**
     * Initialize the span manager
     */
    async initialize() {
        try {
            console.log('SpanManager: Initializing...');
            await this.loadColors();
            this.setupEventListeners();
            this.isInitialized = true;
            console.log('SpanManager: Initialized successfully');
        } catch (error) {
            console.error('SpanManager: Initialization failed:', error);
            if (this.retryCount < this.maxRetries) {
                this.retryCount++;
                console.log(`SpanManager: Retrying initialization (${this.retryCount}/${this.maxRetries})`);
                setTimeout(() => this.initialize(), 1000);
            }
        }
    }

    /**
     * Load color scheme from API
     */
    async loadColors() {
        try {
            const response = await fetch('/api/colors');
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            this.colors = await response.json();
            console.log('SpanManager: Colors loaded:', this.colors);
        } catch (error) {
            console.error('SpanManager: Error loading colors:', error);
            // Fallback colors
            this.colors = {
                'positive': '#d4edda',
                'negative': '#f8d7da',
                'neutral': '#d1ecf1',
                'span': '#ffeaa7'
            };
        }
    }

    /**
     * Setup event listeners for span interaction
     */
    setupEventListeners() {
        // Label selection
        document.addEventListener('click', (e) => {
            if (e.target.classList.contains('label-button')) {
                this.selectLabel(e.target.dataset.label);
            }
        });

        // Text selection handling
        const textContainer = document.getElementById('instance-text');
        if (textContainer) {
            textContainer.addEventListener('mouseup', () => this.handleTextSelection());
            textContainer.addEventListener('keyup', () => this.handleTextSelection());
        }

        // Span deletion
        document.addEventListener('click', (e) => {
            if (e.target.classList.contains('span-delete')) {
                e.stopPropagation();
                const annotationId = e.target.closest('.span-highlight').dataset.annotationId;
                this.deleteSpan(annotationId);
            }
        });
    }

    /**
     * Select a label for annotation
     */
    selectLabel(label) {
        // Update UI
        document.querySelectorAll('.label-button').forEach(btn => {
            btn.classList.remove('active');
        });
        const button = document.querySelector(`[data-label="${label}"]`);
        if (button) {
            button.classList.add('active');
        }

        this.selectedLabel = label;
        console.log('SpanManager: Selected label:', label);
    }

    /**
     * Load annotations for current instance
     */
    async loadAnnotations(instanceId) {
        if (!instanceId) return Promise.resolve();

        try {
            console.log('SpanManager: Loading annotations for instance:', instanceId);
            const response = await fetch(`/api/spans/${instanceId}`);

            if (!response.ok) {
                if (response.status === 404) {
                    // No annotations yet
                    this.annotations = {spans: []};
                    console.log('SpanManager: No annotations found, set to:', this.annotations);
                    this.renderSpans();
                    return Promise.resolve();
                }
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            // Store the full API response, not just the spans array
            this.annotations = await response.json();
            this.currentInstanceId = instanceId;
            console.log('SpanManager: Loaded annotations:', this.annotations);
            console.log('SpanManager: this.annotations.spans:', this.annotations.spans);
            console.log('SpanManager: getSpans() would return:', this.getSpans());

            // Render spans
            console.log('SpanManager: About to call renderSpans()');
            this.renderSpans();
            console.log('SpanManager: renderSpans() call completed');
            return Promise.resolve(this.annotations);
        } catch (error) {
            console.error('SpanManager: Error loading annotations:', error);
            this.annotations = {spans: []};
            this.renderSpans();
            return Promise.reject(error);
        }
    }

    /**
     * Render all spans in the text container
     */
    renderSpans() {
        const textContainer = document.getElementById('instance-text');
        if (!textContainer) {
            console.warn('SpanManager: Text container not found');
            return;
        }

        // Get spans from the correct property
        const spans = this.getSpans();
        console.log('SpanManager: Starting renderSpans with', spans?.length || 0, 'spans');
        console.log('SpanManager: Spans data:', spans);

        // Clear existing content
        textContainer.innerHTML = '';

        if (!spans || spans.length === 0) {
            // Just display the original text
            const originalText = window.currentInstance?.text || '';
            textContainer.textContent = originalText;
            console.log('SpanManager: No spans to render, displaying original text:', originalText);
            return;
        }

        // Calculate overlap depths before rendering
        const overlapData = this.calculateOverlapDepths(spans);
        console.log('SpanManager: Overlap data:', overlapData);

        // Sort spans by start position for proper rendering order
        const sortedSpans = [...spans].sort((a, b) => a.start - b.start);

        // Create boundary events for span start/end positions
        const boundaries = [];
        sortedSpans.forEach(span => {
            boundaries.push({ position: span.start, span: span, type: 'start' });
            boundaries.push({ position: span.end, span: span, type: 'end' });
        });
        boundaries.sort((a, b) => a.position - b.position);

        console.log('SpanManager: Boundaries:', boundaries);

        // Get the original text
        const text = window.currentInstance?.text || textContainer.textContent || '';
        console.log('SpanManager: Original text length:', text.length);

        // Render spans using boundary approach
        const fragmentStack = [document.createDocumentFragment()];
        const openSpans = [];
        let currentPos = 0;

        for (const boundary of boundaries) {
            // Add text before this boundary
            if (currentPos < boundary.position) {
                const textNode = document.createTextNode(text.substring(currentPos, boundary.position));
                fragmentStack[fragmentStack.length - 1].appendChild(textNode);
            }
            currentPos = boundary.position;

            if (boundary.type === 'start') {
                // Open a new span
                const spanElement = document.createElement('span');
                spanElement.className = 'annotation-span';
                spanElement.dataset.spanId = boundary.span.id;
                spanElement.dataset.start = boundary.span.start;
                spanElement.dataset.end = boundary.span.end;
                spanElement.dataset.label = boundary.span.label;

                // Apply the correct color for this label
                const backgroundColor = this.getSpanColor(boundary.span.label);
                if (backgroundColor) {
                    spanElement.style.backgroundColor = backgroundColor;
                }

                // Add delete button
                const deleteBtn = document.createElement('button');
                deleteBtn.className = 'span-delete-btn';
                deleteBtn.innerHTML = '×';
                deleteBtn.title = 'Delete span';
                deleteBtn.onclick = (e) => {
                    e.stopPropagation();
                    this.deleteSpan(boundary.span.id);
                };
                spanElement.appendChild(deleteBtn);

                // Add label display
                const labelSpan = document.createElement('span');
                labelSpan.className = 'span-label';
                labelSpan.textContent = boundary.span.label;
                spanElement.appendChild(labelSpan);

                // Push new fragment for nested content
                const innerFragment = document.createDocumentFragment();
                fragmentStack.push(innerFragment);
                openSpans.push({ span: boundary.span, element: spanElement });
            } else {
                // Close the most recently opened span that matches
                let idx = openSpans.length - 1;
                while (idx >= 0 && openSpans[idx].span.id !== boundary.span.id) {
                    idx--;
                }
                if (idx >= 0) {
                    // Store the element before modifying the array
                    const spanElement = openSpans[idx].element;

                    // Pop all fragments above idx
                    while (openSpans.length - 1 > idx) {
                        // Unwind nested spans if needed
                        const unwound = fragmentStack.pop();
                        openSpans.pop();
                        fragmentStack[fragmentStack.length - 1].appendChild(unwound);
                    }
                    // Now close the matching span
                    const inner = fragmentStack.pop();
                    openSpans.pop();
                    spanElement.appendChild(inner);
                    fragmentStack[fragmentStack.length - 1].appendChild(spanElement);
                }
            }
        }
        // Add any remaining text
        if (currentPos < text.length) {
            const textNode = document.createTextNode(text.substring(currentPos));
            fragmentStack[fragmentStack.length - 1].appendChild(textNode);
        }
        // Unwind any remaining open spans (should not happen for well-formed spans)
        while (openSpans.length > 0) {
            const inner = fragmentStack.pop();
            const { element } = openSpans.pop();
            element.appendChild(inner);
            fragmentStack[fragmentStack.length - 1].appendChild(element);
        }
        // Append to container
        textContainer.appendChild(fragmentStack[0]);

        // Apply overlap styling after rendering
        const spanElements = textContainer.querySelectorAll('.annotation-span');
        this.applyOverlapStyling(spanElements, overlapData);

        console.log('SpanManager: Rendered', spans.length, 'spans');
        console.log('SpanManager: Final DOM has', spanElements.length, 'span elements');
        console.log('SpanManager: Final text container content:', textContainer.innerHTML.substring(0, 200) + '...');
    }

    /**
     * Handle text selection and create annotation
     */
    handleTextSelection() {
        const selection = window.getSelection();
        if (!selection.rangeCount || selection.isCollapsed) return;

        if (!this.selectedLabel) {
            this.showStatus('Please select a label first', 'error');
            return;
        }

        const range = selection.getRangeAt(0);
        const textContainer = document.getElementById('instance-text');
        const selectedText = selection.toString().trim();

        if (!selectedText) return;

        // Calculate position in original text
        const start = this.getOriginalTextPosition(textContainer, range.startContainer, range.startOffset);
        const end = start + selectedText.length;

        console.log('SpanManager: Creating annotation:', {
            text: selectedText,
            start: start,
            end: end,
            label: this.selectedLabel
        });

        // Create annotation
        this.createAnnotation(selectedText, start, end, this.selectedLabel)
            .then(result => {
                console.log('SpanManager: Annotation creation successful:', result);
            })
            .catch(error => {
                console.error('SpanManager: Annotation creation failed:', error);
            });

        // Clear selection
        selection.removeAllRanges();
    }

    /**
     * Calculate position in original text from DOM position
     * This is a more robust implementation that works with rendered spans
     */
    getOriginalTextPosition(container, node, offset) {
        // Get the original text from the global variable
        let originalText;
        if (window.currentInstance && window.currentInstance.text) {
            originalText = window.currentInstance.text;
        } else {
            // Fallback to container text content
            originalText = container.textContent || container.innerText;
        }

        if (!originalText) {
            console.warn('SpanManager: No original text available');
            return 0;
        }

        // Create a tree walker to traverse text nodes
        const walker = document.createTreeWalker(
            container,
            NodeFilter.SHOW_TEXT,
            null,
            false
        );

        let currentNode;
        let textSoFar = '';
        let foundNode = false;

        // Walk through text nodes to find our target node
        while (currentNode = walker.nextNode()) {
            // Skip text nodes that belong to UI elements (delete buttons and labels)
            const parent = currentNode.parentElement;
            if (parent && (
                parent.classList.contains('span-delete-btn') ||
                parent.classList.contains('span-label') ||
                parent.closest('.span-delete-btn') ||
                parent.closest('.span-label')
            )) {
                continue; // Skip this text node
            }

            if (currentNode === node) {
                // Found our target node, add the text up to the offset
                textSoFar += currentNode.textContent.substring(0, offset);
                foundNode = true;
                break;
            }
            // Add the full text of this node
            textSoFar += currentNode.textContent;
        }

        if (!foundNode) {
            console.warn('SpanManager: Target node not found in DOM walk');
            return 0;
        }

        // The length of textSoFar gives us the offset in the original text
        const calculatedOffset = textSoFar.length;

        // Validate the offset
        if (calculatedOffset < 0) {
            console.warn('SpanManager: Calculated negative offset, using 0');
            return 0;
        }

        if (calculatedOffset > originalText.length) {
            console.warn('SpanManager: Calculated offset beyond text length, using text length');
            return originalText.length;
        }

        console.log('SpanManager: Calculated offset:', calculatedOffset, 'for text length:', originalText.length);
        return calculatedOffset;
    }

    /**
     * Create a new span annotation
     */
    async createAnnotation(spanText, start, end, label) {
        console.log('SpanManager: createAnnotation called with:', {spanText, start, end, label});
        if (!this.currentInstanceId) {
            this.showStatus('No instance loaded', 'error');
            return Promise.reject(new Error('No instance loaded'));
        }

        try {
            console.log('SpanManager: Sending POST to /updateinstance');
            const response = await fetch('/updateinstance', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    type: 'span',
                    schema: 'sentiment', // This should come from config
                    state: [
                        {
                            name: label,
                            start: start,
                            end: end,
                            title: label,
                            value: spanText
                        }
                    ],
                    instance_id: this.currentInstanceId
                })
            });

            if (response.ok) {
                const result = await response.json();
                console.log('SpanManager: POST successful, result:', result);
                // Reload all annotations to ensure consistency
                console.log('SpanManager: About to call loadAnnotations');
                await this.loadAnnotations(this.currentInstanceId);
                console.log('SpanManager: loadAnnotations completed');
                this.showStatus(`Created ${label} annotation: "${spanText}"`, 'success');
                console.log('SpanManager: Annotation created:', result);
                return result; // Return the result
            } else {
                const error = await response.json();
                const errorMessage = `Error: ${error.error || 'Failed to create annotation'}`;
                this.showStatus(errorMessage, 'error');
                return Promise.reject(new Error(errorMessage));
            }
        } catch (error) {
            console.error('SpanManager: Error creating annotation:', error);
            this.showStatus('Error creating annotation', 'error');
            return Promise.reject(error);
        }
    }

    /**
     * Delete a span annotation
     */
    async deleteSpan(annotationId) {
        if (!this.currentInstanceId) {
            this.showStatus('No instance loaded', 'error');
            return;
        }

        try {
            // Find the span to delete from current annotations
            const spanToDelete = this.annotations.spans.find(span => span.id === annotationId);
            if (!spanToDelete) {
                this.showStatus('Span not found', 'error');
                return;
            }

            const response = await fetch('/updateinstance', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    type: 'span',
                    schema: 'sentiment', // This should come from config
                    state: [
                        {
                            name: spanToDelete.label,
                            start: spanToDelete.start,
                            end: spanToDelete.end,
                            title: spanToDelete.label,
                            value: null // This signals deletion
                        }
                    ],
                    instance_id: this.currentInstanceId
                })
            });

            if (response.ok) {
                // Reload all annotations to ensure consistency
                await this.loadAnnotations(this.currentInstanceId);
                this.showStatus('Annotation deleted', 'success');
                console.log('SpanManager: Annotation deleted:', annotationId);
            } else {
                const error = await response.json();
                this.showStatus(`Error: ${error.error || 'Failed to delete annotation'}`, 'error');
            }
        } catch (error) {
            console.error('SpanManager: Error deleting annotation:', error);
            this.showStatus('Error deleting annotation', 'error');
        }
    }

    /**
     * Show status message
     */
    showStatus(message, type) {
        const statusDiv = document.getElementById('status');
        if (statusDiv) {
            statusDiv.textContent = message;
            statusDiv.className = `status ${type}`;
            statusDiv.style.display = 'block';

            setTimeout(() => {
                statusDiv.style.display = 'none';
            }, 3000);
        }
        console.log(`SpanManager: ${type.toUpperCase()} - ${message}`);
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
     * Get current annotations
     */
    getAnnotations() {
        return this.annotations;
    }

    /**
     * Get spans in a format suitable for testing and API consistency
     */
    getSpans() {
        if (!this.annotations || !this.annotations.spans) {
            return [];
        }
        return this.annotations.spans;
    }

    /**
     * Clear all annotations (for testing)
     */
    clearAnnotations() {
        this.annotations = {spans: []};
        this.renderSpans();
    }

    /**
     * Get the background color for a given label
     */
    getSpanColor(label) {
        // The colors structure is nested: {schema: {label: color}}
        // We need to search through all schemas to find the label
        if (this.colors) {
            for (const schema in this.colors) {
                if (this.colors[schema] && this.colors[schema][label]) {
                    const color = this.colors[schema][label];
                    // Add 40% opacity (66 in hex) to match backend rendering
                    return color + '66';
                }
            }
        }
        // Fallback color if label not found in colors
        return '#f0f0f066'; // A neutral gray with 40% opacity
    }

    /**
     * Calculate overlap depths and adjust span positioning for better visibility
     */
    calculateOverlapDepths(spans) {
        if (!spans || spans.length === 0) return [];

        // Sort spans by start position
        const sortedSpans = [...spans].sort((a, b) => a.start - b.start);
        const overlapMap = new Map();

        // Calculate overlaps
        for (let i = 0; i < sortedSpans.length; i++) {
            const currentSpan = sortedSpans[i];
            const currentKey = `${currentSpan.start}-${currentSpan.end}`;

            if (!overlapMap.has(currentKey)) {
                overlapMap.set(currentKey, {
                    span: currentSpan,
                    overlaps: [],
                    depth: 0
                });
            }

            // Check for overlaps with other spans
            for (let j = i + 1; j < sortedSpans.length; j++) {
                const otherSpan = sortedSpans[j];

                // Check if spans overlap
                if (this.spansOverlap(currentSpan, otherSpan)) {
                    const otherKey = `${otherSpan.start}-${otherSpan.end}`;

                    // Add to current span's overlaps
                    overlapMap.get(currentKey).overlaps.push(otherSpan);

                    // Add to other span's overlaps
                    if (!overlapMap.has(otherKey)) {
                        overlapMap.set(otherKey, {
                            span: otherSpan,
                            overlaps: [],
                            depth: 0
                        });
                    }
                    overlapMap.get(otherKey).overlaps.push(currentSpan);
                }
            }
        }

        // Calculate depths using a simpler approach to avoid recursion issues
        let changed = true;
        let maxIterations = 100; // Prevent infinite loops
        let iteration = 0;

        while (changed && iteration < maxIterations) {
            changed = false;
            iteration++;

            for (const [spanKey, spanData] of overlapMap) {
                let maxOverlapDepth = 0;

                // Find the maximum depth of overlapping spans
                for (const overlappingSpan of spanData.overlaps) {
                    const overlappingKey = `${overlappingSpan.start}-${overlappingSpan.end}`;
                    const overlappingData = overlapMap.get(overlappingKey);
                    if (overlappingData) {
                        maxOverlapDepth = Math.max(maxOverlapDepth, overlappingData.depth);
                    }
                }

                // Set this span's depth to one more than the maximum overlap depth
                const newDepth = maxOverlapDepth + 1;
                if (newDepth !== spanData.depth) {
                    spanData.depth = newDepth;
                    changed = true;
                }
            }
        }

        if (iteration >= maxIterations) {
            console.warn('SpanManager: Max iterations reached in overlap depth calculation');
        }

        const result = Array.from(overlapMap.values());
        return result;
    }

    /**
     * Check if two spans overlap
     */
    spansOverlap(span1, span2) {
        return span1.start < span2.end && span2.start < span1.end;
    }

    /**
     * Apply overlap-based styling to span elements
     */
    applyOverlapStyling(spanElements, overlapData) {
        // Only apply overlap styling if there are actual overlaps
        const spansWithOverlaps = overlapData.filter(d => d.overlaps.length > 0);

        if (spansWithOverlaps.length === 0) {
            // Remove all overlap styling from all spans
            spanElements.forEach(spanElement => {
                spanElement.classList.remove('span-overlap');
                spanElement.classList.forEach(className => {
                    if (className.startsWith('overlap-depth-')) {
                        spanElement.classList.remove(className);
                    }
                });
                spanElement.style.removeProperty('--overlap-height');
                spanElement.style.removeProperty('--overlap-offset');
                spanElement.style.removeProperty('--overlap-depth');
                spanElement.style.removeProperty('--max-depth');
                spanElement.style.removeProperty('z-index');
            });
            return;
        }

        const maxDepth = Math.max(...overlapData.map(d => d.depth), 0);

        spanElements.forEach(spanElement => {
            const start = parseInt(spanElement.dataset.start);
            const end = parseInt(spanElement.dataset.end);
            const spanKey = `${start}-${end}`;

            const data = overlapData.find(d =>
                d.span.start === start && d.span.end === end
            );

            // Only apply overlap styling if the span actually has overlaps
            if (data && data.overlaps.length > 0) {
                // Invert the depth so outermost is at base, innermost is on top
                const layer = maxDepth - data.depth + 1;
                const baseHeight = 1.2; // Base line height
                const heightIncrement = 0.3; // Additional height per layer
                const offsetIncrement = 0.2; // Vertical offset per layer

                const height = baseHeight + (layer * heightIncrement);
                const offset = (layer - 1) * offsetIncrement;

                // Apply CSS custom properties for dynamic styling
                spanElement.style.setProperty('--overlap-height', `${height}em`);
                spanElement.style.setProperty('--overlap-offset', `${offset}em`);
                spanElement.style.setProperty('--overlap-depth', layer);
                spanElement.style.setProperty('--max-depth', maxDepth);

                // Add overlap class for CSS targeting
                spanElement.classList.add('span-overlap');
                spanElement.classList.add(`overlap-depth-${layer}`);

                // Add z-index to ensure proper layering (innermost on top)
                spanElement.style.zIndex = layer;
            } else {
                // Remove any existing overlap styling for non-overlapping spans
                spanElement.classList.remove('span-overlap');
                spanElement.classList.forEach(className => {
                    if (className.startsWith('overlap-depth-')) {
                        spanElement.classList.remove(className);
                    }
                });
                spanElement.style.removeProperty('--overlap-height');
                spanElement.style.removeProperty('--overlap-offset');
                spanElement.style.removeProperty('--overlap-depth');
                spanElement.style.removeProperty('--max-depth');
                spanElement.style.removeProperty('z-index');
            }
        });
    }
}

// Initialize global span manager
window.spanManager = new SpanManager();
document.addEventListener('DOMContentLoaded', () => {
    window.spanManager.initialize();
});
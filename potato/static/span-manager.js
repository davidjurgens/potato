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

    renderSpans() {
        console.log('SpanManager: renderSpans() called');
        const textContainer = document.getElementById('instance-text');
        if (!textContainer) {
            console.warn('SpanManager: Text container not found');
            return;
        }

        // Use the original text from the global instance if available
        let text = '';
        if (window.currentInstance && window.currentInstance.text) {
            text = window.currentInstance.text;
        } else {
            text = textContainer.textContent;
        }

        const spans = this.getSpans();
        console.log('SpanManager: renderSpans - text length:', text.length);
        console.log('SpanManager: renderSpans - spans:', spans);
        console.log('SpanManager: renderSpans - spans.length:', spans.length);

        // Clear existing content
        textContainer.innerHTML = '';

        if (spans.length === 0) {
            textContainer.textContent = text;
            console.log('SpanManager: No spans to render, restored original text');
            return;
        }

        // Build boundary points
        const boundaries = [];
        spans.forEach(span => {
            boundaries.push({ pos: span.start, type: 'start', span });
            boundaries.push({ pos: span.end, type: 'end', span });
        });
        // Sort: by position, then 'end' before 'start' at same pos
        boundaries.sort((a, b) => a.pos - b.pos || (a.type === 'end' ? -1 : 1));

        let currentPos = 0;
        let openSpans = [];
        const fragmentStack = [document.createDocumentFragment()];

        for (let i = 0; i < boundaries.length; i++) {
            const boundary = boundaries[i];
            // Add text up to this boundary
            if (boundary.pos > currentPos) {
                const textNode = document.createTextNode(text.substring(currentPos, boundary.pos));
                fragmentStack[fragmentStack.length - 1].appendChild(textNode);
                currentPos = boundary.pos;
            }
            if (boundary.type === 'start') {
                // Open a new span
                const spanElement = document.createElement('span');
                spanElement.className = 'annotation-span';
                spanElement.dataset.spanId = boundary.span.id;
                spanElement.dataset.start = boundary.span.start;
                spanElement.dataset.end = boundary.span.end;
                spanElement.dataset.label = boundary.span.label;

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
        console.log('SpanManager: Rendered', spans.length, 'spans');
        console.log('SpanManager: Final DOM has', textContainer.querySelectorAll('.annotation-span').length, 'span elements');
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
}

// Initialize global span manager
window.spanManager = new SpanManager();
document.addEventListener('DOMContentLoaded', () => {
    window.spanManager.initialize();
});
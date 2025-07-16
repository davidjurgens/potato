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
        this.currentSchema = null; // Track the current schema
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
        const textContent = document.getElementById('text-content');
        if (textContainer) {
            textContainer.addEventListener('mouseup', () => this.handleTextSelection());
            textContainer.addEventListener('keyup', () => this.handleTextSelection());
        }
        if (textContent) {
            textContent.addEventListener('mouseup', () => this.handleTextSelection());
            textContent.addEventListener('keyup', () => this.handleTextSelection());
        }

        // DEBUG: Global mouseup event listener
        document.addEventListener('mouseup', (e) => {
            console.log('DEBUG: Global mouseup event fired on', e.target ? e.target.id : '(no id)', 'class:', e.target ? e.target.className : '(no class)');
        });

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
    selectLabel(label, schema = null) {
        // Update UI
        document.querySelectorAll('.label-button').forEach(btn => {
            btn.classList.remove('active');
        });
        const button = document.querySelector(`[data-label="${label}"]`);
        if (button) {
            button.classList.add('active');
        }

        this.selectedLabel = label;
        if (schema) {
            this.currentSchema = schema;
        }
        console.log('SpanManager: Selected label:', label, 'schema:', this.currentSchema);
    }

    /**
     * Load annotations for current instance
     */
    async loadAnnotations(instanceId) {
        if (!instanceId) return Promise.resolve();

        try {
            console.log('SpanManager: Loading annotations for instance:', instanceId);

            // DEBUG: Track overlays before loading annotations
            const spanOverlays = document.getElementById('span-overlays');
            const overlaysBeforeLoad = spanOverlays ? spanOverlays.children.length : 0;
            console.log(`🔍 [DEBUG] SpanManager.loadAnnotations() - Before loading: ${overlaysBeforeLoad} overlays for instance ${instanceId}`);

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

            // Auto-set the schema from the first span if available
            if (this.annotations.spans && this.annotations.spans.length > 0) {
                const firstSpan = this.annotations.spans[0];
                if (firstSpan.schema && !this.currentSchema) {
                    this.currentSchema = firstSpan.schema;
                    console.log('SpanManager: Auto-set schema from loaded spans:', this.currentSchema);
                }
            }

            console.log('SpanManager: Loaded annotations:', this.annotations);
            console.log('SpanManager: this.annotations.spans:', this.annotations.spans);
            console.log('SpanManager: getSpans() would return:', this.getSpans());
            console.log('SpanManager: Current schema:', this.currentSchema);

            // Render spans
            console.log('SpanManager: About to call renderSpans()');
            this.renderSpans();
            console.log('SpanManager: renderSpans() call completed');

            // DEBUG: Track overlays after loading annotations
            const overlaysAfterLoad = spanOverlays ? spanOverlays.children.length : 0;
            console.log(`🔍 [DEBUG] SpanManager.loadAnnotations() - After loading: ${overlaysAfterLoad} overlays for instance ${instanceId}`);

            return Promise.resolve(this.annotations);
        } catch (error) {
            console.error('SpanManager: Error loading annotations:', error);
            this.annotations = {spans: []};
            this.renderSpans();
            return Promise.reject(error);
        }
    }

    /**
     * Render all spans in the text container using interval-based approach
     * This method properly handles partial overlaps by using position-based rendering
     */
    renderSpans() {
        console.log('🔍 [DEBUG] SpanManager.renderSpans() called');

        // Wait for DOM elements to be available
        const waitForElements = () => {
            const textContainer = document.getElementById('instance-text');
            const textContent = document.getElementById('text-content');
            const spanOverlays = document.getElementById('span-overlays');

            if (!textContent) {
                console.log('SpanManager: Waiting for #text-content element to be available...');
                setTimeout(waitForElements, 100);
                return;
            }
            if (!textContainer || !spanOverlays) {
                console.warn('SpanManager: Required containers not found');
                return;
            }

            // DEBUG: Track overlays before rendering
            const overlayCount = spanOverlays.children.length;
            console.log(`🔍 [DEBUG] SpanManager.renderSpans() - Before rendering: ${overlayCount} overlays present`);

            // Elements are available, proceed with rendering
            this._renderSpansInternal(textContainer, textContent, spanOverlays);
        };

        waitForElements();
    }

    /**
     * Internal method to render spans once DOM elements are confirmed available
     */
    _renderSpansInternal(textContainer, textContent, spanOverlays) {
        if (!textContent) {
            console.error('SpanManager: #text-content element not found! The annotation text will not be selectable.');
            this.showStatus('Error: Annotation text not found. Please contact support.', 'error');
            return;
        }
        if (!textContainer || !spanOverlays) {
            console.warn('SpanManager: Required containers not found');
            return;
        }

        // Get spans from the correct property
        const spans = this.getSpans();
        console.log('SpanManager: Starting interval-based renderSpans with', spans?.length || 0, 'spans');

        // DEBUG: Track overlays before clearing
        const overlaysBeforeClear = spanOverlays.children.length;
        console.log(`🔍 [DEBUG] SpanManager._renderSpansInternal() - Before clearing overlays: ${overlaysBeforeClear} overlays`);

        // Clear existing overlays
        spanOverlays.innerHTML = '';

        // DEBUG: Track overlays after clearing
        const overlaysAfterClear = spanOverlays.children.length;
        console.log(`🔍 [DEBUG] SpanManager._renderSpansInternal() - After clearing overlays: ${overlaysAfterClear} overlays`);

        if (!spans || spans.length === 0) {
            // Just display the original text in text content layer
            const originalText = window.currentInstance?.text || '';
            textContent.textContent = originalText;
            console.log('SpanManager: No spans to render, displaying original text:', originalText);
            return;
        }

        // Get the original text
        const text = window.currentInstance?.text || '';
        console.log('SpanManager: Original text length:', text.length);

        // Display text in text content layer
        textContent.textContent = text;

        // Sort spans by start position for consistent rendering
        const sortedSpans = [...spans].sort((a, b) => a.start - b.start);

        // Calculate overlap layers for visual styling
        const overlapDataArray = this.calculateOverlapDepths(sortedSpans);
        console.log('SpanManager: Overlap data:', overlapDataArray);

        // Convert overlap data array to a Map for efficient lookup
        const overlapDataMap = new Map();
        overlapDataArray.forEach(data => {
            const spanKey = `${data.span.start}-${data.span.end}`;
            overlapDataMap.set(spanKey, {
                depth: data.depth,
                heightMultiplier: data.heightMultiplier
            });
        });

        // Render each span as an overlay
        sortedSpans.forEach((span, index) => {
            this.renderSpanOverlay(span, index, textContent, spanOverlays, overlapDataMap);
        });

        // Apply overlap styling
        const spanElements = spanOverlays.querySelectorAll('.span-highlight');
        this.applyOverlapStyling(spanElements, overlapDataArray);

        // DEBUG: Track overlays after rendering
        const overlaysAfterRender = spanOverlays.children.length;
        console.log(`🔍 [DEBUG] SpanManager._renderSpansInternal() - After rendering: ${overlaysAfterRender} overlays created`);
        console.log('SpanManager: Interval-based rendering completed');
    }

    /**
     * Create a span element with proper styling and event handlers
     */
    createSpanElement(span) {
        const spanElement = document.createElement('span');
        spanElement.className = 'annotation-span';
        spanElement.dataset.spanId = span.id;
        spanElement.dataset.start = span.start;
        spanElement.dataset.end = span.end;
        spanElement.dataset.label = span.label;

        // Apply the correct color for this label
        const backgroundColor = this.getSpanColor(span.label);
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
            this.deleteSpan(span.id);
        };
        spanElement.appendChild(deleteBtn);

        // Add label display
        const labelSpan = document.createElement('span');
        labelSpan.className = 'span-label';
        labelSpan.textContent = span.label;
        spanElement.appendChild(labelSpan);

        return spanElement;
    }

    /**
     * Render a span as an overlay using interval-based positioning
     */
    renderSpanOverlay(span, layerIndex, textContent, spanOverlays, overlapData) {
        // Defensive check: ensure text node exists
        const textNode = textContent.firstChild;
        if (!textNode || textNode.nodeType !== Node.TEXT_NODE) {
            console.error('SpanManager: No text node found in #text-content when rendering span overlay', {
                span: span,
                textContentChildNodes: textContent.childNodes.length,
                firstChildType: textNode ? textNode.nodeType : 'null'
            });
            return; // Skip rendering this span
        }

        // Get bounding rects for the span's character range
        const rects = getCharRangeBoundingRect(textContent, span.start, span.end);
        if (!rects || rects.length === 0) {
            console.warn('SpanManager: Could not get bounding rect for span', span);
            return;
        }

        // Get the instance-text container's bounding rect for relative positioning
        const instanceTextContainer = document.getElementById('instance-text');
        const containerRect = instanceTextContainer.getBoundingClientRect();

        // Create overlay for each rect (handles line wrapping)
        rects.forEach((rect, rectIndex) => {
            const overlay = document.createElement('div');
            overlay.className = 'span-overlay annotation-span';
            overlay.dataset.annotationId = span.id;
            overlay.dataset.start = span.start;
            overlay.dataset.end = span.end;
            overlay.dataset.label = span.label;
            overlay.style.position = 'absolute';
            overlay.style.pointerEvents = 'none'; // <-- Always allow selection through overlay

            // Position the overlay relative to the instance-text container
            const left = rect.left - containerRect.left;
            const top = rect.top - containerRect.top;
            const width = rect.right - rect.left;
            const height = rect.bottom - rect.top;

            overlay.style.left = `${left}px`;
            overlay.style.top = `${top}px`;
            overlay.style.width = `${width}px`;
            overlay.style.height = `${height}px`;
            // overlay.style.pointerEvents = 'auto'; // Enable pointer events for this overlay

            // Apply the correct color for this label
            const backgroundColor = this.getSpanColor(span.label);
            if (backgroundColor) {
                overlay.style.backgroundColor = backgroundColor;
            }

            // Set z-index and height based on overlap data
            const spanKey = `${span.start}-${span.end}`;
            const overlapInfo = overlapData.get(spanKey) || { depth: 0, heightMultiplier: 1.0 };
            overlay.style.zIndex = 10 + overlapInfo.depth;

            // Apply height multiplier for visual distinction
            if (overlapInfo.heightMultiplier > 1.0) {
                const originalHeight = rect.bottom - rect.top;
                const adjustedHeight = originalHeight * overlapInfo.heightMultiplier;
                overlay.style.height = `${adjustedHeight}px`;

                // Center the overlay vertically around the original text position
                const heightDifference = adjustedHeight - originalHeight;
                const newTop = top - (heightDifference / 2);
                overlay.style.top = `${newTop}px`;
            }

            // Add label
            const label = document.createElement('span');
            label.className = 'span-label';
            label.textContent = span.label;
            label.style.position = 'absolute';
            label.style.top = '-25px';
            label.style.left = '0';
            label.style.fontSize = '11px';
            label.style.fontWeight = 'bold';
            label.style.backgroundColor = 'rgba(0,0,0,0.9)';
            label.style.color = 'white';
            label.style.padding = '3px 6px';
            label.style.borderRadius = '4px';
            label.style.pointerEvents = 'auto'; // <-- Allow interaction with label
            label.style.zIndex = '1000';
            label.style.whiteSpace = 'nowrap';
            overlay.appendChild(label);

            // Add delete button
            const deleteBtn = document.createElement('button');
            deleteBtn.className = 'span-delete-btn';
            deleteBtn.innerHTML = '×';
            deleteBtn.title = 'Delete span';
            deleteBtn.style.position = 'absolute';
            deleteBtn.style.top = '-25px';
            deleteBtn.style.right = '0';
            deleteBtn.style.backgroundColor = 'rgba(255,0,0,0.9)';
            deleteBtn.style.color = 'white';
            deleteBtn.style.border = 'none';
            deleteBtn.style.borderRadius = '50%';
            deleteBtn.style.width = '18px';
            deleteBtn.style.height = '18px';
            deleteBtn.style.fontSize = '14px';
            deleteBtn.style.fontWeight = 'bold';
            deleteBtn.style.cursor = 'pointer';
            deleteBtn.style.pointerEvents = 'auto'; // <-- Allow interaction with delete button
            deleteBtn.style.zIndex = '1001';
            deleteBtn.style.lineHeight = '1';
            deleteBtn.onclick = (e) => {
                e.stopPropagation();
                this.deleteSpan(span.id);
            };
            overlay.appendChild(deleteBtn);

            spanOverlays.appendChild(overlay);
        });
    }

    /**
     * Create an overlay span for overlapping annotations (legacy method - kept for compatibility)
     */
    createOverlaySpan(span, layerIndex) {
        const overlaySpan = document.createElement('span');
        overlaySpan.className = 'annotation-span overlay-span';
        overlaySpan.dataset.spanId = span.id;
        overlaySpan.dataset.start = span.start;
        overlaySpan.dataset.end = span.end;
        overlaySpan.dataset.label = span.label;

        // Apply the correct color for this label
        const backgroundColor = this.getSpanColor(span.label);
        if (backgroundColor) {
            overlaySpan.style.backgroundColor = backgroundColor;
        }

        // Position the overlay span
        overlaySpan.style.position = 'absolute';
        overlaySpan.style.top = '0';
        overlaySpan.style.left = '0';
        overlaySpan.style.right = '0';
        overlaySpan.style.bottom = '0';
        overlaySpan.style.zIndex = layerIndex + 1;
        // CSS will handle pointer events for overlay spans

        // Add delete button (positioned absolutely)
        const deleteBtn = document.createElement('button');
        deleteBtn.className = 'span-delete-btn overlay-delete-btn';
        deleteBtn.innerHTML = '×';
        deleteBtn.title = 'Delete span';
        deleteBtn.style.position = 'absolute';
        deleteBtn.style.top = '-20px';
        deleteBtn.style.right = '0';
        deleteBtn.style.zIndex = layerIndex + 2;
        deleteBtn.style.pointerEvents = 'auto'; // Allow clicks on delete button
        deleteBtn.onclick = (e) => {
            e.stopPropagation();
            this.deleteSpan(span.id);
        };
        overlaySpan.appendChild(deleteBtn);

        // Add label display (always visible for overlay spans)
        const labelSpan = document.createElement('span');
        labelSpan.className = 'span-label overlay-label';
        labelSpan.textContent = span.label;
        // Make label always visible for overlay spans
        labelSpan.style.position = 'absolute';
        labelSpan.style.top = '-25px';
        labelSpan.style.left = '0';
        labelSpan.style.zIndex = layerIndex + 2;
        labelSpan.style.display = 'block'; // Always show for overlay spans
        labelSpan.style.pointerEvents = 'auto';
        overlaySpan.appendChild(labelSpan);

        return overlaySpan;
    }

    /**
     * Handle text selection and create annotation
     */
    handleTextSelection() {
        const selection = window.getSelection();
        console.log('🔍 [DEBUG] handleTextSelection entered, selection:', selection ? selection.toString() : '(none)', 'rangeCount:', selection ? selection.rangeCount : '(none)', 'isCollapsed:', selection ? selection.isCollapsed : '(none)');
        if (!selection.rangeCount || selection.isCollapsed) return;

        if (!this.selectedLabel) {
            this.showStatus('Please select a label first', 'error');
            return;
        }

        const range = selection.getRangeAt(0);
        const textContent = document.getElementById('text-content');
        const selectedText = selection.toString().trim();

        if (!selectedText) return;

        // With interval-based rendering, text selection is much simpler
        // The text content layer only contains the original text, no spans
        const start = this.getTextPosition(textContent, range.startContainer, range.startOffset);
        const end = this.getTextPosition(textContent, range.endContainer, range.endOffset);

        console.log('🔍 [DEBUG] SpanManager: Creating annotation:', {
            text: selectedText,
            start: start,
            end: end,
            label: this.selectedLabel
        });

        // Validate the selection
        if (start >= end) {
            console.warn('SpanManager: Invalid selection range (start >= end)');
            this.showStatus('Invalid selection range', 'error');
            selection.removeAllRanges();
            return;
        }

        // Create annotation
        this.createAnnotation(selectedText, start, end, this.selectedLabel)
            .then(result => {
                console.log('🔍 [DEBUG] SpanManager: Annotation creation successful:', result);
            })
            .catch(error => {
                console.error('🔍 [DEBUG] SpanManager: Annotation creation failed:', error);
            });

        // Clear selection
        selection.removeAllRanges();
    }

    /**
     * Get the character position within a text node
     * This is used for converting DOM positions to character offsets
     */
    getTextPosition(container, node, offset) {
        if (!container || !node) {
            console.error('SpanManager: getTextPosition called with null container or node');
            return null;
        }

        // Ensure we're working with the correct container
        if (node.parentElement !== container) {
            console.error('SpanManager: Node parent does not match container', {
                nodeParent: node.parentElement?.id || 'null',
                containerId: container.id || 'null'
            });
            return null;
        }

        // Ensure we have a text node
        if (node.nodeType !== Node.TEXT_NODE) {
            console.error('SpanManager: Node is not a text node', {
                nodeType: node.nodeType,
                nodeName: node.nodeName
            });
            return null;
        }

        // Validate offset
        if (offset < 0 || offset > node.textContent.length) {
            console.error('SpanManager: Invalid offset', {
                offset: offset,
                textLength: node.textContent.length
            });
            return null;
        }

        return offset;
    }

    /**
     * Calculate position in original text from DOM position (legacy method - kept for compatibility)
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
            console.warn('SpanManager: Target node not found in DOM walk, attempting fallback');

            // Fallback: try to find the node by traversing the DOM tree
            const allTextNodes = [];
            const fallbackWalker = document.createTreeWalker(
                container,
                NodeFilter.SHOW_TEXT,
                null,
                false
            );

            let fallbackNode;
            while (fallbackNode = fallbackWalker.nextNode()) {
                const parent = fallbackNode.parentElement;
                if (parent && (
                    parent.classList.contains('span-delete-btn') ||
                    parent.classList.contains('span-label') ||
                    parent.closest('.span-delete-btn') ||
                    parent.closest('.span-label')
                )) {
                    continue;
                }
                allTextNodes.push(fallbackNode);
            }

            // Try to find the node in our collected text nodes
            const nodeIndex = allTextNodes.indexOf(node);
            if (nodeIndex !== -1) {
                // Calculate position based on previous text nodes
                for (let i = 0; i < nodeIndex; i++) {
                    textSoFar += allTextNodes[i].textContent;
                }
                textSoFar += node.textContent.substring(0, offset);
                foundNode = true;
            }
        }

        if (!foundNode) {
            console.warn('SpanManager: Target node not found in DOM walk, using fallback position');
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

        if (!this.currentSchema) {
            this.showStatus('No schema selected', 'error');
            return Promise.reject(new Error('No schema selected'));
        }

        try {
            // Get existing spans to include in the request
            const existingSpans = this.getSpans();
            console.log('SpanManager: Existing spans before creating new one:', existingSpans);

            // Create the new span
            const newSpan = {
                name: label,
                start: start,
                end: end,
                title: label,
                value: spanText
            };

            // Combine existing spans with the new span
            const allSpans = [...existingSpans.map(span => ({
                name: span.label,
                start: span.start,
                end: span.end,
                title: span.label,
                value: span.text || span.value
            })), newSpan];

            console.log('SpanManager: Sending POST to /updateinstance with all spans:', allSpans);
            const response = await fetch('/updateinstance', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    type: 'span',
                    schema: this.currentSchema, // Use tracked schema
                    state: allSpans,
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
        console.log(`🔍 [DEBUG] SpanManager.deleteSpan() called for annotationId: ${annotationId}`);

        if (!this.currentInstanceId) {
            this.showStatus('No instance loaded', 'error');
            return;
        }

        if (!this.currentSchema) {
            this.showStatus('No schema selected', 'error');
            return;
        }

        try {
            // DEBUG: Track overlays before deletion
            const spanOverlays = document.getElementById('span-overlays');
            const overlaysBeforeDelete = spanOverlays ? spanOverlays.children.length : 0;
            console.log(`🔍 [DEBUG] SpanManager.deleteSpan() - Before deletion: ${overlaysBeforeDelete} overlays`);

            // Find the span to delete from current annotations
            const spanToDelete = this.annotations.spans.find(span => span.id === annotationId);
            if (!spanToDelete) {
                this.showStatus('Span not found', 'error');
                return;
            }

            console.log('SpanManager: Deleting span:', spanToDelete);

            // Send deletion request with value: null to indicate deletion
            const response = await fetch('/updateinstance', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    type: 'span',
                    schema: this.currentSchema,
                    state: [
                        {
                            name: spanToDelete.label,
                            start: spanToDelete.start,
                            end: spanToDelete.end,
                            title: spanToDelete.label,
                            value: null  // This signals deletion
                        }
                    ],
                    instance_id: this.currentInstanceId
                })
            });

            if (response.ok) {
                console.log('🔍 [DEBUG] SpanManager.deleteSpan() - Backend deletion successful, reloading annotations');
                // Reload all annotations to ensure consistency
                await this.loadAnnotations(this.currentInstanceId);
                this.showStatus('Annotation deleted', 'success');
                console.log('SpanManager: Annotation deleted:', annotationId);

                // DEBUG: Track overlays after deletion and reload
                const overlaysAfterDelete = spanOverlays ? spanOverlays.children.length : 0;
                console.log(`🔍 [DEBUG] SpanManager.deleteSpan() - After deletion and reload: ${overlaysAfterDelete} overlays`);

                // --- FIX: If no spans remain, force overlays to be cleared ---
                if (this.getSpans().length === 0 && spanOverlays) {
                    spanOverlays.innerHTML = '';
                    console.log('🔍 [FIX] No spans remain after deletion, overlays forcibly cleared.');
                }
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

        // Calculate overlaps and containment relationships
        for (let i = 0; i < sortedSpans.length; i++) {
            const currentSpan = sortedSpans[i];
            const currentKey = `${currentSpan.start}-${currentSpan.end}`;

            if (!overlapMap.has(currentKey)) {
                overlapMap.set(currentKey, {
                    span: currentSpan,
                    overlaps: [],
                    containedBy: [],
                    contains: [],
                    depth: 0,
                    heightMultiplier: 1.0
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
                            containedBy: [],
                            contains: [],
                            depth: 0,
                            heightMultiplier: 1.0
                        });
                    }
                    overlapMap.get(otherKey).overlaps.push(currentSpan);

                    // Check for containment relationships
                    if (this.spansContain(currentSpan, otherSpan)) {
                        // currentSpan completely contains otherSpan
                        overlapMap.get(currentKey).contains.push(otherSpan);
                        overlapMap.get(otherKey).containedBy.push(currentSpan);
                    } else if (this.spansContain(otherSpan, currentSpan)) {
                        // otherSpan completely contains currentSpan
                        overlapMap.get(otherKey).contains.push(currentSpan);
                        overlapMap.get(currentKey).containedBy.push(currentSpan);
                    }
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

        // Calculate height multipliers for visual distinction
        this.calculateHeightMultipliers(overlapMap);

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
     * Check if span1 completely contains span2
     */
    spansContain(span1, span2) {
        return span1.start <= span2.start && span1.end >= span2.end;
    }

    /**
     * Calculate height multipliers for overlays based on overlap relationships
     */
    calculateHeightMultipliers(overlapMap) {
        // Base height for all overlays
        const baseHeight = 1.0;
        const heightIncrement = 0.3; // Additional height per level
        const maxHeightMultiplier = 3.0; // Cap the maximum height

        // First pass: calculate height for containing spans
        for (const [spanKey, spanData] of overlapMap) {
            if (spanData.contains.length > 0) {
                // This span contains other spans - make it taller
                const containmentLevel = this.getContainmentLevel(spanData, overlapMap);
                spanData.heightMultiplier = Math.min(
                    baseHeight + (containmentLevel * heightIncrement),
                    maxHeightMultiplier
                );
            }
        }

        // Second pass: adjust heights for partially overlapping spans
        for (const [spanKey, spanData] of overlapMap) {
            if (spanData.overlaps.length > 0 && spanData.contains.length === 0) {
                // This span overlaps but doesn't contain others - make it slightly taller
                const overlapLevel = this.getOverlapLevel(spanData, overlapMap);
                const currentHeight = spanData.heightMultiplier;
                const newHeight = Math.min(
                    currentHeight + (overlapLevel * heightIncrement * 0.5),
                    maxHeightMultiplier
                );
                spanData.heightMultiplier = newHeight;
            }
        }
    }

    /**
     * Get the containment level (how many levels of containment this span has)
     */
    getContainmentLevel(spanData, overlapMap) {
        let maxLevel = 0;
        const visited = new Set();

        const traverseContainment = (span, level) => {
            if (visited.has(`${span.start}-${span.end}`)) return;
            visited.add(`${span.start}-${span.end}`);

            maxLevel = Math.max(maxLevel, level);

            for (const containedSpan of spanData.contains) {
                const containedKey = `${containedSpan.start}-${containedSpan.end}`;
                const containedData = overlapMap.get(containedKey);
                if (containedData && containedData.contains.length > 0) {
                    traverseContainment(containedSpan, level + 1);
                }
            }
        };

        traverseContainment(spanData.span, 1);
        return maxLevel;
    }

    /**
     * Get the overlap level (how many spans this overlaps with)
     */
    getOverlapLevel(spanData, overlapMap) {
        return spanData.overlaps.length;
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

/**
 * Utility: Get bounding rect(s) for character range in a container
 * Returns an array of DOMRects (one per line if the range wraps)
 */
function getCharRangeBoundingRect(container, start, end) {
    const textNode = container.firstChild;
    if (!textNode || textNode.nodeType !== Node.TEXT_NODE) return null;

    const range = document.createRange();
    range.setStart(textNode, start);
    range.setEnd(textNode, end);

    const rects = range.getClientRects();
    if (rects.length === 0) return null;

    // If the range wraps lines, return all rects
    return Array.from(rects);
}

// CommonJS export for Jest
if (typeof module !== 'undefined' && module.exports) {
    module.exports.getCharRangeBoundingRect = getCharRangeBoundingRect;
}

// Initialize global span manager
window.spanManager = new SpanManager();
document.addEventListener('DOMContentLoaded', () => {
    window.spanManager.initialize();
});
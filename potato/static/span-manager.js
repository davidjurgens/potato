// =====================================================================================
// Potato Annotation Platform - Span Manager
// -------------------------------------------------------------------------------------
// This file manages all frontend span annotation logic, including:
//   - Rendering and clearing span overlays
//   - Handling navigation between annotation instances
//   - Synchronizing frontend state with backend API
//   - Defensive logic for browser quirks (esp. Firefox)
//   - Debugging and diagnostics hooks
//
// Key Features:
//   - Robust overlay management with Firefox-specific fixes
//   - Instance ID synchronization with server
//   - Comprehensive debug logging for troubleshooting
//   - Defensive state clearing on navigation
// =====================================================================================

/**
 * Frontend Span Manager for Potato Annotation Platform
 * Handles span annotation rendering, interaction, and API communication
 */

class SpanManager {
    constructor() {
        console.log('[DEEPDEBUG] SpanManager constructor called');

        // Core state
        this.annotations = {spans: []};
        this.colors = {};
        this.selectedLabel = null;
        this.currentSchema = null; // Track the current schema
        this.isInitialized = false;
        this.currentInstanceId = null;
        this.lastKnownInstanceId = null;

        // Debug tracking
        this.debugState = {
            constructorCalls: 0,
            initializeCalls: 0,
            loadAnnotationsCalls: 0,
            onInstanceChangeCalls: 0,
            clearAllStateCalls: 0,
            renderSpansCalls: 0,
            lastInstanceIdFromServer: null,
            lastInstanceIdFromDOM: null,
            lastOverlayCount: 0,
            stateTransitions: []
        };

        this.debugState.constructorCalls++;
        this.debugState.stateTransitions.push({
            timestamp: new Date().toISOString(),
            action: 'constructor',
            currentInstanceId: this.currentInstanceId,
            lastKnownInstanceId: this.lastKnownInstanceId
        });

        // Retry logic for robustness
        this.retryCount = 0;
        this.maxRetries = 3;

        // Aggressive state clearing on construction
        this.clearAllStateAndOverlays();

        console.log('[DEEPDEBUG] SpanManager constructor completed', {
            debugState: this.debugState,
            currentInstanceId: this.currentInstanceId,
            isInitialized: this.isInitialized
        });
    }

    /**
     * Deep debug logging utility
     */
    logDebugState(action, extraData = {}) {
        const state = {
            timestamp: new Date().toISOString(),
            action: action,
            currentInstanceId: this.currentInstanceId,
            lastKnownInstanceId: this.lastKnownInstanceId,
            isInitialized: this.isInitialized,
            annotationsCount: this.annotations?.spans?.length || 0,
            debugState: { ...this.debugState },
            ...extraData
        };

        console.log(`[DEEP DEBUG] ${action}:`, state);
        this.debugState.stateTransitions.push(state);

        // Keep only last 50 transitions to avoid memory bloat
        if (this.debugState.stateTransitions.length > 50) {
            this.debugState.stateTransitions = this.debugState.stateTransitions.slice(-50);
        }
    }

    /**
     * Alternative workflow: Fetch current instance ID from server before any operations
     * This ensures we always have the correct instance ID, even if DOM is stale
     */
    async fetchCurrentInstanceIdFromServer() {
        try {
            console.log('[DEEP DEBUG] fetchCurrentInstanceIdFromServer called');

            const response = await fetch('/api/current_instance');
            if (!response.ok) {
                throw new Error(`Failed to fetch current instance: ${response.status}`);
            }

            const data = await response.json();
            const serverInstanceId = data.instance_id;

            console.log('[DEEP DEBUG] Server returned instance ID:', serverInstanceId);

            // Update debug state
            this.debugState.lastInstanceIdFromServer = serverInstanceId;

            // Check if this is different from what we have
            if (this.currentInstanceId !== serverInstanceId) {
                console.log('[DEEP DEBUG] Instance ID mismatch detected!', {
                    currentInstanceId: this.currentInstanceId,
                    serverInstanceId: serverInstanceId,
                    lastKnownInstanceId: this.lastKnownInstanceId
                });

                // Force state reset if instance ID changed
                if (this.currentInstanceId !== null) {
                    console.log('[DEEP DEBUG] Instance ID changed, forcing state reset');
                    this.clearAllStateAndOverlays();
                }
            }

            this.currentInstanceId = serverInstanceId;
            this.lastKnownInstanceId = serverInstanceId;

            this.logDebugState('fetchCurrentInstanceIdFromServer', {
                serverInstanceId: serverInstanceId,
                previousInstanceId: this.currentInstanceId
            });

            return serverInstanceId;
        } catch (error) {
            console.error('[DEEP DEBUG] Error fetching current instance ID:', error);
            return null;
        }
    }

    /**
     * Initialize the span manager
     */
    async initialize() {
        console.log('[DEEP DEBUG] initialize called');
        this.debugState.initializeCalls++;

        try {
            // Step 1: Fetch current instance ID from server first
            const serverInstanceId = await this.fetchCurrentInstanceIdFromServer();
            if (!serverInstanceId) {
                console.error('[DEEP DEBUG] Failed to get server instance ID during initialization');
                return false;
            }

            // Step 2: Load colors
            await this.loadColors();

            // Step 3: Setup event listeners
            this.setupEventListeners();

            // Step 4: Load annotations for the verified instance ID
            await this.loadAnnotations(serverInstanceId);

            this.isInitialized = true;

            this.logDebugState('initialize_completed', {
                serverInstanceId: serverInstanceId,
                isInitialized: this.isInitialized
            });

            console.log('[DEEPDEBUG] SpanManager initialization completed successfully');
            return true;
        } catch (error) {
            console.error('[DEEP DEBUG] SpanManager initialization failed:', error);
            this.isInitialized = false;
            return false;
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
        // Update UI - uncheck all span checkboxes first
        document.querySelectorAll('.annotation-form.span input[type="checkbox"]').forEach(checkbox => {
            checkbox.checked = false;
        });

        // Find and check the checkbox for this label
        const checkbox = document.querySelector(`.annotation-form.span input[type="checkbox"][value="${label}"]`);
        if (checkbox) {
            checkbox.checked = true;
        }

        this.selectedLabel = label;
        if (schema) {
            this.currentSchema = schema;
        }
        console.log('SpanManager: Selected label:', label, 'schema:', this.currentSchema);
    }

    /**
     * Get the currently selected label from checkbox inputs
     */
    getSelectedLabel() {
        // Check if any span checkbox is checked
        const checkedCheckbox = document.querySelector('.annotation-form.span input[type="checkbox"]:checked');
        if (checkedCheckbox) {
            return checkedCheckbox.value;
        }
        return this.selectedLabel;
    }

    /**
     * Load annotations for current instance
     */
    async loadAnnotations(instanceId) {
        console.log('[DEEP DEBUG] loadAnnotations called with instanceId:', instanceId);
        this.debugState.loadAnnotationsCalls++;

        try {
            // Step 1Verify instance ID with server
            const serverInstanceId = await this.fetchCurrentInstanceIdFromServer();
            if (serverInstanceId !== instanceId) {
                console.warn('[DEEP DEBUG] Instance ID mismatch in loadAnnotations!', {
                    requestedInstanceId: instanceId,
                    serverInstanceId: serverInstanceId
                });

                // Use server instance ID instead
                instanceId = serverInstanceId;
            }

            this.logDebugState('loadAnnotations_start', {
                requestedInstanceId: instanceId,
                serverInstanceId: serverInstanceId
            });

            // Step2ear existing state
            this.clearAllStateAndOverlays();

            // Step 3: Fetch annotations from server
            const response = await fetch(`/api/spans/${instanceId}`);
            if (!response.ok) {
                if (response.status === 404) {
                    // No annotations yet
                    this.annotations = {spans: []};
                    console.log('🔍 [DEBUG] SpanManager.loadAnnotations() - No annotations found (404), set to:', this.annotations);
                    this.renderSpans();
                    console.log('🔍 [DEBUG] SpanManager.loadAnnotations() - EXIT POINT (404)');
                    return Promise.resolve();
                }
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            // Store the full API response, not just the spans array
            this.annotations = await response.json();
            console.log('[DEEP DEBUG] Annotations loaded from server:', {
                instanceId: instanceId,
                annotationsCount: this.annotations?.spans?.length || 0,
                annotations: this.annotations
            });

            // Auto-set the schema from the first span if available
            if (this.annotations.spans && this.annotations.spans.length > 0) {
                const firstSpan = this.annotations.spans[0];
                if (firstSpan.schema && !this.currentSchema) {
                    this.currentSchema = firstSpan.schema;
                    console.log('SpanManager: Auto-set schema from loaded spans:', this.currentSchema);
                }
            }

            console.log('🔍 [DEBUG] SpanManager.loadAnnotations() - Loaded annotations:', this.annotations);
            console.log('🔍 [DEBUG] SpanManager.loadAnnotations() - this.annotations.spans:', this.annotations.spans);
            console.log('🔍 [DEBUG] SpanManager.loadAnnotations() - getSpans() would return:', this.getSpans());
            console.log('🔍 [DEBUG] SpanManager.loadAnnotations() - Current schema:', this.currentSchema);

            // Render spans
            console.log('🔍 [DEBUG] SpanManager.loadAnnotations() - About to call renderSpans()');
            this.renderSpans();
            console.log('🔍 [DEBUG] SpanManager.loadAnnotations() - renderSpans() call completed');

            this.logDebugState('loadAnnotations_completed', {
                instanceId: instanceId,
                annotationsCount: this.annotations?.spans?.length || 0,
                overlayCount: this.getCurrentOverlayCount()
            });

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
        console.log('[DEEP DEBUG] renderSpans called');
        this.debugState.renderSpansCalls++;

        this.logDebugState('renderSpans_start', {
            annotationsCount: this.annotations?.spans?.length || 0,
            currentInstanceId: this.currentInstanceId,
            overlayCount: this.getCurrentOverlayCount()
        });

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

            // Elements are available, proceed with rendering
            this._renderSpansInternal(textContainer, textContent, spanOverlays);
        };

        waitForElements();
    }

    /**
     * Internal method to render spans once DOM elements are confirmed available
     */
    _renderSpansInternal(textContainer, textContent, spanOverlays) {
        console.log('🔍 [DEBUG] SpanManager._renderSpansInternal() - ENTRY POINT');
        console.log('🔍 [DEBUG] SpanManager._renderSpansInternal() - textContent exists:', !!textContent);
        console.log('🔍 [DEBUG] SpanManager._renderSpansInternal() - textContainer exists:', !!textContainer);
        console.log('🔍 [DEBUG] SpanManager._renderSpansInternal() - spanOverlays exists:', !!spanOverlays);

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
        console.log('🔍 [DEBUG] SpanManager._renderSpansInternal() - getSpans() returned:', spans);
        console.log('🔍 [DEBUG] SpanManager._renderSpansInternal() - spans length:', spans?.length || 0);
        console.log('SpanManager: Starting interval-based renderSpans with', spans?.length || 0, 'spans');

        // DEBUG: Track overlays before clearing
        const overlaysBeforeClear = spanOverlays.children.length;
        console.log(`🔍 [DEBUG] SpanManager._renderSpansInternal() - Before clearing overlays: ${overlaysBeforeClear} overlays`);

        // Log details of existing overlays before clearing
        if (overlaysBeforeClear > 0) {
            console.log('🔍 [DEBUG] SpanManager._renderSpansInternal() - Existing overlays before clear:');
            Array.from(spanOverlays.children).forEach((overlay, index) => {
                console.log(`  Overlay ${index}:`, {
                    className: overlay.className,
                    dataset: overlay.dataset,
                    innerHTML: overlay.innerHTML.substring(0, 100) + '...'
                });
            });
        }

        // FIREFOX FIX: Force complete DOM cleanup
        // Firefox sometimes doesn't immediately remove elements when innerHTML is cleared
        const isFirefox = navigator.userAgent.toLowerCase().includes('firefox');
        if (isFirefox) {
            console.log('🔍 [DEBUG] Firefox detected - using enhanced overlay cleanup');

            // Method 1: Remove each child individually
            while (spanOverlays.firstChild) {
                spanOverlays.removeChild(spanOverlays.firstChild);
            }

            // Method 2: Force a reflow to ensure DOM is updated
            spanOverlays.offsetHeight;

            // Method 3: Double-check that all overlays are gone
            const remainingOverlays = spanOverlays.querySelectorAll('.span-overlay');
            if (remainingOverlays.length > 0) {
                console.warn('🔍 [DEBUG] Firefox: Some overlays still present after removal, forcing cleanup');
                remainingOverlays.forEach(overlay => {
                    if (overlay.parentNode) {
                        overlay.parentNode.removeChild(overlay);
                    }
                });
            }
        } else {
            // Standard cleanup for other browsers
            console.log('🔍 [DEBUG] Standard overlay cleanup for non-Firefox browser');
            spanOverlays.innerHTML = '';
        }

        // DEBUG: Track overlays after clearing
        const overlaysAfterClear = spanOverlays.children.length;
        console.log(`🔍 [DEBUG] SpanManager._renderSpansInternal() - After clearing overlays: ${overlaysAfterClear} overlays`);

        if (!spans || spans.length === 0) {
            // Just display the original text in text content layer
            const originalText = window.currentInstance?.text || '';
            textContent.textContent = originalText;
            console.log('🔍 [DEBUG] SpanManager._renderSpansInternal() - No spans to render, displaying original text:', originalText);
            console.log('🔍 [DEBUG] SpanManager._renderSpansInternal() - EXIT POINT (no spans)');
            return;
        }

        // Get the original text
        const text = window.currentInstance?.text || '';
        console.log('SpanManager: Original text length:', text.length);

        // Display text in text content layer
        textContent.textContent = text;

        // FIREFOX FIX: Force a reflow before calculating positions
        if (isFirefox) {
            textContent.offsetHeight;
        }

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
        console.log('🔍 [DEBUG] SpanManager._renderSpansInternal() - About to render', sortedSpans.length, 'spans');
        sortedSpans.forEach((span, index) => {
            console.log(`🔍 [DEBUG] SpanManager._renderSpansInternal() - Rendering span ${index}:`, span);
            this.renderSpanOverlay(span, index, textContent, spanOverlays, overlapDataMap);
        });

        // Apply overlap styling
        const spanElements = spanOverlays.querySelectorAll('.span-highlight');
        this.applyOverlapStyling(spanElements, overlapDataArray);

        // FIREFOX FIX: Add delay before checking overlay count to account for asynchronous creation
        const checkOverlays = () => {
            // DEBUG: Track overlays after rendering
            const overlaysAfterRender = spanOverlays.children.length;
            console.log(`🔍 [DEBUG] SpanManager._renderSpansInternal() - After rendering: ${overlaysAfterRender} overlays created`);
            console.log(`🔍 [DEBUG] SpanManager._renderSpansInternal() - Is Firefox: ${isFirefox}`);

            // Log details of created overlays
            if (overlaysAfterRender > 0) {
                console.log('🔍 [DEBUG] SpanManager._renderSpansInternal() - Created overlays:');
                Array.from(spanOverlays.children).forEach((overlay, index) => {
                    console.log(`  Created Overlay ${index}:`, {
                        className: overlay.className,
                        dataset: overlay.dataset,
                        innerHTML: overlay.innerHTML.substring(0, 100) + '...'
                    });
                });
            } else {
                console.log('🔍 [DEBUG] SpanManager._renderSpansInternal() - WARNING: No overlays created!');
                console.log('🔍 [DEBUG] SpanManager._renderSpansInternal() - spanOverlays container:', spanOverlays);
                console.log('🔍 [DEBUG] SpanManager._renderSpansInternal() - spanOverlays.innerHTML:', spanOverlays.innerHTML.substring(0, 200) + '...');
            }

            console.log('🔍 [DEBUG] SpanManager._renderSpansInternal() - EXIT POINT (with spans)');
            console.log('SpanManager: Interval-based rendering completed');
        };

        if (isFirefox) {
            console.log('🔍 [DEBUG] SpanManager._renderSpansInternal() - Firefox detected, delaying overlay count check');
            setTimeout(checkOverlays, 10); // Small delay to allow async overlay creation
        } else {
            console.log('🔍 [DEBUG] SpanManager._renderSpansInternal() - Not Firefox, checking overlay count immediately');
            checkOverlays();
        }
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
        console.log('🔍 [DEBUG] SpanManager.renderSpanOverlay() - ENTRY POINT');
        console.log('🔍 [DEBUG] SpanManager.renderSpanOverlay() - span:', span);
        console.log('🔍 [DEBUG] SpanManager.renderSpanOverlay() - layerIndex:', layerIndex);
        console.log('🔍 [DEBUG] SpanManager.renderSpanOverlay() - spanOverlays container exists:', !!spanOverlays);
        console.log('🔍 [DEBUG] SpanManager.renderSpanOverlay() - spanOverlays children before:', spanOverlays?.children?.length || 0);

        // Defensive check: ensure text node exists
        const textNode = textContent.firstChild;
        if (!textNode || textNode.nodeType !== Node.TEXT_NODE) {
            console.error('SpanManager: No text node found in #text-content when rendering span overlay', {
                span: span,
                textContentChildNodes: textContent.childNodes.length,
                firstChildType: textNode ? textNode.nodeType : 'null'
            });
            console.log('🔍 [DEBUG] SpanManager.renderSpanOverlay() - EXIT POINT (no text node)');
            return; // Skip rendering this span
        }

        // FIREFOX FIX: Ensure text content is properly rendered before getting bounding rects
        const isFirefox = navigator.userAgent.toLowerCase().includes('firefox');
        console.log('🔍 [DEBUG] SpanManager.renderSpanOverlay() - Is Firefox:', isFirefox);

        if (isFirefox) {
            // Force a reflow to ensure text is properly laid out
            textContent.offsetHeight;
            console.log('🔍 [DEBUG] SpanManager.renderSpanOverlay() - Forced reflow for Firefox');
        }

        // Get bounding rects for the span's character range
        const rects = getCharRangeBoundingRect(textContent, span.start, span.end);
        console.log('🔍 [DEBUG] SpanManager.renderSpanOverlay() - bounding rects:', rects);
        if (!rects || rects.length === 0) {
            console.warn('SpanManager: Could not get bounding rect for span', span);
            console.log('🔍 [DEBUG] SpanManager.renderSpanOverlay() - EXIT POINT (no bounding rect)');
            return;
        }

        // Get the instance-text container's bounding rect for relative positioning
        const instanceTextContainer = document.getElementById('instance-text');
        const containerRect = instanceTextContainer.getBoundingClientRect();
        console.log('🔍 [DEBUG] SpanManager.renderSpanOverlay() - containerRect:', containerRect);

        // FIREFOX FIX: Add small delay to ensure positioning is accurate
        const createOverlay = () => {
            console.log('🔍 [DEBUG] SpanManager.renderSpanOverlay() - createOverlay() called');
            console.log('🔍 [DEBUG] SpanManager.renderSpanOverlay() - rects.length:', rects.length);

            // Create overlay for each rect (handles line wrapping)
            rects.forEach((rect, rectIndex) => {
                console.log(`🔍 [DEBUG] SpanManager.renderSpanOverlay() - Creating overlay for rect ${rectIndex}:`, rect);
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

                // FIREFOX FIX: Ensure positive dimensions and add safety checks
                const safeWidth = Math.max(1, width);
                const safeHeight = Math.max(1, height);

                overlay.style.left = `${left}px`;
                overlay.style.top = `${top}px`;
                overlay.style.width = `${safeWidth}px`;
                overlay.style.height = `${safeHeight}px`;
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
                    overlay.style.height = `${Math.max(1, adjustedHeight)}px`;

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

                console.log('🔍 [DEBUG] SpanManager.renderSpanOverlay() - About to append overlay to container');
                spanOverlays.appendChild(overlay);
                console.log(`🔍 [DEBUG] SpanManager.renderSpanOverlay() - Overlay appended. Container now has ${spanOverlays.children.length} children`);

                // Track overlay creation for debugging
                if (typeof trackOverlayCreation === 'function') {
                    trackOverlayCreation(overlay, 'SpanManager.renderSpanOverlay');
                }
            });

            console.log('🔍 [DEBUG] SpanManager.renderSpanOverlay() - createOverlay() completed');
        };

        // FIREFOX FIX: Use setTimeout for Firefox to ensure DOM is ready
        if (isFirefox) {
            console.log('🔍 [DEBUG] SpanManager.renderSpanOverlay() - Scheduling createOverlay with setTimeout for Firefox');
            setTimeout(() => {
                console.log('🔍 [DEBUG] SpanManager.renderSpanOverlay() - setTimeout callback executing');
                createOverlay();
                console.log('🔍 [DEBUG] SpanManager.renderSpanOverlay() - setTimeout callback completed');
            }, 0);
        } else {
            console.log('🔍 [DEBUG] SpanManager.renderSpanOverlay() - Calling createOverlay immediately (not Firefox)');
            createOverlay();
        }

        console.log('🔍 [DEBUG] SpanManager.renderSpanOverlay() - EXIT POINT (function returning, overlay may be created asynchronously)');
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

        const selectedLabel = this.getSelectedLabel();
        if (!selectedLabel) {
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
            label: selectedLabel
        });

        // Validate the selection
        if (start >= end) {
            console.warn('SpanManager: Invalid selection range (start >= end)');
            this.showStatus('Invalid selection range', 'error');
            selection.removeAllRanges();
            return;
        }

        // Create annotation
        this.createAnnotation(selectedText, start, end, selectedLabel)
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
     * DISABLED: Status messages are suppressed but code is preserved for future diagnostics
     */
    showStatus(message, type) {
        // Status messages are disabled - uncomment the code below to re-enable
        /*
        const statusDiv = document.getElementById('status');
        if (statusDiv) {
            statusDiv.textContent = message;
            statusDiv.className = `status ${type}`;
            statusDiv.style.display = 'block';

            setTimeout(() => {
                statusDiv.style.display = 'none';
            }, 3000);
        }
        */

        // Keep console logging for debugging (can be disabled if needed)
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

    /**
     * Aggressively clear all overlays and internal state with deep logging
     */
    clearAllStateAndOverlays() {
        console.log('[DEEP DEBUG] clearAllStateAndOverlays called');
        this.debugState.clearAllStateCalls++;

        // Log state before clearing
        this.logDebugState('clearAllStateAndOverlays_before', {
            overlayCount: this.getCurrentOverlayCount(),
            annotationsCount: this.annotations?.spans?.length || 0
        });

        // Clear overlays
        const spanOverlays = document.getElementById('span-overlays');
        if (spanOverlays) {
            const beforeCount = spanOverlays.children.length;
            console.log('[DEEP DEBUG] Clearing overlays, count before:', beforeCount);

            while (spanOverlays.firstChild) {
                spanOverlays.removeChild(spanOverlays.firstChild);
            }

            // Force reflow
            spanOverlays.offsetHeight;

            // Double-check
            const remaining = spanOverlays.querySelectorAll('.span-overlay');
            if (remaining.length > 0) {
                console.warn('[DEEP DEBUG] Overlays still present after clear, forcing removal');
                remaining.forEach(node => {
                    if (node.parentNode) {
                        node.parentNode.removeChild(node);
                    }
                });
            }

            const afterCount = spanOverlays.children.length;
            console.log('[DEEP DEBUG] Overlays cleared, count after:', afterCount);
        }

        // Reset internal state
        this.annotations = {spans: []};
        this.currentSchema = null;
        this.selectedLabel = null;
        this.isInitialized = false;

        this.logDebugState('clearAllStateAndOverlays_after', {
            overlayCount: this.getCurrentOverlayCount(),
            annotationsCount: this.annotations?.spans?.length || 0
        });

        console.log('[DEEP DEBUG] Internal state reset complete');
    }

    /**
     * Get current overlay count for debugging
     */
    getCurrentOverlayCount() {
        const spanOverlays = document.getElementById('span-overlays');
        return spanOverlays ? spanOverlays.children.length : 0;
    }

    /**
     * Enhanced onInstanceChange with deep logging
     */
    onInstanceChange(newInstanceId) {
        console.log('[DEEP DEBUG] onInstanceChange called with newInstanceId:', newInstanceId);
        this.debugState.onInstanceChangeCalls++;

        this.logDebugState('onInstanceChange_start', {
            newInstanceId: newInstanceId,
            currentInstanceId: this.currentInstanceId,
            overlayCount: this.getCurrentOverlayCount()
        });

        // Clear all state first
        this.clearAllStateAndOverlays();

        // If newInstanceId is provided, use it; otherwise fetch from server
        if (typeof newInstanceId !== 'undefined') {
            console.log('[DEEP DEBUG] Using provided newInstanceId:', newInstanceId);
            this.loadAnnotations(newInstanceId);
        } else {
            console.log('[DEEP DEBUG] No newInstanceId provided, fetching from server');
            this.fetchCurrentInstanceIdFromServer().then(serverInstanceId => {
                if (serverInstanceId) {
                    this.loadAnnotations(serverInstanceId);
                }
            });
        }

        this.logDebugState('onInstanceChange_completed', {
            newInstanceId: newInstanceId,
            currentInstanceId: this.currentInstanceId
        });
    }

    /**
     * Remove all span overlays from the DOM and reset internal state
     */
    clearAllSpanOverlays() {
        const spanOverlays = document.getElementById('span-overlays');
        if (spanOverlays) {
            while (spanOverlays.firstChild) {
                spanOverlays.removeChild(spanOverlays.firstChild);
            }
        }
        this.annotations = {spans: []};
        console.log('[DEFENSIVE] Cleared all span overlays and reset annotations');
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

    // FIREFOX FIX: Handle Firefox's different behavior with getClientRects
    const isFirefox = navigator.userAgent.toLowerCase().includes('firefox');

    let rects;
    if (isFirefox) {
        // Firefox sometimes returns empty rects if the text hasn't been fully rendered
        // Force a reflow and try multiple times
        let attempts = 0;
        const maxAttempts = 3;

        while (attempts < maxAttempts) {
            // Force a reflow
            container.offsetHeight;

            rects = range.getClientRects();
            if (rects.length > 0) {
                break;
            }

            attempts++;
            if (attempts < maxAttempts) {
                // Small delay before retry
                const startTime = Date.now();
                while (Date.now() - startTime < 10) {
                    // Busy wait for 10ms
                }
            }
        }

        // If still no rects, try alternative method for Firefox
        if (rects.length === 0) {
            console.warn('Firefox: getClientRects returned empty, trying alternative method');

            // Alternative: use getBoundingClientRect on the range
            const boundingRect = range.getBoundingClientRect();
            if (boundingRect.width > 0 && boundingRect.height > 0) {
                rects = [boundingRect];
            }
        }
    } else {
        rects = range.getClientRects();
    }

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

/**
 * ===================== DEBUGGING & MAINTENANCE NOTES =====================
 * - All major state changes are logged with [DEBUG] or [DEFENSIVE] tags.
 * - If overlays persist across navigation, check onInstanceChange and clearAllSpanOverlays.
 * - If overlays are missing, check loadAnnotations and renderSpans logic.
 * - For browser-specific issues (esp. Firefox), see FIREFOX FIX comments.
 * - Selenium tests in tests/selenium/ can be used to automate bug reproduction.
 * ========================================================================
 */
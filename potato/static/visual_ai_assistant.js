/**
 * Visual AI Assistant Manager
 *
 * Manages AI-powered suggestions for image and video annotation tasks.
 * Handles rendering suggestion overlays on Fabric.js canvas (images)
 * and Peaks.js timeline (video), with accept/reject UI.
 */

class VisualAIAssistantManager {
    /**
     * Create a VisualAIAssistantManager.
     * @param {Object} options - Configuration options
     * @param {string} options.annotationType - 'image_annotation' or 'video_annotation'
     * @param {number} options.annotationId - The annotation scheme index
     * @param {Object} options.annotationManager - Reference to ImageAnnotationManager or VideoAnnotationManager
     */
    constructor(options) {
        console.log('[VisualAI] Constructor called with options:', options);
        this.annotationType = options.annotationType;
        this.annotationId = options.annotationId;
        this.annotationManager = options.annotationManager;

        // Suggestion storage
        this.suggestions = [];
        this.suggestionObjects = new Map(); // Map suggestion ID to canvas/timeline objects

        // State
        this.isLoading = false;
        this.lastError = null;

        // UI elements
        this.toolbar = null;
        this.tooltipContainer = null;

        this._init();
        console.log('[VisualAI] Initialization complete, toolbar:', this.toolbar);
    }

    /**
     * Initialize the AI assistant.
     */
    _init() {
        this._createUI();
        this._setupEventListeners();
    }

    /**
     * Create the AI toolbar UI.
     */
    _createUI() {
        // Find the annotation container
        const container = this.annotationManager?.container ||
            document.querySelector('.image-annotation-container, .video-annotation-container');

        if (!container) {
            console.warn('[VisualAI] No annotation container found');
            return;
        }

        // Check if AI toolbar already exists
        if (container.querySelector('.ai-toolbar')) {
            this.toolbar = container.querySelector('.ai-toolbar');
            return;
        }

        // Create AI toolbar
        this.toolbar = document.createElement('div');
        this.toolbar.className = 'ai-toolbar';
        this.toolbar.innerHTML = `
            <div class="ai-toolbar-group">
                <span class="ai-toolbar-label">AI Assist:</span>
                <button type="button" class="ai-btn" data-action="detect" title="Detect objects">
                    <span class="ai-btn-icon">🔍</span> Detect
                </button>
                <button type="button" class="ai-btn" data-action="pre_annotate" title="Auto-annotate all">
                    <span class="ai-btn-icon">⚡</span> Auto
                </button>
                <button type="button" class="ai-btn" data-action="hint" title="Get a hint">
                    <span class="ai-btn-icon">💡</span> Hint
                </button>
            </div>
            <div class="ai-suggestion-controls" style="display: none;">
                <span class="suggestion-count">0 suggestions</span>
                <button type="button" class="ai-btn ai-btn-accept" data-action="accept-all" title="Accept all suggestions">
                    Accept All
                </button>
                <button type="button" class="ai-btn ai-btn-clear" data-action="clear" title="Clear all suggestions">
                    Clear
                </button>
            </div>
            <div class="ai-loading-indicator" style="display: none;">
                <span class="spinner"></span> Loading...
            </div>
        `;

        // Insert toolbar after the main toolbar
        const mainToolbar = container.querySelector('.image-annotation-toolbar, .video-annotation-toolbar');
        if (mainToolbar) {
            mainToolbar.after(this.toolbar);
        } else {
            container.prepend(this.toolbar);
        }

        // Create tooltip container for hints
        this.tooltipContainer = document.createElement('div');
        this.tooltipContainer.className = 'ai-tooltip-container';
        this.tooltipContainer.style.display = 'none';
        container.appendChild(this.tooltipContainer);

        // Add CSS styles
        this._addStyles();
    }

    /**
     * Add CSS styles for the AI toolbar.
     */
    _addStyles() {
        if (document.getElementById('visual-ai-styles')) return;

        const styles = document.createElement('style');
        styles.id = 'visual-ai-styles';
        styles.textContent = `
            .ai-toolbar {
                display: flex;
                align-items: center;
                gap: 1rem;
                padding: 0.5rem 0.75rem;
                background: linear-gradient(to right, #f0f9ff, #e0f2fe);
                border: 1px solid #bae6fd;
                border-radius: 0.375rem;
                margin-bottom: 0.5rem;
                flex-wrap: wrap;
            }

            .ai-toolbar-label {
                font-weight: 600;
                color: #0369a1;
                font-size: 0.85rem;
            }

            .ai-toolbar-group {
                display: flex;
                align-items: center;
                gap: 0.5rem;
            }

            .ai-btn {
                display: inline-flex;
                align-items: center;
                gap: 0.25rem;
                padding: 0.375rem 0.75rem;
                background: white;
                border: 1px solid #0ea5e9;
                border-radius: 0.25rem;
                color: #0284c7;
                font-size: 0.8rem;
                cursor: pointer;
                transition: all 0.15s ease;
            }

            .ai-btn:hover:not(:disabled) {
                background: #0ea5e9;
                color: white;
            }

            .ai-btn:disabled {
                opacity: 0.5;
                cursor: not-allowed;
            }

            .ai-btn-icon {
                font-size: 0.9rem;
            }

            .ai-btn-accept {
                background: #dcfce7;
                border-color: #22c55e;
                color: #166534;
            }

            .ai-btn-accept:hover:not(:disabled) {
                background: #22c55e;
                color: white;
            }

            .ai-btn-clear {
                background: #fee2e2;
                border-color: #ef4444;
                color: #dc2626;
            }

            .ai-btn-clear:hover:not(:disabled) {
                background: #ef4444;
                color: white;
            }

            .ai-suggestion-controls {
                display: flex;
                align-items: center;
                gap: 0.5rem;
                margin-left: auto;
            }

            .suggestion-count {
                font-size: 0.8rem;
                color: #64748b;
            }

            .ai-loading-indicator {
                display: flex;
                align-items: center;
                gap: 0.5rem;
                color: #0369a1;
                font-size: 0.8rem;
            }

            .ai-loading-indicator .spinner {
                width: 1rem;
                height: 1rem;
                border: 2px solid #e0f2fe;
                border-top-color: #0ea5e9;
                border-radius: 50%;
                animation: spin 0.8s linear infinite;
            }

            @keyframes spin {
                to { transform: rotate(360deg); }
            }

            .ai-tooltip-container {
                position: absolute;
                top: 100%;
                left: 0;
                right: 0;
                background: #fef3c7;
                border: 1px solid #f59e0b;
                border-radius: 0.375rem;
                padding: 0.75rem 1rem;
                margin-top: 0.5rem;
                z-index: 100;
                box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
            }

            .ai-tooltip-container .hint-text {
                color: #92400e;
                font-size: 0.9rem;
                line-height: 1.4;
            }

            .ai-tooltip-container .close-btn {
                position: absolute;
                top: 0.5rem;
                right: 0.5rem;
                background: none;
                border: none;
                font-size: 1.25rem;
                color: #92400e;
                cursor: pointer;
                padding: 0;
                line-height: 1;
            }

            /* Suggestion overlay styles for canvas */
            .ai-suggestion-overlay {
                stroke-dasharray: 5, 5;
                stroke-width: 2;
                fill-opacity: 0.2;
            }

            .ai-suggestion-label {
                position: absolute;
                background: rgba(14, 165, 233, 0.9);
                color: white;
                font-size: 0.7rem;
                padding: 0.125rem 0.375rem;
                border-radius: 0.25rem;
                pointer-events: none;
                white-space: nowrap;
            }

            /* Suggestion controls on individual suggestions */
            .suggestion-actions {
                position: absolute;
                display: flex;
                gap: 0.25rem;
                transform: translateY(-100%);
                margin-top: -0.25rem;
            }

            .suggestion-actions button {
                padding: 0.125rem 0.375rem;
                font-size: 0.7rem;
                border: none;
                border-radius: 0.125rem;
                cursor: pointer;
            }

            .suggestion-actions .accept-btn {
                background: #22c55e;
                color: white;
            }

            .suggestion-actions .reject-btn {
                background: #ef4444;
                color: white;
            }

            /* Video timeline suggestion styles */
            .video-suggestion-segment {
                opacity: 0.6;
                stroke-dasharray: 4, 2;
            }

            .video-suggestion-segment:hover {
                opacity: 0.8;
            }
        `;
        document.head.appendChild(styles);
    }

    /**
     * Set up event listeners for toolbar buttons.
     */
    _setupEventListeners() {
        if (!this.toolbar) {
            console.warn('[VisualAI] No toolbar found for event listeners');
            return;
        }

        console.log('[VisualAI] Setting up event listeners on toolbar');
        this.toolbar.addEventListener('click', (e) => {
            const btn = e.target.closest('.ai-btn');
            console.log('[VisualAI] Toolbar click, button:', btn);
            if (!btn || btn.disabled) return;

            const action = btn.dataset.action;
            console.log('[VisualAI] Button action:', action);
            switch (action) {
                case 'detect':
                case 'pre_annotate':
                case 'hint':
                case 'classification':
                case 'scene_detection':
                case 'keyframe_detection':
                    this.requestSuggestion(action);
                    break;
                case 'accept-all':
                    this.acceptAllSuggestions();
                    break;
                case 'clear':
                    this.clearSuggestions();
                    break;
            }
        });

        // Close hint tooltip
        if (this.tooltipContainer) {
            this.tooltipContainer.addEventListener('click', (e) => {
                if (e.target.classList.contains('close-btn')) {
                    this.tooltipContainer.style.display = 'none';
                }
            });
        }
    }

    /**
     * Request AI suggestions from the server.
     * @param {string} aiAssistant - Type of assistance to request
     */
    async requestSuggestion(aiAssistant) {
        console.log('[VisualAI] requestSuggestion called with:', aiAssistant);
        if (this.isLoading) {
            console.log('[VisualAI] Already loading, skipping');
            return;
        }

        this.isLoading = true;
        this._showLoading(true);
        this.lastError = null;

        try {
            const url = `/api/get_ai_suggestion?annotationId=${this.annotationId}&aiAssistant=${aiAssistant}`;
            console.log('[VisualAI] Fetching:', url);
            const response = await fetch(url);

            if (!response.ok) {
                throw new Error(`HTTP error: ${response.status}`);
            }

            const data = await response.json();
            console.log('[VisualAI] Response data:', data);

            if (data.error) {
                throw new Error(data.error);
            }

            this._handleSuggestionResponse(aiAssistant, data);

        } catch (error) {
            console.error('[VisualAI] Error fetching suggestion:', error);
            this.lastError = error.message;
            this._showError(error.message);
        } finally {
            this.isLoading = false;
            this._showLoading(false);
        }
    }

    /**
     * Handle the suggestion response from the server.
     * @param {string} assistantType - Type of assistant that responded
     * @param {Object} data - Response data
     */
    _handleSuggestionResponse(assistantType, data) {
        console.log('[VisualAI] _handleSuggestionResponse:', assistantType, data);

        // Handle hints differently
        if (assistantType === 'hint' && (data.hint || data.suggestive_choice)) {
            this._showHint(data);
            return;
        }

        // Handle detection results
        if (data.detections) {
            console.log('[VisualAI] Rendering detections:', data.detections.length);
            this._renderDetections(data.detections);
        } else {
            console.log('[VisualAI] No detections in response');
        }

        // Handle video segments
        if (data.segments) {
            this._renderVideoSegments(data.segments);
        }

        // Handle keyframes
        if (data.keyframes) {
            this._renderKeyframes(data.keyframes);
        }

        // Handle classification
        if (data.suggested_label) {
            this._showClassificationResult(data);
        }

        // Update suggestion controls
        this._updateSuggestionControls();
    }

    /**
     * Render detection suggestions on the canvas.
     * @param {Array} detections - Array of detection objects
     */
    _renderDetections(detections) {
        if (!this.annotationManager?.canvas) {
            console.warn('[VisualAI] No canvas available for rendering detections');
            return;
        }

        const canvas = this.annotationManager.canvas;
        const image = this.annotationManager.image;

        if (!image) {
            console.warn('[VisualAI] No image loaded');
            return;
        }

        // Get image dimensions for denormalization
        const imgWidth = image.width * image.scaleX;
        const imgHeight = image.height * image.scaleY;
        const imgLeft = image.left;
        const imgTop = image.top;

        detections.forEach((detection, index) => {
            const suggestionId = `suggestion_${Date.now()}_${index}`;

            // Denormalize bbox coordinates
            const bbox = detection.bbox;
            const left = imgLeft + bbox.x * imgWidth;
            const top = imgTop + bbox.y * imgHeight;
            const width = bbox.width * imgWidth;
            const height = bbox.height * imgHeight;

            // Get color for this label
            const color = this._getLabelColor(detection.label);

            // Create suggestion rectangle - EDITABLE so annotators can adjust bounds
            const rect = new fabric.Rect({
                left: left,
                top: top,
                width: width,
                height: height,
                fill: `${color}33`,  // 20% opacity
                stroke: color,
                strokeWidth: 2,
                strokeDashArray: [5, 5],
                selectable: true,  // Allow selection and editing
                evented: true,
                hasControls: true,  // Show resize handles
                hasBorders: true,
                cornerColor: color,
                cornerStyle: 'circle',
                cornerSize: 8,
                transparentCorners: false,
                lockRotation: true,  // Don't allow rotation for bboxes
                suggestionId: suggestionId,
                suggestionData: detection,
                isSuggestion: true  // Mark as suggestion for identification
            });

            // Create label text
            const labelText = new fabric.Text(
                `${detection.label} (${Math.round(detection.confidence * 100)}%)`,
                {
                    left: left,
                    top: top - 18,
                    fontSize: 12,
                    fill: 'white',
                    backgroundColor: color,
                    padding: 3,
                    selectable: false,
                    evented: false,
                    suggestionId: suggestionId
                }
            );

            // Update label position when rect is moved/scaled
            rect.on('moving', () => {
                labelText.set({
                    left: rect.left,
                    top: rect.top - 18
                });
                canvas.renderAll();
            });

            rect.on('scaling', () => {
                labelText.set({
                    left: rect.left * rect.scaleX,
                    top: rect.top * rect.scaleY - 18
                });
            });

            rect.on('modified', () => {
                // Update the suggestion data with new bounds
                const newBounds = {
                    x: (rect.left - imgLeft) / imgWidth,
                    y: (rect.top - imgTop) / imgHeight,
                    width: (rect.width * rect.scaleX) / imgWidth,
                    height: (rect.height * rect.scaleY) / imgHeight
                };
                rect.suggestionData = {
                    ...rect.suggestionData,
                    bbox: newBounds,
                    modified: true
                };
                // Update label position
                labelText.set({
                    left: rect.left,
                    top: rect.top - 18
                });
                canvas.renderAll();
                console.log('[VisualAI] Suggestion modified:', suggestionId, newBounds);
            });

            // Add to canvas
            canvas.add(rect, labelText);

            // Store references
            this.suggestions.push({
                id: suggestionId,
                type: 'detection',
                data: detection
            });
            this.suggestionObjects.set(suggestionId, [rect, labelText]);

            // Add click handler for accept/reject
            rect.on('mousedown', (e) => {
                if (e.e.button === 2) { // Right click to reject
                    this.rejectSuggestion(suggestionId);
                } else if (e.e.detail === 2) { // Double click to accept
                    this.acceptSuggestion(suggestionId);
                }
            });
        });

        canvas.renderAll();
    }

    /**
     * Render video segment suggestions on the timeline.
     * @param {Array} segments - Array of segment objects
     */
    _renderVideoSegments(segments) {
        if (!this.annotationManager?.peaks) {
            console.warn('[VisualAI] No Peaks.js instance for rendering segments');
            return;
        }

        const peaks = this.annotationManager.peaks;

        segments.forEach((segment, index) => {
            const suggestionId = `suggestion_segment_${Date.now()}_${index}`;
            const color = this._getLabelColor(segment.suggested_label);

            // Add segment to Peaks.js
            peaks.segments.add({
                id: suggestionId,
                startTime: segment.start_time,
                endTime: segment.end_time,
                labelText: `${segment.suggested_label} (${Math.round(segment.confidence * 100)}%)`,
                color: color + '99',  // Semi-transparent
                editable: false
            });

            this.suggestions.push({
                id: suggestionId,
                type: 'segment',
                data: segment
            });
        });
    }

    /**
     * Render keyframe suggestions on the timeline.
     * @param {Array} keyframes - Array of keyframe objects
     */
    _renderKeyframes(keyframes) {
        if (!this.annotationManager?.peaks) {
            console.warn('[VisualAI] No Peaks.js instance for rendering keyframes');
            return;
        }

        const peaks = this.annotationManager.peaks;

        keyframes.forEach((keyframe, index) => {
            const suggestionId = `suggestion_keyframe_${Date.now()}_${index}`;
            const color = this._getLabelColor(keyframe.suggested_label);

            peaks.points.add({
                id: suggestionId,
                time: keyframe.timestamp,
                labelText: keyframe.suggested_label,
                color: color,
                editable: false
            });

            this.suggestions.push({
                id: suggestionId,
                type: 'keyframe',
                data: keyframe
            });
        });
    }

    /**
     * Show a hint in the tooltip container.
     * @param {Object} hintData - Hint response data
     */
    _showHint(hintData) {
        if (!this.tooltipContainer) return;

        this.tooltipContainer.innerHTML = `
            <button class="close-btn">&times;</button>
            <div class="hint-text">
                <strong>Hint:</strong> ${hintData.hint}
                ${hintData.suggestive_choice ? `<br><em>Focus: ${hintData.suggestive_choice}</em>` : ''}
            </div>
        `;
        this.tooltipContainer.style.display = 'block';
    }

    /**
     * Show classification result.
     * @param {Object} result - Classification result
     */
    _showClassificationResult(result) {
        if (!this.tooltipContainer) return;

        this.tooltipContainer.innerHTML = `
            <button class="close-btn">&times;</button>
            <div class="hint-text">
                <strong>Suggested Label:</strong> ${result.suggested_label}
                (${Math.round(result.confidence * 100)}% confidence)
                ${result.reasoning ? `<br><em>Reasoning: ${result.reasoning}</em>` : ''}
            </div>
        `;
        this.tooltipContainer.style.display = 'block';
    }

    /**
     * Accept a single suggestion.
     * @param {string} suggestionId - ID of the suggestion to accept
     */
    acceptSuggestion(suggestionId) {
        const suggestion = this.suggestions.find(s => s.id === suggestionId);
        if (!suggestion) return;

        if (suggestion.type === 'detection') {
            this._convertDetectionToAnnotation(suggestion);
        } else if (suggestion.type === 'segment') {
            this._convertSegmentToAnnotation(suggestion);
        } else if (suggestion.type === 'keyframe') {
            this._convertKeyframeToAnnotation(suggestion);
        }

        this._removeSuggestionVisual(suggestionId);
        this.suggestions = this.suggestions.filter(s => s.id !== suggestionId);
        this._updateSuggestionControls();
    }

    /**
     * Reject a single suggestion.
     * @param {string} suggestionId - ID of the suggestion to reject
     */
    rejectSuggestion(suggestionId) {
        this._removeSuggestionVisual(suggestionId);
        this.suggestions = this.suggestions.filter(s => s.id !== suggestionId);
        this._updateSuggestionControls();
    }

    /**
     * Accept all suggestions.
     */
    acceptAllSuggestions() {
        const suggestionsToAccept = [...this.suggestions];
        suggestionsToAccept.forEach(s => this.acceptSuggestion(s.id));
    }

    /**
     * Clear all suggestions.
     */
    clearSuggestions() {
        this.suggestions.forEach(s => this._removeSuggestionVisual(s.id));
        this.suggestions = [];
        this._updateSuggestionControls();
    }

    /**
     * Convert a detection suggestion to a permanent annotation.
     * @param {Object} suggestion - The suggestion to convert
     */
    _convertDetectionToAnnotation(suggestion) {
        if (!this.annotationManager?.addAnnotation) {
            console.warn('[VisualAI] Cannot convert detection - no addAnnotation method');
            return;
        }

        // Get the potentially modified detection data from the canvas object
        const objects = this.suggestionObjects.get(suggestion.id);
        let detection = suggestion.data;

        if (objects && objects[0] && objects[0].suggestionData) {
            // Use the modified data from the canvas rect if available
            detection = objects[0].suggestionData;
            console.log('[VisualAI] Using modified detection data:', detection);
        }

        this.annotationManager.setLabel(detection.label, this._getLabelColor(detection.label));

        // Create annotation from bbox
        this.annotationManager.addAnnotation({
            type: 'bbox',
            label: detection.label,
            bbox: detection.bbox,
            confidence: detection.confidence,
            source: 'ai_suggestion',
            modified: detection.modified || false
        });
    }

    /**
     * Convert a segment suggestion to a permanent annotation.
     * @param {Object} suggestion - The suggestion to convert
     */
    _convertSegmentToAnnotation(suggestion) {
        if (!this.annotationManager?.createSegment) {
            console.warn('[VisualAI] Cannot convert segment - no createSegment method');
            return;
        }

        const segment = suggestion.data;
        this.annotationManager.setActiveLabel(
            segment.suggested_label,
            this._getLabelColor(segment.suggested_label)
        );
        this.annotationManager.createSegment(
            segment.start_time,
            segment.end_time,
            segment.suggested_label
        );
    }

    /**
     * Convert a keyframe suggestion to a permanent annotation.
     * @param {Object} suggestion - The suggestion to convert
     */
    _convertKeyframeToAnnotation(suggestion) {
        if (!this.annotationManager?.markKeyframe) {
            console.warn('[VisualAI] Cannot convert keyframe - no markKeyframe method');
            return;
        }

        const keyframe = suggestion.data;
        this.annotationManager.markKeyframe(
            keyframe.suggested_label,
            keyframe.timestamp
        );
    }

    /**
     * Remove the visual representation of a suggestion.
     * @param {string} suggestionId - ID of the suggestion
     */
    _removeSuggestionVisual(suggestionId) {
        const objects = this.suggestionObjects.get(suggestionId);

        if (objects && this.annotationManager?.canvas) {
            objects.forEach(obj => {
                this.annotationManager.canvas.remove(obj);
            });
            this.annotationManager.canvas.renderAll();
        }

        // For video segments/keyframes
        if (this.annotationManager?.peaks) {
            try {
                this.annotationManager.peaks.segments.removeById(suggestionId);
            } catch (e) { /* ignore */ }
            try {
                this.annotationManager.peaks.points.removeById(suggestionId);
            } catch (e) { /* ignore */ }
        }

        this.suggestionObjects.delete(suggestionId);
    }

    /**
     * Get color for a label.
     * @param {string} label - The label name
     * @returns {string} Hex color
     */
    _getLabelColor(label) {
        // Try to get color from annotation manager
        if (this.annotationManager?.config?.labels) {
            const labelConfig = this.annotationManager.config.labels.find(
                l => (typeof l === 'string' ? l : l.name) === label
            );
            if (labelConfig?.color) return labelConfig.color;
        }

        // Default colors
        const colors = [
            '#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4',
            '#FFEAA7', '#DDA0DD', '#98D8C8', '#F7DC6F'
        ];
        const hash = label.split('').reduce((acc, char) => acc + char.charCodeAt(0), 0);
        return colors[hash % colors.length];
    }

    /**
     * Update the suggestion controls visibility.
     */
    _updateSuggestionControls() {
        if (!this.toolbar) return;

        const controls = this.toolbar.querySelector('.ai-suggestion-controls');
        const count = this.toolbar.querySelector('.suggestion-count');

        if (this.suggestions.length > 0) {
            controls.style.display = 'flex';
            count.textContent = `${this.suggestions.length} suggestion${this.suggestions.length !== 1 ? 's' : ''}`;
        } else {
            controls.style.display = 'none';
        }
    }

    /**
     * Show/hide loading indicator.
     * @param {boolean} show - Whether to show the indicator
     */
    _showLoading(show) {
        if (!this.toolbar) return;

        const indicator = this.toolbar.querySelector('.ai-loading-indicator');
        const buttons = this.toolbar.querySelectorAll('.ai-btn');

        indicator.style.display = show ? 'flex' : 'none';
        buttons.forEach(btn => {
            if (!btn.closest('.ai-suggestion-controls')) {
                btn.disabled = show;
            }
        });
    }

    /**
     * Show an error message.
     * @param {string} message - Error message
     */
    _showError(message) {
        if (!this.tooltipContainer) return;

        this.tooltipContainer.innerHTML = `
            <button class="close-btn">&times;</button>
            <div class="hint-text" style="color: #dc2626;">
                <strong>Error:</strong> ${message}
            </div>
        `;
        this.tooltipContainer.style.display = 'block';
    }
}

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = VisualAIAssistantManager;
}

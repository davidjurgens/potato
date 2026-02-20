/**
 * Tiered Annotation Manager
 *
 * Provides hierarchical multi-tier annotation for audio/video content.
 * Supports ELAN-style annotation with independent and dependent tiers,
 * where dependent tiers have constraint relationships to parent tiers.
 *
 * Features:
 * - Multi-row timeline with tier-based annotation
 * - Independent tiers for direct time alignment
 * - Dependent tiers with parent-child constraints
 * - Constraint validation (time_subdivision, included_in, etc.)
 * - Waveform visualization with Peaks.js
 * - EAF/TextGrid export support
 */

// Debug logging utility
function tieredDebugLog(...args) {
    if (window.config && window.config.debug) {
        console.log('[TieredAnnotation]', ...args);
    }
}

/**
 * TieredAnnotationManager - Main class for managing tiered annotations
 */
class TieredAnnotationManager {
    /**
     * Create a TieredAnnotationManager instance.
     *
     * @param {HTMLElement} container - Container element for the annotation interface
     * @param {Object} config - Configuration object with tier definitions
     */
    constructor(container, config) {
        this.container = container;
        this.config = config;
        this.schemaName = config.schemaName;
        this.mediaType = config.mediaType || 'audio';
        this.sourceField = config.sourceField || 'audio_url';

        // State
        this.annotations = {};  // tierName -> [annotations]
        this.activeTier = null;
        this.activeLabel = null;
        this.selectedAnnotation = null;
        this.peaks = null;
        this.mediaElement = null;
        this.isPlaying = false;
        this.annotationCounter = 0;

        // Media metadata
        this.mediaMetadata = {
            duration: 0,
            sampleRate: 44100
        };

        // Tier views
        this.tierViews = {};  // tierName -> TierView

        // Selection state (for creating new annotations)
        this.selectionStart = null;
        this.selectionEnd = null;
        this.isDragging = false;

        // DOM elements
        this._initializeDomElements();

        // Initialize annotations storage for each tier
        for (const tier of this.config.tiers) {
            this.annotations[tier.name] = [];
        }

        // Set initial active tier
        if (this.config.tiers.length > 0) {
            this.activeTier = this.config.tiers[0].name;
            this.activeLabel = this.config.tiers[0].labels?.[0]?.name || null;
        }

        // Bind methods
        this._handleKeydown = this._handleKeydown.bind(this);
        this._handleMediaTimeUpdate = this._handleMediaTimeUpdate.bind(this);

        tieredDebugLog('TieredAnnotationManager created:', this.schemaName);
    }

    /**
     * Initialize DOM element references
     */
    _initializeDomElements() {
        this.mediaElement = document.getElementById(`media-${this.schemaName}`);
        this.tierSelectEl = document.getElementById(`tier-select-${this.schemaName}`);
        this.labelsEl = document.getElementById(`labels-${this.schemaName}`);
        this.timeDisplayEl = document.getElementById(`time-display-${this.schemaName}`);
        this.overviewEl = document.getElementById(`overview-${this.schemaName}`);
        this.zoomviewEl = document.getElementById(`zoomview-${this.schemaName}`);
        this.tierRowsEl = document.getElementById(`tier-rows-${this.schemaName}`);
        this.timeAxisEl = document.getElementById(`time-axis-${this.schemaName}`);
        this.annotationListEl = document.getElementById(`annotation-list-${this.schemaName}`);
        this.inputEl = document.getElementById(`input-${this.schemaName}`);
        this.rateSelectEl = document.getElementById(`rate-${this.schemaName}`);

        // Zoomed timeline elements
        this.zoomedContainerEl = document.getElementById(`zoomed-container-${this.schemaName}`);
        this.zoomedCanvasEl = document.getElementById(`zoomed-canvas-${this.schemaName}`);
        this.zoomedRangeEl = document.getElementById(`zoomed-range-${this.schemaName}`);
        this.zoomedSliderEl = document.getElementById(`zoomed-slider-${this.schemaName}`);
        this.zoomedLeftBtn = document.getElementById(`zoomed-left-${this.schemaName}`);
        this.zoomedRightBtn = document.getElementById(`zoomed-right-${this.schemaName}`);

        // Zoom state - zoomed view shows 10 seconds by default
        this.zoomedViewDuration = 10;  // Seconds visible in zoomed view
        this.zoomedViewStart = 0;  // Start time of zoomed view in seconds
        this.zoomedTimelineView = null;  // Will hold ZoomedTimelineView instance
    }

    /**
     * Initialize the annotation interface
     */
    async initialize() {
        tieredDebugLog('Initializing TieredAnnotationManager...');

        // Set up UI components first (before waiting for media)
        // This ensures the UI is responsive even if media fails to load
        this._setupTierSelector();
        this._setupLabelButtons();
        this._setupPlaybackControls();
        this._setupKeyboardShortcuts();

        // Initialize tier views (canvases)
        this._initializeTierViews();

        // Initialize zoomed timeline view
        this._initializeZoomedTimeline();

        // Update tier highlighting
        this._updateTierHighlighting();

        // Wait for instance data to be available (set by annotation.js)
        await this._waitForInstanceData();

        // Get media URL from instance data
        const mediaUrl = this._getMediaUrl();
        if (!mediaUrl) {
            console.warn('[TieredAnnotation] No media URL found for field:', this.sourceField);
            // Load existing annotations even without media
            this._loadExistingAnnotations();
            this._renderAllTiers();
            tieredDebugLog('TieredAnnotationManager initialized (no media)');
            return;
        }

        // Set media source
        console.log('[TieredAnnotation] Setting media source:', mediaUrl);
        this.mediaElement.src = mediaUrl;

        // Force load
        this.mediaElement.load();

        // Wait for media metadata
        try {
            await this._waitForMediaMetadata();
            console.log('[TieredAnnotation] Media loaded successfully, duration:', this.mediaMetadata.duration);
        } catch (error) {
            console.error('[TieredAnnotation] Failed to load media:', error);
            console.error('[TieredAnnotation] Media element state:', {
                src: this.mediaElement.src,
                readyState: this.mediaElement.readyState,
                networkState: this.mediaElement.networkState,
                error: this.mediaElement.error
            });
            // Continue anyway - UI should still be functional
        }

        // Set up media event listeners
        this._setupMediaEventListeners();

        // Initialize waveform (Peaks.js) if available
        await this._initializePeaks();

        // Load existing annotations from hidden input
        this._loadExistingAnnotations();

        // Render all tiers
        this._renderAllTiers();

        // Update time display
        this._updateTimeDisplay();

        // Initialize zoomed view with correct duration
        this._updateZoomedView();

        tieredDebugLog('TieredAnnotationManager initialized successfully');
    }

    /**
     * Wait for instance data to be available and fetch full data from API
     */
    async _waitForInstanceData(maxWaitMs = 5000) {
        const startTime = Date.now();

        // Wait for window.currentInstance to have an ID
        while (Date.now() - startTime < maxWaitMs) {
            if (window.currentInstance && window.currentInstance.id) {
                break;
            }
            await new Promise(r => setTimeout(r, 100));
        }

        // If we have the source field already, great
        if (window.currentInstance && window.currentInstance[this.sourceField]) {
            tieredDebugLog('Instance data available:', this.sourceField, '=', window.currentInstance[this.sourceField]);
            return true;
        }

        // Otherwise, fetch the full instance data from /api/current_instance
        // This endpoint now includes a 'data' field with all raw instance fields
        try {
            const response = await fetch('/api/current_instance');
            if (response.ok) {
                const result = await response.json();
                // The API returns { instance_id, current_index, total_instances, data: {...} }
                if (result && result.data && result.data[this.sourceField]) {
                    // Store in currentInstance for later use
                    if (!window.currentInstance) {
                        window.currentInstance = { id: result.instance_id };
                    }
                    window.currentInstance[this.sourceField] = result.data[this.sourceField];
                    tieredDebugLog('Fetched instance data from API:', this.sourceField, '=', result.data[this.sourceField]);
                    return true;
                }
            }
        } catch (e) {
            tieredDebugLog('Failed to fetch instance data from API:', e);
        }

        tieredDebugLog('Could not get instance data for field:', this.sourceField);
        return false;
    }

    /**
     * Convert external URL to use audio proxy for CORS bypass
     * This enables Peaks.js to generate waveforms from external audio files
     */
    _getProxiedUrl(url) {
        if (!url) return url;

        // If it's already a relative URL or data URL, return as-is
        if (url.startsWith('/') || url.startsWith('data:')) {
            return url;
        }

        // If it's an external URL (http/https), proxy it
        if (url.startsWith('http://') || url.startsWith('https://')) {
            const proxiedUrl = `/api/audio/proxy?url=${encodeURIComponent(url)}`;
            tieredDebugLog('Using audio proxy for external URL:', url, '->', proxiedUrl);
            return proxiedUrl;
        }

        return url;
    }

    /**
     * Get media URL from instance data
     * Returns proxied URL for external sources to enable CORS for waveform generation
     */
    _getMediaUrl() {
        let url = null;

        // Method 1: Try window.currentInstance (set by annotation.js)
        if (window.currentInstance && window.currentInstance[this.sourceField]) {
            tieredDebugLog('Found media URL in window.currentInstance:', this.sourceField);
            url = window.currentInstance[this.sourceField];
        }

        // Method 2: Look for instance data in the page's data attributes
        if (!url) {
            const instanceTextEl = document.getElementById('instance-text');
            if (instanceTextEl) {
                const camelKey = this.sourceField.replace(/_([a-z])/g, (g) => g[1].toUpperCase());
                url = instanceTextEl.dataset[camelKey] || instanceTextEl.dataset[this.sourceField];
                if (url) {
                    tieredDebugLog('Found media URL in instance-text dataset:', url);
                }
            }
        }

        // Method 3: Try finding a media element with the URL in display fields
        if (!url) {
            const displayFields = document.querySelectorAll('[data-field-name]');
            for (const field of displayFields) {
                if (field.dataset.fieldName === this.sourceField) {
                    const mediaEl = field.querySelector('audio, video');
                    if (mediaEl && mediaEl.src) {
                        url = mediaEl.src;
                        tieredDebugLog('Found media URL in display field media element:', url);
                        break;
                    }
                    if (field.dataset.url) {
                        url = field.dataset.url;
                        tieredDebugLog('Found media URL in display field data-url:', url);
                        break;
                    }
                    const text = field.textContent?.trim();
                    if (text && (text.startsWith('http') || text.startsWith('/'))) {
                        url = text;
                        tieredDebugLog('Found media URL in display field text:', url);
                        break;
                    }
                }
            }
        }

        // Method 4: Try direct attribute on container
        if (!url) {
            url = this.container.dataset.mediaUrl;
            if (url) {
                tieredDebugLog('Found media URL in container data-media-url:', url);
            }
        }

        // Method 5: Try looking for any audio/video element on the page
        if (!url) {
            const anyMedia = document.querySelector('audio[src], video[src]');
            if (anyMedia && anyMedia.src) {
                url = anyMedia.src;
                tieredDebugLog('Found media URL from existing media element:', url);
            }
        }

        if (!url) {
            tieredDebugLog('No media URL found for field:', this.sourceField);
            return null;
        }

        // Return proxied URL for external sources (enables CORS for waveform generation)
        return this._getProxiedUrl(url);
    }

    /**
     * Wait for media metadata to load
     */
    _waitForMediaMetadata() {
        return new Promise((resolve, reject) => {
            const checkMetadata = () => {
                if (this.mediaElement.readyState >= 1 && !isNaN(this.mediaElement.duration)) {
                    this.mediaMetadata.duration = this.mediaElement.duration;
                    console.log('[TieredAnnotation] Media metadata loaded, duration:', this.mediaMetadata.duration);
                    resolve();
                }
            };

            // Check immediately in case already loaded
            if (this.mediaElement.readyState >= 1 && !isNaN(this.mediaElement.duration)) {
                this.mediaMetadata.duration = this.mediaElement.duration;
                console.log('[TieredAnnotation] Media already loaded, duration:', this.mediaMetadata.duration);
                resolve();
                return;
            }

            this.mediaElement.addEventListener('loadedmetadata', checkMetadata);
            this.mediaElement.addEventListener('error', (e) => {
                const mediaError = this.mediaElement.error;
                const errorMsg = mediaError ? `Code ${mediaError.code}: ${mediaError.message}` : 'Unknown error';
                console.error('[TieredAnnotation] Media error:', errorMsg);
                reject(new Error('Failed to load media: ' + errorMsg));
            });

            // Also listen for canplay as backup
            this.mediaElement.addEventListener('canplay', () => {
                if (!isNaN(this.mediaElement.duration)) {
                    this.mediaMetadata.duration = this.mediaElement.duration;
                    console.log('[TieredAnnotation] Media canplay, duration:', this.mediaMetadata.duration);
                    resolve();
                }
            });

            // Timeout after 30 seconds
            setTimeout(() => {
                console.warn('[TieredAnnotation] Media load timeout, readyState:', this.mediaElement.readyState);
                reject(new Error('Media load timeout'));
            }, 30000);
        });
    }

    /**
     * Set up media element event listeners
     */
    _setupMediaEventListeners() {
        this.mediaElement.addEventListener('timeupdate', this._handleMediaTimeUpdate);

        this.mediaElement.addEventListener('play', () => {
            this.isPlaying = true;
            tieredDebugLog('Media playing');
        });

        this.mediaElement.addEventListener('pause', () => {
            this.isPlaying = false;
            tieredDebugLog('Media paused');
        });

        this.mediaElement.addEventListener('ended', () => {
            this.isPlaying = false;
            tieredDebugLog('Media ended');
        });
    }

    /**
     * Handle media time update
     */
    _handleMediaTimeUpdate() {
        this._updateTimeDisplay();

        // Re-render zoomed timeline view
        if (this.zoomedTimelineView) {
            this.zoomedTimelineView.render();
        }

        // Re-render all tier views so playheads update
        for (const tierName in this.tierViews) {
            this.tierViews[tierName].render();
        }

        // Auto-scroll zoomed view when playhead nears right edge
        if (this.isPlaying && this.mediaElement) {
            const currentTime = this.mediaElement.currentTime;
            const viewEnd = this.zoomedViewStart + this.zoomedViewDuration;
            // Scroll when playhead passes 90% of the visible window
            if (currentTime > this.zoomedViewStart + this.zoomedViewDuration * 0.9) {
                this.zoomedViewStart = currentTime - this.zoomedViewDuration * 0.1;
                const maxStart = Math.max(0, this.mediaMetadata.duration - this.zoomedViewDuration);
                this.zoomedViewStart = Math.min(maxStart, this.zoomedViewStart);
                this._updateZoomedView();
                this._updateZoomedSlider();
            }
        }
    }

    /**
     * Update time display
     */
    _updateTimeDisplay() {
        if (!this.timeDisplayEl) return;

        const currentTime = this.mediaElement.currentTime || 0;
        const duration = this.mediaMetadata.duration || 0;

        const currentTimeEl = this.timeDisplayEl.querySelector('.current-time');
        const totalTimeEl = this.timeDisplayEl.querySelector('.total-time');

        if (currentTimeEl) {
            currentTimeEl.textContent = this._formatTime(currentTime);
        }
        if (totalTimeEl) {
            totalTimeEl.textContent = this._formatTime(duration);
        }
    }

    /**
     * Format time as MM:SS.mmm
     */
    _formatTime(seconds) {
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        const ms = Math.floor((seconds % 1) * 1000);
        return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}.${ms.toString().padStart(3, '0')}`;
    }

    /**
     * Set up tier selector
     */
    _setupTierSelector() {
        if (!this.tierSelectEl) return;

        this.tierSelectEl.addEventListener('change', (e) => {
            this.setActiveTier(e.target.value);
        });

        // Set initial value
        if (this.activeTier) {
            this.tierSelectEl.value = this.activeTier;
        }
    }

    /**
     * Set active tier
     */
    setActiveTier(tierName) {
        const tier = this.config.tiers.find(t => t.name === tierName);
        if (!tier) {
            console.warn('[TieredAnnotation] Unknown tier:', tierName);
            return;
        }

        this.activeTier = tierName;
        this.activeLabel = tier.labels?.[0]?.name || null;

        // Update tier selector
        if (this.tierSelectEl) {
            this.tierSelectEl.value = tierName;
        }

        // Update label buttons
        this._setupLabelButtons();

        // Update tier row highlighting
        this._updateTierHighlighting();

        tieredDebugLog('Active tier set to:', tierName);
    }

    /**
     * Update tier row highlighting
     */
    _updateTierHighlighting() {
        const tierRows = this.tierRowsEl?.querySelectorAll('.tier-row');
        if (!tierRows) return;

        tierRows.forEach(row => {
            const tierName = row.dataset.tier;
            row.classList.toggle('active', tierName === this.activeTier);
        });
    }

    /**
     * Set up label buttons for current tier
     */
    _setupLabelButtons() {
        if (!this.labelsEl) return;

        const tier = this.config.tiers.find(t => t.name === this.activeTier);
        if (!tier) return;

        this.labelsEl.innerHTML = '';

        for (const label of (tier.labels || [])) {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'btn btn-sm label-button';
            button.dataset.label = label.name;
            button.textContent = label.name;
            button.style.backgroundColor = label.color || '#cccccc';
            button.style.color = this._getContrastColor(label.color || '#cccccc');
            button.style.borderColor = label.color || '#cccccc';

            if (label.name === this.activeLabel) {
                button.classList.add('active');
            }

            button.addEventListener('click', () => {
                this.setActiveLabel(label.name);
            });

            if (label.tooltip || label.description) {
                button.title = label.tooltip || label.description;
            }

            this.labelsEl.appendChild(button);
        }
    }

    /**
     * Set active label
     */
    setActiveLabel(labelName) {
        this.activeLabel = labelName;

        // Update button highlighting
        const buttons = this.labelsEl?.querySelectorAll('.label-button');
        buttons?.forEach(btn => {
            btn.classList.toggle('active', btn.dataset.label === labelName);
        });

        tieredDebugLog('Active label set to:', labelName);
    }

    /**
     * Get contrasting color for text
     */
    _getContrastColor(hexColor) {
        const rgb = parseInt(hexColor.slice(1), 16);
        const r = (rgb >> 16) & 0xff;
        const g = (rgb >> 8) & 0xff;
        const b = rgb & 0xff;
        const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
        return luminance > 0.5 ? '#000000' : '#ffffff';
    }

    /**
     * Set up playback controls
     */
    _setupPlaybackControls() {
        // Playback rate
        if (this.rateSelectEl) {
            this.rateSelectEl.addEventListener('change', (e) => {
                this.mediaElement.playbackRate = parseFloat(e.target.value);
            });
        }

        // Zoom controls
        const zoomInBtn = document.getElementById(`zoom-in-${this.schemaName}`);
        const zoomOutBtn = document.getElementById(`zoom-out-${this.schemaName}`);
        const zoomFitBtn = document.getElementById(`zoom-fit-${this.schemaName}`);

        if (zoomInBtn) {
            zoomInBtn.addEventListener('click', () => this._zoomIn());
        }
        if (zoomOutBtn) {
            zoomOutBtn.addEventListener('click', () => this._zoomOut());
        }
        if (zoomFitBtn) {
            zoomFitBtn.addEventListener('click', () => this._zoomFit());
        }

        // Annotation list toggle
        const listToggleBtn = document.getElementById(`list-toggle-${this.schemaName}`);
        if (listToggleBtn) {
            listToggleBtn.addEventListener('click', () => {
                this.annotationListEl?.classList.toggle('collapsed');
                const icon = listToggleBtn.querySelector('i');
                if (icon) {
                    icon.classList.toggle('fa-chevron-down');
                    icon.classList.toggle('fa-chevron-up');
                }
            });
        }
    }

    /**
     * Set up keyboard shortcuts
     */
    _setupKeyboardShortcuts() {
        this.container.addEventListener('keydown', this._handleKeydown);

        // Make container focusable
        if (!this.container.hasAttribute('tabindex')) {
            this.container.setAttribute('tabindex', '0');
        }
    }

    /**
     * Handle keyboard events
     */
    _handleKeydown(e) {
        // Ignore if typing in an input
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') {
            return;
        }

        switch (e.key) {
            case ' ':
                e.preventDefault();
                this._togglePlayPause();
                break;

            case ',':
                e.preventDefault();
                this._stepBackward();
                break;

            case '.':
                e.preventDefault();
                this._stepForward();
                break;

            case 'Delete':
            case 'Backspace':
                if (this.selectedAnnotation) {
                    e.preventDefault();
                    this.deleteAnnotation(this.selectedAnnotation.id);
                }
                break;

            case 'Escape':
                e.preventDefault();
                this.deselectAnnotation();
                break;
        }
    }

    /**
     * Toggle play/pause
     */
    _togglePlayPause() {
        if (this.mediaElement.paused) {
            this.mediaElement.play();
        } else {
            this.mediaElement.pause();
        }
    }

    /**
     * Step backward by a small amount
     */
    _stepBackward() {
        this.mediaElement.currentTime = Math.max(0, this.mediaElement.currentTime - 0.1);
    }

    /**
     * Step forward by a small amount
     */
    _stepForward() {
        this.mediaElement.currentTime = Math.min(
            this.mediaMetadata.duration,
            this.mediaElement.currentTime + 0.1
        );
    }

    /**
     * Zoom in on the timeline
     */
    _zoomIn() {
        if (this.peaks) {
            const view = this.peaks.views.getView('zoomview');
            if (view) {
                try {
                    // Get current zoom level and reduce (more zoomed in)
                    const currentZoom = view.getZoom();
                    const newZoom = Math.max(256, Math.floor(currentZoom.scale * 0.5));
                    view.setZoom({ scale: newZoom });
                    this._renderAllTiers();
                    tieredDebugLog('Zoomed in to scale:', newZoom);
                } catch (e) {
                    console.warn('[TieredAnnotation] Zoom in error:', e);
                }
            }
        }
    }

    /**
     * Zoom out on the timeline
     */
    _zoomOut() {
        if (this.peaks) {
            const view = this.peaks.views.getView('zoomview');
            if (view) {
                try {
                    // Get current zoom level and increase (more zoomed out)
                    const currentZoom = view.getZoom();
                    const newZoom = Math.min(4096, Math.floor(currentZoom.scale * 2));
                    view.setZoom({ scale: newZoom });
                    this._renderAllTiers();
                    tieredDebugLog('Zoomed out to scale:', newZoom);
                } catch (e) {
                    console.warn('[TieredAnnotation] Zoom out error:', e);
                }
            }
        }
    }

    /**
     * Fit timeline to view the entire media
     */
    _zoomFit() {
        if (this.peaks) {
            const view = this.peaks.views.getView('zoomview');
            if (view) {
                try {
                    // Set zoom to fit entire duration
                    view.setZoom({ seconds: this.mediaMetadata.duration || 60 });
                    this._renderAllTiers();
                    tieredDebugLog('Zoomed to fit');
                } catch (e) {
                    console.warn('[TieredAnnotation] Zoom fit error:', e);
                }
            }
        }
    }

    /**
     * Get current view start/end times from Peaks.js zoomview
     */
    _getViewTimes() {
        if (this.peaks) {
            const view = this.peaks.views.getView('zoomview');
            if (view) {
                try {
                    const startTime = view.getStartTime();
                    const endTime = view.getEndTime();
                    return { startTime, endTime };
                } catch (e) {
                    // Fallback
                }
            }
        }
        return { startTime: 0, endTime: this.mediaMetadata.duration || 60 };
    }

    /**
     * Initialize tier views
     */
    _initializeTierViews() {
        for (const tier of this.config.tiers) {
            const canvas = document.getElementById(`tier-canvas-${this.schemaName}-${tier.name}`);
            if (canvas) {
                this.tierViews[tier.name] = new TierView(this, tier, canvas);
            }
        }
    }

    /**
     * Initialize zoomed timeline view
     */
    _initializeZoomedTimeline() {
        if (!this.zoomedCanvasEl) {
            tieredDebugLog('No zoomed canvas element found');
            return;
        }

        // Create zoomed timeline view
        this.zoomedTimelineView = new ZoomedTimelineView(this, this.zoomedCanvasEl);

        // Set up slider
        if (this.zoomedSliderEl) {
            this.zoomedSliderEl.addEventListener('input', (e) => {
                const percent = parseFloat(e.target.value) / 100;
                const maxStart = Math.max(0, this.mediaMetadata.duration - this.zoomedViewDuration);
                this.zoomedViewStart = percent * maxStart;
                this._updateZoomedView();
            });
        }

        // Set up navigation buttons
        if (this.zoomedLeftBtn) {
            this.zoomedLeftBtn.addEventListener('click', () => {
                this.zoomedViewStart = Math.max(0, this.zoomedViewStart - this.zoomedViewDuration / 2);
                this._updateZoomedView();
                this._updateZoomedSlider();
            });
        }

        if (this.zoomedRightBtn) {
            this.zoomedRightBtn.addEventListener('click', () => {
                const maxStart = Math.max(0, this.mediaMetadata.duration - this.zoomedViewDuration);
                this.zoomedViewStart = Math.min(maxStart, this.zoomedViewStart + this.zoomedViewDuration / 2);
                this._updateZoomedView();
                this._updateZoomedSlider();
            });
        }

        tieredDebugLog('Zoomed timeline initialized');
    }

    /**
     * Update zoomed view rendering
     */
    _updateZoomedView() {
        if (this.zoomedTimelineView) {
            this.zoomedTimelineView.render();
        }

        // Re-render all tier views so playheads update
        for (const tierName in this.tierViews) {
            this.tierViews[tierName].render();
        }

        // Update range display
        if (this.zoomedRangeEl) {
            const startTime = this._formatTime(this.zoomedViewStart);
            const endTime = this._formatTime(this.zoomedViewStart + this.zoomedViewDuration);
            this.zoomedRangeEl.textContent = `${startTime} - ${endTime}`;
        }

        // Sync Peaks.js zoomview to match our zoomed view range
        if (this.peaks) {
            // Mark timestamp to prevent zoomview.displaying from causing infinite loop
            this._lastZoomSyncTime = performance.now();
            const zoomview = this.peaks.views.getView('zoomview');
            if (zoomview) {
                try {
                    // Set zoom level to show exactly zoomedViewDuration seconds
                    zoomview.setZoom({ seconds: this.zoomedViewDuration });
                    // Seek to the start of our zoomed view
                    zoomview.setStartTime(this.zoomedViewStart);
                } catch (e) {
                    tieredDebugLog('Could not sync Peaks.js zoomview:', e);
                }
            }
        }
    }

    /**
     * Update zoomed slider position
     */
    _updateZoomedSlider() {
        if (!this.zoomedSliderEl || !this.mediaMetadata.duration) return;

        const maxStart = Math.max(0, this.mediaMetadata.duration - this.zoomedViewDuration);
        const percent = maxStart > 0 ? (this.zoomedViewStart / maxStart) * 100 : 0;
        this.zoomedSliderEl.value = percent;
    }

    /**
     * Center zoomed view on current playback position
     */
    centerZoomedViewOnPlayhead() {
        const currentTime = this.mediaElement.currentTime;
        const halfView = this.zoomedViewDuration / 2;
        const maxStart = Math.max(0, this.mediaMetadata.duration - this.zoomedViewDuration);

        this.zoomedViewStart = Math.max(0, Math.min(maxStart, currentTime - halfView));
        this._updateZoomedView();
        this._updateZoomedSlider();
    }

    /**
     * Initialize Peaks.js for waveform visualization
     */
    async _initializePeaks() {
        // peaks.min.js registers as window.peaks (lowercase)
        const PeaksLib = window.peaks || window.Peaks;
        if (!PeaksLib) {
            console.warn('[TieredAnnotation] Peaks.js not available');
            return;
        }

        if (!this.overviewEl && !this.zoomviewEl) {
            tieredDebugLog('No waveform containers, skipping Peaks.js');
            return;
        }

        try {
            const options = {
                mediaElement: this.mediaElement,
                webAudio: {
                    audioContext: new (window.AudioContext || window.webkitAudioContext)()
                },
                keyboard: false, // We handle keyboard shortcuts ourselves
                zoomLevels: [256, 512, 1024, 2048, 4096],
                segments: []
            };

            // Add overview container if available
            if (this.overviewEl) {
                options.overview = {
                    container: this.overviewEl,
                    waveformColor: 'rgba(74, 144, 217, 0.5)',
                    playedWaveformColor: 'rgba(74, 144, 217, 0.8)',
                    playheadColor: '#1f77b4',
                    highlightColor: 'rgba(255, 255, 255, 0.5)',
                    highlightOffset: 1
                };
            }

            // Add zoomview container if available (for fine-grained control)
            if (this.zoomviewEl) {
                console.log('[TieredAnnotation] Adding zoomview container:', this.zoomviewEl.id);
                options.zoomview = {
                    container: this.zoomviewEl,
                    waveformColor: 'rgba(74, 144, 217, 0.7)',
                    playedWaveformColor: 'rgba(74, 144, 217, 1.0)',
                    playheadColor: '#1f77b4',
                    axisGridlineColor: '#ccc',
                    axisLabelColor: '#666',
                    fontFamily: 'inherit',
                    fontSize: 11,
                    fontStyle: 'normal'
                };
            } else {
                console.log('[TieredAnnotation] No zoomview container found');
            }

            console.log('[TieredAnnotation] Initializing Peaks.js with options:', {
                hasOverview: !!options.overview,
                hasZoomview: !!options.zoomview,
                mediaSrc: this.mediaElement?.src
            });

            this.peaks = await new Promise((resolve, reject) => {
                PeaksLib.init(options, (err, peaks) => {
                    if (err) {
                        console.error('[TieredAnnotation] Peaks.init error:', err);
                        reject(err);
                    } else {
                        console.log('[TieredAnnotation] Peaks.js initialized successfully');
                        resolve(peaks);
                    }
                });
            });

            // Set up Peaks.js event listeners for segment interactions
            this._setupPeaksEventListeners();

            // Enable auto-scroll during playback and set initial zoom
            const zoomviewInstance = this.peaks.views.getView('zoomview');
            if (zoomviewInstance) {
                try {
                    zoomviewInstance.enableAutoScroll(true);
                    zoomviewInstance.setZoom({ seconds: this.zoomedViewDuration });
                    zoomviewInstance.setStartTime(0);
                } catch (e) {
                    tieredDebugLog('Could not configure zoomview:', e);
                }
            }

            // Peaks.js reads container width at init time, which may be
            // incorrect if layout hasn't fully settled. Refit after a frame.
            requestAnimationFrame(() => {
                this._fitPeaksToContainer();
            });

            // Refit on window resize
            window.addEventListener('resize', () => {
                this._fitPeaksToContainer();
            });

            tieredDebugLog('Peaks.js initialized with overview and zoomview');
        } catch (error) {
            console.warn('[TieredAnnotation] Failed to initialize Peaks.js:', error);
        }
    }

    /**
     * Resize Peaks.js canvases to fill their containers.
     * Called after init (layout may not be settled) and on window resize.
     */
    _fitPeaksToContainer() {
        if (!this.peaks) return;
        const overview = this.peaks.views.getView('overview');
        if (overview) {
            try { overview.fitToContainer(); } catch (e) { /* ignore */ }
        }
        const zoomview = this.peaks.views.getView('zoomview');
        if (zoomview) {
            try { zoomview.fitToContainer(); } catch (e) { /* ignore */ }
        }
    }

    /**
     * Set up Peaks.js event listeners for segment interactions
     */
    _setupPeaksEventListeners() {
        if (!this.peaks) return;

        // Listen for segment click
        this.peaks.on('segments.click', (event) => {
            tieredDebugLog('Segment clicked:', event.segment.id);
            this.selectAnnotation(event.segment.id);
        });

        // Listen for segment drag end (resize/move)
        this.peaks.on('segments.dragend', (event) => {
            tieredDebugLog('Segment drag ended:', event.segment.id, event.segment.startTime, event.segment.endTime);
            this._onSegmentDragEnd(event.segment);
        });

        // Double-click on zoomview to seek
        const zoomview = this.peaks.views.getView('zoomview');
        if (zoomview) {
            zoomview.on('dblclick', (event) => {
                tieredDebugLog('Zoomview double-click at time:', event.time);
                this.mediaElement.currentTime = event.time;
            });
        }

        // Click on overview to navigate zoomed view and seek
        const overview = this.peaks.views.getView('overview');
        if (overview) {
            overview.on('click', (event) => {
                tieredDebugLog('Overview click at time:', event.time);
                // Center zoomed view on clicked time
                this.zoomedViewStart = Math.max(0, event.time - this.zoomedViewDuration / 2);
                const maxStart = Math.max(0, this.mediaMetadata.duration - this.zoomedViewDuration);
                this.zoomedViewStart = Math.min(maxStart, this.zoomedViewStart);
                this.mediaElement.currentTime = event.time;
                this._updateZoomedView();
                this._updateZoomedSlider();
            });
            overview.on('dblclick', (event) => {
                tieredDebugLog('Overview double-click at time:', event.time);
                this.mediaElement.currentTime = event.time;
            });
        }

        // Sync when Peaks.js auto-scrolls the zoomview during playback
        this._lastZoomSyncTime = 0;
        this.peaks.on('zoomview.displaying', (startTime, endTime) => {
            // Avoid infinite loops: only sync if change came from Peaks.js (not from our own _updateZoomedView)
            const now = performance.now();
            if (now - this._lastZoomSyncTime < 100) return;

            const newDuration = endTime - startTime;
            if (Math.abs(this.zoomedViewStart - startTime) > 0.1 || Math.abs(this.zoomedViewDuration - newDuration) > 0.1) {
                this.zoomedViewStart = startTime;
                this.zoomedViewDuration = newDuration;
                // Update range display and slider without triggering Peaks.js sync
                if (this.zoomedRangeEl) {
                    const startFmt = this._formatTime(this.zoomedViewStart);
                    const endFmt = this._formatTime(this.zoomedViewStart + this.zoomedViewDuration);
                    this.zoomedRangeEl.textContent = `${startFmt} - ${endFmt}`;
                }
                this._updateZoomedSlider();
                // Re-render zoomed timeline and tier views
                if (this.zoomedTimelineView) {
                    this.zoomedTimelineView.render();
                }
                for (const tierName in this.tierViews) {
                    this.tierViews[tierName].render();
                }
            }
        });
    }

    /**
     * Handle segment drag end - update annotation times
     */
    _onSegmentDragEnd(segment) {
        const annotationId = segment.id;

        // Find and update the annotation
        for (const tierName in this.annotations) {
            const annIndex = this.annotations[tierName].findIndex(a => a.id === annotationId);
            if (annIndex !== -1) {
                const annotation = this.annotations[tierName][annIndex];
                const tier = this.config.tiers.find(t => t.name === tierName);

                // Convert to milliseconds for storage
                const newStartMs = segment.startTime * 1000;
                const newEndMs = segment.endTime * 1000;

                // Validate constraints for dependent tiers
                if (tier && tier.tier_type === 'dependent') {
                    const parentAnnotation = this._findParentAnnotation(
                        tier.parent_tier,
                        segment.startTime,
                        segment.endTime
                    );

                    if (!parentAnnotation) {
                        // Revert the segment to original position
                        this.peaks.segments.removeById(annotationId);
                        this._addSegmentToPeaks(annotation);
                        this._showError(`Cannot move: No parent annotation covers this time range`);
                        return;
                    }

                    const validation = this._validateConstraints(
                        tier,
                        segment.startTime,
                        segment.endTime,
                        parentAnnotation
                    );

                    if (!validation.valid) {
                        // Revert the segment
                        this.peaks.segments.removeById(annotationId);
                        this._addSegmentToPeaks(annotation);
                        this._showError(validation.error);
                        return;
                    }

                    // Update parent reference if needed
                    annotation.parent_id = parentAnnotation.id;
                }

                // Update annotation
                annotation.start_time = newStartMs;
                annotation.end_time = newEndMs;

                // Re-render tier canvas
                if (this.tierViews[tierName]) {
                    this.tierViews[tierName].render();
                }

                this._renderAnnotationList();
                this._saveData();

                tieredDebugLog('Updated annotation times:', annotationId, newStartMs, newEndMs);
                return;
            }
        }
    }

    /**
     * Add a segment to Peaks.js
     */
    _addSegmentToPeaks(annotation) {
        if (!this.peaks) return;

        this.peaks.segments.add({
            id: annotation.id,
            startTime: annotation.start_time / 1000,  // Convert ms to seconds
            endTime: annotation.end_time / 1000,
            labelText: annotation.label,
            color: annotation.color || '#4ECDC4',
            editable: true  // Allow dragging/resizing
        });
    }

    /**
     * Sync all annotations to Peaks.js segments
     */
    _syncAnnotationsToPeaks() {
        if (!this.peaks) return;

        // Clear existing segments
        this.peaks.segments.removeAll();

        // Add all annotations as segments
        for (const tierName in this.annotations) {
            for (const annotation of this.annotations[tierName]) {
                this._addSegmentToPeaks(annotation);
            }
        }

        tieredDebugLog('Synced annotations to Peaks.js segments');
    }

    /**
     * Load existing annotations from hidden input
     */
    _loadExistingAnnotations() {
        if (!this.inputEl || !this.inputEl.value) {
            tieredDebugLog('No existing annotations to load');
            return;
        }

        try {
            const data = JSON.parse(this.inputEl.value);
            if (data.annotations) {
                for (const tierName in data.annotations) {
                    if (this.annotations.hasOwnProperty(tierName)) {
                        this.annotations[tierName] = data.annotations[tierName].map(ann => ({
                            ...ann,
                            id: ann.id || this._generateId()
                        }));
                    }
                }
                tieredDebugLog('Loaded existing annotations:', data.annotations);

                // Sync to Peaks.js for interactive editing
                this._syncAnnotationsToPeaks();
            }
        } catch (error) {
            console.warn('[TieredAnnotation] Failed to parse existing annotations:', error);
        }
    }

    /**
     * Render all tier views
     */
    _renderAllTiers() {
        for (const tierName in this.tierViews) {
            this.tierViews[tierName].render();
        }
        this._renderAnnotationList();
    }

    /**
     * Generate unique annotation ID
     */
    _generateId() {
        return `ann_${Date.now()}_${(++this.annotationCounter).toString(36)}`;
    }

    /**
     * Create a new annotation
     */
    createAnnotation(tierName, startTime, endTime, label) {
        const tier = this.config.tiers.find(t => t.name === tierName);
        if (!tier) {
            console.error('[TieredAnnotation] Unknown tier:', tierName);
            return null;
        }

        // For dependent tiers, find parent annotation
        let parentAnnotation = null;
        if (tier.tier_type === 'dependent') {
            parentAnnotation = this._findParentAnnotation(tier.parent_tier, startTime, endTime);
            if (!parentAnnotation) {
                this._showError(`No parent annotation in '${tier.parent_tier}' covers this time range`);
                return null;
            }
        }

        // Validate constraints
        const validation = this._validateConstraints(tier, startTime, endTime, parentAnnotation);
        if (!validation.valid) {
            this._showError(validation.error);
            return null;
        }

        // Get label data
        const labelData = tier.labels?.find(l => l.name === label);
        const color = labelData?.color || '#cccccc';

        // Create annotation object
        const annotation = {
            id: this._generateId(),
            tier: tierName,
            start_time: startTime * 1000, // Convert to milliseconds
            end_time: endTime * 1000,
            label: label,
            color: color,
            parent_id: parentAnnotation?.id || null,
            value: ''
        };

        // Add to annotations
        this.annotations[tierName].push(annotation);

        // Add to Peaks.js for interactive editing
        this._addSegmentToPeaks(annotation);

        // Re-render affected tier
        if (this.tierViews[tierName]) {
            this.tierViews[tierName].render();
        }

        // Update annotation list
        this._renderAnnotationList();

        // Save data
        this._saveData();

        tieredDebugLog('Created annotation:', annotation);
        return annotation;
    }

    /**
     * Find parent annotation that contains the given time range
     */
    _findParentAnnotation(parentTierName, startTime, endTime) {
        const parentAnnotations = this.annotations[parentTierName] || [];
        const startMs = startTime * 1000;
        const endMs = endTime * 1000;

        for (const parent of parentAnnotations) {
            if (parent.start_time <= startMs && parent.end_time >= endMs) {
                return parent;
            }
        }

        return null;
    }

    /**
     * Validate annotation constraints
     */
    _validateConstraints(tier, startTime, endTime, parentAnnotation) {
        if (tier.tier_type === 'independent') {
            return { valid: true };
        }

        if (!parentAnnotation) {
            return { valid: false, error: 'Parent annotation required for dependent tier' };
        }

        const startMs = startTime * 1000;
        const endMs = endTime * 1000;
        const constraint = tier.constraint_type;

        if (constraint === 'time_subdivision' || constraint === 'included_in') {
            if (startMs < parentAnnotation.start_time || endMs > parentAnnotation.end_time) {
                return {
                    valid: false,
                    error: 'Annotation must be within parent time bounds'
                };
            }
        }

        return { valid: true };
    }

    /**
     * Delete an annotation
     */
    deleteAnnotation(annotationId) {
        // Find annotation
        let annotation = null;
        let tierName = null;

        for (const tn in this.annotations) {
            const ann = this.annotations[tn].find(a => a.id === annotationId);
            if (ann) {
                annotation = ann;
                tierName = tn;
                break;
            }
        }

        if (!annotation) {
            console.warn('[TieredAnnotation] Annotation not found:', annotationId);
            return false;
        }

        // Remove children first (cascade delete)
        const childTiers = this.config.tiers.filter(t => t.parent_tier === tierName);
        for (const childTier of childTiers) {
            const childAnnotations = this.annotations[childTier.name].filter(
                a => a.parent_id === annotationId
            );
            for (const child of childAnnotations) {
                this.deleteAnnotation(child.id);
            }
        }

        // Remove from Peaks.js
        if (this.peaks) {
            try {
                this.peaks.segments.removeById(annotationId);
            } catch (e) {
                // Segment might not exist in Peaks
            }
        }

        // Remove annotation
        this.annotations[tierName] = this.annotations[tierName].filter(
            a => a.id !== annotationId
        );

        // Clear selection if this was selected
        if (this.selectedAnnotation?.id === annotationId) {
            this.selectedAnnotation = null;
        }

        // Re-render
        if (this.tierViews[tierName]) {
            this.tierViews[tierName].render();
        }
        this._renderAnnotationList();

        // Save data
        this._saveData();

        tieredDebugLog('Deleted annotation:', annotationId);
        return true;
    }

    /**
     * Select an annotation
     */
    selectAnnotation(annotationId) {
        // Find annotation
        let annotation = null;
        for (const tierName in this.annotations) {
            annotation = this.annotations[tierName].find(a => a.id === annotationId);
            if (annotation) break;
        }

        if (!annotation) {
            console.warn('[TieredAnnotation] Annotation not found:', annotationId);
            return;
        }

        this.selectedAnnotation = annotation;
        this._renderAllTiers();

        // Seek to annotation start
        this.mediaElement.currentTime = annotation.start_time / 1000;

        tieredDebugLog('Selected annotation:', annotationId);
    }

    /**
     * Deselect current annotation
     */
    deselectAnnotation() {
        this.selectedAnnotation = null;
        this._renderAllTiers();
    }

    /**
     * Update an annotation
     */
    updateAnnotation(annotationId, updates) {
        // Find annotation
        for (const tierName in this.annotations) {
            const annIndex = this.annotations[tierName].findIndex(a => a.id === annotationId);
            if (annIndex !== -1) {
                Object.assign(this.annotations[tierName][annIndex], updates);

                // Re-render
                if (this.tierViews[tierName]) {
                    this.tierViews[tierName].render();
                }
                this._renderAnnotationList();
                this._saveData();

                tieredDebugLog('Updated annotation:', annotationId, updates);
                return true;
            }
        }
        return false;
    }

    /**
     * Render annotation list panel
     */
    _renderAnnotationList() {
        if (!this.annotationListEl) return;

        this.annotationListEl.innerHTML = '';

        // Group by tier
        for (const tier of this.config.tiers) {
            const tierAnnotations = this.annotations[tier.name] || [];
            if (tierAnnotations.length === 0) continue;

            // Tier header
            const header = document.createElement('div');
            header.className = 'annotation-list-tier-header';
            header.textContent = `${tier.name} (${tierAnnotations.length})`;
            this.annotationListEl.appendChild(header);

            // Sort by start time
            const sorted = [...tierAnnotations].sort((a, b) => a.start_time - b.start_time);

            for (const ann of sorted) {
                const item = document.createElement('div');
                item.className = 'annotation-list-item';
                if (this.selectedAnnotation?.id === ann.id) {
                    item.classList.add('selected');
                }

                item.innerHTML = `
                    <span class="annotation-color" style="background-color: ${ann.color}"></span>
                    <span class="annotation-label">${this._escapeHtml(ann.label)}</span>
                    <span class="annotation-time">
                        ${this._formatTime(ann.start_time / 1000)} - ${this._formatTime(ann.end_time / 1000)}
                    </span>
                    <button type="button" class="annotation-delete-btn" title="Delete">
                        <i class="fas fa-times"></i>
                    </button>
                `;

                item.addEventListener('click', (e) => {
                    if (!e.target.closest('.annotation-delete-btn')) {
                        this.selectAnnotation(ann.id);
                    }
                });

                item.querySelector('.annotation-delete-btn')?.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.deleteAnnotation(ann.id);
                });

                this.annotationListEl.appendChild(item);
            }
        }
    }

    /**
     * Save data to hidden input
     */
    _saveData() {
        if (!this.inputEl) return;

        const data = this.serialize();
        this.inputEl.value = JSON.stringify(data);

        tieredDebugLog('Saved data:', data);
    }

    /**
     * Serialize annotations for storage
     */
    serialize() {
        return {
            annotations: this.annotations,
            time_slots: this._generateTimeSlots()
        };
    }

    /**
     * Generate ELAN-style time slots
     */
    _generateTimeSlots() {
        const times = new Set();

        for (const tierName in this.annotations) {
            for (const ann of this.annotations[tierName]) {
                if (ann.start_time != null) times.add(Math.round(ann.start_time));
                if (ann.end_time != null) times.add(Math.round(ann.end_time));
            }
        }

        const sortedTimes = Array.from(times).sort((a, b) => a - b);
        const slots = {};
        sortedTimes.forEach((time, i) => {
            slots[`ts${i + 1}`] = time;
        });

        return slots;
    }

    /**
     * Show error message
     */
    _showError(message) {
        console.error('[TieredAnnotation]', message);
        // Could show a toast/modal here
        alert(message);
    }

    /**
     * Escape HTML
     */
    _escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}


/**
 * TierView - Handles rendering for a single tier
 */
class TierView {
    constructor(manager, tierConfig, canvas) {
        this.manager = manager;
        this.tierConfig = tierConfig;
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');

        // Resize handle state
        this.HANDLE_WIDTH = 8;  // Width of resize handles in pixels
        this.dragState = null;  // { type: 'resize-start'|'resize-end'|'move', annotation, startX, origStart, origEnd }
        this.hoveredHandle = null;  // { annotation, type: 'start'|'end'|'body' }

        this._resizeCanvas();
        this._setupEventListeners();
    }

    /**
     * Resize canvas to match container
     */
    _resizeCanvas() {
        const container = this.canvas.parentElement;
        if (!container) return;

        // Set canvas size
        this.canvas.width = container.offsetWidth;
        this.canvas.height = container.offsetHeight;
    }

    /**
     * Set up event listeners
     */
    _setupEventListeners() {
        // Handle window resize
        window.addEventListener('resize', () => {
            this._resizeCanvas();
            this.render();
        });

        // Mouse events for creating/selecting/resizing annotations
        this.canvas.addEventListener('mousedown', (e) => this._handleMouseDown(e));
        this.canvas.addEventListener('mousemove', (e) => this._handleMouseMove(e));
        this.canvas.addEventListener('mouseup', (e) => this._handleMouseUp(e));
        this.canvas.addEventListener('mouseleave', (e) => this._handleMouseLeave(e));
        this.canvas.addEventListener('dblclick', (e) => this._handleDoubleClick(e));
    }

    /**
     * Get what part of an annotation the mouse is over
     * Returns: { annotation, type: 'start'|'end'|'body' } or null
     */
    _getAnnotationPartAtPosition(x, y) {
        const annotations = this.manager.annotations[this.tierConfig.name] || [];

        for (const ann of annotations) {
            const x1 = this._timeToX(ann.start_time / 1000);
            const x2 = this._timeToX(ann.end_time / 1000);

            // Check if within annotation bounds vertically
            if (y < 4 || y > this.canvas.height - 4) continue;

            // Check start handle
            if (x >= x1 - 2 && x <= x1 + this.HANDLE_WIDTH) {
                return { annotation: ann, type: 'start' };
            }

            // Check end handle
            if (x >= x2 - this.HANDLE_WIDTH && x <= x2 + 2) {
                return { annotation: ann, type: 'end' };
            }

            // Check body (for move/select)
            if (x > x1 + this.HANDLE_WIDTH && x < x2 - this.HANDLE_WIDTH) {
                return { annotation: ann, type: 'body' };
            }
        }

        return null;
    }

    /**
     * Update cursor based on what's being hovered
     */
    _updateCursor() {
        if (this.dragState) {
            // Keep current cursor during drag
            return;
        }

        if (!this.hoveredHandle) {
            this.canvas.style.cursor = 'crosshair';
            return;
        }

        switch (this.hoveredHandle.type) {
            case 'start':
            case 'end':
                this.canvas.style.cursor = 'ew-resize';
                break;
            case 'body':
                this.canvas.style.cursor = 'move';
                break;
            default:
                this.canvas.style.cursor = 'crosshair';
        }
    }

    /**
     * Handle mouse down
     */
    _handleMouseDown(e) {
        if (this.manager.activeTier !== this.tierConfig.name) {
            // Switch to this tier
            this.manager.setActiveTier(this.tierConfig.name);
        }

        const x = e.offsetX;
        const y = e.offsetY;

        // Check if clicking on an annotation part (handle or body)
        const part = this._getAnnotationPartAtPosition(x, y);

        if (part) {
            this.manager.selectAnnotation(part.annotation.id);

            if (part.type === 'start') {
                // Start resizing from start handle
                this.dragState = {
                    type: 'resize-start',
                    annotation: part.annotation,
                    startX: x,
                    origStart: part.annotation.start_time,
                    origEnd: part.annotation.end_time
                };
                this.canvas.style.cursor = 'ew-resize';
            } else if (part.type === 'end') {
                // Start resizing from end handle
                this.dragState = {
                    type: 'resize-end',
                    annotation: part.annotation,
                    startX: x,
                    origStart: part.annotation.start_time,
                    origEnd: part.annotation.end_time
                };
                this.canvas.style.cursor = 'ew-resize';
            } else if (part.type === 'body') {
                // Start moving the annotation
                this.dragState = {
                    type: 'move',
                    annotation: part.annotation,
                    startX: x,
                    origStart: part.annotation.start_time,
                    origEnd: part.annotation.end_time
                };
                this.canvas.style.cursor = 'move';
            }
            return;
        }

        // Not on an annotation - start creating a new one
        const time = this._xToTime(x);
        this.manager.selectionStart = time;
        this.manager.isDragging = true;
    }

    /**
     * Handle mouse move
     */
    _handleMouseMove(e) {
        const x = e.offsetX;
        const y = e.offsetY;

        // If dragging/resizing an annotation
        if (this.dragState) {
            const deltaX = x - this.dragState.startX;
            const deltaTime = this._xToTime(deltaX) * 1000;  // Convert to ms
            const ann = this.dragState.annotation;

            if (this.dragState.type === 'resize-start') {
                // Resize from start
                let newStart = this.dragState.origStart + deltaTime;
                // Ensure start doesn't go past end (minimum 50ms)
                newStart = Math.min(newStart, this.dragState.origEnd - 50);
                // Ensure start doesn't go negative
                newStart = Math.max(0, newStart);
                ann.start_time = newStart;
            } else if (this.dragState.type === 'resize-end') {
                // Resize from end
                let newEnd = this.dragState.origEnd + deltaTime;
                // Ensure end doesn't go before start (minimum 50ms)
                newEnd = Math.max(newEnd, this.dragState.origStart + 50);
                // Ensure end doesn't exceed duration
                const maxTime = (this.manager.mediaMetadata.duration || 3600) * 1000;
                newEnd = Math.min(maxTime, newEnd);
                ann.end_time = newEnd;
            } else if (this.dragState.type === 'move') {
                // Move entire annotation
                const duration = this.dragState.origEnd - this.dragState.origStart;
                let newStart = this.dragState.origStart + deltaTime;
                // Ensure annotation stays in bounds
                newStart = Math.max(0, newStart);
                const maxTime = (this.manager.mediaMetadata.duration || 3600) * 1000;
                newStart = Math.min(maxTime - duration, newStart);
                ann.start_time = newStart;
                ann.end_time = newStart + duration;
            }

            this.render();
            return;
        }

        // If creating a new annotation
        if (this.manager.isDragging) {
            const time = this._xToTime(x);
            this.manager.selectionEnd = time;
            this.render();
            return;
        }

        // Not dragging - update hover state for cursor
        const part = this._getAnnotationPartAtPosition(x, y);
        this.hoveredHandle = part;
        this._updateCursor();

        // Render to show hover state on handles
        this.render();
    }

    /**
     * Handle mouse up
     */
    _handleMouseUp(e) {
        // Finish drag/resize operation
        if (this.dragState) {
            const ann = this.dragState.annotation;
            tieredDebugLog('Finished drag:', this.dragState.type, 'new times:', ann.start_time, '-', ann.end_time);

            // Save the changes
            this.manager._saveData();
            this.manager._renderAnnotationList();

            // Sync to Peaks.js if available
            if (this.manager.peaks) {
                try {
                    const segment = this.manager.peaks.segments.getSegment(ann.id);
                    if (segment) {
                        segment.update({
                            startTime: ann.start_time / 1000,
                            endTime: ann.end_time / 1000
                        });
                    }
                } catch (e) {
                    // Segment might not exist
                }
            }

            this.dragState = null;
            this._updateCursor();
            this.render();
            return;
        }

        // Finish creating new annotation
        if (this.manager.isDragging) {
            this.manager.isDragging = false;

            const x = e.offsetX;
            const endTime = this._xToTime(x);
            const startTime = this.manager.selectionStart;

            // Clear selection
            this.manager.selectionStart = null;
            this.manager.selectionEnd = null;

            // Create annotation if selection is valid (minimum 0.05 seconds)
            if (startTime !== null && endTime !== null && Math.abs(endTime - startTime) > 0.05) {
                const actualStart = Math.min(startTime, endTime);
                const actualEnd = Math.max(startTime, endTime);

                if (this.manager.activeLabel) {
                    this.manager.createAnnotation(
                        this.tierConfig.name,
                        actualStart,
                        actualEnd,
                        this.manager.activeLabel
                    );
                } else {
                    this.manager._showError('Please select a label first');
                }
            }

            this.render();
        }
    }

    /**
     * Handle mouse leave - cancel any drag operation
     */
    _handleMouseLeave(e) {
        // Don't cancel drag if button is still pressed (user might drag back in)
        if (e.buttons === 0) {
            this.dragState = null;
            this.hoveredHandle = null;
            this.canvas.style.cursor = 'crosshair';
        }
    }

    /**
     * Handle double click - seek to position
     */
    _handleDoubleClick(e) {
        const x = e.offsetX;
        const time = this._xToTime(x);
        this.manager.mediaElement.currentTime = time;
    }

    /**
     * Get annotation at canvas position (legacy - for backwards compatibility)
     */
    _getAnnotationAtPosition(x) {
        const annotations = this.manager.annotations[this.tierConfig.name] || [];
        const time = this._xToTime(x) * 1000; // Convert to ms

        for (const ann of annotations) {
            if (time >= ann.start_time && time <= ann.end_time) {
                return ann;
            }
        }

        return null;
    }

    /**
     * Convert x position to time in seconds
     */
    _xToTime(x) {
        const duration = this.manager.mediaMetadata.duration || 1;
        return (x / this.canvas.width) * duration;
    }

    /**
     * Convert time to x position
     */
    _timeToX(timeSeconds) {
        const duration = this.manager.mediaMetadata.duration || 1;
        return (timeSeconds / duration) * this.canvas.width;
    }

    /**
     * Render the tier
     */
    render() {
        this._resizeCanvas();
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

        // Draw background
        this.ctx.fillStyle = '#fafafa';
        this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);

        // Draw grid lines
        this._drawGridLines();

        // Draw annotations
        const annotations = this.manager.annotations[this.tierConfig.name] || [];
        for (const ann of annotations) {
            this._drawAnnotation(ann);
        }

        // Draw selection preview
        if (this.manager.isDragging && this.manager.selectionStart !== null) {
            this._drawSelectionPreview();
        }

        // Draw playhead
        this._drawPlayhead();
    }

    /**
     * Draw playhead line at the current media time
     */
    _drawPlayhead() {
        if (!this.manager.mediaElement) return;
        const currentTime = this.manager.mediaElement.currentTime || 0;
        const duration = this.manager.mediaMetadata.duration;
        if (!duration) return;

        const x = this._timeToX(currentTime);
        if (x < 0 || x > this.canvas.width) return;

        this.ctx.save();
        this.ctx.strokeStyle = '#1f77b4';
        this.ctx.lineWidth = 1.5;
        this.ctx.beginPath();
        this.ctx.moveTo(x, 0);
        this.ctx.lineTo(x, this.canvas.height);
        this.ctx.stroke();
        this.ctx.restore();
    }

    /**
     * Draw grid lines
     */
    _drawGridLines() {
        const duration = this.manager.mediaMetadata.duration;
        if (!duration) return;

        this.ctx.strokeStyle = '#e0e0e0';
        this.ctx.lineWidth = 1;

        // Draw line every second or more depending on zoom
        const interval = duration > 60 ? 10 : duration > 10 ? 5 : 1;

        for (let t = 0; t <= duration; t += interval) {
            const x = this._timeToX(t);
            this.ctx.beginPath();
            this.ctx.moveTo(x, 0);
            this.ctx.lineTo(x, this.canvas.height);
            this.ctx.stroke();
        }
    }

    /**
     * Draw an annotation with resize handles
     */
    _drawAnnotation(ann) {
        const x1 = this._timeToX(ann.start_time / 1000);
        const x2 = this._timeToX(ann.end_time / 1000);
        const height = this.canvas.height - 8;
        const y = 4;

        const isSelected = this.manager.selectedAnnotation?.id === ann.id;
        const isHovered = this.hoveredHandle?.annotation?.id === ann.id;
        const hoverType = isHovered ? this.hoveredHandle.type : null;

        // Draw filled rectangle (main body)
        this.ctx.fillStyle = ann.color || '#cccccc';
        this.ctx.fillRect(x1, y, x2 - x1, height);

        // Draw border (highlight if selected)
        this.ctx.strokeStyle = isSelected ? '#FFD700' : '#333333';
        this.ctx.lineWidth = isSelected ? 3 : 1;
        this.ctx.strokeRect(x1, y, x2 - x1, height);

        // Draw resize handles if selected or hovered
        if (isSelected || isHovered) {
            const handleWidth = this.HANDLE_WIDTH;
            const handleColor = isSelected ? '#FFD700' : '#666666';
            const handleAlpha = 0.7;

            // Left handle (start)
            const leftHandleHighlight = hoverType === 'start' || this.dragState?.type === 'resize-start';
            this.ctx.fillStyle = leftHandleHighlight
                ? 'rgba(255, 215, 0, 0.9)'
                : `rgba(100, 100, 100, ${handleAlpha})`;
            this.ctx.fillRect(x1, y, handleWidth, height);

            // Handle grip lines (left)
            this.ctx.strokeStyle = '#ffffff';
            this.ctx.lineWidth = 1;
            const gripX1 = x1 + handleWidth / 2;
            for (let gy = y + 8; gy < y + height - 8; gy += 4) {
                this.ctx.beginPath();
                this.ctx.moveTo(gripX1 - 1, gy);
                this.ctx.lineTo(gripX1 + 1, gy);
                this.ctx.stroke();
            }

            // Right handle (end)
            const rightHandleHighlight = hoverType === 'end' || this.dragState?.type === 'resize-end';
            this.ctx.fillStyle = rightHandleHighlight
                ? 'rgba(255, 215, 0, 0.9)'
                : `rgba(100, 100, 100, ${handleAlpha})`;
            this.ctx.fillRect(x2 - handleWidth, y, handleWidth, height);

            // Handle grip lines (right)
            this.ctx.strokeStyle = '#ffffff';
            const gripX2 = x2 - handleWidth / 2;
            for (let gy = y + 8; gy < y + height - 8; gy += 4) {
                this.ctx.beginPath();
                this.ctx.moveTo(gripX2 - 1, gy);
                this.ctx.lineTo(gripX2 + 1, gy);
                this.ctx.stroke();
            }
        }

        // Draw label text if there's room (account for handles)
        const textX1 = x1 + (isSelected || isHovered ? this.HANDLE_WIDTH + 4 : 4);
        const textX2 = x2 - (isSelected || isHovered ? this.HANDLE_WIDTH + 4 : 4);

        if (textX2 - textX1 > 10) {
            this.ctx.fillStyle = this.manager._getContrastColor(ann.color || '#cccccc');
            this.ctx.font = '11px sans-serif';
            this.ctx.textBaseline = 'middle';

            // Truncate text if needed
            let label = ann.label;
            const maxWidth = textX2 - textX1;
            let textWidth = this.ctx.measureText(label).width;
            while (textWidth > maxWidth && label.length > 3) {
                label = label.slice(0, -1);
                textWidth = this.ctx.measureText(label + '…').width;
            }
            if (label !== ann.label) label += '…';

            this.ctx.fillText(label, textX1, this.canvas.height / 2);
        }
    }

    /**
     * Draw selection preview
     */
    _drawSelectionPreview() {
        const startTime = this.manager.selectionStart;
        const endTime = this.manager.selectionEnd || startTime;

        const x1 = this._timeToX(Math.min(startTime, endTime));
        const x2 = this._timeToX(Math.max(startTime, endTime));

        // Find active label color
        const tier = this.manager.config.tiers.find(t => t.name === this.manager.activeTier);
        const labelData = tier?.labels?.find(l => l.name === this.manager.activeLabel);
        const color = labelData?.color || '#4ECDC4';

        // Draw semi-transparent preview
        this.ctx.fillStyle = color + '66';  // Add alpha
        this.ctx.fillRect(x1, 4, x2 - x1, this.canvas.height - 8);

        this.ctx.strokeStyle = color;
        this.ctx.lineWidth = 2;
        this.ctx.setLineDash([5, 3]);
        this.ctx.strokeRect(x1, 4, x2 - x1, this.canvas.height - 8);
        this.ctx.setLineDash([]);
    }
}

/**
 * ZoomedTimelineView - Shows a zoomed portion of the timeline for fine-grained editing
 */
class ZoomedTimelineView {
    constructor(manager, canvas) {
        this.manager = manager;
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');

        // Drag state
        this.dragState = null;
        this.hoveredHandle = null;
        this.HANDLE_WIDTH = 10;

        this._resizeCanvas();
        this._setupEventListeners();
    }

    _resizeCanvas() {
        const container = this.canvas.parentElement;
        if (!container) return;
        this.canvas.width = container.offsetWidth;
        this.canvas.height = container.offsetHeight;
    }

    _setupEventListeners() {
        window.addEventListener('resize', () => {
            this._resizeCanvas();
            this.render();
        });

        this.canvas.addEventListener('mousedown', (e) => this._handleMouseDown(e));
        this.canvas.addEventListener('mousemove', (e) => this._handleMouseMove(e));
        this.canvas.addEventListener('mouseup', (e) => this._handleMouseUp(e));
        this.canvas.addEventListener('mouseleave', () => {
            this.hoveredHandle = null;
            this.canvas.style.cursor = 'crosshair';
        });
        this.canvas.addEventListener('dblclick', (e) => this._handleDoubleClick(e));
    }

    /**
     * Convert x position to time (in zoomed view)
     */
    _xToTime(x) {
        const viewStart = this.manager.zoomedViewStart;
        const viewDuration = this.manager.zoomedViewDuration;
        return viewStart + (x / this.canvas.width) * viewDuration;
    }

    /**
     * Convert time to x position (in zoomed view)
     */
    _timeToX(timeSeconds) {
        const viewStart = this.manager.zoomedViewStart;
        const viewDuration = this.manager.zoomedViewDuration;
        return ((timeSeconds - viewStart) / viewDuration) * this.canvas.width;
    }

    /**
     * Get annotation part at position
     */
    _getAnnotationPartAtPosition(x, y) {
        const tierHeight = this.canvas.height / Math.max(1, this.manager.config.tiers.length);

        for (let i = 0; i < this.manager.config.tiers.length; i++) {
            const tier = this.manager.config.tiers[i];
            const tierY = i * tierHeight;
            const annotations = this.manager.annotations[tier.name] || [];

            for (const ann of annotations) {
                const x1 = this._timeToX(ann.start_time / 1000);
                const x2 = this._timeToX(ann.end_time / 1000);

                // Skip if annotation not in view
                if (x2 < 0 || x1 > this.canvas.width) continue;

                // Check if in tier row vertically
                if (y < tierY || y > tierY + tierHeight) continue;

                // Check start handle
                if (x >= x1 - 2 && x <= x1 + this.HANDLE_WIDTH) {
                    return { annotation: ann, tier: tier.name, type: 'start' };
                }
                // Check end handle
                if (x >= x2 - this.HANDLE_WIDTH && x <= x2 + 2) {
                    return { annotation: ann, tier: tier.name, type: 'end' };
                }
                // Check body
                if (x > x1 + this.HANDLE_WIDTH && x < x2 - this.HANDLE_WIDTH) {
                    return { annotation: ann, tier: tier.name, type: 'body' };
                }
            }
        }
        return null;
    }

    _handleMouseDown(e) {
        const x = e.offsetX;
        const y = e.offsetY;

        const part = this._getAnnotationPartAtPosition(x, y);

        if (part) {
            this.manager.selectAnnotation(part.annotation.id);
            this.manager.setActiveTier(part.tier);

            if (part.type === 'start' || part.type === 'end') {
                this.dragState = {
                    type: `resize-${part.type}`,
                    annotation: part.annotation,
                    tier: part.tier,
                    startX: x,
                    origStart: part.annotation.start_time,
                    origEnd: part.annotation.end_time
                };
                this.canvas.style.cursor = 'ew-resize';
            } else if (part.type === 'body') {
                this.dragState = {
                    type: 'move',
                    annotation: part.annotation,
                    tier: part.tier,
                    startX: x,
                    origStart: part.annotation.start_time,
                    origEnd: part.annotation.end_time
                };
                this.canvas.style.cursor = 'move';
            }
            return;
        }

        // Start creating new annotation
        const tierHeight = this.canvas.height / Math.max(1, this.manager.config.tiers.length);
        const tierIndex = Math.floor(y / tierHeight);
        const tier = this.manager.config.tiers[tierIndex];

        if (tier) {
            this.manager.setActiveTier(tier.name);
            this.manager.selectionStart = this._xToTime(x);
            this.manager.isDragging = true;
        }
    }

    _handleMouseMove(e) {
        const x = e.offsetX;
        const y = e.offsetY;

        if (this.dragState) {
            const deltaX = x - this.dragState.startX;
            const deltaTime = (deltaX / this.canvas.width) * this.manager.zoomedViewDuration * 1000;
            const ann = this.dragState.annotation;

            if (this.dragState.type === 'resize-start') {
                let newStart = this.dragState.origStart + deltaTime;
                newStart = Math.min(newStart, this.dragState.origEnd - 50);
                newStart = Math.max(0, newStart);
                ann.start_time = newStart;
            } else if (this.dragState.type === 'resize-end') {
                let newEnd = this.dragState.origEnd + deltaTime;
                newEnd = Math.max(newEnd, this.dragState.origStart + 50);
                const maxTime = (this.manager.mediaMetadata.duration || 3600) * 1000;
                newEnd = Math.min(maxTime, newEnd);
                ann.end_time = newEnd;
            } else if (this.dragState.type === 'move') {
                const duration = this.dragState.origEnd - this.dragState.origStart;
                let newStart = this.dragState.origStart + deltaTime;
                newStart = Math.max(0, newStart);
                const maxTime = (this.manager.mediaMetadata.duration || 3600) * 1000;
                newStart = Math.min(maxTime - duration, newStart);
                ann.start_time = newStart;
                ann.end_time = newStart + duration;
            }

            this.render();
            // Also update tier view
            if (this.manager.tierViews[this.dragState.tier]) {
                this.manager.tierViews[this.dragState.tier].render();
            }
            return;
        }

        if (this.manager.isDragging) {
            this.manager.selectionEnd = this._xToTime(x);
            this.render();
            return;
        }

        // Update hover cursor
        const part = this._getAnnotationPartAtPosition(x, y);
        this.hoveredHandle = part;
        if (part) {
            this.canvas.style.cursor = part.type === 'body' ? 'move' : 'ew-resize';
        } else {
            this.canvas.style.cursor = 'crosshair';
        }
        this.render();
    }

    _handleMouseUp(e) {
        if (this.dragState) {
            this.manager._saveData();
            this.manager._renderAnnotationList();
            this.manager._renderAllTiers();
            this.dragState = null;
            this.render();
            return;
        }

        if (this.manager.isDragging) {
            this.manager.isDragging = false;
            const x = e.offsetX;
            const endTime = this._xToTime(x);
            const startTime = this.manager.selectionStart;

            this.manager.selectionStart = null;
            this.manager.selectionEnd = null;

            if (startTime !== null && endTime !== null && Math.abs(endTime - startTime) > 0.05) {
                const actualStart = Math.min(startTime, endTime);
                const actualEnd = Math.max(startTime, endTime);

                if (this.manager.activeLabel) {
                    this.manager.createAnnotation(
                        this.manager.activeTier,
                        actualStart,
                        actualEnd,
                        this.manager.activeLabel
                    );
                }
            }
            this.render();
        }
    }

    _handleDoubleClick(e) {
        const x = e.offsetX;
        const time = this._xToTime(x);
        this.manager.mediaElement.currentTime = time;
    }

    render() {
        this._resizeCanvas();
        const ctx = this.ctx;
        const width = this.canvas.width;
        const height = this.canvas.height;

        // Clear
        ctx.fillStyle = '#f8f9fa';
        ctx.fillRect(0, 0, width, height);

        const tiers = this.manager.config.tiers;
        const tierHeight = height / Math.max(1, tiers.length);

        // Draw tier backgrounds and labels
        for (let i = 0; i < tiers.length; i++) {
            const tier = tiers[i];
            const y = i * tierHeight;

            // Alternating background
            ctx.fillStyle = i % 2 === 0 ? '#ffffff' : '#f5f5f5';
            ctx.fillRect(0, y, width, tierHeight);

            // Tier divider
            ctx.strokeStyle = '#e0e0e0';
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(0, y + tierHeight);
            ctx.lineTo(width, y + tierHeight);
            ctx.stroke();

            // Tier name
            ctx.fillStyle = '#888';
            ctx.font = '10px sans-serif';
            ctx.textBaseline = 'top';
            ctx.fillText(tier.name, 4, y + 2);
        }

        // Draw time grid
        this._drawTimeGrid();

        // Draw annotations
        for (let i = 0; i < tiers.length; i++) {
            const tier = tiers[i];
            const y = i * tierHeight;
            const annotations = this.manager.annotations[tier.name] || [];

            for (const ann of annotations) {
                this._drawAnnotation(ann, y + 14, tierHeight - 18, tier.name);
            }
        }

        // Draw selection preview
        if (this.manager.isDragging && this.manager.selectionStart !== null && this.manager.selectionEnd !== null) {
            this._drawSelectionPreview();
        }

        // Draw playhead
        const currentTime = this.manager.mediaElement?.currentTime || 0;
        if (currentTime >= this.manager.zoomedViewStart &&
            currentTime <= this.manager.zoomedViewStart + this.manager.zoomedViewDuration) {
            const playheadX = this._timeToX(currentTime);
            ctx.strokeStyle = '#e74c3c';
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.moveTo(playheadX, 0);
            ctx.lineTo(playheadX, height);
            ctx.stroke();

            // Playhead head
            ctx.fillStyle = '#e74c3c';
            ctx.beginPath();
            ctx.arc(playheadX, 0, 5, 0, Math.PI);
            ctx.fill();
        }
    }

    _drawTimeGrid() {
        const ctx = this.ctx;
        const viewStart = this.manager.zoomedViewStart;
        const viewDuration = this.manager.zoomedViewDuration;
        const viewEnd = viewStart + viewDuration;

        // Determine appropriate interval based on view duration
        let interval = 1;  // seconds
        if (viewDuration <= 5) interval = 0.5;
        if (viewDuration <= 2) interval = 0.25;
        if (viewDuration > 30) interval = 5;
        if (viewDuration > 120) interval = 30;

        ctx.strokeStyle = '#ddd';
        ctx.lineWidth = 1;
        ctx.fillStyle = '#999';
        ctx.font = '9px sans-serif';
        ctx.textBaseline = 'bottom';

        const startTick = Math.ceil(viewStart / interval) * interval;
        for (let t = startTick; t <= viewEnd; t += interval) {
            const x = this._timeToX(t);
            ctx.beginPath();
            ctx.moveTo(x, 0);
            ctx.lineTo(x, this.canvas.height);
            ctx.stroke();

            // Time label
            const label = this._formatTimeShort(t);
            ctx.fillText(label, x + 2, this.canvas.height - 2);
        }
    }

    _formatTimeShort(seconds) {
        const mins = Math.floor(seconds / 60);
        const secs = (seconds % 60).toFixed(1);
        return `${mins}:${secs.padStart(4, '0')}`;
    }

    _drawAnnotation(ann, y, height, tierName) {
        const x1 = this._timeToX(ann.start_time / 1000);
        const x2 = this._timeToX(ann.end_time / 1000);

        // Skip if not in view
        if (x2 < 0 || x1 > this.canvas.width) return;

        const ctx = this.ctx;
        const isSelected = this.manager.selectedAnnotation?.id === ann.id;
        const isHovered = this.hoveredHandle?.annotation?.id === ann.id;

        // Draw main body
        ctx.fillStyle = ann.color || '#cccccc';
        ctx.fillRect(x1, y, x2 - x1, height);

        // Border
        ctx.strokeStyle = isSelected ? '#FFD700' : '#333';
        ctx.lineWidth = isSelected ? 2 : 1;
        ctx.strokeRect(x1, y, x2 - x1, height);

        // Draw resize handles if selected or hovered
        if (isSelected || isHovered) {
            const handleColor = 'rgba(100, 100, 100, 0.7)';
            const highlightColor = 'rgba(255, 215, 0, 0.9)';

            // Left handle
            ctx.fillStyle = (this.hoveredHandle?.type === 'start' || this.dragState?.type === 'resize-start')
                ? highlightColor : handleColor;
            ctx.fillRect(x1, y, this.HANDLE_WIDTH, height);

            // Right handle
            ctx.fillStyle = (this.hoveredHandle?.type === 'end' || this.dragState?.type === 'resize-end')
                ? highlightColor : handleColor;
            ctx.fillRect(x2 - this.HANDLE_WIDTH, y, this.HANDLE_WIDTH, height);
        }

        // Label
        const textX = x1 + (isSelected || isHovered ? this.HANDLE_WIDTH + 2 : 4);
        const maxWidth = x2 - x1 - (isSelected || isHovered ? this.HANDLE_WIDTH * 2 + 4 : 8);

        if (maxWidth > 10) {
            ctx.fillStyle = this.manager._getContrastColor(ann.color || '#cccccc');
            ctx.font = '10px sans-serif';
            ctx.textBaseline = 'middle';

            let label = ann.label;
            while (ctx.measureText(label).width > maxWidth && label.length > 2) {
                label = label.slice(0, -1);
            }
            if (label !== ann.label) label += '…';

            ctx.fillText(label, textX, y + height / 2);
        }
    }

    _drawSelectionPreview() {
        const ctx = this.ctx;
        const startTime = this.manager.selectionStart;
        const endTime = this.manager.selectionEnd || startTime;

        const x1 = this._timeToX(Math.min(startTime, endTime));
        const x2 = this._timeToX(Math.max(startTime, endTime));

        const tierHeight = this.canvas.height / Math.max(1, this.manager.config.tiers.length);
        const tierIndex = this.manager.config.tiers.findIndex(t => t.name === this.manager.activeTier);
        const y = tierIndex * tierHeight + 14;
        const height = tierHeight - 18;

        // Get active label color
        const tier = this.manager.config.tiers.find(t => t.name === this.manager.activeTier);
        const labelData = tier?.labels?.find(l => l.name === this.manager.activeLabel);
        const color = labelData?.color || '#4ECDC4';

        ctx.fillStyle = color + '66';
        ctx.fillRect(x1, y, x2 - x1, height);
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.setLineDash([5, 3]);
        ctx.strokeRect(x1, y, x2 - x1, height);
        ctx.setLineDash([]);
    }
}

// Export for use
if (typeof window !== 'undefined') {
    window.TieredAnnotationManager = TieredAnnotationManager;
    window.TierView = TierView;
    window.ZoomedTimelineView = ZoomedTimelineView;
}

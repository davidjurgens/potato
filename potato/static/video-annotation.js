/**
 * Video Annotation Manager
 *
 * Provides video annotation capabilities using Peaks.js for timeline visualization.
 * Supports temporal segments, frame classification, keyframe marking, and object tracking.
 *
 * Features:
 * - Timeline visualization with Peaks.js (uses video's audio track)
 * - Video preview with frame counter and timecode
 * - Segment creation and management
 * - Frame-by-frame navigation
 * - Playback speed control (0.1x to 2.0x)
 * - Keyframe marking
 * - Frame classification
 * - Keyboard shortcuts
 */

// Debug logging utility - respects the debug setting from server config
function videoDebugLog(...args) {
    if (window.config && window.config.debug) {
        console.log(...args);
    }
}

class VideoAnnotationManager {
    /**
     * Create a VideoAnnotationManager instance.
     *
     * @param {Object} options - Configuration options
     * @param {HTMLElement} options.container - Container element
     * @param {string} options.videoId - ID of video element
     * @param {string} options.zoomviewId - ID of timeline container element
     * @param {string} options.overviewId - ID of overview container element
     * @param {string} options.inputId - ID of hidden input for data storage
     * @param {string} options.annotationListId - ID of annotation list container
     * @param {string} options.questionsId - ID of segment questions panel
     * @param {string} options.trackingCanvasId - ID of tracking canvas overlay
     * @param {Object} options.config - Schema configuration
     */
    constructor(options) {
        this.container = options.container;
        this.videoId = options.videoId;
        this.zoomviewId = options.zoomviewId;
        this.overviewId = options.overviewId;
        this.inputId = options.inputId;
        this.annotationListId = options.annotationListId;
        this.questionsId = options.questionsId;
        this.trackingCanvasId = options.trackingCanvasId;
        this.config = options.config || {};

        // State
        this.peaks = null;
        this.segments = [];
        this.keyframes = [];
        this.frameAnnotations = {};
        this.trackingData = {};
        this.activeAnnotationId = null;
        this.activeLabel = null;
        this.activeLabelColor = null;
        this.isPlaying = false;
        this.annotationCounter = 0;

        // Video metadata
        this.videoMetadata = {
            duration: 0,
            fps: this.config.videoFps || 30,
            width: 0,
            height: 0,
            frameCount: 0
        };

        // Selection for segment creation
        this.selectionStart = null;
        this.selectionEnd = null;

        // DOM elements
        this.videoEl = document.getElementById(this.videoId);
        this.zoomviewEl = document.getElementById(this.zoomviewId);
        this.overviewEl = document.getElementById(this.overviewId);
        this.inputEl = document.getElementById(this.inputId);
        this.annotationListEl = document.getElementById(this.annotationListId);
        this.questionsEl = document.getElementById(this.questionsId);
        this.trackingCanvas = document.getElementById(this.trackingCanvasId);

        // Bind methods
        this._onSegmentClick = this._onSegmentClick.bind(this);
        this._onSegmentDragEnd = this._onSegmentDragEnd.bind(this);
        this._handleKeydown = this._handleKeydown.bind(this);
        this._onVideoTimeUpdate = this._onVideoTimeUpdate.bind(this);

        // Set up keyboard shortcuts
        this._setupKeyboardShortcuts();

        videoDebugLog('VideoAnnotationManager initialized:', this.config.schemaName);
    }

    /**
     * Load video and initialize Peaks.js
     *
     * @param {string} videoUrl - URL of the video file
     * @param {string} [waveformUrl] - URL of pre-computed waveform data (optional)
     */
    async loadVideo(videoUrl, waveformUrl = null) {
        videoDebugLog('Loading video:', videoUrl);

        // Set video source
        this.videoEl.src = videoUrl;

        // Wait for video metadata
        try {
            await this._waitForVideoMetadata();
        } catch (error) {
            console.error('[VideoAnnotation] Failed to load video metadata:', error);
            return;
        }

        // Always set up basic video event listeners (even if Peaks.js fails)
        this._setupVideoEventListeners();
        this._updateTimeDisplay();
        this._updateFrameDisplay();

        // Check if Peaks.js is available
        if (typeof Peaks === 'undefined') {
            console.warn('[VideoAnnotation] Peaks.js not available - video will play without timeline visualization');
            // Hide timeline containers since they won't work
            if (this.zoomviewEl) this.zoomviewEl.style.display = 'none';
            if (this.overviewEl) this.overviewEl.style.display = 'none';
            return;
        }

        // Determine waveform source (from video's audio track)
        const waveformSource = waveformUrl
            ? { dataUri: { arraybuffer: waveformUrl } }
            : { webAudio: { audioContext: new (window.AudioContext || window.webkitAudioContext)() } };

        // Peaks.js options - using video element as media source
        const peaksOptions = {
            containers: {
                zoomview: this.zoomviewEl,
                overview: this.overviewEl
            },
            mediaElement: this.videoEl, // Peaks.js supports video elements!
            keyboard: false, // We handle our own keyboard shortcuts
            logger: console.error.bind(console),
            zoomLevels: [256, 512, 1024, 2048, 4096],
            ...waveformSource,
            segments: {
                markers: true,
                overlay: true,
                startMarkerColor: '#4a90d9',
                endMarkerColor: '#4a90d9'
            },
            zoomview: {
                container: this.zoomviewEl,
                waveformColor: 'rgba(74, 144, 217, 0.7)',
                playedWaveformColor: 'rgba(74, 144, 217, 1.0)',
                axisGridlineColor: '#ccc',
                axisLabelColor: '#666',
                fontFamily: 'inherit',
                fontSize: 11,
                fontStyle: 'normal'
            },
            overview: {
                container: this.overviewEl,
                waveformColor: 'rgba(74, 144, 217, 0.5)',
                playedWaveformColor: 'rgba(74, 144, 217, 0.8)',
                highlightColor: 'rgba(255, 255, 255, 0.5)',
                highlightOffset: 1
            }
        };

        try {
            this.peaks = await this._initPeaks(peaksOptions);
            videoDebugLog('Peaks.js initialized successfully for video');

            // Set up Peaks.js-specific event listeners
            this._setupPeaksEventListeners();

            // Load existing annotations if any
            this._loadExistingAnnotations();

            // Set up tracking canvas if in tracking mode
            if (this.config.mode === 'tracking' || this.config.mode === 'combined') {
                this._setupTrackingCanvas();
            }

        } catch (error) {
            console.error('Failed to initialize Peaks.js:', error);
            // Hide timeline containers since they won't work
            if (this.zoomviewEl) this.zoomviewEl.style.display = 'none';
            if (this.overviewEl) this.overviewEl.style.display = 'none';
            console.warn('[VideoAnnotation] Waveform visualization unavailable. Video playback still works.');
        }
    }

    /**
     * Wait for video metadata to load
     */
    _waitForVideoMetadata() {
        return new Promise((resolve, reject) => {
            if (this.videoEl.readyState >= 1) {
                this._extractVideoMetadata();
                resolve();
            } else {
                const onLoadedMetadata = () => {
                    this._extractVideoMetadata();
                    resolve();
                };

                const onError = (e) => {
                    console.error('[VideoAnnotation] Video failed to load:', e);
                    this._showError('Failed to load video. Please check the video URL and ensure it is accessible.');
                    reject(new Error('Video failed to load'));
                };

                this.videoEl.addEventListener('loadedmetadata', onLoadedMetadata, { once: true });
                this.videoEl.addEventListener('error', onError, { once: true });

                // Also handle case where video was already in error state
                if (this.videoEl.error) {
                    onError(this.videoEl.error);
                }
            }
        });
    }

    /**
     * Show error message to user
     */
    _showError(message) {
        const errorDiv = document.createElement('div');
        errorDiv.className = 'video-annotation-error';
        errorDiv.textContent = message;
        this.container.insertBefore(errorDiv, this.container.firstChild);
    }

    /**
     * Extract metadata from video element
     */
    _extractVideoMetadata() {
        this.videoMetadata.duration = this.videoEl.duration;
        this.videoMetadata.width = this.videoEl.videoWidth;
        this.videoMetadata.height = this.videoEl.videoHeight;
        this.videoMetadata.fps = this.config.videoFps || 30;
        this.videoMetadata.frameCount = Math.floor(
            this.videoMetadata.duration * this.videoMetadata.fps
        );
        videoDebugLog('Video metadata:', this.videoMetadata);
    }

    /**
     * Initialize Peaks.js (wrapped in Promise)
     */
    _initPeaks(options) {
        return new Promise((resolve, reject) => {
            Peaks.init(options, (err, peaks) => {
                if (err) {
                    reject(err);
                } else {
                    resolve(peaks);
                }
            });
        });
    }

    /**
     * Set up Peaks.js event listeners
     */
    _setupPeaksEventListeners() {
        if (!this.peaks) return;

        const player = this.peaks.player;
        const view = this.peaks.views.getView('zoomview');

        // Playback events
        player.on('player.playing', () => {
            this.isPlaying = true;
            this._updatePlayButton();
        });

        player.on('player.pause', () => {
            this.isPlaying = false;
            this._updatePlayButton();
        });

        player.on('player.ended', () => {
            this.isPlaying = false;
            this._updatePlayButton();
        });

        player.on('player.timeupdate', (time) => {
            this._updateTimeDisplay(time);
            this._updateFrameDisplay();
        });

        // Segment events
        this.peaks.on('segments.click', this._onSegmentClick);
        this.peaks.on('segments.dragend', this._onSegmentDragEnd);

        // Point (keyframe/frame annotation) events
        this.peaks.on('points.click', (event) => {
            videoDebugLog('Point clicked:', event.point);
            this._selectAnnotation(event.point.id);
        });

        // Double-click to create segment at position
        if (view) {
            view.on('dblclick', (event) => {
                const time = event.time;
                if (this.config.mode === 'segment' || this.config.mode === 'combined') {
                    // Create a 5-second segment starting at click position
                    const endTime = Math.min(time + 5, player.getDuration());
                    this.createSegment(time, endTime);
                }
            });
        }
    }

    /**
     * Set up video element event listeners
     */
    _setupVideoEventListeners() {
        this.videoEl.addEventListener('timeupdate', this._onVideoTimeUpdate);
    }

    /**
     * Handle video time update
     */
    _onVideoTimeUpdate() {
        this._updateFrameDisplay();

        // Update tracking overlay if in tracking mode
        if (this.config.mode === 'tracking' || this.config.mode === 'combined') {
            this._renderTrackingOverlay();
        }
    }

    // ==================== Frame Navigation ====================

    /**
     * Get current frame number
     */
    getCurrentFrame() {
        return Math.floor(this.videoEl.currentTime * this.videoMetadata.fps);
    }

    /**
     * Seek to specific frame
     */
    seekToFrame(frameNumber) {
        const time = frameNumber / this.videoMetadata.fps;
        this.videoEl.currentTime = Math.min(time, this.videoEl.duration);
    }

    /**
     * Step forward one frame
     */
    stepFrameForward() {
        const frameDuration = 1 / this.videoMetadata.fps;
        const newTime = Math.min(
            this.videoEl.currentTime + frameDuration,
            this.videoEl.duration
        );
        this.videoEl.currentTime = newTime;
        this._updateFrameDisplay();
    }

    /**
     * Step backward one frame
     */
    stepFrameBackward() {
        const frameDuration = 1 / this.videoMetadata.fps;
        const newTime = Math.max(
            this.videoEl.currentTime - frameDuration,
            0
        );
        this.videoEl.currentTime = newTime;
        this._updateFrameDisplay();
    }

    // ==================== Playback Controls ====================

    /**
     * Toggle play/pause
     */
    togglePlayPause() {
        if (!this.peaks) return;

        if (this.isPlaying) {
            this.peaks.player.pause();
        } else {
            this.peaks.player.play();
        }
    }

    /**
     * Stop playback
     */
    stop() {
        if (!this.peaks) return;
        this.peaks.player.pause();
        this.peaks.player.seek(0);
    }

    /**
     * Seek relative to current position
     */
    seek(seconds) {
        if (!this.peaks) return;
        const currentTime = this.peaks.player.getCurrentTime();
        const duration = this.peaks.player.getDuration();
        const newTime = Math.max(0, Math.min(currentTime + seconds, duration));
        this.peaks.player.seek(newTime);
    }

    /**
     * Set playback rate
     */
    setPlaybackRate(rate) {
        const clampedRate = Math.max(0.1, Math.min(2.0, rate));
        this.videoEl.playbackRate = clampedRate;
    }

    // ==================== Label Management ====================

    /**
     * Set active label for creating new annotations
     */
    setActiveLabel(label, color) {
        this.activeLabel = label;
        this.activeLabelColor = color;
        videoDebugLog('Active label set:', label, color);
    }

    // ==================== Segment Management ====================

    /**
     * Set segment start time
     */
    setSelectionStart() {
        // Use video element directly if Peaks.js not available
        this.selectionStart = this.peaks
            ? this.peaks.player.getCurrentTime()
            : this.videoEl.currentTime;
        this._showToast(`Segment start: ${this._formatTime(this.selectionStart)}`);
    }

    /**
     * Set segment end time
     */
    setSelectionEnd() {
        // Use video element directly if Peaks.js not available
        this.selectionEnd = this.peaks
            ? this.peaks.player.getCurrentTime()
            : this.videoEl.currentTime;
        this._showToast(`Segment end: ${this._formatTime(this.selectionEnd)}`);
    }

    /**
     * Create segment from selection
     */
    createSegmentFromSelection() {
        if (this.selectionStart === null || this.selectionEnd === null) {
            this._showToast('Please set both start and end times first');
            return;
        }

        const start = Math.min(this.selectionStart, this.selectionEnd);
        const end = Math.max(this.selectionStart, this.selectionEnd);

        if (end - start < 0.1) {
            this._showToast('Segment must be at least 0.1 seconds');
            return;
        }

        this.createSegment(start, end);

        // Clear selection
        this.selectionStart = null;
        this.selectionEnd = null;
    }

    /**
     * Create a new segment
     */
    createSegment(startTime, endTime, label = null, color = null, id = null) {
        // Check max segments
        if (this.config.maxSegments && this.segments.length >= this.config.maxSegments) {
            this._showToast(`Maximum ${this.config.maxSegments} segments allowed`);
            return null;
        }

        const segmentId = id || `segment_${++this.annotationCounter}`;
        const segmentLabel = label || this.activeLabel || 'unlabeled';
        const segmentColor = color || this.activeLabelColor || '#4ECDC4';

        // Add to Peaks.js if available
        if (this.peaks) {
            this.peaks.segments.add({
                id: segmentId,
                startTime: startTime,
                endTime: endTime,
                labelText: segmentLabel,
                color: segmentColor,
                editable: true
            });
        }

        // Track in our list (works with or without Peaks.js)
        const segment = {
            id: segmentId,
            startTime: startTime,
            endTime: endTime,
            startFrame: Math.floor(startTime * (this.videoMetadata.fps || 30)),
            endFrame: Math.floor(endTime * (this.videoMetadata.fps || 30)),
            label: segmentLabel,
            color: segmentColor,
            annotations: {}
        };
        this.segments.push(segment);

        this._updateAnnotationList();
        this._updateSegmentCount();
        this._saveData();

        videoDebugLog('Created segment:', segment);
        return segment;
    }

    /**
     * Delete a segment
     */
    deleteSegment(segmentId) {
        // Remove from Peaks.js if available
        if (this.peaks) {
            this.peaks.segments.removeById(segmentId);
        }

        // Remove from our list
        this.segments = this.segments.filter(s => s.id !== segmentId);

        if (this.activeAnnotationId === segmentId) {
            this.activeAnnotationId = null;
        }

        this._updateAnnotationList();
        this._updateSegmentCount();
        this._saveData();

        videoDebugLog('Deleted segment:', segmentId);
    }

    // ==================== Frame Classification ====================

    /**
     * Classify the current frame
     */
    classifyCurrentFrame(label, color) {
        if (!label) {
            this._showToast('Please select a label first');
            return;
        }

        const frame = this.getCurrentFrame();
        const time = this.videoEl.currentTime;

        this.frameAnnotations[frame] = {
            id: `frame_${frame}`,
            frame: frame,
            time: time,
            label: label,
            color: color || this.activeLabelColor || '#4ECDC4',
            timestamp: Date.now()
        };

        // Add visual marker on timeline
        this._addFrameMarker(frame, label, color);

        this._updateAnnotationList();
        this._saveData();

        this._showToast(`Frame ${frame} classified as "${label}"`);
        videoDebugLog('Classified frame:', this.frameAnnotations[frame]);
    }

    /**
     * Add frame marker on timeline
     */
    _addFrameMarker(frame, label, color) {
        if (!this.peaks) return;

        const time = frame / this.videoMetadata.fps;
        const pointId = `frame_${frame}`;

        // Remove existing marker at this frame if any
        try {
            this.peaks.points.removeById(pointId);
        } catch (e) {
            // Point didn't exist
        }

        this.peaks.points.add({
            id: pointId,
            time: time,
            labelText: label,
            color: color || '#FF6B6B',
            editable: false
        });
    }

    // ==================== Keyframe Marking ====================

    /**
     * Mark current position as keyframe
     */
    markKeyframe(label = null, note = '') {
        const frame = this.getCurrentFrame();
        const time = this.videoEl.currentTime;
        const keyframeLabel = label || this.activeLabel || 'keyframe';

        const keyframe = {
            id: `keyframe_${++this.annotationCounter}`,
            frame: frame,
            time: time,
            label: keyframeLabel,
            note: note,
            color: '#FFD700', // Gold for keyframes
            timestamp: Date.now()
        };

        this.keyframes.push(keyframe);

        // Add point marker on timeline
        this.peaks.points.add({
            id: keyframe.id,
            time: time,
            labelText: `KF: ${keyframeLabel}`,
            color: keyframe.color,
            editable: true
        });

        this._updateAnnotationList();
        this._saveData();

        this._showToast(`Keyframe marked at frame ${frame}`);
        videoDebugLog('Marked keyframe:', keyframe);
        return keyframe;
    }

    // ==================== Object Tracking ====================

    /**
     * Set up tracking canvas
     */
    _setupTrackingCanvas() {
        if (!this.trackingCanvas) return;

        this.trackingCanvas.style.display = 'block';
        this.trackingCanvas.width = this.videoEl.videoWidth || 640;
        this.trackingCanvas.height = this.videoEl.videoHeight || 360;
    }

    /**
     * Add tracking annotation at current frame
     */
    addTrackingAnnotation(bbox, objectId, label) {
        const frame = this.getCurrentFrame();

        if (!objectId) {
            objectId = `object_${++this.annotationCounter}`;
        }

        if (!this.trackingData[objectId]) {
            this.trackingData[objectId] = {
                id: objectId,
                label: label || this.activeLabel || 'object',
                color: this.activeLabelColor || '#FF6B6B',
                keyframes: {}
            };
        }

        this.trackingData[objectId].keyframes[frame] = {
            frame: frame,
            time: this.videoEl.currentTime,
            bbox: bbox // {x, y, width, height}
        };

        this._renderTrackingOverlay();
        this._updateAnnotationList();
        this._saveData();

        videoDebugLog('Added tracking annotation:', objectId, 'at frame', frame);
    }

    /**
     * Render tracking overlay for current frame
     */
    _renderTrackingOverlay() {
        if (!this.trackingCanvas) return;

        const ctx = this.trackingCanvas.getContext('2d');
        ctx.clearRect(0, 0, this.trackingCanvas.width, this.trackingCanvas.height);

        const currentFrame = this.getCurrentFrame();

        // Draw bounding boxes for current frame
        for (const objectId in this.trackingData) {
            const obj = this.trackingData[objectId];
            const kf = obj.keyframes[currentFrame];

            if (kf) {
                ctx.strokeStyle = obj.color || '#FF6B6B';
                ctx.lineWidth = 2;
                ctx.strokeRect(kf.bbox.x, kf.bbox.y, kf.bbox.width, kf.bbox.height);
                ctx.fillStyle = obj.color || '#FF6B6B';
                ctx.font = '12px Arial';
                ctx.fillText(obj.label, kf.bbox.x, kf.bbox.y - 5);
            }
        }
    }

    // ==================== Selection Management ====================

    /**
     * Select an annotation
     */
    _selectAnnotation(annotationId) {
        this.activeAnnotationId = annotationId;
        this._updateAnnotationList();
        this._updateDeleteButton();
    }

    /**
     * Delete selected annotation
     */
    deleteSelectedAnnotation() {
        if (!this.activeAnnotationId) {
            this._showToast('No annotation selected');
            return;
        }

        const id = this.activeAnnotationId;

        // Check if it's a segment
        if (id.startsWith('segment_')) {
            this.deleteSegment(id);
        }
        // Check if it's a keyframe
        else if (id.startsWith('keyframe_')) {
            this.keyframes = this.keyframes.filter(k => k.id !== id);
            try {
                this.peaks.points.removeById(id);
            } catch (e) {}
        }
        // Check if it's a frame annotation
        else if (id.startsWith('frame_')) {
            const frame = parseInt(id.replace('frame_', ''));
            delete this.frameAnnotations[frame];
            try {
                this.peaks.points.removeById(id);
            } catch (e) {}
        }

        this.activeAnnotationId = null;
        this._updateAnnotationList();
        this._updateDeleteButton();
        this._saveData();
    }

    // ==================== Keyboard Shortcuts ====================

    /**
     * Set up keyboard shortcuts
     */
    _setupKeyboardShortcuts() {
        document.addEventListener('keydown', this._handleKeydown);
    }

    /**
     * Handle keydown events
     */
    _handleKeydown(event) {
        // Don't handle if typing in input/textarea
        if (event.target.tagName === 'INPUT' || event.target.tagName === 'TEXTAREA') {
            return;
        }

        // Check if this container is focused/active
        if (!this.container.contains(document.activeElement) &&
            document.activeElement !== document.body) {
            return;
        }

        const key = event.key.toLowerCase();

        switch (key) {
            case ' ': // Space - Play/Pause
                event.preventDefault();
                this.togglePlayPause();
                break;

            case 'arrowleft':
                event.preventDefault();
                if (event.ctrlKey || event.metaKey) {
                    this.stepFrameBackward();
                } else if (event.shiftKey) {
                    this.seek(-30);
                } else {
                    this.seek(-5);
                }
                break;

            case 'arrowright':
                event.preventDefault();
                if (event.ctrlKey || event.metaKey) {
                    this.stepFrameForward();
                } else if (event.shiftKey) {
                    this.seek(30);
                } else {
                    this.seek(5);
                }
                break;

            case ',': // Frame back
                event.preventDefault();
                this.stepFrameBackward();
                break;

            case '.': // Frame forward
                event.preventDefault();
                this.stepFrameForward();
                break;

            case '[':
                event.preventDefault();
                this.setSelectionStart();
                break;

            case ']':
                event.preventDefault();
                this.setSelectionEnd();
                break;

            case 'enter':
                event.preventDefault();
                this.createSegmentFromSelection();
                break;

            case 'k': // Mark keyframe
                event.preventDefault();
                this.markKeyframe(this.activeLabel);
                break;

            case 'c': // Classify frame
                event.preventDefault();
                this.classifyCurrentFrame(this.activeLabel, this.activeLabelColor);
                break;

            case 'delete':
            case 'backspace':
                event.preventDefault();
                this.deleteSelectedAnnotation();
                break;

            case '+':
            case '=':
                event.preventDefault();
                this.zoomIn();
                break;

            case '-':
                event.preventDefault();
                this.zoomOut();
                break;

            case '0':
                event.preventDefault();
                this.zoomToFit();
                break;

            default:
                // Check for label shortcuts
                this._handleLabelShortcut(key);
                break;
        }
    }

    /**
     * Handle label shortcut key
     */
    _handleLabelShortcut(key) {
        const labels = this.config.labels || [];
        for (const label of labels) {
            if (label.key_value && label.key_value.toLowerCase() === key) {
                this.setActiveLabel(label.name, label.color);
                // Update UI
                const buttons = this.container.querySelectorAll('.label-btn');
                buttons.forEach(btn => {
                    btn.classList.toggle('active', btn.dataset.label === label.name);
                });
                this._showToast(`Selected: ${label.name}`);
                break;
            }
        }
    }

    // ==================== Zoom Controls ====================

    zoomIn() {
        if (!this.peaks) return;
        const view = this.peaks.views.getView('zoomview');
        if (view) {
            view.setZoom({ scale: 'auto' });
            const zoomLevel = view.getZoom();
            view.setZoom({ seconds: zoomLevel * 0.75 });
        }
    }

    zoomOut() {
        if (!this.peaks) return;
        const view = this.peaks.views.getView('zoomview');
        if (view) {
            view.setZoom({ scale: 'auto' });
            const zoomLevel = view.getZoom();
            view.setZoom({ seconds: zoomLevel * 1.25 });
        }
    }

    zoomToFit() {
        if (!this.peaks) return;
        const view = this.peaks.views.getView('zoomview');
        if (view) {
            view.setZoom({ seconds: 'auto' });
        }
    }

    // ==================== Event Handlers ====================

    _onSegmentClick(event) {
        videoDebugLog('Segment clicked:', event.segment);
        this._selectAnnotation(event.segment.id);
    }

    _onSegmentDragEnd(event) {
        const segment = event.segment;
        const storedSegment = this.segments.find(s => s.id === segment.id);
        if (storedSegment) {
            storedSegment.startTime = segment.startTime;
            storedSegment.endTime = segment.endTime;
            storedSegment.startFrame = Math.floor(segment.startTime * this.videoMetadata.fps);
            storedSegment.endFrame = Math.floor(segment.endTime * this.videoMetadata.fps);
            this._updateAnnotationList();
            this._saveData();
        }
    }

    // ==================== UI Updates ====================

    _updatePlayButton() {
        const playBtn = this.container.querySelector('[data-action="play"]');
        if (playBtn) {
            const playIcon = playBtn.querySelector('.play-icon');
            const pauseIcon = playBtn.querySelector('.pause-icon');
            if (playIcon && pauseIcon) {
                playIcon.style.display = this.isPlaying ? 'none' : 'inline';
                pauseIcon.style.display = this.isPlaying ? 'inline' : 'none';
            }
        }
    }

    _updateTimeDisplay(time = null) {
        const currentTime = time !== null ? time : (this.peaks ? this.peaks.player.getCurrentTime() : 0);
        const duration = this.peaks ? this.peaks.player.getDuration() : 0;

        const currentTimeEl = this.container.querySelector('.current-time');
        const totalTimeEl = this.container.querySelector('.total-time');

        if (currentTimeEl) {
            currentTimeEl.textContent = this._formatTime(currentTime);
        }
        if (totalTimeEl) {
            totalTimeEl.textContent = this._formatTime(duration);
        }
    }

    _updateFrameDisplay() {
        const frame = this.getCurrentFrame();
        const time = this.videoEl.currentTime;

        const frameValueEl = this.container.querySelector('.frame-value');
        const timecodeEl = this.container.querySelector('.timecode');

        if (frameValueEl) {
            frameValueEl.textContent = frame;
        }
        if (timecodeEl) {
            timecodeEl.textContent = this._formatTimecode(time);
        }
    }

    _updateSegmentCount() {
        const countEl = this.container.querySelector('.count-value');
        if (countEl) {
            countEl.textContent = this.segments.length;
        }
    }

    _updateDeleteButton() {
        const deleteBtn = this.container.querySelector('[data-action="delete-segment"]');
        if (deleteBtn) {
            deleteBtn.disabled = !this.activeAnnotationId;
        }
    }

    _updateAnnotationList() {
        if (!this.annotationListEl) return;

        let html = '';

        // Segments
        if (this.segments.length > 0) {
            html += '<div class="annotation-group"><h5>Segments</h5>';
            for (const segment of this.segments) {
                const isActive = this.activeAnnotationId === segment.id;
                html += `
                    <div class="annotation-item ${isActive ? 'active' : ''}" data-id="${segment.id}">
                        <span class="annotation-color" style="background-color: ${segment.color};"></span>
                        <span class="annotation-label">${segment.label}</span>
                        <span class="annotation-time">${this._formatTime(segment.startTime)} - ${this._formatTime(segment.endTime)}</span>
                        <span class="annotation-frames">(F${segment.startFrame} - F${segment.endFrame})</span>
                        <button class="annotation-play" data-start="${segment.startTime}" title="Play">&#9654;</button>
                        <button class="annotation-delete" data-id="${segment.id}" title="Delete">&times;</button>
                    </div>
                `;
            }
            html += '</div>';
        }

        // Keyframes
        if (this.keyframes.length > 0) {
            html += '<div class="annotation-group"><h5>Keyframes</h5>';
            for (const kf of this.keyframes) {
                const isActive = this.activeAnnotationId === kf.id;
                html += `
                    <div class="annotation-item ${isActive ? 'active' : ''}" data-id="${kf.id}">
                        <span class="annotation-color" style="background-color: ${kf.color};"></span>
                        <span class="annotation-label">${kf.label}</span>
                        <span class="annotation-time">F${kf.frame} (${this._formatTime(kf.time)})</span>
                        <button class="annotation-play" data-start="${kf.time}" title="Jump">&#9654;</button>
                        <button class="annotation-delete" data-id="${kf.id}" title="Delete">&times;</button>
                    </div>
                `;
            }
            html += '</div>';
        }

        // Frame annotations
        const frameKeys = Object.keys(this.frameAnnotations);
        if (frameKeys.length > 0) {
            html += '<div class="annotation-group"><h5>Frame Classifications</h5>';
            for (const frame of frameKeys.sort((a, b) => parseInt(a) - parseInt(b))) {
                const fa = this.frameAnnotations[frame];
                const isActive = this.activeAnnotationId === fa.id;
                html += `
                    <div class="annotation-item ${isActive ? 'active' : ''}" data-id="${fa.id}">
                        <span class="annotation-color" style="background-color: ${fa.color};"></span>
                        <span class="annotation-label">${fa.label}</span>
                        <span class="annotation-time">F${fa.frame} (${this._formatTime(fa.time)})</span>
                        <button class="annotation-play" data-start="${fa.time}" title="Jump">&#9654;</button>
                        <button class="annotation-delete" data-id="${fa.id}" title="Delete">&times;</button>
                    </div>
                `;
            }
            html += '</div>';
        }

        if (!html) {
            html = '<p class="no-annotations">No annotations yet. Use [ and ] to mark segment boundaries, then press Enter to create.</p>';
        }

        this.annotationListEl.innerHTML = html;

        // Wire up event listeners
        this.annotationListEl.querySelectorAll('.annotation-item').forEach(item => {
            item.addEventListener('click', (e) => {
                if (!e.target.classList.contains('annotation-play') &&
                    !e.target.classList.contains('annotation-delete')) {
                    this._selectAnnotation(item.dataset.id);
                }
            });
        });

        this.annotationListEl.querySelectorAll('.annotation-play').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const time = parseFloat(btn.dataset.start);
                if (this.peaks) {
                    this.peaks.player.seek(time);
                }
            });
        });

        this.annotationListEl.querySelectorAll('.annotation-delete').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.activeAnnotationId = btn.dataset.id;
                this.deleteSelectedAnnotation();
            });
        });
    }

    // ==================== Data Persistence ====================

    _saveData() {
        const data = {
            video_metadata: this.videoMetadata,
            segments: this.segments.map(s => ({
                id: s.id,
                start_time: s.startTime,
                end_time: s.endTime,
                start_frame: s.startFrame,
                end_frame: s.endFrame,
                label: s.label,
                annotations: s.annotations || {}
            })),
            frame_annotations: this.frameAnnotations,
            keyframes: this.keyframes,
            tracking: this.trackingData
        };

        if (this.inputEl) {
            this.inputEl.value = JSON.stringify(data);
        }

        videoDebugLog('Saved annotation data:', data);
    }

    _loadExistingAnnotations() {
        if (!this.inputEl || !this.inputEl.value) return;

        try {
            const data = JSON.parse(this.inputEl.value);

            // Load segments
            if (data.segments) {
                for (const segment of data.segments) {
                    this.createSegment(
                        segment.start_time,
                        segment.end_time,
                        segment.label,
                        segment.color,
                        segment.id
                    );
                }
            }

            // Load frame annotations
            if (data.frame_annotations) {
                for (const frame in data.frame_annotations) {
                    const fa = data.frame_annotations[frame];
                    this.frameAnnotations[frame] = fa;
                    this._addFrameMarker(parseInt(frame), fa.label, fa.color);
                }
            }

            // Load keyframes
            if (data.keyframes) {
                for (const kf of data.keyframes) {
                    this.keyframes.push(kf);
                    this.peaks.points.add({
                        id: kf.id,
                        time: kf.time,
                        labelText: `KF: ${kf.label}`,
                        color: kf.color,
                        editable: true
                    });
                }
            }

            // Load tracking data
            if (data.tracking) {
                this.trackingData = data.tracking;
            }

            this._updateAnnotationList();
            videoDebugLog('Loaded existing annotations:', data);

        } catch (e) {
            console.warn('Failed to load existing annotations:', e);
        }
    }

    serialize() {
        return {
            video_metadata: this.videoMetadata,
            segments: this.segments,
            frame_annotations: this.frameAnnotations,
            keyframes: this.keyframes,
            tracking: this.trackingData
        };
    }

    // ==================== Utility Functions ====================

    _formatTime(seconds) {
        if (!seconds || isNaN(seconds)) return '0:00';
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        return `${mins}:${secs.toString().padStart(2, '0')}`;
    }

    _formatTimecode(seconds) {
        if (!seconds || isNaN(seconds)) return '00:00:00.000';
        const hours = Math.floor(seconds / 3600);
        const mins = Math.floor((seconds % 3600) / 60);
        const secs = Math.floor(seconds % 60);
        const ms = Math.floor((seconds % 1) * 1000);
        return `${hours.toString().padStart(2, '0')}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}.${ms.toString().padStart(3, '0')}`;
    }

    _showToast(message) {
        // Simple toast notification
        const toast = document.createElement('div');
        toast.className = 'video-annotation-toast';
        toast.textContent = message;
        this.container.appendChild(toast);

        setTimeout(() => {
            toast.classList.add('show');
        }, 10);

        setTimeout(() => {
            toast.classList.remove('show');
            setTimeout(() => toast.remove(), 300);
        }, 2000);
    }

    _showError(message) {
        console.error(message);
        const errorEl = document.createElement('div');
        errorEl.className = 'video-annotation-error';
        errorEl.textContent = message;
        this.container.appendChild(errorEl);
    }

    /**
     * Clean up when destroying the manager
     */
    destroy() {
        document.removeEventListener('keydown', this._handleKeydown);
        this.videoEl.removeEventListener('timeupdate', this._onVideoTimeUpdate);

        if (this.peaks) {
            this.peaks.destroy();
            this.peaks = null;
        }
    }
}

// Export for use in modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = VideoAnnotationManager;
}

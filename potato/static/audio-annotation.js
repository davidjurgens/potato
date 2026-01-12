/**
 * Audio Annotation Manager
 *
 * Provides audio annotation capabilities using Peaks.js for waveform visualization.
 * Supports segment creation, labeling, and per-segment annotation questions.
 *
 * Features:
 * - Waveform visualization with zoom/scroll
 * - Segment creation and management
 * - Label assignment to segments
 * - Per-segment annotation questions (radio, multirate, etc.)
 * - Keyboard shortcuts
 * - Pre-computed waveform data support for long audio files
 */

class AudioAnnotationManager {
    /**
     * Create an AudioAnnotationManager instance.
     *
     * @param {Object} options - Configuration options
     * @param {HTMLElement} options.container - Container element
     * @param {string} options.waveformId - ID of waveform container element
     * @param {string} options.overviewId - ID of overview container element
     * @param {string} options.audioId - ID of audio element
     * @param {string} options.inputId - ID of hidden input for data storage
     * @param {string} options.segmentListId - ID of segment list container
     * @param {string} options.questionsId - ID of segment questions panel
     * @param {Object} options.config - Schema configuration
     */
    constructor(options) {
        this.container = options.container;
        this.waveformId = options.waveformId;
        this.overviewId = options.overviewId;
        this.audioId = options.audioId;
        this.inputId = options.inputId;
        this.segmentListId = options.segmentListId;
        this.questionsId = options.questionsId;
        this.config = options.config || {};

        // State
        this.peaks = null;
        this.segments = [];
        this.activeSegmentId = null;
        this.activeLabel = null;
        this.activeLabelColor = null;
        this.isPlaying = false;
        this.segmentCounter = 0;

        // Selection for segment creation
        this.selectionStart = null;
        this.selectionEnd = null;

        // DOM elements
        this.waveformEl = document.getElementById(this.waveformId);
        this.overviewEl = document.getElementById(this.overviewId);
        this.audioEl = document.getElementById(this.audioId);
        this.inputEl = document.getElementById(this.inputId);
        this.segmentListEl = document.getElementById(this.segmentListId);
        this.questionsEl = document.getElementById(this.questionsId);

        // Bind methods
        this._onSegmentClick = this._onSegmentClick.bind(this);
        this._onSegmentDragEnd = this._onSegmentDragEnd.bind(this);
        this._handleKeydown = this._handleKeydown.bind(this);

        // Set up keyboard shortcuts
        this._setupKeyboardShortcuts();

        console.log('AudioAnnotationManager initialized:', this.config.schemaName);
    }

    /**
     * Load audio and initialize Peaks.js
     *
     * @param {string} audioUrl - URL of the audio file
     * @param {string} [waveformUrl] - URL of pre-computed waveform data (optional)
     */
    async loadAudio(audioUrl, waveformUrl = null) {
        console.log('Loading audio:', audioUrl);

        // Set audio source
        this.audioEl.src = audioUrl;

        // Determine waveform source
        const waveformSource = waveformUrl
            ? { dataUri: { arraybuffer: waveformUrl } }
            : { webAudio: { audioContext: new (window.AudioContext || window.webkitAudioContext)() } };

        // Peaks.js options
        const peaksOptions = {
            containers: {
                zoomview: this.waveformEl,
                overview: this.overviewEl
            },
            mediaElement: this.audioEl,
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
                container: this.waveformEl,
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
            console.log('Peaks.js initialized successfully');

            // Set up event listeners
            this._setupPeaksEventListeners();

            // Update time display
            this._updateTimeDisplay();

            // Load existing annotations if any
            this._loadExistingAnnotations();

        } catch (error) {
            console.error('Failed to initialize Peaks.js:', error);
            this._showError('Failed to load audio waveform. Please try refreshing the page.');
        }
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
        });

        // Segment events
        this.peaks.on('segments.click', this._onSegmentClick);
        this.peaks.on('segments.dragend', this._onSegmentDragEnd);

        // Double-click to create segment at position
        if (view) {
            view.on('dblclick', (event) => {
                const time = event.time;
                // Create a 5-second segment starting at click position
                const endTime = Math.min(time + 5, player.getDuration());
                this.createSegment(time, endTime);
            });
        }
    }

    /**
     * Set up keyboard shortcuts
     */
    _setupKeyboardShortcuts() {
        document.addEventListener('keydown', this._handleKeydown);
    }

    /**
     * Handle keyboard events
     */
    _handleKeydown(event) {
        // Don't handle if focus is in an input/textarea
        if (event.target.tagName === 'INPUT' || event.target.tagName === 'TEXTAREA') {
            return;
        }

        // Don't handle if container is not visible
        if (!this.container || !this.container.offsetParent) {
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
                if (event.shiftKey) {
                    this.seek(-30); // Shift+Left: 30 seconds back
                } else {
                    this.seek(-5); // Left: 5 seconds back
                }
                break;

            case 'arrowright':
                event.preventDefault();
                if (event.shiftKey) {
                    this.seek(30); // Shift+Right: 30 seconds forward
                } else {
                    this.seek(5); // Right: 5 seconds forward
                }
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

            case 'delete':
            case 'backspace':
                event.preventDefault();
                this.deleteSelectedSegment();
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
                // Check for label shortcuts (1-9)
                if (/^[1-9]$/.test(key)) {
                    const labels = this.config.labels || [];
                    const labelIndex = parseInt(key) - 1;
                    if (labelIndex < labels.length) {
                        const label = labels[labelIndex];
                        this.setActiveLabel(label.name, label.color);
                        // Update UI button
                        this._updateLabelButtons(label.name);
                    }
                }
                // Check for custom label key_values
                else if (this.config.labels) {
                    const matchingLabel = this.config.labels.find(l => l.key_value === key);
                    if (matchingLabel) {
                        this.setActiveLabel(matchingLabel.name, matchingLabel.color);
                        this._updateLabelButtons(matchingLabel.name);
                    }
                }
                break;
        }
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
     *
     * @param {number} seconds - Seconds to seek (positive or negative)
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
     *
     * @param {number} rate - Playback rate (e.g., 0.5, 1.0, 1.5, 2.0)
     */
    setPlaybackRate(rate) {
        if (this.audioEl) {
            this.audioEl.playbackRate = rate;
        }
    }

    /**
     * Play a specific segment
     *
     * @param {string} segmentId - ID of segment to play
     */
    playSegment(segmentId) {
        if (!this.peaks) return;

        const segment = this.peaks.segments.getSegment(segmentId);
        if (segment) {
            this.peaks.player.playSegment(segment);
        }
    }

    // ==================== Zoom Controls ====================

    /**
     * Zoom in on waveform
     */
    zoomIn() {
        if (!this.peaks) return;
        const view = this.peaks.views.getView('zoomview');
        if (view) {
            view.setZoom({ scale: 'auto' });
            const currentZoom = view.getZoom();
            view.setZoom({ scale: Math.max(256, currentZoom / 2) });
        }
    }

    /**
     * Zoom out on waveform
     */
    zoomOut() {
        if (!this.peaks) return;
        const view = this.peaks.views.getView('zoomview');
        if (view) {
            const currentZoom = view.getZoom();
            view.setZoom({ scale: Math.min(4096, currentZoom * 2) });
        }
    }

    /**
     * Zoom to fit entire waveform
     */
    zoomToFit() {
        if (!this.peaks) return;
        const view = this.peaks.views.getView('zoomview');
        if (view) {
            view.setZoom({ scale: 'auto' });
        }
    }

    // ==================== Selection ====================

    /**
     * Set selection start at current playback position
     */
    setSelectionStart() {
        if (!this.peaks) return;
        this.selectionStart = this.peaks.player.getCurrentTime();
        console.log('Selection start:', this.selectionStart);
        this._updateStatus(`Selection start: ${this._formatTime(this.selectionStart)}`);
    }

    /**
     * Set selection end at current playback position
     */
    setSelectionEnd() {
        if (!this.peaks) return;
        this.selectionEnd = this.peaks.player.getCurrentTime();
        console.log('Selection end:', this.selectionEnd);
        this._updateStatus(`Selection end: ${this._formatTime(this.selectionEnd)}`);
    }

    // ==================== Segment Management ====================

    /**
     * Set the active label for new segments
     *
     * @param {string} label - Label name
     * @param {string} color - Label color (hex)
     */
    setActiveLabel(label, color) {
        this.activeLabel = label;
        this.activeLabelColor = color;
        console.log('Active label set:', label, color);
    }

    /**
     * Create a segment from the current selection
     */
    createSegmentFromSelection() {
        if (this.selectionStart === null || this.selectionEnd === null) {
            this._updateStatus('Set selection start ([) and end (]) first');
            return;
        }

        // Ensure start < end
        const start = Math.min(this.selectionStart, this.selectionEnd);
        const end = Math.max(this.selectionStart, this.selectionEnd);

        if (end - start < 0.1) {
            this._updateStatus('Selection too short (minimum 0.1 seconds)');
            return;
        }

        this.createSegment(start, end);

        // Clear selection
        this.selectionStart = null;
        this.selectionEnd = null;
    }

    /**
     * Create a new segment
     *
     * @param {number} startTime - Start time in seconds
     * @param {number} endTime - End time in seconds
     * @param {string} [label] - Label for the segment
     * @param {string} [color] - Color for the segment
     * @param {string} [id] - Segment ID (auto-generated if not provided)
     * @returns {Object} The created segment
     */
    createSegment(startTime, endTime, label = null, color = null, id = null) {
        if (!this.peaks) return null;

        // Check max segments
        if (this.config.maxSegments && this.segments.length >= this.config.maxSegments) {
            this._updateStatus(`Maximum ${this.config.maxSegments} segments allowed`);
            return null;
        }

        const segmentId = id || `segment_${++this.segmentCounter}`;
        const segmentLabel = label || this.activeLabel || 'unlabeled';
        const segmentColor = color || this.activeLabelColor || '#4ECDC4';

        const segment = this.peaks.segments.add({
            id: segmentId,
            startTime: startTime,
            endTime: endTime,
            labelText: segmentLabel,
            color: segmentColor,
            editable: true
        });

        // Track segment data
        const segmentData = {
            id: segmentId,
            startTime: startTime,
            endTime: endTime,
            label: segmentLabel,
            color: segmentColor,
            annotations: {} // For questions mode
        };
        this.segments.push(segmentData);

        // Update UI
        this._updateSegmentList();
        this._updateSegmentCount();
        this._saveData();

        // Select the new segment
        this.selectSegment(segmentId);

        console.log('Created segment:', segmentData);
        return segmentData;
    }

    /**
     * Delete a segment by ID
     *
     * @param {string} segmentId - ID of segment to delete
     */
    deleteSegment(segmentId) {
        if (!this.peaks) return;

        // Remove from Peaks.js
        this.peaks.segments.removeById(segmentId);

        // Remove from our tracking
        const index = this.segments.findIndex(s => s.id === segmentId);
        if (index !== -1) {
            this.segments.splice(index, 1);
        }

        // Clear selection if this was selected
        if (this.activeSegmentId === segmentId) {
            this.activeSegmentId = null;
            this._hideQuestionsPanel();
        }

        // Update UI
        this._updateSegmentList();
        this._updateSegmentCount();
        this._updateDeleteButton();
        this._saveData();

        console.log('Deleted segment:', segmentId);
    }

    /**
     * Delete the currently selected segment
     */
    deleteSelectedSegment() {
        if (this.activeSegmentId) {
            this.deleteSegment(this.activeSegmentId);
        }
    }

    /**
     * Select a segment
     *
     * @param {string} segmentId - ID of segment to select
     */
    selectSegment(segmentId) {
        this.activeSegmentId = segmentId;

        // Update visual selection in segment list
        this._updateSegmentListSelection();

        // Update delete button state
        this._updateDeleteButton();

        // Show questions panel if in questions/both mode
        if (this.config.mode === 'questions' || this.config.mode === 'both') {
            this._showQuestionsPanel(segmentId);
        }

        console.log('Selected segment:', segmentId);
    }

    /**
     * Update segment label
     *
     * @param {string} segmentId - ID of segment
     * @param {string} label - New label
     * @param {string} [color] - New color
     */
    updateSegmentLabel(segmentId, label, color = null) {
        if (!this.peaks) return;

        const segment = this.peaks.segments.getSegment(segmentId);
        if (segment) {
            segment.update({
                labelText: label,
                color: color || segment.color
            });
        }

        // Update our tracking
        const segmentData = this.segments.find(s => s.id === segmentId);
        if (segmentData) {
            segmentData.label = label;
            if (color) segmentData.color = color;
        }

        this._updateSegmentList();
        this._saveData();
    }

    // ==================== Event Handlers ====================

    /**
     * Handle segment click
     */
    _onSegmentClick(event) {
        this.selectSegment(event.segment.id);
    }

    /**
     * Handle segment drag end (resize)
     */
    _onSegmentDragEnd(event) {
        const segment = event.segment;
        const segmentData = this.segments.find(s => s.id === segment.id);

        if (segmentData) {
            segmentData.startTime = segment.startTime;
            segmentData.endTime = segment.endTime;
        }

        this._updateSegmentList();
        this._saveData();
    }

    // ==================== UI Updates ====================

    /**
     * Update play button icon
     */
    _updatePlayButton() {
        const playBtn = this.container.querySelector('.playback-btn[data-action="play"]');
        if (playBtn) {
            const playIcon = playBtn.querySelector('.play-icon');
            const pauseIcon = playBtn.querySelector('.pause-icon');
            if (playIcon && pauseIcon) {
                playIcon.style.display = this.isPlaying ? 'none' : 'inline';
                pauseIcon.style.display = this.isPlaying ? 'inline' : 'none';
            }
        }
    }

    /**
     * Update time display
     */
    _updateTimeDisplay(currentTime = 0) {
        const currentTimeEl = this.container.querySelector('.current-time');
        const totalTimeEl = this.container.querySelector('.total-time');

        if (currentTimeEl) {
            currentTimeEl.textContent = this._formatTime(currentTime);
        }

        if (totalTimeEl && this.peaks) {
            const duration = this.peaks.player.getDuration();
            totalTimeEl.textContent = this._formatTime(duration);
        }
    }

    /**
     * Update segment count display
     */
    _updateSegmentCount() {
        const countEl = this.container.querySelector('.count-value');
        if (countEl) {
            countEl.textContent = this.segments.length;
        }
    }

    /**
     * Update delete button enabled state
     */
    _updateDeleteButton() {
        const deleteBtn = this.container.querySelector('.delete-btn');
        if (deleteBtn) {
            deleteBtn.disabled = !this.activeSegmentId;
        }
    }

    /**
     * Update label buttons to show active state
     */
    _updateLabelButtons(activeLabel) {
        const buttons = this.container.querySelectorAll('.label-btn');
        buttons.forEach(btn => {
            if (btn.dataset.label === activeLabel) {
                btn.classList.add('active');
            } else {
                btn.classList.remove('active');
            }
        });
    }

    /**
     * Update segment list UI
     */
    _updateSegmentList() {
        if (!this.segmentListEl) return;

        // Sort segments by start time
        const sortedSegments = [...this.segments].sort((a, b) => a.startTime - b.startTime);

        let html = '';
        for (const segment of sortedSegments) {
            const isActive = segment.id === this.activeSegmentId;
            html += `
                <div class="segment-item ${isActive ? 'active' : ''}" data-segment-id="${segment.id}">
                    <div class="segment-color" style="background-color: ${segment.color};"></div>
                    <div class="segment-info">
                        <span class="segment-label">${this._escapeHtml(segment.label)}</span>
                        <span class="segment-time">${this._formatTime(segment.startTime)} - ${this._formatTime(segment.endTime)}</span>
                    </div>
                    <div class="segment-actions">
                        <button type="button" class="segment-play-btn" title="Play segment">
                            <span>&#9658;</span>
                        </button>
                        <button type="button" class="segment-delete-btn" title="Delete segment">
                            <span>&times;</span>
                        </button>
                    </div>
                </div>
            `;
        }

        this.segmentListEl.innerHTML = html;

        // Add event listeners
        this.segmentListEl.querySelectorAll('.segment-item').forEach(item => {
            const segmentId = item.dataset.segmentId;

            item.addEventListener('click', (e) => {
                if (!e.target.closest('.segment-actions')) {
                    this.selectSegment(segmentId);
                }
            });

            const playBtn = item.querySelector('.segment-play-btn');
            if (playBtn) {
                playBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.playSegment(segmentId);
                });
            }

            const deleteBtn = item.querySelector('.segment-delete-btn');
            if (deleteBtn) {
                deleteBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.deleteSegment(segmentId);
                });
            }
        });
    }

    /**
     * Update segment list selection highlight
     */
    _updateSegmentListSelection() {
        if (!this.segmentListEl) return;

        this.segmentListEl.querySelectorAll('.segment-item').forEach(item => {
            if (item.dataset.segmentId === this.activeSegmentId) {
                item.classList.add('active');
            } else {
                item.classList.remove('active');
            }
        });
    }

    /**
     * Show questions panel for a segment
     */
    _showQuestionsPanel(segmentId) {
        if (!this.questionsEl || !this.config.segmentSchemes) return;

        const segmentData = this.segments.find(s => s.id === segmentId);
        if (!segmentData) return;

        this.questionsEl.style.display = 'block';

        const contentEl = this.questionsEl.querySelector('.segment-questions-content');
        if (!contentEl) return;

        // Generate form for segment questions
        let html = `<p class="segment-questions-header">Annotating: ${this._escapeHtml(segmentData.label)} (${this._formatTime(segmentData.startTime)} - ${this._formatTime(segmentData.endTime)})</p>`;

        // TODO: Generate actual form fields based on segmentSchemes
        // For now, show placeholder
        html += '<p class="segment-questions-placeholder">Segment annotation questions will appear here.</p>';

        contentEl.innerHTML = html;
    }

    /**
     * Hide questions panel
     */
    _hideQuestionsPanel() {
        if (this.questionsEl) {
            this.questionsEl.style.display = 'none';
        }
    }

    /**
     * Show status message
     */
    _updateStatus(message) {
        // Use the main status element if available
        const statusEl = document.getElementById('status');
        if (statusEl) {
            statusEl.textContent = message;
            statusEl.style.display = 'block';
            setTimeout(() => {
                statusEl.style.display = 'none';
            }, 3000);
        } else {
            console.log('Status:', message);
        }
    }

    /**
     * Show error message
     */
    _showError(message) {
        console.error(message);
        this._updateStatus(message);
    }

    // ==================== Data Persistence ====================

    /**
     * Save segment data to hidden input
     */
    _saveData() {
        if (!this.inputEl) return;

        const data = {
            segments: this.segments.map(s => ({
                id: s.id,
                start_time: s.startTime,
                end_time: s.endTime,
                label: s.label,
                annotations: s.annotations || {}
            }))
        };

        this.inputEl.value = JSON.stringify(data);
        console.log('Saved audio annotation data:', data);
    }

    /**
     * Load existing annotations from hidden input
     */
    _loadExistingAnnotations() {
        if (!this.inputEl || !this.inputEl.value) return;

        try {
            const data = JSON.parse(this.inputEl.value);
            if (data && data.segments && Array.isArray(data.segments)) {
                for (const seg of data.segments) {
                    this.createSegment(
                        seg.start_time,
                        seg.end_time,
                        seg.label,
                        this._getLabelColor(seg.label),
                        seg.id
                    );

                    // Restore annotations
                    const segmentData = this.segments.find(s => s.id === seg.id);
                    if (segmentData && seg.annotations) {
                        segmentData.annotations = seg.annotations;
                    }
                }
                console.log('Loaded existing annotations:', data.segments.length, 'segments');
            }
        } catch (e) {
            console.warn('Failed to load existing annotations:', e);
        }
    }

    /**
     * Get color for a label
     */
    _getLabelColor(label) {
        if (!this.config.labels) return '#4ECDC4';

        const labelConfig = this.config.labels.find(l => l.name === label);
        return labelConfig ? labelConfig.color : '#4ECDC4';
    }

    /**
     * Serialize annotation data
     */
    serialize() {
        return {
            segments: this.segments.map(s => ({
                id: s.id,
                start_time: s.startTime,
                end_time: s.endTime,
                label: s.label,
                annotations: s.annotations || {}
            }))
        };
    }

    /**
     * Deserialize annotation data
     */
    deserialize(data) {
        if (!data || !data.segments) return;

        // Clear existing segments
        this.segments.forEach(s => {
            if (this.peaks) {
                this.peaks.segments.removeById(s.id);
            }
        });
        this.segments = [];

        // Load segments
        for (const seg of data.segments) {
            this.createSegment(
                seg.start_time,
                seg.end_time,
                seg.label,
                this._getLabelColor(seg.label),
                seg.id
            );
        }
    }

    // ==================== Utility Methods ====================

    /**
     * Format time in M:SS format
     */
    _formatTime(seconds) {
        if (!seconds && seconds !== 0) return '0:00';
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        return `${mins}:${secs.toString().padStart(2, '0')}`;
    }

    /**
     * Escape HTML special characters
     */
    _escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    /**
     * Destroy the manager and clean up
     */
    destroy() {
        // Remove keyboard listener
        document.removeEventListener('keydown', this._handleKeydown);

        // Destroy Peaks.js
        if (this.peaks) {
            this.peaks.destroy();
            this.peaks = null;
        }

        console.log('AudioAnnotationManager destroyed');
    }
}

// Export for use
window.AudioAnnotationManager = AudioAnnotationManager;

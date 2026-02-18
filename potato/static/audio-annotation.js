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

// Debug logging utility - respects the debug setting from server config
function audioDebugLog(...args) {
    if (window.config && window.config.debug) {
        console.log(...args);
    }
}

/**
 * Color maps for spectrogram visualization
 * Each color map is an array of RGB arrays for gradient interpolation
 */
const SPECTROGRAM_COLORMAPS = {
    viridis: [
        [68, 1, 84],
        [72, 40, 120],
        [62, 73, 137],
        [49, 104, 142],
        [38, 130, 142],
        [31, 158, 137],
        [53, 183, 121],
        [109, 205, 89],
        [180, 222, 44],
        [253, 231, 37]
    ],
    magma: [
        [0, 0, 4],
        [28, 16, 68],
        [79, 18, 123],
        [129, 37, 129],
        [181, 54, 122],
        [229, 80, 100],
        [251, 135, 97],
        [254, 194, 135],
        [252, 253, 191]
    ],
    plasma: [
        [13, 8, 135],
        [75, 3, 161],
        [125, 3, 168],
        [168, 34, 150],
        [203, 70, 121],
        [229, 107, 93],
        [248, 148, 65],
        [253, 195, 40],
        [240, 249, 33]
    ],
    inferno: [
        [0, 0, 4],
        [31, 12, 72],
        [85, 15, 109],
        [136, 34, 106],
        [186, 54, 85],
        [227, 89, 51],
        [249, 140, 10],
        [249, 201, 50],
        [252, 255, 164]
    ],
    grayscale: [
        [0, 0, 0],
        [255, 255, 255]
    ]
};

/**
 * SpectrogramRenderer - Renders spectrogram visualization of audio using Web Audio API
 *
 * Features:
 * - Real-time FFT computation using AnalyserNode
 * - Offline rendering for full audio buffer
 * - Color mapping with multiple colormap options
 * - Synchronized playhead with waveform
 * - Zoom and scroll support
 */
class SpectrogramRenderer {
    /**
     * Create a SpectrogramRenderer instance.
     *
     * @param {Object} options - Configuration options
     * @param {HTMLCanvasElement} options.canvas - Main canvas for spectrogram
     * @param {HTMLCanvasElement} options.playheadCanvas - Overlay canvas for playhead
     * @param {Object} options.spectrogramOptions - FFT and display options
     */
    constructor(options) {
        this.canvas = options.canvas;
        this.playheadCanvas = options.playheadCanvas;
        this.options = {
            fftSize: 2048,
            hopLength: 512,
            frequencyRange: [0, 8000],
            colorMap: 'viridis',
            ...options.spectrogramOptions
        };

        this.ctx = this.canvas ? this.canvas.getContext('2d') : null;
        this.playheadCtx = this.playheadCanvas ? this.playheadCanvas.getContext('2d') : null;

        // Audio context and data
        this.audioContext = null;
        this.audioBuffer = null;
        this.spectrogramData = null;

        // View state (for zoom/scroll synchronization)
        this.viewStartTime = 0;
        this.viewEndTime = 0;
        this.duration = 0;

        // Playhead position
        this.playheadTime = 0;

        // Build color lookup table for performance
        this._buildColorLUT();

        audioDebugLog('[Spectrogram] SpectrogramRenderer initialized with options:', this.options);
    }

    /**
     * Build color lookup table for fast rendering
     */
    _buildColorLUT() {
        const colormap = SPECTROGRAM_COLORMAPS[this.options.colorMap] || SPECTROGRAM_COLORMAPS.viridis;
        this.colorLUT = new Uint8ClampedArray(256 * 4);

        for (let i = 0; i < 256; i++) {
            const t = i / 255;
            const color = this._interpolateColor(colormap, t);
            this.colorLUT[i * 4] = color[0];
            this.colorLUT[i * 4 + 1] = color[1];
            this.colorLUT[i * 4 + 2] = color[2];
            this.colorLUT[i * 4 + 3] = 255;
        }
    }

    /**
     * Interpolate between colors in a colormap
     *
     * @param {Array} colormap - Array of RGB color arrays
     * @param {number} t - Value between 0 and 1
     * @returns {Array} RGB color array
     */
    _interpolateColor(colormap, t) {
        const n = colormap.length - 1;
        const i = Math.min(Math.floor(t * n), n - 1);
        const f = t * n - i;

        const c1 = colormap[i];
        const c2 = colormap[i + 1];

        return [
            Math.round(c1[0] + f * (c2[0] - c1[0])),
            Math.round(c1[1] + f * (c2[1] - c1[1])),
            Math.round(c1[2] + f * (c2[2] - c1[2]))
        ];
    }

    /**
     * Compute spectrogram from audio buffer using offline FFT
     *
     * @param {AudioBuffer} audioBuffer - The audio buffer to analyze
     * @returns {Promise<Float32Array[]>} 2D array of FFT magnitudes
     */
    async computeSpectrogram(audioBuffer) {
        audioDebugLog('[Spectrogram] Computing spectrogram for buffer:', audioBuffer.duration, 'seconds');

        this.audioBuffer = audioBuffer;
        this.duration = audioBuffer.duration;

        // Get audio data (mono or first channel)
        const channelData = audioBuffer.getChannelData(0);
        const sampleRate = audioBuffer.sampleRate;

        const fftSize = this.options.fftSize;
        const hopLength = this.options.hopLength;
        const numFrames = Math.floor((channelData.length - fftSize) / hopLength) + 1;

        // Compute frequency bin indices for the frequency range
        const minFreq = this.options.frequencyRange[0];
        const maxFreq = Math.min(this.options.frequencyRange[1], sampleRate / 2);
        const freqPerBin = sampleRate / fftSize;
        const minBin = Math.floor(minFreq / freqPerBin);
        const maxBin = Math.min(Math.ceil(maxFreq / freqPerBin), fftSize / 2);
        const numBins = maxBin - minBin;

        audioDebugLog('[Spectrogram] FFT params:', {
            fftSize,
            hopLength,
            numFrames,
            minBin,
            maxBin,
            numBins,
            freqPerBin
        });

        // Create offline audio context for FFT computation
        const offlineCtx = new OfflineAudioContext(1, channelData.length, sampleRate);
        const analyser = offlineCtx.createAnalyser();
        analyser.fftSize = fftSize;
        analyser.smoothingTimeConstant = 0;

        // Allocate spectrogram data array
        this.spectrogramData = new Float32Array(numFrames * numBins);

        // Use a ScriptProcessor approach for frame-by-frame FFT
        // Note: For better performance with large files, we compute manually
        const fftData = new Float32Array(analyser.frequencyBinCount);

        // Window function (Hann window)
        const window = new Float32Array(fftSize);
        for (let i = 0; i < fftSize; i++) {
            window[i] = 0.5 * (1 - Math.cos(2 * Math.PI * i / (fftSize - 1)));
        }

        // Manual FFT computation using Web Audio API AnalyserNode workaround
        // Since OfflineAudioContext doesn't support real-time analysis well,
        // we'll use a simpler approach: create short audio buffers and analyze them

        // For now, use a simplified FFT using real-time analysis
        // This is a compromise between accuracy and performance
        return this._computeSpectrogramRealTime(channelData, sampleRate, numFrames, numBins, minBin);
    }

    /**
     * Compute spectrogram using real-time-like FFT computation
     * This method creates a real AudioContext and processes the audio in chunks
     */
    async _computeSpectrogramRealTime(channelData, sampleRate, numFrames, numBins, minBin) {
        const fftSize = this.options.fftSize;
        const hopLength = this.options.hopLength;

        // Create audio context if needed
        if (!this.audioContext) {
            this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
        }

        // Create analyser
        const analyser = this.audioContext.createAnalyser();
        analyser.fftSize = fftSize;
        analyser.smoothingTimeConstant = 0;

        const fftData = new Uint8Array(analyser.frequencyBinCount);

        // Process in frames using OfflineAudioContext for accurate FFT
        // Create an offline context for each chunk
        const numChunks = Math.ceil(numFrames / 100);
        const framesPerChunk = Math.ceil(numFrames / numChunks);

        for (let chunk = 0; chunk < numChunks; chunk++) {
            const startFrame = chunk * framesPerChunk;
            const endFrame = Math.min((chunk + 1) * framesPerChunk, numFrames);

            for (let frame = startFrame; frame < endFrame; frame++) {
                const startSample = frame * hopLength;
                const endSample = Math.min(startSample + fftSize, channelData.length);

                // Extract frame data
                const frameData = channelData.slice(startSample, endSample);

                // Simple magnitude computation using DFT approximation
                // For performance, we use a simplified approach
                for (let bin = 0; bin < numBins; bin++) {
                    const actualBin = bin + minBin;
                    const freq = actualBin * sampleRate / fftSize;

                    // Compute magnitude at this frequency using Goertzel-like approach
                    let real = 0, imag = 0;
                    const omega = 2 * Math.PI * actualBin / fftSize;

                    for (let i = 0; i < frameData.length; i++) {
                        real += frameData[i] * Math.cos(omega * i);
                        imag -= frameData[i] * Math.sin(omega * i);
                    }

                    const magnitude = Math.sqrt(real * real + imag * imag) / fftSize;
                    // Convert to dB scale (with minimum threshold)
                    const db = 20 * Math.log10(Math.max(magnitude, 1e-10));
                    // Normalize to 0-1 range (assuming -100 to 0 dB range)
                    const normalized = Math.max(0, Math.min(1, (db + 100) / 100));

                    this.spectrogramData[frame * numBins + bin] = normalized;
                }
            }

            // Yield to prevent UI blocking
            if (chunk % 10 === 0) {
                await new Promise(resolve => setTimeout(resolve, 0));
            }
        }

        audioDebugLog('[Spectrogram] Spectrogram computation complete');
        return { numFrames, numBins };
    }

    /**
     * Render the spectrogram to the canvas
     *
     * @param {number} startTime - Start time of visible region
     * @param {number} endTime - End time of visible region
     */
    render(startTime = 0, endTime = null) {
        if (!this.ctx || !this.spectrogramData || !this.audioBuffer) {
            audioDebugLog('[Spectrogram] Cannot render: missing context or data');
            return;
        }

        endTime = endTime || this.duration;
        this.viewStartTime = startTime;
        this.viewEndTime = endTime;

        const canvas = this.canvas;
        const ctx = this.ctx;
        const width = canvas.width;
        const height = canvas.height;

        // Clear canvas
        ctx.clearRect(0, 0, width, height);

        const fftSize = this.options.fftSize;
        const hopLength = this.options.hopLength;
        const sampleRate = this.audioBuffer.sampleRate;

        // Calculate frame range for visible region
        const samplesPerFrame = hopLength;
        const startFrame = Math.floor((startTime * sampleRate) / samplesPerFrame);
        const endFrame = Math.ceil((endTime * sampleRate) / samplesPerFrame);
        const numVisibleFrames = endFrame - startFrame;

        // Get spectrogram dimensions
        const minFreq = this.options.frequencyRange[0];
        const maxFreq = Math.min(this.options.frequencyRange[1], sampleRate / 2);
        const freqPerBin = sampleRate / fftSize;
        const minBin = Math.floor(minFreq / freqPerBin);
        const maxBin = Math.min(Math.ceil(maxFreq / freqPerBin), fftSize / 2);
        const numBins = maxBin - minBin;

        // Create ImageData for efficient rendering
        const imageData = ctx.createImageData(width, height);
        const data = imageData.data;

        // Calculate total frames in spectrogram
        const totalFrames = Math.floor((this.audioBuffer.length - fftSize) / hopLength) + 1;

        // Render each pixel
        for (let x = 0; x < width; x++) {
            // Map x to frame index
            const frameFloat = startFrame + (x / width) * numVisibleFrames;
            const frame = Math.floor(frameFloat);

            if (frame < 0 || frame >= totalFrames) continue;

            for (let y = 0; y < height; y++) {
                // Map y to frequency bin (inverted - high frequencies at top)
                const binFloat = (1 - y / height) * numBins;
                const bin = Math.floor(binFloat);

                if (bin < 0 || bin >= numBins) continue;

                // Get spectrogram value
                const idx = frame * numBins + bin;
                const value = this.spectrogramData[idx] || 0;

                // Map value to color using LUT
                const colorIdx = Math.floor(value * 255) * 4;
                const pixelIdx = (y * width + x) * 4;

                data[pixelIdx] = this.colorLUT[colorIdx];
                data[pixelIdx + 1] = this.colorLUT[colorIdx + 1];
                data[pixelIdx + 2] = this.colorLUT[colorIdx + 2];
                data[pixelIdx + 3] = 255;
            }
        }

        ctx.putImageData(imageData, 0, 0);

        // Draw frequency axis labels
        this._drawFrequencyAxis(ctx, width, height, minFreq, maxFreq);

        audioDebugLog('[Spectrogram] Rendered spectrogram from', startTime, 'to', endTime);
    }

    /**
     * Draw frequency axis labels on the spectrogram
     */
    _drawFrequencyAxis(ctx, width, height, minFreq, maxFreq) {
        ctx.fillStyle = 'rgba(255, 255, 255, 0.8)';
        ctx.font = '10px sans-serif';
        ctx.textAlign = 'left';

        const freqSteps = [100, 500, 1000, 2000, 4000, 8000];
        for (const freq of freqSteps) {
            if (freq >= minFreq && freq <= maxFreq) {
                const y = height * (1 - (freq - minFreq) / (maxFreq - minFreq));
                ctx.fillText(`${freq >= 1000 ? (freq / 1000) + 'k' : freq} Hz`, 4, y + 4);
            }
        }
    }

    /**
     * Update playhead position
     *
     * @param {number} time - Current playhead time in seconds
     */
    updatePlayhead(time) {
        if (!this.playheadCtx || !this.playheadCanvas) return;

        this.playheadTime = time;

        const canvas = this.playheadCanvas;
        const ctx = this.playheadCtx;
        const width = canvas.width;
        const height = canvas.height;

        // Clear canvas
        ctx.clearRect(0, 0, width, height);

        // Calculate playhead x position
        if (time >= this.viewStartTime && time <= this.viewEndTime) {
            const x = (time - this.viewStartTime) / (this.viewEndTime - this.viewStartTime) * width;

            // Draw playhead line
            ctx.strokeStyle = '#ff4444';
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.moveTo(x, 0);
            ctx.lineTo(x, height);
            ctx.stroke();
        }
    }

    /**
     * Resize the spectrogram canvas
     *
     * @param {number} width - New width
     * @param {number} height - New height
     */
    resize(width, height) {
        if (this.canvas) {
            this.canvas.width = width;
            this.canvas.height = height;
        }
        if (this.playheadCanvas) {
            this.playheadCanvas.width = width;
            this.playheadCanvas.height = height;
        }

        // Re-render if we have data
        if (this.spectrogramData) {
            this.render(this.viewStartTime, this.viewEndTime);
        }
    }

    /**
     * Update color map
     *
     * @param {string} colorMap - Color map name
     */
    setColorMap(colorMap) {
        if (SPECTROGRAM_COLORMAPS[colorMap]) {
            this.options.colorMap = colorMap;
            this._buildColorLUT();
            if (this.spectrogramData) {
                this.render(this.viewStartTime, this.viewEndTime);
            }
        }
    }

    /**
     * Clean up resources
     */
    destroy() {
        if (this.audioContext && this.audioContext.state !== 'closed') {
            // Don't close the shared context
        }
        this.spectrogramData = null;
        this.audioBuffer = null;
        audioDebugLog('[Spectrogram] SpectrogramRenderer destroyed');
    }
}

// Export SpectrogramRenderer
window.SpectrogramRenderer = SpectrogramRenderer;

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
     * @param {string} options.spectrogramId - ID of spectrogram container element
     * @param {string} options.spectrogramCanvasId - ID of spectrogram canvas element
     * @param {string} options.spectrogramPlayheadId - ID of spectrogram playhead canvas element
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
        this.spectrogramId = options.spectrogramId;
        this.spectrogramCanvasId = options.spectrogramCanvasId;
        this.spectrogramPlayheadId = options.spectrogramPlayheadId;
        this.config = options.config || {};

        // State
        this.peaks = null;
        this.segments = [];
        this.activeSegmentId = null;
        this.activeLabel = null;
        this.activeLabelColor = null;
        this.isPlaying = false;
        this.segmentCounter = 0;

        // Spectrogram renderer
        this.spectrogramRenderer = null;

        // Ready state for tests to wait on
        this.isReady = false;
        this.readyPromise = null;
        this._resolveReady = null;

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
        this.spectrogramContainerEl = document.getElementById(this.spectrogramId);
        this.spectrogramCanvasEl = document.getElementById(this.spectrogramCanvasId);
        this.spectrogramPlayheadEl = document.getElementById(this.spectrogramPlayheadId);

        // Bind methods
        this._onSegmentClick = this._onSegmentClick.bind(this);
        this._onSegmentDragEnd = this._onSegmentDragEnd.bind(this);
        this._handleKeydown = this._handleKeydown.bind(this);

        // Set up keyboard shortcuts
        this._setupKeyboardShortcuts();

        // Initialize spectrogram if enabled
        if (this.config.spectrogram && this.spectrogramCanvasEl) {
            this._initSpectrogram();
        }

        audioDebugLog('AudioAnnotationManager initialized:', this.config.schemaName);
    }

    /**
     * Initialize spectrogram renderer
     */
    _initSpectrogram() {
        audioDebugLog('[AudioAnnotation] Initializing spectrogram renderer');

        // Set canvas dimensions based on container
        if (this.spectrogramContainerEl) {
            const rect = this.spectrogramContainerEl.getBoundingClientRect();
            const width = rect.width || 800;
            const height = 150; // Fixed height for spectrogram

            if (this.spectrogramCanvasEl) {
                this.spectrogramCanvasEl.width = width;
                this.spectrogramCanvasEl.height = height;
            }
            if (this.spectrogramPlayheadEl) {
                this.spectrogramPlayheadEl.width = width;
                this.spectrogramPlayheadEl.height = height;
            }
        }

        this.spectrogramRenderer = new SpectrogramRenderer({
            canvas: this.spectrogramCanvasEl,
            playheadCanvas: this.spectrogramPlayheadEl,
            spectrogramOptions: this.config.spectrogramOptions || {}
        });
    }

    /**
     * Load audio and initialize Peaks.js
     *
     * @param {string} audioUrl - URL of the audio file
     * @param {string} [waveformUrl] - URL of pre-computed waveform data (optional)
     */
    async loadAudio(audioUrl, waveformUrl = null) {
        audioDebugLog('Loading audio:', audioUrl);

        // Create ready promise for tests to wait on
        this.readyPromise = new Promise((resolve) => {
            this._resolveReady = resolve;
        });

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
            // segments must be an array (empty initially, segments added later)
            segments: [],
            // Segment display options
            segmentOptions: {
                markers: true,
                overlay: true,
                startMarkerColor: '#4a90d9',
                endMarkerColor: '#4a90d9',
                waveformColor: 'rgba(74, 144, 217, 0.4)'
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
            audioDebugLog('Peaks.js initialized successfully');

            // Set up event listeners
            this._setupPeaksEventListeners();

            // Update time display
            this._updateTimeDisplay();

            // Load existing annotations if any
            this._loadExistingAnnotations();

            // Initialize spectrogram if enabled
            if (this.spectrogramRenderer && this.config.spectrogram) {
                await this._loadSpectrogram(audioUrl);
            }

            // Mark as ready
            this.isReady = true;
            if (this._resolveReady) {
                this._resolveReady(true);
            }
            audioDebugLog('AudioAnnotationManager is ready');

        } catch (error) {
            console.error('Failed to initialize Peaks.js:', error);
            this._showError('Failed to load audio waveform. Please try refreshing the page.');
            // Still resolve the promise but with false
            this.isReady = false;
            if (this._resolveReady) {
                this._resolveReady(false);
            }
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
     * Load and compute spectrogram from audio URL
     *
     * @param {string} audioUrl - URL of the audio file
     */
    async _loadSpectrogram(audioUrl) {
        if (!this.spectrogramRenderer) return;

        audioDebugLog('[AudioAnnotation] Loading spectrogram for:', audioUrl);

        try {
            // Fetch audio data
            const response = await fetch(audioUrl);
            const arrayBuffer = await response.arrayBuffer();

            // Decode audio data
            const audioContext = new (window.AudioContext || window.webkitAudioContext)();
            const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);

            // Compute spectrogram
            await this.spectrogramRenderer.computeSpectrogram(audioBuffer);

            // Render initial view (full duration)
            const duration = audioBuffer.duration;
            this.spectrogramRenderer.render(0, duration);

            audioDebugLog('[AudioAnnotation] Spectrogram loaded successfully');

            // Close the temporary audio context
            await audioContext.close();

        } catch (error) {
            console.error('[AudioAnnotation] Failed to load spectrogram:', error);
            // Don't fail the whole load, just log the error
        }
    }

    /**
     * Update spectrogram view to match waveform zoom/scroll
     */
    _updateSpectrogramView() {
        if (!this.spectrogramRenderer || !this.peaks) return;

        const view = this.peaks.views.getView('zoomview');
        if (view) {
            const startTime = view.getStartTime();
            const endTime = view.getEndTime();
            this.spectrogramRenderer.render(startTime, endTime);
        }
    }

    /**
     * Set up Peaks.js event listeners
     */
    _setupPeaksEventListeners() {
        if (!this.peaks) return;

        try {
            // Playback events - register on peaks instance
            this.peaks.on('player.playing', () => {
                this.isPlaying = true;
                this._updatePlayButton();
            });

            this.peaks.on('player.pause', () => {
                this.isPlaying = false;
                this._updatePlayButton();
            });

            this.peaks.on('player.ended', () => {
                this.isPlaying = false;
                this._updatePlayButton();
            });

            this.peaks.on('player.timeupdate', (time) => {
                this._updateTimeDisplay(time);
                // Update spectrogram playhead
                if (this.spectrogramRenderer) {
                    this.spectrogramRenderer.updatePlayhead(time);
                }
            });

            // Segment events
            this.peaks.on('segments.click', this._onSegmentClick);
            this.peaks.on('segments.dragend', this._onSegmentDragEnd);

            // Zoom events - update spectrogram view
            this.peaks.on('zoom.update', () => {
                this._updateSpectrogramView();
            });

            audioDebugLog('Peaks.js event listeners set up successfully');
        } catch (e) {
            console.warn('Error setting up Peaks.js event listeners:', e);
            // Fall back to audio element events
            this._setupAudioElementEvents();
        }

        // Click and drag to select a region (using DOM events)
        this._setupDragSelection();
    }

    /**
     * Fallback: Set up events directly on the audio element
     */
    _setupAudioElementEvents() {
        if (!this.audioEl) return;

        this.audioEl.addEventListener('play', () => {
            this.isPlaying = true;
            this._updatePlayButton();
        });

        this.audioEl.addEventListener('pause', () => {
            this.isPlaying = false;
            this._updatePlayButton();
        });

        this.audioEl.addEventListener('ended', () => {
            this.isPlaying = false;
            this._updatePlayButton();
        });

        this.audioEl.addEventListener('timeupdate', () => {
            this._updateTimeDisplay(this.audioEl.currentTime);
        });

        audioDebugLog('Audio element event listeners set up as fallback');
    }

    /**
     * Set up click-and-drag selection on the waveform
     */
    _setupDragSelection() {
        if (!this.waveformEl || !this.peaks) return;

        let isDragging = false;
        let dragStartTime = null;
        let dragPreviewSegment = null;

        const getTimeFromMouseEvent = (event) => {
            const view = this.peaks.views.getView('zoomview');
            if (!view) return null;

            const rect = this.waveformEl.getBoundingClientRect();
            const x = event.clientX - rect.left;
            const duration = this.peaks.player.getDuration();

            // Get the visible time range from the view
            const startTime = view.getStartTime();
            const endTime = view.getEndTime();
            const visibleDuration = endTime - startTime;

            // Calculate time based on x position within the visible range
            const time = startTime + (x / rect.width) * visibleDuration;
            return Math.max(0, Math.min(time, duration));
        };

        const createPreviewSegment = (startTime, endTime) => {
            // Remove existing preview
            if (dragPreviewSegment) {
                try {
                    this.peaks.segments.removeById(dragPreviewSegment.id);
                } catch (e) {}
            }

            // Create a preview segment with a distinct style
            const start = Math.min(startTime, endTime);
            const end = Math.max(startTime, endTime);

            if (end - start < 0.01) return null; // Too small to show

            dragPreviewSegment = this.peaks.segments.add({
                id: 'drag-preview-' + Date.now(),
                startTime: start,
                endTime: end,
                color: 'rgba(100, 100, 255, 0.3)',
                editable: false
            });

            return dragPreviewSegment;
        };

        const removePreviewSegment = () => {
            if (dragPreviewSegment) {
                try {
                    this.peaks.segments.removeById(dragPreviewSegment.id);
                } catch (e) {}
                dragPreviewSegment = null;
            }
        };

        // Mouse down handler for starting drag-to-annotate
        // RIGHT-CLICK (button 2) is used for span creation
        // LEFT-CLICK (button 0) is left for Peaks.js navigation/seeking
        const handleMouseDown = (event) => {
            // Only handle right-click for span creation
            if (event.button !== 2) return;

            // Get the time at the click position
            const clickTime = getTimeFromMouseEvent(event);
            if (clickTime === null) return;

            audioDebugLog('Right-click drag start for annotation', { clickTime });

            isDragging = true;
            dragStartTime = clickTime;

            // Prevent context menu and default behavior
            event.preventDefault();
            event.stopPropagation();
        };

        // Prevent context menu on the waveform (since we use right-click for annotation)
        this.waveformEl.addEventListener('contextmenu', (event) => {
            event.preventDefault();
            return false;
        });

        // Register mousedown handler
        this.waveformEl.addEventListener('mousedown', handleMouseDown);

        // Mouse move handler - update preview (only when right-click dragging)
        const handleMouseMove = (event) => {
            if (!isDragging || dragStartTime === null) return;

            const currentTime = getTimeFromMouseEvent(event);
            if (currentTime === null) return;

            createPreviewSegment(dragStartTime, currentTime);
        };

        this.waveformEl.addEventListener('mousemove', handleMouseMove);

        // Mouse up - finish drag and create segment
        const finishDrag = (event) => {
            if (!isDragging || dragStartTime === null) return;

            const endTime = getTimeFromMouseEvent(event);
            removePreviewSegment();

            if (endTime !== null) {
                const start = Math.min(dragStartTime, endTime);
                const end = Math.max(dragStartTime, endTime);

                // Only create segment if it's at least 0.1 seconds
                if (end - start >= 0.1) {
                    audioDebugLog('Creating segment from right-click drag', { start, end });
                    this.createSegment(start, end);
                }
            }

            isDragging = false;
            dragStartTime = null;
        };

        this.waveformEl.addEventListener('mouseup', finishDrag);

        // Also handle mouse leaving the waveform area
        this.waveformEl.addEventListener('mouseleave', (event) => {
            if (isDragging) {
                finishDrag(event);
            }
        });
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
            // Update spectrogram to match
            this._updateSpectrogramView();
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
            // Update spectrogram to match
            this._updateSpectrogramView();
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
            // Update spectrogram to match
            this._updateSpectrogramView();
        }
    }

    // ==================== Selection ====================

    /**
     * Set selection start at current playback position
     */
    setSelectionStart() {
        if (!this.peaks) return;
        this.selectionStart = this.peaks.player.getCurrentTime();
        audioDebugLog('Selection start:', this.selectionStart);
        this._updateStatus(`Selection start: ${this._formatTime(this.selectionStart)}`);
    }

    /**
     * Set selection end at current playback position
     */
    setSelectionEnd() {
        if (!this.peaks) return;
        this.selectionEnd = this.peaks.player.getCurrentTime();
        audioDebugLog('Selection end:', this.selectionEnd);
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
        audioDebugLog('Active label set:', label, color);
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

        audioDebugLog('Created segment:', segmentData);
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

        audioDebugLog('Deleted segment:', segmentId);
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

        audioDebugLog('Selected segment:', segmentId);
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
            audioDebugLog('Status:', message);
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
        audioDebugLog('Saved audio annotation data:', data);
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
                audioDebugLog('Loaded existing annotations:', data.segments.length, 'segments');
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

        // Destroy spectrogram renderer
        if (this.spectrogramRenderer) {
            this.spectrogramRenderer.destroy();
            this.spectrogramRenderer = null;
        }

        audioDebugLog('AudioAnnotationManager destroyed');
    }
}

// Export for use
window.AudioAnnotationManager = AudioAnnotationManager;

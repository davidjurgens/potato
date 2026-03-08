/**
 * Web Agent Interaction Recorder
 *
 * Records user interactions within a proxied iframe or Playwright session
 * for building web agent browsing traces.
 *
 * Captures: clicks, typing, scrolling, mouse paths, screenshots.
 * Produces structured step data compatible with the web_agent_trace display format.
 */

class InteractionRecorder {
    constructor(containerEl) {
        this.container = containerEl;
        this.iframe = containerEl.querySelector('.recorder-iframe');
        this.recording = false;
        this.steps = [];
        this.mousePath = [];
        this.mousePathThrottle = 50; // ms between mouse samples
        this.lastMouseTime = 0;
        this.startTime = null;
        this.mode = 'iframe'; // 'iframe' or 'playwright'
        this.sessionId = null;

        this._initUI();
        this._bindMessageListener();
    }

    _initUI() {
        // Recording controls
        this.startBtn = this.container.querySelector('.recorder-start');
        this.stopBtn = this.container.querySelector('.recorder-stop');
        this.statusEl = this.container.querySelector('.recorder-status');
        this.stepCountEl = this.container.querySelector('.recorder-step-count');
        this.urlInput = this.container.querySelector('.recorder-url');

        if (this.startBtn) {
            this.startBtn.addEventListener('click', () => this.startRecording());
        }
        if (this.stopBtn) {
            this.stopBtn.addEventListener('click', () => this.stopRecording());
        }
    }

    _bindMessageListener() {
        // Listen for messages from proxied iframe
        window.addEventListener('message', (event) => {
            if (!this.recording) return;

            const data = event.data;
            if (!data || !data.type) return;

            switch (data.type) {
                case 'proxy-interaction':
                    this._handleInteraction(data);
                    break;
                case 'proxy-mousemove':
                    this._handleMouseMove(data);
                    break;
                case 'proxy-page-loaded':
                    this._handlePageLoad(data);
                    break;
            }
        });
    }

    async startRecording() {
        const url = this.urlInput ? this.urlInput.value : '';
        if (!url) {
            this._setStatus('Please enter a URL');
            return;
        }

        this.recording = true;
        this.steps = [];
        this.mousePath = [];
        this.startTime = Date.now() / 1000;

        // Always start a server-side session first so we have a sessionId
        // for saving steps and screenshots regardless of mode
        try {
            const sessionResp = await fetch('/api/web_agent/start_session', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: url }),
            });
            const sessionData = await sessionResp.json();
            this.sessionId = sessionData.session_id;
        } catch (e) {
            console.warn('Failed to start server session:', e);
            this.sessionId = null;
        }

        // Check if URL is frameable
        try {
            const checkResp = await fetch(`/api/web_agent/check_frameable?url=${encodeURIComponent(url)}`);
            const checkData = await checkResp.json();

            if (checkData.frameable) {
                this.mode = 'iframe';
                this._loadInIframe(url);
            } else {
                this.mode = 'playwright';
                // Session already started above; just load the screenshot
                this._refreshPlaywrightScreenshot();
            }
        } catch (e) {
            // Default to iframe proxy
            this.mode = 'iframe';
            this._loadInIframe(url);
        }

        this._setStatus('Recording...');
        this._updateStepCount();

        if (this.startBtn) this.startBtn.disabled = true;
        if (this.stopBtn) this.stopBtn.disabled = false;
    }

    stopRecording() {
        this.recording = false;
        this._setStatus(`Stopped. ${this.steps.length} steps recorded.`);

        if (this.startBtn) this.startBtn.disabled = false;
        if (this.stopBtn) this.stopBtn.disabled = true;

        // Save the recording
        this._saveRecording();
    }

    _loadInIframe(url) {
        if (this.iframe) {
            this.iframe.src = `/api/web_agent/proxy/${url}`;
        }
    }

    async _startPlaywrightSession(url) {
        // Session is already started in startRecording().
        // Just load the initial screenshot.
        this._refreshPlaywrightScreenshot();
    }

    async _refreshPlaywrightScreenshot() {
        if (!this.sessionId) return;
        try {
            const resp = await fetch(`/api/web_agent/save_screenshot?session_id=${this.sessionId}`);
            const data = await resp.json();
            if (data.screenshot_url) {
                const img = this.container.querySelector('.playwright-screenshot');
                if (img) img.src = data.screenshot_url;
            }
        } catch (e) {
            console.warn('Screenshot refresh failed:', e);
        }
    }

    _handleInteraction(data) {
        const now = Date.now() / 1000;
        const timestamp = now - this.startTime;

        let actionType = 'click';
        let typedText = '';

        switch (data.eventType) {
            case 'click':
                actionType = 'click';
                break;
            case 'input':
                actionType = 'type';
                typedText = data.value || '';
                break;
            case 'scroll':
                actionType = 'scroll';
                break;
            case 'keydown':
                // Skip standalone keydown - wait for input event
                return;
        }

        const step = {
            step_index: this.steps.length,
            screenshot_url: '', // Will be filled by server
            action_type: actionType,
            element: data.target || {},
            coordinates: { x: data.x || 0, y: data.y || 0 },
            mouse_path: [...this.mousePath],
            thought: '',
            observation: '',
            timestamp: timestamp,
            viewport: { width: window.innerWidth, height: window.innerHeight },
            typed_text: typedText,
        };

        this.steps.push(step);
        this.mousePath = []; // Reset path for next step

        this._updateStepCount();
        this._saveStep(step);
    }

    _handleMouseMove(data) {
        this.mousePath.push([data.x, data.y]);
        // Keep path reasonable length
        if (this.mousePath.length > 200) {
            // Downsample: keep every other point
            this.mousePath = this.mousePath.filter((_, i) => i % 2 === 0);
        }
    }

    _handlePageLoad(data) {
        // Add a navigate step when page loads
        if (this.steps.length > 0) {
            const step = {
                step_index: this.steps.length,
                screenshot_url: '',
                action_type: 'navigate',
                element: { text: data.title || '' },
                coordinates: {},
                mouse_path: [],
                thought: '',
                observation: `Navigated to: ${data.url || ''}`,
                timestamp: (Date.now() / 1000) - this.startTime,
                viewport: { width: window.innerWidth, height: window.innerHeight },
            };
            this.steps.push(step);
            this._updateStepCount();
        }
    }

    async _saveStep(step) {
        try {
            await fetch('/api/web_agent/save_step', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    session_id: this.sessionId,
                    step: step,
                }),
            });
        } catch (e) {
            console.warn('Failed to save step:', e);
        }
    }

    async _saveRecording() {
        try {
            await fetch('/api/web_agent/end_session', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    session_id: this.sessionId,
                    steps: this.steps,
                }),
            });
        } catch (e) {
            console.warn('Failed to save recording:', e);
        }
    }

    getSteps() {
        return this.steps;
    }

    _setStatus(text) {
        if (this.statusEl) {
            this.statusEl.textContent = text;
        }
    }

    _updateStepCount() {
        if (this.stepCountEl) {
            this.stepCountEl.textContent = `${this.steps.length} steps`;
        }
    }
}

// Auto-initialize recorders
function initWebAgentRecorders() {
    const recorders = document.querySelectorAll('.web-agent-recorder');
    recorders.forEach(container => {
        if (!container._recorder) {
            container._recorder = new InteractionRecorder(container);
        }
    });
}

document.addEventListener('DOMContentLoaded', initWebAgentRecorders);

window.InteractionRecorder = InteractionRecorder;
window.initWebAgentRecorders = initWebAgentRecorders;

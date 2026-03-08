/**
 * Web Agent Viewer Controller
 *
 * Manages step-by-step navigation, overlay rendering, filmstrip interaction,
 * and per-step annotation coordination for web agent trace displays.
 *
 * Keyboard shortcuts (when viewer is focused):
 *   Left/Right arrows - Previous/Next step
 *   1 - Toggle click markers
 *   2 - Toggle bounding boxes
 *   3 - Toggle mouse paths
 *   4 - Toggle scroll indicators
 *   A - Show all overlays
 *   N - Hide all overlays
 */

class WebAgentViewer {
    constructor(containerEl) {
        this.container = containerEl;
        this.steps = [];
        this.currentStep = 0;
        this.overlayManager = null;
        this.focused = false;

        // Parse steps data
        const stepsJson = containerEl.getAttribute('data-steps');
        if (stepsJson) {
            try {
                this.steps = JSON.parse(stepsJson);
            } catch (e) {
                console.warn('[WebAgentViewer] Failed to parse steps data:', e);
            }
        }

        if (this.steps.length === 0) return;

        this._initElements();
        this._initOverlayManager();
        this._bindEvents();
        this._initFilmstrip();

        // Render first step overlays
        this.goToStep(0);
    }

    _initElements() {
        this.screenshotImg = this.container.querySelector('.step-screenshot');
        this.svgOverlay = this.container.querySelector('.overlay-layer');
        this.prevBtn = this.container.querySelector('.step-prev');
        this.nextBtn = this.container.querySelector('.step-next');
        this.stepCounter = this.container.querySelector('.step-counter');
        this.detailsPanel = this.container.querySelector('.step-details-content');
        this.filmstrip = this.container.querySelector('.filmstrip');
        this.perStepContainer = this.container.querySelector('.web-agent-per-step-annotations');
    }

    _initOverlayManager() {
        const screenshotContainer = this.container.querySelector('.screenshot-container');
        if (screenshotContainer) {
            this.overlayManager = new WebAgentOverlayManager(screenshotContainer);
        }
    }

    _bindEvents() {
        // Navigation buttons
        if (this.prevBtn) {
            this.prevBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.prevStep();
            });
        }
        if (this.nextBtn) {
            this.nextBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.nextStep();
            });
        }

        // Overlay toggle checkboxes
        const toggles = this.container.querySelectorAll('.overlay-toggle');
        toggles.forEach(toggle => {
            toggle.addEventListener('change', () => {
                const type = toggle.getAttribute('data-overlay');
                if (this.overlayManager) {
                    this.overlayManager.toggleOverlay(type, toggle.checked);
                }
            });
        });

        // Focus management - allow keyboard nav when viewer is clicked
        this.container.setAttribute('tabindex', '0');
        this.container.addEventListener('focus', () => { this.focused = true; });
        this.container.addEventListener('blur', () => { this.focused = false; });
        this.container.addEventListener('click', () => {
            this.container.focus();
        });

        // Keyboard shortcuts
        this.container.addEventListener('keydown', (e) => {
            this._handleKeydown(e);
        });
    }

    _handleKeydown(e) {
        // Only handle shortcuts when the viewer container is focused/active
        if (!this.focused) {
            return;
        }

        // Don't intercept if typing in an input
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' ||
            e.target.tagName === 'SELECT') {
            return;
        }

        switch (e.key) {
            case 'ArrowLeft':
                e.preventDefault();
                e.stopPropagation();
                this.prevStep();
                break;
            case 'ArrowRight':
                e.preventDefault();
                e.stopPropagation();
                this.nextStep();
                break;
            case '1':
                e.preventDefault();
                e.stopPropagation();
                this._toggleOverlayCheckbox('click');
                break;
            case '2':
                e.preventDefault();
                e.stopPropagation();
                this._toggleOverlayCheckbox('bbox');
                break;
            case '3':
                e.preventDefault();
                e.stopPropagation();
                this._toggleOverlayCheckbox('path');
                break;
            case '4':
                e.preventDefault();
                e.stopPropagation();
                this._toggleOverlayCheckbox('scroll');
                break;
            case 'a':
            case 'A':
                if (!e.ctrlKey && !e.metaKey) {
                    e.preventDefault();
                    e.stopPropagation();
                    this._setAllOverlays(true);
                }
                break;
            case 'n':
            case 'N':
                if (!e.ctrlKey && !e.metaKey) {
                    e.preventDefault();
                    e.stopPropagation();
                    this._setAllOverlays(false);
                }
                break;
        }
    }

    /**
     * Navigate to a specific step index.
     */
    goToStep(index) {
        if (index < 0 || index >= this.steps.length) return;
        this.currentStep = index;
        const step = this.steps[index];

        // Update screenshot
        if (this.screenshotImg) {
            const url = step.screenshot_url || '';
            if (url) {
                this.screenshotImg.src = url;
                this.screenshotImg.alt = `Step ${index} screenshot`;
                this.screenshotImg.style.display = '';
            } else {
                this.screenshotImg.style.display = 'none';
            }
        }

        // Update overlays
        if (this.overlayManager) {
            this.overlayManager.renderStep(step);
        }

        // Update step counter
        if (this.stepCounter) {
            this.stepCounter.textContent = `Step ${index + 1} of ${this.steps.length}`;
        }

        // Update navigation buttons
        if (this.prevBtn) {
            this.prevBtn.disabled = (index === 0);
        }
        if (this.nextBtn) {
            this.nextBtn.disabled = (index === this.steps.length - 1);
        }

        // Update details panel
        this._updateDetails(step, index);

        // Update filmstrip
        this._updateFilmstripActive(index);

        // Update per-step annotation container
        if (this.perStepContainer) {
            this.perStepContainer.setAttribute('data-step-index', String(index));
            // Dispatch event for annotation system to pick up
            this.container.dispatchEvent(new CustomEvent('web-agent-step-change', {
                detail: { stepIndex: index, step: step },
                bubbles: true,
            }));
        }
    }

    nextStep() {
        if (this.currentStep < this.steps.length - 1) {
            this.goToStep(this.currentStep + 1);
        }
    }

    prevStep() {
        if (this.currentStep > 0) {
            this.goToStep(this.currentStep - 1);
        }
    }

    _updateDetails(step, index) {
        if (!this.detailsPanel) return;

        const actionType = step.action_type || 'unknown';
        const colors = {
            click: 'rgba(255,152,0,0.2)',
            type: 'rgba(33,150,243,0.2)',
            scroll: 'rgba(76,175,80,0.2)',
            hover: 'rgba(156,39,176,0.2)',
            select: 'rgba(0,188,212,0.2)',
            navigate: 'rgba(63,81,181,0.2)',
            wait: 'rgba(158,158,158,0.2)',
            done: 'rgba(56,142,60,0.2)',
        };
        const badgeColor = colors[actionType] || 'rgba(158,158,158,0.2)';

        let html = `<div class="action-badge" style="background:${badgeColor}">${this._escapeHtml(actionType).toUpperCase()}</div>`;

        const ts = step.timestamp;
        if (ts !== undefined && ts !== '') {
            html += `<div class="step-timestamp">t=${this._escapeHtml(String(ts))}s</div>`;
        }

        if (step.thought) {
            html += `<div class="step-thought"><strong>Thought:</strong> ${this._escapeHtml(step.thought)}</div>`;
        }

        const element = step.element || {};
        if (element && typeof element === 'object') {
            const parts = [];
            ['tag', 'text', 'id', 'class'].forEach(k => {
                if (element[k]) parts.push(`${k}="${this._escapeHtml(String(element[k]))}"`);
            });
            if (parts.length > 0) {
                html += `<div class="step-element"><strong>Element:</strong> <code>${parts.join(' ')}</code></div>`;
            }
        }

        const coords = step.coordinates || {};
        if (coords.x !== undefined || coords.y !== undefined) {
            html += `<div class="step-coords"><strong>Coords:</strong> (${coords.x || 0}, ${coords.y || 0})</div>`;
        }

        const typed = step.typed_text || step.value || '';
        if (typed) {
            html += `<div class="step-typed"><strong>Typed:</strong> "${this._escapeHtml(typed)}"</div>`;
        }

        if (step.observation) {
            html += `<div class="step-observation"><strong>Observation:</strong> ${this._escapeHtml(step.observation)}</div>`;
        }

        this.detailsPanel.innerHTML = html;
    }

    _initFilmstrip() {
        if (!this.filmstrip) return;
        const thumbs = this.filmstrip.querySelectorAll('.filmstrip-thumb');
        thumbs.forEach(thumb => {
            thumb.addEventListener('click', () => {
                const stepIdx = parseInt(thumb.getAttribute('data-step'), 10);
                if (!isNaN(stepIdx)) {
                    this.goToStep(stepIdx);
                }
            });
        });
    }

    _updateFilmstripActive(index) {
        if (!this.filmstrip) return;
        const thumbs = this.filmstrip.querySelectorAll('.filmstrip-thumb');
        thumbs.forEach(thumb => {
            const stepIdx = parseInt(thumb.getAttribute('data-step'), 10);
            thumb.classList.toggle('filmstrip-active', stepIdx === index);
        });

        // Scroll active thumb into view
        const activeThumb = this.filmstrip.querySelector('.filmstrip-active');
        if (activeThumb) {
            activeThumb.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
        }
    }

    _toggleOverlayCheckbox(type) {
        const cb = this.container.querySelector(`.overlay-toggle[data-overlay="${type}"]`);
        if (cb) {
            cb.checked = !cb.checked;
            if (this.overlayManager) {
                this.overlayManager.toggleOverlay(type, cb.checked);
            }
        }
    }

    _setAllOverlays(visible) {
        const toggles = this.container.querySelectorAll('.overlay-toggle');
        toggles.forEach(toggle => {
            toggle.checked = visible;
        });
        if (this.overlayManager) {
            this.overlayManager.setAllVisible(visible);
        }
    }

    _escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

/**
 * Auto-initialize all web agent viewers on page load.
 */
function initWebAgentViewers() {
    const viewers = document.querySelectorAll('.web-agent-viewer');
    viewers.forEach(container => {
        if (!container._webAgentViewer) {
            container._webAgentViewer = new WebAgentViewer(container);
        }
    });
}

// Initialize on DOM ready and on instance change
document.addEventListener('DOMContentLoaded', initWebAgentViewers);

// Re-initialize when new instances are loaded (annotation navigation)
if (typeof window.addEventListener === 'function') {
    // Listen for the custom event that annotation.js fires when loading a new instance
    document.addEventListener('instance-loaded', initWebAgentViewers);

    // Also observe DOM mutations in case viewers are added dynamically
    const observer = new MutationObserver((mutations) => {
        for (const mutation of mutations) {
            for (const node of mutation.addedNodes) {
                if (node.nodeType === 1) {
                    if (node.classList && node.classList.contains('web-agent-viewer')) {
                        if (!node._webAgentViewer) {
                            node._webAgentViewer = new WebAgentViewer(node);
                        }
                    }
                    // Check children too
                    const nested = node.querySelectorAll ? node.querySelectorAll('.web-agent-viewer') : [];
                    nested.forEach(v => {
                        if (!v._webAgentViewer) {
                            v._webAgentViewer = new WebAgentViewer(v);
                        }
                    });
                }
            }
        }
    });
    observer.observe(document.body || document.documentElement, { childList: true, subtree: true });
}

// Export
window.WebAgentViewer = WebAgentViewer;
window.initWebAgentViewers = initWebAgentViewers;

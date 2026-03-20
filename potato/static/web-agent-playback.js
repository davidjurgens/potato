/**
 * Web Agent Playback Controller
 *
 * Provides automatic step-by-step playback for web agent trace viewers.
 * Attaches to a WebAgentViewer instance and controls step navigation
 * with configurable speed.
 *
 * Usage:
 *   const viewer = container._webAgentViewer;
 *   const playback = new PlaybackController(viewer, { stepDelay: 2000 });
 *   playback.play();
 */
(function () {
  "use strict";

  const SPEED_OPTIONS = [
    { label: "0.5x", multiplier: 0.5 },
    { label: "1x", multiplier: 1 },
    { label: "2x", multiplier: 2 },
    { label: "4x", multiplier: 4 },
  ];

  class PlaybackController {
    /**
     * @param {WebAgentViewer} viewer - The viewer instance to control
     * @param {Object} options
     * @param {number} options.stepDelay - Base delay per step in ms (default 2000)
     * @param {boolean} options.autoStart - Start playing immediately (default false)
     * @param {boolean} options.loop - Loop back to start when done (default false)
     */
    constructor(viewer, options = {}) {
      this.viewer = viewer;
      this.stepDelay = options.stepDelay || 2000;
      this.autoStart = options.autoStart || false;
      this.loop = options.loop || false;
      this.speedMultiplier = 1;
      this.playing = false;
      this._timer = null;

      this._createControls();

      if (this.autoStart && this.viewer.steps.length > 0) {
        this.play();
      }
    }

    play() {
      if (this.playing) return;
      if (
        this.viewer.currentStep >= this.viewer.steps.length - 1 &&
        !this.loop
      ) {
        // At the end, restart from beginning
        this.viewer.goToStep(0);
      }
      this.playing = true;
      this._updateButtonState();
      this._scheduleNext();
    }

    pause() {
      this.playing = false;
      if (this._timer) {
        clearTimeout(this._timer);
        this._timer = null;
      }
      this._updateButtonState();
    }

    toggle() {
      if (this.playing) {
        this.pause();
      } else {
        this.play();
      }
    }

    setSpeed(multiplier) {
      this.speedMultiplier = multiplier;
      this._updateSpeedButtons();

      // If playing, reschedule with new speed
      if (this.playing) {
        if (this._timer) clearTimeout(this._timer);
        this._scheduleNext();
      }
    }

    seekTo(step) {
      const wasPlaying = this.playing;
      this.pause();
      this.viewer.goToStep(step);
      if (wasPlaying) {
        this.play();
      }
    }

    destroy() {
      this.pause();
      if (this._controlsEl && this._controlsEl.parentNode) {
        this._controlsEl.parentNode.removeChild(this._controlsEl);
      }
    }

    // --- Private ---

    _scheduleNext() {
      if (!this.playing) return;

      const delay = this.stepDelay / this.speedMultiplier;
      this._timer = setTimeout(() => {
        if (!this.playing) return;

        if (this.viewer.currentStep < this.viewer.steps.length - 1) {
          this.viewer.goToStep(this.viewer.currentStep + 1);
          this._updateProgress();
          this._scheduleNext();
        } else if (this.loop) {
          this.viewer.goToStep(0);
          this._updateProgress();
          this._scheduleNext();
        } else {
          this.playing = false;
          this._updateButtonState();
        }
      }, delay);
    }

    _createControls() {
      const container = this.viewer.container;

      // Create playback controls bar
      const bar = document.createElement("div");
      bar.className = "playback-controls";
      bar.innerHTML = `
        <button class="playback-btn playback-play-btn" title="Play/Pause">
          <span class="play-icon">&#9654;</span>
          <span class="pause-icon" style="display:none">&#9646;&#9646;</span>
        </button>
        <div class="playback-progress-wrapper">
          <input type="range" class="playback-progress" min="0"
                 max="${Math.max(0, this.viewer.steps.length - 1)}"
                 value="0" step="1">
        </div>
        <div class="playback-speed-btns">
          ${SPEED_OPTIONS.map(
            (s) =>
              `<button class="playback-speed-btn${s.multiplier === 1 ? " active" : ""}"
                       data-speed="${s.multiplier}">${s.label}</button>`
          ).join("")}
        </div>
        <span class="playback-time">0 / ${this.viewer.steps.length}</span>
      `;

      // Insert after filmstrip or at end of container
      const filmstrip = container.querySelector(".filmstrip");
      if (filmstrip) {
        filmstrip.parentNode.insertBefore(bar, filmstrip.nextSibling);
      } else {
        container.appendChild(bar);
      }

      this._controlsEl = bar;

      // Bind events
      const playBtn = bar.querySelector(".playback-play-btn");
      playBtn.addEventListener("click", () => this.toggle());

      const progress = bar.querySelector(".playback-progress");
      progress.addEventListener("input", (e) => {
        this.seekTo(parseInt(e.target.value, 10));
      });

      const speedBtns = bar.querySelectorAll(".playback-speed-btn");
      speedBtns.forEach((btn) => {
        btn.addEventListener("click", () => {
          this.setSpeed(parseFloat(btn.dataset.speed));
        });
      });

      // Listen for manual navigation to sync progress bar
      container.addEventListener("web-agent-step-change", (e) => {
        this._updateProgress();
        // Interrupt playback on manual navigation
        if (this.playing && !this._advancing) {
          this.pause();
        }
      });

      this._playIcon = bar.querySelector(".play-icon");
      this._pauseIcon = bar.querySelector(".pause-icon");
      this._progressBar = progress;
      this._timeDisplay = bar.querySelector(".playback-time");

      // Add inline styles
      this._addStyles();
    }

    _updateButtonState() {
      if (this._playIcon) {
        this._playIcon.style.display = this.playing ? "none" : "";
      }
      if (this._pauseIcon) {
        this._pauseIcon.style.display = this.playing ? "" : "none";
      }
    }

    _updateProgress() {
      if (this._progressBar) {
        this._progressBar.value = this.viewer.currentStep;
      }
      if (this._timeDisplay) {
        this._timeDisplay.textContent = `${this.viewer.currentStep + 1} / ${this.viewer.steps.length}`;
      }
    }

    _updateSpeedButtons() {
      if (!this._controlsEl) return;
      this._controlsEl.querySelectorAll(".playback-speed-btn").forEach((btn) => {
        btn.classList.toggle(
          "active",
          parseFloat(btn.dataset.speed) === this.speedMultiplier
        );
      });
    }

    _addStyles() {
      if (document.getElementById("playback-controller-styles")) return;

      const style = document.createElement("style");
      style.id = "playback-controller-styles";
      style.textContent = `
.playback-controls {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    background: #f0f0f0;
    border-top: 1px solid #ddd;
    font-size: 13px;
}
.playback-btn {
    width: 32px;
    height: 32px;
    border: 1px solid #ccc;
    border-radius: 4px;
    background: #fff;
    cursor: pointer;
    font-size: 14px;
    display: flex;
    align-items: center;
    justify-content: center;
}
.playback-btn:hover { background: #e8e8e8; }
.playback-progress-wrapper {
    flex: 1;
}
.playback-progress {
    width: 100%;
    cursor: pointer;
    accent-color: #2196F3;
}
.playback-speed-btns {
    display: flex;
    gap: 2px;
}
.playback-speed-btn {
    padding: 2px 8px;
    border: 1px solid #ddd;
    border-radius: 3px;
    background: #fff;
    cursor: pointer;
    font-size: 11px;
}
.playback-speed-btn:hover { background: #f0f0f0; }
.playback-speed-btn.active {
    background: #2196F3;
    color: #fff;
    border-color: #1976D2;
}
.playback-time {
    color: #666;
    min-width: 60px;
    text-align: right;
    font-variant-numeric: tabular-nums;
}
`;
      document.head.appendChild(style);
    }
  }

  // --- Auto-attach to viewers with auto_playback enabled ---

  function attachPlaybackControllers() {
    document
      .querySelectorAll('.web-agent-viewer[data-auto-playback="true"]')
      .forEach((container) => {
        if (container._playbackController) return;
        if (!container._webAgentViewer) return;

        const delay =
          parseFloat(container.dataset.playbackStepDelay || "2") * 1000;
        container._playbackController = new PlaybackController(
          container._webAgentViewer,
          {
            stepDelay: delay,
            autoStart: false,
          }
        );
      });
  }

  // Init after viewers are ready
  document.addEventListener("DOMContentLoaded", () => {
    setTimeout(attachPlaybackControllers, 100);
  });
  document.addEventListener("instance-loaded", () => {
    setTimeout(attachPlaybackControllers, 100);
  });

  window.PlaybackController = PlaybackController;
  window.attachPlaybackControllers = attachPlaybackControllers;
})();

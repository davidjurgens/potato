/**
 * Live Agent Viewer
 *
 * Manages SSE connection to a live agent session, rendering real-time
 * screenshots, SVG overlays, thought panel, and filmstrip. Provides
 * controls for pause/resume/instruct/takeover.
 *
 * Uses WebAgentOverlayManager (from web-agent-overlays.js) for SVG overlays.
 */
(function () {
  "use strict";

  class LiveAgentViewer {
    constructor(container) {
      this.container = container;
      this.fieldKey = container.dataset.fieldKey || "";
      this.config = JSON.parse(container.dataset.config || "{}");
      this.sessionId = null;
      this.eventSource = null;
      this.steps = [];
      this.currentStep = -1;
      this.overlayManager = null;
      this._userPinnedStep = false;

      this._initElements();
      this._initEventHandlers();
      this._initKeyboardShortcuts();
    }

    _initElements() {
      // Status
      this.statusIndicator = this.container.querySelector(
        ".live-agent-status-indicator"
      );
      this.statusText = this.container.querySelector(
        ".live-agent-status-text"
      );
      this.stepCounter = this.container.querySelector(
        ".live-agent-step-counter"
      );
      this.urlDisplay = this.container.querySelector(
        ".live-agent-url-display"
      );

      // Start form
      this.startForm = this.container.querySelector(".live-agent-start-form");
      this.taskInput = this.container.querySelector(".live-agent-task-input");
      this.urlInput = this.container.querySelector(".live-agent-url-input");
      this.startBtn = this.container.querySelector(".live-agent-start-btn");

      // Main viewer
      this.mainViewer = this.container.querySelector(".live-agent-main");
      this.screenshotPanel = this.container.querySelector(
        ".live-agent-screenshot-panel"
      );
      this.screenshotImg = this.container.querySelector(
        ".live-agent-screenshot"
      );
      this.placeholder = this.container.querySelector(
        ".live-agent-screenshot-placeholder"
      );
      this.overlayLayer = this.container.querySelector(
        ".live-agent-overlay-layer"
      );

      // Thought panel
      this.thoughtText = this.container.querySelector(
        ".live-agent-thought-text"
      );

      // Step details
      this.stepDetailsContent = this.container.querySelector(
        ".live-agent-step-details-content"
      );

      // Controls
      this.pauseBtn = this.container.querySelector(".live-agent-pause-btn");
      this.resumeBtn = this.container.querySelector(".live-agent-resume-btn");
      this.takeoverBtn = this.container.querySelector(
        ".live-agent-takeover-btn"
      );
      this.stopBtn = this.container.querySelector(".live-agent-stop-btn");
      this.instructInput = this.container.querySelector(
        ".live-agent-instruct-text"
      );
      this.instructBtn = this.container.querySelector(
        ".live-agent-instruct-btn"
      );

      // Takeover toolbar
      this.takeoverToolbar = this.container.querySelector(
        ".live-agent-takeover-toolbar"
      );
      this.takeoverTypeInput = this.container.querySelector(
        ".live-agent-takeover-type-input"
      );
      this.takeoverNavInput = this.container.querySelector(
        ".live-agent-takeover-nav-input"
      );

      // Collapse toggle
      this.collapseToggle = this.container.querySelector(
        ".live-agent-collapse-toggle"
      );

      // Filmstrip
      this.filmstrip = this.container.querySelector(".live-agent-filmstrip");

      // Overlay controls
      this.overlayToggles = this.container.querySelectorAll(
        ".live-agent-overlay-toggle"
      );

      // Init overlay manager if WebAgentOverlayManager is available
      if (
        this.screenshotPanel &&
        window.WebAgentOverlayManager
      ) {
        this.overlayManager = new window.WebAgentOverlayManager(
          this.screenshotPanel
        );
      }
    }

    _initEventHandlers() {
      // Collapse toggle
      if (this.collapseToggle) {
        this.collapseToggle.addEventListener("click", () => {
          const isCollapsed = this.container.classList.toggle("collapsed");
          this.collapseToggle.innerHTML = isCollapsed
            ? "&#x25BC; Expand"
            : "&#x25B2; Collapse";
        });
      }

      // Start button
      if (this.startBtn) {
        this.startBtn.addEventListener("click", () => this._startSession());
      }

      // Control buttons
      if (this.pauseBtn) {
        this.pauseBtn.addEventListener("click", () => this._pause());
      }
      if (this.resumeBtn) {
        this.resumeBtn.addEventListener("click", () => this._resume());
      }
      if (this.takeoverBtn) {
        this.takeoverBtn.addEventListener("click", () =>
          this._toggleTakeover()
        );
      }
      if (this.stopBtn) {
        this.stopBtn.addEventListener("click", () => this._stop());
      }

      // Instruction
      if (this.instructBtn) {
        this.instructBtn.addEventListener("click", () =>
          this._sendInstruction()
        );
      }
      if (this.instructInput) {
        this.instructInput.addEventListener("keydown", (e) => {
          if (e.key === "Enter") this._sendInstruction();
        });
      }

      // Overlay toggles
      this.overlayToggles.forEach((toggle) => {
        toggle.addEventListener("change", () => {
          if (this.overlayManager) {
            this.overlayManager.toggleOverlay(
              toggle.dataset.overlay,
              toggle.checked
            );
          }
        });
      });

      // Takeover click handler on screenshot — scale coordinates to actual
      // Playwright viewport size (the displayed image is CSS-scaled)
      if (this.screenshotPanel) {
        this.screenshotPanel.addEventListener("click", (e) => {
          if (
            !this.screenshotPanel.classList.contains("takeover-mode") ||
            !this.screenshotImg
          ) {
            return;
          }
          const rect = this.screenshotImg.getBoundingClientRect();
          const displayX = e.clientX - rect.left;
          const displayY = e.clientY - rect.top;

          // Scale from displayed size to actual viewport size
          const scaleX =
            this.screenshotImg.naturalWidth / rect.width || 1;
          const scaleY =
            this.screenshotImg.naturalHeight / rect.height || 1;
          const x = Math.round(displayX * scaleX);
          const y = Math.round(displayY * scaleY);

          this._sendManualAction({ type: "click", x: x, y: y });
          this._showClickFeedback(e.clientX - rect.left, e.clientY - rect.top);
          this._showActionToast(`Click at (${x}, ${y})`);
        });

        // Scroll wheel in takeover mode → scroll action (debounced)
        // Trackpads fire many small wheel events; accumulate and send
        // at most once per 300ms with a minimum threshold.
        let _scrollAccum = 0;
        let _scrollTimer = null;
        this.screenshotPanel.addEventListener("wheel", (e) => {
          if (!this.screenshotPanel.classList.contains("takeover-mode")) {
            return;
          }
          e.preventDefault();
          _scrollAccum += e.deltaY;

          if (!_scrollTimer) {
            _scrollTimer = setTimeout(() => {
              // Only send if accumulated scroll exceeds threshold
              if (Math.abs(_scrollAccum) >= 30) {
                const direction = _scrollAccum > 0 ? "down" : "up";
                const amount = Math.min(Math.abs(Math.round(_scrollAccum)), 600);
                this._sendManualAction({
                  type: "scroll",
                  direction: direction,
                  amount: amount,
                });
                this._showActionToast(`Scroll ${direction} ${amount}px`);
              }
              _scrollAccum = 0;
              _scrollTimer = null;
            }, 300);
          }
        }, { passive: false });
      }

      // Takeover type input — Enter sends the text as a type action
      if (this.takeoverTypeInput) {
        this.takeoverTypeInput.addEventListener("keydown", (e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            const text = this.takeoverTypeInput.value;
            if (text) {
              this._sendManualAction({ type: "type", text: text });
              this._showActionToast(`Typed: "${text}"`);
              this.takeoverTypeInput.value = "";
            }
          }
        });
      }

      // Takeover nav input — Enter sends navigate action
      if (this.takeoverNavInput) {
        this.takeoverNavInput.addEventListener("keydown", (e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            const url = this.takeoverNavInput.value.trim();
            if (url) {
              this._sendManualAction({ type: "navigate", url: url });
              this._showActionToast(`Navigating to ${url}`);
              this.takeoverNavInput.value = "";
            }
          }
        });
      }
    }

    _initKeyboardShortcuts() {
      this.container.setAttribute("tabindex", "0");
      this.container.addEventListener("keydown", (e) => {
        // Let the takeover type input handle its own keys
        if (e.target.classList.contains("live-agent-takeover-type-input")) {
          return;
        }
        if (e.target.tagName === "INPUT") return;

        // In takeover mode, forward printable keys as type actions
        if (
          this._currentState === "takeover" &&
          e.key.length === 1 &&
          !e.ctrlKey &&
          !e.metaKey
        ) {
          e.preventDefault();
          this._sendManualAction({ type: "type", text: e.key });
          this._showActionToast(`Typed: ${e.key}`);
          return;
        }

        // In takeover mode, handle Enter and Backspace
        if (this._currentState === "takeover") {
          if (e.key === "Enter") {
            e.preventDefault();
            this._sendManualAction({ type: "type", text: "\n" });
            this._showActionToast("Pressed Enter");
            return;
          }
          if (e.key === "Backspace") {
            e.preventDefault();
            // Playwright doesn't have a "backspace" action in our schema,
            // but we can simulate via keyboard press
            this._sendManualAction({ type: "type", text: "\b" });
            this._showActionToast("Pressed Backspace");
            return;
          }
        }

        switch (e.key) {
          case " ":
            e.preventDefault();
            if (this._currentState === "running") this._pause();
            else if (this._currentState === "paused") this._resume();
            break;
          case "Escape":
            if (this._currentState === "takeover") {
              this._toggleTakeover(); // Return to agent
            } else {
              this._stop();
            }
            break;
        }
      });
    }

    // --- Session lifecycle ---

    async _startSession() {
      const task = this.taskInput ? this.taskInput.value.trim() : "";
      const url = this.urlInput ? this.urlInput.value.trim() : "";

      if (!task) {
        alert("Please enter a task description.");
        return;
      }
      if (!url) {
        alert("Please enter a starting URL.");
        return;
      }

      this.startBtn.disabled = true;
      this.startBtn.textContent = "Starting...";

      try {
        const instanceId = this._getInstanceId();
        const response = await fetch("/api/live_agent/start", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            task_description: task,
            start_url: url,
            instance_id: instanceId,
          }),
        });

        const data = await response.json();
        if (!response.ok) {
          throw new Error(data.error || "Failed to start session");
        }

        this.sessionId = data.session_id;
        this._showMainViewer();
        this._connectSSE();
        this._enableControls(true);
      } catch (err) {
        console.error("Failed to start agent session:", err);
        alert("Failed to start: " + err.message);
        this.startBtn.disabled = false;
        this.startBtn.textContent = "Start Agent";
      }
    }

    _connectSSE() {
      if (!this.sessionId) return;

      this.eventSource = new EventSource(
        `/api/live_agent/stream/${this.sessionId}`
      );

      this.eventSource.addEventListener("connected", (e) => {
        const data = JSON.parse(e.data);
        this._updateStatus(data.state);
      });

      this.eventSource.addEventListener("thinking", (e) => {
        const data = JSON.parse(e.data);
        this._updateStatus("running");
        if (this.thoughtText) {
          this.thoughtText.textContent = "Thinking...";
          this.thoughtText.style.opacity = "0.6";
        }
        if (data.url && this.urlDisplay) {
          this.urlDisplay.textContent = data.url;
        }
      });

      this.eventSource.addEventListener("step", (e) => {
        const step = JSON.parse(e.data);
        this.steps.push(step);
        // Always add a filmstrip thumb for new steps
        this._addFilmstripThumb(step);
        // Only update the main view if the user hasn't pinned to an older step
        if (!this._userPinnedStep) {
          this._renderStep(step);
          this._setFilmstripActive(step.step_index);
        }
        // Dispatch event for trajectory_eval schema to pick up
        document.dispatchEvent(
          new CustomEvent("live-agent-step", { detail: step })
        );
      });

      this.eventSource.addEventListener("state_change", (e) => {
        const data = JSON.parse(e.data);
        this._updateStatus(data.new_state);
      });

      this.eventSource.addEventListener("instruction_received", (e) => {
        // Visual feedback that instruction was received
        if (this.instructInput) {
          this.instructInput.value = "";
          this.instructInput.placeholder = "Instruction sent!";
          setTimeout(() => {
            this.instructInput.placeholder = "Send instruction to agent...";
          }, 2000);
        }
      });

      this.eventSource.addEventListener("error", (e) => {
        if (e.data) {
          const data = JSON.parse(e.data);
          this._updateStatus("error");
          this._showError(data.message || "Agent error");
        }
        this._disconnectSSE();
        this._enableControls(false);
      });

      this.eventSource.addEventListener("complete", (e) => {
        const data = JSON.parse(e.data);
        this._updateStatus("completed");
        if (this.stepCounter) {
          this.stepCounter.textContent = `Completed (${data.total_steps} steps)`;
        }
        this._disconnectSSE();
        this._enableControls(false);
      });

      this.eventSource.onerror = () => {
        // SSE connection error
        console.warn("LiveAgent SSE connection error");
      };
    }

    _disconnectSSE() {
      if (this.eventSource) {
        this.eventSource.close();
        this.eventSource = null;
      }
    }

    // --- Control actions ---

    async _pause() {
      if (!this.sessionId) return;
      await this._controlRequest("pause");
    }

    async _resume() {
      if (!this.sessionId) return;
      await this._controlRequest("resume");
    }

    async _toggleTakeover() {
      if (!this.sessionId) return;
      await this._controlRequest("takeover");
    }

    async _stop() {
      if (!this.sessionId) return;
      await this._controlRequest("stop");
      this._disconnectSSE();
      this._enableControls(false);
    }

    async _sendInstruction() {
      if (!this.sessionId || !this.instructInput) return;
      const text = this.instructInput.value.trim();
      if (!text) return;

      try {
        await fetch(`/api/live_agent/instruct/${this.sessionId}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ instruction: text }),
        });
      } catch (err) {
        console.error("Failed to send instruction:", err);
      }
    }

    async _sendManualAction(action) {
      if (!this.sessionId) return;
      try {
        await fetch(`/api/live_agent/manual_action/${this.sessionId}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: action }),
        });
      } catch (err) {
        console.error("Failed to send manual action:", err);
      }
    }

    async _controlRequest(action) {
      try {
        const response = await fetch(
          `/api/live_agent/${action}/${this.sessionId}`,
          { method: "POST" }
        );
        const data = await response.json();
        if (data.state) {
          this._updateStatus(data.state);
        }
      } catch (err) {
        console.error(`Control action '${action}' failed:`, err);
      }
    }

    // --- Rendering ---

    _renderStep(step, { addThumb = false } = {}) {
      // Update screenshot
      if (step.screenshot_url && this.screenshotImg) {
        const url = `/api/live_agent/screenshot/${this.sessionId}/${step.step_index}`;
        this.screenshotImg.src = url;
        this.screenshotImg.style.display = "block";
        if (this.placeholder) this.placeholder.style.display = "none";
      }

      // Update overlays
      if (this.overlayManager) {
        this.overlayManager.renderStep(step);
      }

      // Update thought
      if (this.thoughtText && step.thought) {
        this.thoughtText.textContent = step.thought;
        this.thoughtText.style.opacity = "1";
      }

      // Update step details
      if (this.stepDetailsContent) {
        this._updateStepDetails(step);
      }

      // Update counter
      if (this.stepCounter) {
        this.stepCounter.textContent = `Step ${step.step_index + 1}`;
      }

      // Update URL
      if (step.url && this.urlDisplay) {
        this.urlDisplay.textContent = step.url;
      }

      // Only add a filmstrip thumb for new steps, not when revisiting
      if (addThumb) {
        this._addFilmstripThumb(step);
      }

      this.currentStep = step.step_index;
    }

    _updateStepDetails(step) {
      const actionType = step.action_type || step.action?.type || "unknown";
      const colors = this._getActionColors(actionType);
      let html = "";

      html += `<div class="live-agent-action-badge" style="background:${colors.badge};border:1px solid ${colors.border};color:${colors.border};">${actionType}</div>`;

      if (step.observation) {
        html += `<div style="margin-top:8px;color:#555;"><strong>Observation:</strong> ${this._escapeHtml(step.observation)}</div>`;
      }

      if (step.annotator_instruction) {
        html += `<div style="margin-top:8px;color:#2196F3;"><strong>Instruction:</strong> ${this._escapeHtml(step.annotator_instruction)}</div>`;
      }

      this.stepDetailsContent.innerHTML = html;
    }

    _addFilmstripThumb(step) {
      if (!this.filmstrip) return;

      this.filmstrip.style.display = "flex";

      // Don't add a duplicate thumb if one already exists for this step
      const existing = this.filmstrip.querySelector(
        `.live-agent-filmstrip-thumb[data-step="${step.step_index}"]`
      );
      if (existing) return;

      const thumb = document.createElement("img");
      thumb.className = "live-agent-filmstrip-thumb";
      thumb.src = `/api/live_agent/screenshot/${this.sessionId}/${step.step_index}`;
      thumb.dataset.step = step.step_index;
      thumb.alt = `Step ${step.step_index + 1}`;
      thumb.addEventListener("click", () => this._goToStep(step.step_index));

      this.filmstrip.appendChild(thumb);

      // Scroll to end so the new thumb is visible
      this.filmstrip.scrollLeft = this.filmstrip.scrollWidth;
    }

    _setFilmstripActive(index) {
      if (!this.filmstrip) return;
      this.filmstrip
        .querySelectorAll(".live-agent-filmstrip-thumb")
        .forEach((t) => {
          t.classList.toggle(
            "active",
            parseInt(t.dataset.step) === index
          );
        });
    }

    _goToStep(index) {
      if (index < 0 || index >= this.steps.length) return;

      // Mark that the user has pinned to a specific step
      // (prevents SSE updates from stealing focus)
      const latestStep = this.steps.length - 1;
      this._userPinnedStep = index < latestStep;

      this._renderStep(this.steps[index]);
      this._setFilmstripActive(index);
    }

    // --- UI state management ---

    _showMainViewer() {
      if (this.startForm) this.startForm.style.display = "none";
      if (this.mainViewer) this.mainViewer.style.display = "flex";
    }

    _updateStatus(state) {
      this._currentState = state;

      if (this.statusIndicator) {
        this.statusIndicator.className =
          "live-agent-status-indicator " + state;
      }
      if (this.statusText) {
        const labels = {
          idle: "Ready",
          running: "Agent Running",
          paused: "Paused",
          takeover: "Manual Control",
          completed: "Completed",
          error: "Error",
        };
        this.statusText.textContent = labels[state] || state;
      }

      // Toggle control button visibility
      if (state === "running") {
        if (this.pauseBtn) {
          this.pauseBtn.style.display = "";
          this.pauseBtn.disabled = false;
        }
        if (this.resumeBtn) this.resumeBtn.style.display = "none";
        if (this.screenshotPanel)
          this.screenshotPanel.classList.remove("takeover-mode");
      } else if (state === "paused") {
        if (this.pauseBtn) this.pauseBtn.style.display = "none";
        if (this.resumeBtn) {
          this.resumeBtn.style.display = "";
          this.resumeBtn.disabled = false;
        }
      } else if (state === "takeover") {
        if (this.pauseBtn) this.pauseBtn.style.display = "none";
        if (this.resumeBtn) this.resumeBtn.style.display = "none";
        if (this.takeoverBtn) {
          this.takeoverBtn.textContent = "Return to Agent";
          this.takeoverBtn.classList.remove("warning");
          this.takeoverBtn.classList.add("active");
        }
        if (this.screenshotPanel)
          this.screenshotPanel.classList.add("takeover-mode");
        if (this.takeoverToolbar)
          this.takeoverToolbar.style.display = "block";
      }

      if (state !== "takeover") {
        if (this.takeoverBtn) {
          this.takeoverBtn.textContent = "Take Over";
          this.takeoverBtn.classList.add("warning");
          this.takeoverBtn.classList.remove("active");
        }
        if (this.screenshotPanel)
          this.screenshotPanel.classList.remove("takeover-mode");
        if (this.takeoverToolbar)
          this.takeoverToolbar.style.display = "none";
      }
    }

    _enableControls(enabled) {
      const btns = [
        this.pauseBtn,
        this.resumeBtn,
        this.takeoverBtn,
        this.stopBtn,
        this.instructBtn,
      ];
      btns.forEach((btn) => {
        if (btn) btn.disabled = !enabled;
      });
      if (this.instructInput) this.instructInput.disabled = !enabled;
    }

    _showError(message) {
      if (this.thoughtText) {
        this.thoughtText.textContent = "Error: " + message;
        this.thoughtText.style.color = "#F44336";
      }
    }

    _getInstanceId() {
      // Try to get instance ID from the annotation page
      const instanceEl = document.getElementById("instance_id");
      if (instanceEl) return instanceEl.value || instanceEl.textContent;
      return "unknown";
    }

    _getActionColors(actionType) {
      const colors = {
        click: {
          bg: "#fff3e0",
          border: "#FF9800",
          badge: "rgba(255,152,0,0.2)",
        },
        type: {
          bg: "#e8f4fd",
          border: "#2196F3",
          badge: "rgba(33,150,243,0.2)",
        },
        scroll: {
          bg: "#e8f5e9",
          border: "#4CAF50",
          badge: "rgba(76,175,80,0.2)",
        },
        navigate: {
          bg: "#e8eaf6",
          border: "#3F51B5",
          badge: "rgba(63,81,181,0.2)",
        },
        wait: {
          bg: "#f5f5f5",
          border: "#9E9E9E",
          badge: "rgba(158,158,158,0.2)",
        },
        done: {
          bg: "#e8f5e9",
          border: "#388E3C",
          badge: "rgba(56,142,60,0.2)",
        },
      };
      return (
        colors[actionType] || {
          bg: "#f5f5f5",
          border: "#9E9E9E",
          badge: "rgba(158,158,158,0.2)",
        }
      );
    }

    _escapeHtml(text) {
      const div = document.createElement("div");
      div.textContent = text;
      return div.innerHTML;
    }

    /**
     * Show a pulsing circle at the click position in the screenshot panel.
     */
    _showClickFeedback(displayX, displayY) {
      if (!this.screenshotPanel) return;
      const marker = document.createElement("div");
      marker.className = "live-agent-click-marker";
      marker.style.left = displayX + "px";
      marker.style.top = displayY + "px";
      this.screenshotPanel.appendChild(marker);
      marker.addEventListener("animationend", () => marker.remove());
    }

    /**
     * Show a brief toast at the bottom of the screenshot panel
     * confirming what action was sent.
     */
    _showActionToast(message) {
      if (!this.screenshotPanel) return;
      // Remove any existing toast
      const old = this.screenshotPanel.querySelector(".live-agent-action-toast");
      if (old) old.remove();

      const toast = document.createElement("div");
      toast.className = "live-agent-action-toast";
      toast.textContent = message;
      this.screenshotPanel.appendChild(toast);
      toast.addEventListener("animationend", () => toast.remove());
    }

    destroy() {
      this._disconnectSSE();
    }
  }

  // --- Auto-initialization ---

  function initLiveAgentViewers() {
    document.querySelectorAll(".live-agent-viewer").forEach((el) => {
      if (!el._liveAgentViewer) {
        el._liveAgentViewer = new LiveAgentViewer(el);
      }
    });
  }

  // Init on DOM ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initLiveAgentViewers);
  } else {
    initLiveAgentViewers();
  }

  // Re-init on instance load (Potato-specific events)
  document.addEventListener("instance-loaded", initLiveAgentViewers);

  // Watch for dynamically added viewers
  const observer = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      for (const node of mutation.addedNodes) {
        if (node.nodeType === 1) {
          if (node.classList && node.classList.contains("live-agent-viewer")) {
            if (!node._liveAgentViewer) {
              node._liveAgentViewer = new LiveAgentViewer(node);
            }
          }
          const nested = node.querySelectorAll
            ? node.querySelectorAll(".live-agent-viewer")
            : [];
          nested.forEach((el) => {
            if (!el._liveAgentViewer) {
              el._liveAgentViewer = new LiveAgentViewer(el);
            }
          });
        }
      }
    }
  });
  observer.observe(document.body || document.documentElement, {
    childList: true,
    subtree: true,
  });

  window.LiveAgentViewer = LiveAgentViewer;
})();

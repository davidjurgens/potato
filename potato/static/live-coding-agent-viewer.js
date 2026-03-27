/**
 * Live Coding Agent Viewer
 *
 * SSE consumer that renders coding agent tool calls in real-time,
 * reusing CSS classes from CodingTraceDisplay (ct-turn, ct-tool-call, etc.)
 */

(function () {
  'use strict';

  class LiveCodingAgentViewer {
    constructor(container) {
      this.container = container;
      this.fieldKey = container.dataset.fieldKey;
      this.sessionId = null;
      this.eventSource = null;
      this.turnCount = 0;
      this.currentTurnEl = null;
      this.state = 'idle';
      this._init();
    }

    _init() {
      // Start button
      const startBtn = this.container.querySelector('[data-action="start"]');
      if (startBtn) {
        startBtn.addEventListener('click', () => this._startSession());
      }

      // Control buttons
      this.container.querySelectorAll('[data-action]').forEach(btn => {
        const action = btn.dataset.action;
        if (action === 'pause') btn.addEventListener('click', () => this._pause());
        if (action === 'resume') btn.addEventListener('click', () => this._resume());
        if (action === 'stop') btn.addEventListener('click', () => this._stop());
        if (action === 'instruct') btn.addEventListener('click', () => this._sendInstruction());
      });

      // Enter key on instruction input
      const instrInput = this.container.querySelector('.lca-instruction-input');
      if (instrInput) {
        instrInput.addEventListener('keydown', e => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            this._sendInstruction();
          }
        });
      }
    }

    async _startSession() {
      const taskInput = this.container.querySelector('.lca-task-input');
      const task = taskInput ? taskInput.value.trim() : '';
      if (!task) {
        taskInput && taskInput.focus();
        return;
      }

      try {
        const resp = await fetch('/api/live_coding_agent/start', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            task_description: task,
            instance_id: this.fieldKey,
          }),
        });
        const data = await resp.json();
        if (data.error) {
          this._showError(data.error);
          return;
        }

        this.sessionId = data.session_id;

        // Switch to session view
        const startForm = this.container.querySelector('.lca-start-form');
        const sessionView = this.container.querySelector('.lca-session');
        if (startForm) startForm.style.display = 'none';
        if (sessionView) sessionView.style.display = 'block';

        this._connectSSE();
      } catch (e) {
        this._showError('Failed to start session: ' + e.message);
      }
    }

    _connectSSE() {
      if (!this.sessionId) return;

      this.eventSource = new EventSource(
        '/api/live_coding_agent/stream/' + this.sessionId
      );

      this.eventSource.addEventListener('connected', e => {
        const data = JSON.parse(e.data);
        this._updateStatus('running');
      });

      this.eventSource.addEventListener('thinking', e => {
        const data = JSON.parse(e.data);
        this._showThinking(data.text);
      });

      this.eventSource.addEventListener('tool_call_start', e => {
        const data = JSON.parse(e.data);
        this._hideThinking();
        this._renderToolCallStart(data);
      });

      this.eventSource.addEventListener('tool_call', e => {
        const data = JSON.parse(e.data);
        this._renderToolCallEnd(data);
      });

      this.eventSource.addEventListener('turn_end', e => {
        const data = JSON.parse(e.data);
        this._finalizeTurn(data);
      });

      this.eventSource.addEventListener('state_change', e => {
        const data = JSON.parse(e.data);
        this._updateStatus(data.new_state);
      });

      this.eventSource.addEventListener('instruction_received', e => {
        const data = JSON.parse(e.data);
        this._showInstructionConfirm(data.instruction);
      });

      this.eventSource.addEventListener('error', e => {
        const data = JSON.parse(e.data);
        this._showError(data.message);
        this._updateStatus('error');
      });

      this.eventSource.addEventListener('complete', e => {
        this._hideThinking();
        this._updateStatus('completed');
        this._disconnectSSE();
      });

      this.eventSource.onerror = () => {
        // Reconnect after brief delay
        setTimeout(() => {
          if (this.state === 'running') this._connectSSE();
        }, 3000);
      };
    }

    _disconnectSSE() {
      if (this.eventSource) {
        this.eventSource.close();
        this.eventSource = null;
      }
    }

    _showThinking(text) {
      const el = document.getElementById('lca-thinking-' + this.fieldKey);
      const textEl = document.getElementById('lca-thinking-text-' + this.fieldKey);
      if (el) el.style.display = 'flex';
      if (textEl) textEl.textContent = text || 'Thinking...';
    }

    _hideThinking() {
      const el = document.getElementById('lca-thinking-' + this.fieldKey);
      if (el) el.style.display = 'none';
    }

    _renderToolCallStart(data) {
      const turnsEl = document.getElementById('lca-turns-' + this.fieldKey);
      if (!turnsEl) return;

      // Create turn container if needed
      if (!this.currentTurnEl) {
        this.currentTurnEl = document.createElement('div');
        this.currentTurnEl.className = 'ct-turn ct-turn-assistant';
        this.currentTurnEl.dataset.turnIndex = data.turn_index;

        // Step number
        this.turnCount++;
        this.currentTurnEl.innerHTML =
          '<div class="ct-turn-header">' +
          '<span class="ct-step-num">Step ' + this.turnCount + '</span>' +
          '</div>';
        turnsEl.appendChild(this.currentTurnEl);
      }

      // Add tool call card (in-progress state)
      const toolType = this._classifyTool(data.tool);
      const colors = this._getToolColors(toolType);
      const filePath = (data.input || {}).file_path || (data.input || {}).path || '';

      const card = document.createElement('div');
      card.className = 'ct-tool-call ct-tool-' + toolType + ' lca-tool-pending';
      card.dataset.toolId = data.turn_index + '-' + (data.tool_index || 0);
      card.innerHTML =
        '<div class="ct-tool-header">' +
        '<span class="ct-tool-badge" style="background:' + colors[0] +
        ';color:' + colors[1] + ';border:1px solid ' + colors[2] + '">' +
        this._escapeHtml(data.tool) + '</span>' +
        (filePath ? '<span class="ct-file-path">' + this._escapeHtml(filePath) + '</span>' : '') +
        '<span class="lca-tool-spinner">Running...</span>' +
        '</div>' +
        '<div class="ct-tool-body"></div>';
      this.currentTurnEl.appendChild(card);

      // Scroll to bottom
      turnsEl.scrollTop = turnsEl.scrollHeight;
    }

    _renderToolCallEnd(data) {
      const toolId = data.turn_index + '-' + (data.tool_index || 0);
      const card = this.currentTurnEl
        ? this.currentTurnEl.querySelector('[data-tool-id="' + toolId + '"]')
        : null;

      if (!card) return;

      card.classList.remove('lca-tool-pending');
      const spinner = card.querySelector('.lca-tool-spinner');
      if (spinner) spinner.remove();

      // Render the tool output
      const body = card.querySelector('.ct-tool-body');
      if (body) {
        body.innerHTML = this._renderToolOutput(data);
      }

      // Scroll
      const turnsEl = document.getElementById('lca-turns-' + this.fieldKey);
      if (turnsEl) turnsEl.scrollTop = turnsEl.scrollHeight;
    }

    _renderToolOutput(data) {
      const tool = data.tool || '';
      const input = data.input || {};
      const output = data.output || '';
      const outputType = data.output_type || 'generic';

      if (outputType === 'diff' || tool === 'Edit') {
        return this._renderDiff(input, output);
      } else if (outputType === 'terminal' || tool === 'Bash') {
        return this._renderTerminal(input, output);
      } else if (outputType === 'code') {
        return this._renderCode(output);
      } else {
        return this._renderGeneric(input, output);
      }
    }

    _renderDiff(input, output) {
      const oldStr = input.old_string || '';
      const newStr = input.new_string || '';
      let html = '<div class="ct-diff">';
      oldStr.split('\n').forEach(line => {
        html += '<div class="ct-diff-line ct-diff-removed">' +
          '<span class="ct-diff-marker">-</span>' +
          '<span class="ct-diff-text">' + this._escapeHtml(line) + '</span></div>';
      });
      newStr.split('\n').forEach(line => {
        html += '<div class="ct-diff-line ct-diff-added">' +
          '<span class="ct-diff-marker">+</span>' +
          '<span class="ct-diff-text">' + this._escapeHtml(line) + '</span></div>';
      });
      html += '</div>';
      if (output) {
        html += '<div class="ct-edit-status">' + this._escapeHtml(output) + '</div>';
      }
      return html;
    }

    _renderTerminal(input, output) {
      const cmd = input.command || input.cmd || '';
      let html = '<div class="ct-terminal">';
      if (cmd) {
        html += '<div class="ct-terminal-cmd"><span class="ct-terminal-prompt">$</span> ' +
          this._escapeHtml(cmd) + '</div>';
      }
      if (output) {
        html += '<pre class="ct-terminal-output">' + this._escapeHtml(output) + '</pre>';
      }
      html += '</div>';
      return html;
    }

    _renderCode(output) {
      if (!output) return '<div class="ct-code-empty">No output</div>';
      const lines = output.split('\n');
      let html = '<div class="ct-code-block"><table class="ct-code-table">';
      lines.forEach((line, i) => {
        html += '<tr class="ct-code-line"><td class="ct-line-num">' + (i + 1) +
          '</td><td class="ct-line-content"><code>' +
          (this._escapeHtml(line) || '&nbsp;') + '</code></td></tr>';
      });
      html += '</table></div>';
      return html;
    }

    _renderGeneric(input, output) {
      let html = '';
      if (input && Object.keys(input).length) {
        html += '<div class="ct-generic-input"><div class="ct-generic-label">Input</div>' +
          '<pre class="ct-generic-pre">' + this._escapeHtml(JSON.stringify(input, null, 2)) + '</pre></div>';
      }
      if (output) {
        html += '<div class="ct-generic-output"><div class="ct-generic-label">Output</div>' +
          '<pre class="ct-generic-pre">' + this._escapeHtml(output) + '</pre></div>';
      }
      return html || '<div class="ct-generic-empty">No data</div>';
    }

    _finalizeTurn(data) {
      // Add reasoning text if present
      if (data.content && this.currentTurnEl) {
        const header = this.currentTurnEl.querySelector('.ct-turn-header');
        if (header) {
          const reasoning = document.createElement('div');
          reasoning.className = 'ct-reasoning';
          reasoning.textContent = data.content;
          header.after(reasoning);
        }
      }

      // Update counter
      const counterEl = document.getElementById('lca-counter-' + this.fieldKey);
      if (counterEl) {
        counterEl.textContent = (data.turn_index + 1) + ' turns';
      }

      // Reset for next turn
      this.currentTurnEl = null;
    }

    _updateStatus(state) {
      this.state = state;
      const indicator = document.getElementById('lca-status-' + this.fieldKey);
      const text = document.getElementById('lca-status-text-' + this.fieldKey);

      if (indicator) {
        indicator.className = 'lca-status-indicator lca-status-' + state;
      }
      if (text) {
        const labels = {
          idle: 'Idle', running: 'Running', paused: 'Paused',
          completed: 'Completed', error: 'Error',
        };
        text.textContent = labels[state] || state;
      }

      // Toggle pause/resume buttons
      const pauseBtn = this.container.querySelector('[data-action="pause"]');
      const resumeBtn = this.container.querySelector('[data-action="resume"]');
      if (pauseBtn) pauseBtn.style.display = state === 'running' ? '' : 'none';
      if (resumeBtn) resumeBtn.style.display = state === 'paused' ? '' : 'none';
    }

    async _pause() {
      if (!this.sessionId) return;
      await fetch('/api/live_coding_agent/pause/' + this.sessionId, { method: 'POST' });
    }

    async _resume() {
      if (!this.sessionId) return;
      await fetch('/api/live_coding_agent/resume/' + this.sessionId, { method: 'POST' });
    }

    async _stop() {
      if (!this.sessionId) return;
      await fetch('/api/live_coding_agent/stop/' + this.sessionId, { method: 'POST' });
      this._disconnectSSE();
    }

    async _sendInstruction() {
      if (!this.sessionId) return;
      const input = document.getElementById('lca-instruction-input-' + this.fieldKey);
      if (!input || !input.value.trim()) return;

      await fetch('/api/live_coding_agent/instruct/' + this.sessionId, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ instruction: input.value.trim() }),
      });
      input.value = '';
    }

    _showInstructionConfirm(instruction) {
      // Brief toast showing the instruction was received
      const turnsEl = document.getElementById('lca-turns-' + this.fieldKey);
      if (!turnsEl) return;
      const toast = document.createElement('div');
      toast.className = 'ct-turn ct-turn-user';
      toast.innerHTML =
        '<div class="ct-user-badge">Instruction</div>' +
        '<div class="ct-user-text">' + this._escapeHtml(instruction) + '</div>';
      turnsEl.appendChild(toast);
      turnsEl.scrollTop = turnsEl.scrollHeight;
    }

    _showError(message) {
      const turnsEl = document.getElementById('lca-turns-' + this.fieldKey);
      if (!turnsEl) return;
      const errDiv = document.createElement('div');
      errDiv.className = 'lca-error-msg';
      errDiv.textContent = 'Error: ' + message;
      turnsEl.appendChild(errDiv);
    }

    _classifyTool(name) {
      const n = (name || '').toLowerCase();
      if (['grep', 'glob', 'search', 'find'].includes(n)) return 'search';
      if (['read'].includes(n)) return 'read';
      if (['edit', 'replace'].includes(n)) return 'edit';
      if (['write', 'create'].includes(n)) return 'write';
      if (['bash', 'terminal', 'shell', 'run'].includes(n)) return 'bash';
      return 'generic';
    }

    _getToolColors(type) {
      const colors = {
        read: ['#e3f2fd', '#1565c0', '#1976d2'],
        edit: ['#fff3e0', '#e65100', '#ef6c00'],
        write: ['#e8f5e9', '#2e7d32', '#388e3c'],
        bash: ['#263238', '#b0bec5', '#78909c'],
        search: ['#f3e5f5', '#6a1b9a', '#7b1fa2'],
        generic: ['#f5f5f5', '#424242', '#616161'],
      };
      return colors[type] || colors.generic;
    }

    _escapeHtml(text) {
      const div = document.createElement('div');
      div.textContent = text || '';
      return div.innerHTML;
    }
  }

  // Auto-initialize viewers
  function initViewers() {
    document.querySelectorAll('.live-coding-agent-viewer').forEach(el => {
      if (!el._lcaViewer) {
        el._lcaViewer = new LiveCodingAgentViewer(el);
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initViewers);
  } else {
    initViewers();
  }

  // Watch for dynamically added viewers
  const observer = new MutationObserver(initViewers);
  observer.observe(document.body, { childList: true, subtree: true });
})();

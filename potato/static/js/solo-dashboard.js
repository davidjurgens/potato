/**
 * Solo Mode Dashboard
 *
 * Tab management, API data loading, interactive tables,
 * and rule review actions for the Solo Mode status page.
 */

class SoloDashboard {
  constructor() {
    this.currentTab = 'overview';
    this.viz = null;
    this.refreshInterval = null;
    this._confusionLoaded = false;
    this._confusionData = null;
    this._lfLoaded = false;
    this._disagreeLoaded = false;
    this._disagreeData = null;
  }

  init() {
    this._initTabs();
    this._loadOverview();
    this._loadRules();

    // Auto-refresh overview every 30s
    this.refreshInterval = setInterval(() => {
      if (this.currentTab === 'overview') this._loadOverview();
    }, 30000);
  }

  // ── Tab Navigation ──────────────────────────────────────

  _initTabs() {
    document.querySelectorAll('.solo-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        this._switchTab(tab.dataset.tab);
      });
    });
  }

  _switchTab(tabName) {
    document.querySelectorAll('.solo-tab').forEach(tab => {
      tab.classList.toggle('active', tab.dataset.tab === tabName);
    });
    document.querySelectorAll('.solo-tab-content').forEach(el => {
      el.classList.toggle('active', el.id === 'tab-' + tabName);
    });
    this.currentTab = tabName;

    if (tabName === 'confusion' && !this._confusionLoaded) {
      this._loadConfusion();
    }
    if (tabName === 'labeling-fns' && !this._lfLoaded) {
      this._loadLabelingFunctions();
    }
    if (tabName === 'disagreements' && !this._disagreeLoaded) {
      this._loadDisagreements();
    }
    if (tabName === 'clusters' && !this.viz) {
      this._initViz();
    }
  }

  // ── Overview Tab ────────────────────────────────────────

  async _loadOverview() {
    try {
      const resp = await fetch('/solo/api/status');
      if (!resp.ok) return;
      const data = await resp.json();
      this._renderOverview(data);
    } catch (e) {
      console.warn('Solo dashboard: failed to load overview', e);
    }
    this._loadRefinementStatus();
    this._loadLabelingFunctionStatus();
  }

  _renderOverview(data) {
    const stats = data.annotation_stats || {};
    const agreement = data.agreement_metrics || {};
    const llm = data.llm_stats || {};

    // Annotation counts
    this._setText('ov-human', stats.human_labeled || 0);
    this._setText('ov-llm', stats.llm_labeled || 0);
    this._setText('ov-remaining', stats.remaining || 0);

    // Progress bar
    const total = (stats.human_labeled || 0) + (stats.llm_labeled || 0) + (stats.remaining || 0);
    const pct = total > 0 ? Math.round(((stats.human_labeled || 0) + (stats.llm_labeled || 0)) / total * 100) : 0;
    this._setText('ov-progress-text', pct + '%');
    const bar = document.getElementById('ov-progress-bar');
    if (bar) {
      bar.style.width = pct + '%';
      bar.style.background = pct >= 80 ? 'var(--success-color, #10b981)' : 'var(--primary, #6e56cf)';
    }

    // Agreement
    const rate = Math.round((agreement.agreement_rate || 0) * 100);
    this._setText('ov-agreement', rate + '%');
    const agEl = document.getElementById('ov-agreement');
    if (agEl) {
      agEl.className = 'card-value';
      if (rate >= 90) agEl.classList.add('text-success');
      else if (rate >= 70) agEl.classList.add('text-warning');
      else agEl.classList.add('text-danger');
    }
    this._setText('ov-comparisons', agreement.total_compared || 0);
    this._setText('ov-agreements', agreement.agreements || 0);
    this._setText('ov-disagreements', agreement.disagreements || 0);

    // LLM stats
    this._setText('ov-llm-labeled', llm.labeled_count || 0);
    this._setText('ov-llm-queue', llm.queue_size || 0);
    this._setText('ov-llm-errors', llm.error_count || 0);
    const statusEl = document.getElementById('ov-llm-status');
    if (statusEl) {
      if (llm.is_paused) {
        statusEl.textContent = 'Paused';
        statusEl.className = 'status-badge status-pending';
      } else if (llm.is_running) {
        statusEl.textContent = 'Running';
        statusEl.className = 'status-badge status-active';
      } else {
        statusEl.textContent = 'Stopped';
        statusEl.className = 'status-badge status-inactive';
      }
    }

    // Phase
    const phaseName = (data.phase_name || data.phase || '').replace(/_/g, ' ');
    this._setText('ov-phase', phaseName);

    // Confidence routing
    const routing = llm.confidence_routing || {};
    if (routing.enabled) {
      this._setText('ov-routing-total', routing.total_routed || 0);
      this._setText('ov-routing-human', routing.human_routed_count || 0);

      // Update per-tier stats if the card exists
      const routingCard = document.getElementById('routing-card');
      if (routingCard && routing.tiers) {
        // Re-render tier rows dynamically
        const metricRows = routingCard.querySelectorAll('.metric-row');
        // First two rows are Total Routed and Human Routed, rest are tiers
        routing.tiers.forEach((tier, i) => {
          const rowIdx = i + 2;
          if (metricRows[rowIdx]) {
            const name = tier.name || ('Tier ' + (i + 1));
            const rate = Math.round((tier.acceptance_rate || 0) * 100);
            metricRows[rowIdx].querySelector('span').textContent = name;
            metricRows[rowIdx].querySelector('strong').textContent =
              tier.instances_accepted + ' accepted (' + rate + '%)';
          }
        });
      }
    }
  }

  // ── Rules Tab ───────────────────────────────────────────

  async _loadRules() {
    try {
      const resp = await fetch('/solo/api/rules');
      if (!resp.ok) return;
      const data = await resp.json();
      this._renderRulesTable(data);
    } catch (e) {
      console.warn('Solo dashboard: failed to load rules', e);
    }
  }

  _renderRulesTable(data) {
    const tbody = document.getElementById('rules-table-body');
    if (!tbody) return;

    const rules = data.rules || [];
    const stats = data.stats || {};

    this._setText('rules-total', stats.total_rules || 0);
    this._setText('rules-categories', stats.total_categories || 0);
    this._setText('rules-pending', stats.pending_categories || 0);
    this._setText('rules-approved', stats.approved_categories || 0);

    if (rules.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" class="empty-cell">No edge case rules discovered yet</td></tr>';
      return;
    }

    // Sort: pending first, then confidence ascending
    rules.sort((a, b) => {
      if (a.reviewed !== b.reviewed) return a.reviewed ? 1 : -1;
      return (a.source_confidence || 0) - (b.source_confidence || 0);
    });

    tbody.innerHTML = rules.map(rule => {
      const conf = Math.round((rule.source_confidence || 0) * 100);
      let badge;
      if (rule.approved) badge = '<span class="status-badge status-approved">Approved</span>';
      else if (rule.reviewed) badge = '<span class="status-badge status-rejected">Rejected</span>';
      else badge = '<span class="status-badge status-pending">Pending</span>';

      return `<tr>
        <td class="rule-text-cell" title="${this._esc(rule.rule_text || '')}">${this._esc(rule.rule_text || '')}</td>
        <td>${this._esc(rule.instance_id || '')}</td>
        <td>${conf}%</td>
        <td>${this._esc(rule.cluster_id || '—')}</td>
        <td>${badge}</td>
      </tr>`;
    }).join('');
  }

  // ── Confusion Tab ──────────────────────────────────────

  async _loadConfusion() {
    try {
      const resp = await fetch('/solo/api/confusion-analysis');
      if (!resp.ok) return;
      const data = await resp.json();
      this._confusionData = data;
      this._confusionLoaded = true;

      if (!data.enabled) {
        this._setText('confusion-total-disagreements', 'Disabled');
        return;
      }

      // Summary cards
      this._setText('confusion-total-disagreements', data.total_disagreements || 0);
      const patterns = data.patterns || [];
      this._setText('confusion-distinct-patterns', patterns.length);

      if (patterns.length > 0) {
        const top = patterns[0];
        this._setText('confusion-top-pattern',
          top.predicted_label + ' \u2192 ' + top.actual_label);
        this._setText('confusion-top-count', top.count + ' times (' + top.percent + '%)');
      }

      // Render components
      if (data.matrix_data) {
        this._renderConfusionHeatmap(data.matrix_data);
        this._renderLabelAccuracy(data.matrix_data.label_accuracy || {});
      }
      this._renderPatternsTable(patterns);
    } catch (e) {
      console.warn('Solo dashboard: failed to load confusion data', e);
    }
  }

  _renderConfusionHeatmap(matrixData) {
    const container = document.getElementById('confusion-heatmap');
    if (!container || typeof d3 === 'undefined') return;

    container.innerHTML = '';

    const labels = matrixData.labels || [];
    if (labels.length === 0) {
      container.innerHTML = '<p style="color: var(--muted-foreground); text-align: center; padding: 2rem;">No labels to display</p>';
      return;
    }

    const margin = { top: 60, right: 20, bottom: 20, left: 100 };
    const width = container.clientWidth - margin.left - margin.right;
    const cellSize = Math.min(Math.floor(width / labels.length), 60);
    const height = cellSize * labels.length;

    const svg = d3.select(container)
      .append('svg')
      .attr('width', width + margin.left + margin.right)
      .attr('height', height + margin.top + margin.bottom)
      .append('g')
      .attr('transform', `translate(${margin.left},${margin.top})`);

    const x = d3.scaleBand().domain(labels).range([0, cellSize * labels.length]).padding(0.05);
    const y = d3.scaleBand().domain(labels).range([0, cellSize * labels.length]).padding(0.05);

    const maxCount = matrixData.max_count || 1;
    const colorScale = d3.scaleSequential(d3.interpolateReds).domain([0, maxCount]);

    // Build cell lookup
    const cellMap = {};
    (matrixData.cells || []).forEach(c => {
      cellMap[c.predicted + '|' + c.actual] = c.count;
    });

    // Draw cells
    const self = this;
    labels.forEach(predicted => {
      labels.forEach(actual => {
        const count = cellMap[predicted + '|' + actual] || 0;
        const g = svg.append('g');

        g.append('rect')
          .attr('class', 'heatmap-cell')
          .attr('x', x(actual))
          .attr('y', y(predicted))
          .attr('width', x.bandwidth())
          .attr('height', y.bandwidth())
          .attr('fill', count > 0 ? colorScale(count) : '#f8f8f8')
          .attr('rx', 3)
          .on('click', () => self._showPatternDetail(predicted, actual));

        if (count > 0) {
          g.append('text')
            .attr('class', 'heatmap-count' + (count < maxCount * 0.4 ? ' dark-text' : ''))
            .attr('x', x(actual) + x.bandwidth() / 2)
            .attr('y', y(predicted) + y.bandwidth() / 2 + 4)
            .text(count);
        }
      });
    });

    // X axis labels (top) — actual / human corrected
    svg.selectAll('.x-label')
      .data(labels)
      .enter()
      .append('text')
      .attr('class', 'heatmap-label')
      .attr('x', d => x(d) + x.bandwidth() / 2)
      .attr('y', -8)
      .attr('text-anchor', 'middle')
      .text(d => d.length > 12 ? d.substring(0, 10) + '..' : d);

    // X axis title
    svg.append('text')
      .attr('class', 'heatmap-label')
      .attr('x', (cellSize * labels.length) / 2)
      .attr('y', -35)
      .attr('text-anchor', 'middle')
      .attr('font-weight', '600')
      .text('Human Corrected');

    // Y axis labels (left) — predicted
    svg.selectAll('.y-label')
      .data(labels)
      .enter()
      .append('text')
      .attr('class', 'heatmap-label')
      .attr('x', -8)
      .attr('y', d => y(d) + y.bandwidth() / 2 + 4)
      .attr('text-anchor', 'end')
      .text(d => d.length > 14 ? d.substring(0, 12) + '..' : d);

    // Y axis title
    svg.append('text')
      .attr('class', 'heatmap-label')
      .attr('transform', 'rotate(-90)')
      .attr('x', -(cellSize * labels.length) / 2)
      .attr('y', -75)
      .attr('text-anchor', 'middle')
      .attr('font-weight', '600')
      .text('LLM Predicted');
  }

  _renderPatternsTable(patterns) {
    const tbody = document.getElementById('confusion-patterns-body');
    if (!tbody) return;

    if (!patterns || patterns.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" class="empty-cell">No confusion patterns detected yet</td></tr>';
      return;
    }

    tbody.innerHTML = patterns.map(p => {
      return `<tr>
        <td><strong>${this._esc(p.predicted_label)}</strong></td>
        <td><strong>${this._esc(p.actual_label)}</strong></td>
        <td>${p.count}</td>
        <td>${p.percent}%</td>
        <td>
          <button class="suggest-btn"
                  onclick="soloDashboard.suggestGuideline('${this._esc(p.predicted_label)}','${this._esc(p.actual_label)}')">
            Suggest Fix
          </button>
        </td>
      </tr>`;
    }).join('');
  }

  _renderLabelAccuracy(labelAccuracy) {
    const container = document.getElementById('label-accuracy-rows');
    if (!container) return;

    const entries = Object.entries(labelAccuracy);
    if (entries.length === 0) {
      container.innerHTML = '<p style="color: var(--muted-foreground); font-size: 0.8125rem;">No accuracy data yet</p>';
      return;
    }

    entries.sort((a, b) => a[1] - b[1]); // lowest accuracy first

    container.innerHTML = entries.map(([label, accuracy]) => {
      const pct = Math.round(accuracy * 100);
      let cls = '';
      if (pct >= 90) cls = 'text-success';
      else if (pct >= 70) cls = 'text-warning';
      else cls = 'text-danger';

      return `<div class="metric-row">
        <span>${this._esc(label)}</span>
        <strong class="${cls}">${pct}%</strong>
      </div>`;
    }).join('');
  }

  _showPatternDetail(predicted, actual) {
    const panel = document.getElementById('confusion-detail-panel');
    if (!panel || !this._confusionData) return;

    const patterns = this._confusionData.patterns || [];
    const pattern = patterns.find(
      p => p.predicted_label === predicted && p.actual_label === actual
    );

    if (!pattern) {
      panel.innerHTML = `
        <h4 class="detail-header">PATTERN DETAILS</h4>
        <p style="font-size: 0.8125rem; color: var(--muted-foreground);">
          ${this._esc(predicted)} \u2192 ${this._esc(actual)}: No confusion recorded
        </p>`;
      return;
    }

    let examplesHtml = '';
    if (pattern.examples && pattern.examples.length > 0) {
      examplesHtml = '<h4 class="detail-header" style="margin-top: 0.75rem;">EXAMPLES</h4>' +
        pattern.examples.map(e => {
          let meta = 'ID: ' + this._esc(e.instance_id);
          if (e.llm_confidence != null) meta += ' | Conf: ' + Math.round(e.llm_confidence * 100) + '%';
          return `<div class="confusion-example">
            <div class="example-text">${this._esc(e.text || '(no text)')}</div>
            <div class="example-meta">${meta}</div>
            ${e.llm_reasoning ? '<div class="example-meta" style="margin-top:2px;">Reasoning: ' + this._esc(e.llm_reasoning) + '</div>' : ''}
          </div>`;
        }).join('');
    }

    let rootCauseHtml = '';
    if (pattern.root_cause) {
      rootCauseHtml = `<div class="root-cause-box">${this._esc(pattern.root_cause)}</div>`;
    }

    panel.innerHTML = `
      <h4 class="detail-header">PATTERN DETAILS</h4>
      <div class="detail-rule-text">${this._esc(predicted)} \u2192 ${this._esc(actual)}</div>
      <div class="detail-row"><span>Count</span><strong>${pattern.count}</strong></div>
      <div class="detail-row"><span>% of Errors</span><strong>${pattern.percent}%</strong></div>
      ${rootCauseHtml}
      ${examplesHtml}
      <button class="suggest-btn" style="margin-top: 0.75rem; width: 100%;"
              onclick="soloDashboard.suggestGuideline('${this._esc(predicted)}','${this._esc(actual)}')">
        Suggest Guideline Fix
      </button>`;
  }

  async suggestGuideline(predicted, actual) {
    try {
      const btn = event ? event.target : null;
      if (btn) { btn.disabled = true; btn.textContent = 'Analyzing...'; }

      const resp = await fetch('/solo/api/confusion-analysis/suggest-guideline', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ predicted_label: predicted, actual_label: actual }),
      });
      const data = await resp.json();

      if (btn) { btn.disabled = false; btn.textContent = 'Suggest Fix'; }

      if (data.success) {
        let msg = 'Suggested guideline:\n\n' + data.suggestion;
        if (data.root_cause) msg += '\n\nRoot cause: ' + data.root_cause;
        alert(msg);
      } else {
        alert('Could not generate suggestion: ' + (data.error || 'Unknown error'));
      }
    } catch (e) {
      alert('Error: ' + e.message);
    }
  }

  // ── Labeling Functions ─────────────────────────────────

  async _loadLabelingFunctions() {
    try {
      const resp = await fetch('/solo/api/labeling-functions');
      if (!resp.ok) return;
      const data = await resp.json();
      this._lfLoaded = true;

      if (!data.enabled) {
        const tbody = document.getElementById('lf-table-body');
        if (tbody) tbody.innerHTML = '<tr><td colspan="5" class="empty-cell">Labeling functions not enabled</td></tr>';
        return;
      }

      this._renderLabelingFunctions(data);
    } catch (e) {
      console.warn('Solo dashboard: failed to load labeling functions', e);
    }
  }

  _renderLabelingFunctions(data) {
    // Summary cards
    this._setText('lf-total-count', data.total_functions || 0);
    this._setText('lf-enabled-count', data.enabled_functions || 0);
    this._setText('lf-instances-labeled', data.instances_labeled || 0);
    this._setText('lf-abstained-desc',
      (data.instances_abstained || 0) + ' abstained');

    const avgConf = data.avg_confidence || 0;
    this._setText('lf-avg-confidence',
      avgConf > 0 ? Math.round(avgConf * 100) + '%' : '—');

    // Table
    const tbody = document.getElementById('lf-table-body');
    if (!tbody) return;

    const functions = data.functions || [];
    if (functions.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" class="empty-cell">No labeling functions extracted yet. Click "Extract from Predictions" to discover patterns.</td></tr>';
      return;
    }

    // Sort: enabled first, then by coverage desc
    functions.sort((a, b) => {
      if (a.enabled !== b.enabled) return b.enabled ? 1 : -1;
      return (b.coverage || 0) - (a.coverage || 0);
    });

    tbody.innerHTML = functions.map(fn => {
      const conf = Math.round((fn.confidence || 0) * 100);
      const checked = fn.enabled ? 'checked' : '';
      return `<tr>
        <td class="lf-pattern-text" title="${this._esc(fn.pattern_text || '')}">${this._esc(fn.pattern_text || '')}</td>
        <td><span class="lf-label-badge">${this._esc(fn.label || '')}</span></td>
        <td>${conf}%</td>
        <td>${fn.coverage || 0}</td>
        <td>
          <label class="lf-toggle">
            <input type="checkbox" ${checked}
                   onchange="soloDashboard.toggleLabelingFunction('${this._esc(fn.id)}')">
            <span class="slider"></span>
          </label>
        </td>
      </tr>`;
    }).join('');
  }

  async _loadLabelingFunctionStatus() {
    try {
      const resp = await fetch('/solo/api/labeling-functions/stats');
      if (!resp.ok) return;
      const data = await resp.json();
      this._renderLabelingFunctionCard(data);
    } catch (e) {
      // LF not available — hide card
    }
  }

  _renderLabelingFunctionCard(data) {
    const card = document.getElementById('lf-card');
    if (!card) return;

    if (!data.enabled) return;

    card.style.display = '';
    this._setText('ov-lf-count', data.total_functions || 0);
    this._setText('ov-lf-desc',
      (data.total_functions === 1 ? 'function extracted' : 'functions extracted'));
    this._setText('ov-lf-labeled', data.instances_labeled || 0);
    this._setText('ov-lf-saved', data.instances_labeled || 0);
  }

  async extractLabelingFunctions() {
    try {
      const btn = event ? event.target : null;
      if (btn) { btn.disabled = true; btn.textContent = 'Extracting...'; }

      const resp = await fetch('/solo/api/labeling-functions/extract', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      const data = await resp.json();

      if (btn) { btn.disabled = false; btn.textContent = 'Extract Functions'; }

      if (data.success) {
        const msg = data.extracted > 0
          ? `Extracted ${data.extracted} new labeling functions (total: ${data.total})`
          : (data.message || 'No new functions extracted');
        alert(msg);
        this._lfLoaded = false;
        this._loadLabelingFunctions();
        this._loadLabelingFunctionStatus();
      } else {
        alert('Error: ' + (data.error || 'Unknown error'));
      }
    } catch (e) {
      alert('Error: ' + e.message);
    }
  }

  async toggleLabelingFunction(functionId) {
    try {
      const resp = await fetch(`/solo/api/labeling-functions/${functionId}/toggle`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      const data = await resp.json();
      if (!data.success) {
        alert('Error: ' + (data.error || 'Unknown error'));
        // Reload to reset toggle state
        this._lfLoaded = false;
        this._loadLabelingFunctions();
      }
    } catch (e) {
      alert('Error: ' + e.message);
    }
  }

  // ── Refinement Loop ────────────────────────────────────

  async _loadRefinementStatus() {
    try {
      const resp = await fetch('/solo/api/refinement-status');
      if (!resp.ok) return;
      const data = await resp.json();
      this._renderRefinement(data);
    } catch (e) {
      // Refinement not available — hide card
    }
  }

  _renderRefinement(data) {
    const card = document.getElementById('refinement-card');
    if (!card) return;

    if (!data.enabled) return;

    card.style.display = '';

    this._setText('ov-refinement-cycles', data.total_cycles || 0);
    this._setText('ov-refinement-desc',
      (data.total_cycles === 1 ? 'cycle completed' : 'cycles completed'));

    // Status badge
    const statusEl = document.getElementById('ov-refinement-status');
    if (statusEl) {
      if (data.is_stopped) {
        statusEl.innerHTML = '<span class="status-badge status-pending">' +
          this._esc(data.stop_reason || 'Stopped') + '</span>';
      } else if (data.is_running) {
        statusEl.innerHTML = '<span class="status-badge status-active">Running</span>';
      } else {
        statusEl.innerHTML = '<span class="status-badge status-active">Active</span>';
      }
    }

    // Last improvement
    const impEl = document.getElementById('ov-refinement-improvement');
    if (impEl) {
      if (data.last_improvement != null) {
        const pct = (data.last_improvement * 100).toFixed(1);
        const sign = data.last_improvement >= 0 ? '+' : '';
        impEl.textContent = sign + pct + '%';
        impEl.className = data.last_improvement >= 0 ? 'text-success' : 'text-danger';
      } else {
        impEl.textContent = '\u2014';
      }
    }

    // Next check
    this._setText('ov-refinement-next',
      data.is_stopped ? 'Stopped' : (data.annotations_until_next + ' annotations'));

    // Show reset button if stopped
    const resetBtn = document.getElementById('ov-refinement-reset-btn');
    if (resetBtn) {
      resetBtn.style.display = data.is_stopped ? '' : 'none';
    }
  }

  async triggerRefinement() {
    try {
      const resp = await fetch('/solo/api/refinement/trigger', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      const data = await resp.json();
      if (data.success) {
        const cycle = data.cycle;
        if (cycle) {
          alert('Refinement cycle ' + cycle.cycle_number + ': ' + cycle.status +
            '\nSuggestions: ' + cycle.suggestions_generated);
        } else {
          alert(data.message || 'Refinement cycle completed');
        }
        this._loadRefinementStatus();
      } else {
        alert('Error: ' + (data.error || 'Unknown error'));
      }
    } catch (e) {
      alert('Error: ' + e.message);
    }
  }

  async resetRefinement() {
    try {
      const resp = await fetch('/solo/api/refinement/reset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      const data = await resp.json();
      if (data.success) {
        this._loadRefinementStatus();
      } else {
        alert('Error: ' + (data.error || 'Unknown error'));
      }
    } catch (e) {
      alert('Error: ' + e.message);
    }
  }

  // ── Disagreement Explorer Tab ──────────────────────────

  async _loadDisagreements(labelFilter) {
    try {
      let url = '/solo/api/disagreement-explorer';
      if (labelFilter) url += '?label=' + encodeURIComponent(labelFilter);

      const [explorerResp, timelineResp] = await Promise.all([
        fetch(url),
        fetch('/solo/api/disagreement-timeline'),
      ]);

      if (!explorerResp.ok || !timelineResp.ok) return;

      const data = await explorerResp.json();
      const timeline = await timelineResp.json();

      this._disagreeData = data;
      this._disagreeLoaded = true;

      this._renderDisagreementSummary(data.summary || {});
      this._renderDisagreementScatter(data.scatter_points || []);
      this._renderDisagreementTimeline(timeline);
      this._renderLabelBreakdown(data.label_breakdown || []);
      this._renderDisagreementList(data.disagreements || []);
      this._populateLabelFilter(data.label_breakdown || []);
    } catch (e) {
      console.warn('Solo dashboard: failed to load disagreements', e);
    }
  }

  _renderDisagreementSummary(summary) {
    this._setText('disagree-total-compared', summary.total_compared || 0);
    this._setText('disagree-total-disagreements', summary.total_disagreements || 0);

    const rate = Math.round((summary.disagreement_rate || 0) * 100);
    const rateEl = document.getElementById('disagree-rate');
    if (rateEl) {
      rateEl.textContent = rate + '%';
      rateEl.className = 'card-value';
      if (rate <= 10) rateEl.classList.add('text-success');
      else if (rate <= 25) rateEl.classList.add('text-warning');
      else rateEl.classList.add('text-danger');
    }

    const avgConf = summary.avg_disagreement_confidence || 0;
    this._setText('disagree-avg-conf',
      avgConf > 0 ? Math.round(avgConf * 100) + '%' : '\u2014');
  }

  _renderDisagreementScatter(points) {
    const container = document.getElementById('disagree-scatter');
    if (!container || typeof d3 === 'undefined') return;

    container.innerHTML = '';

    if (points.length === 0) {
      container.innerHTML = '<p style="color: var(--muted-foreground); text-align: center; padding: 2rem;">No comparison data yet</p>';
      return;
    }

    const margin = { top: 20, right: 20, bottom: 40, left: 50 };
    const width = container.clientWidth - margin.left - margin.right;
    const height = 310 - margin.top - margin.bottom;

    const svg = d3.select(container)
      .append('svg')
      .attr('width', width + margin.left + margin.right)
      .attr('height', height + margin.top + margin.bottom)
      .append('g')
      .attr('transform', `translate(${margin.left},${margin.top})`);

    // Scales
    const x = d3.scaleLinear().domain([0, 1]).range([0, width]);
    const y = d3.scaleLinear().domain([0, points.length - 1]).range([height, 0]);

    // X axis
    svg.append('g')
      .attr('transform', `translate(0,${height})`)
      .call(d3.axisBottom(x).ticks(5).tickFormat(d => Math.round(d * 100) + '%'))
      .selectAll('text')
      .style('font-size', '0.6875rem')
      .style('fill', 'var(--muted-foreground, #71717a)');

    svg.append('text')
      .attr('x', width / 2)
      .attr('y', height + 35)
      .attr('text-anchor', 'middle')
      .style('font-size', '0.75rem')
      .style('fill', 'var(--muted-foreground, #71717a)')
      .text('Confidence');

    // Y axis label
    svg.append('text')
      .attr('transform', 'rotate(-90)')
      .attr('x', -height / 2)
      .attr('y', -40)
      .attr('text-anchor', 'middle')
      .style('font-size', '0.75rem')
      .style('fill', 'var(--muted-foreground, #71717a)')
      .text('Instance (sorted by confidence)');

    // Tooltip
    const tooltip = d3.select(container)
      .append('div')
      .attr('class', 'scatter-tooltip')
      .style('display', 'none');

    // Draw dots
    const self = this;
    svg.selectAll('.scatter-dot')
      .data(points)
      .enter()
      .append('circle')
      .attr('class', 'scatter-dot')
      .attr('cx', d => x(d.confidence))
      .attr('cy', (d, i) => y(i))
      .attr('r', 4)
      .attr('fill', d => d.agrees
        ? 'var(--success-color, #10b981)'
        : 'var(--danger-color, #ef4444)')
      .attr('opacity', 0.7)
      .on('mouseover', function(event, d) {
        tooltip.style('display', 'block')
          .html(`
            <div class="tooltip-label">${self._esc(d.instance_id)}</div>
            <div class="tooltip-meta">
              LLM: ${self._esc(d.llm_label)}
              ${d.human_label ? ' | Human: ' + self._esc(d.human_label) : ''}
              <br>Confidence: ${Math.round(d.confidence * 100)}%
              | ${d.agrees ? 'Agrees' : 'Disagrees'}
            </div>
            ${d.text ? '<div style="margin-top:4px;font-size:0.6875rem;">' + self._esc(d.text.substring(0, 100)) + '</div>' : ''}
          `);
      })
      .on('mousemove', function(event) {
        tooltip
          .style('left', (event.offsetX + 12) + 'px')
          .style('top', (event.offsetY - 10) + 'px');
      })
      .on('mouseout', function() {
        tooltip.style('display', 'none');
      });

    // Legend
    const legend = svg.append('g').attr('transform', `translate(${width - 120}, 0)`);
    [{ label: 'Agrees', color: 'var(--success-color, #10b981)' },
     { label: 'Disagrees', color: 'var(--danger-color, #ef4444)' }].forEach((item, i) => {
      legend.append('circle').attr('cx', 0).attr('cy', i * 18).attr('r', 4).attr('fill', item.color);
      legend.append('text').attr('x', 10).attr('y', i * 18 + 4)
        .style('font-size', '0.6875rem')
        .style('fill', 'var(--muted-foreground, #71717a)')
        .text(item.label);
    });
  }

  _renderDisagreementTimeline(timelineData) {
    const container = document.getElementById('disagree-timeline');
    if (!container || typeof d3 === 'undefined') return;

    container.innerHTML = '';

    const buckets = timelineData.buckets || [];
    if (buckets.length === 0) {
      container.innerHTML = '<p style="color: var(--muted-foreground); text-align: center; padding: 1rem; font-size: 0.8125rem;">Not enough data</p>';
      return;
    }

    // Trend badge
    const trendEl = document.getElementById('disagree-trend-badge');
    if (trendEl) {
      const trend = timelineData.trend || 'stable';
      trendEl.textContent = trend.charAt(0).toUpperCase() + trend.slice(1);
      trendEl.className = 'trend-badge trend-' + trend;
    }

    const margin = { top: 10, right: 10, bottom: 25, left: 35 };
    const width = container.clientWidth - margin.left - margin.right;
    const height = 150 - margin.top - margin.bottom;

    const svg = d3.select(container)
      .append('svg')
      .attr('width', width + margin.left + margin.right)
      .attr('height', height + margin.top + margin.bottom)
      .append('g')
      .attr('transform', `translate(${margin.left},${margin.top})`);

    const x = d3.scaleBand()
      .domain(buckets.map(b => b.bucket_index))
      .range([0, width])
      .padding(0.2);

    const y = d3.scaleLinear().domain([0, 1]).range([height, 0]);

    // Y axis
    svg.append('g')
      .call(d3.axisLeft(y).ticks(4).tickFormat(d => Math.round(d * 100) + '%'))
      .selectAll('text')
      .style('font-size', '0.625rem')
      .style('fill', 'var(--muted-foreground, #71717a)');

    // X axis
    svg.append('g')
      .attr('transform', `translate(0,${height})`)
      .call(d3.axisBottom(x).tickFormat(d => '#' + (d + 1)))
      .selectAll('text')
      .style('font-size', '0.625rem')
      .style('fill', 'var(--muted-foreground, #71717a)');

    // Bars
    svg.selectAll('.timeline-bar')
      .data(buckets)
      .enter()
      .append('rect')
      .attr('class', 'timeline-bar')
      .attr('x', d => x(d.bucket_index))
      .attr('y', d => y(d.agreement_rate))
      .attr('width', x.bandwidth())
      .attr('height', d => height - y(d.agreement_rate))
      .attr('fill', d => d.agreement_rate >= 0.8
        ? 'var(--success-color, #10b981)'
        : d.agreement_rate >= 0.6
          ? 'var(--warning-color, #f59e0b)'
          : 'var(--danger-color, #ef4444)')
      .attr('rx', 2);
  }

  _renderLabelBreakdown(breakdown) {
    const container = document.getElementById('disagree-label-breakdown');
    if (!container) return;

    if (!breakdown || breakdown.length === 0) {
      container.innerHTML = '<p style="color: var(--muted-foreground); font-size: 0.8125rem;">No breakdown data yet</p>';
      return;
    }

    container.innerHTML = breakdown.map(b => {
      const pct = Math.round(b.agreement_rate * 100);
      let cls = '';
      if (pct >= 90) cls = 'text-success';
      else if (pct >= 70) cls = 'text-warning';
      else cls = 'text-danger';

      let confused = '';
      if (b.confused_with && b.confused_with.length > 0) {
        confused = '<span style="font-size: 0.625rem; color: var(--muted-foreground);"> confused with: ' +
          b.confused_with.map(c => this._esc(c.label) + '(' + c.count + ')').join(', ') + '</span>';
      }

      return `<div class="metric-row">
        <span>${this._esc(b.label)} <small>(${b.total_comparisons})</small>${confused}</span>
        <strong class="${cls}">${pct}%</strong>
      </div>`;
    }).join('');
  }

  _renderDisagreementList(disagreements) {
    const container = document.getElementById('disagree-list');
    if (!container) return;

    if (!disagreements || disagreements.length === 0) {
      container.innerHTML = '<p style="color: var(--muted-foreground); font-size: 0.8125rem;">No disagreements found</p>';
      return;
    }

    container.innerHTML = disagreements.map(d => {
      const conf = Math.round((d.confidence || 0) * 100);
      const resolvedClass = d.resolved ? ' resolved' : '';

      return `<div class="disagree-item${resolvedClass}">
        <div class="disagree-labels">
          <span class="label-pill llm">LLM: ${this._esc(d.llm_label)}</span>
          <span class="label-pill human">Human: ${this._esc(d.human_label)}</span>
          <span style="font-size: 0.6875rem; color: var(--muted-foreground);">Confidence: ${conf}%</span>
          ${d.resolved ? '<span style="font-size: 0.6875rem; color: var(--success-color, #10b981);">Resolved' + (d.resolution_label ? ': ' + this._esc(d.resolution_label) : '') + '</span>' : ''}
        </div>
        ${d.text ? '<div class="disagree-text">' + this._esc(d.text) + '</div>' : ''}
        ${d.reasoning ? '<div class="disagree-meta">Reasoning: ' + this._esc(d.reasoning.substring(0, 200)) + '</div>' : ''}
        <div class="disagree-meta">ID: ${this._esc(d.instance_id)}${d.timestamp ? ' | ' + d.timestamp : ''}</div>
      </div>`;
    }).join('');
  }

  _populateLabelFilter(breakdown) {
    const select = document.getElementById('disagree-label-filter');
    if (!select) return;

    // Preserve current value
    const current = select.value;
    select.innerHTML = '<option value="">All labels</option>';

    (breakdown || []).forEach(b => {
      const opt = document.createElement('option');
      opt.value = b.label;
      opt.textContent = b.label + ' (' + b.total_comparisons + ')';
      select.appendChild(opt);
    });

    if (current) select.value = current;
  }

  filterDisagreements() {
    const select = document.getElementById('disagree-label-filter');
    const label = select ? select.value : '';
    this._disagreeLoaded = false;
    this._loadDisagreements(label || undefined);
  }

  // ── Cluster Viz Tab ─────────────────────────────────────

  async _initViz() {
    const el = document.getElementById('rule-cluster-chart');
    if (!el) return;

    this.viz = new RuleClusterViz('rule-cluster-chart', {
      onRuleSelect: (d) => this._showRuleDetail(d),
    });
    await this.viz.init();
  }

  _showRuleDetail(d) {
    const panel = document.getElementById('rule-detail-panel');
    if (!panel) return;

    const conf = Math.round((d.confidence || 0) * 100);
    const status = d.approved ? 'Approved' : d.reviewed ? 'Rejected' : 'Pending';

    panel.innerHTML = `
      <h4 class="detail-header">RULE DETAILS</h4>
      <div class="detail-rule-text">${this._esc(d.rule_text || '')}</div>
      <div class="detail-metrics">
        <div class="detail-row"><span>Instance</span><strong>${this._esc(d.instance_id || '?')}</strong></div>
        <div class="detail-row"><span>Confidence</span><strong>${conf}%</strong></div>
        <div class="detail-row"><span>Category</span><strong>${this._esc(d.category_summary || 'Unclustered')}</strong></div>
        <div class="detail-row"><span>Status</span><strong>${status}</strong></div>
      </div>`;
  }

  // ── Rule Review Actions ─────────────────────────────────

  async approveCategory(categoryId, action, notes) {
    try {
      const resp = await fetch('/solo/api/rules/approve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ category_id: categoryId, action: action, notes: notes || '' }),
      });
      const data = await resp.json();
      if (data.success) window.location.reload();
      else alert('Error: ' + (data.error || 'Unknown error'));
    } catch (e) {
      alert('Error: ' + e.message);
    }
  }

  async applyRules() {
    try {
      const resp = await fetch('/solo/api/rules/apply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      const data = await resp.json();
      if (data.success) {
        alert('Rules applied! New prompt version: ' + data.new_prompt_version);
        window.location.reload();
      } else {
        alert('Error: ' + (data.error || 'Unknown error'));
      }
    } catch (e) {
      alert('Error: ' + e.message);
    }
  }

  async triggerClustering() {
    try {
      const resp = await fetch('/solo/api/rules/cluster', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      const data = await resp.json();
      if (data.success) {
        alert('Clustering triggered. Results will appear shortly.');
        setTimeout(() => {
          if (this.viz) this.viz.refresh(true);
          this._loadRules();
        }, 3000);
      }
    } catch (e) {
      alert('Error: ' + e.message);
    }
  }

  // ── Helpers ─────────────────────────────────────────────

  _setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  _esc(text) {
    const d = document.createElement('div');
    d.textContent = text;
    return d.innerHTML;
  }

  destroy() {
    if (this.refreshInterval) clearInterval(this.refreshInterval);
  }
}

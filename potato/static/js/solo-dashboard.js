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

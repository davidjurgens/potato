/**
 * Solo Mode Rule Cluster Visualization
 *
 * Interactive D3.js scatter plot showing edge case rules
 * colored by cluster, with hover tooltips and click selection.
 */

class RuleClusterViz {
  constructor(containerId, options = {}) {
    this.containerId = containerId;
    this.container = document.getElementById(containerId);
    this.options = {
      height: options.height || 450,
      margin: options.margin || { top: 20, right: 20, bottom: 40, left: 50 },
      pointRadius: options.pointRadius || 6,
      centroidRadius: options.centroidRadius || 16,
      transitionDuration: 300,
    };

    this.data = null;
    this.svg = null;
    this.tooltip = null;
    this.selectedRuleId = null;
    this.onRuleSelect = options.onRuleSelect || null;

    // 10 distinct cluster colors
    this.clusterColors = [
      '#6e56cf', '#e5484d', '#30a46c', '#e38f25',
      '#3b82f6', '#ec4899', '#14b8a6', '#f97316',
      '#8b5cf6', '#06b6d4',
    ];
  }

  async init() {
    if (!this.container) return false;
    this._createLayout();
    await this.refresh();
    return true;
  }

  _createLayout() {
    this.container.innerHTML = '';
    this.container.style.position = 'relative';

    const rect = this.container.getBoundingClientRect();
    const width = rect.width || 600;
    const { height, margin } = this.options;
    this.width = width;
    this.plotWidth = width - margin.left - margin.right;
    this.plotHeight = height - margin.top - margin.bottom;

    this.svg = d3.select(this.container)
      .append('svg')
      .attr('width', '100%')
      .attr('height', height)
      .attr('viewBox', `0 0 ${width} ${height}`)
      .attr('preserveAspectRatio', 'xMidYMid meet');

    this.plotGroup = this.svg.append('g')
      .attr('transform', `translate(${margin.left},${margin.top})`);

    // Clip path
    this.plotGroup.append('defs')
      .append('clipPath')
      .attr('id', 'solo-plot-clip')
      .append('rect')
      .attr('width', this.plotWidth)
      .attr('height', this.plotHeight);

    // Axis groups
    this.xAxisGroup = this.plotGroup.append('g')
      .attr('class', 'x-axis')
      .attr('transform', `translate(0,${this.plotHeight})`);
    this.yAxisGroup = this.plotGroup.append('g')
      .attr('class', 'y-axis');

    // Render groups (order = back to front)
    this.centroidsGroup = this.plotGroup.append('g')
      .attr('clip-path', 'url(#solo-plot-clip)');
    this.pointsGroup = this.plotGroup.append('g')
      .attr('clip-path', 'url(#solo-plot-clip)');

    // Tooltip
    this.tooltip = d3.select(this.container)
      .append('div')
      .attr('class', 'rule-tooltip')
      .style('position', 'absolute')
      .style('pointer-events', 'none')
      .style('opacity', 0)
      .style('background', 'white')
      .style('border', '1px solid var(--border, #e4e4e7)')
      .style('border-radius', 'var(--radius, 0.5rem)')
      .style('padding', '0.75rem')
      .style('box-shadow', 'var(--box-shadow, 0 1px 3px rgba(0,0,0,0.1))')
      .style('font-size', '0.8125rem')
      .style('max-width', '300px')
      .style('z-index', '20');
  }

  async refresh(forceRefresh) {
    try {
      const url = '/solo/api/rules/viz-data' + (forceRefresh ? '?force_refresh=true' : '');
      const resp = await fetch(url);
      if (!resp.ok) throw new Error('Failed to load viz data');
      this.data = await resp.json();
      this._render();
    } catch (err) {
      this._showError(err.message);
    }
  }

  _render() {
    if (!this.data || !this.data.points || this.data.points.length === 0) {
      this._showEmpty();
      return;
    }

    const { points, clusters } = this.data;
    const { margin } = this.options;

    // Compute scales
    const xExtent = d3.extent(points, d => d.x);
    const yExtent = d3.extent(points, d => d.y);
    const xPad = (xExtent[1] - xExtent[0]) * 0.1 || 1;
    const yPad = (yExtent[1] - yExtent[0]) * 0.1 || 1;

    this.xScale = d3.scaleLinear()
      .domain([xExtent[0] - xPad, xExtent[1] + xPad])
      .range([0, this.plotWidth]);
    this.yScale = d3.scaleLinear()
      .domain([yExtent[0] - yPad, yExtent[1] + yPad])
      .range([this.plotHeight, 0]);

    // Axes
    this.xAxisGroup.call(d3.axisBottom(this.xScale).ticks(5))
      .selectAll('text').style('font-size', '11px').style('fill', '#71717a');
    this.yAxisGroup.call(d3.axisLeft(this.yScale).ticks(5))
      .selectAll('text').style('font-size', '11px').style('fill', '#71717a');
    this.xAxisGroup.selectAll('.domain, line').style('stroke', '#e4e4e7');
    this.yAxisGroup.selectAll('.domain, line').style('stroke', '#e4e4e7');

    const colorFn = (d) => {
      if (d.cluster_id == null) return '#94a3b8';
      const idx = clusters.findIndex(c => c.id === d.cluster_id);
      return idx >= 0 ? this.clusterColors[idx % this.clusterColors.length] : '#94a3b8';
    };

    // --- Cluster centroid halos ---
    const centroidData = clusters.filter(c => c.centroid_x != null);
    const centroids = this.centroidsGroup.selectAll('.centroid')
      .data(centroidData, d => d.id);

    centroids.enter()
      .append('circle')
      .attr('class', 'centroid')
      .attr('r', 0)
      .merge(centroids)
      .transition().duration(this.options.transitionDuration)
      .attr('cx', d => this.xScale(d.centroid_x))
      .attr('cy', d => this.yScale(d.centroid_y))
      .attr('r', d => Math.max(this.options.centroidRadius, Math.sqrt(d.size || 1) * 8))
      .attr('fill', (d, i) => this.clusterColors[i % this.clusterColors.length])
      .attr('fill-opacity', 0.08)
      .attr('stroke', (d, i) => this.clusterColors[i % this.clusterColors.length])
      .attr('stroke-width', 1.5)
      .attr('stroke-dasharray', '4,3');
    centroids.exit().transition().duration(200).attr('r', 0).remove();

    // --- Centroid labels ---
    const labels = this.centroidsGroup.selectAll('.centroid-label')
      .data(centroidData, d => d.id);

    labels.enter()
      .append('text')
      .attr('class', 'centroid-label')
      .merge(labels)
      .attr('x', d => this.xScale(d.centroid_x))
      .attr('y', d => this.yScale(d.centroid_y) - Math.max(this.options.centroidRadius, Math.sqrt(d.size || 1) * 8) - 6)
      .attr('text-anchor', 'middle')
      .attr('font-size', '10px')
      .attr('font-weight', '500')
      .attr('fill', '#71717a')
      .text(d => {
        const text = d.summary_rule || d.id;
        return text.length > 35 ? text.substring(0, 33) + '...' : text;
      });
    labels.exit().remove();

    // --- Rule points ---
    const pts = this.pointsGroup.selectAll('.rule-point')
      .data(points, d => d.rule_id);

    const enter = pts.enter()
      .append('circle')
      .attr('class', 'rule-point')
      .attr('r', 0)
      .attr('cx', d => this.xScale(d.x))
      .attr('cy', d => this.yScale(d.y))
      .style('cursor', 'pointer');

    enter.merge(pts)
      .on('mouseenter', (event, d) => this._showTooltip(event, d))
      .on('mouseleave', () => this._hideTooltip())
      .on('click', (event, d) => this._selectRule(d))
      .transition().duration(this.options.transitionDuration)
      .attr('cx', d => this.xScale(d.x))
      .attr('cy', d => this.yScale(d.y))
      .attr('r', this.options.pointRadius)
      .attr('fill', colorFn)
      .attr('fill-opacity', 0.8)
      .attr('stroke', d => d.approved ? '#10b981' : d.reviewed ? '#ef4444' : '#fff')
      .attr('stroke-width', d => d.reviewed ? 2.5 : 1.5);

    pts.exit().transition().duration(200).attr('r', 0).remove();

    // --- Legend ---
    this._renderLegend(clusters);
  }

  _renderLegend(clusters) {
    this.svg.selectAll('.legend-group').remove();
    if (clusters.length === 0) return;

    const legend = this.svg.append('g')
      .attr('class', 'legend-group')
      .attr('transform', `translate(${this.options.margin.left + 8}, ${this.options.height - 16})`);

    clusters.forEach((c, i) => {
      const g = legend.append('g')
        .attr('transform', `translate(${i * 120}, 0)`);
      g.append('circle')
        .attr('r', 4)
        .attr('fill', this.clusterColors[i % this.clusterColors.length]);
      g.append('text')
        .attr('x', 8)
        .attr('y', 4)
        .attr('font-size', '10px')
        .attr('fill', '#71717a')
        .text((c.summary_rule || c.id).substring(0, 14));
    });
  }

  _showTooltip(event, d) {
    const conf = Math.round((d.confidence || 0) * 100);
    const status = d.approved ? 'Approved' : d.reviewed ? 'Rejected' : 'Pending';

    this.tooltip
      .html(`
        <div style="font-weight:600;margin-bottom:4px;line-height:1.3;">${this._esc(d.rule_text || 'No rule text')}</div>
        <div style="font-size:11px;color:#71717a;line-height:1.5;">
          Instance: ${this._esc(d.instance_id || '?')}<br>
          Confidence: ${conf}%<br>
          Cluster: ${this._esc(d.category_summary || d.cluster_id || 'Unclustered')}<br>
          Status: <strong>${status}</strong>
        </div>
      `)
      .style('opacity', 1)
      .style('left', (event.offsetX + 14) + 'px')
      .style('top', (event.offsetY - 14) + 'px');
  }

  _hideTooltip() {
    this.tooltip.style('opacity', 0);
  }

  _selectRule(d) {
    this.selectedRuleId = d.rule_id;
    this.pointsGroup.selectAll('.rule-point')
      .attr('stroke-width', p => p.rule_id === d.rule_id ? 3.5 : (p.reviewed ? 2.5 : 1.5))
      .attr('stroke', p => {
        if (p.rule_id === d.rule_id) return '#09090b';
        if (p.approved) return '#10b981';
        if (p.reviewed) return '#ef4444';
        return '#fff';
      });
    if (this.onRuleSelect) this.onRuleSelect(d);
  }

  _showEmpty() {
    this.pointsGroup.selectAll('*').remove();
    this.centroidsGroup.selectAll('*').remove();
    this.svg.selectAll('.legend-group').remove();
    this.svg.append('text')
      .attr('x', this.width / 2)
      .attr('y', this.options.height / 2)
      .attr('text-anchor', 'middle')
      .attr('fill', '#94a3b8')
      .attr('font-size', '14px')
      .text('No rule data available — rules appear after LLM labeling discovers edge cases');
  }

  _showError(msg) {
    this.container.innerHTML = `
      <div style="padding:2rem;text-align:center;color:#ef4444;">
        <p style="font-weight:600;">Failed to load visualization</p>
        <p style="font-size:12px;color:#94a3b8;margin-top:0.5rem;">${this._esc(msg)}</p>
      </div>`;
  }

  _esc(text) {
    const d = document.createElement('div');
    d.textContent = text;
    return d.innerHTML;
  }
}

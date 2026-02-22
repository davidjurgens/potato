/**
 * Embedding Visualization Manager
 *
 * Interactive scatter plot visualization of text/image embeddings
 * with selection tools for prioritizing annotation order.
 */

class EmbeddingVizManager {
  constructor(containerId, apiKey) {
    this.container = document.getElementById(containerId);
    this.apiKey = apiKey;
    this.plot = null;
    this.data = null;
    this.selections = []; // Multiple selection groups
    this.currentSelection = null;
    this.selectionCounter = 0;

    // Configuration
    this.config = {
      markerSize: 8,
      markerSizeSelected: 12,
      hoverPreviewLength: 300,
      maxSelectionsDisplayed: 5,
    };

    // Bind methods
    this.handleSelection = this.handleSelection.bind(this);
    this.handleHover = this.handleHover.bind(this);
    this.handleClick = this.handleClick.bind(this);
  }

  /**
   * Initialize the visualization
   */
  async init() {
    if (!this.container) {
      console.error("Container element not found");
      return false;
    }

    this.showLoading(true);

    try {
      await this.loadData();
      this.render();
      this.setupEventListeners();
      this.showLoading(false);
      return true;
    } catch (error) {
      console.error("Failed to initialize embedding visualization:", error);
      this.showError(error.message);
      this.showLoading(false);
      return false;
    }
  }

  /**
   * Load visualization data from API
   */
  async loadData(forceRefresh = false) {
    const url = `/admin/api/embedding_viz/data${
      forceRefresh ? "?force_refresh=true" : ""
    }`;

    const response = await fetch(url, {
      headers: {
        "X-API-Key": this.apiKey,
      },
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error || "Failed to load visualization data");
    }

    this.data = await response.json();

    if (this.data.stats && this.data.stats.error) {
      throw new Error(this.data.stats.error);
    }

    return this.data;
  }

  /**
   * Render the Plotly scatter plot
   */
  render() {
    if (!this.data || !this.data.points || this.data.points.length === 0) {
      this.showError("No data available for visualization");
      return;
    }

    // Prepare data for Plotly
    const points = this.data.points;
    const labelColors = this.data.label_colors;

    // Group points by label for legend
    const tracesByLabel = {};
    const labels = this.data.labels || [];

    // Initialize traces for each label
    labels.forEach((label) => {
      const labelKey = label === null ? "Unannotated" : label;
      tracesByLabel[labelKey] = {
        x: [],
        y: [],
        customdata: [],
        name: labelKey,
        mode: "markers",
        type: "scatter",
        marker: {
          color: labelColors[label] || "#94a3b8",
          size: this.config.markerSize,
          line: {
            width: 0,
            color: "transparent",
          },
        },
        hovertemplate:
          "<b>%{customdata.instance_id}</b><br>" +
          "%{customdata.truncatedPreview}<br>" +
          "<extra>%{customdata.label_display}</extra>",
      };
    });

    // Populate traces
    points.forEach((point) => {
      const labelKey = point.label === null ? "Unannotated" : point.label;

      if (!tracesByLabel[labelKey]) {
        // Handle unexpected labels
        tracesByLabel[labelKey] = {
          x: [],
          y: [],
          customdata: [],
          name: labelKey,
          mode: "markers",
          type: "scatter",
          marker: {
            color: "#94a3b8",
            size: this.config.markerSize,
          },
          hovertemplate:
            "<b>%{customdata.instance_id}</b><br>" +
            "%{customdata.truncatedPreview}<br>" +
            "<extra>%{customdata.label_display}</extra>",
        };
      }

      const truncatedPreview =
        point.preview.length > this.config.hoverPreviewLength
          ? point.preview.substring(0, this.config.hoverPreviewLength) + "..."
          : point.preview;

      tracesByLabel[labelKey].x.push(point.x);
      tracesByLabel[labelKey].y.push(point.y);
      tracesByLabel[labelKey].customdata.push({
        instance_id: point.instance_id,
        preview: point.preview,
        truncatedPreview: truncatedPreview,
        label: point.label,
        label_display: point.label
          ? `Label: ${point.label}`
          : "Not yet annotated",
        annotated: point.annotated,
        annotation_count: point.annotation_count,
        preview_type: point.preview_type,
      });
    });

    // Convert to array of traces
    const traces = Object.values(tracesByLabel);

    // Layout configuration
    const layout = {
      title: {
        text: "Embedding Visualization",
        font: { size: 16 },
      },
      xaxis: {
        title: "UMAP Dimension 1",
        zeroline: false,
        showgrid: true,
        gridcolor: "#f0f0f0",
      },
      yaxis: {
        title: "UMAP Dimension 2",
        zeroline: false,
        showgrid: true,
        gridcolor: "#f0f0f0",
      },
      hovermode: "closest",
      dragmode: "lasso",
      showlegend: true,
      legend: {
        orientation: "h",
        yanchor: "bottom",
        y: 1.02,
        xanchor: "right",
        x: 1,
      },
      margin: { l: 60, r: 20, t: 60, b: 60 },
      plot_bgcolor: "#ffffff",
      paper_bgcolor: "#ffffff",
    };

    // Config for Plotly
    const config = {
      displayModeBar: true,
      modeBarButtonsToAdd: ["lasso2d", "select2d"],
      modeBarButtonsToRemove: ["sendDataToCloud"],
      responsive: true,
      displaylogo: false,
    };

    // Create the plot
    Plotly.newPlot(this.container, traces, layout, config);

    // Store reference
    this.plot = this.container;

    // Update stats display
    this.updateStatsDisplay();
  }

  /**
   * Set up event listeners for the plot
   */
  setupEventListeners() {
    // Selection event
    this.container.on("plotly_selected", this.handleSelection);

    // Hover event for preview
    this.container.on("plotly_hover", this.handleHover);

    // Click event
    this.container.on("plotly_click", this.handleClick);

    // Deselect event
    this.container.on("plotly_deselect", () => {
      this.currentSelection = null;
      this.updateSelectionPanel();
    });
  }

  /**
   * Handle lasso/box selection
   */
  handleSelection(eventData) {
    if (!eventData || !eventData.points) {
      return;
    }

    const selectedIds = eventData.points.map(
      (p) => p.customdata.instance_id
    );

    if (selectedIds.length > 0) {
      this.currentSelection = selectedIds;
      this.updateSelectionPanel();
    }
  }

  /**
   * Handle hover event for preview
   */
  handleHover(eventData) {
    if (!eventData || !eventData.points || eventData.points.length === 0) {
      return;
    }

    const point = eventData.points[0].customdata;
    this.updatePreviewPanel(point);
  }

  /**
   * Handle click event
   */
  handleClick(eventData) {
    if (!eventData || !eventData.points || eventData.points.length === 0) {
      return;
    }

    const point = eventData.points[0].customdata;
    this.updatePreviewPanel(point);

    // Single click can add to current selection
    if (this.currentSelection) {
      if (!this.currentSelection.includes(point.instance_id)) {
        this.currentSelection.push(point.instance_id);
        this.updateSelectionPanel();
      }
    } else {
      this.currentSelection = [point.instance_id];
      this.updateSelectionPanel();
    }
  }

  /**
   * Update the preview panel with point details
   */
  updatePreviewPanel(point) {
    const previewPanel = document.getElementById("embedding-viz-preview");
    if (!previewPanel) return;

    let previewContent = "";
    if (point.preview_type === "image") {
      previewContent = `<img src="${point.preview}" alt="Preview" class="preview-image">`;
    } else {
      previewContent = `<div class="preview-text">${this.escapeHtml(
        point.preview
      )}</div>`;
    }

    previewPanel.innerHTML = `
      <div class="preview-header">
        <strong>${point.instance_id}</strong>
        ${
          point.label
            ? `<span class="preview-label" style="background-color: ${
                this.data.label_colors[point.label]
              }">${point.label}</span>`
            : '<span class="preview-label unannotated">Unannotated</span>'
        }
      </div>
      <div class="preview-body">
        ${previewContent}
      </div>
      <div class="preview-meta">
        <span>Annotations: ${point.annotation_count}</span>
      </div>
    `;
  }

  /**
   * Update the selection panel
   */
  updateSelectionPanel() {
    const selectionPanel = document.getElementById(
      "embedding-viz-selection-panel"
    );
    if (!selectionPanel) return;

    let html = "";

    // Current selection
    if (this.currentSelection && this.currentSelection.length > 0) {
      html += `
        <div class="current-selection">
          <div class="selection-header">
            <strong>Current Selection</strong>
            <span class="selection-count">${this.currentSelection.length} items</span>
          </div>
          <div class="selection-preview">
            ${this.currentSelection.slice(0, 5).join(", ")}
            ${this.currentSelection.length > 5 ? "..." : ""}
          </div>
          <div class="selection-actions">
            <button class="btn btn-primary btn-sm" onclick="embeddingViz.addSelectionToQueue()">
              Add to Queue
            </button>
            <button class="btn btn-secondary btn-sm" onclick="embeddingViz.clearCurrentSelection()">
              Clear
            </button>
          </div>
        </div>
      `;
    }

    // Queued selections
    if (this.selections.length > 0) {
      html += '<div class="queued-selections">';
      html += "<h4>Priority Queue</h4>";

      this.selections.forEach((sel, index) => {
        html += `
          <div class="queued-selection" data-index="${index}">
            <div class="queued-selection-header">
              <span class="priority-badge">Priority ${sel.priority}</span>
              <span class="selection-count">${sel.instance_ids.length} items</span>
              <button class="btn-icon" onclick="embeddingViz.removeSelection(${index})" title="Remove">
                &times;
              </button>
            </div>
            <div class="queued-selection-preview">
              ${sel.instance_ids.slice(0, 3).join(", ")}
              ${sel.instance_ids.length > 3 ? "..." : ""}
            </div>
          </div>
        `;
      });

      html += `
        <div class="queue-actions">
          <button class="btn btn-success" onclick="embeddingViz.applyReordering()">
            Apply Reordering
          </button>
          <button class="btn btn-secondary" onclick="embeddingViz.clearAllSelections()">
            Clear All
          </button>
        </div>
      `;
      html += "</div>";
    }

    if (!html) {
      html = `
        <div class="selection-empty">
          <p>Use lasso or box selection to select points</p>
          <p class="text-muted">Selected items will be prioritized for annotation</p>
        </div>
      `;
    }

    selectionPanel.innerHTML = html;
  }

  /**
   * Add current selection to the queue
   */
  addSelectionToQueue() {
    if (!this.currentSelection || this.currentSelection.length === 0) {
      return;
    }

    this.selectionCounter++;
    this.selections.push({
      instance_ids: [...this.currentSelection],
      priority: this.selectionCounter,
    });

    this.currentSelection = null;
    this.updateSelectionPanel();

    // Clear plot selection
    Plotly.restyle(this.container, { selectedpoints: null });
  }

  /**
   * Clear current selection
   */
  clearCurrentSelection() {
    this.currentSelection = null;
    this.updateSelectionPanel();
    Plotly.restyle(this.container, { selectedpoints: null });
  }

  /**
   * Remove a selection from the queue
   */
  removeSelection(index) {
    this.selections.splice(index, 1);

    // Re-number priorities
    this.selections.forEach((sel, i) => {
      sel.priority = i + 1;
    });

    this.updateSelectionPanel();
  }

  /**
   * Clear all selections
   */
  clearAllSelections() {
    this.selections = [];
    this.currentSelection = null;
    this.selectionCounter = 0;
    this.updateSelectionPanel();
    Plotly.restyle(this.container, { selectedpoints: null });
  }

  /**
   * Apply reordering to the annotation queue
   */
  async applyReordering() {
    if (this.selections.length === 0) {
      this.showNotification("No selections to apply", "warning");
      return;
    }

    try {
      this.showLoading(true);

      const response = await fetch("/admin/api/embedding_viz/reorder", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-API-Key": this.apiKey,
        },
        body: JSON.stringify({
          selections: this.selections,
          interleave: true,
        }),
      });

      const result = await response.json();

      if (result.success) {
        this.showNotification(
          `Reordered ${result.reordered_count} instances`,
          "success"
        );
        this.clearAllSelections();
      } else {
        this.showNotification(
          result.error || "Reordering failed",
          "error"
        );
      }
    } catch (error) {
      console.error("Error applying reordering:", error);
      this.showNotification("Error applying reordering", "error");
    } finally {
      this.showLoading(false);
    }
  }

  /**
   * Refresh the visualization data
   */
  async refresh(forceRecompute = true) {
    try {
      this.showLoading(true);

      if (forceRecompute) {
        // Trigger backend refresh
        await fetch("/admin/api/embedding_viz/refresh", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-API-Key": this.apiKey,
          },
          body: JSON.stringify({ force_recompute: true }),
        });
      }

      await this.loadData(true);
      this.render();
      this.showNotification("Visualization refreshed", "success");
    } catch (error) {
      console.error("Error refreshing visualization:", error);
      this.showNotification("Error refreshing visualization", "error");
    } finally {
      this.showLoading(false);
    }
  }

  /**
   * Update the stats display
   */
  updateStatsDisplay() {
    const statsContainer = document.getElementById("embedding-viz-stats");
    if (!statsContainer || !this.data || !this.data.stats) return;

    const stats = this.data.stats;

    statsContainer.innerHTML = `
      <div class="stat-item">
        <span class="stat-value">${stats.visualized_instances || 0}</span>
        <span class="stat-label">Visualized</span>
      </div>
      <div class="stat-item">
        <span class="stat-value">${stats.annotated_instances || 0}</span>
        <span class="stat-label">Annotated</span>
      </div>
      <div class="stat-item">
        <span class="stat-value">${stats.unannotated_instances || 0}</span>
        <span class="stat-label">Unannotated</span>
      </div>
      <div class="stat-item">
        <span class="stat-value">${stats.unique_labels || 0}</span>
        <span class="stat-label">Labels</span>
      </div>
    `;
  }

  /**
   * Show loading indicator
   */
  showLoading(show) {
    const loader = document.getElementById("embedding-viz-loader");
    if (loader) {
      loader.style.display = show ? "flex" : "none";
    }

    if (this.container) {
      this.container.classList.toggle("loading", show);
    }
  }

  /**
   * Show error message
   */
  showError(message) {
    const errorContainer = document.getElementById("embedding-viz-error");
    if (errorContainer) {
      errorContainer.innerHTML = `
        <div class="error-message">
          <strong>Error:</strong> ${this.escapeHtml(message)}
        </div>
      `;
      errorContainer.style.display = "block";
    }
  }

  /**
   * Show notification
   */
  showNotification(message, type = "info") {
    const notification = document.createElement("div");
    notification.className = `notification notification-${type}`;
    notification.textContent = message;

    document.body.appendChild(notification);

    // Auto-remove after 3 seconds
    setTimeout(() => {
      notification.remove();
    }, 3000);
  }

  /**
   * Escape HTML for safe display
   */
  escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }
}

// Global instance
let embeddingViz = null;

/**
 * Initialize the embedding visualization
 */
function initEmbeddingVisualization(containerId, apiKey) {
  embeddingViz = new EmbeddingVizManager(containerId, apiKey);
  embeddingViz.init();
  return embeddingViz;
}

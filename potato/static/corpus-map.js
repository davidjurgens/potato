/*
 * Corpus Map — annotator navigation surface.
 *
 * Renders a 2D cluster-colored scatter of the corpus on a plain <canvas> (no
 * external charting library, so it works fully offline — an annotation tool must
 * not hard-depend on a CDN). Clicking a point points the reading pane (an
 * /annotate iframe) at that document via /corpus/api/goto, then highlights the
 * document's k-nearest-neighbors. A cluster browser filters the map and lists
 * cluster members.
 *
 * Heavy compute happens server-side at ingest; this file only fetches the small
 * precomputed payload. console.log/info are suppressed globally — use warn/error.
 */
(function () {
  "use strict";

  // Deterministic cluster palette (indexed by cluster id).
  const PALETTE = [
    "#2563eb", "#16a34a", "#dc2626", "#9333ea", "#ea580c",
    "#0891b2", "#c026d3", "#ca8a04", "#4f46e5", "#059669",
    "#db2777", "#65a30d", "#0284c7", "#e11d48", "#7c3aed",
  ];
  const DIM = "#cbd5e1";
  const KNN_RING = "#f59e0b";
  const CURRENT_RING = "#111827";
  const PAD = 24;
  const R = 6;

  const el = (role) => document.querySelector(`[data-role="${role}"]`);

  async function api(url, opts) {
    const res = await fetch(url, {
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      ...opts,
    });
    if (!res.ok) throw new Error(`corpus-map API ${url} -> ${res.status}`);
    return res.json();
  }

  class CorpusMap {
    constructor() {
      this.mapEl = el("map");
      this.statusEl = el("status");
      this.clusterListEl = el("cluster-list");
      this.knnEl = el("knn");
      this.knnListEl = el("knn-list");
      this.frame = el("frame");

      this.points = [];
      this.clusters = [];
      this.docIndex = {}; // doc_id -> point index
      this.currentDoc = null;
      this.filterCluster = null;
      this._knnIds = [];

      this._initCanvas();
      this._bind();
      this.start();
    }

    _initCanvas() {
      this.canvas = document.createElement("canvas");
      this.canvas.className = "cm-canvas";
      this.tooltip = document.createElement("div");
      this.tooltip.className = "cm-tooltip";
      this.tooltip.style.display = "none";
      this.mapEl.appendChild(this.canvas);
      this.mapEl.appendChild(this.tooltip);
      this._resize();
      window.addEventListener("resize", () => {
        this._resize();
        this.draw();
      });

      this.canvas.addEventListener("mousemove", (e) => this._onHover(e));
      this.canvas.addEventListener("mouseleave", () => (this.tooltip.style.display = "none"));
      this.canvas.addEventListener("click", (e) => {
        const p = this._hit(e);
        if (p) this.openDoc(p.doc_id);
      });
    }

    _resize() {
      const rect = this.mapEl.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      this.w = Math.max(200, rect.width);
      this.h = Math.max(200, rect.height);
      this.canvas.width = this.w * dpr;
      this.canvas.height = this.h * dpr;
      this.canvas.style.width = this.w + "px";
      this.canvas.style.height = this.h + "px";
      const ctx = this.canvas.getContext("2d");
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      this.ctx = ctx;
    }

    _bind() {
      const rebuild = el("rebuild");
      if (rebuild) rebuild.addEventListener("click", () => this.rebuild());
      const clear = el("clear-filter");
      if (clear) clear.addEventListener("click", () => this.setClusterFilter(null));
    }

    async start() {
      let built = false;
      for (let i = 0; i < 120 && !built; i++) {
        try {
          const st = await api("/corpus/api/build_status");
          this.statusEl.textContent =
            st.state === "done"
              ? `${st.n_docs} documents`
              : st.state === "error"
              ? `Build error: ${st.error}`
              : "Building corpus map…";
          if (st.state === "done" || st.built) { built = true; break; }
          if (st.state === "error") return;
        } catch (e) {
          console.error(e);
        }
        await new Promise((r) => setTimeout(r, 1500));
      }
      await this.load();
    }

    async load() {
      try {
        const data = await api("/corpus/api/map_data");
        this.points = data.points || [];
        this.clusters = data.clusters || [];
        this.points.forEach((p, i) => (this.docIndex[p.doc_id] = i));
        this._computeScale();
        this.draw();
        this.renderClusters();
      } catch (e) {
        console.error(e);
        this.statusEl.textContent = "Failed to load map data.";
      }
    }

    clusterColor(cid) {
      return cid < 0 ? DIM : PALETTE[cid % PALETTE.length];
    }

    _computeScale() {
      if (!this.points.length) return;
      const xs = this.points.map((p) => p.x);
      const ys = this.points.map((p) => p.y);
      this.minX = Math.min(...xs);
      this.maxX = Math.max(...xs);
      this.minY = Math.min(...ys);
      this.maxY = Math.max(...ys);
    }

    _sx(x) {
      const span = this.maxX - this.minX || 1;
      return PAD + ((x - this.minX) / span) * (this.w - 2 * PAD);
    }
    _sy(y) {
      const span = this.maxY - this.minY || 1;
      // invert so larger y is up
      return this.h - PAD - ((y - this.minY) / span) * (this.h - 2 * PAD);
    }

    draw() {
      if (!this.ctx) return;
      const ctx = this.ctx;
      ctx.clearRect(0, 0, this.w, this.h);
      if (!this.points.length) return;
      const knn = new Set(this._knnIds);
      for (const p of this.points) {
        const dimmed = this.filterCluster !== null && p.cluster !== this.filterCluster;
        const cx = this._sx(p.x);
        const cy = this._sy(p.y);
        ctx.beginPath();
        ctx.arc(cx, cy, R, 0, Math.PI * 2);
        ctx.fillStyle = dimmed ? DIM : this.clusterColor(p.cluster);
        ctx.globalAlpha = dimmed ? 0.4 : 1;
        ctx.fill();
        ctx.globalAlpha = 1;
        // rings for current doc / KNN
        if (p.doc_id === this.currentDoc) {
          ctx.lineWidth = 3;
          ctx.strokeStyle = CURRENT_RING;
          ctx.stroke();
        } else if (knn.has(p.doc_id)) {
          ctx.lineWidth = 2.5;
          ctx.strokeStyle = KNN_RING;
          ctx.stroke();
        } else {
          ctx.lineWidth = 1;
          ctx.strokeStyle = "#ffffff";
          ctx.stroke();
        }
      }
    }

    _hit(e) {
      const rect = this.canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      let best = null;
      let bestD = (R + 4) * (R + 4);
      for (const p of this.points) {
        const dx = this._sx(p.x) - mx;
        const dy = this._sy(p.y) - my;
        const d = dx * dx + dy * dy;
        if (d <= bestD) {
          bestD = d;
          best = p;
        }
      }
      return best;
    }

    _onHover(e) {
      const p = this._hit(e);
      if (!p) {
        this.tooltip.style.display = "none";
        this.canvas.style.cursor = "default";
        return;
      }
      this.canvas.style.cursor = "pointer";
      const rect = this.canvas.getBoundingClientRect();
      this.tooltip.innerHTML = `<b>${p.doc_id}</b><br>${(p.snippet || "").slice(0, 120)}`;
      this.tooltip.style.display = "block";
      let tx = this._sx(p.x) + 12;
      let ty = this._sy(p.y) + 12;
      if (tx > this.w - 160) tx -= 180;
      this.tooltip.style.left = tx + "px";
      this.tooltip.style.top = ty + "px";
    }

    renderClusters() {
      this.clusterListEl.innerHTML = this.clusters
        .map(
          (c) => `
        <li class="cm-cluster-row${this.filterCluster === c.id ? " cm-active" : ""}"
            data-cid="${c.id}">
          <span class="cm-swatch" style="background:${this.clusterColor(c.id)}"></span>
          <span class="cm-cluster-label">${c.label || "cluster " + c.id}</span>
          <span class="cm-cluster-size">${c.size}</span>
        </li>`
        )
        .join("");
      this.clusterListEl.querySelectorAll(".cm-cluster-row").forEach((row) => {
        row.addEventListener("click", () => {
          const cid = parseInt(row.dataset.cid, 10);
          this.setClusterFilter(this.filterCluster === cid ? null : cid);
        });
      });
    }

    setClusterFilter(cid) {
      this.filterCluster = cid;
      el("clear-filter").style.display = cid === null ? "none" : "";
      this.draw();
      this.renderClusters();
    }

    async openDoc(docId) {
      if (!docId) return;
      this.currentDoc = docId;
      this.draw();
      try {
        await api("/corpus/api/goto", {
          method: "POST",
          body: JSON.stringify({ doc_id: docId }),
        });
        try {
          this.frame.contentWindow.location.reload();
        } catch (e) {
          this.frame.src = "/annotate";
        }
      } catch (e) {
        console.error(e);
      }
      this.loadKnn(docId);
    }

    async loadKnn(docId) {
      try {
        const data = await api(`/corpus/api/knn/${encodeURIComponent(docId)}`);
        const neighbors = data.neighbors || [];
        this._knnIds = neighbors.map((n) => n.doc_id);
        this.draw();
        this.knnEl.style.display = neighbors.length ? "" : "none";
        this.knnListEl.innerHTML = neighbors
          .map(
            (n) => `
          <li class="cm-knn-row" data-doc="${n.doc_id}">
            <span class="cm-knn-score">${n.score.toFixed(2)}</span>
            <span class="cm-knn-snippet">${(n.snippet || n.doc_id).slice(0, 70)}</span>
          </li>`
          )
          .join("");
        this.knnListEl.querySelectorAll(".cm-knn-row").forEach((row) => {
          row.addEventListener("click", () => this.openDoc(row.dataset.doc));
        });
      } catch (e) {
        console.error(e);
      }
    }

    async rebuild() {
      try {
        await api("/corpus/api/rebuild", { method: "POST" });
        this.statusEl.textContent = "Rebuilding…";
        this.start();
      } catch (e) {
        console.error(e);
        this.statusEl.textContent = "Rebuild failed (admin only).";
      }
    }
  }

  function boot() {
    window.corpusMap = new CorpusMap();
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();

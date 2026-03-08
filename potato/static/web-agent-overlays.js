/**
 * Web Agent Overlay Manager
 *
 * Renders SVG overlays on web agent screenshots:
 * - Click markers (red circle + crosshair)
 * - Bounding boxes (blue dashed rectangle)
 * - Mouse paths (orange curved line)
 * - Scroll indicators (green arrow)
 * - Type indicators (yellow highlight on target)
 */

class WebAgentOverlayManager {
    constructor(container) {
        this.container = container;
        this.svg = container.querySelector('.overlay-layer');
        this.img = container.querySelector('.step-screenshot');
        this.visibility = {
            click: true,
            bbox: true,
            path: true,
            scroll: true,
        };
    }

    /**
     * Clear all overlays and render for a new step.
     */
    renderStep(stepData) {
        if (!this.svg) return;
        this.svg.innerHTML = '';

        if (!stepData) return;

        const actionType = stepData.action_type || '';
        const coords = stepData.coordinates || {};
        const element = stepData.element || {};
        const bbox = element.bbox || null;
        const mousePath = stepData.mouse_path || [];
        const scrollDir = stepData.scroll_direction || stepData.direction || '';
        const viewport = stepData.viewport || { width: 1280, height: 720 };

        // Update SVG viewBox to match viewport
        this.svg.setAttribute('viewBox', `0 0 ${viewport.width} ${viewport.height}`);

        // Render overlays based on action type and available data
        if (mousePath.length > 1) {
            this.renderMousePath(mousePath);
        }

        if (bbox) {
            this.renderBoundingBox(bbox);
        }

        if (actionType === 'click' && coords.x !== undefined) {
            this.renderClickMarker(coords);
        } else if (actionType === 'type' && bbox) {
            this.renderTypeIndicator(bbox, stepData.typed_text || stepData.value || '');
        } else if (actionType === 'scroll') {
            this.renderScrollIndicator(coords, scrollDir, viewport);
        } else if (actionType === 'hover' && coords.x !== undefined) {
            this.renderHoverMarker(coords);
        }

        // Apply current visibility settings
        this._applyVisibility();
    }

    /**
     * Red circle + crosshair at click point.
     */
    renderClickMarker(coords) {
        const x = coords.x;
        const y = coords.y;
        const group = this._createGroup('overlay-click-marker');

        // Crosshair lines
        const hLine = this._createSVGElement('line', {
            x1: x - 16, y1: y, x2: x + 16, y2: y,
            stroke: '#FF1744', 'stroke-width': 1.5, opacity: 0.7,
        });
        const vLine = this._createSVGElement('line', {
            x1: x, y1: y - 16, x2: x, y2: y + 16,
            stroke: '#FF1744', 'stroke-width': 1.5, opacity: 0.7,
        });

        // Outer ring
        const outerCircle = this._createSVGElement('circle', {
            cx: x, cy: y, r: 12,
            fill: 'none', stroke: '#FF1744', 'stroke-width': 2, opacity: 0.6,
        });

        // Inner filled circle
        const innerCircle = this._createSVGElement('circle', {
            cx: x, cy: y, r: 5,
            fill: '#FF1744', opacity: 0.8,
        });

        // Pulse animation
        const animCircle = this._createSVGElement('circle', {
            cx: x, cy: y, r: 8,
            fill: 'none', stroke: '#FF1744', 'stroke-width': 2, opacity: 0.5,
        });
        const animate = this._createSVGElement('animate', {
            attributeName: 'r', values: '8;14;8',
            dur: '1.5s', repeatCount: 'indefinite',
        });
        animCircle.appendChild(animate);
        const animateOpacity = this._createSVGElement('animate', {
            attributeName: 'opacity', values: '0.5;0.1;0.5',
            dur: '1.5s', repeatCount: 'indefinite',
        });
        animCircle.appendChild(animateOpacity);

        group.appendChild(hLine);
        group.appendChild(vLine);
        group.appendChild(outerCircle);
        group.appendChild(animCircle);
        group.appendChild(innerCircle);
        this.svg.appendChild(group);
    }

    /**
     * Blue dashed rectangle around target element.
     */
    renderBoundingBox(bbox) {
        // bbox format: [x1, y1, x2, y2]
        if (!bbox || bbox.length < 4) return;

        const [x1, y1, x2, y2] = bbox;
        const w = x2 - x1;
        const h = y2 - y1;
        const group = this._createGroup('overlay-bbox');

        // Dashed rectangle
        const rect = this._createSVGElement('rect', {
            x: x1, y: y1, width: w, height: h,
            fill: 'rgba(33,150,243,0.1)', stroke: '#2196F3',
            'stroke-width': 2, 'stroke-dasharray': '6,3',
            rx: 3, ry: 3,
        });

        // Corner markers
        const cornerSize = 6;
        const corners = [
            [x1, y1], [x2, y1], [x1, y2], [x2, y2],
        ];
        corners.forEach(([cx, cy]) => {
            const corner = this._createSVGElement('rect', {
                x: cx - cornerSize / 2, y: cy - cornerSize / 2,
                width: cornerSize, height: cornerSize,
                fill: '#2196F3', stroke: 'none',
            });
            group.appendChild(corner);
        });

        group.appendChild(rect);
        this.svg.appendChild(group);
    }

    /**
     * Orange curved line showing mouse trajectory.
     */
    renderMousePath(points) {
        if (!points || points.length < 2) return;
        const group = this._createGroup('overlay-mouse-path');

        // Build smooth path using cubic bezier
        let d = `M ${points[0][0]} ${points[0][1]}`;
        if (points.length === 2) {
            d += ` L ${points[1][0]} ${points[1][1]}`;
        } else {
            for (let i = 1; i < points.length; i++) {
                const prev = points[i - 1];
                const curr = points[i];
                const cpx = (prev[0] + curr[0]) / 2;
                const cpy = (prev[1] + curr[1]) / 2;
                d += ` Q ${prev[0]} ${prev[1]} ${cpx} ${cpy}`;
            }
            const last = points[points.length - 1];
            d += ` L ${last[0]} ${last[1]}`;
        }

        // Path line
        const path = this._createSVGElement('path', {
            d: d,
            fill: 'none', stroke: '#FF9800', 'stroke-width': 2.5,
            'stroke-linecap': 'round', 'stroke-linejoin': 'round',
            opacity: 0.7,
        });

        // Animated dash
        const animPath = this._createSVGElement('path', {
            d: d,
            fill: 'none', stroke: '#FFE0B2', 'stroke-width': 2,
            'stroke-dasharray': '8,12', 'stroke-linecap': 'round',
            opacity: 0.8,
        });
        const dashAnim = this._createSVGElement('animate', {
            attributeName: 'stroke-dashoffset', values: '0;-20',
            dur: '1s', repeatCount: 'indefinite',
        });
        animPath.appendChild(dashAnim);

        // Start dot
        const startDot = this._createSVGElement('circle', {
            cx: points[0][0], cy: points[0][1], r: 4,
            fill: '#FF9800', opacity: 0.8,
        });

        // End arrowhead
        const last = points[points.length - 1];
        const prev = points[points.length - 2];
        const angle = Math.atan2(last[1] - prev[1], last[0] - prev[0]);
        const arrowLen = 10;
        const arrowWidth = 6;
        const ax1 = last[0] - arrowLen * Math.cos(angle - 0.4);
        const ay1 = last[1] - arrowLen * Math.sin(angle - 0.4);
        const ax2 = last[0] - arrowLen * Math.cos(angle + 0.4);
        const ay2 = last[1] - arrowLen * Math.sin(angle + 0.4);
        const arrow = this._createSVGElement('polygon', {
            points: `${last[0]},${last[1]} ${ax1},${ay1} ${ax2},${ay2}`,
            fill: '#FF9800', opacity: 0.8,
        });

        group.appendChild(path);
        group.appendChild(animPath);
        group.appendChild(startDot);
        group.appendChild(arrow);
        this.svg.appendChild(group);
    }

    /**
     * Green arrow for scroll direction.
     */
    renderScrollIndicator(coords, direction, viewport) {
        const group = this._createGroup('overlay-scroll');
        const cx = coords && coords.x != null ? coords.x : viewport.width / 2;
        const cy = coords && coords.y != null ? coords.y : viewport.height / 2;

        let dy = 0, dx = 0;
        const arrowLen = 60;
        switch ((direction || 'down').toLowerCase()) {
            case 'up': dy = -arrowLen; break;
            case 'down': dy = arrowLen; break;
            case 'left': dx = -arrowLen; break;
            case 'right': dx = arrowLen; break;
        }

        // Arrow line
        const line = this._createSVGElement('line', {
            x1: cx, y1: cy, x2: cx + dx, y2: cy + dy,
            stroke: '#4CAF50', 'stroke-width': 3, opacity: 0.7,
            'stroke-linecap': 'round',
        });

        // Arrowhead
        const angle = Math.atan2(dy, dx);
        const headLen = 12;
        const hx1 = cx + dx - headLen * Math.cos(angle - 0.5);
        const hy1 = cy + dy - headLen * Math.sin(angle - 0.5);
        const hx2 = cx + dx - headLen * Math.cos(angle + 0.5);
        const hy2 = cy + dy - headLen * Math.sin(angle + 0.5);
        const head = this._createSVGElement('polygon', {
            points: `${cx + dx},${cy + dy} ${hx1},${hy1} ${hx2},${hy2}`,
            fill: '#4CAF50', opacity: 0.7,
        });

        // Label
        const label = this._createSVGElement('text', {
            x: cx + dx / 2, y: cy + dy / 2 - 10,
            'text-anchor': 'middle', 'font-size': '14',
            fill: '#2E7D32', 'font-weight': 'bold',
        });
        label.textContent = `SCROLL ${(direction || 'down').toUpperCase()}`;

        group.appendChild(line);
        group.appendChild(head);
        group.appendChild(label);
        this.svg.appendChild(group);
    }

    /**
     * Yellow highlight on type target element.
     */
    renderTypeIndicator(bbox, text) {
        if (!bbox || bbox.length < 4) return;
        const [x1, y1, x2, y2] = bbox;
        const group = this._createGroup('overlay-bbox');

        // Highlight rectangle
        const rect = this._createSVGElement('rect', {
            x: x1, y: y1, width: x2 - x1, height: y2 - y1,
            fill: 'rgba(255,235,59,0.3)', stroke: '#FFC107',
            'stroke-width': 2, rx: 2, ry: 2,
        });

        group.appendChild(rect);

        // Text label above
        if (text) {
            const label = this._createSVGElement('text', {
                x: x1, y: y1 - 5,
                'font-size': '12', fill: '#F57F17',
                'font-family': 'monospace',
            });
            label.textContent = text.length > 30 ? text.substring(0, 30) + '...' : text;
            group.appendChild(label);
        }

        this.svg.appendChild(group);
    }

    /**
     * Light purple circle for hover actions.
     */
    renderHoverMarker(coords) {
        const group = this._createGroup('overlay-click-marker');
        const circle = this._createSVGElement('circle', {
            cx: coords.x, cy: coords.y, r: 10,
            fill: 'rgba(156,39,176,0.2)', stroke: '#9C27B0',
            'stroke-width': 2,
        });
        group.appendChild(circle);
        this.svg.appendChild(group);
    }

    /**
     * Toggle overlay type visibility.
     */
    toggleOverlay(type, visible) {
        this.visibility[type] = visible;
        this._applyVisibility();
    }

    /**
     * Show or hide all overlays.
     */
    setAllVisible(visible) {
        Object.keys(this.visibility).forEach(k => {
            this.visibility[k] = visible;
        });
        this._applyVisibility();
    }

    // --- Private helpers ---

    _applyVisibility() {
        if (!this.svg) return;
        const mapping = {
            'click': 'overlay-click-marker',
            'bbox': 'overlay-bbox',
            'path': 'overlay-mouse-path',
            'scroll': 'overlay-scroll',
        };
        Object.entries(mapping).forEach(([type, className]) => {
            const els = this.svg.querySelectorAll(`.${className}`);
            els.forEach(el => {
                el.style.display = this.visibility[type] ? '' : 'none';
            });
        });
    }

    _createGroup(className) {
        const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        g.setAttribute('class', className);
        return g;
    }

    _createSVGElement(tag, attrs) {
        const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
        Object.entries(attrs).forEach(([k, v]) => {
            el.setAttribute(k, String(v));
        });
        return el;
    }
}

// Export for global use
window.WebAgentOverlayManager = WebAgentOverlayManager;

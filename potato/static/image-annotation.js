/**
 * Image Annotation Manager
 *
 * Provides canvas-based image annotation capabilities using Fabric.js.
 * Supports bounding boxes, polygons, freeform drawing, and landmark points.
 */

class ImageAnnotationManager {
    /**
     * Create an ImageAnnotationManager.
     * @param {string} canvasId - ID of the canvas element
     * @param {string} inputId - ID of the hidden input for storing annotation data
     * @param {Object} config - Configuration object
     */
    constructor(canvasId, inputId, config) {
        this.canvasId = canvasId;
        this.inputId = inputId;
        this.config = config;

        this.canvas = null;
        this.image = null;
        this.currentTool = null;
        this.currentLabel = null;
        this.currentColor = '#FF6B6B';

        // Drawing state
        this.isDrawing = false;
        this.drawingObject = null;
        this.polygonPoints = [];
        this.isPanning = false;
        this.lastPosX = 0;
        this.lastPosY = 0;

        // History for undo/redo
        this.history = [];
        this.historyIndex = -1;
        this.maxHistory = 50;

        // Annotations storage
        this.annotations = [];

        // Callback for annotation count changes
        this.onAnnotationChange = null;

        // Initialize canvas
        this._initCanvas();
        this._setupEventListeners();
        this._setupKeyboardShortcuts();
    }

    /**
     * Initialize the Fabric.js canvas.
     */
    _initCanvas() {
        const canvasEl = document.getElementById(this.canvasId);
        if (!canvasEl) {
            console.error('Canvas element not found:', this.canvasId);
            return;
        }

        // Get parent container dimensions
        const container = canvasEl.parentElement;
        const width = container.clientWidth || 800;
        const height = 600;

        this.canvas = new fabric.Canvas(this.canvasId, {
            width: width,
            height: height,
            selection: true,
            preserveObjectStacking: true,
        });

        // Set initial viewport
        this.canvas.setViewportTransform([1, 0, 0, 1, 0, 0]);
    }

    /**
     * Set up canvas event listeners for drawing.
     */
    _setupEventListeners() {
        if (!this.canvas) return;

        // Mouse down - start drawing
        this.canvas.on('mouse:down', (opt) => {
            const evt = opt.e;
            const pointer = this.canvas.getPointer(evt);

            // Handle pan with space key
            if (evt.altKey || this._spaceKeyDown) {
                this.isPanning = true;
                this.canvas.selection = false;
                this.lastPosX = evt.clientX;
                this.lastPosY = evt.clientY;
                return;
            }

            // If clicking on existing object, don't start new drawing
            if (opt.target && opt.target !== this.image) {
                return;
            }

            this._startDrawing(pointer);
        });

        // Mouse move - continue drawing or pan
        this.canvas.on('mouse:move', (opt) => {
            const evt = opt.e;

            if (this.isPanning) {
                const vpt = this.canvas.viewportTransform;
                vpt[4] += evt.clientX - this.lastPosX;
                vpt[5] += evt.clientY - this.lastPosY;
                this.canvas.requestRenderAll();
                this.lastPosX = evt.clientX;
                this.lastPosY = evt.clientY;
                return;
            }

            if (this.isDrawing) {
                const pointer = this.canvas.getPointer(evt);
                this._continueDrawing(pointer);
            }
        });

        // Mouse up - finish drawing
        this.canvas.on('mouse:up', (opt) => {
            if (this.isPanning) {
                this.isPanning = false;
                this.canvas.selection = true;
                return;
            }

            if (this.isDrawing) {
                this._finishDrawing();
            }
        });

        // Double click - complete polygon
        this.canvas.on('mouse:dblclick', (opt) => {
            if (this.currentTool === 'polygon' && this.polygonPoints.length > 2) {
                this._completePolygon();
            }
        });

        // Object modified - save state
        this.canvas.on('object:modified', () => {
            this._saveState();
            this._updateAnnotationData();
        });

        // Object removed
        this.canvas.on('object:removed', (opt) => {
            if (opt.target && opt.target.annotationData) {
                this._updateAnnotationData();
            }
        });

        // Selection events
        this.canvas.on('selection:created', () => {
            this._updateDeleteButtonState();
        });

        this.canvas.on('selection:cleared', () => {
            this._updateDeleteButtonState();
        });
    }

    /**
     * Set up keyboard shortcuts.
     */
    _setupKeyboardShortcuts() {
        this._spaceKeyDown = false;

        document.addEventListener('keydown', (e) => {
            // Only handle if canvas container is focused or visible
            const container = document.querySelector(`.image-annotation-container[data-schema="${this.config.schemaName}"]`);
            if (!container || !this._isElementVisible(container)) return;

            // Space for pan
            if (e.code === 'Space' && !this._spaceKeyDown) {
                this._spaceKeyDown = true;
                this.canvas.defaultCursor = 'grab';
                e.preventDefault();
            }

            // Tool shortcuts
            if (!e.ctrlKey && !e.metaKey) {
                switch (e.key.toLowerCase()) {
                    case 'b':
                        if (this.config.tools.includes('bbox')) {
                            this._selectTool('bbox');
                        }
                        break;
                    case 'p':
                        if (this.config.tools.includes('polygon')) {
                            this._selectTool('polygon');
                        }
                        break;
                    case 'f':
                        if (this.config.tools.includes('freeform')) {
                            this._selectTool('freeform');
                        }
                        break;
                    case 'l':
                        if (this.config.tools.includes('landmark')) {
                            this._selectTool('landmark');
                        }
                        break;
                    case 'delete':
                    case 'backspace':
                        this.deleteSelected();
                        e.preventDefault();
                        break;
                    case '+':
                    case '=':
                        this.zoom(1.2);
                        e.preventDefault();
                        break;
                    case '-':
                        this.zoom(0.8);
                        e.preventDefault();
                        break;
                    case '0':
                        this.zoomFit();
                        e.preventDefault();
                        break;
                }

                // Label shortcuts
                for (const label of this.config.labels) {
                    if (label.key_value && e.key === label.key_value) {
                        this.setLabel(label.name, label.color);
                        this._updateLabelButtonState(label.name);
                    }
                }
            }

            // Undo/Redo
            if ((e.ctrlKey || e.metaKey) && e.key === 'z') {
                if (e.shiftKey) {
                    this.redo();
                } else {
                    this.undo();
                }
                e.preventDefault();
            }
        });

        document.addEventListener('keyup', (e) => {
            if (e.code === 'Space') {
                this._spaceKeyDown = false;
                this.canvas.defaultCursor = 'default';
            }
        });
    }

    /**
     * Check if element is visible.
     */
    _isElementVisible(el) {
        return el.offsetParent !== null;
    }

    /**
     * Select a tool programmatically.
     */
    _selectTool(tool) {
        this.setTool(tool);
        const container = document.querySelector(`.image-annotation-container[data-schema="${this.config.schemaName}"]`);
        if (container) {
            container.querySelectorAll('.tool-btn').forEach(btn => {
                btn.classList.remove('active');
                if (btn.dataset.tool === tool) {
                    btn.classList.add('active');
                }
            });
        }
    }

    /**
     * Update label button state.
     */
    _updateLabelButtonState(labelName) {
        const container = document.querySelector(`.image-annotation-container[data-schema="${this.config.schemaName}"]`);
        if (container) {
            container.querySelectorAll('.label-btn').forEach(btn => {
                btn.classList.remove('active');
                if (btn.dataset.label === labelName) {
                    btn.classList.add('active');
                }
            });
        }
    }

    /**
     * Update delete button enabled state.
     */
    _updateDeleteButtonState() {
        const container = document.querySelector(`.image-annotation-container[data-schema="${this.config.schemaName}"]`);
        if (container) {
            const deleteBtn = container.querySelector('.delete-btn');
            if (deleteBtn) {
                const hasSelection = this.canvas.getActiveObject() !== null;
                deleteBtn.disabled = !hasSelection;
            }
        }
    }

    /**
     * Load an image onto the canvas.
     * @param {string} imageUrl - URL of the image to load
     */
    loadImage(imageUrl) {
        if (!this.canvas) return;

        console.log('Loading image:', imageUrl);
        fabric.Image.fromURL(imageUrl, (img) => {
            if (!img) {
                console.error('Failed to load image:', imageUrl);
                return;
            }
            console.log('Image loaded successfully:', img.width, 'x', img.height);

            this.image = img;

            // Scale image to fit canvas while maintaining aspect ratio
            const canvasWidth = this.canvas.getWidth();
            const canvasHeight = this.canvas.getHeight();
            const scale = Math.min(
                canvasWidth / img.width,
                canvasHeight / img.height,
                1  // Don't scale up
            );

            img.set({
                scaleX: scale,
                scaleY: scale,
                left: (canvasWidth - img.width * scale) / 2,
                top: (canvasHeight - img.height * scale) / 2,
                selectable: false,
                evented: false,
                hoverCursor: 'default',
            });

            // Store original dimensions for coordinate normalization
            this.imageOriginalWidth = img.width;
            this.imageOriginalHeight = img.height;
            this.imageScale = scale;
            this.imageLeft = img.left;
            this.imageTop = img.top;

            this.canvas.add(img);
            this.canvas.sendToBack(img);
            this.canvas.renderAll();

            // Load any existing annotations
            this._loadExistingAnnotations();
        }, { crossOrigin: 'anonymous' });
    }

    /**
     * Set the current drawing tool.
     * @param {string} tool - Tool name (bbox, polygon, freeform, landmark)
     */
    setTool(tool) {
        this.currentTool = tool;
        this.isDrawing = false;
        this.drawingObject = null;
        this.polygonPoints = [];

        // Update canvas mode
        if (tool === 'freeform') {
            this.canvas.isDrawingMode = true;
            this.canvas.freeDrawingBrush.color = this.currentColor;
            this.canvas.freeDrawingBrush.width = this.config.freeformBrushSize || 5;
        } else {
            this.canvas.isDrawingMode = false;
        }

        // Update cursor
        switch (tool) {
            case 'bbox':
                this.canvas.defaultCursor = 'crosshair';
                break;
            case 'polygon':
                this.canvas.defaultCursor = 'crosshair';
                break;
            case 'landmark':
                this.canvas.defaultCursor = 'crosshair';
                break;
            default:
                this.canvas.defaultCursor = 'default';
        }
    }

    /**
     * Set the current label and color.
     * @param {string} label - Label name
     * @param {string} color - Color hex code
     */
    setLabel(label, color) {
        this.currentLabel = label;
        this.currentColor = color || '#FF6B6B';

        if (this.canvas.isDrawingMode) {
            this.canvas.freeDrawingBrush.color = this.currentColor;
        }
    }

    /**
     * Start drawing based on current tool.
     */
    _startDrawing(pointer) {
        if (!this.currentTool || !this.currentLabel) return;

        switch (this.currentTool) {
            case 'bbox':
                this._startBbox(pointer);
                break;
            case 'polygon':
                this._addPolygonPoint(pointer);
                break;
            case 'landmark':
                this._addLandmark(pointer);
                break;
            // Freeform handled by Fabric's drawing mode
        }
    }

    /**
     * Continue drawing based on current tool.
     */
    _continueDrawing(pointer) {
        switch (this.currentTool) {
            case 'bbox':
                this._updateBbox(pointer);
                break;
        }
    }

    /**
     * Finish drawing based on current tool.
     */
    _finishDrawing() {
        switch (this.currentTool) {
            case 'bbox':
                this._finishBbox();
                break;
        }
    }

    /**
     * Start drawing a bounding box.
     */
    _startBbox(pointer) {
        this.isDrawing = true;
        this.startX = pointer.x;
        this.startY = pointer.y;

        this.drawingObject = new fabric.Rect({
            left: pointer.x,
            top: pointer.y,
            width: 0,
            height: 0,
            fill: this._colorWithAlpha(this.currentColor, 0.2),
            stroke: this.currentColor,
            strokeWidth: 2,
            selectable: true,
            hasControls: true,
            hasBorders: true,
        });

        this.canvas.add(this.drawingObject);
    }

    /**
     * Update bounding box while drawing.
     */
    _updateBbox(pointer) {
        if (!this.drawingObject) return;

        const left = Math.min(this.startX, pointer.x);
        const top = Math.min(this.startY, pointer.y);
        const width = Math.abs(pointer.x - this.startX);
        const height = Math.abs(pointer.y - this.startY);

        this.drawingObject.set({
            left: left,
            top: top,
            width: width,
            height: height,
        });

        this.canvas.renderAll();
    }

    /**
     * Finish drawing bounding box.
     */
    _finishBbox() {
        if (!this.drawingObject) return;

        this.isDrawing = false;

        // Only keep if it has reasonable size
        if (this.drawingObject.width > 5 && this.drawingObject.height > 5) {
            this.drawingObject.annotationData = {
                type: 'bbox',
                label: this.currentLabel,
                color: this.currentColor,
            };
            this._saveState();
            this._updateAnnotationData();
        } else {
            this.canvas.remove(this.drawingObject);
        }

        this.drawingObject = null;
    }

    /**
     * Add a point to the current polygon.
     */
    _addPolygonPoint(pointer) {
        this.polygonPoints.push({ x: pointer.x, y: pointer.y });

        // Draw point marker
        const point = new fabric.Circle({
            left: pointer.x - 4,
            top: pointer.y - 4,
            radius: 4,
            fill: this.currentColor,
            stroke: '#fff',
            strokeWidth: 1,
            selectable: false,
            evented: false,
            polygonMarker: true,
        });
        this.canvas.add(point);

        // Draw line to previous point
        if (this.polygonPoints.length > 1) {
            const prev = this.polygonPoints[this.polygonPoints.length - 2];
            const line = new fabric.Line(
                [prev.x, prev.y, pointer.x, pointer.y],
                {
                    stroke: this.currentColor,
                    strokeWidth: 2,
                    selectable: false,
                    evented: false,
                    polygonLine: true,
                }
            );
            this.canvas.add(line);
        }

        this.canvas.renderAll();
    }

    /**
     * Complete the polygon shape.
     */
    _completePolygon() {
        if (this.polygonPoints.length < 3) return;

        // Remove temporary markers and lines
        const toRemove = this.canvas.getObjects().filter(
            obj => obj.polygonMarker || obj.polygonLine
        );
        toRemove.forEach(obj => this.canvas.remove(obj));

        // Create polygon
        const polygon = new fabric.Polygon(this.polygonPoints, {
            fill: this._colorWithAlpha(this.currentColor, 0.2),
            stroke: this.currentColor,
            strokeWidth: 2,
            selectable: true,
            hasControls: true,
            hasBorders: true,
        });

        polygon.annotationData = {
            type: 'polygon',
            label: this.currentLabel,
            color: this.currentColor,
        };

        this.canvas.add(polygon);
        this.polygonPoints = [];
        this._saveState();
        this._updateAnnotationData();
    }

    /**
     * Add a landmark point.
     */
    _addLandmark(pointer) {
        const landmark = new fabric.Circle({
            left: pointer.x - 8,
            top: pointer.y - 8,
            radius: 8,
            fill: this.currentColor,
            stroke: '#fff',
            strokeWidth: 2,
            selectable: true,
            hasControls: false,
            hasBorders: true,
            originX: 'center',
            originY: 'center',
        });

        landmark.annotationData = {
            type: 'landmark',
            label: this.currentLabel,
            color: this.currentColor,
        };

        // Add label text
        const text = new fabric.Text(this.currentLabel, {
            left: pointer.x + 12,
            top: pointer.y - 6,
            fontSize: 12,
            fill: this.currentColor,
            selectable: false,
            evented: false,
        });

        // Group landmark and label
        const group = new fabric.Group([landmark, text], {
            left: pointer.x - 8,
            top: pointer.y - 8,
            selectable: true,
            hasControls: false,
        });

        group.annotationData = landmark.annotationData;

        this.canvas.add(group);
        this._saveState();
        this._updateAnnotationData();
    }

    /**
     * Handle freeform path completion.
     */
    _handleFreeformPath() {
        const path = this.canvas.getObjects().find(
            obj => obj.type === 'path' && !obj.annotationData
        );

        if (path) {
            path.annotationData = {
                type: 'freeform',
                label: this.currentLabel,
                color: this.currentColor,
            };

            path.set({
                stroke: this.currentColor,
                fill: this._colorWithAlpha(this.currentColor, 0.1),
            });

            this._saveState();
            this._updateAnnotationData();
        }
    }

    /**
     * Delete the currently selected annotation.
     */
    deleteSelected() {
        const active = this.canvas.getActiveObject();
        if (active && active !== this.image) {
            this.canvas.remove(active);
            this._saveState();
            this._updateAnnotationData();
        }
    }

    /**
     * Zoom the canvas.
     * @param {number} factor - Zoom factor (>1 to zoom in, <1 to zoom out)
     */
    zoom(factor) {
        if (!this.canvas) return;

        const center = this.canvas.getCenter();
        let zoom = this.canvas.getZoom() * factor;

        // Clamp zoom
        zoom = Math.max(0.1, Math.min(10, zoom));

        this.canvas.zoomToPoint(
            new fabric.Point(center.left, center.top),
            zoom
        );
    }

    /**
     * Zoom to fit the image.
     */
    zoomFit() {
        if (!this.canvas || !this.image) return;

        const canvasWidth = this.canvas.getWidth();
        const canvasHeight = this.canvas.getHeight();

        const scale = Math.min(
            canvasWidth / (this.image.width * this.image.scaleX),
            canvasHeight / (this.image.height * this.image.scaleY),
            1
        );

        this.canvas.setViewportTransform([1, 0, 0, 1, 0, 0]);
        this.canvas.zoomToPoint(
            new fabric.Point(canvasWidth / 2, canvasHeight / 2),
            scale
        );
    }

    /**
     * Reset zoom to 100%.
     */
    zoomReset() {
        if (!this.canvas) return;
        this.canvas.setViewportTransform([1, 0, 0, 1, 0, 0]);
    }

    /**
     * Undo the last action.
     */
    undo() {
        if (this.historyIndex > 0) {
            this.historyIndex--;
            this._restoreState(this.history[this.historyIndex]);
        }
    }

    /**
     * Redo the last undone action.
     */
    redo() {
        if (this.historyIndex < this.history.length - 1) {
            this.historyIndex++;
            this._restoreState(this.history[this.historyIndex]);
        }
    }

    /**
     * Save current state to history.
     */
    _saveState() {
        // Remove future history if we're not at the end
        this.history = this.history.slice(0, this.historyIndex + 1);

        // Save current state
        const state = this._serializeAnnotations();
        this.history.push(state);

        // Trim history if too long
        if (this.history.length > this.maxHistory) {
            this.history.shift();
        }

        this.historyIndex = this.history.length - 1;
    }

    /**
     * Restore a saved state.
     */
    _restoreState(state) {
        // Remove all annotation objects (keep image)
        const toRemove = this.canvas.getObjects().filter(
            obj => obj !== this.image && obj.annotationData
        );
        toRemove.forEach(obj => this.canvas.remove(obj));

        // Restore annotations
        this._deserializeAnnotations(state);
        this._updateAnnotationData();
    }

    /**
     * Serialize all annotations to JSON.
     */
    _serializeAnnotations() {
        const annotations = [];

        this.canvas.getObjects().forEach(obj => {
            if (obj.annotationData) {
                const ann = {
                    type: obj.annotationData.type,
                    label: obj.annotationData.label,
                    color: obj.annotationData.color,
                    coordinates: this._getObjectCoordinates(obj),
                };
                annotations.push(ann);
            }
        });

        return JSON.stringify(annotations);
    }

    /**
     * Deserialize annotations from JSON and add to canvas.
     */
    _deserializeAnnotations(json) {
        const annotations = JSON.parse(json);

        annotations.forEach(ann => {
            this._createAnnotationObject(ann);
        });

        this.canvas.renderAll();
    }

    /**
     * Get normalized coordinates for an object.
     */
    _getObjectCoordinates(obj) {
        if (!this.image) return null;

        const imgWidth = this.image.width * this.image.scaleX;
        const imgHeight = this.image.height * this.image.scaleY;
        const imgLeft = this.image.left;
        const imgTop = this.image.top;

        const normalize = (x, y) => ({
            x: (x - imgLeft) / imgWidth,
            y: (y - imgTop) / imgHeight,
        });

        switch (obj.annotationData.type) {
            case 'bbox':
                const tl = normalize(obj.left, obj.top);
                return {
                    x: tl.x,
                    y: tl.y,
                    width: (obj.width * obj.scaleX) / imgWidth,
                    height: (obj.height * obj.scaleY) / imgHeight,
                };

            case 'polygon':
                return obj.points.map(p => {
                    const absX = obj.left + p.x - obj.pathOffset.x;
                    const absY = obj.top + p.y - obj.pathOffset.y;
                    return normalize(absX, absY);
                });

            case 'landmark':
                if (obj.type === 'group') {
                    const centerX = obj.left + obj.width / 2;
                    const centerY = obj.top + obj.height / 2;
                    return normalize(centerX, centerY);
                }
                return normalize(obj.left + 8, obj.top + 8);

            case 'freeform':
                // Serialize path data
                return {
                    path: obj.path,
                    left: (obj.left - imgLeft) / imgWidth,
                    top: (obj.top - imgTop) / imgHeight,
                    scaleX: obj.scaleX / (imgWidth / this.image.width),
                    scaleY: obj.scaleY / (imgHeight / this.image.height),
                };

            default:
                return null;
        }
    }

    /**
     * Create annotation object from serialized data.
     */
    _createAnnotationObject(ann) {
        if (!this.image) return;

        const imgWidth = this.image.width * this.image.scaleX;
        const imgHeight = this.image.height * this.image.scaleY;
        const imgLeft = this.image.left;
        const imgTop = this.image.top;

        const denormalize = (nx, ny) => ({
            x: nx * imgWidth + imgLeft,
            y: ny * imgHeight + imgTop,
        });

        let obj;

        switch (ann.type) {
            case 'bbox':
                const pos = denormalize(ann.coordinates.x, ann.coordinates.y);
                obj = new fabric.Rect({
                    left: pos.x,
                    top: pos.y,
                    width: ann.coordinates.width * imgWidth,
                    height: ann.coordinates.height * imgHeight,
                    fill: this._colorWithAlpha(ann.color, 0.2),
                    stroke: ann.color,
                    strokeWidth: 2,
                    selectable: true,
                    hasControls: true,
                });
                break;

            case 'polygon':
                const points = ann.coordinates.map(c => {
                    const p = denormalize(c.x, c.y);
                    return { x: p.x, y: p.y };
                });
                obj = new fabric.Polygon(points, {
                    fill: this._colorWithAlpha(ann.color, 0.2),
                    stroke: ann.color,
                    strokeWidth: 2,
                    selectable: true,
                    hasControls: true,
                });
                break;

            case 'landmark':
                const lpos = denormalize(ann.coordinates.x, ann.coordinates.y);
                const circle = new fabric.Circle({
                    left: 0,
                    top: 0,
                    radius: 8,
                    fill: ann.color,
                    stroke: '#fff',
                    strokeWidth: 2,
                    originX: 'center',
                    originY: 'center',
                });
                const text = new fabric.Text(ann.label, {
                    left: 12,
                    top: -6,
                    fontSize: 12,
                    fill: ann.color,
                });
                obj = new fabric.Group([circle, text], {
                    left: lpos.x - 8,
                    top: lpos.y - 8,
                    selectable: true,
                    hasControls: false,
                });
                break;

            case 'freeform':
                const coords = ann.coordinates;
                obj = new fabric.Path(coords.path, {
                    left: coords.left * imgWidth + imgLeft,
                    top: coords.top * imgHeight + imgTop,
                    scaleX: coords.scaleX * (imgWidth / this.image.width),
                    scaleY: coords.scaleY * (imgHeight / this.image.height),
                    stroke: ann.color,
                    fill: this._colorWithAlpha(ann.color, 0.1),
                    strokeWidth: 2,
                    selectable: true,
                });
                break;
        }

        if (obj) {
            obj.annotationData = {
                type: ann.type,
                label: ann.label,
                color: ann.color,
            };
            this.canvas.add(obj);
        }
    }

    /**
     * Update the hidden input with current annotation data.
     */
    _updateAnnotationData() {
        const input = document.getElementById(this.inputId);
        if (input) {
            input.value = this._serializeAnnotations();
        }

        // Update annotation count
        const count = this.canvas.getObjects().filter(
            obj => obj !== this.image && obj.annotationData
        ).length;

        if (this.onAnnotationChange) {
            this.onAnnotationChange(count);
        }
    }

    /**
     * Load existing annotations from the hidden input.
     */
    _loadExistingAnnotations() {
        const input = document.getElementById(this.inputId);
        if (input && input.value) {
            try {
                this._deserializeAnnotations(input.value);
                this._saveState();
            } catch (e) {
                console.warn('Failed to load existing annotations:', e);
            }
        }
    }

    /**
     * Convert hex color to rgba with alpha.
     */
    _colorWithAlpha(hex, alpha) {
        const r = parseInt(hex.slice(1, 3), 16);
        const g = parseInt(hex.slice(3, 5), 16);
        const b = parseInt(hex.slice(5, 7), 16);
        return `rgba(${r}, ${g}, ${b}, ${alpha})`;
    }

    /**
     * Get current annotation count.
     */
    getAnnotationCount() {
        return this.canvas.getObjects().filter(
            obj => obj !== this.image && obj.annotationData
        ).length;
    }

    /**
     * Serialize annotations for form submission.
     */
    serialize() {
        return this._serializeAnnotations();
    }

    /**
     * Load annotations from JSON.
     */
    deserialize(json) {
        this._deserializeAnnotations(json);
        this._saveState();
        this._updateAnnotationData();
    }
}

// Export for use in modules if needed
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ImageAnnotationManager;
}

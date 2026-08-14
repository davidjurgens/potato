/**
 * Image Annotation Manager
 *
 * Provides canvas-based image annotation capabilities using Fabric.js.
 * Supports bounding boxes, polygons, freeform drawing, and landmark points.
 */

/**
 * Segmentation masks are held in MaskBuffer, which ships as its own script
 * loaded immediately before this one (see base_template_v2.html) and as a
 * CommonJS module for the Jest suites.
 *
 * Resolved once, at load, so a missing dependency reports itself as a sentence
 * on page load rather than as a bare ReferenceError from inside a brush stroke
 * — which is what an annotator would hit, mid-gesture, halfway through a task.
 */
const MaskBuffer = (function () {
    const scope = (typeof globalThis !== 'undefined') ? globalThis
        : (typeof window !== 'undefined' ? window : null);
    if (scope && scope.MaskBuffer) return scope.MaskBuffer;
    throw new Error(
        'image-annotation.js requires mask-buffer.js, which must be loaded ' +
        'first. In a page, add its <script> above this one; in a test, ' +
        "require('potato/static/mask-buffer.js') before this module.");
})();

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

        // Segmentation mask state
        this.maskCanvas = null;
        this.maskCtx = null;
        this.masks = {};  // store key -> {label, color, data, instance?}
        // Which object of the current class a brush stroke extends. Only
        // meaningful in instance mask mode; null means "start a new one".
        this.activeInstance = null;
        this.brushSize = config.brushSize || 20;
        this.eraserSize = config.eraserSize || 20;
        this.maskOpacity = config.maskOpacity || 0.5;
        this.isMaskDrawing = false;
        // Stroke length in image pixels, accumulated across one brush stroke.
        this._strokePx = 0;
        this._strokeLastPoint = null;
        // Set while server-stored annotations are being restored, so hydration
        // is not reported as the annotator having drawn anything.
        this._hydrating = false;

        // Initialize canvas
        this._initCanvas();
        this._initMaskCanvas();
        this._setupEventListeners();
        this._setupKeyboardShortcuts();
        this._setupResizeHandling();
        this._maybeShowKeybindingNotice();
    }

    /**
     * Tell an existing annotator, once, that the tool shortcuts moved.
     *
     * Potato's tool keys changed to match V7 and CVAT so annotators arriving
     * from either are productive immediately. That is a breaking change for
     * anyone with trained muscle memory mid-study, so it is announced rather
     * than discovered, and it names the escape hatch. Projects already
     * collecting data set `keybinding_profile: legacy` and never see this.
     */
    _maybeShowKeybindingNotice() {
        if ((this.config.keybindingProfile || 'v7') !== 'v7') return;

        const flag = `potato.kbNotice.${this.config.schemaName}`;
        try {
            if (localStorage.getItem(flag)) return;
        } catch (e) {
            return;  // Private mode: skip rather than nag on every page.
        }

        const legacy = {bbox: 'b', polygon: 'p', freeform: 'f', landmark: 'l',
                        brush: 'm', fill: 'g', eraser: 'e'};
        const keys = this.config.toolKeys || {};
        const moved = (this.config.tools || [])
            .filter(t => legacy[t] && keys[t] && legacy[t] !== keys[t])
            .map(t => `${t}: ${legacy[t].toUpperCase()} → ${keys[t].toUpperCase()}`);
        if (!moved.length) return;

        const container = document.querySelector(
            `.image-annotation-container[data-schema="${this.config.schemaName}"]`);
        if (!container) return;

        // Built as DOM nodes rather than an innerHTML string. Nothing here is
        // attacker-controlled today (tool names are filtered against a
        // hardcoded map and the keys come from a server-side constant), but
        // this component sits next to instance text that IS user-supplied, and
        // the repo's convention is to never hand-assemble markup near it.
        const note = document.createElement('div');
        note.className = 'keybinding-notice';
        note.setAttribute('role', 'status');

        const lead = document.createElement('strong');
        lead.textContent = 'Shortcuts changed';
        note.appendChild(lead);
        note.appendChild(document.createTextNode(' (V7/CVAT): '));

        moved.forEach((m, i) => {
            if (i) note.appendChild(document.createTextNode(', '));
            const code = document.createElement('code');
            code.textContent = m;
            note.appendChild(code);
        });

        // Terse on purpose: the banner's height pushes the Next button down a
        // page that already overflows a laptop viewport.
        note.appendChild(document.createTextNode('. Admins can restore them with '));
        const opt = document.createElement('code');
        opt.textContent = 'keybinding_profile: legacy';
        note.appendChild(opt);
        note.appendChild(document.createTextNode(' '));

        const dismiss = document.createElement('button');
        dismiss.type = 'button';
        dismiss.className = 'keybinding-notice-dismiss';
        dismiss.textContent = 'Got it';
        dismiss.addEventListener('click', () => {
            try { localStorage.setItem(flag, '1'); } catch (e) { /* best effort */ }
            note.remove();
        });
        note.appendChild(dismiss);

        container.insertBefore(note, container.firstChild);
    }

    /**
     * Initialize the mask canvas for segmentation.
     */
    _initMaskCanvas() {
        const canvasEl = document.getElementById(this.canvasId);
        if (!canvasEl) return;

        const maskCanvasId = this.canvasId.replace('canvas-', 'mask-canvas-');
        this.maskCanvas = document.getElementById(maskCanvasId);

        if (!this.maskCanvas) {
            // Create mask canvas if it doesn't exist
            this.maskCanvas = document.createElement('canvas');
            this.maskCanvas.id = maskCanvasId;
            this.maskCanvas.className = 'mask-canvas';
            canvasEl.parentElement.appendChild(this.maskCanvas);
        }

        // Position mask canvas over the main canvas
        this.maskCanvas.style.position = 'absolute';
        this.maskCanvas.style.top = '0';
        this.maskCanvas.style.left = '0';
        this.maskCanvas.style.pointerEvents = 'none';  // Let events pass through to Fabric canvas

        this.maskCtx = this.maskCanvas.getContext('2d');
    }

    /**
     * Set up mask canvas event listeners.
     */
    _setupMaskEventListeners() {
        if (!this.maskCanvas) return;

        this.maskCanvas.addEventListener('mousedown', (e) => {
            if (this.currentTool === 'fill') {
                this._floodFill(e);
            } else if (this.currentTool === 'brush' || this.currentTool === 'eraser') {
                this._startMaskDraw(e);
            }
        });

        this.maskCanvas.addEventListener('mousemove', (e) => {
            this._continueMaskDraw(e);
        });

        this.maskCanvas.addEventListener('mouseup', () => {
            this._finishMaskDraw();
        });

        this.maskCanvas.addEventListener('mouseleave', () => {
            this._finishMaskDraw();
        });
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
            backgroundColor: '#f8f9fa',  // Light gray background
        });

        // Set initial viewport
        this.canvas.setViewportTransform([1, 0, 0, 1, 0, 0]);
    }

    /**
     * Set up canvas event listeners for drawing.
     */
    _setupEventListeners() {
        if (!this.canvas) return;

        // Set up mask canvas event listeners
        this._setupMaskEventListeners();

        // Scroll to zoom, anchored at the cursor.
        //
        // Zooming was reachable only through the +/- buttons and keys, so
        // working at magnification meant clicking repeatedly and then panning
        // to find the region again. V7 and CVAT both scroll-zoom, and
        // annotators arrive expecting it.
        //
        // Anchoring at the POINTER rather than the canvas centre is what makes
        // it usable: centre-anchored zoom pushes the thing you are looking at
        // off screen and forces a pan after every step.
        this.canvas.on('mouse:wheel', (opt) => {
            if (this.config.zoomEnabled === false) return;

            const evt = opt.e;
            evt.preventDefault();
            evt.stopPropagation();

            // deltaY is device- and OS-dependent; exponentiating a small factor
            // gives smooth, symmetric zoom for both trackpads and wheels.
            let zoom = this.canvas.getZoom() * Math.pow(0.999, evt.deltaY);
            zoom = Math.max(0.1, Math.min(10, zoom));

            this.canvas.zoomToPoint(
                new fabric.Point(evt.offsetX, evt.offsetY), zoom);

            // Masks paint to their own overlay canvas and do not move with the
            // fabric viewport on their own.
            this._renderAllMasks();
            this._telemetry('zoom', { value: Math.round(zoom * 100) });
        });

        // Freeform uses fabric's own free-drawing mode, which emits the finished
        // path through this event. Nothing was ever subscribed to it, so
        // _handleFreeformPath never ran: the stroke appeared on the canvas,
        // never got `annotationData`, and _serializeAnnotations (which filters
        // on that property) dropped it. The tool drew and saved nothing.
        this.canvas.on('path:created', (opt) => {
            this._handleFreeformPath(opt);
        });

        // Mouse down - start drawing
        this.canvas.on('mouse:down', (opt) => {
            const evt = opt.e;
            const pointer = this.canvas.getPointer(evt);
            // Kept so tool handlers can read modifiers; fabric's pointer
            // carries coordinates only, and shift-to-subtract needs the event.
            this._lastPointerEvent = evt;

            // Handle pan with space key
            if (evt.altKey || this._spaceKeyDown) {
                this.isPanning = true;
                this.canvas.selection = false;
                this.lastPosX = evt.clientX;
                this.lastPosY = evt.clientY;
                // One pan is the whole drag, not each mousemove: reporting per
                // move would put thousands of events in the stream and make
                // "pans" a measure of mouse polling rate.
                this._panStart = { x: evt.clientX, y: evt.clientY };
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
                // Re-render masks to follow pan
                this._renderAllMasks();
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
                if (this._panStart) {
                    const dx = this.lastPosX - this._panStart.x;
                    const dy = this.lastPosY - this._panStart.y;
                    const distance = Math.round(Math.sqrt(dx * dx + dy * dy));
                    // A pan of a couple of pixels is a click that wobbled.
                    if (distance > 2) this._telemetry('pan', { value: distance });
                    this._panStart = null;
                }
                return;
            }

            if (this.isDrawing) {
                this._finishDrawing();
            }
        });

        // Double click - complete polygon
        this.canvas.on('mouse:dblclick', (opt) => {
            // A polygon needs 3 points to enclose anything; a polyline is an
            // open path, so 2 is a complete answer.
            const minPoints = this.currentTool === 'polyline' ? 2 : 3;
            if ((this.currentTool === 'polygon' || this.currentTool === 'polyline')
                && this.polygonPoints.length >= minPoints) {
                this._completePolygon();
            }
            // A skeleton with no declared length, or one the annotator wants to
            // finish early (the rest of the joints are out of frame), commits
            // on double-click like a polygon.
            if (this.currentTool === 'keypoint_set'
                && (this.keypointPoints || []).length) {
                this._completeKeypointSet();
            }
        });

        // Object modified - save state
        this.canvas.on('object:modified', (opt) => {
            const data = opt && opt.target && opt.target.annotationData;
            if (data) this._telemetry('shape_edit', { shape: data.type });
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
            // Never steal keys from a text field. This handler is on `document`,
            // so without the guard an annotator writing a comment alongside the
            // image found their typing mangled: Space and Backspace were
            // swallowed by preventDefault (no spaces, no corrections), `h` hid
            // a whole class, `r`/`b`/`p` silently switched tools, and Delete
            // removed the selected annotation. Video, audio, and span
            // annotation already guard this way.
            if (this._isTypingTarget(e.target)) return;

            // Only handle if canvas container is focused or visible
            const container = document.querySelector(`.image-annotation-container[data-schema="${this.config.schemaName}"]`);
            if (!container || !this._isElementVisible(container)) return;

            // Space for pan
            if (e.code === 'Space' && !this._spaceKeyDown) {
                this._spaceKeyDown = true;
                this.canvas.defaultCursor = 'grab';
                e.preventDefault();
            }

            // Tool shortcuts.
            //
            // Driven by config.toolKeys (from the server's keybinding profile)
            // rather than a hardcoded switch, so the bindings, the button
            // tooltips and the docs table all come from one source and cannot
            // drift. The old switch also hardcoded the pre-profile letters.
            if (!e.ctrlKey && !e.metaKey) {
                const pressed = e.key.toLowerCase();
                const toolKeys = this.config.toolKeys || {};
                const commonKeys = this.config.commonKeys || {};

                for (const tool in toolKeys) {
                    if (toolKeys[tool] === pressed && this.config.tools.includes(tool)) {
                        this._selectTool(tool);
                        e.preventDefault();
                        break;
                    }
                }

                // Select/move mode. setTool(null) already means "no drawing
                // tool armed", which is exactly select-and-move.
                if (pressed === (commonKeys.select || 'v')) {
                    this._selectTool(null);
                    e.preventDefault();
                }

                // Hide/solo the armed label. Shift+H isolates it; pressing it
                // again restores everything.
                if (pressed === (commonKeys.hide || 'h') && this.labelVisibility) {
                    if (this.currentLabel) {
                        if (e.shiftKey) this.labelVisibility.solo(this.currentLabel);
                        else this.labelVisibility.toggle(this.currentLabel);
                        e.preventDefault();
                    }
                }

                // Brush/eraser size, adopting V7's [ and ].
                if (e.key === (commonKeys.brush_size_down || '[')) {
                    this.adjustBrushSize(-Math.max(1, Math.round(this.brushSize * 0.2)));
                    e.preventDefault();
                } else if (e.key === (commonKeys.brush_size_up || ']')) {
                    this.adjustBrushSize(Math.max(1, Math.round(this.brushSize * 0.2)));
                    e.preventDefault();
                }

                switch (pressed) {
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
     * True when the event target is somewhere the user is typing.
     *
     * Covers contenteditable and <select> as well as the usual inputs: a
     * codebook memo is contenteditable, and a select swallows its own arrow
     * and letter keys for option matching.
     */
    _isTypingTarget(target) {
        if (!target || !target.tagName) return false;
        const tag = target.tagName.toUpperCase();
        return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT'
            || target.isContentEditable === true;
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
                const on = btn.dataset.tool === tool;
                btn.classList.toggle('active', on);
                // The buttons render with aria-pressed and the CLICK handlers
                // maintain it, but this path did not -- so a screen reader
                // driven by the keyboard shortcuts heard every tool report
                // "not pressed" no matter which one was armed (WCAG 4.1.2).
                btn.setAttribute('aria-pressed', on ? 'true' : 'false');
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
                const on = btn.dataset.label === labelName;
                btn.classList.toggle('active', on);
                btn.setAttribute('aria-pressed', on ? 'true' : 'false');
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

        // Get the container element for status updates
        const container = document.querySelector(`.image-annotation-container[data-schema="${this.config.schemaName}"]`);

        // Show loading state
        if (container) {
            container.classList.add('loading');
            container.classList.remove('error');
        }

        console.log('Loading image:', imageUrl);
        fabric.Image.fromURL(imageUrl, (img) => {
            // Remove loading state
            if (container) {
                container.classList.remove('loading');
            }

            if (!img || !img.width || !img.height) {
                console.error('Failed to load image:', imageUrl);
                if (container) {
                    container.classList.add('error');
                }
                // Show error message on canvas
                this._showCanvasMessage('Failed to load image. Check the URL or CORS settings.');
                return;
            }
            console.log('Image loaded successfully:', img.width, 'x', img.height);

            this.image = img;

            // Drop any cached pixels from the previous image, or a colour-aware
            // fill on instance N+1 would sample instance N's colours.
            this._sourcePixels = null;
            this._sourcePixelsChecked = false;

            this._fitImageToCanvas();
            img.set({
                selectable: false,
                evented: false,
                hoverCursor: 'default',
            });

            this.canvas.add(img);
            this.canvas.sendToBack(img);
            this.canvas.renderAll();

            // Initialize mask canvas dimensions
            this._resizeMaskCanvas();

            // Load any existing annotations
            this._loadExistingAnnotations();

            // Load any existing masks
            this._loadExistingMasks();

            // carry_over: "auto" pre-fills from the previous image, but only
            // once the item's OWN annotations have been restored above, and
            // only if there are none. Copying over real work would be
            // destructive, and re-copying on every revisit would resurrect
            // annotations the user deliberately deleted.
            if (this.config.carryOver === 'auto' && this.getAnnotationCount() === 0) {
                this.copyFromPrevious(false);
            }
        }, { crossOrigin: 'anonymous' });
    }

    /**
     * Scale and centre the image to fit the current canvas, keeping aspect.
     *
     * Extracted so image load and container resize share one definition;
     * before, only the load path knew how to lay the image out, which is why
     * resizing the window left the canvas at whatever width it happened to
     * have when the page first rendered.
     */
    _fitImageToCanvas() {
        if (!this.image) return;

        const canvasWidth = this.canvas.getWidth();
        const canvasHeight = this.canvas.getHeight();
        const scale = Math.min(
            canvasWidth / this.image.width,
            canvasHeight / this.image.height,
            1,  // Don't scale up
        );

        this.image.set({
            scaleX: scale,
            scaleY: scale,
            left: (canvasWidth - this.image.width * scale) / 2,
            top: (canvasHeight - this.image.height * scale) / 2,
        });

        // Kept for coordinate normalization.
        this.imageOriginalWidth = this.image.width;
        this.imageOriginalHeight = this.image.height;
        this.imageScale = scale;
        this.imageLeft = this.image.left;
        this.imageTop = this.image.top;
    }

    /**
     * Keep the canvas in step with its container as the window resizes.
     *
     * The canvas took `container.clientWidth` once at construction and never
     * looked again, so narrowing the window clipped it and widening left dead
     * space — and on a tablet, rotating the device did the same. Neither is
     * exotic user behaviour.
     */
    _setupResizeHandling() {
        const canvasEl = document.getElementById(this.canvasId);
        if (!canvasEl || typeof ResizeObserver === 'undefined') return;

        // NOT canvasEl.parentElement. Fabric wraps the canvas in its own
        // `.canvas-container` div and sizes that div FROM the canvas, so
        // observing it means watching the thing we resize — it can never
        // report the available space and the handler would never fire.
        // `.canvas-wrapper` is the layout element that actually flexes.
        const container = canvasEl.closest('.canvas-wrapper')
            || canvasEl.parentElement?.parentElement
            || canvasEl.parentElement;
        if (!container) return;

        this._resizeContainer = container;
        this._resizeTimer = null;

        this._resizeObserver = new ResizeObserver(() => {
            // Debounced: a drag-resize fires continuously, and each handled
            // resize re-lays out every annotation.
            clearTimeout(this._resizeTimer);
            this._resizeTimer = setTimeout(() => this.handleResize(), 150);
        });
        this._resizeObserver.observe(container);
    }

    /**
     * Re-lay out the canvas, image, and every annotation for a new size.
     *
     * Annotations are round-tripped through serialize/deserialize rather than
     * transformed in place. Stored coordinates are normalized to the image, so
     * the existing (well-tested) restore path repositions everything correctly
     * for the new scale — and masks, which are rebuilt from RLE at natural
     * image resolution, come back unchanged. Hand-written transform maths here
     * would be a second, subtly different implementation of the coordinate
     * contract.
     */
    handleResize() {
        if (!this.canvas || !this._resizeContainer) return;

        const width = this._resizeContainer.clientWidth;
        // Ignore no-op and zero-width callbacks: a hidden container reports 0,
        // and resizing to 0 would destroy the layout.
        if (!width || Math.abs(width - this.canvas.getWidth()) < 2) return;

        const state = this._serializeAnnotations();
        const activeTool = this.currentTool;

        this.canvas.setWidth(width);

        if (this.image) {
            this._fitImageToCanvas();
            this._resizeMaskCanvas();
        }

        // Rebuild from the stored (normalized) form at the new scale.
        this.canvas.getObjects().slice().forEach(obj => {
            if (obj !== this.image && obj.annotationData) this.canvas.remove(obj);
        });
        this.masks = {};
        this._deserializeAnnotations(state);

        this._renderAllMasks();
        this.canvas.renderAll();

        // Re-apply visibility, which lives outside the serialized annotations.
        if (this.labelVisibility) {
            this.applyLabelVisibility(this.labelVisibility.hiddenLabels());
        }
        this.currentTool = activeTool;

        // MUST rewrite the input. Removing the old objects above fires
        // `object:removed`, whose handler writes the then-empty canvas to the
        // hidden input; nothing in the restore path writes it back. Without
        // this line the annotations are still on screen and still in memory
        // while the field the save path reads says "[]" — so a resize silently
        // discarded the annotator's work on the next save.
        this._updateAnnotationData();
    }

    /**
     * Detach observers and timers.
     *
     * A ResizeObserver holds a reference to the container, so an annotation
     * page that swaps managers without this leaks one per instance.
     */
    destroy() {
        if (this._resizeObserver) {
            this._resizeObserver.disconnect();
            this._resizeObserver = null;
        }
        clearTimeout(this._resizeTimer);
    }

    /**
     * Set the current drawing tool.
     * @param {string} tool - Tool name (bbox, polygon, freeform, landmark, brush, eraser, fill)
     */
    setTool(tool) {
        // Reported before the assignment so a no-op re-select of the armed tool
        // does not inflate the switch count.
        if (tool !== this.currentTool) {
            this._telemetry('tool', { meta: { tool: tool || 'select' } });
        }
        this.currentTool = tool;
        this.isDrawing = false;
        this.drawingObject = null;
        this.polygonPoints = [];
        // Same hazard as polygonPoints: any half-finished shape left here would
        // be picked up by the NEXT tool's completion path.
        this.keypointPoints = [];
        this.cuboidFront = null;

        // Switching AWAY from the wand throws away an unaccepted mask. Keeping
        // it would leave a preview painted over an image the annotator has
        // moved on from, and Enter would then commit a mask they had abandoned.
        if (tool !== 'sam' && this.samTool) this.samTool.clear();

        // Selecting the wand is the first moment anything is fetched: the
        // runtime is 13.5 MB and most image projects never touch this tool.
        if (tool === 'sam') {
            this.ensureSegmentation();
        }

        // Update canvas mode
        if (tool === 'freeform') {
            this.canvas.isDrawingMode = true;
            this.canvas.freeDrawingBrush.color = this.currentColor;
            this.canvas.freeDrawingBrush.width = this.config.freeformBrushSize || 5;
            this._showMaskCanvas(false);
        } else {
            this.canvas.isDrawingMode = false;
        }

        // Show/hide mask canvas for mask tools
        if (tool === 'brush' || tool === 'eraser' || tool === 'fill') {
            this._showMaskCanvas(true);
            this.maskCanvas.style.pointerEvents = 'auto';
        } else if (tool === 'sam') {
            // Visible so the preview paints, but NOT interactive: the wand's
            // clicks go to the fabric canvas, which is what knows the viewport
            // transform. A pointer-events mask canvas would swallow them.
            this._showMaskCanvas(true);
            if (this.maskCanvas) this.maskCanvas.style.pointerEvents = 'none';
        } else {
            this._showMaskCanvas(this._hasMasks());
            if (this.maskCanvas) {
                this.maskCanvas.style.pointerEvents = 'none';
            }
        }

        // Update cursor
        switch (tool) {
            case 'bbox':
            case 'polygon':
            case 'polyline':
            case 'ellipse':
            case 'keypoint_set':
            case 'cuboid_2d':
            case 'landmark':
                this.canvas.defaultCursor = 'crosshair';
                break;
            case 'brush':
            case 'eraser':
                this.canvas.defaultCursor = 'crosshair';
                break;
            case 'fill':
            case 'sam':
                this.canvas.defaultCursor = 'crosshair';
                break;
            default:
                this.canvas.defaultCursor = 'default';
        }
    }

    /**
     * Set the brush/eraser size.
     * @param {number} size - Brush size in pixels
     */
    setBrushSize(size) {
        this.brushSize = size;
        this.eraserSize = size;
    }

    /**
     * Change the brush/eraser size by a delta, clamped, keeping the toolbar
     * slider and its readout in step.
     *
     * Bound to [ and ] to match V7 and CVAT. Adjusting size without reaching
     * for the slider is the difference between painting a boundary in one pass
     * and three.
     * @param {number} delta - Pixels to add (negative to shrink)
     */
    adjustBrushSize(delta) {
        const container = document.querySelector(
            `.image-annotation-container[data-schema="${this.config.schemaName}"]`);
        const slider = container && container.querySelector('.brush-size-slider');

        // Clamp to the slider's own range so the keyboard cannot reach a value
        // the control is unable to display.
        const min = slider ? Number(slider.min) || 1 : 1;
        const max = slider ? Number(slider.max) || 100 : 100;

        const next = Math.max(min, Math.min(max, this.brushSize + delta));
        if (next === this.brushSize) return;
        this.setBrushSize(next);

        // The slider is the visible source of truth for this value; leaving it
        // stale would show one size while painting another.
        if (slider) slider.value = next;
        const readout = container && container.querySelector('.brush-size-value');
        if (readout) readout.textContent = next;
    }

    /**
     * Show or hide the mask canvas.
     * @param {boolean} show - Whether to show the mask canvas
     */
    _showMaskCanvas(show) {
        if (this.maskCanvas) {
            this.maskCanvas.style.display = show ? 'block' : 'none';
        }
    }

    /**
     * Check if there are any masks.
     */
    _hasMasks() {
        return Object.keys(this.masks).length > 0;
    }

    /**
     * Resize mask canvas to match image dimensions.
     */
    _resizeMaskCanvas() {
        if (!this.maskCanvas || !this.image) return;

        const imgWidth = this.image.width * this.image.scaleX;
        const imgHeight = this.image.height * this.image.scaleY;

        this.maskCanvas.width = this.canvas.getWidth();
        this.maskCanvas.height = this.canvas.getHeight();

        // Store mask dimensions relative to image
        this.maskImgWidth = this.image.width;
        this.maskImgHeight = this.image.height;

        // Re-render masks
        this._renderAllMasks();
    }

    /**
     * Start mask drawing (brush/eraser).
     */
    _startMaskDraw(e) {
        if (this.currentTool !== 'brush' && this.currentTool !== 'eraser') return;
        if (!this.currentLabel) return;

        this.isMaskDrawing = true;
        this._strokePx = 0;
        this._strokeLastPoint = null;
        this._drawMaskPoint(e);
    }

    /**
     * Continue mask drawing.
     */
    _continueMaskDraw(e) {
        if (!this.isMaskDrawing) return;
        this._drawMaskPoint(e);
    }

    /**
     * Finish mask drawing.
     */
    _finishMaskDraw() {
        if (this.isMaskDrawing) {
            this.isMaskDrawing = false;
            // Erasing empties tiles but cannot afford to prove a tile is empty
            // per pixel, so the buffers reclaim that memory once per gesture.
            // Without this, erasing a whole mask leaves every tile it ever
            // covered still allocated.
            if (this.currentTool === 'eraser') {
                for (const key in this.masks) {
                    if (this.masks[key] && this.masks[key].buffer) {
                        this.masks[key].buffer.compact();
                    }
                }
            }
            // Emitted before _saveState so a stroke that creates a brand-new
            // mask reads in stream order as "mask added, then painted", which
            // is what happened.
            this._telemetry('stroke', {
                shape: 'mask',
                value: Math.round(this._strokePx),
                meta: { tool: this.currentTool },
            });
            this._strokeLastPoint = null;
            this._saveState();
            this._updateMaskData();
        }
    }


    /**
     * The mask store key a brush stroke should target.
     *
     * In the default `semantic` mode this is the bare label, so every stroke of
     * a class merges into one region — correct for semantic segmentation, and
     * what Potato has always done.
     *
     * In `instance` mode it is `label#N`, so two adjacent cats stay two objects.
     * That distinction is a hard prerequisite for interactive segmentation:
     * SAM returns one mask per object, and a label-keyed store would merge them
     * on arrival.
     *
     * Imported COCO instances are already keyed this way, so the two paths meet.
     */
    _activeMaskKey() {
        if (this.config.maskMode !== 'instance') return this.currentLabel;
        if (this.activeInstance === null || this.activeInstance === undefined) {
            this.activeInstance = this._nextInstanceIndex(this.currentLabel);
        }
        return `${this.currentLabel}#${this.activeInstance}`;
    }

    /** Lowest unused instance index for a label. */
    _nextInstanceIndex(label) {
        let next = 0;
        for (const key of Object.keys(this.masks)) {
            const mask = this.masks[key];
            if (!mask || mask.label !== label) continue;
            const idx = (mask.instance === undefined || mask.instance === null)
                ? 0 : Number(mask.instance);
            if (!Number.isNaN(idx) && idx >= next) next = idx + 1;
        }
        return next;
    }

    /**
     * Start a new object of the current class; the next stroke will not merge
     * into the previous one. No-op outside instance mode.
     */
    newMaskInstance() {
        if (this.config.maskMode !== 'instance') return false;
        this.activeInstance = this._nextInstanceIndex(this.currentLabel);
        this._announce(
            `Started ${this.currentLabel} instance ${this.activeInstance + 1}`);
        return true;
    }

    /**
     * The mask the next paint operation belongs to, creating it if needed.
     *
     * `label` is stored explicitly because the store key is not always the
     * label: in instance mode, and for imported COCO instances, it is
     * "label#instance" so two objects of one class stay apart.
     *
     * Note that this allocates before the caller knows whether the pointer is
     * even over the image — an empty mask is therefore a reachable state, which
     * is why `hasAny()` (not merely "a mask object exists") is what the
     * serializer, the handle list and the count all gate on.
     */
    _ensureMask() {
        const maskKey = this._activeMaskKey();
        if (!this.masks[maskKey]) {
            this.masks[maskKey] = {
                label: this.currentLabel,
                color: this.currentColor,
                buffer: new MaskBuffer(this.maskImgWidth, this.maskImgHeight),
            };
            if (this.config.maskMode === 'instance') {
                this.masks[maskKey].instance = this.activeInstance;
                // An instance mask is a single object, which is what
                // iscrowd=0 means; a label-keyed brush region is a crowd.
                this.masks[maskKey].iscrowd = 0;
            }
        }
        return this.masks[maskKey];
    }

    /**
     * Draw a point on the mask canvas.
     */
    _drawMaskPoint(e) {
        if (!this.image || !this.currentLabel) return;

        const rect = this.maskCanvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;

        const mask = this._ensureMask();
        const size = this.currentTool === 'eraser' ? this.eraserSize : this.brushSize;

        // Convert screen coordinates to image coordinates
        const imgCoords = this._screenToImageCoords(x, y);
        if (!imgCoords) return;

        // Stroke length in IMAGE pixels rather than screen pixels, so the same
        // stroke measures the same whether the annotator was zoomed in or out.
        if (this._strokeLastPoint) {
            const dx = imgCoords.x - this._strokeLastPoint.x;
            const dy = imgCoords.y - this._strokeLastPoint.y;
            this._strokePx += Math.sqrt(dx * dx + dy * dy);
        }
        this._strokeLastPoint = { x: imgCoords.x, y: imgCoords.y };

        // Draw circle on mask data
        this._drawCircleOnMask(mask, imgCoords.x, imgCoords.y, size / 2, this.currentTool === 'eraser');

        // Re-render the visible mask
        this._renderAllMasks();
    }

    /**
     * Convert screen coordinates to image coordinates.
     */
    _screenToImageCoords(screenX, screenY) {
        if (!this.image) return null;

        const vpt = this.canvas.viewportTransform;
        const zoom = this.canvas.getZoom();

        // Account for viewport transform
        const canvasX = (screenX - vpt[4]) / zoom;
        const canvasY = (screenY - vpt[5]) / zoom;

        // Convert to image coordinates
        const imgX = (canvasX - this.image.left) / this.image.scaleX;
        const imgY = (canvasY - this.image.top) / this.image.scaleY;

        // Check bounds
        if (imgX < 0 || imgX >= this.image.width || imgY < 0 || imgY >= this.image.height) {
            return null;
        }

        return { x: Math.floor(imgX), y: Math.floor(imgY) };
    }

    /**
     * Draw a filled circle of radius `radius` at (cx, cy) on a mask.
     *
     * Row-at-a-time rather than pixel-at-a-time. For integer dx the test
     * `dx*dx + dy*dy <= r*r` is exactly `|dx| <= floor(sqrt(r*r - dy*dy))`, so
     * each row is one contiguous span and the brush shape is unchanged — pinned
     * by a test against the per-pixel form.
     *
     * The old version also called `_hexToRgb(mask.color)` **inside the inner
     * loop**, re-parsing the colour string once per pixel of every brush dab.
     * Colour now lives on the mask, not in the buffer, so it is not parsed here
     * at all.
     */
    _drawCircleOnMask(mask, cx, cy, radius, erase) {
        const r = Math.floor(radius);
        const buffer = mask.buffer;

        for (let dy = -r; dy <= r; dy++) {
            const y = cy + dy;
            if (y < 0 || y >= this.maskImgHeight) continue;
            const half = Math.floor(Math.sqrt(r * r - dy * dy));
            if (erase) {
                buffer.clearSpan(y, cx - half, cx + half);
            } else {
                buffer.setSpan(y, cx - half, cx + half);
            }
        }
    }

    /**
     * Flood fill on mask.
     *
     * Two modes, selected by `fill_mode` on the schema:
     *
     *   "region" (default) - grow across pixels whose colour is within
     *       `fill_tolerance` of the clicked pixel in the SOURCE IMAGE. This is
     *       what annotators expect from a fill tool: click the sky, get the
     *       sky.
     *   "empty" - grow across unpainted mask area, ignoring image content.
     *       Useful for filling a hole inside an existing mask.
     *
     * Region mode needs to read the image's pixels, which a cross-origin image
     * forbids; that case falls back to "empty" with a warning rather than
     * throwing a SecurityError into the console and doing nothing.
     */
    _floodFill(e) {
        if (!this.image || !this.currentLabel) return;

        const rect = this.maskCanvas.getBoundingClientRect();
        const imgCoords = this._screenToImageCoords(
            e.clientX - rect.left, e.clientY - rect.top);
        if (!imgCoords) return;

        const mask = this._ensureMask();
        let mode = this.config.fillMode || 'region';
        const pixels = mode === 'region' ? this._getSourcePixels() : null;
        if (mode === 'region' && !pixels) {
            mode = 'empty';
        }

        const filled = this._floodFillFrom(
            mask, imgCoords.x, imgCoords.y, mode, pixels);
        if (!filled) return;

        this._renderAllMasks();
        this._telemetry('fill', {
            shape: 'mask', value: filled, meta: { mode: mode },
        });
        this._saveState();
        this._updateMaskData();
    }

    /**
     * Span-based flood fill. Returns the number of pixels filled.
     *
     * The previous version pushed all four neighbours of every pixel, so a
     * region of N pixels cost ~4N stack pushes and ~4N pops. This walks each
     * horizontal run to its ends, fills the whole run, then seeds the rows
     * above and below **only where a run begins** — the standard span-filling
     * optimisation — so the stack holds runs rather than pixels.
     *
     * Measured on a full-canvas fill, output byte-identical to the old
     * algorithm (pinned by tests/jest/flood-fill.test.js):
     *
     *     1 MP    19.8ms -> 10.7ms   (1.8x)
     *     3 MP    57.6ms -> 20.8ms   (2.8x)
     *    12 MP   213.2ms -> 69.1ms   (3.1x)
     *
     * Deliberately NOT claimed as the order-of-magnitude win the stack-push
     * count suggests: writing four bytes per pixel dominates, and that cost is
     * unchanged. The gain grows with image size because stack churn is what
     * scales badly, and it is peak stack memory that improves most.
     *
     * `visited` stays a Uint8Array rather than a Set of "x,y" strings: the
     * string form allocated one key per pixel and was the original reason this
     * locked the tab.
     *
     * ## Why "empty" mode pre-seeds `visited`
     *
     * Empty mode grows only into unpainted area, so it used to read the mask on
     * every probe — now a tiled lookup rather than a flat array index. Instead
     * of paying that in the hot loop, the already-painted pixels are marked
     * visited up front: a pixel that is already painted can never be filled, so
     * "visited" and "already painted" are the same exclusion. That pass costs
     * one step per *set* pixel (cheap, since the interesting case is a mostly
     * empty mask) and leaves the inner loop touching nothing but `visited` and,
     * in region mode, the source pixels.
     */
    _floodFillFrom(mask, startX, startY, mode, pixels) {
        const width = this.maskImgWidth;
        const height = this.maskImgHeight;
        const buffer = mask.buffer;
        const tolerance = this.config.fillTolerance !== undefined
            ? this.config.fillTolerance : 32;
        const maxPixels = this.config.fillMaxPixels || 4000000;

        const startPix = startY * width + startX;
        if (mode === 'empty' && buffer.isSetAt(startX, startY)) {
            // Starting inside existing paint: nothing to grow into.
            return 0;
        }

        let targetR = 0, targetG = 0, targetB = 0;
        if (mode === 'region') {
            const si = startPix * 4;
            targetR = pixels[si];
            targetG = pixels[si + 1];
            targetB = pixels[si + 2];
        }

        const visited = new Uint8Array(width * height);
        if (mode === 'empty') {
            buffer.forEachSetPixel((pix) => { visited[pix] = 1; });
        }

        /** Whether pixel index `pix` should be filled. */
        const matches = (pix) => {
            if (visited[pix]) return false;
            if (mode === 'region') {
                const di = pix * 4;
                return Math.abs(pixels[di] - targetR) <= tolerance &&
                    Math.abs(pixels[di + 1] - targetG) <= tolerance &&
                    Math.abs(pixels[di + 2] - targetB) <= tolerance;
            }
            return true;  // empty mode: painted pixels are already visited
        };

        const stack = [startPix];
        let filled = 0;
        let capped = false;

        while (stack.length > 0 && !capped) {
            const seed = stack.pop();
            if (!matches(seed)) continue;

            const sx = seed % width;
            const rowStart = seed - sx;
            const y = rowStart / width;

            // Walk to both ends of this run.
            let left = sx;
            while (left > 0 && matches(rowStart + left - 1)) left--;
            let right = sx;
            while (right + 1 < width && matches(rowStart + right + 1)) right++;

            // Honour the cap mid-run, exactly as the per-pixel version did, so
            // a capped fill paints the same pixels either way.
            if (filled + (right - left + 1) > maxPixels) {
                right = left + (maxPixels - filled) - 1;
                capped = true;
            }

            // Paint the run in one span: one tile lookup per 64 columns rather
            // than one per pixel.
            buffer.setSpan(y, left, right);

            // Seed the neighbouring rows only at the START of each contiguous
            // run there. Seeding every column would put the per-pixel stack
            // growth straight back.
            let aboveOpen = false;
            let belowOpen = false;
            for (let x = left; x <= right; x++) {
                const pix = rowStart + x;
                visited[pix] = 1;
                filled++;

                if (rowStart >= width) {
                    const up = pix - width;
                    if (matches(up)) {
                        if (!aboveOpen) { stack.push(up); aboveOpen = true; }
                    } else {
                        aboveOpen = false;
                    }
                }
                if (rowStart + width < width * height) {
                    const down = pix + width;
                    if (matches(down)) {
                        if (!belowOpen) { stack.push(down); belowOpen = true; }
                    } else {
                        belowOpen = false;
                    }
                }
            }

            if (capped) {
                console.warn(
                    `[image-annotation] fill stopped at ${maxPixels} pixels. ` +
                    `Lower fill_tolerance, or raise fill_max_pixels.`);
            }
        }

        return filled;
    }

    /**
     * RGBA pixels of the source image at its natural resolution, cached.
     *
     * Returns null when the pixels cannot be read (cross-origin image without
     * CORS headers, or no decoded element yet), so callers can degrade instead
     * of failing.
     */
    _getSourcePixels() {
        // Checked-flag rather than a null test, so a tainted canvas is not
        // re-attempted (and re-warned) on every single click.
        if (this._sourcePixelsChecked) return this._sourcePixels;

        const el = this.image && (this.image._element || this.image.getElement?.());
        if (!el) return null;
        this._sourcePixelsChecked = true;

        try {
            const c = document.createElement('canvas');
            c.width = this.maskImgWidth;
            c.height = this.maskImgHeight;
            const ctx = c.getContext('2d', { willReadFrequently: true });
            ctx.drawImage(el, 0, 0, this.maskImgWidth, this.maskImgHeight);
            this._sourcePixels = ctx.getImageData(
                0, 0, this.maskImgWidth, this.maskImgHeight).data;
            return this._sourcePixels;
        } catch (err) {
            // SecurityError: the image tainted the canvas. Serve images from
            // the same origin, or with Access-Control-Allow-Origin, to use
            // colour-aware fill.
            console.warn(
                '[image-annotation] cannot read image pixels, falling back to ' +
                'empty-area fill. Serve the image same-origin or with CORS ' +
                'headers to enable colour-aware fill.', err.name);
            this._sourcePixels = null;
            return null;
        }
    }

    /**
     * The masks that should be painted, in store order.
     *
     * Masks live outside the fabric canvas, so `obj.visible` cannot reach them;
     * hidden classes are skipped here instead. Keyed by the mask's real label,
     * not the store key, which is "label#instance" for imported instances.
     */
    _visibleMasks() {
        const out = [];
        for (const key in this.masks) {
            const mask = this.masks[key];
            if (!mask || !mask.buffer) continue;
            const label = mask.label !== undefined ? mask.label : key;
            if (this._hiddenLabels && this._hiddenLabels.has(label)) continue;
            out.push({ key, mask });
        }
        return out;
    }

    /**
     * Composite every visible mask into one offscreen canvas at natural image
     * resolution, repainting only the 64x64 tiles that changed.
     *
     * **One shared canvas, not one per mask.** A canvas costs four bytes per
     * pixel of backing store — 48 MB on a 12 MP image — so a canvas per class
     * would hand straight back the memory the sparse buffers save, and ten
     * classes would be worse than the dense buffers they replaced.
     *
     * The version before the sparse rewrite was worse still: it allocated a
     * fresh full-image RGBA array *and* a fresh full-size temp canvas **per
     * mask, per mousemove**, so one brush dab cost the whole image times the
     * number of classes.
     *
     * @returns {HTMLCanvasElement|null} null where there is no 2D context
     *     (jsdom without a canvas backend), so callers degrade rather than throw
     */
    _compositeMasks(visible) {
        const w = this.maskImgWidth;
        const h = this.maskImgHeight;
        if (!w || !h || typeof document === 'undefined') return null;

        if (!this._maskComposite || this._maskComposite.width !== w ||
            this._maskComposite.height !== h) {
            this._maskComposite = document.createElement('canvas');
            this._maskComposite.width = w;
            this._maskComposite.height = h;
            this._compositeCtx = this._maskComposite.getContext('2d');
            this._compositeSignature = null;
        }
        if (!this._compositeCtx) return null;

        // Tiles are only comparable across buffers that agree on geometry.
        // _restoreMaskFromEntry rescales mismatched masks, so this normally
        // keeps everything; anything left over is skipped rather than painted
        // at the wrong stride.
        const usable = visible.filter(({ mask }) =>
            mask.buffer.width === w && mask.buffer.height === h &&
            mask.buffer.tileSize === MaskBuffer.DEFAULT_TILE_SIZE);

        // Which masks are shown, in which order, in which colour. A change to
        // any of that (a delete, a relabel, a class hidden) cannot be expressed
        // as dirty tiles on a surviving buffer, so it forces a full repaint.
        const signature = usable.map(({ key, mask }) => `${key}:${mask.color}`).join('|');
        let full = signature !== this._compositeSignature;
        this._compositeSignature = signature;

        const tiles = new Set();
        for (const { mask } of usable) {
            if (mask.buffer.isAllDirty()) full = true;
            else for (const ti of mask.buffer.dirtyTiles()) tiles.add(ti);
        }

        if (full) {
            // Clear first: a deleted mask's tiles are no longer in any buffer,
            // so nothing would repaint over them.
            this._compositeCtx.clearRect(0, 0, w, h);
            tiles.clear();
            for (const { mask } of usable) {
                for (const ti of mask.buffer.tiles.keys()) tiles.add(ti);
            }
        }

        // Resolved once rather than inside the per-tile loop below.
        const layers = usable.map(({ mask }) =>
            ({ buffer: mask.buffer, rgb: this._hexToRgb(mask.color) }));

        for (const ti of tiles) {
            const [x0, y0, tw, th] = layers.length
                ? layers[0].buffer.tileRect(ti)
                : [0, 0, 0, 0];
            if (tw <= 0 || th <= 0) continue;
            // Starts fully transparent, so an unset pixel needs no write and an
            // erased tile paints as a clean erase.
            const img = this._compositeCtx.createImageData(tw, th);
            for (const { buffer, rgb } of layers) {
                buffer.paintTileInto(img, ti, tw, th, rgb);
            }
            this._compositeCtx.putImageData(img, x0, y0);
        }

        for (const { mask } of visible) mask.buffer.clearDirty();
        return this._maskComposite;
    }

    /**
     * Render all masks to the mask canvas.
     */
    _renderAllMasks() {
        if (!this.maskCtx || !this.image) return;

        // Clear canvas
        this.maskCtx.clearRect(0, 0, this.maskCanvas.width, this.maskCanvas.height);

        const vpt = this.canvas.viewportTransform;
        const zoom = this.canvas.getZoom();

        // Calculate image position on screen
        const imgLeft = this.image.left * zoom + vpt[4];
        const imgTop = this.image.top * zoom + vpt[5];
        const imgWidth = this.image.width * this.image.scaleX * zoom;
        const imgHeight = this.image.height * this.image.scaleY * zoom;

        const visible = this._visibleMasks();
        const composite = visible.length ? this._compositeMasks(visible) : null;
        if (composite) {
            this.maskCtx.globalAlpha = this.maskOpacity;
            this.maskCtx.drawImage(composite, imgLeft, imgTop, imgWidth, imgHeight);
        }

        // The in-progress SAM preview paints LAST, over the committed masks,
        // and through the same transform computed above -- a second painter
        // with its own transform maths is exactly how the old segmentation
        // manager drifted out of alignment under zoom.
        this._renderSegmentationPreview(imgLeft, imgTop, imgWidth, imgHeight);

        this.maskCtx.globalAlpha = 1.0;
    }

    /**
     * Set (or clear) the interactive-segmentation preview.
     *
     * Called by SAMTool. The tool owns the prompt; the manager owns every
     * pixel, so nothing else draws on the mask canvas.
     *
     * @param {object|null} preview {rle, points, box, color, alpha}
     */
    setSegmentationPreview(preview) {
        this._segmentationPreview = preview || null;
        // A SAM preview is a machine-produced mask offered for acceptance, so
        // it belongs in the same latency measure as a detector's suggestions —
        // the annotator still has to look at the boundary before pressing
        // Enter. The click that PROMPTED it is theirs, which is why this counts
        // as one suggestion rather than several.
        if (this._segmentationPreview) {
            this._segmentationId = (this._segmentationId || 0) + 1;
            this._telemetry('ai_suggest', {
                shape: 'mask',
                meta: { sid: `sam-${this._segmentationId}`, src: 'sam' },
            });
        }
        this._renderAllMasks();
    }

    _renderSegmentationPreview(imgLeft, imgTop, imgWidth, imgHeight) {
        const preview = this._segmentationPreview;
        if (!preview || !this.maskCtx || !this.image) return;

        const naturalWidth = this.image.width;
        const naturalHeight = this.image.height;

        if (preview.rle && preview.rle.counts) {
            const temp = document.createElement('canvas');
            temp.width = naturalWidth;
            temp.height = naturalHeight;
            const tempCtx = temp.getContext('2d');
            const image = tempCtx.createImageData(naturalWidth, naturalHeight);
            const rgb = this._hexToRgb(preview.color || '#00b3ff');

            // Potato RLE: row-major counts alternating 0-run first.
            let index = 0;
            let value = 0;
            for (const count of preview.rle.counts) {
                if (value) {
                    for (let i = 0; i < count; i++) {
                        const p = (index + i) * 4;
                        image.data[p] = rgb.r;
                        image.data[p + 1] = rgb.g;
                        image.data[p + 2] = rgb.b;
                        image.data[p + 3] = 255;
                    }
                }
                index += count;
                value = 1 - value;
            }
            tempCtx.putImageData(image, 0, 0);

            this.maskCtx.globalAlpha = preview.alpha || 0.45;
            this.maskCtx.drawImage(temp, imgLeft, imgTop, imgWidth, imgHeight);
            this.maskCtx.globalAlpha = 1.0;
        }

        // The prompt markers matter as much as the mask: without them an
        // annotator refining a mask cannot see which points they have already
        // placed, and clicks the same spot twice.
        const scaleX = imgWidth / naturalWidth;
        const scaleY = imgHeight / naturalHeight;
        (preview.points || []).forEach(([x, y, label]) => {
            const sx = imgLeft + x * scaleX;
            const sy = imgTop + y * scaleY;
            this.maskCtx.beginPath();
            this.maskCtx.arc(sx, sy, 5, 0, Math.PI * 2);
            this.maskCtx.fillStyle = label === 0 ? '#d7263d' : '#0aa84f';
            this.maskCtx.fill();
            this.maskCtx.lineWidth = 2;
            this.maskCtx.strokeStyle = '#fff';
            this.maskCtx.stroke();
        });

        if (preview.box) {
            const [bx, by, bw, bh] = preview.box;
            this.maskCtx.setLineDash([6, 4]);
            this.maskCtx.lineWidth = 2;
            this.maskCtx.strokeStyle = preview.color || '#00b3ff';
            this.maskCtx.strokeRect(imgLeft + bx * scaleX, imgTop + by * scaleY,
                                    bw * scaleX, bh * scaleY);
            this.maskCtx.setLineDash([]);
        }
    }

    /**
     * Convert hex color to RGB.
     */
    _hexToRgb(hex) {
        const cached = this._rgbCache && this._rgbCache.get(hex);
        if (cached) return cached;

        let rgb = null;
        const text = typeof hex === 'string' ? hex.trim() : '';
        // #rgb, #rrggbb, and #rrggbbaa. The shorthand form is valid CSS and
        // common in hand-written configs; it used to fall through to the
        // fallback below, so a label declared `color: "#0f0"` painted its mask
        // RED while its button and bounding boxes — which go through CSS rather
        // than this function — rendered green. Alpha is dropped: mask opacity is
        // a schema option applied to the whole overlay.
        const m = /^#?([a-f\d]{3}|[a-f\d]{6}|[a-f\d]{8})$/i.exec(text);
        if (m) {
            const body = m[1];
            if (body.length === 3) {
                rgb = {
                    r: parseInt(body[0] + body[0], 16),
                    g: parseInt(body[1] + body[1], 16),
                    b: parseInt(body[2] + body[2], 16),
                };
            } else {
                rgb = {
                    r: parseInt(body.slice(0, 2), 16),
                    g: parseInt(body.slice(2, 4), 16),
                    b: parseInt(body.slice(4, 6), 16),
                };
            }
        }

        if (!rgb) {
            // Still red, because changing the fallback would silently restyle
            // existing projects — but say so once per distinct value instead of
            // leaving the annotator to wonder why one class is the wrong
            // colour. Named colours and rgb()/hsl() land here.
            console.warn(
                `[image-annotation] cannot read the colour "${hex}"; painting ` +
                `red. Use a hex colour such as "#33aa55".`);
            rgb = { r: 255, g: 0, b: 0 };
        }

        if (!this._rgbCache) this._rgbCache = new Map();
        this._rgbCache.set(hex, rgb);
        return rgb;
    }

    /**
     * Update the hidden input with mask data.
     */
    _updateMaskData() {
        // Masks are persisted inside the main annotation blob (see
        // _serializeAnnotations), which is the input the save path actually collects.
        // Push them there whenever a stroke changes.
        this._updateAnnotationData();

        // Also mirror into the legacy mask-data-input when it is present, so a page
        // that still has that element keeps working. It is not read back on save —
        // nothing ever collected it — but leaving it stale would be misleading.
        const maskInputId = this.inputId.replace('input-', 'mask-input-');
        const input = document.getElementById(maskInputId);
        if (!input) return;

        const masksData = {};
        for (const key in this.masks) {
            const mask = this.masks[key];
            if (!mask || !mask.buffer) continue;
            masksData[mask.label !== undefined ? mask.label : key] = {
                color: mask.color,
                rle: mask.buffer.encodeRLE(),
                width: this.maskImgWidth,
                height: this.maskImgHeight
            };
        }

        input.value = JSON.stringify(masksData);
    }

    /**
     * Load existing mask data.
     */
    _loadExistingMasks() {
        // Masks now arrive with the shapes, via _deserializeAnnotations. If that
        // already restored some, stop — reading the legacy input here would let a
        // browser-restored value from the PREVIOUS instance overwrite them. That
        // input is never cleared between instances (nothing collects it, so it has no
        // data-server-set guard), which is exactly the cross-instance leak the hidden
        // annotation inputs are guarded against.
        if (Object.keys(this.masks || {}).length > 0) return;

        const maskInputId = this.inputId.replace('input-', 'mask-input-');
        const input = document.getElementById(maskInputId);
        if (!input || !input.value) return;

        try {
            const masksData = JSON.parse(input.value);
            for (const label in masksData) {
                const maskInfo = masksData[label];
                this.masks[label] = {
                    color: maskInfo.color,
                    buffer: MaskBuffer.fromRLE(
                        maskInfo.rle, maskInfo.width, maskInfo.height),
                };
            }
            this._renderAllMasks();
        } catch (e) {
            console.warn('Failed to load existing masks:', e);
        }
    }

    /**
     * Set the current label and color.
     * @param {string} label - Label name
     * @param {string} color - Color hex code
     */
    setLabel(label, color) {
        // Compare BEFORE assigning, or the check is always false.
        const labelChanged = this.currentLabel !== label;
        this.currentLabel = label;
        this.currentColor = color || '#FF6B6B';
        if (labelChanged) {
            // Instance indices are per-label. Carrying one across a label
            // change would make instance 3 of "cat" become instance 3 of
            // "dog" and merge two different objects.
            this.activeInstance = null;
        }

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
            case 'polyline':
                this._addPolygonPoint(pointer);
                break;
            case 'ellipse':
                this._startEllipse(pointer);
                break;
            case 'keypoint_set':
                this._addKeypoint(pointer);
                break;
            case 'cuboid_2d':
                this._cuboidClick(pointer);
                break;
            case 'landmark':
                this._addLandmark(pointer);
                break;
            case 'sam':
                this._samClick(pointer);
                break;
            // Freeform handled by Fabric's drawing mode
        }
    }

    /**
     * A click with the magic-wand tool.
     *
     * Fabric's pointer is already in IMAGE space once the viewport transform
     * is undone, which is the same space the annotator sees and the space SAM
     * prompts are given in -- the 1024-scaling happens inside the preprocessor,
     * so nothing here needs to know about it.
     *
     * Shift subtracts. That is the convention CVAT and V7 both use, and the
     * one annotators arriving from either will try first.
     */
    _samClick(pointer) {
        if (!this.samTool || !this.image) return;

        const coords = this._pointerToImagePixels(pointer);
        if (!coords) return;

        const negative = !!(this._lastPointerEvent
                            && this._lastPointerEvent.shiftKey);
        // Deliberately not awaited: the click should feel instant, and the
        // preview repaints itself when the decode resolves.
        this.samTool.addPoint(coords.x, coords.y, negative);
    }

    /**
     * Fabric pointer -> ORIGINAL image pixels.
     *
     * The image is scaled to fit and centred, so canvas coordinates are not
     * image coordinates; a click near the top-left of the canvas is usually
     * OUTSIDE the image entirely. Returns null there rather than a negative
     * coordinate that reads as a valid prompt.
     */
    _pointerToImagePixels(pointer) {
        if (!this.image) return null;
        const x = (pointer.x - this.image.left) / this.image.scaleX;
        const y = (pointer.y - this.image.top) / this.image.scaleY;
        if (x < 0 || y < 0 || x >= this.image.width || y >= this.image.height) {
            return null;
        }
        return { x: x, y: y };
    }

    /**
     * Continue drawing based on current tool.
     */
    _continueDrawing(pointer) {
        switch (this.currentTool) {
            case 'bbox':
                this._updateBbox(pointer);
                break;
            case 'ellipse':
                this._updateEllipse(pointer);
                break;
            case 'cuboid_2d':
                this._updateCuboidFront(pointer);
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
            case 'ellipse':
                this._finishEllipse();
                break;
            case 'cuboid_2d':
                this._finishCuboidFront();
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
     * Complete the polygon or polyline shape.
     *
     * Both are built from the same click-collected point list; the only
     * differences are the minimum vertex count and whether the result encloses
     * an area. A polyline gets no fill because it has no interior — filling it
     * would draw a region the annotator never claimed.
     */
    _completePolygon() {
        const isPolyline = this.currentTool === 'polyline';
        const minPoints = isPolyline ? 2 : 3;
        if (this.polygonPoints.length < minPoints) return;

        // Remove temporary markers and lines
        const toRemove = this.canvas.getObjects().filter(
            obj => obj.polygonMarker || obj.polygonLine
        );
        toRemove.forEach(obj => this.canvas.remove(obj));

        const Shape = isPolyline ? fabric.Polyline : fabric.Polygon;
        const shape = new Shape(this.polygonPoints, {
            fill: isPolyline ? '' : this._colorWithAlpha(this.currentColor, 0.2),
            stroke: this.currentColor,
            strokeWidth: 2,
            selectable: true,
            hasControls: true,
            hasBorders: true,
            // An open path is only hittable on its stroke, so give fabric a
            // usable target width; without this a 2px polyline is nearly
            // impossible to select or delete.
            perPixelTargetFind: isPolyline,
            targetFindTolerance: isPolyline ? 8 : 0,
        });

        shape.annotationData = {
            type: isPolyline ? 'polyline' : 'polygon',
            label: this.currentLabel,
            color: this.currentColor,
        };

        this.canvas.add(shape);
        this.polygonPoints = [];
        this._saveState();
        this._updateAnnotationData();
    }

    /**
     * The ordered point names for the active skeleton, or [] if none declared.
     */
    _skeletonNames() {
        const skeletons = this.config.skeletons || {};
        const name = this.currentSkeleton
            || Object.keys(skeletons)[0]
            || '';
        const def = skeletons[name];
        return (def && def.names) || [];
    }

    /**
     * Add the next point of a keypoint set.
     *
     * Points are placed in the skeleton's declared ORDER — that ordering is the
     * only thing that makes index 5 mean "left shoulder", so the tool must not
     * let the annotator place them out of sequence. Right-click (handled by the
     * caller) or `Backspace` marks the current point as not-labelled and
     * advances, which is how an occluded joint is recorded.
     */
    _addKeypoint(pointer, visibility = 2) {
        const names = this._skeletonNames();
        this.keypointPoints = this.keypointPoints || [];

        this.keypointPoints.push({ x: pointer.x, y: pointer.y, v: visibility });

        const idx = this.keypointPoints.length - 1;
        const marker = new fabric.Circle({
            left: pointer.x - 5,
            top: pointer.y - 5,
            radius: 5,
            fill: visibility === 1 ? '#ffffff' : this.currentColor,
            stroke: this.currentColor,
            strokeWidth: 2,
            selectable: false,
            evented: false,
            keypointMarker: true,
        });
        this.canvas.add(marker);

        // Draw the skeleton edge back to whichever earlier point this one
        // connects to, so the annotator sees the figure take shape.
        const edges = ((this.config.skeletons || {})[
            this.currentSkeleton || Object.keys(this.config.skeletons || {})[0]
        ] || {}).edges || [];
        edges.forEach(([from, to]) => {
            if (to !== idx || from >= this.keypointPoints.length) return;
            const a = this.keypointPoints[from];
            if (!a || !a.v) return;
            this.canvas.add(new fabric.Line([a.x, a.y, pointer.x, pointer.y], {
                stroke: this.currentColor,
                strokeWidth: 2,
                selectable: false,
                evented: false,
                keypointLine: true,
            }));
        });

        this.canvas.renderAll();
        this._announce(names[idx]
            ? `Placed ${names[idx]} (${idx + 1} of ${names.length})`
            : `Placed keypoint ${idx + 1}`);

        // A skeleton with a declared length completes itself.
        if (names.length && this.keypointPoints.length >= names.length) {
            this._completeKeypointSet();
        }
    }

    /**
     * Finish the keypoint set and replace the markers with one grouped object.
     */
    _completeKeypointSet() {
        const points = this.keypointPoints || [];
        if (points.length < 1) return;

        const toRemove = this.canvas.getObjects().filter(
            o => o.keypointMarker || o.keypointLine);
        toRemove.forEach(o => this.canvas.remove(o));

        const parts = [];
        const skeletonName = this.currentSkeleton
            || Object.keys(this.config.skeletons || {})[0] || '';
        const edges = ((this.config.skeletons || {})[skeletonName] || {}).edges || [];

        edges.forEach(([from, to]) => {
            const a = points[from];
            const b = points[to];
            if (!a || !b || !a.v || !b.v) return;
            parts.push(new fabric.Line([a.x, a.y, b.x, b.y], {
                stroke: this.currentColor, strokeWidth: 2,
            }));
        });
        points.forEach(p => {
            if (!p.v) return;
            parts.push(new fabric.Circle({
                left: p.x - 5, top: p.y - 5, radius: 5,
                fill: p.v === 1 ? '#ffffff' : this.currentColor,
                stroke: this.currentColor, strokeWidth: 2,
            }));
        });

        if (!parts.length) {
            this.keypointPoints = [];
            return;
        }

        const group = new fabric.Group(parts, {
            selectable: true, hasControls: true, hasBorders: true,
        });
        group.annotationData = {
            type: 'keypoint_set',
            label: this.currentLabel,
            color: this.currentColor,
            skeleton: skeletonName,
            // The point list is carried on the object because a fabric Group
            // cannot be reduced back to ordered keypoints: it holds lines and
            // circles in draw order, with unlabelled points absent entirely.
            keypoints: points.map(p => ({ x: p.x, y: p.y, v: p.v })),
        };

        this.canvas.add(group);
        this.keypointPoints = [];
        this._saveState();
        this._updateAnnotationData();
        this._announce(`Completed ${this.currentLabel} skeleton`);
    }

    /**
     * Cuboid drawing is two-stage: drag the visible FRONT face, then move to
     * set the depth offset and click once more to commit.
     */
    _cuboidClick(pointer) {
        if (this.cuboidFront) {
            this._finishCuboid(pointer);
            return;
        }
        this.isDrawing = true;
        this.startX = pointer.x;
        this.startY = pointer.y;
        this.drawingObject = new fabric.Rect({
            left: pointer.x, top: pointer.y, width: 0, height: 0,
            fill: this._colorWithAlpha(this.currentColor, 0.15),
            stroke: this.currentColor, strokeWidth: 2,
            selectable: false, evented: false,
        });
        this.canvas.add(this.drawingObject);
    }

    _updateCuboidFront(pointer) {
        if (!this.drawingObject || this.cuboidFront) return;
        this._updateBbox(pointer);
    }

    /**
     * Commit the front face and wait for the depth click.
     */
    _finishCuboidFront() {
        if (!this.drawingObject) return;
        this.isDrawing = false;
        const r = this.drawingObject;
        if (r.width < 5 || r.height < 5) {
            this.canvas.remove(r);
            this.drawingObject = null;
            return;
        }
        this.cuboidFront = [
            { x: r.left, y: r.top },
            { x: r.left + r.width, y: r.top },
            { x: r.left + r.width, y: r.top + r.height },
            { x: r.left, y: r.top + r.height },
        ];
        this._announce('Front face set — click to set the depth');
    }

    /**
     * Second click: the offset from the front face becomes the back face.
     */
    _finishCuboid(pointer) {
        const front = this.cuboidFront;
        this.cuboidFront = null;
        if (this.drawingObject) {
            this.canvas.remove(this.drawingObject);
            this.drawingObject = null;
        }
        if (!front) return;

        const dx = pointer.x - front[0].x;
        const dy = pointer.y - front[0].y;
        const back = front.map(p => ({ x: p.x + dx, y: p.y + dy }));

        const parts = [
            new fabric.Polygon(front, {
                fill: this._colorWithAlpha(this.currentColor, 0.2),
                stroke: this.currentColor, strokeWidth: 2,
            }),
            new fabric.Polygon(back, {
                fill: '', stroke: this.currentColor, strokeWidth: 1,
                strokeDashArray: [4, 3],
            }),
        ];
        // The four connecting edges that make it read as a box.
        front.forEach((p, i) => parts.push(new fabric.Line(
            [p.x, p.y, back[i].x, back[i].y],
            { stroke: this.currentColor, strokeWidth: 1 })));

        const group = new fabric.Group(parts, {
            selectable: true, hasControls: true, hasBorders: true,
        });
        group.annotationData = {
            type: 'cuboid_2d',
            label: this.currentLabel,
            color: this.currentColor,
            front: front.map(p => ({ x: p.x, y: p.y })),
            back: back.map(p => ({ x: p.x, y: p.y })),
        };

        this.canvas.add(group);
        this._saveState();
        this._updateAnnotationData();
        this._announce(`Added ${this.currentLabel} cuboid`);
    }

    /**
     * Start drawing an ellipse (drag from one corner of its bounding box).
     */
    _startEllipse(pointer) {
        this.isDrawing = true;
        this.startX = pointer.x;
        this.startY = pointer.y;

        this.drawingObject = new fabric.Ellipse({
            left: pointer.x,
            top: pointer.y,
            rx: 0,
            ry: 0,
            fill: this._colorWithAlpha(this.currentColor, 0.2),
            stroke: this.currentColor,
            strokeWidth: 2,
            originX: 'left',
            originY: 'top',
            selectable: true,
            hasControls: true,
            hasBorders: true,
        });

        this.canvas.add(this.drawingObject);
    }

    /**
     * Resize the ellipse while dragging.
     */
    _updateEllipse(pointer) {
        if (!this.drawingObject) return;

        this.drawingObject.set({
            left: Math.min(this.startX, pointer.x),
            top: Math.min(this.startY, pointer.y),
            rx: Math.abs(pointer.x - this.startX) / 2,
            ry: Math.abs(pointer.y - this.startY) / 2,
        });

        this.canvas.renderAll();
    }

    /**
     * Finish the ellipse, discarding accidental click-sized ones.
     */
    _finishEllipse() {
        if (!this.drawingObject) return;

        this.isDrawing = false;

        // Same 5px floor as the bbox tool: a stray click must not leave a
        // degenerate annotation behind.
        if (this.drawingObject.rx > 2.5 && this.drawingObject.ry > 2.5) {
            this.drawingObject.annotationData = {
                type: 'ellipse',
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
     *
     * Fired from the canvas 'path:created' event, which hands us the finished
     * path directly. Falls back to scanning for an unclaimed path so a manual
     * call still works.
     */
    _handleFreeformPath(opt) {
        const path = (opt && opt.path) || this.canvas.getObjects().find(
            obj => obj.type === 'path' && !obj.annotationData
        );

        if (!path) return;
        if (!this.currentLabel) {
            // No label selected: fabric already drew the stroke, but we have
            // nothing to attribute it to. Remove it rather than leaving an
            // unserializable object on the canvas.
            this.canvas.remove(path);
            this.canvas.renderAll();
            return;
        }

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

    /**
     * Add an annotation programmatically.
     *
     * This is the sanctioned entry point for anything that produces annotations
     * without the user drawing them: accepted AI detections, model-generated
     * masks, and copy-from-previous-image. It exists because
     * visual_ai_assistant.js has always called `addAnnotation` and the method
     * was never written — accepting a detection logged a warning and dropped
     * the box on the floor.
     *
     * `obj` MUST be in the client contract shape that _serializeAnnotations
     * writes and cv_utils.to_client_object produces, i.e. shape coordinates
     * NORMALIZED to [0, 1] under a `coordinates` key, masks carrying absolute
     * `rle: {counts, size:[h, w]}`. Anything else is rejected rather than
     * stored, so a caller passing the wrong shape fails loudly here instead of
     * silently exporting a [0,0,0,0] box later.
     *
     * @param {Object} obj - Client-contract annotation object
     * @returns {boolean} true if the annotation was added
     */
    addAnnotation(obj) {
        if (!obj || !obj.type) {
            console.warn('[image-annotation] addAnnotation: missing object or type');
            return false;
        }
        if (!this.image) {
            console.warn('[image-annotation] addAnnotation: no image loaded yet');
            return false;
        }

        if (obj.type === 'mask') {
            if (!obj.rle || !Array.isArray(obj.rle.counts) ||
                !Array.isArray(obj.rle.size) || obj.rle.size.length !== 2) {
                console.warn(
                    '[image-annotation] addAnnotation: mask needs rle {counts, size:[h,w]}',
                    obj);
                return false;
            }
            this._restoreMaskFromEntry(obj);
            if (this.currentTool !== 'freeform') {
                this._showMaskCanvas(true);
            }
            this._renderAllMasks();
        } else {
            if (obj.coordinates === undefined || obj.coordinates === null) {
                console.warn(
                    '[image-annotation] addAnnotation: shape needs normalized ' +
                    '`coordinates` (see the contract in cv_utils.py)', obj);
                return false;
            }
            const before = this.canvas.getObjects().length;
            this._createAnnotationObject(obj);
            if (this.canvas.getObjects().length === before) {
                // _createAnnotationObject silently ignores unknown types.
                console.warn(
                    `[image-annotation] addAnnotation: unsupported type "${obj.type}"`);
                return false;
            }
            this.canvas.renderAll();
        }

        this._saveState();
        this._updateAnnotationData();
        return true;
    }

    /**
     * Hide or show annotations by label.
     *
     * Called by the shared LabelVisibilityManager, which owns the state; this
     * only knows how to hide *image* artifacts. Masks are not fabric objects,
     * so they need the second half — the recurring lesson of this file.
     *
     * Visibility is presentation only: hidden annotations stay in
     * `_serializeAnnotations()` output. Hiding a class must never delete work.
     *
     * @param {Set<string>} hidden - Label names to hide
     */
    applyLabelVisibility(hidden) {
        this._hiddenLabels = hidden || new Set();

        this.canvas.getObjects().forEach(obj => {
            if (!obj.annotationData) return;
            const hide = this._hiddenLabels.has(obj.annotationData.label);
            obj.visible = !hide;
            // A hidden object must not be selectable either, or the annotator
            // can drag or delete something they cannot see.
            obj.selectable = !hide;
            obj.evented = !hide;
        });

        // Deselect if the active object just became invisible.
        const active = this.canvas.getActiveObject();
        if (active && active.annotationData &&
            this._hiddenLabels.has(active.annotationData.label)) {
            this.canvas.discardActiveObject();
        }

        this.canvas.renderAll();
        this._renderAllMasks();
    }

    /**
     * Copy annotations from the previous image in this user's queue.
     *
     * V7 calls this carry-over. It is the difference between redrawing twenty
     * boxes per frame and nudging them, on exactly the sequences where image
     * annotation is most tedious: video frames, satellite time series,
     * microscopy z-stacks.
     *
     * Every object is added through addAnnotation(), so the client contract is
     * enforced on this path too and masks/shapes behave identically to drawing
     * them by hand.
     *
     * @param {boolean} replace - Clear current annotations first
     * @returns {Promise<{added: number, skipped: number, reason?: string}>}
     */
    async copyFromPrevious(replace = false) {
        let payload;
        try {
            const res = await fetch(
                `/api/image_annotations/previous?schema=${encodeURIComponent(this.config.schemaName)}`,
                {credentials: 'same-origin'});
            if (!res.ok) {
                return {added: 0, skipped: 0, reason: `http_${res.status}`};
            }
            payload = await res.json();
        } catch (err) {
            console.warn('[image-annotation] copy-from-previous failed:', err);
            return {added: 0, skipped: 0, reason: 'network_error'};
        }

        const objects = (payload && payload.objects) || [];
        if (!objects.length) {
            return {added: 0, skipped: 0, reason: payload.reason || 'empty'};
        }

        if (replace) this.clearAnnotations();

        let added = 0, skipped = 0;
        objects.forEach(obj => {
            // Copied masks would collide with any mask of the same label
            // already painted here, so replace only when asked.
            if (this.addAnnotation(obj)) added++; else skipped++;
        });

        this._announce(added
            ? `Copied ${added} annotation${added === 1 ? '' : 's'} from the previous image`
            : 'Nothing to copy from the previous image');

        return {added, skipped, sourceInstance: payload.instance_id};
    }

    /**
     * Announce a message to assistive tech via the toolbar's live region.
     *
     * The canvas is invisible to a screen reader, so an action that only
     * changes pixels is otherwise silent.
     */
    _announce(message) {
        const container = document.querySelector(
            `.image-annotation-container[data-schema="${this.config.schemaName}"]`);
        if (!container) return;
        let region = container.querySelector('.annotation-announcer');
        if (!region) {
            region = document.createElement('div');
            region.className = 'annotation-announcer visually-hidden';
            region.setAttribute('role', 'status');
            region.setAttribute('aria-live', 'polite');
            container.appendChild(region);
        }
        region.textContent = message;
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

        // Re-render masks to match new viewport
        this._renderAllMasks();
        this._telemetry('zoom', { value: Math.round(zoom * 100) });
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

        // Re-render masks to match new viewport
        this._renderAllMasks();
        this._telemetry('zoom', { value: Math.round(scale * 100) });
    }

    /**
     * Reset zoom to 100%.
     */
    zoomReset() {
        if (!this.canvas) return;
        this.canvas.setViewportTransform([1, 0, 0, 1, 0, 0]);

        // Re-render masks to match new viewport
        this._renderAllMasks();
        this._telemetry('zoom', { value: 100 });
    }

    /**
     * Undo the last action.
     */
    undo() {
        if (this.historyIndex > 0) {
            this.historyIndex--;
            this._telemetry('undo');
            this._restoreState(this.history[this.historyIndex]);
        }
    }

    /**
     * Redo the last undone action.
     */
    redo() {
        if (this.historyIndex < this.history.length - 1) {
            this.historyIndex++;
            this._telemetry('redo');
            this._restoreState(this.history[this.historyIndex]);
        }
    }

    /**
     * Report one interaction to the telemetry tracker, if it is loaded.
     *
     * Fire-and-forget by design: `recordAnnotationTelemetry` dispatches a
     * CustomEvent nobody may be listening to. Measurement must never be able to
     * break drawing.
     */
    _telemetry(action, detail) {
        if (typeof window.recordAnnotationTelemetry !== 'function') return;
        window.recordAnnotationTelemetry(
            this.config.schemaName, action, detail || {});
    }

    /**
     * Count a serialized state by geometry kind, keeping the parsed objects so
     * the caller can read vertex counts off the ones that were added.
     */
    _telemetryCounts(stateJson) {
        const counts = {};
        const items = [];
        try {
            const parsed = JSON.parse(stateJson || '[]');
            (Array.isArray(parsed) ? parsed : []).forEach((a) => {
                const kind = (a && a.type) || 'unknown';
                counts[kind] = (counts[kind] || 0) + 1;
                items.push(a);
            });
        } catch (e) {
            // A malformed state reports nothing rather than throwing inside the
            // save path, which would lose the annotation itself.
        }
        return { counts: counts, items: items };
    }

    /** Vertices in a committed shape, per the client coordinate contract. */
    _telemetryVertices(ann) {
        const c = ann && ann.coordinates;
        if (Array.isArray(c)) return c.length;
        if (c && typeof c === 'object') {
            if (Array.isArray(c.front) || Array.isArray(c.back)) {
                return (c.front || []).length + (c.back || []).length;
            }
            // A bbox or ellipse is stored as extents but encloses four corners.
            return 4;
        }
        // Masks carry RLE, not coordinates, and have no vertices at all.
        return 0;
    }

    /**
     * Emit shape_add / shape_remove by diffing two serialized states.
     *
     * Diffing rather than instrumenting each commit site is what keeps this
     * correct as tools are added: `_finishBbox`, `_completePolygon`,
     * `_completeKeypointSet`, `_handleFreeformPath`, `addAnnotation` and the
     * SAM accept path all end in `_saveState`, and a twelfth tool added later
     * is covered without touching this file.
     */
    _emitStateDelta(prevJson, nextJson) {
        const before = this._telemetryCounts(prevJson).counts;
        const after = this._telemetryCounts(nextJson);

        const kinds = {};
        Object.keys(before).forEach((k) => { kinds[k] = true; });
        Object.keys(after.counts).forEach((k) => { kinds[k] = true; });

        Object.keys(kinds).forEach((kind) => {
            const delta = (after.counts[kind] || 0) - (before[kind] || 0);
            if (delta > 0) {
                const added = after.items
                    .filter((a) => ((a && a.type) || 'unknown') === kind)
                    .slice(-delta);
                added.forEach((a) => this._telemetry('shape_add', {
                    shape: kind,
                    value: this._telemetryVertices(a),
                }));
            } else if (delta < 0) {
                for (let i = 0; i < -delta; i++) {
                    this._telemetry('shape_remove', { shape: kind });
                }
            }
        });
    }

    /**
     * Save current state to history.
     */
    _saveState() {
        // Read before the slice: `historyIndex` is -1 on the very first save,
        // which is the baseline and must not be reported as work.
        const previous = this.historyIndex >= 0
            ? this.history[this.historyIndex] : null;

        // Remove future history if we're not at the end
        this.history = this.history.slice(0, this.historyIndex + 1);

        // Save current state
        const state = this._serializeAnnotations();
        if (previous !== null && !this._hydrating) {
            this._emitStateDelta(previous, state);
        }
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

        // Masks are NOT fabric objects — they live in `this.masks` and paint to
        // their own canvas — so clearing the fabric canvas leaves them behind.
        // Without this reset, _deserializeAnnotations only ever *overwrites*
        // mask entries present in the restored state, so undo could shrink a
        // stroke but never remove one: a label absent from the target state was
        // simply never written back, and its buffer survived untouched.
        this.masks = {};

        // Restore annotations
        this._deserializeAnnotations(state);

        // _deserializeAnnotations only repaints when the state CONTAINED a mask.
        // Undoing back to a mask-free state has nothing to restore, so repaint
        // here or the cleared strokes stay on screen.
        this._renderAllMasks();
        this._showMaskCanvas(this._hasMasks() && this.currentTool !== 'freeform');

        this._updateAnnotationData();
    }

    /**
     * The annotations in serialization order, each with a handle to what
     * produced it.
     *
     * Exists because a stored annotation's INDEX is its only identity — there
     * are no ids — so anything that reports on annotation N and then wants to
     * act on it (the VLM critique review queue, today) must walk the list in
     * exactly the order `_serializeAnnotations` did. Deriving both from this
     * one method makes that drift impossible; two independent loops over
     * `getObjects()` then `this.masks` would agree right up until someone
     * reordered one of them.
     *
     * @returns {Array<{index:number, kind:'object'|'mask', label:string,
     *                  type:string, object?:Object, maskKey?:string}>}
     */
    getAnnotationHandles() {
        const handles = [];

        this.canvas.getObjects().forEach(obj => {
            if (!obj.annotationData) return;
            handles.push({
                index: handles.length,
                kind: 'object',
                label: obj.annotationData.label,
                type: obj.annotationData.type,
                object: obj,
            });
        });

        for (const key in this.masks) {
            const mask = this.masks[key];
            // `hasAny()`, not merely "a mask object exists": a mousedown that
            // misses the image allocates a mask and paints nothing, and the
            // serializer drops those. Counting one here would shift the index
            // of every annotation after it — and an index IS the identity.
            if (!mask || !mask.buffer || !mask.buffer.hasAny()) continue;
            handles.push({
                index: handles.length,
                kind: 'mask',
                label: mask.label !== undefined ? mask.label : key,
                type: 'mask',
                maskKey: key,
            });
        }

        return handles;
    }

    /**
     * The configured colour for a label name, or null if it is not a label of
     * this schema.
     */
    colorForLabel(name) {
        for (const label of (this.config.labels || [])) {
            const labelName = (label && label.name !== undefined) ? label.name : label;
            if (labelName === name) {
                return (label && label.color) || null;
            }
        }
        return null;
    }

    /**
     * Select and scroll to annotation N, so a report about it can point at it.
     *
     * Masks are not fabric objects and cannot be selected, so for those this
     * makes the label visible (in case it was hidden) and returns false —
     * the caller shows "this is a mask" rather than a selection that silently
     * did nothing.
     *
     * @returns {boolean} whether a selectable object was focused
     */
    focusAnnotation(index) {
        const handle = this.getAnnotationHandles()[index];
        if (!handle) return false;

        // A hidden class cannot be reviewed. Un-hiding is the least surprising
        // response to "show me this one" — the alternative is a Show button
        // that appears to do nothing.
        if (this.labelVisibility && this._hiddenLabels &&
            this._hiddenLabels.has(handle.label)) {
            this.labelVisibility.setVisible(handle.label, true);
        }

        if (handle.kind !== 'object' || !handle.object) return false;

        this.canvas.setActiveObject(handle.object);
        this.canvas.requestRenderAll();
        if (this.container && this.container.scrollIntoView) {
            this.container.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        }
        return true;
    }

    /**
     * Change annotation N's label, keeping its geometry.
     *
     * The colour follows the label, because a shape that keeps the old class's
     * colour after a relabel reads as still being that class on every later
     * glance.
     *
     * @returns {boolean} whether the annotation was relabelled
     */
    relabelAnnotation(index, label) {
        const handle = this.getAnnotationHandles()[index];
        if (!handle || !label) return false;
        const color = this.colorForLabel(label);
        if (!color) return false;  // not a label of this schema

        if (handle.kind === 'mask') {
            const mask = this.masks[handle.maskKey];
            if (!mask) return false;
            // Re-key so the store stays keyed by the label it now carries;
            // leaving it under the old key would make the next brush stroke of
            // the old class extend this mask.
            const suffix = handle.maskKey.includes('#')
                ? '#' + handle.maskKey.split('#').slice(1).join('#') : '';
            const newKey = label + suffix;
            if (newKey !== handle.maskKey) {
                if (this.masks[newKey]) return false;  // would merge two masks
                delete this.masks[handle.maskKey];
                this.masks[newKey] = mask;
            }
            // No pixel work: the buffer stores occupancy only, and the colour
            // it renders in is read from `mask.color` at paint time. The old
            // dense buffer held the colour in every set pixel, so a relabel had
            // to rewrite the whole image.
            mask.label = label;
            mask.color = color;
            this._renderAllMasks();
        } else {
            const obj = handle.object;
            obj.annotationData.label = label;
            obj.annotationData.color = color;
            obj.set({ stroke: color });
            if (obj.fill && obj.fill !== 'transparent') {
                obj.set({ fill: color + '33' });
            }
            this.canvas.requestRenderAll();
        }

        this._saveState();
        this._updateAnnotationData();
        return true;
    }

    /**
     * Delete annotation N.
     *
     * @returns {boolean} whether it was deleted
     */
    deleteAnnotation(index) {
        const handle = this.getAnnotationHandles()[index];
        if (!handle) return false;

        if (handle.kind === 'mask') {
            delete this.masks[handle.maskKey];
            this._renderAllMasks();
        } else {
            this.canvas.discardActiveObject();
            this.canvas.remove(handle.object);
            this.canvas.requestRenderAll();
        }

        this._saveState();
        this._updateAnnotationData();
        return true;
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
                // A keypoint set is meaningless without knowing which skeleton
                // its ordering refers to.
                if (obj.annotationData.type === 'keypoint_set') {
                    ann.skeleton = obj.annotationData.skeleton || '';
                }
                if (obj.annotationData.type === 'polyline') {
                    ann.closed = false;
                }
                annotations.push(ann);
            }
        });

        // Masks go in the SAME blob as the shapes.
        //
        // They used to live in a separate `mask-data-input`, which carried neither
        // `annotation-input` nor `annotation-data-input` — no selector anywhere
        // collected it, so it was write-only and every brush stroke was lost on the
        // next navigation (a full page reload). Masks are not fabric objects (they
        // render to their own canvas), so canvas.getObjects() above never sees them.
        //
        // The shape is the one every exporter already reads — mask_exporter and
        // coco_exporter both want {type:"mask", label, rle:{counts, size:[h,w]}} —
        // rather than the {label: {color, rle:[...], width, height}} the client used
        // to write, which no exporter could consume.
        for (const key in this.masks) {
            const mask = this.masks[key];
            // An allocated-but-unpainted mask is not an annotation. It used to
            // be emitted as an all-background RLE — a phantom entry that
            // exported as a zero-area mask and that getAnnotationCount, which
            // has always tested for pixels, did not count.
            if (!mask || !mask.buffer || !mask.buffer.hasAny()) continue;
            const counts = mask.buffer.encodeRLE();
            const entry = {
                type: 'mask',
                // NOT the store key. An imported per-instance mask is keyed
                // "label#instance" so two instances of one class stay apart,
                // but it has to serialize under its real label.
                label: mask.label !== undefined ? mask.label : key,
                color: mask.color,
                rle: {
                    counts: counts,
                    size: [this.maskImgHeight, this.maskImgWidth],
                },
            };
            // Preserved so imported COCO instances survive save/reload and
            // export as N annotations rather than one merged blob.
            if (mask.instance !== undefined && mask.instance !== null) {
                entry.instance = mask.instance;
            }
            // Emitted whenever it is known, INCLUDING 0. A mask with no
            // iscrowd defaults to 1 on export (a label-keyed brush mask really
            // is a crowd region), so dropping an explicit 0 here would quietly
            // turn imported instances back into one merged blob.
            if (mask.iscrowd !== undefined && mask.iscrowd !== null) {
                entry.iscrowd = mask.iscrowd;
            }
            annotations.push(entry);
        }

        return JSON.stringify(annotations);
    }

    /**
     * Deserialize annotations from JSON and add to canvas.
     */
    _deserializeAnnotations(json) {
        const annotations = JSON.parse(json);
        let restoredMask = false;

        annotations.forEach(ann => {
            if (ann && ann.type === 'mask') {
                // Masks are not fabric objects — rebuild them into this.masks and
                // repaint the mask canvas rather than handing them to the shape
                // factory, which would silently drop them.
                this._restoreMaskFromEntry(ann);
                restoredMask = true;
                return;
            }
            this._createAnnotationObject(ann);
        });

        if (restoredMask) {
            // setTool() ran during init, before any masks existed, so
            // _showMaskCanvas(this._hasMasks()) hid the overlay. Without
            // re-showing it here, restored masks are painted onto a
            // display:none canvas — the pixels are there, nothing is visible.
            // Freeform deliberately hides the overlay, so leave that alone.
            if (this.currentTool !== 'freeform') {
                this._showMaskCanvas(true);
            }
            this._renderAllMasks();
        }
        this.canvas.renderAll();
    }

    /**
     * Rebuild one {type:"mask", label, rle:{counts,size}} entry into this.masks.
     */
    _restoreMaskFromEntry(ann) {
        const rle = ann.rle || {};
        const counts = rle.counts || [];
        const size = rle.size || [];
        if (!counts.length || size.length !== 2) return;

        const height = size[0];
        const width = size[1];
        let buffer = MaskBuffer.fromRLE(counts, width, height);

        // The mask buffers and the mask canvas must agree on resolution. They
        // normally do — COCO's images[].width/height is the natural size, which
        // is what the canvas is sized from — but a resized or thumbnailed
        // image_url makes them disagree, and an RLE at the wrong resolution
        // paints as diagonal garbage with no error at all. Rescale instead.
        if (this.maskImgWidth && this.maskImgHeight &&
            (this.maskImgWidth !== width || this.maskImgHeight !== height)) {
            console.warn(
                `[image-annotation] mask for "${ann.label}" is ${width}x${height} ` +
                `but the canvas is ${this.maskImgWidth}x${this.maskImgHeight}; ` +
                `rescaling. Check that the image served matches the size the ` +
                `annotations were made against.`);
            buffer = buffer.rescale(this.maskImgWidth, this.maskImgHeight);
        } else {
            // Keep the stored dimensions so a re-save round-trips the same
            // rle.size even if nothing is redrawn.
            this.maskImgWidth = this.maskImgWidth || width;
            this.maskImgHeight = this.maskImgHeight || height;
        }

        // Per-instance masks are keyed "label#instance" so that N imported
        // instances of one class do not collapse into a single blob. Brush
        // strokes always target the bare label key, so painting edits the
        // label-level mask and leaves imported instances intact.
        const key = (ann.instance !== undefined && ann.instance !== null)
            ? `${ann.label}#${ann.instance}`
            : ann.label;

        this.masks[key] = {
            label: ann.label,
            color: ann.color,
            buffer: buffer,
        };
        if (ann.instance !== undefined && ann.instance !== null) {
            this.masks[key].instance = ann.instance;
        }
        if (ann.iscrowd !== undefined && ann.iscrowd !== null) {
            this.masks[key].iscrowd = ann.iscrowd;
        }
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

            case 'keypoint_set': {
                // Read from annotationData, not from the fabric Group. A Group
                // holds lines and circles in draw order and omits unlabelled
                // points entirely, so it cannot be reduced back to an ordered
                // keypoint list — and the ordering IS the annotation.
                //
                // The group's transform is applied so dragging the whole
                // skeleton moves the stored points with it.
                const kps = (obj.annotationData.keypoints) || [];
                const matrix = obj.calcTransformMatrix
                    ? obj.calcTransformMatrix() : null;
                return kps.map(p => {
                    let x = p.x;
                    let y = p.y;
                    if (matrix && obj.pathOffset) {
                        const local = new fabric.Point(
                            p.x - obj.pathOffset.x, p.y - obj.pathOffset.y);
                        const abs = fabric.util.transformPoint(local, matrix);
                        x = abs.x;
                        y = abs.y;
                    }
                    const n = normalize(x, y);
                    return { x: n.x, y: n.y, v: p.v };
                });
            }

            case 'cuboid_2d': {
                const d = obj.annotationData;
                return {
                    front: (d.front || []).map(p => normalize(p.x, p.y)),
                    back: (d.back || []).map(p => normalize(p.x, p.y)),
                };
            }

            case 'ellipse': {
                // Stored parametrically rather than as vertices: an ellipse is
                // exact in {cx, cy, rx, ry, angle} and only approximate as a
                // point list, and re-approximating on every save would let the
                // shape drift a little each time it was reloaded.
                //
                // getCenterPoint() rather than arithmetic on obj.left: a
                // freshly drawn ellipse has originX 'left' (so it can be
                // resized by dragging a corner) while a restored one has
                // 'center' (so rotation pivots correctly). Deriving the centre
                // as `left + rx` is therefore right for one and wrong for the
                // other — the shape would jump by its own radius on the first
                // save after a reload. fabric's accessor is origin-agnostic.
                const centrePoint = obj.getCenterPoint();
                const centre = normalize(centrePoint.x, centrePoint.y);
                return {
                    cx: centre.x,
                    cy: centre.y,
                    rx: (obj.rx * obj.scaleX) / imgWidth,
                    ry: (obj.ry * obj.scaleY) / imgHeight,
                    angle: obj.angle || 0,
                };
            }

            case 'polyline':
            case 'polygon': {
                // `obj.left/top` is the bounding box's top-left, but fabric's
                // `points` stay in their own space and `pathOffset` is the
                // box CENTRE — so `left + p.x - pathOffset.x` shifts every
                // vertex by half the polygon's size. Sizes came out right and
                // positions did not, which is why it survived: the exported
                // bbox had the correct width and height in the wrong place.
                //
                // calcTransformMatrix() is fabric's own answer and also
                // handles scaling and rotation, which the old arithmetic
                // silently ignored after any resize.
                const matrix = obj.calcTransformMatrix();
                return obj.points.map(p => {
                    const local = new fabric.Point(
                        p.x - obj.pathOffset.x, p.y - obj.pathOffset.y);
                    const abs = fabric.util.transformPoint(local, matrix);
                    return normalize(abs.x, abs.y);
                });
            }

            case 'landmark':
                if (obj.type === 'group') {
                    const centerX = obj.left + obj.width / 2;
                    const centerY = obj.top + obj.height / 2;
                    return normalize(centerX, centerY);
                }
                return normalize(obj.left + 8, obj.top + 8);

            case 'freeform':
                // Serialize path data.
                //
                // pathOffset is fabric's own origin for the path's point space
                // (the bounding-box centre). Dropping it forced
                // cv_utils._freeform_points to GUESS the origin by anchoring
                // the path's minimum corner at (left, top), which is only right
                // for an unrotated, unscaled brush stroke — and it emitted a
                // warning saying so. Recording it makes the Python side exact.
                return {
                    path: obj.path,
                    left: (obj.left - imgLeft) / imgWidth,
                    top: (obj.top - imgTop) / imgHeight,
                    scaleX: obj.scaleX / (imgWidth / this.image.width),
                    scaleY: obj.scaleY / (imgHeight / this.image.height),
                    pathOffset: obj.pathOffset
                        ? { x: obj.pathOffset.x, y: obj.pathOffset.y }
                        : null,
                    angle: obj.angle || 0,
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

            case 'polyline':
            case 'polygon': {
                const isLine = ann.type === 'polyline';
                const points = ann.coordinates.map(c => {
                    const p = denormalize(c.x, c.y);
                    return { x: p.x, y: p.y };
                });
                const Shape = isLine ? fabric.Polyline : fabric.Polygon;
                obj = new Shape(points, {
                    fill: isLine ? '' : this._colorWithAlpha(ann.color, 0.2),
                    stroke: ann.color,
                    strokeWidth: 2,
                    selectable: true,
                    hasControls: true,
                    perPixelTargetFind: isLine,
                    targetFindTolerance: isLine ? 8 : 0,
                });
                break;
            }

            case 'keypoint_set': {
                const kps = (ann.coordinates || []).map(p => ({
                    x: p.x * imgWidth + imgLeft,
                    y: p.y * imgHeight + imgTop,
                    v: p.v === undefined ? 2 : p.v,
                }));
                const skel = (this.config.skeletons || {})[ann.skeleton] || {};
                const parts = [];
                (skel.edges || []).forEach(([from, to]) => {
                    const a = kps[from];
                    const b = kps[to];
                    if (!a || !b || !a.v || !b.v) return;
                    parts.push(new fabric.Line([a.x, a.y, b.x, b.y], {
                        stroke: ann.color, strokeWidth: 2,
                    }));
                });
                kps.forEach(p => {
                    if (!p.v) return;
                    parts.push(new fabric.Circle({
                        left: p.x - 5, top: p.y - 5, radius: 5,
                        fill: p.v === 1 ? '#ffffff' : ann.color,
                        stroke: ann.color, strokeWidth: 2,
                    }));
                });
                if (!parts.length) return;
                obj = new fabric.Group(parts, {
                    selectable: true, hasControls: true,
                });
                // Carried through so the serializer can rebuild the ordered
                // list; the Group itself cannot supply it.
                obj.annotationData = {
                    type: 'keypoint_set',
                    label: ann.label,
                    color: ann.color,
                    skeleton: ann.skeleton || '',
                    keypoints: kps,
                };
                this.canvas.add(obj);
                return;
            }

            case 'cuboid_2d': {
                const c = ann.coordinates || {};
                const den = pts => (pts || []).map(p => ({
                    x: p.x * imgWidth + imgLeft, y: p.y * imgHeight + imgTop,
                }));
                const front = den(c.front);
                const back = den(c.back);
                if (front.length !== 4 || back.length !== 4) return;
                const parts = [
                    new fabric.Polygon(front, {
                        fill: this._colorWithAlpha(ann.color, 0.2),
                        stroke: ann.color, strokeWidth: 2,
                    }),
                    new fabric.Polygon(back, {
                        fill: '', stroke: ann.color, strokeWidth: 1,
                        strokeDashArray: [4, 3],
                    }),
                ];
                front.forEach((p, i) => parts.push(new fabric.Line(
                    [p.x, p.y, back[i].x, back[i].y],
                    { stroke: ann.color, strokeWidth: 1 })));
                obj = new fabric.Group(parts, {
                    selectable: true, hasControls: true,
                });
                obj.annotationData = {
                    type: 'cuboid_2d', label: ann.label, color: ann.color,
                    front: front, back: back,
                };
                this.canvas.add(obj);
                return;
            }

            case 'ellipse': {
                const c = ann.coordinates || {};
                const rx = (c.rx || 0) * imgWidth;
                const ry = (c.ry || 0) * imgHeight;
                const centre = denormalize(c.cx || 0, c.cy || 0);
                obj = new fabric.Ellipse({
                    // Restored with a CENTRE origin so the stored centre needs
                    // no arithmetic to place, and so rotation pivots correctly.
                    left: centre.x,
                    top: centre.y,
                    originX: 'center',
                    originY: 'center',
                    rx: rx,
                    ry: ry,
                    angle: c.angle || 0,
                    fill: this._colorWithAlpha(ann.color, 0.2),
                    stroke: ann.color,
                    strokeWidth: 2,
                    selectable: true,
                    hasControls: true,
                });
                break;
            }

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

        if (this.onAnnotationChange) {
            this.onAnnotationChange(this.getAnnotationCount());
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
                this._updateAnnotationData();  // Update count display after loading
            } catch (e) {
                console.warn('Failed to load existing annotations:', e);
            }
        } else {
            // No existing annotations - still update count to show 0
            this._updateAnnotationData();
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
     * Show a message on the canvas (for errors/loading states).
     * @param {string} message - Message to display
     */
    _showCanvasMessage(message) {
        if (!this.canvas) return;

        // Clear canvas and show message
        this.canvas.clear();
        this.canvas.setBackgroundColor('#f8f9fa', this.canvas.renderAll.bind(this.canvas));

        const text = new fabric.Text(message, {
            left: this.canvas.getWidth() / 2,
            top: this.canvas.getHeight() / 2,
            fontSize: 16,
            fill: '#dc3545',
            fontFamily: 'system-ui, -apple-system, sans-serif',
            originX: 'center',
            originY: 'center',
            textAlign: 'center',
            selectable: false,
            evented: false,
        });

        this.canvas.add(text);
        this.canvas.renderAll();
    }

    /**
     * Get current annotation count.
     *
     * Counts masks as well as shapes, matching what _serializeAnnotations
     * actually writes (one entry per mask key). Counting fabric objects alone
     * reported 0 for a mask-only image, so the count display read "0
     * annotations" over visible paint and any min_annotations rule rejected a
     * fully segmented image.
     */
    getAnnotationCount() {
        const shapes = this.canvas.getObjects().filter(
            obj => obj !== this.image && obj.annotationData
        ).length;

        let masks = 0;
        for (const key in this.masks) {
            const mask = this.masks[key];
            // Match the serializer: an unpainted buffer is not an annotation.
            // `hasAny()` reads a maintained counter. The old form scanned the
            // whole dense buffer for a set alpha byte, and it ran on every
            // stroke via _updateAnnotationData.
            if (mask && mask.buffer && mask.buffer.hasAny()) {
                masks++;
            }
        }

        return shapes + masks;
    }

    /**
     * Clear all annotations from the canvas.
     * Used when switching to a new instance.
     */
    clearAnnotations() {
        // Iterate a COPY. fabric's getObjects() hands back its live internal
        // array and remove() splices that same array, so forEach over it skips
        // every other element -- clearing [box, box, box] left the second one
        // behind, and this runs on every instance switch, so that leftover was
        // then attributed to the next image.
        const objects = this.canvas.getObjects().slice();
        objects.forEach(obj => {
            if (obj !== this.image && obj.annotationData) {
                this.canvas.remove(obj);
            }
        });
        this.canvas.renderAll();

        // Masks live outside the fabric canvas, so the loop above cannot reach
        // them. This method is what annotation.js calls on every instance
        // switch (clearAllFormInputs -> clearAnnotations); leaving `this.masks`
        // populated carried the previous image's brush strokes into the next
        // one and re-serialized them into its hidden input, silently attaching
        // one annotator's mask to an image they never painted.
        this.masks = {};
        // The composite is keyed on which masks are visible in which colour, and
        // the NEXT image can easily produce the same key (same class, same
        // colour). Without dropping the signature, that match would skip the
        // full repaint and leave the previous image's pixels on screen — the
        // same class of cross-instance leak as the mask store itself.
        this._compositeSignature = null;
        // Same reasoning for the instance counter: a stale index would attach
        // the next image's first stroke to the previous image's numbering, so
        // its objects would start at 4 and the first three would never exist.
        this.activeInstance = null;
        this.polygonPoints = [];
        this.keypointPoints = [];
        this.cuboidFront = null;
        // The in-progress SAM preview is the same class of non-fabric state:
        // left set, an unaccepted mask from the previous image would paint
        // over the next one, and accepting it would attach it to the wrong
        // item. The tool's own prompt is cleared alongside it.
        this._segmentationPreview = null;
        if (this.samTool) this.samTool.clear();
        this._renderAllMasks();
        this._showMaskCanvas(false);

        // Reset history
        this.history = [];
        this.historyIndex = -1;

        // Update the hidden input and count display
        this._updateAnnotationData();
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
        // Restoring stored work is not the annotator drawing it. The empty
        // history in _loadExistingAnnotations already covers first load; this
        // flag covers a restore into a session that has history, which would
        // otherwise report every restored shape as freshly created in 0ms.
        this._hydrating = true;
        try {
            this._deserializeAnnotations(json);
            this._saveState();
        } finally {
            this._hydrating = false;
        }
        this._updateAnnotationData();
    }

    // ------------------------------------------------------------------
    // Interactive segmentation
    // ------------------------------------------------------------------

    /**
     * Bring up the magic wand, fetching the runtime on FIRST USE only.
     *
     * The ONNX runtime is 13.5 MB. Loading it when the page loads would make
     * every image project pay for a tool most of them never touch, so nothing
     * is fetched until someone actually selects the wand — which is also the
     * first moment there is a sensible place to show progress.
     */
    async ensureSegmentation() {
        const config = this.config.segmentation;
        if (!config) return false;
        if (this.samTool && this.samTool.session.isReady()) return true;

        if (!this.samTool) {
            if (typeof SAMSession === 'undefined' || typeof SAMTool === 'undefined') {
                this._segmentationStatus(
                    'Interactive segmentation did not load on this page.',
                    'error');
                return false;
            }
            const session = new SAMSession({
                model: config.model,
                modelBaseUrl: config.modelBaseUrl,
                embeddingLimit: config.embeddingLimit,
            });
            this.samTool = new SAMTool({
                session: session,
                manager: this,
                onStatus: (message, kind) => this._segmentationStatus(message, kind),
            });
        }

        if (!(await this._loadOnnxRuntime(config))) return false;
        this.samTool.session.runtime = window.ort;

        const ready = await this.samTool.session.load();
        if (!ready) {
            this._segmentationStatus(this.samTool.session.statusMessage(), 'error');
            return false;
        }
        return this._encodeCurrentImage();
    }

    /**
     * Inject the ONNX runtime script once.
     *
     * `ort.env.wasm.numThreads = 1` is not a performance choice: multi-threaded
     * wasm needs SharedArrayBuffer, which needs COOP/COEP response headers that
     * Potato does not set. Left at the default, the runtime tries to spawn
     * workers and fails with a cross-origin-isolation error that says nothing
     * about headers.
     */
    async _loadOnnxRuntime(config) {
        if (window.ort) return true;
        if (this._ortLoading) return this._ortLoading;

        this._segmentationStatus('Loading the segmentation runtime (13 MB, '
                               + 'once per session)…', 'busy');

        this._ortLoading = new Promise((resolve) => {
            const script = document.createElement('script');
            script.src = config.runtimeUrl;
            script.onload = () => {
                if (window.ort && window.ort.env && window.ort.env.wasm) {
                    window.ort.env.wasm.wasmPaths = config.wasmBaseUrl;
                    window.ort.env.wasm.numThreads = 1;
                }
                resolve(!!window.ort);
            };
            script.onerror = () => {
                this._segmentationStatus(
                    'The segmentation runtime is not installed. An '
                    + 'administrator can add it with:  '
                    + 'potato download-models onnxruntime', 'error');
                resolve(false);
            };
            document.head.appendChild(script);
        });
        return this._ortLoading;
    }

    /** Encode whatever image is currently loaded. */
    async _encodeCurrentImage() {
        if (!this.samTool || !this.image) return false;
        const element = this.image.getElement ? this.image.getElement() : null;
        if (!element) return false;
        const key = element.currentSrc || element.src || 'image';
        return this.samTool.prepare(
            key, element, this.image.width, this.image.height);
    }

    /** Accept the pending mask. Bound to Enter by the schema's key handler. */
    acceptSegmentation() {
        if (!this.samTool || !this.samTool.hasPreview()) return null;
        const sid = `sam-${this._segmentationId || 0}`;
        const added = this.samTool.accept(this.currentLabel);
        if (added) {
            this._telemetry('ai_accept', { shape: 'mask', meta: { sid: sid } });
            this._saveState();
        }
        return added;
    }

    /** Discard the pending mask without committing it. */
    cancelSegmentation() {
        // Only a preview that existed can be rejected; clearing an empty tool
        // is a no-op and must not count against the acceptance rate.
        if (this._segmentationPreview) {
            this._telemetry('ai_reject', {
                shape: 'mask',
                meta: { sid: `sam-${this._segmentationId || 0}` },
            });
        }
        if (this.samTool) this.samTool.clear();
    }

    _segmentationStatus(message, kind) {
        // Scoped by schema, the way every other DOM lookup in this class is.
        // `this.container` does not exist -- an earlier version used it and the
        // status line was silently never written, so the model download, the
        // "nothing found there" message and every error state were invisible
        // while the unit tests passed against the callback.
        const container = document.querySelector(
            `.image-annotation-container[data-schema="${this.config.schemaName}"]`);
        const el = container
            ? container.querySelector('.segmentation-status') : null;
        if (el) {
            el.textContent = message;
            el.dataset.kind = kind || 'info';
        }
        if (this.onSegmentationStatus) this.onSegmentationStatus(message, kind);
    }
}

// Export for use in modules if needed
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ImageAnnotationManager;
}

// Make available in browser environments
if (typeof window !== 'undefined') {
    window.ImageAnnotationManager = ImageAnnotationManager;
}

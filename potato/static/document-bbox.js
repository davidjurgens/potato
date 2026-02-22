/**
 * Document Bounding Box Annotation
 *
 * Provides bounding box drawing and management for HTML/document displays.
 * Works with rendered HTML content and captures bbox coordinates.
 */

(function() {
    'use strict';

    // Store all bounding boxes by field key
    const boundingBoxes = {};
    let selectedBox = null;
    let currentMode = 'draw'; // 'draw' or 'select'
    let isDrawing = false;
    let isResizing = false;
    let resizeHandle = null; // 'nw', 'ne', 'sw', 'se'
    let drawStart = null;
    let resizeStart = null;
    let currentContainer = null;
    const HANDLE_SIZE = 8;

    // Color palette for labels - distinct, visually appealing colors
    const LABEL_COLORS = [
        '#e74c3c', // Red
        '#3498db', // Blue
        '#2ecc71', // Green
        '#9b59b6', // Purple
        '#f39c12', // Orange
        '#1abc9c', // Teal
        '#e91e63', // Pink
        '#00bcd4', // Cyan
        '#ff5722', // Deep Orange
        '#607d8b', // Blue Grey
        '#8bc34a', // Light Green
        '#673ab7', // Deep Purple
    ];

    // Cache for label-to-color mapping
    const labelColorCache = {};

    /**
     * Get a consistent color for a label.
     * Uses hash-based assignment so the same label always gets the same color.
     */
    function getLabelColor(label) {
        if (!label) return '#0066cc'; // Default blue for unlabeled

        // Return cached color if available
        if (labelColorCache[label]) {
            return labelColorCache[label];
        }

        // Generate hash from label string
        let hash = 0;
        for (let i = 0; i < label.length; i++) {
            const char = label.charCodeAt(i);
            hash = ((hash << 5) - hash) + char;
            hash = hash & hash; // Convert to 32-bit integer
        }

        // Use absolute value and modulo to get index
        const colorIndex = Math.abs(hash) % LABEL_COLORS.length;
        const color = LABEL_COLORS[colorIndex];

        // Cache and return
        labelColorCache[label] = color;
        return color;
    }

    /**
     * Convert hex color to RGBA with specified alpha.
     */
    function hexToRgba(hex, alpha) {
        const r = parseInt(hex.slice(1, 3), 16);
        const g = parseInt(hex.slice(3, 5), 16);
        const b = parseInt(hex.slice(5, 7), 16);
        return `rgba(${r}, ${g}, ${b}, ${alpha})`;
    }

    /**
     * Get the currently selected label from the annotation scheme.
     */
    function getCurrentSelectedLabel() {
        // Check for selected radio button
        const selectedRadio = document.querySelector('input[type="radio"]:checked');
        if (selectedRadio) {
            return selectedRadio.value || selectedRadio.getAttribute('data-label') || selectedRadio.getAttribute('data-name');
        }
        return null;
    }

    /**
     * Initialize bounding box annotation for all document displays in bbox mode.
     */
    function initDocumentBoundingBoxes() {
        const displays = document.querySelectorAll('.document-display[data-annotation-mode="bounding_box"]');
        displays.forEach(initDisplay);
    }

    /**
     * Initialize a single document display for bbox annotation.
     */
    function initDisplay(container) {
        currentContainer = container;
        const fieldKey = container.getAttribute('data-field-key');
        const minSize = parseInt(container.getAttribute('data-bbox-min-size') || '10', 10);
        const showLabels = container.getAttribute('data-show-bbox-labels') !== 'false';

        // Initialize bbox storage
        if (!boundingBoxes[fieldKey]) {
            boundingBoxes[fieldKey] = [];
        }

        // Set up canvas for drawing
        const bboxCanvas = container.querySelector('.document-bbox-canvas');
        const contentEl = container.querySelector('.document-bbox-content');

        if (bboxCanvas && contentEl) {
            initDrawingCanvas(bboxCanvas, contentEl, container, minSize, showLabels);
        }

        // Set up tool buttons
        initToolButtons(container);

        // Load any existing annotations
        loadExistingAnnotations(container, fieldKey);

        // Handle resize
        const resizeObserver = new ResizeObserver(() => {
            syncCanvasSize(container);
        });
        resizeObserver.observe(contentEl);
    }

    /**
     * Get the resize handle at a given point for the selected box.
     * Returns 'nw', 'ne', 'sw', 'se' or null.
     */
    function getResizeHandleAtPoint(point, box, canvas) {
        if (!box) return null;

        const pixelBbox = box.bbox_pixels || [
            box.bbox[0] * canvas.width,
            box.bbox[1] * canvas.height,
            box.bbox[2] * canvas.width,
            box.bbox[3] * canvas.height
        ];

        const [x, y, w, h] = pixelBbox;
        const handles = {
            'nw': { x: x, y: y },
            'ne': { x: x + w, y: y },
            'sw': { x: x, y: y + h },
            'se': { x: x + w, y: y + h }
        };

        for (const [handle, pos] of Object.entries(handles)) {
            if (Math.abs(point.x - pos.x) <= HANDLE_SIZE &&
                Math.abs(point.y - pos.y) <= HANDLE_SIZE) {
                return handle;
            }
        }

        return null;
    }

    /**
     * Update cursor based on position over handles.
     */
    function updateCursor(canvas, point, box) {
        const handle = getResizeHandleAtPoint(point, box, canvas);
        if (handle) {
            // Show resize cursor when over a handle
            if (handle === 'nw' || handle === 'se') {
                canvas.style.cursor = 'nwse-resize';
            } else {
                canvas.style.cursor = 'nesw-resize';
            }
        } else {
            // Default cursor based on mode
            canvas.style.cursor = currentMode === 'draw' ? 'crosshair' : 'pointer';
        }
    }

    /**
     * Initialize the drawing canvas for bounding boxes.
     */
    function initDrawingCanvas(canvas, contentEl, container, minSize, showLabels) {
        const ctx = canvas.getContext('2d');

        // Initial size sync
        syncCanvasSize(container);

        // Mouse events for drawing and resizing
        canvas.addEventListener('mousedown', function(e) {
            const rect = canvas.getBoundingClientRect();
            const mousePos = {
                x: e.clientX - rect.left,
                y: e.clientY - rect.top
            };

            // Check for resize handle first - allow in ANY mode if there's a selected box
            // This lets users resize immediately after drawing without switching modes
            if (selectedBox) {
                const handle = getResizeHandleAtPoint(mousePos, selectedBox, canvas);
                if (handle) {
                    isResizing = true;
                    resizeHandle = handle;
                    resizeStart = mousePos;
                    e.preventDefault();
                    return;
                }
            }

            // Draw mode - start drawing
            if (currentMode === 'draw') {
                isDrawing = true;
                drawStart = mousePos;
            }
        });

        canvas.addEventListener('mousemove', function(e) {
            const rect = canvas.getBoundingClientRect();
            const currentPos = {
                x: e.clientX - rect.left,
                y: e.clientY - rect.top
            };

            // Update cursor - show resize cursor when hovering over handles (any mode)
            if (selectedBox) {
                updateCursor(canvas, currentPos, selectedBox);
            } else if (currentMode === 'draw') {
                canvas.style.cursor = 'crosshair';
            } else {
                canvas.style.cursor = 'pointer';
            }

            // Handle resizing
            if (isResizing && selectedBox) {
                resizeSelectedBox(container, canvas, currentPos);
                return;
            }

            // Handle drawing
            if (isDrawing && currentMode === 'draw') {
                redrawCanvas(container);
                drawTemporaryRect(ctx, drawStart, currentPos);
            }
        });

        canvas.addEventListener('mouseup', function(e) {
            const rect = canvas.getBoundingClientRect();
            const endPos = {
                x: e.clientX - rect.left,
                y: e.clientY - rect.top
            };

            // Finish resizing
            if (isResizing) {
                isResizing = false;
                resizeHandle = null;
                resizeStart = null;
                // Update normalized bbox from pixel bbox
                if (selectedBox) {
                    updateNormalizedBbox(selectedBox, canvas);
                    triggerBoundingBoxEvent(container, 'document-bbox:resized', selectedBox);
                }
                redrawCanvas(container);
                return;
            }

            // Finish drawing
            if (isDrawing && currentMode === 'draw') {
                isDrawing = false;

                // Check minimum size
                const width = Math.abs(endPos.x - drawStart.x);
                const height = Math.abs(endPos.y - drawStart.y);

                if (width >= minSize && height >= minSize) {
                    createBoundingBox(container, drawStart, endPos);
                }

                redrawCanvas(container);
            }
        });

        canvas.addEventListener('mouseleave', function() {
            if (isDrawing) {
                isDrawing = false;
                redrawCanvas(container);
            }
            if (isResizing) {
                isResizing = false;
                resizeHandle = null;
                if (selectedBox) {
                    updateNormalizedBbox(selectedBox, canvas);
                }
                redrawCanvas(container);
            }
        });

        // Click to select in select mode (only if not resizing)
        canvas.addEventListener('click', function(e) {
            if (currentMode !== 'select') return;
            if (isResizing) return;

            const rect = canvas.getBoundingClientRect();
            const clickPos = {
                x: e.clientX - rect.left,
                y: e.clientY - rect.top
            };

            // Don't select if clicking on a resize handle
            if (selectedBox && getResizeHandleAtPoint(clickPos, selectedBox, canvas)) {
                return;
            }

            selectBoxAtPoint(container, clickPos);
        });
    }

    /**
     * Resize the selected box based on handle being dragged.
     */
    function resizeSelectedBox(container, canvas, currentPos) {
        if (!selectedBox || !resizeHandle) return;

        const pixelBbox = selectedBox.bbox_pixels;
        let [x, y, w, h] = pixelBbox;

        const minSize = parseInt(container.getAttribute('data-bbox-min-size') || '10', 10);

        switch (resizeHandle) {
            case 'nw': // Top-left
                const newW_nw = (x + w) - currentPos.x;
                const newH_nw = (y + h) - currentPos.y;
                if (newW_nw >= minSize && newH_nw >= minSize) {
                    x = currentPos.x;
                    y = currentPos.y;
                    w = newW_nw;
                    h = newH_nw;
                }
                break;
            case 'ne': // Top-right
                const newW_ne = currentPos.x - x;
                const newH_ne = (y + h) - currentPos.y;
                if (newW_ne >= minSize && newH_ne >= minSize) {
                    y = currentPos.y;
                    w = newW_ne;
                    h = newH_ne;
                }
                break;
            case 'sw': // Bottom-left
                const newW_sw = (x + w) - currentPos.x;
                const newH_sw = currentPos.y - y;
                if (newW_sw >= minSize && newH_sw >= minSize) {
                    x = currentPos.x;
                    w = newW_sw;
                    h = newH_sw;
                }
                break;
            case 'se': // Bottom-right
                const newW_se = currentPos.x - x;
                const newH_se = currentPos.y - y;
                if (newW_se >= minSize && newH_se >= minSize) {
                    w = newW_se;
                    h = newH_se;
                }
                break;
        }

        // Update pixel bbox
        selectedBox.bbox_pixels = [x, y, w, h];

        redrawCanvas(container);
    }

    /**
     * Update normalized bbox from pixel bbox.
     */
    function updateNormalizedBbox(box, canvas) {
        if (!box.bbox_pixels) return;

        const [x, y, w, h] = box.bbox_pixels;
        box.bbox = [
            x / canvas.width,
            y / canvas.height,
            w / canvas.width,
            h / canvas.height
        ];
    }

    /**
     * Sync canvas size with content element.
     */
    function syncCanvasSize(container) {
        const canvas = container.querySelector('.document-bbox-canvas');
        const contentEl = container.querySelector('.document-bbox-content');

        if (canvas && contentEl) {
            canvas.width = contentEl.offsetWidth;
            canvas.height = contentEl.offsetHeight;
            redrawCanvas(container);
        }
    }

    /**
     * Draw a temporary rectangle while drawing.
     */
    function drawTemporaryRect(ctx, start, end) {
        // Get color based on currently selected label (if any)
        const currentLabel = getCurrentSelectedLabel();
        const color = getLabelColor(currentLabel);

        ctx.strokeStyle = color;
        ctx.fillStyle = hexToRgba(color, 0.15);
        ctx.lineWidth = 2;
        ctx.setLineDash([5, 5]);

        const x = Math.min(start.x, end.x);
        const y = Math.min(start.y, end.y);
        const w = Math.abs(end.x - start.x);
        const h = Math.abs(end.y - start.y);

        ctx.fillRect(x, y, w, h);
        ctx.strokeRect(x, y, w, h);
        ctx.setLineDash([]);
    }

    /**
     * Create a new bounding box.
     */
    function createBoundingBox(container, start, end) {
        const fieldKey = container.getAttribute('data-field-key');
        const canvas = container.querySelector('.document-bbox-canvas');

        // Calculate normalized coordinates (0-1)
        const x = Math.min(start.x, end.x) / canvas.width;
        const y = Math.min(start.y, end.y) / canvas.height;
        const width = Math.abs(end.x - start.x) / canvas.width;
        const height = Math.abs(end.y - start.y) / canvas.height;

        // Generate unique ID
        const boxId = `bbox_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

        // Get currently selected label (if any)
        const currentLabel = getCurrentSelectedLabel();

        // Create box object
        const box = {
            id: boxId,
            bbox: [x, y, width, height],
            bbox_pixels: [
                Math.min(start.x, end.x),
                Math.min(start.y, end.y),
                Math.abs(end.x - start.x),
                Math.abs(end.y - start.y)
            ],
            label: currentLabel, // Auto-assign current label
            created_at: new Date().toISOString()
        };

        // Store box
        boundingBoxes[fieldKey].push(box);

        // Update display
        redrawCanvas(container);
        updateBoxCount(container);

        // Trigger event
        triggerBoundingBoxEvent(container, 'document-bbox:created', box);

        // Prompt for label (allows changing if needed)
        promptForLabel(container, box);
    }

    /**
     * Prompt user to select a label for the bounding box.
     * If no label was auto-assigned, this allows selecting one.
     */
    function promptForLabel(container, box) {
        // Always select the box after drawing (for resize handles)
        selectedBox = box;
        redrawCanvas(container);

        // If box already has a label (from auto-assignment), no need to add listeners
        if (box.label) {
            return;
        }

        const labelButtons = document.querySelectorAll('.span-label-btn, .annotation-label, input[type="radio"]');

        if (labelButtons.length > 0) {
            // Capture the specific box reference (not using global selectedBox)
            const targetBox = box;

            const labelHandler = function(e) {
                const label = e.target.getAttribute('data-label') ||
                              e.target.getAttribute('data-name') ||
                              e.target.value ||
                              e.target.textContent.trim();

                if (label && targetBox) {
                    targetBox.label = label;
                    redrawCanvas(container);
                    triggerBoundingBoxEvent(container, 'document-bbox:labeled', targetBox);
                }

                labelButtons.forEach(btn => {
                    btn.removeEventListener('click', labelHandler);
                    btn.removeEventListener('change', labelHandler);
                });
            };

            labelButtons.forEach(btn => {
                btn.addEventListener('click', labelHandler);
                btn.addEventListener('change', labelHandler);
            });
        }
    }

    /**
     * Select a bounding box at a given point.
     */
    function selectBoxAtPoint(container, point) {
        const fieldKey = container.getAttribute('data-field-key');
        const boxes = boundingBoxes[fieldKey] || [];
        const canvas = container.querySelector('.document-bbox-canvas');

        selectedBox = null;

        // Find box at point (reverse order for top-most first)
        for (let i = boxes.length - 1; i >= 0; i--) {
            const box = boxes[i];
            const pixelBbox = box.bbox_pixels || [
                box.bbox[0] * canvas.width,
                box.bbox[1] * canvas.height,
                box.bbox[2] * canvas.width,
                box.bbox[3] * canvas.height
            ];

            if (point.x >= pixelBbox[0] &&
                point.x <= pixelBbox[0] + pixelBbox[2] &&
                point.y >= pixelBbox[1] &&
                point.y <= pixelBbox[1] + pixelBbox[3]) {
                selectedBox = box;
                break;
            }
        }

        redrawCanvas(container);
        triggerBoundingBoxEvent(container, 'document-bbox:selected', selectedBox);
    }

    /**
     * Delete the currently selected bounding box.
     */
    function deleteSelectedBox(container) {
        if (!selectedBox) return;

        const fieldKey = container.getAttribute('data-field-key');
        const boxes = boundingBoxes[fieldKey] || [];

        const index = boxes.findIndex(b => b.id === selectedBox.id);
        if (index !== -1) {
            boxes.splice(index, 1);
            triggerBoundingBoxEvent(container, 'document-bbox:deleted', selectedBox);
            selectedBox = null;
            redrawCanvas(container);
            updateBoxCount(container);
        }
    }

    /**
     * Redraw all bounding boxes on the canvas.
     */
    function redrawCanvas(container) {
        const fieldKey = container.getAttribute('data-field-key');
        const canvas = container.querySelector('.document-bbox-canvas');
        if (!canvas) return;

        const ctx = canvas.getContext('2d');
        const showLabels = container.getAttribute('data-show-bbox-labels') !== 'false';

        // Clear canvas
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        // Draw all boxes
        const boxes = boundingBoxes[fieldKey] || [];

        boxes.forEach(box => {
            const isSelected = selectedBox && selectedBox.id === box.id;
            drawBoundingBox(ctx, box, canvas.width, canvas.height, isSelected, showLabels);
        });
    }

    /**
     * Draw a single bounding box.
     */
    function drawBoundingBox(ctx, box, canvasWidth, canvasHeight, isSelected, showLabels) {
        const pixelBbox = box.bbox_pixels || [
            box.bbox[0] * canvasWidth,
            box.bbox[1] * canvasHeight,
            box.bbox[2] * canvasWidth,
            box.bbox[3] * canvasHeight
        ];

        const [x, y, w, h] = pixelBbox;

        // Get color based on label
        const labelColor = getLabelColor(box.label);

        // Box style - use label color, with thicker stroke when selected
        if (isSelected) {
            ctx.strokeStyle = labelColor;
            ctx.fillStyle = hexToRgba(labelColor, 0.25);
            ctx.lineWidth = 3;
        } else {
            ctx.strokeStyle = labelColor;
            ctx.fillStyle = hexToRgba(labelColor, 0.1);
            ctx.lineWidth = 2;
        }

        ctx.fillRect(x, y, w, h);
        ctx.strokeRect(x, y, w, h);

        // Draw label
        if (showLabels && box.label) {
            ctx.font = 'bold 12px sans-serif';
            const textWidth = ctx.measureText(box.label).width;
            const labelHeight = 20;
            const labelY = y - labelHeight - 2;

            // Label background - use label color
            ctx.fillStyle = labelColor;
            ctx.fillRect(x, Math.max(0, labelY), textWidth + 10, labelHeight);

            // Label text
            ctx.fillStyle = 'white';
            ctx.fillText(box.label, x + 5, Math.max(14, labelY + 14));
        }

        // Resize handles if selected
        if (isSelected) {
            ctx.fillStyle = labelColor;
            ctx.strokeStyle = 'white';
            ctx.lineWidth = 1;

            // Corner handles with white border for visibility
            const handles = [
                [x - HANDLE_SIZE/2, y - HANDLE_SIZE/2],
                [x + w - HANDLE_SIZE/2, y - HANDLE_SIZE/2],
                [x - HANDLE_SIZE/2, y + h - HANDLE_SIZE/2],
                [x + w - HANDLE_SIZE/2, y + h - HANDLE_SIZE/2]
            ];

            handles.forEach(([hx, hy]) => {
                ctx.fillRect(hx, hy, HANDLE_SIZE, HANDLE_SIZE);
                ctx.strokeRect(hx, hy, HANDLE_SIZE, HANDLE_SIZE);
            });
        }
    }

    /**
     * Initialize tool buttons.
     */
    function initToolButtons(container) {
        const drawBtn = container.querySelector('.document-bbox-draw-btn');
        const selectBtn = container.querySelector('.document-bbox-select-btn');
        const deleteBtn = container.querySelector('.document-bbox-delete-btn');

        if (drawBtn) {
            drawBtn.addEventListener('click', function() {
                setMode(container, 'draw');
            });
        }

        if (selectBtn) {
            selectBtn.addEventListener('click', function() {
                setMode(container, 'select');
            });
        }

        if (deleteBtn) {
            deleteBtn.addEventListener('click', function() {
                deleteSelectedBox(container);
            });
        }
    }

    /**
     * Set the current annotation mode.
     */
    function setMode(container, mode) {
        currentMode = mode;

        const drawBtn = container.querySelector('.document-bbox-draw-btn');
        const selectBtn = container.querySelector('.document-bbox-select-btn');
        const bboxContainer = container.querySelector('.document-bbox-container');

        if (drawBtn) drawBtn.classList.toggle('active', mode === 'draw');
        if (selectBtn) selectBtn.classList.toggle('active', mode === 'select');
        if (bboxContainer) bboxContainer.classList.toggle('selecting', mode === 'select');
    }

    /**
     * Update box count display.
     */
    function updateBoxCount(container) {
        const fieldKey = container.getAttribute('data-field-key');
        const boxes = boundingBoxes[fieldKey] || [];

        const countEl = container.querySelector('.document-bbox-count .count');
        if (countEl) {
            countEl.textContent = boxes.length;
        }
    }

    /**
     * Load existing annotations.
     */
    function loadExistingAnnotations(container, fieldKey) {
        const existingData = container.querySelector('input[name="bbox_annotations"]');
        if (existingData && existingData.value) {
            try {
                const annotations = JSON.parse(existingData.value);
                if (Array.isArray(annotations)) {
                    boundingBoxes[fieldKey] = annotations;
                }
            } catch (e) {
                console.error('Error loading existing document bbox annotations:', e);
            }
        }

        redrawCanvas(container);
        updateBoxCount(container);
    }

    /**
     * Trigger a custom event.
     */
    function triggerBoundingBoxEvent(container, eventName, data) {
        const event = new CustomEvent(eventName, {
            detail: {
                fieldKey: container.getAttribute('data-field-key'),
                data: data,
                allBoxes: getAllBoundingBoxes(container)
            },
            bubbles: true
        });
        container.dispatchEvent(event);
    }

    /**
     * Get all bounding boxes for a container.
     */
    function getAllBoundingBoxes(container) {
        const fieldKey = container.getAttribute('data-field-key');
        const boxes = boundingBoxes[fieldKey] || [];

        return boxes.map(box => ({
            ...box,
            format_coords: {
                format: 'bounding_box',
                bbox: box.bbox,
                bbox_pixels: box.bbox_pixels,
                label: box.label
            }
        }));
    }

    /**
     * Export bounding boxes.
     */
    function exportBoundingBoxes(container) {
        return getAllBoundingBoxes(container);
    }

    // Public API
    window.DocumentBoundingBox = {
        init: initDocumentBoundingBoxes,
        initDisplay: initDisplay,
        getAllBoxes: getAllBoundingBoxes,
        exportBoxes: exportBoundingBoxes,
        syncCanvasSize: syncCanvasSize,
        deleteSelected: function(container) { deleteSelectedBox(container); },
        setMode: setMode
    };

    // Auto-initialize on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initDocumentBoundingBoxes);
    } else {
        initDocumentBoundingBoxes();
    }

})();

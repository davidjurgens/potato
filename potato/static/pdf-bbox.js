/**
 * PDF Bounding Box Annotation
 *
 * Provides bounding box drawing and management for PDF pages.
 * Works with PDF.js for rendering and captures bbox coordinates with page information.
 */

(function() {
    'use strict';

    // Store all bounding boxes by page
    const boundingBoxes = {};
    let selectedBox = null;
    let currentPage = 1;
    let totalPages = 1;
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
     * Initialize bounding box annotation for all PDF displays in bbox mode.
     */
    function initPDFBoundingBoxes() {
        const displays = document.querySelectorAll('.pdf-display[data-annotation-mode="bounding_box"]');
        displays.forEach(initDisplay);
    }

    /**
     * Initialize a single PDF display for bbox annotation.
     */
    function initDisplay(container) {
        currentContainer = container;
        const fieldKey = container.getAttribute('data-field-key');
        const minSize = parseInt(container.getAttribute('data-bbox-min-size') || '10', 10);
        const showLabels = container.getAttribute('data-show-bbox-labels') !== 'false';

        // Get total pages from data attribute or PDF.js
        totalPages = parseInt(container.getAttribute('data-total-pages') || '1', 10);

        // Initialize bbox storage
        if (!boundingBoxes[fieldKey]) {
            boundingBoxes[fieldKey] = {};
        }

        // Set up canvas for drawing - check multiple possible locations
        let bboxCanvas = container.querySelector('.pdf-bbox-canvas');

        // If no canvas exists, create overlays for each pdf-page element
        if (!bboxCanvas) {
            const pagesContainer = container.querySelector('.pdf-pages-container');
            if (pagesContainer) {
                // Create a single canvas overlay for the entire pages container
                bboxCanvas = createCanvasOverlay(pagesContainer);
            }
        }

        if (bboxCanvas) {
            initDrawingCanvas(bboxCanvas, container, minSize, showLabels);
        }

        // Set up navigation controls
        initNavigationControls(container);

        // Set up tool buttons
        initToolButtons(container);

        // Initialize page visibility - show first page
        updatePageVisibility(container);

        // Resize canvas after page visibility is set
        setTimeout(() => {
            resizeCanvasToCurrentPage(container);
        }, 50);

        // Load any existing annotations
        loadExistingAnnotations(container, fieldKey);
    }

    /**
     * Create a canvas overlay for the pages container.
     */
    function createCanvasOverlay(pagesContainer) {
        // Make container position relative for absolute positioning of canvas
        pagesContainer.style.position = 'relative';

        // Create canvas element - will be sized to active page
        const canvas = document.createElement('canvas');
        canvas.className = 'pdf-bbox-canvas';

        // Append canvas to container
        pagesContainer.appendChild(canvas);

        return canvas;
    }

    /**
     * Position and size canvas to match active page.
     */
    function positionCanvasOverPage(container) {
        const canvas = container.querySelector('.pdf-bbox-canvas');
        const activePage = container.querySelector('.pdf-page.active');
        const pagesContainer = container.querySelector('.pdf-pages-container');

        if (!canvas || !activePage || !pagesContainer) return;

        // Get page dimensions and position relative to container
        const pageRect = activePage.getBoundingClientRect();
        const containerRect = pagesContainer.getBoundingClientRect();

        // Calculate offset from container
        const offsetX = pageRect.left - containerRect.left;
        const offsetY = pageRect.top - containerRect.top;

        // Size and position the canvas over the active page
        // Use !important to override CSS rules
        canvas.width = Math.round(pageRect.width);
        canvas.height = Math.round(pageRect.height);
        canvas.setAttribute('style', `
            position: absolute !important;
            left: ${offsetX}px !important;
            top: ${offsetY}px !important;
            width: ${pageRect.width}px !important;
            height: ${pageRect.height}px !important;
            pointer-events: all !important;
            z-index: 10 !important;
            transform: none !important;
        `);
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
     * Initialize the drawing canvas for bounding boxes.
     */
    function initDrawingCanvas(canvas, container, minSize, showLabels) {
        const ctx = canvas.getContext('2d');

        // Match canvas size to PDF canvas
        const pdfCanvas = container.querySelector('.pdf-canvas');
        if (pdfCanvas) {
            canvas.width = pdfCanvas.width;
            canvas.height = pdfCanvas.height;
        }

        // Mouse events for drawing and resizing
        canvas.addEventListener('mousedown', function(e) {
            const canvasRect = canvas.getBoundingClientRect();
            const mousePos = {
                x: e.clientX - canvasRect.left,
                y: e.clientY - canvasRect.top
            };

            // Check for resize handle first - allow in ANY mode if there's a selected box
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
            const canvasRect = canvas.getBoundingClientRect();
            const currentPos = {
                x: e.clientX - canvasRect.left,
                y: e.clientY - canvasRect.top
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
            const canvasRect = canvas.getBoundingClientRect();
            const endPos = {
                x: e.clientX - canvasRect.left,
                y: e.clientY - canvasRect.top
            };

            // Finish resizing
            if (isResizing) {
                isResizing = false;
                resizeHandle = null;
                resizeStart = null;
                // Update normalized bbox from pixel bbox
                if (selectedBox) {
                    updateNormalizedBbox(selectedBox, canvas);
                    triggerBoundingBoxEvent(container, 'bbox:resized', selectedBox);
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

            const canvasRect = canvas.getBoundingClientRect();
            const clickPos = {
                x: e.clientX - canvasRect.left,
                y: e.clientY - canvasRect.top
            };

            // Don't select if clicking on a resize handle
            if (selectedBox && getResizeHandleAtPoint(clickPos, selectedBox, canvas)) {
                return;
            }

            selectBoxAtPoint(container, clickPos);
        });
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
        const canvas = container.querySelector('.pdf-bbox-canvas');

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
            page: currentPage,
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
        if (!boundingBoxes[fieldKey][currentPage]) {
            boundingBoxes[fieldKey][currentPage] = [];
        }
        boundingBoxes[fieldKey][currentPage].push(box);

        // Update display
        redrawCanvas(container);
        updateBoxCounts(container);

        // Trigger event for annotation system
        triggerBoundingBoxEvent(container, 'bbox:created', box);

        // Prompt for label (allows changing if needed)
        promptForLabel(container, box);
    }

    /**
     * Prompt user to select a label for the bounding box.
     * If no label was auto-assigned, this allows selecting one.
     * If a label was already assigned, changing the radio will update the selected box.
     */
    function promptForLabel(container, box) {
        // Always select the box after drawing (for resize handles)
        selectedBox = box;
        redrawCanvas(container);

        // If box already has a label (from auto-assignment), no need to add listeners
        // The user can still change labels by selecting the box and clicking a label
        if (box.label) {
            return;
        }

        // Look for label buttons - include radio buttons used by annotation schemes
        const labelButtons = document.querySelectorAll('.span-label-btn, .annotation-label, input[type="radio"]');

        if (labelButtons.length > 0) {
            // Capture the specific box reference (not using global selectedBox)
            const targetBox = box;

            // Add temporary listener for label clicks/changes
            const labelHandler = function(e) {
                const label = e.target.getAttribute('data-label') ||
                              e.target.getAttribute('data-name') ||
                              e.target.value ||
                              e.target.textContent.trim();

                if (label && targetBox) {
                    targetBox.label = label;
                    redrawCanvas(container);
                    triggerBoundingBoxEvent(container, 'bbox:labeled', targetBox);
                }

                // Remove handlers after labeling
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
        const pageBoxes = boundingBoxes[fieldKey][currentPage] || [];
        const canvas = container.querySelector('.pdf-bbox-canvas');

        selectedBox = null;

        // Find box at point (reverse order for top-most first)
        for (let i = pageBoxes.length - 1; i >= 0; i--) {
            const box = pageBoxes[i];
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
        triggerBoundingBoxEvent(container, 'bbox:selected', selectedBox);
    }

    /**
     * Delete the currently selected bounding box.
     */
    function deleteSelectedBox(container) {
        if (!selectedBox) return;

        const fieldKey = container.getAttribute('data-field-key');
        const pageBoxes = boundingBoxes[fieldKey][currentPage] || [];

        const index = pageBoxes.findIndex(b => b.id === selectedBox.id);
        if (index !== -1) {
            pageBoxes.splice(index, 1);
            triggerBoundingBoxEvent(container, 'bbox:deleted', selectedBox);
            selectedBox = null;
            redrawCanvas(container);
            updateBoxCounts(container);
        }
    }

    /**
     * Redraw all bounding boxes on the canvas.
     */
    function redrawCanvas(container) {
        const fieldKey = container.getAttribute('data-field-key');
        const canvas = container.querySelector('.pdf-bbox-canvas');
        if (!canvas) return;

        const ctx = canvas.getContext('2d');
        const showLabels = container.getAttribute('data-show-bbox-labels') !== 'false';

        // Clear canvas
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        // Draw all boxes on current page
        const pageBoxes = boundingBoxes[fieldKey][currentPage] || [];

        pageBoxes.forEach(box => {
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

        // Box style - use label color, with brighter/thicker stroke when selected
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

        // Draw label if present
        if (showLabels && box.label) {
            ctx.font = 'bold 12px sans-serif';
            const textWidth = ctx.measureText(box.label).width;
            const labelHeight = 20;
            const labelY = y - labelHeight - 2;

            // Label background - use label color
            ctx.fillStyle = labelColor;
            ctx.fillRect(x, labelY, textWidth + 10, labelHeight);

            // Label text
            ctx.fillStyle = 'white';
            ctx.fillText(box.label, x + 5, labelY + 14);
        }

        // Draw resize handles if selected
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
     * Initialize navigation controls.
     */
    function initNavigationControls(container) {
        const prevBtn = container.querySelector('.pdf-prev-btn');
        const nextBtn = container.querySelector('.pdf-next-btn');
        const firstBtn = container.querySelector('.pdf-first-btn');
        const lastBtn = container.querySelector('.pdf-last-btn');
        const pageInput = container.querySelector('.pdf-page-input');

        if (prevBtn) {
            prevBtn.addEventListener('click', () => goToPage(container, currentPage - 1));
        }
        if (nextBtn) {
            nextBtn.addEventListener('click', () => goToPage(container, currentPage + 1));
        }
        if (firstBtn) {
            firstBtn.addEventListener('click', () => goToPage(container, 1));
        }
        if (lastBtn) {
            lastBtn.addEventListener('click', () => goToPage(container, totalPages));
        }
        if (pageInput) {
            pageInput.addEventListener('change', function() {
                goToPage(container, parseInt(this.value, 10));
            });
        }
    }

    /**
     * Navigate to a specific page.
     */
    function goToPage(container, pageNum) {
        if (pageNum < 1 || pageNum > totalPages) return;

        currentPage = pageNum;
        selectedBox = null;

        // Update page input
        const pageInput = container.querySelector('.pdf-page-input');
        if (pageInput) {
            pageInput.value = currentPage;
        }

        // Update page visibility - show only current page
        updatePageVisibility(container);

        // Update button states
        updateNavigationButtons(container);

        // Resize canvas to match current page
        resizeCanvasToCurrentPage(container);

        // Trigger page change event for PDF.js
        triggerBoundingBoxEvent(container, 'bbox:pagechange', { page: currentPage });

        // Redraw boxes for new page
        redrawCanvas(container);
        updateBoxCounts(container);
    }

    /**
     * Update page visibility - show only current page.
     */
    function updatePageVisibility(container) {
        const pages = container.querySelectorAll('.pdf-page');
        pages.forEach((page, index) => {
            const pageNum = parseInt(page.getAttribute('data-page') || (index + 1), 10);
            if (pageNum === currentPage) {
                page.classList.add('active');
            } else {
                page.classList.remove('active');
            }
        });
    }

    /**
     * Resize canvas to match current page dimensions.
     */
    function resizeCanvasToCurrentPage(container) {
        // Use a small delay to let the page become visible first
        setTimeout(() => {
            positionCanvasOverPage(container);
            redrawCanvas(container);
        }, 10);
    }

    /**
     * Update navigation button states.
     */
    function updateNavigationButtons(container) {
        const prevBtn = container.querySelector('.pdf-prev-btn');
        const nextBtn = container.querySelector('.pdf-next-btn');
        const firstBtn = container.querySelector('.pdf-first-btn');
        const lastBtn = container.querySelector('.pdf-last-btn');

        if (prevBtn) prevBtn.disabled = currentPage <= 1;
        if (nextBtn) nextBtn.disabled = currentPage >= totalPages;
        if (firstBtn) firstBtn.disabled = currentPage <= 1;
        if (lastBtn) lastBtn.disabled = currentPage >= totalPages;
    }

    /**
     * Initialize tool buttons.
     */
    function initToolButtons(container) {
        const drawBtn = container.querySelector('.pdf-bbox-draw-btn');
        const selectBtn = container.querySelector('.pdf-bbox-select-btn');
        const deleteBtn = container.querySelector('.pdf-bbox-delete-btn');

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

        const drawBtn = container.querySelector('.pdf-bbox-draw-btn');
        const selectBtn = container.querySelector('.pdf-bbox-select-btn');

        if (drawBtn) {
            drawBtn.classList.toggle('active', mode === 'draw');
        }
        if (selectBtn) {
            selectBtn.classList.toggle('active', mode === 'select');
        }

        // Update container class
        container.classList.toggle('selecting', mode === 'select');
    }

    /**
     * Update box count displays.
     */
    function updateBoxCounts(container) {
        const fieldKey = container.getAttribute('data-field-key');
        const pageBoxes = boundingBoxes[fieldKey][currentPage] || [];

        // Count total boxes across all pages
        let totalCount = 0;
        Object.values(boundingBoxes[fieldKey]).forEach(page => {
            totalCount += page.length;
        });

        const pageCountEl = container.querySelector('.pdf-bbox-count .count');
        const totalCountEl = container.querySelector('.pdf-bbox-total .count');

        if (pageCountEl) pageCountEl.textContent = pageBoxes.length;
        if (totalCountEl) totalCountEl.textContent = totalCount;
    }

    /**
     * Load existing annotations from hidden input.
     */
    function loadExistingAnnotations(container, fieldKey) {
        // Look for existing annotation data
        const existingData = container.querySelector('input[name="bbox_annotations"]');
        if (existingData && existingData.value) {
            try {
                const annotations = JSON.parse(existingData.value);
                if (Array.isArray(annotations)) {
                    annotations.forEach(box => {
                        const page = box.page || 1;
                        if (!boundingBoxes[fieldKey][page]) {
                            boundingBoxes[fieldKey][page] = [];
                        }
                        boundingBoxes[fieldKey][page].push(box);
                    });
                }
            } catch (e) {
                console.error('Error loading existing bbox annotations:', e);
            }
        }

        redrawCanvas(container);
        updateBoxCounts(container);
    }

    /**
     * Trigger a custom event for bounding box actions.
     */
    function triggerBoundingBoxEvent(container, eventName, data) {
        const event = new CustomEvent(eventName, {
            detail: {
                fieldKey: container.getAttribute('data-field-key'),
                page: currentPage,
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
        const allBoxes = [];

        Object.entries(boundingBoxes[fieldKey] || {}).forEach(([page, boxes]) => {
            boxes.forEach(box => {
                allBoxes.push({
                    ...box,
                    format_coords: {
                        format: 'bounding_box',
                        page: parseInt(page, 10),
                        bbox: box.bbox,
                        bbox_pixels: box.bbox_pixels,
                        label: box.label
                    }
                });
            });
        });

        return allBoxes;
    }

    /**
     * Export the bounding boxes for saving.
     */
    function exportBoundingBoxes(container) {
        return getAllBoundingBoxes(container);
    }

    /**
     * Sync canvas size with PDF canvas.
     */
    function syncCanvasSize(container) {
        const pdfCanvas = container.querySelector('.pdf-canvas');
        const bboxCanvas = container.querySelector('.pdf-bbox-canvas');

        if (pdfCanvas && bboxCanvas) {
            bboxCanvas.width = pdfCanvas.width;
            bboxCanvas.height = pdfCanvas.height;
            bboxCanvas.style.width = pdfCanvas.style.width;
            bboxCanvas.style.height = pdfCanvas.style.height;
            redrawCanvas(container);
        }
    }

    // Public API
    window.PDFBoundingBox = {
        init: initPDFBoundingBoxes,
        initDisplay: initDisplay,
        getAllBoxes: getAllBoundingBoxes,
        exportBoxes: exportBoundingBoxes,
        syncCanvasSize: syncCanvasSize,
        goToPage: goToPage,
        deleteSelected: function(container) { deleteSelectedBox(container); },
        setMode: setMode
    };

    // Auto-initialize on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initPDFBoundingBoxes);
    } else {
        initPDFBoundingBoxes();
    }

    // Re-initialize when PDF.js renders a page
    document.addEventListener('pdf:pagerendered', function(e) {
        const container = e.target.closest('.pdf-display');
        if (container && container.getAttribute('data-annotation-mode') === 'bounding_box') {
            syncCanvasSize(container);
            totalPages = parseInt(container.getAttribute('data-total-pages') || '1', 10);
            updateNavigationButtons(container);
        }
    });

})();

/**
 * Segmentation Tool Manager
 *
 * Provides flood fill and eraser tools for the image annotation canvas.
 * Extends the ImageAnnotationManager with segmentation capabilities.
 *
 * Segmentation masks are stored alongside other annotations as:
 *   {type: "mask", label: "road", rle: {counts: [...], size: [h, w]}}
 *
 * The mask overlay is rendered on a separate canvas layer above the
 * annotation canvas, with semi-transparent colored regions.
 */

(function() {
    'use strict';

    class SegmentationToolManager {
        /**
         * @param {HTMLCanvasElement} canvas - The main annotation canvas
         * @param {number} width - Canvas width
         * @param {number} height - Canvas height
         */
        constructor(canvas, width, height) {
            this.canvas = canvas;
            this.width = width;
            this.height = height;

            // Create mask overlay canvas
            this.maskCanvas = document.createElement('canvas');
            this.maskCanvas.width = width;
            this.maskCanvas.height = height;
            this.maskCanvas.style.cssText = 'position:absolute;top:0;left:0;pointer-events:none;opacity:0.4;';
            this.maskCtx = this.maskCanvas.getContext('2d');

            // Working canvas for flood fill operations
            this.workCanvas = document.createElement('canvas');
            this.workCanvas.width = width;
            this.workCanvas.height = height;
            this.workCtx = this.workCanvas.getContext('2d');

            // Mask data: label -> ImageData (binary mask)
            this.masks = {};
            this.activeTool = null;
            this.activeLabel = null;
            this.eraserSize = 20;
            this.fillTolerance = 32;

            // Insert mask canvas after the main canvas
            if (canvas.parentElement) {
                canvas.parentElement.style.position = 'relative';
                canvas.parentElement.insertBefore(this.maskCanvas, canvas.nextSibling);
            }
        }

        setTool(tool) {
            this.activeTool = tool;
        }

        setLabel(label, color) {
            this.activeLabel = label;
            this.activeColor = color || '#FF0000';
        }

        setEraserSize(size) {
            this.eraserSize = size;
        }

        setFillTolerance(tolerance) {
            this.fillTolerance = tolerance;
        }

        /**
         * Handle click on canvas for flood fill.
         */
        floodFill(x, y) {
            if (!this.activeLabel) return null;

            x = Math.round(x);
            y = Math.round(y);
            if (x < 0 || x >= this.width || y < 0 || y >= this.height) return null;

            // Get the source image data from the main canvas
            var ctx = this.canvas.getContext('2d');
            var imageData = ctx.getImageData(0, 0, this.width, this.height);
            var pixels = imageData.data;

            // Target color at click point
            var idx = (y * this.width + x) * 4;
            var targetR = pixels[idx];
            var targetG = pixels[idx + 1];
            var targetB = pixels[idx + 2];

            // Create or get mask for this label
            if (!this.masks[this.activeLabel]) {
                this.masks[this.activeLabel] = new Uint8Array(this.width * this.height);
            }
            var mask = this.masks[this.activeLabel];

            // Scanline flood fill
            var tolerance = this.fillTolerance;
            var visited = new Uint8Array(this.width * this.height);
            var stack = [[x, y]];
            var filled = 0;

            while (stack.length > 0) {
                var point = stack.pop();
                var px = point[0];
                var py = point[1];

                if (px < 0 || px >= this.width || py < 0 || py >= this.height) continue;

                var pidx = py * this.width + px;
                if (visited[pidx]) continue;
                visited[pidx] = 1;

                var ci = pidx * 4;
                var dr = Math.abs(pixels[ci] - targetR);
                var dg = Math.abs(pixels[ci + 1] - targetG);
                var db = Math.abs(pixels[ci + 2] - targetB);

                if (dr <= tolerance && dg <= tolerance && db <= tolerance) {
                    mask[pidx] = 1;
                    filled++;

                    stack.push([px + 1, py]);
                    stack.push([px - 1, py]);
                    stack.push([px, py + 1]);
                    stack.push([px, py - 1]);
                }
            }

            this.renderMasks();

            return {
                type: 'mask',
                label: this.activeLabel,
                rle: this.encodeRLE(mask, this.width, this.height),
                pixelsFilled: filled
            };
        }

        /**
         * Erase mask pixels at the given canvas coordinates.
         */
        erase(x, y) {
            x = Math.round(x);
            y = Math.round(y);
            var r = Math.round(this.eraserSize / 2);
            var changed = false;

            // Erase from all masks
            for (var label in this.masks) {
                var mask = this.masks[label];
                for (var dy = -r; dy <= r; dy++) {
                    for (var dx = -r; dx <= r; dx++) {
                        if (dx * dx + dy * dy <= r * r) {
                            var px = x + dx;
                            var py = y + dy;
                            if (px >= 0 && px < this.width && py >= 0 && py < this.height) {
                                var idx = py * this.width + px;
                                if (mask[idx]) {
                                    mask[idx] = 0;
                                    changed = true;
                                }
                            }
                        }
                    }
                }
            }

            if (changed) {
                this.renderMasks();
            }
            return changed;
        }

        /**
         * Render all mask overlays.
         */
        renderMasks() {
            this.maskCtx.clearRect(0, 0, this.width, this.height);
            var imageData = this.maskCtx.createImageData(this.width, this.height);
            var data = imageData.data;

            for (var label in this.masks) {
                var mask = this.masks[label];
                var color = this._parseColor(this._getLabelColor(label));

                for (var i = 0; i < mask.length; i++) {
                    if (mask[i]) {
                        var pi = i * 4;
                        // Alpha-blend with existing pixel data
                        data[pi] = Math.min(255, data[pi] + color.r);
                        data[pi + 1] = Math.min(255, data[pi + 1] + color.g);
                        data[pi + 2] = Math.min(255, data[pi + 2] + color.b);
                        data[pi + 3] = 200;  // Semi-transparent
                    }
                }
            }

            this.maskCtx.putImageData(imageData, 0, 0);
        }

        /**
         * Encode a binary mask to RLE format.
         */
        encodeRLE(mask, width, height) {
            var counts = [];
            var currentVal = 0;
            var currentCount = 0;

            for (var i = 0; i < mask.length; i++) {
                var val = mask[i] ? 1 : 0;
                if (val === currentVal) {
                    currentCount++;
                } else {
                    counts.push(currentCount);
                    currentVal = val;
                    currentCount = 1;
                }
            }
            counts.push(currentCount);

            return { counts: counts, size: [height, width] };
        }

        /**
         * Decode RLE format back to a binary mask.
         */
        decodeRLE(rle) {
            var size = rle.size;
            var counts = rle.counts;
            var mask = new Uint8Array(size[0] * size[1]);
            var pos = 0;
            var val = 0;

            for (var i = 0; i < counts.length; i++) {
                for (var j = 0; j < counts[i]; j++) {
                    if (pos < mask.length) {
                        mask[pos] = val;
                        pos++;
                    }
                }
                val = 1 - val;
            }

            return mask;
        }

        /**
         * Load mask data from saved annotations.
         */
        loadMask(label, rle) {
            this.masks[label] = this.decodeRLE(rle);
            this.renderMasks();
        }

        /**
         * Get all mask annotations for saving.
         */
        getMaskAnnotations() {
            var annotations = [];
            for (var label in this.masks) {
                var mask = this.masks[label];
                // Check if mask has any filled pixels
                var hasPixels = false;
                for (var i = 0; i < mask.length; i++) {
                    if (mask[i]) { hasPixels = true; break; }
                }
                if (hasPixels) {
                    annotations.push({
                        type: 'mask',
                        label: label,
                        rle: this.encodeRLE(mask, this.width, this.height)
                    });
                }
            }
            return annotations;
        }

        /**
         * Clear all masks.
         */
        clearAll() {
            this.masks = {};
            this.maskCtx.clearRect(0, 0, this.width, this.height);
        }

        /**
         * Clear mask for a specific label.
         */
        clearLabel(label) {
            delete this.masks[label];
            this.renderMasks();
        }

        _getLabelColor(label) {
            // Try to get color from label buttons on the page
            var btn = document.querySelector('.label-btn[data-label="' + label + '"]');
            if (btn) return btn.dataset.color || '#FF0000';
            return this.activeColor || '#FF0000';
        }

        _parseColor(hex) {
            hex = hex.replace('#', '');
            if (hex.length === 3) {
                hex = hex[0] + hex[0] + hex[1] + hex[1] + hex[2] + hex[2];
            }
            return {
                r: parseInt(hex.substring(0, 2), 16),
                g: parseInt(hex.substring(2, 4), 16),
                b: parseInt(hex.substring(4, 6), 16)
            };
        }
    }

    // Expose globally
    window.SegmentationToolManager = SegmentationToolManager;
})();

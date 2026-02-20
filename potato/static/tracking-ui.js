/**
 * Tracking UI Manager
 *
 * Provides interactive bbox drawing on video canvas for object tracking,
 * a track management panel, and integration with the interpolation engine.
 *
 * Supports:
 * - Drawing new bounding boxes
 * - Selecting existing boxes (click)
 * - Moving boxes (drag)
 * - Resizing boxes (corner handles)
 * - Deleting keyframes (Delete key)
 */

(function() {
    'use strict';

    var HANDLE_SIZE = 10;  // Size of resize handles
    var HANDLE_HIT_RADIUS = 12;  // Hit detection radius (larger for easier grabbing)

    class TrackingUIManager {
        /**
         * @param {Object} options
         * @param {HTMLCanvasElement} options.canvas - Tracking overlay canvas
         * @param {HTMLVideoElement} options.video - Video element
         * @param {Object} options.annotationManager - Parent VideoAnnotationManager
         * @param {Object} options.config - Tracking config options
         */
        constructor(options) {
            this.canvas = options.canvas;
            this.video = options.video;
            this.manager = options.annotationManager;
            this.config = options.config || {};

            this.ctx = this.canvas ? this.canvas.getContext('2d') : null;
            this.tracks = {};  // objectId -> track data
            this.activeTrackId = null;
            this.nextTrackId = 1;
            this.autoAdvanceFrames = this.config.autoAdvanceFrames || 5;
            this.defaultInterpolation = this.config.interpolation || 'linear';

            // Interaction state
            this.mode = 'idle';  // 'idle', 'drawing', 'moving', 'resizing'
            this.drawStart = null;
            this.selectedKeyframe = null;  // {trackId, frame}
            this.dragStart = null;
            this.dragOffset = null;
            this.resizeHandle = null;  // 'nw', 'ne', 'sw', 'se', 'n', 's', 'e', 'w'
            this.originalBbox = null;

            if (this.canvas) {
                this._bindCanvasEvents();
                this._bindKeyboardEvents();
                this._updateCanvasPointerEvents();
            }
        }

        /**
         * Create a new track.
         */
        createTrack(label, color) {
            var id = 'track_' + this.nextTrackId++;
            this.tracks[id] = {
                id: id,
                label: label || 'object',
                color: color || '#FF6B6B',
                interpolation: this.defaultInterpolation,
                keyframes: {},
                startFrame: null,
                endFrame: null
            };
            this.activeTrackId = id;
            this.selectedKeyframe = null;
            this._updateCanvasPointerEvents();
            this._renderTrackPanel();
            return id;
        }

        /**
         * Update canvas pointer-events based on active track.
         */
        _updateCanvasPointerEvents() {
            if (this.canvas) {
                if (this.activeTrackId) {
                    this.canvas.classList.remove('no-active-track');
                    this.canvas.style.pointerEvents = 'auto';
                } else {
                    this.canvas.classList.add('no-active-track');
                    this.canvas.style.pointerEvents = 'none';
                }
            }
        }

        /**
         * Add a keyframe bbox to the active track at the current frame.
         */
        addKeyframe(bbox) {
            if (!this.activeTrackId) return;
            var track = this.tracks[this.activeTrackId];
            if (!track) return;

            var frame = this._getCurrentFrame();
            track.keyframes[frame] = {
                frame: frame,
                time: this.video ? this.video.currentTime : 0,
                bbox: bbox
            };

            // Update track range
            this._updateTrackRange(track);

            // Select the new keyframe
            this.selectedKeyframe = { trackId: this.activeTrackId, frame: frame };

            this._renderTrackPanel();
            this.renderOverlay();
        }

        /**
         * Update a keyframe's bbox.
         */
        updateKeyframe(trackId, frame, bbox) {
            var track = this.tracks[trackId];
            if (!track || !track.keyframes[frame]) return;

            track.keyframes[frame].bbox = bbox;
            this.renderOverlay();
        }

        /**
         * Update track frame range after keyframe changes.
         */
        _updateTrackRange(track) {
            var frames = Object.keys(track.keyframes).map(Number);
            if (frames.length > 0) {
                track.startFrame = Math.min.apply(null, frames);
                track.endFrame = Math.max.apply(null, frames);
            } else {
                track.startFrame = null;
                track.endFrame = null;
            }
        }

        /**
         * Delete a keyframe from a track.
         */
        deleteKeyframe(trackId, frame) {
            var track = this.tracks[trackId];
            if (!track) return;
            delete track.keyframes[frame];

            this._updateTrackRange(track);

            // Clear selection if we deleted the selected keyframe
            if (this.selectedKeyframe &&
                this.selectedKeyframe.trackId === trackId &&
                this.selectedKeyframe.frame === frame) {
                this.selectedKeyframe = null;
            }

            this._renderTrackPanel();
            this.renderOverlay();
        }

        /**
         * Delete the currently selected keyframe.
         */
        deleteSelectedKeyframe() {
            if (this.selectedKeyframe) {
                this.deleteKeyframe(this.selectedKeyframe.trackId, this.selectedKeyframe.frame);
            }
        }

        /**
         * Delete an entire track.
         */
        deleteTrack(trackId) {
            delete this.tracks[trackId];
            if (this.activeTrackId === trackId) {
                this.activeTrackId = null;
            }
            if (this.selectedKeyframe && this.selectedKeyframe.trackId === trackId) {
                this.selectedKeyframe = null;
            }
            this._updateCanvasPointerEvents();
            this._renderTrackPanel();
            this.renderOverlay();
        }

        /**
         * Set the interpolation type for a track.
         */
        setInterpolation(trackId, type) {
            var track = this.tracks[trackId];
            if (track) {
                track.interpolation = type;
                this.renderOverlay();
            }
        }

        /**
         * Render tracking overlay for current frame using interpolation.
         */
        renderOverlay() {
            if (!this.ctx || !this.canvas) return;

            this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
            var currentFrame = this._getCurrentFrame();

            for (var trackId in this.tracks) {
                var track = this.tracks[trackId];
                var bbox = null;
                var isKeyframe = false;

                // Check if current frame is a keyframe
                if (track.keyframes[currentFrame]) {
                    bbox = track.keyframes[currentFrame].bbox;
                    isKeyframe = true;
                } else if (window.TrackingInterpolationEngine) {
                    // Use interpolation engine for non-keyframes
                    bbox = window.TrackingInterpolationEngine.interpolate(track, currentFrame);
                }

                if (bbox) {
                    var isActive = trackId === this.activeTrackId;
                    var isSelected = this.selectedKeyframe &&
                                    this.selectedKeyframe.trackId === trackId &&
                                    this.selectedKeyframe.frame === currentFrame;

                    this._drawBbox(bbox, track.color, track.label, isActive, isSelected);

                    // Mark if this is a keyframe
                    if (isKeyframe) {
                        this._drawKeyframeDiamond(bbox, track.color);
                    }

                    // Draw resize handles if selected
                    if (isSelected && isKeyframe) {
                        this._drawResizeHandles(bbox, track.color);
                    }
                }
            }

            // Draw preview if in drawing mode
            if (this.mode === 'drawing' && this.drawStart && this.drawCurrent) {
                this._drawPreviewRect(this.drawStart, this.drawCurrent);
            }
        }

        /**
         * Get all tracking data for saving.
         */
        getTrackingData() {
            return this.tracks;
        }

        /**
         * Load tracking data from saved state.
         */
        loadTrackingData(data) {
            if (!data) return;
            this.tracks = data;
            // Update nextTrackId
            for (var id in this.tracks) {
                var num = parseInt(id.replace('track_', ''), 10);
                if (!isNaN(num) && num >= this.nextTrackId) {
                    this.nextTrackId = num + 1;
                }
            }
            this._renderTrackPanel();
            this.renderOverlay();
        }

        // --- Drawing helpers ---

        _drawBbox(bbox, color, label, isActive, isSelected) {
            this.ctx.strokeStyle = isSelected ? '#FFD700' : color;
            this.ctx.lineWidth = isSelected ? 3 : (isActive ? 2 : 1);

            if (!isActive && !isSelected) {
                this.ctx.setLineDash([4, 4]);
            } else {
                this.ctx.setLineDash([]);
            }

            this.ctx.strokeRect(bbox.x, bbox.y, bbox.width, bbox.height);
            this.ctx.setLineDash([]);

            // Label background
            this.ctx.font = '11px Arial';
            var textWidth = this.ctx.measureText(label).width;
            this.ctx.fillStyle = isSelected ? '#FFD700' : color;
            this.ctx.fillRect(bbox.x, bbox.y - 16, textWidth + 6, 16);
            this.ctx.fillStyle = isSelected ? '#000' : '#fff';
            this.ctx.fillText(label, bbox.x + 3, bbox.y - 4);
        }

        _drawKeyframeDiamond(bbox, color) {
            var cx = bbox.x + bbox.width / 2;
            var cy = bbox.y;
            var size = 5;
            this.ctx.fillStyle = color;
            this.ctx.beginPath();
            this.ctx.moveTo(cx, cy - size);
            this.ctx.lineTo(cx + size, cy);
            this.ctx.lineTo(cx, cy + size);
            this.ctx.lineTo(cx - size, cy);
            this.ctx.closePath();
            this.ctx.fill();
        }

        _drawResizeHandles(bbox, color) {
            var handles = this._getHandlePositions(bbox);
            this.ctx.fillStyle = '#fff';
            this.ctx.strokeStyle = color;
            this.ctx.lineWidth = 1;

            for (var key in handles) {
                var h = handles[key];
                this.ctx.fillRect(h.x - HANDLE_SIZE/2, h.y - HANDLE_SIZE/2, HANDLE_SIZE, HANDLE_SIZE);
                this.ctx.strokeRect(h.x - HANDLE_SIZE/2, h.y - HANDLE_SIZE/2, HANDLE_SIZE, HANDLE_SIZE);
            }
        }

        _drawPreviewRect(start, current) {
            this.ctx.strokeStyle = '#FFD700';
            this.ctx.lineWidth = 2;
            this.ctx.setLineDash([6, 3]);
            this.ctx.strokeRect(
                Math.min(start.x, current.x),
                Math.min(start.y, current.y),
                Math.abs(current.x - start.x),
                Math.abs(current.y - start.y)
            );
            this.ctx.setLineDash([]);
        }

        _getHandlePositions(bbox) {
            return {
                nw: { x: bbox.x, y: bbox.y },
                n:  { x: bbox.x + bbox.width/2, y: bbox.y },
                ne: { x: bbox.x + bbox.width, y: bbox.y },
                e:  { x: bbox.x + bbox.width, y: bbox.y + bbox.height/2 },
                se: { x: bbox.x + bbox.width, y: bbox.y + bbox.height },
                s:  { x: bbox.x + bbox.width/2, y: bbox.y + bbox.height },
                sw: { x: bbox.x, y: bbox.y + bbox.height },
                w:  { x: bbox.x, y: bbox.y + bbox.height/2 }
            };
        }

        // --- Hit testing ---

        _hitTestBbox(x, y, bbox) {
            return x >= bbox.x && x <= bbox.x + bbox.width &&
                   y >= bbox.y && y <= bbox.y + bbox.height;
        }

        _hitTestHandle(x, y, bbox) {
            var handles = this._getHandlePositions(bbox);

            for (var key in handles) {
                var h = handles[key];
                if (Math.abs(x - h.x) <= HANDLE_HIT_RADIUS && Math.abs(y - h.y) <= HANDLE_HIT_RADIUS) {
                    return key;
                }
            }
            return null;
        }

        _findBboxAtPoint(x, y) {
            var currentFrame = this._getCurrentFrame();

            // Check active track first (priority)
            if (this.activeTrackId) {
                var track = this.tracks[this.activeTrackId];
                if (track && track.keyframes[currentFrame]) {
                    var bbox = track.keyframes[currentFrame].bbox;
                    if (this._hitTestBbox(x, y, bbox)) {
                        return { trackId: this.activeTrackId, frame: currentFrame, bbox: bbox };
                    }
                }
            }

            // Check other tracks
            for (var trackId in this.tracks) {
                if (trackId === this.activeTrackId) continue;
                var track = this.tracks[trackId];
                if (track.keyframes[currentFrame]) {
                    var bbox = track.keyframes[currentFrame].bbox;
                    if (this._hitTestBbox(x, y, bbox)) {
                        return { trackId: trackId, frame: currentFrame, bbox: bbox };
                    }
                }
            }

            return null;
        }

        // --- Canvas interaction ---

        /**
         * Get scaled canvas coordinates accounting for display vs internal size.
         */
        _getCanvasCoords(e) {
            var rect = this.canvas.getBoundingClientRect();
            var scaleX = this.canvas.width / rect.width;
            var scaleY = this.canvas.height / rect.height;
            return {
                x: (e.clientX - rect.left) * scaleX,
                y: (e.clientY - rect.top) * scaleY
            };
        }

        _bindCanvasEvents() {
            var self = this;

            this.canvas.addEventListener('mousedown', function(e) {
                if (!self.activeTrackId) return;

                var coords = self._getCanvasCoords(e);
                var x = coords.x;
                var y = coords.y;
                var currentFrame = self._getCurrentFrame();

                // Check if clicking on a resize handle of selected keyframe
                if (self.selectedKeyframe && self.selectedKeyframe.frame === currentFrame) {
                    var track = self.tracks[self.selectedKeyframe.trackId];
                    if (track && track.keyframes[currentFrame]) {
                        var bbox = track.keyframes[currentFrame].bbox;
                        var handle = self._hitTestHandle(x, y, bbox);
                        if (handle) {
                            self.mode = 'resizing';
                            self.resizeHandle = handle;
                            self.originalBbox = { ...bbox };
                            self.dragStart = { x: x, y: y };
                            return;
                        }
                    }
                }

                // Check if clicking on an existing bbox (to select or move)
                var hit = self._findBboxAtPoint(x, y);
                if (hit) {
                    // Select this keyframe
                    self.selectedKeyframe = { trackId: hit.trackId, frame: hit.frame };
                    self.activeTrackId = hit.trackId;
                    self._updateCanvasPointerEvents();
                    self._renderTrackPanel();

                    // Start moving
                    self.mode = 'moving';
                    self.originalBbox = { ...hit.bbox };
                    self.dragStart = { x: x, y: y };
                    self.dragOffset = { x: x - hit.bbox.x, y: y - hit.bbox.y };

                    self.renderOverlay();
                    return;
                }

                // Start drawing a new bbox
                self.mode = 'drawing';
                self.drawStart = { x: x, y: y };
                self.drawCurrent = { x: x, y: y };
                self.selectedKeyframe = null;
                self.canvas.style.cursor = 'crosshair';
            });

            this.canvas.addEventListener('mousemove', function(e) {
                var coords = self._getCanvasCoords(e);
                var x = coords.x;
                var y = coords.y;

                if (self.mode === 'drawing') {
                    self.drawCurrent = { x: x, y: y };
                    self.renderOverlay();
                } else if (self.mode === 'moving' && self.selectedKeyframe) {
                    // Move the bbox
                    var track = self.tracks[self.selectedKeyframe.trackId];
                    if (track && track.keyframes[self.selectedKeyframe.frame]) {
                        var bbox = track.keyframes[self.selectedKeyframe.frame].bbox;
                        bbox.x = x - self.dragOffset.x;
                        bbox.y = y - self.dragOffset.y;
                        self.renderOverlay();
                    }
                } else if (self.mode === 'resizing' && self.selectedKeyframe) {
                    self._handleResize(x, y);
                } else {
                    // Update cursor based on what we're hovering
                    self._updateCursor(x, y);
                }
            });

            this.canvas.addEventListener('mouseup', function(e) {
                var coords = self._getCanvasCoords(e);
                var x = coords.x;
                var y = coords.y;

                if (self.mode === 'drawing') {
                    var bbox = {
                        x: Math.min(self.drawStart.x, x),
                        y: Math.min(self.drawStart.y, y),
                        width: Math.abs(x - self.drawStart.x),
                        height: Math.abs(y - self.drawStart.y)
                    };

                    if (bbox.width > 5 && bbox.height > 5) {
                        self.addKeyframe(bbox);
                    }
                }

                // Reset state
                self.mode = 'idle';
                self.drawStart = null;
                self.drawCurrent = null;
                self.dragStart = null;
                self.dragOffset = null;
                self.resizeHandle = null;
                self.originalBbox = null;
                self.canvas.style.cursor = 'default';

                self._renderTrackPanel();
                self.renderOverlay();
            });

            this.canvas.addEventListener('mouseleave', function() {
                if (self.mode !== 'idle') {
                    // Cancel current operation
                    if (self.mode === 'moving' || self.mode === 'resizing') {
                        // Restore original bbox
                        if (self.selectedKeyframe && self.originalBbox) {
                            var track = self.tracks[self.selectedKeyframe.trackId];
                            if (track && track.keyframes[self.selectedKeyframe.frame]) {
                                track.keyframes[self.selectedKeyframe.frame].bbox = { ...self.originalBbox };
                            }
                        }
                    }
                    self.mode = 'idle';
                    self.drawStart = null;
                    self.drawCurrent = null;
                    self.dragStart = null;
                    self.dragOffset = null;
                    self.resizeHandle = null;
                    self.originalBbox = null;
                    self.renderOverlay();
                }
            });
        }

        _handleResize(x, y) {
            if (!this.selectedKeyframe || !this.originalBbox) return;

            var track = this.tracks[this.selectedKeyframe.trackId];
            if (!track || !track.keyframes[this.selectedKeyframe.frame]) return;

            var bbox = track.keyframes[this.selectedKeyframe.frame].bbox;
            var orig = this.originalBbox;
            var handle = this.resizeHandle;

            // Calculate new dimensions based on handle being dragged
            var newX = orig.x, newY = orig.y;
            var newW = orig.width, newH = orig.height;

            if (handle.includes('w')) {
                newX = Math.min(x, orig.x + orig.width - 10);
                newW = orig.x + orig.width - newX;
            }
            if (handle.includes('e')) {
                newW = Math.max(10, x - orig.x);
            }
            if (handle.includes('n')) {
                newY = Math.min(y, orig.y + orig.height - 10);
                newH = orig.y + orig.height - newY;
            }
            if (handle.includes('s')) {
                newH = Math.max(10, y - orig.y);
            }

            bbox.x = newX;
            bbox.y = newY;
            bbox.width = newW;
            bbox.height = newH;

            this.renderOverlay();
        }

        _updateCursor(x, y) {
            var currentFrame = this._getCurrentFrame();

            // Check for resize handles on selected keyframe
            if (this.selectedKeyframe && this.selectedKeyframe.frame === currentFrame) {
                var track = this.tracks[this.selectedKeyframe.trackId];
                if (track && track.keyframes[currentFrame]) {
                    var bbox = track.keyframes[currentFrame].bbox;
                    var handle = this._hitTestHandle(x, y, bbox);
                    if (handle) {
                        var cursorMap = {
                            nw: 'nw-resize', ne: 'ne-resize', sw: 'sw-resize', se: 'se-resize',
                            n: 'n-resize', s: 's-resize', e: 'e-resize', w: 'w-resize'
                        };
                        this.canvas.style.cursor = cursorMap[handle];
                        return;
                    }
                }
            }

            // Check if hovering over a bbox
            var hit = this._findBboxAtPoint(x, y);
            if (hit) {
                this.canvas.style.cursor = 'move';
            } else {
                this.canvas.style.cursor = 'crosshair';
            }
        }

        _bindKeyboardEvents() {
            var self = this;

            document.addEventListener('keydown', function(e) {
                // Delete key removes selected keyframe
                if ((e.key === 'Delete' || e.key === 'Backspace') && self.selectedKeyframe) {
                    // Make sure we're focused on the canvas area
                    if (document.activeElement.tagName !== 'INPUT' &&
                        document.activeElement.tagName !== 'TEXTAREA') {
                        e.preventDefault();
                        self.deleteSelectedKeyframe();
                    }
                }

                // Escape deselects
                if (e.key === 'Escape') {
                    self.selectedKeyframe = null;
                    self.renderOverlay();
                }
            });
        }

        _getCurrentFrame() {
            if (this.manager && this.manager.getCurrentFrame) {
                return this.manager.getCurrentFrame();
            }
            if (this.video) {
                var fps = this.config.videoFps || 30;
                return Math.round(this.video.currentTime * fps);
            }
            return 0;
        }

        _renderTrackPanel() {
            // Find or create track panel
            var panel = document.querySelector('.tracking-panel');
            if (!panel) return;

            var list = panel.querySelector('.tracking-track-list');
            if (!list) return;

            var trackIds = Object.keys(this.tracks);
            if (trackIds.length === 0) {
                list.innerHTML = '<p class="tracking-no-tracks">No tracks. Select a label, then click "+ Track" to start.</p>';
                return;
            }

            var html = '';
            var self = this;

            for (var i = 0; i < trackIds.length; i++) {
                var track = this.tracks[trackIds[i]];
                var isActive = track.id === this.activeTrackId;
                var kfCount = Object.keys(track.keyframes).length;

                html += '<div class="tracking-track-item' + (isActive ? ' active' : '') + '" data-track-id="' + track.id + '">';
                html += '<span class="tracking-track-color" style="background:' + track.color + '"></span>';
                html += '<span class="tracking-track-label">' + track.label + '</span>';
                html += '<span class="tracking-track-info">' + kfCount + ' kf, ' + track.interpolation + '</span>';
                html += '<button class="tracking-track-delete" data-track-id="' + track.id + '">&times;</button>';
                html += '</div>';
            }

            list.innerHTML = html;

            // Bind events
            list.querySelectorAll('.tracking-track-item').forEach(function(item) {
                item.addEventListener('click', function(e) {
                    if (!e.target.closest('.tracking-track-delete')) {
                        self.activeTrackId = item.dataset.trackId;
                        self._updateCanvasPointerEvents();
                        self._renderTrackPanel();
                        self.renderOverlay();
                    }
                });
            });

            list.querySelectorAll('.tracking-track-delete').forEach(function(btn) {
                btn.addEventListener('click', function(e) {
                    e.stopPropagation();
                    self.deleteTrack(btn.dataset.trackId);
                });
            });
        }
    }

    // Expose globally
    window.TrackingUIManager = TrackingUIManager;
})();

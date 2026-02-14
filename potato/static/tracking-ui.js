/**
 * Tracking UI Manager
 *
 * Provides interactive bbox drawing on video canvas for object tracking,
 * a track management panel, and integration with the interpolation engine.
 */

(function() {
    'use strict';

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
            this.isDrawing = false;
            this.drawStart = null;
            this.autoAdvanceFrames = this.config.autoAdvanceFrames || 5;
            this.defaultInterpolation = this.config.interpolation || 'linear';

            if (this.canvas) {
                this._bindCanvasEvents();
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
            this._renderTrackPanel();
            return id;
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
            var frames = Object.keys(track.keyframes).map(Number);
            track.startFrame = Math.min.apply(null, frames);
            track.endFrame = Math.max.apply(null, frames);

            this._renderTrackPanel();
            this.renderOverlay();

            // Auto-advance
            if (this.autoAdvanceFrames > 0 && this.manager) {
                for (var i = 0; i < this.autoAdvanceFrames; i++) {
                    if (this.manager.stepFrame) {
                        this.manager.stepFrame(1);
                    }
                }
            }
        }

        /**
         * Delete a keyframe from a track.
         */
        deleteKeyframe(trackId, frame) {
            var track = this.tracks[trackId];
            if (!track) return;
            delete track.keyframes[frame];

            var frames = Object.keys(track.keyframes).map(Number);
            if (frames.length > 0) {
                track.startFrame = Math.min.apply(null, frames);
                track.endFrame = Math.max.apply(null, frames);
            }

            this._renderTrackPanel();
            this.renderOverlay();
        }

        /**
         * Delete an entire track.
         */
        deleteTrack(trackId) {
            delete this.tracks[trackId];
            if (this.activeTrackId === trackId) {
                this.activeTrackId = null;
            }
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

                // Use interpolation engine if available
                if (window.TrackingInterpolationEngine) {
                    bbox = window.TrackingInterpolationEngine.interpolate(track, currentFrame);
                } else {
                    // Fallback: only show exact keyframes
                    var kf = track.keyframes[currentFrame];
                    if (kf) bbox = kf.bbox;
                }

                if (bbox) {
                    var isActive = trackId === this.activeTrackId;
                    this._drawBbox(bbox, track.color, track.label, isActive);

                    // Mark if this is a keyframe
                    if (track.keyframes[currentFrame]) {
                        this._drawKeyframeDiamond(bbox, track.color);
                    }
                }
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

        _drawBbox(bbox, color, label, isActive) {
            this.ctx.strokeStyle = color;
            this.ctx.lineWidth = isActive ? 3 : 2;
            if (!isActive) {
                this.ctx.setLineDash([4, 4]);
            } else {
                this.ctx.setLineDash([]);
            }
            this.ctx.strokeRect(bbox.x, bbox.y, bbox.width, bbox.height);
            this.ctx.setLineDash([]);

            // Label
            this.ctx.font = '11px Arial';
            var textWidth = this.ctx.measureText(label).width;
            this.ctx.fillStyle = color;
            this.ctx.fillRect(bbox.x, bbox.y - 16, textWidth + 6, 16);
            this.ctx.fillStyle = '#fff';
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

        // --- Canvas interaction for bbox drawing ---

        _bindCanvasEvents() {
            var self = this;

            this.canvas.addEventListener('mousedown', function(e) {
                if (!self.activeTrackId) return;
                self.isDrawing = true;
                var rect = self.canvas.getBoundingClientRect();
                self.drawStart = {
                    x: e.clientX - rect.left,
                    y: e.clientY - rect.top
                };
                self.canvas.style.cursor = 'crosshair';
            });

            this.canvas.addEventListener('mousemove', function(e) {
                if (!self.isDrawing || !self.drawStart) return;
                var rect = self.canvas.getBoundingClientRect();
                var x = e.clientX - rect.left;
                var y = e.clientY - rect.top;

                // Render current state + drawing preview
                self.renderOverlay();
                self.ctx.strokeStyle = '#FFD700';
                self.ctx.lineWidth = 2;
                self.ctx.setLineDash([6, 3]);
                self.ctx.strokeRect(
                    self.drawStart.x, self.drawStart.y,
                    x - self.drawStart.x, y - self.drawStart.y
                );
                self.ctx.setLineDash([]);
            });

            this.canvas.addEventListener('mouseup', function(e) {
                if (!self.isDrawing || !self.drawStart) return;
                self.isDrawing = false;
                self.canvas.style.cursor = 'default';

                var rect = self.canvas.getBoundingClientRect();
                var x = e.clientX - rect.left;
                var y = e.clientY - rect.top;

                var bbox = {
                    x: Math.min(self.drawStart.x, x),
                    y: Math.min(self.drawStart.y, y),
                    width: Math.abs(x - self.drawStart.x),
                    height: Math.abs(y - self.drawStart.y)
                };

                if (bbox.width > 5 && bbox.height > 5) {
                    self.addKeyframe(bbox);
                }

                self.drawStart = null;
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
                list.innerHTML = '<p class="tracking-no-tracks">No tracks. Create a track to start.</p>';
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

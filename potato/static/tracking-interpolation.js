/**
 * Tracking Interpolation Engine
 *
 * Provides interpolation between keyframes for video object tracking.
 * Supports linear, cubic (Catmull-Rom), and constant interpolation.
 *
 * Given a set of keyframes with bounding boxes at specific frames,
 * computes interpolated bounding boxes for intermediate frames.
 */

(function() {
    'use strict';

    var TrackingInterpolationEngine = {

        /**
         * Interpolate a bounding box at the given frame for a tracked object.
         *
         * @param {Object} trackObj - Track object with keyframes map
         * @param {number} frame - The frame number to interpolate at
         * @returns {Object|null} Interpolated bbox {x, y, width, height} or null if out of range
         */
        interpolate: function(trackObj, frame) {
            if (!trackObj || !trackObj.keyframes) return null;

            var keyframes = trackObj.keyframes;
            var interpolationType = trackObj.interpolation || 'linear';
            var frames = Object.keys(keyframes).map(Number).sort(function(a, b) { return a - b; });

            if (frames.length === 0) return null;
            if (frames.length === 1) {
                return this._cloneBbox(keyframes[frames[0]].bbox);
            }

            // Check if frame is on a keyframe
            if (keyframes[frame]) {
                return this._cloneBbox(keyframes[frame].bbox);
            }

            // Check bounds
            var startFrame = trackObj.startFrame !== undefined ? trackObj.startFrame : frames[0];
            var endFrame = trackObj.endFrame !== undefined ? trackObj.endFrame : frames[frames.length - 1];

            if (frame < startFrame || frame > endFrame) return null;

            // Find surrounding keyframes
            var prevFrame = null;
            var nextFrame = null;
            for (var i = 0; i < frames.length; i++) {
                if (frames[i] <= frame) prevFrame = frames[i];
                if (frames[i] > frame && nextFrame === null) nextFrame = frames[i];
            }

            if (prevFrame === null || nextFrame === null) {
                // Extrapolate: hold last known position
                if (prevFrame !== null) return this._cloneBbox(keyframes[prevFrame].bbox);
                if (nextFrame !== null) return this._cloneBbox(keyframes[nextFrame].bbox);
                return null;
            }

            var t = (frame - prevFrame) / (nextFrame - prevFrame);

            switch (interpolationType) {
                case 'cubic':
                    return this._cubicInterpolate(keyframes, frames, prevFrame, nextFrame, t);
                case 'constant':
                    return this._cloneBbox(keyframes[prevFrame].bbox);
                case 'linear':
                default:
                    return this._linearInterpolate(
                        keyframes[prevFrame].bbox,
                        keyframes[nextFrame].bbox,
                        t
                    );
            }
        },

        /**
         * Linear interpolation between two bboxes.
         */
        _linearInterpolate: function(bbox1, bbox2, t) {
            return {
                x: bbox1.x + (bbox2.x - bbox1.x) * t,
                y: bbox1.y + (bbox2.y - bbox1.y) * t,
                width: bbox1.width + (bbox2.width - bbox1.width) * t,
                height: bbox1.height + (bbox2.height - bbox1.height) * t
            };
        },

        /**
         * Cubic (Catmull-Rom) interpolation using surrounding keyframes.
         */
        _cubicInterpolate: function(keyframes, frames, prevFrame, nextFrame, t) {
            // Find prev-prev and next-next frames for Catmull-Rom
            var prevIdx = frames.indexOf(prevFrame);
            var nextIdx = frames.indexOf(nextFrame);

            var p0Frame = prevIdx > 0 ? frames[prevIdx - 1] : prevFrame;
            var p3Frame = nextIdx < frames.length - 1 ? frames[nextIdx + 1] : nextFrame;

            var p0 = keyframes[p0Frame].bbox;
            var p1 = keyframes[prevFrame].bbox;
            var p2 = keyframes[nextFrame].bbox;
            var p3 = keyframes[p3Frame].bbox;

            return {
                x: this._catmullRom(p0.x, p1.x, p2.x, p3.x, t),
                y: this._catmullRom(p0.y, p1.y, p2.y, p3.y, t),
                width: Math.max(1, this._catmullRom(p0.width, p1.width, p2.width, p3.width, t)),
                height: Math.max(1, this._catmullRom(p0.height, p1.height, p2.height, p3.height, t))
            };
        },

        /**
         * Catmull-Rom spline interpolation for a single value.
         * @param {number} p0 - Value before start
         * @param {number} p1 - Start value
         * @param {number} p2 - End value
         * @param {number} p3 - Value after end
         * @param {number} t - Parameter [0, 1]
         * @returns {number}
         */
        _catmullRom: function(p0, p1, p2, p3, t) {
            var t2 = t * t;
            var t3 = t2 * t;
            return 0.5 * (
                (2 * p1) +
                (-p0 + p2) * t +
                (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 +
                (-p0 + 3 * p1 - 3 * p2 + p3) * t3
            );
        },

        /**
         * Clone a bbox object.
         */
        _cloneBbox: function(bbox) {
            return { x: bbox.x, y: bbox.y, width: bbox.width, height: bbox.height };
        },

        /**
         * Get all frames where this track has a visible bbox (keyframe or interpolated).
         *
         * @param {Object} trackObj - Track object
         * @returns {Object} {startFrame, endFrame}
         */
        getTrackRange: function(trackObj) {
            if (!trackObj || !trackObj.keyframes) return null;
            var frames = Object.keys(trackObj.keyframes).map(Number).sort(function(a, b) { return a - b; });
            if (frames.length === 0) return null;
            return {
                startFrame: trackObj.startFrame !== undefined ? trackObj.startFrame : frames[0],
                endFrame: trackObj.endFrame !== undefined ? trackObj.endFrame : frames[frames.length - 1]
            };
        },

        /**
         * Get keyframe numbers for a track.
         */
        getKeyframes: function(trackObj) {
            if (!trackObj || !trackObj.keyframes) return [];
            return Object.keys(trackObj.keyframes).map(Number).sort(function(a, b) { return a - b; });
        }
    };

    // Expose globally
    window.TrackingInterpolationEngine = TrackingInterpolationEngine;
})();

/**
 * Tracking Interpolation Engine
 *
 * Interpolates a tracked object's shape between keyframes. Given keyframes at
 * frames 0 and 30, it answers "what does this object look like at frame 17?"
 *
 * Supports three shape kinds, because a track is not always a box:
 *
 *   bbox     - linear, cubic (Catmull-Rom) or constant interpolation
 *   polygon  - vertex correspondence by ARC-LENGTH RESAMPLING (see below)
 *   mask     - nearest-keyframe hold, deliberately
 *
 * ## Why polygons need resampling
 *
 * Two polygons of the same object on different frames almost never have the
 * same number of vertices, and even when they do, vertex i of one is not
 * vertex i of the other -- an annotator who starts tracing at the nose on one
 * frame and the tail on the next produces two correct outlines whose vertices
 * correspond to nothing. Interpolating them pairwise makes the shape turn
 * inside out halfway between keyframes.
 *
 * So both polygons are resampled to the same number of points at equal
 * fractions of their perimeter, and the start point of the second is rotated
 * to whichever offset best matches the first. That gives a correspondence that
 * survives different vertex counts and different starting points.
 *
 * ## Why masks are held, not blended
 *
 * Blending two rasters pixel-wise produces a shape that is neither -- ghost
 * regions where the object was and where it will be, and holes in between. The
 * honest options are a signed-distance-field morph (real work, and still wrong
 * for topology changes) or holding the nearest keyframe. This holds, and
 * reports `interpolated: false` so the UI can show that the frame is not a
 * real annotation rather than presenting a guess as data.
 */

(function() {
    'use strict';

    //: How many points a resampled polygon carries. High enough that the
    //: outline is visually unchanged, low enough to interpolate per frame.
    var RESAMPLE_POINTS = 64;

    var TrackingInterpolationEngine = {

        /**
         * Interpolate a tracked shape at the given frame.
         *
         * @param {Object} trackObj - Track with a keyframes map
         * @param {number} frame - Frame number
         * @returns {Object|null} Interpolated bbox, or null if out of range.
         *     Kept returning a bare bbox for backwards compatibility; callers
         *     that need polygons or masks use interpolateShape().
         */
        interpolate: function(trackObj, frame) {
            var shape = this.interpolateShape(trackObj, frame);
            if (!shape) return null;
            if (shape.type === 'bbox') return shape.bbox;
            // A polygon or mask still has a bounding box, which is what the
            // older bbox-only callers want.
            return shape.bbox || null;
        },

        /**
         * Interpolate a tracked shape, preserving its kind.
         *
         * @param {Object} trackObj - Track with a keyframes map
         * @param {number} frame - Frame number
         * @returns {Object|null} {type, bbox, points?, rle?, interpolated}
         */
        interpolateShape: function(trackObj, frame) {
            if (!trackObj || !trackObj.keyframes) return null;

            var keyframes = trackObj.keyframes;
            var frames = Object.keys(keyframes).map(Number).sort(function(a, b) {
                return a - b;
            });
            if (frames.length === 0) return null;

            if (keyframes[frame]) {
                return this._shapeOf(keyframes[frame], true);
            }
            if (frames.length === 1) {
                return this._shapeOf(keyframes[frames[0]], false);
            }

            var startFrame = trackObj.startFrame !== undefined
                ? trackObj.startFrame : frames[0];
            var endFrame = trackObj.endFrame !== undefined
                ? trackObj.endFrame : frames[frames.length - 1];
            if (frame < startFrame || frame > endFrame) return null;

            var prevFrame = null;
            var nextFrame = null;
            for (var i = 0; i < frames.length; i++) {
                if (frames[i] <= frame) prevFrame = frames[i];
                if (frames[i] > frame && nextFrame === null) nextFrame = frames[i];
            }

            if (prevFrame === null || nextFrame === null) {
                // Outside the keyframed span: hold the nearest known shape.
                var edge = prevFrame !== null ? prevFrame : nextFrame;
                if (edge === null) return null;
                return this._shapeOf(keyframes[edge], false);
            }

            var t = (frame - prevFrame) / (nextFrame - prevFrame);
            var from = keyframes[prevFrame];
            var to = keyframes[nextFrame];
            var kind = this._kindOf(from);

            // A track whose shape kind CHANGES between keyframes cannot be
            // interpolated -- there is no meaningful path from a polygon to a
            // mask. Hold rather than invent one.
            if (kind !== this._kindOf(to)) {
                return this._shapeOf(from, false);
            }

            if (kind === 'mask') {
                // Nearest keyframe, not a blend. See the header note.
                return this._shapeOf(t < 0.5 ? from : to, false);
            }

            if (kind === 'polygon') {
                var points = this._interpolatePolygon(
                    this._pointsOf(from), this._pointsOf(to), t);
                if (!points) return this._shapeOf(from, false);
                return {
                    type: 'polygon',
                    points: points,
                    bbox: this._bboxOfPoints(points),
                    interpolated: true
                };
            }

            var interpolationType = trackObj.interpolation || 'linear';
            var bbox;
            switch (interpolationType) {
                case 'cubic':
                    bbox = this._cubicInterpolate(
                        keyframes, frames, prevFrame, nextFrame, t);
                    break;
                case 'constant':
                    bbox = this._cloneBbox(from.bbox);
                    break;
                case 'linear':
                default:
                    bbox = this._linearInterpolate(from.bbox, to.bbox, t);
            }
            return { type: 'bbox', bbox: bbox, interpolated: true };
        },

        // ------------------------------------------------------------------
        // Shape kinds
        // ------------------------------------------------------------------

        _kindOf: function(keyframe) {
            if (!keyframe) return 'bbox';
            if (keyframe.rle) return 'mask';
            if (keyframe.points && keyframe.points.length >= 3) return 'polygon';
            if (keyframe.type) return keyframe.type;
            return 'bbox';
        },

        _pointsOf: function(keyframe) {
            return (keyframe && keyframe.points) || [];
        },

        _shapeOf: function(keyframe, isKeyframe) {
            if (!keyframe) return null;
            var kind = this._kindOf(keyframe);
            if (kind === 'mask') {
                return {
                    type: 'mask',
                    rle: keyframe.rle,
                    bbox: keyframe.bbox ? this._cloneBbox(keyframe.bbox) : null,
                    interpolated: false
                };
            }
            if (kind === 'polygon') {
                var points = this._pointsOf(keyframe).map(function(p) {
                    return { x: p.x, y: p.y };
                });
                return {
                    type: 'polygon',
                    points: points,
                    bbox: keyframe.bbox
                        ? this._cloneBbox(keyframe.bbox)
                        : this._bboxOfPoints(points),
                    interpolated: false
                };
            }
            return {
                type: 'bbox',
                bbox: this._cloneBbox(keyframe.bbox),
                interpolated: !isKeyframe
            };
        },

        // ------------------------------------------------------------------
        // Polygons
        // ------------------------------------------------------------------

        /**
         * Interpolate between two polygon outlines.
         *
         * Both are resampled to RESAMPLE_POINTS at equal fractions of their
         * perimeter, and the second is rotated to the start offset that best
         * matches the first, so vertex counts and tracing start points need
         * not agree between keyframes.
         */
        _interpolatePolygon: function(fromPoints, toPoints, t) {
            if (!fromPoints || !toPoints) return null;
            if (fromPoints.length < 3 || toPoints.length < 3) return null;

            var a = this._resample(fromPoints, RESAMPLE_POINTS);
            var b = this._resample(toPoints, RESAMPLE_POINTS);
            if (!a || !b) return null;

            b = this._alignRotation(a, b);

            var out = new Array(a.length);
            for (var i = 0; i < a.length; i++) {
                out[i] = {
                    x: a[i].x + (b[i].x - a[i].x) * t,
                    y: a[i].y + (b[i].y - a[i].y) * t
                };
            }
            return out;
        },

        /**
         * Resample a closed polygon to `count` points at equal perimeter
         * fractions. This is what makes two outlines with different vertex
         * counts comparable at all.
         */
        _resample: function(points, count) {
            var n = points.length;
            if (n < 3) return null;

            // Cumulative perimeter, closing the ring back to the first point.
            var cumulative = [0];
            var total = 0;
            for (var i = 0; i < n; i++) {
                var p = points[i];
                var q = points[(i + 1) % n];
                total += Math.sqrt(
                    (q.x - p.x) * (q.x - p.x) + (q.y - p.y) * (q.y - p.y));
                cumulative.push(total);
            }
            // A degenerate ring (all points identical) has no arc length to
            // walk along; dividing by it would produce NaN coordinates.
            if (total <= 0) return null;

            var out = new Array(count);
            var segment = 0;
            for (var k = 0; k < count; k++) {
                var target = (k / count) * total;
                while (segment < n - 1 && cumulative[segment + 1] < target) {
                    segment++;
                }
                var segStart = cumulative[segment];
                var segLength = cumulative[segment + 1] - segStart;
                var u = segLength > 0 ? (target - segStart) / segLength : 0;
                var from = points[segment];
                var to = points[(segment + 1) % n];
                out[k] = {
                    x: from.x + (to.x - from.x) * u,
                    y: from.y + (to.y - from.y) * u
                };
            }
            return out;
        },

        /**
         * Rotate `b` to the start offset that minimises total distance to `a`.
         *
         * Without this, an annotator who began tracing at a different point on
         * the second keyframe produces a polygon that appears to spin as it
         * interpolates -- correct outlines, meaningless correspondence.
         */
        _alignRotation: function(a, b) {
            var n = a.length;
            var bestOffset = 0;
            var bestCost = Infinity;
            for (var offset = 0; offset < n; offset++) {
                var cost = 0;
                for (var i = 0; i < n; i++) {
                    var p = a[i];
                    var q = b[(i + offset) % n];
                    var dx = q.x - p.x;
                    var dy = q.y - p.y;
                    cost += dx * dx + dy * dy;
                    if (cost >= bestCost) break;   // early out
                }
                if (cost < bestCost) {
                    bestCost = cost;
                    bestOffset = offset;
                }
            }
            if (bestOffset === 0) return b;
            var rotated = new Array(n);
            for (var j = 0; j < n; j++) {
                rotated[j] = b[(j + bestOffset) % n];
            }
            return rotated;
        },

        _bboxOfPoints: function(points) {
            if (!points || points.length === 0) return null;
            var minX = points[0].x, maxX = points[0].x;
            var minY = points[0].y, maxY = points[0].y;
            for (var i = 1; i < points.length; i++) {
                if (points[i].x < minX) minX = points[i].x;
                if (points[i].x > maxX) maxX = points[i].x;
                if (points[i].y < minY) minY = points[i].y;
                if (points[i].y > maxY) maxY = points[i].y;
            }
            return { x: minX, y: minY, width: maxX - minX, height: maxY - minY };
        },

        // ------------------------------------------------------------------
        // Boxes
        // ------------------------------------------------------------------

        _linearInterpolate: function(bbox1, bbox2, t) {
            return {
                x: bbox1.x + (bbox2.x - bbox1.x) * t,
                y: bbox1.y + (bbox2.y - bbox1.y) * t,
                width: bbox1.width + (bbox2.width - bbox1.width) * t,
                height: bbox1.height + (bbox2.height - bbox1.height) * t
            };
        },

        _cubicInterpolate: function(keyframes, frames, prevFrame, nextFrame, t) {
            var prevIdx = frames.indexOf(prevFrame);
            var nextIdx = frames.indexOf(nextFrame);

            var p0Frame = prevIdx > 0 ? frames[prevIdx - 1] : prevFrame;
            var p3Frame = nextIdx < frames.length - 1
                ? frames[nextIdx + 1] : nextFrame;

            var p0 = keyframes[p0Frame].bbox;
            var p1 = keyframes[prevFrame].bbox;
            var p2 = keyframes[nextFrame].bbox;
            var p3 = keyframes[p3Frame].bbox;

            return {
                x: this._catmullRom(p0.x, p1.x, p2.x, p3.x, t),
                y: this._catmullRom(p0.y, p1.y, p2.y, p3.y, t),
                width: Math.max(1, this._catmullRom(
                    p0.width, p1.width, p2.width, p3.width, t)),
                height: Math.max(1, this._catmullRom(
                    p0.height, p1.height, p2.height, p3.height, t))
            };
        },

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

        _cloneBbox: function(bbox) {
            if (!bbox) return null;
            return {
                x: bbox.x, y: bbox.y,
                width: bbox.width, height: bbox.height
            };
        },

        // ------------------------------------------------------------------
        // Track metadata
        // ------------------------------------------------------------------

        getTrackRange: function(trackObj) {
            if (!trackObj || !trackObj.keyframes) return null;
            var frames = Object.keys(trackObj.keyframes).map(Number)
                .sort(function(a, b) { return a - b; });
            if (frames.length === 0) return null;
            return {
                startFrame: trackObj.startFrame !== undefined
                    ? trackObj.startFrame : frames[0],
                endFrame: trackObj.endFrame !== undefined
                    ? trackObj.endFrame : frames[frames.length - 1]
            };
        },

        getKeyframes: function(trackObj) {
            if (!trackObj || !trackObj.keyframes) return [];
            return Object.keys(trackObj.keyframes).map(Number)
                .sort(function(a, b) { return a - b; });
        },

        /**
         * Which shape kind a track holds, for UI and export decisions.
         * A track whose keyframes disagree reports 'mixed'.
         */
        getTrackKind: function(trackObj) {
            var frames = this.getKeyframes(trackObj);
            if (frames.length === 0) return null;
            var kinds = {};
            for (var i = 0; i < frames.length; i++) {
                kinds[this._kindOf(trackObj.keyframes[frames[i]])] = true;
            }
            var names = Object.keys(kinds);
            return names.length === 1 ? names[0] : 'mixed';
        }
    };

    window.TrackingInterpolationEngine = TrackingInterpolationEngine;
})();

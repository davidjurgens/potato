/**
 * Peaks.js range-selection helper (shared by audio + video annotation).
 *
 * Adds right-click-drag range creation to a Peaks.js view container, plus
 * optional edge auto-scroll so a drag can extend past the visible window.
 *
 * Gesture model (consistent across zoomview and overview):
 *   - LEFT click / drag  -> left to Peaks.js for seeking / navigation
 *   - RIGHT click + drag  -> create an annotation segment
 *
 * On the zoomview, x maps to time within the *visible* window; on the
 * overview (opts.fullDuration), x maps across the whole clip so the entire
 * media is annotatable without first zooming to it.
 *
 * Usage:
 *   const detach = attachPeaksRangeSelection(peaks, zoomEl, 'zoomview', {
 *       onCreate: (start, end) => manager.createSegment(start, end),
 *       edgeScroll: true,
 *   });
 */
(function () {
    'use strict';

    // Peaks.js's UMD bundle exports lowercase `peaks` on window; the audio/video
    // managers expect uppercase `Peaks`. Normalize here (this file loads right
    // after peaks.min.js and before both managers) so the video timeline — which
    // has no alias of its own — initializes instead of silently disabling Peaks.
    if (typeof window.Peaks === 'undefined' && typeof window.peaks !== 'undefined') {
        window.Peaks = window.peaks;
    }

    function clamp(v, lo, hi) {
        return Math.max(lo, Math.min(hi, v));
    }

    /**
     * @param {Object} peaks        Peaks.js instance
     * @param {HTMLElement} containerEl  the view's DOM container
     * @param {string} viewName     'zoomview' | 'overview'
     * @param {Object} opts
     * @param {function(number, number)} opts.onCreate  (startTime, endTime) on a valid drag
     * @param {boolean} [opts.fullDuration=false]  map x across the whole clip (overview)
     * @param {boolean} [opts.edgeScroll=false]    auto-pan the view near the edges (zoomview)
     * @param {number}  [opts.minDuration=0.1]     minimum segment length (seconds)
     * @param {number}  [opts.edgeZone=40]         px from an edge that triggers auto-scroll
     * @param {string}  [opts.previewColor]        preview segment fill
     * @returns {function} detach function
     */
    function attachPeaksRangeSelection(peaks, containerEl, viewName, opts) {
        opts = opts || {};
        if (!peaks || !containerEl) return function () {};

        var minDuration = opts.minDuration != null ? opts.minDuration : 0.1;
        var edgeZone = opts.edgeZone != null ? opts.edgeZone : 40;
        var previewColor = opts.previewColor || 'rgba(100, 100, 255, 0.35)';

        var isDragging = false;
        var dragStartTime = null;
        var previewSegment = null;
        var lastClientX = 0;
        var rafId = null;

        function getView() {
            try {
                return peaks.views.getView(viewName);
            } catch (e) {
                return null;
            }
        }

        function timeFromClientX(clientX) {
            var rect = containerEl.getBoundingClientRect();
            if (!rect.width) return null;
            var x = clamp(clientX - rect.left, 0, rect.width);
            var duration = peaks.player.getDuration() || 0;
            if (!duration) return null;

            if (opts.fullDuration) {
                return clamp((x / rect.width) * duration, 0, duration);
            }
            var view = getView();
            if (!view) return null;
            var startTime = view.getStartTime();
            var visible = view.getEndTime() - startTime;
            return clamp(startTime + (x / rect.width) * visible, 0, duration);
        }

        function updatePreview(a, b) {
            var start = Math.min(a, b);
            var end = Math.max(a, b);
            removePreview();
            if (end - start < 0.01) return;
            try {
                previewSegment = peaks.segments.add({
                    id: 'range-preview-' + viewName,
                    startTime: start,
                    endTime: end,
                    color: previewColor,
                    editable: false
                });
            } catch (e) {
                previewSegment = null;
            }
        }

        function removePreview() {
            if (previewSegment) {
                try {
                    peaks.segments.removeById(previewSegment.id);
                } catch (e) {}
                previewSegment = null;
            }
        }

        function stopAutoScroll() {
            if (rafId !== null) {
                cancelAnimationFrame(rafId);
                rafId = null;
            }
        }

        function autoScrollTick() {
            rafId = null;
            if (!opts.edgeScroll || !isDragging) return;

            var view = getView();
            var duration = peaks.player.getDuration() || 0;
            if (!view || !duration) return;

            var rect = containerEl.getBoundingClientRect();
            var x = lastClientX - rect.left;
            var visible = view.getEndTime() - view.getStartTime();
            var maxStart = Math.max(0, duration - visible);

            var dir = 0;
            var depth = 0;
            if (x < edgeZone) {
                dir = -1;
                depth = (edgeZone - x) / edgeZone;
            } else if (x > rect.width - edgeZone) {
                dir = 1;
                depth = (x - (rect.width - edgeZone)) / edgeZone;
            }

            if (dir === 0) return; // pointer left the edge zone; loop pauses until next move

            // Pan a fraction of the visible window per frame, scaled by edge depth.
            var step = dir * clamp(depth, 0, 1) * visible * 0.03;
            var newStart = clamp(view.getStartTime() + step, 0, maxStart);
            if (newStart !== view.getStartTime()) {
                view.setStartTime(newStart);
            }
            // Extend the selection to the pointer's time in the newly shifted window.
            var t = timeFromClientX(lastClientX);
            if (t !== null && dragStartTime !== null) {
                updatePreview(dragStartTime, t);
            }
            rafId = requestAnimationFrame(autoScrollTick);
        }

        function maybeStartAutoScroll() {
            if (opts.edgeScroll && isDragging && rafId === null) {
                rafId = requestAnimationFrame(autoScrollTick);
            }
        }

        function onMouseDown(e) {
            if (e.button !== 2) return; // right-click only; left-click stays with Peaks
            var t = timeFromClientX(e.clientX);
            if (t === null) return;
            isDragging = true;
            dragStartTime = t;
            lastClientX = e.clientX;
            e.preventDefault();
            e.stopPropagation();
        }

        function onMouseMove(e) {
            if (!isDragging || dragStartTime === null) return;
            lastClientX = e.clientX;
            var t = timeFromClientX(e.clientX);
            if (t !== null) updatePreview(dragStartTime, t);
            maybeStartAutoScroll();
        }

        function finishDrag(e) {
            if (!isDragging || dragStartTime === null) return;
            stopAutoScroll();
            var endTime = timeFromClientX(e ? e.clientX : lastClientX);
            removePreview();
            if (endTime !== null) {
                var start = Math.min(dragStartTime, endTime);
                var end = Math.max(dragStartTime, endTime);
                if (end - start >= minDuration && typeof opts.onCreate === 'function') {
                    opts.onCreate(start, end);
                }
            }
            isDragging = false;
            dragStartTime = null;
        }

        function onContextMenu(e) {
            e.preventDefault();
            return false;
        }

        // Mousedown/contextmenu are container-local; move/up go on window so a
        // drag that runs off the container edge still tracks (needed for edge scroll).
        containerEl.addEventListener('mousedown', onMouseDown);
        containerEl.addEventListener('contextmenu', onContextMenu);
        window.addEventListener('mousemove', onMouseMove);
        window.addEventListener('mouseup', finishDrag);

        return function detach() {
            stopAutoScroll();
            removePreview();
            containerEl.removeEventListener('mousedown', onMouseDown);
            containerEl.removeEventListener('contextmenu', onContextMenu);
            window.removeEventListener('mousemove', onMouseMove);
            window.removeEventListener('mouseup', finishDrag);
        };
    }

    window.attachPeaksRangeSelection = attachPeaksRangeSelection;
})();

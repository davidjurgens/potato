/**
 * Deep-zoom backend for image annotation: OpenSeadragon under, fabric over.
 *
 * ## The one idea this rests on
 *
 * In the ordinary viewer, fabric holds the image as an object with a position
 * and a scale, and annotations are drawn in *canvas* coordinates that happen to
 * sit on top of it. That cannot work for a tiled image, because there is no
 * single image object — there are thousands of tiles that appear and vanish as
 * you move.
 *
 * So this mode inverts it: **fabric draws in image-pixel coordinates**, and the
 * whole canvas is transformed by OpenSeadragon's viewport. The manager's
 * `this.image` becomes an invisible placeholder at (0,0) with scale 1 and the
 * image's natural size, which makes every existing coordinate calculation —
 * `_screenToImageCoords`, `_renderAllMasks`, the normalization in
 * `_getObjectCoordinates` — correct without modification. That is deliberate:
 * a second set of transform maths for the tiled case is exactly how masks and
 * image drifted apart under zoom before Wave 1.3, and there is no reason to
 * reintroduce the same bug in a new file.
 *
 * The transform itself is never derived here. OpenSeadragon is asked where
 * image points (0,0) and (1,0) currently land on screen, and the affine falls
 * out of those two answers. Recomputing it from zoom levels and pan offsets
 * would be a reimplementation of the library's own arithmetic, and it would be
 * subtly wrong at exactly the moments — mid-animation, mid-resize — when it is
 * hardest to notice.
 *
 * ## Events
 *
 * OpenSeadragon and fabric both want the pointer. Rather than fight over it,
 * the overlay's `pointer-events` follow the tool: a drawing tool takes them,
 * navigation gives them back. The wheel is always forwarded to
 * OpenSeadragon, because zooming while a brush is selected is normal and
 * having it silently do nothing reads as a broken scroll wheel.
 */
(function (global) {
    'use strict';

    /** Where the tile routes live. Mirrors potato/media/routes.py. */
    const TILE_BASE = '/media/tiles';

    class DeepZoomBackend {
        /**
         * @param {object} manager - the ImageAnnotationManager being backed
         * @param {HTMLElement} host - element the viewer is drawn into
         * @param {object} options - {tileSize, overlap, maxPixels, showNavigator}
         */
        constructor(manager, host, options) {
            this.manager = manager;
            this.host = host;
            this.options = options || {};
            this.viewer = null;
            this.contentSize = null;
            this._onViewportChange = () => this.syncTransform();
        }

        /** True when the library is actually present. */
        static available() {
            return typeof global.OpenSeadragon !== 'undefined';
        }

        /**
         * Build the descriptor URL for a media path.
         *
         * The `.dzi` suffix is part of the route, not a file on disk: the
         * descriptor is generated from the source's dimensions. Keeping the
         * conventional extension means OpenSeadragon's own format detection
         * works with no configuration.
         */
        static descriptorUrl(mediaPath, options) {
            const params = new URLSearchParams();
            if (options && options.tileSize) params.set('tile_size', options.tileSize);
            if (options && options.overlap != null) params.set('overlap', options.overlap);
            if (options && options.maxPixels) params.set('max_pixels', options.maxPixels);
            if (options && options.page) params.set('page', options.page);
            const query = params.toString();
            const path = String(mediaPath || '').replace(/^\/?media\//, '')
                .replace(/^\//, '');
            return `${TILE_BASE}/${path}.dzi${query ? '?' + query : ''}`;
        }

        /**
         * Open a tiled source. Resolves with {width, height} in image pixels.
         *
         * Rejects rather than resolving with a broken viewer: the caller shows
         * the message, and a half-open viewer that silently accepts drawing
         * would record coordinates against an image that never loaded.
         */
        open(descriptorUrl) {
            if (!DeepZoomBackend.available()) {
                return Promise.reject(new Error(
                    'The deep-zoom viewer needs OpenSeadragon, which did not load. ' +
                    'Check that /static/vendor/openseadragon-5.0.1.min.js is served.'));
            }

            return new Promise((resolve, reject) => {
                let settled = false;
                this.viewer = global.OpenSeadragon({
                    element: this.host,
                    prefixUrl: '',
                    tileSources: descriptorUrl,
                    // Potato draws its own controls. OpenSeadragon's need ~20
                    // PNG sprites which are deliberately not vendored; turning
                    // these on without them gives broken-image icons.
                    showNavigationControl: false,
                    showNavigator: !!this.options.showNavigator,
                    navigatorPosition: 'BOTTOM_RIGHT',
                    // Annotation is a precision task. Springs that keep gliding
                    // after the gesture ends mean the annotator draws where the
                    // image *was*.
                    animationTime: 0.4,
                    springStiffness: 12,
                    // A tiled source is usually being examined at 1:1 or beyond,
                    // which is the entire reason for tiling it.
                    maxZoomPixelRatio: 8,
                    minZoomImageRatio: 0.5,
                    visibilityRatio: 0.5,
                    constrainDuringPan: true,
                    gestureSettingsMouse: { clickToZoom: false, dblClickToZoom: false },
                    crossOriginPolicy: 'Anonymous',
                    ajaxWithCredentials: false,
                });

                this.viewer.addHandler('open', () => {
                    const item = this.viewer.world.getItemAt(0);
                    this.contentSize = item ? item.getContentSize() : null;
                    if (!this.contentSize) {
                        if (!settled) { settled = true; reject(new Error(
                            'The tile source opened with no image in it.')); }
                        return;
                    }
                    this.viewer.addHandler('update-viewport', this._onViewportChange);
                    this.viewer.addHandler('animation', this._onViewportChange);
                    this.viewer.addHandler('resize', this._onViewportChange);
                    // The opening `goHome` is an animation, so the transform
                    // at this instant is the pre-animation one. `animation`
                    // fires per frame and corrects it, but only while the
                    // spring is moving; this guarantees one final sync at the
                    // resting position even if the animation is skipped or
                    // interrupted.
                    this.viewer.addHandler('animation-finish', this._onViewportChange);
                    this.syncTransform();
                    if (!settled) {
                        settled = true;
                        resolve({ width: this.contentSize.x, height: this.contentSize.y });
                    }
                });

                this.viewer.addHandler('open-failed', (event) => {
                    if (settled) return;
                    settled = true;
                    reject(new Error(
                        (event && event.message)
                            ? `The tile source could not be opened: ${event.message}`
                            : 'The tile source could not be opened.'));
                });
            });
        }

        /**
         * Point the fabric canvas at whatever OpenSeadragon is currently showing.
         *
         * Two probe points, not a formula. `imageToViewerElementCoordinates` is
         * the library's own answer to "where is this image pixel right now",
         * and taking it for (0,0) and (1,0) yields the scale and the offset
         * together — including during an animation, when any independently
         * computed transform lags by a frame and the annotations visibly swim
         * against the image.
         */
        syncTransform() {
            const canvas = this.manager && this.manager.canvas;
            const item = this.viewer && this.viewer.world.getItemAt(0);
            if (!canvas || !item || !global.OpenSeadragon) return;

            const origin = item.imageToViewerElementCoordinates(
                new global.OpenSeadragon.Point(0, 0));
            const unit = item.imageToViewerElementCoordinates(
                new global.OpenSeadragon.Point(1, 0));
            const scale = unit.x - origin.x;
            if (!isFinite(scale) || scale <= 0) return;

            canvas.viewportTransform = [scale, 0, 0, scale, origin.x, origin.y];
            canvas.requestRenderAll();
            if (typeof this.manager._renderAllMasks === 'function') {
                this.manager._renderAllMasks();
            }
        }

        /** Match the overlay to the viewer's element. */
        resize(width, height) {
            if (this.viewer && this.viewer.viewport) {
                this.viewer.viewport.resize(
                    new global.OpenSeadragon.Point(width, height), false);
                this.viewer.viewport.applyConstraints();
            }
            this.syncTransform();
        }

        /** Multiply the current zoom. Used by the toolbar's +/- buttons. */
        zoomBy(factor) {
            if (!this.viewer) return;
            this.viewer.viewport.zoomBy(factor);
            this.viewer.viewport.applyConstraints();
        }

        /** Fit the whole image in view. */
        zoomFit() {
            if (!this.viewer) return;
            this.viewer.viewport.goHome();
        }

        /** 1 image pixel to 1 screen pixel — what "actual size" means here. */
        zoomActual() {
            if (!this.viewer || !this.contentSize) return;
            const item = this.viewer.world.getItemAt(0);
            if (!item) return;
            this.viewer.viewport.zoomTo(
                item.imageToViewportZoom(1), null, true);
            this.viewer.viewport.applyConstraints();
        }

        /** Forward a wheel event the overlay swallowed. */
        forwardWheel(event) {
            if (!this.viewer) return;
            const factor = event.deltaY < 0 ? 1.2 : 1 / 1.2;
            const rect = this.host.getBoundingClientRect();
            const point = this.viewer.viewport.pointFromPixel(
                new global.OpenSeadragon.Point(event.clientX - rect.left,
                                               event.clientY - rect.top));
            this.viewer.viewport.zoomBy(factor, point);
            this.viewer.viewport.applyConstraints();
        }

        /**
         * Whether the overlay should receive pointer events.
         *
         * A drawing tool needs them; navigation must not, or OpenSeadragon
         * never sees a drag and the image cannot be panned at all.
         */
        setInteractive(interactive) {
            const wrapper = this.manager && this.manager.canvas
                && this.manager.canvas.wrapperEl;
            if (wrapper) {
                wrapper.style.pointerEvents = interactive ? 'auto' : 'none';
            }
        }

        destroy() {
            if (this.viewer) {
                this.viewer.removeHandler('update-viewport', this._onViewportChange);
                this.viewer.removeHandler('animation', this._onViewportChange);
                this.viewer.removeHandler('resize', this._onViewportChange);
                this.viewer.removeHandler('animation-finish', this._onViewportChange);
                this.viewer.destroy();
                this.viewer = null;
            }
            this.contentSize = null;
        }
    }

    global.DeepZoomBackend = DeepZoomBackend;
})(typeof window !== 'undefined' ? window : globalThis);

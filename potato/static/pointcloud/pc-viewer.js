/**
 * PointCloudAnnotationManager — 3D annotation over three.js.
 *
 * Everything here needs a WebGL context, which jsdom does not have, so it is
 * verified in a real browser rather than by the Jest suite. The arithmetic that
 * *can* be unit-tested lives in `pc-wire.js` next door, deliberately kept free
 * of three.js so that it can be.
 *
 * ## What this deliberately shares with the 2D manager
 *
 * The public surface is the same, because `annotation.js` and
 * `label-visibility.js` already call it:
 *
 *   addAnnotation(obj)        the sanctioned programmatic entry point
 *   getAnnotationHandles()    index-as-identity list
 *   applyLabelVisibility(set) per-class show/hide
 *   clearAnnotations()        called on EVERY instance switch
 *   serialize()               what the hidden input receives
 *
 * `clearAnnotations` is the one to be careful with. Three separate
 * cross-instance data-corruption bugs in the image manager came from state
 * that was not a fabric object and so was missed by a canvas-scoped clear.
 * Here *nothing* is a fabric object, so every field is listed explicitly and a
 * test drives the navigate-away-and-back path.
 *
 * ## Coordinates
 *
 * Absolute metres in the sensor frame, never normalized. See
 * `potato/export/spatial_utils.py` for why 3D has its own contract.
 */
(function (root) {
    'use strict';

    const wire = (root && root.PointCloudWire)
        || (typeof require !== 'undefined' ? require('./pc-wire.js') : null);
    const calib = (root && root.PointCloudCalibration)
        || (typeof require !== 'undefined' ? require('./pc-calibration.js') : null);
    const octree = (root && root.PointCloudOctree)
        || (typeof require !== 'undefined' ? require('./pc-octree.js') : null);
    const mpr = (root && root.PointCloudMPR)
        || (typeof require !== 'undefined' ? require('./pc-mpr.js') : null);

    /** Edges of a cuboid, as index pairs into `cuboid_corners` order. */
    const BOX_EDGES = [
        [0, 1], [1, 2], [2, 3], [3, 0],   // low-z face
        [4, 5], [5, 6], [6, 7], [7, 4],   // high-z face
        [0, 4], [1, 5], [2, 6], [3, 7],   // verticals
    ];

    /**
     * Arrow keys, as a panel axis and a screen direction.
     *
     * Screen, not world: `flipV` decides which way the world runs on the
     * vertical axis and the caller applies it. Keeping that conversion in one
     * place is what stops the up arrow moving the box down.
     */
    const SLAB_ARROWS = {
        ArrowLeft:  { axis: 'u', screen: -1 },
        ArrowRight: { axis: 'u', screen: 1 },
        ArrowUp:    { axis: 'v', screen: -1 },
        ArrowDown:  { axis: 'v', screen: 1 },
    };

    /**
     * Keyboard step sizes, in metres.
     *
     * Deliberately different: repositioning a whole box is a coarse action and
     * 5 cm per press would take forty presses to cross a car, while adjusting
     * a face against the returns behind it is the fine work the slab views
     * exist for. A single step for both would be wrong for one of them.
     */
    const SLAB_MOVE_STEP = 0.1;
    const SLAB_RESIZE_STEP = 0.05;

    class PointCloudAnnotationManager {
        constructor(canvasId, inputId, config) {
            this.canvasId = canvasId;
            this.inputId = inputId;
            this.config = config || {};

            this.canvas = null;
            this.container = null;
            this.scene = null;
            this.camera = null;
            this.renderer = null;
            this.cloud = null;          // THREE.Points (non-LOD path)
            this.parsed = null;         // pc-wire parse result (root, under LOD)

            // Level-of-detail state. `lodIndex` is the octree manifest;
            // `lodNodes` maps a node key to its THREE.Points; `_lodSeen` is the
            // tick at which each was last selected, which drives eviction.
            this.lodIndex = null;
            this.lodNodes = new Map();
            this.lodParsed = new Map();
            this._lodSeen = {};
            this._lodTick = 0;
            this._lodPending = new Set();
            this._lodTimer = null;
            this._colorRange = null;

            // Orthographic slab panels. `mprPanels` maps a plane name to its
            // figure/canvas; `_slabDrag` is the in-flight edge or move drag.
            this.mprPanels = null;
            this._slabDrag = null;
            this._mprObserver = null;

            this.annotations = [];      // client-contract objects
            this.meshes = [];           // one THREE.Object3D per annotation
            this.currentTool = null;
            this.currentLabel = null;
            this.currentColor = null;
            this._hiddenLabels = null;
            this.labelVisibility = null;

            this.history = [];
            this.historyIndex = -1;
            this.maxHistory = 50;

            // Drawing and selection state. `groundZ` is estimated from the
            // cloud rather than assumed to be 0: a sensor mounted 1.7 m up
            // reports the road at z = -1.7, so a box drawn on the z = 0 plane
            // would float above every object in the scene.
            this.groundZ = 0;
            this.selectedIndex = -1;
            this._drag = null;
            this._previewMesh = null;
            this.cameras = [];
        }

        // -------------------------------------------------------------
        // Lifecycle
        // -------------------------------------------------------------

        init() {
            this.canvas = document.getElementById(this.canvasId);
            if (!this.canvas) return;
            this.container = this.canvas.closest(
                '.pointcloud-annotation-container');

            if (typeof THREE === 'undefined') {
                this._status('3D viewer unavailable: three.js did not load. '
                             + 'Other annotation types on this page still work.',
                             'error');
                return;
            }

            this._buildScene();
            this._bindToolbar();
            this._bindKeys();
            this._restoreFromInput();
            this._buildMprPanels();
            this._loadCloud();
            this._loadCalibration();
        }

        destroy() {
            if (this._mprObserver) {
                this._mprObserver.disconnect();
                this._mprObserver = null;
            }
            if (this._resizeObserver) {
                this._resizeObserver.disconnect();
                this._resizeObserver = null;
            }
            if (this._panelObserver) {
                this._panelObserver.disconnect();
                this._panelObserver = null;
            }
            if (this._keyHandler) {
                document.removeEventListener('keydown', this._keyHandler);
                this._keyHandler = null;
            }
            if (this.renderer) this.renderer.dispose();
        }

        _buildScene() {
            this.scene = new THREE.Scene();
            this.scene.background = new THREE.Color(0x11151c);

            const w = this.canvas.clientWidth || 800;
            const h = this.canvas.clientHeight || 500;
            this.camera = new THREE.PerspectiveCamera(55, w / h, 0.1, 5000);
            this.camera.up.set(0, 0, 1);   // Z-up: every format we read is

            this.renderer = new THREE.WebGLRenderer({
                canvas: this.canvas, antialias: true });
            this.renderer.setPixelRatio(window.devicePixelRatio || 1);
            this.renderer.setSize(w, h, false);

            this._orbit = { theta: -Math.PI / 4, phi: Math.PI / 3, radius: 20,
                            target: new THREE.Vector3() };
            this._bindNavigation();
            this._bindDrawing();
            this._applyCamera();

            // The canvas is laid out by CSS, so its pixel size changes with the
            // window. Without this the render is stretched after any resize —
            // the same defect the image canvas had before Wave 0.8.
            if (typeof ResizeObserver !== 'undefined') {
                this._resizeObserver = new ResizeObserver(() => this.handleResize());
                this._resizeObserver.observe(this.canvas.parentElement
                                             || this.canvas);
            }
            this._render();
        }

        handleResize() {
            if (!this.renderer || !this.camera) return;
            const w = this.canvas.clientWidth || 1;
            const h = this.canvas.clientHeight || 1;
            this.camera.aspect = w / h;
            this.camera.updateProjectionMatrix();
            this.renderer.setSize(w, h, false);
            this._render();
            // A taller viewport means every node projects to more pixels, so
            // the detail threshold moves. Resizing without this leaves the
            // cloud at the old window's level of detail.
            this._scheduleLodUpdate();
        }

        _render() {
            if (this.renderer && this.scene && this.camera) {
                this.renderer.render(this.scene, this.camera);
            }
        }

        // -------------------------------------------------------------
        // The cloud
        // -------------------------------------------------------------

        /**
         * Where this item's cloud lives, or null.
         *
         * The record first, the DOM second. `[data-instance-json]` carries the
         * whole item, so the cloud path is read from the field the schema
         * names whether or not that field is *displayed* -- which is how every
         * other widget on the page finds its media, and nothing ever said this
         * one needed the field on screen.
         *
         * Scraping the display field was also wrong in a way that looked like
         * missing data: `render_display_container` puts the field's `label:`
         * inside the same element, so the text of a labelled field is
         * "Cloud\n\nclouds/scene_0001.bin" -- whitespace, which
         * `looksLikeCloud` rejects. Adding a label to the display silently
         * emptied the viewer.
         *
         * The DOM fallbacks stay for items whose path arrives only as the
         * instance text (a `text_key` cloud, which is what the bundled example
         * uses), and read `.display-field-content` rather than the container so
         * a label cannot poison the value.
         */
        _cloudPath() {
            const field = this.config.sourceField || 'point_cloud';

            const record = this._instanceRecord();
            const fromRecord = record && record[field];
            if (typeof fromRecord === 'string' && looksLikeCloud(fromRecord)) {
                return fromRecord.trim();
            }

            const display = document.querySelector(`[data-field-key="${field}"]`);
            if (display) {
                const body = display.querySelector('.display-field-content')
                    || display;
                const value = display.getAttribute('data-source-url')
                    || (body.textContent || '').trim();
                if (looksLikeCloud(value)) return value.trim();
            }

            const text = document.getElementById('text-content')
                || document.getElementById('instance-text');
            if (text) {
                const value = (text.textContent || '').trim();
                if (looksLikeCloud(value)) return value;
            }
            return null;
        }

        /** The whole item record, as the page publishes it. */
        _instanceRecord() {
            try {
                const el = document.querySelector('[data-instance-json]');
                if (el) {
                    return JSON.parse(el.getAttribute('data-instance-json')) || {};
                }
            } catch (err) {
                /* fall through to the DOM sources */
            }
            return null;
        }

        _cloudUrl() {
            const path = this._cloudPath();
            if (!path) return null;
            if (/^https?:\/\//i.test(path)) {
                // A remote cloud still has to go through the converter, so the
                // browser never sees PCD or LAS. Passed as a query parameter
                // rather than a path segment so the scheme survives.
                return `/media/pointcloud/${encodeURIComponent(path)}`
                    + this._maxPointsQuery('?');
            }
            return `/media/pointcloud/${path}` + this._maxPointsQuery('?');
        }

        _maxPointsQuery(prefix) {
            return this.config.maxPoints
                ? `${prefix}max_points=${encodeURIComponent(this.config.maxPoints)}`
                : '';
        }

        /**
         * Every THREE.Points currently holding cloud geometry.
         *
         * One object on the single-buffer path, one per loaded node under LOD.
         * Public because "is the cloud on screen?" is a question the test
         * harness and any future overlay both need to ask, and reaching into
         * `this.cloud` gives the wrong answer as soon as LOD is on — which is
         * exactly how enabling LOD broke seventeen tests that were checking a
         * field rather than a fact.
         */
        cloudObjects() {
            if (this.lodIndex) return Array.from(this.lodNodes.values());
            return this.cloud ? [this.cloud] : [];
        }

        /** True once at least one buffer of points is in the scene. */
        hasCloud() {
            return this.cloudObjects().length > 0;
        }

        /** Points currently in the scene, across every loaded buffer. */
        loadedPointCount() {
            return this._loadedPositions()
                .reduce((n, p) => n + Math.floor(p.length / 3), 0);
        }

        /** True when this viewer loads the cloud as an octree. */
        _lodEnabled() {
            return this.config.lod !== false
                && typeof root.PointCloudOctree !== 'undefined';
        }

        async _loadCloud() {
            const url = this._cloudUrl();
            if (!url) {
                const field = this.config.sourceField || 'point_cloud';
                const record = this._instanceRecord();
                const present = record && record[field];
                this._status(
                    present
                        ? `No point cloud for this item: "${field}" holds `
                          + `"${String(present).slice(0, 80)}", which is not a `
                          + `cloud path. Expected a .pcd, .ply, .bin, .las, `
                          + `.laz, .xyz or .pts file, with no spaces in it.`
                        : `No point cloud for this item: it has no "${field}" `
                          + `field. Set source_field on this schema to the item `
                          + `key that holds the cloud path.`,
                    'error');
                return;
            }

            if (this._lodEnabled()) return this._loadOctree(url);

            this._status('Loading point cloud…');
            let response;
            try {
                response = await fetch(url, { credentials: 'same-origin' });
            } catch (err) {
                this._status(`Could not fetch the point cloud: ${err.message}`,
                             'error');
                return;
            }
            if (!response.ok) {
                // The server sends an actionable message for a format it cannot
                // read ("convert with laszip"); surfacing the status code alone
                // would throw that away.
                let detail = `HTTP ${response.status}`;
                try {
                    detail = (await response.json()).error || detail;
                } catch (_e) { /* not JSON; keep the status */ }
                this._status(detail, 'error');
                return;
            }

            let parsed;
            try {
                parsed = wire.parseWire(await response.arrayBuffer());
            } catch (err) {
                this._status(`Point cloud is unreadable: ${err.message}`, 'error');
                return;
            }
            this.parsed = parsed;
            this._buildPoints(parsed);
            this._status(wire.describeCloud(parsed.header));
        }

        /**
         * A THREE.Points for one parsed buffer.
         *
         * Shared by the single-buffer path and by every octree node, so that
         * point size, colour mode and the colour range cannot drift between
         * them — a node coloured on a different scale from its neighbours shows
         * as a hard seam along an octree boundary.
         */
        _pointsObject(parsed) {
            const geometry = new THREE.BufferGeometry();
            geometry.setAttribute('position',
                new THREE.BufferAttribute(parsed.positions, 3));

            const mode = this._colorMode(parsed);
            let colors = wire.colorize(mode, parsed, null, this._colorRange);
            if (!colors) colors = wire.colorize('height', parsed, null,
                                                this._colorRange);
            geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));

            return new THREE.Points(geometry, new THREE.PointsMaterial({
                size: this.config.pointSize || 1.5,
                sizeAttenuation: false,
                vertexColors: true,
            }));
        }

        /**
         * The colour mode this cloud can actually satisfy.
         *
         * Warns once, on the first buffer, rather than per octree node: a
         * hundred identical "no intensity data" messages would bury whatever
         * the status line said next.
         */
        _colorMode(parsed) {
            const requested = this.config.colorMode || 'height';
            if (requested === 'uniform') return requested;
            if (requested === 'rgb' && !parsed.colors) {
                this._warnColorFallback(requested);
                return 'height';
            }
            if (requested === 'intensity' && !parsed.intensity) {
                this._warnColorFallback(requested);
                return 'height';
            }
            return requested;
        }

        _warnColorFallback(mode) {
            if (this._colorWarned) return;
            this._colorWarned = true;
            // Falling back silently would leave the annotator wondering why
            // "colour by intensity" looks like "colour by height".
            this._status(
                `This cloud has no ${mode} data; colouring by height instead.`,
                'warn');
        }

        /** Pin the ramp's [lo, hi] from a representative buffer. */
        _setColorRange(parsed) {
            const mode = this._colorMode(parsed);
            if (mode === 'rgb' || mode === 'uniform') {
                this._colorRange = null;
                return;
            }
            const values = wire.scalarFor(mode, parsed);
            this._colorRange = values
                ? wire.percentileRange(values, parsed.count) : null;
        }

        _buildPoints(parsed) {
            if (this.cloud) {
                this.scene.remove(this.cloud);
                this.cloud.geometry.dispose();
                this.cloud.material.dispose();
            }

            this._setColorRange(parsed);
            this.cloud = this._pointsObject(parsed);
            this.scene.add(this.cloud);

            this.groundZ = groundLevel(parsed.positions);

            const frame = wire.framing(parsed.header, parsed);
            this._orbit.target.set(frame.center[0], frame.center[1],
                                   frame.center[2]);
            // Derived from the camera's own field of view rather than a fixed
            // multiplier: at 55 degrees a scene half-extent `r` exactly fills
            // the frame from `r / tan(fov/2)`. The 0.7 pulls in closer than
            // that, because the framing radius is the LARGEST of the three
            // extents and a lidar sweep is a flat disc -- fitting its widest
            // axis to the full height leaves the scene a small patch in the
            // middle of a large dark viewport.
            const halfFov = (this.camera.fov * Math.PI / 180) / 2;
            this._orbit.radius = Math.max(
                2.0, frame.radius / Math.tan(halfFov) * 0.7);
            this._applyCamera();
            // Same reason as the LOD path: the panels were built before this
            // buffer existed and nothing else redraws them until the annotator
            // interacts.
            this._drawMpr();
        }

        // -------------------------------------------------------------
        // Level of detail
        //
        // Uniform decimation caps the cloud at 500k points, which for a
        // 20-million-point scan is 2.5% density everywhere: the scene is
        // visible and nothing in it is annotatable. LOD spends that budget
        // where the camera is pointed instead. The selection arithmetic lives
        // in pc-octree.js, free of three.js so it can be unit-tested.
        // -------------------------------------------------------------

        async _loadOctree(baseUrl) {
            this._disposeLod();
            this._status('Loading point cloud…');

            const manifestUrl = withParam(baseUrl, 'lod', '1');
            let manifest;
            try {
                const response = await fetch(manifestUrl,
                                             { credentials: 'same-origin' });
                if (!response.ok) {
                    let detail = `HTTP ${response.status}`;
                    try {
                        detail = (await response.json()).error || detail;
                    } catch (_e) { /* not JSON; keep the status */ }
                    this._status(detail, 'error');
                    return;
                }
                manifest = await response.json();
            } catch (err) {
                this._status(`Could not fetch the point cloud: ${err.message}`,
                             'error');
                return;
            }

            this.lodIndex = new octree.OctreeIndex(manifest);
            this._lodBaseUrl = baseUrl;
            if (!this.lodIndex.root) {
                this._status('This point cloud is empty.', 'warn');
                return;
            }

            // Frame from the manifest's bounds, before a single point has
            // arrived. Framing after the root loads would show the scene from
            // the default camera for one paint, which reads as a jump.
            this._frameOn(wire.framing({ bounds: this.lodIndex.bounds }, null));

            await this._fetchNode('r');
            const rootParsed = this.lodParsed.get('r');
            if (rootParsed) {
                // The root of an additive octree is a uniform sample of the
                // whole scene, so it is the right buffer both for the shared
                // colour range and for the ground estimate — a deep node would
                // give a ground level for one corner of the scene.
                this.parsed = rootParsed;
                this.groundZ = groundLevel(rootParsed.positions);
            }
            this._updateLod();
        }

        _frameOn(frame) {
            this._orbit.target.set(frame.center[0], frame.center[1],
                                   frame.center[2]);
            const halfFov = (this.camera.fov * Math.PI / 180) / 2;
            this._orbit.radius = Math.max(
                2.0, frame.radius / Math.tan(halfFov) * 0.7);
            this._applyCamera();
        }

        async _fetchNode(key) {
            if (this.lodNodes.has(key) || this._lodPending.has(key)) return;
            this._lodPending.add(key);
            try {
                const response = await fetch(
                    withParam(withParam(this._lodBaseUrl, 'lod', '1'),
                              'node', key),
                    { credentials: 'same-origin' });
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                const parsed = wire.parseWire(await response.arrayBuffer());
                if (key === 'r') this._setColorRange(parsed);
                this.lodParsed.set(key, parsed);
                const points = this._pointsObject(parsed);
                this.lodNodes.set(key, points);
                this.scene.add(points);
                this._render();
                // The slabs read from the loaded buffers, and this node is the
                // first data some of them have. Without this the panels stay
                // at whatever they were drawn with -- which, on first load, is
                // an empty scene: _buildMprPanels runs before the fetch, and
                // nothing else redrew them until the annotator interacted.
                // They looked like three broken canvases.
                this._drawMpr();
            } catch (err) {
                // One node failing is a gap in the scene, not a dead viewer.
                // Saying so is the difference between "the network dropped a
                // request" and "this area really has no returns" — and an
                // annotator cannot tell those apart by looking.
                this._status(
                    `Part of the cloud could not be loaded (${err.message}); `
                    + `the view may be missing detail in places.`, 'warn');
            } finally {
                this._lodPending.delete(key);
            }
        }

        /**
         * Six frustum planes, normals pointing inward.
         *
         * three.js `Plane` is `normal · x + constant = 0` with the inside
         * positive, which is exactly the convention `intersectsFrustum` wants —
         * so this is a repack, not a conversion. Flipping it would cull the
         * visible half of the scene and look like sparse data.
         */
        _frustumPlanes() {
            if (typeof THREE === 'undefined' || !this.camera) return null;
            this.camera.updateMatrixWorld();
            const m = new THREE.Matrix4().multiplyMatrices(
                this.camera.projectionMatrix, this.camera.matrixWorldInverse);
            const frustum = new THREE.Frustum().setFromProjectionMatrix(m);
            return frustum.planes.map(
                (p) => [p.normal.x, p.normal.y, p.normal.z, p.constant]);
        }

        /** Recompute the visible node set. Debounced by `_scheduleLodUpdate`. */
        _updateLod() {
            if (!this.lodIndex || !this.camera || !octree) return;
            this._lodTick += 1;

            const selection = this.lodIndex.select({
                position: [this.camera.position.x, this.camera.position.y,
                           this.camera.position.z],
                planes: this._frustumPlanes(),
                fovRadians: this.camera.fov * Math.PI / 180,
                viewportHeight: this.canvas.clientHeight || 600,
                pointBudget: this.config.pointBudget,
                minScreenSize: this.config.minScreenSize,
            });

            const want = new Set(selection.keys);
            selection.keys.forEach((k) => { this._lodSeen[k] = this._lodTick; });

            let loadedPoints = 0;
            this.lodNodes.forEach((obj, key) => {
                obj.visible = want.has(key);
                if (obj.visible) {
                    const parsed = this.lodParsed.get(key);
                    loadedPoints += parsed ? parsed.count : 0;
                }
            });

            selection.keys.forEach((k) => {
                if (!this.lodNodes.has(k)) this._fetchNode(k);
            });

            octree.evictionOrder(Array.from(this.lodNodes.keys()),
                                 this._lodSeen, selection.keys,
                                 this.config.maxLoadedNodes)
                .forEach((k) => this._disposeNode(k));

            // Reports what is *loaded*, not what was selected: a node that has
            // been requested but not arrived is not on screen, and counting it
            // would tell the annotator they are looking at detail they are not.
            const summary = octree.describeLod(this.lodIndex, {
                points: loadedPoints, budgetHit: selection.budgetHit });
            this._status(summary);
            // Announced once, on the first pass. The count changes constantly
            // as the camera moves; what a screen-reader user needs is to know
            // the cloud arrived and roughly how much of it is on screen, not a
            // running commentary on the loader.
            if (!this._lodAnnounced && loadedPoints > 0) {
                this._lodAnnounced = true;
                this._announce(summary);
            }
            this._render();
        }

        _scheduleLodUpdate() {
            if (!this.lodIndex) return;
            // Coalesced: an orbit drag fires dozens of camera updates a second
            // and each one would otherwise re-sort the whole node list and
            // possibly start fetches that the next frame invalidates.
            if (this._lodTimer) clearTimeout(this._lodTimer);
            this._lodTimer = setTimeout(() => {
                this._lodTimer = null;
                this._updateLod();
            }, 120);
        }

        _disposeNode(key) {
            const obj = this.lodNodes.get(key);
            if (obj) {
                this.scene.remove(obj);
                obj.geometry.dispose();
                obj.material.dispose();
            }
            this.lodNodes.delete(key);
            this.lodParsed.delete(key);
            delete this._lodSeen[key];
        }

        _disposeLod() {
            Array.from(this.lodNodes.keys()).forEach((k) => this._disposeNode(k));
            this.lodIndex = null;
            this._lodPending.clear();
            this._colorRange = null;
            this._colorWarned = false;
            if (this._lodTimer) {
                clearTimeout(this._lodTimer);
                this._lodTimer = null;
            }
        }

        /**
         * Every loaded position buffer, coarsest first.
         *
         * An array of arrays rather than one concatenation: under LOD the
         * loaded set can be two million points, and copying it into a single
         * buffer every time a box is drawn would cost 24 MB per drag.
         */
        _loadedPositions() {
            if (this.lodIndex) {
                const out = [];
                this.lodNodes.forEach((obj, key) => {
                    const parsed = this.lodParsed.get(key);
                    if (parsed && obj.visible) out.push(parsed.positions);
                });
                return out;
            }
            return this.parsed ? [this.parsed.positions] : [];
        }

        // -------------------------------------------------------------
        // Drawing a box
        //
        // The interaction that makes 3D labelling tolerable: drag out a
        // footprint on the ground plane, and the box's vertical extent is
        // taken from the points that fall inside it. Judging height by eye in
        // a perspective view of a sparse cloud is the part annotators get
        // wrong, and it is the part the data can answer directly.
        // -------------------------------------------------------------

        _bindDrawing() {
            const canvas = this.canvas;

            canvas.addEventListener('mousedown', (e) => {
                if (e.button !== 0) return;
                if (this.currentTool === 'cuboid_3d') {
                    const hit = this._groundPointAt(e);
                    if (!hit) return;
                    e.preventDefault();
                    this._drag = { a: hit, b: hit, yaw: 0 };
                    this._updatePreview();
                } else if (this.currentTool === 'point_3d') {
                    const hit = this._groundPointAt(e);
                    if (!hit) return;
                    e.preventDefault();
                    this._placePoint(hit);
                } else if (!this.currentTool) {
                    this._selectAt(e);
                }
            });

            canvas.addEventListener('mousemove', (e) => {
                if (!this._drag) return;
                const hit = this._groundPointAt(e);
                if (!hit) return;
                this._drag.b = hit;
                this._updatePreview();
            });

            // On `window`, not the canvas: releasing outside the viewport is
            // ordinary when dragging to the edge of a box, and a mouseup the
            // canvas never sees leaves a preview box following the cursor for
            // the rest of the session.
            window.addEventListener('mouseup', (e) => {
                if (!this._drag || e.button !== 0) return;
                const drag = this._drag;
                this._drag = null;
                this._clearPreview();
                this._commitBox(drag);
            });
        }

        /** Where a mouse event's ray meets the ground plane, or null. */
        _groundPointAt(event) {
            if (!this.camera || typeof THREE === 'undefined') return null;
            const rect = this.canvas.getBoundingClientRect();
            if (!rect.width || !rect.height) return null;
            const ndc = new THREE.Vector3(
                ((event.clientX - rect.left) / rect.width) * 2 - 1,
                -((event.clientY - rect.top) / rect.height) * 2 + 1,
                0.5);
            ndc.unproject(this.camera);
            const origin = this.camera.position;
            const dir = ndc.sub(origin).normalize();
            return intersectPlaneZ([origin.x, origin.y, origin.z],
                                   [dir.x, dir.y, dir.z], this.groundZ);
        }

        _updatePreview() {
            this._clearPreview();
            if (!this._drag) return;
            const coords = this._boxFromDrag(this._drag);
            if (!coords) return;
            const obj = { type: 'cuboid_3d', label: this.currentLabel,
                          color: this.currentColor, coordinates: coords };
            this._previewMesh = this._boxMesh(obj, threeColor(obj.color));
            if (this._previewMesh) {
                // Dashed would be better, but a dashed material needs
                // computeLineDistances on every update; opacity reads as
                // "not committed yet" for the same cost.
                this._previewMesh.material.transparent = true;
                this._previewMesh.material.opacity = 0.55;
                this.scene.add(this._previewMesh);
            }
            this._render();
        }

        _clearPreview() {
            if (this._previewMesh) {
                this.scene.remove(this._previewMesh);
                this._previewMesh = null;
            }
        }

        _boxFromDrag(drag) {
            const height = this.config.defaultBoxHeight || 1.7;
            return footprintToCuboid(drag.a, drag.b, drag.yaw, this.groundZ,
                                     height);
        }

        _commitBox(drag) {
            if (!this.currentLabel) {
                this._status('Pick a class before drawing a box.', 'warn');
                return;
            }
            let coords = this._boxFromDrag(drag);
            if (!coords) {
                // A click rather than a drag. Silently doing nothing is right:
                // a stray click must not leave a degenerate annotation, which
                // is the bug the image canvas was checked for in Wave 0.8.
                return;
            }
            if (this.config.fitBoxHeight !== false) {
                // Every loaded buffer, not just the root: under LOD the dense
                // points near the camera are exactly the ones the annotator
                // drew around, and fitting to the coarse root sample would
                // give a shorter box the closer you zoomed in.
                coords = fitHeightToPoints(coords, this._loadedPositions(),
                                           this.groundZ);
            }
            this.addAnnotation({ type: 'cuboid_3d', label: this.currentLabel,
                                 color: this.currentColor,
                                 coordinates: coords });
            this.selectedIndex = this.annotations.length - 1;
            this._status(`Box added: ${describeBox(coords)}. `
                         + 'Press q/e to rotate it, Delete to remove it.');
        }

        _placePoint(hit) {
            if (!this.currentLabel) {
                this._status('Pick a class before placing a point.', 'warn');
                return;
            }
            this.addAnnotation({ type: 'point_3d', label: this.currentLabel,
                                 color: this.currentColor, coordinates: hit });
            this.selectedIndex = this.annotations.length - 1;
        }

        /** Select the annotation nearest a click, in screen space. */
        _selectAt(event) {
            if (!this.camera || typeof THREE === 'undefined') return;
            const rect = this.canvas.getBoundingClientRect();
            const x = event.clientX - rect.left;
            const y = event.clientY - rect.top;
            let best = -1;
            let bestDistance = 40;   // px; beyond this a click means "deselect"

            this.annotations.forEach((obj, i) => {
                if (this._hiddenLabels && this._hiddenLabels.has(obj.label)) return;
                const centre = annotationCenter(obj);
                if (!centre) return;
                const v = new THREE.Vector3(centre[0], centre[1], centre[2])
                    .project(this.camera);
                if (v.z > 1) return;         // behind the camera
                const sx = (v.x + 1) / 2 * rect.width;
                const sy = (-v.y + 1) / 2 * rect.height;
                const d = Math.hypot(sx - x, sy - y);
                if (d < bestDistance) { bestDistance = d; best = i; }
            });

            this.selectedIndex = best;
            this._highlightSelection();
            if (best >= 0) {
                this._status(
                    `Selected ${this.annotations[best].label}. `
                    + 'q/e rotate, Delete removes.');
            }
        }

        /**
         * Move the selection `step` places, wrapping.
         *
         * Wraps rather than stopping at the ends: there is no visible list to
         * tell you where in it you are, so a key that silently stops working
         * reads as the control being broken.
         */
        cycleSelection(step) {
            const n = this.annotations.length;
            if (!n) return;
            const from = this.selectedIndex < 0
                ? (step > 0 ? -1 : 0) : this.selectedIndex;
            this.selectedIndex = ((from + step) % n + n) % n;
            this._highlightSelection();
            this._drawOverlays();
            const obj = this.annotations[this.selectedIndex];
            const where = obj.type === 'cuboid_3d' && obj.coordinates
                ? ` ${describeBox(obj.coordinates)}` : '';
            const message = `${this.selectedIndex + 1} of ${n}: `
                + `${obj.label}.${where}`;
            this._status(message);
            this._announce(message);
        }

        _highlightSelection() {
            this.meshes.forEach((mesh, i) => {
                if (!mesh || !mesh.material) return;
                // Line width is capped at 1 on most platforms, so thickness
                // cannot carry selection. Brightness can.
                mesh.material.opacity = (i === this.selectedIndex
                                         || this.selectedIndex < 0) ? 1.0 : 0.45;
                mesh.material.transparent = mesh.material.opacity < 1.0;
            });
            this._render();
            // The slabs centre and size themselves on the selection, so a
            // selection change is a full redraw, not a highlight.
            this._drawMpr();
        }

        /** Rotate the selected cuboid about its own centre. */
        rotateSelected(radians) {
            const obj = this.annotations[this.selectedIndex];
            if (!obj || obj.type !== 'cuboid_3d') return false;
            obj.coordinates.rotation = composeYaw(obj.coordinates.rotation,
                                                  radians);
            this._rebuildMeshes();
            this._saveState();
            this._updateAnnotationData();
            return true;
        }

        deleteSelected() {
            if (this.selectedIndex < 0) return false;
            const removed = this.deleteAnnotation(this.selectedIndex);
            this.selectedIndex = -1;
            return removed;
        }

        // -------------------------------------------------------------
        // Camera verification panels
        // -------------------------------------------------------------

        async _loadCalibration() {
            const holder = this.container
                && this.container.querySelector('.pc-cameras');
            if (!holder || !calib) return;

            const field = this.config.calibrationField || 'calibration';
            const instance = document.getElementById('instance_id');
            const params = new URLSearchParams({ field: field });
            if (instance && instance.value) params.set('instance_id', instance.value);

            let payload;
            try {
                const response = await fetch(`/api/calibration?${params}`,
                                             { credentials: 'same-origin' });
                payload = await response.json();
                if (!response.ok) {
                    // A calibration that exists but cannot be parsed is an
                    // admin's problem, and the message names what was missing.
                    this._status(`Camera views unavailable: ${payload.error}`,
                                 'warn');
                    return;
                }
            } catch (err) {
                this._status(`Camera views unavailable: ${err.message}`, 'warn');
                return;
            }

            // No calibration is the normal case for a lidar-only project, so
            // it is silent: an empty panel area, no warning.
            this.cameras = (payload && payload.cameras) || [];
            (payload && payload.warnings || []).forEach(
                (w) => console.warn('[pointcloud] calibration:', w));
            this._buildCameraPanels(holder);
        }

        _buildCameraPanels(holder) {
            holder.innerHTML = '';
            if (!this.cameras.length) return;

            this.cameras.forEach((cam, i) => {
                const panel = document.createElement('figure');
                panel.className = 'pc-camera';
                panel.dataset.camera = String(i);

                const stack = document.createElement('div');
                stack.className = 'pc-camera-stack';

                // Declared before the handlers that close over it: an `error`
                // listener referencing a `const` from further down works only
                // because the event is asynchronous, which is a coincidence
                // rather than a design.
                const caption = document.createElement('figcaption');
                caption.textContent = cam.image_url ? cam.name
                    : `${cam.name} — calibration only, no image for this item`;

                const img = document.createElement('img');
                img.className = 'pc-camera-image';
                // The photograph, and ONLY the photograph. The wireframes live
                // on the canvas above it, so describing them here would tell a
                // screen-reader user this image contains something it does not.
                img.alt = `View from ${cam.name}`;
                img.loading = 'lazy';
                img.decoding = 'async';

                const overlay = document.createElement('canvas');
                overlay.className = 'pc-camera-overlay';
                // Decorative: every box drawn here is already in the hidden
                // input, the annotation count, and the 3D scene. Announcing an
                // unlabelled canvas would add noise without adding access.
                overlay.setAttribute('aria-hidden', 'true');

                img.addEventListener('load', () => this._drawOverlay(i));
                img.addEventListener('error', () => {
                    panel.classList.add('pc-camera-broken');
                    caption.textContent = `${cam.name} — image not found`;
                });
                if (cam.image_url) {
                    img.src = cam.image_url;
                } else {
                    panel.classList.add('pc-camera-broken');
                }

                stack.appendChild(img);
                stack.appendChild(overlay);
                panel.appendChild(stack);
                panel.appendChild(caption);
                holder.appendChild(panel);
            });

            if (typeof ResizeObserver !== 'undefined' && !this._panelObserver) {
                this._panelObserver = new ResizeObserver(
                    () => this._drawOverlays());
                this._panelObserver.observe(holder);
            }
        }

        _drawOverlays() {
            // Guarded rather than assumed non-empty: this runs from
            // _updateAnnotationData, which fires on every mutation including
            // ones that happen before the calibration fetch has returned.
            (this.cameras || []).forEach((_cam, i) => this._drawOverlay(i));
            this._drawMpr();
        }

        // -------------------------------------------------------------
        // Orthographic slab views
        //
        // A perspective view compresses the extent along the view axis, so a
        // box placed by eye comes out short in depth and the error is
        // invisible from the camera that drew it. In a slab, a metre is a
        // metre in both screen directions and the returns behind a face are
        // not hidden by the ones in front. The arithmetic is in pc-mpr.js,
        // free of three.js so it can be unit-tested.
        // -------------------------------------------------------------

        _buildMprPanels() {
            const holder = this.container
                && this.container.querySelector('.pc-mpr');
            if (!holder || !mpr || this.config.mpr === false) return;

            holder.innerHTML = '';
            this.mprPanels = {};

            const help = this.container.querySelector('.pc-mpr-help');
            const helpId = help ? help.id : null;

            mpr.PLANE_ORDER.forEach((plane) => {
                const panel = document.createElement('figure');
                panel.className = 'pc-slab';
                panel.dataset.plane = plane;

                const canvas = document.createElement('canvas');
                canvas.className = 'pc-slab-canvas';
                // NOT aria-hidden. These panels take pointer input and, below,
                // keyboard input; hiding an interactive control from the
                // accessibility tree removes the only way a screen-reader user
                // could know it exists (WCAG 4.1.2). The camera overlay next
                // door IS decorative and keeps its aria-hidden — the
                // difference is whether the element does anything when you
                // press it.
                canvas.setAttribute('role', 'application');
                canvas.setAttribute('aria-label',
                                    `${mpr.PLANES[plane].label} slab view`);
                // Looked up rather than string-built from the schema name: the
                // element's id is HTML-escaped server-side and the config's
                // copy of the name is not, so building it here would drift for
                // any name the escaper touches.
                if (helpId) canvas.setAttribute('aria-describedby', helpId);
                // Focusable, because the pointer path below is otherwise the
                // only way to adjust a face — and the panels exist precisely
                // because placing a box by eye in perspective is imprecise, so
                // "use the 3D view instead" is not an equivalent alternative.
                canvas.tabIndex = 0;

                const caption = document.createElement('figcaption');
                caption.textContent = mpr.PLANES[plane].label;

                panel.appendChild(canvas);
                panel.appendChild(caption);
                holder.appendChild(panel);

                this.mprPanels[plane] = { panel, canvas, caption };
                this._bindSlab(plane, canvas);
            });

            if (typeof ResizeObserver !== 'undefined' && !this._mprObserver) {
                this._mprObserver = new ResizeObserver(() => this._drawMpr());
                this._mprObserver.observe(holder);
            }
            this._drawMpr();
        }

        /** The view for one panel, or null when there is nothing to show. */
        _slabView(plane) {
            const entry = this.mprPanels && this.mprPanels[plane];
            if (!entry || !mpr) return null;
            const rect = entry.canvas.getBoundingClientRect();
            const width = Math.max(1, Math.round(rect.width));
            const height = Math.max(1, Math.round(rect.height));

            const selection = this.annotations[this.selectedIndex] || null;
            const target = this._orbit && this._orbit.target;
            const center = mpr.focusPoint(
                selection, target ? [target.x, target.y, target.z] : [0, 0, 0]);
            const extent = mpr.extentFor(selection, this._sceneExtent());
            return mpr.makeView(plane, center, extent, width, height);
        }

        _sceneExtent() {
            const bounds = this.lodIndex
                ? this.lodIndex.bounds
                : (this.parsed && this.parsed.header
                   && this.parsed.header.bounds);
            if (!bounds) return 20;
            const [lo, hi] = bounds;
            return Math.max(
                2, Math.max(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]) / 2);
        }

        _drawMpr() {
            if (!this.mprPanels || !mpr) return;
            mpr.PLANE_ORDER.forEach((plane) => this._drawSlab(plane));
        }

        _drawSlab(plane) {
            const entry = this.mprPanels[plane];
            if (!entry) return;
            const view = this._slabView(plane);
            if (!view) return;

            const canvas = entry.canvas;
            const dpr = window.devicePixelRatio || 1;
            // Sized in device pixels and scaled back: a canvas sized in CSS
            // pixels renders soft on a retina display, and a slab view exists
            // to be read precisely.
            canvas.width = Math.round(view.width * dpr);
            canvas.height = Math.round(view.height * dpr);
            const ctx = canvas.getContext('2d');
            if (!ctx) return;
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

            ctx.fillStyle = '#11151c';
            ctx.fillRect(0, 0, view.width, view.height);

            const thickness = this.config.slabThickness || mpr.DEFAULT_SLAB;
            ctx.fillStyle = 'rgba(200, 214, 230, 0.85)';
            this._loadedPositions().forEach((positions) => {
                // Strided for dense clouds: a slab of a two-million point
                // cloud is still hundreds of thousands of points, and drawing
                // every one costs more than the extra density is worth in a
                // 240-pixel panel.
                const count = Math.floor(positions.length / 3);
                const stride = Math.max(1, Math.floor(count / 40000));
                mpr.slabIndices(positions, view, thickness, stride)
                    .forEach((i) => {
                        const p = mpr.worldToPanel(
                            view, [positions[i * 3], positions[i * 3 + 1],
                                   positions[i * 3 + 2]]);
                        ctx.fillRect(p.x, p.y, 1.5, 1.5);
                    });
            });

            this._drawSlabCrosshair(ctx, view);
            this.annotations.forEach((obj, index) => {
                if (this._hiddenLabels && this._hiddenLabels.has(obj.label)) {
                    return;
                }
                this._drawSlabAnnotation(ctx, view, obj,
                                         index === this.selectedIndex);
            });

            entry.caption.textContent =
                `${mpr.PLANES[plane].label} — ${thickness.toFixed(1)} m slab`;
        }

        _drawSlabCrosshair(ctx, view) {
            ctx.strokeStyle = 'rgba(120, 140, 170, 0.35)';
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(view.width / 2, 0);
            ctx.lineTo(view.width / 2, view.height);
            ctx.moveTo(0, view.height / 2);
            ctx.lineTo(view.width, view.height / 2);
            ctx.stroke();
        }

        _drawSlabAnnotation(ctx, view, obj, selected) {
            const color = obj.color || '#ff6b6b';
            if (obj.type === 'cuboid_3d' && obj.coordinates) {
                const env = mpr.boxEnvelope(view, obj.coordinates);
                const a = mpr.worldToPanel(
                    view, _slabPoint(view, env.uMin, env.vMin));
                const b = mpr.worldToPanel(
                    view, _slabPoint(view, env.uMax, env.vMax));
                ctx.strokeStyle = color;
                ctx.lineWidth = selected ? 2 : 1;
                ctx.setLineDash(selected ? [] : [4, 3]);
                ctx.strokeRect(Math.min(a.x, b.x), Math.min(a.y, b.y),
                               Math.abs(b.x - a.x), Math.abs(b.y - a.y));
                ctx.setLineDash([]);
                return;
            }
            if (obj.type === 'point_3d' && Array.isArray(obj.coordinates)) {
                const p = mpr.worldToPanel(view, obj.coordinates);
                ctx.fillStyle = color;
                ctx.beginPath();
                ctx.arc(p.x, p.y, selected ? 5 : 3, 0, Math.PI * 2);
                ctx.fill();
            }
        }

        _bindSlab(plane, canvas) {
            canvas.addEventListener('mousedown', (e) => {
                const view = this._slabView(plane);
                const selection = this.annotations[this.selectedIndex];
                if (!view || !selection || selection.type !== 'cuboid_3d') return;

                const point = _canvasPoint(canvas, e);
                const handle = mpr.handleAt(
                    view, selection.coordinates, point.x, point.y);
                if (!handle) return;

                e.preventDefault();
                const world = mpr.panelToWorld(view, point.x, point.y);
                const center = selection.coordinates.center;
                this._slabDrag = {
                    plane, handle,
                    offset: [world[0] - center[0], world[1] - center[1],
                             world[2] - center[2]],
                };
            });

            canvas.addEventListener('mousemove', (e) => {
                const view = this._slabView(plane);
                if (!view) return;
                const point = _canvasPoint(canvas, e);

                if (!this._slabDrag || this._slabDrag.plane !== plane) {
                    // The cursor is the only affordance a slab panel has: an
                    // edge that can be dragged and one that cannot look
                    // identical until you try.
                    const selection = this.annotations[this.selectedIndex];
                    const handle = (selection && selection.type === 'cuboid_3d')
                        ? mpr.handleAt(view, selection.coordinates,
                                       point.x, point.y)
                        : null;
                    canvas.style.cursor = _cursorFor(handle);
                    return;
                }

                const selection = this.annotations[this.selectedIndex];
                if (!selection) return;
                const world = mpr.panelToWorld(view, point.x, point.y);
                selection.coordinates = mpr.applyDrag(
                    view, selection.coordinates, this._slabDrag.handle, world,
                    this._slabDrag.offset);
                this._rebuildMesh(this.selectedIndex);
                this._updateAnnotationData();
            });

            const end = () => {
                if (!this._slabDrag) return;
                this._slabDrag = null;
                // One history entry per drag, not per mousemove: undo has to
                // step back to before the drag, not through sixty intermediate
                // sizes.
                this._saveState();
            };
            canvas.addEventListener('mouseup', end);
            canvas.addEventListener('mouseleave', end);

            canvas.addEventListener('wheel', (e) => {
                e.preventDefault();
                this._nudgeSlabThickness(e.deltaY > 0 ? 1.15 : 1 / 1.15);
            }, { passive: false });

            canvas.addEventListener('keydown', (e) => this._slabKey(plane, e));
        }

        /**
         * Keyboard equivalent of a slab drag.
         *
         * The pointer path can do three things — move the box in the plane,
         * push one face out, pull one face in — and all three have to be
         * reachable from the keyboard (WCAG 2.1.1). The arrow names the side,
         * so the modifier only has to say which direction that side moves:
         * Shift outward, Alt inward. A scheme where the arrow named the
         * direction instead would leave two of the four faces unreachable.
         */
        _slabKey(plane, e) {
            if (e.key === '[' || e.key === ']') {
                e.preventDefault();
                // The document-level handler is still listening; a label whose
                // key_value happened to be a bracket would otherwise fire too.
                e.stopPropagation();
                this._nudgeSlabThickness(e.key === ']' ? 1.15 : 1 / 1.15);
                this._announce(
                    `Slab thickness ${this.config.slabThickness.toFixed(1)} m`);
                return;
            }

            const dir = SLAB_ARROWS[e.key];
            if (!dir) return;
            // Ctrl/Cmd is the browser's and the OS's; claiming it here would
            // shadow real shortcuts for the one class of user who cannot fall
            // back to the mouse.
            if (e.ctrlKey || e.metaKey) return;
            e.stopPropagation();

            const view = this._slabView(plane);
            const selection = this.annotations[this.selectedIndex];
            if (!view || !selection || selection.type !== 'cuboid_3d') {
                this._announce('Select a box first.');
                return;
            }
            e.preventDefault();

            const spec = view.spec;
            const axis = dir.axis === 'u' ? spec.u : spec.v;
            // Screen-up is world-positive on a flipped axis. Without this the
            // box moves the opposite way from the arrow in every panel, which
            // reads as the control being broken rather than inverted.
            const sign = (dir.axis === 'v' && spec.flipV)
                ? -dir.screen : dir.screen;
            const step = e.shiftKey || e.altKey
                ? SLAB_RESIZE_STEP : SLAB_MOVE_STEP;

            let handle = 'move';
            let target = selection.coordinates.center[axis] + sign * step;
            if (e.shiftKey || e.altKey) {
                const env = mpr.boxEnvelope(view, selection.coordinates);
                const lo = dir.axis === 'u' ? env.uMin : env.vMin;
                const hi = dir.axis === 'u' ? env.uMax : env.vMax;
                // The face on the side the arrow points to, in world terms.
                const atMax = sign > 0;
                handle = `${dir.axis}-${atMax ? 'max' : 'min'}`;
                // Shift pushes it away from the box, Alt pulls it in.
                const outward = e.shiftKey ? sign : -sign;
                target = (atMax ? hi : lo) + outward * step;
            }

            const world = selection.coordinates.center.slice();
            world[axis] = target;
            const before = JSON.stringify(selection.coordinates);
            selection.coordinates = mpr.applyDrag(
                view, selection.coordinates, handle, world, [0, 0, 0]);

            if (JSON.stringify(selection.coordinates) === before) {
                // applyDrag refuses a degenerate result. Saying so beats a key
                // that silently does nothing, which reads as a dropped input.
                this._announce('Box is already at its minimum size.');
                return;
            }
            this._rebuildMesh(this.selectedIndex);
            // _updateAnnotationData redraws the slabs and the camera overlays,
            // so there is no separate redraw here.
            this._updateAnnotationData();
            // One history entry per keypress, unlike a drag: each press is a
            // discrete, deliberate edit and should undo on its own.
            this._saveState();
            this._announce(describeBox(selection.coordinates));
        }

        _nudgeSlabThickness(factor) {
            const next = (this.config.slabThickness || mpr.DEFAULT_SLAB)
                * factor;
            this.config.slabThickness = Math.min(200, Math.max(0.1, next));
            this._drawMpr();
        }

        /** Rebuild one annotation's mesh in place after an edit. */
        _rebuildMesh(index) {
            const old = this.meshes[index];
            if (old) this.scene.remove(old);
            // `_buildMesh` appends, so build and then move the result into the
            // same slot. Index IS identity here — the hidden input, the
            // annotation list and `getAnnotationHandles()` all key on array
            // position, so letting it shift would relabel every later box.
            this._buildMesh(this.annotations[index]);
            this.meshes[index] = this.meshes.pop();
            this._render();
        }

        /**
         * Redraw one camera panel's wireframes.
         *
         * The overlay canvas is sized in CSS pixels to match the displayed
         * image, and the projection is scaled from image pixels by the
         * displayed/natural ratio. Using the natural size directly would draw
         * every box off-panel the moment the layout scaled the photograph
         * down, which it always does.
         */
        _drawOverlay(index) {
            if (!calib || !this.container) return;
            const panel = this.container.querySelector(
                `.pc-camera[data-camera="${index}"]`);
            const cam = this.cameras[index];
            if (!panel || !cam) return;

            const img = panel.querySelector('.pc-camera-image');
            const canvas = panel.querySelector('.pc-camera-overlay');
            if (!img || !canvas || !canvas.getContext) return;

            const shownW = img.clientWidth;
            const shownH = img.clientHeight;
            const naturalW = img.naturalWidth || cam.width || shownW;
            const naturalH = img.naturalHeight || cam.height || shownH;
            if (!shownW || !shownH || !naturalW || !naturalH) return;

            // Assigning width/height reallocates the backing store and clears
            // it, so it is guarded rather than done every repaint -- this runs
            // on every annotation change AND on every ResizeObserver tick,
            // which fires many times during a single window drag.
            if (canvas.width !== shownW || canvas.height !== shownH) {
                canvas.width = shownW;
                canvas.height = shownH;
            }
            const sx = shownW / naturalW;
            const sy = shownH / naturalH;

            const ctx = canvas.getContext('2d');
            ctx.clearRect(0, 0, shownW, shownH);
            ctx.lineWidth = 2;
            ctx.lineJoin = 'round';

            this.annotations.forEach((obj, i) => {
                if (obj.type !== 'cuboid_3d') return;
                if (this._hiddenLabels && this._hiddenLabels.has(obj.label)) return;
                const c = obj.coordinates || {};
                const corners = cuboidCorners(c.center, c.size, c.rotation);
                const projected = calib.projectCuboid(cam, corners);
                if (!projected.visible) return;
                if (!calib.overlapsImage(projected.bbox, naturalW, naturalH)) return;

                ctx.strokeStyle = obj.color || '#ffffff';
                ctx.globalAlpha = (this.selectedIndex < 0
                                   || i === this.selectedIndex) ? 1.0 : 0.4;
                ctx.beginPath();
                projected.edges.forEach((edge) => {
                    ctx.moveTo(edge[0][0] * sx, edge[0][1] * sy);
                    ctx.lineTo(edge[1][0] * sx, edge[1][1] * sy);
                });
                ctx.stroke();
            });
            ctx.globalAlpha = 1.0;
        }

        // -------------------------------------------------------------
        // Navigation
        // -------------------------------------------------------------

        _bindNavigation() {
            let dragging = null;
            let last = null;

            this.canvas.addEventListener('mousedown', (e) => {
                if (this.currentTool && e.button === 0) return;  // drawing
                dragging = e.button === 2 ? 'pan' : 'orbit';
                last = { x: e.clientX, y: e.clientY };
                e.preventDefault();
            });
            window.addEventListener('mousemove', (e) => {
                if (!dragging || !last) return;
                const dx = e.clientX - last.x;
                const dy = e.clientY - last.y;
                last = { x: e.clientX, y: e.clientY };
                if (dragging === 'orbit') {
                    this._orbit.theta -= dx * 0.005;
                    // Clamped just short of the poles: at exactly 0 or PI the
                    // up vector and the view direction are parallel and the
                    // camera flips over, which reads as the scene jumping.
                    this._orbit.phi = Math.min(Math.PI - 0.01, Math.max(
                        0.01, this._orbit.phi - dy * 0.005));
                } else {
                    const scale = this._orbit.radius * 0.002;
                    const right = new THREE.Vector3().setFromSphericalCoords(
                        1, Math.PI / 2, this._orbit.theta + Math.PI / 2);
                    this._orbit.target.addScaledVector(right, -dx * scale);
                    this._orbit.target.z += dy * scale;
                }
                this._applyCamera();
            });
            window.addEventListener('mouseup', () => { dragging = null; });
            this.canvas.addEventListener('contextmenu', (e) => e.preventDefault());
            this.canvas.addEventListener('wheel', (e) => {
                e.preventDefault();
                this._orbit.radius = Math.max(
                    0.5, this._orbit.radius * (e.deltaY > 0 ? 1.1 : 0.9));
                this._applyCamera();
            }, { passive: false });
        }

        _applyCamera() {
            if (!this.camera) return;
            const { theta, phi, radius, target } = this._orbit;
            // Spherical about the target, in a Z-up frame.
            this.camera.position.set(
                target.x + radius * Math.sin(phi) * Math.cos(theta),
                target.y + radius * Math.sin(phi) * Math.sin(theta),
                target.z + radius * Math.cos(phi));
            this.camera.lookAt(target);
            this._render();
            // Detail follows the camera. Debounced, so an orbit drag does not
            // start a fetch per frame.
            this._scheduleLodUpdate();
        }

        // -------------------------------------------------------------
        // Tools and labels
        // -------------------------------------------------------------

        _bindToolbar() {
            if (!this.container) return;
            this.container.querySelectorAll('[data-tool]').forEach((btn) => {
                btn.addEventListener('click', () => this.setTool(btn.dataset.tool));
            });
            this.container.querySelectorAll('.label-btn').forEach((btn) => {
                btn.addEventListener('click', () => {
                    this.setLabel(btn.dataset.label, btn.dataset.color);
                });
            });
            const first = this.container.querySelector('.label-btn');
            if (first) this.setLabel(first.dataset.label, first.dataset.color);

            if (typeof LabelVisibilityManager !== 'undefined') {
                this.labelVisibility = new LabelVisibilityManager({
                    container: this.container,
                    schema: this.config.schema,
                    onChange: (hidden) => this.applyLabelVisibility(hidden),
                });
            }
        }

        _bindKeys() {
            const keys = this.config.toolKeys || {};
            this._keyHandler = (e) => {
                // Never steal a key from a text field. The image manager did
                // exactly that, and typing "bad boxes here" in a free-text
                // question next to the canvas produced "badboxesee".
                const t = e.target;
                if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA'
                          || t.tagName === 'SELECT' || t.isContentEditable)) {
                    return;
                }
                if (e.ctrlKey || e.metaKey || e.altKey) return;

                // Cycling the selection. Until this existed, selectedIndex was
                // set only by drawing a box or by clicking one, so a keyboard
                // user could never reach an annotation they had not just made
                // — which made every selection-dependent key below, and the
                // slab panels, unreachable (WCAG 2.1.1). `,`/`.` rather than
                // Tab, which belongs to focus, and matching the prev/next
                // convention the video timeline already uses.
                if (e.key === ',' || e.key === '.') {
                    if (!this.annotations.length) return;
                    e.preventDefault();
                    this.cycleSelection(e.key === '.' ? 1 : -1);
                    return;
                }

                // Adjusting the selected box. Yaw is the one dimension a
                // drag cannot express, and a box that is the right size but
                // 30 degrees off is the commonest 3D labelling error.
                if (this.selectedIndex >= 0) {
                    const step = e.shiftKey ? Math.PI / 180 : Math.PI / 36;
                    if (e.key === 'q' || e.key === 'Q') {
                        e.preventDefault();
                        this.rotateSelected(step);
                        return;
                    }
                    if (e.key === 'e' || e.key === 'E') {
                        e.preventDefault();
                        this.rotateSelected(-step);
                        return;
                    }
                    if (e.key === 'Delete' || e.key === 'Backspace') {
                        e.preventDefault();
                        this.deleteSelected();
                        return;
                    }
                    if (e.key === 'Escape') {
                        e.preventDefault();
                        this.selectedIndex = -1;
                        this._highlightSelection();
                        this._drawOverlays();
                        return;
                    }
                }

                for (const tool of Object.keys(keys)) {
                    if (e.key === keys[tool]) {
                        e.preventDefault();
                        this.setTool(tool);
                        return;
                    }
                }
                for (const label of (this.config.labels || [])) {
                    if (label.key_value && e.key === String(label.key_value)) {
                        e.preventDefault();
                        this.setLabel(label.name, label.color);
                        return;
                    }
                }
            };
            document.addEventListener('keydown', this._keyHandler);
        }

        setTool(tool) {
            this.currentTool = this.currentTool === tool ? null : tool;
            if (!this.container) return;
            this.container.querySelectorAll('[data-tool]').forEach((btn) => {
                const on = btn.dataset.tool === this.currentTool;
                btn.classList.toggle('active', on);
                // Updated here rather than only in the click handler, or a
                // screen reader hears every tool report "not pressed" when the
                // keyboard shortcut is used (WCAG 4.1.2).
                btn.setAttribute('aria-pressed', on ? 'true' : 'false');
            });
        }

        setLabel(name, color) {
            this.currentLabel = name;
            this.currentColor = color;
            if (!this.container) return;
            this.container.querySelectorAll('.label-btn').forEach((btn) => {
                const on = btn.dataset.label === name;
                btn.classList.toggle('active', on);
                btn.setAttribute('aria-pressed', on ? 'true' : 'false');
            });
        }

        // -------------------------------------------------------------
        // Annotations
        // -------------------------------------------------------------

        /**
         * Add one client-contract annotation. The sanctioned programmatic entry
         * point — importers, AI suggestions and copy-between-items all route
         * here so the contract is enforced in exactly one place.
         */
        addAnnotation(obj) {
            if (!obj || typeof obj !== 'object') return false;
            const known = ['cuboid_3d', 'point_3d', 'polyline_3d', 'segment_3d'];
            if (known.indexOf(obj.type) < 0) {
                console.warn('[pointcloud] refusing an unknown annotation type',
                             obj.type);
                return false;
            }
            this.annotations.push(obj);
            this._buildMesh(obj);
            this._saveState();
            this._updateAnnotationData();
            return true;
        }

        /**
         * Serialization order is identity: reports and actions address an
         * annotation by index, so this must agree with `_serializeAnnotations`.
         */
        getAnnotationHandles() {
            return this.annotations.map((obj, index) => ({
                index,
                kind: obj.type,
                label: obj.label,
                type: obj.type,
            }));
        }

        deleteAnnotation(index) {
            if (index < 0 || index >= this.annotations.length) return false;
            this.annotations.splice(index, 1);
            const mesh = this.meshes.splice(index, 1)[0];
            if (mesh) this.scene.remove(mesh);
            this._saveState();
            this._updateAnnotationData();
            this._render();
            return true;
        }

        relabelAnnotation(index, label) {
            const obj = this.annotations[index];
            const color = this.colorForLabel(label);
            if (!obj || !color) return false;
            obj.label = label;
            obj.color = color;
            this._rebuildMeshes();
            this._saveState();
            this._updateAnnotationData();
            return true;
        }

        colorForLabel(name) {
            for (const label of (this.config.labels || [])) {
                const n = (label && label.name !== undefined) ? label.name : label;
                if (n === name) return (label && label.color) || null;
            }
            return null;
        }

        applyLabelVisibility(hidden) {
            this._hiddenLabels = hidden || new Set();
            this.meshes.forEach((mesh, i) => {
                const obj = this.annotations[i];
                if (mesh) mesh.visible = !this._hiddenLabels.has(obj.label);
            });
            // Hiding a class must hide it in the camera panels too, or the
            // verification view contradicts the viewport.
            this._drawOverlays();
            this._render();
        }

        clearAnnotations() {
            // NOTHING here is managed by a scene-graph traversal, so every
            // field is cleared explicitly. The image manager shipped three
            // separate cross-instance corruption bugs from state that a
            // canvas-scoped clear could not reach.
            this.meshes.forEach((m) => { if (m) this.scene.remove(m); });
            this.meshes = [];
            this.annotations = [];
            this.currentTool = null;
            this.history = [];
            this.historyIndex = -1;
            // Selection and the in-flight drag are annotation state too. A
            // stale selectedIndex would point at the next item's annotations,
            // and q/e would silently rotate the wrong box.
            this.selectedIndex = -1;
            this._drag = null;
            // The slab drag is annotation-editing state as much as `_drag` is.
            // Left set across an instance switch, the next mousemove over a
            // panel would resize whatever ended up at the old selected index.
            this._slabDrag = null;
            this._clearPreview();
            this._render();
            this._updateAnnotationData();
        }

        serialize() {
            return this._serializeAnnotations();
        }

        _serializeAnnotations() {
            return JSON.stringify(this.annotations);
        }

        _updateAnnotationData() {
            // Every mutation funnels through here, so this is the one place the
            // camera panels have to be refreshed from -- rather than a redraw
            // call bolted onto each of add/delete/relabel/undo/redo, which is
            // how one of them ends up forgotten and the photograph silently
            // disagrees with the viewport.
            this._drawOverlays();

            const input = document.getElementById(this.inputId);
            if (!input) return;
            input.value = this._serializeAnnotations();
            input.setAttribute('data-modified', 'true');
            input.dispatchEvent(new Event('change', { bubbles: true }));
        }

        _restoreFromInput() {
            const input = document.getElementById(this.inputId);
            if (!input || !input.value) return;
            let parsed;
            try {
                parsed = JSON.parse(input.value);
            } catch (err) {
                console.warn('[pointcloud] stored annotations are not JSON', err);
                return;
            }
            if (!Array.isArray(parsed)) return;
            this.annotations = parsed;
            this._rebuildMeshes();
        }

        _rebuildMeshes() {
            this.meshes.forEach((m) => { if (m) this.scene.remove(m); });
            this.meshes = [];
            this.annotations.forEach((obj) => this._buildMesh(obj));
            if (this._hiddenLabels) this.applyLabelVisibility(this._hiddenLabels);
            this._render();
        }

        _buildMesh(obj) {
            if (!this.scene || typeof THREE === 'undefined') {
                this.meshes.push(null);
                return;
            }
            const color = threeColor(obj.color);
            let mesh = null;

            if (obj.type === 'cuboid_3d') {
                mesh = this._boxMesh(obj, color);
            } else if (obj.type === 'point_3d') {
                mesh = this._pointMesh(obj, color);
            } else if (obj.type === 'polyline_3d') {
                mesh = this._polylineMesh(obj, color);
            }
            // segment_3d has no mesh of its own: it recolours points in the
            // cloud, which is handled by the cloud's own colour attribute.

            if (mesh) this.scene.add(mesh);
            this.meshes.push(mesh);
        }

        _boxMesh(obj, color) {
            const c = obj.coordinates || {};
            const corners = cuboidCorners(c.center, c.size, c.rotation);
            const points = [];
            BOX_EDGES.forEach(([a, b]) => {
                points.push(new THREE.Vector3(...corners[a]));
                points.push(new THREE.Vector3(...corners[b]));
            });
            const geometry = new THREE.BufferGeometry().setFromPoints(points);
            return new THREE.LineSegments(
                geometry, new THREE.LineBasicMaterial({ color }));
        }

        _pointMesh(obj, color) {
            const geometry = new THREE.SphereGeometry(0.15, 8, 6);
            const mesh = new THREE.Mesh(
                geometry, new THREE.MeshBasicMaterial({ color }));
            const c = obj.coordinates || [0, 0, 0];
            mesh.position.set(c[0], c[1], c[2]);
            return mesh;
        }

        _polylineMesh(obj, color) {
            const points = (obj.coordinates || []).map(
                (p) => new THREE.Vector3(p[0], p[1], p[2]));
            if (points.length < 2) return null;
            const geometry = new THREE.BufferGeometry().setFromPoints(points);
            return new THREE.Line(
                geometry, new THREE.LineBasicMaterial({ color }));
        }

        // -------------------------------------------------------------
        // History and status
        // -------------------------------------------------------------

        _saveState() {
            this.history = this.history.slice(0, this.historyIndex + 1);
            this.history.push(JSON.stringify(this.annotations));
            if (this.history.length > this.maxHistory) this.history.shift();
            this.historyIndex = this.history.length - 1;
        }

        undo() {
            if (this.historyIndex <= 0) return false;
            this.historyIndex -= 1;
            this.annotations = JSON.parse(this.history[this.historyIndex]);
            this._rebuildMeshes();
            this._updateAnnotationData();
            return true;
        }

        redo() {
            if (this.historyIndex >= this.history.length - 1) return false;
            this.historyIndex += 1;
            this.annotations = JSON.parse(this.history[this.historyIndex]);
            this._rebuildMeshes();
            this._updateAnnotationData();
            return true;
        }

        getAnnotationCount() {
            return this.annotations.length;
        }

        _status(message, kind) {
            const el = this.container
                && this.container.querySelector('.pc-status');
            if (el) {
                el.textContent = message;
                el.dataset.kind = kind || 'info';
            }
            // .pc-status is not a live region — level-of-detail loading
            // rewrites it about eight times a second while the camera moves.
            // Anything that is not that routine chatter is announced, so a
            // screen-reader user still hears every error and warning.
            if (kind === 'error' || kind === 'warn') this._announce(message);
        }

        /**
         * Say something once, to assistive tech only.
         *
         * The viewport and the slab panels are pixels: an edit that only
         * redraws them is otherwise completely silent.
         */
        _announce(message) {
            const el = this.container
                && this.container.querySelector('.pc-announce[aria-live]');
            if (!el) return;
            // An identical string is not re-announced by most screen readers,
            // and nudging a box repeatedly in one direction produces runs of
            // them. The zero-width space makes each one a distinct value
            // without changing what is read out.
            el.textContent = (el.textContent === message)
                ? `${message}${'\u200B'}` : message;
        }
    }

    /**
     * Eight corners of an oriented box, in the order `spatial_utils.py`'s
     * `cuboid_corners` produces: the -Z face first, then +Z.
     *
     * Duplicated from Python on purpose — the two ends must agree, and a
     * round-trip test in each language is a better guarantee than one
     * implementation neither end can check.
     */
    function cuboidCorners(center, size, rotation) {
        const c = center || [0, 0, 0];
        const s = size || [1, 1, 1];
        const q = normalizeQuat(rotation);
        const [hx, hy, hz] = [Math.abs(s[0]) / 2, Math.abs(s[1]) / 2,
                              Math.abs(s[2]) / 2];
        const [qx, qy, qz, qw] = q;
        const xx = qx * qx, yy = qy * qy, zz = qz * qz;
        const xy = qx * qy, xz = qx * qz, yz = qy * qz;
        const wx = qw * qx, wy = qw * qy, wz = qw * qz;
        const m = [
            [1 - 2 * (yy + zz), 2 * (xy - wz), 2 * (xz + wy)],
            [2 * (xy + wz), 1 - 2 * (xx + zz), 2 * (yz - wx)],
            [2 * (xz - wy), 2 * (yz + wx), 1 - 2 * (xx + yy)],
        ];

        const out = [];
        for (const sz of [-hz, hz]) {
            for (const [sx, sy] of [[-hx, -hy], [hx, -hy], [hx, hy], [-hx, hy]]) {
                out.push([
                    c[0] + m[0][0] * sx + m[0][1] * sy + m[0][2] * sz,
                    c[1] + m[1][0] * sx + m[1][1] * sy + m[1][2] * sz,
                    c[2] + m[2][0] * sx + m[2][1] * sy + m[2][2] * sz,
                ]);
            }
        }
        return out;
    }

    /**
     * Where a ray meets the horizontal plane at height `z`, or null.
     *
     * Null when the ray is parallel to the plane or points away from it — both
     * happen constantly, because the camera orbits freely and half of every
     * sweep of the mouse across the horizon points at the sky. Returning a
     * point anyway would place boxes at absurd distances.
     */
    function intersectPlaneZ(origin, direction, z) {
        const dz = direction[2];
        if (!Number.isFinite(dz) || Math.abs(dz) < 1e-9) return null;
        const t = (z - origin[2]) / dz;
        if (!(t > 0)) return null;
        return [origin[0] + direction[0] * t,
                origin[1] + direction[1] * t,
                z];
    }

    /**
     * Ground height, as a low percentile of the cloud's z values.
     *
     * Not the minimum: one stray return from a manhole or a multipath
     * reflection sits metres below the road, and anchoring every box to it
     * would bury them all. Not zero either — a roof-mounted lidar reports the
     * road at about -1.7, so a box drawn on z = 0 floats above the scene.
     *
     * Sampled with a stride rather than sorting two million floats, which
     * would take longer than loading the cloud did.
     */
    /**
     * One position buffer, or several, as a list.
     *
     * Under level-of-detail loading the cloud is many buffers rather than one,
     * and the geometry helpers have to read all of them. Accepting either shape
     * here means the single-buffer path keeps calling them unchanged rather
     * than every call site growing an `Array.isArray` branch of its own.
     */
    function asChunks(positions) {
        if (!positions) return [];
        if (Array.isArray(positions)) {
            return positions.filter((p) => p && p.length);
        }
        return positions.length ? [positions] : [];
    }

    /** A world point on a slab's centre plane, at in-plane (u, v). */
    function _slabPoint(view, u, v) {
        const out = view.center.slice();
        out[view.spec.u] = u;
        out[view.spec.v] = v;
        return out;
    }

    /**
     * Pointer position in CSS pixels relative to a canvas.
     *
     * From `getBoundingClientRect`, not `offsetX`: the canvas is sized in
     * device pixels and scaled by CSS, so `offsetX` is in a different unit
     * from the coordinates the view was built with and every hit test would be
     * off by the device pixel ratio.
     */
    function _canvasPoint(canvas, event) {
        const rect = canvas.getBoundingClientRect();
        return { x: event.clientX - rect.left, y: event.clientY - rect.top };
    }

    /** The cursor that says what a handle will do. */
    function _cursorFor(handle) {
        if (!handle) return 'default';
        if (handle === 'move') return 'move';
        return handle.startsWith('u-') ? 'ew-resize' : 'ns-resize';
    }

    /** Add or replace a query parameter on a URL that may already have one. */
    function withParam(url, name, value) {
        const sep = url.indexOf('?') === -1 ? '?' : '&';
        return `${url}${sep}${encodeURIComponent(name)}=${encodeURIComponent(value)}`;
    }

    function groundLevel(positions, percentile) {
        const chunks = asChunks(positions);
        if (!chunks.length) return 0;
        const q = (percentile === undefined) ? 0.02 : percentile;
        const total = chunks.reduce((n, c) => n + Math.floor(c.length / 3), 0);
        const stride = Math.max(1, Math.floor(total / 20000));
        const zs = [];
        chunks.forEach((chunk) => {
            const count = Math.floor(chunk.length / 3);
            for (let i = 0; i < count; i += stride) zs.push(chunk[i * 3 + 2]);
        });
        if (!zs.length) return 0;
        zs.sort((a, b) => a - b);
        return zs[Math.min(zs.length - 1,
                           Math.floor(zs.length * q))];
    }

    /**
     * A cuboid from two ground-plane corners of its footprint.
     *
     * The drag gives an axis-aligned rectangle in world XY; `yaw` then turns
     * the box about its own centre. Returns null for a degenerate footprint so
     * that a stray click cannot leave a zero-size annotation — the same guard
     * the 2D canvas needed.
     */
    function footprintToCuboid(a, b, yaw, groundZ, height) {
        if (!a || !b) return null;
        const dx = Math.abs(b[0] - a[0]);
        const dy = Math.abs(b[1] - a[1]);
        // 10 cm: below this it is a click, not a drag. A car is 1.8 m wide, so
        // nothing real is lost.
        if (dx < 0.1 || dy < 0.1) return null;
        const h = Math.abs(height) || 1.7;
        return {
            center: [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2, groundZ + h / 2],
            size: [dx, dy, h],
            rotation: yawQuaternion(yaw || 0),
        };
    }

    /**
     * Snap a box's vertical extent to the points inside its footprint.
     *
     * Height is the dimension a top-down drag cannot express and the one an
     * annotator judges worst in a perspective view of a sparse cloud — but the
     * returns themselves answer it exactly. Returns the box unchanged when the
     * footprint is empty, which means the annotator drew around nothing and
     * a fitted height would be a fabrication.
     */
    function fitHeightToPoints(coords, positions, groundZ, minPoints) {
        const chunks = asChunks(positions);
        if (!coords || !chunks.length) return coords;
        const need = (minPoints === undefined) ? 5 : minPoints;
        const inv = invertYaw(coords.rotation);
        const cx = coords.center[0], cy = coords.center[1];
        const hx = coords.size[0] / 2, hy = coords.size[1] / 2;

        let lo = Infinity;
        let hi = -Infinity;
        let hits = 0;
        for (let c = 0; c < chunks.length; c++) {
            const buffer = chunks[c];
            const count = Math.floor(buffer.length / 3);
            for (let i = 0; i < count; i++) {
                const dx = buffer[i * 3] - cx;
                const dy = buffer[i * 3 + 1] - cy;
                // Rotate into the box's own frame, so a yawed footprint tests
                // against its true extent rather than its bounding rectangle.
                const rx = dx * inv.c - dy * inv.s;
                const ry = dx * inv.s + dy * inv.c;
                if (Math.abs(rx) > hx || Math.abs(ry) > hy) continue;
                const z = buffer[i * 3 + 2];
                // Points at or below the ground are the road surface, not the
                // object; including them stretches every box down to the tarmac.
                if (z < groundZ + 0.05) continue;
                if (z < lo) lo = z;
                if (z > hi) hi = z;
                hits++;
            }
        }
        if (hits < need || !(hi > lo)) return coords;

        // The bottom stays on the ground rather than at the lowest return:
        // lidar rarely sees a car's sill, so the lowest hit is usually the
        // bumper and a box that starts there floats.
        const top = hi + 0.05;
        return {
            center: [coords.center[0], coords.center[1], (groundZ + top) / 2],
            size: [coords.size[0], coords.size[1], top - groundZ],
            rotation: coords.rotation.slice(),
        };
    }

    /** Quaternion for a rotation of `yaw` radians about +Z. */
    function yawQuaternion(yaw) {
        const half = yaw / 2;
        return [0, 0, Math.sin(half), Math.cos(half)];
    }

    /** `rotation` followed by an extra yaw, as a quaternion. */
    function composeYaw(rotation, yaw) {
        const q = normalizeQuat(rotation);
        const r = yawQuaternion(yaw);
        // Hamilton product r * q: the extra yaw is applied in the world frame,
        // so pressing `q` always turns the box the same way on screen no
        // matter how it is already oriented.
        return normalizeQuat([
            r[3] * q[0] + r[0] * q[3] + r[1] * q[2] - r[2] * q[1],
            r[3] * q[1] - r[0] * q[2] + r[1] * q[3] + r[2] * q[0],
            r[3] * q[2] + r[0] * q[1] - r[1] * q[0] + r[2] * q[3],
            r[3] * q[3] - r[0] * q[0] - r[1] * q[1] - r[2] * q[2],
        ]);
    }

    /** cos/sin of the negated yaw of a quaternion, for the inverse rotation. */
    function invertYaw(rotation) {
        const q = normalizeQuat(rotation);
        const yaw = Math.atan2(2 * (q[3] * q[2] + q[0] * q[1]),
                               1 - 2 * (q[1] * q[1] + q[2] * q[2]));
        return { c: Math.cos(-yaw), s: Math.sin(-yaw) };
    }

    /** A representative 3D point for an annotation, for hit-testing. */
    function annotationCenter(obj) {
        if (!obj) return null;
        if (obj.type === 'cuboid_3d') {
            return (obj.coordinates && obj.coordinates.center) || null;
        }
        if (obj.type === 'point_3d') return obj.coordinates || null;
        if (obj.type === 'polyline_3d') {
            const pts = obj.coordinates || [];
            if (!pts.length) return null;
            const sum = pts.reduce((a, p) => [a[0] + p[0], a[1] + p[1],
                                              a[2] + p[2]], [0, 0, 0]);
            return sum.map((v) => v / pts.length);
        }
        return null;
    }

    /** "4.2 x 1.8 x 1.5 m at 12.0, 1.5" — the numbers, for the status line. */
    function describeBox(coords) {
        const s = coords.size;
        const c = coords.center;
        return `${s[0].toFixed(1)} x ${s[1].toFixed(1)} x ${s[2].toFixed(1)} m `
            + `at ${c[0].toFixed(1)}, ${c[1].toFixed(1)}`;
    }

    /**
     * A THREE.Color for a schema colour, in the sRGB the label button uses.
     *
     * `new THREE.Color(r, g, b)` interprets floats as **linear-sRGB working
     * space** since r155's colour management, so handing it sRGB-encoded
     * values silently brightens every annotation: `#ff6b6b` rendered as
     * `#ffadad`, close enough to look intentional and wrong enough that a box
     * no longer matches its own label swatch. `setRGB` with an explicit colour
     * space does the conversion.
     *
     * The parsing stays in `hexToRgb01` rather than THREE's own `setStyle` so
     * that shorthand hex, `#rrggbbaa`, and the unreadable-colour fallback all
     * behave exactly as they do in the 2D manager.
     */
    function threeColor(hex) {
        const rgb = wire.hexToRgb01(hex);
        const color = new THREE.Color();
        if (typeof color.setRGB === 'function' && THREE.SRGBColorSpace) {
            color.setRGB(rgb.r, rgb.g, rgb.b, THREE.SRGBColorSpace);
        } else {
            color.setRGB(rgb.r, rgb.g, rgb.b);
        }
        return color;
    }

    /**
     * Whether a string is plausibly a point cloud path.
     *
     * Checked before fetching so that an item whose text is prose does not
     * produce a request for that prose, and so a missing source reports "no
     * point cloud for this item" rather than a 404 for a sentence.
     */
    function looksLikeCloud(value) {
        if (!value || typeof value !== 'string') return false;
        if (value.length > 512 || /\s/.test(value.trim())) return false;
        return /\.(pcd|ply|bin|las|laz|xyz|pts)(\?|#|$)/i.test(value.trim());
    }

    /** Unit quaternion (x, y, z, w), falling back to identity. */
    function normalizeQuat(raw) {
        if (!Array.isArray(raw) || raw.length < 4) return [0, 0, 0, 1];
        const v = raw.slice(0, 4).map(Number);
        if (v.some((n) => !Number.isFinite(n))) return [0, 0, 0, 1];
        const norm = Math.sqrt(v.reduce((a, n) => a + n * n, 0));
        // A non-unit quaternion SCALES the box when it becomes a matrix, so the
        // annotation renders at the wrong size rather than failing.
        if (norm < 1e-12) return [0, 0, 0, 1];
        return v.map((n) => n / norm);
    }

    PointCloudAnnotationManager.looksLikeCloud = looksLikeCloud;
    PointCloudAnnotationManager.cuboidCorners = cuboidCorners;
    PointCloudAnnotationManager.normalizeQuat = normalizeQuat;
    PointCloudAnnotationManager.BOX_EDGES = BOX_EDGES;
    // The drawing tool's arithmetic, exposed so it can be tested without a
    // WebGL context. Everything above these lines needs a real GPU; none of
    // these do.
    PointCloudAnnotationManager.intersectPlaneZ = intersectPlaneZ;
    PointCloudAnnotationManager.groundLevel = groundLevel;
    PointCloudAnnotationManager.footprintToCuboid = footprintToCuboid;
    PointCloudAnnotationManager.fitHeightToPoints = fitHeightToPoints;
    PointCloudAnnotationManager.yawQuaternion = yawQuaternion;
    PointCloudAnnotationManager.composeYaw = composeYaw;
    PointCloudAnnotationManager.invertYaw = invertYaw;
    PointCloudAnnotationManager.annotationCenter = annotationCenter;
    PointCloudAnnotationManager.asChunks = asChunks;
    PointCloudAnnotationManager.withParam = withParam;

    if (typeof module !== 'undefined' && module.exports) {
        module.exports = PointCloudAnnotationManager;
    }
    if (root) root.PointCloudAnnotationManager = PointCloudAnnotationManager;
})(typeof window !== 'undefined' ? window
    : (typeof globalThis !== 'undefined' ? globalThis : null));

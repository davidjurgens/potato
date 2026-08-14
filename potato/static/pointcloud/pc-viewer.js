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

    /** Edges of a cuboid, as index pairs into `cuboid_corners` order. */
    const BOX_EDGES = [
        [0, 1], [1, 2], [2, 3], [3, 0],   // low-z face
        [4, 5], [5, 6], [6, 7], [7, 4],   // high-z face
        [0, 4], [1, 5], [2, 6], [3, 7],   // verticals
    ];

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
            this.cloud = null;          // THREE.Points
            this.parsed = null;         // pc-wire parse result

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
            this._loadCloud();
            this._loadCalibration();
        }

        destroy() {
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
         * Two sources, in order, mirroring how image annotation finds its
         * image: a display field explicitly wired to this schema, then the
         * instance text (which is where a `text_key` lands). The extension is
         * checked before anything is fetched, so a text-only item does not
         * produce a request for the sentence it happens to contain.
         */
        _cloudPath() {
            const field = this.config.sourceField || 'point_cloud';

            const display = document.querySelector(`[data-field-key="${field}"]`);
            if (display) {
                const value = display.getAttribute('data-source-url')
                    || (display.textContent || '').trim();
                if (looksLikeCloud(value)) return value;
            }

            const text = document.getElementById('text-content')
                || document.getElementById('instance-text');
            if (text) {
                const value = (text.textContent || '').trim();
                if (looksLikeCloud(value)) return value;
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

        async _loadCloud() {
            const url = this._cloudUrl();
            if (!url) {
                this._status(
                    `No point cloud for this item: the "${this.config.sourceField}" `
                    + `field is empty. Check item_properties in the config.`,
                    'error');
                return;
            }

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

        _buildPoints(parsed) {
            if (this.cloud) {
                this.scene.remove(this.cloud);
                this.cloud.geometry.dispose();
                this.cloud.material.dispose();
            }

            const geometry = new THREE.BufferGeometry();
            geometry.setAttribute('position',
                new THREE.BufferAttribute(parsed.positions, 3));

            let mode = this.config.colorMode || 'height';
            let colors = wire.colorize(mode, parsed);
            if (!colors) {
                // Falling back silently would leave the annotator wondering why
                // "colour by intensity" looks like "colour by height".
                this._status(
                    `This cloud has no ${mode} data; colouring by height instead.`,
                    'warn');
                colors = wire.colorize('height', parsed);
            }
            geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));

            this.cloud = new THREE.Points(geometry, new THREE.PointsMaterial({
                size: this.config.pointSize || 1.5,
                sizeAttenuation: false,
                vertexColors: true,
            }));
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
            if (this.config.fitBoxHeight !== false && this.parsed) {
                coords = fitHeightToPoints(coords, this.parsed.positions,
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
    function groundLevel(positions, percentile) {
        if (!positions || !positions.length) return 0;
        const q = (percentile === undefined) ? 0.02 : percentile;
        const count = Math.floor(positions.length / 3);
        const stride = Math.max(1, Math.floor(count / 20000));
        const zs = [];
        for (let i = 0; i < count; i += stride) zs.push(positions[i * 3 + 2]);
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
        if (!coords || !positions || !positions.length) return coords;
        const need = (minPoints === undefined) ? 5 : minPoints;
        const inv = invertYaw(coords.rotation);
        const cx = coords.center[0], cy = coords.center[1];
        const hx = coords.size[0] / 2, hy = coords.size[1] / 2;

        let lo = Infinity;
        let hi = -Infinity;
        let hits = 0;
        const count = Math.floor(positions.length / 3);
        for (let i = 0; i < count; i++) {
            const dx = positions[i * 3] - cx;
            const dy = positions[i * 3 + 1] - cy;
            // Rotate into the box's own frame, so a yawed footprint tests
            // against its true extent rather than its bounding rectangle.
            const rx = dx * inv.c - dy * inv.s;
            const ry = dx * inv.s + dy * inv.c;
            if (Math.abs(rx) > hx || Math.abs(ry) > hy) continue;
            const z = positions[i * 3 + 2];
            // Points at or below the ground are the road surface, not the
            // object; including them stretches every box down to the tarmac.
            if (z < groundZ + 0.05) continue;
            if (z < lo) lo = z;
            if (z > hi) hi = z;
            hits++;
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

    if (typeof module !== 'undefined' && module.exports) {
        module.exports = PointCloudAnnotationManager;
    }
    if (root) root.PointCloudAnnotationManager = PointCloudAnnotationManager;
})(typeof window !== 'undefined' ? window
    : (typeof globalThis !== 'undefined' ? globalThis : null));

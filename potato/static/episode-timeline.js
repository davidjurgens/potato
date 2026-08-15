/**
 * Embodied episode annotation: synchronized video, series lanes, one timeline.
 *
 * ## Why not Peaks.js
 *
 * `tiered-annotation.js` is built on Peaks, which is a waveform widget: it
 * assumes one audio source and draws amplitude. An episode has no audio, has
 * several video streams, and has numeric lanes a waveform view has no concept
 * of. What transfers is the *interaction* — drag to create a segment, lanes
 * with their own labels — and that is reused as a pattern, on a plain canvas.
 *
 * ## Time is the shared coordinate, frames are the storage
 *
 * Everything on screen is in seconds, because that is what the video element
 * exposes and what an annotator reads. Everything stored is in seconds too, so
 * `iaa/geometry.temporal_iou` scores phase boundaries with no conversion. The
 * frame index is recoverable exactly as `round(t * fps)`, which is why the
 * manifest carries fps — a boundary stored in frames and redisplayed in
 * seconds drifts against the data it describes.
 *
 * The pure arithmetic is exported as statics so Jest can drive it without a
 * DOM; the rest needs a real browser and is covered by Playwright.
 */
(function (root) {
    'use strict';

    /** Height of one lane in CSS pixels. */
    const LANE_HEIGHT = 34;
    /** Height of the phase lane, which carries labels and so needs more. */
    const PHASE_LANE_HEIGHT = 46;
    /** Height of the reward lane. */
    const REWARD_LANE_HEIGHT = 60;
    /** Pointer slop for grabbing a segment edge. */
    const EDGE_TOLERANCE = 5;
    /** Shortest segment worth keeping, in seconds. Below this it is a click. */
    const MIN_SEGMENT = 0.05;

    // -----------------------------------------------------------------
    // Pure arithmetic
    // -----------------------------------------------------------------

    /** Seconds -> pixels across a width. */
    function timeToX(t, duration, width) {
        if (!(duration > 0)) return 0;
        return (t / duration) * width;
    }

    /** Pixels -> seconds, clamped into the episode. */
    function xToTime(x, duration, width) {
        if (!(width > 0) || !(duration > 0)) return 0;
        const t = (x / width) * duration;
        return Math.max(0, Math.min(duration, t));
    }

    /**
     * Insert a phase segment, truncating whatever it overlaps.
     *
     * Phases are a *segmentation*: at any instant the robot was doing one
     * thing. Allowing overlap would make "what was it doing at t?" ambiguous
     * and would silently break the temporal-IoU agreement, which assumes a
     * partition. So a new segment wins over what was there, and anything it
     * covers entirely is removed rather than left as a zero-width sliver.
     */
    function insertSegment(segments, incoming) {
        const out = [];
        segments.forEach((seg) => {
            if (seg.end <= incoming.start || seg.start >= incoming.end) {
                out.push(seg);
                return;
            }
            if (seg.start < incoming.start) {
                out.push(Object.assign({}, seg, { end: incoming.start }));
            }
            if (seg.end > incoming.end) {
                out.push(Object.assign({}, seg, { start: incoming.end }));
            }
        });
        out.push(incoming);
        return out
            .filter((s) => s.end - s.start >= MIN_SEGMENT)
            .sort((a, b) => a.start - b.start);
    }

    /** Which segment, and which part of it, is under a time. */
    function segmentAt(segments, t, tolerance) {
        const tol = tolerance === undefined ? 0 : tolerance;
        for (let i = 0; i < segments.length; i++) {
            const s = segments[i];
            if (t < s.start - tol || t > s.end + tol) continue;
            if (Math.abs(t - s.start) <= tol) return { index: i, edge: 'start' };
            if (Math.abs(t - s.end) <= tol) return { index: i, edge: 'end' };
            return { index: i, edge: null };
        }
        return null;
    }

    /**
     * Move one edge of a segment, refusing a degenerate result.
     *
     * Neighbours are not pushed: a phase segmentation is edited one boundary
     * at a time, and a drag that shoved the next segment along would undo an
     * alignment the annotator had already made.
     */
    function resizeSegment(segments, index, edge, t) {
        const seg = segments[index];
        if (!seg) return segments;
        const next = Object.assign({}, seg);
        if (edge === 'start') next.start = Math.min(t, seg.end - MIN_SEGMENT);
        else next.end = Math.max(t, seg.start + MIN_SEGMENT);
        if (next.end - next.start < MIN_SEGMENT) return segments;

        const out = segments.slice();
        out[index] = next;
        return out.sort((a, b) => a.start - b.start);
    }

    /**
     * Write a reward value at a time, replacing any sample within `snap`.
     *
     * A dense reward curve is drawn by dragging, which fires a pointer event
     * every few pixels. Without the snap the curve accumulates hundreds of
     * near-duplicate samples per second and the stored annotation is mostly
     * noise about the annotator's mouse.
     */
    function setReward(points, t, value, snap) {
        const window = snap === undefined ? 0.05 : snap;
        const out = points.filter((p) => Math.abs(p.t - t) > window);
        out.push({ t, value });
        return out.sort((a, b) => a.t - b.t);
    }

    /**
     * Sample a reward curve at a time by linear interpolation.
     *
     * Returns null outside the drawn range rather than extrapolating: "the
     * annotator did not say" and "the annotator said zero" are different, and
     * a reward model trained on the second when the first was true learns that
     * unlabelled regions are bad.
     */
    function rewardAt(points, t) {
        if (!points.length) return null;
        if (t < points[0].t || t > points[points.length - 1].t) return null;
        for (let i = 1; i < points.length; i++) {
            if (t <= points[i].t) {
                const a = points[i - 1];
                const b = points[i];
                const span = b.t - a.t;
                if (span <= 0) return b.value;
                return a.value + (b.value - a.value) * ((t - a.t) / span);
            }
        }
        return points[points.length - 1].value;
    }

    /**
     * Which series lanes to draw, and in what order.
     *
     * A fourteen-joint arm with velocities is twenty-eight channels; drawing
     * them all makes each lane twelve pixels tall and none of them legible. So
     * an explicit list wins, and otherwise the first `maxLanes` are drawn and
     * the caller is told how many were left out — silently dropping half the
     * signals is how an annotator concludes the data does not contain
     * something it does.
     */
    function chooseLanes(series, shown, maxLanes) {
        const cap = maxLanes || 8;
        if (Array.isArray(shown) && shown.length) {
            const wanted = new Set(shown);
            const picked = series.filter((s) => wanted.has(s.name));
            return { lanes: picked, hidden: series.length - picked.length };
        }
        return { lanes: series.slice(0, cap),
                 hidden: Math.max(0, series.length - cap) };
    }

    /** Human-readable seconds, stable width so a live readout does not jitter. */
    function formatTime(t) {
        if (!isFinite(t)) return '0.00 s';
        if (t < 60) return `${t.toFixed(2)} s`;
        const m = Math.floor(t / 60);
        return `${m}:${(t - m * 60).toFixed(2).padStart(5, '0')}`;
    }

    /** Total seconds covered by phase segments — the coverage readout. */
    function coverage(segments) {
        return segments.reduce((n, s) => n + Math.max(0, s.end - s.start), 0);
    }

    // -----------------------------------------------------------------
    // The manager
    // -----------------------------------------------------------------

    class EpisodeAnnotationManager {
        constructor(schemaName, config) {
            this.schema = schemaName;
            this.config = config || {};
            this.container = null;
            this.canvas = null;
            this.episode = null;

            // Annotation state. Every field is listed in clearAnnotations for
            // the reason the point cloud manager lists its own: nothing here
            // is owned by a scene graph, so a generic clear reaches none of it.
            this.phases = [];
            this.reward = [];
            this.outcome = { result: '', cause: '' };
            this.instructions = [];

            this.currentTool = 'select';
            this.currentPhase = null;
            this.selectedPhase = -1;
            this._drag = null;
            this._videos = [];
            this._raf = null;
            this._lanes = [];
            this._hiddenLaneCount = 0;
        }

        init() {
            this.container = document.querySelector(
                `.episode-annotation-container[data-schema="${cssEscape(this.schema)}"]`);
            if (!this.container) return;

            this.canvas = document.createElement('canvas');
            this.canvas.className = 'episode-canvas';
            this.canvas.setAttribute('role', 'application');
            this.canvas.setAttribute('tabindex', '0');
            this.canvas.setAttribute(
                'aria-label',
                'Episode timeline. Drag on the phase lane to mark a phase; '
                + 'the tool buttons above choose what a drag does.');
            const holder = this.container.querySelector('.episode-timeline');
            if (holder) holder.appendChild(this.canvas);

            this._bindToolbar();
            this._bindCanvas();
            this._bindOutcome();
            this._bindInstruction();
            this._restoreFromInput();
            this._loadEpisode();

            if (typeof ResizeObserver !== 'undefined' && holder) {
                this._resizeObserver = new ResizeObserver(() => this.draw());
                this._resizeObserver.observe(holder);
            }
        }

        destroy() {
            if (this._resizeObserver) {
                this._resizeObserver.disconnect();
                this._resizeObserver = null;
            }
            if (this._raf) {
                cancelAnimationFrame(this._raf);
                this._raf = null;
            }
        }

        // -------------------------------------------------------------
        // Loading
        // -------------------------------------------------------------

        /**
         * Where this item's episode lives, or null.
         *
         * Asks the server for the item rather than reading the page, because
         * an episode path is almost never on the page: it is a data field, not
         * a display field, and `text_key` usually points at a human-readable
         * note. Scraping the instance text got the note instead and produced a
         * 403 from the traversal guard — a confusing symptom for a
         * configuration that was entirely correct.
         *
         * A display field explicitly wired to this schema still wins, for the
         * case where the episode path IS what is being shown.
         */
        async _episodePath() {
            const field = this.config.sourceField || 'episode';

            const display = document.querySelector(
                `[data-field-key="${cssEscape(field)}"]`);
            if (display) {
                const value = display.getAttribute('data-source-url')
                    || (display.textContent || '').trim();
                if (value) return value;
            }

            try {
                const response = await fetch('/api/current_instance',
                                             { credentials: 'same-origin' });
                if (!response.ok) return null;
                const payload = await response.json();
                const value = (payload.data || {})[field];
                if (value) return String(value);
            } catch (_err) {
                return null;
            }
            return null;
        }

        async _loadEpisode() {
            const path = await this._episodePath();
            if (!path) {
                this._status(
                    `No episode for this item: it has no "`
                    + `${this.config.sourceField}" field. Set source_field on `
                    + `the schema to whichever field holds the episode path.`,
                    'error');
                return;
            }

            this._status('Loading episode…');
            let payload;
            try {
                const response = await fetch(
                    `/api/episode/${path}`, { credentials: 'same-origin' });
                if (!response.ok) {
                    let detail = `HTTP ${response.status}`;
                    try {
                        detail = (await response.json()).error || detail;
                    } catch (_e) { /* not JSON; keep the status */ }
                    this._status(detail, 'error');
                    return;
                }
                payload = await response.json();
            } catch (err) {
                this._status(`Could not load the episode: ${err.message}`,
                             'error');
                return;
            }

            this.episode = payload;
            const chosen = chooseLanes(payload.series || [],
                                       this.config.seriesShown,
                                       this.config.maxLanes);
            this._lanes = chosen.lanes;
            this._hiddenLaneCount = chosen.hidden;

            this._buildStreams(payload.streams || []);
            this._showInstruction(payload.instruction || '');
            this._describe(payload);
            this.draw();
        }

        _buildStreams(streams) {
            const holder = this.container.querySelector('.episode-streams');
            if (!holder) return;
            holder.innerHTML = '';
            this._videos = [];

            streams.forEach((stream) => {
                const figure = document.createElement('figure');
                figure.className = 'episode-stream';

                const video = document.createElement('video');
                video.className = 'episode-video';
                video.src = stream.url;
                video.preload = 'metadata';
                video.muted = true;
                video.playsInline = true;
                // No native controls: several streams share one transport, and
                // per-video scrub bars would let them drift out of sync — at
                // which point the wrist and overhead views disagree about what
                // frame you are looking at.
                video.controls = false;

                const caption = document.createElement('figcaption');
                caption.textContent = stream.kind
                    ? `${stream.name} (${stream.kind})` : stream.name;

                video.addEventListener('error', () => {
                    figure.classList.add('episode-stream-broken');
                    caption.textContent = `${stream.name} — video not found`;
                });

                figure.appendChild(video);
                figure.appendChild(caption);
                holder.appendChild(figure);
                this._videos.push(video);
            });
        }

        _showInstruction(text) {
            const el = this.container.querySelector('.episode-instruction');
            if (!el) return;
            el.textContent = text ? `Instruction: ${text}` : '';
            el.hidden = !text;
        }

        _describe(payload) {
            const bits = [];
            bits.push(`${payload.num_frames} frames at ${payload.fps} fps `
                      + `(${formatTime(payload.duration)}).`);
            if (this._hiddenLaneCount > 0) {
                // Silently dropping channels is how an annotator concludes the
                // data does not contain something it does. But the advice
                // differs: an explicit `series_shown` means the project chose,
                // and telling them to "set series_shown" when they already did
                // reads as the setting having been ignored.
                const chosen = Array.isArray(this.config.seriesShown)
                    && this.config.seriesShown.length;
                bits.push(chosen
                    ? `${this._hiddenLaneCount} other series in this episode `
                      + `are not shown, by configuration.`
                    : `${this._hiddenLaneCount} more series not shown — set `
                      + `series_shown or raise max_lanes to see them.`);
            }
            (payload.warnings || []).forEach((w) => bits.push(w));
            this._status(bits.join(' '),
                         (payload.warnings || []).length ? 'warn' : '');
        }

        // -------------------------------------------------------------
        // Playback
        // -------------------------------------------------------------

        get duration() {
            return (this.episode && this.episode.duration) || 0;
        }

        get currentTime() {
            return this._videos.length ? this._videos[0].currentTime
                : (this._virtualTime || 0);
        }

        seek(t) {
            const clamped = Math.max(0, Math.min(this.duration, t));
            this._virtualTime = clamped;
            // Every stream, not just the first: they are different cameras on
            // the same instant, and one left behind is worse than none.
            this._videos.forEach((v) => {
                if (isFinite(v.duration)) v.currentTime = clamped;
            });
            this._updateReadout();
            this.draw();
        }

        play() {
            this._videos.forEach((v) => {
                const promise = v.play();
                if (promise && promise.catch) promise.catch(() => {});
            });
            this._playing = true;
            this._tick();
        }

        pause() {
            this._videos.forEach((v) => v.pause());
            this._playing = false;
            if (this._raf) {
                cancelAnimationFrame(this._raf);
                this._raf = null;
            }
        }

        togglePlay() {
            if (this._playing) this.pause(); else this.play();
            const btn = this.container.querySelector('.episode-play');
            if (btn) {
                btn.setAttribute('aria-pressed', String(!!this._playing));
                btn.innerHTML = this._playing
                    ? '<span aria-hidden="true">❚❚</span> Pause'
                    : '<span aria-hidden="true">▶</span> Play';
            }
        }

        _tick() {
            if (!this._playing) return;
            this._updateReadout();
            this.draw();
            this._raf = requestAnimationFrame(() => this._tick());
        }

        _updateReadout() {
            const t = this.currentTime;
            const time = this.container.querySelector('.episode-time');
            if (time) time.textContent = formatTime(t);
            const frame = this.container.querySelector('.episode-frame');
            if (frame && this.episode) {
                // Frames, exactly: a phase boundary is ultimately a frame
                // index, and an annotator checking against the source data
                // needs the number the dataset uses.
                frame.textContent =
                    `frame ${Math.round(t * (this.episode.fps || 0))}`;
            }
        }

        // -------------------------------------------------------------
        // Drawing
        // -------------------------------------------------------------

        _laneLayout() {
            const lanes = [];
            if ((this.config.layers || []).indexOf('phases') !== -1) {
                lanes.push({ kind: 'phases', height: PHASE_LANE_HEIGHT,
                             label: 'Phase' });
            }
            if ((this.config.layers || []).indexOf('reward') !== -1) {
                lanes.push({ kind: 'reward', height: REWARD_LANE_HEIGHT,
                             label: 'Reward' });
            }
            this._lanes.forEach((series) => {
                lanes.push({ kind: 'series', height: LANE_HEIGHT,
                             label: series.name, series });
            });
            let y = 0;
            lanes.forEach((lane) => { lane.y = y; y += lane.height; });
            return { lanes, height: y };
        }

        draw() {
            if (!this.canvas) return;
            const holder = this.canvas.parentElement;
            const width = Math.max(1, (holder ? holder.clientWidth : 0)
                                   || this.canvas.clientWidth || 600);
            const layout = this._laneLayout();

            const dpr = window.devicePixelRatio || 1;
            this.canvas.style.width = '100%';
            this.canvas.style.height = `${layout.height}px`;
            this.canvas.width = Math.round(width * dpr);
            this.canvas.height = Math.round(layout.height * dpr);

            const ctx = this.canvas.getContext('2d');
            if (!ctx) return;
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
            ctx.clearRect(0, 0, width, layout.height);

            layout.lanes.forEach((lane) => {
                this._drawLaneBackground(ctx, lane, width);
                if (lane.kind === 'phases') this._drawPhases(ctx, lane, width);
                else if (lane.kind === 'reward') this._drawReward(ctx, lane, width);
                else this._drawSeries(ctx, lane, width);
            });

            this._drawPlayhead(ctx, width, layout.height);
        }

        _drawLaneBackground(ctx, lane, width) {
            ctx.fillStyle = '#f6f7f9';
            ctx.fillRect(0, lane.y, width, lane.height);
            ctx.strokeStyle = '#dfe3ea';
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(0, lane.y + 0.5);
            ctx.lineTo(width, lane.y + 0.5);
            ctx.stroke();

            ctx.fillStyle = '#6b7280';
            ctx.font = '11px system-ui, sans-serif';
            ctx.textBaseline = 'top';
            ctx.fillText(lane.label, 4, lane.y + 3);
        }

        _drawPhases(ctx, lane, width) {
            const duration = this.duration;
            this.phases.forEach((seg, index) => {
                const x0 = timeToX(seg.start, duration, width);
                const x1 = timeToX(seg.end, duration, width);
                const colour = this._phaseColour(seg.label);
                ctx.fillStyle = colour;
                ctx.globalAlpha = index === this.selectedPhase ? 0.95 : 0.7;
                ctx.fillRect(x0, lane.y + 16, Math.max(1, x1 - x0),
                             lane.height - 20);
                ctx.globalAlpha = 1;

                if (x1 - x0 > 34) {
                    ctx.fillStyle = '#1f2430';
                    ctx.font = '11px system-ui, sans-serif';
                    ctx.fillText(seg.label, x0 + 3, lane.y + 20);
                }
            });
        }

        _drawReward(ctx, lane, width) {
            const [lo, hi] = this.config.rewardRange || [0, 1];
            const span = (hi - lo) || 1;
            const top = lane.y + 16;
            const height = lane.height - 20;

            ctx.strokeStyle = '#c9cdd6';
            ctx.setLineDash([2, 3]);
            ctx.beginPath();
            ctx.moveTo(0, top + height / 2);
            ctx.lineTo(width, top + height / 2);
            ctx.stroke();
            ctx.setLineDash([]);

            if (this.reward.length < 2) {
                if (this.reward.length === 1) {
                    const p = this.reward[0];
                    ctx.fillStyle = '#2f6fd0';
                    ctx.beginPath();
                    ctx.arc(timeToX(p.t, this.duration, width),
                            top + height * (1 - (p.value - lo) / span),
                            3, 0, Math.PI * 2);
                    ctx.fill();
                }
                return;
            }

            ctx.strokeStyle = '#2f6fd0';
            ctx.lineWidth = 2;
            ctx.beginPath();
            this.reward.forEach((p, i) => {
                const x = timeToX(p.t, this.duration, width);
                const y = top + height * (1 - (p.value - lo) / span);
                if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
            });
            ctx.stroke();
            ctx.lineWidth = 1;
        }

        _drawSeries(ctx, lane, width) {
            const series = lane.series;
            const values = series.values || [];
            if (values.length < 2) return;
            const lo = series.min;
            const span = (series.max - series.min) || 1;
            const top = lane.y + 14;
            const height = lane.height - 18;

            ctx.strokeStyle = '#7a8698';
            ctx.beginPath();
            let started = false;
            for (let i = 0; i < values.length; i++) {
                const v = values[i];
                if (!isFinite(v)) {
                    // A gap, not a line to zero: a dropped sample is not a
                    // measurement, and joining across it invents a transition.
                    started = false;
                    continue;
                }
                const x = (i / (values.length - 1)) * width;
                const y = top + height * (1 - (v - lo) / span);
                if (!started) { ctx.moveTo(x, y); started = true; }
                else ctx.lineTo(x, y);
            }
            ctx.stroke();
        }

        _drawPlayhead(ctx, width, height) {
            const x = timeToX(this.currentTime, this.duration, width);
            ctx.strokeStyle = '#d33';
            ctx.lineWidth = 1.5;
            ctx.beginPath();
            ctx.moveTo(x, 0);
            ctx.lineTo(x, height);
            ctx.stroke();
            ctx.lineWidth = 1;
        }

        _phaseColour(name) {
            const found = (this.config.phases || []).find(
                (p) => p.name === name);
            return (found && found.color) || '#9aa5b1';
        }

        // -------------------------------------------------------------
        // Interaction
        // -------------------------------------------------------------

        _timeAt(event) {
            const rect = this.canvas.getBoundingClientRect();
            return xToTime(event.clientX - rect.left, this.duration,
                           rect.width);
        }

        _laneAt(event) {
            const rect = this.canvas.getBoundingClientRect();
            const y = event.clientY - rect.top;
            const layout = this._laneLayout();
            return layout.lanes.find(
                (lane) => y >= lane.y && y < lane.y + lane.height) || null;
        }

        _bindCanvas() {
            this.canvas.addEventListener('mousedown', (e) => {
                const lane = this._laneAt(e);
                const t = this._timeAt(e);
                if (!lane) return;

                if (lane.kind === 'phases' && this.currentTool === 'phase'
                        && this.currentPhase) {
                    e.preventDefault();
                    this._drag = { kind: 'new-phase', start: t };
                    return;
                }
                if (lane.kind === 'phases') {
                    const tol = (EDGE_TOLERANCE / (this.canvas.clientWidth || 1))
                        * this.duration;
                    const hit = segmentAt(this.phases, t, tol);
                    this.selectedPhase = hit ? hit.index : -1;
                    if (hit && hit.edge) {
                        e.preventDefault();
                        this._drag = { kind: 'resize', index: hit.index,
                                       edge: hit.edge };
                    }
                    this.draw();
                    return;
                }
                if (lane.kind === 'reward' && this.currentTool === 'reward') {
                    e.preventDefault();
                    this._drag = { kind: 'reward', lane };
                    this._paintReward(e, lane);
                    return;
                }
                // Anywhere else: scrub. A timeline you cannot click to seek is
                // the first thing every annotator tries.
                this.seek(t);
            });

            this.canvas.addEventListener('mousemove', (e) => {
                if (!this._drag) {
                    this._updateCursor(e);
                    return;
                }
                const t = this._timeAt(e);
                if (this._drag.kind === 'resize') {
                    this.phases = resizeSegment(
                        this.phases, this._drag.index, this._drag.edge, t);
                    this.draw();
                } else if (this._drag.kind === 'reward') {
                    this._paintReward(e, this._drag.lane);
                } else if (this._drag.kind === 'new-phase') {
                    this._drag.end = t;
                    this.draw();
                    this._drawPending();
                }
            });

            const finish = (e) => {
                if (!this._drag) return;
                const drag = this._drag;
                this._drag = null;
                if (drag.kind === 'new-phase') {
                    const t = this._timeAt(e);
                    const start = Math.min(drag.start, t);
                    const end = Math.max(drag.start, t);
                    if (end - start >= MIN_SEGMENT) {
                        this.phases = insertSegment(
                            this.phases,
                            { start, end, label: this.currentPhase });
                        this.selectedPhase = this.phases.findIndex(
                            (s) => s.start === start && s.end === end);
                    }
                }
                this._save();
                this.draw();
            };
            this.canvas.addEventListener('mouseup', finish);
            this.canvas.addEventListener('mouseleave', finish);

            this.canvas.addEventListener('keydown', (e) => {
                if (e.key === 'Delete' || e.key === 'Backspace') {
                    if (this.selectedPhase >= 0) {
                        e.preventDefault();
                        this.phases.splice(this.selectedPhase, 1);
                        this.selectedPhase = -1;
                        this._save();
                        this.draw();
                    }
                } else if (e.key === ' ') {
                    e.preventDefault();
                    this.togglePlay();
                } else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
                    e.preventDefault();
                    // One frame, not one second: the unit the data is in.
                    const step = 1 / ((this.episode && this.episode.fps) || 30);
                    this.seek(this.currentTime
                              + (e.key === 'ArrowRight' ? step : -step));
                }
            });
        }

        _updateCursor(e) {
            const lane = this._laneAt(e);
            if (!lane) { this.canvas.style.cursor = 'default'; return; }
            if (lane.kind === 'phases') {
                if (this.currentTool === 'phase' && this.currentPhase) {
                    this.canvas.style.cursor = 'crosshair';
                    return;
                }
                const tol = (EDGE_TOLERANCE / (this.canvas.clientWidth || 1))
                    * this.duration;
                const hit = segmentAt(this.phases, this._timeAt(e), tol);
                this.canvas.style.cursor =
                    hit && hit.edge ? 'ew-resize' : 'pointer';
                return;
            }
            this.canvas.style.cursor =
                lane.kind === 'reward' && this.currentTool === 'reward'
                    ? 'crosshair' : 'pointer';
        }

        _paintReward(event, lane) {
            const rect = this.canvas.getBoundingClientRect();
            const [lo, hi] = this.config.rewardRange || [0, 1];
            const top = lane.y + 16;
            const height = lane.height - 20;
            const y = event.clientY - rect.top;
            const fraction = 1 - (y - top) / height;
            const value = lo + Math.max(0, Math.min(1, fraction)) * (hi - lo);
            this.reward = setReward(this.reward, this._timeAt(event), value);
            this.draw();
        }

        _drawPending() {
            if (!this._drag || this._drag.kind !== 'new-phase') return;
            const ctx = this.canvas.getContext('2d');
            const width = this.canvas.clientWidth || 1;
            const layout = this._laneLayout();
            const lane = layout.lanes.find((l) => l.kind === 'phases');
            if (!lane || !ctx) return;
            const a = timeToX(Math.min(this._drag.start, this._drag.end || 0),
                              this.duration, width);
            const b = timeToX(Math.max(this._drag.start, this._drag.end || 0),
                              this.duration, width);
            ctx.save();
            ctx.globalAlpha = 0.4;
            ctx.fillStyle = this._phaseColour(this.currentPhase);
            ctx.fillRect(a, lane.y + 16, Math.max(1, b - a), lane.height - 20);
            ctx.restore();
        }

        // -------------------------------------------------------------
        // Toolbar, outcome, persistence
        // -------------------------------------------------------------

        _bindToolbar() {
            this.container.querySelectorAll('[data-tool]').forEach((btn) => {
                btn.addEventListener('click', () => this.setTool(btn.dataset.tool));
            });
            const play = this.container.querySelector('.episode-play');
            if (play) play.addEventListener('click', () => this.togglePlay());

            // Phase buttons live in the toolbar area, built here rather than
            // server-side so they can carry the same colour the canvas uses.
            const bar = this.container.querySelector('.episode-transport');
            if (bar && (this.config.layers || []).indexOf('phases') !== -1) {
                const group = document.createElement('span');
                group.className = 'episode-phase-buttons';
                (this.config.phases || []).forEach((phase) => {
                    const btn = document.createElement('button');
                    btn.type = 'button';
                    btn.className = 'label-btn';
                    btn.dataset.label = phase.name;
                    btn.dataset.color = phase.color;
                    btn.setAttribute('aria-pressed', 'false');
                    btn.style.setProperty('--label-color', phase.color);
                    btn.innerHTML =
                        `<span class="label-color-dot" aria-hidden="true" `
                        + `style="background-color:${phase.color}"></span>`
                        + escapeText(phase.name);
                    btn.addEventListener('click', () => this.setPhase(phase.name));
                    group.appendChild(btn);
                });
                bar.appendChild(group);
            }
        }

        setTool(tool) {
            this.currentTool = tool;
            this.container.querySelectorAll('[data-tool]').forEach((btn) => {
                const on = btn.dataset.tool === tool;
                btn.classList.toggle('active', on);
                // aria-pressed on the same path as the class: driving the
                // toolbar from the keyboard while every button reports
                // "not pressed" is WCAG 4.1.2, and it is the defect the image
                // toolbar shipped with.
                btn.setAttribute('aria-pressed', String(on));
            });
        }

        setPhase(name) {
            this.currentPhase = name;
            this.container.querySelectorAll('.label-btn').forEach((btn) => {
                const on = btn.dataset.label === name;
                btn.classList.toggle('active', on);
                btn.setAttribute('aria-pressed', String(on));
            });
            // Picking a phase means you intend to draw one.
            if (this.currentTool !== 'phase') this.setTool('phase');
        }

        _bindOutcome() {
            const radios = this.container.querySelectorAll(
                '.episode-outcome input[type="radio"]');
            const cause = this.container.querySelector('.episode-cause');
            radios.forEach((radio) => {
                radio.addEventListener('change', () => {
                    this.outcome.result = radio.value;
                    if (cause) {
                        // Enabled only for a non-success outcome, and cleared
                        // when it goes back: a stored cause on a success is a
                        // contradiction that no consumer knows how to read.
                        const needsCause = radio.value !== 'success';
                        cause.disabled = !needsCause;
                        if (!needsCause) {
                            cause.value = '';
                            this.outcome.cause = '';
                        }
                    }
                    this._save();
                });
            });
            if (cause) {
                cause.addEventListener('change', () => {
                    this.outcome.cause = cause.value;
                    this._save();
                });
            }
        }

        _bindInstruction() {
            const box = this.container.querySelector('.episode-relabel');
            const align = this.container.querySelector(
                '.episode-relabel-align');
            if (!box) return;

            box.addEventListener('input', () => {
                this._setInstruction({ text: box.value });
            });

            if (align) {
                align.addEventListener('click', () => {
                    const phase = this.phases[this.selectedPhase];
                    if (!phase) {
                        // Silently doing nothing would read as a broken
                        // button; the annotator has to be told what is missing.
                        this._setRelabelSpan(null);
                        this._status(
                            'Select a phase first, then align the relabel to '
                            + 'it.', 'warn');
                        return;
                    }
                    this._setInstruction({
                        start: phase.start, end: phase.end });
                    this._setRelabelSpan(phase);
                });
            }
        }

        /** Merge fields into the single hindsight relabel, creating it once. */
        _setInstruction(fields) {
            const current = this.instructions[0] || {
                text: '', start: null, end: null };
            const next = Object.assign({}, current, fields);
            // An empty relabel with no range is not an annotation. Storing one
            // would make every untouched episode look answered.
            if (!next.text && next.start === null) {
                this.instructions = [];
            } else {
                this.instructions = [next];
            }
            this._save();
        }

        _setRelabelSpan(phase) {
            const label = this.container.querySelector('.episode-relabel-span');
            if (!label) return;
            label.textContent = phase
                ? `${formatTime(phase.start)} – ${formatTime(phase.end)}`
                : 'whole episode';
        }

        _applyInstructionToInputs() {
            const box = this.container.querySelector('.episode-relabel');
            const entry = this.instructions[0];
            if (box) box.value = (entry && entry.text) || '';
            this._setRelabelSpan(
                entry && entry.start !== null && entry.start !== undefined
                    ? entry : null);
        }

        // -------------------------------------------------------------
        // The four functions annotation.js drives
        // -------------------------------------------------------------

        serialize() {
            return JSON.stringify({
                phases: this.phases,
                reward: this.reward,
                outcome: this.outcome,
                instructions: this.instructions,
            });
        }

        clearAnnotations() {
            // Everything, named explicitly. Nothing here is owned by a canvas
            // or a scene graph, so a generic clear reaches none of it — and
            // three separate cross-instance corruption bugs in the image
            // manager came from exactly that gap.
            this.phases = [];
            this.reward = [];
            this.outcome = { result: '', cause: '' };
            this.instructions = [];
            this.selectedPhase = -1;
            this.currentPhase = null;
            this._drag = null;
            this._resetOutcomeInputs();
            this._applyInstructionToInputs();
            this._save();
            this.draw();
        }

        getAnnotationCount() {
            return this.phases.length
                + (this.reward.length ? 1 : 0)
                + (this.outcome.result ? 1 : 0);
        }

        _resetOutcomeInputs() {
            this.container.querySelectorAll(
                '.episode-outcome input[type="radio"]').forEach((r) => {
                r.checked = false;
            });
            const cause = this.container.querySelector('.episode-cause');
            if (cause) { cause.value = ''; cause.disabled = true; }
        }

        _restoreFromInput() {
            const input = document.getElementById(`input-${this.schema}`);
            if (!input || !input.value) return;
            let data;
            try {
                data = JSON.parse(input.value);
            } catch (_e) {
                return;
            }
            this.phases = Array.isArray(data.phases) ? data.phases : [];
            this.reward = Array.isArray(data.reward) ? data.reward : [];
            this.outcome = data.outcome || { result: '', cause: '' };
            this.instructions = Array.isArray(data.instructions)
                ? data.instructions : [];
            this._applyOutcomeToInputs();
            this._applyInstructionToInputs();
        }

        _applyOutcomeToInputs() {
            const cause = this.container.querySelector('.episode-cause');
            this.container.querySelectorAll(
                '.episode-outcome input[type="radio"]').forEach((r) => {
                r.checked = r.value === this.outcome.result;
            });
            if (cause) {
                cause.disabled = !this.outcome.result
                    || this.outcome.result === 'success';
                cause.value = this.outcome.cause || '';
            }
        }

        _save() {
            const input = document.getElementById(`input-${this.schema}`);
            if (!input) return;
            input.value = this.serialize();
            // data-modified is what annotation.js's save path keys on; without
            // it the value sits in the DOM and never reaches the server.
            input.setAttribute('data-modified', 'true');
            input.dispatchEvent(new Event('change', { bubbles: true }));
        }

        _status(message, kind) {
            const el = this.container
                && this.container.querySelector('.episode-status');
            if (!el) return;
            el.textContent = message;
            if (kind) el.setAttribute('data-kind', kind);
            else el.removeAttribute('data-kind');
        }
    }

    function escapeText(text) {
        const div = document.createElement('div');
        div.textContent = String(text);
        return div.innerHTML;
    }

    function cssEscape(value) {
        if (typeof CSS !== 'undefined' && CSS.escape) return CSS.escape(value);
        return String(value).replace(/["\\]/g, '\\$&');
    }

    EpisodeAnnotationManager.timeToX = timeToX;
    EpisodeAnnotationManager.xToTime = xToTime;
    EpisodeAnnotationManager.insertSegment = insertSegment;
    EpisodeAnnotationManager.segmentAt = segmentAt;
    EpisodeAnnotationManager.resizeSegment = resizeSegment;
    EpisodeAnnotationManager.setReward = setReward;
    EpisodeAnnotationManager.rewardAt = rewardAt;
    EpisodeAnnotationManager.chooseLanes = chooseLanes;
    EpisodeAnnotationManager.formatTime = formatTime;
    EpisodeAnnotationManager.coverage = coverage;
    EpisodeAnnotationManager.MIN_SEGMENT = MIN_SEGMENT;

    if (typeof module !== 'undefined' && module.exports) {
        module.exports = EpisodeAnnotationManager;
    }
    if (root) root.EpisodeAnnotationManager = EpisodeAnnotationManager;
})(typeof window !== 'undefined' ? window
    : (typeof globalThis !== 'undefined' ? globalThis : null));

/**
 * World-model rollout evaluation: frame-locked panels, one timeline.
 *
 * ## One clock, N videos
 *
 * The panels only mean anything if they are on the same frame. Every video
 * here is seeked from a single time, has no controls of its own, and is never
 * played independently — a per-panel scrub bar would let two rollouts drift,
 * and at that point the annotator is comparing frame 40 of one against frame 43
 * of another and cannot know it.
 *
 * ## Why marks snap to the middle of a frame
 *
 * `video.currentTime = frame / fps` is a boundary, and which frame a browser
 * shows at a boundary is not specified — floating point alone decides it, so
 * the same expression lands on frame N in one panel and N-1 in another. Seeking
 * to `(frame + 0.5) / fps` is unambiguous, and it makes `floor(t * fps)` an
 * exact inverse, so a mark round-trips through storage without moving.
 *
 * Marks are stored at that mid-frame time for the same reason. The annotator is
 * looking at a *frame*; recording 3.4187 s implies a precision video does not
 * have, and it would make two annotators who agreed on the frame disagree in
 * the statistics. When no frame rate is declared there is nothing to snap to,
 * so the raw time is stored and frame numbers are omitted rather than invented.
 *
 * The pure arithmetic is exported as statics so Jest can drive it without a
 * DOM; the rest needs a real browser and is covered by Playwright.
 */
(function (root) {
    'use strict';

    /** Height of one stream lane on the timeline, in CSS pixels. */
    const LANE_HEIGHT = 30;
    /** Pointer slop for grabbing a mark, in pixels. */
    const MARK_TOLERANCE = 6;
    /**
     * Two marks on the same stream closer than this are the same mark.
     * A quarter-second: below that the annotator is double-tapping, not
     * identifying two separate failures.
     */
    const MARK_MERGE_WINDOW = 0.25;
    /**
     * How long to wait for a video to report its length before saying it has
     * not. Six seconds: long enough that a normal load on a slow link is not
     * accused of failing, short enough that nobody sits in front of a dead
     * timeline wondering.
     */
    const METADATA_TIMEOUT_MS = 6000;

    // -----------------------------------------------------------------
    // Pure arithmetic
    // -----------------------------------------------------------------

    /** Seconds -> pixels across a width. */
    function timeToX(t, duration, width) {
        if (!(duration > 0)) return 0;
        return (t / duration) * width;
    }

    /** Pixels -> seconds, clamped into the rollout. */
    function xToTime(x, duration, width) {
        if (!(width > 0) || !(duration > 0)) return 0;
        return Math.max(0, Math.min(duration, (x / width) * duration));
    }

    /** Which frame a time falls in. Exact inverse of timeOfFrame. */
    function frameAt(t, fps) {
        if (!(fps > 0)) return null;
        return Math.max(0, Math.floor(t * fps));
    }

    /** The middle of a frame — the unambiguous place to seek to. */
    function timeOfFrame(frame, fps) {
        if (!(fps > 0)) return 0;
        return (Math.max(0, frame) + 0.5) / fps;
    }

    /**
     * Snap a time to the middle of the frame it falls in.
     *
     * Returns the time unchanged when no frame rate is known: snapping to a
     * guessed grid would move every mark by an unknown amount, which is worse
     * than not snapping.
     */
    function snapToFrame(t, fps) {
        if (!(fps > 0)) return t;
        return timeOfFrame(frameAt(t, fps), fps);
    }

    /**
     * Add a mark, replacing any mark on the same stream within the merge
     * window.
     *
     * Replacing rather than refusing: the second press is the annotator's
     * considered answer, and a refusal that looks like nothing happening is
     * how they conclude the key is broken.
     */
    function insertViolation(violations, incoming, window) {
        const merge = window === undefined ? MARK_MERGE_WINDOW : window;
        const out = violations.filter(
            (v) => v.stream !== incoming.stream
                || Math.abs(v.t - incoming.t) > merge);
        out.push(incoming);
        return out.sort((a, b) => a.t - b.t
            || String(a.stream).localeCompare(String(b.stream)));
    }

    /**
     * Index of the mark nearest a time on a stream, within a tolerance.
     *
     * `null` rather than the nearest-at-any-distance: a click in empty space
     * on a lane means "no mark here", and returning the closest one instead
     * selects something the annotator was not pointing at.
     */
    function violationAt(violations, streamId, t, tolerance) {
        let best = null;
        let bestDelta = Infinity;
        violations.forEach((v, index) => {
            if (v.stream !== streamId) return;
            const delta = Math.abs(v.t - t);
            if (delta <= tolerance && delta < bestDelta) {
                best = index;
                bestDelta = delta;
            }
        });
        return best;
    }

    /**
     * Streams that have neither a mark nor a clean flag.
     *
     * The whole reason `clean` exists. Without it a stream with no marks is
     * ambiguous between "watched it, nothing wrong" and "never got to it", and
     * detection agreement cannot be computed across that ambiguity — one
     * reading says the annotators agree there is no break, the other says one
     * of them did not answer.
     */
    function unresolvedStreams(streamIds, violations, clean) {
        const marked = new Set(violations.map((v) => v.stream));
        const cleared = new Set(clean);
        return streamIds.filter((id) => !marked.has(id) && !cleared.has(id));
    }

    /** Human-readable seconds, stable width so a live readout does not jitter. */
    function formatTime(t) {
        if (!isFinite(t)) return '0.00 s';
        if (t < 60) return `${t.toFixed(2)} s`;
        const m = Math.floor(t / 60);
        return `${m}:${(t - m * 60).toFixed(2).padStart(5, '0')}`;
    }

    /**
     * A one-line description of a mark, for the live region.
     *
     * Screen-reader users get no information at all from a tick appearing on a
     * canvas, so this is the entire feedback for the primary action.
     */
    function describeViolation(violation, streamName, fps) {
        const frame = frameAt(violation.t, fps);
        const where = frame === null
            ? formatTime(violation.t)
            : `frame ${frame}, ${formatTime(violation.t)}`;
        const type = String(violation.type || 'unclassified').replace(/_/g, ' ');
        return `${streamName}: ${type} at ${where}.`;
    }

    // -----------------------------------------------------------------
    // The manager
    // -----------------------------------------------------------------

    class RolloutEvaluationManager {
        constructor(schemaName, config) {
            this.schema = schemaName;
            this.config = config || {};
            this.container = null;
            this.canvas = null;
            this.set = null;

            // Annotation state. Every field is listed in clearAnnotations for
            // the reason the episode and point-cloud managers list theirs:
            // nothing here is owned by a scene graph, so a generic clear
            // reaches none of it.
            this.violations = [];
            this.clean = [];
            this.preference = { winner: '', confidence: '', rubric: {} };
            this.counterfactual = { verdict: '', t: null, note: '' };

            this.selectedStream = null;
            this.selectedViolation = -1;
            this._videos = [];
            this._raf = null;
            this._playing = false;
            this._virtualTime = 0;
        }

        // -------------------------------------------------------------
        // Lifecycle
        // -------------------------------------------------------------

        init() {
            this.container = document.querySelector(
                `.rollout-eval-container[data-schema="${cssEscape(this.schema)}"]`);
            if (!this.container) return;

            this.canvas = document.createElement('canvas');
            this.canvas.className = 'rollout-canvas';
            // role="img" with a live-updated description, NOT role="application"
            // with a tabindex. The slab canvases in the point-cloud viewer took
            // the opposite treatment because they own their own keys and had to
            // be focused for those keys to be scoped. Here every key is bound at
            // document level and every action has a button, so focusing the
            // canvas would achieve nothing — a tab stop that does nothing is
            // worse than no tab stop, and role="application" on it would promise
            // a keyboard interface the element does not have.
            //
            // What a screen-reader user genuinely lacks is any way to *survey*
            // the marks, which exist only as pixels. That is what the
            // description is for; _syncProgress rewrites it as they change.
            this.canvas.setAttribute('role', 'img');
            const holder = this.container.querySelector('.rollout-timeline');
            if (holder) holder.appendChild(this.canvas);

            this._bindTransport();
            this._bindCanvas();
            this._bindViolationForm();
            this._bindPreference();
            this._bindCounterfactual();
            this._bindKeys();
            this._bindNavigationGuard();
            this._restoreFromInput();
            this._load();

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
            if (this._metadataTimer) {
                clearTimeout(this._metadataTimer);
                this._metadataTimer = null;
            }
            if (this._navGuard) {
                document.removeEventListener('click', this._navGuard, true);
                this._navGuard = null;
            }
            if (this._keyHandler) {
                document.removeEventListener('keydown', this._keyHandler);
                this._keyHandler = null;
            }
        }

        // -------------------------------------------------------------
        // Loading
        // -------------------------------------------------------------

        async _load() {
            this._status('Loading rollouts…');
            let payload;
            try {
                const response = await fetch(
                    `/api/rollout/set?schema=${encodeURIComponent(this.schema)}`,
                    { credentials: 'same-origin' });
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
                this._status(`Could not load the rollouts: ${err.message}`,
                             'error');
                return;
            }

            this.set = payload;
            this._buildPanels(payload.streams || []);
            this._buildWinnerOptions(payload.streams || []);
            this._showScenario(payload);
            this._describe(payload);
            this._applyRestoredState();
            this._watchForMetadata();
            this._updateReadout();
            this.draw();
        }

        /**
         * Say something when the videos never load.
         *
         * Until at least one panel reports its length the timeline has no
         * duration, so it draws an empty strip, the playhead cannot move, and
         * every control is inert — an interface that looks finished and does
         * nothing. That state is reachable for ordinary reasons: a slow link, a
         * codec the browser will not decode, a backgrounded tab (Chrome defers
         * media loading entirely for hidden tabs, which is how this was found).
         *
         * The watchdog does not retry. A retry loop against a video the browser
         * has decided not to load is a busy wait that never terminates; the
         * useful thing is to name the state so the annotator asks the right
         * question instead of clicking a dead timeline.
         */
        _watchForMetadata() {
            if (this._metadataTimer) clearTimeout(this._metadataTimer);
            this._metadataTimer = setTimeout(() => {
                if (this.duration > 0) return;
                this.container.classList.add('rollout-no-media');
                this._status(
                    'The rollout videos have not reported their length, so the '
                    + 'timeline is inactive. They may still be downloading; if '
                    + 'this persists, the browser may not be able to decode '
                    + 'them — Chromium builds ship without an H.264 decoder, so '
                    + 'MP4 rollouts need converting to WebM/VP9.', 'warn');
            }, METADATA_TIMEOUT_MS);
        }

        get fps() {
            return (this.set && this.set.fps) || 0;
        }

        get duration() {
            return (this.set && this.set.duration) || 0;
        }

        get streamIds() {
            return ((this.set && this.set.streams) || [])
                .map((s) => s.stream_id);
        }

        _streamName(streamId) {
            const stream = ((this.set && this.set.streams) || [])
                .find((s) => s.stream_id === streamId);
            return stream ? stream.name : streamId;
        }

        _buildPanels(streams) {
            const holder = this.container.querySelector('.rollout-panels');
            if (!holder) return;
            holder.innerHTML = '';
            this._videos = [];

            streams.forEach((stream, index) => {
                const figure = document.createElement('figure');
                figure.className = 'rollout-panel';
                figure.dataset.stream = stream.stream_id;

                // A button, not a click handler on the figure: choosing a
                // panel is the gate on every marking action, so it has to be
                // reachable, focusable and announced. The number is the
                // shortcut, shown because an unlabelled shortcut is one nobody
                // uses.
                const choose = document.createElement('button');
                choose.type = 'button';
                choose.className = 'rollout-panel-choose';
                choose.setAttribute('aria-pressed', 'false');
                choose.innerHTML =
                    `<span class="rollout-panel-key" aria-hidden="true">`
                    + `${index + 1}</span> `
                    + `<span class="rollout-panel-name"></span>`;
                choose.querySelector('.rollout-panel-name').textContent =
                    stream.name;
                choose.title = `Choose this panel (${index + 1})`;
                // The badge is aria-hidden because sighted users read it as a
                // key cap, not as part of the name. But then the shortcut
                // reaches a screen-reader user nowhere at all -- title is not
                // reliably announced -- so it goes into the accessible name,
                // which is the one string every reader gets.
                choose.setAttribute(
                    'aria-label',
                    `Choose panel ${stream.name}, shortcut ${index + 1}`);
                choose.addEventListener(
                    'click', () => this.selectStream(stream.stream_id));

                const video = document.createElement('video');
                video.className = 'rollout-video';
                video.src = stream.url;
                video.preload = 'metadata';
                video.muted = true;
                video.playsInline = true;
                // No native controls: the panels share one transport, and a
                // per-panel scrub bar is how they drift out of frame lock.
                video.controls = false;
                video.setAttribute(
                    'aria-label',
                    `${stream.name}. Compared against the other panels; the `
                    + `controls below drive all of them together.`);

                video.addEventListener('loadedmetadata',
                                       () => this._onMetadata());
                video.addEventListener('error', () => {
                    figure.classList.add('rollout-panel-broken');
                    const caption = figure.querySelector('figcaption');
                    if (caption) {
                        caption.textContent = `${stream.name} — video not found`;
                    }
                });

                // Empty in the normal case: the choose button above already
                // carries the name, and a caption repeating it is a second
                // label for the same thing. This is the slot the load-failure
                // message lands in, which is the only time it has anything to
                // say the button does not.
                const caption = document.createElement('figcaption');
                caption.textContent = '';

                figure.appendChild(choose);
                figure.appendChild(video);
                figure.appendChild(caption);
                holder.appendChild(figure);
                this._videos.push({ el: video, streamId: stream.stream_id });
            });

            if (streams.length && !this.selectedStream) {
                this.selectStream(streams[0].stream_id);
            }
        }

        /**
         * Reconcile declared durations against what the videos actually are.
         *
         * The manifest may declare a duration and may be wrong; the browser
         * knows. Nothing server-side probes the files — that would be four
         * subprocesses per item — so this is where a length mismatch is
         * actually discovered, and it is worth saying: rollouts of different
         * lengths usually mean a generation terminated early, which is itself
         * the thing being annotated.
         */
        _onMetadata() {
            const durations = this._videos
                .map((v) => v.el.duration)
                .filter((d) => isFinite(d) && d > 0);
            if (!durations.length || !this.set) return;

            this.set.duration = Math.max.apply(null, durations);
            this.container.classList.remove('rollout-no-media');
            this._videos.forEach((entry) => {
                const stream = (this.set.streams || []).find(
                    (s) => s.stream_id === entry.streamId);
                if (stream && isFinite(entry.el.duration)) {
                    stream.duration = entry.el.duration;
                }
            });

            // Re-say the summary now that the durations are real. `_describe`
            // ran once with the server payload, whose `duration` is 0 because
            // nothing server-side probes the files -- so the sentence the
            // annotator reads said "3 rollouts, 0.00 s." for three six-second
            // clips and never changed, while the clock and the frame counter
            // beside it were right.
            this._describe(this.set);

            if (durations.length === this._videos.length) {
                const spread = Math.max.apply(null, durations)
                    - Math.min.apply(null, durations);
                const slack = this.fps > 0 ? 1 / this.fps : 0.05;
                if (spread > slack) {
                    this._status(
                        `Panels differ in length by ${spread.toFixed(2)} s. The `
                        + `timeline runs to the longest; a short rollout is `
                        + `often a generation that stopped early.`, 'warn');
                }
            }
            this._updateReadout();
            this.draw();
        }

        _buildWinnerOptions(streams) {
            const holder = this.container.querySelector('.rollout-winner');
            if (!holder) return;
            holder.innerHTML = '';
            streams.forEach((stream) => {
                const label = document.createElement('label');
                label.className = 'rollout-winner-option';
                const input = document.createElement('input');
                input.type = 'radio';
                input.name = `rollout-winner-${this.schema}`;
                input.value = stream.stream_id;
                input.addEventListener('change', () => {
                    this.preference.winner = stream.stream_id;
                    this._save();
                });
                label.appendChild(input);
                label.appendChild(document.createTextNode(` ${stream.name}`));
                holder.appendChild(label);
            });

            // A tie is a real answer and the commonest one for two rollouts
            // that both fail immediately. Without it annotators pick at random
            // and the preference statistic measures coin flips.
            const tie = document.createElement('label');
            tie.className = 'rollout-winner-option';
            const tieInput = document.createElement('input');
            tieInput.type = 'radio';
            tieInput.name = `rollout-winner-${this.schema}`;
            tieInput.value = '__tie__';
            tieInput.addEventListener('change', () => {
                this.preference.winner = '__tie__';
                this._save();
            });
            tie.appendChild(tieInput);
            tie.appendChild(document.createTextNode(' no difference'));
            holder.appendChild(tie);

            this._buildRubricScales();
        }

        _buildRubricScales() {
            const rubric = this.config.rubric || {};
            this.container.querySelectorAll('.rollout-rubric-scale')
                .forEach((holder) => {
                    const dimension = holder.dataset.dimension;
                    if (!(dimension in rubric)) return;
                    holder.innerHTML = '';
                    for (let score = 1; score <= 5; score += 1) {
                        const label = document.createElement('label');
                        label.className = 'rollout-rubric-point';
                        const input = document.createElement('input');
                        input.type = 'radio';
                        input.name = `rollout-rubric-${this.schema}-${dimension}`;
                        input.value = String(score);
                        input.addEventListener('change', () => {
                            this.preference.rubric[dimension] = score;
                            this._save();
                        });
                        const text = document.createElement('span');
                        text.textContent = String(score);
                        label.appendChild(input);
                        label.appendChild(text);
                        holder.appendChild(label);
                    }
                });
        }

        _showScenario(payload) {
            const prompt = this.container.querySelector('.rollout-prompt');
            if (prompt) {
                prompt.textContent = payload.prompt
                    ? `Scenario: ${payload.prompt}` : '';
                prompt.hidden = !payload.prompt;
            }
            const intervention =
                this.container.querySelector('.rollout-intervention');
            const hasIntervention = !!payload.intervention;
            if (intervention) {
                intervention.textContent = hasIntervention
                    ? `Intervention: ${payload.intervention}` : '';
                intervention.hidden = !hasIntervention;
            }
            // The counterfactual question is meaningless without something to
            // diverge from, so the block is hidden rather than shown empty —
            // an answer to a question that was not asked is worse than a gap.
            const block =
                this.container.querySelector('.rollout-counterfactual');
            if (block) block.hidden = !hasIntervention;
        }

        _describe(payload) {
            const bits = [];
            const n = (payload.streams || []).length;
            bits.push(`${n} rollout${n === 1 ? '' : 's'}, `
                      + `${formatTime(payload.duration || 0)}.`);
            if (!this.fps) {
                // Not a warning about a missing feature — a warning that every
                // frame number on screen would be a guess, so there are none.
                bits.push('No frame rate is declared for this item, so frames '
                          + 'are not shown; set fps on the schema to see them.');
            }
            const missing = (payload.metadata || {}).missing_streams || [];
            if (missing.length) {
                bits.push(`Not in this item: ${missing.join(', ')}.`);
            }
            (payload.warnings || []).forEach((w) => bits.push(w));
            const bad = (payload.warnings || []).length || missing.length;
            this._status(bits.join(' '), bad ? 'warn' : '');
        }

        // -------------------------------------------------------------
        // Playback — one clock
        // -------------------------------------------------------------

        get currentTime() {
            return this._virtualTime || 0;
        }

        seek(t) {
            const clamped = Math.max(0, Math.min(this.duration, t));
            this._virtualTime = clamped;
            this._videos.forEach((entry) => {
                if (isFinite(entry.el.duration)) entry.el.currentTime = clamped;
            });
            this._updateReadout();
            this.draw();
        }

        /** Move by whole frames. No-op without a declared rate. */
        stepFrame(delta) {
            if (!this.fps) {
                this._announce('Stepping needs a declared frame rate.');
                return;
            }
            this.pause();
            const frame = (frameAt(this.currentTime, this.fps) || 0) + delta;
            this.seek(timeOfFrame(frame, this.fps));
            this._announce(`Frame ${frameAt(this.currentTime, this.fps)}.`);
        }

        play() {
            this._videos.forEach((entry) => {
                const promise = entry.el.play();
                if (promise && promise.catch) promise.catch(() => {});
            });
            this._playing = true;
            this._tick();
            this._syncPlayButton();
        }

        pause() {
            this._videos.forEach((entry) => entry.el.pause());
            this._playing = false;
            if (this._raf) {
                cancelAnimationFrame(this._raf);
                this._raf = null;
            }
            this._syncPlayButton();
        }

        togglePlay() {
            if (this._playing) this.pause(); else this.play();
        }

        _syncPlayButton() {
            const btn = this.container.querySelector('.rollout-play');
            if (!btn) return;
            btn.setAttribute('aria-pressed', String(!!this._playing));
            btn.innerHTML = this._playing
                ? '<span aria-hidden="true">\u275A\u275A</span> Pause'
                : '<span aria-hidden="true">\u25B6</span> Play';
        }

        _tick() {
            if (!this._playing) return;
            // The clock follows the first *playing* video rather than a
            // wall-clock timer, so a panel that buffers does not silently
            // desynchronise the marks from what is on screen.
            const leader = this._videos.find(
                (entry) => isFinite(entry.el.duration));
            if (leader) this._virtualTime = leader.el.currentTime;
            this._updateReadout();
            this.draw();
            this._raf = requestAnimationFrame(() => this._tick());
        }

        _updateReadout() {
            const t = this.currentTime;
            const time = this.container.querySelector('.rollout-time');
            if (time) time.textContent = formatTime(t);
            const frame = this.container.querySelector('.rollout-frame');
            if (frame) {
                const index = frameAt(t, this.fps);
                frame.textContent = index === null ? '' : `frame ${index}`;
            }
        }

        // -------------------------------------------------------------
        // Panels and marks
        // -------------------------------------------------------------

        selectStream(streamId) {
            this.selectedStream = streamId;
            this.container.querySelectorAll('.rollout-panel')
                .forEach((figure) => {
                    const chosen = figure.dataset.stream === streamId;
                    figure.classList.toggle('rollout-panel-chosen', chosen);
                    const btn = figure.querySelector('.rollout-panel-choose');
                    if (btn) btn.setAttribute('aria-pressed', String(chosen));
                });
            this._syncMarkButtons();
            this._announce(`${this._streamName(streamId)} chosen.`);
            this.draw();
        }

        selectPanelByIndex(index) {
            const ids = this.streamIds;
            if (index < 0 || index >= ids.length) return;
            this.selectStream(ids[index]);
        }

        markViolation() {
            if (!this.selectedStream) {
                this._status('Choose a panel first — a break belongs to one '
                             + 'rollout.', 'warn');
                return;
            }
            const cap = this.config.maxViolations;
            if (cap && this.violations.length >= cap) {
                this._status(`This task allows at most ${cap} breaks.`, 'warn');
                return;
            }
            const t = snapToFrame(this.currentTime, this.fps);
            const incoming = { stream: this.selectedStream, t,
                               type: this._defaultType(),
                               severity: this._defaultSeverity(), note: '' };
            this.violations = insertViolation(this.violations, incoming);
            this.selectedViolation = this.violations.indexOf(incoming);
            // Marking a stream un-cleans it: they are contradictory answers,
            // and leaving both would make the stream simultaneously "no breaks"
            // and "a break at 3.4 s".
            this.clean = this.clean.filter((id) => id !== incoming.stream);
            this._syncViolationForm();
            this._syncMarkButtons();
            this._syncProgress();
            this._save();
            this.draw();
            this._announce(
                describeViolation(incoming,
                                  this._streamName(incoming.stream), this.fps)
                + ' Set what broke in the form below.');
        }

        /**
         * The type a new mark starts as.
         *
         * The first in the taxonomy, and the form opens focused on it. There
         * is no "unclassified" option on purpose: a nullable default is one
         * every annotator leaves alone under time pressure, and a dataset of
         * untyped breaks answers "when" without ever answering "why".
         */
        _defaultType() {
            const types = this.config.violationTypes || [];
            return types.length ? types[0].name : '';
        }

        /** The middle of the severity scale — neither dismissed nor maximal. */
        _defaultSeverity() {
            const scale = this.config.severities || [];
            if (!scale.length) return 2;
            return scale[Math.floor((scale.length - 1) / 2)].value;
        }

        toggleClean() {
            if (!this.selectedStream) return;
            const id = this.selectedStream;
            if (this.clean.indexOf(id) !== -1) {
                this.clean = this.clean.filter((s) => s !== id);
                this._announce(`${this._streamName(id)} no longer marked as `
                               + `having no breaks.`);
            } else {
                const had = this.violations.some((v) => v.stream === id);
                if (had) {
                    this._status(
                        `${this._streamName(id)} already has breaks marked. `
                        + `Delete them before saying it has none.`, 'warn');
                    return;
                }
                this.clean = this.clean.concat([id]);
                this._announce(`${this._streamName(id)} marked as having no `
                               + `breaks.`);
            }
            this._syncMarkButtons();
            this._syncProgress();
            this._save();
            this.draw();
        }

        selectViolation(index) {
            this.selectedViolation = index;
            if (index >= 0 && this.violations[index]) {
                const violation = this.violations[index];
                this.selectStream(violation.stream);
                this.seek(violation.t);
            }
            this._syncViolationForm();
            this.draw();
        }

        cycleViolation(step) {
            if (!this.violations.length) {
                this._announce('No breaks marked yet.');
                return;
            }
            const n = this.violations.length;
            const from = this.selectedViolation < 0
                ? (step > 0 ? -1 : 0) : this.selectedViolation;
            const next = ((from + step) % n + n) % n;
            this.selectViolation(next);
            this._announce(
                describeViolation(this.violations[next],
                                  this._streamName(this.violations[next].stream),
                                  this.fps));
        }

        /** Move the selected mark by whole frames. */
        nudgeViolation(delta) {
            const violation = this.violations[this.selectedViolation];
            if (!violation) return;
            if (!this.fps) {
                this._announce('Nudging needs a declared frame rate.');
                return;
            }
            const frame = (frameAt(violation.t, this.fps) || 0) + delta;
            violation.t = Math.max(0, Math.min(this.duration,
                                               timeOfFrame(frame, this.fps)));
            // Re-sorting moves the mark's index, so the selection is recovered
            // by identity rather than by position — otherwise a nudge past a
            // neighbour silently selects the neighbour.
            this.violations = this.violations
                .slice()
                .sort((a, b) => a.t - b.t);
            this.selectedViolation = this.violations.indexOf(violation);
            this.seek(violation.t);
            this._syncViolationForm();
            this._save();
            this.draw();
            this._announce(`Moved to frame ${frameAt(violation.t, this.fps)}.`);
        }

        deleteViolation() {
            const index = this.selectedViolation;
            if (index < 0 || !this.violations[index]) return;
            const removed = this.violations[index];
            this.violations = this.violations.filter((_, i) => i !== index);
            this.selectedViolation = -1;
            this._syncViolationForm();
            this._syncMarkButtons();
            this._syncProgress();
            this._save();
            this.draw();
            this._announce(
                `Break on ${this._streamName(removed.stream)} deleted.`);
        }

        // -------------------------------------------------------------
        // Drawing
        // -------------------------------------------------------------

        _lanes() {
            return this.streamIds.map((id, index) => ({
                streamId: id,
                y: index * LANE_HEIGHT,
                height: LANE_HEIGHT,
            }));
        }

        draw() {
            if (!this.canvas) return;
            const lanes = this._lanes();
            const height = Math.max(LANE_HEIGHT, lanes.length * LANE_HEIGHT);
            const width = this.canvas.clientWidth || 600;
            const dpr = window.devicePixelRatio || 1;

            if (this.canvas.width !== Math.round(width * dpr)
                || this.canvas.height !== Math.round(height * dpr)) {
                this.canvas.width = Math.round(width * dpr);
                this.canvas.height = Math.round(height * dpr);
                this.canvas.style.height = `${height}px`;
            }

            const ctx = this.canvas.getContext('2d');
            if (!ctx) return;
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
            ctx.clearRect(0, 0, width, height);

            lanes.forEach((lane) => this._drawLane(ctx, lane, width));
            this._drawIntervention(ctx, width, height);
            this._drawPlayhead(ctx, width, height);
        }

        _drawLane(ctx, lane, width) {
            // Two independent things to show, so they get two channels rather
            // than fighting over one fill: the lane's FILL is its answer state,
            // and a bar down its left edge is whether it is the chosen panel.
            //
            // The answer state was previously invisible here -- an unanswered
            // lane and a lane with a mark on it were the same grey, so the
            // timeline could not be scanned for what was left to do and only
            // the progress line knew. Colour is reinforcement, not the signal:
            // the progress line names the pending panels in text, and the
            // canvas description lists them (WCAG 1.4.1).
            const marked = this.violations.some(
                (v) => v.stream === lane.streamId);
            const clear = this.clean.indexOf(lane.streamId) !== -1;
            if (clear) {
                ctx.fillStyle = '#e6f4ea';        // answered: no breaks
            } else if (marked) {
                ctx.fillStyle = '#f6f6f7';        // answered: has breaks
            } else {
                ctx.fillStyle = '#fdf6e7';        // not answered yet
            }
            ctx.fillRect(0, lane.y, width, lane.height - 2);

            if (lane.streamId === this.selectedStream) {
                ctx.fillStyle = '#6e56cf';
                ctx.fillRect(0, lane.y, 3, lane.height - 2);
            }

            ctx.fillStyle = '#5a6472';
            ctx.font = '12px system-ui, sans-serif';
            ctx.textBaseline = 'middle';
            ctx.fillText(this._streamName(lane.streamId), 6,
                         lane.y + lane.height / 2);

            this.violations.forEach((violation, index) => {
                if (violation.stream !== lane.streamId) return;
                const x = timeToX(violation.t, this.duration, width);
                const selected = index === this.selectedViolation;
                ctx.strokeStyle = selected ? '#b02a37' : '#c2410c';
                ctx.lineWidth = selected ? 3 : 2;
                ctx.beginPath();
                ctx.moveTo(x, lane.y + 2);
                ctx.lineTo(x, lane.y + lane.height - 4);
                ctx.stroke();
                // A triangle at the top, so a mark is findable at a glance in a
                // lane that also carries a label and a playhead.
                ctx.fillStyle = ctx.strokeStyle;
                ctx.beginPath();
                ctx.moveTo(x - 4, lane.y + 2);
                ctx.lineTo(x + 4, lane.y + 2);
                ctx.lineTo(x, lane.y + 8);
                ctx.closePath();
                ctx.fill();
            });
        }

        _drawIntervention(ctx, width, height) {
            const t = this.set && this.set.intervention_t;
            if (t === null || t === undefined || !(this.duration > 0)) return;
            const x = timeToX(t, this.duration, width);
            ctx.save();
            ctx.setLineDash([4, 3]);
            ctx.strokeStyle = '#6e56cf';
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.moveTo(x, 0);
            ctx.lineTo(x, height);
            ctx.stroke();
            ctx.restore();
        }

        _drawPlayhead(ctx, width, height) {
            const x = timeToX(this.currentTime, this.duration, width);
            ctx.strokeStyle = '#11151c';
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(x, 0);
            ctx.lineTo(x, height);
            ctx.stroke();
        }

        // -------------------------------------------------------------
        // Binding
        // -------------------------------------------------------------

        _bindTransport() {
            const play = this.container.querySelector('.rollout-play');
            if (play) play.addEventListener('click', () => this.togglePlay());
            this.container.querySelectorAll('.rollout-step')
                .forEach((btn) => {
                    btn.addEventListener('click', () => this.stepFrame(
                        parseInt(btn.dataset.step, 10) || 0));
                });
            const mark = this.container.querySelector('.rollout-mark');
            if (mark) mark.addEventListener('click', () => this.markViolation());
            const clean = this.container.querySelector('.rollout-clean-btn');
            if (clean) clean.addEventListener('click', () => this.toggleClean());
        }

        _syncMarkButtons() {
            const has = !!this.selectedStream;
            const mark = this.container.querySelector('.rollout-mark');
            if (mark) mark.disabled = !has;
            const clean = this.container.querySelector('.rollout-clean-btn');
            if (clean) {
                clean.disabled = !has;
                const on = has && this.clean.indexOf(this.selectedStream) !== -1;
                clean.setAttribute('aria-pressed', String(on));
                clean.classList.toggle('rollout-clean-on', on);
            }
        }

        _bindCanvas() {
            if (!this.canvas) return;
            this.canvas.addEventListener('pointerdown', (event) => {
                const rect = this.canvas.getBoundingClientRect();
                const x = event.clientX - rect.left;
                const y = event.clientY - rect.top;
                const lane = this._lanes().find(
                    (l) => y >= l.y && y < l.y + l.height);
                if (!lane) return;

                const t = xToTime(x, this.duration, rect.width);
                const tolerance = this.duration > 0
                    ? (MARK_TOLERANCE / rect.width) * this.duration : 0;
                const index = violationAt(this.violations, lane.streamId, t,
                                          tolerance);
                if (index !== null) {
                    this.selectViolation(index);
                } else {
                    this.selectStream(lane.streamId);
                    this.seek(snapToFrame(t, this.fps));
                }
            });
        }

        _bindViolationForm() {
            const type = this.container.querySelector('.rollout-violation-type');
            const severity =
                this.container.querySelector('.rollout-violation-severity');
            const note = this.container.querySelector('.rollout-violation-note');
            const del =
                this.container.querySelector('.rollout-violation-delete');

            if (type) {
                type.addEventListener('change', () => {
                    const violation = this.violations[this.selectedViolation];
                    if (!violation) return;
                    violation.type = type.value;
                    this._save();
                    this.draw();
                });
            }
            if (severity) {
                severity.addEventListener('change', () => {
                    const violation = this.violations[this.selectedViolation];
                    if (!violation) return;
                    violation.severity = parseInt(severity.value, 10);
                    this._save();
                });
            }
            if (note) {
                note.addEventListener('input', () => {
                    const violation = this.violations[this.selectedViolation];
                    if (!violation) return;
                    violation.note = note.value;
                    this._save();
                });
            }
            if (del) del.addEventListener('click', () => this.deleteViolation());
        }

        _syncViolationForm() {
            const violation = this.violations[this.selectedViolation];
            const where =
                this.container.querySelector('.rollout-violation-where');
            const type = this.container.querySelector('.rollout-violation-type');
            const severity =
                this.container.querySelector('.rollout-violation-severity');
            const note = this.container.querySelector('.rollout-violation-note');
            const del =
                this.container.querySelector('.rollout-violation-delete');

            [type, severity, note, del].forEach((el) => {
                if (el) el.disabled = !violation;
            });
            if (where) {
                where.textContent = violation
                    ? describeViolation(violation,
                                        this._streamName(violation.stream),
                                        this.fps)
                    : 'No break selected';
            }
            if (!violation) return;
            if (type) type.value = violation.type || '';
            if (severity) severity.value = String(violation.severity || '');
            if (note) note.value = violation.note || '';
        }

        _bindPreference() {
            const confidence =
                this.container.querySelector('.rollout-confidence');
            if (confidence) {
                confidence.addEventListener('change', () => {
                    this.preference.confidence = confidence.value;
                    this._save();
                });
            }
        }

        _bindCounterfactual() {
            this.container.querySelectorAll(
                `input[name="rollout-cf-${cssEscape(this.schema)}"]`)
                .forEach((radio) => {
                    radio.addEventListener('change', () => {
                        this.counterfactual.verdict = radio.value;
                        // The divergence time is where the annotator was when
                        // they answered, which is the only time they can be
                        // said to have judged. Asking for it separately gets a
                        // guess or a blank.
                        this.counterfactual.t = this.currentTime;
                        this._save();
                    });
                });
            const note = this.container.querySelector('.rollout-cf-note');
            if (note) {
                note.addEventListener('input', () => {
                    this.counterfactual.note = note.value;
                    this._save();
                });
            }
        }

        _bindKeys() {
            const keys = this.config.toolKeys || {};
            this._keyHandler = (event) => {
                if (!this.container || !document.body.contains(this.container)) {
                    return;
                }
                // Typing in a field is not a shortcut. Without this, writing a
                // note moves the playhead, marks breaks and toggles playback —
                // the exact defect found in image-annotation.js in Wave 0.8.
                const target = event.target;
                const tag = target && target.tagName;
                if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT'
                    || (target && target.isContentEditable)) {
                    return;
                }
                if (event.metaKey || event.ctrlKey || event.altKey) return;

                const key = event.key;
                if (key === keys.play || key === ' ') {
                    event.preventDefault();
                    this.togglePlay();
                } else if (key === keys.prev_frame) {
                    event.preventDefault();
                    this.stepFrame(-1);
                } else if (key === keys.next_frame) {
                    event.preventDefault();
                    this.stepFrame(1);
                } else if (key === keys.mark) {
                    event.preventDefault();
                    this.markViolation();
                } else if (key === keys.clean) {
                    event.preventDefault();
                    this.toggleClean();
                } else if (key === keys.prev_violation) {
                    event.preventDefault();
                    this.cycleViolation(-1);
                } else if (key === keys.next_violation) {
                    event.preventDefault();
                    this.cycleViolation(1);
                } else if (key === 'ArrowLeft' || key === 'ArrowRight') {
                    if (this.selectedViolation < 0) return;
                    event.preventDefault();
                    this.nudgeViolation(key === 'ArrowLeft' ? -1 : 1);
                } else if (key === 'Delete' || key === 'Backspace') {
                    if (this.selectedViolation < 0) return;
                    event.preventDefault();
                    this.deleteViolation();
                } else if (/^[1-9]$/.test(key)) {
                    event.preventDefault();
                    this.selectPanelByIndex(parseInt(key, 10) - 1);
                }
            };
            document.addEventListener('keydown', this._keyHandler);
        }

        // -------------------------------------------------------------
        // The four functions annotation.js drives
        // -------------------------------------------------------------

        serialize() {
            return JSON.stringify({
                violations: this.violations,
                clean: this.clean,
                preference: this.preference,
                counterfactual: this.counterfactual,
            });
        }

        clearAnnotations() {
            // Everything, named explicitly. Nothing here is owned by a canvas
            // or a scene graph, so a generic clear reaches none of it — three
            // separate cross-instance corruption bugs in the image manager came
            // from exactly that gap.
            this.violations = [];
            this.clean = [];
            this.preference = { winner: '', confidence: '', rubric: {} };
            this.counterfactual = { verdict: '', t: null, note: '' };
            this.selectedViolation = -1;
            this._resetFormInputs();
            this._syncViolationForm();
            this._syncMarkButtons();
            this._syncProgress();
            this._save();
            this.draw();
        }

        getAnnotationCount() {
            return this.violations.length
                + this.clean.length
                + (this.preference.winner ? 1 : 0)
                + (this.counterfactual.verdict ? 1 : 0);
        }

        /**
         * Streams the annotator has not answered for.
         *
         * Exposed rather than private because it is the thing a validation
         * hook wants, and because "you have not looked at panel C" is the
         * single most useful message this schema can produce.
         */
        unresolved() {
            if (!this.config.requireClean) return [];
            return unresolvedStreams(this.streamIds, this.violations,
                                     this.clean);
        }

        /**
         * Keep the "how much is left" line, and the canvas description, true.
         *
         * Both exist because the state they describe is otherwise invisible.
         * `require_clean` was a config option that did nothing at all until
         * this landed: `unresolved()` was defined and called from nowhere, so a
         * project could set it, read the documentation promising a submission
         * would be refused, and have every incomplete item sail through.
         *
         * The canvas half is the same problem for a different reader — the
         * marks live only as pixels, so without a description a screen-reader
         * user can create marks and never afterwards find out what they have.
         */
        _syncProgress() {
            const ids = this.streamIds;
            const pending = this.unresolved();
            const line = this.container.querySelector('.rollout-progress');
            if (line) {
                if (!ids.length) {
                    line.textContent = '';
                } else if (!this.config.requireClean) {
                    line.textContent = '';
                } else if (!pending.length) {
                    line.textContent = `All ${ids.length} panels answered.`;
                    line.removeAttribute('data-kind');
                } else {
                    const names = pending.map((id) => this._streamName(id));
                    line.textContent =
                        `${ids.length - pending.length} of ${ids.length} panels `
                        + `answered — still to do: ${names.join(', ')}.`;
                    line.setAttribute('data-kind', 'pending');
                }
            }
            if (this.canvas) {
                this.canvas.setAttribute('aria-label',
                                         this._describeTimeline());
            }
        }

        /** The timeline in words: what is marked, what is clear, what is not. */
        _describeTimeline() {
            const ids = this.streamIds;
            if (!ids.length) return 'Rollout timeline, no panels loaded.';
            const parts = ids.map((id) => {
                const name = this._streamName(id);
                const marks = this.violations.filter((v) => v.stream === id);
                if (marks.length) {
                    const where = marks.map((v) => {
                        const frame = frameAt(v.t, this.fps);
                        return frame === null ? formatTime(v.t)
                            : `frame ${frame}`;
                    });
                    return `${name}: ${marks.length} break`
                        + `${marks.length === 1 ? '' : 's'} at ${where.join(', ')}`;
                }
                if (this.clean.indexOf(id) !== -1) return `${name}: no breaks`;
                return `${name}: not answered`;
            });
            return `Rollout timeline. ${parts.join('. ')}.`;
        }

        /**
         * Warn — once — before leaving an item with unanswered panels.
         *
         * Warn and allow, not block. A panel whose video failed to decode can
         * never be answered, and a hard block would trap the annotator on an
         * item with no way forward and no way to report it. A second press
         * proceeds, so the cost of a deliberate skip is one extra click and the
         * cost of an accidental one is zero.
         */
        _bindNavigationGuard() {
            this._navGuard = (event) => {
                // Same containment check the key handler carries. Today Next is
                // a full page load, so a stale listener dies with the document
                // — but if the shell ever re-renders in place, a detached
                // manager would keep warning about panels that are no longer
                // on the page.
                if (!this.container || !document.body.contains(this.container)) {
                    return;
                }
                const target = event.target
                    && event.target.closest
                    && event.target.closest('#next-btn, #submit-btn');
                if (!target) return;
                const pending = this.unresolved();
                if (!pending.length || this._navWarned) {
                    this._navWarned = false;
                    return;
                }
                // stopImmediatePropagation, on DOCUMENT, in the capture phase.
                // The Next button navigates from an inline `onclick` attribute,
                // which is registered when the template is parsed -- long before
                // this manager exists. A listener on the button itself is
                // therefore registered second and runs second, so cancelling
                // there fires the warning AND navigates anyway: the annotator
                // sees the message flash past on their way to the next item.
                // Document-level capture is the only phase that genuinely
                // precedes an inline handler on the target.
                event.preventDefault();
                event.stopImmediatePropagation();
                this._navWarned = true;
                const names = pending.map((id) => this._streamName(id));
                this._status(
                    `${names.join(', ')} ${names.length === 1 ? 'has' : 'have'} `
                    + `no answer yet — mark a break, or press "No breaks". `
                    + `Press Next again to move on anyway.`, 'warn');
                this._announce(
                    `${names.length} panel${names.length === 1 ? '' : 's'} `
                    + `still unanswered. Press Next again to move on anyway.`);
            };
            document.addEventListener('click', this._navGuard, true);
        }

        _resetFormInputs() {
            this.container.querySelectorAll(
                '.rollout-winner input[type="radio"], '
                + '.rollout-counterfactual input[type="radio"], '
                + '.rollout-rubric input[type="radio"]')
                .forEach((radio) => { radio.checked = false; });
            const confidence =
                this.container.querySelector('.rollout-confidence');
            if (confidence) confidence.value = '';
            const cfNote = this.container.querySelector('.rollout-cf-note');
            if (cfNote) cfNote.value = '';
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
            this.violations = Array.isArray(data.violations)
                ? data.violations : [];
            this.clean = Array.isArray(data.clean) ? data.clean : [];
            this.preference = data.preference
                || { winner: '', confidence: '', rubric: {} };
            if (!this.preference.rubric) this.preference.rubric = {};
            this.counterfactual = data.counterfactual
                || { verdict: '', t: null, note: '' };
        }

        /**
         * Push restored state into the controls.
         *
         * Separate from `_restoreFromInput` because the winner radios do not
         * exist until the manifest arrives — they are built from it — so
         * restoring on init would write to controls that are not there yet and
         * silently drop the annotator's saved preference.
         */
        _applyRestoredState() {
            this.container.querySelectorAll(
                `.rollout-winner input[type="radio"]`).forEach((radio) => {
                radio.checked = radio.value === this.preference.winner;
            });
            const confidence =
                this.container.querySelector('.rollout-confidence');
            if (confidence) {
                confidence.value = this.preference.confidence || '';
            }
            Object.keys(this.preference.rubric || {}).forEach((dimension) => {
                const value = String(this.preference.rubric[dimension]);
                this.container.querySelectorAll(
                    `input[name="rollout-rubric-${cssEscape(this.schema)}-`
                    + `${cssEscape(dimension)}"]`).forEach((radio) => {
                    radio.checked = radio.value === value;
                });
            });
            this.container.querySelectorAll(
                `input[name="rollout-cf-${cssEscape(this.schema)}"]`)
                .forEach((radio) => {
                    radio.checked = radio.value === this.counterfactual.verdict;
                });
            const cfNote = this.container.querySelector('.rollout-cf-note');
            if (cfNote) cfNote.value = this.counterfactual.note || '';
            this._syncViolationForm();
            this._syncMarkButtons();
            this._syncProgress();
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
                && this.container.querySelector('.rollout-status');
            if (!el) return;
            el.textContent = message;
            if (kind) el.setAttribute('data-kind', kind);
            else el.removeAttribute('data-kind');
        }

        /**
         * Announce something a screen reader would otherwise never learn.
         *
         * The status line is not a live region: it is rewritten as the
         * playhead moves, and a live region updated several times a second is
         * a screen reader that never stops talking. Discrete events come here
         * instead. The zero-width space alternation is because a screen reader
         * does not re-announce an unchanged string, so marking two breaks in a
         * row would be announced once.
         */
        _announce(message) {
            const el = this.container
                && this.container.querySelector('.rollout-announce');
            if (!el) return;
            el.textContent = (el.textContent === message)
                ? `${message}\u200B` : message;
        }
    }

    function cssEscape(value) {
        if (typeof CSS !== 'undefined' && CSS.escape) return CSS.escape(value);
        return String(value).replace(/["\\]/g, '\\$&');
    }

    RolloutEvaluationManager.timeToX = timeToX;
    RolloutEvaluationManager.xToTime = xToTime;
    RolloutEvaluationManager.frameAt = frameAt;
    RolloutEvaluationManager.timeOfFrame = timeOfFrame;
    RolloutEvaluationManager.snapToFrame = snapToFrame;
    RolloutEvaluationManager.insertViolation = insertViolation;
    RolloutEvaluationManager.violationAt = violationAt;
    RolloutEvaluationManager.unresolvedStreams = unresolvedStreams;
    RolloutEvaluationManager.describeViolation = describeViolation;
    RolloutEvaluationManager.formatTime = formatTime;
    RolloutEvaluationManager.MARK_MERGE_WINDOW = MARK_MERGE_WINDOW;
    RolloutEvaluationManager.LANE_HEIGHT = LANE_HEIGHT;

    if (typeof module !== 'undefined' && module.exports) {
        module.exports = RolloutEvaluationManager;
    }
    if (root) root.RolloutEvaluationManager = RolloutEvaluationManager;
})(typeof window !== 'undefined' ? window
    : (typeof globalThis !== 'undefined' ? globalThis : null));

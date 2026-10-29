/*
 * Timed trials on the annotation page (config: trial_timing).
 *
 * Each item runs as one trial:
 *   inter-trial interval -> fixation -> stimulus -> response window -> save + next
 *
 * The stimulus is revealed inside a requestAnimationFrame callback and its
 * onset is the timestamp of the FOLLOWING frame, the first one painted with
 * the stimulus visible. The reaction time is the keydown event's timeStamp
 * minus that onset; both are on the performance.now() clock. Stimulus offset
 * and the deadline are checked every frame rather than with setTimeout, so
 * they land on frame boundaries.
 *
 * Navigation is a full page load, so the inter-trial interval spans two
 * pages: the response time is kept in sessionStorage and the next page waits
 * out whatever is left of iti_ms before its fixation.
 *
 * The record goes to the server with the normal save (annotation.js puts
 * window.potatoTrial.record() in the /updateinstance body).
 *
 * With trial_timing.presentation the stimulus is the item's text shown one
 * region at a time (moving window, centred, cumulative, or the maze task).
 * Each region appears on a frame boundary like the stimulus does, and its
 * reading time is the next key press minus that frame. After the last region
 * the comprehension question, if any, runs as the normal response window.
 */
(function () {
    'use strict';

    var cfg = window.potatoTrialTiming;
    if (!cfg) { return; }

    var LAST_END_KEY = 'potato.trial.lastEndEpochMs';
    var STARTED_KEY = 'potato.trial.started';
    var body = document.body;

    var state = 'idle';
    var onset = null;
    var instanceId = null;
    var frameMs = null;
    var timerResolution = null;
    var fixationActual = null;
    var stimulusActual = null;
    var stimulusHiddenAt = null;
    var itiActual = null;
    var earlyKeys = 0;
    var tabHidden = false;
    var fullscreenAtOnset = false;
    var reloads = 0;
    var result = null;
    var rafId = null;
    var pres = cfg.presentation || null;
    var regionIndex = -1;
    var regionOnset = null;
    var regionErrors = 0;
    var regionLog = [];
    var mazeCorrectSide = null;
    var readingEl = null;

    var api = {
        ownsKeys: false,
        state: function () { return state; },
        record: function () { return result; }
    };
    window.potatoTrial = api;

    function epochNow() { return performance.timeOrigin + performance.now(); }

    function readSession(key) {
        try { return window.sessionStorage.getItem(key); } catch (e) { return null; }
    }
    function writeSession(key, value) {
        try {
            if (value === null) { window.sessionStorage.removeItem(key); }
            else { window.sessionStorage.setItem(key, value); }
        } catch (e) { /* private mode: the ITI then starts from page load */ }
    }

    function measureTimerResolution() {
        var smallest = Infinity;
        var last = performance.now();
        for (var i = 0; i < 2000; i++) {
            var t = performance.now();
            if (t > last) {
                smallest = Math.min(smallest, t - last);
                last = t;
            }
        }
        return smallest === Infinity ? null : Math.round(smallest * 1000) / 1000;
    }

    function setPhase(name) {
        state = name;
        body.setAttribute('data-trial-state', name);
    }

    // ---- DOM ------------------------------------------------------------

    function buildChrome() {
        var area = document.querySelector('.instance-area');
        if (area && !document.getElementById('potato-trial-fixation')) {
            var fix = document.createElement('div');
            fix.id = 'potato-trial-fixation';
            fix.className = 'potato-trial-fixation';
            fix.setAttribute('aria-hidden', 'true');
            fix.textContent = cfg.fixation_symbol || '+';
            // Inside the stimulus area, over it: the area keeps its size while
            // hidden, so the stimulus appears exactly where the cross was.
            area.appendChild(fix);
        }
        var keys = Object.keys(cfg.keys || {});
        if (area && keys.length && !document.getElementById('potato-trial-keys')) {
            var legend = document.createElement('p');
            legend.id = 'potato-trial-keys';
            legend.className = 'potato-trial-keys';
            legend.textContent = keys.map(function (k) {
                return (k === ' ' ? 'Space' : k.toUpperCase()) + ' = ' + cfg.keys[k];
            }).join('    ');
            area.parentNode.insertBefore(legend, area.nextSibling);
        }
        if (!cfg.show_response_options) { body.classList.add('potato-trial-hide-responses'); }
        if (!cfg.allow_mouse) { body.classList.add('potato-trial-keys-only'); }
    }

    // ---- Trial sequence -------------------------------------------------

    function start(id) {
        instanceId = id;
        api.ownsKeys = true;
        timerResolution = measureTimerResolution();

        var started = null;
        try { started = JSON.parse(readSession(STARTED_KEY) || 'null'); } catch (e) { started = null; }
        if (started && started.id === id) { reloads = (started.reloads || 0) + 1; }
        writeSession(STARTED_KEY, JSON.stringify({ id: id, reloads: reloads }));

        var lastEnd = parseFloat(readSession(LAST_END_KEY));
        var wait = 0;
        if (!isNaN(lastEnd)) {
            var since = epochNow() - lastEnd;
            if (since >= 0 && since < 60000) {
                wait = Math.max(0, (cfg.iti_ms || 0) - since);
            }
        } else {
            wait = cfg.iti_ms || 0;
        }
        setPhase('iti');
        waitFrames(wait, function () {
            if (!isNaN(lastEnd)) { itiActual = Math.round(epochNow() - lastEnd); }
            fixation();
        });
    }

    // Call `done` on the first frame at least `ms` after now; measures the
    // frame interval on the way.
    function waitFrames(ms, done) {
        var begin = null;
        var prev = null;
        var deltas = [];
        function step(ts) {
            if (begin === null) { begin = ts; }
            if (prev !== null) { deltas.push(ts - prev); }
            prev = ts;
            if (ts - begin >= ms) {
                if (deltas.length) {
                    deltas.sort(function (a, b) { return a - b; });
                    var median = deltas[Math.floor(deltas.length / 2)];
                    frameMs = frameMs === null ? median : Math.min(frameMs, median);
                }
                done(ts);
                return;
            }
            rafId = requestAnimationFrame(step);
        }
        rafId = requestAnimationFrame(step);
    }

    function fixation() {
        var ms = cfg.fixation_ms || 0;
        if (!ms) { reveal(); return; }
        setPhase('fixation');
        body.classList.add('potato-trial-fixating');
        var shownAt = null;
        rafId = requestAnimationFrame(function (ts) {
            shownAt = ts;
            waitFrames(Math.max(0, ms - (frameMs || 16.7) / 2), function (endTs) {
                fixationActual = Math.round(endTs - shownAt);
                body.classList.remove('potato-trial-fixating');
                reveal();
            });
        });
    }

    // ---- Word-by-word presentation (self-paced reading, RSVP, maze) -----

    function mask(text) {
        return text.replace(/\S/g, pres.mask_char || '-');
    }

    function buildReading() {
        var area = document.querySelector('.instance-area');
        readingEl = document.createElement('div');
        readingEl.id = 'potato-trial-reading';
        readingEl.className = 'potato-trial-reading potato-trial-reading-' + pres.mode;
        readingEl.setAttribute('aria-live', 'off');
        if (area) { area.appendChild(readingEl); }
        body.classList.add('potato-trial-presenting');
        var legend = document.getElementById('potato-trial-keys');
        // "word" only when every region is one word; regions can be phrases.
        var unit = (pres.regions || []).every(function (r) { return !/\s/.test(String(r).trim()); })
            ? 'word' : 'region';
        var hint = pres.mode === 'maze'
            ? (pres.maze_keys.left.toUpperCase() + ' = left ' + unit + '    ' + pres.maze_keys.right.toUpperCase() + ' = right ' + unit)
            : ((pres.advance_key === ' ' ? 'Space' : pres.advance_key.toUpperCase()) + ' = next ' + unit);
        var p = document.createElement('p');
        p.id = 'potato-trial-reading-keys';
        p.className = 'potato-trial-keys';
        p.textContent = hint;
        if (area) { area.parentNode.insertBefore(p, area.nextSibling); }
        if (legend) { legend.hidden = true; }
    }

    function renderRegion(i) {
        var regions = pres.regions;
        readingEl.innerHTML = '';
        if (pres.mode === 'maze') {
            var correctLeft = Math.random() < 0.5;
            mazeCorrectSide = correctLeft ? 'left' : 'right';
            var right = regions[i], wrong = pres.distractors[i] || 'x-x-x';
            [correctLeft ? right : wrong, correctLeft ? wrong : right].forEach(function (w, k) {
                var span = document.createElement('span');
                span.className = 'potato-trial-maze-word potato-trial-maze-' + (k ? 'right' : 'left');
                span.textContent = w;
                readingEl.appendChild(span);
            });
            return;
        }
        if (pres.mode === 'centered') {
            var only = document.createElement('span');
            only.className = 'potato-trial-region potato-trial-region-current';
            only.textContent = regions[i];
            readingEl.appendChild(only);
            return;
        }
        regions.forEach(function (r, k) {
            var span = document.createElement('span');
            var shown = k === i || (pres.mode === 'cumulative' && k < i);
            span.className = 'potato-trial-region' + (k === i ? ' potato-trial-region-current' : '');
            span.textContent = shown ? r : mask(r);
            readingEl.appendChild(span);
            if (k < regions.length - 1) { readingEl.appendChild(document.createTextNode(' ')); }
        });
    }

    function startReading() {
        buildReading();
        regionIndex = -1;
        // The masked sentence first (or nothing, for centred and maze), then
        // the first region on the first key press -- the usual self-paced
        // reading start. The maze starts on its first word pair at once.
        if (pres.mode === 'maze') {
            showRegion(0);
        } else {
            if (pres.mode !== 'centered') {
                readingEl.textContent = pres.regions.map(mask).join(' ');
            }
            setPhase('reading');
        }
    }

    function showRegion(i) {
        regionIndex = i;
        regionErrors = 0;
        renderRegion(i);
        setPhase('reading');
        rafId = requestAnimationFrame(function () {
            rafId = requestAnimationFrame(function (ts) { regionOnset = ts; });
        });
    }

    function readingKey(key, ts) {
        if (pres.mode === 'maze') {
            if (regionOnset === null) { return; }
            var side = key === pres.maze_keys.left ? 'left' : (key === pres.maze_keys.right ? 'right' : null);
            if (!side) { return; }
            var correct = side === mazeCorrectSide;
            if (!correct && pres.on_error === 'redo') {
                regionErrors++;
                readingEl.classList.add('potato-trial-maze-error');
                setTimeout(function () { readingEl.classList.remove('potato-trial-maze-error'); }, 300);
                return;
            }
            regionLog.push({index: regionIndex, text: pres.regions[regionIndex],
                            rt_ms: Math.round((ts - regionOnset) * 10) / 10,
                            correct: correct, side: side, errors: regionErrors});
            if (!correct) { endReading(); return; }      // on_error: stop
        } else {
            if (key !== pres.advance_key) { return; }
            if (regionIndex >= 0 && regionOnset !== null) {
                regionLog.push({index: regionIndex, text: pres.regions[regionIndex],
                                rt_ms: Math.round((ts - regionOnset) * 10) / 10});
            }
        }
        regionOnset = null;
        if (regionIndex + 1 < pres.regions.length) { showRegion(regionIndex + 1); }
        else { endReading(); }
    }

    function endReading() {
        if (readingEl) { readingEl.innerHTML = ''; }
        var keysHint = document.getElementById('potato-trial-reading-keys');
        if (keysHint) { keysHint.hidden = true; }
        if (!pres.ask || !cfg.schema) {
            finish('completed', null, performance.now());
            return;
        }
        var legend = document.getElementById('potato-trial-keys');
        if (legend) { legend.hidden = false; }
        if (pres.question) {
            var q = document.createElement('p');
            q.className = 'potato-trial-question';
            q.textContent = pres.question;
            readingEl.appendChild(q);
        } else {
            body.classList.remove('potato-trial-presenting');
        }
        // The question is the stimulus of a normal response window.
        rafId = requestAnimationFrame(function () {
            rafId = requestAnimationFrame(function (ts) {
                onset = ts;
                setPhase('response');
                if (cfg.show_response_options) { body.classList.add('potato-trial-responding'); }
                loop(ts);
            });
        });
    }

    function reveal() {
        rafId = requestAnimationFrame(function () {
            body.classList.remove('potato-trial-pending');
            if (pres && pres.regions && pres.regions.length) {
                startReading();
                return;
            }
            rafId = requestAnimationFrame(function (ts) {
                onset = ts;
                fullscreenAtOnset = !!document.fullscreenElement;
                setPhase('response');
                if (cfg.show_response_options) { body.classList.add('potato-trial-responding'); }
                loop(ts);
            });
        });
    }

    function loop(ts) {
        if (state !== 'response') { return; }
        var half = (frameMs || 16.7) / 2;
        if (cfg.stimulus_duration_ms && stimulusHiddenAt === null &&
                ts >= onset + cfg.stimulus_duration_ms - half) {
            body.classList.add('potato-trial-stimulus-off');
            stimulusHiddenAt = ts;
            stimulusActual = Math.round(ts - onset);
        }
        if (cfg.trial_duration_ms && performance.now() - onset >= cfg.trial_duration_ms) {
            finish('timeout', null, performance.now());
            return;
        }
        rafId = requestAnimationFrame(loop);
    }

    function selectLabel(label) {
        var schema = cfg.schema;
        var inputs = document.querySelectorAll('input[type="radio"][schema="' + CSS.escape(schema) + '"]');
        for (var i = 0; i < inputs.length; i++) {
            var input = inputs[i];
            if (input.getAttribute('label_name') === label || input.value === label) {
                if (!input.checked) { input.click(); }
                return true;
            }
        }
        console.warn('[potato-trial] no option "' + label + '" in scheme "' + schema + '"');
        return false;
    }

    function finish(outcome, key, ts) {
        if (state === 'ended') { return; }
        setPhase('ended');
        if (rafId !== null) { cancelAnimationFrame(rafId); }
        body.classList.add('potato-trial-stimulus-off');
        if (stimulusHiddenAt === null && onset !== null) {
            stimulusActual = Math.round(ts - onset);
        }
        var label = null;
        if (outcome === 'response') {
            label = key !== null ? cfg.keys[key] : mouseLabel;
            if (key !== null) { selectLabel(label); }
        }
        result = {
            outcome: outcome,
            key: key === ' ' ? 'space' : key,
            label: label,
            rt_ms: outcome === 'response' ? Math.round((ts - onset) * 10) / 10 : null,
            onset_epoch_ms: Math.round(performance.timeOrigin + (onset !== null ? onset : ts)),
            regions: pres ? regionLog : undefined,
            fixation_ms_actual: fixationActual,
            stimulus_ms_actual: stimulusActual,
            iti_actual_ms: itiActual,
            frame_ms: frameMs === null ? null : Math.round(frameMs * 100) / 100,
            timer_resolution_ms: timerResolution,
            early_keys: earlyKeys,
            reloads: reloads,
            tab_hidden: tabHidden,
            fullscreen_at_onset: fullscreenAtOnset,
            intended: {
                fixation_ms: cfg.fixation_ms || 0,
                stimulus_duration_ms: cfg.stimulus_duration_ms || null,
                trial_duration_ms: cfg.trial_duration_ms || null,
                iti_ms: cfg.iti_ms || 0
            }
        };
        writeSession(LAST_END_KEY, String(performance.timeOrigin + ts));
        writeSession(STARTED_KEY, null);
        // A read sentence with no question has nothing to answer either.
        advance(outcome === 'timeout' || outcome === 'completed', 0);
    }

    // annotation.js refuses to navigate while it is still loading or saving;
    // try again shortly rather than leave the participant on a blank trial.
    function advance(bypassRequired, tries) {
        if (typeof navigateToNext !== 'function') { return; }
        if (typeof isLoading !== 'undefined' && isLoading && tries < 100) {
            setTimeout(function () { advance(bypassRequired, tries + 1); }, 30);
            return;
        }
        navigateToNext({ bypassRequired: bypassRequired });
    }

    // ---- Input ----------------------------------------------------------

    var mouseLabel = null;

    function normalizeKey(e) {
        if (e.key === ' ' || e.code === 'Space') { return ' '; }
        return (e.key || '').toLowerCase();
    }

    document.addEventListener('keydown', function (e) {
        if (!api.ownsKeys) { return; }
        var key = normalizeKey(e);
        var mapped = Object.prototype.hasOwnProperty.call(cfg.keys || {}, key);
        if (state === 'reading') {
            var readKeys = pres.mode === 'maze' ? [pres.maze_keys.left, pres.maze_keys.right]
                : [pres.advance_key];
            if (readKeys.indexOf(key) >= 0) {
                e.preventDefault();
                e.stopImmediatePropagation();
                if (!e.repeat) { readingKey(key, e.timeStamp); }
            }
            return;
        }
        if (state === 'response') {
            if (mapped) {
                e.preventDefault();
                e.stopImmediatePropagation();
                if (e.repeat) { return; }
                finish('response', key, e.timeStamp);
            }
            return;
        }
        if (mapped && state !== 'ended') {
            // Before the stimulus: counted, not taken.
            e.preventDefault();
            e.stopImmediatePropagation();
            if (!e.repeat) { earlyKeys++; }
        }
    }, true);

    document.addEventListener('change', function (e) {
        if (!cfg.allow_mouse || state !== 'response') { return; }
        var t = e.target;
        if (t && t.getAttribute && t.getAttribute('schema') === cfg.schema && t.checked) {
            mouseLabel = t.getAttribute('label_name') || t.value;
            finish('response', null, performance.now());
        }
    }, true);

    document.addEventListener('visibilitychange', function () {
        if (document.hidden && state !== 'idle' && state !== 'ended') { tabHidden = true; }
    });

    function init(id) {
        if (state !== 'idle') { return; }
        buildChrome();
        start(id);
    }

    document.addEventListener('potato:instance-ready', function (e) {
        init(e.detail && e.detail.instanceId);
    });
})();

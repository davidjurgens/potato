/**
 * Potato Pocket — mobile-first annotation client.
 *
 * Card-stack UI over the same server APIs the desktop page uses:
 * - GET  /pocket/api/task   (schema specs + capability)
 * - GET  /pocket/api/batch  (items to annotate; prefetched for offline)
 * - POST /updateinstance    (saves — identical payload to annotation.js)
 *
 * Offline-first: the fetched batch and any unsent saves live in localStorage;
 * the queue flushes on 'online' and after every successful save. A service
 * worker (/pocket/sw.js) caches the app shell so the page itself loads
 * offline after the first visit.
 */
(function () {
    'use strict';

    var QUEUE_KEY = 'pocket_save_queue_v1';
    var ITEMS_KEY = 'pocket_items_v1';

    var state = {
        task: null,       // /pocket/api/task payload
        items: [],        // [{instance_id, text, annotations}]
        idx: 0,
        total: 0,
        done: 0,
        answers: {},      // current card: {schema: {label: value}}
        touchStartX: null
    };

    var main = document.getElementById('pk-main');

    function esc(s) {
        var d = document.createElement('div');
        d.textContent = s == null ? '' : String(s);
        return d.innerHTML;
    }

    function haptic() {
        if (navigator.vibrate) navigator.vibrate(12);
    }

    // ------------------------------------------------------------ storage --
    function loadQueue() {
        try { return JSON.parse(localStorage.getItem(QUEUE_KEY)) || []; }
        catch (e) { return []; }
    }

    function saveQueue(queue) {
        localStorage.setItem(QUEUE_KEY, JSON.stringify(queue));
        renderSyncChip();
    }

    // -------------------------------------------------------------- server --
    function fetchTask() {
        return fetch('/pocket/api/task').then(function (r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
        });
    }

    function fetchBatch() {
        return fetch('/pocket/api/batch').then(function (r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
        });
    }

    /**
     * "The server cannot be reached" and "the server refused this" used to be
     * the same event: every non-2xx became one Error and the record stayed
     * queued forever. A restart of a default config is enough to produce it --
     * no secret_key, no persist_sessions, so the Flask session does not
     * survive and /updateinstance answers 401. The chip then read "Syncing 2
     * saves…" indefinitely while the annotator was never told the one thing
     * that fixes it, which is to sign in again.
     */
    function authError(status) {
        var e = new Error('HTTP ' + status);
        e.needsLogin = true;
        return e;
    }

    /** Same payload shape annotation.js sends. */
    function postSave(record) {
        return fetch('/updateinstance', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                instance_id: record.instance_id,
                annotations: record.annotations,
                span_annotations: [],
                // How long the card was on screen. Read by the attention-check
                // path, which is where `min_response_time` lives; without it
                // a check served to a phone could not fail on time, which
                // would show on the admin page as a check that PASSED.
                // Measured on the client, so a record that waited an hour in
                // the offline queue still reports an honest reading time.
                response_time_seconds: record.response_time_seconds
            })
        }).then(function (r) {
            if (r.status === 401 || r.status === 403) throw authError(r.status);
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
        }).then(function (data) {
            if (data && data.status === 'error') throw new Error(data.message);
            return data;
        });
    }

    /** Set when the server has refused us; cleared by a successful save. */
    var signedOut = false;

    function flushQueue() {
        var queue = loadQueue();
        if (!queue.length || !navigator.onLine) { renderSyncChip(); return; }
        var record = queue[0];
        postSave(record).then(function () {
            signedOut = false;
            var rest = loadQueue().filter(function (q) {
                return !(q.instance_id === record.instance_id && q.ts === record.ts);
            });
            saveQueue(rest);
            if (rest.length) {
                flushQueue();
            } else {
                renderSyncChip(true);
                // The end-of-batch screen says how many answers are still to
                // send, so it goes stale the moment the last one goes. Found
                // by the node harness: the queue emptied and the page kept
                // saying "2 answers still to send".
                if (showingPendingDone) renderDone();
            }
        }).catch(function (err) {
            // A refusal is not a lost connection. Retrying it is not going to
            // work and saying "syncing" while it happens is a lie, so stop and
            // say what would fix it. Nothing is discarded: the records stay in
            // the queue and drain on the next flush after signing in.
            var was = signedOut;
            signedOut = !!(err && err.needsLogin);
            renderSyncChip();
            // The end-of-batch screen explains what will happen to the queued
            // answers, and "as soon as the server answers" stops being true
            // the moment the server refuses. Found in Chrome: the chip flipped
            // and the screen behind it did not.
            if (showingPendingDone && was !== signedOut) renderDone();
        });
    }

    /** Retry now, whatever stopped us last time. */
    function retryQueue() {
        signedOut = false;
        flushQueue();
    }

    // ---------------------------------------------------------------- sync --
    function renderSyncChip(justSynced) {
        var chip = document.getElementById('pk-sync');
        var queue = loadQueue();
        if (queue.length) {
            chip.hidden = false;
            chip.classList.remove('pk-ok');
            chip.classList.toggle('pk-blocked', signedOut);
            var n = queue.length + ' save' + (queue.length === 1 ? '' : 's');
            if (signedOut) {
                // The one thing that fixes it, said where the annotator is
                // looking. The saves are safe; they are not going anywhere
                // until this is dealt with.
                chip.innerHTML = n + ' waiting — <a href="/login">sign in again</a> to send them';
            } else {
                chip.textContent = navigator.onLine
                    ? 'Syncing ' + n + '…'
                    : 'Offline — ' + n + ' queued';
            }
        } else if (justSynced) {
            chip.hidden = false;
            chip.classList.add('pk-ok');
            chip.textContent = 'All saves synced ✓';
            setTimeout(function () { chip.hidden = true; }, 2200);
        } else {
            chip.hidden = true;
        }
    }

    // ------------------------------------------------------------ progress --
    function renderProgress() {
        var finished = state.done + state.idx;
        var total = Math.max(state.total, 1);
        var pct = Math.min(100, Math.round(100 * finished / total));
        document.getElementById('pk-progress').style.width = pct + '%';
        document.getElementById('pk-count').textContent =
            Math.min(finished + 1, total) + ' of ' + total;
        var bar = document.querySelector('.pk-progress');
        if (bar) bar.setAttribute('aria-valuenow', String(pct));
    }

    // -------------------------------------------------------------- saving --
    function currentItem() { return state.items[state.idx] || null; }

    function answersComplete() {
        var schemas = state.task.schemas.filter(function (s) {
            return s.annotation_type !== 'pure_display';
        });
        return schemas.every(function (s) {
            var a = state.answers[s.name];
            return a && Object.keys(a).length > 0;
        });
    }

    function flatAnnotations() {
        var flat = {};
        Object.keys(state.answers).forEach(function (schema) {
            var labels = state.answers[schema];
            Object.keys(labels).forEach(function (label) {
                flat[schema + ':' + label] = labels[label];
            });
        });
        return flat;
    }

    function commitCard() {
        var item = currentItem();
        if (!item || !answersComplete()) return;
        var record = {
            instance_id: item.instance_id,
            annotations: flatAnnotations(),
            ts: Date.now(),
            response_time_seconds: shownForSeconds()
        };
        var queue = loadQueue();
        queue.push(record);
        saveQueue(queue);
        flushQueue();
        haptic();
        advance();
    }

    function advance() {
        var card = main.querySelector('.pk-card');
        var go = function () {
            state.idx += 1;
            state.answers = {};
            localStorage.setItem(ITEMS_KEY, JSON.stringify({
                items: state.items.slice(state.idx), total: state.total,
                done: state.done + state.idx
            }));
            if (state.idx >= state.items.length) renderDone(); else renderCard();
        };
        if (card && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
            card.classList.add('pk-out-left');
            setTimeout(go, 150);
        } else {
            go();
        }
    }

    function goBack() {
        if (state.idx === 0) return;
        state.idx -= 1;
        state.answers = {};
        renderCard();
    }

    // ------------------------------------------------------------- renders --
    function renderMessage(html) {
        main.innerHTML = '<div class="pk-message">' + html + '</div>';
    }

    /** True while the end-of-batch screen is counting unsent saves. */
    var showingPendingDone = false;

    function renderDone() {
        renderProgress();
        var queue = loadQueue();
        showingPendingDone = queue.length > 0;
        if (queue.length) {
            // "Every item in your queue is annotated" is the sentence someone
            // reads before closing the tab, and it was shown with unsent saves
            // sitting in localStorage -- with the header still reading "4 of
            // 6", because a batch smaller than the study is the ordinary case.
            // Claiming completion over a non-empty queue is the part that was
            // wrong; the batch itself is fine.
            var n = queue.length + ' answer' + (queue.length === 1 ? '' : 's');
            main.innerHTML =
                '<div class="pk-done pk-done-pending">' +
                '  <div class="pk-done-mark">&#8635;</div>' +
                '  <div class="pk-done-title">' + n + ' still to send</div>' +
                '  <div class="pk-done-sub">Saved on this device. ' +
                (signedOut
                    ? 'Sign in again and they will go up.'
                    : 'They will go up as soon as the server answers.') +
                '<br>Leave this page open, or come back to it later — nothing is lost.</div>' +
                '  <button type="button" class="pk-retry" id="pk-retry">Try now</button>' +
                '</div>';
            var retry = document.getElementById('pk-retry');
            if (retry) retry.addEventListener('click', retryQueue);
            flushQueue();
            return;
        }
        main.innerHTML =
            '<div class="pk-done">' +
            '  <div class="pk-done-mark">&#10003;</div>' +
            '  <div class="pk-done-title">All caught up</div>' +
            '  <div class="pk-done-sub">Every item in your queue is annotated.<br>' +
            '  Pull down to refresh, or come back when new items arrive.</div>' +
            '</div>';
    }

    /** What a scale point is called out loud: bare numbers say nothing. */
    function ariaForPoint(scheme, n, size) {
        if (n === 1 && scheme.min_label) return n + ' — ' + scheme.min_label;
        if (n === size && scheme.max_label) return n + ' — ' + scheme.max_label;
        return String(n);
    }

    function schemeControls(scheme) {
        var type = scheme.annotation_type;
        var host = document.createElement('div');
        host.className = 'pk-scheme';
        if (scheme.description) {
            host.innerHTML = '<div class="pk-scheme-title">' + esc(scheme.description) + '</div>';
        }

        function setAnswer(labels, exclusive) {
            state.answers[scheme.name] = labels;
            updateNextButton();
        }

        if (type === 'radio' || (type === 'likert' && scheme.labels.length)) {
            var wrap = document.createElement('div');
            wrap.className = type === 'likert' ? 'pk-likert' : 'pk-options' +
                (scheme.labels.length > 4 ? ' pk-grid-2' : '');
            scheme.labels.forEach(function (label) {
                var btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'pk-opt';
                btn.innerHTML = '<span class="pk-check">&#10003;</span>' + esc(label);
                btn.addEventListener('click', function () {
                    wrap.querySelectorAll('.pk-opt').forEach(function (b) {
                        b.classList.remove('selected');
                    });
                    btn.classList.add('selected');
                    var labels = {};
                    // "on" is what a checked radio posts, and so what the
                    // annotation page stores. The label is already carried by
                    // the key; writing it in the value too left the same
                    // answer spelled two ways in one exported column.
                    labels[label] = 'on';
                    setAnswer(labels, true);
                    haptic();
                    maybeAutoCommit();
                });
                wrap.appendChild(btn);
            });
            host.appendChild(wrap);
        } else if (type === 'likert') {
            // size-based likert: numbered segments between the two anchors.
            var size = parseInt(scheme.size, 10) || 5;
            var scale = document.createElement('div');
            scale.className = 'pk-likert-scale';
            var row = document.createElement('div');
            row.className = 'pk-likert';
            for (var i = 1; i <= size; i++) {
                (function (n) {
                    var btn = document.createElement('button');
                    btn.type = 'button';
                    btn.className = 'pk-opt';
                    btn.textContent = n;
                    btn.setAttribute('aria-label', ariaForPoint(scheme, n, size));
                    btn.addEventListener('click', function () {
                        row.querySelectorAll('.pk-opt').forEach(function (b) {
                            b.classList.remove('selected');
                            b.setAttribute('aria-pressed', 'false');
                        });
                        btn.classList.add('selected');
                        btn.setAttribute('aria-pressed', 'true');
                        var labels = {};
                        // The scale point IS the label name, which is what
                        // likert.py writes on the desktop page. This used to
                        // send `scale_3`, so the same answer from two
                        // annotators on two surfaces was two different labels
                        // and they read as having answered different questions.
                        labels[String(n)] = String(n);
                        setAnswer(labels, true);
                        haptic();
                        maybeAutoCommit();
                    });
                    btn.setAttribute('aria-pressed', 'false');
                    row.appendChild(btn);
                })(i);
            }
            // Potato requires min_label and max_label on every likert, so if
            // they are missing the config never validated and the anchors are
            // simply absent rather than empty.
            if (scheme.min_label || scheme.max_label) {
                // `.pk-likert-legend` was already in pocket.css, styled for
                // exactly this and emitted by nothing -- the anchors were
                // designed in and then never rendered.
                var legend = document.createElement('div');
                legend.className = 'pk-likert-legend';
                legend.innerHTML =
                    '<span>' + esc(scheme.min_label || '') + '</span>' +
                    '<span>' + esc(scheme.max_label || '') + '</span>';
                scale.appendChild(row);
                scale.appendChild(legend);
                host.appendChild(scale);
            } else {
                host.appendChild(row);
            }
        } else if (type === 'multiselect') {
            var grid = document.createElement('div');
            grid.className = 'pk-options' + (scheme.labels.length > 4 ? ' pk-grid-2' : '');
            var selected = {};
            scheme.labels.forEach(function (label) {
                var btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'pk-opt';
                btn.innerHTML = '<span class="pk-check">&#10003;</span>' + esc(label);
                btn.addEventListener('click', function () {
                    if (selected[label]) {
                        delete selected[label];
                        btn.classList.remove('selected');
                    } else {
                        selected[label] = 'on';   // as a ticked checkbox posts
                        btn.classList.add('selected');
                    }
                    setAnswer(Object.assign({}, selected));
                    haptic();
                });
                grid.appendChild(btn);
            });
            host.appendChild(grid);
        } else if (type === 'slider' || type === 'number') {
            var min = scheme.min != null ? scheme.min : 0;
            var max = scheme.max != null ? scheme.max : 100;
            var row2 = document.createElement('div');
            row2.className = 'pk-slider-row';
            row2.innerHTML =
                '<input type="range" class="pk-slider" min="' + min + '" max="' + max +
                '" value="' + Math.round((Number(min) + Number(max)) / 2) +
                '" aria-label="' + esc(scheme.description || scheme.name) + '">' +
                '<output class="pk-slider-value"></output>';
            var slider = row2.querySelector('.pk-slider');
            var output = row2.querySelector('.pk-slider-value');
            output.textContent = slider.value;
            slider.addEventListener('input', function () {
                output.textContent = slider.value;
                var labels = {};
                labels['slider'] = slider.value;
                setAnswer(labels);
            });
            host.appendChild(row2);
        } else if (type === 'text' || type === 'textbox') {
            var labels = scheme.labels.length ? scheme.labels : ['text_box'];
            labels.forEach(function (label) {
                var area = document.createElement('textarea');
                area.className = 'pk-textarea';
                area.placeholder = labels.length > 1 ? label : 'Type your answer…';
                area.setAttribute('aria-label', label);
                area.addEventListener('input', function () {
                    var current = state.answers[scheme.name] || {};
                    if (area.value.trim()) current[label] = area.value;
                    else delete current[label];
                    setAnswer(current);
                });
                host.appendChild(area);
            });
        }
        return host;
    }

    /** Single radio/likert scheme -> selecting is the whole job: auto-commit. */
    function maybeAutoCommit() {
        var interactive = state.task.schemas.filter(function (s) {
            return s.annotation_type !== 'pure_display';
        });
        var fastTypes = ['radio', 'likert'];
        if (interactive.length === 1 &&
            fastTypes.indexOf(interactive[0].annotation_type) !== -1) {
            setTimeout(commitCard, 220); // let the selection state paint first
        } else {
            updateNextButton();
        }
    }

    function updateNextButton() {
        var next = document.getElementById('pk-next');
        if (next) next.disabled = !answersComplete();
    }

    /**
     * When the current card went on screen. `attention_checks.min_response_time`
     * is measured from this to the save, so it has to be stamped where the card
     * is drawn and nowhere else -- deriving it from the save time would measure
     * network latency, which is the mistake the annotation page already made
     * once.
     */
    var shownAt = null;

    function shownForSeconds() {
        return shownAt == null ? null : (Date.now() - shownAt) / 1000;
    }

    function renderCard() {
        var item = currentItem();
        if (!item) { renderDone(); return; }
        renderProgress();
        showingPendingDone = false;
        shownAt = Date.now();

        var card = document.createElement('div');
        card.className = 'pk-card';
        card.innerHTML =
            '<div class="pk-text">' + esc(item.text) + '</div>' +
            '<div class="pk-swipe-hint">swipe to navigate</div>' +
            '<div class="pk-controls"></div>' +
            '<div class="pk-actions">' +
            '  <button type="button" class="pk-nav" id="pk-prev" aria-label="Previous item">&#8592;</button>' +
            '  <button type="button" class="pk-next" id="pk-next" disabled>Save &amp; next</button>' +
            '  <button type="button" class="pk-nav" id="pk-skip" aria-label="Skip item">&#8594;</button>' +
            '</div>';

        var controls = card.querySelector('.pk-controls');
        state.task.schemas.forEach(function (scheme) {
            if (scheme.annotation_type === 'pure_display') return;
            controls.appendChild(schemeControls(scheme));
        });

        main.innerHTML = '';
        main.appendChild(card);

        document.getElementById('pk-prev').disabled = state.idx === 0;
        document.getElementById('pk-prev').addEventListener('click', goBack);
        document.getElementById('pk-skip').addEventListener('click', advance);
        document.getElementById('pk-next').addEventListener('click', commitCard);
        updateNextButton();
    }

    // --------------------------------------------------------------- swipe --
    main.addEventListener('touchstart', function (e) {
        if (e.touches.length === 1) state.touchStartX = e.touches[0].clientX;
    }, { passive: true });
    main.addEventListener('touchend', function (e) {
        if (state.touchStartX == null) return;
        var dx = e.changedTouches[0].clientX - state.touchStartX;
        state.touchStartX = null;
        if (Math.abs(dx) < 70) return;
        if (dx < 0) advance(); else goBack();
    }, { passive: true });

    // ---------------------------------------------------------------- boot --
    function boot() {
        fetchTask().then(function (task) {
            state.task = task;
            if (!task.capable) {
                renderMessage(
                    '<strong>This task isn&rsquo;t phone-sized.</strong>' +
                    '<span>The scheme' + (task.incompatible_schemes.length > 1 ? 's' : '') +
                    ' <em>' + task.incompatible_schemes.map(esc).join(', ') +
                    '</em> need' + (task.incompatible_schemes.length > 1 ? '' : 's') +
                    ' a desktop. Open the regular interface at <code>/annotate</code>.</span>');
                return;
            }
            return fetchBatch().then(function (batch) {
                state.items = batch.items;
                state.total = batch.total;
                state.done = batch.done;
                state.idx = 0;
                localStorage.setItem(ITEMS_KEY, JSON.stringify(batch));
                if (state.items.length) renderCard(); else renderDone();
            });
        }).catch(function () {
            // Offline boot: fall back to the cached batch
            var cached = null;
            try { cached = JSON.parse(localStorage.getItem(ITEMS_KEY)); } catch (e) { }
            if (cached && cached.items && cached.items.length && state.task) {
                state.items = cached.items;
                state.total = cached.total;
                state.done = cached.done;
                renderCard();
            } else {
                renderMessage('<strong>Couldn&rsquo;t load your queue.</strong>' +
                    '<span>Check your connection (or log in at <code>/login</code>) and retry.</span>');
            }
        });
        flushQueue();
        renderSyncChip();
    }

    window.addEventListener('online', retryQueue);
    window.addEventListener('offline', function () { renderSyncChip(); });

    // A phone that keeps its network and loses the SERVER -- a restart, a
    // deploy, a proxy blip -- never fires `online`. With a successful save the
    // only other trigger, an annotator who has reached the end of their batch
    // has nothing left to piggyback on either, so the queue had no way back
    // without a reload. Two more triggers, both cheap:
    //
    //   visibilitychange, because coming back to the tab is exactly when
    //   someone expects it to catch up; and a slow timer, because the outage
    //   may heal while the tab is in front of them.
    //
    // Neither retries a refusal: `flushQueue` leaves `signedOut` set and the
    // chip keeps saying so until the annotator signs in.
    document.addEventListener('visibilitychange', function () {
        if (document.visibilityState === 'visible') flushQueue();
    });

    var FLUSH_INTERVAL_MS = 30000;
    setInterval(function () {
        if (loadQueue().length && navigator.onLine && !signedOut) flushQueue();
    }, FLUSH_INTERVAL_MS);

    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/pocket/sw.js').catch(function () {
            /* PWA is progressive enhancement */
        });
    }

    boot();
})();

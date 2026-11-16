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
    // The task description (schemes, capability), kept so Pocket can start
    // with no connection. Without it the offline fallback in boot() never ran:
    // it needed the task, and the task only arrived from the request that had
    // just failed. Stored without prior_answers, which are the participant's
    // own words and are not kept on the device.
    var TASK_KEY = 'pocket_task_v1';

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

    /**
     * The participant's own earlier survey answers (config `prior_answers`),
     * the same boxes /annotate shows above its forms. They come from
     * /pocket/api/task rather than the page, which the service worker caches
     * for every account on the device. Built with textContent only: the
     * answers are participant text and arrive unescaped.
     */
    function renderPriorAnswers(blocks) {
        var host = document.getElementById('pk-prior-answers');
        if (!host) return;
        host.textContent = '';
        blocks.forEach(function (block) {
            var box = document.createElement(block.collapsible ? 'details' : 'section');
            box.className = 'prior-answer-block';
            box.setAttribute('data-prior-answer-schema', block.schema || '');
            if (block.collapsible && block.open) box.open = true;
            var title = document.createElement(block.collapsible ? 'summary' : 'div');
            if (!block.collapsible) title.className = 'prior-answer-title';
            title.textContent = block.title || '';
            var content = document.createElement('div');
            content.className = 'prior-answer-content';
            content.textContent = (block.lines || []).join('\n');
            box.appendChild(title);
            box.appendChild(content);
            host.appendChild(box);
        });
        host.hidden = !blocks.length;
    }

    function haptic() {
        if (navigator.vibrate) navigator.vibrate(12);
    }

    // ------------------------------------------------------------ storage --
    function loadQueue() {
        try { return JSON.parse(localStorage.getItem(QUEUE_KEY)) || []; }
        catch (e) { return []; }
    }

    /**
     * Whose saves these are. The queue is one list per device, and a record
     * used to carry no account: when one person queued saves offline and
     * someone else signed in on the same phone, the next flush posted the
     * first person's answers under the second person's session.
     *
     * Records now carry the account Pocket last heard from the server, and a
     * flush posts only the records of `confirmedUser`, the account that
     * /pocket/api/task answered for in this page. The task kept for offline
     * starts names an account too, but nothing on the device can check it
     * against the session cookie, so it labels new records and is never
     * trusted to send them. A record from before this field is the old
     * behaviour: it goes with whoever is signed in, and so does every record
     * when the server names no account.
     *
     * `userChecked` is kept apart from the name so that a task without one
     * ends the check instead of starting it again on every flush.
     */
    var confirmedUser = null;
    var userChecked = false;

    /**
     * The account signed in on this phone, from the readable `pocket_user`
     * cookie the server keeps equal to the session (the session cookie itself
     * is HttpOnly). Null once signed out. Readable offline, which is the
     * point: it is how an offline start knows whose batch it may open.
     */
    function signedInAccount() {
        var m = String(document.cookie || '').match(/(?:^|;\s*)pocket_user=([^;]*)/);
        if (!m) return null;
        try { return decodeURIComponent(m[1]) || null; } catch (e) { return null; }
    }

    function queueOwner() {
        if (userChecked) return confirmedUser;
        return signedInAccount() || (state.task && state.task.username) || null;
    }

    function confirmUser(task) {
        confirmedUser = task.username || null;
        userChecked = true;
    }

    function isMine(record) {
        var owner = queueOwner();
        return !record.user || !owner || record.user === owner;
    }

    function myQueue() { return loadQueue().filter(isMine); }

    function saveQueue(queue) {
        localStorage.setItem(QUEUE_KEY, JSON.stringify(queue));
        renderSyncChip();
    }

    // -------------------------------------------------------------- server --
    function fetchTask() {
        return fetch('/pocket/api/task').then(function (r) {
            if (r.status === 401 || r.status === 403) throw authError(r.status);
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
        }).then(function (task) {
            var stored = {};
            Object.keys(task).forEach(function (k) {
                if (k !== 'prior_answers') stored[k] = task[k];
            });
            try { localStorage.setItem(TASK_KEY, JSON.stringify(stored)); } catch (e) { }
            return task;
        }, function (err) {
            // fetch() rejects with a TypeError when there is no network; an
            // HTTP error arrives as a response and was thrown above.
            if (err instanceof TypeError) err.offline = true;
            throw err;
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

    var confirming = false;

    /** Ask the server who is signed in, then send that account's saves. */
    function confirmUserThenFlush() {
        if (confirming) return;
        confirming = true;
        fetchTask().then(function (task) {
            confirming = false;
            confirmUser(task);
            if (!state.task) state.task = task;
            flushQueue();
        }, function (err) {
            confirming = false;
            if (err && err.needsLogin) signedOut = true;
            renderSyncChip();
        });
    }

    function flushQueue() {
        if (!navigator.onLine || !loadQueue().length) { renderSyncChip(); return; }
        if (!userChecked) { confirmUserThenFlush(); return; }
        var queue = myQueue();
        if (!queue.length) { renderSyncChip(); return; }
        var record = queue[0];
        postSave(record).then(function () {
            signedOut = false;
            var rest = loadQueue().filter(function (q) {
                return !(q.instance_id === record.instance_id && q.ts === record.ts);
            });
            saveQueue(rest);
            if (rest.some(isMine)) {
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
    var othersNoticeUntil = 0;   // the notice below shows for 5 s per page

    function renderSyncChip(justSynced) {
        var chip = document.getElementById('pk-sync');
        var queue = myQueue();
        var others = loadQueue().length - queue.length;
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
            setTimeout(function () { renderSyncChip(); }, 2200);
        } else if (others && (!othersNoticeUntil || Date.now() < othersNoticeUntil)) {
            // Someone else's unsent answers. They stay on the phone and go up
            // when that account signs in here; saying nothing would leave
            // them invisible to everyone who could act on it. Said once per
            // page and then hidden: the chip floats over the answer options,
            // and this person has nothing to do about it.
            if (!othersNoticeUntil) {
                othersNoticeUntil = Date.now() + 5000;
                // Re-render rather than hide: by then the chip may be saying
                // something else, such as this person's own queued saves.
                setTimeout(function () { renderSyncChip(); }, 5050);
            }
            chip.hidden = false;
            chip.classList.remove('pk-ok', 'pk-blocked');
            chip.textContent = others + ' save' + (others === 1 ? '' : 's') +
                ' from another account on this phone, sent when it signs in here';
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
        // The card is already on its way out: a second tap is not an answer.
        if (advancing) return;
        var item = currentItem();
        if (!item || !answersComplete()) return;
        var record = {
            user: queueOwner(),
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

    /** True from an advance until the next card is up: a double tap or a
     * key repeat within the card's exit animation skipped an item unsaved. */
    var advancing = false;

    function advance() {
        if (advancing) return;
        advancing = true;
        var card = main.querySelector('.pk-card');
        var go = function () {
            advancing = false;
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
        var queue = myQueue();
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
        // The end of a batch is not the end of the work: ask the server once
        // (every save has gone up by now) before saying so. A labeling-engine
        // study hands out requests a batch at a time, and the phone said "All
        // caught up" after 3 cards with 168 requests open.
        if (navigator.onLine && !refetchedForBatch) {
            refetchedForBatch = true;
            fetchBatch().then(function (batch) {
                if (batch.items && batch.items.length) {
                    state.items = batch.items;
                    state.total = batch.total;
                    state.done = batch.done;
                    state.idx = 0;
                    refetchedForBatch = false;
                    localStorage.setItem(ITEMS_KEY, JSON.stringify(batch));
                    renderCard();
                } else {
                    showCaughtUp();
                }
            }).catch(showCaughtUp);
            return;
        }
        showCaughtUp();
    }

    /** Whether renderDone has already asked for more since the last batch
     * with cards in it, so an empty answer is not asked for again in a loop. */
    var refetchedForBatch = false;

    function showCaughtUp() {
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
            (item.note ? '<div class="pk-note" role="note">' + esc(item.note) + '</div>' : '') +
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
            confirmUser(task);
            flushQueue();
            renderPriorAnswers(task.prior_answers || []);
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
                refetchedForBatch = !batch.items.length;
                state.items = batch.items;
                state.total = batch.total;
                state.done = batch.done;
                state.idx = 0;
                localStorage.setItem(ITEMS_KEY, JSON.stringify(batch));
                if (state.items.length) renderCard(); else renderDone();
            });
        }).catch(function (err) {
            // Offline boot: fall back to the cached task and batch. Only when
            // the network failed -- a server that answered "sign in" must not
            // be worked around with the last account's queue.
            var cached = null, task = state.task;
            try { cached = JSON.parse(localStorage.getItem(ITEMS_KEY)); } catch (e) { }
            if (!task && err && err.offline) {
                try { task = JSON.parse(localStorage.getItem(TASK_KEY)); } catch (e) { }
            }
            // The stored task and batch belong to the account that last
            // loaded them, which need not be who is signed in now: the phone
            // may have signed out, or someone else may have signed in through
            // the desktop page. They open only for that same account.
            var account = signedInAccount();
            var sameAccount = !!(account && task && (!task.username || task.username === account));
            if ((err && err.needsLogin) || (err && err.offline && !account)) {
                signedOut = true;
                renderMessage('<strong>You&rsquo;re signed out.</strong>' +
                    '<span><a href="/login">Sign in again</a> to load your queue.</span>');
            } else if (sameAccount && cached && cached.items && cached.items.length && task.capable) {
                state.task = task;
                state.items = cached.items;
                state.total = cached.total;
                state.done = cached.done;
                state.idx = 0;
                renderCard();
            } else {
                renderMessage('<strong>Couldn&rsquo;t load your queue.</strong>' +
                    '<span>Check your connection (or log in at <code>/login</code>) and retry.</span>');
            }
        });
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
        // scope '/pocket', not the default '/pocket/': the page is /pocket,
        // and a worker scoped to the directory never controlled it.
        navigator.serviceWorker.register('/pocket/sw.js', { scope: '/pocket' }).catch(function () {
            /* PWA is progressive enhancement */
        });
    }

    boot();
})();

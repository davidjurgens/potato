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

    /** Same payload shape annotation.js sends. */
    function postSave(record) {
        return fetch('/updateinstance', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                instance_id: record.instance_id,
                annotations: record.annotations,
                span_annotations: []
            })
        }).then(function (r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
        }).then(function (data) {
            if (data && data.status === 'error') throw new Error(data.message);
            return data;
        });
    }

    function flushQueue() {
        var queue = loadQueue();
        if (!queue.length || !navigator.onLine) { renderSyncChip(); return; }
        var record = queue[0];
        postSave(record).then(function () {
            var rest = loadQueue().filter(function (q) {
                return !(q.instance_id === record.instance_id && q.ts === record.ts);
            });
            saveQueue(rest);
            if (rest.length) flushQueue(); else renderSyncChip(true);
        }).catch(function () {
            renderSyncChip(); // stays queued; retried on next flush
        });
    }

    // ---------------------------------------------------------------- sync --
    function renderSyncChip(justSynced) {
        var chip = document.getElementById('pk-sync');
        var queue = loadQueue();
        if (queue.length) {
            chip.hidden = false;
            chip.classList.remove('pk-ok');
            chip.textContent = navigator.onLine
                ? 'Syncing ' + queue.length + ' save' + (queue.length === 1 ? '' : 's') + '…'
                : 'Offline — ' + queue.length + ' save' + (queue.length === 1 ? '' : 's') + ' queued';
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
            ts: Date.now()
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

    function renderDone() {
        renderProgress();
        main.innerHTML =
            '<div class="pk-done">' +
            '  <div class="pk-done-mark">&#10003;</div>' +
            '  <div class="pk-done-title">All caught up</div>' +
            '  <div class="pk-done-sub">Every item in your queue is annotated.<br>' +
            '  Pull down to refresh, or come back when new items arrive.</div>' +
            '</div>';
        var queue = loadQueue();
        if (queue.length) flushQueue();
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
                    labels[label] = label;
                    setAnswer(labels, true);
                    haptic();
                    maybeAutoCommit();
                });
                wrap.appendChild(btn);
            });
            host.appendChild(wrap);
        } else if (type === 'likert') {
            // size-based likert: numbered segments
            var size = parseInt(scheme.size, 10) || 5;
            var row = document.createElement('div');
            row.className = 'pk-likert';
            for (var i = 1; i <= size; i++) {
                (function (n) {
                    var btn = document.createElement('button');
                    btn.type = 'button';
                    btn.className = 'pk-opt';
                    btn.textContent = n;
                    btn.addEventListener('click', function () {
                        row.querySelectorAll('.pk-opt').forEach(function (b) {
                            b.classList.remove('selected');
                        });
                        btn.classList.add('selected');
                        var labels = {};
                        labels['scale_' + n] = String(n);
                        setAnswer(labels, true);
                        haptic();
                        maybeAutoCommit();
                    });
                    row.appendChild(btn);
                })(i);
            }
            host.appendChild(row);
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
                        selected[label] = 'true';
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

    function renderCard() {
        var item = currentItem();
        if (!item) { renderDone(); return; }
        renderProgress();

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

    window.addEventListener('online', flushQueue);
    window.addEventListener('offline', function () { renderSyncChip(); });

    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/pocket/sw.js').catch(function () {
            /* PWA is progressive enhancement */
        });
    }

    boot();
})();

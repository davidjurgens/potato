/*
 * The runtime-independent half of a runtime phase page (jsPsych, OSWeb,
 * PsychoJS, ...): reads the page's config, saves trials and the finished run
 * to the server, shows the saving / retry status, and exposes `window.potato`
 * to the author's study.
 *
 * A boot script (static/runtime-boot-<kind>.js) loads after this file and
 * calls `potatoRuntime.onStart(fn)` with the function that starts its
 * runtime. The bridge calls it on DOMContentLoaded, after every synchronous
 * script (runtime files, extra scripts, the study file) has run. The boot
 * script reports data with `potatoRuntime.trial(data)` and
 * `potatoRuntime.finish(trials, interaction)`, and a study that cannot start
 * with `potatoRuntime.fail(message)`.
 */
(function () {
    'use strict';

    var configEl = document.getElementById('potato-runtime-config');
    if (!configEl) { return; }
    var cfg = JSON.parse(configEl.textContent);

    var statusEl = document.getElementById('potato-runtime-status');
    var statusText = document.getElementById('potato-runtime-status-text');
    var retryBtn = document.getElementById('potato-runtime-retry');

    var finishing = false;
    var seq = 0;
    var starter = null;
    var aborter = null;
    var collector = null;
    var TAG = '[potato-' + cfg.kind + ']';

    function showStatus(message, canRetry) {
        statusText.textContent = message;
        statusEl.hidden = false;
        retryBtn.hidden = !canRetry;
        if (canRetry) { retryBtn.focus(); }
    }

    function post(url, body) {
        return fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                // Forces a CORS preflight, so another site cannot post here
                // with the participant's cookie.
                'X-Potato-Navigation': '1'
            },
            body: JSON.stringify(body),
            keepalive: body && body.trial !== undefined
        });
    }

    function attempt(body, tries) {
        post(cfg.endpoints.finish, body).then(function (response) {
            return response.json().catch(function () { return {}; }).then(function (json) {
                if (response.ok && json.redirect) {
                    window.location.replace(json.redirect);
                    return;
                }
                if (response.status === 409) {
                    showStatus(json.message || 'This page is out of date. Reload to continue.', false);
                    return;
                }
                throw new Error(json.message || ('HTTP ' + response.status));
            });
        }).catch(function (err) {
            if (tries < 2) {
                setTimeout(function () { attempt(body, tries + 1); }, 1000 * (tries + 1));
                return;
            }
            console.error(TAG, 'could not save run', err);
            showStatus('Your responses could not be saved. Check your connection, ' +
                       'then try again. Do not close this page.', true);
            retryBtn.onclick = function () {
                showStatus('Saving your responses…', false);
                attempt(body, 0);
            };
        });
    }

    function plain(list) {
        // Runtimes hand back class instances and typed arrays; the server
        // stores JSON objects.
        return (list || []).map(function (item) {
            return (item && typeof item === 'object') ? JSON.parse(JSON.stringify(item)) : {value: item};
        });
    }

    function finish(trials, interaction) {
        if (finishing) { return; }
        finishing = true;
        var body = {page: cfg.page, run_id: cfg.run_id, trials: plain(trials),
                    interaction: plain(interaction)};
        var size = JSON.stringify(body).length;
        if (cfg.max_bytes && size > cfg.max_bytes) {
            showStatus('This task produced more data than the study allows (' +
                       Math.round(size / 1048576) + ' MB). Please contact the researcher.', false);
            return;
        }
        showStatus('Saving your responses…', false);
        attempt(body, 0);
    }

    function trial(data) {
        if (cfg.save !== 'incremental' || finishing) { return; }
        var n = seq++;
        post(cfg.endpoints.trial, {page: cfg.page, run_id: cfg.run_id, seq: n,
                                   trial: plain([data])[0]})
            .catch(function (err) { console.warn(TAG, 'trial save failed', err); });
    }

    function fail(message, detail) {
        if (detail !== undefined) { console.error(TAG, message, detail); }
        showStatus('This task could not start: ' + message + ' Please contact the researcher.', false);
    }

    var conditionColumns = {};
    Object.keys(cfg.conditions || {}).forEach(function (factor) {
        conditionColumns['condition_' + factor] = cfg.conditions[factor];
    });

    window.potatoRuntime = {
        config: cfg,
        /* Columns every trial carries: participant, page, run, conditions. */
        properties: Object.assign({
            potato_user: cfg.participant,
            potato_page: cfg.page,
            potato_run_id: cfg.run_id,
            potato_attempt: cfg.attempt
        }, conditionColumns),
        onStart: function (fn) { starter = fn; },
        /* Called by window.potato.finish() to stop the runtime first. */
        onAbort: function (fn) { aborter = fn; },
        /* Returns [trials, interaction] for an early finish. */
        onCollect: function (fn) { collector = fn; },
        trial: trial,
        finish: finish,
        fail: fail,
        status: showStatus,
        /* URL of a file in the page's assets_dir. */
        asset: function (path) { return cfg.endpoints.assets + String(path).replace(/^\/+/, ''); }
    };

    window.potato = {
        participant: cfg.participant,
        page: cfg.page,
        runId: cfg.run_id,
        attempt: cfg.attempt,
        conditions: cfg.conditions || {},
        answers: cfg.answers || {},
        asset: window.potatoRuntime.asset,
        /* End the task now and save what has been collected. */
        finish: function () {
            if (aborter) {
                try { aborter(); } catch (err) { console.warn(TAG, 'abort failed', err); }
            }
            var got = collector ? collector() : [[], []];
            finish(got[0], got[1]);
        }
    };

    document.addEventListener('DOMContentLoaded', function () {
        if (!starter) {
            fail('its runtime did not load.');
            return;
        }
        try {
            starter();
        } catch (err) {
            fail('its script raised an error.', err);
        }
    });
})();

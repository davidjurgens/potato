/*
 * Runs an author's jsPsych timeline inside a Potato phase page and hands the
 * data back to the server.
 *
 * The timeline file assigns `window.potatoTimeline`, either an array of
 * trials or a function `(jsPsych, potato) => timeline`. `potato` carries the
 * participant id, their between-subjects conditions, any survey answers the
 * config exposes, and `finish()` for a timeline that ends itself early.
 *
 * Loaded before the timeline so `window.potato` exists while the timeline
 * file is evaluated; the run starts on DOMContentLoaded, after every
 * synchronous script (plugins, extra scripts, timeline) has run.
 */
(function () {
    'use strict';

    var configEl = document.getElementById('potato-jspsych-config');
    if (!configEl) { return; }
    var cfg = JSON.parse(configEl.textContent);

    var statusEl = document.getElementById('potato-jspsych-status');
    var statusText = document.getElementById('potato-jspsych-status-text');
    var retryBtn = document.getElementById('potato-jspsych-retry');

    var jsPsych = null;
    var finishing = false;
    var seq = 0;

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

    function collect() {
        return {
            page: cfg.page,
            run_id: cfg.run_id,
            trials: jsPsych ? jsPsych.data.get().values() : [],
            interaction: jsPsych ? jsPsych.data.getInteractionData().values() : []
        };
    }

    function sendFinish() {
        if (finishing) { return; }
        finishing = true;
        var body = collect();
        var size = JSON.stringify(body).length;
        if (cfg.max_bytes && size > cfg.max_bytes) {
            showStatus('This task produced more data than the study allows (' +
                       Math.round(size / 1048576) + ' MB). Please contact the researcher.', false);
            return;
        }
        showStatus('Saving your responses…', false);
        attempt(body, 0);
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
            console.error('[potato-jspsych] could not save run', err);
            showStatus('Your responses could not be saved. Check your connection, ' +
                       'then try again. Do not close this page.', true);
            retryBtn.onclick = function () {
                showStatus('Saving your responses…', false);
                attempt(body, 0);
            };
        });
    }

    function onTrial(data) {
        if (cfg.save !== 'incremental') { return; }
        var n = seq++;
        post(cfg.endpoints.trial, {page: cfg.page, run_id: cfg.run_id, seq: n, trial: data})
            .catch(function (err) { console.warn('[potato-jspsych] trial save failed', err); });
    }

    var conditionColumns = {};
    Object.keys(cfg.conditions || {}).forEach(function (factor) {
        conditionColumns['condition_' + factor] = cfg.conditions[factor];
    });

    window.potato = {
        participant: cfg.participant,
        page: cfg.page,
        runId: cfg.run_id,
        attempt: cfg.attempt,
        conditions: cfg.conditions || {},
        answers: cfg.answers || {},
        /* URL of a file in the page's assets_dir. */
        asset: function (path) { return cfg.endpoints.assets + String(path).replace(/^\/+/, ''); },
        /* End the task now and save what has been collected. */
        finish: function () {
            if (jsPsych) { jsPsych.abortExperiment(); }
            sendFinish();
        }
    };

    function start() {
        var source = window.potatoTimeline;
        if (!source) {
            showStatus('This task could not start: its script did not define ' +
                       'window.potatoTimeline. Please contact the researcher.', false);
            console.error('[potato-jspsych] window.potatoTimeline is not defined');
            return;
        }
        if (typeof initJsPsych !== 'function') {
            showStatus('This task could not start: jsPsych did not load.', false);
            return;
        }
        jsPsych = initJsPsych({
            display_element: 'jspsych-target',
            on_data_update: onTrial,
            on_finish: sendFinish
        });
        jsPsych.data.addProperties(Object.assign({
            potato_user: cfg.participant,
            potato_page: cfg.page,
            potato_run_id: cfg.run_id,
            potato_attempt: cfg.attempt
        }, conditionColumns));
        var timeline;
        try {
            timeline = typeof source === 'function' ? source(jsPsych, window.potato) : source;
        } catch (err) {
            console.error('[potato-jspsych] building the timeline failed', err);
            showStatus('This task could not start because of an error in its script. ' +
                       'Please contact the researcher.', false);
            return;
        }
        if (!Array.isArray(timeline)) {
            showStatus('This task could not start: window.potatoTimeline must be an ' +
                       'array of trials, or a function that returns one. Please contact ' +
                       'the researcher.', false);
            console.error('[potato-jspsych] timeline is not an array:', timeline);
            return;
        }
        if (timeline.length === 0) {
            showStatus('This task could not start: its timeline is empty. Please ' +
                       'contact the researcher.', false);
            return;
        }
        jsPsych.run(timeline);
    }

    document.addEventListener('DOMContentLoaded', start);
})();

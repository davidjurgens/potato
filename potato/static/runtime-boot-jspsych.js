/*
 * Starts an author's jsPsych timeline on a runtime phase page.
 *
 * The timeline file assigns `window.potatoTimeline`, either an array of
 * trials or a function `(jsPsych, potato) => timeline`. `potato` carries the
 * participant id, their between-subjects conditions, any survey answers the
 * config exposes, and `finish()` for a timeline that ends itself early.
 */
(function () {
    'use strict';
    var rt = window.potatoRuntime;
    if (!rt) { return; }
    var cfg = rt.config;
    var jsPsych = null;

    function collect() {
        return [jsPsych ? jsPsych.data.get().values() : [],
                jsPsych ? jsPsych.data.getInteractionData().values() : []];
    }

    rt.onCollect(collect);
    rt.onAbort(function () { if (jsPsych) { jsPsych.abortExperiment(); } });

    rt.onStart(function () {
        var source = window.potatoTimeline;
        if (!source) {
            rt.fail('its script did not define window.potatoTimeline.');
            return;
        }
        if (typeof initJsPsych !== 'function') {
            rt.fail('jsPsych did not load.');
            return;
        }
        var extensions = ((cfg.runtime || {}).extensions || []).map(function (ext) {
            return {type: window[ext.global]};
        }).filter(function (ext) { return ext.type; });
        jsPsych = initJsPsych({
            display_element: 'runtime-target',
            extensions: extensions,
            on_data_update: rt.trial,
            on_finish: function () {
                var got = collect();
                rt.finish(got[0], got[1]);
            }
        });
        jsPsych.data.addProperties(rt.properties);
        var timeline;
        try {
            timeline = typeof source === 'function' ? source(jsPsych, window.potato) : source;
        } catch (err) {
            rt.fail('building its timeline raised an error.', err);
            return;
        }
        if (!Array.isArray(timeline)) {
            rt.fail('window.potatoTimeline must be an array of trials, or a function ' +
                    'that returns one.', timeline);
            return;
        }
        if (timeline.length === 0) {
            rt.fail('its timeline is empty.');
            return;
        }
        jsPsych.run(timeline);
    });
})();

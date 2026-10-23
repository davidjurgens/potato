/*
 * A short Stroop task, run by Potato as a `type: jspsych` phase.
 *
 * Potato loads jsPsych and the plugins named in config.yaml, then this file.
 * It assigns window.potatoTimeline a function; Potato calls it with the
 * jsPsych instance and a `potato` object holding the participant id and
 * their between-subjects conditions. When the timeline ends Potato saves
 * the data and moves the participant to the next phase.
 */
window.potatoTimeline = function (jsPsych, potato) {
    var inks = [
        {name: 'RED', color: '#c62828', key: 'r'},
        {name: 'GREEN', color: '#2e7d32', key: 'g'},
        {name: 'BLUE', color: '#1565c0', key: 'b'}
    ];

    // Every word in every ink: 3 congruent and 6 incongruent combinations.
    var stimuli = [];
    inks.forEach(function (word) {
        inks.forEach(function (ink) {
            stimuli.push({
                word: word.name,
                ink: ink.name,
                color: ink.color,
                correct_response: ink.key,
                congruent: word.name === ink.name
            });
        });
    });

    var instructions = {
        type: jsPsychInstructions,
        pages: [
            '<p>A colour word will appear in coloured ink.</p>' +
            '<p>Press the key for the <strong>ink colour</strong>, not the word:</p>' +
            '<p><strong>R</strong> = red &nbsp; <strong>G</strong> = green &nbsp; ' +
            '<strong>B</strong> = blue</p>',
            '<p>Answer as quickly and accurately as you can.</p>'
        ],
        show_clickable_nav: true
    };

    var fixation = {
        type: jsPsychHtmlKeyboardResponse,
        stimulus: '<div style="font-size:48px;">+</div>',
        choices: 'NO_KEYS',
        trial_duration: function () {
            return jsPsych.randomization.sampleWithoutReplacement([400, 500, 600], 1)[0];
        },
        data: {task: 'fixation'}
    };

    var trial = {
        type: jsPsychHtmlKeyboardResponse,
        stimulus: function () {
            return '<div style="font-size:64px;font-weight:700;color:' +
                jsPsych.evaluateTimelineVariable('color') + ';">' +
                jsPsych.evaluateTimelineVariable('word') + '</div>';
        },
        choices: ['r', 'g', 'b'],
        trial_duration: 2500,
        data: {
            task: 'stroop',
            word: jsPsych.timelineVariable('word'),
            ink: jsPsych.timelineVariable('ink'),
            congruent: jsPsych.timelineVariable('congruent'),
            correct_response: jsPsych.timelineVariable('correct_response')
        },
        on_finish: function (data) {
            data.correct = jsPsych.pluginAPI.compareKeys(data.response, data.correct_response);
        }
    };

    // Shown only to participants assigned feedback: immediate.
    var feedback = {
        timeline: [{
            type: jsPsychHtmlKeyboardResponse,
            stimulus: function () {
                var last = jsPsych.data.get().last(1).values()[0];
                if (last.response === null) { return '<p>Too slow</p>'; }
                return last.correct ? '<p>Correct</p>' : '<p>Incorrect</p>';
            },
            choices: 'NO_KEYS',
            trial_duration: 600,
            data: {task: 'feedback'}
        }],
        conditional_function: function () {
            return potato.conditions.feedback === 'immediate';
        }
    };

    var block = {
        timeline: [fixation, trial, feedback],
        timeline_variables: stimuli,
        repetitions: 2,
        randomize_order: true
    };

    return [instructions, block];
};

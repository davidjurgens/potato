# jsPsych Phase

A `type: jspsych` phase runs a [jsPsych](https://www.jspsych.org/) timeline as
one page of a Potato study. Potato serves the page, passes the participant's
id and condition to the timeline, stores the data jsPsych collects, and moves
the participant on when the timeline ends. Consent, surveys, annotation,
Prolific or SONA, and the export stay in Potato.

Potato ships jsPsych 8.3.0 and 15 of its plugins, so a study works offline and
on servers with no internet access.

## Configuration

```yaml
phases:
  order: [consent, stroop, annotation, debrief]
  stroop:
    type: jspsych
    timeline: tasks/stroop.js
    plugins: [instructions, html-keyboard-response]
```

| Key | Default | Meaning |
|---|---|---|
| `timeline` | required | A `.js` file in the task directory that defines `window.potatoTimeline` |
| `plugins` | `[]` | Plugins to load, from the list below |
| `extensions` | `[]` | jsPsych extensions to load and pass to `initJsPsych`. Shipped: `mouse-tracking` |
| `extra_scripts` | `[]` | More `.js` files from the task directory, such as plugins Potato does not ship, loaded after `plugins` and before the timeline |
| `assets_dir` | none | A folder of stimuli the timeline can load (images, audio, video, text, CSS, fonts) |
| `expose_answers` | `[]` | Survey questions from earlier pages whose answers the timeline receives. Each must be asked on an earlier page; answers arrive as strings, numbers included (`"30"`) |
| `save` | `on_finish` | `incremental` also stores each trial as it finishes, so a closed tab keeps the trials done so far |
| `allow_rerun` | `false` | Whether returning to a finished page runs the task again |
| `max_data_mb` | `10` | Largest run the server accepts |
| `slot` | inferred | `prestudy` before the annotation phase, `poststudy` after it. An explicit slot that contradicts the page's place in `order` wins, and a warning is logged |
| `csp.extra_sources` | `[]` | `https://` origins the page may load fonts, images or scripts from |

A jsPsych page also takes `show_when` and `exit_when` like any phase page
([Experiment flow](experiment_flow.md)), and can be counterbalanced against
other pages of its slot. Its `exit_when` is checked when the timeline
finishes, so the run's data is already stored for a participant it screens
out; put a screener on its own page before the task to exclude people before
they do it.

### Shipped plugins

`html-keyboard-response`, `html-button-response`, `html-slider-response`,
`image-keyboard-response`, `image-button-response`, `audio-keyboard-response`,
`audio-button-response`, `video-keyboard-response`, `instructions`, `preload`,
`fullscreen`, `survey-likert`, `survey-text`, `survey-multi-choice`,
`call-function`.

Other plugins, including ones from `jspsych-contrib`, go in `extra_scripts`
as browser builds (the `index.browser.min.js` file of the npm package).

### Extensions

`extensions: [mouse-tracking]` loads `@jspsych/extension-mouse-tracking`
1.2.0 and registers it with jsPsych. A trial turns it on in the usual way,
and each such trial gets `mouse_tracking_data` (a list of `{x, y, t, event}`
samples) and `mouse_tracking_targets` in its data:

```javascript
{
    type: jsPsychHtmlButtonResponse,
    stimulus: '<p id="stim">Which is bigger?</p>',
    choices: ['3', '8'],
    extensions: [{type: jsPsychExtensionMouseTracking, params: {targets: ['#stim']}}]
}
```

The WebGazer eye-tracking extension is not shipped. WebGazer needs
`'unsafe-eval'`, which the jsPsych page's Content-Security-Policy does not
allow.

## The timeline file

```javascript
window.potatoTimeline = function (jsPsych, potato) {
    var trial = {
        type: jsPsychHtmlKeyboardResponse,
        stimulus: '<p style="font-size:48px">RED</p>',
        choices: ['r', 'g', 'b']
    };
    return [trial];
};
```

`window.potatoTimeline` is a timeline array, or a function that returns one.
Potato calls the function with the jsPsych instance it created and a `potato`
object:

| Property | Content |
|---|---|
| `potato.participant` | The Potato username (Prolific id, SONA id and so on) |
| `potato.conditions` | `{factor: level}` from `conditions` |
| `potato.answers` | `{question: answer}` for the questions in `expose_answers` |
| `potato.attempt` | 1 on the first run; higher once a reload follows a run that had sent data |
| `potato.asset(path)` | The URL of a file in `assets_dir` |
| `potato.finish()` | End the task now and save what was collected |

Do not call `initJsPsych` yourself, and do not set `on_finish` on the
experiment; Potato owns both. Trial-level `on_finish` and the rest of the
jsPsych API work as usual.

Every trial gets `potato_user`, `potato_page`, `potato_run_id`,
`potato_attempt` and one `condition_<factor>` column per factor.

### Stimuli

```javascript
{
    type: jsPsychImageKeyboardResponse,
    stimulus: potato.asset('faces/f01.png')
}
```

Preload stimuli with the `preload` plugin, as in any jsPsych experiment.

## When the timeline ends

The page sends the data to the server, shows "Saving your responses", and
goes to the next page once the server has stored it. If the save fails it
retries, then shows a Try again button; the participant is not moved on
without their data.

There is no other way off the page: until the run is stored, the server
rejects a post of the phase form and the annotation page's Next.

A reload starts the timeline over. jsPsych cannot resume mid-timeline. A run
that has sent no data is reused, and its attempt number does not change: with
the default `save: on_finish`, trials done before a reload are lost and leave
no trace except the page's `page_loads` count in `participants.csv`. With
`save: incremental`, a run that has sent data is kept as incomplete, and a
reload starts a new attempt. Opening the task in a second tab is a reload; the
first tab's run can no longer finish.

A timeline that is not an array, or is empty, shows the participant a
message instead of a blank page.

## Data and export

Runs are stored in the project database (`project.sqlite` in the task
directory, table `runtime_runs`), not in `user_state.json`. The `jspsych`
export format writes the files below; the `runtime` format writes the same
for every [runtime phase](runtime_phases.md) the project uses:

| File | Content |
|---|---|
| `jspsych_runs.csv` | One row per run: participant, page, attempt, status, trial count, conditions |
| `jspsych_trials.csv` | One row per trial, with every column jsPsych recorded. Nested values are JSON |
| `jspsych_interaction.csv` | jsPsych's blur, focus and fullscreen events, when any were recorded |
| `jspsych_raw/<user>/<page>-<run>.json` | Each run's data as jsPsych produced it |

```bash
python -m potato.export --config config.yaml --format jspsych --output ./export/
```

Runs that did not finish have status `started` or `partial`.

## Security

The timeline is code you wrote, and it runs on the Potato server's origin
with the participant's session, the same trust as a custom HTML instructions
page. It is served with a Content-Security-Policy that allows scripts,
styles, media and network requests only from the Potato server (plus any
`csp.extra_sources`), and network requests only to the Potato server. A
stimulus that shows participant text (for example from `expose_answers`)
cannot load or send to anything else, but you should still escape such text
before putting it in HTML.

Every file the page names must be inside the task directory. The asset route
serves only the file types listed above, never `.js` or `.html` from
`assets_dir`, and serves each with a sandboxing CSP of its own, so an SVG
opened directly runs no script. `csp.extra_sources` takes single `https://`
origins; wildcards are refused.

## Timing

jsPsych's own timing applies. Its timing-accuracy page reports that response
times measured in JavaScript tend to be 10–40 ms longer than in lab software,
with similar variance. Potato adds nothing to the trial loop, because the
page runs jsPsych alone, without Potato's annotation scripts.

## Example

```bash
python potato/flask_server.py start examples/advanced/jspsych-stroop/config.yaml -p 8000
```

A Stroop task between a screener and a word-rating task, with feedback shown
to half of the participants (`conditions`).

## Related

- [Runtime phases](runtime_phases.md)
- [Coming from jsPsych](../guides/coming-from-jspsych.md)
- [Experiment flow](experiment_flow.md)
- [Timed trials](timed_trials.md)
- [Multi-phase workflows](surveyflow.md)

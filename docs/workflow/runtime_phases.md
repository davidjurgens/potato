# Runtime Phases

A runtime phase is a page of a Potato study that runs a task built for
another experiment runtime, or a built-in task, instead of a page of
questions. Potato serves the page, passes the participant's id, conditions
and chosen survey answers to the task, stores what the task records, and
moves the participant on when it ends.

| `type` | Runs |
|---|---|
| [`jspsych`](jspsych_phase.md) | A jsPsych 8 timeline |
| [`headphone_check`](#headphone-check) | Potato's headphone screening test |
| [`external`](#external-tasks-otree-empirica-hosted-surveys) | A task on another server (oTree, Empirica, a hosted survey), with a return link |

Every runtime phase:

- sits in the prestudy or poststudy slot, by its place in `phases.order`
  (or `slot:`), and takes `show_when`, `exit_when` and counterbalancing like
  any phase page ([Experiment flow](experiment_flow.md));
- runs under a Content-Security-Policy that allows scripts and network
  requests only to the Potato server;
- cannot be skipped: until the task's data is stored, the server refuses the
  phase form and the annotation page's Next;
- stores its data in the project database (`project.sqlite`, table
  `runtime_runs`), not in `user_state.json`, and exports it with
  `--format runtime` (or `--format jspsych` for jsPsych pages only).

These keys apply to every runtime phase:

| Key | Default | Meaning |
|---|---|---|
| `extra_scripts` | `[]` | More `.js` files from the task directory, loaded before the task |
| `assets_dir` | none | A folder of files the task may load |
| `expose_answers` | `[]` | Answers to earlier survey questions passed to the task |
| `save` | `on_finish` | `incremental` also stores each trial as it finishes |
| `allow_rerun` | `false` | Whether returning to a finished page runs the task again |
| `max_data_mb` | `10` | Largest run the server accepts |
| `csp.extra_sources` | `[]` | `https://` origins the page may load fonts, images or scripts from |

A jsPsych page can also list `answers`: values its timeline records that
`show_when` and `exit_when` on that page or a later one can test. See
[Answers page rules can test](jspsych_phase.md#answers-page-rules-can-test).

## Headphone check

A screening page for listening studies: it checks that the participant is
wearing headphones, not using loudspeakers.

```yaml
phases:
  order: [consent, headphones, annotation]
  headphones:
    type: headphone_check
    test: huggins
    trials: 6
    pass_threshold: 5
```

| Key | Default | Meaning |
|---|---|---|
| `test` | `huggins` | `huggins`, `antiphase`, or `both` |
| `trials` | `6` | Trials per test (2–20) |
| `pass_threshold` | `5` | Correct trials needed to pass, per test |
| `on_fail` | `screen_out` | `screen_out` ends the study for a participant who fails; `continue` records the result and goes on |
| `message` | a default | What a screened-out participant reads |

The page asks the participant to put on headphones and set a comfortable
volume, then runs the trials. Each trial plays three sounds once; the
participant picks one.

- **huggins** (Milne et al., 2021): three bursts of noise. In one, a narrow
  band around 600 Hz is phase-inverted in one ear, which over headphones is
  heard as a faint tone and over loudspeakers is not. "Which sound had a faint
  tone hidden in the noise?"
- **antiphase** (Woods et al., 2017): three 200 Hz tones. One is 6 dB
  quieter; one is in antiphase between the ears, which over loudspeakers
  partly cancels and sounds quietest. "Which sound was the quietest?"

The server makes the sounds when the page asks for them, so no audio files
are shipped. It also picks which of the three sounds is the answer, and
sends each trial's three as one WAV that does not say which it is.

The page answers two questions that later pages can test:
`<page>_passed` (`yes` or `no`) and `<page>_correct` (a number; for
`test: both`, `<page>_correct_huggins` and `<page>_correct_antiphase`).
With `on_fail: screen_out` the page gets an `exit_when` on
`<page>_passed equals no`. With `on_fail: continue`, use the answer
yourself:

```yaml
  speakers_note:
    type: prestudy
    file: surveys/speakers.json
    show_when:
      - {schema: headphones_passed, operator: equals, value: "no"}
```

The server scores each response against its own record; the browser sends
only the choice. A target or "correct" value in what the browser posts is
ignored, as are a second answer to the same trial and an answer to a sound
that was never fetched. Made-up answers score at chance.

Passing still does not prove the participant wore headphones. Someone on
loudspeakers can guess right (one in three per trial). A participant who
writes code to analyse the downloaded sound can find the answer, as with
any headphone screen whose sounds reach the browser.

## External tasks (oTree, Empirica, hosted surveys)

A `type: external` page sends the participant to a task on another server
and takes them back when it ends. The task runs on the other server; Potato
hands over the participant and records that they came back.

```yaml
phases:
  order: [consent, game, annotation]
  game:
    type: external
    url: "https://otree.example.org/room/public_goods/?participant_label={participant}&potato_return={return_url}"
    return_params: [payoff]
    description: The next part is a short game with three other participants.
    button_text: Start the game
```

| Key | Default | Meaning |
|---|---|---|
| `url` | required | Where to send the participant (`https://`; `http` only for `localhost`, `127.0.0.1` or `[::1]`), with placeholders |
| `return_params` | `[]` | Query parameters to keep from the return link |
| `return_secret` | none | A private string of at least 16 characters, shared with the other system. When set, the return must be signed (see below) |
| `description` | none | Text above the button |
| `button_text` | "Continue to the task" | The button |
| `new_tab` | `false` | Open the task in a new tab |

Placeholders in `url`, URL-encoded: `{participant}` (the Potato user id),
`{return_url}` (the address that brings the participant back), `{run_id}`
and `{condition.<factor>}`.

The other system sends the participant to `{return_url}` when they finish,
adding any results as query parameters:
`<return_url>&payoff=4.50`. The return must arrive in the same browser
session and name the participant's current attempt; an out-of-date link
shows "This link is out of date" and changes nothing. The page then answers
`<page>_returned` (`yes`) and `<page>_<param>` for each listed parameter,
which later pages can test, and the parameters are stored with the run.

### Signed returns

The return link is in the address the participant is sent to, so the
participant can read it, change `payoff=4.50` to `payoff=99`, and open it
without playing. Without `return_secret`, the returned parameters are
self-reported. Do not pay from them unless you check them against the other
system's own records.

With `return_secret`, the other system adds `sig` to the return link: the
hex HMAC-SHA256, keyed with the secret, of the run id followed by
`&<param>=<value>` for each returned parameter in `return_params`, sorted by
name. Each name and value is percent-encoded with every reserved character
escaped (Python's `quote(x, safe="")`), so a value containing `&` or `=`
cannot pass for another parameter. The run id is the `run` parameter of
`{return_url}`, or `{run_id}`. In Python:

```python
import hashlib, hmac
from urllib.parse import quote
message = run_id + "".join(f"&{quote(k, safe='')}={quote(params[k], safe='')}"
                           for k in sorted(params))
sig = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
# redirect to f"{return_url}&{urlencode({**params, 'sig': sig})}"
```

For run `3f2a…` and `payoff=4.50`, the message is `3f2a…&payoff=4.50`. A
return without `sig`, or with a `sig` that does not match, gets status 409
and the page "This return could not be confirmed". The page is not marked
done, so a correctly signed return still works afterwards. The secret has to
be kept on the other system's server. A hosted survey that builds its end
redirect in the participant's browser cannot keep it private, so signing
does not help there.

- **oTree**: send participants to a room URL with
  `participant_label={participant}`. The app has to carry the return URL
  itself: read the `potato_return` parameter when the participant arrives,
  keep it in `participant.vars`, and redirect to it from the last page. How
  the first page reads URL parameters depends on the oTree version; check
  its documentation.
- **Empirica**: pass `{participant}` as the `participantKey` URL parameter.
- **A hosted survey or experiment** (Qualtrics, Gorilla, Pavlovia): put
  `{participant}` in an embedded-data or URL parameter, and set the end
  redirect to the return URL.

## Data and export

```bash
python -m potato.export --config config.yaml --format runtime --output ./export/
```

writes, for each runtime the project uses (`<kind>` is `jspsych`,
`headphone_check`, ...):

| File | Content |
|---|---|
| `<kind>_runs.csv` | One row per run: participant, page, attempt, status, trial count, conditions |
| `<kind>_trials.csv` | One row per trial, every column the task recorded |
| `<kind>_interaction.csv` | Blur, focus and fullscreen events, when any were recorded |
| `<kind>_raw/<user>/<page>-<run>.json` | Each run's data as the task produced it |

A headphone-check trial records `test`, `trial`, `index` (its position in
the run), `response` (the sound chosen, 1 to 3), and three values the server
adds: `target` (the correct sound), `correct`, and `scored`, which is
`false` for an answer the server did not count (a repeat, a sound never
fetched, a response outside 1 to 3).

## Example

```bash
python potato/flask_server.py start examples/audio/listening-test-p808/config.yaml -p 8000
```

A headphone check, then speech clips rated on the ACR scale.

## Related

- [jsPsych phase](jspsych_phase.md)
- [Listening tests](../annotation-types/multimedia/listening_tests.md)
- [Experiment flow](experiment_flow.md)

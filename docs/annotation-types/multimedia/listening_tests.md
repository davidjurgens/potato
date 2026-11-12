# Listening Tests

A `listening_test` scheme runs a standard audio quality or discrimination
test on each item:

| `method` | Standard | What the listener does |
|---|---|---|
| `mushra` | ITU-R BS.1534-3 | Rates every sample 0–100 against an open reference. The samples include a hidden reference and optional low-pass anchors |
| `bs1116` | ITU-R BS.1116 | Hears the reference, then A and B (one is the hidden reference) and rates each 1.0–5.0 for impairment |
| `acr` | ITU-T P.800 / P.808 / P.910 | Rates one sample: Excellent, Good, Fair, Poor, Bad |
| `dcr` | ITU-T P.800 | Hears the reference, then the sample, and rates the degradation in 5 steps |
| `ccr` | ITU-T P.800 | Compares two samples: Much better … Much worse (+3 to −3) |
| `p835` | ITU-T P.835 | Rates one sample three times: speech signal, background, overall |
| `abx` | | Hears A, B and X, and says whether X is A or B |

All samples of a trial are decoded into one Web Audio context. Switching from
one sample to another continues from the same position, and a loop region
lets the listener compare a short passage. The page keeps track of what has
been played, and the answer can only be given once the playback rule is met.

The page is not told which sample is which: it gets slot names
(`Sample 1`, `A`, `X`) and audio URLs of the form
`/api/listening/audio/<scheme>/<item>/<slot>`. The order is shuffled per
listener and per item, seeded so it is the same on every visit and can be
recomputed for the export without storing it.

## MUSHRA

```yaml
annotation_schemes:
  - annotation_type: listening_test
    name: quality
    method: mushra
    description: Rate the audio quality of each sample against the reference
    reference_field: reference
    stimuli_field: stimuli
    anchors: [3500, 7000]
    label_requirement:
      required: true
```

```json
{"id": "excerpt_1",
 "reference": "/media/chord_ref.wav",
 "stimuli": {"lowrate": "/media/chord_lowrate.wav", "coarse": "/media/chord_coarse.wav"}}
```

`stimuli` maps condition names to files; a list of `{"id", "url"}` objects
also works. The page shows the reference, then one slider per sample: the
conditions, the hidden reference (`hidden_reference: true`, the default),
and one anchor per cut-off in `anchors`. Anchors are made from the reference
by low-pass filtering at that frequency (BS.1534-3 asks for 3.5 kHz and
recommends 7 kHz). This works for a PCM WAV reference. For any other format,
put the anchor files in `stimuli` yourself.

A trial is complete when every sample has been listened to (two seconds, or
half the sample if it is shorter), every sample is rated, and at least one
is rated 100 (`require_one_at_100`). Sliders start in the middle with a
hollow thumb and count as rated only once moved.

## ACR, DCR and P.835 (one clip per item)

```yaml
annotation_schemes:
  - annotation_type: listening_test
    name: quality
    method: acr
    description: How would you rate the quality of this speech sample?
    stimuli_field: audio
    condition_field: condition
```

```json
{"id": "clip_1", "audio": "/media/clip_1.wav", "condition": "noise_10db"}
```

`condition_field` names the item field holding the clip's condition, so
the export can report a mean opinion score per codec, system or noise
level. The rating buttons stay disabled until the clip has played to the
end (`require_full_playback`, the default for these methods). DCR also needs
`reference_field`. `scale_labels` replaces the five category labels for
`acr`, `dcr` and `ccr` (best first).

## CCR and ABX

`ccr` and `abx` read two conditions from `stimuli`. CCR presents them in a
seeded order and stores the rating of the second against the first; the
export turns it into a score for each condition against the other. ABX
plays A and B and an X that is one of them, chosen per listener and item.

## Options

| Key | Default | Meaning |
|---|---|---|
| `method` | `mushra` | One of the seven methods above |
| `stimuli_field` | `stimuli` | Item field with the samples: a map, a list, or one file |
| `reference_field` | `reference` | Item field with the open reference (`mushra`, `bs1116`, `dcr`) |
| `condition_field` | `condition` | Item field naming a single clip's condition |
| `hidden_reference` | `true` | Add the reference among the MUSHRA samples |
| `anchors` | none | Low-pass anchor cut-offs in Hz, from a WAV reference (`mushra` only) |
| `loop` | `true` for `mushra`, `bs1116` | Show the loop controls |
| `require_full_playback` | `true` for single-clip methods and ABX | Answer only after every sample has played to the end |
| `require_all_played` | `true` | Answer only after listening to every sample |
| `require_one_at_100` | `true` for `mushra` | One sample must be rated 100 |
| `scale_labels` | the standard's | Five (`acr`, `dcr`) or seven (`ccr`) labels, best first |
| `instructions` | none | Text shown under the question |
| `label_requirement` | | `required: true` makes the trial required, as for any scheme |

Keys: `1`–`9` play a sample, `R` the reference, `Space` pauses. They work
while focus is on one of the test's buttons (a play button, say) and do not
trigger Potato's label shortcuts. While a slider, the position bar or one of
the loop controls has focus, the keys go to that control instead: the arrow
keys move a slider, the loop fields take typed numbers and `Space` ticks the
loop box. Click or tab to a button to
use the shortcuts again.

## Headphone check

Run a [`headphone_check` page](../../workflow/runtime_phases.md#headphone-check)
before a listening test. It uses the Huggins-pitch test (Milne et al. 2021)
or the antiphase test (Woods et al. 2017), and by default ends the study for
anyone who fails it.

## Export

`python -m potato.export --format listening_test` maps every slot back to
its condition and writes:

| File | Contents |
|---|---|
| `listening_ratings.csv` | One row per rating: participant, item, scheme, method, slot, condition, scale, score |
| `listening_summary.csv` | Per scheme, condition and scale: n, mean, SD, 95% confidence interval |
| `listening_abx.csv` | Per participant and ABX scheme: trials, correct, proportion, one-sided binomial p |
| `listening_screening.csv` | Per participant and MUSHRA scheme: the BS.1534-3 post-screening counts and whether the rule excludes them |

Scores: ACR, DCR and the P.835 scales run 5 (best) to 1; MUSHRA 0–100;
BS.1116 1.0–5.0; CCR +3 to −3.

The post-screening rule, as implemented: a listener is excluded if they rate
the hidden reference below 90 on more than 15% of items, or the mid anchor
(the highest anchor cut-off) above 90 on more than 15% of items. An item
where more than 25% of listeners rate the mid anchor above 90 is left out of
the anchor test for everyone. Excluded listeners are flagged, not removed.

## Running a P.808-style study

ITU-T P.808 also asks for a qualification step, training with gold clips,
and trapping clips inside the rating session. In Potato:

- qualification: a `headphone_check` page, plus a prestudy survey on the
  listening environment;
- training: a [training phase](../../workflow/training_phase.md) with gold
  answers;
- trapping clips: [attention checks](../../workflow/quality_control.md) whose
  expected answer is the category the clip announces.

Microsoft's P.808 toolkit ships its clips under several licenses; Potato
bundles none of them.

## What the page can see

The page gets one URL per slot (`/api/listening/audio/<schema>/<item>/<slot>`)
and nothing that says which condition a slot is:

- the stimulus, reference and condition fields are left out of the item
  data sent to the page;
- files named by a listening item are not served at `/media/`, so they
  cannot be downloaded and compared with the slots;
- each slot response carries no ETag, Last-Modified or file name, and WAV,
  FLAC and MP3 files get a padding block of random length inside the
  container, so two slots holding the same file (the hidden reference, or
  ABX's X) have different bytes. The audio is unchanged.

A file used by a listening item cannot also be shown by another scheme
through `/media/`; give that scheme its own copy.

## Limitations

- The page decodes every slot to play it, so a participant using the
  browser's developer tools can compare the decoded audio. Blinding stops
  casual and scripted lookups of files, headers and hashes, not a
  participant who sets out to analyse the samples.
- Other audio formats are sent unchanged, and the server logs a warning.
  For ABX and a hidden reference, use WAV, FLAC or MP3.
- A sample given as an `http(s)` URL is fetched by a redirect, so its URL
  shows in the browser's network log. For a blind test, serve the files from
  the project's `media/` directory.
- Anchors are made from PCM WAV references only.
- Playback goes through the browser's audio output. Potato cannot calibrate
  level or check the playback chain beyond the headphone check.

## Examples

```bash
python potato/flask_server.py start examples/audio/listening-test-mushra/config.yaml -p 8000
python potato/flask_server.py start examples/audio/listening-test-p808/config.yaml -p 8000
```

## Related

- [Audio annotation](audio_annotation.md)
- [Runtime phases and the headphone check](../../workflow/runtime_phases.md)
- [Timed trials](../../workflow/timed_trials.md)

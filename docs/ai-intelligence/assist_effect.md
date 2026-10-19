# Measuring AI Influence

An answer given after seeing a model's suggestion is pulled toward it. That is
fine when the suggestion is right and costly when it is wrong, and from the
answers alone a study cannot tell how much of its agreement with the model, or
between annotators, came from the suggestion. `ai_support.holdout` sets aside a
random share of annotators' items that get no AI assistance at all, and the
admin dashboard compares the two groups.

## Configuration

```yaml
ai_support:
  holdout:
    fraction: 0.2      # share of (annotator, item) pairs shown no assistance
    salt: my-study     # changes which pairs; keep it fixed for the study
```

| Key | Default | Meaning |
|---|---|---|
| `fraction` | `0` (off) | Share of (annotator, item) pairs held out, from 0 to 1 |
| `salt` | `""` | Changes the draw. Changing it, or `fraction`, mid-study reshuffles the groups |

The draw is per annotator and item, not per item, so most items end up with
some assisted and some held-out annotators. It is a salted hash, so a pair is in
the same group on every visit and after a restart. The comparison is by group,
not by whether an annotator chose to open a hint, which would mix up the effect
of the suggestion with the kind of annotator who asks for one.

`holdout` works whether or not `ai_support.enabled` is on. A study whose only
assistance is pre-annotations (see the example) uses it the same way.

## Assistance withheld from held-out pairs

| Assistance | Held out |
|---|---|
| Pre-annotations (`pre_annotation`) | Not applied, and the prediction field is removed from the item data the page receives |
| Hints, keyword and rationale help | The routes refuse with 403 |
| Option highlights | Refused |
| Visual AI toolbar | Not loaded |
| Annotation critique | Refused |
| Chat sidebar | Not loaded, and the chat route refuses |
| Inline judge suggestion | Not shown |
| PRM pre-label | Refused |
| Keyword highlighting set by an administrator | None returned |
| Interactive (click-to-mask) and text-prompt segmentation on images | The tools are hidden and cannot be selected |
| SAM 2 object tracking in video | Refused |

These are the same checks the labeling engine uses for its blind calibration
items, so an item blind for the engine is also unassisted. Administrator
keywords are withheld although no model makes them, because they point the
annotator at an answer just as a model's highlights do.

### What the annotator did with a suggestion

Each time an item is saved, Potato compares the saved answer on a scheme with
the labels a hint or suggestion offered for it, and records the result on the
AI usage record as `decision`:

| `decision` | When |
|---|---|
| `accepted` | The saved answer holds every suggested label. `suggestion_accepted` names them |
| `partial` | It holds some of them (a multiselect that kept part of the suggestion) |
| `rejected` | It holds none |

The comparison is on the full set of labels saved, so a multiselect is judged
as a set, and the last save decides: an annotator who takes a suggestion and
then changes their mind is recorded by what they saved. `time_to_decision_ms`
runs from the suggestion to that save. A text answer counts as accepted only
when it is exactly the suggested string. The admin dashboard's AI usage
counts report `partial` with the rejects.

## The AI influence tab

When a hold-out is configured, the admin dashboard has an **AI influence** tab.
For each radio, multiselect, likert and select scheme it compares the assisted
group with the held-out group on:

- **Match the model:** how often the answer equals the model's own answer for
  the item, read from its pre-annotation field. Anchoring shows up here as a
  higher rate with assistance.
- **Match gold:** accuracy on items with a gold label. If assistance raises
  model agreement without raising gold accuracy, annotators are copying rather
  than being helped.
- **Alpha within group:** agreement between annotators. It can rise because
  everyone copies the same suggestion, which says nothing about reliability.

The difference in model agreement comes with a 95% bootstrap interval over
items. Until each group has 10 answers on items with a model answer, the tab
says how many it has instead of printing a difference. The same report is
available as JSON from `/admin/api/ai_influence`.

## Example

```bash
python potato/flask_server.py start examples/ai-assisted/assist-holdout/config.yaml -p 8000
```

Ten reviews, each with a model prediction shown as a pre-selected answer. The
model calls every review positive or negative, including the ones with mixed
sentiment, so anchoring shows as assisted annotators choosing "mixed" less
often. 30% of each annotator's reviews show no prediction.

## Related

- [AI Support](ai_support.md)
- [Option Highlighting](option_highlighting.md)
- [Labeling engine](../labeling-engine/configuration.md)

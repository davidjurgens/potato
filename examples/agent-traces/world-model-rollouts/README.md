# World-model rollout evaluation

Three videos of the same scenario, frame-locked: the real recording and two
model continuations. The annotator finds the frame at which each one stops
making sense, says why, picks a winner, and — where the scenario carries an
intervention — judges whether the divergence follows from it.

```bash
# from the repository root
python examples/agent-traces/world-model-rollouts/generate_rollouts.py
python potato/flask_server.py start \
    examples/agent-traces/world-model-rollouts/config.yaml -p 8000
```

`generate_rollouts.py` needs **ffmpeg**. Without it there is nothing to show.

The `.webm` files are committed so the example runs — and so
`tests/playwright/test_rollout_evaluation.py` has something to load — but
**libvpx encoding is not byte-reproducible**, so re-running the generator
produces a nine-file binary diff with identical content. Discard it unless you
changed the scenarios.

## What is in the data

Three scenarios. Each model rollout is wrong in one specific, findable way, and
the frame it goes wrong at is deliberately **not** in the data — that is what
the annotator is being asked to find.

| Scenario | Model A | Model B |
|---|---|---|
| `ball_drop` | the ball stops mid-air at 2.0 s (`gravity_violation`) | correct |
| `block_push` | the block passes through the wall from 2.6 s (`interpenetration`) | the block vanishes at 3.4 s (`object_permanence`) |
| `two_balls` | correct | the two balls swap colour at 3.0 s (`identity_flicker`) |

`block_push` also carries an intervention — "the wall was moved 50 px left at
1.5 s" — so the counterfactual layer has something to judge. Model A ignores
the intervention entirely and sails past where the wall now is; Model B stops
correctly and then loses the block.

Two of the nine rollouts (`ball_drop/gen_b`, `two_balls/gen_a`) are byte-identical
to their recordings. They are there on purpose: a taxonomy that only ever gets
applied to broken clips is never tested against a correct one, and "no breaks"
has to be an answer an annotator actually gives before the detection agreement
means anything.

## What to look at once it is running

- **Panel order and captions.** The panels are blinded to `A`, `B`, `C` and
  shuffled per annotator. Log in as a second user and the order changes; reload
  as the same user and it does not.
- **The progress line.** "0 of 3 panels answered — still to do: A, B, C." Press
  `c` on a panel with no breaks and watch it fall to 2.
- **The Next guard.** With a panel unanswered, the first Next press warns
  instead of navigating. The second proceeds.
- **Frame stepping.** `,` and `.` move every panel one frame together. The
  readout quotes the frame number, which is what a researcher checks against
  the tensor.

## Agreement

The config assigns two annotators per item, so `/admin/iaa` has something to
compute. Annotate all three items as two different users and the report shows
detection, localization, category and severity agreement across a tolerance
sweep — see
[World-Model Evaluation](../../../docs/agent-evaluation/world_model_eval.md).

With only three items the numbers are illustrative, not evidence. The point is
to see the shape of the report.

# Annotation review — VLM as judge

Ask a vision model to review the regions you have already drawn, one at a time,
and present what it doubts as a queue you work through.

```bash
cp examples/image/annotation-critique/ai-config.yaml.example \
   examples/image/annotation-critique/ai-config.yaml
# edit it to point at a vision-capable endpoint, then:
python potato/flask_server.py start examples/image/annotation-critique/config.yaml -p 8000
```

## What to try

The demo is most informative if you make mistakes on purpose:

1. Box a car correctly.
2. Box a **person** and label it **car**.
3. Box a sign with a box roughly three times too large.
4. Leave one object unannotated entirely.
5. Press **Review** in the AI Assist bar.

You should get three findings — a wrong label with the suggested one, a loose
boundary, and a possibly-missed object — and one confirmation, collapsed.

## Why this is not the same as agreement

Krippendorff's α over IoU (see [geometry agreement](../../../docs/advanced/geometry_agreement.md))
asks whether two annotators drew the same shape. It cannot tell you anything
when:

- there is only one annotator, which is the common case in a pilot; or
- both annotators are confidently wrong in the same way, which is what happens
  when a guideline is ambiguous.

Asking a model to look at each region on its own catches exactly that second
case, because it never sees the other annotator's answer.

It is also much weaker evidence. A verdict is one model's opinion, and the
panel says so every time it opens. The useful reading of a flag is "look at
this again", never "the model says change it".

## What the judge is sent

For each annotation, the server crops the region **with surrounding context**
and draws the annotator's own outline onto the crop in red, then asks the model
about the outlined region. Both halves matter:

- **without context**, the object fills the frame by construction, so every
  boundary looks tight and the boundary question is unanswerable;
- **without the drawn outline**, the model cannot see where the boundary is and
  answers about one it imagined.

A separate whole-image pass asks what was missed. Anything it reports that
lands on a region already annotated is dropped, because that is the same
mistake the per-region verdict already reported — showing it twice makes one
error look like two.

Nothing is applied automatically. Every change to your work happens because you
pressed a button with the reason on screen.

## Configuration

See `config.yaml` for the full set with comments. The options live under the
schema's `ai_support.critique`:

| Option | Default | What it does |
|---|---|---|
| `context_ratio` | 0.6 | Context around each region, as a fraction of its longer side |
| `min_confidence` | 0.5 | Below this, a verdict is "unclear" and stays out of the queue |
| `max_regions` | 24 | Cost ceiling; the excess is reported as "not reviewed" |
| `max_workers` | 4 | Concurrent model calls |
| `check_missed` | true | Also run the whole-image "what was missed?" pass |
| `coverage_ratio` | 0.5 | How much of a "missed" object must lie inside an existing region to count as covered |

Full documentation: [docs/ai-intelligence/annotation_critique.md](../../../docs/ai-intelligence/annotation_critique.md)

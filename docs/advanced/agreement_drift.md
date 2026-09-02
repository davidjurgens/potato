# Agreement Over Time and Re-Calibration

A single agreement number for a whole project averages early work and late work
together, so a team whose recent annotations have become unusable can still
show an acceptable figure.

Guidelines drift as new edge cases arrive. The practice credited with large
agreement gains is the calibration session, where annotators work through
pre-annotated items and argue about the disagreements, and the gain holds only
if the sessions repeat.

Potato had fourteen agreement metrics and no time dimension. This adds one, and
the re-calibration round that acts on it.

---

## Quick start

Nothing to configure. Open `/admin/iaa` and the **Agreement over time** section
sits below the per-schema tables.

To tune it:

```yaml
calibration:
  enabled: true          # default
  windows: 6             # how many slices
  window_by: count       # or "time"
  drop_threshold: 0.15   # 15% below baseline raises the prompt
```

JSON, for scripting:

```bash
curl -H "X-API-Key: $KEY" http://localhost:8000/admin/iaa/drift
```

---

## Windows and timestamps

Three decisions worth stating, since all three are arguable.

**Which timestamp.** An annotation has several. `session_start` is when the
annotator first opened the item, which for a queue skimmed once and answered
later sits nowhere near the moment the answer was given. Potato uses the last
recorded change for the schema instead, then falls back to `session_end` and
`session_start`.

**When an item enters a window.** Agreement is a property of an item across
annotators rather than of one annotator's answer, so an item belongs to the
window containing the moment its last annotator finished. That is when the item
became measurable.

**Which metric.** Each window re-runs the same agreement computation restricted
to its own items, so every window is scored with the same per-schema metric the
whole-project report uses. Picking one metric for the chart would score a span
schema and a slider schema with the same measure.

### Window sizing

`window_by: count` gives every window the same number of items, and is the
default. Equal-duration windows leave some stretches of a bursty study empty, and an empty window has no agreement at all rather than low
agreement. A chart cannot tell the two apart.

### Windows with no number

A chance-corrected coefficient is undefined when there is nothing to be right
about by chance. If every annotator chose the same label on every item in a
window, α is 0/0, so a window of perfect agreement has no value to plot.

Potato marks those `total agreement` and explains the marker under the table,
rather than leaving a bare dash that reads as missing data.

---

## The re-calibration prompt

When the latest window falls more than `drop_threshold` below the project
baseline, `/admin/iaa` raises a prompt naming the schema and the size of the
fall.

It deliberately does not fire on two things:

- **An old dip.** Only the latest non-sparse window is judged. A drop the team
  already recovered from is history, and firing on it teaches people to ignore
  the prompt.
- **A baseline at or below zero.** Agreement already at chance is a problem the
  whole-project number reports, and a percentage fall from zero is arithmetic.

Windows holding fewer than five items are shown but marked `too few to judge`,
and never fire the prompt.

The baseline is the whole-project figure rather than the first window's. A first
window that happens to be unusually good would otherwise set the bar for the
whole study, and the first window is where an uncalibrated team's numbers are
least stable.

---

## Codebook markers

If the project uses a [codebook](qda.md), each revision is marked on the
timeline, so a guideline edit that moved agreement shows up as an edit rather
than an unexplained step.

Revisions recorded since this feature shipped are exact. Older ones are
inferred from the earliest annotation stamped with each revision, which is a
lower bound, and are labelled `approximate` so the guess is visible.

---

## Running a calibration round

A round sends annotators back through the training exercise mid-study. Before
this, `TRAINING` was a one-shot gate: a user who passed it could never be sent
back, so "re-calibrate periodically" was not expressible.

```bash
# Who is eligible, and how past rounds went
curl -H "X-API-Key: $KEY" http://localhost:8000/admin/calibration

# Recall everyone eligible
curl -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
     -d '{"reason": "tone alpha fell 22%"}' \
     http://localhost:8000/admin/calibration/start
```

Omitting `usernames` recalls everyone eligible, which is usually right, since
drift is a property of the guidelines and affects the whole team.

A round resets each annotator's training state and returns them to the training
phase. Their assignments and existing annotations are untouched, so they rejoin
annotation where they left off. A round asks them to re-do the exercise rather
than the study.

Annotators who have not passed the training gate yet are reported as skipped
rather than silently dropped. An admin recalling twelve people needs to know
that two of them are still on the consent page.

!!! note "Rounds re-run the training set, not the disagreements"
    A disagreement item has no right answer, and the training phase grades every
    answer against known correct ones. Pointing it at the adjudication queue
    would grade annotators against nothing.

    Reviewing disagreements is a separate need, and
    [Adjudication](../administration/adjudication.md) already does it with the
    right affordances.

`training` must be enabled. Recalling annotators to a phase that immediately
advances past itself looks exactly like the feature doing nothing, so Potato
refuses instead.

---

## Cost

The timeline costs one extra agreement pass per window on each `/admin/iaa`
load. Turn it off on a very large project:

```yaml
calibration:
  enabled: false
```

---

## Related

- [Admin Dashboard](../administration/admin_dashboard.md)
- [Training Phase](../workflow/training_phase.md)
- [Adjudication](../administration/adjudication.md)
- [Presentation Order](presentation_order.md) — the other way an agreement
  number can be confidently wrong

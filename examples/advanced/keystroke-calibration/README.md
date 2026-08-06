# Keystroke Calibration Example

Generates **labeled** writing-process data from inside your own study, so you can
fit a real classifier instead of relying on hand-set thresholds.

```bash
python potato/flask_server.py start examples/advanced/keystroke-calibration/config.yaml -p 8000
```

## The idea

Potato ships no pre-trained detection model, on purpose: there is no labeled
corpus in this repository, and shipping fitted coefficients would be fabricating
validation. The built-in rules are transparent heuristics you can read and
argue with.

But you can produce real labels without running a separate study. The training
phase asks each annotator to **copy a supplied passage verbatim**. Those sessions
are genuine *transcription* exemplars. Their normal answers in the annotation
phase are *composed* exemplars.

Same people, same keyboards, same interface — which is exactly the contrast the
published work relies on. Crossley et al. (EDM 2024) built their corpus the same
way, and reported 99% accuracy separating the two classes with a random forest.

## How the split works

The training phase and the annotation phase deliberately use the **same**
`response` textarea — identical field, identical interface, only the task
differs. The two classes are separated by `phase`, not by schema name.

Note that phase-page sessions carry `instance_id = '__phase_page__'` (phase
pages have no instance), which is why `phase` is the column to group on:

```bash
sqlite3 examples/advanced/keystroke-calibration/project.sqlite "
  SELECT phase,
         count(*)                       AS sessions,
         round(avg(iki_log_cv), 3)      AS rhythm_cv,
         round(avg(revision_ratio), 3)  AS revision,
         round(avg(pause_2s * 100.0 / final_chars), 2) AS pauses_per_100ch
  FROM typing_sessions
  WHERE final_chars > 80
  GROUP BY phase;"
```

The `training` (copied) rows should show markedly lower rhythm variance and
near-zero revision — the copy-typing signature. If they don't, the contrast in
your population is weaker than expected, and that is itself worth knowing before
you act on any flag.

!!! note
    The `phases:` block in `config.yaml` is required. A `training:` block alone
    configures the task but does **not** insert a training step into the
    workflow — annotators would go straight to the annotation phase and no
    transcription exemplars would ever be collected.

## Fitting thresholds

Once you have at least 30 usable sessions:

```bash
python -m potato.typing_detect calibrate \
    examples/advanced/keystroke-calibration/config.yaml --dry-run
```

Drop `--dry-run` to save the fit, then set `detection.calibrate: true`.

## Fitting a classifier

```python
from potato import typing_store
from potato.typing_detect import fit_supervised

task_dir, project = ".", "keystroke-calibration"
sessions = [s for u in {r["user_id"] for r in typing_store.feature_matrix(task_dir, project)}
              for s in typing_store.sessions_for_user(task_dir, project, u)]

rows   = [s for s in sessions if s["final_chars"] and s["final_chars"] > 80]
labels = [1 if s["phase"] == "training" else 0 for s in rows]   # 1 = transcribed

# `sessions_for_user` returns the full summary too, if you want features beyond
# the denormalized columns: s["summary"] is the complete TypingSummary dict.

result = fit_supervised(rows, labels, model="random_forest")
print(result["cv_accuracy_mean"], result["feature_importances"])
```

Requires `scikit-learn` (lazily imported; not a Potato dependency).

## Caveats

Copy-typing a passage is not identical to copy-typing an LLM answer — people
read differently when the text is meaningful to them, and a transcription task
is more monotonous than any real writing. Treat a model fitted this way as
calibrated for *this interface and this population*, not as a general-purpose
AI-text detector.

Tell participants the copying task is a calibration exercise. Read
[the ethics guide](../../../docs/advanced/keystroke_logging_ethics.md).

## Documentation

- [Writing-Process Detection](../../../docs/advanced/writing_process_detection.md)
- [Keystroke Logging](../../../docs/advanced/keystroke_logging.md)
- [Keystroke Logging Ethics](../../../docs/advanced/keystroke_logging_ethics.md)

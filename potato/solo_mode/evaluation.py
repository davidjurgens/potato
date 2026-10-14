"""
Scoring a prompt before trusting it: a gold set, a small trial, background jobs.

Two checks a study runs before the LLM labels the corpus:

- **Gold-set evaluation.** Label a set of items whose answers are known (the
  ``solo_mode.gold`` file) with a prompt version and report accuracy, macro F1
  and per-class precision and recall. Re-running it is free when the response
  cache is on, so each prompt version can be scored as it is written.
- **A trial.** Label N unlabelled items with a prompt and show the answers,
  confidences and reasons, so a broken prompt is caught on ten items rather
  than ten thousand.

Both run in a background thread (a gold set of a few hundred items takes
minutes against a real model), tracked by ``JobRegistry``.
"""

import csv
import logging
import os
import threading
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

#: Scheme types a gold set can score. Spans and free text need a matching
#: rule (overlap, similarity) that a single accuracy figure would hide.
GOLD_SCHEME_TYPES = ('radio', 'select', 'likert', 'multiselect')


@dataclass
class GoldItem:
    instance_id: str
    label: Any
    #: Set when the gold file carries its own text (items outside the corpus).
    text: Optional[str] = None


def _read_rows(path: str) -> List[Dict[str, Any]]:
    lower = path.lower()
    if lower.endswith(('.csv', '.tsv')):
        with open(path, newline='', encoding='utf-8') as f:
            return list(csv.DictReader(
                f, delimiter='\t' if lower.endswith('.tsv') else ','))
    from potato.filter_by_annotation import load_data_file
    return load_data_file(path)


def resolve_gold_path(path: str, task_dir: str) -> str:
    """The gold file's absolute path, checked to stay inside the project."""
    from potato.server_utils.config_module import validate_path_security
    base = os.path.abspath(task_dir or '.')
    full = path if os.path.isabs(path) else os.path.join(base, path)
    return validate_path_security(full, base)


def load_gold(path: str, task_dir: str, id_key: str = 'id',
              label_key: str = 'label', text_key: Optional[str] = None) -> List[GoldItem]:
    """Read a gold file (JSON, JSONL, CSV or TSV) into GoldItems.

    Rows without an id or a label are skipped with a warning, so a partly
    filled file scores what it has rather than failing.
    """
    rows = _read_rows(resolve_gold_path(path, task_dir))
    items, skipped = [], 0
    for row in rows:
        if not isinstance(row, dict):
            skipped += 1
            continue
        iid, label = row.get(id_key), row.get(label_key)
        if iid in (None, '') or label in (None, ''):
            skipped += 1
            continue
        text = row.get(text_key) if text_key else None
        items.append(GoldItem(str(iid), label, None if text is None else str(text)))
    if skipped:
        logger.warning("Gold file %s: skipped %d row(s) without %r or %r",
                       path, skipped, id_key, label_key)
    return items


# === Scoring ===

def _as_label_set(value) -> frozenset:
    """A multiselect answer as a set of label strings, whatever shape it has."""
    import json
    if isinstance(value, (list, tuple, set)):
        return frozenset(str(v) for v in value)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith('['):
            try:
                return frozenset(str(v) for v in json.loads(stripped))
            except ValueError:
                pass
        return frozenset(p.strip() for p in stripped.split(',') if p.strip())
    return frozenset() if value is None else frozenset([str(value)])


def _prf(tp: int, fp: int, fn: int) -> Dict[str, Optional[float]]:
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    if precision is None or recall is None or precision + recall == 0:
        f1 = 0.0 if (precision is not None and recall is not None) else None
    else:
        f1 = 2 * precision * recall / (precision + recall)
    return {'precision': precision, 'recall': recall, 'f1': f1}


def score(predictions: Dict[str, Any], gold: Dict[str, Any],
          annotation_type: str) -> Dict[str, Any]:
    """Accuracy, macro F1 and per-class P/R/F1 of ``predictions`` against ``gold``.

    An item the model failed to label (missing or None) counts as wrong, not
    as skipped: dropping failures would score a model that refuses the hard
    items above one that attempts them.
    """
    ids = list(gold)
    n = len(ids)
    errors = sum(1 for i in ids if predictions.get(i) is None)
    if annotation_type == 'multiselect':
        exact = 0
        per = defaultdict(lambda: [0, 0, 0])  # tp, fp, fn
        for i in ids:
            g = _as_label_set(gold[i])
            p = _as_label_set(predictions.get(i))
            exact += g == p
            for label in g | p:
                if label in g and label in p:
                    per[label][0] += 1
                elif label in p:
                    per[label][1] += 1
                else:
                    per[label][2] += 1
        per_class = {label: {**_prf(*c), 'support': c[0] + c[2]}
                     for label, c in sorted(per.items())}
        tp, fp, fn = (sum(c[k] for c in per.values()) for k in range(3))
        f1s = [v['f1'] for v in per_class.values() if v['f1'] is not None]
        return {
            'n_items': n, 'n_errors': errors,
            'accuracy': exact / n if n else None,  # exact set match
            'micro_f1': _prf(tp, fp, fn)['f1'],
            'macro_f1': sum(f1s) / len(f1s) if f1s else None,
            'per_class': per_class, 'confusion': None,
        }

    gold_s = {i: str(gold[i]) for i in ids}
    pred_s = {i: (None if predictions.get(i) is None else str(predictions[i]))
              for i in ids}
    correct = sum(1 for i in ids if pred_s[i] == gold_s[i])
    labels = sorted(set(gold_s.values()) | {p for p in pred_s.values() if p is not None})
    confusion = {g: dict(Counter(pred_s[i] if pred_s[i] is not None else '(no label)'
                                 for i in ids if gold_s[i] == g))
                 for g in sorted(set(gold_s.values()))}
    per_class = {}
    for label in labels:
        tp = sum(1 for i in ids if gold_s[i] == label and pred_s[i] == label)
        fp = sum(1 for i in ids if gold_s[i] != label and pred_s[i] == label)
        fn = sum(1 for i in ids if gold_s[i] == label and pred_s[i] != label)
        per_class[label] = {**_prf(tp, fp, fn), 'support': tp + fn}
    # Macro F1 over the classes the gold set contains, so a label the model
    # invented cannot pad the average with a zero it was never tested on.
    f1s = [per_class[g]['f1'] for g in set(gold_s.values())
           if per_class[g]['f1'] is not None]
    return {
        'n_items': n, 'n_errors': errors,
        'accuracy': correct / n if n else None,
        'macro_f1': sum(f1s) / len(f1s) if f1s else None,
        'per_class': per_class, 'confusion': confusion,
    }


# === Background jobs ===

@dataclass
class Job:
    id: str
    kind: str
    total: int = 0
    done: int = 0
    status: str = 'running'   # running | done | failed
    result: Any = None
    error: Optional[str] = None
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id, 'kind': self.kind, 'status': self.status,
            'total': self.total, 'done': self.done, 'result': self.result,
            'error': self.error, 'started_at': self.started_at,
            'finished_at': self.finished_at,
        }


class JobRegistry:
    """One background thread per job; at most one running job per kind."""

    def __init__(self):
        self._lock = threading.Lock()
        self._jobs: Dict[str, Job] = {}

    def running(self, kind: str) -> Optional[Job]:
        with self._lock:
            return next((j for j in self._jobs.values()
                         if j.kind == kind and j.status == 'running'), None)

    def start(self, kind: str, total: int,
              work: Callable[[Job], Any]) -> Job:
        """Run ``work(job)`` in a thread. ``work`` advances ``job.done``."""
        existing = self.running(kind)
        if existing is not None:
            return existing
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, total=total)
        with self._lock:
            self._jobs[job.id] = job

        def run():
            try:
                job.result = work(job)
                job.status = 'done'
            except Exception as e:  # reported on the job, not lost in a log
                logger.exception("Solo %s job %s failed", kind, job.id)
                job.error = str(e)
                job.status = 'failed'
            finally:
                job.finished_at = time.time()

        threading.Thread(target=run, name=f"solo-{kind}-{job.id}",
                         daemon=True).start()
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def latest(self, kind: str) -> Optional[Job]:
        with self._lock:
            jobs = [j for j in self._jobs.values() if j.kind == kind]
        return max(jobs, key=lambda j: j.started_at) if jobs else None

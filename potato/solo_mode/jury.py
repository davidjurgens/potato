"""
A jury of labeling models: several models vote and the plurality label wins.

Where ``labeling_models`` is a fallback list (the first model that answers
labels the item), a jury asks every model and aggregates. Agreement between
models is a confidence signal no single self-reported confidence gives, and
an ensemble of comparable models is more accurate than its members (see the
references in ``internal/llm-labeling-landscape-2026-10.md``: Snorkel's
multi-model labeling, CaMVo 2025).

Aggregation:

- radio, select, likert: the plurality label. A tie goes to the label whose
  voters reported more confidence in total, then to the first model's vote.
  Confidence is the winner's share of the valid votes.
- multiselect: each label is kept when more than half the valid votes
  include it. Confidence is the mean share of votes for the labels kept.

``early_stop`` (on by default) skips the remaining models once no number of
further votes could change the winner: with three models, two that agree
settle the item and the third is never called.
"""

import json
import logging
from collections import Counter, defaultdict
from typing import Any, Callable, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

#: Scheme types a jury can aggregate.
JURY_SCHEME_TYPES = ('radio', 'select', 'likert', 'multiselect')


def _labels_of(value) -> List[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str) and value.strip().startswith('['):
        try:
            return [str(v) for v in json.loads(value)]
        except ValueError:
            pass
    return [str(value)]


def decided(votes: Counter, remaining: int) -> bool:
    """Whether ``remaining`` more votes could still change the plurality."""
    if not votes:
        return False
    ranked = votes.most_common(2)
    leader = ranked[0][1]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0
    return leader > runner_up + remaining


def aggregate(results: Sequence[Any], annotation_type: str) -> Dict[str, Any]:
    """Combine LabelingResults into one label, confidence and vote record.

    Returns ``{'label', 'confidence', 'votes', 'n_valid'}``; ``label`` is None
    when no juror returned a valid label.
    """
    valid = [r for r in results if r is not None and not r.error and r.label is not None]
    votes = [{'model': r.model_name, 'label': r.label,
              'confidence': r.confidence} for r in valid]
    if not valid:
        return {'label': None, 'confidence': 0.0, 'votes': votes, 'n_valid': 0}

    if annotation_type == 'multiselect':
        counts = Counter()
        for r in valid:
            counts.update(set(_labels_of(r.label)))
        kept = sorted(label for label, c in counts.items() if c * 2 > len(valid))
        share = (sum(counts[label] for label in kept) / (len(kept) * len(valid))
                 if kept else 0.0)
        return {'label': json.dumps(kept), 'confidence': share,
                'votes': votes, 'n_valid': len(valid)}

    counts = Counter(str(r.label) for r in valid)
    confidence_sum = defaultdict(float)
    first_vote = {}
    for i, r in enumerate(valid):
        confidence_sum[str(r.label)] += float(r.confidence or 0)
        first_vote.setdefault(str(r.label), i)
    winner = max(counts, key=lambda label: (
        counts[label], confidence_sum[label], -first_vote[label]))
    return {'label': winner, 'confidence': counts[winner] / len(valid),
            'votes': votes, 'n_valid': len(valid)}


def run_jury(jurors: Sequence[Any], label_fn: Callable[[Any], Any],
             annotation_type: str, early_stop: bool = True) -> Dict[str, Any]:
    """Ask each juror in turn (``label_fn(endpoint) -> LabelingResult``).

    Returns the aggregate plus ``calls`` (juror index -> 1 for each juror
    actually called), which is what the spend record charges.
    """
    results, calls = [], {}
    tally = Counter()
    for i, juror in enumerate(jurors):
        remaining = len(jurors) - i
        if (early_stop and annotation_type != 'multiselect'
                and decided(tally, remaining)):
            break
        calls[i] = 1
        try:
            result = label_fn(juror)
        except Exception as e:
            logger.warning("Jury member %d failed: %s", i, e)
            result = None
        results.append(result)
        if result is not None and not result.error and result.label is not None:
            tally[str(result.label)] += 1
    out = aggregate(results, annotation_type)
    out['calls'] = calls
    return out

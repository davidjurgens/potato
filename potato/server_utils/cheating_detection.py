"""
LLM-cheating / fraud detection for annotations — *without* ground truth.

Up to ~40% of crowd workers were found to use LLMs covertly (2024–25). This module
flags annotators who likely echoed an LLM, using peer-prediction signals that need
no gold labels. No annotation platform ships this; it is squarely Potato's
self-hosted-crowdsourcing wheelhouse.

Two complementary, training-free signals (pure stdlib, deterministic):

1. **Correlated Agreement (CA)** — peer-prediction (Dasgupta-Ghosh / Shnayder
   et al.): a worker's agreement with peers on the *same* item minus their
   agreement with peers on *different* items. Honest workers share the task
   signal → positive CA; random/spam workers → ~0.

2. **Conditioned LLM-echo signal** — when a reference LLM's labels are available:
   a covert LLM user agrees with the LLM heavily AND, crucially, contributes **no
   independent signal** — on the items where they diverge from the LLM they agree
   with peers only at chance. High ``llm_alignment`` + low ``residual_agreement``
   (agreement with peers conditioned on both diverging from the LLM) ⇒ suspicious.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

Observation = Tuple[str, str, str]  # (worker, item, label)


@dataclass
class AnnotatorReport:
    annotator: str
    n_items: int = 0
    ca_score: Optional[float] = None            # same-item minus cross-item peer agreement
    llm_alignment: Optional[float] = None        # agreement rate with the reference LLM
    residual_agreement: Optional[float] = None   # peer agreement when both diverge from the LLM
    suspicion: float = 0.0                        # 0..1 (higher = more likely LLM-echo)
    flags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {"annotator": self.annotator, "n_items": self.n_items,
                "ca_score": _round(self.ca_score), "llm_alignment": _round(self.llm_alignment),
                "residual_agreement": _round(self.residual_agreement),
                "suspicion": round(self.suspicion, 3), "flags": self.flags}


def _round(x):
    return round(x, 3) if isinstance(x, float) else x


def _by_item(obs: List[Observation]) -> Dict[str, Dict[str, str]]:
    """{item: {worker: label}} (last label wins on dupes)."""
    d: Dict[str, Dict[str, str]] = defaultdict(dict)
    for w, i, l in obs:
        d[i][w] = l
    return d


def correlated_agreement(obs: List[Observation]) -> Dict[str, Optional[float]]:
    """Per-worker CA = P(agree with a peer on the SAME item) − P(agree with a peer
    on a DIFFERENT item). Honest workers > 0; random/duplicating workers ≈ 0.

    The cross-item term is worker-specific, as Shnayder et al. define it:
    sum_k f_w(k) * f_peer(k) over each peer the worker shares items with,
    weighted by how many items they share. A pooled sum_k p_k^2 let a
    worker who always answers the majority label score above the flag line
    on an imbalanced task (0.069 against a threshold of 0.05), because their
    same-item agreement beats the pooled baseline while equalling their own.

    None for a worker who shares no item with anyone: there is no peer to
    compare with, which is not the same as scoring 0.
    """
    by_item = _by_item(obs)
    workers = sorted({w for w, _i, _l in obs})

    label_freq: Dict[str, Dict[str, float]] = {}
    for w in workers:
        counts: Dict[str, int] = defaultdict(int)
        for it, labels in by_item.items():
            if w in labels:
                counts[labels[w]] += 1
        total = sum(counts.values()) or 1
        label_freq[w] = {label: c / total for label, c in counts.items()}

    out: Dict[str, Optional[float]] = {}
    for w in workers:
        same_hits = same_n = 0
        shared_with: Dict[str, int] = defaultdict(int)
        for labels in by_item.values():
            if w not in labels:
                continue
            for o in labels:
                if o == w:
                    continue
                shared_with[o] += 1
                same_n += 1
                same_hits += labels[o] == labels[w]
        if not same_n:
            out[w] = None
            continue
        chance = sum(
            n * sum(p * label_freq[o].get(label, 0.0)
                    for label, p in label_freq[w].items())
            for o, n in shared_with.items()) / same_n
        out[w] = round(same_hits / same_n - chance, 4)
    return out


def llm_echo_signal(obs: List[Observation], llm_labels: Dict[str, str]
                    ) -> Dict[str, Tuple[Optional[float], Optional[float]]]:
    """Per-worker ``(llm_alignment, residual_agreement)``.

    ``llm_alignment``: fraction of the worker's items where they match the LLM.
    ``residual_agreement``: among items where the worker diverges from the LLM, how
    often they still agree with a peer who *also* diverges — i.e. independent signal.
    A covert LLM user has high alignment and low residual (no independent signal).
    """
    by_item = _by_item(obs)
    workers = sorted({w for w, _i, _l in obs})
    out: Dict[str, Tuple[Optional[float], Optional[float]]] = {}
    for w in workers:
        align_hits = align_n = 0
        resid_hits = resid_n = 0
        for it, labels in by_item.items():
            if w not in labels or it not in llm_labels:
                continue
            llm = llm_labels[it]
            align_n += 1
            if labels[w] == llm:
                align_hits += 1
            else:
                # worker diverged from the LLM; do they agree with a divergent peer?
                div_peers = [labels[o] for o in labels if o != w and labels[o] != llm]
                if div_peers:
                    resid_hits += sum(1 for p in div_peers if p == labels[w])
                    resid_n += len(div_peers)
        align = (align_hits / align_n) if align_n else None
        resid = (resid_hits / resid_n) if resid_n else None
        out[w] = (align, resid)
    return out


def detect_llm_cheating(obs: List[Observation], llm_labels: Optional[Dict[str, str]] = None,
                        llm_alignment_threshold: float = 0.9,
                        residual_threshold: float = 0.34,
                        ca_threshold: float = 0.05) -> List[AnnotatorReport]:
    """Score every annotator for likely LLM-echo / low-effort behavior.

    Returns reports sorted by ``suspicion`` (desc). ``suspicion`` combines:
      - high LLM alignment with low residual independent signal (the LLM-echo tell), and
      - low Correlated-Agreement (random/duplicating tell).
    Flags: ``llm_echo`` (align ≥ threshold and residual ≤ threshold), ``low_signal``
    (CA ≤ threshold). Thresholds are conservative defaults — tune per task.
    """
    ca = correlated_agreement(obs)
    echo = llm_echo_signal(obs, llm_labels) if llm_labels else {}
    counts: Dict[str, int] = defaultdict(int)
    for w, _i, _l in obs:
        counts[w] += 1

    reports: List[AnnotatorReport] = []
    for w in sorted(counts):
        align, resid = echo.get(w, (None, None))
        r = AnnotatorReport(annotator=w, n_items=counts[w], ca_score=ca.get(w),
                            llm_alignment=align, residual_agreement=resid)
        suspicion = 0.0
        if align is not None:
            # echo suspicion: rises with alignment, falls with residual signal.
            resid_term = 1.0 if resid is None else max(0.0, 1.0 - (resid / max(residual_threshold, 1e-6)))
            echo_susp = max(0.0, (align - 0.5) / 0.5) * resid_term
            suspicion = max(suspicion, echo_susp)
            if align >= llm_alignment_threshold and (resid is None or resid <= residual_threshold):
                r.flags.append("llm_echo")
        if r.ca_score is not None and r.ca_score <= ca_threshold:
            suspicion = max(suspicion, 0.5 + 0.5 * (ca_threshold - r.ca_score))
            r.flags.append("low_signal")
        r.suspicion = min(1.0, suspicion)
        reports.append(r)
    reports.sort(key=lambda x: x.suspicion, reverse=True)
    return reports

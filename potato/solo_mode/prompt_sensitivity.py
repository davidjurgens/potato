"""
Prompt-paraphrase label stability for Solo Mode.

Baumann et al., "Large Language Model Hacking: Quantifying the Hidden Risks of
Using LLMs for Text Annotation" (arXiv:2509.08825, 2025) show that annotation
conclusions drawn from LLM labels can change with small, meaning-preserving
changes to the prompt. This module measures that directly for one labelling
prompt: it asks a generative model for paraphrases that keep the task,
label set and criteria fixed, labels the same items under each wording, and
reports how often an item's label depends on the wording.

Everything that talks to a model is injected, so the analyzer has no endpoint,
Flask or manager dependencies:

* ``generate_fn(prompt) -> str`` produces paraphrases.
* ``label_fn(prompt, instance_id, text) -> label | None`` labels one item.
  ``None`` (or an exception) is an error; that variant's label for that item
  is left out of the stability statistics and counted in ``error_count``.

Labels may be any JSON-serialisable value (strings, numbers, lists of
labels, span dicts). They are compared through a canonical form, see
:func:`canonical_label`.
"""

from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from potato.server_utils.iaa.nominal import fleiss_kappa, mean_pairwise_agreement

logger = logging.getLogger(__name__)

PREVIEW_CHARS = 160
_PLACEHOLDER_RE = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")

PARAPHRASE_INSTRUCTIONS = """You are helping test whether an annotation prompt is robust to rewording.

Write {n} paraphrases of the annotation prompt below. Each paraphrase must:
- ask for exactly the same task, with the same label set and the same criteria;
- keep every label name exactly as written, and keep the output format the same;
- keep every placeholder in curly braces (such as {{text}}) exactly as written;
- change only the wording, sentence order or tone. Do not add, drop or soften any rule.

Return ONLY a JSON array of {n} strings, with no commentary.

PROMPT:
<<<
{prompt}
>>>"""


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------

def canonical_label(label: Any) -> str:
    """
    A stable, hashable key for a label.

    Strings are used as they are (stripped of surrounding whitespace); any
    other value becomes compact JSON with sorted keys, so ``{"a":1,"b":2}``
    and ``{"b":2,"a":1}`` match and lists compare element by element. A
    string ``"1"`` and the integer ``1`` therefore share the key ``"1"``:
    models return either for the same answer, and that is not a flip.
    """
    if isinstance(label, str):
        return label.strip()
    try:
        return json.dumps(label, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        return repr(label)


def _total_variation(p: Counter, q: Counter) -> float:
    np_, nq = sum(p.values()), sum(q.values())
    if not np_ or not nq:
        return 0.0
    keys = set(p) | set(q)
    return 0.5 * sum(abs(p[k] / np_ - q[k] / nq) for k in keys)


def _preview(prompt: str) -> str:
    flat = " ".join(prompt.split())
    return flat if len(flat) <= PREVIEW_CHARS else flat[: PREVIEW_CHARS - 1] + "…"


def _nan_to_none(x: Optional[float]) -> Optional[float]:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    return x


# ---------------------------------------------------------------------------
# Paraphrase generation
# ---------------------------------------------------------------------------

def _parse_string_list(response: Any) -> List[str]:
    """Pull a list of strings out of a model response; [] when there is none."""
    if isinstance(response, list):
        data: Any = response
    else:
        if not isinstance(response, str) or not response.strip():
            return []
        text = response.strip()
        data = None
        candidates = [text]
        fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        if fence:
            candidates.append(fence.group(1).strip())
        start, end = text.find("["), text.rfind("]")
        if 0 <= start < end:
            candidates.append(text[start : end + 1])
        for cand in candidates:
            try:
                parsed = json.loads(cand)
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
            if isinstance(parsed, dict):
                parsed = next((v for v in parsed.values() if isinstance(v, list)), None)
            if isinstance(parsed, list):
                data = parsed
                break
        if data is None:
            return []
    out = []
    for entry in data:
        if isinstance(entry, dict):
            entry = entry.get("prompt") or entry.get("paraphrase") or entry.get("text")
        if isinstance(entry, str) and entry.strip():
            out.append(entry.strip())
    return out


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def generate_paraphrases(
    base_prompt: str,
    n: int,
    generate_fn: Callable[[str], str],
    *,
    preserve_terms: Sequence[str] = (),
    max_attempts: int = 3,
) -> List[str]:
    """
    Ask a generative model for up to ``n`` meaning-preserving paraphrases.

    The request tells the model to keep the label set, criteria, output
    format and ``{placeholders}`` unchanged and to return a JSON array.
    Candidates are dropped when they are empty, equal the base prompt
    (ignoring case and whitespace), duplicate an earlier candidate, are much
    shorter than the base (under a third of its length: usually a refusal or
    a fragment), lose a ``{placeholder}`` the base contains, or lose one of
    ``preserve_terms`` (pass the label names to enforce them verbatim).

    Unparseable output, a raising ``generate_fn`` or too few survivors
    trigger another request for the remainder, up to ``max_attempts`` calls.
    The result can be shorter than ``n``, including empty; it never contains
    the base prompt.
    """
    if n <= 0 or not base_prompt or not base_prompt.strip():
        return []
    placeholders = set(_PLACEHOLDER_RE.findall(base_prompt))
    required = [t for t in preserve_terms if t]
    min_len = len(base_prompt.strip()) / 3
    seen = {_norm(base_prompt)}
    accepted: List[str] = []

    for attempt in range(max_attempts):
        need = n - len(accepted)
        if need <= 0:
            break
        request = PARAPHRASE_INSTRUCTIONS.format(n=need, prompt=base_prompt)
        try:
            response = generate_fn(request)
        except Exception as exc:  # the model call is the caller's; keep going
            logger.warning("paraphrase generation attempt %d failed: %s", attempt + 1, exc)
            continue
        candidates = _parse_string_list(response)
        if not candidates:
            logger.info("paraphrase attempt %d returned no JSON list", attempt + 1)
        for cand in candidates:
            key = _norm(cand)
            if key in seen or len(cand) < min_len:
                continue
            if not placeholders.issubset(set(_PLACEHOLDER_RE.findall(cand))):
                continue
            if any(term not in cand for term in required):
                continue
            seen.add(key)
            accepted.append(cand)
            if len(accepted) >= n:
                break
    return accepted


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

@dataclass
class VariantSummary:
    """One prompt wording. Index 0 is the base prompt."""
    variant_index: int
    prompt_preview: str
    agreement_with_base: Optional[float]  # over items both labelled; None if none
    label_distribution: Dict[str, int]
    n_labeled: int
    n_errors: int
    tv_distance_from_base: Optional[float]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "variant_index": self.variant_index,
            "prompt_preview": self.prompt_preview,
            "agreement_with_base": self.agreement_with_base,
            "label_distribution": dict(self.label_distribution),
            "n_labeled": self.n_labeled,
            "n_errors": self.n_errors,
            "tv_distance_from_base": self.tv_distance_from_base,
        }


@dataclass
class SensitivityReport:
    """
    Label stability of one prompt under paraphrase.

    ``n_variants`` counts every wording, the base included. ``flip_rate`` is
    the fraction of evaluable items (two or more successful labels) whose
    labels are not all the same. ``mean_pairwise_agreement`` is the mean,
    over those items, of the fraction of variant pairs that agree (Fleiss'
    P-bar). ``fleiss_kappa`` treats the variants as raters; it is None where
    it is undefined (every label identical). ``label_distribution_shift`` is
    the largest total-variation distance between a variant's label
    distribution and the base's, over the items both labelled.
    """
    n_items: int
    n_variants: int
    n_evaluable_items: int
    flip_rate: Optional[float]
    mean_pairwise_agreement: Optional[float]
    fleiss_kappa: Optional[float]
    label_distribution_shift: Optional[float]
    per_variant: List[VariantSummary] = field(default_factory=list)
    unstable_items: List[Dict[str, Any]] = field(default_factory=list)
    n_unstable_items: int = 0
    error_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "n_items": self.n_items,
            "n_variants": self.n_variants,
            "n_evaluable_items": self.n_evaluable_items,
            "flip_rate": self.flip_rate,
            "mean_pairwise_agreement": self.mean_pairwise_agreement,
            "fleiss_kappa": self.fleiss_kappa,
            "label_distribution_shift": self.label_distribution_shift,
            "per_variant": [v.to_dict() for v in self.per_variant],
            "unstable_items": list(self.unstable_items),
            "n_unstable_items": self.n_unstable_items,
            "error_count": self.error_count,
        }


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def run_sensitivity(
    base_prompt: str,
    variants: Sequence[str],
    items: Sequence[Tuple[str, str]],
    label_fn: Callable[[str, str, str], Any],
    max_workers: int = 4,
    *,
    max_unstable_items: int = 100,
) -> SensitivityReport:
    """
    Label ``items`` under the base prompt and every variant, and compare.

    Args:
        base_prompt: the prompt in use; it becomes variant 0.
        variants: paraphrases (e.g. from :func:`generate_paraphrases`).
        items: ``(instance_id, text)`` pairs.
        label_fn: ``(prompt, instance_id, text) -> label``; ``None`` or an
            exception counts as an error for that (variant, item) cell.
        max_workers: thread pool size for the ``len(prompts) * len(items)``
            label calls.
        max_unstable_items: cap on the listed unstable items;
            ``n_unstable_items`` keeps the full count.
    """
    prompts = [base_prompt] + [v for v in variants]
    n_v = len(prompts)
    n_items = len(items)

    def _call(cell: Tuple[int, int]) -> Any:
        v, i = cell
        instance_id, text = items[i]
        try:
            return label_fn(prompts[v], instance_id, text)
        except Exception as exc:
            logger.warning("label_fn failed for variant %d, item %s: %s", v, instance_id, exc)
            return None

    cells = [(v, i) for v in range(n_v) for i in range(n_items)]
    if max_workers and max_workers > 1 and len(cells) > 1:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            results = list(pool.map(_call, cells))
    else:
        results = [_call(c) for c in cells]

    # raw[v][i] is the label as returned; keys[v][i] its canonical form.
    raw: List[List[Any]] = [[None] * n_items for _ in range(n_v)]
    keys: List[List[Optional[str]]] = [[None] * n_items for _ in range(n_v)]
    for (v, i), label in zip(cells, results):
        if label is not None:
            raw[v][i] = label
            keys[v][i] = canonical_label(label)

    errors_by_variant = [sum(1 for k in keys[v] if k is None) for v in range(n_v)]

    # Per-item stability across the variants that labelled it.
    rater_maps: List[Dict[str, str]] = []
    count_maps: List[Dict[str, int]] = []
    unstable: List[Dict[str, Any]] = []
    n_flipped = 0
    for i in range(n_items):
        got = {str(v): keys[v][i] for v in range(n_v) if keys[v][i] is not None}
        if len(got) < 2:
            continue
        rater_maps.append(got)
        count_maps.append(dict(Counter(got.values())))
        if len(set(got.values())) > 1:
            n_flipped += 1
            if len(unstable) < max_unstable_items:
                unstable.append({
                    "instance_id": items[i][0],
                    "labels_by_variant": [raw[v][i] for v in range(n_v)],
                })

    n_eval = len(rater_maps)
    flip_rate = n_flipped / n_eval if n_eval else None
    mpa = _nan_to_none(float(mean_pairwise_agreement(rater_maps))) if n_eval else None
    kappa = _nan_to_none(float(fleiss_kappa(count_maps))) if n_eval else None

    per_variant: List[VariantSummary] = []
    shifts: List[float] = []
    for v in range(n_v):
        dist = Counter(k for k in keys[v] if k is not None)
        paired = [i for i in range(n_items) if keys[v][i] is not None and keys[0][i] is not None]
        if paired:
            agree = sum(1 for i in paired if keys[v][i] == keys[0][i]) / len(paired)
            tv = _total_variation(
                Counter(keys[v][i] for i in paired), Counter(keys[0][i] for i in paired)
            )
            if v > 0:
                shifts.append(tv)
        else:
            agree, tv = None, None
        per_variant.append(VariantSummary(
            variant_index=v,
            prompt_preview=_preview(prompts[v]),
            agreement_with_base=agree,
            label_distribution=dict(dist),
            n_labeled=sum(dist.values()),
            n_errors=errors_by_variant[v],
            tv_distance_from_base=tv,
        ))

    return SensitivityReport(
        n_items=n_items,
        n_variants=n_v,
        n_evaluable_items=n_eval,
        flip_rate=flip_rate,
        mean_pairwise_agreement=mpa,
        fleiss_kappa=kappa,
        label_distribution_shift=max(shifts) if shifts else None,
        per_variant=per_variant,
        unstable_items=unstable,
        n_unstable_items=n_flipped,
        error_count=sum(errors_by_variant),
    )

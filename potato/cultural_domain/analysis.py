"""
The analyses behind the ``cultural_domain`` export.

Free lists (Weller & Romney 1988, ch. 2)
    frequency, percentage of informants, average rank, Smith's S and
    Sutrop's (2001) cognitive salience index. For item j over N lists, where
    list i has length L_i and mentions j at rank r_ij (counting from 1)::

        S_j   = (1/N) * sum over lists i that mention j of (L_i - r_ij + 1) / L_i
        CSI_j = F_j / (N * mean rank of j)

    F_j is the number of lists that mention j. Items are normalized and
    mapped through the synonym table first; an item listed twice in one list
    counts once, at its first rank, and the list length is then the number of
    distinct items.

Pile sorts (ch. 4)
    an item-by-item matrix per informant (1 when two items share a pile),
    their average (the proportion of informants who put the pair together,
    out of those who sorted both items), and an informant-by-informant
    matrix: the proportion of item pairs two informants treated the same way.

Triads (ch. 5)
    in a triad (a, b, c) whose odd item is c, the pair (a, b) is judged
    similar. Similarity of a pair = times judged similar / times shown
    together, over all informants.

Cultural consensus (Romney, Weller & Batchelder 1986)
    M_ij is the proportion of questions informants i and j answered alike,
    corrected for guessing among L options: M*_ij = (L M_ij - 1)/(L - 1).
    The model says M*_ij = D_i D_j for i != j, where D_i is informant i's
    competence, so the competences are the loadings on the first factor of
    M*. The diagonal is unknown and is estimated by iterated principal axis
    factoring: start from each row's largest off-diagonal value, take the
    first eigenvector, put the squared loadings on the diagonal, repeat.

    The answer key follows Batchelder & Romney (1988): with a uniform prior
    over the L options, the posterior of answer l to question k is
    proportional to the product, over informants who gave l, of
    ((L - 1) D_i + 1) / (1 - D_i).

Implemented from the formulas in those sources. Only numpy is used.
"""

from __future__ import annotations

import csv
import math
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np

NORMALIZE_STEPS = ("lowercase", "trim")


# ----------------------------------------------------------------------
# Free lists
# ----------------------------------------------------------------------

def normalize_item(text: str, steps: Iterable[str]) -> str:
    steps = set(steps or ())
    out = str(text)
    if "trim" in steps:
        out = " ".join(out.split())
    if "lowercase" in steps:
        out = out.lower()
    return out


def load_synonyms(path: str, steps: Iterable[str] = ()) -> Dict[str, str]:
    """``variant,canonical`` rows (an optional header row is skipped)."""
    table: Dict[str, str] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for n, row in enumerate(csv.reader(f)):
            if len(row) < 2 or not row[0].strip():
                continue
            if n == 0 and row[0].strip().lower() == "variant" and row[1].strip().lower() == "canonical":
                continue
            table[normalize_item(row[0].strip(), steps)] = normalize_item(row[1].strip(), steps)
    return table


def clean_list(items: Sequence[str], steps: Iterable[str] = (),
               synonyms: Optional[Mapping[str, str]] = None) -> List[str]:
    """Normalize, map synonyms, drop blanks and repeats (first rank kept)."""
    out: List[str] = []
    for raw in items:
        text = normalize_item(raw, steps)
        if not text.strip():
            continue
        if synonyms:
            text = synonyms.get(text, text)
        if text not in out:
            out.append(text)
    return out


def salience(lists: Sequence[Sequence[str]]) -> List[Dict[str, float]]:
    """One row per item, most salient (Smith's S) first.

    ``lists`` are already cleaned (see :func:`clean_list`). Empty lists are
    not informants and are left out of N.
    """
    lists = [lst for lst in lists if lst]
    n = len(lists)
    freq: Dict[str, int] = defaultdict(int)
    rank_sum: Dict[str, float] = defaultdict(float)
    smith: Dict[str, float] = defaultdict(float)
    first_seen: Dict[str, int] = {}
    for lst in lists:
        length = len(lst)
        for r, item in enumerate(lst, start=1):
            first_seen.setdefault(item, len(first_seen))
            freq[item] += 1
            rank_sum[item] += r
            smith[item] += (length - r + 1) / length
    rows = []
    for item in freq:
        mean_rank = rank_sum[item] / freq[item]
        rows.append({
            "item": item,
            "frequency": freq[item],
            "pct_informants": 100.0 * freq[item] / n,
            "mean_rank": mean_rank,
            "smith_s": smith[item] / n,
            "sutrop_csi": freq[item] / (n * mean_rank),
        })
    rows.sort(key=lambda r: (-r["smith_s"], -r["frequency"], first_seen[r["item"]]))
    return rows


# ----------------------------------------------------------------------
# Pile sorts
# ----------------------------------------------------------------------

def pile_matrix(piles: Mapping[str, Sequence[str]], items: Sequence[str]) -> np.ndarray:
    """1 where two items share a pile, NaN for an item this informant did not sort."""
    index = {it: k for k, it in enumerate(items)}
    n = len(items)
    m = np.zeros((n, n))
    sorted_items = set()
    for members in piles.values():
        members = [index[x] for x in members if x in index]
        sorted_items.update(members)
        for a in members:
            for b in members:
                m[a, b] = 1.0
    missing = [k for k in range(n) if k not in sorted_items]
    for k in missing:
        m[k, :] = np.nan
        m[:, k] = np.nan
    return m


def pile_aggregate(matrices: Sequence[np.ndarray]) -> np.ndarray:
    """Proportion of informants who put each pair together (of those who sorted both)."""
    stack = np.array(matrices)
    with np.errstate(invalid="ignore", divide="ignore"):
        counts = np.sum(~np.isnan(stack), axis=0)
        total = np.nansum(stack, axis=0)
        return np.where(counts > 0, total / np.maximum(counts, 1), np.nan)


def informant_agreement(matrices: Sequence[np.ndarray]) -> np.ndarray:
    """Proportion of item pairs (both sorted by both informants) treated alike."""
    k = len(matrices)
    out = np.full((k, k), np.nan)
    if not k:
        return out
    n = matrices[0].shape[0]
    iu = np.triu_indices(n, 1)
    vecs = [m[iu] for m in matrices]
    for a in range(k):
        for b in range(k):
            ok = ~np.isnan(vecs[a]) & ~np.isnan(vecs[b])
            if ok.any():
                out[a, b] = float(np.mean(vecs[a][ok] == vecs[b][ok]))
    return out


# ----------------------------------------------------------------------
# Triads
# ----------------------------------------------------------------------

def triad_similarity(answers: Iterable[Sequence], items: Sequence[str]) -> Tuple[np.ndarray, np.ndarray]:
    """``(similarity, times shown together)`` from ``[a, b, c, odd]`` answers."""
    index = {it: k for k, it in enumerate(items)}
    n = len(items)
    similar = np.zeros((n, n))
    shown = np.zeros((n, n))
    for a, b, c, odd in answers:
        if odd is None or odd not in (a, b, c):
            continue
        trio = [index[x] for x in (a, b, c) if x in index]
        if len(trio) != 3:
            continue
        for x in trio:
            for y in trio:
                if x != y:
                    shown[x, y] += 1
        pair = [index[x] for x in (a, b, c) if x != odd]
        similar[pair[0], pair[1]] += 1
        similar[pair[1], pair[0]] += 1
    with np.errstate(invalid="ignore", divide="ignore"):
        sim = np.where(shown > 0, similar / np.maximum(shown, 1), np.nan)
    np.fill_diagonal(sim, 1.0)
    return sim, shown


# ----------------------------------------------------------------------
# Cultural consensus
# ----------------------------------------------------------------------

def guessing_correction(m: float, n_options: int) -> float:
    """M* = (L M - 1) / (L - 1)."""
    return (n_options * m - 1.0) / (n_options - 1.0)


@dataclass
class ConsensusResult:
    informants: List[str]
    questions: List[str]
    competence: np.ndarray
    eigenvalues: List[float]
    ratio: Optional[float]
    answer_key: Dict[str, str]
    posterior: Dict[str, float]
    majority: Dict[str, str]
    n_answers: Dict[str, int]
    agreement: np.ndarray
    iterations: int
    converged: bool
    warnings: List[str] = field(default_factory=list)


def agreement_matrix(answers: Mapping[str, Mapping[str, str]], informants: Sequence[str],
                     n_options: Mapping[str, int]) -> np.ndarray:
    """Guessing-corrected agreement M* between informants (diagonal NaN).

    When the shared questions have different numbers of options, the chance
    rate 1/L is averaged over those questions, which reduces to
    (L M - 1)/(L - 1) when they all have L options.
    """
    k = len(informants)
    out = np.full((k, k), np.nan)
    for a in range(k):
        for b in range(a + 1, k):
            ia, ib = answers[informants[a]], answers[informants[b]]
            shared = [q for q in ia if q in ib]
            if not shared:
                continue
            m = sum(1 for q in shared if ia[q] == ib[q]) / len(shared)
            g = sum(1.0 / n_options[q] for q in shared) / len(shared)
            out[a, b] = out[b, a] = (m - g) / (1.0 - g)
    return out


def first_factor(mstar: np.ndarray, max_iter: int = 1000, tol: float = 1e-7):
    """Iterated principal axis factoring with the diagonal estimated.

    Returns ``(loadings, eigenvalues of the reduced matrix, iterations,
    converged, heywood)``.
    """
    a = np.array(mstar, dtype=float)
    k = a.shape[0]
    a[np.isnan(a)] = 0.0
    off = a.copy()
    np.fill_diagonal(off, -np.inf)
    diag = np.clip(np.max(off, axis=1), 0.0, 1.0) if k > 1 else np.ones(k)
    heywood = False
    converged = False
    it = 0
    loadings = np.zeros(k)
    for it in range(1, max_iter + 1):
        np.fill_diagonal(a, diag)
        vals, vecs = np.linalg.eigh(a)
        lam, vec = vals[-1], vecs[:, -1]
        loadings = math.sqrt(max(lam, 0.0)) * vec
        new = loadings ** 2
        if np.any(new > 1.0):
            heywood = True
            new = np.minimum(new, 1.0)
        if np.max(np.abs(new - diag)) < tol:
            diag = new
            converged = True
            break
        diag = new
    np.fill_diagonal(a, diag)
    vals = np.linalg.eigvalsh(a)[::-1]
    if loadings.sum() < 0:
        loadings = -loadings
    return loadings, [float(v) for v in vals], it, converged, heywood


def answer_key(answers: Mapping[str, Mapping[str, str]], informants: Sequence[str],
               competence: Sequence[float], options: Mapping[str, Sequence[str]],
               n_options: Optional[Mapping[str, int]] = None,
               ) -> Tuple[Dict[str, str], Dict[str, float]]:
    """Batchelder & Romney (1988) posterior answer for each question.

    Competences are clipped to [0, 0.999] here: the formula needs D < 1, and
    a negative competence (worse than guessing) is given no weight rather
    than counted as evidence against the answer it gave.
    """
    comp = {inf: min(max(float(d), 0.0), 0.999) for inf, d in zip(informants, competence)}
    key: Dict[str, str] = {}
    post: Dict[str, float] = {}
    for q, opts in options.items():
        n_opt = (n_options or {}).get(q) or max(len(opts), 2)
        logw = OrderedDict((o, 0.0) for o in opts)
        for inf in informants:
            given = answers[inf].get(q)
            if given is None:
                continue
            if given not in logw:
                logw[given] = 0.0
            d = comp[inf]
            logw[given] += math.log(((n_opt - 1) * d + 1.0) / (1.0 - d))
        names = list(logw)
        vals = np.array([logw[o] for o in names])
        p = np.exp(vals - vals.max())
        p /= p.sum()
        best = int(np.argmax(p))
        key[q] = names[best]
        post[q] = float(p[best])
    return key, post


def consensus(answers: Mapping[str, Mapping[str, str]], options: Mapping[str, Sequence[str]],
              min_answers: int = 2, n_options: Optional[Mapping[str, int]] = None) -> ConsensusResult:
    """Fit the consensus model to ``{informant: {question: answer}}``.

    ``options`` gives each question's possible answers; L is their number
    unless ``n_options`` says otherwise. Informants with fewer than
    ``min_answers`` answers are left out.
    """
    warnings: List[str] = []
    informants = sorted(i for i, a in answers.items() if len(a) >= min_answers)
    dropped = sorted(set(answers) - set(informants))
    if dropped:
        warnings.append(f"{len(dropped)} informant(s) with fewer than {min_answers} answers were left out")
    questions = sorted({q for i in informants for q in answers[i]})
    if len(informants) < 3:
        raise ValueError("cultural consensus needs at least three informants")
    n_opt = {q: (n_options or {}).get(q) or max(len(options.get(q) or ()), 2) for q in questions}
    mstar = agreement_matrix(answers, informants, n_opt)
    off = mstar[~np.eye(len(informants), dtype=bool)]
    if np.isnan(off).any():
        warnings.append("some pairs of informants answered no question in common; "
                        "their agreement was taken as 0")
    loadings, eig, iters, converged, heywood = first_factor(mstar)
    if not converged:
        warnings.append(f"the factoring did not converge in {iters} iterations")
    if heywood:
        warnings.append("an estimated competence reached 1 (a Heywood case); it was capped at 1")
    ratio = eig[0] / eig[1] if len(eig) > 1 and eig[1] > 1e-12 else None
    key, post = answer_key(answers, informants, loadings,
                           {q: list(options.get(q) or ()) for q in questions}, n_opt)
    majority: Dict[str, str] = {}
    counts: Dict[str, int] = {}
    for q in questions:
        tally: Dict[str, int] = defaultdict(int)
        for inf in informants:
            if q in answers[inf]:
                tally[answers[inf][q]] += 1
        counts[q] = sum(tally.values())
        if tally:
            top = max(tally.values())
            winners = [a for a, c in tally.items() if c == top]
            majority[q] = winners[0] if len(winners) == 1 else ""
    return ConsensusResult(informants=informants, questions=questions, competence=loadings,
                           eigenvalues=eig, ratio=ratio, answer_key=key, posterior=post,
                           majority=majority, n_answers=counts, agreement=mstar,
                           iterations=iters, converged=converged, warnings=warnings)

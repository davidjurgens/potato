"""Held-out metrics for the structured kinds.

``evaluation.score_split`` calls these with the bundle targets and the
predictions, both in the canonical forms of :mod:`potato.training.structured`:
spans as ``{start, end, label}``, and links, chains and events referring to
spans by position in the answer's own span list. Positions are turned back
into offsets before anything is compared, because a prediction's span list is
not the gold one.

Standard library only, like ``evaluation``: the worker runs it on a training
host.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

__all__ = ["score_relations", "score_coreference", "score_events",
           "score_rankings", "score_bws", "score_distributions",
           "score_glosses", "score_trees", "score_scale_preferences",
           "soft_label_scores", "hungarian"]

Span = Tuple[int, int, str]


def _f1(precision: float, recall: float) -> float:
    return 0.0 if precision + recall == 0 else \
        2 * precision * recall / (precision + recall)


def _prf(tp: int, n_pred: int, n_gold: int, prefix: str = "") -> Dict[str, float]:
    precision = tp / n_pred if n_pred else 0.0
    recall = tp / n_gold if n_gold else 0.0
    return {prefix + "precision": precision, prefix + "recall": recall,
            prefix + "f1": _f1(precision, recall)}


def _span_list(answer: Any) -> List[Span]:
    out = []
    for span in (answer or {}).get("spans") or [] if isinstance(answer, dict) else []:
        try:
            out.append((int(span["start"]), int(span["end"]),
                        str(span.get("label") or "")))
        except (KeyError, TypeError, ValueError):
            out.append((-1, -1, ""))
    return out


def _at(spans: List[Span], position: Any) -> Optional[Span]:
    try:
        return spans[int(position)]
    except (IndexError, TypeError, ValueError):
        return None


def _offsets(span: Span) -> Tuple[int, int]:
    return span[0], span[1]


# -------------------------------------------------------------- relations

def _links(answer: Any) -> Set[Tuple]:
    """Links as (member offsets..., type), member order kept for a
    directed link and sorted for an undirected one."""
    spans = _span_list(answer)
    out = set()
    for link in (answer or {}).get("links") or [] if isinstance(answer, dict) else []:
        members = [_at(spans, p) for p in link.get("spans") or []]
        if len(members) < 2 or any(m is None for m in members):
            continue
        keys = [_offsets(m) for m in members]
        if not link.get("directed"):
            keys.sort()
        out.add(tuple(keys) + (str(link.get("type") or ""),))
    return out


def _heads(answer: Any) -> Optional[Dict[Tuple[int, int], Tuple[Tuple[int, int], str]]]:
    """``{dependent offsets: (head offsets, type)}`` when the links form a
    dependency tree (directed, head first, at most one head per span);
    None otherwise."""
    spans = _span_list(answer)
    heads = {}
    for link in (answer or {}).get("links") or []:
        members = [_at(spans, p) for p in link.get("spans") or []]
        if not link.get("directed") or len(members) != 2 or None in members:
            return None
        head, dependent = _offsets(members[0]), _offsets(members[1])
        if dependent in heads:
            return None
        heads[dependent] = (head, str(link.get("type") or ""))
    return heads


def score_relations(gold: Sequence[Any], predicted: Sequence[Any],
                    trees: Optional[bool] = None) -> Dict[str, float]:
    """Link precision, recall and F1 over (member offsets, type), and
    mention F1 over (offsets, label). When the scheme is a dependency parse,
    also UAS and LAS over the gold spans.

    *trees* says whether it is one, decided over the training answers as
    hf-relation decides it; None decides over *gold*. A held-out split of a
    few small items can be all trees by chance (two spans, one link), and
    reported UAS for a run that never parsed."""
    tp = n_pred = n_gold = 0
    m_tp = m_pred = m_gold = 0
    # A dependency parse: every span has one head but the root, so an item
    # has one link fewer than spans. Any relation scheme without crossing
    # heads passed the head test alone, and reported UAS it never meant.
    from potato.training.structured import is_tree_answer
    trees = (trees is not False) and all(is_tree_answer(g) for g in gold)
    attached = labelled = n_tokens = 0
    for g, p in zip(gold, predicted):
        g_links, p_links = _links(g), _links(p)
        tp += len(g_links & p_links)
        n_pred += len(p_links)
        n_gold += len(g_links)
        g_spans, p_spans = set(_span_list(g)), set(_span_list(p))
        m_tp += len(g_spans & p_spans)
        m_pred += len(p_spans)
        m_gold += len(g_spans)
        if trees:
            g_heads = _heads(g) or {}
            p_heads = _heads(p) or {}
            for span in sorted({_offsets(s) for s in g_spans}):
                n_tokens += 1
                want, got = g_heads.get(span), p_heads.get(span)
                # A root has no head; predicting none for it is right.
                if (want and got and want[0] == got[0]) or (not want and not got):
                    attached += 1
                    if want == got:
                        labelled += 1
    out = _prf(tp, n_pred, n_gold)
    out.update(_prf(m_tp, m_pred, m_gold, "mention_"))
    if trees and n_tokens:
        out["uas"] = attached / n_tokens
        out["las"] = labelled / n_tokens
    return out


# ------------------------------------------------------------ coreference

def _clusters(answer: Any) -> List[Set[Tuple[int, int]]]:
    """Clusters as sets of mention offsets. A mention in no chain is a
    singleton cluster of its own: annotators marked it and linked it to
    nothing."""
    spans = _span_list(answer)
    clusters, chained = [], set()
    for cluster in (answer or {}).get("clusters") or [] if isinstance(answer, dict) else []:
        members = {_offsets(m) for m in (_at(spans, p) for p in cluster.get("spans") or [])
                   if m is not None}
        if members:
            clusters.append(members)
            chained |= members
    clusters.extend({_offsets(s)} for s in spans if _offsets(s) not in chained)
    return clusters


def _muc(key: List[Set], response: List[Set]) -> Tuple[float, float]:
    """MUC numerator and denominator for recall (swap for precision)."""
    numerator = denominator = 0
    for cluster in key:
        if len(cluster) < 2:
            continue
        parts = 0
        covered = set()
        for other in response:
            shared = cluster & other
            if shared:
                parts += 1
                covered |= shared
        parts += len(cluster - covered)       # each uncovered mention alone
        numerator += len(cluster) - parts
        denominator += len(cluster) - 1
    return numerator, denominator


def _b_cubed(key: List[Set], response: List[Set]) -> Tuple[float, float]:
    where = {}
    for cluster in response:
        for mention in cluster:
            where[mention] = cluster
    numerator = 0.0
    total = 0
    for cluster in key:
        for mention in cluster:
            total += 1
            other = where.get(mention)
            if other:
                numerator += len(cluster & other) / len(cluster)
    return numerator, total


def hungarian(cost: List[List[float]]) -> List[Tuple[int, int]]:
    """Minimum-cost assignment of rows to columns (Kuhn-Munkres), for a
    rectangular matrix. Returns (row, column) pairs."""
    n_rows = len(cost)
    n_cols = len(cost[0]) if cost else 0
    if not n_rows or not n_cols:
        return []
    transposed = n_rows > n_cols
    if transposed:
        cost = [list(col) for col in zip(*cost)]
        n_rows, n_cols = n_cols, n_rows
    inf = float("inf")
    u = [0.0] * (n_rows + 1)
    v = [0.0] * (n_cols + 1)
    match = [0] * (n_cols + 1)          # column -> row (1-based), 0 is free
    way = [0] * (n_cols + 1)
    for row in range(1, n_rows + 1):
        match[0] = row
        column = 0
        best = [inf] * (n_cols + 1)
        used = [False] * (n_cols + 1)
        while True:
            used[column] = True
            current, delta, next_column = match[column], inf, 0
            for j in range(1, n_cols + 1):
                if used[j]:
                    continue
                reduced = cost[current - 1][j - 1] - u[current] - v[j]
                if reduced < best[j]:
                    best[j], way[j] = reduced, column
                if best[j] < delta:
                    delta, next_column = best[j], j
            for j in range(n_cols + 1):
                if used[j]:
                    u[match[j]] += delta
                    v[j] -= delta
                else:
                    best[j] -= delta
            column = next_column
            if match[column] == 0:
                break
        while column:
            previous = way[column]
            match[column] = match[previous]
            column = previous
    pairs = [(match[j] - 1, j - 1) for j in range(1, n_cols + 1) if match[j]]
    return [(c, r) for r, c in pairs] if transposed else pairs


def _ceaf_e(key: List[Set], response: List[Set]) -> Tuple[float, int, int]:
    """Entity CEAF: the best one-to-one cluster alignment under
    phi4 = 2|K & R| / (|K| + |R|)."""
    if not key or not response:
        return 0.0, len(key), len(response)
    similarity = [[2 * len(k & r) / (len(k) + len(r)) for r in response]
                  for k in key]
    pairs = hungarian([[-s for s in row] for row in similarity])
    return sum(similarity[i][j] for i, j in pairs), len(key), len(response)


def score_coreference(gold: Sequence[Any], predicted: Sequence[Any]) -> Dict[str, float]:
    """MUC, B-cubed and entity CEAF, pooled over items, and CoNLL F1, their
    mean. Mentions are compared by offsets; a predicted mention the gold
    lacks counts against precision."""
    sums = {"muc": [0, 0, 0, 0], "b3": [0.0, 0, 0.0, 0], "ceafe": [0.0, 0, 0]}
    for g, p in zip(gold, predicted):
        key, response = _clusters(g), _clusters(p)
        rn, rd = _muc(key, response)
        pn, pd = _muc(response, key)
        sums["muc"] = [a + b for a, b in zip(sums["muc"], (rn, rd, pn, pd))]
        rn, rd = _b_cubed(key, response)
        pn, pd = _b_cubed(response, key)
        sums["b3"] = [a + b for a, b in zip(sums["b3"], (rn, rd, pn, pd))]
        sim, n_key, n_resp = _ceaf_e(key, response)
        sums["ceafe"] = [a + b for a, b in zip(sums["ceafe"], (sim, n_key, n_resp))]
    out = {}
    for name in ("muc", "b3"):
        rn, rd, pn, pd = sums[name]
        out[name + "_f1"] = _f1(pn / pd if pd else 0.0, rn / rd if rd else 0.0)
    sim, n_key, n_resp = sums["ceafe"]
    out["ceafe_f1"] = _f1(sim / n_resp if n_resp else 0.0,
                          sim / n_key if n_key else 0.0)
    out["conll_f1"] = (out["muc_f1"] + out["b3_f1"] + out["ceafe_f1"]) / 3
    return out


# ----------------------------------------------------------------- events

def _event_sets(answer: Any) -> Tuple[Set, Set]:
    spans = _span_list(answer)
    triggers, arguments = set(), set()
    for event in (answer or {}).get("events") or [] if isinstance(answer, dict) else []:
        trigger = _at(spans, event.get("trigger"))
        if trigger is None:
            continue
        kind = str(event.get("type") or "")
        triggers.add((_offsets(trigger), kind))
        for argument in event.get("arguments") or []:
            span = _at(spans, argument.get("span"))
            if span is not None:
                arguments.add((_offsets(trigger), kind, _offsets(span),
                               str(argument.get("role") or "")))
    return triggers, arguments


def score_events(gold: Sequence[Any], predicted: Sequence[Any]) -> Dict[str, float]:
    """Trigger F1 over (offsets, event type), and argument F1 over (trigger,
    event type, argument offsets, role): the usual ACE-style scores."""
    t = [0, 0, 0]
    a = [0, 0, 0]
    for g, p in zip(gold, predicted):
        gt, ga = _event_sets(g)
        pt, pa = _event_sets(p)
        t = [t[0] + len(gt & pt), t[1] + len(pt), t[2] + len(gt)]
        a = [a[0] + len(ga & pa), a[1] + len(pa), a[2] + len(ga)]
    out = _prf(*t, prefix="trigger_")
    out.update(_prf(*a, prefix="argument_"))
    return out


# ------------------------------------------------------- orders and pairs

def _tiers(payload: Any) -> List[List[str]]:
    """A ranking's tiers, best first; a tie (``"A=D"``) is one tier."""
    from potato.server_utils.iaa.dispatcher import rank_tiers
    if isinstance(payload, dict):
        payload = payload.get("order", payload.get("rank_order"))
    return rank_tiers(payload) if isinstance(payload, (str, list, tuple)) else []


def _order(payload: Any) -> List[str]:
    return [item for tier in _tiers(payload) for item in tier]


def _kendall(gold: List[List[str]], predicted: List[str]) -> Optional[float]:
    """Kendall's tau over the items both contain. A pair the annotators
    tied is not scored: no order of it is wrong."""
    tier = {item: n for n, members in enumerate(gold) for item in members}
    position = {item: i for i, item in enumerate(predicted)}
    shared = [item for item in tier if item in position]
    concordant = discordant = 0
    for i in range(len(shared)):
        for j in range(i + 1, len(shared)):
            a, b = shared[i], shared[j]
            if tier[a] == tier[b]:
                continue
            if (tier[a] < tier[b]) == (position[a] < position[b]):
                concordant += 1
            else:
                discordant += 1
    if not concordant + discordant:
        return None
    return (concordant - discordant) / (concordant + discordant)


def score_rankings(gold: Sequence[Any], predicted: Sequence[Any]) -> Dict[str, float]:
    """Kendall's tau, the share of item pairs ordered as annotators ordered
    them, and how often the top item is theirs (one of them, after a tie at
    the top). A missing prediction counts as tau -1 and a wrong top item."""
    taus, top = [], 0
    for g, p in zip(gold, predicted):
        order, tiers = _order(p), _tiers(g)
        tau = _kendall(tiers, order)
        taus.append(-1.0 if tau is None else tau)
        top += bool(order and tiers) and order[0] in tiers[0]
    mean_tau = sum(taus) / len(taus)
    return {"kendall_tau": mean_tau, "pairwise_accuracy": (mean_tau + 1) / 2,
            "top1_accuracy": top / len(gold)}


def score_bws(gold: Sequence[Any], predicted: Sequence[Any]) -> Dict[str, float]:
    best = worst = 0
    for g, p in zip(gold, predicted):
        p = p if isinstance(p, dict) else {}
        best += str(p.get("best", "")) == str(g.get("best"))
        worst += str(p.get("worst", "")) == str(g.get("worst"))
    n = len(gold)
    return {"best_accuracy": best / n, "worst_accuracy": worst / n,
            "best_worst_accuracy": (best + worst) / (2 * n)}


def score_scale_preferences(gold: Sequence[Any], predicted: Sequence[Any]) -> Dict[str, float]:
    """Whether the model prefers the response annotators preferred (a zero,
    "no preference", is not scored for direction), and the distance on the
    scale."""
    hits = directed = 0
    errors = []
    for g, p in zip(gold, predicted):
        try:
            value = float(p.get("value") if isinstance(p, dict) else p)
        except (TypeError, ValueError):
            value = None
        g = float(g)
        if g != 0:
            directed += 1
            hits += value is not None and value * g > 0
        if value is not None:
            errors.append(abs(value - g))
    return {"direction_accuracy": hits / directed if directed else 0.0,
            "mae": sum(errors) / len(errors) if errors else 0.0}


# ----------------------------------------------------------- distributions

def _shares(value: Any) -> Dict[str, float]:
    if isinstance(value, dict):
        value = value.get("distribution", value)
    out = {}
    for label, share in (value or {}).items() if isinstance(value, dict) else []:
        try:
            out[str(label)] = max(0.0, float(share))
        except (TypeError, ValueError):
            continue
    total = sum(out.values())
    return {k: v / total for k, v in out.items()} if total > 0 else {}


def _jsd(p: Dict[str, float], q: Dict[str, float]) -> float:
    """Jensen-Shannon divergence in bits: 0 for the same distribution, 1 for
    disjoint ones."""
    labels = set(p) | set(q)
    m = {k: (p.get(k, 0.0) + q.get(k, 0.0)) / 2 for k in labels}

    def kl(a):
        return sum(a[k] * math.log2(a[k] / m[k]) for k in a if a[k] > 0)
    return max(0.0, min(1.0, (kl(p) + kl(q)) / 2))


def _cross_entropy(target: Dict[str, float], predicted: Dict[str, float]) -> float:
    return -sum(share * math.log(max(predicted.get(label, 0.0), 1e-9))
                for label, share in target.items() if share > 0)


def score_distributions(gold: Sequence[Any], predicted: Sequence[Any]) -> Dict[str, float]:
    """How close predicted label distributions are to the annotators':
    1 - JSD (the headline, higher is better), JSD, cross-entropy, and
    whether the most likely label is theirs. A missing prediction is a
    JSD of 1."""
    jsds, entropies, top = [], [], 0
    for g, p in zip(gold, predicted):
        target, guess = _shares(g), _shares(p)
        if not guess:
            jsds.append(1.0)
            continue
        jsds.append(_jsd(target, guess))
        entropies.append(_cross_entropy(target, guess))
        top += max(target, key=target.get) == max(guess, key=guess.get)
    n = len(gold)
    mean = sum(jsds) / n
    out = {"distribution_agreement": 1 - mean, "jsd": mean,
           "argmax_accuracy": top / n}
    if entropies:
        out["cross_entropy"] = sum(entropies) / len(entropies)
    return out


def soft_label_scores(soft: Sequence[Dict[str, float]], predicted: Sequence[Any],
                      gold: Sequence[str], bins: int = 10) -> Dict[str, float]:
    """For a classifier trained with soft targets: distance of its
    probabilities from the annotator distribution, and expected calibration
    error against the voted labels.

    Only rows that have both a soft target and predicted probabilities
    count; empty when there are none.
    """
    pairs = [(s, p.get("probabilities"), g) for s, p, g in zip(soft, predicted, gold)
             if s and isinstance(p, dict) and isinstance(p.get("probabilities"), dict)]
    if not pairs:
        return {}
    jsds = [_jsd(_shares(s), _shares(p)) for s, p, _ in pairs]
    entropies = [_cross_entropy(_shares(s), _shares(p)) for s, p, _ in pairs]
    buckets: List[List[Tuple[float, bool]]] = [[] for _ in range(bins)]
    for _, probabilities, label in pairs:
        shares = _shares(probabilities)
        guess = max(shares, key=shares.get)
        confidence = shares[guess]
        buckets[min(bins - 1, int(confidence * bins))].append(
            (confidence, guess == label))
    ece = sum(abs(sum(c for c, _ in b) / len(b) - sum(ok for _, ok in b) / len(b))
              * len(b) for b in buckets if b) / len(pairs)
    return {"soft_jsd": sum(jsds) / len(jsds),
            "soft_cross_entropy": sum(entropies) / len(entropies),
            "ece": ece, "n_soft": float(len(pairs))}


# ----------------------------------------------------------------- glosses

def _gloss_words(answer: Any) -> List[Dict[str, str]]:
    words = (answer or {}).get("words") if isinstance(answer, dict) else None
    return [w for w in words or [] if isinstance(w, dict)]


def _morphemes(gloss: str) -> List[str]:
    import re
    return [m for m in re.split(r"[-=]", gloss or "") if m]


def score_glosses(gold: Sequence[Any], predicted: Sequence[Any]) -> Dict[str, float]:
    """Word gloss accuracy (the whole gloss right) and morpheme gloss
    accuracy (each gold morpheme gloss matched at its position), over the
    words annotators glossed. Words are aligned by position."""
    words = word_hits = morphemes = morpheme_hits = 0
    for g, p in zip(gold, predicted):
        p_words = _gloss_words(p)
        for n, word in enumerate(_gloss_words(g)):
            gloss = (word.get("gloss") or "").strip()
            if not gloss:
                continue
            guess = (p_words[n].get("gloss") or "").strip() if n < len(p_words) else ""
            words += 1
            word_hits += guess == gloss
            want, got = _morphemes(gloss), _morphemes(guess)
            morphemes += len(want)
            morpheme_hits += sum(1 for i, m in enumerate(want)
                                 if i < len(got) and got[i] == m)
    return {"word_accuracy": word_hits / words if words else 0.0,
            "morpheme_accuracy": morpheme_hits / morphemes if morphemes else 0.0,
            "n_words": float(words)}


# ------------------------------------------------------- conversation trees

def score_trees(gold: Sequence[Any], predicted: Sequence[Any]) -> Dict[str, float]:
    """Node answers pooled over trees (accuracy and macro-F1 per node
    question), and how often the selected path is exactly the annotators'."""
    from potato.training.evaluation import _macro_f1
    node_gold: List[str] = []
    node_pred: List[Optional[str]] = []
    paths = path_hits = 0
    for g, p in zip(gold, predicted):
        p = p if isinstance(p, dict) else {}
        predicted_nodes = p.get("nodes") or {}
        for node, answers in (g.get("nodes") or {}).items():
            for question, answer in (answers or {}).items():
                node_gold.append("%s=%s" % (question, answer))
                guess = (predicted_nodes.get(node) or {}).get(question)
                node_pred.append(None if guess is None
                                 else "%s=%s" % (question, guess))
        if g.get("path"):
            paths += 1
            path_hits += list(p.get("path") or []) == list(g["path"])
    out = {}
    if node_gold:
        out["node_accuracy"] = sum(1 for a, b in zip(node_gold, node_pred)
                                   if a == b) / len(node_gold)
        out["node_macro_f1"] = _macro_f1(node_gold, node_pred)
    if paths:
        out["path_accuracy"] = path_hits / paths
    return out

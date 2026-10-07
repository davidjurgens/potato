"""
Annotator and item models -- MACE, GLAD/IRT and iterative BWS -- checked by
simulating annotators whose true quality is known and asking whether the model
recovers it. The earlier tests generated their data from the model's own
assumptions, or stored values the server never writes.
"""

from __future__ import annotations

import math
import random
from unittest.mock import MagicMock

import numpy as np
import pytest

from potato.bws_tuple_generator import BwsTupleGenerator
from potato.ibws_manager import IBWSManager
from potato.item_state_management import Label
from potato.mace import MACEAlgorithm
from potato.mace_manager import MACEManager
from potato.psychometrics.irt import IRTModel


# ---------------------------------------------------------------------------
# MACE
# ---------------------------------------------------------------------------

class TestMaceRestartChoice:
    def test_restart_criterion_is_the_marginal_likelihood(self):
        """sum_i log sum_k (1/K) prod_j P(a_ij | k), computed here by brute
        force. The old criterion was a q-weighted sum with no label prior."""
        rng = np.random.RandomState(3)
        n, k, j = 12, 3, 4
        data = rng.randint(-1, k, size=(n, j))
        spamming = rng.uniform(0.5, 3.0, size=(j, 2))
        theta = rng.uniform(0.5, 3.0, size=(j, k))
        s = spamming / spamming.sum(axis=1, keepdims=True)
        t = theta / theta.sum(axis=1, keepdims=True)
        expected = 0.0
        for i in range(n):
            total = 0.0
            for truth in range(k):
                p = 1.0 / k
                for a in range(j):
                    if data[i, a] < 0:
                        continue
                    p *= s[a, 0] * (data[i, a] == truth) + s[a, 1] * t[a, data[i, a]]
                total += p
            expected += math.log(total)
        mace = MACEAlgorithm(j, k, n)
        assert mace._log_likelihood(data, None, spamming, theta) == pytest.approx(expected)


class _User:
    def __init__(self, uid, labels):
        self.uid = uid
        self.instance_id_to_label_to_value = labels

    def get_user_id(self):
        return self.uid


def _usm(users):
    usm = MagicMock()
    usm.get_user_ids.return_value = [u.uid for u in users]
    usm.get_user_state.side_effect = lambda uid: next(u for u in users if u.uid == uid)
    return usm


def _manager(scheme):
    config = {"annotation_schemes": [scheme],
              "mace": {"enabled": True, "min_annotations_per_item": 2,
                       "min_items": 3, "num_restarts": 3, "num_iters": 30,
                       "cache_results": False}}
    return MACEManager(config)


class TestMaceMultiselect:
    SCHEME = {"name": "tags", "annotation_type": "multiselect",
              "labels": [{"name": "naming"}, {"name": "other"}]}

    def _users(self):
        """Only CHECKED options are stored, as the server writes them."""
        rng = random.Random(1)
        users = []
        truth = {f"i{n}": rng.random() < 0.5 for n in range(40)}
        for uid, accuracy in (("good1", 0.95), ("good2", 0.95), ("good3", 0.95),
                              ("spam", 0.5)):
            labels = {}
            for iid, on in truth.items():
                says = on if rng.random() < accuracy else not on
                stored = {Label("tags", "other"): "true"}
                if says:
                    stored[Label("tags", "naming")] = "true"
                labels[iid] = stored
            users.append(_User(uid, labels))
        return users

    def test_unchecked_options_count_as_no(self):
        mgr = _manager(self.SCHEME)
        results = mgr.run_all_schemas(_usm(self._users()), MagicMock())
        key = next(k for k in results if "naming" in k)
        competence = results[key].competence_scores
        assert competence["spam"] < min(competence[u] for u in ("good1", "good2", "good3"))
        predicted = set(results[key].predicted_labels.values())
        assert predicted == {"0", "1"}

    def test_dict_written_options_get_results(self):
        mgr = _manager(self.SCHEME)
        results = mgr.run_all_schemas(_usm(self._users()), MagicMock())
        assert any("naming" in key for key in results)


class TestMaceRadio:
    SCHEME = {"name": "s", "annotation_type": "radio", "labels": ["pos", "neg"],
              "has_free_response": True}

    def test_free_text_is_not_the_answer(self):
        mgr = _manager(self.SCHEME)
        stored = {Label("s", "free_response"): "because", Label("s", "neg"): "true"}
        assert mgr._extract_annotation(stored, "s", "radio") == "neg"

    def test_annotators_without_an_eligible_item_get_no_score(self):
        users = []
        for uid in ("a", "b", "c"):
            users.append(_User(uid, {f"i{n}": {Label("s", "pos" if (n + ord(uid)) % 3 else "neg"): "true"}
                                     for n in range(6)}))
        users.append(_User("loner", {"solo": {Label("s", "pos"): "true"}}))
        mgr = _manager({"name": "s", "annotation_type": "radio", "labels": ["pos", "neg"]})
        results = mgr.run_all_schemas(_usm(users), MagicMock())
        result = next(iter(results.values()))
        assert "loner" not in result.competence_scores
        assert result.num_annotators == 3


# ---------------------------------------------------------------------------
# GLAD
# ---------------------------------------------------------------------------

class TestGladChance:
    @pytest.mark.parametrize("k", [2, 3, 4, 6])
    def test_a_random_guesser_is_uninformative_not_inverted(self, k):
        """Ability 0 is chance for any K. Without the logit(1/K) offset a
        uniform guesser fitted at -0.69 (K=3), -1.10 (K=4), -1.61 (K=6) and
        was shown as "inverted" (below -0.2). One fit is noisy, so average
        four seeds."""
        thetas = []
        for seed in range(4):
            rng = random.Random(seed * 10 + k)
            labels = list(range(k))
            truth = {f"i{n}": rng.choice(labels) for n in range(200)}
            obs = []
            for iid, t in truth.items():
                for good in ("g1", "g2", "g3"):
                    obs.append((iid, good, t if rng.random() < 0.85 else rng.choice(labels)))
                obs.append((iid, "random", rng.choice(labels)))
            thetas.append(IRTModel().fit(obs).ability("random").theta)
        assert abs(sum(thetas) / len(thetas)) < 0.3
        assert min(thetas) > -0.5


# ---------------------------------------------------------------------------
# Iterative BWS
# ---------------------------------------------------------------------------

def _pool(n):
    return [{"id": f"item_{v:03d}", "text": str(v), "value": v} for v in range(n)]


def _run_ibws(n, tuple_size=4, max_rounds=None, tuples_per_item=20, limit=10):
    """Drive IBWS with a perfect annotator; return true values in rank order."""
    pool = _pool(n)
    value = {p["id"]: p["value"] for p in pool}
    mgr = IBWSManager({"ibws_config": {
        "tuple_size": tuple_size, "max_rounds": max_rounds, "seed": 1,
        "tuples_per_item_per_round": tuples_per_item}}, pool, "id", "text")
    tuples = mgr.generate_round_tuples()
    store = {}
    rounds = 0
    while tuples and rounds < limit:
        rounds += 1
        for t in tuples:
            items = t["_bws_items"]
            best = max(items, key=lambda i: value[i["source_id"]])
            worst = min(items, key=lambda i: value[i["source_id"]])
            store[t["id"]] = {Label("bws", "best"): best["position"],
                              Label("bws", "worst"): worst["position"]}
        user = _User("u", store)
        usm = MagicMock()
        usm.get_all_users.return_value = [user]
        tuples = mgr.advance_round(MagicMock(), usm, "bws")
    return [value[r["item_id"]] for r in mgr.get_final_ranking()], mgr


class TestIterativeBws:
    @pytest.mark.parametrize("n", [10, 22, 30])
    def test_buckets_stay_in_rank_order(self, n):
        """Terminal buckets were appended as they stopped, so the small top
        and bottom thirds both came before a middle third that split later:
        [9,8,7, 2,1,0, 6,5,4,3] for ten items, Spearman 0.45 at N=30."""
        ranked, mgr = _run_ibws(n)
        assert mgr.completed
        spearman = pytest.importorskip("scipy.stats").spearmanr
        rho = spearman(ranked, sorted(ranked, reverse=True))[0]
        assert rho > 0.95

    def test_max_rounds_keeps_the_last_round(self):
        ranked, _ = _run_ibws(20, max_rounds=1)
        # One round of perfect annotation separates the top third from the
        # bottom; stopping before scoring returned the input order.
        assert min(ranked[:6]) > max(ranked[-6:])

    def test_pairs_terminate(self):
        ranked, mgr = _run_ibws(4, tuple_size=2)
        assert mgr.completed
        assert ranked == [3, 2, 1, 0]

    def test_every_item_is_shown_each_round(self):
        pool = _pool(100)
        tuples = BwsTupleGenerator(pool, "id", "text", tuple_size=4,
                                   num_tuples=50, seed=7).generate()
        shown = {i["source_id"] for t in tuples for i in t["_bws_items"]}
        assert len(shown) == 100
        assert all(len({i["source_id"] for i in t["_bws_items"]}) == 4 for t in tuples)

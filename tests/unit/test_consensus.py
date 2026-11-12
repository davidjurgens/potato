"""Unit tests for Dawid-Skene consensus (D4)."""

import pytest

from potato.server_utils.consensus import dawid_skene, majority_vote, ConsensusResult


class TestMajorityVote:
    def test_basic_majority(self):
        obs = [("w1", "i1", "a"), ("w2", "i1", "a"), ("w3", "i1", "b")]
        assert majority_vote(obs)["i1"] == "a"

    def test_tie_breaks_first_seen(self):
        obs = [("w1", "i1", "b"), ("w2", "i1", "a")]
        assert majority_vote(obs)["i1"] == "b"


class TestDawidSkene:
    def test_unanimous(self):
        obs = [(f"w{w}", "i1", "yes") for w in range(3)]
        r = dawid_skene(obs)
        assert r.labels["i1"] == "yes"
        assert r.confidence["i1"] == pytest.approx(1.0, abs=1e-6)

    def test_single_class(self):
        obs = [("w1", "i1", "x"), ("w1", "i2", "x")]
        r = dawid_skene(obs)
        assert r.labels == {"i1": "x", "i2": "x"}

    def test_reliable_worker_outweighs_spammer(self):
        # Ground truth: items 0-9 = 'a', items 10-19 = 'b'.
        # w_good is always correct; w_spam always says 'a'. Two more decent workers.
        truth = {f"i{n}": ("a" if n < 10 else "b") for n in range(20)}
        obs = []
        for n in range(20):
            t = truth[f"i{n}"]
            obs.append(("w_good", f"i{n}", t))
            obs.append(("w_ok1", f"i{n}", t if n % 5 else ("b" if t == "a" else "a")))
            obs.append(("w_ok2", f"i{n}", t if n % 4 else ("b" if t == "a" else "a")))
            obs.append(("w_spam", f"i{n}", "a"))  # always 'a'
        r = dawid_skene(obs)
        # DS should recover the truth on the 'b' items despite the spammer voting 'a'
        recovered = sum(1 for n in range(20) if r.labels[f"i{n}"] == truth[f"i{n}"])
        assert recovered >= 19
        # the spammer is rated less reliable than the perfect worker
        assert r.reliability["w_spam"] < r.reliability["w_good"]

    def test_consensus_can_beat_majority_with_spammers(self):
        # 3 spammers all say 'a', 2 good workers say the truth 'b' on a hard item.
        # Majority would pick 'a'; DS, having learned the spammers are unreliable
        # from other items, can favor the good workers.
        obs = []
        truth = {}
        for n in range(12):
            t = "a" if n < 6 else "b"
            truth[f"i{n}"] = t
            obs.append(("good1", f"i{n}", t))
            obs.append(("good2", f"i{n}", t))
            # spammers correct on easy 'a' items, wrong (say 'a') on 'b' items
            for s in ("s1", "s2", "s3"):
                obs.append((s, f"i{n}", "a"))
        r = dawid_skene(obs)
        # good workers must be rated more reliable than spammers
        assert min(r.reliability["good1"], r.reliability["good2"]) > max(
            r.reliability["s1"], r.reliability["s2"], r.reliability["s3"])

    def test_empty(self):
        r = dawid_skene([])
        assert r.labels == {} and isinstance(r, ConsensusResult)

    def test_confidence_in_unit_interval(self):
        obs = [("w1", "i1", "a"), ("w2", "i1", "b"), ("w3", "i1", "a")]
        r = dawid_skene(obs)
        assert 0.0 <= r.confidence["i1"] <= 1.0

    def test_to_dict_rounds(self):
        obs = [("w1", "i1", "a"), ("w2", "i1", "a")]
        d = dawid_skene(obs).to_dict()
        assert "labels" in d and "reliability" in d and "classes" in d


class TestConsensusReferenceOutputs:
    """Batch integration used by dataset curation."""

    def test_consensus_reference_outputs_maps_back_to_value_maps(self):
        from potato.eval_datasets.annotation_aggregation import consensus_reference_outputs
        # 2 good annotators + 1 spammer over 4 instances; scheme 'sentiment'.
        truth = {"i0": "pos", "i1": "pos", "i2": "neg", "i3": "neg"}
        store = {}
        for u in ("good1", "good2"):
            for iid, t in truth.items():
                store[(u, iid)] = {"sentiment": {t: True}}
        for iid in truth:  # spammer always 'pos'
            store[("spam", iid)] = {"sentiment": {"pos": True}}

        def getter(user, iid):
            return store.get((user, iid), {})

        refs, meta = consensus_reference_outputs(
            list(truth.keys()), ["good1", "good2", "spam"], getter)
        assert meta["method"] == "dawid_skene"
        # negatives recovered despite the spammer
        assert refs["i2"]["sentiment"] == {"neg": True}
        assert refs["i3"]["sentiment"] == {"neg": True}
        # spammer rated less reliable than a good annotator
        rel = meta["reliability"]["sentiment"]
        assert rel["spam"] < rel["good1"]

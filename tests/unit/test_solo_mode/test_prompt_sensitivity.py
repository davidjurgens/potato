"""Tests for potato.solo_mode.prompt_sensitivity (Baumann et al. 2025)."""

import json

import pytest

from potato.solo_mode.prompt_sensitivity import (
    canonical_label,
    generate_paraphrases,
    run_sensitivity,
)

BASE = "Classify the sentiment of {text} as positive, negative or neutral. Answer with one label."
V1 = "Read {text} and decide whether its sentiment is positive, negative or neutral. Give one label."
V2 = "What is the sentiment of {text}: positive, negative or neutral? Reply with a single label."

ITEMS = [(f"i{n}", f"text {n}") for n in range(10)]
BASE_LABELS = {f"i{n}": ("pos" if n < 5 else "neg") for n in range(10)}


def _by_prompt(table):
    """label_fn that looks up (prompt, instance_id) in a dict of dicts."""
    def fn(prompt, instance_id, text):
        return table[prompt][instance_id]
    return fn


class TestStability:
    def test_identical_variants(self):
        labels = {f"i{n}": ["pos", "neg", "neu"][n % 3] for n in range(10)}
        r = run_sensitivity(BASE, [V1, V2], ITEMS, _by_prompt({BASE: labels, V1: labels, V2: labels}))
        assert r.n_items == 10 and r.n_variants == 3
        assert r.flip_rate == 0.0
        assert r.fleiss_kappa == pytest.approx(1.0)
        assert r.mean_pairwise_agreement == pytest.approx(1.0)
        assert r.label_distribution_shift == 0.0
        assert [v.agreement_with_base for v in r.per_variant] == [1.0, 1.0, 1.0]
        assert r.unstable_items == [] and r.error_count == 0

    def test_one_variant_flips_half_and_shifts_distribution(self):
        flipped = {i: "neg" for i in BASE_LABELS}  # items 0-4 pos -> neg
        r = run_sensitivity(
            BASE, [V1, V2], ITEMS,
            _by_prompt({BASE: BASE_LABELS, V1: BASE_LABELS, V2: flipped}),
        )
        assert r.flip_rate == pytest.approx(0.5)
        # base 50/50 pos/neg, V2 all neg: 0.5 * (|0.5-0| + |0.5-1|) = 0.5
        assert r.label_distribution_shift == pytest.approx(0.5)
        assert [v.agreement_with_base for v in r.per_variant] == [1.0, 1.0, 0.5]
        assert r.per_variant[2].label_distribution == {"neg": 10}
        # Fleiss P-bar: 5 items at 1/3 and 5 at 1 -> 2/3.
        assert r.mean_pairwise_agreement == pytest.approx(2 / 3)
        # p_pos=1/3, p_neg=2/3, Pe=5/9; kappa = (2/3 - 5/9) / (4/9) = 0.25
        assert r.fleiss_kappa == pytest.approx(0.25)
        assert sorted(u["instance_id"] for u in r.unstable_items) == ["i0", "i1", "i2", "i3", "i4"]
        assert r.unstable_items[0]["labels_by_variant"] == ["pos", "pos", "neg"]

    def test_flip_rate_and_tv_measure_different_things(self):
        # Half the items move (2 pos->neg, 3 neg->pos) but the marginal only
        # moves from 5/5 to 6/4: flip rate 0.5, TV 0.1. A balanced swap
        # (r2) flips 0.2 of the items and leaves TV at 0.
        swapped = dict(BASE_LABELS)
        for n in (0, 1, 5, 6, 7):
            i = f"i{n}"
            swapped[i] = "neg" if swapped[i] == "pos" else "pos"
        r = run_sensitivity(BASE, [V1], ITEMS, _by_prompt({BASE: BASE_LABELS, V1: swapped}))
        assert r.flip_rate == pytest.approx(0.5)
        assert r.label_distribution_shift == pytest.approx(0.1)
        r2 = run_sensitivity(BASE, [V1], ITEMS, _by_prompt({
            BASE: BASE_LABELS,
            V1: {**BASE_LABELS, "i0": "neg", "i5": "pos"},
        }))
        assert r2.flip_rate == pytest.approx(0.2)
        assert r2.label_distribution_shift == 0.0

    def test_no_variants(self):
        r = run_sensitivity(BASE, [], ITEMS, _by_prompt({BASE: BASE_LABELS}))
        assert r.n_variants == 1 and r.n_evaluable_items == 0
        assert r.flip_rate is None and r.fleiss_kappa is None
        assert r.label_distribution_shift is None

    def test_all_one_label_kappa_is_undefined_not_perfect(self):
        same = {i: "pos" for i in BASE_LABELS}
        r = run_sensitivity(BASE, [V1], ITEMS, _by_prompt({BASE: same, V1: same}))
        assert r.flip_rate == 0.0 and r.fleiss_kappa is None
        json.dumps(r.to_dict())  # no NaN in the payload

    def test_threaded_and_serial_agree(self):
        flipped = {**BASE_LABELS, "i3": "neg"}
        fn = _by_prompt({BASE: BASE_LABELS, V1: flipped, V2: BASE_LABELS})
        a = run_sensitivity(BASE, [V1, V2], ITEMS, fn, max_workers=8).to_dict()
        b = run_sensitivity(BASE, [V1, V2], ITEMS, fn, max_workers=1).to_dict()
        assert a == b


class TestErrors:
    def test_none_and_exceptions_are_errors(self):
        def fn(prompt, instance_id, text):
            if prompt == V1 and instance_id == "i0":
                return None
            if prompt == V1 and instance_id == "i1":
                raise RuntimeError("endpoint down")
            if prompt == V1:
                return "neg"  # flips i2-i4 (pos -> neg)
            return BASE_LABELS[instance_id]

        r = run_sensitivity(BASE, [V1], ITEMS, fn)
        assert r.error_count == 2
        assert [v.n_errors for v in r.per_variant] == [0, 2]
        assert r.per_variant[1].n_labeled == 8
        # i0 and i1 have one label left, so they are not evaluable.
        assert r.n_evaluable_items == 8
        assert r.flip_rate == pytest.approx(3 / 8)
        assert r.per_variant[1].agreement_with_base == pytest.approx(5 / 8)
        assert "i0" not in {u["instance_id"] for u in r.unstable_items}

    def test_error_cell_excluded_but_item_kept_with_other_variants(self):
        def fn(prompt, instance_id, text):
            if prompt == V1 and instance_id == "i0":
                return None
            return BASE_LABELS[instance_id]

        r = run_sensitivity(BASE, [V1, V2], ITEMS, fn)
        assert r.n_evaluable_items == 10 and r.flip_rate == 0.0
        assert r.error_count == 1

    def test_everything_fails(self):
        r = run_sensitivity(BASE, [V1], ITEMS, lambda p, i, t: None)
        assert r.error_count == 20 and r.flip_rate is None
        assert r.per_variant[1].agreement_with_base is None


class TestUnhashableLabels:
    def test_canonical_label(self):
        assert canonical_label({"b": 2, "a": 1}) == canonical_label({"a": 1, "b": 2})
        assert canonical_label(["x", "y"]) != canonical_label(["y", "x"])
        assert canonical_label(" pos ") == "pos"
        assert canonical_label(1) == canonical_label("1")

    def test_list_and_dict_labels(self):
        items = ITEMS[:4]
        base = {
            "i0": ["joy", "trust"], "i1": {"start": 0, "end": 4, "label": "PER"},
            "i2": ["anger"], "i3": [],
        }
        variant = {
            "i0": ["joy", "trust"], "i1": {"label": "PER", "end": 4, "start": 0},
            "i2": ["anger", "fear"], "i3": [],
        }
        r = run_sensitivity(BASE, [V1], items, _by_prompt({BASE: base, V1: variant}))
        assert r.flip_rate == pytest.approx(0.25)
        assert r.unstable_items == [
            {"instance_id": "i2", "labels_by_variant": [["anger"], ["anger", "fear"]]}
        ]
        json.dumps(r.to_dict())


class TestGenerateParaphrases:
    def test_parses_plain_json(self):
        fn = lambda req: json.dumps([V1, V2])
        assert generate_paraphrases(BASE, 2, fn) == [V1, V2]

    def test_request_carries_the_constraints(self):
        seen = []
        generate_paraphrases(BASE, 2, lambda req: seen.append(req) or json.dumps([V1, V2]))
        assert BASE in seen[0] and "same label set" in seen[0] and "{text}" in seen[0]

    def test_fenced_and_wrapped_output(self):
        fenced = "Sure! Here they are:\n```json\n" + json.dumps([V1, V2]) + "\n```\nHope that helps."
        assert generate_paraphrases(BASE, 2, lambda r: fenced) == [V1, V2]
        wrapped = json.dumps({"paraphrases": [{"prompt": V1}, V2, 7, None]})
        assert generate_paraphrases(BASE, 2, lambda r: wrapped, max_attempts=1) == [V1, V2]

    def test_never_returns_base_and_dedupes(self):
        out = generate_paraphrases(
            BASE, 3,
            lambda r: json.dumps([BASE, "  " + BASE.upper() + " ", V1, V1, " ".join(V1.split()) + " "]),
            max_attempts=1,
        )
        assert out == [V1]

    def test_drops_lost_placeholders_terms_and_fragments(self):
        no_placeholder = V1.replace("{text}", "the passage")
        no_label = V2.replace("neutral", "mixed")
        fragment = "Sentiment of {text}?"
        out = generate_paraphrases(
            BASE, 4,
            lambda r: json.dumps([no_placeholder, no_label, fragment, V1]),
            preserve_terms=["positive", "negative", "neutral"],
            max_attempts=1,
        )
        assert out == [V1]

    def test_junk_output_retries_then_gives_up(self):
        calls = []
        def fn(req):
            calls.append(req)
            return "I cannot help with that." if len(calls) < 3 else "[not json"
        assert generate_paraphrases(BASE, 2, fn, max_attempts=3) == []
        assert len(calls) == 3

    def test_retries_for_the_remainder(self):
        replies = iter([json.dumps([V1]), "garbage", json.dumps([V1, V2])])
        reqs = []
        def fn(req):
            reqs.append(req)
            return next(replies)
        assert generate_paraphrases(BASE, 2, fn) == [V1, V2]
        assert "Write 1 paraphrases" in reqs[1]

    def test_raising_generate_fn(self):
        def fn(req):
            raise TimeoutError("slow")
        assert generate_paraphrases(BASE, 2, fn) == []

    def test_degenerate_inputs(self):
        assert generate_paraphrases(BASE, 0, lambda r: json.dumps([V1])) == []
        assert generate_paraphrases("  ", 2, lambda r: json.dumps([V1])) == []
        assert generate_paraphrases(BASE, 1, lambda r: None) == []

    def test_feeds_run_sensitivity(self):
        variants = generate_paraphrases(BASE, 2, lambda r: json.dumps([V1, V2]))
        r = run_sensitivity(BASE, variants, ITEMS, lambda p, i, t: BASE_LABELS[i])
        assert r.n_variants == 3 and r.flip_rate == 0.0

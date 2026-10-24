"""
Triad designs for triad_test (potato/cultural_domain/triads.py) and their
browser twin (potato/static/triad-design.js).

The page builds the plan itself, so the JavaScript is run in Node and must
give the same triads, in the same order and positions, as the Python.
"""

import itertools
import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest

from potato.cultural_domain import triads as T

REPO = Path(__file__).resolve().parents[2]
JS = REPO / "potato" / "static" / "triad-design.js"


def _pair_counts(design, n):
    counts = {pair: 0 for pair in itertools.combinations(range(n), 2)}
    for t in design:
        for pair in itertools.combinations(sorted(t), 2):
            counts[pair] += 1
    return counts


@pytest.mark.parametrize("n", [n for n in range(3, 46) if n % 6 in (1, 3)])
def test_steiner_system_has_every_pair_exactly_once(n):
    design = T.steiner_design(n)
    assert len(design) == n * (n - 1) // 6
    assert all(len(set(t)) == 3 and all(0 <= x < n for x in t) for t in design)
    assert set(_pair_counts(design, n).values()) == {1}


@pytest.mark.parametrize("n", [4, 5, 6, 8, 10, 11, 12])
def test_no_steiner_system_for_other_sizes(n):
    assert not T.steiner_exists(n)
    with pytest.raises(ValueError):
        T.steiner_design(n)


@pytest.mark.parametrize("n", [4, 5, 8, 10, 11, 12, 14, 16, 17, 20, 23])
def test_sample_covers_every_pair_at_most_twice(n):
    design = T.sample_design(n, None, seed=12345)
    counts = _pair_counts(design, n).values()
    assert min(counts) >= 1 and max(counts) <= 2
    assert len(set(design)) == len(design)
    assert len(design) >= T.schoenheim_bound(n)


@pytest.mark.parametrize("n,size,seed", [(10, 30, 7), (10, 30, 99), (8, 20, 1), (12, 50, 3)])
def test_sample_of_a_fixed_size_keeps_pairs_close_to_even(n, size, seed):
    """Greedy, so not optimal: every pair appears, and counts stay within 2."""
    design = T.sample_design(n, size, seed=seed)
    assert len(design) == size and len(set(design)) == size
    counts = list(_pair_counts(design, n).values())
    assert min(counts) >= 1 and max(counts) - min(counts) <= 2
    items = [sum(x in t for t in design) for x in range(n)]
    assert max(items) - min(items) <= 2


def test_auto_picks_complete_then_steiner_then_sample():
    assert T.resolve_design(6) == "complete"          # 20 triads
    assert T.resolve_design(7) == "steiner"           # 35 > 20, 7 = 1 mod 6
    assert T.resolve_design(8) == "sample"
    assert T.resolve_design(9) == "steiner"
    # A cap below the design's size falls back to a sample of that size.
    assert T.resolve_design(6, max_triads=10) == "sample"
    assert T.resolve_design(13, max_triads=20) == "sample"   # 26 triads
    assert T.resolve_design(13, max_triads=26) == "steiner"
    assert T.resolve_design(8, "steiner") == "sample"
    kind, design = T.build_design([str(i) for i in range(6)], "s", max_triads=10)
    assert kind == "sample" and len(design) == 10


def test_complete_design_is_every_triad():
    assert len(T.complete_design(6)) == math.comb(6, 3)
    assert len(set(T.complete_design(6))) == 20


def test_plan_is_stable_per_participant_and_differs_between_them():
    domain = list("abcdefghi")
    a1 = T.shown_plan(domain, "triads", "alice", "item1")[1]
    a2 = T.shown_plan(domain, "triads", "alice", "item1")[1]
    b = T.shown_plan(domain, "triads", "bob", "item1")[1]
    other_item = T.shown_plan(domain, "triads", "alice", "item2")[1]
    assert a1 == a2
    assert a1 != b and a1 != other_item
    # Same triads (as sets), only order and positions differ.
    assert sorted(map(sorted, a1)) == sorted(map(sorted, b))


def test_fnv1a_known_values():
    # Published FNV-1a 32-bit test vectors.
    assert T.fnv1a("") == 0x811C9DC5
    assert T.fnv1a("a") == 0xE40C292C
    assert T.fnv1a("foobar") == 0xBF9CF968


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_javascript_builds_the_same_plan():
    cases = [(n, user, inst, design, cap)
             for n in (3, 5, 6, 7, 8, 9, 10, 13, 14)
             for user, inst in (("alice", "item_1"), ("Zoë", "__phase_page__"))
             for design, cap in (("auto", None), ("sample", 12))]
    script = f"""
    const D = require({json.dumps(str(JS))});
    const cases = {json.dumps(cases)};
    const out = cases.map(([n, user, inst, design, cap]) => {{
        const domain = Array.from({{length: n}}, (_, i) => 'item ' + i + ' é');
        return D.plan(domain, 'triads', user, inst, design, cap);
    }});
    console.log(JSON.stringify({{plans: out, hashes: ['', 'a', 'foobar', 'Zoë'].map(D.fnv1a)}}));
    """
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    got = json.loads(result.stdout)
    assert got["hashes"] == [T.fnv1a(s) for s in ("", "a", "foobar", "Zoë")]
    for (n, user, inst, design, cap), js in zip(cases, got["plans"]):
        domain = [f"item {i} é" for i in range(n)]
        kind, plan = T.shown_plan(domain, "triads", user, inst, design, cap)
        assert js["design"] == kind, (n, design)
        assert js["triads"] == plan, (n, user, design)

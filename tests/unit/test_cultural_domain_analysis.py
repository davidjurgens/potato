"""
Free-list salience, pile-sort and triad similarity, and the cultural
consensus model (potato/cultural_domain/analysis.py), checked against small
cases worked by hand and against synthetic data with known competences.
"""

import numpy as np
import pytest

from potato.cultural_domain import analysis as A


def _rows(lists):
    return {r["item"]: r for r in A.salience(lists)}


def test_smiths_s_and_sutrop_csi_on_three_lists():
    """
    Three lists, N = 3:

        list 1 (L=3): apple, banana, cherry
        list 2 (L=2): banana, apple
        list 3 (L=4): apple, date, banana, cherry

    Smith's S = (1/N) sum over lists mentioning j of (L - r + 1)/L:

        apple   (3/3 + 1/2 + 4/4) / 3 = 2.5 / 3      = 0.833333
        banana  (2/3 + 2/2 + 2/4) / 3 = 2.166667 / 3 = 0.722222
        cherry  (1/3 + 1/4) / 3       = 0.583333 / 3 = 0.194444
        date    (3/4) / 3                            = 0.25

    Sutrop's CSI = F / (N * mean rank):

        apple   F=3, mean rank 4/3  -> 3 / (3 * 4/3) = 0.75
        banana  F=3, mean rank 2    -> 3 / (3 * 2)   = 0.5
        cherry  F=2, mean rank 3.5  -> 2 / (3 * 3.5) = 0.190476
        date    F=1, mean rank 2    -> 1 / (3 * 2)   = 0.166667
    """
    lists = [["apple", "banana", "cherry"], ["banana", "apple"], ["apple", "date", "banana", "cherry"]]
    rows = _rows(lists)
    expected_s = {"apple": 2.5 / 3, "banana": (2 / 3 + 1 + 0.5) / 3,
                  "cherry": (1 / 3 + 1 / 4) / 3, "date": 0.25}
    expected_csi = {"apple": 0.75, "banana": 0.5, "cherry": 2 / 10.5, "date": 1 / 6}
    for item in expected_s:
        assert rows[item]["smith_s"] == pytest.approx(expected_s[item])
        assert rows[item]["sutrop_csi"] == pytest.approx(expected_csi[item])
    assert rows["apple"]["frequency"] == 3 and rows["apple"]["pct_informants"] == pytest.approx(100.0)
    assert rows["cherry"]["mean_rank"] == pytest.approx(3.5)
    assert [r["item"] for r in A.salience(lists)] == ["apple", "banana", "date", "cherry"]


def test_empty_lists_are_not_informants():
    assert _rows([["apple"], []])["apple"]["pct_informants"] == pytest.approx(100.0)


def test_normalize_synonyms_and_repeats_before_counting(tmp_path):
    path = tmp_path / "syn.csv"
    path.write_text("variant,canonical\nApples,apple\nmangos,mango\n")
    synonyms = A.load_synonyms(str(path), ["lowercase", "trim"])
    assert synonyms == {"apples": "apple", "mangos": "mango"}
    cleaned = A.clean_list(["  Apples ", "MANGOS", "apple", "Kiwi  fruit", ""],
                           ["lowercase", "trim"], synonyms)
    # "apple" repeats "Apples" after mapping and keeps its first rank.
    assert cleaned == ["apple", "mango", "kiwi fruit"]
    assert A.clean_list(["Apple", "apple"], []) == ["Apple", "apple"]


def test_guessing_correction():
    assert A.guessing_correction(1.0, 4) == pytest.approx(1.0)
    assert A.guessing_correction(0.25, 4) == pytest.approx(0.0)      # chance level
    assert A.guessing_correction(0.5, 4) == pytest.approx(1 / 3)
    assert A.guessing_correction(0.5, 2) == pytest.approx(0.0)
    assert A.guessing_correction(0.0, 2) == pytest.approx(-1.0)


def test_agreement_matrix_applies_the_correction():
    answers = {"a": {"q1": "x", "q2": "y", "q3": "x", "q4": "y"},
               "b": {"q1": "x", "q2": "y", "q3": "y", "q4": "x"}}
    m = A.agreement_matrix(answers, ["a", "b"], {q: 2 for q in ("q1", "q2", "q3", "q4")})
    assert m[0, 1] == pytest.approx(0.0)       # half alike with L = 2: chance
    m4 = A.agreement_matrix(answers, ["a", "b"], {q: 4 for q in ("q1", "q2", "q3", "q4")})
    assert m4[0, 1] == pytest.approx((4 * 0.5 - 1) / 3)


def _synthetic(competence, n_questions, n_options, seed):
    rng = np.random.default_rng(seed)
    opts = [f"o{k}" for k in range(n_options)]
    key = {f"q{k:03d}": opts[rng.integers(n_options)] for k in range(n_questions)}
    answers = {}
    for i, d in enumerate(competence):
        answers[f"inf{i:02d}"] = {q: (z if rng.random() < d else opts[rng.integers(n_options)])
                                  for q, z in key.items()}
    return answers, key, {q: opts for q in key}


@pytest.mark.parametrize("n_options", [2, 4])
def test_consensus_recovers_competence_and_answer_key(n_options):
    truth = np.linspace(0.9, 0.3, 20)
    answers, key, options = _synthetic(truth, 80, n_options, seed=11)
    result = A.consensus(answers, options)
    est = dict(zip(result.informants, result.competence))
    est = np.array([est[f"inf{i:02d}"] for i in range(len(truth))])
    assert result.converged
    assert np.corrcoef(est, truth)[0, 1] > 0.85
    assert np.mean(np.abs(est - truth)) < 0.12
    assert sum(result.answer_key[q] == z for q, z in key.items()) / len(key) >= 0.97
    assert result.ratio is not None and result.ratio > 3


def test_competence_weighting_beats_the_majority():
    """Two experts outvote three guessers who agree with each other by chance."""
    experts = {"e1": 0.95, "e2": 0.95}
    answers = {}
    opts = ["a", "b", "c", "d"]
    # Built so the competences are estimable: 40 questions where the experts
    # match the key and the others guess, plus one question where all three
    # guessers happen to give the same wrong answer.
    rng = np.random.default_rng(3)
    key = {f"q{k}": opts[k % 4] for k in range(40)}
    for name in experts:
        answers[name] = dict(key)
    for g in ("g1", "g2", "g3"):
        answers[g] = {q: opts[rng.integers(4)] for q in key}
    key["trap"] = "a"
    answers["e1"]["trap"] = answers["e2"]["trap"] = "a"
    for g in ("g1", "g2", "g3"):
        answers[g]["trap"] = "b"
    result = A.consensus(answers, {q: opts for q in key})
    assert result.majority["trap"] == "b"
    assert result.answer_key["trap"] == "a"


def test_answer_key_posterior_matches_the_formula():
    """One question, L = 2, competences 0.8 and 0.5 say "x", 0.6 says "y".

    weight(l) = product over informants who said l of ((L-1)D + 1)/(1 - D):
        x: (1.8/0.2) * (1.5/0.5) = 27
        y: 1.6/0.4               = 4
    so P(x) = 27/31.
    """
    answers = {"a": {"q": "x"}, "b": {"q": "x"}, "c": {"q": "y"}}
    key, post = A.answer_key(answers, ["a", "b", "c"], [0.8, 0.5, 0.6], {"q": ["x", "y"]})
    assert key["q"] == "x"
    assert post["q"] == pytest.approx(27 / 31)


def test_an_informant_who_contradicts_everyone_gets_a_negative_competence():
    truth = [0.9, 0.85, 0.8, 0.8, 0.75, 0.7]
    answers, key, options = _synthetic(truth, 60, 2, seed=5)
    flip = {"o0": "o1", "o1": "o0"}
    answers["contrarian"] = {q: flip[z] for q, z in key.items()}
    result = A.consensus(answers, options)
    comp = dict(zip(result.informants, result.competence))
    assert comp["contrarian"] < 0
    assert all(comp[i] > 0.4 for i in comp if i != "contrarian")
    assert sum(result.answer_key[q] == z for q, z in key.items()) / len(key) >= 0.95


def test_consensus_needs_three_informants():
    with pytest.raises(ValueError):
        A.consensus({"a": {"q1": "x", "q2": "y"}, "b": {"q1": "x", "q2": "y"}}, {"q1": ["x", "y"]})


def test_pile_sort_matrices():
    items = ["apple", "lemon", "lime", "pear"]
    sorts = [
        {"sweet": ["apple", "pear"], "sour": ["lemon", "lime"]},
        {"all": ["apple", "pear", "lemon"], "green": ["lime"]},
        {"citrus": ["lemon", "lime"]},                 # apple and pear not sorted
    ]
    mats = [A.pile_matrix(s, items) for s in sorts]
    agg = A.pile_aggregate(mats)
    i = {x: k for k, x in enumerate(items)}
    assert agg[i["apple"], i["pear"]] == pytest.approx(1.0)       # 2 of 2 who sorted both
    assert agg[i["lemon"], i["lime"]] == pytest.approx(2 / 3)
    assert agg[i["apple"], i["lemon"]] == pytest.approx(1 / 2)
    sim = A.informant_agreement(mats)
    # Informants 1 and 2, pair by pair (same pile 1/0): apple-lemon 0/1,
    # apple-lime 0/0, apple-pear 1/1, lemon-lime 1/0, lemon-pear 0/1,
    # lime-pear 0/0, so 3 of 6 alike.
    assert sim[0, 1] == pytest.approx(0.5)
    assert sim[0, 2] == pytest.approx(1.0)                         # only lemon-lime shared
    assert sim[0, 0] == pytest.approx(1.0)


def test_triad_similarity_counts_the_pair_left_together():
    items = ["a", "b", "c", "d"]
    answers = [["a", "b", "c", "c"],       # a-b similar
               ["b", "a", "d", "d"],       # a-b similar
               ["a", "c", "d", "a"],       # c-d similar
               ["a", "b", "c", None]]      # unanswered: ignored
    sim, shown = A.triad_similarity(answers, items)
    assert sim[0, 1] == pytest.approx(1.0) and shown[0, 1] == 2
    assert sim[2, 3] == pytest.approx(1.0)
    assert sim[0, 2] == pytest.approx(0.0) and shown[0, 2] == 2
    assert sim[1, 3] == pytest.approx(0.0)
    assert sim[1, 2] == pytest.approx(0.0) and shown[1, 2] == 1
    assert sim[0, 0] == 1.0

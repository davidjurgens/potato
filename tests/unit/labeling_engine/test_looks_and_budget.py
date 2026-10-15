"""
When a certification spends a look, and how the human-label budget binds.

A look is one test of the cert labels at a stricter level. Spending one per
planner pass, per new dev label, or per cascade restarted at look 1 would
each break the stated confidence or drain it while people label.
"""

import random

import pytest

from potato.labeling_engine.allocation import designs
from potato.labeling_engine.service import Engine
from potato.persistence import clear_db_cache

from .test_engine_service import LABELS, _answer_all, _config, _items


@pytest.fixture(autouse=True)
def _fresh_db():
    clear_db_cache()
    yield
    clear_db_cache()


def _study(tmp_path, n=1500, **kw):
    items = _items(n)
    eng = Engine(_config(tmp_path, **kw))
    scheme = eng.scheme("sentiment")
    eng.register_items(items)
    eng.predict(scheme, items)
    return eng, scheme, items


def _answer(eng, items, requests, user="ann1"):
    gold = {i.item_id: i.data["gold"] for i in items}
    for r in requests:
        eng.record_human_label(r.item_id, r.schema, gold[r.item_id], user, request_id=r.id)


SR_ONLY = [{"id": "acc", "kind": "selective_risk", "schema": "sentiment",
            "error": 0.1, "confidence": 0.9}]


def test_dev_labels_that_pick_the_same_rule_spend_no_look(tmp_path):
    eng, scheme, items = _study(tmp_path, contracts=SR_ONLY)
    eng.draw_calibration(scheme, [i.item_id for i in items], rate=0.2)
    reqs = eng.store.requests(status=["open"], purpose=["calibration"])
    cert = [r for r in reqs if r.split == "cert"]
    dev = [r for r in reqs if r.split == "dev"]
    _answer(eng, items, cert + dev[:-15])
    prev = eng.certify(scheme)["acc"]
    assert prev["looks_spent"] == 1
    # Dev grows one label at a time; the cert labels are untouched. With
    # retest, a look is spent exactly when dev changed the rule under test.
    reused = 0
    for r in dev[-15:]:
        _answer(eng, items, [r])
        res = eng.certify(scheme, retest=True)["acc"]
        same = res["signature"] == prev["signature"]
        assert res["looks_spent"] == prev["looks_spent"] + (0 if same else 1)
        reused += same
        prev = res
    assert reused >= 10


def test_polling_certify_while_dev_grows_spends_no_look(tmp_path):
    """Found by potato-skill (F1). Each spent look lowered the level, which
    moved dev's rule, which made the next certify a new test: certify after
    every 5 dev labels took a met contract to look 6 and insufficient on
    unchanged cert labels."""
    eng, scheme, items = _study(tmp_path, contracts=SR_ONLY)
    eng.draw_calibration(scheme, [i.item_id for i in items], rate=0.3)
    reqs = eng.store.requests(status=["open"], purpose=["calibration"])
    cert = [r for r in reqs if r.split == "cert"]
    dev = [r for r in reqs if r.split == "dev"]
    _answer(eng, items, cert + dev[:20])
    first = eng.certify(scheme)["acc"]
    assert first["looks_spent"] == 1
    moved = 0
    for k in range(20, min(len(dev), 120), 5):
        _answer(eng, items, dev[k:k + 5])
        res = eng.certify(scheme)["acc"]
        assert res["looks_spent"] == 1 and res["status"] == first["status"]
        moved += bool(res.get("retest_available"))
    # Dev did move the rule at some point, and the result says how to test it.
    assert moved
    assert eng.certify(scheme, retest=True)["acc"]["looks_spent"] == 2


def test_a_renamed_contract_keeps_its_looks(tmp_path):
    """Found by potato-skill (F2): renaming `acc` started the new id at look 1,
    so rename-and-retry undid the look count."""
    eng, scheme, items = _study(tmp_path, contracts=SR_ONLY)
    eng.draw_calibration(scheme, [i.item_id for i in items], rate=0.2)
    _answer_all(eng, items)
    eng.certify(scheme)
    cfg = _config(tmp_path, contracts=[dict(SR_ONLY[0], id="accuracy")])
    eng2 = Engine(cfg)
    res = eng2.certify(eng2.scheme("sentiment"))["accuracy"]
    assert res["looks_spent"] == 2
    # A second contract that still exists keeps its own count.
    both = _config(tmp_path, contracts=[dict(SR_ONLY[0], id="accuracy"),
                                        dict(SR_ONLY[0], id="strict", error=0.08)])
    eng3 = Engine(both)
    out = eng3.certify(eng3.scheme("sentiment"))
    assert out["strict"]["looks_spent"] == 2      # acc, the retired id, spent 1


def test_a_changed_cascade_on_the_same_cert_labels_is_the_next_look(tmp_path):
    eng, scheme, items = _study(tmp_path, contracts=SR_ONLY)
    eng.draw_calibration(scheme, [i.item_id for i in items], rate=0.2)
    _answer_all(eng, items)
    a = eng.certify(scheme)["acc"]
    assert a["looks_spent"] == 1
    # Same study, a source parameter tweaked: a new cascade hash.
    cfg = _config(tmp_path, contracts=SR_ONLY)
    cfg["labeling_engine"]["sources"][0]["options"]["separability"] = 0.81
    eng2 = Engine(cfg)
    scheme2 = eng2.scheme("sentiment")
    assert eng2.cascade_hash(scheme2) != eng.cascade_hash(scheme)
    eng2.predict(scheme2, items)
    b = eng2.certify(scheme2)["acc"]
    assert b["looks_spent"] == 2 and b["alpha"] < a["alpha"]


def test_planner_passes_do_not_retest_a_met_contract(tmp_path):
    eng, scheme, items = _study(tmp_path, contracts=SR_ONLY)
    ids = [i.item_id for i in items]
    eng.draw_calibration(scheme, ids, rate=0.15, seed=1)
    _answer_all(eng, items)
    met = eng.certify(scheme, auto=True)["acc"]
    assert met["status"] == "met" and met["looks_spent"] == 1
    # Five more agreeing cert labels arrive, one planner pass each.
    eng.draw_calibration(scheme, ids, rate=0.05, seed=2)
    more = eng.store.requests(status=["open"], purpose=["calibration"])
    for r in more[:5]:
        _answer(eng, items, [r])
        res = eng.certify(scheme, auto=True)["acc"]
        assert res["status"] == "met" and res["looks_spent"] == 1
    # Even after the labels have grown well past the next milestone.
    eng.draw_calibration(scheme, ids, rate=0.15, seed=3)
    _answer_all(eng, items)
    res = eng.certify(scheme, auto=True)["acc"]
    assert res["status"] == "met" and res["looks_spent"] == 1
    # An explicit certify tests now.
    assert eng.certify(scheme)["acc"]["looks_spent"] == 2


def _met_study(tmp_path):
    eng, scheme, items = _study(tmp_path, contracts=SR_ONLY)
    eng.draw_calibration(scheme, [i.item_id for i in items], rate=0.15)
    _answer_all(eng, items)
    met = eng.certify(scheme, auto=True)["acc"]
    assert met["status"] == "met" and met["looks_spent"] == 1
    return eng, scheme, items


def _cert_items(eng, scheme, correct, n=10):
    """Cert requests where the machine's delivered answer is right (or wrong)."""
    view = eng.view(scheme)
    by_item = {c.item_id: c for c in view.split("cert")}
    out = []
    for r in eng.store.requests(status=["done"], purpose=["calibration"]):
        c = by_item.get(r.item_id)
        if r.split == "cert" and c is not None and c.output is not None \
                and view.correct(c.output.value, r.label) == correct:
            out.append((r, c.output.value))
    assert len(out) >= n
    return out[:n]


def _flip(eng, rows):
    for r, machine in rows:
        eng.record_human_label(r.item_id, r.schema,
                               next(l for l in LABELS if l != machine), r.user_id)


def _more_coming(eng, scheme, items):
    """An ongoing study: another wave of calibration requests still open."""
    eng.draw_calibration(scheme, [i.item_id for i in items], rate=0.2, seed=77)
    assert eng.store.requests(status=["open"], purpose=["calibration"])


def test_an_edit_and_its_revert_cost_no_look(tmp_path):
    """Found by potato-skill (F5): each planner pass after a cert-label edit
    spent a look, so three changes of mind cost five looks and sent the
    accepted labels to pending_recert."""
    eng, scheme, items = _met_study(tmp_path)
    _more_coming(eng, scheme, items)
    eng.resolve(scheme)
    accepted = sum(1 for r in eng.store.resolved(schema="sentiment") if r.origin == "auto")
    rows = _cert_items(eng, scheme, correct=True)
    _flip(eng, rows)                                  # adds errors
    res = eng.certify(scheme, auto=True)["acc"]
    assert res["status"] == "met" and res["looks_spent"] == 1
    assert res["next_test_at"] and any("edited after look 1" in n for n in res["notes"])
    # Stored, so status (and the admin page and certificate) show it.
    shown = eng.contract_status(scheme)["acc"]
    assert shown["next_test_at"] == res["next_test_at"]
    assert any("10 cert label(s) edited after look 1" in n for n in shown["notes"])
    eng.resolve(scheme)
    assert not [x for x in eng.store.resolved(schema="sentiment")
                if x.status == "pending_recert"]
    for r, machine in rows:                           # and back
        eng.record_human_label(r.item_id, r.schema, machine, r.user_id)
    res = eng.certify(scheme, auto=True)["acc"]
    assert res["status"] == "met" and res["looks_spent"] == 1
    eng.resolve(scheme)
    assert sum(1 for x in eng.store.resolved(schema="sentiment")
               if x.origin == "auto") == accepted
    assert eng.store.looks_used("acc") == 1


def test_an_edit_that_removes_an_error_keeps_the_look(tmp_path):
    eng, scheme, items = _met_study(tmp_path)
    for r, machine in _cert_items(eng, scheme, correct=False, n=3):
        eng.record_human_label(r.item_id, r.schema, machine, r.user_id)
    res = eng.certify(scheme)["acc"]          # even an explicit certify
    assert res["status"] == "met" and res["looks_spent"] == 1
    assert eng.store.looks_used("acc") == 1


def test_an_edit_that_adds_errors_is_tested_on_an_explicit_certify(tmp_path):
    eng, scheme, items = _met_study(tmp_path)
    _flip(eng, _cert_items(eng, scheme, correct=True))
    res = eng.certify(scheme)["acc"]
    assert res["looks_spent"] == 2
    assert res["cert_labels"] != {}


def test_an_unmet_contract_waits_for_label_growth_between_planner_passes(tmp_path):
    strict = [dict(SR_ONLY[0], error=0.07)]
    eng, scheme, items = _study(tmp_path, contracts=strict)
    ids = [i.item_id for i in items]
    eng.draw_calibration(scheme, ids, rate=0.1, seed=1)
    _answer_all(eng, items)
    first = eng.certify(scheme, auto=True)["acc"]
    assert first["status"] != "met" and first["looks_spent"] == 1
    n0 = first["n_cert"] + first["n_dev"]
    eng.draw_calibration(scheme, ids, rate=0.01, seed=2)
    few = eng.store.requests(status=["open"], purpose=["calibration"])
    _answer(eng, items, few[:3])
    held = eng.certify(scheme, auto=True)["acc"]
    assert held["looks_spent"] == 1
    assert held["next_test_at"] == max(int(-(-n0 * 1.25 // 1)), n0 + 10)
    # Enough new labels: the planner tests again.
    eng.draw_calibration(scheme, ids, rate=0.1, seed=3)
    _answer_all(eng, items)
    assert eng.certify(scheme, auto=True)["acc"]["looks_spent"] == 2


def test_a_ppi_that_could_not_run_spends_no_look(tmp_path):
    eng, scheme, items = _study(tmp_path, contracts=[
        {"id": "prev", "kind": "ppi", "schema": "sentiment"}])
    ids = [i.item_id for i in items]
    eng.draw_calibration(scheme, ids, rate=0.002, seed=1)    # a handful
    for k in range(2):
        open_ = eng.store.requests(status=["open"], purpose=["calibration"])
        _answer(eng, items, open_[:1])
        res = eng.certify(scheme)["prev"]
        assert not res["ran"] and res["looks_spent"] == 0


def test_a_new_prediction_pass_is_not_served_the_old_result(tmp_path):
    eng, scheme, items = _study(tmp_path, n=1200, contracts=SR_ONLY)
    eng.draw_calibration(scheme, [i.item_id for i in items], rate=0.2)
    _answer_all(eng, items)
    a = eng.certify(scheme)["acc"]
    extra = _items(1600)[1200:]
    eng.register_items(extra)
    eng.predict(scheme, extra)
    b = eng.certify(scheme)["acc"]
    assert b is not a and b["pred_mark"] != a["pred_mark"]


# === Human-label budget ====================================================

def test_capped_inclusion_matches_simulation():
    n, r, m = 200, 0.3, 50
    rng = random.Random(1)
    trials, hits = 40000, 0
    for _ in range(trials):
        sel = [i for i in range(n) if rng.random() < r]
        if len(sel) > m:
            sel = rng.sample(sel, m)
        hits += 0 in sel
    assert designs.capped_inclusion(r, n, m) == pytest.approx(hits / trials, abs=0.006)
    assert designs.capped_inclusion(r, n, n) == r


@pytest.mark.parametrize("block", [
    {},
    {"humans": {"overlap": 1.0, "overlap_k": 3}},
])
def test_the_human_label_budget_caps_the_calibration_sample(tmp_path, block):
    eng, scheme, items = _study(tmp_path, budgets={"human_labels": 60}, **block)
    eng.draw_calibration(scheme, [i.item_id for i in items], rate=0.2)
    opened = [r for r in eng.store.requests() if r.purpose != "organic"]
    assert 0 < len(opened) <= 60
    assert eng.store.get_budget("human_labels").spent == len(opened)
    # The recorded inclusion probability is the capped design's, the same
    # for every item, so the sample is still uniform.
    pis = {round(r.inclusion_prob, 12) for r in opened}
    assert len(pis) == 1 and pis.pop() < 0.2
    # Nothing more can be opened.
    eng.draw_calibration(scheme, [i.item_id for i in items], rate=0.2, seed=9)
    assert len([r for r in eng.store.requests() if r.purpose != "organic"]) == len(opened)


def test_organic_labels_do_not_spend_the_budget(tmp_path):
    eng, scheme, items = _study(tmp_path, budgets={"human_labels": 10})
    eng.record_human_label(items[0].item_id, "sentiment", "positive", "ann1")
    assert eng.human_labels_remaining() == 10


# === Answers and serving ===================================================

def test_a_revisited_answer_updates_the_request_instead_of_adding_a_vote(tmp_path):
    eng, scheme, items = _study(tmp_path)
    eng.draw_calibration(scheme, [i.item_id for i in items], rate=0.05)
    [r] = eng.claim_requests("ann1", 1)
    eng.record_human_label(r.item_id, r.schema, "negative", "ann1")
    eng.record_human_label(r.item_id, r.schema, "negative", "ann1")   # autosave
    eng.record_human_label(r.item_id, r.schema, "neutral", "ann1")    # an edit
    rows = eng.store.requests(item_id=r.item_id, schema="sentiment")
    assert [(x.purpose, x.label) for x in rows] == [("calibration", "neutral")]
    eng.resolve(scheme)
    [res] = [x for x in eng.store.resolved(schema="sentiment") if x.item_id == r.item_id]
    assert res.value == "neutral"


def test_a_re_save_leaves_the_overlap_copy_for_another_person(tmp_path):
    """Found by potato-skill (R1): the second save closed the item's unassigned
    overlap copy with the same person's label, so one person counted as two
    raters."""
    eng, scheme, items = _study(tmp_path, n=300,
                                humans={"overlap": 1.0, "overlap_k": 2})
    eng.draw_calibration(scheme, [i.item_id for i in items], rate=0.1)
    [r] = eng.claim_requests("u1", 1)
    copies = [x for x in eng.store.requests(item_id=r.item_id, schema="sentiment")
              if x.id != r.id]
    assert copies and all(c.status == "open" for c in copies)
    eng.record_human_label(r.item_id, r.schema, "negative", "u1")
    eng.record_human_label(r.item_id, r.schema, "negative", "u1")
    eng.record_human_label(r.item_id, r.schema, "neutral", "u1")
    rows = {x.id: x for x in eng.store.requests(item_id=r.item_id, schema="sentiment")}
    assert rows[r.id].status == "done" and rows[r.id].label == "neutral"
    assert all(rows[c.id].status == "open" for c in copies)
    # A person who was never served the copy does not close it either: they
    # did not see the item blind. Their label is organic.
    eng.record_human_label(r.item_id, r.schema, "negative", "u3")
    rows = {x.id: x for x in eng.store.requests(item_id=r.item_id, schema="sentiment")}
    assert all(rows[c.id].status == "open" for c in copies)
    [org] = [x for x in eng.store.requests(item_id=r.item_id, schema="sentiment")
             if x.user_id == "u3"]
    assert org.purpose == "organic" and org.inclusion_prob is None
    # Served to another person, the copy closes with their label.
    [c2] = [x for x in eng.claim_requests("u2", 1000) if x.item_id == r.item_id]
    eng.record_human_label(r.item_id, r.schema, "negative", "u2")
    done = eng.store.requests(item_id=r.item_id, schema="sentiment", status=["done"])
    assert {x.user_id for x in done if x.purpose != "organic"} == {"u1", "u2"}


def test_calibration_is_served_in_random_order_mixing_dev_and_cert(tmp_path):
    eng, scheme, items = _study(tmp_path)
    eng.draw_calibration(scheme, [i.item_id for i in items], rate=0.2)
    reqs = eng.store.requests(status=["open"], purpose=["calibration"])
    served = eng.claim_requests("ann1", 40)
    # Not file order, and both splits in the first 40.
    assert [r.id for r in served] != sorted(r.id for r in served)
    assert {r.split for r in served} == {"dev", "cert"}
    assert len(reqs) > 40


class _MemStore:
    """Just what designs.draw touches."""

    def __init__(self):
        self.meta, self.opened, self._n = {}, [], 0

    def requests(self, **_):
        return []

    def add_design(self, design):
        self._n += 1
        return self._n

    def get_items_meta(self, ids, key):
        return {}

    def upsert_items(self, rows):
        for r in rows:
            self.meta[r["item_id"]] = r["meta"]

    def add_requests(self, reqs):
        self.opened = list(reqs)
        return list(range(len(reqs)))


def test_a_capped_draw_with_unequal_rates_records_the_true_inclusion():
    """Found by potato-skill (F3): with two strata under a cap, one uniform cut
    across both dropped items with a probability nothing recorded, and the
    Horvitz-Thompson total came out 3% low."""
    ids = [f"a{k}" for k in range(100)] + [f"b{k}" for k in range(100)]
    rates = {i: (0.6 if i[0] == "a" else 0.2) for i in ids}
    trials = 3000
    hits = {"a": 0, "b": 0}
    pi = {}
    for seed in range(trials):
        st = _MemStore()
        designs.draw(st, "s", ids, rates, seed=seed, max_requests=40)
        assert len(st.opened) <= 40
        for r in st.opened:
            hits[r.item_id[0]] += 1
            pi[r.item_id[0]] = r.inclusion_prob
    for g in "ab":
        assert hits[g] / (trials * 100) == pytest.approx(pi[g], abs=0.006), g
    # Horvitz-Thompson for the share of stratum-a items: unbiased.
    assert (hits["a"] / pi["a"]) / (trials * 200) == pytest.approx(0.5, abs=0.01)


def test_a_cap_over_more_distinct_rates_than_requests_is_refused():
    ids = [f"i{k}" for k in range(10)]
    with pytest.raises(ValueError, match="distinct"):
        designs.draw(_MemStore(), "s", ids, {i: 0.1 + k / 100 for k, i in enumerate(ids)},
                     max_requests=5)


def test_reverting_to_a_tested_state_restores_that_result(tmp_path):
    eng, scheme, items = _met_study(tmp_path)
    rows = _cert_items(eng, scheme, correct=True)
    _flip(eng, rows)
    assert eng.certify(scheme)["acc"]["looks_spent"] == 2
    for r, machine in rows:
        eng.record_human_label(r.item_id, r.schema, machine, r.user_id)
    res = eng.certify(scheme)["acc"]
    assert res["looks_spent"] == 1 and res["status"] == "met"
    assert eng.store.looks_used("acc") == 2


def test_an_edit_after_growth_waits_for_new_labels(tmp_path):
    """Found by potato-skill (F5 gap): labels kept arriving after met, which
    auto rightly ignored, so the first edit found the look-based milestone
    already passed and re-tested at once."""
    eng, scheme, items = _study(tmp_path, contracts=SR_ONLY)
    ids = [i.item_id for i in items]
    eng.draw_calibration(scheme, ids, rate=0.15, seed=1)
    _answer_all(eng, items)
    met = eng.certify(scheme, auto=True)["acc"]
    assert met["status"] == "met"
    eng.draw_calibration(scheme, ids, rate=0.1, seed=2)        # grow ~1.6x
    _answer_all(eng, items)
    assert eng.certify(scheme, auto=True)["acc"]["looks_spent"] == 1
    _more_coming(eng, scheme, items)
    _flip(eng, _cert_items(eng, scheme, correct=True, n=3))
    res = eng.certify(scheme, auto=True)["acc"]
    assert res["status"] == "met" and res["looks_spent"] == 1
    n_now = res["n_cert"] + res["n_dev"]
    assert res["next_test_at"] >= n_now + 10
    # Another edit in the same burst keeps the same milestone.
    _flip(eng, _cert_items(eng, scheme, correct=True, n=2))
    assert eng.certify(scheme, auto=True)["acc"]["next_test_at"] == res["next_test_at"]


def test_human_work_remaining_until_the_budget_or_the_labels_run_out(tmp_path):
    eng, scheme, items = _study(tmp_path, n=300, budgets={"human_labels": 40})
    assert eng.human_work_remaining() == "the planner has not run yet"
    eng.planner_passes = 1
    assert eng.human_work_remaining() is not None          # nothing drawn yet
    eng.draw_calibration(scheme, [i.item_id for i in items], rate=0.2)
    assert eng.human_work_remaining() == "requests are open"
    for seed in range(1, 50):
        _answer_all(eng, items)
        if eng.human_labels_remaining() == 0:
            break
        assert eng.human_work_remaining() is not None    # budget left, labels missing
        eng.draw_calibration(scheme, [i.item_id for i in items], rate=0.2, seed=seed)
    # The 40 requests the budget allows are answered; nothing more can open.
    assert eng.human_labels_remaining() == 0
    assert eng.human_work_remaining() is None


def test_a_person_at_their_cap_is_finished_while_requests_stay_open(tmp_path):
    """Found by potato-skill (A5): max_annotations_per_user 3 with 24 requests
    open left the annotator on "come back later" forever."""
    from types import SimpleNamespace
    from potato.labeling_engine.integration import hooks
    eng, scheme, items = _study(tmp_path, n=300)
    eng.draw_calibration(scheme, [i.item_id for i in items], rate=0.2)
    person = SimpleNamespace(max_assignments=3,
                             get_assigned_instance_ids=lambda: {"a", "b", "c"})
    other = SimpleNamespace(max_assignments=3,
                            get_assigned_instance_ids=lambda: {"a"})
    old = hooks._ENGINE
    hooks._ENGINE = eng
    try:
        assert hooks.finished_for_user(person) == "per-annotator cap reached"
        assert hooks.finished_for_user(other) is None
    finally:
        hooks._ENGINE = old


def test_an_edit_with_no_labels_left_to_come_is_tested_at_once(tmp_path):
    """Found by potato-skill (F5b): with the sample finished, the milestone
    could never be reached, and auto held met for good on cert labels an
    explicit test said did not pass."""
    eng, scheme, items = _met_study(tmp_path)
    assert not eng.store.requests(status=["open", "assigned"], purpose=["calibration"])
    _flip(eng, _cert_items(eng, scheme, correct=True))
    res = eng.certify(scheme, auto=True)["acc"]
    assert res["looks_spent"] == 2


def test_an_overall_and_a_per_class_contract_both_met_accept_labels(tmp_path):
    """Found while answering potato-skill's I9: with a per-class contract on
    the scheme, the overall contract's rule was looked up by class, found
    nothing, and nothing was accepted even with both met."""
    both = [dict(SR_ONLY[0], per_class=False),
            dict(SR_ONLY[0], id="per_class", per_class=True, error=0.2)]
    eng, scheme, items = _study(tmp_path, contracts=both)
    eng.draw_calibration(scheme, [i.item_id for i in items], rate=0.2)
    _answer_all(eng, items)
    res = eng.certify(scheme)
    assert res["acc"]["status"] == "met" and res["per_class"]["status"] == "met"
    eng.resolve(scheme)
    assert sum(1 for r in eng.store.resolved(schema="sentiment") if r.origin == "auto") > 100


def test_an_unmet_contract_blocks_acceptance_on_its_scheme(tmp_path):
    """potato-skill's design question on I9: contracts declare what the
    labels must satisfy, so a met 10% contract beside an unmet 1% one
    accepts nothing."""
    both = [dict(SR_ONLY[0], per_class=False),
            dict(SR_ONLY[0], id="strict", per_class=True, error=0.01)]
    eng, scheme, items = _study(tmp_path, contracts=both)
    eng.draw_calibration(scheme, [i.item_id for i in items], rate=0.2)
    _answer_all(eng, items)
    res = eng.certify(scheme)
    assert res["acc"]["status"] == "met" and res["strict"]["status"] != "met"
    assert "until it is met" in res["strict"]["statement"]
    eng.resolve(scheme)
    assert not [r for r in eng.store.resolved(schema="sentiment") if r.origin == "auto"]


def test_a_held_request_is_work_even_on_an_item_the_page_counts_as_done(tmp_path):
    """Found in the Chrome pass: on a two-scheme item the annotator saved one
    question while the request they held was for the other, and the page said
    "nothing to label" because held items were excluded."""
    eng, scheme, items = _study(tmp_path, n=300)
    eng.draw_calibration(scheme, [i.item_id for i in items], rate=0.05)
    [r] = eng.claim_requests("u1", 1)
    for x in eng.store.requests(status=["open"]):
        eng.store.update_request(x.id, status="cancelled")
    assert eng.has_work_for("u1", exclude=[r.item_id])
    eng.record_human_label(r.item_id, r.schema, "positive", "u1")
    assert not eng.has_work_for("u1", exclude=[r.item_id])


def test_a_ppi_estimate_is_redone_as_labels_arrive(tmp_path):
    """Found by potato-skill (J1): the planner held a met ppi at its first
    look, so the interval used 23 labels while 171 existed."""
    eng, scheme, items = _study(tmp_path, contracts=[
        {"id": "prev", "kind": "ppi", "schema": "sentiment"}])
    ids = [i.item_id for i in items]
    eng.draw_calibration(scheme, ids, rate=0.2)
    reqs = eng.store.requests(status=["open"], purpose=["calibration"])
    _answer(eng, items, reqs[:40])
    first = eng.certify(scheme, auto=True)["prev"]
    assert first["status"] == "met" and first["looks_spent"] == 1
    _answer(eng, items, reqs[40:45])                 # a few more: wait
    assert eng.certify(scheme, auto=True)["prev"]["looks_spent"] == 1
    _answer(eng, items, reqs[45:])                   # the sample is complete
    last = eng.certify(scheme, auto=True)["prev"]
    assert last["looks_spent"] == 2
    assert last["n_at_look"] == last["n_cert"] + last["n_dev"] == len(reqs)


def test_a_ppi_estimate_is_redone_when_the_sample_completes_before_a_milestone(tmp_path):
    eng, scheme, items = _study(tmp_path, contracts=[
        {"id": "prev", "kind": "ppi", "schema": "sentiment"}])
    eng.draw_calibration(scheme, [i.item_id for i in items], rate=0.2)
    reqs = eng.store.requests(status=["open"], purpose=["calibration"])
    _answer(eng, items, reqs[:40])
    assert eng.certify(scheme, auto=True)["prev"]["looks_spent"] == 1
    _answer(eng, items, reqs[40:44])
    for r in reqs[44:]:                               # the rest is withdrawn
        eng.store.update_request(r.id, status="cancelled")
    last = eng.certify(scheme, auto=True)["prev"]
    assert last["looks_spent"] == 2 and last["n_at_look"] == 44


def test_nobody_is_finished_before_the_first_planner_pass(tmp_path):
    """Found by potato-skill (J3): before the first pass there were no items
    and no requests, so "every item has a final label" held vacuously and the
    first annotators were sent to the completion page for good."""
    from types import SimpleNamespace
    from potato.labeling_engine.integration import hooks
    eng = Engine(_config(tmp_path))
    person = SimpleNamespace(max_assignments=-1, get_assigned_instance_ids=lambda: set())
    old = hooks._ENGINE
    hooks._ENGINE = eng
    try:
        assert hooks.finished_for_user(person) is None
        eng.planner_passes = 1                       # a pass, but no items yet
        assert hooks.finished_for_user(person) is None
    finally:
        hooks._ENGINE = old


def test_an_infeasible_contract_sends_the_rest_to_people(tmp_path):
    """Found by potato-skill (R3): under "every contract must be met" an
    infeasible one blocked acceptance and nothing else was opened, so the
    study stalled with labels unassigned and budget unspent."""
    both = [dict(SR_ONLY[0], per_class=False),
            dict(SR_ONLY[0], id="strict", per_class=True, error=0.001)]
    eng, scheme, items = _study(tmp_path, n=600, contracts=both,
                                budgets={"human_labels": 400})
    eng.planner_passes = 1
    eng.draw_calibration(scheme, [i.item_id for i in items], rate=0.3)
    _answer_all(eng, items)
    res = eng.certify(scheme)
    assert res["strict"]["status"] == "infeasible"
    counts = eng.resolve(scheme)
    opened = eng.store.requests(status=["open"], purpose=["resolve"])
    assert counts["requests_opened"] == len(opened) > 0
    assert all(r.visibility == "blind" for r in opened)
    assert eng.human_labels_remaining() == 0 or not eng.store.requests(status=["open"],
                                                                         purpose=["verify"])
    # Answer them: the budget is spent, so the study is over for people.
    _answer_all(eng, items, purposes=("resolve",))
    assert eng.human_labels_remaining() == 0
    assert eng.human_work_remaining() is None
    # The same store in a new process (a restart): not finished until its
    # planner has run once.
    eng.planner_passes = 0
    assert eng.human_work_remaining() == "the planner has not run yet"


@pytest.mark.parametrize("drift_on", [None, False])
def test_breached_audits_show_on_the_contract(tmp_path, drift_on):
    """Found by potato-skill (J4): with features.drift off, 88 of 91 failed
    audits left the contract a green "met" and its labels certified; and
    nothing about the default said audits only watched."""
    from potato.labeling_engine.certificate import build_certificate, render_markdown
    block = {} if drift_on is None else {"features": {"drift": drift_on}}
    eng, scheme, items = _study(tmp_path, contracts=SR_ONLY,
                                humans={"audit_rate": 0.3}, **block)
    eng.draw_calibration(scheme, [i.item_id for i in items], rate=0.2)
    _answer_all(eng, items)
    assert eng.certify(scheme)["acc"]["status"] == "met"
    eng.resolve(scheme)
    eng.draw_audit(scheme, seed=1)
    for r in eng.store.requests(status=["open"], purpose=["audit"]):
        p = eng.store.get_prediction(r.shown_prediction_id)
        wrong = next(l for l in LABELS if l != p.value)
        eng.record_human_label(r.item_id, r.schema, wrong, "auditor", request_id=r.id)
    st = eng.contract_status(scheme)["acc"]
    assert st["audits_breached"]
    md = render_markdown(build_certificate(eng, save=False))
    if drift_on is None:                     # the default: audits act
        assert st["status"] == "violated"
        eng.resolve(scheme)
        assert not [r for r in eng.store.resolved(schema="sentiment")
                    if r.origin == "auto" and r.status == "accepted"]
    else:
        assert st["status"] == "met"
        assert any("features.drift is false" in n for n in st["notes"])
        assert "| acc | selective_risk | met, audits breached |" in md


def test_certifying_again_after_a_breach_starts_a_fresh_audit_sequence(tmp_path):
    """Found by potato-skill (R4): the monitor ran over every audit ever
    answered, so a breach was permanent and re-certifying changed nothing."""
    import time as _t
    eng, scheme, items = _study(tmp_path, contracts=SR_ONLY, humans={"audit_rate": 0.3})
    ids = [i.item_id for i in items]
    eng.draw_calibration(scheme, ids, rate=0.15, seed=1)
    _answer_all(eng, items)
    assert eng.certify(scheme)["acc"]["status"] == "met"
    eng.resolve(scheme)
    eng.draw_audit(scheme, seed=1)
    for r in eng.store.requests(status=["open"], purpose=["audit"]):
        p = eng.store.get_prediction(r.shown_prediction_id)
        eng.record_human_label(r.item_id, r.schema, next(l for l in LABELS if l != p.value),
                               "auditor", request_id=r.id)
    assert eng.contract_status(scheme)["acc"]["status"] == "violated"
    _t.sleep(0.01)
    # More calibration labels, and an explicit test of them: a new look.
    eng.draw_calibration(scheme, ids, rate=0.1, seed=2)
    _answer_all(eng, items)
    res = eng.certify(scheme, retest=True)["acc"]
    assert res["status"] == "met" and res["looks_spent"] == 2
    st = eng.contract_status(scheme)["acc"]
    assert st["status"] == "met" and not st.get("audits_breached")
    assert "certified again" in eng.drift(scheme)["acc"]["earlier_breach"]
    eng.resolve(scheme)
    assert [r for r in eng.store.resolved(schema="sentiment")
            if r.origin == "auto" and r.status == "accepted"]


def test_a_projection_beyond_the_corpus_says_it_is_not_reachable(tmp_path):
    """Found by potato-skill (A7): "about 234,719 more" on 481 items."""
    eng, scheme, items = _study(tmp_path, n=400, contracts=[dict(SR_ONLY[0], error=0.02)])
    eng.draw_calibration(scheme, [i.item_id for i in items], rate=0.3)
    _answer_all(eng, items)
    eng.certify(scheme)
    st = eng.contract_status(scheme)["acc"]
    assert st["status"] != "met"
    more = (st.get("projection") or {}).get("more_calibration_labels")
    assert more > 400
    assert st["projection"]["reachable"] is False
    assert any(n.startswith("Not reachable with this corpus") for n in st["notes"])


def test_a_study_with_no_rule_in_force_and_nothing_to_draw_goes_to_people(tmp_path):
    """Found by potato-skill (K1, the class of R3 and R4): an unmet contract
    with no projection left nothing open, items unlabeled and budget unspent,
    and annotators were told to come back forever."""
    from potato.labeling_engine.allocation.planner import Planner
    eng = Engine(_config(tmp_path, error_rate=0.65, contracts=SR_ONLY,
                         humans={"calibration_rate": 0.5}, budgets={"human_labels": 400}))
    scheme = eng.scheme("sentiment")
    items = _items(120)
    planner = Planner(eng, item_source=lambda _e: items)
    planner.tick()
    _answer_all(eng, items)
    # As in K1: the planner finds nothing more to draw (no projection).
    planner._top_up = lambda scheme, ids: {}
    planner.tick()
    planner.tick()
    assert eng.contract_status(scheme)["acc"]["status"] != "met"
    opened = eng.store.requests(status=["open"], purpose=["resolve"])
    assert opened and all(r.visibility == "blind" for r in opened)
    _answer_all(eng, items, purposes=("resolve",))
    planner.tick()
    eng.resolve(scheme)
    assert eng.human_work_remaining() is None or eng.human_labels_remaining() > 0


def test_an_item_is_taken_with_all_its_schemes(tmp_path):
    """Found by potato-skill (D4): one person held has_person on an item
    while a second was served it for `objects`, and the second person's
    has_person answer was organic."""
    cfg = _config(tmp_path, humans={"overlap": 1.0, "overlap_k": 2})
    second = dict(cfg["annotation_schemes"][0], name="tone")
    cfg["annotation_schemes"].append(second)
    eng = Engine(cfg)
    items = _items(200)
    eng.register_items(items)
    for name in ("sentiment", "tone"):
        sch = eng.scheme(name)
        eng.predict(sch, items)
        eng.draw_calibration(sch, [i.item_id for i in items], rate=0.1)   # same items: shared key
    [first] = eng.claim_requests("u1", 1)
    held = eng.store.requests(status=["assigned"], user="u1")
    assert {r.item_id for r in held} == {first.item_id}
    assert {r.schema for r in held} == {"sentiment", "tone"}       # both schemes
    assert len(held) == 2                                          # not both copies
    # The overlap copies are still there for someone else.
    other = eng.claim_requests("u2", 50)
    assert first.item_id in {r.item_id for r in other}


def test_a_hold_is_released_after_runtime_hold_minutes(tmp_path):
    """Found by potato-skill (D5): a fixed hour, with no key to change it."""
    import time as _t
    from potato.labeling_engine.allocation.planner import Planner
    eng = Engine(_config(tmp_path, runtime={"hold_minutes": 5}))
    items = _items(200)
    planner = Planner(eng, item_source=lambda _e: items)
    planner.tick()
    [r] = eng.claim_requests("u1", 1)
    eng.store.update_request(r.id, assigned_at=_t.time() - 4 * 60)
    planner.tick()
    assert eng.store.get_request(r.id).status == "assigned"
    eng.store.update_request(r.id, assigned_at=_t.time() - 6 * 60)
    planner.tick()
    assert eng.store.get_request(r.id).status == "open"


def test_open_verify_requests_are_withdrawn_when_their_item_is_accepted(tmp_path):
    """Found by potato-skill (B6): 208 verify requests from a stale window
    stayed open, showing an old prediction, after their items were accepted."""
    from potato.labeling_engine.model.records import HumanRequest
    eng, scheme, items = _met_study(tmp_path)
    eng.resolve(scheme)
    auto = [r.item_id for r in eng.store.resolved(schema="sentiment") if r.origin == "auto"]
    eng.store.add_requests([HumanRequest(item_id=iid, schema="sentiment", purpose="verify",
                                         inclusion_prob=None, visibility="shown")
                            for iid in auto[:5]])
    counts = eng.resolve(scheme)
    assert counts["cancelled"] == 5
    assert not [r for r in eng.store.requests(status=["open"], purpose=["verify"])
                if r.item_id in auto[:5]]

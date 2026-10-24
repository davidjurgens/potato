"""Payoff math, seeding, pay modes and the Prolific hand-off in potato/incentives.py.

The numbers in the hand-checked tests are worked out in the comments next to
them, not read back from the code.
"""

import csv
import hashlib
import json
import os
import random
from decimal import Decimal
from fractions import Fraction
from itertools import product
from unittest.mock import MagicMock, patch

import pytest

from potato.export.base import ExportContext
from potato.export.incentives_exporter import IncentivesExporter
from potato.incentives import (
    IncentiveReport, bdm_payoff, bdm_price, bin_outcome, binary_outcome, bsr_loss,
    bsr_win_probability, compute_incentives, decision_rng, draw_seed, incentive_config_problems,
    play_lottery, private_item_fields)
from potato.server_utils.schemas.price_list import build_rows
from tests.helpers.test_utils import create_test_directory

HL = {"annotation_type": "price_list", "name": "risk", "description": "d", "preset": "holt_laury"}
WTP = {"annotation_type": "bdm", "name": "wtp", "description": "d", "max": 10}
FORECAST = {"annotation_type": "belief_elicitation", "name": "fc", "description": "d"}
DIST = {"annotation_type": "belief_elicitation", "name": "dist", "description": "d",
        "mode": "bins", "bins": ["low", "mid", "high"]}
TP = {"annotation_type": "price_list", "name": "tp", "description": "d", "preset": "time_preference",
      "amount_now": 10, "amounts_later": [10, 11, 12], "delay_label": "in 4 weeks"}


def _config(rules, pay="sum", **extra):
    return {"annotation_schemes": [HL, WTP, FORECAST, DIST, TP],
            "incentives": {"enabled": True, "seed": "s3cret", "pay": pay, "rules": rules, **extra}}


def _ann(user, item, scheme, answer):
    return {"user_id": user, "instance_id": item, "labels": {scheme: {scheme: json.dumps(answer)}}}


DONE = {"current_phase_and_page": ["done", None]}


def _prolific(pid):
    return {**DONE, "crowd_metadata": {"provider": "prolific", "worker_id": pid}}


# ----------------------------------------------------------------- preset --

def test_holt_laury_rows_match_the_published_design():
    rows = build_rows(HL)
    assert len(rows) == 10
    assert rows[0]["a_pays"] == [(0.1, 2.0), (pytest.approx(0.9), 1.6)]
    assert rows[0]["b_pays"] == [(0.1, 3.85), (pytest.approx(0.9), 0.1)]
    assert rows[9]["a_pays"] == [(1.0, 2.0)] and rows[9]["b_pays"] == [(1.0, 3.85)]
    assert rows[2]["a"] == "30% chance of $2.00, 70% chance of $1.60"
    assert rows[9]["b"] == "$3.85 for sure"
    # A risk-neutral chooser takes A in rows 1-4 and B from row 5 (Holt & Laury
    # 2002): row 4 EV(A) = .4*2 + .6*1.6 = 1.76 > EV(B) = .4*3.85 + .6*.1 = 1.60;
    # row 5 EV(A) = 1.80 < EV(B) = 1.975.
    ev = [(sum(p * a for p, a in r["a_pays"]), sum(p * a for p, a in r["b_pays"])) for r in rows]
    assert [i + 1 for i, (a, b) in enumerate(ev) if b > a][0] == 5


def test_scale_multiplies_every_amount():
    rows = build_rows({**HL, "scale": 10, "currency": "£"})
    assert rows[0]["b_pays"][0] == (0.1, pytest.approx(38.5))
    assert rows[0]["a"] == "10% chance of £20.00, 90% chance of £16.00"


# ------------------------------------------------------------ payoff math --

def test_lottery_resolution_is_hand_checked():
    row3_b = build_rows(HL)[2]["b_pays"]          # 30% of $3.85, 70% of $0.10
    assert play_lottery(row3_b, 0.25) == 3.85     # u < 0.3: the high prize
    assert play_lottery(row3_b, 0.35) == 0.10
    assert play_lottery([(1.0, 2.0)], 0.999) == 2.0


def test_bdm_payoff_is_hand_checked():
    assert bdm_payoff(5, 3, endowment=10) == (True, 7)          # buys: 10 - 3
    assert bdm_payoff(2, 3, endowment=10) == (False, 10)        # keeps the endowment
    assert bdm_payoff(3, 3, endowment=10, item_value=4) == (True, 11)   # a tie buys: 10 - 3 + 4


def test_bdm_price_draw():
    grid = {"min": 0, "max": 5, "step": 0.25}                   # 21 prices, 0.00 .. 5.00
    assert bdm_price(grid, 0.0) == 0.0
    assert bdm_price(grid, 0.5) == 2.5                          # int(0.5 * 21) = 10 -> 10 * 0.25
    assert bdm_price(grid, 0.9999) == 5.0
    assert bdm_price({"min": 0, "max": 10}, 0.123456) == 1.23


def test_bsr_loss_and_win_probability_are_hand_checked():
    assert bsr_loss(0.7, 1, "point") == pytest.approx(0.09)    # (1 - .7)^2
    assert bsr_win_probability(0.7, 1, "point") == pytest.approx(0.91)
    assert bsr_win_probability(0.7, 0, "point") == pytest.approx(0.51)   # 1 - .49
    # (0-.2)^2 + (1-.5)^2 + (0-.3)^2 = .04 + .25 + .09 = .38; K = 2
    assert bsr_loss([0.2, 0.5, 0.3], 1, "bins") == pytest.approx(0.38)
    assert bsr_win_probability([0.2, 0.5, 0.3], 1, "bins") == pytest.approx(0.81)


@pytest.mark.parametrize("belief", [Fraction(5, 100), Fraction(30, 100), Fraction(75, 100)])
def test_bsr_point_report_is_best_at_the_true_belief(belief):
    """Expected win probability, computed exactly over every report 0..100."""
    def expected(r):
        q = Fraction(r, 100)
        return belief * (1 - (1 - q) ** 2) + (1 - belief) * (1 - q ** 2)
    values = {r: expected(r) for r in range(101)}
    best = max(values.values())
    assert [r for r, v in values.items() if v == best] == [int(belief * 100)]
    # The code's own win probability gives the same expectation.
    for r in (0, 37, 100):
        code = float(belief) * bsr_win_probability(r / 100, 1, "point") + \
            float(1 - belief) * bsr_win_probability(r / 100, 0, "point")
        assert code == pytest.approx(float(values[r]))


def test_bsr_bins_report_is_best_at_the_true_distribution():
    truth = [Fraction(2, 10), Fraction(5, 10), Fraction(3, 10)]

    def expected(report):
        return sum(t * (1 - sum(((1 if k == o else 0) - p) ** 2 for k, p in enumerate(report)) / 2)
                   for o, t in enumerate(truth))
    grid = [(Fraction(a, 10), Fraction(b, 10), Fraction(10 - a - b, 10))
            for a, b in product(range(11), repeat=2) if a + b <= 10]
    values = {g: expected(g) for g in grid}
    best = max(values.values())
    assert [g for g, v in values.items() if v == best] == [tuple(truth)]
    # The loss never exceeds K = 2, so the win probability is never clipped.
    assert max(bsr_loss([float(x) for x in g], o, "bins") for g in grid for o in range(3)) <= 2


def test_outcome_parsing():
    assert [binary_outcome(v) for v in (1, 0, True, "yes", "No", "1", 2, None)] == [1, 0, 1, 1, 0, 1, None, None]
    assert bin_outcome("mid", ["low", "mid", "high"]) == 1
    assert bin_outcome(2, ["low", "mid", "high"]) == 2
    assert bin_outcome("3", ["0", "1", "3"]) == 2            # a label wins over an index
    assert bin_outcome(5, ["low", "mid"]) is None


# ---------------------------------------------------------------- seeding --

def test_draws_follow_order_seed_and_the_private_seed():
    key = "u1\x1fincentives\x1frisk".encode()
    expected_seed = int.from_bytes(hashlib.blake2b(key, digest_size=8).digest(), "big")
    assert draw_seed("u1", "risk") == expected_seed
    rng = decision_rng("u1", "risk", "item_3", "s3cret")
    assert rng.random() == random.Random(f"{expected_seed}\x1fitem_3\x1fs3cret").random()
    assert decision_rng("u1", "risk", "item_3", "other").random() != \
        decision_rng("u1", "risk", "item_3", "s3cret").random()


def test_computation_is_reproducible_and_pinned():
    config = _config([{"scheme": "risk", "method": "mpl_random_row"}])
    anns = [_ann("u1", "i1", "risk", {"choices": ["A"] * 4 + ["B"] * 6})]
    a = compute_incentives(config, anns, [], {}, {"u1": DONE})
    b = compute_incentives(config, anns, [], {}, {"u1": DONE})
    assert a.rows == b.rows
    draws = json.loads(a.rows[0]["draws"])
    # Pinned: a change to the seeding scheme changes every past study's draws.
    rng = random.Random(f"{draw_seed('u1', 'risk')}\x1fi1\x1fs3cret")
    row, u = rng.randrange(10), rng.random()
    assert draws["row"] == row + 1 and draws["u"] == u
    choice = "A" if row < 4 else "B"
    pays = build_rows(HL)[row]["a_pays" if choice == "A" else "b_pays"]
    assert draws["choice"] == choice
    assert a.rows[0]["payoff"] == f"{play_lottery(pays, u):.2f}"


def test_adding_an_item_leaves_other_draws_alone():
    config = _config([{"scheme": "fc", "method": "bsr", "prize": 2, "outcome_field": "happened"}])
    items = {"i1": {"happened": 1}, "i2": {"happened": 0}}
    one = compute_incentives(config, [_ann("u1", "i1", "fc", {"report": 60})], [], items, {"u1": DONE})
    two = compute_incentives(config, [_ann("u1", "i1", "fc", {"report": 60}),
                                      _ann("u1", "i2", "fc", {"report": 60})], [], items, {"u1": DONE})
    assert one.rows[0]["draws"] == [r for r in two.rows if r["decision"] == "i1"][0]["draws"]


# -------------------------------------------------------------- rules end-to-end --

def test_bdm_rule_with_item_price_and_value():
    config = _config([{"scheme": "wtp", "method": "bdm", "endowment": 5, "price_field": "price",
                       "value_field": "value"}])
    items = {"i1": {"price": 3, "value": 4}, "i2": {"price": 3, "value": 4}}
    r = compute_incentives(config, [_ann("u1", "i1", "wtp", {"bid": 3.5}),
                                    _ann("u1", "i2", "wtp", {"bid": 2.5})], [], items, {"u1": DONE})
    by = {row["decision"]: row for row in r.rows}
    assert by["i1"]["payoff"] == "6.00"           # buys: 5 - 3 + 4
    assert by["i2"]["payoff"] == "5.00"           # does not buy
    assert r.totals["u1"]["total"] == Decimal("11.00")


def test_bsr_rule_and_outcome_missing():
    config = _config([{"scheme": "fc", "method": "bsr", "prize": 2, "outcome_field": "happened"}])
    items = {"i1": {"happened": 1}, "i2": {}}
    r = compute_incentives(config, [_ann("u1", "i1", "fc", {"report": 100}),
                                    _ann("u1", "i2", "fc", {"report": 50})], [], items, {"u1": DONE})
    by = {row["decision"]: row for row in r.rows}
    # Report 100 on an event that happened: loss 0 < U always, so it wins.
    assert by["i1"]["payoff"] == "2.00" and json.loads(by["i1"]["draws"])["won"] is True
    assert by["i2"]["payoff"] == "" and "no outcome" in by["i2"]["note"]


def test_bins_must_sum_to_100():
    config = _config([{"scheme": "dist", "method": "bsr", "prize": 2, "outcome": "mid"}])
    r = compute_incentives(config, [_ann("u1", "i1", "dist", {"bins": [20, 50, 20]})], [], {}, {"u1": DONE})
    assert "sums to 90" in r.rows[0]["note"] and r.totals["u1"]["total"] == 0


def test_multiple_switching_is_flagged_and_still_paid():
    config = _config([{"scheme": "risk", "method": "mpl_random_row"}])
    choices = ["A", "B", "A", "B", "A", "B", "B", "B", "B", "B"]
    r = compute_incentives(config, [_ann("u1", "i1", "risk", {"choices": choices})], [], {}, {"u1": DONE})
    assert "multiple switching (5 switches)" in r.rows[0]["note"]
    assert r.rows[0]["payoff"] != ""


def test_phase_page_answers_are_paid():
    config = _config([{"scheme": "wtp", "method": "bdm", "endowment": 10, "draw": {"min": 0, "max": 10}}])
    phase = [{"user_id": "u1", "phase": "poststudy", "page": "poststudy", "schema": "wtp",
              "label_name": "wtp", "value": json.dumps({"bid": 10})}]
    r = compute_incentives(config, [], phase, {}, {"u1": DONE})
    assert r.rows[0]["decision"] == "poststudy/poststudy"
    draws = json.loads(r.rows[0]["draws"])
    assert draws["bought"] is True                     # a bid of max always buys
    assert r.rows[0]["payoff"] == f"{10 - draws['price']:.2f}"


def test_one_random_item_pays_exactly_one_and_sum_pays_all():
    rules = [{"scheme": "wtp", "method": "bdm", "endowment": 1, "draw": {"min": 0, "max": 1}}]
    anns = [_ann("u1", f"i{k}", "wtp", {"bid": 0}) for k in range(5)]   # never buys: 1.00 each
    one = compute_incentives(_config(rules, pay="one_random_item"), anns, [], {}, {"u1": DONE})
    assert sum(r["paid"] for r in one.rows) == 1 and one.totals["u1"]["total"] == Decimal("1.00")
    paid = [r for r in one.rows if r["paid"]][0]
    assert json.loads(paid["draws"])["of"] == 5
    for mode in ("sum", "all"):
        total = compute_incentives(_config(rules, pay=mode), anns, [], {}, {"u1": DONE}).totals["u1"]
        assert total["total"] == Decimal("5.00")


def test_max_bonus_caps_and_marks():
    rules = [{"scheme": "wtp", "method": "bdm", "endowment": 1, "draw": {"min": 0, "max": 1}}]
    anns = [_ann("u1", f"i{k}", "wtp", {"bid": 0}) for k in range(5)]
    t = compute_incentives(_config(rules, max_bonus=3.5), anns, [], {}, {"u1": DONE}).totals["u1"]
    assert t["total"] == Decimal("3.50") and t["capped"] is True and t["uncapped"] == Decimal("5.00")


def test_unfinished_participants_get_no_draws():
    config = _config([{"scheme": "risk", "method": "mpl_random_row"}])
    anns = [_ann("u1", "i1", "risk", {"choices": ["A"] * 10})]
    r = compute_incentives(config, anns, [], {}, {"u1": {"current_phase_and_page": ["annotation", "x"]}})
    assert r.rows[0]["draws"] == "" and "not finished" in r.rows[0]["note"]
    assert r.totals["u1"]["eligible"] is False
    config["incentives"]["only_finished"] = False
    r = compute_incentives(config, anns, [], {}, {"u1": {"current_phase_and_page": ["annotation", "x"]}})
    assert r.rows[0]["draws"]


def test_a_delayed_payment_is_kept_out_of_the_prolific_rows():
    config = _config([{"scheme": "tp", "method": "mpl_random_row"}])
    r = compute_incentives(config, [_ann("u1", "i1", "tp", {"choices": ["B", "B", "B"]})], [], {},
                           {"u1": _prolific("P1")})
    assert r.totals["u1"]["pay_after"] == "in 4 weeks" and not r.totals["u1"]["eligible"]
    assert r.prolific_rows() == []
    assert any("in 4 weeks" in w for w in r.warnings)


def test_missing_seed_is_warned():
    config = _config([{"scheme": "risk", "method": "mpl_random_row"}])
    del config["incentives"]["seed"]
    r = compute_incentives(config, [], [], {}, {})
    assert any("incentives.seed is not set" in w for w in r.warnings)


# ------------------------------------------------------------ Prolific rows --

def test_prolific_rows_use_the_bulk_format_and_skip_who_cannot_be_paid():
    rules = [{"scheme": "wtp", "method": "bdm", "endowment": 1.5, "draw": {"min": 0, "max": 1}}]
    anns = [_ann(u, "i1", "wtp", {"bid": 0}) for u in ("u1", "u2", "u3")]
    states = {"u1": _prolific("5f1a2b3c4d5e6f7a8b9c0d1e"),
              "u2": {**DONE, "crowd_metadata": {"PROLIFIC_PID": "60aa11bb22cc33dd44ee55ff"}},
              "u3": DONE}
    r = compute_incentives(_config(rules), anns, [], {}, states)
    assert r.prolific_rows() == [("5f1a2b3c4d5e6f7a8b9c0d1e", "1.50"), ("60aa11bb22cc33dd44ee55ff", "1.50")]
    assert r.totals["u3"]["reason"] == "no Prolific id"
    assert r.summary()["prolific_total"] == "3.00"


def test_one_prolific_id_twice_is_refused():
    rules = [{"scheme": "wtp", "method": "bdm", "endowment": 1, "draw": {"min": 0, "max": 1}}]
    anns = [_ann(u, "i1", "wtp", {"bid": 0}) for u in ("u1", "u2")]
    r = compute_incentives(_config(rules), anns, [], {}, {"u1": _prolific("P1"), "u2": _prolific("P1")})
    with pytest.raises(ValueError, match="listed twice"):
        r.prolific_rows()


def test_exporter_writes_both_files():
    out = create_test_directory("incentives_export")
    states_dir = os.path.join(out, "annotation_output")
    for uid, state in (("u1", _prolific("PID1")), ("u2", DONE)):
        os.makedirs(os.path.join(states_dir, uid), exist_ok=True)
        with open(os.path.join(states_dir, uid, "user_state.json"), "w") as f:
            json.dump({"user_id": uid, **state}, f)
    rules = [{"scheme": "wtp", "method": "bdm", "endowment": 2, "draw": {"min": 0, "max": 2}}]
    ctx = ExportContext(config={**_config(rules), "task_dir": out},
                        annotations=[_ann("u1", "i1", "wtp", {"bid": 0}), _ann("u2", "i1", "wtp", {"bid": 0})],
                        items={}, schemas=[WTP], output_dir=states_dir)
    result = IncentivesExporter().export(ctx, os.path.join(out, "export"))
    assert result.success, result.errors
    with open(os.path.join(out, "export", "bonuses.csv")) as f:
        rows = list(csv.DictReader(f))
    assert {r["user_id"]: (r["prolific_id"], r["total"], r["capped"]) for r in rows} == \
        {"u1": ("PID1", "2.00", "0"), "u2": ("", "2.00", "0")}
    assert all(r["seed"] and json.loads(r["draws"])["bought"] is False for r in rows)
    with open(os.path.join(out, "export", "bonuses_prolific.csv")) as f:
        assert f.read() == "PID1,2.00\n"
    assert any("no Prolific id" in w for w in result.warnings)


def test_exporter_needs_enabled_rules():
    ctx = ExportContext(config={"incentives": {"enabled": False, "rules": []}}, annotations=[],
                        items={}, schemas=[], output_dir="")
    ok, reason = IncentivesExporter().can_export(ctx)
    assert not ok and "enabled" in reason


# --------------------------------------------------------- config validation --

@pytest.mark.parametrize("rule,match", [
    ({"scheme": "nope", "method": "bsr", "prize": 1, "outcome": 1}, "not defined"),
    ({"scheme": "risk", "method": "bdm", "draw": {"min": 0, "max": 1}}, "pays a bdm scheme"),
    ({"scheme": "risk", "method": "guess"}, "method must be one of"),
    ({"scheme": "wtp", "method": "bdm"}, "exactly one of `draw"),
    ({"scheme": "wtp", "method": "bdm", "endowment": 2, "draw": {"min": 0, "max": 5}}, "below draw.max"),
    ({"scheme": "wtp", "method": "bdm", "draw": {"min": 3, "max": 1}}, "0 <= min < max"),
    ({"scheme": "fc", "method": "bsr", "outcome": 1}, "prize"),
    ({"scheme": "fc", "method": "bsr", "prize": 1}, "outcome_field"),
    ({"scheme": "fc", "method": "bsr", "prize": 1, "outcome": "maybe"}, "outcome must be"),
    ({"scheme": "fc", "method": "bsr", "prize": 1, "outcome": 1, "draw": {}}, "unknown key"),
])
def test_bad_rules_are_refused(rule, match):
    problems = incentive_config_problems(_config([rule]))
    assert problems and match in problems[0]


def test_price_list_rows_without_payoffs_cannot_be_paid():
    config = _config([{"scheme": "custom", "method": "mpl_random_row"}])
    config["annotation_schemes"].append({"annotation_type": "price_list", "name": "custom", "description": "d",
                                         "rows": [{"a": "x", "b": "y"}, {"a": "x", "b": "z"}]})
    assert "have no payoffs" in incentive_config_problems(config)[0]


def test_block_level_problems():
    config = _config([{"scheme": "risk", "method": "mpl_random_row"}], pay="most")
    assert "incentives.pay" in incentive_config_problems(config)[0]
    two = _config([{"scheme": "risk", "method": "mpl_random_row"}] * 2)
    assert "second rule named 'risk'" in incentive_config_problems(two)[0]
    assert incentive_config_problems(_config([{"scheme": "risk", "method": "mpl_random_row"}])) == []


def test_validate_yaml_structure_runs_the_check():
    from potato.server_utils.config_module import ConfigValidationError, validate_yaml_structure
    import yaml
    path = os.path.join(os.path.dirname(__file__), "..", "..", "examples", "advanced",
                        "incentivized-elicitation", "config.yaml")
    with open(path) as f:
        config = yaml.safe_load(f)
    config_dir = os.path.dirname(os.path.abspath(path))
    validate_yaml_structure(config, config_dir, config_dir)
    config["incentives"]["rules"][0]["prize"] = -1
    with pytest.raises(ConfigValidationError, match="prize"):
        validate_yaml_structure(config, config_dir, config_dir)


# ------------------------------------------------------------ private fields --

def test_outcome_and_price_fields_never_reach_the_page():
    from potato.server_utils.schemas.cloze import strip_answer_fields
    config = _config([{"scheme": "fc", "method": "bsr", "prize": 1, "outcome_field": "happened"},
                      {"scheme": "wtp", "method": "bdm", "price_field": "price"}])
    assert sorted(private_item_fields(config)) == ["happened", "price"]
    item = {"id": "i1", "text": "t", "happened": 1, "price": 3}
    assert strip_answer_fields(config, item) == {"id": "i1", "text": "t"}


# ----------------------------------------------------------------- admin route --

@pytest.fixture
def admin_client():
    from flask import Flask
    from potato.crowdsourcing.admin_api import crowd_admin_bp
    out = create_test_directory("incentives_admin")
    states_dir = os.path.join(out, "annotation_output")
    os.makedirs(os.path.join(states_dir, "u1"))
    state = {"user_id": "u1", **_prolific("PIDX"),
             "instance_id_to_label_to_value": {"i1": [[{"schema": "wtp", "name": "wtp"}, json.dumps({"bid": 0})]]}}
    with open(os.path.join(states_dir, "u1", "user_state.json"), "w") as f:
        json.dump(state, f)
    config = {**_config([{"scheme": "wtp", "method": "bdm", "endowment": 2.25,
                          "draw": {"min": 0, "max": 2}}]),
              "task_dir": out, "output_annotation_dir": states_dir, "data_files": [],
              "prolific": {"token": "tok", "study_id": "S1"}}
    app = Flask(__name__)
    app.secret_key = "x"
    app.register_blueprint(crowd_admin_bp)
    allow = MagicMock()
    allow.check.return_value = True
    with patch("potato.server_utils.rbac.get_rbac_manager", return_value=allow), \
            patch("potato.crowdsourcing.admin_api._config", return_value=config):
        yield app.test_client()


def test_admin_dry_run_never_calls_prolific(admin_client):
    with patch("potato.crowdsourcing.prolific_api.ProlificClient") as client:
        r = admin_client.get("/admin/api/crowd/incentive_bonuses")
        assert r.status_code == 200
        body = r.get_json()
        assert body["dry_run"] is True and body["prolific_rows"] == [["PIDX", "2.25"]]
        assert body["prolific_total"] == "2.25"
        r = admin_client.post("/admin/api/crowd/incentive_bonuses", json={"pay": "yes"})
        assert r.get_json()["dry_run"] is True              # only a literal true pays
        client.assert_not_called()


def test_admin_pay_needs_the_reviewed_total(admin_client):
    with patch("potato.crowdsourcing.prolific_api.ProlificClient") as client:
        r = admin_client.post("/admin/api/crowd/incentive_bonuses", json={"pay": True})
        assert r.status_code == 409
        r = admin_client.post("/admin/api/crowd/incentive_bonuses",
                              json={"pay": True, "expected_total": "9.99"})
        assert r.status_code == 409
        client.assert_not_called()


def test_admin_pay_sets_up_and_pays_the_computed_rows(admin_client):
    with patch("potato.crowdsourcing.prolific_api.ProlificClient") as cls:
        api = cls.return_value
        api.set_up_bonuses.return_value = {"id": "BULK1"}
        api.pay_bonuses.return_value = {"status": "paid"}
        r = admin_client.post("/admin/api/crowd/incentive_bonuses",
                              json={"pay": True, "expected_total": "2.25"})
        assert r.status_code == 200, r.get_json()
        api.set_up_bonuses.assert_called_once_with("S1", [["PIDX", "2.25"]])
        api.pay_bonuses.assert_called_once_with("BULK1")


def _pay(client, **extra):
    return client.post("/admin/api/crowd/incentive_bonuses",
                       json={"pay": True, "expected_total": "2.25", **extra})


def test_admin_pay_twice_is_refused_and_names_the_first_batch(admin_client):
    with patch("potato.crowdsourcing.prolific_api.ProlificClient") as cls:
        api = cls.return_value
        api.set_up_bonuses.return_value = {"id": "BULK1"}
        api.pay_bonuses.return_value = {"status": "paid"}
        assert _pay(admin_client).status_code == 200
        r = _pay(admin_client)
        assert r.status_code == 409
        body = r.get_json()
        assert "BULK1" in body["error"] and "PIDX" in body["error"]
        assert body["earlier_batches"][0]["bulk_id"] == "BULK1"
        assert api.pay_bonuses.call_count == 1 and api.set_up_bonuses.call_count == 1


def test_admin_repeat_true_pays_again_and_is_recorded(admin_client):
    from potato.incentives import load_payments, payments_path
    from potato.crowdsourcing.admin_api import _config
    with patch("potato.crowdsourcing.prolific_api.ProlificClient") as cls:
        api = cls.return_value
        api.set_up_bonuses.side_effect = [{"id": "BULK1"}, {"id": "BULK2"}]
        api.pay_bonuses.return_value = {"status": "paid"}
        assert _pay(admin_client).status_code == 200
        assert _pay(admin_client, repeat="yes").status_code == 409     # only a literal true
        assert _pay(admin_client, repeat=True).status_code == 200
        recs = load_payments(payments_path(_config()))
        assert [(r["bulk_id"], r["repeat"], r["rows"]) for r in recs] == [
            ("BULK1", False, [["PIDX", "2.25"]]), ("BULK2", True, [["PIDX", "2.25"]])]


def test_admin_failed_payment_is_not_recorded(admin_client):
    from potato.crowdsourcing.prolific_api import ProlificAPIError
    with patch("potato.crowdsourcing.prolific_api.ProlificClient") as cls:
        api = cls.return_value
        api.set_up_bonuses.return_value = {"id": "BULK1"}
        api.pay_bonuses.side_effect = [ProlificAPIError("down", 503), {"status": "paid"}]
        assert _pay(admin_client).status_code == 502
        assert _pay(admin_client).status_code == 200                  # nothing was paid before


def test_admin_skip_paid_pays_only_the_new_participants(admin_client):
    """potato-skill, audit 97 re-verify: after more people finish, the only
    way to pay the newcomers was repeat:true, which pays everyone again."""
    from potato.crowdsourcing.admin_api import _config
    from potato.incentives import load_payments, payments_path, record_payment
    cfg = _config()
    record_payment(payments_path(cfg), [("PIDX", "2.25")], "BULK0", "S1", "2.25")
    newcomer = os.path.join(cfg["output_annotation_dir"], "u2")
    os.makedirs(newcomer)
    with open(os.path.join(newcomer, "user_state.json"), "w") as f:
        json.dump({"user_id": "u2", **_prolific("PIDY"), "instance_id_to_label_to_value": {
            "i1": [[{"schema": "wtp", "name": "wtp"}, json.dumps({"bid": 0})]]}}, f)
    url = "/admin/api/crowd/incentive_bonuses"
    with patch("potato.crowdsourcing.prolific_api.ProlificClient") as cls:
        api = cls.return_value
        api.set_up_bonuses.return_value = {"id": "BULK1"}
        api.pay_bonuses.return_value = {"status": "paid"}
        dry = admin_client.get(url).get_json()
        assert (dry["prolific_total"], dry["already_paid"], dry["unpaid_total"]) == (
            "4.50", ["PIDX"], "2.25")
        assert admin_client.post(url, json={"pay": True, "expected_total": "4.50"}).status_code == 409
        assert admin_client.post(url, json={"pay": True, "skip_paid": True, "repeat": True,
                                            "expected_total": "2.25"}).status_code == 400
        # The full total does not pass for the unpaid one.
        assert admin_client.post(url, json={"pay": True, "skip_paid": True,
                                            "expected_total": "4.50"}).status_code == 409
        r = admin_client.post(url, json={"pay": True, "skip_paid": True, "expected_total": "2.25"})
        assert r.status_code == 200, r.get_json()
        api.set_up_bonuses.assert_called_once_with("S1", [["PIDY", "2.25"]])
        recs = load_payments(payments_path(cfg))
        assert [(x["bulk_id"], x["total"]) for x in recs] == [("BULK0", "2.25"), ("BULK1", "2.25")]
        r = admin_client.post(url, json={"pay": True, "skip_paid": True, "expected_total": "0.00"})
        assert r.status_code == 400 and "already paid" in r.get_json()["error"]


def test_a_batch_overlapping_an_earlier_one_is_found():
    from potato.incentives import batch_key, earlier_payments, record_payment
    path = os.path.join(create_test_directory("incentives_ledger"), "incentive_payments.json")
    if os.path.exists(path):
        os.remove(path)
    assert batch_key([("A", "1.00"), ("B", "2.00")]) == batch_key([("B", "2.00"), ("A", "1.00")])
    record_payment(path, [("A", "1.00"), ("B", "2.00")], "BULK1", "S1", "3.00")
    assert earlier_payments(path, [("C", "1.00")]) == []
    # A new participant finishing must not pay A and B a second time.
    assert [r["bulk_id"] for r in earlier_payments(path, [("A", "1.00"), ("C", "4.00")])] == ["BULK1"]


@pytest.mark.parametrize("login, pays", [
    ({"type": "url_direct", "url_argument": "PROLIFIC_PID"}, True),
    ({"type": "url_direct"}, True),                     # PROLIFIC_PID is the default
    ({"type": "url_direct", "url_argument": "prolific_pid"}, True),  # case-insensitive, like login
    ({"type": "url_direct", "url_argument": "workerId"}, False),
])
def test_url_direct_prolific_login_is_a_prolific_id(login, pays):
    rules = [{"scheme": "wtp", "method": "bdm", "endowment": 1.5, "draw": {"min": 0, "max": 1}}]
    # What routes.py stores for a url_direct login (the legacy provider).
    state = {**DONE, "crowd_metadata": {"provider": "url_direct", "worker_id": "P001"}}
    r = compute_incentives({**_config(rules), "login": login},
                           [_ann("u1", "i1", "wtp", {"bid": 0})], [], {}, {"u1": state})
    assert r.prolific_rows() == ([("P001", "1.50")] if pays else [])
    if not pays:
        assert r.totals["u1"]["reason"] == "no Prolific id"


def test_filling_in_an_outcome_never_changes_the_paid_decision():
    config = _config([{"scheme": "fc", "method": "bsr", "prize": 2, "outcome_field": "happened"}],
                     pay="one_random_item")
    users = [f"u{k}" for k in range(20)]
    anns = [_ann(u, e, "fc", {"report": 70}) for u in users for e in ("e1", "e2", "e3")]
    states = {u: _prolific(f"P{u}") for u in users}
    before = compute_incentives(config, anns, [], {"e1": {"happened": 1}, "e2": {"happened": 0},
                                                   "e3": {}}, states)
    after = compute_incentives(config, anns, [], {"e1": {"happened": 1}, "e2": {"happened": 0},
                                                  "e3": {"happened": 1}}, states)

    def paid(r):
        return {row["user_id"]: row["decision"] for row in r.rows if row["paid"]}
    assert paid(before) == paid(after)
    waiting = sorted(u for u, d in paid(before).items() if d == "e3")
    assert waiting                                      # the seed draws e3 for some users
    assert before.summary()["pending"] == waiting
    for u in waiting:
        t = before.totals[u]
        assert t["pending"] and not t["eligible"] and t["reason"].startswith("pending")
    assert {p for p, _ in before.prolific_rows()}.isdisjoint({f"P{u}" for u in waiting})
    assert after.summary()["pending"] == []


def test_validate_names_the_example_placeholder_seed():
    from potato.validate_cli import validate_config_file
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    example = os.path.join(root, "examples", "advanced", "incentivized-elicitation", "config.yaml")
    report = validate_config_file(example)
    assert report.ok, report.to_dict()
    hits = [w for w in report.other_warnings if "example placeholder" in w]
    assert len(hits) == 1 and "CHANGE-ME-this-example-seed-is-public" in hits[0], report.other_warnings


def test_placeholder_seed_is_warned_but_a_private_one_is_not():
    config = _config([{"scheme": "risk", "method": "mpl_random_row"}])
    assert not any("placeholder" in w for w in compute_incentives(config, [], [], {}, {}).warnings)
    config["incentives"]["seed"] = "replace-with-a-private-string"
    assert any("example placeholder 'replace-with-a-private-string'" in w
               for w in compute_incentives(config, [], [], {}, {}).warnings)

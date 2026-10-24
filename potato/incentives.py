"""
Incentive payments for incentivized elicitation.

Computes each participant's bonus from their stored answers to ``price_list``,
``bdm`` and ``belief_elicitation`` schemes, following the ``incentives:``
block of the config::

    incentives:
      enabled: true
      currency: USD
      seed: "a private string"         # mixed into every draw
      pay: one_random_item              # or all / sum
      max_bonus: 10.00
      rules:
        - {scheme: risk, method: mpl_random_row}
        - {scheme: wtp, method: bdm, endowment: 5, draw: {min: 0, max: 5, step: 0.25}}
        - {scheme: forecast, method: bsr, prize: 2.00, outcome_field: happened}

Methods:

``mpl_random_row`` (price_list)
    One row of the list is drawn at random and the option the participant
    chose in that row is played: a lottery is resolved with a second draw.

``bdm`` (Becker, DeGroot & Marschak 1964)
    A price is drawn (``draw: {min, max, step}``, uniform) or read from the
    item (``price_field``). A bid at or above the price buys at the price:
    payoff = endowment - price + item value. A lower bid does not buy:
    payoff = endowment.

``bsr`` (binarized scoring rule, Hossain & Okui 2013)
    The prize is paid when the quadratic loss of the report is below U,
    U ~ Uniform[0, K]. For a probability p of a binary event the loss is
    (1{event} - p)^2 and K = 1; for a distribution over bins it is
    sum_b (1{bin} - p_b)^2 and K = 2. The win probability is 1 - loss / K,
    which a participant maximises in expectation by reporting their belief.

Nothing is drawn at answer time. The draws happen here, at export or admin
time, after the participant has finished, so the page never reveals a price,
row or threshold that could change an answer. Every draw is seeded with
``order_seed(user, "incentives", rule name)`` (plus the decision and the
private ``seed``), so running this again gives the same draws, and every
draw is written out for audit.

Nothing here pays anyone. :func:`IncentiveReport.prolific_rows` gives the rows
for Prolific's bulk bonus; the admin route
``/admin/api/crowd/incentive_bonuses`` sends them only on an explicit
``pay: true``.
"""

from __future__ import annotations

import json
import logging
import math
import os
import random
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

#: method -> the annotation_type it pays.
METHODS = {"mpl_random_row": "price_list", "bdm": "bdm", "bsr": "belief_elicitation"}
PAY_MODES = ("one_random_item", "all", "sum")
BLOCK_KEYS = {"enabled", "currency", "rules", "pay", "max_bonus", "seed", "only_finished"}
RULE_KEYS = {
    "mpl_random_row": {"name", "scheme", "method"},
    "bdm": {"name", "scheme", "method", "endowment", "draw", "price_field", "item_value", "value_field"},
    "bsr": {"name", "scheme", "method", "prize", "outcome_field", "outcome"},
}
#: K in U ~ Uniform[0, K] for the binarized scoring rule.
BSR_K = {"point": 1.0, "bins": 2.0}


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def cents(amount: float) -> Decimal:
    """``amount`` rounded half-up to two decimals."""
    return Decimal(repr(float(amount))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def rule_name(rule: Mapping[str, Any]) -> str:
    return str(rule.get("name") or rule.get("scheme"))


def draw_seed(user_id: str, name: str) -> int:
    """The rule-level seed: ``order_seed(user, "incentives", rule name)``."""
    from potato.server_utils.presentation_order import order_seed
    return order_seed(str(user_id), "incentives", name)


def decision_rng(user_id: str, name: str, decision: str, secret: str = "") -> random.Random:
    """A private generator for one decision.

    The rule-level seed is combined with the decision (item id or phase page)
    so that adding or removing one item does not change the draws for the
    others, and with the private ``incentives.seed`` so that someone who knows
    the code and a user id still cannot compute the draws in advance.
    """
    return random.Random(f"{draw_seed(user_id, name)}\x1f{decision}\x1f{secret}")


def play_lottery(pays: Sequence[Tuple[float, float]], u: float) -> float:
    """The amount a lottery ``[(probability, amount), ...]`` pays for a
    uniform draw ``u`` in [0, 1): outcomes are laid end to end in order."""
    acc = 0.0
    for p, amount in pays:
        acc += p
        if u < acc:
            return float(amount)
    return float(pays[-1][1])


def bdm_payoff(bid: float, price: float, endowment: float = 0.0,
               item_value: float = 0.0) -> Tuple[bool, float]:
    """(bought, payoff). A bid at or above the price buys at the price."""
    bought = bid >= price
    return bought, (endowment - price + item_value) if bought else endowment


def bdm_price(draw: Mapping[str, Any], u: float) -> float:
    """A uniform price from ``draw`` for a draw ``u`` in [0, 1). With
    ``step`` the price is one of min, min + step, ..., max, each equally
    likely; without it, a continuous price rounded to cents."""
    lo, hi = float(draw["min"]), float(draw["max"])
    step = draw.get("step")
    if step:
        n = int(round((hi - lo) / float(step)))
        return round(lo + min(int(u * (n + 1)), n) * float(step), 10)
    return float(cents(lo + u * (hi - lo)))


def bsr_loss(report: Any, outcome: int, mode: str) -> float:
    """Quadratic loss. ``point``: report is p in [0, 1], outcome 0/1.
    ``bins``: report is the list of bin probabilities, outcome the bin index."""
    if mode == "point":
        return (outcome - float(report)) ** 2
    return sum(((1.0 if k == outcome else 0.0) - float(p)) ** 2 for k, p in enumerate(report))


def bsr_win_probability(report: Any, outcome: int, mode: str) -> float:
    """P(loss < U) for U ~ Uniform[0, K]: 1 - loss / K."""
    return max(0.0, 1.0 - bsr_loss(report, outcome, mode) / BSR_K[mode])


def binary_outcome(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return int(value)
    if _num(value) and value in (0, 1):
        return int(value)
    if isinstance(value, str):
        s = value.strip().lower()
        if s in ("1", "true", "yes", "y"):
            return 1
        if s in ("0", "false", "no", "n"):
            return 0
    return None


def bin_outcome(value: Any, labels: Sequence[Any]) -> Optional[int]:
    """The index of the bin that happened: a bin label, or a 0-based index
    when the value matches no label."""
    names = [str(b) for b in labels]
    if value is not None and str(value) in names:
        return names.index(str(value))
    if _num(value) and float(value).is_integer() and 0 <= int(value) < len(names):
        return int(value)
    if isinstance(value, str) and value.strip().isdigit() and int(value) < len(names):
        return int(value)
    return None


def decode_answer(raw: Any) -> Optional[dict]:
    """A stored answer: the hidden input's JSON, or the dict itself."""
    if isinstance(raw, dict) and len(raw) == 1:
        (inner,) = raw.values()
        if isinstance(inner, (str, dict)):   # {label_name: value}
            raw = inner
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    return raw if isinstance(raw, dict) else None


def private_item_fields(config: Optional[Mapping[str, Any]]) -> List[str]:
    """Item fields the incentive rules read that must never reach the page:
    event outcomes (``outcome_field``) and pre-drawn prices (``price_field``).
    Either one, seen in advance, lets a participant answer strategically."""
    block = (config or {}).get("incentives")
    if not isinstance(block, dict):
        return []
    out = []
    for rule in block.get("rules") or []:
        if isinstance(rule, dict):
            for key in ("outcome_field", "price_field"):
                if isinstance(rule.get(key), str) and rule[key]:
                    out.append(rule[key])
    return out


# ---------------------------------------------------------------------------
# scheme lookup
# ---------------------------------------------------------------------------

def find_schemes(config: Mapping[str, Any], config_dir: Optional[str] = None
                 ) -> Tuple[Dict[str, dict], bool]:
    """``({name: scheme}, complete)`` over annotation_schemes and phase pages.
    ``complete`` is False when a phase file could not be read here."""
    found: Dict[str, dict] = {}
    for s in config.get("annotation_schemes") or []:
        if isinstance(s, dict) and s.get("name"):
            found.setdefault(str(s["name"]), s)
    complete = True
    if config.get("phases"):
        try:
            from potato.server_utils.config_module import phase_page_schemes
            pages = phase_page_schemes(dict(config), config_dir)
        except Exception:
            pages = None
        if pages is None:
            complete = False
        else:
            for schemes in pages.values():
                for s in schemes:
                    if isinstance(s, dict) and s.get("name"):
                        found.setdefault(str(s["name"]), s)
    return found, complete


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------

def _rule_problem(rule: Any, schemes: Dict[str, dict], complete: bool) -> Optional[str]:
    if not isinstance(rule, dict):
        return "must be a mapping with `scheme` and `method`"
    method = rule.get("method")
    if method not in METHODS:
        return f"method must be one of {', '.join(METHODS)}, got {method!r}"
    if not (isinstance(rule.get("scheme"), str) and rule["scheme"]):
        return "needs `scheme`, the name of the scheme it pays"
    if "name" in rule and not (isinstance(rule["name"], str) and rule["name"].strip()):
        return "name must be non-empty text"
    scheme = schemes.get(rule["scheme"])
    if scheme is None:
        if complete:
            return f"scheme {rule['scheme']!r} is not defined (annotation_schemes or a phase page)"
    elif scheme.get("annotation_type") != METHODS[method]:
        return (f"method {method} pays a {METHODS[method]} scheme; {rule['scheme']!r} is "
                f"{scheme.get('annotation_type')!r}")
    unknown = set(rule) - RULE_KEYS[method]
    if unknown:
        return f"unknown key(s) for method {method}: {', '.join(sorted(unknown))}"

    if method == "mpl_random_row" and scheme is not None:
        from potato.server_utils.schemas.price_list import build_rows
        try:
            rows = build_rows(scheme)
        except (ValueError, TypeError, KeyError):
            return None                       # the scheme validator reports it
        unpaid = [i + 1 for i, r in enumerate(rows) if not r["a_pays"] or not r["b_pays"]]
        if unpaid:
            return (f"rows {', '.join(map(str, unpaid))} of {rule['scheme']!r} have no payoffs; "
                    "give each row `a_pays` and `b_pays`, or use a preset")
    if method == "bdm":
        has_draw, has_field = "draw" in rule, "price_field" in rule
        if has_draw == has_field:
            return "needs exactly one of `draw: {min, max}` or `price_field`"
        endowment = rule.get("endowment", 0)
        if not _num(endowment) or endowment < 0:
            return "endowment must be a number of 0 or more"
        if has_draw:
            d = rule["draw"]
            if not isinstance(d, dict) or set(d) - {"min", "max", "step"}:
                return "draw must be {min, max} with an optional step"
            if not (_num(d.get("min")) and _num(d.get("max"))) or d["min"] < 0 or d["max"] <= d["min"]:
                return "draw needs numbers min and max with 0 <= min < max"
            if "step" in d and (not _num(d["step"]) or d["step"] <= 0 or d["step"] > d["max"] - d["min"]):
                return "draw.step must be a positive number no larger than max - min"
            if endowment < d["max"]:
                return (f"endowment ({endowment}) is below draw.max ({d['max']}): a purchase "
                        "could cost more than the participant was given")
        elif not (isinstance(rule["price_field"], str) and rule["price_field"]):
            return "price_field must be the name of an item field"
        if "item_value" in rule and "value_field" in rule:
            return "use item_value or value_field, not both"
        if "item_value" in rule and (not _num(rule["item_value"]) or rule["item_value"] < 0):
            return "item_value must be a number of 0 or more"
        if "value_field" in rule and not (isinstance(rule["value_field"], str) and rule["value_field"]):
            return "value_field must be the name of an item field"
    if method == "bsr":
        prize = rule.get("prize")
        if not _num(prize) or prize <= 0:
            return "needs `prize`, a positive amount paid on a win"
        if ("outcome_field" in rule) == ("outcome" in rule):
            return "needs exactly one of `outcome_field` (an item field) or `outcome` (one value)"
        if "outcome_field" in rule and not (isinstance(rule["outcome_field"], str) and rule["outcome_field"]):
            return "outcome_field must be the name of an item field"
        if "outcome" in rule and scheme is not None:
            mode = scheme.get("mode", "point")
            ok = (binary_outcome(rule["outcome"]) is not None if mode == "point"
                  else bin_outcome(rule["outcome"], scheme.get("bins") or []) is not None)
            if not ok:
                return ("outcome must be 1/0 (true/false) for a point report, or a bin label "
                        "for a bins report")
    return None


def incentive_config_problems(config: Mapping[str, Any], config_dir: Optional[str] = None) -> List[str]:
    """Every problem with the ``incentives`` block, as sentences."""
    block = config.get("incentives")
    if block is None:
        return []
    if not isinstance(block, dict):
        return ["incentives must be a mapping"]
    problems = []
    for key in ("enabled", "only_finished"):
        if key in block and not isinstance(block[key], bool):
            problems.append(f"incentives.{key} must be true or false")
    if "currency" in block and not (isinstance(block["currency"], str) and block["currency"].strip()):
        problems.append("incentives.currency must be text such as USD or GBP")
    if "seed" in block and not (isinstance(block["seed"], str) and block["seed"]):
        problems.append("incentives.seed must be a non-empty string")
    if block.get("pay", "one_random_item") not in PAY_MODES:
        problems.append(f"incentives.pay must be one of {', '.join(PAY_MODES)}")
    if "max_bonus" in block and (not _num(block["max_bonus"]) or block["max_bonus"] <= 0):
        problems.append("incentives.max_bonus must be a positive amount")
    rules = block.get("rules")
    if rules is None:
        if block.get("enabled"):
            problems.append("incentives.rules is required when incentives are enabled")
        return problems
    if not isinstance(rules, list) or not rules:
        return problems + ["incentives.rules must be a non-empty list"]
    schemes, complete = find_schemes(config, config_dir)
    names = set()
    for i, rule in enumerate(rules):
        problem = _rule_problem(rule, schemes, complete)
        if problem:
            problems.append(f"incentives.rules[{i}]: {problem}")
            continue
        name = rule_name(rule)
        if name in names:
            problems.append(f"incentives.rules[{i}]: a second rule named {name!r}; give one a `name`")
        names.add(name)
    return problems


#: Seeds from the shipped example and the docs. They are public, so draws
#: made with one can be computed by anyone.
PLACEHOLDER_SEEDS = frozenset({
    "CHANGE-ME-this-example-seed-is-public", "replace-with-a-private-string",
    "a private string", "a private string, kept out of the repository"})


def placeholder_seed_warning(config: Mapping[str, Any]) -> Optional[str]:
    seed = (config.get("incentives") or {}).get("seed") if isinstance(config.get("incentives"), dict) else None
    if isinstance(seed, str) and seed.strip() in PLACEHOLDER_SEEDS:
        return (f"incentives.seed is the example placeholder {seed.strip()!r}: replace it with a "
                "private string before paying anyone. The placeholder is public, so the draws "
                "made with it can be computed in advance.")
    return None


def validate_incentives_config(config: Mapping[str, Any], config_file_dir: Optional[str] = None) -> None:
    """Raise ConfigValidationError for the first problem in ``incentives``."""
    problems = incentive_config_problems(config, config_file_dir)
    if problems:
        from potato.server_utils.config_module import ConfigValidationError
        raise ConfigValidationError(problems[0])
    warning = placeholder_seed_warning(config)
    if warning:
        # The config_module logger is the one `potato validate` reports.
        logging.getLogger("potato.server_utils.config_module").warning(warning)


# ---------------------------------------------------------------------------
# computing payoffs
# ---------------------------------------------------------------------------

@dataclass
class Decision:
    """One answer a rule pays: a scheme answered on one item or phase page."""
    user_id: str
    rule: dict
    scheme: dict
    key: str                    # instance id, or "<phase>/<page>"
    answer: dict
    item: dict = field(default_factory=dict)


def _pay_decision(d: Decision, secret: str) -> Dict[str, Any]:
    """``{"payoff", "draws", "pay_after", "note", "valid"}`` for one decision."""
    rule, scheme, answer = d.rule, d.scheme, d.answer
    method = rule["method"]
    name = rule_name(rule)
    rng = decision_rng(d.user_id, name, d.key, secret)
    # ``pending``: the answer is usable but the item data its payoff needs
    # (an outcome, a price, a value) is not there yet.
    out: Dict[str, Any] = {"payoff": 0.0, "draws": {}, "pay_after": "", "note": "", "valid": False,
                           "pending": False}

    if method == "mpl_random_row":
        from potato.server_utils.schemas.price_list import build_rows, count_switches
        rows = build_rows(scheme)
        choices = answer.get("choices")
        if (not isinstance(choices, list) or len(choices) != len(rows)
                or any(c not in ("A", "B") for c in choices)):
            out["note"] = "price list not answered in every row"
            return out
        switches = count_switches(choices)
        row = rng.randrange(len(rows))
        u = rng.random()
        side = choices[row]
        pays = rows[row]["a_pays" if side == "A" else "b_pays"]
        out.update(valid=True, payoff=play_lottery(pays, u),
                   pay_after=rows[row]["a_after" if side == "A" else "b_after"],
                   draws={"row": row + 1, "choice": side, "u": u, "switches": switches})
        if switches > 1:
            out["note"] = f"multiple switching ({switches} switches)"
        return out

    if method == "bdm":
        bid = answer.get("bid")
        lo, hi = float(scheme.get("min", 0)), float(scheme.get("max", math.inf))
        if not _num(bid) or not lo <= bid <= hi:
            out["note"] = "no valid bid"
            return out
        if "price_field" in rule:
            price = d.item.get(rule["price_field"])
            if not _num(price):
                out.update(note=f"item has no numeric {rule['price_field']!r}", pending=True)
                return out
            draws = {"price": float(price), "price_source": "item"}
        else:
            u = rng.random()
            price = bdm_price(rule["draw"], u)
            draws = {"u": u, "price": price}
        if "value_field" in rule:
            value = d.item.get(rule["value_field"])
            if not _num(value):
                out.update(note=f"item has no numeric {rule['value_field']!r}", pending=True)
                return out
        else:
            value = rule.get("item_value", 0)
        bought, payoff = bdm_payoff(float(bid), float(price), float(rule.get("endowment", 0)), float(value))
        draws["bought"] = bought
        out.update(valid=True, payoff=payoff, draws=draws)
        return out

    # bsr
    mode = scheme.get("mode", "point")
    raw = d.item.get(rule["outcome_field"]) if "outcome_field" in rule else rule.get("outcome")
    if mode == "point":
        report = answer.get("report")
        if not _num(report) or not 0 <= report <= 100:
            out["note"] = "no valid probability report"
            return out
        outcome = binary_outcome(raw)
        probs: Any = float(report) / 100.0
    else:
        bins = answer.get("bins")
        labels = scheme.get("bins") or []
        if (not isinstance(bins, list) or len(bins) != len(labels)
                or not all(_num(b) and b >= 0 for b in bins)):
            out["note"] = "no valid distribution"
            return out
        if abs(sum(bins) - 100) > 1e-9:
            out["note"] = f"distribution sums to {sum(bins):g}, not 100"
            return out
        outcome = bin_outcome(raw, labels)
        probs = [float(b) / 100.0 for b in bins]
    if outcome is None:
        out.update(note=(f"no outcome for {d.key}" if "outcome_field" in rule
                         else "rule outcome is not usable"), pending=True)
        return out
    k = BSR_K[mode]
    loss = bsr_loss(probs, outcome, mode)
    threshold = rng.random() * k
    won = loss < threshold
    out.update(valid=True, payoff=float(rule["prize"]) if won else 0.0,
               draws={"loss": loss, "U": threshold, "K": k, "outcome": outcome, "won": won})
    return out


@dataclass
class IncentiveReport:
    """Per-decision rows and per-participant totals."""
    currency: str
    pay: str
    rows: List[Dict[str, Any]] = field(default_factory=list)
    totals: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def prolific_rows(self) -> List[Tuple[str, str]]:
        """``(participant_id, "1.50")`` for every participant owed a bonus now.

        Left out, each with a warning already recorded: a zero bonus, no
        Prolific id, a bonus that pays later (a time-preference choice), a
        paid decision still waiting for its outcome, and a participant who
        has not finished when ``only_finished`` is on.
        """
        out = []
        for uid in sorted(self.totals):
            t = self.totals[uid]
            if t["eligible"]:
                out.append((t["prolific_id"], f"{t['total']:.2f}"))
        from potato.crowdsourcing.prolific_api import validate_bonus_rows
        return validate_bonus_rows(out)

    def summary(self) -> Dict[str, Any]:
        rows = self.prolific_rows()
        return {
            "currency": self.currency,
            "pay": self.pay,
            "participants": len(self.totals),
            "bonuses": [{"user_id": uid, **{k: (str(v) if isinstance(v, Decimal) else v)
                                            for k, v in t.items()}}
                        for uid, t in sorted(self.totals.items())],
            "prolific_rows": [list(r) for r in rows],
            "prolific_total": rows_total(rows),
            "pending": [uid for uid, t in sorted(self.totals.items()) if t.get("pending")],
            "warnings": list(self.warnings),
        }


def _prolific_id(state: Mapping[str, Any], config: Optional[Mapping[str, Any]] = None) -> str:
    """The participant's Prolific id from their login.

    Recorded by the ``prolific`` crowd provider, or by a ``url_direct`` login
    whose ``url_argument`` is ``PROLIFIC_PID`` (its default, matched without
    regard to case, as the crowd provider does): the worker id is then the
    PROLIFIC_PID from the study URL.
    """
    md = state.get("crowd_metadata") or {}
    pid = md.get("PROLIFIC_PID")
    provider = str(md.get("provider", "")).lower()
    if not pid and provider == "prolific":
        pid = md.get("worker_id")
    if not pid and provider == "url_direct":
        login = (config or {}).get("login") or {}
        if str(login.get("url_argument") or "PROLIFIC_PID").lower() == "prolific_pid":
            pid = md.get("worker_id")
    return str(pid) if pid else ""


def _finished(state: Mapping[str, Any]) -> bool:
    phase = state.get("current_phase_and_page")
    if isinstance(phase, (list, tuple)) and phase:
        phase = phase[0]
    return str(phase or "").split(".")[-1].lower() == "done"


def collect_decisions(config: Mapping[str, Any], annotations: Iterable[dict],
                      phase_responses: Iterable[dict], items: Mapping[str, dict],
                      schemes: Mapping[str, dict]) -> Dict[str, List[Decision]]:
    rules = [r for r in ((config.get("incentives") or {}).get("rules") or []) if isinstance(r, dict)]
    by_user: Dict[str, List[Decision]] = {}
    for ann in annotations or []:
        uid, iid = str(ann.get("user_id", "")), str(ann.get("instance_id", ""))
        labels = ann.get("labels") or {}
        for rule in rules:
            scheme = schemes.get(rule.get("scheme"))
            answer = decode_answer(labels.get(rule.get("scheme")))
            if scheme is None or not answer:
                continue
            by_user.setdefault(uid, []).append(Decision(uid, rule, scheme, iid, answer,
                                                        dict(items.get(iid) or {})))
    for rec in phase_responses or []:
        if rec.get("superseded") or rec.get("hidden"):
            continue
        for rule in rules:
            if rec.get("schema") != rule.get("scheme"):
                continue
            scheme = schemes.get(rule["scheme"])
            answer = decode_answer(rec.get("value"))
            if scheme is None or not answer:
                continue
            uid = str(rec.get("user_id", ""))
            by_user.setdefault(uid, []).append(Decision(
                uid, rule, scheme, f"{rec.get('phase')}/{rec.get('page')}", answer))
    return by_user


def compute_incentives(config: Mapping[str, Any], annotations: Iterable[dict],
                       phase_responses: Iterable[dict], items: Mapping[str, dict],
                       states: Mapping[str, Mapping[str, Any]],
                       config_dir: Optional[str] = None) -> IncentiveReport:
    """Every participant's bonus. Deterministic for the same stored answers."""
    block = dict(config.get("incentives") or {})
    report = IncentiveReport(currency=str(block.get("currency", "USD")),
                             pay=str(block.get("pay", "one_random_item")))
    if not block:
        report.warnings.append("no incentives block in the config")
        return report
    secret = str(block.get("seed", ""))
    if not secret:
        report.warnings.append(
            "incentives.seed is not set: the draws depend only on the user id and the rule "
            "name, so anyone who knows both could compute them in advance")
    elif placeholder_seed_warning(config):
        report.warnings.append(placeholder_seed_warning(config))
    only_finished = bool(block.get("only_finished", True))
    cap = block.get("max_bonus")
    schemes, _ = find_schemes(config, config_dir)
    decisions = collect_decisions(config, annotations, phase_responses, items, schemes)

    for uid in sorted(decisions):
        state = states.get(uid) or {}
        pid = _prolific_id(state, config)
        finished = _finished(state)
        mine = sorted(decisions[uid], key=lambda d: (rule_name(d.rule), d.key))
        base = {"user_id": uid, "prolific_id": pid, "finished": finished}
        if only_finished and not finished:
            for d in mine:
                report.rows.append({**base, "rule": rule_name(d.rule), "method": d.rule["method"],
                                    "scheme": d.rule["scheme"], "decision": d.key, "seed": "",
                                    "draws": "", "payoff": "", "paid": False, "pay_after": "",
                                    "note": "not finished; nothing drawn"})
            report.totals[uid] = {"prolific_id": pid, "finished": False, "total": Decimal("0.00"),
                                  "uncapped": Decimal("0.00"), "capped": False, "pay_after": "",
                                  "pending": False, "eligible": False, "reason": "not finished"}
            continue

        results = [(d, _pay_decision(d, secret)) for d in mine]
        # The draw is over every decision with a usable answer, including
        # those still waiting for an outcome, so filling in an outcome later
        # never changes which decision is paid.
        drawable = [i for i, (_, r) in enumerate(results) if r["valid"] or r["pending"]]
        paid: List[int] = []
        pick: Dict[str, Any] = {}
        if drawable:
            if report.pay == "one_random_item":
                pay_rng = decision_rng(uid, "__pay__", "", secret)
                j = pay_rng.randrange(len(drawable))
                paid = [drawable[j]]
                pick = {"paid_decision": j + 1, "of": len(drawable)}
            else:
                paid = drawable
        waiting = [results[i][0].key for i in paid if results[i][1]["pending"]]
        uncapped = sum((cents(results[i][1]["payoff"]) for i in paid), Decimal("0.00"))
        total = max(uncapped, Decimal("0.00"))
        capped = cap is not None and total > cents(cap)
        if capped:
            total = cents(cap)
        delays = sorted({results[i][1]["pay_after"] for i in paid if results[i][1]["pay_after"]})

        for i, (d, r) in enumerate(results):
            draws = dict(r["draws"])
            if i in paid and pick:
                draws.update(pick)
            report.rows.append({
                **base, "rule": rule_name(d.rule), "method": d.rule["method"],
                "scheme": d.rule["scheme"], "decision": d.key,
                "seed": draw_seed(uid, rule_name(d.rule)),
                "draws": json.dumps(draws, sort_keys=True) if draws else "",
                "payoff": f"{cents(r['payoff']):.2f}" if r["valid"] else "",
                "paid": i in paid, "pay_after": r["pay_after"], "note": r["note"]})

        reason = ""
        if waiting:
            reason = f"pending: {', '.join(waiting)} has no outcome yet"
            report.warnings.append(f"{uid}: the paid decision {', '.join(waiting)} cannot be "
                                   "scored yet; pending, left out of the Prolific file")
        elif total <= 0:
            reason = "nothing to pay"
        elif not pid:
            reason = "no Prolific id"
            report.warnings.append(f"{uid}: bonus {total:.2f} but no Prolific id was recorded at "
                                   "login (log in with url_argument PROLIFIC_PID or the "
                                   "prolific provider)")
        elif delays:
            reason = f"pays later ({', '.join(delays)})"
            report.warnings.append(f"{uid}: bonus {total:.2f} pays {', '.join(delays)}; "
                                   "left out of the Prolific file")
        report.totals[uid] = {"prolific_id": pid, "finished": finished, "total": total,
                              "uncapped": uncapped, "capped": capped, "pay_after": ", ".join(delays),
                              "pending": bool(waiting), "eligible": not reason, "reason": reason}
    return report


# ---------------------------------------------------------------------------
# loading stored answers
# ---------------------------------------------------------------------------

def _config_dir(config: Mapping[str, Any]) -> str:
    if config.get("config_file"):
        return os.path.dirname(os.path.abspath(str(config["config_file"])))
    return os.path.abspath(str(config.get("task_dir") or "."))


def _output_dir(config: Mapping[str, Any], config_dir: str) -> str:
    base = _task_dir(config, config_dir)
    out = str(config.get("output_annotation_dir") or os.path.join(base, "annotation_output"))
    return out if os.path.isabs(out) else os.path.join(base, out)


PAYMENTS_FILE = "incentive_payments.json"


def _task_dir(config: Mapping[str, Any], config_dir: str) -> str:
    task_dir = str(config.get("task_dir") or ".")
    return task_dir if os.path.isabs(task_dir) else os.path.normpath(os.path.join(config_dir, task_dir))


def payments_path(config: Mapping[str, Any], config_dir: Optional[str] = None) -> str:
    """``<task_dir>/incentive_payments.json``: every bonus batch sent to Prolific."""
    return os.path.join(_task_dir(config, config_dir or _config_dir(config)), PAYMENTS_FILE)


def rows_total(rows: Sequence[Sequence[str]]) -> str:
    """The total of Prolific bonus rows, as the dry run prints it ("12.40")."""
    return f"{sum((Decimal(str(a)) for _, a in rows), Decimal('0.00')):.2f}"


def paid_participants(path: str) -> set:
    """Every participant id a recorded batch has paid."""
    return {str(p) for rec in load_payments(path) for p, _ in rec.get("rows") or []}


def batch_key(rows: Sequence[Sequence[str]]) -> str:
    """A hash of the payee rows, independent of their order."""
    import hashlib
    canon = json.dumps(sorted([str(p), str(a)] for p, a in rows), separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def load_payments(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"{path} is not a list of payment records")
    return data


def earlier_payments(path: str, rows: Sequence[Sequence[str]]) -> List[Dict[str, Any]]:
    """Recorded batches that paid these rows, or any participant in them."""
    key = batch_key(rows)
    payees = {str(p) for p, _ in rows}
    return [rec for rec in load_payments(path)
            if rec.get("batch_key") == key
            or payees & {str(p) for p, _ in rec.get("rows") or []}]


def record_payment(path: str, rows: Sequence[Sequence[str]], bulk_id: str, study_id: str,
                   total: str, repeat: bool = False) -> Dict[str, Any]:
    """Append a paid batch to the payments file (written atomically)."""
    import time
    records = load_payments(path)
    rec = {"batch_key": batch_key(rows), "bulk_id": str(bulk_id), "study_id": str(study_id),
           "total": str(total), "rows": [[str(p), str(a)] for p, a in rows],
           "paid_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "repeat": bool(repeat)}
    records.append(rec)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)
    os.replace(tmp, path)
    return rec


def report_from_config(config: Mapping[str, Any], config_dir: Optional[str] = None) -> IncentiveReport:
    """Load every stored answer for ``config`` and compute the bonuses.

    Raises ValueError when the incentives block is missing, disabled or
    invalid.
    """
    from potato.export.cli import (load_annotations_from_output_dir, load_items_from_data_files,
                                   load_phase_responses_from_output_dir)
    from potato.server_utils.stored_states import iter_stored_states
    block = config.get("incentives")
    if not isinstance(block, dict) or not block.get("enabled"):
        raise ValueError("incentives are not enabled in this config (incentives.enabled)")
    config_dir = config_dir or _config_dir(config)
    problems = incentive_config_problems(config, config_dir)
    if problems:
        raise ValueError(problems[0])
    out_dir = _output_dir(config, config_dir)
    cfg = dict(config)
    items = load_items_from_data_files(cfg, config_dir)
    annotations = load_annotations_from_output_dir(out_dir, cfg.get("annotation_schemes") or [], cfg)
    phases = load_phase_responses_from_output_dir(out_dir, config=cfg)
    states = {str(s.get("user_id", name)): s for name, s in iter_stored_states(out_dir, cfg)}
    return compute_incentives(cfg, annotations, phases, items, states, config_dir)

"""
What an AI action will cost, and refusing to start one that costs too much.

The loudest money complaint about the commercial annotation platforms is not
the price. It is the *surprise*: credits consumed by auto-labelling and
discovered at export time, when the work is already done and the bill is
already owed.

Potato's bring-your-own-key model avoids the lock-in and reproduces the
surprise exactly. The bill is unbounded and invisible until the provider sends
it, and nothing in the tool has ever said what a run was about to cost.

Three things, in the order they matter:

**A pre-run estimate.** Projected tokens and dollars for an action over N
items, *before* it starts. Most of the value is here: the number is usually
either obviously fine or obviously not.

**A cap that refuses up front.** Halting halfway through leaves a project with
a partly-labelled dataset and a bill for it. A cap that checks the estimate
first refuses to start, which is the only refusal that saves money.

**A running total**, so the estimate can be checked against reality and the
next one trusted.

On the price table
------------------
Prices change and this table will go stale. That is why every estimate carries
``priced`` and ``as_of``: an estimate from a stale price is still useful for
order of magnitude, but it must never be presented as though it were a quote.
A model that is not in the table reports tokens and ``cost: None`` rather than
guessing -- a made-up price is worse than no price, because it will be
believed.

Self-hosted models (vLLM, Ollama) are priced at zero, which is *correct*: the
marginal cost of a local call is electricity. The estimate still reports the
token count, because that is what predicts how long the run takes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

#: When the prices below were last checked. Reported with every estimate so a
#: stale table is visible rather than silently trusted.
PRICES_AS_OF = "2026-08"

#: USD per 1,000,000 tokens, (input, output), keyed by a model-name prefix.
#: Longest prefix wins, so "gpt-4o-mini" is not priced as "gpt-4o".
PRICE_TABLE: Dict[str, tuple] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "o3-mini": (1.10, 4.40),
    "claude-haiku": (0.80, 4.00),
    "claude-sonnet": (3.00, 15.00),
    "claude-opus": (15.00, 75.00),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-1.5-flash": (0.075, 0.30),
    "gemini-1.5-pro": (1.25, 5.00),
}

#: Endpoint types that run on hardware you already pay for. Zero is the right
#: marginal price, not a missing one, so these are priced rather than unknown.
LOCAL_ENDPOINTS = frozenset({"vllm", "ollama", "huggingface", "yolo", "sam",
                             "sam2", "sam3"})

#: Characters per token. A rule of thumb, and stated as one: real tokenizers
#: vary by 20-30% and by language, so this is for deciding "is this run
#: affordable", never for reconciling an invoice.
CHARS_PER_TOKEN = 4.0


@dataclass
class CostEstimate:
    """What a run is projected to cost, and how much to trust the projection."""

    n_items: int
    input_tokens: int
    output_tokens: int
    model: str = ""
    #: None when the model is not in the price table. Deliberately not zero:
    #: "free" and "unknown" are different, and only one of them is safe to
    #: budget against.
    cost_usd: Optional[float] = None
    priced: bool = False
    #: Whether the model runs on hardware you already pay for. Carried as a
    #: FACT rather than inferred from cost_usd == 0, which is also true of an
    #: empty batch on a paid model -- and reporting that as "self-hosted" is a
    #: claim about someone's infrastructure that happens to be wrong.
    local: bool = False
    as_of: str = PRICES_AS_OF
    notes: List[str] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> dict:
        return {
            "n_items": self.n_items,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "model": self.model,
            "cost_usd": self.cost_usd,
            "priced": self.priced,
            "local": self.local,
            "as_of": self.as_of,
            "notes": list(self.notes),
        }

    def summary(self) -> str:
        """One line for a human about to press the button."""
        if not self.n_items:
            return "Nothing to run."
        if self.cost_usd is None:
            return (f"{self.n_items} item(s), about {self.total_tokens:,} "
                    f"tokens. No price on record for {self.model or 'this model'}, "
                    f"so the cost is unknown.")
        if self.local:
            return (f"{self.n_items} item(s), about {self.total_tokens:,} "
                    f"tokens, on a self-hosted model: no per-token cost.")
        return (f"{self.n_items} item(s), about {self.total_tokens:,} tokens, "
                f"roughly ${self.cost_usd:.2f} at {self.as_of} prices. "
                f"An estimate, not a quote.")


def price_for(model: str, endpoint_type: str = "") -> Optional[tuple]:
    """
    ``(input, output)`` USD per million tokens, or None if unknown.

    Matches on the longest prefix so a cheaper variant is not priced as its
    expensive parent -- "gpt-4o-mini" costs a sixteenth of "gpt-4o", and
    getting that backwards is a sixteen-fold error in the direction that
    stops people using the feature.
    """
    if (endpoint_type or "").lower() in LOCAL_ENDPOINTS:
        return (0.0, 0.0)

    name = (model or "").lower()
    best = None
    for prefix, prices in PRICE_TABLE.items():
        if prefix in name and (best is None or len(prefix) > len(best[0])):
            best = (prefix, prices)
    return best[1] if best else None


def estimate_tokens(texts: Sequence[str], prompt_overhead_chars: int = 0,
                    max_output_tokens: int = 100) -> tuple:
    """
    ``(input_tokens, output_tokens)`` for a batch, from character counts.

    Output is counted at the configured *maximum*, not an average. An estimate
    that assumes short answers is the one that surprises you, and the whole
    point of this module is not being surprised.
    """
    total_chars = sum(len(t or "") for t in texts) + \
        prompt_overhead_chars * len(texts)
    input_tokens = int(total_chars / CHARS_PER_TOKEN)
    return input_tokens, int(max_output_tokens) * len(texts)


def estimate(texts: Sequence[str], model: str, endpoint_type: str = "",
             prompt_overhead_chars: int = 0, max_output_tokens: int = 100,
             calls_per_item: int = 1) -> CostEstimate:
    """
    Project the cost of running a model over ``texts``.

    Args:
        calls_per_item: More than one where an action queries per item more
            than once -- the position-bias probe judges everything twice, and
            an estimate that halved its cost would be exactly the surprise
            this exists to prevent.
    """
    input_tokens, output_tokens = estimate_tokens(
        texts, prompt_overhead_chars, max_output_tokens)
    input_tokens *= max(1, calls_per_item)
    output_tokens *= max(1, calls_per_item)

    prices = price_for(model, endpoint_type)
    result = CostEstimate(
        n_items=len(texts), input_tokens=input_tokens,
        output_tokens=output_tokens, model=model,
    )
    if prices is None:
        result.notes.append(
            f"No price on record for {model!r}. The token counts are still "
            f"projected; the cost is not, because a guessed price would be "
            f"believed.")
        return result

    result.priced = True
    result.local = (endpoint_type or "").lower() in LOCAL_ENDPOINTS
    # Six decimals, not four. Individual runs are often fractions of a cent,
    # and rounding each one to 4dp before the running total sums them makes
    # the total drift from the invoice by more than the rounding saves in
    # readability. Display rounding belongs in the display.
    result.cost_usd = round(
        input_tokens / 1_000_000 * prices[0]
        + output_tokens / 1_000_000 * prices[1], 6)
    if result.local:
        result.notes.append(
            "Self-hosted: no per-token cost. The token count still predicts "
            "how long the run takes.")
    if calls_per_item > 1:
        result.notes.append(
            f"This action queries the model {calls_per_item} times per item.")
    return result


# --------------------------------------------------------------- the cap


class SpendCapExceeded(RuntimeError):
    """Raised instead of starting a run that would exceed the cap."""

    def __init__(self, message: str, estimate: Optional[CostEstimate] = None,
                 spent: float = 0.0, cap: float = 0.0):
        super().__init__(message)
        self.estimate = estimate
        self.spent = spent
        self.cap = cap


def cap_for(config: Dict[str, Any]) -> Optional[float]:
    """The configured USD ceiling for this project, or None."""
    settings = config.get("ai_budget") or {}
    value = settings.get("cap_usd")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        logger.warning("ai_budget.cap_usd is not a number: %r", value)
        return None


def check_before_running(config: Dict[str, Any], projected: CostEstimate,
                         spent_usd: float = 0.0) -> None:
    """
    Refuse a run that would take the project past its cap.

    Checked BEFORE the first call, not during. Halting halfway leaves a
    part-labelled dataset and a bill for it, which is the worst of both --
    refusing up front is the only refusal that actually saves money.

    An unpriced model does not block: the cap is a dollar ceiling and there is
    no dollar figure to compare it against. Saying so is better than either
    refusing a run that might be free or waving through one that might not be.

    Raises:
        SpendCapExceeded: When the projection crosses the cap.
    """
    cap = cap_for(config)
    if cap is None:
        return
    if projected.cost_usd is None:
        logger.warning(
            "ai_budget.cap_usd is set but %r has no price on record, so this "
            "run cannot be checked against it. Projected %s tokens.",
            projected.model, f"{projected.total_tokens:,}")
        return

    projected_total = spent_usd + projected.cost_usd
    if projected_total > cap:
        raise SpendCapExceeded(
            f"This run is projected to cost ${projected.cost_usd:.2f}, which "
            f"would take the project to ${projected_total:.2f} against a cap "
            f"of ${cap:.2f} (${spent_usd:.2f} already spent). Nothing has "
            f"been run. Raise ai_budget.cap_usd, or run fewer items.",
            estimate=projected, spent=spent_usd, cap=cap)


# ------------------------------------------------------------ the running total


_SPEND_MIGRATION = None


def _db(task_dir: str):
    from potato.persistence import Migration, get_db, register_migration

    global _SPEND_MIGRATION
    if _SPEND_MIGRATION is None:
        _SPEND_MIGRATION = Migration(
            name="0001_ai_spend",
            sql="""
            CREATE TABLE IF NOT EXISTS ai_spend (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                project       TEXT NOT NULL,
                action        TEXT NOT NULL,
                model         TEXT NOT NULL DEFAULT '',
                n_items       INTEGER NOT NULL DEFAULT 0,
                input_tokens  INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                cost_usd      REAL,
                estimated     INTEGER NOT NULL DEFAULT 1,
                created_at    REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ai_spend_project
                ON ai_spend (project, created_at DESC);
            """,
        )
    register_migration(_SPEND_MIGRATION)
    return get_db(task_dir)


def record_spend(config: Dict[str, Any], action: str,
                 spend: CostEstimate, estimated: bool = True) -> None:
    """
    Log what a run cost.

    ``estimated`` is stored rather than assumed. A projection and a measured
    figure are different kinds of number, and a total that silently mixes them
    cannot be checked against an invoice -- which is the only way anyone finds
    out the estimate was wrong.
    """
    import time

    try:
        conn = _db(config.get("task_dir", "."))
        conn.execute(
            """INSERT INTO ai_spend (project, action, model, n_items,
                   input_tokens, output_tokens, cost_usd, estimated, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (config.get("annotation_task_name", "default"), action,
             spend.model, spend.n_items, spend.input_tokens,
             spend.output_tokens, spend.cost_usd, 1 if estimated else 0,
             time.time()),
        )
        conn.commit()
    except Exception:
        # A run that happened but was not logged beats an exception after the
        # model has already been paid for.
        logger.exception("Could not record AI spend for %s", action)


def total_spend(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    The project's running AI total, and what it is made of.

    ``cost_usd`` sums only the priced rows. Unpriced runs are counted
    separately, because folding them in as zero would report a project using
    an unpriced model as having spent nothing.
    """
    try:
        rows = _db(config.get("task_dir", ".")).execute(
            """SELECT action, model, n_items, input_tokens, output_tokens,
                      cost_usd, estimated, created_at
               FROM ai_spend WHERE project = ? ORDER BY created_at DESC""",
            (config.get("annotation_task_name", "default"),),
        ).fetchall()
    except Exception:
        logger.debug("Could not read AI spend", exc_info=True)
        rows = []

    runs = [dict(r) for r in rows]
    priced = [r for r in runs if r["cost_usd"] is not None]
    return {
        "cost_usd": round(sum(r["cost_usd"] for r in priced), 6),
        "total_tokens": sum(r["input_tokens"] + r["output_tokens"] for r in runs),
        "n_runs": len(runs),
        "n_unpriced_runs": len(runs) - len(priced),
        "cap_usd": cap_for(config),
        "runs": runs[:50],
        "note": (
            f"{len(runs) - len(priced)} run(s) used a model with no price on "
            f"record and are not in the dollar total."
        ) if len(runs) != len(priced) else "",
    }

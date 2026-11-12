"""Who or what produced an annotation.

Potato has had one kind of participant: a person with a ``user_state.json``.
Two facilities already put machine output beside human output, and they solved
the problem in opposite directions.

The importers refuse to write machine output into a user state at all. The
comment in ``potato/importers/cli.py`` gives the reason -- doing so "would make
machine output indistinguishable from human work and fabricate agreement
between annotators who never touched the item" -- so imported predictions live
in item data, where no agreement, adjudication or psychometric code can reach
them.

The simulator does the opposite. ``potato/simulator/user_simulator.py``
registers over HTTP, authenticates, and saves through ``/updateinstance``, so an
LLM-driven annotator gets a real user state by the ordinary route. It is then
counted as a person by ``/admin/iaa``, MACE and the IRT engine, because nothing
on the user state says it was not one. A researcher who runs the LLM strategy to
build a machine baseline gets contaminated reliability statistics and no warning.

Origin is the fact both facilities were missing. A participant declared in the
``machine_annotators`` config block carries its kind, its identity and its
version on the user state, so measurement code can separate raters by kind
instead of guessing from a username prefix. Declared machines are legitimate
raters. Undeclared ones are what the importer guard was written against, and
this module does not create a way to make one.

Two rules the rest of the codebase depends on:

**Absent means human.** A user state with no ``origin`` is a person. Every study
that predates this module keeps the behaviour it had, and that is what makes the
change safe to land on a running project.

**Present but unreadable means machine.** If something wrote an ``origin`` that
cannot be parsed, the conservative reading is the one that keeps it out of
human-human agreement. Counting a machine as a person corrupts the number a
study exists to produce; counting a person as a machine only withholds their
rows from one partition.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional

logger = logging.getLogger(__name__)

#: A participant who is a person.
HUMAN = "human"

#: A non-human participant that is an analysis pipeline or program -- Prokka,
#: a parser, a detector. It has a version and a database, not a prompt.
TOOL = "tool"

#: A non-human participant that is a language model.
LLM = "llm"

MACHINE_KINDS = (TOOL, LLM)
KNOWN_KINDS = (HUMAN,) + MACHINE_KINDS

#: The origin every participant has until something says otherwise.
HUMAN_ORIGIN: Dict[str, Any] = {"kind": HUMAN}

PAIR_HUMAN_HUMAN = "human_human"
PAIR_MACHINE_MACHINE = "machine_machine"
PAIR_HUMAN_MACHINE = "human_machine"

#: Optional fields copied from a declaration onto the stored origin. `version`,
#: `database_version` and `run_date` are here because a benchmark of four genome
#: annotation tools (Jundzill et al., Genome Biology 27:284) could not analyse
#: how annotations drifted between releases: the tools record what they found
#: and not which database found it, so a re-run that gains 139 features cannot
#: be told from a database that gained them.
_OPTIONAL_ORIGIN_FIELDS = (
    "tool",
    "model",
    "endpoint_type",
    "version",
    "database_version",
    "run_date",
    "description",
)


def _now() -> str:
    """UTC, to the second. Sub-second precision on a provenance stamp is noise."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class MachineAnnotator:
    """One declared non-human rater.

    ``id`` is the user id the machine annotates under, so it is the join key
    between this declaration and the user state on disk.
    """

    id: str
    kind: str = TOOL
    tool: Optional[str] = None
    model: Optional[str] = None
    endpoint_type: Optional[str] = None
    version: Optional[str] = None
    database_version: Optional[str] = None
    run_date: Optional[str] = None
    description: Optional[str] = None

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> Optional["MachineAnnotator"]:
        """Build one declaration, or None if it has no usable id."""
        if not isinstance(raw, Mapping):
            logger.warning(
                "machine_annotators.annotators entry is %s, not a mapping; ignored",
                type(raw).__name__,
            )
            return None

        raw_id = raw.get("id")
        if raw_id is None or not str(raw_id).strip():
            logger.warning(
                "machine_annotators.annotators entry has no 'id' and cannot be "
                "matched to a user state; ignored"
            )
            return None

        kind = str(raw.get("kind") or TOOL).strip().lower()
        if kind not in MACHINE_KINDS:
            # Not fatal. An unknown kind still is not human, and treating it as
            # machine keeps it out of human-human agreement, which is the
            # reading that cannot corrupt a published number.
            logger.warning(
                "machine_annotators: %r declares kind %r; expected one of %s. "
                "Treating it as a machine rater",
                raw_id, kind, ", ".join(MACHINE_KINDS),
            )

        def _opt(name: str) -> Optional[str]:
            value = raw.get(name)
            return None if value is None else str(value)

        return cls(
            id=str(raw_id).strip(),
            kind=kind,
            **{name: _opt(name) for name in _OPTIONAL_ORIGIN_FIELDS},
        )

    def to_origin(self, recorded_at: Optional[str] = None) -> Dict[str, Any]:
        """The dict stored on the user state and serialized to disk."""
        origin: Dict[str, Any] = {
            "kind": self.kind,
            "id": self.id,
            "declared_in": "config",
        }
        for name in _OPTIONAL_ORIGIN_FIELDS:
            value = getattr(self, name)
            if value is not None:
                origin[name] = value
        origin["recorded_at"] = recorded_at or _now()
        return origin


def parse_machine_annotators(
    config: Optional[Mapping[str, Any]],
) -> Dict[str, MachineAnnotator]:
    """Read the ``machine_annotators`` block into ``{user_id: declaration}``.

    Returns an empty roster when the block is absent or disabled, which is the
    same thing as "every participant is a person".

    Disabling the block stops new stamping; it does not unmake origins already
    written to disk. A rater that was a machine last week was still a machine,
    and ``origin_of`` keeps reading what is there.
    """
    if not isinstance(config, Mapping):
        return {}

    block = config.get("machine_annotators")
    if not isinstance(block, Mapping) or not block.get("enabled"):
        return {}

    declared = block.get("annotators")
    if declared is None:
        logger.warning(
            "machine_annotators is enabled but declares no 'annotators'; no "
            "participant will be recorded as a machine"
        )
        return {}
    if not isinstance(declared, (list, tuple)):
        logger.warning(
            "machine_annotators.annotators is %s, not a list; ignored",
            type(declared).__name__,
        )
        return {}

    roster: Dict[str, MachineAnnotator] = {}
    for raw in declared:
        annotator = MachineAnnotator.from_dict(raw)
        if annotator is None:
            continue
        if annotator.id in roster:
            # Keep the first. Taking the last would mean the file's ordering
            # silently decides which version string gets published.
            logger.warning(
                "machine_annotators declares %r twice; keeping the first "
                "declaration and ignoring the rest",
                annotator.id,
            )
            continue
        roster[annotator.id] = annotator

    return roster


def origin_of(subject: Any) -> Dict[str, Any]:
    """The origin of a user state, a raw origin mapping, or None.

    Always returns a readable origin dict. See the module docstring for why an
    absent origin reads as human and an unreadable one reads as machine.
    """
    if subject is None:
        return dict(HUMAN_ORIGIN)

    raw = subject if isinstance(subject, Mapping) else getattr(subject, "origin", None)

    if raw is None or raw == {}:
        return dict(HUMAN_ORIGIN)

    if not isinstance(raw, Mapping):
        logger.warning(
            "origin is %s, not a mapping; reading it as an undeclared machine "
            "rather than as a person", type(raw).__name__,
        )
        return {"kind": TOOL, "id": None, "malformed": True}

    kind = raw.get("kind")
    if not isinstance(kind, str) or not kind.strip():
        logger.warning(
            "origin %r has no readable 'kind'; reading it as an undeclared "
            "machine rather than as a person", raw,
        )
        out = dict(raw)
        out["kind"] = TOOL
        out["malformed"] = True
        return out

    return dict(raw)


def is_human(subject: Any) -> bool:
    """True when the participant is a person."""
    return origin_of(subject).get("kind") == HUMAN


def is_machine(subject: Any) -> bool:
    """True when the participant is anything other than a person."""
    return not is_human(subject)


def kind_of(subject: Any) -> str:
    """``"human"`` or ``"machine"`` -- the partition, not the declared sub-kind."""
    return HUMAN if is_human(subject) else "machine"


def describe(subject: Any) -> str:
    """A short label for a dashboard or a log line."""
    origin = origin_of(subject)
    kind = origin.get("kind", HUMAN)
    if kind == HUMAN:
        return "human"
    parts = [str(origin.get("id") or kind)]
    version = origin.get("version")
    if version:
        parts.append(str(version))
    database_version = origin.get("database_version")
    if database_version:
        parts.append(f"db {database_version}")
    return f"{' '.join(parts)} ({kind})"


def partition(user_states: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Split ``{user_id: user_state}`` into human and machine sub-dicts.

    The sub-dicts are the same shape as the input, so a caller can hand either
    one to code that already takes a ``user_states`` mapping. That is what lets
    the IAA dispatcher report per-partition metrics without any gatherer or
    aggregator knowing that origin exists.
    """
    groups: Dict[str, Dict[str, Any]] = {HUMAN: {}, "machine": {}}
    for user_id, state in (user_states or {}).items():
        groups[kind_of(state)][user_id] = state
    return groups


def pair_kind(subject_a: Any, subject_b: Any) -> str:
    """Classify a rater pair, for per-pair statistics such as Cohen's kappa.

    ``potato/judge_calibration/metrics.py`` already partitions pairs this way,
    keyed on a username prefix it controls. This keys the same taxonomy on the
    stored origin, so it works for raters that module never created.
    """
    a_machine = is_machine(subject_a)
    b_machine = is_machine(subject_b)
    if a_machine and b_machine:
        return PAIR_MACHINE_MACHINE
    if not a_machine and not b_machine:
        return PAIR_HUMAN_HUMAN
    return PAIR_HUMAN_MACHINE


def summarize(user_states: Mapping[str, Any]) -> Dict[str, Any]:
    """Counts and ids by kind, for the ``annotators`` block of a report."""
    groups = partition(user_states)
    return {
        "n_human": len(groups[HUMAN]),
        "n_machine": len(groups["machine"]),
        "human": sorted(groups[HUMAN]),
        "machine": sorted(groups["machine"]),
        "machine_detail": {
            user_id: describe(state)
            for user_id, state in sorted(groups["machine"].items())
        },
    }


def has_machine_participants(user_states: Mapping[str, Any]) -> bool:
    """True when at least one participant is not a person."""
    return any(is_machine(state) for state in (user_states or {}).values())


def undeclared_participant(
    user_id: Any,
    roster: Mapping[str, MachineAnnotator],
    authorized_usernames: Any = (),
) -> bool:
    """True when a participant is neither a declared machine nor a listed person.

    This is what ``machine_annotators.require_declaration`` refuses on. It is a
    pure function of three inputs so the rule can be tested without a request,
    a session, or a running server.

    ``authorized_usernames`` must be the study's *allowlist*
    (``user_config.authorized_users``), not the set of accounts that happen to
    exist. Every username that registers becomes a valid account -- that is
    what open registration means -- so a check against existing accounts would
    accept exactly the participants this refuses.
    """
    if not user_id:
        return False
    key = str(user_id)
    if key in (roster or {}):
        return False
    return key not in {str(u) for u in (authorized_usernames or ())}


def stamp_user_state(user_state: Any, roster: Mapping[str, MachineAnnotator]) -> bool:
    """Record a declared origin on one user state. True when it changed.

    Called from ``UserStateManager.add_user`` and ``load_user_state`` so that
    ``/register`` and ``/auth`` need no change: a machine that authenticates the
    ordinary way is stamped by the manager that created its state, and a state
    loaded from disk is re-stamped in case the declaration changed.

    Re-stamping preserves ``recorded_at`` when nothing else moved, so the
    timestamp keeps meaning "when this was first recorded" rather than "when the
    server last restarted".
    """
    if not roster:
        return False

    get_user_id = getattr(user_state, "get_user_id", None)
    user_id = get_user_id() if callable(get_user_id) else getattr(user_state, "user_id", None)
    if user_id is None:
        return False

    declared = roster.get(str(user_id))
    if declared is None:
        return False

    current = getattr(user_state, "origin", None)
    new = declared.to_origin()

    if isinstance(current, Mapping) and current:
        unchanged = all(
            current.get(name) == new.get(name)
            for name in ("kind", "id") + _OPTIONAL_ORIGIN_FIELDS
        )
        if unchanged:
            return False
        new["recorded_at"] = current.get("recorded_at", new["recorded_at"])

    user_state.origin = new
    logger.info("Recorded %r as a machine rater: %s", str(user_id), describe(new))
    return True

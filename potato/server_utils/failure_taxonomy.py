"""
Agent failure-mode taxonomies.

Ships canonical, research-backed failure taxonomies so a project can tag *why* an
agent trace failed without hand-authoring the label set. The flagship preset is
**MAST** (Multi-Agent System Failure Taxonomy) from Cemri et al. (2025),
*"Why Do Multi-Agent LLM Systems Fail?"* — 14 failure modes across 3 categories,
empirically derived with κ=0.88 human inter-annotator agreement.

Usage (in a config):

    annotation_schemes:
      - annotation_type: hierarchical_multiselect
        name: failure_modes
        description: "Tag every failure mode this trace exhibits"
        taxonomy_preset: mast        # auto-fills taxonomy + tooltips

The preset expands to the nested taxonomy the ``hierarchical_multiselect`` schema
already understands, and each mode's description is attached as a hover tooltip.

To add a taxonomy, append to ``TAXONOMY_PRESETS``. Each preset is an ordered
mapping ``{category: [(code, name, description), ...]}``.
"""

from collections import OrderedDict
from typing import Dict, List, Tuple

# A taxonomy is {category_name: [(code, mode_name, description), ...]}
Taxonomy = "Dict[str, List[Tuple[str, str, str]]]"


# --------------------------------------------------------------------------- #
# MAST — Multi-Agent System Failure Taxonomy (Cemri et al., 2025)
# --------------------------------------------------------------------------- #
MAST_TAXONOMY = OrderedDict([
    ("Specification & System Design", [
        ("1.1", "Disobey task specification",
         "The agent ignores or violates the constraints, format, or requirements "
         "stated in the task."),
        ("1.2", "Disobey role specification",
         "The agent acts outside its assigned role or persona (e.g. a reviewer "
         "starts writing the solution)."),
        ("1.3", "Step repetition",
         "The agent needlessly repeats a step or action it (or another agent) has "
         "already completed."),
        ("1.4", "Loss of conversation history",
         "The agent forgets or drops earlier context, contradicting or ignoring "
         "what was established before."),
        ("1.5", "Unaware of termination conditions",
         "The agent does not recognize the conditions under which the task is "
         "complete and should stop."),
    ]),
    ("Inter-Agent Misalignment", [
        ("2.1", "Conversation reset",
         "An agent unexpectedly restarts the dialogue, discarding accumulated "
         "progress."),
        ("2.2", "Fail to ask for clarification",
         "The agent proceeds on an ambiguous or under-specified request instead of "
         "asking a clarifying question."),
        ("2.3", "Task derailment",
         "The conversation drifts away from the original objective onto a tangent."),
        ("2.4", "Information withholding",
         "An agent fails to share information it holds that another agent needs."),
        ("2.5", "Ignored other agent's input",
         "An agent disregards relevant input, correction, or results provided by "
         "another agent."),
        ("2.6", "Reasoning-action mismatch",
         "The agent's stated reasoning does not match the action it actually "
         "takes."),
    ]),
    ("Task Verification & Termination", [
        ("3.1", "Premature termination",
         "The system stops before the task is actually complete."),
        ("3.2", "No or incomplete verification",
         "The output is not checked, or is checked only partially, before being "
         "accepted."),
        ("3.3", "Incorrect verification",
         "Verification is performed but reaches the wrong conclusion (accepts a "
         "bad result or rejects a good one)."),
    ]),
])


TAXONOMY_PRESETS = {
    "mast": MAST_TAXONOMY,
}


def get_preset(name: str):
    """Return the raw taxonomy preset (ordered {category: [(code, name, desc)]}).

    Raises ``KeyError`` with the list of valid names if unknown.
    """
    key = (name or "").strip().lower()
    if key not in TAXONOMY_PRESETS:
        raise KeyError(
            f"Unknown taxonomy preset '{name}'. "
            f"Available: {', '.join(sorted(TAXONOMY_PRESETS))}"
        )
    return TAXONOMY_PRESETS[key]


def to_hierarchical(name: str) -> "OrderedDict":
    """Expand a preset into the nested ``{category: [mode_name, ...]}`` dict that
    the ``hierarchical_multiselect`` schema consumes. Mode names are prefixed with
    their code (e.g. ``"1.1 Disobey task specification"``) so selections are
    self-identifying in exported data."""
    preset = get_preset(name)
    out = OrderedDict()
    for category, modes in preset.items():
        out[category] = [f"{code} {mode}" for code, mode, _desc in modes]
    return out


def to_tooltips(name: str) -> Dict[str, str]:
    """Map each coded label to its description, for hover tooltips."""
    preset = get_preset(name)
    tips: Dict[str, str] = {}
    for modes in preset.values():
        for code, mode, desc in modes:
            tips[f"{code} {mode}"] = desc
    return tips


def list_presets() -> List[str]:
    """Names of available taxonomy presets."""
    return sorted(TAXONOMY_PRESETS)


def mode_count(name: str) -> int:
    """Total number of failure modes in a preset."""
    return sum(len(modes) for modes in get_preset(name).values())

"""
Context-Attribution Schema.

Annotates how an agent USED its available context/memory at each turn:
did it draw on earlier information correctly, hallucinate context that was
never established, or ignore context it should have used? Attributions that
reference earlier material (used correctly / hallucinated) link the turn to
the source turn being (mis)used — the same cross-turn-link interaction as
``consensus_tracking``, whose generator this schema reuses.

Config::

    - annotation_type: context_attribution
      name: memory_use
      description: "How did the agent use its context?"
      turns_key: conversation      # instance field holding the turns
      # acts / linked_acts overridable like consensus_tracking

Stored as a hidden-input JSON list (shared format)::

    [{"turn": 6, "act": "hallucinated_context", "ref": 2, "agent_id": "assistant"}]
"""

from typing import Any, Dict, List, Tuple

from .identifier_utils import safe_generate_layout
from .consensus_tracking import _generate_internal as _consensus_internal

DEFAULT_ATTRIBUTIONS = ["used_context_correctly", "hallucinated_context", "ignored_context"]
#: Attributions that reference an earlier turn (arm link mode).
DEFAULT_LINKED_ATTRIBUTIONS = ["used_context_correctly", "hallucinated_context"]

_HINT = (
    "Tag how each turn uses earlier context. <em>used_context_correctly</em> and "
    "<em>hallucinated_context</em> then ask you to click the source turn being "
    "(mis)used; <em>ignored_context</em> stands alone."
)


def generate_context_attribution_layout(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    return safe_generate_layout(annotation_scheme, _generate_internal)


def _generate_internal(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    scheme = dict(annotation_scheme)
    scheme.setdefault("acts", DEFAULT_ATTRIBUTIONS)
    scheme.setdefault("linked_acts", DEFAULT_LINKED_ATTRIBUTIONS)
    scheme.setdefault("hint", _HINT)
    return _consensus_internal(scheme)

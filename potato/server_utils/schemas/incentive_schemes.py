"""The three incentivized elicitation schemes, re-exported in one place.

``price_list`` (multiple price list), ``bdm`` (Becker-DeGroot-Marschak bid)
and ``belief_elicitation`` (probability or distribution report). Payment for
all three is computed by ``potato/incentives.py``.
"""

from .bdm import generate_bdm_layout, validate_bdm
from .belief_elicitation import generate_belief_elicitation_layout, validate_belief_elicitation
from .price_list import generate_price_list_layout, validate_price_list

INCENTIVE_TYPES = ("price_list", "bdm", "belief_elicitation")

_VALIDATORS = {
    "price_list": validate_price_list,
    "bdm": validate_bdm,
    "belief_elicitation": validate_belief_elicitation,
}


def validate_incentive_scheme(scheme: dict) -> None:
    """Raise ValueError for a malformed price_list / bdm / belief_elicitation."""
    _VALIDATORS[scheme["annotation_type"]](scheme)


__all__ = ["generate_price_list_layout", "generate_bdm_layout",
           "generate_belief_elicitation_layout", "validate_incentive_scheme",
           "INCENTIVE_TYPES"]

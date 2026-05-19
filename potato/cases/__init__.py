"""
Cases (universal annotation feature).

Groups instances into units of analysis (interview participant,
respondent, document set) backed by the universal `project.sqlite`.
Top-level `cases:` config; QDA auto-detects from
`participant_id`/`respondent_id`/`case_id`. The crosstab reads
case-level attributes when set.

Layers:
- `store`   — SQLite persistence (cases / case_attributes / case_documents).
- `service` — get-or-create, auto-detection, attribute accessors.
"""

from .service import (
    DEFAULT_CASE_KEYS,
    assign_instance,
    attribute_for_instance,
    attributes,
    auto_detect,
    case_for_instance,
    cases_enabled,
    get_or_create_case,
    init_cases_from_config,
    list_cases,
    set_attribute,
)

__all__ = [
    "DEFAULT_CASE_KEYS",
    "get_or_create_case",
    "list_cases",
    "set_attribute",
    "attributes",
    "assign_instance",
    "case_for_instance",
    "attribute_for_instance",
    "auto_detect",
    "cases_enabled",
    "init_cases_from_config",
]

"""
Single-select exclusivity resolution.

Answers one question: *may this annotation schema persist more than one label?*

Background (GH #167). Annotations are stored as ``{Label(schema, label_name): value}``.
A ``radio``/``likert``/``confidence`` schema renders one input per option, each with its
own ``label_name``, so changing the answer writes a **new** dict key rather than
overwriting the old one. Unless the previous label is explicitly removed, both survive —
in ``instance_id_to_label_to_value`` during the annotation phase and in
``phase_to_page_to_label_to_value`` during consent / instructions / training / prestudy /
poststudy. The exported CSV then carries two populated columns for one answer with no way
to tell which one the annotator settled on.

This module is the single source of truth for that decision. It resolves a schema *name*
to its ``annotation_type`` across every place schemes can be declared, then defers to the
``single_select`` flag on the schema registry.

Deliberately dependency-light: ``config_module`` and ``cohort_schemes`` are imported
lazily inside functions so importing this module from the storage layer
(``user_state_management``) cannot create an import cycle.
"""

import logging
from typing import Any, Dict, Iterable, List, Optional, Set

from potato.server_utils.schemas.registry import schema_registry

logger = logging.getLogger(__name__)


#: Label names that legitimately coexist with a single-select schema's chosen option and
#: must therefore survive the purge.
#:
#: ``free_response`` is the "Other (please specify)" text input that ``radio`` and
#: ``multiselect`` attach to the *same* schema (``radio.py`` ``has_free_response``).
#:
#: ``bad_text`` is deliberately NOT listed: it is a real member of the likert radio group
#: (``likert.py`` ``bad_text_label``) and selecting it must replace the scale point.
#:
#: Owned by :mod:`potato.server_utils.answer_collapse` and re-exported here, so the
#: purge and the display-logic collapse can never disagree about what is exempt.
from potato.server_utils.answer_collapse import EXEMPT_LABEL_NAMES  # noqa: E402

NON_EXCLUSIVE_LABEL_NAMES = EXEMPT_LABEL_NAMES


def _config() -> Dict[str, Any]:
    """The live config dict, or an empty dict when no config is loaded."""
    try:
        from potato.server_utils.config_module import config
        return config or {}
    except Exception:  # pragma: no cover - config unavailable (bare unit tests)
        return {}


def _cohort_schemes_for_user(username: Optional[str]) -> Optional[List[dict]]:
    """Schemes the given user sees, or None when cohorts aren't in play."""
    if not username:
        return None
    try:
        from potato.server_utils.cohort_schemes import get_cohort_scheme_resolver
        return get_cohort_scheme_resolver().get_schemes_for_user(username)
    except Exception:
        # No resolver initialised (bare unit tests, or cohorts unused). Fall through
        # to the global scheme lists rather than failing the save.
        return None


def _scheme_lists(username: Optional[str] = None) -> Iterable[List[dict]]:
    """Every scheme list a schema name could be declared in, in resolution order.

    Cohort schemes win over the global ``annotation_schemes`` list; SurveyFlow question
    schemes come last because they live in a namespace of their own (phase pages), and a
    same-named annotation scheme should take precedence.
    """
    cohort = _cohort_schemes_for_user(username)
    if cohort:
        yield cohort
    cfg = _config()
    yield cfg.get("annotation_schemes") or []
    # SurveyFlow question schemes, stashed by flask_server after phase loading. These
    # are the ones the pre-#167 code could never resolve.
    yield cfg.get("_surveyflow_schemes") or []


def _find_scheme(schema_name: str, username: Optional[str] = None) -> Optional[dict]:
    """The scheme dict declaring ``schema_name``, or None."""
    if not schema_name:
        return None
    for schemes in _scheme_lists(username):
        for scheme in schemes:
            if isinstance(scheme, dict) and scheme.get("name") == schema_name:
                return scheme
    return None


def resolve_annotation_type(schema_name: str,
                            username: Optional[str] = None) -> Optional[str]:
    """Resolve a schema name to its configured ``annotation_type``.

    Args:
        schema_name: The schema's ``name`` as it appears in the config.
        username: Used to pick the right cohort scheme list, when cohorts are in use.

    Returns:
        The annotation type, or None when the schema cannot be found (a dynamically
        injected or already-removed schema).
    """
    scheme = _find_scheme(schema_name, username)
    return scheme.get("annotation_type") if scheme else None


def _scheme_is_single_select(scheme: Optional[dict]) -> bool:
    """Whether a resolved scheme dict is single-select."""
    if not scheme:
        return False
    # turn_level / session_level schemes never run their registered generator
    # (front_end.py routes them to a single hidden `_data` input, or to no input at
    # all), so their declared annotation_type says nothing about the labels stored.
    if scheme.get("turn_level") or scheme.get("session_level"):
        return False
    definition = schema_registry.get(scheme.get("annotation_type"))
    return bool(definition and definition.single_select)


def is_single_select(schema_name: str, username: Optional[str] = None) -> bool:
    """Whether ``schema_name`` may persist at most one label.

    Unknown schemas resolve to False: refusing to delete is the safe default when we
    cannot prove the schema is exclusive.
    """
    return _scheme_is_single_select(_find_scheme(schema_name, username))


def is_multiselect(schema_name: str, username: Optional[str] = None) -> bool:
    """Whether ``schema_name`` is a checkbox multiselect.

    Multiselect is not single-select, but it still needs its labels cleared before a
    re-write *when the client sends the complete set*, so that a deselected checkbox is
    actually removed rather than left behind.
    """
    return resolve_annotation_type(schema_name, username) == "multiselect"


def single_select_schema_names(schemes: Iterable[dict]) -> Set[str]:
    """Names of the single-select schemas in an arbitrary scheme list."""
    names = set()
    for scheme in schemes or []:
        if isinstance(scheme, dict) and _scheme_is_single_select(scheme):
            name = scheme.get("name")
            if name:
                names.add(name)
    return names


def all_single_select_schema_names(config: Optional[Dict[str, Any]] = None) -> Set[str]:
    """Every single-select schema name a user could encounter in this deployment.

    Spans the global ``annotation_schemes``, all cohort scheme sets, and the SurveyFlow
    question schemes — so the resulting set is valid in every phase.
    """
    cfg = config if config is not None else _config()
    names = single_select_schema_names(cfg.get("annotation_schemes") or [])
    names |= single_select_schema_names(cfg.get("_surveyflow_schemes") or [])
    try:
        from potato.server_utils.cohort_schemes import get_cohort_scheme_resolver
        names |= single_select_schema_names(
            get_cohort_scheme_resolver().union_of_all_schemes()
        )
    except Exception:
        pass
    return names


def is_exempt_label(label_name: str) -> bool:
    """Whether a label name survives a single-select purge (see the constant above)."""
    return label_name in NON_EXCLUSIVE_LABEL_NAMES

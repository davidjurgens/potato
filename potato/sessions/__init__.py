"""
Session-level scoring (D1 enterprise parity).

Groups traces that share a ``session_id``/``thread_id`` into *sessions*
(cases in the ``<project>::sessions`` namespace of the universal cases
store) and lets annotators score the session as a whole — "did this
multi-trace interaction resolve the user's problem?" — the
Langfuse/LangSmith session-annotation workflow.

Config::

    sessions:
      enabled: true
      key: session_id          # optional; default scans session_id,
                               # thread_id, conversation_id
      attributes: [user_id]    # optional; lifted onto the session

    annotation_schemes:
      - annotation_type: likert
        name: session_quality
        description: "Overall session quality"
        size: 5
        session_level: true    # scored on /sessions, not per trace

Layers:
- ``service`` — enablement, auto-detection, aggregates, JSONL export.
- ``api``     — ``/sessions`` page + ``/api/sessions`` blueprint.

Storage: ``potato.cases.annotations`` (``case_annotations`` table).
"""

from .service import (
    DEFAULT_SESSION_KEYS,
    SESSION_LEVEL_SUPPORTED_TYPES,
    get_session_level_schemes,
    init_sessions_from_config,
    is_session_level_scheme,
    session_aggregates,
    sessions_enabled,
    sessions_project,
    write_session_export,
)

__all__ = [
    "DEFAULT_SESSION_KEYS",
    "SESSION_LEVEL_SUPPORTED_TYPES",
    "get_session_level_schemes",
    "init_sessions_from_config",
    "is_session_level_scheme",
    "session_aggregates",
    "sessions_enabled",
    "sessions_project",
    "write_session_export",
]

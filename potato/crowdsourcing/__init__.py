"""Crowdsourcing platform integrations (Prolific, MTurk, generic panels)."""

from potato.crowdsourcing.base import (
    CompletionAction,
    CompletionOutcome,
    CrowdProvider,
    ParticipantIdentity,
)
from potato.crowdsourcing.registry import (
    clear_crowd_provider,
    get_crowd_provider,
    get_supported_providers,
    init_crowd_provider,
    register_provider,
)

__all__ = [
    "CompletionAction",
    "CompletionOutcome",
    "CrowdProvider",
    "ParticipantIdentity",
    "clear_crowd_provider",
    "get_crowd_provider",
    "get_supported_providers",
    "init_crowd_provider",
    "register_provider",
]

"""
Unit tests for GitHub issue #154 phase-type inference.

When a file-based phase omits `type:` but its name is a canonical phase
type, the type must be inferred from the name. Custom-named phases without
a `type:` must not crash the phase-sequence computation (previously a bare
`["type"]` dict access raised KeyError).
"""

from potato.phase import UserPhase
from potato.user_state_management import UserStateManager


def _usm(phases: dict) -> UserStateManager:
    return UserStateManager({"output_annotation_dir": ".", "phases": phases})


def test_typeless_canonical_phase_inferred_from_name():
    """A phase named `consent` with no `type:` is treated as CONSENT."""
    usm = _usm(
        {
            "order": ["consent", "annotation"],
            "consent": {"file": "consent.json"},
            "annotation": {"type": "annotation"},
        }
    )
    usm.add_phase(UserPhase.CONSENT, "consent", "consent.html")

    sequence = usm._get_configured_phase_sequence()

    assert UserPhase.CONSENT in sequence
    assert UserPhase.ANNOTATION in sequence


def test_explicit_type_still_takes_precedence_over_name():
    """An explicit `type:` overrides the phase name."""
    usm = _usm(
        {
            "order": ["intro", "annotation"],
            "intro": {"type": "prestudy", "file": "intro.json"},
            "annotation": {"type": "annotation"},
        }
    )
    usm.add_phase(UserPhase.PRESTUDY, "intro", "intro.html")

    sequence = usm._get_configured_phase_sequence()

    assert UserPhase.PRESTUDY in sequence


def test_custom_named_typeless_phase_does_not_crash():
    """A non-canonical phase name without `type:` is skipped, not a KeyError."""
    usm = _usm(
        {
            "order": ["weird_name", "annotation"],
            "weird_name": {"file": "weird.json"},
            "annotation": {"type": "annotation"},
        }
    )

    # Must not raise KeyError/ValueError; annotation still resolves.
    sequence = usm._get_configured_phase_sequence()

    assert UserPhase.ANNOTATION in sequence

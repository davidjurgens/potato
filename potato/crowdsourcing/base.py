"""
Core abstractions for crowdsourcing platform providers.

A CrowdProvider connects Potato to a recruitment platform (Prolific,
CloudResearch Connect, SONA, Mechanical Turk, generic panels, ...) using the
external-study-URL pattern:

    arrival:    platform sends the participant to Potato with ID URL params
                -> extract_identity() names the participant
    completion: Potato shows a completion code and/or sends the participant
                back to the platform -> completion_action() describes the UI,
                on_completion() performs server-side side effects (e.g. a
                SONA credit-grant call)

Providers are registered and resolved in potato.crowdsourcing.registry.
"""

from abc import ABC
from dataclasses import dataclass, field
from enum import Enum


@dataclass
class ParticipantIdentity:
    """Who arrived from the platform. worker_id becomes the Potato username."""

    worker_id: str
    session_id: str = None   # e.g. Prolific SESSION_ID, MTurk assignmentId
    study_id: str = None     # e.g. Prolific STUDY_ID, MTurk hitId, Connect projectId
    extra: dict = field(default_factory=dict)  # other captured params (e.g. turkSubmitTo)


class CompletionOutcome(Enum):
    """Why the participant reached the end of the task."""

    COMPLETED = "completed"
    FAILED_CHECKS = "failed_checks"    # blocked by attention-check threshold
    SCREENED_OUT = "screened_out"      # platform-paid screen-out
    NO_MORE_ITEMS = "no_more_items"    # ran out of assignable items


@dataclass
class CompletionAction:
    """What the done page should show / do for this participant.

    kind:
        code_only      show the completion code with copy-to-clipboard
        redirect       show a return button (and optionally auto-redirect)
        post_form      render a POST form back to the platform (MTurk)
        generated_code show a per-participant verification code (e.g. VCODE)
        none           plain thank-you page
    """

    kind: str = "none"
    code: str = None
    redirect_url: str = None
    form_action: str = None
    form_fields: dict = field(default_factory=dict)
    auto_redirect: bool = False
    auto_redirect_delay: int = 5000
    platform_label: str = ""
    message: str = None


class CrowdProvider(ABC):
    """Base class for crowdsourcing platform integrations.

    Subclasses override the hooks they need; the defaults implement a
    plain URL-parameter platform with a static completion code.
    """

    #: registry key and admin-dashboard grouping key
    name = "generic"
    #: human-readable platform name for UI labels
    display_name = "your crowdsourcing platform"

    def __init__(self, provider_config, app_config):
        """
        Args:
            provider_config (dict): this provider's sub-block of the
                ``crowdsourcing:`` config (or synthesized legacy config)
            app_config (dict): the full application config
        """
        self.config = provider_config or {}
        self.app_config = app_config or {}

    # --- arrival (home route) -------------------------------------------------

    def id_param(self):
        """Name of the URL parameter carrying the participant ID."""
        return self.config.get('id_param', 'PROLIFIC_PID')

    def extract_identity(self, request_args):
        """Build a ParticipantIdentity from the request's query parameters.

        Returns None when the ID parameter is missing (the caller renders a
        missing-parameter error page).
        """
        worker_id = request_args.get(self.id_param())
        if not worker_id:
            return None
        extra = {}
        for param in self.config.get('capture_params', []) or []:
            value = request_args.get(param)
            if value is not None:
                extra[param] = value
        return ParticipantIdentity(worker_id=worker_id, extra=extra)

    def is_preview(self, request_args):
        """True when the platform is showing a no-account preview (MTurk)."""
        return False

    def preview_response(self):
        """Flask response for preview mode; only used when is_preview() is True."""
        return None

    def on_arrival(self, identity):
        """Hook called after the participant is logged in. Best-effort:
        exceptions are logged by the caller, never shown to the participant."""

    # --- completion (done route) ----------------------------------------------

    def completion_action(self, identity, outcome):
        """Describe what the done page should render for this participant."""
        completion = self.config.get('completion', {}) or {}
        code = self._code_for_outcome(completion, outcome)
        redirect_template = completion.get('redirect_url')
        if redirect_template and code is not None:
            return CompletionAction(
                kind="redirect",
                code=code,
                redirect_url=self._fill_template(redirect_template, identity, code),
                auto_redirect=completion.get(
                    'auto_redirect',
                    bool(self.app_config.get('auto_redirect_on_completion', False))),
                auto_redirect_delay=int(self.app_config.get('auto_redirect_delay', 5000)),
                platform_label=self.platform_label(),
            )
        if code:
            return CompletionAction(kind="code_only", code=code,
                                    platform_label=self.platform_label())
        return CompletionAction(kind="none")

    def on_completion(self, identity, outcome):
        """Server-side completion side effects (credit grants, postbacks).

        Called before the done page is rendered. Must be idempotent: the done
        page can be re-rendered. Best-effort: exceptions are logged by the
        caller.
        """

    # --- optional API / lifecycle ---------------------------------------------

    def init_api(self):
        """Build the platform API client if credentials are configured."""

    def admin_summary(self):
        """Extra provider stats for the admin crowdsourcing dashboard."""
        return {}

    # --- helpers --------------------------------------------------------------

    def platform_label(self):
        label = self.config.get('platform_label')
        return label if label else self.display_name

    def _code_for_outcome(self, completion, outcome):
        """Pick the completion code for an outcome, falling back sensibly."""
        code = completion.get('code', self.app_config.get('completion_code'))
        if outcome == CompletionOutcome.FAILED_CHECKS:
            return completion.get('failed_code', code)
        if outcome == CompletionOutcome.SCREENED_OUT:
            return completion.get('screened_out_code',
                                  completion.get('failed_code', code))
        return code

    def _fill_template(self, template, identity, code):
        """Substitute {code}/{worker_id}/{session_id}/{study_id}/{<extra>} in a URL."""
        values = {
            'code': code or '',
            'worker_id': identity.worker_id if identity else '',
            'session_id': (identity.session_id if identity else None) or '',
            'study_id': (identity.study_id if identity else None) or '',
        }
        if identity:
            for key, value in identity.extra.items():
                values.setdefault(key, value)

        class _Missing(dict):
            def __missing__(self, key):
                return ''

        return template.format_map(_Missing(values))

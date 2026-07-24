"""
Backwards-compatibility provider for `login.type: url_direct` / `prolific`
configs that predate the `crowdsourcing:` block.

This reproduces the historical routes.py behavior exactly, including the
dual-platform quirk: one config simultaneously serves Prolific arrivals
(configured url_argument + SESSION_ID/STUDY_ID) and MTurk arrivals
(assignmentId/hitId/turkSubmitTo are always sniffed, and the MTurk preview
page is shown for ASSIGNMENT_ID_NOT_AVAILABLE). Do not "clean up" this
behavior: the shipped mturk-example relies on it, as do existing deployments
that run the same config on both platforms.
"""

from potato.crowdsourcing.base import (
    CompletionAction,
    CrowdProvider,
    ParticipantIdentity,
)
from potato.crowdsourcing.providers.mturk import (
    PREVIEW_ASSIGNMENT_ID,
    normalize_submit_url,
)
from potato.crowdsourcing.providers.prolific import PROLIFIC_COMPLETION_URL

MTURK_PARAMS = ('assignmentId', 'hitId', 'turkSubmitTo')


class LegacyUrlDirectProvider(CrowdProvider):
    name = "url_direct"
    display_name = "your crowdsourcing platform"

    def __init__(self, provider_config, app_config):
        super().__init__(provider_config, app_config)
        self.login_config = (app_config or {}).get('login', {}) or {}

    def id_param(self):
        return self.login_config.get('url_argument', 'PROLIFIC_PID')

    def uses_prolific_redirect(self):
        return self.id_param().lower() == 'prolific_pid'

    def extract_identity(self, request_args):
        worker_id = request_args.get(self.id_param())
        if not worker_id:
            return None
        identity = ParticipantIdentity(
            worker_id=worker_id,
            session_id=request_args.get('SESSION_ID'),
            study_id=request_args.get('STUDY_ID'),
        )
        for param in MTURK_PARAMS:
            value = request_args.get(param)
            if value:
                identity.extra[param] = value
        return identity

    def is_preview(self, request_args):
        return request_args.get('assignmentId') == PREVIEW_ASSIGNMENT_ID

    def preview_response(self):
        from flask import render_template
        config = self.app_config
        return render_template(
            "mturk_preview.html",
            title=config.get("annotation_task_name", "Task Preview"),
            task_description=config.get("task_description", ""),
            annotation_task_name=config.get("annotation_task_name", "Annotation Task"),
        )

    def on_arrival(self, identity):
        """Track Prolific sessions via the API when login.type: prolific is set up."""
        if not identity.session_id:
            return
        try:
            from potato.flask_server import get_prolific_study
            study = get_prolific_study()
        except Exception:
            return
        if study:
            study.add_new_user({
                'PROLIFIC_PID': identity.worker_id,
                'SESSION_ID': identity.session_id,
            })

    def completion_action(self, identity, outcome):
        code = self._code_for_outcome(self.config.get('completion', {}) or {}, outcome)
        submit_to = identity.extra.get('turkSubmitTo') if identity else None
        assignment_id = identity.extra.get('assignmentId') if identity else None

        if submit_to and assignment_id:
            fields = {'assignmentId': assignment_id}
            if code:
                fields['completionCode'] = code
            return CompletionAction(
                kind="post_form",
                code=code,
                form_action=normalize_submit_url(submit_to),
                form_fields=fields,
                platform_label="MTurk",
            )
        if code and self.uses_prolific_redirect():
            return CompletionAction(
                kind="redirect",
                code=code,
                redirect_url=PROLIFIC_COMPLETION_URL.format(code=code),
                auto_redirect=bool(self.app_config.get('auto_redirect_on_completion', False)),
                auto_redirect_delay=int(self.app_config.get('auto_redirect_delay', 5000)),
                platform_label="Prolific",
            )
        if code:
            return CompletionAction(kind="code_only", code=code,
                                    platform_label=self.platform_label())
        return CompletionAction(kind="none")

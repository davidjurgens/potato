"""
Mechanical Turk provider: workerId arrival, HIT preview mode, and the
POST-form submit back to turkSubmitTo.

MTurk closed to new requesters on 2026-07-30; this provider is maintained
for existing requester accounts (see docs/deployment/mturk_integration.md).
"""

from potato.crowdsourcing.base import (
    CompletionAction,
    CrowdProvider,
)

PREVIEW_ASSIGNMENT_ID = 'ASSIGNMENT_ID_NOT_AVAILABLE'


def normalize_submit_url(turk_submit_to):
    """MTurk sends turkSubmitTo as a bare origin; the ExternalQuestion submit
    endpoint is /mturk/externalSubmit on that host."""
    if turk_submit_to and '/mturk/externalSubmit' not in turk_submit_to:
        return turk_submit_to.rstrip('/') + '/mturk/externalSubmit'
    return turk_submit_to


class MTurkProvider(CrowdProvider):
    name = "mturk"
    display_name = "MTurk"

    def id_param(self):
        return self.config.get('id_param', 'workerId')

    def extract_identity(self, request_args):
        identity = super().extract_identity(request_args)
        if identity is None:
            return None
        identity.session_id = request_args.get('assignmentId')
        identity.study_id = request_args.get('hitId')
        turk_submit_to = request_args.get('turkSubmitTo')
        if turk_submit_to:
            identity.extra['turkSubmitTo'] = turk_submit_to
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

    def completion_action(self, identity, outcome):
        completion = self.config.get('completion', {}) or {}
        code = self._code_for_outcome(completion, outcome)
        submit_to = identity.extra.get('turkSubmitTo') if identity else None
        assignment_id = identity.session_id if identity else None
        if submit_to and assignment_id:
            fields = {'assignmentId': assignment_id}
            if code:
                fields['completionCode'] = code
            return CompletionAction(
                kind="post_form",
                code=code,
                form_action=normalize_submit_url(submit_to),
                form_fields=fields,
                platform_label=self.platform_label(),
            )
        if code:
            return CompletionAction(kind="code_only", code=code,
                                    platform_label=self.platform_label())
        return CompletionAction(kind="none")

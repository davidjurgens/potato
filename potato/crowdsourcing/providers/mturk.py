"""
Mechanical Turk provider: workerId arrival, HIT preview mode, and the
POST-form submit back to turkSubmitTo.

Amazon Mechanical Turk closed permanently on 2026-09-30: no HITs can be
created and no worker can reach a study through it. The provider remains so an
archived MTurk study's config still loads, its server starts, and its
annotations export (see docs/deployment/mturk_integration.md).
"""

from potato.crowdsourcing.base import (
    CompletionAction,
    CrowdProvider,
)

PREVIEW_ASSIGNMENT_ID = 'ASSIGNMENT_ID_NOT_AVAILABLE'


#: The hosts MTurk sends as turkSubmitTo (production and the worker sandbox).
MTURK_SUBMIT_HOSTS = frozenset({'www.mturk.com', 'workersandbox.mturk.com'})


def normalize_submit_url(turk_submit_to):
    """MTurk sends turkSubmitTo as a bare origin; the ExternalQuestion submit
    endpoint is /mturk/externalSubmit on that host.

    The value arrives as a URL parameter and becomes a form action, so only
    MTurk's own hosts are accepted; anything else is refused (None). A
    javascript: action would run script when the worker submits, and any
    other host would make the done page post the worker to it.
    """
    if not turk_submit_to:
        return turk_submit_to
    from urllib.parse import urlparse
    parsed = urlparse(str(turk_submit_to).strip())
    if (parsed.scheme.lower() != 'https'
            or (parsed.hostname or '').lower() not in MTURK_SUBMIT_HOSTS
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        return None
    # Rebuilt from the parsed host: appending to the raw value kept any
    # query, fragment or path the parameter carried.
    return f"https://{parsed.hostname.lower()}/mturk/externalSubmit"


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
        submit_to = normalize_submit_url(
            identity.extra.get('turkSubmitTo') if identity else None)
        assignment_id = identity.session_id if identity else None
        if submit_to and assignment_id:
            fields = {'assignmentId': assignment_id}
            if code:
                fields['completionCode'] = code
            return CompletionAction(
                kind="post_form",
                code=code,
                form_action=submit_to,
                form_fields=fields,
                platform_label=self.platform_label(),
            )
        if code:
            return CompletionAction(kind="code_only", code=code,
                                    platform_label=self.platform_label())
        return CompletionAction(kind="none")

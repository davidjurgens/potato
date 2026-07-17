"""
Prolific provider: PROLIFIC_PID/STUDY_ID/SESSION_ID arrival and the
app.prolific.com completion redirect, with the optional ProlificStudy API
client for submission tracking.

.. code-block:: yaml

    crowdsourcing:
      provider: prolific
      prolific:
        completion:
          code: "C1ABCDEF"          # defaults to top-level completion_code
          failed_code: "C1FAILED"   # optional screen-out/failure code
        # API features (optional):
        token: "..."                # or config_file_path
        study_id: "..."
"""

import logging

from potato.crowdsourcing.base import (
    CompletionAction,
    CrowdProvider,
)

logger = logging.getLogger(__name__)

PROLIFIC_COMPLETION_URL = "https://app.prolific.com/submissions/complete?cc={code}"


class ProlificProvider(CrowdProvider):
    name = "prolific"
    display_name = "Prolific"

    def id_param(self):
        return self.config.get('id_param', 'PROLIFIC_PID')

    def extract_identity(self, request_args):
        identity = super().extract_identity(request_args)
        if identity is None:
            return None
        identity.session_id = request_args.get('SESSION_ID')
        identity.study_id = request_args.get('STUDY_ID')
        return identity

    def on_arrival(self, identity):
        """Track the new session with the Prolific API when configured."""
        study = self._prolific_study()
        if study and identity.session_id:
            study.add_new_user({
                'PROLIFIC_PID': identity.worker_id,
                'SESSION_ID': identity.session_id,
            })

    def on_completion(self, identity, outcome):
        """Paid screen-out for participants blocked by attention checks.

        Requires `screen_out_on_block: true` plus API credentials (token +
        study_id), and the study must have the fixed screen-out feature with
        a screen-out completion code configured on Prolific.
        """
        from potato.crowdsourcing.base import CompletionOutcome
        if outcome not in (CompletionOutcome.FAILED_CHECKS, CompletionOutcome.SCREENED_OUT):
            return
        if not self.config.get('screen_out_on_block', False):
            return
        token = self.config.get('token')
        study_id = self.config.get('study_id')
        if not (token and study_id and identity and identity.session_id):
            logger.warning("screen_out_on_block set but token/study_id/session_id missing; "
                           "skipping API screen-out for %s",
                           identity.worker_id if identity else '?')
            return
        try:
            from potato.crowdsourcing.prolific_api import ProlificClient
            client = ProlificClient(token)
            client.screen_out_submissions(study_id, [identity.session_id])
            logger.info("Screened out Prolific submission %s (blocked participant %s)",
                        identity.session_id, identity.worker_id)
        except Exception as e:
            logger.warning("Prolific screen-out failed for %s: %s", identity.session_id, e)

    def completion_action(self, identity, outcome):
        completion = self.config.get('completion', {}) or {}
        code = self._code_for_outcome(completion, outcome)
        if not code:
            return CompletionAction(kind="none")
        return CompletionAction(
            kind="redirect",
            code=code,
            redirect_url=PROLIFIC_COMPLETION_URL.format(code=code),
            auto_redirect=bool(self.app_config.get('auto_redirect_on_completion', False)),
            auto_redirect_delay=int(self.app_config.get('auto_redirect_delay', 5000)),
            platform_label=self.platform_label(),
        )

    def admin_summary(self):
        study = self._prolific_study()
        if not study:
            return {}
        try:
            return {'study': study.get_basic_study_info()}
        except Exception as e:
            logger.debug("Could not fetch Prolific study info: %s", e)
            return {}

    def _prolific_study(self):
        # Lazy import: flask_server owns the ProlificStudy singleton and
        # importing it at module level would be circular.
        try:
            from potato.flask_server import get_prolific_study
            return get_prolific_study()
        except Exception:
            return None

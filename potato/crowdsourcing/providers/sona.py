"""
SONA Systems provider (university subject pools, credit granting).

SONA substitutes a unique per-participant code for ``%SURVEY_CODE%`` in the
study URL. On completion, Potato grants credit **server-side** via SONA's
WebstudyCredit endpoint (more robust than the client-side redirect: it works
even if the participant closes the tab), falling back to the client-side
``webstudy_credit.aspx`` link if the server-side call fails.

Study URL to configure in SONA:
    https://your-server.com/?sona_code=%SURVEY_CODE%

.. code-block:: yaml

    crowdsourcing:
      provider: sona
      sona:
        hostname: yourdept.sona-systems.com
        experiment_id: 123
        credit_token: 9185d436e5f94b1581b0918162f6d7e8
        id_param: sona_code          # default

Credit grants are idempotent: the grant is recorded in the participant's
user state, so re-rendering the done page never double-credits.
"""

import logging

from potato.crowdsourcing.base import (
    CompletionAction,
    CrowdProvider,
)

logger = logging.getLogger(__name__)

SERVER_CREDIT_URL = (
    "https://{hostname}/services/SonaAPI.svc/WebstudyCredit"
    "?experiment_id={experiment_id}&credit_token={credit_token}&survey_code={survey_code}"
)
CLIENT_CREDIT_URL = (
    "https://{hostname}/webstudy_credit.aspx"
    "?experiment_id={experiment_id}&credit_token={credit_token}&survey_code={survey_code}"
)


class SonaProvider(CrowdProvider):
    name = "sona"
    display_name = "SONA"

    def id_param(self):
        return self.config.get('id_param', 'sona_code')

    def on_completion(self, identity, outcome):
        """Grant credit server-side, exactly once per participant."""
        if not self._is_configured():
            return
        state = self._user_state(identity.worker_id)
        if state is not None and state.crowd_metadata.get('sona_credit_granted'):
            return

        url = self._credit_url(SERVER_CREDIT_URL, identity.worker_id)
        try:
            import requests
            response = requests.get(url, timeout=10)
            # The endpoint answers XML; any 2xx means SONA accepted the grant
            granted = 200 <= response.status_code < 300
        except Exception as e:
            logger.warning("SONA credit grant request failed: %s", e)
            granted = False

        if granted:
            logger.info("Granted SONA credit for survey code %s", identity.worker_id)
            if state is not None:
                state.crowd_metadata['sona_credit_granted'] = True
                self._save_user_state(state)
        else:
            logger.warning(
                "SONA server-side credit grant failed for %s; participant can "
                "use the client-side credit link on the done page", identity.worker_id)

    def completion_action(self, identity, outcome):
        if not self._is_configured():
            return CompletionAction(kind="none")

        state = self._user_state(identity.worker_id) if identity else None
        if state is not None and state.crowd_metadata.get('sona_credit_granted'):
            return CompletionAction(
                kind="none",
                message="Your participation credit has been granted automatically.",
            )
        # Server-side grant failed: offer the client-side credit link
        return CompletionAction(
            kind="redirect",
            code=None,
            redirect_url=self._credit_url(CLIENT_CREDIT_URL, identity.worker_id),
            auto_redirect=bool(self.app_config.get('auto_redirect_on_completion', False)),
            auto_redirect_delay=int(self.app_config.get('auto_redirect_delay', 5000)),
            platform_label=self.platform_label(),
        )

    # --- helpers --------------------------------------------------------------

    def _is_configured(self):
        required = ('hostname', 'experiment_id', 'credit_token')
        missing = [key for key in required if not self.config.get(key)]
        if missing:
            logger.warning("SONA provider missing config keys: %s", ', '.join(missing))
            return False
        return True

    def _credit_url(self, template, survey_code):
        return template.format(
            hostname=self.config['hostname'],
            experiment_id=self.config['experiment_id'],
            credit_token=self.config['credit_token'],
            survey_code=survey_code,
        )

    def _user_state(self, username):
        try:
            from potato.user_state_management import get_user_state_manager
            state = get_user_state_manager().get_user_state(username)
            if state is not None and not hasattr(state, 'crowd_metadata'):
                state.crowd_metadata = {}
            return state
        except Exception:
            return None

    def _save_user_state(self, state):
        try:
            from potato.user_state_management import get_user_state_manager
            get_user_state_manager().save_user_state(state)
        except Exception as e:
            logger.warning("Could not persist SONA credit-grant flag: %s", e)

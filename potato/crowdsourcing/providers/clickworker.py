"""
Clickworker provider (completion code + optional payment postback).

Clickworker's external-survey orders send workers to your URL with a worker
ID/code parameter; completion is verified either with codes you upload to
Clickworker, or — with the marketplace API — by your server POSTing a
completion notification that triggers payment.

The postback contract of Clickworker's marketplace API could not be verified
from public docs (docs.clickworker.com was unreachable during research), so
the postback is EXPERIMENTAL and disabled unless you both configure it and
set ``experimental: true``. The completion-code path needs no API and is safe.

.. code-block:: yaml

    crowdsourcing:
      provider: clickworker
      clickworker:
        id_param: worker_id
        completion:
          code: "CW-DONE-01"
        # Experimental payment postback (verify the contract with Clickworker
        # support before enabling):
        # experimental: true
        # postback_url: "https://api.clickworker.com/.../{worker_id}/complete"
        # postback_method: POST
        # api_key: "..."
"""

import logging

from potato.crowdsourcing.base import CrowdProvider

logger = logging.getLogger(__name__)


class ClickworkerProvider(CrowdProvider):
    name = "clickworker"
    display_name = "Clickworker"

    def id_param(self):
        return self.config.get('id_param', 'worker_id')

    def on_completion(self, identity, outcome):
        """POST the completion postback (exactly once per worker), if enabled."""
        postback_url = self.config.get('postback_url')
        if not postback_url:
            return
        if not self.config.get('experimental', False):
            logger.warning(
                "Clickworker postback_url configured but 'experimental: true' is not "
                "set; skipping postback (the API contract is unverified)")
            return

        state = self._user_state(identity.worker_id)
        if state is not None and state.crowd_metadata.get('clickworker_postback_sent'):
            return

        url = self._fill_template(postback_url, identity,
                                  (self.config.get('completion', {}) or {}).get('code'))
        headers = {}
        if self.config.get('api_key'):
            headers['Authorization'] = f"Bearer {self.config['api_key']}"
        method = str(self.config.get('postback_method', 'POST')).upper()

        try:
            import requests
            response = requests.request(method, url, headers=headers, timeout=10)
            sent = 200 <= response.status_code < 300
        except Exception as e:
            logger.warning("Clickworker completion postback failed: %s", e)
            sent = False

        if sent:
            logger.info("Clickworker completion postback sent for worker %s", identity.worker_id)
            if state is not None:
                state.crowd_metadata['clickworker_postback_sent'] = True
                self._save_user_state(state)

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
            logger.warning("Could not persist Clickworker postback flag: %s", e)

"""
Expert-invite provider: tokenized links for hired experts (Upwork, Fiverr,
Toptal, direct contracts, professional networks).

Expert marketplaces have no participant-ID/completion-code protocol — you
hire someone and message them. The working integration is an **invite link**:
generate a unique token per hired expert, paste the link into the contract
chat, and the expert lands directly in the annotation task under a friendly
name. Unlike ``url_direct`` (where any visitor can self-register), invite
tokens are pre-authorized — the right posture for paid expert work.

Payment stays on the marketplace (hourly/fixed contract). Potato's admin
dashboard timing data (items, time on task) serves as the work report when
verifying invoices.

.. code-block:: yaml

    login:
      type: url_direct
      url_argument: invite

    crowdsourcing:
      provider: expert
      expert:
        id_param: invite
        invites:                      # token -> expert display name
          k3J9mQ2xLp8v: "med-expert-1"
          Zt5wRq7nB4cd: "med-expert-2"
        # or load from a file (YAML mapping or one token per line),
        # kept out of version control:
        # invites_file: configs/expert_invites.yaml
        completion:
          message: "Thank you! Your work has been recorded. You can invoice per your contract."

Invite links to send: ``https://your-server.com/?invite=k3J9mQ2xLp8v``
"""

import logging
import os

from potato.crowdsourcing.base import (
    CompletionAction,
    CrowdProvider,
    ParticipantIdentity,
)

logger = logging.getLogger(__name__)


class ExpertInviteProvider(CrowdProvider):
    name = "expert"
    display_name = "your contracting platform"

    def __init__(self, provider_config, app_config):
        super().__init__(provider_config, app_config)
        self._invites = self._load_invites()

    def id_param(self):
        return self.config.get('id_param', 'invite')

    def extract_identity(self, request_args):
        token = request_args.get(self.id_param())
        if not token:
            return None
        if token not in self._invites:
            logger.warning("Rejected unknown expert invite token: %s...", str(token)[:8])
            return None
        display_name = self._invites[token] or token
        return ParticipantIdentity(
            worker_id=display_name,
            extra={'invite_token': token},
        )

    def completion_action(self, identity, outcome):
        completion = self.config.get('completion', {}) or {}
        code = completion.get('code')
        if code:
            return CompletionAction(kind="code_only", code=code,
                                    platform_label=self.platform_label())
        return CompletionAction(
            kind="none",
            message=completion.get(
                'message',
                "Thank you! Your work has been recorded. Payment is handled "
                "through your contract."),
        )

    def _load_invites(self):
        """Merge inline `invites` mapping and `invites_file` (mapping or token lines)."""
        invites = dict(self.config.get('invites', {}) or {})
        invites_file = self.config.get('invites_file')
        if invites_file:
            try:
                path = invites_file
                if not os.path.isabs(path):
                    path = os.path.join(self.app_config.get('task_dir', '.'), path)
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                loaded = None
                try:
                    import yaml
                    loaded = yaml.safe_load(content)
                except Exception:
                    pass
                if isinstance(loaded, dict):
                    invites.update({str(k): (str(v) if v else None) for k, v in loaded.items()})
                else:
                    for line in content.splitlines():
                        token = line.strip()
                        if token and not token.startswith('#'):
                            invites[token] = None
            except OSError as e:
                logger.error("Could not read expert invites_file: %s", e)
        if not invites:
            logger.warning("Expert provider has no invite tokens configured; "
                           "all arrivals will be rejected")
        return invites

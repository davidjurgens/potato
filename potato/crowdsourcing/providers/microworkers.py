"""
Microworkers provider (VCODE verification).

Microworkers external campaigns send workers to your URL with their ID; the
worker proves completion by pasting back a VCODE that your server generates.
Potato derives a deterministic per-worker VCODE with an HMAC over the worker
and campaign IDs, so the same worker always sees the same code and codes
cannot be guessed without the secret. The same HMAC can be recomputed later
to verify submitted codes (`verify_vcode`).

.. code-block:: yaml

    crowdsourcing:
      provider: microworkers
      microworkers:
        id_param: mw_id              # match the {{MW_ID}} macro in your campaign URL
        capture_params: [campaign_id, slot_id]
        vcode_secret: "keep-this-private"
        vcode_prefix: "mw-"          # optional
        vcode_length: 12             # hex chars after the prefix

Campaign URL template on Microworkers:
    https://your-server.com/?mw_id={{MW_ID}}&campaign_id={{CAMP_ID}}&slot_id={{SLOT_ID}}

Note: Microworkers' REST API v2 (campaigns, bonuses, worker ratings) is not
wired up yet; VCODE verification is self-contained and needs no API access.
Quality on volume crowds is MTurk-like — pair with Potato's attention checks
and gold standards.
"""

import hashlib
import hmac
import logging

from potato.crowdsourcing.base import (
    CompletionAction,
    CrowdProvider,
)

logger = logging.getLogger(__name__)


def compute_vcode(secret, worker_id, campaign_id="", prefix="", length=12):
    digest = hmac.new(
        secret.encode('utf-8'),
        f"{worker_id}:{campaign_id}".encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()
    return f"{prefix}{digest[:int(length)]}"


class MicroworkersProvider(CrowdProvider):
    name = "microworkers"
    display_name = "Microworkers"

    def id_param(self):
        return self.config.get('id_param', 'mw_id')

    def extract_identity(self, request_args):
        identity = super().extract_identity(request_args)
        if identity is None:
            return None
        campaign_id = request_args.get('campaign_id')
        if campaign_id:
            identity.study_id = campaign_id
            identity.extra.setdefault('campaign_id', campaign_id)
        slot_id = request_args.get('slot_id')
        if slot_id:
            identity.session_id = slot_id
            identity.extra.setdefault('slot_id', slot_id)
        return identity

    def completion_action(self, identity, outcome):
        secret = self.config.get('vcode_secret')
        if not secret:
            logger.warning("Microworkers provider needs 'vcode_secret' to generate VCODEs")
            return super().completion_action(identity, outcome)
        vcode = self.vcode_for(identity)
        return CompletionAction(
            kind="generated_code",
            code=vcode,
            platform_label=self.platform_label(),
            message="Paste this VCODE into the Microworkers task window to submit your work.",
        )

    def vcode_for(self, identity):
        return compute_vcode(
            self.config['vcode_secret'],
            identity.worker_id if identity else '',
            campaign_id=(identity.study_id if identity else '') or '',
            prefix=self.config.get('vcode_prefix', ''),
            length=self.config.get('vcode_length', 12),
        )

    def verify_vcode(self, worker_id, campaign_id, submitted_code):
        """Recompute the VCODE for a worker and compare (for offline verification)."""
        expected = compute_vcode(
            self.config['vcode_secret'], worker_id, campaign_id=campaign_id or '',
            prefix=self.config.get('vcode_prefix', ''),
            length=self.config.get('vcode_length', 12))
        return hmac.compare_digest(expected, submitted_code or '')

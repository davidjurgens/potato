"""
Prolific webhook receiver: HMAC verification and event dispatch.

Prolific signs each delivery with HMAC-SHA256 over ``timestamp + body`` using
your subscription secret, base64-encoded, in ``X-Prolific-Request-Signature``
(timestamp in ``X-Prolific-Request-Timestamp``, idempotency key in
``X-Event-Id``). Retries: up to 13 attempts over 48h, so handlers MUST be
idempotent — we keep a bounded seen-event-id set.

Handled events:
- ``submission.status.change``: RETURNED / TIMED-OUT / REJECTED participants
  get their unannotated Potato assignments reclaimed in real time (same path
  as the polling monitor, without the poll delay). AWAITING REVIEW can
  optionally auto-approve via the API.
- ``study.status.change`` / ``study.progress.change`` /
  ``study.has_high_return_rate``: recorded for the admin dashboard.

Endpoint: POST /webhooks/prolific (registered from configure_routes; no
session auth — the HMAC signature is the authentication).

Config:

.. code-block:: yaml

    crowdsourcing:
      prolific:
        webhooks:
          enabled: true
          secret: "whsec_..."       # workspace webhook secret
          auto_approve: false       # approve submissions on AWAITING REVIEW
"""

import base64
import hashlib
import hmac
import logging
from collections import OrderedDict

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

crowd_webhooks_bp = Blueprint('crowd_webhooks', __name__)

# Bounded idempotency cache of processed X-Event-Id values
_seen_event_ids = OrderedDict()
_SEEN_MAX = 10000

# Last-seen study events for the admin dashboard
last_study_events = {}


def _webhook_config():
    from potato.server_utils.config_module import config
    crowd = (config.get('crowdsourcing') or {}).get('prolific') or {}
    return crowd.get('webhooks') or {}, crowd


def verify_prolific_signature(body_bytes, timestamp, signature, secret):
    """Verify HMAC-SHA256(secret, timestamp + body), base64, constant-time."""
    if not (timestamp and signature and secret):
        return False
    digest = hmac.new(
        secret.encode('utf-8'),
        timestamp.encode('utf-8') + body_bytes,
        hashlib.sha256,
    ).digest()
    expected = base64.b64encode(digest).decode('ascii')
    return hmac.compare_digest(expected, signature)


def _mark_seen(event_id):
    """Record an event id; returns True if it was already processed."""
    if not event_id:
        return False
    if event_id in _seen_event_ids:
        return True
    _seen_event_ids[event_id] = True
    while len(_seen_event_ids) > _SEEN_MAX:
        _seen_event_ids.popitem(last=False)
    return False


def clear_seen_events():
    """Reset idempotency state (for tests)."""
    _seen_event_ids.clear()
    last_study_events.clear()


@crowd_webhooks_bp.route('/webhooks/prolific', methods=['POST'])
def prolific_webhook():
    webhook_config, prolific_config = _webhook_config()
    if not webhook_config.get('enabled', False):
        return jsonify({"error": "Prolific webhooks not enabled"}), 404

    secret = webhook_config.get('secret')
    if not secret:
        logger.error("Prolific webhooks enabled but no secret configured")
        return jsonify({"error": "Webhook secret not configured"}), 503

    signature = request.headers.get('X-Prolific-Request-Signature', '')
    timestamp = request.headers.get('X-Prolific-Request-Timestamp', '')
    if not verify_prolific_signature(request.get_data(), timestamp, signature, secret):
        logger.warning("Rejected Prolific webhook with bad signature")
        return jsonify({"error": "Invalid signature"}), 401

    if _mark_seen(request.headers.get('X-Event-Id')):
        return jsonify({"status": "duplicate", "processed": False}), 200

    payload = request.get_json(force=True, silent=True) or {}
    event_type = payload.get('event_type', '')
    try:
        result = _dispatch(event_type, payload, prolific_config, webhook_config)
    except Exception as e:
        # 2xx anyway: Prolific retries failures for 48h and disables the
        # subscription after persistent errors; our handlers are best-effort.
        logger.error("Prolific webhook handler error for %s: %s", event_type, e)
        result = {"handler_error": str(e)}
    return jsonify({"status": "ok", "event_type": event_type, **(result or {})}), 200


def _dispatch(event_type, payload, prolific_config, webhook_config):
    if event_type == 'submission.status.change':
        return _handle_submission_change(payload, prolific_config, webhook_config)
    if event_type in ('study.status.change', 'study.progress.change',
                      'study.has_high_return_rate'):
        last_study_events[event_type] = payload
        if event_type == 'study.has_high_return_rate':
            logger.warning("Prolific reports a high return rate for study %s",
                           payload.get('resource_id'))
        return {"recorded": True}
    logger.info("Unhandled Prolific webhook event type: %s", event_type)
    return {"ignored": True}


def _handle_submission_change(payload, prolific_config, webhook_config):
    status = payload.get('status')
    participant_id = payload.get('participant_id')
    submission_id = payload.get('resource_id')
    result = {"submission_status": status}

    if status in ('RETURNED', 'TIMED-OUT', 'REJECTED') and participant_id:
        reason = {
            'RETURNED': 'prolific_returned',
            'TIMED-OUT': 'prolific_timed_out',
            'REJECTED': 'prolific_rejected',
        }[status]
        from potato.item_state_management import get_item_state_manager
        reclaimed_by_user = get_item_state_manager().reclaim_unannotated_assignments_for_users(
            [participant_id], reason=reason)
        reclaimed_count = sum(len(items) for items in reclaimed_by_user.values())
        logger.info("Webhook: reclaimed %d assignments from %s (%s)",
                    reclaimed_count, participant_id, status)
        result["reclaimed"] = reclaimed_count

    elif status == 'AWAITING REVIEW' and webhook_config.get('auto_approve', False):
        token = prolific_config.get('token')
        if token and submission_id:
            from potato.crowdsourcing.prolific_api import ProlificClient
            ProlificClient(token).approve_submission(submission_id)
            logger.info("Webhook: auto-approved submission %s", submission_id)
            result["auto_approved"] = True
        else:
            logger.warning("auto_approve set but token/submission id missing")

    return result

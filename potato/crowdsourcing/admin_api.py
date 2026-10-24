"""
Admin API for crowd-platform management (Prolific Tier-3 automation).

All endpoints live under /admin/api/crowd/ and require the
MANAGE_CROWDSOURCING permission (the shared admin key and debug mode pass,
per the RBAC contract). Registered as a blueprint from configure_routes().

Endpoints wrap potato.crowdsourcing.prolific_api.ProlificClient — study
lifecycle, submission review, bonuses, paid screen-outs, cost preview,
participant-group qualification sync, and test participants.
"""

import logging
import math
import threading

from flask import Blueprint, jsonify, request

from potato.server_utils.rbac import Permission, require_permission

logger = logging.getLogger(__name__)

crowd_admin_bp = Blueprint('crowd_admin', __name__, url_prefix='/admin/api/crowd')


@crowd_admin_bp.before_request
def _refuse_cross_origin_writes():
    """These routes publish studies and pay people. A page on another site
    must not be able to trigger them with the admin's cookie, so a write whose
    Origin or Referer names another site is refused."""
    from potato.server_utils.origin_check import is_same_origin
    if request.method not in ('GET', 'HEAD', 'OPTIONS') and not is_same_origin():
        return jsonify({'error': 'Cross-origin request rejected'}), 403
    return None


def _config():
    from potato.server_utils.config_module import config
    return config


def _prolific_settings():
    """Resolve Prolific API settings from crowdsourcing.prolific or the legacy
    prolific block (inline or config_file_path)."""
    config = _config()
    settings = dict((config.get('prolific') or {}))
    crowd_prolific = (config.get('crowdsourcing') or {}).get('prolific') or {}
    settings.update(crowd_prolific)

    config_file_path = settings.get('config_file_path')
    if config_file_path and not settings.get('token'):
        try:
            import os
            import yaml
            from potato.server_utils.config_module import get_abs_or_rel_path
            path = get_abs_or_rel_path(config_file_path, config)
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    file_settings = yaml.safe_load(f) or {}
                file_settings.update({k: v for k, v in settings.items()
                                      if k != 'config_file_path' and v is not None})
                settings = file_settings
        except Exception as e:
            logger.warning("Could not load Prolific config file: %s", e)
    return settings


def _client():
    from potato.crowdsourcing.prolific_api import ProlificClient
    settings = _prolific_settings()
    token = settings.get('token')
    if not token:
        return None, (jsonify({"error": "No Prolific API token configured "
                                        "(prolific.token or crowdsourcing.prolific.token)"}), 400)
    return ProlificClient(token), None


def _study_id(explicit=None):
    if explicit:
        return explicit
    return _prolific_settings().get('study_id')


def _api_call(fn):
    """Run a client call, mapping ProlificAPIError to a JSON error response."""
    from potato.crowdsourcing.prolific_api import ProlificAPIError
    try:
        return jsonify(fn()), 200
    except ProlificAPIError as e:
        return jsonify({"error": str(e), "status_code": e.status_code,
                        "payload": e.payload}), 502
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@crowd_admin_bp.route('/status', methods=['GET'])
@require_permission(Permission.MANAGE_CROWDSOURCING)
def crowd_status():
    """Provider + study status overview for the admin dashboard."""
    from potato.crowdsourcing import get_crowd_provider
    provider = get_crowd_provider()
    result = {
        "provider": provider.name if provider else None,
        "platform_label": provider.platform_label() if provider else None,
        "api_configured": bool(_prolific_settings().get('token')),
        "study_id": _study_id(),
    }
    if provider:
        try:
            result["summary"] = provider.admin_summary()
        except Exception as e:
            result["summary_error"] = str(e)
    return jsonify(result), 200


@crowd_admin_bp.route('/study', methods=['GET', 'POST'])
@require_permission(Permission.MANAGE_CROWDSOURCING)
def crowd_study():
    client, err = _client()
    if err:
        return err
    if request.method == 'GET':
        study_id = _study_id(request.args.get('study_id'))
        if not study_id:
            return _api_call(lambda: client.list_studies())
        return _api_call(lambda: client.get_study(study_id))
    spec = request.get_json(force=True, silent=True) or {}
    if not spec:
        return jsonify({"error": "Missing study spec in request body"}), 400
    return _api_call(lambda: client.create_study(spec))


@crowd_admin_bp.route('/study/<study_id>/<action>', methods=['POST'])
@require_permission(Permission.MANAGE_CROWDSOURCING)
def crowd_study_transition(study_id, action):
    client, err = _client()
    if err:
        return err
    transitions = {
        'publish': client.publish_study,
        'pause': client.pause_study,
        'start': client.start_study,
        'stop': client.stop_study,
    }
    if action == 'places':
        body = request.get_json(force=True, silent=True) or {}
        places = body.get('total_available_places')
        if not isinstance(places, int) or places < 1:
            return jsonify({"error": "total_available_places (int >= 1) required"}), 400
        return _api_call(lambda: client.increase_places(study_id, places))
    if action == 'auto_scale':
        return _auto_scale(client, study_id)
    if action == 'test':
        return _api_call(lambda: client.make_test_study(study_id))
    if action not in transitions:
        return jsonify({"error": f"Unknown study action '{action}'"}), 400
    return _api_call(lambda: transitions[action](study_id))


def _remaining_annotation_slots():
    """Annotation slots people still need to fill, across all items.

    Each item's own cap (``required_annotations`` from an overlap sample, or
    the global ``num_annotators_per_item``) minus the PEOPLE who have
    annotated it. The global cap alone under-counted overlap items, and
    counting declared machine raters as filled slots under-recruited by one
    place per tool per item.

    Under the labeling engine the work is its open crowd requests instead:
    it decides which items need a person, and how many.
    """
    from potato.labeling_engine.integration.hooks import get_engine
    engine = get_engine()
    if engine is not None and "crowd" in engine.cfg.humans.pools:
        return len(engine.store.requests(status=["open", "assigned"], pool="crowd"))

    from potato.annotator_origin import is_machine
    from potato.item_state_management import get_item_state_manager
    from potato.user_state_management import get_user_state_manager
    ism = get_item_state_manager()
    cap = getattr(ism, 'max_annotations_per_item', -1)
    if cap is None or cap < 0:
        return None
    try:
        usm = get_user_state_manager()
    except Exception:
        usm = None
    machines = set()
    if usm is not None:
        for uid in usm.get_user_ids():
            st = usm.get_user_state(uid)
            if st is not None and is_machine(st):
                machines.add(uid)
    remaining = 0
    for iid in ism.get_instance_ids():
        item_cap = ism._get_annotator_cap_for_item(iid)
        if item_cap is None or item_cap < 0:
            continue
        people = [u for u in ism.get_annotators_for_item(iid) if u not in machines]
        remaining += max(0, item_cap - len(people))
    return remaining


def _auto_scale(client, study_id):
    """Grow total_available_places to cover remaining annotation slots.

    needed_places = places_taken + ceil(remaining_slots / per-worker quota)
    + headroom. Places never shrink (Prolific constraint).
    """
    body = request.get_json(force=True, silent=True) or {}
    headroom = int(body.get('headroom', 0))
    remaining = _remaining_annotation_slots()
    if remaining is None:
        return jsonify({"error": "Cannot auto-scale: no per-item annotation cap "
                                 "(num_annotators_per_item) configured"}), 400
    per_user = _config().get('max_annotations_per_user', -1)
    if not isinstance(per_user, int) or per_user < 1:
        return jsonify({"error": "Cannot auto-scale: max_annotations_per_user "
                                 "not configured to a positive value"}), 400

    from potato.crowdsourcing.prolific_api import ProlificAPIError
    try:
        study = client.get_study(study_id)
        places_taken = study.get('places_taken', 0) or 0
        needed = places_taken + math.ceil(remaining / per_user) + headroom
        result = client.increase_places(study_id, needed)
        return jsonify({
            "remaining_annotation_slots": remaining,
            "per_user_quota": per_user,
            "places_taken": places_taken,
            "target_places": needed,
            "study": result,
        }), 200
    except ProlificAPIError as e:
        return jsonify({"error": str(e), "status_code": e.status_code}), 502


@crowd_admin_bp.route('/study/<study_id>/submissions', methods=['GET'])
@require_permission(Permission.MANAGE_CROWDSOURCING)
def crowd_submissions(study_id):
    client, err = _client()
    if err:
        return err
    return _api_call(lambda: client.list_submissions(study_id))


@crowd_admin_bp.route('/submissions/<submission_id>/approve', methods=['POST'])
@require_permission(Permission.MANAGE_CROWDSOURCING)
def crowd_approve(submission_id):
    client, err = _client()
    if err:
        return err
    return _api_call(lambda: client.approve_submission(submission_id))


@crowd_admin_bp.route('/submissions/<submission_id>/reject', methods=['POST'])
@require_permission(Permission.MANAGE_CROWDSOURCING)
def crowd_reject(submission_id):
    client, err = _client()
    if err:
        return err
    body = request.get_json(force=True, silent=True) or {}
    return _api_call(lambda: client.reject_submission(
        submission_id, body.get('message', ''), body.get('rejection_category', 'OTHER')))


@crowd_admin_bp.route('/study/<study_id>/bulk_approve', methods=['POST'])
@require_permission(Permission.MANAGE_CROWDSOURCING)
def crowd_bulk_approve(study_id):
    client, err = _client()
    if err:
        return err
    body = request.get_json(force=True, silent=True) or {}
    submission_ids = body.get('submission_ids') or []
    if not submission_ids:
        return jsonify({"error": "submission_ids required"}), 400
    return _api_call(lambda: client.bulk_approve(study_id, submission_ids))


@crowd_admin_bp.route('/study/<study_id>/screen_out', methods=['POST'])
@require_permission(Permission.MANAGE_CROWDSOURCING)
def crowd_screen_out(study_id):
    client, err = _client()
    if err:
        return err
    body = request.get_json(force=True, silent=True) or {}
    submission_ids = body.get('submission_ids') or []
    if not submission_ids:
        return jsonify({"error": "submission_ids required"}), 400
    return _api_call(lambda: client.screen_out_submissions(
        study_id, submission_ids, increase_places=bool(body.get('increase_places', False))))


@crowd_admin_bp.route('/study/<study_id>/bonus', methods=['POST'])
@require_permission(Permission.MANAGE_CROWDSOURCING)
def crowd_bonus(study_id):
    """Set up (and optionally dispatch) bulk bonuses.

    Body: {"bonuses": [["participant_id", 1.50], ...], "pay": true}
    """
    client, err = _client()
    if err:
        return err
    body = request.get_json(force=True, silent=True) or {}
    bonuses = body.get('bonuses') or []
    if not bonuses:
        return jsonify({"error": "bonuses required: [[participant_id, amount], ...]"}), 400

    return _set_up_bonuses(client, study_id, bonuses, bool(body.get('pay')))


def _set_up_bonuses(client, study_id, bonuses, pay, on_paid=None):
    """Validate, set up the bulk bonus, and dispatch it only when ``pay``.

    ``on_paid(bulk_id, result)`` runs after Prolific accepts the payment.
    """
    from potato.crowdsourcing.prolific_api import ProlificAPIError, validate_bonus_rows
    try:
        validate_bonus_rows(bonuses)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    try:
        setup = client.set_up_bonuses(study_id, bonuses)
        result = {"setup": setup}
        if pay:
            bulk_id = setup.get('id')
            if not bulk_id:
                return jsonify({"error": "Bonus setup returned no id; not paying",
                                "setup": setup}), 502
            result["payment"] = client.pay_bonuses(bulk_id)
            if on_paid is not None:
                on_paid(bulk_id, result)
        return jsonify(result), 200
    except ProlificAPIError as e:
        return jsonify({"error": str(e), "status_code": e.status_code}), 502


_PAYMENT_LOCK = threading.Lock()


@crowd_admin_bp.route('/incentive_bonuses', methods=['GET', 'POST'])
@require_permission(Permission.MANAGE_CROWDSOURCING)
def crowd_incentive_bonuses():
    """Bonuses computed from stored answers by potato/incentives.py.

    GET, or POST without ``pay``: a dry run. Nothing is sent to Prolific; the
    response lists each participant's bonus, the Prolific rows and their total.

    POST {"pay": true, "expected_total": "12.40", "study_id": "..."}: sets up
    and pays those rows through the same code as /study/<id>/bonus.
    ``expected_total`` must equal the dry run's ``prolific_total``, so the
    amount paid is the amount that was reviewed; if an answer changed in
    between, the request is refused (409) and nothing is sent.

    Every paid batch is recorded in ``<task_dir>/incentive_payments.json``.
    A batch with the same rows as an earlier one, or one that pays a
    participant an earlier batch already paid, is refused (409) with the
    earlier batch named, unless the body has ``"repeat": true``.

    ``"skip_paid": true`` pays only the participants no recorded batch has
    paid; ``expected_total`` must then equal the dry run's ``unpaid_total``.
    The dry run lists ``already_paid`` and ``unpaid_total`` for this.
    """
    from potato.incentives import report_from_config
    body = (request.get_json(force=True, silent=True) or {}) if request.method == 'POST' else {}
    try:
        report = report_from_config(_config())
        summary = report.summary()
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    from potato.incentives import paid_participants, payments_path, rows_total
    ledger = payments_path(_config())
    try:
        paid = paid_participants(ledger)
    except (OSError, ValueError) as e:
        return jsonify({"error": f"Could not read the payments record {ledger}: {e}"}), 500
    unpaid = [list(r) for r in summary["prolific_rows"] if str(r[0]) not in paid]
    summary["already_paid"] = sorted({str(r[0]) for r in summary["prolific_rows"]} & paid)
    summary["unpaid_total"] = rows_total(unpaid)
    if body.get('pay') is not True:
        return jsonify({"dry_run": True, **summary}), 200

    skip_paid = body.get('skip_paid') is True
    if skip_paid and body.get('repeat') is True:
        return jsonify({"error": "Send skip_paid or repeat, not both"}), 400
    total_key = "unpaid_total" if skip_paid else "prolific_total"
    expected = body.get('expected_total')
    if expected is None or str(expected).strip() != summary[total_key]:
        return jsonify({"error": "expected_total does not match the computed total; run the "
                                 f"dry run again and confirm its {total_key}",
                        total_key: summary[total_key]}), 409
    rows = unpaid if skip_paid else [list(r) for r in summary["prolific_rows"]]
    if not rows:
        message = ("Every participant owed a bonus was already paid" if skip_paid
                   else "No participant is owed a bonus")
        return jsonify({"error": message, **summary}), 400
    study_id = _study_id(body.get('study_id'))
    if not study_id:
        return jsonify({"error": "study_id required (in the body or crowdsourcing.prolific.study_id)"}), 400
    from potato.incentives import earlier_payments, payments_path, record_payment
    ledger = payments_path(_config())
    with _PAYMENT_LOCK:
        try:
            earlier = earlier_payments(ledger, rows)
        except (OSError, ValueError) as e:
            return jsonify({"error": f"Could not read the payments record {ledger}: {e}; "
                                     "not paying"}), 500
        if earlier and body.get('repeat') is not True:
            payees = {p for p, _ in rows}
            return jsonify({
                "error": "These participants were already paid: " + "; ".join(
                    f"bulk bonus {rec.get('bulk_id')} on {rec.get('paid_at')} "
                    f"({', '.join(sorted(payees & {p for p, _ in rec.get('rows') or []}))})"
                    for rec in earlier)
                + ". Send \"repeat\": true to pay them again.",
                "earlier_batches": [{k: rec.get(k) for k in ("bulk_id", "study_id", "paid_at", "total")}
                                    for rec in earlier],
                "prolific_total": summary["prolific_total"]}), 409
        client, err = _client()
        if err:
            return err

        def on_paid(bulk_id, result):
            try:
                result["recorded"] = record_payment(ledger, rows, bulk_id, study_id,
                                                    rows_total(rows), repeat=bool(earlier))
            except OSError as e:
                logger.error("Paid bulk bonus %s but could not record it in %s: %s",
                             bulk_id, ledger, e)
                result["warning"] = (f"Paid, but the payment could not be recorded in {ledger}; "
                                     "a repeat would not be refused")
        return _set_up_bonuses(client, study_id, rows, pay=True, on_paid=on_paid)


@crowd_admin_bp.route('/cost_preview', methods=['GET'])
@require_permission(Permission.MANAGE_CROWDSOURCING)
def crowd_cost_preview():
    client, err = _client()
    if err:
        return err
    try:
        reward = int(request.args.get('reward', ''))
        places = int(request.args.get('places', ''))
    except ValueError:
        return jsonify({"error": "reward (subcurrency int) and places (int) required"}), 400
    return _api_call(lambda: client.calculate_cost(reward, places))


@crowd_admin_bp.route('/qualification_sync', methods=['POST'])
@require_permission(Permission.MANAGE_CROWDSOURCING)
def crowd_qualification_sync():
    """Materialize local annotator sets as a Prolific participant group.

    Body: {"project_id": "...", "group_name": "...",
           "source": "annotated" | "blocked",
           "group_id": "..." (optional: update existing instead of creating)}

    The group can then be used as a study filter for cross-study
    inclusion/exclusion (e.g. don't show study 2 to study-1 annotators).
    """
    client, err = _client()
    if err:
        return err
    body = request.get_json(force=True, silent=True) or {}
    source = body.get('source', 'annotated')

    participant_ids = _collect_participants(source)
    if participant_ids is None:
        return jsonify({"error": f"Unknown source '{source}' (annotated|blocked)"}), 400

    from potato.crowdsourcing.prolific_api import ProlificAPIError
    try:
        group_id = body.get('group_id')
        if not group_id:
            project_id = body.get('project_id')
            group_name = body.get('group_name')
            if not project_id or not group_name:
                return jsonify({"error": "project_id and group_name (or group_id) required"}), 400
            group = client.create_participant_group(
                project_id, group_name,
                description=f"Synced from Potato ({source} users)")
            group_id = group.get('id')
        if participant_ids:
            client.add_to_group(group_id, participant_ids)
        return jsonify({"group_id": group_id, "source": source,
                        "participants_synced": len(participant_ids)}), 200
    except ProlificAPIError as e:
        return jsonify({"error": str(e), "status_code": e.status_code}), 502


def _collect_participants(source):
    """Local user sets that can be synced to a participant group."""
    from potato.user_state_management import get_user_state_manager
    usm = get_user_state_manager()
    if source == 'annotated':
        users = []
        for username in usm.get_user_ids():
            state = usm.get_user_state(username)
            if state and state.get_labeled_instance_ids():
                users.append(username)
        return users
    if source == 'blocked':
        try:
            from potato.quality_control import get_quality_control_manager
            qc = get_quality_control_manager()
            if qc is None:
                return []
            return [u for u in usm.get_user_ids() if qc.is_user_blocked(u)]
        except Exception:
            return []
    return None


@crowd_admin_bp.route('/test_participant', methods=['POST'])
@require_permission(Permission.MANAGE_CROWDSOURCING)
def crowd_test_participant():
    client, err = _client()
    if err:
        return err
    return _api_call(lambda: client.create_test_participant())


@crowd_admin_bp.route('/webhooks/register', methods=['POST'])
@require_permission(Permission.MANAGE_CROWDSOURCING)
def crowd_webhooks_register():
    """Subscribe this server's /webhooks/prolific endpoint to Prolific events.

    Body: {"workspace_id": "...", "public_url": "https://your-server.com",
           "event_types": ["submission.status.change", ...]}  (event_types optional)
    """
    client, err = _client()
    if err:
        return err
    body = request.get_json(force=True, silent=True) or {}
    workspace_id = body.get('workspace_id')
    public_url = (body.get('public_url') or '').rstrip('/')
    if not workspace_id or not public_url:
        return jsonify({"error": "workspace_id and public_url required"}), 400
    if not public_url.startswith('https://'):
        return jsonify({"error": "public_url must be public HTTPS "
                                 "(Prolific will not deliver to plain HTTP)"}), 400
    event_types = body.get('event_types') or [
        'submission.status.change', 'study.status.change',
        'study.progress.change', 'study.has_high_return_rate']
    target_url = f"{public_url}/webhooks/prolific"

    from potato.crowdsourcing.prolific_api import ProlificAPIError
    try:
        existing = client.list_hook_subscriptions(workspace_id)
        existing_pairs = {(s.get('event_type'), s.get('target_url'))
                          for s in (existing.get('results') or [])}
        created = []
        for event_type in event_types:
            if (event_type, target_url) in existing_pairs:
                continue
            created.append(client.create_hook_subscription(
                workspace_id, event_type, target_url))
        return jsonify({
            "target_url": target_url,
            "created": len(created),
            "already_subscribed": len(event_types) - len(created),
            "note": "Ensure crowdsourcing.prolific.webhooks.secret matches the "
                    "workspace webhook secret so deliveries verify.",
        }), 200
    except ProlificAPIError as e:
        return jsonify({"error": str(e), "status_code": e.status_code}), 502

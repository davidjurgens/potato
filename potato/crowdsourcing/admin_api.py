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

from flask import Blueprint, jsonify, request

from potato.server_utils.rbac import Permission, require_permission

logger = logging.getLogger(__name__)

crowd_admin_bp = Blueprint('crowd_admin', __name__, url_prefix='/admin/api/crowd')


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
    """Annotation slots still needed across all items (cap - current annotators)."""
    from potato.item_state_management import get_item_state_manager
    ism = get_item_state_manager()
    cap = getattr(ism, 'max_annotations_per_item', -1)
    if cap is None or cap < 0:
        return None
    remaining = 0
    for iid in ism.get_instance_ids():
        remaining += max(0, cap - len(ism.get_annotators_for_item(iid)))
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

    from potato.crowdsourcing.prolific_api import ProlificAPIError
    try:
        setup = client.set_up_bonuses(study_id, bonuses)
        result = {"setup": setup}
        if body.get('pay'):
            bulk_id = setup.get('id')
            if not bulk_id:
                return jsonify({"error": "Bonus setup returned no id; not paying",
                                "setup": setup}), 502
            result["payment"] = client.pay_bonuses(bulk_id)
        return jsonify(result), 200
    except ProlificAPIError as e:
        return jsonify({"error": str(e), "status_code": e.status_code}), 502


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

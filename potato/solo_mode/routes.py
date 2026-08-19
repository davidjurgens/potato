"""
Solo Mode Routes

Flask routes for Solo Mode human-LLM collaborative annotation.
Provides endpoints for:
- Setup and configuration
- Prompt review and editing
- Edge case labeling
- Main annotation workflow
- Disagreement resolution
- Validation and status
"""

import json
import logging
import traceback
from flask import (
    Blueprint,
    render_template,
    request,
    jsonify,
    redirect,
    url_for,
    session,
)
from functools import wraps
from typing import Any, Dict, Optional

from .manager import get_solo_mode_manager
from .phase_controller import SoloPhase
from potato.item_state_management import get_item_state_manager

logger = logging.getLogger(__name__)

# Create blueprint
solo_mode_bp = Blueprint('solo_mode', __name__, url_prefix='/solo')


def solo_mode_required(f):
    """Decorator to ensure Solo Mode is enabled and initialized."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        manager = get_solo_mode_manager()
        if manager is None:
            return jsonify({'error': 'Solo Mode not enabled'}), 400
        return f(*args, **kwargs)
    return decorated_function


def login_required(f):
    """Decorator to require user authentication."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def api_login_required(f):
    """Like login_required but returns JSON 401 instead of redirecting.

    Intended for /api/* endpoints called by JS, where a 302 to /login is
    useless (fetch follows it and gets HTML, not JSON).
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return jsonify({'error': 'Authentication required'}), 401
        return f(*args, **kwargs)
    return decorated_function


def same_origin_required(f):
    """CSRF protection for state-changing API routes.

    Rejects requests whose Origin or Referer header doesn't match the host.
    Browsers automatically attach these headers; cross-origin forms cannot
    forge them. This is a lightweight CSRF defense without requiring token
    machinery wired into every JS call site.

    Allows requests with no Origin/Referer (server-to-server, curl from
    admins with X-API-Key) since those aren't subject to CSRF.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        origin = request.headers.get('Origin')
        referer = request.headers.get('Referer')
        host = request.host_url.rstrip('/')

        # If neither header is present, this isn't a browser request — allow.
        if not origin and not referer:
            return f(*args, **kwargs)

        if origin and not origin.startswith(host):
            return jsonify({'error': 'Cross-origin request rejected'}), 403
        if referer and not referer.startswith(host):
            return jsonify({'error': 'Cross-origin request rejected'}), 403

        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    """Require a valid admin API key (X-API-Key header) for destructive ops.

    Bypasses the standard session login; used for endpoints that can corrupt
    workflow state (forced phase transitions, refinement approval, etc.).
    Falls back to allowing in debug mode via the existing admin key system.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Lazy import to avoid circular dependencies at module load.
        from potato.server_utils.admin_key import validate_admin_api_key
        from potato.flask_server import config as _config

        api_key = (
            request.headers.get('X-API-Key')
            or session.get('admin_api_key')
        )
        if not validate_admin_api_key(api_key, _config):
            return jsonify({'error': 'Admin authentication required'}), 403
        return f(*args, **kwargs)
    return decorated_function


def _stamp_codebook_provenance(instance_id: str, username: str) -> None:
    """Re-stamp this instance with the current codebook revision now that
    a human has (re-)decided its label — annotate(), disagreement
    resolution, periodic review, and final validation all finalize a
    human label and should call this.

    Without it, the codebook tray's "Review" worklist (instances flagged
    stale because the codebook changed since they were labeled) never
    clears: that worklist is driven entirely by comparing each instance's
    stamped revision against the current one, and revisiting/resolving
    the instance here doesn't move that stamp unless this runs. No-op
    unless the project uses a codebook; never allowed to break the save.
    """
    try:
        from potato.codebook.api import codebook_enabled
        from potato.flask_server import config as _config
        if codebook_enabled(_config):
            from potato.codebook import record_annotation
            record_annotation(
                _config.get('task_dir', '.'),
                _config.get('annotation_task_name') or 'default',
                instance_id, username,
            )
    except Exception:
        logger.debug(
            "Codebook provenance stamp skipped for %s", instance_id,
            exc_info=True,
        )


def _link_codebook_code(instance_id: str, label: Any, username: str) -> None:
    """Link this instance to the codebook code matching its label
    (Solo Mode's scheme labels *are* code names when the scheme has
    codebook: true), replacing any link left over from an earlier label.

    This is what lets a codebook edit's review-flag be scoped to just the
    instances that actually used the affected code (via
    codebook.service._restamp / store.affected_annotation_ids) instead of
    either the whole project or nothing — without it, nothing ever
    populates the annotation<->code link table Solo Mode's labeling never
    touched, and scoping isn't possible at all. No-op unless the project
    uses a codebook, or the label doesn't match a code (free-text
    schemas); never allowed to break the save.
    """
    try:
        from potato.codebook.api import codebook_enabled
        from potato.flask_server import config as _config
        if not codebook_enabled(_config):
            return
        if label is None:
            return

        from potato.codebook.codebook import Codebook
        from potato.codebook import service as codebook_service

        task_dir = _config.get('task_dir', '.')
        project = _config.get('annotation_task_name') or 'default'

        cb = Codebook.load(task_dir, project)
        target = next(
            (d for d in cb.details_in_order() if d.get('name') == str(label)),
            None,
        )
        if target is None:
            return  # label doesn't correspond to a codebook code

        # Drop any link from a *different* code (an earlier label, before
        # a relabel) so an instance always points at exactly the code
        # matching its current label, never a stale extra one.
        for existing in codebook_service.codes_on(task_dir, instance_id):
            if existing.get('code_id') != target['id']:
                codebook_service.remove_code(
                    task_dir, annotation_id=instance_id,
                    code_id=existing['code_id'])

        codebook_service.apply_code(
            task_dir, project=project, annotation_id=instance_id,
            code_id=target['id'], created_by=username,
        )
    except Exception:
        logger.debug(
            "Codebook code-link skipped for %s", instance_id, exc_info=True,
        )


def _current_user_stale_items(username: str) -> list:
    """This user's codebook-review worklist: instances they labeled under
    an older codebook revision, each with the codes added since. []
    (never raises) if the project doesn't use a codebook."""
    try:
        from potato.codebook.api import codebook_enabled
        from potato.flask_server import config as _config
        if not codebook_enabled(_config):
            return []
        from potato.codebook import stale_instances
        return stale_instances(
            _config.get('task_dir', '.'),
            _config.get('annotation_task_name') or 'default',
            username,
        )
    except Exception:
        logger.debug("Codebook staleness check skipped", exc_info=True)
        return []


def _current_user_stale_ids(username: str) -> set:
    return {str(it['instance_id']) for it in _current_user_stale_items(username)}


# =============================================================================
# User Routes
# =============================================================================

@solo_mode_bp.route('/setup', methods=['GET', 'POST'])
@login_required
@solo_mode_required
def setup():
    """
    Solo Mode setup page.

    GET: Display setup form for task description
    POST: Process task description and advance to prompt review
    """
    manager = get_solo_mode_manager()
    current_phase = manager.get_current_phase()

    # Guard: setup is only valid while still in SETUP phase. Once the user has
    # advanced (and possibly started annotating), re-submission would silently
    # overwrite task_description and append a stale prompt version.
    already_configured = current_phase != SoloPhase.SETUP

    if request.method == 'POST':
        if already_configured:
            return render_template(
                'solo/setup.html',
                error=(
                    f'Setup is already complete (current phase: '
                    f'{current_phase.name.lower().replace("_", " ")}). '
                    'Return to status to continue, or visit the prompt editor '
                    'to refine your annotation prompt.'
                ),
                phase=current_phase.name.lower(),
                already_configured=True,
            ), 409

        task_description = request.form.get('task_description', '')

        if task_description:
            manager.set_task_description(task_description)
            # An explicit configured prompt wins over the derived wrapper, so a
            # project can ship the exact base prompt the LLM should see (the
            # codebook block is appended to it at label time).
            configured_prompt = manager.app_config.get('solo_mode', {}).get('initial_prompt')
            prompt_text = configured_prompt or (
                f"Label the following text according to this task: {task_description}"
            )
            manager.create_prompt_version(
                prompt_text,
                created_by='user_setup',
                source_description='Initial prompt from task description'
            )
            manager.advance_to_phase(SoloPhase.PROMPT_REVIEW)
            return redirect(url_for('solo_mode.prompt_editor'))

        return render_template(
            'solo/setup.html',
            error='Please provide a task description',
            phase=current_phase.name.lower(),
            already_configured=False,
            default_task_description=manager.app_config.get('task_description', ''),
        )

    return render_template(
        'solo/setup.html',
        phase=current_phase.name.lower(),
        already_configured=already_configured,
        default_task_description=manager.app_config.get('task_description', ''),
    )


@solo_mode_bp.route('/prompt', methods=['GET', 'POST'])
@login_required
@solo_mode_required
def prompt_editor():
    """
    Prompt review and editing page.

    GET: Display current prompt with editing interface
    POST: Update prompt and optionally advance to edge case synthesis
    """
    manager = get_solo_mode_manager()

    if request.method == 'POST':
        action = request.form.get('action', '')

        if action == 'update':
            new_prompt = request.form.get('prompt', '')
            if new_prompt:
                manager.update_prompt(new_prompt, source='manual_edit')
                return jsonify({'success': True})
            return jsonify({'error': 'Prompt cannot be empty'}), 400

        elif action == 'advance':
            # Move to edge case synthesis. Only a legal move from
            # PROMPT_REVIEW — if this fires from PROMPT_VALIDATION (post
            # edge cases) the transition is illegal and silently no-ops,
            # which is exactly the "generate edge cases" button doing
            # nothing from the verify screen that prompted this comment.
            # The verify screen no longer offers this action (see 'revise'
            # below); kept as-is for the initial prompt-review screen.
            try:
                manager.advance_to_phase(SoloPhase.EDGE_CASE_SYNTHESIS)
            except ValueError:
                pass  # Already past this phase
            return redirect(url_for('solo_mode.edge_cases'))

        elif action == 'revise':
            # From the verify screen: the prompt needs more work, go back
            # and edit it (optionally regenerating edge cases from there).
            try:
                manager.advance_to_phase(SoloPhase.PROMPT_REVIEW)
            except ValueError:
                pass  # Already in or past this phase
            return redirect(url_for('solo_mode.prompt_editor'))

        elif action == 'skip_to_annotation':
            # Skip edge cases (from the initial review), or continue on to
            # annotation (from the verify screen after edge cases) —
            # either way the destination is the same.
            try:
                manager.advance_to_phase(SoloPhase.PARALLEL_ANNOTATION)
            except ValueError:
                pass  # Already in or past this phase
            return redirect(url_for('solo_mode.annotate'))

    # Get prompt history
    prompt_history = []
    for pv in manager.get_all_prompt_versions():
        prompt_history.append({
            'version': pv.version,
            'prompt': pv.prompt_text,
            'source': pv.created_by,
            'timestamp': pv.created_at.isoformat(),
        })

    current_phase = manager.get_current_phase()

    # Verifying the prompt post-edge-cases: the thing that actually
    # changed is the codebook block injected at labeling time, not the
    # base prompt text above (codebook edits never touch current_prompt).
    # Give the template a real instance to preview the assembled prompt
    # against, same mechanism as the annotate screen's "Prompt the LLM
    # sees" panel.
    preview_instance_id = None
    if current_phase == SoloPhase.PROMPT_VALIDATION:
        try:
            ism = get_item_state_manager()
            if ism.instance_id_ordering:
                preview_instance_id = ism.instance_id_ordering[0]
        except Exception:
            pass

    return render_template(
        'solo/prompt_editor.html',
        current_prompt=manager.get_current_prompt_text(),
        prompt_history=prompt_history,
        phase=current_phase.name.lower(),
        preview_instance_id=preview_instance_id,
    )


@solo_mode_bp.route('/edge-cases', methods=['GET', 'POST'])
@login_required
@solo_mode_required
def edge_cases():
    """
    Edge case labeling page.

    GET: Display edge cases for labeling
    POST: Submit label for an edge case
    """
    manager = get_solo_mode_manager()

    if request.method == 'POST':
        case_id = request.form.get('case_id')
        label = request.form.get('label')
        notes = request.form.get('notes', '')

        if case_id and label:
            manager.edge_case_synthesizer.record_label(case_id, label, notes)

            # Check if all edge cases are labeled
            unlabeled = manager.edge_case_synthesizer.get_unlabeled_edge_cases()
            if not unlabeled:
                # Advance to prompt validation. A duplicate/near-simultaneous
                # submit (e.g. a double-click) can race here: both requests
                # see an empty `unlabeled` list before either has advanced
                # the phase, so the second call targets a phase we're
                # already in/past — not a real error, just a lost race.
                try:
                    manager.advance_to_phase(SoloPhase.PROMPT_VALIDATION)
                except ValueError:
                    pass
                return redirect(url_for('solo_mode.prompt_editor'))

            # The form posts normally (no JS/AJAX), so redirect back to render
            # the next unlabeled case instead of dumping raw JSON to the page.
            return redirect(url_for('solo_mode.edge_cases'))

        return redirect(url_for('solo_mode.edge_cases'))

    # Generate edge cases if needed
    if manager.get_current_phase() == SoloPhase.EDGE_CASE_SYNTHESIS:
        unlabeled = manager.edge_case_synthesizer.get_unlabeled_edge_cases()

        if not unlabeled:
            # Synthesize new edge cases
            manager.edge_case_synthesizer.synthesize_edge_cases(
                task_description=manager.get_task_description() or '',
                prompt=manager.get_current_prompt_text(),
                num_cases=5,
            )
            unlabeled = manager.edge_case_synthesizer.get_unlabeled_edge_cases()

        # Advance to labeling phase. Edge case synthesis is a slow LLM
        # call (10-30s) — a second request that arrives while the first
        # is still synthesizing (double-click, refresh, a second tab)
        # will also see phase == EDGE_CASE_SYNTHESIS and reach this same
        # line; whichever one loses the race is trying to transition into
        # a phase we're already in, which is a lost race, not a real
        # error (this is the same defensive pattern annotate() already
        # uses for its own auto-advance calls below).
        try:
            manager.advance_to_phase(SoloPhase.EDGE_CASE_LABELING)
        except ValueError:
            pass

    # Get edge cases to display
    unlabeled = manager.edge_case_synthesizer.get_unlabeled_edge_cases()
    current_case = unlabeled[0] if unlabeled else None

    # Get available labels from config
    labels = manager.get_available_labels()

    return render_template(
        'solo/edge_cases.html',
        current_case=current_case.to_dict() if current_case else None,
        remaining_count=len(unlabeled),
        labels=labels,
        phase=manager.get_current_phase().name.lower(),
    )


@solo_mode_bp.route('/codebook-review')
@login_required
@solo_mode_required
def codebook_review():
    """Mandatory stop for instances labeled under an older codebook
    revision. annotate() redirects here whenever this user has any
    outstanding, and each "Go" link routes back into annotate() for that
    specific instance — which the gate there lets through because it's
    one of the flagged ids, not a request for new work."""
    manager = get_solo_mode_manager()
    user_id = session.get('username', 'anonymous')

    items = _current_user_stale_items(user_id)
    if not items:
        # Cleared since the redirect that sent them here (e.g. two tabs,
        # or they just finished the last one) — nothing left to gate on.
        return redirect(url_for('solo_mode.annotate'))

    return render_template(
        'solo/codebook_review.html',
        items=items,
        phase=manager.get_current_phase().name.lower(),
    )


@solo_mode_bp.route('/annotate', methods=['GET', 'POST'])
@login_required
@solo_mode_required
def annotate():
    """
    Main annotation page for Solo Mode.

    GET: Display next instance for annotation
    POST: Submit annotation for an instance
    """
    manager = get_solo_mode_manager()
    user_id = session.get('username', 'anonymous')

    # Setup guard: annotating needs a prompt, which Setup creates. Without
    # one (Setup not completed, or jumped straight to /solo/annotate) the LLM
    # can't label and the screen is a dead end — send the user to Setup.
    if not manager.get_current_prompt_text():
        return redirect(url_for('solo_mode.setup'))

    # Codebook-review gate: instances this user labeled under an older
    # codebook revision must be re-confirmed before new work is handed
    # out. Previously this was purely advisory (a badge in the tray you
    # could ignore forever); now it's mandatory. Only blocks requests for
    # a *new* instance — a request for one of the flagged instances
    # itself (the "Go" link from the review page/tray) passes through so
    # the review can actually happen.
    if request.method == 'GET':
        requested_id = request.args.get('instance_id')
        stale_ids = _current_user_stale_ids(user_id)
        # True once the user has actually clicked "Go" on a specific
        # flagged item — used below so *that* request isn't itself
        # bounced to a different mandatory queue (disagreements) before
        # it ever reaches the instance the user is trying to resolve.
        reviewing_stale_item = (
            requested_id is not None and requested_id in stale_ids
        )
        if stale_ids and not reviewing_stale_item:
            return redirect(url_for('solo_mode.codebook_review'))

        # Disagreement gate: the live annotate-and-submit path already
        # redirects to /disagreements the moment a disagreement happens
        # in front of the user, but the background labeling thread can
        # also find one on its own — retroactively comparing an LLM
        # prediction against an instance the human labeled earlier, out
        # of order, with no request in flight to redirect anywhere at
        # that moment (see manager.check_and_advance_to_autonomous).
        # Catch that case here so it can't just sit unresolved while the
        # workflow moves on toward Complete. Skipped while
        # reviewing_stale_item: without this, a pending disagreement
        # anywhere in the project silently hijacks every "Go" click from
        # the codebook-review queue and reroutes it to /disagreements
        # instead — the review item never becomes reachable at all, and
        # from the user's side that reads as "Go does nothing".
        if not reviewing_stale_item and manager.get_pending_disagreements():
            return redirect(url_for('solo_mode.disagreements'))

    # Reaching the annotate screen means parallel annotation has begun.
    # Two ways in leave the phase behind PARALLEL_ANNOTATION: coming
    # straight from edge-case validation (PROMPT_VALIDATION), or using
    # edge_cases.html's "Start Annotation" skip link when there were no
    # edge cases to label (leaves the phase at EDGE_CASE_LABELING, since
    # that phase can't jump directly to PARALLEL_ANNOTATION). Either way,
    # walk forward through the legitimate transition chain so the phase
    # stepper reflects where the user actually is instead of getting
    # stuck showing "Edge Cases"/"Prompt" while the annotate screen is
    # what's on screen.
    if manager.get_current_phase() == SoloPhase.EDGE_CASE_LABELING:
        try:
            manager.advance_to_phase(SoloPhase.PROMPT_VALIDATION)
        except ValueError:
            pass
    if manager.get_current_phase() == SoloPhase.PROMPT_VALIDATION:
        try:
            manager.advance_to_phase(SoloPhase.PARALLEL_ANNOTATION)
        except ValueError:
            pass

    if request.method == 'POST':
        instance_id = request.form.get('instance_id')
        annotation = request.form.get('annotation')

        if instance_id and annotation:
            # Record human annotation
            manager.record_human_annotation(instance_id, annotation, user_id)
            _stamp_codebook_provenance(instance_id, user_id)
            _link_codebook_code(instance_id, annotation, user_id)

            # Check for disagreements
            if manager.check_for_disagreement(instance_id, annotation):
                # Redirect to disagreement resolution
                session['disagreement_instance'] = instance_id
                return redirect(url_for('solo_mode.disagreements'))

            # Get next instance
            return redirect(url_for('solo_mode.annotate'))

        return jsonify({'error': 'Missing instance_id or annotation'}), 400

    # Get next instance ID — or a specific one requested via ?instance_id=,
    # which is how the codebook tray's review-worklist "Go" button (and the
    # Back/Next nav below) jump to a particular instance (solo mode has no
    # AJAX instance navigation, so these are full-page links to this route).
    requested_id = request.args.get('instance_id')
    instance_id, nav = _resolve_nav_instance(manager, user_id, requested_id)

    # Get available labels (needed for all render paths)
    labels = manager.get_available_labels()

    if instance_id is None:
        # Check if annotation is complete (atomic check-and-advance).
        # check_autonomous_readiness() is the diagnostic sibling of the
        # older check_and_advance_to_autonomous() — same trigger, but
        # when it's not ready it also says *why* (agreement below
        # threshold, a disagreement still pending, not enough
        # comparisons yet), so "Caught up for now" doesn't leave the
        # user staring at a page with no idea whether anything is
        # actually still blocking Auto Label from starting.
        readiness = manager.check_autonomous_readiness()
        if readiness.get('advanced'):
            return redirect(url_for('solo_mode.status'))

        return render_template(
            'solo/annotate.html',
            instance=None,
            instance_id=None,
            labels=labels,
            message='No more instances available',
            phase=manager.get_current_phase().name.lower(),
            stats=manager.get_annotation_stats(user_id),
            nav=nav,
            relabel=manager.get_relabel_progress(),
            existing_label=None,
            autonomous_blockers=readiness.get('blockers') or [],
        )

    # Get full instance data
    try:
        ism = get_item_state_manager()
        item = ism.get_item(instance_id)
        instance = {
            'id': instance_id,
            'text': item.get_displayed_text(),
            'data': item.get_data(),
        }
    except ValueError as e:
        logger.error(f"ItemStateManager not initialized when fetching instance {instance_id}: {e}")
        return render_template(
            'solo/annotate.html',
            instance=None,
            instance_id=None,
            labels=labels,
            message='Error: Item state manager not available. Please restart the server.',
            phase=manager.get_current_phase().name.lower(),
            nav=nav,
            existing_label=None,
            relabel=manager.get_relabel_progress(),
        )
    except KeyError as e:
        logger.error(f"Instance {instance_id} not found in ItemStateManager: {e}")
        return render_template(
            'solo/annotate.html',
            instance=None,
            instance_id=None,
            labels=labels,
            message=f'Error: Instance {instance_id} not found.',
            phase=manager.get_current_phase().name.lower(),
            nav=nav,
            existing_label=None,
            relabel=manager.get_relabel_progress(),
        )

    # Get LLM prediction if available
    llm_prediction = manager.get_llm_prediction_for_instance(instance_id)

    # Was this instance already labeled by this human? (true when Back/Next
    # nav or the codebook worklist "Go" button lands on a prior instance) —
    # lets the template show "Update label" instead of "Submit" and
    # pre-select the existing choice.
    existing_label = manager.get_human_label_for_instance(instance_id)

    return render_template(
        'solo/annotate.html',
        instance=instance,
        instance_id=instance_id,
        llm_prediction=llm_prediction,
        labels=labels,
        phase=manager.get_current_phase().name.lower(),
        stats=manager.get_annotation_stats(user_id),
        nav=nav,
        existing_label=existing_label,
        relabel=manager.get_relabel_progress(),
    )


# Cap how many instance IDs we keep in the session's Back/Next history so
# the session cookie can't grow unbounded over a long annotation run.
_NAV_HISTORY_CAP = 200


def _resolve_nav_instance(manager, user_id, requested_id):
    """Resolve which instance to show and update the Back/Next history.

    The history is a simple visited-instances stack kept in the session
    (``solo_nav_history`` + ``solo_nav_pos``). Landing on an explicit
    ``?instance_id=`` (Back/Next links, or the codebook worklist's "Go"
    button) moves the cursor to that id without disturbing the rest of the
    stack; a plain "next" request (no id) either resumes moving forward
    through history the annotator already visited, or — once at the
    frontier — asks the instance selector for a brand new instance and
    appends it.

    Returns:
        (instance_id, nav) where nav is a dict of
        {can_back, can_forward, back_id, forward_id} for the template.
    """
    history = session.get('solo_nav_history', [])
    pos = session.get('solo_nav_pos', -1)

    if requested_id:
        instance_id = requested_id
        if 0 <= pos < len(history) and history[pos] == instance_id:
            pass  # already here
        elif instance_id in history:
            pos = history.index(instance_id)
        else:
            history.append(instance_id)
            pos = len(history) - 1
    elif 0 <= pos < len(history) - 1:
        # Previously went Back — a plain "next" resumes toward the
        # frontier instead of picking a brand new instance.
        pos += 1
        instance_id = history[pos]
    else:
        instance_id = manager.get_next_instance_for_human(user_id)
        if instance_id is not None:
            history.append(instance_id)
            pos = len(history) - 1

    if len(history) > _NAV_HISTORY_CAP:
        trim = len(history) - _NAV_HISTORY_CAP
        history = history[trim:]
        pos -= trim

    session['solo_nav_history'] = history
    session['solo_nav_pos'] = pos

    can_back = pos > 0
    can_forward = 0 <= pos < len(history) - 1
    nav = {
        'can_back': can_back,
        'can_forward': can_forward,
        'back_id': history[pos - 1] if can_back else None,
        'forward_id': history[pos + 1] if can_forward else None,
    }
    return instance_id, nav


@solo_mode_bp.route('/llm-suggestion', methods=['GET'])
@login_required
@solo_mode_required
def llm_suggestion():
    """JSON: the LLM's suggested label for ``instance_id``, labeling it on
    demand if the background thread hasn't reached it yet.

    Lets the annotate screen always show the model's take on the instance
    in front of the human, with a visible "thinking" state, rather than
    silently depending on background timing.
    """
    manager = get_solo_mode_manager()
    instance_id = request.args.get('instance_id')
    if not instance_id:
        return jsonify({'error': 'Missing instance_id'}), 400

    suggestion = manager.get_or_create_llm_suggestion(instance_id)
    if suggestion is None:
        return jsonify({'available': False})
    return jsonify({'available': True, **suggestion})


@solo_mode_bp.route('/prompt-preview', methods=['GET'])
@login_required
@solo_mode_required
def prompt_preview():
    """JSON: the exact prompt (and its component sections) the LLM would be
    given for ``instance_id``, plus the current codebook revision.

    Backs the "Prompt the LLM sees" panel on the annotate screen. Read-only
    — it never queries the model, so it's safe to refresh after editing the
    codebook to watch the ``## Codebook`` block change.
    """
    manager = get_solo_mode_manager()
    instance_id = request.args.get('instance_id')
    if not instance_id:
        return jsonify({'error': 'Missing instance_id'}), 400

    preview = manager.get_prompt_preview(instance_id)
    if preview is None:
        return jsonify({'error': 'No preview available for this instance'}), 404
    return jsonify(preview)


@solo_mode_bp.route('/api/distill-options', methods=['GET', 'POST'])
@login_required
@solo_mode_required
def distill_options():
    """GET the effective codebook->prompt distill options (YAML defaults
    merged with any live override); POST a partial override for the
    current session. Backs the Options control next to the "Prompt the
    LLM sees" panel."""
    from .distill_options import effective_options, save_override

    manager = get_solo_mode_manager()

    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        state_dir = manager.config.state_dir
        if not state_dir:
            return jsonify({'error': 'Solo mode has no state_dir configured'}), 400
        merged = save_override(state_dir, data)
        return jsonify({'options': {**effective_options(manager.config), **merged}})

    return jsonify({'options': effective_options(manager.config)})


@solo_mode_bp.route('/api/prompt-feedback', methods=['GET'])
@login_required
@solo_mode_required
def prompt_feedback():
    """LLM-generated targeted feedback on the current prompt (advisory
    only — never edits anything). Backs the "Get Feedback" button next
    to the "Prompt the LLM sees" panel."""
    manager = get_solo_mode_manager()
    instance_id = request.args.get('instance_id')
    result = manager.get_prompt_feedback(instance_id)
    code = 200
    if result.get('reason') and not result.get('feedback'):
        code = 503
    return jsonify(result), code


@solo_mode_bp.route('/disagreements', methods=['GET', 'POST'])
@login_required
@solo_mode_required
def disagreements():
    """
    Disagreement resolution page.

    GET: Display disagreement for resolution
    POST: Submit resolution decision
    """
    manager = get_solo_mode_manager()

    if request.method == 'POST':
        if request.form.get('action') == 'refine_with_edge_cases':
            # Detour: disagreement rate is high enough that resolving one
            # instance at a time isn't fixing the underlying ambiguity —
            # offer to synthesize/label fresh edge cases to sharpen the
            # guidelines instead. Existing edge cases (if any) are shown
            # first; edge_cases() only synthesizes new ones while in
            # EDGE_CASE_SYNTHESIS with none unlabeled.
            try:
                manager.advance_to_phase(
                    SoloPhase.EDGE_CASE_SYNTHESIS,
                    reason='High disagreement rate during annotation',
                )
            except ValueError:
                pass
            return redirect(url_for('solo_mode.edge_cases'))

        disagreement_id = request.form.get('disagreement_id')
        resolution = request.form.get('resolution')  # 'human', 'llm', or custom label
        notes = request.form.get('notes', '')

        if disagreement_id and resolution:
            # disagreement_id is "instance_id:schema_name"
            parts = disagreement_id.split(':', 1)
            instance_id = parts[0]
            schema_name = parts[1] if len(parts) > 1 else 'default'

            # Resolve "human"/"llm" to the actual label value
            actual_label = resolution
            if resolution == 'human':
                # Use the human's label
                disagreement = manager.get_disagreement(instance_id)
                if disagreement:
                    actual_label = disagreement.get('human_label', resolution)
            elif resolution == 'llm':
                # Use the LLM's label
                pred = manager.get_llm_prediction_for_instance(instance_id)
                if pred:
                    actual_label = pred.get('label', resolution)

            manager.resolve_disagreement(
                instance_id, schema_name, actual_label, resolved_by='human',
                notes=notes
            )
            _stamp_codebook_provenance(
                instance_id, session.get('username', 'anonymous'))
            _link_codebook_code(
                instance_id, actual_label, session.get('username', 'anonymous'))

            # Check for more disagreements
            pending = manager.get_pending_disagreements()
            if not pending:
                # Return to annotation
                return redirect(url_for('solo_mode.annotate'))

            return redirect(url_for('solo_mode.disagreements'))

        # The form posts normally (no AJAX). A missing/empty resolution — e.g.
        # the user accepted an LLM label that came back blank — shouldn't dump a
        # raw JSON 400 to the page; send them back to re-pick a resolution.
        return redirect(url_for('solo_mode.disagreements'))

    # Get current disagreement
    instance_id = session.pop('disagreement_instance', None)
    if instance_id:
        disagreement = manager.get_disagreement(instance_id)
    else:
        # Get next pending disagreement
        pending = manager.get_pending_disagreements()
        disagreement = manager.get_disagreement(pending[0]) if pending else None

    if disagreement is None:
        return redirect(url_for('solo_mode.annotate'))

    # Get available labels
    labels = manager.get_available_labels()

    # Suggest an edge-case-labeling detour once there's enough signal that
    # the disagreement isn't a one-off: agreement rate has dipped below
    # threshold across enough compared instances.
    metrics = manager.get_agreement_metrics()
    thresholds = manager.config.thresholds
    suggest_edge_cases = (
        metrics.total_compared >= thresholds.edge_case_suggestion_min_compared
        and metrics.agreement_rate < thresholds.edge_case_suggestion_agreement_rate
    )

    return render_template(
        'solo/disagreement.html',
        disagreement=disagreement,
        labels=labels,
        phase=manager.get_current_phase().name.lower(),
        suggest_edge_cases=suggest_edge_cases,
        agreement_rate=metrics.agreement_rate,
    )


@solo_mode_bp.route('/review', methods=['GET', 'POST'])
@login_required
@solo_mode_required
def review():
    """
    Periodic review of low-confidence LLM labels.

    GET: Display instances for review
    POST: Submit review decision
    """
    manager = get_solo_mode_manager()

    if request.method == 'POST':
        instance_id = request.form.get('instance_id')
        decision = request.form.get('decision')  # 'approve', 'correct'
        corrected_label = request.form.get('corrected_label')

        if instance_id and decision:
            final_label = None
            if decision == 'approve':
                manager.approve_llm_label(instance_id)
                pred = manager.get_llm_prediction_for_instance(instance_id)
                final_label = pred.get('label') if pred else None
            elif decision == 'correct' and corrected_label:
                manager.correct_llm_label(instance_id, corrected_label)
                final_label = corrected_label
            username = session.get('username', 'anonymous')
            _stamp_codebook_provenance(instance_id, username)
            _link_codebook_code(instance_id, final_label, username)

            return redirect(url_for('solo_mode.review'))

        return jsonify({'error': 'Invalid review data'}), 400

    # Get instances for review
    instances = manager.get_instances_for_review()

    if not instances:
        # Reset review counter and return to annotation
        manager.validation_tracker.reset_periodic_review_counter()
        return redirect(url_for('solo_mode.annotate'))

    # Get available labels
    labels = manager.get_available_labels()

    return render_template(
        'solo/review.html',
        instances=instances,
        current_instance=instances[0] if instances else None,
        labels=labels,
        phase=manager.get_current_phase().name.lower(),
    )


@solo_mode_bp.route('/validation', methods=['GET', 'POST'])
@login_required
@solo_mode_required
def validation():
    """
    Final validation of LLM-only labeled instances.

    GET: Display validation interface
    POST: Submit validation result
    """
    manager = get_solo_mode_manager()

    if request.method == 'POST':
        instance_id = request.form.get('instance_id')
        human_label = request.form.get('human_label')
        notes = request.form.get('notes', '')

        if instance_id and human_label:
            manager.record_validation(instance_id, human_label, notes)
            _stamp_codebook_provenance(
                instance_id, session.get('username', 'anonymous'))
            _link_codebook_code(
                instance_id, human_label, session.get('username', 'anonymous'))

            # Check if validation is complete
            progress = manager.get_validation_progress()
            if progress['remaining'] == 0:
                manager.advance_to_phase(SoloPhase.COMPLETED)
                return redirect(url_for('solo_mode.status'))

            return redirect(url_for('solo_mode.validation'))

        return jsonify({'error': 'Missing validation data'}), 400

    # Get validation samples
    samples = manager.get_validation_samples()
    current_sample = samples[0] if samples else None

    # Get progress
    progress = manager.get_validation_progress()

    # Get available labels
    labels = manager.get_available_labels()

    return render_template(
        'solo/validation.html',
        current_sample=current_sample,
        progress=progress,
        labels=labels,
        phase=manager.get_current_phase().name.lower(),
    )


@solo_mode_bp.route('/rules', methods=['GET', 'POST'])
@login_required
@solo_mode_required
def rule_review():
    """
    Edge case rule review page.

    GET: Display aggregated categories for review
    POST: Submit approval/rejection for a category
    """
    manager = get_solo_mode_manager()

    if request.method == 'POST':
        category_id = request.form.get('category_id')
        action = request.form.get('action')  # 'approve' or 'reject'
        notes = request.form.get('notes', '')

        if category_id and action:
            ecr = manager.edge_case_rule_manager
            if action == 'approve':
                ecr.approve_category(category_id, notes)
            elif action == 'reject':
                ecr.reject_category(category_id, notes)

            # Check if more categories pending
            pending = ecr.get_pending_categories()
            if not pending:
                # All reviewed - return to annotation
                current_phase = manager.get_current_phase()
                if current_phase == SoloPhase.RULE_REVIEW:
                    manager.advance_to_phase(
                        SoloPhase.ACTIVE_ANNOTATION,
                        reason="All rule categories reviewed"
                    )
                return redirect(url_for('solo_mode.annotate'))

            return redirect(url_for('solo_mode.rule_review'))

        return jsonify({'error': 'Missing category_id or action'}), 400

    # Get rule data
    ecr = manager.edge_case_rule_manager
    pending = ecr.get_pending_categories()
    approved = ecr.get_approved_categories()
    rejected = ecr.get_rejected_categories()
    stats = ecr.get_stats()

    # Build category details with member rules
    categories_with_rules = []
    for cat in pending:
        member_rules = []
        for rid in cat.member_rule_ids:
            rule = ecr.get_rule(rid)
            if rule:
                member_rules.append(rule.to_dict())
        categories_with_rules.append({
            'category': cat.to_dict(),
            'member_rules': member_rules,
        })

    return render_template(
        'solo/rule_review.html',
        pending_categories=categories_with_rules,
        approved_count=len(approved),
        rejected_count=len(rejected),
        stats=stats,
        phase=manager.get_current_phase().name.lower(),
    )


@solo_mode_bp.route('/status')
@login_required
@solo_mode_required
def status():
    """
    Solo Mode status dashboard.

    Tabbed dashboard with:
    - Overview: annotation progress, agreement, LLM stats
    - Edge Case Rules: inline rule review with approve/reject
    - Rule Clusters: D3.js scatter plot visualization
    """
    manager = get_solo_mode_manager()

    # Lazy import to avoid circular dependencies at module load (same
    # pattern as admin_required below).
    from potato.flask_server import config as _config
    debug_mode = _config.get('debug', False)

    # Edge case rule data
    edge_case_rule_stats = None
    pending_categories = []
    approved_count = 0
    rejected_count = 0

    if manager._edge_case_rule_manager is not None:
        ecr = manager.edge_case_rule_manager
        edge_case_rule_stats = ecr.get_stats()
        approved_count = len(ecr.get_approved_categories())
        rejected_count = len(ecr.get_rejected_categories())

        for cat in ecr.get_pending_categories():
            member_rules = []
            for rid in cat.member_rule_ids:
                rule = ecr.get_rule(rid)
                if rule:
                    member_rules.append(rule.to_dict())
            pending_categories.append({
                'category': cat.to_dict(),
                'member_rules': member_rules,
            })

    return render_template(
        'solo/status.html',
        phase=manager.get_current_phase().name.lower(),
        phase_name=manager.get_current_phase().name,
        annotation_stats=manager.get_annotation_stats(),
        agreement_metrics=manager.get_agreement_metrics(),
        llm_stats=manager.get_llm_labeling_stats(),
        validation_progress=manager.get_validation_progress(),
        edge_case_rule_stats=edge_case_rule_stats,
        pending_categories=pending_categories,
        approved_count=approved_count,
        rejected_count=rejected_count,
        debug_mode=debug_mode,
    )


# =============================================================================
# Admin API Routes
# =============================================================================

@solo_mode_bp.route('/api/status')
@solo_mode_required
def api_status():
    """Get comprehensive Solo Mode status."""
    manager = get_solo_mode_manager()

    return jsonify({
        'phase': manager.get_current_phase().name.lower(),
        'phase_name': manager.get_current_phase().name,
        'annotation_stats': manager.get_annotation_stats(),
        'agreement_metrics': manager.get_agreement_metrics().to_dict(),
        'llm_stats': manager.get_llm_labeling_stats(),
        'validation_progress': manager.get_validation_progress(),
        'should_end_human_annotation': manager.should_end_human_annotation(),
    })


@solo_mode_bp.route('/api/autonomous-labeling/check', methods=['POST'])
@login_required
@solo_mode_required
def api_check_autonomous_labeling():
    """Manually check autonomous-labeling progress and finish the phase
    if it's actually done. Safe to call repeatedly/on a timer — backs the
    dashboard's live indicator while this phase runs, and restarts the
    background thread if it should be running but isn't (e.g. after a
    server restart)."""
    manager = get_solo_mode_manager()
    return jsonify(manager.check_autonomous_labeling_progress())


@solo_mode_bp.route('/api/autonomous-readiness/check', methods=['POST'])
@login_required
@solo_mode_required
def api_check_autonomous_readiness():
    """Check whether Parallel/Active Annotation is ready to hand off to
    Autonomous Labeling, and advance if so — reporting *why* not if it
    isn't (agreement below threshold, not enough comparisons yet, a
    disagreement still pending). Safe to call repeatedly/on a timer.

    check_and_advance_to_autonomous() (what actually gates the
    transition) only ever runs inside annotate()'s GET handler, so once
    there's nothing left to annotate, nothing re-checks it if you're just
    sitting on the dashboard — this is what the dashboard polls instead.
    """
    manager = get_solo_mode_manager()
    return jsonify(manager.check_autonomous_readiness())


@solo_mode_bp.route('/api/relabel-status')
@solo_mode_required
def api_relabel_status():
    """Progress of the current relabel wave — instances that need a fresh
    label because the prompt changed since they were last labeled. Backs
    the spinner/progress bar next to the Agreement stat."""
    manager = get_solo_mode_manager()
    return jsonify(manager.get_relabel_progress())


@solo_mode_bp.route('/api/current-agreement')
@solo_mode_required
def api_current_agreement():
    """Agreement rate scoped to the prompt version currently in effect
    (as opposed to ``agreement_metrics``, which is cumulative across every
    prompt version ever used). Backs the "Refresh Agreement" control."""
    manager = get_solo_mode_manager()
    return jsonify(manager.get_current_version_agreement())


@solo_mode_bp.route('/api/prompts')
@solo_mode_required
def api_prompts():
    """Get prompt version history."""
    manager = get_solo_mode_manager()

    history = []
    for pv in manager.get_all_prompt_versions():
        history.append({
            'version': pv.version,
            'prompt': pv.prompt_text,
            'source': pv.created_by,
            'timestamp': pv.created_at.isoformat(),
            'changes': pv.source_description,
        })

    return jsonify({
        'current_prompt': manager.get_current_prompt_text(),
        'current_version': manager.current_prompt_version,
        'history': history,
    })


@solo_mode_bp.route('/api/predictions')
@solo_mode_required
def api_predictions():
    """Get all LLM predictions."""
    manager = get_solo_mode_manager()

    predictions = manager.get_all_llm_predictions()
    # Serialize predictions to dicts
    serialized = {
        iid: {s: p.to_dict() for s, p in schemas.items()}
        for iid, schemas in predictions.items()
    }

    return jsonify({
        'count': len(predictions),
        'predictions': serialized,
    })


@solo_mode_bp.route('/api/advance-phase', methods=['POST'])
@api_login_required
@same_origin_required
@solo_mode_required
def api_advance_phase():
    """Manually advance to a specific phase.

    force=True bypasses the phase transition graph and can corrupt workflow
    state; it requires admin authentication via X-API-Key.
    """
    manager = get_solo_mode_manager()

    payload = request.get_json(silent=True) or {}
    target_phase = payload.get('phase')
    if not target_phase:
        return jsonify({'error': 'Missing target phase'}), 400

    force = bool(payload.get('force', False))
    if force:
        from potato.server_utils.admin_key import validate_admin_api_key
        from potato.flask_server import config as _config
        api_key = (
            request.headers.get('X-API-Key')
            or session.get('admin_api_key')
        )
        if not validate_admin_api_key(api_key, _config):
            return jsonify({
                'error': 'force=True requires admin authentication',
            }), 403

    try:
        phase = SoloPhase.from_str(target_phase)
    except (ValueError, KeyError):
        return jsonify({'error': f'Unknown phase: {target_phase}'}), 400

    try:
        success = manager.advance_to_phase(phase, force=force)

        if success:
            return jsonify({
                'success': True,
                'new_phase': manager.get_current_phase().name.lower(),
            })
        else:
            return jsonify({
                'error': (
                    f'Invalid phase transition from '
                    f'{manager.get_current_phase().name} to {phase.name}'
                ),
                'current_phase': manager.get_current_phase().name.lower(),
            }), 400

    except ValueError as e:
        return jsonify({
            'error': str(e),
            'current_phase': manager.get_current_phase().name.lower(),
        }), 400


@solo_mode_bp.route('/api/pause-labeling', methods=['POST'])
@api_login_required
@same_origin_required
@solo_mode_required
def api_pause_labeling():
    """Pause background LLM labeling."""
    manager = get_solo_mode_manager()

    if not manager.is_background_labeling_running():
        return jsonify({'error': 'LLM labeling thread not running'}), 400

    manager.pause_background_labeling()
    return jsonify({'success': True, 'paused': True})


@solo_mode_bp.route('/api/resume-labeling', methods=['POST'])
@api_login_required
@same_origin_required
@solo_mode_required
def api_resume_labeling():
    """Resume background LLM labeling."""
    manager = get_solo_mode_manager()

    if not manager.is_background_labeling_running():
        return jsonify({'error': 'LLM labeling thread not running'}), 400

    manager.resume_background_labeling()
    return jsonify({'success': True, 'paused': False})

@solo_mode_bp.route('/api/start-labeling', methods=['POST'])
@api_login_required
@same_origin_required
@solo_mode_required
def api_start_labeling():
    """Start background LLM labeling."""
    manager = get_solo_mode_manager()
    success = manager.start_background_labeling()
    if success:
        return jsonify({'success': True, 'message': 'LLM labeling started'})
    return jsonify({'success': False, 'message': 'Already running or failed to start'})

@solo_mode_bp.route('/api/optimize-prompt', methods=['POST'])
@api_login_required
@same_origin_required
@solo_mode_required
def api_optimize_prompt():
    """Trigger prompt optimization."""
    manager = get_solo_mode_manager()

    # Access the (lazily-constructed) optimizer explicitly. Don't guard with
    # hasattr(): hasattr() swallows any exception raised while building the
    # property and would mislabel a real init failure as "not configured".
    try:
        optimizer = manager.prompt_optimizer if manager is not None else None
    except Exception:
        logger.error("Prompt optimizer failed to initialize: %s", traceback.format_exc())
        return jsonify({'error': 'Prompt optimizer failed to initialize'}), 500

    if optimizer is None:
        return jsonify({'error': 'Prompt optimizer not configured'}), 400

    try:
        result = optimizer.optimize()
        return jsonify({
            'success': True,
            'result': result,
        })
    except Exception as e:
        logger.error("Prompt optimization failed: %s", traceback.format_exc())
        return jsonify({'error': 'An internal error occurred'}), 500


@solo_mode_bp.route('/api/disagreements')
@solo_mode_required
def api_disagreements():
    """Get all disagreements and their status.

    Reads from the manager's authoritative `disagreement_ids` set (populated
    inside record_human_label). Keeps /api/disagreements consistent with the
    Overview card and with get_agreement_metrics().
    """
    manager = get_solo_mode_manager()

    pending = manager.get_pending_disagreements()
    total = len(manager.disagreement_ids)
    resolved = max(total - len(pending), 0)

    return jsonify({
        'total': total,
        'pending': len(pending),
        'resolved': resolved,
        'pending_ids': pending,
    })


@solo_mode_bp.route('/api/edge-cases')
@solo_mode_required
def api_edge_cases():
    """Get edge case status."""
    manager = get_solo_mode_manager()

    if manager.edge_case_synthesizer:
        return jsonify(manager.edge_case_synthesizer.get_status())

    return jsonify({
        'total_edge_cases': 0,
        'labeled': 0,
        'unlabeled': 0,
    })


@solo_mode_bp.route('/api/rules')
@solo_mode_required
def api_rules():
    """Get all edge case rules and their status."""
    manager = get_solo_mode_manager()
    ecr = manager.edge_case_rule_manager

    rules = [r.to_dict() for r in ecr.get_all_rules()]
    return jsonify({
        'rules': rules,
        'stats': ecr.get_stats(),
    })


@solo_mode_bp.route('/api/rules/categories')
@solo_mode_required
def api_rules_categories():
    """Get aggregated edge case rule categories."""
    manager = get_solo_mode_manager()
    ecr = manager.edge_case_rule_manager

    categories = []
    for cat in ecr.get_all_categories():
        member_rules = []
        for rid in cat.member_rule_ids:
            rule = ecr.get_rule(rid)
            if rule:
                member_rules.append(rule.to_dict())
        categories.append({
            'category': cat.to_dict(),
            'member_rules': member_rules,
        })

    return jsonify({'categories': categories})


@solo_mode_bp.route('/api/rules/approve', methods=['POST'])
@api_login_required
@same_origin_required
@solo_mode_required
def api_rules_approve():
    """Approve or reject an edge case rule category."""
    manager = get_solo_mode_manager()
    ecr = manager.edge_case_rule_manager

    data = request.json or {}
    category_id = data.get('category_id')
    action = data.get('action', 'approve')
    notes = data.get('notes', '')

    if not category_id:
        return jsonify({'error': 'Missing category_id'}), 400

    if action == 'approve':
        success = ecr.approve_category(category_id, notes)
    elif action == 'reject':
        success = ecr.reject_category(category_id, notes)
    else:
        return jsonify({'error': f'Invalid action: {action}'}), 400

    return jsonify({'success': success})


@solo_mode_bp.route('/api/rules/apply', methods=['POST'])
@admin_required
@solo_mode_required
def api_rules_apply():
    """Inject approved rules into the annotation prompt."""
    manager = get_solo_mode_manager()

    try:
        result = manager.apply_approved_rules()
        return jsonify(result)
    except Exception as e:
        logger.error("Error applying approved rules: %s", traceback.format_exc())
        return jsonify({'error': 'An internal error occurred'}), 500


@solo_mode_bp.route('/api/rules/cluster', methods=['POST'])
@api_login_required
@same_origin_required
@solo_mode_required
def api_rules_cluster():
    """Manually trigger rule clustering."""
    manager = get_solo_mode_manager()
    manager._trigger_rule_clustering()
    return jsonify({'success': True, 'message': 'Clustering triggered'})


@solo_mode_bp.route('/api/rules/viz-data')
@solo_mode_required
def api_rules_viz_data():
    """Return 2D-projected rule embeddings for D3 scatter plot visualization."""
    manager = get_solo_mode_manager()
    ecr = manager.edge_case_rule_manager
    rules = ecr.get_all_rules()

    if not rules:
        return jsonify({'points': [], 'clusters': []})

    # Project to 2D
    try:
        from .rule_clusterer import RuleClusterer
        clusterer = RuleClusterer(manager.config, manager.solo_config)
        coords = clusterer.project_to_2d(rules)
    except Exception as e:
        logger.warning(f"Rule projection failed: {e}")
        coords = [(0.0, 0.0)] * len(rules)

    # Build points
    points = []
    for i, rule in enumerate(rules):
        x, y = coords[i] if i < len(coords) else (0.0, 0.0)
        cat = ecr.get_category_for_rule(rule.id)
        points.append({
            'x': float(x),
            'y': float(y),
            'rule_id': rule.id,
            'rule_text': rule.rule_text,
            'cluster_id': rule.cluster_id,
            'category_id': cat.id if cat else None,
            'category_summary': cat.summary_rule if cat else None,
            'confidence': rule.source_confidence,
            'instance_id': rule.instance_id,
            'approved': rule.approved,
            'reviewed': rule.reviewed,
        })

    # Build cluster info with centroids
    clusters = []
    for cat in ecr.get_all_categories():
        member_indices = [
            i for i, r in enumerate(rules) if r.cluster_id == cat.id
        ]
        if member_indices:
            cx = sum(coords[i][0] for i in member_indices) / len(member_indices)
            cy = sum(coords[i][1] for i in member_indices) / len(member_indices)
        else:
            cx, cy = 0.0, 0.0

        clusters.append({
            'id': cat.id,
            'summary_rule': cat.summary_rule,
            'centroid_x': float(cx),
            'centroid_y': float(cy),
            'size': len(cat.member_rule_ids),
            'approved': cat.approved,
            'reviewed': cat.reviewed,
        })

    return jsonify({'points': points, 'clusters': clusters})


@solo_mode_bp.route('/api/confusion-analysis')
@solo_mode_required
def api_confusion_analysis():
    """Get full confusion analysis with enriched patterns and heatmap data."""
    manager = get_solo_mode_manager()

    try:
        return jsonify(manager.get_confusion_analysis_full())
    except Exception as e:
        logger.error("Confusion analysis failed: %s", traceback.format_exc())
        return jsonify({'enabled': False, 'error': 'An internal error occurred'}), 500


@solo_mode_bp.route('/api/confusion-analysis/root-cause', methods=['POST'])
@api_login_required
@same_origin_required
@solo_mode_required
def api_confusion_root_cause():
    """Generate root cause analysis for a confusion pattern."""
    manager = get_solo_mode_manager()

    data = request.json or {}
    predicted = data.get('predicted_label')
    actual = data.get('actual_label')

    if not predicted or not actual:
        return jsonify({'error': 'Missing predicted_label or actual_label'}), 400

    # Find the pattern
    analysis = manager.get_confusion_analysis_full()
    if not analysis.get('enabled'):
        return jsonify({'error': 'Confusion analysis not enabled'}), 400

    pattern_data = None
    for p in analysis.get('patterns', []):
        if p['predicted_label'] == predicted and p['actual_label'] == actual:
            pattern_data = p
            break

    if pattern_data is None:
        return jsonify({'error': f'Pattern {predicted}->{actual} not found'}), 404

    # Build a ConfusionPattern from the data
    from .confusion_analyzer import ConfusionPattern, ConfusionExample
    pattern = ConfusionPattern(
        predicted_label=predicted,
        actual_label=actual,
        count=pattern_data['count'],
        percent=pattern_data['percent'],
        examples=[
            ConfusionExample(
                instance_id=e['instance_id'],
                text=e.get('text', ''),
                llm_reasoning=e.get('llm_reasoning'),
                llm_confidence=e.get('llm_confidence'),
            )
            for e in pattern_data.get('examples', [])
        ],
    )

    analyzer = manager.confusion_analyzer
    root_cause = analyzer.generate_root_cause(pattern)

    if root_cause is None:
        return jsonify({
            'error': 'No LLM endpoint available for root cause analysis'
        }), 503

    return jsonify({'success': True, 'root_cause': root_cause})


@solo_mode_bp.route('/api/confusion-analysis/suggest-guideline', methods=['POST'])
@api_login_required
@same_origin_required
@solo_mode_required
def api_confusion_suggest_guideline():
    """Suggest a guideline to address a confusion pattern."""
    manager = get_solo_mode_manager()

    data = request.json or {}
    predicted = data.get('predicted_label')
    actual = data.get('actual_label')

    if not predicted or not actual:
        return jsonify({'error': 'Missing predicted_label or actual_label'}), 400

    # Find the pattern
    analysis = manager.get_confusion_analysis_full()
    if not analysis.get('enabled'):
        return jsonify({'error': 'Confusion analysis not enabled'}), 400

    pattern_data = None
    for p in analysis.get('patterns', []):
        if p['predicted_label'] == predicted and p['actual_label'] == actual:
            pattern_data = p
            break

    if pattern_data is None:
        return jsonify({'error': f'Pattern {predicted}->{actual} not found'}), 404

    from .confusion_analyzer import ConfusionPattern, ConfusionExample
    pattern = ConfusionPattern(
        predicted_label=predicted,
        actual_label=actual,
        count=pattern_data['count'],
        percent=pattern_data['percent'],
        examples=[
            ConfusionExample(
                instance_id=e['instance_id'],
                text=e.get('text', ''),
                llm_reasoning=e.get('llm_reasoning'),
                llm_confidence=e.get('llm_confidence'),
            )
            for e in pattern_data.get('examples', [])
        ],
        root_cause=pattern_data.get('root_cause'),
    )

    analyzer = manager.confusion_analyzer

    # Generate root cause first if not already available
    if not pattern.root_cause:
        pattern.root_cause = analyzer.generate_root_cause(pattern)

    current_prompt = manager.get_current_prompt_text()
    suggestion = analyzer.suggest_guideline(pattern, current_prompt)

    if suggestion is None:
        return jsonify({
            'error': 'No LLM endpoint available for guideline suggestion'
        }), 503

    return jsonify({
        'success': True,
        'suggestion': suggestion,
        'root_cause': pattern.root_cause,
    })


@solo_mode_bp.route('/api/refinement-status')
@solo_mode_required
def api_refinement_status():
    """Get refinement loop status and cycle history."""
    manager = get_solo_mode_manager()
    return jsonify(manager.get_refinement_status())


@solo_mode_bp.route('/api/refinement/trigger', methods=['POST'])
@api_login_required
@same_origin_required
@solo_mode_required
def api_refinement_trigger():
    """Manually trigger a refinement cycle."""
    manager = get_solo_mode_manager()

    if not manager.config.refinement_loop.enabled:
        return jsonify({'error': 'Refinement loop not enabled'}), 400

    try:
        result = manager.trigger_refinement_cycle()
        return jsonify(result)
    except Exception as e:
        logger.error("Refinement trigger failed: %s", traceback.format_exc())
        return jsonify({'error': 'An internal error occurred'}), 500


@solo_mode_bp.route('/api/reannotation-report')
@solo_mode_required
def api_reannotation_report():
    """Get before/after accuracy report for re-annotated instances."""
    manager = get_solo_mode_manager()
    return jsonify(manager.get_reannotation_report())


@solo_mode_bp.route('/api/refinement/reset', methods=['POST'])
@admin_required
@solo_mode_required
def api_refinement_reset():
    """Reset the refinement loop, allowing new cycles."""
    manager = get_solo_mode_manager()

    if not manager.config.refinement_loop.enabled:
        return jsonify({'error': 'Refinement loop not enabled'}), 400

    manager.refinement_loop.reset()
    # Also reset the validated framework's failure counter
    if hasattr(manager, '_refinement_consecutive_failures'):
        manager._refinement_consecutive_failures = 0
    return jsonify({'success': True, 'message': 'Refinement loop reset'})


@solo_mode_bp.route('/api/debug/full_reset', methods=['POST'])
@admin_required
@solo_mode_required
def api_debug_full_reset():
    """Debug-only: wipe the codebook and all Solo Mode tracking state and
    restart the workflow at the SETUP phase, for easier local testing.

    Does not touch underlying annotation output storage. Admin-gated
    (X-API-Key) since this is destructive.
    """
    manager = get_solo_mode_manager()
    try:
        result = manager.full_reset()
    except Exception as e:
        logger.error("Solo Mode full_reset failed: %s", traceback.format_exc())
        return jsonify({'error': 'An internal error occurred'}), 500
    return jsonify({
        'success': True,
        'message': 'Codebook and Solo Mode state reset',
        **result,
    })


@solo_mode_bp.route('/api/refinement/log')
@solo_mode_required
def api_refinement_log():
    """Get the full log of refinement cycles (validated framework only).

    Returns each cycle's result including whether it was applied, dry-run,
    candidates, per-candidate val accuracy, and the baseline score.
    """
    manager = get_solo_mode_manager()
    log = manager.get_refinement_log() if hasattr(manager, 'get_refinement_log') else []
    return jsonify({'log': log, 'count': len(log)})


@solo_mode_bp.route('/api/refinement/pending')
@solo_mode_required
def api_refinement_pending():
    """Get refinement candidates awaiting admin approval.

    Only populated when refinement_loop.require_approval is True. Each entry
    includes the proposed change, validation scores, and rationale so an
    admin can decide whether to apply.
    """
    manager = get_solo_mode_manager()
    pending = manager.get_pending_refinements() if hasattr(manager, 'get_pending_refinements') else []
    return jsonify({'pending': pending, 'count': len(pending)})


@solo_mode_bp.route('/api/refinement/approve', methods=['POST'])
@admin_required
@solo_mode_required
def api_refinement_approve():
    """Apply a pending refinement candidate. Triggers re-annotation on apply."""
    manager = get_solo_mode_manager()
    data = request.get_json(silent=True) or {}
    index = data.get('index')
    if index is None or not isinstance(index, int):
        return jsonify({'error': 'Missing integer index'}), 400

    if not hasattr(manager, 'approve_pending_refinement'):
        return jsonify({'error': 'Validated refinement not available'}), 400

    result = manager.approve_pending_refinement(index)
    status = 200 if result.get('success') else 400
    return jsonify(result), status


@solo_mode_bp.route('/api/refinement/reject', methods=['POST'])
@admin_required
@solo_mode_required
def api_refinement_reject():
    """Reject a pending refinement candidate."""
    manager = get_solo_mode_manager()
    data = request.get_json(silent=True) or {}
    index = data.get('index')
    if index is None or not isinstance(index, int):
        return jsonify({'error': 'Missing integer index'}), 400

    if not hasattr(manager, 'reject_pending_refinement'):
        return jsonify({'error': 'Validated refinement not available'}), 400

    result = manager.reject_pending_refinement(index)
    status = 200 if result.get('success') else 400
    return jsonify(result), status


@solo_mode_bp.route('/api/refinement/strategies')
@solo_mode_required
def api_refinement_strategies():
    """List available refinement strategies and their metadata."""
    try:
        from .refinement import list_strategies
        return jsonify({'strategies': list_strategies()})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@solo_mode_bp.route('/api/labeling-functions')
@solo_mode_required
def api_labeling_functions():
    """Get all labeling functions and their stats."""
    manager = get_solo_mode_manager()

    status = manager.get_labeling_function_status()
    if not status.get('enabled'):
        return jsonify({'enabled': False})

    functions = [
        f.to_dict()
        for f in manager.labeling_function_manager.get_all_functions()
    ]

    return jsonify({
        **status,
        'functions': functions,
    })


@solo_mode_bp.route('/api/labeling-functions/extract', methods=['POST'])
@api_login_required
@same_origin_required
@solo_mode_required
def api_labeling_functions_extract():
    """Trigger labeling function extraction from high-confidence predictions."""
    manager = get_solo_mode_manager()

    if not manager.config.labeling_functions.enabled:
        return jsonify({'error': 'Labeling functions not enabled'}), 400

    try:
        result = manager.extract_labeling_functions()
        return jsonify(result)
    except Exception as e:
        logger.error("Labeling function extraction failed: %s", traceback.format_exc())
        return jsonify({'error': 'An internal error occurred'}), 500


@solo_mode_bp.route('/api/labeling-functions/<function_id>/toggle', methods=['POST'])
@api_login_required
@same_origin_required
@solo_mode_required
def api_labeling_function_toggle(function_id):
    """Toggle a labeling function's enabled state."""
    manager = get_solo_mode_manager()

    if not manager.config.labeling_functions.enabled:
        return jsonify({'error': 'Labeling functions not enabled'}), 400

    new_state = manager.labeling_function_manager.toggle_function(function_id)
    if new_state is None:
        return jsonify({'error': f'Function {function_id} not found'}), 404

    return jsonify({'success': True, 'function_id': function_id, 'enabled': new_state})


@solo_mode_bp.route('/api/labeling-functions/stats')
@solo_mode_required
def api_labeling_functions_stats():
    """Get labeling function statistics."""
    manager = get_solo_mode_manager()
    return jsonify(manager.get_labeling_function_status())


@solo_mode_bp.route('/api/disagreement-explorer')
@solo_mode_required
def api_disagreement_explorer():
    """Get disagreement explorer data with scatter plots and label breakdowns."""
    manager = get_solo_mode_manager()
    label_filter = request.args.get('label')

    try:
        data = manager.get_disagreement_explorer_data(label_filter=label_filter)
        return jsonify(data)
    except Exception as e:
        logger.error("Disagreement explorer failed: %s", traceback.format_exc())
        return jsonify({'error': 'An internal error occurred'}), 500


@solo_mode_bp.route('/api/disagreement-timeline')
@solo_mode_required
def api_disagreement_timeline():
    """Get temporal disagreement trend data."""
    manager = get_solo_mode_manager()
    bucket_size = request.args.get('bucket_size', 10, type=int)
    bucket_size = max(2, min(bucket_size, 100))

    try:
        data = manager.get_disagreement_timeline(bucket_size=bucket_size)
        return jsonify(data)
    except Exception as e:
        logger.error("Disagreement timeline failed: %s", traceback.format_exc())
        return jsonify({'error': 'An internal error occurred'}), 500


@solo_mode_bp.route('/api/export')
@solo_mode_required
def api_export():
    """Export all Solo Mode data."""
    manager = get_solo_mode_manager()

    # Serialize predictions to plain dicts
    predictions = manager.get_all_llm_predictions()
    serialized_predictions = {
        iid: {s: p.to_dict() for s, p in schemas.items()}
        for iid, schemas in predictions.items()
    }

    export_data = {
        'phase': manager.get_current_phase().name.lower(),
        'annotations': manager.get_all_annotations(),
        'llm_predictions': serialized_predictions,
        'disagreements': {
            'total': len(manager.disagreement_ids),
            'pending': len(manager.get_pending_disagreements()),
        },
        'agreement_metrics': manager.get_agreement_metrics().to_dict(),
        'prompt_history': [
            {
                'version': pv.version,
                'prompt': pv.prompt_text,
                'source': pv.created_by,
                'timestamp': pv.created_at.isoformat(),
            }
            for pv in manager.get_all_prompt_versions()
        ],
    }

    return jsonify(export_data)

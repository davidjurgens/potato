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

    if request.method == 'POST':
        task_description = request.form.get('task_description', '')

        if task_description:
            # Store task description and create initial prompt
            manager.set_task_description(task_description)
            manager.create_prompt_version(
                f"Label the following text according to this task: {task_description}",
                created_by='user_setup',
                source_description='Initial prompt from task description'
            )

            # Advance to prompt review phase (ignore if already past setup)
            try:
                manager.advance_to_phase(SoloPhase.PROMPT_REVIEW)
            except ValueError:
                pass  # Already past setup phase

            return redirect(url_for('solo_mode.prompt_editor'))

        return render_template(
            'solo/setup.html',
            error='Please provide a task description',
            phase=manager.get_current_phase().value,
        )

    return render_template(
        'solo/setup.html',
        phase=manager.get_current_phase().value,
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
            # Move to edge case synthesis
            try:
                manager.advance_to_phase(SoloPhase.EDGE_CASE_SYNTHESIS)
            except ValueError:
                pass  # Already past this phase
            return redirect(url_for('solo_mode.edge_cases'))

        elif action == 'skip_to_annotation':
            # Skip edge cases, go directly to parallel annotation
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

    return render_template(
        'solo/prompt_editor.html',
        current_prompt=manager.get_current_prompt_text(),
        prompt_history=prompt_history,
        phase=manager.get_current_phase().value,
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
                # Advance to prompt validation
                manager.advance_to_phase(SoloPhase.PROMPT_VALIDATION)
                return redirect(url_for('solo_mode.prompt_editor'))

            return jsonify({'success': True, 'remaining': len(unlabeled)})

        return jsonify({'error': 'Missing case_id or label'}), 400

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

        # Advance to labeling phase
        manager.advance_to_phase(SoloPhase.EDGE_CASE_LABELING)

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
        phase=manager.get_current_phase().value,
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

    if request.method == 'POST':
        instance_id = request.form.get('instance_id')
        annotation = request.form.get('annotation')

        if instance_id and annotation:
            # Record human annotation
            manager.record_human_annotation(instance_id, annotation, user_id)

            # Check for disagreements
            if manager.check_for_disagreement(instance_id, annotation):
                # Redirect to disagreement resolution
                session['disagreement_instance'] = instance_id
                return redirect(url_for('solo_mode.disagreements'))

            # Get next instance
            return redirect(url_for('solo_mode.annotate'))

        return jsonify({'error': 'Missing instance_id or annotation'}), 400

    # Get next instance ID
    instance_id = manager.get_next_instance_for_human(user_id)

    # Get available labels (needed for all render paths)
    labels = manager.get_available_labels()

    if instance_id is None:
        # Check if annotation is complete (atomic check-and-advance)
        if manager.check_and_advance_to_autonomous():
            return redirect(url_for('solo_mode.status'))

        return render_template(
            'solo/annotate.html',
            instance=None,
            instance_id=None,
            labels=labels,
            message='No more instances available',
            phase=manager.get_current_phase().value,
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
            phase=manager.get_current_phase().value,
        )
    except KeyError as e:
        logger.error(f"Instance {instance_id} not found in ItemStateManager: {e}")
        return render_template(
            'solo/annotate.html',
            instance=None,
            instance_id=None,
            labels=labels,
            message=f'Error: Instance {instance_id} not found.',
            phase=manager.get_current_phase().value,
        )

    # Get LLM prediction if available
    llm_prediction = manager.get_llm_prediction_for_instance(instance_id)

    return render_template(
        'solo/annotate.html',
        instance=instance,
        instance_id=instance_id,
        llm_prediction=llm_prediction,
        labels=labels,
        phase=manager.get_current_phase().value,
        stats=manager.get_annotation_stats(),
    )


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
        disagreement_id = request.form.get('disagreement_id')
        resolution = request.form.get('resolution')  # 'human', 'llm', or custom label
        notes = request.form.get('notes', '')

        if disagreement_id and resolution:
            # disagreement_id is "instance_id:schema_name"
            parts = disagreement_id.split(':', 1)
            instance_id = parts[0]
            schema_name = parts[1] if len(parts) > 1 else 'default'
            manager.resolve_disagreement(instance_id, schema_name, resolution, 'human')

            # Check for more disagreements
            pending = manager.get_pending_disagreements()
            if not pending:
                # Return to annotation
                return redirect(url_for('solo_mode.annotate'))

            return redirect(url_for('solo_mode.disagreements'))

        return jsonify({'error': 'Missing disagreement_id or resolution'}), 400

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

    return render_template(
        'solo/disagreement.html',
        disagreement=disagreement,
        labels=labels,
        phase=manager.get_current_phase().value,
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
            if decision == 'approve':
                manager.approve_llm_label(instance_id)
            elif decision == 'correct' and corrected_label:
                manager.correct_llm_label(instance_id, corrected_label)

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
        phase=manager.get_current_phase().value,
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
        phase=manager.get_current_phase().value,
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
        phase=manager.get_current_phase().value,
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
        phase=manager.get_current_phase().value,
        phase_name=manager.get_current_phase().name,
        annotation_stats=manager.get_annotation_stats(),
        agreement_metrics=manager.get_agreement_metrics(),
        llm_stats=manager.get_llm_labeling_stats(),
        validation_progress=manager.get_validation_progress(),
        edge_case_rule_stats=edge_case_rule_stats,
        pending_categories=pending_categories,
        approved_count=approved_count,
        rejected_count=rejected_count,
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
        'phase': manager.get_current_phase().value,
        'phase_name': manager.get_current_phase().name,
        'annotation_stats': manager.get_annotation_stats(),
        'agreement_metrics': manager.get_agreement_metrics().to_dict(),
        'llm_stats': manager.get_llm_labeling_stats(),
        'validation_progress': manager.get_validation_progress(),
        'should_end_human_annotation': manager.should_end_human_annotation(),
    })


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
@solo_mode_required
def api_advance_phase():
    """Manually advance to a specific phase."""
    manager = get_solo_mode_manager()

    target_phase = request.json.get('phase')
    if not target_phase:
        return jsonify({'error': 'Missing target phase'}), 400

    force = request.json.get('force', False)

    try:
        phase = SoloPhase.from_str(target_phase)
    except (ValueError, KeyError):
        return jsonify({'error': f'Unknown phase: {target_phase}'}), 400

    try:
        success = manager.advance_to_phase(phase, force=force)

        if success:
            return jsonify({
                'success': True,
                'new_phase': manager.get_current_phase().value,
            })
        else:
            return jsonify({
                'error': (
                    f'Invalid phase transition from '
                    f'{manager.get_current_phase().name} to {phase.name}'
                ),
                'current_phase': manager.get_current_phase().value,
            }), 400

    except ValueError as e:
        return jsonify({
            'error': str(e),
            'current_phase': manager.get_current_phase().value,
        }), 400


@solo_mode_bp.route('/api/pause-labeling', methods=['POST'])
@solo_mode_required
def api_pause_labeling():
    """Pause background LLM labeling."""
    manager = get_solo_mode_manager()

    if manager.llm_labeling_thread:
        manager.llm_labeling_thread.pause()
        return jsonify({'success': True, 'paused': True})

    return jsonify({'error': 'LLM labeling thread not running'}), 400


@solo_mode_bp.route('/api/resume-labeling', methods=['POST'])
@solo_mode_required
def api_resume_labeling():
    """Resume background LLM labeling."""
    manager = get_solo_mode_manager()

    if manager.llm_labeling_thread:
        manager.llm_labeling_thread.resume()
        return jsonify({'success': True, 'paused': False})

    return jsonify({'error': 'LLM labeling thread not running'}), 400

@solo_mode_bp.route('/api/start-labeling', methods=['POST'])
@solo_mode_required
def api_start_labeling():
    """Start background LLM labeling."""
    manager = get_solo_mode_manager()
    success = manager.start_background_labeling()
    if success:
        return jsonify({'success': True, 'message': 'LLM labeling started'})
    return jsonify({'success': False, 'message': 'Already running or failed to start'})

@solo_mode_bp.route('/api/optimize-prompt', methods=['POST'])
@solo_mode_required
def api_optimize_prompt():
    """Trigger prompt optimization."""
    manager = get_solo_mode_manager()

    if not hasattr(manager, 'prompt_optimizer') or manager.prompt_optimizer is None:
        return jsonify({'error': 'Prompt optimizer not configured'}), 400

    try:
        result = manager.prompt_optimizer.optimize()
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
    """Get all disagreements and their status."""
    manager = get_solo_mode_manager()

    if manager.disagreement_resolver:
        stats = manager.disagreement_resolver.get_stats()
        pending = manager.disagreement_resolver.get_pending_disagreements()
        return jsonify({
            'pending': len(pending),
            'resolved': stats.get('resolved', 0),
            'stats': stats,
        })

    return jsonify({'pending': 0, 'resolved': 0, 'stats': {}})


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


@solo_mode_bp.route('/api/refinement/reset', methods=['POST'])
@solo_mode_required
def api_refinement_reset():
    """Reset the refinement loop, allowing new cycles."""
    manager = get_solo_mode_manager()

    if not manager.config.refinement_loop.enabled:
        return jsonify({'error': 'Refinement loop not enabled'}), 400

    manager.refinement_loop.reset()
    return jsonify({'success': True, 'message': 'Refinement loop reset'})


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
        'phase': manager.get_current_phase().value,
        'annotations': manager.get_all_annotations(),
        'llm_predictions': serialized_predictions,
        'disagreements': (
            manager.disagreement_resolver.get_stats()
            if manager._disagreement_resolver is not None else {}
        ),
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

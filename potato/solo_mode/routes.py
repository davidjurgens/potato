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

            # Advance to prompt review phase
            manager.advance_to_phase(SoloPhase.PROMPT_REVIEW)

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
            manager.advance_to_phase(SoloPhase.EDGE_CASE_SYNTHESIS)
            return redirect(url_for('solo_mode.edge_cases'))

        elif action == 'skip_to_annotation':
            # Skip edge cases, go directly to parallel annotation
            manager.advance_to_phase(SoloPhase.PARALLEL_ANNOTATION)
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

    if instance_id is None:
        # Check if annotation is complete (atomic check-and-advance)
        if manager.check_and_advance_to_autonomous():
            return redirect(url_for('solo_mode.status'))

        return render_template(
            'solo/annotate.html',
            instance=None,
            instance_id=None,
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
            message='Error: Item state manager not available. Please restart the server.',
            phase=manager.get_current_phase().value,
        )
    except KeyError as e:
        logger.error(f"Instance {instance_id} not found in ItemStateManager: {e}")
        return render_template(
            'solo/annotate.html',
            instance=None,
            instance_id=None,
            message=f'Error: Instance {instance_id} not found.',
            phase=manager.get_current_phase().value,
        )

    # Get LLM prediction if available
    llm_prediction = manager.get_llm_prediction_for_instance(instance_id)

    # Get available labels
    labels = manager.get_available_labels()

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
            manager.resolve_disagreement(disagreement_id, resolution, notes)

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
        disagreement = pending[0] if pending else None

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


@solo_mode_bp.route('/status')
@login_required
@solo_mode_required
def status():
    """
    Solo Mode status dashboard.

    Displays:
    - Current phase
    - Annotation progress
    - Agreement metrics
    - LLM labeling stats
    """
    manager = get_solo_mode_manager()

    return render_template(
        'solo/status.html',
        phase=manager.get_current_phase().value,
        phase_name=manager.get_current_phase().name,
        annotation_stats=manager.get_annotation_stats(),
        agreement_metrics=manager.get_agreement_metrics(),
        llm_stats=manager.get_llm_labeling_stats(),
        validation_progress=manager.get_validation_progress(),
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

    try:
        phase = SoloPhase(target_phase)
        success = manager.advance_to_phase(phase)

        if success:
            return jsonify({
                'success': True,
                'new_phase': manager.get_current_phase().value,
            })
        else:
            return jsonify({
                'error': 'Invalid phase transition',
                'current_phase': manager.get_current_phase().value,
            }), 400

    except ValueError:
        return jsonify({'error': f'Unknown phase: {target_phase}'}), 400


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
        logger.error(f"Prompt optimization failed: {e}")
        return jsonify({'error': str(e)}), 500


@solo_mode_bp.route('/api/disagreements')
@solo_mode_required
def api_disagreements():
    """Get all disagreements and their status."""
    manager = get_solo_mode_manager()

    if manager.disagreement_resolver:
        return jsonify({
            'pending': len(manager.disagreement_resolver.get_pending_disagreements()),
            'resolved': len(manager.disagreement_resolver.get_resolved_disagreements()),
            'all': manager.disagreement_resolver.get_all_disagreements(),
        })

    return jsonify({'pending': 0, 'resolved': 0, 'all': []})


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


@solo_mode_bp.route('/api/confusion-analysis')
@solo_mode_required
def api_confusion_analysis():
    """Get confusion pattern analysis."""
    manager = get_solo_mode_manager()

    if manager.validation_tracker:
        return jsonify(manager.validation_tracker.get_confusion_analysis())

    return jsonify({'patterns': [], 'most_confused': None})


@solo_mode_bp.route('/api/export')
@solo_mode_required
def api_export():
    """Export all Solo Mode data."""
    manager = get_solo_mode_manager()

    export_data = {
        'phase': manager.get_current_phase().value,
        'annotations': manager.get_all_annotations(),
        'llm_predictions': manager.get_all_llm_predictions(),
        'disagreements': (
            manager.disagreement_resolver.get_all_disagreements()
            if manager.disagreement_resolver else []
        ),
        'agreement_metrics': manager.get_agreement_metrics(),
        'prompt_history': [],
    }

    if manager.prompt_manager:
        for rev in manager.prompt_manager.revision_history:
            export_data['prompt_history'].append({
                'version': rev.version,
                'prompt': rev.prompt_text,
                'source': rev.source,
                'timestamp': rev.timestamp.isoformat(),
            })

    return jsonify(export_data)

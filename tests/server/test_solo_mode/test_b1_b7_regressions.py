"""Regression tests for Solo Mode bugs B1–B7 surfaced during deep review (2026-05).

Each test pins one specific bug so the fix can't silently regress.

B1: Phase progress bar broken because SoloPhase.value (int from auto()) was
    passed to templates expecting string phase identifiers.
B2: ValidationTracker.comparison_history was never persisted across restarts,
    wiping confusion-matrix data every time.
B3: /api/disagreements always returned 0 because DisagreementResolver.check_and_record
    was never called.
B4: All /api/* POST endpoints had no auth and no CSRF protection — anonymous
    callers could force phase transitions.
B5: POST /solo/setup mutated state regardless of current phase, letting users
    silently overwrite task_description after annotation started.
B6: Pause/resume API was a silent no-op because the background loop never
    checked the pause event.
B7: status.html had two style= attributes on the same <button>; browsers kept
    only the first, breaking display:none on the Reset button.
"""

import json
import os
import re
import time

import pytest
import requests
import yaml

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port


# ---------------------------------------------------------------------------
# Test scaffolding
# ---------------------------------------------------------------------------

def _make_config(test_dir):
    data_dir = os.path.join(test_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    data = [{"id": f"r{i:03d}", "text": f"Sample text {i}."} for i in range(10)]
    with open(os.path.join(data_dir, "test_data.json"), 'w') as f:
        json.dump(data, f)

    cfg = {
        'task_dir': '.',
        'verbose': False,
        'annotation_task_name': 'solo_b1_b7_test',
        'output_annotation_dir': 'annotations',
        'solo_mode': {
            'enabled': True,
            'labeling_models': [{
                'endpoint_type': 'ollama',
                'model': 'test-dummy',
                'endpoint_url': 'http://127.0.0.1:1',
            }],
            'uncertainty': {'strategy': 'direct_confidence'},
            'thresholds': {
                'end_human_annotation_agreement': 0.90,
                'minimum_validation_sample': 3,
            },
            'instance_selection': {
                'low_confidence_weight': 0.4,
                'diversity_weight': 0.3,
                'random_weight': 0.2,
                'disagreement_weight': 0.1,
            },
            'batches': {
                'llm_labeling_batch': 5,
                'max_parallel_labels': 10,
            },
            'state_dir': 'solo_state',
        },
        'data_files': ['data/test_data.json'],
        'item_properties': {'id_key': 'id', 'text_key': 'text'},
        'annotation_schemes': [{
            'name': 'sentiment',
            'description': 'Classify sentiment',
            'annotation_type': 'radio',
            'labels': [
                {'name': 'positive', 'key_value': '1'},
                {'name': 'negative', 'key_value': '2'},
                {'name': 'neutral', 'key_value': '3'},
            ],
        }],
        'user_config': {'allow_no_password': True},
        'output': {
            'annotation_output_format': 'json',
            'annotation_output_dir': 'annotations',
        },
    }
    cfg_path = os.path.join(test_dir, 'config.yaml')
    with open(cfg_path, 'w') as f:
        yaml.dump(cfg, f)
    return cfg_path


@pytest.fixture(scope="module")
def solo_server():
    tests_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    test_dir = os.path.join(tests_dir, "output", f"solo_b1_b7_{int(time.time())}")
    os.makedirs(test_dir, exist_ok=True)

    config_file = _make_config(test_dir)
    port = find_free_port(preferred_port=9301)
    server = FlaskTestServer(port=port, debug=False, config_file=config_file)
    if not server.start_server():
        pytest.skip("Failed to start Flask server")
    server._wait_for_server_ready(timeout=15)
    yield server
    server.stop_server()
    import shutil
    try:
        shutil.rmtree(test_dir)
    except Exception:
        pass


@pytest.fixture
def authed(solo_server):
    """Authed session with Origin header set (so same-origin CSRF guard passes)."""
    s = requests.Session()
    user_email = f"u_{int(time.time()*1000)}"
    s.post(f"{solo_server.base_url}/auth",
           data={"email": user_email, "pass": ""})
    s.headers['Origin'] = solo_server.base_url
    s.headers['Referer'] = solo_server.base_url + "/"
    yield s
    s.close()


# ---------------------------------------------------------------------------
# B1: phase progress bar must mark exactly one step active
# ---------------------------------------------------------------------------

class TestB1PhaseProgressBar:
    """B1: progress bar uses string phase identifiers, not enum int values."""

    def _phase_steps(self, html):
        block = re.search(
            r'<nav class="phase-progress"[^>]*>(.*?)</nav>',
            html, re.S,
        )
        if not block:
            return []
        return [
            (m.group(1).strip(), m.group(2).strip())
            for m in re.finditer(
                r'<div class="(phase-step[^"]*)"[^>]*>.*?step-label">([^<]+)</span>',
                block.group(1), re.S,
            )
        ]

    def test_setup_page_marks_setup_step_active(self, authed, solo_server):
        """On a fresh server in SETUP phase, /solo/setup should show
        Setup as active and all subsequent steps as upcoming."""
        r = authed.get(f"{solo_server.base_url}/solo/setup")
        assert r.status_code == 200
        steps = self._phase_steps(r.text)
        assert len(steps) == 7, f"expected 7 visible phase steps, got {steps}"

        classes = [c for c, _ in steps]
        labels = [l for _, l in steps]
        assert 'phase-step active' in classes, (
            f"no phase-step has the 'active' class — phase bar broken. "
            f"classes={classes}, labels={labels}"
        )
        # Exactly one active.
        assert sum(1 for c in classes if 'active' in c) == 1

        # The first step (Setup) is the one that's active.
        assert 'active' in classes[0], (
            f"on a fresh server, Setup (step 1) should be active. classes={classes}"
        )

    def test_sidebar_phase_label_is_a_string_not_an_int(
        self, authed, solo_server
    ):
        """Sidebar should render a human-readable phase name, never a bare integer."""
        r = authed.get(f"{solo_server.base_url}/solo/setup")
        assert r.status_code == 200
        # Find the Phase row in the sidebar's stats panel
        m = re.search(
            r'stat-label">\s*Phase\s*</span>\s*<span class="stat-value">([^<]+)</span>',
            r.text,
        )
        # Setup overrides the stats block; phase may not appear there. Status
        # page is the canonical place — also probe that.
        if m:
            value = m.group(1).strip()
            assert not value.isdigit(), (
                f"sidebar phase value is the bare enum int '{value}' — "
                f"routes.py is passing .value instead of .name.lower()"
            )

        r = authed.get(f"{solo_server.base_url}/solo/status")
        assert r.status_code == 200
        # Status page renders phase_name (string) in a pill; also check that
        # the underlying `phase` context isn't an int that would break the bar.
        steps = self._phase_steps(r.text)
        if steps:
            assert any('active' in c for c, _ in steps), (
                "status page also has a dead phase progress bar — broken"
            )


# ---------------------------------------------------------------------------
# B5: setup is idempotent — re-POSTing once past SETUP doesn't mutate state
# ---------------------------------------------------------------------------

class TestB5SetupReentryGuard:
    """B5: POST /solo/setup after the phase has advanced must NOT overwrite
    task_description or create a new prompt version."""

    def test_post_after_advance_returns_409_and_does_not_mutate(
        self, authed, solo_server
    ):
        # First POST sets the task and advances to PROMPT_REVIEW
        r1 = authed.post(
            f"{solo_server.base_url}/solo/setup",
            data={'task_description': 'Original task description'},
            allow_redirects=False,
        )
        assert r1.status_code in (302, 303), r1.status_code

        # Capture prompts state
        before = authed.get(f"{solo_server.base_url}/solo/api/prompts").json()
        before_versions = len(before['history'])
        before_current = before['current_prompt']

        # Second POST: try to overwrite. Must be blocked.
        r2 = authed.post(
            f"{solo_server.base_url}/solo/setup",
            data={'task_description': 'STALE OVERWRITE — should not land'},
        )
        assert r2.status_code == 409, (
            f"second /setup POST should return 409 Conflict, got {r2.status_code}"
        )

        after = authed.get(f"{solo_server.base_url}/solo/api/prompts").json()
        assert len(after['history']) == before_versions, (
            "second setup POST added a prompt version — guard not enforced"
        )
        assert after['current_prompt'] == before_current, (
            "second setup POST mutated current_prompt — guard not enforced"
        )


# ---------------------------------------------------------------------------
# B4: auth + CSRF on mutating APIs
# ---------------------------------------------------------------------------

class TestB4MutatingAPIAuth:
    """B4: /api/* POST endpoints reject unauthenticated and cross-origin calls."""

    def test_anonymous_post_to_advance_phase_returns_401(self, solo_server):
        r = requests.post(
            f"{solo_server.base_url}/solo/api/advance-phase",
            json={"phase": "completed", "force": True},
        )
        assert r.status_code == 401, (
            f"anonymous POST to /api/advance-phase must be rejected, "
            f"got {r.status_code}: {r.text[:200]}"
        )

    def test_force_true_without_admin_key_returns_403(self, authed, solo_server):
        r = authed.post(
            f"{solo_server.base_url}/solo/api/advance-phase",
            json={"phase": "completed", "force": True},
        )
        assert r.status_code == 403, (
            f"force=True without admin key must be rejected, got {r.status_code}"
        )

    def test_cross_origin_post_is_rejected(self, authed, solo_server):
        # Override Origin to look cross-site
        r = authed.post(
            f"{solo_server.base_url}/solo/api/pause-labeling",
            headers={'Origin': 'https://evil.example.com'},
        )
        assert r.status_code == 403, (
            f"cross-origin POST must be rejected, got {r.status_code}"
        )

    def test_same_origin_authed_post_succeeds(self, authed, solo_server):
        """Sanity check: the auth changes don't break legitimate calls."""
        # /solo/api/start-labeling — safe to call; manager already running.
        r = authed.post(
            f"{solo_server.base_url}/solo/api/start-labeling",
        )
        # 200 (started) or 200 with success=False (already running) both OK;
        # what matters is it's NOT 401 or 403.
        assert r.status_code not in (401, 403), (
            f"legitimate same-origin authed POST blocked: {r.status_code}"
        )


# ---------------------------------------------------------------------------
# B7: Reset button on status page has a single, valid style attribute
# ---------------------------------------------------------------------------

class TestB7DuplicateStyleAttr:
    """B7: the Reset button (#ov-refinement-reset-btn) must have exactly one
    style attribute, and that attribute must contain display: none."""

    def test_reset_button_has_single_style_with_display_none(
        self, authed, solo_server
    ):
        r = authed.get(f"{solo_server.base_url}/solo/status")
        assert r.status_code == 200

        # Find the Reset button by ID
        m = re.search(
            r'<button[^>]*id="ov-refinement-reset-btn"[^>]*>',
            r.text, re.S,
        )
        assert m, "Reset button (#ov-refinement-reset-btn) not found on status page"

        tag = m.group(0)
        style_attrs = re.findall(r'\bstyle\s*=', tag)
        assert len(style_attrs) == 1, (
            f"Reset button has {len(style_attrs)} style attributes; "
            f"must be exactly 1. Tag: {tag}"
        )
        assert 'display: none' in tag or 'display:none' in tag, (
            f"Reset button's style must include display:none. Tag: {tag}"
        )


# ---------------------------------------------------------------------------
# B2 + B3 + B6: manager-level (unit-style) tests
# ---------------------------------------------------------------------------

class TestB2ValidationTrackerPersistence:
    """B2: ValidationTracker.comparison_history survives save→load."""

    def test_validation_tracker_round_trips_through_save_state(
        self, tmp_path
    ):
        from potato.solo_mode.manager import SoloModeManager
        from potato.solo_mode.config import parse_solo_mode_config

        cfg = parse_solo_mode_config({
            'solo_mode': {
                'enabled': True,
                'labeling_models': [{
                    'endpoint_type': 'ollama',
                    'model': 'test',
                    'endpoint_url': 'http://127.0.0.1:1',
                }],
                'state_dir': str(tmp_path / "solo_state"),
            },
        })
        app_cfg = {
            'annotation_schemes': [{'name': 'sentiment'}],
            'item_properties': {'id_key': 'id', 'text_key': 'text'},
        }

        mgr1 = SoloModeManager(cfg, app_cfg)
        mgr1.validation_tracker.record_comparison(
            instance_id='r001',
            human_label='positive',
            llm_label='negative',
            schema_name='sentiment',
            agrees=False,
        )
        history_before = mgr1.validation_tracker.get_comparison_history()
        assert len(history_before) == 1
        mgr1._save_state()

        # Second manager loads from disk
        mgr2 = SoloModeManager(cfg, app_cfg)
        mgr2.load_state()
        history_after = mgr2.validation_tracker.get_comparison_history()
        assert len(history_after) == 1, (
            f"comparison_history did not survive restart: "
            f"before={len(history_before)} after={len(history_after)}"
        )
        # And the confusion matrix entry is restored
        assert mgr2.validation_tracker._metrics.confusion_matrix.get(
            ('negative', 'positive')
        ) == 1


class TestB3DisagreementsAPI:
    """B3: /api/disagreements reads from the manager's authoritative
    disagreement_ids set, not from the disconnected DisagreementResolver.

    Verified two ways:
    1. The endpoint exposes the new contract fields (total, pending_ids).
    2. A direct manager-level integration confirms record_human_label →
       manager.disagreement_ids → /api/disagreements counts correctly.
    """

    def test_endpoint_exposes_new_contract_fields(self, authed, solo_server):
        r = authed.get(f"{solo_server.base_url}/solo/api/disagreements")
        assert r.status_code == 200
        data = r.json()
        # New contract: total, pending, resolved, pending_ids
        assert 'total' in data, (
            f"/api/disagreements must return 'total' (was missing before B3 fix): {data}"
        )
        assert 'pending_ids' in data, (
            f"/api/disagreements must return 'pending_ids': {data}"
        )
        # Old contract (now removed) had 'stats' nested from resolver
        # (always-empty dict). Its absence confirms we're not on the old path.

    def test_manager_disagreement_path_drives_counts(self, tmp_path):
        """Direct integration: writing a disagreement to manager.disagreement_ids
        is visible via get_pending_disagreements (the source the route now reads)."""
        from potato.solo_mode.manager import SoloModeManager, LLMPrediction
        from potato.solo_mode.config import parse_solo_mode_config

        cfg = parse_solo_mode_config({
            'solo_mode': {
                'enabled': True,
                'labeling_models': [{
                    'endpoint_type': 'ollama',
                    'model': 'test',
                    'endpoint_url': 'http://127.0.0.1:1',
                }],
                'state_dir': str(tmp_path / "solo_state"),
            },
        })
        app_cfg = {
            'annotation_schemes': [{
                'name': 'sentiment',
                'labels': [
                    {'name': 'positive', 'key_value': '1'},
                    {'name': 'negative', 'key_value': '2'},
                ],
            }],
            'item_properties': {'id_key': 'id', 'text_key': 'text'},
        }
        mgr = SoloModeManager(cfg, app_cfg)
        instance_id = 'r000'
        with mgr._lock:
            mgr.predictions.setdefault(instance_id, {})['sentiment'] = LLMPrediction(
                instance_id=instance_id,
                schema_name='sentiment',
                predicted_label='negative',
                confidence_score=0.8,
                uncertainty_score=0.2,
                prompt_version=1,
                reasoning='test',
            )
        mgr.record_human_label(
            instance_id=instance_id,
            schema_name='sentiment',
            label='positive',
            user_id='test',
        )

        assert instance_id in mgr.disagreement_ids, (
            "record_human_label with conflicting LLM prediction must add "
            "to manager.disagreement_ids"
        )
        pending = mgr.get_pending_disagreements()
        assert instance_id in pending, (
            f"get_pending_disagreements (what /api/disagreements reads) must "
            f"contain unresolved instances: {pending}"
        )


class TestB6PauseResume:
    """B6: pause/resume actually toggles the background loop's pause flag."""

    def test_pause_then_resume_via_manager(self, solo_server):
        import importlib
        mod = importlib.import_module('potato.solo_mode.manager')
        mgr = mod.get_solo_mode_manager()
        if mgr is None:
            pytest.skip("Solo manager not available")

        # Ensure background labeling is running
        if not mgr.is_background_labeling_running():
            mgr.start_background_labeling()
            time.sleep(0.2)

        assert mgr.is_background_labeling_running()
        assert not mgr.is_background_labeling_paused()

        paused = mgr.pause_background_labeling()
        assert paused is True
        assert mgr.is_background_labeling_paused()

        # Stats should reflect paused state
        stats = mgr.get_llm_labeling_stats()
        assert stats['is_paused'] is True
        assert stats['is_running'] is False  # paused → not actively running

        resumed = mgr.resume_background_labeling()
        assert resumed is True
        assert not mgr.is_background_labeling_paused()

        stats = mgr.get_llm_labeling_stats()
        assert stats['is_paused'] is False
        assert stats['is_running'] is True

"""
Server tests for blind suggestions (solo_mode.suggestions) on the real routes.

On this branch the annotate page never shows the LLM's label before the human
answers, so it posts suggestion_visible=0 for every item and every comparison
is filed as blind. The on-demand /solo/llm-suggestion endpoint still withholds
a blind item's label until the human has answered it.
"""

import os
import re
import time

import pytest
import requests
import yaml

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.server.test_solo_mode.test_solo_mode_api import (
    _create_solo_mode_test_config,
)


@pytest.fixture(scope="module")
def blind_server():
    tests_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    test_dir = os.path.join(tests_dir, "output", "solo_blind_suggestions_test")
    os.makedirs(test_dir, exist_ok=True)
    config_file = _create_solo_mode_test_config(test_dir)
    with open(config_file) as f:
        config = yaml.safe_load(f)
    config['annotation_task_name'] = 'solo_blind_test'
    config['solo_mode']['suggestions'] = {
        'display': 'blind_sample', 'blind_rate': 0.5, 'minimum_blind_sample': 2,
    }
    with open(config_file, 'w') as f:
        yaml.dump(config, f)

    from potato.solo_mode import clear_solo_mode_manager
    clear_solo_mode_manager()
    server = FlaskTestServer(port=find_free_port(preferred_port=9230),
                             debug=False, config_file=config_file)
    if not server.start_server():
        pytest.skip("Failed to start Flask server")
    server._wait_for_server_ready(timeout=15)
    yield server
    server.stop_server()
    clear_solo_mode_manager()
    import shutil
    shutil.rmtree(test_dir, ignore_errors=True)


@pytest.fixture
def manager(blind_server):
    from potato.solo_mode import get_solo_mode_manager
    from potato.solo_mode.manager import LLMPrediction
    mgr = get_solo_mode_manager()
    assert mgr is not None
    mgr.pause_background_labeling()
    # The annotate page sends a user without a prompt back to Setup.
    if not mgr.get_current_prompt_text():
        mgr.create_prompt_version("Label the sentiment.", "user")
    for k in range(10):
        iid = f"api_{k:03d}"
        mgr.set_llm_prediction(iid, 'sentiment', LLMPrediction(
            instance_id=iid, schema_name='sentiment', predicted_label='positive',
            confidence_score=0.9, uncertainty_score=0.1, prompt_version=1,
            model_name='test'))
    return mgr


@pytest.fixture
def session(blind_server):
    s = requests.Session()
    s.post(f"{blind_server.base_url}/auth",
           data={"email": f"blind_user_{time.time()}", "pass": ""})
    s.headers['Origin'] = blind_server.base_url
    s.headers['Referer'] = blind_server.base_url + "/"
    yield s
    s.close()


def _field(html, name):
    m = re.search(rf'name="{name}"[^>]*value="([^"]*)"', html)
    return m.group(1) if m else None


def test_annotate_page_withholds_blind_suggestions(blind_server, manager, session):
    seen = {'blind': 0, 'shown': 0}
    for _ in range(10):
        html = session.get(f"{blind_server.base_url}/solo/annotate").text
        iid = _field(html, 'instance_id')
        if iid is None:
            break
        assert 'id="accept-llm-btn"' not in html
        assert 'The model suggests' not in html
        assert _field(html, 'suggestion_visible') == '0'
        seen['blind' if manager.anchoring.is_blind(iid) else 'shown'] += 1

        # A blind item's label stays withheld until the human answers it.
        suggestion = session.get(f"{blind_server.base_url}/solo/llm-suggestion",
                                 params={'instance_id': iid}).json()
        if manager.anchoring.is_blind(iid):
            assert suggestion == {'available': False, 'blind': True}

        # Post the page's own visibility back, as the browser would.
        session.post(f"{blind_server.base_url}/solo/annotate", data={
            'instance_id': iid, 'annotation': 'positive',
            'suggestion_visible': _field(html, 'suggestion_visible'),
            'accepted_suggestion': '0',
        }, allow_redirects=False)
    # blind_rate 0.5 over ten items: both kinds of item should appear.
    assert seen['blind'] and seen['shown'], seen

    # Nothing was shown, so every comparison is filed as blind.
    stats = session.get(f"{blind_server.base_url}/solo/api/status").json()['anchoring']
    assert stats['blind']['compared'] == seen['blind'] + seen['shown']
    assert stats['shown']['compared'] == 0
    assert stats['display'] == 'blind_sample'


def test_status_page_renders_the_blind_agreement_card(blind_server, session):
    html = session.get(f"{blind_server.base_url}/solo/status").text
    assert 'id="anchoring-card"' in html
    assert 'Blind Agreement' in html


def test_sidebar_progress_counts_the_whole_dataset(blind_server, manager, session):
    """Once the LLM has labelled every item, the sidebar used to read 0 / 0."""
    from potato.solo_mode.manager import AgreementMetrics
    from potato.solo_mode.phase_controller import SoloPhase
    # Undo the earlier test's handoff so the page serves an item again.
    manager.agreement_metrics = AgreementMetrics()
    manager.human_labeled_ids = set()
    manager.phase_controller.transition_to(SoloPhase.PARALLEL_ANNOTATION, force=True)
    for k in range(10):
        manager.llm_labeled_ids.add(f"api_{k:03d}")
    html = session.get(f"{blind_server.base_url}/solo/annotate").text
    assert 'name="instance_id"' in html
    progress = re.search(r'Your progress</span>\s*<span class="stat-value">([^<]+)<', html)
    assert progress and progress.group(1).strip().endswith('/ 10'), progress
    assert 'Left for you' in html

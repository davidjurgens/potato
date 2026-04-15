"""
End-to-end phase flow tests using the SimulatedUser infrastructure.

These tests combine the real-world-style annotation behavior of
`potato.simulator.SimulatedUser` with the multi-phase workflow
(consent → instructions → annotation). The simulator provides realistic
timing, strategy, and competence handling for the annotation phase; the
test harness walks through pre-annotation phases manually, since the
simulator currently only handles the annotation phase.

Coverage goals:
- Full phase flow runs end-to-end without crashes
- After-phase annotation loop submits via the real `/updateinstance`
  endpoint and gets 200 responses
- Back-navigation across annotated instances works after a realistic
  simulator-driven annotation run (regression guard for the PR #147
  class of bugs when the user has recently interacted with multiple
  instances)
- Phase ordering bug class: users who finish annotation phase land on
  poststudy (not DONE or an error) when poststudy is configured
"""

import json
from pathlib import Path

import pytest
import requests

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import (
    create_test_directory,
    create_test_data_file,
    create_test_config,
    cleanup_test_directory,
)

from potato.simulator.user_simulator import SimulatedUser
from potato.simulator.config import (
    UserConfig,
    CompetenceLevel,
    AnnotationStrategyType,
    TimingConfig,
)


# =====================================================================
# Helpers
# =====================================================================


def _write_phase_scheme(test_dir, filename, schemes):
    path = Path(test_dir) / filename
    with open(path, "w") as f:
        json.dump(schemes, f)
    return filename


def _build_sim(server_url: str, user_id: str, max_annotations: int = 3) -> SimulatedUser:
    """Construct a SimulatedUser with deterministic settings for tests."""
    user_config = UserConfig(
        user_id=user_id,
        competence=CompetenceLevel.GOOD,
        strategy=AnnotationStrategyType.RANDOM,
        timing=TimingConfig(
            annotation_time_min=0.0,
            annotation_time_max=0.1,
            annotation_time_mean=0.05,
            annotation_time_std=0.01,
            distribution="uniform",
            fast_response_threshold=0.0,
        ),
        max_annotations=max_annotations,
    )
    return SimulatedUser(
        user_config=user_config,
        server_url=server_url,
        simulate_wait=False,  # no sleeps
    )


def _walk_consent_and_instructions(sim: SimulatedUser):
    """POST through the consent and instructions phases using the sim's session.

    Assumes the phase config matches the fixture in this file (consent has
    age_consent + info_consent radios, instructions has read_instructions).
    """
    # Consent page
    home = sim.session.get(f"{sim.server_url}/", timeout=5)
    assert home.status_code == 200
    assert "Are you at least 18 years old?" in home.text, (
        "Expected consent page on first home GET"
    )

    resp = sim.session.post(
        f"{sim.server_url}/annotate",
        data={
            "age_consent:::Yes": "true",
            "info_consent:::Yes": "true",
        },
        timeout=5,
        allow_redirects=True,
    )
    assert resp.status_code == 200

    # Instructions page
    home = sim.session.get(f"{sim.server_url}/", timeout=5)
    assert home.status_code == 200
    assert "Have you read the instructions?" in home.text, (
        "Expected instructions page after consent submission"
    )

    resp = sim.session.post(
        f"{sim.server_url}/annotate",
        data={"read_instructions:::Yes": "true"},
        timeout=5,
        allow_redirects=True,
    )
    assert resp.status_code == 200


def _drive_simulator_annotation_loop(sim: SimulatedUser, max_items: int) -> int:
    """Drive the simulator's annotation sub-methods directly.

    We don't call `run_simulation()` because it always calls `login()` again,
    which is a no-op but redundant after the phase walk. Instead, we invoke
    the individual steps just like `run_simulation()` does.

    Returns the number of annotations successfully submitted.
    """
    schemas = sim.get_schemas()
    assert schemas, "Simulator failed to fetch annotation schemas"

    submitted = 0
    for _ in range(max_items):
        instance = sim.get_current_instance()
        if not instance or not instance.get("instance_id"):
            break

        response_time = sim.timing.get_response_time(0.0)
        annotations = sim.generate_annotations(instance)

        if sim.submit_annotation(
            instance["instance_id"], annotations, response_time
        ):
            submitted += 1

        if not sim.navigate_next():
            break

    return submitted


# =====================================================================
# TestSimulatorAfterPhaseWalk — core end-to-end flow
# =====================================================================


class TestSimulatorAfterPhaseWalk:
    """Use SimulatedUser for the annotation phase after manually walking
    through consent and instructions."""

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("sim_phase_flow_test")
        test_data = [
            {"id": f"simp_{i}", "text": f"Simulator phase item {i}."}
            for i in range(5)
        ]
        data_file = create_test_data_file(test_dir, test_data)

        consent_file = _write_phase_scheme(
            test_dir,
            "consent_phase.json",
            [
                {
                    "name": "age_consent",
                    "annotation_type": "radio",
                    "labels": ["Yes", "No"],
                    "description": "Are you at least 18 years old?",
                },
                {
                    "name": "info_consent",
                    "annotation_type": "radio",
                    "labels": ["Yes", "No"],
                    "description": "Do you agree to participate?",
                },
            ],
        )
        instructions_file = _write_phase_scheme(
            test_dir,
            "instructions_phase.json",
            [
                {
                    "name": "read_instructions",
                    "annotation_type": "radio",
                    "labels": ["Yes", "No"],
                    "description": "Have you read the instructions?",
                }
            ],
        )

        config_file = create_test_config(
            test_dir,
            annotation_schemes=[
                {
                    "name": "sentiment",
                    "annotation_type": "radio",
                    "labels": ["positive", "negative", "neutral"],
                    "description": "Classify the sentiment of the text.",
                }
            ],
            data_files=[data_file],
            phases={
                "order": ["consent", "instructions", "annotation"],
                "consent": {"type": "consent", "file": consent_file},
                "instructions": {
                    "type": "instructions",
                    "file": instructions_file,
                },
            },
        )

        server = FlaskTestServer(config=config_file)
        if not server.start():
            pytest.fail("Failed to start Flask test server")
        request.addfinalizer(lambda: (server.stop(), cleanup_test_directory(test_dir)))
        yield server

    def test_simulator_annotates_after_consent_and_instructions(self, flask_server):
        """
        Full flow: sim.login → walk consent → walk instructions → sim annotates 3 items.
        """
        sim = _build_sim(flask_server.base_url, "sim_flow_user_1", max_annotations=3)
        assert sim.login(), "Simulator failed to log in"

        _walk_consent_and_instructions(sim)

        submitted = _drive_simulator_annotation_loop(sim, max_items=3)
        assert submitted == 3, (
            f"Simulator expected to submit 3 annotations, got {submitted}. "
            f"Errors: {sim.result.errors}"
        )
        assert not sim.result.was_blocked
        assert len(sim.result.annotations) == 3

    def test_simulator_back_nav_to_annotated_instance_post_phase(self, flask_server):
        """
        Regression combining the PR #147 bug class with realistic simulator
        behavior: after the simulator annotates multiple items, back-navigate
        via POST action=prev_instance and assert the render succeeds.
        """
        sim = _build_sim(flask_server.base_url, "sim_flow_user_2", max_annotations=2)
        assert sim.login()

        _walk_consent_and_instructions(sim)

        submitted = _drive_simulator_annotation_loop(sim, max_items=2)
        assert submitted == 2

        # Back-navigate into the annotated instance.
        resp = sim.session.post(
            f"{flask_server.base_url}/annotate",
            data={"action": "prev_instance"},
            timeout=5,
        )
        assert resp.status_code == 200, (
            f"Back-navigation after simulator annotation failed: {resp.status_code}"
        )
        # The annotated-render branch must have executed — badge should be 'labeled'
        assert "status-badge labeled" in resp.text, (
            "Back-navigated page did not render the 'labeled' status badge"
        )

    def test_simulator_run_is_isolated_per_user(self, flask_server):
        """
        Two simulated users should not interfere with each other's phase progression.
        User A walks to annotation and annotates 2 items. User B starts fresh and
        must see the consent page (not user A's annotation state).
        """
        sim_a = _build_sim(flask_server.base_url, "sim_flow_user_a", max_annotations=2)
        assert sim_a.login()
        _walk_consent_and_instructions(sim_a)
        assert _drive_simulator_annotation_loop(sim_a, max_items=2) == 2

        sim_b = _build_sim(flask_server.base_url, "sim_flow_user_b", max_annotations=2)
        assert sim_b.login()

        home = sim_b.session.get(f"{flask_server.base_url}/", timeout=5)
        assert home.status_code == 200
        # User B is a new user — must be on consent page
        assert "Are you at least 18 years old?" in home.text, (
            "New user B incorrectly skipped consent phase"
        )


# =====================================================================
# TestPoststudyPhaseReachable — phase-ordering regression
# =====================================================================


class TestPoststudyPhaseReachable:
    """After completing all assigned items, a user with a poststudy phase
    configured must reach the poststudy page (not hit an error or skip it).

    Guards against the phase-ordering bug class where annotation → poststudy
    transition could fail if the poststudy phase was registered out of order
    (see fdfa414 / test_phase_page_order_from_config.py).
    """

    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        test_dir = create_test_directory("poststudy_reach_test")
        test_data = [
            {"id": "ps_1", "text": "Poststudy test item 1."},
            {"id": "ps_2", "text": "Poststudy test item 2."},
        ]
        data_file = create_test_data_file(test_dir, test_data)

        poststudy_file = _write_phase_scheme(
            test_dir,
            "poststudy_phase.json",
            [
                {
                    "name": "overall_rating",
                    "annotation_type": "radio",
                    "labels": ["1", "2", "3", "4", "5"],
                    "description": "How was the study overall?",
                }
            ],
        )

        config_file = create_test_config(
            test_dir,
            annotation_schemes=[
                {
                    "name": "rating",
                    "annotation_type": "radio",
                    "labels": ["good", "bad"],
                    "description": "Rate the item.",
                }
            ],
            data_files=[data_file],
            max_annotations_per_user=2,
            phases={
                "order": ["annotation", "poststudy"],
                "poststudy": {
                    "type": "poststudy",
                    "file": poststudy_file,
                },
            },
        )

        server = FlaskTestServer(config=config_file)
        if not server.start():
            pytest.fail("Failed to start Flask test server")
        request.addfinalizer(lambda: (server.stop(), cleanup_test_directory(test_dir)))
        yield server

    def test_user_reaches_poststudy_after_annotations(self, flask_server):
        """Annotate both items via the simulator, then the next home GET
        should render the poststudy survey."""
        sim = _build_sim(flask_server.base_url, "poststudy_user", max_annotations=2)
        assert sim.login()

        # No consent/instructions configured — straight to annotation
        submitted = _drive_simulator_annotation_loop(sim, max_items=5)
        # Server should cut us off at 2 (max_annotations_per_user)
        assert submitted >= 2

        # After exhausting annotations, home should show poststudy
        resp = sim.session.get(f"{flask_server.base_url}/", timeout=5)
        assert resp.status_code == 200
        assert "How was the study overall?" in resp.text, (
            f"Expected poststudy survey, got:\n{resp.text[:500]}"
        )

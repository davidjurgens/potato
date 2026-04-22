"""
Solo Mode Simulator

Drives all 12 phases of Potato's Solo Mode through the /solo/* HTTP endpoints,
simulating a single human annotator collaborating with an LLM.

Usage:
    from potato.simulator.solo_mode_simulator import SoloModeSimulator, SoloSimulatorConfig

    sim = SoloModeSimulator(
        server_url="http://localhost:8200",
        gold_labels={"emo_001": "joy", "emo_002": "sadness", ...},
        config=SoloSimulatorConfig(noise_rate=0.2),
    )
    result = sim.run_full_simulation()
    print(result.summary())
"""

import json
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


@dataclass
class SoloSimulatorConfig:
    """Configuration for solo mode simulation."""

    # User identity
    user_id: str = "solo_simulator"
    password: str = "simulated_password_123"

    # Task description for setup phase
    task_description: str = (
        "Classify the primary emotion expressed in each text. "
        "Choose the single best label from: joy, sadness, anger, fear, surprise, neutral."
    )

    # Annotation noise
    noise_rate: float = 0.2  # probability of choosing wrong label

    # Disagreement resolution strategy
    disagree_prefer_human: float = 0.6
    disagree_prefer_llm: float = 0.25
    disagree_prefer_third: float = 0.15

    # Annotation counts per phase
    parallel_annotation_count: int = 30
    active_annotation_count: int = 50

    # Review/validation behavior
    review_approve_rate: float = 0.7
    rule_approve_rate: float = 0.7

    # Timing
    max_wait_autonomous: int = 120  # seconds to wait for autonomous labeling
    poll_interval: float = 2.0  # seconds between status polls

    # Phase control
    force_advance_on_stuck: bool = True  # use /api/advance-phase if stuck

    # Schema name (must match config)
    schema_name: str = "emotion"


@dataclass
class PhaseResult:
    """Result from simulating a single phase."""

    phase: str
    success: bool = False
    annotations_submitted: int = 0
    disagreements_encountered: int = 0
    disagreements_resolved: int = 0
    reviews_completed: int = 0
    errors: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SoloSimulationResult:
    """Complete results from a solo mode simulation run."""

    phase_results: List[PhaseResult] = field(default_factory=list)
    total_annotations: int = 0
    total_disagreements: int = 0
    total_errors: List[str] = field(default_factory=list)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    final_status: Optional[Dict[str, Any]] = None

    def summary(self) -> str:
        lines = [
            "=== Solo Mode Simulation Summary ===",
            f"Duration: {(self.end_time - self.start_time).total_seconds():.1f}s"
            if self.start_time and self.end_time
            else "Duration: unknown",
            f"Total annotations: {self.total_annotations}",
            f"Total disagreements: {self.total_disagreements}",
            f"Errors: {len(self.total_errors)}",
            "",
            "Phase Results:",
        ]
        for pr in self.phase_results:
            status = "OK" if pr.success else "FAIL"
            lines.append(
                f"  {pr.phase}: {status} "
                f"(annotations={pr.annotations_submitted}, "
                f"disagreements={pr.disagreements_encountered}, "
                f"duration={pr.duration_seconds:.1f}s)"
            )
        if self.final_status:
            lines.append("")
            lines.append("Final Status:")
            agreement = self.final_status.get("agreement", {})
            lines.append(f"  Agreement rate: {agreement.get('agreement_rate', 'N/A')}")
            lines.append(
                f"  Total compared: {agreement.get('total_compared', 'N/A')}"
            )
            labeling = self.final_status.get("labeling", {})
            lines.append(f"  Human labeled: {labeling.get('human_labeled', 'N/A')}")
            lines.append(f"  LLM labeled: {labeling.get('llm_labeled', 'N/A')}")
            prompt = self.final_status.get("prompt", {})
            lines.append(
                f"  Prompt versions: {prompt.get('total_versions', 'N/A')}"
            )
        if self.total_errors:
            lines.append("")
            lines.append(f"Errors ({len(self.total_errors)}):")
            for err in self.total_errors[:10]:
                lines.append(f"  - {err}")
        return "\n".join(lines)


class SoloModeSimulator:
    """Simulates a single user driving all solo mode phases via HTTP.

    Args:
        server_url: Base URL of the Potato server
        gold_labels: Dict mapping instance_id -> gold label string
        available_labels: List of all valid label names
        config: SoloSimulatorConfig
    """

    def __init__(
        self,
        server_url: str,
        gold_labels: Dict[str, str],
        available_labels: Optional[List[str]] = None,
        config: Optional[SoloSimulatorConfig] = None,
    ):
        self.server_url = server_url.rstrip("/")
        self.gold_labels = gold_labels
        self.available_labels = available_labels or []
        self.config = config or SoloSimulatorConfig()
        self.session = requests.Session()
        self.result = SoloSimulationResult()
        self._logged_in = False

    # === Authentication ===

    def _login(self) -> bool:
        """Register and login the simulated user."""
        try:
            self.session.post(
                f"{self.server_url}/register",
                data={
                    "action": "signup",
                    "email": self.config.user_id,
                    "pass": self.config.password,
                },
                allow_redirects=True,
                timeout=30,
            )
            self.session.post(
                f"{self.server_url}/auth",
                data={
                    "action": "login",
                    "email": self.config.user_id,
                    "pass": self.config.password,
                },
                allow_redirects=True,
                timeout=30,
            )
            self._logged_in = True
            logger.info(f"Logged in as {self.config.user_id}")
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"Login failed: {e}")
            self.result.total_errors.append(f"Login failed: {e}")
            return False

    # === Status & Phase Helpers ===

    def _get_status(self) -> Dict[str, Any]:
        """Get current solo mode status."""
        try:
            resp = self.session.get(
                f"{self.server_url}/solo/api/status", timeout=30
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.warning(f"Failed to get status: {e}")
        return {}

    def _get_current_phase(self) -> str:
        """Get current phase name."""
        status = self._get_status()
        # Status may return phase as int, string, or dict depending on version
        phase_info = status.get("phase", {})
        if isinstance(phase_info, dict):
            return phase_info.get("current_phase", "unknown")
        # phase_name is the string representation
        return status.get("phase_name", str(phase_info)).lower()

    def _force_advance(self, target_phase: str) -> bool:
        """Force advance to a specific phase."""
        try:
            resp = self.session.post(
                f"{self.server_url}/solo/api/advance-phase",
                json={"phase": target_phase, "force": True},
                timeout=30,
            )
            if resp.status_code == 200:
                logger.info(f"Force-advanced to {target_phase}")
                return True
            logger.warning(
                f"Force advance to {target_phase} failed: {resp.status_code} {resp.text}"
            )
        except Exception as e:
            logger.error(f"Force advance failed: {e}")
        return False

    def _generate_annotation(self, instance_id: str) -> str:
        """Generate an annotation for an instance.

        Uses gold label with noise_rate probability of choosing wrong label.
        """
        gold = self.gold_labels.get(instance_id)
        if gold and random.random() > self.config.noise_rate:
            return gold

        # Choose a random label (possibly different from gold)
        if self.available_labels:
            candidates = [l for l in self.available_labels if l != gold]
            if candidates:
                return random.choice(candidates)
        return gold or (self.available_labels[0] if self.available_labels else "unknown")

    # === Phase Simulators ===

    def _simulate_setup(self) -> PhaseResult:
        """Simulate the SETUP phase: submit task description."""
        start = time.time()
        result = PhaseResult(phase="setup")

        try:
            resp = self.session.post(
                f"{self.server_url}/solo/setup",
                data={"task_description": self.config.task_description},
                allow_redirects=True,
                timeout=30,
            )
            result.success = resp.status_code in (200, 302)
            if not result.success:
                result.errors.append(f"Setup failed: {resp.status_code}")
            logger.info(f"Setup phase: {'OK' if result.success else 'FAIL'}")
        except Exception as e:
            result.errors.append(f"Setup error: {e}")
            result.success = False

        result.duration_seconds = time.time() - start
        return result

    def _simulate_prompt_review(self) -> PhaseResult:
        """Simulate PROMPT_REVIEW: accept the prompt and advance."""
        start = time.time()
        result = PhaseResult(phase="prompt_review")

        try:
            # Accept prompt and advance to edge cases
            resp = self.session.post(
                f"{self.server_url}/solo/prompt",
                data={"action": "advance"},
                allow_redirects=True,
                timeout=30,
            )
            result.success = resp.status_code in (200, 302)
            if not result.success:
                result.errors.append(f"Prompt review failed: {resp.status_code}")
        except Exception as e:
            result.errors.append(f"Prompt review error: {e}")
            result.success = False

        result.duration_seconds = time.time() - start
        return result

    def _simulate_edge_case_labeling(self) -> PhaseResult:
        """Simulate EDGE_CASE_SYNTHESIS + EDGE_CASE_LABELING."""
        start = time.time()
        result = PhaseResult(phase="edge_case_labeling")

        try:
            # GET to trigger synthesis
            resp = self.session.get(
                f"{self.server_url}/solo/edge-cases",
                allow_redirects=True,
                timeout=60,
            )

            # Label edge cases in a loop
            labeled_count = 0
            for _ in range(20):  # max iterations to avoid infinite loop
                resp = self.session.get(
                    f"{self.server_url}/solo/edge-cases",
                    timeout=30,
                )
                if resp.status_code != 200:
                    break

                # Parse the page to find the current case
                # Use API endpoint if available, otherwise check page content
                api_resp = self.session.get(
                    f"{self.server_url}/solo/api/edge-cases",
                    timeout=30,
                )
                if api_resp.status_code == 200:
                    ec_data = api_resp.json()
                    unlabeled = ec_data.get("unlabeled", 0)
                    if unlabeled == 0:
                        break

                # Submit a label for the current edge case
                label = random.choice(self.available_labels) if self.available_labels else "neutral"
                resp = self.session.post(
                    f"{self.server_url}/solo/edge-cases",
                    data={"label": label},
                    allow_redirects=True,
                    timeout=30,
                )
                labeled_count += 1

            result.annotations_submitted = labeled_count
            result.success = True
            logger.info(f"Edge case labeling: labeled {labeled_count} cases")
        except Exception as e:
            result.errors.append(f"Edge case labeling error: {e}")
            result.success = False

        result.duration_seconds = time.time() - start
        return result

    def _simulate_annotation(self, count: int) -> PhaseResult:
        """Simulate annotation phase (PARALLEL or ACTIVE).

        Submits `count` annotations via /solo/annotate.
        Handles disagreement redirects inline.
        """
        start = time.time()
        result = PhaseResult(phase="annotation")
        annotations_done = 0
        disagreements = 0

        for i in range(count):
            try:
                # GET next instance
                resp = self.session.get(
                    f"{self.server_url}/solo/annotate",
                    allow_redirects=True,
                    timeout=30,
                )
                if resp.status_code != 200:
                    result.errors.append(f"Get annotate failed: {resp.status_code}")
                    continue

                # Extract instance_id from the page
                # Look for hidden input or data attribute
                instance_id = self._extract_instance_id(resp.text)
                if not instance_id:
                    logger.debug("No instance available, stopping annotation")
                    break

                # Generate annotation
                annotation = self._generate_annotation(instance_id)

                # Submit annotation
                resp = self.session.post(
                    f"{self.server_url}/solo/annotate",
                    data={"instance_id": instance_id, "annotation": annotation},
                    allow_redirects=False,
                    timeout=30,
                )

                annotations_done += 1

                # Check if redirected to disagreements
                if resp.status_code == 302:
                    location = resp.headers.get("Location", "")
                    if "disagreement" in location:
                        disagreements += 1
                        self._handle_disagreement()

            except Exception as e:
                result.errors.append(f"Annotation {i} error: {e}")

        result.annotations_submitted = annotations_done
        result.disagreements_encountered = disagreements
        result.success = annotations_done > 0
        result.duration_seconds = time.time() - start
        logger.info(
            f"Annotation phase: {annotations_done} annotations, "
            f"{disagreements} disagreements"
        )
        return result

    def _handle_disagreement(self) -> None:
        """Handle a single disagreement resolution."""
        try:
            # GET the disagreement page
            resp = self.session.get(
                f"{self.server_url}/solo/disagreements",
                allow_redirects=True,
                timeout=30,
            )
            if resp.status_code != 200:
                return

            # Extract disagreement ID from page
            disagreement_id = self._extract_disagreement_id(resp.text)
            if not disagreement_id:
                return

            # Decide resolution strategy
            roll = random.random()
            if roll < self.config.disagree_prefer_human:
                resolution = "human"
            elif roll < self.config.disagree_prefer_human + self.config.disagree_prefer_llm:
                resolution = "llm"
            else:
                # Choose a third label
                resolution = random.choice(self.available_labels) if self.available_labels else "neutral"

            # Submit resolution
            self.session.post(
                f"{self.server_url}/solo/disagreements",
                data={
                    "disagreement_id": disagreement_id,
                    "resolution": resolution,
                },
                allow_redirects=True,
                timeout=30,
            )
            logger.debug(f"Resolved disagreement {disagreement_id}: {resolution}")

        except Exception as e:
            logger.warning(f"Disagreement resolution error: {e}")

    def _simulate_periodic_review(self) -> PhaseResult:
        """Simulate PERIODIC_REVIEW: approve or correct low-confidence labels."""
        start = time.time()
        result = PhaseResult(phase="periodic_review")
        reviews = 0

        try:
            for _ in range(20):  # max iterations
                resp = self.session.get(
                    f"{self.server_url}/solo/review",
                    allow_redirects=True,
                    timeout=30,
                )
                if resp.status_code != 200:
                    break

                instance_id = self._extract_instance_id(resp.text)
                if not instance_id:
                    break

                # Decide: approve or correct
                if random.random() < self.config.review_approve_rate:
                    decision = "approve"
                    corrected_label = ""
                else:
                    decision = "correct"
                    gold = self.gold_labels.get(instance_id, "")
                    corrected_label = gold or (
                        random.choice(self.available_labels) if self.available_labels else ""
                    )

                self.session.post(
                    f"{self.server_url}/solo/review",
                    data={
                        "instance_id": instance_id,
                        "decision": decision,
                        "corrected_label": corrected_label,
                    },
                    allow_redirects=True,
                    timeout=30,
                )
                reviews += 1

        except Exception as e:
            result.errors.append(f"Review error: {e}")

        result.reviews_completed = reviews
        result.success = True
        result.duration_seconds = time.time() - start
        return result

    def _simulate_rule_review(self) -> PhaseResult:
        """Simulate RULE_REVIEW: approve or reject edge case rule categories."""
        start = time.time()
        result = PhaseResult(phase="rule_review")

        try:
            resp = self.session.get(
                f"{self.server_url}/solo/api/rules/categories",
                timeout=30,
            )
            if resp.status_code == 200:
                data = resp.json()
                categories = data.get("categories", [])
                for cat in categories:
                    cat_id = cat.get("id", "")
                    action = "approve" if random.random() < self.config.rule_approve_rate else "reject"
                    self.session.post(
                        f"{self.server_url}/solo/api/rules/approve",
                        json={"category_id": cat_id, "action": action, "notes": ""},
                        timeout=30,
                    )
                result.metadata["categories_reviewed"] = len(categories)

            result.success = True
        except Exception as e:
            result.errors.append(f"Rule review error: {e}")
            result.success = False

        result.duration_seconds = time.time() - start
        return result

    def _simulate_autonomous_wait(self) -> PhaseResult:
        """Wait for autonomous labeling to complete."""
        start = time.time()
        result = PhaseResult(phase="autonomous_labeling")

        # Start labeling if not running
        self.session.post(
            f"{self.server_url}/solo/api/start-labeling",
            timeout=30,
        )

        # Poll until done or timeout
        deadline = time.time() + self.config.max_wait_autonomous
        while time.time() < deadline:
            status = self._get_status()
            labeling = status.get("labeling", {})
            if not labeling.get("background_running", True):
                break
            time.sleep(self.config.poll_interval)

        result.success = True
        result.duration_seconds = time.time() - start
        return result

    def _simulate_validation(self) -> PhaseResult:
        """Simulate FINAL_VALIDATION: validate a sample of LLM-only labels."""
        start = time.time()
        result = PhaseResult(phase="final_validation")
        validated = 0

        try:
            for _ in range(100):  # max iterations
                resp = self.session.get(
                    f"{self.server_url}/solo/validation",
                    allow_redirects=True,
                    timeout=30,
                )
                if resp.status_code != 200:
                    break

                instance_id = self._extract_instance_id(resp.text)
                if not instance_id:
                    break

                # Get gold label or approve LLM label
                gold = self.gold_labels.get(instance_id)
                if gold:
                    self.session.post(
                        f"{self.server_url}/solo/validation",
                        data={
                            "instance_id": instance_id,
                            "human_label": gold,
                        },
                        allow_redirects=True,
                        timeout=30,
                    )
                else:
                    # Approve the LLM label
                    self.session.post(
                        f"{self.server_url}/solo/validation",
                        data={
                            "instance_id": instance_id,
                            "decision": "approve",
                        },
                        allow_redirects=True,
                        timeout=30,
                    )
                validated += 1

        except Exception as e:
            result.errors.append(f"Validation error: {e}")

        result.annotations_submitted = validated
        result.success = True
        result.duration_seconds = time.time() - start
        return result

    # === LLM Control Helpers ===

    def _start_llm_labeling(self) -> None:
        """Start the background LLM labeling thread."""
        try:
            self.session.post(
                f"{self.server_url}/solo/api/start-labeling",
                timeout=30,
            )
            logger.info("Started LLM labeling")
        except Exception as e:
            logger.warning(f"Failed to start LLM labeling: {e}")

    def _wait_for_predictions(self, min_count: int = 10, timeout: int = 60) -> int:
        """Wait until at least min_count LLM predictions exist.

        Returns:
            Actual prediction count
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                resp = self.session.get(
                    f"{self.server_url}/solo/api/predictions",
                    timeout=30,
                )
                if resp.status_code == 200:
                    count = resp.json().get("count", 0)
                    if count >= min_count:
                        logger.info(f"LLM has {count} predictions (target: {min_count})")
                        return count
            except Exception:
                pass
            time.sleep(self.config.poll_interval)
        logger.warning(f"Timeout waiting for {min_count} predictions")
        return 0

    # === HTML Parsing Helpers ===

    def _extract_instance_id(self, html: str) -> Optional[str]:
        """Extract instance_id from an HTML page.

        Looks for common patterns: hidden input, data attribute, or JSON.
        """
        import re

        # Pattern: <input ... name="instance_id" value="...">
        match = re.search(
            r'name=["\']instance_id["\'][^>]*value=["\']([^"\']+)', html
        )
        if match:
            return match.group(1)

        # Pattern: value="..." name="instance_id"
        match = re.search(
            r'value=["\']([^"\']+)["\'][^>]*name=["\']instance_id', html
        )
        if match:
            return match.group(1)

        # Pattern: data-instance-id="..."
        match = re.search(r'data-instance-id=["\']([^"\']+)', html)
        if match:
            return match.group(1)

        # Pattern: "instance_id": "..."
        match = re.search(r'"instance_id"\s*:\s*"([^"]+)"', html)
        if match:
            return match.group(1)

        return None

    def _extract_disagreement_id(self, html: str) -> Optional[str]:
        """Extract disagreement_id from the disagreement page."""
        import re

        match = re.search(
            r'name=["\']disagreement_id["\'][^>]*value=["\']([^"\']+)', html
        )
        if match:
            return match.group(1)

        match = re.search(
            r'value=["\']([^"\']+)["\'][^>]*name=["\']disagreement_id', html
        )
        if match:
            return match.group(1)

        return None

    # === Main Orchestration ===

    def run_full_simulation(self) -> SoloSimulationResult:
        """Run the complete solo mode simulation.

        Drives through all phases: setup, prompt review, edge cases,
        parallel annotation, active annotation, review, validation.

        Returns:
            SoloSimulationResult with per-phase metrics
        """
        self.result.start_time = datetime.now()
        random.seed(42)

        try:
            # Login
            if not self._login():
                return self.result

            # Discover available labels from schemas
            if not self.available_labels:
                self._discover_labels()

            # Phase 1: Setup
            pr = self._simulate_setup()
            self.result.phase_results.append(pr)

            # Phase 2: Prompt Review
            pr = self._simulate_prompt_review()
            self.result.phase_results.append(pr)

            # Phase 3-5: Edge Case Synthesis + Labeling + Validation
            current_phase = self._get_current_phase()
            if "edge" in current_phase.lower():
                pr = self._simulate_edge_case_labeling()
                self.result.phase_results.append(pr)

            # Phase 6: Parallel Annotation
            if self.config.force_advance_on_stuck:
                self._force_advance("parallel-annotation")

            # Start LLM labeling and wait for predictions to accumulate
            self._start_llm_labeling()
            self._wait_for_predictions(min_count=20, timeout=60)

            pr = self._simulate_annotation(count=self.config.parallel_annotation_count)
            self.result.phase_results.append(pr)
            self.result.total_annotations += pr.annotations_submitted
            self.result.total_disagreements += pr.disagreements_encountered

            # Phase 8: Active Annotation
            if self.config.force_advance_on_stuck:
                self._force_advance("active-annotation")

            # Wait for more LLM predictions
            self._wait_for_predictions(min_count=50, timeout=60)

            pr = self._simulate_annotation(count=self.config.active_annotation_count)
            self.result.phase_results.append(pr)
            self.result.total_annotations += pr.annotations_submitted
            self.result.total_disagreements += pr.disagreements_encountered

            # Check for periodic review
            current_phase = self._get_current_phase()
            if "review" in current_phase.lower() and "rule" not in current_phase.lower():
                pr = self._simulate_periodic_review()
                self.result.phase_results.append(pr)

            # Check for rule review
            if "rule" in current_phase.lower():
                pr = self._simulate_rule_review()
                self.result.phase_results.append(pr)

            # Phase 11: Autonomous Labeling
            if self.config.force_advance_on_stuck:
                self._force_advance("autonomous-labeling")
            pr = self._simulate_autonomous_wait()
            self.result.phase_results.append(pr)

            # Phase 12: Final Validation
            if self.config.force_advance_on_stuck:
                self._force_advance("final-validation")
            pr = self._simulate_validation()
            self.result.phase_results.append(pr)

            # Collect final status
            self.result.final_status = self._get_status()

        except Exception as e:
            logger.error(f"Simulation error: {e}")
            self.result.total_errors.append(f"Simulation error: {e}")

        finally:
            self.result.end_time = datetime.now()
            # Collect errors from all phases
            for pr in self.result.phase_results:
                self.result.total_errors.extend(pr.errors)

        return self.result

    def _discover_labels(self) -> None:
        """Discover available labels from the server's schema API."""
        try:
            resp = self.session.get(
                f"{self.server_url}/api/schemas",
                timeout=30,
            )
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and "schemas" in data:
                    schemas = data["schemas"]
                    if isinstance(schemas, dict):
                        schemas = list(schemas.values())
                elif isinstance(data, list):
                    schemas = data
                else:
                    schemas = list(data.values()) if isinstance(data, dict) else []

                for schema in schemas:
                    labels = schema.get("labels", [])
                    for label in labels:
                        if isinstance(label, str):
                            self.available_labels.append(label)
                        elif isinstance(label, dict):
                            self.available_labels.append(
                                label.get("name", str(label))
                            )
                logger.info(f"Discovered labels: {self.available_labels}")
        except Exception as e:
            logger.warning(f"Failed to discover labels: {e}")

    def get_verification_data(self) -> Dict[str, Any]:
        """Collect data for verification checks after simulation.

        Returns:
            Dict with status, predictions, prompts, and phase history.
        """
        data = {"status": self._get_status()}

        try:
            resp = self.session.get(
                f"{self.server_url}/solo/api/prompts", timeout=30
            )
            if resp.status_code == 200:
                data["prompts"] = resp.json()
        except Exception:
            pass

        try:
            resp = self.session.get(
                f"{self.server_url}/solo/api/predictions", timeout=30
            )
            if resp.status_code == 200:
                data["predictions"] = resp.json()
        except Exception:
            pass

        try:
            resp = self.session.get(
                f"{self.server_url}/solo/api/disagreements", timeout=30
            )
            if resp.status_code == 200:
                data["disagreements"] = resp.json()
        except Exception:
            pass

        return data

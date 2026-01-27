"""
Core user simulator class.

This module provides the SimulatedUser class that simulates a single
annotator interacting with the Potato annotation platform via its API.
"""

import logging
import random
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
import requests

from .config import (
    UserConfig,
    SimulatorConfig,
    CompetenceLevel,
    AnnotationStrategyType,
    TimingConfig,
)
from .competence_profiles import CompetenceProfile, create_competence_profile
from .annotation_strategies import AnnotationStrategy, create_strategy
from .timing_models import TimingModel, NoWaitTimingModel

logger = logging.getLogger(__name__)


@dataclass
class AnnotationRecord:
    """Record of a single annotation submission.

    Attributes:
        instance_id: ID of the annotated instance
        schema_name: Name of the annotation schema
        annotation: The annotation data submitted
        response_time: Time taken to annotate (seconds)
        timestamp: When the annotation was submitted
        was_attention_check: Whether this was an attention check item
        attention_check_passed: Result of attention check (if applicable)
        was_gold_standard: Whether this was a gold standard item
        gold_standard_correct: Whether gold standard was answered correctly
    """

    instance_id: str
    schema_name: str
    annotation: Dict[str, Any]
    response_time: float
    timestamp: datetime
    was_attention_check: bool = False
    attention_check_passed: Optional[bool] = None
    was_gold_standard: bool = False
    gold_standard_correct: Optional[bool] = None


@dataclass
class UserSimulationResult:
    """Results from a user simulation session.

    Attributes:
        user_id: ID of the simulated user
        annotations: List of annotation records
        total_time: Total simulation time in seconds
        attention_checks_passed: Number of passed attention checks
        attention_checks_failed: Number of failed attention checks
        gold_standard_correct: Number of correct gold standard answers
        gold_standard_incorrect: Number of incorrect gold standard answers
        errors: List of error messages encountered
        start_time: When simulation started
        end_time: When simulation ended
        was_blocked: Whether user was blocked by quality control
    """

    user_id: str
    annotations: List[AnnotationRecord] = field(default_factory=list)
    total_time: float = 0.0
    attention_checks_passed: int = 0
    attention_checks_failed: int = 0
    gold_standard_correct: int = 0
    gold_standard_incorrect: int = 0
    errors: List[str] = field(default_factory=list)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    was_blocked: bool = False


class SimulatedUser:
    """Simulates a single user annotating items via the Potato API.

    The SimulatedUser handles:
    - Authentication (login/registration)
    - Fetching annotation items
    - Generating annotations based on strategy
    - Submitting annotations
    - Navigating between items
    - Tracking quality control results
    """

    def __init__(
        self,
        user_config: UserConfig,
        server_url: str,
        gold_standards: Optional[Dict[str, Dict[str, Any]]] = None,
        simulate_wait: bool = False,
        attention_check_fail_rate: float = 0.0,
        respond_fast_rate: float = 0.0,
    ):
        """Initialize simulated user.

        Args:
            user_config: Configuration for this user
            server_url: Base URL of the Potato server
            gold_standards: Optional gold standard answers keyed by instance_id
            simulate_wait: Whether to actually wait between annotations
            attention_check_fail_rate: Rate at which to fail attention checks
            respond_fast_rate: Rate of suspiciously fast responses
        """
        self.config = user_config
        self.server_url = server_url.rstrip("/")
        self.gold_standards = gold_standards or {}
        self.attention_check_fail_rate = attention_check_fail_rate
        self.respond_fast_rate = respond_fast_rate

        # Initialize components
        self.competence = create_competence_profile(user_config.competence)
        self.strategy = self._create_strategy()

        # Create timing model based on simulate_wait setting
        if simulate_wait:
            self.timing = TimingModel(user_config.timing)
        else:
            self.timing = NoWaitTimingModel(user_config.timing)

        # Session and state
        self.session = requests.Session()
        self.logged_in = False
        self.current_instance_id: Optional[str] = None
        self.schemas: List[Dict[str, Any]] = []

        # Results tracking
        self.result = UserSimulationResult(user_id=user_config.user_id)

    def _create_strategy(self) -> AnnotationStrategy:
        """Create the annotation strategy for this user.

        Returns:
            AnnotationStrategy instance
        """
        return create_strategy(
            strategy_type=self.config.strategy,
            llm_config=self.config.llm_config,
            biased_config=self.config.biased_config,
            pattern_config=self.config.pattern_config,
            user_id=self.config.user_id,
        )

    def login(self) -> bool:
        """Login or register the simulated user.

        Attempts to login first, then registers if login fails.

        Returns:
            True if authentication successful
        """
        password = "simulated_password_123"

        try:
            # Try to register first (in case user doesn't exist)
            response = self.session.post(
                f"{self.server_url}/register",
                data={
                    "action": "signup",
                    "email": self.config.user_id,
                    "pass": password,
                },
                allow_redirects=True,
                timeout=30,
            )

            # Now try to login
            response = self.session.post(
                f"{self.server_url}/auth",
                data={
                    "action": "login",
                    "email": self.config.user_id,
                    "pass": password,
                },
                allow_redirects=True,
                timeout=30,
            )

            # Check if we're logged in by trying to access annotate page
            check_response = self.session.get(
                f"{self.server_url}/annotate",
                allow_redirects=False,
                timeout=30,
            )

            # If we get redirected to login, auth failed
            if check_response.status_code == 302:
                location = check_response.headers.get("Location", "")
                if "auth" in location or "login" in location:
                    logger.warning(f"Login failed for {self.config.user_id}")
                    self.result.errors.append("Login failed - redirected to auth")
                    return False

            self.logged_in = True
            logger.debug(f"User {self.config.user_id} logged in successfully")
            return True

        except requests.exceptions.RequestException as e:
            logger.error(f"Login failed for {self.config.user_id}: {e}")
            self.result.errors.append(f"Login failed: {e}")
            return False

    def get_current_instance(self) -> Optional[Dict[str, Any]]:
        """Get the current instance to annotate.

        Returns:
            Instance data dict or None if unavailable
        """
        try:
            response = self.session.get(
                f"{self.server_url}/api/current_instance",
                timeout=30,
            )

            if response.status_code == 200:
                data = response.json()
                self.current_instance_id = data.get("instance_id")

                # Get the actual text content
                if self.current_instance_id:
                    text_response = self.session.get(
                        f"{self.server_url}/api/spans/{self.current_instance_id}",
                        timeout=30,
                    )
                    if text_response.status_code == 200:
                        text_data = text_response.json()
                        data["text"] = text_data.get("text", "")

                return data

            elif response.status_code == 404:
                logger.info(f"No more instances for {self.config.user_id}")
                return None
            else:
                logger.warning(
                    f"Failed to get instance: {response.status_code} - {response.text}"
                )
                return None

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get current instance: {e}")
            self.result.errors.append(f"Get instance failed: {e}")
            return None

    def get_schemas(self) -> List[Dict[str, Any]]:
        """Get annotation schemas from the server.

        Returns:
            List of schema definitions
        """
        try:
            response = self.session.get(
                f"{self.server_url}/api/schemas",
                timeout=30,
            )

            if response.status_code == 200:
                data = response.json()
                # Handle both list and dict formats
                if isinstance(data, dict):
                    if "schemas" in data:
                        self.schemas = (
                            list(data["schemas"].values())
                            if isinstance(data["schemas"], dict)
                            else data["schemas"]
                        )
                    else:
                        self.schemas = list(data.values())
                else:
                    self.schemas = data
                return self.schemas

            logger.warning(f"Failed to get schemas: {response.status_code}")
            return []

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get schemas: {e}")
            self.result.errors.append(f"Get schemas failed: {e}")
            return []

    def generate_annotations(self, instance: Dict[str, Any]) -> Dict[str, Any]:
        """Generate annotations for all schemas.

        Args:
            instance: Instance data including text

        Returns:
            Combined annotation dictionary for all schemas
        """
        instance_id = instance.get("instance_id")
        gold_answer = self.gold_standards.get(instance_id)

        all_annotations = {}

        for schema in self.schemas:
            schema_name = schema.get("name")
            schema_gold = None
            if gold_answer:
                schema_gold = {schema_name: gold_answer.get(schema_name)}

            annotation = self.strategy.generate_annotation(
                instance, schema, self.competence, schema_gold
            )

            all_annotations.update(annotation)

        return all_annotations

    def submit_annotation(
        self,
        instance_id: str,
        annotations: Dict[str, Any],
        response_time: float,
    ) -> bool:
        """Submit annotations for an instance.

        Args:
            instance_id: ID of the instance
            annotations: Annotation data to submit
            response_time: Time taken to annotate

        Returns:
            True if submission successful
        """
        try:
            payload = {
                "instance_id": instance_id,
                "annotations": annotations,
                "span_annotations": [],
                "client_timestamp": datetime.now().isoformat(),
            }

            response = self.session.post(
                f"{self.server_url}/updateinstance",
                json=payload,
                timeout=30,
            )

            if response.status_code == 200:
                result_data = response.json()

                # Create annotation record
                record = AnnotationRecord(
                    instance_id=instance_id,
                    schema_name=",".join(annotations.keys()),
                    annotation=annotations,
                    response_time=response_time,
                    timestamp=datetime.now(),
                )

                # Check for quality control results
                if "qc_result" in result_data:
                    qc_result = result_data["qc_result"]
                    qc_type = qc_result.get("type")

                    if qc_type == "attention_check":
                        record.was_attention_check = True
                        record.attention_check_passed = qc_result.get("passed", False)
                        if record.attention_check_passed:
                            self.result.attention_checks_passed += 1
                        else:
                            self.result.attention_checks_failed += 1

                    elif qc_type == "gold_standard":
                        record.was_gold_standard = True
                        record.gold_standard_correct = qc_result.get("correct", False)
                        if record.gold_standard_correct:
                            self.result.gold_standard_correct += 1
                        else:
                            self.result.gold_standard_incorrect += 1

                # Check for blocking
                if result_data.get("status") == "blocked":
                    self.result.was_blocked = True
                    logger.info(f"User {self.config.user_id} was blocked")

                self.result.annotations.append(record)
                return True

            else:
                logger.warning(
                    f"Annotation submission failed: {response.status_code} - {response.text}"
                )
                self.result.errors.append(f"Submit failed: {response.status_code}")
                return False

        except requests.exceptions.RequestException as e:
            logger.error(f"Submit annotation failed: {e}")
            self.result.errors.append(f"Submit failed: {e}")
            return False

    def navigate_next(self) -> bool:
        """Navigate to the next instance.

        Returns:
            True if navigation successful
        """
        try:
            # POST to /annotate with action=next_instance
            response = self.session.post(
                f"{self.server_url}/annotate",
                data={"action": "next_instance"},
                timeout=30,
            )

            return response.status_code in [200, 302]

        except requests.exceptions.RequestException as e:
            logger.error(f"Navigate next failed: {e}")
            self.result.errors.append(f"Navigate failed: {e}")
            return False

    def run_simulation(
        self, max_annotations: Optional[int] = None
    ) -> UserSimulationResult:
        """Run the full simulation for this user.

        Args:
            max_annotations: Maximum number of annotations (optional)

        Returns:
            UserSimulationResult with all tracking data
        """
        self.result.start_time = datetime.now()
        max_ann = max_annotations if max_annotations is not None else self.config.max_annotations
        annotation_count = 0

        try:
            # Login
            if not self.login():
                logger.warning(f"User {self.config.user_id} failed to login")
                return self.result

            # Get schemas
            if not self.get_schemas():
                logger.warning(f"User {self.config.user_id} failed to get schemas")
                self.result.errors.append("Failed to get schemas")

            # Main annotation loop
            while True:
                # Check if blocked
                if self.result.was_blocked:
                    logger.info(f"User {self.config.user_id} is blocked, stopping")
                    break

                # Check annotation limit
                if max_ann is not None and annotation_count >= max_ann:
                    logger.debug(
                        f"User {self.config.user_id} reached annotation limit ({max_ann})"
                    )
                    break

                # Get current instance
                instance = self.get_current_instance()
                if not instance or not instance.get("instance_id"):
                    logger.info(f"No more instances for {self.config.user_id}")
                    break

                # Generate timing
                response_time = self.timing.get_response_time(self.respond_fast_rate)

                # Wait if configured (NoWaitTimingModel skips actual waiting)
                self.timing.wait(response_time)

                # Generate annotations
                annotations = self.generate_annotations(instance)

                # Submit
                if self.submit_annotation(
                    instance.get("instance_id"),
                    annotations,
                    response_time,
                ):
                    annotation_count += 1
                    logger.debug(
                        f"User {self.config.user_id} annotated {annotation_count} items"
                    )

                # Navigate to next
                if not self.navigate_next():
                    logger.debug(f"User {self.config.user_id} navigation failed")
                    break

        except Exception as e:
            logger.error(f"Simulation error for {self.config.user_id}: {e}")
            self.result.errors.append(f"Simulation error: {e}")

        finally:
            self.result.end_time = datetime.now()
            self.result.total_time = (
                self.result.end_time - self.result.start_time
            ).total_seconds()

        logger.info(
            f"User {self.config.user_id} completed: "
            f"{len(self.result.annotations)} annotations in {self.result.total_time:.1f}s"
        )

        return self.result

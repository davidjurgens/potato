"""
Simulator manager for orchestrating multiple simulated users.

This module provides the SimulatorManager class that manages multiple
SimulatedUser instances, handling parallel execution and result aggregation.
"""

import json
import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Any, Optional

from .config import (
    SimulatorConfig,
    UserConfig,
    CompetenceLevel,
    AnnotationStrategyType,
)
from .user_simulator import SimulatedUser, UserSimulationResult
from .reporting import SimulationReporter

logger = logging.getLogger(__name__)


class SimulatorManager:
    """Orchestrates multiple simulated users.

    The SimulatorManager handles:
    - Generating user configurations based on competence distribution
    - Running simulations in parallel or sequentially
    - Aggregating results across all users
    - Exporting results via SimulationReporter
    """

    def __init__(
        self,
        config: SimulatorConfig,
        server_url: str,
        gold_standards: Optional[Dict[str, Dict[str, Any]]] = None,
    ):
        """Initialize simulator manager.

        Args:
            config: Simulator configuration
            server_url: Base URL of the Potato server
            gold_standards: Optional gold standard answers keyed by instance_id
        """
        self.config = config
        self.server_url = server_url.rstrip("/")
        self.gold_standards = gold_standards or {}

        # Load gold standards from file if specified
        if config.gold_standard_file and not gold_standards:
            self.gold_standards = self._load_gold_standards(config.gold_standard_file)

        # Generate user configs if not provided
        self.user_configs = self._generate_user_configs()

        # Results tracking
        self.results: Dict[str, UserSimulationResult] = {}
        self.reporter = SimulationReporter(config.output_dir)

    def _load_gold_standards(self, filepath: str) -> Dict[str, Dict[str, Any]]:
        """Load gold standards from JSON file.

        Expected format:
        [
            {"id": "instance_001", "label_field": "value", ...},
            ...
        ]

        Args:
            filepath: Path to JSON file

        Returns:
            Gold standards dict keyed by instance ID
        """
        try:
            with open(filepath, "r") as f:
                items = json.load(f)

            gold_standards = {}
            for item in items:
                item_id = item.pop("id", None)
                if item_id:
                    gold_standards[item_id] = item

            logger.info(f"Loaded {len(gold_standards)} gold standards from {filepath}")
            return gold_standards

        except Exception as e:
            logger.warning(f"Failed to load gold standards from {filepath}: {e}")
            return {}

    def _generate_user_configs(self) -> List[UserConfig]:
        """Generate user configurations based on competence distribution.

        If explicit user configs are provided, uses those.
        Otherwise, generates based on user_count and competence_distribution.

        Returns:
            List of UserConfig instances
        """
        if self.config.users:
            return self.config.users

        users = []

        # Get competence distribution
        competence_levels = list(self.config.competence_distribution.keys())
        competence_weights = list(self.config.competence_distribution.values())

        # Normalize weights
        total_weight = sum(competence_weights)
        if total_weight > 0:
            competence_weights = [w / total_weight for w in competence_weights]

        for i in range(self.config.user_count):
            # Select competence level based on distribution
            competence_str = random.choices(
                competence_levels, weights=competence_weights, k=1
            )[0]

            try:
                competence = CompetenceLevel(competence_str)
            except ValueError:
                competence = CompetenceLevel.AVERAGE

            users.append(
                UserConfig(
                    user_id=f"sim_user_{i:04d}",
                    competence=competence,
                    strategy=self.config.strategy,
                    timing=self.config.timing,
                    llm_config=self.config.llm_config,
                    biased_config=self.config.biased_config,
                )
            )

        logger.info(f"Generated {len(users)} user configurations")
        return users

    def run_single_user(
        self, user_config: UserConfig, max_annotations: Optional[int] = None
    ) -> UserSimulationResult:
        """Run simulation for a single user.

        Args:
            user_config: Configuration for the user
            max_annotations: Maximum annotations for this user

        Returns:
            UserSimulationResult with tracking data
        """
        user = SimulatedUser(
            user_config=user_config,
            server_url=self.server_url,
            gold_standards=self.gold_standards,
            simulate_wait=self.config.simulate_wait,
            attention_check_fail_rate=self.config.attention_check_fail_rate,
            respond_fast_rate=self.config.respond_fast_rate,
        )

        result = user.run_simulation(max_annotations)
        self.results[user_config.user_id] = result

        return result

    def run_parallel(
        self, max_annotations_per_user: Optional[int] = None
    ) -> Dict[str, UserSimulationResult]:
        """Run simulation for all users in parallel.

        Args:
            max_annotations_per_user: Maximum annotations per user

        Returns:
            Dict mapping user_id to UserSimulationResult
        """
        logger.info(
            f"Starting parallel simulation with {len(self.user_configs)} users "
            f"({self.config.parallel_users} concurrent)"
        )

        with ThreadPoolExecutor(max_workers=self.config.parallel_users) as executor:
            futures = {}

            for i, user_config in enumerate(self.user_configs):
                # Stagger user starts
                if i > 0 and self.config.delay_between_users > 0:
                    time.sleep(self.config.delay_between_users)

                future = executor.submit(
                    self.run_single_user, user_config, max_annotations_per_user
                )
                futures[future] = user_config.user_id

            # Wait for completion
            completed = 0
            for future in as_completed(futures):
                user_id = futures[future]
                completed += 1
                try:
                    result = future.result()
                    logger.info(
                        f"[{completed}/{len(futures)}] User {user_id} completed: "
                        f"{len(result.annotations)} annotations"
                    )
                except Exception as e:
                    logger.error(f"User {user_id} failed: {e}")

        logger.info(f"Parallel simulation completed: {len(self.results)} users")
        return self.results

    def run_sequential(
        self, max_annotations_per_user: Optional[int] = None
    ) -> Dict[str, UserSimulationResult]:
        """Run simulation for all users sequentially.

        Args:
            max_annotations_per_user: Maximum annotations per user

        Returns:
            Dict mapping user_id to UserSimulationResult
        """
        logger.info(
            f"Starting sequential simulation with {len(self.user_configs)} users"
        )

        for i, user_config in enumerate(self.user_configs):
            result = self.run_single_user(user_config, max_annotations_per_user)
            logger.info(
                f"[{i+1}/{len(self.user_configs)}] User {user_config.user_id} "
                f"completed: {len(result.annotations)} annotations"
            )

        logger.info(f"Sequential simulation completed: {len(self.results)} users")
        return self.results

    def get_summary(self) -> Dict[str, Any]:
        """Get summary statistics for all users.

        Returns:
            Summary dictionary with aggregate statistics
        """
        if not self.results:
            return {"error": "No results available"}

        total_annotations = sum(len(r.annotations) for r in self.results.values())
        total_time = sum(r.total_time for r in self.results.values())

        total_attention_passed = sum(
            r.attention_checks_passed for r in self.results.values()
        )
        total_attention_failed = sum(
            r.attention_checks_failed for r in self.results.values()
        )
        total_gold_correct = sum(
            r.gold_standard_correct for r in self.results.values()
        )
        total_gold_incorrect = sum(
            r.gold_standard_incorrect for r in self.results.values()
        )

        blocked_users = sum(1 for r in self.results.values() if r.was_blocked)
        users_with_errors = sum(1 for r in self.results.values() if r.errors)

        # Calculate response time statistics
        all_response_times = [
            record.response_time
            for result in self.results.values()
            for record in result.annotations
        ]

        response_time_stats = {}
        if all_response_times:
            response_time_stats = {
                "min": min(all_response_times),
                "max": max(all_response_times),
                "mean": sum(all_response_times) / len(all_response_times),
            }

        # Competence level distribution in results
        competence_distribution = {}
        for user_id in self.results:
            for config in self.user_configs:
                if config.user_id == user_id:
                    level = config.competence.value
                    competence_distribution[level] = (
                        competence_distribution.get(level, 0) + 1
                    )
                    break

        return {
            "user_count": len(self.results),
            "total_annotations": total_annotations,
            "total_time_seconds": total_time,
            "average_annotations_per_user": (
                total_annotations / len(self.results) if self.results else 0
            ),
            "average_time_per_user": (
                total_time / len(self.results) if self.results else 0
            ),
            "attention_checks": {
                "passed": total_attention_passed,
                "failed": total_attention_failed,
                "pass_rate": (
                    total_attention_passed
                    / (total_attention_passed + total_attention_failed)
                    if (total_attention_passed + total_attention_failed) > 0
                    else None
                ),
            },
            "gold_standards": {
                "correct": total_gold_correct,
                "incorrect": total_gold_incorrect,
                "accuracy": (
                    total_gold_correct / (total_gold_correct + total_gold_incorrect)
                    if (total_gold_correct + total_gold_incorrect) > 0
                    else None
                ),
            },
            "blocked_users": blocked_users,
            "users_with_errors": users_with_errors,
            "response_time_stats": response_time_stats,
            "competence_distribution": competence_distribution,
            "per_user": {
                user_id: {
                    "annotations": len(r.annotations),
                    "total_time": r.total_time,
                    "attention_passed": r.attention_checks_passed,
                    "attention_failed": r.attention_checks_failed,
                    "gold_correct": r.gold_standard_correct,
                    "gold_incorrect": r.gold_standard_incorrect,
                    "was_blocked": r.was_blocked,
                    "errors": len(r.errors),
                }
                for user_id, r in self.results.items()
            },
        }

    def export_results(self) -> str:
        """Export all results using the reporter.

        Returns:
            Path to the output directory
        """
        self.reporter.export_results(self.results, self.get_summary())
        return self.config.output_dir

    def print_summary(self) -> None:
        """Print a summary of results to stdout."""
        summary = self.get_summary()

        print("\n" + "=" * 60)
        print("SIMULATION SUMMARY")
        print("=" * 60)

        print(f"\nUsers: {summary['user_count']}")
        print(f"Total annotations: {summary['total_annotations']}")
        print(f"Total time: {summary['total_time_seconds']:.1f}s")
        print(
            f"Avg annotations/user: {summary['average_annotations_per_user']:.1f}"
        )
        print(f"Avg time/user: {summary['average_time_per_user']:.1f}s")

        ac = summary["attention_checks"]
        if ac["passed"] or ac["failed"]:
            print(f"\nAttention Checks:")
            print(f"  Passed: {ac['passed']}")
            print(f"  Failed: {ac['failed']}")
            if ac["pass_rate"] is not None:
                print(f"  Pass rate: {ac['pass_rate']:.1%}")

        gs = summary["gold_standards"]
        if gs["correct"] or gs["incorrect"]:
            print(f"\nGold Standards:")
            print(f"  Correct: {gs['correct']}")
            print(f"  Incorrect: {gs['incorrect']}")
            if gs["accuracy"] is not None:
                print(f"  Accuracy: {gs['accuracy']:.1%}")

        if summary["blocked_users"]:
            print(f"\nBlocked users: {summary['blocked_users']}")

        if summary["users_with_errors"]:
            print(f"Users with errors: {summary['users_with_errors']}")

        if summary["competence_distribution"]:
            print(f"\nCompetence distribution:")
            for level, count in summary["competence_distribution"].items():
                print(f"  {level}: {count}")

        print("\n" + "=" * 60)

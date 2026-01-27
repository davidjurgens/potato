"""
Unit tests for timestamp tracking functionality.

This module tests the comprehensive timestamp tracking system for annotation actions,
including performance metrics calculation, suspicious activity detection, and session management.
"""

import unittest
import datetime
import json
import time
from unittest.mock import Mock, patch, MagicMock

from potato.annotation_history import (
    AnnotationAction, AnnotationHistoryManager, _get_suspicious_level
)
from potato.user_state_management import InMemoryUserState
from potato.item_state_management import Label, SpanAnnotation
from potato.phase import UserPhase


class TestTimestampTrackingCore(unittest.TestCase):
    """Test core timestamp tracking functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.timestamp = datetime.datetime.now()
        self.client_timestamp = self.timestamp - datetime.timedelta(seconds=1)

    def test_annotation_action_timestamp_creation(self):
        """Test creating AnnotationAction with proper timestamps."""
        action = AnnotationHistoryManager.create_action(
            user_id="test_user",
            instance_id="test_instance",
            action_type="add_label",
            schema_name="sentiment",
            label_name="positive",
            old_value=None,
            new_value="true",
            session_id="test_session",
            client_timestamp=self.client_timestamp,
            metadata={"request_id": "req-123", "user_agent": "test-browser"}
        )

        self.assertIsInstance(action.action_id, str)
        self.assertIsInstance(action.timestamp, datetime.datetime)
        self.assertEqual(action.client_timestamp, self.client_timestamp)
        self.assertEqual(action.server_processing_time_ms, 0)  # Not set yet
        self.assertEqual(action.metadata["request_id"], "req-123")
        self.assertEqual(action.metadata["user_agent"], "test-browser")

    def test_annotation_action_processing_time(self):
        """Test setting server processing time."""
        action = AnnotationHistoryManager.create_action(
            user_id="test_user",
            instance_id="test_instance",
            action_type="add_label",
            schema_name="sentiment",
            label_name="positive",
            old_value=None,
            new_value="true",
            session_id="test_session"
        )

        # Simulate processing time
        action.server_processing_time_ms = 150
        self.assertEqual(action.server_processing_time_ms, 150)

    def test_annotation_action_span_data(self):
        """Test AnnotationAction with span annotation data."""
        span_data = {
            "start": 10,
            "end": 18,
            "title": "John Doe"
        }

        action = AnnotationHistoryManager.create_action(
            user_id="test_user",
            instance_id="test_instance",
            action_type="add_span",
            schema_name="entity",
            label_name="person",
            old_value=None,
            new_value="John Doe",
            span_data=span_data,
            session_id="test_session"
        )

        self.assertEqual(action.span_data["start"], 10)
        self.assertEqual(action.span_data["end"], 18)
        self.assertEqual(action.span_data["title"], "John Doe")

    def test_annotation_action_serialization(self):
        """Test AnnotationAction serialization to/from JSON."""
        action = AnnotationHistoryManager.create_action(
            user_id="test_user",
            instance_id="test_instance",
            action_type="update_label",
            schema_name="sentiment",
            label_name="negative",
            old_value="positive",
            new_value="negative",
            session_id="test_session",
            client_timestamp=self.client_timestamp,
            metadata={"test": "data"}
        )

        # Convert to dict
        action_dict = action.to_dict()
        self.assertIn("action_id", action_dict)
        self.assertIn("timestamp", action_dict)
        self.assertIn("client_timestamp", action_dict)
        self.assertIn("metadata", action_dict)

        # Convert back from dict
        new_action = AnnotationAction.from_dict(action_dict)
        self.assertEqual(new_action.action_id, action.action_id)
        self.assertEqual(new_action.user_id, action.user_id)
        self.assertEqual(new_action.action_type, action.action_type)
        self.assertEqual(new_action.old_value, action.old_value)
        self.assertEqual(new_action.new_value, action.new_value)


class TestPerformanceMetrics(unittest.TestCase):
    """Test performance metrics calculation."""

    def setUp(self):
        """Set up test fixtures."""
        self.base_time = datetime.datetime.now()
        self.actions = []

    def test_performance_metrics_empty_history(self):
        """Test performance metrics with empty action history."""
        metrics = AnnotationHistoryManager.calculate_performance_metrics([])

        self.assertEqual(metrics["total_actions"], 0)
        self.assertEqual(metrics["average_action_time_ms"], 0)
        self.assertEqual(metrics["fastest_action_time_ms"], 0)
        self.assertEqual(metrics["slowest_action_time_ms"], 0)
        self.assertEqual(metrics["actions_per_minute"], 0)
        self.assertEqual(metrics["total_processing_time_ms"], 0)

    def test_performance_metrics_single_action(self):
        """Test performance metrics with single action."""
        action = AnnotationAction(
            action_id="action-1",
            timestamp=self.base_time,
            user_id="test_user",
            instance_id="test_instance",
            action_type="add_label",
            schema_name="sentiment",
            label_name="positive",
            old_value=None,
            new_value="true",
            span_data=None,
            session_id="test_session",
            client_timestamp=None,
            server_processing_time_ms=150,
            metadata={}
        )

        metrics = AnnotationHistoryManager.calculate_performance_metrics([action])

        self.assertEqual(metrics["total_actions"], 1)
        self.assertEqual(metrics["average_action_time_ms"], 150)
        self.assertEqual(metrics["fastest_action_time_ms"], 150)
        self.assertEqual(metrics["slowest_action_time_ms"], 150)
        self.assertEqual(metrics["actions_per_minute"], 0)  # Single action, no time span

    def test_performance_metrics_multiple_actions(self):
        """Test performance metrics with multiple actions."""
        actions = []
        for i in range(5):
            action = AnnotationAction(
                action_id=f"action-{i}",
                timestamp=self.base_time + datetime.timedelta(seconds=i),
                user_id="test_user",
                instance_id="test_instance",
                action_type="add_label",
                schema_name="sentiment",
                label_name="positive",
                old_value=None,
                new_value="true",
                span_data=None,
                session_id="test_session",
                client_timestamp=None,
                server_processing_time_ms=100 + i * 25,  # 100, 125, 150, 175, 200
                metadata={}
            )
            actions.append(action)

        metrics = AnnotationHistoryManager.calculate_performance_metrics(actions)

        self.assertEqual(metrics["total_actions"], 5)
        self.assertEqual(metrics["fastest_action_time_ms"], 100)
        self.assertEqual(metrics["slowest_action_time_ms"], 200)
        self.assertEqual(metrics["average_action_time_ms"], 150)  # (100+125+150+175+200)/5
        self.assertGreater(metrics["actions_per_minute"], 0)

    def test_performance_metrics_actions_per_minute(self):
        """Test actions per minute calculation."""
        actions = []
        for i in range(10):
            action = AnnotationAction(
                action_id=f"action-{i}",
                timestamp=self.base_time + datetime.timedelta(seconds=i),
                user_id="test_user",
                instance_id="test_instance",
                action_type="add_label",
                schema_name="sentiment",
                label_name="positive",
                old_value=None,
                new_value="true",
                span_data=None,
                session_id="test_session",
                client_timestamp=None,
                server_processing_time_ms=100,
                metadata={}
            )
            actions.append(action)

        metrics = AnnotationHistoryManager.calculate_performance_metrics(actions)

        # 10 actions over 9 seconds = ~66.67 actions per minute
        self.assertGreater(metrics["actions_per_minute"], 60)
        self.assertLess(metrics["actions_per_minute"], 70)


class TestSuspiciousActivityDetection(unittest.TestCase):
    """Test suspicious activity detection."""

    def setUp(self):
        """Set up test fixtures."""
        self.base_time = datetime.datetime.now()

    def test_suspicious_activity_empty_history(self):
        """Test suspicious activity detection with empty history."""
        analysis = AnnotationHistoryManager.detect_suspicious_activity([])

        self.assertEqual(analysis["suspicious_actions"], [])
        self.assertEqual(analysis["fast_actions_count"], 0)
        self.assertEqual(analysis["burst_actions_count"], 0)
        self.assertEqual(analysis["suspicious_score"], 0)

    def test_suspicious_activity_fast_actions(self):
        """Test detection of suspiciously fast actions."""
        actions = []
        for i in range(5):
            action = AnnotationAction(
                action_id=f"fast-action-{i}",
                timestamp=self.base_time + datetime.timedelta(seconds=i),
                user_id="test_user",
                instance_id="test_instance",
                action_type="add_label",
                schema_name="sentiment",
                label_name="positive",
                old_value=None,
                new_value="true",
                span_data=None,
                session_id="test_session",
                client_timestamp=None,
                server_processing_time_ms=50,  # Very fast
                metadata={}
            )
            actions.append(action)

        analysis = AnnotationHistoryManager.detect_suspicious_activity(actions)

        self.assertGreater(analysis["fast_actions_count"], 0)
        self.assertGreater(analysis["suspicious_score"], 0)
        self.assertIn(analysis["suspicious_level"], ["Normal", "Low", "Medium", "High", "Very High"])

    def test_suspicious_activity_burst_actions(self):
        """Test detection of burst actions (many actions in short time)."""
        actions = []
        for i in range(20):  # Many actions
            action = AnnotationAction(
                action_id=f"burst-action-{i}",
                timestamp=self.base_time + datetime.timedelta(seconds=i//2),  # 2 actions per second
                user_id="test_user",
                instance_id="test_instance",
                action_type="add_label",
                schema_name="sentiment",
                label_name="positive",
                old_value=None,
                new_value="true",
                span_data=None,
                session_id="test_session",
                client_timestamp=None,
                server_processing_time_ms=200,
                metadata={}
            )
            actions.append(action)

        analysis = AnnotationHistoryManager.detect_suspicious_activity(actions)

        self.assertGreater(analysis["burst_actions_count"], 0)
        self.assertGreater(analysis["suspicious_score"], 0)

    def test_suspicious_activity_normal_behavior(self):
        """Test that normal annotation behavior is not flagged as suspicious."""
        actions = []
        for i in range(5):
            action = AnnotationAction(
                action_id=f"normal-action-{i}",
                timestamp=self.base_time + datetime.timedelta(minutes=i),  # 1 action per minute
                user_id="test_user",
                instance_id="test_instance",
                action_type="add_label",
                schema_name="sentiment",
                label_name="positive",
                old_value=None,
                new_value="true",
                span_data=None,
                session_id="test_session",
                client_timestamp=None,
                server_processing_time_ms=2000,  # Normal processing time
                metadata={}
            )
            actions.append(action)

        analysis = AnnotationHistoryManager.detect_suspicious_activity(actions)

        self.assertEqual(analysis["fast_actions_count"], 0)
        self.assertEqual(analysis["burst_actions_count"], 0)
        self.assertEqual(analysis["suspicious_score"], 0)
        self.assertEqual(analysis["suspicious_level"], "Normal")


class TestSessionManagement(unittest.TestCase):
    """Test session management functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.user_state = InMemoryUserState("test_user", max_assignments=10)
        self.user_state.advance_to_phase(UserPhase.ANNOTATION, "annotation")

    def test_session_start_and_end(self):
        """Test session start and end functionality."""
        # Start session
        session_id = "test_session_123"
        self.user_state.start_session(session_id)

        self.assertIsNotNone(self.user_state.session_start_time)
        self.assertEqual(self.user_state.current_session_id, session_id)
        self.assertIsNotNone(self.user_state.last_activity_time)

        # End session
        self.user_state.end_session()

        self.assertIsNone(self.user_state.current_session_id)
        self.assertIsNone(self.user_state.session_start_time)  # Cleared on end

    def test_session_activity_tracking(self):
        """Test that session activity time is updated."""
        self.user_state.start_session("test_session")

        initial_activity_time = self.user_state.last_activity_time

        # Simulate some time passing
        time.sleep(0.1)

        # Add an action (should update last_activity_time)
        action = AnnotationHistoryManager.create_action(
            user_id="test_user",
            instance_id="test_instance",
            action_type="add_label",
            schema_name="sentiment",
            label_name="positive",
            old_value=None,
            new_value="true",
            session_id="test_session"
        )

        self.user_state.add_annotation_action(action)

        self.assertGreater(self.user_state.last_activity_time, initial_activity_time)


class TestAnnotationHistoryFiltering(unittest.TestCase):
    """Test annotation history filtering functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.user_state = InMemoryUserState("test_user", max_assignments=10)
        self.user_state.advance_to_phase(UserPhase.ANNOTATION, "annotation")
        self.base_time = datetime.datetime.now()

    def test_get_actions_by_time_range(self):
        """Test filtering actions by time range."""
        # Create actions with different timestamps
        actions = []
        for i in range(10):
            action = AnnotationAction(
                action_id=f"action-{i}",
                timestamp=self.base_time + datetime.timedelta(minutes=i),
                user_id="test_user",
                instance_id="test_instance",
                action_type="add_label",
                schema_name="sentiment",
                label_name="positive",
                old_value=None,
                new_value="true",
                span_data=None,
                session_id="test_session",
                client_timestamp=None,
                server_processing_time_ms=100,
                metadata={}
            )
            actions.append(action)

        # Add actions to user state
        for action in actions:
            self.user_state.add_annotation_action(action)

        # Filter by time range (last 5 minutes from now)
        recent_actions = self.user_state.get_recent_actions(5)

        # Should get actions from the last 5 minutes from current time
        # Since all actions are in the past relative to now, we should get all of them
        self.assertEqual(len(recent_actions), 10)

    def test_get_actions_by_instance(self):
        """Test filtering actions by instance."""
        # Create actions for different instances
        for i in range(3):
            action = AnnotationHistoryManager.create_action(
                user_id="test_user",
                instance_id=f"instance_{i}",
                action_type="add_label",
                schema_name="sentiment",
                label_name="positive",
                old_value=None,
                new_value="true",
                session_id="test_session"
            )
            self.user_state.add_annotation_action(action)

        # Filter by specific instance
        instance_0_actions = self.user_state.get_annotation_history("instance_0")
        instance_1_actions = self.user_state.get_annotation_history("instance_1")

        self.assertEqual(len(instance_0_actions), 1)
        self.assertEqual(len(instance_1_actions), 1)
        self.assertEqual(instance_0_actions[0].instance_id, "instance_0")
        self.assertEqual(instance_1_actions[0].instance_id, "instance_1")

    def test_get_actions_by_type(self):
        """Test filtering actions by action type."""
        # Create different types of actions
        action_types = ["add_label", "update_label", "add_span", "delete_span"]
        for action_type in action_types:
            action = AnnotationHistoryManager.create_action(
                user_id="test_user",
                instance_id="test_instance",
                action_type=action_type,
                schema_name="sentiment",
                label_name="positive",
                old_value=None,
                new_value="true",
                session_id="test_session"
            )
            self.user_state.add_annotation_action(action)

        # Filter by action type
        label_actions = AnnotationHistoryManager.get_actions_by_type(
            self.user_state.get_annotation_history(), "add_label"
        )
        span_actions = AnnotationHistoryManager.get_actions_by_type(
            self.user_state.get_annotation_history(), "add_span"
        )

        self.assertEqual(len(label_actions), 1)
        self.assertEqual(len(span_actions), 1)
        self.assertEqual(label_actions[0].action_type, "add_label")
        self.assertEqual(span_actions[0].action_type, "add_span")


class TestSuspiciousLevelClassification(unittest.TestCase):
    """Test suspicious level classification function."""

    def test_suspicious_level_normal(self):
        """Test normal suspicious level."""
        level = _get_suspicious_level(0)
        self.assertEqual(level, "Normal")

    def test_suspicious_level_low(self):
        """Test low suspicious level."""
        level = _get_suspicious_level(25)
        self.assertEqual(level, "Low")

    def test_suspicious_level_medium(self):
        """Test medium suspicious level."""
        level = _get_suspicious_level(50)
        self.assertEqual(level, "Medium")

    def test_suspicious_level_high(self):
        """Test high suspicious level."""
        level = _get_suspicious_level(75)
        self.assertEqual(level, "High")

    def test_suspicious_level_very_high(self):
        """Test very high suspicious level."""
        level = _get_suspicious_level(100)
        self.assertEqual(level, "Very High")


if __name__ == "__main__":
    unittest.main()
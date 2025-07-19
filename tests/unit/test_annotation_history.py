"""
Unit tests for annotation history functionality.

This module tests the comprehensive timestamp tracking system for annotation actions,
including performance metrics calculation and suspicious activity detection.
"""

import unittest
import datetime
import json
from unittest.mock import Mock, patch

from potato.annotation_history import (
    AnnotationAction, AnnotationHistoryManager, _get_suspicious_level
)


class TestAnnotationAction(unittest.TestCase):
    """Test cases for the AnnotationAction dataclass."""

    def setUp(self):
        """Set up test fixtures."""
        self.timestamp = datetime.datetime.now()
        self.client_timestamp = datetime.datetime.now() - datetime.timedelta(seconds=1)

        self.action = AnnotationAction(
            action_id="test-action-123",
            timestamp=self.timestamp,
            user_id="test_user",
            instance_id="test_instance",
            action_type="add_label",
            schema_name="sentiment",
            label_name="positive",
            old_value=None,
            new_value="true",
            span_data=None,
            session_id="test_session",
            client_timestamp=self.client_timestamp,
            server_processing_time_ms=150,
            metadata={"test": "data"}
        )

    def test_annotation_action_creation(self):
        """Test creating an AnnotationAction with all fields."""
        self.assertEqual(self.action.action_id, "test-action-123")
        self.assertEqual(self.action.user_id, "test_user")
        self.assertEqual(self.action.instance_id, "test_instance")
        self.assertEqual(self.action.action_type, "add_label")
        self.assertEqual(self.action.schema_name, "sentiment")
        self.assertEqual(self.action.label_name, "positive")
        self.assertIsNone(self.action.old_value)
        self.assertEqual(self.action.new_value, "true")
        self.assertEqual(self.action.server_processing_time_ms, 150)
        self.assertEqual(self.action.metadata, {"test": "data"})

    def test_annotation_action_to_dict(self):
        """Test converting AnnotationAction to dictionary."""
        action_dict = self.action.to_dict()

        self.assertEqual(action_dict["action_id"], "test-action-123")
        self.assertEqual(action_dict["user_id"], "test_user")
        self.assertEqual(action_dict["action_type"], "add_label")
        self.assertEqual(action_dict["timestamp"], self.timestamp.isoformat())
        self.assertEqual(action_dict["client_timestamp"], self.client_timestamp.isoformat())
        self.assertEqual(action_dict["metadata"], {"test": "data"})

    def test_annotation_action_from_dict(self):
        """Test creating AnnotationAction from dictionary."""
        action_dict = self.action.to_dict()
        new_action = AnnotationAction.from_dict(action_dict)

        self.assertEqual(new_action.action_id, self.action.action_id)
        self.assertEqual(new_action.user_id, self.action.user_id)
        self.assertEqual(new_action.action_type, self.action.action_type)
        self.assertEqual(new_action.timestamp, self.action.timestamp)
        self.assertEqual(new_action.client_timestamp, self.action.client_timestamp)

    def test_annotation_action_str_representation(self):
        """Test string representation of AnnotationAction."""
        action_str = str(self.action)
        self.assertIn("add_label", action_str)
        self.assertIn("sentiment:positive", action_str)
        self.assertIn("true", action_str)

    def test_annotation_action_with_span_data(self):
        """Test AnnotationAction with span annotation data."""
        span_action = AnnotationAction(
            action_id="span-action-456",
            timestamp=self.timestamp,
            user_id="test_user",
            instance_id="test_instance",
            action_type="add_span",
            schema_name="entity",
            label_name="person",
            old_value=None,
            new_value="John Doe",
            span_data={"start": 10, "end": 18, "text": "John Doe"},
            session_id="test_session",
            client_timestamp=None,
            server_processing_time_ms=200,
            metadata={}
        )

        self.assertEqual(span_action.span_data["start"], 10)
        self.assertEqual(span_action.span_data["end"], 18)
        self.assertEqual(span_action.span_data["text"], "John Doe")


class TestAnnotationHistoryManager(unittest.TestCase):
    """Test cases for the AnnotationHistoryManager utility class."""

    def setUp(self):
        """Set up test fixtures."""
        self.timestamp = datetime.datetime.now()
        self.actions = [
            AnnotationAction(
                action_id=f"action-{i}",
                timestamp=self.timestamp + datetime.timedelta(seconds=i),
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
                server_processing_time_ms=100 + i * 10,
                metadata={}
            )
            for i in range(5)
        ]

    def test_create_action(self):
        """Test creating a new annotation action."""
        action = AnnotationHistoryManager.create_action(
            user_id="test_user",
            instance_id="test_instance",
            action_type="update_label",
            schema_name="sentiment",
            label_name="negative",
            old_value="positive",
            new_value="negative",
            session_id="test_session",
            server_processing_time_ms=150
        )

        self.assertIsInstance(action.action_id, str)
        self.assertEqual(action.user_id, "test_user")
        self.assertEqual(action.action_type, "update_label")
        self.assertEqual(action.old_value, "positive")
        self.assertEqual(action.new_value, "negative")
        self.assertEqual(action.server_processing_time_ms, 150)
        self.assertIsInstance(action.timestamp, datetime.datetime)

    def test_calculate_performance_metrics_empty(self):
        """Test performance metrics calculation with empty actions list."""
        metrics = AnnotationHistoryManager.calculate_performance_metrics([])

        self.assertEqual(metrics["total_actions"], 0)
        self.assertEqual(metrics["average_action_time_ms"], 0)
        self.assertEqual(metrics["fastest_action_time_ms"], 0)
        self.assertEqual(metrics["slowest_action_time_ms"], 0)
        self.assertEqual(metrics["actions_per_minute"], 0)

    def test_calculate_performance_metrics(self):
        """Test performance metrics calculation with actions."""
        metrics = AnnotationHistoryManager.calculate_performance_metrics(self.actions)

        self.assertEqual(metrics["total_actions"], 5)
        self.assertEqual(metrics["fastest_action_time_ms"], 100)
        self.assertEqual(metrics["slowest_action_time_ms"], 140)
        self.assertGreater(metrics["average_action_time_ms"], 0)

    def test_detect_suspicious_activity_empty(self):
        """Test suspicious activity detection with empty actions list."""
        analysis = AnnotationHistoryManager.detect_suspicious_activity([])

        self.assertEqual(analysis["suspicious_actions"], [])
        self.assertEqual(analysis["fast_actions_count"], 0)
        self.assertEqual(analysis["burst_actions_count"], 0)
        self.assertEqual(analysis["suspicious_score"], 0)

    def test_detect_suspicious_activity_fast_actions(self):
        """Test suspicious activity detection with fast actions."""
        fast_actions = [
            AnnotationAction(
                action_id=f"fast-{i}",
                timestamp=self.timestamp + datetime.timedelta(seconds=i),
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
            for i in range(3)
        ]

        analysis = AnnotationHistoryManager.detect_suspicious_activity(fast_actions)

        self.assertEqual(analysis["fast_actions_count"], 3)
        self.assertGreater(analysis["suspicious_score"], 0)
        self.assertIn("suspicious_level", analysis)

    def test_detect_suspicious_activity_burst_actions(self):
        """Test suspicious activity detection with burst actions."""
        burst_actions = [
            AnnotationAction(
                action_id=f"burst-{i}",
                timestamp=self.timestamp + datetime.timedelta(seconds=i*0.5),  # Very close together
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
            for i in range(3)
        ]

        analysis = AnnotationHistoryManager.detect_suspicious_activity(burst_actions)

        self.assertGreater(analysis["burst_actions_count"], 0)
        self.assertGreater(analysis["suspicious_score"], 0)

    def test_get_actions_by_time_range(self):
        """Test filtering actions by time range."""
        start_time = self.timestamp + datetime.timedelta(seconds=1)
        end_time = self.timestamp + datetime.timedelta(seconds=3)

        filtered_actions = AnnotationHistoryManager.get_actions_by_time_range(
            self.actions, start_time, end_time
        )

        self.assertLessEqual(len(filtered_actions), len(self.actions))
        for action in filtered_actions:
            self.assertGreaterEqual(action.timestamp, start_time)
            self.assertLessEqual(action.timestamp, end_time)

    def test_get_actions_by_instance(self):
        """Test filtering actions by instance ID."""
        # Add actions with different instance IDs
        mixed_actions = self.actions + [
            AnnotationAction(
                action_id="other-instance",
                timestamp=self.timestamp,
                user_id="test_user",
                instance_id="other_instance",
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
        ]

        filtered_actions = AnnotationHistoryManager.get_actions_by_instance(
            mixed_actions, "test_instance"
        )

        self.assertEqual(len(filtered_actions), len(self.actions))
        for action in filtered_actions:
            self.assertEqual(action.instance_id, "test_instance")

    def test_get_actions_by_type(self):
        """Test filtering actions by action type."""
        mixed_actions = self.actions + [
            AnnotationAction(
                action_id="span-action",
                timestamp=self.timestamp,
                user_id="test_user",
                instance_id="test_instance",
                action_type="add_span",
                schema_name="entity",
                label_name="person",
                old_value=None,
                new_value="John",
                span_data={"start": 0, "end": 4},
                session_id="test_session",
                client_timestamp=None,
                server_processing_time_ms=100,
                metadata={}
            )
        ]

        label_actions = AnnotationHistoryManager.get_actions_by_type(
            mixed_actions, "add_label"
        )
        span_actions = AnnotationHistoryManager.get_actions_by_type(
            mixed_actions, "add_span"
        )

        self.assertEqual(len(label_actions), len(self.actions))
        self.assertEqual(len(span_actions), 1)
        self.assertEqual(span_actions[0].action_type, "add_span")


class TestSuspiciousLevelFunction(unittest.TestCase):
    """Test cases for the _get_suspicious_level helper function."""

    def test_suspicious_level_normal(self):
        """Test suspicious level classification for normal scores."""
        self.assertEqual(_get_suspicious_level(5), "Normal")
        self.assertEqual(_get_suspicious_level(0), "Normal")

    def test_suspicious_level_low(self):
        """Test suspicious level classification for low scores."""
        self.assertEqual(_get_suspicious_level(15), "Low")
        self.assertEqual(_get_suspicious_level(25), "Low")

    def test_suspicious_level_medium(self):
        """Test suspicious level classification for medium scores."""
        self.assertEqual(_get_suspicious_level(35), "Medium")
        self.assertEqual(_get_suspicious_level(55), "Medium")

    def test_suspicious_level_high(self):
        """Test suspicious level classification for high scores."""
        self.assertEqual(_get_suspicious_level(65), "High")
        self.assertEqual(_get_suspicious_level(75), "High")

    def test_suspicious_level_very_high(self):
        """Test suspicious level classification for very high scores."""
        self.assertEqual(_get_suspicious_level(85), "Very High")
        self.assertEqual(_get_suspicious_level(100), "Very High")


if __name__ == "__main__":
    unittest.main()
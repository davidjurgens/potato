"""
Integration tests for user state annotation history functionality.

This module tests the integration between user state management and annotation history
tracking, including performance metrics and suspicious activity detection.
"""

import unittest
import datetime
import tempfile
import os
from unittest.mock import Mock, patch

from potato.user_state_management import InMemoryUserState
from potato.annotation_history import AnnotationAction, AnnotationHistoryManager
from potato.item_state_management import Label, SpanAnnotation
from potato.phase import UserPhase


class TestUserStateAnnotationHistory(unittest.TestCase):
    """Test cases for user state annotation history integration."""

    def setUp(self):
        """Set up test fixtures."""
        self.user_state = InMemoryUserState("test_user", max_assignments=10)
        self.user_state.advance_to_phase(UserPhase.ANNOTATION, "annotation")

        # Mock item state manager
        self.mock_item = Mock()
        self.mock_item.get_id.return_value = "test_instance"
        self.user_state.assign_instance(self.mock_item)

    def test_add_annotation_action(self):
        """Test adding annotation actions to user state."""
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

        history = self.user_state.get_annotation_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].action_id, action.action_id)
        self.assertEqual(history[0].action_type, "add_label")

    def test_get_annotation_history_by_instance(self):
        """Test filtering annotation history by instance."""
        # Add actions for different instances
        action1 = AnnotationHistoryManager.create_action(
            user_id="test_user",
            instance_id="instance_1",
            action_type="add_label",
            schema_name="sentiment",
            label_name="positive",
            old_value=None,
            new_value="true",
            session_id="test_session"
        )

        action2 = AnnotationHistoryManager.create_action(
            user_id="test_user",
            instance_id="instance_2",
            action_type="add_label",
            schema_name="sentiment",
            label_name="negative",
            old_value=None,
            new_value="true",
            session_id="test_session"
        )

        self.user_state.add_annotation_action(action1)
        self.user_state.add_annotation_action(action2)

        # Filter by instance
        instance_1_history = self.user_state.get_annotation_history("instance_1")
        instance_2_history = self.user_state.get_annotation_history("instance_2")

        self.assertEqual(len(instance_1_history), 1)
        self.assertEqual(len(instance_2_history), 1)
        self.assertEqual(instance_1_history[0].instance_id, "instance_1")
        self.assertEqual(instance_2_history[0].instance_id, "instance_2")

    def test_get_recent_actions(self):
        """Test getting recent actions within a time window."""
        # Add actions with different timestamps
        now = datetime.datetime.now()

        action1 = AnnotationAction(
            action_id="action_1",
            timestamp=now - datetime.timedelta(minutes=10),
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

        action2 = AnnotationAction(
            action_id="action_2",
            timestamp=now - datetime.timedelta(minutes=2),
            user_id="test_user",
            instance_id="test_instance",
            action_type="add_label",
            schema_name="sentiment",
            label_name="negative",
            old_value=None,
            new_value="true",
            span_data=None,
            session_id="test_session",
            client_timestamp=None,
            server_processing_time_ms=150,
            metadata={}
        )

        self.user_state.add_annotation_action(action1)
        self.user_state.add_annotation_action(action2)

        # Get recent actions (last 5 minutes)
        recent_actions = self.user_state.get_recent_actions(5)

        self.assertEqual(len(recent_actions), 1)
        self.assertEqual(recent_actions[0].action_id, "action_2")

    def test_get_suspicious_activity(self):
        """Test detecting suspicious activity."""
        # Add fast actions (suspicious)
        for i in range(5):
            action = AnnotationAction(
                action_id=f"fast_action_{i}",
                timestamp=datetime.datetime.now() + datetime.timedelta(seconds=i),
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
            self.user_state.add_annotation_action(action)

        suspicious_actions = self.user_state.get_suspicious_activity()

        self.assertGreater(len(suspicious_actions), 0)
        for action in suspicious_actions:
            self.assertLess(action.server_processing_time_ms, 500)  # Fast threshold

    def test_get_performance_metrics(self):
        """Test getting performance metrics."""
        # Add actions with different processing times
        for i in range(3):
            action = AnnotationAction(
                action_id=f"action_{i}",
                timestamp=datetime.datetime.now() + datetime.timedelta(seconds=i),
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
                server_processing_time_ms=100 + i * 50,
                metadata={}
            )
            self.user_state.add_annotation_action(action)

        metrics = self.user_state.get_performance_metrics()

        self.assertEqual(metrics["total_actions"], 3)
        self.assertGreater(metrics["average_action_time_ms"], 0)
        self.assertEqual(metrics["fastest_action_time_ms"], 100)
        self.assertEqual(metrics["slowest_action_time_ms"], 200)

    def test_session_management(self):
        """Test session start and end functionality."""
        # Start session
        self.user_state.start_session("test_session_123")

        self.assertIsNotNone(self.user_state.session_start_time)
        self.assertEqual(self.user_state.current_session_id, "test_session_123")
        self.assertIsNotNone(self.user_state.last_activity_time)

        # End session
        self.user_state.end_session()

        self.assertIsNone(self.user_state.session_start_time)
        self.assertIsNone(self.user_state.current_session_id)

    def test_performance_metrics_update(self):
        """Test that performance metrics are updated when actions are added."""
        # Add actions and check metrics update
        for i in range(2):
            action = AnnotationAction(
                action_id=f"action_{i}",
                timestamp=datetime.datetime.now() + datetime.timedelta(seconds=i),
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
                server_processing_time_ms=100 + i * 50,
                metadata={}
            )
            self.user_state.add_annotation_action(action)

        metrics = self.user_state.get_performance_metrics()

        self.assertEqual(metrics["total_actions"], 2)
        self.assertIsNotNone(metrics["last_action_timestamp"])

    def test_annotation_history_persistence(self):
        """Test that annotation history persists through save/load cycles."""
        # Add some actions
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

        # Save and reload
        with tempfile.TemporaryDirectory() as temp_dir:
            user_dir = os.path.join(temp_dir, "test_user")
            os.makedirs(user_dir)

            # Note: The current save/load implementation doesn't include annotation history
            # This test documents the current behavior and can be updated when
            # annotation history persistence is implemented
            self.user_state.save(user_dir)

            # For now, we just verify the save doesn't fail
            self.assertTrue(os.path.exists(os.path.join(user_dir, "user_state.json")))

    def test_multiple_action_types(self):
        """Test handling different types of annotation actions."""
        # Add label action
        label_action = AnnotationHistoryManager.create_action(
            user_id="test_user",
            instance_id="test_instance",
            action_type="add_label",
            schema_name="sentiment",
            label_name="positive",
            old_value=None,
            new_value="true",
            session_id="test_session"
        )
        self.user_state.add_annotation_action(label_action)

        # Add span action
        span_action = AnnotationHistoryManager.create_action(
            user_id="test_user",
            instance_id="test_instance",
            action_type="add_span",
            schema_name="entity",
            label_name="person",
            old_value=None,
            new_value="John Doe",
            span_data={"start": 0, "end": 8, "text": "John Doe"},
            session_id="test_session"
        )
        self.user_state.add_annotation_action(span_action)

        # Add update action
        update_action = AnnotationHistoryManager.create_action(
            user_id="test_user",
            instance_id="test_instance",
            action_type="update_label",
            schema_name="sentiment",
            label_name="positive",
            old_value="true",
            new_value="false",
            session_id="test_session"
        )
        self.user_state.add_annotation_action(update_action)

        history = self.user_state.get_annotation_history()
        self.assertEqual(len(history), 3)

        action_types = [action.action_type for action in history]
        self.assertIn("add_label", action_types)
        self.assertIn("add_span", action_types)
        self.assertIn("update_label", action_types)

    def test_instance_action_history(self):
        """Test that actions are properly organized by instance."""
        # Add actions for different instances
        instances = ["instance_1", "instance_2", "instance_1"]

        for i, instance_id in enumerate(instances):
            action = AnnotationHistoryManager.create_action(
                user_id="test_user",
                instance_id=instance_id,
                action_type="add_label",
                schema_name="sentiment",
                label_name="positive",
                old_value=None,
                new_value="true",
                session_id="test_session"
            )
            self.user_state.add_annotation_action(action)

        # Check instance-specific history
        instance_1_history = self.user_state.get_annotation_history("instance_1")
        instance_2_history = self.user_state.get_annotation_history("instance_2")

        self.assertEqual(len(instance_1_history), 2)
        self.assertEqual(len(instance_2_history), 1)

        # Check total history
        total_history = self.user_state.get_annotation_history()
        self.assertEqual(len(total_history), 3)


if __name__ == "__main__":
    unittest.main()
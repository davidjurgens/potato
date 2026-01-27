"""
Annotation History Module

This module provides comprehensive tracking of all annotation actions with fine-grained
timestamp metadata. It enables performance analysis, quality assurance, and future
undo functionality.

Key Components:
- AnnotationAction: Dataclass representing a single annotation action
- AnnotationHistoryManager: Utility class for creating and analyzing annotation actions
- Performance metrics calculation and suspicious activity detection
"""

import uuid
import datetime
import logging
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, List
import json

logger = logging.getLogger(__name__)


@dataclass
class AnnotationAction:
    """
    Represents a single annotation action with full metadata.

    This class captures all information about an annotation change, including
    timing data, user context, and action details for comprehensive tracking.
    """
    action_id: str  # UUID for unique identification
    timestamp: datetime.datetime  # Precise timestamp
    user_id: str
    instance_id: str
    action_type: str  # 'add_label', 'update_label', 'delete_label', 'add_span', 'update_span', 'delete_span'
    schema_name: str
    label_name: str
    old_value: Optional[Any]  # Previous value (for updates/deletes)
    new_value: Optional[Any]  # New value (for adds/updates)
    span_data: Optional[Dict]  # For span annotations (start, end, text)
    session_id: str  # Browser session identifier
    client_timestamp: Optional[datetime.datetime]  # Frontend timestamp
    server_processing_time_ms: int  # Server processing time
    metadata: Dict[str, Any]  # Additional metadata (browser info, etc.)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        data = asdict(self)
        data['timestamp'] = self.timestamp.isoformat()
        if self.client_timestamp:
            data['client_timestamp'] = self.client_timestamp.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AnnotationAction':
        """Create from dictionary"""
        data['timestamp'] = datetime.datetime.fromisoformat(data['timestamp'])
        if data.get('client_timestamp'):
            data['client_timestamp'] = datetime.datetime.fromisoformat(data['client_timestamp'])
        return cls(**data)

    def __str__(self) -> str:
        """String representation for logging"""
        return f"AnnotationAction({self.action_type}: {self.schema_name}:{self.label_name} = {self.new_value})"


class AnnotationHistoryManager:
    """
    Manages annotation history and provides analytics.

    This class provides utilities for creating annotation actions, calculating
    performance metrics, and detecting suspicious activity patterns.
    """

    @staticmethod
    def create_action(
        user_id: str,
        instance_id: str,
        action_type: str,
        schema_name: str,
        label_name: str,
        old_value: Optional[Any],
        new_value: Optional[Any],
        span_data: Optional[Dict] = None,
        session_id: str = None,
        client_timestamp: Optional[datetime.datetime] = None,
        server_processing_time_ms: int = 0,
        metadata: Optional[Dict] = None
    ) -> AnnotationAction:
        """
        Create a new annotation action with current timestamp.

        Args:
            user_id: The user performing the action
            instance_id: The instance being annotated
            action_type: Type of action (add_label, update_label, etc.)
            schema_name: Name of the annotation schema
            label_name: Name of the specific label
            old_value: Previous value (for updates/deletes)
            new_value: New value (for adds/updates)
            span_data: Span annotation data (start, end, text)
            session_id: Browser session identifier
            client_timestamp: Frontend timestamp
            server_processing_time_ms: Server processing time in milliseconds
            metadata: Additional metadata

        Returns:
            AnnotationAction object with current timestamp
        """
        return AnnotationAction(
            action_id=str(uuid.uuid4()),
            timestamp=datetime.datetime.now(),
            user_id=user_id,
            instance_id=instance_id,
            action_type=action_type,
            schema_name=schema_name,
            label_name=label_name,
            old_value=old_value,
            new_value=new_value,
            span_data=span_data,
            session_id=session_id or "unknown",
            client_timestamp=client_timestamp,
            server_processing_time_ms=server_processing_time_ms,
            metadata=metadata or {}
        )

    @staticmethod
    def calculate_performance_metrics(actions: List[AnnotationAction]) -> Dict[str, Any]:
        """
        Calculate performance metrics from action history.

        Args:
            actions: List of annotation actions to analyze

        Returns:
            Dictionary containing performance metrics
        """
        if not actions:
            return {
                'total_actions': 0,
                'average_action_time_ms': 0,
                'fastest_action_time_ms': 0,
                'slowest_action_time_ms': 0,
                'actions_per_minute': 0,
                'total_processing_time_ms': 0
            }

        processing_times = [a.server_processing_time_ms for a in actions]
        total_time = sum(processing_times)

        # Calculate actions per minute
        if len(actions) > 1:
            time_span = (actions[-1].timestamp - actions[0].timestamp).total_seconds() / 60
            actions_per_minute = len(actions) / time_span if time_span > 0 else 0
        else:
            actions_per_minute = 0

        return {
            'total_actions': len(actions),
            'average_action_time_ms': total_time / len(actions),
            'fastest_action_time_ms': min(processing_times),
            'slowest_action_time_ms': max(processing_times),
            'actions_per_minute': actions_per_minute,
            'total_processing_time_ms': total_time
        }

    @staticmethod
    def detect_suspicious_activity(actions: List[AnnotationAction],
                                 fast_threshold_ms: int = 500,
                                 burst_threshold_seconds: int = 2) -> Dict[str, Any]:
        """
        Detect potentially suspicious annotation activity.

        Args:
            actions: List of annotation actions to analyze
            fast_threshold_ms: Threshold for considering an action "too fast"
            burst_threshold_seconds: Threshold for burst activity detection

        Returns:
            Dictionary containing suspicious activity analysis
        """
        if not actions:
            return {
                'suspicious_actions': [],
                'fast_actions_count': 0,
                'burst_actions_count': 0,
                'suspicious_score': 0
            }

        suspicious_actions = []
        fast_actions = []
        burst_actions = []

        # Detect fast actions
        for action in actions:
            if action.server_processing_time_ms < fast_threshold_ms:
                fast_actions.append(action)
                suspicious_actions.append(action)

        # Detect burst activity (multiple actions in quick succession)
        for i in range(1, len(actions)):
            time_diff = (actions[i].timestamp - actions[i-1].timestamp).total_seconds()
            if time_diff < burst_threshold_seconds:
                burst_actions.append(actions[i])
                if actions[i] not in suspicious_actions:
                    suspicious_actions.append(actions[i])

        # Calculate suspicious score (0-100)
        total_actions = len(actions)
        fast_percentage = (len(fast_actions) / total_actions) * 100 if total_actions > 0 else 0
        burst_percentage = (len(burst_actions) / total_actions) * 100 if total_actions > 0 else 0

        suspicious_score = min(100, (fast_percentage * 0.6) + (burst_percentage * 0.4))

        return {
            'suspicious_actions': suspicious_actions,
            'fast_actions_count': len(fast_actions),
            'burst_actions_count': len(burst_actions),
            'fast_actions_percentage': fast_percentage,
            'burst_actions_percentage': burst_percentage,
            'suspicious_score': suspicious_score,
            'suspicious_level': _get_suspicious_level(suspicious_score)
        }

    @staticmethod
    def get_actions_by_time_range(actions: List[AnnotationAction],
                                 start_time: datetime.datetime,
                                 end_time: datetime.datetime) -> List[AnnotationAction]:
        """
        Filter actions by time range.

        Args:
            actions: List of annotation actions
            start_time: Start of time range
            end_time: End of time range

        Returns:
            Filtered list of actions within the time range
        """
        return [action for action in actions
                if start_time <= action.timestamp <= end_time]

    @staticmethod
    def get_actions_by_instance(actions: List[AnnotationAction],
                               instance_id: str) -> List[AnnotationAction]:
        """
        Filter actions by instance ID.

        Args:
            actions: List of annotation actions
            instance_id: Instance ID to filter by

        Returns:
            Filtered list of actions for the specified instance
        """
        return [action for action in actions if action.instance_id == instance_id]

    @staticmethod
    def get_actions_by_type(actions: List[AnnotationAction],
                           action_type: str) -> List[AnnotationAction]:
        """
        Filter actions by action type.

        Args:
            actions: List of annotation actions
            action_type: Action type to filter by

        Returns:
            Filtered list of actions of the specified type
        """
        return [action for action in actions if action.action_type == action_type]


def _get_suspicious_level(score: float) -> str:
    """Convert suspicious score to level description."""
    if score < 10:
        return "Normal"
    elif score < 30:
        return "Low"
    elif score < 60:
        return "Medium"
    elif score < 80:
        return "High"
    else:
        return "Very High"
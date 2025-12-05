"""
Admin Dashboard Module

This module provides comprehensive admin functionality for the annotation platform,
including dashboard data generation, timing analysis, and configuration management.

The admin dashboard offers:
- Real-time overview of annotation progress and statistics
- Detailed annotator performance metrics and timing analysis
- Instance-level annotation tracking and disagreement analysis
- Configuration management and system state monitoring
- Question and annotation scheme analysis
- User progress tracking and completion statistics
- Comprehensive annotation history tracking and suspicious activity detection
- Performance metrics and quality assurance monitoring
- Session tracking and behavioral analysis

Key Components:
- AdminDashboard: Main class for admin functionality
- AnnotatorTimingData: Data class for annotator timing information
- InstanceData: Data class for instance information and statistics
- Dashboard data generation and analysis functions
- Configuration update and management functions
- AnnotationHistoryAnalyzer: Advanced history analysis and suspicious activity detection

The dashboard provides insights into:
- Overall annotation progress and completion rates
- Individual annotator performance and efficiency
- Annotation quality through disagreement analysis
- System configuration and operational status
- Real-time monitoring of active annotation sessions
- Fine-grained annotation timing and behavioral patterns
- Suspicious activity detection and quality assurance
- Session-based performance analysis

Access Control:
- Admin access is controlled via API key authentication
- Debug mode allows admin access without API key
- All admin endpoints require proper authentication
"""

import json
import logging
import datetime
from typing import Dict, List, Optional, Tuple, Any
from collections import defaultdict, Counter
from dataclasses import dataclass
from flask import request, jsonify, session

from potato.flask_server import (
    config, logger, get_user_state_manager, get_item_state_manager,
    get_users, get_total_annotations
)
from potato.annotation_history import AnnotationHistoryManager, AnnotationAction

@dataclass
class AnnotatorTimingData:
    """
    Data class for annotator timing information.

    This class encapsulates timing metrics for individual annotators,
    including total annotations, working time, and performance statistics.
    Now enhanced with annotation history tracking and suspicious activity detection.
    """
    user_id: str
    total_annotations: int
    total_seconds: int
    average_seconds_per_annotation: float
    last_activity: Optional[datetime.datetime]
    current_instance_time: Optional[int]
    annotations_per_hour: float
    phase: str
    has_assignments: bool
    remaining_assignments: bool

    # Annotation history metrics
    total_actions: int
    average_action_time_ms: float
    fastest_action_time_ms: int
    slowest_action_time_ms: int
    actions_per_minute: float
    suspicious_score: float
    suspicious_level: str
    fast_actions_count: int
    burst_actions_count: int
    session_start_time: Optional[datetime.datetime]
    current_session_duration_minutes: Optional[float]
    recent_actions_count: int  # Actions in last 5 minutes

    # Training metrics
    training_completed: bool
    training_correct_answers: int
    training_total_attempts: int
    training_pass_rate: float
    training_current_question: int
    training_total_questions: int

@dataclass
class InstanceData:
    """
    Data class for instance information.

    This class encapsulates information about annotation instances,
    including annotation counts, disagreement scores, and annotator lists.
    """
    id: str
    text: str
    displayed_text: str
    annotation_count: int
    completion_percentage: float
    most_frequent_label: Optional[str]
    label_disagreement: float
    annotators: List[str]
    num_ai_instance: int
    average_time_per_annotation: Optional[float]

class AdminDashboard:
    """
    Main class for admin dashboard functionality.

    This class provides comprehensive admin features including dashboard
    data generation, timing analysis, configuration management, and
    system monitoring capabilities.
    """

    def __init__(self):
        """Initialize the admin dashboard."""
        self.logger = logging.getLogger(__name__)

    def check_admin_access(self) -> bool:
        """
        Check if the current request has admin access via API key.

        Returns:
            bool: True if admin access is granted, False otherwise
        """
        api_key = request.headers.get('X-API-Key')
        if not config.get("debug", False) and api_key != "admin_api_key":
            return False
        return True

    def get_dashboard_overview(self) -> Dict[str, Any]:
        """
        Get comprehensive dashboard overview data.

        This method generates a complete overview of the annotation system,
        including user statistics, annotation progress, and system configuration.

        Returns:
            Dict containing overview statistics with the following structure:
            - overview: User counts, annotation counts, completion percentages
            - config: System configuration and settings

        Side Effects:
            - Logs errors if data generation fails
        """
        if not self.check_admin_access():
            return {"error": "Admin access required"}, 403

        try:
            usm = get_user_state_manager()
            ism = get_item_state_manager()

            # Get all users and their states
            users = get_users()
            total_annotations = get_total_annotations()

            # Calculate user statistics
            active_users = 0
            completed_users = 0
            total_working_time = 0

            for username in users:
                user_state = usm.get_user_state(username)
                if user_state:
                    if user_state.get_phase().value == "ANNOTATION":
                        active_users += 1
                    elif user_state.get_phase().value == "DONE":
                        completed_users += 1

                    # Get timing data
                    timing_data = self._get_annotator_timing_data(username)
                    if timing_data:
                        total_working_time += timing_data.total_seconds

            # Get item statistics
            items = ism.items()
            items_with_annotations = 0
            total_assignments = 0

            for item in items:
                item_id = item.get_id()
                annotators = ism.get_annotators_for_item(item_id)
                if annotators:
                    items_with_annotations += 1
                    total_assignments += len(annotators)

            # Calculate completion percentages
            total_items = len(items)
            completion_percentage = (items_with_annotations / total_items * 100) if total_items > 0 else 0

            # Format total working time
            hours = total_working_time // 3600
            minutes = (total_working_time % 3600) // 60
            formatted_time = f"{hours}h {minutes}m"

            return {
                "overview": {
                    "total_users": len(users),
                    "active_users": active_users,
                    "completed_users": completed_users,
                    "total_annotations": total_annotations,
                    "total_items": total_items,
                    "items_with_annotations": items_with_annotations,
                    "completion_percentage": round(completion_percentage, 1),
                    "total_assignments": total_assignments,
                    "total_working_time": formatted_time,
                    "average_annotations_per_item": round(total_annotations / total_items, 1) if total_items > 0 else 0
                },
                "config": {
                    "annotation_task_name": config.get("annotation_task_name", "Unknown"),
                    "max_annotations_per_user": config.get("max_annotations_per_user", "Unlimited"),
                    "max_annotations_per_item": config.get("max_annotations_per_item", "Unlimited"),
                    "assignment_strategy": config.get("assignment_strategy", "fixed_order"),
                    "debug_mode": config.get("debug", False)
                }
            }

        except Exception as e:
            self.logger.error(f"Error getting dashboard overview: {e}")
            return {"error": f"Failed to get dashboard overview: {str(e)}"}, 500

    def get_annotators_data(self) -> Dict[str, Any]:
        """
        Get detailed annotator data including timing information.

        Returns:
            Dict containing annotator data with timing analysis
        """
        if not self.check_admin_access():
            return {"error": "Admin access required"}, 403

        try:
            usm = get_user_state_manager()
            users = get_users()
            annotators_data = []


            for username in users:
                user_state = usm.get_user_state(username)
                if user_state:
                    timing_data = self._get_annotator_timing_data(username)
                    if timing_data:
                        annotators_data.append({
                            "user_id": timing_data.user_id,
                            "total_annotations": timing_data.total_annotations,
                            "completion_percentage": self._calculate_completion_percentage(timing_data.user_id),
                            "total_seconds": timing_data.total_seconds,
                            "average_seconds_per_annotation": timing_data.average_seconds_per_annotation,
                            "annotations_per_hour": timing_data.annotations_per_hour,
                            "phase": timing_data.phase,
                            "has_assignments": timing_data.has_assignments,
                            "remaining_assignments": timing_data.remaining_assignments,
                            "last_activity": timing_data.last_activity.isoformat() if timing_data.last_activity else None,
                            "current_instance_time": timing_data.current_instance_time,

                            # NEW: Annotation history metrics
                            "total_actions": timing_data.total_actions,
                            "average_action_time_ms": timing_data.average_action_time_ms,
                            "fastest_action_time_ms": timing_data.fastest_action_time_ms if timing_data.fastest_action_time_ms != float('inf') else None,
                            "slowest_action_time_ms": timing_data.slowest_action_time_ms,
                            "actions_per_minute": timing_data.actions_per_minute,
                            "suspicious_score": timing_data.suspicious_score,
                            "suspicious_level": timing_data.suspicious_level,
                            "fast_actions_count": timing_data.fast_actions_count,
                            "burst_actions_count": timing_data.burst_actions_count,
                            "session_start_time": timing_data.session_start_time.isoformat() if timing_data.session_start_time else None,
                            "current_session_duration_minutes": timing_data.current_session_duration_minutes,
                            "recent_actions_count": timing_data.recent_actions_count,

                            # Training metrics
                            "training_completed": timing_data.training_completed,
                            "training_correct_answers": timing_data.training_correct_answers,
                            "training_total_attempts": timing_data.training_total_attempts,
                            "training_pass_rate": round(timing_data.training_pass_rate, 2),
                            "training_current_question": timing_data.training_current_question,
                            "training_total_questions": timing_data.training_total_questions
                        })

            # Sort by suspicious score (highest first)
            annotators_data.sort(key=lambda x: x["suspicious_score"], reverse=True)

            return {
                "total_annotators": len(annotators_data),
                "annotators": annotators_data,
                "summary": {
                    "high_suspicious_count": len([a for a in annotators_data if a["suspicious_level"] in ["High", "Very High"]]),
                    "medium_suspicious_count": len([a for a in annotators_data if a["suspicious_level"] == "Medium"]),
                    "low_suspicious_count": len([a for a in annotators_data if a["suspicious_level"] == "Low"]),
                    "normal_count": len([a for a in annotators_data if a["suspicious_level"] == "Normal"]),
                    "average_suspicious_score": sum(a["suspicious_score"] for a in annotators_data) / len(annotators_data) if annotators_data else 0
                }
            }

        except Exception as e:
            self.logger.error(f"Error getting annotators data: {e}")
            return {"error": f"Failed to get annotators data: {str(e)}"}, 500

    def get_annotation_history_data(self, user_id: Optional[str] = None,
                                   instance_id: Optional[str] = None,
                                   minutes: Optional[int] = None) -> Dict[str, Any]:
        """
        Get detailed annotation history data with filtering options.

        Args:
            user_id: Optional user ID to filter by
            instance_id: Optional instance ID to filter by
            minutes: Optional time window in minutes

        Returns:
            Dict containing annotation history data
        """
        if not self.check_admin_access():
            return {"error": "Admin access required"}, 403

        try:
            usm = get_user_state_manager()

            if user_id:
                # Get history for specific user
                user_state = usm.get_user_state(user_id)
                if not user_state:
                    return {"error": f"User {user_id} not found"}, 404

                actions = user_state.get_annotation_history(instance_id)
                if minutes:
                    actions = user_state.get_recent_actions(minutes)

                return self._format_annotation_history(actions, user_id)
            else:
                # Get history for all users
                all_actions = []
                users = get_users()

                for username in users:
                    user_state = usm.get_user_state(username)
                    if user_state:
                        user_actions = user_state.get_annotation_history(instance_id)
                        if minutes:
                            user_actions = user_state.get_recent_actions(minutes)
                        all_actions.extend(user_actions)

                return self._format_annotation_history(all_actions, "all_users")

        except Exception as e:
            self.logger.error(f"Error getting annotation history data: {e}")
            return {"error": f"Failed to get annotation history data: {str(e)}"}, 500

    def get_suspicious_activity_data(self) -> Dict[str, Any]:
        """
        Get comprehensive suspicious activity analysis.

        Returns:
            Dict containing suspicious activity data
        """
        if not self.check_admin_access():
            return {"error": "Admin access required"}, 403

        try:
            usm = get_user_state_manager()
            users = get_users()
            suspicious_data = []

            for username in users:
                user_state = usm.get_user_state(username)
                if user_state:
                    suspicious_actions = user_state.get_suspicious_activity()
                    if suspicious_actions:
                        suspicious_data.append({
                            "user_id": username,
                            "suspicious_actions_count": len(suspicious_actions),
                            "suspicious_actions": [
                                {
                                    "action_id": action.action_id,
                                    "timestamp": action.timestamp.isoformat(),
                                    "instance_id": action.instance_id,
                                    "action_type": action.action_type,
                                    "schema_name": action.schema_name,
                                    "label_name": action.label_name,
                                    "server_processing_time_ms": action.server_processing_time_ms,
                                    "session_id": action.session_id
                                }
                                for action in suspicious_actions[:10]  # Limit to 10 most recent
                            ]
                        })

            return {
                "total_users_with_suspicious_activity": len(suspicious_data),
                "suspicious_activity": suspicious_data
            }

        except Exception as e:
            self.logger.error(f"Error getting suspicious activity data: {e}")
            return {"error": f"Failed to get suspicious activity data: {str(e)}"}, 500

    def get_instances_data(self, page: int = 1, page_size: int = 25,
                          sort_by: str = "annotation_count", sort_order: str = "desc",
                          filter_completion: Optional[str] = None) -> Dict[str, Any]:
        """
        Get paginated instances data with sorting and filtering.

        Args:
            page: Page number (1-based)
            page_size: Number of instances per page
            sort_by: Field to sort by (annotation_count, completion_percentage, disagreement, id)
            sort_order: Sort order (asc, desc)
            filter_completion: Filter by completion status (completed, incomplete, all)

        Returns:
            Dict containing paginated instances data
        """
        if not self.check_admin_access():
            return {"error": "Admin access required"}, 403

        try:
            ism = get_item_state_manager()
            items = ism.items()

            # Convert items to InstanceData objects
            instances_data = []
            for item in items:
                item_id = item.get_id()
                annotators = ism.get_annotators_for_item(item_id)
                annotation_count = len(annotators) if annotators else 0

                # Calculate completion percentage
                max_annotations = config.get("max_annotations_per_item", -1)
                if max_annotations > 0:
                    completion_percentage = min(100, (annotation_count / max_annotations) * 100)
                else:
                    completion_percentage = 100 if annotation_count > 0 else 0

                # Calculate most frequent label and disagreement
                most_frequent_label, disagreement = self._calculate_label_statistics(item_id)

                # Calculate average time per annotation
                avg_time = self._calculate_average_time_per_annotation(item_id)

                instance_data = InstanceData(
                    id=item_id,
                    text=item.get_text(),
                    displayed_text=item.get_displayed_text(),
                    annotation_count=annotation_count,
                    completion_percentage=completion_percentage,
                    most_frequent_label=most_frequent_label,
                    label_disagreement=disagreement,
                    annotators=list(annotators) if annotators else [],
                    average_time_per_annotation=avg_time,
                    num_ai_instance=self._calculate_total_instance_ai(item_id)
                )
                instances_data.append(instance_data)

                print("fiwejfoijweoijfew ", instance_data)

            # Apply filters
            if filter_completion == "completed":
                instances_data = [i for i in instances_data if i.completion_percentage >= 100]
            elif filter_completion == "incomplete":
                instances_data = [i for i in instances_data if i.completion_percentage < 100]

            # Apply sorting
            reverse = sort_order.lower() == "desc"
            if sort_by == "annotation_count":
                instances_data.sort(key=lambda x: x.annotation_count, reverse=reverse)
            elif sort_by == "completion_percentage":
                instances_data.sort(key=lambda x: x.completion_percentage, reverse=reverse)
            elif sort_by == "disagreement":
                instances_data.sort(key=lambda x: x.label_disagreement, reverse=reverse)
            elif sort_by == "id":
                instances_data.sort(key=lambda x: x.id, reverse=reverse)
            elif sort_by == "average_time":
                instances_data.sort(key=lambda x: x.average_time_per_annotation or 0, reverse=reverse)

            # Apply pagination
            total_instances = len(instances_data)
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            paginated_instances = instances_data[start_idx:end_idx]

            # Convert to serializable format
            serialized_instances = []
            for instance in paginated_instances:
                serialized_instances.append({
                    "id": instance.id,
                    "text": instance.text[:100] + "..." if len(instance.text) > 100 else instance.text,
                    "displayed_text": instance.displayed_text[:100] + "..." if len(instance.displayed_text) > 100 else instance.displayed_text,
                    "annotation_count": instance.annotation_count,
                    "completion_percentage": round(instance.completion_percentage, 1),
                    "most_frequent_label": instance.most_frequent_label,
                    "label_disagreement": round(instance.label_disagreement, 2),
                    "annotators": instance.annotators,
                    "num_ai_instance": instance.num_ai_instance,
                    "average_time_per_annotation": self._format_seconds(instance.average_time_per_annotation) if instance.average_time_per_annotation else None
                })

            return {
                "instances": serialized_instances,
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "total_instances": total_instances,
                    "total_pages": (total_instances + page_size - 1) // page_size,
                    "has_next": end_idx < total_instances,
                    "has_prev": page > 1
                },
                "summary": {
                    "completed_instances": len([i for i in instances_data if i.completion_percentage >= 100]),
                    "incomplete_instances": len([i for i in instances_data if i.completion_percentage < 100]),
                    "average_annotations_per_instance": round(sum(i.annotation_count for i in instances_data) / len(instances_data), 1) if instances_data else 0,
                    "average_disagreement": round(sum(i.label_disagreement for i in instances_data) / len(instances_data), 2) if instances_data else 0
                }
            }

        except Exception as e:
            self.logger.error(f"Error getting instances data: {e}")
            return {"error": f"Failed to get instances data: {str(e)}"}, 500

    def update_config(self, config_updates: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update system configuration.

        Args:
            config_updates: Dictionary of configuration updates

        Returns:
            Dict containing update result
        """
        if not self.check_admin_access():
            return {"error": "Admin access required"}, 403

        try:
            # Validate and apply updates
            updated_fields = []

            for key, value in config_updates.items():
                if key in ["max_annotations_per_user", "max_annotations_per_item"]:
                    if isinstance(value, int) and value >= -1:
                        config[key] = value
                        updated_fields.append(key)
                    else:
                        return {"error": f"Invalid value for {key}: must be integer >= -1"}, 400

                elif key == "assignment_strategy":
                    valid_strategies = ["random", "fixed_order", "least_annotated", "max_diversity", "active_learning", "llm_confidence"]
                    if value in valid_strategies:
                        config[key] = value
                        updated_fields.append(key)
                    else:
                        return {"error": f"Invalid assignment strategy: {value}"}, 400

            return {
                "status": "success",
                "message": f"Updated configuration fields: {', '.join(updated_fields)}",
                "updated_fields": updated_fields
            }

        except Exception as e:
            self.logger.error(f"Error updating config: {e}")
            return {"error": f"Failed to update config: {str(e)}"}, 500

    def get_questions_data(self) -> Dict[str, Any]:
        """
        Get aggregate analysis data for each annotation schema/question.

        Returns:
            Dict containing questions data with visualizations for different annotation types
        """
        if not self.check_admin_access():
            return {"error": "Admin access required"}, 403

        try:
            ism = get_item_state_manager()
            annotation_schemes = config.get("annotation_schemes", [])
            questions_data = []

            # Get all users to collect their annotations
            users = get_users()

            for scheme in annotation_schemes:
                scheme_name = scheme.get("name", "Unknown")
                annotation_type = scheme.get("annotation_type", "unknown")

                # Collect all annotations for this scheme
                all_annotations = []
                item_annotations = {}

                for item in ism.items():
                    item_id = item.get_id()
                    item_annotations[item_id] = []

                    for username in users:
                        user_state = get_user_state_manager().get_user_state(username)
                        if user_state:
                            # Get label annotations for this user and item
                            label_annotations = user_state.get_label_annotations(item_id)
                            for label, value in label_annotations.items():
                                if hasattr(label, 'schema_name') and label.schema_name == scheme_name:
                                    all_annotations.append(value)
                                    item_annotations[item_id].append(value)
                                elif isinstance(label, str) and label == scheme_name:
                                    all_annotations.append(value)
                                    item_annotations[item_id].append(value)

                # Generate analysis based on annotation type
                analysis = self._analyze_annotation_scheme(
                    annotation_type, scheme, all_annotations, item_annotations
                )

                questions_data.append({
                    "name": scheme_name,
                    "type": annotation_type,
                    "description": scheme.get("description", ""),
                    "total_annotations": len(all_annotations),
                    "items_with_annotations": len([item_id for item_id, annotations in item_annotations.items() if annotations]),
                    "analysis": analysis
                })

            return {
                "questions": questions_data,
                "summary": {
                    "total_questions": len(questions_data),
                    "total_annotations": sum(q["total_annotations"] for q in questions_data),
                    "question_types": list(set(q["type"] for q in questions_data))
                }
            }

        except Exception as e:
            self.logger.error(f"Error getting questions data: {e}")
            return {"error": f"Failed to get questions data: {str(e)}"}, 500

    def _analyze_annotation_scheme(self, annotation_type: str, scheme: dict,
                                 all_annotations: list, item_annotations: dict) -> dict:
        """
        Analyze annotations based on their type and generate appropriate visualizations.
        """
        if not all_annotations:
            return {"error": "No annotations found"}

        analysis = {
            "type": annotation_type,
            "total_count": len(all_annotations)
        }

        if annotation_type in ["radio", "select"]:
            # Categorical data - show histogram
            label_counts = Counter(all_annotations)
            labels = scheme.get("labels", [])

            analysis.update({
                "visualization_type": "histogram",
                "data": {
                    "labels": labels,
                    "counts": [label_counts.get(label, 0) for label in labels],
                    "percentages": [round(label_counts.get(label, 0) / len(all_annotations) * 100, 1)
                                  for label in labels]
                },
                "most_common": label_counts.most_common(1)[0] if label_counts else None,
                "agreement_score": self._calculate_agreement_score(item_annotations)
            })

        elif annotation_type == "multiselect":
            # Multi-label data - show label frequency and co-occurrence
            label_counts = Counter()
            co_occurrence = defaultdict(int)
            labels = scheme.get("labels", [])

            for annotations in item_annotations.values():
                if isinstance(annotations, list):
                    # Count individual labels
                    for annotation in annotations:
                        if isinstance(annotation, list):
                            for label in annotation:
                                label_counts[label] += 1

                    # Count co-occurrences
                    for i, annotation1 in enumerate(annotations):
                        if isinstance(annotation1, list):
                            for j, annotation2 in enumerate(annotations):
                                if i != j and isinstance(annotation2, list):
                                    for label1 in annotation1:
                                        for label2 in annotation2:
                                            if label1 < label2:
                                                co_occurrence[(label1, label2)] += 1

            analysis.update({
                "visualization_type": "multiselect_analysis",
                "data": {
                    "labels": labels,
                    "counts": [label_counts.get(label, 0) for label in labels],
                    "percentages": [round(label_counts.get(label, 0) / len(item_annotations) * 100, 1)
                                  for label in labels],
                    "co_occurrence": dict(co_occurrence)
                },
                "most_common": label_counts.most_common(3) if label_counts else [],
                "average_labels_per_item": round(sum(len(ann) if isinstance(ann, list) else 1
                                                    for anns in item_annotations.values()
                                                    for ann in anns) / len(all_annotations), 2)
            })

        elif annotation_type in ["likert", "number", "slider"]:
            # Numeric data - show distribution and statistics
            numeric_values = []
            for value in all_annotations:
                try:
                    if isinstance(value, (int, float)):
                        numeric_values.append(float(value))
                    elif isinstance(value, str) and value.replace('.', '').replace('-', '').isdigit():
                        numeric_values.append(float(value))
                except (ValueError, TypeError):
                    continue

            if numeric_values:
                analysis.update({
                    "visualization_type": "distribution",
                    "data": {
                        "values": numeric_values,
                        "bins": self._create_histogram_bins(numeric_values, scheme),
                        "statistics": {
                            "mean": round(sum(numeric_values) / len(numeric_values), 2),
                            "median": round(sorted(numeric_values)[len(numeric_values)//2], 2),
                            "min": min(numeric_values),
                            "max": max(numeric_values),
                            "std": round((sum((x - sum(numeric_values)/len(numeric_values))**2
                                            for x in numeric_values) / len(numeric_values))**0.5, 2)
                        }
                    },
                    "range": scheme.get("min", 0) if "min" in scheme else None,
                    "max": scheme.get("max", 10) if "max" in scheme else None
                })
            else:
                analysis["error"] = "No valid numeric values found"

        elif annotation_type == "text":
            # Text data - show length distribution and common patterns
            text_lengths = []
            word_counts = []
            common_words = Counter()

            for value in all_annotations:
                if isinstance(value, str) and value.strip():
                    text_lengths.append(len(value))
                    words = value.lower().split()
                    word_counts.append(len(words))
                    common_words.update(words)

            if text_lengths:
                analysis.update({
                    "visualization_type": "text_analysis",
                    "data": {
                        "lengths": text_lengths,
                        "word_counts": word_counts,
                        "common_words": common_words.most_common(10),
                        "statistics": {
                            "avg_length": round(sum(text_lengths) / len(text_lengths), 1),
                            "avg_words": round(sum(word_counts) / len(word_counts), 1),
                            "min_length": min(text_lengths),
                            "max_length": max(text_lengths),
                            "empty_responses": len([v for v in all_annotations
                                                  if not isinstance(v, str) or not v.strip()])
                        }
                    }
                })
            else:
                analysis["error"] = "No valid text responses found"

        elif annotation_type == "span":
            # Span data - show coverage and overlap statistics
            span_counts = []
            total_spans = 0

            for annotations in item_annotations.values():
                if isinstance(annotations, list):
                    for annotation in annotations:
                        if isinstance(annotation, list):
                            span_counts.append(len(annotation))
                            total_spans += len(annotation)

            if span_counts:
                analysis.update({
                    "visualization_type": "span_analysis",
                    "data": {
                        "span_counts": span_counts,
                        "total_spans": total_spans,
                        "statistics": {
                            "avg_spans_per_item": round(sum(span_counts) / len(span_counts), 2),
                            "items_with_spans": len([c for c in span_counts if c > 0]),
                            "max_spans": max(span_counts) if span_counts else 0,
                            "min_spans": min(span_counts) if span_counts else 0
                        }
                    }
                })
            else:
                analysis["error"] = "No valid span annotations found"

        else:
            analysis["error"] = f"Unsupported annotation type: {annotation_type}"

        return analysis

    def _calculate_agreement_score(self, item_annotations: dict) -> float:
        """Calculate agreement score for categorical annotations."""
        if not item_annotations:
            return 0.0

        agreement_scores = []
        for annotations in item_annotations.values():
            if len(annotations) > 1:
                # Calculate percentage of most common annotation
                counter = Counter(annotations)
                most_common_count = counter.most_common(1)[0][1]
                agreement_scores.append(most_common_count / len(annotations))

        return round(sum(agreement_scores) / len(agreement_scores) * 100, 1) if agreement_scores else 0.0

    def _create_histogram_bins(self, values: list, scheme: dict) -> dict:
        """Create histogram bins for numeric data."""
        if not values:
            return {"bins": [], "counts": []}

        min_val = scheme.get("min", min(values))
        max_val = scheme.get("max", max(values))

        # Create 10 bins
        bin_size = (max_val - min_val) / 10
        bins = [min_val + i * bin_size for i in range(11)]
        counts = [0] * 10

        for value in values:
            bin_index = min(int((value - min_val) / bin_size), 9)
            counts[bin_index] += 1

        return {
            "bins": [round(b, 2) for b in bins],
            "counts": counts
        }

    def _get_annotator_timing_data(self, user_id: str) -> Optional[AnnotatorTimingData]:
        """
        Get timing data for a specific annotator.

        Args:
            user_id: The user ID to get timing data for

        Returns:
            AnnotatorTimingData object or None if user not found
        """
        try:
            usm = get_user_state_manager()
            user_state = usm.get_user_state(user_id)

            if not user_state:
                return None

            # Get basic user info
            total_annotations = len(user_state.get_all_annotations())
            phase = str(user_state.get_phase())
            has_assignments = user_state.has_assignments()
            remaining_assignments = user_state.has_remaining_assignments()

            # Calculate timing data
            total_seconds = 0
            instance_times = []

            for instance_id, behavioral_data in user_state.instance_id_to_behavioral_data.items():
                time_string = behavioral_data.get("time_string")
                if time_string:
                    parsed_time = user_state.parse_time_string(time_string)
                    if parsed_time:
                        instance_seconds = parsed_time["total_seconds"]
                        total_seconds += instance_seconds
                        instance_times.append(instance_seconds)

            # Calculate averages
            average_seconds_per_annotation = total_seconds / total_annotations if total_annotations > 0 else 0
            annotations_per_hour = (total_annotations * 3600) / total_seconds if total_seconds > 0 else 0

            # Get current instance time (if any)
            current_instance_time = None
            current_instance = user_state.get_current_instance()
            if current_instance:
                current_instance_id = current_instance.get_id()
                current_behavioral = user_state.instance_id_to_behavioral_data.get(current_instance_id, {})
                current_time_string = current_behavioral.get("time_string")
                if current_time_string:
                    parsed_current = user_state.parse_time_string(current_time_string)
                    if parsed_current:
                        current_instance_time = parsed_current["total_seconds"]

            # Estimate last activity (for now, use current time - this could be enhanced)
            last_activity = datetime.datetime.now()

            # NEW: Get annotation history metrics
            performance_metrics = user_state.get_performance_metrics()
            suspicious_analysis = AnnotationHistoryManager.detect_suspicious_activity(
                user_state.get_annotation_history()
            )
            recent_actions = user_state.get_recent_actions(5)  # Last 5 minutes

            # Calculate session duration
            current_session_duration_minutes = None
            if user_state.session_start_time:
                duration = datetime.datetime.now() - user_state.session_start_time
                current_session_duration_minutes = duration.total_seconds() / 60

            # Get training statistics
            training_state = user_state.get_training_state()
            training_completed = training_state.is_passed() if training_state else False
            training_correct_answers = training_state.get_correct_answer_count() if training_state else 0
            training_total_attempts = training_state.get_total_attempts() if training_state else 0
            training_pass_rate = (training_correct_answers / training_total_attempts * 100) if training_total_attempts > 0 else 0
            training_current_question = training_state.get_current_question_index() if training_state else 0
            training_total_questions = len(training_state.get_training_instances()) if training_state else 0

            return AnnotatorTimingData(
                user_id=user_id,
                total_annotations=total_annotations,
                total_seconds=total_seconds,
                average_seconds_per_annotation=average_seconds_per_annotation,
                last_activity=last_activity,
                current_instance_time=current_instance_time,
                annotations_per_hour=annotations_per_hour,
                phase=phase,
                has_assignments=has_assignments,
                remaining_assignments=remaining_assignments,

                # NEW: Annotation history metrics
                total_actions=performance_metrics.get('total_actions', 0),
                average_action_time_ms=performance_metrics.get('average_action_time_ms', 0.0),
                fastest_action_time_ms=performance_metrics.get('fastest_action_time_ms', 0),
                slowest_action_time_ms=performance_metrics.get('slowest_action_time_ms', 0),
                actions_per_minute=performance_metrics.get('actions_per_minute', 0.0),
                suspicious_score=suspicious_analysis.get('suspicious_score', 0.0),
                suspicious_level=suspicious_analysis.get('suspicious_level', 'Normal'),
                fast_actions_count=suspicious_analysis.get('fast_actions_count', 0),
                burst_actions_count=suspicious_analysis.get('burst_actions_count', 0),
                session_start_time=user_state.session_start_time,
                current_session_duration_minutes=current_session_duration_minutes,
                recent_actions_count=len(recent_actions),

                # Training metrics
                training_completed=training_completed,
                training_correct_answers=training_correct_answers,
                training_total_attempts=training_total_attempts,
                training_pass_rate=training_pass_rate,
                training_current_question=training_current_question,
                training_total_questions=training_total_questions
            )

        except Exception as e:
            self.logger.error(f"Error getting timing data for user {user_id}: {e}")
            return None
    
    def _calculate_total_instance_ai(self, instance_id: str) -> Tuple[Optional[str], float]:
        """
        Calculate most frequent label and disagreement for an instance.

        Args:
            instance_id: The instance ID to analyze

        Returns:
            Tuple of (most_frequent_label, disagreement_score)
        """
        try:
            usm = get_user_state_manager()
            users = get_users()

            total_ai = 0
            for username in users:
                user_state = usm.get_user_state(username)
                if user_state:
                    total_ai += user_state.get_page_total_ai(instance_id.replace("item_", ""))

            return total_ai

        except Exception as e:
            self.logger.error(f"Error calculating label statistics for instance {instance_id}: {e}")
            return None, 0.0

    def _calculate_label_statistics(self, instance_id: str) -> Tuple[Optional[str], float]:
        """
        Calculate most frequent label and disagreement for an instance.

        Args:
            instance_id: The instance ID to analyze

        Returns:
            Tuple of (most_frequent_label, disagreement_score)
        """
        try:
            usm = get_user_state_manager()
            users = get_users()

            all_labels = []
            for username in users:
                user_state = usm.get_user_state(username)
                if user_state:
                    annotations = user_state.get_all_annotations()
                    if instance_id in annotations:
                        instance_annotations = annotations[instance_id]
                        if "labels" in instance_annotations:
                            for label, value in instance_annotations["labels"].items():
                                if hasattr(label, 'label_name'):
                                    all_labels.append(label.label_name)
                                else:
                                    all_labels.append(str(value))

            if not all_labels:
                return None, 0.0

            # Calculate most frequent label
            label_counts = Counter(all_labels)
            most_frequent_label = label_counts.most_common(1)[0][0]

            # Calculate disagreement (1 - proportion of most frequent label)
            total_annotations = len(all_labels)
            most_frequent_count = label_counts[most_frequent_label]
            disagreement = 1 - (most_frequent_count / total_annotations)

            return most_frequent_label, disagreement

        except Exception as e:
            self.logger.error(f"Error calculating label statistics for instance {instance_id}: {e}")
            return None, 0.0

    def _calculate_average_time_per_annotation(self, instance_id: str) -> Optional[float]:
        """
        Calculate average time per annotation for an instance.

        Args:
            instance_id: The instance ID to analyze

        Returns:
            Average time in seconds or None if no data
        """
        try:
            usm = get_user_state_manager()
            users = get_users()

            total_time = 0
            annotation_count = 0

            for username in users:
                user_state = usm.get_user_state(username)
                if user_state:
                    behavioral_data = user_state.instance_id_to_behavioral_data.get(instance_id, {})
                    time_string = behavioral_data.get("time_string")
                    if time_string:
                        parsed_time = user_state.parse_time_string(time_string)
                        if parsed_time:
                            total_time += parsed_time["total_seconds"]
                            annotation_count += 1

            return total_time / annotation_count if annotation_count > 0 else None

        except Exception as e:
            self.logger.error(f"Error calculating average time for instance {instance_id}: {e}")
            return None

    def _calculate_completion_percentage(self, user_id: str) -> float:
        """
        Calculate completion percentage for a user.

        Args:
            user_id: The user ID to calculate completion for

        Returns:
            Completion percentage (0-100)
        """
        try:
            usm = get_user_state_manager()
            user_state = usm.get_user_state(user_id)

            if not user_state:
                return 0.0

            total_assignments = user_state.get_assigned_instance_count()
            completed_assignments = len(user_state.get_all_annotations())

            if total_assignments == 0:
                return 0.0

            return (completed_assignments / total_assignments) * 100

        except Exception as e:
            self.logger.error(f"Error calculating completion percentage for user {user_id}: {e}")
            return 0.0

    def _format_seconds(self, seconds: Optional[float]) -> Optional[str]:
        """
        Format seconds into a human-readable string.

        Args:
            seconds: Number of seconds to format

        Returns:
            Formatted time string or None if input is None
        """
        if seconds is None:
            return None

        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            minutes = int(seconds // 60)
            remaining_seconds = int(seconds % 60)
            return f"{minutes}m {remaining_seconds}s"
        else:
            hours = int(seconds // 3600)
            remaining_minutes = int((seconds % 3600) // 60)
            return f"{hours}h {remaining_minutes}m"

    def _format_annotation_history(self, actions: List[AnnotationAction], context: str) -> Dict[str, Any]:
        """
        Format annotation history data for API response.

        Args:
            actions: List of annotation actions
            context: Context string (user_id or "all_users")

        Returns:
            Formatted annotation history data
        """
        if not actions:
            return {
                "context": context,
                "total_actions": 0,
                "actions": [],
                "summary": {
                    "action_types": {},
                    "time_distribution": {},
                    "performance_metrics": {}
                }
            }

        # Calculate summary statistics
        action_types = Counter(action.action_type for action in actions)
        time_distribution = self._calculate_time_distribution(actions)
        performance_metrics = AnnotationHistoryManager.calculate_performance_metrics(actions)

        # Format actions for response
        formatted_actions = []
        for action in actions[-100:]:  # Limit to 100 most recent
            formatted_actions.append({
                "action_id": action.action_id,
                "timestamp": action.timestamp.isoformat(),
                "user_id": action.user_id,
                "instance_id": action.instance_id,
                "action_type": action.action_type,
                "schema_name": action.schema_name,
                "label_name": action.label_name,
                "old_value": action.old_value,
                "new_value": action.new_value,
                "span_data": action.span_data,
                "session_id": action.session_id,
                "client_timestamp": action.client_timestamp.isoformat() if action.client_timestamp else None,
                "server_processing_time_ms": action.server_processing_time_ms,
                "metadata": action.metadata
            })

        return {
            "context": context,
            "total_actions": len(actions),
            "actions": formatted_actions,
            "summary": {
                "action_types": dict(action_types),
                "time_distribution": time_distribution,
                "performance_metrics": performance_metrics
            }
        }

    def _calculate_time_distribution(self, actions: List[AnnotationAction]) -> Dict[str, int]:
        """
        Calculate time distribution of actions.

        Args:
            actions: List of annotation actions

        Returns:
            Dictionary with time distribution data
        """
        if not actions:
            return {}

        # Group by hour of day
        hour_distribution = defaultdict(int)
        for action in actions:
            hour = action.timestamp.hour
            hour_distribution[f"{hour:02d}:00"] += 1

        return dict(hour_distribution)

# Global instance
admin_dashboard = AdminDashboard()

"""
MySQL-backed UserState implementation for Potato annotation platform.

This module provides a database-backed implementation of the UserState interface,
storing all user state data in MySQL tables for persistence and scalability.
"""

import logging
import threading
from typing import Dict, List, Set, Any, Optional, Tuple
from collections import defaultdict

from potato.user_state_management import UserState
from potato.phase import UserPhase
from potato.item_state_management import Item, Label, SpanAnnotation
from .connection import DatabaseManager

logger = logging.getLogger(__name__)


class MysqlUserState(UserState):
    """
    MySQL-backed implementation of UserState.

    This class stores all user state data in MySQL tables, providing
    persistence and scalability for annotation workflows.
    """

    def __init__(self, user_id: str, db_manager: DatabaseManager, max_assignments: int = -1):
        """
        Initialize the MySQL user state.

        Args:
            user_id: Unique identifier for the user
            db_manager: Database manager instance
            max_assignments: Maximum number of assignments for this user
        """
        self.user_id = user_id
        self.db_manager = db_manager
        self.max_assignments = max_assignments

        # Thread-safe cache lock
        self._cache_lock = threading.Lock()

        # Ensure user exists in database
        self._ensure_user_exists()

        # Cache for performance (protected by _cache_lock)
        self._instance_ordering_cache = None
        self._current_phase_cache = None
        self._current_page_cache = None
        self._current_instance_index_cache = None

    def _ensure_user_exists(self):
        """Create user record if it doesn't exist."""
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT IGNORE INTO user_states
                (user_id, current_phase, current_page, current_instance_index, max_assignments)
                VALUES (%s, %s, %s, %s, %s)
            """, (self.user_id, 'LOGIN', None, -1, self.max_assignments))
            conn.commit()

    def _invalidate_cache(self):
        """Invalidate cached data (thread-safe)."""
        with self._cache_lock:
            self._instance_ordering_cache = None
            self._current_phase_cache = None
            self._current_page_cache = None
            self._current_instance_index_cache = None

    def advance_to_phase(self, phase: UserPhase, page: str) -> None:
        """Advance the user to a new phase and page."""
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE user_states
                SET current_phase = %s, current_page = %s
                WHERE user_id = %s
            """, (str(phase), page, self.user_id))
            conn.commit()

        self._invalidate_cache()

    def assign_instance(self, item: Item) -> None:
        """Assign an instance to the user for annotation."""
        instance_id = item.get_id()

        # Check if already assigned
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM user_instance_assignments
                WHERE user_id = %s AND instance_id = %s
            """, (self.user_id, instance_id))

            result = cursor.fetchone()
            if result is not None and result[0] > 0:
                return  # Already assigned

            # Get next assignment order
            cursor.execute("""
                SELECT COALESCE(MAX(assignment_order), -1) + 1
                FROM user_instance_assignments
                WHERE user_id = %s
            """, (self.user_id,))
            result = cursor.fetchone()
            next_order = result[0] if result is not None else 0

            # Insert assignment
            cursor.execute("""
                INSERT INTO user_instance_assignments (user_id, instance_id, assignment_order)
                VALUES (%s, %s, %s)
            """, (self.user_id, instance_id, next_order))

            # Update current instance index if this is the first assignment
            cursor.execute("""
                SELECT current_instance_index FROM user_states WHERE user_id = %s
            """, (self.user_id,))
            result = cursor.fetchone()
            current_index = result[0] if result is not None else -1

            if current_index == -1:
                cursor.execute("""
                    UPDATE user_states SET current_instance_index = 0 WHERE user_id = %s
                """, (self.user_id,))

            conn.commit()

        self._invalidate_cache()

    def get_current_instance(self) -> Optional[Item]:
        """Get the current instance the user is annotating."""
        current_index = self.get_current_instance_index()
        if current_index < 0:
            return None

        instance_ordering = self._get_instance_ordering()
        if current_index >= len(instance_ordering):
            return None

        instance_id = instance_ordering[current_index]
        from potato.item_state_management import get_item_state_manager
        return get_item_state_manager().get_item(instance_id)

    def get_current_instance_index(self) -> int:
        """Get the current instance index."""
        if self._current_instance_index_cache is not None:
            return self._current_instance_index_cache

        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT current_instance_index FROM user_states WHERE user_id = %s
            """, (self.user_id,))
            result = cursor.fetchone()
            self._current_instance_index_cache = result[0] if result else -1
            return self._current_instance_index_cache

    def get_user_id(self) -> str:
        """Get the user ID."""
        return self.user_id

    def goto_prev_instance(self) -> bool:
        """Move to the previous instance."""
        current_index = self.get_current_instance_index()
        if current_index > 0:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE user_states SET current_instance_index = %s WHERE user_id = %s
                """, (current_index - 1, self.user_id))
                conn.commit()

            self._invalidate_cache()
            return True
        return False

    def goto_next_instance(self) -> bool:
        """Move to the next instance."""
        current_index = self.get_current_instance_index()
        instance_ordering = self._get_instance_ordering()

        if current_index < len(instance_ordering) - 1:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE user_states SET current_instance_index = %s WHERE user_id = %s
                """, (current_index + 1, self.user_id))
                conn.commit()

            self._invalidate_cache()
            return True
        return False

    def go_to_index(self, instance_index: int) -> None:
        """Move to a specific instance index."""
        instance_ordering = self._get_instance_ordering()
        if 0 <= instance_index < len(instance_ordering):
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE user_states SET current_instance_index = %s WHERE user_id = %s
                """, (instance_index, self.user_id))
                conn.commit()

            self._invalidate_cache()

    def get_all_annotations(self) -> Dict[str, Dict[str, Any]]:
        """Get all annotations for this user."""
        annotations = {}

        # Get label annotations
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT instance_id, schema_name, label_name, label_value
                FROM label_annotations
                WHERE user_id = %s
            """, (self.user_id,))

            for row in cursor.fetchall():
                instance_id, schema_name, label_name, label_value = row
                if instance_id not in annotations:
                    annotations[instance_id] = {"labels": {}, "spans": {}}

                if schema_name not in annotations[instance_id]["labels"]:
                    annotations[instance_id]["labels"][schema_name] = {}

                annotations[instance_id]["labels"][schema_name][label_name] = label_value

            # Get span annotations
            cursor.execute("""
                SELECT instance_id, schema_name, span_name, span_title, start_pos, end_pos
                FROM span_annotations
                WHERE user_id = %s
            """, (self.user_id,))

            for row in cursor.fetchall():
                instance_id, schema_name, span_name, span_title, start_pos, end_pos = row
                if instance_id not in annotations:
                    annotations[instance_id] = {"labels": {}, "spans": {}}

                if schema_name not in annotations[instance_id]["spans"]:
                    annotations[instance_id]["spans"][schema_name] = {}

                annotations[instance_id]["spans"][schema_name][span_name] = {
                    "title": span_title,
                    "start": start_pos,
                    "end": end_pos
                }

        return annotations

    def get_label_annotations(self, instance_id: str) -> Dict[Label, Any]:
        """Get label annotations for a specific instance."""
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT schema_name, label_name, label_value
                FROM label_annotations
                WHERE user_id = %s AND instance_id = %s
            """, (self.user_id, instance_id))

            annotations = {}
            for row in cursor.fetchall():
                schema_name, label_name, label_value = row
                label = Label(schema_name, label_name)
                annotations[label] = label_value

            return annotations

    def get_span_annotations(self, instance_id: str) -> Dict[SpanAnnotation, Any]:
        """Get span annotations for a specific instance."""
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT schema_name, span_name, span_title, start_pos, end_pos
                FROM span_annotations
                WHERE user_id = %s AND instance_id = %s
            """, (self.user_id, instance_id))

            annotations = {}
            for row in cursor.fetchall():
                schema_name, span_name, span_title, start_pos, end_pos = row
                span = SpanAnnotation(schema_name, span_name, span_title, start_pos, end_pos)
                annotations[span] = True  # Span annotations are boolean

            return annotations

    def get_current_phase_and_page(self) -> Tuple[UserPhase, Optional[str]]:
        """Get the current phase and page."""
        if self._current_phase_cache is not None and self._current_page_cache is not None:
            return self._current_phase_cache, self._current_page_cache

        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT current_phase, current_page FROM user_states WHERE user_id = %s
            """, (self.user_id,))
            result = cursor.fetchone()

            if result:
                phase_str, page = result
                phase = UserPhase.fromstr(phase_str)
                self._current_phase_cache = phase
                self._current_page_cache = page
                return phase, page
            else:
                return UserPhase.LOGIN, None

    def get_annotation_count(self) -> int:
        """Get the number of annotated instances."""
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(DISTINCT instance_id) FROM label_annotations WHERE user_id = %s
                UNION
                SELECT COUNT(DISTINCT instance_id) FROM span_annotations WHERE user_id = %s
            """, (self.user_id, self.user_id))

            results = cursor.fetchall()
            return sum(result[0] for result in results)

    def get_assigned_instance_count(self) -> int:
        """Get the number of assigned instances."""
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM user_instance_assignments WHERE user_id = %s
            """, (self.user_id,))
            result = cursor.fetchone()
            return result[0] if result is not None else 0

    def get_assigned_instance_ids(self) -> Set[str]:
        """Get the set of assigned instance IDs."""
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT instance_id FROM user_instance_assignments
                WHERE user_id = %s ORDER BY assignment_order
            """, (self.user_id,))
            return {row[0] for row in cursor.fetchall()}

    def add_label_annotation(self, instance_id: str, label: Label, value: Any) -> None:
        """Add a label annotation."""
        phase, page = self.get_current_phase_and_page()

        if phase == UserPhase.ANNOTATION:
            # Store in label_annotations table
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO label_annotations
                    (user_id, instance_id, schema_name, label_name, label_value)
                    VALUES (%s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE label_value = VALUES(label_value)
                """, (self.user_id, instance_id, label.get_schema(),
                      label.get_name(), str(value)))
                conn.commit()
        else:
            # Store in phase_annotations table
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO phase_annotations
                    (user_id, phase_name, page_name, schema_name, label_name, label_value)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE label_value = VALUES(label_value)
                """, (self.user_id, str(phase), page, label.get_schema(),
                      label.get_name(), str(value)))
                conn.commit()

    def add_span_annotation(self, instance_id: str, span: SpanAnnotation, value: Any) -> None:
        """Add a span annotation."""
        phase, page = self.get_current_phase_and_page()

        if phase == UserPhase.ANNOTATION:
            # Store in span_annotations table
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO span_annotations
                    (user_id, instance_id, schema_name, span_name, span_title, start_pos, end_pos)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        span_title = VALUES(span_title),
                        start_pos = VALUES(start_pos),
                        end_pos = VALUES(end_pos)
                """, (self.user_id, instance_id, span.get_schema(), span.get_name(),
                      span.get_title(), span.get_start(), span.get_end()))
                conn.commit()
        else:
            # For non-annotation phases, store in phase_annotations as JSON
            span_data = {
                "title": span.get_title(),
                "start": span.get_start(),
                "end": span.get_end()
            }
            import json
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO phase_annotations
                    (user_id, phase_name, page_name, schema_name, label_name, label_value)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE label_value = VALUES(label_value)
                """, (self.user_id, str(phase), page, span.get_schema(),
                      span.get_name(), json.dumps(span_data)))
                conn.commit()

    def get_annotated_instance_ids(self) -> Set[str]:
        """Get the set of annotated instance IDs."""
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT instance_id FROM label_annotations WHERE user_id = %s
                UNION
                SELECT DISTINCT instance_id FROM span_annotations WHERE user_id = %s
            """, (self.user_id, self.user_id))
            return {row[0] for row in cursor.fetchall()}

    def has_annotated(self, instance_id: str) -> bool:
        """Check if the user has annotated a specific instance."""
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM label_annotations WHERE user_id = %s AND instance_id = %s
                UNION
                SELECT COUNT(*) FROM span_annotations WHERE user_id = %s AND instance_id = %s
            """, (self.user_id, instance_id, self.user_id, instance_id))

            results = cursor.fetchall()
            return any(result[0] > 0 for result in results)

    def clear_all_annotations(self) -> None:
        """Clear all annotations for this user."""
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM label_annotations WHERE user_id = %s", (self.user_id,))
            cursor.execute("DELETE FROM span_annotations WHERE user_id = %s", (self.user_id,))
            cursor.execute("DELETE FROM phase_annotations WHERE user_id = %s", (self.user_id,))
            cursor.execute("DELETE FROM behavioral_data WHERE user_id = %s", (self.user_id,))
            cursor.execute("DELETE FROM ai_hints WHERE user_id = %s", (self.user_id,))
            conn.commit()

    def has_assignments(self) -> bool:
        """Check if the user has any assignments."""
        return self.get_assigned_instance_count() > 0

    def has_remaining_assignments(self) -> bool:
        """Check if the user has remaining assignments."""
        if self.max_assignments < 0:
            return True
        return self.get_annotation_count() < self.max_assignments

    def set_max_assignments(self, max_assignments: int) -> None:
        """Set the maximum number of assignments."""
        self.max_assignments = max_assignments
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE user_states SET max_assignments = %s WHERE user_id = %s
            """, (max_assignments, self.user_id))
            conn.commit()

    def get_max_assignments(self) -> int:
        """Get the maximum number of assignments."""
        return self.max_assignments

    def hint_exists(self, instance_id: str) -> bool:
        """Check if a hint exists for an instance."""
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM ai_hints WHERE user_id = %s AND instance_id = %s
            """, (self.user_id, instance_id))
            result = cursor.fetchone()
            return result is not None and result[0] > 0

    def get_hint(self, instance_id: str) -> Optional[str]:
        """Get the hint for an instance."""
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT hint_text FROM ai_hints WHERE user_id = %s AND instance_id = %s
            """, (self.user_id, instance_id))
            result = cursor.fetchone()
            return result[0] if result else None

    def cache_hint(self, instance_id: str, hint: str) -> None:
        """Cache a hint for an instance."""
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO ai_hints (user_id, instance_id, hint_text)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE hint_text = VALUES(hint_text)
            """, (self.user_id, instance_id, hint))
            conn.commit()

    def _get_instance_ordering(self) -> List[str]:
        """Get the ordered list of assigned instance IDs."""
        if self._instance_ordering_cache is not None:
            return self._instance_ordering_cache

        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT instance_id FROM user_instance_assignments
                WHERE user_id = %s ORDER BY assignment_order
            """, (self.user_id,))

            self._instance_ordering_cache = [row[0] for row in cursor.fetchall()]
            return self._instance_ordering_cache

    def is_at_end_index(self) -> bool:
        """Check if the user is at the end of their assignments."""
        current_index = self.get_current_instance_index()
        instance_ordering = self._get_instance_ordering()
        return current_index == len(instance_ordering) - 1

    def go_back(self) -> bool:
        """Move back to the previous instance."""
        return self.goto_prev_instance()

    def go_forward(self) -> bool:
        """Move forward to the next instance."""
        return self.goto_next_instance()

    def get_current_instance_id(self) -> Optional[str]:
        """Get the ID of the current instance."""
        current_instance = self.get_current_instance()
        return current_instance.get_id() if current_instance else None

    def get_labels(self) -> Dict[str, Dict[str, str]]:
        """Get all labels (deprecated, use get_all_annotations)."""
        annotations = self.get_all_annotations()
        labels = {}
        for instance_id, data in annotations.items():
            labels[instance_id] = data.get("labels", {})
        return labels


"""
Interaction tracking data structures and utilities for behavioral analysis.

Dataclasses for tracking user interactions during annotation,
including clicks, focus changes, navigation, AI assistance usage, and annotation changes.
All data is designed to be serializable for persistence and later analysis.
"""
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Any, Optional
import time


@dataclass
class InteractionEvent:
    """
    A single user interaction with the annotation interface.

    Attributes:
        event_type: Type of interaction ("click", "focus_in", "focus_out",
                    "navigation", "save", "scroll", "keypress", etc.)
        timestamp: Server-side Unix timestamp when event was recorded
        target: Element identifier (e.g., "label:positive", "nav:next", "schema:sentiment")
        instance_id: The annotation instance this event occurred on
        client_timestamp: Client-side timestamp in milliseconds (for latency analysis)
        metadata: Additional context (position, value changes, duration, etc.)
    """
    event_type: str
    timestamp: float
    target: str
    instance_id: str
    client_timestamp: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'event_type': self.event_type,
            'timestamp': self.timestamp,
            'target': self.target,
            'instance_id': self.instance_id,
            'client_timestamp': self.client_timestamp,
            'metadata': self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'InteractionEvent':
        """Reconstruct from serialized dictionary."""
        return cls(
            event_type=data.get('event_type', ''),
            timestamp=data.get('timestamp', 0),
            target=data.get('target', ''),
            instance_id=data.get('instance_id', ''),
            client_timestamp=data.get('client_timestamp'),
            metadata=data.get('metadata', {}),
        )


@dataclass
class AIUsageEvent:
    """
    Tracks AI assistance usage for an annotation instance.

    Captures the full lifecycle of an AI assistance request:
    request -> response -> user decision (accept/reject/ignore)

    Attributes:
        request_timestamp: When AI assistance was requested
        schema_name: Which annotation schema the AI assisted with
        suggestions_shown: List of labels/values the AI suggested
        response_timestamp: When the AI response was received
        suggestion_accepted: The value the user accepted (None if rejected/ignored)
        final_annotation: What the user ultimately annotated for this schema
        time_to_decision_ms: Milliseconds from response to user action
    """
    request_timestamp: float
    schema_name: str
    suggestions_shown: List[str] = field(default_factory=list)
    response_timestamp: Optional[float] = None
    suggestion_accepted: Optional[str] = None
    final_annotation: Optional[str] = None
    time_to_decision_ms: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'request_timestamp': self.request_timestamp,
            'schema_name': self.schema_name,
            'suggestions_shown': self.suggestions_shown,
            'response_timestamp': self.response_timestamp,
            'suggestion_accepted': self.suggestion_accepted,
            'final_annotation': self.final_annotation,
            'time_to_decision_ms': self.time_to_decision_ms,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AIUsageEvent':
        """Reconstruct from serialized dictionary."""
        return cls(
            request_timestamp=data.get('request_timestamp', 0),
            schema_name=data.get('schema_name', ''),
            suggestions_shown=data.get('suggestions_shown', []),
            response_timestamp=data.get('response_timestamp'),
            suggestion_accepted=data.get('suggestion_accepted'),
            final_annotation=data.get('final_annotation'),
            time_to_decision_ms=data.get('time_to_decision_ms'),
        )


@dataclass
class AnnotationChange:
    """
    Records a single change to an annotation.

    Attributes:
        timestamp: When the change occurred
        schema_name: Which schema was modified
        label_name: Which label was affected (if applicable)
        action: Type of change ("select", "deselect", "update", "clear")
        old_label: The label the answer moved AWAY from. Single-select schemas
            (radio/likert/confidence) store one entry per option, so a revision changes
            the label as well as the value — recording only old_value cannot express
            "moved from scale point 5 to scale point 4".
        old_value: Previous value (if any)
        new_value: New value after the change
        source: What triggered the change ("user", "ai_accept", "prefill", "keyboard")
        phase: Workflow phase the change happened in ("annotation", "prestudy", ...).
            Behavioral data is bucketed by instance id, and every non-annotation page
            shares the sentinel "__phase_page__", so without phase/page the trail
            cannot say which survey a change belongs to.
        page: The phase page name, for non-annotation phases.
    """
    timestamp: float
    schema_name: str
    action: str
    label_name: Optional[str] = None
    old_label: Optional[str] = None
    old_value: Any = None
    new_value: Any = None
    source: str = "user"
    phase: Optional[str] = None
    page: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'timestamp': self.timestamp,
            'schema_name': self.schema_name,
            'label_name': self.label_name,
            'old_label': self.old_label,
            'action': self.action,
            'old_value': self.old_value,
            'new_value': self.new_value,
            'source': self.source,
            'phase': self.phase,
            'page': self.page,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AnnotationChange':
        """Reconstruct from serialized dictionary.

        Every field added after the original release is read with .get(), so records
        written by older Potato versions deserialize unchanged.
        """
        return cls(
            timestamp=data.get('timestamp', 0),
            schema_name=data.get('schema_name', ''),
            label_name=data.get('label_name'),
            old_label=data.get('old_label'),
            action=data.get('action', ''),
            old_value=data.get('old_value'),
            new_value=data.get('new_value'),
            source=data.get('source', 'user'),
            phase=data.get('phase'),
            page=data.get('page'),
        )


@dataclass
class ChatMessage:
    """
    A single chat message between an annotator and the LLM assistant.

    Attributes:
        role: 'user' or 'assistant'
        content: The message text
        timestamp: Unix timestamp when the message was sent/received
        instance_id: The annotation instance this message relates to
        response_time_ms: Milliseconds for the LLM to respond (assistant messages only)
    """
    role: str
    content: str
    timestamp: float
    instance_id: str
    response_time_ms: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'role': self.role,
            'content': self.content,
            'timestamp': self.timestamp,
            'instance_id': self.instance_id,
            'response_time_ms': self.response_time_ms,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ChatMessage':
        """Reconstruct from serialized dictionary."""
        return cls(
            role=data.get('role', ''),
            content=data.get('content', ''),
            timestamp=data.get('timestamp', 0),
            instance_id=data.get('instance_id', ''),
            response_time_ms=data.get('response_time_ms'),
        )


@dataclass
class BehavioralData:
    """
    Complete behavioral data for an annotation instance session.

    Aggregates all tracking data for a single instance annotation session,
    including timing, interactions, AI usage, and annotation changes.

    Attributes:
        instance_id: The annotation instance ID
        session_start: Unix timestamp when user first loaded this instance
        session_end: Unix timestamp when user navigated away or saved
        total_time_ms: Total milliseconds spent on this instance
        interactions: List of all interaction events
        ai_usage: List of AI assistance usage events
        annotation_changes: List of annotation modifications
        navigation_history: List of navigation events to/from this instance
        focus_time_by_element: Milliseconds spent focused on each element
        scroll_depth_max: Maximum scroll percentage reached (0-100)
        keyword_highlights_shown: Keyword highlights displayed (from randomization feature)
        presentation_order: Which order each scheme's options were shown in,
            ``{schema_name: [label names]}``. Recorded whether or not
            randomization is on, because a fixed order biases every annotator
            the same way -- which inflates agreement while biasing the
            estimate -- and the only way to correct a study afterwards is to
            know what each annotator actually saw. See
            potato/server_utils/presentation_order.py.
        chat_history: Messages exchanged with the LLM assistant sidebar
        typing_summaries: Per-field typing-dynamics sketch, keyed
            "{schema}:::{label}". Only the compact summary lives here — the raw
            keystroke event streams go to SQLite (potato/typing_store.py), because
            user_state.json is fully re-serialized on every annotation save and a
            single long response is thousands of events. See
            potato/typing_dynamics.py.
        annotation_telemetry: Per-schema drawing-dynamics sketch, keyed by
            schema name. Same split and same reasoning as typing_summaries —
            raw event streams live in SQLite
            (potato/annotation_telemetry_store.py). See
            potato/annotation_telemetry.py.
    """
    instance_id: str
    session_start: float = field(default_factory=time.time)
    session_end: Optional[float] = None
    total_time_ms: int = 0
    interactions: List[InteractionEvent] = field(default_factory=list)
    ai_usage: List[AIUsageEvent] = field(default_factory=list)
    annotation_changes: List[AnnotationChange] = field(default_factory=list)
    navigation_history: List[Dict[str, Any]] = field(default_factory=list)
    focus_time_by_element: Dict[str, int] = field(default_factory=dict)
    scroll_depth_max: float = 0.0
    keyword_highlights_shown: List[Dict[str, Any]] = field(default_factory=list)
    presentation_order: Dict[str, List[str]] = field(default_factory=dict)
    chat_history: List[ChatMessage] = field(default_factory=list)
    typing_summaries: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    annotation_telemetry: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'instance_id': self.instance_id,
            'session_start': self.session_start,
            'session_end': self.session_end,
            'total_time_ms': self.total_time_ms,
            'interactions': [
                e.to_dict() if hasattr(e, 'to_dict') else e
                for e in self.interactions
            ],
            'ai_usage': [
                e.to_dict() if hasattr(e, 'to_dict') else e
                for e in self.ai_usage
            ],
            'annotation_changes': [
                e.to_dict() if hasattr(e, 'to_dict') else e
                for e in self.annotation_changes
            ],
            'navigation_history': self.navigation_history,
            'focus_time_by_element': self.focus_time_by_element,
            'scroll_depth_max': self.scroll_depth_max,
            'keyword_highlights_shown': self.keyword_highlights_shown,
            'presentation_order': self.presentation_order,
            'chat_history': [
                e.to_dict() if hasattr(e, 'to_dict') else e
                for e in self.chat_history
            ],
            'typing_summaries': self.typing_summaries,
            'annotation_telemetry': self.annotation_telemetry,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BehavioralData':
        """
        Reconstruct from serialized dictionary.

        Handles both raw dictionaries and properly typed objects.
        """
        bd = cls(instance_id=data.get('instance_id', ''))
        bd.session_start = data.get('session_start', 0)
        bd.session_end = data.get('session_end')
        bd.total_time_ms = data.get('total_time_ms', 0)

        # Reconstruct interactions
        interactions = data.get('interactions', [])
        bd.interactions = [
            InteractionEvent.from_dict(e) if isinstance(e, dict) else e
            for e in interactions
        ]

        # Reconstruct AI usage events
        ai_usage = data.get('ai_usage', [])
        bd.ai_usage = [
            AIUsageEvent.from_dict(e) if isinstance(e, dict) else e
            for e in ai_usage
        ]

        # Reconstruct annotation changes
        changes = data.get('annotation_changes', [])
        bd.annotation_changes = [
            AnnotationChange.from_dict(e) if isinstance(e, dict) else e
            for e in changes
        ]

        bd.navigation_history = data.get('navigation_history', [])
        bd.focus_time_by_element = data.get('focus_time_by_element', {})
        bd.scroll_depth_max = data.get('scroll_depth_max', 0.0)
        bd.keyword_highlights_shown = data.get('keyword_highlights_shown', [])
        bd.presentation_order = data.get('presentation_order', {}) or {}

        # Reconstruct chat history
        chat_history = data.get('chat_history', [])
        bd.chat_history = [
            ChatMessage.from_dict(e) if isinstance(e, dict) else e
            for e in chat_history
        ]

        # Read with .get() so states written before typing dynamics existed
        # deserialize unchanged.
        bd.typing_summaries = data.get('typing_summaries', {})
        bd.annotation_telemetry = data.get('annotation_telemetry', {})

        return bd

    def add_interaction(self, event_type: str, target: str,
                       client_timestamp: Optional[float] = None,
                       metadata: Optional[Dict[str, Any]] = None) -> None:
        """Add an interaction event with current timestamp."""
        self.interactions.append(InteractionEvent(
            event_type=event_type,
            timestamp=time.time(),
            target=target,
            instance_id=self.instance_id,
            client_timestamp=client_timestamp,
            metadata=metadata or {},
        ))

    def add_ai_request(self, schema_name: str) -> AIUsageEvent:
        """Record an AI assistance request and return the event for later update."""
        event = AIUsageEvent(
            request_timestamp=time.time(),
            schema_name=schema_name,
        )
        self.ai_usage.append(event)
        return event

    def add_annotation_change(self, schema_name: str, action: str,
                             label_name: Optional[str] = None,
                             old_value: Any = None, new_value: Any = None,
                             source: str = "user", old_label: Optional[str] = None,
                             phase: Optional[str] = None,
                             page: Optional[str] = None) -> None:
        """Record an annotation change."""
        self.annotation_changes.append(AnnotationChange(
            timestamp=time.time(),
            schema_name=schema_name,
            label_name=label_name,
            old_label=old_label,
            action=action,
            old_value=old_value,
            new_value=new_value,
            source=source,
            phase=phase,
            page=page,
        ))

    def add_navigation(self, action: str, from_instance: Optional[str] = None,
                      to_instance: Optional[str] = None) -> None:
        """Record a navigation event."""
        self.navigation_history.append({
            'action': action,
            'from_instance': from_instance,
            'to_instance': to_instance,
            'timestamp': time.time(),
        })

    def update_focus_time(self, element: str, duration_ms: int) -> None:
        """Add time spent focused on an element."""
        current = self.focus_time_by_element.get(element, 0)
        self.focus_time_by_element[element] = current + duration_ms

    def update_scroll_depth(self, depth: float) -> None:
        """Update maximum scroll depth if new depth is greater."""
        if depth > self.scroll_depth_max:
            self.scroll_depth_max = depth

    def set_typing_summary(self, schema_name: str, label_name: str,
                          summary: Dict[str, Any]) -> None:
        """Store the typing-dynamics sketch for one free-text field.

        Keyed the same way annotation labels are (`schema:::label`), so a field
        can be joined back to its annotation without a separate mapping.
        """
        self.typing_summaries[f"{schema_name}:::{label_name}"] = summary

    def set_annotation_telemetry(self, schema_name: str,
                                 summary: Dict[str, Any]) -> None:
        """Store the drawing-dynamics sketch for one geometry schema.

        Keyed by schema alone rather than `schema:::label`: a drawn annotation
        is stored under the single `_data` key, so there is no label to key on
        and inventing one would create a join that does not exist.
        """
        self.annotation_telemetry[schema_name] = summary

    def finalize_session(self) -> None:
        """Mark session as ended and calculate total time."""
        self.session_end = time.time()
        self.total_time_ms = int((self.session_end - self.session_start) * 1000)


def create_behavioral_data(instance_id: str) -> BehavioralData:
    """Factory function to create new behavioral data for an instance."""
    return BehavioralData(instance_id=instance_id)


def get_or_create_behavioral_data(
    behavioral_data_dict: Dict[str, Any],
    instance_id: str
) -> BehavioralData:
    """
    Get existing behavioral data or create new one.

    Args:
        behavioral_data_dict: Dictionary mapping instance_id to BehavioralData
        instance_id: The instance to get/create data for

    Returns:
        BehavioralData object for the instance
    """
    if instance_id not in behavioral_data_dict:
        behavioral_data_dict[instance_id] = create_behavioral_data(instance_id)

    bd = behavioral_data_dict[instance_id]

    # Handle case where dict contains raw dict instead of BehavioralData
    if isinstance(bd, dict):
        bd = BehavioralData.from_dict(bd)
        behavioral_data_dict[instance_id] = bd

    return bd

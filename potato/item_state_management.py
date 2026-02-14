"""
Item State Management Module

This module provides the core data structures and management logic for annotation items
in the Potato platform. It handles item storage, assignment strategies, and tracking
of annotation progress across users.

The module includes:
- Item class: Represents individual annotation items with metadata
- Label class: Represents annotation labels with schema information
- SpanAnnotation class: Represents text span annotations with position data
- AssignmentStrategy enum: Defines different strategies for assigning items to users
- ItemStateManager: Main class for managing item state and assignments

The system supports multiple assignment strategies including random, fixed order,
active learning, and diversity-based assignment to optimize annotation efficiency.
"""

from __future__ import annotations

# Need to import UserState as a type hint for the ItemStateManager
from typing import TYPE_CHECKING, Dict, Set, List, Optional
if TYPE_CHECKING:
    from potato.user_state_management import UserState

from enum import Enum
from collections import OrderedDict, deque, Counter, defaultdict
import random
import uuid
import logging
import threading

# Singleton instance of the ItemStateManager with thread-safe lock
ITEM_STATE_MANAGER = None
_ITEM_STATE_MANAGER_LOCK = threading.Lock()

def init_item_state_manager(config: dict) -> ItemStateManager:
    """
    Initialize the singleton ItemStateManager instance.

    This function creates the global ItemStateManager that will be shared
    across all users. It's designed to be called once during application startup.
    Thread-safe initialization using double-checked locking pattern.

    Args:
        config: Configuration dictionary containing item management settings

    Returns:
        ItemStateManager: The initialized singleton instance

    Note:
        TODO: make the manager type configurable between in-memory and DB-backed.
        The DB back-end is for when we have a ton of data and don't want it sitting in
        memory all the time (or where some external process is going to be adding new items)
    """
    global ITEM_STATE_MANAGER

    # Double-checked locking for thread safety
    if ITEM_STATE_MANAGER is None:
        with _ITEM_STATE_MANAGER_LOCK:
            # Check again inside the lock
            if ITEM_STATE_MANAGER is None:
                ITEM_STATE_MANAGER = ItemStateManager(config)

    return ITEM_STATE_MANAGER

def clear_item_state_manager():
    """
    Clear the singleton item state manager instance (for testing).

    This function is primarily used for testing purposes to reset the
    global state between test runs. Thread-safe.
    """
    global ITEM_STATE_MANAGER
    with _ITEM_STATE_MANAGER_LOCK:
        ITEM_STATE_MANAGER = None

def get_item_state_manager() -> ItemStateManager:
    """
    Get the singleton ItemStateManager instance.

    Returns:
        ItemStateManager: The singleton instance

    Raises:
        ValueError: If the manager has not been initialized

    Note:
        TODO: make the manager type configurable between in-memory and DB-backed.
        The DB back-end is for when we have a ton of data and don't want it sitting in
        memory all the time (or where some external process is going to be adding new items)
    """
    global ITEM_STATE_MANAGER

    if ITEM_STATE_MANAGER is None:
        raise ValueError("Item State Manager has not been initialized yet!")

    return ITEM_STATE_MANAGER

class Item:
    """
    A class for maintaining state on items that are being annotated.

    The state of the annotations themselves are stored in the UserState class.
    The item itself is largely immutable but can be updated with metadata.
    """

    def __init__(self, item_id, item_data):
        """
        Initialize an annotation item.

        Args:
            item_id: Unique identifier for this item
            item_data: Dictionary containing the item's data (text, context, etc.)
        """
        self.item_id = item_id
        self.item_data = item_data
        self.metadata = {}

        # This data structure keeps the label-based annotations the user has
        # completed so far
        self.labels = {}

        # This data structure keeps the span-based annotations the user has
        # completed so far
        self.span_annotations = {}

    def add_metadata(self, metadata_name: str, metadata_value: str):
        """Add metadata to this item"""
        self.metadata[metadata_name] = metadata_value

    def get_id(self):
        """Get the item's unique identifier"""
        return self.item_id

    def get_data(self):
        """Get the item's raw data dictionary"""
        return self.item_data

    def get_text(self):
        """
        Get the text content from the item data.

        This method intelligently extracts text from various data structures,
        trying common keys first, then falling back to string conversion.

        Returns:
            str: The text content for annotation
        """
        if isinstance(self.item_data, dict):
            # Try to get text from common keys
            for key in ['text', 'content', 'message', 'title']:
                if key in self.item_data:
                    return self.item_data[key]
            # If no text key found, return the first string value
            for value in self.item_data.values():
                if isinstance(value, str):
                    return value
        elif isinstance(self.item_data, str):
            return self.item_data
        return str(self.item_data)

    def get_displayed_text(self):
        """Get the displayed text (same as get_text for now)"""
        return self.get_text()

    def get_metadata(self, metadata_name: str):
        """Get metadata value by name"""
        return self.metadata.get(metadata_name, None)

    def __str__(self):
        return f"Item(id:{self.item_id}, data:{self.item_data}, metadata:{self.metadata})"

class Label:
    """
    A utility class for representing a single label in any annotation scheme.

    Labels may have a integer value (likert), a string value (text), or a boolean value (binary).
    Span annotations are represented with a different class.
    """
    def __init__(self, schema: str, name: str):
        """
        Initialize a label.

        Args:
            schema: The annotation scheme this label belongs to
            name: The label name/value
        """
        self.schema = schema
        self.name = name

    def get_schema(self):
        """Get the schema this label belongs to"""
        return self.schema

    def get_name(self):
        """Get the label name/value"""
        return self.name

    def __str__(self):
        return f"Label(schema:{self.schema}, name:{self.name})"

    def __eq__(self, other):
        """Check if two labels are equal"""
        return self.schema == other.schema and self.name == other.name

    def __hash__(self):
        """Generate hash for label (enables use in sets/dicts)"""
        return hash((self.schema, self.name))

class SpanAnnotation:
    """
    A utility class for representing a single span annotation in any annotation scheme.

    Spans are represented by a start and end index, as well as a label.
    Optionally includes format-specific coordinates (e.g., PDF page/bbox, spreadsheet row/col).
    """
    def __init__(self, schema: str, name: str, title: str, start: int, end: int,
                 id: str = None, annotation_id: str = None, target_field: str = None,
                 format_coords: dict = None):
        """
        Initialize a span annotation.

        Args:
            schema: The annotation scheme this span belongs to
            name: The span label name
            title: The span title/description
            start: Start character index (inclusive)
            end: End character index (exclusive)
            id: Optional custom ID for the span
            annotation_id: Alternative parameter name for ID (for compatibility)
            target_field: The display field this span targets (for multi-span mode)
            format_coords: Optional format-specific coordinates (e.g., PDF page/bbox,
                          spreadsheet row/col). Structure depends on source format:
                          - PDF: {"format": "pdf", "page": 1, "bbox": [x0, y0, x1, y1]}
                          - Spreadsheet: {"format": "spreadsheet", "row": 1, "col": 2, "cell_ref": "B1"}
                          - Code: {"format": "code", "line": 10, "column": 5}
                          - Document: {"format": "document", "paragraph_id": "p_0", "local_offset": 0}
        """
        self.schema = schema
        self.start = start
        self.title = title
        self.end = end
        self.name = name
        self.target_field = target_field  # For multi-span support
        self.format_coords = format_coords  # Format-specific coordinates
        # Accept both id and annotation_id for compatibility
        _id = id if id is not None else annotation_id
        if _id is not None:
            self._id = _id
        else:
            # Generate a unique ID if none provided
            self._id = f"span_{uuid.uuid4().hex}"

    def get_schema(self):
        """Get the schema this span belongs to"""
        return self.schema

    def get_start(self):
        """Get the start character index"""
        return self.start

    def get_end(self):
        """Get the end character index"""
        return self.end

    def get_name(self):
        """Get the span label name"""
        return self.name

    def get_title(self):
        """Get the span title/description"""
        return self.title

    def get_id(self):
        """Get the span's unique identifier"""
        return self._id

    def get_target_field(self):
        """Get the target field key (for multi-span mode)"""
        return self.target_field

    def get_format_coords(self):
        """Get format-specific coordinates (for document format support)"""
        return self.format_coords

    def set_format_coords(self, coords: dict):
        """Set format-specific coordinates"""
        self.format_coords = coords

    def to_dict(self) -> dict:
        """Convert span annotation to dictionary for serialization."""
        result = {
            "schema": self.schema,
            "name": self.name,
            "title": self.title,
            "start": self.start,
            "end": self.end,
            "id": self._id,
        }
        if self.target_field:
            result["target_field"] = self.target_field
        if self.format_coords:
            result["format_coords"] = self.format_coords
        return result

    def __str__(self):
        field_str = f", target_field:{self.target_field}" if self.target_field else ""
        coords_str = f", format_coords:{self.format_coords}" if self.format_coords else ""
        return f"SpanAnnotation(schema:{self.schema}, name:{self.name}, start:{self.start}, end:{self.end}, id:{self._id}{field_str}{coords_str})"

    def __eq__(self, other):
        """Check if two span annotations are equal"""
        return (
            isinstance(other, SpanAnnotation)
            and self.schema == other.schema
            and self.name == other.name
            and self.title == other.title
            and self.start == other.start
            and self.end == other.end
            and self.target_field == other.target_field
            # Note: format_coords not included in equality check
            # as they are derived from position, not essential identity
        )

    def __hash__(self):
        """Generate hash for span annotation (enables use in sets/dicts)"""
        return hash((self.schema, self.name, self.title, self.start, self.end, self.target_field))


class SpanLink:
    """
    A utility class for representing a link/relationship between spans.

    SpanLinks connect two or more spans to represent relationships like
    "PERSON works_for ORGANIZATION" or multi-way relationships.
    """
    def __init__(self, schema: str, link_type: str, span_ids: List[str],
                 direction: str = "undirected", id: str = None, properties: dict = None):
        """
        Initialize a span link.

        Args:
            schema: The annotation scheme this link belongs to
            link_type: The type of relationship (e.g., "WORKS_FOR", "KNOWS")
            span_ids: Ordered list of span IDs that are connected by this link
            direction: "directed" or "undirected" - for directed links, order matters
            id: Optional custom ID for the link
            properties: Optional dictionary of additional properties
        """
        self.schema = schema
        self.link_type = link_type
        self.span_ids = span_ids  # Ordered list for directed links
        self.direction = direction  # "directed", "undirected"
        self.properties = properties or {}
        self._id = id if id else f"link_{uuid.uuid4().hex}"

    def get_schema(self) -> str:
        """Get the schema this link belongs to"""
        return self.schema

    def get_link_type(self) -> str:
        """Get the link type/relationship name"""
        return self.link_type

    def get_span_ids(self) -> List[str]:
        """Get the ordered list of span IDs connected by this link"""
        return self.span_ids

    def get_direction(self) -> str:
        """Get whether this link is directed or undirected"""
        return self.direction

    def get_id(self) -> str:
        """Get the link's unique identifier"""
        return self._id

    def get_properties(self) -> dict:
        """Get additional properties for this link"""
        return self.properties

    def is_directed(self) -> bool:
        """Check if this link is directed"""
        return self.direction == "directed"

    def to_dict(self) -> dict:
        """Convert the span link to a dictionary for serialization"""
        return {
            "id": self._id,
            "schema": self.schema,
            "link_type": self.link_type,
            "span_ids": self.span_ids,
            "direction": self.direction,
            "properties": self.properties
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'SpanLink':
        """Create a SpanLink from a dictionary"""
        return cls(
            schema=data["schema"],
            link_type=data["link_type"],
            span_ids=data["span_ids"],
            direction=data.get("direction", "undirected"),
            id=data.get("id"),
            properties=data.get("properties", {})
        )

    def __str__(self):
        return f"SpanLink(schema:{self.schema}, type:{self.link_type}, spans:{self.span_ids}, direction:{self.direction}, id:{self._id})"

    def __eq__(self, other):
        """Check if two span links are equal"""
        return (
            isinstance(other, SpanLink)
            and self.schema == other.schema
            and self.link_type == other.link_type
            and self.span_ids == other.span_ids
            and self.direction == other.direction
        )

    def __hash__(self):
        """Generate hash for span link (enables use in sets/dicts)"""
        return hash((self.schema, self.link_type, tuple(self.span_ids), self.direction))


class AssignmentStrategy(Enum):
    """
    Enumeration of strategies for assigning items to users.

    Different strategies optimize for different goals:
    - RANDOM: Maximizes diversity and reduces bias
    - FIXED_ORDER: Ensures consistent ordering across users
    - ACTIVE_LEARNING: Prioritizes items with high uncertainty
    - LLM_CONFIDENCE: Uses AI model confidence for prioritization
    - MAX_DIVERSITY: Prioritizes items with high disagreement
    - LEAST_ANNOTATED: Prioritizes items with fewest annotations
    - CATEGORY_BASED: Assigns items matching user's qualified categories
    - DIVERSITY_CLUSTERING: Samples items round-robin from embedding clusters
    """
    RANDOM = 'random'
    FIXED_ORDER = 'fixed_order'
    ACTIVE_LEARNING = 'active_learning'
    LLM_CONFIDENCE = 'llm_confidence'
    MAX_DIVERSITY = 'max_diversity'
    LEAST_ANNOTATED = 'least_annotated'
    CATEGORY_BASED = 'category_based'
    DIVERSITY_CLUSTERING = 'diversity_clustering'

    def fromstr(phase: str) -> AssignmentStrategy:
        """
        Convert a string representation to an AssignmentStrategy enum value.

        Args:
            phase: String representation of the strategy (case-insensitive)

        Returns:
            AssignmentStrategy: The corresponding enum value

        Raises:
            ValueError: If the string doesn't match any known strategy
        """
        phase = phase.lower()
        if phase == "random":
            return AssignmentStrategy.RANDOM
        elif phase == "fixed_order":
            return AssignmentStrategy.FIXED_ORDER
        elif phase == "active_learning":
            return AssignmentStrategy.ACTIVE_LEARNING
        elif phase == "llm_confidence":
            return AssignmentStrategy.LLM_CONFIDENCE
        elif phase == "max_diversity":
            return AssignmentStrategy.MAX_DIVERSITY
        elif phase == "least_annotated":
            return AssignmentStrategy.LEAST_ANNOTATED
        elif phase == "category_based":
            return AssignmentStrategy.CATEGORY_BASED
        elif phase == "diversity_clustering":
            return AssignmentStrategy.DIVERSITY_CLUSTERING
        else:
            raise ValueError(f"Unknown phase: {phase}")


class ItemStateManager:
    """
    A class for maintaining state on the ordering and metadata of items that are being annotated.

    This class aims to be a singleton that is shared across all users and provides the functionality
    of determining which item is next to be annotated.
    The state of the annotations themselves are stored in the UserState class.
    """

    def __init__(self, config: dict):
        """
        Initialize the item state manager.

        Args:
            config: Configuration dictionary containing item management settings
        """
        # Cache the config for later
        self.config = config
        self.logger = logging.getLogger(__name__)

        # Thread-safe lock for concurrent access to item data
        self._lock = threading.RLock()

        # This data structure keeps the ordering of the items that are being annotated
        # and a mapping from item ID to the Item object
        self.instance_id_to_instance = OrderedDict()

        self.instance_id_ordering = []

        # Load max annotations per item from config
        self.max_annotations_per_item = config.get('max_annotations_per_item', -1)

        # Track which annotators have worked on each item
        self.instance_annotators = defaultdict(set)

        # Queue of remaining instances to be assigned
        self.remaining_instance_ids = deque()

        # NOTE: We use an extra set to keep track of completed instances to allow for
        # O(1) tests of whether an item needs to be removed from the remaining list
        self.completed_instance_ids = set()

        # Initialize item annotation counts for tracking
        self.item_annotation_counts = defaultdict(int)

        # Load how we want to assign items to users
        if 'assignment_strategy' in config:
            strat = config['assignment_strategy']
            if isinstance(strat, str):
                self.assignment_strategy = AssignmentStrategy.fromstr(strat)
            elif isinstance(strat, dict):
                self.assignment_strategy = AssignmentStrategy.fromstr(strat['name'])
            else:
                raise ValueError("Invalid assignment_strategy in config")
        else:
            self.assignment_strategy = AssignmentStrategy.FIXED_ORDER

        # Set up random seed for assignment strategies
        self.random_seed = config.get('random_seed', 1234)
        self.random = random.Random(self.random_seed)
        self.logger.info(f"ItemStateManager initialized with random_seed={self.random_seed}")

        # Category-based assignment support
        item_properties = config.get('item_properties', {})
        self.category_key = item_properties.get('category_key', None)

        # Maps category name to set of instance IDs in that category
        self.category_to_instance_ids: Dict[str, Set[str]] = defaultdict(set)

        # Maps instance ID to its set of categories
        self.instance_id_to_categories: Dict[str, Set[str]] = {}

        # Instances with no category
        self.uncategorized_instance_ids: Set[str] = set()

        # Category assignment fallback behavior (loaded from category_assignment config)
        category_assignment_config = config.get('category_assignment', {})
        self.category_fallback = category_assignment_config.get('fallback', 'uncategorized')

        # Dynamic expertise mode - uses probabilistic routing based on annotator agreement
        dynamic_config = category_assignment_config.get('dynamic', {})
        self.dynamic_expertise_enabled = dynamic_config.get('enabled', False)

    def has_item(self, instance_id: str) -> bool:
        """Returns True if the item is in the state manager"""
        return instance_id in self.instance_id_to_instance

    def add_item(self, instance_id: str, instance_data: dict):
        """
        Adds a new instance to be annotated to the state manager (thread-safe).

        Args:
            instance_id: Unique identifier for the item
            instance_data: Dictionary containing the item's data

        Raises:
            ValueError: If an item with the same ID already exists
        """
        with self._lock:
            item = Item(instance_id, instance_data)
            if instance_id in self.instance_id_to_instance:
                raise ValueError(f"Duplicate Item ID! Item with ID {instance_id} already exists in the state manager")

            self.instance_id_to_instance[instance_id] = item
            self.instance_id_ordering.append(instance_id)
            self.remaining_instance_ids.append(instance_id)

            # Index categories for this item
            self._index_item_categories(instance_id, instance_data)

    def update_item(self, instance_id: str, instance_data: dict) -> bool:
        """
        Update an existing instance's data (thread-safe).

        This method updates the item_data for an existing instance while preserving
        all existing annotations (labels, span_annotations) and metadata. This is
        useful for dynamic data loading scenarios where file contents change.

        Args:
            instance_id: Unique identifier for the item to update
            instance_data: New data dictionary for the item

        Returns:
            bool: True if the item was updated, False if the item doesn't exist
        """
        with self._lock:
            if instance_id not in self.instance_id_to_instance:
                return False
            item = self.instance_id_to_instance[instance_id]
            # Update item_data while preserving labels, span_annotations, and metadata
            item.item_data = instance_data
            return True

    def add_items(self, instances: dict[str, dict]):
        """
        Given a dictionary of instance IDs to instance data, add them to the state manager.

        Args:
            instances: Dictionary mapping instance IDs to instance data dictionaries
        """
        for iid, instance_data in instances.items():
            self.add_item(iid, instance_data)

    # =========================================================================
    # Category Indexing Methods
    # =========================================================================

    def _index_item_categories(self, instance_id: str, instance_data: dict) -> None:
        """
        Extract and index categories for an item.

        Categories can be specified as a string or list of strings in the data.
        If no category_key is configured or the item has no category, it is
        added to uncategorized_instance_ids.

        Args:
            instance_id: The ID of the item
            instance_data: The item's data dictionary
        """
        if not self.category_key:
            # No category key configured, all items are uncategorized
            self.uncategorized_instance_ids.add(instance_id)
            self.instance_id_to_categories[instance_id] = set()
            return

        category_value = instance_data.get(self.category_key)

        if category_value is None:
            # Item has no category
            self.uncategorized_instance_ids.add(instance_id)
            self.instance_id_to_categories[instance_id] = set()
            return

        # Normalize to list
        if isinstance(category_value, str):
            # Treat empty/whitespace-only strings as uncategorized
            if category_value.strip():
                categories = [category_value]
            else:
                categories = []
        elif isinstance(category_value, list):
            categories = [c for c in category_value if isinstance(c, str) and c.strip()]
        else:
            self.logger.warning(
                f"Item {instance_id} has invalid category value type: {type(category_value)}. "
                f"Expected string or list of strings."
            )
            self.uncategorized_instance_ids.add(instance_id)
            self.instance_id_to_categories[instance_id] = set()
            return

        if not categories:
            # Empty category list
            self.uncategorized_instance_ids.add(instance_id)
            self.instance_id_to_categories[instance_id] = set()
            return

        # Index the categories
        category_set = set(categories)
        self.instance_id_to_categories[instance_id] = category_set

        for category in category_set:
            self.category_to_instance_ids[category].add(instance_id)

    def get_instances_by_category(self, category: str) -> Set[str]:
        """
        Get all instance IDs that belong to a specific category.

        Args:
            category: The category name

        Returns:
            Set of instance IDs in that category
        """
        with self._lock:
            return self.category_to_instance_ids.get(category, set()).copy()

    def get_instances_by_categories(self, categories: Set[str]) -> Set[str]:
        """
        Get all instance IDs that belong to any of the specified categories.

        Args:
            categories: Set of category names

        Returns:
            Set of instance IDs in any of those categories
        """
        with self._lock:
            result = set()
            for category in categories:
                result.update(self.category_to_instance_ids.get(category, set()))
            return result

    def get_categories_for_instance(self, instance_id: str) -> Set[str]:
        """
        Get all categories that an instance belongs to.

        Args:
            instance_id: The instance ID

        Returns:
            Set of category names (empty set if uncategorized)
        """
        with self._lock:
            return self.instance_id_to_categories.get(instance_id, set()).copy()

    def get_uncategorized_instances(self) -> Set[str]:
        """
        Get all instance IDs that have no category.

        Returns:
            Set of uncategorized instance IDs
        """
        with self._lock:
            return self.uncategorized_instance_ids.copy()

    def get_all_categories(self) -> Set[str]:
        """
        Get all unique category names in the system.

        Returns:
            Set of all category names
        """
        with self._lock:
            return set(self.category_to_instance_ids.keys())

    def get_category_counts(self) -> Dict[str, int]:
        """
        Get the count of instances per category.

        Returns:
            Dictionary mapping category names to instance counts
        """
        with self._lock:
            return {cat: len(ids) for cat, ids in self.category_to_instance_ids.items()}

    # =========================================================================
    # Assignment Methods
    # =========================================================================

    def assign_instances_to_user(self, user_state: UserState) -> int:
        """
        Assigns a set of instances to a user based on the current state of the system
        and returns the number of instances assigned.

        This method implements various assignment strategies to optimize annotation
        efficiency and quality. The strategy used depends on the configuration.

        If ICL verification is enabled with mix_with_regular_assignments, this method
        may include verification tasks from the ICL labeler's queue. These appear as
        regular annotation tasks (blind labeling) so users don't know they're verifying
        LLM predictions.

        Args:
            user_state: The user state object to assign instances to

        Returns:
            int: Number of instances assigned to the user

        Side Effects:
            - Updates user_state with new instance assignments
            - Updates internal tracking of item assignments
            - May modify remaining_instance_ids queue
        """
        self.logger.debug(f"Assigning instances to user {getattr(user_state, 'user_id', None)} with strategy {self.assignment_strategy} and random_seed={self.random_seed}")

        # Check if we should assign a verification task from ICL labeling
        verification_assigned = self._maybe_assign_icl_verification(user_state)
        if verification_assigned:
            # Return early if we assigned a verification task
            return verification_assigned

        # Decline to assign new items to users that have completed the maximum
        if not user_state.has_remaining_assignments():
            return 0

        # Determine how many instances to assign
        current_assignments = user_state.get_assigned_instance_count()
        max_assignments = user_state.get_max_assignments()

        if max_assignments > 0:
            remaining_capacity = max_assignments - current_assignments
            if remaining_capacity <= 0:
                return 0
            # For fixed_order strategy, assign all remaining capacity at once
            # For other strategies, use the original incremental logic
            if self.assignment_strategy == AssignmentStrategy.FIXED_ORDER:
                instances_to_assign = remaining_capacity
            else:
                # If user has less than 3 assignments, assign up to 3 more (or remaining capacity)
                if current_assignments < 3:
                    instances_to_assign = min(3, remaining_capacity)
                else:
                    # Otherwise, assign one at a time
                    instances_to_assign = 1
        else:
            # No maximum, assign one at a time
            instances_to_assign = 1

        # TODO: add strategy for assigning instances to users:
        #
        # 1) Random assignment (up to max per item/user)
        # 2) Dynamic assignment based on user performance
        # 3) Dynamic assignment based on item difficulty
        # 4) Dynamic assignment based on item diversity
        # 5) Dynamic assignment based on active learning model uncertainty
        #
        # NOTE: This method should probably be where we periodically
        # check for item re-assignment where some items are assigned
        # for a long time but never get annotated
        #
        # FOR NOW, just assign all instances to the user
        if self.assignment_strategy == AssignmentStrategy.RANDOM:
            # Random assignment strategy
            unlabeled_items = []
            for iid in self.remaining_instance_ids:
                annotation_count = len(self.instance_annotators[iid])
                self.logger.debug(f"[ASSIGNMENT] Considering {iid}: annotation_count={annotation_count}, cap={self.max_annotations_per_item}")
                # Always skip items that have reached max annotations, but do not remove here
                if self.max_annotations_per_item >= 0 and annotation_count >= self.max_annotations_per_item:
                    self.logger.debug(f"[ASSIGNMENT] Skipping {iid}: reached annotation cap")
                    continue
                if not user_state.has_annotated(iid):
                    unlabeled_items.append(iid)
                else:
                    self.logger.debug(f"User {getattr(user_state, 'user_id', None)} already annotated {iid}, skipping.")
            self.logger.debug(f"Unlabeled items for user: {unlabeled_items}")
            if not unlabeled_items:
                self.logger.info(f"No unlabeled items available for user {getattr(user_state, 'user_id', None)}")
                return 0
            to_assign = self.random.sample(unlabeled_items, min(instances_to_assign, len(unlabeled_items)))
            self.logger.debug(f"Randomly assigning items {to_assign} to user {getattr(user_state, 'user_id', None)}")
            for item_id in to_assign:
                user_state.assign_instance(self.instance_id_to_instance[item_id])
            return len(to_assign)
        elif self.assignment_strategy == AssignmentStrategy.FIXED_ORDER:
            # Fixed order assignment strategy
            assigned = 0
            for iid in list(self.remaining_instance_ids):
                if self.max_annotations_per_item >= 0 and len(self.instance_annotators[iid]) >= self.max_annotations_per_item:
                    if iid in self.remaining_instance_ids:
                        self.remaining_instance_ids.remove(iid)
                    continue
                if iid not in user_state.get_assigned_instance_ids():
                    user_state.assign_instance(self.instance_id_to_instance[iid])
                    assigned += 1
                    if assigned >= instances_to_assign:
                        break
            return assigned
        elif self.assignment_strategy == AssignmentStrategy.MAX_DIVERSITY:
            # Maximum diversity assignment strategy
            unlabeled_items = []
            for iid in list(self.remaining_instance_ids):
                if self.max_annotations_per_item >= 0 and len(self.instance_annotators[iid]) >= self.max_annotations_per_item:
                    if iid in self.remaining_instance_ids:
                        self.remaining_instance_ids.remove(iid)
                    continue
                if not user_state.has_annotated(iid):
                    unlabeled_items.append(iid)
            if not unlabeled_items:
                return 0
            # Calculate disagreement scores for each item
            item_disagreement_scores = {}
            for iid in unlabeled_items:
                disagreement_score = self._calculate_disagreement_score(iid)
                item_disagreement_scores[iid] = disagreement_score
            # Sort by disagreement score (highest first)
            sorted_items = sorted(item_disagreement_scores.keys(), key=lambda x: item_disagreement_scores[x], reverse=True)
            assigned = 0
            for item_id in sorted_items[:instances_to_assign]:
                user_state.assign_instance(self.instance_id_to_instance[item_id])
                assigned += 1
            return assigned
        elif self.assignment_strategy == AssignmentStrategy.ACTIVE_LEARNING:
            # Active learning assignment strategy (currently falls back to random)
            unlabeled_items = []
            for iid in list(self.remaining_instance_ids):
                if self.max_annotations_per_item >= 0 and len(self.instance_annotators[iid]) >= self.max_annotations_per_item:
                    if iid in self.remaining_instance_ids:
                        self.remaining_instance_ids.remove(iid)
                    continue
                if not user_state.has_annotated(iid):
                    unlabeled_items.append(iid)
            if not unlabeled_items:
                return 0
            to_assign = self.random.sample(unlabeled_items, min(instances_to_assign, len(unlabeled_items)))
            self.logger.debug(f"Active learning (random fallback): assigning items {to_assign} to user {getattr(user_state, 'user_id', None)}")
            for item_id in to_assign:
                user_state.assign_instance(self.instance_id_to_instance[item_id])
            return len(to_assign)
        elif self.assignment_strategy == AssignmentStrategy.LLM_CONFIDENCE:
            # LLM confidence assignment strategy (currently falls back to random)
            unlabeled_items = []
            for iid in list(self.remaining_instance_ids):
                if self.max_annotations_per_item >= 0 and len(self.instance_annotators[iid]) >= self.max_annotations_per_item:
                    if iid in self.remaining_instance_ids:
                        self.remaining_instance_ids.remove(iid)
                    continue
                if not user_state.has_annotated(iid):
                    unlabeled_items.append(iid)
            if not unlabeled_items:
                return 0
            to_assign = self.random.sample(unlabeled_items, min(instances_to_assign, len(unlabeled_items)))
            self.logger.debug(f"LLM confidence (random fallback): assigning items {to_assign} to user {getattr(user_state, 'user_id', None)}")
            for item_id in to_assign:
                user_state.assign_instance(self.instance_id_to_instance[item_id])
            return len(to_assign)
        elif self.assignment_strategy == AssignmentStrategy.CATEGORY_BASED:
            # Category-based assignment strategy
            user_id = getattr(user_state, 'user_id', None)

            # Check if dynamic expertise mode is enabled
            if self.dynamic_expertise_enabled:
                return self._assign_category_based_dynamic(user_state, instances_to_assign)

            # Standard category-based assignment using qualification
            # Assigns instances from categories the user has qualified for
            qualified_categories = user_state.get_qualified_categories()

            self.logger.debug(f"Category-based assignment for user {user_id}, qualified categories: {qualified_categories}")

            # Get candidate instances from qualified categories
            candidate_ids = set()
            if qualified_categories:
                for category in qualified_categories:
                    candidate_ids.update(self.category_to_instance_ids.get(category, set()))

            # If no candidates from categories, apply fallback behavior
            if not candidate_ids:
                self.logger.debug(f"No category matches for user {user_id}, using fallback: {self.category_fallback}")
                if self.category_fallback == 'uncategorized':
                    candidate_ids = self.uncategorized_instance_ids.copy()
                elif self.category_fallback == 'random':
                    candidate_ids = set(self.remaining_instance_ids)
                # 'none' fallback means no assignment

            # Filter candidates: not already annotated by user, not completed
            unlabeled_items = []
            for iid in candidate_ids:
                # Skip if item is not in remaining (already completed)
                if iid not in self.remaining_instance_ids:
                    continue
                # Skip if item has reached max annotations
                if self.max_annotations_per_item >= 0 and len(self.instance_annotators[iid]) >= self.max_annotations_per_item:
                    continue
                # Skip if user already annotated this item
                if not user_state.has_annotated(iid):
                    unlabeled_items.append(iid)

            self.logger.debug(f"Category-based: {len(unlabeled_items)} unlabeled items available for user {user_id}")

            if not unlabeled_items:
                return 0

            # Randomly sample from eligible items (can be combined with other sub-strategies in future)
            to_assign = self.random.sample(unlabeled_items, min(instances_to_assign, len(unlabeled_items)))
            self.logger.debug(f"Category-based: assigning items {to_assign} to user {user_id}")

            for item_id in to_assign:
                user_state.assign_instance(self.instance_id_to_instance[item_id])

            return len(to_assign)
        elif self.assignment_strategy == AssignmentStrategy.DIVERSITY_CLUSTERING:
            # Diversity clustering assignment strategy
            from potato.diversity_manager import get_diversity_manager
            dm = get_diversity_manager()

            if dm and dm.enabled:
                # Get user's annotated items for preservation
                annotated_ids = set(user_state.get_annotated_instance_ids()) if hasattr(user_state, 'get_annotated_instance_ids') else set()

                # Get available items (respecting max_annotations_per_item)
                available_ids = []
                for iid in self.remaining_instance_ids:
                    # Skip if item has reached annotation limit
                    if self.max_annotations_per_item >= 0 and len(self.instance_annotators[iid]) >= self.max_annotations_per_item:
                        continue
                    # Skip if user already annotated
                    if user_state.has_annotated(iid):
                        continue
                    available_ids.append(iid)

                if not available_ids:
                    return 0

                # Get user_id for diversity manager
                user_id = getattr(user_state, 'user_id', 'anonymous')

                # Generate diverse ordering with preserved positions
                diverse_order = dm.apply_to_user_ordering(
                    user_id, available_ids, annotated_ids
                )

                # Assign items from diverse order
                assigned = 0
                for item_id in diverse_order[:instances_to_assign]:
                    user_state.assign_instance(self.instance_id_to_instance[item_id])
                    assigned += 1

                return assigned
            else:
                # Fallback to random if diversity manager unavailable
                self.logger.debug("Diversity manager not available, falling back to random")
                return self._assign_random_fallback(user_state, instances_to_assign)
        else:
            # Default fallback to fixed order
            self.logger.warning(f"Unknown assignment strategy: {self.assignment_strategy}, falling back to fixed order")
            return self.assign_instances_to_user_fixed_order(user_state, instances_to_assign)

    def _assign_category_based_dynamic(self, user_state: 'UserState', instances_to_assign: int) -> int:
        """
        Dynamic category-based assignment using probabilistic routing.

        In dynamic mode, users can receive instances from ALL categories, but are
        more likely to get instances from categories they have demonstrated expertise
        in (based on agreement with other annotators).

        Args:
            user_state: The user state to assign instances to
            instances_to_assign: Number of instances to assign

        Returns:
            int: Number of instances actually assigned
        """
        from potato.expertise_manager import get_expertise_manager

        user_id = getattr(user_state, 'user_id', None)
        expertise_manager = get_expertise_manager()

        if not expertise_manager:
            # Fallback to random if expertise manager not available
            self.logger.warning("ExpertiseManager not available, falling back to random assignment")
            return self._assign_random_fallback(user_state, instances_to_assign)

        assigned_count = 0

        for _ in range(instances_to_assign):
            # Find categories with available (unlabeled) instances for this user
            available_categories = set()
            category_to_eligible_items: Dict[str, List[str]] = {}

            for category, instance_ids in self.category_to_instance_ids.items():
                eligible_items = []
                for iid in instance_ids:
                    # Skip if item is not in remaining (already completed)
                    if iid not in self.remaining_instance_ids:
                        continue
                    # Skip if item has reached max annotations
                    if self.max_annotations_per_item >= 0 and len(self.instance_annotators[iid]) >= self.max_annotations_per_item:
                        continue
                    # Skip if user already annotated this item
                    if not user_state.has_annotated(iid):
                        eligible_items.append(iid)

                if eligible_items:
                    available_categories.add(category)
                    category_to_eligible_items[category] = eligible_items

            # Also check uncategorized instances
            uncategorized_eligible = []
            for iid in self.uncategorized_instance_ids:
                if iid not in self.remaining_instance_ids:
                    continue
                if self.max_annotations_per_item >= 0 and len(self.instance_annotators[iid]) >= self.max_annotations_per_item:
                    continue
                if not user_state.has_annotated(iid):
                    uncategorized_eligible.append(iid)

            if not available_categories and not uncategorized_eligible:
                # No more instances available
                break

            # Use ExpertiseManager to probabilistically select a category
            if available_categories:
                selected_category = expertise_manager.select_category_probabilistically(
                    user_id,
                    available_categories,
                    random_instance=self.random
                )
            else:
                selected_category = None

            # Get an instance from the selected category (or uncategorized)
            if selected_category and selected_category in category_to_eligible_items:
                eligible_items = category_to_eligible_items[selected_category]
                selected_item = self.random.choice(eligible_items)
            elif uncategorized_eligible:
                selected_item = self.random.choice(uncategorized_eligible)
            else:
                break

            # Assign the selected instance
            user_state.assign_instance(self.instance_id_to_instance[selected_item])
            assigned_count += 1

            self.logger.debug(
                f"Dynamic category assignment: assigned {selected_item} "
                f"(category={selected_category}) to user {user_id}"
            )

        return assigned_count

    def _assign_random_fallback(self, user_state: 'UserState', instances_to_assign: int) -> int:
        """Fallback to random assignment when expertise manager is not available."""
        unlabeled_items = []
        for iid in self.remaining_instance_ids:
            if self.max_annotations_per_item >= 0 and len(self.instance_annotators[iid]) >= self.max_annotations_per_item:
                continue
            if not user_state.has_annotated(iid):
                unlabeled_items.append(iid)

        if not unlabeled_items:
            return 0

        to_assign = self.random.sample(unlabeled_items, min(instances_to_assign, len(unlabeled_items)))
        for item_id in to_assign:
            user_state.assign_instance(self.instance_id_to_instance[item_id])

        return len(to_assign)

    def _calculate_disagreement_score(self, instance_id: str) -> float:
        """
        Calculate a disagreement score for an instance based on existing annotations.

        This method analyzes the annotations for a given instance and calculates
        a score indicating how much disagreement exists among annotators.
        Higher scores indicate more disagreement, which suggests the item
        might be more difficult or ambiguous to annotate.

        Args:
            instance_id: The ID of the instance to calculate disagreement for

        Returns:
            float: Disagreement score (higher = more disagreement)
        """
        # This is a placeholder implementation
        # In a real implementation, you would:
        # 1. Get all annotations for this instance
        # 2. Calculate disagreement metrics (e.g., Krippendorff's alpha)
        # 3. Return a normalized score

        # For now, return a random score as placeholder
        return self.random.random()

    def _maybe_assign_icl_verification(self, user_state: 'UserState') -> int:
        """
        Maybe assign an ICL verification task to the user.

        This implements "blind labeling" - the user receives an instance that was
        already labeled by the LLM, but they don't know it's a verification task.
        After they annotate it, we compare their label to the LLM's prediction.

        Args:
            user_state: The user state to potentially assign to

        Returns:
            int: Number of verification instances assigned (0 or 1)
        """
        # Check if ICL labeling is enabled
        icl_config = self.config.get('icl_labeling', {})
        if not icl_config.get('enabled', False):
            return 0

        # Check if verification is enabled with mixed assignments
        verification_config = icl_config.get('verification', {})
        if not verification_config.get('enabled', True):
            return 0
        if not verification_config.get('mix_with_regular_assignments', True):
            return 0

        # Probabilistic check - only assign verification ~20% of the time
        # This ensures users still get regular tasks most of the time
        verification_mix_rate = verification_config.get('assignment_mix_rate', 0.2)
        if self.random.random() > verification_mix_rate:
            return 0

        try:
            from potato.ai.icl_labeler import get_icl_labeler
            icl_labeler = get_icl_labeler()
            if icl_labeler is None:
                return 0

            # Get pending verifications that this user hasn't already annotated
            pending = icl_labeler.get_pending_verifications(count=5)
            user_id = getattr(user_state, 'user_id', None)

            for instance_id, schema_name in pending:
                # Skip if user already annotated this instance
                if user_state.has_annotated(instance_id):
                    continue

                # Skip if instance is already assigned to user
                if instance_id in user_state.get_assigned_instance_ids():
                    continue

                # Check if instance exists in our manager
                if instance_id not in self.instance_id_to_instance:
                    continue

                # Assign the verification instance
                item = self.instance_id_to_instance[instance_id]
                user_state.assign_instance(item)

                # Mark this as a verification task in the user's metadata
                # This is stored privately so we can record verification after annotation
                user_state.mark_instance_as_verification(instance_id, schema_name)

                self.logger.info(
                    f"Assigned ICL verification task {instance_id} to user {user_id}"
                )
                return 1

        except ImportError:
            # ICL labeler module not available
            pass
        except Exception as e:
            self.logger.warning(f"Error assigning ICL verification: {e}")

        return 0

    def generate_id_order_mapping(self):
        """Generate a mapping from instance IDs to their order"""
        return {iid: idx for idx, iid in enumerate(self.instance_id_ordering)}

    def get_next_instance_id(self, user_state: UserState) -> str:
        """
        Get the next instance ID for a user based on the assignment strategy.

        Args:
            user_state: The user state to get the next instance for

        Returns:
            str: The next instance ID, or None if no more instances available
        """
        # This method would implement the logic to determine which instance
        # should be next for a given user based on the assignment strategy
        # For now, it's a placeholder
        return None

    def get_instance_ids(self) -> list[str]:
        """Get all instance IDs in the manager"""
        return list(self.instance_id_to_instance.keys())

    def get_item(self, instance_id: str) -> Item:
        """Get an item by its ID"""
        return self.instance_id_to_instance[instance_id]

    def get_annotators_for_item(self, instance_id: str) -> set[str]:
        """Get the set of annotators who have worked on this item"""
        return self.instance_annotators[instance_id]

    def get_total_assignable_items_for_user(self, user_state: UserState) -> int:
        """
        Get the total number of items that can be assigned to a user.

        This takes into account:
        - Items the user hasn't already annotated
        - Items that haven't reached their annotation limit
        - Items that are still available for assignment

        Args:
            user_state: The user state to check assignments for

        Returns:
            int: Number of items that can be assigned
        """
        count = 0
        for iid in self.remaining_instance_ids:
            # Check if item has reached annotation limit
            if self.max_annotations_per_item >= 0 and len(self.instance_annotators[iid]) >= self.max_annotations_per_item:
                continue
            # Check if user has already annotated this item
            if user_state.has_annotated(iid):
                continue
            count += 1
        return count

    def items(self) -> list[Item]:
        """Get all items in the manager"""
        return list(self.instance_id_to_instance.values())

    def register_annotator(self, instance_id: str, user_id: str):
        """
        Register that a user has annotated an instance.

        This method updates the tracking of which users have worked on which
        items, and may trigger cleanup of completed items.

        Args:
            instance_id: The ID of the instance that was annotated
            user_id: The ID of the user who did the annotation

        Side Effects:
            - Updates instance_annotators tracking
            - May remove items from remaining_instance_ids if they reach limits
            - Updates item_annotation_counts
        """
        # Add user to the set of annotators for this item
        self.instance_annotators[instance_id].add(user_id)

        # Update annotation count
        self.item_annotation_counts[instance_id] += 1

        # Check if this item has reached its annotation limit
        if self.max_annotations_per_item >= 0 and len(self.instance_annotators[instance_id]) >= self.max_annotations_per_item:
            # Remove from remaining instances if it's there
            if instance_id in self.remaining_instance_ids:
                self.remaining_instance_ids.remove(instance_id)
            # Mark as completed
            self.completed_instance_ids.add(instance_id)

    def update_annotation_count(self, instance_id: str, delta=1):
        """
        Update the annotation count for an instance.

        Args:
            instance_id: The ID of the instance to update
            delta: The change in annotation count (default: +1)
        """
        self.item_annotation_counts[instance_id] += delta

    def reorder_instances(self, new_order: List[str]):
        """
        Reorder instances based on active learning predictions.

        Args:
            new_order: List of instance IDs in the new desired order

        Note:
            This method preserves instances that are not in the new_order list
            by appending them to the end of the ordering.
        """
        # Create a set of instances in the new order for efficient lookup
        new_order_set = set(new_order)

        # Filter out instances that don't exist in our manager
        valid_new_order = [instance_id for instance_id in new_order if instance_id in self.instance_id_to_instance]

        # Find instances that are not in the new order
        remaining_instances = [instance_id for instance_id in self.instance_id_ordering if instance_id not in new_order_set]

        # Combine the new order with remaining instances
        self.instance_id_ordering = valid_new_order + remaining_instances

        # Update the remaining_instance_ids queue to match the new ordering
        self.remaining_instance_ids.clear()
        for instance_id in self.instance_id_ordering:
            if instance_id not in self.completed_instance_ids:
                self.remaining_instance_ids.append(instance_id)

        self.logger.info(f"Reordered {len(valid_new_order)} instances, {len(remaining_instances)} instances preserved")

    def clear(self):
        """Clear all data from the manager (for testing)"""
        self.instance_id_to_instance.clear()
        self.instance_id_ordering.clear()
        self.remaining_instance_ids.clear()
        self.completed_instance_ids.clear()
        self.instance_annotators.clear()
        self.item_annotation_counts.clear()
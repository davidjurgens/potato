from __future__ import annotations

# Need to import UserState as a type hint for the ItemStateManager
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from potato.user_state_management import UserState

from enum import Enum
from collections import OrderedDict, deque, Counter, defaultdict
import random
import uuid
import logging

# Singleton instance of the ItemStateManager
ITEM_STATE_MANAGER = None

def init_item_state_manager(config: dict) -> ItemStateManager:
    # TODO: make the manager type configurable between in-memory and DB-backed.
    # The DB back-end is for when we have a ton of data and don't want it sitting in
    # memory all the time (or where some external process is going to be adding new items)
    global ITEM_STATE_MANAGER

    if ITEM_STATE_MANAGER is None:
        ITEM_STATE_MANAGER = ItemStateManager(config)

    return ITEM_STATE_MANAGER

def clear_item_state_manager():
    '''
    Clear the singleton item state manager instance (for testing).
    '''
    global ITEM_STATE_MANAGER
    ITEM_STATE_MANAGER = None

def get_item_state_manager() -> ItemStateManager:
    # TODO: make the manager type configurable between in-memory and DB-backed.
    # The DB back-end is for when we have a ton of data and don't want it sitting in
    # memory all the time (or where some external process is going to be adding new items)
    global ITEM_STATE_MANAGER

    if ITEM_STATE_MANAGER is None:
        raise ValueError("Item State Manager has not been initialized yet!")

    return ITEM_STATE_MANAGER

class Item:
    """
    A class for maintaining state on items that are being annotated.
    The state of the annotations themselves are stored in the UserState class.
    The item iself is largely immutable but can be updated with metadata.
    """

    def __init__(self, item_id, item_data):
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
        self.metadata[metadata_name] = metadata_value

    def get_id(self):
        return self.item_id

    def get_data(self):
        return self.item_data

    def get_text(self):
        """Get the text content from the item data"""
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
        return self.metadata.get(metadata_name, None)

    def __str__(self):
        return f"Item(id:{self.item_id}, data:{self.item_data}, metadata:{self.metadata})"

class Label:
    '''A utility class for representing a single label in any annotation scheme. Labels
       may have a integer value (likert), a string value (text), or a boolean value (binary).
       Span annotations are represented with a different class.'''
    def __init__(self, schema: str, label_name: str):
        self.schema = schema
        self.label_name = label_name

    def get_schema(self):
        return self.schema

    def get_name(self):
        return self.label_name

    def __str__(self):
        return f"Label(schema:{self.schema}, name:{self.label_name})"

    def __eq__(self, other):
        return self.schema == other.schema and self.label_name == other.label_name

    def __hash__(self):
        return hash((self.schema, self.label_name))

class SpanAnnotation:
    '''A utility class for representing a single span annotation in any annotation scheme. Spans
       are represented by a start and end index, as well as a label.'''
    def __init__(self, schema: str, name: str, title: str, start: int, end: int, id: str = None, annotation_id: str = None):
        self.schema = schema
        self.start = start
        self.title = title
        self.end = end
        self.name = name
        # Accept both id and annotation_id
        _id = id if id is not None else annotation_id
        if _id is not None:
            self._id = _id
        else:
            self._id = f"span_{uuid.uuid4().hex}"

    def get_schema(self):
        return self.schema

    def get_start(self):
        return self.start

    def get_end(self):
        return self.end

    def get_name(self):
        return self.name

    def get_title(self):
        return self.title

    def get_id(self):
        return self._id

    def __str__(self):
        return f"SpanAnnotation(schema:{self.schema}, name:{self.name}, start:{self.start}, end:{self.end}, id:{self._id})"

    def __eq__(self, other):
        return self.schema == other.schema and self.start == other.start and self.end == other.end \
            and self.name == other.name

    def __hash__(self):
        return hash((self.schema, self.start, self.end, self.name))

class AssignmentStrategy(Enum):
    RANDOM = 'random'
    FIXED_ORDER = 'fixed_order'
    ACTIVE_LEARNING = 'active_learning'
    LLM_CONFIDENCE = 'llm_confidence'
    MAX_DIVERSITY = 'max_diversity'
    LEAST_ANNOTATED = 'least_annotated'

    def fromstr(phase: str) -> AssignmentStrategy:
        '''Converts a string to a UserPhase enum'''
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

        # Cache the config for later
        self.config = config
        self.logger = logging.getLogger(__name__)

        # This data structure keeps the ordering of the items that are being annotated
        # and a mapping from item ID to the Item object
        self.instance_id_to_item = OrderedDict()

        self.instance_id_ordering = []

        # Load max annotations per item from config
        self.max_annotations_per_item = config.get('max_annotations_per_item', -1)

        self.item_annotators = defaultdict(set)

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

    def has_item(self, instance_id: str) -> bool:
        '''Returns True if the item is in the state manager'''
        return instance_id in self.instance_id_to_item

    def add_item(self, instance_id: str, item_data: dict):
        '''Adds a new item to be annotated to the state manager'''
        item = Item(instance_id, item_data)
        if instance_id in self.instance_id_to_item:
            raise ValueError(f"Duplicate Item ID! Item with ID {instance_id} already exists in the state manager")

        self.instance_id_to_item[instance_id] = item
        self.instance_id_ordering.append(instance_id)
        self.remaining_instance_ids.append(instance_id)

    def add_items(self, items: dict[str, dict]):
        '''Given a dictionary of item IDs to item data, add them to the state manager'''
        for iid, item_data in items.items():
            self.add_item(iid, item_data)

    def assign_instances_to_user(self, user_state: UserState) -> int:
        '''Assigns a set of instances to a user based on the current state of the system
        and returns the number of instances assigned'''
        self.logger.debug(f"Assigning instances to user {getattr(user_state, 'user_id', None)} with strategy {self.assignment_strategy} and random_seed={self.random_seed}")

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
            unlabeled_items = []
            for iid in self.remaining_instance_ids:
                annotation_count = len(self.item_annotators[iid])
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
                user_state.assign_instance(self.instance_id_to_item[item_id])
            return len(to_assign)
        elif self.assignment_strategy == AssignmentStrategy.FIXED_ORDER:
            assigned = 0
            for iid in list(self.remaining_instance_ids):
                if self.max_annotations_per_item >= 0 and len(self.item_annotators[iid]) >= self.max_annotations_per_item:
                    if iid in self.remaining_instance_ids:
                        self.remaining_instance_ids.remove(iid)
                    continue
                if iid not in user_state.get_assigned_instance_ids():
                    user_state.assign_instance(self.instance_id_to_item[iid])
                    assigned += 1
                    if assigned >= instances_to_assign:
                        break
            return assigned
        elif self.assignment_strategy == AssignmentStrategy.MAX_DIVERSITY:
            unlabeled_items = []
            for iid in list(self.remaining_instance_ids):
                if self.max_annotations_per_item >= 0 and len(self.item_annotators[iid]) >= self.max_annotations_per_item:
                    if iid in self.remaining_instance_ids:
                        self.remaining_instance_ids.remove(iid)
                    continue
                if not user_state.has_annotated(iid):
                    unlabeled_items.append(iid)
            if not unlabeled_items:
                return 0
            item_disagreement_scores = {}
            for iid in unlabeled_items:
                disagreement_score = self._calculate_disagreement_score(iid)
                item_disagreement_scores[iid] = disagreement_score
            sorted_items = sorted(item_disagreement_scores.keys(), key=lambda x: item_disagreement_scores[x], reverse=True)
            assigned = 0
            for item_id in sorted_items[:instances_to_assign]:
                user_state.assign_instance(self.instance_id_to_item[item_id])
                assigned += 1
            return assigned
        elif self.assignment_strategy == AssignmentStrategy.ACTIVE_LEARNING:
            unlabeled_items = []
            for iid in list(self.remaining_instance_ids):
                if self.max_annotations_per_item >= 0 and len(self.item_annotators[iid]) >= self.max_annotations_per_item:
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
                user_state.assign_instance(self.instance_id_to_item[item_id])
            return len(to_assign)
        elif self.assignment_strategy == AssignmentStrategy.LLM_CONFIDENCE:
            unlabeled_items = []
            for iid in list(self.remaining_instance_ids):
                if self.max_annotations_per_item >= 0 and len(self.item_annotators[iid]) >= self.max_annotations_per_item:
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
                user_state.assign_instance(self.instance_id_to_item[item_id])
            return len(to_assign)
        elif self.assignment_strategy == AssignmentStrategy.LEAST_ANNOTATED:
            unlabeled_items = []
            for iid in list(self.remaining_instance_ids):
                if self.max_annotations_per_item >= 0 and len(self.item_annotators[iid]) >= self.max_annotations_per_item:
                    if iid in self.remaining_instance_ids:
                        self.remaining_instance_ids.remove(iid)
                    continue
                if not user_state.has_annotated(iid):
                    unlabeled_items.append(iid)
            if not unlabeled_items:
                return 0
            item_annotation_counts = {}
            for iid in unlabeled_items:
                item_annotation_counts[iid] = len(self.item_annotators[iid])
            sorted_items = sorted(item_annotation_counts.keys(), key=lambda x: item_annotation_counts[x])
            assigned = 0
            for item_id in sorted_items[:instances_to_assign]:
                user_state.assign_instance(self.instance_id_to_item[item_id])
                assigned += 1
            return assigned
        else:
            print("Unsupported assignment strategy: %s" % self.assignment_strategy)
            raise ValueError("Unsupported assignment strategy, %s" % self.assignment_strategy)

    def _calculate_disagreement_score(self, instance_id: str) -> float:
        """
        Calculate disagreement score for an item based on existing annotations.
        Higher score means more disagreement/diversity in annotations.
        """
        if instance_id not in self.item_annotators:
            return 0.0

        # Get all annotations for this item
        all_annotations = []
        for user_id in self.item_annotators[instance_id]:
            # Use lazy import to avoid circular import
            from potato.user_state_management import get_user_state_manager
            user_state = get_user_state_manager().get_user_state(user_id)
            if user_state and user_state.has_annotated(instance_id):
                annotations = user_state.get_label_annotations(instance_id)
                all_annotations.extend(annotations.values())

        if not all_annotations:
            return 0.0

        # Calculate disagreement based on annotation diversity
        # For now, use a simple approach: count unique annotations
        unique_annotations = set(str(ann) for ann in all_annotations)
        total_annotations = len(all_annotations)

        if total_annotations == 0:
            return 0.0

        # Disagreement score: ratio of unique annotations to total annotations
        # Higher ratio = more disagreement
        disagreement_score = len(unique_annotations) / total_annotations

        return disagreement_score


    def generate_id_order_mapping(self):
        pass

    def get_next_instance_id(self, user_state: UserState) -> str:
        '''Returns the ID of the next instance that should be annotated based on
           the system configuration and the total current annotation state'''

        already_annotated_ids = user_state.get_labeled_instance_ids()

        # Check that the user hasn't already annotated too many items
        if user_state.get_max_assignments() > 0 \
            and len(already_annotated_ids) >= user_state.get_max_assignments():
            return None

        # TODO: add support for item sampling strategy here. Notably, random next-item selection

        for inst_id in self.remaining_instance_ids:
            if inst_id not in already_annotated_ids:
                return inst_id

        return None

    def get_instance_ids(self) -> list[str]:
        '''Returns the list of all known instance IDs'''
        return self.instance_id_ordering

    def get_item(self, instance_id: str) -> Item:
        '''Returns the Item object for a given instance ID'''
        return self.instance_id_to_item[instance_id]

    def get_annotators_for_item(self, instance_id: str) -> set[str]:
        '''Returns the set of annotators who have annotated a given item'''
        return self.item_annotators.get(instance_id, set())

    def get_total_assignable_items_for_user(self, user_state: UserState) -> int:
        '''Returns the total number of items that will be assigned to a user based on:
        1. User's max_assignments limit
        2. Available items in the dataset
        3. Max annotations per item constraint
        '''
        max_assignments = user_state.get_max_assignments()

        # If user has a specific limit, that's the total
        if max_assignments > 0:
            return max_assignments

        # For unlimited assignments, calculate based on available items
        # that the user hasn't already annotated
        available_items = 0
        for iid in self.remaining_instance_ids:
            # Skip items that have reached max annotations
            if self.max_annotations_per_item >= 0 and len(self.item_annotators[iid]) >= self.max_annotations_per_item:
                continue
            # Skip items the user has already annotated
            if user_state.has_annotated(iid):
                continue
            available_items += 1

        return available_items

    def items(self) -> list[Item]:
        '''Returns a list of all Item objects'''
        return list(self.instance_id_to_item.values())

    def register_annotator(self, instance_id: str, user_id: str):
        '''Registers that a user has annotated an item'''

        print(f"[REGISTER_ANNOTATOR] Called for instance_id={instance_id}, user_id={user_id}")

        if instance_id not in self.instance_id_to_item:
            raise ValueError(f"Unknown instance ID: {instance_id}")

        print(f"[REGISTER_ANNOTATOR] Pool before: {list(self.remaining_instance_ids)}")
        self.logger.debug(f"[REGISTER_ANNOTATOR] Pool before: {list(self.remaining_instance_ids)}")
        # Check for duplicates
        pool_list = list(self.remaining_instance_ids)
        if len(pool_list) != len(set(pool_list)):
            self.logger.warning(f"[REGISTER_ANNOTATOR] Duplicate entries found in remaining_instance_ids: {pool_list}")

        self.item_annotators[instance_id].add(user_id)
        print(f"[REGISTER_ANNOTATOR] Added {user_id} to annotators for {instance_id}. Current annotators: {list(self.item_annotators[instance_id])}")

        # If we allow unlimited annotations per item
        if self.max_annotations_per_item < 0:
            print(f"[REGISTER_ANNOTATOR] Unlimited annotations allowed, returning")
            return

        # Remove this instance from the remaining list if it has been annotated enough
        current_count = len(self.item_annotators[instance_id])
        print(f"[REGISTER_ANNOTATOR] Current annotation count for {instance_id}: {current_count}, max: {self.max_annotations_per_item}")

        if current_count >= self.max_annotations_per_item:
            if instance_id in self.remaining_instance_ids:
                self.remaining_instance_ids.remove(instance_id)
                print(f"[REGISTER_ANNOTATOR] Removed {instance_id} from remaining_instance_ids after reaching cap. Pool now: {list(self.remaining_instance_ids)}")
                self.logger.debug(f"[REGISTER_ANNOTATOR] Removed {instance_id} from remaining_instance_ids after reaching cap. Pool now: {list(self.remaining_instance_ids)}")
            else:
                print(f"[REGISTER_ANNOTATOR] {instance_id} not in remaining_instance_ids at cap time. Pool: {list(self.remaining_instance_ids)}")
                self.logger.debug(f"[REGISTER_ANNOTATOR] {instance_id} not in remaining_instance_ids at cap time. Pool: {list(self.remaining_instance_ids)}")
        else:
            print(f"[REGISTER_ANNOTATOR] {instance_id} not at cap yet ({current_count}/{self.max_annotations_per_item})")

        print(f"[REGISTER_ANNOTATOR] Pool after: {list(self.remaining_instance_ids)}")
        self.logger.debug(f"[REGISTER_ANNOTATOR] Pool after: {list(self.remaining_instance_ids)}")

    def update_annotation_count(self, instance_id: str, delta=1):
        if self.max_annotations_per_item < 0:
            return

        # Otherwise, update the count
        self.item_annotation_counts[instance_id] += delta

        # Remove this instance from the remaining list if it has been annotated enough
        if self.item_annotation_counts[instance_id] >= self.max_annotations_per_item:
            if instance_id not in self.completed_instance_ids:
                self.completed_instance_ids.add(instance_id)
                self.remaining_instance_ids.remove(instance_id)

    def clear(self):
        """Clear all item state (for testing/debugging)."""
        print(f"[DEBUG] ItemStateManager attributes before clear: {list(self.__dict__.keys())}")
        # Only clear attributes that exist
        for attr in [
            'instance_id_to_item',
            'instance_id_ordering',
            'item_annotators',
            'item_annotation_counts',
            'remaining_instance_ids',
            'completed_instance_ids',
        ]:
            if hasattr(self, attr):
                getattr(self, attr).clear()
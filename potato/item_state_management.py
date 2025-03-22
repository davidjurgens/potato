from __future__ import annotations

# Need to import UserState as a type hint for the ItemStateManager
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from user_state_management import UserState

from enum import Enum
from collections import OrderedDict, deque, Counter, defaultdict
import random

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
    def __init__(self, schema: str, name: str, title: str, start: int, end: int):
        self.schema = schema
        self.start = start
        self.title = title
        self.end = end
        self.name = name

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

    def __str__(self):
        return f"SpanAnnotation(schema:{self.schema}, name:{self.name}, start:{self.start}, end:{self.end})"

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

        # This data structure keeps the ordering of the items that are being annotated
        # and a mapping from item ID to the Item object
        self.instance_id_to_item = OrderedDict()

        self.instance_id_ordering = []

        # TODO: load this from the config
        self.max_annotations_per_item = -1

        self.item_annotators = defaultdict(set)

        self.remaining_instance_ids = deque()

        # NOTE: We use an extra set to keep track of completed instances to allow for
        # O(1) tests of whether an item needs to be removed from the remaining list
        self.completed_instance_ids = set()

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

        # Decline to assign new items to users that have completed the maximum
        if not user_state.has_remaining_assignments():
            return 0

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
            # TODO: make this a lot more efficient
            unlabeled_items = [iid for iid in self.remaining_instance_ids if not user_state.has_annotated(iid)]
            to_assign = random.sample(unlabeled_items, 1)
            print("assigning item %s to user %s" % (to_assign.get_id(), user_state.get_user_id()))
            user_state.assign_instance(self.instance_id_to_item[to_assign])
            return 1
        elif self.assignment_strategy == AssignmentStrategy.FIXED_ORDER:
            for iid in self.remaining_instance_ids:
                if not user_state.has_annotated(iid):
                    print("assigning item %s to user %s" % (iid, user_state.get_user_id()))
                    user_state.assign_instance(self.instance_id_to_item[iid])
                    return 1
            return 0
        else:
            raise ValueError("Unsupported assignment strategy, %s" % self.assignment_strategy)


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

    def items(self) -> list[Item]:
        '''Returns a list of all Item objects'''
        return list(self.instance_id_to_item.values())

    def register_annotator(self, instance_id: str, user_id: str):
        '''Registers that a user has annotated an item'''

        if instance_id not in self.instance_id_to_item:
            raise ValueError(f"Unknown instance ID: {instance_id}")

        self.item_annotators[instance_id].add(user_id)

        # If we allow unlimited annotations per item
        if self.max_annotations_per_item < 0:
            return

        # Remove this instance from the remaining list if it has been annotated enough
        #
        # NOTE: We keep track of the number of annotators for each item, rather than the
        # number of annotations because users register annotations dynamically and some
        # items may receive multiple updates (e.g., a user edits their annotation), so
        # we don't want to double count those.
        if len(self.item_annotators[instance_id]) >= self.max_annotations_per_item:
            self.remaining_instance_ids.remove(instance_id)

    def update_annotation_count(self, instance_id: str, delta=1):
        if self.max_annotations_per_item < 0:
            return

        # Otherwise, udpate the count
        self.item_annotation_counts[instance_id] += delta

        # Remove this instance from the remaining list if it has been annotated enough
        if self.item_annotation_counts[instance_id] >= self.max_annotations_per_item:
            if instance_id not in self.completed_instance_ids:
                self.completed_instance_ids.add(instance_id)
                self.remaining_instance_ids.remove(instance_id)
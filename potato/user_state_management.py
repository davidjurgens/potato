from __future__ import annotations

import json
from collections import defaultdict, OrderedDict
import logging
import os

import logging

from authentificaton import UserAuthenticator
from phase import UserPhase

from item_state_management import get_item_state_manager, Item, SpanAnnotation, Label

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logging.basicConfig()



# Singleton instance of the user state manager
USER_STATE_MANAGER = None

@staticmethod
def init_user_state_manager(config: dict) -> UserStateManager:
    '''
    Returns the manager for tracking all the users' states in where they are in the annotation process.
    '''
    global USER_STATE_MANAGER

    if USER_STATE_MANAGER is None:
        USER_STATE_MANAGER = UserStateManager(config)
    return USER_STATE_MANAGER

def get_user_state_manager() -> UserStateManager:
    '''
    Returns the manager for tracking all the users' states in where they are in the annotation process.
    '''
    global USER_STATE_MANAGER

    if USER_STATE_MANAGER is None:
        raise ValueError('User state manager has not been initialized')
    return USER_STATE_MANAGER

class UserStateManager:
    '''Manages all the users'''


    def __init__(self, config: dict):
        self.config = config
        self.user_to_annotation_state = {}
        self.task_assignment = {}
        self.prolific_study = None
        self.phase_type_to_name_to_page = defaultdict(OrderedDict)


        # TODO: load this from the config
        self.max_annotations_per_user = -1

        self.logger = logging.getLogger(__name__)
        # setting to debug
        self.logger.setLevel(logging.DEBUG)
        logging.basicConfig()



    def add_phase(self, phase_type: UserPhase, phase_name: str, page_fname: str):
        self.phase_type_to_name_to_page[phase_type][phase_name] = page_fname

    def add_user(self, user_id: str) -> UserState:
        '''Adds a user to the user state manager'''

        if user_id in self.user_to_annotation_state:
            raise ValueError(f'User "{user_id}" already exists in the user state manager')

        # TODO: make the user state type configurable between in-memory and DB-backed.
        user_state = InMemoryUserState(user_id, self.max_annotations_per_user)
        self.user_to_annotation_state[user_id] = user_state

        return user_state

    def get_or_create_user(self, user_id: str) -> UserState:
        '''Gets a user from the user state manager, creating a new user if they don't exist'''
        if user_id not in self.user_to_annotation_state:
            self.logger.debug('Previously unknown user "%s"; creating new annotation state' % (user_id))
            user_state = self.add_user(user_id)
        else:
            user_state = self.user_to_annotation_state[user_id]
        return user_state

    def get_max_annotations_per_user(self) -> int:
        '''Returns the maximum number of items that each annotator should annotate'''
        return self.max_annotations_per_user

    def set_max_annotations_per_user(self, max_annotations_per_user: int) -> None:
        '''Sets the maximum number of items that each annotator should annotate'''
        self.max_annotations_per_user = max_annotations_per_user

    def old_get_or_create_user(self, user_id: str) -> UserState:
        if user_id not in self.user_to_annotation_state:
            self.logger.debug('Previously unknown user "%s"; creating new annotation state' % (user_id))

            if "automatic_assignment" in self.config and self.config["automatic_assignment"]["on"]:
                # when pre_annotation is set up, only assign the instance when consent question is answered
                if "prestudy" in self.config and self.config["prestudy"]["on"]:
                    user_state = UserState(generate_initial_user_dataflow(user_id))
                    self.user_to_annotation_state[user_id] = user_state

                # when pre_annotation is set up, only assign the instance when consent question is answered
                elif "pre_annotation" in self.config["automatic_assignment"] \
                        and "pre_annotation" in self.config["automatic_assignment"]["order"]:

                    user_state = UserState(generate_initial_user_dataflow(user_id))
                    self.user_to_annotation_state[user_id] = user_state

                # assign instances to new user when automatic assignment is turned on and there is no pre_annotation or prestudy pages
                else:
                    user_state = UserState(generate_initial_user_dataflow(user_id))
                    self.user_to_annotation_state[user_id] = user_state
                    self.assign_instances_to_user(user_id)

            else:
                # assign all the instance to each user when automatic assignment is turned off
                user_state = UserState(user_id)
                # user_state.real_instance_assigned_count = user_state.get_assigned_instance_count()
                self.user_to_annotation_state[user_id] = user_state
        else:
            user_state = self.user_to_annotation_state[user_id]

    def get_user_state(self, user_id: str) -> UserState:
        '''Gets a user from the user state manager or None if the user does not exist'''
        if user_id not in self.user_to_annotation_state:
            return None
        return self.user_to_annotation_state[user_id]

    def get_all_users(self) -> list[UserState]:
        '''Gets all users from the user state manager'''
        return list(self.user_to_annotation_state.values())

    def get_phase_html_fname(self, phase: UserPhase, page: str) -> str:
        '''Returns the filename of the page for the given phase and page name'''
        return self.phase_type_to_name_to_page[phase][page]

    def has_user(self, user_id: str) -> bool:
        '''Checks if a user exists in the user state manager'''
        return user_id in self.user_to_annotation_state

    def advance_phase(self, user_id: str) -> None:
        '''Moves the user to the next page in the current phase or the next phase'''
        phase, page = self.get_next_user_phase_page(user_id)
        # Get the current user's state
        user_state = self.get_user_state(user_id)
        user_state.advance_to_phase(phase, page)

    def get_next_user_phase_page(self, user_id: str) -> tuple[UserPhase,str]:
        '''Returns the name and filename of next the page for the user, either
           in the current phase or next phase. This method handles the
           case of where there are multiple pages within the same phase type'''

        # Get the current user's state
        user_state = self.get_user_state(user_id)

        # Get the current of their phase
        cur_phase, cur_page = user_state.get_current_phase_and_page()
        print('GET NEXT USER PHASE PAGE: cur_phase, cur_page: ', cur_phase, cur_page)
        if cur_phase == UserPhase.DONE:
            return UserPhase.DONE, None

        page2file_for_cur_phase = self.phase_type_to_name_to_page[cur_phase]
        if len(page2file_for_cur_phase) > 1:
            pages_for_cur_phase = list(page2file_for_cur_phase.keys())
            cur_page_index = pages_for_cur_phase.index(cur_page)
            # If there are more pages in this phase, return the next one
            if cur_page_index < len(pages_for_cur_phase) - 1:
                next_page = pages_for_cur_phase[cur_page_index + 1]
                return cur_phase, next_page

        # If there are no more pages in this phase, return the next phase.
        # Filter the set of all_phases to those that were added to this task
        all_phases = [p for p in list(UserPhase) if p in self.phase_type_to_name_to_page]
        cur_phase_index = all_phases.index(cur_phase)
        if cur_phase_index < len(all_phases) - 1:
            next_phase = all_phases[cur_phase_index + 1]
            # Use the first page in the next phase
            next_page = list(self.phase_type_to_name_to_page[next_phase].keys())[0]
            return next_phase, next_page
        else:
            return UserPhase.DONE, None

    def get_user_ids(self) -> list[str]:
        '''Gets all user IDs from the user state manager'''
        return [user.user_id for user in self.get_all_users()]

    def get_user_count(self) -> int:
        '''Get the number of users in the user state manager'''
        return len(self.user_to_annotation_state)

    def is_consent_required(self) -> bool:
        return UserPhase.CONSENT in self.phase_type_to_name_to_page

    def is_instructions_required(self) -> bool:
        return UserPhase.INSTRUCTIONS in self.phase_type_to_name_to_page

    def is_prestudy_required(self) -> bool:
        return UserPhase.PRESTUDY in self.phase_type_to_name_to_page

    def is_training_required(self) -> bool:
        return UserPhase.TRAINING in self.phase_type_to_name_to_page

    def is_poststudy_required(self) -> bool:
        return UserPhase.POSTSTUDY in self.phase_type_to_name_to_page

    def save_user_state(self, user_state: UserState) -> None:
        '''Saves the user state for the given user ID'''

        # Figure out where this user's data would be stored on disk
        output_annotation_dir = self.config["output_annotation_dir"]
        username = user_state.get_user_id()

        # NB: Do some kind of sanitizing on the username to improve security
        user_dir = os.path.join(output_annotation_dir, username)

        # Make sure the directory exists
        if not os.path.exists(user_dir):
            os.makedirs(user_dir)
            logger.debug('Created state directory for user "%s"' % (username))

        # Write the user's state to disk
        user_state.save(user_dir)

    def load_user_state(self, user_dir: str) -> UserState:
        '''Loads the user state for the given user ID'''

        # Figure out where this user's data would be stored on disk
        output_annotation_dir = self.config["output_annotation_dir"]

        # TODO: make the user state type configurable between in-memory and DB-backed.
        user_state = InMemoryUserState.load(user_dir)


        if user_state.get_user_id() in self.user_to_annotation_state:
            logger.warning(f'User "{user_state.get_user_id()}" already exists in the user state manager, but is being overwritten by load_state()')

        self.user_to_annotation_state[user_state.get_user_id()] = user_state

        return user_state



class UserState:
    """
    An interface class for maintaining state on which annotations users have completed.
    """

    def __init__(self, user_id: str):
        pass

    def advance_to_phase(self, phase: UserPhase, page: str) -> None:
        raise NotImplementedError()

    def assign_instance(self, item: Item) -> None:
        raise NotImplementedError()

    def get_current_instance(self) -> Item:
        raise NotImplementedError()

    def get_labeled_instance_ids(self) -> set[str]:
        '''Returns the set of instances ids that this user has labeled'''
        raise NotImplementedError()

    def get_span_annotations(self):
        return self.span_annotations

    def get_current_instance_index(self) -> int:
        raise NotImplementedError()

    def get_user_id(self) -> str:
        '''Returns the user ID for this user'''
        raise NotImplementedError()

    def goto_prev_instance(self) -> None:
        raise NotImplementedError()

    def goto_next_instance(self) -> None:
        raise NotImplementedError()

    def go_to_index(self, instance_index: int) -> None:
        '''Moves the annotator's view to the instance at the specified index'''
        raise NotImplementedError()

    def get_all_annotations(self):
        """
        Returns all annotations (label and span) for all annotated instances
        """
        raise NotImplementedError()

    def get_label_annotations(self, instance_id):
        """
        Returns the label-based annotations for the instance.
        """
        raise NotImplementedError()

    def get_span_annotations(self, instance_id):
        """
        Returns the span annotations for this instance.
        """
        raise NotImplementedError()

    def get_current_phase_and_page(self) -> tuple[UserPhase, str]:
        raise NotImplementedError()

    def get_annotation_count(self) -> int:
        raise NotImplementedError()

    def get_assigned_instance_count(self):
        raise NotImplementedError()

    def get_phase(self) -> UserPhase:
        return self.current_phase_and_page[0]

    def set_phase(self, phase: UserPhase) -> None:
        raise NotImplementedError()

    def move_to_next_phase(self) -> None:
        raise NotImplementedError()

    def set_max_assignments(self) -> None:
        raise NotImplementedError()

    def set_annotation(
        self, instance_id, schema_to_label_to_value, span_annotations, behavioral_data_dict
    ):
     pass



class MysqlUserState(UserState):

    def __init__(self, user_id: str, db_conn):
        raise NotImplementedError('MysqlUserState is not implemented yet')

class InMemoryUserState(UserState):

    def __init__(self, user_id: str, max_assignments: int = -1):

        self.user_id = user_id

        # This data struction records the specific ordering for which instances have been
        # labeled so that, should orderings differ between users, we can still determine
        # the previous and next instances if a user navigates back and forth.
        self.instance_id_ordering = []

        # Utilit data structure for O(1) look up of whether some ID is already in our ordering
        self.assigned_instance_ids = set()

        # This is the index in instance_id_ordering that the user is currently being shown.
        self.current_instance_index = -1

        # TODO: Put behavioral information of each instance with the labels
        # together however, that requires too many changes of the data structure
        # therefore, we contruct a separate dictionary to save all the
        # behavioral information (e.g. time, click, ..)
        self.instance_id_to_behavioral_data = defaultdict(dict)

        # The data structure to save the labels (e.g. multiselect, radio, text) that
        # a user labels for each instance.
        self.instance_id_to_label_to_value = defaultdict(dict)

        # For non-annotation data, we save the responses for each page in separate
        # dictionaries to keep the data organized and make state-tracking easier.
        self.phase_to_page_to_label_to_value = defaultdict(lambda: defaultdict(dict))

        # The data structure to save the span annotations that a user labels for each
        # instance. The key is the instance id and the value is a list of span
        # annotations
        self.instance_id_to_span_to_value = defaultdict(dict)

        # For non-annotation data, we save any span labels for each page in separate
        # dictionaries to keep the data organized and make state-tracking easier.
        self.phase_to_page_to_span_to_value = defaultdict(lambda: defaultdict(dict))

        # This keeps track of which page the user is on in the annotation process.
        # All users start at the LOGIN page.
        self.current_phase_and_page = (UserPhase.LOGIN, None)

        # This data structure keeps track of which phases and pages the user has completed
        # and shouldn't include the current phase (yet)
        self.completed_phase_and_pages = defaultdict(set)

        # How many items a user can be assigned
        self.max_assignments = max_assignments

    def add_new_assigned_data(self, new_assigned_data):
        """
        Add new assigned data to the user state
        """
        for key in new_assigned_data:
            self.instance_id_to_data[key] = new_assigned_data[key]
            self.instance_id_ordering.append(key)
        self.instance_id_to_order = self.generate_id_order_mapping(self.instance_id_ordering)

    def advance_to_phase(self, phase: UserPhase, page: str) -> None:
        # print('advancing to', phase, page)
        self.current_phase_and_page = (phase, page)

    def assign_instance(self, item: Item) -> None:
        ''' Assigns an instance to the user for annotation'''

        # check that the item has not already been assigned to the user
        if item.get_id() in self.assigned_instance_ids:
            return
        #print('Assigned %s to %s' % (item.get_id(), self.instance_id_ordering   ))
        self.instance_id_ordering.append(item.get_id())
        self.assigned_instance_ids.add(item.get_id())
        # If this is the first assigned instance, set the current instance to be the first one
        if self.current_instance_index == -1:
            self.current_instance_index = 0

    def get_current_phase_and_page(self) -> tuple[UserPhase, str]:
        return self.current_phase_and_page

    def set_current_phase_and_page(self, phase_and_page: tuple[UserPhase, str]) -> None:
        #print('set phase to', phase_and_page)
        self.current_phase_and_page = phase_and_page

    def get_current_instance(self) -> Item:
        if self.current_instance_index < 0:
            return None

        if self.current_instance_index >= len(self.instance_id_ordering):
            return None
        inst_id = self.instance_id_ordering[self.current_instance_index]
        return get_item_state_manager().get_item(inst_id)

    def get_current_instance_id(self) -> str:
        '''Returns the ID of the instance that the user is currently annotating'''
        return self.get_current_instance().get_id()


    def get_labels(self) -> dict[str, dict[str, str]]:
        return self.labels

    def get_span_annotations(self):
        return self.span_annotations

    def add_label_annotation(self, instance_id: str, label: Label, value: any) -> None:
        '''Assigns the provided label to the instance or if the user is not in the annotation phase,
              to the page associated with the current phase'''
        if self.current_phase_and_page[0] == UserPhase.ANNOTATION:
            self.instance_id_to_label_to_value[instance_id][label] = value
        else:
            self.phase_to_page_to_label_to_value[self.current_phase_and_page[0]][self.current_phase_and_page[1]][label] = value
        #print('add_labels ->', self.instance_id_to_label_to_value)

    def add_span_annotation(self, instance_id: str, label: SpanAnnotation, value: any) -> None:
        '''Adds a set of span annotations to the instance or if the user is not
           in the annotation phase, to the page associated with the current phase'''
        if self.current_phase_and_page[0] == UserPhase.ANNOTATION:
            self.instance_id_to_span_to_value[instance_id][label] = value
        else:
            self.phase_to_page_to_span_to_value[self.current_phase_and_page[0]][self.current_phase_and_page[1]][label] = value

    def get_current_instance_index(self):
        '''Returns the index of the item the user is annotating within the list of items
           that the user has currently been assigned to annotate'''

        #print('GET current_instance_index ->', self.current_instance_index)
        return self.current_instance_index

    def go_back(self) -> bool:
        '''Moves the user back to the previous instance and returns True if successful'''
        if self.current_instance_index > 0:
            self.current_instance_index -= 1
            return True
        return False
        #print('GO BACK current_instance_index ->', self.current_instance_index)

    def is_at_end_index(self) -> bool:

        # TODO: Rename this function to be something more descriptive
        return self.current_instance_index == len(self.instance_id_ordering) - 1

    def go_forward(self) -> bool:
        '''Moves the user forward to the next instance and returns True if successful'''
        #print('GO FORWARD current_instance_index ->', self.current_instance_index)
        #print('GO FORWARD instance_id_ordering ->', self.instance_id_ordering)
        print(f"self.instance_id_ordering: {len(self.instance_id_ordering)}")
        if self.current_instance_index < len(self.instance_id_ordering) - 1:
            self.current_instance_index += 1
            return True
        return False



    def get_current_phase_and_page(self) -> tuple[UserPhase, str]:
        '''Returns the current phase and page that the user is on'''
        return self.current_phase_and_page

    def go_to_index(self, instance_index: int) -> None:
        '''Moves the annotator's view to the instance at the specified index'''
        if instance_index < len(self.instance_id_ordering) and instance_index >= 0:
            self.current_instance_index = instance_index

    def get_all_annotations(self) -> dict[Item, list[SpanAnnotation|Label]]:
        """
        Returns all annotations (label and span) for all annotated instances
        """
        labeled = set(self.instance_id_to_label_to_value.keys()) | set(
            self.instance_id_to_span_to_value.keys()
        )

        anns = {}
        for iid in labeled:
            labels = {}
            if iid in self.instance_id_to_label_to_value:
                labels = self.instance_id_to_label_to_value[iid]
            spans = {}
            if iid in self.instance_id_to_span_to_value:
                spans = self.instance_id_to_span_to_value[iid]

            anns[iid] = {"labels": labels, "spans": spans}

        return anns

    def get_label_annotations(self, instance_id) -> dict[str,list[Label]]:
        """
        Returns a mapping from each schema to the label-based annotations for the instance.
        """
        # print('get_labels ->', self.instance_id_to_label_to_value)
        if instance_id not in self.instance_id_to_label_to_value:
            return {}
        # NB: Should this be a view/copy?
        return self.instance_id_to_label_to_value[instance_id]

    def get_span_annotations(self, instance_id) -> dict[str,list[SpanAnnotation]]:
        """
        Returns a mapping from each schema to the span annotations for that schema.
        """
        if instance_id not in self.instance_id_to_span_to_value:
            return {}
        # NB: Should this be a view/copy?
        return self.instance_id_to_span_to_value[instance_id]

    def get_user_id(self) -> str:
        '''Returns the user ID for this user'''
        return self.user_id

    def get_annotated_instance_ids(self) -> set[str]:
        return set(self.instance_id_to_label_to_value.keys())\
                    | set(self.instance_id_to_span_to_value.keys())

    def get_annotation_count(self) -> int:
        '''Returns the total number of instances annotated by this user.'''
        return len(self.get_annotated_instance_ids())

    def get_assigned_instance_count(self):
        #print('instance_id_ordering ->', self.instance_id_ordering)
        return len(self.instance_id_ordering)

    def set_prestudy_status(self, whether_passed):
        if self.prestudy_passed is not None:
            return False
        self.prestudy_passed = whether_passed
        return True

    def get_prestudy_status(self):
        """
        Check if the user has passed the prestudy test.
        """
        return self.prestudy_passed

    def get_consent_status(self):
        """
        Check if the user has agreed to participate this study.
        """
        return self.consent_agreed

    def has_assignments(self) -> bool:
        """Returns True if the user has been assigned any instances to annotate"""
        return len(self.instance_id_ordering) > 0

    def has_annotated(self, instance_id: str) -> bool:
        '''Returns True if the user has annotated the instance with the given ID'''
        return instance_id in self.instance_id_to_label_to_value \
            or instance_id in self.instance_id_to_span_to_value

    def has_remaining_assignments(self) -> bool:
        """Returns True if the user has any remaining instances to annotate. If the user
           does not have a maximum number of assignments, this will always return True."""
        return self.max_assignments < 0 or len(self.get_annotated_instance_ids()) < self.max_assignments

    def set_max_assignments(self, max_assignments: int) -> None:
        '''Sets the maximum number of items that this user can be assigned'''
        self.max_assignments = max_assignments

    def get_max_assignments(self) -> int:
        '''Returns the maximum number of items that this user can be assigned'''
        return self.max_assignments

    def set_annotation(
        self, instance_id, schema_to_label_to_value, span_annotations, behavioral_data_dict
    ):
        """
        Based on a user's actions, updates the annotation for this particular instance.

        :span_annotations: a list of span annotations, which are each
          represented as dictionary objects/
        :return: True if setting these annotation values changes the previous
          annotation of this instance.
        """

        # Get whatever annotations were present for this instance, or, if the
        # item has not been annotated represent that with empty data structures
        # so we can keep track of whether the state changes
        old_annotation = defaultdict(dict)
        if instance_id in self.instance_id_to_label_to_value:
            old_annotation = self.instance_id_to_label_to_value[instance_id]

        old_span_annotations = []
        if instance_id in self.instance_id_to_span_to_value:
            old_span_annotations = self.instance_id_to_span_to_value[instance_id]

        # Avoid updating with no entries
        if len(schema_to_label_to_value) > 0:
            self.instance_id_to_label_to_value[instance_id] = schema_to_label_to_value
        # If the user didn't label anything (e.g. they unselected items), then
        # we delete the old annotation state
        elif instance_id in self.instance_id_to_label_to_value:
            del self.instance_id_to_label_to_value[instance_id]

        # Avoid updating with no entries
        if len(span_annotations) > 0:
            self.instance_id_to_span_to_value[instance_id] = span_annotations
        # If the user didn't label anything (e.g. they unselected items), then
        # we delete the old annotation state
        elif instance_id in self.instance_id_to_span_to_value:
            del self.instance_id_to_span_to_value[instance_id]

        # TODO: keep track of all the annotation behaviors instead of only
        # keeping the latest one each time when new annotation is updated,
        # we also update the behavioral_data_dict (currently done in the
        # update_annotation_state function)
        #
        # self.instance_id_to_behavioral_data[instance_id] = behavioral_data_dict

        return (
            old_annotation != schema_to_label_to_value or old_span_annotations != span_annotations
        )

    def update(self, annotation_order, annotated_instances):
        """
        Updates the entire state of annotations for this user by inserting
        all the data in annotated_instances into this user's state. Typically
        this data is loaded from a file

        NOTE: This is only used to update the entire list of annotations,
        normally when loading all the saved data

        :annotation_order: a list of string instance IDs in the order that this
        user should see those instances.
        :annotated_instances: a list of dictionary objects detailing the
        annotations on each item.
        """

        self.instance_id_to_label_to_value = {}
        for inst in annotated_instances:

            inst_id = inst["id"]
            label_annotations = inst["label_annotations"]
            span_annotations = inst["span_annotations"]

            self.instance_id_to_label_to_value[inst_id] = label_annotations
            self.instance_id_to_span_to_value[inst_id] = span_annotations

            behavior_dict = inst.get("behavioral_data", {})
            self.instance_id_to_behavioral_data[inst_id] = behavior_dict

            # TODO: move this code somewhere else so consent is organized
            # separately
            if re.search("consent", inst_id):
                consent_key = "I want to participate in this research and continue with the study."
                self.consent_agreed = False
                if label_annotations[consent_key].get("Yes") == "true":
                    self.consent_agreed = True

        self.instance_id_ordering = annotation_order
        self.instance_id_to_order = self.generate_id_order_mapping(self.instance_id_ordering)

        # Set the current item to be the one after the last thing that was
        # annotated
        # self.current_instance_index = min(len(self.instance_id_to_labeling),
        #                           len(self.instance_id_ordering)-1)

        annotated_set = set([it['id'] for it in annotated_instances])
        self.current_instance_index = self.instance_id_to_order[annotated_instances[-1]['id']]
        for in_id in self.instance_id_ordering:
            if in_id[-4:] == 'html':
                continue
            if in_id in annotated_set:
                self.current_instance_index = self.instance_id_to_order[in_id]
            else:
                break
    def reorder_remaining_instances(self, new_id_order, preserve_order):

        # Preserve the ordering the user has seen so far for data they've
        # annotated. This also includes items that *other* users have annotated
        # to ensure all items get the same number of annotations (otherwise
        # these items might get re-ordered farther away)
        new_order = [iid for iid in self.instance_id_ordering if iid in preserve_order]

        # Now add all the other IDs
        for iid in new_id_order:
            if iid not in self.instance_id_to_label_to_value:
                new_order.append(iid)

        assert len(new_order) == len(self.instance_id_ordering)

        # Update the user's state
        self.instance_id_ordering = new_order
        self.instance_id_to_order = self.generate_id_order_mapping(self.instance_id_ordering)

    def parse_time_string(self, time_string):
        """
        Parse the time string generated by front end,
        e.g., 'time_string': 'Time spent: 0d 0h 0m 5s '
        """
        time_dict = {}
        items = time_string.strip().split(" ")
        if len(items) != 6:
            return None
        time_dict["day"] = int(items[2][:-1])
        time_dict["hour"] = int(items[3][:-1])
        time_dict["minute"] = int(items[4][:-1])
        time_dict["second"] = int(items[5][:-1])
        time_dict["total_seconds"] = (
            time_dict["second"] + 60 * time_dict["minute"] + 3600 * time_dict["hour"]
        )

        return time_dict

    def total_working_time(self):
        """
        Calculate the amount of time a user have spend on annotation
        """
        total_working_seconds = 0
        for inst_id in self.instance_id_to_behavioral_data:
            time_string = self.instance_id_to_behavioral_data[inst_id].get("time_string")
            if time_string:
                total_working_seconds += (
                    self.parse_time_string(time_string)["total_seconds"]
                    if self.parse_time_string(time_string)
                    else 0
                )

        if total_working_seconds < 60:
            total_working_time_str = str(total_working_seconds) + " seconds"
        elif total_working_seconds < 3600:
            total_working_time_str = str(int(total_working_seconds) / 60) + " minutes"
        else:
            total_working_time_str = str(int(total_working_seconds) / 3600) + " hours"

        return (total_working_seconds, total_working_time_str)

    def generate_user_statistics(self):
        statistics = {
            "Annotated instances": self.get_annotation_count(),
            "Total working time": self.total_working_time()[1],
            "Average time on each instance": "N/A",
        }
        if statistics["Annotated instances"] != 0:
            statistics["Average time on each instance"] = "%s seconds" % str(
                round(self.total_working_time()[0] / statistics["Annotated instances"], 1)
            )
        return statistics

    def to_json(self):

        def pp_to_tuple(pp: tuple[UserPhase,str]) -> tuple[str,str]:
            return (str(pp[0]), pp[1])

        def label_to_dict(l: Label) -> dict[str,any]:
            return {
                "schema": l.get_schema(),
                "name": l.get_name()
            }

        def span_to_dict(s: SpanAnnotation) -> dict[str,any]:
            return {
                "schema": s.get_schema(),
                "name": s.get_name(),
                "start": s.get_start(),
                "end": s.get_end(),
                "title": s.get_title()
            }


        def convert_label_dict(d: dict[Label, any]) -> list[tuple[dict[str], str]]:
            return [(label_to_dict(k), v) for k, v in d.items()]

        def convert_span_dict(d: dict[SpanAnnotation, any]) -> list[tuple[dict[str], str]]:
            return [(span_to_dict(k), v) for k, v in d.items()]


        # Do the easy cases first
        d = {
            'user_id': self.user_id,
            'instance_id_ordering': self.instance_id_ordering,
            'current_instance_index': self.current_instance_index,
            'current_phase_and_page': pp_to_tuple(self.current_phase_and_page),
            'completed_phase_and_pages':
                [ pp_to_tuple(pp) for pp in self.completed_phase_and_pages],
            'max_assignments': self.max_assignments,
        }
        # TODO once we figure out the type of the behavioral data
        #d['instance_id_to_behavioral_data']:

        {k: {k2: v2 for k2, v2 in v.items()} for k, v in self.instance_id_to_behavioral_data.items()}
        d['instance_id_to_label_to_value'] = {k: convert_label_dict(v) for k,v in self.instance_id_to_label_to_value.items()}
        d['instance_id_to_span_to_value'] = {k: convert_span_dict(v) for k,v in self.instance_id_to_span_to_value.items()}
        d['phase_to_page_to_label_to_value'] = {str(k): {k2: convert_label_dict(v2) for k2, v2 in v.items()} for k, v in self.phase_to_page_to_label_to_value.items()}
        d['phase_to_page_to_span_to_value'] = {str(k): {k2: convert_span_dict(v2) for k2, v2 in v.items()} for k, v in self.phase_to_page_to_span_to_value.items()}

        return d


    def save(self, user_dir: str) -> None:
        '''Saves the user's state to disk'''

        # Convert the state to something JSON serializable
        user_state = self.to_json()
        with open(os.path.join(user_dir, 'user_state.json'), 'wt') as outf:
            json.dump(user_state, outf)


    def load(user_dir: str) -> UserState:
        '''Loads the user's state from disk'''

        state_file = os.path.join(user_dir, 'user_state.json')
        if not os.path.exists(state_file):
            raise ValueError(f'User state file not found for user in directory "{user_dir}"')
        with open(os.path.join(user_dir, 'user_state.json'), 'rt') as f:
            j = json.load(f)

        def to_label(d: dict[str,str]) -> Label:
            return Label(d['schema'], d['name'])

        def to_span(d: dict[str,str]) -> SpanAnnotation:
            return SpanAnnotation(d['schema'], d['name'], d['title'], d['start'], d['end'])

        def to_phase_and_page(t: tuple[str,str]) -> tuple[UserPhase,str]:
            return (UserPhase.fromstr(t[0]), t[1])

        user_state = InMemoryUserState(j['user_id'], j['max_assignments'])

        user_state.instance_id_ordering = j['instance_id_ordering']
        user_state.assigned_instance_ids = set(j['instance_id_ordering'])
        user_state.current_instance_index = j['current_instance_index']
        # TODO...
        #user_state.instance_id_to_behavioral_data = j['instance_id_to_behavioral_data']
        for iid, l2v in j['instance_id_to_label_to_value'].items():
            user_state.instance_id_to_label_to_value[iid] = {to_label(k): v for k, v in l2v}

        for iid, s2v in j['instance_id_to_span_to_value'].items():
            user_state.instance_id_to_span_to_value[iid] = {to_span(k): v for k, v in s2v}

        for phase, p2l2lv in j['phase_to_page_to_label_to_value'].items():
            phase = UserPhase.fromstr(phase)
            for page, lv_list in p2l2lv.items():
                for lv in lv_list:
                    label = lv[0]
                    label = to_label(label)
                    value = lv[1]
                    user_state.phase_to_page_to_label_to_value[phase][page][label] = value


        for phase, p2s2v in j['phase_to_page_to_span_to_value'].items():
            phase = UserPhase.fromstr(phase)
            for page, sv_list in p2s2v.items():
                for sv in sv_list:
                    span = sv[0]
                    span = to_span(span)
                    value = sv[1]
                    user_state.phase_to_page_to_span_to_value[phase][page][span] = value

        # These require converting the dictionaries back to the original types
        user_state.current_phase_and_page = to_phase_and_page(j['current_phase_and_page'])
        user_state.completed_phase_and_pages = [
            to_phase_and_page(pp) for pp in j['completed_phase_and_pages']
        ]

        return user_state


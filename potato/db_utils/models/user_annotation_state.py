"""
SQLAlchemy model for users.
"""
from typing import Mapping, Any

import re
from collections import defaultdict
from sqlalchemy.types import PickleType
from potato.db import db


def _generate_id_order_mapping(instance_id_ordering):
    id_order_mapping = {
        ordering: idx for idx, ordering in enumerate(instance_id_ordering)
    }
    return id_order_mapping


class UserAnnotationState(db.Model):
    # NOTE: This id is NOT equivalent to instance id!
    id = db.Column(db.Integer, primary_key=True)

    username = db.Column(db.String, db.ForeignKey("user.username"), nullable=False)

    # id (str) --> "label_annotations" (Dict)
    instance_id_to_labeling = db.Column(PickleType)

    # This data structure keeps the span-based annotations the user has
    # completed so far
    # id (str) --> "span_annotations" (List)
    instance_id_to_span_annotations = db.Column(PickleType)

    # This is a reference to the data
    # Mapping from instance id to data.
    # id (str) --> data (Dict)
    # NB: do we need this as a field?
    instance_id_to_data = db.Column(PickleType)

    # TODO: Put behavioral information of each instance with the labels
    # together however, that requires too many changes of the data structure
    # therefore, we contruct a separate dictionary to save all the
    # behavioral information (e.g. time, click, ..)
    # id (str) --> "behavior_data" (Dict)
    instance_id_to_behavioral_data = db.Column(PickleType)

    # NOTE: this might be dumb but at the moment, we cache the order in
    # which this user will walk the instances. This might not work if we're
    # annotating a ton of things with a lot of people, but hopefully it's
    # not too bad. The underlying motivation is to programmatically change
    # this ordering later
    # List[id (str)]
    instance_id_ordering = db.Column(PickleType)

    # initialize the mapping from instance id to order
    # Dict[id (str), int]
    instance_id_to_order = db.Column(PickleType)

    instance_cursor = db.Column(db.Integer, default=0)

    # Indicator of whether the user has passed the prestudy, None means no
    # prestudy or prestudy not complete, True means passed and False means
    # failed
    prestudy_passed = db.Column(db.Boolean, default=False)

    # Indicator of whether the user has agreed to participate this study,
    # None means consent not complete, True means yes and False measn no
    consent_agreed = db.Column(db.Boolean, default=False)

    # Total annotation instances assigned to a user
    real_instance_assigned_count = db.Column(db.Integer, default=0)

    def __init__(self, assigned_user_data):
        """
        Initialize instance.
        :assigned_user_data: Mapping[str, Dict]
            (instance_id (str) --> data object
        """
        self.instance_id_to_data = assigned_user_data
        self.instance_id_to_labeling = {}
        self.instance_id_to_span_annotations = {}
        self.instance_id_to_behavioral_data = {}
        self.instance_id_ordering = list(assigned_user_data.keys())
        self.instance_id_to_order = _generate_id_order_mapping(
            self.instance_id_ordering
        )
        self.instance_cursor = 0
        self.prestudy_passed = False
        self.consent_agreed = False
        self.real_instance_assigned_count = 0

    def add_new_assigned_data(self, new_assigned_data: Mapping[str, Any]):
        """
        Add new assigned data to the user state.
        :new_assigned_data: Mapping from instance_ids (?) to "Data".
        """
        for key, data in enumerate(new_assigned_data):
            self.instance_id_to_data[key] = data
            self.instance_id_ordering.append(key)
        self.instance_id_to_order = _generate_id_order_mapping(
            self.instance_id_ordering
        )
        breakpoint()
        db.session.commit()
        breakpoint()

    def get_assigned_data(self):
        return self.instance_id_to_data

    def current_instance(self):
        breakpoint()
        inst_id = self.instance_id_ordering[self.instance_cursor]
        instance = self.instance_id_to_data[inst_id]
        breakpoint()
        return instance

    def get_instance_cursor(self):
        return self.instance_cursor

    def cursor_to_real_instance_id(self, cursor):
        return self.instance_id_ordering[cursor]

    def is_prestudy_question(self, cursor):
        return self.instance_id_ordering[cursor].startswith("prestudy")

    def go_back(self):
        if self.instance_cursor > 0:
            if self.prestudy_passed and self.is_prestudy_question(
                self.instance_cursor - 1
            ):
                return

            # Should avoid += or -= operations in SQLAlchemy land:
            # see https://stackoverflow.com/questions/9667138/how-to-update-sqlalchemy-row-entry#57743964
            self.instance_cursor = self.instance_cursor - 1
            db.session.commit()

    def go_forward(self):
        if self.instance_cursor < len(self.instance_id_to_data) - 1:
            # Should avoid += or -= operations in SQLAlchemy land:
            # see https://stackoverflow.com/questions/9667138/how-to-update-sqlalchemy-row-entry#57743964
            self.instance_cursor = self.instance_cursor + 1
            db.session.commit()

    def go_to_id(self, _id):
        if _id < len(self.instance_id_to_data) and _id >= 0:
            self.instance_cursor = _id
            db.session.commit()

    def get_all_annotations(self):
        """
        Returns all annotations (label and span) for all annotated instances.
        """
        labeled = set(self.instance_id_to_labeling.keys()) | set(
            self.instance_id_to_span_annotations.keys()
        )

        anns = {}
        for iid in labeled:
            labels = {}
            if iid in self.instance_id_to_labeling:
                labels = self.instance_id_to_labeling[iid]
            spans = {}
            if iid in self.instance_id_to_span_annotations:
                spans = self.instance_id_to_span_annotations[iid]

            anns[iid] = {"labels": labels, "spans": spans}

        return anns

    def get_label_annotations(self, instance_id):
        """
        Returns the label-based annotations for the instance.
        """
        if instance_id not in self.instance_id_to_labeling:
            return None
        # NB: Should this be a view/copy?
        return self.instance_id_to_labeling[instance_id]

    def get_span_annotations(self, instance_id):
        """
        Returns the span annotations for this instance.
        """
        if instance_id not in self.instance_id_to_span_annotations:
            return None
        # NB: Should this be a view/copy?
        return self.instance_id_to_span_annotations[instance_id]

    def get_annotation_count(self):
        return len(self.instance_id_to_labeling) + len(
            self.instance_id_to_span_annotations
        )

    def get_assigned_instance_count(self):
        return len(self.instance_id_ordering)

    def set_prestudy_status(self, whether_passed):
        if not self.prestudy_passed:
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

    def get_real_assigned_instance_count(self):
        """
        Check the number of assigned instances for a user (only the core annotation parts)
        """
        return self.real_instance_assigned_count

    def set_annotation(
        self,
        instance_id,
        schema_to_label_to_value,
        span_annotations,
        behavioral_data_dict,
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
        breakpoint()
        old_annotation = defaultdict(dict)
        if instance_id in self.instance_id_to_labeling:
            old_annotation = self.instance_id_to_labeling[instance_id]

        old_span_annotations = []
        if instance_id in self.instance_id_to_span_annotations:
            old_span_annotations = self.instance_id_to_span_annotations[
                instance_id
            ]

        # Avoid updating with no entries
        if len(schema_to_label_to_value) > 0:
            self.instance_id_to_labeling[
                instance_id
            ] = schema_to_label_to_value

        # If the user didn't label anything (e.g. they unselected items), then
        # we delete the old annotation state
        elif instance_id in self.instance_id_to_labeling:
            breakpoint()
            del self.instance_id_to_labeling[instance_id]
            breakpoint()

        # Avoid updating with no entries
        if len(span_annotations) > 0:
            self.instance_id_to_span_annotations[
                instance_id
            ] = span_annotations
        # If the user didn't label anything (e.g. they unselected items), then
        # we delete the old annotation state
        elif instance_id in self.instance_id_to_span_annotations:
            del self.instance_id_to_span_annotations[instance_id]

        # TODO: keep track of all the annotation behaviors instead of only
        # keeping the latest one each time when new annotation is updated,
        # we also update the behavioral_data_dict (currently done in the
        # update_annotation_state function)
        breakpoint()
        db.session.commit()
        breakpoint()
        return (
            old_annotation != schema_to_label_to_value
            or old_span_annotations != span_annotations
        )

    def update(self, annotation_order, annotated_instances):
        """
        Updates the entire state of annotations for this user by inserting
        all the data in annotated_instances into this user's state. Typically
        this data is loaded from a file.

        NOTE: This is only used to update the entire list of annotations,
        normally when loading all the saved data.
        Use with caution!

        :annotation_order: a list of string instance IDs in the order that this
        user should see those instances.
        :annotated_instances: a list of dictionary objects detailing the
        annotations on each item.
        """

        instance_id_to_labeling = {}
        instance_id_to_span_annotations = {}
        instance_id_to_behavioral_data = {}

        for inst in annotated_instances:

            inst_id = inst["id"]
            label_annotations = inst["label_annotations"]
            span_annotations = inst["span_annotations"]

            instance_id_to_labeling[inst_id] = label_annotations
            instance_id_to_span_annotations[inst_id] = span_annotations

            behavior_dict = inst.get("behavioral_data", {})
            instance_id_to_behavioral_data[inst_id] = behavior_dict

            # TODO: move this code somewhere else so consent is organized
            # separately
            if re.search("consent", inst_id):
                consent_key = "I want to participate in this research and continue with the study."
                self.consent_agreed = False
                if label_annotations[consent_key].get("Yes") == "true":
                    self.consent_agreed = True

        self.instance_id_ordering = annotation_order
        self.instance_id_to_order = _generate_id_order_mapping(
            self.instance_id_ordering
        )
        self.instance_id_to_labeling = instance_id_to_labeling
        self.instance_id_to_span_annotations = instance_id_to_span_annotations
        self.instance_id_to_behavioral_data = instance_id_to_behavioral_data

        # Set the current item to be the one after the last thing that was
        # annotated.
        if len(annotated_instances) > 0:
            self.instance_cursor = self.instance_id_to_order[
                annotated_instances[-1]["id"]
            ]

        db.session.commit()


    def reorder_remaining_instances(self, new_id_order, preserve_order):
        # Preserve the ordering the user has seen so far for data they've
        # annotated. This also includes items that *other* users have annotated
        # to ensure all items get the same number of annotations (otherwise
        # these items might get re-ordered farther away)
        new_order = [
            iid for iid in self.instance_id_ordering if iid in preserve_order
        ]

        # Now add all the other IDs
        for iid in new_id_order:
            if iid not in self.instance_id_to_labeling:
                new_order.append(iid)

        assert len(new_order) == len(self.instance_id_ordering)

        # Update the user's state
        self.instance_id_ordering = new_order
        self.instance_id_to_order = _generate_id_order_mapping(
            self.instance_id_ordering
        )
        db.session.commit()

    @staticmethod
    def parse_time_string(time_string):
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
            time_dict["second"]
            + 60 * time_dict["minute"]
            + 3600 * time_dict["hour"]
        )
        return time_dict

    def total_working_time(self):
        """
        Calculate the amount of time a user have spend on annotation.
        """
        total_working_seconds = 0
        for inst_id in self.instance_id_to_behavioral_data:
            time_string = self.instance_id_to_behavioral_data[inst_id].get(
                "time_string"
            )
            if time_string:
                total_working_seconds += (
                    self.parse_time_string(time_string)["total_seconds"]
                    if self.parse_time_string(time_string)
                    else 0
                )

        if total_working_seconds < 60:
            total_working_time_str = str(total_working_seconds) + " seconds"
        elif total_working_seconds < 3600:
            total_working_time_str = (
                str(int(total_working_seconds) / 60) + " minutes"
            )
        else:
            total_working_time_str = (
                str(int(total_working_seconds) / 3600) + " hours"
            )

        return (total_working_seconds, total_working_time_str)

    def generate_user_statistics(self):
        statistics = {
            "Annotated instances": len(self.instance_id_to_labeling),
            "Total working time": self.total_working_time()[1],
            "Average time on each instance": "N/A",
        }
        if statistics["Annotated instances"] != 0:
            statistics["Average time on each instance"] = "%s seconds" % str(
                round(
                    self.total_working_time()[0]
                    / statistics["Annotated instances"],
                    1,
                )
            )
        return statistics
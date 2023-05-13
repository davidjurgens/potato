import re
from collections import defaultdict


class UserAnnotationState:
    """
    A class for maintaining state on which annotations users have completed.
    """

    def __init__(self, assigned_user_data):
        # This data structure keeps the label-based annotations the user has
        # completed so far
        self.instance_id_to_labeling = {}

        # This data structure keeps the span-based annotations the user has
        # completed so far
        self.instance_id_to_span_annotations = {}

        # This is a reference to the data
        #
        # NB: do we need this as a field?
        self.instance_id_to_data = assigned_user_data

        # TODO: Put behavioral information of each instance with the labels
        # together however, that requires too many changes of the data structure
        # therefore, we contruct a separate dictionary to save all the
        # behavioral information (e.g. time, click, ..)
        self.instance_id_to_behavioral_data = {}

        # NOTE: this might be dumb but at the moment, we cache the order in
        # which this user will walk the instances. This might not work if we're
        # annotating a ton of things with a lot of people, but hopefully it's
        # not too bad. The underlying motivation is to programmatically change
        # this ordering later
        self.instance_id_ordering = list(assigned_user_data.keys())

        # initialize the mapping from instance id to order
        self.instance_id_to_order = self.generate_id_order_mapping(
            self.instance_id_ordering
        )

        self.instance_cursor = 0

        # Indicator of whether the user has passed the prestudy, None means no
        # prestudy or prestudy not complete, True means passed and False means
        # failed
        self.prestudy_passed = None

        # Indicator of whether the user has agreed to participate this study,
        # None means consent not complete, True means yes and False measn no
        self.consent_agreed = None

        # Total annotation instances assigned to a user
        self.real_instance_assigned_count = 0

    def generate_id_order_mapping(self, instance_id_ordering):
        id_order_mapping = {}
        for i in range(len(instance_id_ordering)):
            id_order_mapping[instance_id_ordering[i]] = i
        return id_order_mapping

    def add_new_assigned_data(self, new_assigned_data):
        """
        Add new assigned data to the user state
        """
        for key in new_assigned_data:
            self.instance_id_to_data[key] = new_assigned_data[key]
            self.instance_id_ordering.append(key)
        self.instance_id_to_order = self.generate_id_order_mapping(
            self.instance_id_ordering
        )

    def get_assigned_data(self):
        return self.instance_id_to_data

    def current_instance(self):
        inst_id = self.instance_id_ordering[self.instance_cursor]
        instance = self.instance_id_to_data[inst_id]
        return instance

    def get_instance_cursor(self):
        return self.instance_cursor

    def cursor_to_real_instance_id(self, cursor):
        return self.instance_id_ordering[cursor]

    def is_prestudy_question(self, cursor):
        return self.instance_id_ordering[cursor][:8] == "prestudy"

    def go_back(self):
        if self.instance_cursor > 0:
            if self.prestudy_passed is not None and self.is_prestudy_question(
                self.instance_cursor - 1
            ):
                return
            self.instance_cursor -= 1

    def go_forward(self):
        if self.instance_cursor < len(self.instance_id_to_data) - 1:
            self.instance_cursor += 1

    def go_to_id(self, _id):
        if _id < len(self.instance_id_to_data) and _id >= 0:
            self.instance_cursor = _id

    def get_all_annotations(self):
        """
        Returns all annotations (label and span) for all annotated instances
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

    def get_real_assigned_instance_count(self):
        """
        Check the number of assigned instances for a user (only the core annotation parts)
        """
        return len([it for it in self.instance_id_ordering if it[-4:] != "html"])

    def get_real_finished_instance_count(self):
        """
        Check the number of finished instances for a user (only the core annotation parts)
        """
        finished_instances = [
            it for it in self.instance_id_to_labeling if it[-4:] != "html"
        ]
        finished_span_instances = [
            it
            for it in self.instance_id_to_span_annotations
            if (
                it[-4:] != "html" and len(self.instance_id_to_span_annotations[it]) != 0
            )
        ]

        return len(set(finished_instances + finished_span_instances))

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
        old_annotation = defaultdict(dict)
        if instance_id in self.instance_id_to_labeling:
            old_annotation = self.instance_id_to_labeling[instance_id]

        old_span_annotations = []
        if instance_id in self.instance_id_to_span_annotations:
            old_span_annotations = self.instance_id_to_span_annotations[instance_id]

        # Avoid updating with no entries
        if len(schema_to_label_to_value) > 0:
            self.instance_id_to_labeling[instance_id] = schema_to_label_to_value
        # If the user didn't label anything (e.g. they unselected items), then
        # we delete the old annotation state
        elif instance_id in self.instance_id_to_labeling:
            del self.instance_id_to_labeling[instance_id]

        # Avoid updating with no entries
        if len(span_annotations) > 0:
            self.instance_id_to_span_annotations[instance_id] = span_annotations
        # If the user didn't label anything (e.g. they unselected items), then
        # we delete the old annotation state
        elif instance_id in self.instance_id_to_span_annotations:
            del self.instance_id_to_span_annotations[instance_id]

        # TODO: keep track of all the annotation behaviors instead of only
        # keeping the latest one each time when new annotation is updated,
        # we also update the behavioral_data_dict (currently done in the
        # update_annotation_state function)
        #
        # self.instance_id_to_behavioral_data[instance_id] = behavioral_data_dict

        return (
            old_annotation != schema_to_label_to_value
            or old_span_annotations != span_annotations
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

        self.instance_id_to_labeling = {}
        for inst in annotated_instances:
            inst_id = inst["id"]
            label_annotations = inst["label_annotations"]
            span_annotations = inst["span_annotations"]

            self.instance_id_to_labeling[inst_id] = label_annotations
            self.instance_id_to_span_annotations[inst_id] = span_annotations

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
        self.instance_id_to_order = self.generate_id_order_mapping(
            self.instance_id_ordering
        )

        # Set the current item to be the one after the last thing that was
        # annotated
        # self.instance_cursor = min(len(self.instance_id_to_labeling),
        #                           len(self.instance_id_ordering)-1)

        # follow the first unannotated instance and set it as the current instance after user re-login
        if self.get_real_finished_instance_count() > 0:
            annotated_set = set([it["id"] for it in annotated_instances])
            self.instance_cursor = self.instance_id_to_order[
                annotated_instances[-1]["id"]
            ]
            for in_id in self.instance_id_ordering:
                if in_id[-4:] == "html":
                    continue
                if in_id in annotated_set:
                    self.instance_cursor = self.instance_id_to_order[in_id]
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
            if iid not in self.instance_id_to_labeling:
                new_order.append(iid)

        assert len(new_order) == len(self.instance_id_ordering)

        # Update the user's state
        self.instance_id_ordering = new_order
        self.instance_id_to_order = self.generate_id_order_mapping(
            self.instance_id_ordering
        )

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
            total_working_time_str = str(int(total_working_seconds) / 60) + " minutes"
        else:
            total_working_time_str = str(int(total_working_seconds) / 3600) + " hours"

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
                    self.total_working_time()[0] / statistics["Annotated instances"], 1
                )
            )
        return statistics

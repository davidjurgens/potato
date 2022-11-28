"""
Interface for UserAnnotationState.
"""
from typing import Mapping

import os
import json
import random
import re
import logging
from collections import defaultdict
import pandas as pd
from sqlalchemy.orm.attributes import flag_modified
from potato.db_utils.models.user import User
from potato.db_utils.models.user_annotation_state import UserAnnotationState
from potato.server_utils.prestudy import (
    get_prestudy_label,
    print_prestudy_result,
)
from potato.server_utils.config_module import config
import potato.state as state

logger = logging.getLogger(__name__)


def instances_all_assigned():
    """
    Check if all instances are assigned.
    """
    if "unassigned" not in state.task_assignment:
        return False

    return len(state.task_assignment["unassigned"]) <= int(
        config["automatic_assignment"]["instance_per_annotator"] * 0.7
    )


def _parse_html_span_annotation(html_span_annotation):
    """
    Parses the span annotations produced in raw HTML by Potato's front end
    and extracts out the precise spans and labels annotated by users.

    :returns: a tuple of (1) the annotated string without annotation HTML
              and a list of annotations
    """
    span_annotation = html_span_annotation.strip()
    init_tag_regex = re.compile(r"(<span.+?>)")
    end_tag_regex = re.compile(r"(</span>)")
    anno_regex = re.compile(r'<div class="span_label".+?>(.+)</div>')
    no_html_s = ""
    start = 0

    annotations = []

    while True:
        _m = init_tag_regex.search(span_annotation, start)
        if not _m:
            break

        # find the end tag
        _m2 = end_tag_regex.search(span_annotation, _m.end())

        middle = span_annotation[_m.end() : _m2.start()]

        # Get the annotation label from the middle text
        _m3 = anno_regex.search(middle)

        middle_text = middle[: _m3.start()]
        annotation = _m3.group(1)

        no_html_s += span_annotation[start : _m.start()]

        ann = {
            "start": len(no_html_s),
            "end": len(no_html_s) + len(middle_text),
            "span": middle_text,
            "annotation": annotation,
        }
        annotations.append(ann)

        no_html_s += middle_text
        start = _m2.end(0)

    # Add whatever trailing text exists
    no_html_s += span_annotation[start:]

    return no_html_s, annotations


class UserAnnotationStateManager:
    def __init__(self, db, config, prefetch=True):
        self.db = db
        self.config = config

    def add(self, username, assigned_user_data):
        """
        Add user annotation state.
        """
        user_annotation_state = UserAnnotationState(
            username, assigned_user_data
        )

        self.db.session.add(user_annotation_state)
        self.db.session.commit()
        return user_annotation_state

    def get_user_state(self, username):
        """
        Returns the UserAnnotationState for a user, or if that user has not yet
        annotated, creates a new state for them and registers them with the system.
        """
        user_state = self._get_user_state(username)
        if user_state:
            return user_state

        logger.debug(
            'Previously unknown user "%s"; creating new annotation state'
            % (username)
        )

        if (
            "automatic_assignment" in self.config
            and self.config["automatic_assignment"]["on"]
        ):
            # assign instances to new user when automatic assignment is on.
            if "prestudy" in self.config and self.config["prestudy"]["on"]:
                user_state = self.add(
                    username, generate_initial_user_dataflow(username)
                )

            else:
                user_state = self.add(
                    username, generate_initial_user_dataflow(username)
                )
                self.assign_instances_to_user(username)

        else:
            # assign all the instance to each user when automatic assignment
            # is turned off
            user_state = self.add(username, state.instance_id_to_data)

        return user_state

    def load_user_state(self, username):
        """
        Loads the user's state from the database. The state includes which
        instances they have annotated and the order in which they are
        expected to see instances.
        """
        user = self._get_user(username)
        if not user:
            # New user, so initialize state
            logger.debug(
                'Previously unknown user "%s"; creating new annotation state'
                % (username)
            )

            user = self._get_user(username)

            # create new user state with the look up function
            if instances_all_assigned():
                return "all instances have been assigned"

            self.get_user_state(username)
            return "new user initialized"

        # Old user
        user_state = self._get_user_state(username)
        if user_state:
            # Old user with previous annotations.
            logger.info(
                'Loaded %d annotations for known user "%s"'
                % (user_state.get_annotation_count(), username)
            )
            return "old user loaded"

        # Old user but no annotated data.
        assigned_user_data = state.instance_id_to_data
        annotated_instances = []
        annotation_order = [iid for iid in assigned_user_data.keys()]
        user_state = self.add(username, state.instance_id_to_data)
        user_state.update(annotation_order, annotated_instances)
        return "old user loaded with new annotation state"

    def save_user_state(self, username, save_order=False):
        """
        Dump user state to file.
        """
        # Figure out where this user's data would be stored on disk
        output_annotation_dir = self.config["output_annotation_dir"]

        # NB: Do some kind of sanitizing on the username to improve security
        user_dir = os.path.join(output_annotation_dir, username)

        user_state = self.get_user_state(username)

        if not os.path.exists(user_dir):
            os.makedirs(user_dir)
            logger.debug('Created state directory for user "%s"' % (username))

        annotation_order_fname = os.path.join(user_dir, "annotation_order.txt")
        if not os.path.exists(annotation_order_fname) or save_order:
            with open(annotation_order_fname, "wt") as outf:
                for inst in user_state.instance_id_ordering:
                    # JIAXIN: output id has to be str
                    outf.write(str(inst) + "\n")

        annotated_instances_fname = os.path.join(
            user_dir, "annotated_instances.jsonl"
        )

        with open(annotated_instances_fname, "wt") as outf:
            for inst_id, data in user_state.get_all_annotations().items():
                bd_dict = {}
                if inst_id in user_state.instance_id_to_behavioral_data:
                    bd_dict = user_state.instance_id_to_behavioral_data[
                        inst_id
                    ]

                output = {
                    "id": inst_id,
                    "displayed_text": state.instance_id_to_data[inst_id][
                        "displayed_text"
                    ],
                    "label_annotations": data["labels"],
                    "span_annotations": data["spans"],
                    "behavioral_data": bd_dict,
                }
                json.dump(output, outf)
                outf.write("\n")

    def _set_annotation(
        self,
        username,
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
        user_state = self._get_user_state(username)
        if not user_state:
            raise RuntimeError("Could not find user-state for %s." % username)

        # Get whatever annotations were present for this instance, or, if the
        # item has not been annotated represent that with empty data structures
        # so we can keep track of whether the state changes
        old_annotation = defaultdict(dict)
        if instance_id in user_state.instance_id_to_labeling:
            old_annotation = user_state.instance_id_to_labeling[instance_id]

        old_span_annotations = []
        if instance_id in user_state.instance_id_to_span_annotations:
            old_span_annotations = user_state.instance_id_to_span_annotations[
                instance_id
            ]

        # Avoid updating with no entries
        if len(schema_to_label_to_value) > 0:
            user_state.instance_id_to_labeling[
                instance_id
            ] = schema_to_label_to_value

        # If the user didn't label anything (e.g. they unselected items), then
        # we delete the old annotation state
        elif instance_id in user_state.instance_id_to_labeling:
            del user_state.instance_id_to_labeling[instance_id]

        # Avoid updating with no entries
        if len(span_annotations) > 0:
            user_state.instance_id_to_span_annotations[
                instance_id
            ] = span_annotations
        # If the user didn't label anything (e.g. they unselected items), then
        # we delete the old annotation state
        elif instance_id in user_state.instance_id_to_span_annotations:
            del user_state.instance_id_to_span_annotations[instance_id]

        # TODO: keep track of all the annotation behaviors instead of only
        # keeping the latest one each time when new annotation is updated,
        # we also update the behavioral_data_dict (currently done in the
        # update_annotation_state function)
        did_change = (
            old_annotation != schema_to_label_to_value
            or old_span_annotations != span_annotations
        )
        if did_change:
            self.db.session.commit()

        return did_change

    def move_to_prev_instance(self, username):
        user_state = self.get_user_state(username)
        user_state.go_back()
        self.db.session.commit()

    def move_to_next_instance(self, username):
        user_state = self.get_user_state(username)
        user_state.go_forward()
        self.db.session.commit()

    def go_to_id(self, username, _id):
        # go to specific item
        user_state = self.get_user_state(username)
        user_state.go_to_id(int(_id))
        self.db.session.commit()

    def _get_user_state(self, username):
        """
        Return UserAnnotationState for :username:
        """
        return UserAnnotationState.query.filter_by(username=username).first()

    def _get_all_user_states(self):
        """
        Return UserAnnotationState for :username:
        """
        return UserAnnotationState.query.all()

    def _get_user(self, username):
        """
        Return User with :username:
        """
        return User.query.filter_by(username=username).first()

    def _get_all_users(self):
        """
        Return User with :username:
        """
        return User.query.all()

    def get_total_annotations(self):
        """
        Returns the total number of unique annotations done across all users.
        """
        total = 0
        for user_state in self._get_all_user_states():
            total += user_state.get_annotation_count()
        return total

    def get_annotations_for_user_on(self, username, instance_id):
        """
        Returns the label-based annotations made by this user on the instance.
        """
        user_state = self.get_user_state(username)
        annotations = user_state.get_label_annotations(instance_id)
        return annotations

    def get_span_annotations_for_user_on(self, username, instance_id):
        """
        Returns the span annotations made by this user on the instance.
        """
        user_state = self.get_user_state(username)
        span_annotations = user_state.get_span_annotations(instance_id)
        return span_annotations

    def update_annotation_state(self, username, form):
        """
        Parses the state of the HTML form (what the user did to the instance) and
        updates the state of the instance's annotations accordingly.
        """
        # Get what the user has already annotated, which might include
        # this instance too
        user_state = self.get_user_state(username)

        # Jiaxin: the instance_id are changed to the user's local instance cursor
        instance_id = user_state.cursor_to_real_instance_id(
            int(form["instance_id"])
        )

        schema_to_label_to_value = defaultdict(dict)

        behavioral_data_dict = {}

        did_change = False
        for key in form:

            # look for behavioral information regarding time, click, ...
            if key[:9] == "behavior_":
                behavioral_data_dict[key[9:]] = form[key]
                continue

            # Look for the marker that indicates an annotation label.
            #
            # NOTE: The span annotation uses radio buttons as well to figure out
            # which label. These inputs are labeled with "span_label" so we can
            # skip them as being actual annotatins (spans are saved below though).
            if ":::" in key and "span_label" not in key:

                cols = key.split(":::")
                annotation_schema = cols[0]
                annotation_label = cols[1]
                annotation_value = form[key]

                # skip the input when it is an empty string (from a text-box)
                if annotation_value == "":
                    continue

                schema_to_label_to_value[annotation_schema][
                    annotation_label
                ] = annotation_value

        # Span annotations are a bit funkier since we're getting raw HTML that
        # we need to post-process on the server side.
        span_annotations = []
        if "span-annotation" in form:
            span_annotation_html = form["span-annotation"]
            span_text, span_annotations = _parse_html_span_annotation(
                span_annotation_html
            )

        did_change = self._set_annotation(
            username,
            instance_id,
            schema_to_label_to_value,
            span_annotations,
            behavioral_data_dict,
        )

        # update the behavioral information regarding time only when
        # the annotations are changed
        if did_change:
            user_state.instance_id_to_behavioral_data[
                instance_id
            ] = behavioral_data_dict

            flag_modified(user_state, "instance_id_to_behavioral_data")

            flag_modified(user_state, "instance_id_to_data")
            flag_modified(user_state, "instance_id_ordering")
            flag_modified(user_state, "instance_id_to_order")

            self.db.session.merge(user_state)

            # TODO: we probably need a more elegant way to check
            # the status of user consent
            # when the user agreed to participate, try to assign
            if re.search("consent", instance_id):
                consent_key = "I want to participate in this research and continue with the study."
                user_state.consent_agreed = False
                if schema_to_label_to_value[consent_key].get("Yes") == "true":
                    user_state.consent_agreed = True

                self.assign_instances_to_user(username)

            # when the user is working on prestudy, check the status
            if re.search("prestudy", instance_id):
                print(self.check_prestudy_status(username))

        self.db.session.commit()
        return did_change

    def save_all_annotations(self):
        # Figure out where this user's data would be stored on disk
        output_annotation_dir = config["output_annotation_dir"]
        fmt = config["output_annotation_format"]

        if fmt not in ["csv", "tsv", "json", "jsonl"]:
            raise Exception("Unsupported output format: " + fmt)

        if not os.path.exists(output_annotation_dir):
            os.makedirs(output_annotation_dir)
            logger.debug(
                "Created state directory for annotations: %s"
                % (output_annotation_dir)
            )

        annotated_instances_fname = os.path.join(
            output_annotation_dir, "annotated_instances." + fmt
        )

        # We write jsonl format regardless
        if fmt in ["json", "jsonl"]:
            with open(annotated_instances_fname, "wt") as outf:
                for user_state in self._get_all_user_states():
                    for (
                        inst_id,
                        data,
                    ) in user_state.get_all_annotations().items():

                        bd_dict = (
                            user_state.instance_id_to_behavioral_data.get(
                                inst_id, {}
                            )
                        )

                        output = {
                            "id": inst_id,
                            "displayed_text": state.instance_id_to_data[
                                inst_id
                            ]["displayed_text"],
                            "label_annotations": data["labels"],
                            "span_annotations": data["spans"],
                            "behavioral_data": bd_dict,
                        }
                        json.dump(output, outf)
                        outf.write("\n")

        # Convert to Pandas and then dump
        elif fmt in ["csv", "tsv"]:
            df = defaultdict(list)

            # Loop 1, figure out which schemas/labels have values so we know which
            # things will need to be columns in each row
            schema_to_labels = defaultdict(set)
            span_labels = set()

            for user_state in self._get_all_user_states():
                for annotations in user_state.get_all_annotations().values():
                    # Columns for each label-based annotation
                    for schema, label_vals in annotations["labels"].items():
                        for label in label_vals.keys():
                            schema_to_labels[schema].add(label)

                    # Columns for each span type too
                    for span in annotations["spans"]:
                        span_labels.add(span["annotation"])

                    # TODO: figure out what's in the behavioral dict and how to format it

            # Loop 2, report everything that's been annotated
            for user_state in self._get_all_user_states():
                for (
                    inst_id,
                    annotations,
                ) in user_state.get_all_annotations().items():

                    df["user"].append(user_state.username)
                    df["instance_id"].append(inst_id)
                    df["displayed_text"].append(
                        state.instance_id_to_data[inst_id]["displayed_text"]
                    )

                    label_annotations = annotations["labels"]
                    span_annotations = annotations["spans"]

                    for schema, labels in schema_to_labels.items():
                        if schema in label_annotations:
                            label_vals = label_annotations[schema]
                            for label in labels:
                                val = label_vals.get(label)
                                # For some sanity, combine the schema and label it a single column
                                df[schema + ":::" + label].append(val)
                        # If the user did label this schema at all, fill it with None values
                        else:
                            for label in labels:
                                df[schema + ":::" + label].append(None)

                    # We bunch spans by their label to make it slightly easier to
                    # process, but it's still kind of messy compared with the JSON
                    # format.
                    for span_label in span_labels:
                        anns = [
                            sa
                            for sa in span_annotations
                            if sa["annotation"] == span_label
                        ]
                        df["span_annotation:::" + span_label].append(anns)

                    # TODO: figure out what's in the behavioral dict and how to format it

            df = pd.DataFrame(df)
            sep = "," if fmt == "csv" else "\t"
            df.to_csv(annotated_instances_fname, index=False, sep=sep)

        # Save the annotation assignment info if automatic task assignment is on.
        # Jiaxin: we are simply saving this as a json file at this moment
        if (
            "automatic_assignment" in config
            and config["automatic_assignment"]["on"]
        ):
            # TODO: write the code here
            print("saved")

    def check_prestudy_status(self, username):
        """
        Check whether a user has passed the prestudy test
        (this function will only be used)
        :return:
        """
        if "prestudy" not in config or config["prestudy"]["on"] is False:
            return "no prestudy test"

        user_state = self.get_user_state(username)

        # directly return the status if the user has passed/failed
        # the prestudy before
        if not user_state.get_prestudy_status():
            return "prestudy failed"
        if user_state.get_prestudy_status():
            return "prestudy passed"

        res = []
        for _id in state.task_assignment["prestudy_ids"]:
            label = user_state.get_label_annotations(_id)
            if label is None:
                return "prestudy not complete"
            groundtruth = state.instance_id_to_data[_id][
                config["prestudy"]["groundtruth_key"]
            ]
            label = get_prestudy_label(label)
            res.append(label == groundtruth)

        # check if the score is higher than the minimum defined in config
        if (sum(res) / len(res)) < config["prestudy"]["minimum_score"]:
            user_state.set_prestudy_status(False)
            state.task_assignment["prestudy_failed_users"].append(username)
            prestudy_result = "prestudy just failed"
        else:
            user_state.set_prestudy_status(True)
            state.task_assignment["prestudy_passed_users"].append(username)
            prestudy_result = "prestudy just passed"

        print_prestudy_result()

        # update the annotation list according the prestudy test result
        self.assign_instances_to_user(username)
        return prestudy_result

    def assign_instances_to_user(self, username):
        """
        Assign instances to a user
        :return: UserAnnotationState
        """
        user_state = self._get_user_state(username)

        # check if the user has already been assigned with instances to annotate
        # Currently we are just assigning once, but we might chance this later
        if user_state.get_real_assigned_instance_count() > 0:
            logger.warning(
                "Instance already assigned to user %s, assigning process stoppped"
                % username
            )
            return False

        prestudy_status = user_state.get_prestudy_status()
        consent_status = user_state.get_consent_status()

        if prestudy_status is None:
            if "prestudy" in config and config["prestudy"]["on"]:
                logger.warning(
                    "Trying to assign instances to user when the prestudy test is not completed, assigning process stoppped"
                )
                return False

            if (
                "surveyflow" not in config
                or not config["surveyflow"]["on"]
                or "prestudy" not in config
                or not config["prestudy"]["on"]
            ) or consent_status:
                sampled_keys = _sample_instances(username)
                user_state.real_instance_assigned_count = (
                    user_state.real_instance_assigned_count + len(sampled_keys)
                )
                if "post_annotation_pages" in state.task_assignment:
                    sampled_keys = (
                        sampled_keys
                        + state.task_assignment["post_annotation_pages"]
                    )
            else:
                logger.warning(
                    "Trying to assign instances to user when the user has yet agreed to participate. assigning process stoppped"
                )
                return False

        elif prestudy_status is False:
            sampled_keys = state.task_assignment["prestudy_failed_pages"]

        else:
            sampled_keys = _sample_instances(username)
            user_state.real_instance_assigned_count = (
                user_state.real_instance_assigned_count + len(sampled_keys)
            )
            sampled_keys = (
                state.task_assignment["prestudy_passed_pages"] + sampled_keys
            )
            if "post_annotation_pages" in state.task_assignment:
                sampled_keys = (
                    sampled_keys
                    + state.task_assignment["post_annotation_pages"]
                )

        assigned_user_data = {
            key: state.instance_id_to_data[key] for key in sampled_keys
        }
        user_state.add_new_assigned_data(assigned_user_data)

        print(
            "assinged %d instances to %s, total pages: %s"
            % (
                user_state.get_real_assigned_instance_count(),
                username,
                user_state.get_assigned_instance_count(),
            )
        )

        # save the assigned user data dict
        user_dir = os.path.join(config["output_annotation_dir"], username)
        assigned_user_data_path = user_dir + "/assigned_user_data.json"

        if not os.path.exists(user_dir):
            os.makedirs(user_dir)
            logger.debug('Created state directory for user "%s"' % (username))

        with open(assigned_user_data_path, "w") as file_p:
            json.dump(user_state.get_assigned_data(), file_p)

        # save task assignment status
        task_assignment_path = (
            config["output_annotation_dir"]
            + config["automatic_assignment"]["output_filename"]
        )
        with open(task_assignment_path, "w") as file_p:
            json.dump(state.task_assignment, file_p)

        user_state.instance_assigned = True
        self.db.session.commit()

        # return the assigned user data dict
        return assigned_user_data


def generate_full_user_dataflow(username):
    """
    Directly assign all the instances to a user at the beginning of the study
    :return: UserAnnotationState
    """
    if "sampling_strategy" not in config["automatic_assignment"]:
        logger.debug(
            "Undefined sampling strategy, default to random assignment"
        )
        config["automatic_assignment"]["sampling_strategy"] = "random"

    # Force the sampling strategy to be random at this moment, will change this
    # when more sampling strategies are created
    config["automatic_assignment"]["sampling_strategy"] = "random"

    if config["automatic_assignment"]["sampling_strategy"] == "random":
        sampled_keys = random.sample(
            list(state.task_assignment["unassigned"].keys()),
            config["automatic_assignment"]["instance_per_annotator"],
        )
        # update state.task_assignment to keep track of task assignment status globally
        for key in sampled_keys:
            if key not in state.task_assignment["assigned"]:
                state.task_assignment["assigned"][key] = []
            state.task_assignment["assigned"][key].append(username)
            state.task_assignment["unassigned"][key] -= 1
            if state.task_assignment["unassigned"][key] == 0:
                del state.task_assignment["unassigned"][key]

        # sample and insert test questions
        if state.task_assignment["testing"]["test_question_per_annotator"] > 0:
            sampled_testing_ids = random.sample(
                state.task_assignment["testing"]["ids"],
                k=state.task_assignment["testing"][
                    "test_question_per_annotator"
                ],
            )
            # adding test question sampling status to the task assignment
            for key in sampled_testing_ids:
                if key not in state.task_assignment["assigned"]:
                    state.task_assignment["assigned"][key] = []
                state.task_assignment["assigned"][key].append(username)
                sampled_keys.insert(
                    random.randint(0, len(sampled_keys) - 1), key
                )

        # save task assignment status
        task_assignment_path = os.path.join(
            config["output_annotation_dir"],
            config["automatic_assignment"]["output_filename"],
        )
        with open(task_assignment_path, "w") as file_p:
            json.dump(state.task_assignment, file_p)

        # add the amount of sampled instances
        real_assigned_instance_count = len(sampled_keys)

        if "pre_annotation_pages" in state.task_assignment:
            sampled_keys = (
                state.task_assignment["pre_annotation_pages"] + sampled_keys
            )

        if "post_annotation_pages" in state.task_assignment:
            sampled_keys = (
                sampled_keys + state.task_assignment["post_annotation_pages"]
            )

        assigned_user_data = {
            key: state.instance_id_to_data[key] for key in sampled_keys
        }

        # save the assigned user data dict
        user_dir = os.path.join(config["output_annotation_dir"], username)
        assigned_user_data_path = user_dir + "/assigned_user_data.json"

        if not os.path.exists(user_dir):
            os.makedirs(user_dir)
            logger.debug('Created state directory for user "%s"' % (username))

        with open(assigned_user_data_path, "w") as file_p:
            json.dump(assigned_user_data, file_p)

        # return the assigned user data dict
        return assigned_user_data, real_assigned_instance_count


def _sample_instances(username):
    if "sampling_strategy" not in config["automatic_assignment"]:
        logger.debug(
            "Undefined sampling strategy, default to random assignment"
        )
        config["automatic_assignment"]["sampling_strategy"] = "random"

    # Force the sampling strategy to be random at this moment, will change this
    # when more sampling strategies are created
    config["automatic_assignment"]["sampling_strategy"] = "random"

    if config["automatic_assignment"]["sampling_strategy"] == "random":
        # previously we were doing random sample directly, however, when there
        # are a large amount of instances and users, it is possible that some
        # instances are rarely sampled and some are oversampled at the end of
        # the sampling process
        # sampled_keys = random.sample(list(state.task_assignment['unassigned'].keys()),
        #                             config["automatic_assignment"]["instance_per_annotator"])

        # Currently we will shuffle the unassinged keys first, and then rank
        # the dict based on the availability of each instance, and they directly
        # get the first N instances
        unassigned_dict = state.task_assignment["unassigned"]
        unassigned_dict = {
            k: unassigned_dict[k]
            for k in random.sample(
                list(unassigned_dict.keys()), len(unassigned_dict)
            )
        }
        sorted_keys = [
            it[0]
            for it in sorted(
                unassigned_dict.items(), key=lambda item: item[1], reverse=True
            )
        ]
        sampled_keys = sorted_keys[
            : min(
                config["automatic_assignment"]["instance_per_annotator"],
                len(sorted_keys),
            )
        ]

        # update state.task_assignment to keep track of task assignment status globally
        for key in sampled_keys:
            if key not in state.task_assignment["assigned"]:
                state.task_assignment["assigned"][key] = []
            state.task_assignment["assigned"][key].append(username)
            state.task_assignment["unassigned"][key] -= 1
            if state.task_assignment["unassigned"][key] == 0:
                del state.task_assignment["unassigned"][key]

        # sample and insert test questions
        if state.task_assignment["testing"]["test_question_per_annotator"] > 0:
            sampled_testing_ids = random.sample(
                state.task_assignment["testing"]["ids"],
                k=state.task_assignment["testing"][
                    "test_question_per_annotator"
                ],
            )
            # adding test question sampling status to the task assignment
            for key in sampled_testing_ids:
                if key not in state.task_assignment["assigned"]:
                    state.task_assignment["assigned"][key] = []
                state.task_assignment["assigned"][key].append(username)
                sampled_keys.insert(
                    random.randint(0, len(sampled_keys) - 1), key
                )

    return sampled_keys


def generate_initial_user_dataflow(username):
    """
    Generate initial dataflow for a new annotator including
    surveyflows and prestudy.
    :return: UserAnnotationState
    """
    sampled_keys = []
    for _it in ["pre_annotation_pages", "prestudy_ids"]:
        if _it in state.task_assignment:
            sampled_keys += state.task_assignment[_it]

    assigned_user_data = {
        key: state.instance_id_to_data[key] for key in sampled_keys
    }

    # save the assigned user data dict
    user_dir = os.path.join(config["output_annotation_dir"], username)
    assigned_user_data_path = user_dir + "/assigned_user_data.json"

    if not os.path.exists(user_dir):
        os.makedirs(user_dir)
        logger.debug('Created state directory for user "%s"' % (username))

    with open(assigned_user_data_path, "w") as file_p:
        json.dump(assigned_user_data, file_p, indent=4)

    # return the assigned user data dict
    return assigned_user_data

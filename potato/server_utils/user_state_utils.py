"""
Utility functions around user state management.
Namely, we likely care about the following:
    * lookup_user_state()
    * save_user_state()
    * load_user_state()
    * assign_instances_to_user()
    * move_to_prev_instance()
    * move_to_next_instance()
    * go_to_id()
"""

import os
import json
import random
import logging
import state
from server_utils.config_module import config
from server_utils.user_annotation_state import UserAnnotationState

logger = logging.getLogger(__name__)


def lookup_user_state(username):
    """
    Returns the UserAnnotationState for a user, or if that user has not yet
    annotated, creates a new state for them and registers them with the system.
    """
    if username not in state.user_to_annotation_state:
        logger.debug('Previously unknown user "%s"; creating new annotation state' % (username))

        if "automatic_assignment" in config and config["automatic_assignment"]["on"]:
            # assign instances to new user when automatic assignment is on.
            if "prestudy" in config and config["prestudy"]["on"]:
                user_state = UserAnnotationState(generate_initial_user_dataflow(username))
                state.user_to_annotation_state[username] = user_state

            else:
                user_state = UserAnnotationState(generate_initial_user_dataflow(username))
                state.user_to_annotation_state[username] = user_state
                assign_instances_to_user(username)

        else:
            # assign all the instance to each user when automatic assignment
            # is turned off
            user_state = UserAnnotationState(state.instance_id_to_data)
            state.user_to_annotation_state[username] = user_state
    else:
        user_state = state.user_to_annotation_state[username]

    return user_state


def save_user_state(username, save_order=False):
    """
    Dump user state to file.
    """
    # Figure out where this user's data would be stored on disk
    output_annotation_dir = config["output_annotation_dir"]

    # NB: Do some kind of sanitizing on the username to improve security
    user_dir = os.path.join(output_annotation_dir, username)

    user_state = lookup_user_state(username)

    if not os.path.exists(user_dir):
        os.makedirs(user_dir)
        logger.debug('Created state directory for user "%s"' % (username))

    annotation_order_fname = os.path.join(user_dir, "annotation_order.txt")
    if not os.path.exists(annotation_order_fname) or save_order:
        with open(annotation_order_fname, "wt") as outf:
            for inst in user_state.instance_id_ordering:
                # JIAXIN: output id has to be str
                outf.write(str(inst) + "\n")

    annotated_instances_fname = os.path.join(user_dir, "annotated_instances.jsonl")

    with open(annotated_instances_fname, "wt") as outf:
        for inst_id, data in user_state.get_all_annotations().items():
            bd_dict = {}
            if inst_id in user_state.instance_id_to_behavioral_data:
                bd_dict = user_state.instance_id_to_behavioral_data[inst_id]

            output = {
                "id": inst_id,
                "displayed_text": state.instance_id_to_data[inst_id]["displayed_text"],
                "label_annotations": data["labels"],
                "span_annotations": data["spans"],
                "behavioral_data": bd_dict,
            }
            json.dump(output, outf)
            outf.write("\n")


def load_user_state(username):
    """
    Loads the user's state from disk. The state includes which instances they
    have annotated and the order in which they are expected to see instances.
    """
    # Figure out where this user's data would be stored on disk
    user_state_dir = config["output_annotation_dir"]

    # NB: Do some kind of sanitizing on the username to improve securty
    user_dir = os.path.join(user_state_dir, username)

    # User has annotated before or has assigned_data
    if os.path.exists(user_dir):
        logger.debug('Found known user "%s"; loading annotation state' % (username))

        # if automatic assignment is on, load assigned user data
        if "automatic_assignment" in config and config["automatic_assignment"]["on"]:
            assigned_user_data_path = user_dir + "/assigned_user_data.json"

            with open(assigned_user_data_path, "r") as file_p:
                assigned_user_data = json.load(file_p)
        # otherwise, set the assigned user data as all the instances
        else:
            assigned_user_data = state.instance_id_to_data

        annotation_order = []
        annotation_order_fname = os.path.join(user_dir, "annotation_order.txt")
        if os.path.exists(annotation_order_fname):
            with open(annotation_order_fname, "rt") as file_p:
                for line in file_p:
                    instance_id = line[:-1]
                    if instance_id not in assigned_user_data:
                        logger.warning(
                            (
                                "Annotation state for %s does not match "
                                + "instances in existing dataset at %s"
                            )
                            % (user_dir, ",".join(config["data_files"]))
                        )
                        continue
                    annotation_order.append(line[:-1])

        annotated_instances = []
        annotated_instances_fname = os.path.join(user_dir, "annotated_instances.jsonl")
        if os.path.exists(annotated_instances_fname):

            with open(annotated_instances_fname, "rt") as file_p:
                for line in file_p:
                    annotated_instance = json.loads(line)
                    instance_id = annotated_instance["id"]
                    if instance_id not in assigned_user_data:
                        logger.warning(
                            (
                                "Annotation state for %s does not match "
                                + "instances in existing dataset at %s"
                            )
                            % (user_dir, ",".join(config["data_files"]))
                        )
                        continue
                    annotated_instances.append(annotated_instance)

        # Ensure the current data is represented in the annotation order
        # NOTE: this is a hack to be fixed for when old user data is in the
        # same directory
        for iid in assigned_user_data.keys():
            if iid not in annotation_order:
                annotation_order.append(iid)

        user_state = UserAnnotationState(assigned_user_data)
        user_state.update(annotation_order, annotated_instances)

        # Make sure we keep track of the user throughout the program
        state.user_to_annotation_state[username] = user_state

        logger.info(
            'Loaded %d annotations for known user "%s"'
            % (user_state.get_annotation_count(), username)
        )

        return "old user loaded"

    # New user, so initialize state
    logger.debug('Previously unknown user "%s"; creating new annotation state' % (username))

    # create new user state with the look up function
    if instances_all_assigned():
        return "all instances have been assigned"

    lookup_user_state(username)
    return "new user initialized"


def move_to_prev_instance(username):
    user_state = lookup_user_state(username)
    user_state.go_back()


def move_to_next_instance(username):
    user_state = lookup_user_state(username)
    user_state.go_forward()


def go_to_id(username, _id):
    # go to specific item
    user_state = lookup_user_state(username)
    user_state.go_to_id(int(_id))


def assign_instances_to_user(username):
    """
    Assign instances to a user
    :return: UserAnnotationState
    """
    user_state = state.user_to_annotation_state[username]

    # check if the user has already been assigned with instances to annotate
    # Currently we are just assigning once, but we might chance this later
    if user_state.get_real_assigned_instance_count() > 0:
        logger.warning(
            "Instance already assigned to user %s, assigning process stoppped" % username
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
            user_state.real_instance_assigned_count += len(sampled_keys)
            if "post_annotation_pages" in state.task_assignment:
                sampled_keys = sampled_keys + state.task_assignment["post_annotation_pages"]
        else:
            logger.warning(
                "Trying to assign instances to user when the user has yet agreed to participate. assigning process stoppped"
            )
            return False

    elif prestudy_status is False:
        sampled_keys = state.task_assignment["prestudy_failed_pages"]

    else:
        sampled_keys = _sample_instances(username)
        user_state.real_instance_assigned_count += len(sampled_keys)
        sampled_keys = state.task_assignment["prestudy_passed_pages"] + sampled_keys
        if "post_annotation_pages" in state.task_assignment:
            sampled_keys = sampled_keys + state.task_assignment["post_annotation_pages"]

    assigned_user_data = {key: state.instance_id_to_data[key] for key in sampled_keys}
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
        config["output_annotation_dir"] + config["automatic_assignment"]["output_filename"]
    )
    with open(task_assignment_path, "w") as file_p:
        json.dump(state.task_assignment, file_p)

    user_state.instance_assigned = True

    # return the assigned user data dict
    return assigned_user_data


def generate_full_user_dataflow(username):
    """
    Directly assign all the instances to a user at the beginning of the study
    :return: UserAnnotationState
    """
    if "sampling_strategy" not in config["automatic_assignment"]:
        logger.debug("Undefined sampling strategy, default to random assignment")
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
                k=state.task_assignment["testing"]["test_question_per_annotator"],
            )
            # adding test question sampling status to the task assignment
            for key in sampled_testing_ids:
                if key not in state.task_assignment["assigned"]:
                    state.task_assignment["assigned"][key] = []
                state.task_assignment["assigned"][key].append(username)
                sampled_keys.insert(random.randint(0, len(sampled_keys) - 1), key)

        # save task assignment status
        task_assignment_path = os.path.join(
            config["output_annotation_dir"], config["automatic_assignment"]["output_filename"]
        )
        with open(task_assignment_path, "w") as file_p:
            json.dump(state.task_assignment, file_p)

        # add the amount of sampled instances
        real_assigned_instance_count = len(sampled_keys)

        if "pre_annotation_pages" in state.task_assignment:
            sampled_keys = state.task_assignment["pre_annotation_pages"] + sampled_keys

        if "post_annotation_pages" in state.task_assignment:
            sampled_keys = sampled_keys + state.task_assignment["post_annotation_pages"]

        assigned_user_data = {key: state.instance_id_to_data[key] for key in sampled_keys}

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
        logger.debug("Undefined sampling strategy, default to random assignment")
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
            for k in random.sample(list(unassigned_dict.keys()), len(unassigned_dict))
        }
        sorted_keys = [
            it[0] for it in sorted(unassigned_dict.items(), key=lambda item: item[1], reverse=True)
        ]
        sampled_keys = sorted_keys[
            : min(config["automatic_assignment"]["instance_per_annotator"], len(sorted_keys))
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
                k=state.task_assignment["testing"]["test_question_per_annotator"],
            )
            # adding test question sampling status to the task assignment
            for key in sampled_testing_ids:
                if key not in state.task_assignment["assigned"]:
                    state.task_assignment["assigned"][key] = []
                state.task_assignment["assigned"][key].append(username)
                sampled_keys.insert(random.randint(0, len(sampled_keys) - 1), key)

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

    assigned_user_data = {key: state.instance_id_to_data[key] for key in sampled_keys}

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


def instances_all_assigned():
    """
    Check if all instances are assigned.
    """
    return len(state.task_assignment.get("unassigned", [])) <= int(
        config["automatic_assignment"]["instance_per_annotator"] * 0.7
    )

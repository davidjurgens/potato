"""
Utility functions surrounding pre-study.
"""

from server_utils.config_module import config
from server_utils.user_state_utils import lookup_user_state, assign_instances_to_user
import state


def convert_labels(annotation, schema_type):
    """
    Convert labels.
    """
    if schema_type == "likert":
        return int(list(annotation.keys())[0][6:])
    if schema_type == "radio":
        return list(annotation.keys())[0]
    if schema_type == "multiselect":
        return list(annotation.keys())
    print("Unrecognized schema_type %s" % schema_type)
    return None


def get_prestudy_label(label):
    """
    Get prestudy label.
    """
    for schema in config["annotation_schemes"]:
        if schema["name"] == config["prestudy"]["question_key"]:
            cur_schema = schema["annotation_type"]
    label = convert_labels(label[config["prestudy"]["question_key"]], cur_schema)
    return config["prestudy"]["answer_mapping"][label]


def print_prestudy_result():
    """
    Print prestudy results.
    """
    print("----- prestudy test restult -----")
    print("passed annotators: ", state.task_assignment["prestudy_passed_users"])
    print("failed annotators: ", state.task_assignment["prestudy_failed_users"])
    print(
        "pass rate: ",
        len(state.task_assignment["prestudy_passed_users"])
        / len(
            state.task_assignment["prestudy_passed_users"]
            + state.task_assignment["prestudy_failed_users"]
        ),
    )


def check_prestudy_status(username):
    """
    Check whether a user has passed the prestudy test
    (this function will only be used)
    :return:
    """
    if "prestudy" not in config or config["prestudy"]["on"] is False:
        return "no prestudy test"

    user_state = lookup_user_state(username)

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
        groundtruth = state.instance_id_to_data[_id][config["prestudy"]["groundtruth_key"]]
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
    assign_instances_to_user(username)

    return prestudy_result

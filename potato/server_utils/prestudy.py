"""
Utility functions surrounding pre-study.
"""

from potato.app import db
from potato.server_utils.config_module import config
import potato.state as state


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



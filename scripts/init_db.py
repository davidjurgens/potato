"""
Module Doc String
"""

import os
import json
from collections import OrderedDict, defaultdict
import pandas as pd
import yaml
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from potato.db_utils.models.user import User
from potato.db_utils.models.user_annotation_state import UserAnnotationState
from potato.flask_server import get_displayed_text
from constants import POTATO_HOME

Base = declarative_base()


def load_all_data(config):
    # Where to look in the JSON item object for the text to annotate
    text_key = config["item_properties"]["text_key"]
    id_key = config["item_properties"]["id_key"]

    # Keep the data in the same order we read it in
    instance_id_to_data = OrderedDict()

    data_files = config["data_files"]

    for data_fname in data_files:

        fmt = data_fname.split(".")[-1]
        if fmt not in ["csv", "tsv", "json", "jsonl"]:
            raise Exception(
                "Unsupported input file format %s for %s" % (fmt, data_fname)
            )

        if fmt in ["json", "jsonl"]:
            with open(data_fname, "rt") as f:
                for line_no, line in enumerate(f):
                    item = json.loads(line)

                    # fix the encoding
                    # item[text_key] = item[text_key].encode("latin-1").decode("utf-8")

                    instance_id = item[id_key]

                    # TODO: check for duplicate instance_id
                    instance_id_to_data[instance_id] = item

        else:
            sep = "," if fmt == "csv" else "\t"
            # Ensure the key is loaded as a string form (prevents weirdness
            # later)
            df = pd.read_csv(
                data_fname, sep=sep, dtype={id_key: str, text_key: str}
            )
            for _, row in df.iterrows():

                item = {}
                for c in df.columns:
                    item[c] = row[c]
                instance_id = row[id_key]

                # TODO: check for duplicate instance_id
                instance_id_to_data[instance_id] = item

    # TODO Setup automatic test questions for each annotation schema,
    # currently we are doing it similar to survey flow to allow multilingual test questions
    if "surveyflow" in config and config["surveyflow"]["on"]:
        for test_file in config["surveyflow"].get("testing", []):
            with open(test_file, "r") as r:
                for line in r:
                    line = json.loads(line.strip())
                    for l in line["choices"]:
                        item = {
                            "id": line["id"] + "_testing_" + l,
                            "text": line["text"].replace(
                                "[test_question_choice]", l
                            ),
                        }
                        # currently we simply move all these test questions to the end of the instance list
                        instance_id_to_data.update({item["id"]: item})
                        instance_id_to_data.move_to_end(item["id"], last=True)

    # insert survey questions into state.instance_id_to_data
    for page in config.get("pre_annotation_pages", []):
        # TODO Currently we simply remove the language type before,
        # but we need a more elegant way for this in the future
        item = {"id": page, "text": page.split("-")[-1][:-5]}
        instance_id_to_data.update({page: item})
        instance_id_to_data.move_to_end(page, last=False)

    for it in ["prestudy_failed_pages", "prestudy_passed_pages"]:
        for page in config.get(it, []):
            # TODO Currently we simply remove the language type before -,
            # but we need a more elegant way for this in the future
            item = {"id": page, "text": page.split("-")[-1][:-5]}
            instance_id_to_data.update({page: item})
            instance_id_to_data.move_to_end(page, last=False)

    for page in config.get("post_annotation_pages", []):
        item = {"id": page, "text": page.split("-")[-1][:-5]}
        instance_id_to_data.update({page: item})
        instance_id_to_data.move_to_end(page, last=True)

    # Generate the text to display in state.instance_id_to_data
    for inst_id in instance_id_to_data:
        instance_id_to_data[inst_id]["displayed_text"] = get_displayed_text(
            instance_id_to_data[inst_id][config["item_properties"]["text_key"]]
        )

    return instance_id_to_data


def init_db(config, user_config_path, project_dir, instance_id_to_data):
    """
    Initialize DB.
    """
    db_path = config["db_path"]

    json_users = []
    with open(user_config_path, "r") as file_p:
        for line in file_p:
            json_users.append(json.loads(line))

    users = [
        User(
            username=json_user["username"],
            email=json_user["email"],
            password=json_user["password"],
            annotation_state=None,
        )
        for json_user in json_users
    ]

    engine = create_engine("sqlite:///" + db_path)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine, tables=[User.__table__, UserAnnotationState.__table__])
    with Session(engine) as session:
        session.add_all(users)
        session.commit()

        for user in users:
            username = user.username
            annotation_dir = os.path.join(
                project_dir, "annotation_output/%s" % username
            )

            # User has NOT annotated before or has assigned_data
            if not os.path.exists(annotation_dir):
                print("Continuing")
                continue

            # if automatic assignment is on, load assigned user data
            if (
                "automatic_assignment" in config
                and config["automatic_assignment"]["on"]
            ):
                assigned_user_data_path = (
                    annotation_dir + "/assigned_user_data.json"
                )

                with open(assigned_user_data_path, "r") as file_p:
                    assigned_user_data = json.load(file_p)
            # otherwise, set the assigned user data as all the instances
            else:
                assigned_user_data = instance_id_to_data

            annotation_order = []
            annotation_order_fname = os.path.join(
                annotation_dir, "annotation_order.txt"
            )
            if os.path.exists(annotation_order_fname):
                with open(annotation_order_fname, "rt") as file_p:
                    for line in file_p:
                        annotation_order.append(line[:-1])

            annotated_instances = []
            annotated_instances_fname = os.path.join(
                annotation_dir, "annotated_instances.jsonl"
            )
            if os.path.exists(annotated_instances_fname):

                with open(annotated_instances_fname, "rt") as file_p:
                    for line in file_p:
                        annotated_instance = json.loads(line)
                        annotated_instances.append(annotated_instance)

            # Ensure the current data is represented in the annotation order
            # NOTE: this is a hack to be fixed for when old user data is in the
            # same directory
            for iid in assigned_user_data.keys():
                if iid not in annotation_order:
                    annotation_order.append(iid)

            user_annotation_state = UserAnnotationState(
                username, assigned_user_data
            )
            user_annotation_state.update(annotation_order, annotated_instances)
            breakpoint()
            session.add(user_annotation_state)
            session.commit()


def main():
    """ Driver """

    project_dir = os.path.join(
        POTATO_HOME, "example-projects/dialogue_analysis"
    )
    config_filepath = os.path.join(
        project_dir, "configs/dialogue-analysis.yaml"
    )
    user_config_path = os.path.join(POTATO_HOME, "potato/user_config.json")

    with open(config_filepath, "r") as file_p:
        config = yaml.safe_load(file_p)

    instance_id_to_data = load_all_data(config)
    init_db(config, user_config_path, project_dir, instance_id_to_data)


if __name__ == "__main__":
    main()

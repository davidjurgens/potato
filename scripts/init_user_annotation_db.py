"""
Initialize DB with user_config.json file.
"""

import os
import json
from collections import OrderedDict, defaultdict
import pandas as pd
import yaml
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from potato.db_utils.models.user_annotation_state import UserAnnotationState
from potato.flask_server import get_displayed_text

Base = declarative_base()


def load_all_data(config):
    # Hacky nonsense
    global re_to_highlights

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
            line_no = len(df)

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


# Modified version of potato.server_utils.user_state_utils.load_user_state()
def dump_to_db(username, user_dir, instance_id_to_data, config, db_path):
    """
    Loads the user's state from disk. The state includes which instances they
    have annotated and the order in which they are expected to see instances.
    """
    # User has NOT annotated before or has assigned_data
    if not os.path.exists(user_dir):
        return

    # if automatic assignment is on, load assigned user data
    if (
        "automatic_assignment" in config
        and config["automatic_assignment"]["on"]
    ):
        assigned_user_data_path = user_dir + "/assigned_user_data.json"

        with open(assigned_user_data_path, "r") as file_p:
            assigned_user_data = json.load(file_p)
    # otherwise, set the assigned user data as all the instances
    else:
        assigned_user_data = instance_id_to_data

    annotation_order = []
    annotation_order_fname = os.path.join(user_dir, "annotation_order.txt")
    if os.path.exists(annotation_order_fname):
        with open(annotation_order_fname, "rt") as file_p:
            for line in file_p:
                instance_id = line[:-1]
                annotation_order.append(line[:-1])

    annotated_instances = []
    annotated_instances_fname = os.path.join(
        user_dir, "annotated_instances.jsonl"
    )
    if os.path.exists(annotated_instances_fname):

        with open(annotated_instances_fname, "rt") as file_p:
            for line in file_p:
                annotated_instance = json.loads(line)
                instance_id = annotated_instance["id"]
                annotated_instances.append(annotated_instance)

    # Ensure the current data is represented in the annotation order
    # NOTE: this is a hack to be fixed for when old user data is in the
    # same directory
    for iid in assigned_user_data.keys():
        if iid not in annotation_order:
            annotation_order.append(iid)

    engine = create_engine("sqlite:///" + db_path)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine, tables=[UserAnnotationState.__table__])
    with Session(engine) as session:
        user_annotation_state = UserAnnotationState(assigned_user_data)
        user_annotation_state.update(annotation_order, annotated_instances)
        session.add(user_annotation_state)
        session.commit()


def main():
    """ Driver """
    config_filepath = "/home/repos/potato/example-projects/dialogue_analysis/configs/dialogue-analysis.yaml"
    with open(config_filepath, "r") as file_p:
        config = yaml.safe_load(file_p)

    instance_id_to_data = load_all_data(config)

    project_dir = "/home/repos/potato/example-projects/dialogue_analysis"
    db_path = os.path.join(project_dir, "database.db")
    users = ["zxcv@zxcv.com"]

    for _user in users:
        annotations_dir = os.path.join(
            project_dir, "annotation_output/%s" % _user
        )
        dump_to_db(
            _user, annotations_dir, instance_id_to_data, config, db_path
        )


if __name__ == "__main__":
    main()

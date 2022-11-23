from argparse import ArgumentParser
import yaml
import os
import pandas as pd
import json
from collections import defaultdict


def arguments():
    """
    Creates and returns the arg parser for Potato on the command line
    """
    parser = ArgumentParser()
    parser.set_defaults(show_path=False, show_similarity=False)

    parser.add_argument("multitask_config_file")

    return parser.parse_args()


def main():
    args = arguments()

    # load multitask annotation config
    with open(args.multitask_config_file, "rt") as f:
        multitask_config = yaml.safe_load(f)

    # create basic folders
    for folder in ["surveyflow", "annotation_output", "data_files", "configs", "htmls"]:
        cur_path = multitask_config["base_dir"] + folder
        if not os.path.exists(cur_path):
            os.makedirs(cur_path)
            print("Created directory: %s" % (cur_path))

    # build mapping dict
    key2text = defaultdict(dict)

    if "multitask_guideline_file" in multitask_config and os.path.exists(
        multitask_config["multitask_guideline_file"]
    ):
        # load multitask annotation guideline
        multitask_guideline_df = pd.read_csv(multitask_config["multitask_guideline_file"])
        for i, row in multitask_guideline_df.iterrows():
            if type(row["key"]) != str or row["key"][0] != "[" or row["key"][-1] != "]":
                continue
            for task in multitask_config["tasks"]:
                key2text[row["key"]][task] = (
                    row[task] if type(row[task]) == str else row[multitask_config["base_task"]]
                )

    for task in multitask_config["tasks"]:
        # load basic config file
        with open(multitask_config["base_config_file"], "rt") as f:
            page = f.read()
            for key in key2text:
                page = page.replace(key, key2text[key][task])

            surveyflow_output_path = multitask_config["surveyflow_output_path"].replace(
                "[TASK]", task
            )
            page = page.replace(
                multitask_config["surveyflow_path"], surveyflow_output_path + task + "-"
            )
            page = page.replace("[TASK]", task)

            config = yaml.safe_load(page)

        config["output_annotation_dir"] = multitask_config["output_annotation_dir"].replace(
            "[TASK]", task
        )
        if not os.path.exists(config["output_annotation_dir"]):
            os.makedirs(config["output_annotation_dir"])

        """
        # setup the site_dir path for each task
        config['path_under_site_dir'] = multitask_config['path_under_site_dir'].replace("[TASK]", task)
        config["site_dir"] += config['path_under_site_dir']
        if not os.path.exists(config["site_dir"]):
            os.makedirs(config["site_dir"])
        """

        config["annotation_task_name"] = multitask_config["annotation_task_name"].replace(
            "[TASK]", task
        )
        config["data_files"] = [
            it.replace("[TASK]", task) for it in multitask_config["data_files"]
        ]
        # config["prestudy"] = [it.replace("[TASK]", task) for it in multitask_config['prestudy']]

        with open(multitask_config["base_dir"] + "configs/%s.yaml" % task, "wt") as f:
            json.dump(config, f, indent=4)

        # create the dir for surveyflow_output_path
        if not os.path.exists(surveyflow_output_path):
            os.makedirs(surveyflow_output_path)

        # setup surveyflow pages
        surveyflow_files = os.listdir(multitask_config["surveyflow_path"])
        for file in surveyflow_files:
            if os.path.isdir(multitask_config["surveyflow_path"] + file):
                continue
            with open(multitask_config["surveyflow_path"] + file, "r") as f:
                page = f.read()
            for key in key2text:
                page = page.replace(key, key2text[key][task])
            page = page.replace("[TASK]", task)
            # print(surveyflow_output_path)
            with open(surveyflow_output_path + task + "-" + file, "wt") as f:
                f.write(page)

        # for key in ["surveyflow_output_path", ]


if __name__ == "__main__":
    main()

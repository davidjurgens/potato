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

    parser.add_argument("multilingual_config_file")

    return parser.parse_args()


def main():
    args = arguments()

    # load multilingual annotation config
    with open(args.multilingual_config_file, "rt") as f:
        multilingual_config = yaml.safe_load(f)

    # create basic folders
    for folder in ["surveyflow", "annotation_output", "data_files", "configs", "htmls"]:
        cur_path = multilingual_config["base_dir"] + folder
        if not os.path.exists(cur_path):
            os.makedirs(cur_path)
            print("Created directory: %s" % (cur_path))

    # build mapping dict
    key2text = defaultdict(dict)

    if "multilingual_guideline_file" in multilingual_config and os.path.exists(
        multilingual_config["multilingual_guideline_file"]
    ):
        # load multilingual annotation guideline
        multilingual_guideline_df = pd.read_csv(multilingual_config["multilingual_guideline_file"])
        for i, row in multilingual_guideline_df.iterrows():
            if type(row["key"]) != str or row["key"][0] != "[" or row["key"][-1] != "]":
                continue
            for lang in multilingual_config["languages"]:
                key2text[row["key"]][lang] = (
                    row[lang]
                    if type(row[lang]) == str
                    else row[multilingual_config["base_language"]]
                )

    for lang in multilingual_config["languages"]:
        # load basic config file
        with open(multilingual_config["base_config_file"], "rt") as f:
            page = f.read()
            for key in key2text:
                page = page.replace(key, key2text[key][lang])

            surveyflow_output_path = multilingual_config["surveyflow_output_path"].replace(
                "[LANGUAGE]", lang
            )
            page = page.replace(
                multilingual_config["surveyflow_path"], surveyflow_output_path + lang + "-"
            )
            page = page.replace("[LANGUAGE]", lang)

            config = yaml.safe_load(page)

        config["output_annotation_dir"] = multilingual_config["output_annotation_dir"].replace(
            "[LANGUAGE]", lang
        )
        if not os.path.exists(config["output_annotation_dir"]):
            os.makedirs(config["output_annotation_dir"])

        """
        # setup the site_dir path for each language
        config['path_under_site_dir'] = multilingual_config['path_under_site_dir'].replace("[LANGUAGE]", lang)
        config["site_dir"] += config['path_under_site_dir']
        if not os.path.exists(config["site_dir"]):
            os.makedirs(config["site_dir"])
        """

        config["annotation_task_name"] = multilingual_config["annotation_task_name"].replace(
            "[LANGUAGE]", lang
        )
        config["data_files"] = [
            it.replace("[LANGUAGE]", lang) for it in multilingual_config["data_files"]
        ]

        with open(multilingual_config["base_dir"] + "configs/%s.yaml" % lang, "wt") as f:
            json.dump(config, f, indent=4)

        # create the dir for surveyflow_output_path
        if not os.path.exists(surveyflow_output_path):
            os.makedirs(surveyflow_output_path)

        # setup surveyflow pages
        surveyflow_files = os.listdir(multilingual_config["surveyflow_path"])
        for file in surveyflow_files:
            if os.path.isdir(multilingual_config["surveyflow_path"] + file):
                continue
            with open(multilingual_config["surveyflow_path"] + file, "r") as f:
                page = f.read()
            for key in key2text:
                page = page.replace(key, key2text[key][lang])
            page = page.replace("[LANGUAGE]", lang)
            # print(surveyflow_output_path)
            with open(surveyflow_output_path + lang + "-" + file, "wt") as f:
                f.write(page)

        # for key in ["surveyflow_output_path", ]


if __name__ == "__main__":
    main()

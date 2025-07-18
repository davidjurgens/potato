"""
Multitask Configuration Setup Module

This module provides functionality for setting up multitask annotation projects.
It processes a base configuration and creates task-specific configurations
for each supported task, including:

- Task-specific survey flow files
- Specialized configuration files
- Task-specific output directories
- Multitask guideline integration

The module supports dynamic text replacement using key-based task mappings
and creates the necessary directory structure for multitask annotation projects.
"""

from argparse import ArgumentParser
import yaml
import os
import pandas as pd
import json
from collections import defaultdict


def arguments():
    """
    Creates and returns the argument parser for multitask configuration setup.

    Returns:
        ArgumentParser: Configured argument parser with multitask_config_file argument
    """
    parser = ArgumentParser()
    parser.set_defaults(show_path=False, show_similarity=False)

    parser.add_argument("multitask_config_file")

    return parser.parse_args()


def main():
    """
    Main function for setting up multitask annotation configurations.

    This function processes a multitask configuration file and creates
    task-specific configurations for each supported task. It handles:

    1. Directory structure creation
    2. Task mapping from guideline files
    3. Configuration file generation for each task
    4. Survey flow file specialization
    5. Output directory setup

    Side Effects:
        - Creates directories for surveyflow, annotation_output, data_files, configs, htmls
        - Generates task-specific configuration files
        - Creates specialized survey flow files
        - Sets up task-specific output directories
    """
    args = arguments()

    # Load multitask annotation configuration
    with open(args.multitask_config_file, "rt") as f:
        multitask_config = yaml.safe_load(f)

    # Create basic folder structure for the multitask project
    for folder in ["surveyflow", "annotation_output", "data_files", "configs", "htmls"]:
        cur_path = multitask_config["base_dir"] + folder
        if not os.path.exists(cur_path):
            os.makedirs(cur_path)
            print("Created directory: %s" % (cur_path))

    # Build task mapping dictionary
    # This maps task keys to their task-specific text values
    key2text = defaultdict(dict)

    # Load multitask annotation guidelines if specified and available
    if "multitask_guideline_file" in multitask_config and os.path.exists(
        multitask_config["multitask_guideline_file"]
    ):
        # Load multitask annotation guideline from CSV
        multitask_guideline_df = pd.read_csv(multitask_config["multitask_guideline_file"])
        for i, row in multitask_guideline_df.iterrows():
            # Only process rows with proper key format (enclosed in brackets)
            if type(row["key"]) != str or row["key"][0] != "[" or row["key"][-1] != "]":
                continue
            # Create task mapping for each supported task
            for task in multitask_config["tasks"]:
                key2text[row["key"]][task] = (
                    row[task] if type(row[task]) == str else row[multitask_config["base_task"]]
                )

    # Generate configuration for each supported task
    for task in multitask_config["tasks"]:
        # Load and process the base configuration file
        with open(multitask_config["base_config_file"], "rt") as f:
            page = f.read()
            # Replace task keys with task-specific text
            for key in key2text:
                page = page.replace(key, key2text[key][task])

            # Update surveyflow output path for this task
            surveyflow_output_path = multitask_config["surveyflow_output_path"].replace(
                "[TASK]", task
            )
            page = page.replace(
                multitask_config["surveyflow_path"], surveyflow_output_path + task + "-"
            )
            page = page.replace("[TASK]", task)

            # Parse the processed configuration
            config = yaml.safe_load(page)

        # Set up task-specific output directory
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

        # Update task name and data files for this task
        config["annotation_task_name"] = multitask_config["annotation_task_name"].replace(
            "[TASK]", task
        )
        config["data_files"] = [
            it.replace("[TASK]", task) for it in multitask_config["data_files"]
        ]
        # config["prestudy"] = [it.replace("[TASK]", task) for it in multitask_config['prestudy']]

        # Save the task-specific configuration file
        with open(multitask_config["base_dir"] + "configs/%s.yaml" % task, "wt") as f:
            json.dump(config, f, indent=4)

        # Create the directory for surveyflow output path
        if not os.path.exists(surveyflow_output_path):
            os.makedirs(surveyflow_output_path)

        # Process and specialize surveyflow files
        surveyflow_files = os.listdir(multitask_config["surveyflow_path"])
        for file in surveyflow_files:
            # Skip directories, only process files
            if os.path.isdir(multitask_config["surveyflow_path"] + file):
                continue
            # Read the surveyflow file
            with open(multitask_config["surveyflow_path"] + file, "r") as f:
                page = f.read()
            # Replace task keys with task-specific text
            for key in key2text:
                page = page.replace(key, key2text[key][task])
            page = page.replace("[TASK]", task)
            # Write the specialized surveyflow file
            with open(surveyflow_output_path + task + "-" + file, "wt") as f:
                f.write(page)

        # for key in ["surveyflow_output_path", ]


if __name__ == "__main__":
    main()

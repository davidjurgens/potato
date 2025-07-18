"""
Multilingual Configuration Setup Module

This module provides functionality for setting up multilingual annotation tasks.
It processes a base configuration and creates language-specific configurations
for each supported language, including:

- Language-specific survey flow files
- Translated configuration files
- Localized output directories
- Multilingual guideline integration

The module supports dynamic text replacement using key-based translation mappings
and creates the necessary directory structure for multilingual annotation projects.
"""

from argparse import ArgumentParser
import yaml
import os
import pandas as pd
import json
from collections import defaultdict


def arguments():
    """
    Creates and returns the argument parser for multilingual configuration setup.

    Returns:
        ArgumentParser: Configured argument parser with multilingual_config_file argument
    """
    parser = ArgumentParser()
    parser.set_defaults(show_path=False, show_similarity=False)

    parser.add_argument("multilingual_config_file")

    return parser.parse_args()


def main():
    """
    Main function for setting up multilingual annotation configurations.

    This function processes a multilingual configuration file and creates
    language-specific configurations for each supported language. It handles:

    1. Directory structure creation
    2. Translation mapping from guideline files
    3. Configuration file generation for each language
    4. Survey flow file localization
    5. Output directory setup

    Side Effects:
        - Creates directories for surveyflow, annotation_output, data_files, configs, htmls
        - Generates language-specific configuration files
        - Creates localized survey flow files
        - Sets up language-specific output directories
    """
    args = arguments()

    # Load multilingual annotation configuration
    with open(args.multilingual_config_file, "rt") as f:
        multilingual_config = yaml.safe_load(f)

    # Create basic folder structure for the multilingual project
    for folder in ["surveyflow", "annotation_output", "data_files", "configs", "htmls"]:
        cur_path = multilingual_config["base_dir"] + folder
        if not os.path.exists(cur_path):
            os.makedirs(cur_path)
            print("Created directory: %s" % (cur_path))

    # Build translation mapping dictionary
    # This maps translation keys to their language-specific text values
    key2text = defaultdict(dict)

    # Load multilingual annotation guidelines if specified and available
    if "multilingual_guideline_file" in multilingual_config and os.path.exists(
        multilingual_config["multilingual_guideline_file"]
    ):
        # Load multilingual annotation guideline from CSV
        multilingual_guideline_df = pd.read_csv(multilingual_config["multilingual_guideline_file"])
        for i, row in multilingual_guideline_df.iterrows():
            # Only process rows with proper key format (enclosed in brackets)
            if type(row["key"]) != str or row["key"][0] != "[" or row["key"][-1] != "]":
                continue
            # Create translation mapping for each supported language
            for lang in multilingual_config["languages"]:
                key2text[row["key"]][lang] = (
                    row[lang]
                    if type(row[lang]) == str
                    else row[multilingual_config["base_language"]]
                )

    # Generate configuration for each supported language
    for lang in multilingual_config["languages"]:
        # Load and process the base configuration file
        with open(multilingual_config["base_config_file"], "rt") as f:
            page = f.read()
            # Replace translation keys with language-specific text
            for key in key2text:
                page = page.replace(key, key2text[key][lang])

            # Update surveyflow output path for this language
            surveyflow_output_path = multilingual_config["surveyflow_output_path"].replace(
                "[LANGUAGE]", lang
            )
            page = page.replace(
                multilingual_config["surveyflow_path"], surveyflow_output_path + lang + "-"
            )
            page = page.replace("[LANGUAGE]", lang)

            # Parse the processed configuration
            config = yaml.safe_load(page)

        # Set up language-specific output directory
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

        # Update task name and data files for this language
        config["annotation_task_name"] = multilingual_config["annotation_task_name"].replace(
            "[LANGUAGE]", lang
        )
        config["data_files"] = [
            it.replace("[LANGUAGE]", lang) for it in multilingual_config["data_files"]
        ]

        # Save the language-specific configuration file
        with open(multilingual_config["base_dir"] + "configs/%s.yaml" % lang, "wt") as f:
            json.dump(config, f, indent=4)

        # Create the directory for surveyflow output path
        if not os.path.exists(surveyflow_output_path):
            os.makedirs(surveyflow_output_path)

        # Process and localize surveyflow files
        surveyflow_files = os.listdir(multilingual_config["surveyflow_path"])
        for file in surveyflow_files:
            # Skip directories, only process files
            if os.path.isdir(multilingual_config["surveyflow_path"] + file):
                continue
            # Read the surveyflow file
            with open(multilingual_config["surveyflow_path"] + file, "r") as f:
                page = f.read()
            # Replace translation keys with language-specific text
            for key in key2text:
                page = page.replace(key, key2text[key][lang])
            page = page.replace("[LANGUAGE]", lang)
            # Write the localized surveyflow file
            with open(surveyflow_output_path + lang + "-" + file, "wt") as f:
                f.write(page)

        # for key in ["surveyflow_output_path", ]


if __name__ == "__main__":
    main()

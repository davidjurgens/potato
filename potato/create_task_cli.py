"""
Interactive Task Creation CLI Module

This module provides an interactive command-line interface for creating new
annotation tasks. It guides users through a series of questions to configure
their annotation task and generates a YAML configuration file.

The CLI supports various annotation types including:
- multiselect: Checkboxes where users can pick 0 or more options
- radio: Radio buttons where users must pick exactly 1 option
- text: Free text entry boxes
- likert: Likert scales with ordered radio buttons
- bws: Best-worst scaling where users select most/least extreme options

The generated configuration can be further customized by editing the YAML file.
"""

import json
from collections import OrderedDict
import os


def yes_or_no(question):
    """
    Prompt user for a yes/no response with validation.

    Args:
        question: The question to ask the user

    Returns:
        bool: True for yes, False for no

    Side Effects:
        - Prompts user for input
        - Continues prompting until valid input is received
    """
    while "the answer is invalid":
        reply = input(question + " (y/n): ").lower().strip()
        if reply[:1] == "y":
            return True
        if reply[:1] == "n":
            return False


def get_annotation_type():
    """
    Prompt user to select an annotation type.

    Returns:
        str: The selected annotation type

    Side Effects:
        - Displays available annotation types
        - Prompts user for selection
        - Validates input against allowed options
    """
    q = (
        "What type of annotation is this? Possible types are...\n"
        + "  multiselect -- checkboxes where users can pick 0 or more\n"
        + "  radio -- radio buttons where users must pick 1\n"
        + "  text -- free text entry box\n"
        + "  likert -- a likert scale with an order list of radio buttons\n"
        + "  bws -- a set of options where users select the most/least extreme "
        + "options w.r.t. some scale\n\n"
    )

    options = ("multiselect", "radio", "text", "likert", "bws")
    while "the answer is invalid":
        reply = input(q).lower().strip()
        if reply in options:
            return reply


def get_initial_config():
    """
    Create the initial configuration template with default values.

    Returns:
        OrderedDict: Configuration dictionary with default settings

    The initial config includes:
    - Server name and basic settings
    - User configuration (allow all users by default)
    - Alert timing settings
    - HTML layout and template settings
    - Site directory configuration
    """
    config = OrderedDict()

    config["server_name"] = "potato annotator"

    config["user_config"] = {"allow_all_users": True, "users": []}

    # The html that changes the visualization for your task. Change this file
    # to influence the layout and description of your task. This is not a full
    # HTML page, just the piece that does lays out your task's pieces
    config["html_layout"] = "default"

    # The core UI files for Potato. You should not need to change these normally.
    #
    # Exceptions to this might include:
    # 1) You want to add custom CSS/fonts to style your task
    # 2) Your layout requires additional JS/assets to render
    # 3) You want to support additional keybinding magic
    #
    config["base_html_template"] = "default"
    config["header_file"] = "default"

    # This is where the actual HTML files will be generated
    config["site_dir"] = "default"

    return config


def create_task_cli():
    """
    Main interactive task creation function.

    This function guides users through the process of creating a new annotation
    task by asking a series of questions about their requirements. It collects
    information about:

    1. Server configuration (port, task name)
    2. Data files and their structure
    3. Annotation schemes and types
    4. Output settings

    Side Effects:
        - Prompts user for various configuration options
        - Creates a YAML configuration file
        - Provides guidance and validation for user inputs
    """
    print("Welcome to the Potato annotation task creation process on the command line!")
    print("This process will walk you through a series of questions about your task")
    print("and generate a .yaml file that has the initial configuration for your")
    print("task. You can edit this .yaml file at any time after the process to tweak")
    print("the instructions, add fancier features, or even change the nature of the")
    print("annotation. This process will only take a few minutes.")
    print("")
    print("If you don't yet know the answer to any of these questions you can leave")
    print("the answer blank and edit your .yaml file later to fill in these details.")

    print("")
    print("First, some preliminary questions about how you want the server setup:")

    config = get_initial_config()

    # Get task name from user
    config["annotation_task_name"] = input(
        "What is the name for your annotation task" + " that will be shown to users?\n"
    )

    # Get server port with validation
    while True:
        port = input("What port do you want the server to run on? ")
        try:
            port = int(port)
            if port > 1 and port < 16000:
                config["port"] = port
                break
        except ValueError:
            print("%s needs to be a valid numeric port number")

    # Collect data files
    data_files = []
    fname = input("What is the absolute path to one of your data files? ")
    data_files.append(fname)

    # Let the user enter more files
    while yes_or_no("Do you have more data files?"):
        fname = input("What is the absolute path to another data files? ")
        data_files.append(fname)
    config["data_files"] = data_files

    # Get data file structure information
    id_key = input("Which field/column in the data file is the item's ID? ")
    text_key = input("Which field/column in the data file is the item's text? ")
    context_key = input(
        "(optional) Which field/column in the data file is the item's additional context? "
    )

    # Set up item properties configuration
    ip = {"id_key": id_key, "text_key": text_key}
    if len(context_key) > 0:
        ip["contex_key"] = context_key

    config["item_properties"] = ip

    # Get additional configuration details
    config["annotation_codebook_url"] = input("What is the URL for the annotation codebook? ")

    config["output_annotation_dir"] = input(
        "What is the absolute path for the directory "
        + "where the annotations should be written?\n"
    )

    config["output_annotation_format"] = input(
        "What format do you want the annotations written in?\n"
        + "Options: csv, tsv, json, jsonl\n\n"
    )

    print("\nNow we're going to ask about the specific ways you want the data annotated")

    # Collect annotation schemes
    annotation_schemes = []
    while True:

        scheme = {}

        # Get annotation type and basic information
        atype = get_annotation_type()

        desc = input("What description/question/instructions should annotators see for this?\n")
        name = input("What is the internal name for this category (used in output files)?\n")

        # Handle different annotation types
        if atype == "likert" or atype == "bws":
            min_label = ""
            max_label = ""

            if atype == "likert":
                size = input("How many items are on the likert scale?\n")
            else:
                size = input("How many items to display at once for Best-Worst Scaling?\n")

            scheme["min_label"] = min_label
            scheme["max_label"] = max_label
            scheme["size"] = size

        elif atype == "text":
            scheme["annotation_type"] = "text"
            scheme["name"] = name
            scheme["description"] = desc

        elif atype == "mutliselect" or atype == "radio":
            # Get the options for multiselect/radio annotations
            labels = []
            label = input(
                "Enter the text for one option (or press enter with no input when done): "
            )
            while label != "":
                labels.append(label)
                label = input(
                    "Enter the text for one option (or press enter with no input when done): "
                )

            scheme["labels"] = labels

        annotation_schemes.append(scheme)

        if not yes_or_no("Are there more annotation types/tasks to add?"):
            break

    config["annotation_schemes"] = annotation_schemes

    # Save the configuration file
    while True:
        config_file = input(
            "What is the absolute path for where this config.yaml file should be written?\n"
        )

        if os.path.exists(config_file):
            if not yes_or_no("Config file already exists. Overwrite?"):
                continue

        with open(config_file, "wt") as f:
            json.dump(config, f, indent=4)
        break

import json
from collections import OrderedDict
import os


def yes_or_no(question):
    while "the answer is invalid":
        reply = input(question + " (y/n): ").lower().strip()
        if reply[:1] == "y":
            return True
        if reply[:1] == "n":
            return False


def get_annotation_type():
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
    config = OrderedDict()

    config["server_name"] = "potato annotator"

    config["user_config"] = {"allow_all_users": True, "users": []}

    config["alert_time_each_instance"] = 10000000

    # The html that changes the visualiztation for your task. Change this file
    # to influence the layout and description of your task. This is not a full
    # HTML page, just the piece that does lays out your task's pieces
    config["html_layout"] = "templates/examples/plain_layout.html"

    # The core UI files for Potato. You should not need to change these normally.
    #
    # Exceptions to this might include:
    # 1) You want to add custom CSS/fonts to style your task
    # 2) Your layout requires additional JS/assets to render
    # 3) You want to support additional keybinding magic
    #
    config["base_html_template"] = "templates/base_template.html"
    config["header_file"] = "templates/header.html"

    # This is where the actual HTML files will be generated
    config["site_dir"] = "potato/templates/"

    return config


def create_task_cli():

    print("Welcome to the Potato annotation task creation process on the command line!")
    print("This process will walk you through a series of questions about your task")
    print("and generate a .yaml file that has the initial configuration for your")
    print("task. You can edit this .yaml file at any time after the process to tweak")
    print("the intructions, add fancier features, or even change the nature of the")
    print("annotation. This process will only take a few minutes.")
    print("")
    print("If you don't yet know the answer to any of these questions you can leave")
    print("the answer blank and edit your .yaml file later to fill in these details.")

    print("")
    print("First, some preliminary questions about how you want the server setup:")

    config = get_initial_config()

    config["annotation_task_name"] = input(
        "What is the name for your annotation task" + " that will be shown to users?\n"
    )

    while True:
        port = input("What port do you want the server to run on? ")
        try:
            port = int(port)
            if port > 1 and port < 16000:
                config["port"] = port
                break
        except ValueError:
            print("%s needs to be a valid numeric port number")

    data_files = []
    fname = input("What is the absolute path to one of your data files? ")
    data_files.append(fname)

    # Let the user entire more files
    while yes_or_no("Do you have more data files?"):
        fname = input("What is the absolute path to another data files? ")
        data_files.append(fname)
    config["data_files"] = data_files

    id_key = input("Which field/column in the data file is the item's ID? ")
    text_key = input("Which field/column in the data file is the item's text? ")
    context_key = input(
        "(optional) Which field/column in the data file is the item's additional context? "
    )

    ip = {"id_key": id_key, "text_key": text_key}
    if len(context_key) > 0:
        ip["contex_key"] = context_key

    config["item_properties"] = ip

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

    annotation_schemes = []
    while True:

        scheme = {}

        atype = get_annotation_type()

        desc = input("What description/question/instructions should annotators see for this?\n")
        name = input("What is the internal name for this category (used in output files)?\n")

        if atype == "likert" or atype == "bws":
            min_label = ""
            max_label = ""

            if atype == "likert":
                size = input("How many items are on the likert scale?\n")
            else:
                size = input("How many items to dislay at once for Best-Worst Scaling?\n")

            scheme["min_label"] = min_label
            scheme["max_label"] = max_label
            scheme["size"] = size

        elif atype == "text":
            pass

        elif atype == "mutliselect" or atype == "radio":
            # Get the options
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

    config["annoation_schemes"] = annotation_schemes

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

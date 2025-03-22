"""
Flask Server Driver

This module provides the main Flask server implementation for the annotation platform.
Features include:
- User authentication and session management
- Annotation state tracking
- Multi-phase annotation workflow
- Survey flow support
- Data loading and persistence
- AI augmentation support
"""
from __future__ import annotations

import logging
import os
import sys
import random
import json
from collections import deque, defaultdict, Counter, OrderedDict
from itertools import zip_longest
import string
import threading
import yaml

import numpy as np
import pandas as pd
from tqdm import tqdm
from sklearn.pipeline import Pipeline
import simpledorff
from simpledorff.metrics import nominal_metric, interval_metric

import flask
from flask import Flask, session, render_template, request, redirect, url_for, jsonify, make_response
from bs4 import BeautifulSoup
import shutil
from datetime import timedelta

from dataclasses import dataclass

cur_working_dir = os.getcwd() #get the current working dir
cur_program_dir = os.path.dirname(os.path.abspath(__file__)) #get the current program dir (for the case of pypi, it will be the path where potato is installed)
flask_templates_dir = os.path.join(cur_program_dir,'templates') #get the dir where the flask templates are saved
base_html_dir = os.path.join(cur_program_dir,'base_htmls') #get the dir where the the base_html templates files are saved

#insert the current program dir into sys path
sys.path.insert(0, cur_program_dir)

from item_state_management import ItemStateManager, Item, Label, SpanAnnotation
from item_state_management import get_item_state_manager, init_item_state_manager
from user_state_management import UserStateManager, UserState, get_user_state_manager, init_user_state_manager
from authentificaton import UserAuthenticator
from phase import UserPhase

from create_task_cli import create_task_cli, yes_or_no
from server_utils.arg_utils import arguments
from server_utils.config_module import init_config, config
from server_utils.front_end import generate_annotation_html_template, generate_html_from_schematic
from server_utils.schemas.span import render_span_annotations
from server_utils.cli_utlis import get_project_from_hub, show_project_hub
from server_utils.prolific_apis import ProlificStudy
from server_utils.json import easy_json

# This allows us to create an AI endpoint for the system to interact with as needed (if configured)
from ai.ai_endpoint import get_ai_endpoint

app = Flask(__name__)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

random.seed(0)

domain_file_path = ""
file_list = []
file_list_size = 0
default_port = 8000
user_dict = {}

file_to_read_from = ""

user_story_pos = defaultdict(lambda: 0, dict())
user_response_dicts_queue = defaultdict(deque)

# A global mapping from username to the annotator's
#user_to_annotation_state = {}
#user_state_manager = None

# A global mapping from an instance's id to its data. This is filled by
# load_all_data()
#instance_id_to_data = {}
#item_state_manager = None

# A global dict to keep tracking of the task assignment status
#task_assignment = {}

# path to save user information
USER_CONFIG_PATH = "user_config.json"
DEFAULT_LABELS_PER_INSTANCE = 3

# This variable of tyep ActiveLearningState keeps track of information on active
# learning, such as which instances were sampled according to each strategy
#active_learning_state = None

# Hacky nonsense
schema_label_to_color = {}

# Keyword Highlights File Data
@dataclass(frozen=True)
class HighlightSchema:
    label: str
    schema: str

    def __hash__(self):
        return hash((self.label, self.schema))

emphasis_corpus_to_schemas = defaultdict(set)

# Response Highlight Class
@dataclass(frozen=True)
class SuggestedResponse:
    name: str
    label: str

    def __hash__(self):
        return hash((self.name, self.label))

COLOR_PALETTE = [
    "rgb(179,226,205)",
    "rgb(253,205,172)",
    "rgb(203,213,232)",
    "rgb(244,202,228)",
    "rgb(230,245,201)",
    "rgb(255,242,174)",
    "rgb(241,226,204)",
    "rgb(204,204,204)",
    "rgb(102, 197, 204)",
    "rgb(246, 207, 113)",
    "rgb(248, 156, 116)",
    "rgb(220, 176, 242)",
    "rgb(135, 197, 95)",
    "rgb(158, 185, 243)",
    "rgb(254, 136, 177)",
    "rgb(201, 219, 116)",
    "rgb(139, 224, 164)",
    "rgb(180, 151, 231)",
    "rgb(179, 179, 179)",
]

# Mapping the base html template str to the real file
template_dict = {
    "base_html_template":{
        'base': os.path.join(cur_program_dir, 'base_html/base_template.html'),
        'default': os.path.join(cur_program_dir, 'base_html/base_template.html'),
    },
    "header_file":{
        'default': os.path.join(cur_program_dir, 'base_html/header.html'),
    },
    "html_layout":{
        'default': os.path.join(cur_program_dir, 'base_html/examples/plain_layout.html'),
        'plain': os.path.join(cur_program_dir, 'base_html/examples/plain_layout.html'),
        'kwargs': os.path.join(cur_program_dir, 'base_html/examples/kwargs_example.html'),
        'fixed_keybinding': os.path.join(cur_program_dir, 'base_html/examples/fixed_keybinding_layout.html')
    },
    "surveyflow_html_layout": {
        'default': os.path.join(cur_program_dir, 'base_html/examples/plain_layout.html'),
        'plain': os.path.join(cur_program_dir, 'base_html/examples/plain_layout.html'),
        'kwargs': os.path.join(cur_program_dir, 'base_html/examples/kwargs_example.html'),
        'fixed_keybinding': os.path.join(cur_program_dir, 'base_html/examples/fixed_keybinding_layout.html')
    }
}

class ActiveLearningState:
    """
    A class for maintaining state on active learning.
    """

    def __init__(self):
        self.id_to_selection_type = {}
        self.id_to_update_round = {}
        self.cur_round = 0

    def update_selection_types(self, id_to_selection_type):
        self.cur_round += 1

        for iid, st in id_to_selection_type.items():
            self.id_to_selection_type[iid] = st
            self.id_to_update_round[iid] = self.cur_round

def load_instance_data(config: dict):
    '''Loads the instance data from the files specified in the config.'''

    ism = get_item_state_manager()

    # Where to look in the JSON item object for the text to annotate
    text_key = config["item_properties"]["text_key"]
    id_key = config["item_properties"]["id_key"]

    data_files = config["data_files"]
    logger.debug("Loading data from %d files" % (len(data_files)))

    for data_fname in data_files:
        fmt = data_fname.split(".")[-1]
        if fmt not in ["csv", "tsv", "json", "jsonl"]:
            raise Exception("Unsupported input file format %s for %s" % (fmt, data_fname))

        logger.debug("Reading data from " + data_fname)

        if fmt in ["json", "jsonl"]:
            with open(data_fname, "rt") as f:
                for line_no, line in enumerate(f):
                    item = json.loads(line)

                    # Validate that the ID key exists in the item
                    if id_key not in item:
                        raise KeyError(f"ID key '{id_key}' not found in item at line {line_no+1}")

                    instance_id = str(item[id_key]) # Ensure ID is string

                    # Check for duplicate IDs
                    if ism.has_item(instance_id):
                        raise ValueError(f"Duplicate instance ID '{instance_id}' found at line {line_no+1}")

                    # Validate text key exists if required
                    if text_key not in item:
                        logger.warning(f"Text key '{text_key}' not found in item with ID '{instance_id}'")

                    ism.add_item(instance_id, item)
        else:
            sep = "," if fmt == "csv" else "\t"

            # Validate required columns exist
            df = pd.read_csv(data_fname, sep=sep)
            if id_key not in df.columns:
                raise KeyError(f"ID column '{id_key}' not found in file {data_fname}")
            if text_key not in df.columns:
                logger.warning(f"Text column '{text_key}' not found in file {data_fname}")

            # Convert ID column to string to ensure consistent typing
            df[id_key] = df[id_key].astype(str)

            # Check for duplicate IDs in the dataframe
            if df[id_key].duplicated().any():
                dupes = df[id_key][df[id_key].duplicated()].tolist()
                raise ValueError(f"Duplicate instance IDs found in {data_fname}: {dupes}")

            # Check for duplicate IDs with existing items
            existing_dupes = [id for id in df[id_key] if ism.has_item(id)]
            if existing_dupes:
                raise ValueError(f"Instance IDs in {data_fname} conflict with existing IDs: {existing_dupes}")

            # Load data with proper type conversion
            df = df.astype({id_key: str})
            if text_key in df.columns:
                df = df.astype({text_key: str})

            # Add items to state manager
            for _, row in df.iterrows():
                item = row.to_dict()
                instance_id = item[id_key]
                ism.add_item(instance_id, item)

            line_no = len(df)

        # If the admin didn't specify a subset, have the user annotate all instances
        max_annotations_per_user = config.get("max_annotations_per_user", len(ism.get_instance_ids()))
        get_user_state_manager().set_max_annotations_per_user(max_annotations_per_user)

        logger.debug("Loaded %d instances from %s" % (line_no, data_fname))

    # For each item, render the text to display in the UI ahead of time.
    for item in get_item_state_manager().items():
        item_data = item.get_data()

        # Validate text key exists before rendering
        if text_key in item_data:
            item_data["displayed_text"] = get_displayed_text(item_data[text_key])
        else:
            item_data["displayed_text"] = ""
            logger.warning(f"No text found for item {item.get_id()}, using empty string")

def load_user_data(config: dict):

    user_data_dir = config['output_annotation_dir']
    usm = get_user_state_manager()

    # For each user's directory, load in their state
    for user_dir in os.listdir(user_data_dir):
        usm.load_user_state(os.path.join(user_data_dir, user_dir))

    logger.info("Loaded user data for %d users" % len(usm.get_user_ids()))

def load_all_data(config: dict):
    '''Loads instance and annotation data from the files specified in the config.'''
    global item_state_manager
    global user_state_manager

    # Hacky nonsense
    global emphasis_corpus_to_schemas

    load_annotation_schematic_data(config)
    load_instance_data(config)
    load_user_data(config)
    load_phase_data(config)
    load_highlights_data(config)

    print("STATES: ", get_user_state_manager().phase_type_to_name_to_page)

def load_annotation_schematic_data(config: dict) -> None:

    # Swap in the right file paths if the user specified the default templates
    if config["base_html_template"] == "default":
        config["base_html_template"] = template_dict["base_html_template"]["default"]
    if config["header_file"] == "default":
        config["header_file"] = template_dict["header_file"]["default"]
    if config["html_layout"] == "default":
        config["html_layout"] = template_dict["html_layout"]["default"]

    task_dir = config["task_dir"]
    # Swap in the right file paths if the user specified the default templates
    if config["site_dir"] == "default" or True:
        templates_dir = os.path.join(cur_program_dir, 'templates')
        if not os.path.exists(templates_dir):
            # make the directory
            os.makedirs(templates_dir)
        config["site_dir"] = templates_dir


    # Creates the templates we'll use in flask by mashing annotation
    # specification on top of the proto-templates
    html_template_fname = generate_annotation_html_template(config)

    # Register that we have an annotation phase. Theoretically, we always
    # should have this, but perhaps there will be some future case where
    # annotation is not the primary task.
    #
    # NOTE: We don't have any HTML for this yet...
    usm = get_user_state_manager()
    usm.add_phase(UserPhase.ANNOTATION, config['annotation_task_name'],
                  html_template_fname)

def load_highlights_data(config: dict) -> None:
    pass

def load_phase_data(config: dict) -> None:
    global logger

    if "phases" not in config or not config["phases"]:
        return

    phases = config["phases"]
    if "order" in phases:
        phase_order = phases["order"]
    else:
        phase_order = list(phases.keys())

    logger.debug("Loading %d phases in order: %s" % (len(phase_order), phase_order))

    # TODO: add some logging if "order" was specified with fewer phases than are defined
    # TODO: add some validation logic to ensure that
    #         1) all phase names have a definition in the config
    #         2) all names are unique (no repeats)
    #         3) all names are strings
    #         4) all names are non-empty
    #         5) all types are recognized and valid



    for phase_name in phase_order:
        phase = phases[phase_name]
        if not "type" in phase or not phase['type']:
            raise Exception("Phase %s does not have a type" % phase_name)
        if not "file" in phase or not phase['file']:
            raise Exception("Phase %s is specified but does not have a file" % phase_name)

        # Get the phase labeling schemes, being robust to relative or absolute paths
        phase_scheme_fname = get_abs_or_rel_path(phase['file'], config)
        phase_labeling_schemes = get_phase_annotation_schemes(phase_scheme_fname)

        # Use the default templates unless specified in the phase config
        html_template_filename = config["base_html_template"]
        if 'template' in phase:
            html_template_filename = phase['template']
        html_header_filename = config["header_file"]
        if 'header' in phase:
            html_header_filename = phase['header']
        html_layout_filename = config["html_layout"]
        if 'layout' in phase:
            html_layout_filename = phase['layout']

        try:
            phase_html_fname = generate_html_from_schematic(html_template_filename,
                                            html_header_filename,
                                            html_layout_filename,
                                            phase_labeling_schemes,
                                            False, False,
                                            phase_name, config)
        except KeyError as e:
            raise Exception("Error generating HTML for phase %s (file: %s): %s" \
                            % (phase_name, phase['file'], str(e)))

        phase_type = UserPhase.fromstr(phase['type'])

        # Register the HTML so it's easy to find later
        # config['phase'][phase['type']]['pages'].append(phase_html_fname)
        # Add the phase to the user state manager
        user_state_manager.add_phase(phase_type, phase_name, phase_html_fname)

        match phase['type']:
            case "consent":
                consent_fname = None
            case "instructions":
                instructions_fname = phase_html_fname
            case "prestudy":
                prestudy_fname = phase_html_fname
            case "training":
                training_fname = phase_html_fname
            case "poststudy":
                poststudy_fname = phase_html_fname
            case _:
                raise Exception("Unknown phase type %s specified for %s" \
                                 % (phase_name, phase['type']))


def get_phase_annotation_schemes(filename: str) -> list[dict]:
    '''Returns the annotation schemes for a phase from a file.'''

    schemes = []
    if not os.path.exists(filename):
        raise Exception("Phase labeling schemes file %s does not exist" % filename)

    if filename.endswith(".json"):
        with open(filename, "rt") as f:
            schemes = json.load(f)
        # Allow users to have specified a single scheme in the JSON file
        if type(schemes) != list:
            schemes = [schemes]
    elif filename.endswith(".jsonl"):
        with open(filename, 'rt') as f:
            for line in f:
                schemes.append(json.loads(line))
    elif filename.endswith(".yaml") or filename.endswith(".yml"):
        with open(filename, 'rt') as f:
            schemes = yaml.safe_load(f)
    else:
        raise Exception("Unknown file format for phase labeling schemes file %s" % filename)
    return schemes

def get_abs_or_rel_path(fname: str, config: dict) -> str:
    """
    Returns the path to the fname if it exists as specified, or if not, attempts to find
    the file in the relative paths from the config file.
    """

    if os.path.exists(fname):
        return fname

    # See if we can find the file in the same directory as the config file
    dname = os.path.dirname(config["__config_file__"])
    rel_path = os.path.join(dname, fname)
    if os.path.exists(rel_path):
        return rel_path

    # See if we can locate the file in the current working directory
    cwd = os.getcwd()
    rel_path = os.path.join(cwd, fname)
    if os.path.exists(rel_path):
        return rel_path

    # See if we can figure it out from the real path directory
    real_path = os.path.abspath(dname)
    dir_path = os.path.dirname(real_path)
    fname = os.path.join(dir_path, fname)

    if not os.path.exists(fname):
        raise FileNotFoundError("File not found: %s" % fname)
    return fname


def load_all_data_old(config) -> None:
    global item_state_manager
    global task_assignment

    # Hacky nonsense
    global emphasis_corpus_to_schemas

    # Where to look in the JSON item object for the text to annotate
    text_key = config["item_properties"]["text_key"]
    id_key = config["item_properties"]["id_key"]

    # Keep the data in the same order we read it in
    instance_id_to_data = OrderedDict()

    data_files = config["data_files"]
    logger.debug("Loading data from %d files" % (len(data_files)))

    for data_fname in data_files:

        fmt = data_fname.split(".")[-1]
        if fmt not in ["csv", "tsv", "json", "jsonl"]:
            raise Exception("Unsupported input file format %s for %s" % (fmt, data_fname))

        logger.debug("Reading data from " + data_fname)

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
            df = pd.read_csv(data_fname, sep=sep, dtype={id_key: str, text_key: str})
            for _, row in df.iterrows():

                item = {}
                for c in df.columns:
                    item[c] = row[c]
                instance_id = row[id_key]

                # TODO: check for duplicate instance_id
                instance_id_to_data[instance_id] = item
            line_no = len(df)

        logger.debug("Loaded %d instances from %s" % (line_no, data_fname))

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
                            "text": line["text"].replace("[test_question_choice]", l),
                        }
                        # currently we simply move all these test questions to the end of the instance list
                        instance_id_to_data.update({item["id"]: item})
                        instance_id_to_data.move_to_end(item["id"], last=True)

    # insert survey questions into instance_id_to_data
    for page in config.get("pre_annotation_pages", []):
        # TODO Currently we simply remove the language type before -,
        # but we need a more elegant way for this in the future
        item = {"id": page['id'], "text": page['text'] if 'text' in page else page['id'].split("-")[-1][:-5]}
        instance_id_to_data.update({page['id']: item})
        instance_id_to_data.move_to_end(page['id'], last=False)

    for it in ["prestudy_failed_pages", "prestudy_passed_pages"]:
        for page in config.get(it, []):
            # TODO Currently we simply remove the language type before -,
            # but we need a more elegant way for this in the future
            item = {"id": page['id'], "text": page['text'] if 'text' in page else page['id'].split("-")[-1][:-5]}
            instance_id_to_data.update({page['id']: item})
            instance_id_to_data.move_to_end(page['id'], last=False)

    for page in config.get("post_annotation_pages", []):
        item = {"id": page['id'], "text": page['text'] if 'text' in page else page['id'].split("-")[-1][:-5]}
        instance_id_to_data.update({page['id']: item})
        instance_id_to_data.move_to_end(page['id'], last=True)

    # Generate the text to display in instance_id_to_data
    for inst_id in instance_id_to_data:
        instance_id_to_data[inst_id]["displayed_text"] = get_displayed_text(
            instance_id_to_data[inst_id][config["item_properties"]["text_key"]]
        )

    # TODO: make this fully configurable somehow...
    if "keyword_highlights_file" in config:
        kh_file = config["keyword_highlights_file"]
        logger.debug("Loading keyword highlighting from %s" % (kh_file))

        with open(kh_file, "rt") as f:
            # TODO: make it flexible based on keyword
            df = pd.read_csv(kh_file, sep="\t")
            for i, row in df.iterrows():
                emphasis_corpus_to_schemas[row["Word"]].add(
                    HighlightSchema(row["Schema"], row["Label"])
                )

        logger.debug(
            "Loaded %d regexes to map to %d labels for dynamic highlighting"
            % (len(emphasis_corpus_to_schemas), i)
        )

    # Load the annotation assignment info if automatic task assignment is on.
    # Jiaxin: we are simply saving this as a json file at this moment
    if "automatic_assignment" in config and config["automatic_assignment"]["on"]:

        # path to save task assignment information
        task_assignment_path = os.path.join(
            config["output_annotation_dir"], config["automatic_assignment"]["output_filename"]
        )

        if os.path.exists(task_assignment_path):
            # load the task assignment if it has been generated and saved
            with open(task_assignment_path, "r") as r:
                task_assignment = json.load(r)
        else:
            # Otherwise generate a new task assignment dict
            task_assignment = {
                "assigned": {},
                "unassigned": OrderedDict(), #use ordered dict so that we can keep track of the original order
                "testing": {"test_question_per_annotator": 0, "ids": []},
                "prestudy_ids": [],
                "prestudy_passed_users": [],
                "prestudy_failed_users": [],
            }
            # Setting test_question_per_annotator if it is defined in automatic_assignment,
            # otherwise it is default to 0 and no test question will be used
            if "test_question_per_annotator" in config["automatic_assignment"]:
                task_assignment["testing"]["test_question_per_annotator"] = config[
                    "automatic_assignment"
                ]["test_question_per_annotator"]

            for it in ["pre_annotation", "prestudy_passed", "prestudy_failed", "post_annotation"]:
                if it + "_pages" in config:
                    task_assignment[it + "_pages"] = [p['id'] if type(p) == dict else p for p in config[it + "_pages"]]
                    for p in config[it + "_pages"]:
                        task_assignment["assigned"][p['id']] = 0

            for _id in instance_id_to_data:
                if _id in task_assignment["assigned"]:
                    continue
                # add test questions to the assignment dict
                if re.search("testing", _id):
                    task_assignment["testing"]["ids"].append(_id)
                    continue
                if re.search("prestudy", _id):
                    task_assignment["prestudy_ids"].append(_id)
                    continue
                # set the total labels per instance, if not specified, default to 3
                task_assignment["unassigned"][_id] = (
                    config["automatic_assignment"]["labels_per_instance"]
                    if "labels_per_instance" in config["automatic_assignment"]
                    else DEFAULT_LABELS_PER_INSTANCE
                )


def convert_labels(annotation, schema_type):
    if schema_type == "likert":
        return int(list(annotation.keys())[0][6:])
    if schema_type == "radio":
        return list(annotation.keys())[0]
    if schema_type == "multiselect":
        return list(annotation.keys())
    if schema_type == 'number':
        return float(annotation['text_box'])
    if schema_type == 'textbox':
        return annotation['text_box']
    print("Unrecognized schema_type %s" % schema_type)
    return None


def get_agreement_score(user_list, schema_name, return_type="overall_average"):
    """
    Get the final agreement score for selected users and schemas.
    """
    global user_state_manager

    if user_list == "all":
        user_list = user_state_manager.get_user_ids()

    name2alpha = {}
    if schema_name == "all":
        for i in range(len(config["annotation_schemes"])):
            schema = config["annotation_schemes"][i]
            alpha = cal_agreement(user_list, schema["name"])
            name2alpha[schema["name"]] = alpha

    alpha_list = []
    if return_type == "overall_average":
        for name in name2alpha:
            alpha = name2alpha[name]
            if isinstance(alpha, dict):
                average_alpha = sum([it[1] for it in list(alpha.items())]) / len(alpha)
                alpha_list.append(average_alpha)
            elif isinstance(alpha, (np.floating, float)):
                alpha_list.append(alpha)
            else:
                continue
        if len(alpha_list) > 0:
            return round(sum(alpha_list) / len(alpha_list), 2)
        return "N/A"

    return name2alpha


def cal_agreement(user_list, schema_name, schema_type=None, selected_keys=None):
    """
    Calculate the krippendorff's alpha for selected users and schema.
    """
    global user_to_annotation_state

    # get the schema_type/annotation_type from the config file
    for i in range(len(config["annotation_schemes"])):
        schema = config["annotation_schemes"][i]
        if schema["name"] == schema_name:
            schema_type = schema["annotation_type"]
            break

    # obtain the list of keys for calculating IAA and the user annotations
    union_keys = set()
    user_annotation_list = []
    for user in user_list:
        if user not in user_to_annotation_state:
            print("%s not found in user_to_annotation_state" % user)
        user_annotated_ids = user_to_annotation_state[user].instance_id_to_labeling.keys()
        union_keys = union_keys | user_annotated_ids
        user_annotation_list.append(user_to_annotation_state[user].instance_id_to_labeling)

    if len(user_annotation_list) < 2:
        print("Cannot calculate agreement score for less than 2 users")
        return None

    # only calculate the agreement for selected keys when selected_keys is specified
    if selected_keys is None:
        selected_keys = list(union_keys)

    if len(selected_keys) == 0:
        print(
            "Cannot calculate agreement score when annotators work on different sets of instances"
        )
        return None

    if schema_type in ["radio", "likert"]:
        distance_metric_dict = {"radio": nominal_metric, "likert": interval_metric}
        # initialize agreement data matrix
        l = []
        for _ in range(len(user_annotation_list)):
            l.append([np.nan] * len(selected_keys))

        for i, _selected_key in enumerate(selected_keys):
            for j in range(len(l)):
                if _selected_key in user_annotation_list[j]:
                    l[j][i] = convert_labels(
                        user_annotation_list[j][_selected_key][schema_name], schema_type
                    )
        alpha = simpledorff.calculate_krippendorffs_alpha(pd.DataFrame(np.array(l)),metric_fn=distance_metric_dict[schema_type])

        return alpha

    # When multiple labels are annotated for each instance, calculate the IAA for each label
    if schema_type == "multiselect":
        # collect the label list from configuration file
        if isinstance(schema["labels"][0], dict):
            labels = [it["name"] for it in schema["labels"]]
        elif isinstance(schema["labels"][0], str):
            labels = schema["labels"]
        else:
            print("Unknown label type in schema['labels']")
            return None

        # initialize agreement data matrix for each label
        l_dict = {}
        for l in labels:
            l_dict[l] = []
            for i in range(len(user_annotation_list)):
                l_dict[l].append([np.nan] * len(selected_keys))

        # consider binary agreement for each label in the multi-label schema
        for i, _selected_key in enumerate(selected_keys):
            for j in range(len(user_annotation_list)):
                if (_selected_key in user_annotation_list[j]) and (
                    schema_name in user_annotation_list[j][_selected_key]
                ):
                    annotations = convert_labels(
                        user_annotation_list[j][_selected_key][schema_name], schema_type
                    )
                    for l in labels:
                        l_dict[l][j][i] = 1
                        if l not in annotations:
                            l_dict[l][j][i] = 0

        alpha_dict = {}
        for key in labels:
            alpha_dict[key] = simpledorff.calculate_krippendorffs_alpha(pd.DataFrame(np.array(l_dict[key])),metric_fn=nominal_metric)
        return alpha_dict


def cal_amount(user):
    count = 0
    lines = user_dict[user]["user_data"]
    for key in lines:
        if lines[key]["annotated"]:
            count += 1
    return count


def find_start_id(user):
    """
    path = user_dict[user]["path"]
    # if not os.path.exists(path):
    user_data = {}
    user_dict[user]["start_id"] = len(all_data["annotated_data"])
    lines = user_dict[user]["user_data"]
    for i in range(len(lines), 0):
        line = lines[str(i)]
        if not line["annotated"]:
            user_dict[user]["start_id"] = line["id"]
            return line["id"]
    # user_dict[user]['user_data'] = user_data
    """
    raise RuntimeError("This function is deprecated?")


def move_to_prev_instance(user_id) -> bool:
    '''Moves the user back to the previous instance and returns True if successful'''
    user_state = get_user_state(user_id)
    return user_state.go_back()


def move_to_next_instance(user_id) -> bool:
    '''Moves the user forward to the next instance and returns True if successful'''
    user_state = get_user_state(user_id)

    # If the user is at the end of the list, try to assign instances to the user
    if user_state.is_at_end_index():
        logger.debug(f"User {user_id} is at the end of the list, assigning new instances")
        num_assigned = get_item_state_manager().assign_instances_to_user(user_state)
        logger.debug(f"Assigned {num_assigned} new instances to user {user_id}")

    return user_state.go_forward()


def go_to_id(user_id: str, instance_index: int):
    '''Causes the user's view to change to the Item at the given index.'''
    user_state = get_user_state(user_id)
    user_state.go_to_index(int(instance_index))


def get_total_annotations():
    """
    Returns the total number of unique annotations done across all users.
    """
    total = 0
    for username in get_users():
        user_state = get_user_state(username)
        total += user_state.get_annotation_count()

    return total


def update_annotation_state(username, form):
    """
    Parses the state of the HTML form (what the user did to the instance) and
    updates the state of the instance's annotations accordingly.
    """

    # Get what the user has already annotated, which might include this instance too
    user_state = get_user_state(username)

    # Jiaxin: the instance_id are changed to the user's local instance cursor
    instance_id = user_state.get_current_instance_id()

    schema_to_label_to_value = defaultdict(dict)

    behavioral_data_dict = {}

    did_change = False
    for key in form:

        # look for behavioral information regarding time, click, ...
        if key[:9] == "behavior_":
            behavioral_data_dict[key[9:]] = form[key]
            continue

        # Look for the marker that indicates an annotation label.
        #
        # NOTE: The span annotation uses radio buttons as well to figure out
        # which label. These inputs are labeled with "span_label" so we can skip
        # them as being actual annotatins (the spans are saved below though).
        if ":::" in key and "span_label" not in key:

            cols = key.split(":::")
            annotation_schema = cols[0]
            annotation_label = cols[1]
            annotation_value = form[key]

            # skip the input when it is an empty string (from a text-box)
            if annotation_value == "":
                continue

            schema_to_label_to_value[annotation_schema][annotation_label] = annotation_value


    # Span annotations are a bit funkier since we're getting raw HTML that
    # we need to post-process on the server side.
    span_annotations = []
    if "span-annotation" in form:
        span_annotation_html = form["span-annotation"]
        span_text, span_annotations = parse_html_span_annotation(span_annotation_html)

    did_change = user_state.set_annotation(
        instance_id, schema_to_label_to_value, span_annotations, behavioral_data_dict
    )

    # update the behavioral information regarding time only when the annotations are changed
    if did_change:
        user_state.instance_id_to_behavioral_data[instance_id] = behavioral_data_dict
    return did_change


def get_annotations_for_user_on(username, instance_id):
    """
    Returns the label-based annotations made by this user on the instance.
    """
    user_state = get_user_state(username)
    print("instance_id", instance_id)
    annotations = user_state.get_label_annotations(instance_id)
    return annotations


def get_span_annotations_for_user_on(username, instance_id):
    """
    Returns the span annotations made by this user on the instance.
    """
    user_state = get_user_state(username)
    span_annotations = user_state.get_span_annotations(instance_id)
    return span_annotations

def old_home():
    global user_config

    if config["__debug__"]:
        print("debug user logging in")
        return annotate_page("debug_user", action="home")
    if "login" in config:

        try:
            if config["login"]["type"] == "url_direct":
                url_arguments = (
                    config["login"]["url_argument"] if "url_argument" in config["login"] else "username"
                )
                if type(url_arguments) == str:
                    url_arguments = [url_arguments]
                username = '&'.join([request.args.get(it) for it in url_arguments])
                print("url direct logging in with %s=%s" % ('&'.join(url_arguments),username))
                return annotate_page(username, action="home")
            elif config["login"]["type"] == "prolific":
                #we force the order of the url_arguments for prolific logins, so that we can easily retrieve
                #the session and study information
                #url_arguments = ['PROLIFIC_PID','STUDY_ID', 'SESSION_ID']

                #Currently we still only use PROLIFIC_PID as the username, however, in the longer term, we might switch to
                # a combination of PROLIFIC_PID and SESSION id
                url_arguments = ['PROLIFIC_PID']
                username = '&'.join([request.args.get(it) for it in url_arguments])
                print("prolific logging in with %s=%s" % ('&'.join(url_arguments),username))

                # check if the provided study id is the same as the study id defined in prolific configuration file, if not,
                # pause the studies and terminate the program
                if request.args.get('STUDY_ID') != prolific_study.study_id:
                    print('ERROR: Study id (%s) does not match the study id in %s (%s), trying to pause the prolific study, \
                          please check if study id is defined correctly on the server or if the study link if provided correctly \
                          on prolific'%(request.args.get('STUDY_ID'),
                         config['prolific']['config_file_path'], prolific_study.study_id))
                    prolific_study.pause_study(study_id=request.args.get('STUDY_ID'))
                    prolific_study.pause_study(study_id=prolific_study.study_id)
                    quit()

                return annotate_page(username, action="home")
            print("password logging in")
            return render_template("home.html", title=config["annotation_task_name"])

        except:
            return render_template(
                "error.html",
                error_message="Please login to annotate or you are using the wrong link",
            )
    print("password logging in")
    return render_template("home.html", title=config["annotation_task_name"])



@app.route("/", methods=["GET", "POST"])
def home():
    """
    Handle requests to the home page.

    Features:
    - Session management
    - User authentication
    - Phase routing
    - Survey flow management
    - Progress tracking

    Returns:
        flask.Response: Rendered template or redirect based on user state
    """
    logger.debug("Processing home page request")

    if 'username' not in session:
        logger.debug("No active session, rendering login page")
        return redirect(url_for("auth"))

    username = session['username']
    logger.info(f"Active session for user: {username}")

    print("home request.form: ", request.form)
    print("home request.json: ", request.json)
    print('home: request.method: ', request.method)

    user_state = get_user_state(username)
    phase = user_state.get_phase()
    logger.debug(f"User phase: {phase}")

    if phase == UserPhase.LOGIN:
        return redirect(url_for("auth"), code=307)
    elif phase == UserPhase.CONSENT:
        return render_template("consent")
    elif phase == UserPhase.PRESTUDY:
        return redirect(url_for("prestudy"), code=307)
    elif phase == UserPhase.INSTRUCTIONS:
        return redirect(url_for("instructions"), code=307)
    elif phase == UserPhase.TRAINING:
        return redirect(url_for("training"), code=307)
    elif phase == UserPhase.ANNOTATION:
        return redirect(url_for("annotate"), code=307)
    elif phase == UserPhase.POSTSTUDY:
        return redirect(url_for("poststudy"), code=307)
    elif phase == UserPhase.DONE:
        return redirect(url_for("done"))

    logger.error(f"Invalid phase for user {username}: {phase}")
    return render_template("error.html", message="Invalid application state")


@app.route("/auth", methods=["GET", "POST"])
def auth():
    """
    Handle requests to the home page, redirecting to appropriate auth method.

    Returns:
        flask.Response: Rendered template or redirect
    """
    logger.debug("Processing home page request")

    # Check if user is already logged in
    if 'username' in session:
        logger.debug(f"User {session['username']} already logged in, redirecting to annotate")
        return redirect(url_for("annotate"))

    # Get authentication method from config
    auth_method = config.get("authentication", {}).get("method", "in_memory")

    # For Clerk SSO, redirect to clerk login page
    if auth_method == "clerk":
        logger.debug("Using Clerk SSO, redirecting to clerk login")
        return redirect(url_for("clerk_login"))

    # For passwordless login (check if require_password is False)
    if not config.get("require_password", True):
        logger.debug("Passwordless login enabled, redirecting")
        return redirect(url_for("passwordless_login"))

    # For standard username/password login
    if request.method == "POST":
        username = request.form.get("email")
        password = request.form.get("pass")

        logger.debug(f"Login attempt for user: {username}")

        if not username:
            logger.warning("Login attempt with empty username")
            return render_template("home.html",
                                  login_error="Username is required",
                                  title=config.get("annotation_task_name", "Annotation Platform"))

        # Authenticate the user
        if UserAuthenticator.authenticate(username, password):
            session.clear()  # Clear any existing session data
            session['username'] = username
            session.permanent = True  # Make session persist longer
            logger.info(f"Login successful for user: {username}")


            # Initialize user state if needed
            if not get_user_state_manager().has_user(username):
                logger.debug(f"Initializing state for new user: {username}")
                #init_user_state(username)
                usm = get_user_state_manager()
                usm.add_user(username)
                usm.advance_phase(username)
                request.method = 'GET'
                return home()
        else:
            logger.warning(f"Login failed for user: {username}")
            return render_template("home.html",
                                  login_error="Invalid username or password",
                                  login_email=username,
                                  title=config.get("annotation_task_name", "Annotation Platform"))

    # GET request - show the login form
    return render_template("home.html",
                         title=config.get("annotation_task_name", "Annotation Platform"))


@app.route("/passwordless-login", methods=["GET", "POST"])
def passwordless_login():
    """
    Handle passwordless login page requests.

    Returns:
        flask.Response: Rendered template or redirect
    """
    logger.debug("Processing passwordless login page request")

    # Redirect to regular login if passwords are required
    if config.get("require_password", True):
        logger.debug("Passwords required, redirecting to regular login")
        return redirect(url_for("home"))

    # Check if username was submitted via POST
    if request.method == "POST":
        username = request.form.get("email")

        if not username:
            logger.warning("Passwordless login attempt with empty username")
            return render_template("passwordless_login.html",
                                  login_error="Username is required",
                                  title=config.get("annotation_task_name", "Annotation Platform"))

        # Authenticate without password
        if UserAuthenticator.authenticate(username, None):
            session['username'] = username
            logger.info(f"Passwordless login successful for user: {username}")

            # Initialize user state if needed
            if not get_user_state_manager().has_user(username):
                logger.debug(f"Initializing state for new user: {username}")
                init_user_state(username)

            return redirect(url_for("annotate"))
        else:
            logger.warning(f"Passwordless login failed for user: {username}")
            return render_template("passwordless_login.html",
                                  login_error="Invalid username",
                                  login_email=username,
                                  title=config.get("annotation_task_name", "Annotation Platform"))

    # GET request - show the passwordless login form
    return render_template("passwordless_login.html",
                         title=config.get("annotation_task_name", "Annotation Platform"))

@app.route("/clerk-login", methods=["GET", "POST"])
def clerk_login():
    """
    Handle Clerk SSO login process.

    Returns:
        flask.Response: Rendered template or redirect
    """
    logger.debug("Processing Clerk SSO login request")

    # Only proceed if Clerk is configured
    auth_method = config.get("authentication", {}).get("method", "in_memory")
    if auth_method != "clerk":
        logger.warning("Clerk login attempted but not configured")
        return redirect(url_for("home"))

    # Get the Clerk frontend API key
    authenticator = UserAuthenticator.get_instance()
    clerk_frontend_api = authenticator.get_clerk_frontend_api()

    if not clerk_frontend_api:
        logger.error("Clerk frontend API key not configured")
        return render_template("home.html",
                             login_error="SSO configuration error",
                             title=config.get("annotation_task_name", "Annotation Platform"))

    # Handle the Clerk token verification
    if request.method == "POST":
        token = request.form.get("clerk_token")
        username = request.form.get("username")

        if not token or not username:
            logger.warning("Clerk login attempt with missing token or username")
            return render_template("clerk_login.html",
                                 login_error="Missing authentication data",
                                 title=config.get("annotation_task_name", "Annotation Platform"))

        # Authenticate with Clerk
        if UserAuthenticator.authenticate(username, token):
            session['username'] = username
            logger.info(f"Clerk SSO login successful for user: {username}")

            # Initialize user state if needed
            if not get_user_state_manager().has_user(username):
                logger.debug(f"Initializing state for new user: {username}")
                init_user_state(username)

            return redirect(url_for("annotate"))
        else:
            logger.warning(f"Clerk SSO login failed for user: {username}")
            return render_template("clerk_login.html",
                                 login_error="Authentication failed",
                                 title=config.get("annotation_task_name", "Annotation Platform"))

    # GET request - show the Clerk login form
    return render_template("clerk_login.html",
                         clerk_frontend_api=clerk_frontend_api,
                         title=config.get("annotation_task_name", "Annotation Platform"))

@app.route("/login", methods=["GET", "POST"])
def login():
    """
    Handle login requests - now just redirects to home which handles login

    Returns:
        flask.Response: Redirect to home
    """
    logger.debug("Redirecting /login to home")
    return redirect(url_for("home"))

@app.route("/logout")
def logout():
    """
    Handle user logout requests.

    Features:
    - Session cleanup
    - State persistence
    - Progress saving

    Returns:
        flask.Response: Redirect to login page
    """
    logger.debug("Processing logout request")

    if 'username' in session:
        username = session['username']
        logger.info(f"Logging out user: {username}")

        # Save user progress
        user_state = get_user_state(username)
        if user_state:
            user_state.save_progress()
            logger.debug(f"Saved progress for user: {username}")

        session.pop('username', None)

    return redirect(url_for("home"))

@app.route("/submit_annotation", methods=["POST"])
def submit_annotation():
    """
    Handle annotation submission requests.

    Features:
    - Validation checking
    - Progress tracking
    - State updates
    - AI integration
    - Data persistence

    Args (from form):
        annotation_data: JSON-encoded annotation data
        instance_id: ID of annotated instance

    Returns:
        flask.Response: JSON response with submission result
    """
    logger.debug("Processing annotation submission")

    if 'username' not in session:
        logger.warning("Annotation submission without active session")
        return jsonify({"status": "error", "message": "No active session"})

    username = session['username']
    instance_id = request.form.get("instance_id")
    annotation_data = request.form.get("annotation_data")

    logger.debug(f"Annotation from {username} for instance {instance_id}")

    try:
        # Validate annotation data
        annotation = json.loads(annotation_data)
        if not validate_annotation(annotation):
            raise ValueError("Invalid annotation format")

        # Update state
        user_state = get_user_state(username)
        user_state.add_annotation(instance_id, annotation)

        # Process with AI if configured
        if config.get("ai_enabled"):
            ai_endpoint = get_ai_endpoint()
            ai_feedback = ai_endpoint.process_annotation(annotation)
            logger.debug(f"AI feedback received: {ai_feedback}")

        logger.info(f"Successfully saved annotation for {instance_id} from {username}")
        return jsonify({"status": "success"})

    except Exception as e:
        logger.error(f"Failed to save annotation: {e}")
        return jsonify({"status": "error", "message": str(e)})

def get_user_state(username):
    """
    Retrieve or create user state object.

    Args:
        username (str): User identifier

    Returns:
        UserState: User's current state object

    Raises:
        ValueError: If username is invalid
    """
    logger.debug(f"Retrieving state for user: {username}")

    if not username:
        error_msg = "Invalid username"
        logger.error(error_msg)
        raise ValueError(error_msg)

    user_state_manager = get_user_state_manager()
    if not user_state_manager.has_user(username):
        logger.debug(f"Creating new state for user: {username}")
        user_state_manager.create_user(username)

    return user_state_manager.get_user_state(username)

@app.route("/register", methods=["POST"])
def register():
    """
    Register a new user and initialize their user state.

    Args:
        username: The username to initialize state for
    """
    logger.debug("Registering new user")

    if 'username' in session:
        logger.warning("User already logged in, redirecting to annotate")
        return home()

    username = request.form.get("email")
    password = request.form.get("pass")

    if not username or not password:
        logger.warning("Missing username or password")
        return render_template("home.html",
                                login_error="Username and password are required")

    # Register the user with the autheticator
    user_authenticator = UserAuthenticator.get_instance()
    user_authenticator.add_user(username, password)

    # Redirect to the annotate page
    return redirect(url_for("annotate"))

def get_current_page_html(config: dict, username: str) -> str:
    user_state = get_user_state(username)
    phase, page = user_state.get_current_phase_and_page()
    usm = get_user_state_manager()
    # Look up the html template for the current page
    html_fname = usm.get_phase_html_fname(phase, page)
    # Render the consent form
    return render_template(html_fname)

@app.route("/consent", methods=["GET", "POST"])
def consent():
    if 'username' not in session:
        return home()

    username = session['username']
    user_state = get_user_state(username)
    print('CONSENT: user_state: ', user_state)
    print('CONSENT: user_state.get_phase(): ', user_state.get_phase())

    # Check at the user is still in the consent phase. Note that this might
    # #nvolve multiple pages of different types of consent
    if user_state.get_phase() != UserPhase.CONSENT:
        # If not in the consent phase, dump back to the home page to redirect
        return home()

    # If the user is returning some information from the pag
    if request.method == 'POST':
        # User is logged in, so check where they are in the process and redirect
        print('POST -> CONSENT: ', request.form)

        # The form should require that the user consent to the study
        #
        # TODO: add some extra sanity checks here that they actually did,
        #       which is going to require us to know which keys are the
        #       consent keys from the relevant phase's schema

        # Now that the user has consisented, advance the state
        # and have the home page redirect to the appropriate next phase
        usm = get_user_state_manager()
        usm.advance_phase(session['username'])

        # Reset to pretend this is a new get request
        request.method = 'GET'
        return home()
    # Show the current consent form
    else:
        print("GET <- CONSENT")
        if True:
            return get_current_page_html(config, username)
        # Get the page the user is currentlly on
        phase, page = user_state.get_current_phase_and_page()

        usm = get_user_state_manager()
        # Look up the html template for the current consent form
        consent_html_fname = usm.get_phase_html_fname(phase, page)
        # Render the consent form
        return render_template(consent_html_fname)

@app.route("/instructions", methods=["GET", "POST"])
def instructions():
    if 'username' not in session:
        return home()

    username = session['username']
    user_state = get_user_state(username)

    # Check at the user is still in the instructions phase. Note that this might
    # #nvolve multiple pages of different types of consent
    if user_state.get_phase() != UserPhase.INSTRUCTIONS:
        # If not in the instructions phase, dump back to the home page to redirect
        # Reset to pretend this is a new get request
        return home()

    # If the user is returning some information from the page
    if request.method == 'POST':
        print('POST -> INSTRUCTIONS: ', request.form)

        # Verify that the user has read the instructions.
        #
        # TODO: add some extra sanity checks here that they actually did,
        #       which is going to require us to know which keys are the
        #       required keys and values from the relevant phase's schema

        # Now that the user has read the instructions, advance the state
        # and have the home page redirect to the appropriate next phase
        usm = get_user_state_manager()
        usm.advance_phase(session['username'])
        request.method = 'GET'
        return home()

    # Show the current set of instructions
    else:
        # Get the page the user is currentlly on
        phase, page = user_state.get_current_phase_and_page()
        print('GET <-- INSTRUCTIONS: phase, page: ', phase, page)

        usm = get_user_state_manager()
        # Look up the html template for the current consent form
        instructions_html_fname = usm.get_phase_html_fname(phase, page)
        # Render the consent form
        return render_template(instructions_html_fname)

@app.route("/prestudy", methods=["GET", "POST"])
def prestudy():
    if 'username' not in session:
        return home()

    username = session['username']
    user_state = get_user_state(username)

    # Check at the user is still in the instructions phase. Note that this might
    # #nvolve multiple pages of different types of consent
    if user_state.get_phase() != UserPhase.PRESTUDY:
        print('NOT IN PRESTUDY PHASE')
        return home()

    # If the user is returning some information from the page
    if request.method == 'POST':
        print('POST -> PRESTUDY: ', request.form)

        # Process the prestudy form data
        #
        # TODO: Save this data in the user state manager

        # Advance the state and have the home page redirect to the
        # appropriate next phase
        usm = get_user_state_manager()
        usm.advance_phase(session['username'])
        request.method = 'GET'
        return home()

    # Show the current prestudy page
    else:
        # Get the page the user is currently on
        phase, page = user_state.get_current_phase_and_page()
        print('GET <-- PRESTUDY: phase, page: ', phase, page)

        # Look up the html template for the current page and
        usm = get_user_state_manager()
        prestudy_html_fname = usm.get_phase_html_fname(phase, page)
        return render_template(prestudy_html_fname)

@app.route("/annotate2", methods=["GET", "POST"])
def annotate2():
    if 'username' not in session:
        return home()

    username = session['username']
    user_state = get_user_state(username)

    # Check at the user is in the annotation phase.
    if user_state.get_phase() != UserPhase.ANNOTATION:
        # If not in the annotation phase, dump back to the home page to redirect
        return home()

    # If the user is returning some information from the page
    if request.method == 'POST':
        print('POST -> ANNOTATION: ', request.form)
        usm = get_user_state_manager()
        usm.advance_phase(session['username'])
        request.method = 'GET'
        return home()
    # Show an annotation page
    else:
        # Get the page the user is currentlly on
        phase, page = user_state.get_current_phase_and_page()
        print('GET <-- ANNOTATION: phase, page: ', phase, page)
        usm = get_user_state_manager()
        # Look up the html template for the current annotation form
        html_fname = usm.get_phase_html_fname(phase, page)
        # Render the consent form
        return render_template(html_fname)


@app.route("/annotate", methods=["GET", "POST"])
def annotate():
    """
    Handle annotation page requests.
    """
    # Check if user is logged in
    if 'username' not in session:
        logger.warning("Unauthorized access attempt to annotate page")
        return redirect(url_for("home"))

    username = session['username']

    print('annotate_page: username: ', username)
    print('annotate: request.method: ', request.method)

    # Ensure user state exists
    if not get_user_state_manager().has_user(username):
        logger.info(f"Creating missing user state for {username}")
        init_user_state(username)

    logger.debug("Handling annotation request")

    user_state = get_user_state(username)
    logger.debug(f"Retrieved state for user: {username}")

    # Check user phase
    if user_state.get_phase() != UserPhase.ANNOTATION:
        logger.info(f"User {username} not in annotation phase, redirecting")
        return home()

    # If the user hasn't yet be assigned anything to annotate, do so now. We do
    # this step now rather than when the user was created to ensure that we
    # only assign instances to users after they have completed any pre-study
    # phases that might be required (e.g., consent, instructions, etc.)
    #
    # Have the ItemStateManager assign the instances to the user based on its
    # internal logic (e.g. random, round-robin, etc.). Note that this may
    # be a no-op if the ISM declines to assign items ot the user (e.g.,
    # because they have already annotated everything).
    if not user_state.has_assignments():
        get_item_state_manager().assign_instances_to_user(user_state)

    # See if this user has finished annotating all of their assigned instances
    if not user_state.has_remaining_assignments():
        print('User %s has NO remaining instances to annotate' % username)
        # If the user is done annotating, advance to the next phase
        #
        # NOTE: Should we check prompt the user to confirm that they are done
        # since they won't be able to go back and annotate?
        get_user_state_manager().advance_phase(username)
        return home()

    if request.is_json and 'action' in request.json:
       action = request.json['action']
       print('request.json: ', request.json)
    else:
       action = request.form['action'] if 'action' in request.form else "init"

    print('form: ', request.form)
    # print("Action: ", action)

    if action == "prev_instance":
        move_to_prev_instance(username)

    elif action == "next_instance":
        move_to_next_instance(username)

    elif action == "go_to":
        go_to_id(username, request.form.get("go_to"))
    else:
        print('unrecognized action request: "%s"' % action)

    # Once we figure out what instance the user is annotating now,
    # render the page for that with any existing annotations
    return render_page_with_annotations(username)

@app.route("/go_to", methods=["GET", "POST"])
def go_to():
    """
    TBD
    """
    if 'username' not in session:
        return home()

    username = session['username']
    user_state = get_user_state(username)

    # Check at the user is in the annotation phase.
    if user_state.get_phase() != UserPhase.ANNOTATION:
        # If not in the annotation phase, dump back to the home page to redirect
        return home()

    if request.method == 'POST':
        print('POST -> GO_TO: ', request.form)
        go_to_id(username, request.form.get("go_to"))

    return render_page_with_annotations(username)

def render_page_with_annotations(username) -> str:
    '''
    When annotating, shows the current instance to the user with any annotations
    they may have made. This method is called when the user is in the annotation
    phase and is currently annotating.
    '''

    # Hacky nonsense
    global emphasis_corpus_to_schemas

    user_state = get_user_state_manager().get_user_state(username)
    item = user_state.get_current_instance()
    instance_id = item.get_id()
    # print('instance_id: ', instance_id)

    # directly display the prepared displayed_text
    text = item.get_data()["displayed_text"]
    # print('displayed_text: ', text)

    var_elems = {
        "instance": { "text": text },
        "emphasis": list(emphasis_corpus_to_schemas)
    }

    # also save the displayed text in the metadata dict
    # instance_id_to_data[instance_id]['displayed_text'] = text

    # If the user has labeled spans within this instance before, replace the
    # current instance text with pre-annotated mark-up. We do this here before
    # the render_template call so that we can directly insert the span-marked-up
    # HTML into the template.
    #
    # NOTE: This currently requires a very tight (and kludgy) binding between
    # the UI code for how Potato represents span annotations and how the
    # back-end displays these. Future work when we are better programmers will
    # pass this info to client side for rendering, rather than doing
    # pre-rendering here. This also means that any changes to the UI code for
    # rendering need to be updated here too.
    #
    # NOTE2: We have to this here to account for any keyword highlighting before
    # the instance text gets marked up in the post-processing below
    span_annotations = get_span_annotations_for_user_on(username, instance_id)
    if span_annotations is not None and len(span_annotations) > 0:
        # Mark up the instance text where the annotated spans were
        text = render_span_annotations(text, span_annotations)

    # If the admin has specified that certain keywords need to be highlighted,
    # post-process the selected instance so that it now also has colored span
    # overlays for keywords. This also include label suggestions for the user.
    #
    # NOTE: this code is probably going to break the span annotation's
    # understanding of the instance. Need to check this...
    schema_content_to_prefill = []

    #prepare label suggestions
    label_suggestion_json = get_label_suggestions(item, config, schema_content_to_prefill)

    var_elems["suggestions"] = list(label_suggestion_json)
    # Fill in the kwargs that the user wanted us to include when rendering the page
    kwargs = {}
    for kw in config["item_properties"].get("kwargs", []):
        if kw in item.get_data():
            kwargs[kw] = item.get_data()[kw]

    all_statistics = get_user_state(username).generate_user_statistics()

    # TODO: Display plots for agreement scores instead of only the overall score
    # in the statistics sidebar
    # all_statistics['Agreement'] = get_agreement_score('all', 'all', return_type='overall_average')
    # print(all_statistics)

    # Set the html file as surveyflow pages when the instance is a not an
    # annotation page (survey pages, prestudy pass or fail page)
    html_file = config["site_file"]

    var_elems_html = "".join(
        map(lambda item : (
            f'<script id="{item[0]}" ' +
            ' type="application/json"> ' +
            f' {easy_json(item[1])} </script>'
        ), var_elems.items())
    )

    custom_js = ""
    if config["customjs"] and config.get("customjs_hostname"):
        custom_js = (
            f'<script src="http://{config["customjs_hostname"]}/potato.js"' +
            ' defer></script>'
        )
    elif config["customjs"]:
        custom_js = (
            '<script src="http://localhost:4173/potato.js" ' +
            ' defer></script>'
        )
    else:
        custom_js = (
            '<script src="https://cdn.jsdelivr.net/gh/' +
            'davidjurgens/potato@HEAD/node/live/potato.js" ' +
            ' crossorigin="anonymous"></script>'
        )

    # Flask will fill in the things we need into the HTML template we've created,
    # replacing {{variable_name}} with t    he associated text for keyword arguments
    rendered_html = render_template(
        html_file,
        username=username,
        # This is what instance the user is currently on
        instance=text,
        instance_obj=item,
        instance_id=instance_id,
        instance_index=user_state.get_current_instance_index(),
        finished=get_user_state(username).get_annotation_count(),
        total_count=get_user_state(username).get_max_assignments(),
        alert_time_each_instance=config["alert_time_each_instance"],
        statistics_nav=all_statistics,
        var_elems=var_elems_html,
        custom_js=custom_js,
        **kwargs
    )

    # Parse the page so we can programmatically reset the annotation state
    # to what it was before
    soup = BeautifulSoup(rendered_html, "html.parser")

    # If the user has annotated this before, walk the DOM and fill out what they
    # did
    annotations = get_annotations_for_user_on(username, instance_id)
    # print(f'annotations for {instance_id}: ', annotations)

    # convert the label suggestions into annotations for front-end rendering
    if annotations == None and schema_content_to_prefill:
        scheme_dict = {}
        annotations = defaultdict(dict)
        for it in config['annotation_schemes']:
            if it['annotation_type'] in ['radio', 'multiselect']:
                it['label2value'] = {(l if type(l) == str else l['name']):str(i+1) for i,l in enumerate(it['labels'])}
            scheme_dict[it['name']] = it
        for s in schema_content_to_prefill:
            if scheme_dict[s['name']]['annotation_type'] in ['radio', 'multiselect']:
                annotations[s['name']][s['label']] = scheme_dict[s['name']]['label2value'][s['label']]
            elif scheme_dict[s['name']]['annotation_type'] in ['text']:
                if "labels" not in scheme_dict[s['name']]:
                    annotations[s['name']]['text_box'] = s['label']
            else:
                print('WARNING: label suggestions not supported for annotation_type %s, please submit a github issue to get support'%scheme_dict[s['name']]['annotation_type'])
    #print(schema_content_to_prefill, annotations)


    if annotations is not None:
        # Reset the state
        for label_obj, value in annotations.items():

            print("Filling in ", label_obj, value)

            schema = label_obj.get_schema()
            label = label_obj.get_name()

            name = schema + ":::" + label

            # Find all the input, select, and textarea tags with this name
            # (which was annotated) and figure out which one to fill in
            input_fields = soup.find_all(["input", "select", "textarea"], {"name": name})

            for input_field in input_fields:

                if input_field is None:
                    print("No input for ", name)
                    continue

                # If it's a slider, set the value for the slider
                if input_field['type'] == 'range' and name.endswith(':::slider'):
                    input_field['value'] = value
                    continue

                if input_field['type'] == 'checkbox' or input_field['type'] == 'radio':
                    if value:
                        input_field['checked'] = True

                if input_field['type'] == 'text' or input_field['type'] == 'textarea':
                    if isinstance(value, str):
                        input_field['value'] = value

                if False:
                    # If it's not a text area, let's see if this is the button
                    # that was checked, and if so mark it as checked
                    if input_field.name != "textarea" and input_field.has_attr("value") and input_field.get("value") != value:
                        continue
                    else:
                        input_field["checked"] = True
                        input_field["value"] = value

                    # Set the input value for textarea input
                    #if input_field.name == "textarea" and isinstance(value, str):
                    #    input_field.string = value

                    # Find the right option and set it as selected if the current
                    # annotation schema is a select box
                    if label == "select-one":
                        option = input_field.findChildren("option", {"value": value})[0]
                        option["selected"] = "selected"

    # randomize the order of options for multirate schema
    selected_schemas_for_option_randomization = []
    for it in config['annotation_schemes']:
        if it['annotation_type'] == 'multirate' and it.get('option_randomization'):
            selected_schemas_for_option_randomization.append(it['description'])

    if len(selected_schemas_for_option_randomization) > 0:
        soup = randomize_options(soup, selected_schemas_for_option_randomization,
                                 map_user_id_to_digit(username))

    # If the admin has turned on AI hints, add them to the page
    soup = add_ai_hints(soup, instance_id)

    rendered_html = str(soup)

    return rendered_html

def get_label_suggestions(item, config, schema_content_to_prefill) -> set[SuggestedResponse]:

    label_suggestions_json = set()
    if 'label_suggestions' in item.get_data():
        suggestions = item.get_data()['label_suggestions']
        for schema in config['annotation_schemes']:
            if schema['name'] not in suggestions:
                continue
            suggested_labels = suggestions[schema['name']]
            if type(suggested_labels) == str:
                suggested_labels = [suggested_labels]
            elif type(suggested_labels) == list:
                suggested_labels = suggested_labels
            else:
                print("WARNING: Unsupported suggested label type %s, please check your input data" % type(s))
                continue

            if not schema.get('label_suggestions') in ['highlight', 'prefill']:
                print('WARNING: the style of suggested labels is not defined, please check your configuration file.')
                continue

            label_suggestion = schema['label_suggestions']
            for s in suggested_labels:
                if label_suggestion == 'highlight':
                        #bad suggestion -- TODO make chance configurable
                        if random.randrange(0, 3) == 2:
                            label_suggestions_json.add(SuggestedResponse(schema['name'], random.choice(schema['labels'])))
                            continue

                        label_suggestions_json.add(SuggestedResponse(schema['name'], s))
                elif label_suggestion == 'prefill':
                        schema_content_to_prefill.append({'name':schema['name'], 'label':s})
    return label_suggestions_json

def add_ai_hints(soup: BeautifulSoup, instance_id: str) -> BeautifulSoup:
    """
    Adds AI-generated hints to the page, if enabled. This is a hook for adding hints to the
    page based on the instance that the user is currently annotating.
    """

    return soup


@app.route("/poststudy", methods=["GET", "POST"])
def poststudy():
    if 'username' not in session:
        return home()

    username = session['username']
    user_state = get_user_state(username)

    # Check at the user is still in the instructions phase. Note that this might
    # #nvolve multiple pages of different types of consent
    if user_state.get_phase() != UserPhase.POSTSTUDY:
        # If not in the instructions phase, dump back to the home page to redirect
        # Reset to pretend this is a new get request
        return home()

    # If the user is returning some information from the page
    if request.method == 'POST':
        print('POSTSTUDY: POST: ', request.form)

        # TODO: Record the poststudy data

        # Advance the state and move to the appropriate next phase
        usm = get_user_state_manager()
        usm.advance_phase(session['username'])
        request.method = 'GET'
        return home()

    # Show the current set of instructions
    else:
        # Get the page the user is currentlly on
        phase, page = user_state.get_current_phase_and_page()
        print('INSTRUCTIONS GET: phase, page: ', phase, page)

        usm = get_user_state_manager()
        # Look up the html template for the current consent form
        html_fname = usm.get_phase_html_fname(phase, page)
        # Render the consent form
        return render_template(html_fname)

@app.route("/done", methods=["GET", "POST"])
def done():
    print(get_user_state_manager().phase_type_to_name_to_page)
    return '<p>u did it done now. gud job.</p>'

@app.route("/prolificlogin", methods=["GET", "POST"])
def prolificlogin():
    global user_config


def old_login():

    if config["__debug__"]:
        action = "login"
        username = "debug_user"
        password = "debug"
    elif "login" in config and config["login"]["type"] == "url_direct":
        action = request.form.get("action")
        username = request.form.get("email")
        password = "require_no_password"
    else:
        # Jiaxin: currently we are just using email as the username
        action = request.form.get("action")
        username = request.form.get("email")
        password = request.form.get("pass")

    if action == "login":
        if (
            config["__debug__"]
            or ("login" in config and config["login"]["type"] == "url_direct")
            or user_config.is_valid_password(username, password)
        ):
            # if surveyflow is setup, jump to the page before annotation
            print("%s login successful" % username)
            return annotate_page(username)
        return render_template(
            "home.html",
            title=config["annotation_task_name"],
            login_email=username,
            login_error="Invalid username or password",
        )
    print("unknown action at home page")
    return render_template("home.html", title=config["annotation_task_name"])


@app.route("/signup", methods=["GET", "POST"])
def signup():
    """
    Handle user registration requests.

    Features:
    - Email validation
    - Password handling (TODO: add proper hashing)
    - User authorization checking
    - Config persistence

    Args (from form):
        email: User's email address
        pass: User's password
        action: Request action type

    Returns:
        flask.Response: Rendered template with registration result
    """
    global config
    user_auth = UserAuthenticator.get_instance()
    logger.debug("Processing signup request")

    action = request.form.get("action")
    username = request.form.get("email")
    email = request.form.get("email")
    password = request.form.get("pass")

    logger.debug(f"Signup action: {action}")

    if action == "signup":
        single_user = {"username": username, "email": email, "password": password}
        result = user_auth.add_single_user(single_user)
        logger.info(f"Signup result for {username}: {result}")

        if result == "Success":
            user_auth.save_user_config()
            return render_template(
                "home.html",
                title=config["annotation_task_name"],
                login_email=username,
                login_error="User registration success for " + username + ", please login now",
            )
        elif result == 'Unauthorized user':
            return render_template(
                "home.html",
                title=config["annotation_task_name"],
                login_error=result + ", please contact your admin",
            )

        # TODO: return to the signup page and display error message
        return render_template(
            "home.html",
            title=config["annotation_task_name"],
            login_email=username,
            login_error=result + ", please try again or log in",
        )

    print("unknown action at home page")
    return render_template(
        "home.html",
        title=config["annotation_task_name"],
        login_email=username,
        login_error="Invalid username or password",
    )

@app.route("/updateinstance", methods=["POST"])
def update_instance() -> str:
    '''The API endpoint for updating the instance data when a user clicks on the
       something in the web UI. We track the progress in real time.'''

    if request.is_json:
        # Get the instance id
        instance_id = request.json.get("instance_id")

        # Get the schema name
        schema_name = request.json.get("schema")

        # Get the state of items for that schema
        schema_state = request.json.get("state")

        username = session['username']
        user_state = get_user_state(username)

        print('updateinstance/ -> ', request.json)

        if request.json.get("type") == "label":
            for lv in schema_state:
                label = Label(schema_name, lv['name'])
                value = lv['value']
                user_state.add_label_annotation(instance_id, label, value)
        elif request.json.get("type") == "span":
            for sv in schema_state:
                span = SpanAnnotation(schema_name, sv['name'], sv['title'], sv['start'], sv['end'])
                value = sv['value']
                user_state.add_span_annotation(instance_id, span, value)
        else:
            raise Exception("Unknown annotation type: ", request.json.get("type"))

        # If we're annotating
        if user_state.get_phase() == UserPhase.ANNOTATION:

            # Update that we got some annotation on this instance
            get_item_state_manager().register_annotator(instance_id, username)

        # Save these new instance labels (could be annotations or pre/post study)
        get_user_state_manager().save_user_state(user_state)

    return {"status": "success"}

@app.route("/newuser")
def new_user():
    return render_template("newuser.html")


def get_users() -> list[str]:
    """
    Returns an iterable over the usernames of all users who have annotated in
    the system so far
    """
    global user_state_manager

    return user_state_manager.get_user_ids()


def get_prestudy_label(label):
    for schema in config["annotation_schemes"]:
        if schema["name"] == config["prestudy"]["question_key"]:
            cur_schema = schema["annotation_type"]
    label = convert_labels(label[config["prestudy"]["question_key"]], cur_schema)
    return config["prestudy"]["answer_mapping"][label] if "answer_mapping" in config["prestudy"] else label


def print_prestudy_result():
    global task_assignment
    print("----- prestudy test result -----")
    print("passed annotators: ", task_assignment["prestudy_passed_users"])
    print("failed annotators: ", task_assignment["prestudy_failed_users"])
    print(
        "pass rate: ",
        len(task_assignment["prestudy_passed_users"])
        / len(task_assignment["prestudy_passed_users"] + task_assignment["prestudy_failed_users"]),
    )


def check_prestudy_status(username):
    """
    Check whether a user has passed the prestudy test (this function will only be used )
    :return:
    """
    global task_assignment
    global instance_id_to_data

    if "prestudy" not in config or config["prestudy"]["on"] is False:
        return "no prestudy test"

    user_state = get_user_state(username)

    # directly return the status if the user has passed/failed the prestudy before
    if user_state.get_prestudy_status() == False:
        return "prestudy failed"
    elif user_state.get_prestudy_status() == True:
        return "prestudy passed"

    res = []
    for _id in task_assignment["prestudy_ids"]:
        label = user_state.get_label_annotations(_id)
        if label is None:
            return "prestudy not complete"
        groundtruth = instance_id_to_data[_id][config["prestudy"]["groundtruth_key"]]
        label = get_prestudy_label(label)
        print(label, groundtruth)
        res.append(label == groundtruth)

    print(res, sum(res) / len(res))
    # check if the score is higher than the minimum defined in config
    if (sum(res) / len(res)) < config["prestudy"]["minimum_score"]:
        user_state.set_prestudy_status(False)
        task_assignment["prestudy_failed_users"].append(username)
        prestudy_result = "prestudy just failed"
    else:
        user_state.set_prestudy_status(True)
        task_assignment["prestudy_passed_users"].append(username)
        prestudy_result = "prestudy just passed"

    print_prestudy_result()

    # update the annotation list according the prestudy test result
    #assign_instances_to_user(username)

    return prestudy_result


def generate_initial_user_dataflow(username):
    """
    Generate initial dataflow for a new annotator including surveyflows and prestudy.
    :return: UserAnnotationState
    """
    global user_to_annotation_state
    global instance_id_to_data

    sampled_keys = []
    for it in ["pre_annotation_pages", "prestudy_ids"]:
        if it in task_assignment:
            sampled_keys += task_assignment[it]

    assigned_user_data = {key: instance_id_to_data[key] for key in sampled_keys}

    # save the assigned user data dict
    user_dir = os.path.join(config["output_annotation_dir"], username)
    assigned_user_data_path = os.path.join(user_dir, "assigned_user_data.json")

    if not os.path.exists(user_dir):
        os.makedirs(user_dir)
        logger.debug('Created state directory for user "%s"' % (username))

    with open(assigned_user_data_path, "w") as w:
        json.dump(assigned_user_data, w)

    # return the assigned user data dict
    return assigned_user_data


def sample_instances(username):
    global user_to_annotation_state
    global instance_id_to_data

    # check if sampling strategy is specified in configuration, if not, set it as random
    if "sampling_strategy" not in config["automatic_assignment"] \
           or config["automatic_assignment"]["sampling_strategy"] not in ['random','ordered']:
        logger.debug("Undefined sampling strategy, default to random assignment")
        config["automatic_assignment"]["sampling_strategy"] = "random"

    # Force the sampling strategy to be random at this moment, will change this
    # when more sampling strategies are created
    #config["automatic_assignment"]["sampling_strategy"] = "random"

    if config["automatic_assignment"]["sampling_strategy"] == "random":
        # previously we were doing random sample directly, however, when there
        # are a large amount of instances and users, it is possible that some
        # instances are rarely sampled and some are oversampled at the end of
        # the sampling process
        # sampled_keys = random.sample(list(task_assignment['unassigned'].keys()),
        #                             config["automatic_assignment"]["instance_per_annotator"])

        # Currently we will shuffle the unassinged keys first, and then rank
        # the dict based on the availability of each instance, and they directly
        # get the first N instances
        unassigned_dict = task_assignment["unassigned"]
        unassigned_dict = {
            k: unassigned_dict[k]
            for k in random.sample(list(unassigned_dict.keys()), len(unassigned_dict))
        }
        sorted_keys = [
            it[0] for it in sorted(unassigned_dict.items(), key=lambda item: item[1], reverse=True)
        ]
        sampled_keys = sorted_keys[
            : min(config["automatic_assignment"]["instance_per_annotator"], len(sorted_keys))
        ]

    elif config["automatic_assignment"]["sampling_strategy"] == "ordered":
        # sampling instances based on the natural order of the data

        sorted_keys = list(task_assignment["unassigned"].keys())
        sampled_keys = sorted_keys[
                       : min(config["automatic_assignment"]["instance_per_annotator"], len(sorted_keys))
        ]
        #print(sampled_keys)

    # update task_assignment to keep track of task assignment status globally
    for key in sampled_keys:
        if key not in task_assignment["assigned"]:
            task_assignment["assigned"][key] = []
        task_assignment["assigned"][key].append(username)
        task_assignment["unassigned"][key] -= 1
        if task_assignment["unassigned"][key] == 0:
            del task_assignment["unassigned"][key]

    # sample and insert test questions
    if task_assignment["testing"]["test_question_per_annotator"] > 0:
        sampled_testing_ids = random.sample(
            task_assignment["testing"]["ids"],
            k=task_assignment["testing"]["test_question_per_annotator"],
        )
        # adding test question sampling status to the task assignment
        for key in sampled_testing_ids:
            if key not in task_assignment["assigned"]:
                task_assignment["assigned"][key] = []
            task_assignment["assigned"][key].append(username)
            sampled_keys.insert(random.randint(0, len(sampled_keys) - 1), key)

    return sampled_keys


def assign_instances_to_user(username):
    """
    Assign instances to a user
    :return: UserAnnotationState
    """
    global user_to_annotation_state
    global instance_id_to_data

    user_state = user_to_annotation_state[username]

    # check if the user has already been assigned with instances to annotate
    # Currently we are just assigning once, but we might chance this later
    if user_state.get_real_assigned_instance_count() > 0:
        logging.warning(
            "Instance already assigned to user %s, assigning process stoppped" % username
        )
        return False

    prestudy_status = user_state.get_prestudy_status()
    consent_status = user_state.get_consent_status()

    if prestudy_status is None:
        if "prestudy" in config and config["prestudy"]["on"]:
            logging.warning(
                "Trying to assign instances to user when the prestudy test is not completed, assigning process stoppped"
            )
            return False

        if (
            "surveyflow" not in config
            or not config["surveyflow"]["on"]
            or "prestudy" not in config
            or not config["prestudy"]["on"]
        ) or consent_status:
            sampled_keys = sample_instances(username)
            user_state.real_instance_assigned_count += len(sampled_keys)
            if "post_annotation_pages" in task_assignment:
                sampled_keys = sampled_keys + task_assignment["post_annotation_pages"]
        else:
            logging.warning(
                "Trying to assign instances to user when the user has yet agreed to participate. assigning process stoppped"
            )
            return False

    elif prestudy_status is False:
        sampled_keys = task_assignment["prestudy_failed_pages"]

    else:
        sampled_keys = sample_instances(username)
        user_state.real_instance_assigned_count += len(sampled_keys)
        sampled_keys = task_assignment["prestudy_passed_pages"] + sampled_keys
        if "post_annotation_pages" in task_assignment:
            sampled_keys = sampled_keys + task_assignment["post_annotation_pages"]

    assigned_user_data = {key: instance_id_to_data[key] for key in sampled_keys}
    user_state.add_new_assigned_data(assigned_user_data)

    print(
        "assinged %d instances to %s, total pages: %s, total users: %s, unassigned labels: %s, finished users: %s"
        % (
            user_state.get_real_assigned_instance_count(),
            username,
            user_state.get_assigned_instance_count(),
            get_total_user_count(),
            get_unassigned_count(),
            get_finished_user_count()
        )
    )

    # save the assigned user data dict
    user_dir = os.path.join(config["output_annotation_dir"], username)
    assigned_user_data_path = os.path.join(user_dir, "assigned_user_data.json")

    if not os.path.exists(user_dir):
        os.makedirs(user_dir)
        logger.debug('Created state directory for user "%s"' % (username))

    with open(assigned_user_data_path, "w") as w:
        json.dump(user_state.get_assigned_data(), w)

    # save task assignment status
    task_assignment_path = os.path.join(
        config["output_annotation_dir"], config["automatic_assignment"]["output_filename"]
    )
    with open(task_assignment_path, "w") as w:
        json.dump(task_assignment, w)

    user_state.instance_assigned = True

    # return the assigned user data dict
    return assigned_user_data



def remove_instances_from_users(user_set):
    """
    Remove users from the annotation state, move the saved annotations to another folder
    Release the assigned instances
    """
    global user_to_annotation_state
    global archived_users
    global instance_id_to_data
    global task_assignment

    if len(user_set) == 0:
        print('No users need to be dropped at this moment')
        return None

    #remove user from the global user_to_annotation_state
    for u in user_set:
        if u in user_to_annotation_state:
            archived_users = user_to_annotation_state[u]
            del user_to_annotation_state[u]

    #remove assigned instances
    for inst_id in task_assignment['assigned']:
        new_li = []
        if type(task_assignment['assigned'][inst_id]) != list:
            continue
        for u in task_assignment['assigned'][inst_id]:
            if u in user_set:
                if inst_id not in task_assignment['unassigned']:
                    task_assignment['unassigned'][inst_id] = 0
                task_assignment['unassigned'][inst_id] += 1
            else:
                new_li.append(u)
        # if len(new_li) != len(task_assignment['assigned'][inst_id]):
        #    print(task_assignment['assigned'][inst_id], new_li)
        task_assignment['assigned'][inst_id] = new_li

    # Figure out where this user's data would be stored on disk
    output_annotation_dir = config["output_annotation_dir"]

    # move the bad users into a separate dir under annotation output
    bad_user_dir = os.path.join(output_annotation_dir, "archived_users")
    if not os.path.exists(bad_user_dir):
        os.mkdir(bad_user_dir)
    for u in user_set:
        if os.path.exists(os.path.join(output_annotation_dir, u)):
            shutil.move(os.path.join(output_annotation_dir, u), os.path.join(bad_user_dir, u))
    print('bad users moved to %s' % bad_user_dir)
    print('removed %s users from the current annotation queue' % len(user_set))



def generate_full_user_dataflow(username):
    """
    Directly assign all the instances to a user at the beginning of the study
    :return: UserAnnotationState
    """
    global user_to_annotation_state
    global instance_id_to_data

    #check if sampling strategy is specified in configuration, if not, set it as random
    if "sampling_strategy" not in config["automatic_assignment"] or config["automatic_assignment"]["sampling_strategy"] not in ['random','ordered']:
        logger.debug("Undefined sampling strategy, default to random assignment")
        config["automatic_assignment"]["sampling_strategy"] = "random"

    # Force the sampling strategy to be random at this moment, will change this
    # when more sampling strategies are created
    #config["automatic_assignment"]["sampling_strategy"] = "random"

    if config["automatic_assignment"]["sampling_strategy"] == "random":
        sampled_keys = random.sample(
            list(task_assignment["unassigned"].keys()),
            config["automatic_assignment"]["instance_per_annotator"],
        )
    elif config["automatic_assignment"]["sampling_strategy"] == "ordered":
        # sampling instances based on the natural order of the data

        sorted_keys = list(task_assignment["unassigned"].keys())
        sampled_keys = sorted_keys[
                       : min(config["automatic_assignment"]["instance_per_annotator"], len(sorted_keys))
                       ]

    # update task_assignment to keep track of task assignment status globally
    for key in sampled_keys:
        if key not in task_assignment["assigned"]:
            task_assignment["assigned"][key] = []
        task_assignment["assigned"][key].append(username)
        task_assignment["unassigned"][key] -= 1
        if task_assignment["unassigned"][key] == 0:
            del task_assignment["unassigned"][key]

    # sample and insert test questions
    if task_assignment["testing"]["test_question_per_annotator"] > 0:
        sampled_testing_ids = random.sample(
            task_assignment["testing"]["ids"],
            k=task_assignment["testing"]["test_question_per_annotator"],
        )
        # adding test question sampling status to the task assignment
        for key in sampled_testing_ids:
            if key not in task_assignment["assigned"]:
                task_assignment["assigned"][key] = []
            task_assignment["assigned"][key].append(username)
            sampled_keys.insert(random.randint(0, len(sampled_keys) - 1), key)

    # save task assignment status
    task_assignment_path = os.path.join(
        config["output_annotation_dir"], config["automatic_assignment"]["output_filename"]
    )
    with open(task_assignment_path, "w") as w:
        json.dump(task_assignment, w)

    # add the amount of sampled instances
    real_assigned_instance_count = len(sampled_keys)

    if "pre_annotation_pages" in task_assignment:
        sampled_keys = task_assignment["pre_annotation_pages"] + sampled_keys

    if "post_annotation_pages" in task_assignment:
        sampled_keys = sampled_keys + task_assignment["post_annotation_pages"]

    assigned_user_data = {key: instance_id_to_data[key] for key in sampled_keys}

    # save the assigned user data dict
    user_dir = os.path.join(config["output_annotation_dir"], username)
    assigned_user_data_path = os.path.join(user_dir, "assigned_user_data.json")

    if not os.path.exists(user_dir):
        os.makedirs(user_dir)
        logger.debug('Created state directory for user "%s"' % (username))

    with open(assigned_user_data_path, "w") as w:
        json.dump(assigned_user_data, w)

    # return the assigned user data dict
    return assigned_user_data, real_assigned_instance_count


def instances_all_assigned():
    global task_assignment

    if 'unassigned' in task_assignment and len(task_assignment['unassigned']) <= int(config["automatic_assignment"]["instance_per_annotator"] * 0.7):
        return True
    return False


def get_unassigned_count():
    """
    return the number of unassigned instances
    """
    global task_assignment
    if 'unassigned' in task_assignment:
        return sum(list(task_assignment['unassigned'].values()))
    else:
        return 0

def get_finished_user_count():
    """
        return the number of users who have finished the task
    """
    global user_to_annotation_state
    cnt = 0
    for user_state in user_to_annotation_state.values():
        if user_state.get_real_finished_instance_count() >= user_state.get_real_assigned_instance_count():
            cnt += 1

    return cnt


def get_total_user_count():
    """
    return the number of users
    """
    global user_to_annotation_state

    return len(user_to_annotation_state)

def update_prolific_study_status():
    """
    Update the prolific study status
    This is the regular status update of prolific study object
    """

    global prolific_study
    global user_to_annotation_state

    print('update_prolific_study is called')
    prolific_study.update_submission_status()
    users_to_drop = prolific_study.get_dropped_users()
    users_to_drop = [it for it in users_to_drop if it in user_to_annotation_state] # only drop the users who are currently in the data
    remove_instances_from_users(users_to_drop)

    #automatically check if there are too many users working on the task and if so, pause it
    #
    if prolific_study.get_concurrent_sessions_count() > prolific_study.max_concurrent_sessions:
        print('Concurrent sessions (%s) exceed the predefined threshold (%s), trying to pause the prolific study'%
              (prolific_study.get_concurrent_sessions_count(), prolific_study.max_concurrent_sessions))
        prolific_study.pause_study()

        #use a separate thread to periodically check if the amount of active users are below a threshold
        th = threading.Thread(target=prolific_study.workload_checker)
        th.start()

def get_user_state(user_id: str) -> UserState:
    """
    Returns the UserState for a user
    """

    user_state = get_user_state_manager().get_user_state(user_id)

    return user_state

def save_user_state(username, save_order=False):
    global user_to_annotation_state
    global instance_id_to_data

    # Figure out where this user's data would be stored on disk
    output_annotation_dir = config["output_annotation_dir"]

    # NB: Do some kind of sanitizing on the username to improve security
    user_dir = os.path.join(output_annotation_dir, username)

    user_state = get_user_state(username)

    if not os.path.exists(user_dir):
        os.makedirs(user_dir)
        logger.debug('Created state directory for user "%s"' % (username))

    annotation_order_fname = os.path.join(user_dir, "annotation_order.txt")
    if not os.path.exists(annotation_order_fname) or save_order:
        with open(annotation_order_fname, "wt") as outf:
            for inst in user_state.instance_id_ordering:
                # JIAXIN: output id has to be str
                outf.write(str(inst) + "\n")

    annotated_instances_fname = os.path.join(user_dir, "annotated_instances.jsonl")

    with open(annotated_instances_fname, "wt") as outf:
        for inst_id, data in user_state.get_all_annotations().items():
            bd_dict = {}
            if inst_id in user_state.instance_id_to_behavioral_data:
                bd_dict = user_state.instance_id_to_behavioral_data[inst_id]

            item = get_item_state_manager().get_item(inst_id)

            output = {
                "id": inst_id,
                "displayed_text": item.get_data()["displayed_text"],
                "label_annotations": data["labels"],
                "span_annotations": data["spans"],
                "behavioral_data": bd_dict,
            }
            json.dump(output, outf)
            outf.write("\n")


def save_all_annotations():
    global user_to_annotation_state
    global instance_id_to_data

    # Figure out where this user's data would be stored on disk
    output_annotation_dir = config["output_annotation_dir"]
    fmt = config["output_annotation_format"]

    if fmt not in ["csv", "tsv", "json", "jsonl"]:
        raise Exception("Unsupported output format: " + fmt)

    if not os.path.exists(output_annotation_dir):
        os.makedirs(output_annotation_dir)
        logger.debug("Created state directory for annotations: %s" % (output_annotation_dir))

    annotated_instances_fname = os.path.join(output_annotation_dir, "annotated_instances." + fmt)

    # We write jsonl format regardless
    if fmt in ["json", "jsonl"]:
        with open(annotated_instances_fname, "wt") as outf:
            for user_id, user_state in user_to_annotation_state.items():
                for inst_id, data in user_state.get_all_annotations().items():

                    bd_dict = user_state.instance_id_to_behavioral_data.get(inst_id, {})

                    output = {
                        "user_id": user_id,  # "user_id
                        "instance_id": inst_id,
                        "displayed_text": instance_id_to_data[inst_id]["displayed_text"],
                        "label_annotations": data["labels"],
                        "span_annotations": data["spans"],
                        "behavioral_data": bd_dict,
                    }
                    json.dump(output, outf)
                    outf.write("\n")

    # Convert to Pandas and then dump
    elif fmt in ["csv", "tsv"]:
        df = defaultdict(list)

        # Loop 1, figure out which schemas/labels have values so we know which
        # things will need to be columns in each row
        schema_to_labels = defaultdict(set)
        span_labels = set()

        for user_state in user_to_annotation_state.values():
            for annotations in user_state.get_all_annotations().values():
                # Columns for each label-based annotation
                for schema, label_vals in annotations["labels"].items():
                    for label in label_vals.keys():
                        schema_to_labels[schema].add(label)

                # Columns for each span type too
                for span in annotations["spans"]:
                    span_labels.add(span["annotation"])

                # TODO: figure out what's in the behavioral dict and how to format it

        # Loop 2, report everything that's been annotated
        for user_id, user_state in user_to_annotation_state.items():
            for inst_id, annotations in user_state.get_all_annotations().items():

                df["user"].append(user_id)
                df["instance_id"].append(inst_id)
                df["displayed_text"].append(instance_id_to_data[inst_id]["displayed_text"])

                label_annotations = annotations["labels"]
                span_annotations = annotations["spans"]

                for schema, labels in schema_to_labels.items():
                    if schema in label_annotations:
                        label_vals = label_annotations[schema]
                        for label in labels:
                            val = label_vals[label] if label in label_vals else None
                            # For some sanity, combine the schema and label it a single column
                            df[schema + ":::" + label].append(val)
                    # If the user did label this schema at all, fill it with None values
                    else:
                        for label in labels:
                            df[schema + ":::" + label].append(None)

                # We bunch spans by their label to make it slightly easier to
                # process, but it's still kind of messy compared with the JSON
                # format.
                for span_label in span_labels:
                    anns = [sa for sa in span_annotations if sa["annotation"] == span_label]
                    df["span_annotation:::" + span_label].append(anns)

                # TODO: figure out what's in the behavioral dict and how to format it

        df = pd.DataFrame(df)
        sep = "," if fmt == "csv" else "\t"
        df.to_csv(annotated_instances_fname, index=False, sep=sep)

    # Save the annotation assignment info if automatic task assignment is on.
    # Jiaxin: we are simply saving this as a json file at this moment
    if "automatic_assignment" in config and config["automatic_assignment"]["on"]:
        # TODO: write the code here
        print("saved")


def load_user_state(config: dict):
    users_with_annotations = [
        f for f in os.listdir(config["output_annotation_dir"])
        if os.path.isdir(os.path.join(config["output_annotation_dir"],f)) and f != 'archived_users'
    ]
    for user in users_with_annotations:
        #load_user_state2(user)
        pass

def load_user_state2(username):
    """
    Loads the user's state from disk. The state includes which instances they
    have annotated and the order in which they are expected to see instances.
    """

    # Figure out where this user's data would be stored on disk
    user_state_dir = config["output_annotation_dir"]

    # NB: Do some kind of sanitizing on the username to improve securty
    user_dir = os.path.join(user_state_dir, username)

    # User has annotated before or has assigned_data
    if os.path.exists(user_dir):
        logger.debug('Found known user "%s"; loading annotation state' % (username))

        # if automatic assignment is on, load assigned user data
        if "automatic_assignment" in config and config["automatic_assignment"]["on"]:
            assigned_user_data_path = os.path.join(user_dir, "assigned_user_data.json")

            with open(assigned_user_data_path, "r") as r:
                assigned_user_data = json.load(r)
        # otherwise, set the assigned user data as all the instances
        else:
            #assigned_user_data = instance_id_to_data
            pass

        annotation_order = []
        annotation_order_fname = os.path.join(user_dir, "annotation_order.txt")
        if os.path.exists(annotation_order_fname):
            with open(annotation_order_fname, "rt") as f:
                for line in f:
                    instance_id = line[:-1]
                    if instance_id not in assigned_user_data:
                        logger.warning(
                            (
                                "Annotation state for %s does not match "
                                + "instances in existing dataset at %s"
                            )
                            % (user_dir, ",".join(config["data_files"]))
                        )
                        continue
                    annotation_order.append(line[:-1])

        annotated_instances = []
        annotated_instances_fname = os.path.join(user_dir, "annotated_instances.jsonl")
        if os.path.exists(annotated_instances_fname):

            with open(annotated_instances_fname, "rt") as f:
                for line in f:
                    annotated_instance = json.loads(line)
                    instance_id = annotated_instance["id"]
                    if instance_id not in assigned_user_data:
                        logger.warning(
                            (
                                "Annotation state for %s does not match "
                                + "instances in existing dataset at %s"
                            )
                            % (user_dir, ",".join(config["data_files"]))
                        )
                        continue
                    annotated_instances.append(annotated_instance)

        # Ensure the current data is represented in the annotation order
        # NOTE: this is a hack to be fixed for when old user data is in the same directory
        for iid in assigned_user_data.keys():
            if iid not in annotation_order:
                annotation_order.append(iid)

        user_state = UserAnnotationState(assigned_user_data)
        user_state.update(annotation_order, annotated_instances)

        # Make sure we keep track of the user throughout the program
        user_to_annotation_state[username] = user_state

        logger.info(
            'Loaded %d annotations for known user "%s"'
            % (user_state.get_real_finished_instance_count(), username)
        )

        return "old user loaded"

    # New user, so initialize state
    else:

        logger.debug('Previously unknown user "%s"; creating new annotation state' % (username))

        # whenever a user creation happens, update the prolific study first so that we can potentially release some spots
        if config.get('prolific'):
            update_prolific_study_status()

        # create new user state with the look up function
        if instances_all_assigned():
            if config.get('prolific'):
                print('All instance have been assigned, trying to pause the prolific study')
                prolific_study.pause_study()
            return "all instances have been assigned"

        get_user_state(username)
        return "new user initialized"


def get_cur_instance_for_user(username):
    global user_to_annotation_state
    global instance_id_to_data

    user_state = get_user_state(username)

    return user_state.get_current_instance()


def previous_response(user, file_path):
    global user_story_pos
    global user_response_dicts_queue
    user_story_pos[user] -= 1

    with open(file_path, "r") as f:
        responses = f.readlines()[:-1]

    user_response_dicts_queue[user].pop()

    with open(file_path, "w") as f:
        for line in responses:
            f.write(line)


def get_displayed_text(text):
    # automatically unfold the text list when input text is a list (e.g. best-worst-scaling).
    if "list_as_text" in config and config["list_as_text"]:
        if isinstance(text, str):
            try:
                text = eval(text)
            except Exception:
                text = str(text)
        if isinstance(text, list):
            if config["list_as_text"]["text_list_prefix_type"] == "alphabet":
                prefix_list = list(string.ascii_uppercase)
                text = [prefix_list[i] + ". " + text[i] for i in range(len(text))]
            elif config["list_as_text"]["text_list_prefix_type"] == "number":
                text = [str(i) + ". " + text[i] for i in range(len(text))]
            text = "<br>".join(text)

        # unfolding dict into different sections
        elif isinstance(text, dict):
            #randomize the order of the displayed text
            if "randomization" in config["list_as_text"]:
                if config["list_as_text"].get("randomization") == "value":
                    values = list(text.values())
                    random.shuffle(values)
                    text = {key: value for key, value in zip(text.keys(), values)}
                elif config["list_as_text"].get("randomization") == "key":
                    keys = list(text.keys())
                    random.shuffle(keys)
                    text = {key: text[key] for key in keys}
                else:
                    print("WARNING: %s currently not supported for list_as_text, please check your .yaml file"%config["list_as_text"].get("randomization"))

            block = []
            if config["list_as_text"].get("horizontal"):
                for key in text:
                    block.append(
                        '<div id="instance-text" name="instance_text" style="float:left;width:%s;padding:5px;" class="column"> <legend> %s </legend> %s </div>'
                        % ("%d" % int(100 / len(text)) + "%", key, text[key])
                    )
                text = '<div class="row" style="display: table"> %s </div>' % ("".join(block))
            else:
                for key in text:
                    block.append(
                        '<div id="instance-text" name="instance_text"> <legend> %s </legend> %s <br/> </div>'
                        % (key, text[key])
                    )
                text = "".join(block)
        else:
            text = text
    return text


#@app.route("/annotate", methods=["GET", "POST"])
def annotate_page(username=None, action=None):
    """
    Parses the input received from the user's annotation and takes some action
    based on what was clicked/typed. This method is the main switch for changing
    the state of the server for this user.
    """
    # use the provided username when the username is given
    if not username:
        if config["__debug__"]:
            username = "debug_user"
        else:
            username_from_last_page = request.form.get("email")
            if username_from_last_page is None:
                return render_template(
                    "error.html",
                    error_message="Please login to annotate or you are using the wrong link",
                )
            username = username_from_last_page

    # Check if the user is authorized. If not, go to the login page
    # if not user_config.is_valid_username(username):
    #    return render_template("home.html")

    print('annotate_page')

    # Based on what the user did to the instance, update the annotate state for
    # this instance. All of the instances clicks/checks/text are stored in the
    # request.form object, which has the name of the HTML element and its value.
    #
    # If the user actually changed the annotate state (as opposed to just moving
    # through instances), then save the state of the annotations.
    #
    # NOTE: I *think* this is safe from race conditions since the flask server
    # is running in a single thread, but it's probably good to check on this at
    # some point if we scale to having lots of concurrent users.
    if "instance_id" in request.form:
        did_change = update_annotation_state(username, request.form)

        if did_change:

            # Check if we need to run active learning to re-order instances. We
            # do this before saving the user state in case the order does change.o
            #
            # NOTE: In a perfect world, this would be done in a separate process
            # that is synchronized and users get their next instance from some
            # centrally managed queue so we don't block while doing all this
            # training. However, such advanced wizardry is beyond this MVP and
            # will have to wait
            if (
                "active_learning_config" in config
                and config["active_learning_config"]["enable_active_learning"]
            ):

                # Check to see if we've hit the threshold for the number of
                # annotations needed
                al_config = config["active_learning_config"]

                # How many total annotations do we need to have
                update_rate = al_config["update_rate"]
                total_annotations = get_total_annotations()

                if total_annotations % update_rate == 0:
                    actively_learn()

            save_user_state(username)

            # Save everything in a separate thread to avoid I/O issues
            th = threading.Thread(target=save_all_annotations)
            th.start()

    # AJYL: Note that action can still be None, if "src" not in request.form.
    # Not sure if this is intended.
    action = request.form.get("src") if action is None else action

    if action == "home":
        result_code = load_user_state(username)
        if result_code == "all instances have been assigned":
            return render_template(
                "error.html",
                error_message="Sorry that you've come a bit late. We have collected enough responses for our study. However, prolific sometimes will recruit more participants than we expected. We are sorry for the inconvenience!",
            )

    elif action == "prev_instance":
        move_to_prev_instance(username)

    elif action == "next_instance":
        move_to_next_instance(username)

    elif action == "go_to":
        go_to_id(username, request.form.get("go_to"))

    else:
        print('unrecognized action request: "%s"' % action)

    instance = get_cur_instance_for_user(username)

    id_key = config["item_properties"]["id_key"]
    if config["annotation_task_name"] == "Contextual Acceptability":
        context_key = config["item_properties"]["context_key"]

    # directly display the prepared displayed_text
    instance_id = instance[id_key]
    text = instance["displayed_text"]
    var_elems = {
        "instance": { "text": text },
        "emphasis": list(emphasis_corpus_to_schemas)
    }

    # also save the displayed text in the metadata dict
    # instance_id_to_data[instance_id]['displayed_text'] = text

    # If the user has labeled spans within this instance before, replace the
    # current instance text with pre-annotated mark-up. We do this here before
    # the render_template call so that we can directly insert the span-marked-up
    # HTML into the template.
    #
    # NOTE: This currently requires a very tight (and kludgy) binding between
    # the UI code for how Potato represents span annotations and how the
    # back-end displays these. Future work when we are better programmers will
    # pass this info to client side for rendering, rather than doing
    # pre-rendering here. This also means that any changes to the UI code for
    # rendering need to be updated here too.
    #
    # NOTE2: We have to this here to account for any keyword highlighting before
    # the instance text gets marked up in the post-processing below
    span_annotations = get_span_annotations_for_user_on(username, instance_id)
    if span_annotations is not None and len(span_annotations) > 0:
        # Mark up the instance text where the annotated spans were
        text = render_span_annotations(text, span_annotations)

    # If the admin has specified that certain keywords need to be highlighted,
    # post-process the selected instance so that it now also has colored span
    # overlays for keywords.
    #
    # NOTE: this code is probably going to break the span annotation's
    # understanding of the instance. Need to check this...
    schema_content_to_prefill = []

    #prepare label suggestions
    label_suggestion_json = set()
    if 'label_suggestions' in instance:
        suggestions = instance['label_suggestions']
        for schema in config['annotation_schemes']:
            if schema['name'] not in suggestions:
                continue
            suggested_labels = suggestions[schema['name']]
            if type(suggested_labels) == str:
                suggested_labels = [suggested_labels]
            elif type(suggested_labels) == list:
                suggested_labels = suggested_labels
            else:
                print("WARNING: Unsupported suggested label type %s, please check your input data" % type(s))
                continue

            if not schema.get('label_suggestions') in ['highlight', 'prefill']:
                print('WARNING: the style of suggested labels is not defined, please check your configuration file.')
                continue

            label_suggestion = schema['label_suggestions']
            for s in suggested_labels:
                if label_suggestion == 'highlight':
                        #bad suggestion -- TODO make chance configurable
                        if random.randrange(0, 3) == 2:
                            label_suggestion_json.add(SuggestedResponse(schema['name'], random.choice(schema['labels'])))
                            continue

                        label_suggestion_json.add(SuggestedResponse(schema['name'], s))
                elif label_suggestion == 'prefill':
                        schema_content_to_prefill.append({'name':schema['name'], 'label':s})

    var_elems["suggestions"] = list(label_suggestion_json)
    # Fill in the kwargs that the user wanted us to include when rendering the page
    kwargs = {}
    for kw in config["item_properties"].get("kwargs", []):
        if kw in instance:
            kwargs[kw] = instance[kw]

    all_statistics = get_user_state(username).generate_user_statistics()

    # TODO: Display plots for agreement scores instead of only the overall score
    # in the statistics sidebar
    # all_statistics['Agreement'] = get_agreement_score('all', 'all', return_type='overall_average')
    # print(all_statistics)

    # Set the html file as surveyflow pages when the instance is a not an
    # annotation page (survey pages, prestudy pass or fail page)
    if instance_id in config.get("non_annotation_pages", []):
        html_file = instance_id
    # otherwise set the page as the normal annotation page
    else:
        html_file = config["site_file"]

    var_elems_html = "".join(
        map(lambda item : (
            f'<script id="{item[0]}" ' +
            ' type="application/json"> ' +
            f' {easy_json(item[1])} </script>'
        ), var_elems.items())
    )

    custom_js = ""
    if config["customjs"] and config.get("customjs_hostname"):
        custom_js = (
            f'<script src="http://{config["customjs_hostname"]}/potato.js"' +
            ' defer></script>'
        )
    elif config["customjs"]:
        custom_js = (
            '<script src="http://localhost:4173/potato.js" ' +
            ' defer></script>'
        )
    else:
        custom_js = (
            '<script src="https://cdn.jsdelivr.net/gh/' +
            'davidjurgens/potato@HEAD/node/live/potato.js" ' +
            ' crossorigin="anonymous"></script>'
        )

    # Flask will fill in the things we need into the HTML template we've created,
    # replacing {{variable_name}} with the associated text for keyword arguments
    rendered_html = render_template(
        html_file,
        username=username,
        # This is what instance the user is currently on
        instance=text,
        instance_obj=instance,
        instance_id=get_user_state(username).get_current_instance_index(),
        finished=get_user_state(username).get_real_finished_instance_count(),
        total_count=get_user_state(username).get_real_assigned_instance_count(),
        alert_time_each_instance=config["alert_time_each_instance"],
        statistics_nav=all_statistics,
        var_elems=var_elems_html,
        custom_js=custom_js,
        **kwargs
    )

    # UGHGHGHGH the template does unusual escaping, which makes it a PAIN to do
    # the replacement later
    # m = re.search('<div name="instance_text">(.*?)</div>', rendered_html,
    #              flags=(re.DOTALL|re.MULTILINE))
    # text = m.group(1)

    # Parse the page so we can programmatically reset the annotation state
    # to what it was before
    soup = BeautifulSoup(rendered_html, "html.parser")

    # If the user has annotated this before, walk the DOM and fill out what they
    # did
    annotations = get_annotations_for_user_on(username, instance_id)

    # convert the label suggestions into annotations for front-end rendering
    if annotations == None and schema_content_to_prefill:
        scheme_dict = {}
        annotations = defaultdict(dict)
        for it in config['annotation_schemes']:
            if it['annotation_type'] in ['radio', 'multiselect']:
                it['label2value'] = {(l if type(l) == str else l['name']):str(i+1) for i,l in enumerate(it['labels'])}
            scheme_dict[it['name']] = it
        for s in schema_content_to_prefill:
            if scheme_dict[s['name']]['annotation_type'] in ['radio', 'multiselect']:
                annotations[s['name']][s['label']] = scheme_dict[s['name']]['label2value'][s['label']]
            elif scheme_dict[s['name']]['annotation_type'] in ['text']:
                if "labels" not in scheme_dict[s['name']]:
                    annotations[s['name']]['text_box'] = s['label']
            else:
                print('WARNING: label suggestions not supported for annotation_type %s, please submit a github issue to get support'%scheme_dict[s['name']]['annotation_type'])
    #print(schema_content_to_prefill, annotations)


    if annotations is not None:
        # Reset the state
        for schema, labels in annotations.items():
            for label, value in labels.items():

                print("Filling in", schema, label, value)

                name = schema + ":::" + label

                # Find all the input, select, and textarea tags with this name
                # (which was annotated) and figure out which one to fill in
                input_fields = soup.find_all(["input", "select", "textarea"], {"name": name})

                for input_field in input_fields:
                    if input_field is None:
                        print("No input for ", name)
                        continue

                    # If it's a slider, set the value for the slider
                    if input_field['type'] == 'range' and name.endswith(':::slider'):
                        input_field['value'] = value
                        continue

                    # If it's not a text area, let's see if this is the button
                    # that was checked, and if so mark it as checked
                    if input_field.name != "textarea" and input_field.has_attr("value") and input_field.get("value") != value:
                        continue
                    else:
                        input_field["checked"] = True
                        input_field["value"] = value

                    # Set the input value for textarea input
                    if input_field.name == "textarea":
                        input_field.string = value

                    # Find the right option and set it as selected if the current
                    # annotation schema is a select box
                    elif label == "select-one":
                        option = input_field.findChildren("option", {"value": value})[0]
                        option["selected"] = "selected"

    # randomize the order of options for multirate schema
    selected_schemas_for_option_randomization = []
    for it in config['annotation_schemes']:
        if it['annotation_type'] == 'multirate' and it.get('option_randomization'):
            selected_schemas_for_option_randomization.append(it['description'])

    if len(selected_schemas_for_option_randomization) > 0:
        soup = randomize_options(soup, selected_schemas_for_option_randomization, map_user_id_to_digit(username))

    rendered_html = str(soup)

    return rendered_html


def map_user_id_to_digit(user_id_str):
    # Convert the user_id_str to an integer using a hash function
    user_id_hash = hash(user_id_str)

    # Map the hashed value to a single-digit integer using modulus
    digit = abs(user_id_hash) % 9 + 1  # Add 1 to avoid 0

    return digit


def randomize_options(soup, legend_names, seed):
    random.seed(seed)

    # Find all fieldsets in the soup
    fieldsets = soup.find_all('fieldset')
    if not fieldsets:
        print("No fieldsets found.")
        return soup

    # Initialize a variable to track whether the legend is found
    legend_found = False

    # Iterate through each fieldset
    for fieldset in fieldsets:
        # Find the legend within the current fieldset
        legend = fieldset.find('legend')
        if legend and legend.string in legend_names:
            # Legend found, set the flag and break the loop
            legend_found = True

            # Find the table within the fieldset
            table = fieldset.find('table')
            if not table:
                print("Table not found within the fieldset.")
                continue

            # Get the list of tr elements excluding the first one (title)
            tr_elements = table.find_all('tr')[1:]

            # Shuffle the tr elements based on the given random seed
            random.shuffle(tr_elements)

            # Insert the shuffled tr elements back into the tbody
            for tr in tr_elements:
                table.append(tr)

    # Check if any legend was found
    if not legend_found:
        print(f"No matching legends found within any fieldset.")

    return soup


def get_color_for_schema_label(schema, label):
    global schema_label_to_color

    t = (schema, label)
    if t in schema_label_to_color:
        return schema_label_to_color[t]
    c = COLOR_PALETTE[len(schema_label_to_color)]
    schema_label_to_color[t] = c
    return c


def parse_html_span_annotation(html_span_annotation):
    """
    Parses the span annotations produced in raw HTML by Potato's front end
    and extracts out the precise spans and labels annotated by users.

    :returns: a tuple of (1) the annotated string without annotation HTML
              and a list of annotations
    """
    s = html_span_annotation.strip()
    init_tag_regex = re.compile(r"(<span.+?>)")
    end_tag_regex = re.compile(r"(</span>)")
    anno_regex = re.compile(r'<div class="span_label".+?>(.+)</div>')
    no_html_s = ""
    start = 0

    annotations = []

    while True:
        m = init_tag_regex.search(s, start)
        if not m:
            break

        # find the end tag
        m2 = end_tag_regex.search(s, m.end())

        middle = s[m.end() : m2.start()]

        # Get the annotation label from the middle text
        m3 = anno_regex.search(middle)

        middle_text = middle[: m3.start()]
        annotation = m3.group(1)

        no_html_s += s[start : m.start()]

        ann = {
            "start": len(no_html_s),
            "end": len(no_html_s) + len(middle_text),
            "span": middle_text,
            "annotation": annotation,
        }
        annotations.append(ann)

        no_html_s += middle_text
        start = m2.end(0)

    # Add whatever trailing text exists
    no_html_s += s[start:]

    return no_html_s, annotations

def parse_story_pair_from_file(filepath):
    with open(filepath, "r") as f:
        lines = f.readlines()
    lines = [l.strip("\n").split("\t") for l in lines]
    return lines


@app.route("/<path:filename>")
def get_file(filename):
    """
    Serve static files needed for annotation interface.

    Args:
        filename (str): Path to requested file relative to working directory

    Returns:
        flask.Response: File contents or 404 error

    Raises:
        FileNotFoundError: If requested file doesn't exist
    """
    logger.debug(f"File request for: {filename}")
    try:
        return flask.send_from_directory(os.getcwd(), filename)
    except FileNotFoundError:
        logger.warning(f"File not found: {filename}")
        flask.abort(404)


def get_class(kls):
    """
    Dynamically load and instantiate a class from its fully qualified name.

    Args:
        kls (str): Fully qualified class name (e.g. "package.module.ClassName")

    Returns:
        type: Instantiated class object

    Raises:
        ImportError: If module cannot be imported
        AttributeError: If class doesn't exist in module
    """
    logger.debug(f"Loading class: {kls}")
    parts = kls.split(".")
    module = ".".join(parts[:-1])

    try:
        m = __import__(module)
        for comp in parts[1:]:
            m = getattr(m, comp)
        logger.debug(f"Successfully loaded class {kls}")
        return m
    except (ImportError, AttributeError) as e:
        logger.error(f"Failed to load class {kls}: {e}")
        raise



def resolve(annotations, strategy):
    """
    Resolve multiple annotations into a single annotation using specified strategy.

    Args:
        annotations (list): List of annotation values to resolve
        strategy (str): Resolution strategy ('random' or others)

    Returns:
        Any: Single resolved annotation value

    Raises:
        ValueError: If strategy is unknown
    """
    logger.debug(f"Resolving {len(annotations)} annotations using strategy: {strategy}")

    if strategy == "random":
        result = random.choice(annotations)
        logger.debug(f"Random resolution selected: {result}")
        return result

    error_msg = f'Unknown annotation resolution strategy: "{strategy}"'
    logger.error(error_msg)
    raise ValueError(error_msg)

def run_create_task_cli():
    """
    Launch the interactive task creation CLI.

    Prompts user to:
    - Choose between CLI and GUI interfaces (GUI not implemented)
    - Start task creation process
    - Configure task parameters

    Raises:
        NotImplementedError: If GUI option is selected
    """
    logger.info("Starting task creation process")

    if yes_or_no("Launch task creation process?"):
        if yes_or_no("Launch on command line?"):
            logger.info("Starting CLI task creation")
            create_task_cli()
        else:
            error_msg = "GUI-based design not supported yet"
            logger.error(error_msg)
            raise NotImplementedError(error_msg)
    else:
        logger.info("Task creation cancelled by user")

def run_server(args):
    """
    Initialize and run the Flask annotation server.

    Handles:
    - Configuration loading
    - Template setup
    - Directory creation
    - Data loading
    - Server startup

    Args:
        args: Command line arguments

    Raises:
        ConfigurationError: If server configuration is invalid
    """
    logger.info("Initializing annotation server")

    # Initialize config
    init_config(args)

    # Apply command line flags that override config settings
    if args.require_password is not None:
        # Command line flag takes precedence over config file
        config["require_password"] = args.require_password
        logger.debug(f"Password requirement set from command line: {args.require_password}")

    # Set logging level based on verbosity flags
    if config.get("verbose"):
        logger.setLevel(logging.DEBUG)
    if config.get("very_verbose"):
        logger.setLevel(logging.NOTSET)

    # Ensure that the task directory exists
    task_dir = config["task_dir"]
    if not os.path.exists(task_dir):
        os.makedirs(task_dir)

    # Ensure that the output annotation directory exists
    output_annotation_dir = config["output_annotation_dir"]
    if not os.path.exists(output_annotation_dir):
        os.makedirs(output_annotation_dir)

    # Initialize authenticator
    UserAuthenticator.init_from_config(config)

    init_user_state_manager(config)
    init_item_state_manager(config)
    load_all_data(config)


    # Log password requirement status
    logger.info(f"Password authentication required: {config.get('require_password', True)}")

    # Server startup
    port = args.port or config.get("port", default_port)
    logger.info(f"Starting server on port {port}")

    app.config["SESSION_PERMANENT"] = False
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=1)
    app.secret_key = b'_5#y2L"F4Q8z\n\xec]/FIXME22'  # TODO: Make configurable

    logger.info("Server initialization complete")
    app.run(debug=args.very_verbose, host="0.0.0.0", port=port)

def main():
    """
    Main entry point for the annotation server.

    Handles:
    - Command line argument parsing
    - Server mode selection:
        - Task creation
        - Server startup
        - Project retrieval
        - Project listing
    - Configuration loading
    """
    logger.info("Starting annotation platform")

    if len(sys.argv) == 1:
        logger.debug("No arguments provided, launching task creation")
        return run_create_task_cli()

    args = arguments()
    logger.debug(f"Parsed arguments: {args}")

    if args.mode == 'start':
        logger.info("Starting server mode")
        run_server(args)
    elif args.mode == 'get':
        logger.info("Starting project retrieval")
        get_project_from_hub(args.config_file)
    elif args.mode == 'list':
        logger.info("Listing available projects")
        show_project_hub(args.config_file)

    logger.info("Annotation platform shutdown complete")


if __name__ == "__main__":
    main()

def init_user_state(username):
    """
    Initialize the user state for a new user.

    Args:
        username: The username to initialize state for
    """
    user_state_manager = get_user_state_manager()

    # Only initialize if user doesn't already have state
    if not user_state_manager.has_user(username):
        logger.debug(f"Initializing state for new user: {username}")

        # Create user state
        user_state = user_state_manager.add_user(username)


@app.route("/routes", methods=["GET"])
def show_routes():
    """Debug endpoint to show all registered routes"""
    routes = []
    for rule in app.url_map.iter_rules():
        methods = ','.join(sorted([method for method in rule.methods if method not in ('OPTIONS', 'HEAD')]))
        routes.append(f"{rule} ({methods})")

    routes.sort()
    return jsonify({
        "routes": routes,
        "total": len(routes)
    })

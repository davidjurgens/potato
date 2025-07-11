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
import re
from collections import deque, defaultdict, Counter, OrderedDict
from itertools import zip_longest
import string
import threading
import yaml
from datetime import datetime, timedelta

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

from dataclasses import dataclass

cur_working_dir = os.getcwd() #get the current working dir
cur_program_dir = os.path.dirname(os.path.abspath(__file__)) #get the current program dir (for the case of pypi, it will be the path where potato is installed)
flask_templates_dir = os.path.join(cur_program_dir,'templates') #get the dir where the flask templates are saved
base_html_dir = os.path.join(cur_program_dir,'base_htmls') #get the dir where the the base_html templates files are saved

#insert the current program dir into sys path
sys.path.insert(0, cur_program_dir)

from potato.item_state_management import ItemStateManager, Item, Label, SpanAnnotation
from potato.item_state_management import get_item_state_manager, init_item_state_manager
from potato.user_state_management import UserStateManager, UserState, get_user_state_manager, init_user_state_manager
from potato.authentificaton import UserAuthenticator
from potato.phase import UserPhase

from potato.create_task_cli import create_task_cli, yes_or_no
from potato.server_utils.arg_utils import arguments
from potato.server_utils.config_module import init_config, config
from potato.server_utils.schemas.span import render_span_annotations
from potato.server_utils.cli_utlis import get_project_from_hub, show_project_hub
from potato.server_utils.prolific_apis import ProlificStudy
from potato.server_utils.json import easy_json

# This allows us to create an AI endpoint for the system to interact with as needed (if configured)
from ai.ai_endpoint import get_ai_endpoint

# Initialize Flask app
app = Flask(__name__)

# Secret key will be set in configure_app() from config

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

# path to save user information
USER_CONFIG_PATH = "user_config.json"
DEFAULT_LABELS_PER_INSTANCE = 3

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
        'base': os.path.join(cur_program_dir, 'base_html/base_template_v2.html'),
        'default': os.path.join(cur_program_dir, 'base_html/base_template_v2.html'),
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

# Set session timeout duration (e.g., 30 minutes)
SESSION_TIMEOUT = timedelta(minutes=1)

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
        print(f"[DEBUG] Loading data from file: {data_fname}")
        print(f"[DEBUG] Current working directory: {os.getcwd()}")
        print(f"[DEBUG] File exists: {os.path.exists(data_fname)}")

        # Read and print first few lines of the file
        try:
            with open(data_fname, "rt") as f:
                first_lines = [f.readline().strip() for _ in range(3)]
                print(f"[DEBUG] First 3 lines of file: {first_lines}")
        except Exception as e:
            print(f"[DEBUG] Error reading file: {e}")

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

    # Check if the output directory exists
    if not os.path.exists(user_data_dir):
        os.makedirs(user_data_dir)
        logger.info("Created output directory: %s" % user_data_dir)
        return

    # For each user's directory, load in their state
    user_dirs = [d for d in os.listdir(user_data_dir) if os.path.isdir(os.path.join(user_data_dir, d))]

    for user_dir in user_dirs:
        try:
            usm.load_user_state(os.path.join(user_data_dir, user_dir))
        except ValueError as e:
            # Skip directories that don't have valid user state files
            logger.warning("Skipping invalid user directory %s: %s" % (user_dir, str(e)))
            continue

    logger.info("Loaded user data for %d users" % len(usm.get_user_ids()))

def load_all_data(config: dict):
    '''Loads instance and annotation data from the files specified in the config.'''
    load_annotation_schematic_data(config)
    load_instance_data(config)
    load_user_data(config)
    load_phase_data(config)
    load_highlights_data(config)

    print("STATES: ", get_user_state_manager().phase_type_to_name_to_page)

def load_annotation_schematic_data(config: dict) -> None:
    # Lazy import - only when this function is called
    from server_utils.front_end import generate_annotation_html_template

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
    # Lazy import - only when this function is called
    from server_utils.front_end import generate_html_from_schematic

    global logger

    if "phases" not in config or not config["phases"]:
        return

    phases = config["phases"]
    if "order" in phases:
        phase_order = phases["order"]
    else:
        phase_order = [k for k in phases.keys() if k != "order"]

    logger.debug(f"[PHASE LOAD] phases dict: {phases}")
    logger.debug(f"[PHASE LOAD] phase_order: {phase_order}")

    logger.debug("Loading %d phases in order: %s" % (len(phase_order), phase_order))

    for phase_name in phase_order:
        try:
            phase = phases[phase_name]
            if not "type" in phase or not phase['type']:
                logger.error(f"Phase {phase_name} does not have a type")
                raise Exception("Phase %s does not have a type" % phase_name)
            if not "file" in phase or not phase['file']:
                logger.error(f"Phase {phase_name} is specified but does not have a file")
                raise Exception("Phase %s is specified but does not have a file" % phase_name)

            # Get the phase labeling schemes, being robust to relative or absolute paths
            phase_scheme_fname = get_abs_or_rel_path(phase['file'], config)
            logger.debug(f"Resolved phase file for {phase_name}: {phase_scheme_fname}")
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
                logger.error(f"Error generating HTML for phase {phase_name} (file: {phase['file']}): {e}")
                raise Exception("Error generating HTML for phase %s (file: %s): %s" \
                                % (phase_name, phase['file'], str(e)))

            phase_type = UserPhase.fromstr(phase['type'])

            # Register the HTML so it's easy to find later
            user_state_manager = get_user_state_manager()
            user_state_manager.add_phase(phase_type, phase_name, phase_html_fname)
            logger.debug(f"Registered phase {phase_name} as {phase_type} with HTML {phase_html_fname}")

        except Exception as e:
            logger.error(f"Failed to load phase '{phase_name}': {e}")
            continue

    user_state_manager = get_user_state_manager()
    logger.debug(f"[PHASE LOAD] phase_type_to_name_to_page: {user_state_manager.phase_type_to_name_to_page}")


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
    import os
    logger = globals().get('logger', None)
    if logger:
        logger.debug(f"get_abs_or_rel_path: input fname={fname}")
    if os.path.exists(fname):
        if logger:
            logger.debug(f"get_abs_or_rel_path: found file at {fname}")
        return fname

    # See if we can find the file in the same directory as the config file
    dname = os.path.dirname(config["__config_file__"]) if "__config_file__" in config else os.getcwd()
    rel_path = os.path.join(dname, fname)
    if logger:
        logger.debug(f"get_abs_or_rel_path: trying {rel_path}")
    if os.path.exists(rel_path):
        if logger:
            logger.debug(f"get_abs_or_rel_path: found file at {rel_path}")
        return rel_path

    # See if we can locate the file in the current working directory
    cwd = os.getcwd()
    rel_path = os.path.join(cwd, fname)
    if logger:
        logger.debug(f"get_abs_or_rel_path: trying {rel_path}")
    if os.path.exists(rel_path):
        if logger:
            logger.debug(f"get_abs_or_rel_path: found file at {rel_path}")
        return rel_path

    # See if we can figure it out from the real path directory
    real_path = os.path.abspath(dname)
    dir_path = os.path.dirname(real_path)
    fname2 = os.path.join(dir_path, fname)
    if logger:
        logger.debug(f"get_abs_or_rel_path: trying {fname2}")
    if not os.path.exists(fname2):
        if logger:
            logger.error(f"File not found: {fname2}")
        raise FileNotFoundError("File not found: %s" % fname2)
    return fname2

def get_displayed_text(text):
    """Render the text to display to the user in the annotation interface."""
    if config.get("highlight_linebreaks", False):
        text = text.replace("\n", "<br/>")

    return text

# Core functions used by routes.py

def init_user_state(username):
    """
    Initialize the state for a user, returning the user state object.
    """
    usm = get_user_state_manager()
    usm.add_user(username)

    # Store the session creation time
    session['created_at'] = datetime.now()

    return usm.get_user_state(username)

def is_session_valid() -> bool:
    """
    Check if the current session is valid based on the creation time.
    """
    if 'created_at' not in session:
        return False
    return datetime.now() - session['created_at'] < SESSION_TIMEOUT

@app.before_request
def before_request():
    """
    Check session validity before processing any request.
    """
    # Skip session validation in debug mode
    if config.get("debug", False):
        return None

    if not is_session_valid():
        session.clear()  # Clear the session
        return redirect(url_for('login'))  # Redirect to login page

def get_users():
    """
    Returns the list of users that have logged in.
    """
    return get_user_state_manager().get_user_ids()

def get_user_state(username):
    """
    Returns the user state object for the given username.
    """
    return get_user_state_manager().get_user_state(username)

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

def get_current_page_html(config, username):
    """
    Returns the HTML for the current page that the user is on.
    """
    user_state = get_user_state(username)
    phase, page = user_state.get_current_phase_and_page()

    usm = get_user_state_manager()
    html_fname = usm.get_phase_html_fname(phase, page)
    return render_template(html_fname)

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

    # Shea: Test for AI suggestion
    # ai_hints = get_ai_hints(text)

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
        # Pass annotation schemes to the template
        annotation_schemes=config["annotation_schemes"],
        annotation_task_name=config["annotation_task_name"],
        debug=config.get("debug", False),
        # ai=ai_hints,
        **kwargs
    )

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
    print("annotations")
    print(annotations)
    if annotations is not None:
        # Reset the state
        for schema_name, label_dict in annotations.items():
            # this needs to be fixed, there is a chance that we get incorrect type
            if not isinstance(label_dict, dict):
                print(f"Skipping {schema_name}: Expected dict but got {type(label_dict)} -> {label_dict}")
                continue

            for label_name, value in label_dict.items():
                schema = schema_name
                label = label_name
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

# Shea: a function to get some suggestions from AI
def ai_hints(text: str) -> str:
    """
    Returns the AI hints for the given instance.
    """
    import requests
    print(text)
    description = config["annotation_schemes"][0]["description"]
    annotation_type = config["annotation_schemes"][0]["annotation_type"]
    print(description)
    prompt = f'''You are assisting a user with an annotation task. Here is the annotation instruction: {description}
    Here is the annotation task type: {annotation_type}
    Here is the sentence (or item) to annotate: {text}
    Based on the instruction, task type, and the given sentence, generate a short, helpful hint that guides the user on how to approach this annotation.
    Also, give a short reason of your answer and the relevant part(keyword or text).
    The hint should not provide the label or answer directly, but should highlight what the user might consider or look for.'''

    try:
        response = requests.post(
            'http://localhost:11434/api/generate',
            json={
                # 'model': 'llama3.2',
                'model': 'qwen3:0.6b',
                'prompt': prompt,
                'stream': False
            },
            timeout=5  # Add timeout to prevent hanging
        )
        print(response.json()['response'])
        return response.json()['response']
    except requests.exceptions.ConnectionError:
        print("AI hints service not available (Ollama not running)")
        return "AI hints are currently unavailable. Please proceed with manual annotation."
    except requests.exceptions.Timeout:
        print("AI hints service timeout")
        return "AI hints service is slow to respond. Please proceed with manual annotation."
    except Exception as e:
        print(f"Error getting AI hints: {e}")
        return "AI hints are currently unavailable. Please proceed with manual annotation."



def render_page_with_annotations_WEIRD(username):
    """
    Renders the annotation page with the current instance and any existing annotations.
    """
    user_state = get_user_state(username)
    instance_id = user_state.get_current_instance_id()

    # Get the annotations for this instance
    annotations = get_annotations_for_user_on(username, instance_id)
    span_annotations = get_span_annotations_for_user_on(username, instance_id)

    # Get the instance data
    item = get_item_state_manager().get_item(instance_id)
    item_data = item.get_data()

    # Get the HTML template
    phase, page = user_state.get_current_phase_and_page()
    html_fname = get_user_state_manager().get_phase_html_fname(phase, page)

    # Get user progress information
    progress = user_state.get_progress()

    return render_template(
        html_fname,
        instance_id=instance_id,
        instance_data=item_data,
        annotations=annotations,
        span_annotations=span_annotations,
        progress=progress,
        username=username
    )

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

def map_user_id_to_digit(user_id_str):
    # Convert the user_id_str to an integer using a hash function
    user_id_hash = hash(user_id_str)

    # Map the hashed value to a single-digit integer using modulus
    digit = abs(user_id_hash) % 9 + 1  # Add 1 to avoid 0

    return digit

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
    raw_annotations = user_state.get_label_annotations(instance_id)

    # Process the raw annotations into the expected format
    processed_annotations = {}
    for label, value in raw_annotations.items():
        if hasattr(label, 'schema_name') and hasattr(label, 'label_name'):
            schema_name = label.schema_name
            label_name = label.label_name
        else:
            # Fallback for string labels
            continue

        if schema_name not in processed_annotations:
            processed_annotations[schema_name] = {}
        processed_annotations[schema_name][label_name] = value

    return processed_annotations


def get_span_annotations_for_user_on(username, instance_id):
    """
    Returns the span annotations made by this user on the instance.
    """
    user_state = get_user_state(username)
    span_annotations = user_state.get_span_annotations(instance_id)
    print(f"🔍 get_span_annotations_for_user_on({username}, {instance_id}): {span_annotations}")
    return span_annotations

def parse_html_span_annotation(html):
    """
    Parses the HTML for span annotations and returns the text and a list of spans.
    """
    soup = BeautifulSoup(html, "html.parser")
    spans = []
    for span in soup.find_all("span", {"data-annotation": True}):
        spans.append({
            "text": span.get_text(),
            "label": span["data-label"],
            "start": int(span["data-start"]),
            "end": int(span["data-end"])
        })
    return soup.get_text(), spans

def validate_annotation(annotation):
    """
    Validates that the annotation is properly formatted.
    """
    # Simple validation for now - can be expanded as needed
    return isinstance(annotation, dict)

# Configure the Flask application
def configure_app(flask_app):
    """
    Configure the Flask application instance

    Args:
        flask_app: The Flask application instance

    Returns:
        The configured Flask application instance
    """
    global app
    app = flask_app

    # Set application configuration
    app.secret_key = config.get("secret_key", "potato-annotation-platform")
    app.permanent_session_lifetime = timedelta(days=config.get("session_lifetime_days", 2))

    # Configure routes from the routes module
    from routes import configure_routes
    configure_routes(app, config)

    return app

# Function to create and initialize the Flask application
def create_app():
    """
    Create and configure the Flask application

    Returns:
        The configured Flask application instance
    """
    global app

    # Initialize the app
    app = Flask(__name__)

    # Configure the app
    configure_app(app)

    return app

def run_server(args):
    """
    Run the Flask server with the given arguments.
    """

    # Initialize configuration
    init_config(args)


    # Apply command line flags that override config settings
    if args.require_password is not None:
        # Command line flag takes precedence over config file
        config["require_password"] = args.require_password
        logger.debug(f"Password requirement set from command line: {args.require_password}")

    # Override port from command line if specified
    if args.port is not None:
        config["port"] = args.port
        logger.debug(f"Port set from command line: {args.port}")

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

    # Create and configure the Flask app
    app = create_app()

    # Run the Flask app
    host = config.get("host", "0.0.0.0")
    port = config.get("port", 8000)
    app.run(host=host, port=port, debug=config.get("debug", False), use_reloader=False)


# Define the main entry point for the Flask server
def main():
    """
    Main entry point for the Flask server

    This function initializes the application, loads data, and runs the server.
    """
    # Parse command line arguments
    args = arguments()

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


# Main entry point
if __name__ == "__main__":
    main()

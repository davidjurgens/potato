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
- Active learning integration
- Admin dashboard functionality

The server handles:
1. Data loading from various file formats (JSON, CSV, TSV, JSONL)
2. User session management and authentication
3. Annotation submission and validation
4. Phase progression and workflow management
5. AI hint generation and integration
6. Active learning model training and instance reordering
7. Admin dashboard data generation
8. Configuration management and validation

Key Components:
- Flask application setup and configuration
- Data loading and preprocessing
- User state initialization
- Annotation scheme processing
- Template rendering and customization
- Session timeout management
- Error handling and logging
"""
from __future__ import annotations
from dataclasses import dataclass

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
from typing import List, Dict, Any

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

# Get current working directory and program directory
cur_working_dir = os.getcwd() #get the current working dir
cur_program_dir = os.path.dirname(os.path.abspath(__file__)) #get the current program dir (for the case of pypi, it will be the path where potato is installed)
flask_templates_dir = os.path.join(cur_program_dir,'templates') #get the dir where the flask templates are saved
base_html_dir = os.path.join(cur_program_dir,'base_htmls') #get the dir where the the base_html templates files are saved

#insert the current program dir into sys path
sys.path.insert(0, cur_program_dir)

from potato.item_state_management import ItemStateManager, Item, Label, SpanAnnotation
from potato.item_state_management import get_item_state_manager, init_item_state_manager
from potato.user_state_management import UserStateManager, UserState, get_user_state_manager, init_user_state_manager
from potato.authentication import UserAuthenticator
from potato.phase import UserPhase
from potato.expertise_manager import init_expertise_manager, get_expertise_manager, clear_expertise_manager
from potato.quality_control import (
    init_quality_control_manager, get_quality_control_manager, clear_quality_control_manager
)
from potato.adjudication import (
    init_adjudication_manager, get_adjudication_manager, clear_adjudication_manager
)

from potato.create_task_cli import create_task_cli, yes_or_no
from potato.server_utils.arg_utils import arguments
from potato.server_utils.config_module import init_config, config
from potato.server_utils.schemas.span import render_span_annotations
from potato.server_utils.cli_utlis import get_project_from_hub, show_project_hub
from potato.server_utils.prolific_apis import ProlificStudy
from potato.server_utils.mturk_apis import init_mturk_hit, get_mturk_hit
from potato.server_utils.json import easy_json
from potato.server_utils.instance_display import InstanceDisplayRenderer, get_instance_display_renderer

# This allows us to create an AI endpoint for the system to interact with as needed (if configured)
from potato.ai.ai_endpoint import get_ai_endpoint

# AI support initialization
from potato.ai.ai_prompt import init_ai_prompt
from potato.ai.ai_cache import init_ai_cache_manager, get_ai_cache_manager
from potato.ai.ai_help_wrapper import init_dynamic_ai_help

# Initialize Flask app
app = Flask(__name__)

# Secret key will be set in configure_app() from config

# Use centralized logging configuration
from potato.logging_config import get_logger, setup_logging
logger = get_logger(__name__)

# Set random seed for reproducible behavior
random.seed(0)

# Global variables for file management and user tracking
domain_file_path = ""
file_list = []
file_list_size = 0
default_port = 8000
user_dict = {}

file_to_read_from = ""

# User story position tracking and response queue management
user_story_pos = defaultdict(lambda: 0, dict())
user_response_dicts_queue = defaultdict(deque)

# path to save user information
USER_CONFIG_PATH = "user_config.json"
DEFAULT_LABELS_PER_INSTANCE = 3

# Hacky nonsense - schema label to color mapping
schema_label_to_color = {}

# Global Prolific study instance for API integration
PROLIFIC_STUDY_INSTANCE = None

# Keyword Highlights File Data
@dataclass(frozen=True)
class HighlightSchema:
    """
    Data class for highlight schema information.

    This class represents a highlight schema with a label and schema name.
    It's used for organizing highlight data and ensuring consistent
    color assignments across the annotation interface.
    """
    label: str
    schema: str

    def __hash__(self):
        return hash((self.label, self.schema))

# Global emphasis corpus to schemas mapping
emphasis_corpus_to_schemas = defaultdict(set)

# Keyword highlight patterns loaded from TSV file
# List of dicts: {pattern: str, regex: compiled_regex, label: str, schema: str}
keyword_highlight_patterns = []

# Keyword highlight settings (probabilities, random word config)
# These control randomization and caching behavior for keyword highlights
keyword_highlight_settings = {
    'keyword_probability': 1.0,        # Probability of showing a matched keyword (0.0-1.0)
    'random_word_probability': 0.0,    # Probability of highlighting random words (disabled by default)
    'random_word_label': 'distractor', # Label for random word highlights
    'random_word_schema': 'keyword',   # Schema for random word highlights
}

def get_keyword_highlight_patterns():
    """Get the current keyword highlight patterns list."""
    logger.debug(f"[get_keyword_highlight_patterns] Returning {len(keyword_highlight_patterns)} patterns")
    return keyword_highlight_patterns

def get_keyword_highlight_settings():
    """Get the current keyword highlight settings."""
    return keyword_highlight_settings

# Response Highlight Class
@dataclass(frozen=True)
class SuggestedResponse:
    """
    Data class for suggested response information.

    This class represents a suggested response with a name and label.
    It's used for AI-generated suggestions and pre-filled annotation values.
    """
    name: str
    label: str

    def __hash__(self):
        return hash((self.name, self.label))

# Color palette for annotation interface
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
# REMOVED: template_dict is no longer needed since we use hardcoded template paths

class ActiveLearningState:
    """
    A class for maintaining state on active learning.

    This class tracks active learning selection types and update rounds
    to ensure proper coordination between active learning cycles and
    user assignment updates.
    """

    def __init__(self):
        """Initialize the active learning state tracker."""
        self.id_to_selection_type = {}
        self.id_to_update_round = {}
        self.cur_round = 0

    def update_selection_types(self, id_to_selection_type):
        """
        Update the selection types for active learning.

        Args:
            id_to_selection_type: Dictionary mapping instance IDs to selection types
        """
        self.cur_round += 1

        for iid, st in id_to_selection_type.items():
            self.id_to_selection_type[iid] = st
            self.id_to_update_round[iid] = self.cur_round

# Set session timeout duration (e.g., 30 minutes)
SESSION_TIMEOUT = timedelta(minutes=1)

def load_instance_data(config: dict):
    """
    Load instance data from the files specified in the config.

    This function reads annotation data from various file formats (JSON, CSV, TSV, JSONL)
    and populates the ItemStateManager with the data. It handles different data structures
    and validates that required fields are present.

    Args:
        config: Configuration dictionary containing data file paths and item properties

    Side Effects:
        - Populates ItemStateManager with loaded data
        - Validates data structure and required fields
        - Logs loading progress and statistics

    Raises:
        Exception: If file format is unsupported or required fields are missing
    """
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
            # Handle JSON and JSONL formats
            # Try parsing as a JSON array first, fall back to JSON Lines
            with open(data_fname, "rt") as f:
                raw = f.read()

            items = None
            if fmt == "json":
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, list):
                        items = parsed
                        logger.debug(f"Parsed {data_fname} as JSON array with {len(items)} items")
                except json.JSONDecodeError:
                    pass  # Fall through to JSON Lines parsing

            if items is None:
                # Parse as JSON Lines (one JSON object per line)
                items = []
                for line_no, line in enumerate(raw.splitlines()):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        items.append(json.loads(line))
                    except json.JSONDecodeError as e:
                        raise ValueError(
                            f"Invalid JSON at line {line_no+1} in {data_fname}: {e}"
                        ) from e

            for item_no, item in enumerate(items):
                if not isinstance(item, dict):
                    raise ValueError(f"Expected JSON object at item {item_no+1} in {data_fname}, got {type(item).__name__}")

                # Validate that the ID key exists in the item
                if id_key not in item:
                    raise KeyError(f"ID key '{id_key}' not found in item {item_no+1}")

                instance_id = str(item[id_key]) # Ensure ID is string

                # Check for duplicate IDs
                if ism.has_item(instance_id):
                    raise ValueError(f"Duplicate instance ID '{instance_id}' found at item {item_no+1}")

                # Validate text key exists if required
                if text_key not in item:
                    logger.warning(f"Text key '{text_key}' not found in item with ID '{instance_id}'")

                ism.add_item(instance_id, item)

            line_no = len(items)
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

    # Rebuild instance_annotators from loaded user state so that
    # adjudication build_queue() (and other code that relies on
    # ism.instance_annotators) works with pre-loaded annotation data.
    ism = get_item_state_manager()
    for user_id in usm.get_user_ids():
        user_state = usm.get_user_state(user_id)
        if user_state:
            for instance_id in user_state.instance_id_to_label_to_value:
                if instance_id in ism.instance_id_to_instance:
                    ism.register_annotator(instance_id, user_id)
            for instance_id in user_state.instance_id_to_span_to_value:
                if instance_id in ism.instance_id_to_instance:
                    ism.register_annotator(instance_id, user_id)

    logger.info("Loaded user data for %d users" % len(usm.get_user_ids()))

def load_training_data(config: dict) -> None:
    """
    Load training data from the training data file specified in the config.

    This function loads training instances with correct answers and explanations
    for the training phase. It validates the training data format and stores
    the training instances for use during the training phase.

    Args:
        config: Configuration dictionary containing training settings

    Side Effects:
        - Stores training instances in global training data storage
        - Validates training data format and consistency
        - Logs loading progress and statistics

    Raises:
        Exception: If training data file is not found or invalid
    """
    if 'training' not in config or not config['training'].get('enabled', False):
        logger.debug("Training not enabled, skipping training data loading")
        return

    training_config = config['training']
    data_file = training_config.get('data_file')

    if not data_file:
        logger.warning("Training enabled but no data_file specified")
        return

    # Resolve the training data file path
    try:
        training_data_path = get_abs_or_rel_path(data_file, config)
    except FileNotFoundError:
        logger.error(f"Training data file not found: {data_file}")
        raise Exception(f"Training data file not found: {data_file}")

    logger.debug(f"Loading training data from {training_data_path}")

    try:
        with open(training_data_path, 'r', encoding='utf-8') as f:
            training_data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.error(f"Invalid training data file format: {e}")
        raise Exception(f"Invalid training data file format: {e}")

    if not isinstance(training_data, dict):
        raise Exception("Training data must be a JSON object")

    if 'training_instances' not in training_data:
        raise Exception("Training data must contain 'training_instances' field")

    training_instances = training_data['training_instances']
    if not isinstance(training_instances, list):
        raise Exception("training_instances must be a list")

    if not training_instances:
        raise Exception("training_instances cannot be empty")

    # Validate training data against annotation schemes
    annotation_schemes = training_config.get('annotation_schemes', config.get('annotation_schemes', []))

    # Handle both string references and full scheme dictionaries
    scheme_names = set()
    for scheme in annotation_schemes:
        if isinstance(scheme, str):
            # String reference to existing scheme
            scheme_names.add(scheme)
        elif isinstance(scheme, dict) and 'name' in scheme:
            # Full scheme dictionary
            scheme_names.add(scheme['name'])
        else:
            logger.warning(f"Invalid annotation scheme format: {scheme}")

    # Convert training instances to Item objects and store them
    global training_items
    training_items = []

    for instance in training_instances:
        # Validate required fields
        if 'id' not in instance or 'text' not in instance or 'correct_answers' not in instance:
            raise Exception(f"Training instance missing required fields: {instance}")

        # Validate correct_answers correspond to annotation schemes
        for scheme_name in instance['correct_answers'].keys():
            if scheme_name not in scheme_names:
                logger.warning(f"Training instance {instance['id']} contains unknown scheme: {scheme_name}")

        # Normalize category field (can be string or list)
        category_value = instance.get('category')
        if category_value is not None:
            if isinstance(category_value, str):
                categories = [category_value]
            elif isinstance(category_value, list):
                categories = [c for c in category_value if isinstance(c, str) and c.strip()]
            else:
                logger.warning(f"Training instance {instance['id']} has invalid category type: {type(category_value)}")
                categories = []
        else:
            categories = []

        # Create Item object for training instance
        item_data = {
            'id': instance['id'],
            'text': instance['text'],
            'correct_answers': instance['correct_answers'],
            'explanation': instance.get('explanation', ''),
            'displayed_text': get_displayed_text(instance['text']),
            'categories': categories  # Store normalized categories list
        }

        training_item = Item(instance['id'], item_data)
        training_items.append(training_item)

    logger.info(f"Loaded {len(training_items)} training instances")
    logger.debug(f"Training instances: {[item.get_id() for item in training_items]}")


def get_training_instances() -> List[Item]:
    """
    Get the loaded training instances.

    Returns:
        List of training Item objects
    """
    global training_items
    return training_items if 'training_items' in globals() else []


def get_training_correct_answers(instance_id: str) -> Dict[str, Any]:
    """
    Get the correct answers for a training instance.

    Args:
        instance_id: The ID of the training instance

    Returns:
        Dictionary of correct answers for the instance
    """
    training_items = get_training_instances()
    for item in training_items:
        if item.get_id() == instance_id:
            return item.get_data().get('correct_answers', {})
    return {}


def get_training_explanation(instance_id: str) -> str:
    """
    Get the explanation for a training instance.

    Args:
        instance_id: The ID of the training instance

    Returns:
        Explanation string for the instance
    """
    training_items = get_training_instances()
    for item in training_items:
        if item.get_id() == instance_id:
            return item.get_data().get('explanation', '')
    return ''


def get_training_instance_categories(instance_id: str) -> List[str]:
    """
    Get the categories for a training instance.

    Args:
        instance_id: The ID of the training instance

    Returns:
        List of category names (empty list if no categories)
    """
    training_items = get_training_instances()
    for item in training_items:
        if item.get_id() == instance_id:
            return item.get_data().get('categories', [])
    return []


# =============================================================================
# Prolific Integration Functions
# =============================================================================

def init_prolific_study(config: dict) -> None:
    """
    Initialize the Prolific study instance from config.

    This function reads the Prolific configuration and initializes the
    ProlificStudy API wrapper for tracking participants and managing
    study status.

    Args:
        config: The application configuration dictionary

    Side Effects:
        - Sets global PROLIFIC_STUDY_INSTANCE
        - May start workload checker thread
    """
    global PROLIFIC_STUDY_INSTANCE

    prolific_config = config.get('prolific', {})
    if not prolific_config:
        logger.debug("No Prolific configuration found")
        return

    # Check for config file path
    config_file_path = prolific_config.get('config_file_path')
    if config_file_path:
        # Load Prolific config from file
        import yaml
        prolific_config_path = get_abs_or_rel_path(config_file_path, config)
        if os.path.exists(prolific_config_path):
            with open(prolific_config_path, 'r') as f:
                prolific_settings = yaml.safe_load(f)
                logger.info(f"Loaded Prolific config from {prolific_config_path}")
        else:
            logger.warning(f"Prolific config file not found: {prolific_config_path}")
            return
    else:
        # Use inline config
        prolific_settings = prolific_config

    # Validate required fields
    token = prolific_settings.get('token')
    study_id = prolific_settings.get('study_id')

    if not token or not study_id:
        logger.warning("Prolific config missing 'token' or 'study_id'")
        return

    # Get optional settings
    max_concurrent_sessions = prolific_settings.get('max_concurrent_sessions', 30)
    workload_checker_period = prolific_settings.get('workload_checker_period', 60)

    # Get saving directory for submission data
    saving_dir = config.get('output_annotation_dir', 'annotation_output')

    try:
        PROLIFIC_STUDY_INSTANCE = ProlificStudy(
            token=token,
            study_id=study_id,
            saving_dir=saving_dir,
            max_concurrent_sessions=max_concurrent_sessions,
            workload_checker_period=workload_checker_period
        )
        logger.info(f"Initialized Prolific study: {study_id}")
        logger.info(f"Study info: {PROLIFIC_STUDY_INSTANCE.get_basic_study_info()}")

    except Exception as e:
        logger.error(f"Failed to initialize Prolific study: {e}")
        PROLIFIC_STUDY_INSTANCE = None


def get_prolific_study() -> 'ProlificStudy':
    """
    Get the global Prolific study instance.

    Returns:
        ProlificStudy instance if configured, None otherwise
    """
    return PROLIFIC_STUDY_INSTANCE


def load_all_data(config: dict):
    '''Loads instance and annotation data from the files specified in the config.'''
    load_annotation_schematic_data(config)
    load_instance_data(config)
    load_user_data(config)
    load_phase_data(config)
    load_highlights_data(config)
    load_training_data(config)
    init_prolific_study(config)
    init_mturk_hit(config)

    logger.debug(f"STATES: {get_user_state_manager().phase_type_to_name_to_page}")

def load_annotation_schematic_data(config: dict) -> None:
    # Lazy import - only when this function is called
    from server_utils.front_end import generate_annotation_html_template

    # No longer need to swap in template paths - they are hardcoded in front_end.py

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
    """
    Load keyword highlights from a TSV file specified in the config.

    The TSV file should have columns: Word, Label, Schema
    - Word: The keyword or phrase to highlight (supports * wildcards)
    - Label: The annotation label associated with this keyword
    - Schema: The annotation schema name

    Wildcards are converted to regex patterns:
    - 'word*' matches 'word', 'words', 'wording', etc.
    - '*word' matches 'sword', 'keyword', etc.
    - 'word' matches exactly 'word' (case-insensitive, word boundaries)

    Also loads keyword_highlight_settings from config:
    - keyword_probability: Probability of showing matched keywords (default: 1.0)
    - random_word_probability: Probability of highlighting random words (default: 0.05)
    - random_word_label: Label for random highlights (default: 'distractor')
    - random_word_schema: Schema for random highlights (default: 'keyword')
    """
    # IMPORTANT: When running as __main__, we need to modify the list in the
    # package module (potato.flask_server) so that routes.py can see the changes.
    # This is because Python treats __main__ and potato.flask_server as different modules.
    import sys
    if __name__ == '__main__' and 'potato.flask_server' in sys.modules:
        # Use the package module's list instead of __main__'s list
        pkg_module = sys.modules['potato.flask_server']
        patterns_list = pkg_module.keyword_highlight_patterns
        emphasis_map = pkg_module.emphasis_corpus_to_schemas
        settings_dict = pkg_module.keyword_highlight_settings
    else:
        global keyword_highlight_patterns, emphasis_corpus_to_schemas, keyword_highlight_settings
        patterns_list = keyword_highlight_patterns
        emphasis_map = emphasis_corpus_to_schemas
        settings_dict = keyword_highlight_settings

    # Load keyword highlight settings from config (with defaults)
    config_settings = config.get('keyword_highlight_settings', {})
    settings_dict['keyword_probability'] = config_settings.get('keyword_probability', 1.0)
    settings_dict['random_word_probability'] = config_settings.get('random_word_probability', 0.05)
    settings_dict['random_word_label'] = config_settings.get('random_word_label', 'distractor')
    settings_dict['random_word_schema'] = config_settings.get('random_word_schema', 'keyword')
    logger.debug(f"Loaded keyword highlight settings: {settings_dict}")

    keyword_highlights_file = config.get("keyword_highlights_file")
    if not keyword_highlights_file:
        logger.debug("No keyword_highlights_file specified in config")
        return

    # Note: CWD is already set to task_dir by config_module.py,
    # so we just need to convert to absolute path from CWD
    # (don't prepend task_dir again, or we'll double the path)
    keyword_highlights_file = os.path.realpath(keyword_highlights_file)

    if not os.path.exists(keyword_highlights_file):
        logger.warning(f"Keyword highlights file not found: {keyword_highlights_file}")
        return

    logger.info(f"Loading keyword highlights from: {keyword_highlights_file}")

    # Clear the existing list in place (don't reassign) so that modules
    # that imported keyword_highlight_patterns see the updated contents
    patterns_list.clear()

    try:
        with open(keyword_highlights_file, 'r', encoding='utf-8') as f:
            import csv
            reader = csv.DictReader(f, delimiter='\t')

            for row in reader:
                word = row.get('Word', '').strip()
                label = row.get('Label', '').strip()
                schema = row.get('Schema', '').strip()

                if not word:
                    continue

                # Convert wildcard pattern to regex
                # Escape special regex characters except *
                escaped = re.escape(word).replace(r'\*', r'\w*')

                # Add word boundary markers for exact matching
                # If pattern starts with wildcard, don't require word boundary at start
                # If pattern ends with wildcard, don't require word boundary at end
                if word.startswith('*'):
                    pattern = escaped
                else:
                    pattern = r'\b' + escaped

                if word.endswith('*'):
                    pattern = pattern
                else:
                    pattern = pattern + r'\b'

                try:
                    compiled_regex = re.compile(pattern, re.IGNORECASE)
                    patterns_list.append({
                        'pattern': word,
                        'regex': compiled_regex,
                        'label': label,
                        'schema': schema
                    })

                    # Also populate the emphasis corpus for backward compatibility
                    emphasis_map[word].add(HighlightSchema(label=label, schema=schema))

                except re.error as e:
                    logger.warning(f"Invalid regex pattern for keyword '{word}': {e}")
                    continue

        logger.info(f"Loaded {len(patterns_list)} keyword highlight patterns")

    except Exception as e:
        logger.error(f"Error loading keyword highlights file: {e}")
        patterns_list.clear()

def load_phase_data(config: dict) -> None:
    # Lazy import - only when this function is called
    from server_utils.front_end import generate_html_from_schematic

    global logger

    if "phases" not in config or not config["phases"]:
        return

    phases = config["phases"]

    # Handle both list and dictionary formats for phases
    if isinstance(phases, list):
        # If phases is a list, use the order as defined in the list
        phase_order = [phase["name"] for phase in phases]
        # Convert list to dict for easier access
        phases_dict = {phase["name"]: phase for phase in phases}
    else:
        # Original dictionary format
        if "order" in phases:
            phase_order = phases["order"]
        else:
            phase_order = [k for k in phases.keys() if k != "order"]
        phases_dict = phases

    logger.debug(f"[PHASE LOAD] phases: {phases}")
    logger.debug(f"[PHASE LOAD] phase_order: {phase_order}")

    logger.debug("Loading %d phases in order: %s" % (len(phase_order), phase_order))

    for phase_name in phase_order:
        try:
            phase = phases_dict[phase_name]

            # Handle new format with annotation_schemes directly in phase
            if "annotation_schemes" in phase:
                phase_labeling_schemes = phase["annotation_schemes"]
                # Determine phase type by checking all annotation schemes
                if phase_labeling_schemes:
                    display_only_count = sum(
                        1 for s in phase_labeling_schemes
                        if s.get("annotation_type") == "pure_display"
                    )
                    interactive_count = len(phase_labeling_schemes) - display_only_count

                    if display_only_count > 0 and interactive_count > 0:
                        logger.warning(
                            f"Phase '{phase_name}' has mixed scheme types: "
                            f"{display_only_count} display-only and {interactive_count} interactive. "
                            f"Treating as ANNOTATION phase."
                        )
                        phase_type = UserPhase.ANNOTATION
                    elif display_only_count == len(phase_labeling_schemes):
                        phase_type = UserPhase.INSTRUCTIONS
                    else:
                        phase_type = UserPhase.ANNOTATION
                else:
                    phase_type = UserPhase.ANNOTATION
            else:
                # Legacy format with file and type
                if not "type" in phase or not phase['type']:
                    logger.error(f"Phase {phase_name} does not have a type")
                    raise Exception("Phase %s does not have a type" % phase_name)

                phase_type = UserPhase.fromstr(phase['type'])

                # Training and annotation phases can work without a file
                # They use the main annotation schemes from the config
                if phase_type in [UserPhase.TRAINING, UserPhase.ANNOTATION]:
                    if "file" not in phase or not phase['file']:
                        # Use the main annotation schemes for training/annotation
                        phase_labeling_schemes = config.get('annotation_schemes', [])
                        logger.debug(f"Phase {phase_name} using main annotation schemes")
                    else:
                        # Use the file if specified
                        phase_scheme_fname = get_abs_or_rel_path(phase['file'], config)
                        logger.debug(f"Resolved phase file for {phase_name}: {phase_scheme_fname}")
                        phase_labeling_schemes = get_phase_annotation_schemes(phase_scheme_fname)
                else:
                    # Other phases require a file
                    if not "file" in phase or not phase['file']:
                        logger.error(f"Phase {phase_name} is specified but does not have a file")
                        raise Exception("Phase %s is specified but does not have a file" % phase_name)

                    # Get the phase labeling schemes, being robust to relative or absolute paths
                    phase_scheme_fname = get_abs_or_rel_path(phase['file'], config)
                    logger.debug(f"Resolved phase file for {phase_name}: {phase_scheme_fname}")
                    phase_labeling_schemes = get_phase_annotation_schemes(phase_scheme_fname)

            # Use the default templates unless specified in the phase config
            # Note: Template paths are now hardcoded in front_end.py
            # Only handle custom task_layout if specified
            task_layout_file = None
            if 'task_layout' in phase:
                task_layout_file = phase['task_layout']

            try:
                phase_html_fname = generate_html_from_schematic(
                                                phase_labeling_schemes,
                                                False, False,
                                                phase_name, config,
                                                task_layout_file)
            except KeyError as e:
                logger.error(f"Error generating HTML for phase {phase_name}: {e}")
                raise Exception("Error generating HTML for phase %s: %s" \
                                % (phase_name, str(e)))

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
            for line_no, line in enumerate(f):
                line = line.strip()
                if not line:  # Skip empty lines
                    continue
                try:
                    schemes.append(json.loads(line))
                except json.JSONDecodeError as e:
                    raise ValueError(
                        f"Invalid JSON at line {line_no+1} in {filename}: {e}"
                    ) from e
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
    """Render the text to display to the user in the annotation interface.

    Handles both string and list inputs. When text is a list (for dialogue
    or pairwise comparisons), it formats the list items according to list_as_text config.

    Supported prefix types:
    - alphabet: A. B. C. prefixes
    - number: 1. 2. 3. prefixes
    - bullet: • prefixes
    - none: No prefix (use for dialogue with speaker names in text)

    Additional options:
    - horizontal: Display items side-by-side (for pairwise comparison)
    - alternating_shading: Shade every other turn (for dialogue readability)
    """
    import re

    # Handle list inputs (for dialogue or pairwise comparisons with list_as_text config)
    if isinstance(text, list):
        list_config = config.get("list_as_text", {})
        prefix_type = list_config.get("text_list_prefix_type", "alphabet")
        horizontal = list_config.get("horizontal", False)
        alternating_shading = list_config.get("alternating_shading", False)

        formatted_items = []
        for i, item in enumerate(text):
            # Generate prefix based on type
            if prefix_type == "alphabet":
                prefix = f"<b>{chr(ord('A') + i)}.</b> "
            elif prefix_type == "number":
                prefix = f"<b>{i + 1}.</b> "
            elif prefix_type == "bullet":
                prefix = "<b>•</b> "
            elif prefix_type == "none":
                prefix = ""
            else:
                # Default to alphabet for unknown types
                prefix = f"<b>{chr(ord('A') + i)}.</b> "

            # Recursively process each item
            processed_item = get_displayed_text(item) if isinstance(item, str) else str(item)

            # Apply alternating shading for dialogue readability
            if alternating_shading:
                shade_class = "dialogue-turn-even" if i % 2 == 0 else "dialogue-turn-odd"

                # Try to extract speaker name (text before first colon)
                speaker_match = re.match(r'^([^:]+):\s*(.*)$', processed_item, re.DOTALL)
                if speaker_match:
                    speaker_name = speaker_match.group(1).strip()
                    speaker_text = speaker_match.group(2).strip()
                    # Generate a consistent color index based on speaker name
                    speaker_hash = sum(ord(c) for c in speaker_name) % 6
                    # Use span with display:block style (spans are in sanitizer allowlist)
                    formatted_items.append(
                        f'<span class="dialogue-turn {shade_class}" style="display:block;">'
                        f'<b class="dialogue-speaker speaker-color-{speaker_hash}">{speaker_name}:</b> '
                        f'{prefix}{speaker_text}</span>'
                    )
                else:
                    # No speaker detected, use simple format
                    formatted_items.append(
                        f'<span class="dialogue-turn {shade_class}" style="display:block;">{prefix}{processed_item}</span>'
                    )
            else:
                formatted_items.append(f"{prefix}{processed_item}")

        # Join based on layout type
        if horizontal:
            # Horizontal layout for pairwise comparison
            cell_width = 100 // len(formatted_items) if formatted_items else 100
            cells = [
                f'<span class="pairwise-cell" style="width:{cell_width}%;display:inline-block;vertical-align:top;padding:10px;box-sizing:border-box;">{item}</span>'
                for item in formatted_items
            ]
            text = '<span class="pairwise-container" style="display:flex;gap:20px;">' + ''.join(cells) + '</span>'
        elif alternating_shading:
            # Already wrapped in divs, join without extra breaks
            text = ''.join(formatted_items)
        else:
            # Vertical layout with double line breaks
            text = "<br/><br/>".join(formatted_items)
        return text

    # Normalize text for consistent positioning (matches client-side normalization)
    # Remove non-printable characters and normalize whitespace
    text = re.sub(r'[^\x20-\x7E\n]', '', text)
    text = re.sub(r'[ \t]+', ' ', text)  # Normalize horizontal whitespace only
    text = text.strip()

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
    Only enforce session validation for protected routes.
    """
    # Skip session validation in debug mode
    if config.get("debug", False):
        return None

    # Allow unauthenticated access to these endpoints
    allowed_paths = [
        '/', '/auth', '/register', '/static/', '/favicon.ico', '/robots.txt', '/health', '/api/', '/api/instance/', '/api/instances', '/api/config', '/api/status', '/api/heartbeat'
    ]
    path = request.path
    if any(path == allowed or path.startswith(allowed) for allowed in allowed_paths):
        return None

    if not is_session_valid():
        session.clear()  # Clear the session
        return redirect(url_for('home'))  # Redirect to home page (login/register)

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
    logger.debug(f"=== MOVE_TO_NEXT_INSTANCE START ===")
    logger.debug(f"User ID: {user_id}")

    user_state = get_user_state(user_id)
    logger.debug(f"Before navigation - current_instance_index: {user_state.get_current_instance_index()}")
    logger.debug(f"Before navigation - instance_id_ordering: {user_state.instance_id_ordering}")

    # If the user is at the end of the list, try to assign instances to the user
    if user_state.is_at_end_index():
        logger.debug(f"User {user_id} is at the end of the list, assigning new instances")
        num_assigned = get_item_state_manager().assign_instances_to_user(user_state)
        logger.debug(f"Assigned {num_assigned} new instances to user {user_id}")

    result = user_state.go_forward()
    logger.debug(f"After navigation - current_instance_index: {user_state.get_current_instance_index()}")
    logger.debug(f"Navigation result: {result}")

    logger.debug(f"=== MOVE_TO_NEXT_INSTANCE END ===")
    return result

def go_to_id(user_id: str, instance_index: int):
    '''Causes the user's view to change to the Item at the given index.'''
    user_state = get_user_state(user_id)
    user_state.go_to_index(int(instance_index))

def get_current_page_html(config, username):
    """
    Returns the HTML for the current page that the user is on.

    For phase pages (consent, instructions, etc.), this provides minimal
    context variables needed by the shared template structure.
    """
    user_state = get_user_state(username)
    phase, page = user_state.get_current_phase_and_page()

    usm = get_user_state_manager()
    html_fname = usm.get_phase_html_fname(phase, page)

    # Provide context variables needed by the template
    # For phase pages, many annotation-specific fields can be empty/default
    context = {
        'username': username,
        'instance': '',
        'instance_plain_text': '',
        'instance_id': '',
        'finished': 0,
        'total_count': user_state.get_assigned_instance_count() if hasattr(user_state, 'get_assigned_instance_count') else 0,
        'ui_config': config.get('ui_config', {}),
    }
    return render_template(html_fname, **context)

def _is_user_adjudicator(username: str) -> bool:
    """Check if a user is an authorized adjudicator."""
    adj_mgr = get_adjudication_manager()
    if adj_mgr and adj_mgr.adj_config.enabled:
        return adj_mgr.is_adjudicator(username)
    return False


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

    # Extract pre-annotation data if quality control is enabled
    pre_annotation_data = None
    qc_manager = get_quality_control_manager()
    if qc_manager:
        pre_annotation_data = qc_manager.extract_pre_annotations(instance_id, item.get_data())

    # DEBUG: Add detailed logging
    logger.debug(f"=== RENDER_PAGE_WITH_ANNOTATIONS START ===")
    logger.debug(f"Username: {username}")
    logger.debug(f"User state current_instance_index: {user_state.get_current_instance_index()}")
    logger.debug(f"User state instance_id_ordering: {user_state.instance_id_ordering}")
    logger.debug(f"Current instance ID: {instance_id}")

    # print('instance_id: ', instance_id)

    # directly display the prepared displayed_text
    text = item.get_data()["displayed_text"]
    # print('displayed_text: ', text)

    # Save the original plain text BEFORE any span rendering
    # This is needed for the frontend to calculate correct span positions
    # The data-original-text attribute must contain plain text (no HTML span tags)
    # while the DOM content contains the rendered HTML with span highlights
    # Strip HTML tags to get actual plain text for position calculations
    import re as re_module
    original_plain_text = re_module.sub(r'<[^>]+>', '', text)
    # Also normalize whitespace
    original_plain_text = re_module.sub(r'\s+', ' ', original_plain_text).strip()

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
    # replacing {{variable_name}} with the associated text for keyword arguments

        # Calculate progress counter values
    # Use the total number of items that will be assigned to the user
    total_count = get_item_state_manager().get_total_assignable_items_for_user(get_user_state(username))

    # Get UI configuration from config
    ui_config = config.get("ui", {})

    # Detect if any annotation scheme is video_annotation type
    # This is used to customize the display (show "Video to Annotate:" instead of "Text to Annotate:")
    has_video_annotation = any(
        scheme.get("annotation_type") == "video_annotation"
        for scheme in config.get("annotation_schemes", [])
    )

    # Detect if any annotation scheme is audio_annotation type
    # This is used to customize the display (show "Audio to Annotate:" instead of "Text to Annotate:")
    has_audio_annotation = any(
        scheme.get("annotation_type") == "audio_annotation"
        for scheme in config.get("annotation_schemes", [])
    )

    # Detect if any annotation scheme is image_annotation type
    # This is used to customize the display (show "Image to Annotate:" instead of "Text to Annotate:")
    has_image_annotation = any(
        scheme.get("annotation_type") == "image_annotation"
        for scheme in config.get("annotation_schemes", [])
    )

    # Check if AI support is enabled (for conditional loading of visual_ai_assistant.js)
    ai_enabled = config.get("ai_support", {}).get("enabled", False)

    # Get pre-annotation configuration
    pre_annotation_config = {}
    if qc_manager:
        pre_annotation_config = qc_manager.get_pre_annotation_config()

    # Check if instance_display is configured (new explicit display mode)
    has_instance_display = "instance_display" in config
    display_html = ""
    display_template_vars = {}

    if has_instance_display:
        try:
            display_renderer = get_instance_display_renderer(config)
            display_template_vars = display_renderer.get_template_variables(item.get_data())
            display_html = display_template_vars.get("display_html", "")
            logger.debug(f"Instance display rendered: {len(display_html)} chars")
        except Exception as e:
            logger.error(f"Error rendering instance display: {e}")
            has_instance_display = False  # Fall back to legacy mode

    rendered_html = render_template(
        html_file,
        username=username,
        # This is what instance the user is currently on (may contain span HTML)
        instance=text,
        # Original plain text without span HTML (for data-original-text attribute)
        instance_plain_text=original_plain_text,
        instance_obj=item,
        instance_id=instance_id,
        instance_index=user_state.get_current_instance_index(),
        finished=get_user_state(username).get_annotation_count(),
        total_count=total_count,
        alert_time_each_instance=config.get("alert_time_each_instance", 10000000),
        statistics_nav=all_statistics,
        var_elems=var_elems_html,
        custom_js=custom_js,
        # Pass annotation schemes to the template
        annotation_schemes=config["annotation_schemes"],
        annotation_task_name=config["annotation_task_name"],
        debug=config.get("debug", False),
        ui_config=ui_config,
        has_video_annotation=has_video_annotation,
        has_audio_annotation=has_audio_annotation,
        has_image_annotation=has_image_annotation,
        ai_enabled=ai_enabled,
        # Pre-annotation data for model predictions
        pre_annotations=pre_annotation_data,
        pre_annotation_config=pre_annotation_config,
        # Instance display (new explicit display mode)
        has_instance_display=has_instance_display,
        display_html=display_html,
        display_fields=display_template_vars.get("display_fields", {}),
        display_raw=display_template_vars.get("display_raw", {}),
        span_targets=display_template_vars.get("span_targets", []),
        multi_span_mode=display_template_vars.get("multi_span_mode", False),
        # Adjudication: show link for adjudicators
        is_adjudicator=_is_user_adjudicator(username),
        # ai=ai_hints,
        **kwargs
    )

    # Parse the page so we can programmatically reset the annotation state
    # to what it was before
    soup = BeautifulSoup(rendered_html, "html.parser")

    # If the user has annotated this before, walk the DOM and fill out what they
    # did
    annotations = get_annotations_for_user_on(username, instance_id)

    # If no annotations yet, check for pre-annotations (model predictions)
    if annotations is None and pre_annotation_data:
        logger.debug(f"Applying pre-annotations for instance {instance_id}")
        scheme_dict = {}
        annotations = defaultdict(dict)
        for it in config['annotation_schemes']:
            if it['annotation_type'] in ['radio', 'multiselect']:
                it['label2value'] = {(l if type(l) == str else l['name']):str(i+1) for i,l in enumerate(it['labels'])}
            scheme_dict[it['name']] = it

        for schema_name, predicted_value in pre_annotation_data.items():
            if schema_name not in scheme_dict:
                logger.debug(f"Pre-annotation schema {schema_name} not found in annotation schemes")
                continue

            scheme = scheme_dict[schema_name]
            if scheme['annotation_type'] in ['radio', 'multiselect']:
                # predicted_value should be a label name
                if isinstance(predicted_value, str) and predicted_value in scheme.get('label2value', {}):
                    annotations[schema_name][predicted_value] = scheme['label2value'][predicted_value]
                elif isinstance(predicted_value, list):
                    # Multi-select: multiple values
                    for val in predicted_value:
                        if val in scheme.get('label2value', {}):
                            annotations[schema_name][val] = scheme['label2value'][val]
            elif scheme['annotation_type'] in ['text']:
                if "labels" not in scheme:
                    annotations[schema_name]['text_box'] = str(predicted_value)
            elif scheme['annotation_type'] in ['likert', 'slider', 'number']:
                annotations[schema_name]['slider'] = str(predicted_value)
            else:
                logger.debug(f"Pre-annotation not yet supported for {scheme['annotation_type']}")

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
                logger.warning('Label suggestions not supported for annotation_type %s, please submit a github issue to get support' % scheme_dict[s['name']]['annotation_type'])
    logger.debug(f"annotations: {annotations}")
    if annotations is not None:
        # Reset the state
        for schema_name, label_dict in annotations.items():
            # this needs to be fixed, there is a chance that we get incorrect type
            if not isinstance(label_dict, dict):
                logger.warning(f"Skipping {schema_name}: Expected dict but got {type(label_dict)} -> {label_dict}")
                continue

            for label_name, value in label_dict.items():
                schema = schema_name
                label = label_name
                name = schema + ":::" + label

                # Find all the input, select, and textarea tags with this name
                # (which was annotated) and figure out which one to fill in
                input_fields = soup.find_all(["input", "select", "textarea"], {"name": name})

                # For radio buttons, the name attribute is just the schema (not schema:::label)
                # because all radio buttons in a group must have the same name for HTML mutual exclusivity
                # So we also search by schema and label_name attributes
                if not input_fields:
                    input_fields = soup.find_all(
                        ["input"],
                        {"schema": schema, "label_name": label}
                    )

                # For image/audio/video annotation data, the hidden input has name=schema_name
                # and the label is "_data"
                if not input_fields and label == "_data":
                    input_fields = soup.find_all(
                        ["input"],
                        {"name": schema, "class": "annotation-data-input"}
                    )
                    logger.debug(f"Looking for annotation-data-input with name={schema}, found {len(input_fields)}")

                for input_field in input_fields:

                    if input_field is None:
                        logger.debug(f"No input for {name}")
                        continue

                    # If it's a slider, set the value for the slider
                    if input_field.get('type') == 'range' and name.endswith(':::slider'):
                        input_field['value'] = value
                        continue

                    if input_field.get('type') == 'checkbox' or input_field.get('type') == 'radio':
                        if value:
                            # For radio buttons, only check if the value matches
                            # (multiple radios share the same schema/label_name but have different values)
                            if input_field.get('type') == 'radio':
                                if input_field.get('value') == value:
                                    input_field['checked'] = True
                            else:
                                # For checkboxes, set checked
                                input_field['checked'] = True

                    # Handle text inputs - set value attribute
                    if input_field.get('type') == 'text':
                        if isinstance(value, str):
                            input_field['value'] = value

                    # Handle number inputs - set value attribute
                    if input_field.get('type') == 'number':
                        input_field['value'] = str(value)

                    # Handle textareas - set content between tags (not value attribute)
                    # Textareas don't have a type attribute, check tag name instead
                    if input_field.name == 'textarea':
                        if isinstance(value, str):
                            input_field.string = value

                    # Handle hidden inputs for image/audio/video annotation data
                    if input_field.get('type') == 'hidden':
                        if isinstance(value, str):
                            input_field['value'] = value
                            # Mark this input as server-set to distinguish from browser-cached values
                            input_field['data-server-set'] = 'true'
                            logger.debug(f"Set hidden input {name} value (length: {len(value)}) with server-set flag")

                    # Handle select elements - set the 'selected' attribute on matching option
                    if input_field.name == 'select':
                        if isinstance(value, str):
                            # Find the option with the matching value and set it as selected
                            options = input_field.find_all("option", {"value": value})
                            if options:
                                options[0]["selected"] = "selected"
                                logger.debug(f"Set select {name} option to {value}")
                            else:
                                logger.debug(f"No option found with value {value} for select {name}")

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
                logger.warning("Unsupported suggested label type %s, please check your input data" % type(suggested_labels))
                continue

            if not schema.get('label_suggestions') in ['highlight', 'prefill']:
                logger.warning('The style of suggested labels is not defined, please check your configuration file.')
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
    logger.debug(f"AI hints text: {text}")
    description = config["annotation_schemes"][0]["description"]
    annotation_type = config["annotation_schemes"][0]["annotation_type"]
    logger.debug(f"AI hints description: {description}")
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
        result = response.json()['response']
        logger.debug(f"AI hints response: {result}")
        return result
    except requests.exceptions.ConnectionError:
        logger.warning("AI hints service not available (Ollama not running)")
        return "AI hints are currently unavailable. Please proceed with manual annotation."
    except requests.exceptions.Timeout:
        logger.warning("AI hints service timeout")
        return "AI hints service is slow to respond. Please proceed with manual annotation."
    except Exception as e:
        logger.error(f"Error getting AI hints: {e}")
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

    # Get UI configuration from config
    ui_config = config.get("ui", {})

    return render_template(
        html_fname,
        instance_id=instance_id,
        instance_data=item_data,
        annotations=annotations,
        span_annotations=span_annotations,
        progress=progress,
        username=username,
        ui_config=ui_config
    )

def randomize_options(soup, legend_names, seed):
    random.seed(seed)

    # Find all fieldsets in the soup
    fieldsets = soup.find_all('fieldset')
    if not fieldsets:
        logger.debug("No fieldsets found.")
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
                logger.debug("Table not found within the fieldset.")
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
        logger.debug("No matching legends found within any fieldset.")

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
    DEPRECATED: This function is no longer called during navigation.

    Annotations are now saved in real-time via /updateinstance endpoint when users
    interact with checkboxes, radio buttons, etc. This ensures proper timing tracking
    for behavioral data analysis.

    This function is kept for backward compatibility but should not be used in new code.
    Use add_label_annotation() via /updateinstance instead.

    Original purpose: Parses the state of the HTML form (what the user did to the
    instance) and updates the state of the instance's annotations accordingly.
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
    span_annotations = None  # Changed from [] to None to preserve existing spans during navigation
    if "span-annotation" in form:
        span_annotation_html = form["span-annotation"]
        span_text, span_annotations = parse_html_span_annotation(span_annotation_html)

    did_change = user_state.set_annotation(
        instance_id, schema_to_label_to_value, span_annotations, behavioral_data_dict
    )
    # update the behavioral information regarding time only when the annotations are changed
    if did_change:
        # Include keyword highlight state in behavioral data for research tracking
        keyword_state = user_state.get_keyword_highlight_state(instance_id)
        if keyword_state:
            behavioral_data_dict['keyword_highlights_shown'] = keyword_state.get('highlights', [])
        user_state.instance_id_to_behavioral_data[instance_id] = behavioral_data_dict
    return did_change


def get_annotations_for_user_on(username, instance_id):
    """
    Returns the label-based annotations made by this user on the instance.

    Handles two data formats:
    1. Label objects as keys: {Label("schema", "label"): value}
       - Created by add_label_annotation() via /updateinstance endpoint
    2. Nested string dicts: {"schema": {"label": value}}
       - Created by set_annotation() via /annotate navigation
    """
    # Normalize instance_id to string for consistent key lookup
    instance_id = str(instance_id)

    user_state = get_user_state(username)
    logger.debug(f"instance_id: {instance_id}")
    raw_annotations = user_state.get_label_annotations(instance_id)

    # Process the raw annotations into the expected format
    processed_annotations = {}
    for label, value in raw_annotations.items():
        # Check for Label object - the Label class uses 'schema' and 'name' attributes
        # with get_schema() and get_name() getter methods
        if hasattr(label, 'get_schema') and hasattr(label, 'get_name'):
            # Format 1: Label object as key (from add_label_annotation via /updateinstance)
            schema_name = label.get_schema()
            label_name = label.get_name()
            if schema_name not in processed_annotations:
                processed_annotations[schema_name] = {}
            processed_annotations[schema_name][label_name] = value
        elif isinstance(label, str) and isinstance(value, dict):
            # Format 2: Nested dict format {"schema": {"label": value}}
            # (legacy format from set_annotation, kept for backward compatibility)
            schema_name = label
            if schema_name not in processed_annotations:
                processed_annotations[schema_name] = {}
            for label_name, label_value in value.items():
                processed_annotations[schema_name][label_name] = label_value
        else:
            # Unknown format - log and skip
            logger.warning(f"Skipping unknown annotation format: key={label}, value={value}")
            continue

    return processed_annotations


def get_span_annotations_for_user_on(username, instance_id):
    """
    Returns the span annotations made by this user on the instance.
    """
    logger.debug(f"=== GET_SPAN_ANNOTATIONS_FOR_USER_ON START ===")
    logger.debug(f"Username: {username}")
    logger.debug(f"Instance ID: {instance_id}")

    # Normalize instance_id to string for consistent key lookup
    instance_id = str(instance_id)
    logger.debug(f"Normalized Instance ID: {instance_id}")

    user_state = get_user_state(username)
    logger.debug(f"User state: {user_state}")

    if not user_state:
        logger.warning(f"User state not found for user: {username}")
        return []

    # DEBUG: Check if this instance has any span annotations at all
    if hasattr(user_state, 'instance_id_to_span_to_value'):
        logger.debug(f"User state instance_id_to_span_to_value keys: {list(user_state.instance_id_to_span_to_value.keys())}")

        if instance_id in user_state.instance_id_to_span_to_value:
            instance_spans = user_state.instance_id_to_span_to_value[instance_id]
            logger.debug(f"Spans for instance {instance_id}: {instance_spans}")

            # DEBUG: Show each span in detail
            for span, value in instance_spans.items():
                logger.debug(f"Span: {span}, Value: {value}")
                if hasattr(span, 'get_schema'):
                    logger.debug(f"  Schema: {span.get_schema()}")
                    logger.debug(f"  Name: {span.get_name()}")
                    logger.debug(f"  Start: {span.get_start()}")
                    logger.debug(f"  End: {span.get_end()}")
                    logger.debug(f"  ID: {span.get_id()}")
        else:
            logger.debug(f"No spans found for instance {instance_id}")

    span_annotations_dict = user_state.get_span_annotations(instance_id)
    logger.debug(f"Raw span annotations from user state: {span_annotations_dict}")

    # Convert dictionary to list of SpanAnnotation objects
    span_annotations = list(span_annotations_dict.keys()) if span_annotations_dict else []
    logger.debug(f"Converted to list: {span_annotations}")

    # Log details of each span
    for span in span_annotations:
        logger.debug(f"[DEBUG SPAN] schema={span.get_schema()} label={span.get_name()} start={span.get_start()} end={span.get_end()} id={span.get_id()}")

    logger.debug(f"=== GET_SPAN_ANNOTATIONS_FOR_USER_ON END ===")
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
    # Use a random secret key if sessions shouldn't persist, otherwise use the configured one
    if config.get("persist_sessions", False):
        secret_key = config.get("secret_key") or os.environ.get("POTATO_SECRET_KEY")
        if not secret_key:
            raise ValueError(
                "persist_sessions is enabled but no secret_key is configured. "
                "Set 'secret_key' in your config file or POTATO_SECRET_KEY environment variable."
            )
        app.secret_key = secret_key
    else:
        # Generate a random secret key to ensure sessions don't persist between restarts
        import secrets
        app.secret_key = secrets.token_hex(32)

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

    # Initialize the app with explicit static folder configuration
    static_folder = os.path.join(cur_program_dir, 'static')
    app = Flask(__name__, static_folder=static_folder)

    # Configure Jinja2 to look in both main templates and generated templates directories
    real_templates_dir = os.path.join(cur_program_dir, 'templates')
    generated_templates_dir = os.path.join(real_templates_dir, 'generated')

    # Ensure the generated directory exists
    if not os.path.exists(generated_templates_dir):
        os.makedirs(generated_templates_dir, exist_ok=True)

    # Add the generated directory to the template search path
    from jinja2 import ChoiceLoader, FileSystemLoader
    app.jinja_loader = ChoiceLoader([
        FileSystemLoader(real_templates_dir),
        FileSystemLoader(generated_templates_dir)
    ])

    # Register HTML sanitization filters for XSS protection
    from potato.server_utils.html_sanitizer import register_jinja_filters
    register_jinja_filters(app)

    # Configure the app
    configure_app(app)

    # Add context processor for debug settings and common config values
    @app.context_processor
    def inject_template_context():
        """Inject debug settings and common config values into all templates."""
        from potato.logging_config import is_ui_debug_enabled, is_server_debug_enabled
        return {
            'ui_debug': is_ui_debug_enabled(),
            'server_debug': is_server_debug_enabled(),
            'debug_mode': config.get('debug', False),
            'debug_phase': config.get('debug_phase'),
            # Add common config values needed by templates
            'annotation_task_name': config.get('annotation_task_name', 'Annotation Task'),
        }

    return app


def _init_waveform_service(config: dict) -> None:
    """
    Initialize the WaveformService for audio annotation if the config
    includes audio_annotation schemes.

    Args:
        config: The application configuration dictionary
    """
    # Check if any audio_annotation schemes are configured
    has_audio_annotation = False
    annotation_schemes = config.get('annotation_schemes', [])
    for scheme in annotation_schemes:
        if scheme.get('annotation_type') == 'audio_annotation':
            has_audio_annotation = True
            break

    if not has_audio_annotation:
        logger.debug("No audio_annotation schemes found, skipping WaveformService initialization")
        return

    # Get waveform configuration
    audio_config = config.get('audio_annotation', {})
    task_dir = config.get('task_dir', '.')

    # Default cache directory
    cache_dir = audio_config.get('waveform_cache_dir')
    if not cache_dir:
        cache_dir = os.path.join(task_dir, 'waveform_cache')

    # Make cache_dir absolute if relative
    if not os.path.isabs(cache_dir):
        cache_dir = os.path.join(task_dir, cache_dir)

    # Get other configuration options
    look_ahead = audio_config.get('waveform_look_ahead', 5)
    cache_max_size = audio_config.get('waveform_cache_max_size', 100)
    client_fallback_max_duration = audio_config.get('client_fallback_max_duration', 1800)

    try:
        from potato.server_utils.waveform_service import init_waveform_service, get_waveform_service

        waveform_service = init_waveform_service(
            cache_dir=cache_dir,
            look_ahead=look_ahead,
            cache_max_size=cache_max_size,
            client_fallback_max_duration=client_fallback_max_duration
        )

        if waveform_service.is_available:
            logger.info(f"WaveformService initialized with audiowaveform tool (cache: {cache_dir})")
        else:
            logger.warning("WaveformService initialized but audiowaveform tool not available. "
                          "Client-side waveform generation will be used as fallback.")

        # Register cleanup handler
        import atexit
        def cleanup_waveform_service():
            service = get_waveform_service()
            if service:
                service.stop_background_precompute()
                logger.info("WaveformService background precompute stopped")
        atexit.register(cleanup_waveform_service)

    except Exception as e:
        logger.error(f"Failed to initialize WaveformService: {e}")
        logger.warning("Audio annotation will use client-side waveform generation only")


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

    # Handle require_no_password (inverse of require_password) for backwards compatibility
    # This is commonly used in Prolific/MTurk configs
    if config.get("require_no_password", False):
        config["require_password"] = False
        logger.debug("Password requirement disabled via require_no_password config")

    # For URL-direct login, automatically disable password requirement
    login_config = config.get('login', {})
    if login_config.get('type') in ['url_direct', 'prolific']:
        config["require_password"] = False
        logger.debug(f"Password requirement disabled for {login_config.get('type')} login type")

    # Override port from command line if specified
    if args.port is not None:
        config["port"] = args.port
        logger.debug(f"Port set from command line: {args.port}")

    # Apply persist_sessions flag from command line
    config["persist_sessions"] = args.persist_sessions
    logger.debug(f"Session persistence set from command line: {args.persist_sessions}")

    # --- Add support for random seed ---
    # Admins can set 'random_seed' in config YAML to control assignment randomness (default 1234)
    if "random_seed" not in config:
        config["random_seed"] = 1234
    logger.info(f"Assignment random seed set to: {config['random_seed']}")
    # -----------------------------------

    # Set up centralized logging with appropriate verbosity
    setup_logging(
        verbose=config.get("verbose", False),
        debug=config.get("debug", False) or config.get("very_verbose", False),
        debug_log=config.get("debug_log"),
        log_dir=config.get("output_annotation_dir"),
    )

    # Log debug phase setting if specified
    if config.get("debug_phase"):
        logger.info(f"Debug phase set to: {config['debug_phase']}")

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

    # Initialize AI prompt and wrapper BEFORE load_all_data() because
    # template generation needs get_ai_wrapper() to return the AI help div
    if config.get("ai_support", {}).get("enabled", False):
        logger.info("Initializing AI prompt and wrapper...")
        init_ai_prompt(config)
        init_dynamic_ai_help()

    load_all_data(config)

    # Initialize AI cache manager AFTER load_all_data() because
    # it needs item_state_manager to be fully initialized for warmup
    if config.get("ai_support", {}).get("enabled", False):
        logger.info("Initializing AI cache manager...")
        init_ai_cache_manager()
        logger.info("AI support initialized successfully")

    # Initialize quality control manager if any QC features are enabled
    qc_enabled = (
        config.get('attention_checks', {}).get('enabled', False) or
        config.get('gold_standards', {}).get('enabled', False) or
        config.get('pre_annotation', {}).get('enabled', False)
    )
    if qc_enabled:
        task_dir = config.get('task_dir', os.path.dirname(config.get('config_file', '')))
        init_quality_control_manager(config, task_dir)
        logger.info("Quality control manager initialized")

    # Initialize adjudication manager if configured
    if config.get('adjudication', {}).get('enabled', False):
        init_adjudication_manager(config)
        logger.info("Adjudication manager initialized")

    # Initialize ExpertiseManager for dynamic category assignment
    category_assignment = config.get('category_assignment', {})
    dynamic_config = category_assignment.get('dynamic', {})
    if dynamic_config.get('enabled', False):
        expertise_manager = init_expertise_manager(config)
        expertise_manager.start_background_worker()
        logger.info("Dynamic category expertise enabled with background worker")

        # Register cleanup handler for expertise manager
        import atexit
        def cleanup_expertise_manager():
            em = get_expertise_manager()
            if em:
                em.stop_background_worker()
                logger.info("Expertise manager background worker stopped")
        atexit.register(cleanup_expertise_manager)

    # Initialize ICL labeler for AI-assisted labeling if configured
    icl_config = config.get('icl_labeling', {})
    if icl_config.get('enabled', False):
        from potato.ai.icl_labeler import init_icl_labeler, get_icl_labeler
        icl_labeler = init_icl_labeler(config)
        icl_labeler.start_background_worker()
        logger.info("ICL (In-Context Learning) labeler enabled with background worker")

        # Register cleanup handler for ICL labeler
        import atexit
        def cleanup_icl_labeler():
            labeler = get_icl_labeler()
            if labeler:
                labeler.stop_background_worker()
                labeler.save_state()
                logger.info("ICL labeler background worker stopped and state saved")
        atexit.register(cleanup_icl_labeler)

    # Initialize directory watcher if configured
    if "data_directory" in config:
        from potato.directory_watcher import init_directory_watcher, get_directory_watcher
        dw = init_directory_watcher(config)
        if dw:
            # Load all files from the directory
            count = dw.load_directory()
            logger.info(f"Loaded {count} instances from data_directory: {config['data_directory']}")

            # Start watching if enabled
            if config.get("watch_data_directory", False):
                dw.start_watching()
                logger.info(f"Directory watching enabled (poll interval: {config.get('watch_poll_interval', 5.0)}s)")

            # Register cleanup handler
            import atexit
            def cleanup_directory_watcher():
                watcher = get_directory_watcher()
                if watcher:
                    watcher.stop()
                    logger.info("Directory watcher stopped")
            atexit.register(cleanup_directory_watcher)

    # Initialize WaveformService for audio annotation if configured
    _init_waveform_service(config)

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
    elif args.mode == 'migrate':
        logger.info("Starting config migration")
        from potato.migrate_cli import main as migrate_main
        # Pass arguments to migrate CLI
        migrate_args = [args.config_file]
        if args.to_v2:
            migrate_args.append("--to-v2")
        if args.output_file:
            migrate_args.extend(["--output", args.output_file])
        if args.in_place:
            migrate_args.append("--in-place")
        if args.dry_run:
            migrate_args.append("--dry-run")
        if args.quiet:
            migrate_args.append("--quiet")
        sys.exit(migrate_main(migrate_args))

    logger.info("Annotation platform shutdown complete")


# Main entry point
if __name__ == "__main__":
    main()
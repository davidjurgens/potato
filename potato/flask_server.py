"""
Flask Server Driver

The main Flask server implementation for the annotation platform.
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
    init_quality_control_manager, get_quality_control_manager,
    clear_quality_control_manager, count_dataset_items
)
from potato.adjudication import (
    init_adjudication_manager, get_adjudication_manager, clear_adjudication_manager
)
from potato.diversity_manager import (
    init_diversity_manager, get_diversity_manager, clear_diversity_manager
)
from potato.knowledge_base import init_kb_manager

from potato.solo_mode import init_solo_mode_manager, get_solo_mode_manager
from potato.solo_mode.routes import solo_mode_bp

from potato.qda_mode import init_qda_mode_manager

from potato.server_utils.arg_utils import arguments
from potato.server_utils.config_module import init_config, config
from potato.server_utils.schemas.span import render_span_annotations
from potato.server_utils.prolific_apis import ProlificStudy
from potato.server_utils.mturk_apis import init_mturk_hit, get_mturk_hit
from potato.server_utils.json import easy_json
from potato.server_utils.instance_display import InstanceDisplayRenderer, get_instance_display_renderer
from potato.server_utils.transcripts.binding import enrich_record as enrich_transcript_record

# This allows us to create an AI endpoint for the system to interact with as needed (if configured)
from potato.ai.ai_endpoint import get_ai_endpoint

# AI support initialization
from potato.ai.ai_prompt import init_ai_prompt
from potato.ai.ai_cache import init_ai_cache_manager, get_ai_cache_manager
from potato.ai.ai_help_wrapper import init_dynamic_ai_help

# Initialize Flask app
app = Flask(__name__)
app.register_blueprint(solo_mode_bp)
from potato.judge_calibration.routes import judge_calibration_bp
app.register_blueprint(judge_calibration_bp)
# Note: qda_mode_bp is registered on the *served* app in
# potato.routes.configure_routes (the module-level `app` here is discarded
# and rebuilt by create_app), so it is intentionally not registered here.

# Web agent recording and proxy blueprints (registered lazily in configure_app
# only when web_agent display types are configured)

# Secret key will be set in configure_app() from config

# Use centralized logging configuration
from potato.logging_config import get_logger, setup_logging
logger = get_logger(__name__)

_FRONTEND_TEMPLATE_TEXT_CACHE: dict[str, tuple[float, str]] = {}

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

#: How long a signed-in session may sit idle before it is cleared. Overridable
#: with ``session_timeout_minutes``; eight hours is one working day, which is
#: the unit an annotation shift is actually measured in.
#:
#: This used to be one minute, and nobody was ever signed out, because the gate
#: below never ran (see :func:`before_request`). Two defects cancelling: the
#: moment the gate was fixed, a one-minute timeout would have evicted every
#: annotator mid-item.
DEFAULT_SESSION_TIMEOUT_MINUTES = 8 * 60
SESSION_TIMEOUT = timedelta(minutes=DEFAULT_SESSION_TIMEOUT_MINUTES)


def get_session_timeout() -> timedelta:
    """The configured idle-session timeout."""
    try:
        minutes = float(config.get("session_timeout_minutes",
                                   DEFAULT_SESSION_TIMEOUT_MINUTES))
    except (TypeError, ValueError):
        return SESSION_TIMEOUT
    return timedelta(minutes=minutes) if minutes > 0 else SESSION_TIMEOUT


def _read_cached_template_text(path: str) -> str:
    """Read a generated template file with a lightweight mtime cache."""
    if not path:
        return ""

    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return ""

    cached = _FRONTEND_TEMPLATE_TEXT_CACHE.get(path)
    if cached and cached[0] == mtime:
        return cached[1]

    try:
        with open(path, "rt", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return ""

    _FRONTEND_TEMPLATE_TEXT_CACHE[path] = (mtime, text)
    return text


def _resolve_generated_template_path(html_file: str) -> str:
    """Resolve ``config['site_file']`` (a bare filename) to the absolute path of
    the generated template on disk.

    The generated template lives under ``<site_dir>/generated/<site_file>``, but
    ``config['site_file']`` is stored as just the filename (Jinja resolves it via
    its template search path). The server ``chdir``s into ``task_dir`` at startup,
    so reading the bare name with ``open()`` would fail and silently disable every
    page-template-gated frontend asset. Resolving against the (absolute) site_dir
    makes asset detection work regardless of the process CWD.
    """
    if not html_file:
        return html_file
    if os.path.isabs(html_file) and os.path.exists(html_file):
        return html_file
    from potato.server_utils.generated_templates import (
        resolve_generated_templates_dir)

    site_dir = config.get("site_dir") or ""
    if site_dir:
        candidate = os.path.join(
            resolve_generated_templates_dir(site_dir, create=False), html_file)
        if os.path.exists(candidate):
            return candidate
    return html_file


# Authoritative mapping from asset key to the HTML markers that trigger loading.
# Tests verify these markers appear in the actual schema/display generators,
# so adding a new generator or renaming a CSS class will cause a test failure
# rather than a silent asset-loading miss.
FRONTEND_ASSET_MARKERS: dict[str, tuple[str, ...]] = {
    "image_annotation": ("image-annotation-container",),
    # Interactive segmentation, keyed on the tool button the schema renders.
    # Gated separately from image_annotation because the ONNX runtime is a
    # 13 MB fetch that a project drawing only boxes should never pay for.
    "segmentation": ('data-tool="sam"',),
    # Text-prompt detection, keyed on the prompt box. Separate from
    # `segmentation` because the two models are independent — a project can
    # have either, both, or neither — and this one is a 145 MB fetch.
    "text_prompt": ("data-text-prompt",),
    # Deep zoom. Gated separately from image_annotation because OpenSeadragon
    # is a 277 KB download that a project annotating ordinary photographs must
    # not pay for.
    "deepzoom": ("deepzoom-host",),
    # 3D point cloud annotation. Gated separately from image_annotation
    # because three.js is a 670 KB download that a 2D project must not pay for.
    "spatial_annotation": ("pointcloud-annotation-container",),
    # Depth maps. A display type rather than a schema, so the marker comes from
    # the display's own wrapper.
    "depth_map": ("depth-display",),
    # Embodied robot episodes: synchronized video plus time-series lanes.
    "episode_annotation": ("episode-annotation-container",),
    # World-model rollout evaluation: frame-locked video panels.
    "rollout_evaluation": ("rollout-eval-container",),
    # Grounding evaluation. Needs the image annotation assets too, but those
    # are gated on their own marker and a grounding project always renders an
    # image_annotation schema beside this one.
    "grounding_eval": ("grounding-eval-container",),
    "region_caption": ("region-caption-container",),
    "audio_annotation": ("audio-annotation-container",),
    "video_annotation": ("video-annotation-container",),
    "span_link": ("span-link-container",),
    "event_annotation": ("event-annotation-container",),
    "multi_document_event": ('data-annotation-type="multi_document_event"', "mde-container"),
    "coreference": ('data-annotation-type="coreference"', "coref-chain-panel"),
    # The display emits `conv-tree`; the `tree_annotation` *scheme* emits
    # `tree-ann-container` and needs the same script. Keyed on the display alone,
    # a tree_annotation scheme in a project whose display was something else
    # loaded no JS at all -- no node selection, no path building, nothing.
    "conversation_tree": ("conv-tree", "tree-ann-container"),
    # Per-segment/per-node question forms. Audio and video emit this template
    # for `segment_schemes`, tree_annotation for `node_scheme`.
    "segment_questions": ("segment-questions-template",),
    "tracking": ("tracking-panel", "tracking-overlay", "tracking-controls-group"),
    "triage": ('class="annotation-form triage"', 'data-annotation-type="triage"', "triage-container"),
    "tiered_annotation": ("tiered-annotation-container",),
    "document_bbox": ("document-bbox-mode", "document-bbox-container", "document-bbox-canvas"),
    "pdf_bbox": ("pdf-bbox-mode", "pdf-bbox-container", "pdf-bbox-canvas"),
    "pdf_link": ("pdf-link-mode",),
    # Plain PDF.js viewer: the default annotation_mode ("span") for a PDF
    # display. Marker matches the class pdf_display._render_pdfjs emits.
    "pdf_viewer": ("pdf-plain-mode",),
    "web_agent_viewer": ('class="web-agent-viewer"', 'class="live-agent-viewer"'),
    "web_agent_playback": ('data-auto-playback="true"',),
    "web_agent_recorder": ("web-agent-recorder",),
    "live_coding_agent": ("live-coding-agent-viewer",),
    # Per-class show/hide is shared across modalities. Keyed on the label-button
    # convention that image and video annotation already render identically, so
    # any surface adopting that markup gets the feature without new wiring.
    "label_visibility": ("label-btn",),
}


def _detect_frontend_assets_for_page(html_file: str, display_html: str = "") -> dict[str, bool]:
    """
    Detect which frontend assets are needed for the current page only.

    This avoids loading every specialized bundle just because some other phase
    in the overall task config happens to use it.
    """
    page_html = _read_cached_template_text(_resolve_generated_template_path(html_file))
    combined_html = f"{page_html}\n{display_html or ''}"

    def has_any(*markers: str) -> bool:
        return any(marker in combined_html for marker in markers)

    detected = {key: has_any(*markers) for key, markers in FRONTEND_ASSET_MARKERS.items()}

    # span_link also loads when coreference is present
    detected["span_link"] = detected["span_link"] or detected["coreference"]

    return detected


# Extensions worth warming the HTTP cache for. Text is not here: it arrives in
# the page itself, so there is nothing to prefetch.
_PREFETCHABLE_SUFFIXES = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".svg",
    ".mp3", ".wav", ".ogg", ".m4a", ".flac",
    ".mp4", ".webm", ".mov", ".mkv",
    ".pdf",
)

# Several media fields on one item are normal (a video plus its poster frame);
# a hundred are not. Cap it so a wide table cannot flood the connection pool
# and slow down the page the annotator is actually looking at.
_MAX_PREFETCH_URLS = 4


def _looks_prefetchable(value) -> bool:
    if not isinstance(value, str) or len(value) > 2048:
        return False
    candidate = value.split("?", 1)[0].split("#", 1)[0].strip().lower()
    if not candidate:
        return False
    if not (candidate.startswith(("/", "http://", "https://"))):
        return False
    return candidate.endswith(_PREFETCHABLE_SUFFIXES)


def _next_instance_prefetch_urls(user_state) -> list:
    """Media URLs on the instance the annotator will see next.

    Navigation is a full page reload, so a JS-side prefetch would be thrown
    away. Emitting ``<link rel="prefetch">`` instead warms the *HTTP* cache,
    which survives the reload — that is the whole mechanism.

    Returns [] for anything unexpected. A prefetch is an optimisation; it must
    never be the reason a page fails to render.
    """
    try:
        ordering = getattr(user_state, "instance_id_ordering", None)
        index = getattr(user_state, "current_instance_index", -1)
        if not ordering or index < 0 or index + 1 >= len(ordering):
            return []

        ism = get_item_state_manager()
        next_id = ordering[index + 1]
        if not ism.has_item(next_id):
            return []

        data = ism.get_item(next_id).get_data() or {}
        urls = []
        for value in data.values():
            if _looks_prefetchable(value):
                if value not in urls:
                    urls.append(value)
                if len(urls) >= _MAX_PREFETCH_URLS:
                    break
        return urls
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug(f"Skipping media prefetch: {exc}")
        return []


def _apply_annotation_filter(items: list, filter_config: dict, id_key: str) -> list:
    """
    Filter items based on prior annotation decisions.

    This enables chaining annotation tasks, e.g., triage -> full annotation.

    Args:
        items: List of data items to filter
        filter_config: Configuration dict with:
            - annotation_dir: Path to annotation_output directory
            - schema: Name of the annotation schema to filter by
            - value: Value(s) to filter for (string or list)
            - invert: If True, return items that DON'T match (optional)
        id_key: Key in items containing the instance ID

    Returns:
        Filtered list of items
    """
    from potato.filter_by_annotation import load_annotations_from_dir

    annotation_dir = filter_config.get("annotation_dir")
    schema_name = filter_config.get("schema")
    filter_value = filter_config.get("value")
    invert = filter_config.get("invert", False)

    if not annotation_dir:
        logger.warning("filter_by_prior_annotation missing 'annotation_dir', skipping filter")
        return items
    if not schema_name:
        logger.warning("filter_by_prior_annotation missing 'schema', skipping filter")
        return items
    if not filter_value:
        logger.warning("filter_by_prior_annotation missing 'value', skipping filter")
        return items

    # Normalize filter_value to a set
    if isinstance(filter_value, str):
        filter_values = {filter_value}
    else:
        filter_values = set(filter_value)

    # Load prior annotations
    annotations = load_annotations_from_dir(annotation_dir)
    logger.debug(f"Loaded prior annotations for {len(annotations)} instances")

    # Filter items
    filtered = []
    for item in items:
        instance_id = str(item.get(id_key, ""))
        if not instance_id:
            continue

        # Check if this instance has the annotation we're looking for
        instance_annotations = annotations.get(instance_id, {})
        schema_annotation = instance_annotations.get(schema_name, {})

        # Get the annotation value
        anno_value = schema_annotation.get("name") or schema_annotation.get("value")
        matches = anno_value in filter_values

        if invert:
            matches = not matches

        if matches:
            filtered.append(item)

    return filtered


def load_instance_data(config: dict):
    """
    Load instance data from the files specified in the config.

    This function reads annotation data from various file formats (JSON, CSV, TSV, JSONL)
    and populates the ItemStateManager with the data. It handles different data structures
    and validates that required fields are present.

    Supports multiple data loading modes:
    1. data_files: List of local file paths (traditional mode)
    2. data_sources: Extended sources including URLs, cloud storage, databases
    3. data_directory: Watch a directory for files (handled separately)

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

    # Check if data_sources is configured (new extended data loading)
    if config.get("data_sources"):
        _load_from_data_sources(config, ism, id_key, text_key)
        return

    data_files = list(config.get("data_files", []))
    seen_data_files = {
        _data_file_entry_identity(data_file_entry, config.get("task_dir", "."))
        for data_file_entry in data_files
    }
    for data_file_entry in _batch_assignment_data_file_entries(config):
        key = _data_file_entry_identity(data_file_entry, config.get("task_dir", "."))
        if key not in seen_data_files:
            data_files.append(data_file_entry)
            seen_data_files.add(key)

    if not data_files:
        # No data_files, might use data_directory which is handled elsewhere
        logger.debug("No data_files configured, skipping file-based loading")
        return

    logger.debug("Loading data from %d files" % (len(data_files)))

    for data_file_entry in data_files:
        # Support both string paths and dict configs
        if isinstance(data_file_entry, dict):
            data_fname = data_file_entry.get("path")
            filter_config = data_file_entry.get("filter_by_prior_annotation")
            encoding = data_file_entry.get("encoding", "utf-8")
        else:
            data_fname = data_file_entry
            filter_config = None
            encoding = "utf-8"

        if not data_fname:
            logger.warning(f"Skipping data_files entry with no path: {data_file_entry}")
            continue
        fmt = data_fname.split(".")[-1]
        if fmt not in ["csv", "tsv", "json", "jsonl", "parquet"]:
            raise Exception("Unsupported input file format %s for %s" % (fmt, data_fname))

        logger.debug("Reading data from " + data_fname)

        if fmt in ["json", "jsonl"]:
            # Handle JSON and JSONL formats
            # Try parsing as a JSON array first, fall back to JSON Lines
            with open(data_fname, "rt", encoding=encoding) as f:
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

            # Apply filter_by_prior_annotation if configured
            if filter_config:
                items = _apply_annotation_filter(items, filter_config, id_key)
                logger.info(f"Filtered to {len(items)} items based on prior annotations")

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
        elif fmt == "parquet":
            import pyarrow.parquet as pq

            table = pq.read_table(data_fname)
            df = table.to_pandas()

            if id_key not in df.columns:
                raise KeyError(f"ID column '{id_key}' not found in file {data_fname}")
            if text_key not in df.columns:
                logger.warning(f"Text column '{text_key}' not found in file {data_fname}")

            df[id_key] = df[id_key].astype(str)

            if df[id_key].duplicated().any():
                dupes = df[id_key][df[id_key].duplicated()].tolist()
                raise ValueError(f"Duplicate instance IDs found in {data_fname}: {dupes}")

            existing_dupes = [id for id in df[id_key] if ism.has_item(id)]
            if existing_dupes:
                raise ValueError(f"Instance IDs in {data_fname} conflict with existing IDs: {existing_dupes}")

            if text_key in df.columns:
                df = df.astype({text_key: str})

            items = df.to_dict('records')

            if filter_config:
                items = _apply_annotation_filter(items, filter_config, id_key)
                logger.info(f"Filtered to {len(items)} items based on prior annotations")

            for item in items:
                instance_id = item[id_key]
                ism.add_item(instance_id, item)

            line_no = len(items)
        else:
            sep = "," if fmt == "csv" else "\t"

            # Validate required columns exist
            df = pd.read_csv(data_fname, sep=sep, encoding=encoding)
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

            # Convert to list of dicts for filtering
            items = df.to_dict('records')

            # Apply filter_by_prior_annotation if configured
            if filter_config:
                items = _apply_annotation_filter(items, filter_config, id_key)
                logger.info(f"Filtered to {len(items)} items based on prior annotations")

            # Add items to state manager
            for item in items:
                instance_id = item[id_key]
                ism.add_item(instance_id, item)

            line_no = len(items)

        # If the admin didn't specify a subset, have the user annotate all instances
        # (or unlimited when a dynamic source can add more at runtime — see F-037).
        max_annotations_per_user = _default_max_annotations_per_user(config, ism)
        get_user_state_manager().set_max_annotations_per_user(max_annotations_per_user)

        logger.debug("Loaded %d instances from %s" % (line_no, data_fname))

    # If BWS config is present, generate tuples from pool items
    bws_config = config.get("bws_config")
    if bws_config:
        from potato.bws_tuple_generator import BwsTupleGenerator

        # Collect all loaded pool items
        pool_items = [item.get_data() for item in ism.items()]

        # Store pool items for scoring later
        config["_bws_pool_items"] = [dict(item) for item in pool_items]

        generator = BwsTupleGenerator(
            pool_items=pool_items,
            id_key=id_key,
            text_key=text_key,
            tuple_size=bws_config.get("tuple_size", 4),
            num_tuples=bws_config.get("num_tuples"),
            seed=bws_config.get("seed", 42),
            min_item_appearances=bws_config.get("min_item_appearances"),
        )
        generator.validate()
        tuples = generator.generate()

        # Clear pool items and replace with generated tuples
        ism.clear()
        for t in tuples:
            ism.add_item(str(t[id_key]), t)

        # Update max annotations per user for the new tuple count
        max_annotations_per_user = config.get(
            "max_annotations_per_user", len(ism.get_instance_ids())
        )
        get_user_state_manager().set_max_annotations_per_user(max_annotations_per_user)

        logger.info(f"BWS: Replaced {len(pool_items)} pool items with {len(tuples)} tuples")

    # If IBWS config is present, initialize iterative BWS manager and generate round 1 tuples
    ibws_config = config.get("ibws_config")
    if ibws_config:
        from potato.ibws_manager import init_ibws_manager

        # Collect all loaded pool items
        pool_items = [item.get_data() for item in ism.items()]

        # Store pool items for scoring
        config["_bws_pool_items"] = [dict(item) for item in pool_items]

        # Initialize IBWS manager
        ibws_mgr = init_ibws_manager(config, pool_items, id_key, text_key)

        # Generate round 1 tuples
        round1_tuples = ibws_mgr.generate_round_tuples()

        # Clear pool items and replace with round 1 tuples
        ism.clear()
        for t in round1_tuples:
            ism.add_item(str(t[id_key]), t)

        # Set unlimited annotations — IBWS manager controls completion
        get_user_state_manager().set_max_annotations_per_user(-1)

        logger.info(
            f"IBWS: Initialized with {len(pool_items)} pool items, "
            f"generated {len(round1_tuples)} round-1 tuples"
        )

    # For each item, render the text to display in the UI ahead of time.
    _render_displayed_text(text_key)


def _data_file_entry_identity(data_file_entry, task_dir: str = ".") -> str:
    if isinstance(data_file_entry, dict):
        data_file_entry = data_file_entry.get("path", "")
    path = str(data_file_entry)
    if path and not os.path.isabs(path):
        path = os.path.join(task_dir, path)
    return os.path.normcase(os.path.abspath(os.path.normpath(path)))


def _batch_assignment_data_file_entries(config: dict) -> list:
    batch_config = config.get("batch_assignment")
    if not isinstance(batch_config, dict):
        return []

    entries = []
    for group in batch_config.get("groups") or []:
        if not isinstance(group, dict):
            continue
        data_file = group.get(
            "data_file",
            group.get("input_data_file", group.get("input_file")),
        )
        if data_file:
            entries.append(_resolve_batch_assignment_data_file_entry(config, data_file))
    return entries


def _resolve_batch_assignment_data_file_entry(config: dict, data_file_entry):
    task_dir = config.get("task_dir", ".")

    if isinstance(data_file_entry, dict):
        resolved_entry = dict(data_file_entry)
        path = resolved_entry.get("path")
        if isinstance(path, str) and path and not os.path.isabs(path):
            resolved_entry["path"] = os.path.normpath(os.path.join(task_dir, path))
        return resolved_entry

    if isinstance(data_file_entry, str) and data_file_entry and not os.path.isabs(data_file_entry):
        return os.path.normpath(os.path.join(task_dir, data_file_entry))
    return data_file_entry


def _has_live_ingestion_source(config: dict) -> bool:
    """
    True when any enabled data source polls for rows added at runtime.

    Args:
        config: Application configuration

    Returns:
        True if at least one enabled data_sources entry has
        ``live_ingestion.enabled``
    """
    for source in (config.get("data_sources") or []):
        if not isinstance(source, dict):
            continue
        if source.get("enabled", True) is False:
            continue
        live = source.get("live_ingestion")
        if isinstance(live, dict) and live.get("enabled"):
            return True
    return False


def _start_live_ingestion(config: dict) -> None:
    """
    Start the background poll workers for live data sources.

    Called from ``configure_app()``, i.e. after the initial data load and
    after user state has been restored. Failures are logged, never fatal: a
    database that is unreachable at boot must not stop the annotation server
    from serving the items it already has.
    """
    # Flask's reloader runs the module twice; only the child (WERKZEUG_RUN_MAIN
    # == "true") should own the poll threads, or every insert gets fetched by
    # two workers in two separate item pools.
    if os.environ.get("WERKZEUG_RUN_MAIN") == "false":
        logger.debug("Skipping live ingestion start in the reloader parent process")
        return

    try:
        from potato.data_sources import get_data_source_manager
        manager = get_data_source_manager()
        if manager is None:
            logger.warning(
                "live_ingestion is configured but the DataSourceManager is not "
                "initialized; no pollers started"
            )
            return

        for index, source in enumerate(config.get("data_sources") or []):
            if not isinstance(source, dict):
                continue
            live = source.get("live_ingestion")
            if isinstance(live, dict) and live.get("enabled") and not (
                source.get("id") or source.get("source_id")
            ):
                logger.warning(
                    "data_sources[%d] enables live_ingestion but has no explicit "
                    "'id'. The auto-generated id encodes the list position, so "
                    "reordering data_sources would point this source's stored "
                    "cursor at a different table. Set an explicit id.",
                    index,
                )

        started = manager.start_live_ingestion()
        if started:
            logger.info("Started %d live ingestion worker(s)", started)
            logger.warning(
                "Live ingestion assumes a SINGLE server process. Potato keeps "
                "its item pool in memory per process, so running under multiple "
                "workers (e.g. gunicorn -w N) gives each one its own pool, its "
                "own poller, and no cross-process deduplication."
            )

        import atexit
        atexit.register(manager.stop_live_ingestion)

    except Exception as e:
        logger.error("Failed to start live ingestion: %s", e, exc_info=True)


def _default_max_annotations_per_user(config: dict, ism) -> int:
    """
    Resolve the default per-user annotation quota.

    When ``max_annotations_per_user`` is explicitly configured, honor it.
    Otherwise the historical default is "annotate everything" = the instance
    count. But that count is frozen at load time, so when a DYNAMIC data source
    can add items at runtime (trace ingestion, directory watching, live database
    ingestion), freezing the cap means later-added items exceed every user's
    quota and are never assigned to any annotator (F-037). In that case default
    to unlimited (-1) instead, so the live ``remaining_instance_ids`` pool stays
    fully assignable.
    """
    has_live_ingestion = _has_live_ingestion_source(config)

    configured = config.get("max_annotations_per_user")
    if configured is not None:
        if has_live_ingestion and configured >= 0:
            logger.warning(
                "max_annotations_per_user is set to %s while live database "
                "ingestion is enabled. Each annotator will stop receiving items "
                "after %s, including newly ingested ones. Remove the setting (or "
                "set it to -1) to keep the live pool fully assignable.",
                configured, configured,
            )
        return configured

    dynamic_source = bool(
        (config.get("trace_ingestion") or {}).get("enabled")
        or config.get("watch_data_directory")
        or has_live_ingestion
    )
    if dynamic_source:
        return -1
    return len(ism.get_instance_ids())


def _render_displayed_text(text_key: str) -> None:
    """
    Render the displayed text for all items.

    This processes the text_key field to generate the displayed_text
    that will be shown in the annotation UI.

    Args:
        text_key: The key in item data containing the text to display
    """
    for item in get_item_state_manager().items():
        item_data = item.get_data()

        # Validate text key exists before rendering
        if text_key in item_data:
            item_data["displayed_text"] = get_displayed_text(item_data[text_key])
        else:
            item_data["displayed_text"] = ""
            logger.warning(f"No text found for item {item.get_id()}, using empty string")


def _load_from_data_sources(config: dict, ism, id_key: str, text_key: str) -> None:
    """
    Load data using the extended DataSourceManager.

    This function initializes the DataSourceManager and loads data from
    configured sources (URLs, cloud storage, databases, etc.).

    Args:
        config: Application configuration
        ism: ItemStateManager instance
        id_key: Key for item IDs
        text_key: Key for text content
    """
    # Import and register source implementations
    from potato.data_sources import init_data_source_manager, get_data_source_manager
    import potato.data_sources.sources  # This registers all source types

    # Initialize the data source manager
    manager = init_data_source_manager(config)

    if not manager:
        logger.warning("DataSourceManager initialization failed")
        return

    # Load initial data from all sources
    total_loaded = manager.load_initial_data()
    logger.info(f"Loaded {total_loaded} items from data sources")

    # Set max annotations per user (unlimited when a dynamic source — e.g. a
    # watched directory or trace ingestion — can add items at runtime; F-037).
    max_annotations_per_user = _default_max_annotations_per_user(config, ism)
    get_user_state_manager().set_max_annotations_per_user(max_annotations_per_user)

    # Render displayed text for all loaded items
    _render_displayed_text(text_key)


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
    user_id_to_instance_ids = {}
    for user_id in usm.get_user_ids():
        user_state = usm.get_user_state(user_id)
        if user_state:
            for instance_id in user_state.instance_id_to_label_to_value:
                if ism.has_item(instance_id):
                    ism.register_annotator(instance_id, user_id)
            for instance_id in user_state.instance_id_to_span_to_value:
                if ism.has_item(instance_id):
                    ism.register_annotator(instance_id, user_id)
            # Rebuild the per-item assignee index too. It backs the per-item
            # annotator cap alongside instance_annotators, and it is in-memory
            # only -- without this a restart forgets every outstanding hold and
            # the cap goes back to counting submitters, which is the bug it
            # exists to fix.
            assigned = set(user_state.get_assigned_instance_ids())
            for instance_id in assigned:
                if ism.has_item(instance_id):
                    ism.register_assignee(instance_id, user_id)

            # Collect assigned + annotated items so auto-batch cohort pins can be
            # reconstructed below (they are otherwise in-memory only and reset on
            # every restart).
            user_id_to_instance_ids[user_id] = (
                assigned | set(user_state.get_annotated_instance_ids())
            )

    # Restore auto-assigned batch cohort pins from persisted assignments so that
    # returning users stay in their original group and new users keep balancing
    # against accurate per-group counts after a restart. No-op unless
    # batch_assignment.auto_assign_annotators is enabled.
    ism.rebuild_auto_batch_pins_from_users(user_id_to_instance_ids)

    logger.info("Loaded user data for %d users" % len(usm.get_user_ids()))
    _warn_on_orphaned_schemes(config, usm)


def _warn_on_orphaned_schemes(config: dict, usm) -> None:
    """Warn when saved annotations name a scheme the config no longer defines.

    Editing `annotation_schemes` after people have annotated is silent in every
    direction. An item stays "annotated" whatever it was annotated *with*, so a
    renamed or newly added scheme is never put back in front of anyone who
    already finished, and the three surfaces that report on the study disagree
    without saying so: the overview reports 100% complete, agreement reports
    zero items for every configured scheme, and the CSV export -- which is
    driven by what was stored rather than by the config -- comes out with
    columns named after schemes that no longer exist.

    This does not repair anything. It puts the mismatch in the boot log, which
    is the only place the operator is already looking.
    """
    configured = {s.get("name") for s in (config.get("annotation_schemes") or [])
                  if isinstance(s, dict) and s.get("name")}
    if not configured:
        return

    stored: dict[str, int] = {}
    for user_id in usm.get_user_ids():
        user_state = usm.get_user_state(user_id)
        if not user_state:
            continue
        for labels in user_state.instance_id_to_label_to_value.values():
            for label in labels:
                schema = getattr(label, "schema", None)
                if schema and schema not in configured:
                    stored[schema] = stored.get(schema, 0) + 1

    if not stored:
        return

    named = ", ".join(f"{name} ({count} answer(s))"
                      for name, count in sorted(stored.items()))
    logger.warning(
        "Saved annotations name %d scheme(s) that annotation_schemes no longer "
        "defines: %s. Items already annotated stay annotated, so nobody who "
        "finished will be shown the current schemes, agreement will report zero "
        "items for them, and exports will carry the old names. If this was a "
        "rename, keep the old name or start a new output_annotation_dir.",
        len(stored), named,
    )

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

    # A project whose text_key is not "text" -- an image task pointing it at the
    # image URL field, say -- writes its practice question under that key. Accept
    # either, and carry the key through to the Item below.
    training_text_key = config.get("item_properties", {}).get("text_key", "text")

    for instance in training_instances:
        # Validate required fields
        if 'id' not in instance or 'correct_answers' not in instance:
            raise Exception(f"Training instance missing required fields: {instance}")
        if 'text' not in instance and training_text_key not in instance:
            raise Exception(
                f"Training instance {instance['id']} has neither 'text' nor the "
                f"configured text_key '{training_text_key}'"
            )

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

        # Create Item object for training instance.
        #
        # Start from the instance itself rather than a fixed six keys. The old
        # version copied id/text/correct_answers/explanation/displayed_text and
        # threw the rest away, so an image project's `image_url` -- the field its
        # text_key names, and the one the practice page needs -- never reached
        # the Item. The page then fell back to the prose in `text` and asked the
        # browser to load a sentence as an image.
        question_text = instance.get(training_text_key) or instance.get('text', '')
        item_data = dict(instance)
        item_data.update({
            'id': instance['id'],
            'correct_answers': instance['correct_answers'],
            'explanation': instance.get('explanation', ''),
            'displayed_text': get_displayed_text(question_text),
            'categories': categories  # Store normalized categories list
        })

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
    # Bridge the __main__ vs potato.flask_server module split. When the server is
    # launched from source via `python potato/flask_server.py start ...`, this file
    # executes in the `__main__` namespace, so load_training_data's
    # `global training_items` binds `__main__.training_items`. But routes.py and
    # user_state_management.py call this function via
    # `from potato.flask_server import get_training_instances`, which is the
    # *potato.flask_server* copy whose own global is never set — previously
    # leaving the training phase with "No training instance available". Scan the
    # candidate module namespaces so the data is found regardless of launch style.
    for _mod_name in (__name__, 'potato.flask_server', '__main__'):
        _mod = sys.modules.get(_mod_name)
        _items = getattr(_mod, 'training_items', None) if _mod is not None else None
        if _items:
            return _items
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
            with open(prolific_config_path, 'r', encoding='utf-8') as f:
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

        # Auto pause/resume polling is opt-in: it makes recurring Prolific API
        # calls, so existing token-configured deployments must not start polling
        # just because they upgraded.
        if prolific_settings.get('workload_checker', False):
            # With webhooks delivering submission changes in real time, the
            # poller only reconciles missed events — slow it down.
            webhooks_enabled = (((config.get('crowdsourcing') or {}).get('prolific') or {})
                                .get('webhooks') or {}).get('enabled', False)
            if webhooks_enabled:
                PROLIFIC_STUDY_INSTANCE.checker_period = max(
                    PROLIFIC_STUDY_INSTANCE.checker_period, 600)
            PROLIFIC_STUDY_INSTANCE.start_workload_monitor()
            import atexit

            def cleanup_prolific_monitor():
                study = get_prolific_study()
                if study:
                    study.stop_workload_monitor()
            atexit.register(cleanup_prolific_monitor)

    except Exception as e:
        logger.error(f"Failed to initialize Prolific study: {e}")
        PROLIFIC_STUDY_INSTANCE = None


def get_prolific_study() -> 'ProlificStudy':
    """
    Get the global Prolific study instance.

    Returns:
        ProlificStudy instance if configured, None otherwise
    """
    global PROLIFIC_STUDY_INSTANCE
    # Same __main__ vs potato.flask_server split as get_training_instances (F-044):
    # init_prolific_study reassigns this global, so under `python flask_server.py`
    # it lands on __main__ while routes.py reads the potato.flask_server copy (None).
    # Scan candidate namespaces so a configured study is found regardless of launch.
    for _mod_name in (__name__, 'potato.flask_server', '__main__'):
        _mod = sys.modules.get(_mod_name)
        _inst = getattr(_mod, 'PROLIFIC_STUDY_INSTANCE', None) if _mod is not None else None
        if _inst is not None:
            return _inst
    return PROLIFIC_STUDY_INSTANCE


def _prefill_diversity_embeddings(dm, config: dict) -> None:
    """
    Prefill embeddings for diversity ordering with progress bar.

    Args:
        dm: DiversityManager instance
        config: Application configuration
    """
    from tqdm import tqdm
    from potato.embedders import resolve

    ism = get_item_state_manager()
    items = list(ism.items())[:dm.config.prefill_count]
    if not items:
        return

    # Which field, and which encoder? Asking the project rather than assuming
    # text: `item.get_text()` falls back to an item's first string value, so a
    # vision corpus used to embed its own instance ids and say nothing about it.
    samples = [item.get_data() for item in items[:50]]
    embedder = resolve(config, samples=samples,
                       cache_dir=config.get("output_annotation_dir"))
    if not embedder.available:
        logger.warning("Diversity embeddings unavailable: %s",
                       embedder.spec.unavailable_reason)
        print(f"Skipping embeddings: {embedder.spec.unavailable_reason}")
        return
    dm.use_embedder(embedder)

    texts = {}
    for item in items:
        reference = embedder.reference_for(item.get_data())
        if reference is not None:
            texts[item.get_id()] = reference

    if not texts:
        logger.warning(
            "Diversity embeddings: no item carried the field '%s'",
            embedder.spec.source_field)
        return

    print(f"Prefilling {len(texts)} embeddings "
          f"({embedder.spec.backend}/{embedder.spec.model} "
          f"over '{embedder.spec.source_field}')...")

    # Track progress with tqdm
    completed = [0]

    def on_complete(iid, emb):
        completed[0] += 1

    with tqdm(total=len(texts), desc="Computing embeddings", unit="item") as pbar:
        # Compute in batches
        batch_size = dm.config.batch_size
        ids = list(texts.keys())

        for i in range(0, len(ids), batch_size):
            batch_ids = ids[i:i + batch_size]
            batch_texts = {iid: texts[iid] for iid in batch_ids}
            dm.compute_embeddings_batch(batch_texts, callback=on_complete)
            pbar.update(len(batch_ids))

    # Run clustering after prefill
    if dm.cluster_items():
        stats = dm.get_stats()
        logger.info(
            f"Clustered {stats['embedding_count']} items into "
            f"{stats['cluster_count']} clusters"
        )


def apply_cot_segmentation_to_all(config: dict) -> None:
    """Segment long CoT reasoning on every loaded item, per the ``cot_segmentation``
    config block. No-op when the block is absent. The ``llm`` strategy reuses the
    configured AI/judge endpoint; any endpoint error falls back to heuristics.
    """
    seg_config = config.get("cot_segmentation")
    if not seg_config or not isinstance(seg_config, dict):
        return

    from potato.server_utils.cot_segmentation import apply_cot_segmentation

    endpoint = None
    if seg_config.get("strategy") == "llm":
        try:
            from potato.ai.ai_endpoint import AIEndpointFactory
            endpoint = AIEndpointFactory.create_endpoint(config)
        except Exception as exc:  # noqa: BLE001 - heuristic fallback on any error
            logger.warning("cot_segmentation 'llm' endpoint unavailable, using heuristics: %s", exc)

    count = 0
    for item in get_item_state_manager().items():
        data = item.get_data()
        if isinstance(data, dict):
            before = data.get(seg_config.get("target_key", "cot_steps"))
            apply_cot_segmentation(data, seg_config, endpoint=endpoint)
            if data.get(seg_config.get("target_key", "cot_steps")) is not before:
                count += 1
    logger.info("CoT segmentation applied to %d items (strategy=%s)",
                count, seg_config.get("strategy", "auto"))


def _init_automation_manager_early(config: dict) -> None:
    """Build the automation manager BEFORE the corpus loads.

    `ItemStateManager.add_item` calls `automation.process_item` for every item,
    static or ingested -- but the manager was built during blueprint
    registration, which happens after `load_all_data`. So
    `get_automation_manager()` returned None for every item in a file-loaded
    corpus, `items_processed` stayed 0, and `automation` only ever saw traffic
    that arrived after boot. The triage scorer beside it initializes earlier
    and did run, which is why one of the pair worked and the other did not.

    `configure_app` still calls `init_automation_manager` and no-ops when this
    has already run, so the WSGI path keeps working unchanged.
    """
    if not (config.get("automation") or {}).get("enabled", False):
        return
    try:
        from potato.automation import (get_automation_manager,
                                       init_automation_manager)
        if get_automation_manager() is None:
            init_automation_manager(config)
    except Exception as e:
        logger.warning("Could not initialize the automation rules engine "
                       "before loading data: %s", e)


def load_all_data(config: dict):
    '''Loads instance and annotation data from the files specified in the config.'''
    load_annotation_schematic_data(config)
    load_instance_data(config)
    # Segment long chain-of-thought reasoning into per-step lists (feeds the
    # cot_trace display + process_reward schema). Must run after items load so
    # every static item is segmented before assignment/rendering.
    apply_cot_segmentation_to_all(config)
    # Stamp per-item annotator caps for the overlap sample (must run before
    # user_data so that initial assignments see the heterogeneous caps).
    try:
        from potato.server_utils.overlap_sampler import apply_overlap_sample
        sampled = apply_overlap_sample(get_item_state_manager(), config)
        if sampled:
            logger.info("Overlap sampling stamped %d items", len(sampled))
    except Exception as exc:
        logger.warning("Overlap sampling skipped due to error: %s", exc)
    load_user_data(config)
    load_phase_data(config)
    load_highlights_data(config)
    load_training_data(config)
    init_prolific_study(config)
    init_mturk_hit(config)
    from potato.crowdsourcing import init_crowd_provider
    init_crowd_provider(config)

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

    # Replay model predictions from previous training runs back into item data.
    # They are not durable on their own: item_data["predictions"] is populated
    # from the input file at load time and nothing re-persists it, so without
    # this every prelabel written at runtime vanishes on restart and the review
    # queue empties itself each time the server bounces.
    if config.get("model_training", {}).get("enabled", False):
        try:
            from potato.training.writeback import rehydrate_predictions
            restored = rehydrate_predictions(config, get_item_state_manager())
            if restored:
                logger.info("Restored %d model prediction(s) from earlier "
                            "training runs", restored)
        except Exception as e:
            logger.warning("Could not restore model predictions: %s", e)


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
    - random_word_probability: Probability of highlighting random words (default: 0.0)
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
    settings_dict['random_word_probability'] = config_settings.get('random_word_probability', 0.0)
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
            raw = f.read()
    except OSError as e:
        logger.error(f"Error reading keyword highlights file: {e}")
        return

    try:
        entries, detected_format = _parse_keyword_highlight_entries(
            raw, keyword_highlights_file)
    except Exception as e:  # noqa: BLE001 - a bad file must not stop the boot
        logger.error(f"Error loading keyword highlights file: {e}")
        patterns_list.clear()
        return

    for entry in entries:
        word = entry["word"]
        label, schema, color = entry["label"], entry["schema"], entry["color"]

        # Convert wildcard pattern to regex.
        # Escape special regex characters except *.
        escaped = re.escape(word).replace(r'\*', r'\w*')

        # Word boundaries, except where the author asked for a wildcard edge.
        pattern = escaped if word.startswith('*') else r'\b' + escaped
        if not word.endswith('*'):
            pattern = pattern + r'\b'

        try:
            compiled_regex = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            logger.warning(f"Invalid regex pattern for keyword '{word}': {e}")
            continue

        patterns_list.append({
            'pattern': word,
            'regex': compiled_regex,
            'label': label,
            'schema': schema,
        })
        # Also populate the emphasis corpus for backward compatibility
        emphasis_map[word].add(HighlightSchema(label=label, schema=schema))

        # A per-keyword colour goes into the same registry the span schemas
        # use, which is where /keyword_highlights reads it back from.
        if color:
            from potato.server_utils.schemas.span import set_span_color
            set_span_color(schema, label, _as_rgb_triple(color, word))

    if patterns_list:
        logger.info("Loaded %d keyword highlight patterns from %s (read as %s)",
                    len(patterns_list), keyword_highlights_file, detected_format)
    else:
        logger.warning(
            "Loaded 0 keyword highlight patterns from %s (read as %s). "
            "Accepted formats: a CSV or TSV with a 'keyword' header column "
            "(plus optional label, schema, color), one keyword per line, or "
            "JSON/JSONL/YAML holding a list of keywords, a list of objects, "
            "or a {keyword: label} mapping. See "
            "docs/administration/productivity.md",
            keyword_highlights_file, detected_format)


def _as_rgb_triple(color, context=""):
    """Normalise a colour to the ``(r, g, b)`` string the span registry stores.

    Hex is accepted because it is what people write, but it cannot be stored
    raw: the span label chip builds its CSS as ``"rgb" + color``, so a
    ``#ffcc00`` in the registry renders as ``rgb#ffcc00`` and the chip loses
    its colour.
    """
    value = str(color or "").strip()
    if value.startswith("#"):
        digits = value[1:]
        if len(digits) == 3:
            digits = "".join(ch * 2 for ch in digits)
        if len(digits) == 6:
            try:
                r, g, b = (int(digits[i:i + 2], 16) for i in (0, 2, 4))
                return f"({r}, {g}, {b})"
            except ValueError:
                pass
        logger.warning("Ignoring unreadable colour %r for keyword %r", color, context)
        return ""
    return value


#: Column names accepted for each field of a keyword-highlights table, matched
#: case-insensitively with spaces/underscores/hyphens ignored. The names people
#: actually write differ from the ones the original TSV used, and a header the
#: reader does not recognise costs the study its highlights silently.
KEYWORD_HIGHLIGHT_COLUMNS = {
    "word": ("keyword", "word", "pattern", "term", "text", "phrase"),
    "label": ("label", "category", "class", "tag", "name"),
    "schema": ("schema", "scheme", "annotationscheme", "annotationschema"),
    "color": ("color", "colour", "highlightcolor", "highlightcolour"),
}


def _normalize_keyword_column(name):
    return "".join(ch for ch in str(name or "").lower()
                   if ch.isalnum())


def _keyword_column_map(header_cells):
    """Map a header row's cells onto (word, label, schema, color) positions."""
    mapping = {}
    for index, cell in enumerate(header_cells):
        normalized = _normalize_keyword_column(cell)
        for field, aliases in KEYWORD_HIGHLIGHT_COLUMNS.items():
            if normalized in aliases and field not in mapping:
                mapping[field] = index
    return mapping


def _keyword_entry(word, label="", schema="", color=""):
    word = str(word or "").strip()
    if not word:
        return None
    return {
        "word": word,
        "label": str(label or "").strip(),
        "schema": str(schema or "").strip(),
        "color": str(color or "").strip(),
    }


def _keyword_entries_from_object(row):
    """One entry from a mapping, whatever the keys are called."""
    resolved = {}
    for key, value in row.items():
        normalized = _normalize_keyword_column(key)
        for field, aliases in KEYWORD_HIGHLIGHT_COLUMNS.items():
            if normalized in aliases and field not in resolved:
                resolved[field] = value
    return _keyword_entry(resolved.get("word"), resolved.get("label"),
                          resolved.get("schema"), resolved.get("color"))


def _parse_keyword_highlight_entries(raw, path):
    """Parse a keyword-highlights file into entry dicts.

    Every documented shape is header-first, and headers are matched by name
    rather than by position, so the columns can be in any order and can be
    called any of several sensible things -- ``keyword``/``word``/``pattern``
    for the term, ``label``/``category``/``tag`` for what to call it. See
    ``docs/administration/productivity.md``.

    Accepted:

        keyword,label,schema         CSV or TSV with a header row
        keyword                      a single-column file, header optional
        [{"keyword": ..., ...}]      JSON array of objects, or of strings
        {"latch": "Hazard"}          JSON object mapping keyword to label
        {"keyword": ...}             JSONL, one object per line
        (the same shapes in YAML)

    Before this read more than one of them, three of the four obvious things
    to write loaded zero patterns and logged "Loaded 0", which reads as an
    empty file rather than an unrecognised one. Nothing downstream fails when
    highlighting is missing, so a study just ran without the highlights its
    author configured.

    Returns a list of ``{word, label, schema, color}`` dicts; ``label``,
    ``schema`` and ``color`` are "" where the file does not carry them.
    """
    import csv
    import json

    text = (raw or "").strip()
    if not text:
        return [], "empty"

    extension = os.path.splitext(path or "")[1].lower()
    content_lines = [line for line in text.splitlines()
                     if line.strip() and not line.lstrip().startswith("#")]
    # JSONL first when it looks like JSONL, so the whole-file JSON parse does
    # not fail on it and log a misleading "does not parse".
    looks_like_jsonl = (
        len(content_lines) > 1
        and all(line.lstrip().startswith("{") for line in content_lines)
    )

    if not looks_like_jsonl and (text[0] in "[{" or extension == ".json"):
        entries, fmt = _parse_keyword_json(text, path)
        if entries is not None:
            return entries, fmt

    if extension in (".yaml", ".yml"):
        try:
            import yaml as _yaml
            data = _yaml.safe_load(text)
        except Exception as e:  # noqa: BLE001 - fall through to delimited text
            logger.warning("%s did not parse as YAML (%s); reading it as "
                           "delimited text instead", path, e)
        else:
            entries = _keyword_entries_from_data(data, path)
            if entries is not None:
                return entries, "yaml"

    lines = content_lines
    if not lines:
        return [], "empty"

    # JSONL: every line its own JSON object.
    if lines and all(line.lstrip().startswith("{") for line in lines):
        entries = []
        for line in lines:
            try:
                row = json.loads(line)
            except ValueError:
                entries = None
                break
            entry = _keyword_entries_from_object(row) if isinstance(row, dict) else None
            if entry:
                entries.append(entry)
        if entries is not None:
            return entries, "jsonl"

    delimiter = "\t" if "\t" in lines[0] else ("," if "," in lines[0] else None)
    if delimiter is None:
        # Single column. A lone "keyword" header line would otherwise become a
        # keyword in its own right.
        if _normalize_keyword_column(lines[0]) in KEYWORD_HIGHLIGHT_COLUMNS["word"]:
            lines = lines[1:]
        entries = [_keyword_entry(line) for line in lines]
        return [e for e in entries if e], "one keyword per line"

    header_cells = next(csv.reader([lines[0]], delimiter=delimiter))
    columns = _keyword_column_map(header_cells)
    if "word" in columns:
        entries = []
        for row in csv.reader(lines[1:], delimiter=delimiter):
            def cell(field):
                index = columns.get(field)
                return row[index] if index is not None and index < len(row) else ""
            entry = _keyword_entry(cell("word"), cell("label"),
                                   cell("schema"), cell("color"))
            if entry:
                entries.append(entry)
        return entries, f"delimited with a header ({', '.join(header_cells)})"

    # No recognisable header. Read positionally and say so: a file whose first
    # column is not the keyword will produce nonsense, and the log line is the
    # only place that becomes visible.
    logger.warning(
        "%s has no recognised header row, so its columns are being read "
        "positionally as keyword, label, schema. Add a header line -- "
        "'keyword,label,schema' -- to be explicit.", path)
    entries = []
    for row in csv.reader(lines, delimiter=delimiter):
        entry = _keyword_entry(*(list(row) + ["", "", ""])[:4])
        if entry:
            entries.append(entry)
    return entries, "delimited, no header"


def _parse_keyword_json(text, path):
    """(entries, format) from JSON text, or (None, None) if it is not JSON."""
    import json
    try:
        data = json.loads(text)
    except ValueError:
        logger.warning("%s starts like JSON but does not parse; reading it "
                       "as delimited text instead", path)
        return None, None
    entries = _keyword_entries_from_data(data, path)
    if entries is None:
        return [], "json"
    return entries, "json"


def _keyword_entries_from_data(data, path):
    """Entries from already-parsed JSON/YAML, or None if the shape is wrong."""
    if isinstance(data, dict):
        # {"latch": "Hazard"} -- keyword to label.
        entries = []
        for key, value in data.items():
            if isinstance(value, dict):
                entry = _keyword_entries_from_object(dict(value, keyword=key))
            else:
                entry = _keyword_entry(key, value)
            if entry:
                entries.append(entry)
        return entries
    if isinstance(data, list):
        entries = []
        for row in data:
            if isinstance(row, str):
                entry = _keyword_entry(row)
            elif isinstance(row, dict):
                entry = _keyword_entries_from_object(row)
            else:
                entry = None
            if entry:
                entries.append(entry)
        return entries
    logger.warning("%s parsed to %s; expected a list or an object",
                   path, type(data).__name__)
    return None


def _check_phase_schemes(schemes, source, phase_name):
    """Refuse a phase file whose entries cannot be rendered, and say which.

    The generator raises `KeyError: 'annotation_type'` and the boot aborts --
    correct, since a phase the author asked for and did not get is never the
    safe outcome, but the message names neither the file nor the entry. On a
    survey file with a dozen questions that leaves the author reading all
    twelve. Name the file, the position, and the question.
    """
    required = ("annotation_type", "name", "description")
    problems = []
    for index, scheme in enumerate(schemes or []):
        if not isinstance(scheme, dict):
            problems.append(
                f"  entry {index}: expected a question object, got "
                f"{type(scheme).__name__}")
            continue
        missing = [key for key in required if not scheme.get(key)]
        if missing:
            named = scheme.get("name") or scheme.get("description") or "(unnamed)"
            problems.append(
                f"  entry {index} ({named!r}) is missing: {', '.join(missing)}")
    if problems:
        raise ValueError(
            f"{source} cannot be rendered as the '{phase_name}' phase.\n"
            + "\n".join(problems)
            + "\nEvery question needs annotation_type, name and description."
        )


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

    # Accumulate every phase's questions so display_logic references can be
    # validated across the whole SurveyFlow (a poststudy question may condition
    # on a prestudy answer). Validated once after all phases load.
    _all_phase_schemes_for_dl = []

    # Phase names in `order` with no matching definition. The loader skips
    # them, but until the order itself is pruned every other consumer still
    # believes they exist -- `/register` reads `phases.order[0]` directly and
    # parked the annotator on a phase with no registered page, so
    # `get_phase_html_fname` raised KeyError and every request, including `/`,
    # returned 500. The warning said it had recovered; it had not.
    undefined_phase_names = []

    for phase_name in phase_order:
        try:
            # Skip 'annotation' — it's handled by the main annotation flow,
            # not the phase loader. It can appear in the order for sequencing
            # but doesn't need a phase dict entry.
            if phase_name not in phases_dict:
                if phase_name == "annotation":
                    logger.debug(f"Skipping phase '{phase_name}' in loader (handled by main annotation flow)")
                else:
                    logger.warning(
                        f"Phase '{phase_name}' in order but not defined in phases config; "
                        f"dropping it from the phase order"
                    )
                    undefined_phase_names.append(phase_name)
                continue

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
                # File-based phase. Prefer an explicit `type`; otherwise
                # infer it from the phase name when the name is itself a
                # canonical phase (e.g. a phase literally named `consent`
                # or `prestudy`). This makes the documented `phases`
                # config work even without a `type` field, while still
                # requiring an explicit `type` for custom-named phases.
                explicit_type = phase.get("type") if isinstance(phase, dict) else None
                if explicit_type:
                    phase_type = UserPhase.fromstr(explicit_type)
                else:
                    try:
                        phase_type = UserPhase.fromstr(phase_name)
                    except ValueError:
                        logger.error(
                            f"Phase '{phase_name}' has no 'type' and its name is "
                            f"not a canonical phase type"
                        )
                        raise Exception(
                            "Phase %s does not have a 'type' and its name is not "
                            "a canonical phase type (one of: consent, prestudy, "
                            "instructions, training, annotation, poststudy). Add "
                            "a 'type:' field to this phase." % phase_name
                        )

                # Instructions phase with an HTML file: register the HTML
                # directly as a template rather than parsing it as annotation
                # schemes.
                if phase_type == UserPhase.INSTRUCTIONS and "file" in phase and phase['file']:
                    phase_file = get_abs_or_rel_path(phase['file'], config)
                    if phase_file.endswith(('.html', '.htm')):
                        logger.debug(f"Instructions phase '{phase_name}' using HTML file: {phase_file}")
                        # Read the HTML and write it as a generated template
                        with open(phase_file, 'rt', encoding='utf-8') as f:
                            instructions_html = f.read()

                        # Wrap in a minimal page template for consistency
                        cur_program_dir = os.path.dirname(os.path.abspath(__file__))
                        from server_utils.front_end import get_html
                        html_template_file = os.path.join(cur_program_dir, 'templates', 'base_template_v2.html')
                        header_file = os.path.join(cur_program_dir, 'templates', 'header.html')
                        html_template = get_html(html_template_file, config)
                        header = get_html(header_file, config)
                        html_template = html_template.replace("{{ HEADER }}", header)
                        html_template = html_template.replace("{{ TASK_LAYOUT }}", instructions_html)
                        html_template = html_template.replace("{{annotation_codebook}}", "")
                        html_template = html_template.replace("{{annotation_task_name}}",
                                                              config.get("annotation_task_name", ""))
                        html_template = html_template.replace("{{keybindings}}", "")
                        html_template = html_template.replace("{{statistics_nav}}", "")

                        # Inject project-level base CSS
                        from server_utils.front_end import load_project_base_css_html
                        try:
                            project_css = load_project_base_css_html(config)
                        except FileNotFoundError:
                            project_css = ""
                        html_template = html_template.replace("{{ PROJECT_BASE_CSS }}", project_css)

                        site_name = (
                            "_".join(config["annotation_task_name"].split(" "))
                            + "-" + "%s.html" % phase_name
                        )
                        from potato.server_utils.generated_templates import (
                            resolve_generated_templates_dir)
                        generated_dir = resolve_generated_templates_dir(
                            config["site_dir"])
                        output_html_fname = os.path.join(generated_dir, site_name)
                        with open(output_html_fname, "wt", encoding="utf-8") as outf:
                            outf.write(html_template)

                        user_state_manager = get_user_state_manager()
                        user_state_manager.add_phase(phase_type, phase_name, site_name)
                        logger.debug(f"Registered instructions phase {phase_name} with HTML {site_name}")
                        continue

                # Training and annotation phases can work without a file
                # They use the main annotation schemes from the config.
                # Training files typically contain training data items (with
                # gold_label), not annotation schemes — so always use the main
                # annotation schemes for the training phase layout.
                if phase_type in [UserPhase.TRAINING, UserPhase.ANNOTATION]:
                    phase_labeling_schemes = config.get('annotation_schemes', [])
                    logger.debug(f"Phase {phase_name} using main annotation schemes")
                else:
                    # Other phases (prestudy, poststudy, etc.)
                    # Support instrument/instruments keys for standard survey instruments
                    phase_labeling_schemes = []

                    # Handle single instrument reference
                    if "instrument" in phase:
                        from potato.survey_instruments import get_instrument_questions
                        inst_id = phase["instrument"]
                        logger.debug(f"Phase {phase_name} loading instrument: {inst_id}")
                        phase_labeling_schemes = get_instrument_questions(inst_id)

                    # Handle multiple instruments
                    elif "instruments" in phase:
                        from potato.survey_instruments import get_instrument_questions
                        for inst_id in phase["instruments"]:
                            logger.debug(f"Phase {phase_name} loading instrument: {inst_id}")
                            phase_labeling_schemes.extend(get_instrument_questions(inst_id))

                    # Handle file reference (can be combined with instrument)
                    if "file" in phase and phase['file']:
                        phase_scheme_fname = get_abs_or_rel_path(phase['file'], config)
                        logger.debug(f"Resolved phase file for {phase_name}: {phase_scheme_fname}")
                        file_schemes = get_phase_annotation_schemes(phase_scheme_fname)
                        _check_phase_schemes(file_schemes, phase_scheme_fname,
                                             phase_name)
                        if phase_labeling_schemes:
                            # Append file schemes after instrument schemes
                            phase_labeling_schemes.extend(file_schemes)
                        else:
                            phase_labeling_schemes = file_schemes

                    # Require at least one source of questions
                    if not phase_labeling_schemes:
                        logger.error(f"Phase {phase_name} requires 'instrument', 'instruments', or 'file'")
                        raise Exception(
                            f"Phase {phase_name} requires 'instrument', 'instruments', or 'file' "
                            "to specify its annotation schemes"
                        )

                    # Survey/consent/instrument labels are author-written prose
                    # (often full sentences, any language), not machine identifiers,
                    # so don't title-case them by default. Without this, a label like
                    # "Ja, natürlich möchte ich teilnehmen" was humanized to
                    # "Ja, Natürlich Möchte Ich Teilnehmen" (F-049). An individual
                    # survey scheme can still opt back in with humanize_labels: true.
                    # (The TRAINING/ANNOTATION branch above reuses the main schemes
                    # and keeps their existing humanization behavior.)
                    for _survey_scheme in phase_labeling_schemes:
                        if isinstance(_survey_scheme, dict):
                            _survey_scheme.setdefault("humanize_labels", False)

            # Remember this phase's questions for cross-phase display_logic
            # validation after all phases have loaded (see below).
            for _s in phase_labeling_schemes:
                if isinstance(_s, dict):
                    _all_phase_schemes_for_dl.append(_s)

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
            from potato.server_utils.config_module import ConfigValidationError
            if isinstance(e, ConfigValidationError):
                raise
            # A phase that cannot be built must abort the boot, not be dropped.
            # Logging and continuing produced studies that launched and were
            # completed by annotators with the entire post-study survey
            # missing -- the only trace was one ERROR line in the startup log.
            # Same reasoning as consent/prestudy gating: a phase the author
            # asked for and did not get is never the safe outcome.
            logger.error(f"Failed to load phase '{phase_name}': {e}")
            raise ConfigValidationError(
                f"Failed to load phase '{phase_name}': {e}"
            ) from e

    # Drop the undefined phases from the order the rest of the server reads, so
    # the sequence in the config matches the sequence that actually loaded.
    if undefined_phase_names and isinstance(phases, dict) and "order" in phases:
        phases["order"] = [
            name for name in phases["order"] if name not in undefined_phase_names
        ]
        get_user_state_manager().invalidate_phase_caches()

    # Validate display_logic on SurveyFlow questions now that every phase's
    # questions are known. This covers what the config-load validator misses
    # (it only sees inline annotation_schemes, not questions loaded from phase
    # JSON/instrument files): unsupported operators, references to a question
    # that exists on no phase, and circular dependencies. References may point
    # to a question on any phase (cross-page conditions, e.g. a poststudy
    # question gated on a prestudy answer). A failure aborts startup rather than
    # silently letting broken logic reach the frontend.
    if any(s.get("display_logic") for s in _all_phase_schemes_for_dl):
        from potato.server_utils.config_module import (
            validate_display_logic_references,
            ConfigValidationError,
        )
        try:
            validate_display_logic_references(_all_phase_schemes_for_dl)
        except ConfigValidationError as dl_err:
            raise ConfigValidationError(
                f"Invalid SurveyFlow display_logic: {dl_err}"
            )

    # Stash SurveyFlow question schemes so downstream consumers (e.g. auto-export
    # server-side hidden-answer exclusion) can reach display_logic definitions,
    # which otherwise live only in external phase files, not in config.
    config['_surveyflow_schemes'] = _all_phase_schemes_for_dl

    user_state_manager = get_user_state_manager()
    logger.debug(f"[PHASE LOAD] phase_type_to_name_to_page: {user_state_manager.phase_type_to_name_to_page}")


def get_phase_annotation_schemes(filename: str) -> list[dict]:
    '''Returns the annotation schemes for a phase from a file.'''

    schemes = []
    if not os.path.exists(filename):
        raise Exception("Phase labeling schemes file %s does not exist" % filename)

    if filename.endswith(".json"):
        with open(filename, "rt", encoding="utf-8") as f:
            schemes = json.load(f)
        # Allow users to have specified a single scheme in the JSON file
        if type(schemes) != list:
            schemes = [schemes]
    elif filename.endswith(".jsonl"):
        with open(filename, 'rt', encoding='utf-8') as f:
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
        with open(filename, 'rt', encoding='utf-8') as f:
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

#: Annotation schemes whose item "text" is often just a media file path/URL.
_TEMPORAL_MEDIA_TYPES = frozenset({
    "audio_annotation",
    "video_annotation",
    "tiered_annotation",
    "temporal_grounding",
    "speech_transcript",
})

#: File extensions that mark a string as a media path even without a slash.
_MEDIA_PATH_EXTENSIONS = (
    ".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac",
    ".mp4", ".webm", ".mov", ".avi", ".mkv",
)


def _looks_like_media_path(value):
    """Heuristic: does this string look like a bare media path/URL (not prose)?

    A genuine prompt/transcript contains whitespace; a path does not. We treat a
    whitespace-free string as a path when it is a URL, contains a path separator,
    or ends in a known media extension.
    """
    if not isinstance(value, str):
        return False
    s = value.strip()
    if not s or any(c.isspace() for c in s):
        return False
    lowered = s.lower()
    if lowered.startswith(("http://", "https://", "//", "/")):
        return True
    if "/" in s or "\\" in s:
        return True
    return lowered.endswith(_MEDIA_PATH_EXTENSIONS)


def _compute_instance_text_is_media_path(annotation_schemes, item_data, displayed_text):
    """Whether the instance-text header is just the media path (so it can be hidden).

    True when a temporal-media scheme is present AND the displayed text is either
    equal to that scheme's media source field value or otherwise looks like a bare
    media path/URL. Returns False when the item carries a real prompt/transcript.
    """
    media_scheme = next(
        (s for s in (annotation_schemes or [])
         if s.get("annotation_type") in _TEMPORAL_MEDIA_TYPES),
        None,
    )
    if media_scheme is None:
        return False

    display = displayed_text.strip() if isinstance(displayed_text, str) else ""
    if not display:
        # No visible text at all — nothing to show, treat as "hide".
        return True

    source_field = (
        media_scheme.get("source_field")
        or media_scheme.get("video_key")
        or media_scheme.get("audio_key")
    )
    if source_field and isinstance(item_data, dict):
        source_value = str(item_data.get(source_field, "") or "").strip()
        if source_value and display == source_value:
            return True

    return _looks_like_media_path(display)


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

    # Handle dict inputs (for tree structures, agent traces, complex data)
    # Convert to JSON string for display — the actual rendering is handled by
    # display types (conversation_tree, web_agent_trace, live_agent, etc.)
    if isinstance(text, dict):
        import json as _json
        return _json.dumps(text, ensure_ascii=False, indent=2)

    # Handle list inputs (for dialogue or pairwise comparisons with list_as_text config)
    if isinstance(text, list):
        # `list_as_text: true` is what a config author writes after reading a
        # one-line "render list-valued fields as text": the sub-keys are not
        # obvious and turning the feature on is. A bare bool used to reach
        # `.get()` and raise AttributeError, so take it as "on, with defaults".
        list_config = config.get("list_as_text")
        if not isinstance(list_config, dict):
            list_config = {}
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
    # Remove control characters but preserve all Unicode (fixes issue #114)
    text = re.sub(r'[\x00-\x1F\x7F]', lambda m: m.group() if m.group() == '\n' else '', text)
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
    Check whether the current session has been idle longer than the timeout.

    An unstamped session counts as valid: `created_at` is written by
    :func:`init_user_state`, and a session that reached a protected route
    without going through it is a session the timeout has nothing to say about.
    Treating it as expired would sign people out for a bookkeeping gap.
    """
    stamped = session.get('last_seen_at') or session.get('created_at')
    if stamped is None:
        return True
    return datetime.now() - stamped < get_session_timeout()


#: Paths served without a session. Prefixes end in "/" and are matched with
#: startswith; everything else must match exactly.
#:
#: "/" was in this list as a prefix, and `startswith("/")` is true of every
#: path there is -- so the gate below returned early on every request and no
#: session was ever checked. A prefix list that contains the root prefix is not
#: a list.
_UNAUTHENTICATED_PATHS = frozenset({
    '/', '/auth', '/register', '/favicon.ico', '/robots.txt', '/health',
    '/logout', '/forgot-password', '/reset-password',
})
_UNAUTHENTICATED_PREFIXES = ('/static/', '/api/')


@app.before_request
def before_request():
    """
    Clear a session that has been idle past the timeout, and refresh one that
    has not. Applies only to requests that already carry a signed-in user;
    anonymous requests are the login flow's business, not this gate's.
    """
    # Skip session validation in debug mode
    if config.get("debug", False):
        return None

    path = request.path
    if path in _UNAUTHENTICATED_PATHS or path.startswith(_UNAUTHENTICATED_PREFIXES):
        return None

    if 'username' not in session:
        return None

    if not is_session_valid():
        logger.info("Session for %s expired after %s idle; clearing it",
                    session.get('username'), get_session_timeout())
        session.clear()
        return redirect(url_for('home'))

    # Idle timeout, not an absolute one: a working annotator is not signed out
    # mid-shift. Stamped per request, so the clock restarts on every action.
    session['last_seen_at'] = datetime.now()


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

def _training_page_context(user_state):
    """Template context specific to a training page.

    Training renders through the same generated page as every other phase, but the
    shared template's defaults are annotation-shaped: they hide the instance text
    outside the annotation phase, and they know nothing about practice questions.
    This supplies the difference — the question text, the progress counters, and the
    feedback from the last attempt (all of which TrainingState already persists).
    """
    training_state = user_state.get_training_state()
    instance = user_state.get_current_training_instance()

    text = ""
    instance_id = ""
    if instance is not None:
        data = instance.get_data()
        # Respect the project's configured text_key. Hardcoding
        # displayed_text/text meant an image project — whose text_key points at
        # the image URL field — produced an EMPTY training question, so the
        # canvas had no image to load even once its assets were wired up.
        text_key = config.get("item_properties", {}).get("text_key", "text")
        # `displayed_text` stays first: it is `get_displayed_text(question_text)`,
        # so for a list-valued practice item it holds the formatted HTML while
        # the raw field holds a Python list. What was broken was upstream --
        # load_training_data derived it from `text` alone and dropped the field
        # `text_key` names, so on an image project this whole chain resolved to
        # the practice question's prose. It now derives from text_key when the
        # instance carries it, which is what makes the branch below reachable.
        text = (data.get("displayed_text")
                or data.get(text_key)
                or data.get("text", ""))
        instance_id = instance.get_id()

    total = len(training_state.training_instances)
    return {
        "is_training_page": True,
        # The shared template hides #instance-text unless this is set; without it the
        # practice question never appears on screen.
        "show_instance_text": True,
        "instance_text_heading": "Training Question",
        "instance": text,
        "instance_plain_text": text,
        "instance_id": instance_id,
        "training_current_question": min(training_state.get_current_question_index() + 1,
                                         total) if total else 0,
        "training_total_questions": total,
        "training_correct_count": training_state.get_correct_answer_count(),
        "training_mistake_count": training_state.get_total_mistakes(),
        "training_show_feedback": training_state.show_feedback,
        "training_feedback": training_state.feedback_message,
        "training_feedback_type": getattr(training_state, "feedback_type", "info"),
        "training_allow_retry": training_state.allow_retry,
        # Practice questions are answered in order and there is nothing to go back to.
        "can_go_back": False,
        "jumping_to_id_disabled": True,
        "finished": training_state.get_current_question_index(),
        "total_count": total,
    }


def get_current_page_html(config, username):
    """
    Returns the HTML for the current page that the user is on.

    For phase pages (consent, instructions, etc.), this provides minimal
    context variables needed by the shared template structure.
    """
    user_state = get_user_state(username)
    phase, page = user_state.get_current_phase_and_page()

    is_annotation_page = phase == UserPhase.ANNOTATION

    usm = get_user_state_manager()
    html_fname = usm.get_phase_html_fname(phase, page)

    # Provide context variables needed by the template
    # For phase pages, many annotation-specific fields can be empty/default
    context = {
        'username': username,
        'annotation_task_name': config.get('annotation_task_name', ''),
        'annotation_codebook_url': _sanitize_codebook_url(config.get('annotation_codebook_url', '')),
        'debug_mode': config.get('debug', False),
        'ui_debug': config.get('ui_debug', False),
        'server_debug': config.get('server_debug', False),
        'debug_phase': config.get('debug_phase', None),
        'instance': '',
        'instance_plain_text': '',
        'instance_id': '',
        'instance_index': 0,
        'finished': 0,
        'total_count': user_state.get_assigned_instance_count() if hasattr(user_state, 'get_assigned_instance_count') else 0,
        'ui_config': config.get('ui_config', {}),
        'is_annotation_page': is_annotation_page,
        'annotation_instructions': config.get('annotation_instructions', ''),
        'annotation_status': 'unlabeled',
        'instance_has_annotations': False,
        'can_go_back': usm.can_user_go_back(username),
        'jumping_to_id_disabled': config.get('jumping_to_id_disabled', False),
    }
    # Phase pages render through this path rather than render_page_with_annotations,
    # so the keystroke-tracker wiring has to be repeated here. Without it, typing
    # dynamics would be captured on the annotation page only — and the endpoint
    # stamps phase/page precisely so that free-text answers in surveys and the
    # training phase can be attributed too.
    from potato.server_utils.config_module import get_keystroke_client_config
    keystroke_client_config = get_keystroke_client_config(config)
    context['keystroke_client_config'] = keystroke_client_config
    context['keystroke_logging_enabled'] = (
        keystroke_client_config["enabled"]
        and keystroke_client_config["fidelity"] != "off"
    )

    # Same for drawing telemetry, and for the same reason: the TRAINING phase
    # renders real annotation schemes through this path, so telemetry gated only
    # on the annotation path would silently collect nothing during training --
    # which is exactly where a new annotator's drawing behaviour is most worth
    # measuring.
    from potato.server_utils.config_module import (
        get_annotation_telemetry_client_config)
    telemetry_client_config = get_annotation_telemetry_client_config(config)
    context['annotation_telemetry_client_config'] = telemetry_client_config
    context['annotation_telemetry_enabled'] = (
        telemetry_client_config["enabled"]
        and telemetry_client_config["fidelity"] != "off"
    )

    # Phase pages are rendered from the SAME template as the annotation page, so
    # they need the same asset gating. Without this, `frontend_assets` defaults
    # to {} and neither fabric.js nor image-annotation.js is loaded — which made
    # image annotation completely non-functional during TRAINING: the canvas
    # element rendered and nothing ever initialized it. Audio, video, and span
    # practice questions had the same problem.
    #
    # This is the two-render-path hazard: anything conditional added to
    # base_template_v2.html must be wired here as well as in
    # render_page_with_annotations, or the feature silently works on only half
    # the workflow.
    annotation_schemes = config.get("annotation_schemes", []) or []
    # The detector resolves the template path itself.
    context['frontend_assets'] = _detect_frontend_assets_for_page(html_fname)
    context['has_image_annotation'] = any(
        scheme.get("annotation_type") == "image_annotation"
        for scheme in annotation_schemes
    )
    context['ai_enabled'] = config.get("ai_support", {}).get("enabled", False)
    # Same two-path hazard. The sidebars sit behind `is_annotation_page` as
    # well, so today this only keeps the flags defined rather than falling
    # through to Jinja's `default(false)` -- but a page that renders the
    # annotation template must carry every variable that template reads, or
    # the next person to widen that condition gets a silent no-op.
    context.update(_annotation_sidebar_flags(config))

    if phase == UserPhase.TRAINING:
        context.update(_training_page_context(user_state))
    rendered_html = render_template(html_fname, **context)
    soup = BeautifulSoup(rendered_html, "html.parser")

    phase_annotations = user_state.phase_to_page_to_label_to_value.get(phase, {}).get(page, {})
    for label_obj, value in phase_annotations.items():
        schema = label_obj.get_schema()
        label = label_obj.get_name()
        name = schema + ":::" + label

        input_fields = soup.find_all(["input", "select", "textarea"], {"name": name})
        if not input_fields:
            input_fields = soup.find_all(["input"], {"schema": schema, "label_name": label})

        for input_field in input_fields:
            if input_field is None:
                continue

            # Ranges and hidden inputs restore exactly as they do on the
            # annotation page. They were missing here, which is the "two
            # page-render paths" trap in CLAUDE.md: a `slider` or a `ranking`
            # answered on a survey page was stored server-side and then rendered
            # back at its default, so re-showing the page (a reload, or a
            # validation bounce) put the default in front of the respondent and
            # a resubmit overwrote the real answer. `data-server-set` is what
            # tells the client the value is an answer rather than a starting
            # position.
            if input_field.get('type') == 'range':
                input_field['value'] = value
                input_field['data-server-set'] = 'true'
                continue

            if input_field.get('type') == 'hidden':
                if isinstance(value, str):
                    input_field['value'] = value
                    input_field['data-server-set'] = 'true'
                continue

            if input_field.get('type') == 'checkbox' or input_field.get('type') == 'radio':
                if value:
                    if input_field.get('type') == 'radio':
                        # See the annotation-page restore below: label_name is the
                        # identity, `value` only disambiguates when several inputs
                        # share one label_name.
                        if len(input_fields) == 1 or input_field.get('value') == value:
                            input_field['checked'] = True
                    else:
                        input_field['checked'] = True

            if input_field.get('type') == 'text':
                if isinstance(value, str):
                    input_field['value'] = value

            if input_field.get('type') == 'number':
                input_field['value'] = str(value)

            if input_field.name == 'textarea':
                if isinstance(value, str):
                    input_field.string = value

            if input_field.name == 'select':
                if isinstance(value, str):
                    options = input_field.find_all("option", {"value": value})
                    if options:
                        # Same as the annotation-page path: drop the
                        # placeholder's `selected` explicitly.
                        for other in input_field.find_all("option"):
                            if other.has_attr("selected"):
                                del other["selected"]
                        options[0]["selected"] = "selected"

    # Cross-page conditional display_logic: expose answers from OTHER phase
    # pages so a question can be shown/hidden based on an answer given on an
    # earlier SurveyFlow page (e.g. a poststudy question gated on a prestudy
    # answer). Built in the same nested {schema: {label: value}} shape as the
    # client's currentAnnotations so display-logic.js can reuse one transform.
    # The current page is excluded here — its answers already flow through the
    # normal currentAnnotations pipeline and must win over prior answers.
    prior_raw = {}
    for other_phase, pages_dict in user_state.phase_to_page_to_label_to_value.items():
        for other_page, labels_dict in pages_dict.items():
            if other_phase == phase and other_page == page:
                continue
            for label_obj, value in labels_dict.items():
                try:
                    schema = label_obj.get_schema()
                    label = label_obj.get_name()
                except AttributeError:
                    continue
                prior_raw.setdefault(schema, {})[label] = value

    if prior_raw:
        # Escape "<" so an answer containing "</script>" cannot break out of the
        # inline script (BeautifulSoup does not entity-escape script contents).
        safe_json = easy_json(prior_raw).replace("<", "\\u003c")
        script_tag = soup.new_tag("script")
        script_tag.string = "window.priorPhaseAnswersRaw = " + safe_json + ";"
        target = soup.body if soup.body else soup
        target.append(script_tag)

        # The collapse in display-logic.js needs each schema's annotation_type to know
        # that, say, a multiselect answered on an earlier page collapses to the full
        # list of selected labels rather than one arbitrary member. Types for schemas
        # on the CURRENT page are read from the DOM (every generator stamps
        # data-annotation-type on the schema form); prior-phase schemas have no markup
        # here, so ship their types alongside the answers.
        prior_types = {}
        for scheme in (config.get("_surveyflow_schemes") or []):
            if isinstance(scheme, dict) and scheme.get("name") in prior_raw:
                prior_types[scheme["name"]] = scheme.get("annotation_type")
        if prior_types:
            types_json = easy_json(prior_types).replace("<", "\\u003c")
            types_tag = soup.new_tag("script")
            types_tag.string = "window.priorPhaseAnswerTypes = " + types_json + ";"
            target.append(types_tag)

    return str(soup)

def _sanitize_codebook_url(url: str) -> str:
    """Sanitize codebook URL to prevent javascript: and other dangerous protocols."""
    if not url:
        return ""
    stripped = url.strip()
    # Block dangerous URL schemes
    lower = stripped.lower().replace('\t', '').replace('\n', '').replace('\r', '')
    for scheme in ('javascript:', 'vbscript:', 'data:'):
        if lower.startswith(scheme):
            logger.warning(f"Blocked dangerous scheme in annotation_codebook_url: {scheme}")
            return ""
    return stripped


def _scheme_is_required(scheme: dict) -> bool:
    """Check if an annotation scheme is marked as required."""
    if scheme.get("required") is True:
        return True

    lr = scheme.get("label_requirement", {})
    if lr is True:
        return True
    if isinstance(lr, dict) and lr.get("required") is True:
        return True
    return False


def _scheme_has_required_annotation(user_state, instance_id: str, scheme: dict) -> bool:
    """Check whether a required scheme has any annotation value for an instance."""
    schema_name = scheme.get("name", "")

    label_annotations = user_state.instance_id_to_label_to_value.get(instance_id, {})
    for label_key, value in label_annotations.items():
        if hasattr(label_key, "get_schema") and label_key.get_schema() == schema_name:
            if value:
                return True

    span_annotations = user_state.instance_id_to_span_to_value.get(instance_id, {})
    if span_annotations:
        if isinstance(span_annotations, dict) and span_annotations:
            return True
        if isinstance(span_annotations, list) and len(span_annotations) > 0:
            return True

    return False


def _flat_annotations_for_instance(user_state, instance_id: str) -> dict:
    """`{schema: value}` for one instance, in the shape display_logic compares.

    Mirrors `flatten_phase_annotations`, which does the same job for phase
    pages; annotation pages key by `Label` objects rather than by page, so the
    flattening differs even though the comparison afterwards is identical.
    """
    flat: dict = {}
    for label_key, value in (
        user_state.instance_id_to_label_to_value.get(instance_id, {}) or {}
    ).items():
        if not hasattr(label_key, "get_schema"):
            continue
        schema = label_key.get_schema()
        name = label_key.get_name() if hasattr(label_key, "get_name") else None
        if not value:
            continue
        existing = flat.get(schema)
        # A multiselect contributes one entry per ticked label, so collect them
        # into a list; single-choice schemes keep the label name, which is what
        # `equals` is written against in a config.
        if existing is None:
            flat[schema] = name if name is not None else value
        elif isinstance(existing, list):
            existing.append(name)
        else:
            flat[schema] = [existing, name]
    return flat


def _hidden_scheme_names(user_state, instance_id: str) -> set:
    """Schemes whose `display_logic` condition is not met for this instance."""
    schemes = config.get("annotation_schemes", []) or []
    if not any(isinstance(s, dict) and s.get("display_logic") for s in schemes):
        return set()
    try:
        from potato.server_utils.display_logic import compute_hidden_schemas
        return compute_hidden_schemas(
            schemes, _flat_annotations_for_instance(user_state, instance_id))
    except Exception:
        logger.warning(
            "display_logic could not be evaluated for %s; required-answer "
            "checking will treat every scheme as visible", instance_id,
            exc_info=True)
        return set()


def _instance_meets_required_annotation_rules(user_state, instance_id: str) -> list:
    """Return the names of required schemes that are still unsatisfied.

    A scheme hidden by its own `display_logic` is skipped. Without that, a
    required follow-up behind a condition is unsatisfiable the moment the
    condition is false: the annotator cannot see the question, cannot answer
    it, and every save is refused with a 400 they are never shown. The task
    validates, previews and screenshots cleanly, so nothing catches it before
    an annotator is stuck on the first item that takes the other branch.

    `display_logic` plus `required` is the natural way to write a gated
    follow-up, which is why this has to work rather than be documented around.
    """
    hidden = _hidden_scheme_names(user_state, instance_id)
    unsatisfied = []
    for scheme in config.get("annotation_schemes", []):
        name = scheme.get("name", "unknown")
        if name in hidden:
            continue
        if _scheme_is_required(scheme) and not _scheme_has_required_annotation(user_state, instance_id, scheme):
            unsatisfied.append(name)
    return unsatisfied


def _is_user_adjudicator(username: str) -> bool:
    """Check if a user is an authorized adjudicator."""
    adj_mgr = get_adjudication_manager()
    if adj_mgr and adj_mgr.adj_config.enabled:
        return adj_mgr.is_adjudicator(username)
    return False


def _annotator_dashboard_enabled() -> bool:
    """Whether the opt-in annotator progress dashboard is enabled (default off).

    Accepts both ``annotator_dashboard: true`` and the dict form
    ``annotator_dashboard: {enabled: true, ...}``.
    """
    raw = config.get("annotator_dashboard", False)
    if raw is True:
        return True
    if isinstance(raw, dict):
        return bool(raw.get("enabled", False))
    return False


_SIDEBAR_GATE_WARNED: set[str] = set()


def _annotation_sidebar_flags(cfg) -> dict:
    """Which of the three universal sidebars this task actually has.

    Memos, search-and-claim and the codebook tray used to be *self-gating*: the
    template loaded all three on every annotation page and each one probed its
    own API to find out whether the feature was on. Almost no task enables any
    of them, so the common case was nine failed requests per page view -- five
    503s from the codebook blueprint, two from memos, a 403 from search -- and
    a console noisy enough to hide a real error.

    The server already knows the answer, so it says so here and the template
    omits the markup and the script entirely. Each predicate is imported from
    the blueprint that enforces it, so the client and the API cannot disagree
    about what is enabled.
    """
    def gate(name, fn):
        # A broken subsystem degrades to "off", matching what already happens
        # to its blueprint: routes.py registers all three inside a try, so an
        # import failure has always meant the feature is absent. Warn once
        # rather than per request -- this runs on every page render.
        try:
            return bool(fn())
        except Exception:
            if name not in _SIDEBAR_GATE_WARNED:
                _SIDEBAR_GATE_WARNED.add(name)
                logger.warning(
                    "%s gate is unavailable; the sidebar will stay off", name,
                    exc_info=True)
            return False

    def memos():
        from potato.memos.api import memos_enabled
        return memos_enabled(cfg)

    def codebook():
        from potato.codebook.api import codebook_enabled
        return codebook_enabled(cfg)

    def search_claim():
        from potato.search.service import search_settings
        return (search_settings(cfg) or {}).get("annotator_claim")

    return {
        "memos_enabled": gate("memos", memos),
        "codebook_ui_enabled": gate("codebook", codebook),
        "search_claim_enabled": gate("search", search_claim),
    }


def render_page_with_annotations(username: str):
    '''
    When annotating, shows the current instance to the user with any annotations
    they may have made. This method is called when the user is in the annotation
    phase and is currently annotating.
    '''

    # Hacky nonsense
    global emphasis_corpus_to_schemas

    user_state = get_user_state_manager().get_user_state(username)
    phase, page = user_state.get_current_phase_and_page()

    is_annotation_page = phase == UserPhase.ANNOTATION

    item = user_state.get_current_instance()
    if item is None:
        logger.warning(
            f"User {username} has no valid current instance after loading state"
        )
        if not user_state.has_remaining_assignments():
            get_user_state_manager().advance_phase(username)
        return redirect(url_for("home"))

    instance_id = item.get_id()

    # Extract pre-annotation data if quality control is enabled
    pre_annotation_data = None
    qc_manager = get_quality_control_manager()
    if qc_manager:
        pre_annotation_data = qc_manager.extract_pre_annotations(instance_id, item.get_data())

    # LLM-judge inline suggestion (judge ↔ human alignment). Reads a persisted
    # judge prediction for this instance/schema; optionally computes on demand.
    judge_prediction = _get_inline_judge_prediction(instance_id, item)

    # Signal-based triage: why was this item prioritized in the queue?
    triage_info = _get_triage_info(item)

    # DEBUG: Add detailed logging
    logger.debug(f"=== RENDER_PAGE_WITH_ANNOTATIONS START ===")
    logger.debug(f"Username: {username}")
    logger.debug(f"User state current_instance_index: {user_state.get_current_instance_index()}")
    logger.debug(f"User state instance_id_ordering: {user_state.instance_id_ordering}")
    logger.debug(f"Current instance ID: {instance_id}")

    # print('instance_id: ', instance_id)

    # directly display the prepared displayed_text
    item_data = item.get_data() if hasattr(item, "get_data") else {}
    text_key = config.get("item_properties", {}).get("text_key", "text")
    raw_text = None
    if isinstance(item_data, dict):
        raw_text = item_data.get("displayed_text")
        if raw_text is None:
            raw_text = item_data.get(text_key, item_data.get("text"))

    if raw_text is None:
        raw_text = item.get_displayed_text() if hasattr(item, "get_displayed_text") else item.get_text()

    text = raw_text if "displayed_text" in (item_data or {}) else get_displayed_text(raw_text)
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

    # Include full instance data for dynamic schemas (extractive_qa, text_edit,
    # error_span, card_sort, conjoint) that need fields beyond text_key
    if item_data and isinstance(item_data, dict):
        var_elems["instance_data"] = {
            k: v for k, v in item_data.items()
            if isinstance(v, (str, int, float, bool, list))
        }
        # Pairwise candidates come from the item's own data and are laid out by
        # the client in the order it receives them, so swapping them means
        # permuting the list HERE -- there is no markup to reorder afterwards.
        # Always showing A before B is the position bias the whole feature
        # exists for: it does not cancel across annotators, it inflates
        # agreement while biasing the estimate.
        _apply_pairwise_order(var_elems["instance_data"], user_state,
                              username, instance_id)

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
    if not span_annotations:
        # Span pre-annotations have to be applied HERE, not in the soup walk
        # below that handles every other schema type. Spans are not an input
        # value: they are markup baked into the instance text, and by the time
        # that walk runs the text has already been rendered. Without this a
        # config with `pre_annotation.enabled` and a span scheme fell through
        # to "not yet supported" and showed the annotator nothing -- which is
        # exactly what an imported brat/CoNLL/QDPX project produces.
        span_annotations = _span_annotations_from_pre_annotations(
            pre_annotation_data, config)
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

    # Pass BWS items data to frontend JS
    if config.get("bws_config") or config.get("ibws_config"):
        var_elems["bws_items"] = item.get_data().get("_bws_items", [])
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
    # annotation page (survey pages, prestudy pass or fail page).
    # When the user's cohort binds its own annotation schemes, serve that
    # cohort's pre-generated site file; otherwise fall back to the default.
    html_file = config["site_file"]
    cohort_site_files = config.get("cohort_site_files") or {}
    if cohort_site_files:
        try:
            from potato.server_utils.cohort_schemes import get_cohort_scheme_resolver
            _cohort = get_cohort_scheme_resolver().get_cohort_for_user(username)
            if _cohort and _cohort in cohort_site_files:
                html_file = cohort_site_files[_cohort]
        except Exception as e:
            logger.debug(f"Cohort site-file selection skipped: {e}")

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
    # Get the number of completed annotations and remaining assignable items.
    #
    # Both halves count dataset items only. Attention checks and gold items are
    # injected by the platform, not drawn from the pool, so they are absent from
    # the denominator -- counting them in the numerator walked the counter past
    # its own total ("13/12", "15/12") on a 12-item study with four injected
    # items.
    finished_count = count_dataset_items(
        get_user_state(username).get_annotated_instance_ids()
    )
    # Their own outstanding assignments AND what is still free in the pool.
    # Counting only the pool told every annotator after the first that they
    # were 100% done from their first save: a hold counts against an item's
    # cap, so with two annotators on six items the pool is empty for the
    # second one while their ordering holds all six.
    remaining_count = count_dataset_items(
        get_item_state_manager().get_progress_pending_ids_for_user(
            get_user_state(username))
    )
    # Total = finished + remaining (so counter shows "X / Total" not "X / Remaining")
    total_count = finished_count + remaining_count

    # Cap total by max_assignments if set (so progress shows "3/6" not "3/100")
    max_assignments = get_user_state(username).get_max_assignments()
    if max_assignments >= 0:
        total_count = min(total_count, max_assignments)

    # Determine annotation status for the status badge (three-state)
    annotation_status = "unlabeled"
    if user_state.has_annotated(instance_id):
        unsatisfied = _instance_meets_required_annotation_rules(user_state, instance_id)
        annotation_status = "labeled" if not unsatisfied else "in_progress"
    instance_has_annotations = (annotation_status != "unlabeled")

    # Get UI configuration from config
    ui_config = config.get("ui", {})
    # Resolve the schemes for this user's cohort (falls back to the global
    # annotation_schemes when per-cohort schemas are not configured).
    try:
        from potato.server_utils.cohort_schemes import get_cohort_scheme_resolver
        annotation_schemes = get_cohort_scheme_resolver().get_schemes_for_user(username)
    except Exception:
        annotation_schemes = config.get("annotation_schemes", [])

    # Add layout configuration to ui_config for JavaScript access
    if config.get("layout"):
        ui_config = dict(ui_config)  # Make a copy to avoid modifying the original
        ui_config["layout"] = config["layout"]

    # Detect if any annotation scheme is video_annotation type (or tiered_annotation with video media)
    # This is used to customize the display (show "Video to Annotate:" instead of "Text to Annotate:")
    has_video_annotation = any(
        scheme.get("annotation_type") == "video_annotation"
        or (scheme.get("annotation_type") == "tiered_annotation" and scheme.get("media_type") == "video")
        for scheme in annotation_schemes
    )

    # Detect if any annotation scheme is audio_annotation type (or tiered_annotation with audio media)
    # This is used to customize the display (hide "Text to Annotate:" for audio-focused tasks)
    has_audio_annotation = any(
        scheme.get("annotation_type") == "audio_annotation"
        or (scheme.get("annotation_type") == "tiered_annotation" and scheme.get("media_type") == "audio")
        for scheme in annotation_schemes
    )

    # Detect if any annotation scheme is image_annotation type
    # This is used to customize the display (show "Image to Annotate:" instead of "Text to Annotate:")
    has_image_annotation = any(
        scheme.get("annotation_type") == "image_annotation"
        for scheme in annotation_schemes
    )

    # For temporal media schemes the item's "text" is often just the media file
    # path/URL. When that is the case we hide the redundant header (the player IS
    # the content); but if the item has a genuine prompt/transcript we still show
    # it. See base_template_v2.html instance-display branches.
    instance_text_is_media_path = _compute_instance_text_is_media_path(
        annotation_schemes, item_data, original_plain_text
    )

    # Initialize display_html before it's referenced by _detect_frontend_assets_for_page
    display_html = ""

    frontend_assets = _detect_frontend_assets_for_page(html_file, display_html)

    # Check if AI support is enabled (for conditional loading of visual_ai_assistant.js)
    ai_enabled = config.get("ai_support", {}).get("enabled", False)

    # Check if agent proxy is configured (for conditional loading of agent-chat.js/css).
    # Presence alone used to be enough, so `enabled: false` still loaded the
    # assets and initialised the backend -- harmless while nothing renders,
    # and not once something does.
    agent_proxy_enabled = _agent_proxy_enabled(config)

    # Check if chat support is enabled (for conditional loading of llm-chat-sidebar assets)
    chat_enabled = config.get("chat_support", {}).get("enabled", False)

    # Boundary Lab (counterfactual boundary probing): conditional assets + JS config
    boundary_client_config = None
    boundary_block = config.get("boundary_probing", {})
    if boundary_block.get("enabled", False):
        from potato.boundary import get_boundary_manager
        boundary_manager = get_boundary_manager()
        if boundary_manager and boundary_manager.boundary_config.schema:
            bc = boundary_manager.boundary_config
            boundary_client_config = {
                "schema": bc.schema,
                "debounce_ms": bc.debounce_ms,
                "rationale_on_flip": bc.rationale_on_flip,
            }
    boundary_enabled = boundary_client_config is not None
    # Keystroke logging (typing dynamics on free-text fields): conditional asset
    # + JS config. Detection thresholds stay server-side; see
    # get_keystroke_client_config.
    from potato.server_utils.config_module import get_keystroke_client_config
    keystroke_client_config = get_keystroke_client_config(config)
    keystroke_logging_enabled = (
        keystroke_client_config["enabled"]
        and keystroke_client_config["fidelity"] != "off"
    )
    # Annotation telemetry (drawing dynamics on geometry schemas): conditional
    # asset + JS config. Screening thresholds stay server-side; see
    # get_annotation_telemetry_client_config.
    from potato.server_utils.config_module import (
        get_annotation_telemetry_client_config)
    annotation_telemetry_client_config = get_annotation_telemetry_client_config(config)
    annotation_telemetry_enabled = (
        annotation_telemetry_client_config["enabled"]
        and annotation_telemetry_client_config["fidelity"] != "off"
    )
    # Truth Serum (surprisingly-popular scoring): conditional assets + JS config
    truth_serum_client_config = None
    if config.get("truth_serum", {}).get("enabled", False):
        from potato.truth_serum import get_truth_serum_manager
        ts_manager = get_truth_serum_manager()
        if ts_manager and ts_manager.ts_config.schema:
            truth_serum_client_config = {
                "schema": ts_manager.ts_config.schema,
                "question": ts_manager.ts_config.question,
            }
    truth_serum_enabled = truth_serum_client_config is not None
    # Think-Aloud (voice rationales): conditional assets + JS config
    thinkaloud_client_config = None
    if config.get("thinkaloud", {}).get("enabled", False):
        from potato.thinkaloud import get_thinkaloud_manager
        ta_manager = get_thinkaloud_manager()
        if ta_manager and ta_manager.ta_config.schema:
            ta = ta_manager.ta_config
            thinkaloud_client_config = {
                "schema": ta.schema,
                "chunk_seconds": ta.chunk_seconds,
                "require_spoken_label": ta.require_spoken_label,
            }
    thinkaloud_enabled = thinkaloud_client_config is not None

    # Check if live agent is enabled (for conditional loading of live-agent assets)
    live_agent_enabled = bool(config.get("live_agent"))

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

    frontend_assets = _detect_frontend_assets_for_page(html_file, display_html)

    # Warm the HTTP cache for the next instance's media while the annotator
    # works on this one, so Next does not begin with a blank wait.
    prefetch_urls = _next_instance_prefetch_urls(user_state)

    # Get IBWS round info if active
    ibws_round_info = None
    if config.get("ibws_config"):
        from potato.ibws_manager import get_ibws_manager
        ibws_mgr = get_ibws_manager()
        if ibws_mgr:
            ibws_round_info = ibws_mgr.get_round_info()

    rendered_html = render_template(
        html_file,
        username=username,
        # This is what instance the user is currently on (may contain span HTML)
        instance=text,
        # Original plain text without span HTML (for data-original-text attribute)
        instance_plain_text=original_plain_text,
        instance_obj=item,
        # Full record dict so schemas like process_reward / trajectory_eval
        # can bind to structured fields (e.g. structured_turns) via the
        # [data-instance-json] element. Transcript-consuming schemes also get a
        # normalized "_transcripts" index attached here, so they accept every
        # format the audio_dialogue display does (see transcripts/binding.py).
        instance_record=enrich_transcript_record(
            item.get_data(), config, base_dir=config.get("task_dir")
        ),
        instance_id=instance_id,
        instance_index=user_state.get_current_instance_index(),
        # The counter the annotator reads. It must be the same count the
        # denominator is built from -- `get_annotation_count()` includes the
        # injected quality-control items, which are absent from `total_count`,
        # so the bar walked past its own total.
        finished=finished_count,
        total_count=total_count,
        alert_time_each_instance=config.get("alert_time_each_instance", 10000000),
        statistics_nav=all_statistics,
        var_elems=var_elems_html,
        custom_js=custom_js,
        # Pass annotation schemes to the template
        annotation_schemes=annotation_schemes,
        annotation_task_name=config["annotation_task_name"],
        debug=config.get("debug", False),
        ui_config=ui_config,
        has_video_annotation=has_video_annotation,
        has_audio_annotation=has_audio_annotation,
        has_image_annotation=has_image_annotation,
        instance_text_is_media_path=instance_text_is_media_path,
        ai_enabled=ai_enabled,
        # Pre-annotation data for model predictions
        pre_annotations=pre_annotation_data,
        pre_annotation_config=pre_annotation_config,
        # LLM-judge inline suggestion (judge ↔ human alignment)
        judge_prediction=judge_prediction,
        # Signal-based triage badge (why this item was prioritized)
        triage_info=triage_info,
        # Instance display (new explicit display mode)
        has_instance_display=has_instance_display,
        display_html=display_html,
        display_fields=display_template_vars.get("display_fields", {}),
        display_raw=display_template_vars.get("display_raw", {}),
        span_targets=display_template_vars.get("span_targets", []),
        multi_span_mode=display_template_vars.get("multi_span_mode", False),
        frontend_assets=frontend_assets,
        prefetch_urls=prefetch_urls,
        # Agent proxy (for conditional loading of agent-chat assets)
        agent_proxy_enabled=agent_proxy_enabled,
        # Chat support (for conditional loading of llm-chat-sidebar assets)
        chat_enabled=chat_enabled,
        # Boundary Lab (counterfactual boundary probing)
        boundary_enabled=boundary_enabled,
        keystroke_logging_enabled=keystroke_logging_enabled,
        keystroke_client_config=keystroke_client_config,
        annotation_telemetry_enabled=annotation_telemetry_enabled,
        annotation_telemetry_client_config=annotation_telemetry_client_config,
        boundary_client_config=boundary_client_config,
        # Truth Serum (surprisingly-popular scoring)
        truth_serum_enabled=truth_serum_enabled,
        truth_serum_client_config=truth_serum_client_config,
        # Think-Aloud (voice rationales, rule-based label phrases)
        thinkaloud_enabled=thinkaloud_enabled,
        thinkaloud_client_config=thinkaloud_client_config,
        # Live agent (for conditional loading of live-agent assets)
        live_agent_enabled=live_agent_enabled,
        # Annotation instructions (collapsible banner)
        annotation_instructions=config.get("annotation_instructions", ""),
        # Adjudication: show link for adjudicators
        is_adjudicator=_is_user_adjudicator(username),
        # Annotator progress dashboard nav link (opt-in, off by default)
        annotator_dashboard_enabled=_annotator_dashboard_enabled(),
        annotation_codebook_url=_sanitize_codebook_url(config.get("annotation_codebook_url", "")),
        # Annotation status indicator (three-state: labeled/in_progress/unlabeled)
        annotation_status=annotation_status,
        instance_has_annotations=instance_has_annotations,
        # if this is an annotation page
        is_annotation_page=is_annotation_page,
        # IBWS round info (for round banner)
        ibws_round_info=ibws_round_info,
        # Hide back button when on first instance with no previous phase
        can_go_back=get_user_state_manager().can_user_go_back(username),
        # Hide jump-to-ID navigation controls when disabled
        jumping_to_id_disabled=config.get("jumping_to_id_disabled", False),
        # Hotkey review mode (auto-advance when all required schemas complete)
        review_mode=config.get("review_mode", {}) or {},
        # Universal sidebars (memos / search-and-claim / codebook tray). Off
        # unless the task enables them; see _annotation_sidebar_flags.
        **_annotation_sidebar_flags(config),
        # ai=ai_hints,
        **kwargs
    )

    # Parse the page so we can programmatically reset the annotation state
    # to what it was before
    soup = BeautifulSoup(rendered_html, "html.parser")

    # If the user has annotated this before, walk the DOM and fill out what they
    # did
    annotations = get_annotations_for_user_on(username, instance_id)

    # If no annotations yet, check for pre-annotations (model predictions).
    # NOTE: get_annotations_for_user_on returns an empty dict {} (not None) for a
    # user with no annotations, so guard on falsiness rather than `is None`.
    if not annotations and pre_annotation_data:
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
                # predicted_value should be a label name. Store the LABEL NAME as
                # the value (not the label2value index): the renderer below checks
                # a radio when input.value == value, and the radio's value
                # attribute is the label name. This matches how a returning
                # user's restored annotations are stored.
                known = scheme.get('label2value', {})
                for name in _prelabel_names(predicted_value):
                    if name in known:
                        annotations[schema_name][name] = name
            elif scheme['annotation_type'] in ['text']:
                if "labels" not in scheme:
                    annotations[schema_name]['text_box'] = str(predicted_value)
            elif scheme['annotation_type'] in ['likert', 'slider', 'number']:
                # A likert with an explicit `labels:` list renders as a RADIO
                # group -- `generate_likert_layout` switches on exactly this
                # condition -- so its inputs carry the label names and nothing
                # reads a value stored under "slider". Seeding one checked no
                # button and logged nothing: the item came up blank while the
                # radio scheme beside it came up pre-filled.
                if scheme['annotation_type'] == 'likert' and 'labels' in scheme:
                    known = {(l if isinstance(l, str) else l.get('name')): True
                             for l in scheme['labels']}
                    matched = [name for name in _prelabel_names(predicted_value)
                               if name in known]
                    for name in matched:
                        annotations[schema_name][name] = name
                    if not matched:
                        logger.warning(
                            f"Pre-annotation '{predicted_value}' for likert "
                            f"schema '{schema_name}' matches none of its "
                            f"labels {sorted(str(k) for k in known)}; nothing "
                            f"will be pre-selected")
                else:
                    annotations[schema_name]['slider'] = str(predicted_value)
            elif scheme['annotation_type'] == 'image_annotation':
                # Image annotations live in a single hidden input under the
                # "_data" label. The DOM walk below has a dedicated fallback for
                # it (`if not input_fields and label == "_data"`), which sets the
                # value plus data-server-set='true' -- exactly the path a
                # returning user's saved annotations already take, and which
                # ImageAnnotationManager._loadExistingAnnotations() deserializes.
                #
                # The value must be a JSON *array* of client-shaped objects; see
                # potato.export.cv_utils.to_client_object.
                if isinstance(predicted_value, str):
                    annotations[schema_name]['_data'] = predicted_value
                elif isinstance(predicted_value, list):
                    annotations[schema_name]['_data'] = json.dumps(predicted_value)
                else:
                    logger.warning(
                        f"Pre-annotation for image schema {schema_name} must be a "
                        f"list of annotation objects or a JSON string, got "
                        f"{type(predicted_value).__name__}"
                    )
            elif scheme['annotation_type'] == 'span':
                # Already applied, further up, by
                # _span_annotations_from_pre_annotations(). Spans are markup in
                # the instance text rather than an input value, so they cannot
                # be set by this DOM walk -- the text was rendered before it.
                pass
            else:
                logger.debug(f"Pre-annotation not yet supported for {scheme['annotation_type']}")

    # convert the label suggestions into annotations for front-end rendering
    # (empty dict, like None, means "no user annotations yet")
    if not annotations and schema_content_to_prefill:
        scheme_dict = {}
        annotations = defaultdict(dict)
        for it in config['annotation_schemes']:
            if it['annotation_type'] in ['radio', 'multiselect']:
                it['label2value'] = {(l if type(l) == str else l['name']):str(i+1) for i,l in enumerate(it['labels'])}
            scheme_dict[it['name']] = it
        for s in schema_content_to_prefill:
            if scheme_dict[s['name']]['annotation_type'] in ['radio', 'multiselect']:
                # Store the label NAME as value so the renderer matches the
                # radio/checkbox input's value attribute (not the index).
                annotations[s['name']][s['label']] = s['label']
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

                    # If it's a range input (slider, soft_label, vas, constant_sum
                    # in slider mode), set the value attribute so loadAnnotations()
                    # reads it back -- and mark it server-set.
                    #
                    # The flag is not decoration: a range always reports a value, so
                    # loadAnnotations() and validateRequiredFields() both treat one
                    # as an answer only when data-server-set or data-modified says
                    # where the value came from. Setting the value without the flag
                    # meant a stored slider answer was rendered but not adopted, so
                    # a *required* slider the annotator had already answered blocked
                    # Next for good the moment they navigated back to it.
                    if input_field.get('type') == 'range':
                        input_field['value'] = value
                        input_field['data-server-set'] = 'true'
                        continue

                    if input_field.get('type') == 'checkbox' or input_field.get('type') == 'radio':
                        if value:
                            if input_field.get('type') == 'radio':
                                # label_name is the identity; `value` is only a
                                # tie-break for the rare case where several inputs
                                # share one label_name. Requiring an exact value match
                                # here means any change to how a value is derived
                                # silently stops old answers restoring — a likert
                                # stored under sequential_key_binding, for instance,
                                # kept its label_name but had its value rewritten.
                                if len(input_fields) == 1 or input_field.get('value') == value:
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
                                # Clear the placeholder's `selected` rather than
                                # relying on "the last selected option wins" to
                                # override it.
                                for other in input_field.find_all("option"):
                                    if other.has_attr("selected"):
                                        del other["selected"]
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

    # Record which order every ordered scheme's options are shown in, and
    # shuffle the ones configured for it.
    #
    # Recording happens whether or not randomization is on. A fixed order
    # biases every annotator the same way, which INFLATES agreement while
    # biasing the estimate -- so a study that ran without randomization can
    # only be corrected afterwards if we wrote down what was actually shown.
    from potato.server_utils import presentation_order as _order

    shown_orders = _order.orders_for_item(
        config.get('annotation_schemes', []), username, instance_id)
    # Re-read what comes back: an item rendered before is answered against the
    # order it was FIRST shown in, not the one we would derive now.
    shown_orders = _order.record(user_state, instance_id, shown_orders)

    randomized = {
        it['description']: shown_orders.get(it.get('name'))
        for it in config.get('annotation_schemes', [])
        if _order.wants_randomization(it) and shown_orders.get(it.get('name'))
    }
    if randomized:
        # Called ONCE, outside the loop. It used to sit inside it, so the soup
        # was re-shuffled once per configured scheme with a partially-built
        # name list -- and with a seed from the builtin hash(), which is salted
        # per process, so the order changed on every server restart.
        soup = randomize_options(soup, randomized)

    # If the admin has turned on AI hints, add them to the page
    soup = add_ai_hints(soup, instance_id)

    rendered_html = str(soup)

    # Filter options per instance based on dynamic_options config
    dynamic_option_schemes = [
        s for s in config.get('annotation_schemes', [])
        if s.get('dynamic_options') and s['annotation_type'] in ('radio', 'multiselect', 'select')
    ]
    if dynamic_option_schemes:
        soup = filter_dynamic_options(soup, dynamic_option_schemes, item.get_data())
        rendered_html = str(soup)

    # Populate dynamic multirate options from instance data
    has_dynamic_multirate = any(
        scheme.get('options_from_data')
        for scheme in config.get('annotation_schemes', [])
        if scheme.get('annotation_type') == 'multirate'
    )
    if has_dynamic_multirate:
        from potato.server_utils.schemas.multirate import populate_dynamic_multirate
        rendered_html = populate_dynamic_multirate(rendered_html, item.get_data())

    return rendered_html


def _get_inline_judge_prediction(instance_id, item):
    """Return a judge suggestion dict for the inline display, or None.

    Gated by ``judge_alignment.inline.enabled``. Prefers a persisted prediction
    (admin pre-runs the batch); computes on demand only if
    ``judge_alignment.inline.compute_on_demand`` is set. Shape mirrors solo
    mode's ``llm_prediction``: {label, confidence, reasoning, schema,
    prompt_version, running}.
    """
    ja = config.get("judge_alignment", {}) or {}
    inline = ja.get("inline", {}) or {}
    if not inline.get("enabled"):
        return None
    try:
        from potato.server_utils import judge_alignment as ja_mod
        schemas = ja_mod.judge_scoped_schemas(config)
        # Optional inline schema allow-list.
        allow = set(inline.get("schemas", []) or [])
        if allow:
            schemas = [s for s in schemas if s.get("name") in allow]
        if not schemas:
            return None
        schema_info = schemas[0]
        schema_name = schema_info.get("name")

        # 1) persisted prediction for the latest prompt version
        preds = ja_mod.load_predictions(config)
        version = ja_mod.latest_prompt_version(config)
        pred = (preds.get(version, {}) or {}).get(f"{instance_id}::{schema_name}") if version else None

        # 2) optional on-demand compute
        if pred is None and inline.get("compute_on_demand"):
            from potato.ai.judge import JudgeService
            svc = JudgeService(config)
            jp = svc.judge_instance(instance_id, schema_info, item.get_text())
            if jp is not None:
                ja_mod.save_prediction(config, jp)
                pred = jp.to_dict()

        if not pred:
            return None

        running = ja_mod.running_agreement(config, schema_name)
        return {
            "label": pred.get("predicted_label"),
            "confidence": pred.get("confidence", 0.0),
            "reasoning": pred.get("reasoning", ""),
            "schema": schema_name,
            "prompt_version": pred.get("prompt_version", ""),
            "running": running,
        }
    except Exception as e:
        logger.warning(f"Inline judge prediction failed for {instance_id}: {e}")
        return None


def _get_triage_info(item):
    """Return a triage badge dict for the inline display, or None.

    Gated by ``triage.show_badge`` (default true when triage is enabled). Reads
    the priority/reason stored on the item's metadata by the triage scorer at
    load/ingestion time. Only returns something when the item carries a reason
    (i.e. a rule flagged it), so unflagged items show no banner.
    """
    triage_cfg = config.get("triage", {}) or {}
    if not triage_cfg.get("enabled"):
        return None
    if not triage_cfg.get("show_badge", True):
        return None
    try:
        reason = item.get_metadata("triage_reason")
        if not reason:
            return None
        return {
            "reason": reason,
            "rule": item.get_metadata("triage_rule"),
            "priority": item.get_metadata("triage_priority"),
        }
    except Exception as e:
        logger.warning(f"Triage info failed for {item.get_id()}: {e}")
        return None


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
    schemes = config.get("annotation_schemes", [])
    if not schemes:
        logger.warning("Cannot generate AI hints: no annotation_schemes configured")
        return ""
    description = schemes[0].get("description", "")
    annotation_type = schemes[0].get("annotation_type", "")
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

    # Add layout configuration to ui_config for JavaScript access
    if config.get("layout"):
        ui_config = dict(ui_config)  # Make a copy to avoid modifying the original
        ui_config["layout"] = config["layout"]

    return render_template(
        html_fname,
        instance_id=instance_id,
        instance_data=item_data,
        instance_record=item_data,
        annotations=annotations,
        span_annotations=span_annotations,
        progress=progress,
        username=username,
        ui_config=ui_config,
        annotation_codebook_url=_sanitize_codebook_url(config.get("annotation_codebook_url", "")),
    )

def _apply_pairwise_order(instance_data, user_state, username, instance_id):
    """
    Permute a pairwise scheme's candidate list, and record where each came from.

    The record is a list of SOURCE INDICES, not label names: the candidates are
    per-item text, so "this annotator saw the item that was second in the data
    first" is the only fact an analyst can condition on afterwards.

    Reuses an order already recorded for this item rather than deriving a fresh
    one, so a reload shows the same arrangement -- an annotator shown a
    different pairing on every visit is being asked a different question each
    time.
    """
    from potato.server_utils import presentation_order as _order

    for scheme in config.get('annotation_schemes', []) or []:
        name = scheme.get("name")
        if not name:
            continue
        order = _order.item_order(scheme, instance_data, username, instance_id)
        if not order:
            continue

        recorded = _order.record(user_state, instance_id, {name: order}).get(name)
        if recorded and len(recorded) == len(order):
            try:
                order = [int(i) for i in recorded]
            except (TypeError, ValueError):
                logger.warning("Ignoring a malformed recorded order for %s/%s",
                               instance_id, name)

        items_key = scheme.get("items_key", "text")
        items = instance_data.get(items_key)
        if isinstance(items, list) and len(items) == len(order):
            instance_data[items_key] = [items[i] for i in order]


def randomize_options(soup, orders):
    """
    Reorder a scheme's options to match an order decided upstream.

    Args:
        soup: The rendered page.
        orders: ``{legend text: [label names in the order to show]}``, from
            :func:`potato.server_utils.presentation_order.orders_for_item`.

    Three things changed here, each of which had made the feature not work:

    1. **The order is an input, not a decision.** It used to shuffle in place
       with ``random.seed(seed)``. That both reached into the global random
       stream every other caller in the process shares, and left the server
       unable to say what it had shown -- so the order could never be recorded
       and a study could never be corrected for position bias afterwards.
    2. **The seed is stable.** It came from the builtin ``hash()``, which is
       salted per process, so every option set re-ordered on each server
       restart -- an annotator returning to an item was asked a different
       question. It also collapsed to nine distinct values, so annotators
       collided.
    3. **It runs once.** The call sat inside the loop that built its own
       argument, so it re-shuffled the soup once per configured scheme.

    Matching is still by legend text, which is the scheme ``description``,
    because that is what the generated markup carries. Two schemes sharing a
    description are therefore reordered together; that is a pre-existing
    limitation of the markup, not of the ordering.
    """
    if not orders:
        return soup

    fieldsets = soup.find_all('fieldset')
    if not fieldsets:
        logger.debug("No fieldsets found.")
        return soup

    def reorder(nodes, wanted, key):
        """Nodes in `wanted` order; anything unnamed keeps its relative place."""
        by_name = {}
        for node in nodes:
            name = key(node)
            if name is not None:
                by_name.setdefault(name, []).append(node)
        ordered = []
        for name in wanted:
            ordered.extend(by_name.pop(name, []))
        # An option present in the DOM but absent from the recorded order --
        # a dynamic option, or a config edited mid-study. Appending rather
        # than dropping it keeps the annotator able to answer.
        for leftovers in by_name.values():
            ordered.extend(leftovers)
        return ordered

    for fieldset in fieldsets:
        legend = fieldset.find('legend')
        wanted = orders.get(legend.string) if legend else None
        if not wanted:
            continue

        parent_form = fieldset.find_parent('form')
        annotation_type = parent_form.get('data-annotation-type', '') if parent_form else ''

        if annotation_type == 'multirate':
            table = fieldset.find('table')
            if not table:
                logger.debug("Table not found within the fieldset.")
                continue
            rows = table.find_all('tr')[1:]
            for row in reorder(rows, wanted, _row_label):
                table.append(row)

        elif annotation_type == 'radio':
            container = (fieldset.find('div', class_='shadcn-radio-options')
                         or fieldset)
            options = container.find_all('div', class_='shadcn-radio-option',
                                         recursive=False)
            if not options:
                logger.warning(
                    "Randomization asked for on radio %r but no option "
                    "elements were found; the configured order is what was "
                    "shown.", legend.string)
            for div in reorder(options, wanted, _option_label):
                container.append(div)

        elif annotation_type == 'multiselect':
            grid = fieldset.find('div', class_='shadcn-multiselect-grid') or fieldset
            # `shadcn-multiselect-item` is what the generator emits. This
            # looked for `-option`, matched nothing, and reordered nothing --
            # so `option_randomization: true` on a multiselect was inert, and
            # silently so: the order was computed, recorded as the order shown,
            # and then not shown. The recorded orders are wrong for any study
            # that ran with it.
            options = grid.find_all('div', class_='shadcn-multiselect-item',
                                    recursive=False)
            if not options:
                logger.warning(
                    "Randomization asked for on multiselect %r but no option "
                    "elements were found; the configured order is what was "
                    "shown.", legend.string)
            for div in reorder(options, wanted, _option_label):
                grid.append(div)

        elif annotation_type == 'select':
            select_el = fieldset.find('select')
            if not select_el:
                continue
            placeholder = None
            shuffleable = []
            for opt in select_el.find_all('option'):
                if not placeholder and (opt.get('value', '') == ''
                                        or opt.get('disabled') is not None):
                    placeholder = opt
                else:
                    shuffleable.append(opt)
            ordered = reorder(shuffleable, wanted,
                              lambda o: o.get('value') or (o.string or '').strip())
            select_el.clear()
            if placeholder:
                select_el.append(placeholder)
            for opt in ordered:
                select_el.append(opt)
        else:
            logger.debug("Unsupported annotation type for randomization: %s",
                         annotation_type)

    return soup


def _option_label(node):
    """The label name a radio/checkbox option div stands for."""
    field = node.find(['input', 'select', 'textarea'])
    if field is not None:
        for attr in ('label_name', 'value'):
            value = field.get(attr)
            if value:
                return value
    label = node.find('label')
    return label.get_text(strip=True) if label else None


def _row_label(row):
    """The option name a multirate row stands for."""
    field = row.find('input')
    if field is not None:
        for attr in ('label_name', 'schema'):
            value = field.get(attr)
            if value:
                return value
    cell = row.find(['th', 'td'])
    return cell.get_text(strip=True) if cell else None


def filter_dynamic_options(soup, schemes, instance_data):
    """
    Filter annotation options per instance based on dynamic_options config.

    Each scheme can specify a `dynamic_options_field` that references a field
    in the instance data containing a list of visible option labels.
    Options not in the list are removed from the DOM.

    Args:
        soup: BeautifulSoup page object
        schemes: List of annotation scheme dicts with dynamic_options enabled
        instance_data: The current instance's data dictionary
    """
    for scheme in schemes:
        field_name = scheme.get('dynamic_options_field', 'visible_labels')
        visible_labels = instance_data.get(field_name)
        if visible_labels is None:
            continue  # No filtering for this instance

        if isinstance(visible_labels, str):
            visible_labels = [visible_labels]

        visible_set = set(visible_labels)
        schema_name = scheme['name']
        annotation_type = scheme['annotation_type']

        # Find the form for this schema
        form = soup.find('form', {'data-schema-name': schema_name})
        if not form:
            form = soup.find('form', id=schema_name)
        if not form:
            continue

        removed = 0
        if annotation_type == 'radio':
            for option_div in form.find_all('div', class_='shadcn-radio-option'):
                input_el = option_div.find('input', type='radio')
                if input_el and input_el.get('value') not in visible_set:
                    option_div.decompose()
                    removed += 1

        elif annotation_type == 'multiselect':
            # `shadcn-multiselect-item`, not `-option`: the class name here did
            # not match the markup, so `dynamic_options` on a multiselect
            # removed nothing. An item naming two of six labels rendered all
            # six, with nothing in the log to say the filter had run.
            for option_div in form.find_all('div', class_='shadcn-multiselect-item'):
                input_el = option_div.find('input', type='checkbox')
                if input_el and input_el.get('value') not in visible_set:
                    option_div.decompose()
                    removed += 1

        elif annotation_type == 'select':
            select_el = form.find('select')
            if select_el:
                for option in select_el.find_all('option'):
                    val = option.get('value', '')
                    # Keep placeholder options (empty value or disabled)
                    if val == '' or option.get('disabled') is not None:
                        continue
                    if val not in visible_set:
                        option.decompose()
                        removed += 1

        if not removed:
            logger.debug(
                "dynamic_options on %r removed nothing: %s names %d label(s) "
                "and every option is in that list.",
                schema_name, field_name, len(visible_set))

    return soup


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


def _prelabel_names(predicted_value):
    """
    The label names in a categorical pre-annotation, whatever shape it is in.

    A model that reports confidence writes
    ``[{"label": "positive", "confidence": 0.31}]``, not ``["positive"]`` --
    which is the shape `ai_prelabel` and every importer produce. This used to
    test ``dict in label2value`` and raise ``TypeError: unhashable type:
    'dict'`` from inside the annotation-page render, so the whole page 500'd
    and the annotator saw a stack trace rather than an item.

    Anything with no recognisable name is skipped rather than raising: a
    malformed prediction should cost its own highlight, not the page.
    """
    if isinstance(predicted_value, str):
        return [predicted_value]
    if isinstance(predicted_value, dict):
        predicted_value = [predicted_value]
    if not isinstance(predicted_value, list):
        return []

    names = []
    for entry in predicted_value:
        if isinstance(entry, str):
            names.append(entry)
        elif isinstance(entry, dict):
            name = entry.get('label') or entry.get('name')
            if isinstance(name, str):
                names.append(name)
    return names


def _span_annotations_from_pre_annotations(pre_annotation_data, config):
    """
    Build SpanAnnotation objects out of a span scheme's pre-annotations.

    Every other schema type takes its pre-annotation through the soup walk in
    ``render_page_with_annotations``, which sets an input's value. Spans have
    no such input -- they are markup rendered into the instance text before the
    template ever sees it -- so they need their own path, and without one a
    span scheme silently ignored ``pre_annotation`` entirely.

    Args:
        pre_annotation_data: ``{schema_name: value}`` from
            ``QualityControlManager.extract_pre_annotations``, or None.
        config: The task config, read for which schemes are spans.

    Returns:
        A list of SpanAnnotation, empty when there is nothing to render.
    """
    if not pre_annotation_data:
        return []

    span_schemes = {
        scheme.get("name")
        for scheme in config.get("annotation_schemes", [])
        if scheme.get("annotation_type") == "span"
    }
    if not span_schemes:
        return []

    spans = []
    for schema_name, predicted in pre_annotation_data.items():
        if schema_name not in span_schemes:
            continue
        if isinstance(predicted, str):
            # Accept the JSON-string form for the same reason image
            # pre-annotations do: a data file written by hand often quotes it.
            try:
                predicted = json.loads(predicted)
            except (TypeError, ValueError):
                logger.warning(
                    "Pre-annotation for span schema %s is a string that is not "
                    "JSON; ignoring it", schema_name)
                continue
        if not isinstance(predicted, list):
            logger.warning(
                "Pre-annotation for span schema %s must be a list of span "
                "dicts, got %s", schema_name, type(predicted).__name__)
            continue

        for entry in predicted:
            if not isinstance(entry, dict):
                continue
            try:
                start = int(entry["start"])
                end = int(entry["end"])
            except (KeyError, TypeError, ValueError):
                logger.warning(
                    "Skipping a pre-annotated span on %s with no usable "
                    "start/end: %r", schema_name, entry)
                continue
            name = entry.get("name") or entry.get("label") or ""
            if not name:
                continue
            spans.append(SpanAnnotation(
                schema=schema_name,
                name=name,
                title=entry.get("title") or name,
                start=start,
                end=end,
                id=entry.get("id"),
                target_field=entry.get("target_field"),
                additional_parts=entry.get("additional_parts"),
            ))

    return spans


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

    # Continuous backup to a HuggingFace Dataset, when configured. Started here
    # rather than in run_server() so it runs on the WSGI factory path too --
    # which is every container, and precisely where an ephemeral filesystem
    # makes it the only copy of the data.
    from potato.server_utils.hf_backup import init_backup
    init_backup(config)

    # Set application configuration
    from potato.server_utils.session_config import configure_session
    configure_session(app, config)

    # Configure routes from the routes module
    from routes import configure_routes
    configure_routes(app, config)

    # Conditionally register web agent blueprints only when needed
    _register_web_agent_blueprints_if_needed(app, config)

    return app


def _agent_proxy_enabled(config) -> bool:
    """Whether the agent proxy should be wired up.

    Present unless explicitly switched off, so `enabled: false` turns it off
    without deleting the block -- which is what that key means everywhere else.
    """
    block = config.get("agent_proxy")
    if not isinstance(block, dict):
        return bool(block)
    return block.get("enabled", True) is not False


def _preflight_coding_agent_sandbox(config):
    """Check the configured agent sandbox is usable, and say what it is.

    Raises on an unusable sandbox instead of starting: a server that accepts
    annotators while unable to contain their tool calls is worse than one that
    refuses to boot with an actionable message.
    """
    from potato.sandbox import SandboxSettings, preflight, startup_report

    settings = SandboxSettings.from_config(config.get("live_coding_agent", {}))

    reason = preflight(settings)
    if reason:
        raise RuntimeError(
            "Live coding agent sandbox is not usable: %s" % reason
        )

    for line in startup_report(settings).split("\n"):
        if settings.is_isolated_mode():
            logger.info(line)
        else:
            logger.warning(line)

    if settings.mode == "container":
        # A previous crash leaves one container per session with nothing left
        # running to reap it.
        from potato.sandbox.container import sweep_orphaned_containers
        swept = sweep_orphaned_containers(settings.container_cli)
        if swept:
            logger.info("Swept %d orphaned sandbox container(s)", swept)


def _register_web_agent_blueprints_if_needed(flask_app, config):
    """Register web agent blueprints only if web_agent display types are configured."""
    needs_web_agent = False
    instance_display = config.get("instance_display", {})
    fields = instance_display.get("fields", [])
    for field in fields:
        if isinstance(field, dict):
            field_type = field.get("type", "")
            if field_type in ("web_agent_trace", "web_agent_recorder"):
                needs_web_agent = True
                break

    if needs_web_agent:
        from potato.routes_web_agent import web_agent_bp
        from potato.web_proxy import web_proxy_bp
        flask_app.register_blueprint(web_agent_bp)
        flask_app.register_blueprint(web_proxy_bp)
        logger.info("Registered web agent blueprints (web_agent_trace/recorder display type detected)")

    # Check for live_agent display type
    needs_live_agent = False
    for field in fields:
        if isinstance(field, dict) and field.get("type") == "live_agent":
            needs_live_agent = True
            break

    if needs_live_agent:
        from potato.routes_live_agent import live_agent_bp
        flask_app.register_blueprint(live_agent_bp)
        # Store live_agent config on the app for route access
        live_agent_config = config.get("live_agent", {})
        flask_app.config["live_agent"] = live_agent_config
        flask_app.config["live_agent_enabled"] = True
        logger.info("Registered live agent blueprint (live_agent display type detected)")

        # Register cleanup on app shutdown
        import atexit
        def _cleanup_agent_sessions():
            try:
                from potato.agent_runner_manager import AgentRunnerManager
                AgentRunnerManager.clear_instance()
            except Exception as e:
                logger.warning(f"Failed to clean up agent sessions: {e}")
        atexit.register(_cleanup_agent_sessions)

    # Check for live_coding_agent display type
    needs_live_coding_agent = False
    for field in fields:
        if isinstance(field, dict) and field.get("type") == "live_coding_agent":
            needs_live_coding_agent = True
            break

    if needs_live_coding_agent:
        from potato.routes_live_coding_agent import live_coding_agent_bp
        flask_app.register_blueprint(live_coding_agent_bp)
        flask_app.config["live_coding_agent_enabled"] = True
        logger.info("Registered live coding agent blueprint (live_coding_agent display type detected)")

        # Annotators can edit and execute tool calls through this blueprint, so
        # the sandbox is the security boundary. Validate it now rather than at
        # the first tool call, which would strand an annotator mid-task.
        _preflight_coding_agent_sandbox(config)

        import atexit
        def _cleanup_coding_agent_sessions():
            try:
                from potato.coding_agent_runner_manager import CodingAgentRunnerManager
                CodingAgentRunnerManager.clear_instance()
            except Exception as e:
                logger.warning(f"Failed to clean up coding agent sessions: {e}")
        atexit.register(_cleanup_coding_agent_sessions)

    # Check for trace_ingestion config
    trace_ingestion_config = config.get("trace_ingestion", {})
    if trace_ingestion_config.get("enabled", False):
        from potato.routes_trace_ingestion import trace_ingestion_bp
        flask_app.register_blueprint(trace_ingestion_bp)
        flask_app.config["trace_ingestion"] = trace_ingestion_config
        if not trace_ingestion_config.get("api_key"):
            if trace_ingestion_config.get("allow_unauthenticated"):
                logger.warning(
                    "trace_ingestion is enabled with allow_unauthenticated: true and no "
                    "api_key -- /api/traces/webhook accepts writes from anyone who can "
                    "reach this server."
                )
            else:
                logger.warning(
                    "trace_ingestion is enabled but no api_key is set, so the webhook "
                    "endpoints will reject every request. Set trace_ingestion.api_key, "
                    "or trace_ingestion.allow_unauthenticated: true to accept anonymous "
                    "posts."
                )
        logger.info("Registered trace ingestion blueprint")

        # Start Langfuse poller if configured. Guard against `sources:` being
        # present-but-null in YAML (e.g. when all entries are commented out),
        # which yields None rather than an empty list.
        sources = trace_ingestion_config.get("sources") or []
        for source in sources:
            if source.get("type") == "langfuse":
                from potato.trace_ingestion.langfuse_poller import LangfusePoller
                poller = LangfusePoller(
                    api_url=source.get("api_url", "https://cloud.langfuse.com"),
                    public_key=source.get("public_key", ""),
                    secret_key=source.get("secret_key", source.get("api_key", "")),
                    poll_interval=source.get("poll_interval", 30),
                )
                poller.start()
                logger.info(f"Started Langfuse poller (interval={source.get('poll_interval', 30)}s)")

                import atexit
                atexit.register(poller.stop)

    # Live database ingestion: background cursor pollers for data_sources
    # entries with live_ingestion.enabled. Started here in configure_app() —
    # the single chokepoint called by create_app() on BOTH the live `start`
    # path and the WSGI factory path — so pollers run regardless of launch
    # mode. (The directory watcher, started from run_server(), does not have
    # that parity; do not copy its placement.)
    #
    # Ordering matters twice over. This point is after load_all_data(), so the
    # manager exists and the initial catch-up read has already seeded the
    # cursor — polling before that would race the initial load. It is also
    # after load_user_data(), which rebuilds ism.instance_annotators by
    # iterating instance_id_to_instance; a poll thread mutating that dict
    # mid-rebuild yields a nondeterministic map that adjudication reads.
    if _has_live_ingestion_source(config):
        _start_live_ingestion(config)

    # Datasets / Experiments. Registered here in configure_app() — the single
    # chokepoint called by create_app() on BOTH the live `start` path and the
    # WSGI factory path — so the route exists regardless of how the server is
    # launched (see project_route_dual_registration).
    if config.get("datasets", {}).get("enabled", False):
        from potato.eval_datasets import init_datasets_manager, get_datasets_manager
        from potato.eval_datasets.routes import datasets_bp
        from potato.eval_datasets.eval_admin import eval_admin_bp
        if get_datasets_manager() is None:
            init_datasets_manager(config)
        if "datasets" not in flask_app.blueprints:
            flask_app.register_blueprint(datasets_bp)
        if "eval_admin" not in flask_app.blueprints:
            flask_app.register_blueprint(eval_admin_bp)
        logger.info("Registered datasets/experiments + eval-admin blueprints")

    # Automation rules engine (Phase 4): closes the production->eval loop by
    # running filter->sample->actions over every item entering Potato.
    if config.get("automation", {}).get("enabled", False):
        from potato.automation import init_automation_manager, get_automation_manager
        from potato.automation.routes import automation_bp
        if get_automation_manager() is None:
            init_automation_manager(config)
        if "automation" not in flask_app.blueprints:
            flask_app.register_blueprint(automation_bp)
        import atexit
        atexit.register(lambda: (get_automation_manager() and get_automation_manager().shutdown()))
        logger.info("Registered automation-rules blueprint")

    # MCP control surface. Config-gated like the blueprints below, and with an
    # extra refusal: register_mcp_routes() declines under debug: true unless
    # mcp.allow_debug is set, because debug disables admin auth server-wide.
    try:
        from potato.mcp_server.routes import register_mcp_routes

        register_mcp_routes(flask_app, config)
    except Exception as e:
        logger.warning("Could not register the MCP control surface: %s", e)

    # Semantic curation (Catalog): embedding index + similarity search + slices.
    if config.get("curation", {}).get("enabled", False):
        from potato.curation import init_curation_manager, get_curation_manager
        from potato.curation.routes import curation_bp
        if get_curation_manager() is None:
            init_curation_manager(config)
        if "curation" not in flask_app.blueprints:
            flask_app.register_blueprint(curation_bp)
        logger.info("Registered semantic-curation (catalog) blueprint")

    # Model training and the retrain loop. Off unless asked for: it spawns
    # subprocesses and writes model artifacts, neither of which a project that
    # has not opted in should get.
    if config.get("model_training", {}).get("enabled", False):
        from potato.training.manager import (get_training_manager,
                                             init_training_manager)
        from potato.training.routes import training_bp
        if get_training_manager() is None:
            init_training_manager(config)
        if "training" not in flask_app.blueprints:
            flask_app.register_blueprint(training_bp)
        logger.info("Registered model-training blueprint")

    # Dataset publishing (HuggingFace / Zenodo / local archive). Always on for
    # admins — packaging a dataset needs no per-project config, and the manager
    # only does work when the wizard is used.
    try:
        from potato.publish.manager import get_publish_manager, init_publish_manager
        from potato.publish.routes import publish_bp
        if get_publish_manager() is None:
            init_publish_manager(config)
        if "publish" not in flask_app.blueprints:
            flask_app.register_blueprint(publish_bp)
        logger.info("Registered dataset-publishing blueprint")
    except Exception as e:
        logger.warning("Could not register dataset-publishing blueprint: %s", e)

    # Multi-model arena: fan a prompt out to N providers side by side.
    if config.get("arena", {}).get("enabled", False):
        from potato.arena import init_arena_manager, get_arena_manager
        from potato.arena.routes import arena_bp
        if get_arena_manager() is None:
            init_arena_manager(config)
        if "arena" not in flask_app.blueprints:
            flask_app.register_blueprint(arena_bp)
        logger.info("Registered model-arena blueprint")

    # Multi-document event annotation: cross-document event registry (import-light,
    # safe at boot) + optional corpus map (ML, lazy). The event registry powers the
    # multi_document_event schema; the corpus map adds the 2D navigation surface.
    if config.get("event_template", {}).get("enabled", False) or config.get("corpus_map", {}).get("enabled", False):
        from potato.event_registry import (
            init_event_registry_manager,
            get_event_registry_manager,
        )
        from potato.event_registry.routes import event_registry_bp
        if get_event_registry_manager() is None:
            init_event_registry_manager(config)
        if "event_registry" not in flask_app.blueprints:
            flask_app.register_blueprint(event_registry_bp)
        logger.info("Registered cross-document event-registry blueprint")

    # Corpus map: 2D cluster-map navigation surface for multi-document tasks.
    # The heavy embed/cluster/UMAP build runs lazily in a background thread so it
    # never blocks boot; the annotator page polls /corpus/api/build_status.
    if config.get("corpus_map", {}).get("enabled", False):
        from potato.corpus_map import init_corpus_map_manager, get_corpus_map_manager
        from potato.corpus_map.routes import corpus_map_bp
        if get_corpus_map_manager() is None:
            init_corpus_map_manager(config)
        if "corpus_map" not in flask_app.blueprints:
            flask_app.register_blueprint(corpus_map_bp)
        _cm = get_corpus_map_manager()
        if _cm and _cm.build_on_start and not _cm.is_built():
            import threading as _threading
            _threading.Thread(target=lambda: _cm.build(force=False), daemon=True).start()
            logger.info("Corpus map build started in background")
        logger.info("Registered corpus-map blueprint")

# Function to create and initialize the Flask application
def create_app(config_file=None):
    """
    Create and configure the Flask application.

    When *config_file* is provided (e.g. from a gunicorn factory call like
    ``gunicorn "potato.flask_server:create_app('config.yaml')"``), this
    function also performs the full server initialization (config loading,
    state managers, data loading, etc.) that ``run_server()`` normally does.
    This makes it compatible with WSGI servers that use the factory pattern.

    Args:
        config_file: Optional path to a YAML config file.  When provided,
            ``init_config`` and ``_initialize_from_config`` are called
            automatically so the app is ready to serve requests.

    Returns:
        The configured Flask application instance
    """
    global app

    # If a config file was provided, perform full initialization first.
    # This is the code path used by gunicorn / WSGI factory calls.
    if config_file is not None:
        _initialize_from_config(config_file)

    # Initialize the app with explicit static folder configuration
    static_folder = os.path.join(cur_program_dir, 'static')
    app = Flask(__name__, static_folder=static_folder)
    _apply_url_prefix_from_env(app)
    _apply_proxy_fix_from_env(app)

    # Configure Jinja2 to look in both main templates and generated templates directories
    real_templates_dir = os.path.join(cur_program_dir, 'templates')
    # Not necessarily inside the package: an ordinary (non-editable) install
    # leaves site-packages read-only for the serving user, so this may resolve
    # to a writable directory elsewhere. The generator uses the same resolver,
    # which is what keeps the two in agreement.
    from potato.server_utils.generated_templates import (
        resolve_generated_templates_dir)
    generated_templates_dir = resolve_generated_templates_dir(real_templates_dir)

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

        # ui_lang_defaults is the shared English source of truth (single
        # definition in server_utils/i18n.py); the whitelist and catalog
        # key-filter derive from it.
        from potato.server_utils.i18n import UI_LANG_DEFAULTS as ui_lang_defaults
        # Resolve ui_lang from English defaults + an optional bundled language
        # catalog (e.g. ui_language: es) + optional inline per-key overrides.
        from potato.server_utils.i18n import resolve_ui_language
        ui_lang = resolve_ui_language(config.get('ui_language'), ui_lang_defaults)

        # Load project-level base CSS if configured
        from potato.server_utils.front_end import load_project_base_css_html, resolve_header_logo_src
        try:
            project_base_css = load_project_base_css_html(config)
        except FileNotFoundError:
            project_base_css = ""
            logger.warning("base_css file configured but not found")

        # Resolve header logo (cached as data URL at startup)
        header_logo_url = resolve_header_logo_src(config)

        return {
            'ui_debug': is_ui_debug_enabled(),
            'server_debug': is_server_debug_enabled(),
            'debug_mode': config.get('debug', False),
            'debug_phase': config.get('debug_phase'),
            # Add common config values needed by templates
            'annotation_task_name': config.get('annotation_task_name', 'Annotation Task'),
            'annotation_codebook_url': _sanitize_codebook_url(config.get('annotation_codebook_url', '')),
            # Multilingual UI strings
            'ui_lang': ui_lang,
            # Project-level base CSS
            'PROJECT_BASE_CSS': project_base_css,
            # Header logo
            'header_logo_url': header_logo_url,
            # Deployment URL prefix for client-side fetch/beacon/media URLs.
            #
            # Both proxy mechanisms converge on the WSGI SCRIPT_NAME: ProxyFix
            # sets it from X-Forwarded-Prefix, and StaticPrefixMiddleware sets it
            # from POTATO_URL_PREFIX. request.script_root surfaces that value, so
            # it is the single source of truth and works in BOTH modes (including
            # a real WSGI mount). We fall back to the env var defensively. When no
            # proxy is involved script_root is "" and this is a no-op.
            'url_prefix': request.script_root or _normalize_url_prefix(
                os.environ.get("POTATO_URL_PREFIX", "")
            ),
            # Custom footer HTML (e.g., promotional banner for HF Spaces)
            'custom_footer_html': config.get('custom_footer_html', ''),
        }

    return app


def _env_flag_enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _normalize_url_prefix(prefix: str) -> str:
    prefix = (prefix or "").strip().strip("/")
    return f"/{prefix}" if prefix else ""


def _apply_url_prefix_from_env(flask_app):
    """
    Force URL generation to include a deployment prefix when the reverse proxy
    cannot send X-Forwarded-Prefix.

    This is for deployments where nginx exposes Potato at /app1/ and strips
    that prefix before proxying to Flask. Setting POTATO_URL_PREFIX=/app1 makes
    url_for('static', ...) emit /app1/static/... while Flask still receives
    backend paths such as /static/styles.css.
    """
    prefix = _normalize_url_prefix(os.environ.get("POTATO_URL_PREFIX", ""))
    if not prefix:
        return

    class StaticPrefixMiddleware:
        def __init__(self, wrapped_app, script_name):
            self.wrapped_app = wrapped_app
            self.script_name = script_name

        def __call__(self, environ, start_response):
            if not environ.get("SCRIPT_NAME"):
                environ["SCRIPT_NAME"] = self.script_name
            return self.wrapped_app(environ, start_response)

    flask_app.wsgi_app = StaticPrefixMiddleware(flask_app.wsgi_app, prefix)


def _apply_proxy_fix_from_env(flask_app):
    """
    Enable reverse-proxy prefix handling when explicitly requested.

    Deployments mounted below a path such as /round1 need Flask to see the
    forwarded prefix so url_for('static', ...) emits /round1/static/... instead
    of /static/.... Without that, the annotation shell renders but CSS/JS 404s.
    """
    if not _env_flag_enabled("POTATO_PROXY_FIX"):
        return

    from werkzeug.middleware.proxy_fix import ProxyFix

    flask_app.wsgi_app = ProxyFix(
        flask_app.wsgi_app,
        x_for=int(os.environ.get("POTATO_PROXY_FIX_X_FOR", "1")),
        x_proto=int(os.environ.get("POTATO_PROXY_FIX_X_PROTO", "1")),
        x_host=int(os.environ.get("POTATO_PROXY_FIX_X_HOST", "1")),
        x_prefix=int(os.environ.get("POTATO_PROXY_FIX_X_PREFIX", "1")),
    )


def _initialize_from_config(config_file):
    """
    Perform full server initialization from a config file path.

    This is used by ``create_app(config_file)`` for WSGI/gunicorn deployments
    where ``run_server()`` is not called.  It mirrors the initialization steps
    in ``run_server()`` but constructs a minimal ``args`` namespace instead of
    parsing sys.argv.
    """
    import types

    # Build a minimal args namespace that init_config expects
    args = types.SimpleNamespace(
        config_file=config_file,
        port=None,
        verbose=False,
        very_verbose=False,
        debug=False,
        debug_log=None,
        debug_phase=None,
        customjs=None,
        customjs_hostname=None,
        persist_sessions=False,
        require_password=None,
        mode="start",
    )

    # Initialize configuration
    init_config(args)

    # Handle require_no_password
    if config.get("require_no_password", False):
        config["require_password"] = False

    # For URL-direct login, disable password requirement
    login_config = config.get("login", {})
    if login_config.get("type") in ["url_direct", "prolific"]:
        config["require_password"] = False

    # Set random seed default
    if "random_seed" not in config:
        config["random_seed"] = 1234

    # Set up logging
    setup_logging(
        verbose=config.get("verbose", False),
        debug=config.get("debug", False),
        debug_log=config.get("debug_log"),
        log_dir=config.get("output_annotation_dir"),
    )

    # Ensure directories exist
    task_dir = config.get("task_dir", ".")
    if not os.path.exists(task_dir):
        os.makedirs(task_dir)

    output_annotation_dir = config.get("output_annotation_dir", "annotation_output")
    if not os.path.exists(output_annotation_dir):
        os.makedirs(output_annotation_dir)

    # Initialize authenticator
    UserAuthenticator.init_from_config(config)

    # Initialize state managers (singletons — safe to call if already initialized)
    init_user_state_manager(config)
    init_item_state_manager(config)

    # Initialize AI support if enabled
    if config.get("ai_support", {}).get("enabled", False):
        init_ai_prompt(config)
        init_dynamic_ai_help()

    # Before the corpus loads: add_item() runs the automation rules per item.
    _init_automation_manager_early(config)

    # Load data
    load_all_data(config)

    # Initialize AI cache after data is loaded
    if config.get("ai_support", {}).get("enabled", False):
        init_ai_cache_manager()

    # Initialize quality control if enabled
    qc_enabled = (
        config.get("attention_checks", {}).get("enabled", False)
        or config.get("gold_standards", {}).get("enabled", False)
        or config.get("pre_annotation", {}).get("enabled", False)
    )
    if qc_enabled:
        qc_task_dir = config.get(
            "task_dir", os.path.dirname(config.get("config_file", ""))
        )
        init_quality_control_manager(config, qc_task_dir)

    # Initialize adjudication if configured
    if config.get("adjudication", {}).get("enabled", False):
        init_adjudication_manager(config)

    # Initialize RBAC + per-cohort schema resolver (always; cheap and lazy-safe)
    from potato.server_utils.rbac import init_rbac_manager
    from potato.server_utils.cohort_schemes import init_cohort_scheme_resolver
    init_rbac_manager(config)
    init_cohort_scheme_resolver(config)

    # Initialize knowledge base manager
    init_kb_manager(config)

    # Initialize WaveformService for audio annotation
    _init_waveform_service(config)

    # Initialize webhook emitter if configured
    if config.get("webhooks", {}).get("enabled", False):
        from potato.webhooks import init_webhook_emitter
        init_webhook_emitter(config)

    # Initialize Solo Mode if enabled (parity with run_server() — the
    # WSGI/gunicorn factory path must initialize it too, otherwise the
    # /solo routes exist but the manager is never created).
    if config.get("solo_mode", {}).get("enabled", False):
        logger.info("Initializing Solo Mode...")
        init_solo_mode_manager(config)
        logger.info("Solo Mode initialized successfully")

    # Initialize QDA Mode if enabled (parity with run_server()).
    if config.get("qda_mode", {}).get("enabled", False):
        logger.info("Initializing QDA Mode...")
        init_qda_mode_manager(config)
        logger.info("QDA Mode initialized successfully")

    # Initialize Boundary Lab if enabled (parity with run_server()).
    if config.get("boundary_probing", {}).get("enabled", False):
        logger.info("Initializing Boundary Lab...")
        from potato.boundary import init_boundary_manager
        init_boundary_manager(config)
        logger.info("Boundary Lab initialized successfully")
    # Initialize Truth Serum if enabled (parity with run_server()).
    if config.get("truth_serum", {}).get("enabled", False):
        logger.info("Initializing Truth Serum...")
        from potato.truth_serum import init_truth_serum_manager
        init_truth_serum_manager(config)
        logger.info("Truth Serum initialized successfully")
    # Initialize Think-Aloud if enabled (parity with run_server()).
    if config.get("thinkaloud", {}).get("enabled", False):
        logger.info("Initializing Think-Aloud...")
        from potato.thinkaloud import init_thinkaloud_manager
        init_thinkaloud_manager(config)
        logger.info("Think-Aloud initialized successfully")
    # Initialize Pocket Mode if enabled (parity with run_server()).
    if config.get("pocket", {}).get("enabled", False):
        logger.info("Initializing Pocket Mode...")
        from potato.pocket.routes import init_pocket
        init_pocket(config)
        logger.info("Pocket Mode initialized successfully")
    # Initialize Psychometrics if enabled (parity with run_server()).
    if config.get("psychometrics", {}).get("enabled", False):
        logger.info("Initializing Psychometrics...")
        from potato.psychometrics import init_psychometrics_manager
        init_psychometrics_manager(config)
        logger.info("Psychometrics initialized successfully")
    # Initialize Multiplayer Rooms if enabled (parity with run_server()).
    if config.get("rooms", {}).get("enabled", False):
        logger.info("Initializing Multiplayer Rooms...")
        from potato.rooms import init_rooms_manager
        init_rooms_manager(config)
        logger.info("Multiplayer Rooms initialized successfully")

    # Initialize Judge Calibration if enabled (parity with run_server()).
    if config.get("judge_calibration", {}).get("enabled", False):
        logger.info("Initializing Judge Calibration...")
        from potato.judge_calibration import init_judge_calibration_manager
        init_judge_calibration_manager(config)
        logger.info("Judge Calibration initialized successfully")

    # Keep ICL prompts restricted to the codebook's current set: a
    # change listener re-syncs live scheme labels on any codebook edit.
    try:
        from potato.codebook.schema_bridge import install_codebook_icl_sync
        install_codebook_icl_sync()
    except Exception as e:
        logger.warning(f"Codebook ICL sync not installed: {e}")

    # Auto-detect cases from item metadata (no-op unless cases enabled
    # or QDA mode is on).
    try:
        from potato.cases import init_cases_from_config
        init_cases_from_config(config)
    except Exception as e:
        logger.warning(f"Cases auto-detect skipped: {e}")

    # Group traces into sessions by session_id/thread_id (no-op unless
    # sessions enabled).
    try:
        from potato.sessions import init_sessions_from_config
        init_sessions_from_config(config)
    except Exception as e:
        logger.warning(f"Sessions auto-detect skipped: {e}")

    # Enroll instances into the review workflow board (no-op unless
    # review_workflow enabled).
    try:
        from potato.review_workflow import init_review_workflow_from_config
        init_review_workflow_from_config(config)
    except Exception as e:
        logger.warning(f"Review workflow init skipped: {e}")

    # Build the universal search index (no-op if search disabled).
    try:
        from potato.search import init_search_from_item_state
        init_search_from_item_state(config)
    except Exception as e:
        logger.warning(f"Search index init skipped: {e}")

    logger.info("Server initialization complete (WSGI factory mode)")


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
            client_fallback_max_duration=client_fallback_max_duration,
            # Local media paths from request bodies resolve inside this.
            task_dir=config.get("task_dir", "."),
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

    # Before the corpus loads: add_item() runs the automation rules per item.
    _init_automation_manager_early(config)

    load_all_data(config)

    # Initialize AI cache manager AFTER load_all_data() because
    # it needs item_state_manager to be fully initialized for warmup
    if config.get("ai_support", {}).get("enabled", False):
        logger.info("Initializing AI cache manager...")
        init_ai_cache_manager()
        # Report the endpoint, not the try block. This said "AI support
        # initialized successfully" two lines under "AI endpoint unavailable at
        # startup", so an author grepping the boot log for the AI subsystem
        # found the success line and stopped reading.
        _ai_manager = get_ai_cache_manager()
        if _ai_manager is not None and getattr(_ai_manager, "ai_endpoint", None) is not None:
            logger.info("AI support initialized successfully")
        else:
            logger.error(
                "AI support is enabled in the config but no endpoint could be "
                "created, so no assistant will appear on any item. See the "
                "endpoint warning above for the reason.")
    
    # Initialize chat manager if enabled
    if config.get("chat_support", {}).get("enabled", False):
        logger.info("Initializing Chat Manager...")
        from potato.chat_manager import init_chat_manager
        init_chat_manager(config)
        logger.info("Chat support initialized successfully")

    # Initialize Solo Mode if enabled
    if config.get("solo_mode", {}).get("enabled", False):
        logger.info("Initializing Solo Mode...")
        init_solo_mode_manager(config)
        logger.info("Solo Mode initialized successfully")

    # Initialize QDA Mode if enabled
    if config.get("qda_mode", {}).get("enabled", False):
        logger.info("Initializing QDA Mode...")
        init_qda_mode_manager(config)
        logger.info("QDA Mode initialized successfully")

    # Initialize Boundary Lab if enabled
    if config.get("boundary_probing", {}).get("enabled", False):
        logger.info("Initializing Boundary Lab...")
        from potato.boundary import init_boundary_manager
        init_boundary_manager(config)
        logger.info("Boundary Lab initialized successfully")
    # Initialize Truth Serum if enabled
    if config.get("truth_serum", {}).get("enabled", False):
        logger.info("Initializing Truth Serum...")
        from potato.truth_serum import init_truth_serum_manager
        init_truth_serum_manager(config)
        logger.info("Truth Serum initialized successfully")
    # Initialize Think-Aloud if enabled
    if config.get("thinkaloud", {}).get("enabled", False):
        logger.info("Initializing Think-Aloud...")
        from potato.thinkaloud import init_thinkaloud_manager
        init_thinkaloud_manager(config)
        logger.info("Think-Aloud initialized successfully")
    # Initialize Pocket Mode if enabled
    if config.get("pocket", {}).get("enabled", False):
        logger.info("Initializing Pocket Mode...")
        from potato.pocket.routes import init_pocket
        init_pocket(config)
        logger.info("Pocket Mode initialized successfully")
    # Initialize Psychometrics if enabled
    if config.get("psychometrics", {}).get("enabled", False):
        logger.info("Initializing Psychometrics...")
        from potato.psychometrics import init_psychometrics_manager
        init_psychometrics_manager(config)
        logger.info("Psychometrics initialized successfully")
    # Initialize Multiplayer Rooms if enabled
    if config.get("rooms", {}).get("enabled", False):
        logger.info("Initializing Multiplayer Rooms...")
        from potato.rooms import init_rooms_manager
        init_rooms_manager(config)
        logger.info("Multiplayer Rooms initialized successfully")

    # Initialize Judge Calibration if enabled
    if config.get("judge_calibration", {}).get("enabled", False):
        logger.info("Initializing Judge Calibration...")
        from potato.judge_calibration import init_judge_calibration_manager
        init_judge_calibration_manager(config)
        logger.info("Judge Calibration initialized successfully")

    # Keep ICL prompts restricted to the codebook's current set: a
    # change listener re-syncs live scheme labels on any codebook edit.
    try:
        from potato.codebook.schema_bridge import install_codebook_icl_sync
        install_codebook_icl_sync()
    except Exception as e:
        logger.warning(f"Codebook ICL sync not installed: {e}")

    # Auto-detect cases from item metadata (no-op unless cases enabled
    # or QDA mode is on).
    try:
        from potato.cases import init_cases_from_config
        init_cases_from_config(config)
    except Exception as e:
        logger.warning(f"Cases auto-detect skipped: {e}")

    # Group traces into sessions by session_id/thread_id (no-op unless
    # sessions enabled).
    try:
        from potato.sessions import init_sessions_from_config
        init_sessions_from_config(config)
    except Exception as e:
        logger.warning(f"Sessions auto-detect skipped: {e}")

    # Enroll instances into the review workflow board (no-op unless
    # review_workflow enabled).
    try:
        from potato.review_workflow import init_review_workflow_from_config
        init_review_workflow_from_config(config)
    except Exception as e:
        logger.warning(f"Review workflow init skipped: {e}")

    # Build the universal search index (no-op if search disabled).
    try:
        from potato.search import init_search_from_item_state
        init_search_from_item_state(config)
    except Exception as e:
        logger.warning(f"Search index init skipped: {e}")

    # Initialize diversity manager if diversity_clustering strategy is used
    # or if diversity_ordering is explicitly enabled
    assignment_strategy = config.get("assignment_strategy", "")
    if isinstance(assignment_strategy, dict):
        assignment_strategy = assignment_strategy.get("name", "")
    diversity_enabled = (
        assignment_strategy == "diversity_clustering" or
        config.get("diversity_ordering", {}).get("enabled", False)
    )
    if diversity_enabled:
        logger.info("Initializing diversity manager...")
        dm = init_diversity_manager(config)
        if dm and dm.enabled:
            # Prefill embeddings for first N items
            _prefill_diversity_embeddings(dm, config)
            logger.info("Diversity manager initialized successfully")

            # Initialize embedding visualization manager (requires diversity manager)
            from potato.embedding_visualization import init_embedding_viz_manager
            viz_manager = init_embedding_viz_manager(config)
            if viz_manager and viz_manager.enabled:
                logger.info("Embedding visualization manager initialized")
            else:
                logger.debug(
                    "Embedding visualization not enabled. "
                    "Install umap-learn: pip install umap-learn"
                )
        else:
            logger.warning(
                "Diversity ordering requested but manager not enabled. "
                "Install sentence-transformers and scikit-learn: "
                "pip install sentence-transformers scikit-learn"
            )

    # Initialize active learning manager if enabled. The manager trains a
    # classifier on annotations in a background thread and reorders the
    # unlabeled pool by query strategy (uncertainty/BADGE/BALD/hybrid). Without
    # this, `assignment_strategy: active_learning` falls back to random order.
    if config.get('active_learning', {}).get('enabled', False):
        try:
            from potato.active_learning_manager import (
                parse_active_learning_config, init_active_learning_manager,
            )
            al_cfg = parse_active_learning_config(config)
            if al_cfg:
                init_active_learning_manager(al_cfg)
                logger.info(
                    "Active learning manager initialized (query_strategy=%s, "
                    "update_frequency=%s, schemas=%s)",
                    al_cfg.query_strategy, al_cfg.update_frequency, al_cfg.schema_names,
                )
        except Exception as e:
            logger.warning(
                "Active learning requested but could not initialize (%s). "
                "Continuing without active-learning reordering.", e
            )

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

    # Initialize RBAC + per-cohort schema resolver (always; cheap and lazy-safe)
    from potato.server_utils.rbac import init_rbac_manager
    from potato.server_utils.cohort_schemes import init_cohort_scheme_resolver
    init_rbac_manager(config)
    init_cohort_scheme_resolver(config)

    # Initialize MACE competence estimation if configured
    if config.get('mace', {}).get('enabled', False):
        from potato.mace_manager import init_mace_manager
        init_mace_manager(config)
        logger.info("MACE manager initialized")

    # Initialize knowledge base manager for entity linking
    init_kb_manager(config)
    logger.info("Knowledge base manager initialized")

    # Two blocks that ran without ever announcing themselves. The standard way
    # to check a feature took -- enable it, look for its initialization line --
    # had nothing to look for, so "on and working" and "silently ignored"
    # printed the same thing at boot: nothing.
    keystroke_cfg = config.get("keystroke_logging") or {}
    if keystroke_cfg.get("enabled"):
        logger.info(
            "Keystroke logging enabled (raw streams in project.sqlite, "
            "summaries mirrored into behavioral data)")

    budget_cfg = config.get("ai_budget") or {}
    if budget_cfg.get("cap_usd") is not None:
        logger.info("AI budget cap set at $%s for this run",
                    budget_cfg.get("cap_usd"))

    # Initialize agent session manager if agent_proxy is configured
    if _agent_proxy_enabled(config):
        from potato.agent_proxy import init_agent_session_manager
        init_agent_session_manager(config)
        logger.info(f"Agent session manager initialized (proxy type: {config['agent_proxy'].get('type', 'unknown')})")

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

    # Initialize webhook emitter if configured
    if config.get('webhooks', {}).get('enabled', False):
        from potato.webhooks import init_webhook_emitter, get_webhook_emitter
        init_webhook_emitter(config)
        logger.info("Webhook emitter initialized")

        import atexit
        def cleanup_webhook_emitter():
            emitter = get_webhook_emitter()
            if emitter:
                emitter.stop()
                logger.info("Webhook emitter stopped")
        atexit.register(cleanup_webhook_emitter)

    # The HuggingFace backup used to be started here. It now runs from
    # configure_app(), because this function is only reached by `potato start`:
    # every container starts through the create_app WSGI factory, so a backup
    # wired here never ran on the hosts whose disks do not survive a restart.

    # Initialize WaveformService for audio annotation if configured
    _init_waveform_service(config)

    # Log password requirement status
    logger.info(f"Password authentication required: {config.get('require_password', True)}")

    # Create and configure the Flask app
    app = create_app()

    # Initialize OAuth with Flask app if using OAuth authentication
    # (must happen after create_app() since OAuth needs the Flask app instance)
    auth_method = config.get("authentication", {}).get("method", "in_memory")
    if auth_method == "oauth":
        authenticator = UserAuthenticator.get_instance()
        oauth_backend = authenticator.get_oauth_backend()
        if oauth_backend:
            oauth_backend.init_oauth(app)
            logger.info("OAuth providers initialized with Flask app")

    # Run the Flask app
    host = config.get("host", "0.0.0.0")
    port = config.get("port", 8000)

    # --ssl-cert/--ssl-key used to be parsed and then dropped, so the server
    # served plaintext while the operator thought it was serving TLS.
    ssl_context = None
    if config.get("ssl_cert") and config.get("ssl_key"):
        ssl_context = (config["ssl_cert"], config["ssl_key"])
        logger.info("Serving over HTTPS using cert %s", config["ssl_cert"])

    # Two different things are spelled `debug`. Potato's own conveniences
    # (skip login, debug phases, verbose logging) are safe to keep wherever
    # the operator asked for them. Flask's `debug=True` additionally serves the
    # Werkzeug interactive debugger, which is a remote console for anyone who
    # can reach a traceback. Those are separable, and only the second one has
    # to be refused off loopback.
    from potato.server_utils.admin_key import is_loopback_bind

    debug_requested = config.get("debug", False)
    loopback = is_loopback_bind({"host": host})

    if debug_requested and not loopback:
        if os.environ.get("POTATO_ALLOW_REMOTE_DEBUG") != "1":
            raise SystemExit(
                "Refusing to start: debug is enabled and the server is bound "
                "to %s rather than loopback.\n"
                "  debug disables parts of the admin authentication and, with "
                "the built-in server, exposes the Werkzeug interactive "
                "debugger.\n"
                "  Bind to 127.0.0.1, remove `debug: true`, or set "
                "POTATO_ALLOW_REMOTE_DEBUG=1 if you accept the risk."
                % host
            )
        logger.warning(
            "=" * 70 + "\n"
            "debug is enabled on %s, a non-loopback bind, allowed only "
            "because POTATO_ALLOW_REMOTE_DEBUG=1 is set.\n"
            "The Werkzeug interactive debugger is still withheld.\n"
            + "=" * 70, host,
        )

    # The interactive debugger is never served off loopback, override or not.
    werkzeug_debug = bool(debug_requested and loopback)

    if debug_requested:
        logger.warning(
            "debug is on. Bound to %s. Admin bypass: %s. Werkzeug debugger: %s.",
            host,
            "active (loopback)" if loopback else "withheld (not loopback)",
            "on" if werkzeug_debug else "off",
        )

    # Use threaded=True so background LLM calls (solo mode refinement,
    # edge case synthesis, etc.) don't block the HTTP server.
    app.run(host=host, port=port, debug=werkzeug_debug,
            use_reloader=False, threaded=True, ssl_context=ssl_context)


# Define the main entry point for the Flask server
def main():
    """
    Main entry point for the Flask server

    This function initializes the application, loads data, and runs the server.
    """
    # ``transcripts`` is dispatched before the server's own argument parsing.
    # It takes input paths rather than a config file and has its own flags, so
    # routing it through the server parser would mean bending both.
    if len(sys.argv) > 1 and sys.argv[1] == 'transcripts':
        from potato.transcript_cli import main as transcripts_main
        sys.exit(transcripts_main(sys.argv[2:]))

    # ``convokit`` is dispatched the same way and for the same reason: it takes a
    # corpus name or path rather than a config file.
    if len(sys.argv) > 1 and sys.argv[1] == 'convokit':
        from potato.convokit.cli import main as convokit_main
        sys.exit(convokit_main(sys.argv[2:]))

    # ``import`` generates a project from an existing annotation file (COCO,
    # ...), so it takes input paths rather than a config file.
    if len(sys.argv) > 1 and sys.argv[1] == 'import':
        from potato.importers.cli import main as import_main
        sys.exit(import_main(sys.argv[2:]))

    # ``download-models`` fetches segmentation weights. Dispatched here for the
    # same reason as the others: it takes a model name, not a config file.
    if len(sys.argv) > 1 and sys.argv[1] == 'download-models':
        from potato.models_cli import main as models_main
        sys.exit(models_main(sys.argv[2:]))

    # ``deploy`` puts a task on a host and takes it down again. It has its own
    # subcommands and flag set, so it does not fit the mode + config_file
    # positional shape the server parser uses.
    if len(sys.argv) > 1 and sys.argv[1] == 'deploy':
        from potato.deploy.cli import main as deploy_main
        sys.exit(deploy_main(sys.argv[2:]))

    # ``share`` serves a task on a temporary public URL through a tunnel.
    if len(sys.argv) > 1 and sys.argv[1] == 'share':
        from potato.deploy.share_cli import main as share_main
        sys.exit(share_main(sys.argv[2:]))

    # ``validate`` and ``preview`` inspect a config without starting anything.
    # They take a config file like the server modes do, but each carries flags
    # (--strict/--json, --format/--layout-only) that would collide with the
    # server parser's, and registering them there would pull all ~24 server
    # flags into their --help.
    if len(sys.argv) > 1 and sys.argv[1] == 'validate':
        from potato.validate_cli import main as validate_main
        sys.exit(validate_main(sys.argv[2:]))

    if len(sys.argv) > 1 and sys.argv[1] == 'preview':
        from potato.preview_cli import main as preview_main
        sys.exit(preview_main(sys.argv[2:]))

    # ``mcp`` runs the Model Context Protocol server that coding agents connect
    # to. Its own subcommands (serve/tools/config), and `serve` takes a --root
    # rather than a config file.
    if len(sys.argv) > 1 and sys.argv[1] == 'mcp':
        from potato.mcp_server.cli import main as mcp_main
        sys.exit(mcp_main(sys.argv[2:]))

    # Parse command line arguments
    args = arguments()

    if args.mode == 'start':
        logger.info("Starting server mode")
        run_server(args)
    elif args.mode == 'reset-password':
        logger.info("Starting password reset")
        from potato.password_reset import cli_reset_password
        cli_reset_password(args)
        return
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
    elif args.mode == 'codebook':
        logger.info("Starting codebook initialization")
        from potato.codebook_cli import main as codebook_main
        sys.exit(codebook_main([args.config_file]))
    elif args.mode == 'repair-annotations':
        logger.info("Starting single-select annotation repair")
        from potato.repair_cli import run_repair
        sys.exit(run_repair(args))

    logger.info("Annotation platform shutdown complete")


# Main entry point
if __name__ == "__main__":
    main()


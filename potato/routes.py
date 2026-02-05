"""
Flask Routes Module

This module contains all the route handlers for the Flask server.
It defines the HTTP endpoints and their associated logic for:
- User authentication and session management
- Navigation between annotation phases
- Form handling and validation
- Annotation submission and processing
- User registration and management
- Admin dashboard functionality
- API endpoints for frontend integration

The routes handle the complete annotation workflow from initial login
through completion, including consent, instructions, training, annotation,
and post-study phases. They also provide admin functionality for monitoring
progress and managing the annotation system.

Key Features:
- Session-based authentication with timeout management
- Multi-phase workflow support with configurable phases
- Annotation submission with validation and persistence
- AI hint integration for improved annotation quality
- Admin dashboard with comprehensive statistics
- API endpoints for real-time frontend updates
- Error handling and user feedback
"""
from __future__ import annotations

import json
import logging
import datetime
from datetime import timedelta
from flask import Flask, session, render_template, request, redirect, url_for, jsonify, make_response
import time
import uuid

# Import from the main flask_server.py module
from potato.flask_server import (
    app, config, logger,
    get_user_state_manager, get_user_state, get_item_state_manager,
    init_user_state, UserAuthenticator, UserPhase,
    move_to_prev_instance, move_to_next_instance, go_to_id,
    get_annotations_for_user_on, get_span_annotations_for_user_on,
    render_page_with_annotations, get_current_page_html,
    validate_annotation, parse_html_span_annotation, Label, SpanAnnotation,
    get_users, get_total_annotations, update_annotation_state,
    get_ai_cache_manager,
    get_users, get_total_annotations, update_annotation_state, ai_hints,
    get_training_instances, get_training_correct_answers, get_training_explanation,
    get_training_instance_categories, get_prolific_study, get_keyword_highlight_patterns,
    get_keyword_highlight_settings
)

# Import admin dashboard functionality
from potato.admin import admin_dashboard

# Import span color functions
from potato.ai.ai_help_wrapper import generate_ai_help_html
from potato.ai.ai_prompt import get_ai_prompt
from potato.server_utils.schemas.span import get_span_color, set_span_color, SPAN_COLOR_PALETTE

# Import annotation history
from potato.annotation_history import AnnotationHistoryManager
from potato.logging_config import is_ui_debug_enabled, get_debug_log_settings

# Import quality control
from potato.quality_control import get_quality_control_manager

import os


def get_debug_phase_target(debug_phase: str) -> tuple:
    """
    Parse the debug_phase string and find the matching phase and page.

    The debug_phase can be:
    - A phase type name like "annotation", "prestudy", "poststudy"
    - A specific page name within a phase (e.g., "consent_page_1")

    Args:
        debug_phase: The debug phase string from config

    Returns:
        tuple: (UserPhase, page_name) or (None, None) if not found
    """
    if not debug_phase:
        return None, None

    usm = get_user_state_manager()

    # First, try to match as a phase type (case-insensitive)
    try:
        phase = UserPhase.fromstr(debug_phase)
        # Check if this phase exists in the config
        if phase in usm.phase_type_to_name_to_page:
            pages = list(usm.phase_type_to_name_to_page[phase].keys())
            if pages:
                return phase, pages[0]
        # Special handling for ANNOTATION phase which is always available
        if phase == UserPhase.ANNOTATION:
            return phase, "annotation"
        return None, None
    except (ValueError, KeyError):
        pass

    # If not a phase type, search for it as a page name
    for phase_type, pages_dict in usm.phase_type_to_name_to_page.items():
        for page_name in pages_dict.keys():
            if page_name.lower() == debug_phase.lower():
                return phase_type, page_name

    logger.warning(f"Debug phase '{debug_phase}' not found in configured phases")
    return None, None


def apply_debug_phase_skip(user_id: str) -> bool:
    """
    Apply debug phase skip if configured.

    Args:
        user_id: The user ID to apply the skip for

    Returns:
        bool: True if skip was applied, False otherwise
    """
    debug_phase = config.get("debug_phase")
    if not debug_phase:
        return False

    phase, page = get_debug_phase_target(debug_phase)
    if phase is None:
        logger.warning(f"Could not apply debug phase skip: '{debug_phase}' not found")
        return False

    usm = get_user_state_manager()
    user_state = usm.get_user_state(user_id)

    if user_state:
        user_state.advance_to_phase(phase, page)
        logger.info(f"Debug: Skipped user '{user_id}' to phase '{phase.value}', page '{page}'")
        return True

    return False

# Cache for auto-generated admin API key
_generated_admin_api_key = None

def get_admin_api_key():
    """Get the admin API key from config, environment variable, or auto-generate one.

    Priority order:
    1. Config file: admin_api_key setting
    2. Environment variable: POTATO_ADMIN_API_KEY
    3. Auto-generated: Creates a random key and saves it to {task_dir}/admin_api_key.txt

    Returns:
        str or None: The admin API key, or None if generation fails.
    """
    global _generated_admin_api_key

    # Check config first
    configured_key = config.get("admin_api_key")
    if configured_key:
        return configured_key

    # Check environment variable
    env_key = os.environ.get("POTATO_ADMIN_API_KEY")
    if env_key:
        return env_key

    # Return cached generated key if we have one
    if _generated_admin_api_key:
        return _generated_admin_api_key

    # Auto-generate a key and save it to task directory
    task_dir = config.get("task_dir", ".")
    if not task_dir:
        task_dir = "."

    key_file_path = os.path.join(task_dir, "admin_api_key.txt")

    # Check if a key file already exists (from previous run)
    if os.path.exists(key_file_path):
        try:
            with open(key_file_path, 'r') as f:
                existing_key = f.read().strip()
                if existing_key:
                    _generated_admin_api_key = existing_key
                    logger.info(f"Loaded existing admin API key from {key_file_path}")
                    return _generated_admin_api_key
        except Exception as e:
            logger.warning(f"Could not read existing admin API key file: {e}")

    # Generate a new key
    import secrets
    _generated_admin_api_key = secrets.token_urlsafe(32)

    # Save to file
    try:
        with open(key_file_path, 'w') as f:
            f.write(_generated_admin_api_key)
        logger.info(f"Generated admin API key and saved to {key_file_path}")
        logger.info(f"Use this key to access the admin dashboard at /admin")
    except Exception as e:
        logger.warning(f"Could not save admin API key to file: {e}")
        logger.info(f"Auto-generated admin API key (not persisted): {_generated_admin_api_key}")

    return _generated_admin_api_key

def validate_admin_api_key(provided_key: str) -> bool:
    """Validate an admin API key against the configured or auto-generated key.

    In debug mode, admin endpoints are accessible without a key.
    Otherwise, the provided key must match the configured or auto-generated key.

    Args:
        provided_key: The API key provided in the request.

    Returns:
        bool: True if the key is valid or debug mode is enabled.
    """
    debug_val = config.get("debug", False)
    if debug_val:
        return True

    expected_key = get_admin_api_key()
    if not expected_key:
        # This should rarely happen since we auto-generate keys
        logger.warning("Could not obtain admin API key")
        return False

    # Use constant-time comparison to prevent timing attacks
    import hmac
    return hmac.compare_digest(str(provided_key or ""), expected_key)

@app.route("/", methods=["GET", "POST"])
def home():
    """
    Handle requests to the home page.

    This route serves as the main entry point for the annotation platform.
    It handles session management, user authentication, and phase routing
    based on the user's current state in the annotation workflow.

    Features:
    - Session validation and timeout management
    - User authentication and state initialization
    - Phase-based routing to appropriate pages
    - Survey flow management
    - Progress tracking and validation
    - URL-direct login for crowdsourcing platforms (Prolific, MTurk, etc.)

    Returns:
        flask.Response: Rendered template or redirect based on user state

    Side Effects:
        - May initialize new user state
        - May advance user phases
        - May clear invalid sessions
    """
    logger.debug("Processing home page request")

    # In debug mode with debug_phase, auto-login and skip to the specified phase
    if config.get("debug") and config.get("debug_phase") and 'username' not in session:
        debug_user = "debug_user"
        logger.info(f"Debug mode: Auto-logging in as '{debug_user}' and skipping to phase '{config.get('debug_phase')}'")

        # Auto-register the debug user if needed
        user_authenticator = UserAuthenticator.get_instance()
        if not user_authenticator.is_valid_username(debug_user):
            user_authenticator.add_user(debug_user, None)

        # Set session
        session['username'] = debug_user
        session.permanent = True

        # Initialize user state and apply debug phase skip
        usm = get_user_state_manager()
        if not usm.has_user(debug_user):
            usm.add_user(debug_user)

        # Apply the debug phase skip
        apply_debug_phase_skip(debug_user)

        # Redirect to home to process the new session
        return redirect(url_for("home"))

    # Check if user has an active session
    if 'username' not in session:
        # Check for URL-direct login (used by Prolific, MTurk, etc.)
        login_config = config.get('login', {})
        login_type = login_config.get('type', 'standard')

        if login_type in ['url_direct', 'prolific']:
            # Get the URL argument name (default to PROLIFIC_PID for backwards compatibility)
            url_argument = login_config.get('url_argument', 'PROLIFIC_PID')
            username = request.args.get(url_argument)

            # Also capture SESSION_ID and STUDY_ID if provided (for Prolific tracking)
            prolific_session_id = request.args.get('SESSION_ID')
            prolific_study_id = request.args.get('STUDY_ID')

            # Capture MTurk-specific parameters
            mturk_assignment_id = request.args.get('assignmentId')
            mturk_hit_id = request.args.get('hitId')
            mturk_submit_to = request.args.get('turkSubmitTo')

            # Handle MTurk preview mode (worker hasn't accepted the HIT yet)
            if mturk_assignment_id == 'ASSIGNMENT_ID_NOT_AVAILABLE':
                logger.info("MTurk preview mode detected - showing preview page")
                return render_template("mturk_preview.html",
                                      title=config.get("annotation_task_name", "Task Preview"),
                                      task_description=config.get("task_description", ""),
                                      annotation_task_name=config.get("annotation_task_name", "Annotation Task"))

            if username:
                logger.info(f"URL-direct login: user={username}, session_id={prolific_session_id}, study_id={prolific_study_id}")

                # Auto-register and login the user
                user_authenticator = UserAuthenticator.get_instance()

                # Add user if not exists (passwordless for URL-direct)
                if not user_authenticator.is_valid_username(username):
                    result = user_authenticator.add_user(username, None,
                                                         prolific_session_id=prolific_session_id,
                                                         prolific_study_id=prolific_study_id)
                    logger.debug(f"Auto-registered URL-direct user {username}: {result}")

                # Set session
                session['username'] = username
                session.permanent = True

                # Store Prolific IDs in session for later use
                if prolific_session_id:
                    session['prolific_session_id'] = prolific_session_id
                if prolific_study_id:
                    session['prolific_study_id'] = prolific_study_id

                # Store MTurk IDs in session for completion flow
                if mturk_assignment_id:
                    session['mturk_assignment_id'] = mturk_assignment_id
                if mturk_hit_id:
                    session['mturk_hit_id'] = mturk_hit_id
                if mturk_submit_to:
                    session['mturk_submit_to'] = mturk_submit_to

                # Initialize user state if needed
                if not get_user_state_manager().has_user(username):
                    logger.debug(f"Initializing user state for URL-direct user: {username}")
                    init_user_state(username)

                # Get the user state and set to first phase
                usm = get_user_state_manager()
                user_state = usm.get_user_state(username)

                if user_state:
                    # Determine the first phase from config
                    phases_config = config.get('phases', {})
                    phases_order = phases_config.get('order', ['annotation'])
                    first_phase_name = phases_order[0] if phases_order else 'annotation'
                    first_phase = UserPhase.fromstr(first_phase_name)

                    # Set user to the first phase if they're in LOGIN
                    if user_state.get_phase() == UserPhase.LOGIN:
                        logger.debug(f"Advancing URL-direct user {username} to first phase: {first_phase}")
                        user_state.advance_to_phase(first_phase, None)

                    # Assign instances if user doesn't have any
                    if not user_state.has_assignments():
                        logger.debug(f"Assigning instances to URL-direct user {username}")
                        get_item_state_manager().assign_instances_to_user(user_state)

                    # Track with Prolific API if configured
                    prolific_study = get_prolific_study()
                    if prolific_study and prolific_session_id:
                        try:
                            prolific_study.add_new_user({
                                'PROLIFIC_PID': username,
                                'SESSION_ID': prolific_session_id
                            })
                            logger.debug(f"Tracked user {username} with Prolific API")
                        except Exception as e:
                            logger.warning(f"Failed to track user with Prolific API: {e}")

                # Redirect to home to process the now-logged-in user
                return redirect(url_for("home"))

            else:
                # URL-direct login configured but no username in URL
                # Show error or redirect to a waiting page
                logger.warning(f"URL-direct login configured but '{url_argument}' not found in URL")
                return render_template("error.html",
                                      message=f"Missing required URL parameter: {url_argument}. "
                                              f"Please access this page through your crowdsourcing platform.")

        logger.debug("No active session, rendering login page")
        return render_template("home.html",
                              title=config.get("annotation_task_name", "Annotation Platform"),
                              require_password=config.get("require_password", True))

    user_id = session['username']
    logger.debug(f"Active session for user: {user_id}")

    # Get user state and validate it exists
    user_state = get_user_state(user_id)
    if user_state is None:
        logger.warning(f"User {user_id} not found in user state")
        session.clear()
        return redirect(url_for("auth"))

    # Get the current phase of the user and route accordingly
    phase = user_state.get_phase()
    logger.debug(f"User phase: {phase}")

    # Route to appropriate phase handler based on current phase
    if phase == UserPhase.LOGIN:
        return auth() #redirect(url_for("auth"))
    elif phase == UserPhase.CONSENT:
        return consent() #redirect(url_for("consent"))
    elif phase == UserPhase.PRESTUDY:
        return prestudy() #redirect(url_for("prestudy"))
    elif phase == UserPhase.INSTRUCTIONS:
        return instructions() #redirect(url_for("instructions"))
    elif phase == UserPhase.TRAINING:
        return training() #redirect(url_for("training"))
    elif phase == UserPhase.ANNOTATION:
        return annotate() # redirect(url_for("annotate"))
    elif phase == UserPhase.POSTSTUDY:
        return poststudy() #redirect(url_for("poststudy"))
    elif phase == UserPhase.DONE:
        return done() #redirect(url_for("done"))

    logger.error(f"Invalid phase for user {user_id}: {phase}")
    return render_template("error.html", message="Invalid application state")


@app.route("/auth", methods=["GET", "POST"])
def auth():
    """
    Handle authentication requests.

    This route manages user authentication for the annotation platform.
    It supports both password-based and passwordless authentication modes
    depending on the system configuration.

    Features:
    - Session validation and management
    - User authentication against configured backends
    - User state initialization for new users
    - Error handling and user feedback
    - Redirect logic based on authentication success

    Returns:
        flask.Response: Rendered template or redirect

    Side Effects:
        - May create new user sessions
        - May initialize new user states
        - May clear existing sessions
    """
    # Check if user is already logged in
    if 'username' in session and get_user_state_manager().has_user(session['username']):
        logger.debug(f"User {session['username']} already logged in, redirecting to annotate")
        return redirect(url_for("annotate"))

    # Handle POST requests for user authentication
    if request.method == "POST":
        user_id = request.form.get("email")
        password = request.form.get("pass")

        logger.debug(f"Login attempt for user: {user_id}")

        # Get require_password setting
        require_password = config.get("require_password", True)

        # Validate that user ID is provided
        if not user_id:
            logger.warning("Login attempt with empty user_id")
            return render_template("home.html",
                                  login_error="User ID is required",
                                  title=config.get("annotation_task_name", "Annotation Platform"),
                                  require_password=require_password)

        # In passwordless mode, auto-register new users
        if not require_password:
            user_authenticator = UserAuthenticator.get_instance()
            if not user_authenticator.is_valid_username(user_id):
                logger.info(f"Auto-registering new user in passwordless mode: {user_id}")
                user_authenticator.add_user(user_id, None)

        # Authenticate the user against the configured backend
        if UserAuthenticator.authenticate(user_id, password):
            session.clear()  # Clear any existing session data
            session['username'] = user_id
            session.permanent = True  # Make session persist longer
            logger.info(f"Login successful for user: {user_id}")

            # Initialize user state if needed
            if not get_user_state_manager().has_user(user_id):
                logger.debug(f"Initializing state for new user: {user_id}")
                usm = get_user_state_manager()
                usm.add_user(user_id)

                # Check for debug phase skip
                if config.get("debug") and config.get("debug_phase"):
                    if apply_debug_phase_skip(user_id):
                        return redirect(url_for("home"))
                    else:
                        # Fall back to normal phase advancement
                        usm.advance_phase(user_id)
                else:
                    usm.advance_phase(user_id)
                return redirect(url_for("annotate"))
            return redirect(url_for("annotate"))
        else:
            logger.warning(f"Login failed for user: {user_id}")
            error_msg = "Invalid user ID or password" if require_password else "Login failed"
            return render_template("home.html",
                                  login_error=error_msg,
                                  login_email=user_id,
                                  title=config.get("annotation_task_name", "Annotation Platform"),
                                  require_password=require_password)

    # GET request - show the login form
    return render_template("home.html",
                         title=config.get("annotation_task_name", "Annotation Platform"),
                         require_password=config.get("require_password", True))


@app.route("/passwordless-login", methods=["GET", "POST"])
def passwordless_login():
    """
    Legacy route for passwordless login.

    This route now redirects to the main home page, which handles
    both password and passwordless authentication based on the
    require_password config setting.

    Kept for backwards compatibility with existing links/bookmarks.
    """
    logger.debug("Redirecting from legacy passwordless-login to home")
    return redirect(url_for("home"))


@app.route("/clerk-login", methods=["GET", "POST"])
def clerk_login():
    """
    Handle Clerk SSO login process.

    This route manages authentication through Clerk's single sign-on service.
    It handles token validation and user session creation for SSO users.

    Features:
    - Clerk SSO integration
    - Token validation and verification
    - User session management
    - Error handling for SSO failures

    Returns:
        flask.Response: Rendered template or redirect

    Side Effects:
        - May create new user sessions
        - May initialize new user states
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
    Handle login requests - render the auth page directly

    Returns:
        flask.Response: Rendered auth template
    """
    logger.debug("Rendering auth page for /login")
    return auth()

@app.route("/logout", methods=["GET"])
def logout_page():
    """
    Handle user logout requests and redirect to login page.

    Returns:
        flask.Response: Redirect to login page
    """
    logger.debug("Processing logout request")

    # Clear the session
    session.clear()
    logger.info("User logged out successfully")

    return redirect(url_for("home"))  # Redirect to the login page

@app.route("/logout", methods=["POST"])
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
    logger.debug("Redirecting /logout to logout_page")
    return logout_page()

@app.route("/submit_annotation", methods=["POST"])
def submit_annotation():
    """
    DEPRECATED: Handle annotation submission requests.

    This route was added by Cursor and duplicates functionality from /updateinstance.
    It only handles label annotations (not span annotations) and is used primarily
    for saving annotations during navigation in newer templates.

    TODO: This route should be deprecated and all functionality moved to /updateinstance
    to reduce confusion and ensure consistent handling of both label and span annotations.

    Features:
    - Validation checking
    - Progress tracking
    - State updates
    - AI integration
    - Data persistence

    Args (from form or JSON):
        instance_id: ID of annotated instance
        annotations: annotation data (either JSON string or dict) - LABEL ANNOTATIONS ONLY
        user_id: user ID (optional, defaults to session)

    Returns:
        flask.Response: JSON response with submission result
    """
    logger.debug("=== SUBMIT ANNOTATION ROUTE START ===")
    logger.debug(f"Session: {dict(session)}")
    logger.debug(f"Session username: {session.get('username', 'NOT_SET')}")
    logger.debug(f"Request content type: {request.content_type}")
    logger.debug(f"Request is JSON: {request.is_json}")
    logger.debug(f"Request headers: {dict(request.headers)}")
    logger.debug(f"Debug mode: {config.get('debug', False)}")


    if 'username' not in session:
        logger.warning("Annotation submission without active session")
        return jsonify({"status": "error", "message": "No active session"})

    user_id = session['username']
    logger.debug(f"Using user_id: {user_id}")
    logger.debug(f"All users in state manager: {get_user_state_manager().get_user_ids()}")
    logger.debug(f"User state manager has user '{user_id}': {get_user_state_manager().has_user(user_id)}")

    # Handle both form data and JSON data
    if request.is_json:
        data = request.get_json()
        instance_id = data.get("instance_id")
        annotations = data.get("annotations", {})
        logger.debug(f"Received JSON data: {data}")
    else:
        instance_id = request.form.get("instance_id")
        annotation_data = request.form.get("annotation_data")
        logger.debug(f"Received form data: {dict(request.form)}")
        if annotation_data:
            annotations = json.loads(annotation_data)
            logger.debug(f"Parsed annotation_data: {annotations}")
        else:
            annotations = {}
            logger.debug("No annotation_data found in form")

    logger.debug(f"Instance ID: {instance_id}")
    logger.debug(f"Annotations: {annotations}")

    if not instance_id:
        logger.warning("Missing instance_id")
        return jsonify({"status": "error", "message": "Missing instance_id"})

    try:
        logger.debug(f"Getting user state for user_id: {user_id}")
        user_state = get_user_state(user_id)
        logger.debug(f"Retrieved user state: {user_state}")
        logger.debug(f"User state phase: {user_state.get_phase() if user_state else 'No user state'}")


        # Process the annotations
        annotations_processed = 0
        for schema_name, label_data in annotations.items():
            logger.debug(f"Processing schema: {schema_name}, label_data: {label_data}, type: {type(label_data)}")

            if isinstance(label_data, dict):
                # Nested structure: {'schema': {'label': 'value'}}
                for label_name, value in label_data.items():
                    label = Label(schema_name, label_name)
                    logger.debug(f"Adding annotation: {schema_name}:{label_name} = {value}")
                    user_state.add_label_annotation(instance_id, label, value)
                    annotations_processed += 1
            elif isinstance(label_data, str):
                # Direct string value for text annotations: {'schema': 'value'}
                # For text annotations, we need to create a label with a default name
                label = Label(schema_name, "text_box")
                logger.debug(f"Adding text annotation: {schema_name}:text_box = {label_data}")
                user_state.add_label_annotation(instance_id, label, label_data)
                annotations_processed += 1
            else:
                logger.warning(f"Unexpected label_data type: {type(label_data)} for schema {schema_name}")

        logger.debug(f"Processed {annotations_processed} annotations")

        # Register the annotator for this instance
        logger.debug(f"Registering annotator {user_id} for instance {instance_id}")
        get_item_state_manager().register_annotator(instance_id, user_id)

        # Save the user state
        logger.debug(f"Saving user state for {user_id}")
        get_user_state_manager().save_user_state(user_state)
        logger.debug(f"User state saved successfully")

        # Check if this was an ICL verification task and record the result
        _maybe_record_icl_verification(user_state, instance_id, annotations)

        # Log the saved annotations
        all_annotations = user_state.get_all_annotations()
        logger.debug(f"All annotations after save: {all_annotations}")
        logger.debug(f"Annotations for instance {instance_id}: {all_annotations.get(instance_id, 'Not found')}")


        logger.info(f"Successfully saved annotation for {instance_id} from {user_id}")
        logger.debug("=== SUBMIT ANNOTATION ROUTE END ===")
        return jsonify({"status": "success", "message": "Annotation saved successfully", "annotations_processed": annotations_processed})

    except Exception as e:
        logger.error(f"Error saving annotation: {str(e)}")
        logger.debug(f"Exception details: {type(e).__name__}: {str(e)}")
        import traceback
        logger.debug(f"Traceback: {traceback.format_exc()}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": f"Failed to save annotation: {str(e)}"})

@app.route("/register", methods=["POST"])
def register():
    """
    Register a new user and initialize their user state.

    Args:
        username: The username to initialize state for
    """
    logger.debug("=== REGISTER ROUTE START ===")
    logger.debug(f"Session before registration: {dict(session)}")
    logger.debug(f"Request form data: {dict(request.form)}")
    logger.debug(f"Request headers: {dict(request.headers)}")

    if 'username' in session:
        logger.warning(f"User already logged in with username: {session['username']}, redirecting to annotate")
        return home()

    username = request.form.get("email")
    password = request.form.get("pass")

    logger.debug(f"Registration attempt for username: {username}")

    if not username or not password:
        logger.warning("Missing username or password")
        return render_template("home.html",
                                login_error="Username and password are required")

    # Register the user with the autheticator
    logger.debug("Adding user to authenticator...")
    user_authenticator = UserAuthenticator.get_instance()
    user_authenticator.add_user(username, password)

    logger.debug("Setting session variables...")
    session['username'] = username
    session.permanent = True

    logger.debug(f"Session after registration: {dict(session)}")
    logger.debug(f"Session ID: {session.sid if hasattr(session, 'sid') else 'No session ID'}")
    logger.debug(f"User state manager has user '{username}': {get_user_state_manager().has_user(username)}")
    logger.debug(f"All users in state manager: {get_user_state_manager().get_user_ids()}")

    # Initialize user state if needed
    if not get_user_state_manager().has_user(username):
        logger.debug(f"Initializing user state for new user: {username}")
        init_user_state(username)
        logger.debug(f"User state initialized. User exists: {get_user_state_manager().has_user(username)}")
        logger.debug(f"All users in state manager after init: {get_user_state_manager().get_user_ids()}")

    # Ensure user is in the correct starting phase
    usm = get_user_state_manager()
    user_state = usm.get_user_state(username)
    logger.debug(f"Retrieved user state for '{username}': {user_state}")
    logger.debug(f"User state phase: {user_state.get_phase() if user_state else 'No user state'}")

    # Determine the first phase from config
    phases_config = config.get('phases', {})
    phases_order = phases_config.get('order', ['annotation'])
    first_phase_name = phases_order[0] if phases_order else 'annotation'
    # Get the phase type from the config (phase name may differ from type, e.g., 'prescreen' has type 'prestudy')
    first_phase_config = phases_config.get(first_phase_name, {})
    first_phase_type = first_phase_config.get('type', first_phase_name)
    first_phase = UserPhase.fromstr(first_phase_type)
    logger.debug(f"First phase from config: {first_phase_name} (type={first_phase_type}) -> {first_phase}")

    # Set user to the first phase if they're in LOGIN
    if user_state and user_state.get_phase() == UserPhase.LOGIN:
        logger.debug(f"Advancing user {username} to first phase: {first_phase}")
        # Use first_phase_name as the page since that's the key in the phase config
        user_state.advance_to_phase(first_phase, first_phase_name)
        logger.debug(f"User state phase after advancement: {user_state.get_phase()}")

    # Assign instances if user doesn't have any
    if user_state and not user_state.has_assignments():
        logger.debug(f"Assigning instances to user {username}")
        get_item_state_manager().assign_instances_to_user(user_state)
        logger.debug(f"User has assignments after assignment: {user_state.has_assignments()}")

    logger.debug("=== REGISTER ROUTE END - Redirecting to home ===")
    # Redirect to home which will route to the appropriate phase
    return redirect(url_for("home"))

@app.route("/consent", methods=["GET", "POST"])
def consent():
    """
    Handle the consent phase of the annotation process.

    Returns:
        flask.Response: Rendered template or redirect
    """
    if 'username' not in session:
        return home()

    username = session['username']
    user_state = get_user_state(username)
    logger.debug(f'CONSENT: user_state: {user_state}')
    logger.debug(f'CONSENT: user_state.get_phase(): {user_state.get_phase()}')

    # Check that the user is still in the consent phase
    if user_state.get_phase() != UserPhase.CONSENT:
        # If not in the consent phase, redirect
        return home()

    # If the user is returning information from the page
    if request.method == 'POST':
        # The form should require that the user consent to the study
        logger.debug(f'POST -> CONSENT: {request.form}')

        # Now that the user has consented, advance the state
        # and have the home page redirect to the appropriate next phase
        usm = get_user_state_manager()
        usm.advance_phase(session['username'])

        # Reset to pretend this is a new get request
        request.method = 'GET'
        return home()
    # Show the current consent form
    else:
        logger.debug("GET <- CONSENT")
        return get_current_page_html(config, username)

@app.route("/instructions", methods=["GET", "POST"])
def instructions():
    """
    Handle the instructions phase of the annotation process.

    Returns:
        flask.Response: Rendered template or redirect
    """
    if 'username' not in session:
        return home()

    username = session['username']
    user_state = get_user_state(username)

    # Check that the user is in the instructions phase
    if user_state.get_phase() != UserPhase.INSTRUCTIONS:
        # If not in the instructions phase, redirect
        return home()

    # If the user is returning information from the page
    if request.method == 'POST':
        logger.debug(f'POST -> INSTRUCTIONS: {request.form}')

        # Now that the user has read the instructions, advance the state
        # and have the home page redirect to the appropriate next phase
        usm = get_user_state_manager()
        usm.advance_phase(session['username'])
        request.method = 'GET'
        return home()

    # Show the current set of instructions
    else:
        # Get the page the user is currently on
        phase, page = user_state.get_current_phase_and_page()
        logger.debug(f'GET <-- INSTRUCTIONS: phase, page: {phase}, {page}')

        usm = get_user_state_manager()
        # Look up the html template for the current instructions
        instructions_html_fname = usm.get_phase_html_fname(phase, page)
        # Render the instructions with necessary context variables
        return render_template(instructions_html_fname,
                             annotation_task_name=config.get("annotation_task_name", "Annotation Task"),
                             title=config.get("annotation_task_name", "Instructions"),
                             username=session.get('username', ''),
                             debug_mode=config.get("debug", False),
                             ui_debug=config.get("ui_debug", False),
                             server_debug=config.get("server_debug", False),
                             debug_phase=config.get("debug_phase"),
                             ui_config=config.get("ui_config", {}))

@app.route("/training", methods=["GET", "POST"])
def training():
    """
    Handle the training phase of the annotation process.

    This route manages the training phase where users practice annotation
    with feedback on their performance. It supports:
    - Displaying training instances with correct answers
    - Processing user annotations and providing feedback
    - Tracking training progress and performance
    - Advancing users based on training performance criteria
    - Allowing retries for failed attempts
    - Kicking out users who exceed max_mistakes threshold

    Training Configuration Options:
    - min_correct: Minimum correct answers needed to pass
    - require_all_correct: Whether all questions must be correct
    - max_mistakes: Maximum total mistakes before failure (kicked out)
    - max_mistakes_per_question: Maximum mistakes per question before failure
    - allow_retry: Whether to allow retrying incorrect answers
    - failure_action: "move_to_done" (kick out) or "repeat_training"

    Returns:
        flask.Response: Rendered template or redirect
    """
    if 'username' not in session:
        return home()

    username = session['username']
    user_state = get_user_state(username)

    # Check that the user is in the training phase
    if user_state.get_phase() != UserPhase.TRAINING:
        logger.debug(f'User {username} not in training phase, redirecting')
        return home()

    # Check if training is enabled in config
    training_config = config.get('training', {})
    if not training_config.get('enabled', False):
        logger.debug('Training not enabled, advancing to next phase')
        usm = get_user_state_manager()
        usm.advance_phase(username)
        return home()

    # Get training state and initialize max_mistakes from config if not set
    training_state = user_state.get_training_state()
    passing_criteria = training_config.get('passing_criteria', {})

    # Initialize training instances if not already done
    if not training_state.training_instances:
        training_instances = get_training_instances()
        training_state.set_training_instances([item.get_id() for item in training_instances])

    # Set max_mistakes from config
    if training_state.max_mistakes == -1 and 'max_mistakes' in passing_criteria:
        training_state.set_max_mistakes(passing_criteria.get('max_mistakes', -1))
    if training_state.max_mistakes_per_question == -1 and 'max_mistakes_per_question' in passing_criteria:
        training_state.set_max_mistakes_per_question(passing_criteria.get('max_mistakes_per_question', -1))

    # Check if user has already failed due to too many mistakes
    if training_state.is_failed() or training_state.should_fail_due_to_mistakes():
        training_state.set_failed(True)
        logger.info(f'User {username} has failed training due to too many mistakes')
        # Move to DONE phase (kick out)
        user_state.set_current_phase_and_page((UserPhase.DONE, None))
        return render_template("training_failed.html",
                             message="You have exceeded the maximum number of allowed mistakes and cannot continue.",
                             total_mistakes=training_state.get_total_mistakes(),
                             max_mistakes=training_state.max_mistakes,
                             annotation_task_name=config.get("annotation_task_name", "Annotation Platform"),
                             username=username)

    # Get progress info
    total_questions = len(training_state.training_instances)
    current_question_num = training_state.get_current_question_index() + 1

    # Handle POST requests (annotation submission)
    if request.method == 'POST':
        logger.debug(f'POST -> TRAINING: {request.form}')

        # Get the current training instance
        current_instance = user_state.get_current_training_instance()
        if not current_instance:
            logger.error(f'No training instance available for user {username}')
            return render_template("error.html", message="No training instance available")

        instance_id = current_instance.get_id()
        instance_text = current_instance.get_data().get('displayed_text', current_instance.get_data().get('text', ''))

        # Process the annotation
        if request.is_json:
            annotation_data = request.get_json()
        else:
            annotation_data = dict(request.form)

        # Get correct answers for this training instance
        correct_answers = get_training_correct_answers(instance_id)
        if not correct_answers:
            logger.error(f'No correct answers found for training instance {instance_id}')
            return render_template("error.html", message="Training data error")

        # Validate and process the annotation
        try:
            # Update user's training answer
            user_state.update_training_answer(instance_id, annotation_data)

            # Check if the answer is correct
            is_correct = check_training_answer(annotation_data, correct_answers)

            # Track category performance for category-based assignment
            instance_categories = get_training_instance_categories(instance_id)
            if instance_categories:
                training_state.record_category_answer(instance_categories, is_correct)

            if is_correct:
                logger.info(f'User {username} answered training question {instance_id} correctly')
                # Record correct answer
                training_state.add_answer(instance_id, True, training_state.get_mistakes_for_question(instance_id) + 1)
                training_state.clear_feedback()

                # Check if user has passed based on min_correct
                min_correct = passing_criteria.get('min_correct', len(training_state.training_instances))
                if training_state.get_correct_answer_count() >= min_correct:
                    # User has passed training
                    training_state.set_passed(True)
                    logger.info(f'User {username} passed training with {training_state.get_correct_answer_count()} correct answers')

                    # Calculate category qualifications based on training performance
                    cat_config = config.get('category_assignment', {})
                    if cat_config.get('enabled', False):
                        qual_config = cat_config.get('qualification', {})
                        threshold = qual_config.get('threshold', 0.7)
                        min_questions = qual_config.get('min_questions', 1)
                        qualified = user_state.calculate_and_set_qualifications(threshold, min_questions)
                        if qualified:
                            logger.info(f'User {username} qualified for categories: {qualified}')

                    usm = get_user_state_manager()
                    usm.advance_phase(username)
                    return home()

                # Move to next training question or complete training
                if user_state.advance_training_question():
                    # More questions available
                    training_state.set_feedback(True, "Correct! Moving to next question.", False)
                    # Get next instance for display
                    next_instance = user_state.get_current_training_instance()
                    next_instance_text = next_instance.get_data().get('displayed_text', next_instance.get_data().get('text', ''))
                    return render_template("training.html",
                                         instance_text=next_instance_text,
                                         instance_id=next_instance.get_id(),
                                         feedback="Correct! Moving to next question.",
                                         feedback_type="success",
                                         show_feedback=True,
                                         allow_retry=False,
                                         current_question=current_question_num + 1,
                                         total_questions=total_questions,
                                         correct_count=training_state.get_correct_answer_count(),
                                         mistake_count=training_state.get_total_mistakes(),
                                         annotation_task_name=config.get("annotation_task_name", "Annotation Platform"),
                                         username=username)
                else:
                    # All questions completed
                    require_all = passing_criteria.get('require_all_correct', False)
                    if require_all and training_state.get_correct_answer_count() < total_questions:
                        # User didn't get all correct
                        training_state.set_failed(True)
                        user_state.set_current_phase_and_page((UserPhase.DONE, None))
                        return render_template("training_failed.html",
                                             message="You did not answer all training questions correctly.",
                                             correct_count=training_state.get_correct_answer_count(),
                                             total_questions=total_questions,
                                             annotation_task_name=config.get("annotation_task_name", "Annotation Platform"),
                                             username=username)
                    else:
                        # Training completed successfully
                        training_state.set_passed(True)
                        logger.info(f'User {username} completed training successfully')

                        # Calculate category qualifications based on training performance
                        cat_config = config.get('category_assignment', {})
                        if cat_config.get('enabled', False):
                            qual_config = cat_config.get('qualification', {})
                            threshold = qual_config.get('threshold', 0.7)
                            min_questions = qual_config.get('min_questions', 1)
                            qualified = user_state.calculate_and_set_qualifications(threshold, min_questions)
                            if qualified:
                                logger.info(f'User {username} qualified for categories: {qualified}')

                        usm = get_user_state_manager()
                        usm.advance_phase(username)
                        return home()
            else:
                logger.info(f'User {username} answered training question {instance_id} incorrectly')
                # Record the mistake
                training_state.record_mistake(instance_id)

                # Check if user should fail due to too many mistakes
                if training_state.should_fail_due_to_mistakes():
                    training_state.set_failed(True)
                    logger.info(f'User {username} failed training - exceeded max_mistakes ({training_state.max_mistakes})')
                    user_state.set_current_phase_and_page((UserPhase.DONE, None))
                    return render_template("training_failed.html",
                                         message="You have exceeded the maximum number of allowed mistakes.",
                                         total_mistakes=training_state.get_total_mistakes(),
                                         max_mistakes=training_state.max_mistakes,
                                         annotation_task_name=config.get("annotation_task_name", "Annotation Platform"),
                                         username=username)

                # Check if user should fail due to too many mistakes on this question
                if training_state.should_fail_question_due_to_mistakes(instance_id):
                    training_state.set_failed(True)
                    logger.info(f'User {username} failed training - exceeded max_mistakes_per_question on {instance_id}')
                    user_state.set_current_phase_and_page((UserPhase.DONE, None))
                    return render_template("training_failed.html",
                                         message="You have made too many mistakes on a single question.",
                                         question_mistakes=training_state.get_mistakes_for_question(instance_id),
                                         max_mistakes_per_question=training_state.max_mistakes_per_question,
                                         annotation_task_name=config.get("annotation_task_name", "Annotation Platform"),
                                         username=username)

                # Get explanation for incorrect answer
                explanation = get_training_explanation(instance_id)

                # Check if user should be allowed to retry
                allow_retry = training_config.get('allow_retry', True)

                if allow_retry:
                    training_state.set_feedback(True, f"Incorrect. {explanation}", True)
                    return render_template("training.html",
                                         instance_text=instance_text,
                                         instance_id=instance_id,
                                         feedback=f"Incorrect. {explanation}",
                                         feedback_type="error",
                                         show_feedback=True,
                                         allow_retry=True,
                                         current_question=current_question_num,
                                         total_questions=total_questions,
                                         correct_count=training_state.get_correct_answer_count(),
                                         mistake_count=training_state.get_total_mistakes(),
                                         annotation_task_name=config.get("annotation_task_name", "Annotation Platform"),
                                         username=username)
                else:
                    # No retry allowed - check failure action
                    failure_action = training_config.get('failure_action', 'move_to_done')
                    if failure_action == 'move_to_done':
                        training_state.set_failed(True)
                        logger.info(f'User {username} failed training - no retry allowed')
                        user_state.set_current_phase_and_page((UserPhase.DONE, None))
                        return render_template("training_failed.html",
                                             message="You answered incorrectly and retries are not allowed.",
                                             explanation=explanation,
                                             annotation_task_name=config.get("annotation_task_name", "Annotation Platform"),
                                             username=username)
                    else:
                        # Advance to next question even though wrong
                        if user_state.advance_training_question():
                            next_instance = user_state.get_current_training_instance()
                            next_instance_text = next_instance.get_data().get('displayed_text', next_instance.get_data().get('text', ''))
                            training_state.set_feedback(True, f"Incorrect. {explanation} Moving to next question.", False)
                            return render_template("training.html",
                                                 instance_text=next_instance_text,
                                                 instance_id=next_instance.get_id(),
                                                 feedback=f"Previous answer was incorrect: {explanation}",
                                                 feedback_type="warning",
                                                 show_feedback=True,
                                                 allow_retry=False,
                                                 current_question=current_question_num + 1,
                                                 total_questions=total_questions,
                                                 correct_count=training_state.get_correct_answer_count(),
                                                 mistake_count=training_state.get_total_mistakes(),
                                                 annotation_task_name=config.get("annotation_task_name", "Annotation Platform"),
                                                 username=username)
                        else:
                            # No more questions - check if passed
                            min_correct = passing_criteria.get('min_correct', total_questions)
                            if training_state.get_correct_answer_count() >= min_correct:
                                training_state.set_passed(True)
                                usm = get_user_state_manager()
                                usm.advance_phase(username)
                                return home()
                            else:
                                training_state.set_failed(True)
                                user_state.set_current_phase_and_page((UserPhase.DONE, None))
                                return render_template("training_failed.html",
                                                     message="You did not meet the minimum correct answers requirement.",
                                                     correct_count=training_state.get_correct_answer_count(),
                                                     min_correct=min_correct,
                                                     annotation_task_name=config.get("annotation_task_name", "Annotation Platform"),
                                                     username=username)

        except Exception as e:
            logger.error(f'Error processing training annotation: {e}')
            import traceback
            traceback.print_exc()
            return render_template("error.html", message="Error processing training annotation")

    # Handle GET requests (display training question)
    else:
        logger.debug(f'GET <-- TRAINING for user {username}')

        # Get the current training instance
        current_instance = user_state.get_current_training_instance()
        if not current_instance:
            logger.error(f'No training instance available for user {username}')
            return render_template("error.html", message="No training instance available")

        instance_text = current_instance.get_data().get('displayed_text', current_instance.get_data().get('text', ''))

        # Check if we should show feedback from previous attempt
        show_feedback = training_state.show_feedback if training_state else False
        feedback_message = training_state.feedback_message if training_state else ""
        allow_retry = training_state.allow_retry if training_state else False

        return render_template("training.html",
                             instance_text=instance_text,
                             instance_id=current_instance.get_id(),
                             feedback=feedback_message,
                             feedback_type="error" if allow_retry else "info",
                             show_feedback=show_feedback,
                             allow_retry=allow_retry,
                             current_question=current_question_num,
                             total_questions=total_questions,
                             correct_count=training_state.get_correct_answer_count(),
                             mistake_count=training_state.get_total_mistakes(),
                             annotation_task_name=config.get("annotation_task_name", "Annotation Platform"),
                             username=username)


def check_training_answer(user_answer: dict, correct_answers: dict) -> bool:
    """
    Check if the user's answer matches the correct answers.

    Handles different annotation types:
    - Radio/single select: string comparison
    - Multiselect/checkbox: set comparison (order-independent)
    - Likert/number: numeric comparison
    - Text: exact or fuzzy string match

    Args:
        user_answer: Dictionary of user's answers by schema name
        correct_answers: Dictionary of correct answers by schema name

    Returns:
        True if all answers are correct, False otherwise
    """
    for schema_name, correct_value in correct_answers.items():
        if schema_name not in user_answer:
            return False

        user_value = user_answer[schema_name]

        # Handle multiselect/checkbox (list comparison)
        if isinstance(correct_value, list):
            if isinstance(user_value, list):
                if set(user_value) != set(correct_value):
                    return False
            elif isinstance(user_value, str):
                # Single value submitted, check if it's the only correct answer
                if len(correct_value) != 1 or user_value not in correct_value:
                    return False
            else:
                return False
        # Handle numeric values
        elif isinstance(correct_value, (int, float)):
            try:
                if float(user_value) != float(correct_value):
                    return False
            except (ValueError, TypeError):
                return False
        # Handle string comparison (radio, text)
        else:
            if str(user_value).strip().lower() != str(correct_value).strip().lower():
                return False

    return True

@app.route("/prestudy", methods=["GET", "POST"])
def prestudy():
    """
    Handle the prestudy phase of the annotation process.

    Returns:
        flask.Response: Rendered template or redirect
    """
    if 'username' not in session:
        return home()

    username = session['username']
    user_state = get_user_state(username)

    # Check that the user is in the prestudy phase
    if user_state.get_phase() != UserPhase.PRESTUDY:
        logger.debug('NOT IN PRESTUDY PHASE')
        return home()

    # If the user is returning information from the page
    if request.method == 'POST':
        logger.debug(f'POST -> PRESTUDY: {request.form}')

        # Advance the state and redirect to the appropriate next phase
        usm = get_user_state_manager()
        usm.advance_phase(session['username'])
        request.method = 'GET'
        return home()

    # Show the current prestudy page
    else:
        # Get the page the user is currently on
        phase, page = user_state.get_current_phase_and_page()
        logger.debug(f'GET <-- PRESTUDY: phase, page: {phase}, {page}')

        # Look up the html template for the current page
        usm = get_user_state_manager()
        prestudy_html_fname = usm.get_phase_html_fname(phase, page)
        return render_template(prestudy_html_fname)

@app.route("/annotate", methods=["GET", "POST"])
def annotate():
    """
    Handle annotation page requests.
    """
    logger.debug("=== ANNOTATE ROUTE START ===")
    logger.debug(f"Session: {dict(session)}")
    logger.debug(f"Session username: {session.get('username', 'NOT_SET')}")
    logger.debug(f"Debug mode: {config.get('debug', False)}")
    logger.debug(f"Request method: {request.method}")
    logger.debug(f"Request headers: {dict(request.headers)}")
    logger.debug(f"Request content type: {request.content_type}")
    logger.debug(f"Request is JSON: {request.is_json}")

    # Check if user is logged in
    if 'username' not in session:
        logger.warning("Unauthorized access attempt to annotate page")
        return redirect(url_for("home"))

    username = session['username']
    logger.debug(f"Using username: {username}")
    logger.debug(f"All users in state manager: {get_user_state_manager().get_user_ids()}")

    # Ensure user state exists
    if not get_user_state_manager().has_user(username):
        logger.info(f"Creating missing user state for {username}")
        init_user_state(username)
        logger.debug(f"User state created. User exists: {get_user_state_manager().has_user(username)}")

    logger.debug("Handling annotation request")

    user_state = get_user_state(username)
    logger.debug(f"Retrieved state for user: {username}")
    logger.debug(f"User state: {user_state}")
    logger.debug(f"User state phase: {user_state.get_phase() if user_state else 'No user state'}")

    # Check user phase
    if not user_state or user_state.get_phase() != UserPhase.ANNOTATION:
        logger.info(f"User {username} not in annotation phase, redirecting. Phase: {user_state.get_phase() if user_state else 'No user state'}")
        return home()

    # If the user hasn't yet been assigned anything to annotate, do so now
    if not user_state.has_assignments():
        logger.debug(f"User {username} has no assignments, assigning instances")
        get_item_state_manager().assign_instances_to_user(user_state)
        logger.debug(f"User has assignments after assignment: {user_state.has_assignments()}")

    # See if this user has finished annotating all of their assigned instances
    if not user_state.has_remaining_assignments():
        logger.debug(f"User {username} has no remaining assignments, advancing phase")
        # If the user is done annotating, advance to the next phase
        get_user_state_manager().advance_phase(username)
        return home()

    # Handle POST requests
    if request.method == 'POST':
        logger.debug(f"POST request to annotate")
        if request.is_json:
            logger.debug(f"POST JSON data: {request.get_json()}")
        else:
            logger.debug(f"POST form data: {dict(request.form)}")

    if request.is_json and 'action' in request.json:
       logger.debug(f"Action from JSON: {request.json['action']}")
       action = request.json['action']
    else:
       logger.debug(f"Action from form: {request.form.get('action', 'init')}")
       action = request.form['action'] if 'action' in request.form else "init"

    logger.debug(f"Processing action: {action}")

    # NOTE: Annotations are saved in real-time via /updateinstance endpoint when users
    # click checkboxes, radio buttons, etc. This ensures proper timing tracking for
    # behavioral data. We do NOT save annotations during navigation - they should
    # already be saved by the time the user navigates.

    if action == "prev_instance":
        logger.debug(f"Moving to previous instance for user: {username}")
        move_to_prev_instance(username)
        acm = get_ai_cache_manager()
        if acm:
            acm.start_prefetch(user_state.current_instance_index,
                               getattr(acm, "prefetch_page_count_on_prev", 0) )
    elif action == "next_instance":
        logger.debug(f"Moving to next instance for user: {username}")
        move_to_next_instance(username)
        acm = get_ai_cache_manager()
        if acm:
            acm.start_prefetch(user_state.current_instance_index, getattr(acm,"prefetch_page_count_on_next", 0))

    elif action == "go_to":
        # Try to get go_to from JSON first, then form
        go_to_value = None
        if request.is_json and request.json.get("go_to") is not None:
            go_to_value = request.json.get("go_to")
        elif request.form.get("go_to") is not None:
            go_to_value = request.form.get("go_to")

        logger.debug(f"go_to action with value: {go_to_value}")
        if go_to_value is not None:
            go_to_id(username, go_to_value)
            acm = get_ai_cache_manager()
            if acm:
                acm.start_prefetch(user_state.current_instance_index, 1)
                acm.start_prefetch(user_state.current_instance_index, -1)

        else:
            logger.warning('go_to action requested but no go_to value provided')
    else:
        logger.debug(f'Action "{action}" - no specific handling')

    # After processing the action, check again if user has completed all assignments
    # This handles the case where the user just finished their last item
    if not user_state.has_remaining_assignments():
        logger.debug(f"User {username} has completed all assignments, advancing phase")
        get_user_state_manager().advance_phase(username)
        return home()

    # Handle GET requests with instance_id query parameter
    if request.method == 'GET' and request.args.get('instance_id'):
        instance_id = request.args.get('instance_id')
        logger.debug(f"GET request with instance_id parameter: {instance_id}")

        # Find the index of this instance in the user's assigned instances
        try:
            instance_index = user_state.instance_id_ordering.index(instance_id)
            logger.debug(f"Found instance {instance_id} at index {instance_index}")

            # Update the user's current instance to match the URL parameter
            if instance_index != user_state.current_instance_index:
                logger.debug(f"Updating user's current instance from index {user_state.current_instance_index} to {instance_index}")
                user_state.current_instance_index = instance_index
            else:
                logger.debug(f"User already on instance {instance_id} at index {instance_index}")
        except ValueError:
            logger.warning(f"Instance {instance_id} not found in user's assigned instances")
            # Don't change the current instance if the requested one isn't assigned to this user

    logger.debug("=== ANNOTATE ROUTE END ===")
    # Render the page with any existing annotations
    return render_page_with_annotations(username)

@app.route('/get_ai_suggestion', methods=['GET'])
def get_ai_suggestion():
    if 'username' not in session:
        return home()

    username = session['username']
    user_state = get_user_state(username)
    ais = get_ai_cache_manager()
    annotation_id = int(request.args.get('annotationId'))
    ai_assistant = request.args.get('aiAssistant')

    instance_id = user_state.get_current_instance_index()

    res = ais.get_ai_help(instance_id, annotation_id, ai_assistant)
    logger.debug(f"AI suggestion result: {res}")

    # Ensure proper JSON response with correct content-type
    if isinstance(res, dict):
        return jsonify(res)
    elif isinstance(res, str):
        # If it's an error message string, wrap it
        return jsonify({"error": res})
    else:
        return jsonify(res)


# Admin routes for system inspection (read-only)
@app.route("/admin/health", methods=["GET"])
def admin_health():
    """
    Health check endpoint for administrators.

    Returns:
        flask.Response: JSON response with server status
    """
    # Check API key
    api_key = request.headers.get('X-API-Key')
    if not validate_admin_api_key(api_key):
        return jsonify({
            "error": "Health check only available in debug mode or with valid API key"
        }), 403

    try:
        # Check if core managers are accessible
        usm = get_user_state_manager()
        ism = get_item_state_manager()

        return jsonify({
            "status": "healthy",
            "timestamp": str(datetime.datetime.now()),
            "managers": {
                "user_state_manager": "available",
                "item_state_manager": "available"
            },
            "config": {
                "debug_mode": config.get("debug", False),
                "annotation_task_name": config.get("annotation_task_name", "Unknown")
            }
        })
    except Exception as e:
        return jsonify({
            "status": "unhealthy",
            "error": str(e),
            "timestamp": str(datetime.datetime.now())
        }), 500


@app.route("/admin/system_state", methods=["GET"])
def admin_system_state():
    """
    Get overall system state including user and item statistics.
    Admin-only endpoint requiring API key.

    Returns:
        flask.Response: JSON response with system state
    """
    # Check API key
    api_key = request.headers.get('X-API-Key')
    if not validate_admin_api_key(api_key):
        return jsonify({
            "error": "System state only available in debug mode or with valid API key"
        }), 403

    try:
        usm = get_user_state_manager()
        ism = get_item_state_manager()

        # Get all users
        users = get_users()
        user_stats = {}
        total_annotations = 0

        for username in users:
            user_state = usm.get_user_state(username)
            if user_state:
                user_annotations = len(user_state.get_all_annotations())
                total_annotations += user_annotations
                user_stats[username] = {
                    "phase": str(user_state.get_phase()),
                    "annotations_count": user_annotations,
                    "has_assignments": user_state.has_assignments(),
                    "remaining_assignments": user_state.has_remaining_assignments()
                }

        # Get item statistics
        items = ism.items()
        item_stats = {
            "total_items": len(items),
            "items_with_annotations": 0,
            "items_by_annotator_count": {}
        }

        for item in items:
            item_id = item.get_id()
            annotators = ism.get_annotators_for_item(item_id)
            if annotators:
                item_stats["items_with_annotations"] += 1
                annotator_count = len(annotators)
                item_stats["items_by_annotator_count"][annotator_count] = item_stats["items_by_annotator_count"].get(annotator_count, 0) + 1

        return jsonify({
            "system_state": {
                "total_users": len(users),
                "total_items": item_stats["total_items"],
                "total_annotations": total_annotations,
                "items_with_annotations": item_stats["items_with_annotations"],
                "items_by_annotator_count": item_stats["items_by_annotator_count"]
            },
            "users": user_stats,
            "config": {
                "debug_mode": config.get("debug", False),
                "annotation_task_name": config.get("annotation_task_name", "Unknown"),
                "max_annotations_per_user": config.get("max_annotations_per_user", "Unlimited"),
                "annotation_schemes": config.get("annotation_schemes", []),
                "ui": config.get("ui", {})
            }
        })
    except Exception as e:
        return jsonify({
            "error": f"Failed to get system state: {str(e)}"
        }), 500


@app.route("/admin/all_instances", methods=["GET"])
def admin_all_instances():
    """
    Get all available instances for navigation purposes.
    Admin-only endpoint requiring API key.

    Returns:
        flask.Response: JSON response with all instances
    """
    # Check API key
    api_key = request.headers.get('X-API-Key')
    if not validate_admin_api_key(api_key):
        return jsonify({
            "error": "All instances only available in debug mode or with valid API key"
        }), 403

    try:
        ism = get_item_state_manager()
        items = ism.items()

        all_instances = []
        for item in items:
            all_instances.append({
                "id": item.get_id(),
                "text": item.get_text(),
                "displayed_text": item.get_displayed_text()
            })

        return jsonify({
            "total_items": len(all_instances),
            "items": all_instances
        })
    except Exception as e:
        return jsonify({
            "error": f"Failed to get all instances: {str(e)}"
        }), 500





@app.route("/admin/user_state/<user_id>", methods=["GET"])
def admin_user_state(user_id):
    """
    Get detailed state for a specific user.
    Admin-only endpoint requiring API key.

    Args:
        user_id: The user ID to get state for

    Returns:
        flask.Response: JSON response with user state
    """
    logger.debug("=== ADMIN USER STATE ROUTE START ===")
    logger.debug(f"Requested user_id: {user_id}")
    logger.debug(f"Request headers: {dict(request.headers)}")
    logger.debug(f"Debug mode: {config.get('debug', False)}")

    # Check API key
    api_key = request.headers.get('X-API-Key')
    if not validate_admin_api_key(api_key):
        logger.warning("Access denied to admin endpoint - invalid API key")
        return jsonify({
            "error": "User state only available in debug mode or with valid API key"
        }), 403
    try:
        logger.debug(f"Getting user state manager")
        usm = get_user_state_manager()
        logger.debug(f"All users in state manager: {usm.get_user_ids()}")
        logger.debug(f"Looking for user: {user_id}")
        logger.debug(f"User exists: {usm.has_user(user_id)}")

        user_state = usm.get_user_state(user_id)
        logger.debug(f"Retrieved user state: {user_state}")

        if not user_state:
            logger.warning(f"User '{user_id}' not found in state manager")
            return jsonify({
                "error": f"User '{user_id}' not found"
            }), 404

        # Get current instance
        current_instance = user_state.get_current_instance()
        current_instance_data = None
        if current_instance:
            # Get the base text
            base_text = current_instance.get_text()

            # Get span annotations for this instance and user
            span_annotations = get_span_annotations_for_user_on(user_id, current_instance.get_id())

            # Render the text with span annotations
            from potato.server_utils.schemas.span import render_span_annotations
            displayed_text = render_span_annotations(base_text, span_annotations)


            current_instance_data = {
                "id": current_instance.get_id(),
                "text": base_text,
                "displayed_text": displayed_text
            }

        # Helper to recursively convert all dict keys to strings
        def stringify_keys(obj):
            if isinstance(obj, dict):
                return {str(k): stringify_keys(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [stringify_keys(i) for i in obj]
            else:
                return obj

        # Get all annotations
        all_annotations = user_state.get_all_annotations()

        # Convert all keys to strings for JSON serialization
        serializable_annotations = {}
        for instance_id, annotations in all_annotations.items():
            instance_id_str = str(instance_id)
            serializable_annotations[instance_id_str] = {}

            # Process labels
            if "labels" in annotations:
                for label, value in annotations["labels"].items():
                    if hasattr(label, 'schema_name') and hasattr(label, 'label_name'):
                        label_str = f"{label.schema_name}:{label.label_name}"
                    else:
                        label_str = str(label)
                    serializable_annotations[instance_id_str][label_str] = value

            # Process spans
            if "spans" in annotations:
                for span, value in annotations["spans"].items():
                    span_str = str(span)
                    serializable_annotations[instance_id_str][span_str] = value

        serializable_annotations = stringify_keys(serializable_annotations)

        # Get assignments
        assignments = []
        if user_state.has_assignments():
            for instance_id in user_state.get_assigned_instance_ids():
                instance = get_item_state_manager().get_item(instance_id)
                if instance:
                    assignments.append({
                        "id": instance.get_id(),
                        "text": instance.get_text(),
                        "displayed_text": instance.get_displayed_text(),
                        "has_annotation": instance_id in all_annotations
                    })

        return jsonify({
            "user_id": user_id,
            "phase": str(user_state.get_phase()),
            "current_instance": current_instance_data,
            "max_assignments": user_state.get_max_assignments(),
            "assignments": {
                "total": len(assignments),
                "annotated": len([a for a in assignments if a["has_annotation"]]),
                "remaining": len([a for a in assignments if not a["has_annotation"]]),
                "items": assignments
            },
            "annotations": {
                "total_count": len(all_annotations),
                "by_instance": serializable_annotations
            },
            "hints": {
                "cached_hints": list(user_state.get_cached_hints().keys()) if hasattr(user_state, 'get_cached_hints') else []
            }
        })
    except Exception as e:
        return jsonify({
            "error": f"Failed to get user state for '{user_id}': {str(e)}"
        }), 500


@app.route("/admin/item_state", methods=["GET"])
def admin_item_state():
    """
    Get state for all items in the system.
    Admin-only endpoint requiring API key.

    Returns:
        flask.Response: JSON response with item state
    """
    # Check API key
    api_key = request.headers.get('X-API-Key')
    if not validate_admin_api_key(api_key):
        return jsonify({
            "error": "Item state only available in debug mode or with valid API key"
        }), 403

    try:
        ism = get_item_state_manager()
        items = ism.items()

        item_states = []
        for item in items:
            item_id = item.get_id()
            annotators = ism.get_annotators_for_item(item_id)

            item_states.append({
                "id": item_id,
                "text": item.get_text(),
                "displayed_text": item.get_displayed_text(),
                "annotators": list(annotators) if annotators else [],
                "annotation_count": len(annotators) if annotators else 0
            })

        # Sort by annotation count for easier analysis
        item_states.sort(key=lambda x: x["annotation_count"], reverse=True)

        return jsonify({
            "total_items": len(item_states),
            "items": item_states,
            "summary": {
                "items_with_annotations": len([i for i in item_states if i["annotation_count"] > 0]),
                "items_without_annotations": len([i for i in item_states if i["annotation_count"] == 0]),
                "average_annotations_per_item": sum(i["annotation_count"] for i in item_states) / len(item_states) if item_states else 0
            }
        })
    except Exception as e:
        return jsonify({
            "error": f"Failed to get item state: {str(e)}"
        }), 500


@app.route("/admin/item_state/<item_id>", methods=["GET"])
def admin_item_state_detail(item_id):
    """
    Get detailed state for a specific item.
    Admin-only endpoint requiring API key.

    Args:
        item_id: The item ID to get state for

    Returns:
        flask.Response: JSON response with item state
    """
    # Check API key
    api_key = request.headers.get('X-API-Key')
    if not validate_admin_api_key(api_key):
        return jsonify({
            "error": "Item state detail only available in debug mode or with valid API key"
        }), 403
    try:
        ism = get_item_state_manager()
        item = ism.get_item(item_id)

        if not item:
            return jsonify({
                "error": f"Item '{item_id}' not found"
            }), 404

        annotators = ism.get_annotators_for_item(item_id)

        # Get annotations from all users for this item
        usm = get_user_state_manager()
        item_annotations = {}

        for username in get_users():
            user_state = usm.get_user_state(username)
            if user_state:
                user_annotations = user_state.get_all_annotations()
                if item_id in user_annotations:
                    item_annotations[username] = user_annotations[item_id]

        return jsonify({
            "item_id": item_id,
            "text": item.get_text(),
            "displayed_text": item.get_displayed_text(),
            "annotators": list(annotators) if annotators else [],
            "annotation_count": len(annotators) if annotators else 0,
            "annotations": item_annotations
        })
    except Exception as e:
        return jsonify({
            "error": f"Failed to get item state for '{item_id}': {str(e)}"
        }), 500


# Test Support Endpoints (only available in debug mode)

@app.route("/admin/api/test/reset_state", methods=["POST"])
def admin_api_test_reset_state():
    """
    Reset server state for testing purposes.
    Only available in debug mode.

    This endpoint clears user state and reloads data, allowing tests
    to start with a fresh state without restarting the server.

    Returns:
        flask.Response: JSON response with reset status
    """
    if not config.get('debug', False):
        return jsonify({'error': 'This endpoint is only available in debug mode'}), 403

    try:
        from potato.user_state_management import clear_user_state_manager, init_user_state_manager
        from potato.item_state_management import clear_item_state_manager, init_item_state_manager
        from potato.flask_server import load_all_data
        from potato.authentication import UserAuthenticator

        # Clear existing state
        clear_user_state_manager()
        clear_item_state_manager()

        # Clear ICL labeler if it exists
        try:
            from potato.ai.icl_labeler import clear_icl_labeler
            clear_icl_labeler()
        except ImportError:
            pass

        # Reinitialize state
        UserAuthenticator.init_from_config(config)
        init_user_state_manager(config)
        init_item_state_manager(config)
        load_all_data(config)

        logger.info("Server state reset successfully for testing")
        return jsonify({
            'status': 'success',
            'message': 'Server state reset successfully'
        })

    except Exception as e:
        logger.error(f"Failed to reset server state: {e}")
        return jsonify({
            'status': 'error',
            'message': f'Failed to reset state: {str(e)}'
        }), 500


# New Admin Dashboard API Endpoints

@app.route("/admin/api/overview", methods=["GET"])
def admin_api_overview():
    """
    Get dashboard overview data.
    Admin-only endpoint requiring API key.

    Returns:
        flask.Response: JSON response with overview statistics
    """
    result = admin_dashboard.get_dashboard_overview()
    if isinstance(result, tuple):
        return jsonify(result[0]), result[1]
    return jsonify(result)


@app.route("/admin/api/annotators", methods=["GET"])
def admin_api_annotators():
    """
    Get detailed annotator data including timing information.
    Admin-only endpoint requiring API key.

    Returns:
        flask.Response: JSON response with annotator data
    """
    result = admin_dashboard.get_annotators_data()
    if isinstance(result, tuple):
        return jsonify(result[0]), result[1]
    return jsonify(result)


@app.route("/admin/api/instances", methods=["GET"])
def admin_api_instances():
    """
    Get paginated instances data with sorting and filtering.
    Admin-only endpoint requiring API key.

    Query Parameters:
        page: Page number (default: 1)
        page_size: Items per page (default: 25)
        sort_by: Sort field (annotation_count, completion_percentage, disagreement, id, average_time)
        sort_order: Sort order (asc, desc)
        filter_completion: Filter by completion (completed, incomplete, all)

    Returns:
        flask.Response: JSON response with paginated instances data
    """
    # Get query parameters
    page = int(request.args.get('page', 1))
    page_size = int(request.args.get('page_size', 25))
    sort_by = request.args.get('sort_by', 'annotation_count')
    sort_order = request.args.get('sort_order', 'desc')
    filter_completion = request.args.get('filter_completion')

    result = admin_dashboard.get_instances_data(
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order,
        filter_completion=filter_completion
    )
    if isinstance(result, tuple):
        return jsonify(result[0]), result[1]
    return jsonify(result)


@app.route("/admin/api/config", methods=["GET", "POST"])
def admin_api_config():
    """
    Get or update system configuration.
    Admin-only endpoint requiring API key.

    GET: Returns current configuration
    POST: Updates configuration with provided data

    Returns:
        flask.Response: JSON response with configuration data or update result
    """
    if request.method == "GET":
        # Return current configuration
        response_data = {
            "max_annotations_per_user": config.get("max_annotations_per_user", -1),
            "max_annotations_per_item": config.get("max_annotations_per_item", -1),
            "assignment_strategy": config.get("assignment_strategy", "fixed_order"),
            "annotation_task_name": config.get("annotation_task_name", "Unknown"),
            "debug_mode": config.get("debug", False)
        }

        # Add training configuration if present
        if "training" in config:
            response_data["training"] = config["training"]

        return jsonify(response_data)

    elif request.method == "POST":
        # Update configuration
        config_updates = request.get_json()
        if not config_updates:
            return jsonify({"error": "No configuration updates provided"}), 400

        result = admin_dashboard.update_config(config_updates)
        if isinstance(result, tuple):
            return jsonify(result[0]), result[1]
        return jsonify(result)


@app.route("/admin/api/questions", methods=["GET"])
def admin_api_questions():
    """
    Get aggregate analysis data for all annotation schemas/questions.
    Admin-only endpoint requiring API key.

    Returns:
        flask.Response: JSON response with questions data and visualizations
    """
    result = admin_dashboard.get_questions_data()
    if isinstance(result, tuple):
        return jsonify(result[0]), result[1]
    return jsonify(result)


@app.route("/admin/api/annotation_history", methods=["GET"])
def admin_api_annotation_history():
    """
    Get detailed annotation history data with filtering options.
    Admin-only endpoint requiring API key.

    Query Parameters:
        user_id: Optional user ID to filter by
        instance_id: Optional instance ID to filter by
        minutes: Optional time window in minutes

    Returns:
        flask.Response: JSON response with annotation history data
    """
    user_id = request.args.get('user_id')
    instance_id = request.args.get('instance_id')
    minutes = request.args.get('minutes')

    if minutes:
        try:
            minutes = int(minutes)
        except ValueError:
            return jsonify({"error": "Invalid minutes parameter"}), 400

    result = admin_dashboard.get_annotation_history_data(
        user_id=user_id,
        instance_id=instance_id,
        minutes=minutes
    )
    if isinstance(result, tuple):
        return jsonify(result[0]), result[1]
    return jsonify(result)


@app.route("/admin/api/suspicious_activity", methods=["GET"])
def admin_api_suspicious_activity():
    """
    Get comprehensive suspicious activity analysis.
    Admin-only endpoint requiring API key.

    Returns:
        flask.Response: JSON response with suspicious activity data
    """
    result = admin_dashboard.get_suspicious_activity_data()
    if isinstance(result, tuple):
        return jsonify(result[0]), result[1]
    return jsonify(result)


@app.route("/admin/api/crowdsourcing", methods=["GET"])
def admin_api_crowdsourcing():
    """
    Get crowdsourcing platform statistics (MTurk, Prolific).
    Admin-only endpoint requiring API key.

    Returns:
        flask.Response: JSON response with crowdsourcing data including:
        - summary: Overall worker counts by platform
        - prolific: Prolific-specific statistics and worker list
        - mturk: MTurk-specific statistics and worker list
        - other: Non-crowdsourcing workers
    """
    result = admin_dashboard.get_crowdsourcing_data()
    if isinstance(result, tuple):
        return jsonify(result[0]), result[1]
    return jsonify(result)


@app.route("/admin/api/agreement", methods=["GET"])
def admin_api_agreement():
    """
    Get inter-annotator agreement metrics.
    Admin-only endpoint requiring API key.

    Returns:
        flask.Response: JSON response with agreement metrics including:
        - overall: Average Krippendorff's alpha across schemas
        - by_schema: Per-schema agreement metrics
        - interpretation: Human-readable interpretation
    """
    result = admin_dashboard.get_agreement_metrics()
    if isinstance(result, tuple):
        return jsonify(result[0]), result[1]
    return jsonify(result)


@app.route("/admin/api/quality_control", methods=["GET"])
def admin_api_quality_control():
    """
    Get quality control metrics (attention checks, gold standards).
    Admin-only endpoint requiring API key.

    Returns:
        flask.Response: JSON response with quality control data including:
        - attention_checks: Statistics on attention check pass/fail rates
        - gold_standards: Statistics on gold standard accuracy
        - by_user: Per-user quality metrics
    """
    result = admin_dashboard.get_quality_control_data()
    if isinstance(result, tuple):
        return jsonify(result[0]), result[1]
    return jsonify(result)


@app.route("/admin/api/behavioral_analytics", methods=["GET"])
def admin_api_behavioral_analytics():
    """
    Get behavioral analytics data for all annotators.
    Admin-only endpoint requiring API key.

    Returns:
        flask.Response: JSON response with behavioral analytics including:
        - aggregate_stats: Overall statistics (total users, instances, avg time)
        - ai_usage: AI assistance usage statistics
        - quality_summary: Quality indicators and suspicious activity flags
        - interaction_types: Breakdown of interaction types
        - change_sources: Sources of annotation changes
        - users: Per-user behavioral metrics sorted by suspicion score
    """
    result = admin_dashboard.get_behavioral_analytics_data()
    if isinstance(result, tuple):
        return jsonify(result[0]), result[1]
    return jsonify(result)


# === ICL Verification Helper ===

def _maybe_record_icl_verification(user_state, instance_id: str, annotations: dict) -> bool:
    """
    Check if an annotation was for an ICL verification task and record the result.

    This is called after a user submits an annotation. If the instance was assigned
    as a verification task (blind labeling), we compare their label to the LLM's
    prediction and record the verification result.

    Args:
        user_state: The user's state object
        instance_id: The annotated instance ID
        annotations: The user's annotation data

    Returns:
        True if verification was recorded, False otherwise
    """
    # Check if this instance is a verification task
    if not hasattr(user_state, 'is_verification_task'):
        return False

    if not user_state.is_verification_task(instance_id):
        return False

    try:
        from potato.ai.icl_labeler import get_icl_labeler

        icl_labeler = get_icl_labeler()
        if icl_labeler is None:
            return False

        # Get the schema being verified
        schema_name = user_state.get_verification_schema(instance_id)
        if not schema_name:
            return False

        # Extract the human's label for this schema
        human_label = None
        if schema_name in annotations:
            label_data = annotations[schema_name]
            if isinstance(label_data, dict):
                # For radio/multiselect, find the selected value
                for label_name, value in label_data.items():
                    if value == 'true' or value is True:
                        human_label = label_name
                        break
                    elif isinstance(value, str) and value not in ('false', ''):
                        human_label = value
                        break
            elif isinstance(label_data, str):
                human_label = label_data

        if human_label is None:
            logger.warning(f"Could not extract human label for verification of {instance_id}")
            return False

        # Record the verification
        user_id = user_state.get_user_id()
        success = icl_labeler.record_verification(
            instance_id=instance_id,
            schema_name=schema_name,
            human_label=human_label,
            verified_by=user_id
        )

        if success:
            # Remove from user's verification task tracking
            user_state.complete_verification_task(instance_id)
            logger.info(f"Recorded ICL verification for {instance_id} by {user_id}: {human_label}")

        return success

    except ImportError:
        # ICL labeler module not available
        return False
    except Exception as e:
        logger.warning(f"Error recording ICL verification: {e}")
        return False


# === ICL Labeling Admin API ===

@app.route("/admin/api/icl/status", methods=["GET"])
def admin_api_icl_status():
    """
    Get ICL labeler status and statistics.
    Admin-only endpoint.

    Returns:
        JSON with ICL labeler status including:
        - enabled: Whether ICL labeling is enabled
        - total_examples: Number of high-confidence examples
        - total_predictions: Number of LLM predictions made
        - accuracy_metrics: Verification-based accuracy
        - labeling_paused: Whether labeling is currently paused
    """
    try:
        from potato.ai.icl_labeler import get_icl_labeler
        icl_labeler = get_icl_labeler()

        if icl_labeler is None:
            return jsonify({
                'enabled': False,
                'message': 'ICL labeling not initialized'
            })

        return jsonify(icl_labeler.get_status())

    except Exception as e:
        logger.error(f"Error getting ICL status: {e}")
        return jsonify({'error': str(e)}), 500


@app.route("/admin/api/icl/examples", methods=["GET"])
def admin_api_icl_examples():
    """
    Get current high-confidence examples.

    Query params:
        schema: Optional schema name to filter by

    Returns:
        JSON with examples grouped by schema
    """
    try:
        from potato.ai.icl_labeler import get_icl_labeler
        icl_labeler = get_icl_labeler()

        if icl_labeler is None:
            # Return empty results when ICL is not initialized (graceful degradation)
            schema_filter = request.args.get('schema')
            return jsonify({
                'examples': {},
                'total_count': 0,
                'schema': schema_filter
            })

        schema_filter = request.args.get('schema')

        examples = {}
        for schema_name, schema_examples in icl_labeler.schema_to_examples.items():
            if schema_filter and schema_name != schema_filter:
                continue
            examples[schema_name] = [ex.to_dict() for ex in schema_examples]

        response_data = {
            'examples': examples,
            'total_count': sum(len(ex) for ex in examples.values())
        }
        if schema_filter:
            response_data['schema'] = schema_filter
        return jsonify(response_data)

    except Exception as e:
        logger.error(f"Error getting ICL examples: {e}")
        return jsonify({'error': str(e)}), 500


@app.route("/admin/api/icl/predictions", methods=["GET"])
def admin_api_icl_predictions():
    """
    Get LLM predictions with filtering.

    Query params:
        schema: Optional schema name to filter by
        status: Optional verification status filter
        limit: Maximum number of predictions to return (default 100)

    Returns:
        JSON with predictions list
    """
    try:
        from potato.ai.icl_labeler import get_icl_labeler
        icl_labeler = get_icl_labeler()

        if icl_labeler is None:
            # Return empty results when ICL is not initialized (graceful degradation)
            return jsonify({
                'predictions': [],
                'total_count': 0
            })

        schema_filter = request.args.get('schema')
        status_filter = request.args.get('status')
        limit = int(request.args.get('limit', 100))

        predictions_list = []
        for inst_id, schemas in icl_labeler.predictions.items():
            for schema_name, prediction in schemas.items():
                if schema_filter and schema_name != schema_filter:
                    continue
                if status_filter and prediction.verification_status != status_filter:
                    continue

                predictions_list.append(prediction.to_dict())

                if len(predictions_list) >= limit:
                    break
            if len(predictions_list) >= limit:
                break

        # Sort by timestamp descending
        predictions_list.sort(key=lambda x: x['timestamp'], reverse=True)

        return jsonify({
            'predictions': predictions_list[:limit],
            'total_count': len(predictions_list)
        })

    except Exception as e:
        logger.error(f"Error getting ICL predictions: {e}")
        return jsonify({'error': str(e)}), 500


@app.route("/admin/api/icl/accuracy", methods=["GET"])
def admin_api_icl_accuracy():
    """
    Get accuracy metrics.

    Query params:
        schema: Optional schema name to filter by

    Returns:
        JSON with accuracy metrics
    """
    try:
        from potato.ai.icl_labeler import get_icl_labeler
        icl_labeler = get_icl_labeler()

        if icl_labeler is None:
            # Return empty metrics when ICL is not initialized (graceful degradation)
            schema_filter = request.args.get('schema')
            return jsonify({
                'total_predictions': 0,
                'total_verified': 0,
                'verified_correct': 0,
                'verified_incorrect': 0,
                'pending_verification': 0,
                'accuracy': 0.0,
                'schema_name': schema_filter
            })

        schema_filter = request.args.get('schema')
        metrics = icl_labeler.get_accuracy_metrics(schema_filter)

        return jsonify(metrics)

    except Exception as e:
        logger.error(f"Error getting ICL accuracy: {e}")
        return jsonify({'error': str(e)}), 500


@app.route("/admin/api/icl/trigger", methods=["POST"])
def admin_api_icl_trigger():
    """
    Manually trigger ICL operations.

    JSON body:
        action: "refresh_examples" | "batch_label" | "save_state"
        schema: Optional schema name for batch_label

    Returns:
        JSON with operation result
    """
    try:
        from potato.ai.icl_labeler import get_icl_labeler
        icl_labeler = get_icl_labeler()

        if icl_labeler is None:
            return jsonify({'error': 'ICL labeling not initialized'}), 400

        data = request.get_json() or {}
        action = data.get('action', '')

        # Support shorthand: if schema_name is provided without action, default to batch_label
        if not action and data.get('schema_name'):
            action = 'batch_label'
            # Use schema_name as the schema for backwards compatibility
            if 'schema' not in data:
                data['schema'] = data['schema_name']

        if action == 'refresh_examples':
            examples = icl_labeler.refresh_high_confidence_examples()
            return jsonify({
                'action': 'refresh_examples',
                'success': True,
                'example_counts': {k: len(v) for k, v in examples.items()}
            })

        elif action == 'batch_label':
            schema = data.get('schema')
            if not schema:
                return jsonify({'error': 'schema required for batch_label'}), 400

            predictions = icl_labeler.batch_label_instances(schema)
            icl_labeler.save_state()

            return jsonify({
                'action': 'batch_label',
                'success': True,
                'predictions_count': len(predictions),
                'schema': schema,
                'message': f'Labeled {len(predictions)} instances for schema {schema}'
            })

        elif action == 'save_state':
            icl_labeler.save_state()
            return jsonify({
                'action': 'save_state',
                'success': True
            })

        else:
            return jsonify({'error': f'Unknown action: {action}'}), 400

    except Exception as e:
        logger.error(f"Error triggering ICL action: {e}")
        return jsonify({'error': str(e)}), 500


@app.route("/api/icl/record_verification", methods=["POST"])
def api_icl_record_verification():
    """
    Record human verification of an LLM prediction.

    This is called when an annotator completes labeling an instance
    that was selected for verification.

    JSON body:
        instance_id: The instance ID
        schema_name: The schema name
        human_label: The human's label

    Returns:
        JSON with verification result
    """
    try:
        if 'username' not in session:
            return jsonify({'error': 'Not authenticated'}), 401

        from potato.ai.icl_labeler import get_icl_labeler
        icl_labeler = get_icl_labeler()

        if icl_labeler is None:
            return jsonify({'error': 'ICL labeling not initialized'}), 400

        data = request.get_json() or {}
        instance_id = data.get('instance_id')
        schema_name = data.get('schema_name')
        human_label = data.get('human_label')

        if not all([instance_id, schema_name, human_label]):
            return jsonify({'error': 'Missing required fields'}), 400

        username = session['username']
        success = icl_labeler.record_verification(
            instance_id, schema_name, human_label, username
        )

        if success:
            icl_labeler.save_state()
            return jsonify({'success': True, 'message': 'Verification recorded'})
        else:
            return jsonify({'success': False, 'message': 'No prediction found to verify'})

    except Exception as e:
        logger.error(f"Error recording verification: {e}")
        return jsonify({'error': str(e)}), 500


@app.route("/go_to", methods=["GET", "POST"])
def go_to():
    """
    Handle requests to go to a specific instance.
    """
    if 'username' not in session:
        return home()

    username = session['username']
    user_state = get_user_state(username)

    # Check that the user is in the annotation phase
    if user_state.get_phase() != UserPhase.ANNOTATION:
        # If not in the annotation phase, redirect
        return home()

    if request.method == 'POST':
        logger.debug(f'POST -> GO_TO: {request.form}')
        go_to_id(username, request.form.get("go_to"))

    return render_page_with_annotations(username)

@app.route('/get_annotations', methods=['GET'])
def get_annotations():
    """Get annotations for the current user and instance."""
    try:
        # Get user from session
        if 'username' not in session:
            return jsonify({"error": "No user session"}), 401

        username = session['username']

        # Get instance ID from query parameters
        instance_id = request.args.get('instance_id')
        if not instance_id:
            return jsonify({"error": "No instance_id provided"}), 400

        # Get user state
        user_state = get_user_state_manager().get_user_state(username)
        if not user_state:
            return jsonify({"error": "User not found"}), 404

        # Get annotations for the instance
        label_annotations = user_state.get_label_annotations(instance_id)
        span_annotations = user_state.get_span_annotations(instance_id)

        # Convert span annotations to serializable format
        serializable_span_annotations = {}
        for span, value in span_annotations.items():
            serializable_span_annotations[str(span)] = value

        # Combine annotations
        annotations = {
            "label_annotations": label_annotations,
            "span_annotations": serializable_span_annotations
        }

        return jsonify(annotations)

    except Exception as e:
        logger.error(f"Error getting annotations: {e}")
        return jsonify({"error": "Internal server error"}), 500

@app.route("/api/current_instance", methods=["GET"])
def get_current_instance():
    """Get the current instance information for the current user."""
    logger.debug(f"=== GET_CURRENT_INSTANCE START ===")

    if 'username' not in session:
        logger.warning("Get current instance without active session")
        return jsonify({"error": "No active session"}), 401

    username = session['username']
    logger.debug(f"Username: {username}")

    try:
        user_state = get_user_state(username)
        if not user_state:
            logger.error(f"User state not found for user: {username}")
            return jsonify({"error": "User state not found"}), 404

        current_instance = user_state.get_current_instance()
        if not current_instance:
            logger.error(f"No current instance for user: {username}")
            return jsonify({"error": "No current instance"}), 404

        instance_id = current_instance.get_id()
        logger.debug(f"Current instance ID: {instance_id}")

        return jsonify({
            "instance_id": instance_id,
            "current_index": user_state.get_current_instance_index(),
            "total_instances": len(user_state.instance_id_ordering)
        })

    except Exception as e:
        logger.error(f"Error getting current instance: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/spans/<instance_id>")
def get_span_data(instance_id):
    """
    Get span annotations as structured data for frontend rendering.

    Returns:
        JSON with instance text and span annotations in a format
        suitable for frontend DOM manipulation.
    """
    logger.debug(f"=== GET_SPAN_DATA START ===")
    logger.debug(f"Instance ID: {instance_id}")

    # Add debugging for URL decoding
    import urllib.parse
    decoded_instance_id = urllib.parse.unquote(instance_id)
    logger.debug(f"Decoded Instance ID: {decoded_instance_id}")
    logger.debug(f"Instance ID length: {len(instance_id)}")
    logger.debug(f"Decoded Instance ID length: {len(decoded_instance_id)}")

    if 'username' not in session:
        logger.warning("Get span data without active session")
        return jsonify({"error": "No active session"}), 401

    username = session['username']
    logger.debug(f"Username: {username}")

    # Get the original text for this instance
    try:
        # Get the text from the item state manager
        item_state_manager = get_item_state_manager()

        # Try with original instance_id first
        instance = item_state_manager.get_item(instance_id)
        if not instance:
            logger.debug(f"Instance not found with original ID, trying decoded ID")
            # Try with decoded instance_id
            instance = item_state_manager.get_item(decoded_instance_id)
            if instance:
                logger.debug(f"Instance found with decoded ID")
                instance_id = decoded_instance_id  # Use decoded ID for rest of function
            else:
                logger.error(f"Instance not found with either original or decoded ID")
                # Debug: list all available instance IDs
                all_instance_ids = list(item_state_manager.instance_id_to_instance.keys())
                logger.debug(f"Available instance IDs: {all_instance_ids[:5]}...")  # Show first 5
                logger.debug(f"Total available instances: {len(all_instance_ids)}")
                return jsonify({"error": "Instance not found"}), 404
        else:
            logger.debug(f"Instance found with original ID")

        # Use configured text_key to get the right field, not generic get_text()
        text_key = config.get("item_properties", {}).get("text_key", "text")
        item_data = instance.get_data()
        original_text = item_data.get(text_key, instance.get_text()) if isinstance(item_data, dict) else instance.get_text()
        logger.debug(f"Original text (raw, text_key={text_key}): {str(original_text)[:100]}...")

        # IMPORTANT: Normalize text the same way as flask_server.py template rendering
        # This ensures span offsets calculated on normalized text match the API response
        # 1. Strip HTML tags
        import re as re_module
        original_text = str(original_text)
        normalized_text = re_module.sub(r'<[^>]+>', '', original_text)
        # 2. Normalize whitespace (multiple spaces/newlines -> single space)
        normalized_text = re_module.sub(r'\s+', ' ', normalized_text).strip()
        logger.debug(f"Normalized text: {normalized_text[:100]}...")
    except Exception as e:
        logger.error(f"Error getting instance text: {e}")
        return jsonify({"error": f"Instance not found: {instance_id}"}), 404

    # Get span annotations (returns a list of SpanAnnotation objects)
    spans = get_span_annotations_for_user_on(username, instance_id)
    logger.debug(f"Found {len(spans)} spans")

    # Convert to frontend-friendly format
    span_data = []
    for span in spans:
        # span is a SpanAnnotation object
        span_schema = span.get_schema() if hasattr(span, 'get_schema') else span.schema
        span_name = span.get_name() if hasattr(span, 'get_name') else span.name
        span_title = span.get_title() if hasattr(span, 'get_title') else getattr(span, 'title', span_name)
        span_start = span.get_start() if hasattr(span, 'get_start') else span.start
        span_end = span.get_end() if hasattr(span, 'get_end') else span.end
        span_id = span.get_id() if hasattr(span, 'get_id') else getattr(span, 'id', None)

        color = get_span_color(span_schema, span_name)
        hex_color = None
        if color:
            if isinstance(color, str) and color.startswith("(") and color.endswith(")"):
                try:
                    rgb_parts = color.strip("()").split(", ")
                    if len(rgb_parts) == 3:
                        r, g, b = int(rgb_parts[0]), int(rgb_parts[1]), int(rgb_parts[2])
                        hex_color = f"#{r:02x}{g:02x}{b:02x}"
                except (ValueError, IndexError):
                    hex_color = "#f0f0f0"
            else:
                hex_color = color

        span_target_field = span.get_target_field() if hasattr(span, 'get_target_field') else getattr(span, 'target_field', None)

        # Use the correct field text for extracting span text
        # In multi-field mode, each span's offsets are relative to its target field's text
        span_source_text = normalized_text  # default: text_key field
        if span_target_field and isinstance(item_data, dict) and span_target_field in item_data:
            field_text = str(item_data[span_target_field])
            field_text = re_module.sub(r'<[^>]+>', '', field_text)
            span_source_text = re_module.sub(r'\s+', ' ', field_text).strip()

        span_entry = {
            'id': span_id,
            'schema': span_schema,
            'label': span_name,
            'title': span_title,
            'start': span_start,
            'end': span_end,
            'text': span_source_text[span_start:span_end] if span_start < len(span_source_text) and span_end <= len(span_source_text) else "",
            'color': hex_color
        }
        if span_target_field:
            span_entry['target_field'] = span_target_field
        span_data.append(span_entry)

    response_data = {
        'instance_id': instance_id,
        'text': normalized_text,  # Use normalized text matching template rendering
        'spans': span_data
    }

    logger.debug(f"=== GET_SPAN_DATA END ===", response_data)
    return jsonify(response_data)


@app.route("/updateinstance", methods=["POST"])
def update_instance():
    """
    PRIMARY ANNOTATION ENDPOINT: Handle all annotation updates for instances.
    This endpoint only updates backend state for spans and labels. It does not generate or return any HTML.

    Supports two formats:
    1. Frontend format: {"instance_id": "...", "annotations": {...}, "span_annotations": [...]}
    2. Backend format: {"instance_id": "...", "schema": "...", "state": [...], "type": "..."}
    """
    import time
    import datetime
    from potato.annotation_history import AnnotationHistoryManager

    start_time = time.time()

    logger.debug("=== UPDATEINSTANCE ROUTE START ===")
    logger.debug(f"Session: {dict(session)}")
    logger.debug(f"Session username: {session.get('username', 'NOT_SET')}")
    logger.debug(f"Request content type: {request.content_type}")
    logger.debug(f"Request is JSON: {request.is_json}")
    logger.debug(f"Debug mode: {config.get('debug', False)}")

    if 'username' not in session:
        logger.warning("Update instance without active session")
        return jsonify({"status": "error", "message": "No active session"})

    if request.is_json:
        logger.debug(f"Received JSON data: {request.json}")
        instance_id = str(request.json.get("instance_id"))  # Normalize to string
        username = session['username']
        user_state = get_user_state(username)
        if not user_state:
            logger.error(f"User state not found for user: {username}")
            return jsonify({"status": "error", "message": "User state not found"})

        # Debug: Log user phase for debugging annotation storage issues
        logger.debug(f"User '{username}' phase: {user_state.get_phase()}, current_phase_and_page: {user_state.current_phase_and_page}")

        # Track session
        if not user_state.session_start_time:
            user_state.start_session(session.get('session_id', str(uuid.uuid4())))

        # Get client timestamp if provided
        client_timestamp = None
        if request.json.get("client_timestamp"):
            try:
                client_timestamp = datetime.datetime.fromisoformat(request.json["client_timestamp"])
            except ValueError:
                logger.warning(f"Invalid client timestamp format: {request.json['client_timestamp']}")

        # Prepare metadata
        metadata = {
            "request_id": request.json.get("request_id"),
            "user_agent": request.headers.get("User-Agent"),
            "ip_address": request.remote_addr,
            "content_type": request.content_type,
            "request_size": len(request.get_data()) if request.get_data() else 0
        }

        # Check if this is the frontend format (annotations, span_annotations)
        if "annotations" in request.json:
            logger.debug("Processing frontend format (annotations, span_annotations)")

            # Handle label annotations from frontend format
            annotations = request.json.get("annotations", {})
            for key, value in annotations.items():
                if ":::" in key:
                    # Use ::: separator for image/audio/video annotation data
                    # e.g., "video_segments:::_data" -> schema="video_segments", label="_data"
                    schema_name, label_name = key.split(":::", 1)
                    label = Label(schema_name, label_name)
                elif ":" in key:
                    # Legacy format with single colon
                    schema_name, label_name = key.split(":", 1)
                    label = Label(schema_name, label_name)
                else:
                    logger.warning(f"Skipping annotation with no separator: {key}")
                    continue

                # Get old value for comparison
                old_value = None
                if instance_id in user_state.instance_id_to_label_to_value:
                    old_value = user_state.instance_id_to_label_to_value[instance_id].get(label)

                # Determine action type
                action_type = "add_label" if old_value is None else "update_label"

                # Create annotation action
                action = AnnotationHistoryManager.create_action(
                    user_id=username,
                    instance_id=instance_id,
                    action_type=action_type,
                    schema_name=schema_name,
                    label_name=label_name,
                    old_value=old_value,
                    new_value=value,
                    session_id=user_state.current_session_id,
                    client_timestamp=client_timestamp,
                    metadata=metadata
                )

                # Add to history
                user_state.add_annotation_action(action)

                # Update annotation
                user_state.add_label_annotation(instance_id, label, value)
                logger.debug(f"Added label annotation: {schema_name}:{label_name} = {value[:100]}..." if len(str(value)) > 100 else f"Added label annotation: {schema_name}:{label_name} = {value}")

            # Handle span annotations from frontend format
            span_annotations = request.json.get("span_annotations", [])
            for span_data in span_annotations:
                if isinstance(span_data, dict) and "schema" in span_data:
                    span = SpanAnnotation(
                        span_data["schema"],
                        span_data["name"],
                        span_data.get("title", span_data["name"]),
                        int(span_data["start"]),
                        int(span_data["end"]),
                        target_field=span_data.get("target_field")
                    )
                    value = span_data.get("value")

                    if value is not None:
                        # Get old value for comparison
                        old_value = None
                        if instance_id in user_state.instance_id_to_span_to_value:
                            old_value = user_state.instance_id_to_span_to_value[instance_id].get(span)

                        # Determine action type
                        action_type = "add_span" if old_value is None else "update_span"

                        # Create annotation action
                        action = AnnotationHistoryManager.create_action(
                            user_id=username,
                            instance_id=instance_id,
                            action_type=action_type,
                            schema_name=span_data["schema"],
                            label_name=span_data["name"],
                            old_value=old_value,
                            new_value=value,
                            span_data={
                                "start": span_data["start"],
                                "end": span_data["end"],
                                "title": span_data.get("title", span_data["name"])
                            },
                            session_id=user_state.current_session_id,
                            client_timestamp=client_timestamp,
                            metadata=metadata
                        )

                        # Add to history
                        user_state.add_annotation_action(action)

                        # Update annotation
                        user_state.add_span_annotation(instance_id, span, value)
                        logger.debug(f"Added span annotation: {span_data}")

            # Handle link annotations from frontend format
            link_annotations = request.json.get("link_annotations", [])
            for link_data in link_annotations:
                if isinstance(link_data, dict) and "schema" in link_data and "link_type" in link_data:
                    from potato.item_state_management import SpanLink
                    link = SpanLink(
                        schema=link_data["schema"],
                        link_type=link_data["link_type"],
                        span_ids=link_data.get("span_ids", []),
                        direction=link_data.get("direction", "undirected"),
                        id=link_data.get("id"),
                        properties=link_data.get("properties", {})
                    )

                    # Add or update the link annotation
                    user_state.add_link_annotation(instance_id, link)
                    logger.debug(f"Added link annotation: {link}")

        # Check if this is the backend format (schema, state, type)
        elif "schema" in request.json and "state" in request.json and "type" in request.json:
            logger.debug("Processing backend format (schema, state, type)")

            schema_name = request.json.get("schema")
            schema_state = request.json.get("state")
            annotation_type = request.json.get("type")

            if annotation_type == "span":
                logger.debug(f"Processing span annotation state: {schema_state}")
                for sv in schema_state:
                    # Validate and correct negative offsets
                    start_offset = int(sv["start"])
                    end_offset = int(sv["end"])

                    # Correct negative offsets to 0
                    if start_offset < 0:
                        start_offset = 0
                        logger.warning(f"Corrected negative start offset {sv['start']} to 0")
                    if end_offset < 0:
                        end_offset = 0
                        logger.warning(f"Corrected negative end offset {sv['end']} to 0")

                    # Ensure end is not less than start
                    if end_offset < start_offset:
                        end_offset = start_offset
                        logger.warning(f"Corrected end offset {sv['end']} to match start offset {start_offset}")

                    # Get span_id or generate one if not provided
                    span_id = sv.get("span_id") or sv.get("id") or f"{schema_name}_{sv['name']}_{start_offset}_{end_offset}"
                    span = SpanAnnotation(schema_name, sv["name"], sv.get("title", sv["name"]), start_offset, end_offset, span_id, target_field=sv.get("target_field"))
                    
                    value = sv.get("value")

                    # Get old value for comparison
                    old_value = None
                    if instance_id in user_state.instance_id_to_span_to_value:
                        old_value = user_state.instance_id_to_span_to_value[instance_id].get(span)

                    # Determine action type
                    if value is None:
                        action_type = "delete_span"
                    else:
                        action_type = "add_span" if old_value is None else "update_span"

                    # Create annotation action
                    action = AnnotationHistoryManager.create_action(
                        user_id=username,
                        instance_id=instance_id,
                        action_type=action_type,
                        schema_name=schema_name,
                        label_name=sv["name"],
                        old_value=old_value,
                        new_value=value,
                        span_data={
                            "start": start_offset,
                            "end": end_offset,
                            "title": sv.get("title", sv["name"])
                        },
                        session_id=user_state.current_session_id,
                        client_timestamp=client_timestamp,
                        metadata=metadata
                    )

                    # Add to history
                    user_state.add_annotation_action(action)

                    # Handle span deletion vs creation/update
                    if value is None:
                        # Delete the span - find and remove the matching span
                        if instance_id in user_state.instance_id_to_span_to_value:
                            # Find the span to delete by matching properties
                            spans_to_delete = []
                            for existing_span in user_state.instance_id_to_span_to_value[instance_id].keys():
                                if (existing_span.get_schema() == span.get_schema() and
                                    existing_span.get_name() == span.get_name() and
                                    existing_span.get_start() == span.get_start() and
                                    existing_span.get_end() == span.get_end()):
                                    spans_to_delete.append(existing_span)

                            for span_to_delete in spans_to_delete:
                                del user_state.instance_id_to_span_to_value[instance_id][span_to_delete]
                                logger.debug(f"Deleted span annotation: {span_to_delete}")
                    else:
                        # Add or update the span annotation
                        user_state.add_span_annotation(instance_id, span, value)
                        logger.debug(f"Added span annotation: {span} with value: {value}")
            elif annotation_type == "label":
                for sv in schema_state:
                    label = Label(schema_name, sv["name"])
                    value = sv["value"]

                    # Get old value for comparison
                    old_value = None
                    if instance_id in user_state.instance_id_to_label_to_value:
                        old_value = user_state.instance_id_to_label_to_value[instance_id].get(label)

                    # Determine action type
                    action_type = "add_label" if old_value is None else "update_label"
                
                   
                    # Create annotation action
                    action = AnnotationHistoryManager.create_action(
                        user_id=username,
                        instance_id=instance_id,
                        action_type=action_type,
                        schema_name=schema_name,
                        label_name=sv["name"],
                        old_value=old_value,
                        new_value=value,
                        session_id=user_state.current_session_id,
                        client_timestamp=client_timestamp,
                        metadata=metadata
                    )

                    # Add to history
                    user_state.add_annotation_action(action)

                    # Update annotation
                    user_state.add_label_annotation(instance_id, label, value)
        else:
            logger.warning("Unknown data format in /updateinstance")
            return jsonify({"status": "error", "message": "Unknown data format"})

        # Quality control validation (attention checks and gold standards)
        qc_manager = get_quality_control_manager()
        qc_result = None

        if qc_manager:
            # Collect all annotations for validation
            all_annotations = {}
            if "annotations" in request.json:
                for key, value in request.json.get("annotations", {}).items():
                    # Parse schema:label format
                    if ":" in key:
                        schema_name, label_name = key.split(":", 1)
                        all_annotations[schema_name] = value
                    else:
                        all_annotations[key] = value
            elif "schema" in request.json:
                schema_name = request.json.get("schema")
                schema_state = request.json.get("state", [])
                # Convert state list to dict for validation
                for sv in schema_state:
                    if "value" in sv:
                        all_annotations[schema_name] = sv.get("value")

            # Calculate response time
            response_time = None
            if client_timestamp:
                response_time = (datetime.datetime.now() - client_timestamp).total_seconds()

            # Check if this is an attention check
            attention_result = qc_manager.validate_attention_response(
                username, instance_id, all_annotations, response_time
            )

            if attention_result is not None:
                qc_result = {"type": "attention_check", **attention_result}

                # Handle blocking
                if attention_result.get("blocked"):
                    logger.warning(f"User {username} blocked by attention check")
                    # Don't save state for blocked user
                    return jsonify({
                        "status": "blocked",
                        "message": attention_result.get("message", "You have been blocked."),
                        "qc_result": qc_result
                    })
            else:
                # Check if this is a gold standard
                gold_result = qc_manager.validate_gold_response(
                    username, instance_id, all_annotations
                )

                if gold_result is not None:
                    qc_result = {"type": "gold_standard", **gold_result}

            # Record regular item for attention check frequency tracking
            if not qc_manager.is_attention_check(instance_id) and not qc_manager.is_gold_standard(instance_id):
                qc_manager.record_regular_item(username)

                # Track for gold standard auto-promotion
                promotion_result = qc_manager.record_item_annotation(
                    instance_id, username, all_annotations
                )
                if promotion_result and promotion_result.get("promoted"):
                    logger.info(f"Item {instance_id} auto-promoted to gold standard")

        # Calculate processing time
        processing_time_ms = int((time.time() - start_time) * 1000)

        # Update the last action's processing time
        if user_state.annotation_history:
            user_state.annotation_history[-1].server_processing_time_ms = processing_time_ms

        # Save state
        get_user_state_manager().save_user_state(user_state)
        logger.debug(f"User state saved for {username}")

        # Get performance metrics for response
        performance_metrics = user_state.get_performance_metrics()

        response_data = {
            "status": "success",
            "processing_time_ms": processing_time_ms,
            "performance_metrics": performance_metrics
        }

        # Include quality control result if present
        if qc_result:
            response_data["qc_result"] = qc_result

            # Add warning message if needed
            if qc_result.get("warning"):
                response_data["warning"] = True
                response_data["warning_message"] = qc_result.get("message")

        return jsonify(response_data)
    else:
        logger.warning("Update instance called without JSON data")
        return jsonify({"status": "error", "message": "JSON data required"})

@app.route("/poststudy", methods=["GET", "POST"])
def poststudy():
    """
    Handle the poststudy phase of the annotation process.

    Returns:
        flask.Response: Rendered template or redirect
    """
    if 'username' not in session:
        return home()

    username = session['username']
    user_state = get_user_state(username)

    # Check that the user is in the poststudy phase
    if user_state.get_phase() != UserPhase.POSTSTUDY:
        # If not in the poststudy phase, redirect
        return home()

    # If the user is returning information from the page
    if request.method == 'POST':
        logger.debug(f'POSTSTUDY: POST: {request.form}')

        # Advance the state and move to the appropriate next phase
        usm = get_user_state_manager()
        usm.advance_phase(session['username'])
        request.method = 'GET'
        return home()

    # Show the current poststudy page
    else:
        # Get the page the user is currently on
        phase, page = user_state.get_current_phase_and_page()
        logger.debug(f'POSTSTUDY GET: phase, page: {phase}, {page}')

        usm = get_user_state_manager()
        # Look up the html template for the current page
        html_fname = usm.get_phase_html_fname(phase, page)
        # Render the page
        return render_template(html_fname)

@app.route("/done", methods=["GET", "POST"])
def done():
    """
    Handle the done phase of the annotation process.

    This route displays the completion page with:
    - A thank you message
    - The completion code (if configured)
    - A redirect link to Prolific (if configured)

    Returns:
        flask.Response: Rendered template or redirect
    """
    if 'username' not in session:
        return home()

    username = session['username']
    user_state = get_user_state(username)

    # Check that the user is in the done phase
    if user_state.get_phase() != UserPhase.DONE:
        # If not in the done phase, redirect
        return home()

    # Get completion code from config
    completion_code = config.get("completion_code", "")

    # Build Prolific redirect URL if completion code is set
    prolific_redirect_url = None
    login_config = config.get('login', {})
    login_type = login_config.get('type', 'standard')

    if completion_code and login_type in ['url_direct', 'prolific']:
        # Build the Prolific completion URL (only if using Prolific-style URL argument)
        url_argument = login_config.get('url_argument', 'PROLIFIC_PID')
        if url_argument in ['PROLIFIC_PID', 'prolific_pid']:
            # Format: https://app.prolific.co/submissions/complete?cc=YOUR_CODE
            prolific_redirect_url = f"https://app.prolific.co/submissions/complete?cc={completion_code}"

    # Get MTurk submission parameters from session
    mturk_submit_url = session.get('mturk_submit_to')
    mturk_assignment_id = session.get('mturk_assignment_id')

    # Check for auto-redirect setting
    auto_redirect = config.get('auto_redirect_on_completion', False)
    auto_redirect_delay = config.get('auto_redirect_delay', 5000)  # milliseconds

    # Show the completion page
    return render_template("done.html",
                          title=config.get("annotation_task_name", "Annotation Platform"),
                          completion_code=completion_code,
                          prolific_redirect_url=prolific_redirect_url,
                          mturk_submit_url=mturk_submit_url,
                          mturk_assignment_id=mturk_assignment_id,
                          auto_redirect=auto_redirect,
                          auto_redirect_delay=auto_redirect_delay)

@app.route("/admin", methods=["GET"])
def admin():
    """
    Serve the admin dashboard page.

    This route serves the main admin dashboard interface with API key authentication.
    The dashboard provides comprehensive system monitoring and management capabilities.

    Returns:
        flask.Response: Rendered admin dashboard template or login form
    """
    # Check if admin API key is provided in session or headers
    api_key = request.headers.get('X-API-Key') or session.get('admin_api_key')

    if not validate_admin_api_key(api_key):
        # Show API key entry form
        return render_template("admin_login.html",
                             title=config.get("annotation_task_name", "Admin Dashboard"))

    # Store API key in session for future requests
    session['admin_api_key'] = api_key

    # Get basic context for the dashboard
    context = {
        "annotation_task_name": config.get("annotation_task_name", "Annotation Platform"),
        "debug_mode": config.get("debug", False)
    }

    return render_template("admin.html", **context)







@app.route("/api-frontend", methods=["GET"])
def api_frontend():
    """
    Serve the API-based frontend interface.

    This route serves a modern single-page application that uses API calls
    to interact with the backend instead of server-side rendering.

    Returns:
        flask.Response: Rendered API frontend template
    """
    if 'username' not in session:
        return redirect(url_for("home"))


    username = session['username']

    # Ensure user state exists
    if not get_user_state_manager().has_user(username):
        logger.info(f"Creating missing user state for {username}")
        init_user_state(username)

    user_state = get_user_state(username)

    # Check user phase
    if user_state.get_phase() != UserPhase.ANNOTATION:
        logger.info(f"User {username} not in annotation phase, redirecting")
        return home()

    # If the user hasn't yet been assigned anything to annotate, do so now
    if not user_state.has_assignments():
        get_item_state_manager().assign_instances_to_user(user_state)

    # See if this user has finished annotating all of their assigned instances
    if not user_state.has_remaining_assignments():
        # If the user is done annotating, advance to the next phase
        get_user_state_manager().advance_phase(username)
        return home()

    # Render the API frontend template
    return render_template("api_frontend.html",
                         username=username,
                         annotation_task_name=config.get("annotation_task_name", "Annotation Platform"),
                         annotation_codebook_url=config.get("annotation_codebook_url", ""),
                         alert_time_each_instance=config.get("alert_time_each_instance", 10000000))


@app.route("/span-api-frontend", methods=["GET"])
def span_api_frontend():
    """
    Serve the span annotation API-based frontend interface.

    This route serves a modern single-page application specifically designed
    for span annotation tasks that uses API calls to interact with the backend.

    Returns:
        flask.Response: Rendered span API frontend template
    """
    if 'username' not in session:
        return redirect(url_for("home"))


    username = session['username']

    # Ensure user state exists
    if not get_user_state_manager().has_user(username):
        logger.info(f"Creating missing user state for {username}")
        init_user_state(username)

    user_state = get_user_state(username)

    # Check user phase
    if user_state.get_phase() != UserPhase.ANNOTATION:
        logger.info(f"User {username} not in annotation phase, redirecting")
        return home()

    # If the user hasn't yet been assigned anything to annotate, do so now
    if not user_state.has_assignments():
        get_item_state_manager().assign_instances_to_user(user_state)

    # See if this user has finished annotating all of their assigned instances
    if not user_state.has_remaining_assignments():
        # If the user is done annotating, advance to the next phase
        get_user_state_manager().advance_phase(username)
        return home()

    # Render the span API frontend template
    return render_template("span_api_frontend.html",
                         username=username,
                         annotation_task_name=config.get("annotation_task_name", "Span Annotation Platform"),
                         annotation_codebook_url=config.get("annotation_codebook_url", ""),
                         alert_time_each_instance=config.get("alert_time_each_instance", 10000000))

@app.route("/test-span-colors")
def test_span_colors():
    """
    Serve a test page for visually verifying span colors.
    """
    return render_template("test_span_colors.html")

def normalize_color(color_value):
    """
    Normalize color value to a consistent format for the frontend.
    Accepts: hex (#rrggbb), rgb/rgba, named colors, or tuple format "(r, g, b)".
    Returns a CSS-compatible color string.
    """
    if not color_value:
        return None

    color_str = str(color_value).strip()

    # Already a valid CSS color (hex, rgb, rgba, named)
    if color_str.startswith('#') or color_str.startswith('rgb') or color_str.startswith('hsl'):
        return color_str

    # Tuple format "(r, g, b)" -> rgba
    if color_str.startswith("(") and color_str.endswith(")"):
        try:
            rgb_parts = color_str.strip("()").split(",")
            rgb_parts = [p.strip() for p in rgb_parts]
            if len(rgb_parts) == 3:
                r, g, b = int(rgb_parts[0]), int(rgb_parts[1]), int(rgb_parts[2])
                return f"rgba({r}, {g}, {b}, 0.8)"
            elif len(rgb_parts) == 4:
                r, g, b, a = int(rgb_parts[0]), int(rgb_parts[1]), int(rgb_parts[2]), float(rgb_parts[3])
                return f"rgba({r}, {g}, {b}, {a})"
        except (ValueError, IndexError):
            pass

    # Named color - return as-is
    return color_str


# Default color palette for labels (used when no custom color is specified)
DEFAULT_LABEL_COLORS = [
    'rgba(110, 86, 207, 0.8)',   # Purple (primary)
    'rgba(34, 197, 94, 0.8)',    # Green
    'rgba(239, 68, 68, 0.8)',    # Red
    'rgba(59, 130, 246, 0.8)',   # Blue
    'rgba(245, 158, 11, 0.8)',   # Amber
    'rgba(236, 72, 153, 0.8)',   # Pink
    'rgba(6, 182, 212, 0.8)',    # Cyan
    'rgba(249, 115, 22, 0.8)',   # Orange
    'rgba(139, 92, 246, 0.8)',   # Violet
    'rgba(16, 185, 129, 0.8)',   # Emerald
]

# Named color mappings for common label names
NAMED_LABEL_COLORS = {
    'positive': 'rgba(34, 197, 94, 0.8)',    # Green
    'negative': 'rgba(239, 68, 68, 0.8)',    # Red
    'neutral': 'rgba(156, 163, 175, 0.8)',   # Gray
    'mixed': 'rgba(245, 158, 11, 0.8)',      # Amber
    'happy': 'rgba(34, 197, 94, 0.8)',       # Green
    'sad': 'rgba(59, 130, 246, 0.8)',        # Blue
    'angry': 'rgba(220, 38, 38, 0.8)',       # Dark red
    'fear': 'rgba(139, 92, 246, 0.8)',       # Violet
    'surprise': 'rgba(249, 115, 22, 0.8)',   # Orange
    'disgust': 'rgba(132, 204, 22, 0.8)',    # Lime
    'yes': 'rgba(34, 197, 94, 0.8)',         # Green
    'no': 'rgba(239, 68, 68, 0.8)',          # Red
    'maybe': 'rgba(245, 158, 11, 0.8)',      # Amber
    'true': 'rgba(34, 197, 94, 0.8)',        # Green
    'false': 'rgba(239, 68, 68, 0.8)',       # Red
    'high': 'rgba(239, 68, 68, 0.8)',        # Red
    'medium': 'rgba(245, 158, 11, 0.8)',     # Amber
    'low': 'rgba(34, 197, 94, 0.8)',         # Green
}


def get_default_label_color(label_name, index=0):
    """
    Get a default color for a label based on its name or index.
    First checks for named colors, then falls back to palette by index.
    """
    # Check for named color match (case-insensitive)
    lower_name = label_name.lower().strip()
    if lower_name in NAMED_LABEL_COLORS:
        return NAMED_LABEL_COLORS[lower_name]

    # Fall back to color from palette based on index
    return DEFAULT_LABEL_COLORS[index % len(DEFAULT_LABEL_COLORS)]


@app.route("/api/colors")
def get_span_colors():
    """
    Return the color mapping for all schemas/labels as JSON.
    Supports colors from:
    1. ui.label_colors - global color definitions by schema/label
    2. ui.spans.span_colors - legacy span-specific colors
    3. Inline 'color' property on labels in annotation_schemes
    4. Auto-generated colors from SPAN_COLOR_PALETTE
    """
    logger.debug("=== GET_COLORS START ===")

    color_map = {}

    # 1. Load colors from ui.label_colors (new unified format)
    if "ui" in config and "label_colors" in config["ui"]:
        logger.debug("Found ui.label_colors in config")
        for schema_name, label_colors in config["ui"]["label_colors"].items():
            color_map[schema_name] = {}
            for label_name, color_value in label_colors.items():
                normalized = normalize_color(color_value)
                if normalized:
                    color_map[schema_name][label_name] = normalized

    # 2. Load colors from ui.spans.span_colors (legacy format)
    if "ui" in config and "spans" in config["ui"] and "span_colors" in config["ui"]["spans"]:
        logger.debug("Found ui.spans.span_colors in config")
        span_colors = config["ui"]["spans"]["span_colors"]
        for schema_name, label_colors in span_colors.items():
            if schema_name not in color_map:
                color_map[schema_name] = {}
            for label_name, color_value in label_colors.items():
                if label_name not in color_map[schema_name]:
                    normalized = normalize_color(color_value)
                    if normalized:
                        color_map[schema_name][label_name] = normalized

    # 3. Extract colors from annotation_schemes (inline label colors)
    annotation_schemes = config.get('annotation_schemes', [])
    if isinstance(annotation_schemes, list):
        for schema in annotation_schemes:
            schema_name = schema.get('name', f"schema_{schema.get('annotation_id', 'unknown')}")
            if schema_name not in color_map:
                color_map[schema_name] = {}

            labels = schema.get('labels', [])
            for i, label in enumerate(labels):
                if isinstance(label, dict):
                    label_name = label.get('name', str(label))
                    # Check for inline color definition
                    if 'color' in label and label_name not in color_map[schema_name]:
                        normalized = normalize_color(label['color'])
                        if normalized:
                            color_map[schema_name][label_name] = normalized
                else:
                    label_name = str(label)

                # Generate default color if not already set
                if label_name not in color_map[schema_name]:
                    # Try to get from SPAN_COLOR_PALETTE
                    assigned_color = get_span_color(schema_name, label_name)
                    if assigned_color:
                        normalized = normalize_color(assigned_color)
                        if normalized:
                            color_map[schema_name][label_name] = normalized
                    else:
                        # Use hash-based color from default palette
                        color_map[schema_name][label_name] = get_default_label_color(label_name, i)

    logger.debug(f"Final color map: {color_map}")
    logger.debug("=== GET_COLORS END ===")
    return jsonify(color_map)


@app.route("/api/keyword_highlights/<instance_id>")
def get_keyword_highlights(instance_id):
    """
    Get keyword highlights for a specific instance.

    This endpoint finds all occurrences of admin-defined keywords in the instance text
    and returns them in the same format as AI keyword suggestions, so they can be
    displayed using the same visual system (bounding boxes around keywords).

    The endpoint supports randomization for research purposes:
    - keyword_probability: Probability of showing each matched keyword (default: 1.0)
    - random_word_probability: Probability of highlighting random words as distractors (default: 0.05)

    Highlights are cached per user+instance to ensure consistency across navigation.

    Colors are assigned based on schema/label to match the span annotation color scheme.

    Returns:
        JSON with list of keyword matches:
        {
            "keywords": [
                {
                    "label": "Economic",
                    "start": 10,
                    "end": 20,
                    "text": "employment",
                    "reasoning": "Keyword match: employ*",
                    "schema": "Issue-General",
                    "color": "rgba(110, 86, 207, 0.8)",
                    "type": "keyword"
                },
                ...
            ],
            "instance_id": "item_1",
            "from_cache": false
        }
    """
    import urllib.parse
    import random
    import hashlib
    import re

    logger.debug(f"=== GET_KEYWORD_HIGHLIGHTS START ===")
    logger.debug(f"Instance ID: {instance_id}")

    decoded_instance_id = urllib.parse.unquote(instance_id)

    if 'username' not in session:
        logger.warning("Get keyword highlights without active session")
        return jsonify({"error": "No active session"}), 401

    username = session.get('username')

    # Get user state for caching
    user_state = get_user_state(username) if username else None

    # Check for cached state
    if user_state:
        cached_state = user_state.get_keyword_highlight_state(instance_id)
        if not cached_state:
            # Try with decoded ID
            cached_state = user_state.get_keyword_highlight_state(decoded_instance_id)
        if cached_state:
            logger.debug(f"Returning cached keyword highlights for {instance_id}")
            return jsonify({
                "keywords": cached_state.get("highlights", []),
                "instance_id": instance_id,
                "from_cache": True
            })

    # Get settings for randomization
    settings = get_keyword_highlight_settings()
    keyword_prob = settings.get('keyword_probability', 1.0)
    random_word_prob = settings.get('random_word_probability', 0.05)
    random_word_label = settings.get('random_word_label', 'distractor')
    random_word_schema = settings.get('random_word_schema', 'keyword')

    logger.debug(f"Keyword highlight settings: keyword_prob={keyword_prob}, random_word_prob={random_word_prob}")

    # Create deterministic seed from username + instance_id for reproducibility
    seed_str = f"{username}:{instance_id}" if username else instance_id
    seed = int(hashlib.md5(seed_str.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)

    # Check if keyword highlights are enabled
    keyword_patterns = get_keyword_highlight_patterns()

    # Get the instance text
    try:
        item_state_manager = get_item_state_manager()
        instance = item_state_manager.get_item(instance_id)
        if not instance:
            instance = item_state_manager.get_item(decoded_instance_id)
            if instance:
                instance_id = decoded_instance_id
            else:
                logger.error(f"Instance not found: {instance_id}")
                return jsonify({"error": "Instance not found"}), 404

        original_text = instance.get_text()
        logger.debug(f"Instance text length: {len(original_text)}")

    except Exception as e:
        logger.error(f"Error getting instance text: {e}")
        return jsonify({"error": f"Instance not found: {instance_id}"}), 404

    # Find all keyword matches in the text
    keywords = []
    seen_spans = set()  # Track (start, end) to avoid duplicate overlapping matches

    # Track color assignments for keyword labels (schema -> label -> color)
    keyword_color_counter = 0

    for pattern_info in keyword_patterns:
        regex = pattern_info['regex']
        label = pattern_info['label']
        schema = pattern_info['schema']
        pattern_str = pattern_info['pattern']

        for match in regex.finditer(original_text):
            start = match.start()
            end = match.end()
            matched_text = match.group()

            # Skip if we already have a match at this exact position
            span_key = (start, end)
            if span_key in seen_spans:
                continue

            # Apply keyword probability filter
            if rng.random() > keyword_prob:
                logger.debug(f"Skipping keyword '{matched_text}' due to probability filter")
                continue

            seen_spans.add(span_key)

            # Get or assign color for this schema/label combination
            color = get_span_color(schema, label)
            if not color:
                # Auto-assign a color from the palette
                idx = keyword_color_counter % len(SPAN_COLOR_PALETTE)
                color = SPAN_COLOR_PALETTE[idx]
                keyword_color_counter += 1
                # Store it for consistency
                set_span_color(schema, label, color)

            # Convert RGB tuple string to rgba format for frontend
            # Color format is "(r, g, b)" - convert to "rgba(r, g, b, 0.8)"
            if color.startswith("(") and color.endswith(")"):
                rgba_color = f"rgba{color[:-1]}, 0.8)"
            else:
                rgba_color = color

            keywords.append({
                "label": label,
                "start": start,
                "end": end,
                "text": matched_text,
                "reasoning": f"Keyword: {pattern_str} → {label}",
                "schema": schema,
                "color": rgba_color,
                "type": "keyword"
            })

    # Generate random word highlights (distractors)
    random_highlights = []
    if random_word_prob > 0:
        random_highlights = generate_random_word_highlights(
            original_text, rng, random_word_prob,
            random_word_label, random_word_schema,
            seen_spans
        )
        keywords.extend(random_highlights)

    # Sort by start position
    keywords.sort(key=lambda k: k['start'])

    logger.debug(f"Found {len(keywords)} total highlights ({len(keywords) - len(random_highlights)} keywords, {len(random_highlights)} random)")

    # Cache the state for this user+instance
    if user_state:
        user_state.set_keyword_highlight_state(instance_id, {
            "highlights": keywords,
            "seed": seed,
            "settings": {
                "keyword_probability": keyword_prob,
                "random_word_probability": random_word_prob
            }
        })
        logger.debug(f"Cached keyword highlight state for {username}:{instance_id}")

    logger.debug("=== GET_KEYWORD_HIGHLIGHTS END ===")

    return jsonify({
        "keywords": keywords,
        "instance_id": instance_id,
        "from_cache": False
    })


def generate_random_word_highlights(text: str, rng, probability: float,
                                    label: str, schema: str, excluded_spans: set) -> list:
    """
    Generate random word highlights based on probability.

    This function selects random words from the text to highlight as "distractors"
    to prevent annotators from relying solely on keyword highlights.

    Args:
        text: The instance text
        rng: Seeded random.Random instance for reproducibility
        probability: Probability of selecting each word (0.0-1.0)
        label: Label for random highlights (e.g., 'distractor')
        schema: Schema for random highlights (e.g., 'keyword')
        excluded_spans: Set of (start, end) tuples to avoid (already highlighted)

    Returns:
        List of highlight dictionaries with keys: label, start, end, text, reasoning, schema, color, type
    """
    import re

    highlights = []

    # Find all words (sequences of word characters)
    word_pattern = re.compile(r'\b\w+\b')

    # Get color for random highlights
    color = get_span_color(schema, label)
    if not color:
        # Use a gray color for distractors by default
        color = "(156, 163, 175)"
        set_span_color(schema, label, color)

    # Convert to rgba
    if color.startswith("(") and color.endswith(")"):
        color_str = f"rgba{color[:-1]}, 0.6)"
    else:
        color_str = color

    for match in word_pattern.finditer(text):
        start = match.start()
        end = match.end()
        word = match.group()

        # Skip if overlaps with existing highlight
        overlaps = False
        for ex_start, ex_end in excluded_spans:
            if start < ex_end and end > ex_start:
                overlaps = True
                break
        if overlaps:
            continue

        # Skip very short words (1-2 chars) - articles, prepositions, etc.
        if len(word) <= 2:
            continue

        # Apply probability
        if rng.random() < probability:
            highlights.append({
                "label": label,
                "start": start,
                "end": end,
                "text": word,
                "reasoning": "Random selection",
                "schema": schema,
                "color": color_str,
                "type": "random"
            })
            excluded_spans.add((start, end))

    return highlights


# =============================================================================
# Behavioral Tracking API Endpoints
# =============================================================================

@app.route("/api/track_interactions", methods=["POST"])
def track_interactions():
    """
    Receive batched interaction events from the frontend.

    Expected JSON payload:
    {
        "instance_id": "...",
        "events": [...],
        "focus_time": {"element": ms, ...},
        "scroll_depth": float
    }
    """
    import time as time_module
    from potato.interaction_tracking import get_or_create_behavioral_data

    if 'username' not in session:
        return jsonify({"error": "Not authenticated"}), 401

    username = session['username']
    data = request.get_json()

    if not data:
        return jsonify({"error": "No data provided"}), 400

    instance_id = data.get('instance_id')
    events = data.get('events', [])

    user_state = get_user_state(username)
    if not user_state:
        return jsonify({"error": "User state not found"}), 404

    # Get or create behavioral data for this instance
    bd = get_or_create_behavioral_data(
        user_state.instance_id_to_behavioral_data,
        instance_id
    )

    # Record server timestamp for each event
    server_timestamp = time_module.time()

    # Add events
    for event in events:
        # Add server timestamp if not present
        if 'timestamp' not in event or event.get('timestamp') is None:
            event['timestamp'] = server_timestamp

        # Ensure instance_id is set
        event['instance_id'] = instance_id

        # Add to behavioral data
        if hasattr(bd, 'interactions'):
            from potato.interaction_tracking import InteractionEvent
            bd.interactions.append(InteractionEvent(
                event_type=event.get('event_type', 'unknown'),
                timestamp=event.get('timestamp', server_timestamp),
                target=event.get('target', ''),
                instance_id=instance_id,
                client_timestamp=event.get('client_timestamp'),
                metadata=event.get('metadata', {}),
            ))

    # Update focus time if provided
    focus_time = data.get('focus_time', {})
    for element, time_ms in focus_time.items():
        if hasattr(bd, 'update_focus_time'):
            bd.update_focus_time(element, time_ms)
        elif hasattr(bd, 'focus_time_by_element'):
            bd.focus_time_by_element[element] = bd.focus_time_by_element.get(element, 0) + time_ms

    # Update scroll depth
    if 'scroll_depth' in data:
        scroll_depth = data['scroll_depth']
        if hasattr(bd, 'update_scroll_depth'):
            bd.update_scroll_depth(scroll_depth)
        elif hasattr(bd, 'scroll_depth_max'):
            bd.scroll_depth_max = max(bd.scroll_depth_max, scroll_depth)

    return jsonify({"status": "ok", "events_recorded": len(events)})


@app.route("/api/track_ai_usage", methods=["POST"])
def track_ai_usage():
    """
    Track AI assistance request, response, and user decisions.

    Expected JSON payload:
    {
        "instance_id": "...",
        "schema_name": "...",
        "event_type": "request" | "response" | "accept" | "reject",
        "suggestions": [...],  # for response events
        "accepted_value": "..."  # for accept events
    }
    """
    import time as time_module
    from potato.interaction_tracking import get_or_create_behavioral_data, AIUsageEvent

    if 'username' not in session:
        return jsonify({"error": "Not authenticated"}), 401

    username = session['username']
    data = request.get_json()

    if not data:
        return jsonify({"error": "No data provided"}), 400

    instance_id = data.get('instance_id')
    schema_name = data.get('schema_name')
    event_type = data.get('event_type')  # 'request', 'response', 'accept', 'reject'

    if not instance_id or not schema_name or not event_type:
        return jsonify({"error": "Missing required fields"}), 400

    user_state = get_user_state(username)
    if not user_state:
        return jsonify({"error": "User state not found"}), 404

    # Get or create behavioral data
    bd = get_or_create_behavioral_data(
        user_state.instance_id_to_behavioral_data,
        instance_id
    )

    timestamp = time_module.time()

    if event_type == 'request':
        # Create new AI usage event
        ai_event = AIUsageEvent(
            request_timestamp=timestamp,
            schema_name=schema_name,
        )
        if hasattr(bd, 'ai_usage'):
            bd.ai_usage.append(ai_event)

    elif event_type == 'response':
        suggestions = data.get('suggestions', [])
        # Update the most recent AI event for this schema
        if hasattr(bd, 'ai_usage'):
            for ai_event in reversed(bd.ai_usage):
                event_schema = ai_event.schema_name if hasattr(ai_event, 'schema_name') else ai_event.get('schema_name')
                event_response = ai_event.response_timestamp if hasattr(ai_event, 'response_timestamp') else ai_event.get('response_timestamp')
                if event_schema == schema_name and not event_response:
                    if hasattr(ai_event, 'response_timestamp'):
                        ai_event.response_timestamp = timestamp
                        ai_event.suggestions_shown = suggestions
                    else:
                        ai_event['response_timestamp'] = timestamp
                        ai_event['suggestions_shown'] = suggestions
                    break

    elif event_type in ('accept', 'reject'):
        accepted_value = data.get('accepted_value') if event_type == 'accept' else None
        # Update the most recent AI event for this schema
        if hasattr(bd, 'ai_usage'):
            for ai_event in reversed(bd.ai_usage):
                event_schema = ai_event.schema_name if hasattr(ai_event, 'schema_name') else ai_event.get('schema_name')
                event_response = ai_event.response_timestamp if hasattr(ai_event, 'response_timestamp') else ai_event.get('response_timestamp')
                if event_schema == schema_name and event_response:
                    if hasattr(ai_event, 'suggestion_accepted'):
                        ai_event.suggestion_accepted = accepted_value
                        ai_event.time_to_decision_ms = int((timestamp - ai_event.response_timestamp) * 1000)
                    else:
                        ai_event['suggestion_accepted'] = accepted_value
                        ai_event['time_to_decision_ms'] = int((timestamp - ai_event['response_timestamp']) * 1000)
                    break

    return jsonify({"status": "ok", "event_type": event_type})


@app.route("/api/track_annotation_change", methods=["POST"])
def track_annotation_change():
    """
    Track annotation changes from the frontend.

    Expected JSON payload:
    {
        "instance_id": "...",
        "schema_name": "...",
        "label_name": "...",
        "action": "select" | "deselect" | "update" | "clear",
        "old_value": ...,
        "new_value": ...,
        "source": "user" | "ai_accept" | "keyboard" | "prefill"
    }
    """
    import time as time_module
    from potato.interaction_tracking import get_or_create_behavioral_data, AnnotationChange

    if 'username' not in session:
        return jsonify({"error": "Not authenticated"}), 401

    username = session['username']
    data = request.get_json()

    if not data:
        return jsonify({"error": "No data provided"}), 400

    instance_id = data.get('instance_id')
    schema_name = data.get('schema_name')
    action = data.get('action')

    if not instance_id or not schema_name or not action:
        return jsonify({"error": "Missing required fields"}), 400

    user_state = get_user_state(username)
    if not user_state:
        return jsonify({"error": "User state not found"}), 404

    # Get or create behavioral data
    bd = get_or_create_behavioral_data(
        user_state.instance_id_to_behavioral_data,
        instance_id
    )

    # Create annotation change record
    change = AnnotationChange(
        timestamp=time_module.time(),
        schema_name=schema_name,
        label_name=data.get('label_name'),
        action=action,
        old_value=data.get('old_value'),
        new_value=data.get('new_value'),
        source=data.get('source', 'user'),
    )

    if hasattr(bd, 'annotation_changes'):
        bd.annotation_changes.append(change)

    return jsonify({"status": "ok"})


@app.route("/api/behavioral_data/<instance_id>", methods=["GET"])
def get_behavioral_data(instance_id):
    """
    Get behavioral data for a specific instance.
    Useful for debugging and analysis.
    """
    if 'username' not in session:
        return jsonify({"error": "Not authenticated"}), 401

    username = session['username']
    user_state = get_user_state(username)

    if not user_state:
        return jsonify({"error": "User state not found"}), 404

    bd = user_state.instance_id_to_behavioral_data.get(instance_id)

    if not bd:
        return jsonify({"error": "No behavioral data for instance"}), 404

    if hasattr(bd, 'to_dict'):
        return jsonify(bd.to_dict())
    elif isinstance(bd, dict):
        return jsonify(bd)
    else:
        return jsonify({"error": "Invalid behavioral data format"}), 500


@app.route("/api/schemas")
def get_annotation_schemas():
    """
    Return the annotation schema information for all annotation types.
    This provides the schema names, types, and their labels to the frontend
    and API consumers (like the user simulator).
    """
    logger.debug("=== GET_ANNOTATION_SCHEMAS START ===")

    schemas = {}
    annotation_scheme = config.get('annotation_scheme') or config.get('annotation_schemes')

    if annotation_scheme:
        # Helper function to extract labels from a schema
        def extract_labels(schema):
            labels = []
            for label in schema.get('labels', []):
                if isinstance(label, dict):
                    labels.append(label.get('name', str(label)))
                else:
                    labels.append(str(label))
            return labels

        # Helper function to process a single schema
        def process_schema(schema, schema_name=None):
            name = schema_name or schema.get('name', 'unknown')
            schema_type = schema.get('annotation_type') or schema.get('type', 'unknown')

            schema_info = {
                'name': name,
                'description': schema.get('description', ''),
                'labels': extract_labels(schema),
                'type': schema_type
            }

            # Include additional type-specific info
            if schema_type == 'likert':
                schema_info['size'] = schema.get('size', 5)
                schema_info['min_label'] = schema.get('min_label', '')
                schema_info['max_label'] = schema.get('max_label', '')
            elif schema_type == 'slider':
                schema_info['min_value'] = schema.get('min_value', 0)
                schema_info['max_value'] = schema.get('max_value', 100)
            elif schema_type == 'textbox':
                schema_info['textarea'] = schema.get('textarea', False)

            return schema_info

        # If dict (new style), iterate items
        if isinstance(annotation_scheme, dict):
            for schema_name, schema in annotation_scheme.items():
                schemas[schema_name] = process_schema(schema, schema_name)
        # If list (legacy style), iterate list
        elif isinstance(annotation_scheme, list):
            for schema in annotation_scheme:
                schema_name = schema.get('name', 'unknown')
                schemas[schema_name] = process_schema(schema)

    logger.debug(f"Found schemas: {schemas}")
    logger.debug("=== GET_ANNOTATION_SCHEMAS END ===")
    return jsonify(schemas)

@app.route("/api/spans/<instance_id>/clear", methods=["POST"])
def clear_span_annotations(instance_id):
    """
    Clear all span annotations for a specific instance and user.
    This is useful for debugging and fixing persistent overlay issues.
    """
    logger.debug(f"=== CLEAR_SPAN_ANNOTATIONS START ===")
    logger.debug(f"Instance ID: {instance_id}")

    if 'username' not in session:
        logger.warning("Clear span annotations without active session")
        return jsonify({"error": "No active session"}), 401

    username = session['username']
    logger.debug(f"Username: {username}")

    try:
        user_state = get_user_state(username)
        if not user_state:
            logger.error(f"User state not found for user: {username}")
            return jsonify({"error": "User state not found"}), 404

        # Normalize instance_id to string
        instance_id = str(instance_id)

        # Check if instance has span annotations
        if hasattr(user_state, 'instance_id_to_span_to_value'):
            if instance_id in user_state.instance_id_to_span_to_value:
                spans_before = len(user_state.instance_id_to_span_to_value[instance_id])
                logger.debug(f"Found {spans_before} spans for instance {instance_id}")

                # Clear the spans
                del user_state.instance_id_to_span_to_value[instance_id]
                logger.debug(f"Cleared {spans_before} spans for instance {instance_id}")

                return jsonify({
                    "status": "success",
                    "message": f"Cleared {spans_before} span annotations for instance {instance_id}",
                    "spans_cleared": spans_before
                })
            else:
                logger.debug(f"No spans found for instance {instance_id}")
                return jsonify({
                    "status": "success",
                    "message": f"No span annotations found for instance {instance_id}",
                    "spans_cleared": 0
                })
        else:
            logger.debug("User state has no span annotations")
            return jsonify({
                "status": "success",
                "message": "User state has no span annotations",
                "spans_cleared": 0
            })

    except Exception as e:
        logger.error(f"Error clearing span annotations: {e}")
        return jsonify({"error": f"Failed to clear span annotations: {str(e)}"}), 500

    finally:
        logger.debug(f"=== CLEAR_SPAN_ANNOTATIONS END ===")


@app.route("/api/links/<instance_id>")
def get_link_annotations(instance_id):
    """
    Get link annotations (span relationships) for a specific instance.

    Returns:
        JSON with link annotations for the instance.
    """
    logger.debug(f"=== GET_LINK_ANNOTATIONS START ===")
    logger.debug(f"Instance ID: {instance_id}")

    if 'username' not in session:
        logger.warning("Get link annotations without active session")
        return jsonify({"error": "No active session"}), 401

    username = session['username']
    logger.debug(f"Username: {username}")

    try:
        user_state = get_user_state(username)
        if not user_state:
            logger.error(f"User state not found for user: {username}")
            return jsonify({"error": "User state not found"}), 404

        # Normalize instance_id to string
        instance_id = str(instance_id)

        # Get link annotations for this instance
        links = user_state.get_link_annotations(instance_id)

        # Convert to serializable format
        links_data = []
        for link_id, link in links.items():
            links_data.append(link.to_dict())

        logger.debug(f"Found {len(links_data)} link annotations for instance {instance_id}")

        return jsonify({
            "status": "success",
            "instance_id": instance_id,
            "links": links_data
        })

    except Exception as e:
        logger.error(f"Error getting link annotations: {e}")
        return jsonify({"error": f"Failed to get link annotations: {str(e)}"}), 500

    finally:
        logger.debug(f"=== GET_LINK_ANNOTATIONS END ===")


@app.route("/api/links/<instance_id>/<link_id>", methods=["DELETE"])
def delete_link_annotation(instance_id, link_id):
    """
    Delete a specific link annotation.

    Args:
        instance_id: The instance ID
        link_id: The link ID to delete

    Returns:
        JSON with success/failure status.
    """
    logger.debug(f"=== DELETE_LINK_ANNOTATION START ===")
    logger.debug(f"Instance ID: {instance_id}, Link ID: {link_id}")

    if 'username' not in session:
        logger.warning("Delete link annotation without active session")
        return jsonify({"error": "No active session"}), 401

    username = session['username']
    logger.debug(f"Username: {username}")

    try:
        user_state = get_user_state(username)
        if not user_state:
            logger.error(f"User state not found for user: {username}")
            return jsonify({"error": "User state not found"}), 404

        # Normalize instance_id to string
        instance_id = str(instance_id)

        # Try to remove the link
        success = user_state.remove_link_annotation(instance_id, link_id)

        if success:
            logger.debug(f"Deleted link annotation: {link_id} from instance {instance_id}")
            return jsonify({
                "status": "success",
                "message": f"Link {link_id} deleted successfully"
            })
        else:
            logger.warning(f"Link not found: {link_id} in instance {instance_id}")
            return jsonify({
                "status": "error",
                "message": f"Link {link_id} not found"
            }), 404

    except Exception as e:
        logger.error(f"Error deleting link annotation: {e}")
        return jsonify({"error": f"Failed to delete link annotation: {str(e)}"}), 500

    finally:
        logger.debug(f"=== DELETE_LINK_ANNOTATION END ===")


@app.route("/api/waveform/<cache_key>")
def get_waveform_data(cache_key):
    """
    Serve pre-computed waveform data for audio annotation.

    This endpoint serves .dat waveform files generated by the WaveformService.
    The cache_key is an MD5 hash of the audio file path.

    Args:
        cache_key: The MD5 hash identifying the cached waveform file

    Returns:
        The binary waveform data file, or an error response
    """
    logger.debug(f"=== GET_WAVEFORM_DATA START ===")
    logger.debug(f"Cache key: {cache_key}")

    try:
        # Import waveform service
        from potato.server_utils.waveform_service import get_waveform_service

        waveform_service = get_waveform_service()
        if not waveform_service:
            logger.warning("WaveformService not initialized")
            return jsonify({"error": "Waveform service not available"}), 503

        # Construct the cache file path
        cache_path = os.path.join(waveform_service.cache_dir, f"{cache_key}.dat")

        if not os.path.exists(cache_path):
            logger.warning(f"Waveform file not found: {cache_path}")
            return jsonify({"error": "Waveform data not found"}), 404

        # Serve the waveform file
        from flask import send_file
        logger.debug(f"Serving waveform file: {cache_path}")
        return send_file(
            cache_path,
            mimetype='application/octet-stream',
            as_attachment=False
        )

    except Exception as e:
        logger.error(f"Error serving waveform data: {e}")
        return jsonify({"error": f"Failed to serve waveform data: {str(e)}"}), 500

    finally:
        logger.debug(f"=== GET_WAVEFORM_DATA END ===")


@app.route("/api/waveform/generate", methods=["POST"])
def generate_waveform():
    """
    Generate waveform data for an audio file.

    This endpoint triggers waveform generation for a given audio URL.
    It can be called by the frontend when the audio loads.

    Request body:
        audio_url: URL or path of the audio file

    Returns:
        JSON with the waveform URL or error message
    """
    logger.debug(f"=== GENERATE_WAVEFORM START ===")

    try:
        data = request.get_json()
        if not data or 'audio_url' not in data:
            return jsonify({"error": "audio_url is required"}), 400

        audio_url = data['audio_url']
        logger.debug(f"Generating waveform for: {audio_url}")

        # Import waveform service
        from potato.server_utils.waveform_service import get_waveform_service

        waveform_service = get_waveform_service()
        if not waveform_service:
            logger.warning("WaveformService not initialized")
            return jsonify({
                "error": "Waveform service not available",
                "use_client_fallback": True
            }), 503

        # Check if we should use client-side fallback
        if not waveform_service.is_available:
            return jsonify({
                "use_client_fallback": True,
                "message": "Server-side waveform generation not available"
            })

        # Get or generate waveform
        waveform_path = waveform_service.get_waveform_path(audio_url)
        if waveform_path:
            waveform_url = waveform_service.get_waveform_url(audio_url)
            logger.debug(f"Waveform available at: {waveform_url}")
            return jsonify({
                "waveform_url": waveform_url,
                "use_client_fallback": False
            })
        else:
            logger.warning(f"Failed to generate waveform for: {audio_url}")
            return jsonify({
                "use_client_fallback": True,
                "message": "Waveform generation failed, use client-side fallback"
            })

    except Exception as e:
        logger.error(f"Error generating waveform: {e}")
        return jsonify({
            "error": f"Failed to generate waveform: {str(e)}",
            "use_client_fallback": True
        }), 500

    finally:
        logger.debug(f"=== GENERATE_WAVEFORM END ===")


@app.route("/api/video/metadata", methods=["POST"])
def get_video_metadata():
    """
    Get metadata for a video file.

    This endpoint returns video metadata including duration, FPS, and resolution.
    It can be called by the frontend when a video loads to get frame-accurate
    timing information for video annotation.

    Request body:
        video_url: URL or path of the video file

    Returns:
        JSON with video metadata:
        - duration: Video duration in seconds
        - fps: Frames per second (estimated if not available)
        - width: Video width in pixels
        - height: Video height in pixels
        - frame_count: Total number of frames (if calculable)
    """
    logger.debug("=== GET_VIDEO_METADATA START ===")

    try:
        data = request.get_json()
        if not data or 'video_url' not in data:
            return jsonify({"error": "Missing video_url parameter"}), 400

        video_url = data['video_url']
        logger.debug(f"Video URL: {video_url}")

        # For now, return a basic response that the frontend can use
        # The actual video metadata will be determined by the browser
        # since we don't have ffprobe installed by default
        return jsonify({
            "status": "ok",
            "message": "Video metadata should be retrieved client-side",
            "video_url": video_url,
            "use_client_detection": True
        })

    except Exception as e:
        logger.error(f"Error getting video metadata: {e}")
        return jsonify({"error": str(e)}), 500

    finally:
        logger.debug("=== GET_VIDEO_METADATA END ===")


@app.route("/api/video/waveform/generate", methods=["POST"])
def generate_video_waveform():
    """
    Generate waveform data from a video file's audio track.

    This endpoint triggers waveform generation for a video's audio track.
    It reuses the existing audio waveform generation infrastructure.

    Request body:
        video_url: URL or path of the video file

    Returns:
        JSON with waveform status and cache key (if successful)
    """
    logger.debug("=== GENERATE_VIDEO_WAVEFORM START ===")

    try:
        data = request.get_json()
        if not data or 'video_url' not in data:
            return jsonify({"error": "Missing video_url parameter"}), 400

        video_url = data['video_url']
        logger.debug(f"Video URL for waveform: {video_url}")

        # Try to generate waveform using the existing WaveformService
        try:
            from potato.server_utils.waveform_service import WaveformService
            waveform_service = WaveformService()

            # Generate waveform from video (will extract audio track)
            result = waveform_service.generate_waveform(video_url)

            if result.get('status') == 'ready':
                return jsonify({
                    "status": "ready",
                    "waveform_url": result.get('waveform_url'),
                    "cache_key": result.get('cache_key')
                })
            else:
                return jsonify({
                    "status": result.get('status', 'pending'),
                    "message": result.get('message', 'Waveform generation in progress')
                })

        except ImportError:
            logger.warning("WaveformService not available for video waveform generation")
            return jsonify({
                "status": "unavailable",
                "message": "Waveform service not available",
                "use_client_fallback": True
            })

    except Exception as e:
        logger.error(f"Error generating video waveform: {e}")
        return jsonify({
            "error": str(e),
            "use_client_fallback": True
        }), 500

    finally:
        logger.debug("=== GENERATE_VIDEO_WAVEFORM END ===")


@app.route("/api/audio/proxy")
def audio_proxy():
    """
    Proxy endpoint for fetching external audio files with Range request support.

    This endpoint fetches audio files from external URLs and returns them
    with proper headers, bypassing CORS restrictions that prevent the browser
    from directly accessing external audio files for waveform generation.

    Supports HTTP Range requests to enable seeking in audio files.

    Query parameters:
        url: The external audio URL to fetch

    Returns:
        The audio file with appropriate Content-Type header
    """
    import requests as req

    audio_url = request.args.get('url')
    if not audio_url:
        return jsonify({"error": "Missing url parameter"}), 400

    # Validate URL (basic security check)
    if not audio_url.startswith(('http://', 'https://')):
        return jsonify({"error": "Invalid URL - must be http or https"}), 400

    try:
        # Forward any Range header from the client to the upstream server
        headers = {}
        if 'Range' in request.headers:
            headers['Range'] = request.headers['Range']

        # Fetch the audio file
        response = req.get(audio_url, headers=headers, stream=True, timeout=30)
        response.raise_for_status()

        # Get content type from response or default to audio/mpeg
        content_type = response.headers.get('Content-Type', 'audio/mpeg')
        content_length = response.headers.get('Content-Length')

        # Create response with the audio data
        flask_response = make_response(response.content)
        flask_response.headers['Content-Type'] = content_type
        flask_response.headers['Access-Control-Allow-Origin'] = '*'
        flask_response.headers['Cache-Control'] = 'public, max-age=3600'

        # Add headers to support Range requests (seeking)
        flask_response.headers['Accept-Ranges'] = 'bytes'

        if content_length:
            flask_response.headers['Content-Length'] = content_length

        # If the upstream returned a 206 Partial Content, pass that through
        if response.status_code == 206:
            flask_response.status_code = 206
            if 'Content-Range' in response.headers:
                flask_response.headers['Content-Range'] = response.headers['Content-Range']

        return flask_response

    except req.exceptions.Timeout:
        logger.error(f"Timeout fetching audio: {audio_url}")
        return jsonify({"error": "Request timed out"}), 504
    except req.exceptions.RequestException as e:
        logger.error(f"Error fetching audio {audio_url}: {e}")
        return jsonify({"error": f"Failed to fetch audio: {str(e)}"}), 502


@app.route("/api/ai_assistant", methods=["GET"])
def ai_assistant():
    annotation_id_str = request.args.get("annotationId")
    logger.debug(f"[AI Assistant] Request for annotationId={annotation_id_str}")

    # Handle null/None/invalid annotation IDs
    if annotation_id_str is None or annotation_id_str == "null" or annotation_id_str == "":
        logger.debug("[AI Assistant] Invalid annotation ID - returning empty")
        return jsonify({"html": "", "error": None})

    try:
        annotation_id = int(annotation_id_str)
    except (ValueError, TypeError):
        logger.debug("[AI Assistant] Failed to parse annotation ID")
        return jsonify({"html": "", "error": None})

    # Check if annotation_id is valid
    if annotation_id < 0 or annotation_id >= len(config.get("annotation_schemes", [])):
        logger.debug(f"[AI Assistant] annotation_id {annotation_id} out of range")
        return jsonify({"html": "", "error": None})

    username = session['username']
    user_state = get_user_state(username)
    instance = user_state.get_current_instance_index()
    annotation_type = config["annotation_schemes"][annotation_id]["annotation_type"]

    result = generate_ai_help_html(instance, annotation_id, annotation_type)
    logger.debug(f"[AI Assistant] Result for instance={instance}, annotation_id={annotation_id}, type={annotation_type}: '{result[:100] if result else 'empty'}...'")
    return result


def configure_routes(flask_app, app_config):
    """
    Initialize the Flask routes with the given Flask app instance
    and configuration.

    This function is called by flask_server.py when initializing the application.

    Args:
        flask_app: The Flask application instance
        app_config: The application configuration
    """
    global app, config
    app = flask_app
    config = app_config

    # Set up session configuration
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

    app.permanent_session_lifetime = timedelta(days=config.get("session_lifetime_days", 7))

    # Register all routes with the flask app instance
    app.add_url_rule("/", "home", home, methods=["GET", "POST"])
    app.add_url_rule("/auth", "auth", auth, methods=["GET", "POST"])
    app.add_url_rule("/passwordless-login", "passwordless_login", passwordless_login, methods=["GET", "POST"])
    app.add_url_rule("/clerk-login", "clerk_login", clerk_login, methods=["GET", "POST"])
    app.add_url_rule("/login", "login", login, methods=["GET", "POST"])
    app.add_url_rule("/logout", "logout", logout)
    app.add_url_rule("/submit_annotation", "submit_annotation", submit_annotation, methods=["POST"])
    app.add_url_rule("/register", "register", register, methods=["POST"])
    app.add_url_rule("/consent", "consent", consent, methods=["GET", "POST"])
    app.add_url_rule("/instructions", "instructions", instructions, methods=["GET", "POST"])
    app.add_url_rule("/prestudy", "prestudy", prestudy, methods=["GET", "POST"])
    app.add_url_rule("/training", "training", training, methods=["GET", "POST"])
    app.add_url_rule("/annotate", "annotate", annotate, methods=["GET", "POST"])
    app.add_url_rule("/go_to", "go_to", go_to, methods=["GET", "POST"])
    app.add_url_rule("/updateinstance", "update_instance", update_instance, methods=["POST"])
    app.add_url_rule("/poststudy", "poststudy", poststudy, methods=["GET", "POST"])
    app.add_url_rule("/done", "done", done, methods=["GET", "POST"])
    app.add_url_rule("/admin", "admin", admin, methods=["GET"])

    app.add_url_rule("/api/get_ai_suggestion", "get_ai_suggestion", get_ai_suggestion, methods=["GET"])
    
    app.add_url_rule("/api-frontend", "api_frontend", api_frontend, methods=["GET"])
    app.add_url_rule("/span-api-frontend", "span_api_frontend", span_api_frontend, methods=["GET"])
    app.add_url_rule("/api/spans/<instance_id>", "get_span_data", get_span_data, methods=["GET"])
    app.add_url_rule("/api/colors", "get_span_colors", get_span_colors, methods=["GET"])
    app.add_url_rule("/api/schemas", "get_annotation_schemas", get_annotation_schemas, methods=["GET"])
    app.add_url_rule("/api/keyword_highlights/<instance_id>", "get_keyword_highlights", get_keyword_highlights, methods=["GET"])
    app.add_url_rule("/test-span-colors", "test_span_colors", test_span_colors, methods=["GET"])
    app.add_url_rule("/api/spans/<instance_id>/clear", "clear_span_annotations", clear_span_annotations, methods=["POST"])
    app.add_url_rule("/api/links/<instance_id>", "get_link_annotations", get_link_annotations, methods=["GET"])
    app.add_url_rule("/api/links/<instance_id>/<link_id>", "delete_link_annotation", delete_link_annotation, methods=["DELETE"])
    app.add_url_rule("/api/current_instance", "get_current_instance", get_current_instance, methods=["GET"])
    app.add_url_rule("/api/ai_assistant", "ai_assistant", ai_assistant, methods=["GET"])
    app.add_url_rule("/api/audio/proxy", "audio_proxy", audio_proxy, methods=["GET"])
    app.add_url_rule("/admin/user_state/<user_id>", "admin_user_state", admin_user_state, methods=["GET"])
    app.add_url_rule("/admin/health", "admin_health", admin_health, methods=["GET"])
    app.add_url_rule("/admin/system_state", "admin_system_state", admin_system_state, methods=["GET"])
    app.add_url_rule("/admin/all_instances", "admin_all_instances", admin_all_instances, methods=["GET"])
    app.add_url_rule("/admin/item_state", "admin_item_state", admin_item_state, methods=["GET"])
    app.add_url_rule("/admin/item_state/<item_id>", "admin_item_state_detail", admin_item_state_detail, methods=["GET"])

    # New admin dashboard API routes
    app.add_url_rule("/admin/api/overview", "admin_api_overview", admin_api_overview, methods=["GET"])
    app.add_url_rule("/admin/api/annotators", "admin_api_annotators", admin_api_annotators, methods=["GET"])
    app.add_url_rule("/admin/api/instances", "admin_api_instances", admin_api_instances, methods=["GET"])
    app.add_url_rule("/admin/api/config", "admin_api_config", admin_api_config, methods=["GET", "POST"])
    app.add_url_rule("/admin/api/questions", "admin_api_questions", admin_api_questions, methods=["GET"])
    app.add_url_rule("/admin/api/annotation_history", "admin_api_annotation_history", admin_api_annotation_history, methods=["GET"])
    app.add_url_rule("/admin/api/suspicious_activity", "admin_api_suspicious_activity", admin_api_suspicious_activity, methods=["GET"])
    app.add_url_rule("/admin/api/crowdsourcing", "admin_api_crowdsourcing", admin_api_crowdsourcing, methods=["GET"])

    # ICL labeling admin API routes
    app.add_url_rule("/admin/api/icl/status", "admin_api_icl_status", admin_api_icl_status, methods=["GET"])
    app.add_url_rule("/admin/api/icl/examples", "admin_api_icl_examples", admin_api_icl_examples, methods=["GET"])
    app.add_url_rule("/admin/api/icl/predictions", "admin_api_icl_predictions", admin_api_icl_predictions, methods=["GET"])
    app.add_url_rule("/admin/api/icl/accuracy", "admin_api_icl_accuracy", admin_api_icl_accuracy, methods=["GET"])
    app.add_url_rule("/admin/api/icl/trigger", "admin_api_icl_trigger", admin_api_icl_trigger, methods=["POST"])
    app.add_url_rule("/api/icl/record_verification", "api_icl_record_verification", api_icl_record_verification, methods=["POST"])

    # Behavioral tracking and analytics routes
    app.add_url_rule("/admin/api/agreement", "admin_api_agreement", admin_api_agreement, methods=["GET"])
    app.add_url_rule("/admin/api/quality_control", "admin_api_quality_control", admin_api_quality_control, methods=["GET"])
    app.add_url_rule("/admin/api/behavioral_analytics", "admin_api_behavioral_analytics", admin_api_behavioral_analytics, methods=["GET"])
    app.add_url_rule("/api/track_interactions", "track_interactions", track_interactions, methods=["POST"])
    app.add_url_rule("/api/track_ai_usage", "track_ai_usage", track_ai_usage, methods=["POST"])
    app.add_url_rule("/api/track_annotation_change", "track_annotation_change", track_annotation_change, methods=["POST"])
    app.add_url_rule("/api/behavioral_data/<instance_id>", "get_behavioral_data", get_behavioral_data, methods=["GET"])

    app.add_url_rule("/shutdown", "shutdown", shutdown, methods=["POST"])

@app.route('/shutdown', methods=['POST'])
def shutdown():
    func = request.environ.get('werkzeug.server.shutdown')
    if func is None:
        return jsonify({'error': 'Not running with the Werkzeug Server'}), 500
    logger.info('Shutting down server via /shutdown')
    func()
    return jsonify({'status': 'Server shutting down...'})


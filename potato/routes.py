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
    get_prolific_study, keyword_highlight_patterns
)

# Import admin dashboard functionality
from potato.admin import admin_dashboard

# Import span color functions
from potato.ai.ai_help_wrapper import generate_ai_help_html
from potato.ai.ai_prompt import get_ai_prompt
from potato.server_utils.schemas.span import get_span_color, set_span_color, SPAN_COLOR_PALETTE

# Import annotation history
from potato.annotation_history import AnnotationHistoryManager

import os

def get_admin_api_key():
    """Get the admin API key from config or environment variable.

    Returns:
        str or None: The configured admin API key, or None if not configured.
    """
    return config.get("admin_api_key") or os.environ.get("POTATO_ADMIN_API_KEY")

def validate_admin_api_key(provided_key: str) -> bool:
    """Validate an admin API key against the configured key.

    In debug mode, admin endpoints are accessible without a key.
    In production, a valid API key must be configured and provided.

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
        logger.warning("Admin API key not configured - admin endpoints disabled in production")
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
    first_phase = UserPhase.fromstr(first_phase_name)
    logger.debug(f"First phase from config: {first_phase_name} -> {first_phase}")

    # Set user to the first phase if they're in LOGIN
    if user_state and user_state.get_phase() == UserPhase.LOGIN:
        logger.debug(f"Advancing user {username} to first phase: {first_phase}")
        user_state.advance_to_phase(first_phase, None)
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
        # Render the instructions
        return render_template(instructions_html_fname)

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
    return res


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

        original_text = instance.get_text()
        logger.debug(f"Original text: {original_text[:100]}...")
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

        span_data.append({
            'id': span_id,
            'schema': span_schema,
            'label': span_name,
            'title': span_title,
            'start': span_start,
            'end': span_end,
            'text': original_text[span_start:span_end] if span_start < len(original_text) and span_end <= len(original_text) else "",
            'color': hex_color
        })
    
    response_data = {
        'instance_id': instance_id,
        'text': original_text,
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
                if ":" in key:
                    schema_name, label_name = key.split(":", 1)
                    label = Label(schema_name, label_name)

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
                    logger.debug(f"Added label annotation: {schema_name}:{label_name} = {value}")

            # Handle span annotations from frontend format
            span_annotations = request.json.get("span_annotations", [])
            for span_data in span_annotations:
                if isinstance(span_data, dict) and "schema" in span_data:
                    span = SpanAnnotation(
                        span_data["schema"],
                        span_data["name"],
                        span_data.get("title", span_data["name"]),
                        int(span_data["start"]),
                        int(span_data["end"])
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

        # Check if this is the backend format (schema, state, type)
        elif "schema" in request.json and "state" in request.json and "type" in request.json:
            logger.debug("Processing backend format (schema, state, type)")

            schema_name = request.json.get("schema")
            schema_state = request.json.get("state")
            annotation_type = request.json.get("type")

            if annotation_type == "span":
                print("schema_stateschema_state", schema_state)
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
                    span = SpanAnnotation(schema_name, sv["name"], sv.get("title", sv["name"]), start_offset, end_offset, span_id)
                    
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

        return jsonify({
            "status": "success",
            "processing_time_ms": processing_time_ms,
            "performance_metrics": performance_metrics
        })
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
        # Build the Prolific completion URL
        # Format: https://app.prolific.co/submissions/complete?cc=YOUR_CODE
        prolific_redirect_url = f"https://app.prolific.co/submissions/complete?cc={completion_code}"

    # Check for auto-redirect setting
    auto_redirect = config.get('auto_redirect_on_completion', False)
    auto_redirect_delay = config.get('auto_redirect_delay', 5000)  # milliseconds

    # Show the completion page
    return render_template("done.html",
                          title=config.get("annotation_task_name", "Annotation Platform"),
                          completion_code=completion_code,
                          prolific_redirect_url=prolific_redirect_url,
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

@app.route("/api/colors")
def get_span_colors():
    """
    Return the span color mapping for all schemas/labels as JSON.
    """
    logger.debug("=== GET_SPAN_COLORS START ===")
    logger.debug(f"Config keys: {list(config.keys())}")
    logger.debug(f"UI config: {config.get('ui', 'NOT_FOUND')}")

    # First, try to get colors from ui.spans.span_colors (current config format)
    color_map = {}
    if "ui" in config and "spans" in config["ui"] and "span_colors" in config["ui"]["spans"]:
        logger.debug("Found ui.spans.span_colors in config")
        span_colors = config["ui"]["spans"]["span_colors"]
        logger.debug(f"Span colors from config: {span_colors}")
        # Convert RGB format to hex for frontend compatibility
        for schema_name, label_colors in span_colors.items():
            color_map[schema_name] = {}
            for label_name, rgb_color in label_colors.items():
                # Convert RGB format "(r, g, b)" to hex
                if isinstance(rgb_color, str) and rgb_color.startswith("(") and rgb_color.endswith(")"):
                    try:
                        # Parse RGB values
                        rgb_parts = rgb_color.strip("()").split(", ")
                        if len(rgb_parts) == 3:
                            r, g, b = int(rgb_parts[0]), int(rgb_parts[1]), int(rgb_parts[2])
                            hex_color = f"#{r:02x}{g:02x}{b:02x}"
                            color_map[schema_name][label_name] = hex_color
                            logger.debug(f"Converted {rgb_color} to {hex_color}")
                        else:
                            color_map[schema_name][label_name] = "#f0f0f0"
                    except (ValueError, IndexError):
                        color_map[schema_name][label_name] = "#f0f0f0"
                else:
                    color_map[schema_name][label_name] = rgb_color
    else:
        logger.debug("No ui.spans.span_colors found in config")

    # If no colors found in ui.spans.span_colors, try annotation_scheme format
    if not color_map:
        logger.debug("Trying annotation_scheme format")
        annotation_scheme = config.get('annotation_scheme') or config.get('annotation_schemes')
        logger.debug(f"Annotation scheme: {annotation_scheme}")
        if annotation_scheme:
            # If dict (new style), iterate items
            if isinstance(annotation_scheme, dict):
                for schema_name, schema in annotation_scheme.items():
                    if schema.get('type') == 'span':
                        label_colors = {}
                        # Prefer color_scheme, fallback to default
                        color_scheme = schema.get('color_scheme')
                        labels = schema.get('labels', [])
                        for label in labels:
                            if isinstance(label, dict):
                                label_name = label.get('name', label)
                            else:
                                label_name = label
                            if color_scheme and label_name in color_scheme:
                                label_colors[label_name] = color_scheme[label_name]
                            else:
                                # Fallback color
                                label_colors[label_name] = '#f0f0f0'
                        color_map[schema_name] = label_colors
            # If list (legacy style), iterate list
            elif isinstance(annotation_scheme, list):
                for schema in annotation_scheme:
                    if schema.get('type') == 'span' or schema.get('annotation_type') == 'span':
                        schema_name = schema.get('name', 'span')
                        label_colors = {}
                        color_scheme = schema.get('color_scheme') or schema.get('colors')
                        labels = schema.get('labels', [])
                        for label in labels:
                            if isinstance(label, dict):
                                label_name = label.get('name', label)
                            else:
                                label_name = label
                            if color_scheme and label_name in color_scheme:
                                label_colors[label_name] = color_scheme[label_name]
                            else:
                                label_colors[label_name] = '#f0f0f0'
                        color_map[schema_name] = label_colors

    # Fallback: provide all expected keys with better colors that match the design system
    if not color_map:
        logger.debug("Using fallback colors")
        # Enhanced color palette that matches the design system and provides good contrast
        enhanced_colors = {
            # Primary colors (based on the purple theme)
            'positive': '#6E56CF',  # Primary purple
            'negative': '#EF4444',  # Destructive red
            'neutral': '#71717A',   # Gray
            'mixed': '#F59E0B',     # Amber
            'happy': '#10B981',     # Success green
            'sad': '#3B82F6',       # Blue
            'angry': '#DC2626',     # Red
            'surprised': '#8B5CF6', # Purple
            'low': '#9CA3AF',       # Light gray
            'medium': '#6B7280',    # Medium gray
            'high': '#374151',      # Dark gray
            # Additional colors for variety
            'excited': '#F97316',   # Orange
            'calm': '#06B6D4',      # Cyan
            'confused': '#EC4899',  # Pink
            'confident': '#059669', # Dark green
            'uncertain': '#7C3AED', # Violet
            'satisfied': '#16A34A', # Green
            'dissatisfied': '#EA580C', # Dark orange
            'optimistic': '#2563EB', # Blue
            'pessimistic': '#7F1D1D', # Dark red
        }
        color_map = {
            'sentiment': enhanced_colors,
            'emotion': enhanced_colors,
            'entity': enhanced_colors,
            'topic': enhanced_colors,
            'intensity': enhanced_colors,
        }

    logger.debug(f"Final color map: {color_map}")
    logger.debug("=== GET_SPAN_COLORS END ===")
    return jsonify(color_map)


@app.route("/api/keyword_highlights/<instance_id>")
def get_keyword_highlights(instance_id):
    """
    Get keyword highlights for a specific instance.

    This endpoint finds all occurrences of admin-defined keywords in the instance text
    and returns them in the same format as AI keyword suggestions, so they can be
    displayed using the same visual system (bounding boxes around keywords).

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
                    "color": "rgba(110, 86, 207, 0.8)"
                },
                ...
            ],
            "instance_id": "item_1"
        }
    """
    import urllib.parse

    logger.debug(f"=== GET_KEYWORD_HIGHLIGHTS START ===")
    logger.debug(f"Instance ID: {instance_id}")

    decoded_instance_id = urllib.parse.unquote(instance_id)

    if 'username' not in session:
        logger.warning("Get keyword highlights without active session")
        return jsonify({"error": "No active session"}), 401

    # Check if keyword highlights are enabled
    if not keyword_highlight_patterns:
        logger.debug("No keyword highlight patterns loaded")
        return jsonify({"keywords": [], "instance_id": instance_id})

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

    for pattern_info in keyword_highlight_patterns:
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
                "color": rgba_color
            })

    # Sort by start position
    keywords.sort(key=lambda k: k['start'])

    logger.debug(f"Found {len(keywords)} keyword matches")
    logger.debug("=== GET_KEYWORD_HIGHLIGHTS END ===")

    return jsonify({
        "keywords": keywords,
        "instance_id": instance_id
    })


@app.route("/api/schemas")
def get_annotation_schemas():
    """
    Return the annotation schema information for all span annotation types.
    This provides the schema names and their labels to the frontend.
    """
    logger.debug("=== GET_ANNOTATION_SCHEMAS START ===")

    schemas = {}
    annotation_scheme = config.get('annotation_scheme') or config.get('annotation_schemes')

    if annotation_scheme:
        # If dict (new style), iterate items
        if isinstance(annotation_scheme, dict):
            for schema_name, schema in annotation_scheme.items():
                if schema.get('type') == 'span' or schema.get('annotation_type') == 'span':
                    labels = []
                    for label in schema.get('labels', []):
                        if isinstance(label, dict):
                            labels.append(label.get('name', str(label)))
                        else:
                            labels.append(str(label))

                    schemas[schema_name] = {
                        'name': schema_name,
                        'description': schema.get('description', ''),
                        'labels': labels,
                        'type': 'span'
                    }
        # If list (legacy style), iterate list
        elif isinstance(annotation_scheme, list):
            for schema in annotation_scheme:
                if schema.get('type') == 'span' or schema.get('annotation_type') == 'span':
                    schema_name = schema.get('name', 'span')
                    labels = []
                    for label in schema.get('labels', []):
                        if isinstance(label, dict):
                            labels.append(label.get('name', str(label)))
                        else:
                            labels.append(str(label))

                    schemas[schema_name] = {
                        'name': schema_name,
                        'description': schema.get('description', ''),
                        'labels': labels,
                        'type': 'span'
                    }

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


@app.route("/api/ai_assistant", methods=["GET"])
def ai_assistant():
    annotation_id = int(request.args.get("annotationId"))
    username = session['username']
    user_state = get_user_state(username)
    instance = user_state.get_current_instance_index()
    annotation_type = config["annotation_schemes"][annotation_id]["annotation_type"]
    return generate_ai_help_html(instance, annotation_id, annotation_type)


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
    app.add_url_rule("/api/current_instance", "get_current_instance", get_current_instance, methods=["GET"])
    app.add_url_rule("/api/ai_assistant", "ai_assistant", ai_assistant, methods=["GET"])
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

    app.add_url_rule("/shutdown", "shutdown", shutdown, methods=["POST"])

@app.route('/shutdown', methods=['POST'])
def shutdown():
    func = request.environ.get('werkzeug.server.shutdown')
    if func is None:
        return jsonify({'error': 'Not running with the Werkzeug Server'}), 500
    logger.info('Shutting down server via /shutdown')
    func()
    return jsonify({'status': 'Server shutting down...'})


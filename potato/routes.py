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
    get_users, get_total_annotations, update_annotation_state, ai_hints
)

# Import admin dashboard functionality
from potato.admin import admin_dashboard

# Import span color functions
from potato.server_utils.schemas.span import get_span_color

# Import annotation history
from potato.annotation_history import AnnotationHistoryManager

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
        logger.debug("No active session, rendering login page")
        return render_template("home.html", title=config.get("annotation_task_name", "Annotation Platform"))

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

        # Validate that user ID is provided
        if not user_id:
            logger.warning("Login attempt with empty user_id")
            return render_template("home.html",
                                  login_error="User ID is required",
                                  title=config.get("annotation_task_name", "Annotation Platform"))

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
            return render_template("home.html",
                                  login_error="Invalid user ID or password",
                                  login_email=user_id,
                                  title=config.get("annotation_task_name", "Annotation Platform"))

    # GET request - show the login form
    return render_template("home.html",
                         title=config.get("annotation_task_name", "Annotation Platform"))


@app.route("/passwordless-login", methods=["GET", "POST"])
def passwordless_login():
    """
    Handle passwordless login page requests.

    This route provides a simplified login interface for systems configured
    to use passwordless authentication. Users only need to provide their
    username to access the annotation platform.

    Features:
    - Passwordless authentication flow
    - Configuration-based access control
    - User state initialization
    - Error handling and validation

    Returns:
        flask.Response: Rendered template or redirect

    Side Effects:
        - May create new user sessions
        - May initialize new user states
    """
    logger.debug("Processing passwordless login page request")

    # Redirect to regular login if passwords are required
    if config.get("require_password", True):
        logger.debug("Passwords required, redirecting to regular login")
        return redirect(url_for("home"))

    # Handle POST requests for passwordless authentication
    if request.method == "POST":
        username = request.form.get("email")

        # Validate that username is provided
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

    print(f"[DEBUG] /submit_annotation: id(get_user_state_manager())={id(get_user_state_manager())}")
    print(f"[DEBUG] /submit_annotation: user IDs in manager: {get_user_state_manager().get_user_ids()}")
    print(f"[DEBUG] /submit_annotation: session username = {session.get('username', 'NOT_SET')}")

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
        print(f"🔍 submit_annotation - JSON data: {data}")
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
        print(f"🔍 submit_annotation - Form data: {dict(request.form)}")

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

        print(f"🔍 submit_annotation - Processing annotations: {annotations}")

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
                    print(f"🔍 Added annotation: {schema_name}:{label_name} = {value}")
            elif isinstance(label_data, str):
                # Direct string value for text annotations: {'schema': 'value'}
                # For text annotations, we need to create a label with a default name
                label = Label(schema_name, "text_box")
                logger.debug(f"Adding text annotation: {schema_name}:text_box = {label_data}")
                user_state.add_label_annotation(instance_id, label, label_data)
                annotations_processed += 1
                print(f"🔍 Added text annotation: {schema_name}:text_box = {label_data}")
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

        print(f"🔍 submit_annotation - Successfully processed {annotations_processed} annotations")
        print(f"🔍 submit_annotation - User state after save: {dict(user_state.instance_id_to_label_to_value)}")

        logger.info(f"Successfully saved annotation for {instance_id} from {user_id}")
        logger.debug("=== SUBMIT ANNOTATION ROUTE END ===")
        return jsonify({"status": "success", "message": "Annotation saved successfully", "annotations_processed": annotations_processed})

    except Exception as e:
        logger.error(f"Error saving annotation: {str(e)}")
        logger.debug(f"Exception details: {type(e).__name__}: {str(e)}")
        print(f"🔍 submit_annotation - Error: {str(e)}")
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

    # Ensure user is in annotation phase and has assignments
    usm = get_user_state_manager()
    user_state = usm.get_user_state(username)
    logger.debug(f"Retrieved user state for '{username}': {user_state}")
    logger.debug(f"User state phase: {user_state.get_phase() if user_state else 'No user state'}")

    # Advance user to annotation phase if not already there
    if user_state and user_state.get_phase() != UserPhase.ANNOTATION:
        logger.debug(f"Advancing user {username} to annotation phase")
        user_state.advance_to_phase(UserPhase.ANNOTATION, None)
        logger.debug(f"User state phase after advancement: {user_state.get_phase()}")

    # Assign instances if user doesn't have any
    if user_state and not user_state.has_assignments():
        logger.debug(f"Assigning instances to user {username}")
        get_item_state_manager().assign_instances_to_user(user_state)
        logger.debug(f"User has assignments after assignment: {user_state.has_assignments()}")

    logger.debug("=== REGISTER ROUTE END - Redirecting to annotate ===")
    # Redirect to the annotate page
    return redirect(url_for("annotate"))

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
    print('CONSENT: user_state: ', user_state)
    print('CONSENT: user_state.get_phase(): ', user_state.get_phase())

    # Check that the user is still in the consent phase
    if user_state.get_phase() != UserPhase.CONSENT:
        # If not in the consent phase, redirect
        return home()

    # If the user is returning information from the page
    if request.method == 'POST':
        # The form should require that the user consent to the study
        print('POST -> CONSENT: ', request.form)

        # Now that the user has consented, advance the state
        # and have the home page redirect to the appropriate next phase
        usm = get_user_state_manager()
        usm.advance_phase(session['username'])

        # Reset to pretend this is a new get request
        request.method = 'GET'
        return home()
    # Show the current consent form
    else:
        print("GET <- CONSENT")
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
        print('POST -> INSTRUCTIONS: ', request.form)

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
        print('GET <-- INSTRUCTIONS: phase, page: ', phase, page)

        usm = get_user_state_manager()
        # Look up the html template for the current instructions
        instructions_html_fname = usm.get_phase_html_fname(phase, page)
        # Render the instructions
        return render_template(instructions_html_fname)

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
        print('NOT IN PRESTUDY PHASE')
        return home()

    # If the user is returning information from the page
    if request.method == 'POST':
        print('POST -> PRESTUDY: ', request.form)

        # Advance the state and redirect to the appropriate next phase
        usm = get_user_state_manager()
        usm.advance_phase(session['username'])
        request.method = 'GET'
        return home()

    # Show the current prestudy page
    else:
        # Get the page the user is currently on
        phase, page = user_state.get_current_phase_and_page()
        print('GET <-- PRESTUDY: phase, page: ', phase, page)

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

     # Process any annotation updates if they were submitted
    if request.method == 'POST' and request.json and 'instance_id' in request.json:
        if action == "prev_instance" or action == "next_instance" or action == "go_to":
            logger.debug(f"Updating annotation state for user: {username}")
            update_annotation_state(username, request.json)

    if action == "prev_instance":
        logger.debug(f"Moving to previous instance for user: {username}")
        move_to_prev_instance(username)
    elif action == "next_instance":
        logger.debug(f"Moving to next instance for user: {username}")
        move_to_next_instance(username)
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
        else:
            logger.warning('go_to action requested but no go_to value provided')
    else:
        logger.debug(f'Action "{action}" - no specific handling')

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

@app.route('/get_ai_hint', methods=['GET'])
def get_ai_hint():
    if 'username' not in session:
        return home()

    username = session['username']
    user_state = get_user_state(username)
    instance_text = request.args.get('instance_text')
    print(f"instance_text: {instance_text}")
    instance = user_state.get_current_instance()
    if instance is None:
        return jsonify({'reasoning': 'No instance assigned.'})

    instance_id = instance.get_id()

    # Return cached version if it exists
    if user_state.hint_exists(instance_id):
        return jsonify({'reasoning': user_state.get_hint(instance_id)})

    # Otherwise generate, cache, and return
    reasoning = ai_hints(instance_text)
    user_state.cache_hint(instance_id, reasoning)

    return jsonify({'reasoning': reasoning})


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
    if not config.get("debug", False) and api_key != "admin_api_key":
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
    if not config.get("debug", False) and api_key != "admin_api_key":
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
    if not config.get("debug", False) and api_key != "admin_api_key":
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
    logger.debug(f"API key provided: {api_key}")
    logger.debug(f"Expected API key: admin_api_key")

    if not config.get("debug", False) and api_key != "admin_api_key":
        logger.warning(f"Access denied - debug mode: {config.get('debug', False)}, api_key: {api_key}")
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

            print(f"[DEBUG] /admin/user_state: instance_id={current_instance.get_id()} displayed_text=\n{displayed_text}\n---END---")

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
        print(f"🔍 test_user_state - all_annotations raw: {all_annotations}")
        print(f"🔍 test_user_state - instance_id_to_label_to_value: {dict(user_state.instance_id_to_label_to_value)}")
        print(f"🔍 test_user_state - instance_id_to_span_to_value: {dict(user_state.instance_id_to_span_to_value)}")

        # Convert all keys to strings for JSON serialization
        serializable_annotations = {}
        for instance_id, annotations in all_annotations.items():
            instance_id_str = str(instance_id)
            serializable_annotations[instance_id_str] = {}
            print(f"🔍 Processing instance {instance_id_str}: {annotations}")

            # Process labels
            if "labels" in annotations:
                print(f"🔍 Processing labels for instance {instance_id_str}: {annotations['labels']}")
                for label, value in annotations["labels"].items():
                    print(f"🔍 Processing label: {label} (type: {type(label)}) = {value}")
                    if hasattr(label, 'schema_name') and hasattr(label, 'label_name'):
                        label_str = f"{label.schema_name}:{label.label_name}"
                        print(f"🔍 Converted label to string: {label_str}")
                    else:
                        label_str = str(label)
                        print(f"🔍 Using string representation: {label_str}")
                    serializable_annotations[instance_id_str][label_str] = value

            # Process spans
            if "spans" in annotations:
                print(f"🔍 Processing spans for instance {instance_id_str}: {annotations['spans']}")
                for span, value in annotations["spans"].items():
                    span_str = str(span)
                    serializable_annotations[instance_id_str][span_str] = value

        serializable_annotations = stringify_keys(serializable_annotations)
        print(f"🔍 test_user_state - serializable_annotations: {serializable_annotations}")

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
    if not config.get("debug", False) and api_key != "admin_api_key":
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
    if not config.get("debug", False) and api_key != "admin_api_key":
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
        return jsonify({
            "max_annotations_per_user": config.get("max_annotations_per_user", -1),
            "max_annotations_per_item": config.get("max_annotations_per_item", -1),
            "assignment_strategy": config.get("assignment_strategy", "fixed_order"),
            "annotation_task_name": config.get("annotation_task_name", "Unknown"),
            "debug_mode": config.get("debug", False)
        })

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
        print('POST -> GO_TO: ', request.form)
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

    if 'username' not in session:
        logger.warning("Get span data without active session")
        return jsonify({"error": "No active session"}), 401

    username = session['username']
    logger.debug(f"Username: {username}")

    # Get the original text for this instance
    try:
        # Get the text from the item state manager
        item_state_manager = get_item_state_manager()
        instance = item_state_manager.get_item(instance_id)
        if not instance:
            logger.error(f"Instance not found: {instance_id}")
            return jsonify({"error": "Instance not found"}), 404

        original_text = instance.get_text()
        logger.debug(f"Original text: {original_text[:100]}...")
    except Exception as e:
        logger.error(f"Error getting instance text: {e}")
        return jsonify({"error": f"Instance not found: {instance_id}"}), 404

    # Get span annotations
    spans = get_span_annotations_for_user_on(username, instance_id)
    logger.debug(f"Found {len(spans)} spans")

    # Convert to frontend-friendly format
    span_data = []
    for span in spans:
        # Get color for this span
        color = get_span_color(span.get_schema(), span.get_name())
        hex_color = None
        if color:
            # Convert RGB format to hex
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

        span_info = {
            'id': span.get_id(),
            'schema': span.get_schema(),
            'label': span.get_name(),
            'title': span.get_title(),
            'start': span.get_start(),
            'end': span.get_end(),
            'text': original_text[span.get_start():span.get_end()],
            'color': hex_color
        }
        span_data.append(span_info)
        logger.debug(f"Span data: {span_info}")

    response_data = {
        'instance_id': instance_id,
        'text': original_text,
        'spans': span_data
    }

    logger.debug(f"=== GET_SPAN_DATA END ===")
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

                    span = SpanAnnotation(schema_name, sv["name"], sv.get("title", sv["name"]), start_offset, end_offset)
                    value = sv["value"]

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

                    # Always add the span annotation, regardless of whether value is None
                    user_state.add_span_annotation(instance_id, span, value)
                    logger.debug(f"Added span annotation: {span} with value: {value}")

                    # If value is None, also handle span removal logic
                    if value is None:
                        if instance_id in user_state.instance_id_to_span_to_value:
                            spans_to_remove = []
                            for existing_span in user_state.instance_id_to_span_to_value[instance_id]:
                                if (existing_span.get_schema() == span.get_schema() and
                                    existing_span.get_name() == span.get_name() and
                                    existing_span.get_start() == span.get_start() and
                                    existing_span.get_end() == span.get_end()):
                                    spans_to_remove.append(existing_span)
                            for span_to_remove in spans_to_remove:
                                del user_state.instance_id_to_span_to_value[instance_id][span_to_remove]
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
        print('POSTSTUDY: POST: ', request.form)

        # Advance the state and move to the appropriate next phase
        usm = get_user_state_manager()
        usm.advance_phase(session['username'])
        request.method = 'GET'
        return home()

    # Show the current poststudy page
    else:
        # Get the page the user is currently on
        phase, page = user_state.get_current_phase_and_page()
        print('POSTSTUDY GET: phase, page: ', phase, page)

        usm = get_user_state_manager()
        # Look up the html template for the current page
        html_fname = usm.get_phase_html_fname(phase, page)
        # Render the page
        return render_template(html_fname)

@app.route("/done", methods=["GET", "POST"])
def done():
    """
    Handle the done phase of the annotation process.

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

    # Show the completion page
    return render_template("done.html",
                          title=config.get("annotation_task_name", "Annotation Platform"),
                          completion_code=config.get("completion_code", ""))

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

    if not config.get("debug", False) and api_key != "admin_api_key":
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
                    if schema.get('type') == 'span' or schema.get('annotation_type') == 'highlight':
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
                print(f"🔍 Found {spans_before} spans for instance {instance_id}")

                # Clear the spans
                del user_state.instance_id_to_span_to_value[instance_id]
                logger.debug(f"Cleared {spans_before} spans for instance {instance_id}")
                print(f"🔍 Cleared {spans_before} spans for instance {instance_id}")

                return jsonify({
                    "status": "success",
                    "message": f"Cleared {spans_before} span annotations for instance {instance_id}",
                    "spans_cleared": spans_before
                })
            else:
                logger.debug(f"No spans found for instance {instance_id}")
                print(f"🔍 No spans found for instance {instance_id}")
                return jsonify({
                    "status": "success",
                    "message": f"No span annotations found for instance {instance_id}",
                    "spans_cleared": 0
                })
        else:
            logger.debug("User state has no span annotations")
            print(f"🔍 User state has no span annotations")
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
        app.secret_key = config.get("secret_key", "potato-annotation-platform")
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
    app.add_url_rule("/annotate", "annotate", annotate, methods=["GET", "POST"])
    app.add_url_rule("/go_to", "go_to", go_to, methods=["GET", "POST"])
    app.add_url_rule("/updateinstance", "update_instance", update_instance, methods=["POST"])
    app.add_url_rule("/poststudy", "poststudy", poststudy, methods=["GET", "POST"])
    app.add_url_rule("/done", "done", done, methods=["GET", "POST"])
    app.add_url_rule("/admin", "admin", admin, methods=["GET"])
    app.add_url_rule("/get_ai_hint", "get_ai_hint", get_ai_hint, methods=["GET"])
    app.add_url_rule("/api-frontend", "api_frontend", api_frontend, methods=["GET"])
    app.add_url_rule("/span-api-frontend", "span_api_frontend", span_api_frontend, methods=["GET"])
    app.add_url_rule("/api/spans/<instance_id>", "get_span_data", get_span_data, methods=["GET"])
    app.add_url_rule("/api/colors", "get_span_colors", get_span_colors, methods=["GET"])
    app.add_url_rule("/test-span-colors", "test_span_colors", test_span_colors, methods=["GET"])
    app.add_url_rule("/api/spans/<instance_id>/clear", "clear_span_annotations", clear_span_annotations, methods=["POST"])
    app.add_url_rule("/api/current_instance", "get_current_instance", get_current_instance, methods=["GET"])

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
    print('[DEBUG] Shutting down server via /shutdown')
    func()
    return jsonify({'status': 'Server shutting down...'})


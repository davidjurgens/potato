"""
Flask Routes Module

This module contains all the route handlers for the Flask server.
It defines the HTTP endpoints and their associated logic for:
- User authentication
- Navigation between annotation phases
- Form handling
- Annotation submission
- User registration
"""
from __future__ import annotations

import json
import logging
import datetime
from datetime import timedelta
from flask import Flask, session, render_template, request, redirect, url_for, jsonify, make_response

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
        return render_template("home.html", title=config.get("annotation_task_name", "Annotation Platform"))

    user_id = session['username']
    logger.debug(f"Active session for user: {user_id}")

    user_state = get_user_state(user_id)
    if user_state is None:
        logger.warning(f"User {user_id} not found in user state")
        session.clear()
        return redirect(url_for("auth"))

    # Get the phase of the user
    phase = user_state.get_phase()
    logger.debug(f"User phase: {phase}")

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

    Returns:
        flask.Response: Rendered template or redirect
    """
    # Check if user is already logged in
    if 'username' in session and get_user_state_manager().has_user(session['username']):
        logger.debug(f"User {session['username']} already logged in, redirecting to annotate")
        return redirect(url_for("annotate"))

    # For standard user_id/password login
    if request.method == "POST":
        user_id = request.form.get("email")
        password = request.form.get("pass")

        logger.debug(f"Login attempt for user: {user_id}")

        if not user_id:
            logger.warning("Login attempt with empty user_id")
            return render_template("home.html",
                                  login_error="User ID is required",
                                  title=config.get("annotation_task_name", "Annotation Platform"))

        # Authenticate the user
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
        span_info = {
            'id': span.get_id(),
            'schema': span.get_schema(),
            'label': span.get_name(),
            'title': span.get_title(),
            'start': span.get_start(),
            'end': span.get_end(),
            'text': original_text[span.get_start():span.get_end()]
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
    """
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
        schema_name = request.json.get("schema")
        schema_state = request.json.get("state")
        annotation_type = request.json.get("type")
        username = session['username']
        user_state = get_user_state(username)
        if not user_state:
            logger.error(f"User state not found for user: {username}")
            return jsonify({"status": "error", "message": "User state not found"})

        if annotation_type == "span":
            for sv in schema_state:
                span = SpanAnnotation(schema_name, sv["name"], sv.get("title", sv["name"]), int(sv["start"]), int(sv["end"]))
                value = sv["value"]
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
                else:
                    if instance_id not in user_state.instance_id_to_span_to_value:
                        user_state.instance_id_to_span_to_value[instance_id] = {}
                    user_state.add_span_annotation(instance_id, span, value)
        elif annotation_type == "label":
            for sv in schema_state:
                label = Label(schema_name, sv["name"])
                value = sv["value"]
                user_state.add_label_annotation(instance_id, label, value)
        # Save state
        get_user_state_manager().save_user_state(user_state)
        return jsonify({"status": "success"})
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
    num_annotations = get_total_annotations()
    context = {
        "total_annotations": num_annotations,
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

@app.route("/api/colors")
def get_span_colors():
    """
    Return the span color mapping for all schemas/labels as JSON.
    """
    # Try to get annotation scheme from config
    color_map = {}
    annotation_scheme = config.get('annotation_scheme') or config.get('annotation_schemes')
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
    # Fallback: provide all expected keys
    if not color_map:
        default_colors = {
            'positive': '#d4edda',
            'negative': '#f8d7da',
            'neutral': '#d1ecf1',
            'mixed': '#fff3cd',
            'happy': '#FFE6E6',
            'sad': '#E6F3FF',
            'angry': '#FFE6CC',
            'surprised': '#E6FFE6',
        }
        color_map = {
            'sentiment': default_colors,
            'entity': default_colors,
            'topic': default_colors,
        }
    return jsonify(color_map)


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

    app.add_url_rule("/admin/user_state/<user_id>", "admin_user_state", admin_user_state, methods=["GET"])
    app.add_url_rule("/admin/health", "admin_health", admin_health, methods=["GET"])
    app.add_url_rule("/admin/system_state", "admin_system_state", admin_system_state, methods=["GET"])
    app.add_url_rule("/admin/all_instances", "admin_all_instances", admin_all_instances, methods=["GET"])
    app.add_url_rule("/admin/item_state", "admin_item_state", admin_item_state, methods=["GET"])
    app.add_url_rule("/admin/item_state/<item_id>", "admin_item_state_detail", admin_item_state_detail, methods=["GET"])
    app.add_url_rule("/shutdown", "shutdown", shutdown, methods=["POST"])

@app.route('/shutdown', methods=['POST'])
def shutdown():
    func = request.environ.get('werkzeug.server.shutdown')
    if func is None:
        return jsonify({'error': 'Not running with the Werkzeug Server'}), 500
    print('[DEBUG] Shutting down server via /shutdown')
    func()
    return jsonify({'status': 'Server shutting down...'})


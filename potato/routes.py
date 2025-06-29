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
from datetime import timedelta
from flask import Flask, session, render_template, request, redirect, url_for, jsonify, make_response

# Import from the main flask_server.py module
from flask_server import (
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
        return redirect(url_for("auth"))

    username = session['username']
    logger.debug(f"Active session for user: {username}")

    user_state = get_user_state(username)
    if user_state is None:
        logger.warning(f"User {username} not found in user state")
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
    if 'username' in session and get_user_state_manager().has_user(session['username']):
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
                usm = get_user_state_manager()
                usm.add_user(username)
                usm.advance_phase(username)
                request.method = 'GET'
                return home()
            return redirect(url_for("home"))
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

    # Check if user is logged in
    if 'username' not in session:
        logger.warning("Unauthorized access attempt to annotate page")
        return redirect(url_for("home"))

    username = session['username']
    # Ensure user state exists
    if not get_user_state_manager().has_user(username):
        logger.info(f"Creating missing user state for {username}")
        init_user_state(username)

    logger.debug("Handling annotation request")

    user_state = get_user_state(username)
    # logger.info(vars(user_state))
    logger.debug(f"Retrieved state for user: {username}")

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
    
    if request.is_json and 'action' in request.json:
       print(f"request.json: {request.json}")
       action = request.json['action']
    else:
       print(f"request.form: {request.form}")
       action = request.form['action'] if 'action' in request.form else "init"
    
     # Process any annotation updates if they were submitted
    if request.method == 'POST' and request.json and 'instance_id' in request.json:
        if action == "prev_instance" or action == "next_instance" or action == "go_to":
            update_annotation_state(username, request.json)

    if action == "prev_instance":
        move_to_prev_instance(username)
    elif action == "next_instance":
        move_to_next_instance(username)
    elif action == "go_to":
        go_to_id(username, request.form.get("go_to"))
    else:
        logger.warning('unrecognized action request: "%s"' % action)


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

@app.route("/updateinstance", methods=["POST"])
def update_instance():
    '''
    API endpoint for updating instance data when a user interacts with the web UI.
    '''
    if 'username' not in session:
        return jsonify({"status": "error", "message": "No active session"})

    if request.is_json:
        print("updateinstance request.json: ", request.json)

        # Get the instance id
        instance_id = request.json.get("instance_id")

        # Get the schema name
        schema_name = request.json.get("schema")

        # Get the state of items for that schema
        schema_state = request.json.get("state")

        username = session['username']
        user_state = get_user_state(username)

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

        # Save these new instance labels
        get_user_state_manager().save_user_state(user_state)

    return jsonify({"status": "success"})

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
    app.secret_key = config.get("secret_key", "potato-annotation-platform")
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
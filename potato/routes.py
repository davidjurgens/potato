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

    # Check if debug mode is enabled and bypass authentication
    if config.get("debug", False):
        logger.debug("Debug mode enabled, bypassing authentication")

        # Create debug user if not exists
        debug_user_id = "debug_user"
        if not get_user_state_manager().has_user(debug_user_id):
            logger.debug(f"Creating debug user: {debug_user_id}")
            usm = get_user_state_manager()
            usm.add_user(debug_user_id)

            # Set debug user directly to annotation phase
            user_state = usm.get_user_state(debug_user_id)
            # Set phase directly to annotation instead of advancing through all phases
            user_state.advance_to_phase(UserPhase.ANNOTATION, None)
            logger.debug(f"Debug user phase set directly to: {user_state.get_phase()}")

            # Assign instances if needed
            if not user_state.has_assignments():
                # Create some test data for the debug user
                ism = get_item_state_manager()
                # Check if there are any items available
                try:
                    items = ism.items()
                    if not items:
                        # Create a test item if no items exist
                        from potato.item_state_management import Item
                        test_item = Item("test_1", {"id": "test_1", "text": "This is a test item for debugging."})
                        ism.add_item("test_1", {
                            "id": "test_1",
                            "text": "This is a test item for debugging.",
                            "displayed_text": "This is a test item for debugging."
                        })
                except Exception as e:
                    logger.warning(f"Could not check/create test items: {e}")

                # Assign instances to the debug user
                ism.assign_instances_to_user(user_state)

        # Set session for debug user
        session['user_id'] = debug_user_id
        session.permanent = True
        logger.info(f"Debug mode: auto-logged in as {debug_user_id}")

    if 'user_id' not in session:
        logger.debug("No active session, rendering login page")
        return redirect(url_for("auth"))

    user_id = session['user_id']
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
    if 'user_id' in session and get_user_state_manager().has_user(session['user_id']):
        logger.debug(f"User {session['user_id']} already logged in, redirecting to annotate")
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
            session['user_id'] = user_id
            session.permanent = True  # Make session persist longer
            logger.info(f"Login successful for user: {user_id}")


            # Initialize user state if needed
            if not get_user_state_manager().has_user(user_id):
                logger.debug(f"Initializing state for new user: {user_id}")
                usm = get_user_state_manager()
                usm.add_user(user_id)
                usm.advance_phase(user_id)
                request.method = 'GET'
                return home()
            return redirect(url_for("home"))
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

    print(f"[DEBUG] /submit_annotation: id(get_user_state_manager())={id(get_user_state_manager())}")
    print(f"[DEBUG] /submit_annotation: user IDs in manager: {get_user_state_manager().get_user_ids()}")
    print(f"[DEBUG] /submit_annotation: session user_id = {session.get('user_id', 'NOT_SET')}")

    if 'user_id' not in session and not config.get("debug", False):
        logger.warning("Annotation submission without active session")
        return jsonify({"status": "error", "message": "No active session"})

    # In debug mode, ensure we have a user_id
    if config.get("debug", False) and 'user_id' not in session:
        session['user_id'] = "debug_user"

    user_id = session['user_id']
    instance_id = request.form.get("instance_id")
    annotation_data = request.form.get("annotation_data")

    logger.debug(f"Annotation from {user_id} for instance {instance_id}")

    if not instance_id or not annotation_data:
        logger.warning("Missing instance_id or annotation_data")
        return jsonify({"status": "error", "message": "Missing required data"})

    try:
        # Parse the annotation data
        annotations = json.loads(annotation_data)
        user_state = get_user_state(user_id)

        # Process the annotations
        validate_annotation(instance_id, annotations, user_state)

        # Save the user state
        get_user_state_manager().save_user_state(user_state)

        logger.info(f"Successfully saved annotation for {instance_id} from {user_id}")
        return jsonify({"status": "success", "message": "Annotation saved successfully"})

    except Exception as e:
        logger.error(f"Error saving annotation: {str(e)}")
        return jsonify({"status": "error", "message": f"Failed to save annotation: {str(e)}"})

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
    if 'username' not in session and not config.get("debug", False):
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
    if 'username' not in session and not config.get("debug", False):
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
    if 'username' not in session and not config.get("debug", False):
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

    # Check if user is logged in (skip in debug mode)
    if 'username' not in session and not config.get("debug", False):
        logger.warning("Unauthorized access attempt to annotate page")
        return redirect(url_for("home"))

    # In debug mode, ensure debug user exists
    if config.get("debug", False):
        debug_username = "debug_user"
        if not get_user_state_manager().has_user(debug_username):
            logger.debug(f"Creating debug user: {debug_username}")
            usm = get_user_state_manager()
            usm.add_user(debug_username)

            # Set debug user directly to annotation phase
            user_state = usm.get_user_state(debug_username)
            while user_state.get_phase() != UserPhase.ANNOTATION:
                usm.advance_phase(debug_username)
                user_state = usm.get_user_state(debug_username)

            # Assign instances if needed
            if not user_state.has_assignments():
                get_item_state_manager().assign_instances_to_user(user_state)

        session['username'] = debug_username
        session.permanent = True

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
    if 'username' not in session and not config.get("debug", False):
        return home()

    # In debug mode, ensure we have a username
    if config.get("debug", False) and 'username' not in session:
        session['username'] = "debug_user"

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


# Test routes for exposing system state
@app.route("/test/health", methods=["GET"])
def test_health():
    """
    Health check endpoint for testing server status.

    Returns:
        flask.Response: JSON response with server status
    """
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


@app.route("/test/system_state", methods=["GET"])
def test_system_state():
    """
    Get overall system state including user and item statistics.

    Returns:
        flask.Response: JSON response with system state
    """
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


@app.route("/test/all_instances", methods=["GET"])
def test_all_instances():
    """
    Get all available instances for navigation purposes.

    Returns:
        flask.Response: JSON response with all instances
    """
    if not config.get("debug", False):
        return jsonify({
            "error": "All instances endpoint only available in debug mode"
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


@app.route("/test/user_state/<user_id>", methods=["GET"])
def test_user_state(user_id):
    """
    Get detailed state for a specific user.

    Args:
        user_id: The user ID to get state for

    Returns:
        flask.Response: JSON response with user state
    """
    try:
        usm = get_user_state_manager()
        user_state = usm.get_user_state(user_id)

        if not user_state:
            return jsonify({
                "error": f"User '{user_id}' not found"
            }), 404

        # Get current instance
        current_instance = user_state.get_current_instance()
        current_instance_data = None
        if current_instance:
            current_instance_data = {
                "id": current_instance.get_id(),
                "text": current_instance.get_text(),
                "displayed_text": current_instance.get_displayed_text()
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


@app.route("/test/item_state", methods=["GET"])
def test_item_state():
    """
    Get state for all items in the system.

    Returns:
        flask.Response: JSON response with item state
    """
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


@app.route("/test/item_state/<item_id>", methods=["GET"])
def test_item_state_detail(item_id):
    """
    Get detailed state for a specific item.

    Args:
        item_id: The item ID to get state for

    Returns:
        flask.Response: JSON response with item state
    """
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


@app.route("/test/reset", methods=["POST"])
def test_reset():
    """
    Reset the system state (for testing purposes only).

    Returns:
        flask.Response: JSON response with reset status
    """
    print("[DEBUG] /test/reset called")
    if not config.get("debug", False):
        print("[DEBUG] Debug mode not enabled")
        return jsonify({
            "error": "Reset only available in debug mode"
        }), 403

    print("[DEBUG] Debug mode is enabled, proceeding with reset")
    try:
        print("[DEBUG] Getting user state manager...")
        usm = get_user_state_manager()
        print("[DEBUG] Getting item state manager...")
        ism = get_item_state_manager()

        print(f"[DEBUG] Before reset: user count = {len(usm.get_user_ids())}, item count = {len(ism.get_instance_ids())}")
        # Clear all state
        print("[DEBUG] Clearing user state...")
        usm.clear()
        print("[DEBUG] Clearing item state...")
        ism.clear()
        print(f"[DEBUG] After reset: user count = {len(usm.get_user_ids())}, item count = {len(ism.get_instance_ids())}")

        return jsonify({
            "status": "reset_complete",
            "message": "All user and item state has been cleared"
        })
    except Exception as e:
        print(f"[DEBUG] Exception in /test/reset: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "error": f"Failed to reset system: {str(e)}"
        }), 500


@app.route("/test/create_user", methods=["POST"])
def test_create_user():
    """
    Create a test user (for testing purposes only).

    This route is only available when debug mode is enabled.
    It allows programmatic creation of users for testing scenarios.

    Request Body:
        {
            "user_id": "test_user_name",
            "initial_phase": "ANNOTATION" (optional),
            "assign_items": true (optional)
        }

    Returns:
        flask.Response: JSON response with user creation status
    """
    # Security check: Only available in debug mode
    if not config.get("debug", False):
        return jsonify({
            "error": "User creation only available in debug mode",
            "debug_mode_required": True
        }), 403

    try:
        data = request.get_json()
        if not data or 'user_id' not in data:
            return jsonify({
                "error": "Missing user_id in request",
                "required_fields": ["user_id"],
                "optional_fields": ["initial_phase", "assign_items"]
            }), 400

        user_id = data['user_id']
        initial_phase = data.get('initial_phase', None)
        assign_items = data.get('assign_items', False)

        # Validate user_id format
        if not isinstance(user_id, str) or len(user_id.strip()) == 0:
            return jsonify({
                "error": "user_id must be a non-empty string"
            }), 400

        user_id = user_id.strip()

        # Validate initial phase if provided
        valid_phases = ['LOGIN', 'CONSENT', 'PRESTUDY', 'INSTRUCTIONS', 'TRAINING', 'ANNOTATION', 'POSTSTUDY', 'DONE']
        if initial_phase and initial_phase.upper() not in valid_phases:
            return jsonify({
                "error": f"Invalid initial phase: {initial_phase}",
                "valid_phases": valid_phases
            }), 400

        usm = get_user_state_manager()

        # Check if user already exists
        if usm.has_user(user_id):
            return jsonify({
                "error": f"User '{user_id}' already exists",
                "user_id": user_id,
                "status": "exists"
            }), 409

        # Create the user
        usm.add_user(user_id)
        user_state = usm.get_user_state(user_id)

        # Set initial phase if specified
        if initial_phase:
            from potato.flask_server import UserPhase
            # Convert to uppercase for mapping, but accept both cases
            phase_upper = initial_phase.upper()
            phase_mapping = {
                'LOGIN': UserPhase.LOGIN,
                'CONSENT': UserPhase.CONSENT,
                'PRESTUDY': UserPhase.PRESTUDY,
                'INSTRUCTIONS': UserPhase.INSTRUCTIONS,
                'TRAINING': UserPhase.TRAINING,
                'ANNOTATION': UserPhase.ANNOTATION,
                'POSTSTUDY': UserPhase.POSTSTUDY,
                'DONE': UserPhase.DONE
            }
            if phase_upper not in phase_mapping:
                return jsonify({
                    "error": f"Invalid initial phase: {initial_phase}",
                    "valid_phases": list(phase_mapping.keys())
                }), 400
            user_state.advance_to_phase(phase_mapping[phase_upper], None)

        # Assign items if requested
        if assign_items:
            ism = get_item_state_manager()
            ism.assign_instances_to_user(user_state)

        return jsonify({
            "status": "created",
            "user_id": user_id,
            "initial_phase": initial_phase or "LOGIN",
            "assign_items": assign_items,
            "message": f"User '{user_id}' created successfully",
            "user_state": {
                "phase": str(user_state.get_phase()),
                "has_assignments": user_state.has_assignments(),
                "assignments_count": len(user_state.get_assigned_instance_ids()) if user_state.has_assignments() else 0
            }
        })
    except Exception as e:
        return jsonify({
            "error": f"Failed to create user: {str(e)}",
            "user_id": data.get('user_id') if 'data' in locals() else None
        }), 500


@app.route("/test/create_users", methods=["POST"])
def test_create_users():
    """
    Create multiple test users (for testing purposes only).

    This route is only available when debug mode is enabled.
    It allows programmatic creation of multiple users for testing scenarios.

    Request Body:
        {
            "users": [
                {
                    "user_id": "user_1",
                    "initial_phase": "ANNOTATION" (optional),
                    "assign_items": true (optional)
                },
                {
                    "user_id": "user_2",
                    "initial_phase": "CONSENT" (optional),
                    "assign_items": false (optional)
                }
            ]
        }

    Returns:
        flask.Response: JSON response with user creation status
    """
    # Security check: Only available in debug mode
    if not config.get("debug", False):
        return jsonify({
            "error": "User creation only available in debug mode",
            "debug_mode_required": True
        }), 403

    try:
        data = request.get_json()
        if not data or 'users' not in data:
            return jsonify({
                "error": "Missing users array in request",
                "required_fields": ["users"],
                "example": {
                    "users": [
                        {"user_id": "user_1", "initial_phase": "ANNOTATION"},
                        {"user_id": "user_2", "initial_phase": "CONSENT"}
                    ]
                }
            }), 400

        users_data = data['users']
        if not isinstance(users_data, list):
            return jsonify({
                "error": "users must be an array"
            }), 400

        usm = get_user_state_manager()
        results = {
            "created": [],
            "already_exists": [],
            "failed": []
        }

        for user_data in users_data:
            try:
                if not isinstance(user_data, dict) or 'user_id' not in user_data:
                    results["failed"].append({
                        "data": user_data,
                        "error": "Invalid user data format - missing user_id"
                    })
                    continue

                user_id = user_data['user_id']
                initial_phase = user_data.get('initial_phase', None)
                assign_items = user_data.get('assign_items', False)

                # Validate user_id
                if not isinstance(user_id, str) or len(user_id.strip()) == 0:
                    results["failed"].append({
                        "user_id": user_id,
                        "error": "user_id must be a non-empty string"
                    })
                    continue

                user_id = user_id.strip()

                # Validate initial phase if provided
                valid_phases = ['LOGIN', 'CONSENT', 'PRESTUDY', 'INSTRUCTIONS', 'TRAINING', 'ANNOTATION', 'POSTSTUDY', 'DONE']
                if initial_phase and initial_phase.upper() not in valid_phases:
                    results["failed"].append({
                        "user_id": user_id,
                        "error": f"Invalid initial phase: {initial_phase}",
                        "valid_phases": valid_phases
                    })
                    continue

                # Check if user already exists
                if usm.has_user(user_id):
                    results["already_exists"].append({
                        "user_id": user_id,
                        "status": "exists"
                    })
                    continue

                # Create the user
                usm.add_user(user_id)
                user_state = usm.get_user_state(user_id)

                # Set initial phase if specified
                if initial_phase:
                    from potato.flask_server import UserPhase
                    # Convert to uppercase for mapping, but accept both cases
                    phase_upper = initial_phase.upper()
                    phase_mapping = {
                        'LOGIN': UserPhase.LOGIN,
                        'CONSENT': UserPhase.CONSENT,
                        'PRESTUDY': UserPhase.PRESTUDY,
                        'INSTRUCTIONS': UserPhase.INSTRUCTIONS,
                        'TRAINING': UserPhase.TRAINING,
                        'ANNOTATION': UserPhase.ANNOTATION,
                        'POSTSTUDY': UserPhase.POSTSTUDY,
                        'DONE': UserPhase.DONE
                    }
                    if phase_upper not in phase_mapping:
                        return jsonify({
                            "error": f"Invalid initial phase: {initial_phase}",
                            "valid_phases": list(phase_mapping.keys())
                        }), 400
                    user_state.advance_to_phase(phase_mapping[phase_upper], None)

                # Assign items if requested
                if assign_items:
                    ism = get_item_state_manager()
                    ism.assign_instances_to_user(user_state)

                results["created"].append({
                    "user_id": user_id,
                    "initial_phase": initial_phase or "LOGIN",
                    "assign_items": assign_items,
                    "user_state": {
                        "phase": str(user_state.get_phase()),
                        "has_assignments": user_state.has_assignments(),
                        "assignments_count": len(user_state.get_assigned_instance_ids()) if user_state.has_assignments() else 0
                    }
                })

            except Exception as e:
                results["failed"].append({
                    "user_id": user_data.get('user_id') if isinstance(user_data, dict) else "unknown",
                    "error": f"Failed to create user: {str(e)}"
                })

        return jsonify({
            "status": "completed",
            "summary": {
                "created": len(results["created"]),
                "already_exists": len(results["already_exists"]),
                "failed": len(results["failed"]),
                "total_requested": len(users_data)
            },
            "results": results
        })

    except Exception as e:
        return jsonify({
            "error": f"Failed to process user creation request: {str(e)}"
        }), 500


@app.route("/test/advance_user_phase/<user_id>", methods=["POST"])
def test_advance_user_phase(user_id):
    """
    Advance a user to the next phase (for testing purposes only).

    This route is only available when debug mode is enabled.
    It allows programmatic advancement of user phases for testing scenarios.

    Args:
        user_id (str): The ID of the user to advance

    Returns:
        flask.Response: JSON response with advancement status
    """
    # Security check: Only available in debug mode
    if not config.get("debug", False):
        return jsonify({
            "error": "Phase advancement only available in debug mode",
            "debug_mode_required": True
        }), 403

    try:
        usm = get_user_state_manager()

        # Check if user exists
        if not usm.has_user(user_id):
            return jsonify({
                "error": f"User '{user_id}' not found",
                "available_users": usm.get_user_ids()
            }), 404

        # Get current phase before advancement
        user_state = usm.get_user_state(user_id)
        current_phase_before = user_state.get_phase()

        # Advance the user's phase
        usm.advance_phase(user_id)

        # Get phase after advancement
        user_state = usm.get_user_state(user_id)
        current_phase_after = user_state.get_phase()

        return jsonify({
            "status": "advanced",
            "user_id": user_id,
            "previous_phase": str(current_phase_before),
            "current_phase": str(current_phase_after),
            "message": f"User '{user_id}' advanced from {current_phase_before} to {current_phase_after}"
        })

    except Exception as e:
        return jsonify({
            "error": f"Failed to advance user phase: {str(e)}",
            "user_id": user_id
        }), 500


@app.route("/go_to", methods=["GET", "POST"])
def go_to():
    """
    Handle requests to go to a specific instance.
    """
    if 'username' not in session and not config.get("debug", False):
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
    if 'username' not in session and not config.get("debug", False):
        return jsonify({"status": "error", "message": "No active session"})

    if request.is_json:
        print("updateinstance request.json: ", request.json)

        # Get the instance id
        instance_id = request.json.get("instance_id")

        # Get the schema name
        schema_name = request.json.get("schema")

        # Get the state of items for that schema
        schema_state = request.json.get("state")

        # In debug mode, ensure we have a username
        if config.get("debug", False) and 'username' not in session:
            session['username'] = "debug_user"

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
    if 'username' not in session and not config.get("debug", False):
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
    if 'username' not in session and not config.get("debug", False):
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

@app.route("/test/create_dataset", methods=["POST"])
def test_create_dataset():
    """
    Create a test dataset with specified items and configuration.

    Args:
        JSON payload with:
        - items: dict of item_id -> item_data
        - max_annotations_per_item: int (optional)
        - assignment_strategy: str (optional)

    Returns:
        flask.Response: JSON response with dataset creation status
    """
    if not config.get("debug", False):
        return jsonify({
            "error": "Dataset creation only available in debug mode"
        }), 403

    try:
        data = request.get_json()
        if not data:
            return jsonify({
                "error": "No JSON data provided"
            }), 400

        items = data.get("items", {})
        max_annotations_per_item = data.get("max_annotations_per_item", -1)
        assignment_strategy = data.get("assignment_strategy", "fixed_order")

        # Create new config with the specified parameters
        test_config = config.copy()
        test_config["max_annotations_per_item"] = max_annotations_per_item
        test_config["assignment_strategy"] = assignment_strategy

        # Initialize item state manager with new config
        from potato.item_state_management import init_item_state_manager, ITEM_STATE_MANAGER
        import potato.item_state_management
        potato.item_state_management.ITEM_STATE_MANAGER = None  # Reset singleton
        ism = init_item_state_manager(test_config)

        # Add items to the dataset
        ism.add_items(items)

        return jsonify({
            "status": "created",
            "summary": {
                "created": len(items),
                "max_annotations_per_item": max_annotations_per_item,
                "assignment_strategy": assignment_strategy
            },
            "items": list(items.keys())
        })
    except Exception as e:
        return jsonify({
            "error": f"Failed to create dataset: {str(e)}"
        }), 500


@app.route("/test/submit_annotation", methods=["POST"])
def test_submit_annotation():
    """
    Submit an annotation for testing purposes.

    Args:
        JSON payload with:
        - instance_id: str
        - annotations: dict of schema -> label_data
        - user_id: str (optional, defaults to debug_user)

    Returns:
        flask.Response: JSON response with annotation submission status
    """
    if not config.get("debug", False):
        return jsonify({
            "error": "Annotation submission only available in debug mode"
        }), 403

    try:
        data = request.get_json()
        print(f"🔍 test_submit_annotation received data: {data}")

        if not data:
            return jsonify({
                "error": "No JSON data provided"
            }), 400

        instance_id = data.get("instance_id")
        annotations = data.get("annotations", {})
        user_id = data.get("user_id", "debug_user")

        print(f"🔍 Processing annotation for instance {instance_id}, user {user_id}")
        print(f"🔍 Annotations structure: {annotations}")

        if not instance_id:
            return jsonify({
                "error": "instance_id is required"
            }), 400

        usm = get_user_state_manager()

        # Ensure user exists and is in annotation phase
        if not usm.has_user(user_id):
            usm.add_user(user_id)
            user_state = usm.get_user_state(user_id)
            user_state.advance_to_phase(UserPhase.ANNOTATION, None)
            print(f"🔍 Created new user {user_id} in annotation phase")
        else:
            user_state = usm.get_user_state(user_id)
            # Ensure user is in annotation phase
            if user_state.get_phase() != UserPhase.ANNOTATION:
                user_state.advance_to_phase(UserPhase.ANNOTATION, None)
                print(f"🔍 Advanced user {user_id} to annotation phase")

        # Submit annotations
        annotation_count = 0
        for schema_name, label_data in annotations.items():
            if isinstance(label_data, dict):
                for label_name, value in label_data.items():
                    label = Label(schema_name, label_name)
                    user_state.add_label_annotation(instance_id, label, value)
                    annotation_count += 1
                    print(f"🔍 Added label annotation: {schema_name}:{label_name} = {value}")
            elif isinstance(label_data, list):
                for label_item in label_data:
                    if isinstance(label_item, dict) and 'name' in label_item and 'value' in label_item:
                        label = Label(schema_name, label_item['name'])
                        user_state.add_label_annotation(instance_id, label, label_item['value'])
                        annotation_count += 1
                        print(f"🔍 Added label annotation: {schema_name}:{label_item['name']} = {label_item['value']}")

        # Register the annotator for this instance
        get_item_state_manager().register_annotator(instance_id, user_id)

        # Save user state
        usm.save_user_state(user_state)

        print(f"🔍 Successfully submitted {annotation_count} annotations for instance {instance_id} by user {user_id}")

        return jsonify({
            "status": "success",
            "user_id": user_id,
            "instance_id": instance_id,
            "annotations_submitted": annotation_count,
            "message": f"Successfully submitted {annotation_count} annotations for instance {instance_id}"
        })

    except Exception as e:
        print(f"🔍 Error in test_submit_annotation: {str(e)}")
        return jsonify({
            "error": f"Failed to submit annotation: {str(e)}",
            "user_id": data.get("user_id") if 'data' in locals() else None,
            "instance_id": data.get("instance_id") if 'data' in locals() else None
        }), 500


@app.route("/api-frontend", methods=["GET"])
def api_frontend():
    """
    Serve the API-based frontend interface.

    This route serves a modern single-page application that uses API calls
    to interact with the backend instead of server-side rendering.

    Returns:
        flask.Response: Rendered API frontend template
    """
    if 'username' not in session and not config.get("debug", False):
        return redirect(url_for("home"))

    # In debug mode, ensure debug user exists
    if config.get("debug", False):
        debug_username = "debug_user"
        if not get_user_state_manager().has_user(debug_username):
            logger.debug(f"Creating debug user: {debug_username}")
            usm = get_user_state_manager()
            usm.add_user(debug_username)

            # Set debug user directly to annotation phase
            user_state = usm.get_user_state(debug_username)
            while user_state.get_phase() != UserPhase.ANNOTATION:
                usm.advance_phase(debug_username)
                user_state = usm.get_user_state(debug_username)

            # Assign instances if needed
            if not user_state.has_assignments():
                get_item_state_manager().assign_instances_to_user(user_state)

        session['username'] = debug_username
        session.permanent = True

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
    if 'username' not in session and not config.get("debug", False):
        return redirect(url_for("home"))

    # In debug mode, ensure debug user exists
    if config.get("debug", False):
        debug_username = "debug_user"
        if not get_user_state_manager().has_user(debug_username):
            logger.debug(f"Creating debug user: {debug_username}")
            usm = get_user_state_manager()
            usm.add_user(debug_username)

            # Set debug user directly to annotation phase
            user_state = usm.get_user_state(debug_username)
            while user_state.get_phase() != UserPhase.ANNOTATION:
                usm.advance_phase(debug_username)
                user_state = usm.get_user_state(debug_username)

            # Assign instances if needed
            if not user_state.has_assignments():
                get_item_state_manager().assign_instances_to_user(user_state)

        session['username'] = debug_username
        session.permanent = True

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


@app.route("/test/assign_multiple_items/<username>", methods=["POST"])
def test_assign_multiple_items(username):
    """
    Test endpoint to assign multiple items to a user for testing navigation.
    Only available in debug mode.
    """
    if not config.get("debug", False):
        return jsonify({
            "error": "Multiple item assignment only available in debug mode"
        }), 403

    try:
        data = request.get_json() or {}
        item_ids = data.get("item_ids", ["1", "2", "3", "4", "5"])

        user_state = get_user_state(username)
        if not user_state:
            return jsonify({
                "error": f"User '{username}' not found"
            }), 404

        ism = get_item_state_manager()
        assigned_count = 0

        for item_id in item_ids:
            if ism.has_item(item_id) and not user_state.has_annotated(item_id):
                item = ism.get_item(item_id)
                user_state.assign_instance(item)
                assigned_count += 1

        return jsonify({
            "status": "success",
            "assigned_count": assigned_count,
            "item_ids": item_ids
        })

    except Exception as e:
        return jsonify({
            "error": f"Failed to assign items to '{username}': {str(e)}"
        }), 500


@app.route("/test/clear_annotations/<username>", methods=["POST"])
def test_clear_annotations(username):
    """
    Test endpoint to clear all annotations for a user.
    Only available in debug mode.
    """
    if not config.get("debug", False):
        return jsonify({
            "error": "Clear annotations only available in debug mode"
        }), 403

    try:
        user_state = get_user_state(username)
        if not user_state:
            return jsonify({
                "error": f"User '{username}' not found"
            }), 404

        print(f"🔍 CLEARING annotations for user '{username}'")
        print(f"🔍 Before clearing - Label annotations: {dict(user_state.instance_id_to_label_to_value)}")
        print(f"🔍 Before clearing - Span annotations: {dict(user_state.instance_id_to_span_to_value)}")

        # Clear all annotations
        user_state.clear_all_annotations()

        print(f"🔍 After clearing - Label annotations: {dict(user_state.instance_id_to_label_to_value)}")
        print(f"🔍 After clearing - Span annotations: {dict(user_state.instance_id_to_span_to_value)}")

        # Save the updated user state
        usm = get_user_state_manager()
        usm.save_user_state(user_state)

        print(f"🔍 Successfully cleared and saved annotations for user '{username}'")

        return jsonify({
            "status": "success",
            "message": f"Cleared all annotations for user '{username}'"
        })

    except Exception as e:
        print(f"🔍 Error clearing annotations for '{username}': {str(e)}")
        return jsonify({
            "error": f"Failed to clear annotations for '{username}': {str(e)}"
        }), 500


@app.route("/test/clear_debug_annotations", methods=["POST"])
def test_clear_debug_annotations():
    """
    Test endpoint to clear all annotations for the debug user.
    Only available in debug mode.
    """
    if not config.get("debug", False):
        return jsonify({
            "error": "Clear debug annotations only available in debug mode"
        }), 403

    try:
        username = "debug_user"
        user_state = get_user_state(username)

        if not user_state:
            return jsonify({
                "error": f"Debug user '{username}' not found"
            }), 404

        print(f"🔍 CLEARING DEBUG annotations for user '{username}'")
        print(f"🔍 Before clearing - Label annotations: {dict(user_state.instance_id_to_label_to_value)}")
        print(f"🔍 Before clearing - Span annotations: {dict(user_state.instance_id_to_span_to_value)}")

        # Clear all annotations
        user_state.clear_all_annotations()

        print(f"🔍 After clearing - Label annotations: {dict(user_state.instance_id_to_label_to_value)}")
        print(f"🔍 After clearing - Span annotations: {dict(user_state.instance_id_to_span_to_value)}")

        # Save the updated user state
        usm = get_user_state_manager()
        usm.save_user_state(user_state)

        print(f"🔍 Successfully cleared and saved debug annotations")

        return jsonify({
            "status": "success",
            "message": f"Cleared all annotations for debug user",
            "cleared_user": username
        })

    except Exception as e:
        print(f"🔍 Error clearing debug annotations: {str(e)}")
        return jsonify({
            "error": f"Failed to clear debug annotations: {str(e)}"
        }), 500


@app.route("/test/delete_span", methods=["POST"])
def test_delete_span():
    """
    Test endpoint to delete a specific span annotation.
    Only available in debug mode.

    Expected POST data:
        instance_id: ID of the instance
        span_key: The span annotation key to delete
        username: Username (optional, defaults to debug_user)

    Returns:
        flask.Response: JSON response with deletion status
    """
    if not config.get("debug", False):
        return jsonify({
            "error": "Delete span only available in debug mode"
        }), 403

    try:
        # Get request data
        data = request.get_json()
        if not data:
            data = request.form.to_dict()

        instance_id = data.get('instance_id')
        span_key = data.get('span_key')
        username = data.get('username', 'debug_user')

        print(f"🔍 Delete span request - instance: {instance_id}, span_key: {span_key}, user: {username}")

        if not instance_id or not span_key:
            return jsonify({
                "status": "error",
                "message": "Missing instance_id or span_key"
            }), 400

        # Get user state
        user_state = get_user_state(username)
        if not user_state:
            return jsonify({
                "error": f"User '{username}' not found"
            }), 404

        # Get span annotations for the user
        span_annotations = user_state.instance_id_to_span_to_value

        # Check if the instance has any span annotations
        if instance_id not in span_annotations:
            print(f"🔍 No span annotations found for instance {instance_id}")
            return jsonify({
                "status": "success",
                "message": "Instance has no span annotations",
                "instance_id": instance_id
            })

        instance_spans = span_annotations[instance_id]
        print(f"🔍 Current spans for instance {instance_id}: {list(str(span) for span in instance_spans.keys())}")

        # Find the matching span annotation object
        span_to_delete = None
        for span_obj, span_value in instance_spans.items():
            if str(span_obj) == span_key and span_value == 'true':
                span_to_delete = span_obj
                break

        if span_to_delete:
            # Delete the span
            del instance_spans[span_to_delete]
            print(f"🔍 Deleted span: {span_to_delete}")

            # If no spans left for this instance, remove the instance entry
            if not instance_spans:
                del span_annotations[instance_id]
                print(f"🔍 Removed empty instance {instance_id} from span annotations")

            # Save the changes
            usm = get_user_state_manager()
            usm.save_user_state(user_state)

            print("🔍 Successfully deleted span and saved changes")

            return jsonify({
                "status": "success",
                "message": f"Deleted span annotation",
                "instance_id": instance_id,
                "span_key": span_key,
                "username": username
            })
        else:
            print(f"🔍 Span not found: {span_key}")
            return jsonify({
                "status": "error",
                "message": "Span not found",
                "instance_id": instance_id,
                "span_key": span_key
            }), 404

    except Exception as e:
        print(f"🔍 Error deleting span: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Error deleting span: {str(e)}"
        }), 500


@app.route("/test/set_debug_session", methods=["POST"])
def test_set_debug_session():
    """
    Set the debug session for testing purposes.

    Args:
        JSON payload with:
        - user_id: str

    Returns:
        flask.Response: JSON response with session status
    """
    if not config.get("debug", False):
        return jsonify({
            "error": "Debug session setting only available in debug mode"
        }), 403

    try:
        data = request.get_json()
        if not data or 'user_id' not in data:
            return jsonify({
                "error": "Missing user_id in request",
                "required_fields": ["user_id"]
            }), 400

        user_id = data['user_id']

        # Validate user_id
        if not isinstance(user_id, str) or len(user_id.strip()) == 0:
            return jsonify({
                "error": "user_id must be a non-empty string"
            }), 400

        user_id = user_id.strip()

        # Check if user exists
        usm = get_user_state_manager()
        if not usm.has_user(user_id):
            return jsonify({
                "error": f"User '{user_id}' not found",
                "user_id": user_id
            }), 404

        # Set the session
        session['user_id'] = user_id
        session.permanent = True

        return jsonify({
            "status": "success",
            "user_id": user_id,
            "message": f"Debug session set for user '{user_id}'"
        })

    except Exception as e:
        return jsonify({
            "error": f"Failed to set debug session: {str(e)}",
            "user_id": data.get('user_id') if 'data' in locals() else None
        }), 500


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
    app.add_url_rule("/api-frontend", "api_frontend", api_frontend, methods=["GET"])
    app.add_url_rule("/span-api-frontend", "span_api_frontend", span_api_frontend, methods=["GET"])
    app.add_url_rule("/test/assign_multiple_items/<username>", "test_assign_multiple_items", test_assign_multiple_items, methods=["POST"])
    app.add_url_rule("/test/clear_annotations/<username>", "test_clear_annotations", test_clear_annotations, methods=["POST"])
    app.add_url_rule("/test/clear_debug_annotations", "test_clear_debug_annotations", test_clear_debug_annotations, methods=["POST"])
    app.add_url_rule("/test/delete_span", "test_delete_span", test_delete_span, methods=["POST"])
    app.add_url_rule("/test/set_debug_session", "test_set_debug_session", test_set_debug_session, methods=["POST"])

    # Test routes for debugging and testing
    app.add_url_rule("/test/health", "test_health", test_health, methods=["GET"])
    app.add_url_rule("/test/system_state", "test_system_state", test_system_state, methods=["GET"])
    app.add_url_rule("/test/all_instances", "test_all_instances", test_all_instances, methods=["GET"])
    app.add_url_rule("/test/user_state/<user_id>", "test_user_state", test_user_state, methods=["GET"])
    app.add_url_rule("/test/item_state", "test_item_state", test_item_state, methods=["GET"])
    app.add_url_rule("/test/item_state/<item_id>", "test_item_state_detail", test_item_state_detail, methods=["GET"])
    app.add_url_rule("/test/reset", "test_reset", test_reset, methods=["POST"])
    app.add_url_rule("/test/create_user", "test_create_user", test_create_user, methods=["POST"])
    app.add_url_rule("/test/create_users", "test_create_users", test_create_users, methods=["POST"])
    app.add_url_rule("/test/advance_user_phase/<user_id>", "test_advance_user_phase", test_advance_user_phase, methods=["POST"])
    app.add_url_rule("/test/create_dataset", "test_create_dataset", test_create_dataset, methods=["POST"])
    app.add_url_rule("/test/submit_annotation", "test_submit_annotation", test_submit_annotation, methods=["POST"])

@app.route('/shutdown', methods=['POST'])
def shutdown():
    if not config.get('debug', False):
        return jsonify({'error': 'Shutdown only available in debug mode'}), 403
    func = request.environ.get('werkzeug.server.shutdown')
    if func is None:
        return jsonify({'error': 'Not running with the Werkzeug Server'}), 500
    print('[DEBUG] Shutting down server via /shutdown')
    func()
    return jsonify({'status': 'Server shutting down...'})
"""
Main Flask app
"""

import os
from flask import Flask, render_template, request
from potato.db import db

from potato.db_utils.models.user import User
from potato.db_utils.models.user_annotation_state import UserAnnotationState

from potato.db_utils.user_manager import UserManager
from potato.db_utils.user_annotation_state_manager import UserAnnotationStateManager
from potato.constants import POTATO_HOME


def create_app(config):
    """ App factory """
    app = Flask(__name__)

    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(POTATO_HOME, config["db_path"])
    db.init_app(app)

    with app.app_context():
        db.create_all()

        user_manager = UserManager(db)
        user_state_manager = UserAnnotationStateManager(db, config)

    return app, user_manager, user_state_manager

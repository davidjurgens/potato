"""
Main Flask app
"""

from flask import Flask, render_template, request
from potato.db import db
from potato.db_utils.models.users import User
from potato.db_utils.models.user_annotation_state import UserAnnotationState


def create_app(db_path):
    """ App factory """
    app = Flask(__name__)

    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + db_path
    db.init_app(app)

    with app.app_context():
        db.create_all()

    return app

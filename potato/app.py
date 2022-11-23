"""
Main Flask app
"""

import os
from flask import Flask, render_template, request
from potato.db import db

app = Flask(__name__)

basedir = os.path.abspath(os.path.dirname(__file__))
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(
    basedir, "database.db"
)

db.init_app(app)

from potato.db_utils.models import User

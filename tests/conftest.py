import pytest
import sys
import os
# Import test setup for Flask app, config, managers, and routes
import tests.flask_test_setup
from potato.flask_server import app as flask_app

@pytest.fixture(scope="session")
def app():
    flask_app.config["TESTING"] = True
    flask_app.config["debug"] = True
    yield flask_app

@pytest.fixture(scope="function")
def client(app):
    return app.test_client()
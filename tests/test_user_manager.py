"""
Testcases for UserAnnotationStateManager
"""

import os
import shutil
import yaml
from potato.app import create_app, db
from potato.db_utils.user_manager import UserManager
from potato.db_utils.models.user import User
from potato.constants import POTATO_HOME


PROJECT_DIR = os.path.join(POTATO_HOME, "tests/test_project")

# Use an initial DB state for all tests.
# This database has been initialized with user and annotation data
# in tests/test_project/user_config.json and
# tests/test_project/annotation_output/.
INIT_DB_PATH = os.path.join(PROJECT_DIR, "initial_database.db")



class TestUserManager:
    @classmethod
    def setup_class(cls):
        """
        setup config.
        """
        config_filepath = os.path.join(PROJECT_DIR, "config.yaml")
        with open(config_filepath, "r") as file_p:
            config = yaml.safe_load(file_p)

        cls.db_path = os.path.join(POTATO_HOME, config["db_path"])
        shutil.copy(INIT_DB_PATH, cls.db_path)
        cls.app = create_app(cls.db_path)
        cls.user_manager = UserManager(db)

    @classmethod
    def teardown_class(cls):
        """
        tear down test instance.
        """
        os.remove(cls.db_path)

    def test_initial_state(self):
        """
        Verify initial DB state.
        """
        with self.app.app_context():
            users = User.query.all()
            assert len(users) == 1

            user = users[0]
            assert user.username == "zxcv@zxcv.com"
            assert user.email == "zxcv@zxcv.com"

    def test_add_user(self):
        """
        Test adding a new user.
        """
        new_username = "test_user_2"
        with self.app.app_context():

            self.user_manager.add_single_user({
                "username": new_username,
                "email": "z@z.com",
                "password": "zxcv"
            })

            users = User.query.all()
            assert len(users) == 2

            new_user = users[-1]
            assert new_user.username == new_username
            assert new_user.email == "z@z.com"
            assert new_user.password == "zxcv"

    def test_validation_methods(self):
        """
        Test is_valid_username(), is_valid_password(), is_valid_user().
        """
        with self.app.app_context():

            assert self.user_manager.username_is_available("available") is True
            assert self.user_manager.username_is_available("zxcv@zxcv.com") is False
            assert self.user_manager.username_is_available("test_user_2") is False

            assert self.user_manager.is_valid_password("test_user_2", "zxcv") is True
            assert self.user_manager.is_valid_password("test_user_2", "asdf") is False

            assert self.user_manager.is_valid_user("zxcv@zxcv.com") is True
            self.user_manager.set_allow_all_users(False)
            assert self.user_manager.is_valid_user("zxcv@zxcv.com") is True
            assert self.user_manager.is_valid_user("invalid") is False

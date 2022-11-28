"""
Unit tests for each end point.
"""

import os
import json
import shutil
import yaml
import pytest
from potato.app import create_app, db
from potato.flask_server import (
    app, user_state_manager,
    generate_site,
    load_all_data,
    config,
)
from potato.constants import POTATO_HOME

PROJECT_DIR = os.path.join(POTATO_HOME, "tests/test_project")

# Use an initial DB state for all tests.
# This database has been initialized with user and annotation data
# in tests/test_project/user_config.json and
# tests/test_project/annotation_output/.
INIT_DB_PATH = os.path.join(PROJECT_DIR, "initial_database.db")


class TestServer:
    @classmethod
    def setup_class(cls):
        """
        Set up config.
        """
        cls.db_path = os.path.join(POTATO_HOME, config["db_path"])
        shutil.copy(INIT_DB_PATH, cls.db_path)

        generate_site(config)
        load_all_data(config)

        data_filepath = config["data_files"]
        cls.test_data = []
        for _filepath in data_filepath:
            with open(_filepath, "r") as file_p:
                for line in file_p:
                    _data = json.loads(line)
                    cls.test_data.append(_data)

    @classmethod
    def teardown_class(cls):
        """
        tear down test instance.
        """
        os.remove(cls.db_path)

    def test_failed_login(self):
        """
        Test case when user is not logged in -- the current logic
        seems to check this by checking whether an email is provided?
        """

        with app.test_client() as client:
            username = "zxcv@zxcv.com"
            response = client.post("/annotate", data={"username": username})
            assert (
                str.encode(
                    "Please login to annotate or you are using the wrong link"
                )
                in response.data
            )

    def test_annotate_render_simple(self):
        """
        Test the simplest case of rendering the /annotate endpoint,
        in which there is no action specified.
        """
        username = "zxcv@zxcv.com"
        with app.test_client() as client:
            response = client.post(
                "/annotate",
                data={
                    "username": username,
                    "email": username,
                },
            )

            test_data = self.test_data[1]
            for text in test_data["text"]:
                assert str.encode(text) in response.data

    def test_update_annotation_state(self):
        """
        Test updating user states.
        """
        username = "zxcv@zxcv.com"
        with app.app_context():
            curr_state = user_state_manager.get_user_state(username).get_all_annotations()
            assert len(curr_state) == 3

            html_tags_pre = (
                '<span class="span_container"'
                'selection_label="uncertain"'
                'style="background-color:rgb(60, 180, 75, 0.25);">'
            )

            span = "Tom: I am so sorry"

            html_tags_post = (
                '<div class="span_label" style="background-color:white;border:2px '
                'solid rgb(60, 180, 75);">uncertain</div></span>for that<br>Sam: '
                "No worries<br>Tom: thanks for your understanding"
            )

            form = {
                "email": username,
                "instance_id": 1,
                "sentiment:::negative": True,
                "span_label:::certainty:::uncertain": True,
                "span-annotation": "".join([html_tags_pre, span, html_tags_post]),
                "label": "",
                "src": "next_instance",
                "go_to": "",
            }
            user_state_manager.update_annotation_state(username, form)
            user_state = user_state_manager.get_user_state(username).get_all_annotations()
            assert len(user_state) == 3
            assert user_state["6"]["labels"]["sentiment"] == {"negative": "true"}
            assert user_state["6"]["spans"] == {}

            assert user_state["4"]["labels"]["sentiment"] == {"positive": "true"}
            assert user_state["4"]["spans"] == [
                    {"start": 0, "end": 13, "span": "C: Checkmate.", "annotation": "uncertain"},
            ]

            assert user_state["2"]["labels"]["sentiment"] == {"negative": True}
            assert user_state["2"]["spans"] == [
                {"start": 0, "end": 18, "span": span, "annotation": "uncertain"},
            ]

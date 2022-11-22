"""
Unit tests for each end point.
"""

import json
import pytest

from potato.server_utils.config_module import init_config, config
from potato.server_utils.messages import LOGIN_ERROR_MSG
from potato.flask_server import (
    app,
    generate_site,
    load_all_data,
    lookup_user_state,
    update_annotation_state,
)


@pytest.fixture
def client():
    with app.test_client() as client:
        yield client


class TestOne:
    @classmethod
    def setup_class(cls):
        """
        Set up config.
        """
        cls.username = "testuser@umich.edu"
        config_filepath = "tests/test_config.yaml"
        init_config(config_filepath)

        generate_site(config)
        load_all_data(config)

        data_filepath = config["data_files"]
        cls.test_data = []
        for _filepath in data_filepath:
            with open(_filepath, "r") as file_p:
                for line in file_p:
                    _data = json.loads(line)
                    cls.test_data.append(_data)

    def test_failed_login(self, client):
        """
        Test case when user is not logged in -- the current logic
        seems to check this by checking whether an email is provided?
        """
        response = client.post("/annotate", data={"username": self.username})
        assert str.encode(LOGIN_ERROR_MSG) in response.data

    def test_annotate_render_simple(self, client):
        """
        Test the simplest case of rendering the /annotate endpoint,
        in which there is no action specified.
        """
        response = client.post(
            "/annotate",
            data={
                "username": self.username,
                "email": "testuser@umich.edu",
            },
        )

        test_data = self.test_data[0]
        for text in test_data["text"]:
            assert str.encode(text) in response.data

    def test_update_annotation_state(self):
        """
        Test updating user states.
        """
        curr_state = lookup_user_state(self.username).get_all_annotations()
        assert len(curr_state) == 0

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
            "email": self.username,
            "instance_id": 0,
            "sentiment:::negative": True,
            "span_label:::certainty:::uncertain": True,
            "span-annotation": "".join([html_tags_pre, span, html_tags_post]),
            "label": "",
            "src": "next_instance",
            "go_to": "",
        }
        update_annotation_state(self.username, form)
        updated_state = lookup_user_state(self.username).get_all_annotations()
        assert len(updated_state) == 1
        assert updated_state["1"]["labels"]["sentiment"] == {"negative": True}
        assert updated_state["1"]["spans"] == [
            {"start": 0, "end": 18, "span": span, "annotation": "uncertain"},
        ]

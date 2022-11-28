"""
Testcases for UserAnnotationStateManager
"""

import os
import json
import shutil
import pytest
from collections import OrderedDict, defaultdict
import yaml
from potato.app import create_app, db
from potato.db_utils.models.user import User
from potato.db_utils.models.user_annotation_state import UserAnnotationState
from potato.server_utils.front_end import get_displayed_text
from potato.constants import POTATO_HOME
from potato import state


PROJECT_DIR = os.path.join(POTATO_HOME, "tests/test_project")

# Use an initial DB state for all tests.
# This database has been initialized with user and annotation data
# in tests/test_project/user_config.json and
# tests/test_project/annotation_output/.
INIT_DB_PATH = os.path.join(PROJECT_DIR, "initial_database.db")


def load_data(filepath):
    """
    Load data to annotate. Assumes a json filepath.
    """
    state.instance_id_to_data = OrderedDict()
    with open(filepath, "rt") as file_p:
        for _, line in enumerate(file_p):
            data_obj = json.loads(line)
            state.instance_id_to_data[data_obj["id"]] = data_obj
    return state.instance_id_to_data


class TestUserAnnotationStateManager:
    def setup_class(cls):
        """
        setup config.
        """
        config_filepath = os.path.join(PROJECT_DIR, "config.yaml")
        with open(config_filepath, "r") as file_p:
            config = yaml.safe_load(file_p)

        db_path = os.path.join(POTATO_HOME, config["db_path"])
        shutil.copy(INIT_DB_PATH, db_path)
        cls.app, cls.user_manager, cls.user_state_manager = create_app(config)
        cls.data = load_data(config["data_files"][0])

    def test_initial_state(self):
        """
        Test initial database state.
        """
        with self.app.app_context():
            users = User.query.all()
            user_states = UserAnnotationState.query.all()
            assert len(users) == 1
            assert len(user_states) == 1

            test_user = users[0]
            test_user_state = user_states[0]

            assert test_user.username == "zxcv@zxcv.com"
            assert test_user.email == "zxcv@zxcv.com"
            assert test_user.annotation_state == test_user_state

            assert test_user_state.instance_id_to_labeling == {
                "6": {"sentiment": {"negative": "true"}},
                "4": {"sentiment": {"positive": "true"}},
                "2": {"sentiment": {"positive": "true"}},
            }
            assert test_user_state.instance_id_to_span_annotations == {
                "6": {},
                "4": [
                    {
                        "start": 0,
                        "end": 13,
                        "span": "C: Checkmate.",
                        "annotation": "uncertain",
                    }
                ],
                "2": [
                    {
                        "start": 55,
                        "end": 85,
                        "span": "thanks for your understanding!",
                        "annotation": "uncertain",
                    }
                ],
            }
            assert test_user_state.instance_id_to_behavioral_data == {
                "6": {"time_string": "Time spent: 0d 0h 0m 2s "},
                "4": {"time_string": "Time spent: 0d 0h 0m 6s "},
                "2": {"time_string": "Time spent: 0d 0h 0m 4s "},
            }
            assert test_user_state.instance_id_ordering == [
                "1",
                "2",
                "3",
                "4",
                "5",
                "6",
            ]
            assert test_user_state.instance_id_to_order == {
                "1": 0,
                "2": 1,
                "3": 2,
                "4": 3,
                "5": 4,
                "6": 5,
            }
            assert test_user_state.instance_cursor == 1

    def test_get_user_state(self):
        """
        Test get_user_state()
        """
        username = "test_user_2"
        with self.app.app_context():
            # Add a new user.
            self.user_manager.add_single_user(
                {
                    "username": username,
                    "email": "z@z.com",
                    "password": "zxcv",
                }
            )
            users = User.query.all()
            assert len(users) == 2

            new_user = User.query.filter_by(username=username).first()
            assert new_user is not None
            assert new_user.username == username
            assert new_user.email == "z@z.com"
            assert new_user.password == "zxcv"
            assert new_user.annotation_state is None

            # Add user-state
            self.user_state_manager.get_user_state(new_user.username)
            all_user_states = UserAnnotationState.query.all()
            assert len(all_user_states) == 2

            new_user_state = UserAnnotationState.query.filter_by(
                username=username
            ).first()
            assert new_user.annotation_state == new_user_state
            assert new_user_state.instance_id_to_labeling == {}
            assert (
                new_user_state.instance_id_to_data == state.instance_id_to_data
            )

    def test_load_user_state(self):
        """
        Test load_user_state().
        """
        with self.app.app_context():
            old_user = "zxcv@zxcv.com"
            res = self.user_state_manager.load_user_state(old_user)
            assert res == "old user loaded"

            old_user_with_no_annotations = "test_user_2"
            res = self.user_state_manager.load_user_state(
                old_user_with_no_annotations
            )
            assert res == "old user loaded"
            user_state = UserAnnotationState.query.filter_by(
                username=old_user_with_no_annotations
            ).first()
            assert user_state.instance_id_to_labeling == {}
            assert user_state.instance_id_to_data == state.instance_id_to_data

            new_user = "test_user_3"
            res = self.user_state_manager.load_user_state(new_user)
            assert res == "new user initialized"
            user_state = UserAnnotationState.query.filter_by(
                username=new_user
            ).first()
            assert user_state.instance_id_to_labeling == {}
            assert user_state.instance_id_to_data == state.instance_id_to_data

    def test_update_annotation_state(self):
        """
        Test update_annotation_state()
        """
        username = "zxcv@zxcv.com"
        with self.app.app_context():
            # Test adding a new entry.
            form = {
                "email": username,
                "instance_id": 0,
                "sentiment:::negative": True,
            }

            self.user_state_manager.update_annotation_state(username, form)
            user_state = UserAnnotationState.query.filter_by(username=username).first()

            assert user_state.instance_id_to_labeling == {
                "6": {"sentiment": {"negative": "true"}},
                "4": {"sentiment": {"positive": "true"}},
                "2": {"sentiment": {"positive": "true"}},
                "1": {"sentiment": {"negative": True}},
            }
            assert user_state.instance_id_to_span_annotations == {
                "6": {},
                "4": [
                    {
                        "start": 0,
                        "end": 13,
                        "span": "C: Checkmate.",
                        "annotation": "uncertain",
                    }
                ],
                "2": [
                    {
                        "start": 55,
                        "end": 85,
                        "span": "thanks for your understanding!",
                        "annotation": "uncertain",
                    }
                ],
            }

            # Test updating label and span.
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
                "span-annotation": "".join(
                    [html_tags_pre, span, html_tags_post]
                ),
            }

            self.user_state_manager.update_annotation_state(username, form)
            user_state = UserAnnotationState.query.filter_by(username=username).first()

            assert user_state.instance_id_to_labeling == {
                "6": {"sentiment": {"negative": "true"}},
                "4": {"sentiment": {"positive": "true"}},
                "2": {"sentiment": {"negative": True}},
                "1": {"sentiment": {"negative": True}},
            }
            assert user_state.instance_id_to_span_annotations == {
                "6": {},
                "4": [
                    {
                        "start": 0,
                        "end": 13,
                        "span": "C: Checkmate.",
                        "annotation": "uncertain",
                    }
                ],
                "2": [
                    {
                        "start": 0,
                        "end": 18,
                        "span": span,
                        "annotation": "uncertain",
                    },
                ],
            }

            # Test removing annotations.
            form = {"email": username, "instance_id": 1}

            self.user_state_manager.update_annotation_state(username, form)
            user_state = UserAnnotationState.query.filter_by(username=username).first()

            assert user_state.instance_id_to_labeling == {
                "6": {"sentiment": {"negative": "true"}},
                "4": {"sentiment": {"positive": "true"}},
                "1": {"sentiment": {"negative": True}},
            }
            assert user_state.instance_id_to_span_annotations == {
                "6": {},
                "4": [
                    {
                        "start": 0,
                        "end": 13,
                        "span": "C: Checkmate.",
                        "annotation": "uncertain",
                    }
                ],
            }

    def test_get_total_annotations(self):
        """
        Test get_total_annotations()
        """
        # TODO: This function is kinda misleading. Is it meant to
        # return the total number of data points that have been annotated,
        # by either a label or a span?
        # Or does it consider labels and spans as separate annotations and
        # return the number of labels + spans? Ie, it's possible that
        # get_total_annotations() > # of data points?

        # For now I'm leaving this test as failing, for a couple of reasons:
        # 1) db_utils.models.user_annotation_state.get_annotation_count()
        # does not take into consideration the case when there are
        # different annotations for labels and spans.
        # ex: label: {"1": True, "2": False}, spans: {"1": [...]}
        # Then the total count of annotations should be 2 ("1" and "2").
        # However, it will currently return 3 ("1", "2", "1").
        # 2) Secondly, using the same example as above, there is no
        # span annotation for instance "2". However, when dumping data
        # to file, these missing holes are filled in.
        # (see db_utils.models.user_annotation_state.get_all_annotations())
        # Therefore in the annotations file, the span annotations will show
        # up as {"1": [...], "2": []}. Because these files were used to
        # initialize our test db, these holes will show up in our db, which
        # should not be counted towards the total annotation count.
        with self.app.app_context():
            count = self.user_state_manager.get_total_annotations()
            assert count == 3

    def test_get_annotations_for_user_on(self):
        """
        Test get_annotations_for_user_on(), get_span_annotations_for_user_on()
        """
        username = "zxcv@zxcv.com"
        with self.app.app_context():
            label = self.user_state_manager.get_annotations_for_user_on(
                username, "1"
            )
            assert label == {"sentiment": {"negative": True}}

            label = self.user_state_manager.get_annotations_for_user_on(
                username, "2"
            )
            assert label is None

            label = self.user_state_manager.get_annotations_for_user_on(
                username, "4"
            )
            assert label == {"sentiment": {"positive": "true"}}

            span_label = (
                self.user_state_manager.get_span_annotations_for_user_on(
                    username, "1"
                )
            )
            assert span_label is None
            span_label = (
                self.user_state_manager.get_span_annotations_for_user_on(
                    username, "4"
                )
            )
            assert span_label == [
                {
                    "start": 0,
                    "end": 13,
                    "span": "C: Checkmate.",
                    "annotation": "uncertain",
                }
            ]

    def test_cursor(self):
        """
        Test move_to_prev_instance(), move_to_next_instance(), go_to_id()
        """
        username = "zxcv@zxcv.com"
        with self.app.app_context():
            user_state = self.user_state_manager.get_user_state(username)
            assert user_state.instance_cursor == 1
            self.user_state_manager.move_to_prev_instance(username)
            assert user_state.instance_cursor == 0
            self.user_state_manager.move_to_prev_instance(username)
            assert user_state.instance_cursor == 0
            self.user_state_manager.move_to_next_instance(username)
            assert user_state.instance_cursor == 1
            self.user_state_manager.go_to_id(username, 5)
            assert user_state.instance_cursor == 5
            self.user_state_manager.move_to_next_instance(username)
            assert user_state.instance_cursor == 5
            self.user_state_manager.move_to_prev_instance(username)
            assert user_state.instance_cursor == 4
            self.user_state_manager.go_to_id(username, 999)
            assert user_state.instance_cursor == 4


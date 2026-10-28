"""
A finished `/agent_chat` conversation belongs to the annotator who had it.

`/agent_chat/finish` used to write the transcript into the shared item's
in-memory data. Two consequences, both covered here:

1. A second annotator assigned the same item was shown the first annotator's
   finished conversation instead of a fresh chat panel.
2. Nothing persisted the transcript, so it was gone after a restart and never
   reached an export.

Two users, one item, the echo proxy (no network), and a second server started
on the same task directory to stand in for a restart.
"""

import json
import os

import pytest
import requests
import yaml

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.port_manager import find_free_port
from tests.helpers.test_utils import create_test_directory


A_TEXT = "alpha-only message about the Lisbon booking"
B_TEXT = "bravo-only message about the Oslo booking"


def _write_config(test_dir):
    abs_dir = os.path.abspath(test_dir)
    data = [{"id": "chat_item_1", "task_description": "Book a trip.",
             "conversation": None}]
    with open(os.path.join(abs_dir, "data.json"), "w") as f:
        json.dump(data, f)
    config = {
        "annotation_task_name": "Agent Chat Transcript Isolation",
        "task_dir": abs_dir,
        "data_files": ["data.json"],
        "item_properties": {"id_key": "id", "text_key": "task_description"},
        "annotation_schemes": [{
            "name": "task_success", "annotation_type": "radio",
            "labels": ["success", "failure"], "description": "Did it work?",
        }],
        "assignment_strategy": "fixed_order",
        "max_annotations_per_item": -1,
        "output_annotation_dir": os.path.join(abs_dir, "output"),
        "site_dir": "default",
        "alert_time_each_instance": 0,
        "require_password": False,
        "authentication": {"method": "in_memory"},
        "persist_sessions": False,
        "debug": False,
        "secret_key": "test-secret",
        "user_config": {"allow_all_users": True, "users": []},
        "agent_proxy": {
            "type": "echo",
            "responses": ["Echo reply one", "Echo reply two"],
            "sandbox": {"max_steps": 10, "max_session_seconds": 600,
                        "request_timeout_seconds": 10,
                        "rate_limit_per_minute": 60},
        },
        "instance_display": {
            "layout": {"direction": "vertical"},
            "fields": [
                {"key": "task_description", "type": "text", "label": "Task"},
                {"key": "conversation", "type": "interactive_chat",
                 "label": "Chat"},
            ],
        },
    }
    path = os.path.join(abs_dir, "config.yaml")
    with open(path, "w") as f:
        yaml.dump(config, f)
    return path


def _login(server, username):
    s = requests.Session()
    s.post(f"{server.base_url}/register",
           data={"email": username, "pass": "pw"}, timeout=5)
    s.post(f"{server.base_url}/auth",
           data={"email": username, "pass": "pw"}, timeout=5)
    return s


def _start(config_path):
    server = FlaskTestServer(port=find_free_port(), config_file=config_path)
    if not server.start():
        pytest.fail("Failed to start Flask test server")
    return server


class TestAgentChatTranscriptIsolation:

    def test_transcript_is_per_user_and_survives_restart(self):
        test_dir = create_test_directory("agent_chat_transcript_isolation")
        config_path = _write_config(test_dir)

        server = _start(config_path)
        try:
            a = _login(server, "chat_user_a")
            b = _login(server, "chat_user_b")
            page_a = a.get(f"{server.base_url}/annotate", timeout=5).text
            assert "agent-chat-panel" in page_a

            r = a.post(f"{server.base_url}/agent_chat/send",
                       json={"message": A_TEXT}, timeout=10)
            assert r.status_code == 200, r.text
            r = a.post(f"{server.base_url}/agent_chat/finish", json={},
                       timeout=10)
            assert r.status_code == 200, r.text

            # A sees their own finished conversation.
            page_a = a.get(f"{server.base_url}/annotate", timeout=5).text
            assert A_TEXT in page_a
            assert "agent-chat-panel" not in page_a

            # B is on the same item and must get a fresh panel, with none of
            # A's conversation anywhere on the page.
            page_b = b.get(f"{server.base_url}/annotate", timeout=5).text
            assert 'data-instance-id="chat_item_1"' in page_b or \
                "chat_item_1" in page_b
            assert "agent-chat-panel" in page_b, (
                "second annotator was shown a finished conversation instead "
                "of a fresh chat panel")
            assert A_TEXT not in page_b, (
                "another annotator's conversation leaked onto the page")

            # B can chat and finish independently; A's view is unchanged.
            r = b.post(f"{server.base_url}/agent_chat/send",
                       json={"message": B_TEXT}, timeout=10)
            assert r.status_code == 200, r.text
            r = b.post(f"{server.base_url}/agent_chat/finish", json={},
                       timeout=10)
            assert r.status_code == 200, r.text
            page_b = b.get(f"{server.base_url}/annotate", timeout=5).text
            assert B_TEXT in page_b and A_TEXT not in page_b
            page_a = a.get(f"{server.base_url}/annotate", timeout=5).text
            assert A_TEXT in page_a and B_TEXT not in page_a
        finally:
            server.stop()

        # Restart: a new server on the same task directory. In-memory items
        # and agent sessions are rebuilt from scratch.
        server = _start(config_path)
        try:
            a = _login(server, "chat_user_a")
            page_a = a.get(f"{server.base_url}/annotate", timeout=5).text
            assert A_TEXT in page_a, (
                "the finished transcript did not survive a restart")
            assert "agent-chat-panel" not in page_a
            assert B_TEXT not in page_a

            # The finished chat cannot be restarted (and overwritten) just
            # because the in-memory session went away with the old server.
            r = a.post(f"{server.base_url}/agent_chat/send",
                       json={"message": "a second chat"}, timeout=10)
            assert r.status_code == 400
            page_a = a.get(f"{server.base_url}/annotate", timeout=5).text
            assert A_TEXT in page_a and "a second chat" not in page_a

            # A user who never chatted on this item still gets a panel.
            c = _login(server, "chat_user_c")
            page_c = c.get(f"{server.base_url}/annotate", timeout=5).text
            assert "agent-chat-panel" in page_c
            assert A_TEXT not in page_c and B_TEXT not in page_c
        finally:
            server.stop()

from pathlib import Path

from bs4 import BeautifulSoup
from flask import Flask

import potato.flask_server as fs
from potato.item_state_management import Label
from potato.phase import UserPhase


def test_get_current_page_html_restores_saved_phase_answers(monkeypatch):
    template_dir = Path(__file__).resolve().parent / "phase_page_templates"
    app = Flask(__name__, template_folder=str(template_dir))
    app.secret_key = "test-secret"

    class StubUserState:
        def __init__(self):
            self.phase_to_page_to_label_to_value = {
                UserPhase.PRESTUDY: {
                    "survey_page": {
                        Label("radio_schema", "choice"): "yes",
                        Label("checkbox_schema", "selected"): True,
                        Label("text_schema", "comment"): "Saved text",
                        Label("number_schema", "count"): 7,
                        Label("textarea_schema", "notes"): "Saved notes",
                        Label("select_schema", "pick"): "b",
                    }
                }
            }

        def get_current_phase_and_page(self):
            return (UserPhase.PRESTUDY, "survey_page")

        def get_assigned_instance_count(self):
            return 0

    class StubUSM:
        def get_phase_html_fname(self, phase, page):
            return "survey_page.html"

    monkeypatch.setattr(fs, "app", app, raising=False)
    monkeypatch.setattr(fs, "get_user_state", lambda username: StubUserState())
    monkeypatch.setattr(fs, "get_user_state_manager", lambda: StubUSM())

    with app.test_request_context("/"):
        html = fs.get_current_page_html({"annotation_task_name": "Survey Test"}, "user1")

    soup = BeautifulSoup(html, "html.parser")

    assert soup.find("input", {"name": "radio_schema:::choice", "value": "yes"}).has_attr("checked")
    assert soup.find("input", {"name": "checkbox_schema:::selected"}).has_attr("checked")
    assert soup.find("input", {"name": "text_schema:::comment"})["value"] == "Saved text"
    assert soup.find("input", {"name": "number_schema:::count"})["value"] == "7"
    assert soup.find("textarea", {"name": "textarea_schema:::notes"}).text == "Saved notes"
    assert soup.find("select", {"name": "select_schema:::pick"}).find("option", {"value": "b"}).has_attr("selected")

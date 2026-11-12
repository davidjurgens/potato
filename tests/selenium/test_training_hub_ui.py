"""The run page's "Publish to the Hugging Face Hub" form, in a browser.

Real typing and clicks against a stand-in Hub (FakeHub): a mismatched
confirmation is caught on the page, a push shows its result and, after a
reload, its place in the history. Keyboard submit and phone width too.
"""

import json
import os
import time

import pytest
import yaml
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import cleanup_test_directory, create_test_directory
from tests.unit.test_training_hub import FakeHub

KEY = "hub-ui-key"
FAKE = FakeHub()


@pytest.fixture(scope="module")
def server():
    pytest.importorskip("huggingface_hub")
    test_dir = create_test_directory("training_hub_ui")
    data_path = os.path.join(test_dir, "items.json")
    with open(data_path, "w") as f:
        f.write(json.dumps({"id": "h0", "text": "item"}) + "\n")
    config = {
        "port": 8000, "server_name": "test",
        "annotation_task_name": "training hub ui", "task_dir": test_dir,
        "output_annotation_dir": os.path.join(test_dir, "output"),
        "data_files": [data_path],
        "item_properties": {"id_key": "id", "text_key": "text"},
        "user_config": {"allow_all_users": True, "users": []},
        "site_dir": "default", "admin_api_key": KEY,
        "annotation_schemes": [{"annotation_type": "radio", "name": "sentiment",
                                "description": "?", "labels": ["pos", "neg"]}],
        "model_training": {"enabled": True},
    }
    path = os.path.join(test_dir, "config.yaml")
    with open(path, "w") as f:
        yaml.safe_dump(config, f)
    srv = FlaskTestServer(config_file=path)
    if not srv.start():
        cleanup_test_directory(test_dir)
        pytest.fail("Failed to start server")
    from potato.training import hub, store
    from potato.training.manager import get_training_manager
    store.record_run(config, store.TrainingRun(
        run_id="run-ui", trainer="sklearn-text", schema_names=["sentiment"],
        status="success", n_train=6, n_val=1, n_test=1))
    artifacts = os.path.join(get_training_manager().run_dir("run-ui"), "artifacts")
    os.makedirs(artifacts, exist_ok=True)
    with open(os.path.join(artifacts, "model.pkl"), "wb") as fh:
        fh.write(b"model")
    saved = hub._default_api
    hub._default_api = lambda token: FAKE
    os.environ["HF_TOKEN"] = "hf_ui_test"
    yield srv
    hub._default_api = saved
    os.environ.pop("HF_TOKEN", None)
    srv.stop()
    cleanup_test_directory(test_dir)


@pytest.fixture(scope="module")
def driver(server):
    options = webdriver.ChromeOptions()
    for arg in ("--headless=new", "--no-sandbox", "--window-size=1280,900"):
        options.add_argument(arg)
    d = webdriver.Chrome(options=options)
    d.get(server.base_url + "/admin")
    box = d.find_element(By.CSS_SELECTOR, "input[type=password]")
    box.send_keys(KEY)
    box.submit()
    time.sleep(1)
    yield d
    d.quit()


def _fill(driver, repo, confirm):
    for field, value in (("hub-repo", repo), ("hub-confirm", confirm)):
        box = driver.find_element(By.ID, field)
        box.clear()
        box.send_keys(value)


def _result(driver, predicate):
    WebDriverWait(driver, 10).until(
        lambda d: predicate(d.find_element(By.ID, "hub-result").text))
    return driver.find_element(By.ID, "hub-result").text


def test_a_mismatched_confirmation_is_caught_on_the_page(driver, server):
    driver.get(server.base_url + "/admin/training/runs/run-ui")
    _fill(driver, "lab/model", "lab/modle")
    driver.find_element(By.ID, "hub-btn").click()
    assert _result(driver, bool) == "The two repository names differ."
    assert driver.switch_to.active_element.get_attribute("id") == "hub-confirm"
    assert FAKE.commits == []


def test_a_push_shows_its_result_and_then_its_history(driver, server):
    driver.get(server.base_url + "/admin/training/runs/run-ui")
    assert driver.find_element(By.ID, "hub-private").is_selected()
    _fill(driver, "lab/model", "lab/model")
    driver.find_element(By.ID, "hub-btn").click()
    text = _result(driver, lambda t: t.startswith("Pushed"))
    assert text.startswith("Pushed 2 files to lab/model.")
    assert FAKE.commits[-1]["repo_id"] == "lab/model"
    assert FAKE.created[-1] == ("lab/model", True)
    driver.get(server.base_url + "/admin/training/runs/run-ui")
    history = driver.find_element(By.ID, "hub-pushes").text
    assert "lab/model (private, commit abc123def4" in history


def test_the_form_submits_from_the_keyboard(driver, server):
    driver.get(server.base_url + "/admin/training/runs/run-ui")
    _fill(driver, "lab/keys", "lab/keys")
    driver.find_element(By.ID, "hub-confirm").send_keys(Keys.ENTER)
    assert _result(driver, lambda t: t.startswith("Pushed")).startswith(
        "Pushed 2 files to lab/keys.")


def test_the_run_page_fits_a_phone(driver, server):
    driver.set_window_size(390, 844)
    try:
        driver.get(server.base_url + "/admin/training/runs/run-ui")
        overflow = driver.execute_script(
            "return document.documentElement.scrollWidth - "
            "document.documentElement.clientWidth")
        assert overflow <= 0
        assert driver.find_element(By.ID, "hub-btn").is_displayed()
    finally:
        driver.set_window_size(1280, 900)

"""
The admin Training page in a browser.

The "running" badge stayed on the page after a run had finished, and on a
page where no run had started: `.tr-live { display: flex }` beat the `hidden`
attribute, and so did the shared button styles: Cancel showed with no run and
Check on the local backend. The Parameters box suggested `{"lora": true}` to every trainer,
including ones that refuse it.
"""

import json
import os
import time

import pytest
import yaml
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import cleanup_test_directory, create_test_directory

KEY = "training-ui-key"


@pytest.fixture(scope="module")
def server():
    test_dir = create_test_directory("training_page_ui")
    data_path = os.path.join(test_dir, "items.json")
    with open(data_path, "w") as f:
        for i in range(4):
            f.write(json.dumps({"id": "t%d" % i, "text": "item %d" % i}) + "\n")
    config = {
        "port": 8000, "server_name": "test",
        "annotation_task_name": "training page ui", "task_dir": test_dir,
        "output_annotation_dir": os.path.join(test_dir, "output"),
        "data_files": [data_path],
        "item_properties": {"id_key": "id", "text_key": "text"},
        "user_config": {"allow_all_users": True, "users": []},
        "site_dir": "default", "admin_api_key": KEY,
        "annotation_schemes": [{"annotation_type": "radio", "name": "sentiment",
                                "description": "Sentiment?",
                                "labels": ["positive", "negative"]}],
        "model_training": {"enabled": True},
    }
    path = os.path.join(test_dir, "config.yaml")
    with open(path, "w") as f:
        yaml.safe_dump(config, f)
    srv = FlaskTestServer(config_file=path)
    if not srv.start():
        cleanup_test_directory(test_dir)
        pytest.fail("Failed to start server")
    yield srv
    srv.stop()
    cleanup_test_directory(test_dir)


@pytest.fixture(scope="module")
def page(server):
    options = webdriver.ChromeOptions()
    for arg in ("--headless=new", "--no-sandbox", "--window-size=1280,900"):
        options.add_argument(arg)
    driver = webdriver.Chrome(options=options)
    driver.get(server.base_url + "/admin")
    box = driver.find_element(By.CSS_SELECTOR, "input[type=password]")
    box.send_keys(KEY)
    box.submit()
    time.sleep(1)
    driver.get(server.base_url + "/admin/training")
    time.sleep(1.5)
    yield driver
    driver.quit()


def test_no_running_badge_without_a_run(page):
    live = page.find_element(By.ID, "live")
    assert not live.is_displayed()
    assert page.execute_script(
        "return getComputedStyle(document.getElementById('live')).display") == "none"


def test_cancel_and_check_hidden_with_no_run_on_the_local_backend(page):
    assert Select(page.find_element(By.ID, "backend-select")) \
        .first_selected_option.get_attribute("value") == "local"
    assert not page.find_element(By.ID, "cancel-btn").is_displayed()
    assert not page.find_element(By.ID, "check-btn").is_displayed()
    assert page.find_element(By.ID, "start-btn").is_displayed()


def test_the_placeholder_names_a_parameter_the_trainer_takes(page):
    select = Select(page.find_element(By.ID, "trainer-select"))
    box = page.find_element(By.ID, "params-input")
    seen = 0
    for option in select.options:
        if not option.is_enabled():
            continue
        select.select_by_value(option.get_attribute("value"))
        takes = [n.strip() for n in
                 (option.get_attribute("data-params") or "").split(",") if n.strip()]
        placeholder = box.get_attribute("placeholder")
        if takes:
            assert placeholder.startswith('{"%s"' % takes[0]), (option.text, placeholder)
            seen += 1
        else:
            assert placeholder == "{}"
    assert seen >= 1

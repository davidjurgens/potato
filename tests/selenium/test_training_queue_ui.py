"""The Training page with a run in flight: a remote run still waiting in a
scheduler's queue shows as live, and Train now queues another run, which
the Runs table lists with its place and a Cancel button.

Before, "queued" (a remote run waiting for its agent or a SLURM node) was
not treated as in flight: no live badge, no Cancel, and the page stopped
polling at once. Real clicks; the outcome is read back from the server.
"""

import json
import os
import time

import pytest
import yaml
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import cleanup_test_directory, create_test_directory

KEY = "training-queue-ui-key"


@pytest.fixture(scope="module")
def server():
    test_dir = create_test_directory("training_queue_ui")
    data_path = os.path.join(test_dir, "items.json")
    with open(data_path, "w") as f:
        for i in range(4):
            f.write(json.dumps({"id": "t%d" % i, "text": "item %d" % i}) + "\n")
    config = {
        "port": 8000, "server_name": "test",
        "annotation_task_name": "training queue ui", "task_dir": test_dir,
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


@pytest.fixture
def in_flight(server):
    from potato.training.manager import get_training_manager
    manager = get_training_manager()
    manager._set(state="queued", run_id="remote-run",
                 step="SLURM job 4242: PENDING (Priority)")
    yield manager
    manager._set(state="idle", step="")
    for run in manager.waiting_runs():
        manager.cancel(run.run_id)


def test_a_run_waiting_for_a_node_shows_as_live(driver, server, in_flight):
    driver.get(server.base_url + "/admin/training")
    WebDriverWait(driver, 10).until(
        lambda d: d.find_element(By.ID, "live").is_displayed())
    assert driver.find_element(By.ID, "live-state").text == "queued"
    assert driver.find_element(By.ID, "live-step").text == \
        "SLURM job 4242: PENDING (Priority)"
    assert driver.find_element(By.ID, "cancel-btn").is_displayed()
    # Still polling: a step change shows without a reload.
    in_flight._set(step="SLURM job 4242: RUNNING on sushi")
    WebDriverWait(driver, 10).until(
        lambda d: d.find_element(By.ID, "live-step").text.endswith("on sushi"))


def test_train_now_queues_and_the_queued_run_can_be_cancelled(driver, server,
                                                              in_flight):
    driver.get(server.base_url + "/admin/training")
    start = driver.find_element(By.ID, "start-btn")
    assert start.is_enabled()
    start.click()
    WebDriverWait(driver, 10).until(
        lambda d: "number 1 in the queue" in d.find_element(By.ID, "start-status").text)
    (waiting,) = in_flight.waiting_runs()

    # The page reloads; the run is in the table with its place.
    button = WebDriverWait(driver, 10).until(
        lambda d: d.find_element(
            By.CSS_SELECTOR, '.tr-unqueue[data-run="%s"]' % waiting.run_id))
    row = button.find_element(By.XPATH, "./ancestor::tr")
    assert "waiting #1" in row.text
    button.click()
    WebDriverWait(driver, 10).until(
        lambda d: not d.find_elements(By.CSS_SELECTOR, ".tr-unqueue"))
    from potato.training import store
    assert store.load_run(in_flight.config, waiting.run_id).status == "cancelled"


def test_the_runs_table_fits_a_phone_with_a_waiting_run(driver, server, in_flight):
    in_flight.start_run("sklearn-text", ["sentiment"])
    driver.set_window_size(390, 844)
    try:
        driver.get(server.base_url + "/admin/training")
        overflow = driver.execute_script(
            "return document.documentElement.scrollWidth - "
            "document.documentElement.clientWidth")
        assert overflow <= 0
    finally:
        driver.set_window_size(1280, 900)


def test_no_console_errors_and_the_cancel_button_takes_keyboard_focus(
        driver, server, in_flight):
    from selenium.webdriver.common.keys import Keys
    outcome = in_flight.start_run("sklearn-text", ["sentiment"])
    driver.get(server.base_url + "/admin/training")
    time.sleep(1)
    # Admin pages have no favicon; that 404 is not this page's.
    errors = [e for e in driver.get_log("browser") if e["level"] == "SEVERE"
              and "favicon.ico" not in e["message"]]
    assert errors == []
    button = driver.find_element(
        By.CSS_SELECTOR, '.tr-unqueue[data-run="%s"]' % outcome["run_id"])
    body = driver.find_element(By.TAG_NAME, "body")
    for _ in range(40):
        if driver.switch_to.active_element == button:
            break
        body.send_keys(Keys.TAB) if driver.switch_to.active_element.tag_name == "body" \
            else driver.switch_to.active_element.send_keys(Keys.TAB)
    assert driver.switch_to.active_element == button
    button.send_keys(Keys.ENTER)
    WebDriverWait(driver, 10).until(
        lambda d: not d.find_elements(By.CSS_SELECTOR, ".tr-unqueue"))

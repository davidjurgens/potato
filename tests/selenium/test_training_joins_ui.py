"""The run page's "Keep this split as a dataset" form and the Catalog's
"Train on these" button, in a browser.

Real clicks, then the result checked on the server: the dataset version
exists with the run's val items, and the slice's refusal is shown rather than
swallowed. Plus the phone-width check for the new form.
"""

import json
import os
import time

import pytest
import yaml
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import Select, WebDriverWait

from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import cleanup_test_directory, create_test_directory

KEY = "training-joins-ui-key"
IDS = ["r%02d" % i for i in range(10)]


@pytest.fixture(scope="module")
def server():
    test_dir = create_test_directory("training_joins_ui")
    data_path = os.path.join(test_dir, "items.json")
    with open(data_path, "w") as f:
        for iid in IDS:
            f.write(json.dumps({"id": iid, "text": "item %s" % iid}) + "\n")
    config = {
        "port": 8000, "server_name": "test",
        "annotation_task_name": "training joins ui", "task_dir": test_dir,
        "output_annotation_dir": os.path.join(test_dir, "output"),
        "data_files": [data_path],
        "item_properties": {"id_key": "id", "text_key": "text"},
        "user_config": {"allow_all_users": True, "users": []},
        "site_dir": "default", "admin_api_key": KEY,
        "annotation_schemes": [{"annotation_type": "radio", "name": "sentiment",
                                "description": "Sentiment?",
                                "labels": ["positive", "negative"]}],
        "model_training": {"enabled": True},
        "datasets": {"enabled": True},
        "curation": {"enabled": True},
    }
    path = os.path.join(test_dir, "config.yaml")
    with open(path, "w") as f:
        yaml.safe_dump(config, f)
    srv = FlaskTestServer(config_file=path)
    if not srv.start():
        cleanup_test_directory(test_dir)
        pytest.fail("Failed to start server")

    from potato.training import store
    store.record_run(config, store.TrainingRun(
        run_id="run-ui", trainer="sklearn-text", schema_names=["sentiment"],
        status="success", created_at=1.0, finished_at=2.0,
        n_train=6, n_val=2, n_test=2))
    store.record_run_items(config, "run-ui", {"train": IDS[:6],
                                              "val": IDS[6:8],
                                              "test": IDS[8:]})
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


def _text_when(driver, element_id, predicate, timeout=10):
    WebDriverWait(driver, timeout).until(
        lambda d: predicate(d.find_element(By.ID, element_id).text))
    return driver.find_element(By.ID, element_id).text


def test_saving_the_val_split_creates_a_dataset_version(driver, server):
    driver.get(server.base_url + "/admin/training/runs/run-ui")
    split = Select(driver.find_element(By.ID, "pin-split"))
    assert [o.text for o in split.options] == ["val (2 items)", "test (2 items)",
                                               "train (6 items)"]
    name = driver.find_element(By.ID, "pin-dataset")
    assert name.get_attribute("value") == "sentiment-heldout"
    name.clear()
    name.send_keys("ui-heldout")
    driver.find_element(By.ID, "pin-btn").click()
    text = _text_when(driver, "pin-result", lambda t: t.startswith("Saved"))
    assert text == "Saved 2 items as version v0001 of ui-heldout."

    from potato.eval_datasets.manager import get_datasets_manager
    examples = get_datasets_manager().store.list_examples("ui-heldout")
    assert sorted(e.id for e in examples) == IDS[6:8]


def test_the_form_submits_from_the_keyboard(driver, server):
    driver.get(server.base_url + "/admin/training/runs/run-ui")
    name = driver.find_element(By.ID, "pin-dataset")
    name.clear()
    name.send_keys("keyboard-heldout", Keys.ENTER)
    assert _text_when(driver, "pin-result", lambda t: t.startswith("Saved")) \
        .endswith("of keyboard-heldout.")


def test_the_run_page_fits_a_phone(driver, server):
    driver.set_window_size(390, 844)
    try:
        driver.get(server.base_url + "/admin/training/runs/run-ui")
        overflow = driver.execute_script(
            "return document.documentElement.scrollWidth - "
            "document.documentElement.clientWidth")
        assert overflow <= 0
        button = driver.find_element(By.ID, "pin-btn")
        assert button.is_displayed() and button.rect["x"] >= 0
    finally:
        driver.set_window_size(1280, 900)


def test_train_on_these_reports_why_nothing_was_pinned(driver, server):
    driver.get(server.base_url + "/admin/catalog")
    button = driver.find_element(
        By.CSS_SELECTOR, '.s-totrain[data-name="model-found-nothing"]')
    button.click()
    # The index was never built, so the built-in slice matches nothing, and
    # the page says so.
    text = _text_when(driver, "slice-status", lambda t: "matches no items" in t)
    assert "build the index" in text

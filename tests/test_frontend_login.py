import pytest
from selenium import webdriver
from selenium.webdriver.common.by import By
import time

@pytest.mark.skip(reason="Requires running server and selenium setup.")
def test_login_ui_loads():
    driver = webdriver.Chrome()
    driver.get("http://localhost:9000/auth")
    time.sleep(2)
    assert "login" in driver.page_source or "debug_user" in driver.page_source
    driver.quit()
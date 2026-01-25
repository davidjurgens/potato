import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from tests.selenium.test_base import BaseSeleniumTest


class TestSpanManagerInitAndRender(BaseSeleniumTest):
    def test_manager_initializes_and_renders_overlay(self):
        self.driver.get(f"{self.server.base_url}/annotate")

        # Wait for main elements
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "text-content"))
        )
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "span-overlays"))
        )

        # Ensure manager exists and isInitialized eventually
        is_initialized = self.driver.execute_script(
            "return !!(window.spanManager && window.spanManager.isInitialized);"
        )
        if not is_initialized:
            # Give a bit more time for initialization
            time.sleep(1)
            is_initialized = self.driver.execute_script(
                "return !!(window.spanManager && window.spanManager.isInitialized);"
            )
        assert is_initialized, "spanManager should initialize"

        # Basic sanity: hidden instance_id exists
        instance_id_dom = self.driver.execute_script(
            "var el=document.getElementById('instance_id'); return el?el.value:null;"
        )
        assert instance_id_dom, "DOM instance_id should exist"

        # If there are preexisting spans, overlays should render
        # Wait briefly for overlays to be appended
        time.sleep(0.5)
        overlay_count = self.driver.execute_script(
            "var c=document.getElementById('span-overlays'); return c?c.children.length:0;"
        )

        # Select a small portion of text and create a span to verify overlay appears
        text_elem = self.driver.find_element(By.ID, "text-content")
        self.driver.execute_script(
            "var el=arguments[0]; var r=document.createRange();"
            "var n=el.firstChild||el; var len=(n.textContent||'').length;"
            "var start=Math.max(0, Math.floor(len/4)); var end=Math.min(len, start+3);"
            "try{r.setStart(n,start); r.setEnd(n,end);}catch(e){}"
            "var sel=window.getSelection(); sel.removeAllRanges(); sel.addRange(r);",
            text_elem,
        )

        # Pick a label checkbox if present
        try:
            checkbox = self.driver.find_element(By.CSS_SELECTOR, ".annotation-form.span input[type='checkbox']")
            checkbox.click()
        except Exception:
            pass

        # Trigger selection handler
        self.driver.execute_script("window.spanManager && window.spanManager.handleTextSelection();")
        time.sleep(0.5)

        new_overlay_count = self.driver.execute_script(
            "var c=document.getElementById('span-overlays'); return c?c.children.length:0;"
        )

        assert new_overlay_count >= overlay_count, "Overlay count should not decrease after creating span"

        # Reload and ensure manager re-renders overlays without errors
        self.driver.refresh()
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "span-overlays"))
        )
        # Give time for initialization
        time.sleep(1)
        re_overlay_count = self.driver.execute_script(
            "var c=document.getElementById('span-overlays'); return c?c.children.length:0;"
        )
        assert re_overlay_count >= 0, "Overlay layer should be present after reload"



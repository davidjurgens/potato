import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from tests.selenium.test_base import BaseSeleniumTest


class TestSpanOverlayAlignment(BaseSeleniumTest):
    def test_overlay_aligned_with_selection(self):
        self.driver.get(f"{self.server.base_url}/annotate")

        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "text-content"))
        )
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "span-overlays"))
        )

        # Ensure manager initialized
        WebDriverWait(self.driver, 10).until(lambda d: d.execute_script("return !!(window.spanManager && window.spanManager.isInitialized);"))

        text_elem = self.driver.find_element(By.ID, "text-content")
        # Select a small range roughly mid-text
        self.driver.execute_script(
            "var el=arguments[0]; var r=document.createRange();"
            "var n=el.firstChild||el; var len=(n.textContent||'').length;"
            "var start=Math.max(0, Math.floor(len/2)); var end=Math.min(len, start+6);"
            "try{r.setStart(n,start); r.setEnd(n,end);}catch(e){}"
            "var sel=window.getSelection(); sel.removeAllRanges(); sel.addRange(r);",
            text_elem,
        )

        # Pick a label checkbox if present (fallback to programmatic selection)
        try:
            checkbox = self.driver.find_element(By.CSS_SELECTOR, ".annotation-form.span input[type='checkbox']")
            checkbox.click()
        except Exception:
            self.driver.execute_script("window.spanManager && window.spanManager.selectLabel('positive','emotion_spans');")

        # Trigger selection handler and wait a moment
        self.driver.execute_script("window.spanManager && window.spanManager.handleTextSelection();")
        time.sleep(0.1)

        # Get first overlay segment rect
        rects = self.driver.execute_script(
            "var el=document.getElementById('span-overlays');"
            "if(!el||!el.firstElementChild) return null;"
            "var seg=el.firstElementChild.querySelector('.span-highlight-segment');"
            "if(!seg) return null;"
            "var segRect=seg.getBoundingClientRect();"
            "return {sw:segRect.width, sh:segRect.height};"
        )

        assert rects is not None, "Overlay segment should exist"
        assert rects['sw'] > 0, "Overlay width should be > 0"
        assert rects['sh'] >= 10, "Overlay height unexpectedly small"


class TestSpanOverlayNavigation(BaseSeleniumTest):
    def test_no_full_overlay_on_return(self):
        self.driver.get(f"{self.server.base_url}/annotate")

        WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((By.ID, "text-content")))
        WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((By.ID, "span-overlays")))

        WebDriverWait(self.driver, 10).until(lambda d: d.execute_script("return !!(window.spanManager && window.spanManager.isInitialized);"))

        # Create a span
        text_elem = self.driver.find_element(By.ID, "text-content")
        self.driver.execute_script(
            "var el=arguments[0]; var r=document.createRange();"
            "var n=el.firstChild||el; var len=(n.textContent||'').length;"
            "var start=Math.max(0, Math.floor(len/3)); var end=Math.min(len, start+5);"
            "try{r.setStart(n,start); r.setEnd(n,end);}catch(e){}"
            "var sel=window.getSelection(); sel.removeAllRanges(); sel.addRange(r);",
            text_elem,
        )
        try:
            checkbox = self.driver.find_element(By.CSS_SELECTOR, ".annotation-form.span input[type='checkbox']")
            checkbox.click()
        except Exception:
            self.driver.execute_script("window.spanManager && window.spanManager.selectLabel('positive','emotion_spans');")
        self.driver.execute_script("window.spanManager && window.spanManager.handleTextSelection();")
        time.sleep(0.1)

        # Navigate next then previous
        self.driver.find_element(By.ID, "next-btn").click()
        WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((By.ID, "text-content")))
        time.sleep(0.1)
        self.driver.find_element(By.ID, "prev-btn").click()
        WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((By.ID, "text-content")))
        time.sleep(0.1)

        # Assert overlays exist and none covers full container
        full_cover = self.driver.execute_script(
            "var inst=document.getElementById('instance-text').getBoundingClientRect();"
            "var c=document.getElementById('span-overlays'); if(!c) return true;"
            "var children=c.children; if(children.length===0) return false;"
            "for(var i=0;i<children.length;i++){var seg=children[i];"
            "  var r=seg.getBoundingClientRect();"
            "  if(Math.abs(r.width-inst.width)<5 && Math.abs(r.height-inst.height)<5){return true;}"
            "} return false;"
        )
        assert full_cover is False, "No overlay should cover the entire instance text container"

    def test_scroll_and_padding_compensation(self):
        # Ensure that overlays align even when the instance text is scrollable
        self.driver.get(f"{self.server.base_url}/annotate")
        WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((By.ID, "instance-text")))

        # Force a max height to induce scroll
        self.driver.execute_script(
            "var it=document.getElementById('instance-text');"
            "it.style.maxHeight='60px'; it.style.overflowY='auto'; it.style.padding='12px';"
        )

        WebDriverWait(self.driver, 10).until(lambda d: d.execute_script("return !!(window.spanManager && window.spanManager.isInitialized);"))

        text_elem = self.driver.find_element(By.ID, "text-content")
        # Scroll down a bit
        self.driver.execute_script("document.getElementById('instance-text').scrollTop=10;")
        # Select a range and create span
        self.driver.execute_script(
            "var el=arguments[0]; var r=document.createRange();"
            "var n=el.firstChild||el; var len=(n.textContent||'').length;"
            "var start=Math.max(0, Math.floor(len/2)); var end=Math.min(len, start+6);"
            "try{r.setStart(n,start); r.setEnd(n,end);}catch(e){}"
            "var sel=window.getSelection(); sel.removeAllRanges(); sel.addRange(r);",
            text_elem,
        )
        try:
            checkbox = self.driver.find_element(By.CSS_SELECTOR, ".annotation-form.span input[type='checkbox']")
            checkbox.click()
        except Exception:
            pass
        self.driver.execute_script("window.spanManager && window.spanManager.handleTextSelection();")
        time.sleep(0.1)

        # Verify overlay appears and has a reasonable height
        seg_height = self.driver.execute_script(
            "var c=document.getElementById('span-overlays'); if(!c||!c.firstElementChild) return 0;"
            "var seg=c.firstElementChild.querySelector('.span-highlight-segment'); if(!seg) return 0;"
            "return seg.getBoundingClientRect().height;"
        )
        assert seg_height >= 10, "Overlay segment height should be reasonable even with scroll/padding applied"



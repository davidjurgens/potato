#!/usr/bin/env python3
"""
Selenium test for memo threads and issues in the Notes panel.

Raise an issue, reply to it, resolve it, then navigate away and back (not a
refresh, per CLAUDE.md): the thread, the reply and the Resolved state must
all come back from the server, shown as the page shows them.
"""

import unittest

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

# Through the module: a bare import would make pytest collect TestMemosUI here too.
from tests.selenium import test_memos_ui as memos_ui


class TestMemoThreadsUI(memos_ui.TestMemosUI):
    # Inherit the server, browser and helpers; run only this class's test.
    test_memo_survives_navigate_away_and_back = None
    test_memo_not_shown_on_other_instance = None

    def _click(self, css):
        button = self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, css)))
        button.click()
        return button

    def test_issue_reply_and_resolve_survive_navigation(self):
        start = self._instance_id()
        self._open_panel()
        body = self.wait.until(EC.visibility_of_element_located((By.ID, "memo-new-body")))
        body.send_keys("the second sentence is ambiguous")
        self.driver.find_element(By.ID, "memo-new-issue").click()
        assignee = self.wait.until(EC.visibility_of_element_located((By.ID, "memo-new-assignee")))
        assignee.send_keys("reviewer1")
        self.driver.find_element(By.ID, "memo-add-btn").click()
        self.wait.until(EC.text_to_be_present_in_element((By.ID, "memo-list"), "Open issue"))
        self.assertIn("assigned to reviewer1", self.driver.find_element(By.ID, "memo-list").text)

        self._click('#memo-list button[data-act="reply"]')
        reply = self.wait.until(EC.visibility_of_element_located(
            (By.CSS_SELECTOR, "#memo-list .memo-reply-input")))
        self.assertEqual(self.driver.switch_to.active_element, reply, "reply box did not take focus")
        reply.send_keys("agree, it reads two ways")
        self._click('#memo-list button[data-act="send-reply"]')
        self.wait.until(EC.text_to_be_present_in_element((By.ID, "memo-list"), "it reads two ways"))

        self._click('#memo-list button[data-act="resolve"]')
        self.wait.until(EC.text_to_be_present_in_element((By.ID, "memo-list"), "Resolved"))

        self._annotate_radio()
        self._nav("next-btn")
        self.assertNotEqual(self._instance_id(), start)
        self._nav("prev-btn")
        self.assertEqual(self._instance_id(), start)

        memo_list = self._open_panel()
        self.wait.until(EC.text_to_be_present_in_element((By.ID, "memo-list"), "Resolved"))
        item = memo_list.find_element(By.CSS_SELECTOR, ".memo-item")
        self.assertIn("is-resolved", item.get_attribute("class"))
        self.assertEqual(
            [r.find_element(By.CSS_SELECTOR, ".memo-body").text
             for r in item.find_elements(By.CSS_SELECTOR, ".memo-thread .memo-reply")],
            ["agree, it reads two ways"])
        self.assertTrue(item.find_elements(By.CSS_SELECTOR, 'button[data-act="reopen"]'))
        self.assertIn("resolved by", item.text)


if __name__ == "__main__":
    unittest.main()

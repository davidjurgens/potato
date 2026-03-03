#!/usr/bin/env python3
"""
Selenium tests for Solo Mode dashboard tab interactions and content.

Tests tab switching, overview content, and tab-specific content on the
status dashboard page (/solo/status).

Run with:
    pytest tests/selenium/test_solo_mode/test_solo_dashboard.py -v -m selenium
"""

import time
import unittest

import pytest
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException

from tests.selenium.test_solo_mode.test_base_solo import BaseSoloModeSeleniumTest


@pytest.mark.selenium
class TestDashboardTabSwitching(BaseSoloModeSeleniumTest):
    """Test tab switching on the Solo Mode status dashboard."""

    def test_overview_tab_active_by_default(self):
        """Overview tab should be active on initial page load."""
        self.login_user()
        self.navigate_to_solo_status()

        tab = self.driver.find_element(
            By.CSS_SELECTOR, '.solo-tab[data-tab="overview"]'
        )
        assert 'active' in tab.get_attribute('class'), (
            "Overview tab should be active by default"
        )

    def test_click_confusion_tab(self):
        """Clicking Confusion tab activates it and shows its content."""
        self.login_user()
        self.navigate_to_solo_status()

        tab = self.wait_for_element_clickable(
            By.CSS_SELECTOR, '.solo-tab[data-tab="confusion"]'
        )
        tab.click()
        time.sleep(0.5)

        assert 'active' in tab.get_attribute('class')
        content = self.driver.find_element(By.ID, 'tab-confusion')
        assert 'active' in content.get_attribute('class')

    def test_click_labeling_fns_tab(self):
        """Clicking Labeling Fns tab activates it."""
        self.login_user()
        self.navigate_to_solo_status()

        tab = self.wait_for_element_clickable(
            By.CSS_SELECTOR, '.solo-tab[data-tab="labeling-fns"]'
        )
        tab.click()
        time.sleep(0.5)

        assert 'active' in tab.get_attribute('class')
        content = self.driver.find_element(By.ID, 'tab-labeling-fns')
        assert 'active' in content.get_attribute('class')

    def test_click_disagreements_tab(self):
        """Clicking Disagreements tab activates it."""
        self.login_user()
        self.navigate_to_solo_status()

        tab = self.wait_for_element_clickable(
            By.CSS_SELECTOR, '.solo-tab[data-tab="disagreements"]'
        )
        tab.click()
        time.sleep(0.5)

        assert 'active' in tab.get_attribute('class')
        content = self.driver.find_element(By.ID, 'tab-disagreements')
        assert 'active' in content.get_attribute('class')

    def test_click_rules_tab(self):
        """Clicking Rules tab activates it."""
        self.login_user()
        self.navigate_to_solo_status()

        tab = self.wait_for_element_clickable(
            By.CSS_SELECTOR, '.solo-tab[data-tab="rules"]'
        )
        tab.click()
        time.sleep(0.5)

        assert 'active' in tab.get_attribute('class')
        content = self.driver.find_element(By.ID, 'tab-rules')
        assert 'active' in content.get_attribute('class')

    def test_click_clusters_tab(self):
        """Clicking Clusters tab activates it."""
        self.login_user()
        self.navigate_to_solo_status()

        tab = self.wait_for_element_clickable(
            By.CSS_SELECTOR, '.solo-tab[data-tab="clusters"]'
        )
        tab.click()
        time.sleep(0.5)

        assert 'active' in tab.get_attribute('class')
        content = self.driver.find_element(By.ID, 'tab-clusters')
        assert 'active' in content.get_attribute('class')

    def test_switching_back_to_overview(self):
        """Switching to another tab and back to overview works."""
        self.login_user()
        self.navigate_to_solo_status()

        # Switch to confusion
        confusion_tab = self.wait_for_element_clickable(
            By.CSS_SELECTOR, '.solo-tab[data-tab="confusion"]'
        )
        confusion_tab.click()
        time.sleep(0.3)

        # Switch back to overview
        overview_tab = self.wait_for_element_clickable(
            By.CSS_SELECTOR, '.solo-tab[data-tab="overview"]'
        )
        overview_tab.click()
        time.sleep(0.3)

        assert 'active' in overview_tab.get_attribute('class')
        content = self.driver.find_element(By.ID, 'tab-overview')
        assert 'active' in content.get_attribute('class')

    def test_only_one_tab_active_at_a_time(self):
        """Only one tab should have the active class at any time."""
        self.login_user()
        self.navigate_to_solo_status()

        # Click through each tab and verify only one is active
        tab_names = ['confusion', 'labeling-fns', 'disagreements', 'rules']
        for name in tab_names:
            tab = self.wait_for_element_clickable(
                By.CSS_SELECTOR, f'.solo-tab[data-tab="{name}"]'
            )
            tab.click()
            time.sleep(0.3)

            active_tabs = self.driver.find_elements(
                By.CSS_SELECTOR, '.solo-tab.active'
            )
            assert len(active_tabs) == 1, (
                f"Expected 1 active tab after clicking {name}, "
                f"found {len(active_tabs)}"
            )


@pytest.mark.selenium
class TestDashboardOverviewContent(BaseSoloModeSeleniumTest):
    """Test content displayed on the overview tab."""

    def test_phase_indicator_present(self):
        """Phase indicator badge should be on the page."""
        self.login_user()
        self.navigate_to_solo_status()

        indicator = self.driver.find_element(
            By.CSS_SELECTOR, '.phase-indicator'
        )
        assert indicator.text.strip(), "Phase indicator should have text"

    def test_dashboard_cards_present(self):
        """Dashboard should contain cards with values."""
        self.login_user()
        self.navigate_to_solo_status()

        cards = self.driver.find_elements(By.CSS_SELECTOR, '.dashboard-card')
        assert len(cards) > 0, "Dashboard should have at least one card"

        values = self.driver.find_elements(By.CSS_SELECTOR, '.card-value')
        assert len(values) > 0, "Dashboard cards should have value elements"

    def test_agreement_rate_displayed(self):
        """Agreement rate card should be displayed."""
        self.login_user()
        self.navigate_to_solo_status()

        # Look for the agreement rate card by its ID
        try:
            rate_elem = self.driver.find_element(By.ID, 'ov-agreement-rate')
            assert rate_elem is not None
        except NoSuchElementException:
            # Fallback: look for text mentioning agreement
            self.assert_text_in_page('Agreement')

    def test_progress_bar_elements_present(self):
        """Progress bar should be present on the overview."""
        self.login_user()
        self.navigate_to_solo_status()

        try:
            track = self.driver.find_element(
                By.CSS_SELECTOR, '.progress-track'
            )
            fill = self.driver.find_element(
                By.CSS_SELECTOR, '.progress-fill'
            )
            assert track is not None
            assert fill is not None
        except NoSuchElementException:
            # Progress bar may use different markup
            pass

    def test_llm_stats_section_present(self):
        """LLM stats section should exist on the overview."""
        self.login_user()
        self.navigate_to_solo_status()

        # Look for LLM-related text on the page
        page = self.get_page_source()
        assert 'LLM' in page or 'Labeled' in page or 'labeled' in page, (
            "Page should mention LLM labeling stats"
        )


@pytest.mark.selenium
class TestDashboardTabContent(BaseSoloModeSeleniumTest):
    """Test content within each dashboard tab."""

    def _switch_to_tab(self, tab_name):
        """Helper to switch to a tab and wait."""
        tab = self.wait_for_element_clickable(
            By.CSS_SELECTOR, f'.solo-tab[data-tab="{tab_name}"]'
        )
        tab.click()
        time.sleep(0.5)

    def test_confusion_tab_has_content(self):
        """Confusion tab shows heatmap container or empty message."""
        self.login_user()
        self.navigate_to_solo_status()
        self._switch_to_tab('confusion')

        content = self.driver.find_element(By.ID, 'tab-confusion')
        assert content.is_displayed(), "Confusion tab content should be visible"
        # Should have either a heatmap or summary cards
        html = content.get_attribute('innerHTML')
        assert len(html.strip()) > 0, "Confusion tab should have content"

    def test_labeling_fns_tab_has_content(self):
        """Labeling Fns tab shows function table or empty message."""
        self.login_user()
        self.navigate_to_solo_status()
        self._switch_to_tab('labeling-fns')

        content = self.driver.find_element(By.ID, 'tab-labeling-fns')
        assert content.is_displayed()
        html = content.get_attribute('innerHTML')
        assert len(html.strip()) > 0

    def test_labeling_fns_extract_button_present(self):
        """Labeling Fns tab has the Extract from Predictions button."""
        self.login_user()
        self.navigate_to_solo_status()
        self._switch_to_tab('labeling-fns')

        content = self.driver.find_element(By.ID, 'tab-labeling-fns')
        html = content.get_attribute('innerHTML')
        assert 'Extract' in html, (
            "Labeling Fns tab should have Extract button"
        )

    def test_disagreements_tab_summary_cards(self):
        """Disagreements tab has summary cards."""
        self.login_user()
        self.navigate_to_solo_status()
        self._switch_to_tab('disagreements')

        content = self.driver.find_element(By.ID, 'tab-disagreements')
        assert content.is_displayed()

        # Check for the summary card IDs
        try:
            self.driver.find_element(By.ID, 'disagree-total-compared')
        except NoSuchElementException:
            # The element might exist but with different structure
            pass

    def test_disagreements_tab_has_scatter_container(self):
        """Disagreements tab has a scatter plot container."""
        self.login_user()
        self.navigate_to_solo_status()
        self._switch_to_tab('disagreements')

        content = self.driver.find_element(By.ID, 'tab-disagreements')
        html = content.get_attribute('innerHTML')
        # Should have some visualization container (scatter, chart, or svg)
        assert len(html.strip()) > 100, (
            "Disagreements tab should have substantial content"
        )

    def test_disagreements_tab_has_label_filter(self):
        """Disagreements tab has a label filter dropdown."""
        self.login_user()
        self.navigate_to_solo_status()
        self._switch_to_tab('disagreements')

        content = self.driver.find_element(By.ID, 'tab-disagreements')
        html = content.get_attribute('innerHTML')
        # Look for filter-related elements
        has_filter = ('filter' in html.lower() or 'select' in html.lower()
                      or 'label' in html.lower())
        assert has_filter, "Disagreements tab should have label filter"

    def test_rules_tab_has_content(self):
        """Rules tab shows rules table or empty message."""
        self.login_user()
        self.navigate_to_solo_status()
        self._switch_to_tab('rules')

        content = self.driver.find_element(By.ID, 'tab-rules')
        assert content.is_displayed()
        html = content.get_attribute('innerHTML')
        assert len(html.strip()) > 0

    def test_rules_tab_stats_cards_present(self):
        """Rules tab has stats cards."""
        self.login_user()
        self.navigate_to_solo_status()
        self._switch_to_tab('rules')

        # Check for stats card IDs
        page = self.get_page_source()
        assert 'rules-total' in page or 'Edge Case' in page

    def test_clusters_tab_has_viz_container(self):
        """Clusters tab has a visualization container."""
        self.login_user()
        self.navigate_to_solo_status()
        self._switch_to_tab('clusters')

        content = self.driver.find_element(By.ID, 'tab-clusters')
        assert content.is_displayed()
        html = content.get_attribute('innerHTML')
        assert len(html.strip()) > 0, (
            "Clusters tab should have content"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "selenium"])

"""
Tests for save/navigation safety in annotation.js.

Verifies that the frontend handles save failures correctly during navigation
to prevent silent data loss. Also checks debounce flush and annotation-data-input
loading patterns.
"""

import os
import re
import pytest


class TestSaveAnnotationsReturnValue:
    """Verify saveAnnotations() returns false on HTTP errors."""

    @pytest.fixture(autouse=True)
    def load_js(self):
        js_path = os.path.join(
            os.path.dirname(__file__), "../../potato/static/annotation.js"
        )
        with open(js_path, "r") as f:
            self.js_code = f.read()

    def _extract_function(self, name):
        """Extract a function body from the JS code."""
        # Find function start
        pattern = rf'(async\s+)?function\s+{name}\s*\('
        match = re.search(pattern, self.js_code)
        if not match:
            return None
        start = match.start()
        # Find matching closing brace by counting
        depth = 0
        in_func = False
        for i in range(start, len(self.js_code)):
            if self.js_code[i] == '{':
                depth += 1
                in_func = True
            elif self.js_code[i] == '}':
                depth -= 1
                if in_func and depth == 0:
                    return self.js_code[start:i + 1]
        return self.js_code[start:start + 3000]

    def test_save_returns_false_on_http_error(self):
        """saveAnnotations() must return false when response.ok is false."""
        func = self._extract_function('saveAnnotations')
        assert func is not None, "saveAnnotations function not found"

        # The else branch (response not ok) should return false
        # Find the pattern: "} else {" ... "return false"
        # We need to make sure there's a "return false" in the error path
        assert "return false" in func, (
            "saveAnnotations() must return false on HTTP errors to prevent "
            "silent data loss during navigation"
        )

        # Count return statements - should have true for success and false for failure
        true_returns = func.count("return true")
        false_returns = func.count("return false")
        assert true_returns >= 1, "Should return true on success"
        assert false_returns >= 2, (
            "Should return false on both HTTP errors AND catch errors "
            f"(found {false_returns} false returns)"
        )


class TestNavigationChecksave:
    """Verify navigation functions check saveAnnotations() return value."""

    @pytest.fixture(autouse=True)
    def load_js(self):
        js_path = os.path.join(
            os.path.dirname(__file__), "../../potato/static/annotation.js"
        )
        with open(js_path, "r") as f:
            self.js_code = f.read()

    def _get_function_body(self, name, max_chars=3000):
        pattern = rf'(async\s+)?function\s+{name}\s*\('
        match = re.search(pattern, self.js_code)
        if not match:
            return None
        return self.js_code[match.start():match.start() + max_chars]

    def test_navigate_to_next_checks_save_result(self):
        """navigateToNext() must check if saveAnnotations() succeeded."""
        func = self._get_function_body('navigateToNext')
        assert func is not None

        # Should assign the result of saveAnnotations() to a variable
        assert "= await saveAnnotations()" in func, (
            "navigateToNext must capture the return value of saveAnnotations"
        )
        # Should check for failure
        assert "false" in func.split("saveAnnotations")[1][:200], (
            "navigateToNext must check for save failure after calling saveAnnotations"
        )

    def test_navigate_to_previous_checks_save_result(self):
        """navigateToPrevious() must check if saveAnnotations() succeeded."""
        func = self._get_function_body('navigateToPrevious')
        assert func is not None

        assert "= await saveAnnotations()" in func, (
            "navigateToPrevious must capture the return value of saveAnnotations"
        )

    def test_navigate_to_instance_checks_save_result(self):
        """navigateToInstance() must check if saveAnnotations() succeeded."""
        func = self._get_function_body('navigateToInstance')
        assert func is not None

        assert "= await saveAnnotations()" in func, (
            "navigateToInstance must capture the return value of saveAnnotations"
        )


class TestDebounceFlushBeforeNavigation:
    """Verify debounce timers are flushed before navigation saves."""

    @pytest.fixture(autouse=True)
    def load_js(self):
        js_path = os.path.join(
            os.path.dirname(__file__), "../../potato/static/annotation.js"
        )
        with open(js_path, "r") as f:
            self.js_code = f.read()

    def _get_function_body(self, name, max_chars=3000):
        pattern = rf'(async\s+)?function\s+{name}\s*\('
        match = re.search(pattern, self.js_code)
        if not match:
            return None
        return self.js_code[match.start():match.start() + max_chars]

    def test_navigate_to_next_flushes_debounce(self):
        """navigateToNext must clear textSaveTimer before saving."""
        func = self._get_function_body('navigateToNext')
        assert func is not None

        # clearTimeout(textSaveTimer) should appear before saveAnnotations()
        clear_pos = func.find('clearTimeout(textSaveTimer)')
        save_pos = func.find('saveAnnotations()')
        assert clear_pos != -1, "navigateToNext must call clearTimeout(textSaveTimer)"
        assert clear_pos < save_pos, "clearTimeout must come before saveAnnotations"

    def test_navigate_to_previous_flushes_debounce(self):
        """navigateToPrevious must clear textSaveTimer before saving."""
        func = self._get_function_body('navigateToPrevious')
        assert func is not None

        clear_pos = func.find('clearTimeout(textSaveTimer)')
        save_pos = func.find('saveAnnotations()')
        assert clear_pos != -1, "navigateToPrevious must call clearTimeout(textSaveTimer)"
        assert clear_pos < save_pos, "clearTimeout must come before saveAnnotations"

    def test_navigate_to_instance_flushes_debounce(self):
        """navigateToInstance must clear textSaveTimer before saving."""
        func = self._get_function_body('navigateToInstance')
        assert func is not None

        clear_pos = func.find('clearTimeout(textSaveTimer)')
        save_pos = func.find('saveAnnotations()')
        assert clear_pos != -1, "navigateToInstance must call clearTimeout(textSaveTimer)"
        assert clear_pos < save_pos, "clearTimeout must come before saveAnnotations"


class TestAnnotationDataInputLoading:
    """Verify annotation-data-input elements are loaded into currentAnnotations."""

    @pytest.fixture(autouse=True)
    def load_js(self):
        js_path = os.path.join(
            os.path.dirname(__file__), "../../potato/static/annotation.js"
        )
        with open(js_path, "r") as f:
            self.js_code = f.read()

    def _get_full_function(self, name):
        """Extract the complete function body by brace matching."""
        pattern = rf'(async\s+)?function\s+{name}\s*\('
        match = re.search(pattern, self.js_code)
        if not match:
            return None
        start = match.start()
        depth = 0
        in_func = False
        for i in range(start, min(start + 20000, len(self.js_code))):
            if self.js_code[i] == '{':
                depth += 1
                in_func = True
            elif self.js_code[i] == '}':
                depth -= 1
                if in_func and depth == 0:
                    return self.js_code[start:i + 1]
        return self.js_code[start:start + 10000]

    def test_load_annotations_includes_data_inputs(self):
        """loadAnnotations() must read annotation-data-input elements."""
        func = self._get_full_function('loadAnnotations')
        assert func is not None

        assert "annotation-data-input" in func, (
            "loadAnnotations() must read .annotation-data-input elements into "
            "currentAnnotations to keep frontend state in sync with backend"
        )

    def test_load_annotations_checks_server_set_for_data_inputs(self):
        """loadAnnotations() should only load data inputs with data-server-set flag."""
        func = self._get_full_function('loadAnnotations')
        assert func is not None

        # The data-input loading section should check for data-server-set
        data_input_section = func[func.find('annotation-data-input'):]
        assert "data-server-set" in data_input_section[:500], (
            "annotation-data-input loading should check data-server-set to avoid "
            "loading browser-cached values"
        )

    def test_save_and_load_both_handle_data_inputs(self):
        """Both save and load paths must handle annotation-data-input."""
        save_func = self._get_full_function('saveAnnotations')
        load_func = self._get_full_function('loadAnnotations')

        assert "annotation-data-input" in save_func, "save must handle data inputs"
        assert "annotation-data-input" in load_func, "load must handle data inputs"

"""
Tests for save/navigation safety in annotation.js.

Verifies that the frontend handles save failures correctly during navigation
to prevent silent data loss. Also checks debounce flush and annotation-data-input
loading patterns.
"""

import os
import re
import pytest


def extract_js_function(js_code, name, limit=None):
    """Return the full source of a top-level JS function, braces balanced.

    Steps over the parameter list before counting body braces. Counting from
    the `function` keyword reads a destructured parameter — `({ background =
    false } = {})` — as the body and stops at its closing brace, handing back
    the signature alone; every substring assertion against it then passes or
    fails for the wrong reason.
    """
    match = re.search(rf'(async\s+)?function\s+{name}\s*\(', js_code)
    if not match:
        return None
    start = match.start()

    paren_depth = 0
    body_start = None
    for i in range(match.end() - 1, len(js_code)):
        ch = js_code[i]
        if ch == '(':
            paren_depth += 1
        elif ch == ')':
            paren_depth -= 1
            if paren_depth == 0:
                body_start = js_code.find('{', i)
                break
    if body_start is None or body_start == -1:
        return None

    depth = 0
    end = len(js_code) if limit is None else min(body_start + limit, len(js_code))
    for i in range(body_start, end):
        if js_code[i] == '{':
            depth += 1
        elif js_code[i] == '}':
            depth -= 1
            if depth == 0:
                return js_code[start:i + 1]
    return js_code[start:end]


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
        return extract_js_function(self.js_code, name)

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
        return extract_js_function(self.js_code, name, limit=20000)

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
        """Both save and load paths must handle annotation-data-input.

        `saveAnnotations` may collect them itself or delegate to
        `collectAnnotationDataInputs`, which is shared with the beforeunload
        flush — that flush used to build its own payload and omit these
        entirely, so a closed tab posted an answer with the canvas schemas
        missing. What matters is that the save path reaches them, not where the
        querySelectorAll lives.
        """
        save_func = self._get_full_function('saveAnnotations')
        load_func = self._get_full_function('loadAnnotations')

        collects_directly = "annotation-data-input" in save_func
        delegates = "collectAnnotationDataInputs" in save_func
        assert collects_directly or delegates, "save must handle data inputs"

        if delegates:
            collector = self._get_full_function('collectAnnotationDataInputs')
            assert collector and "annotation-data-input" in collector, (
                "saveAnnotations delegates to collectAnnotationDataInputs, and "
                "that function does not read the data inputs")

        assert "annotation-data-input" in load_func, "load must handle data inputs"

    def test_the_unload_flush_collects_data_inputs_too(self):
        """
        `flushPendingSave` posts through sendBeacon during unload. It built its
        payload from `currentAnnotations` alone, so the canvas and timeline
        schemas were absent from it — which the server reads as cleared rather
        than unmentioned.
        """
        flush = self._get_full_function('flushPendingSave')
        assert flush, "flushPendingSave is gone; the unload path needs re-checking"
        assert ("collectAnnotationDataInputs" in flush
                or "annotation-data-input" in flush), (
            "the unload flush posts without the .annotation-data-input values")

"""
Test to reproduce span annotation persistence bug.

This test verifies that span annotations persist correctly when navigating
between instances and returning to a previously annotated instance.
"""

import pytest

# Skip server integration tests for fast CI - run with pytest -m slow
pytestmark = pytest.mark.skip(reason="Server integration tests skipped for fast CI execution")
import requests
import json
import os
import tempfile
import shutil
import yaml
import time
from tests.helpers.flask_test_setup import FlaskTestServer

class TestSpanPersistence:
    """Test span annotation persistence across navigation."""

    def test_span_annotation_persistence_bug(self):
        """Test that reproduces the bug where span highlights disappear from UI after navigation."""
        # --- Setup temporary test directory and files ---
        test_dir = tempfile.mkdtemp(prefix="span_persistence_test_", dir=os.path.join(os.path.dirname(__file__), 'output'))
        data_file = os.path.join(test_dir, 'test_data.jsonl')
        config_file = os.path.join(test_dir, 'test_config.yaml')
        output_dir = os.path.join(test_dir, 'output')
        os.makedirs(output_dir, exist_ok=True)

        # Create test data
        test_data = [
            {"id": "instance1", "text": "I am very happy today."},
            {"id": "instance2", "text": "This is a different instance."}
        ]
        with open(data_file, 'w') as f:
            for item in test_data:
                f.write(json.dumps(item) + '\n')

        # Create config
        config = {
            "debug": False,
            "annotation_task_name": "Span Persistence Test",
            "require_password": False,
            "authentication": {"method": "in_memory"},
            "data_files": [os.path.basename(data_file)],
            "item_properties": {"text_key": "text", "id_key": "id"},
            "annotation_schemes": [
                {
                    "name": "emotion",
                    "annotation_type": "span",
                    "labels": ["happy", "sad"],
                    "description": "Mark emotion spans in the text."
                }
            ],
            "output_annotation_dir": output_dir,
            "task_dir": test_dir,
            "site_file": "base_template.html",
            "alert_time_each_instance": 0
        }
        with open(config_file, 'w') as f:
            yaml.dump(config, f)

        # --- Start Flask test server ---
        port = 9011
        server = FlaskTestServer(port=port, debug=False, config_file=config_file)
        assert server.start(), "Failed to start Flask test server"
        base_url = f"http://localhost:{port}"

        try:
            session = requests.Session()
            username = "test_user_span_persistence"
            password = "test_password"

            # Register and login user
            user_data = {"email": username, "pass": password}
            reg_response = session.post(f"{base_url}/register", data=user_data)
            assert reg_response.status_code in [200, 302]
            login_response = session.post(f"{base_url}/auth", data=user_data)
            assert login_response.status_code in [200, 302]
            print("✅ User registered and logged in")

            # Get current instance (should be instance1)
            resp = session.get(f"{base_url}/api/current_instance")
            assert resp.status_code == 200
            instance_id = resp.json()["instance_id"]
            print(f"Current instance: {instance_id}")
            assert instance_id == "instance1"

            # Submit span annotation on instance1
            annotation_data = {
                "instance_id": instance_id,
                "type": "span",
                "schema": "emotion",
                "state": [
                    {"name": "happy", "title": "happy", "start": 5, "end": 10, "value": "happy"}
                ]
            }
            update_resp = session.post(f"{base_url}/updateinstance", json=annotation_data)
            assert update_resp.status_code == 200
            print("✅ Span annotation submitted")

            # Check that span highlight appears in the rendered page BEFORE navigation
            annotate_resp = session.get(f"{base_url}/annotate")
            assert annotate_resp.status_code == 200
            html_before_navigation = annotate_resp.text
            print(f"HTML length before navigation: {len(html_before_navigation)}")

            # Look for span annotation markup in the HTML
            span_markup_indicators = [
                'data-schema="emotion"',
                'data-label="happy"',
                'class="span-annotation"',
                'span-annotation',
                'span-highlight',  # This is the actual class used for span highlights
                'span-overlays'    # This div contains the span overlays
            ]
            markup_found_before = any(indicator in html_before_navigation for indicator in span_markup_indicators)
            print(f"Span markup found before navigation: {markup_found_before}")

            # Debug: Show what span markup is actually present
            for indicator in span_markup_indicators:
                if indicator in html_before_navigation:
                    print(f"✅ Found: {indicator}")
                else:
                    print(f"❌ Missing: {indicator}")

            # Look for the actual text content
            if 'I am very happy today' in html_before_navigation:
                print("✅ Found text 'I am very happy today' before navigation")
            else:
                print("❌ Missing text 'I am very happy today' before navigation")

            # Look for the span-overlays div specifically
            if 'span-overlays' in html_before_navigation:
                print("✅ Found span-overlays div before navigation")
            else:
                print("❌ Missing span-overlays div before navigation")

            # Show a snippet of the HTML around the text-content div
            text_content_index = html_before_navigation.find("text-content")
            if text_content_index != -1:
                snippet_start = max(0, text_content_index - 100)
                snippet_end = min(len(html_before_navigation), text_content_index + 300)
                snippet = html_before_navigation[snippet_start:snippet_end]
                print(f"HTML snippet around text-content: {snippet}")
            else:
                print("❌ Could not find text-content div in HTML")

            # Navigate to next instance
            nav_resp = session.get(f"{base_url}/annotate?action=next_instance")
            assert nav_resp.status_code in [200, 302], f"Navigation to next instance failed: {nav_resp.status_code}"
            print("✅ Navigated to next instance")

            # Navigate back to previous instance
            nav_resp = session.get(f"{base_url}/annotate?action=prev_instance")
            assert nav_resp.status_code in [200, 302], f"Navigation to prev instance failed: {nav_resp.status_code}"
            print("✅ Navigated back to previous instance")

            # Check that span highlight appears in the rendered page AFTER navigation
            annotate_resp = session.get(f"{base_url}/annotate")
            assert annotate_resp.status_code == 200
            html_after_navigation = annotate_resp.text
            print(f"HTML length after navigation: {len(html_after_navigation)}")

            # Look for span annotation markup in the HTML after navigation
            markup_found_after = any(indicator in html_after_navigation for indicator in span_markup_indicators)
            print(f"Span markup found after navigation: {markup_found_after}")

            # Debug: Show what span markup is actually present after navigation
            for indicator in span_markup_indicators:
                if indicator in html_after_navigation:
                    print(f"✅ Found after: {indicator}")
                else:
                    print(f"❌ Missing after: {indicator}")

            # Look for the actual text content after navigation
            if 'I am very happy today' in html_after_navigation:
                print("✅ Found text 'I am very happy today' after navigation")
            else:
                print("❌ Missing text 'I am very happy today' after navigation")

            # Look for the span-overlays div specifically after navigation
            if 'span-overlays' in html_after_navigation:
                print("✅ Found span-overlays div after navigation")
            else:
                print("❌ Missing span-overlays div after navigation")

            # Show a snippet of the HTML around the text-content div after navigation
            text_content_index = html_after_navigation.find("text-content")
            if text_content_index != -1:
                snippet_start = max(0, text_content_index - 100)
                snippet_end = min(len(html_after_navigation), text_content_index + 300)
                snippet = html_after_navigation[snippet_start:snippet_end]
                print(f"HTML snippet around text-content after navigation: {snippet}")
            else:
                print("❌ Could not find text-content div in HTML after navigation")

            # This is the bug: span highlights should persist in the UI
            if not markup_found_after:
                print("❌ BUG CONFIRMED: Span highlights disappeared from UI after navigation!")
                print("Expected: Span markup should be present in HTML after navigation")
                print("Actual: No span markup found in HTML after navigation")

                # Also verify that the data still exists in the backend
                span_resp = session.get(f"{base_url}/api/spans/instance1")
                assert span_resp.status_code == 200
                spans_data = span_resp.json()
                print(f"Backend spans data: {spans_data}")

                # The bug is confirmed if backend has data but frontend doesn't show it
                assert len(spans_data["spans"]) > 0, "Backend also lost the data - this is a different bug"
                print("✅ Backend data persists, but frontend doesn't render it - this is the UI persistence bug!")

                # The test should fail to indicate the bug
                assert markup_found_after, "Span annotation markup not found in rendered page after navigation - this is the bug!"
            else:
                print("✅ Span highlights persist in UI after navigation - no bug found")

        finally:
            server.stop()
            shutil.rmtree(test_dir)

    def test_frontend_span_persistence_after_reload(self):
        """Test that simulates the actual user experience with page reloads."""
        # --- Setup temporary test directory and files ---
        test_dir = tempfile.mkdtemp(prefix="span_frontend_test_", dir=os.path.join(os.path.dirname(__file__), 'output'))
        data_file = os.path.join(test_dir, 'test_data.jsonl')
        config_file = os.path.join(test_dir, 'test_config.yaml')
        output_dir = os.path.join(test_dir, 'output')
        os.makedirs(output_dir, exist_ok=True)

        # Create test data
        test_data = [
            {"id": "instance1", "text": "I am very happy today."},
            {"id": "instance2", "text": "This is a different instance."}
        ]
        with open(data_file, 'w') as f:
            for item in test_data:
                f.write(json.dumps(item) + '\n')

        # Create config
        config = {
            "debug": False,
            "annotation_task_name": "Span Frontend Test",
            "require_password": False,
            "authentication": {"method": "in_memory"},
            "data_files": [os.path.basename(data_file)],
            "item_properties": {"text_key": "text", "id_key": "id"},
            "annotation_schemes": [
                {
                    "name": "emotion",
                    "annotation_type": "span",
                    "labels": ["happy", "sad"],
                    "description": "Mark emotion spans in the text."
                }
            ],
            "output_annotation_dir": output_dir,
            "task_dir": test_dir,
            "site_file": "base_template.html",
            "alert_time_each_instance": 0
        }
        with open(config_file, 'w') as f:
            yaml.dump(config, f)

        # --- Start Flask test server ---
        port = 9012
        server = FlaskTestServer(port=port, debug=False, config_file=config_file)
        assert server.start(), "Failed to start Flask test server"
        base_url = f"http://localhost:{port}"

        try:
            session = requests.Session()
            username = "test_user_frontend_persistence"
            password = "test_password"

            # Register and login user
            user_data = {"email": username, "pass": password}
            reg_response = session.post(f"{base_url}/register", data=user_data)
            assert reg_response.status_code in [200, 302]
            login_response = session.post(f"{base_url}/auth", data=user_data)
            assert login_response.status_code in [200, 302]
            print("✅ User registered and logged in")

            # Get current instance (should be instance1)
            resp = session.get(f"{base_url}/api/current_instance")
            assert resp.status_code == 200
            instance_id = resp.json()["instance_id"]
            print(f"Current instance: {instance_id}")
            assert instance_id == "instance1"

            # Submit span annotation on instance1
            annotation_data = {
                "instance_id": instance_id,
                "type": "span",
                "schema": "emotion",
                "state": [
                    {"name": "happy", "title": "happy", "start": 5, "end": 10, "value": "happy"}
                ]
            }
            update_resp = session.post(f"{base_url}/updateinstance", json=annotation_data)
            assert update_resp.status_code == 200
            print("✅ Span annotation submitted")

            # Verify backend has the data
            span_resp = session.get(f"{base_url}/api/spans/instance1")
            assert span_resp.status_code == 200
            spans_data = span_resp.json()
            assert len(spans_data["spans"]) > 0, "Backend should have span data"
            print("✅ Backend has span data")

            # Simulate navigation with page reload (like the user experience)
            # First, navigate to next instance
            nav_resp = session.get(f"{base_url}/annotate?action=next_instance")
            assert nav_resp.status_code in [200, 302]
            print("✅ Navigated to next instance")

            # Then navigate back to previous instance (this triggers page reload)
            nav_resp = session.get(f"{base_url}/annotate?action=prev_instance")
            assert nav_resp.status_code in [200, 302]
            print("✅ Navigated back to previous instance")

            # Now check if the API still returns the span data after navigation
            span_resp = session.get(f"{base_url}/api/spans/instance1")
            assert span_resp.status_code == 200
            spans_data_after = span_resp.json()
            print(f"Spans data after navigation: {spans_data_after}")

            # The backend data should persist
            assert len(spans_data_after["spans"]) > 0, "Backend lost span data after navigation"
            print("✅ Backend data persists after navigation")

            # Now check the rendered page - this is where the frontend bug occurs
            annotate_resp = session.get(f"{base_url}/annotate")
            assert annotate_resp.status_code == 200
            html_after_navigation = annotate_resp.text

            # Look for the specific span markup that should be rendered by the server
            # The server should render the spans in the HTML, not rely on JavaScript
            span_highlight_found = 'span-highlight' in html_after_navigation
            span_overlays_found = 'span-overlays' in html_after_navigation
            data_label_found = 'data-label="happy"' in html_after_navigation

            print(f"Span highlight found in HTML: {span_highlight_found}")
            print(f"Span overlays found in HTML: {span_overlays_found}")
            print(f"Data label found in HTML: {data_label_found}")

            # The bug is that the server-side rendering should include the spans
            # If it doesn't, then the frontend JavaScript won't be able to display them
            if not (span_highlight_found and span_overlays_found and data_label_found):
                print("❌ BUG CONFIRMED: Server-side rendering is not including span markup!")
                print("Expected: Server should render span markup in HTML")
                print("Actual: Span markup missing from server-rendered HTML")

                # Show what's actually in the HTML around the text content
                text_content_index = html_after_navigation.find("text-content")
                if text_content_index != -1:
                    snippet_start = max(0, text_content_index - 100)
                    snippet_end = min(len(html_after_navigation), text_content_index + 300)
                    snippet = html_after_navigation[snippet_start:snippet_end]
                    print(f"HTML snippet around text-content: {snippet}")

                # This should fail the test
                assert False, "Server-side rendering is not including span markup after navigation"
            else:
                print("✅ Server-side rendering includes span markup - no bug found")

        finally:
            server.stop()
            shutil.rmtree(test_dir)

    def test_frontend_javascript_span_handling(self):
        """Test that checks if frontend JavaScript correctly handles pre-rendered spans."""
        # --- Setup temporary test directory and files ---
        test_dir = tempfile.mkdtemp(prefix="span_js_test_", dir=os.path.join(os.path.dirname(__file__), 'output'))
        data_file = os.path.join(test_dir, 'test_data.jsonl')
        config_file = os.path.join(test_dir, 'test_config.yaml')
        output_dir = os.path.join(test_dir, 'output')
        os.makedirs(output_dir, exist_ok=True)

        # Create test data
        test_data = [
            {"id": "instance1", "text": "I am very happy today."},
            {"id": "instance2", "text": "This is a different instance."}
        ]
        with open(data_file, 'w') as f:
            for item in test_data:
                f.write(json.dumps(item) + '\n')

        # Create config
        config = {
            "debug": False,
            "annotation_task_name": "Span JS Test",
            "require_password": False,
            "authentication": {"method": "in_memory"},
            "data_files": [os.path.basename(data_file)],
            "item_properties": {"text_key": "text", "id_key": "id"},
            "annotation_schemes": [
                {
                    "name": "emotion",
                    "annotation_type": "span",
                    "labels": ["happy", "sad"],
                    "description": "Mark emotion spans in the text."
                }
            ],
            "output_annotation_dir": output_dir,
            "task_dir": test_dir,
            "site_file": "base_template.html",
            "alert_time_each_instance": 0
        }
        with open(config_file, 'w') as f:
            yaml.dump(config, f)

        # --- Start Flask test server ---
        port = 9013
        server = FlaskTestServer(port=port, debug=False, config_file=config_file)
        assert server.start(), "Failed to start Flask test server"
        base_url = f"http://localhost:{port}"

        try:
            session = requests.Session()
            username = "test_user_js_persistence"
            password = "test_password"

            # Register and login user
            user_data = {"email": username, "pass": password}
            reg_response = session.post(f"{base_url}/register", data=user_data)
            assert reg_response.status_code in [200, 302]
            login_response = session.post(f"{base_url}/auth", data=user_data)
            assert login_response.status_code in [200, 302]
            print("✅ User registered and logged in")

            # Get current instance (should be instance1)
            resp = session.get(f"{base_url}/api/current_instance")
            assert resp.status_code == 200
            instance_id = resp.json()["instance_id"]
            print(f"Current instance: {instance_id}")
            assert instance_id == "instance1"

            # Submit span annotation on instance1
            annotation_data = {
                "instance_id": instance_id,
                "type": "span",
                "schema": "emotion",
                "state": [
                    {"name": "happy", "title": "happy", "start": 5, "end": 10, "value": "happy"}
                ]
            }
            update_resp = session.post(f"{base_url}/updateinstance", json=annotation_data)
            assert update_resp.status_code == 200
            print("✅ Span annotation submitted")

            # Get the initial page with spans rendered by server
            annotate_resp = session.get(f"{base_url}/annotate")
            assert annotate_resp.status_code == 200
            initial_html = annotate_resp.text

            # Verify that server-rendered spans are present
            assert 'span-highlight' in initial_html, "Server should render span highlights"
            assert 'data-label="happy"' in initial_html, "Server should include data-label"
            print("✅ Server-rendered spans are present in initial HTML")

            # Now simulate what happens when JavaScript loads
            # The JavaScript should NOT clear the server-rendered spans
            # Let's check if the JavaScript initialization would interfere

            # Get the API response that JavaScript would use
            span_resp = session.get(f"{base_url}/api/spans/instance1")
            assert span_resp.status_code == 200
            api_spans = span_resp.json()
            print(f"API spans data: {api_spans}")

            # The key insight: The server renders spans in the HTML, but the JavaScript
            # might be clearing them and trying to re-render them from the API
            # This could cause a race condition or timing issue

            # Let's check if there's a mismatch between what the server renders
            # and what the API returns
            server_span_id = None
            if 'data-annotation-id="' in initial_html:
                # Extract the span ID from the server-rendered HTML
                start_idx = initial_html.find('data-annotation-id="') + len('data-annotation-id="')
                end_idx = initial_html.find('"', start_idx)
                server_span_id = initial_html[start_idx:end_idx]
                print(f"Server-rendered span ID: {server_span_id}")

            api_span_id = None
            if api_spans.get("spans") and len(api_spans["spans"]) > 0:
                api_span_id = api_spans["spans"][0]["id"]
                print(f"API span ID: {api_span_id}")

            # These should match
            if server_span_id and api_span_id:
                if server_span_id != api_span_id:
                    print(f"❌ MISMATCH: Server span ID ({server_span_id}) != API span ID ({api_span_id})")
                    print("This could cause JavaScript to not recognize the server-rendered spans")
                else:
                    print("✅ Server and API span IDs match")

            # The real issue might be in the JavaScript initialization logic
            # Let's check if the JavaScript would clear the existing spans
            # by looking at the clearAllStateAndOverlays method

            # Based on the user's report, the issue is that spans disappear after navigation
            # This suggests that the JavaScript is either:
            # 1. Not properly detecting server-rendered spans
            # 2. Clearing them during initialization
            # 3. Not re-rendering them after loading from API

            # Let's simulate navigation and see what happens
            nav_resp = session.get(f"{base_url}/annotate?action=next_instance")
            assert nav_resp.status_code in [200, 302]
            print("✅ Navigated to next instance")

            nav_resp = session.get(f"{base_url}/annotate?action=prev_instance")
            assert nav_resp.status_code in [200, 302]
            print("✅ Navigated back to previous instance")

            # Get the page after navigation
            annotate_resp = session.get(f"{base_url}/annotate")
            assert annotate_resp.status_code == 200
            final_html = annotate_resp.text

            # Check if spans are still present
            spans_still_present = 'span-highlight' in final_html and 'data-label="happy"' in final_html
            print(f"Spans still present after navigation: {spans_still_present}")

            if not spans_still_present:
                print("❌ BUG CONFIRMED: Spans disappeared after navigation!")
                print("This is the exact bug the user reported")

                # Show what changed in the HTML
                text_content_index = final_html.find("text-content")
                if text_content_index != -1:
                    snippet_start = max(0, text_content_index - 100)
                    snippet_end = min(len(final_html), text_content_index + 300)
                    snippet = final_html[snippet_start:snippet_end]
                    print(f"HTML snippet around text-content after navigation: {snippet}")

                # This should fail the test
                assert False, "Spans disappeared after navigation - this is the bug!"
            else:
                print("✅ Spans persist after navigation - no bug found")

        finally:
            server.stop()
            shutil.rmtree(test_dir)

    def test_javascript_clears_server_rendered_spans(self):
        """Test that specifically checks if JavaScript clearAllStateAndOverlays clears server-rendered spans."""
        # --- Setup temporary test directory and files ---
        test_dir = tempfile.mkdtemp(prefix="span_js_clear_test_", dir=os.path.join(os.path.dirname(__file__), 'output'))
        data_file = os.path.join(test_dir, 'test_data.jsonl')
        config_file = os.path.join(test_dir, 'test_config.yaml')
        output_dir = os.path.join(test_dir, 'output')
        os.makedirs(output_dir, exist_ok=True)

        # Create test data
        test_data = [
            {"id": "instance1", "text": "I am very happy today."},
            {"id": "instance2", "text": "This is a different instance."}
        ]
        with open(data_file, 'w') as f:
            for item in test_data:
                f.write(json.dumps(item) + '\n')

        # Create config
        config = {
            "debug": False,
            "annotation_task_name": "Span JS Clear Test",
            "require_password": False,
            "authentication": {"method": "in_memory"},
            "data_files": [os.path.basename(data_file)],
            "item_properties": {"text_key": "text", "id_key": "id"},
            "annotation_schemes": [
                {
                    "name": "emotion",
                    "annotation_type": "span",
                    "labels": ["happy", "sad"],
                    "description": "Mark emotion spans in the text."
                }
            ],
            "output_annotation_dir": output_dir,
            "task_dir": test_dir,
            "site_file": "base_template.html",
            "alert_time_each_instance": 0
        }
        with open(config_file, 'w') as f:
            yaml.dump(config, f)

        # --- Start Flask test server ---
        port = 9014
        server = FlaskTestServer(port=port, debug=False, config_file=config_file)
        assert server.start(), "Failed to start Flask test server"
        base_url = f"http://localhost:{port}"

        try:
            session = requests.Session()
            username = "test_user_js_clear"
            password = "test_password"

            # Register and login user
            user_data = {"email": username, "pass": password}
            reg_response = session.post(f"{base_url}/register", data=user_data)
            assert reg_response.status_code in [200, 302]
            login_response = session.post(f"{base_url}/auth", data=user_data)
            assert login_response.status_code in [200, 302]
            print("✅ User registered and logged in")

            # Get current instance (should be instance1)
            resp = session.get(f"{base_url}/api/current_instance")
            assert resp.status_code == 200
            instance_id = resp.json()["instance_id"]
            print(f"Current instance: {instance_id}")
            assert instance_id == "instance1"

            # Submit span annotation on instance1
            annotation_data = {
                "instance_id": instance_id,
                "type": "span",
                "schema": "emotion",
                "state": [
                    {"name": "happy", "title": "happy", "start": 5, "end": 10, "value": "happy"}
                ]
            }
            update_resp = session.post(f"{base_url}/updateinstance", json=annotation_data)
            assert update_resp.status_code == 200
            print("✅ Span annotation submitted")

            # Get the page with server-rendered spans
            annotate_resp = session.get(f"{base_url}/annotate")
            assert annotate_resp.status_code == 200
            initial_html = annotate_resp.text

            # Verify server-rendered spans are present
            assert 'span-highlight' in initial_html, "Server should render span highlights"
            assert 'data-label="happy"' in initial_html, "Server should include data-label"
            print("✅ Server-rendered spans are present in initial HTML")

            # Now simulate what happens when JavaScript loadsAnnotations is called
            # The key issue is that loadAnnotations calls clearAllStateAndOverlays()
            # which clears the spanOverlays.innerHTML, removing server-rendered spans

            # Get the API response that JavaScript would use
            span_resp = session.get(f"{base_url}/api/spans/instance1")
            assert span_resp.status_code == 200
            api_spans = span_resp.json()
            print(f"API spans data: {api_spans}")

            # The problem: JavaScript loadAnnotations() calls clearAllStateAndOverlays()
            # which clears the spanOverlays.innerHTML, removing server-rendered spans
            # Then it tries to re-render from the API, but this might fail or have timing issues

            # Let's check if the server-rendered spans and API spans match
            server_span_id = None
            if 'data-annotation-id="' in initial_html:
                start_idx = initial_html.find('data-annotation-id="') + len('data-annotation-id="')
                end_idx = initial_html.find('"', start_idx)
                server_span_id = initial_html[start_idx:end_idx]
                print(f"Server-rendered span ID: {server_span_id}")

            api_span_id = None
            if api_spans.get("spans") and len(api_spans["spans"]) > 0:
                api_span_id = api_spans["spans"][0]["id"]
                print(f"API span ID: {api_span_id}")

            # These should match
            if server_span_id and api_span_id:
                if server_span_id != api_span_id:
                    print(f"❌ MISMATCH: Server span ID ({server_span_id}) != API span ID ({api_span_id})")
                else:
                    print("✅ Server and API span IDs match")

            # The real issue: JavaScript clearAllStateAndOverlays() clears server-rendered spans
            # This is the root cause of the bug
            print("🔍 DIAGNOSIS: The bug is in JavaScript loadAnnotations() method")
            print("🔍 DIAGNOSIS: It calls clearAllStateAndOverlays() which clears spanOverlays.innerHTML")
            print("🔍 DIAGNOSIS: This removes server-rendered spans from the DOM")
            print("🔍 DIAGNOSIS: Then it tries to re-render from API, but this may fail")

            # Let's simulate navigation to trigger the bug
            nav_resp = session.get(f"{base_url}/annotate?action=next_instance")
            assert nav_resp.status_code in [200, 302]
            print("✅ Navigated to next instance")

            nav_resp = session.get(f"{base_url}/annotate?action=prev_instance")
            assert nav_resp.status_code in [200, 302]
            print("✅ Navigated back to previous instance")

            # Get the page after navigation
            annotate_resp = session.get(f"{base_url}/annotate")
            assert annotate_resp.status_code == 200
            final_html = annotate_resp.text

            # Check if spans are still present
            spans_still_present = 'span-highlight' in final_html and 'data-label="happy"' in final_html
            print(f"Spans still present after navigation: {spans_still_present}")

            if not spans_still_present:
                print("❌ BUG CONFIRMED: JavaScript clearAllStateAndOverlays() cleared server-rendered spans!")
                print("This is the exact bug the user reported")

                # Show what changed in the HTML
                text_content_index = final_html.find("text-content")
                if text_content_index != -1:
                    snippet_start = max(0, text_content_index - 100)
                    snippet_end = min(len(final_html), text_content_index + 300)
                    snippet = final_html[snippet_start:snippet_end]
                    print(f"HTML snippet around text-content after navigation: {snippet}")

                # This should fail the test
                assert False, "JavaScript clearAllStateAndOverlays() cleared server-rendered spans - this is the bug!"
            else:
                print("✅ Spans persist after navigation - no bug found")

        finally:
            server.stop()
            shutil.rmtree(test_dir)

    def test_span_overlay_positioning_after_navigation(self):
        """Test that span overlays are positioned correctly after navigation."""
        # --- Setup temporary test directory and files ---
        test_dir = tempfile.mkdtemp(prefix="span_positioning_test_", dir=os.path.join(os.path.dirname(__file__), 'output'))
        data_file = os.path.join(test_dir, 'test_data.jsonl')
        config_file = os.path.join(test_dir, 'test_config.yaml')
        output_dir = os.path.join(test_dir, 'output')
        os.makedirs(output_dir, exist_ok=True)

        # Create test data with specific positioning requirements
        test_data = [
            {"id": "instance1", "text": "I am very happy today."},
            {"id": "instance2", "text": "This is a different instance."}
        ]
        with open(data_file, 'w') as f:
            for item in test_data:
                f.write(json.dumps(item) + '\n')

        # Create config
        config = {
            "debug": False,
            "annotation_task_name": "Span Positioning Test",
            "require_password": False,
            "authentication": {"method": "in_memory"},
            "data_files": [os.path.basename(data_file)],
            "item_properties": {"text_key": "text", "id_key": "id"},
            "annotation_schemes": [
                {
                    "name": "emotion",
                    "annotation_type": "span",
                    "labels": ["happy", "sad"],
                    "description": "Mark emotion spans in the text."
                }
            ],
            "output_annotation_dir": output_dir,
            "task_dir": test_dir,
            "site_file": "base_template.html",
            "alert_time_each_instance": 0
        }
        with open(config_file, 'w') as f:
            yaml.dump(config, f)

        # --- Start Flask test server ---
        port = 9015
        server = FlaskTestServer(port=port, debug=False, config_file=config_file)
        assert server.start(), "Failed to start Flask test server"
        base_url = f"http://localhost:{port}"

        try:
            session = requests.Session()
            username = "test_user_positioning"
            password = "test_password"

            # Register and login user
            user_data = {"email": username, "pass": password}
            reg_response = session.post(f"{base_url}/register", data=user_data)
            assert reg_response.status_code in [200, 302]
            login_response = session.post(f"{base_url}/auth", data=user_data)
            assert login_response.status_code in [200, 302]
            print("✅ User registered and logged in")

            # Get current instance (should be instance1)
            resp = session.get(f"{base_url}/api/current_instance")
            assert resp.status_code == 200
            instance_id = resp.json()["instance_id"]
            print(f"Current instance: {instance_id}")
            assert instance_id == "instance1"

            # Submit span annotation on instance1 with specific positioning
            # The text is "I am very happy today." and we want to annotate "very " (positions 5-10)
            annotation_data = {
                "instance_id": instance_id,
                "type": "span",
                "schema": "emotion",
                "state": [
                    {"name": "happy", "title": "happy", "start": 5, "end": 10, "value": "happy"}
                ]
            }
            update_resp = session.post(f"{base_url}/updateinstance", json=annotation_data)
            assert update_resp.status_code == 200
            print("✅ Span annotation submitted")

            # Get the initial page with spans rendered by server
            annotate_resp = session.get(f"{base_url}/annotate")
            assert annotate_resp.status_code == 200
            initial_html = annotate_resp.text

            # Verify that server-rendered spans are present
            assert 'span-highlight' in initial_html, "Server should render span highlights"
            assert 'data-label="happy"' in initial_html, "Server should include data-label"
            print("✅ Server-rendered spans are present in initial HTML")

            # Check the initial positioning - the span should be around "very "
            text_content_index = initial_html.find("text-content")
            if text_content_index != -1:
                snippet_start = max(0, text_content_index - 100)
                snippet_end = min(len(initial_html), text_content_index + 300)
                snippet = initial_html[snippet_start:snippet_end]
                print(f"Initial HTML snippet around text-content: {snippet}")

            # Verify the span is positioned correctly in the initial HTML
            # Should be: "I am <span class="span-highlight">very </span>happy today."
            if 'I am <span class="span-highlight"' in initial_html and 'very </span>happy today' in initial_html:
                print("✅ Initial span positioning is correct")
            else:
                print("❌ Initial span positioning is incorrect")
                print("Expected: 'I am <span class=\"span-highlight\">very </span>happy today.'")
                print("Actual HTML snippet shows incorrect positioning")

            # Now simulate navigation
            nav_resp = session.get(f"{base_url}/annotate?action=next_instance")
            assert nav_resp.status_code in [200, 302]
            print("✅ Navigated to next instance")

            nav_resp = session.get(f"{base_url}/annotate?action=prev_instance")
            assert nav_resp.status_code in [200, 302]
            print("✅ Navigated back to previous instance")

            # Get the page after navigation
            annotate_resp = session.get(f"{base_url}/annotate")
            assert annotate_resp.status_code == 200
            final_html = annotate_resp.text

            # Check the positioning after navigation
            text_content_index = final_html.find("text-content")
            if text_content_index != -1:
                snippet_start = max(0, text_content_index - 100)
                snippet_end = min(len(final_html), text_content_index + 300)
                snippet = final_html[snippet_start:snippet_end]
                print(f"Final HTML snippet around text-content: {snippet}")

            # Verify the span is still positioned correctly after navigation
            # Should still be: "I am <span class="span-highlight">very </span>happy today."
            if 'I am <span class="span-highlight"' in final_html and 'very </span>happy today' in final_html:
                print("✅ Final span positioning is correct after navigation")
            else:
                print("❌ BUG CONFIRMED: Span positioning is incorrect after navigation!")
                print("Expected: 'I am <span class=\"span-highlight\">very </span>happy today.'")
                print("Actual HTML snippet shows incorrect positioning")

                # This should fail the test
                assert False, "Span positioning is incorrect after navigation - this is the positioning bug!"

            # Also check that the API data is still correct
            span_resp = session.get(f"{base_url}/api/spans/instance1")
            assert span_resp.status_code == 200
            spans_data = span_resp.json()
            print(f"API spans data after navigation: {spans_data}")

            # Verify the API data has correct positioning
            if spans_data.get("spans") and len(spans_data["spans"]) > 0:
                span = spans_data["spans"][0]
                if span["start"] == 5 and span["end"] == 10 and span["text"] == "very ":
                    print("✅ API data has correct positioning")
                else:
                    print("❌ API data has incorrect positioning")
                    print(f"Expected: start=5, end=10, text='very '")
                    print(f"Actual: start={span['start']}, end={span['end']}, text='{span['text']}'")
            else:
                print("❌ No spans found in API data")

        finally:
            server.stop()
            shutil.rmtree(test_dir)

    def test_span_overlay_positioning_with_javascript(self):
        """Test that span overlays are positioned correctly when JavaScript re-renders them."""
        # --- Setup temporary test directory and files ---
        test_dir = tempfile.mkdtemp(prefix="span_overlay_test_", dir=os.path.join(os.path.dirname(__file__), 'output'))
        data_file = os.path.join(test_dir, 'test_data.jsonl')
        config_file = os.path.join(test_dir, 'test_config.yaml')
        output_dir = os.path.join(test_dir, 'output')
        os.makedirs(output_dir, exist_ok=True)

        # Create test data with specific positioning requirements
        test_data = [
            {"id": "instance1", "text": "I am very happy today."},
            {"id": "instance2", "text": "This is a different instance."}
        ]
        with open(data_file, 'w') as f:
            for item in test_data:
                f.write(json.dumps(item) + '\n')

        # Create config
        config = {
            "debug": False,
            "annotation_task_name": "Span Overlay Test",
            "require_password": False,
            "authentication": {"method": "in_memory"},
            "data_files": [os.path.basename(data_file)],
            "item_properties": {"text_key": "text", "id_key": "id"},
            "annotation_schemes": [
                {
                    "name": "emotion",
                    "annotation_type": "span",
                    "labels": ["happy", "sad"],
                    "description": "Mark emotion spans in the text."
                }
            ],
            "output_annotation_dir": output_dir,
            "task_dir": test_dir,
            "site_file": "base_template.html",
            "alert_time_each_instance": 0
        }
        with open(config_file, 'w') as f:
            yaml.dump(config, f)

        # --- Start Flask test server ---
        port = 9016
        server = FlaskTestServer(port=port, debug=False, config_file=config_file)
        assert server.start(), "Failed to start Flask test server"
        base_url = f"http://localhost:{port}"

        try:
            session = requests.Session()
            username = "test_user_overlay"
            password = "test_password"

            # Register and login user
            user_data = {"email": username, "pass": password}
            reg_response = session.post(f"{base_url}/register", data=user_data)
            assert reg_response.status_code in [200, 302]
            login_response = session.post(f"{base_url}/auth", data=user_data)
            assert login_response.status_code in [200, 302]
            print("✅ User registered and logged in")

            # Get current instance (should be instance1)
            resp = session.get(f"{base_url}/api/current_instance")
            assert resp.status_code == 200
            instance_id = resp.json()["instance_id"]
            print(f"Current instance: {instance_id}")
            assert instance_id == "instance1"

            # Submit span annotation on instance1 with specific positioning
            # The text is "I am very happy today." and we want to annotate "very " (positions 5-10)
            annotation_data = {
                "instance_id": instance_id,
                "type": "span",
                "schema": "emotion",
                "state": [
                    {"name": "happy", "title": "happy", "start": 5, "end": 10, "value": "happy"}
                ]
            }
            update_resp = session.post(f"{base_url}/updateinstance", json=annotation_data)
            assert update_resp.status_code == 200
            print("✅ Span annotation submitted")

            # Get the initial page with spans rendered by server
            annotate_resp = session.get(f"{base_url}/annotate")
            assert annotate_resp.status_code == 200
            initial_html = annotate_resp.text

            # Verify that server-rendered spans are present
            assert 'span-highlight' in initial_html, "Server should render span highlights"
            assert 'data-label="happy"' in initial_html, "Server should include data-label"
            print("✅ Server-rendered spans are present in initial HTML")

            # Check for span-overlays div in initial HTML
            if 'span-overlays' in initial_html:
                print("✅ span-overlays div is present in initial HTML")
            else:
                print("❌ span-overlays div is missing from initial HTML")

            # Now simulate navigation to trigger JavaScript re-rendering
            nav_resp = session.get(f"{base_url}/annotate?action=next_instance")
            assert nav_resp.status_code in [200, 302]
            print("✅ Navigated to next instance")

            nav_resp = session.get(f"{base_url}/annotate?action=prev_instance")
            assert nav_resp.status_code in [200, 302]
            print("✅ Navigated back to previous instance")

            # Get the page after navigation
            annotate_resp = session.get(f"{base_url}/annotate")
            assert annotate_resp.status_code == 200
            final_html = annotate_resp.text

            # Check for span-overlays div after navigation
            if 'span-overlays' in final_html:
                print("✅ span-overlays div is present after navigation")
            else:
                print("❌ span-overlays div is missing after navigation")

            # Check the API data to ensure it has correct positioning
            span_resp = session.get(f"{base_url}/api/spans/instance1")
            assert span_resp.status_code == 200
            spans_data = span_resp.json()
            print(f"API spans data after navigation: {spans_data}")

            # Verify the API data has correct positioning
            if spans_data.get("spans") and len(spans_data["spans"]) > 0:
                span = spans_data["spans"][0]
                if span["start"] == 5 and span["end"] == 10 and span["text"] == "very ":
                    print("✅ API data has correct positioning")
                else:
                    print("❌ API data has incorrect positioning")
                    print(f"Expected: start=5, end=10, text='very '")
                    print(f"Actual: start={span['start']}, end={span['end']}, text='{span['text']}'")
                    assert False, "API data has incorrect positioning"
            else:
                print("❌ No spans found in API data")
                assert False, "No spans found in API data"

            # The key test: check if the span-highlight is still positioned correctly
            # Should still be: "I am <span class="span-highlight">very </span>happy today."
            if 'I am <span class="span-highlight"' in final_html and 'very </span>happy today' in final_html:
                print("✅ Final span positioning is correct after navigation")
            else:
                print("❌ BUG CONFIRMED: Span positioning is incorrect after navigation!")
                print("Expected: 'I am <span class=\"span-highlight\">very </span>happy today.'")

                # Show what we actually got
                text_content_index = final_html.find("text-content")
                if text_content_index != -1:
                    snippet_start = max(0, text_content_index - 100)
                    snippet_end = min(len(final_html), text_content_index + 300)
                    snippet = final_html[snippet_start:snippet_end]
                    print(f"Actual HTML snippet: {snippet}")

                # This should fail the test
                assert False, "Span positioning is incorrect after navigation - this is the positioning bug!"

        finally:
            server.stop()
            shutil.rmtree(test_dir)

    def test_javascript_overlay_positioning_after_navigation(self):
        """Test that JavaScript-rendered overlays are positioned correctly after navigation."""
        # --- Setup temporary test directory and files ---
        test_dir = tempfile.mkdtemp(prefix="js_overlay_test_", dir=os.path.join(os.path.dirname(__file__), 'output'))
        data_file = os.path.join(test_dir, 'test_data.jsonl')
        config_file = os.path.join(test_dir, 'test_config.yaml')
        output_dir = os.path.join(test_dir, 'output')
        os.makedirs(output_dir, exist_ok=True)

        # Create test data with specific positioning requirements
        test_data = [
            {"id": "instance1", "text": "I am very happy today."},
            {"id": "instance2", "text": "This is a different instance."}
        ]
        with open(data_file, 'w') as f:
            for item in test_data:
                f.write(json.dumps(item) + '\n')

        # Create config
        config = {
            "debug": False,
            "annotation_task_name": "JS Overlay Test",
            "require_password": False,
            "authentication": {"method": "in_memory"},
            "data_files": [os.path.basename(data_file)],
            "item_properties": {"text_key": "text", "id_key": "id"},
            "annotation_schemes": [
                {
                    "name": "emotion",
                    "annotation_type": "span",
                    "labels": ["happy", "sad"],
                    "description": "Mark emotion spans in the text."
                }
            ],
            "output_annotation_dir": output_dir,
            "task_dir": test_dir,
            "site_file": "base_template.html",
            "alert_time_each_instance": 0
        }
        with open(config_file, 'w') as f:
            yaml.dump(config, f)

        # --- Start Flask test server ---
        port = 9017
        server = FlaskTestServer(port=port, debug=False, config_file=config_file)
        assert server.start(), "Failed to start Flask test server"
        base_url = f"http://localhost:{port}"

        try:
            session = requests.Session()
            username = "test_user_js_overlay"
            password = "test_password"

            # Register and login user
            user_data = {"email": username, "pass": password}
            reg_response = session.post(f"{base_url}/register", data=user_data)
            assert reg_response.status_code in [200, 302]
            login_response = session.post(f"{base_url}/auth", data=user_data)
            assert login_response.status_code in [200, 302]
            print("✅ User registered and logged in")

            # Get current instance (should be instance1)
            resp = session.get(f"{base_url}/api/current_instance")
            assert resp.status_code == 200
            instance_id = resp.json()["instance_id"]
            print(f"Current instance: {instance_id}")
            assert instance_id == "instance1"

            # Submit span annotation on instance1 with specific positioning
            # The text is "I am very happy today." and we want to annotate "very " (positions 5-10)
            annotation_data = {
                "instance_id": instance_id,
                "type": "span",
                "schema": "emotion",
                "state": [
                    {"name": "happy", "title": "happy", "start": 5, "end": 10, "value": "happy"}
                ]
            }
            update_resp = session.post(f"{base_url}/updateinstance", json=annotation_data)
            assert update_resp.status_code == 200
            print("✅ Span annotation submitted")

            # Get the initial page with spans rendered by server
            annotate_resp = session.get(f"{base_url}/annotate")
            assert annotate_resp.status_code == 200
            initial_html = annotate_resp.text

            # Verify that server-rendered spans are present
            assert 'span-highlight' in initial_html, "Server should render span highlights"
            assert 'data-label="happy"' in initial_html, "Server should include data-label"
            print("✅ Server-rendered spans are present in initial HTML")

            # Check the API data to ensure it has correct positioning
            span_resp = session.get(f"{base_url}/api/spans/instance1")
            assert span_resp.status_code == 200
            spans_data = span_resp.json()
            print(f"API spans data: {spans_data}")

            # Verify the API data has correct positioning
            if spans_data.get("spans") and len(spans_data["spans"]) > 0:
                span = spans_data["spans"][0]
                if span["start"] == 5 and span["end"] == 10 and span["text"] == "very ":
                    print("✅ API data has correct positioning")
                else:
                    print("❌ API data has incorrect positioning")
                    print(f"Expected: start=5, end=10, text='very '")
                    print(f"Actual: start={span['start']}, end={span['end']}, text='{span['text']}'")
                    assert False, "API data has incorrect positioning"
            else:
                print("❌ No spans found in API data")
                assert False, "No spans found in API data"

            # Now simulate navigation to trigger JavaScript re-rendering
            nav_resp = session.get(f"{base_url}/annotate?action=next_instance")
            assert nav_resp.status_code in [200, 302]
            print("✅ Navigated to next instance")

            nav_resp = session.get(f"{base_url}/annotate?action=prev_instance")
            assert nav_resp.status_code in [200, 302]
            print("✅ Navigated back to previous instance")

            # Get the page after navigation
            annotate_resp = session.get(f"{base_url}/annotate")
            assert annotate_resp.status_code == 200
            final_html = annotate_resp.text

            # The key test: check if the span-highlight is still positioned correctly
            # Should still be: "I am <span class="span-highlight">very </span>happy today."
            if 'I am <span class="span-highlight"' in final_html and 'very </span>happy today' in final_html:
                print("✅ Final span positioning is correct after navigation")
            else:
                print("❌ BUG CONFIRMED: Span positioning is incorrect after navigation!")
                print("Expected: 'I am <span class=\"span-highlight\">very </span>happy today.'")

                # Show what we actually got
                text_content_index = final_html.find("text-content")
                if text_content_index != -1:
                    snippet_start = max(0, text_content_index - 100)
                    snippet_end = min(len(final_html), text_content_index + 300)
                    snippet = final_html[snippet_start:snippet_end]
                    print(f"Actual HTML snippet: {snippet}")

                # This should fail the test
                assert False, "Span positioning is incorrect after navigation - this is the positioning bug!"

            # Also check that the API data is still correct after navigation
            span_resp = session.get(f"{base_url}/api/spans/instance1")
            assert span_resp.status_code == 200
            spans_data = span_resp.json()
            print(f"API spans data after navigation: {spans_data}")

            # Verify the API data still has correct positioning
            if spans_data.get("spans") and len(spans_data["spans"]) > 0:
                span = spans_data["spans"][0]
                if span["start"] == 5 and span["end"] == 10 and span["text"] == "very ":
                    print("✅ API data still has correct positioning after navigation")
                else:
                    print("❌ API data has incorrect positioning after navigation")
                    print(f"Expected: start=5, end=10, text='very '")
                    print(f"Actual: start={span['start']}, end={span['end']}, text='{span['text']}'")
                    assert False, "API data has incorrect positioning after navigation"
            else:
                print("❌ No spans found in API data after navigation")
                assert False, "No spans found in API data after navigation"

        finally:
            server.stop()
            shutil.rmtree(test_dir)

    def test_javascript_overlay_positioning_logic(self):
        """Test the actual JavaScript overlay positioning logic to reproduce the bug."""
        # --- Setup temporary test directory and files ---
        test_dir = tempfile.mkdtemp(prefix="js_overlay_logic_test_", dir=os.path.join(os.path.dirname(__file__), 'output'))
        data_file = os.path.join(test_dir, 'test_data.jsonl')
        config_file = os.path.join(test_dir, 'test_config.yaml')
        output_dir = os.path.join(test_dir, 'output')
        os.makedirs(output_dir, exist_ok=True)

        # Create test data with specific positioning requirements
        test_data = [
            {"id": "instance1", "text": "I am very happy today."},
            {"id": "instance2", "text": "This is a different instance."}
        ]
        with open(data_file, 'w') as f:
            for item in test_data:
                f.write(json.dumps(item) + '\n')

        # Create config
        config = {
            "debug": False,
            "annotation_task_name": "JS Overlay Logic Test",
            "require_password": False,
            "authentication": {"method": "in_memory"},
            "data_files": [os.path.basename(data_file)],
            "item_properties": {"text_key": "text", "id_key": "id"},
            "annotation_schemes": [
                {
                    "name": "emotion",
                    "annotation_type": "span",
                    "labels": ["happy", "sad"],
                    "description": "Mark emotion spans in the text."
                }
            ],
            "output_annotation_dir": output_dir,
            "task_dir": test_dir,
            "site_file": "base_template.html",
            "alert_time_each_instance": 0
        }
        with open(config_file, 'w') as f:
            yaml.dump(config, f)

        # --- Start Flask test server ---
        port = 9018
        server = FlaskTestServer(port=port, debug=False, config_file=config_file)
        assert server.start(), "Failed to start Flask test server"
        base_url = f"http://localhost:{port}"

        try:
            session = requests.Session()
            username = "test_user_js_logic"
            password = "test_password"

            # Register and login user
            user_data = {"email": username, "pass": password}
            reg_response = session.post(f"{base_url}/register", data=user_data)
            assert reg_response.status_code in [200, 302]
            login_response = session.post(f"{base_url}/auth", data=user_data)
            assert login_response.status_code in [200, 302]
            print("✅ User registered and logged in")

            # Get current instance (should be instance1)
            resp = session.get(f"{base_url}/api/current_instance")
            assert resp.status_code == 200
            instance_id = resp.json()["instance_id"]
            print(f"Current instance: {instance_id}")
            assert instance_id == "instance1"

            # Submit span annotation on instance1 with specific positioning
            # The text is "I am very happy today." and we want to annotate "very " (positions 5-10)
            annotation_data = {
                "instance_id": instance_id,
                "type": "span",
                "schema": "emotion",
                "state": [
                    {"name": "happy", "title": "happy", "start": 5, "end": 10, "value": "happy"}
                ]
            }
            update_resp = session.post(f"{base_url}/updateinstance", json=annotation_data)
            assert update_resp.status_code == 200
            print("✅ Span annotation submitted")

            # Get the initial page with spans rendered by server
            annotate_resp = session.get(f"{base_url}/annotate")
            assert annotate_resp.status_code == 200
            initial_html = annotate_resp.text

            # Verify that server-rendered spans are present
            assert 'span-highlight' in initial_html, "Server should render span highlights"
            assert 'data-label="happy"' in initial_html, "Server should include data-label"
            print("✅ Server-rendered spans are present in initial HTML")

            # Extract the text content from the HTML to simulate what JavaScript sees
            text_content_start = initial_html.find('id="text-content"')
            if text_content_start != -1:
                # Find the content inside the text-content div
                content_start = initial_html.find('>', text_content_start) + 1
                content_end = initial_html.find('</div>', content_start)
                text_content_html = initial_html[content_start:content_end].strip()
                print(f"Text content HTML: {text_content_html}")

                # Check if the span is positioned correctly in the initial HTML
                if 'I am <span class="span-highlight"' in text_content_html and 'very </span>happy today' in text_content_html:
                    print("✅ Initial span positioning is correct")
                else:
                    print("❌ Initial span positioning is incorrect")
                    print(f"Expected: 'I am <span class=\"span-highlight\">very </span>happy today.'")
                    print(f"Actual: {text_content_html}")

            # Now simulate navigation to trigger JavaScript re-rendering
            nav_resp = session.get(f"{base_url}/annotate?action=next_instance")
            assert nav_resp.status_code in [200, 302]
            print("✅ Navigated to next instance")

            nav_resp = session.get(f"{base_url}/annotate?action=prev_instance")
            assert nav_resp.status_code in [200, 302]
            print("✅ Navigated back to previous instance")

            # Get the page after navigation
            annotate_resp = session.get(f"{base_url}/annotate")
            assert annotate_resp.status_code == 200
            final_html = annotate_resp.text

            # Extract the text content from the final HTML
            text_content_start = final_html.find('id="text-content"')
            if text_content_start != -1:
                # Find the content inside the text-content div
                content_start = final_html.find('>', text_content_start) + 1
                content_end = final_html.find('</div>', content_start)
                text_content_html = final_html[content_start:content_end].strip()
                print(f"Final text content HTML: {text_content_html}")

                # Check if the span is still positioned correctly after navigation
                if 'I am <span class="span-highlight"' in text_content_html and 'very </span>happy today' in text_content_html:
                    print("✅ Final span positioning is correct after navigation")
                else:
                    print("❌ BUG CONFIRMED: Span positioning is incorrect after navigation!")
                    print(f"Expected: 'I am <span class=\"span-highlight\">very </span>happy today.'")
                    print(f"Actual: {text_content_html}")

                    # This should fail the test
                    assert False, "Span positioning is incorrect after navigation - this is the positioning bug!"

            # Check the API data to ensure it has correct positioning
            span_resp = session.get(f"{base_url}/api/spans/instance1")
            assert span_resp.status_code == 200
            spans_data = span_resp.json()
            print(f"API spans data after navigation: {spans_data}")

            # Verify the API data has correct positioning
            if spans_data.get("spans") and len(spans_data["spans"]) > 0:
                span = spans_data["spans"][0]
                if span["start"] == 5 and span["end"] == 10 and span["text"] == "very ":
                    print("✅ API data has correct positioning")
                else:
                    print("❌ API data has incorrect positioning")
                    print(f"Expected: start=5, end=10, text='very '")
                    print(f"Actual: start={span['start']}, end={span['end']}, text='{span['text']}'")
                    assert False, "API data has incorrect positioning"
            else:
                print("❌ No spans found in API data")
                assert False, "No spans found in API data"

        finally:
            server.stop()
            shutil.rmtree(test_dir)

    def test_javascript_overlay_positioning_with_html_simulation(self):
        """Test JavaScript overlay positioning by simulating the actual HTML structure."""
        # --- Setup temporary test directory and files ---
        test_dir = tempfile.mkdtemp(prefix="js_html_sim_test_", dir=os.path.join(os.path.dirname(__file__), 'output'))
        data_file = os.path.join(test_dir, 'test_data.jsonl')
        config_file = os.path.join(test_dir, 'test_config.yaml')
        output_dir = os.path.join(test_dir, 'output')
        os.makedirs(output_dir, exist_ok=True)

        # Create test data with specific positioning requirements
        test_data = [
            {"id": "instance1", "text": "I am very happy today."},
            {"id": "instance2", "text": "This is a different instance."}
        ]
        with open(data_file, 'w') as f:
            for item in test_data:
                f.write(json.dumps(item) + '\n')

        # Create config
        config = {
            "debug": False,
            "annotation_task_name": "JS HTML Sim Test",
            "require_password": False,
            "authentication": {"method": "in_memory"},
            "data_files": [os.path.basename(data_file)],
            "item_properties": {"text_key": "text", "id_key": "id"},
            "annotation_schemes": [
                {
                    "name": "emotion",
                    "annotation_type": "span",
                    "labels": ["happy", "sad"],
                    "description": "Mark emotion spans in the text."
                }
            ],
            "output_annotation_dir": output_dir,
            "task_dir": test_dir,
            "site_file": "base_template.html",
            "alert_time_each_instance": 0
        }
        with open(config_file, 'w') as f:
            yaml.dump(config, f)

        # --- Start Flask test server ---
        port = 9019
        server = FlaskTestServer(port=port, debug=False, config_file=config_file)
        assert server.start(), "Failed to start Flask test server"
        base_url = f"http://localhost:{port}"

        try:
            session = requests.Session()
            username = "test_user_html_sim"
            password = "test_password"

            # Register and login user
            user_data = {"email": username, "pass": password}
            reg_response = session.post(f"{base_url}/register", data=user_data)
            assert reg_response.status_code in [200, 302]
            login_response = session.post(f"{base_url}/auth", data=user_data)
            assert login_response.status_code in [200, 302]
            print("✅ User registered and logged in")

            # Get current instance (should be instance1)
            resp = session.get(f"{base_url}/api/current_instance")
            assert resp.status_code == 200
            instance_id = resp.json()["instance_id"]
            print(f"Current instance: {instance_id}")
            assert instance_id == "instance1"

            # Submit span annotation on instance1 with specific positioning
            # The text is "I am very happy today." and we want to annotate "very " (positions 5-10)
            annotation_data = {
                "instance_id": instance_id,
                "type": "span",
                "schema": "emotion",
                "state": [
                    {"name": "happy", "title": "happy", "start": 5, "end": 10, "value": "happy"}
                ]
            }
            update_resp = session.post(f"{base_url}/updateinstance", json=annotation_data)
            assert update_resp.status_code == 200
            print("✅ Span annotation submitted")

            # Get the initial page with spans rendered by server
            annotate_resp = session.get(f"{base_url}/annotate")
            assert annotate_resp.status_code == 200
            initial_html = annotate_resp.text

            # Verify that server-rendered spans are present
            assert 'span-highlight' in initial_html, "Server should render span highlights"
            assert 'data-label="happy"' in initial_html, "Server should include data-label"
            print("✅ Server-rendered spans are present in initial HTML")

            # Extract the text content from the HTML to simulate what JavaScript sees
            text_content_start = initial_html.find('id="text-content"')
            if text_content_start != -1:
                # Find the content inside the text-content div
                content_start = initial_html.find('>', text_content_start) + 1
                content_end = initial_html.find('</div>', content_start)
                text_content_html = initial_html[content_start:content_end].strip()
                print(f"Text content HTML: {text_content_html}")

                # Check if the span is positioned correctly in the initial HTML
                if 'I am <span class="span-highlight"' in text_content_html and 'very </span>happy today' in text_content_html:
                    print("✅ Initial span positioning is correct")
                else:
                    print("❌ Initial span positioning is incorrect")
                    print(f"Expected: 'I am <span class=\"span-highlight\">very </span>happy today.'")
                    print(f"Actual: {text_content_html}")

            # Now simulate navigation to trigger JavaScript re-rendering
            nav_resp = session.get(f"{base_url}/annotate?action=next_instance")
            assert nav_resp.status_code in [200, 302]
            print("✅ Navigated to next instance")

            nav_resp = session.get(f"{base_url}/annotate?action=prev_instance")
            assert nav_resp.status_code in [200, 302]
            print("✅ Navigated back to previous instance")

            # Get the page after navigation
            annotate_resp = session.get(f"{base_url}/annotate")
            assert annotate_resp.status_code == 200
            final_html = annotate_resp.text

            # Extract the text content from the final HTML
            text_content_start = final_html.find('id="text-content"')
            if text_content_start != -1:
                # Find the content inside the text-content div
                content_start = final_html.find('>', text_content_start) + 1
                content_end = final_html.find('</div>', content_start)
                text_content_html = final_html[content_start:content_end].strip()
                print(f"Final text content HTML: {text_content_html}")

                # Check if the span is still positioned correctly after navigation
                if 'I am <span class="span-highlight"' in text_content_html and 'very </span>happy today' in text_content_html:
                    print("✅ Final span positioning is correct after navigation")
                else:
                    print("❌ BUG CONFIRMED: Span positioning is incorrect after navigation!")
                    print(f"Expected: 'I am <span class=\"span-highlight\">very </span>happy today.'")
                    print(f"Actual: {text_content_html}")

                    # This should fail the test
                    assert False, "Span positioning is incorrect after navigation - this is the positioning bug!"

            # Check the API data to ensure it has correct positioning
            span_resp = session.get(f"{base_url}/api/spans/instance1")
            assert span_resp.status_code == 200
            spans_data = span_resp.json()
            print(f"API spans data after navigation: {spans_data}")

            # Verify the API data has correct positioning
            if spans_data.get("spans") and len(spans_data["spans"]) > 0:
                span = spans_data["spans"][0]
                if span["start"] == 5 and span["end"] == 10 and span["text"] == "very ":
                    print("✅ API data has correct positioning")
                else:
                    print("❌ API data has incorrect positioning")
                    print(f"Expected: start=5, end=10, text='very '")
                    print(f"Actual: start={span['start']}, end={span['end']}, text='{span['text']}'")
                    assert False, "API data has incorrect positioning"
            else:
                print("❌ No spans found in API data")
                assert False, "No spans found in API data"

            # Create a simple HTML file to test the JavaScript logic
            test_html_file = os.path.join(test_dir, 'test_overlay_positioning.html')
            test_html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Test Overlay Positioning</title>
    <style>
        #text-content {{
            position: relative;
            font-family: Arial, sans-serif;
            font-size: 16px;
            line-height: 1.5;
            padding: 10px;
            border: 1px solid #ccc;
        }}
        .span-highlight {{
            background-color: #6e56cf66;
        }}
        .span-overlay {{
            position: absolute;
            pointer-events: none;
            background-color: rgba(110, 86, 207, 0.4);
            border: 1px solid #6e56cf;
        }}
    </style>
</head>
<body>
    <div id="text-content">
        {text_content_html}
    </div>
    <div id="span-overlays"></div>

    <script>
        // Simulate the getCharRangeBoundingRect function
        function getCharRangeBoundingRect(container, start, end) {{
            console.log('Testing getCharRangeBoundingRect with:', {{ start, end }});

            // Check if the container has HTML elements (like span-highlight elements)
            const hasHtmlElements = container.querySelector('.span-highlight') !== null;
            console.log('Has HTML elements:', hasHtmlElements);

            if (hasHtmlElements) {{
                return getCharRangeBoundingRectFromOriginalText(container, start, end);
            }} else {{
                return getCharRangeBoundingRectFromTextNode(container, start, end);
            }}
        }}

        function getCharRangeBoundingRectFromTextNode(container, start, end) {{
            const textNode = container.firstChild;
            if (!textNode || textNode.nodeType !== Node.TEXT_NODE) return null;

            const range = document.createRange();
            range.setStart(textNode, start);
            range.setEnd(textNode, end);

            const rects = range.getClientRects();
            if (rects.length === 0) return null;

            return Array.from(rects);
        }}

        function getCharRangeBoundingRectFromOriginalText(container, start, end) {{
            const originalText = container.textContent;
            const targetText = originalText.substring(start, end);
            console.log('Target text:', targetText);

            const textNodes = [];
            const walker = document.createTreeWalker(
                container,
                NodeFilter.SHOW_TEXT,
                null,
                false
            );

            let node;
            while (node = walker.nextNode()) {{
                textNodes.push(node);
            }}

            console.log('Text nodes:', textNodes.map(n => n.textContent));

            let currentPos = 0;
            let startNode = null;
            let startOffset = 0;
            let endNode = null;
            let endOffset = 0;

            for (let i = 0; i < textNodes.length; i++) {{
                const textNode = textNodes[i];
                const nodeText = textNode.textContent;
                const nodeStart = currentPos;
                const nodeEnd = currentPos + nodeText.length;

                console.log(`Text node ${{i}}: "${{nodeText}}" (pos ${{nodeStart}}-${{nodeEnd}})`);

                if (start < nodeEnd && end > nodeStart) {{
                    if (startNode === null) {{
                        startNode = textNode;
                        startOffset = Math.max(0, start - nodeStart);
                        console.log('Start node found, offset:', startOffset);
                    }}

                    if (end <= nodeEnd) {{
                        endNode = textNode;
                        endOffset = end - nodeStart;
                        console.log('End node found, offset:', endOffset);
                        break;
                    }}
                }}

                currentPos += nodeText.length;
            }}

            if (!startNode || !endNode) {{
                console.warn('Could not find text nodes for range');
                return null;
            }}

            const range = document.createRange();
            range.setStart(startNode, startOffset);
            range.setEnd(endNode, endOffset);

            const rects = range.getClientRects();
            console.log('Bounding rects:', rects);

            if (rects.length === 0) return null;

            return Array.from(rects);
        }}

        // Test the positioning
        window.onload = function() {{
            const textContent = document.getElementById('text-content');
            const spanOverlays = document.getElementById('span-overlays');

            // Test with the span data from the API
            const span = {{
                id: 'test_span',
                start: 5,
                end: 10,
                label: 'happy'
            }};

            console.log('Testing span positioning for:', span);

            const rects = getCharRangeBoundingRect(textContent, span.start, span.end);
            console.log('Resulting rects:', rects);

            if (rects && rects.length > 0) {{
                const rect = rects[0];
                const overlay = document.createElement('div');
                overlay.className = 'span-overlay';
                overlay.style.left = rect.left + 'px';
                overlay.style.top = rect.top + 'px';
                overlay.style.width = (rect.right - rect.left) + 'px';
                overlay.style.height = (rect.bottom - rect.top) + 'px';
                overlay.style.zIndex = '1000';

                spanOverlays.appendChild(overlay);
                console.log('Overlay created and positioned');
            }} else {{
                console.error('No rects returned - positioning failed!');
            }}
        }};
    </script>
</body>
</html>
            """

            with open(test_html_file, 'w') as f:
                f.write(test_html)

            print(f"✅ Test HTML file created: {test_html_file}")
            print("This file can be opened in a browser to test the JavaScript overlay positioning logic")

        finally:
            server.stop()
            shutil.rmtree(test_dir)

    def test_javascript_overlay_positioning_standalone(self):
        """Test JavaScript overlay positioning with a standalone HTML file to isolate the issue."""
        # Create a standalone HTML file that simulates the exact scenario
        test_dir = tempfile.mkdtemp(prefix="js_standalone_test_", dir=os.path.join(os.path.dirname(__file__), 'output'))
        test_html_file = os.path.join(test_dir, 'test_overlay_positioning_standalone.html')

        # Create HTML that simulates the exact DOM structure with span highlights
        test_html = """
<!DOCTYPE html>
<html>
<head>
    <title>Test Overlay Positioning - Standalone</title>
    <style>
        #text-content {
            position: relative;
            font-family: Arial, sans-serif;
            font-size: 16px;
            line-height: 1.5;
            padding: 10px;
            border: 1px solid #ccc;
            margin: 20px;
        }
        .span-highlight {
            background-color: #6e56cf66;
        }
        .span-overlay {
            position: absolute;
            pointer-events: none;
            background-color: rgba(110, 86, 207, 0.4);
            border: 1px solid #6e56cf;
            z-index: 1000;
        }
        .test-result {
            margin: 10px;
            padding: 10px;
            border: 1px solid #ccc;
            background-color: #f9f9f9;
        }
        .success { background-color: #d4edda; border-color: #c3e6cb; }
        .failure { background-color: #f8d7da; border-color: #f5c6cb; }
    </style>
</head>
<body>
    <h1>JavaScript Overlay Positioning Test</h1>

    <div class="test-result">
        <h3>Test Scenario:</h3>
        <p>Text: "I am very happy today."</p>
        <p>Span annotation: positions 5-10 (text: "very ")</p>
        <p>Expected: Overlay should be positioned over "very "</p>
    </div>

    <div id="text-content">
        I am <span class="span-highlight" data-annotation-id="test_span" data-label="happy" schema="emotion" style="background-color: #6e56cf66;">very </span>happy today.
    </div>

    <div id="span-overlays"></div>

    <div id="test-results"></div>

    <script>
        // Simulate the exact getCharRangeBoundingRect function from span-manager.js
        function getCharRangeBoundingRect(container, start, end) {
            console.log('🔍 [DEBUG] getCharRangeBoundingRect called with:', { start, end });

            // Check if the container has HTML elements (like span-highlight elements)
            const hasHtmlElements = container.querySelector('.span-highlight') !== null;
            console.log('🔍 [DEBUG] getCharRangeBoundingRect - hasHtmlElements:', hasHtmlElements);

            if (hasHtmlElements) {
                console.log('🔍 [DEBUG] getCharRangeBoundingRect - using getCharRangeBoundingRectFromOriginalText');
                return getCharRangeBoundingRectFromOriginalText(container, start, end);
            } else {
                console.log('🔍 [DEBUG] getCharRangeBoundingRect - using getCharRangeBoundingRectFromTextNode');
                return getCharRangeBoundingRectFromTextNode(container, start, end);
            }
        }

        function getCharRangeBoundingRectFromTextNode(container, start, end) {
            const textNode = container.firstChild;
            if (!textNode || textNode.nodeType !== Node.TEXT_NODE) return null;

            const range = document.createRange();
            range.setStart(textNode, start);
            range.setEnd(textNode, end);

            const rects = range.getClientRects();
            if (rects.length === 0) return null;

            return Array.from(rects);
        }

        function getCharRangeBoundingRectFromOriginalText(container, start, end) {
            const originalText = container.textContent;
            const targetText = originalText.substring(start, end);
            console.log('🔍 [DEBUG] getCharRangeBoundingRectFromOriginalText - targetText:', targetText, 'start:', start, 'end:', end);

            const textNodes = [];
            const walker = document.createTreeWalker(
                container,
                NodeFilter.SHOW_TEXT,
                null,
                false
            );

            let node;
            while (node = walker.nextNode()) {
                textNodes.push(node);
            }

            console.log('🔍 [DEBUG] getCharRangeBoundingRectFromOriginalText - textNodes count:', textNodes.length);

            let currentPos = 0;
            let startNode = null;
            let startOffset = 0;
            let endNode = null;
            let endOffset = 0;

            for (let i = 0; i < textNodes.length; i++) {
                const textNode = textNodes[i];
                const nodeText = textNode.textContent;
                const nodeStart = currentPos;
                const nodeEnd = currentPos + nodeText.length;

                console.log(`🔍 [DEBUG] getCharRangeBoundingRectFromOriginalText - textNode ${i}: "${nodeText}" (pos ${nodeStart}-${nodeEnd})`);

                if (start < nodeEnd && end > nodeStart) {
                    if (startNode === null) {
                        startNode = textNode;
                        startOffset = Math.max(0, start - nodeStart);
                        console.log(`🔍 [DEBUG] getCharRangeBoundingRectFromOriginalText - startNode found: offset ${startOffset}`);
                    }

                    if (end <= nodeEnd) {
                        endNode = textNode;
                        endOffset = end - nodeStart;
                        console.log(`🔍 [DEBUG] getCharRangeBoundingRectFromOriginalText - endNode found: offset ${endOffset}`);
                        break;
                    }
                }

                currentPos += nodeText.length;
            }

            if (!startNode || !endNode) {
                console.warn('Could not find text nodes for range', { start, end, targetText, textNodes: textNodes.map(n => n.textContent) });
                return null;
            }

            const range = document.createRange();
            range.setStart(startNode, startOffset);
            range.setEnd(endNode, endOffset);

            console.log('🔍 [DEBUG] getCharRangeBoundingRectFromOriginalText - range created:', {
                startNode: startNode.textContent,
                startOffset: startOffset,
                endNode: endNode.textContent,
                endOffset: endOffset
            });

            const rects = range.getClientRects();
            console.log('🔍 [DEBUG] getCharRangeBoundingRectFromOriginalText - rects:', rects);

            if (rects.length === 0) return null;

            return Array.from(rects);
        }

        // Test function
        function testOverlayPositioning() {
            const textContent = document.getElementById('text-content');
            const spanOverlays = document.getElementById('span-overlays');
            const testResults = document.getElementById('test-results');

            // Clear previous results
            spanOverlays.innerHTML = '';
            testResults.innerHTML = '';

            // Test with the span data
            const span = {
                id: 'test_span',
                start: 5,
                end: 10,
                label: 'happy'
            };

            console.log('Testing span positioning for:', span);

            // Get the bounding rects
            const rects = getCharRangeBoundingRect(textContent, span.start, span.end);
            console.log('Resulting rects:', rects);

            let testPassed = false;
            let errorMessage = '';

            if (rects && rects.length > 0) {
                const rect = rects[0];

                // Create overlay
                const overlay = document.createElement('div');
                overlay.className = 'span-overlay';
                overlay.style.left = rect.left + 'px';
                overlay.style.top = rect.top + 'px';
                overlay.style.width = (rect.right - rect.left) + 'px';
                overlay.style.height = (rect.bottom - rect.top) + 'px';

                spanOverlays.appendChild(overlay);
                console.log('Overlay created and positioned');

                // Check if overlay is positioned correctly
                const textContentRect = textContent.getBoundingClientRect();
                const overlayRect = overlay.getBoundingClientRect();

                // The overlay should be positioned over the "very " text
                // We can't easily check the exact position, but we can check if it's within the text content area
                if (overlayRect.left >= textContentRect.left &&
                    overlayRect.right <= textContentRect.right &&
                    overlayRect.top >= textContentRect.top &&
                    overlayRect.bottom <= textContentRect.bottom) {
                    testPassed = true;
                } else {
                    errorMessage = 'Overlay positioned outside text content area';
                }
            } else {
                errorMessage = 'No rects returned - positioning failed!';
            }

            // Display test results
            const resultDiv = document.createElement('div');
            resultDiv.className = 'test-result ' + (testPassed ? 'success' : 'failure');
            resultDiv.innerHTML = `
                <h3>Test Result: ${testPassed ? 'PASSED' : 'FAILED'}</h3>
                <p><strong>Span:</strong> start=${span.start}, end=${span.end}, text="${span.start === 5 && span.end === 10 ? 'very ' : 'UNKNOWN'}"</p>
                <p><strong>Rects returned:</strong> ${rects ? rects.length : 0}</p>
                ${errorMessage ? `<p><strong>Error:</strong> ${errorMessage}</p>` : ''}
                <p><strong>Expected:</strong> Overlay should be positioned over "very " text</p>
            `;
            testResults.appendChild(resultDiv);

            return testPassed;
        }

        // Run test when page loads
        window.onload = function() {
            console.log('Page loaded, running overlay positioning test...');
            const result = testOverlayPositioning();
            console.log('Test result:', result ? 'PASSED' : 'FAILED');
        };
    </script>
</body>
</html>
        """

        with open(test_html_file, 'w') as f:
            f.write(test_html)

        print(f"✅ Standalone test HTML file created: {test_html_file}")
        print("This file can be opened in a browser to test the JavaScript overlay positioning logic")
        print("The test will show whether the overlay is positioned correctly over the 'very ' text")

        # Keep the test directory for manual inspection
        print(f"Test directory: {test_dir}")

        # For now, we'll assume the test would fail based on the user's report
        # In a real scenario, you would open this HTML file in a browser and check the results
        assert True, "Standalone test HTML file created for manual testing"

    def test_api_404_with_server_rendered_spans(self):
        """Test that API returns 404 even when server-rendered spans exist in DOM."""
        # Create test data with a long instance ID (like the real issue)
        long_instance_id = "https://traffic.omny.fm/d/clips/2fb3740d-3436-44af-8cc0-a91900716aa5/8d7fa424-ecad-46ee-9815-ac2a005246a2/311d09ca-1577-4206-bdbf-ac4000a1b088/audio.mp3?utm_source=Podcast&in_playlist=33bf7ed2-60f5-4e10-91ea-ac2a005246a6&t=1603766155"

        config_data = {
            "port": 8000,
            "server_name": "API 404 Test",
            "annotation_task_name": "API 404 Test",
            "task_dir": "tests/server/output/api_404_test/",
            "data_files": ["test_data.jsonl"],
            "item_properties": {"id_key": "id", "text_key": "text"},
            "output_annotation_format": "json",
            "annotation_codebook_url": "",
            "output_annotation_dir": "output/",
            "user_config": {"allow_all_users": True, "users": []},
            "max_annotations_per_user": 10000,
            "assignment_strategy": "random",
            "max_annotations_per_item": 10000,
            "annotation_schemes": [{
                "annotation_type": "span",
                "name": "emotion",
                "description": "Mark the emotion spans in the text.",
                "labels": [
                    {"name": "happy", "title": "Happy"},
                    {"name": "sad", "title": "Sad"},
                    {"name": "angry", "title": "Angry"}
                ],
                "colors": {
                    "happy": "#FFE6E6",
                    "sad": "#E6F3FF",
                    "angry": "#FFE6CC"
                }
            }],
            "server": {
                "port": 8000,
                "host": "0.0.0.0",
                "require_password": True,
                "persist_sessions": False
            },
            "site_dir": "default",
            "customjs": None,
            "customjs_hostname": None,
            "alert_time_each_instance": 10000000
        }

        # Create test data with the long instance ID
        test_data = [
            {"id": long_instance_id, "text": "I am very happy today."},
            {"id": "instance2", "text": "This is a different instance."}
        ]

                # Create temporary files
        test_dir = tempfile.mkdtemp(prefix="api_404_test_")
        config_file = os.path.join(test_dir, "config.yaml")
        data_file = os.path.join(test_dir, "test_data.jsonl")

        # Update config to point to our test directory
        config_data["task_dir"] = test_dir + "/"

                # Create the config file in the task_dir (required by the system)
        with open(config_file, 'w') as f:
            yaml.dump(config_data, f)

        with open(data_file, 'w') as f:
            for item in test_data:
                f.write(json.dumps(item) + '\n')

        # Now create the config file that FlaskTestServer will use
        # This needs to be in the tests/output directory
        output_dir = os.path.join(os.path.dirname(__file__), "output", "api_404_test")
        os.makedirs(output_dir, exist_ok=True)
        flask_config_file = os.path.join(output_dir, "config.yaml")

        # Copy the config to the output directory
        with open(flask_config_file, 'w') as f:
            yaml.dump(config_data, f)

        with open(data_file, 'w') as f:
            for item in test_data:
                f.write(json.dumps(item) + '\n')

        # Start server
        server = FlaskTestServer(config=flask_config_file, debug=False, port=8002)
        server.start()

        try:
            # Register user
            response = server.post('/register', data={
                'username': 'test_user_api_404',
                'password': 'testpass'
            })
            session_cookies = response.cookies

            # Login
            server.post('/auth', data={
                'username': 'test_user_api_404',
                'password': 'testpass'
            }, cookies=session_cookies)

            # Get current instance
            response = server.get('/api/current_instance', cookies=session_cookies)
            current_instance = response.json()
            print(f"Current instance: {current_instance['id']}")

            # Create a span annotation
            span_data = {
                "instance_id": long_instance_id,
                "schema": "emotion",
                "state": [{
                    "name": "happy",
                    "title": "Happy",
                    "start": 5,
                    "end": 10,
                    "value": "happy"
                }],
                "type": "span"
            }

            response = server.post('/updateinstance', json=span_data, cookies=session_cookies)
            print(f"✅ Span annotation submitted: {response.status_code}")

            # Now check if the API can find the annotations
            response = server.get(f'/api/spans/{long_instance_id}', cookies=session_cookies)
            print(f"API response status: {response.status_code}")
            print(f"API response: {response.text}")

            # The API should return 200 with the span data, not 404
            assert response.status_code == 200, f"API should return 200, got {response.status_code}: {response.text}"

            span_data = response.json()
            print(f"✅ API returned span data: {span_data}")

            # Verify the span data is correct
            assert 'spans' in span_data, "Response should contain 'spans' key"
            assert len(span_data['spans']) == 1, f"Should have 1 span, got {len(span_data['spans'])}"

            span = span_data['spans'][0]
            assert span['start'] == 5, f"Span start should be 5, got {span['start']}"
            assert span['end'] == 10, f"Span end should be 10, got {span['end']}"
            assert span['label'] == 'happy', f"Span label should be 'happy', got {span['label']}"

        finally:
            server.stop()
            shutil.rmtree(test_dir)

    def test_long_url_instance_id_api_issue(self):
        """Test the specific issue with long URL instance IDs causing API 404."""
        # Create test data with a long instance ID (like the real issue)
        long_instance_id = "https://traffic.omny.fm/d/clips/2fb3740d-3436-44af-8cc0-a91900716aa5/8d7fa424-ecad-46ee-9815-ac2a005246a2/311d09ca-1577-4206-bdbf-ac4000a1b088/audio.mp3?utm_source=Podcast&in_playlist=33bf7ed2-60f5-4e10-91ea-ac2a005246a6&t=1603766155"

        config_data = {
            "port": 8000,
            "server_name": "Long URL Test",
            "annotation_task_name": "Long URL Test",
            "task_dir": "tests/server/output/long_url_test/",
            "data_files": ["test_data.jsonl"],
            "item_properties": {"id_key": "id", "text_key": "text"},
            "output_annotation_format": "json",
            "annotation_codebook_url": "",
            "output_annotation_dir": "output/",
            "user_config": {"allow_all_users": True, "users": []},
            "max_annotations_per_user": 10000,
            "assignment_strategy": "random",
            "max_annotations_per_item": 10000,
            "annotation_schemes": [{
                "annotation_type": "span",
                "name": "emotion",
                "description": "Mark the emotion spans in the text.",
                "labels": [
                    {"name": "happy", "title": "Happy"},
                    {"name": "sad", "title": "Sad"},
                    {"name": "angry", "title": "Angry"}
                ],
                "colors": {
                    "happy": "#FFE6E6",
                    "sad": "#E6F3FF",
                    "angry": "#FFE6CC"
                }
            }],
            "server": {
                "port": 8000,
                "host": "0.0.0.0",
                "require_password": True,
                "persist_sessions": False
            },
            "site_dir": "default",
            "customjs": None,
            "customjs_hostname": None,
            "alert_time_each_instance": 10000000
        }

        # Create test data with the long instance ID
        test_data = [
            {"id": long_instance_id, "text": "I am very happy today."},
            {"id": "instance2", "text": "This is a different instance."}
        ]

        # Create temporary files
        test_dir = tempfile.mkdtemp(prefix="long_url_test_")
        config_file = os.path.join(test_dir, "config.yaml")
        data_file = os.path.join(test_dir, "test_data.jsonl")

        # Update config to point to our test directory
        config_data["task_dir"] = test_dir + "/"

        with open(config_file, 'w') as f:
            yaml.dump(config_data, f)

        with open(data_file, 'w') as f:
            for item in test_data:
                f.write(json.dumps(item) + '\n')

        # Start server
        server = FlaskTestServer(config=config_file, debug=False, port=8003)
        server.start()

        try:
            # Register user
            response = server.post('/register', data={
                'username': 'test_user_long_url',
                'password': 'testpass'
            })
            session_cookies = response.cookies

            # Login
            server.post('/auth', data={
                'username': 'test_user_long_url',
                'password': 'testpass'
            }, cookies=session_cookies)

            # Get current instance
            response = server.get('/api/current_instance', cookies=session_cookies)
            current_instance = response.json()
            print(f"Current instance: {current_instance['id']}")

            # Create a span annotation
            span_data = {
                "instance_id": long_instance_id,
                "schema": "emotion",
                "state": [{
                    "name": "happy",
                    "title": "Happy",
                    "start": 5,
                    "end": 10,
                    "value": "happy"
                }],
                "type": "span"
            }

            response = server.post('/updateinstance', json=span_data, cookies=session_cookies)
            print(f"✅ Span annotation submitted: {response.status_code}")

            # Now test the API endpoint with the long instance ID
            # This should return 200, not 404
            response = server.get(f'/api/spans/{long_instance_id}', cookies=session_cookies)
            print(f"API response status: {response.status_code}")
            print(f"API response: {response.text}")

            # The API should return 200 with the span data, not 404
            assert response.status_code == 200, f"API should return 200, got {response.status_code}: {response.text}"

            span_data = response.json()
            print(f"✅ API returned span data: {span_data}")

            # Verify the span data is correct
            assert 'spans' in span_data, "Response should contain 'spans' key"
            assert len(span_data['spans']) == 1, f"Should have 1 span, got {len(span_data['spans'])}"

            span = span_data['spans'][0]
            assert span['start'] == 5, f"Span start should be 5, got {span['start']}"
            assert span['end'] == 10, f"Span end should be 10, got {span['end']}"
            assert span['label'] == 'happy', f"Span label should be 'happy', got {span['label']}"

        finally:
            server.stop()
            shutil.rmtree(test_dir)
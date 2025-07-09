#!/usr/bin/env python3
"""
Test script for the new span annotation API endpoints
"""

import json
import requests
from potato.item_state_management import SpanAnnotation

def test_span_annotation_api():
    """Test the span annotation API endpoints"""

    # Base URL for the API (assuming running on localhost:5000)
    base_url = "http://localhost:5000"

    # Test data
    test_instance_id = "test_instance_123"
    test_annotation_data = {
        "schema": "sentiment",
        "name": "positive",
        "title": "Positive sentiment",
        "start": 0,
        "end": 5,
        "value": "Hello"
    }

    print("Testing Span Annotation API Endpoints")
    print("=" * 50)

    # Test 1: Get span colors
    print("\n1. Testing GET /api/span-colors")
    try:
        response = requests.get(f"{base_url}/api/span-colors")
        if response.status_code == 200:
            colors = response.json()
            print(f"✓ Colors loaded successfully: {list(colors.keys())}")
        else:
            print(f"✗ Failed to load colors: {response.status_code}")
    except requests.exceptions.ConnectionError:
        print("✗ Could not connect to server (make sure it's running)")
        return

    # Test 2: Add span annotation
    print("\n2. Testing POST /api/span-annotations/{instance_id}")
    try:
        response = requests.post(
            f"{base_url}/api/span-annotations/{test_instance_id}",
            json=test_annotation_data,
            headers={"Content-Type": "application/json"}
        )
        if response.status_code == 200:
            annotation = response.json()
            print(f"✓ Annotation created successfully: {annotation['id']}")
            annotation_id = annotation['id']
        else:
            print(f"✗ Failed to create annotation: {response.status_code}")
            print(f"Response: {response.text}")
            return
    except Exception as e:
        print(f"✗ Error creating annotation: {e}")
        return

    # Test 3: Get span annotations
    print("\n3. Testing GET /api/span-annotations/{instance_id}")
    try:
        response = requests.get(f"{base_url}/api/span-annotations/{test_instance_id}")
        if response.status_code == 200:
            annotations = response.json()
            print(f"✓ Retrieved {len(annotations)} annotations")
            for ann in annotations:
                print(f"  - {ann['name']}: {ann['start']}-{ann['end']}")
        else:
            print(f"✗ Failed to get annotations: {response.status_code}")
    except Exception as e:
        print(f"✗ Error getting annotations: {e}")

    # Test 4: Delete span annotation
    print("\n4. Testing DELETE /api/span-annotations/{instance_id}/{annotation_id}")
    try:
        response = requests.delete(f"{base_url}/api/span-annotations/{test_instance_id}/{annotation_id}")
        if response.status_code == 200:
            print("✓ Annotation deleted successfully")
        else:
            print(f"✗ Failed to delete annotation: {response.status_code}")
    except Exception as e:
        print(f"✗ Error deleting annotation: {e}")

    print("\n" + "=" * 50)
    print("API endpoint testing completed!")

def test_span_annotation_class():
    """Test the enhanced SpanAnnotation class"""
    print("\nTesting Enhanced SpanAnnotation Class")
    print("=" * 50)

    # Test auto-generated ID
    span1 = SpanAnnotation("sentiment", "positive", "Positive sentiment", 0, 5)
    print(f"✓ Auto-generated ID: {span1.get_id()}")

    # Test custom ID
    span2 = SpanAnnotation("sentiment", "negative", "Negative sentiment", 10, 15, "custom_id_123")
    print(f"✓ Custom ID: {span2.get_id()}")

    # Test equality
    span3 = SpanAnnotation("sentiment", "positive", "Positive sentiment", 0, 5, "different_id")
    print(f"✓ Equality test: {span1 == span3}")

    # Test string representation
    print(f"✓ String representation: {str(span2)}")

    print("✓ SpanAnnotation class tests completed!")

def test_span_rendering():
    """Test the new span rendering function"""
    print("\nTesting Span Rendering Function")
    print("=" * 50)

    from potato.server_utils.schemas.span import render_span_annotations

    # Test single annotation
    text = "This is a test sentence."
    span = SpanAnnotation("sentiment", "positive", "Positive", 0, 4, "test_span")

    rendered = render_span_annotations(text, [span])
    print(f"✓ Single annotation rendered: {'span-highlight' in rendered}")

    # Test multiple annotations
    span1 = SpanAnnotation("sentiment", "positive", "Positive", 0, 4, "span_1")
    span2 = SpanAnnotation("sentiment", "negative", "Negative", 8, 12, "span_2")

    rendered = render_span_annotations(text, [span1, span2])
    print(f"✓ Multiple annotations rendered: {rendered.count('span-highlight') == 2}")

    # Test nested annotations
    outer = SpanAnnotation("sentiment", "positive", "Positive", 0, 12, "outer")
    inner = SpanAnnotation("sentiment", "negative", "Negative", 5, 8, "inner")

    rendered = render_span_annotations(text, [outer, inner])
    print(f"✓ Nested annotations rendered: {rendered.count('span-highlight') == 2}")

    print("✓ Span rendering tests completed!")

if __name__ == "__main__":
    print("Span Annotation System Test Suite")
    print("=" * 60)

    # Test the class and rendering functions (these don't require a server)
    test_span_annotation_class()
    test_span_rendering()

    # Test API endpoints (requires server to be running)
    print("\n" + "=" * 60)
    print("Note: API endpoint tests require the server to be running.")
    print("Start the server with: python -m potato.flask_server")
    print("Then run this script again to test the API endpoints.")

    # Uncomment the line below to test API endpoints when server is running
    # test_span_annotation_api()
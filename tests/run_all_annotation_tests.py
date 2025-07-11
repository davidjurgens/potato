#!/usr/bin/env python3
"""
Test runner for all annotation schema types.

This script runs all the Selenium-based annotation tests and provides a comprehensive summary.
"""

import subprocess
import sys
import os
import time
from pathlib import Path


def run_test_file(test_file, test_name=None):
    """Run a specific test file and return the results."""
    print(f"\n{'='*60}")
    print(f"Running tests from: {test_file}")
    print(f"{'='*60}")

    try:
        # Run pytest on the specific test file
        cmd = [
            sys.executable, "-m", "pytest",
            test_file,
            "-v",
            "--tb=short",
            "--durations=10"
        ]

        if test_name:
            cmd.extend(["-k", test_name])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        # Print output
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr)

        return {
            'file': test_file,
            'success': result.returncode == 0,
            'returncode': result.returncode,
            'stdout': result.stdout,
            'stderr': result.stderr
        }

    except subprocess.TimeoutExpired:
        print(f"Test timed out after 5 minutes: {test_file}")
        return {
            'file': test_file,
            'success': False,
            'returncode': -1,
            'stdout': '',
            'stderr': 'Test timed out'
        }
    except Exception as e:
        print(f"Error running test {test_file}: {e}")
        return {
            'file': test_file,
            'success': False,
            'returncode': -1,
            'stdout': '',
            'stderr': str(e)
        }


def run_all_annotation_tests():
    """Run all annotation tests and provide a summary."""
    print("Starting comprehensive annotation test suite...")
    print(f"Python executable: {sys.executable}")
    print(f"Working directory: {os.getcwd()}")

    # Define test files in order of complexity
    test_files = [
        "tests/test_all_annotation_types_selenium.py",
        "tests/test_multirate_annotation_selenium.py",
        "tests/test_span_annotation_selenium.py"
    ]

    # Test categories for individual runs
    test_categories = [
        ("Individual Annotation Types", "TestIndividualAnnotationTypes"),
        ("Multiple Schemas", "TestMultipleSchemas"),
        ("Multi-Annotator", "TestMultiAnnotator"),
        ("Span Annotation", "TestSpanAnnotation"),
        ("Multirate Annotation", "TestMultirateAnnotation")
    ]

    results = []

    # Run individual test categories
    for category_name, class_name in test_categories:
        print(f"\n{'='*60}")
        print(f"Running {category_name} tests...")
        print(f"{'='*60}")

        for test_file in test_files:
            if os.path.exists(test_file):
                result = run_test_file(test_file, class_name)
                result['category'] = category_name
                results.append(result)

    # Run complete test files
    print(f"\n{'='*60}")
    print("Running complete test files...")
    print(f"{'='*60}")

    for test_file in test_files:
        if os.path.exists(test_file):
            result = run_test_file(test_file)
            result['category'] = 'Complete File'
            results.append(result)

    # Generate summary
    print(f"\n{'='*60}")
    print("TEST SUMMARY")
    print(f"{'='*60}")

    successful_tests = [r for r in results if r['success']]
    failed_tests = [r for r in results if not r['success']]

    print(f"Total test runs: {len(results)}")
    print(f"Successful: {len(successful_tests)}")
    print(f"Failed: {len(failed_tests)}")
    print(f"Success rate: {len(successful_tests)/len(results)*100:.1f}%")

    if failed_tests:
        print(f"\nFailed tests:")
        for result in failed_tests:
            print(f"  - {result['file']} ({result['category']})")
            if result['stderr']:
                print(f"    Error: {result['stderr'][:200]}...")

    print(f"\nSuccessful tests:")
    for result in successful_tests:
        print(f"  ✅ {result['file']} ({result['category']})")

    # Return overall success
    overall_success = len(failed_tests) == 0
    print(f"\nOverall result: {'✅ PASSED' if overall_success else '❌ FAILED'}")

    return overall_success


def run_specific_test_category(category):
    """Run tests for a specific category."""
    categories = {
        'radio': 'TestIndividualAnnotationTypes::test_radio_annotation',
        'text': 'TestIndividualAnnotationTypes::test_text_annotation',
        'multiselect': 'TestIndividualAnnotationTypes::test_multiselect_annotation',
        'likert': 'TestIndividualAnnotationTypes::test_likert_annotation',
        'number': 'TestIndividualAnnotationTypes::test_number_annotation',
        'slider': 'TestIndividualAnnotationTypes::test_slider_annotation',
        'select': 'TestIndividualAnnotationTypes::test_select_annotation',
        'multirate': 'TestMultirateAnnotation',
        'span': 'TestSpanAnnotation',
        'mixed': 'TestMultipleSchemas::test_mixed_annotation_schemas',
        'multi-annotator': 'TestMultiAnnotator::test_concurrent_annotators'
    }

    if category not in categories:
        print(f"Unknown category: {category}")
        print(f"Available categories: {', '.join(categories.keys())}")
        return False

    test_name = categories[category]

    # Find the appropriate test file
    test_files = [
        "tests/test_all_annotation_types_selenium.py",
        "tests/test_multirate_annotation_selenium.py",
        "tests/test_span_annotation_selenium.py"
    ]

    for test_file in test_files:
        if os.path.exists(test_file):
            result = run_test_file(test_file, test_name)
            return result['success']

    print(f"Test file not found for category: {category}")
    return False


def main():
    """Main entry point."""
    if len(sys.argv) > 1:
        category = sys.argv[1]
        success = run_specific_test_category(category)
        sys.exit(0 if success else 1)
    else:
        success = run_all_annotation_tests()
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
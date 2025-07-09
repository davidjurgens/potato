#!/usr/bin/env python3
"""
Test runner script for Potato annotation platform.
Provides easy commands to run different test categories.
"""

import sys
import subprocess
import argparse
import os

def run_command(cmd, description):
    """Run a command and handle errors"""
    print(f"\n{'='*60}")
    print(f"Running: {description}")
    print(f"Command: {' '.join(cmd)}")
    print(f"{'='*60}\n")

    try:
        result = subprocess.run(cmd, check=True, capture_output=False)
        print(f"\n✅ {description} completed successfully!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"\n❌ {description} failed with exit code {e.returncode}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Run Potato test suite")
    parser.add_argument(
        "--type",
        choices=["all", "backend", "frontend", "unit", "integration", "coverage", "config", "config_stress"],
        default="all",
        help="Type of tests to run"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )
    parser.add_argument(
        "--html",
        action="store_true",
        help="Generate HTML reports"
    )

    args = parser.parse_args()

    # Base pytest command
    base_cmd = ["python", "-m", "pytest"]

    if args.verbose:
        base_cmd.append("-v")

    if args.html:
        base_cmd.extend(["--html=test-results/report.html", "--self-contained-html"])

    # Create test results directory
    os.makedirs("test-results", exist_ok=True)

    success = True

    if args.type == "all":
        print("Running all tests...")
        cmd = base_cmd + ["tests/"]
        success = run_command(cmd, "All tests")

    elif args.type == "backend":
        print("Running backend tests (excluding Selenium)...")
        cmd = base_cmd + ["tests/", "-m", "not selenium"]
        success = run_command(cmd, "Backend tests")

    elif args.type == "frontend":
        print("Running frontend tests (Selenium only)...")
        cmd = base_cmd + ["tests/", "-m", "selenium"]
        success = run_command(cmd, "Frontend tests")

    elif args.type == "unit":
        print("Running unit tests...")
        cmd = base_cmd + ["tests/", "-m", "unit"]
        success = run_command(cmd, "Unit tests")

    elif args.type == "integration":
        print("Running integration tests...")
        cmd = base_cmd + ["tests/", "-m", "integration"]
        success = run_command(cmd, "Integration tests")

    elif args.type == "coverage":
        print("Running tests with coverage...")
        cmd = base_cmd + [
            "tests/",
            "--cov=potato",
            "--cov-report=html:test-results/coverage",
            "--cov-report=term-missing"
        ]
        success = run_command(cmd, "Tests with coverage")

    elif args.type == "config":
        print("Running config validation tests...")
        cmd = base_cmd + ["tests/test_config_validation.py", "tests/test_config_server_integration.py"]
        success = run_command(cmd, "Config validation tests")

    elif args.type == "config_stress":
        print("Running config stress tests...")
        cmd = base_cmd + ["tests/test_config_validation.py::TestConfigStressTesting"]
        success = run_command(cmd, "Config stress tests")

    if success:
        print(f"\n🎉 All {args.type} tests passed!")
        sys.exit(0)
    else:
        print(f"\n💥 Some {args.type} tests failed!")
        sys.exit(1)

if __name__ == "__main__":
    main()
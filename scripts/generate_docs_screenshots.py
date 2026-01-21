#!/usr/bin/env python3
"""
Documentation Screenshot Generator

Automatically generates screenshots of various annotation types for documentation.
Uses Selenium to render the annotation interface with sample data.

Usage:
    python scripts/generate_docs_screenshots.py [--output-dir docs/img/screenshots]

Requirements:
    pip install selenium webdriver-manager pillow
"""

import os
import sys
import time
import json
import yaml
import tempfile
import shutil
import argparse
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any

# Add project root to path
project_root = Path(__file__).parents[1]
sys.path.insert(0, str(project_root))

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service as ChromeService
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.action_chains import ActionChains
    SELENIUM_AVAILABLE = True
    try:
        from webdriver_manager.chrome import ChromeDriverManager
        WEBDRIVER_MANAGER_AVAILABLE = True
    except ImportError:
        WEBDRIVER_MANAGER_AVAILABLE = False
except ImportError:
    SELENIUM_AVAILABLE = False
    WEBDRIVER_MANAGER_AVAILABLE = False
    print("Warning: Selenium not installed. Run: pip install selenium webdriver-manager")


# Sample data for different annotation types
SAMPLE_DATA = {
    "text_classification": [
        {
            "id": "sample_001",
            "text": "The new restaurant downtown has amazing food and great service. I highly recommend trying their signature pasta dish!",
            "metadata": {"source": "review", "date": "2024-01-15"}
        },
        {
            "id": "sample_002",
            "text": "I'm frustrated with the constant delays in shipping. This is the third time my order has been late.",
            "metadata": {"source": "feedback", "date": "2024-01-16"}
        }
    ],
    "span_annotation": [
        {
            "id": "span_001",
            "text": "Apple Inc. announced that CEO Tim Cook will present the new iPhone 15 at their headquarters in Cupertino, California next Tuesday.",
            "metadata": {"source": "news"}
        }
    ],
    "pairwise": [
        {
            "id": "pair_001",
            "text": ["The quick brown fox jumps over the lazy dog.", "A fast auburn fox leaps across the sleepy canine."]
        }
    ],
    "video_annotation": [
        {
            "id": "video_001",
            "video_url": "https://www.w3schools.com/html/mov_bbb.mp4",
            "title": "Sample Video",
            "description": "Big Buck Bunny sample clip"
        }
    ],
    "audio_annotation": [
        {
            "id": "audio_001",
            "audio_url": "https://www.w3schools.com/html/horse.mp3",
            "title": "Sample Audio",
            "description": "Sample audio clip for annotation"
        }
    ],
    "image_annotation": [
        {
            "id": "image_001",
            "image_url": "https://picsum.photos/800/600",
            "title": "Sample Image",
            "description": "Random sample image for annotation"
        }
    ]
}


# Annotation scheme configurations for different types
ANNOTATION_CONFIGS = {
    "radio": {
        "name": "Radio Buttons Example",
        "description": "Single-choice classification with radio buttons",
        "schemes": [{
            "annotation_type": "radio",
            "name": "sentiment",
            "description": "What is the overall sentiment of this text?",
            "labels": [
                {"name": "Positive", "key_value": "1", "tooltip": "Text expresses positive emotions or opinions"},
                {"name": "Neutral", "key_value": "2", "tooltip": "Text is neutral or factual"},
                {"name": "Negative", "key_value": "3", "tooltip": "Text expresses negative emotions or opinions"}
            ]
        }],
        "data_type": "text_classification"
    },
    "checkbox": {
        "name": "Checkbox Example",
        "description": "Multi-select classification with checkboxes",
        "schemes": [{
            "annotation_type": "multiselect",
            "name": "topics",
            "description": "Select all topics that apply to this text:",
            "labels": [
                {"name": "Food & Dining", "key_value": "1"},
                {"name": "Customer Service", "key_value": "2"},
                {"name": "Pricing", "key_value": "3"},
                {"name": "Quality", "key_value": "4"},
                {"name": "Location", "key_value": "5"}
            ],
            "min_labels": 1
        }],
        "data_type": "text_classification"
    },
    "likert": {
        "name": "Likert Scale Example",
        "description": "Rating scale annotation",
        "schemes": [{
            "annotation_type": "likert",
            "name": "rating",
            "description": "How would you rate the quality of this text?",
            "size": 5,
            "min_label": "Very Poor",
            "max_label": "Excellent"
        }],
        "data_type": "text_classification"
    },
    "slider": {
        "name": "Slider Example",
        "description": "Continuous value annotation with slider",
        "schemes": [{
            "annotation_type": "slider",
            "name": "confidence",
            "description": "How confident are you in your assessment?",
            "min_value": 0,
            "max_value": 100,
            "step": 1,
            "starting_value": 50
        }],
        "data_type": "text_classification"
    },
    "textbox": {
        "name": "Textbox Example",
        "description": "Free-text response annotation",
        "schemes": [{
            "annotation_type": "text",
            "name": "summary",
            "description": "Please provide a brief summary of this text:",
            "textarea": True
        }],
        "data_type": "text_classification"
    },
    "span": {
        "name": "Span Annotation Example",
        "description": "Text span highlighting and labeling",
        "schemes": [{
            "annotation_type": "span",
            "name": "entities",
            "description": "Highlight and label named entities in the text:",
            "labels": [
                {"name": "Person", "color": "#FF6B6B", "key_value": "p"},
                {"name": "Organization", "color": "#4ECDC4", "key_value": "o"},
                {"name": "Location", "color": "#45B7D1", "key_value": "l"},
                {"name": "Date", "color": "#96CEB4", "key_value": "d"}
            ],
            "allow_overlapping": False
        }],
        "data_type": "span_annotation"
    },
    "video_annotation": {
        "name": "Video Annotation Example",
        "description": "Temporal video segment annotation",
        "schemes": [{
            "annotation_type": "video_annotation",
            "name": "video_segments",
            "description": "Mark video segments using [ and ] keys, then press Enter to create segment.",
            "mode": "segment",
            "labels": [
                {"name": "Intro", "color": "#4ECDC4", "key_value": "1"},
                {"name": "Main Content", "color": "#FF6B6B", "key_value": "2"},
                {"name": "Transition", "color": "#45B7D1", "key_value": "3"},
                {"name": "Outro", "color": "#96CEB4", "key_value": "4"}
            ],
            "timeline_height": 70,
            "playback_rate_control": True,
            "frame_stepping": True,
            "show_timecode": True
        }],
        "data_type": "video_annotation"
    },
    "multirate": {
        "name": "Multi-Rate Example",
        "description": "Rate multiple items on scales",
        "schemes": [{
            "annotation_type": "multirate",
            "name": "aspects",
            "description": "Rate the following aspects:",
            "options": [
                {"name": "Clarity", "tooltip": "How clear is the writing?"},
                {"name": "Relevance", "tooltip": "How relevant is the content?"},
                {"name": "Completeness", "tooltip": "How complete is the information?"}
            ],
            "labels": [
                {"name": "1", "tooltip": "Poor"},
                {"name": "2", "tooltip": "Fair"},
                {"name": "3", "tooltip": "Good"},
                {"name": "4", "tooltip": "Very Good"},
                {"name": "5", "tooltip": "Excellent"}
            ]
        }],
        "data_type": "text_classification"
    },
    "audio_annotation": {
        "name": "Audio Annotation Example",
        "description": "Audio segmentation with timeline",
        "schemes": [{
            "annotation_type": "audio_annotation",
            "name": "audio_segmentation",
            "description": "Listen and mark segments using [ and ] keys, then press Enter.",
            "mode": "label",
            "labels": [
                {"name": "Speech", "color": "#4ECDC4", "key_value": "1"},
                {"name": "Music", "color": "#FF6B6B", "key_value": "2"},
                {"name": "Silence", "color": "#95A5A6", "key_value": "3"},
                {"name": "Noise", "color": "#F39C12", "key_value": "4"}
            ],
            "min_segments": 1,
            "zoom_enabled": True,
            "playback_rate_control": True
        }],
        "data_type": "audio_annotation"
    },
    "image_annotation": {
        "name": "Image Annotation Example",
        "description": "Image bounding box and polygon annotation",
        "schemes": [{
            "annotation_type": "image_annotation",
            "name": "object_detection",
            "description": "Draw boxes around objects. Use polygon tool for irregular shapes.",
            "tools": ["bbox", "polygon"],
            "labels": [
                {"name": "Person", "color": "#FF6B6B", "key_value": "1"},
                {"name": "Vehicle", "color": "#4ECDC4", "key_value": "2"},
                {"name": "Animal", "color": "#45B7D1", "key_value": "3"},
                {"name": "Object", "color": "#96CEB4", "key_value": "4"}
            ],
            "min_annotations": 1,
            "zoom_enabled": True,
            "pan_enabled": True
        }],
        "data_type": "image_annotation"
    },
    "pairwise": {
        "name": "Pairwise Comparison Example",
        "description": "Compare two items and select the better one",
        "schemes": [{
            "annotation_type": "radio",
            "name": "pairwise_comparison",
            "description": "Which text is better written?",
            "labels": [
                {"name": "A is better", "key_value": "1"},
                {"name": "B is better", "key_value": "2"},
                {"name": "About the same", "key_value": "3"}
            ],
            "horizontal": False,
            "label_requirement": {"required": True}
        }],
        "data_type": "pairwise"
    },
    "best_worst": {
        "name": "Best-Worst Scaling Example",
        "description": "Select the best and worst items from a set",
        "schemes": [{
            "annotation_type": "radio",
            "name": "best_choice",
            "description": "Which text is the BEST?",
            "labels": [
                {"name": "Text A", "key_value": "1"},
                {"name": "Text B", "key_value": "2"},
                {"name": "Text C", "key_value": "3"},
                {"name": "Text D", "key_value": "4"}
            ]
        },
        {
            "annotation_type": "radio",
            "name": "worst_choice",
            "description": "Which text is the WORST?",
            "labels": [
                {"name": "Text A", "key_value": "q"},
                {"name": "Text B", "key_value": "w"},
                {"name": "Text C", "key_value": "e"},
                {"name": "Text D", "key_value": "r"}
            ]
        }],
        "data_type": "text_classification"
    }
}


class ScreenshotGenerator:
    """Generates documentation screenshots using Selenium."""

    def __init__(self, output_dir: str, headless: bool = True, window_size: tuple = (1400, 900)):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.headless = headless
        self.window_size = window_size
        self.driver: Optional[webdriver.Chrome] = None
        self.temp_dir: Optional[str] = None
        self.server_process: Optional[subprocess.Popen] = None

    def setup_driver(self):
        """Initialize the Chrome WebDriver."""
        if not SELENIUM_AVAILABLE:
            raise RuntimeError("Selenium is not available. Install with: pip install selenium webdriver-manager")

        options = ChromeOptions()
        if self.headless:
            options.add_argument("--headless=new")
        options.add_argument(f"--window-size={self.window_size[0]},{self.window_size[1]}")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--force-device-scale-factor=1")

        # Try different approaches to set up the driver
        driver_initialized = False

        # First, try using explicit homebrew chromedriver path (most reliable on macOS)
        homebrew_chromedriver = "/opt/homebrew/bin/chromedriver"
        if os.path.exists(homebrew_chromedriver):
            try:
                service = ChromeService(executable_path=homebrew_chromedriver)
                self.driver = webdriver.Chrome(service=service, options=options)
                driver_initialized = True
                print(f"Using chromedriver from: {homebrew_chromedriver}")
            except Exception as e:
                print(f"Homebrew chromedriver failed: {e}")

        # Second, try using system ChromeDriver directly (relies on PATH)
        if not driver_initialized:
            try:
                self.driver = webdriver.Chrome(options=options)
                driver_initialized = True
                print("Using system chromedriver from PATH")
            except Exception as e:
                print(f"System ChromeDriver failed: {e}")

        # Last resort: try webdriver-manager
        if not driver_initialized and WEBDRIVER_MANAGER_AVAILABLE:
            try:
                service = ChromeService(ChromeDriverManager().install())
                self.driver = webdriver.Chrome(service=service, options=options)
                driver_initialized = True
                print("Using webdriver-manager chromedriver")
            except Exception as e:
                print(f"WebDriver manager failed: {e}")

        if not driver_initialized:
            raise RuntimeError(
                "Could not initialize Chrome WebDriver. Make sure Chrome is installed "
                "and try installing chromedriver: brew install chromedriver (macOS) "
                "or download from https://chromedriver.chromium.org/"
            )

        self.driver.set_window_size(*self.window_size)

    def teardown_driver(self):
        """Close the WebDriver."""
        if self.driver:
            self.driver.quit()
            self.driver = None

    def create_temp_project(self, config_name: str, config: Dict[str, Any]) -> str:
        """Create a temporary project directory with config and data."""
        # Create temp dir inside the project to pass security validation
        temp_base = project_root / "temp_screenshots"
        temp_base.mkdir(exist_ok=True)
        self.temp_dir = tempfile.mkdtemp(prefix="screenshot_", dir=str(temp_base))

        # Create data file as JSONL (one JSON object per line)
        data_type = config.get("data_type", "text_classification")
        data = SAMPLE_DATA.get(data_type, SAMPLE_DATA["text_classification"])
        data_file_path = os.path.join(self.temp_dir, "data.jsonl")
        with open(data_file_path, "w") as f:
            for item in data:
                f.write(json.dumps(item) + "\n")
        # Use relative path for config (relative to task_dir)
        data_file = "data.jsonl"

        # Determine text_key based on data type
        text_key = "text"
        if data_type == "video_annotation":
            text_key = "video_url"
        elif data_type == "audio_annotation":
            text_key = "audio_url"
        elif data_type == "image_annotation":
            text_key = "image_url"
        elif data_type == "pairwise":
            text_key = "text"

        # Create config file
        yaml_config = {
            "port": 9999,
            "server_name": "screenshot_generator",
            "annotation_task_name": config["name"],
            "task_dir": self.temp_dir,
            "output_annotation_dir": os.path.join(self.temp_dir, "output"),
            "output_annotation_format": "json",
            "data_files": [data_file],
            "item_properties": {
                "id_key": "id",
                "text_key": text_key
            },
            "user_config": {
                "allow_all_users": True,
                "users": []
            },
            "require_password": False,
            "annotation_schemes": config["schemes"],
            "site_dir": "default",
            "alert_time_each_instance": 0
        }

        # Add list_as_text for pairwise data
        if data_type == "pairwise":
            yaml_config["list_as_text"] = {
                "text_list_prefix_type": "alphabet"
            }

        config_file = os.path.join(self.temp_dir, "config.yaml")
        with open(config_file, "w") as f:
            yaml.dump(yaml_config, f, default_flow_style=False)

        return config_file

    def cleanup_temp_project(self, keep_for_debugging=False):
        """Remove temporary project directory."""
        if keep_for_debugging:
            print(f"  DEBUG: Temp directory preserved at: {self.temp_dir}")
            return
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
            self.temp_dir = None

    def start_server(self, config_file: str, port: int = 9999) -> bool:
        """Start the Potato server."""
        try:
            # Start server in background
            cmd = [
                sys.executable,
                str(project_root / "potato" / "flask_server.py"),
                "start",
                config_file,
                "-p", str(port)
            ]

            # Create log files for debugging
            stdout_log = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='_stdout.log')
            stderr_log = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='_stderr.log')
            self.stderr_log_path = stderr_log.name

            self.server_process = subprocess.Popen(
                cmd,
                stdout=stdout_log,
                stderr=stderr_log,
                cwd=str(project_root)
            )

            # Wait for server to start
            import requests
            max_wait = 30
            start_time = time.time()
            while time.time() - start_time < max_wait:
                try:
                    response = requests.get(f"http://localhost:{port}/", timeout=2)
                    if response.status_code in [200, 302]:
                        return True
                except requests.exceptions.ConnectionError:
                    pass
                except Exception as e:
                    pass

                # Check if process has terminated
                if self.server_process.poll() is not None:
                    # Process has exited, read error logs
                    stdout_log.close()
                    stderr_log.close()
                    with open(stderr_log.name, 'r') as f:
                        stderr_content = f.read()
                    print(f"  Server exited early. Stderr: {stderr_content[:500]}")
                    return False

                time.sleep(0.5)

            print(f"Warning: Server may not have started properly after {max_wait}s")
            return False

        except Exception as e:
            print(f"Error starting server: {e}")
            import traceback
            traceback.print_exc()
            return False

    def stop_server(self):
        """Stop the Potato server."""
        if self.server_process:
            self.server_process.terminate()
            try:
                self.server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.server_process.kill()
            self.server_process = None

    def login(self, port: int = 9999, username: str = "demo_user"):
        """Login to the annotation interface."""
        import requests

        try:
            base_url = f"http://localhost:{port}"

            # Use requests library to register and login (handles cookies properly)
            session = requests.Session()

            # Potato uses 'email' and 'pass' as field names (not 'username' and 'password')
            # With require_password: false, users are auto-registered on login
            # Include 'action' field as the form does
            login_response = session.post(
                f"{base_url}/auth",
                data={"email": username, "pass": username, "action": "login"},
                allow_redirects=True
            )

            # Check if login was successful by checking the response
            if login_response.status_code == 200 and session.cookies:
                # Transfer cookies from requests session to Selenium
                self.driver.get(base_url)
                time.sleep(1)

                # Add cookies from requests session to Selenium
                for cookie in session.cookies:
                    try:
                        self.driver.add_cookie({'name': cookie.name, 'value': cookie.value})
                    except Exception:
                        pass

                # Refresh to use the cookies
                self.driver.get(base_url)
                time.sleep(3)

                # Check if login succeeded
                logged_in = self.driver.execute_script("""
                    return !!document.getElementById('annotation-forms');
                """)

                if logged_in:
                    time.sleep(1)
                    return True

            print("  Login failed")
            return False

        except Exception as e:
            print(f"  Login error: {e}")
            return False

    def take_screenshot(self, filename: str, element_selector: Optional[str] = None,
                       full_page: bool = False, highlight_elements: List[str] = None):
        """Take a screenshot and save it."""
        time.sleep(0.5)  # Allow any animations to complete

        # Optionally highlight elements
        if highlight_elements:
            for selector in highlight_elements:
                try:
                    self.driver.execute_script(f"""
                        var elements = document.querySelectorAll('{selector}');
                        elements.forEach(function(el) {{
                            el.style.boxShadow = '0 0 10px 3px rgba(255, 107, 107, 0.8)';
                        }});
                    """)
                except:
                    pass

        output_path = self.output_dir / filename

        if element_selector:
            # Screenshot specific element
            try:
                element = self.driver.find_element(By.CSS_SELECTOR, element_selector)
                element.screenshot(str(output_path))
            except Exception as e:
                print(f"Could not screenshot element '{element_selector}': {e}")
                self.driver.save_screenshot(str(output_path))
        else:
            # Full page or viewport screenshot
            if full_page:
                # Scroll to capture full page
                total_height = self.driver.execute_script("return document.body.scrollHeight")
                self.driver.set_window_size(self.window_size[0], total_height)
                time.sleep(0.3)

            self.driver.save_screenshot(str(output_path))

            if full_page:
                self.driver.set_window_size(*self.window_size)

        print(f"  ✓ Saved: {output_path}")
        return output_path

    def generate_annotation_screenshot(self, config_name: str, config: Dict[str, Any]) -> Optional[Path]:
        """Generate a screenshot for a specific annotation type."""
        print(f"\nGenerating screenshot for: {config_name}")

        try:
            # Create temp project
            config_file = self.create_temp_project(config_name, config)

            # Start server
            if not self.start_server(config_file):
                print(f"  ✗ Failed to start server for {config_name}")
                return None

            # Login
            if not self.login():
                print(f"  ✗ Failed to login for {config_name}")
                return None

            # Take screenshot of the annotation form
            screenshot_path = self.take_screenshot(
                f"{config_name}_annotation.png",
                element_selector="#task_layout"
            )

            # Also take a full interface screenshot
            self.take_screenshot(
                f"{config_name}_full.png"
            )

            return screenshot_path

        except Exception as e:
            print(f"  ✗ Error generating screenshot for {config_name}: {e}")
            import traceback
            traceback.print_exc()
            return None

        finally:
            self.stop_server()
            self.cleanup_temp_project()

    def generate_all_screenshots(self, annotation_types: List[str] = None):
        """Generate screenshots for all (or specified) annotation types."""
        if annotation_types is None:
            annotation_types = list(ANNOTATION_CONFIGS.keys())

        print(f"Generating screenshots for {len(annotation_types)} annotation types...")
        print(f"Output directory: {self.output_dir}")

        self.setup_driver()

        results = {}
        for config_name in annotation_types:
            if config_name not in ANNOTATION_CONFIGS:
                print(f"Warning: Unknown annotation type '{config_name}', skipping")
                continue

            config = ANNOTATION_CONFIGS[config_name]
            screenshot_path = self.generate_annotation_screenshot(config_name, config)
            results[config_name] = screenshot_path

        self.teardown_driver()

        # Print summary
        print("\n" + "=" * 50)
        print("Screenshot Generation Summary")
        print("=" * 50)
        successful = sum(1 for v in results.values() if v is not None)
        print(f"Total: {len(results)}, Successful: {successful}, Failed: {len(results) - successful}")

        for name, path in results.items():
            status = "✓" if path else "✗"
            print(f"  {status} {name}")

        return results


def main():
    parser = argparse.ArgumentParser(
        description="Generate documentation screenshots for Potato annotation types"
    )
    parser.add_argument(
        "--output-dir", "-o",
        default="docs/img/screenshots",
        help="Output directory for screenshots (default: docs/img/screenshots)"
    )
    parser.add_argument(
        "--types", "-t",
        nargs="+",
        choices=list(ANNOTATION_CONFIGS.keys()) + ["all"],
        default=["all"],
        help="Annotation types to screenshot (default: all)"
    )
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="Run browser in visible mode (useful for debugging)"
    )
    parser.add_argument(
        "--window-size",
        default="1400x900",
        help="Browser window size as WIDTHxHEIGHT (default: 1400x900)"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available annotation types and exit"
    )

    args = parser.parse_args()

    if args.list:
        print("Available annotation types:")
        for name, config in ANNOTATION_CONFIGS.items():
            print(f"  {name}: {config['description']}")
        return

    if not SELENIUM_AVAILABLE:
        print("Error: Selenium is required. Install with:")
        print("  pip install selenium webdriver-manager")
        sys.exit(1)

    # Parse window size
    try:
        width, height = map(int, args.window_size.split("x"))
        window_size = (width, height)
    except:
        print(f"Invalid window size format: {args.window_size}")
        window_size = (1400, 900)

    # Determine which types to generate
    if "all" in args.types:
        annotation_types = None  # All types
    else:
        annotation_types = args.types

    # Generate screenshots
    generator = ScreenshotGenerator(
        output_dir=args.output_dir,
        headless=not args.no_headless,
        window_size=window_size
    )

    try:
        generator.generate_all_screenshots(annotation_types)
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        generator.stop_server()
        generator.cleanup_temp_project()
        generator.teardown_driver()


if __name__ == "__main__":
    main()

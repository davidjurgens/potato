#!/usr/bin/env python3
"""
Test utilities for creating secure test configurations and data files.

This module provides helper functions that ensure all test files are created
within the tests/ directory structure to comply with path security requirements.
"""

import os
import json
import yaml
import tempfile
import uuid
from typing import Dict, Any, List, Tuple
from pathlib import Path


def create_test_directory(test_name: str, base_dir: str = None) -> str:
    """
    Create a test directory within the tests/output/ structure.

    Args:
        test_name: Name for the test directory
        base_dir: Base directory (defaults to tests/output/)

    Returns:
        Path to the created test directory
    """
    if base_dir is None:
        # Get the tests directory
        tests_dir = Path(__file__).parent.parent
        base_dir = tests_dir / "output"

    # Create a unique test directory
    unique_id = str(uuid.uuid4())[:8]
    test_dir = Path(base_dir) / f"{test_name}_{unique_id}"
    test_dir.mkdir(parents=True, exist_ok=True)

    return str(test_dir)


def create_test_data_file(test_dir: str, data: List[Dict[str, Any]], filename: str = "test_data.jsonl") -> str:
    """
    Create a test data file in JSONL format.

    Args:
        test_dir: Directory to create the file in
        data: List of data objects to write
        filename: Name of the file to create

    Returns:
        Path to the created data file
    """
    data_file = Path(test_dir) / filename

    with open(data_file, 'w') as f:
        for item in data:
            f.write(json.dumps(item) + '\n')

    return str(data_file)


def create_test_config(
    test_dir: str,
    annotation_schemes: List[Dict[str, Any]],
    data_files: List[str] = None,
    **kwargs
) -> str:
    """
    Create a test configuration file.

    Args:
        test_dir: Directory to create the config in
        annotation_schemes: List of annotation schemes
        data_files: List of data file paths (relative to test_dir)
        **kwargs: Additional config options

    Returns:
        Path to the created config file
    """
    if data_files is None:
        data_files = ["test_data.jsonl"]

    # Ensure all data files are relative to test_dir
    relative_data_files = [os.path.basename(f) for f in data_files]

    config = {
        "annotation_task_name": kwargs.get("annotation_task_name", "Test Task"),
        "task_dir": test_dir,
        "data_files": relative_data_files,
        "item_properties": kwargs.get("item_properties", {"id_key": "id", "text_key": "text"}),
        "annotation_schemes": annotation_schemes,
        "output_annotation_dir": os.path.join(test_dir, "output"),
        "site_dir": kwargs.get("site_dir", "default"),
        "alert_time_each_instance": kwargs.get("alert_time_each_instance", 0),
        "require_password": kwargs.get("require_password", False),
        "authentication": kwargs.get("authentication", {"method": "in_memory"}),
        "persist_sessions": kwargs.get("persist_sessions", False),
        "debug": kwargs.get("debug", False),
        "port": kwargs.get("port", 8000),
        "host": kwargs.get("host", "0.0.0.0"),
        "secret_key": kwargs.get("secret_key", "test-secret-key"),
        "session_lifetime_days": kwargs.get("session_lifetime_days", 1),
    }

    config_file = Path(test_dir) / "config.yaml"

    with open(config_file, 'w') as f:
        yaml.dump(config, f)

    return str(config_file)


def create_span_annotation_config(test_dir: str, **kwargs) -> Tuple[str, str]:
    """
    Create a test configuration with span annotation support.

    Args:
        test_dir: Directory to create the config in
        **kwargs: Additional config options

    Returns:
        Tuple of (config_file_path, data_file_path)
    """
    # Create test data
    test_data = [
        {"id": "1", "text": "I am absolutely thrilled about this new technology that will revolutionize our industry."},
        {"id": "2", "text": "The weather is terrible today and I'm feeling quite disappointed."},
        {"id": "3", "text": "This is a neutral statement with no strong emotional content."}
    ]

    data_file = create_test_data_file(test_dir, test_data)

    # Create span annotation scheme
    annotation_schemes = [
        {
            "name": "emotion_spans",
            "annotation_type": "span",
            "labels": ["positive", "negative", "neutral"],
            "description": "Mark emotional content in text spans",
            "color_scheme": {
                "positive": "#d4edda",
                "negative": "#f8d7da",
                "neutral": "#d1ecf1"
            }
        }
    ]

    config_file = create_test_config(
        test_dir,
        annotation_schemes,
        data_files=[data_file],
        **kwargs
    )

    return config_file, data_file


def create_comprehensive_annotation_config(test_dir: str, **kwargs) -> Tuple[str, str]:
    """
    Create a test configuration with multiple annotation types.

    Args:
        test_dir: Directory to create the config in
        **kwargs: Additional config options

    Returns:
        Tuple of (config_file_path, data_file_path)
    """
    # Create test data
    test_data = [
        {"id": "1", "text": "This is a test item for comprehensive annotation testing."},
        {"id": "2", "text": "Another test item with different content for validation."}
    ]

    data_file = create_test_data_file(test_dir, test_data)

    # Create comprehensive annotation schemes
    annotation_schemes = [
        {
            "name": "likert_rating",
            "annotation_type": "likert",
            "min_label": "1",
            "max_label": "5",
            "size": 5,
            "description": "Rate on a scale of 1-5"
        },
        {
            "name": "radio_choice",
            "annotation_type": "radio",
            "labels": ["option_a", "option_b", "option_c"],
            "description": "Choose one option"
        },
        {
            "name": "slider_value",
            "annotation_type": "slider",
            "min_value": 1,
            "max_value": 10,
            "starting_value": 5,
            "description": "Rate on a scale of 1-10"
        },
        {
            "name": "text_input",
            "annotation_type": "text",
            "description": "Enter your response"
        },
        {
            "name": "span_annotation",
            "annotation_type": "span",
            "labels": ["positive", "negative"],
            "description": "Mark spans of text"
        }
    ]

    config_file = create_test_config(
        test_dir,
        annotation_schemes,
        data_files=[data_file],
        **kwargs
    )

    return config_file, data_file


def cleanup_test_directory(test_dir: str):
    """
    Clean up a test directory and all its contents.

    Args:
        test_dir: Path to the test directory to clean up
    """
    import shutil
    try:
        if os.path.exists(test_dir):
            shutil.rmtree(test_dir)
    except Exception as e:
        print(f"Warning: Failed to clean up test directory {test_dir}: {e}")


def get_project_root() -> str:
    """
    Get the project root directory.

    Returns:
        Path to the project root
    """
    return str(Path(__file__).parent.parent.parent)


def get_tests_dir() -> str:
    """
    Get the tests directory.

    Returns:
        Path to the tests directory
    """
    return str(Path(__file__).parent.parent)


def validate_test_paths(test_dir: str, config_file: str, data_files: List[str]):
    """
    Validate that all test paths are within the tests directory.

    Args:
        test_dir: Test directory path
        config_file: Config file path
        data_files: List of data file paths

    Raises:
        ValueError: If any path is outside the tests directory
    """
    tests_dir = get_tests_dir()

    paths_to_check = [test_dir, config_file] + data_files

    for path in paths_to_check:
        if not os.path.abspath(path).startswith(os.path.abspath(tests_dir)):
            raise ValueError(f"Test path {path} is outside the tests directory {tests_dir}")


class TestConfigManager:
    """
    Context manager for creating and cleaning up test configurations.
    """

    def __init__(self, test_name: str, annotation_schemes: List[Dict[str, Any]], **kwargs):
        self.test_name = test_name
        self.annotation_schemes = annotation_schemes
        self.kwargs = kwargs
        self.test_dir = None
        self.config_file = None
        self.data_file = None

    def __enter__(self):
        # Create test directory
        self.test_dir = create_test_directory(self.test_name)

        # Create test data
        test_data = [
            {"id": "1", "text": "Test item 1"},
            {"id": "2", "text": "Test item 2"}
        ]
        self.data_file = create_test_data_file(self.test_dir, test_data)

        # Create config
        self.config_file = create_test_config(
            self.test_dir,
            self.annotation_schemes,
            data_files=[self.data_file],
            **self.kwargs
        )

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Clean up
        if self.test_dir:
            cleanup_test_directory(self.test_dir)

    @property
    def config_path(self) -> str:
        return self.config_file

    @property
    def data_path(self) -> str:
        return self.data_file

    @property
    def task_dir(self) -> str:
        return self.test_dir


def copy_config_to_test_dir(config_path: str, test_name: str = None) -> Tuple[str, str]:
    """
    Copy an existing config file to a test directory and update paths for security compliance.

    The new config file location requirement means configs must be in the task_dir.
    This function copies a config to a test directory and updates all paths accordingly.

    Args:
        config_path: Path to the original config file
        test_name: Optional name for the test directory

    Returns:
        Tuple of (new_config_path, test_dir)
    """
    import shutil

    if test_name is None:
        test_name = Path(config_path).stem

    # Create test directory
    test_dir = create_test_directory(test_name)

    # Load the original config
    with open(config_path, 'r') as f:
        config_data = yaml.safe_load(f)

    # Update task_dir to point to test_dir
    config_data['task_dir'] = test_dir

    # Update output_annotation_dir to be within test_dir
    output_dir = os.path.join(test_dir, 'output')
    os.makedirs(output_dir, exist_ok=True)
    config_data['output_annotation_dir'] = output_dir

    # Handle data files - copy them to test_dir if they exist
    original_config_dir = Path(config_path).parent
    new_data_files = []

    for data_file in config_data.get('data_files', []):
        # Resolve the original data file path
        if os.path.isabs(data_file):
            original_data_path = data_file
        else:
            original_data_path = original_config_dir / data_file

        if os.path.exists(original_data_path):
            # Copy to test_dir
            new_data_path = os.path.join(test_dir, os.path.basename(data_file))
            shutil.copy2(original_data_path, new_data_path)
            new_data_files.append(os.path.basename(data_file))
        else:
            # Create a minimal test data file
            new_data_path = os.path.join(test_dir, os.path.basename(data_file))
            with open(new_data_path, 'w') as f:
                f.write(json.dumps({"id": "1", "text": "Test item 1"}) + '\n')
                f.write(json.dumps({"id": "2", "text": "Test item 2"}) + '\n')
            new_data_files.append(os.path.basename(data_file))

    # If no data files, create a default one
    if not new_data_files:
        default_data_file = os.path.join(test_dir, 'test_data.jsonl')
        with open(default_data_file, 'w') as f:
            f.write(json.dumps({"id": "1", "text": "Test item 1"}) + '\n')
            f.write(json.dumps({"id": "2", "text": "Test item 2"}) + '\n')
        new_data_files.append('test_data.jsonl')

    config_data['data_files'] = new_data_files

    # Write the new config file to test_dir
    new_config_path = os.path.join(test_dir, 'config.yaml')
    with open(new_config_path, 'w') as f:
        yaml.dump(config_data, f)

    return new_config_path, test_dir


def create_image_annotation_config(test_dir: str, **kwargs) -> Tuple[str, str]:
    """
    Create a test configuration with image annotation support.

    Args:
        test_dir: Directory to create the config in
        **kwargs: Additional config options

    Returns:
        Tuple of (config_file_path, data_file_path)
    """
    # Create test data with image URLs
    test_data = [
        {"id": "img_001", "image_url": "https://picsum.photos/id/1011/800/600"},
        {"id": "img_002", "image_url": "https://picsum.photos/id/1025/800/600"},
        {"id": "img_003", "image_url": "https://picsum.photos/id/1035/800/600"}
    ]

    data_file = create_test_data_file(test_dir, test_data, filename="image_data.jsonl")

    # Create image annotation scheme
    annotation_schemes = [
        {
            "annotation_type": "image_annotation",
            "name": "object_detection",
            "description": "Draw boxes around objects in the image",
            "tools": ["bbox", "polygon"],
            "labels": [
                {"name": "person", "color": "#FF0000", "key_value": "1"},
                {"name": "animal", "color": "#00FF00", "key_value": "2"},
                {"name": "vehicle", "color": "#0000FF", "key_value": "3"}
            ],
            "zoom_enabled": True,
            "pan_enabled": True
        }
    ]

    config_file = create_test_config(
        test_dir,
        annotation_schemes,
        data_files=[data_file],
        item_properties={"id_key": "id", "text_key": "image_url"},
        **kwargs
    )

    return config_file, data_file


def create_audio_annotation_config(test_dir: str, **kwargs) -> Tuple[str, str]:
    """
    Create a test configuration with audio annotation support.

    Args:
        test_dir: Directory to create the config in
        **kwargs: Additional config options

    Returns:
        Tuple of (config_file_path, data_file_path)
    """
    # Create test data with audio URLs
    test_data = [
        {"id": "audio_001", "audio_url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3"},
        {"id": "audio_002", "audio_url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-2.mp3"}
    ]

    data_file = create_test_data_file(test_dir, test_data, filename="audio_data.jsonl")

    # Create audio annotation scheme
    annotation_schemes = [
        {
            "annotation_type": "audio_annotation",
            "name": "audio_segmentation",
            "description": "Segment the audio by content type",
            "mode": "label",
            "labels": [
                {"name": "speech", "color": "#4ECDC4", "key_value": "1"},
                {"name": "music", "color": "#FF6B6B", "key_value": "2"},
                {"name": "silence", "color": "#95A5A6", "key_value": "3"}
            ],
            "zoom_enabled": True,
            "playback_rate_control": True
        }
    ]

    config_file = create_test_config(
        test_dir,
        annotation_schemes,
        data_files=[data_file],
        item_properties={"id_key": "id", "text_key": "audio_url"},
        **kwargs
    )

    return config_file, data_file
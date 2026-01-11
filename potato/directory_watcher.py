"""
Directory Watcher Module

This module provides functionality for loading annotation instances from a directory
and optionally watching that directory for new or modified files. When watching is
enabled, a background thread periodically scans the directory and dynamically loads
new instances or updates existing ones.

The module supports the same file formats as the standard data_files configuration:
JSON, JSONL, CSV, and TSV.

Configuration:
    data_directory: str - Path to the directory containing data files
    watch_data_directory: bool - Whether to watch for changes (default: False)
    watch_poll_interval: float - Seconds between directory scans (default: 5.0)

Example config:
    data_directory: "./data/incoming"
    watch_data_directory: true
    watch_poll_interval: 10.0
"""

from __future__ import annotations

import json
import logging
import os
import threading
import glob
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple, TYPE_CHECKING

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

if TYPE_CHECKING:
    from potato.item_state_management import ItemStateManager

logger = logging.getLogger(__name__)

# Singleton instance with thread-safe initialization
DIRECTORY_WATCHER: Optional['DirectoryWatcher'] = None
_DIRECTORY_WATCHER_LOCK = threading.Lock()


@dataclass
class FileState:
    """
    Tracks the state of a watched file.

    Attributes:
        file_path: Absolute path to the file
        last_modified: Last modification time (os.path.getmtime)
        file_size: File size in bytes
        instance_ids: Set of instance IDs loaded from this file
        last_error: Last error message if processing failed, None otherwise
        last_processed: Timestamp of last successful processing
    """
    file_path: str
    last_modified: float = 0.0
    file_size: int = 0
    instance_ids: Set[str] = field(default_factory=set)
    last_error: Optional[str] = None
    last_processed: Optional[float] = None


class DirectoryWatcher:
    """
    Watches a directory for new or modified data files and loads them as annotation instances.

    This class provides two modes of operation:
    1. Static loading: Load all files from a directory at startup (load_directory())
    2. Dynamic watching: Continuously monitor for changes (start_watching())

    The watcher tracks which instances came from which file, enabling proper handling
    of file modifications (updating existing instances rather than creating duplicates).

    Thread Safety:
        All public methods are thread-safe. The internal state is protected by
        a reentrant lock (_lock) to allow safe concurrent access from the main
        application thread and the background watching thread.

    Attributes:
        data_directory: Path to the directory to watch
        poll_interval: Seconds between directory scans
        id_key: Key in data items containing the unique instance ID
        text_key: Key in data items containing the text to annotate
    """

    # Supported file extensions
    SUPPORTED_EXTENSIONS = ('.json', '.jsonl', '.csv', '.tsv')

    def __init__(self, config: dict, item_state_manager: 'ItemStateManager'):
        """
        Initialize the directory watcher.

        Args:
            config: Configuration dictionary containing:
                - data_directory: Path to watch
                - watch_poll_interval: Seconds between scans (default: 5.0)
                - item_properties.id_key: Key for instance IDs
                - item_properties.text_key: Key for text content
            item_state_manager: The ItemStateManager instance to add items to

        Raises:
            ValueError: If data_directory is not configured or doesn't exist
        """
        self.data_directory = config.get("data_directory")
        if not self.data_directory:
            raise ValueError("data_directory must be configured")

        # Resolve relative paths based on task_dir if available
        if not os.path.isabs(self.data_directory):
            task_dir = config.get("task_dir", "")
            if task_dir:
                self.data_directory = os.path.join(task_dir, self.data_directory)
            self.data_directory = os.path.abspath(self.data_directory)

        if not os.path.isdir(self.data_directory):
            raise ValueError(f"data_directory does not exist or is not a directory: {self.data_directory}")

        self.poll_interval = config.get("watch_poll_interval", 5.0)
        self.id_key = config["item_properties"]["id_key"]
        self.text_key = config["item_properties"]["text_key"]

        self._item_state_manager = item_state_manager

        # File tracking state
        self._file_states: Dict[str, FileState] = {}
        self._instance_to_file: Dict[str, str] = {}  # instance_id -> file_path

        # Threading
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._watch_thread: Optional[threading.Thread] = None

        logger.info(f"DirectoryWatcher initialized for: {self.data_directory}")

    def load_directory(self) -> int:
        """
        Load all supported files from the data directory.

        This method performs an initial scan of the directory and loads all
        instances from supported file formats. It should be called once at
        startup before start_watching().

        Returns:
            int: Total number of instances loaded

        Side Effects:
            - Populates ItemStateManager with loaded instances
            - Updates internal file tracking state
        """
        total_added = 0

        with self._lock:
            files = self._scan_directory()
            logger.info(f"Found {len(files)} supported files in {self.data_directory}")

            for file_path in files:
                try:
                    added, updated = self._process_file(file_path)
                    total_added += added
                    if added > 0 or updated > 0:
                        logger.info(f"Loaded {file_path}: {added} added, {updated} updated")
                except Exception as e:
                    logger.error(f"Error loading {file_path}: {e}")

        logger.info(f"Directory load complete: {total_added} total instances loaded")
        return total_added

    def start_watching(self) -> None:
        """
        Start the background directory watching thread.

        The watching thread will periodically scan the directory for new or
        modified files and process them. Use stop() to terminate the thread.

        Note:
            This method is idempotent - calling it multiple times has no effect
            if the thread is already running.
        """
        with self._lock:
            if self._watch_thread is not None and self._watch_thread.is_alive():
                logger.warning("Directory watcher thread is already running")
                return

            self._stop_event.clear()
            self._watch_thread = threading.Thread(
                target=self._watch_loop,
                name="DirectoryWatcher",
                daemon=True
            )
            self._watch_thread.start()
            logger.info(f"Directory watching started (poll interval: {self.poll_interval}s)")

    def stop(self) -> None:
        """
        Stop the directory watching thread gracefully.

        This method signals the watching thread to stop and waits for it
        to terminate (up to 5 seconds). It's safe to call this method
        even if watching was never started.
        """
        self._stop_event.set()

        if self._watch_thread is not None and self._watch_thread.is_alive():
            self._watch_thread.join(timeout=5.0)
            if self._watch_thread.is_alive():
                logger.warning("Directory watcher thread did not stop gracefully")
            else:
                logger.info("Directory watcher stopped")

        self._watch_thread = None

    def get_stats(self) -> dict:
        """
        Get statistics about the directory watcher state.

        Returns:
            dict: Statistics including:
                - data_directory: Path being watched
                - is_watching: Whether the watch thread is running
                - poll_interval: Seconds between scans
                - files_tracked: Number of files being tracked
                - total_instances: Total instances loaded from this directory
                - files: List of file states with details
        """
        with self._lock:
            return {
                "data_directory": self.data_directory,
                "is_watching": self._watch_thread is not None and self._watch_thread.is_alive(),
                "poll_interval": self.poll_interval,
                "files_tracked": len(self._file_states),
                "total_instances": len(self._instance_to_file),
                "files": [
                    {
                        "path": fs.file_path,
                        "last_modified": fs.last_modified,
                        "instance_count": len(fs.instance_ids),
                        "last_error": fs.last_error
                    }
                    for fs in self._file_states.values()
                ]
            }

    def force_rescan(self) -> Tuple[int, int]:
        """
        Force an immediate rescan of the directory.

        This method can be called to trigger an immediate check for changes
        without waiting for the next poll interval.

        Returns:
            Tuple[int, int]: (total_added, total_updated) counts
        """
        return self._scan_and_process()

    def _watch_loop(self) -> None:
        """
        Main watching loop that runs in the background thread.

        This loop periodically scans the directory for changes and processes
        any new or modified files. It continues until stop() is called.
        """
        logger.debug("Directory watch loop started")

        while not self._stop_event.is_set():
            try:
                added, updated = self._scan_and_process()
                if added > 0 or updated > 0:
                    logger.info(f"Directory scan: {added} instances added, {updated} updated")
            except Exception as e:
                logger.error(f"Error in directory watch loop: {e}", exc_info=True)

            # Wait for the poll interval or until stopped
            self._stop_event.wait(timeout=self.poll_interval)

        logger.debug("Directory watch loop ended")

    def _scan_and_process(self) -> Tuple[int, int]:
        """
        Scan for changed files and process them.

        Returns:
            Tuple[int, int]: (total_added, total_updated) counts
        """
        total_added = 0
        total_updated = 0

        with self._lock:
            current_files = set(self._scan_directory())
            tracked_files = set(self._file_states.keys())

            # Find new and potentially modified files
            for file_path in current_files:
                try:
                    stat = os.stat(file_path)
                    current_mtime = stat.st_mtime
                    current_size = stat.st_size
                except OSError as e:
                    logger.warning(f"Cannot stat file {file_path}: {e}")
                    continue

                # Check if file is new or modified
                if file_path not in self._file_states:
                    # New file
                    added, updated = self._process_file(file_path)
                    total_added += added
                    total_updated += updated
                else:
                    # Check if modified
                    fs = self._file_states[file_path]
                    if current_mtime > fs.last_modified or current_size != fs.file_size:
                        logger.debug(f"File modified: {file_path}")
                        added, updated = self._process_file(file_path)
                        total_added += added
                        total_updated += updated

            # Note: We don't remove instances when files are deleted - this preserves
            # annotations that may have been made on those instances.
            removed_files = tracked_files - current_files
            for file_path in removed_files:
                logger.info(f"File removed (instances preserved): {file_path}")
                # Keep the file state but mark that the file is gone
                if file_path in self._file_states:
                    self._file_states[file_path].last_error = "File removed from directory"

        return total_added, total_updated

    def _scan_directory(self) -> List[str]:
        """
        Scan the data directory for supported files.

        Returns:
            List[str]: List of absolute paths to supported files
        """
        files = []
        for ext in self.SUPPORTED_EXTENSIONS:
            pattern = os.path.join(self.data_directory, f"*{ext}")
            files.extend(glob.glob(pattern))
        return sorted(files)

    def _process_file(self, file_path: str) -> Tuple[int, int]:
        """
        Process a single data file, adding or updating instances.

        Args:
            file_path: Absolute path to the file to process

        Returns:
            Tuple[int, int]: (added_count, updated_count)

        Side Effects:
            - Updates ItemStateManager with new/updated instances
            - Updates file tracking state
        """
        added_count = 0
        updated_count = 0

        try:
            instances = self._parse_file(file_path)
            stat = os.stat(file_path)

            # Get or create file state
            if file_path not in self._file_states:
                self._file_states[file_path] = FileState(file_path=file_path)

            fs = self._file_states[file_path]
            new_instance_ids: Set[str] = set()

            for instance_data in instances:
                # Validate ID key exists
                if self.id_key not in instance_data:
                    logger.warning(f"Missing id_key '{self.id_key}' in {file_path}, skipping instance")
                    continue

                instance_id = str(instance_data[self.id_key])
                new_instance_ids.add(instance_id)

                # Check if text_key is missing (warning only)
                if self.text_key not in instance_data:
                    logger.warning(f"Missing text_key '{self.text_key}' for instance {instance_id}")

                # Add or update the instance
                if self._item_state_manager.has_item(instance_id):
                    # Update existing instance
                    if self._item_state_manager.update_item(instance_id, instance_data):
                        updated_count += 1
                        logger.debug(f"Updated instance: {instance_id}")
                else:
                    # Add new instance
                    try:
                        self._item_state_manager.add_item(instance_id, instance_data)
                        self._instance_to_file[instance_id] = file_path
                        added_count += 1
                        logger.debug(f"Added instance: {instance_id}")
                    except ValueError as e:
                        logger.error(f"Failed to add instance {instance_id}: {e}")

            # Update file state
            fs.last_modified = stat.st_mtime
            fs.file_size = stat.st_size
            fs.instance_ids = new_instance_ids
            fs.last_error = None
            fs.last_processed = stat.st_mtime

        except Exception as e:
            logger.error(f"Error processing file {file_path}: {e}")
            if file_path in self._file_states:
                self._file_states[file_path].last_error = str(e)
            else:
                self._file_states[file_path] = FileState(
                    file_path=file_path,
                    last_error=str(e)
                )

        return added_count, updated_count

    def _parse_file(self, file_path: str) -> List[dict]:
        """
        Parse a data file and return a list of instance dictionaries.

        Args:
            file_path: Absolute path to the file

        Returns:
            List[dict]: List of instance data dictionaries

        Raises:
            ValueError: If file format is unsupported or parsing fails
        """
        ext = os.path.splitext(file_path)[1].lower()

        if ext in ('.json', '.jsonl'):
            return self._parse_json_file(file_path)
        elif ext == '.csv':
            return self._parse_csv_file(file_path, separator=',')
        elif ext == '.tsv':
            return self._parse_csv_file(file_path, separator='\t')
        else:
            raise ValueError(f"Unsupported file format: {ext}")

    def _parse_json_file(self, file_path: str) -> List[dict]:
        """
        Parse a JSON or JSONL file.

        Supports both:
        - JSONL format: One JSON object per line
        - JSON format: Single JSON array or object per line

        Args:
            file_path: Path to the JSON/JSONL file

        Returns:
            List[dict]: List of parsed instance dictionaries
        """
        instances = []

        with open(file_path, 'rt', encoding='utf-8') as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue

                try:
                    item = json.loads(line)

                    # Handle both single objects and arrays
                    if isinstance(item, list):
                        instances.extend(item)
                    else:
                        instances.append(item)

                except json.JSONDecodeError as e:
                    raise ValueError(
                        f"Invalid JSON at line {line_no} in {file_path}: {e}"
                    ) from e

        return instances

    def _parse_csv_file(self, file_path: str, separator: str) -> List[dict]:
        """
        Parse a CSV or TSV file.

        Args:
            file_path: Path to the CSV/TSV file
            separator: Column separator (',' for CSV, '\t' for TSV)

        Returns:
            List[dict]: List of row dictionaries

        Raises:
            ImportError: If pandas is not available
            ValueError: If required columns are missing
        """
        if not HAS_PANDAS:
            raise ImportError(
                "pandas is required for CSV/TSV file support. "
                "Install it with: pip install pandas"
            )

        df = pd.read_csv(file_path, sep=separator)

        # Validate ID column exists
        if self.id_key not in df.columns:
            raise ValueError(f"ID column '{self.id_key}' not found in {file_path}")

        # Convert ID column to string
        df[self.id_key] = df[self.id_key].astype(str)

        # Convert text column to string if present
        if self.text_key in df.columns:
            df[self.text_key] = df[self.text_key].astype(str)

        return df.to_dict('records')


def init_directory_watcher(config: dict) -> Optional[DirectoryWatcher]:
    """
    Initialize the global DirectoryWatcher singleton if data_directory is configured.

    This function creates a DirectoryWatcher instance if the configuration includes
    a data_directory setting. The watcher is initialized but not started - call
    load_directory() and optionally start_watching() after initialization.

    Args:
        config: Configuration dictionary

    Returns:
        DirectoryWatcher: The initialized watcher, or None if not configured

    Note:
        Thread-safe initialization using double-checked locking pattern.
    """
    global DIRECTORY_WATCHER

    # Check if data_directory is configured
    if "data_directory" not in config:
        return None

    # Double-checked locking for thread safety
    if DIRECTORY_WATCHER is None:
        with _DIRECTORY_WATCHER_LOCK:
            if DIRECTORY_WATCHER is None:
                from potato.item_state_management import get_item_state_manager
                ism = get_item_state_manager()
                DIRECTORY_WATCHER = DirectoryWatcher(config, ism)

    return DIRECTORY_WATCHER


def get_directory_watcher() -> Optional[DirectoryWatcher]:
    """
    Get the global DirectoryWatcher singleton instance.

    Returns:
        DirectoryWatcher: The singleton instance, or None if not initialized
    """
    return DIRECTORY_WATCHER


def clear_directory_watcher() -> None:
    """
    Clear the global DirectoryWatcher singleton (for testing).

    This function stops any running watch thread and clears the global instance.
    Thread-safe.
    """
    global DIRECTORY_WATCHER

    with _DIRECTORY_WATCHER_LOCK:
        if DIRECTORY_WATCHER is not None:
            DIRECTORY_WATCHER.stop()
            DIRECTORY_WATCHER = None

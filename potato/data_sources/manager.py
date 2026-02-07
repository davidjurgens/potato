"""
Data Source Manager

This module provides the central manager for all data sources, implementing
the singleton pattern for thread-safe access across the application.
"""

import logging
import threading
from typing import Any, Dict, Iterator, List, Optional, Type, TYPE_CHECKING

from potato.data_sources.base import DataSource, SourceConfig, SourceType
from potato.data_sources.credentials import CredentialManager
from potato.data_sources.cache_manager import CacheManager
from potato.data_sources.partial_reader import PartialReader, PartialLoadingConfig

if TYPE_CHECKING:
    from potato.item_state_management import ItemStateManager

logger = logging.getLogger(__name__)

# Singleton instance with thread-safe initialization
DATA_SOURCE_MANAGER: Optional["DataSourceManager"] = None
_MANAGER_LOCK = threading.Lock()


# Registry of source type implementations
_SOURCE_REGISTRY: Dict[SourceType, Type[DataSource]] = {}


def register_source_type(source_type: SourceType, source_class: Type[DataSource]) -> None:
    """
    Register a data source implementation.

    Args:
        source_type: The SourceType enum value
        source_class: The DataSource subclass
    """
    _SOURCE_REGISTRY[source_type] = source_class
    logger.debug(f"Registered source type: {source_type.value} -> {source_class.__name__}")


def get_source_class(source_type: SourceType) -> Optional[Type[DataSource]]:
    """
    Get the source class for a given type.

    Args:
        source_type: The SourceType to look up

    Returns:
        The DataSource subclass, or None if not registered
    """
    return _SOURCE_REGISTRY.get(source_type)


def get_registered_types() -> List[str]:
    """Get list of registered source type names."""
    return [t.value for t in _SOURCE_REGISTRY.keys()]


class DataSourceManager:
    """
    Central manager for all data sources.

    This class provides:
    - Registration and lifecycle management of data sources
    - Credential management with environment variable substitution
    - Caching for remote sources
    - Partial/incremental loading coordination
    - Thread-safe access to all sources

    Attributes:
        config: The application configuration
        credential_manager: Handles credential resolution
        cache_manager: Manages cached remote files
        partial_reader: Coordinates incremental loading
    """

    def __init__(
        self,
        config: Dict[str, Any],
        item_state_manager: "ItemStateManager"
    ):
        """
        Initialize the data source manager.

        Args:
            config: Application configuration dictionary
            item_state_manager: The ItemStateManager for adding items
        """
        self._config = config
        self._item_state_manager = item_state_manager
        self._sources: Dict[str, DataSource] = {}
        self._lock = threading.RLock()

        # Initialize sub-managers
        self.credential_manager = CredentialManager.from_config(config)

        # Set up cache manager if caching is enabled
        cache_config = config.get("data_cache", {})
        if cache_config.get("enabled", True):
            cache_dir = cache_config.get(
                "cache_dir",
                ".potato_cache/data_sources"
            )
            # Resolve relative to task_dir
            task_dir = config.get("task_dir", ".")
            if not cache_dir.startswith("/"):
                import os
                cache_dir = os.path.join(task_dir, cache_dir)

            self.cache_manager = CacheManager(
                cache_dir=cache_dir,
                ttl_seconds=cache_config.get("ttl_seconds", 3600),
                max_size_mb=cache_config.get("max_size_mb", 500)
            )
        else:
            self.cache_manager = None

        # Set up partial reader if incremental loading is configured
        partial_config = PartialLoadingConfig.from_dict(config)
        if partial_config.enabled:
            output_dir = config.get("output_annotation_dir", ".")
            self.partial_reader = PartialReader(partial_config, output_dir)
        else:
            self.partial_reader = None

        # Get item property keys
        item_props = config.get("item_properties", {})
        self._id_key = item_props.get("id_key", "id")
        self._text_key = item_props.get("text_key", "text")

        # Initialize sources from configuration
        self._init_sources()

        logger.info(f"DataSourceManager initialized with {len(self._sources)} sources")

    def _init_sources(self) -> None:
        """Initialize data sources from configuration."""
        data_sources = self._config.get("data_sources", [])

        for index, source_dict in enumerate(data_sources):
            try:
                # Process credentials in the source config
                processed_config = self.credential_manager.process_config(source_dict)

                # Parse source configuration
                source_config = SourceConfig.from_dict(processed_config, index)

                if not source_config.enabled:
                    logger.debug(f"Skipping disabled source: {source_config.source_id}")
                    continue

                # Get the source class for this type
                source_class = get_source_class(source_config.source_type)
                if not source_class:
                    logger.warning(
                        f"No implementation for source type: {source_config.source_type.value}. "
                        f"Available types: {get_registered_types()}"
                    )
                    continue

                # Create the source instance
                source = source_class(source_config)

                # Validate configuration
                errors = source.validate_config()
                if errors:
                    logger.error(
                        f"Invalid configuration for source {source_config.source_id}: "
                        f"{'; '.join(errors)}"
                    )
                    continue

                # Check availability
                if not source.is_available():
                    logger.warning(
                        f"Source {source_config.source_id} is not available. "
                        f"Check dependencies and credentials."
                    )
                    # Still register the source, but log the warning
                    # It may become available later

                self._sources[source_config.source_id] = source
                logger.info(
                    f"Initialized source: {source_config.source_id} "
                    f"(type={source_config.source_type.value})"
                )

            except Exception as e:
                logger.error(f"Failed to initialize source at index {index}: {e}")

    def get_source(self, source_id: str) -> Optional[DataSource]:
        """
        Get a data source by ID.

        Args:
            source_id: The source identifier

        Returns:
            The DataSource instance, or None if not found
        """
        with self._lock:
            return self._sources.get(source_id)

    def get_all_sources(self) -> Dict[str, DataSource]:
        """
        Get all registered sources.

        Returns:
            Dictionary mapping source_id to DataSource
        """
        with self._lock:
            return dict(self._sources)

    def list_sources(self) -> List[Dict[str, Any]]:
        """
        List all sources with their status.

        Returns:
            List of source status dictionaries
        """
        with self._lock:
            statuses = []
            for source in self._sources.values():
                status = source.get_status()

                # Add partial loading state if available
                if self.partial_reader:
                    state = self.partial_reader.get_state(source.source_id)
                    if state:
                        status["items_loaded"] = state.items_loaded
                        status["is_complete"] = state.is_complete
                        status["last_loaded_at"] = state.last_loaded_at

                statuses.append(status)

            return statuses

    def load_initial_data(self) -> int:
        """
        Load initial data from all sources.

        If partial loading is enabled, loads only the initial_count items
        from each source. Otherwise, loads all data.

        Returns:
            Total number of items loaded
        """
        total_loaded = 0

        with self._lock:
            for source_id, source in self._sources.items():
                try:
                    count = self._load_from_source(source, is_initial=True)
                    total_loaded += count
                    logger.info(f"Loaded {count} items from {source_id}")
                except Exception as e:
                    logger.error(f"Failed to load from {source_id}: {e}")

        return total_loaded

    def load_more(
        self,
        source_id: str,
        count: Optional[int] = None
    ) -> int:
        """
        Load more items from a specific source.

        Args:
            source_id: The source to load from
            count: Number of items to load (uses batch_size if not specified)

        Returns:
            Number of items loaded

        Raises:
            ValueError: If source_id is not found
        """
        with self._lock:
            source = self._sources.get(source_id)
            if not source:
                raise ValueError(f"Unknown source: {source_id}")

            return self._load_from_source(source, is_initial=False, count=count)

    def _load_from_source(
        self,
        source: DataSource,
        is_initial: bool = True,
        count: Optional[int] = None
    ) -> int:
        """
        Load items from a source into the ItemStateManager.

        Args:
            source: The data source
            is_initial: Whether this is the initial load
            count: Number of items to load (overrides config)

        Returns:
            Number of items loaded
        """
        source_id = source.source_id

        # Check if source is complete
        if self.partial_reader:
            state = self.partial_reader.get_state(source_id)
            if state and state.is_complete:
                logger.debug(f"Source {source_id} is already complete")
                return 0

        # Determine how many items to load and from what position
        if self.partial_reader and self.partial_reader.config.enabled:
            start = self.partial_reader.get_start_position(source_id)
            if count is None:
                count = self.partial_reader.get_load_count(source_id, is_initial)
        else:
            start = 0
            count = None  # Load all

        # Check if source supports partial reading
        if start > 0 and not source.supports_partial_reading():
            logger.warning(
                f"Source {source_id} does not support partial reading, "
                f"cannot continue from position {start}"
            )
            return 0

        # Load items
        items_loaded = 0
        is_complete = False

        try:
            for item in source.read_items(start=start, count=count):
                # Validate ID key exists
                if self._id_key not in item:
                    logger.warning(
                        f"Missing id_key '{self._id_key}' in item from {source_id}"
                    )
                    continue

                instance_id = str(item[self._id_key])

                # Check for duplicates
                if self._item_state_manager.has_item(instance_id):
                    logger.debug(f"Skipping duplicate ID: {instance_id}")
                    continue

                # Add item to state manager
                try:
                    self._item_state_manager.add_item(instance_id, item)
                    items_loaded += 1
                except ValueError as e:
                    logger.warning(f"Failed to add item {instance_id}: {e}")

            # Check if we loaded fewer items than requested (source exhausted)
            if count is not None and items_loaded < count:
                is_complete = True

        except StopIteration:
            is_complete = True

        # Update partial reader state
        if self.partial_reader:
            total_estimate = source.get_total_count()
            self.partial_reader.update_state(
                source_id=source_id,
                items_added=items_loaded,
                is_complete=is_complete,
                total_estimate=total_estimate
            )

        return items_loaded

    def refresh_source(self, source_id: str) -> bool:
        """
        Refresh a data source (re-fetch from remote).

        Args:
            source_id: The source to refresh

        Returns:
            True if refresh was successful

        Raises:
            ValueError: If source_id is not found
        """
        with self._lock:
            source = self._sources.get(source_id)
            if not source:
                raise ValueError(f"Unknown source: {source_id}")

            # Invalidate cache
            if self.cache_manager:
                self.cache_manager.invalidate(source_id)

            # Reset partial reader state
            if self.partial_reader:
                self.partial_reader.reset_state(source_id)

            return source.refresh()

    def check_auto_load(
        self,
        annotated_count: int,
        total_loaded: int
    ) -> Dict[str, int]:
        """
        Check if any sources should auto-load more data.

        Args:
            annotated_count: Total number of annotated items
            total_loaded: Total number of loaded items

        Returns:
            Dictionary mapping source_id to items loaded (for sources that triggered)
        """
        if not self.partial_reader or not self.partial_reader.config.auto_load_enabled:
            return {}

        results = {}

        with self._lock:
            for source_id, source in self._sources.items():
                if self.partial_reader.should_load_more(
                    source_id, annotated_count, total_loaded
                ):
                    try:
                        loaded = self._load_from_source(source, is_initial=False)
                        if loaded > 0:
                            results[source_id] = loaded
                            logger.info(
                                f"Auto-loaded {loaded} items from {source_id}"
                            )
                    except Exception as e:
                        logger.error(f"Auto-load failed for {source_id}: {e}")

        return results

    def clear_cache(self) -> int:
        """
        Clear the download cache for all sources.

        Returns:
            Number of cache entries cleared
        """
        if self.cache_manager:
            return self.cache_manager.clear()
        return 0

    def get_stats(self) -> Dict[str, Any]:
        """
        Get comprehensive statistics.

        Returns:
            Dictionary with source and manager statistics
        """
        stats = {
            "source_count": len(self._sources),
            "sources": self.list_sources(),
        }

        if self.cache_manager:
            stats["cache"] = self.cache_manager.get_stats()

        if self.partial_reader:
            stats["partial_loading"] = self.partial_reader.get_stats()

        return stats

    def close(self) -> None:
        """Close all sources and release resources."""
        with self._lock:
            for source in self._sources.values():
                try:
                    source.close()
                except Exception as e:
                    logger.warning(f"Error closing source {source.source_id}: {e}")

            self._sources.clear()


def init_data_source_manager(config: Dict[str, Any]) -> Optional[DataSourceManager]:
    """
    Initialize the global DataSourceManager singleton.

    This function creates the manager if data_sources is configured in
    the configuration. Thread-safe initialization using double-checked
    locking pattern.

    Args:
        config: Application configuration dictionary

    Returns:
        The DataSourceManager instance, or None if not configured
    """
    global DATA_SOURCE_MANAGER

    # Check if data_sources is configured
    if "data_sources" not in config or not config["data_sources"]:
        return None

    # Double-checked locking
    if DATA_SOURCE_MANAGER is None:
        with _MANAGER_LOCK:
            if DATA_SOURCE_MANAGER is None:
                from potato.item_state_management import get_item_state_manager
                ism = get_item_state_manager()
                DATA_SOURCE_MANAGER = DataSourceManager(config, ism)

    return DATA_SOURCE_MANAGER


def get_data_source_manager() -> Optional[DataSourceManager]:
    """
    Get the global DataSourceManager singleton.

    Returns:
        The DataSourceManager instance, or None if not initialized
    """
    return DATA_SOURCE_MANAGER


def clear_data_source_manager() -> None:
    """
    Clear the global DataSourceManager singleton.

    This function closes all sources and clears the singleton instance.
    Thread-safe. Used primarily for testing.
    """
    global DATA_SOURCE_MANAGER

    with _MANAGER_LOCK:
        if DATA_SOURCE_MANAGER is not None:
            DATA_SOURCE_MANAGER.close()
            DATA_SOURCE_MANAGER = None

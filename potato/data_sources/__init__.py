"""
Data Sources Module

This module provides extensible data loading from various sources including
local files, URLs, cloud storage (Google Drive, Dropbox, S3), databases,
and other remote sources.

The module follows a singleton pattern for the DataSourceManager, similar
to other managers in Potato (ItemStateManager, UserStateManager).

Example usage:
    from potato.data_sources import (
        init_data_source_manager,
        get_data_source_manager,
        clear_data_source_manager
    )

    # Initialize with config
    manager = init_data_source_manager(config)

    # Load initial data
    manager.load_initial_data()

    # Get manager later
    manager = get_data_source_manager()

    # Load more data incrementally
    manager.load_more(source_id, count=500)
"""

from potato.data_sources.manager import (
    init_data_source_manager,
    get_data_source_manager,
    clear_data_source_manager,
    DataSourceManager,
)

from potato.data_sources.base import (
    DataSource,
    SourceType,
    SourceConfig,
)

from potato.data_sources.credentials import (
    CredentialManager,
    substitute_env_vars,
)

from potato.data_sources.cache_manager import (
    CacheManager,
    CacheEntry,
)

from potato.data_sources.partial_reader import (
    PartialReader,
    PartialReadState,
)

__all__ = [
    # Manager functions
    "init_data_source_manager",
    "get_data_source_manager",
    "clear_data_source_manager",
    "DataSourceManager",
    # Base classes
    "DataSource",
    "SourceType",
    "SourceConfig",
    # Credential management
    "CredentialManager",
    "substitute_env_vars",
    # Cache management
    "CacheManager",
    "CacheEntry",
    # Partial/incremental loading
    "PartialReader",
    "PartialReadState",
]

"""
Partial/incremental loading for data sources.

This module provides functionality for loading data in chunks, enabling:
- Initial loading of first K items
- Batch loading of additional items as annotation progresses
- Auto-loading when annotation reaches a threshold
- State persistence for resumption after restart
"""

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from potato.data_sources.base import DataSource

logger = logging.getLogger(__name__)


@dataclass
class PartialReadState:
    """
    Tracks the read state for a data source.

    This dataclass maintains information about how much data has been
    read from a source, enabling incremental loading.

    Attributes:
        source_id: Identifier of the data source
        items_loaded: Number of items loaded so far
        total_estimate: Estimated total items (None if unknown)
        file_position: Byte position for file-based sources
        line_number: Line number for line-based sources
        is_complete: Whether all data has been loaded
        last_loaded_at: Unix timestamp of last load
        metadata: Additional source-specific state
    """
    source_id: str
    items_loaded: int = 0
    total_estimate: Optional[int] = None
    file_position: int = 0
    line_number: int = 0
    is_complete: bool = False
    last_loaded_at: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "source_id": self.source_id,
            "items_loaded": self.items_loaded,
            "total_estimate": self.total_estimate,
            "file_position": self.file_position,
            "line_number": self.line_number,
            "is_complete": self.is_complete,
            "last_loaded_at": self.last_loaded_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PartialReadState":
        """Create from dictionary."""
        return cls(
            source_id=data["source_id"],
            items_loaded=data.get("items_loaded", 0),
            total_estimate=data.get("total_estimate"),
            file_position=data.get("file_position", 0),
            line_number=data.get("line_number", 0),
            is_complete=data.get("is_complete", False),
            last_loaded_at=data.get("last_loaded_at"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class PartialLoadingConfig:
    """
    Configuration for partial/incremental loading.

    Attributes:
        enabled: Whether partial loading is enabled
        initial_count: Number of items to load initially
        batch_size: Number of items per incremental load
        auto_load_threshold: Auto-load when this fraction is annotated (0.0-1.0)
        auto_load_enabled: Whether auto-loading is enabled
    """
    enabled: bool = False
    initial_count: int = 1000
    batch_size: int = 500
    auto_load_threshold: float = 0.8
    auto_load_enabled: bool = True

    @classmethod
    def from_dict(cls, config: Dict[str, Any]) -> "PartialLoadingConfig":
        """Create from configuration dictionary."""
        partial_config = config.get("partial_loading", {})
        return cls(
            enabled=partial_config.get("enabled", False),
            initial_count=partial_config.get("initial_count", 1000),
            batch_size=partial_config.get("batch_size", 500),
            auto_load_threshold=partial_config.get("auto_load_threshold", 0.8),
            auto_load_enabled=partial_config.get("auto_load_enabled", True),
        )

    def validate(self) -> List[str]:
        """Validate the configuration."""
        errors = []

        if self.initial_count < 1:
            errors.append("partial_loading.initial_count must be at least 1")

        if self.batch_size < 1:
            errors.append("partial_loading.batch_size must be at least 1")

        if not 0.0 <= self.auto_load_threshold <= 1.0:
            errors.append(
                "partial_loading.auto_load_threshold must be between 0.0 and 1.0"
            )

        return errors


class PartialReader:
    """
    Manages partial/incremental loading of data sources.

    This class coordinates loading data in chunks across multiple sources,
    tracking state for each source and providing auto-loading when
    annotation progress reaches a threshold.

    Thread Safety:
        All public methods are thread-safe. Internal state is protected
        by a lock.

    Attributes:
        config: Partial loading configuration
        state_file: Path to state persistence file
    """

    STATE_FILENAME = ".data_source_state.json"

    def __init__(
        self,
        config: PartialLoadingConfig,
        output_dir: str
    ):
        """
        Initialize the partial reader.

        Args:
            config: Partial loading configuration
            output_dir: Directory for state persistence
        """
        self.config = config
        self.output_dir = Path(output_dir)
        self.state_file = self.output_dir / self.STATE_FILENAME

        self._states: Dict[str, PartialReadState] = {}
        self._lock = threading.RLock()

        # Load existing state
        self._load_state()

        logger.info(
            f"PartialReader initialized: initial={config.initial_count}, "
            f"batch={config.batch_size}, auto_threshold={config.auto_load_threshold}"
        )

    def _load_state(self) -> None:
        """Load persisted state from disk."""
        if not self.state_file.exists():
            return

        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            for state_data in data.get("sources", []):
                state = PartialReadState.from_dict(state_data)
                self._states[state.source_id] = state

            logger.debug(f"Loaded partial read state for {len(self._states)} sources")

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to load partial read state: {e}")
            self._states = {}

    def _save_state(self) -> None:
        """Save state to disk."""
        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)

        data = {
            "version": 1,
            "sources": [state.to_dict() for state in self._states.values()]
        }

        try:
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
        except IOError as e:
            logger.error(f"Failed to save partial read state: {e}")

    def get_state(self, source_id: str) -> Optional[PartialReadState]:
        """
        Get the current state for a source.

        Args:
            source_id: The source identifier

        Returns:
            PartialReadState or None if not tracked
        """
        with self._lock:
            return self._states.get(source_id)

    def get_or_create_state(self, source_id: str) -> PartialReadState:
        """
        Get or create state for a source.

        Args:
            source_id: The source identifier

        Returns:
            PartialReadState for the source
        """
        with self._lock:
            if source_id not in self._states:
                self._states[source_id] = PartialReadState(source_id=source_id)
                self._save_state()
            return self._states[source_id]

    def update_state(
        self,
        source_id: str,
        items_added: int,
        file_position: Optional[int] = None,
        line_number: Optional[int] = None,
        is_complete: bool = False,
        total_estimate: Optional[int] = None
    ) -> PartialReadState:
        """
        Update the state after loading items.

        Args:
            source_id: The source identifier
            items_added: Number of items added in this batch
            file_position: New file position (for file sources)
            line_number: New line number (for line-based sources)
            is_complete: Whether all data has been loaded
            total_estimate: Updated total estimate

        Returns:
            Updated PartialReadState
        """
        import time

        with self._lock:
            state = self.get_or_create_state(source_id)
            state.items_loaded += items_added
            state.last_loaded_at = time.time()

            if file_position is not None:
                state.file_position = file_position
            if line_number is not None:
                state.line_number = line_number
            if total_estimate is not None:
                state.total_estimate = total_estimate
            if is_complete:
                state.is_complete = True

            self._save_state()
            return state

    def mark_complete(self, source_id: str) -> None:
        """
        Mark a source as completely loaded.

        Args:
            source_id: The source identifier
        """
        with self._lock:
            state = self.get_or_create_state(source_id)
            state.is_complete = True
            self._save_state()

    def should_load_more(
        self,
        source_id: str,
        annotated_count: int,
        total_loaded: int
    ) -> bool:
        """
        Check if more data should be loaded based on annotation progress.

        This method implements the auto-load threshold logic.

        Args:
            source_id: The source identifier
            annotated_count: Number of items annotated
            total_loaded: Total number of items loaded

        Returns:
            True if more data should be loaded
        """
        if not self.config.auto_load_enabled:
            return False

        with self._lock:
            state = self._states.get(source_id)
            if state and state.is_complete:
                return False

            if total_loaded == 0:
                return False

            progress = annotated_count / total_loaded
            return progress >= self.config.auto_load_threshold

    def get_load_count(
        self,
        source_id: str,
        is_initial: bool = False
    ) -> int:
        """
        Get the number of items to load.

        Args:
            source_id: The source identifier
            is_initial: Whether this is the initial load

        Returns:
            Number of items to load
        """
        if is_initial:
            return self.config.initial_count
        return self.config.batch_size

    def get_start_position(self, source_id: str) -> int:
        """
        Get the starting position for the next load.

        Args:
            source_id: The source identifier

        Returns:
            Number of items already loaded (start position for next batch)
        """
        with self._lock:
            state = self._states.get(source_id)
            if state:
                return state.items_loaded
            return 0

    def reset_state(self, source_id: str) -> None:
        """
        Reset the state for a source.

        Args:
            source_id: The source identifier
        """
        with self._lock:
            if source_id in self._states:
                del self._states[source_id]
                self._save_state()

    def clear_all_state(self) -> None:
        """Clear state for all sources."""
        with self._lock:
            self._states.clear()
            self._save_state()

    def get_all_states(self) -> Dict[str, PartialReadState]:
        """
        Get all source states.

        Returns:
            Dictionary mapping source_id to PartialReadState
        """
        with self._lock:
            return dict(self._states)

    def get_stats(self) -> Dict[str, Any]:
        """
        Get statistics about partial loading.

        Returns:
            Dictionary with loading statistics
        """
        with self._lock:
            total_loaded = sum(s.items_loaded for s in self._states.values())
            complete_count = sum(1 for s in self._states.values() if s.is_complete)

            return {
                "enabled": self.config.enabled,
                "initial_count": self.config.initial_count,
                "batch_size": self.config.batch_size,
                "auto_load_threshold": self.config.auto_load_threshold,
                "sources_tracked": len(self._states),
                "sources_complete": complete_count,
                "total_items_loaded": total_loaded,
            }

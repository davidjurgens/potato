"""
Data source implementations.

This module registers all available data source types. Source implementations
are lazy-loaded to avoid importing optional dependencies.

To add a new source type:
1. Create a new module (e.g., my_source.py) with a DataSource subclass
2. Import and register it in this file
3. Add any required dependencies to the requirements.txt (as optional)
"""

import logging

from potato.data_sources.base import SourceType
from potato.data_sources.manager import register_source_type

logger = logging.getLogger(__name__)


def _register_all_sources() -> None:
    """Register all available source implementations."""

    # Local file source - always available
    try:
        from potato.data_sources.sources.local_source import LocalFileSource
        register_source_type(SourceType.FILE, LocalFileSource)
    except ImportError as e:
        logger.debug(f"LocalFileSource not available: {e}")

    # URL source - always available (uses standard library)
    try:
        from potato.data_sources.sources.url_source import URLSource
        register_source_type(SourceType.URL, URLSource)
    except ImportError as e:
        logger.debug(f"URLSource not available: {e}")

    # Google Drive source - requires google-api-python-client
    try:
        from potato.data_sources.sources.gdrive_source import GoogleDriveSource
        register_source_type(SourceType.GOOGLE_DRIVE, GoogleDriveSource)
    except ImportError as e:
        logger.debug(f"GoogleDriveSource not available: {e}")

    # Dropbox source - requires dropbox
    try:
        from potato.data_sources.sources.dropbox_source import DropboxSource
        register_source_type(SourceType.DROPBOX, DropboxSource)
    except ImportError as e:
        logger.debug(f"DropboxSource not available: {e}")

    # S3 source - requires boto3
    try:
        from potato.data_sources.sources.s3_source import S3Source
        register_source_type(SourceType.S3, S3Source)
    except ImportError as e:
        logger.debug(f"S3Source not available: {e}")

    # HuggingFace source - requires datasets
    try:
        from potato.data_sources.sources.huggingface_source import HuggingFaceSource
        register_source_type(SourceType.HUGGINGFACE, HuggingFaceSource)
    except ImportError as e:
        logger.debug(f"HuggingFaceSource not available: {e}")

    # Google Sheets source - requires google-api-python-client
    try:
        from potato.data_sources.sources.gsheets_source import GoogleSheetsSource
        register_source_type(SourceType.GOOGLE_SHEETS, GoogleSheetsSource)
    except ImportError as e:
        logger.debug(f"GoogleSheetsSource not available: {e}")

    # Database source - requires sqlalchemy
    try:
        from potato.data_sources.sources.database_source import DatabaseSource
        register_source_type(SourceType.DATABASE, DatabaseSource)
    except ImportError as e:
        logger.debug(f"DatabaseSource not available: {e}")


# Register sources when module is imported
_register_all_sources()

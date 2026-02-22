"""
Format Handler Registry

Provides a centralized registry for managing format handlers.
Supports auto-detection of formats from file extensions.

Usage:
    from potato.format_handlers.registry import format_handler_registry

    # Extract content from a file (auto-detect format)
    output = format_handler_registry.extract("document.pdf")

    # Extract with specific options
    output = format_handler_registry.extract(
        "document.pdf",
        options={"extraction_mode": "text", "max_pages": 10}
    )

    # List supported formats
    formats = format_handler_registry.get_supported_formats()

    # Check if a file is supported
    if format_handler_registry.can_handle("document.pdf"):
        output = format_handler_registry.extract("document.pdf")
"""

from typing import Dict, List, Any, Optional, Type
from pathlib import Path
import logging

from .base import BaseFormatHandler, FormatOutput

logger = logging.getLogger(__name__)


class FormatHandlerRegistry:
    """
    Centralized registry for format handlers.

    Provides methods to register, retrieve, and use format handlers.
    Supports both built-in handlers and custom plugins.
    """

    def __init__(self):
        self._handlers: Dict[str, BaseFormatHandler] = {}
        self._extension_map: Dict[str, str] = {}  # Extension -> format_name
        logger.debug("FormatHandlerRegistry initialized")

    def register(self, handler: BaseFormatHandler) -> None:
        """
        Register a format handler.

        Args:
            handler: BaseFormatHandler instance to register

        Raises:
            ValueError: If a handler for this format is already registered
        """
        name = handler.format_name

        if name in self._handlers:
            raise ValueError(f"Format handler '{name}' is already registered")

        self._handlers[name] = handler

        # Map extensions to this handler
        for ext in handler.supported_extensions:
            ext_lower = ext.lower()
            if ext_lower in self._extension_map:
                existing = self._extension_map[ext_lower]
                logger.warning(
                    f"Extension '{ext}' already mapped to '{existing}', "
                    f"overriding with '{name}'"
                )
            self._extension_map[ext_lower] = name

        logger.debug(
            f"Registered format handler: {name} "
            f"(extensions: {handler.supported_extensions})"
        )

    def unregister(self, format_name: str) -> bool:
        """
        Unregister a format handler.

        Args:
            format_name: Name of the format to unregister

        Returns:
            True if handler was unregistered, False if not found
        """
        if format_name not in self._handlers:
            return False

        handler = self._handlers[format_name]

        # Remove extension mappings
        for ext in handler.supported_extensions:
            ext_lower = ext.lower()
            if self._extension_map.get(ext_lower) == format_name:
                del self._extension_map[ext_lower]

        del self._handlers[format_name]
        logger.debug(f"Unregistered format handler: {format_name}")
        return True

    def get_handler(self, format_name: str) -> Optional[BaseFormatHandler]:
        """
        Get a handler by format name.

        Args:
            format_name: The format name (e.g., "pdf", "docx")

        Returns:
            BaseFormatHandler if found, None otherwise
        """
        return self._handlers.get(format_name)

    def get_handler_for_file(self, file_path: str) -> Optional[BaseFormatHandler]:
        """
        Get the appropriate handler for a file based on its extension.

        Args:
            file_path: Path to the file

        Returns:
            BaseFormatHandler if a matching handler exists, None otherwise
        """
        ext = Path(file_path).suffix.lower()
        format_name = self._extension_map.get(ext)
        if format_name:
            return self._handlers.get(format_name)
        return None

    def detect_format(self, file_path: str) -> Optional[str]:
        """
        Detect the format of a file based on its extension.

        Args:
            file_path: Path to the file

        Returns:
            Format name if detected, None otherwise
        """
        ext = Path(file_path).suffix.lower()
        return self._extension_map.get(ext)

    def can_handle(self, file_path: str) -> bool:
        """
        Check if any registered handler can process the file.

        Args:
            file_path: Path to the file

        Returns:
            True if a handler is available
        """
        return self.get_handler_for_file(file_path) is not None

    def extract(
        self,
        file_path: str,
        format_name: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None
    ) -> FormatOutput:
        """
        Extract content from a file.

        Args:
            file_path: Path to the file
            format_name: Optional format override (auto-detect if not specified)
            options: Optional extraction options

        Returns:
            FormatOutput with extracted content

        Raises:
            ValueError: If no handler is available for the file
            FileNotFoundError: If the file doesn't exist
        """
        # Determine handler to use
        if format_name:
            handler = self.get_handler(format_name)
            if not handler:
                raise ValueError(
                    f"No handler registered for format '{format_name}'. "
                    f"Available formats: {', '.join(self.get_supported_formats())}"
                )
        else:
            handler = self.get_handler_for_file(file_path)
            if not handler:
                ext = Path(file_path).suffix
                raise ValueError(
                    f"No handler available for extension '{ext}'. "
                    f"Supported extensions: {', '.join(self.get_supported_extensions())}"
                )

        # Validate file
        errors = handler.validate_file(file_path)
        if errors:
            raise ValueError(f"File validation failed: {'; '.join(errors)}")

        # Extract content
        logger.info(f"Extracting content from '{file_path}' using {handler.format_name} handler")
        return handler.extract(file_path, options)

    def get_supported_formats(self) -> List[str]:
        """
        Get list of all supported format names.

        Returns:
            Sorted list of format names
        """
        return sorted(self._handlers.keys())

    def get_supported_extensions(self) -> List[str]:
        """
        Get list of all supported file extensions.

        Returns:
            Sorted list of extensions
        """
        return sorted(self._extension_map.keys())

    def list_handlers(self) -> List[Dict[str, Any]]:
        """
        List all registered handlers with their metadata.

        Returns:
            List of handler information dictionaries
        """
        result = []
        for name, handler in sorted(self._handlers.items()):
            missing_deps = handler.check_dependencies()
            result.append({
                "name": name,
                "description": handler.description,
                "extensions": handler.supported_extensions,
                "requires": handler.requires_dependencies,
                "available": len(missing_deps) == 0,
                "missing_dependencies": missing_deps,
            })
        return result

    def is_registered(self, format_name: str) -> bool:
        """
        Check if a format is registered.

        Args:
            format_name: The format name

        Returns:
            True if registered
        """
        return format_name in self._handlers


# Global registry instance
format_handler_registry = FormatHandlerRegistry()


def _register_builtin_handlers() -> None:
    """
    Register all built-in format handlers.
    Called automatically when this module is imported.
    """
    # Import handlers here to avoid circular imports
    # and to make dependencies optional
    handlers_to_register = []

    # PDF Handler
    try:
        from .pdf_handler import PDFHandler
        handlers_to_register.append(PDFHandler())
    except ImportError as e:
        logger.debug(f"PDF handler not available: {e}")

    # DOCX Handler
    try:
        from .docx_handler import DocxHandler
        handlers_to_register.append(DocxHandler())
    except ImportError as e:
        logger.debug(f"DOCX handler not available: {e}")

    # Markdown Handler
    try:
        from .markdown_handler import MarkdownHandler
        handlers_to_register.append(MarkdownHandler())
    except ImportError as e:
        logger.debug(f"Markdown handler not available: {e}")

    # Spreadsheet Handler
    try:
        from .spreadsheet_handler import SpreadsheetHandler
        handlers_to_register.append(SpreadsheetHandler())
    except ImportError as e:
        logger.debug(f"Spreadsheet handler not available: {e}")

    # Code Handler
    try:
        from .code_handler import CodeHandler
        handlers_to_register.append(CodeHandler())
    except ImportError as e:
        logger.debug(f"Code handler not available: {e}")

    # Register all available handlers
    for handler in handlers_to_register:
        try:
            format_handler_registry.register(handler)
        except Exception as e:
            logger.warning(f"Failed to register {handler.format_name} handler: {e}")

    logger.debug(f"Registered {len(handlers_to_register)} format handlers")


# Auto-register built-in handlers on import
_register_builtin_handlers()

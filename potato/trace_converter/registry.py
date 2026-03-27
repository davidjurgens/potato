"""
Trace Converter Registry

Centralized registry for trace format converters, following
the same pattern as SchemaRegistry, DisplayRegistry, and ExportRegistry.

Usage:
    from potato.trace_converter.registry import converter_registry

    # Convert traces
    traces = converter_registry.convert("langchain", data)

    # Auto-detect format
    format_name = converter_registry.detect_format(data)

    # List formats
    formats = converter_registry.get_supported_formats()
"""

import logging
from typing import Dict, List, Optional, Any

from .base import BaseTraceConverter, CanonicalTrace

logger = logging.getLogger(__name__)


class TraceConverterRegistry:
    """
    Centralized registry for trace format converters.
    """

    def __init__(self):
        self._converters: Dict[str, BaseTraceConverter] = {}
        logger.debug("TraceConverterRegistry initialized")

    def register(self, converter: BaseTraceConverter) -> None:
        """Register a converter instance."""
        name = converter.format_name
        if not name:
            raise ValueError("Converter must have a non-empty format_name")
        if name in self._converters:
            raise ValueError(f"Converter '{name}' is already registered")
        self._converters[name] = converter
        logger.debug(f"Registered trace converter: {name}")

    def get(self, name: str) -> Optional[BaseTraceConverter]:
        """Get a converter by format name."""
        return self._converters.get(name)

    def convert(self, format_name: str, data: Any,
                options: Optional[Dict] = None) -> List[CanonicalTrace]:
        """
        Convert traces using the named format converter.

        Args:
            format_name: Converter name (e.g., "langchain", "react")
            data: Input data to convert
            options: Format-specific options

        Returns:
            List of CanonicalTrace objects

        Raises:
            ValueError: If format is not registered
        """
        converter = self.get(format_name)
        if not converter:
            supported = ", ".join(sorted(self._converters.keys()))
            raise ValueError(
                f"Unknown trace format: '{format_name}'. "
                f"Supported formats: {supported}"
            )
        return converter.convert(data, options)

    def detect_format(self, data: Any) -> Optional[str]:
        """
        Auto-detect the format of input data.

        Args:
            data: Parsed input data

        Returns:
            Format name if detected, None otherwise
        """
        for name, converter in self._converters.items():
            try:
                if converter.detect(data):
                    logger.info(f"Auto-detected trace format: {name}")
                    return name
            except Exception:
                continue
        return None

    def get_supported_formats(self) -> List[str]:
        """Get sorted list of supported format names."""
        return sorted(self._converters.keys())

    def list_converters(self) -> List[Dict[str, str]]:
        """List all registered converters with metadata."""
        return [
            converter.get_format_info()
            for converter in sorted(self._converters.values(),
                                    key=lambda c: c.format_name)
        ]

    def is_registered(self, name: str) -> bool:
        """Check if a format is registered."""
        return name in self._converters


# Global registry instance
converter_registry = TraceConverterRegistry()


def _register_builtin_converters():
    """Register all built-in converters. Called on import.

    Registration order matters for auto-detection (first match wins).
    More specific formats are registered before generic ones to avoid
    false positives:
    - ReAct before MultiAgent (both have "steps" but ReAct steps have thought/action/observation)
    - SWE-bench before ReAct (instance_id is highly specific)
    - OTEL before others (trace_id+span_id is unique)
    - MCP before others (MCP methods are distinctive)
    - Anthropic before OpenAI (content blocks vs string content)
    - MultiAgent last among message-based (checks for sender/receiver/agents)
    """
    from .converters.react_converter import ReActConverter
    from .converters.langchain_converter import LangChainConverter
    from .converters.langfuse_converter import LangfuseConverter
    from .converters.atif_converter import ATIFConverter
    from .converters.webarena_converter import WebArenaConverter
    from .converters.swebench_converter import SWEBenchConverter
    from .converters.otel_converter import OTELConverter
    from .converters.mcp_converter import MCPConverter
    from .converters.anthropic_converter import AnthropicConverter
    from .converters.openai_converter import OpenAIConverter
    from .converters.multi_agent_converter import MultiAgentConverter
    from .converters.web_agent_converter import WebAgentConverter
    from .converters.claude_code_converter import ClaudeCodeConverter
    from .converters.aider_converter import AiderConverter
    from .converters.swe_agent_trajectory_converter import SWEAgentTrajectoryConverter

    converters = [
        # Existing converters (specific formats first)
        ReActConverter(),
        LangChainConverter(),
        LangfuseConverter(),
        ATIFConverter(),
        # Web agent (with coordinates/mouse_path) before plain WebArena
        WebAgentConverter(),
        WebArenaConverter(),
        # New converters (specific-to-generic order)
        SWEBenchConverter(),
        SWEAgentTrajectoryConverter(),  # SWE-Agent trajectories before generic
        AiderConverter(),               # Aider edit blocks
        OTELConverter(),
        MCPConverter(),
        ClaudeCodeConverter(),  # Before Anthropic (more specific: coding tool names)
        AnthropicConverter(),
        OpenAIConverter(),
        MultiAgentConverter(),
    ]

    for converter in converters:
        converter_registry.register(converter)

    logger.debug(f"Registered {len(converters)} built-in trace converters")


_register_builtin_converters()

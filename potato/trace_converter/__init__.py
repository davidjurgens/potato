"""
Trace Converter Package

Converts agent traces from various formats to Potato's canonical JSONL format.

Usage:
    python -m potato.trace_converter --input traces.json --input-format langchain --output data.jsonl

Supported formats:
    - langchain: LangSmith/LangChain export format
    - langfuse: Langfuse observation export format
    - atif: Academic Trace Interchange Format
    - webarena: WebArena/GUI benchmark format
    - react: Generic ReAct JSON format
"""

from .registry import converter_registry
from .base import BaseTraceConverter

__all__ = [
    'converter_registry',
    'BaseTraceConverter',
]

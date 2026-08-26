"""
Model Context Protocol server for Potato.

Lets a coding agent (Claude Code, Codex, Cursor) discover annotation types,
validate a config it wrote, and look at the page that config produces -- without
a human reading errors back to it.

The package is deliberately *not* named `potato/mcp/`. Potato is routinely run
as `python potato/flask_server.py`, which puts `potato/` at the front of
`sys.path`, so a subpackage named `mcp` would shadow the official MCP SDK this
module imports. The same trap already forced `datasets` to become
`eval_datasets`; `tests/unit/test_import_shadowing.py` now enforces it.

The SDK is an optional dependency:

    pip install 'potato-annotation[mcp]'

Nothing here is imported at server boot.
"""

from potato.mcp_server.tools_local import (  # noqa: F401
    describe_annotation_type,
    describe_config_key,
    describe_display_type,
    get_config_schema,
    get_example,
    list_annotation_types,
    list_config_keys,
    list_display_types,
    list_examples,
    preview_config,
    validate_config,
)

__all__ = [
    "describe_annotation_type",
    "describe_config_key",
    "describe_display_type",
    "get_config_schema",
    "get_example",
    "list_annotation_types",
    "list_config_keys",
    "list_display_types",
    "list_examples",
    "preview_config",
    "validate_config",
]

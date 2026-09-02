"""
The MCP server: registers Potato's local tools, resources and prompt.

Tools are the thin wrappers in `tools_local`, plus `render_task_screenshot`,
which is the one that needs a browser and returns an image.

Two of these carry most of the value. `validate_config` is why an agent
converges rather than guessing: it is the server's own validator, so satisfying
it means the config really works. `render_task_screenshot` is why this is worth
being an MCP server rather than another document: the agent sees the page it
built, and gets the browser's uncaught exceptions with it.

Writes are confined to `--root`. Nothing here reaches a running Potato instance;
that is a separate, config-gated surface.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

INSTALL_HINT = (
    "The MCP SDK is not installed. Install it with:\n"
    "    pip install 'potato-annotation[mcp]'"
)

SERVER_NAME = "potato"

INSTRUCTIONS = """\
Potato is a web annotation platform for NLP research. Tasks are defined by a
single YAML config.

The loop that works:

  1. list_annotation_types() to see what is available, then
     describe_annotation_type(name) for the one you want. Its `example` field is
     a scheme lifted from a config that really runs -- start from that rather
     than assembling fields yourself.
  2. list_examples(...) to find a whole project close to the task, and
     get_example(name) to read its config.
  3. Write the config. Put this line at the top so editors validate it live:
     # yaml-language-server: $schema=https://potatoannotator.readthedocs.io/en/latest/schemas/potato-config.schema.json
  4. validate_config(path) -- the server's own validator. Fix what it reports
     and run it again.
  5. render_task_screenshot(path) -- boots the task in a browser and returns the
     annotation page plus any errors the browser hit. A config can validate
     cleanly and still render a broken interface; this is what catches that.

Four keys are always required: annotation_task_name, task_dir,
output_annotation_dir, item_properties (with id_key and text_key). A data source
is also required: data_files, data_directory, or data_sources.

Paths are resolved against task_dir, and anything resolving outside it is
rejected.
"""


def check_sdk_available() -> bool:
    try:
        import mcp  # noqa: F401
        return True
    except ImportError:
        return False


def _resolve(root: str, path: str) -> Optional[str]:
    """Resolve `path` under `root`, or None if it escapes.

    The agent chooses these paths, so they are checked rather than trusted --
    the same rule `validate_path_security()` applies to config paths.
    """
    candidate = os.path.realpath(os.path.join(root, path))
    root_real = os.path.realpath(root)
    if candidate == root_real or candidate.startswith(root_real + os.sep):
        return candidate
    return None


def build_server(root: Optional[str] = None):
    """Construct the FastMCP server. Raises ImportError without the SDK."""
    from mcp.server.fastmcp import FastMCP

    from potato.mcp_server import tools_local as local

    root_dir = os.path.realpath(root or os.getcwd())
    mcp_server = FastMCP(SERVER_NAME, instructions=INSTRUCTIONS)

    def _outside(path: str) -> Dict[str, Any]:
        return {
            "error": f"{path!r} is outside the server root ({root_dir}).",
            "hint": "Start the server with --root pointing at your project.",
        }

    # ------------------------------------------------------------- discovery --

    @mcp_server.tool()
    def list_annotation_types() -> List[Dict[str, Any]]:
        """List every annotation type Potato supports, with a short description."""
        return local.list_annotation_types()

    @mcp_server.tool()
    def describe_annotation_type(name: str) -> Dict[str, Any]:
        """Full field list and a working example for one annotation type.

        The `example` is taken from a shipped config that uses this type, so it
        is known to run.
        """
        return local.describe_annotation_type(name)

    @mcp_server.tool()
    def list_display_types() -> List[Dict[str, Any]]:
        """List every `instance_display` field type (text, image, audio, ...)."""
        return local.list_display_types()

    @mcp_server.tool()
    def describe_display_type(name: str) -> Dict[str, Any]:
        """Required and optional keys for one `instance_display` field type."""
        return local.describe_display_type(name)

    @mcp_server.tool()
    def list_config_keys(category: Optional[str] = None) -> List[Dict[str, Any]]:
        """List documented top-level config keys, optionally by category."""
        return local.list_config_keys(category)

    @mcp_server.tool()
    def describe_config_key(path: str) -> Dict[str, Any]:
        """Describe one config key by dotted path, e.g. `attention_checks.frequency`."""
        return local.describe_config_key(path)

    @mcp_server.tool()
    def get_config_schema() -> Dict[str, Any]:
        """The complete config JSON Schema.

        Large. Prefer describe_annotation_type / describe_config_key unless you
        need the whole contract.
        """
        return local.get_config_schema()

    # -------------------------------------------------------------- examples --

    @mcp_server.tool()
    def list_examples(
        annotation_type: Optional[str] = None,
        display_type: Optional[str] = None,
        category: Optional[str] = None,
        config_key: Optional[str] = None,
        query: Optional[str] = None,
        limit: int = 20,
    ) -> Dict[str, Any]:
        """Find shipped example projects. Filters are combined with AND.

        Copying a working example beats assembling a config from field lists.
        """
        return local.list_examples(
            annotation_type=annotation_type,
            display_type=display_type,
            category=category,
            config_key=config_key,
            query=query,
            limit=limit,
        )

    @mcp_server.tool()
    def get_example(name: str) -> Dict[str, Any]:
        """Read one example's full config, by directory (`classification/likert`)."""
        return local.get_example(name)

    # ------------------------------------------------------------ validation --

    @mcp_server.tool()
    def validate_config(
        path: Optional[str] = None, yaml_text: Optional[str] = None
    ) -> Dict[str, Any]:
        """Validate a config with the server's own validator.

        Pass a path relative to the server root, or the YAML text directly.
        Returns errors, unrecognized keys, and other warnings. Run this after
        every edit -- it is the same check `potato start` performs.
        """
        if path:
            resolved = _resolve(root_dir, path)
            if resolved is None:
                return _outside(path)
            return local.validate_config(path=resolved)
        return local.validate_config(yaml_text=yaml_text)

    @mcp_server.tool()
    def preview_config(path: str) -> Dict[str, Any]:
        """Show what a config declares: schemes, labels, keybindings, conflicts.

        No server is started. Use render_task_screenshot to see the real page.
        """
        resolved = _resolve(root_dir, path)
        if resolved is None:
            return _outside(path)
        return local.preview_config(resolved)

    @mcp_server.tool()
    def render_task_screenshot(
        path: str, phase: str = "annotation", width: int = 1280, height: int = 900
    ) -> List[Any]:
        """Boot the task, screenshot the annotation page, report browser errors.

        Returns the image plus a summary of every uncaught exception,
        console.error and failed request. A config can validate cleanly and
        still render a broken interface -- most annotation UI is built by
        JavaScript after the HTML arrives, so this is the only check that sees
        those failures.
        """
        from mcp.server.fastmcp import Image as _Image  # noqa: F811

        from potato.preview_render import capture_task, playwright_available

        # FastMCP serializes ContentBlock instances, not the Image helper, so
        # the helper has to be converted before it goes back over the wire.

        resolved = _resolve(root_dir, path)
        if resolved is None:
            return [_json_block(_outside(path))]

        if not playwright_available():
            return [_json_block({
                "error": "Playwright is not installed, so no screenshot is possible.",
                "install": (
                    "pip install 'potato-annotation[preview]' && "
                    "playwright install chromium"
                ),
            })]

        out_path = os.path.join(root_dir, ".potato-preview.png")
        result = capture_task(
            resolved, phase=phase, out_path=out_path, width=width, height=height
        )

        blocks: List[Any] = [_json_block({
            "ok": result.ok,
            "clean": result.clean,
            "summary": result.summary(),
            "console_errors": result.console_errors,
            "page_errors": result.page_errors,
            "http_errors": result.http_errors,
            "message": result.message,
        })]

        if result.png_path and os.path.isfile(result.png_path):
            with open(result.png_path, "rb") as f:
                image = _Image(data=f.read(), format="png")
            blocks.append(image.to_image_content())
            os.unlink(result.png_path)
        return blocks

    # ------------------------------------------------------------- resources --

    @mcp_server.resource("potato://config-schema")
    def config_schema_resource() -> str:
        """The config JSON Schema."""
        import json

        return json.dumps(local.get_config_schema(), indent=2)

    @mcp_server.resource("potato://annotation-types")
    def annotation_types_resource() -> str:
        """Every annotation type with its fields and a worked example."""
        import json

        return json.dumps(
            [local.describe_annotation_type(t["name"])
             for t in local.list_annotation_types()],
            indent=2,
        )

    @mcp_server.resource("potato://examples")
    def examples_resource() -> str:
        """The catalog of shipped example projects."""
        import json

        from potato.server_utils.examples_manifest import load_manifest

        return json.dumps(load_manifest() or {}, indent=2)

    @mcp_server.resource("potato://guide")
    def guide_resource() -> str:
        """How to author a Potato task."""
        return INSTRUCTIONS

    # ---------------------------------------------------------------- prompt --

    @mcp_server.prompt()
    def author_potato_task(description: str) -> str:
        """Author a new Potato annotation task from a plain-English description."""
        return (
            f"Build a Potato annotation task for this: {description}\n\n"
            f"{INSTRUCTIONS}\n"
            "Work through the loop above in order. Do not hand back a config "
            "you have not run validate_config on, and prefer starting from an "
            "example over writing schemes from scratch."
        )

    return mcp_server


def _json_block(payload: Dict[str, Any]):
    """Wrap a dict as MCP text content."""
    import json

    from mcp.types import TextContent

    return TextContent(type="text", text=json.dumps(payload, indent=2))

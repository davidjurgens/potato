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
from typing import Annotated, Any, Dict, List, Optional

from pydantic import Field

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

  1. list_examples(...) to find a shipped project close to the task, and
     get_example(name) to read its config. Copying a config that runs beats
     assembling one from field lists.
  2. describe_annotation_type(name) for each scheme you add or change. Its
     `example` is a scheme taken from a config that runs. list_annotation_types()
     lists them all.
  3. Write the config. Put this line at the top so editors validate it live:
     # yaml-language-server: $schema=https://potatoannotator.readthedocs.io/en/latest/schemas/potato-config.schema.json
  4. validate_config(path), the server's own validator. Fix what it reports
     and run it again.
  5. render_task_screenshot(path) boots the task in a browser and returns the
     annotation page plus any errors the browser hit. A config can validate
     cleanly and still render a broken interface, and the screenshot shows it.

Four keys are always required: annotation_task_name, task_dir,
output_annotation_dir, item_properties (with id_key and text_key). A data source
is also required: data_files, data_directory, or data_sources.

Paths are resolved against task_dir, and anything resolving outside it is
rejected.
"""

#: Every local tool and what an agent is told about it. `potato mcp tools`
#: prints the first line of each, so the two cannot drift apart, and it needs
#: no SDK to do so.
TOOL_DESCRIPTIONS = {
    "list_annotation_types": (
        "List every annotation type Potato supports, with a one-line "
        "description and its required fields."
    ),
    "describe_annotation_type": (
        "Fields and a working example for one annotation type.\n\n"
        "The `example` is a scheme from a shipped config that uses this type, "
        "so it is known to run."
    ),
    "list_display_types": (
        "List every `instance_display` field type (text, image, audio, ...)."
    ),
    "describe_display_type": (
        "Required and optional keys for one `instance_display` field type."
    ),
    "list_plugins": (
        "Installed plugins, read from package metadata without importing them."
        "\n\nPass `name` to load one plugin and list the annotation and "
        "display types it adds. A plugin's types work only in a config that "
        "lists the plugin under `plugins:`."
    ),
    "list_config_keys": (
        "List the documented top-level config keys, optionally for one "
        "category.\n\nWithout a category it returns every key. "
        "describe_config_key answers about one."
    ),
    "describe_config_key": (
        "Describe one config key by dotted path, e.g. "
        "`attention_checks.frequency`: type, default, example and sub-keys."
    ),
    "get_config_schema": (
        "The config JSON Schema for one key, by dotted path.\n\n"
        "Without `key` it returns the top-level key names and what is "
        "required. `full=true` returns the whole schema, which is very large."
    ),
    "list_examples": (
        "Find shipped example projects. Filters combine with AND.\n\n"
        "Start here: copying a working example beats assembling a config from "
        "field lists. A filter that matches nothing says which one and what "
        "it accepts."
    ),
    "get_example": (
        "Read one example's full config, by the `name` list_examples returns "
        "(`classification/likert`)."
    ),
    "validate_config": (
        "Validate a config with the server's own validator, the same check "
        "`potato start` runs.\n\n"
        "Pass a path relative to the server root, or the YAML text. Returns "
        "errors, unrecognized keys and other warnings. Run it after every edit."
    ),
    "preview_config": (
        "Show what a config declares: schemes, labels, keybindings and their "
        "conflicts.\n\nNo server is started; render_task_screenshot shows the "
        "real page."
    ),
    "render_task_screenshot": (
        "Boot the task, screenshot one page, and report browser errors.\n\n"
        "Returns the image plus every uncaught exception, console.error and "
        "failed request. Most annotation UI is built by JavaScript after the "
        "HTML arrives, so a config that validates can still render a broken "
        "page, and this is the only check that sees it. Needs Playwright."
    ),
}


def _compact(result: Any) -> str:
    """A tool result as compact JSON.

    FastMCP indents JSON results by two spaces, and every tool used to
    advertise an output schema that said only "an object". Returning text
    drops both. The full config schema is a third smaller this way.
    """
    import json

    return json.dumps(result, ensure_ascii=False, default=str,
                      separators=(",", ":"))


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

    from mcp.types import ToolAnnotations

    def tool(read_only: bool = True):
        """Register a tool under its TOOL_DESCRIPTIONS entry.

        Every tool here only reads, except render_task_screenshot, which boots
        the task and so may write its output directory.
        """
        def register(fn):
            return mcp_server.tool(
                description=TOOL_DESCRIPTIONS[fn.__name__],
                annotations=ToolAnnotations(
                    readOnlyHint=read_only, destructiveHint=False,
                    idempotentHint=True, openWorldHint=False),
                structured_output=False,
            )(fn)
        return register

    # ------------------------------------------------------------- discovery --

    @tool()
    def list_annotation_types() -> str:
        return _compact(local.list_annotation_types())

    @tool()
    def describe_annotation_type(
        name: Annotated[str, Field(description="An annotation type, e.g. radio, span, likert")],
    ) -> str:
        return _compact(local.describe_annotation_type(name))

    @tool()
    def list_display_types() -> str:
        return _compact(local.list_display_types())

    @tool()
    def list_plugins(
        name: Annotated[Optional[str], Field(
            description="One installed plugin to load and describe")] = None,
    ) -> str:
        return _compact(local.list_plugins(name))

    @tool()
    def describe_display_type(
        name: Annotated[str, Field(description="A display type, e.g. image, audio, dialogue")],
    ) -> str:
        return _compact(local.describe_display_type(name))

    @tool()
    def list_config_keys(
        category: Annotated[Optional[str], Field(description=(
            "Matched without case, exactly or as a substring: 'auth' finds "
            "'Authentication / Login'. An unknown one returns the categories."
        ))] = None,
    ) -> str:
        return _compact(local.list_config_keys(category))

    @tool()
    def describe_config_key(
        path: Annotated[str, Field(description="Dotted key path, e.g. attention_checks.frequency")],
    ) -> str:
        return _compact(local.describe_config_key(path))

    @tool()
    def get_config_schema(
        key: Annotated[Optional[str], Field(description=(
            "Dotted key path, e.g. attention_checks or item_properties.id_key"
        ))] = None,
        full: Annotated[bool, Field(description=(
            "Return the whole schema. Ignored when key is given."
        ))] = False,
    ) -> str:
        if key:
            return _compact(local.get_config_schema(key))
        if full:
            return _compact(local.get_config_schema())
        return _compact(local.config_schema_overview())

    # -------------------------------------------------------------- examples --

    @tool()
    def list_examples(
        annotation_type: Annotated[Optional[str], Field(
            description="Only examples with a scheme of this type, e.g. likert")] = None,
        display_type: Annotated[Optional[str], Field(
            description="Only examples with an instance_display field of this type")] = None,
        category: Annotated[Optional[str], Field(description=(
            "The examples/ subdirectory: classification, span, image, audio, "
            "video, advanced, ..."
        ))] = None,
        config_key: Annotated[Optional[str], Field(
            description=("Only examples that set this key. A dotted key is "
                         "matched by its top-level part"))] = None,
        query: Annotated[Optional[str], Field(description=(
            "Substring, without case, of the directory, task name, "
            "description or annotation types"
        ))] = None,
        limit: Annotated[int, Field(description="Most results to return")] = 20,
    ) -> str:
        return _compact(local.list_examples(
            annotation_type=annotation_type,
            display_type=display_type,
            category=category,
            config_key=config_key,
            query=query,
            limit=limit,
        ))

    @tool()
    def get_example(
        name: Annotated[str, Field(description="The `name` from list_examples, e.g. classification/likert")],
    ) -> str:
        return _compact(local.get_example(name))

    # ------------------------------------------------------------ validation --

    @tool()
    def validate_config(
        path: Annotated[Optional[str], Field(
            description="Config path, relative to the server root")] = None,
        yaml_text: Annotated[Optional[str], Field(
            description="The config itself, instead of a path")] = None,
    ) -> str:
        if path:
            resolved = _resolve(root_dir, path)
            if resolved is None:
                return _compact(_outside(path))
            return _compact(local.validate_config(path=resolved))
        return _compact(local.validate_config(yaml_text=yaml_text))

    @tool()
    def preview_config(
        path: Annotated[str, Field(description="Config path, relative to the server root")],
    ) -> str:
        resolved = _resolve(root_dir, path)
        if resolved is None:
            return _compact(_outside(path))
        return _compact(local.preview_config(resolved))

    @tool(read_only=False)
    def render_task_screenshot(
        path: Annotated[str, Field(description="Config path, relative to the server root")],
        phase: Annotated[str, Field(description=(
            "The page to show: consent, instructions, training, annotation "
            "or poststudy"
        ))] = "annotation",
        width: Annotated[int, Field(description="Viewport width in pixels")] = 1280,
        height: Annotated[int, Field(description="Viewport height in pixels")] = 900,
    ) -> List[Any]:
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

    return TextContent(type="text", text=json.dumps(payload, separators=(",", ":")))

"""
Tests for the MCP server.

Two layers. `tools_local` is plain functions, so most of this is ordinary unit
testing: the shapes agents depend on, and the error paths, which matter more
here than usual because a tool that raises tells an agent nothing while a
returned message tells it what to fix.

The second layer drives the real server over stdio. That is slow and needs the
SDK, but it is the only thing that catches the failures that live in the
protocol boundary rather than in the functions -- both of the bugs found while
building this were of that kind: `capture_task` calling `asyncio.run()` inside
the server's own event loop, and the `Image` helper not being serializable.
Neither is visible from the Python side.
"""

import json
import os

import pytest

from potato.mcp_server import tools_local as local
from potato.mcp_server.server import _resolve, check_sdk_available

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXAMPLE = "examples/classification/single-choice/config.yaml"


class TestRegistryTools:
    def test_lists_every_registered_type(self):
        from potato.server_utils.schemas.registry import schema_registry

        listed = local.list_annotation_types()
        assert len(listed) == len(schema_registry.get_supported_types())
        assert all(t["name"] and "description" in t for t in listed)

    def test_describe_returns_a_worked_example(self):
        """The example is the reason this tool beats reading a field list."""
        described = local.describe_annotation_type("likert")
        assert described["example"], "no example for likert"
        assert described["example"]["annotation_type"] == "likert"
        assert described["example_source"].startswith("examples/")

    def test_describe_example_has_no_server_written_fields(self):
        """`annotation_id` and friends are set at render time, not in config."""
        for name in ("radio", "likert", "multiselect", "span"):
            example = local.describe_annotation_type(name)["example"]
            if not example:
                continue
            assert "annotation_id" not in example
            assert "_allocated_keys" not in example

    def test_unknown_type_returns_an_error_and_the_alternatives(self):
        result = local.describe_annotation_type("radioo")
        assert "error" in result
        assert "radio" in result["supported_types"]

    def test_display_types_are_listed_and_described(self):
        from potato.server_utils.displays import display_registry

        assert len(local.list_display_types()) == len(
            display_registry.get_supported_types()
        )
        described = local.describe_display_type("text")
        assert described["name"] == "text"
        assert "error" not in described

    def test_unknown_display_type_returns_an_error(self):
        assert "error" in local.describe_display_type("nope")


class TestConfigKeyTools:
    def test_list_returns_only_top_level_keys(self):
        assert all("." not in k["key"] for k in local.list_config_keys())

    def test_category_filter(self):
        core = local.list_config_keys(category="Core / Required")
        assert core
        assert all(k["category"] == "Core / Required" for k in core)

    def test_describe_a_nested_key(self):
        result = local.describe_config_key("attention_checks.frequency")
        assert result["recognized"] and result["documented"]
        assert result["type"] == "integer"

    def test_describe_a_container_lists_sub_keys(self):
        result = local.describe_config_key("item_properties")
        assert "id_key" in result["sub_keys"]

    def test_recognized_but_undocumented_says_so(self):
        """Not documented is different from not real, and an agent must not
        conclude the second from the first."""
        result = local.describe_config_key("annotation_schemes")
        assert result["recognized"] is True
        if not result.get("documented"):
            assert "note" in result

    def test_unknown_key_returns_an_error(self):
        assert "error" in local.describe_config_key("definitely.not.a.key")

    def test_schema_is_the_published_one(self):
        schema = local.get_config_schema()
        assert schema["$schema"].startswith("https://json-schema.org/")
        assert "annotation_schemes" in schema["properties"]


class TestExampleTools:
    def test_search_by_annotation_type(self):
        result = local.list_examples(annotation_type="bws")
        assert result["count"] >= 1
        assert all("bws" in e["annotation_types"] for e in result["examples"])

    def test_limit_is_honored(self):
        assert local.list_examples(limit=2)["count"] <= 2

    def test_get_example_by_directory(self):
        result = local.get_example("classification/check-box")
        assert "error" not in result
        assert result["config_text"], "no config text returned"
        assert "annotation_task_name" in result["config_text"]

    def test_get_example_accepts_the_examples_prefix(self):
        assert "error" not in local.get_example("examples/classification/check-box")

    def test_unknown_example_returns_an_error(self):
        assert "error" in local.get_example("no/such/example")


class TestValidateTool:
    def test_valid_config_passes(self):
        result = local.validate_config(path=os.path.join(REPO_ROOT, EXAMPLE))
        assert result["ok"], result["errors"]

    def test_invalid_type_is_reported_with_the_alternatives(self):
        """The agent has to be able to self-correct from this message alone."""
        result = local.validate_config(yaml_text=(
            "annotation_task_name: T\n"
            "task_dir: .\n"
            "output_annotation_dir: ./out\n"
            "data_files: [data/x.json]\n"
            "item_properties:\n"
            "  id_key: id\n"
            "  text_key: text\n"
            "annotation_schemes:\n"
            "  - annotation_type: radioo\n"
            "    name: q\n"
            "    description: d\n"
        ))
        assert not result["ok"]
        joined = " ".join(result["errors"])
        assert "radioo" in joined or "annotation_type" in joined
        assert "radio" in joined, "the error should name the valid alternatives"

    def test_neither_argument_is_an_error(self):
        assert "error" in local.validate_config()

    def test_missing_file_is_reported_not_raised(self):
        result = local.validate_config(path=os.path.join(REPO_ROOT, "nope.yaml"))
        assert not result["ok"]


class TestPreviewTool:
    def test_reports_schemes_and_keybindings(self):
        result = local.preview_config(os.path.join(REPO_ROOT, EXAMPLE))
        assert result["schema_count"] == 1
        assert result["schemas"][0]["type"] == "radio"
        assert "keybinding_conflicts" in result

    def test_missing_file_is_reported_not_raised(self):
        assert "error" in local.preview_config("/nonexistent/config.yaml")


class TestRootConfinement:
    """Paths come from the agent, so they are checked rather than trusted."""

    def test_path_inside_root_resolves(self, tmp_path):
        (tmp_path / "config.yaml").write_text("x: 1")
        assert _resolve(str(tmp_path), "config.yaml") is not None

    @pytest.mark.parametrize("path", [
        "../escape.yaml",
        "../../etc/passwd",
        "sub/../../outside.yaml",
    ])
    def test_traversal_is_refused(self, tmp_path, path):
        assert _resolve(str(tmp_path), path) is None

    def test_absolute_path_outside_root_is_refused(self, tmp_path):
        assert _resolve(str(tmp_path), "/etc/passwd") is None

    def test_symlink_out_of_root_is_refused(self, tmp_path):
        """realpath, not normpath: a symlink is the way around a textual check."""
        outside = tmp_path.parent / "outside_target"
        outside.mkdir(exist_ok=True)
        root = tmp_path / "root"
        root.mkdir()
        (root / "link").symlink_to(outside, target_is_directory=True)
        assert _resolve(str(root), "link/secret.yaml") is None


@pytest.mark.skipif(not check_sdk_available(), reason="mcp SDK not installed")
class TestServerConstruction:
    def test_builds(self, tmp_path):
        from potato.mcp_server.server import build_server

        assert build_server(root=str(tmp_path)) is not None

    def test_carries_instructions(self, tmp_path):
        """The instructions are how the agent learns the loop."""
        from potato.mcp_server.server import INSTRUCTIONS, build_server

        server = build_server(root=str(tmp_path))
        assert server.instructions == INSTRUCTIONS
        assert "validate_config" in INSTRUCTIONS
        assert "render_task_screenshot" in INSTRUCTIONS


@pytest.mark.skipif(not check_sdk_available(), reason="mcp SDK not installed")
class TestOverStdio:
    """Drive the real server the way a client does.

    Both bugs found while building this lived here and nowhere else: a nested
    `asyncio.run()`, and an image type FastMCP could not serialize. Calling the
    Python functions directly reported success for both.
    """

    @pytest.fixture(scope="class")
    def responses(self, tmp_path_factory):
        import asyncio
        import sys

        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        root = tmp_path_factory.mktemp("mcproot")
        (root / "data").mkdir()
        (root / "data" / "items.json").write_text(
            json.dumps([{"id": "1", "text": "first"}])
        )
        (root / "config.yaml").write_text(
            "annotation_task_name: MCP Probe\n"
            "task_dir: .\n"
            "output_annotation_dir: ./out\n"
            "data_files: [data/items.json]\n"
            "item_properties:\n"
            "  id_key: id\n"
            "  text_key: text\n"
            "annotation_schemes:\n"
            "  - annotation_type: radio\n"
            "    name: q1\n"
            "    description: pick\n"
            "    labels: [a, b]\n"
        )

        async def drive():
            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", "potato", "mcp", "serve", "--root", str(root)],
                cwd=REPO_ROOT,
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    init = await session.initialize()
                    tools = await session.list_tools()
                    resources = await session.list_resources()
                    prompts = await session.list_prompts()
                    described = await session.call_tool(
                        "describe_annotation_type", {"name": "bws"}
                    )
                    validated = await session.call_tool(
                        "validate_config", {"path": "config.yaml"}
                    )
                    escaped = await session.call_tool(
                        "validate_config", {"path": "../../../etc/passwd"}
                    )
                    return {
                        "init": init,
                        "tools": [t.name for t in tools.tools],
                        "resources": [str(r.uri) for r in resources.resources],
                        "prompts": [p.name for p in prompts.prompts],
                        "described": described,
                        "validated": validated,
                        "escaped": escaped,
                    }

        return asyncio.run(drive())

    def test_handshake(self, responses):
        assert responses["init"].serverInfo.name == "potato"
        assert responses["init"].instructions

    def test_all_tools_are_advertised(self, responses):
        for name in (
            "list_annotation_types", "describe_annotation_type",
            "list_display_types", "describe_display_type",
            "list_config_keys", "describe_config_key", "get_config_schema",
            "list_examples", "get_example",
            "validate_config", "preview_config", "render_task_screenshot",
        ):
            assert name in responses["tools"], f"{name} is not exposed"

    def test_resources_and_prompt(self, responses):
        assert "potato://config-schema" in responses["resources"]
        assert "potato://examples" in responses["resources"]
        assert "author_potato_task" in responses["prompts"]

    def test_tool_call_returns_usable_json(self, responses):
        payload = json.loads(responses["described"].content[0].text)
        assert payload["name"] == "bws"
        assert payload["example"]

    def test_validate_over_the_wire(self, responses):
        assert not responses["validated"].isError
        assert json.loads(responses["validated"].content[0].text)["ok"]

    def test_traversal_is_refused_over_the_wire(self, responses):
        payload = json.loads(responses["escaped"].content[0].text)
        assert "error" in payload
        assert "outside the server root" in payload["error"]


@pytest.mark.skipif(not check_sdk_available(), reason="mcp SDK not installed")
def test_screenshot_returns_an_image_block(tmp_path):
    """The whole reason this is MCP and not a document.

    Exercised over the wire because both of its failure modes were invisible
    from Python: the render ran inside the server's event loop, and the image
    had to survive serialization.
    """
    import asyncio
    import sys

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    from potato.preview_render import playwright_available

    if not playwright_available():
        pytest.skip("Playwright not installed")

    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "items.json").write_text(
        json.dumps([{"id": "1", "text": "first"}])
    )
    (tmp_path / "config.yaml").write_text(
        "annotation_task_name: Shot Probe\n"
        "task_dir: .\n"
        "output_annotation_dir: ./out\n"
        "data_files: [data/items.json]\n"
        "item_properties:\n"
        "  id_key: id\n"
        "  text_key: text\n"
        "annotation_schemes:\n"
        "  - annotation_type: radio\n"
        "    name: q1\n"
        "    description: pick\n"
        "    labels: [a, b]\n"
    )

    async def drive():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "potato", "mcp", "serve", "--root", str(tmp_path)],
            cwd=REPO_ROOT,
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await session.call_tool(
                    "render_task_screenshot", {"path": "config.yaml"}
                )

    result = asyncio.run(drive())
    assert not result.isError, result.content[0].text

    kinds = [block.type for block in result.content]
    assert "text" in kinds, "no diagnostics block"
    assert "image" in kinds, (
        "no image came back; the render or its serialization failed"
    )

    report = json.loads(
        next(b for b in result.content if b.type == "text").text
    )
    assert report["ok"], report["summary"]

    image = next(b for b in result.content if b.type == "image")
    assert image.mimeType == "image/png"

    import base64

    assert base64.b64decode(image.data)[:8] == b"\x89PNG\r\n\x1a\n"

"""
The live-instance tool registry: what an agent may do to a *running* task.

Every tool declares the permission it needs and whether it is destructive. That
table is the whole authorization model -- one place to read, one place to audit,
rather than scopes bolted onto 400-odd existing routes.

Nothing here is reachable unless an admin writes an `mcp:` block into the task
config naming the tools by hand. There is no default-on set, and a destructive
tool needs a second, separate opt-in on top of the first.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from potato.server_utils.rbac import Permission


@dataclass(frozen=True)
class LiveParam:
    """One argument a live tool takes.

    These exist so `potato mcp connect` can publish a real inputSchema. Without
    them every forwarded tool advertised a single opaque `arguments` object, so
    a connected agent was told the tool existed and nothing else -- not the
    argument names, not which were required, not even that top-level arguments
    would be silently dropped. Discovery is the whole point of the surface.

    `type` is a JSON Schema type name; it is also what decides the Python
    annotation the forwarder's signature is built with.
    """

    name: str
    type: str = "string"
    required: bool = False
    description: str = ""
    default: Optional[object] = None

    def to_dict(self) -> dict:
        out = {"name": self.name, "type": self.type,
               "required": self.required, "description": self.description}
        if self.default is not None:
            out["default"] = self.default
        return out


@dataclass(frozen=True)
class LiveTool:
    """One thing an agent can do to a running task.

    Attributes:
        name: What the admin writes in `mcp.tools`.
        summary: One line, shown to the agent.
        permission: RBAC permission the caller's token must carry.
        destructive: Loses or overwrites work. Needs `mcp.destructive` as well,
            and `confirm: true` at call time.
        handler: Name of the function in `live_handlers` that implements it.
        parameters: What the tool's JSON payload accepts, published to clients.
    """

    name: str
    summary: str
    permission: str
    destructive: bool = False
    handler: str = ""
    parameters: Tuple[LiveParam, ...] = ()


_TOOLS: List[LiveTool] = [
    # ---- read -------------------------------------------------------------
    LiveTool("get_status", "Server health, task name and item counts",
             Permission.VIEW_ADMIN_DASHBOARD, handler="get_status"),
    LiveTool("get_progress", "Overall annotation progress",
             Permission.VIEW_ADMIN_DASHBOARD, handler="get_progress"),
    LiveTool("list_annotators", "Annotators and how much each has done",
             Permission.VIEW_ADMIN_DASHBOARD, handler="list_annotators"),
    LiveTool("list_items", "Items, with per-item annotation counts",
             Permission.VIEW_ADMIN_DASHBOARD, handler="list_items",
             parameters=(
                 LiveParam("limit", "integer", False,
                           "How many items to return", 50),
                 LiveParam("offset", "integer", False,
                           "Index of the first item to return", 0),
             )),
    LiveTool("get_item", "One item's data and its annotations",
             Permission.VIEW_ADMIN_DASHBOARD, handler="get_item",
             parameters=(
                 LiveParam("instance_id", "string", True,
                           "The item's id, as it appears in the data file"),
             )),
    LiveTool("get_agreement", "Inter-annotator agreement",
             Permission.VIEW_ADMIN_DASHBOARD, handler="get_agreement"),
    LiveTool("get_config", "The task's current configuration",
             Permission.VIEW_ADMIN_DASHBOARD, handler="get_config"),

    # ---- write ------------------------------------------------------------
    LiveTool("add_items", "Add new items to the task",
             Permission.MANAGE_ASSIGNMENT, handler="add_items",
             parameters=(
                 LiveParam("items", "array", True,
                           "Item objects, each carrying the task's id_key"),
             )),
    LiveTool("submit_annotation", "Record an annotation as a given user",
             Permission.ANNOTATE, handler="submit_annotation",
             parameters=(
                 LiveParam("username", "string", True,
                           "The annotator to record the work as"),
                 LiveParam("instance_id", "string", True, "The item's id"),
                 LiveParam("annotations", "object", True,
                           "{schema: {label: value}}, or {schema: value} for a "
                           "single-field scheme"),
                 LiveParam("span_annotations", "array", False,
                           "Span objects: schema, name, start, end, and "
                           "optionally title, value, target_field"),
                 LiveParam("behavioral_data", "object", False,
                           "Interaction telemetry to store with the answer"),
             )),
    LiveTool("assign_items", "Set how many items an annotator may receive",
             Permission.MANAGE_ASSIGNMENT, handler="assign_items",
             parameters=(
                 LiveParam("username", "string", True, "The annotator"),
                 LiveParam("max_instances", "integer", True,
                           "New per-user assignment cap"),
             )),
    LiveTool("export_data", "Export annotations in a registered format",
             Permission.EXPORT_DATA, handler="export_data",
             parameters=(
                 LiveParam("format", "string", True,
                           "A registered exporter name, e.g. jsonl or csv"),
                 LiveParam("output", "string", False,
                           "Directory to write into, on the SERVER's disk"),
                 LiveParam("options", "object", False,
                           "Exporter-specific options"),
             )),

    # ---- destructive ------------------------------------------------------
    # Potato has no supported way to delete an annotator, so there is no
    # reset_user tool. Clearing their annotations item by item is the closest
    # operation the server actually implements.
    LiveTool("delete_annotations", "Clear a user's annotations for one item",
             Permission.MANAGE_ASSIGNMENT, destructive=True,
             handler="delete_annotations",
             parameters=(
                 LiveParam("username", "string", True, "The annotator"),
                 LiveParam("instance_id", "string", True, "The item's id"),
                 LiveParam("confirm", "boolean", True,
                           "Must be true. This destroys annotation work."),
             )),
]

TOOLS: Dict[str, LiveTool] = {tool.name: tool for tool in _TOOLS}

TOOL_NAMES = sorted(TOOLS)
DESTRUCTIVE_TOOL_NAMES = sorted(t.name for t in _TOOLS if t.destructive)
READ_ONLY_TOOL_NAMES = sorted(
    t.name for t in _TOOLS
    if not t.destructive and t.permission == Permission.VIEW_ADMIN_DASHBOARD
)


def get_tool(name: str) -> Optional[LiveTool]:
    return TOOLS.get(name)


def describe_tools(enabled: Optional[List[str]] = None) -> List[dict]:
    """The tool table, optionally narrowed to what a task has switched on."""
    names = sorted(enabled) if enabled is not None else TOOL_NAMES
    return [
        {
            "name": tool.name,
            "summary": tool.summary,
            "permission": tool.permission,
            "destructive": tool.destructive,
            "parameters": [p.to_dict() for p in tool.parameters],
        }
        for tool in (TOOLS[n] for n in names if n in TOOLS)
    ]

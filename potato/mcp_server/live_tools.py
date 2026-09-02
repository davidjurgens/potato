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
from typing import Dict, List, Optional

from potato.server_utils.rbac import Permission


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
    """

    name: str
    summary: str
    permission: str
    destructive: bool = False
    handler: str = ""


_TOOLS: List[LiveTool] = [
    # ---- read -------------------------------------------------------------
    LiveTool("get_status", "Server health, task name and item counts",
             Permission.VIEW_ADMIN_DASHBOARD, handler="get_status"),
    LiveTool("get_progress", "Overall annotation progress",
             Permission.VIEW_ADMIN_DASHBOARD, handler="get_progress"),
    LiveTool("list_annotators", "Annotators and how much each has done",
             Permission.VIEW_ADMIN_DASHBOARD, handler="list_annotators"),
    LiveTool("list_items", "Items, with per-item annotation counts",
             Permission.VIEW_ADMIN_DASHBOARD, handler="list_items"),
    LiveTool("get_item", "One item's data and its annotations",
             Permission.VIEW_ADMIN_DASHBOARD, handler="get_item"),
    LiveTool("get_agreement", "Inter-annotator agreement",
             Permission.VIEW_ADMIN_DASHBOARD, handler="get_agreement"),
    LiveTool("get_config", "The task's current configuration",
             Permission.VIEW_ADMIN_DASHBOARD, handler="get_config"),

    # ---- write ------------------------------------------------------------
    LiveTool("add_items", "Add new items to the task",
             Permission.MANAGE_ASSIGNMENT, handler="add_items"),
    LiveTool("submit_annotation", "Record an annotation as a given user",
             Permission.ANNOTATE, handler="submit_annotation"),
    LiveTool("assign_items", "Set how many items an annotator may receive",
             Permission.MANAGE_ASSIGNMENT, handler="assign_items"),
    LiveTool("export_data", "Export annotations in a registered format",
             Permission.EXPORT_DATA, handler="export_data"),

    # ---- destructive ------------------------------------------------------
    # Potato has no supported way to delete an annotator, so there is no
    # reset_user tool. Clearing their annotations item by item is the closest
    # operation the server actually implements.
    LiveTool("delete_annotations", "Clear a user's annotations for one item",
             Permission.MANAGE_ASSIGNMENT, destructive=True,
             handler="delete_annotations"),
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
        }
        for tool in (TOOLS[n] for n in names if n in TOOLS)
    ]

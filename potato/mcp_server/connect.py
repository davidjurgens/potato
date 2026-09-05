"""
`potato mcp connect` — an MCP server fronting a *remote* Potato instance.

The live surface at `/api/mcp/*` is plain HTTP JSON, and MCP clients speak stdio.
This bridges the two: it advertises whatever the remote instance says the token
is allowed to do, and forwards each call.

It holds no policy. The tool list comes from the remote manifest, and every
refusal is the remote server's -- an agent pointed at a task whose admin granted
nothing gets a server with no tools, which is the correct answer rather than a
client-side approximation of one.

Local tools come along too, so one connection covers both authoring a config and
watching the task it produced.

Usage:
    potato mcp connect --url https://my-task.example --token $POTATO_AGENT_TOKEN
"""

from __future__ import annotations

import json
import logging
import inspect
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30


class RemoteError(Exception):
    """The remote instance refused or could not answer."""


class PotatoClient:
    """Minimal HTTP client for a remote instance's MCP surface.

    Deliberately urllib rather than requests: this is three calls, and keeping
    the dependency list of `potato mcp` down to the SDK matters more than
    ergonomics here.
    """

    def __init__(self, base_url: str, token: str, timeout: int = DEFAULT_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _request(self, path: str, payload: Optional[dict] = None) -> Any:
        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            url,
            data=data,
            method="POST" if data is not None else "GET",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            # The refusal body is the useful part -- it says which check failed
            # and often what would satisfy it, so pass it through rather than
            # replacing it with a status code.
            try:
                return json.loads(e.read().decode("utf-8"))
            except Exception:
                raise RemoteError(f"HTTP {e.code} from {url}") from e
        except urllib.error.URLError as e:
            raise RemoteError(f"Could not reach {url}: {e.reason}") from e

    def manifest(self) -> dict:
        return self._request("/api/mcp/manifest")

    def call(self, tool: str, payload: Optional[dict] = None) -> Any:
        return self._request(f"/api/mcp/tools/{tool}", payload or {})


def build_connected_server(url: str, token: str, root: Optional[str] = None):
    """An MCP server exposing the remote instance's tools plus the local ones."""
    import os

    from potato.mcp_server.server import build_server

    client = PotatoClient(url, token)
    manifest = client.manifest()

    if "error" in manifest:
        raise RemoteError(
            f"{url} refused the token: {manifest['error']}\n"
            "Issue one with: potato mcp issue-token --config config.yaml "
            "--name <agent> --role <role>"
        )

    remote_tools = manifest.get("tools", [])
    task_name = manifest.get("task") or url

    # Start from the local server so authoring tools stay available, then add a
    # forwarder per granted remote tool.
    mcp_server = build_server(root=root or os.getcwd())

    for entry in remote_tools:
        _register_forwarder(mcp_server, client, entry)

    logger.info(
        "Connected to %s as %s (%s); %d remote tool(s) granted",
        task_name, manifest.get("agent"), manifest.get("role"), len(remote_tools),
    )
    return mcp_server, manifest


#: JSON Schema type name -> the Python annotation FastMCP builds a schema from.
_PARAM_TYPES = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "object": Dict[str, Any],
    "array": List[Any],
}


def _forwarder_signature(parameters: List[dict]):
    """An `inspect.Signature` matching what the remote tool documents.

    FastMCP derives a tool's inputSchema from the callable's signature, so a
    forwarder written as `f(arguments=None)` publishes exactly one property
    called `arguments` -- which is what every live tool used to advertise. An
    agent reading that list learned the tool's name and nothing else, and
    passing the obvious thing (`{"instance_id": "W01"}`) was silently dropped
    in favour of the wrapper the schema never mentioned.

    Required parameters come first: a signature cannot put a parameter without
    a default after one with a default.
    """
    ordered = ([p for p in parameters if p.get("required")] +
               [p for p in parameters if not p.get("required")])
    params, annotations = [], {}
    for spec in ordered:
        pname = spec.get("name")
        if not pname:
            continue
        annotation = _PARAM_TYPES.get(spec.get("type", "string"), Any)
        if spec.get("required"):
            default = inspect.Parameter.empty
        else:
            annotation = Optional[annotation]
            default = spec.get("default", None)
        params.append(inspect.Parameter(
            pname, inspect.Parameter.KEYWORD_ONLY,
            default=default, annotation=annotation))
        annotations[pname] = annotation
    return inspect.Signature(params), annotations


def _register_forwarder(mcp_server, client: PotatoClient, entry: dict) -> None:
    """Add one remote tool, named `live_<tool>` to keep it distinct."""
    name = entry["name"]
    summary = entry.get("summary", "")
    destructive = entry.get("destructive", False)
    # `[]` means "this tool takes nothing" and `None` means "this instance is
    # too old to say" -- two different answers that must not collapse.
    parameters = entry.get("parameters")
    publishes_schema = parameters is not None
    parameters = parameters or []

    description = summary
    if parameters:
        described = ", ".join(
            f"{p['name']} ({p.get('type', 'string')}"
            f"{', required' if p.get('required') else ''})"
            for p in parameters if p.get("name")
        )
        description += f". Arguments: {described}"
    if destructive:
        description += (
            ". Destroys annotation work: the call must include "
            '"confirm": true, and the task admin must have listed this tool in '
            "mcp.destructive."
        )

    if publishes_schema:
        signature, annotations = _forwarder_signature(parameters)

        def forwarder(**kwargs: Any) -> Any:
            """Forward to the remote instance."""
            # Drop the omitted optionals rather than sending explicit nulls:
            # the remote reads `payload.get(k)`, and a null would override a
            # server-side default with None.
            payload = {k: v for k, v in kwargs.items() if v is not None}
            try:
                return client.call(name, payload)
            except RemoteError as e:
                return {"error": str(e)}

        forwarder.__signature__ = signature
        forwarder.__annotations__ = dict(annotations, **{"return": Any})
    else:
        # An older instance publishes no parameter list. Keep the wrapper form
        # so `connect` still works against it, and say so in the description
        # rather than leaving the agent to discover it from an error string.
        description += (
            ". This instance does not publish an argument schema; pass "
            'arguments as a nested object, e.g. {"arguments": {...}}.'
        )

        def forwarder(arguments: Optional[Dict[str, Any]] = None) -> Any:
            """Forward to the remote instance."""
            try:
                return client.call(name, arguments or {})
            except RemoteError as e:
                return {"error": str(e)}

    forwarder.__name__ = f"live_{name}"
    forwarder.__doc__ = description or f"Call {name} on the connected instance."

    mcp_server.add_tool(
        forwarder, name=f"live_{name}", description=forwarder.__doc__
    )


def summarize(manifest: dict) -> str:
    """A human-readable line about what the connection allows."""
    tools = manifest.get("tools", [])
    destructive = manifest.get("destructive_enabled", [])
    lines = [
        f"Connected to {manifest.get('task', 'the instance')} "
        f"as {manifest.get('agent')} ({manifest.get('role')}).",
        f"{len(tools)} remote tool(s) granted:",
    ]
    for tool in tools:
        mark = " [destructive]" if tool.get("destructive") else ""
        lines.append(f"  live_{tool['name']}{mark} — {tool.get('summary', '')}")
    if destructive:
        lines.append(
            f"Destructive tools enabled: {', '.join(destructive)}. "
            f"These need \"confirm\": true on every call."
        )
    scope = manifest.get("scope") or {}
    if scope.get("users"):
        lines.append(f"Limited to annotators: {', '.join(scope['users'])}")
    return "\n".join(lines)

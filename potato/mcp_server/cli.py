"""
`potato mcp` — run Potato's MCP server.

    potato mcp serve                 # stdio, rooted at the current directory
    potato mcp serve --root ./myproj
    potato mcp connect --url URL     # add a running instance's tools
    potato mcp tools                 # list the tools, no SDK needed
    potato mcp config                # emit a client config block to paste

`serve` speaks stdio, which is what Claude Code, Codex and Cursor connect over.
It writes nothing to stdout except protocol traffic -- logging goes to stderr,
because a stray print corrupts the stream and the failure looks like the server
never started.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import List, Optional


def _configure_logging(verbose: bool) -> None:
    """Send all logging to stderr. stdout belongs to the protocol."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        stream=sys.stderr,
        format="%(levelname)s %(name)s: %(message)s",
    )


def cmd_serve(args) -> int:
    from potato.mcp_server.server import INSTALL_HINT, build_server, check_sdk_available

    if not check_sdk_available():
        print(INSTALL_HINT, file=sys.stderr)
        return 1

    root = os.path.realpath(args.root)
    if not os.path.isdir(root):
        print(f"--root is not a directory: {root}", file=sys.stderr)
        return 1

    _configure_logging(args.verbose)
    print(f"Potato MCP server starting, rooted at {root}", file=sys.stderr)

    server = build_server(root=root)
    server.run(transport="stdio")
    return 0


def cmd_tools(args) -> int:
    """List the tools without importing the SDK.

    Useful for checking what is on offer before wiring up a client, and for
    confirming an install is sane when `serve` will not start.
    """
    from potato.mcp_server import tools_local as local

    tools = [
        ("list_annotation_types", "Every annotation type, with descriptions"),
        ("describe_annotation_type", "Fields and a working example for one type"),
        ("list_display_types", "Every instance_display field type"),
        ("describe_display_type", "Fields for one display type"),
        ("list_config_keys", "Documented top-level config keys"),
        ("describe_config_key", "One config key by dotted path"),
        ("get_config_schema", "The full config JSON Schema"),
        ("list_examples", "Search the shipped example projects"),
        ("get_example", "Read one example's config"),
        ("validate_config", "Validate a config with the server's own validator"),
        ("preview_config", "Schemes, labels and keybindings a config declares"),
        ("render_task_screenshot", "Boot the task, screenshot it, report browser errors"),
    ]

    if args.json:
        print(json.dumps([{"name": n, "description": d} for n, d in tools], indent=2))
        return 0

    print("Potato MCP tools:\n")
    for name, description in tools:
        print(f"  {name:26} {description}")
    print(f"\nRegistries behind them: {len(local.list_annotation_types())} annotation "
          f"types, {len(local.list_display_types())} display types, "
          f"{len(local.list_config_keys())} documented config keys.")
    return 0


def cmd_config(args) -> int:
    """Print a client config block for this machine."""
    root = os.path.realpath(args.root)
    block = {
        "mcpServers": {
            "potato": {
                "command": sys.executable,
                "args": ["-m", "potato", "mcp", "serve", "--root", root],
            }
        }
    }
    print(json.dumps(block, indent=2))
    print(
        "\nClaude Code: save as .mcp.json in your project, or run\n"
        f"  claude mcp add potato -- {sys.executable} -m potato mcp serve --root {root}",
        file=sys.stderr,
    )
    return 0


def cmd_connect(args) -> int:
    """Serve a remote instance's MCP surface over stdio."""
    from potato.mcp_server.connect import RemoteError, build_connected_server, summarize
    from potato.mcp_server.server import INSTALL_HINT, check_sdk_available

    if not check_sdk_available():
        print(INSTALL_HINT, file=sys.stderr)
        return 1

    token = args.token or os.environ.get("POTATO_AGENT_TOKEN")
    if not token:
        print(
            "An agent token is required. Pass --token, or set "
            "POTATO_AGENT_TOKEN.\nIssue one on the server with:\n"
            "  potato mcp issue-token --config config.yaml --name <agent> "
            "--role <role>",
            file=sys.stderr,
        )
        return 1

    _configure_logging(args.verbose)

    try:
        server, manifest = build_connected_server(args.url, token, root=args.root)
    except RemoteError as e:
        print(str(e), file=sys.stderr)
        return 1

    print(summarize(manifest), file=sys.stderr)
    server.run(transport="stdio")
    return 0


def _load_task_config(config_file: str) -> dict:
    import yaml

    with open(config_file, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    # Tokens live under task_dir, which is relative to the config.
    task_dir = config.get("task_dir") or "."
    if not os.path.isabs(task_dir):
        config["task_dir"] = os.path.normpath(
            os.path.join(os.path.dirname(os.path.abspath(config_file)), task_dir)
        )
    return config


def cmd_issue_token(args) -> int:
    """Mint an agent token for a task."""
    from potato.server_utils.agent_tokens import issue_token, token_file_path

    if not os.path.isfile(args.config):
        print(f"Config file not found: {args.config}", file=sys.stderr)
        return 1

    config = _load_task_config(args.config)
    try:
        token = issue_token(args.name, role=args.role, note=args.note, config=config)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1

    print(token)
    print(
        f"\nIssued to {args.name!r} with the {args.role!r} role.\n"
        f"Recorded in {token_file_path(config)} as a hash -- this is the only "
        f"time the token itself is shown.\n\n"
        f"Use it as:  Authorization: Bearer {token[:8]}...",
        file=sys.stderr,
    )
    return 0


def cmd_list_tokens(args) -> int:
    from potato.server_utils.agent_tokens import list_tokens

    config = _load_task_config(args.config)
    records = list_tokens(config)
    if args.json:
        print(json.dumps(records, indent=2))
        return 0

    if not records:
        print("No agent tokens issued for this task.")
        return 0
    print(f"{'NAME':24} {'ROLE':14} {'CREATED':22} STATUS")
    for record in records:
        status = "revoked" if record["revoked"] else "active"
        print(f"{record['name']:24} {record['role']:14} {record['created']:22} {status}")
    return 0


def cmd_revoke_token(args) -> int:
    from potato.server_utils.agent_tokens import revoke_token

    config = _load_task_config(args.config)
    count = revoke_token(args.name, config)
    print(f"Revoked {count} token(s) issued to {args.name!r}.")
    return 0 if count else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="potato mcp",
        description="Run Potato's MCP server for coding agents.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Run the MCP server over stdio")
    serve.add_argument(
        "--root",
        default=".",
        help="Directory the server may read and write (default: cwd)",
    )
    serve.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    serve.set_defaults(func=cmd_serve)

    tools = sub.add_parser("tools", help="List the tools this server exposes")
    tools.add_argument("--json", action="store_true", help="Emit JSON")
    tools.set_defaults(func=cmd_tools)

    config = sub.add_parser("config", help="Print a client config block")
    config.add_argument("--root", default=".", help="Project directory")
    config.set_defaults(func=cmd_config)

    connect = sub.add_parser(
        "connect",
        help="Serve a running instance's MCP surface over stdio",
    )
    connect.add_argument("--url", required=True, help="Base URL of the instance")
    connect.add_argument(
        "--token",
        help="Agent token (falls back to $POTATO_AGENT_TOKEN)",
    )
    connect.add_argument(
        "--root", default=".",
        help="Local directory for the authoring tools (default: cwd)",
    )
    connect.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    connect.set_defaults(func=cmd_connect)

    issue = sub.add_parser(
        "issue-token", help="Mint an agent token for a live task's MCP surface"
    )
    issue.add_argument("--config", required=True, help="Task config.yaml")
    issue.add_argument("--name", required=True, help="Who the token is for")
    issue.add_argument(
        "--role", default="annotator",
        choices=["admin", "adjudicator", "annotator"],
        help="Role the token carries (default: annotator)",
    )
    issue.add_argument("--note", default="", help="Free-text note")
    issue.set_defaults(func=cmd_issue_token)

    tokens = sub.add_parser("tokens", help="List agent tokens for a task")
    tokens.add_argument("--config", required=True, help="Task config.yaml")
    tokens.add_argument("--json", action="store_true", help="Emit JSON")
    tokens.set_defaults(func=cmd_list_tokens)

    revoke = sub.add_parser("revoke-token", help="Revoke an agent's tokens")
    revoke.add_argument("--config", required=True, help="Task config.yaml")
    revoke.add_argument("--name", required=True, help="Whose tokens to revoke")
    revoke.set_defaults(func=cmd_revoke_token)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

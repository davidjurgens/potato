# MCP Server

Potato ships a [Model Context Protocol](https://modelcontextprotocol.io) server
so coding agents (Claude Code, Codex, Cursor) can build annotation tasks without
a human relaying error messages back and forth.

The agent asks what annotation types exist, reads a working example of the one it
wants, writes a config, validates it with the same validator the server uses, and
then looks at the rendered page. If the page throws, the agent gets the exception
and fixes it.

## Install

```bash
pip install 'potato-annotation[agent]'
playwright install chromium
```

The `agent` extra is the MCP SDK plus the headless browser used for rendering.
`[mcp]` alone gives you everything except `render_task_screenshot`.

## Connect an agent

```bash
potato mcp config --root .
```

That prints a config block for the current directory. For Claude Code:

```bash
claude mcp add potato -- python -m potato mcp serve --root .
```

Or save the printed block as `.mcp.json` in your project. Cursor and Codex read
the same shape from their own config files.

`--root` is the only directory the server will read or write. Paths outside it
are refused. So are symlinks that point out of it, since paths are resolved
before they are checked.

## Tools

| Tool | What it answers |
|------|-----------------|
| `list_annotation_types` | What can this thing do? |
| `describe_annotation_type` | What fields does `bws` take, and what does a real one look like? |
| `list_display_types` | How can an item be displayed? |
| `describe_display_type` | What keys does an `image` field take? |
| `list_config_keys` | What top-level keys exist? |
| `describe_config_key` | What is `attention_checks.frequency`? |
| `get_config_schema` | The whole contract, as JSON Schema |
| `list_examples` | Is there an example that already does most of this? |
| `get_example` | Show me its config |
| `validate_config` | Is this config correct? |
| `preview_config` | What form does it declare? |
| `render_task_screenshot` | What does it actually look like, and did anything break? |

**`validate_config`** runs `validate_yaml_structure()` — the same code
`potato start` runs at boot. An agent that satisfies it has satisfied the server,
so it can correct itself instead of guessing. Errors name the alternatives: an
unknown `annotation_type` comes back with the list of valid ones.

**`render_task_screenshot`** boots the task on a spare port, opens it in a
headless browser, and returns a picture of the annotation page along with every
uncaught exception, `console.error` and failed request. A config can validate
cleanly and still render a broken interface. Most of the annotation UI is built
by JavaScript after the HTML arrives, so nothing server-side sees those failures.

## Examples over field lists

`describe_annotation_type` returns an `example`: a scheme lifted from a config in
`examples/` that uses that type. CI already checks those configs run and really
use the type they claim, so the example is known to work. 60 of the 61 registered
types have one.

```json
{
  "name": "likert",
  "example": {
    "annotation_type": "likert",
    "name": "awesomeness",
    "description": "How awesome is this?",
    "min_label": "Not Awesome",
    "max_label": "Completely Awesome",
    "size": 5
  },
  "example_source": "examples/classification/likert/config.yaml"
}
```

## Resources and prompt

Four resources are exposed for clients that read them directly:
`potato://config-schema`, `potato://annotation-types`, `potato://examples`,
`potato://guide`.

One prompt, `author_potato_task`, takes a plain-English description and returns
the authoring loop with it filled in.

## Checking the install

```bash
potato mcp tools
```

Lists the tools and the registry counts behind them, without starting a server or
needing the SDK. If this works and `serve` does not, the problem is the SDK
install rather than Potato.

## Controlling a running task

Everything above is local: it reads configs and registries on your machine and
touches no running server. A separate, opt-in surface lets an agent query and
control a live task.

It is off unless an admin writes an `mcp:` block naming every tool by hand. There
is no default-on set.

```yaml
mcp:
  enabled: true
  tools:
    - get_status
    - get_progress
    - list_items
    - get_item
  destructive: []           # second, separate opt-in for tools that discard work
  scope:
    users: [agent-annotator]
  audit_log: mcp_audit.jsonl
```

Then issue a token per agent:

```bash
potato mcp issue-token --config config.yaml --name ops-agent --role admin
potato mcp tokens --config config.yaml
potato mcp revoke-token --config config.yaml --name ops-agent
```

The token is shown once. Only its SHA-256 digest is stored, in
`{task_dir}/mcp_tokens.json`. Agents send it as `Authorization: Bearer <token>`.

### Available tools

| Tool | Permission | Destructive |
|------|------------|-------------|
| `get_status` | view_admin_dashboard | |
| `get_progress` | view_admin_dashboard | |
| `list_annotators` | view_admin_dashboard | |
| `list_items` | view_admin_dashboard | |
| `get_item` | view_admin_dashboard | |
| `get_agreement` | view_admin_dashboard | |
| `get_config` | view_admin_dashboard | |
| `add_items` | manage_assignment | |
| `assign_items` | manage_assignment | |
| `submit_annotation` | annotate | |
| `export_data` | export_data | |
| `delete_annotations` | manage_assignment | yes |

### The six checks a call must pass

In order, each failing closed with a reason the agent can act on:

1. `mcp.enabled` — otherwise the endpoints do not exist
2. A valid, unrevoked agent token
3. The tool appears in `mcp.tools`
4. If destructive, it also appears in `mcp.destructive`
5. If destructive, the call passes `"confirm": true`
6. The token's role carries the tool's permission

`mcp.scope.users` narrows which annotators an agent may act on. Every attempt,
allowed or refused, is appended to the audit log.

### Debug mode

`debug: true` disables admin authentication across the whole server, so the two
together would be remote control with no lock on it. Potato refuses the
combination twice: config validation fails at startup, and the blueprint declines
to register even if validation is bypassed. Setting `mcp.allow_debug: true` states
that you mean it — and even then the token check still applies.

`potato deploy check` reports on all of this before you ship.

### Connecting an agent to it

The live surface speaks HTTP; MCP clients speak stdio. `potato mcp connect`
bridges them, adding the remote tools alongside the local authoring ones:

```bash
export POTATO_AGENT_TOKEN=...
potato mcp connect --url https://my-task.example
```

Remote tools arrive prefixed `live_`, and only the ones the token is actually
granted appear — the list comes from the server's manifest, not from a guess made
locally. Refusals come back with the server's own message, so an agent told
`'delete_annotations' destroys work. Pass "confirm": true to proceed.` can act on
it.

## Notes

The server writes protocol traffic to stdout and everything else to stderr. A
stray `print()` in a tool would corrupt the stream, and the failure looks like the
server never started.

## Related

- [Preview CLI](preview_cli.md) — the same validation and rendering from a shell
- [Machine-Readable Specs](../api-reference/machine_readable.md) — the JSON Schema,
  OpenAPI spec and examples catalog the tools are built on
- [Configuration Reference](../configuration/config_reference.md) — every config key

# Agent Instructions

Claude Code, Codex and Cursor can build a Potato task from a description, and
they do it far better with instructions than without. The instructions are a
separate project:

**[github.com/davidjurgens/potato-skill](https://github.com/davidjurgens/potato-skill)**

They live outside this repository because most people installing Potato are not
using a coding agent, and there is no reason to ship them a skill they will
never load.

## Installing it

In Claude Code:

```
/plugin marketplace add davidjurgens/potato-skill
/plugin install potato-tasks@potato
```

Codex and Cursor read `AGENTS.md`, which is at the root of that repository. Copy
it into the project you are working in.

## The references

The skill loads reference material on demand rather than all at once: designing
a task before any YAML is written, laying out the interface, phases and pages,
attention checks and gold standards, assignment and agreement, importing
existing annotations, getting the data back out, deploying, and the symptoms of
a task that validates clean and then does something else.

Three of its references are generated from Potato's own registries, so the
annotation types, display types and config keys an agent reads are the ones this
server enforces.

All of it is published at
**[davidjurgens.github.io/potato-skill](https://davidjurgens.github.io/potato-skill/)**,
which is worth reading directly whether or not you use an agent.

## Related

- [MCP Server](mcp_server.md) — the protocol server an agent connects to for
  live queries against a running task
- [Preview CLI](preview_cli.md) — rendering a config without booting a server
- [Machine-Readable Specs](../api-reference/machine_readable.md) — the JSON
  Schema, OpenAPI spec and `llms.txt` an agent reads first

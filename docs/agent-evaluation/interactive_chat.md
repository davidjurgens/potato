# Interactive Agent Chat

An annotator talks to an agent, clicks **Finish & Annotate**, and then rates
the conversation they just had. Two pieces of config do this:

- an `agent_proxy` block, which connects Potato to the agent backend;
- an `instance_display` field of `type: interactive_chat`, which puts the chat
  panel on the page.

With only the proxy and no `interactive_chat` field, the server starts and
loads the chat scripts, but the annotator has no panel to type in.

## Example

From `examples/agent-testing/interactive-agent-test/`:

```yaml
agent_proxy:
  type: echo                 # echo, http, openai, subprocess_coding, docker_coding
  responses:
    - "I understand your request. Let me look into that for you."
    - "Here's what I recommend based on my research."
  sandbox:
    max_steps: 20
    max_session_seconds: 600
    request_timeout_seconds: 60
    rate_limit_per_minute: 10

instance_display:
  fields:
    - key: task_description
      type: text
      label: "Task Description"
    - key: conversation
      type: interactive_chat
      label: "Agent Interaction"
      display_options:
        show_turn_numbers: true
        per_turn_ratings:
          speakers: ["Agent"]
          schemes:
            - schema_name: turn_helpfulness
              scheme:
                type: likert
                size: 3
                labels: ["Unhelpful", "Helpful"]

annotation_schemes:
  - annotation_type: radio
    name: task_success
    description: "Did the agent successfully complete the task?"
    labels: [success, partial, failure]
```

The data file gives each item a task and an empty conversation:

```json
{"id": "task_1", "task_description": "Book a round-trip flight from New York to London.", "conversation": null}
```

Run it:

```bash
python potato/flask_server.py start examples/agent-testing/interactive-agent-test/config.yaml -p 8000
```

## From chat to annotation

1. While the field's value is empty, the field shows a chat panel with
   **Send** and **Finish & Annotate** buttons. The agent's session starts with
   the item's `task_description` field as the task, or its `text` field when
   there is no `task_description`.
2. Each message goes to the proxy, within the `sandbox` limits listed below.
3. **Finish & Annotate** stores the conversation for this annotator and this
   item, as `speaker`/`text`/`timestamp` turns with the speakers `User` and
   `Agent` (`System (Error)` for a failed call), and reloads the page.
4. The field then renders the conversation like a `dialogue` field, with any
   per-turn ratings, and the annotator fills in the annotation schemes.

### Storage and export

When an annotator clicks **Finish & Annotate**, Potato stores the conversation
for that annotator and that item in the project database
(`<task_dir>/project.sqlite`, table `agent_chat_transcripts`). The page then
shows that annotator their own conversation in place of the chat panel. Every
other annotator assigned the same item still gets an empty chat panel and has
a conversation of their own. A finished chat cannot be reopened, and its
stored conversation survives a server restart. A chat that is never finished
is not stored.

Exports include the conversation:

- `jsonl`: the annotator's record for the item carries an `agent_chat` object
  with `field`, `proxy_type`, `step_count`, `started_at`, `finished_at` and
  `conversation` (a list of `{speaker, text, timestamp}` turns). Records exist
  only for items the annotator labeled.
- `csv` and `tsv`: a sidecar file, `agent_chat_turns.csv` or
  `agent_chat_turns.tsv`, has one row per turn with the columns `user_id`,
  `instance_id`, `field`, `turn_index`, `speaker`, `text`, `timestamp`,
  `proxy_type`, `step_count`, `started_at`, `finished_at`. It also covers
  chats on items the annotator did not label.

Adjudicators see the item without any annotator's conversation.

## `interactive_chat` field options

Set these under the field's `display_options`.

| Option | Default | Description |
|--------|---------|-------------|
| `placeholder_text` | `Start chatting with the agent to begin the task.` | Text in the empty chat panel |
| `per_turn_ratings` | none | Rating widgets under each turn of the finished conversation, as in [per-turn dialogue ratings](../annotation-types/instance_display.md#per-turn-dialogue-ratings) |
| `show_turn_numbers` | `true` | Number the turns of the finished conversation |
| `alternating_shading` | `true` | Shade alternate turns |

The field also takes `span_target: true`, so annotators can highlight text in
the finished conversation.

## `agent_proxy` options

| Key | Applies to | Default | Description |
|-----|-----------|---------|-------------|
| `type` | all | required | `echo`, `http`, `openai`, `subprocess_coding` or `docker_coding` |
| `enabled` | all | `true` | `false` turns the proxy off without deleting the block |
| `sandbox.max_steps` | all | 20 | Messages allowed per session |
| `sandbox.max_session_seconds` | all | 600 | Session length limit |
| `sandbox.request_timeout_seconds` | all | 60 | Timeout for one call to the backend |
| `sandbox.rate_limit_per_minute` | all | 10 | Messages per annotator per minute |
| `responses` | `echo` | built-in list | Replies to cycle through, for testing without a model |
| `url` | `http` | required | Endpoint that receives a JSON POST per message |
| `headers` | `http` | `{}` | Extra request headers |
| `message_key` | `http` | `message` | Request field that carries the annotator's message |
| `response_key` | `http` | `response` | Response field that holds the agent's reply |
| `session_id_key` | `http` | `session_id` | Request field that carries the session id |
| `send_history` | `http` | `false` | Also send the conversation so far |
| `history_key` | `http` | `messages` | Request field for the history |
| `api_key` | `openai` | `OPENAI_API_KEY` | Key, or `${ENV_VAR}`. Not needed with a `base_url` |
| `base_url` | `openai` | OpenAI | An OpenAI-compatible server (vLLM, Ollama and others) |
| `model` | `openai` | `gpt-4o` | Model name |
| `system_prompt` | `openai` | empty | System message sent before the task |
| `temperature` | `openai` | 0.7 | Sampling temperature |
| `max_tokens` | `openai` | 1024 | Reply length limit |
| `llm.*` | coding | `endpoint_type: ollama` | Model that plans each step: `endpoint_type`, `model`, `base_url`, `api_key`, `temperature` (0.2), `max_tokens` (800) |
| `execution.per_step_timeout` | coding | 8 | Seconds allowed for one code step |
| `execution.max_output_chars` | coding | 4000 | Output kept from each step |
| `execution.starter_files` | coding | `{}` | Files to put in the workspace, as `{path: content}` |
| `docker.image` | `docker_coding` | `python:3.11-slim` | Container image |
| `docker.memory` | `docker_coding` | `512m` | Memory limit |
| `docker.cpus` | `docker_coding` | 1.0 | CPU limit |
| `docker.network` | `docker_coding` | `none` | Container network |

The `openai` connection settings (`api_key`, `base_url`, `model`,
`system_prompt`, `temperature`, `max_tokens`) can also go under `ai_config`
inside the block. The flat form wins when both are given.

`subprocess_coding` runs the agent's code as a local subprocess in a temporary
directory, with a reduced environment and a per-step timeout. That is not a
security boundary. Use `docker_coding` for anything you do not trust. The
examples `coding-agent-live-test` and `coding-agent-docker-test` under
`examples/agent-testing/` show both.

## Related

- [Live Agent Interaction](live_agent.md): watch and steer a browsing agent
- [Turn-Level Annotation](turn_level_annotation.md): per-turn schemes on finished conversations
- [Coding Agent Annotation](coding_agent_annotation.md)

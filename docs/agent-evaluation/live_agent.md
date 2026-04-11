# Live Agent Interaction

Annotators can observe an AI agent browse the web in real time, with the ability to pause, send instructions, or take over manual control.

## Overview

The live agent feature connects an LLM vision model to a headless browser (via Playwright). The agent takes screenshots, sends them to the LLM, parses actions from the response, and executes them — all streamed to the annotator in real time via Server-Sent Events (SSE).

## Requirements

```bash
pip install playwright anthropic
playwright install chromium
export ANTHROPIC_API_KEY=your_key_here
```

## Configuration

Add a `live_agent` section to your config and use the `live_agent` display type:

```yaml
live_agent:
  endpoint_type: anthropic_vision
  ai_config:
    model: claude-sonnet-4-20250514
    api_key: ${ANTHROPIC_API_KEY}
    max_tokens: 4096
    temperature: 0.3
  system_prompt: |
    You are a web browsing agent...
  max_steps: 30
  step_delay: 1.0
  viewport:
    width: 1280
    height: 720
  allow_takeover: true
  allow_instructions: true

instance_display:
  fields:
    - key: task_description
      type: text
      label: "Task"
    - key: agent_trace
      type: live_agent
      label: "Live Agent Session"
      display_options:
        show_overlays: true
        show_filmstrip: true
        show_thought: true
        show_controls: true
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `endpoint_type` | string | `anthropic_vision` | LLM provider (currently only `anthropic_vision`) |
| `ai_config.model` | string | `claude-sonnet-4-20250514` | Model to use |
| `ai_config.api_key` | string | `$ANTHROPIC_API_KEY` | API key |
| `ai_config.max_tokens` | int | 4096 | Max response tokens |
| `ai_config.temperature` | float | 0.3 | Sampling temperature |
| `system_prompt` | string | (built-in) | System prompt for the agent |
| `max_steps` | int | 30 | Maximum steps before stopping |
| `step_delay` | float | 1.0 | Seconds between steps |
| `viewport.width` | int | 1280 | Browser viewport width |
| `viewport.height` | int | 720 | Browser viewport height |
| `allow_takeover` | bool | true | Allow manual control |
| `allow_instructions` | bool | true | Allow sending instructions |
| `history_window` | int | 5 | Recent steps included in LLM context |

### Display Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `show_overlays` | bool | true | Show SVG action overlays |
| `show_filmstrip` | bool | true | Show step thumbnail filmstrip |
| `show_thought` | bool | true | Show agent thinking panel |
| `show_controls` | bool | true | Show control buttons |
| `allow_takeover` | bool | true | Show takeover button |
| `allow_instructions` | bool | true | Show instruction input |
| `screenshot_max_width` | int | 900 | Max screenshot width (px) |
| `screenshot_max_height` | int | 650 | Max screenshot height (px) |

## Data Format

Each instance should have at minimum:

```json
{
  "id": "task_001",
  "task_description": "Search for climate change on Wikipedia",
  "start_url": "https://en.wikipedia.org"
}
```

The `task_description` and `start_url` fields are used to initialize the agent session.

## Annotator Workflow

1. The annotator sees the task description and a "Start Agent" form
2. Clicking "Start Agent" launches a headless browser and connects the LLM
3. Real-time screenshots stream to the viewer as the agent navigates
4. The annotator can:
   - **Pause/Resume**: Temporarily halt the agent
   - **Send Instructions**: Guide the agent (e.g., "Click the search button instead")
   - **Take Over**: Manually click/type in the browser
   - **Stop**: End the session early
5. When the session completes, the trace is saved and the display switches to review mode
6. The annotator evaluates the agent's performance using the annotation schemes

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| Space | Pause/Resume |
| Escape | Stop |

## Architecture

```
Browser (JS)  <--SSE stream--  Flask Server  <--Playwright-->  Headless Browser
              --REST control->              <--LLM API----->  Claude Vision
```

- **SSE** streams step screenshots, thoughts, and state changes to the client
- **REST endpoints** handle pause/resume/instruct/takeover/stop
- **Background thread** runs the async agent loop with its own event loop
- **Screenshots** are saved to `{task_dir}/live_sessions/` and served via API

## Trace Export

Completed sessions are automatically exported as `web_agent_trace`-compatible JSON, including:
- All steps with screenshots, actions, thoughts, and observations
- Annotator interactions (instructions sent, takeover periods)
- Agent configuration metadata

## Example

```bash
python potato/flask_server.py start examples/agent-traces/live-agent-evaluation/config.yaml -p 8000
```

## Troubleshooting

- **"Playwright is not installed"**: Run `pip install playwright && playwright install chromium`
- **"Anthropic API key required"**: Set `ANTHROPIC_API_KEY` environment variable
- **Agent seems slow**: Each step involves an LLM API call (3-10s). The "thinking" indicator shows when the LLM is processing.
- **Screenshots not loading**: Check that the `task_dir` is writable and the server has disk space

## Related Documentation

- [Web Agent Trace Review](../annotation-types/schemas_and_templates.md) — Post-hoc trace review
- [AI Support](../ai-intelligence/ai_support.md) — AI endpoint configuration

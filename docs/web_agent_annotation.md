# Web Agent Annotation

Potato supports both **reviewing** and **creating** web agent browsing traces through an interactive interface with SVG overlay visualizations.

## Overview

Web agent annotation provides two modes:

1. **Review Mode** — View pre-recorded agent browsing traces step-by-step with screenshot overlays showing clicks, bounding boxes, mouse paths, and scroll indicators. Annotators evaluate agent behavior using per-step and trajectory-level annotation schemes.

2. **Creation Mode** — Browse websites through a proxied iframe while interactions are automatically recorded to build new agent traces.

## Review Mode

### Configuration

```yaml
instance_display:
  fields:
    - key: steps
      type: web_agent_trace
      label: "Agent Browsing Trace"
      display_options:
        show_overlays: true         # Enable SVG overlays (default: true)
        show_filmstrip: true        # Show thumbnail filmstrip bar (default: true)
        show_thought: true          # Show agent's reasoning (default: true)
        show_observation: true      # Show environment observations (default: true)
        show_element_info: true     # Show target element details (default: true)
        screenshot_max_width: 800   # Max screenshot width in pixels (default: 800)
        screenshot_max_height: 600  # Max screenshot height in pixels (default: 600)
        filmstrip_size: 80          # Thumbnail size in pixels (default: 80)
```

### Data Format

Each instance should contain a `steps` array with step-level data:

```json
{
  "id": "trace_001",
  "task_description": "Find and add a blue wool sweater to cart",
  "site": "amazon.com",
  "steps": [
    {
      "step_index": 0,
      "screenshot_url": "screenshots/step_000.png",
      "action_type": "click",
      "element": {
        "tag": "input",
        "text": "Search",
        "bbox": [340, 45, 680, 75]
      },
      "coordinates": {"x": 510, "y": 60},
      "mouse_path": [[200, 300], [350, 200], [510, 60]],
      "thought": "I need to search for blue wool sweaters",
      "observation": "Search box is focused",
      "timestamp": 1.2,
      "viewport": {"width": 1280, "height": 720}
    }
  ]
}
```

### Supported Action Types

| Action | Description | Overlay |
|--------|-------------|---------|
| `click` | Mouse click on element | Red circle + crosshair |
| `type` | Text input | Yellow highlight on target |
| `scroll` | Page scroll | Green directional arrow |
| `hover` | Mouse hover | Purple circle |
| `select` | Dropdown selection | Blue bounding box |
| `navigate` | URL navigation | — |
| `wait` | Waiting for page load | — |
| `done` | Task completion | — |

### SVG Overlays

The viewer renders SVG overlays on top of screenshots:

- **Click markers** — Red circle with crosshair and pulse animation at click coordinates
- **Bounding boxes** — Blue dashed rectangle around the target element's bounding box
- **Mouse paths** — Orange curved line showing the mouse trajectory with animated dash
- **Scroll indicators** — Green arrow showing scroll direction and magnitude

### Keyboard Shortcuts

When the viewer is focused (click on it):

| Key | Action |
|-----|--------|
| `←` / `→` | Previous / Next step |
| `1` | Toggle click marker overlays |
| `2` | Toggle bounding box overlays |
| `3` | Toggle mouse path overlays |
| `4` | Toggle scroll indicator overlays |
| `A` | Show all overlays |
| `N` | Hide all overlays |

### Per-Step Annotations

Add `per_step: true` to an annotation scheme to create per-step annotations that appear inline with each step:

```yaml
annotation_schemes:
  - annotation_type: radio
    name: step_correctness
    per_step: true
    labels:
      - name: correct
      - name: incorrect
      - name: unnecessary
```

Per-step annotations are stored as `{scheme_name}_step_{index}` (e.g., `step_correctness_step_0`).

### Converting Traces

Use the web agent converter to transform various formats:

```bash
# Convert from file
python -m potato.trace_converter -i traces.json -f web_agent -o output.jsonl

# Auto-detect format
python -m potato.trace_converter -i traces.json --auto-detect -o output.jsonl
```

Supported input formats:
- **WebArena/VisualWebArena** — `action_type` + `element` in action steps
- **Mind2Web** — `operation` + `target_html` in action steps
- **Anthropic Computer Use** — Tool blocks with `computer_20241022` type
- **Raw recordings** — Steps with `mouse_path` + `viewport` data

## Creation Mode

### Configuration

```yaml
instance_display:
  fields:
    - key: browsing_session
      type: web_agent_recorder
      display_options:
        start_url: "https://www.google.com"
        proxy_mode: auto          # auto, iframe, playwright
        record_mouse_path: true
        record_viewport: true
        screenshot_method: server
        max_steps: 50
```

### How It Works

1. The annotator sees a task description and a browser iframe
2. They browse the website while their interactions are recorded
3. Clicks, typing, scrolling, and mouse movements are captured
4. Screenshots are taken at each step
5. The recording is saved as a structured trace

### Proxy Modes

- **`auto`** (default) — Automatically detects if the target site allows iframe embedding. Uses iframe proxy if allowed, falls back to Playwright if not.
- **`iframe`** — Forces iframe proxy mode. Works for ~90% of sites. Fast with <100ms overhead.
- **`playwright`** — Forces server-side Playwright mode. Works for 100% of sites. Requires `playwright` package installation.

### Playwright Setup (Optional)

For sites that block iframes:

```bash
pip install playwright
playwright install chromium
```

## Example Projects

### Review Mode

```bash
python potato/flask_server.py start examples/agent-traces/web-agent-review/config.yaml -p 8000
```

### Creation Mode

```bash
python potato/flask_server.py start examples/agent-traces/web-agent-creation/config.yaml -p 8000
```

## API Endpoints

### Recording API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/web_agent/start_session` | POST | Start recording session |
| `/api/web_agent/save_step` | POST | Save a recorded step |
| `/api/web_agent/save_screenshot` | POST | Upload step screenshot |
| `/api/web_agent/end_session` | POST | End session, save trace |
| `/api/web_agent/proxy/<url>` | GET | Proxy external URL |
| `/api/web_agent/check_frameable` | GET | Check iframe compatibility |

## Related Documentation

- [Agent Trace Display](schemas_and_templates.md) — Standard agent trace step cards
- [Configuration Reference](configuration.md) — Full configuration options
- [Trace Converters](configuration.md) — Converting between trace formats

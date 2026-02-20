# Option Highlighting

Option Highlighting is an AI-assisted feature that helps annotators identify the most likely correct options for discrete annotation tasks (radio buttons, checkboxes, likert scales). Using an LLM, the system analyzes the content and task description to predict the top-k most likely options, displaying them at full opacity while dimming less-likely options.

## Overview

When enabled, Option Highlighting:

1. Analyzes instance content using an LLM
2. Identifies the most probable options based on task context
3. Highlights likely options with a star indicator (★)
4. Dims less-likely options (configurable opacity)
5. Keeps all options fully clickable - this is guidance, not restriction

This feature is particularly useful for:
- Tasks with many options where some are clearly more relevant
- Training new annotators by showing likely patterns
- Reducing cognitive load on complex classification tasks
- Providing a "second opinion" to increase annotation confidence

## Configuration

Add the `option_highlighting` section under `ai_support` in your config:

```yaml
ai_support:
  enabled: true
  endpoint_type: "openai"  # Any text-capable endpoint
  ai_config:
    model: "gpt-4o-mini"   # Fast, cost-effective model recommended
    api_key: "${OPENAI_API_KEY}"
    temperature: 0.3       # Lower temperature for consistency

  option_highlighting:
    enabled: true
    top_k: 3                    # Number of options to highlight (1-10)
    dim_opacity: 0.4            # Opacity for non-highlighted options (0.1-0.9)
    auto_apply: true            # Apply on page load vs manual trigger
    schemas: null               # null = all schemas, or ["schema1", "schema2"]
    prefetch_count: 20          # Items to prefetch (default: 20)

  cache_config:
    disk_cache:
      enabled: true
      path: annotation_output/ai_cache.json
    prefetch:
      warm_up_page_count: 10    # Prefetch on startup
      on_next: 3                # Prefetch when moving forward
      on_prev: 1                # Prefetch when moving backward
```

## Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | boolean | `false` | Enable/disable option highlighting |
| `top_k` | integer | `3` | Number of options to highlight (1-10) |
| `dim_opacity` | float | `0.4` | Opacity for dimmed options (0.1-0.9) |
| `auto_apply` | boolean | `true` | Automatically apply on page load |
| `schemas` | list/null | `null` | Limit to specific schema names, or `null` for all |
| `prefetch_count` | integer | `20` | Number of items to prefetch ahead |

## Supported Annotation Types

Option highlighting works with discrete choice annotation types:

- **radio** - Single choice selection
- **multiselect** - Multiple checkbox selection
- **likert** - Likert scale ratings
- **select** - Dropdown selection (limited visual effect)

It does **not** apply to:
- `span` - Text span annotations
- `textbox` - Free text input
- `slider` - Continuous value selection
- `image_annotation` - Bounding boxes
- `video_annotation` - Temporal annotations

## Visual Appearance

### Highlighted Options
- Full opacity (1.0)
- Gold star indicator (★) before the label
- Subtle background highlight

### Dimmed Options
- Reduced opacity (configurable, default 0.4)
- Brighten to 0.7 on hover
- Still fully clickable

### Form Indicator
- Gold left border on annotation forms with highlighting active
- Small "AI" badge at the top-left corner

## Prefetching for Smooth Navigation

Since LLM queries can be slow, option highlighting uses aggressive prefetching:

1. **Warmup**: First N items prefetched on server start
2. **On navigation**: Next items prefetched when user moves forward/backward
3. **Background processing**: Prefetch happens asynchronously
4. **Caching**: Results cached to disk for reuse

Configure prefetch behavior:

```yaml
option_highlighting:
  prefetch_count: 20          # Per-navigation prefetch count

cache_config:
  prefetch:
    warm_up_page_count: 10    # Initial warmup count
```

## API Endpoints

### Get Highlights for Current Instance

```
GET /api/option_highlights/<annotation_id>
```

Returns:
```json
{
  "highlighted": ["Positive", "Neutral"],
  "top_k": 2,
  "confidence": 0.85,
  "config": {
    "enabled": true,
    "top_k": 2,
    "dim_opacity": 0.4,
    "auto_apply": true
  }
}
```

### Get Configuration

```
GET /api/option_highlights/config
```

### Trigger Prefetch

```
POST /api/option_highlights/prefetch
Content-Type: application/json

{"count": 20}
```

## Example Project

A complete example is available at:
```
examples/advanced/option-highlight/
```

Run it:
```bash
export OPENAI_API_KEY="your-api-key"
python potato/flask_server.py start examples/advanced/option-highlight/config.yaml -p 8000
```

## Best Practices

1. **Use a fast model**: `gpt-4o-mini` or similar provides good balance of speed and accuracy
2. **Set appropriate top_k**: For binary choices use 1, for 4-5 options use 2-3
3. **Enable prefetching**: Higher `prefetch_count` (20+) ensures smooth navigation
4. **Consider task complexity**: More complex tasks benefit more from highlighting
5. **Train annotators**: Explain that highlights are suggestions, not requirements

## Troubleshooting

### Highlights not appearing

1. Check that `ai_support.enabled` is `true`
2. Check that `option_highlighting.enabled` is `true`
3. Verify the annotation type is supported (radio, multiselect, likert)
4. Check browser console for API errors
5. Verify API key is set correctly

### Slow highlighting

1. Increase `prefetch_count` to prefetch more items
2. Use a faster model (e.g., `gpt-4o-mini` instead of `gpt-4`)
3. Enable disk caching to avoid re-computing

### Incorrect suggestions

1. Improve the annotation scheme description
2. Use a more capable model
3. Adjust `temperature` in `ai_config` (lower = more consistent)

## Security Considerations

- Highlights are generated server-side, not exposed to users
- LLM responses are cached locally (not sent externally)
- All options remain selectable regardless of highlighting
- Annotators should not over-rely on AI suggestions

## Related Documentation

- [AI Support](ai_support.md) - General AI assistant configuration
- [Annotation Schemas](schemas_and_templates.md) - Supported annotation types
- [Configuration](configuration.md) - Complete configuration reference

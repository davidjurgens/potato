# Developer Guide

This guide covers extending Potato, integrating via API, and customizing the platform.

## Architecture Overview

Potato is a Flask-based web application with these core components:

| Component | File | Purpose |
|-----------|------|---------|
| Flask app | `potato/flask_server.py` | Server startup, data loading, configuration |
| Routes | `potato/routes.py` | HTTP route handlers for annotation workflow |
| Item state | `potato/item_state_management.py` | Singleton managing annotation items and assignment |
| User state | `potato/user_state_management.py` | Singleton tracking user progress and annotations |
| Config | `potato/server_utils/config_module.py` | Configuration loading and validation |
| Schemas | `potato/server_utils/schemas/` | Annotation type implementations |

## API Reference

Full REST API documentation for programmatic access:

- **[API Reference](../api-reference/api_reference.md)** - All endpoints for authentication, annotation, admin, and data access

## Adding New Annotation Types

Schema implementations live in `potato/server_utils/schemas/`. To add a new type:

1. Create `potato/server_utils/schemas/my_schema.py`
2. Register in `potato/server_utils/schemas/registry.py`
3. Add to valid_types in `potato/server_utils/config_module.py`
4. Create documentation at `docs/annotation-types/<category>/my_schema.md`
5. Add example project at `examples/<category>/my-schema-example/`

For the schema registry API, see the [Schema Gallery](../annotation-types/schemas_and_templates.md).

## Custom Layouts and UI

- **[UI Configuration](../configuration/ui_configuration.md)** - Interface customization options
- **[Form Layout](../configuration/form_layout.md)** - Grid layout, column spanning, styling, and alignment
- **[Layout Customization](../configuration/layout_customization.md)** - Custom CSS and HTML layouts
- **[Conditional Logic](../configuration/conditional_logic.md)** - Show/hide questions based on prior answers
- **[Instance Display](../annotation-types/instance_display.md)** - Separate content display from annotation

## Webhooks and Integrations

- **[Webhooks](../integrations/webhooks.md)** - Outgoing webhook notifications for annotation events
- **[LangChain Integration](../integrations/langchain_integration.md)** - Send LangChain agent traces to Potato

## AI Integration

- **[AI Integration Internals](../ai-intelligence/ai_integration_internals.md)** - Architecture for AI endpoints
- **[Solo Mode Developer Guide](../solo-mode/solo_mode_developer_guide.md)** - Extending the Solo Mode pipeline

AI endpoints are in `potato/ai/`:
- `ai_endpoint.py` - Base endpoint interface
- `openai_endpoint.py`, `anthropic_endpoint.py`, `ollama_endpoint.py`, etc.

## Development Tools

- **[Preview CLI](../tools/preview_cli.md)** - Preview configs without running the server
- **[Simulator](../tools/simulator.md)** - Automated user simulation for testing
- **[Debugging Guide](../tools/debugging_guide.md)** - Debug flags and troubleshooting
- **[Migration CLI](../tools/migration_cli.md)** - Upgrade v1 configs to v2 format

## Testing

```bash
pytest tests/unit/ -v        # Fast unit tests
pytest tests/server/ -v      # Server integration tests
pytest tests/selenium/ -v    # Browser tests
pytest --cov=potato --cov-report=html  # Coverage
```

## Contributing

- **[Contributing Guide](../deployment/open-sourcing.md)** - How to contribute to Potato

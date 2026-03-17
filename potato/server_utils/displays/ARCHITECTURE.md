# Display Type System Architecture

This document describes the design contracts and extension points for the
display type system in `potato/server_utils/displays/`.

## Overview

The display system separates **content presentation** from **annotation
collection**.  Each field in `instance_display.fields` has a `type` that
maps to a registered display class.  Displays produce HTML; annotation
schemas collect labels.

```
Config YAML
  └─ instance_display.fields[].type
       └─ DisplayRegistry.render()
            └─ BaseDisplay.render()  →  inner HTML
            └─ render_display_container()  →  wrapped HTML
                 └─ template {{ display_html | safe }}
```

## Key Files

| File | Purpose |
|------|---------|
| `base.py` | `BaseDisplay` ABC — class attributes, abstract `render()`, helpers |
| `registry.py` | `DisplayRegistry` singleton — registration, lookup, render dispatch |
| `../instance_display.py` | `InstanceDisplayRenderer` — orchestrates field rendering |
| `__init__.py` | Package exports |

## BaseDisplay Contract

### Required to implement

| Method / Attribute | Description |
|--------------------|-------------|
| `name: str` | Unique type identifier (e.g., `"dialogue"`) |
| `render(field_config, data) -> str` | Return inner HTML for the field content |

### Optional to override

| Method | Default | When to override |
|--------|---------|------------------|
| `get_css_classes(field_config)` | `["display-field", "display-type-{name}"]` | Add type-specific classes |
| `get_data_attributes(field_config, data)` | `{"field-key", "field-type", "span-target"}` | Add custom data attrs |
| `get_js_init()` | `None` | Return JS to run on page load |
| `validate_config(field_config)` | Checks `required_fields` | Add enum/range validation |
| `has_inline_label(field_config)` | `False` | Return `True` if display renders its own label (avoids duplicate) |
| `get_display_options(field_config)` | Merges `optional_fields` with `display_options` | Rarely needed |

### Class attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `required_fields` | `List[str]` | Config keys that must be present |
| `optional_fields` | `Dict[str, Any]` | Default values for optional display_options |
| `description` | `str` | Human-readable description |
| `supports_span_target` | `bool` | Whether this type implements the span annotation contract |

## Span Target Contract

**If `supports_span_target = True`, the display MUST satisfy these requirements
when `field_config["span_target"]` is `True`:**

### 1. `.text-content` wrapper

The rendered HTML must contain:

```html
<div class="text-content"
     id="text-content-{field_key}"
     data-original-text="{escaped_plain_text}"
     style="position: relative; padding-top: 24px;">
  {content HTML}
</div>
```

Use the `render_span_wrapper()` helper:

```python
if field_config.get("span_target"):
    inner_html = self.render_span_wrapper(field_key, inner_html, plain_text)
```

### 2. `data-original-text` must contain plain text

The `plain_text` argument to `render_span_wrapper()` must be the canonical
plain text that `routes.py` will use for span offset extraction.  For
structured data (dialogue, lists), use `concatenate_dialogue_text()` from
`base.py` so both rendering and API extraction use identical formats.

### 3. CSS classes on the outer container

Override `get_css_classes()` to add `"span-target-field"` and
`"span-target-{name}"` when span_target is true.

### 4. Text format consistency

The text format used in `data-original-text` **MUST** match the text
extraction logic in `routes.py` (`/api/spans/<id>` endpoint).  If the
data is a list of dicts, both sides must use `concatenate_dialogue_text()`.

### Why this matters

SpanManager (span-core.js) discovers span-target fields via:
```javascript
document.querySelectorAll('.display-field[data-span-target="true"]')
```
Then looks for the text element inside each:
```javascript
const textContent = field.querySelector('.text-content');
```
If `.text-content` is missing, SpanManager silently skips the field and
span annotation will not work.

## Registry

The `display_registry` singleton provides:

- `render(field_type, field_config, data)` — render a field
- `get_supported_types()` — list all registered type names
- `type_supports_span_target(field_type)` — check span target support
- `get_span_target_types()` — list all types supporting span targets
- `validate(field_type, field_config)` — validate config
- `list_displays()` — metadata for all displays

The registry wraps each display's `render()` output in
`render_display_container()`, which adds the outer `.display-field` div,
label, and `.display-field-content` wrapper.

## Instance Display Renderer

`InstanceDisplayRenderer` in `instance_display.py`:

1. Reads `instance_display.fields` from config
2. Queries `display_registry.type_supports_span_target()` for span targets
   (no hardcoded list)
3. Warns if `span_target: true` is set on an unsupported type
4. Renders each field via `display_registry.render()`
5. Optionally wraps in resizable container (`_wrap_resizable()`)

## Adding a New Display Type

1. Create `my_display.py` with a class extending `BaseDisplay`
2. Set `name`, `required_fields`, `optional_fields`, `description`
3. If supporting span annotation:
   - Set `supports_span_target = True`
   - Use `render_span_wrapper()` in `render()` when `span_target` is True
   - Override `get_css_classes()` to add `span-target-field`
4. Register in `registry.py` via `DisplayDefinition`
5. Add to `__init__.py` exports
6. Add CSS to `styles.css` using `.display-type-{name}` convention
7. Write unit tests verifying render output
8. Write a contract enforcement test (see `test_display_span_contract.py`)

## Shared Utilities

| Function | Location | Purpose |
|----------|----------|---------|
| `render_span_wrapper(field_key, inner_html, plain_text)` | `BaseDisplay` method | Standard `.text-content` wrapper |
| `concatenate_dialogue_text(data, speaker_key, text_key)` | `base.py` module | Canonical dialogue→plain text conversion |
| `render_display_container(inner_html, classes, attrs, label)` | `base.py` module | Standard outer container wrapper |

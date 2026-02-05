# Layout Customization Guide

This guide explains how to create sophisticated, custom visual layouts for your annotation tasks using custom CSS and HTML templates.

## Overview

Potato provides two approaches for customizing the annotation interface layout:

1. **Auto-generated layouts**: Potato generates a `layouts/task_layout.html` file that you can edit
2. **Custom layout files**: Create your own HTML template with full control over styling

## Quick Start

### Using Auto-generated Layouts

1. Run your server once - Potato creates `layouts/task_layout.html`
2. Edit the generated file to customize styling
3. Your changes persist across server restarts (unless you modify `annotation_schemes` in the config)

### Using Custom Layout Files

1. Create your layout file (e.g., `layouts/custom_task_layout.html`)
2. Reference it in your config:

```yaml
task_layout: layouts/custom_task_layout.html
```

## Layout File Structure

A custom layout file must include:

```html
<style>
    /* Your custom CSS */
</style>

<div class="annotation_schema">
    <!-- Your annotation forms -->
    <form id="schema_name" class="annotation-form radio" data-annotation-id="0">
        <fieldset schema="schema_name">
            <legend>Question text</legend>
            <!-- Input elements -->
        </fieldset>
    </form>
</div>
```

### Required Form Attributes

Each annotation scheme needs:

- `id`: Must match the `name` in your config's `annotation_schemes`
- `class`: Include `annotation-form` and the type (e.g., `radio`, `multiselect`)
- `data-annotation-id`: Sequential index (0, 1, 2...)
- `schema` attribute on fieldset and inputs

### Required Input Attributes

```html
<input class="schema_name annotation-input"
       type="radio"
       name="schema_name"
       value="label_value"
       schema="schema_name"
       label_name="label_value"
       onclick="onlyOne(this);registerAnnotation(this);">
```

## Example Layouts

Potato includes three sophisticated example layouts demonstrating advanced customization:

### 1. Content Moderation Dashboard

**Location**: `project-hub/layout-examples/content-moderation/`

**Features**:
- Warning banner header with content metadata
- 2-column grid for violation categories
- Color-coded severity levels (green/yellow/red)
- Professional moderation workflow

**Run**:
```bash
python potato/flask_server.py start project-hub/layout-examples/content-moderation/config.yaml -p 8000
```

### 2. Customer Service Dialogue QA

**Location**: `project-hub/layout-examples/dialogue-qa/`

**Features**:
- Case header with metadata badges
- Grouped assessment sections
- Circular Likert-scale ratings
- Quality issues checklist
- Color-coded resolution indicators

**Run**:
```bash
python potato/flask_server.py start project-hub/layout-examples/dialogue-qa/config.yaml -p 8000
```

### 3. Medical Image Review

**Location**: `project-hub/layout-examples/medical-review/`

**Features**:
- Professional medical UI styling
- Two-column layout for location/severity
- Grouped findings sections
- Structured medical reporting workflow
- Recommendation cards with descriptions

**Run**:
```bash
python potato/flask_server.py start project-hub/layout-examples/medical-review/config.yaml -p 8000
```

## CSS Techniques

### Grid Layouts

Create multi-column layouts:

```css
.annotation-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 16px;
}

/* Full-width items */
.full-width {
    grid-column: 1 / -1;
}

/* Responsive */
@media (max-width: 768px) {
    .annotation-grid {
        grid-template-columns: 1fr;
    }
}
```

### Color-Coded Options

Style radio buttons with severity colors:

```css
.severity-option input[type="radio"] {
    position: absolute;
    opacity: 0;
}

.severity-label {
    display: block;
    padding: 10px;
    border-radius: 6px;
    border: 2px solid transparent;
    cursor: pointer;
    transition: all 0.2s;
}

/* None - Green */
.severity-none .severity-label {
    background: #dcfce7;
    color: #166534;
}
.severity-none input:checked + .severity-label {
    background: #22c55e;
    color: white;
}

/* Severe - Red */
.severity-severe .severity-label {
    background: #fee2e2;
    color: #991b1b;
}
.severity-severe input:checked + .severity-label {
    background: #ef4444;
    color: white;
}
```

### Section Styling

Create visual groupings:

```css
.annotation-section {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 16px;
    margin-bottom: 16px;
}

.section-title {
    font-size: 13px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 12px;
    padding-bottom: 8px;
    border-bottom: 2px solid #3b82f6;
}

/* Accent border */
.primary-section {
    border-left: 4px solid #3b82f6;
}
```

### Circular Likert Ratings

```css
.likert-circle {
    width: 36px;
    height: 36px;
    border-radius: 50%;
    border: 2px solid #e2e8f0;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
}

.likert-option input:checked + .likert-circle {
    background: #8b5cf6;
    color: white;
    border-color: #7c3aed;
}
```

### Header Banners

```css
.warning-banner {
    background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%);
    border: 2px solid #f59e0b;
    border-radius: 8px;
    padding: 12px 20px;
    display: flex;
    align-items: center;
    gap: 12px;
}
```

## Combining with Instance Display

Custom layouts work alongside `instance_display` configuration. The instance content (images, text, dialogues) is rendered separately above your annotation forms.

```yaml
# Instance display renders content
instance_display:
  fields:
    - key: image_url
      type: image
      display_options:
        zoomable: true

# Custom layout controls annotation form presentation
task_layout: layouts/custom_task_layout.html

# Annotation schemes define the data structure
annotation_schemes:
  - annotation_type: radio
    name: category
    # ...
```

## Best Practices

1. **Match schema names**: Form `id` must exactly match `name` in `annotation_schemes`
2. **Sequential annotation IDs**: Use 0, 1, 2... for `data-annotation-id`
3. **Include required handlers**: Use `onclick="onlyOne(this);registerAnnotation(this);"` for radio, `onclick="registerAnnotation(this);"` for checkbox
4. **Test responsiveness**: Use media queries for mobile support
5. **Keep accessibility**: Use proper labels, maintain keyboard navigation
6. **Hide default styling**: Override Potato's default form styles with your CSS

## Troubleshooting

### Annotations not saving

Check that:
- Form `id` matches annotation scheme `name`
- Inputs have `schema` and `label_name` attributes
- Click handlers (`registerAnnotation`) are present

### Styles not applying

- Ensure CSS specificity is high enough to override defaults
- Check that your `<style>` block is inside the layout file
- Use browser dev tools to inspect applied styles

### Layout not loading

- Verify path in `task_layout` is relative to config file
- Check for HTML syntax errors
- Review server logs for error messages

## Related Documentation

- [Instance Display](instance_display.md) - Configure what content to show
- [Annotation Schemas](schemas_and_templates.md) - Available annotation types
- [Configuration Reference](configuration.md) - Full configuration options

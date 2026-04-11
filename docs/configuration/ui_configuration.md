# User Interface Configuration

## Overview

The Potato annotation platform provides extensive configuration options for customizing the user interface. These settings allow administrators to control the appearance, behavior, and functionality of the annotation interface to suit their specific needs.

## Configuration Structure

All UI configuration options are defined in the `ui` section of your configuration file:

```yaml
ui:
  # UI configuration options go here
```

## Available Configuration Options

### 1. Maximum Instance Height

**Option**: `max_instance_height`

**Description**: Controls the maximum height of the instance text display area. When long text instances would otherwise push annotation options below the visible area, this feature provides a scrollable text area to keep the interface usable.

**Type**: Integer (pixels)

**Default**: No limit (full height display)

**Example**:
```yaml
ui:
  max_instance_height: 300  # 300 pixels maximum height
```

**How It Works**:
1. **When `max_instance_height` is specified**: The instance text area is limited to the specified height in pixels. If the text exceeds this height, a scrollbar appears allowing users to scroll through the text while keeping the annotation options visible.

2. **When `max_instance_height` is not specified**: The instance text area displays the full text without height restrictions (default behavior).

**Benefits**:
- **Improved Usability**: Long text instances no longer push annotation options out of view
- **Consistent Interface**: Annotation options remain in a predictable location
- **Flexible Configuration**: Can be enabled/disabled per task as needed
- **Customizable Height**: Adjust the maximum height based on your specific needs

**Technical Details**:
- The feature uses CSS `max-height` and `overflow-y: auto` for scrolling
- Custom scrollbar styling is applied for better visual integration
- The height limit is applied via CSS custom properties for dynamic configuration
- JavaScript automatically applies the configuration when the page loads

**Browser Compatibility**:
- **Chrome/Edge**: Full support with custom scrollbar styling
- **Firefox**: Full support with standard scrollbar
- **Safari**: Full support with standard scrollbar
- **Mobile browsers**: Responsive design with touch-friendly scrolling

### 2. Label Colors

Potato supports custom colors for labels across all annotation types (radio, checkbox, span, likert, etc.). Colors are used for:
- Span annotation highlighting
- AI keyword highlighting
- Visual label differentiation in the interface

#### Option A: Global Label Colors (`ui.label_colors`)

**Description**: Define colors for labels across all schemas in one place.

**Type**: Object mapping schema names to label color mappings

**Example**:
```yaml
ui:
  label_colors:
    sentiment:
      positive: "#22C55E"      # Green
      negative: "#EF4444"      # Red
      neutral: "#9CA3AF"       # Gray
    emotion:
      happy: "rgba(34, 197, 94, 0.8)"
      sad: "rgba(59, 130, 246, 0.8)"
      angry: "rgba(220, 38, 38, 0.8)"
```

#### Option B: Inline Label Colors (in `annotation_schemes`)

**Description**: Define colors directly on each label in your annotation scheme.

**Example**:
```yaml
annotation_schemes:
  - annotation_type: radio
    name: sentiment
    description: "What is the sentiment?"
    labels:
      - name: positive
        color: "#22C55E"
        tooltip: "Positive sentiment"
      - name: negative
        color: "#EF4444"
        tooltip: "Negative sentiment"
      - name: neutral
        color: "#9CA3AF"
        tooltip: "Neutral sentiment"
```

#### Option C: Span-Specific Colors (Legacy)

**Description**: The original span-only color configuration, still supported.

**Example**:
```yaml
ui:
  spans:
    span_colors:
      sentiment:
        positive: "(220, 252, 231)"  # RGB format
        negative: "(254, 226, 226)"
```

#### Color Format Support

All color options support multiple formats:
- **Hex format**: `"#FF8000"` or `"#F80"`
- **RGB format**: `"(255, 128, 0)"` or `"rgb(255, 128, 0)"`
- **RGBA format**: `"rgba(255, 128, 0, 0.8)"`
- **Named colors**: `"red"`, `"blue"`, `"green"`, etc.

#### Default Colors for Common Labels

If no custom color is specified, Potato automatically assigns colors based on label names:

| Label Name | Color |
|------------|-------|
| positive, yes, true, happy | Green |
| negative, no, false, angry | Red |
| neutral, maybe | Gray |
| mixed, surprise | Amber |
| sad | Blue |
| fear | Violet |

Labels not in this list receive colors from a default palette based on their position.

#### Color Priority

Colors are resolved in this order (first match wins):
1. `ui.label_colors` (highest priority)
2. `ui.spans.span_colors` (for span annotations)
3. Inline `color` property on label definition
4. Auto-generated from `SPAN_COLOR_PALETTE`
5. Default colors based on label name
6. Fallback palette color based on index

### 3. Interface Display Options

**Options**: `show_progress`, `show_instructions`, `allow_navigation`, `allow_editing`

**Description**: Control the visibility and functionality of various interface elements.

**Type**: Boolean

**Default**: All options default to `true` if not specified

**Example**:
```yaml
ui:
  show_progress: true        # Show progress indicators
  show_instructions: true    # Show instruction panels
  allow_navigation: true     # Allow navigation between instances
  allow_editing: true        # Allow editing of annotations
```

**Available Options**:
- `show_progress`: Display progress bars and completion statistics
- `show_instructions`: Show instruction panels and help text
- `allow_navigation`: Enable previous/next navigation buttons
- `allow_editing`: Allow users to modify existing annotations

## Task Layout Customization

Potato automatically generates HTML layouts for your annotation task based on your configuration. You can customize these layouts or provide your own.

### Auto-Generated Layouts

When you run Potato, it automatically generates a layout file at:
```
{task_dir}/annotation_layouts/annotation_layout.html
```

This file contains the HTML for your annotation forms and is regenerated when your config changes (detected via MD5 hash).

**Benefits of auto-generated layouts:**
- Always synchronized with your config
- Automatic keybinding integration
- Consistent styling with the Potato design system
- No maintenance required

### Viewing the Generated Layout

To see what Potato generates, simply run your task once and then examine the layout file:
```bash
cat {task_dir}/annotation_layouts/annotation_layout.html
```

The file includes a config hash comment at the top:
```html
<!-- CONFIG_HASH: abc123... -->
<!-- Auto-generated annotation layout - customizable -->
```

### Custom Task Layouts

If you need more control over the layout, you can provide a custom HTML file:

```yaml
task_layout: "my_custom_layout.html"
```

**Creating a Custom Layout:**

1. **Start from the generated layout**: Copy the auto-generated file as a starting point
2. **Modify as needed**: Adjust HTML, add custom elements, change arrangement
3. **Reference your file**: Set `task_layout` in your config

**Example Custom Layout:**
```html
<!-- my_custom_layout.html -->
<div class="custom-annotation-container">
    <div class="instructions-panel">
        <h3>Quick Guide</h3>
        <p>Select the sentiment that best matches the text.</p>
    </div>

    <!-- Annotation form - use the generated form code -->
    <div class="annotation-form" data-annotation-id="0" data-schema-name="sentiment">
        <div class="annotation-form-header">
            <span class="annotation-name">Sentiment Analysis</span>
            <div class="ai-help none"><div class="tooltip"></div></div>
        </div>
        <p class="annotation-desc">What is the overall sentiment?</p>
        <div class="annotation-form-body">
            <!-- Radio options generated by Potato -->
            <label class="shadcn-radio-option">
                <input type="radio" name="schema_0" value="positive">
                <span>Positive</span>
            </label>
            <label class="shadcn-radio-option">
                <input type="radio" name="schema_0" value="negative">
                <span>Negative</span>
            </label>
            <label class="shadcn-radio-option">
                <input type="radio" name="schema_0" value="neutral">
                <span>Neutral</span>
            </label>
        </div>
    </div>
</div>
```

### Layout Structure Requirements

Custom layouts must include certain elements for Potato to function correctly:

| Element | Purpose | Required |
|---------|---------|----------|
| `.annotation-form` | Container for each annotation scheme | Yes |
| `data-annotation-id` | Unique ID matching your config | Yes |
| `data-schema-name` | Schema name for color lookups | Recommended |
| `.ai-help` | Container for AI assistant buttons | If using AI |
| `.tooltip` | Tooltip display for AI hints | If using AI |
| Input elements | Radio, checkbox, text, etc. | Yes |

### CSS Classes Reference

Potato's styling system uses these CSS classes:

**Form Structure:**
- `.annotation-form` - Main form container
- `.annotation-form-header` - Header with name and AI buttons
- `.annotation-form-body` - Body with input options
- `.annotation-name` - Schema name display
- `.annotation-desc` - Description text

**Input Options (ShadCN-styled):**
- `.shadcn-radio-option` - Radio button option
- `.shadcn-checkbox-option` - Checkbox option
- `.shadcn-span-option` - Span annotation option
- `.shadcn-likert-option` - Likert scale option

**AI Features:**
- `.ai-help` - AI assistant container
- `.ai-assistant-containter` - Individual AI button
- `.hint` - Hint button class
- `.keyword` - Keyword button class
- `.tooltip` - Tooltip display area

### JavaScript Integration

Custom layouts can use Potato's JavaScript APIs:

```javascript
// Access the AI assistant manager
window.aiAssistantManager.getLabelColor('positive', 'sentiment');

// Access the span manager (for span annotations)
window.spanManager.renderSpans();

// Access configuration
window.config.debug; // Debug mode flag
```

### Regenerating Layouts

To force layout regeneration:
1. Delete the layout file: `rm {task_dir}/annotation_layouts/annotation_layout.html`
2. Restart the server

Or modify your config (any change triggers regeneration).

## Site Directory Configuration

### Custom Templates

**Option**: `site_dir`

**Description**: Specifies the directory containing custom HTML templates for the annotation interface.

**Type**: String (path)

**Default**: `"default"` (uses built-in templates)

**Example**:
```yaml
site_dir: "custom_templates"  # Use custom templates
```

**Usage**:
- Set to `"default"` to use built-in templates
- Set to a custom path to use your own HTML templates
- Custom templates must follow the Potato template structure

### Custom JavaScript

**Options**: `customjs`, `customjs_hostname`

**Description**: Allows injection of custom JavaScript code into the annotation interface.

**Type**: String

**Default**: `null` (no custom JavaScript)

**Example**:
```yaml
customjs: "http://localhost:8080/custom.js"
customjs_hostname: "localhost:8080"
```

**Usage**:
- `customjs`: URL or path to custom JavaScript file
- `customjs_hostname`: Hostname for custom JavaScript (if different from main server)

## Complete Configuration Example

Here's a complete example showing all UI configuration options:

```yaml
annotation_task_name: "Comprehensive UI Example"
task_dir: "my_task"
output_annotation_dir: "my_task/output"
data_files:
  - "data/my_data.json"
item_properties:
  id_key: "id"
  text_key: "text"

# Annotation schemes with inline colors
annotation_schemes:
  - annotation_type: radio
    annotation_id: 0
    name: sentiment
    description: "What is the overall sentiment of this text?"
    labels:
      - name: positive
        color: "#22C55E"
        tooltip: "The text expresses positive sentiment"
        key_value: p
      - name: negative
        color: "#EF4444"
        tooltip: "The text expresses negative sentiment"
        key_value: n
      - name: neutral
        color: "#9CA3AF"
        tooltip: "The text is neutral or mixed"
        key_value: u

  - annotation_type: span
    annotation_id: 1
    name: entities
    description: "Highlight named entities in the text."
    labels:
      - name: person
        color: "#3B82F6"
      - name: organization
        color: "#8B5CF6"
      - name: location
        color: "#10B981"

# UI Configuration
ui:
  # Instance text height control
  max_instance_height: 400

  # Global label colors (applies to all schemas)
  label_colors:
    sentiment:
      positive: "rgba(34, 197, 94, 0.8)"
      negative: "rgba(239, 68, 68, 0.8)"
      neutral: "rgba(156, 163, 175, 0.8)"
    entities:
      person: "#3B82F6"
      organization: "#8B5CF6"
      location: "#10B981"

  # Legacy span colors (still supported)
  spans:
    span_colors:
      entities:
        person: "(59, 130, 246)"
        organization: "(139, 92, 246)"
        location: "(16, 185, 129)"

  # Interface display options
  show_progress: true
  show_instructions: true
  allow_navigation: true
  allow_editing: true

# Optional: Custom task layout
# task_layout: "custom_layout.html"

# Site configuration
site_dir: "default"
customjs: null
customjs_hostname: null
```

## Browser Compatibility

All UI configuration options are designed to work across modern browsers:

- **Chrome/Edge**: Full support with custom scrollbar styling
- **Firefox**: Full support with standard scrollbar
- **Safari**: Full support with standard scrollbar
- **Mobile browsers**: Responsive design with touch-friendly interactions

## Best Practices

1. **Test Your Configuration**: Always test UI changes with your specific data and users
2. **Consider Accessibility**: Ensure color choices provide sufficient contrast
3. **Mobile Responsiveness**: Test configurations on mobile devices
4. **Performance**: Large custom JavaScript files may impact loading times
5. **Backup Templates**: Keep backups of custom templates before modifications

## Troubleshooting

### Common Issues

1. **Colors Not Appearing**: Ensure RGB format uses parentheses and spaces: `"(255, 128, 0)"`
2. **Height Limit Not Working**: Check that `max_instance_height` is a positive integer
3. **Custom Templates Not Loading**: Verify `site_dir` path exists and contains valid templates
4. **Custom JavaScript Errors**: Check browser console for JavaScript errors

### Debug Mode

Enable debug mode to see detailed configuration information:

```yaml
debug: true
```

This will log UI configuration details to help diagnose issues.
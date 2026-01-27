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

### 2. Span Annotation Colors

**Option**: `spans.span_colors`

**Description**: Defines custom colors for span annotation labels. Colors can be specified in RGB format `"(r, g, b)"` or hex format `"#RRGGBB"`.

**Type**: Object mapping schema names to label color mappings

**Default**: System-generated colors

**Example**:
```yaml
ui:
  spans:
    span_colors:
      sentiment:
        positive: "(220, 252, 231)"  # Light green
        negative: "(254, 226, 226)"  # Light red
        neutral: "(241, 245, 249)"   # Light gray
      emotion:
        happy: "#10B981"     # Green
        sad: "#3B82F6"       # Blue
        angry: "#DC2626"     # Red
```

**Color Format Support**:
- RGB format: `"(255, 128, 0)"` (automatically converted to hex)
- Hex format: `"#FF8000"`
- Named colors: `"red"`, `"blue"`, etc.

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

annotation_schemes:
  - annotation_type: "span"
    name: "sentiment"
    description: "Mark sentiment spans in the text."
    labels:
      - "positive"
      - "negative"
      - "neutral"

# UI Configuration
ui:
  # Instance text height control
  max_instance_height: 400

  # Span annotation colors
  spans:
    span_colors:
      sentiment:
        positive: "(220, 252, 231)"
        negative: "(254, 226, 226)"
        neutral: "(241, 245, 249)"

  # Interface display options
  show_progress: true
  show_instructions: true
  allow_navigation: true
  allow_editing: true

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
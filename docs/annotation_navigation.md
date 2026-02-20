# Annotation Navigation & Status Indicators

Potato provides navigation tools to help annotators efficiently move through their assigned items, including visual status indicators and skip-to-unannotated navigation buttons.

## Overview

The navigation system includes:
- **Previous/Next buttons**: Navigate sequentially through items
- **Status indicator**: Shows whether current item is labeled or not
- **Skip to unannotated**: Jump directly to the next/previous unannotated item
- **Progress counter**: Shows completed/total items
- **Go to index**: Jump directly to a specific item number

## Status Indicator

The status indicator appears in the navbar and shows whether the current instance has any annotations:

| Status | Display | Meaning |
|--------|---------|---------|
| Not labeled | Yellow badge | No annotations on this item |
| Labeled | Green badge | At least one annotation exists |

The status updates dynamically when annotations are added or removed.

## Skip to Unannotated Navigation

Two navigation buttons allow jumping directly to unannotated items:

- **Skip Backward** (`<<`): Jump to the previous unannotated item
- **Skip Forward** (`>>`): Jump to the next unannotated item

These buttons help annotators:
- Quickly find items they haven't completed
- Return to skipped items later
- Efficiently work through large batches

### Behavior

1. **Forward skip**: Searches from current position to end, then wraps to beginning
2. **Backward skip**: Searches from current position to beginning, then wraps to end
3. **All annotated**: Shows notification when no unannotated items remain

## Progress Counter

The progress counter shows: `Completed / Total`

For example, "15/50" means:
- 15 items have been annotated
- 50 total items are assigned

## Go To Specific Item

Use the number input field to jump directly to a specific item by its position:
1. Enter the item number (1-based index)
2. Press Enter or click Go
3. The page navigates to that item

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `→` or `Enter` | Go to next item |
| `←` | Go to previous item |

Note: Custom keybindings can be configured through the keyboard shortcuts system.

## Configuration

Navigation features are enabled by default. No additional configuration is required.

### Hiding Navigation Elements

To hide navigation elements (useful for crowdsourcing):

```yaml
hide_navbar: true  # Hides the entire navbar including navigation
```

### Custom Navigation Layout

For custom navigation layouts, modify the HTML template:

```yaml
html_layout: "path/to/custom_layout.html"
```

## How Status is Determined

An item is considered "labeled" if it has:
- At least one label annotation (radio, checkbox, likert, etc.), OR
- At least one span annotation

The status check happens server-side when the page loads.

## Implementation Details

### Server-Side

The navigation system uses methods in `user_state_management.py`:

- `find_next_unannotated_index()`: Finds next unannotated item forward
- `find_prev_unannotated_index()`: Finds previous unannotated item backward
- `get_annotated_instance_ids()`: Returns set of annotated item IDs
- `go_to_index(index)`: Navigates to specific item

### Client-Side

JavaScript functions in `annotation.js`:

- `navigateToNext()`: Go to next item
- `navigateToPrev()`: Go to previous item
- `jumpToUnannotated()`: Skip to next unannotated
- `jumpToUnannotatedPrev()`: Skip to previous unannotated

## Use Cases

### Efficient Batch Annotation

1. Annotate items sequentially
2. Skip difficult items using "Skip" option
3. Return to skipped items using "Skip Backward" button

### Quality Review

1. Navigate to specific item numbers reported for review
2. Use status indicator to verify annotation presence
3. Skip forward through already-reviewed items

### Crowdsourcing

1. Hide navbar for clean interface: `hide_navbar: true`
2. Use bottom navigation buttons only
3. Progress is still tracked server-side

## Troubleshooting

### Status Shows "Not Labeled" After Annotating

1. Ensure annotation was saved (check for confirmation)
2. Verify annotation input has a value
3. Check browser console for JavaScript errors

### Skip Button Not Working

1. Verify there are unannotated items remaining
2. Check for network errors in browser console
3. Ensure session is valid (try refreshing page)

### Progress Counter Not Updating

1. Navigation may be cached - refresh the page
2. Check that annotations are being saved successfully
3. Verify server logs for errors

## Best Practices

1. **Train annotators on navigation**: Show them how to use skip buttons efficiently

2. **Use for quality control**: Navigation tools help reviewers quickly find items

3. **Monitor progress**: The progress counter helps track annotation throughput

4. **Handle skipped items**: Use skip-to-unannotated to ensure all items are eventually completed

## Related Documentation

- [Task Assignment](task_assignment.md) - How items are assigned to annotators
- [UI Configuration](ui_configuration.md) - Interface customization options
- [Quality Control](quality_control.md) - Monitoring annotation quality

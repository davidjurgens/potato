# Layout Examples

This directory contains sophisticated example configurations demonstrating advanced visual design customization using `instance_display` combined with custom CSS layouts.

## Examples

### 1. Content Moderation Dashboard

A professional content review interface for evaluating potentially problematic content.

**Features:**
- Warning banner header with content metadata
- 2-column grid for violation category assessment
- Color-coded severity levels (green/yellow/red buttons)
- Final decision section with prominent action buttons
- Moderator notes field

**Run:**
```bash
python potato/flask_server.py start project-hub/layout-examples/content-moderation/config.yaml -p 8000
```

---

### 2. Customer Service Dialogue QA

A quality assessment interface for reviewing customer service conversations.

**Features:**
- Case header with metadata badges
- Overall assessment section with resolution/effort ratings
- Circular Likert-scale ratings for agent performance
- Quality issues checklist with visual indicators
- Recommendation section for training purposes

**Run:**
```bash
python potato/flask_server.py start project-hub/layout-examples/dialogue-qa/config.yaml -p 8000
```

---

### 3. Medical Image Review

A professional radiology review interface for structured medical reporting.

**Features:**
- Dark header with study metadata
- Primary finding assessment with large icon buttons
- Two-column layout for location and severity
- Finding characteristics grid
- Impression text area with structured placeholder
- Recommendation cards with descriptions

**Run:**
```bash
python potato/flask_server.py start project-hub/layout-examples/medical-review/config.yaml -p 8000
```

## Key Techniques Demonstrated

### Custom CSS Styling
- Grid and flexbox layouts
- Color-coded radio/checkbox buttons
- Section grouping with borders and backgrounds
- Responsive design with media queries

### Custom HTML Structure
- Section headers and dividers
- Icon integration (Unicode symbols)
- Card-based organization
- Inline labels and descriptions

### Integration with Instance Display
- Image display with zoom controls
- Dialogue display with speaker extraction
- Collapsible context sections
- Horizontal split layouts

## Creating Your Own Custom Layout

1. **Start with an example**: Copy one of these examples as a starting point
2. **Define your annotation schemes**: Add all needed schemes to `config.yaml`
3. **Create your layout HTML**: Match form IDs to scheme names
4. **Add custom CSS**: Style your interface to match your workflow
5. **Test thoroughly**: Verify all annotations save correctly

See [Layout Customization Guide](../../docs/layout_customization.md) for detailed documentation.

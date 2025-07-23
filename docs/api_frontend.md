# API-Based Frontend Interface

## Overview

The API-based frontend is a modern alternative to the traditional server-side rendered interface in Potato. It provides a single-page application (SPA) experience that communicates with the backend through REST API endpoints.

## Key Features

### Modern UI/UX
- **Responsive Design**: Built with Bootstrap 5 for mobile-friendly experience
- **Real-time Updates**: Instant feedback and auto-save functionality
- **Keyboard Shortcuts**: Efficient navigation and interaction
- **Progress Tracking**: Visual progress indicators and statistics
- **Error Handling**: Clear error messages and success notifications

### Technical Advantages
- **API-First Architecture**: Clean separation between frontend and backend
- **Single Page Application**: No page reloads during annotation
- **Modular Design**: Easy to extend and customize
- **Better Performance**: Reduced server load and faster interactions
- **Modern JavaScript**: ES6+ features and async/await patterns

## Architecture

### Frontend Components
```
api_frontend.html
├── Navigation Bar (Bootstrap navbar)
├── Main Container
│   ├── Progress Bar
│   ├── Annotation Card
│   │   ├── Instance Display
│   │   └── Dynamic Annotation Forms
│   └── Navigation Controls
├── Statistics Panel (Slide-out sidebar)
└── Keyboard Shortcuts (Floating panel)
```

### API Endpoints Used
- `GET /test/user_state/{username}` - Get current user state
- `POST /test/submit_annotation` - Submit annotations
- `POST /annotate` - Navigate between instances
- `GET /test/system_state` - Get system statistics
- `GET /test/health` - Health check

## Usage

### Starting the API Frontend

1. **Use the new route**: Navigate to `/api-frontend` instead of `/annotate`
2. **Same authentication**: Uses existing session management
3. **Same configuration**: Works with all existing Potato configs

### Example Configuration

```yaml
{
    "port": 9002,
    "annotation_task_name": "API Frontend Test",
    "debug": true,
    "annotation_schemes": [
        {
            "annotation_type": "radio",
            "name": "sentiment",
            "description": "What kind of sentiment does the given text hold?",
            "labels": ["positive", "neutral", "negative"]
        }
    ]
}
```

### Testing the API Frontend

```bash
# Set up test environment
python test_api_frontend.py

# Start server with test config
python -m potato.flask_server start test_api_frontend/config.yaml

# Access the frontend
# Open http://localhost:9002/api-frontend in your browser
```

## Supported Annotation Types

### Radio Buttons (Single Choice)
```javascript
// Generated HTML
<div class="radio-group">
    <div class="radio-option">
        <input type="radio" name="sentiment" value="positive">
        <label>positive</label>
    </div>
    <!-- ... more options -->
</div>
```

### Checkboxes (Multiple Choice)
```javascript
// Generated HTML
<div class="checkbox-group">
    <div class="checkbox-option">
        <input type="checkbox" name="topics" value="politics">
        <label>politics</label>
    </div>
    <!-- ... more options -->
</div>
```

### Text Input
```javascript
// Generated HTML
<label for="comments_input">Any additional comments?</label>
<textarea id="comments_input" name="comments" rows="3"></textarea>
```

### Likert Scale
```javascript
// Generated HTML
<div class="likert-scale">
    <div class="likert-option">
        <input type="radio" name="quality" value="1">
        <label>Very Poor</label>
    </div>
    <!-- ... more options -->
</div>
```

### Slider
```javascript
// Generated HTML
<div class="slider-container">
    <input type="range" class="slider-input" min="0" max="100" value="50">
    <div class="slider-labels">
        <span>Not at all</span>
        <span>Very much</span>
    </div>
</div>
```

### Number Input
```javascript
// Generated HTML
<label for="age_input">What is your age?</label>
<input type="number" id="age_input" name="age">
```

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `←` | Previous instance |
| `→` | Next instance |
| `S` | Open statistics panel |
| `Esc` | Close statistics panel |

## API Integration

### Loading User State
```javascript
async function loadUserState() {
    const response = await fetch('/test/user_state/username');
    const userState = await response.json();
    return userState;
}
```

### Submitting Annotations
```javascript
async function saveAnnotation() {
    const response = await fetch('/test/submit_annotation', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            instance_id: currentInstance.id,
            annotations: currentAnnotations,
            username: 'username'
        })
    });
    return response.json();
}
```

### Navigation
```javascript
async function navigateNext() {
    const response = await fetch('/annotate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'next_instance' })
    });
    // Reload page to get new instance
    window.location.reload();
}
```

## Customization

### Styling
The frontend uses CSS custom properties for easy theming:

```css
:root {
    --primary-color: #6e56cf;
    --secondary-color: #7c66ce;
    --accent-color: #a18fff;
    --dark-color: #09090b;
    --light-color: #fafafa;
    /* ... more variables */
}
```

### Adding New Annotation Types
1. Add the annotation type to `generateInputForScheme()`
2. Create the corresponding input generation function
3. Add event listeners in `setupSchemeEventListeners()`

### Extending Functionality
The modular JavaScript structure makes it easy to add features:

```javascript
// Add custom validation
function validateAnnotations() {
    // Custom validation logic
}

// Add custom UI components
function addCustomComponent() {
    // Custom component logic
}
```

## Comparison with Original Frontend

| Feature | Original Frontend | API Frontend |
|---------|------------------|--------------|
| Architecture | Server-side rendering | Single-page application |
| Performance | Page reloads | No reloads, faster |
| UI Framework | Custom CSS | Bootstrap 5 |
| JavaScript | jQuery-based | Modern ES6+ |
| Error Handling | Basic | Comprehensive |
| Extensibility | Limited | High |
| Mobile Support | Basic | Responsive |
| Real-time Updates | No | Yes |

## Benefits

### For Users
- **Faster Interaction**: No page reloads between instances
- **Better UX**: Modern, responsive interface
- **Real-time Feedback**: Immediate save confirmations
- **Keyboard Efficiency**: Comprehensive shortcuts

### For Developers
- **API-First**: Clean separation of concerns
- **Modern Stack**: Bootstrap 5, ES6+ JavaScript
- **Extensible**: Easy to add new features
- **Maintainable**: Modular, well-structured code

### For System Administrators
- **Reduced Server Load**: Less server-side processing
- **Better Scalability**: API endpoints can be cached/optimized
- **Easier Deployment**: Static frontend assets
- **Monitoring**: Clear API endpoint metrics

## Future Enhancements

### Planned Features
- **Real-time Collaboration**: Multiple users annotating simultaneously
- **Advanced Analytics**: Real-time statistics and insights
- **Custom Themes**: User-configurable appearance
- **Offline Support**: Work without internet connection
- **Mobile App**: Native mobile application

### Technical Improvements
- **WebSocket Support**: Real-time updates
- **Service Workers**: Offline functionality
- **Progressive Web App**: Installable web application
- **Advanced Caching**: Better performance optimization

## Troubleshooting

### Common Issues

**Frontend not loading**
- Check if server is running on correct port
- Verify debug mode is enabled
- Check browser console for JavaScript errors

**Annotations not saving**
- Verify API endpoints are accessible
- Check network tab for failed requests
- Ensure user is authenticated

**UI not responsive**
- Check Bootstrap CSS is loading
- Verify viewport meta tag is present
- Test on different screen sizes

### Debug Mode
Enable debug mode in config for easier troubleshooting:

```yaml
{
    "debug": true,
    "verbose": true
}
```

### Browser Compatibility
- Chrome 90+
- Firefox 88+
- Safari 14+
- Edge 90+

## Conclusion

The API-based frontend provides a modern, efficient alternative to the traditional Potato interface. It maintains full compatibility with existing configurations while offering significant improvements in user experience, performance, and extensibility.

For users who prefer the original interface, it remains fully functional and can be used alongside the new API frontend. The choice between interfaces can be made based on specific needs and preferences.
"""
Video Annotation Layout

Generates a form interface for video annotation with:
- Temporal segment marking (like audio annotation)
- Frame-level classification
- Keyframe annotation
- Object tracking across frames (basic support)

Uses Peaks.js for timeline visualization with synchronized video playback.

Features:
- Waveform/timeline visualization from video's audio track
- Video preview panel with frame counter
- Segment creation and labeling
- Frame-by-frame stepping (,/. keys)
- Multiple playback speeds (0.1x to 2.0x)
- Keyframe marking (K key)
"""

import logging
import json
from typing import List, Dict, Tuple, Any
from .identifier_utils import (
    safe_generate_layout,
    escape_html_content
)

logger = logging.getLogger(__name__)

# Default colors for segment/frame labels
DEFAULT_COLORS = [
    "#4ECDC4",  # Teal
    "#FF6B6B",  # Red
    "#45B7D1",  # Blue
    "#96CEB4",  # Green
    "#FFEAA7",  # Yellow
    "#DDA0DD",  # Plum
    "#95A5A6",  # Gray
    "#F39C12",  # Orange
    "#9B59B6",  # Purple
    "#3498DB",  # Light Blue
]

# Valid annotation modes
VALID_MODES = ["segment", "frame", "keyframe", "tracking", "combined"]


def generate_video_annotation_layout(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    """
    Generate HTML for a video annotation interface.

    Args:
        annotation_scheme (dict): Configuration including:
            - name: Schema identifier
            - description: Display description
            - mode: "segment" | "frame" | "keyframe" | "tracking" | "combined"
            - labels: List of labels (for segment/frame/keyframe modes)
            - segment_schemes: List of annotation schemes per segment (optional)
            - min_segments: Minimum required segments (default: 0)
            - max_segments: Maximum allowed segments (default: null/unlimited)
            - timeline_height: Height of timeline in pixels (default: 70)
            - overview_height: Height of overview bar (default: 40)
            - zoom_enabled: Whether to enable zoom (default: True)
            - playback_rate_control: Show playback speed controls (default: True)
            - frame_stepping: Enable frame-by-frame navigation (default: True)
            - show_timecode: Show timecode display (default: True)
            - video_fps: Frames per second for frame calculations (default: 30)

    Returns:
        tuple: (html_string, key_bindings)
            html_string: Complete HTML for the video annotation interface
            key_bindings: List of keyboard shortcuts

    Raises:
        ValueError: If required fields are missing or invalid
    """
    return safe_generate_layout(annotation_scheme, _generate_video_annotation_layout_internal)


def _generate_video_annotation_layout_internal(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    """
    Internal function to generate video annotation layout after validation.
    """
    schema_name = annotation_scheme.get('name', 'video_annotation')
    logger.debug(f"Generating video annotation layout for schema: {schema_name}")

    # Get mode (default to "segment")
    mode = annotation_scheme.get('mode', 'segment')
    if mode not in VALID_MODES:
        error_msg = f"Invalid mode '{mode}' in schema: {schema_name}. Must be one of: {VALID_MODES}"
        logger.error(error_msg)
        raise ValueError(error_msg)

    # Validate labels for segment/frame/keyframe/combined modes
    labels = []
    if mode in ['segment', 'frame', 'keyframe', 'combined']:
        if 'labels' not in annotation_scheme:
            error_msg = f"Missing labels in schema: {schema_name} (required for mode '{mode}')"
            logger.error(error_msg)
            raise ValueError(error_msg)
        labels = _process_labels(annotation_scheme['labels'])

    # Validate segment_schemes for combined mode
    segment_schemes = []
    if mode in ['combined'] and 'segment_schemes' in annotation_scheme:
        segment_schemes = annotation_scheme['segment_schemes']
        if not isinstance(segment_schemes, list):
            error_msg = f"segment_schemes must be a list in schema: {schema_name}"
            logger.error(error_msg)
            raise ValueError(error_msg)

    # Get configuration options
    min_segments = annotation_scheme.get('min_segments', 0)
    max_segments = annotation_scheme.get('max_segments', None)
    timeline_height = annotation_scheme.get('timeline_height', 70)
    overview_height = annotation_scheme.get('overview_height', 40)
    zoom_enabled = annotation_scheme.get('zoom_enabled', True)
    playback_rate_control = annotation_scheme.get('playback_rate_control', True)
    frame_stepping = annotation_scheme.get('frame_stepping', True)
    show_timecode = annotation_scheme.get('show_timecode', True)
    video_fps = annotation_scheme.get('video_fps', 30)

    # AI support configuration
    ai_support = annotation_scheme.get("ai_support", {})
    ai_enabled = ai_support.get("enabled", False)

    # Build config object for JavaScript
    js_config = {
        "schemaName": schema_name,
        "mode": mode,
        "labels": labels,
        "segmentSchemes": segment_schemes,
        "minSegments": min_segments,
        "maxSegments": max_segments,
        "timelineHeight": timeline_height,
        "overviewHeight": overview_height,
        "zoomEnabled": zoom_enabled,
        "playbackRateControl": playback_rate_control,
        "frameStepping": frame_stepping,
        "showTimecode": show_timecode,
        "videoFps": video_fps,
        "aiSupport": ai_enabled,
        "aiFeatures": ai_support.get("features", {}) if ai_enabled else {},
    }

    # Generate HTML
    html = _generate_html(annotation_scheme, js_config, schema_name, labels, mode, ai_enabled, ai_support)

    # Generate keybindings
    keybindings = _generate_keybindings(labels, mode, frame_stepping)

    logger.info(f"Successfully generated video annotation layout for {schema_name}")
    return html, keybindings


def _process_labels(labels_config: List) -> List[Dict[str, Any]]:
    """
    Process label configuration and assign colors.

    Args:
        labels_config: List of label configs (strings or dicts)

    Returns:
        List of processed label dicts with name, color, and optional key_value
    """
    processed = []
    for i, label in enumerate(labels_config):
        if isinstance(label, str):
            processed.append({
                "name": label,
                "color": DEFAULT_COLORS[i % len(DEFAULT_COLORS)],
            })
        elif isinstance(label, dict):
            processed.append({
                "name": label.get("name", f"label_{i}"),
                "color": label.get("color", DEFAULT_COLORS[i % len(DEFAULT_COLORS)]),
                "key_value": label.get("key_value"),
            })
        else:
            processed.append({
                "name": str(label),
                "color": DEFAULT_COLORS[i % len(DEFAULT_COLORS)],
            })
    return processed


def _generate_html(
    annotation_scheme: Dict[str, Any],
    js_config: Dict[str, Any],
    schema_name: str,
    labels: List[Dict[str, Any]],
    mode: str,
    ai_enabled: bool = False,
    ai_support: Dict[str, Any] = None
) -> str:
    """
    Generate the HTML for the video annotation interface.
    """
    escaped_name = escape_html_content(schema_name)
    description = escape_html_content(annotation_scheme.get('description', ''))
    config_json = json.dumps(js_config)
    timeline_height = js_config.get('timelineHeight', 70)
    overview_height = js_config.get('overviewHeight', 40)

    # Generate label buttons
    label_selector = ""
    if labels:
        label_selector = _generate_label_selector(labels)

    # Generate AI toolbar if enabled
    ai_toolbar_html = ""
    ai_init_script = ""
    if ai_enabled:
        ai_features = ai_support.get("features", {}) if ai_support else {}
        ai_toolbar_html = _generate_video_ai_toolbar(ai_features, mode)
        ai_init_script = _generate_video_ai_init_script(escaped_name)

    # Generate playback rate control
    playback_rate_html = ""
    if js_config.get('playbackRateControl'):
        playback_rate_html = '''
            <div class="playback-rate-group">
                <span class="tool-group-label">Speed:</span>
                <select class="playback-rate-select">
                    <option value="0.1">0.1x</option>
                    <option value="0.25">0.25x</option>
                    <option value="0.5">0.5x</option>
                    <option value="0.75">0.75x</option>
                    <option value="1" selected>1x</option>
                    <option value="1.25">1.25x</option>
                    <option value="1.5">1.5x</option>
                    <option value="2">2x</option>
                </select>
            </div>
        '''

    # Generate frame stepping controls
    frame_stepping_html = ""
    if js_config.get('frameStepping'):
        frame_stepping_html = '''
            <div class="frame-stepping-group">
                <button type="button" class="frame-btn" data-action="frame-back" title="Step back one frame for precise positioning (Keyboard: ,)">|&lt;</button>
                <button type="button" class="frame-btn" data-action="frame-forward" title="Step forward one frame for precise positioning (Keyboard: .)">|&gt;</button>
            </div>
        '''

    # Generate mode-specific controls
    mode_controls_html = ""
    if mode in ['keyframe', 'combined']:
        mode_controls_html += '''
            <div class="keyframe-group">
                <button type="button" class="keyframe-btn" data-action="mark-keyframe" title="Mark Keyframe (K)">Mark Keyframe</button>
            </div>
        '''
    if mode in ['frame', 'combined']:
        mode_controls_html += '''
            <div class="frame-classify-group">
                <button type="button" class="frame-classify-btn" data-action="classify-frame" title="Classify Current Frame (C)">Classify Frame</button>
            </div>
        '''

    # Generate timecode display
    timecode_html = ""
    if js_config.get('showTimecode'):
        timecode_html = '''
            <div class="timecode-display">
                <span class="frame-number">Frame: <span class="frame-value">0</span></span>
                <span class="timecode">00:00:00.000</span>
            </div>
        '''

    html = f'''
    <form id="{escaped_name}" class="annotation-form video-annotation" action="/action_page.php">
        <fieldset schema="{escaped_name}">
            <legend>{description}</legend>

            <!-- Video Annotation Container -->
            <div class="video-annotation-container" data-schema="{escaped_name}" data-mode="{mode}">
                <!-- Video Preview Panel -->
                <div class="video-preview-panel">
                    <video id="video-{escaped_name}" class="video-element" controls></video>
                    <div class="video-overlay">
                        {timecode_html}
                    </div>
                    <!-- Tracking canvas overlay (for tracking mode) -->
                    <canvas id="tracking-canvas-{escaped_name}" class="tracking-overlay" style="display: none;"></canvas>
                </div>

                <!-- Instructions panel (collapsible) -->
                <details class="video-instructions" style="margin-bottom: 0.75rem; padding: 0.5rem 0.75rem; background: #f0f9ff; border: 1px solid #bae6fd; border-radius: 0.375rem; font-size: 0.8rem;">
                    <summary style="cursor: pointer; font-weight: 600; color: #0369a1;">How to annotate video segments (click to expand)</summary>
                    <div style="margin-top: 0.5rem; color: #475569; line-height: 1.5;">
                        <p style="margin: 0.25rem 0;"><strong>To create a segment:</strong></p>
                        <ol style="margin: 0.25rem 0 0.5rem 1.25rem; padding: 0;">
                            <li>Select a label (colored buttons below)</li>
                            <li>Play/scrub video to the start point, then click <kbd>[</kbd> or press the [ key</li>
                            <li>Move to the end point, then click <kbd>]</kbd> or press the ] key</li>
                            <li>Click <kbd>+ Segment</kbd> or press Enter to create the segment</li>
                        </ol>
                        <p style="margin: 0.25rem 0;"><strong>Timeline controls:</strong> <kbd>+</kbd> zoom in, <kbd>-</kbd> zoom out, <kbd>Fit</kbd> show entire video</p>
                        <p style="margin: 0.25rem 0;"><strong>Playback:</strong> <kbd>Space</kbd> play/pause, <kbd>&#9664;&#9654;</kbd> frame step, change speed with dropdown</p>
                    </div>
                </details>

                <!-- Toolbar -->
                <div class="video-annotation-toolbar">
                    <!-- Playback controls -->
                    <div class="playback-group">
                        <button type="button" class="playback-btn" data-action="play" title="Play or pause the video (Keyboard: Space)">
                            <span class="play-icon">&#9654;</span>
                            <span class="pause-icon" style="display:none;">&#9208;</span>
                        </button>
                        <button type="button" class="playback-btn" data-action="stop" title="Stop playback and return to start">&#9209;</button>
                        {frame_stepping_html}
                        <span class="time-display">
                            <span class="current-time">0:00</span> / <span class="total-time">0:00</span>
                        </span>
                    </div>

                    {playback_rate_html}

                    <!-- Label selector -->
                    {label_selector}

                    <!-- Mode-specific controls -->
                    {mode_controls_html}

                    <!-- Zoom controls -->
                    <div class="zoom-group" title="Timeline zoom controls">
                        <button type="button" class="zoom-btn" data-action="zoom-in" title="Zoom in on timeline to see more detail (Keyboard: +)">+</button>
                        <button type="button" class="zoom-btn" data-action="zoom-out" title="Zoom out on timeline to see more of the video (Keyboard: -)">-</button>
                        <button type="button" class="zoom-btn" data-action="zoom-fit" title="Fit entire video duration in timeline view (Keyboard: 0)">Fit</button>
                    </div>

                    <!-- Segment controls -->
                    <div class="segment-group" title="Segment creation controls">
                        <button type="button" class="segment-btn" data-action="set-start" title="Mark the START of a new segment at current video position (Keyboard: [)">[</button>
                        <button type="button" class="segment-btn" data-action="set-end" title="Mark the END of a new segment at current video position (Keyboard: ])">]</button>
                        <button type="button" class="segment-btn" data-action="create-segment" title="Create a segment from marked start/end points with selected label (Keyboard: Enter)">+ Segment</button>
                        <button type="button" class="segment-btn delete-btn" data-action="delete-segment" title="Delete the currently selected segment (Keyboard: Delete)" disabled>Delete</button>
                    </div>

                    <!-- Annotation count -->
                    <div class="count-group">
                        <span class="segment-count">Segments: <span class="count-value">0</span></span>
                    </div>
                </div>

                {ai_toolbar_html}

                <!-- Timeline (Peaks.js) -->
                <div class="timeline-wrapper">
                    <div id="zoomview-{escaped_name}" class="timeline-container" style="height: {timeline_height}px;"></div>
                    <div id="overview-{escaped_name}" class="overview-container" style="height: {overview_height}px;"></div>
                </div>

                <!-- Annotation list -->
                <div class="annotation-list-container">
                    <h4>Annotations</h4>
                    <div id="annotation-list-{escaped_name}" class="annotation-list"></div>
                </div>

                <!-- Segment questions panel (for combined mode) -->
                <div id="segment-questions-{escaped_name}" class="segment-questions-panel" style="display: none;">
                    <h4>Segment Details</h4>
                    <div class="segment-questions-content"></div>
                </div>

                <!-- Hidden input for storing annotation data -->
                <!-- autocomplete="off" prevents Firefox from restoring old values on reload -->
                <input type="hidden"
                       name="{escaped_name}"
                       id="input-{escaped_name}"
                       class="annotation-data-input"
                       autocomplete="off"
                       value="">

            </div>

            <!-- Initialize the annotation manager -->
            <script>
                (function() {{
                    // Guard against multiple initializations
                    var initKey = '__videoAnnotationInit_{escaped_name}';
                    if (window[initKey]) {{
                        console.log('[VideoAnnotation INIT] Already initialized, skipping');
                        return;
                    }}
                    window[initKey] = true;

                    console.log('[VideoAnnotation INIT] Script starting for schema: {escaped_name}');

                    function initWhenReady() {{
                        // Only wait for VideoAnnotationManager - Peaks is optional
                        if (typeof VideoAnnotationManager === 'undefined') {{
                            setTimeout(initWhenReady, 100);
                            return;
                        }}

                        console.log('[VideoAnnotation INIT] VideoAnnotationManager ready, Peaks available:', typeof Peaks !== 'undefined');

                        var container = document.querySelector('.video-annotation-container[data-schema="{escaped_name}"]');
                        if (!container) {{
                            console.error('[VideoAnnotation INIT] Container not found!');
                            return;
                        }}

                        // Check if already initialized on this container
                        if (container.videoAnnotationManager) {{
                            console.log('[VideoAnnotation INIT] Container already has manager, skipping');
                            return;
                        }}

                        console.log('[VideoAnnotation INIT] Initializing video annotation...');

                        var config = {config_json};
                        var videoId = 'video-{escaped_name}';
                        var zoomviewId = 'zoomview-{escaped_name}';
                        var overviewId = 'overview-{escaped_name}';
                        var inputId = 'input-{escaped_name}';
                        var annotationListId = 'annotation-list-{escaped_name}';
                        var questionsId = 'segment-questions-{escaped_name}';
                        var trackingCanvasId = 'tracking-canvas-{escaped_name}';

                        // Get video URL from the instance display
                        // Try multiple possible element IDs (hyphen and underscore variants)
                        var textContent = document.getElementById('text-content');
                        var instanceText = document.getElementById('instance-text');
                        var instanceTextUnderscore = document.getElementById('instance_text');

                        console.log('[VideoAnnotation DEBUG] Looking for video URL...');
                        console.log('[VideoAnnotation DEBUG] text-content element:', textContent);
                        console.log('[VideoAnnotation DEBUG] instance-text element:', instanceText);
                        console.log('[VideoAnnotation DEBUG] instance_text element:', instanceTextUnderscore);

                        var instanceContainer = textContent || instanceText || instanceTextUnderscore;
                        var videoUrl = null;

                        // Try to find video URL in instance text
                        if (instanceContainer) {{
                            var text = instanceContainer.textContent || instanceContainer.innerText;
                            console.log('[VideoAnnotation DEBUG] Container text content (first 200 chars):', text ? text.substring(0, 200) : 'EMPTY');

                            // Check if it's a URL
                            if (text && (text.trim().startsWith('http') || text.trim().endsWith('.mp4') || text.trim().endsWith('.webm') || text.trim().endsWith('.ogg'))) {{
                                videoUrl = text.trim();
                                console.log('[VideoAnnotation DEBUG] Found video URL:', videoUrl);
                            }}
                            // Check for video element
                            var videoEl = instanceContainer.querySelector('video');
                            if (videoEl && videoEl.src) {{
                                videoUrl = videoEl.src;
                                console.log('[VideoAnnotation DEBUG] Found video element with src:', videoUrl);
                            }}
                        }} else {{
                            console.error('[VideoAnnotation DEBUG] No instance container found!');
                        }}

                        // Debug: Log if video URL not found
                        if (!videoUrl) {{
                            console.error('[VideoAnnotation ERROR] Could not find video URL!');
                            // Show visible error message
                            var errorDiv = document.createElement('div');
                            errorDiv.style.cssText = 'background: #fee2e2; border: 2px solid #ef4444; color: #dc2626; padding: 1rem; margin: 1rem 0; border-radius: 0.5rem;';
                            errorDiv.innerHTML = '<strong>Video URL not found!</strong><br>Check browser console for details.';
                            container.insertBefore(errorDiv, container.firstChild);
                        }} else {{
                            console.log('[VideoAnnotation DEBUG] Video URL found:', videoUrl);
                        }}

                        // Check if video element exists
                        var videoElement = document.getElementById(videoId);
                        console.log('[VideoAnnotation DEBUG] Video element ID:', videoId);
                        console.log('[VideoAnnotation DEBUG] Video element found:', videoElement);

                        if (!videoElement) {{
                            console.error('[VideoAnnotation ERROR] Video element not found!');
                            var errorDiv = document.createElement('div');
                            errorDiv.style.cssText = 'background: #fee2e2; border: 2px solid #ef4444; color: #dc2626; padding: 1rem; margin: 1rem 0; border-radius: 0.5rem;';
                            errorDiv.innerHTML = '<strong>Video element not found!</strong><br>Expected element with ID: ' + videoId;
                            container.insertBefore(errorDiv, container.firstChild);
                            return;
                        }}

                        // Initialize manager
                        var manager = new VideoAnnotationManager({{
                            container: container,
                            videoId: videoId,
                            zoomviewId: zoomviewId,
                            overviewId: overviewId,
                            inputId: inputId,
                            annotationListId: annotationListId,
                            questionsId: questionsId,
                            trackingCanvasId: trackingCanvasId,
                            config: config
                        }});

                        // Store reference on container
                        container.videoAnnotationManager = manager;

                        // Load video if available
                        if (videoUrl) {{
                            console.log('[VideoAnnotation DEBUG] Calling manager.loadVideo with URL:', videoUrl);
                            manager.loadVideo(videoUrl);
                        }} else {{
                            console.error('[VideoAnnotation ERROR] No video URL to load!');
                        }}

                        // Wire up toolbar buttons
                        container.querySelectorAll('.playback-btn').forEach(function(btn) {{
                            btn.addEventListener('click', function() {{
                                var action = this.dataset.action;
                                if (action === 'play') manager.togglePlayPause();
                                else if (action === 'stop') manager.stop();
                            }});
                        }});

                        container.querySelectorAll('.frame-btn').forEach(function(btn) {{
                            btn.addEventListener('click', function() {{
                                var action = this.dataset.action;
                                if (action === 'frame-back') manager.stepFrameBackward();
                                else if (action === 'frame-forward') manager.stepFrameForward();
                            }});
                        }});

                        container.querySelectorAll('.label-btn').forEach(function(btn) {{
                            btn.addEventListener('click', function() {{
                                var label = this.dataset.label;
                                var color = this.dataset.color;
                                manager.setActiveLabel(label, color);
                                container.querySelectorAll('.label-btn').forEach(function(b) {{
                                    b.classList.remove('active');
                                }});
                                this.classList.add('active');
                            }});
                        }});

                        container.querySelectorAll('.zoom-btn').forEach(function(btn) {{
                            btn.addEventListener('click', function() {{
                                var action = this.dataset.action;
                                if (action === 'zoom-in') manager.zoomIn();
                                else if (action === 'zoom-out') manager.zoomOut();
                                else if (action === 'zoom-fit') manager.zoomToFit();
                            }});
                        }});

                        container.querySelectorAll('.segment-btn').forEach(function(btn) {{
                            btn.addEventListener('click', function() {{
                                var action = this.dataset.action;
                                if (action === 'set-start') manager.setSelectionStart();
                                else if (action === 'set-end') manager.setSelectionEnd();
                                else if (action === 'create-segment') manager.createSegmentFromSelection();
                                else if (action === 'delete-segment') manager.deleteSelectedAnnotation();
                            }});
                        }});

                        container.querySelectorAll('.keyframe-btn').forEach(function(btn) {{
                            btn.addEventListener('click', function() {{
                                manager.markKeyframe(manager.activeLabel);
                            }});
                        }});

                        container.querySelectorAll('.frame-classify-btn').forEach(function(btn) {{
                            btn.addEventListener('click', function() {{
                                manager.classifyCurrentFrame(manager.activeLabel, manager.activeLabelColor);
                            }});
                        }});

                        // Playback rate control
                        var rateSelect = container.querySelector('.playback-rate-select');
                        if (rateSelect) {{
                            rateSelect.addEventListener('change', function() {{
                                manager.setPlaybackRate(parseFloat(this.value));
                            }});
                        }}

                        // Set default label
                        var firstLabelBtn = container.querySelector('.label-btn');
                        if (firstLabelBtn) firstLabelBtn.click();

                        {ai_init_script}
                    }}

                    if (document.readyState === 'loading') {{
                        document.addEventListener('DOMContentLoaded', initWhenReady);
                    }} else {{
                        initWhenReady();
                    }}
                }})();
            </script>
        </fieldset>
    </form>
    '''

    return html


def _generate_video_ai_toolbar(ai_features: Dict[str, Any], mode: str) -> str:
    """
    Generate HTML for the video AI assistance toolbar.
    """
    scene_detection_enabled = ai_features.get("scene_detection", True)
    frame_classification_enabled = ai_features.get("frame_classification", False)
    keyframe_detection_enabled = ai_features.get("keyframe_detection", False)
    tracking_enabled = ai_features.get("tracking", False)
    pre_annotate_enabled = ai_features.get("pre_annotate", True)
    hint_enabled = ai_features.get("hint", True)

    buttons = []

    if scene_detection_enabled and mode in ['segment', 'combined']:
        buttons.append(
            '<button type="button" class="ai-btn" data-action="scene_detection" title="Detect scene boundaries">'
            '<span class="ai-btn-icon">🎬</span> Scenes</button>'
        )

    if pre_annotate_enabled:
        buttons.append(
            '<button type="button" class="ai-btn" data-action="pre_annotate" title="Auto-segment the entire video">'
            '<span class="ai-btn-icon">⚡</span> Auto</button>'
        )

    if frame_classification_enabled and mode in ['frame', 'combined']:
        buttons.append(
            '<button type="button" class="ai-btn" data-action="frame_classification" title="Classify current frame">'
            '<span class="ai-btn-icon">🏷️</span> Classify</button>'
        )

    if keyframe_detection_enabled and mode in ['keyframe', 'combined']:
        buttons.append(
            '<button type="button" class="ai-btn" data-action="keyframe_detection" title="Detect keyframes">'
            '<span class="ai-btn-icon">📍</span> Keyframes</button>'
        )

    if tracking_enabled and mode == 'tracking':
        buttons.append(
            '<button type="button" class="ai-btn" data-action="tracking_suggestion" title="Get tracking suggestions">'
            '<span class="ai-btn-icon">👁️</span> Track</button>'
        )

    if hint_enabled:
        buttons.append(
            '<button type="button" class="ai-btn" data-action="hint" title="Get a hint for annotation">'
            '<span class="ai-btn-icon">💡</span> Hint</button>'
        )

    if not buttons:
        return ""

    return f'''
                <!-- AI Assistance Toolbar -->
                <div class="ai-toolbar">
                    <div class="ai-toolbar-group">
                        <span class="ai-toolbar-label">AI Assist:</span>
                        {" ".join(buttons)}
                    </div>
                    <div class="ai-suggestion-controls" style="display: none;">
                        <span class="suggestion-count">0 suggestions</span>
                        <button type="button" class="ai-btn ai-btn-accept" data-action="accept-all" title="Accept all suggestions">
                            Accept All
                        </button>
                        <button type="button" class="ai-btn ai-btn-clear" data-action="clear" title="Clear all suggestions">
                            Clear
                        </button>
                    </div>
                    <div class="ai-loading-indicator" style="display: none;">
                        <span class="spinner"></span> Loading...
                    </div>
                </div>
                <!-- AI Tooltip Container -->
                <div class="ai-tooltip-container" style="display: none;"></div>
    '''


def _generate_video_ai_init_script(escaped_name: str) -> str:
    """
    Generate JavaScript initialization code for video AI assistant.
    """
    return f'''
                        // Initialize AI assistant if enabled and VisualAIAssistantManager is available
                        if (config.aiSupport && typeof VisualAIAssistantManager !== 'undefined') {{
                            var annotationId = Array.from(document.querySelectorAll('.annotation-form')).indexOf(
                                document.getElementById('{escaped_name}')
                            );
                            container.aiAssistant = new VisualAIAssistantManager({{
                                annotationType: 'video_annotation',
                                annotationId: annotationId >= 0 ? annotationId : 0,
                                annotationManager: manager
                            }});
                        }}
    '''


def _generate_label_selector(labels: List[Dict[str, Any]]) -> str:
    """
    Generate HTML for label selection buttons.
    """
    import html
    buttons = []
    for label in labels:
        # Escape for both content and attributes
        name_escaped = escape_html_content(label["name"])
        name_attr = html.escape(label["name"], quote=True)
        color = label["color"]
        key_hint = f' ({label["key_value"]})' if label.get("key_value") else ""
        key_hint_escaped = html.escape(key_hint, quote=True)
        buttons.append(
            f'<button type="button" class="label-btn" data-label="{name_attr}" data-color="{color}" '
            f'title="{name_attr}{key_hint_escaped}" style="--label-color: {color};">'
            f'<span class="label-color-dot" style="background-color: {color};"></span>'
            f'{name_escaped}</button>'
        )

    return f'''
        <div class="label-group">
            <span class="tool-group-label">Label:</span>
            {"".join(buttons)}
        </div>
    '''


def _generate_keybindings(labels: List[Dict[str, Any]], mode: str, frame_stepping: bool) -> List[Tuple[str, str]]:
    """
    Generate keybinding list for the schema.
    """
    keybindings = []

    # Playback shortcuts
    keybindings.append(("Space", "Play/Pause"))
    keybindings.append(("Left/Right", "Seek 5 seconds"))

    # Frame stepping
    if frame_stepping:
        keybindings.append((",", "Previous frame"))
        keybindings.append((".", "Next frame"))

    # Label shortcuts
    for label in labels:
        if label.get("key_value"):
            keybindings.append((label["key_value"], f"Select: {label['name']}"))

    # Segment shortcuts
    if mode in ['segment', 'combined']:
        keybindings.append(("[", "Set segment start"))
        keybindings.append(("]", "Set segment end"))
        keybindings.append(("Enter", "Create segment"))

    # Keyframe shortcut
    if mode in ['keyframe', 'combined']:
        keybindings.append(("K", "Mark keyframe"))

    # Frame classification
    if mode in ['frame', 'combined']:
        keybindings.append(("C", "Classify current frame"))

    # Delete shortcut
    keybindings.append(("Del", "Delete selected"))

    # Zoom shortcuts
    keybindings.append(("+/-", "Zoom in/out"))
    keybindings.append(("0", "Fit to view"))

    return keybindings

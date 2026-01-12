"""
Audio Annotation Layout

Generates a form interface for audio annotation with segmentation.
Uses Peaks.js for waveform visualization and segment management.

Features:
- Waveform visualization (amplitude display)
- Region/segment selection and playback
- Zoom and pan for long audio files
- Two annotation modes:
  - Label mode: Assign labels to segments (like span annotation)
  - Questions mode: Answer questions about each segment (radio, multirate, etc.)
"""

import logging
import json
from typing import List, Dict, Tuple, Any
from .identifier_utils import (
    safe_generate_layout,
    escape_html_content
)

logger = logging.getLogger(__name__)

# Default colors for segment labels
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
VALID_MODES = ["label", "questions", "both"]


def generate_audio_annotation_layout(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    """
    Generate HTML for an audio annotation interface.

    Args:
        annotation_scheme (dict): Configuration including:
            - name: Schema identifier
            - description: Display description
            - mode: "label" | "questions" | "both"
            - labels: List of segment labels (for label/both modes)
            - segment_schemes: List of annotation schemes per segment (for questions/both modes)
            - min_segments: Minimum required segments (default: 0)
            - max_segments: Maximum allowed segments (default: null/unlimited)
            - zoom_enabled: Whether to enable zoom (default: True)
            - playback_rate_control: Show playback speed controls (default: False)

    Returns:
        tuple: (html_string, key_bindings)
            html_string: Complete HTML for the audio annotation interface
            key_bindings: List of keyboard shortcuts

    Raises:
        ValueError: If required fields are missing or invalid
    """
    return safe_generate_layout(annotation_scheme, _generate_audio_annotation_layout_internal)


def _generate_audio_annotation_layout_internal(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    """
    Internal function to generate audio annotation layout after validation.
    """
    schema_name = annotation_scheme.get('name', 'audio_annotation')
    logger.debug(f"Generating audio annotation layout for schema: {schema_name}")

    # Get mode (default to "label" for simplicity)
    mode = annotation_scheme.get('mode', 'label')
    if mode not in VALID_MODES:
        error_msg = f"Invalid mode '{mode}' in schema: {schema_name}. Must be one of: {VALID_MODES}"
        logger.error(error_msg)
        raise ValueError(error_msg)

    # Validate labels for label/both modes
    labels = []
    if mode in ['label', 'both']:
        if 'labels' not in annotation_scheme:
            error_msg = f"Missing labels in schema: {schema_name} (required for mode '{mode}')"
            logger.error(error_msg)
            raise ValueError(error_msg)
        labels = _process_labels(annotation_scheme['labels'])

    # Validate segment_schemes for questions/both modes
    segment_schemes = []
    if mode in ['questions', 'both']:
        if 'segment_schemes' not in annotation_scheme:
            error_msg = f"Missing segment_schemes in schema: {schema_name} (required for mode '{mode}')"
            logger.error(error_msg)
            raise ValueError(error_msg)
        segment_schemes = annotation_scheme['segment_schemes']
        if not isinstance(segment_schemes, list) or not segment_schemes:
            error_msg = f"segment_schemes must be a non-empty list in schema: {schema_name}"
            logger.error(error_msg)
            raise ValueError(error_msg)

    # Get configuration options
    min_segments = annotation_scheme.get('min_segments', 0)
    max_segments = annotation_scheme.get('max_segments', None)
    zoom_enabled = annotation_scheme.get('zoom_enabled', True)
    playback_rate_control = annotation_scheme.get('playback_rate_control', False)

    # Build config object for JavaScript
    js_config = {
        "schemaName": schema_name,
        "mode": mode,
        "labels": labels,
        "segmentSchemes": segment_schemes,
        "minSegments": min_segments,
        "maxSegments": max_segments,
        "zoomEnabled": zoom_enabled,
        "playbackRateControl": playback_rate_control,
    }

    # Generate HTML
    html = _generate_html(annotation_scheme, js_config, schema_name, labels, mode)

    # Generate keybindings
    keybindings = _generate_keybindings(labels, mode)

    logger.info(f"Successfully generated audio annotation layout for {schema_name}")
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
    mode: str
) -> str:
    """
    Generate the HTML for the audio annotation interface.
    """
    escaped_name = escape_html_content(schema_name)
    description = escape_html_content(annotation_scheme.get('description', ''))
    config_json = json.dumps(js_config)

    # Generate label buttons (for label/both modes)
    label_selector = ""
    if mode in ['label', 'both'] and labels:
        label_selector = _generate_label_selector(labels)

    # Generate playback rate control
    playback_rate_html = ""
    if js_config.get('playbackRateControl'):
        playback_rate_html = '''
            <div class="playback-rate-group">
                <span class="tool-group-label">Speed:</span>
                <select class="playback-rate-select">
                    <option value="0.5">0.5x</option>
                    <option value="0.75">0.75x</option>
                    <option value="1" selected>1x</option>
                    <option value="1.25">1.25x</option>
                    <option value="1.5">1.5x</option>
                    <option value="2">2x</option>
                </select>
            </div>
        '''

    html = f'''
    <form id="{escaped_name}" class="annotation-form audio-annotation" action="/action_page.php">
        <fieldset schema="{escaped_name}">
            <legend>{description}</legend>

            <!-- Audio Annotation Container -->
            <div class="audio-annotation-container" data-schema="{escaped_name}">
                <!-- Toolbar -->
                <div class="audio-annotation-toolbar">
                    <!-- Playback controls -->
                    <div class="playback-group">
                        <button type="button" class="playback-btn" data-action="play" title="Play/Pause (Space)">
                            <span class="play-icon">▶</span>
                            <span class="pause-icon" style="display:none;">⏸</span>
                        </button>
                        <button type="button" class="playback-btn" data-action="stop" title="Stop">⏹</button>
                        <span class="time-display">
                            <span class="current-time">0:00</span> / <span class="total-time">0:00</span>
                        </span>
                    </div>

                    {playback_rate_html}

                    <!-- Label selector (for label/both modes) -->
                    {label_selector}

                    <!-- Zoom controls -->
                    <div class="zoom-group">
                        <button type="button" class="zoom-btn" data-action="zoom-in" title="Zoom In (+)">+</button>
                        <button type="button" class="zoom-btn" data-action="zoom-out" title="Zoom Out (-)">-</button>
                        <button type="button" class="zoom-btn" data-action="zoom-fit" title="Fit to View (0)">Fit</button>
                    </div>

                    <!-- Segment controls -->
                    <div class="segment-group">
                        <button type="button" class="segment-btn" data-action="create-segment" title="Create Segment from Selection (Enter)">+ Segment</button>
                        <button type="button" class="segment-btn delete-btn" data-action="delete-segment" title="Delete Selected (Del)" disabled>Delete</button>
                    </div>

                    <!-- Segment count -->
                    <div class="count-group">
                        <span class="segment-count">Segments: <span class="count-value">0</span></span>
                    </div>
                </div>

                <!-- Waveform container -->
                <div class="waveform-wrapper">
                    <div id="waveform-{escaped_name}" class="waveform-container"></div>
                    <div id="overview-{escaped_name}" class="overview-container"></div>
                </div>

                <!-- Segment list -->
                <div class="segment-list-container">
                    <h4>Segments</h4>
                    <div id="segment-list-{escaped_name}" class="segment-list"></div>
                </div>

                <!-- Segment questions panel (for questions/both modes) -->
                <div id="segment-questions-{escaped_name}" class="segment-questions-panel" style="display: none;">
                    <h4>Segment Details</h4>
                    <div class="segment-questions-content"></div>
                </div>

                <!-- Hidden input for storing annotation data -->
                <input type="hidden"
                       name="{escaped_name}"
                       id="input-{escaped_name}"
                       class="annotation-data-input"
                       value="">

                <!-- Hidden audio element -->
                <audio id="audio-{escaped_name}" style="display: none;"></audio>
            </div>

            <!-- Initialize the annotation manager -->
            <script>
                (function() {{
                    function initWhenReady() {{
                        if (typeof AudioAnnotationManager === 'undefined' || typeof Peaks === 'undefined') {{
                            setTimeout(initWhenReady, 100);
                            return;
                        }}
                        var container = document.querySelector('.audio-annotation-container[data-schema="{escaped_name}"]');
                        if (!container) return;

                        var config = {config_json};
                        var waveformId = 'waveform-{escaped_name}';
                        var overviewId = 'overview-{escaped_name}';
                        var audioId = 'audio-{escaped_name}';
                        var inputId = 'input-{escaped_name}';
                        var segmentListId = 'segment-list-{escaped_name}';
                        var questionsId = 'segment-questions-{escaped_name}';

                        // Get audio URL from the instance display
                        var instanceContainer = document.getElementById('instance_text') || document.getElementById('text-content');
                        var audioUrl = null;

                        // Try to find audio URL in instance text
                        if (instanceContainer) {{
                            var text = instanceContainer.textContent || instanceContainer.innerText;
                            // Check if it's a URL
                            if (text && (text.trim().startsWith('http') || text.trim().endsWith('.mp3') || text.trim().endsWith('.wav'))) {{
                                audioUrl = text.trim();
                            }}
                            // Check for audio element
                            var audioEl = instanceContainer.querySelector('audio');
                            if (audioEl && audioEl.src) {{
                                audioUrl = audioEl.src;
                            }}
                        }}

                        // Initialize manager
                        var manager = new AudioAnnotationManager({{
                            container: container,
                            waveformId: waveformId,
                            overviewId: overviewId,
                            audioId: audioId,
                            inputId: inputId,
                            segmentListId: segmentListId,
                            questionsId: questionsId,
                            config: config
                        }});

                        // Store reference on container
                        container.audioAnnotationManager = manager;

                        // Load audio if available
                        if (audioUrl) {{
                            manager.loadAudio(audioUrl);
                        }}

                        // Wire up toolbar buttons
                        container.querySelectorAll('.playback-btn').forEach(function(btn) {{
                            btn.addEventListener('click', function() {{
                                var action = this.dataset.action;
                                if (action === 'play') manager.togglePlayPause();
                                else if (action === 'stop') manager.stop();
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
                                if (action === 'create-segment') manager.createSegmentFromSelection();
                                else if (action === 'delete-segment') manager.deleteSelectedSegment();
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


def _generate_label_selector(labels: List[Dict[str, Any]]) -> str:
    """
    Generate HTML for label selection buttons.
    """
    buttons = []
    for label in labels:
        name = escape_html_content(label["name"])
        color = label["color"]
        key_hint = f' ({label["key_value"]})' if label.get("key_value") else ""
        buttons.append(
            f'<button type="button" class="label-btn" data-label="{name}" data-color="{color}" '
            f'title="{name}{key_hint}" style="--label-color: {color};">'
            f'<span class="label-color-dot" style="background-color: {color};"></span>'
            f'{name}</button>'
        )

    return f'''
        <div class="label-group">
            <span class="tool-group-label">Label:</span>
            {"".join(buttons)}
        </div>
    '''


def _generate_keybindings(labels: List[Dict[str, Any]], mode: str) -> List[Tuple[str, str]]:
    """
    Generate keybinding list for the schema.
    """
    keybindings = []

    # Playback shortcuts
    keybindings.append(("Space", "Play/Pause"))
    keybindings.append(("←/→", "Seek 5 seconds"))

    # Label shortcuts (for label/both modes)
    if mode in ['label', 'both']:
        for label in labels:
            if label.get("key_value"):
                keybindings.append((label["key_value"], f"Select: {label['name']}"))

    # Segment shortcuts
    keybindings.append(("[/]", "Set segment start/end"))
    keybindings.append(("Enter", "Create segment"))
    keybindings.append(("Del", "Delete segment"))

    # Zoom shortcuts
    keybindings.append(("+/-", "Zoom in/out"))
    keybindings.append(("0", "Fit to view"))

    return keybindings

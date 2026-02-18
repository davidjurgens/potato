"""
Audio Annotation Layout

Generates a form interface for audio annotation with segmentation.
Uses Peaks.js for waveform visualization and segment management.

Features:
- Waveform visualization (amplitude display)
- Spectrogram visualization (frequency display) - optional
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

# Default spectrogram options
DEFAULT_SPECTROGRAM_OPTIONS = {
    "fft_size": 2048,
    "hop_length": 512,
    "frequency_range": [0, 8000],
    "color_map": "viridis",
}

# Valid color maps for spectrogram
VALID_COLOR_MAPS = ["viridis", "magma", "plasma", "inferno", "grayscale"]


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
            - waveform: Whether to show waveform (default: True)
            - spectrogram: Whether to show spectrogram (default: False)
            - spectrogram_options: Spectrogram configuration (optional):
                - fft_size: FFT window size (default: 2048)
                - hop_length: Hop length between FFT windows (default: 512)
                - frequency_range: [min_hz, max_hz] (default: [0, 8000])
                - color_map: Color mapping ("viridis", "magma", "plasma", "inferno", "grayscale")

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

    # Waveform and spectrogram display options
    show_waveform = annotation_scheme.get('waveform', True)
    show_spectrogram = annotation_scheme.get('spectrogram', False)

    # Process spectrogram options with defaults
    spectrogram_options = _process_spectrogram_options(
        annotation_scheme.get('spectrogram_options', {}),
        schema_name
    )

    # source_field: Links this annotation schema to a display field from instance_display
    source_field = annotation_scheme.get("source_field", "")

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
        "sourceField": source_field,
        "waveform": show_waveform,
        "spectrogram": show_spectrogram,
        "spectrogramOptions": spectrogram_options,
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


def _process_spectrogram_options(options: Dict[str, Any], schema_name: str) -> Dict[str, Any]:
    """
    Process and validate spectrogram configuration options.

    Args:
        options: User-provided spectrogram options
        schema_name: Schema name for error messages

    Returns:
        Validated and merged spectrogram options with defaults
    """
    # Start with defaults
    processed = dict(DEFAULT_SPECTROGRAM_OPTIONS)

    if not options:
        return processed

    # Validate and merge fft_size
    if 'fft_size' in options:
        fft_size = options['fft_size']
        if isinstance(fft_size, int) and fft_size > 0:
            # Ensure power of 2 for FFT efficiency
            if fft_size & (fft_size - 1) == 0:
                processed['fft_size'] = fft_size
            else:
                logger.warning(
                    f"fft_size {fft_size} is not a power of 2 in schema {schema_name}, "
                    f"using default {DEFAULT_SPECTROGRAM_OPTIONS['fft_size']}"
                )

    # Validate and merge hop_length
    if 'hop_length' in options:
        hop_length = options['hop_length']
        if isinstance(hop_length, int) and hop_length > 0:
            processed['hop_length'] = hop_length

    # Validate and merge frequency_range
    if 'frequency_range' in options:
        freq_range = options['frequency_range']
        if (isinstance(freq_range, (list, tuple)) and len(freq_range) == 2
                and all(isinstance(f, (int, float)) for f in freq_range)
                and freq_range[0] < freq_range[1]):
            processed['frequency_range'] = list(freq_range)
        else:
            logger.warning(
                f"Invalid frequency_range {freq_range} in schema {schema_name}, "
                f"using default {DEFAULT_SPECTROGRAM_OPTIONS['frequency_range']}"
            )

    # Validate and merge color_map
    if 'color_map' in options:
        color_map = options['color_map']
        if color_map in VALID_COLOR_MAPS:
            processed['color_map'] = color_map
        else:
            logger.warning(
                f"Invalid color_map '{color_map}' in schema {schema_name}, "
                f"must be one of {VALID_COLOR_MAPS}. Using default '{DEFAULT_SPECTROGRAM_OPTIONS['color_map']}'"
            )

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

    # Determine display mode
    show_waveform = js_config.get('waveform', True)
    show_spectrogram = js_config.get('spectrogram', False)

    # Generate label buttons (for label/both modes)
    label_selector = ""
    if mode in ['label', 'both'] and labels:
        label_selector = _generate_label_selector(labels)

    # Generate playback rate control
    playback_rate_html = ""
    if js_config.get('playbackRateControl'):
        playback_rate_html = '''
            <div class="playback-rate-group">
                <span class="tool-group-label" title="Adjust playback speed">Speed:</span>
                <select class="playback-rate-select" title="Change audio playback speed (0.5x to 2x)">
                    <option value="0.5">0.5x</option>
                    <option value="0.75">0.75x</option>
                    <option value="1" selected>1x</option>
                    <option value="1.25">1.25x</option>
                    <option value="1.5">1.5x</option>
                    <option value="2">2x</option>
                </select>
            </div>
        '''

    # source_field attribute for linking to display fields
    source_field = annotation_scheme.get("source_field", "")
    source_field_attr = f' data-source-field="{escape_html_content(source_field)}"' if source_field else ""

    # Generate spectrogram HTML if enabled
    spectrogram_html = ""
    if show_spectrogram:
        spectrogram_html = f'''
                    <!-- Spectrogram visualization -->
                    <div class="spectrogram-section">
                        <div class="spectrogram-label" style="font-size: 0.85em; color: #666; margin-bottom: 4px; margin-top: 12px;">
                            Spectrogram (frequency analysis)
                        </div>
                        <div id="spectrogram-{escaped_name}" class="spectrogram-container">
                            <canvas id="spectrogram-canvas-{escaped_name}" class="spectrogram-canvas"></canvas>
                            <canvas id="spectrogram-playhead-{escaped_name}" class="spectrogram-playhead-canvas"></canvas>
                        </div>
                    </div>
        '''

    html = f'''
    <form id="{escaped_name}" class="annotation-form audio-annotation" action="/action_page.php"{source_field_attr}>
        <fieldset schema="{escaped_name}">
            <legend>{description}</legend>

            <!-- Audio Annotation Container -->
            <div class="audio-annotation-container" data-schema="{escaped_name}">

                <!-- 1. Full waveform overview at top -->
                <div class="waveform-wrapper">
                    <div class="overview-label" style="font-size: 0.85em; color: #666; margin-bottom: 4px;">Full Audio Overview (click to navigate)</div>
                    <div id="overview-{escaped_name}" class="overview-container" style="margin-bottom: 12px;"></div>

                    <!-- 2. Zoomed waveform below -->
                    <div class="zoomview-label" style="font-size: 0.85em; color: #666; margin-bottom: 4px;">Zoomed View (right-click drag to annotate)</div>
                    <div id="waveform-{escaped_name}" class="waveform-container"></div>

                    {spectrogram_html}
                </div>

                <!-- 3. Toolbar with annotation buttons -->
                <div class="audio-annotation-toolbar" style="margin-top: 12px;">
                    <!-- Playback controls -->
                    <div class="playback-group">
                        <button type="button" class="playback-btn" data-action="play" title="Play or pause audio playback. Keyboard shortcut: Space">
                            <span class="play-icon">▶</span>
                            <span class="pause-icon" style="display:none;">⏸</span>
                        </button>
                        <button type="button" class="playback-btn" data-action="stop" title="Stop playback and return to the beginning">⏹</button>
                        <span class="time-display" title="Current playback position / Total duration">
                            <span class="current-time">0:00</span> / <span class="total-time">0:00</span>
                        </span>
                    </div>

                    {playback_rate_html}

                    <!-- Label selector (for label/both modes) -->
                    {label_selector}

                    <!-- Zoom controls -->
                    <div class="zoom-group">
                        <button type="button" class="zoom-btn" data-action="zoom-in" title="Zoom in to see more detail. Keyboard shortcut: + or =">+</button>
                        <button type="button" class="zoom-btn" data-action="zoom-out" title="Zoom out to see more of the audio. Keyboard shortcut: -">-</button>
                        <button type="button" class="zoom-btn" data-action="zoom-fit" title="Fit the entire audio in the view. Keyboard shortcut: 0">Fit</button>
                    </div>

                    <!-- Segment controls -->
                    <div class="segment-group">
                        <button type="button" class="segment-btn" data-action="set-start" title="Mark the start of a new segment at the current playback position. Keyboard shortcut: [">[</button>
                        <button type="button" class="segment-btn" data-action="set-end" title="Mark the end of a new segment at the current playback position. Keyboard shortcut: ]">]</button>
                        <button type="button" class="segment-btn" data-action="create-segment" title="Create a segment from the marked start and end positions. Keyboard shortcut: Enter">+ Segment</button>
                        <button type="button" class="segment-btn delete-btn" data-action="delete-segment" title="Delete the currently selected segment. Keyboard shortcut: Delete or Backspace" disabled>Delete</button>
                    </div>

                    <!-- Segment count -->
                    <div class="count-group">
                        <span class="segment-count" title="Number of segments you have created">Segments: <span class="count-value">0</span></span>
                    </div>

                    <!-- Help toggle button -->
                    <div class="help-toggle" style="margin-left: auto;">
                        <button type="button" class="help-toggle-btn" onclick="this.closest('.audio-annotation-container').querySelector('.help-panel').classList.toggle('collapsed')" title="Show or hide usage instructions" style="background: none; border: 1px solid #ccc; border-radius: 4px; padding: 4px 8px; cursor: pointer; font-size: 0.85em;">
                            ❓ Help
                        </button>
                    </div>
                </div>

                <!-- 4. Help/Instructions Panel -->
                <div class="help-panel" style="background: #f8f9fa; border: 1px solid #e9ecef; border-radius: 4px; padding: 12px; margin-top: 10px; font-size: 0.9em;">
                    <div style="display: flex; gap: 30px; flex-wrap: wrap;">
                        <div>
                            <strong style="color: #495057;">🖱️ Creating Segments:</strong>
                            <ul style="margin: 5px 0 0 0; padding-left: 20px; color: #666;">
                                <li><strong>Left-click</strong> to navigate through the audio</li>
                                <li><strong>Right-click + drag</strong> to create a segment</li>
                                <li>Or use <strong>[ and ]</strong> keys to mark start/end while playing</li>
                                <li><strong>Drag segment edges</strong> to resize</li>
                            </ul>
                        </div>
                        <div>
                            <strong style="color: #495057;">⌨️ Keyboard Shortcuts:</strong>
                            <ul style="margin: 5px 0 0 0; padding-left: 20px; color: #666;">
                                <li><strong>Space</strong> - Play/Pause</li>
                                <li><strong>[ ]</strong> - Mark segment start/end</li>
                                <li><strong>Enter</strong> - Create segment from markers</li>
                                <li><strong>Delete</strong> - Delete selected segment</li>
                                <li><strong>+/-/0</strong> - Zoom in/out/fit</li>
                                <li><strong>← →</strong> - Skip 5s (Shift: 30s)</li>
                            </ul>
                        </div>
                        <div>
                            <strong style="color: #495057;">📝 Quick Start:</strong>
                            <ol style="margin: 5px 0 0 0; padding-left: 20px; color: #666;">
                                <li>Select a label above</li>
                                <li>Right-click and drag on waveform to create segment</li>
                                <li>Adjust edges by dragging if needed</li>
                            </ol>
                        </div>
                    </div>
                </div>
                <style>
                    .help-panel.collapsed {{ display: none; }}
                </style>

                <!-- Segment list -->
                <div class="segment-list-container" style="margin-top: 12px;">
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
                    console.log('[AudioAnnotation] Initialization script started for schema: {escaped_name}');

                    function initWhenReady() {{
                        if (typeof AudioAnnotationManager === 'undefined') {{
                            console.log('[AudioAnnotation] Waiting for AudioAnnotationManager...');
                            setTimeout(initWhenReady, 100);
                            return;
                        }}
                        // Peaks.js exports as lowercase 'peaks', create alias for uppercase 'Peaks' if needed
                        if (typeof Peaks === 'undefined' && typeof peaks !== 'undefined') {{
                            window.Peaks = peaks;
                            console.log('[AudioAnnotation] Created Peaks alias from lowercase peaks');
                        }}
                        if (typeof Peaks === 'undefined' && typeof peaks === 'undefined') {{
                            console.log('[AudioAnnotation] Waiting for Peaks.js (checked both Peaks and peaks)...');
                            setTimeout(initWhenReady, 100);
                            return;
                        }}
                        console.log('[AudioAnnotation] AudioAnnotationManager and Peaks.js loaded');

                        var container = document.querySelector('.audio-annotation-container[data-schema="{escaped_name}"]');
                        if (!container) {{
                            console.error('[AudioAnnotation] Container not found for schema: {escaped_name}');
                            return;
                        }}

                        // Wait for waveform container to be visible and have dimensions
                        // (main-content starts hidden and is shown after API data loads)
                        var waveformContainer = document.getElementById('waveform-{escaped_name}');
                        if (waveformContainer) {{
                            var rect = waveformContainer.getBoundingClientRect();
                            if (rect.width === 0 || rect.height === 0) {{
                                console.log('[AudioAnnotation] Waveform container not visible yet, waiting...');
                                setTimeout(initWhenReady, 100);
                                return;
                            }}
                        }}
                        console.log('[AudioAnnotation] Container found and visible:', container);

                        var config = {config_json};
                        var waveformId = 'waveform-{escaped_name}';
                        var overviewId = 'overview-{escaped_name}';
                        var audioId = 'audio-{escaped_name}';
                        var inputId = 'input-{escaped_name}';
                        var segmentListId = 'segment-list-{escaped_name}';
                        var questionsId = 'segment-questions-{escaped_name}';
                        var spectrogramId = config.spectrogram ? 'spectrogram-{escaped_name}' : null;
                        var spectrogramCanvasId = config.spectrogram ? 'spectrogram-canvas-{escaped_name}' : null;
                        var spectrogramPlayheadId = config.spectrogram ? 'spectrogram-playhead-{escaped_name}' : null;

                        // Get audio URL from various sources
                        var audioUrl = null;

                        // 1. First try to find from source_field in instance_display field
                        if (config.sourceField) {{
                            var displayField = document.querySelector('[data-field-key="' + config.sourceField + '"]');
                            console.log('[AudioAnnotation] Looking for display field:', config.sourceField, displayField);
                            if (displayField) {{
                                // Check for data-source-url attribute
                                var sourceUrl = displayField.dataset.sourceUrl;
                                if (sourceUrl) {{
                                    audioUrl = sourceUrl;
                                    console.log('[AudioAnnotation] Found audio URL from display field data-source-url:', audioUrl);
                                }}
                                // Check for audio element inside display field
                                var audioEl = displayField.querySelector('audio');
                                if (!audioUrl && audioEl) {{
                                    var source = audioEl.querySelector('source');
                                    audioUrl = source ? source.src : audioEl.src;
                                    console.log('[AudioAnnotation] Found audio URL from display field audio element:', audioUrl);
                                }}
                            }}
                        }}

                        // 2. Try instance-display container's data-instance-fields attribute
                        if (!audioUrl && config.sourceField) {{
                            var instanceDisplayContainer = document.querySelector('.instance-display-container[data-instance-fields]');
                            if (instanceDisplayContainer) {{
                                try {{
                                    var instanceFields = JSON.parse(instanceDisplayContainer.dataset.instanceFields);
                                    if (instanceFields[config.sourceField]) {{
                                        audioUrl = instanceFields[config.sourceField];
                                        console.log('[AudioAnnotation] Found audio URL from instance fields:', audioUrl);
                                    }}
                                }} catch (e) {{
                                    console.warn('[AudioAnnotation] Failed to parse instance fields:', e);
                                }}
                            }}
                        }}

                        // 3. Fallback: Try instance-text or text-content containers
                        if (!audioUrl) {{
                            var instanceContainer = document.getElementById('instance-text') || document.getElementById('text-content');
                            console.log('[AudioAnnotation] Fallback - Instance container:', instanceContainer);
                            if (instanceContainer) {{
                                var text = instanceContainer.textContent || instanceContainer.innerText;
                                // Check if it's a URL
                                if (text && (text.trim().startsWith('http') || text.trim().endsWith('.mp3') || text.trim().endsWith('.wav'))) {{
                                    audioUrl = text.trim();
                                    console.log('[AudioAnnotation] Found audio URL in text:', audioUrl);
                                }}
                                // Check for audio element
                                var audioEl = instanceContainer.querySelector('audio');
                                if (audioEl && audioEl.src) {{
                                    audioUrl = audioEl.src;
                                    console.log('[AudioAnnotation] Found audio URL in audio element:', audioUrl);
                                }}
                            }}
                        }}

                        // Initialize manager
                        console.log('[AudioAnnotation] Creating AudioAnnotationManager with audioUrl:', audioUrl);
                        var manager = new AudioAnnotationManager({{
                            container: container,
                            waveformId: waveformId,
                            overviewId: overviewId,
                            audioId: audioId,
                            inputId: inputId,
                            segmentListId: segmentListId,
                            questionsId: questionsId,
                            spectrogramId: spectrogramId,
                            spectrogramCanvasId: spectrogramCanvasId,
                            spectrogramPlayheadId: spectrogramPlayheadId,
                            config: config
                        }});

                        // Store reference on container
                        container.audioAnnotationManager = manager;

                        // Load audio if available
                        if (audioUrl) {{
                            // Use proxy for external URLs to avoid CORS issues
                            var finalAudioUrl = audioUrl;
                            if (audioUrl.startsWith('http://') || audioUrl.startsWith('https://')) {{
                                // Check if it's an external URL (not same origin)
                                var currentOrigin = window.location.origin;
                                if (!audioUrl.startsWith(currentOrigin)) {{
                                    finalAudioUrl = '/api/audio/proxy?url=' + encodeURIComponent(audioUrl);
                                    console.log('[AudioAnnotation] Using proxy for external URL:', finalAudioUrl);
                                }}
                            }}
                            console.log('[AudioAnnotation] Calling loadAudio with:', finalAudioUrl);
                            manager.loadAudio(finalAudioUrl);
                        }} else {{
                            console.warn('[AudioAnnotation] No audio URL found, waveform will not be loaded');
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
                                if (action === 'set-start') manager.setSelectionStart();
                                else if (action === 'set-end') manager.setSelectionEnd();
                                else if (action === 'create-segment') manager.createSegmentFromSelection();
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
        key_hint = f' Keyboard shortcut: {label["key_value"]}' if label.get("key_value") else ""
        tooltip = f"Select '{name}' as the label for new segments.{key_hint}"
        buttons.append(
            f'<button type="button" class="label-btn" data-label="{name}" data-color="{color}" '
            f'title="{tooltip}" style="--label-color: {color};">'
            f'<span class="label-color-dot" style="background-color: {color};"></span>'
            f'{name}</button>'
        )

    return f'''
        <div class="label-group">
            <span class="tool-group-label" title="Select a label before creating segments">Label:</span>
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

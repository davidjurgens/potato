"""
Tiered Annotation Schema

Generates a multi-tier timeline annotation interface for audio/video content.
This schema supports ELAN-style hierarchical annotation with independent and
dependent tiers, where dependent tiers can have various constraint relationships
to their parent tiers.

Features:
- Multi-row timeline visualization with waveform (via Peaks.js)
- Independent tiers for direct time alignment
- Dependent tiers with parent-child constraints
- Tier selection with dynamic label buttons
- Constraint validation in real-time
- EAF and TextGrid export support

Example configuration:
    annotation_schemes:
      - annotation_type: tiered_annotation
        name: linguistic_tiers
        description: "Multi-tier linguistic annotation"
        source_field: audio_url
        media_type: audio
        tiers:
          - name: utterance
            tier_type: independent
            labels:
              - name: Speaker_A
                color: "#4ECDC4"
              - name: Speaker_B
                color: "#FF6B6B"
          - name: word
            tier_type: dependent
            parent_tier: utterance
            constraint_type: time_subdivision
            labels:
              - name: Word
                color: "#95E1D3"
"""

import json
import logging
from typing import Dict, Any, Tuple, List

from .identifier_utils import safe_generate_layout, escape_html_content

logger = logging.getLogger(__name__)

# Default colors for tier labels
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

# Valid constraint types
VALID_CONSTRAINT_TYPES = [
    "time_subdivision",
    "included_in",
    "symbolic_association",
    "symbolic_subdivision",
    "none"
]


def generate_tiered_annotation_layout(
    annotation_scheme: Dict[str, Any]
) -> Tuple[str, List[Tuple[str, str]]]:
    """
    Generate HTML for a tiered annotation interface.

    Args:
        annotation_scheme: Configuration dictionary including:
            - name: Schema identifier
            - description: Display description
            - source_field: Field name containing media URL
            - media_type: "audio" or "video"
            - tiers: List of tier definitions
            - tier_height: Height per tier row in pixels (default: 50)
            - show_tier_labels: Show tier name labels (default: True)
            - collapsed_tiers: List of tier names to start collapsed
            - zoom_enabled: Enable zoom controls (default: True)
            - playback_rate_control: Show playback speed controls (default: True)

    Returns:
        Tuple of (html_string, keybindings_list)
    """
    return safe_generate_layout(annotation_scheme, _generate_tiered_annotation_layout_internal)


def _generate_tiered_annotation_layout_internal(
    annotation_scheme: Dict[str, Any]
) -> Tuple[str, List[Tuple[str, str]]]:
    """Internal implementation of tiered annotation layout generation."""

    schema_name = annotation_scheme.get("name", "tiered_annotation")
    description = annotation_scheme.get("description", "")
    source_field = annotation_scheme.get("source_field", "audio_url")
    media_type = annotation_scheme.get("media_type", "audio").lower()

    # Validate media type
    if media_type not in ("audio", "video"):
        raise ValueError(f"Invalid media_type '{media_type}'. Must be 'audio' or 'video'.")

    # Get tier definitions
    tiers = annotation_scheme.get("tiers", [])
    if not tiers:
        raise ValueError("tiered_annotation requires at least one tier definition")

    # Validate and process tiers
    processed_tiers = _process_tiers(tiers)

    # Validate tier structure
    _validate_tier_structure(processed_tiers)

    # Configuration options
    tier_height = annotation_scheme.get("tier_height", 50)
    show_tier_labels = annotation_scheme.get("show_tier_labels", True)
    collapsed_tiers = annotation_scheme.get("collapsed_tiers", [])
    zoom_enabled = annotation_scheme.get("zoom_enabled", True)
    playback_rate_control = annotation_scheme.get("playback_rate_control", True)
    overview_height = annotation_scheme.get("overview_height", 40)

    # Build tier rows HTML
    tier_rows_html = _generate_tier_rows_html(
        schema_name, processed_tiers, tier_height, show_tier_labels, collapsed_tiers
    )

    # Build tier selector options
    tier_selector_html = _generate_tier_selector_html(processed_tiers)

    # Build JavaScript configuration
    js_config = {
        "schemaName": schema_name,
        "mediaType": media_type,
        "sourceField": source_field,
        "tiers": processed_tiers,
        "tierHeight": tier_height,
        "showTierLabels": show_tier_labels,
        "collapsedTiers": collapsed_tiers,
        "zoomEnabled": zoom_enabled,
        "playbackRateControl": playback_rate_control,
        "overviewHeight": overview_height,
    }
    config_json = json.dumps(js_config)

    # Generate media element
    media_element = _generate_media_element(schema_name, media_type)

    # Generate playback controls
    playback_controls = _generate_playback_controls(
        schema_name, playback_rate_control, zoom_enabled
    )

    # Generate the complete HTML
    html = f'''
<form id="{escape_html_content(schema_name)}" class="annotation-form tiered-annotation-container"
      action="/action_page.php"
      data-annotation-type="tiered_annotation"
      data-schema-name="{escape_html_content(schema_name)}"
      data-config='{escape_html_content(config_json)}'>

    <fieldset schema="{escape_html_content(schema_name)}">
        <legend>{escape_html_content(description)}</legend>

        <!-- Media Player Panel -->
        <div class="tiered-media-panel" id="media-panel-{escape_html_content(schema_name)}">
            {media_element}
        </div>

        <!-- Tier Toolbar -->
        <div class="tier-toolbar" id="tier-toolbar-{escape_html_content(schema_name)}">
            <div class="tier-toolbar-left">
                <label for="tier-select-{escape_html_content(schema_name)}" class="tier-select-label">Active Tier:</label>
                <select class="tier-select" id="tier-select-{escape_html_content(schema_name)}">
                    {tier_selector_html}
                </select>
            </div>

            <div class="tier-toolbar-center">
                <div class="label-buttons-container" id="labels-{escape_html_content(schema_name)}">
                    <!-- Label buttons populated by JavaScript -->
                </div>
            </div>

            <div class="tier-toolbar-right">
                {playback_controls}
            </div>
        </div>

        <!-- Timeline Container -->
        <div class="tiered-timeline-container" id="timeline-container-{escape_html_content(schema_name)}">
            <!-- Waveform Overview (full media) -->
            <div class="waveform-overview-container">
                <div class="waveform-overview" id="overview-{escape_html_content(schema_name)}"></div>
            </div>

            <!-- Zoomed Timeline View (for fine-grained editing) -->
            <div class="zoomed-timeline-container" id="zoomed-container-{escape_html_content(schema_name)}">
                <div class="zoomed-timeline-header">
                    <span class="zoomed-timeline-label">Zoomed View</span>
                    <span class="zoomed-timeline-range" id="zoomed-range-{escape_html_content(schema_name)}">0:00 - 0:10</span>
                </div>
                <!-- Peaks.js zoomview waveform -->
                <div class="zoomed-waveform" id="zoomview-{escape_html_content(schema_name)}"></div>
                <!-- Canvas for annotations overlay -->
                <div class="zoomed-timeline-scroll" id="zoomed-scroll-{escape_html_content(schema_name)}">
                    <canvas class="zoomed-timeline-canvas" id="zoomed-canvas-{escape_html_content(schema_name)}"></canvas>
                </div>
                <div class="zoomed-timeline-controls">
                    <button type="button" class="btn btn-sm btn-outline-secondary" id="zoomed-left-{escape_html_content(schema_name)}" title="Scroll left">
                        <i class="fas fa-chevron-left"></i>
                    </button>
                    <input type="range" class="zoomed-timeline-slider" id="zoomed-slider-{escape_html_content(schema_name)}" min="0" max="100" value="0">
                    <button type="button" class="btn btn-sm btn-outline-secondary" id="zoomed-right-{escape_html_content(schema_name)}" title="Scroll right">
                        <i class="fas fa-chevron-right"></i>
                    </button>
                </div>
            </div>

            <!-- Tier Rows -->
            <div class="tier-rows-container" id="tier-rows-{escape_html_content(schema_name)}">
                {tier_rows_html}
            </div>

            <!-- Time Axis -->
            <div class="time-axis" id="time-axis-{escape_html_content(schema_name)}"></div>
        </div>

        <!-- Annotation List Panel -->
        <div class="tiered-annotation-list-panel">
            <div class="annotation-list-header">
                <span class="annotation-list-title">Annotations</span>
                <button type="button" class="btn btn-sm btn-outline-secondary annotation-list-toggle"
                        id="list-toggle-{escape_html_content(schema_name)}">
                    <i class="fas fa-chevron-down"></i>
                </button>
            </div>
            <div class="annotation-list" id="annotation-list-{escape_html_content(schema_name)}">
                <!-- Annotation list populated by JavaScript -->
            </div>
        </div>

        <!-- Hidden input for form submission -->
        <input type="hidden" name="{escape_html_content(schema_name)}"
               id="input-{escape_html_content(schema_name)}"
               class="annotation-data-input" value="">
    </fieldset>

    <!-- Initialization Script -->
    <script>
    (function() {{
        var initKey = '__tieredAnnotationInit_{escape_html_content(schema_name)}';
        if (window[initKey]) return;
        window[initKey] = true;

        var config = {config_json};

        function initTieredAnnotation() {{
            if (typeof TieredAnnotationManager === 'undefined') {{
                console.warn('TieredAnnotationManager not loaded yet, retrying...');
                setTimeout(initTieredAnnotation, 100);
                return;
            }}

            var container = document.getElementById('{escape_html_content(schema_name)}');
            if (!container) {{
                console.error('Container not found for tiered annotation: {escape_html_content(schema_name)}');
                return;
            }}

            try {{
                var manager = new TieredAnnotationManager(container, config);
                container._tieredManager = manager;
                manager.initialize().then(function() {{
                    console.log('TieredAnnotationManager initialized:', '{escape_html_content(schema_name)}');
                }}).catch(function(err) {{
                    console.error('Failed to initialize TieredAnnotationManager:', err);
                }});
            }} catch (e) {{
                console.error('Error creating TieredAnnotationManager:', e);
            }}
        }}

        if (document.readyState === 'loading') {{
            document.addEventListener('DOMContentLoaded', initTieredAnnotation);
        }} else {{
            initTieredAnnotation();
        }}
    }})();
    </script>
</form>
'''

    # Define keybindings
    keybindings = [
        ("Space", "Play/Pause"),
        (",", "Step back 1 frame"),
        (".", "Step forward 1 frame"),
        ("Delete/Backspace", "Delete selected annotation"),
        ("Esc", "Deselect annotation"),
    ]

    return html, keybindings


def _process_tiers(tiers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Process tier definitions, assigning colors and normalizing fields.

    Args:
        tiers: Raw tier configuration list

    Returns:
        Processed tier list with normalized fields
    """
    processed = []
    color_index = 0

    for tier in tiers:
        tier_data = {
            "name": tier.get("name", f"tier_{len(processed)}"),
            "tier_type": tier.get("tier_type", "independent").lower(),
            "parent_tier": tier.get("parent_tier", None),
            "constraint_type": tier.get("constraint_type", "none").lower(),
            "description": tier.get("description", ""),
            "linguistic_type": tier.get("linguistic_type"),
            "labels": [],
        }

        # Validate tier_type
        if tier_data["tier_type"] not in ("independent", "dependent"):
            raise ValueError(
                f"Tier '{tier_data['name']}' has invalid tier_type: {tier_data['tier_type']}"
            )

        # Validate constraint_type
        if tier_data["constraint_type"] not in VALID_CONSTRAINT_TYPES:
            raise ValueError(
                f"Tier '{tier_data['name']}' has invalid constraint_type: {tier_data['constraint_type']}"
            )

        # Process labels
        raw_labels = tier.get("labels", [])
        for label in raw_labels:
            if isinstance(label, str):
                label_data = {
                    "name": label,
                    "color": DEFAULT_COLORS[color_index % len(DEFAULT_COLORS)],
                }
                color_index += 1
            elif isinstance(label, dict):
                label_data = {
                    "name": label.get("name", ""),
                    "color": label.get("color", DEFAULT_COLORS[color_index % len(DEFAULT_COLORS)]),
                    "description": label.get("description", ""),
                    "tooltip": label.get("tooltip", ""),
                }
                if not label.get("color"):
                    color_index += 1
            else:
                continue

            if label_data["name"]:
                tier_data["labels"].append(label_data)

        processed.append(tier_data)

    return processed


def _validate_tier_structure(tiers: List[Dict[str, Any]]) -> None:
    """
    Validate the tier hierarchy structure.

    Args:
        tiers: Processed tier list

    Raises:
        ValueError: If structure is invalid
    """
    tier_names = {t["name"] for t in tiers}

    for tier in tiers:
        # Check dependent tier requirements
        if tier["tier_type"] == "dependent":
            if not tier.get("parent_tier"):
                raise ValueError(
                    f"Dependent tier '{tier['name']}' must have a parent_tier"
                )
            if tier["parent_tier"] not in tier_names:
                raise ValueError(
                    f"Tier '{tier['name']}' references unknown parent '{tier['parent_tier']}'"
                )
            if tier["parent_tier"] == tier["name"]:
                raise ValueError(
                    f"Tier '{tier['name']}' cannot be its own parent"
                )

    # Check for cycles
    def has_cycle(tier_name: str, visited: set) -> bool:
        if tier_name in visited:
            return True
        visited.add(tier_name)
        tier = next((t for t in tiers if t["name"] == tier_name), None)
        if tier and tier.get("parent_tier"):
            return has_cycle(tier["parent_tier"], visited)
        return False

    for tier in tiers:
        if has_cycle(tier["name"], set()):
            raise ValueError(f"Cycle detected in tier hierarchy involving '{tier['name']}'")


def _generate_tier_rows_html(
    schema_name: str,
    tiers: List[Dict[str, Any]],
    tier_height: int,
    show_tier_labels: bool,
    collapsed_tiers: List[str]
) -> str:
    """Generate HTML for tier rows."""
    rows = []

    for tier in tiers:
        tier_name = tier["name"]
        is_collapsed = tier_name in collapsed_tiers
        collapsed_class = "collapsed" if is_collapsed else ""
        indent_class = "tier-dependent" if tier["tier_type"] == "dependent" else ""

        row_html = f'''
        <div class="tier-row {indent_class} {collapsed_class}"
             data-tier="{escape_html_content(tier_name)}"
             data-tier-type="{escape_html_content(tier['tier_type'])}"
             data-parent-tier="{escape_html_content(tier.get('parent_tier') or '')}"
             data-constraint-type="{escape_html_content(tier.get('constraint_type', 'none'))}"
             style="height: {tier_height}px;">
'''

        if show_tier_labels:
            row_html += f'''
            <div class="tier-label" title="{escape_html_content(tier.get('description', ''))}">
                <span class="tier-name">{escape_html_content(tier_name)}</span>
                <button type="button" class="tier-collapse-btn" data-tier="{escape_html_content(tier_name)}">
                    <i class="fas fa-chevron-{'up' if is_collapsed else 'down'}"></i>
                </button>
            </div>
'''

        row_html += f'''
            <div class="tier-canvas-container">
                <canvas class="tier-canvas" id="tier-canvas-{escape_html_content(schema_name)}-{escape_html_content(tier_name)}"></canvas>
            </div>
        </div>
'''
        rows.append(row_html)

    return "\n".join(rows)


def _generate_tier_selector_html(tiers: List[Dict[str, Any]]) -> str:
    """Generate HTML for tier selector dropdown."""
    options = []
    for tier in tiers:
        indent = "&nbsp;&nbsp;" if tier["tier_type"] == "dependent" else ""
        tier_type_indicator = " (→)" if tier["tier_type"] == "dependent" else ""
        options.append(
            f'<option value="{escape_html_content(tier["name"])}">'
            f'{indent}{escape_html_content(tier["name"])}{tier_type_indicator}</option>'
        )
    return "\n".join(options)


def _generate_media_element(schema_name: str, media_type: str) -> str:
    """Generate the media player element (audio or video)."""
    if media_type == "video":
        return f'''
        <video id="media-{escape_html_content(schema_name)}"
               class="tiered-media-player tiered-video-player"
               controls preload="metadata">
            <!-- Source set by JavaScript -->
            Your browser does not support the video element.
        </video>
'''
    else:
        # Audio (default)
        return f'''
        <audio id="media-{escape_html_content(schema_name)}"
               class="tiered-media-player tiered-audio-player"
               controls preload="metadata">
            <!-- Source set by JavaScript -->
            Your browser does not support the audio element.
        </audio>
'''


def _generate_playback_controls(
    schema_name: str,
    playback_rate_control: bool,
    zoom_enabled: bool
) -> str:
    """Generate playback and zoom controls HTML."""
    controls = []

    if playback_rate_control:
        controls.append(f'''
        <div class="playback-rate-control">
            <label for="rate-{escape_html_content(schema_name)}">Speed:</label>
            <select id="rate-{escape_html_content(schema_name)}" class="playback-rate-select">
                <option value="0.25">0.25x</option>
                <option value="0.5">0.5x</option>
                <option value="0.75">0.75x</option>
                <option value="1" selected>1x</option>
                <option value="1.25">1.25x</option>
                <option value="1.5">1.5x</option>
                <option value="2">2x</option>
            </select>
        </div>
''')

    if zoom_enabled:
        controls.append(f'''
        <div class="zoom-control">
            <button type="button" class="btn btn-sm btn-outline-secondary zoom-in-btn"
                    id="zoom-in-{escape_html_content(schema_name)}" title="Zoom in">
                <i class="fas fa-search-plus"></i>
            </button>
            <button type="button" class="btn btn-sm btn-outline-secondary zoom-out-btn"
                    id="zoom-out-{escape_html_content(schema_name)}" title="Zoom out">
                <i class="fas fa-search-minus"></i>
            </button>
            <button type="button" class="btn btn-sm btn-outline-secondary zoom-fit-btn"
                    id="zoom-fit-{escape_html_content(schema_name)}" title="Fit to view">
                <i class="fas fa-expand"></i>
            </button>
        </div>
''')

    # Time display
    controls.append(f'''
        <div class="time-display" id="time-display-{escape_html_content(schema_name)}">
            <span class="current-time">00:00.000</span>
            <span class="time-separator">/</span>
            <span class="total-time">00:00.000</span>
        </div>
''')

    return "\n".join(controls)

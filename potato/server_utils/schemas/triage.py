"""
Triage Layout

Generates a Prodigy-style binary accept/reject/skip interface for rapid data curation.
Features include:
- Three large buttons: Accept (green), Reject (red), Skip (gray)
- Keyboard shortcuts: a (accept), r (reject), s (skip)
- Auto-advance to next item option
- Progress indicator display
- Minimal UI optimized for rapid decisions
"""

import logging
from typing import Dict, Any, Tuple, List

from .identifier_utils import (
    safe_generate_layout,
    escape_html_content,
    generate_layout_attributes,
)

logger = logging.getLogger(__name__)

# Default labels for triage actions
DEFAULT_ACCEPT_LABEL = "Keep"
DEFAULT_REJECT_LABEL = "Discard"
DEFAULT_SKIP_LABEL = "Unsure"

# Default keyboard shortcuts (1/2/3 are adjacent and easy for rapid annotation)
DEFAULT_KEYBINDINGS = {
    "accept": "1",
    "reject": "2",
    "skip": "3",
}


def generate_triage_layout(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    """
    Generate HTML for a triage (accept/reject/skip) interface.

    Args:
        annotation_scheme (dict): Configuration including:
            - name: Schema identifier
            - description: Display description
            - accept_label: Custom label for accept button (default: "Accept")
            - reject_label: Custom label for reject button (default: "Reject")
            - skip_label: Custom label for skip button (default: "Skip")
            - auto_advance: Whether to auto-advance after selection (default: true)
            - show_progress: Whether to show progress indicator (default: true)
            - accept_key: Custom keyboard shortcut for accept (default: "a")
            - reject_key: Custom keyboard shortcut for reject (default: "r")
            - skip_key: Custom keyboard shortcut for skip (default: "s")

    Returns:
        tuple: (html_string, key_bindings)
            html_string: Complete HTML for the triage interface
            key_bindings: List of (key, description) tuples for keyboard shortcuts
    """
    return safe_generate_layout(annotation_scheme, _generate_triage_layout_internal)


def _generate_triage_layout_internal(annotation_scheme: Dict[str, Any]) -> Tuple[str, List[Tuple[str, str]]]:
    """
    Internal function to generate triage layout after validation.
    """
    logger.debug(f"Generating triage layout for schema: {annotation_scheme['name']}")

    schema_name = annotation_scheme["name"]
    description = annotation_scheme.get("description", "")

    # Get custom labels or use defaults
    accept_label = annotation_scheme.get("accept_label", DEFAULT_ACCEPT_LABEL)
    reject_label = annotation_scheme.get("reject_label", DEFAULT_REJECT_LABEL)
    skip_label = annotation_scheme.get("skip_label", DEFAULT_SKIP_LABEL)

    # Get keyboard shortcuts
    accept_key = annotation_scheme.get("accept_key", DEFAULT_KEYBINDINGS["accept"])
    reject_key = annotation_scheme.get("reject_key", DEFAULT_KEYBINDINGS["reject"])
    skip_key = annotation_scheme.get("skip_key", DEFAULT_KEYBINDINGS["skip"])

    # Get options
    auto_advance = annotation_scheme.get("auto_advance", True)
    show_progress = annotation_scheme.get("show_progress", True)

    # Get layout attributes for grid positioning
    layout_attrs = generate_layout_attributes(annotation_scheme)

    # Build keybindings list
    key_bindings = [
        (accept_key, f"{schema_name}: {accept_label}"),
        (reject_key, f"{schema_name}: {reject_label}"),
        (skip_key, f"{schema_name}: {skip_label}"),
    ]

    # Escape for HTML attributes
    safe_schema_name = escape_html_content(schema_name)
    safe_description = escape_html_content(description)
    safe_accept_label = escape_html_content(accept_label)
    safe_reject_label = escape_html_content(reject_label)
    safe_skip_label = escape_html_content(skip_label)

    # Build the HTML
    html = f"""
    <form id="{safe_schema_name}" class="annotation-form triage" action="/action_page.php"
          data-annotation-id="{annotation_scheme.get('annotation_id', '')}"
          data-annotation-type="triage"
          data-schema-name="{safe_schema_name}"
          data-auto-advance="{str(auto_advance).lower()}"
          {layout_attrs}>
        <fieldset schema="{safe_schema_name}">
            <legend class="triage-title">{safe_description}</legend>

            <!-- Hidden input to store the decision value -->
            <input type="hidden"
                   id="{safe_schema_name}_value"
                   name="{safe_schema_name}:::decision"
                   class="annotation-input triage-input"
                   schema="{safe_schema_name}"
                   label_name="decision"
                   value="">

            <div class="triage-container">
                <!-- Triage buttons -->
                <div class="triage-buttons">
                    <button type="button"
                            class="triage-btn triage-accept"
                            data-value="accept"
                            data-schema="{safe_schema_name}"
                            data-key="{escape_html_content(accept_key)}">
                        <span class="triage-btn-icon">&#10003;</span>
                        <span class="triage-btn-label">{safe_accept_label}</span>
                        <span class="triage-btn-key">[{escape_html_content(accept_key.upper())}]</span>
                    </button>

                    <button type="button"
                            class="triage-btn triage-reject"
                            data-value="reject"
                            data-schema="{safe_schema_name}"
                            data-key="{escape_html_content(reject_key)}">
                        <span class="triage-btn-icon">&#10007;</span>
                        <span class="triage-btn-label">{safe_reject_label}</span>
                        <span class="triage-btn-key">[{escape_html_content(reject_key.upper())}]</span>
                    </button>

                    <button type="button"
                            class="triage-btn triage-skip"
                            data-value="skip"
                            data-schema="{safe_schema_name}"
                            data-key="{escape_html_content(skip_key)}">
                        <span class="triage-btn-icon">&#8594;</span>
                        <span class="triage-btn-label">{safe_skip_label}</span>
                        <span class="triage-btn-key">[{escape_html_content(skip_key.upper())}]</span>
                    </button>
                </div>
    """

    # Add progress indicator if enabled
    if show_progress:
        html += """
                <!-- Progress indicator (populated by JavaScript) -->
                <div class="triage-progress" id="triage-progress-{schema_name}">
                    <div class="triage-progress-bar">
                        <div class="triage-progress-fill" style="width: 0%"></div>
                    </div>
                    <div class="triage-progress-text">
                        <span class="triage-progress-current">0</span> /
                        <span class="triage-progress-total">0</span>
                    </div>
                </div>
        """.format(schema_name=safe_schema_name)

    html += """
            </div>
        </fieldset>
    </form>
    """

    logger.info(f"Successfully generated triage layout for {schema_name}")
    return html, key_bindings

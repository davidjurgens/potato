"""
Dialogue Display Type

Renders conversation/dialogue content for display in the annotation interface.
Supports multiple conversation turns with speaker identification and styling.
"""

import html
from typing import Dict, Any, List, Union

from .base import BaseDisplay


class DialogueDisplay(BaseDisplay):
    """
    Display type for dialogue/conversation content.

    Displays conversations with alternating speaker turns and
    visual styling to distinguish between speakers.
    Can be used as a target for span annotations.
    """

    name = "dialogue"
    required_fields = ["key"]
    optional_fields = {
        "alternating_shading": True,
        "speaker_extraction": True,
        "speaker_key": "speaker",
        "text_key": "text",
        "show_turn_numbers": False,
        "per_turn_ratings": None,
    }
    description = "Dialogue/conversation turns display"
    supports_span_target = True

    def render(self, field_config: Dict[str, Any], data: Any) -> str:
        """
        Render dialogue content as HTML.

        Args:
            field_config: The field configuration
            data: The dialogue data - can be:
                  - List of strings (each string is a turn)
                  - List of dicts with speaker/text keys
                  - String with turns separated by newlines

        Returns:
            HTML string for the dialogue display
        """
        if not data:
            return '<div class="dialogue-placeholder">No dialogue provided</div>'

        # Get display options
        options = self.get_display_options(field_config)
        alternating_shading = options.get("alternating_shading", True)
        speaker_extraction = options.get("speaker_extraction", True)
        speaker_key = options.get("speaker_key", "speaker")
        text_key = options.get("text_key", "text")
        show_turn_numbers = options.get("show_turn_numbers", False)
        per_turn_ratings = options.get("per_turn_ratings")

        # Normalize the dialogue data to a list of turns
        turns = self._normalize_dialogue(data, speaker_key, text_key, speaker_extraction)

        if not turns:
            return '<div class="dialogue-placeholder">No dialogue turns found</div>'

        field_key = html.escape(field_config.get("key", ""), quote=True)
        is_span_target = field_config.get("span_target", False)

        # Determine which speakers get per-turn ratings
        rated_speakers = set()
        rating_config = {}
        if per_turn_ratings:
            rated_speakers = set(per_turn_ratings.get("speakers", []))
            rating_config = per_turn_ratings.get("scheme", {})

        # Build HTML for each turn
        turn_html_list = []
        for i, turn in enumerate(turns):
            speaker = turn.get("speaker", "")
            text = turn.get("text", "")

            # Determine styling
            turn_classes = ["dialogue-turn"]
            if alternating_shading:
                turn_classes.append(f"turn-{'even' if i % 2 == 0 else 'odd'}")

            # Speaker-based styling
            speaker_index = self._get_speaker_index(speaker, turns)
            turn_classes.append(f"speaker-{speaker_index}")

            # Build turn HTML
            speaker_html = ""
            if speaker:
                escaped_speaker = html.escape(str(speaker))
                speaker_html = f'<span class="dialogue-speaker" data-speaker="{escaped_speaker}">{escaped_speaker}:</span>'

            turn_number_html = ""
            if show_turn_numbers:
                turn_number_html = f'<span class="turn-number">[{i + 1}]</span>'

            escaped_text = html.escape(str(text))

            # For span target, add data attributes
            span_attrs = ""
            text_id = ""
            if is_span_target:
                text_id = f'id="turn-text-{field_key}-{i}"'
                span_attrs = f'data-original-text="{escaped_text}" data-turn-index="{i}"'

            # Per-turn rating widget
            rating_html = ""
            if per_turn_ratings and speaker in rated_speakers:
                rating_html = self._render_turn_rating(field_key, i, rating_config)

            turn_html = f'''
            <div class="{' '.join(turn_classes)}" data-speaker-index="{speaker_index}">
                {turn_number_html}
                {speaker_html}
                <span class="dialogue-text" {text_id} {span_attrs}>{escaped_text}</span>
                {rating_html}
            </div>
            '''
            turn_html_list.append(turn_html)

        # Combine all turns
        all_turns_html = "\n".join(turn_html_list)

        # Hidden input for storing per-turn rating data
        hidden_input_html = ""
        if per_turn_ratings:
            schema_name = html.escape(per_turn_ratings.get("schema_name", "per_turn_ratings"), quote=True)
            hidden_input_html = f'''
            <input type="hidden" class="annotation-data-input"
                   name="{schema_name}"
                   id="per-turn-ratings-{field_key}"
                   value="" />
            '''

        # Wrap in container
        container_classes = ["dialogue-display-content"]
        if is_span_target:
            container_classes.append("span-target-dialogue")
        if per_turn_ratings:
            container_classes.append("has-per-turn-ratings")

        return f'''
        <div class="{' '.join(container_classes)}" data-field-key="{field_key}">
            {all_turns_html}
            {hidden_input_html}
        </div>
        '''

    def _render_turn_rating(self, field_key: str, turn_index: int, rating_config: Dict[str, Any]) -> str:
        """
        Render an inline rating widget for a dialogue turn.

        Args:
            field_key: The field key for the dialogue
            turn_index: The index of the turn
            rating_config: Configuration for the rating widget

        Returns:
            HTML string for the rating widget
        """
        rating_type = rating_config.get("type", "likert")
        size = rating_config.get("size", 5)
        labels = rating_config.get("labels", [])
        min_label = labels[0] if len(labels) > 0 else ""
        max_label = labels[1] if len(labels) > 1 else ""

        escaped_min = html.escape(str(min_label))
        escaped_max = html.escape(str(max_label))

        # Build rating circles/stars
        rating_items = []
        for v in range(1, size + 1):
            rating_items.append(
                f'<span class="ptr-value" data-field="{field_key}" '
                f'data-turn="{turn_index}" data-value="{v}" '
                f'title="{v}">{v}</span>'
            )

        items_html = "\n".join(rating_items)

        min_html = f'<span class="ptr-label ptr-min">{escaped_min}</span>' if min_label else ""
        max_html = f'<span class="ptr-label ptr-max">{escaped_max}</span>' if max_label else ""

        return f'''
        <div class="per-turn-rating" data-field="{field_key}" data-turn="{turn_index}">
            {min_html}
            <div class="ptr-values">{items_html}</div>
            {max_html}
        </div>
        '''

    def _normalize_dialogue(
        self,
        data: Any,
        speaker_key: str,
        text_key: str,
        speaker_extraction: bool
    ) -> List[Dict[str, str]]:
        """
        Normalize dialogue data to a list of {speaker, text} dicts.

        Args:
            data: Raw dialogue data
            speaker_key: Key for speaker in dict format
            text_key: Key for text in dict format
            speaker_extraction: Whether to extract speaker from text

        Returns:
            List of turn dictionaries
        """
        turns = []

        # Handle string input (newline-separated turns)
        if isinstance(data, str):
            lines = data.strip().split('\n')
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                speaker, text = self._extract_speaker(line) if speaker_extraction else ("", line)
                turns.append({"speaker": speaker, "text": text})

        # Handle list input
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, str):
                    speaker, text = self._extract_speaker(item) if speaker_extraction else ("", item)
                    turns.append({"speaker": speaker, "text": text})
                elif isinstance(item, dict):
                    speaker = item.get(speaker_key, "")
                    text = item.get(text_key, str(item))
                    turns.append({"speaker": speaker, "text": text})
                else:
                    turns.append({"speaker": "", "text": str(item)})

        # Handle single dict (unlikely but possible)
        elif isinstance(data, dict):
            speaker = data.get(speaker_key, "")
            text = data.get(text_key, str(data))
            turns.append({"speaker": speaker, "text": text})

        return turns

    def _extract_speaker(self, text: str) -> tuple:
        """
        Extract speaker from text if it starts with "Speaker:" pattern.

        Args:
            text: The text that may contain a speaker prefix

        Returns:
            Tuple of (speaker, remaining_text)
        """
        import re
        # Match patterns like "Speaker:" or "Speaker 1:" or "User:" at the start
        match = re.match(r'^([A-Za-z0-9_\s]+):\s*(.*)$', text)
        if match:
            return match.group(1).strip(), match.group(2).strip()
        return "", text

    def _get_speaker_index(self, speaker: str, turns: List[Dict[str, str]]) -> int:
        """
        Get a consistent index for a speaker for styling purposes.

        Args:
            speaker: The speaker name
            turns: All turns in the dialogue

        Returns:
            Integer index for the speaker (0, 1, 2, ...)
        """
        if not speaker:
            return 0

        # Get unique speakers in order of first appearance
        seen_speakers = []
        for turn in turns:
            s = turn.get("speaker", "")
            if s and s not in seen_speakers:
                seen_speakers.append(s)

        try:
            return seen_speakers.index(speaker)
        except ValueError:
            return 0

    def get_css_classes(self, field_config: Dict[str, Any]) -> List[str]:
        """Get CSS classes for the container."""
        classes = super().get_css_classes(field_config)
        if field_config.get("span_target"):
            classes.append("span-target-field")
        return classes

    def get_data_attributes(self, field_config: Dict[str, Any], data: Any) -> Dict[str, str]:
        """Get data attributes for the container."""
        attrs = super().get_data_attributes(field_config, data)
        if field_config.get("span_target"):
            attrs["span-target"] = "true"
        return attrs

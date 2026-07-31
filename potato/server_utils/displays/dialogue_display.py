"""
Dialogue Display Type

Renders conversation/dialogue content for display in the annotation interface.
Supports multiple conversation turns with speaker identification and styling.
"""

import html
from datetime import datetime, timezone
from typing import Dict, Any, List, Union

from .base import BaseDisplay

#: Keys copied from a source turn dict in addition to the shared
#: ``_trace_normalize.PASSTHROUGH_KEYS``.
#:
#: These are dialogue concepts — reply structure, wall-clock time, and per-turn
#: source metadata — that the threaded rendering needs. They are deliberately kept
#: local rather than added to ``PASSTHROUGH_KEYS``, which is the shared contract
#: for ``normalize_steps()`` and is consumed by every trace display
#: (``agent_trace``, ``eval_trace``, ``cot_trace``, ``web_agent_trace``,
#: ``coding_trace``, ``multi_agent_discussion``) and snapshotted into stored
#: annotations by ``turn_annotations.build_turn_index()``. Widening that tuple
#: would double-write ``timestamp`` (which ``normalize_steps`` already sets
#: explicitly), leak ``meta``/``reply_to`` into every trace display's step dicts,
#: and bypass the id-specific handling in ``_passthrough(..., skip_ids=True)``.
#: ``id`` is included because plain threaded data (a forum export, a chat log)
#: identifies its messages that way; ``turn_id``/``step_id`` already come through
#: ``PASSTHROUGH_KEYS``. Without it, ``reply_to`` could not be resolved for any
#: source that had not already adopted Potato's own naming.
DIALOGUE_EXTRA_KEYS = (
    "depth", "reply_to", "timestamp", "meta", "is_focus", "index", "id",
)


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
        # --- reply threading and per-turn chrome -------------------------- #
        # All of the following render as CSS pseudo-element content or data
        # attributes, never as text nodes, so they do not change the container's
        # textContent and span offsets stay exactly where they were. See
        # reconstruct_dialogue_dom_text() in base.py, which span extraction in
        # routes.py depends on and which knows only about turn numbers, the
        # speaker prefix, and the turn text.
        "indent_replies": False,
        "max_indent_depth": 6,
        "show_reply_lines": True,
        "show_timestamps": False,
        "timestamp_format": "relative",     # relative | absolute | epoch
        "turn_meta_fields": None,
        "meta_key": "meta",
        "depth_key": "depth",
        "reply_to_key": "reply_to",
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

        indent_replies = options.get("indent_replies", False)
        max_indent_depth = options.get("max_indent_depth", 6)
        show_reply_lines = options.get("show_reply_lines", True)
        show_timestamps = options.get("show_timestamps", False)
        timestamp_format = options.get("timestamp_format", "relative")
        turn_meta_fields = options.get("turn_meta_fields") or []
        meta_key = options.get("meta_key", "meta")
        depth_key = options.get("depth_key", "depth")
        reply_to_key = options.get("reply_to_key", "reply_to")

        # Normalize the dialogue data to a list of turns. The configurable key
        # names are added to the pass-through set so a source that calls its
        # metadata "attributes" or its parent link "in_reply_to" works without
        # being renamed first.
        turns = self._normalize_dialogue(
            data, speaker_key, text_key, speaker_extraction,
            extra_keys=DIALOGUE_EXTRA_KEYS + (meta_key, depth_key, reply_to_key),
        )

        if not turns:
            return '<div class="dialogue-placeholder">No dialogue turns found</div>'

        field_key = html.escape(field_config.get("key", ""), quote=True)
        is_span_target = field_config.get("span_target", False)

        # Turn-level annotation schemes bound to this field (injected by
        # InstanceDisplayRenderer via the internal _turn_schemes key)
        turn_schemes = field_config.get("_turn_schemes") or []

        # Determine which speakers get per-turn ratings
        rated_speakers = set()
        rating_schemes = []
        if per_turn_ratings:
            rated_speakers = set(per_turn_ratings.get("speakers", []))
            # Support both single-scheme and multi-scheme formats
            if "schemes" in per_turn_ratings:
                # New multi-dimension format
                rating_schemes = per_turn_ratings["schemes"]
            elif "scheme" in per_turn_ratings:
                # Legacy single-scheme format: wrap in list
                rating_schemes = [{
                    "schema_name": per_turn_ratings.get("schema_name", "per_turn_ratings"),
                    "scheme": per_turn_ratings["scheme"],
                }]

        # Relative timestamps are measured from the conversation's first turn, so
        # the origin is a property of the whole dialogue, computed once.
        timestamp_origin = (
            self._earliest_timestamp(turns)
            if show_timestamps and timestamp_format == "relative"
            else 0.0
        )

        # Depth is taken from the data when present and derived from reply_to
        # otherwise, so any threaded source works without preprocessing.
        turn_depths = (
            self._derive_depths(turns, depth_key, reply_to_key)
            if indent_replies
            else []
        )

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

            # Per-turn rating widgets (one or more per rated turn)
            rating_html = ""
            if per_turn_ratings and speaker in rated_speakers and rating_schemes:
                if len(rating_schemes) == 1:
                    rating_html = self._render_turn_rating(
                        field_key, i, rating_schemes[0].get("scheme", {}),
                        rating_schemes[0].get("schema_name", "per_turn_ratings")
                    )
                else:
                    # Multi-dimension: wrap multiple ratings in a group
                    parts = []
                    for scheme_entry in rating_schemes:
                        parts.append(self._render_turn_rating(
                            field_key, i, scheme_entry.get("scheme", {}),
                            scheme_entry.get("schema_name", "")
                        ))
                    rating_html = f'<div class="per-turn-rating-group">{"".join(parts)}</div>'

            # Turn-level annotation slot (proxy widgets; real state lives in
            # the scheme's hidden anchor input — see turn_annotations.py)
            slot_html = ""
            if turn_schemes:
                from ..turn_annotations import render_turn_slot
                slot_html = render_turn_slot(turn_schemes, turn, i, field_key)

            # Threading / chrome attributes. Every one of these is an attribute
            # or an inline custom property — never a text node — so the turn's
            # textContent is unchanged and span offsets remain valid.
            chrome_attrs = ""

            if indent_replies:
                depth = turn_depths[i]
                capped = min(depth, max_indent_depth)
                chrome_attrs += f' data-depth="{depth}" style="--turn-depth:{capped}"'

            if reply_to_key in turn and turn[reply_to_key]:
                parent = html.escape(str(turn[reply_to_key]), quote=True)
                chrome_attrs += f' data-reply-to="{parent}"'

            if turn.get("is_focus"):
                chrome_attrs += ' data-focus="true"'

            # The chrome strip (timestamp + metadata chips) is painted by a
            # ::before on the text span, so CSS attr() needs the values on THAT
            # element — attr() only reads its own element's attributes. The turn
            # div gets matching attributes too, because they are what the CSS
            # selectors, the hover-highlight JS, and the tests key off.
            text_chrome_attrs = ""

            if show_timestamps and turn.get("timestamp") not in (None, ""):
                label = self._format_timestamp(
                    turn.get("timestamp"), timestamp_format, timestamp_origin
                )
                if label:
                    escaped_label = html.escape(label, quote=True)
                    chrome_attrs += f' data-timestamp="{escaped_label}"'
                    text_chrome_attrs += f' data-turn-timestamp="{escaped_label}"'

            if turn_meta_fields:
                chips = self._meta_chips(turn.get(meta_key), turn_meta_fields)
                if chips:
                    escaped_chips = html.escape(chips, quote=True)
                    chrome_attrs += f' data-meta-chips="{escaped_chips}"'
                    text_chrome_attrs += f' data-turn-meta-chips="{escaped_chips}"'

            # Whitespace inside a turn is deliberate and minimal: exactly one
            # space between the turn number, the speaker, and the text, and none
            # anywhere else. Span offsets are measured against this element's
            # textContent, and reconstruct_dialogue_dom_text() in base.py has to
            # reproduce it character for character on the server to slice the
            # right substring back out. Indented, pretty-printed HTML injects
            # whitespace text nodes that the server cannot predict, which is
            # exactly how these two drifted apart before. Keep this on one line.
            inner_parts = []
            if turn_number_html:
                inner_parts.append(turn_number_html)
                inner_parts.append(" ")
            if speaker_html:
                inner_parts.append(speaker_html)
                inner_parts.append(" ")
            inner_parts.append(
                f'<span class="dialogue-text" {text_id} {span_attrs}'
                f'{text_chrome_attrs}>{escaped_text}</span>'
            )
            # Both of these are excluded from the offset basis by
            # shouldSkipForOffsets() in static/span-core.js — but only their own
            # subtrees are. Whitespace their templates leave *around* the
            # skipped element is a sibling text node inside the turn and would
            # count, so strip it.
            inner_parts.append(rating_html.strip())
            inner_parts.append(slot_html.strip())

            turn_html = (
                f'<div class="{" ".join(turn_classes)}" '
                f'data-speaker-index="{speaker_index}"{chrome_attrs}>'
                f'{"".join(inner_parts)}</div>'
            )
            turn_html_list.append(turn_html)

        # Turns are separated by exactly one newline, mirrored by the server-side
        # reconstruction. See TURN_SEPARATOR in displays/base.py.
        all_turns_html = "\n".join(turn_html_list)

        # For span annotation, wrap in .text-content WITHOUT data-original-text.
        # Dialogue DOM textContent (with turn numbers, speaker prefixes, whitespace)
        # differs from concatenate_dialogue_text() output.  By omitting the attribute,
        # getCanonicalText() falls back to container.textContent, so offsets from
        # selection and from canonicalText always agree.
        if is_span_target:
            escaped_key = html.escape(field_key, quote=True)
            all_turns_html = (
                f'<div class="text-content" id="text-content-{escaped_key}"'
                f' style="position: relative; padding-top: 24px;">'
                f'{all_turns_html}'
                f'</div>'
            )

        # Hidden inputs for storing per-turn rating data (one per scheme)
        hidden_input_html = ""
        if per_turn_ratings and rating_schemes:
            hidden_parts = []
            for scheme_entry in rating_schemes:
                schema_name = html.escape(
                    scheme_entry.get("schema_name", "per_turn_ratings"), quote=True
                )
                hidden_parts.append(
                    f'<input type="hidden" class="annotation-data-input per-turn-hidden"'
                    f' name="{schema_name}"'
                    f' id="per-turn-ratings-{field_key}-{schema_name}"'
                    f' data-schema-name="{schema_name}"'
                    f' value="" />'
                )
            hidden_input_html = "\n".join(hidden_parts)

        # Wrap in container
        container_classes = ["dialogue-display-content"]
        if is_span_target:
            container_classes.append("span-target-dialogue")
        if per_turn_ratings:
            container_classes.append("has-per-turn-ratings")
        # The chrome is drawn by CSS keyed off these container classes, so it can
        # be toggled without touching markup — and so it stays in ::before/::after
        # content, out of textContent.
        if indent_replies:
            container_classes.append("indent-replies")
            if show_reply_lines:
                container_classes.append("show-reply-lines")
        if show_timestamps:
            container_classes.append("show-timestamps")
        if turn_meta_fields:
            container_classes.append("show-meta-chips")

        return f'''
        <div class="{' '.join(container_classes)}" data-field-key="{field_key}">
            {all_turns_html}
            {hidden_input_html}
        </div>
        '''

    #: Keys checked, in order, when a turn needs an identity for reply linking.
    #: ``turn_id`` is the turn-annotation framework's key; ``step_id`` is the
    #: trace displays'; ``id`` is what plain hand-written data tends to use.
    IDENTITY_KEYS = ("turn_id", "step_id", "id")

    @classmethod
    def _turn_identity(cls, turn: Dict[str, Any]) -> Any:
        for key in cls.IDENTITY_KEYS:
            value = turn.get(key)
            if value not in (None, ""):
                return value
        return None

    @classmethod
    def _derive_depths(
        cls, turns: List[Dict[str, Any]], depth_key: str, reply_to_key: str
    ) -> List[int]:
        """Depth per turn, taken from the data or computed from ``reply_to``.

        Threaded data does not always arrive with depth precomputed. A forum
        export, a chat log, or a hand-written fixture typically has only "this
        message replies to that one", so the display resolves the nesting itself
        rather than requiring every producer to do it.

        An explicit depth on any turn wins outright — a producer that computed
        depth knows something the display cannot, such as the position of a
        subtree that was sliced out of a larger thread and whose parents are not
        present here.

        Cycles and parents pointing outside the rendered turns both resolve to
        depth 0 rather than raising: real threaded data contains both, and a
        conversation that renders flat is better than one that does not render.
        """
        explicit = []
        for turn in turns:
            raw = turn.get(depth_key)
            if raw is None:
                explicit.append(None)
                continue
            try:
                explicit.append(max(0, int(raw)))
            except (TypeError, ValueError):
                explicit.append(None)
        if any(d is not None for d in explicit):
            return [d if d is not None else 0 for d in explicit]

        index_by_id = {}
        for i, turn in enumerate(turns):
            identity = cls._turn_identity(turn)
            if identity is not None and identity not in index_by_id:
                index_by_id[identity] = i

        depths = [0] * len(turns)
        for i, turn in enumerate(turns):
            depth = 0
            seen = {i}
            parent = turn.get(reply_to_key)
            while parent not in (None, "") and depth <= len(turns):
                parent_index = index_by_id.get(parent)
                if parent_index is None or parent_index in seen:
                    break
                seen.add(parent_index)
                depth += 1
                parent = turns[parent_index].get(reply_to_key)
            depths[i] = depth
        return depths

    @staticmethod
    def _earliest_timestamp(turns: List[Dict[str, Any]]) -> float:
        """The conversation's start, used as the origin for relative times."""
        stamps = []
        for turn in turns:
            value = turn.get("timestamp")
            if value in (None, ""):
                continue
            try:
                stamps.append(float(value))
            except (TypeError, ValueError):
                continue
        return min(stamps) if stamps else 0.0

    @staticmethod
    def _format_timestamp(value: Any, style: str, origin: float) -> str:
        """Render a timestamp for display as pseudo-element content.

        ConvoKit timestamps are epoch seconds. ``relative`` shows the offset from
        the first turn, which is what matters when reading a thread; ``absolute``
        shows a UTC wall-clock date; ``epoch`` shows the raw number.
        """
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            return ""

        if style == "epoch":
            return str(value)

        if style == "absolute":
            try:
                return datetime.fromtimestamp(seconds, tz=timezone.utc).strftime(
                    "%Y-%m-%d %H:%M"
                )
            except (OverflowError, OSError, ValueError):
                return str(value)

        delta = seconds - origin
        if delta < 0:
            # Out-of-order timestamps happen in real corpora; showing a negative
            # offset is more honest than clamping it to zero.
            return f"-{DialogueDisplay._humanize(-delta)}"
        if delta < 1:
            return "start"
        return f"+{DialogueDisplay._humanize(delta)}"

    @staticmethod
    def _humanize(seconds: float) -> str:
        if seconds < 60:
            return f"{int(seconds)}s"
        if seconds < 3600:
            return f"{int(seconds // 60)}m"
        if seconds < 86400:
            return f"{int(seconds // 3600)}h"
        return f"{int(seconds // 86400)}d"

    @staticmethod
    def _meta_chips(meta: Any, fields: List[str]) -> str:
        """Render selected per-turn metadata as one compact attribute string.

        Kept as a single attribute rather than per-chip elements so it can be
        drawn entirely by a single ``::before``, contributing nothing to
        textContent.
        """
        if not isinstance(meta, dict):
            return ""
        parts = []
        for name in fields:
            if name not in meta:
                continue
            value = meta[name]
            if value is None or isinstance(value, (dict, list)):
                continue
            if isinstance(value, float):
                value = f"{value:.3g}"
            elif isinstance(value, bool):
                value = "true" if value else "false"
            parts.append(f"{name}: {value}")
        return "  ·  ".join(parts)

    def _render_turn_rating(self, field_key: str, turn_index: int,
                           rating_config: Dict[str, Any],
                           schema_name: str = "") -> str:
        """
        Render an inline rating widget for a dialogue turn.

        Args:
            field_key: The field key for the dialogue
            turn_index: The index of the turn
            rating_config: Configuration for the rating widget
            schema_name: Schema name for multi-dimension support

        Returns:
            HTML string for the rating widget
        """
        size = rating_config.get("size", 5)
        labels = rating_config.get("labels", [])
        min_label = labels[0] if len(labels) > 0 else ""
        max_label = labels[1] if len(labels) > 1 else ""

        escaped_min = html.escape(str(min_label))
        escaped_max = html.escape(str(max_label))
        escaped_schema = html.escape(str(schema_name), quote=True)

        # Build rating circles/stars
        rating_items = []
        for v in range(1, size + 1):
            rating_items.append(
                f'<span class="ptr-value" data-field="{field_key}" '
                f'data-turn="{turn_index}" data-value="{v}" '
                f'data-schema="{escaped_schema}" '
                f'title="{v}">{v}</span>'
            )

        items_html = "\n".join(rating_items)

        min_html = f'<span class="ptr-label ptr-min">{escaped_min}</span>' if min_label else ""
        max_html = f'<span class="ptr-label ptr-max">{escaped_max}</span>' if max_label else ""

        # Schema label for multi-dimension mode
        schema_label_html = ""
        if schema_name:
            readable_name = schema_name.replace("_", " ").title()
            escaped_readable = html.escape(readable_name)
            schema_label_html = f'<span class="ptr-schema-label">{escaped_readable}:</span>'

        return f'''
        <div class="per-turn-rating" data-field="{field_key}" data-turn="{turn_index}" data-schema="{escaped_schema}">
            {schema_label_html}
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
        speaker_extraction: bool,
        extra_keys: tuple = DIALOGUE_EXTRA_KEYS,
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
                    turn = {"speaker": speaker, "text": text}
                    # Pass through identity keys (turn-level bindings +
                    # multi-agent displays consume these), plus the dialogue-only
                    # keys the threaded rendering needs (see DIALOGUE_EXTRA_KEYS).
                    from ._trace_normalize import PASSTHROUGH_KEYS
                    for key in tuple(PASSTHROUGH_KEYS) + tuple(extra_keys):
                        if key in item and item[key] not in (None, ""):
                            turn[key] = item[key]
                    turns.append(turn)
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

"""
Audio Dialogue Display Type (podcast / interview turn annotation).

Renders a spoken multi-speaker transcript as a **chat of colored speaker
bubbles** with a synced audio player.  Each turn carries a start/end time and a
per-turn ▶ button that plays *just that turn's* audio; a sticky transport bar at
the top plays the whole episode and highlights / auto-scrolls the active turn.

It combines existing Potato subsystems rather than inventing new ones:

* **Transcript ingestion** — the field value is normalized by
  :func:`potato.server_utils.transcript_ingest.normalize_transcript`, so native
  turn JSON, WhisperX / diarized JSON, plain Whisper JSON, and VTT/SRT strings
  all render.
* **Per-turn ratings** — via the turn-level framework (``turn_level: true`` +
  ``turn_binding``); this display consumes the injected ``_turn_schemes`` and
  calls :func:`render_turn_slot` per turn, exactly like ``dialogue`` /
  ``multi_agent_discussion``.
* **Span highlighting + cross-turn linking** — via the standard span-target
  contract (single ``.text-content`` wrapper); ``span`` + ``span_link`` schemes
  work unchanged.
* **Speaker assignment (undiarized transcripts)** — turns with no speaker render
  as an *unassigned* bubble with a speaker picker.  The assignment is persisted
  in a display-emitted hidden ``annotation-data-input`` (name
  ``{field_key}_speakers``) that round-trips through the standard ``_data``
  pipeline — the same mechanism dialogue ``per_turn_ratings`` uses.

**Span-offset stability contract.**  Span offsets are computed over the whole
``.text-content`` textContent (see span-core.js ``getOffsetsFromSelection``).
Speaker assignment recolors / repositions / renames a bubble, so any *mutable*
chrome text inside the container would shift offsets.  To keep offsets stable
across assignment and reload, all mutable chrome (avatar initial, speaker name,
timestamp, play glyph) is rendered as **CSS pseudo-content from data attributes**
— visuals change without mutating ``textContent`` — and repositioning is CSS
alignment only (DOM order is never changed).  The sticky audio bar (whose time
readout mutates during playback) lives *outside* ``.text-content``.

Client behavior (transport, per-turn play, auto-scroll, speaker assignment
persistence) lives in ``potato/static/audio-dialogue.js`` / ``audio-dialogue.css``.
"""

import html
import json
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseDisplay
from .multi_agent_discussion_display import agent_color, readable_text_on

# Neutral swatch for an unassigned (undiarized) turn before the annotator picks.
UNASSIGNED_COLOR = "#9ca3af"


class AudioDialogueDisplay(BaseDisplay):
    """Display type for audio dialogue / podcast turn annotation."""

    name = "audio_dialogue"
    required_fields = ["key"]
    optional_fields = {
        "audio_key": "audio",
        "turns_key": "turns",
        "speaker_key": "speaker",
        "text_key": "text",
        "speakers": [],            # roster: [{id, name, color, side}]
        "allow_speaker_assignment": "auto",  # "auto" | True | False
        "scroll_height": "480px",
        "show_timestamps": True,
        "playback_rates": [1, 1.25, 1.5, 2],
    }
    description = "Podcast / interview dialogue: speaker bubbles, per-turn audio playback, ratings, spans"
    supports_span_target = True

    # -- render -------------------------------------------------------------

    def render(self, field_config: Dict[str, Any], data: Any) -> str:
        options = self.get_display_options(field_config)
        from ..transcript_ingest import normalize_transcript

        norm = normalize_transcript(
            data,
            audio_key=options.get("audio_key", "audio"),
            turns_key=options.get("turns_key", "turns"),
            speaker_key=options.get("speaker_key", "speaker"),
            text_key=options.get("text_key", "text"),
        )
        audio = norm.get("audio")
        turns = norm.get("turns") or []

        field_key = str(field_config.get("key", ""))
        esc_field = html.escape(field_key, quote=True)
        is_span_target = bool(field_config.get("span_target"))
        turn_schemes = field_config.get("_turn_schemes") or []
        show_timestamps = options.get("show_timestamps", True)

        if not turns:
            return '<div class="ad-placeholder">No dialogue turns provided</div>'

        roster = self._resolve_roster(options.get("speakers") or [], turns)
        allow_assignment = self._resolve_allow_assignment(
            options.get("allow_speaker_assignment", "auto"), turns, roster
        )

        # Root config + roster for the client (colors/sides/names per speaker id).
        roster_json = html.escape(json.dumps({
            k: {"name": v["name"], "color": v["color"], "side": v["side"], "on": v["on"]}
            for k, v in roster.items()
        }), quote=True)
        config_json = html.escape(json.dumps({
            "field_key": field_key,
            "allow_assignment": allow_assignment,
            "unassigned_color": UNASSIGNED_COLOR,
        }), quote=True)

        audio_bar = self._render_audio_bar(esc_field, audio, options)
        legend = self._render_legend(roster)

        bubbles = [
            self._render_turn(
                turn, i, esc_field, roster, is_span_target,
                turn_schemes, field_key, show_timestamps, allow_assignment,
            )
            for i, turn in enumerate(turns)
        ]
        turns_html = "\n".join(bubbles)

        # Span-target contract: one .text-content wrapper, NO container-level
        # data-original-text (offsets fall back to normalized textContent, which
        # agrees with selection). Mirrors dialogue / multi_agent_discussion.
        if is_span_target:
            turns_html = (
                f'<div class="text-content ad-text-content" id="text-content-{esc_field}"'
                f' style="position: relative; padding-top: 24px;">{turns_html}</div>'
            )

        scroll_style = f"max-height: {html.escape(str(options.get('scroll_height', '480px')), quote=True)};"

        # Hidden speaker-assignment store + the click-to-assign popover menu.
        # Both live OUTSIDE .text-content so neither their value nor the menu's
        # (runtime-growing) option text ever pollutes span offsets.
        speaker_input = ""
        speaker_menu = ""
        if allow_assignment:
            speaker_input = (
                f'<input type="hidden" class="annotation-data-input ad-speaker-input"'
                f' name="{esc_field}_speakers" id="ad-speakers-{esc_field}"'
                f' data-schema-name="{esc_field}_speakers" value="">'
            )
            speaker_menu = (
                f'<div class="ad-speaker-menu" id="ad-menu-{esc_field}" role="menu" hidden></div>'
            )

        return f'''
        <div class="audio-dialogue" data-field-key="{esc_field}"
             data-ad-config="{config_json}" data-ad-roster="{roster_json}">
            {audio_bar}
            {speaker_input}
            {speaker_menu}
            {legend}
            <div class="ad-scroll" id="ad-scroll-{esc_field}" style="{scroll_style}">
                {turns_html}
            </div>
        </div>
        '''

    # -- pieces -------------------------------------------------------------

    def _render_audio_bar(self, esc_field: str, audio: Optional[str], options: Dict[str, Any]) -> str:
        rates = options.get("playback_rates") or [1]
        rate_opts = "".join(
            f'<option value="{float(r)}"{" selected" if float(r) == 1.0 else ""}>{self._fmt_rate(r)}</option>'
            for r in rates
        )
        src = ""
        if audio:
            src = f' src="{html.escape(str(audio), quote=True)}"'
        # aria-hidden decorative glyphs are CSS pseudo-content (see CSS); the bar
        # is intentionally OUTSIDE .text-content.
        return f'''
        <div class="ad-audiobar" data-field-key="{esc_field}">
            <audio id="ad-audio-{esc_field}" class="ad-audio" preload="metadata"{src}></audio>
            <button type="button" class="ad-transport ad-playpause" data-field-key="{esc_field}"
                    aria-label="Play or pause"></button>
            <button type="button" class="ad-transport ad-stop" data-field-key="{esc_field}"
                    aria-label="Stop"></button>
            <div class="ad-scrubwrap">
                <input type="range" class="ad-scrub" data-field-key="{esc_field}"
                       min="0" max="1000" value="0" step="1" aria-label="Seek">
            </div>
            <span class="ad-clock" data-field-key="{esc_field}"><span class="ad-cur">0:00</span> / <span class="ad-dur">0:00</span></span>
            <label class="ad-rate-wrap">Speed
                <select class="ad-rate" data-field-key="{esc_field}" aria-label="Playback speed">{rate_opts}</select>
            </label>
        </div>
        '''

    def _render_legend(self, roster: Dict[str, Dict[str, Any]]) -> str:
        if len(roster) < 2:
            return ""
        chips = []
        for sid, info in roster.items():
            color = info["color"]
            chips.append(
                f'<span class="ad-legend-chip" style="--ad-color:{color};">'
                f'<span class="ad-legend-dot" style="background:{color};"></span>'
                f'{html.escape(info["name"])}</span>'
            )
        return f'<div class="ad-legend">{"".join(chips)}</div>'

    def _render_turn(
        self,
        turn: Dict[str, Any],
        index: int,
        esc_field: str,
        roster: Dict[str, Dict[str, Any]],
        is_span_target: bool,
        turn_schemes: List[Dict[str, Any]],
        field_key: str,
        show_timestamps: bool,
        allow_assignment: bool,
    ) -> str:
        from ..turn_annotations import turn_id_for

        tid = turn_id_for(turn, index)
        esc_tid = html.escape(str(tid), quote=True)
        speaker = turn.get("speaker")
        text = str(turn.get("text", ""))
        start = float(turn.get("start", 0) or 0)
        end = float(turn.get("end", start) or start)

        assigned = speaker is not None and str(speaker) != ""
        if assigned:
            info = roster.get(str(speaker)) or self._auto_info(str(speaker), 0)
            color = info["color"]
            name = info["name"]
            side = info["side"]
            on_color = info["on"]
        else:
            color = UNASSIGNED_COLOR
            name = "Unassigned"
            side = "left"
            on_color = readable_text_on(UNASSIGNED_COLOR)

        initial = (name[:1].upper() if name else "?")
        time_label = f"{self._fmt_time(start)}–{self._fmt_time(end)}" if show_timestamps else ""
        # Speaker/time are shown via CSS pseudo-content (offset-stability), so
        # fold them into the play button's aria-label for screen readers.
        play_aria = f"Play this turn by {name}" + (f", {time_label}" if time_label else "")

        classes = ["ad-turn", f"ad-side-{side}"]
        if not assigned:
            classes.append("ad-unassigned")

        # Chrome uses CSS pseudo-content (data-* attrs) so speaker assignment
        # never mutates .text-content offsets. See module docstring.
        esc_text = html.escape(text)
        text_attrs = ""
        if is_span_target:
            text_attrs = (
                f' id="ad-text-{esc_field}-{index}"'
                f' data-original-text="{html.escape(text, quote=True)}"'
                f' data-turn-index="{index}"'
            )

        slot_html = ""
        if turn_schemes:
            from ..turn_annotations import render_turn_slot
            slot_html = render_turn_slot(turn_schemes, turn, index, field_key)

        # Avatar + name. When assignment is enabled the pair becomes a button
        # that opens the speaker menu (click the speaker to change it — works on
        # any turn, diarized or not). The button has no text node of its own
        # (avatar/name are pseudo-content), so it never affects span offsets.
        avatar_html = f'<span class="ad-avatar" data-initial="{html.escape(initial, quote=True)}" aria-hidden="true"></span>'
        name_html = f'<span class="ad-speaker-name" data-name="{html.escape(name, quote=True)}"></span>'
        if allow_assignment:
            change_aria = f"Speaker: {name}. Click to change."
            speaker_control = (
                f'<button type="button" class="ad-speaker-btn" data-turn-id="{esc_tid}"'
                f' data-field-key="{esc_field}" aria-haspopup="menu" aria-expanded="false"'
                f' aria-label="{html.escape(change_aria, quote=True)}">'
                f'{avatar_html}{name_html}'
                f'<span class="ad-speaker-caret" aria-hidden="true"></span></button>'
            )
        else:
            speaker_control = f'{avatar_html}{name_html}'

        return f'''
        <div class="{' '.join(classes)}" data-turn-id="{esc_tid}" data-turn-index="{index}"
             data-speaker="{html.escape(str(speaker) if assigned else '', quote=True)}"
             data-assigned="{'true' if assigned else 'false'}"
             style="--ad-color:{color}; --ad-on:{on_color};">
            <div class="ad-turn-header">
                <button type="button" class="ad-play" data-start="{start:.3f}" data-end="{end:.3f}"
                        data-field-key="{esc_field}" aria-label="{html.escape(play_aria, quote=True)}"></button>
                {speaker_control}
                <span class="ad-time" data-time="{html.escape(time_label, quote=True)}" aria-hidden="true"></span>
            </div>
            <span class="ad-text"{text_attrs}>{esc_text}</span>
            {slot_html}
        </div>
        '''

    # -- roster / speakers --------------------------------------------------

    def _resolve_roster(
        self, config_speakers: List[Any], turns: List[Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        """Ordered map ``speaker_id -> {name, color, side}`` for every speaker
        known from config or appearing in the data. Config entries win; unlisted
        speakers get a deterministic color and alternating side."""
        roster: Dict[str, Dict[str, Any]] = {}

        for entry in config_speakers:
            if not isinstance(entry, dict):
                continue
            sid = str(entry.get("id") or entry.get("name") or "").strip()
            if not sid:
                continue
            side = str(entry.get("side", "")).lower()
            if side not in ("left", "right"):
                side = "left" if len(roster) % 2 == 0 else "right"
            color = str(entry.get("color") or agent_color(sid))
            roster[sid] = {
                "name": str(entry.get("name") or sid),
                "color": color,
                "side": side,
                "on": readable_text_on(color),
            }

        # Fold in speakers that appear in the data but aren't rostered.
        unlisted_index = sum(1 for v in roster.values())
        for turn in turns:
            sp = turn.get("speaker")
            if sp in (None, ""):
                continue
            sid = str(sp)
            if sid in roster:
                continue
            roster[sid] = self._auto_info(sid, unlisted_index)
            unlisted_index += 1
        return roster

    def _auto_info(self, sid: str, order_index: int) -> Dict[str, Any]:
        color = agent_color(sid)
        return {
            "name": sid,
            "color": color,
            "side": "left" if order_index % 2 == 0 else "right",
            "on": readable_text_on(color),
        }

    def _resolve_allow_assignment(
        self, setting: Any, turns: List[Dict[str, Any]], roster: Dict[str, Dict[str, Any]]
    ) -> bool:
        if setting is True:
            return True
        if setting is False:
            return False
        # "auto": enable click-to-assign whenever there is anything to do —
        # undiarized turns to label, or a roster whose diarized labels the
        # annotator may want to correct. Annotators can always add new speakers.
        has_unassigned = any(t.get("speaker") in (None, "") for t in turns)
        return has_unassigned or bool(roster)

    # -- formatting ---------------------------------------------------------

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        seconds = max(0, int(round(seconds)))
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    @staticmethod
    def _fmt_rate(r: Any) -> str:
        f = float(r)
        return (f"{f:g}×")

    # -- container hooks ----------------------------------------------------

    def get_css_classes(self, field_config: Dict[str, Any]) -> List[str]:
        classes = super().get_css_classes(field_config)
        if field_config.get("span_target"):
            classes.append("span-target-field")
        return classes

    def get_data_attributes(self, field_config: Dict[str, Any], data: Any) -> Dict[str, str]:
        attrs = super().get_data_attributes(field_config, data)
        if field_config.get("span_target"):
            attrs["span-target"] = "true"
        return attrs

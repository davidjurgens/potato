"""
Eval Trace Display Type

Purpose-built rendering for *continuous agent evaluation*: it takes a single
agent trace and splits it into three synchronized side-by-side panes —

    Reasoning  |  Function Calls  |  Final Answer

so an evaluator can see, at a glance, what the agent thought, what it did, and
what it ultimately produced. Clicking any card highlights the linked cards in
the other panes (a "logical step" links a thought to the calls it triggered).

Unlike ``agent_trace`` (which stacks an interleaved trace vertically in a
single column), ``eval_trace`` decomposes one interleaved trace into its three
semantic components. It consumes the same trace data formats as ``agent_trace``
(see ``_trace_normalize.normalize_steps``), so existing data and trace
converters work unchanged.

Usage:
    In instance_display config:
    fields:
      - key: trace
        type: eval_trace
        display_options:
          pane_labels: ["Reasoning", "Function Calls", "Final Answer"]
          show_step_numbers: true
          collapse_long_outputs: true
          max_output_lines: 20
          link_steps: true
          compact: false

Data contract:
    A single trace under the field key, in any format ``normalize_steps``
    accepts. Step types map to panes as:
        thought / system        -> Reasoning
        action                  -> Function Calls (with adjacent observation
                                   rendered as a nested "↳ result")
        observation             -> nested under its preceding call
    The Final Answer pane shows the trace's answer-like step (a step whose
    speaker/tool matches "final answer", "send_message", "respond", etc.),
    falling back to the last action. Make an explicit final answer by ending
    the trace with a step whose speaker is e.g. "Agent (Final Answer)".
"""

import html
import re
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseDisplay
from ._trace_normalize import normalize_steps


# Speaker labels / tool names that mark a step as the final answer to the user.
ANSWER_PATTERN = re.compile(
    r"(final[\s_]*answer|send[\s_]*message|respond|response|finish|submit|conclusion)",
    re.IGNORECASE,
)

DEFAULT_PANE_LABELS = ["Reasoning", "Function Calls", "Final Answer"]


def _escape(text: Any) -> str:
    """HTML-escape any value."""
    return html.escape(str(text), quote=True)


def _truncate(text: str, max_lines: int) -> Tuple[str, bool]:
    """Truncate text to ``max_lines`` lines; return (text, was_truncated)."""
    if not text or max_lines <= 0:
        return text, False
    lines = text.split("\n")
    if len(lines) <= max_lines:
        return text, False
    return "\n".join(lines[:max_lines]), True


def _tool_name(action_text: str) -> str:
    """Extract the tool/function name from a ``tool(args)`` action string."""
    if "(" in action_text:
        return action_text.split("(", 1)[0].strip()
    return action_text.strip()


class EvalTraceDisplay(BaseDisplay):
    """Three-pane (reasoning | function calls | final answer) trace display."""

    name = "eval_trace"
    required_fields = ["key"]
    optional_fields = {
        "pane_labels": DEFAULT_PANE_LABELS,
        "show_step_numbers": True,
        "collapse_long_outputs": True,
        "max_output_lines": 20,
        "link_steps": True,
        "compact": False,
        "speaker_key": "speaker",
        "text_key": "text",
    }
    description = "Three-pane agent trace eval: reasoning, function calls, and final answer side-by-side"
    # Per-pane card IDs do not follow the single .text-content wrapper contract
    # required by SpanManager, so span annotation is not supported (yet).
    supports_span_target = False

    def render(self, field_config: Dict[str, Any], data: Any) -> str:
        field_key = _escape(field_config.get("key", ""))

        if not data:
            return self._placeholder(field_key, "No trace data provided")

        options = self.get_display_options(field_config)
        pane_labels = self._resolve_pane_labels(options.get("pane_labels"))
        speaker_key = options.get("speaker_key", "speaker")
        text_key = options.get("text_key", "text")

        steps = normalize_steps(data, speaker_key, text_key)
        if not steps:
            return self._placeholder(field_key, "No trace steps found")

        answer_idx = self._find_answer_step(steps)
        groups = self._build_groups(steps, exclude_idx=answer_idx)

        show_numbers = options.get("show_step_numbers", True)
        collapse = options.get("collapse_long_outputs", True)
        max_lines = options.get("max_output_lines", 20)
        link_steps = options.get("link_steps", True)
        compact = options.get("compact", False)

        reasoning_html = self._render_reasoning_pane(groups, show_numbers, link_steps)
        calls_html = self._render_calls_pane(
            groups, show_numbers, link_steps, collapse, max_lines
        )
        answer_html = self._render_answer_pane(
            steps[answer_idx] if answer_idx is not None else None
        )

        css = self._build_css(compact)
        link_attr = ' data-link-steps="true"' if link_steps else ""

        panes = [
            self._wrap_pane("reasoning", pane_labels[0], reasoning_html),
            self._wrap_pane("calls", pane_labels[1], calls_html),
            self._wrap_pane("answer", pane_labels[2], answer_html),
        ]

        js = self._build_js(field_key) if link_steps else ""

        return f'''
        <style>{css}</style>
        <div class="eval-trace-display" data-field-key="{field_key}"{link_attr}>
            <div class="eval-trace-panes">
                {"".join(panes)}
            </div>
        </div>
        <script>{js}</script>
        '''

    # ----- pane assembly --------------------------------------------------

    def _wrap_pane(self, pane_id: str, label: str, body_html: str) -> str:
        if not body_html.strip():
            body_html = '<div class="eval-empty">—</div>'
        return (
            f'<section class="eval-pane eval-pane-{pane_id}">'
            f'<header class="eval-pane-header">{_escape(label)}</header>'
            f'<div class="eval-pane-body">{body_html}</div>'
            f'</section>'
        )

    def _render_reasoning_pane(
        self, groups: List[Dict[str, Any]], show_numbers: bool, link: bool
    ) -> str:
        cards = []
        for g in groups:
            if not g["thoughts"]:
                continue
            idx = g["index"]
            num_html = (
                f'<span class="eval-step-num">#{idx + 1}</span>' if show_numbers else ""
            )
            for step in g["thoughts"]:
                step_type = _escape(step.get("type", "thought"))
                text = _escape(step.get("text", ""))
                cards.append(
                    f'<div class="eval-card eval-card-{step_type}"'
                    f'{self._link_attr(idx, link)}>'
                    f'<div class="eval-card-head">{num_html}'
                    f'<span class="eval-badge badge-{step_type}">'
                    f'{_escape(step.get("speaker") or step_type.capitalize())}</span></div>'
                    f'<div class="eval-card-text">{text}</div>'
                    f'</div>'
                )
        return "\n".join(cards)

    def _render_calls_pane(
        self,
        groups: List[Dict[str, Any]],
        show_numbers: bool,
        link: bool,
        collapse: bool,
        max_lines: int,
    ) -> str:
        cards = []
        for g in groups:
            if not g["calls"]:
                continue
            idx = g["index"]
            num_html = (
                f'<span class="eval-step-num">#{idx + 1}</span>' if show_numbers else ""
            )
            for call in g["calls"]:
                call_step = call["call"]
                results = call["results"]

                if call_step is not None:
                    action_text = str(call_step.get("text", ""))
                    tool = _escape(_tool_name(action_text))
                    call_line = (
                        f'<div class="eval-call-line">'
                        f'<span class="eval-tool-badge">{tool}</span>'
                        f'<code class="eval-call-code">{_escape(action_text)}</code>'
                        f'</div>'
                    )
                else:
                    call_line = ""

                results_html = "".join(
                    self._render_result(r, collapse, max_lines) for r in results
                )

                cards.append(
                    f'<div class="eval-card eval-card-action"'
                    f'{self._link_attr(idx, link)}>'
                    f'<div class="eval-card-head">{num_html}</div>'
                    f'{call_line}{results_html}'
                    f'</div>'
                )
        return "\n".join(cards)

    def _render_result(self, step: Dict[str, Any], collapse: bool, max_lines: int) -> str:
        text = str(step.get("text", ""))
        if not text:
            return ""
        truncated, was_truncated = _truncate(text, max_lines)
        if was_truncated and collapse:
            n = len(text.splitlines())
            return (
                f'<details class="eval-result">'
                f'<summary>↳ result ({n} lines — expand)</summary>'
                f'<pre class="eval-result-pre">{_escape(text)}</pre>'
                f'</details>'
            )
        return (
            f'<div class="eval-result">'
            f'<span class="eval-result-arrow">↳</span>'
            f'<pre class="eval-result-pre">{_escape(truncated)}</pre>'
            f'</div>'
        )

    def _render_answer_pane(self, answer_step: Optional[Dict[str, Any]]) -> str:
        if not answer_step:
            return '<div class="eval-empty">No final answer in trace</div>'
        text = str(answer_step.get("text", ""))
        return f'<div class="eval-card eval-card-answer"><div class="eval-card-text">{_escape(text)}</div></div>'

    # ----- grouping / answer detection -----------------------------------

    def _find_answer_step(self, steps: List[Dict[str, Any]]) -> Optional[int]:
        """Return the index of the step that is the final answer, or None.

        Preference order: the last step whose speaker or tool name matches an
        answer pattern; otherwise the last ``action`` step; otherwise None.
        """
        answer_idx = None
        last_action_idx = None
        for i, step in enumerate(steps):
            stype = step.get("type", "")
            speaker = str(step.get("speaker", ""))
            text = str(step.get("text", ""))
            if stype == "action":
                last_action_idx = i
                if ANSWER_PATTERN.search(speaker) or ANSWER_PATTERN.search(_tool_name(text)):
                    answer_idx = i
            elif ANSWER_PATTERN.search(speaker):
                # An explicit "Final Answer" turn that isn't typed as an action.
                answer_idx = i
        if answer_idx is not None:
            return answer_idx
        return last_action_idx

    def _build_groups(
        self, steps: List[Dict[str, Any]], exclude_idx: Optional[int]
    ) -> List[Dict[str, Any]]:
        """Group steps into logical cycles linking thoughts to their calls.

        A new group starts on a ``thought`` that follows a completed cycle (one
        that already has calls), so consecutive thoughts stay together and the
        thought(s) preceding a call share that call's group index.
        """
        groups: List[Dict[str, Any]] = []
        current: Optional[Dict[str, Any]] = None

        def new_group() -> Dict[str, Any]:
            g = {"index": len(groups), "thoughts": [], "calls": []}
            groups.append(g)
            return g

        for i, step in enumerate(steps):
            if exclude_idx is not None and i == exclude_idx:
                continue
            stype = step.get("type", "observation")

            if stype == "thought":
                if current is None or current["calls"]:
                    current = new_group()
                current["thoughts"].append(step)
            elif stype == "action":
                if current is None:
                    current = new_group()
                current["calls"].append({"call": step, "results": []})
            elif stype == "observation":
                if current is None:
                    current = new_group()
                if current["calls"]:
                    current["calls"][-1]["results"].append(step)
                else:
                    current["calls"].append({"call": None, "results": [step]})
            else:  # system / error → treat as a reasoning-side note
                if current is None:
                    current = new_group()
                current["thoughts"].append(step)

        return groups

    # ----- helpers --------------------------------------------------------

    def _resolve_pane_labels(self, labels: Any) -> List[str]:
        """Coerce ``pane_labels`` to exactly three strings, padding defaults."""
        if not isinstance(labels, (list, tuple)):
            return list(DEFAULT_PANE_LABELS)
        result = [str(l) for l in labels[:3]]
        while len(result) < 3:
            result.append(DEFAULT_PANE_LABELS[len(result)])
        return result

    def _link_attr(self, idx: int, link: bool) -> str:
        """Attributes that make a card a linkable, accessible button.

        When linking is on, the card is an ARIA button that highlights the
        steps sharing its index across panes. When off, the card carries no
        index and is not focusable (it has no behavior to expose).
        """
        if not link:
            return ""
        return (
            f' data-step-index="{idx}" role="button" tabindex="0"'
            f' aria-pressed="false"'
            f' aria-label="Highlight step {idx + 1} across panes"'
        )

    def _placeholder(self, field_key: str, message: str) -> str:
        return (
            f'<div class="eval-trace-display eval-trace-empty" '
            f'data-field-key="{field_key}">{_escape(message)}</div>'
        )

    def validate_config(self, field_config: Dict[str, Any]) -> List[str]:
        errors = super().validate_config(field_config)
        opts = field_config.get("display_options", {}) or {}
        labels = opts.get("pane_labels")
        if labels is not None and not isinstance(labels, (list, tuple)):
            errors.append(
                f"Display type '{self.name}': 'pane_labels' must be a list of "
                f"strings (got {type(labels).__name__})."
            )
        return errors

    def _build_js(self, field_key: str) -> str:
        """Cross-pane highlight: clicking/focusing a card with data-step-index
        toggles the .eval-linked class on all cards sharing that index."""
        return f'''
        (function() {{
            var root = document.querySelector('.eval-trace-display[data-field-key="{field_key}"]');
            if (!root || root.dataset.evalBound) return;
            root.dataset.evalBound = "1";
            function clear() {{
                root.querySelectorAll('.eval-card.eval-linked').forEach(function(c) {{
                    c.classList.remove('eval-linked');
                    if (c.hasAttribute('aria-pressed')) c.setAttribute('aria-pressed', 'false');
                }});
            }}
            function linkTo(idx) {{
                clear();
                if (idx === null || idx === undefined) return;
                root.querySelectorAll('.eval-card[data-step-index="' + idx + '"]').forEach(function(c) {{
                    c.classList.add('eval-linked');
                    if (c.hasAttribute('aria-pressed')) c.setAttribute('aria-pressed', 'true');
                }});
            }}
            root.addEventListener('click', function(e) {{
                var card = e.target.closest('.eval-card[data-step-index]');
                if (!card) {{ clear(); return; }}
                linkTo(card.getAttribute('data-step-index'));
            }});
            root.addEventListener('keydown', function(e) {{
                if (e.key !== 'Enter' && e.key !== ' ') return;
                var card = e.target.closest('.eval-card[data-step-index]');
                if (card) {{ e.preventDefault(); linkTo(card.getAttribute('data-step-index')); }}
            }});
        }})();
        '''

    def _build_css(self, compact: bool) -> str:
        pad = "6px 8px" if compact else "10px 12px"
        gap = "8px" if compact else "12px"
        return f'''
        .eval-trace-display {{ font-family: inherit; width: 100%; }}
        .eval-trace-empty {{ padding: 16px; color: #777; font-style: italic; }}
        .eval-trace-panes {{
            display: flex; gap: {gap}; align-items: stretch; width: 100%;
        }}
        .eval-pane {{
            flex: 1 1 0; min-width: 0; display: flex; flex-direction: column;
            border: 1px solid #e3e6ea; border-radius: 8px; overflow: hidden;
            background: #fff;
        }}
        .eval-pane-header {{
            padding: 8px 12px; font-weight: 600; font-size: 0.85em;
            letter-spacing: 0.02em; text-transform: uppercase; color: #4a5568;
            background: #f7f8fa; border-bottom: 1px solid #e3e6ea;
        }}
        .eval-pane-reasoning .eval-pane-header {{ color: #1565c0; }}
        .eval-pane-calls .eval-pane-header {{ color: #c2410c; }}
        .eval-pane-answer .eval-pane-header {{ color: #2e7d32; }}
        .eval-pane-body {{ padding: {gap}; display: flex; flex-direction: column; gap: {gap}; }}
        .eval-empty {{ color: #aaa; font-size: 0.9em; padding: 4px; }}
        .eval-card {{
            border-radius: 6px; padding: {pad}; border-left: 3px solid #cbd5e0;
            background: #f8fafc; transition: box-shadow .12s, outline .12s;
            outline: 2px solid transparent;
        }}
        /* Only linkable cards are interactive (they carry role=button). */
        .eval-card[role="button"] {{ cursor: pointer; }}
        .eval-card[role="button"]:hover {{ box-shadow: 0 1px 6px rgba(15,23,42,0.12); }}
        .eval-card:focus-visible {{ outline: 2px solid #90cdf4; }}
        .eval-card-thought, .eval-card-system {{ background: #e8f4fd; border-left-color: #2196F3; }}
        .eval-card-action {{ background: #fff3e0; border-left-color: #FF9800; }}
        .eval-card-answer {{ background: #e8f5e9; border-left-color: #4CAF50; }}
        .eval-card-error {{ background: #ffebee; border-left-color: #f44336; }}
        /* Linked-step highlight: an indigo ring distinct from the orange
           action accent, plus a soft lift, so "linked" never reads as "action". */
        .eval-card.eval-linked {{ box-shadow: 0 0 0 2px #6366f1, 0 2px 8px rgba(99,102,241,0.18); }}
        .eval-card-head {{ display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }}
        .eval-step-num {{ color: #718096; font-size: 0.78em; font-weight: 600; }}
        .eval-badge {{
            padding: 1px 7px; border-radius: 10px; font-size: 0.75em; font-weight: 600; color: #2d3748;
        }}
        .badge-thought, .badge-system {{ background: rgba(33,150,243,0.18); }}
        .eval-card-text {{ white-space: pre-wrap; word-break: break-word; line-height: 1.45; font-size: 0.92em; }}
        .eval-call-line {{ display: flex; align-items: baseline; gap: 6px; flex-wrap: wrap; }}
        .eval-tool-badge {{
            background: rgba(255,152,0,0.22); color: #b45309; padding: 1px 7px;
            border-radius: 4px; font-size: 0.78em; font-weight: 700;
            font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
        }}
        .eval-call-code {{
            font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
            font-size: 0.85em; word-break: break-word; color: #44403c;
        }}
        .eval-result {{ margin-top: 6px; display: flex; gap: 4px; align-items: flex-start; }}
        .eval-result-arrow {{ color: #16a34a; font-weight: 700; flex: 0 0 auto; }}
        .eval-result-pre {{
            margin: 0; white-space: pre-wrap; word-break: break-word;
            font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
            font-size: 0.82em; color: #57534e; background: rgba(0,0,0,0.03);
            padding: 4px 6px; border-radius: 4px; flex: 1 1 auto; min-width: 0;
        }}
        details.eval-result {{ display: block; }}
        details.eval-result summary {{ cursor: pointer; color: #16a34a; font-size: 0.82em; }}
        @media (max-width: 720px) {{
            .eval-trace-panes {{ flex-direction: column; }}
        }}
        @media (prefers-reduced-motion: reduce) {{
            .eval-card {{ transition: none; }}
        }}
        '''

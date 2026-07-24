"""
CoT Trace Display Type

Purpose-built rendering for a **long chain-of-thought (CoT) reasoning trace** as
a tall vertical column of numbered, type-badged step cards — the display half of
the process-reward (PRM) verification workflow.

It is tuned for the "very tall" shape of a segmented CoT:

- A **sticky header** with a live progress summary and a **"Jump to next
  unverified"** control.
- A **sticky step rail** of progress dots (one per step) that recolor as steps
  are marked correct / neutral / incorrect / AI-suggested; each dot scrolls its
  step into view.
- **Collapsible long steps** (clamp + "Show more") so one giant step can't blow
  out the layout, and the page never scrolls horizontally.
- ``data-turn-index`` on every step card so the ``process_reward`` schema's
  ``inline_with_trace`` mode injects its ✓/○/✗ control directly onto each step.

Data is normalized with the shared :func:`normalize_steps`, so a segmented CoT
(list of ``{index, text, type}`` from ``cot_segmentation``) and any other trace
format type their steps identically to ``agent_trace``/``eval_trace``.
"""

import html
from typing import Dict, Any, List

from .base import BaseDisplay
from ._trace_normalize import (
    DEFAULT_STEP_COLORS,
    normalize_steps,
    infer_type_from_text,
)


class CotTraceDisplay(BaseDisplay):
    """Vertical long-CoT display with a sticky step rail for PRM verification."""

    name = "cot_trace"
    required_fields = ["key"]
    optional_fields = {
        "show_step_numbers": True,
        "show_types": True,
        "show_rail": True,
        "collapse_long_steps": True,
        "clamp_lines": 12,
        "compact": False,
        "step_type_colors": DEFAULT_STEP_COLORS,
        "speaker_key": "speaker",
        "text_key": "text",
    }
    description = "Long chain-of-thought trace: vertical step cards with a sticky progress rail for process-reward verification"
    # Per-step cards don't follow the single .text-content wrapper contract.
    supports_span_target = False

    def render(self, field_config: Dict[str, Any], data: Any) -> str:
        if not data:
            return '<div class="cot-trace-placeholder">No reasoning provided</div>'

        options = self.get_display_options(field_config)
        show_step_numbers = options.get("show_step_numbers", True)
        show_types = options.get("show_types", True)
        show_rail = options.get("show_rail", True)
        collapse_long = options.get("collapse_long_steps", True)
        clamp_lines = int(options.get("clamp_lines", 12))
        compact = options.get("compact", False)
        colors = options.get("step_type_colors", DEFAULT_STEP_COLORS)
        speaker_key = options.get("speaker_key", "speaker")
        text_key = options.get("text_key", "text")

        field_key = html.escape(field_config.get("key", ""), quote=True)

        # Turn-level annotation schemes bound to this field (proxy widgets; real
        # state lives in the scheme's hidden anchor — see turn_annotations.py).
        turn_schemes = field_config.get("_turn_schemes") or []

        steps = self._to_steps(data, speaker_key, text_key)
        if not steps:
            return '<div class="cot-trace-placeholder">No reasoning steps found</div>'

        css = self._build_css(colors, compact)

        rail_html = self._build_rail(steps) if show_rail else ""

        card_html_list: List[str] = []
        for i, step in enumerate(steps):
            card_html_list.append(
                self._build_card(
                    i, step, field_key, turn_schemes,
                    show_step_numbers, show_types, collapse_long, clamp_lines,
                )
            )
        steps_html = "\n".join(card_html_list)

        header_html = self._build_header(len(steps))

        body_classes = ["cot-trace-body"]
        if show_rail:
            body_classes.append("has-rail")

        return f'''
        <style>{css}</style>
        <div class="cot-trace-display" data-field-key="{field_key}" data-step-count="{len(steps)}">
            {header_html}
            <div class="{' '.join(body_classes)}">
                {rail_html}
                <div class="cot-trace-steps">
                    {steps_html}
                </div>
            </div>
        </div>
        {self._build_js()}
        '''

    def _to_steps(self, data: Any, speaker_key: str, text_key: str) -> List[Dict[str, Any]]:
        """Normalize input to typed steps.

        Recognizes the ``cot_segmentation`` output shape (a list of dicts each
        carrying a ``text`` key, typically with ``type``/``index``) directly so
        segmented reasoning renders without depending on the speaker/step_type
        formats ``normalize_steps`` expects. Falls back to the shared
        :func:`normalize_steps` for other trace/dialogue formats.
        """
        if (
            isinstance(data, list)
            and data
            and all(isinstance(s, dict) and text_key in s for s in data)
            and any(("type" in s or "index" in s) and speaker_key not in s and "step_type" not in s for s in data)
        ):
            steps: List[Dict[str, Any]] = []
            for s in data:
                text = str(s.get(text_key, ""))
                step = {
                    "type": s.get("type") or infer_type_from_text(text),
                    "speaker": s.get("speaker", ""),
                    "text": text,
                }
                for k in ("run_id", "agent_id", "turn_id", "step_id"):
                    if s.get(k):
                        step[k] = s[k]
                steps.append(step)
            return steps
        return normalize_steps(data, speaker_key, text_key)

    def _build_header(self, n_steps: int) -> str:
        return f'''
        <div class="cot-trace-header">
            <div class="cot-trace-progress">
                <span class="cot-progress-label">Reasoning</span>
                <span class="cot-progress-counts" data-total="{n_steps}" role="status" aria-live="polite">{n_steps} steps</span>
            </div>
            <button type="button" class="cot-jump-next" title="Scroll to the next step that still needs review">
                Jump to next unverified ↓
            </button>
        </div>
        '''

    def _build_rail(self, steps: List[Dict[str, Any]]) -> str:
        dots = []
        for i, step in enumerate(steps):
            stype = html.escape(step.get("type", "observation"), quote=True)
            dots.append(
                f'<button type="button" class="cot-rail-dot" data-target-index="{i}" '
                f'data-step-type="{stype}" '
                f'title="Step {i + 1}" aria-label="Go to step {i + 1}">'
                f'<span class="cot-rail-num">{i + 1}</span></button>'
            )
        return (
            '<nav class="cot-trace-rail" aria-label="Reasoning step navigation">'
            '<div class="cot-rail-title">Steps</div>'
            f'<div class="cot-rail-dots">{"".join(dots)}</div>'
            '</nav>'
        )

    def _build_card(
        self,
        i: int,
        step: Dict[str, Any],
        field_key: str,
        turn_schemes: list,
        show_step_numbers: bool,
        show_types: bool,
        collapse_long: bool,
        clamp_lines: int,
    ) -> str:
        step_type = step.get("type", "observation")
        safe_type = html.escape(step_type, quote=True)
        speaker = step.get("speaker", "")
        text = str(step.get("text", ""))
        escaped_text = html.escape(text)

        # Clamp long steps so a single huge step doesn't dominate the column.
        line_count = text.count("\n") + 1
        long_step = collapse_long and (line_count > clamp_lines or len(text) > 900)
        text_classes = ["cot-step-text"]
        if long_step:
            text_classes.append("clamped")
        expand_html = (
            '<button type="button" class="cot-step-expand" aria-expanded="false">Show more ▾</button>'
            if long_step else ""
        )

        num_html = ""
        if show_step_numbers:
            num_html = f'<span class="cot-step-num">Step {i + 1}</span>'

        badge_html = ""
        if show_types:
            badge_label = html.escape(str(speaker)) if speaker else safe_type.capitalize()
            badge_html = f'<span class="cot-step-badge badge-{safe_type}">{badge_label}</span>'

        # Turn-level annotation slot (proxy widgets), if any schemes bind here.
        slot_html = ""
        if turn_schemes:
            from ..turn_annotations import render_turn_slot
            slot_html = render_turn_slot(turn_schemes, step, i, field_key)

        run_id_attr = ""
        if step.get("run_id"):
            run_id_attr = f' data-run-id="{html.escape(str(step["run_id"]), quote=True)}"'

        # data-turn-index is the canonical index the process_reward inline mode
        # binds to; it MUST equal the step index so saved rewards line up.
        return f'''
        <div class="cot-step step-type-{safe_type}" data-turn-index="{i}" data-step-index="{i}" data-step-type="{safe_type}"{run_id_attr} style="--cot-clamp:{clamp_lines};">
            <div class="cot-step-header">
                {num_html}
                {badge_html}
            </div>
            <div class="cot-step-body">
                <div class="{' '.join(text_classes)}" style="--cot-clamp:{clamp_lines};">{escaped_text}</div>
                {expand_html}
                {slot_html}
            </div>
        </div>
        '''

    def _build_css(self, colors: Dict[str, str], compact: bool) -> str:
        thought = colors.get("thought", DEFAULT_STEP_COLORS["thought"])
        action = colors.get("action", DEFAULT_STEP_COLORS["action"])
        obs = colors.get("observation", DEFAULT_STEP_COLORS["observation"])
        system = colors.get("system", DEFAULT_STEP_COLORS["system"])
        error = colors.get("error", DEFAULT_STEP_COLORS["error"])
        pad = "8px 12px" if compact else "12px 16px"
        gap = "6px" if compact else "10px"
        return f'''
        .cot-trace-display {{ font-family: inherit; max-width: 100%; }}
        .cot-trace-placeholder {{ padding: 12px; color: var(--muted-foreground,#71717a); font-style: italic; }}

        /* Sticky header (sticks to page scroll over the tall step column). */
        .cot-trace-header {{
            position: sticky; top: 0; z-index: 5;
            display: flex; align-items: center; gap: 12px;
            padding: 8px 12px; margin-bottom: 8px;
            background: var(--card,#fff); border: 1px solid var(--border,#e4e4e7);
            border-radius: var(--radius,0.5rem);
        }}
        .cot-progress-label {{ font-weight: 600; }}
        .cot-progress-counts {{ font-size: 0.85em; color: var(--muted-foreground,#71717a); margin-left: 6px; }}
        .cot-progress-counts .cot-c-correct {{ color:#2e7d32; font-weight:500; }}
        .cot-progress-counts .cot-c-incorrect {{ color:#c62828; font-weight:500; }}
        .cot-progress-counts .cot-c-neutral {{ color:#b26a00; font-weight:500; }}
        .cot-progress-counts .cot-c-pending {{ color:#6a5acd; font-weight:500; }}
        .cot-jump-next {{
            margin-left: auto; padding: 5px 12px; font-size: 0.85em;
            border: 1px solid var(--border,#e4e4e7); border-radius: var(--radius,0.5rem);
            background: var(--card,#fff); cursor: pointer; white-space: nowrap;
        }}
        .cot-jump-next:hover {{ background: var(--secondary,#f4f4f5); }}
        .cot-jump-next:focus-visible {{ outline: 2px solid var(--ring,#6e56cf); outline-offset: 2px; }}
        .cot-jump-next[disabled] {{ opacity: 0.5; cursor: default; }}

        .cot-trace-body {{ display: block; }}
        .cot-trace-body.has-rail {{ display: flex; gap: 12px; align-items: flex-start; }}
        .cot-trace-steps {{ flex: 1; min-width: 0; display: flex; flex-direction: column; gap: {gap}; }}

        /* Sticky rail: stays visible while the long step column scrolls. */
        .cot-trace-rail {{
            flex: 0 0 auto; position: sticky; top: 56px; align-self: flex-start;
            max-height: 78vh; overflow-y: auto;
            border: 1px solid var(--border,#e4e4e7); border-radius: var(--radius,0.5rem);
            padding: 8px; background: var(--card,#fff);
        }}
        .cot-rail-title {{ font-size: 0.72em; font-weight: 600; text-transform: uppercase;
            color: var(--muted-foreground,#71717a); margin-bottom: 6px; text-align: center; }}
        .cot-rail-dots {{ display: flex; flex-direction: column; gap: 4px; }}
        .cot-rail-dot {{
            width: 30px; height: 24px; border-radius: 6px; cursor: pointer;
            border: 1px solid var(--border,#e4e4e7); background: var(--secondary,#f4f4f5);
            color: var(--muted-foreground,#71717a); font-size: 0.72em; font-weight: 600;
            display: flex; align-items: center; justify-content: center; padding: 0;
        }}
        .cot-rail-dot:hover {{ border-color:#999; }}
        .cot-rail-dot:focus-visible {{ outline: 2px solid var(--ring,#6e56cf); outline-offset: 1px; }}
        .cot-rail-dot.cot-active {{ box-shadow: 0 0 0 2px var(--ring,#6e56cf); }}
        .cot-rail-dot.cot-dot-correct {{ background:#4caf50; color:#fff; border-color:#4caf50; }}
        .cot-rail-dot.cot-dot-incorrect {{ background:#f44336; color:#fff; border-color:#f44336; }}
        .cot-rail-dot.cot-dot-neutral {{ background:#ffb300; color:#fff; border-color:#ffb300; }}
        .cot-rail-dot.cot-dot-pending {{ background:#ede9fe; color:#5b21b6; border-color:#a78bfa; border-style: dashed; }}

        .cot-step {{
            padding: {pad}; border-radius: var(--radius,0.5rem);
            border: 1px solid var(--border,#e4e4e7); border-left: 4px solid #ccc;
            background: var(--card,#fff); scroll-margin-top: 64px;
        }}
        .step-type-thought {{ border-left-color: #2196F3; background: {thought}; }}
        .step-type-action {{ border-left-color: #FF9800; background: {action}; }}
        .step-type-observation {{ border-left-color: #4CAF50; background: {obs}; }}
        .step-type-system {{ border-left-color: #9C27B0; background: {system}; }}
        .step-type-error {{ border-left-color: #f44336; background: {error}; }}
        .cot-step-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }}
        .cot-step-num {{ font-size: 0.8em; font-weight: 600; color: var(--muted-foreground,#71717a); }}
        .cot-step-badge {{ padding: 2px 8px; border-radius: 4px; font-size: 0.78em; font-weight: 600; color:#333; }}
        .badge-thought {{ background: rgba(33,150,243,0.2); }}
        .badge-action {{ background: rgba(255,152,0,0.2); }}
        .badge-observation {{ background: rgba(76,175,80,0.2); }}
        .badge-system {{ background: rgba(156,39,176,0.2); }}
        .badge-error {{ background: rgba(244,67,54,0.2); }}
        .cot-step-text {{ white-space: pre-wrap; word-break: break-word; overflow-wrap: anywhere; line-height: 1.55; font-size: 0.92em; }}
        /* Clamp long steps to ~clamp_lines lines with a fade. */
        .cot-step-text.clamped {{
            display: -webkit-box; -webkit-line-clamp: var(--cot-clamp, 12);
            -webkit-box-orient: vertical; overflow: hidden;
        }}
        .cot-step-expand {{
            margin-top: 4px; padding: 2px 8px; font-size: 0.8em; cursor: pointer;
            border: 1px solid var(--border,#e4e4e7); border-radius: 6px;
            background: var(--secondary,#f4f4f5); color: var(--foreground,#18181b);
        }}
        .cot-step-expand:hover {{ background: var(--muted,#e4e4e7); }}

        /* Verification tints (set by the process_reward inline controls). */
        .cot-step.prm-turn-correct {{ box-shadow: inset 3px 0 0 #4caf50; }}
        .cot-step.prm-turn-incorrect {{ box-shadow: inset 3px 0 0 #f44336; }}
        .cot-step.prm-turn-neutral {{ box-shadow: inset 3px 0 0 #ffb300; }}
        .cot-step.prm-ai-pending {{ outline: 2px dashed #a78bfa; outline-offset: -2px; }}

        @media (max-width: 640px) {{
            .cot-trace-body.has-rail {{ display: block; }}
            .cot-trace-rail {{ position: static; max-height: none; margin-bottom: 8px; }}
            .cot-rail-dots {{ flex-direction: row; flex-wrap: wrap; }}
        }}
        @media (prefers-reduced-motion: reduce) {{
            .cot-rail-dot, .cot-jump-next, .cot-step-expand {{ transition: none; }}
        }}
        '''

    def _build_js(self) -> str:
        # Rail sync + jump-to-next-unverified + expand toggles. Reads the
        # verification classes the process_reward inline mode sets on each
        # [data-turn-index] step host, so the rail stays in lockstep with the
        # PRM widget without any coupling between the two scripts.
        return '''
        <script>
        (function() {
          function initCotTrace(root) {
            if (!root || root._cotInit) return;
            root._cotInit = true;
            var steps = Array.prototype.slice.call(root.querySelectorAll('.cot-step'));
            var dots = Array.prototype.slice.call(root.querySelectorAll('.cot-rail-dot'));
            var counts = root.querySelector('.cot-progress-counts');
            var jumpBtn = root.querySelector('.cot-jump-next');

            function stateOf(step) {
              if (step.classList.contains('prm-ai-pending')) return 'pending';
              if (step.classList.contains('prm-turn-correct')) return 'correct';
              if (step.classList.contains('prm-turn-incorrect')) return 'incorrect';
              if (step.classList.contains('prm-turn-neutral')) return 'neutral';
              return '';
            }
            function isDone(step) {
              var s = stateOf(step);
              return s === 'correct' || s === 'incorrect' || s === 'neutral';
            }

            function refresh() {
              var c = {correct:0, incorrect:0, neutral:0, pending:0};
              steps.forEach(function(step, i) {
                var s = stateOf(step);
                var dot = dots[i];
                if (dot) {
                  dot.classList.remove('cot-dot-correct','cot-dot-incorrect','cot-dot-neutral','cot-dot-pending');
                  if (s) dot.classList.add('cot-dot-' + s);
                }
                if (s && c[s] !== undefined) c[s]++;
              });
              if (counts) {
                var total = parseInt(counts.getAttribute('data-total'), 10) || steps.length;
                var reviewed = c.correct + c.incorrect + c.neutral;
                var parts = ['<strong>' + reviewed + '/' + total + '</strong> reviewed'];
                if (c.correct) parts.push('<span class="cot-c-correct">' + c.correct + ' ✓</span>');
                if (c.neutral) parts.push('<span class="cot-c-neutral">' + c.neutral + ' ○</span>');
                if (c.incorrect) parts.push('<span class="cot-c-incorrect">' + c.incorrect + ' ✗</span>');
                if (c.pending) parts.push('<span class="cot-c-pending">' + c.pending + ' ✨ to verify</span>');
                counts.innerHTML = parts.join(' · ');
              }
              if (jumpBtn) {
                var anyLeft = steps.some(function(s) { return !isDone(s); });
                jumpBtn.disabled = !anyLeft;
              }
            }

            var reduceMotion = window.matchMedia
              && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
            function scrollToStep(i) {
              if (steps[i]) {
                steps[i].scrollIntoView(
                  {block: 'nearest', behavior: reduceMotion ? 'auto' : 'smooth'});
                dots.forEach(function(d) { d.classList.remove('cot-active'); });
                if (dots[i]) dots[i].classList.add('cot-active');
              }
            }

            dots.forEach(function(dot) {
              dot.addEventListener('click', function() {
                scrollToStep(parseInt(dot.getAttribute('data-target-index'), 10));
              });
            });

            if (jumpBtn) {
              jumpBtn.addEventListener('click', function() {
                for (var i = 0; i < steps.length; i++) {
                  if (!isDone(steps[i])) { scrollToStep(i); return; }
                }
              });
            }

            // Expand/collapse long steps.
            root.querySelectorAll('.cot-step-expand').forEach(function(btn) {
              btn.addEventListener('click', function() {
                var body = btn.parentElement.querySelector('.cot-step-text');
                if (!body) return;
                var clamped = body.classList.toggle('clamped');
                btn.setAttribute('aria-expanded', String(!clamped));
                btn.textContent = clamped ? 'Show more ▾' : 'Show less ▴';
              });
            });

            // Keep the rail in sync as PRM marks steps (class changes on hosts).
            var obs = new MutationObserver(refresh);
            steps.forEach(function(step) {
              obs.observe(step, {attributes: true, attributeFilter: ['class']});
            });
            refresh();
          }

          function initAll() {
            document.querySelectorAll('.cot-trace-display').forEach(initCotTrace);
          }
          if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', initAll);
          } else {
            initAll();
          }
          // Re-init after instance navigation (annotation.js fires this).
          document.addEventListener('instanceChanged', function() {
            document.querySelectorAll('.cot-trace-display').forEach(function(r) {
              r._cotInit = false; initCotTrace(r);
            });
          });
        })();
        </script>
        '''

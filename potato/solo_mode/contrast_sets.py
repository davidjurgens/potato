"""
Contrast Set Generator for Solo Mode

A "contrast set" (Gardner et al. 2020) is a minimally-edited variant of an
existing example that flips its label. This module takes the synthetic
edge cases a human has already labeled (see ``edge_case_synthesizer.py``)
and, for each one with a genuine second boundary label to aim for, asks
the *human* to make the smallest edit they can think of — a word or short
phrase — that would flip it from their label to that other one.

Deliberately human-authored, not LLM-generated: the whole point is
capturing where the human themselves believes the real boundary lies, and
a human who understands the task can usually produce a much sharper
minimal edit than an LLM guessing at one from the outside (Ollama models
in particular were prone to naive word-splicing that read as
grammatically incoherent, or echoing the text back unchanged).

Once a batch of pairs for a given label pair has been written,
``propose_rules_from_contrast_pairs`` asks the LLM to state, in the
codebook's own vocabulary (``negative_clarification``), exactly what
distinguishes the two labels — grounded in the human's own edits, but
written as a general, paraphrased rule rather than a quote of any one
excerpt. The result is staged via the existing LLM-propose/human-confirm
pipeline (``potato.codebook.changelog.propose_change``), the same one
``notes_feedback.py`` uses: nothing is written to the codebook until a
human confirms it in the Codebook tray.
"""

import inspect
import json
import logging
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ContrastRuleResponse(BaseModel):
    should_propose: bool = False
    rationale: str = ""
    label_a_negative_clarification: Optional[str] = None
    label_b_negative_clarification: Optional[str] = None


def _query_endpoint(endpoint: Any, prompt: str, response_model: Any) -> Any:
    """Call ``endpoint.query()`` in a way that works across AI backends.

    Most backends (Ollama, OpenAI, HuggingFace, ...) require a pydantic
    ``output_format`` as a second positional argument; Anthropic's takes
    only ``prompt``. Rather than hardcode per-backend branches, inspect
    the bound method's own parameter count and call it accordingly.
    """
    try:
        param_count = len(inspect.signature(endpoint.query).parameters)
    except (TypeError, ValueError):
        param_count = 1
    if param_count >= 2:
        return endpoint.query(prompt, response_model)
    return endpoint.query(prompt)


def _parse_json_response(response: Any) -> Dict[str, Any]:
    """Parse a JSON object out of an LLM response, whether it's already a
    dict, a pydantic model, or a string (optionally fenced in ```json)."""
    if isinstance(response, dict):
        return response
    if hasattr(response, 'model_dump'):
        return response.model_dump()

    content = str(response).strip()
    match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
    if match:
        content = match.group(1).strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {}


def _describe_edit(original_text: str, edited_text: str) -> str:
    """A compact "old -> new" summary of just the changed spans, computed
    deterministically via diff rather than self-reported (previously the
    LLM described its own edit; a human's edit is described the same way
    the review UI's diff highlight already computes it, for consistency)."""
    orig_tokens = re.findall(r'\S+|\s+', original_text)
    edit_tokens = re.findall(r'\S+|\s+', edited_text)
    matcher = SequenceMatcher(a=orig_tokens, b=edit_tokens, autojunk=False)

    removed, added = [], []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == 'equal':
            continue
        old_span = ''.join(orig_tokens[i1:i2]).strip()
        new_span = ''.join(edit_tokens[j1:j2]).strip()
        if old_span:
            removed.append(old_span)
        if new_span:
            added.append(new_span)

    old_desc = ' / '.join(removed) if removed else '(nothing removed)'
    new_desc = ' / '.join(added) if added else '(nothing added)'
    return f'"{old_desc}" -> "{new_desc}"'


CONTRAST_RULE_TEMPLATE = """You are refining an annotation codebook by \
proposing a rule that distinguishes two adjacent labels, grounded in \
minimal edits a human annotator wrote themselves.

## Label A
{label_a}

## Label B
{label_b}

## Human-authored contrast pairs
For each pair, the human took an excerpt they had labeled Label A and \
made the smallest edit they could think of to turn it into an excerpt \
that should be labeled Label B instead.
{pairs_text}

## Task
Based on exactly what the human changed (and their own explanation, when \
given), write ONE crisp, general clarification sentence per label stating \
concretely why it applies instead of the other. Generalize the pattern — \
do not quote or closely paraphrase any specific excerpt from the pairs \
above; state the underlying distinction so it reads as a standalone rule, \
not a description of one example. If the pairs don't reveal a clear, \
specific pattern, say so and propose nothing.

Respond with JSON:
{{
    "should_propose": <true|false>,
    "rationale": "<one sentence citing which pair(s) motivated this>",
    "label_a_negative_clarification": "<general rule: why NOT to use label A when label B applies, or omit/null>",
    "label_b_negative_clarification": "<general rule: why NOT to use label B when label A applies, or omit/null>"
}}
"""


@dataclass
class ContrastPair:
    """A minimally-edited, label-flipping variant of a labeled edge case.

    ``edited_text`` starts empty — the human hasn't written their edit
    yet — and the pair isn't complete until record_human_edit() fills it
    in (see get_unreviewed_pairs()/get_reviewed_pairs())."""
    id: str
    source_case_id: str
    label_a: str  # the edge case's human label
    label_b: str  # the other boundary label the edit should reach
    original_text: str
    edited_text: str
    changed_span: str
    proposed_label: str
    created_at: datetime = field(default_factory=datetime.now)

    # Filled in by record_human_edit() once the human writes their edit
    human_verdict: Optional[str] = None  # "authored" once written
    human_label: Optional[str] = None
    notes: Optional[str] = None
    reviewed_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'source_case_id': self.source_case_id,
            'label_a': self.label_a,
            'label_b': self.label_b,
            'original_text': self.original_text,
            'edited_text': self.edited_text,
            'changed_span': self.changed_span,
            'proposed_label': self.proposed_label,
            'created_at': self.created_at.isoformat(),
            'human_verdict': self.human_verdict,
            'human_label': self.human_label,
            'notes': self.notes,
            'reviewed_at': (
                self.reviewed_at.isoformat() if self.reviewed_at else None),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ContrastPair':
        return cls(
            id=data['id'],
            source_case_id=data['source_case_id'],
            label_a=data['label_a'],
            label_b=data['label_b'],
            original_text=data['original_text'],
            edited_text=data['edited_text'],
            changed_span=data.get('changed_span', ''),
            proposed_label=data['proposed_label'],
            created_at=datetime.fromisoformat(data['created_at']),
            human_verdict=data.get('human_verdict'),
            human_label=data.get('human_label'),
            notes=data.get('notes'),
            reviewed_at=(
                datetime.fromisoformat(data['reviewed_at'])
                if data.get('reviewed_at') else None
            ),
        )


class ContrastSetGenerator:
    """Tracks contrast pairs the human writes from their labeled edge
    cases, and drives the LLM rule-proposal step once they're written."""

    def __init__(self, config: Dict[str, Any], solo_config: Any):
        self.config = config
        self.solo_config = solo_config
        self._lock = threading.RLock()

        self.pairs: Dict[str, ContrastPair] = {}
        self._id_counter = 0
        # Guards against duplicate rule proposals when a double-click or
        # resubmitted form POSTs an edit for a pair that was already the
        # last unwritten one — see record_human_edit()/manager.propose_
        # rules_from_contrast_pairs().
        self.rules_proposed = False
        self._endpoint = None

    def _get_endpoint(self) -> Optional[Any]:
        if self._endpoint is not None:
            return self._endpoint

        if not self.solo_config.revision_models:
            logger.warning("No models configured for contrast set generation")
            return None

        try:
            from potato.ai.ai_endpoint import AIEndpointFactory

            for model_config in self.solo_config.revision_models:
                try:
                    endpoint_config = model_config.to_endpoint_config(
                        temperature_override=0.3)
                    endpoint = AIEndpointFactory.create_endpoint(endpoint_config)
                    if endpoint:
                        self._endpoint = endpoint
                        return endpoint
                except Exception as e:
                    logger.debug(f"Failed to create contrast-set endpoint: {e}")
                    continue
        except Exception as e:
            logger.error(f"Error creating contrast-set endpoint: {e}")

        return None

    def _generate_id(self) -> str:
        self._id_counter += 1
        return f"contrast_{self._id_counter:04d}"

    def prepare_pairs_for_writing(
        self, labeled_cases: List[Any]
    ) -> List[ContrastPair]:
        """Create one empty (unwritten) contrast pair per eligible labeled
        edge case, ready for the human to fill in via record_human_edit().

        A case is eligible when it has at least two distinct
        ``boundary_labels`` — without a second label there's no target to
        aim the edit at. ``label_a`` is the case's human label; ``label_b``
        is the other boundary label (or the first boundary label that
        isn't the human label, if the human picked a third option)."""
        prepared: List[ContrastPair] = []
        with self._lock:
            for case in labeled_cases:
                boundary = list(dict.fromkeys(case.boundary_labels or []))
                label_a = case.human_label
                others = [l for l in boundary if l != label_a]
                if not label_a or not others:
                    logger.debug(
                        f"Skipping edge case {case.id}: fewer than 2 "
                        f"distinct boundary labels to contrast against"
                    )
                    continue
                label_b = others[0]

                pair = ContrastPair(
                    id=self._generate_id(),
                    source_case_id=case.id,
                    label_a=label_a,
                    label_b=label_b,
                    original_text=case.text,
                    edited_text='',
                    changed_span='',
                    proposed_label=label_b,
                )
                self.pairs[pair.id] = pair
                prepared.append(pair)

        logger.info(f"Prepared {len(prepared)} contrast pairs for writing")
        return prepared

    def record_human_edit(
        self,
        pair_id: str,
        edited_text: str,
        notes: Optional[str] = None,
    ) -> bool:
        """Record the human's own minimal edit for a pair. Rejects an
        empty edit or one identical to the original — there's nothing to
        learn from a pair with no actual change."""
        with self._lock:
            pair = self.pairs.get(pair_id)
            if pair is None:
                logger.warning(f"Unknown contrast pair: {pair_id}")
                return False

            edited_text = (edited_text or '').strip()
            if not edited_text or edited_text == pair.original_text.strip():
                logger.debug(
                    f"Rejecting edit for {pair_id}: empty or unchanged")
                return False

            pair.edited_text = edited_text
            pair.changed_span = _describe_edit(pair.original_text, edited_text)
            pair.notes = notes
            pair.human_verdict = 'authored'
            pair.human_label = pair.proposed_label
            pair.reviewed_at = datetime.now()
            return True

    def get_unreviewed_pairs(self) -> List[ContrastPair]:
        with self._lock:
            return [p for p in self.pairs.values() if p.human_verdict is None]

    def get_reviewed_pairs(self) -> List[ContrastPair]:
        with self._lock:
            return [
                p for p in self.pairs.values() if p.human_verdict is not None
            ]

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            total = len(self.pairs)
            reviewed = len(self.get_reviewed_pairs())
            return {
                'total_pairs': total,
                'reviewed': reviewed,
                'unreviewed': total - reviewed,
            }

    def try_claim_rule_proposal(self) -> bool:
        """Atomically claim the right to run rule proposal for this
        review round. Returns True the first time it's called (caller
        should proceed), False on every call after (caller should no-op)
        — prevents a double-click or resubmitted edit POST from staging
        the same proposals twice."""
        with self._lock:
            if self.rules_proposed:
                return False
            self.rules_proposed = True
            return True

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                'pairs': {pid: p.to_dict() for pid, p in self.pairs.items()},
                'id_counter': self._id_counter,
                'rules_proposed': self.rules_proposed,
            }

    def from_dict(self, data: Dict[str, Any]) -> None:
        with self._lock:
            self.pairs = {
                pid: ContrastPair.from_dict(pdata)
                for pid, pdata in data.get('pairs', {}).items()
            }
            self._id_counter = data.get('id_counter', len(self.pairs))
            self.rules_proposed = data.get('rules_proposed', False)


def _format_pairs_for_prompt(pairs: List[ContrastPair]) -> str:
    lines = []
    for i, pair in enumerate(pairs, 1):
        note = f' Human\'s note: {pair.notes}' if pair.notes else ''
        lines.append(
            f"{i}. Original ({pair.label_a}): \"{pair.original_text}\"\n"
            f"   Human's edit (now {pair.label_b}): \"{pair.edited_text}\"\n"
            f"   What changed: {pair.changed_span}.{note}"
        )
    return '\n'.join(lines)


def propose_rules_from_contrast_pairs(
    task_dir: str, project: str, pairs: List[ContrastPair], *, endpoint: Any,
    actor: str = "contrast_set_llm",
) -> List[Dict[str, Any]]:
    """Group written contrast pairs by label pair, ask the LLM to propose a
    distinguishing rule for each, and stage the result via the existing
    LLM-propose/human-confirm pipeline. Returns the created proposal
    records. Best-effort per group: one group's failure doesn't stop the
    others.
    """
    from potato.codebook import changelog
    from potato.codebook.codebook import Codebook

    written = [p for p in pairs if p.human_verdict is not None]
    if not written:
        return []

    groups: Dict[frozenset, List[ContrastPair]] = {}
    for pair in written:
        key = frozenset({pair.label_a, pair.label_b})
        groups.setdefault(key, []).append(pair)

    cb = Codebook.load(task_dir, project)
    by_name = {d.get("name"): d for d in cb.details_in_order()}

    created: List[Dict[str, Any]] = []
    for key, group_pairs in groups.items():
        if len(key) != 2:
            continue
        label_a, label_b = sorted(key)
        try:
            prompt = CONTRAST_RULE_TEMPLATE.format(
                label_a=label_a,
                label_b=label_b,
                pairs_text=_format_pairs_for_prompt(group_pairs),
            )
            response = _query_endpoint(endpoint, prompt, ContrastRuleResponse)
            parsed = _parse_json_response(response)
            if not parsed.get('should_propose'):
                continue

            rationale = parsed.get('rationale', '')
            for label, prefix in ((label_a, 'label_a'), (label_b, 'label_b')):
                code = by_name.get(label)
                if not code:
                    continue

                neg_clarification = parsed.get(f'{prefix}_negative_clarification')
                if not neg_clarification:
                    continue  # nothing to change for this code

                payload: Dict[str, Any] = {
                    'code_id': code['id'],
                    'negative_clarification': neg_clarification,
                }

                payload['rationale'] = rationale
                prop = changelog.propose_change(
                    task_dir, project=project, op='update_fields',
                    payload=payload, actor=actor, actor_kind='model')
                created.append(prop)
        except Exception:
            logger.warning(
                "contrast-set rule proposal failed for label pair %r",
                key, exc_info=True)
            continue

    return created

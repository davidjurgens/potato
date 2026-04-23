"""
Built-in refinement strategies.

Each strategy inherits from RefinementStrategy and is registered via
@register_strategy so the manager can look it up by name.

The framework (manager.trigger_refinement_cycle) handles:
  - validation split
  - candidate evaluation via CandidateEvaluator
  - validation gating (reject candidates below baseline)
  - failure counter and resume-on-new-disagreements

Strategies only need to implement propose_candidates().
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .base import (
    RefinementStrategy,
    RefinementCandidate,
    CandidateKind,
)
from .registry import register_strategy

logger = logging.getLogger(__name__)


def _build_guidelines_section(rules: List[str]) -> str:
    """Build the `## Annotation Guidelines` section from a list of rules."""
    rules_text = "\n".join(f"- {r.strip()}" for r in rules if r.strip())
    return (
        "## Annotation Guidelines\n\n"
        "When distinguishing between similar labels, follow these rules:\n"
        f"{rules_text}\n"
    )


def _replace_guidelines_section(current_prompt: str, new_rules: List[str]) -> str:
    """Replace the existing `## Annotation Guidelines` / `## Refinement Guidelines`
    section with a new one built from rules. Append if no section exists.
    """
    import re
    new_section = _build_guidelines_section(new_rules)
    pattern = r'## (?:Refinement |Annotation )?Guidelines[\s\S]*?(?=\n## |\Z)'
    if re.search(pattern, current_prompt):
        return re.sub(pattern, new_section, current_prompt).rstrip() + "\n"
    else:
        return current_prompt.rstrip() + "\n\n" + new_section


def _extract_existing_rules(current_prompt: str) -> List[str]:
    """Extract rules from the existing guidelines section, if any."""
    import re
    match = re.search(
        r'## (?:Refinement |Annotation )?Guidelines[\s\S]*?\n([\s\S]*?)(?=\n## |\Z)',
        current_prompt,
    )
    if not match:
        return []
    rules = []
    for line in match.group(1).split('\n'):
        stripped = line.strip()
        if stripped.startswith('- ') and len(stripped) > 3:
            rules.append(stripped[2:].strip())
    return rules


@register_strategy
class ValidatedFocusedEditStrategy(RefinementStrategy):
    """Produces prompt-rule candidates via the LLM; validation gate filters
    those that don't improve over the baseline.

    This is the safe default for small optimizer models (4B–7B). It generates
    a small number of candidate rule sets and lets the framework pick the
    winner on the val set.
    """

    NAME = "validated_focused_edit"
    RECOMMENDED_OPTIMIZER_TIER = "small"
    BEST_FOR = ["binary", "few_labels", "objective"]
    DESCRIPTION = (
        "Generate prompt-rule candidates and keep only those that improve "
        "validation accuracy. Good default for small optimizer models."
    )

    def __init__(self, manager: Any, solo_config: Any):
        super().__init__(manager, solo_config)
        # Multiple candidate sets to give the framework choices
        self.num_candidates = getattr(
            solo_config.refinement_loop, "num_candidates", 3
        )

    def propose_candidates(
        self,
        patterns: List[Any],
        current_prompt: str,
        train_comparisons: List[Dict[str, Any]],
    ) -> List[RefinementCandidate]:
        """Generate N candidate rule sets via the existing confusion analyzer."""
        if not patterns:
            return []

        analyzer = self.manager.confusion_analyzer
        candidates: List[RefinementCandidate] = []

        # Generate several independent candidate rule sets
        for i in range(self.num_candidates):
            try:
                rules = analyzer.generate_guidelines_rewrite(patterns, current_prompt)
            except Exception as e:
                logger.warning(f"[ValidatedFocusedEdit] generation #{i} failed: {e}")
                continue
            if not rules:
                continue

            # Build the candidate prompt text by replacing the guidelines section
            candidate_prompt = _replace_guidelines_section(current_prompt, rules)

            candidates.append(RefinementCandidate(
                kind=CandidateKind.PROMPT_EDIT,
                payload={
                    "new_prompt_text": candidate_prompt,
                    "rules": rules,
                },
                target_pattern=f"top-{len(patterns)} confusion patterns",
                proposed_by=self.NAME,
                rationale=(
                    f"Candidate #{i+1}: {len(rules)} rules addressing "
                    f"{len(patterns)} confusion patterns"
                ),
            ))

        logger.info(
            f"[ValidatedFocusedEdit] Proposed {len(candidates)} candidate(s)"
        )
        return candidates


@register_strategy
class PrincipleICLStrategy(RefinementStrategy):
    """Instead of editing the prompt, add validated instances as ICL examples.

    For each disagreement, optionally extract a one-sentence principle (via LLM),
    then validate by checking if adding this instance as an ICL example improves
    accuracy on val. Accepted entries go to the ICL library.

    Each candidate is an individual ICL_EXAMPLE — the framework evaluates them
    one at a time. Good for subjective tasks and small models where writing
    rules fails.
    """

    NAME = "principle_icl"
    RECOMMENDED_OPTIMIZER_TIER = "small"
    BEST_FOR = ["subjective", "many_labels", "small_model"]
    DESCRIPTION = (
        "Add validated instances as in-context examples instead of editing "
        "the prompt. Robust against narrow-rule overfitting."
    )

    def __init__(self, manager: Any, solo_config: Any):
        super().__init__(manager, solo_config)
        self.max_candidates = getattr(
            solo_config.refinement_loop, "num_candidates", 5
        )
        self.extract_principle = True  # ask LLM for a short rationale

    def propose_candidates(
        self,
        patterns: List[Any],
        current_prompt: str,
        train_comparisons: List[Dict[str, Any]],
    ) -> List[RefinementCandidate]:
        """Propose each distinct disagreement as an ICL candidate.

        Chooses one instance per confusion pattern so examples are diverse
        (don't all come from the same predicted→actual confusion).
        """
        candidates: List[RefinementCandidate] = []

        # Use confusion patterns to sample diverse disagreements
        # (one per pattern, up to max_candidates)
        seen_pairs = set()
        analyzer = self.manager.confusion_analyzer

        for pattern in patterns:
            if len(candidates) >= self.max_candidates:
                break
            pair = (pattern.predicted_label, pattern.actual_label)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)

            # Take the first example in this pattern
            if not pattern.examples:
                continue
            ex = pattern.examples[0]

            # Optionally extract a principle via LLM
            principle = ""
            if self.extract_principle:
                try:
                    principle = self._extract_principle(pattern, ex, current_prompt)
                except Exception as e:
                    logger.debug(f"[PrincipleICL] principle extraction failed: {e}")

            candidates.append(RefinementCandidate(
                kind=CandidateKind.ICL_EXAMPLE,
                payload={
                    "instance_id": ex.instance_id,
                    "text": ex.text,
                    "label": pattern.actual_label,
                    "principle": principle,
                },
                target_pattern=f"{pattern.predicted_label}->{pattern.actual_label}",
                proposed_by=self.NAME,
                rationale=principle or "Disagreement example",
            ))

        logger.info(
            f"[PrincipleICL] Proposed {len(candidates)} ICL candidate(s) "
            f"from {len(patterns)} patterns"
        )
        return candidates

    def _extract_principle(self, pattern, example, current_prompt: str) -> str:
        """Ask the revision LLM for a one-sentence principle explaining the fix."""
        analyzer = self.manager.confusion_analyzer
        endpoint = analyzer._get_revision_endpoint()
        if endpoint is None:
            return ""

        prompt = (
            f"The following text was misclassified.\n\n"
            f"Text: \"{example.text[:500]}\"\n"
            f"Model's wrong label: {pattern.predicted_label}\n"
            f"Correct label: {pattern.actual_label}\n\n"
            f"In ONE short sentence (max 25 words), describe the general "
            f"linguistic signal that makes this text a '{pattern.actual_label}' "
            f"rather than '{pattern.predicted_label}'.\n"
            f"Focus on general features, not specific phrases.\n\n"
            f"Respond with JSON: {{\"principle\": \"<one sentence>\"}}"
        )

        try:
            from pydantic import BaseModel

            class PrincipleResponse(BaseModel):
                principle: str = ""

            try:
                response = endpoint.query(prompt, PrincipleResponse)
            except TypeError:
                response = endpoint.query(prompt)

            data = analyzer._parse_json(response)
            return data.get("principle", "").strip()
        except Exception as e:
            logger.debug(f"[PrincipleICL] principle LLM call failed: {e}")
            return ""


@register_strategy
class HybridDualTrackStrategy(RefinementStrategy):
    """Try prompt edits first; fall back to ICL examples if edits fail.

    This is the recommended default: combines ValidatedFocusedEdit and
    PrincipleICL. On the first cycle, proposes both kinds; the framework's
    validation gate picks whichever kind has the best candidate.

    After 2 consecutive prompt-edit failures (tracked by failure counter),
    future cycles propose ICL candidates only. This avoids wasted LLM cost
    on a model that can't write good rules.
    """

    NAME = "hybrid_dual_track"
    RECOMMENDED_OPTIMIZER_TIER = "small"
    BEST_FOR = ["general_default", "unknown_data_properties"]
    DESCRIPTION = (
        "Try prompt edits; fall back to ICL examples on failure. "
        "Recommended default for practitioners unsure of their data profile."
    )

    def __init__(self, manager: Any, solo_config: Any):
        super().__init__(manager, solo_config)
        self._focused_edit = ValidatedFocusedEditStrategy(manager, solo_config)
        self._icl = PrincipleICLStrategy(manager, solo_config)

    def propose_candidates(
        self,
        patterns: List[Any],
        current_prompt: str,
        train_comparisons: List[Dict[str, Any]],
    ) -> List[RefinementCandidate]:
        # Check consecutive failure count
        consecutive_failures = getattr(
            self.manager, "_refinement_consecutive_failures", 0
        )

        candidates: List[RefinementCandidate] = []

        if consecutive_failures < 2:
            # Try prompt edits
            candidates.extend(self._focused_edit.propose_candidates(
                patterns, current_prompt, train_comparisons
            ))

        # Always propose ICL candidates too — framework picks best
        candidates.extend(self._icl.propose_candidates(
            patterns, current_prompt, train_comparisons
        ))

        logger.info(
            f"[HybridDualTrack] Proposed {len(candidates)} total candidates "
            f"(prompt_edits + ICL; failures_so_far={consecutive_failures})"
        )
        return candidates


@register_strategy
class LegacyAppendStrategy(RefinementStrategy):
    """Original append-only refinement for ablation comparisons.

    No validation gate. Appends generated rules to the prompt. Preserved as
    a research baseline — DO NOT use in production.
    """

    NAME = "legacy_append"
    RECOMMENDED_OPTIMIZER_TIER = "small"
    BEST_FOR = ["ablation", "research_baseline"]
    DESCRIPTION = (
        "Legacy append-only behavior. No validation. For ablation comparison only."
    )

    def propose_candidates(
        self,
        patterns: List[Any],
        current_prompt: str,
        train_comparisons: List[Dict[str, Any]],
    ) -> List[RefinementCandidate]:
        if not patterns:
            return []
        analyzer = self.manager.confusion_analyzer
        try:
            rules = analyzer.generate_guidelines_rewrite(patterns, current_prompt)
        except Exception as e:
            logger.warning(f"[LegacyAppend] generation failed: {e}")
            return []
        if not rules:
            return []
        new_prompt = _replace_guidelines_section(current_prompt, rules)
        return [RefinementCandidate(
            kind=CandidateKind.PROMPT_EDIT,
            payload={"new_prompt_text": new_prompt, "rules": rules},
            target_pattern=f"top-{len(patterns)} patterns",
            proposed_by=self.NAME,
            rationale="Legacy: appended without validation",
        )]

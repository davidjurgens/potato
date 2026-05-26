"""
Confusion Analyzer for Solo Mode

Enriches confusion matrix data with example instances, LLM reasoning,
and optional root cause / guideline suggestions via LLM.
"""

import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class ConfusionExample:
    """A single instance that contributed to a confusion pattern."""
    instance_id: str
    text: str  # truncated display text
    llm_reasoning: Optional[str] = None
    llm_confidence: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {
            'instance_id': self.instance_id,
            'text': self.text,
        }
        if self.llm_reasoning is not None:
            result['llm_reasoning'] = self.llm_reasoning
        if self.llm_confidence is not None:
            result['llm_confidence'] = self.llm_confidence
        return result


@dataclass
class ConfusionPattern:
    """An enriched confusion pattern with examples and optional analysis."""
    predicted_label: str
    actual_label: str
    count: int
    percent: float
    examples: List[ConfusionExample] = field(default_factory=list)
    root_cause: Optional[str] = None
    guideline_suggestion: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {
            'predicted_label': self.predicted_label,
            'actual_label': self.actual_label,
            'count': self.count,
            'percent': self.percent,
            'examples': [e.to_dict() for e in self.examples],
        }
        if self.root_cause is not None:
            result['root_cause'] = self.root_cause
        if self.guideline_suggestion is not None:
            result['guideline_suggestion'] = self.guideline_suggestion
        return result


class ConfusionAnalyzer:
    """Analyzes confusion patterns and optionally generates root causes / suggestions.

    Enriches the raw confusion matrix from ValidationTracker with example
    instances, LLM reasoning, and optional LLM-powered analysis.
    """

    MAX_TEXT_LENGTH = 200
    MAX_EXAMPLES_PER_PATTERN = 5

    def __init__(self, app_config: Dict[str, Any], solo_config: Any):
        self.app_config = app_config
        self.solo_config = solo_config
        self._endpoint = None

    def analyze(
        self,
        comparison_history: List[Dict[str, Any]],
        predictions: Dict[str, Dict[str, Any]],
        text_getter: Optional[Callable[[str], str]] = None,
    ) -> List[ConfusionPattern]:
        """Build enriched confusion patterns from comparison history.

        Args:
            comparison_history: List of comparison dicts with instance_id,
                human_label, llm_label, agrees fields.
            predictions: Dict of instance_id -> schema_name -> LLMPrediction.
            text_getter: Optional callable(instance_id) -> text string.

        Returns:
            List of ConfusionPattern sorted by count descending.
        """
        ca_config = self.solo_config.confusion_analysis

        # Group disagreements by (llm_label, human_label)
        groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
        for record in comparison_history:
            if record.get('agrees'):
                continue
            key = (str(record['llm_label']), str(record['human_label']))
            groups[key].append(record)

        # Filter by minimum instance count
        patterns = []
        for (predicted, actual), records in groups.items():
            if len(records) < ca_config.min_instances_for_pattern:
                continue

            total_disagreements = sum(
                1 for r in comparison_history if not r.get('agrees')
            )
            percent = (
                len(records) / total_disagreements * 100
                if total_disagreements > 0 else 0.0
            )

            # Build examples
            examples = []
            for record in records[:self.MAX_EXAMPLES_PER_PATTERN]:
                iid = record['instance_id']
                text = ''
                if text_getter is not None:
                    try:
                        raw = text_getter(iid)
                        text = self._truncate(raw)
                    except Exception:
                        text = ''

                # Get reasoning and confidence from predictions
                reasoning = None
                confidence = None
                if iid in predictions:
                    for schema_preds in predictions[iid].values():
                        pred = schema_preds
                        reasoning = (
                            pred.reasoning
                            if hasattr(pred, 'reasoning')
                            else pred.get('reasoning')
                        )
                        confidence = (
                            pred.confidence_score
                            if hasattr(pred, 'confidence_score')
                            else pred.get('confidence_score')
                        )
                        break

                examples.append(ConfusionExample(
                    instance_id=iid,
                    text=text,
                    llm_reasoning=reasoning,
                    llm_confidence=confidence,
                ))

            patterns.append(ConfusionPattern(
                predicted_label=predicted,
                actual_label=actual,
                count=len(records),
                percent=round(percent, 1),
                examples=examples,
            ))

        # Sort by count descending, limit
        patterns.sort(key=lambda p: p.count, reverse=True)
        return patterns[:ca_config.max_patterns]

    def get_confusion_matrix_data(
        self,
        confusion_matrix: Dict[Tuple[str, str], int],
        labels: List[str],
        label_accuracy: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """Build heatmap-ready data from raw confusion matrix.

        Args:
            confusion_matrix: Dict of (predicted, actual) -> count.
            labels: All label names.
            label_accuracy: Optional per-label accuracy dict.

        Returns:
            Dict with labels, cells, max_count, and label_accuracy.
        """
        cells = []
        max_count = 0
        for predicted in labels:
            for actual in labels:
                count = confusion_matrix.get((predicted, actual), 0)
                cells.append({
                    'predicted': predicted,
                    'actual': actual,
                    'count': count,
                })
                if count > max_count:
                    max_count = count

        return {
            'labels': labels,
            'cells': cells,
            'max_count': max_count,
            'label_accuracy': label_accuracy or {},
        }

    def generate_root_cause(self, pattern: ConfusionPattern) -> Optional[str]:
        """Use LLM to explain why a confusion pattern occurs.

        Args:
            pattern: The confusion pattern to analyze.

        Returns:
            Root cause explanation string, or None if unavailable.
        """
        endpoint = self._get_revision_endpoint()
        if endpoint is None:
            return None

        examples_text = "\n".join(
            f"- Instance {e.instance_id}: \"{e.text}\""
            + (f" (LLM reasoning: {e.llm_reasoning})" if e.llm_reasoning else "")
            for e in pattern.examples
        )

        prompt = (
            f"The LLM predicted \"{pattern.predicted_label}\" when the correct "
            f"label was \"{pattern.actual_label}\", {pattern.count} times.\n\n"
            f"Example instances:\n{examples_text}\n\n"
            f"In 2-3 sentences, explain the most likely root cause of this "
            f"confusion. What pattern in the text makes these labels hard to "
            f"distinguish?\n\n"
            f"Respond with JSON:\n"
            f'{{"root_cause": "<your explanation>"}}'
        )

        try:
            response = endpoint.query(prompt)
            data = self._parse_json(response)
            return data.get('root_cause')
        except Exception as e:
            logger.warning(f"Root cause generation failed: {e}")
            return None

    def suggest_guideline(
        self,
        pattern: ConfusionPattern,
        current_prompt: str,
    ) -> Optional[str]:
        """Use LLM to suggest a guideline to disambiguate a confusion pattern.

        Args:
            pattern: The confusion pattern to address.
            current_prompt: The current annotation prompt text.

        Returns:
            Guideline suggestion string, or None if unavailable.
        """
        endpoint = self._get_revision_endpoint()
        if endpoint is None:
            return None

        # Build examples from the confusion pattern
        examples_text = ""
        for i, ex in enumerate(pattern.examples[:3]):
            examples_text += (
                f"  Example {i+1}: \"{ex.text}\"\n"
                f"    Model labeled: {pattern.predicted_label}"
            )
            if ex.llm_confidence is not None:
                examples_text += f" (confidence: {ex.llm_confidence:.0%})"
            examples_text += f"\n    Correct label: {pattern.actual_label}\n"
            if ex.llm_reasoning:
                examples_text += f"    Model reasoning: {ex.llm_reasoning[:150]}\n"

        prompt = (
            f"You are helping improve annotation guidelines. The system's LLM "
            f"annotator keeps confusing \"{pattern.predicted_label}\" with "
            f"\"{pattern.actual_label}\" ({pattern.count} times).\n\n"
            f"## Confused Examples\n{examples_text}\n"
            f"## Current Prompt\n{current_prompt[:1500]}\n\n"
            f"## Task\n"
            f"Write a GENERAL, actionable guideline (1-2 sentences) to help correctly "
            f"distinguish \"{pattern.actual_label}\" from \"{pattern.predicted_label}\".\n\n"
            f"Requirements:\n"
            f"- Reference GENERAL linguistic features (sentiment polarity, intent, "
            f"  rhetorical structure, framing) that differentiate the two labels.\n"
            f"- DO NOT mention specific phrases or quotes from the examples above — "
            f"  the rule should generalize to unseen cases.\n"
            f"- DO NOT repeat what the current prompt already says.\n"
            f"- Focus on the underlying reason the examples were misclassified, not the surface form.\n\n"
            f"Bad rule (too specific): 'If the text says \"get under your skin\", classify as negative.'\n"
            f"Good rule (general): 'When the text describes emotional discomfort or unease as a reaction to the content, classify as negative rather than positive.'\n\n"
            f"Respond with JSON: {{\"suggestion\": \"<your guideline>\"}}"
        )

        try:
            # OllamaEndpoint requires an output_format (Pydantic model).
            # Other endpoints accept just a prompt string.
            try:
                from pydantic import BaseModel

                class SuggestionResponse(BaseModel):
                    suggestion: str = ""

                response = endpoint.query(prompt, SuggestionResponse)
            except TypeError:
                # Endpoint doesn't require output_format (e.g., OpenAI)
                response = endpoint.query(prompt)

            data = self._parse_json(response)
            suggestion = data.get('suggestion')
            if suggestion:
                logger.info(
                    f"Generated guideline for {pattern.predicted_label}->"
                    f"{pattern.actual_label}: {suggestion[:100]}"
                )
            else:
                logger.warning(
                    f"No suggestion extracted from LLM response for "
                    f"{pattern.predicted_label}->{pattern.actual_label}: "
                    f"{str(response)[:200]}"
                )
            return suggestion
        except Exception as e:
            logger.warning(f"Guideline suggestion failed: {e}")
            return None

    def generate_guidelines_rewrite(
        self,
        patterns: List[ConfusionPattern],
        current_prompt: str,
    ) -> Optional[List[str]]:
        """Generate a complete, non-redundant set of guidelines addressing all confusion patterns.

        Instead of generating one rule at a time (which leads to contradictions),
        this method asks the LLM to produce a coherent set of rules that replaces
        the existing guidelines section entirely.

        Args:
            patterns: List of confusion patterns to address (top N by count).
            current_prompt: The full current annotation prompt.

        Returns:
            List of guideline strings, or None if generation failed.
        """
        endpoint = self._get_revision_endpoint()
        if endpoint is None:
            return None

        # Extract existing guidelines from prompt
        import re as re_mod
        existing_match = re_mod.search(
            r'## (?:Refinement |Annotation )?Guidelines\s*\n(.*)',
            current_prompt, re_mod.DOTALL
        )
        existing_guidelines = existing_match.group(1).strip() if existing_match else "None yet"

        # Format confusion patterns with examples
        patterns_text = ""
        for i, pattern in enumerate(patterns[:8]):
            patterns_text += (
                f"\n{i+1}. Model predicts \"{pattern.predicted_label}\" "
                f"but correct label is \"{pattern.actual_label}\" "
                f"({pattern.count} times)\n"
            )
            for ex in pattern.examples[:2]:
                patterns_text += f"   Text: \"{ex.text}\"\n"
                if ex.llm_reasoning:
                    patterns_text += f"   Model reasoning: {ex.llm_reasoning[:100]}\n"

        # Extract base prompt (without guidelines section) for context
        base_prompt = current_prompt
        if existing_match:
            base_prompt = current_prompt[:existing_match.start()].strip()

        has_existing = existing_guidelines and existing_guidelines != "None yet"

        prompt = (
            f"You are improving annotation guidelines for a text classification task.\n\n"
            f"## Base Task\n{base_prompt[:1000]}\n\n"
            f"## Existing Guidelines\n{existing_guidelines[:1500]}\n\n"
            f"## Current Confusion Patterns\n"
            f"These are errors the model made WITH the guidelines above in place:\n"
            f"{patterns_text}\n"
            f"## Instructions\n"
            + (
                "You are REFINING existing guidelines, NOT replacing them. Follow these rules strictly:\n\n"
                "1. START with the existing guidelines above. KEEP all rules that address patterns NOT in the confusion list.\n"
                "2. For each confusion pattern, check: is there already a rule addressing this label pair?\n"
                "   - YES: The existing rule isn't working. REFINE it with more specific criteria — do NOT reverse its direction.\n"
                "   - NO: ADD a new rule.\n"
                "3. NEVER flip an existing rule from 'classify X as A' to 'classify X as B' — this creates contradictions.\n"
                "4. Rules must be GENERAL — do NOT quote specific phrases from the examples. The rule should apply to unseen cases.\n"
                "5. Output the COMPLETE updated list (existing rules + refinements + new rules).\n"
                "6. Output at most 8 rules total. If you exceed 8, drop the ones with fewest matching examples.\n\n"
                if has_existing else
                "Write 3-8 disambiguation rules. Each rule should:\n"
                "1. Target a specific confusion pattern above\n"
                "2. Give GENERAL criteria (sentiment polarity, intent, rhetorical structure, framing)\n"
                "   — do NOT quote specific phrases from the example texts.\n"
                "3. NOT contradict other rules in your list\n\n"
                "Bad (too specific): 'If the text says \"get under your skin\", classify as negative.'\n"
                "Good (general): 'When the text describes emotional discomfort as a reaction, classify as negative.'\n\n"
            )
            + f"Respond with JSON: {{\"guidelines\": [\"rule 1\", \"rule 2\", ...]}}"
        )

        try:
            from pydantic import BaseModel

            class GuidelinesResponse(BaseModel):
                guidelines: List[str] = []

            try:
                response = endpoint.query(prompt, GuidelinesResponse)
            except TypeError:
                response = endpoint.query(prompt)

            data = self._parse_json(response)
            guidelines = data.get('guidelines', [])

            if guidelines:
                logger.info(
                    f"[Focused Edit] Generated {len(guidelines)} guidelines "
                    f"for {len(patterns)} confusion patterns"
                )
                return guidelines
            else:
                # Fallback: try to extract from 'suggestion' key or raw text
                suggestion = data.get('suggestion')
                if suggestion:
                    return [suggestion]
                logger.warning(
                    f"No guidelines extracted from rewrite response: "
                    f"{str(response)[:200]}"
                )
                return None

        except Exception as e:
            logger.warning(f"Guidelines rewrite failed: {e}")
            return None

    def generate_and_critique_guidelines(
        self,
        patterns: List[ConfusionPattern],
        current_prompt: str,
    ) -> List[str]:
        """Two-pass guideline generation: generate candidates, then critique and filter.

        Pass 1: Generate one suggestion per confusion pattern.
        Pass 2: Evaluate all suggestions together for specificity, consistency,
                and redundancy. Keep only the best ones.

        Args:
            patterns: Confusion patterns to address.
            current_prompt: Current annotation prompt.

        Returns:
            List of approved guideline strings (may be empty).
        """
        endpoint = self._get_revision_endpoint()
        if endpoint is None:
            return []

        # Pass 1: Generate candidates
        candidates = []
        for pattern in patterns[:5]:
            suggestion = self.suggest_guideline(pattern, current_prompt)
            if suggestion:
                candidates.append({
                    'pattern': f"{pattern.predicted_label} -> {pattern.actual_label} ({pattern.count}x)",
                    'suggestion': suggestion,
                })

        if not candidates:
            return []

        logger.info(f"[Generator-Critic] Generated {len(candidates)} candidates, running critic...")

        # Pass 2: Critic evaluates
        # Format each candidate so the rule text is clearly separated from metadata
        candidates_text = ""
        for i, c in enumerate(candidates):
            candidates_text += (
                f"\n### Candidate {i+1} (addresses pattern: {c['pattern']})\n"
                f"RULE TEXT: {c['suggestion']}\n"
            )

        # Extract existing guidelines for contradiction check
        import re as re_mod
        existing_match = re_mod.search(
            r'## (?:Refinement |Annotation )?Guidelines\s*\n(.*)',
            current_prompt, re_mod.DOTALL
        )
        existing_guidelines = existing_match.group(1).strip() if existing_match else ""

        critic_prompt = (
            f"You are a quality reviewer for annotation guidelines. Be strict.\n\n"
            f"## Base Annotation Task\n{current_prompt[:800]}\n\n"
            + (f"## Existing Guidelines (already in production)\n{existing_guidelines[:800]}\n\n" if existing_guidelines else "")
            + f"## Candidate Guidelines to Review\n{candidates_text}\n\n"
            f"## Task\n"
            f"Review each candidate. For each candidate you APPROVE, copy its full "
            f"text verbatim into your response. REJECT any candidate that:\n"
            f"- Is too vague (e.g., 'consider the context' without specifying what)\n"
            f"- Is too narrow (cherry-picks a specific phrase like 'lingering tug' instead of a general pattern)\n"
            f"- Is redundant with another candidate\n"
            + ("- CONTRADICTS an existing guideline above (flips 'classify as A' to 'classify as B')\n"
               "- Restates an existing guideline without adding new criteria\n"
               if existing_guidelines else "")
            + f"- Mentions specific instance text rather than general features\n\n"
            f"Prefer general patterns over specific words. Prefer 2-3 strong rules over 5 weak ones.\n"
            f"If NO candidate is good enough, return an empty list.\n\n"
            f"CRITICAL: Each entry in 'approved' must be ONLY the RULE TEXT from the candidate "
            f"(the part after 'RULE TEXT:' above). Do NOT include 'Candidate N', 'Pattern:', or any "
            f"metadata — just the rule itself. Example:\n"
            f'{{"approved": ["When the text describes emotional discomfort as a reaction, classify as negative rather than positive."]}}'
            f"\n\nRespond with JSON: {{\"approved\": [\"<rule text only>\", ...]}}"
        )

        try:
            from pydantic import BaseModel

            class CriticResponse(BaseModel):
                approved: List[str] = []

            try:
                response = endpoint.query(critic_prompt, CriticResponse)
            except TypeError:
                response = endpoint.query(critic_prompt)

            data = self._parse_json(response)
            approved = data.get('approved', [])

            # Clean up metadata prefixes the critic may have copied
            import re as _re
            cleaned_approved = []
            for a in approved:
                if not isinstance(a, str):
                    continue
                # Strip common prefixes: "Candidate N", "Pattern:", "RULE TEXT:", etc.
                text = a.strip()
                text = _re.sub(r'^(?:Candidate\s+\d+[^:]*:\s*)?', '', text)
                text = _re.sub(r'^(?:Pattern:\s*[^(]*\(\d+x\)\s*)?', '', text, flags=_re.IGNORECASE)
                text = _re.sub(r'^(?:\s*Suggestion:\s*)?', '', text, flags=_re.IGNORECASE)
                text = _re.sub(r'^(?:\s*RULE TEXT:\s*)?', '', text, flags=_re.IGNORECASE)
                text = text.strip()
                if len(text) > 20:
                    cleaned_approved.append(text)

            # Sanity check: reject malformed output (e.g., just indices like ["1","2"])
            valid_approved = cleaned_approved

            if len(valid_approved) < len(approved):
                logger.warning(
                    f"[Generator-Critic] Critic returned {len(approved)} items but only "
                    f"{len(valid_approved)} had full guideline text. Falling back to all candidates."
                )
                return [c['suggestion'] for c in candidates]

            logger.info(
                f"[Generator-Critic] Critic approved {len(valid_approved)}/{len(candidates)} guidelines"
            )
            return valid_approved

        except Exception as e:
            logger.warning(f"Critic pass failed: {e}, using all candidates")
            return [c['suggestion'] for c in candidates]

    def _get_revision_endpoint(self) -> Optional[Any]:
        """Get or create an AI endpoint for LLM analysis."""
        if self._endpoint is not None:
            return self._endpoint

        try:
            from potato.ai.ai_endpoint import AIEndpointFactory

            models = (
                self.solo_config.revision_models
                or self.solo_config.labeling_models
            )
            for model_config in models:
                try:
                    endpoint_config = model_config.to_endpoint_config(temperature_override=0.3)

                    endpoint = AIEndpointFactory.create_endpoint(endpoint_config)
                    if endpoint:
                        self._endpoint = endpoint
                        return endpoint
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"Could not create analysis endpoint: {e}")

        return None

    def _truncate(self, text: str) -> str:
        """Truncate text to MAX_TEXT_LENGTH."""
        if not text:
            return ''
        if len(text) <= self.MAX_TEXT_LENGTH:
            return text
        return text[:self.MAX_TEXT_LENGTH] + '...'

    def _parse_json(self, response: Any) -> Dict[str, Any]:
        """Parse JSON from an LLM response, with robust fallbacks.

        Handles common LLM output issues:
        - JSON wrapped in markdown code blocks
        - JSON embedded in surrounding prose
        - Plain text suggestions (no JSON at all)
        - Slightly malformed JSON (trailing commas, single quotes)
        """
        if isinstance(response, dict):
            return response
        if hasattr(response, 'model_dump'):
            return response.model_dump()

        content = str(response).strip()

        # Try markdown code block extraction
        match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
        if match:
            content = match.group(1).strip()

        # Try direct JSON parse
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # Try extracting a JSON object from anywhere in the text
        match = re.search(r'\{[^{}]*\}', content)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        # Fallback: treat the entire response as a plain text suggestion
        # Strip common preamble patterns
        cleaned = content
        for prefix in [
            'Here is', 'Here\'s', 'My suggestion', 'Suggestion:',
            'Guideline:', 'I suggest', 'I would suggest',
        ]:
            if cleaned.lower().startswith(prefix.lower()):
                cleaned = cleaned[len(prefix):].lstrip(':').strip()
                break

        if cleaned and len(cleaned) > 10:
            return {'suggestion': cleaned}

        return {}

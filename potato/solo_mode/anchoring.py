"""
Anchoring measurement for Solo Mode.

Showing the LLM's suggestion before the human answers shifts the human's
labels toward it and inflates the LLM's measured agreement (Schroeder, Roy &
Kabbara, "Just Put a Human in the Loop? Investigating LLM-Assisted Annotation
for Subjective Tasks", Findings of ACL 2025). Solo Mode hands the corpus to the
LLM when agreement crosses a threshold, so agreement measured on anchored
labels can end human annotation early.

This module records, for each human-LLM comparison, whether the human could
see the suggestion when they answered, keeps the two agreement rates apart,
and tells the handoff gate which one to read. A comparison is filed under the
visibility of the human's *first* answer for that item and schema. A later
re-label (a disagreement re-review, say) happens after the human has seen the
LLM's label, so it may move the overall agreement rate but never the blind
one.
"""

import hashlib
import logging
from typing import Any, Dict, Optional, Set

logger = logging.getLogger(__name__)

SHOWN = 'shown'
BLIND = 'blind'

#: Comparisons each bucket needs before the gap between them is reported. A
#: gap over one blind item is noise, and a dashboard that shows it invites a
#: reading it cannot support.
MIN_FOR_GAP = 5


class AnchoringTracker:
    """Blind-versus-shown agreement and the handoff basis that follows from it."""

    def __init__(self, config, salt: str = ''):
        """
        Args:
            config: A SuggestionsConfig.
            salt: Mixed into the blind-sample hash so two studies over the same
                items do not blind the same ones. The task name is the default.
        """
        self.config = config
        self.salt = salt
        self._buckets: Dict[str, Dict[str, int]] = {
            SHOWN: {'compared': 0, 'agreements': 0},
            BLIND: {'compared': 0, 'agreements': 0},
        }
        #: comparison key ("instance:schema") -> bucket it was filed under
        self._filed: Dict[str, str] = {}
        #: instances whose suggestion was on screen when the human answered
        self._shown_instances: Set[str] = set()
        #: shown comparisons whose label came from the Accept button
        self._accepted = 0

    # === Which items are blind ===

    def is_blind(self, instance_id: str) -> bool:
        """Whether the suggestion is withheld until the human has answered."""
        display = self.config.display
        if display == 'after_label':
            return True
        if display != 'blind_sample':
            return False
        # Deterministic, so a reload or a restart blinds the same items.
        # hash() is salted per process and would not be.
        digest = hashlib.blake2b(
            f"{self.salt}:{instance_id}".encode('utf-8'), digest_size=8
        ).digest()
        return int.from_bytes(digest, 'big') / 2 ** 64 < self.config.blind_rate

    # === Recording ===

    def mark_shown(self, instance_id: str) -> None:
        self._shown_instances.add(instance_id)

    def was_shown(self, instance_id: str) -> bool:
        return instance_id in self._shown_instances

    def record(self, key: str, agrees: bool, shown: bool,
               accepted: bool = False) -> None:
        """File one comparison. Only the first comparison for a key counts."""
        if key in self._filed:
            return
        bucket = SHOWN if shown else BLIND
        self._filed[key] = bucket
        self._buckets[bucket]['compared'] += 1
        if agrees:
            self._buckets[bucket]['agreements'] += 1
        if shown and accepted:
            self._accepted += 1

    # === Reading ===

    def _rate(self, bucket: str) -> Optional[float]:
        b = self._buckets[bucket]
        return b['agreements'] / b['compared'] if b['compared'] else None

    def blind_count(self) -> int:
        return self._buckets[BLIND]['compared']

    def handoff_basis(self, blind_items_left: Optional[int] = None) -> str:
        """Which agreement the handoff gate should read.

        ``blind`` once there are ``minimum_blind_sample`` blind comparisons.
        Before that, ``waiting`` when the configured mode exists to produce
        blind comparisons, and ``all`` under ``before_label``, which keeps
        the original behaviour for studies that never blind anything.

        ``blind_items_left`` is how many blind items the human has still to
        label. When even all of them cannot reach the minimum -- a small
        corpus, or a low blind_rate -- waiting would never end and the study
        could not hand over or finish. The basis is then ``blind_short``:
        blind agreement over the blind comparisons there are, or all
        agreement if there are none.
        """
        if self.blind_count() >= self.config.minimum_blind_sample:
            return 'blind'
        if self.config.display in ('after_label', 'blind_sample'):
            if (blind_items_left is not None and self.blind_count() + blind_items_left
                    < self.config.minimum_blind_sample):
                return 'blind_short'
            return 'waiting'
        return 'all'

    def blind_agreement_rate(self) -> Optional[float]:
        return self._rate(BLIND)

    def stats(self, blind_items_left: Optional[int] = None) -> Dict[str, Any]:
        shown = self._buckets[SHOWN]
        blind = self._buckets[BLIND]
        shown_rate = self._rate(SHOWN)
        blind_rate = self._rate(BLIND)
        gap = (shown_rate - blind_rate
               if shown['compared'] >= MIN_FOR_GAP and blind['compared'] >= MIN_FOR_GAP
               else None)
        return {
            'display': self.config.display,
            'blind_rate_configured': (
                self.config.blind_rate
                if self.config.display == 'blind_sample' else None),
            'minimum_blind_sample': self.config.minimum_blind_sample,
            'shown': {**shown, 'agreement_rate': shown_rate},
            'blind': {**blind, 'agreement_rate': blind_rate},
            # Positive means the human agreed more often when they could see
            # the suggestion: the anchoring signal.
            'gap': gap,
            'accepted_with_button': self._accepted,
            'accept_rate': (self._accepted / shown['compared']
                            if shown['compared'] else None),
            'handoff_basis': self.handoff_basis(blind_items_left),
            'blind_items_left': blind_items_left,
            'min_for_gap': MIN_FOR_GAP,
        }

    # === Persistence ===

    def to_dict(self) -> Dict[str, Any]:
        return {
            'buckets': self._buckets,
            'filed': self._filed,
            'shown_instances': sorted(self._shown_instances),
            'accepted': self._accepted,
        }

    def load(self, data: Optional[Dict[str, Any]]) -> None:
        if not data:
            return
        for bucket in (SHOWN, BLIND):
            saved = (data.get('buckets') or {}).get(bucket) or {}
            self._buckets[bucket] = {
                'compared': int(saved.get('compared', 0)),
                'agreements': int(saved.get('agreements', 0)),
            }
        self._filed = dict(data.get('filed') or {})
        self._shown_instances = set(data.get('shown_instances') or [])
        self._accepted = int(data.get('accepted', 0))

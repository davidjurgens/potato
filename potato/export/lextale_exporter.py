"""
LexTALE Exporter

Scores a lexical decision vocabulary test (LexTALE, Lemhöfer & Broersma
2012) given as a radio scheme with a ``lextale`` block:

.. code-block:: yaml

    - annotation_type: radio
      name: lexicality
      description: Is this an existing English word?
      labels: ["yes", "no"]
      lextale: {answer_field: is_word, word: "yes", nonword: "no"}

Each item's ``answer_field`` says whether it is a word (``word``, ``yes``,
``true`` or ``1``) or a nonword. The answer field is never sent to the page.

``lextale.csv``, one row per participant: words and nonwords answered and
correct, and the LexTALE score, the average of the percentage of words
correct and the percentage of nonwords correct. The item lists are not
shipped with Potato; use the published lists under their authors' terms.
"""

from __future__ import annotations

import csv
import os
from collections import defaultdict
from typing import Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult

COLUMNS = ["user_id", "schema", "words", "words_correct", "nonwords", "nonwords_correct",
           "pct_words_correct", "pct_nonwords_correct", "lextale_score", "unanswered_items"]
_TRUE = {"word", "yes", "true", "1", "w"}


class LexTALEExporter(BaseExporter):
    format_name = "lextale"
    description = "LexTALE-style vocabulary test scores (Lemhöfer & Broersma 2012)"
    file_extensions = [".csv"]

    def _schemes(self, context):
        return [s for s in context.schemas or [] if isinstance(s.get("lextale"), dict)]

    @staticmethod
    def _phase_page_schemes(context):
        """(page, scheme) for lextale schemes on phase pages. A lextale block
        is scored per item from the item's answer field, and a phase page
        has no item, so these cannot be scored."""
        from .survey_experiment_exporter import phase_page_schemes
        return [(page, s) for page, schemes in phase_page_schemes(context).items()
                for s in schemes if isinstance(s.get("lextale"), dict)]

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        if self._schemes(context):
            return True, ""
        on_pages = self._phase_page_schemes(context)
        if on_pages:
            return False, ("; ".join(f"{s.get('name')} is on the phase page {page}" for page, s in on_pages)
                           + ". A lextale block is scored per item from the item's answer field, "
                             "so the scheme must be in annotation_schemes")
        return False, "No scheme has a lextale block"

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        os.makedirs(output_path, exist_ok=True)
        rows = []
        for scheme in self._schemes(context):
            lt = scheme["lextale"]
            field, word_label = lt["answer_field"], str(lt.get("word", "word"))
            keyed = {iid: str(item.get(field, "")).strip().lower() in _TRUE
                     for iid, item in context.items.items()
                     if isinstance(item, dict) and str(item.get(field, "")).strip() != ""}
            tally = defaultdict(lambda: [0, 0, 0, 0, set()])
            for ann in context.annotations:
                iid, uid = str(ann.get("instance_id")), str(ann.get("user_id"))
                if iid not in keyed:
                    continue
                labels = (ann.get("labels") or {}).get(scheme["name"]) or {}
                chosen = next((str(k) for k, v in labels.items() if v not in (None, "", False)), None)
                t = tally[uid]
                t[4].add(iid)
                if chosen is None:
                    continue
                said_word = chosen == word_label
                if keyed[iid]:
                    t[0] += 1
                    t[1] += int(said_word)
                else:
                    t[2] += 1
                    t[3] += int(not said_word)
            for uid, (w, wc, n, nc, seen) in sorted(tally.items()):
                pw = 100.0 * wc / w if w else None
                pn = 100.0 * nc / n if n else None
                score = (pw + pn) / 2 if pw is not None and pn is not None else None
                rows.append({"user_id": uid, "schema": scheme["name"], "words": w, "words_correct": wc,
                             "nonwords": n, "nonwords_correct": nc,
                             "pct_words_correct": "" if pw is None else round(pw, 2),
                             "pct_nonwords_correct": "" if pn is None else round(pn, 2),
                             "lextale_score": "" if score is None else round(score, 2),
                             "unanswered_items": len(keyed) - (w + n)})
        path = os.path.join(output_path, "lextale.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            wr = csv.DictWriter(f, fieldnames=COLUMNS)
            wr.writeheader()
            wr.writerows(rows)
        warnings = [f"{s.get('name')} is on the phase page {page} and was not scored: a lextale "
                    "block is scored per item, so put the scheme in annotation_schemes"
                    for page, s in self._phase_page_schemes(context)]
        return ExportResult(success=True, format_name=self.format_name, files_written=[path],
                            warnings=warnings,
                            stats={"num_participants": len(rows)})

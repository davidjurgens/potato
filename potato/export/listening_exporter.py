"""
Listening Test Exporter

For ``listening_test`` schemes. The page stores ratings by slot (``s1``,
``A``, ...); this export maps each slot back to its condition using the same
seeded plan the server built for that participant and item
(potato/listening/plan.py), then writes:

    listening_ratings.csv    one row per rating: participant, item, scheme,
                             method, slot, condition, scale, score
    listening_summary.csv    per scheme, condition and scale: n, mean, SD and
                             95% confidence interval (MOS for ACR/DCR/P.835,
                             CMOS for CCR, MUSHRA and BS.1116 means)
    listening_abx.csv        per participant and scheme: trials, correct,
                             proportion and one-sided binomial p (ABX only)
    listening_screening.csv  per participant and MUSHRA scheme: the
                             ITU-R BS.1534-3 post-screening counts and whether
                             the rule excludes them (MUSHRA only)

Scores: ACR, DCR and the P.835 scales are 5 (best) to 1; CCR is -3..+3 for the
second sample against the first, also written as each condition's score
against the other; MUSHRA 0-100; BS.1116 1.0-5.0.

BS.1534-3 post-screening, as implemented: an assessor is excluded when they
rate the hidden reference below 90 on more than 15% of items, or the mid-range
anchor (the highest anchor cut-off) above 90 on more than 15% of items. An item
on which more than 25% of assessors rate the mid anchor above 90 is left out of
the anchor test for everyone. Excluded assessors are flagged, never removed.
"""

from __future__ import annotations

import csv
import json
import math
import os
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult


def _decode(labels: Any, schema: str) -> Optional[dict]:
    if not isinstance(labels, dict):
        return None
    raw = labels.get(schema)
    if raw is None and len(labels) == 1:
        raw = next(iter(labels.values()))
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    return raw if isinstance(raw, dict) else None


def _t95(n: int) -> float:
    if n < 2:
        return float("nan")
    try:
        from scipy.stats import t
        return float(t.ppf(0.975, n - 1))
    except Exception:
        return 1.96


def _binom_p(k: int, n: int) -> float:
    """P(X >= k) for X ~ Binomial(n, 0.5)."""
    return sum(math.comb(n, i) for i in range(k, n + 1)) / (2 ** n) if n else float("nan")


class ListeningTestExporter(BaseExporter):
    format_name = "listening_test"
    description = "Listening tests: ratings by condition, MOS / MUSHRA means with CIs, ABX, BS.1534 screening"
    file_extensions = [".csv"]

    def _schemes(self, context: ExportContext) -> Dict[str, dict]:
        return {s["name"]: s for s in context.schemas or []
                if s.get("annotation_type") == "listening_test"}

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        if not self._schemes(context):
            return False, "No listening_test scheme in this project"
        if not context.annotations:
            return False, "No annotations to export"
        return True, ""

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        from potato.listening.plan import ANCHOR_PREFIX, HIDDEN_REFERENCE, build_plan
        os.makedirs(output_path, exist_ok=True)
        schemes = self._schemes(context)
        rows: List[Dict[str, Any]] = []
        abx: Dict[Tuple[str, str], List[int]] = defaultdict(list)
        warnings: List[str] = []

        for ann in context.annotations:
            uid, iid = str(ann.get("user_id", "")), str(ann.get("instance_id", ""))
            for name, scheme in schemes.items():
                answer = _decode((ann.get("labels") or {}).get(name), name)
                if not answer:
                    continue
                item = context.items.get(iid)
                if not isinstance(item, dict):
                    warnings.append(f"item {iid} is not in the data; its {name} ratings were skipped")
                    continue
                plan = build_plan(scheme, item, uid, iid)
                by_slot = {s["slot"]: s["condition"] for s in plan["slots"]}
                method = plan["method"]
                base = {"user_id": uid, "instance_id": iid, "schema": name, "method": method}

                def add(slot, scale, score, condition=None):
                    rows.append({**base, "slot": slot, "condition": condition or by_slot.get(slot, ""),
                                 "scale": scale, "score": score})

                if method in ("mushra", "bs1116"):
                    for slot, score in (answer.get("ratings") or {}).items():
                        add(slot, method, score)
                elif method in ("acr", "dcr"):
                    if isinstance(answer.get("rating"), int):
                        add("s1", method, 5 - answer["rating"])
                elif method == "p835":
                    for key in ("sig", "bak", "ovrl"):
                        if isinstance(answer.get(key), int):
                            add("s1", key, 5 - answer[key])
                elif method == "ccr":
                    if isinstance(answer.get("rating"), int) and len(plan["slots"]) == 2:
                        score = 3 - answer["rating"]       # second sample vs first
                        first, second = plan["slots"][0]["condition"], plan["slots"][1]["condition"]
                        add("s2", "ccr", score, condition=second)
                        add("s1", "ccr", -score, condition=first)
                elif method == "abx":
                    choice = answer.get("choice")
                    if choice in ("A", "B"):
                        correct = int(choice == plan.get("x_is"))
                        add("X", "abx_correct", correct, condition=f"{by_slot.get('A')}|{by_slot.get('B')}")
                        abx[(uid, name)].append(correct)

        files: List[str] = []

        def write(fname, columns, data):
            path = os.path.join(output_path, fname)
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
                w.writeheader()
                for r in data:
                    w.writerow(r)
            files.append(path)

        write("listening_ratings.csv",
              ["user_id", "instance_id", "schema", "method", "slot", "condition", "scale", "score"], rows)

        groups: Dict[Tuple[str, str, str], List[float]] = defaultdict(list)
        for r in rows:
            if r["scale"] != "abx_correct":
                groups[(r["schema"], r["condition"], r["scale"])].append(float(r["score"]))
        summary = []
        for (schema, condition, scale), values in sorted(groups.items()):
            n = len(values)
            mean = sum(values) / n
            sd = math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1)) if n > 1 else float("nan")
            half = _t95(n) * sd / math.sqrt(n) if n > 1 else float("nan")
            summary.append({"schema": schema, "condition": condition, "scale": scale, "n": n,
                            "mean": round(mean, 4), "sd": round(sd, 4) if n > 1 else "",
                            "ci95_low": round(mean - half, 4) if n > 1 else "",
                            "ci95_high": round(mean + half, 4) if n > 1 else ""})
        write("listening_summary.csv",
              ["schema", "condition", "scale", "n", "mean", "sd", "ci95_low", "ci95_high"], summary)

        if abx:
            out = []
            for (uid, schema), results in sorted(abx.items()):
                n, k = len(results), sum(results)
                out.append({"user_id": uid, "schema": schema, "trials": n, "correct": k,
                            "proportion": round(k / n, 4), "p_one_sided": round(_binom_p(k, n), 6)})
            write("listening_abx.csv", ["user_id", "schema", "trials", "correct", "proportion",
                                        "p_one_sided"], out)

        mushra = [n for n, s in schemes.items() if s.get("method", "mushra") == "mushra"]
        if mushra:
            write("listening_screening.csv",
                  ["user_id", "schema", "items", "hidden_reference_below_90", "hidden_reference_pct",
                   "anchor_items", "mid_anchor_above_90", "mid_anchor_pct", "excluded", "reason"],
                  self._screening(rows, schemes, mushra, HIDDEN_REFERENCE, ANCHOR_PREFIX))

        return ExportResult(success=True, format_name=self.format_name, files_written=files,
                            warnings=sorted(set(warnings)),
                            stats={"num_ratings": len(rows), "num_conditions": len(summary)})

    @staticmethod
    def _screening(rows, schemes, names, hidden, anchor_prefix) -> List[Dict[str, Any]]:
        out = []
        for schema in names:
            cutoffs = sorted(int(a) for a in (schemes[schema].get("anchors") or []))
            mid = f"{anchor_prefix}{cutoffs[-1]}" if cutoffs else None
            ref: Dict[str, Dict[str, float]] = defaultdict(dict)
            anc: Dict[str, Dict[str, float]] = defaultdict(dict)
            for r in rows:
                if r["schema"] != schema:
                    continue
                if r["condition"] == hidden:
                    ref[r["user_id"]][r["instance_id"]] = float(r["score"])
                elif mid and r["condition"] == mid:
                    anc[r["user_id"]][r["instance_id"]] = float(r["score"])
            # Items where the anchor did not degrade enough for anyone to hear.
            per_item = defaultdict(list)
            for uid, items in anc.items():
                for iid, score in items.items():
                    per_item[iid].append(score > 90)
            lenient = {iid for iid, flags in per_item.items() if sum(flags) / len(flags) > 0.25}
            for uid in sorted(set(ref) | set(anc)):
                r_items = ref.get(uid, {})
                low = sum(1 for s in r_items.values() if s < 90)
                r_pct = low / len(r_items) if r_items else 0.0
                a_items = {i: s for i, s in anc.get(uid, {}).items() if i not in lenient}
                high = sum(1 for s in a_items.values() if s > 90)
                a_pct = high / len(a_items) if a_items else 0.0
                reasons = []
                if r_pct > 0.15:
                    reasons.append("hidden reference below 90 on more than 15% of items")
                if a_pct > 0.15:
                    reasons.append("mid anchor above 90 on more than 15% of items")
                out.append({"user_id": uid, "schema": schema, "items": len(r_items),
                            "hidden_reference_below_90": low, "hidden_reference_pct": round(r_pct, 4),
                            "anchor_items": len(a_items), "mid_anchor_above_90": high,
                            "mid_anchor_pct": round(a_pct, 4), "excluded": int(bool(reasons)),
                            "reason": "; ".join(reasons)})
        return out

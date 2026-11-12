"""
Cultural domain analysis exporter (format ``cultural_domain``).

Reads ``free_list``, ``triad_test`` and ``card_sort`` answers, from items and
from phase pages, and the categorical questions named in
``consensus_schemes``. The analyses are described in
:mod:`potato.cultural_domain.analysis`. Files written, each only when there
is something to put in it:

    freelist_items.csv                 one row per listed item: user, item
                                       (normalized), what was typed, rank,
                                       list length, time
    salience.csv                       per item: frequency, % of informants,
                                       mean rank, Smith's S, Sutrop's CSI
    pilesort_cooccurrence_<key>.csv    item x item: proportion of informants
                                       who put the pair in one pile
    pilesort_informants_<key>.csv      informant x informant: proportion of
                                       item pairs sorted alike
    pilesort_pairs.csv                 long form: user, item pair, same pile
    triads_answers.csv                 one row per answered triad
    triads_similarity_<key>.csv        item x item similarity from triads
    consensus_informants.csv           competence per informant
    consensus_answers.csv              estimated answer key, posterior,
                                       majority answer
    consensus_summary.json             eigenvalues, ratio, warnings

``<key>`` is the scheme name, followed by the item id for a scheme on items.

Options (``--option key=value``):

    normalize           true / false / lowercase / trim (comma-separated);
                        overrides each free_list scheme's own ``normalize``
    synonyms            path to a CSV of ``variant,canonical`` rows, applied
                        after normalizing
    consensus_schemes   comma-separated scheme names: radio, select or likert
                        questions, one question per item (on items) or per
                        scheme (on phase pages)
    consensus_choices   the number of options L, when a scheme does not say
    consensus_min_answers  informants with fewer answers are left out (2)
"""

from __future__ import annotations

import csv
import json
import logging
import os
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult

logger = logging.getLogger(__name__)

CATEGORICAL_TYPES = ("radio", "select", "likert")
DOMAIN_TYPES = ("free_list", "triad_test", "card_sort")


def _parse_json(raw: Any) -> Optional[dict]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip().startswith("{"):
        try:
            value = json.loads(raw)
        except ValueError:
            return None
        return value if isinstance(value, dict) else None
    return None


def _blob(labels: Any, schema: str) -> Optional[dict]:
    """The JSON answer of a one-hidden-input scheme from ``labels[schema]``."""
    if not isinstance(labels, dict):
        return None
    raw = labels.get(schema)
    if isinstance(raw, dict):
        if schema in raw:
            raw = raw[schema]
        elif len(raw) == 1:
            raw = next(iter(raw.values()))
    return _parse_json(raw)


def _categorical(entry: Any, schema: str) -> Optional[str]:
    """The chosen option from ``{label_name: value}``.

    radio and likert store the option as both name and value; a type that
    stores under a generic label name (the scheme's own name) keeps the
    option in the value.
    """
    if not isinstance(entry, dict) or not entry:
        return None
    entry = {k: v for k, v in entry.items() if k != "free_response"}
    if len(entry) != 1:
        return None
    name, value = next(iter(entry.items()))
    if isinstance(value, str) and value and value not in ("true", "True", "on", "1") and name in (schema, "select"):
        return value
    return str(name)


def _truthy(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(name)).strip("_") or "x"


class CulturalDomainExporter(BaseExporter):
    format_name = "cultural_domain"
    description = ("Cultural domain analysis: free-list salience (Smith's S, Sutrop's CSI), "
                   "pile-sort and triad similarity matrices, cultural consensus")
    file_extensions = [".csv", ".json"]

    # ------------------------------------------------------------------

    def _all_schemes(self, context: ExportContext) -> Dict[str, dict]:
        """Item schemes plus the questions in phase files and inline phases."""
        schemes: Dict[str, dict] = {}
        for s in context.schemas or []:
            if isinstance(s, dict) and s.get("name"):
                schemes[s["name"]] = s
        config = context.config or {}
        phases = config.get("phases")
        try:
            from potato.server_utils.phase_files import (
                load_phase_schemes, question_file_phases, resolve_phase_file)
            base = config.get("task_dir") or os.getcwd()
            for _name, filename in question_file_phases(config):
                path = resolve_phase_file(filename, os.path.join(base, "config.yaml")) \
                    or os.path.join(base, filename)
                if path and os.path.exists(path):
                    for s in load_phase_schemes(path) or []:
                        if isinstance(s, dict) and s.get("name"):
                            schemes.setdefault(s["name"], s)
        except Exception:
            logger.debug("could not read the phase question files", exc_info=True)
        entries = phases.values() if isinstance(phases, dict) else (phases or [])
        for phase in entries:
            if isinstance(phase, dict):
                for s in phase.get("annotation_schemes") or []:
                    if isinstance(s, dict) and s.get("name"):
                        schemes.setdefault(s["name"], s)
        return schemes

    def _of_type(self, schemes: Dict[str, dict], kind: str) -> Dict[str, dict]:
        return {n: s for n, s in schemes.items() if s.get("annotation_type") == kind}

    def _records(self, context: ExportContext, names) -> List[Tuple[str, str, str, Any]]:
        """``(user, instance_id or "", schema, labels-entry)`` for each answer.

        Phase pages give one row per label; the last row for a user and
        scheme wins.
        """
        names = set(names)
        out = []
        for ann in context.annotations or []:
            labels = ann.get("labels") or {}
            for name in names:
                if name in labels:
                    out.append((str(ann.get("user_id", "")), str(ann.get("instance_id", "")),
                                name, labels[name]))
        latest: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for row in context.phase_responses or []:
            if row.get("schema") not in names or row.get("superseded") or row.get("hidden"):
                continue
            k = (str(row.get("user_id", "")), row["schema"])
            latest.setdefault(k, {})
            latest[k][str(row.get("label_name"))] = row.get("value")
        for (user, name), entry in latest.items():
            out.append((user, "", name, entry))
        return out

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        schemes = self._all_schemes(context)
        usable = [n for n, s in schemes.items()
                  if s.get("annotation_type") in DOMAIN_TYPES + CATEGORICAL_TYPES]
        if not usable:
            return False, ("No free_list, triad_test, card_sort or categorical (consensus) "
                           "scheme in this project")
        if not context.annotations and not context.phase_responses:
            return False, "No annotations to export"
        # A radio, select or likert answer is used only when consensus_schemes
        # names it, which export() checks: options do not reach this method.
        if not self._records(context, usable):
            return False, ("No answers to the free_list, triad_test, card_sort or categorical "
                           "(consensus) schemes yet")
        return True, ""

    # ------------------------------------------------------------------

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        from potato.cultural_domain import analysis as A
        options = dict(options or {})
        self._synonym_cache = {}
        os.makedirs(output_path, exist_ok=True)
        schemes = self._all_schemes(context)
        files: List[str] = []
        warnings: List[str] = []
        stats: Dict[str, Any] = {}

        def write_rows(fname, columns, rows):
            path = os.path.join(output_path, fname)
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
                w.writeheader()
                for r in rows:
                    w.writerow(r)
            files.append(path)

        def write_matrix(fname, labels, matrix, corner="item"):
            path = os.path.join(output_path, fname)
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow([corner] + list(labels))
                for name, row in zip(labels, matrix):
                    w.writerow([name] + ["" if v != v else round(float(v), 6) for v in row])
            files.append(path)

        # ---------------- free lists ----------------
        free = self._of_type(schemes, "free_list")
        if free:
            synonyms_path = options.get("synonyms")
            override = options.get("normalize")
            from potato.server_utils.schemas.free_list import MAX_ITEM_LENGTH, list_limit
            item_rows, sal_rows = [], []
            lists: Dict[Tuple[str, str], List[List[str]]] = defaultdict(list)
            cut: Dict[str, int] = defaultdict(int)
            for user, iid, name, entry in self._records(context, free):
                answer = _blob({name: entry}, name)
                if not answer or not isinstance(answer.get("items"), list):
                    continue
                steps = self._steps(override, free[name].get("normalize"))
                synonyms = self._synonyms(synonyms_path, steps, context, warnings)
                # The page enforces these limits; a stored answer that breaks
                # them did not come from the page and is cut to fit.
                limit = list_limit(free[name])
                raw = [str(x) for x in answer["items"]]
                if len(raw) > limit or any(len(x) > MAX_ITEM_LENGTH for x in raw):
                    cut[name] += 1
                raw = [x[:MAX_ITEM_LENGTH] for x in raw[:limit]]
                timings = answer.get("timings_ms") or []
                cleaned = A.clean_list(raw, steps, synonyms)
                lists[(name, iid)].append(cleaned)
                seen = set()
                rank = 0
                for pos, typed in enumerate(raw):
                    norm = A.normalize_item(typed, steps)
                    item = synonyms.get(norm, norm) if synonyms else norm
                    if not item.strip() or item in seen:
                        continue
                    seen.add(item)
                    rank += 1
                    item_rows.append({"schema": name, "instance_id": iid, "user_id": user,
                                      "item": item, "typed": typed, "rank": rank,
                                      "list_length": len(cleaned),
                                      "time_ms": timings[pos] if pos < len(timings) else ""})
            for (name, iid), group in sorted(lists.items()):
                n = len([g for g in group if g])
                for r in A.salience(group):
                    sal_rows.append({"schema": name, "instance_id": iid, "n_lists": n,
                                     **{k: (round(v, 6) if isinstance(v, float) else v)
                                        for k, v in r.items()}})
            if item_rows:
                write_rows("freelist_items.csv", ["schema", "instance_id", "user_id", "item", "typed",
                                                  "rank", "list_length", "time_ms"], item_rows)
                write_rows("salience.csv", ["schema", "instance_id", "n_lists", "item", "frequency",
                                            "pct_informants", "mean_rank", "smith_s", "sutrop_csi"],
                           sal_rows)
            for name, n in sorted(cut.items()):
                warnings.append(f"{name}: {n} free list(s) had more than {list_limit(free[name])} "
                                f"items or an item over {MAX_ITEM_LENGTH} characters; only the "
                                "first items and characters up to those limits were used")
            stats["free_lists"] = sum(len(g) for g in lists.values())

        # ---------------- pile sorts ----------------
        piles = self._of_type(schemes, "card_sort")
        if piles:
            by_domain: Dict[Tuple[str, str], Dict[str, dict]] = defaultdict(dict)
            for user, iid, name, entry in self._records(context, piles):
                answer = _blob({name: entry}, name)
                if not answer:
                    continue
                groups = {g: [str(x) for x in v] for g, v in answer.items() if isinstance(v, list)}
                if any(groups.values()):
                    by_domain[(name, iid)][user] = groups
            pair_rows = []
            for (name, iid), sorts in sorted(by_domain.items()):
                items = self._pile_items(context, piles[name], iid, sorts)
                users = sorted(sorts)
                mats = [A.pile_matrix(sorts[u], items) for u in users]
                key = _safe(name) + (f"_{_safe(iid)}" if iid else "")
                write_matrix(f"pilesort_cooccurrence_{key}.csv", items, A.pile_aggregate(mats))
                write_matrix(f"pilesort_informants_{key}.csv", users, A.informant_agreement(mats),
                             corner="user_id")
                for u, m in zip(users, mats):
                    for a in range(len(items)):
                        for b in range(a + 1, len(items)):
                            if m[a, b] == m[a, b]:
                                pair_rows.append({"schema": name, "instance_id": iid, "user_id": u,
                                                  "item_a": items[a], "item_b": items[b],
                                                  "same_pile": int(m[a, b])})
            if pair_rows:
                write_rows("pilesort_pairs.csv", ["schema", "instance_id", "user_id", "item_a", "item_b",
                                                  "same_pile"], pair_rows)
            stats["pile_sorts"] = sum(len(s) for s in by_domain.values())

        # ---------------- triads ----------------
        triad_schemes = self._of_type(schemes, "triad_test")
        if triad_schemes:
            answers_rows = []
            by_domain_t: Dict[Tuple[str, str], List[list]] = defaultdict(list)
            for user, iid, name, entry in self._records(context, triad_schemes):
                answer = _blob({name: entry}, name)
                if not answer or not isinstance(answer.get("triads"), list):
                    continue
                for pos, t in enumerate(answer["triads"], start=1):
                    if not (isinstance(t, list) and len(t) == 4) or t[3] is None:
                        continue
                    t = [str(t[0]), str(t[1]), str(t[2]), str(t[3])]
                    by_domain_t[(name, iid)].append(t)
                    answers_rows.append({"schema": name, "instance_id": iid, "user_id": user,
                                         "position": pos, "item_1": t[0], "item_2": t[1],
                                         "item_3": t[2], "odd": t[3], "design": answer.get("design", "")})
            for (name, iid), answers in sorted(by_domain_t.items()):
                items = self._triad_items(context, triad_schemes[name], iid, answers)
                sim, _shown = A.triad_similarity(answers, items)
                key = _safe(name) + (f"_{_safe(iid)}" if iid else "")
                write_matrix(f"triads_similarity_{key}.csv", items, sim)
            if answers_rows:
                write_rows("triads_answers.csv", ["schema", "instance_id", "user_id", "position", "item_1",
                                                  "item_2", "item_3", "odd", "design"], answers_rows)
            stats["triads_answered"] = len(answers_rows)

        # ---------------- consensus ----------------
        wanted = options.get("consensus_schemes")
        if wanted:
            if isinstance(wanted, str):
                wanted = [w.strip() for w in wanted.split(",") if w.strip()]
            summary = self._consensus(context, schemes, list(wanted), options, warnings,
                                      write_rows, output_path, files)
            if summary:
                stats["consensus_informants"] = summary["n_informants"]
                stats["consensus_questions"] = summary["n_questions"]

        if not files:
            if wanted:
                why = "no free-list, triad, pile-sort or consensus answers found"
            elif any(s.get("annotation_type") in DOMAIN_TYPES for s in schemes.values()):
                why = ("no free-list, triad or pile-sort answers found. For a cultural consensus "
                       "analysis of radio, select or likert questions, pass --option "
                       "consensus_schemes=<scheme names>")
            else:
                why = ("this project has no free_list, triad_test or card_sort scheme, and "
                       "radio, select and likert questions are analysed only when named: pass "
                       "--option consensus_schemes=<scheme names> for a cultural consensus analysis")
            return ExportResult(success=False, format_name=self.format_name, files_written=[],
                                warnings=sorted(set(warnings)), errors=[f"Nothing to export: {why}"],
                                stats=stats)
        return ExportResult(success=True, format_name=self.format_name, files_written=files,
                            warnings=sorted(set(warnings)), stats=stats)

    # ------------------------------------------------------------------

    @staticmethod
    def _steps(override, scheme_value) -> List[str]:
        from potato.server_utils.schemas.free_list import normalize_steps
        if override is not None and override != "":
            if isinstance(override, str):
                low = override.strip().lower()
                if low in ("true", "yes", "1"):
                    return ["lowercase", "trim"]
                if low in ("false", "no", "0", "none"):
                    return []
                return [s.strip() for s in low.split(",") if s.strip()]
            return normalize_steps(override)
        return normalize_steps(scheme_value)

    def _synonyms(self, path, steps, context, warnings) -> Dict[str, str]:
        if not path:
            return {}
        from potato.cultural_domain.analysis import load_synonyms
        candidates = [path]
        base = (context.config or {}).get("task_dir")
        if base and not os.path.isabs(path):
            candidates.append(os.path.join(base, path))
        for candidate in candidates:
            if os.path.exists(candidate):
                key = (os.path.abspath(candidate), tuple(steps))
                if not hasattr(self, "_synonym_cache"):
                    self._synonym_cache = {}
                if key not in self._synonym_cache:
                    self._synonym_cache[key] = load_synonyms(candidate, steps)
                return self._synonym_cache[key]
        warnings.append(f"synonyms file {path} was not found; no synonyms were applied")
        return {}

    @staticmethod
    def _pile_items(context, scheme, iid, sorts) -> List[str]:
        item = (context.items or {}).get(iid) or {}
        listed = item.get(scheme.get("items_field", "items"))
        out: List[str] = [str(x) for x in listed] if isinstance(listed, list) else []
        for groups in sorts.values():
            for members in groups.values():
                for x in members:
                    if x not in out:
                        out.append(x)
        return out

    @staticmethod
    def _triad_items(context, scheme, iid, answers) -> List[str]:
        from potato.cultural_domain.triads import domain_items
        if scheme.get("labels"):
            out = domain_items(scheme["labels"])
        else:
            item = (context.items or {}).get(iid) or {}
            out = domain_items(item.get(scheme.get("items_field", "items")) or [])
        for t in answers:
            for x in t[:3]:
                if x not in out:
                    out.append(x)
        return out

    def _consensus(self, context, schemes, wanted, options, warnings, write_rows, output_path, files):
        from potato.cultural_domain.analysis import consensus
        from potato.server_utils.presentation_order import label_names
        answers: Dict[str, Dict[str, str]] = defaultdict(dict)
        opts: Dict[str, List[str]] = {}
        fixed_l = options.get("consensus_choices")
        fixed_l = int(fixed_l) if fixed_l not in (None, "") else None
        for name in wanted:
            scheme = schemes.get(name)
            if scheme is None:
                warnings.append(f"consensus scheme {name} is not in the config")
                continue
            kind = scheme.get("annotation_type")
            if kind not in CATEGORICAL_TYPES:
                warnings.append(f"consensus scheme {name} is a {kind}; only radio, select and likert "
                                "(one answer per question) can be used")
                continue
            if kind == "likert" and not scheme.get("labels"):
                labels = [str(i) for i in range(1, int(scheme.get("size", 5)) + 1)]
            else:
                labels = label_names(scheme)
            for user, iid, _n, entry in self._records(context, [name]):
                value = _categorical(entry, name)
                if value is None:
                    continue
                q = f"{name}:{iid}" if iid else name
                answers[user][q] = value
                if q not in opts:
                    opts[q] = list(labels)
                if value not in opts[q]:
                    opts[q].append(value)
        n_options = {q: max(fixed_l or len(v), len(v), 2) for q, v in opts.items()}
        if not answers:
            warnings.append("no answers to the consensus schemes were found")
            return None
        try:
            min_answers = int(options.get("consensus_min_answers", 2))
            result = consensus(answers, opts, min_answers=min_answers, n_options=n_options)
        except ValueError as e:
            warnings.append(f"consensus analysis skipped: {e}")
            return None
        warnings.extend(result.warnings)
        rows = []
        for inf, d in zip(result.informants, result.competence):
            rows.append({"user_id": inf, "competence": round(float(d), 6),
                         "n_answered": len(answers[inf]), "negative": int(d < 0)})
        write_rows("consensus_informants.csv", ["user_id", "competence", "n_answered", "negative"], rows)
        qrows = []
        for q in result.questions:
            schema, _, iid = q.partition(":")
            qrows.append({"question": q, "schema": schema, "instance_id": iid,
                          "n_options": n_options[q], "n_answers": result.n_answers[q],
                          "answer": result.answer_key[q], "posterior": round(result.posterior[q], 6),
                          "majority_answer": result.majority.get(q, ""),
                          "agrees_with_majority": int(result.majority.get(q, "") == result.answer_key[q])})
        write_rows("consensus_answers.csv", ["question", "schema", "instance_id", "n_options", "n_answers",
                                             "answer", "posterior", "majority_answer",
                                             "agrees_with_majority"], qrows)
        negative = [r["user_id"] for r in rows if r["negative"]]
        ratio = result.ratio
        summary = {
            "model": "cultural consensus (Romney, Weller & Batchelder 1986)",
            "factoring": "iterated principal axis, diagonal estimated",
            "answer_key": "Bayesian weighting (Batchelder & Romney 1988), uniform prior",
            "n_informants": len(result.informants),
            "n_questions": len(result.questions),
            "options_per_question": sorted(set(n_options.values())),
            "eigenvalues": [round(v, 6) for v in result.eigenvalues[:5]],
            "eigenvalue_ratio_1_to_2": round(ratio, 6) if ratio is not None else None,
            "ratio_rule_of_thumb": (
                "A first-to-second eigenvalue ratio above 3 is the usual rule of thumb for "
                "treating the answers as coming from one shared culture. It is a rule of thumb, "
                "not a test."),
            "ratio_above_3": (ratio is not None and ratio > 3),
            "mean_competence": round(float(sum(result.competence) / len(result.competence)), 6),
            "negative_competence": negative,
            "iterations": result.iterations,
            "converged": result.converged,
            "warnings": result.warnings,
        }
        if negative:
            warnings.append(f"{len(negative)} informant(s) have a negative competence: "
                            "they agree with the others less than chance")
        path = os.path.join(output_path, "consensus_summary.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
        files.append(path)
        return summary

"""
Survey Experiments Exporter

Estimates for the sensitive-question designs (potato/server_utils/schemas/
survey_experiments.py). Writes ``survey_experiments.csv``, one row per scheme
(and, for a list experiment, per participant group):

* ``list_experiment``: the difference in mean counts between the treatment
  and control groups (the difference-in-means estimator), with a Welch
  standard error and a 95% normal-approximation interval. Counts outside
  0..len(items) (control) or 0..len(items)+1 (treatment), and answers that
  are not whole numbers, are excluded and counted in ``excluded``. The page
  does not stop them being stored: its input allows 0..len(items)+1 for
  everyone, and a request can bypass the page.
* ``randomized_response``, ``forced_response``: with λ the proportion of
  "Yes", π = (λ − p_yes) / p_truth, SE = sqrt(λ(1 − λ) / n) / p_truth.
* ``randomized_response``, ``crosswise`` (Yu, Tian & Tang 2008): with λ the
  proportion answering "both or neither" and p the non-sensitive statement's
  prevalence, π = (λ + p − 1) / (2p − 1), SE = sqrt(λ(1 − λ) / n) / |2p − 1|.

Estimates are not clipped to [0, 1]: a value outside it says the sample is
too small or the design assumptions do not hold, and clipping would hide that.
"""

from __future__ import annotations

import csv
import math
import os
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult

COLUMNS = ["schema", "design", "estimate", "se", "ci95_low", "ci95_high", "n",
           "n_treatment", "n_control", "mean_treatment", "mean_control", "excluded", "note"]


INVALID = object()      # a list count that is not a number


def phase_page_schemes(context: ExportContext) -> Dict[str, List[dict]]:
    """``{page: [schemes]}`` for the questions on phase pages (surveys,
    prestudy, poststudy), read from the config and its phase files the way
    the server reads them. Empty when they cannot be read here."""
    config = context.config or {}
    if not config.get("phases"):
        return {}
    config_dir = (os.path.dirname(os.path.abspath(config["config_file"]))
                  if config.get("config_file") else config.get("task_dir"))
    try:
        from potato.server_utils.config_module import phase_page_schemes as read
        return read(dict(config), config_dir) or {}
    except Exception:
        return {}


def _conditions_by_user(context: ExportContext) -> Dict[str, Dict[str, Any]]:
    from .experiment_sidecars import _states
    out = {}
    try:
        for user_id, state in _states(context):
            out[str(user_id)] = (state.get("flow_record") or {}).get("conditions") or {}
    except Exception:
        pass
    return out


def _mean_var(xs: List[float]) -> Tuple[float, float]:
    n = len(xs)
    m = sum(xs) / n
    v = sum((x - m) ** 2 for x in xs) / (n - 1) if n > 1 else float("nan")
    return m, v


def _answer(labels: Any, kind: str):
    if not isinstance(labels, dict):
        return None
    if kind == "number":
        for v in labels.values():
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
        return None
    for name, v in labels.items():
        if v not in (None, "", False):
            return str(name)
    return None


def estimate_list(treat: List[float], control: List[float]) -> Dict[str, Any]:
    if len(treat) < 2 or len(control) < 2:
        return {"note": "needs at least two participants in each group"}
    mt, vt = _mean_var(treat)
    mc, vc = _mean_var(control)
    est = mt - mc
    se = math.sqrt(vt / len(treat) + vc / len(control))
    return {"estimate": est, "se": se, "ci95_low": est - 1.96 * se, "ci95_high": est + 1.96 * se,
            "mean_treatment": mt, "mean_control": mc}


def estimate_forced(yes: int, n: int, p_truth: float, p_yes: float) -> Dict[str, Any]:
    lam = yes / n
    est = (lam - p_yes) / p_truth
    se = math.sqrt(lam * (1 - lam) / n) / p_truth
    return {"estimate": est, "se": se, "ci95_low": est - 1.96 * se, "ci95_high": est + 1.96 * se}


def estimate_crosswise(same: int, n: int, p: float) -> Dict[str, Any]:
    lam = same / n
    est = (lam + p - 1) / (2 * p - 1)
    se = math.sqrt(lam * (1 - lam) / n) / abs(2 * p - 1)
    return {"estimate": est, "se": se, "ci95_low": est - 1.96 * se, "ci95_high": est + 1.96 * se}


class SurveyExperimentExporter(BaseExporter):
    format_name = "survey_experiments"
    description = "Estimates for list experiments and randomized-response questions"
    file_extensions = [".csv"]

    def _schemes(self, context):
        """The design schemes in annotation_schemes and on phase pages."""
        kinds = ("list_experiment", "randomized_response")
        found = [s for s in context.schemas or [] if s.get("annotation_type") in kinds]
        names = {s.get("name") for s in found}
        for schemes in phase_page_schemes(context).values():
            for s in schemes:
                if s.get("annotation_type") in kinds and s.get("name") not in names:
                    found.append(s)
                    names.add(s.get("name"))
        return found

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        if not self._schemes(context):
            return False, "No list_experiment or randomized_response scheme in this project"
        return True, ""

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        from potato.server_utils.schemas.survey_experiments import CROSSWISE_LABELS, DEFAULT_P
        os.makedirs(output_path, exist_ok=True)
        conditions = _conditions_by_user(context)
        rows = []
        for scheme in self._schemes(context):
            name, kind = scheme["name"], scheme["annotation_type"]
            # One answer per participant (the latest record wins). A list
            # count that is not a number is kept as INVALID so that it is
            # counted in `excluded`, like a count out of range.
            answers: Dict[str, Any] = {}
            for ann in context.annotations:
                labels = (ann.get("labels") or {}).get(name)
                value = _answer(labels, "number" if kind == "list_experiment" else "choice")
                if value is not None:
                    answers[str(ann.get("user_id"))] = value
                elif kind == "list_experiment" and isinstance(labels, dict) and any(
                        v not in (None, "") for v in labels.values()):
                    answers[str(ann.get("user_id"))] = INVALID
            for resp in context.phase_responses or []:
                if resp.get("schema") == name and resp.get("value") not in (None, ""):
                    v = resp.get("label_name") if kind != "list_experiment" else resp.get("value")
                    try:
                        answers[str(resp.get("user_id"))] = float(v) if kind == "list_experiment" else str(v)
                    except (TypeError, ValueError):
                        if kind == "list_experiment":
                            answers[str(resp.get("user_id"))] = INVALID
            row: Dict[str, Any] = {"schema": name}
            if kind == "list_experiment":
                t = scheme.get("treatment") or {}
                j = len(scheme.get("items") or [])
                treat, control, excluded = [], [], 0
                for uid, count in answers.items():
                    in_treat = str(conditions.get(uid, {}).get(t.get("factor"))) == str(t.get("level"))
                    if (count is INVALID or not math.isfinite(count)
                            or not (0 <= count <= j + (1 if in_treat else 0)) or count != int(count)):
                        excluded += 1
                        continue
                    (treat if in_treat else control).append(count)
                row.update({"design": "list_experiment", "n": len(treat) + len(control),
                            "n_treatment": len(treat), "n_control": len(control),
                            "excluded": excluded})
                row.update(estimate_list(treat, control))
            else:
                method = scheme.get("method", "forced_response")
                n = len(answers)
                row.update({"design": method, "n": n})
                if n == 0:
                    row["note"] = "no answers"
                elif method == "crosswise":
                    same = sum(1 for v in answers.values() if v == CROSSWISE_LABELS[0])
                    row.update(estimate_crosswise(same, n, float(scheme["nonsensitive_prevalence"])))
                else:
                    p_truth = float(scheme.get("p_truth", DEFAULT_P["p_truth"]))
                    p_yes = float(scheme.get("p_yes", DEFAULT_P["p_yes"]))
                    yes = sum(1 for v in answers.values() if v == "Yes")
                    row.update(estimate_forced(yes, n, p_truth, p_yes))
            for k in ("estimate", "se", "ci95_low", "ci95_high", "mean_treatment", "mean_control"):
                if isinstance(row.get(k), float):
                    row[k] = round(row[k], 6)
            rows.append(row)
        path = os.path.join(output_path, "survey_experiments.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow(r)
        return ExportResult(success=True, format_name=self.format_name, files_written=[path],
                            stats={"num_schemes": len(rows)})

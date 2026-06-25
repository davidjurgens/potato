"""
Judge Calibration manager — the singleton orchestrator.

Owns the parsed config, the phase state machine and the LLM result store, and
drives the run lifecycle:

    SETUP -> GENERATING (background thread) -> HUMAN_CALIBRATION -> REPORT -> COMPLETED

Items and annotation schemes are resolved lazily (at ``start_generation``)
because data is loaded after the manager is constructed at app startup.
"""

import logging
import threading
from typing import Any, Dict, List, Optional, Tuple

from potato.judge_calibration.config import (
    JudgeCalibrationConfig,
    parse_judge_calibration_config,
)
from potato.judge_calibration.phase import JCPhase, JCPhaseController
from potato.judge_calibration.storage import ResultStore
from potato.judge_calibration.generation import LLMGenerationThread

logger = logging.getLogger(__name__)

# Generation is schema-type agnostic (aggregation handles each), but we only
# feed it types whose label space extract_labels() understands.
SUPPORTED_GENERATION_TYPES = {"radio", "select", "likert", "multiselect", "span"}


class JudgeCalibrationManager:
    def __init__(self, app_config: Dict[str, Any]):
        self.app_config = app_config or {}
        self.config: JudgeCalibrationConfig = parse_judge_calibration_config(self.app_config)
        self.phase = JCPhaseController(self.config.state_dir)
        self.store = ResultStore(self.config.state_dir)
        self._lock = threading.RLock()
        self._gen_thread: Optional[LLMGenerationThread] = None
        self._progress: Dict[str, Any] = {
            "done_units": 0,
            "total_units": 0,
            "current_model": None,
        }

        # Resume any prior run.
        self.phase.load_state()
        self.store.load()

    # ----- schema / item resolution --------------------------------------

    def get_schema_infos(self) -> List[Dict[str, Any]]:
        """Annotation schemes to evaluate (filtered by config.schemas + type)."""
        schemes = self.app_config.get("annotation_schemes", []) or []
        wanted = set(self.config.schemas)
        out = []
        for s in schemes:
            if not isinstance(s, dict):
                continue
            name = s.get("name")
            atype = s.get("annotation_type")
            if wanted and name not in wanted:
                continue
            if atype not in SUPPORTED_GENERATION_TYPES:
                if wanted and name in wanted:
                    logger.warning(
                        "judge_calibration: schema '%s' has unsupported type '%s'; skipping",
                        name, atype,
                    )
                continue
            out.append(s)
        return out

    def _resolve_cap(self, total: int) -> int:
        if self.config.max_items is not None:
            return min(total, max(1, self.config.max_items))
        if self.config.fraction is not None:
            return max(1, int(round(total * self.config.fraction)))
        return total

    def gather_work_items(self) -> List[Tuple[str, str]]:
        """(instance_id, text) pairs the LLMs will label, honoring the cap."""
        from potato.item_state_management import get_item_state_manager

        ism = get_item_state_manager()
        all_ids = list(ism.instance_id_to_instance.keys())
        cap = self._resolve_cap(len(all_ids))
        selected = all_ids[:cap]

        text_key = (self.app_config.get("item_properties", {}) or {}).get("text_key")
        items: List[Tuple[str, str]] = []
        for iid in selected:
            item = ism.instance_id_to_instance[iid]
            data = item.get_data()
            if isinstance(data, dict) and text_key and text_key in data:
                text = data[text_key]
            else:
                text = item.get_text()
            items.append((iid, str(text)))
        return items

    # ----- lifecycle -----------------------------------------------------

    def update_config(self, overrides: Dict[str, Any]) -> List[str]:
        """Merge wizard overrides into the judge_calibration config + re-parse.

        Returns a list of validation errors (empty if the new config is valid).
        The config is updated regardless so the wizard can show the errors.
        """
        with self._lock:
            jc = dict(self.app_config.get("judge_calibration", {}) or {})
            jc.update(overrides or {})
            jc["enabled"] = True
            self.app_config["judge_calibration"] = jc
            self.config = parse_judge_calibration_config(self.app_config)
            return self.config.validate()

    def is_generating(self) -> bool:
        with self._lock:
            return self._gen_thread is not None and self._gen_thread.is_alive()

    def start_generation(self, force_restart: bool = False) -> bool:
        """Kick off (or resume) background LLM generation. Returns True if started."""
        with self._lock:
            if self.is_generating():
                return False
            if not self.config.models:
                raise ValueError("judge_calibration: no models configured")

            schema_infos = self.get_schema_infos()
            if not schema_infos:
                raise ValueError("judge_calibration: no supported schemas to evaluate")
            work_items = self.gather_work_items()
            if not work_items:
                raise ValueError("judge_calibration: no items to label")

            if force_restart:
                self.store.clear()
                self.phase.reset()

            if self.phase.get_current_phase() != JCPhase.GENERATING:
                # SETUP -> GENERATING (force covers re-runs from later phases).
                self.phase.transition_to(JCPhase.GENERATING, reason="start", force=True)

            # Record run metadata for the report.
            self.phase.set_phase_data("n_models", len(self.config.models))
            self.phase.set_phase_data("n_schemas", len(schema_infos))
            self.phase.set_phase_data("n_items", len(work_items))

            self._progress = {
                "done_units": 0,
                "total_units": len(work_items) * len(schema_infos) * len(self.config.models),
                "current_model": None,
            }

            self._gen_thread = LLMGenerationThread(
                config=self.config,
                work_items=work_items,
                schema_infos=schema_infos,
                result_store=self.store,
                on_progress=self._on_progress,
                on_complete=self._on_generation_complete,
            )
            self._gen_thread.start()
            logger.info("judge_calibration: generation started (%d units)",
                        self._progress["total_units"])
            return True

    def _on_progress(self, progress: Dict[str, Any]) -> None:
        with self._lock:
            self._progress.update(progress)

    def _on_generation_complete(self) -> None:
        try:
            self.phase.transition_to(JCPhase.HUMAN_CALIBRATION, reason="generation complete")
            # Draw the human calibration subset now that all items are labeled.
            self.select_calibration_sample()
        except Exception as e:
            logger.error("judge_calibration: failed to advance phase: %s", e)

    # ----- calibration sample + report -----------------------------------

    def _stratum_fn(self):
        """Build a stratum mapping for stratified sampling, or None.

        If ``sampling.stratify_by`` names an item-data field, stratify on that.
        Otherwise stratify on the first model's modal label (stratify-by-label)
        for the first evaluated schema.
        """
        if self.config.sampling.strategy != "stratified":
            return None

        field = self.config.sampling.stratify_by
        if field:
            from potato.item_state_management import get_item_state_manager
            ism = get_item_state_manager()

            def by_field(iid):
                item = ism.instance_id_to_instance.get(iid)
                data = item.get_data() if item else None
                return data.get(field) if isinstance(data, dict) else None
            return by_field

        # stratify-by-label: use the first model + first schema modal label
        schema_infos = self.get_schema_infos()
        if not schema_infos or not self.config.models:
            return None
        first_schema = schema_infos[0].get("name")
        first_model = self.config.models[0].model

        def by_label(iid):
            r = self.store.get(first_model, iid, first_schema)
            return r.modal_label if r else None
        return by_label

    def select_calibration_sample(self) -> List[str]:
        """Pick (and persist) the human calibration subset from labeled items."""
        from potato.judge_calibration.sampler import select_calibration_sample as _select

        labeled = self.store.labeled_instance_ids()
        sample = _select(labeled, self.config.sampling, stratum_of=self._stratum_fn())
        self.phase.set_phase_data("calibration_sample", sample)
        logger.info("judge_calibration: calibration sample = %d items", len(sample))
        return sample

    def get_calibration_sample(self) -> List[str]:
        return self.phase.get_phase_data("calibration_sample", []) or []

    def build_report(self) -> Dict[str, Any]:
        """Compute metrics and write report files. Advances phase to COMPLETED."""
        from potato.judge_calibration import report as report_module
        from potato.judge_calibration.phase import JCPhase

        with self._lock:
            if self.phase.get_current_phase() not in (JCPhase.REPORT, JCPhase.COMPLETED):
                self.phase.transition_to(JCPhase.REPORT, reason="build report", force=True)
        result = report_module.build_report(self)
        with self._lock:
            if self.phase.get_current_phase() != JCPhase.COMPLETED:
                self.phase.transition_to(JCPhase.COMPLETED, reason="report complete")
        return result

    def get_progress(self) -> Dict[str, Any]:
        with self._lock:
            error = self._gen_thread.error if self._gen_thread else None
            return {
                "phase": self.phase.get_current_phase().to_str(),
                "generating": self.is_generating(),
                "results": self.store.count(),
                "error": error,
                **self._progress,
            }

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "enabled": self.config.enabled,
                "phase": self.phase.get_current_phase().to_str(),
                "progress": self.get_progress(),
                "n_models": len(self.config.models),
                "models": [m.model for m in self.config.models],
            }


# ----- singleton ----------------------------------------------------------

_manager: Optional[JudgeCalibrationManager] = None
_manager_lock = threading.Lock()


def init_judge_calibration_manager(app_config: Dict[str, Any]) -> JudgeCalibrationManager:
    global _manager
    with _manager_lock:
        _manager = JudgeCalibrationManager(app_config)
        logger.info("Judge Calibration manager initialized")
        return _manager


def get_judge_calibration_manager() -> Optional[JudgeCalibrationManager]:
    return _manager


def clear_judge_calibration_manager() -> None:
    global _manager
    with _manager_lock:
        _manager = None

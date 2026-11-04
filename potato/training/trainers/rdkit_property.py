"""Molecular property models from questions asked about molecules.

For a radio, select, likert or slider question over items that show a
molecule (a ``molecule`` display field) or ask annotators to draw one (a
``chemical_structure`` scheme on the same item). The bundle writes each
item's structure into its row as SMILES or a molfile; this trainer turns it
into features and fits a scikit-learn model on the question's answers.

Features are a Morgan fingerprint (radius 2, 2048 bits by default, the
ECFP4 most property papers start from) and RDKit's 2D descriptors (weight,
logP, TPSA, ring and atom counts and the rest of ``Descriptors``), scaled.
Logistic regression or a random forest for a choice or a Likert answer;
ridge or a random forest for a slider, whose prediction is rounded to the
slider's step and clamped to its range. A structure RDKit cannot parse is
left out of training and predicted on by nothing, and both are counted.

Needs rdkit (the ``chemistry`` extra); scikit-learn and numpy are core.
"""

from __future__ import annotations

import math
import os
import pickle
from typing import Any, ClassVar, Dict, Iterable, Iterator, List, Optional, Tuple

from potato.training.base import (BundleRef, FitResult, PredictItem,
                                  PredictionRecord, ProgressReporter, Trainer,
                                  TrainerError, TrainingSpec)
from potato.training.trainers import _hf_common as hf

INSTALL_HINT = "pip install 'potato-annotation[chemistry]'"
_NEEDS = ("rdkit", "sklearn", "numpy")
MODEL_FILE = "model.pkl"

#: Models per kind; the first is the default.
MODELS = {"nominal": ("logistic", "random_forest"),
          "ordinal": ("logistic", "random_forest"),
          "continuous": ("ridge", "random_forest")}


def parse(text: Any):
    """An RDKit molecule from SMILES or a molfile, or None."""
    if not isinstance(text, str) or not text.strip():
        return None
    from rdkit import Chem, RDLogger
    RDLogger.DisableLog("rdApp.*")
    from potato.chemistry.structures import looks_like_molfile
    mol = Chem.MolFromMolBlock(text) if looks_like_molfile(text) else \
        Chem.MolFromSmiles(text.strip())
    return mol


def descriptor_names() -> List[str]:
    from rdkit.Chem import Descriptors
    return [name for name, _fn in Descriptors._descList]


def featurize(mol, radius: int, bits: int, descriptors: List[str]):
    """One molecule's feature vector: fingerprint bits, then descriptors
    (non-finite values, which a few descriptors give on odd structures,
    become 0)."""
    import numpy
    from rdkit import DataStructs
    from rdkit.Chem import Descriptors, rdFingerprintGenerator
    generator = rdFingerprintGenerator.GetMorganGenerator(radius=radius, fpSize=bits)
    fingerprint = numpy.zeros((bits,), dtype="float64")
    DataStructs.ConvertToNumpyArray(generator.GetFingerprint(mol), fingerprint)
    functions = dict(Descriptors._descList)
    values = []
    for name in descriptors:
        try:
            value = float(functions[name](mol))
        except Exception:  # noqa: BLE001 - a descriptor that fails is a 0
            value = 0.0
        values.append(value if math.isfinite(value) and abs(value) < 1e12 else 0.0)
    return numpy.concatenate([fingerprint, numpy.asarray(values, dtype="float64")])


def scale_of(scheme: Dict[str, Any]) -> Dict[str, float]:
    """A slider's range and step, for rounding a regression's answer. The
    step is the slider's own default, 1, when the scheme sets none."""
    out = {"step": 1.0}
    for key, name in (("min", "min_value"), ("max", "max_value"), ("step", "step")):
        try:
            out[key] = float(scheme[name])
        except (KeyError, TypeError, ValueError):
            continue
    return out


def snap(value: float, scale: Dict[str, float]) -> float:
    """*value* on the slider: a multiple of the step from the minimum, and
    inside the range. A maximum off the grid (0 to 12 in steps of 5) is not
    a position the slider has, so the top is the last step under it."""
    low, high = scale.get("min"), scale.get("max")
    step = scale.get("step")
    origin = low or 0.0
    if step and step > 0:
        value = origin + round((value - origin) / step) * step
        if high is not None:
            high = origin + math.floor((high - origin) / step + 1e-9) * step
    if low is not None:
        value = max(low, value)
    if high is not None:
        value = min(high, value)
    return round(value, 6)


def slider_label(value: float) -> str:
    """A slider position as the page stores it: "7", not 7.0."""
    return str(int(value)) if float(value).is_integer() else repr(float(value))


class RDKitPropertyTrainer(Trainer):
    name: ClassVar[str] = "rdkit-property"
    description: ClassVar[str] = (
        "Molecular property models: Morgan fingerprints and RDKit descriptors "
        "with a scikit-learn classifier or regressor, for questions about the "
        "molecule an item shows or an annotator drew.")
    kinds: ClassVar[Tuple[str, ...]] = ("nominal", "ordinal", "continuous")
    modalities: ClassVar[Tuple[str, ...]] = ("molecule",)
    install_hint: ClassVar[str] = INSTALL_HINT
    licence: ClassVar[str] = "BSD-3-Clause"
    commercial_use: ClassVar[Optional[bool]] = True

    @classmethod
    def available(cls) -> Tuple[bool, str]:
        return hf.availability(_NEEDS)

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {"model": None, "radius": 2, "bits": 2048, "descriptors": True,
                "C": 1.0, "alpha": 1.0, "n_estimators": 300, "class_weight": None,
                "min_instances": 10}

    @classmethod
    def params_schema(cls) -> Dict[str, Any]:
        return {"type": "object", "additionalProperties": False, "properties": {
            "model": {"type": ["string", "null"], "default": None,
                      "enum": [None, "logistic", "random_forest", "ridge"],
                      "description": "logistic or random_forest for a choice or "
                                     "Likert question, ridge or random_forest for "
                                     "a slider. null picks the first."},
            "radius": {"type": "integer", "minimum": 1, "maximum": 4, "default": 2,
                       "description": "Morgan fingerprint radius (2 is ECFP4)."},
            "bits": {"type": "integer", "minimum": 64, "default": 2048,
                     "description": "Fingerprint length."},
            "descriptors": {"type": "boolean", "default": True,
                            "description": "Add RDKit's 2D descriptors to the "
                                           "fingerprint."},
            "C": {"type": "number", "exclusiveMinimum": 0, "default": 1.0,
                  "description": "Inverse regularization of logistic regression."},
            "alpha": {"type": "number", "exclusiveMinimum": 0, "default": 1.0,
                      "description": "Ridge regularization."},
            "n_estimators": {"type": "integer", "minimum": 10, "default": 300,
                             "description": "Trees in a random forest."},
            "class_weight": {"type": ["string", "null"], "enum": [None, "balanced"],
                             "default": None,
                             "description": "balanced weights rare answers up."},
            "min_instances": {"type": "integer", "minimum": 2, "default": 10,
                              "description": "Labelled molecules needed in the "
                                             "train split."},
        }}

    @classmethod
    def server_params(cls, config, schema_names, params) -> Dict[str, Any]:
        for scheme in (config or {}).get("annotation_schemes") or []:
            if isinstance(scheme, dict) and schema_names and \
                    scheme.get("name") == schema_names[0] and \
                    scheme.get("annotation_type") == "slider":
                return {"_scale": scale_of(scheme)}
        return {}

    def _params(self, spec: TrainingSpec) -> Dict[str, Any]:
        return hf.merged_params(self.default_params(), spec)

    def validate(self, spec: TrainingSpec, bundle: BundleRef) -> List[str]:
        params = self._params(spec)
        schema = spec.primary_schema
        if schema is None:
            return ["No schema was selected for training."]
        problems = []
        if schema.kind not in self.kinds:
            problems.append("Schema %r is %s; this trainer answers choice, Likert "
                            "and slider questions." % (schema.name, schema.kind))
            return problems
        if params.get("model") and params["model"] not in MODELS[schema.kind]:
            problems.append("model %r does not fit a %s answer; use %s"
                            % (params["model"], schema.kind,
                               " or ".join(MODELS[schema.kind])))
        rows = hf.rows_with_target(bundle.read_split("train"), schema.name)
        with_structure = [r for r in rows if r.get("molecule")]
        if rows and not with_structure:
            problems.append("No train item has a structure. Show it with a "
                            "molecule display field, or draw it in a "
                            "chemical_structure scheme.")
        elif len(with_structure) < int(params["min_instances"]):
            problems.append("Only %d labelled molecules in the train split; this "
                            "trainer needs at least %d."
                            % (len(with_structure), int(params["min_instances"])))
        if schema.kind != "continuous" and len(bundle.labels(schema.name)) < 2:
            problems.append("Schema %r has fewer than two answers in the data."
                            % schema.name)
        return problems

    # ------------------------------------------------------------ data

    def _matrix(self, rows: Iterable[Dict[str, Any]], radius: int, bits: int,
                descriptors: List[str]):
        """``(features, kept rows, unparseable count)``. A row with no
        structure is skipped and not counted: the bundle already warned."""
        import numpy
        features, kept, bad = [], [], 0
        for row in rows:
            if not row.get("molecule"):
                continue    # no structure at all; the bundle warned
            mol = parse(row.get("molecule"))
            if mol is None:
                bad += 1
                continue
            features.append(featurize(mol, radius, bits, descriptors))
            kept.append(row)
        matrix = numpy.vstack(features) if features else numpy.zeros((0, bits))
        return matrix, kept, bad

    def _estimator(self, kind: str, params: Dict[str, Any], seed: int):
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        model = params.get("model") or MODELS[kind][0]
        if model == "random_forest":
            from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
            cls = RandomForestRegressor if kind == "continuous" else RandomForestClassifier
            kwargs = {"n_estimators": int(params["n_estimators"]), "random_state": seed,
                      "n_jobs": -1}
            if kind != "continuous" and params.get("class_weight"):
                kwargs["class_weight"] = params["class_weight"]
            return model, cls(**kwargs)
        if model == "ridge":
            from sklearn.linear_model import Ridge
            return model, make_pipeline(StandardScaler(), Ridge(alpha=float(params["alpha"])))
        from sklearn.linear_model import LogisticRegression
        return model, make_pipeline(StandardScaler(), LogisticRegression(
            C=float(params["C"]), max_iter=2000, class_weight=params.get("class_weight")))

    @staticmethod
    def _target(kind: str, value: Any):
        if kind == "continuous":
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
        return str(value)

    # ------------------------------------------------------------ fit

    def fit(self, spec: TrainingSpec, bundle: BundleRef,
            report: ProgressReporter) -> FitResult:
        hf.require(_NEEDS, INSTALL_HINT)
        params = self._params(spec)
        schema = spec.primary_schema
        radius, bits = int(params["radius"]), int(params["bits"])
        names = descriptor_names() if params.get("descriptors", True) else []
        rows = [r for r in hf.rows_with_target(bundle.read_split("train"), schema.name)
                if self._target(schema.kind, r["targets"][schema.name]) is not None]
        report.status("running", "featurizing")
        features, kept, bad = self._matrix(rows, radius, bits, names)
        if bad:
            report.log("warning", "%d train structure(s) RDKit could not parse; "
                       "left out" % bad)
        if not kept:
            raise TrainerError("No train structure could be parsed for %r" % schema.name)
        targets = [self._target(schema.kind, r["targets"][schema.name]) for r in kept]
        model_name, estimator = self._estimator(schema.kind, params, spec.seed)
        report.log("info", "%d molecules, %d features (%d-bit radius-%d fingerprint%s); %s"
                   % (len(kept), features.shape[1], bits, radius,
                      " and %d descriptors" % len(names) if names else "", model_name))
        report.status("running", "fitting")
        estimator.fit(features, targets)
        os.makedirs(spec.workdir, exist_ok=True)
        with open(os.path.join(spec.workdir, MODEL_FILE), "wb") as fh:
            pickle.dump(estimator, fh)
        classes = [str(c) for c in getattr(estimator, "classes_", [])]
        version = "%s-%s-%s" % (self.name, schema.name, spec.run_id)
        hf.write_card(spec.workdir, {
            "trainer": self.name, "schema": schema.name, "kind": schema.kind,
            "model": model_name, "radius": radius, "bits": bits, "descriptors": names,
            "label_order": classes, "scale": params.get("_scale") or {},
            "model_version": version, "n_train": len(kept), "n_unparseable": bad,
            "bundle_digest": bundle.digest})
        metrics = {"n_train": float(len(kept)), "n_unparseable": float(bad)}
        return FitResult(model_version=version,
                         artifact_paths=[MODEL_FILE, hf.CARD_FILE],
                         metrics=metrics, label_order=classes)

    # ------------------------------------------------------------ predict

    def predict(self, spec: TrainingSpec, artifact_dir: str,
                items: Iterable[PredictItem],
                report: ProgressReporter) -> Iterator[PredictionRecord]:
        hf.require(_NEEDS, INSTALL_HINT)
        card = hf.read_card(artifact_dir)
        with open(os.path.join(artifact_dir, MODEL_FILE), "rb") as fh:
            estimator = pickle.load(fh)
        schema = spec.primary_schema
        items = list(items)
        unparseable = 0
        for start in range(0, len(items), 256):
            chunk = items[start:start + 256]
            rows = [dict(item.data, instance_id=item.instance_id) for item in chunk]
            features, kept, bad = self._matrix(rows, int(card["radius"]),
                                               int(card["bits"]), list(card["descriptors"]))
            unparseable += bad
            if not kept:
                continue
            if card["kind"] == "continuous":
                values = estimator.predict(features)
                for row, value in zip(kept, values):
                    value = snap(float(value), card.get("scale") or {})
                    yield PredictionRecord(instance_id=row["instance_id"],
                                           schema_name=schema.name,
                                           payload={"label": slider_label(value),
                                                    "confidence": None})
            else:
                probabilities = estimator.predict_proba(features)
                classes = [str(c) for c in estimator.classes_]
                for row, probs in zip(kept, probabilities):
                    best = int(max(range(len(probs)), key=lambda i: probs[i]))
                    confidence = round(float(probs[best]), 4)
                    yield PredictionRecord(instance_id=row["instance_id"],
                                           schema_name=schema.name,
                                           payload={"label": classes[best],
                                                    "confidence": confidence},
                                           confidence=confidence)
            report.progress("predict", min(start + 256, len(items)), len(items))
            if report.should_stop():
                return
        if unparseable:
            report.log("warning", "%d item(s) had no structure RDKit could parse; "
                       "nothing was predicted for them" % unparseable)

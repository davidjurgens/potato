"""Classical classifiers over text or image embeddings.

The reference implementation of :class:`~potato.training.base.Trainer`, and the
one that needs no optional dependency: scikit-learn, scipy and numpy are core.
A project can train something the day it installs Potato.

The estimator and vectorizer are named by dotted path and imported
dynamically, which is carried over from ``ActiveLearningManager`` unchanged.
It means any scikit-learn-API estimator works from YAML without a code change,
and it means every config that already names one keeps working.

Two vectorizers reach past bag-of-words, both lazily: ``sentence-transformers``
for dense text embeddings, and ``clip`` for images by way of
``potato.vision_features``. The image path is why this trainer declares the
``image`` modality -- the query strategies and the classifier never needed to
know the difference, only the feature extractor did.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import pickle
import time
from typing import Any, ClassVar, Dict, Iterable, Iterator, List, Optional, Tuple

from potato.training.base import (BundleRef, FitResult, MissingDependency,
                                  PredictItem, PredictionRecord,
                                  ProgressReporter, Trainer, TrainerError,
                                  TrainingSpec)

logger = logging.getLogger(__name__)

_DEFAULT_CLASSIFIER = "sklearn.linear_model.LogisticRegression"
_DEFAULT_VECTORIZER = "sklearn.feature_extraction.text.TfidfVectorizer"

#: Model file inside the artifact directory.
MODEL_FILE = "model.pkl"
META_FILE = "model_card.json"


class SklearnTextTrainer(Trainer):
    """Fit a scikit-learn pipeline on resolved annotations."""

    name: ClassVar[str] = "sklearn-text"
    description: ClassVar[str] = (
        "Linear and tree classifiers over bag-of-words, sentence embeddings "
        "or CLIP image embeddings. Needs no optional dependency.")
    kinds: ClassVar[Tuple[str, ...]] = ("nominal", "ordinal", "multilabel")
    modalities: ClassVar[Tuple[str, ...]] = ("text", "image")
    install_hint: ClassVar[str] = ""
    licence: ClassVar[str] = "BSD-3-Clause"
    commercial_use: ClassVar[Optional[bool]] = True

    # ------------------------------------------------------------ capability

    @classmethod
    def available(cls) -> Tuple[bool, str]:
        # find_spec, not an import: this runs in the parent process on every
        # render of the training page.
        import importlib.util
        if importlib.util.find_spec("sklearn") is None:
            return False, "scikit-learn is not installed"
        return True, ""

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {
            "classifier": _DEFAULT_CLASSIFIER,
            "classifier_kwargs": {},
            "vectorizer": _DEFAULT_VECTORIZER,
            "vectorizer_kwargs": {},
            "calibrate": True,
            "min_instances": 10,
        }

    @classmethod
    def params_schema(cls) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "classifier": {
                    "type": "string", "default": _DEFAULT_CLASSIFIER,
                    "description": "Dotted path to any scikit-learn-API "
                                   "estimator.",
                },
                "classifier_kwargs": {
                    "type": "object", "default": {},
                    "description": "Passed to the estimator's constructor.",
                },
                "vectorizer": {
                    "type": "string", "default": _DEFAULT_VECTORIZER,
                    "description": "Dotted path, or 'sentence-transformers', "
                                   "or 'clip' for images.",
                },
                "vectorizer_kwargs": {"type": "object", "default": {}},
                "calibrate": {
                    "type": "boolean", "default": True,
                    "description": "Fit isotonic calibration so confidences "
                                   "mean something. Needs enough data to "
                                   "cross-validate; skipped automatically "
                                   "when there is not.",
                },
                "min_instances": {
                    "type": "integer", "default": 10, "minimum": 2,
                    "description": "Refuse to fit below this many labelled "
                                   "items.",
                },
            },
            "additionalProperties": False,
        }

    # ------------------------------------------------------------ validation

    def validate(self, spec: TrainingSpec, bundle: BundleRef) -> List[str]:
        problems = []
        params = {**self.default_params(), **(spec.params or {})}

        n_train = bundle.split_size("train")
        minimum = int(params.get("min_instances", 10))
        if n_train < minimum:
            problems.append(
                "Only %d items in the train split; this trainer needs at "
                "least %d. Annotate more, or lower min_instances."
                % (n_train, minimum))

        if not spec.schemas:
            problems.append("No schema was selected for training.")

        for schema in spec.schemas:
            if schema.kind not in self.kinds:
                problems.append(
                    "Schema %r is %s, which this trainer cannot fit. It "
                    "handles: %s." % (schema.name, schema.kind,
                                      ", ".join(self.kinds)))
            labels = bundle.labels(schema.name)
            if schema.kind == "nominal" and len(labels) < 2:
                problems.append(
                    "Schema %r has %d distinct label(s) in the data. A "
                    "classifier needs at least two to have anything to "
                    "separate." % (schema.name, len(labels)))

        return problems

    # ------------------------------------------------------------------ fit

    def fit(self, spec: TrainingSpec, bundle: BundleRef,
            report: ProgressReporter) -> FitResult:
        params = {**self.default_params(), **(spec.params or {})}
        schema = spec.primary_schema
        if schema is None:
            raise TrainerError("No schema to train on")

        report.status("running", "reading bundle")
        features, targets, _ = self._read_split(spec, bundle, schema, "train",
                                                report)
        if not features:
            raise TrainerError(
                "The train split produced no usable rows for schema %r"
                % schema.name)

        report.status("running", "building pipeline")
        pipeline = self._build_pipeline(params, schema, report)

        if report.should_stop():
            raise TrainerError("Cancelled before fitting")

        report.status("running", "fitting")
        report.progress("fit", 0, 1)
        started = time.time()
        pipeline.fit(features, targets)
        elapsed = time.time() - started
        report.progress("fit", 1, 1)

        pipeline = self._maybe_calibrate(pipeline, features, targets, params,
                                         report)

        os.makedirs(spec.workdir, exist_ok=True)
        model_path = os.path.join(spec.workdir, MODEL_FILE)
        with open(model_path, "wb") as fh:
            pickle.dump(pipeline, fh)

        label_order = [str(c) for c in getattr(pipeline, "classes_", [])]
        if not label_order:
            label_order = bundle.labels(schema.name)

        metrics = {"train_seconds": round(elapsed, 3),
                   "n_train": float(len(features))}
        try:
            from sklearn.metrics import accuracy_score
            metrics["train_accuracy"] = float(
                accuracy_score(targets, pipeline.predict(features)))
        except Exception:
            logger.debug("Could not score the training set", exc_info=True)

        report.metric("train", "accuracy", metrics.get("train_accuracy", 0.0))

        card = {
            "trainer": self.name, "schema": schema.name,
            "kind": schema.kind, "classifier": params.get("classifier"),
            "vectorizer": params.get("vectorizer"),
            "calibration": getattr(self, "_calibration", {}),
            "label_order": label_order, "n_train": len(features),
            "bundle_digest": bundle.digest,
            # Recorded so a reloaded model can be refused if it predates a
            # label vocabulary change. Column order is what a classifier's
            # output means.
            "labels_at_fit": bundle.labels(schema.name),
        }
        with open(os.path.join(spec.workdir, META_FILE), "w") as fh:
            json.dump(card, fh, indent=2)

        return FitResult(
            model_version="%s-%s-%s" % (self.name, schema.name, spec.run_id),
            artifact_paths=[MODEL_FILE, META_FILE],
            metrics=metrics, label_order=label_order)

    # -------------------------------------------------------------- predict

    def predict(self, spec: TrainingSpec, artifact_dir: str,
                items: Iterable[PredictItem],
                report: ProgressReporter) -> Iterator[PredictionRecord]:
        schema = spec.primary_schema
        if schema is None:
            return

        model_path = os.path.join(artifact_dir, MODEL_FILE)
        if not os.path.isfile(model_path):
            raise TrainerError("No fitted model at %s" % model_path)
        with open(model_path, "rb") as fh:
            pipeline = pickle.load(fh)

        batch: List[PredictItem] = []
        seen = 0

        def flush(chunk):
            if not chunk:
                return []
            features = [self._feature_of(item, schema) for item in chunk]
            try:
                probabilities = pipeline.predict_proba(features)
                classes = [str(c) for c in pipeline.classes_]
            except Exception:
                # Not every estimator gives probabilities; a bare prediction
                # with no confidence is still usable, it just cannot be
                # ordered by uncertainty.
                predictions = pipeline.predict(features)
                return [PredictionRecord(
                    instance_id=item.instance_id, schema_name=schema.name,
                    payload={"label": str(pred), "confidence": None},
                    confidence=None)
                    for item, pred in zip(chunk, predictions)]

            out = []
            for item, row in zip(chunk, probabilities):
                best = int(max(range(len(row)), key=lambda i: row[i]))
                confidence = float(row[best])
                out.append(PredictionRecord(
                    instance_id=item.instance_id, schema_name=schema.name,
                    payload={"label": classes[best], "confidence": confidence},
                    confidence=confidence))
            return out

        for item in items:
            batch.append(item)
            if len(batch) >= 256:
                for record in flush(batch):
                    yield record
                seen += len(batch)
                report.progress("predict", seen, 0)
                batch = []
                if report.should_stop():
                    return

        for record in flush(batch):
            yield record

    # --------------------------------------------------------------- helpers

    def _read_split(self, spec: TrainingSpec, bundle: BundleRef, schema,
                    split: str, report: ProgressReporter
                    ) -> Tuple[List[str], List[Any], List[str]]:
        """``(features, targets, instance_ids)`` for one split."""
        features, targets, ids = [], [], []
        for row in bundle.read_split(split):
            target = (row.get("targets") or {}).get(schema.name)
            if target is None or target == [] or target == "":
                continue
            features.append(self._feature_of(
                PredictItem(instance_id=row.get("instance_id", ""),
                            text=row.get("text", ""),
                            media=row.get("media")), schema,
                bundle=bundle))
            targets.append(target)
            ids.append(row.get("instance_id", ""))

        if schema.kind == "multilabel":
            # A list target per row; join into a canonical string so a plain
            # classifier can treat the combination as a class. Crude, and
            # honest about it: real multilabel wants a different head, which
            # is what the transformers trainer is for.
            targets = ["|".join(sorted(str(t) for t in target))
                       if isinstance(target, list) else str(target)
                       for target in targets]
        elif schema.kind == "ordinal":
            targets = [str(t) for t in targets]

        report.log("info", "Read %d labelled rows from the %s split"
                   % (len(features), split))
        return features, targets, ids

    def _feature_of(self, item: PredictItem, schema,
                    bundle: Optional[BundleRef] = None) -> str:
        """What the vectorizer sees: the text, or a media path.

        For an image schema this is a file path, and the CLIP vectorizer opens
        it. Handing an image trainer the item's text is the failure that made
        image active learning sort by filename.
        """
        if item.media:
            if bundle is not None:
                return bundle.resolve_media(item.media)
            return item.media
        return item.text or ""

    def _build_pipeline(self, params: Dict[str, Any], schema,
                        report: ProgressReporter):
        from sklearn.pipeline import Pipeline

        vectorizer = self._make_vectorizer(params, report)
        classifier = self._make_classifier(params, report)
        return Pipeline([("vectorizer", vectorizer),
                         ("classifier", classifier)])

    def _make_vectorizer(self, params: Dict[str, Any],
                         report: ProgressReporter):
        name = params.get("vectorizer") or _DEFAULT_VECTORIZER
        kwargs = dict(params.get("vectorizer_kwargs") or {})

        # YAML gives a list; sklearn wants a tuple.
        if isinstance(kwargs.get("ngram_range"), list):
            kwargs["ngram_range"] = tuple(kwargs["ngram_range"])

        if name == "sentence-transformers":
            from potato.active_learning_manager import \
                SentenceTransformerVectorizer
            return SentenceTransformerVectorizer(
                model_name=kwargs.pop("model_name", "all-MiniLM-L6-v2"))

        if name in ("clip", "image"):
            try:
                from potato.vision_features import (DEFAULT_IMAGE_MODEL,
                                                    ImageEmbeddingVectorizer)
            except ImportError as exc:
                raise MissingDependency(
                    "Image embeddings need sentence-transformers and pillow: "
                    "%s" % exc,
                    install_hint='pip install "potato-annotation[embeddings]"'
                ) from exc
            return ImageEmbeddingVectorizer(
                model_name=kwargs.pop("model_name", DEFAULT_IMAGE_MODEL),
                cache_dir=kwargs.pop("cache_dir", None),
                image_root=kwargs.pop("image_root", None))

        return self._by_dotted_path(name, kwargs, _DEFAULT_VECTORIZER, report,
                                    "vectorizer")

    def _make_classifier(self, params: Dict[str, Any],
                         report: ProgressReporter):
        name = params.get("classifier") or _DEFAULT_CLASSIFIER
        kwargs = dict(params.get("classifier_kwargs") or {})
        if name.endswith(".SVC"):
            # Without this an SVC has no predict_proba, and everything
            # downstream -- uncertainty ranking, the confidence floor, the
            # review queue -- is built on confidences.
            kwargs.setdefault("probability", True)
        return self._by_dotted_path(name, kwargs, _DEFAULT_CLASSIFIER, report,
                                    "classifier")

    def _by_dotted_path(self, name: str, kwargs: Dict[str, Any],
                        fallback: str, report: ProgressReporter, what: str):
        try:
            module_path, class_name = name.rsplit(".", 1)
            module = importlib.import_module(module_path)
            return getattr(module, class_name)(**kwargs)
        except Exception as exc:
            # Falling back rather than failing matches the previous behaviour,
            # but say so loudly: a silent fallback to TfidfVectorizer is how a
            # project ends up wondering why its configured model changed
            # nothing.
            report.log("warning",
                       "Could not build %s %r (%s); falling back to %s"
                       % (what, name, exc, fallback))
            module_path, class_name = fallback.rsplit(".", 1)
            module = importlib.import_module(module_path)
            return getattr(module, class_name)()

    def _maybe_calibrate(self, pipeline, features, targets,
                         params: Dict[str, Any], report: ProgressReporter):
        """Calibrate, and keep the result only if it helped.

        See :mod:`potato.training.calibration` for why the check exists: on a
        small training set, calibration reliably makes the model worse and
        gives no sign of having done so.
        """
        from potato.training.calibration import calibrate_if_it_helps

        report.status("running", "calibrating")
        outcome = calibrate_if_it_helps(
            pipeline, features, targets,
            enabled=bool(params.get("calibrate", True)),
            log=report.log)
        self._calibration = outcome.to_dict()
        return outcome.model

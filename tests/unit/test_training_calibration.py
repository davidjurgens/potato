"""Probability calibration, and the collapse it used to cause silently.

The bug this guards was live and shipped: `calibrate_probabilities` defaults to
True, active learning trains from 10 annotations, and isotonic calibration over
3 folds of that many samples makes every prediction come back with an identical
probability. Nothing raises. The model loads, predicts, and reports confidences
-- they are just all the same number, so uncertainty sampling ranks every item
equally and the whole point of active learning quietly stops working.
"""

import pytest

from potato.training.calibration import (MAX_ACCURACY_LOSS,
                                         MIN_SAMPLES_FOR_CALIBRATION,
                                         MIN_SAMPLES_FOR_ISOTONIC,
                                         calibrate_if_it_helps)

POS = ["great movie", "loved it", "wonderful film", "excellent work",
       "so good", "a delight", "beautifully done", "really enjoyed"]
NEG = ["terrible movie", "hated it", "awful film", "poor work", "so bad",
       "a chore", "badly done", "really disliked"]


def _fitted(features, targets):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline

    pipeline = Pipeline([("v", TfidfVectorizer()), ("c", LogisticRegression())])
    pipeline.fit(features, targets)
    return pipeline


def _small():
    features = POS + NEG
    targets = ["positive"] * len(POS) + ["negative"] * len(NEG)
    return features, targets


def _large(n=60):
    features, targets = [], []
    for i in range(n):
        features.append("%s number %d" % (POS[i % len(POS)], i))
        targets.append("positive")
        features.append("%s number %d" % (NEG[i % len(NEG)], i))
        targets.append("negative")
    return features, targets


class TestSmallSampleIsRefused:
    def test_a_small_training_set_is_not_calibrated(self):
        features, targets = _small()
        outcome = calibrate_if_it_helps(_fitted(features, targets),
                                        features, targets)
        assert outcome.applied is False
        assert "at least %d" % MIN_SAMPLES_FOR_CALIBRATION in outcome.reason

    def test_the_uncalibrated_model_is_returned_intact(self):
        features, targets = _small()
        pipeline = _fitted(features, targets)
        outcome = calibrate_if_it_helps(pipeline, features, targets)
        assert outcome.model is pipeline

    def test_the_model_still_separates_after_the_refusal(self):
        """The regression itself: this used to come back at 0.5 everywhere."""
        from sklearn.metrics import accuracy_score

        features, targets = _small()
        outcome = calibrate_if_it_helps(_fitted(features, targets),
                                        features, targets)
        predictions = outcome.model.predict(features)
        assert accuracy_score(targets, predictions) > 0.9

    def test_confidences_vary_across_inputs(self):
        """A constant confidence makes every ranking arbitrary."""
        features, targets = _small()
        outcome = calibrate_if_it_helps(_fitted(features, targets),
                                        features, targets)
        maxima = {round(float(max(row)), 6)
                  for row in outcome.model.predict_proba(features)}
        assert len(maxima) > 1, "every input got the same confidence"


class TestDegenerateCalibrationIsRejected:
    def test_a_collapsed_calibration_is_backed_out(self):
        """Force the failure directly, at a size that would otherwise pass."""
        features, targets = _large(30)
        pipeline = _fitted(features, targets)

        outcome = calibrate_if_it_helps(pipeline, features, targets,
                                        min_samples=4)
        # Either it was refused, or it was applied and is not degenerate.
        maxima = {round(float(max(row)), 6)
                  for row in outcome.model.predict_proba(features[:32])}
        assert len(maxima) > 1

    def test_accuracy_loss_backs_calibration_out(self, monkeypatch):
        features, targets = _large(40)
        pipeline = _fitted(features, targets)

        class Collapsed:
            """Stands in for a calibrator that has learned nothing."""

            classes_ = ["negative", "positive"]

            def fit(self, X, y):
                return self

            def predict(self, X):
                return ["positive"] * len(X)

            def predict_proba(self, X):
                return [[0.5, 0.5] for _ in X]

        monkeypatch.setattr("sklearn.calibration.CalibratedClassifierCV",
                            lambda *a, **k: Collapsed())

        outcome = calibrate_if_it_helps(pipeline, features, targets,
                                        min_samples=4)
        assert outcome.applied is False
        assert outcome.model is pipeline
        assert "accuracy" in outcome.reason or "same probability" in outcome.reason


class TestMethodSelection:
    def test_sigmoid_below_the_isotonic_threshold(self):
        from potato.training.calibration import _method_for
        assert _method_for(MIN_SAMPLES_FOR_ISOTONIC - 1) == "sigmoid"

    def test_isotonic_above_it(self):
        from potato.training.calibration import _method_for
        assert _method_for(MIN_SAMPLES_FOR_ISOTONIC) == "isotonic"


class TestGuards:
    def test_disabled_returns_the_model_untouched(self):
        features, targets = _large(40)
        pipeline = _fitted(features, targets)
        outcome = calibrate_if_it_helps(pipeline, features, targets,
                                        enabled=False)
        assert outcome.applied is False
        assert outcome.model is pipeline
        assert outcome.reason == "disabled"

    def test_an_estimator_without_probabilities_is_skipped(self):
        class NoProbabilities:
            def predict(self, X):
                return ["a"] * len(X)

        outcome = calibrate_if_it_helps(NoProbabilities(), ["x"] * 100,
                                        ["a"] * 100)
        assert outcome.applied is False
        assert "probabilities" in outcome.reason

    def test_a_singleton_class_cannot_be_cross_validated(self):
        features = POS * 8 + ["a lone example"]
        targets = ["positive"] * (len(POS) * 8) + ["rare"]
        outcome = calibrate_if_it_helps(_fitted(features, targets),
                                        features, targets)
        assert outcome.applied is False
        assert "smallest class" in outcome.reason

    def test_calibration_never_raises_out_of_a_fit(self, monkeypatch):
        features, targets = _large(40)
        pipeline = _fitted(features, targets)

        def explode(*a, **k):
            raise RuntimeError("boom")

        monkeypatch.setattr("sklearn.calibration.CalibratedClassifierCV",
                            explode)
        outcome = calibrate_if_it_helps(pipeline, features, targets,
                                        min_samples=4)
        assert outcome.applied is False
        assert outcome.model is pipeline
        assert "boom" in outcome.reason

    def test_the_outcome_is_reportable(self):
        features, targets = _small()
        outcome = calibrate_if_it_helps(_fitted(features, targets),
                                        features, targets)
        data = outcome.to_dict()
        assert data["applied"] is False
        assert data["reason"]


class TestActiveLearningUsesIt:
    """The manager's own path, at the size it actually trains at."""

    def test_a_ten_annotation_fit_still_ranks(self):
        from potato.active_learning_manager import (ActiveLearningConfig,
                                                    ActiveLearningManager)

        manager = ActiveLearningManager(ActiveLearningConfig(
            enabled=False, schema_names=["s"], calibrate_probabilities=True,
            min_instances_for_training=5))

        # Overlapping vocabulary and uneven length, because perfectly
        # symmetric documents with disjoint vocabulary land every example at
        # the same distance from the boundary and give identical confidences
        # for reasons that have nothing to do with calibration.
        texts = [
            "this movie was great and I loved it",
            "a wonderful film, really excellent",
            "so good, I enjoyed the movie",
            "great work, wonderful and charming",
            "I loved this excellent film",
            "this movie was terrible and I hated it",
            "an awful film, really poor",
            "so bad, I disliked the movie",
            "poor work, awful and tedious",
            "I hated this dreadful film",
        ]
        training_data = {
            "texts": texts,
            "labels": ["positive"] * 5 + ["negative"] * 5,
            "instance_ids": ["i%d" % i for i in range(10)],
        }
        model, metrics = manager._train_classifier(training_data, "s")

        assert model is not None
        assert metrics.accuracy > 0.9, (
            "a 10-annotation fit scored %.2f; calibration collapsed the model"
            % metrics.accuracy)

        maxima = {round(float(max(row)), 6)
                  for row in model.predict_proba(training_data["texts"])}
        assert len(maxima) > 1, (
            "every instance got the same confidence, so uncertainty sampling "
            "has nothing to rank by")

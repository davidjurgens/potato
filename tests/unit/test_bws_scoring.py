"""Unit tests for BWS scoring module."""

import os
import tempfile

import pytest
from potato.bws_scoring import BwsScorer, write_scores


def make_pool(n=6):
    """Create a simple pool of items."""
    return [
        {"id": f"s{i:03d}", "text": f"Item {i}"}
        for i in range(1, n + 1)
    ]


def make_annotation(bws_items, best_pos, worst_pos, annotator="user1"):
    """Create a BWS annotation record."""
    return {
        "instance_id": "bws_tuple_0001",
        "bws_items": bws_items,
        "best": best_pos,
        "worst": worst_pos,
        "annotator": annotator,
    }


def make_bws_items(source_ids):
    """Create BWS items list from source IDs."""
    positions = [chr(ord("A") + i) for i in range(len(source_ids))]
    return [
        {"source_id": sid, "text": f"Text for {sid}", "position": pos}
        for sid, pos in zip(source_ids, positions)
    ]


class TestBwsCounting:
    """Tests for counting scoring method."""

    def test_counting_basic(self):
        """Correct scores for simple annotations."""
        pool = make_pool(4)
        items = make_bws_items(["s001", "s002", "s003", "s004"])

        annotations = [
            make_annotation(items, "A", "D"),  # s001=best, s004=worst
        ]

        scorer = BwsScorer(annotations, pool, "id", "text")
        scores = scorer.counting()

        assert scores["s001"]["score"] == 1.0  # 1 best, 0 worst, 1 appearance
        assert scores["s004"]["score"] == -1.0  # 0 best, 1 worst, 1 appearance
        assert scores["s002"]["score"] == 0.0   # 0 best, 0 worst, 1 appearance
        assert scores["s003"]["score"] == 0.0   # 0 best, 0 worst, 1 appearance

    def test_counting_all_best_score_one(self):
        """Item always picked as best gets score 1.0."""
        pool = make_pool(4)
        items = make_bws_items(["s001", "s002", "s003", "s004"])

        annotations = [
            make_annotation(items, "A", "B"),
            make_annotation(items, "A", "C"),
            make_annotation(items, "A", "D"),
        ]

        scorer = BwsScorer(annotations, pool, "id", "text")
        scores = scorer.counting()

        assert scores["s001"]["score"] == 1.0
        assert scores["s001"]["best_count"] == 3
        assert scores["s001"]["worst_count"] == 0

    def test_counting_all_worst_score_neg_one(self):
        """Item always picked as worst gets score -1.0."""
        pool = make_pool(4)
        items = make_bws_items(["s001", "s002", "s003", "s004"])

        annotations = [
            make_annotation(items, "B", "A"),
            make_annotation(items, "C", "A"),
            make_annotation(items, "D", "A"),
        ]

        scorer = BwsScorer(annotations, pool, "id", "text")
        scores = scorer.counting()

        assert scores["s001"]["score"] == -1.0
        assert scores["s001"]["best_count"] == 0
        assert scores["s001"]["worst_count"] == 3

    def test_counting_no_annotations(self):
        """No annotations gives score 0.0."""
        pool = make_pool(4)
        scorer = BwsScorer([], pool, "id", "text")
        scores = scorer.counting()

        for iid in ["s001", "s002", "s003", "s004"]:
            assert scores[iid]["score"] == 0.0
            assert scores[iid]["appearances"] == 0

    def test_counting_multiple_annotators(self):
        """Aggregates across users correctly."""
        pool = make_pool(4)
        items = make_bws_items(["s001", "s002", "s003", "s004"])

        annotations = [
            make_annotation(items, "A", "D", annotator="user1"),
            make_annotation(items, "A", "C", annotator="user2"),
            make_annotation(items, "B", "D", annotator="user3"),
        ]

        scorer = BwsScorer(annotations, pool, "id", "text")
        scores = scorer.counting()

        # s001: 2 best, 0 worst, 3 appearances = 2/3
        assert abs(scores["s001"]["score"] - 2 / 3) < 0.001
        # s004: 0 best, 2 worst, 3 appearances = -2/3
        assert abs(scores["s004"]["score"] - (-2 / 3)) < 0.001

    def test_counting_incomplete_annotation_skipped(self):
        """Annotations missing best or worst are skipped."""
        pool = make_pool(4)
        items = make_bws_items(["s001", "s002", "s003", "s004"])

        annotations = [
            make_annotation(items, "A", "D"),
            {"instance_id": "t2", "bws_items": items, "best": "A", "worst": ""},
            {"instance_id": "t3", "bws_items": items, "best": "", "worst": "B"},
        ]

        scorer = BwsScorer(annotations, pool, "id", "text")
        scores = scorer.counting()

        # Only the first annotation should count
        assert scores["s001"]["appearances"] == 1


class TestBwsBradleyTerry:
    """Tests for Bradley-Terry scoring method."""

    def test_bradley_terry_requires_choix(self):
        """ImportError with helpful message if choix missing."""
        pool = make_pool(4)
        items = make_bws_items(["s001", "s002", "s003", "s004"])
        annotations = [make_annotation(items, "A", "D")]

        scorer = BwsScorer(annotations, pool, "id", "text")

        try:
            import choix
            # choix is available, test ordering instead
            scores = scorer.bradley_terry()
            assert scores["s001"]["score"] > scores["s004"]["score"]
        except ImportError:
            with pytest.raises(ImportError, match="choix"):
                scorer.bradley_terry()

    def test_bradley_terry_ordering(self):
        """Known-better items get higher BT scores."""
        try:
            import choix
        except ImportError:
            pytest.skip("choix not installed")

        pool = make_pool(4)
        items = make_bws_items(["s001", "s002", "s003", "s004"])

        # s001 is always best, s004 is always worst
        annotations = [
            make_annotation(items, "A", "D"),
            make_annotation(items, "A", "D"),
            make_annotation(items, "A", "D"),
        ]

        scorer = BwsScorer(annotations, pool, "id", "text")
        scores = scorer.bradley_terry()

        assert scores["s001"]["score"] > scores["s002"]["score"]
        assert scores["s001"]["score"] > scores["s004"]["score"]
        assert scores["s002"]["score"] > scores["s004"]["score"]


class TestBwsPlackettLuce:
    """Tests for Plackett-Luce scoring method."""

    def test_plackett_luce_ordering(self):
        """Known-better items get higher PL scores."""
        try:
            import choix
        except ImportError:
            pytest.skip("choix not installed")

        pool = make_pool(4)
        items = make_bws_items(["s001", "s002", "s003", "s004"])

        annotations = [
            make_annotation(items, "A", "D"),
            make_annotation(items, "A", "D"),
            make_annotation(items, "A", "D"),
        ]

        scorer = BwsScorer(annotations, pool, "id", "text")
        scores = scorer.plackett_luce()

        assert scores["s001"]["score"] > scores["s004"]["score"]


class TestScoreFileOutput:
    """Tests for score file writing."""

    def test_score_file_output(self):
        """write_scores() produces correct TSV with header, scores, and ranks."""
        scores = {
            "s001": {"score": 0.5, "best_count": 3, "worst_count": 1, "appearances": 4, "text": "Item 1"},
            "s002": {"score": -0.25, "best_count": 1, "worst_count": 2, "appearances": 4, "text": "Item 2"},
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "bws_scores.tsv")
            write_scores(scores, output_path)

            assert os.path.exists(output_path)

            with open(output_path) as f:
                lines = f.readlines()

            # Header + 2 data rows
            assert len(lines) == 3
            header = lines[0].strip()
            assert "item_id" in header
            assert "score" in header
            assert "rank" in header

            # First row should be the higher-scored item
            first_data = lines[1].strip().split("\t")
            assert first_data[0] == "s001"
            assert first_data[-1] == "1"  # rank 1

    def test_score_method_dispatch(self):
        """score() method dispatches correctly."""
        pool = make_pool(4)
        items = make_bws_items(["s001", "s002", "s003", "s004"])
        annotations = [make_annotation(items, "A", "D")]

        scorer = BwsScorer(annotations, pool, "id", "text")

        # Counting should always work
        scores = scorer.score("counting")
        assert "s001" in scores

        # Invalid method should raise
        with pytest.raises(ValueError, match="Unknown scoring method"):
            scorer.score("invalid_method")

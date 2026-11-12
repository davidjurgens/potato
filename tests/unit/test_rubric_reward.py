"""Unit tests for Rubrics-as-Rewards export (E9)."""

import pytest

from potato.server_utils.rubric_reward import (
    reward_row_from_agent_judge, reward_row_from_dag, build_reward_dataset,
)


AGENT_RESULT = {"key": "agent_as_judge", "score": 2 / 3,
                "metadata": {"verdicts": [
                    {"requirement": "under $400", "satisfied": True, "evidence": "$371"},
                    {"requirement": "refundable", "satisfied": True, "evidence": "ok"},
                    {"requirement": "emailed", "satisfied": False, "evidence": "no email"}]}}

DAG_RESULT = {"key": "rubric_dag", "score": 1.0,
              "metadata": {"path": [{"node": "answers", "choice": "yes", "reasoning": "x"},
                                    {"node": "grounded", "choice": "yes", "reasoning": "y"}],
                           "leaf": {"score": 1.0, "label": "complete"}}}


class TestAgentJudgeRows:
    def test_criteria_and_reward(self):
        row = reward_row_from_agent_judge(AGENT_RESULT, prompt="book", response="booked")
        assert len(row["criteria"]) == 3
        assert row["reward"] == pytest.approx(2 / 3)  # 2 of 3 satisfied, equal weights
        assert row["source"] == "agent_as_judge"
        assert row["criteria"][0]["points"] == 1.0 and row["criteria"][2]["points"] == 0.0

    def test_weights_applied(self):
        # weight the "emailed" (failed) criterion heavily -> reward drops
        row = reward_row_from_agent_judge(AGENT_RESULT, weights={"emailed": 8.0})
        assert row["reward"] < 0.5

    def test_no_verdicts(self):
        assert reward_row_from_agent_judge({"metadata": {}}) is None


class TestDagRows:
    def test_path_to_criteria_and_reward(self):
        row = reward_row_from_dag(DAG_RESULT, prompt="q", response="Paris")
        assert row["reward"] == 1.0
        assert [c["name"] for c in row["criteria"]] == ["answers", "grounded"]
        assert row["leaf"]["label"] == "complete"
        assert row["source"] == "rubric_dag"


class TestBuildDataset:
    def test_autodetects_source(self):
        rows = build_reward_dataset([
            {"result": AGENT_RESULT, "prompt": "a"},
            {"result": DAG_RESULT, "prompt": "b"}])
        assert {r["source"] for r in rows} == {"agent_as_judge", "rubric_dag"}
        assert len(rows) == 2

    def test_skips_empty(self):
        rows = build_reward_dataset([{"result": {"key": "agent_as_judge", "metadata": {}}}])
        assert rows == []

    def test_jsonl_ready(self):
        import json
        rows = build_reward_dataset([{"result": AGENT_RESULT}])
        json.dumps(rows[0])  # must serialize
        assert "reward" in rows[0] and "criteria" in rows[0]

"""Unit tests for dataset -> SFT/DPO export."""

import json

import pytest

from potato.eval_datasets.models import Example
from potato.eval_datasets.export import to_sft_records, to_dpo_records, export_examples


def test_sft_records_skip_without_reference():
    examples = [
        Example(id="a", inputs={"q": "1+1"}, reference_outputs={"output": "2"}),
        Example(id="b", inputs={"q": "2+2"}, reference_outputs=None),  # skipped
    ]
    records, skipped = to_sft_records(examples)
    assert skipped == 1
    assert records == [{"prompt": json.dumps({"q": "1+1"}, ensure_ascii=False), "completion": "2"}]


def test_dpo_records_need_chosen_and_rejected():
    examples = [
        Example(id="a", inputs={"q": "x"}, reference_outputs={"output": "good"},
                metadata={"rejected": "bad"}),
        Example(id="b", inputs={"q": "y"}, reference_outputs={"output": "good"}),  # no rejected -> skip
        Example(id="c", inputs={"q": "z"}, reference_outputs={"output": "good"},
                metadata={"outputs": "worse"}),  # falls back to outputs
    ]
    records, skipped = to_dpo_records(examples)
    assert skipped == 1
    assert records[0] == {"prompt": json.dumps({"q": "x"}, ensure_ascii=False),
                          "chosen": "good", "rejected": "bad"}
    assert records[1]["rejected"] == "worse"


def test_export_examples_jsonl_and_unknown_format():
    examples = [Example(id="a", inputs={"q": "1"}, reference_outputs={"output": "2"})]
    jsonl, skipped = export_examples(examples, "sft")
    assert jsonl.endswith("\n") and json.loads(jsonl.strip())["completion"] == "2"
    with pytest.raises(ValueError):
        export_examples(examples, "bogus")

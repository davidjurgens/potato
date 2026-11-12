"""Runtime trial tables write values the way jsPsych's own CSV does."""

import csv
import io

from potato.export.runtime_exporter import _cell


def _written(row):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(row))
    writer.writeheader()
    writer.writerow({k: _cell(v) for k, v in row.items()})
    return out.getvalue().splitlines()[1]


def test_booleans_are_lowercase():
    # csv writes a Python bool as True/False; jsPsych and R read true/false.
    assert _written({"correct": True, "timed_out": False}) == "true,false"


def test_numbers_and_nested_values_are_unchanged():
    assert _written({"rt": 512, "zero": 0, "resp": {"a": 1}}) == '512,0,"{""a"":1}"'


def test_numpy_booleans_are_lowercase_too():
    import numpy as np
    assert _written({"correct": np.bool_(True)}) == "true"

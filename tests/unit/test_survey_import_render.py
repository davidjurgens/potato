"""Every question any survey importer writes renders as a question.

A scheme its generator refuses (an empty pure_display description or labels
list, a slider without bounds) shows "Error Generating Annotation Form" in
place of the question, and no importer test that only inspects the scheme
dicts notices.
"""

from pathlib import Path

import pytest

from potato.importers import surveys
from potato.server_utils.schemas.registry import schema_registry

FIXTURES = Path(__file__).resolve().parents[1] / "data" / "surveys"
CASES = sorted(p for p in FIXTURES.rglob("*") if p.is_file() and surveys.detect(str(p)))


def test_fixtures_found():
    assert {surveys.detect(str(p)) for p in CASES} >= {"surveyjs", "qualtrics", "limesurvey",
                                                       "redcap", "beiwe"}


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.name)
def test_every_imported_question_renders(path):
    result = surveys.IMPORTERS[surveys.detect(str(path))].parse_path(path, {})
    bad = []
    for q in result.all_questions():
        html, _ = schema_registry.generate(dict(q))
        if "Error Generating" in html:
            bad.append(q["name"])
    assert not bad, f"{path.name}: {bad}"

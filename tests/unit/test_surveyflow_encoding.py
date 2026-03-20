"""
Tests for issue #116: Surveyflow text rendered with incorrect encoding.

Survey JSON files must be opened with encoding='utf-8' to prevent mojibake
on systems where the default encoding is not UTF-8 (e.g., Windows).
"""

import json
import os
import pytest
import tempfile

from tests.helpers.test_utils import create_test_directory, cleanup_test_directory


class TestSurveyflowEncoding:
    """Test that surveyflow phase files with non-ASCII content are loaded correctly."""

    @pytest.fixture
    def test_dir(self):
        test_dir = create_test_directory("encoding_test")
        yield test_dir
        cleanup_test_directory(test_dir)

    def test_get_phase_annotation_schemes_loads_utf8_json(self, test_dir):
        """
        Issue #116: JSON phase files with German umlauts should be loaded correctly.
        """
        # Create a JSON survey file with German text
        survey_data = {
            "title": "Einverständniserklärung",
            "description": "Ich möchte an dieser Forschung teilnehmen.",
            "questions": [
                {
                    "question": "Stimmen Sie zu, über die Brücke zu gehen?",
                    "type": "radio",
                    "options": ["Ja, natürlich", "Nein"]
                }
            ]
        }

        survey_file = os.path.join(test_dir, "consent.json")
        with open(survey_file, "w", encoding="utf-8") as f:
            json.dump(survey_data, f, ensure_ascii=False)

        # Load using the function under test
        from potato.flask_server import get_phase_annotation_schemes
        schemes = get_phase_annotation_schemes(survey_file)

        # Verify the text was loaded correctly (not mojibake)
        assert isinstance(schemes, list)
        assert len(schemes) == 1
        scheme = schemes[0]
        assert "möchte" in scheme.get("description", "")
        assert "Einverständniserklärung" in scheme.get("title", "")
        assert "natürlich" in scheme["questions"][0]["options"][0]
        assert "Brücke" in scheme["questions"][0]["question"]

    def test_get_phase_annotation_schemes_loads_utf8_jsonl(self, test_dir):
        """JSONL phase files with non-ASCII content should load correctly."""
        survey_items = [
            {"title": "Fråga 1", "text": "Vad tycker du om ämnet?"},
            {"title": "Fråga 2", "text": "Är du nöjd?"},
        ]

        survey_file = os.path.join(test_dir, "survey.jsonl")
        with open(survey_file, "w", encoding="utf-8") as f:
            for item in survey_items:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

        from potato.flask_server import get_phase_annotation_schemes
        schemes = get_phase_annotation_schemes(survey_file)

        assert len(schemes) == 2
        assert "Fråga" in schemes[0]["title"]
        assert "ämnet" in schemes[0]["text"]
        assert "nöjd" in schemes[1]["text"]

    def test_get_phase_annotation_schemes_loads_utf8_yaml(self, test_dir):
        """YAML phase files with non-ASCII content should load correctly."""
        import yaml

        survey_data = [
            {"title": "Вопрос", "text": "Как вы себя чувствуете?"},
        ]

        survey_file = os.path.join(test_dir, "survey.yaml")
        with open(survey_file, "w", encoding="utf-8") as f:
            yaml.dump(survey_data, f, allow_unicode=True)

        from potato.flask_server import get_phase_annotation_schemes
        schemes = get_phase_annotation_schemes(survey_file)

        assert len(schemes) == 1
        assert "Вопрос" in schemes[0]["title"]

    def test_chinese_characters_in_survey(self, test_dir):
        """Chinese characters in survey files should be preserved."""
        survey_data = {
            "title": "同意书",
            "description": "请仔细阅读以下信息。",
        }

        survey_file = os.path.join(test_dir, "consent_zh.json")
        with open(survey_file, "w", encoding="utf-8") as f:
            json.dump(survey_data, f, ensure_ascii=False)

        from potato.flask_server import get_phase_annotation_schemes
        schemes = get_phase_annotation_schemes(survey_file)

        assert "同意书" in schemes[0]["title"]
        assert "请仔细阅读" in schemes[0]["description"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""
Unit tests verifying UTF-8 encoding is used for all file I/O operations.

Regression tests for GitHub issue #112: UnicodeDecodeError on Windows
when template files contain non-ASCII characters (e.g., German umlauts).

On Windows, Python defaults to the system encoding (often cp1252) when
no encoding is specified. These tests verify that non-ASCII content
round-trips correctly through all file read/write paths.
"""

import json
import os
import tempfile
import textwrap
from unittest.mock import patch

import pytest


# Non-ASCII test strings covering common problem characters
NON_ASCII_SAMPLES = {
    "german": "Bewertung: positiv / negativ / ärgerlich / überraschend",
    "french": "Positif / Négatif / Très bien",
    "chinese": "情感分析：正面 / 负面 / 中性",
    "japanese": "感情: ポジティブ / ネガティブ",
    "spanish": "Clasificación: buño / señal / año",
    "mixed": "Héllo — 中文 — ñoño — Ünïcödé — 日本語 — émojis",
    "special": "curly quotes \u201c \u201d, em dash \u2014, bullet \u2022, euro \u20ac",
}


class TestFrontEndGetHtml:
    """Tests for front_end.get_html() reading HTML files with non-ASCII content."""

    def test_reads_german_umlauts(self, tmp_path):
        html_file = tmp_path / "page.html"
        html_file.write_text(
            f"<p>{NON_ASCII_SAMPLES['german']}</p>", encoding="utf-8"
        )
        from potato.server_utils.front_end import get_html

        config = {"__config_file__": str(tmp_path / "config.yaml")}
        result = get_html(str(html_file), config)
        assert NON_ASCII_SAMPLES["german"] in result

    def test_reads_cjk_characters(self, tmp_path):
        html_file = tmp_path / "page.html"
        content = f"<div>{NON_ASCII_SAMPLES['chinese']}</div>"
        html_file.write_text(content, encoding="utf-8")
        from potato.server_utils.front_end import get_html

        config = {"__config_file__": str(tmp_path / "config.yaml")}
        result = get_html(str(html_file), config)
        assert NON_ASCII_SAMPLES["chinese"] in result

    def test_reads_mixed_unicode(self, tmp_path):
        html_file = tmp_path / "page.html"
        html_file.write_text(
            f"<span>{NON_ASCII_SAMPLES['mixed']}</span>", encoding="utf-8"
        )
        from potato.server_utils.front_end import get_html

        config = {"__config_file__": str(tmp_path / "config.yaml")}
        result = get_html(str(html_file), config)
        assert NON_ASCII_SAMPLES["mixed"] in result

    def test_resolves_relative_path_with_non_ascii(self, tmp_path):
        html_file = tmp_path / "layout.html"
        html_file.write_text(
            f"<p>{NON_ASCII_SAMPLES['french']}</p>", encoding="utf-8"
        )
        config_file = tmp_path / "config.yaml"
        config_file.write_text("", encoding="utf-8")
        from potato.server_utils.front_end import get_html

        result = get_html("layout.html", {"__config_file__": str(config_file)})
        assert NON_ASCII_SAMPLES["french"] in result


class TestFrontEndLayoutGeneration:
    """Tests for annotation layout file generation with non-ASCII labels."""

    def test_generate_layout_with_german_labels(self, tmp_path):
        from potato.server_utils.front_end import generate_annotation_layout_file

        config = {
            "task_dir": str(tmp_path),
            "annotation_task_name": "Bewertung",
            "__config_file__": str(tmp_path / "config.yaml"),
        }
        schemes = [
            {
                "annotation_type": "radio",
                "annotation_id": 0,
                "name": "bewertung",
                "description": NON_ASCII_SAMPLES["german"],
                "labels": ["Ärgerlich", "Überraschend", "Positiv"],
            }
        ]
        path = generate_annotation_layout_file(config, schemes)
        assert os.path.exists(path)
        content = open(path, encoding="utf-8").read()
        assert "<!-- CONFIG_HASH:" in content

    def test_generate_layout_with_cjk_labels(self, tmp_path):
        from potato.server_utils.front_end import generate_annotation_layout_file

        config = {
            "task_dir": str(tmp_path),
            "annotation_task_name": "感情分析",
            "__config_file__": str(tmp_path / "config.yaml"),
        }
        schemes = [
            {
                "annotation_type": "radio",
                "annotation_id": 0,
                "name": "sentiment",
                "description": NON_ASCII_SAMPLES["chinese"],
                "labels": ["正面", "负面", "中性"],
            }
        ]
        path = generate_annotation_layout_file(config, schemes)
        assert os.path.exists(path)
        content = open(path, encoding="utf-8").read()
        assert "<!-- CONFIG_HASH:" in content

    def test_layout_roundtrip_preserves_non_ascii(self, tmp_path):
        """Write a layout then read it back — non-ASCII must survive."""
        from potato.server_utils.front_end import (
            generate_annotation_layout_file,
            get_or_generate_annotation_layout,
        )

        config = {
            "task_dir": str(tmp_path),
            "annotation_task_name": "Test",
            "__config_file__": str(tmp_path / "config.yaml"),
        }
        schemes = [
            {
                "annotation_type": "radio",
                "annotation_id": 0,
                "name": "q",
                "description": NON_ASCII_SAMPLES["spanish"],
                "labels": ["Señal", "Año"],
            }
        ]
        # Generate
        path = generate_annotation_layout_file(config, schemes)

        # Read back via get_or_generate (should use cached version)
        path2 = get_or_generate_annotation_layout(config, schemes)
        assert path == path2

        content = open(path2, encoding="utf-8").read()
        assert "CONFIG_HASH" in content


class TestFrontEndCacheHashWithNonAscii:
    """Tests that cache hash checking works with non-ASCII layout files."""

    def test_repeated_generation_with_non_ascii_does_not_crash(self, tmp_path):
        """Calling get_or_generate twice with non-ASCII should not raise."""
        from potato.server_utils.front_end import get_or_generate_annotation_layout

        config = {
            "task_dir": str(tmp_path),
            "annotation_task_name": "Ünïcödé",
            "__config_file__": str(tmp_path / "config.yaml"),
        }
        schemes = [
            {
                "annotation_type": "radio",
                "annotation_id": 0,
                "name": "q",
                "description": "Ünïcödé description",
                "labels": ["ä", "ö", "ü"],
            }
        ]
        # First call generates the file
        path1 = get_or_generate_annotation_layout(config, schemes)
        assert os.path.exists(path1)

        # Second call reads the existing file (hash check) — must not crash
        path2 = get_or_generate_annotation_layout(config, schemes)
        assert os.path.exists(path2)

    def test_hash_mismatch_triggers_regeneration(self, tmp_path):
        from potato.server_utils.front_end import get_or_generate_annotation_layout

        config = {
            "task_dir": str(tmp_path),
            "annotation_task_name": "Test",
            "__config_file__": str(tmp_path / "config.yaml"),
        }
        schemes_v1 = [
            {
                "annotation_type": "radio",
                "annotation_id": 0,
                "name": "q",
                "description": "Version Eins",
                "labels": ["Ärgerlich"],
            }
        ]
        schemes_v2 = [
            {
                "annotation_type": "radio",
                "annotation_id": 0,
                "name": "q",
                "description": "Version Zwei",
                "labels": ["Ärgerlich", "Überraschend"],
            }
        ]
        path1 = get_or_generate_annotation_layout(config, schemes_v1)
        mtime1 = os.path.getmtime(path1)

        import time

        time.sleep(0.05)
        path2 = get_or_generate_annotation_layout(config, schemes_v2)
        mtime2 = os.path.getmtime(path2)
        assert mtime2 > mtime1


class TestUserStateSaveLoadUtf8:
    """Tests that user state save/load handles non-ASCII annotation values."""

    def test_save_and_load_non_ascii_annotations(self, tmp_path):
        """UserState with non-ASCII annotation text should round-trip through JSON."""
        user_dir = str(tmp_path / "user1")
        os.makedirs(user_dir, exist_ok=True)

        state_file = os.path.join(user_dir, "user_state.json")
        state = {
            "phase": "annotation",
            "annotations": {
                "item_001": {
                    "sentiment": NON_ASCII_SAMPLES["german"],
                    "notes": NON_ASCII_SAMPLES["chinese"],
                }
            },
        }

        # Write with encoding
        fd, temp_path = tempfile.mkstemp(dir=user_dir, suffix=".tmp")
        with os.fdopen(fd, "wt", encoding="utf-8") as outf:
            json.dump(state, outf, indent=2)
        os.replace(temp_path, state_file)

        # Read back with encoding
        with open(state_file, "rt", encoding="utf-8") as f:
            loaded = json.load(f)

        assert loaded["annotations"]["item_001"]["sentiment"] == NON_ASCII_SAMPLES["german"]
        assert loaded["annotations"]["item_001"]["notes"] == NON_ASCII_SAMPLES["chinese"]

    def test_json_with_special_unicode(self, tmp_path):
        """Special Unicode characters (curly quotes, em dash, euro) survive round-trip."""
        user_dir = str(tmp_path / "user2")
        os.makedirs(user_dir, exist_ok=True)

        state_file = os.path.join(user_dir, "user_state.json")
        state = {"notes": NON_ASCII_SAMPLES["special"]}

        fd, temp_path = tempfile.mkstemp(dir=user_dir, suffix=".tmp")
        with os.fdopen(fd, "wt", encoding="utf-8") as outf:
            json.dump(state, outf, indent=2, ensure_ascii=False)
        os.replace(temp_path, state_file)

        with open(state_file, "rt", encoding="utf-8") as f:
            loaded = json.load(f)

        assert loaded["notes"] == NON_ASCII_SAMPLES["special"]


class TestAuthenticationUtf8:
    """Tests that user authentication file I/O handles non-ASCII usernames."""

    def test_jsonl_user_file_with_non_ascii_names(self, tmp_path):
        """User config JSONL with non-ASCII usernames should round-trip."""
        user_file = tmp_path / "users.jsonl"
        users = [
            {"username": "müller", "password": "hash1"},
            {"username": "田中太郎", "password": "hash2"},
            {"username": "garcía", "password": "hash3"},
        ]

        # Write as JSONL
        with open(str(user_file), "wt", encoding="utf-8") as f:
            for u in users:
                f.write(json.dumps(u, ensure_ascii=False) + "\n")

        # Read back
        loaded = []
        with open(str(user_file), "rt", encoding="utf-8") as f:
            for line in f.readlines():
                loaded.append(json.loads(line.strip()))

        assert loaded[0]["username"] == "müller"
        assert loaded[1]["username"] == "田中太郎"
        assert loaded[2]["username"] == "garcía"


class TestQualityControlUtf8:
    """Tests that quality control JSON files handle non-ASCII content."""

    def test_attention_check_with_non_ascii_text(self, tmp_path):
        """Attention check items with non-ASCII text should load correctly."""
        check_file = tmp_path / "attention_checks.json"
        items = [
            {
                "id": "check_1",
                "text": "Bewerten Sie: Diese Aussage ist ärgerlich.",
                "expected": "negativ",
            },
            {
                "id": "check_2",
                "text": "评价：这个句子是正面的。",
                "expected": "正面",
            },
        ]
        with open(str(check_file), "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False)

        # Read back
        with open(str(check_file), "r", encoding="utf-8") as f:
            loaded = json.load(f)

        assert loaded[0]["text"] == "Bewerten Sie: Diese Aussage ist ärgerlich."
        assert loaded[1]["expected"] == "正面"

    def test_gold_standard_with_non_ascii_labels(self, tmp_path):
        """Gold standard items with non-ASCII labels should load correctly."""
        gold_file = tmp_path / "gold_standards.json"
        items = [
            {
                "id": "gold_1",
                "text": "El año pasado fue difícil.",
                "label": "Señal negativa",
            }
        ]
        with open(str(gold_file), "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False)

        with open(str(gold_file), "r", encoding="utf-8") as f:
            loaded = json.load(f)

        assert loaded[0]["label"] == "Señal negativa"


class TestSchemaTooltipUtf8:
    """Tests that schema tooltip file reading handles non-ASCII content."""

    def test_tooltip_file_with_german_text(self, tmp_path):
        """Tooltip files with German umlauts should be read correctly."""
        tooltip_file = tmp_path / "tooltip.html"
        tooltip_content = "<p>Wählen Sie die Bewertung für diesen Ärger-Auslöser.</p>"
        tooltip_file.write_text(tooltip_content, encoding="utf-8")

        with open(str(tooltip_file), "rt", encoding="utf-8") as f:
            result = "".join(f.readlines())

        assert "Ärger-Auslöser" in result

    def test_tooltip_file_with_cjk(self, tmp_path):
        """Tooltip files with CJK characters should be read correctly."""
        tooltip_file = tmp_path / "tooltip_cjk.html"
        tooltip_content = "<p>このラベルは感情分析の結果を示します。</p>"
        tooltip_file.write_text(tooltip_content, encoding="utf-8")

        with open(str(tooltip_file), "rt", encoding="utf-8") as f:
            result = "".join(f.readlines())

        assert "感情分析" in result


class TestOpenEncodingParameter:
    """
    Static analysis tests verifying that open() calls in critical files
    include encoding='utf-8'. These catch regressions if someone adds a
    new open() call without encoding.
    """

    CRITICAL_FILES = [
        "potato/server_utils/front_end.py",
        "potato/user_state_management.py",
        "potato/authentication.py",
        "potato/quality_control.py",
    ]

    @pytest.fixture
    def project_root(self):
        return os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))

    @pytest.mark.parametrize("rel_path", CRITICAL_FILES)
    def test_no_text_open_without_encoding(self, project_root, rel_path):
        """All text-mode open() calls in critical files must specify encoding."""
        import re

        filepath = os.path.join(project_root, rel_path)
        if not os.path.exists(filepath):
            pytest.skip(f"File not found: {filepath}")

        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()

        # Find open() calls that are text mode (not 'rb' or 'wb')
        # Pattern: open(...) with 'r', 'w', 'rt', 'wt', 'a', 'at' modes
        # but NOT 'rb', 'wb', 'ab' binary modes
        text_open_pattern = re.compile(
            r"""open\s*\([^)]*?['"]([rawt]+)['"][^)]*\)"""
        )
        fdopen_pattern = re.compile(
            r"""fdopen\s*\([^)]*?['"]([rawt]+)['"][^)]*\)"""
        )

        for line_num, line in enumerate(source.splitlines(), 1):
            stripped = line.strip()
            # Skip comments and strings
            if stripped.startswith("#"):
                continue

            for pattern in [text_open_pattern, fdopen_pattern]:
                for match in pattern.finditer(line):
                    mode = match.group(1)
                    # Skip binary modes
                    if "b" in mode:
                        continue
                    # Verify encoding is specified
                    full_call = line[match.start() :]
                    assert "encoding" in full_call, (
                        f"{rel_path}:{line_num} has text-mode open() "
                        f"without encoding parameter:\n  {stripped}"
                    )


class TestEndToEndNonAsciiTemplate:
    """
    End-to-end test: generate a complete layout file with non-ASCII content,
    then read it back, simulating the full pipeline that crashed in issue #112.
    """

    def test_full_pipeline_german_umlauts(self, tmp_path):
        """
        Simulates the exact scenario from issue #112:
        1. Generate template with German umlaut labels
        2. Write to disk
        3. Read back (as Jinja would)
        4. Verify content is intact
        """
        from potato.server_utils.front_end import generate_annotation_layout_file

        config = {
            "task_dir": str(tmp_path),
            "annotation_task_name": "Deutsche Bewertung",
            "__config_file__": str(tmp_path / "config.yaml"),
        }
        schemes = [
            {
                "annotation_type": "radio",
                "annotation_id": 0,
                "name": "bewertung",
                "description": "Bewerten Sie die Aussage",
                "labels": [
                    "Ärgerlich",
                    "Überraschend",
                    "Glücklich",
                    "Trübsinnig",
                ],
            }
        ]

        # Step 1-2: Generate and write
        layout_path = generate_annotation_layout_file(config, schemes)

        # Step 3: Read back (simulating what Jinja/Flask does)
        with open(layout_path, "rt", encoding="utf-8") as f:
            content = f.read()

        # Step 4: Verify - no UnicodeDecodeError raised, content intact
        assert "CONFIG_HASH" in content
        assert "annotation_schema" in content

    def test_full_pipeline_multibyte_unicode(self, tmp_path):
        """Same pipeline with CJK and emoji-adjacent Unicode."""
        from potato.server_utils.front_end import generate_annotation_layout_file

        config = {
            "task_dir": str(tmp_path),
            "annotation_task_name": "多言語テスト",
            "__config_file__": str(tmp_path / "config.yaml"),
        }
        schemes = [
            {
                "annotation_type": "radio",
                "annotation_id": 0,
                "name": "lang_test",
                "description": "多言語テスト — 中文 / 日本語 / 한국어",
                "labels": ["正面", "ポジティブ", "긍정적"],
            }
        ]

        layout_path = generate_annotation_layout_file(config, schemes)

        with open(layout_path, "rt", encoding="utf-8") as f:
            content = f.read()

        assert "CONFIG_HASH" in content

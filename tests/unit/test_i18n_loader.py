"""Unit tests for bundled UI-language catalog loading and resolution.

Covers potato/server_utils/i18n.py:
- load_catalog: valid code, unknown code, path-traversal rejection, key filtering
- resolve_ui_language: string / legacy-dict / _base+overrides forms, precedence
- available_language_codes: discovers the shipped catalogs
- catalog integrity: every bundled catalog matches the whitelist exactly and
  preserves the {token} placeholders (a drift guard so new keys can't silently
  desync the defaults, the whitelist, and the translations)
"""

import re

import pytest

from potato.server_utils.i18n import (
    available_language_codes,
    is_valid_language_code,
    load_catalog,
    resolve_ui_language,
)
from potato.server_utils.config_module import KNOWN_CONFIG_KEYS


WHITELIST = KNOWN_CONFIG_KEYS["ui_language"] - {"_base"}

# Keys whose values carry client-substituted placeholders. The exact token set
# must survive translation or the runtime .replace() breaks.
PLACEHOLDER_KEYS = {
    "dash_assigned_completed": {"n", "total"},
    "dash_items_started_pct": {"started", "total", "pct"},
    "admin_opt_per_page": {"n"},
    "judge_over_versions": {"n"},
}


class TestValidCode:
    def test_accepts_simple_codes(self):
        assert is_valid_language_code("es")
        assert is_valid_language_code("zh")
        assert is_valid_language_code("pt-br")

    def test_rejects_traversal_and_junk(self):
        assert not is_valid_language_code("../secret")
        assert not is_valid_language_code("es/../../etc/passwd")
        assert not is_valid_language_code("")
        assert not is_valid_language_code("EN")  # uppercase not allowed
        assert not is_valid_language_code(None)


class TestLoadCatalog:
    def test_loads_spanish(self):
        cat = load_catalog("es")
        assert cat is not None
        assert cat["next_button"] == "Siguiente"
        assert cat["html_lang"] == "es"
        assert cat["html_dir"] == "ltr"

    def test_arabic_is_rtl(self):
        cat = load_catalog("ar")
        assert cat["html_dir"] == "rtl"

    def test_unknown_code_returns_none_and_warns(self, caplog):
        with caplog.at_level("WARNING"):
            assert load_catalog("xx") is None
        assert any("xx" in r.message for r in caplog.records)

    def test_traversal_code_rejected(self, caplog):
        # Must never build a path from an unvalidated code.
        with caplog.at_level("WARNING"):
            assert load_catalog("../secret") is None

    def test_only_whitelisted_keys_returned(self):
        cat = load_catalog("es")
        assert set(cat.keys()) <= WHITELIST


class TestResolveUiLanguage:
    DEFAULTS = {"next_button": "Next", "html_dir": "ltr", "keep": "keepme"}

    def test_none_returns_pure_defaults(self):
        out = resolve_ui_language(None, self.DEFAULTS)
        assert out["next_button"] == "Next"
        assert out["keep"] == "keepme"

    def test_string_code_loads_catalog(self):
        out = resolve_ui_language("es", self.DEFAULTS)
        assert out["next_button"] == "Siguiente"
        # untranslated default keys still fall through
        assert out["keep"] == "keepme"

    def test_legacy_dict_still_overrides(self):
        out = resolve_ui_language({"next_button": "Weiter"}, self.DEFAULTS)
        assert out["next_button"] == "Weiter"

    def test_base_plus_override_precedence(self):
        # override beats catalog beats default
        out = resolve_ui_language(
            {"_base": "es", "next_button": "CUSTOM"}, self.DEFAULTS
        )
        assert out["next_button"] == "CUSTOM"
        # a catalog key not overridden comes from the catalog
        assert out["html_dir"] == "ltr"

    def test_unknown_base_falls_back_to_defaults(self):
        out = resolve_ui_language({"_base": "zz"}, self.DEFAULTS)
        assert out["next_button"] == "Next"

    def test_unexpected_type_ignored(self, caplog):
        with caplog.at_level("WARNING"):
            out = resolve_ui_language(123, self.DEFAULTS)
        assert out["next_button"] == "Next"


class TestAvailableCodes:
    def test_ships_expected_languages(self):
        codes = available_language_codes()
        for expected in ["es", "ar", "fr", "de", "pt", "zh", "hi", "ja", "ru", "ko"]:
            assert expected in codes, f"missing bundled catalog: {expected}"


class TestCatalogIntegrity:
    """Drift guards: keep defaults, whitelist, and all catalogs in lockstep."""

    @pytest.mark.parametrize("code", sorted(available_language_codes()))
    def test_catalog_keys_match_whitelist_exactly(self, code):
        # load_catalog filters to the whitelist, so a mismatch means the raw
        # file is missing a key or carries an unknown one. Read raw to catch
        # dropped keys too.
        import yaml
        from potato.server_utils.i18n import CATALOG_DIR

        raw = yaml.safe_load((CATALOG_DIR / f"{code}.yaml").read_text(encoding="utf-8"))
        missing = WHITELIST - set(raw.keys())
        extra = set(raw.keys()) - WHITELIST
        assert not missing, f"{code}.yaml missing keys: {sorted(missing)}"
        assert not extra, f"{code}.yaml has non-whitelisted keys: {sorted(extra)}"

    @pytest.mark.parametrize("code", sorted(available_language_codes()))
    def test_placeholders_preserved(self, code):
        cat = load_catalog(code)
        for key, expected_tokens in PLACEHOLDER_KEYS.items():
            got = set(re.findall(r"\{(\w+)\}", cat[key]))
            assert got == expected_tokens, (
                f"{code}.yaml {key}: placeholders {got} != {expected_tokens}"
            )

    @pytest.mark.parametrize("code", sorted(available_language_codes()))
    def test_direction_is_valid(self, code):
        cat = load_catalog(code)
        assert cat["html_dir"] in ("ltr", "rtl")
        assert cat["html_lang"] == code

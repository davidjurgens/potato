"""
Unit tests for soft suggest-on-create (Phase 2 #1):
`derive_code_name` (name-from-selection) and `similar_code_names`
(near-duplicate detection cutoff). Pure functions — no DB/server.
"""

from potato.codebook.similar import derive_code_name, similar_code_names


class TestDeriveCodeName:
    def test_collapses_whitespace_and_trims(self):
        assert derive_code_name("  the   cost   is  high \n") \
            == "the cost is high"

    def test_short_text_unchanged(self):
        assert derive_code_name("access barriers") == "access barriers"

    def test_caps_at_word_boundary(self):
        text = "patients report that the cost of insulin is the single " \
               "biggest barrier to adherence over time"
        out = derive_code_name(text, cap=40)
        assert len(out) <= 40
        assert not out.endswith(" ")
        assert " " in out                       # cut on a word boundary
        assert text.startswith(out)

    def test_empty(self):
        assert derive_code_name("") == ""
        assert derive_code_name("   ") == ""


class TestSimilarCodeNames:
    NAMES = ["cost concerns", "access barriers", "provider trust",
             "insurance gaps"]

    def test_near_duplicate_found(self):
        assert "cost concerns" in similar_code_names(
            self.NAMES, "cost concern")

    def test_case_and_space_insensitive_exact_first(self):
        out = similar_code_names(self.NAMES, "  COST   Concerns ")
        assert out and out[0] == "cost concerns"

    def test_dissimilar_excluded(self):
        # topically related but lexically distant -> not a match
        assert similar_code_names(self.NAMES, "telehealth") == []

    def test_empty_proposed_returns_nothing(self):
        assert similar_code_names(self.NAMES, "") == []
        assert similar_code_names(self.NAMES, "   ") == []

    def test_no_existing_codes(self):
        assert similar_code_names([], "cost concerns") == []

    def test_ranked_best_first_and_capped(self):
        names = ["cost", "costs", "cost concern", "cost concerns",
                 "cost worries", "expense"]
        out = similar_code_names(names, "cost concerns", n=3)
        assert len(out) <= 3
        assert out[0] == "cost concerns"

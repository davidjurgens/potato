"""Unit tests for Boundary Lab probe generation (potato/boundary/generator.py)."""

import pytest

from potato.boundary.config import BoundaryConfig, parse_boundary_config
from potato.boundary.generator import (
    KIND_FLIP,
    KIND_INVARIANCE,
    ProbeGenerator,
    generate_rule_probes,
    make_probe_id,
)


class TestParseBoundaryConfig:
    def test_disabled_by_default(self):
        assert parse_boundary_config({}).enabled is False

    def test_parses_block(self):
        config = {
            "boundary_probing": {
                "enabled": True,
                "schema": "politeness",
                "probes_per_item": 4,
                "sources": ["precomputed", "rules"],
                "rationale_on_flip": False,
            }
        }
        bc = parse_boundary_config(config)
        assert bc.enabled is True
        assert bc.schema == "politeness"
        assert bc.probes_per_item == 4
        assert bc.sources == ["precomputed", "rules"]
        assert bc.rationale_on_flip is False

    def test_defaults_schema_to_first_radio(self):
        config = {
            "boundary_probing": {"enabled": True},
            "annotation_schemes": [
                {"annotation_type": "span", "name": "spans"},
                {"annotation_type": "radio", "name": "sentiment"},
            ],
        }
        assert parse_boundary_config(config).schema == "sentiment"

    def test_unknown_sources_dropped(self):
        config = {"boundary_probing": {"enabled": True, "sources": ["rules", "magic"]}}
        assert parse_boundary_config(config).sources == ["rules"]

    def test_probes_per_item_floor(self):
        config = {"boundary_probing": {"enabled": True, "probes_per_item": 0}}
        assert parse_boundary_config(config).probes_per_item == 1


class TestProbeId:
    def test_stable(self):
        a = make_probe_id("i1", "s", "Polite", "text one")
        b = make_probe_id("i1", "s", "Polite", "text one")
        assert a == b

    def test_distinct_per_text_and_label(self):
        base = make_probe_id("i1", "s", "Polite", "text one")
        assert make_probe_id("i1", "s", "Polite", "text two") != base
        assert make_probe_id("i1", "s", "Impolite", "text one") != base


class TestRuleProbes:
    def test_generates_flip_and_invariance(self):
        text = "Please send me the report. I can't find it and I'm very frustrated!"
        probes = generate_rule_probes(text, n_flip=2, n_invariance=1)
        kinds = [k for _, k, _ in probes]
        assert kinds.count(KIND_FLIP) == 2
        assert kinds.count(KIND_INVARIANCE) == 1

    def test_all_probes_differ_from_original(self):
        text = "Please review this very carefully. Don't rush it!"
        for new_text, _, _ in generate_rule_probes(text, 3, 2):
            assert new_text != text
            assert new_text.strip()

    def test_politeness_toggle_removes_please(self):
        probes = generate_rule_probes("Please close the door.", 1, 0)
        assert probes, "expected at least one flip probe"
        assert "please" not in probes[0][0].lower()

    def test_politeness_toggle_adds_please(self):
        probes = generate_rule_probes("Close the door.", 1, 0)
        assert probes
        assert probes[0][0].lower().startswith("please ")

    def test_contraction_invariance(self):
        probes = generate_rule_probes("I can't attend the meeting.", 0, 1)
        assert probes
        text, kind, _ = probes[0]
        assert kind == KIND_INVARIANCE
        assert "cannot" in text

    def test_handles_text_with_no_applicable_transforms(self):
        # No aux verbs, intensifiers, contractions, greetings, or punctuation
        probes = generate_rule_probes("xyzzy plugh", 3, 2)
        assert isinstance(probes, list)  # must not raise; may be empty or partial


class TestProbeGeneratorTiers:
    def _generator(self, sources, probes_per_item=3):
        config = {"boundary_probing": {
            "enabled": True, "schema": "s", "sources": sources,
            "probes_per_item": probes_per_item,
        }}
        bc = parse_boundary_config(config)
        return ProbeGenerator(config, bc)

    def test_precomputed_takes_priority(self):
        gen = self._generator(["precomputed", "rules"])
        item_data = {"counterfactuals": [
            {"text": "variant one", "kind": "flip", "edit_hint": "h1"},
            {"text": "variant two", "kind": "flip"},
            {"text": "variant three", "kind": "invariance"},
        ]}
        probes = gen.generate("i1", "s", "Polite", ["Polite", "Impolite"],
                              "Please send the report.", item_data=item_data)
        assert len(probes) == 3
        assert all(p.source == "precomputed" for p in probes)
        # Flips first, invariance last
        assert [p.kind for p in probes] == [KIND_FLIP, KIND_FLIP, KIND_INVARIANCE]
        assert probes[0].original_text == "Please send the report."

    def test_rules_fill_gaps_left_by_precomputed(self):
        gen = self._generator(["precomputed", "rules"])
        item_data = {"counterfactuals": [{"text": "only one flip", "kind": "flip"}]}
        probes = gen.generate("i1", "s", "Polite", ["Polite", "Impolite"],
                              "Please send the report. I can't wait!",
                              item_data=item_data)
        sources = {p.source for p in probes}
        assert "precomputed" in sources
        assert "rules" in sources

    def test_rules_only(self):
        gen = self._generator(["rules"])
        probes = gen.generate("i1", "s", "Polite", ["Polite", "Impolite"],
                              "Please send the report. I can't wait!")
        assert probes
        assert all(p.source == "rules" for p in probes)

    def test_malformed_precomputed_entries_skipped(self):
        gen = self._generator(["precomputed"])
        item_data = {"counterfactuals": [
            "not a dict",
            {"kind": "flip"},                      # missing text
            {"text": "ok", "kind": "bogus_kind"},  # bad kind
            {"text": "good variant", "kind": "flip"},
        ]}
        probes = gen.generate("i1", "s", "Polite", ["Polite", "Impolite"],
                              "Some text.", item_data=item_data)
        assert [p.text for p in probes] == ["good variant"]

    def test_llm_tier_skipped_without_endpoint(self):
        # No ai_support configured -> llm tier contributes nothing, rules fill in.
        gen = self._generator(["llm", "rules"])
        probes = gen.generate("i1", "s", "Polite", ["Polite", "Impolite"],
                              "Please send the report.")
        assert all(p.source == "rules" for p in probes)

    def test_respects_probe_budget(self):
        gen = self._generator(["precomputed"], probes_per_item=2)
        item_data = {"counterfactuals": [
            {"text": f"variant {i}", "kind": "flip"} for i in range(5)
        ]}
        probes = gen.generate("i1", "s", "Polite", ["Polite", "Impolite"],
                              "Some text.", item_data=item_data)
        # budget 2 with include_invariance -> 1 flip slot + 1 unfilled invariance slot
        assert len(probes) <= 2

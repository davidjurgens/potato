"""
Unit tests for server-side transcript binding.

This is the layer that lets the transcript *schemas* — which only see the
instance record client-side — accept the same formats the ``audio_dialogue``
display does. It normalizes the fields those schemes are configured to read and
attaches the result under ``_transcripts``.

The invariant that matters most: the original field is never replaced and the
stored record is never mutated. Annotations and exports have to keep seeing
exactly the data the user supplied.
"""

import pytest

from potato.server_utils.transcripts.binding import (
    INDEX_KEY,
    build_index,
    collect_bindings,
    enrich_record,
)

SRT = """1
00:00:00,000 --> 00:00:02,400
Alice: Good morning.

2
00:00:02,400 --> 00:00:05,000
Bob: Morning!
"""


class TestCollectBindings:
    def test_speech_transcript_default_key(self):
        config = {"annotation_schemes": [
            {"annotation_type": "speech_transcript", "name": "t"},
        ]}
        assert [b["field"] for b in collect_bindings(config)] == ["segments"]

    def test_speech_transcript_custom_key(self):
        config = {"annotation_schemes": [
            {"annotation_type": "speech_transcript", "name": "t",
             "segments_key": "asr_output"},
        ]}
        assert [b["field"] for b in collect_bindings(config)] == ["asr_output"]

    def test_voice_interaction_default_key(self):
        config = {"annotation_schemes": [
            {"annotation_type": "voice_interaction", "name": "v"},
        ]}
        assert [b["field"] for b in collect_bindings(config)] == ["turns"]

    def test_audio_dialogue_display_field(self):
        config = {"instance_display": {"fields": [
            {"key": "conversation", "type": "audio_dialogue"},
        ]}}
        assert [b["field"] for b in collect_bindings(config)] == ["conversation"]

    def test_scheme_key_overrides_are_carried(self):
        config = {"annotation_schemes": [
            {"annotation_type": "voice_interaction", "name": "v",
             "speaker_key": "role", "turns_key": "dialogue"},
        ]}
        binding = collect_bindings(config)[0]
        assert binding["field"] == "dialogue"
        assert binding["speaker_key"] == "role"

    def test_unrelated_schemes_ignored(self):
        config = {"annotation_schemes": [
            {"annotation_type": "radio", "name": "sentiment"},
            {"annotation_type": "span", "name": "entities"},
        ]}
        assert collect_bindings(config) == []

    def test_duplicate_fields_collapse(self):
        config = {
            "annotation_schemes": [
                {"annotation_type": "voice_interaction", "name": "v",
                 "turns_key": "conversation"},
            ],
            "instance_display": {"fields": [
                {"key": "conversation", "type": "audio_dialogue"},
            ]},
        }
        assert len(collect_bindings(config)) == 1

    def test_empty_config(self):
        assert collect_bindings({}) == []

    def test_malformed_entries_do_not_raise(self):
        config = {
            "annotation_schemes": ["not a dict", None],
            "instance_display": {"fields": [None, {"type": "audio_dialogue"}]},
        }
        assert collect_bindings(config) == []


class TestTieredSeedingIsOptIn:
    """Tiered annotation only binds a transcript when one is named."""

    def test_not_bound_by_default(self):
        config = {"annotation_schemes": [
            {"annotation_type": "tiered_annotation", "name": "t",
             "tiers": [{"name": "utterance"}]},
        ]}
        assert collect_bindings(config) == []

    def test_bound_when_transcript_field_set(self):
        config = {"annotation_schemes": [
            {"annotation_type": "tiered_annotation", "name": "t",
             "transcript_field": "asr", "tiers": [{"name": "utterance"}]},
        ]}
        assert [b["field"] for b in collect_bindings(config)] == ["asr"]

    def test_index_built_for_seeding(self):
        config = {"annotation_schemes": [
            {"annotation_type": "tiered_annotation", "name": "t",
             "transcript_field": "asr", "tiers": [{"name": "utterance"}]},
        ]}
        out = enrich_record({"asr": SRT}, config)
        turns = out[INDEX_KEY]["asr"]["turns"]
        assert [t["text"] for t in turns] == ["Good morning.", "Morning!"]


class TestTieredSchemaConfig:
    """The tier named for seeding has to exist, or the config is wrong."""

    def _scheme(self, **extra):
        scheme = {
            "annotation_type": "tiered_annotation",
            "name": "tiers",
            "description": "d",
            "tiers": [
                {"name": "utterance", "labels": [{"name": "speech", "color": "#abc"}]},
                {"name": "notes"},
            ],
        }
        scheme.update(extra)
        return scheme

    def test_unknown_transcript_tier_rejected(self):
        from potato.server_utils.schemas.tiered_annotation import (
            generate_tiered_annotation_layout,
        )

        html, _keys = generate_tiered_annotation_layout(
            self._scheme(transcript_field="asr", transcript_tier="nonexistent")
        )
        # safe_generate_layout turns the error into a visible message rather
        # than a traceback, so assert the config did not silently pass.
        assert "nonexistent" in html

    def test_defaults_to_first_tier(self):
        from potato.server_utils.schemas.tiered_annotation import (
            generate_tiered_annotation_layout,
        )

        html, _keys = generate_tiered_annotation_layout(
            self._scheme(transcript_field="asr")
        )
        assert '"transcriptTier": "utterance"' in html
        assert '"transcriptField": "asr"' in html

    def test_absent_when_not_configured(self):
        from potato.server_utils.schemas.tiered_annotation import (
            generate_tiered_annotation_layout,
        )

        html, _keys = generate_tiered_annotation_layout(self._scheme())
        assert '"transcriptField": null' in html


class TestBuildIndex:
    BINDINGS = [{
        "field": "segments", "audio_key": "audio", "turns_key": "turns",
        "speaker_key": "speaker", "text_key": "text",
    }]

    def test_normalizes_srt_string(self):
        index = build_index({"segments": SRT}, self.BINDINGS)
        assert [t["speaker"] for t in index["segments"]["turns"]] == ["Alice", "Bob"]

    def test_normalizes_native_rows(self):
        record = {"segments": [{"start": 0, "end": 1, "text": "hi", "speaker": "A"}]}
        index = build_index(record, self.BINDINGS)
        assert index["segments"]["turns"][0]["text"] == "hi"

    def test_missing_field_skipped(self):
        assert build_index({"other": "x"}, self.BINDINGS) == {}

    def test_uninterpretable_field_does_not_raise(self):
        # An int is not a transcript; the page must still render.
        index = build_index({"segments": 42}, self.BINDINGS)
        assert index == {}


class TestEnrichRecord:
    CONFIG = {"annotation_schemes": [
        {"annotation_type": "speech_transcript", "name": "t"},
    ]}

    def test_attaches_index(self):
        record = {"id": "a1", "segments": SRT}
        out = enrich_record(record, self.CONFIG)
        assert INDEX_KEY in out
        assert len(out[INDEX_KEY]["segments"]["turns"]) == 2

    def test_original_field_untouched(self):
        record = {"id": "a1", "segments": SRT}
        out = enrich_record(record, self.CONFIG)
        assert out["segments"] == SRT

    def test_does_not_mutate_input(self):
        # The stored item data must never gain a rendering-only key.
        record = {"id": "a1", "segments": SRT}
        enrich_record(record, self.CONFIG)
        assert INDEX_KEY not in record

    def test_no_bindings_returns_same_object(self):
        record = {"id": "a1", "text": "hello"}
        assert enrich_record(record, {"annotation_schemes": []}) is record

    def test_nothing_normalized_returns_same_object(self):
        record = {"id": "a1", "text": "hello"}
        assert enrich_record(record, self.CONFIG) is record

    def test_non_dict_record_passes_through(self):
        assert enrich_record("just a string", self.CONFIG) == "just a string"

    @pytest.mark.parametrize("payload,expected_turns", [
        ({"events": [{"tStartMs": 0, "dDurationMs": 1000,
                      "segs": [{"utf8": "hi"}]}]}, 1),
        ({"transcription": [{"offsets": {"from": 0, "to": 900}, "text": "hi"}]}, 1),
        ({"monologues": [{"speaker": 0, "elements": [
            {"type": "text", "value": "hi", "ts": 0, "end_ts": 0.4}]}]}, 1),
    ])
    def test_schemas_now_accept_display_only_formats(self, payload, expected_turns):
        # The point of the whole layer: formats that previously only worked in
        # the audio_dialogue display now reach the schemas too.
        out = enrich_record({"segments": payload}, self.CONFIG)
        assert len(out[INDEX_KEY]["segments"]["turns"]) == expected_turns

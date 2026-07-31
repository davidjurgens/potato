"""
Unit tests for the stdlib ConvoKit corpus reader.

The fixtures under ``tests/data/convokit/`` each isolate one axis of real-world
format variation; see ``generate_fixtures.py`` there for how they are built and
which real corpus motivated each one.
"""

import json
import os
import pickle
import zipfile

import pytest

from potato.convokit import (
    BIN_DELIM_L,
    BIN_DELIM_R,
    ConvoKitReadError,
    CorpusIndex,
    read_corpus,
    resolve_corpus_dir,
)
from potato.convokit.reader import iter_utterance_lines

FIXTURES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "convokit")

MODERN = os.path.join(FIXTURES, "mini-modern")
LEGACY = os.path.join(FIXTURES, "mini-legacy")
BIN = os.path.join(FIXTURES, "mini-bin")
BROKEN = os.path.join(FIXTURES, "mini-broken")
UNDERSCORE = os.path.join(FIXTURES, "mini-underscore")
MODERN_ZIP = os.path.join(FIXTURES, "mini-modern.zip")


# Stand-ins for the numpy types real corpora store in their pickle sidecars.
# Module level because pickle cannot serialize locally-defined classes.
class FakeNumpyScalar:
    """Duck-types a numpy scalar: exposes .item()."""

    def item(self):
        return 13


class FakeNumpyArray:
    """Duck-types a numpy array: exposes .tolist()."""

    def tolist(self):
        return [1, 2]


class Opaque:
    """Something with no faithful JSON form, e.g. a spacy Doc."""

    def __repr__(self):
        return "<opaque>"


class TestModernCorpus:
    def test_reads_all_utterances_and_conversations(self):
        corpus = read_corpus(MODERN)
        assert len(corpus.utterances) == 6
        assert set(corpus.conversations) == {"c0", "d0"}
        assert corpus.conversations["c0"].utterance_ids == ["c0", "c1", "c2", "c3"]
        assert corpus.conversations["d0"].utterance_ids == ["d0", "d1"]
        assert corpus.legacy is False

    def test_core_utterance_fields(self):
        corpus = read_corpus(MODERN)
        utt = corpus.utterances["c1"]
        assert utt.speaker == "bob"
        assert utt.conversation_id == "c0"
        assert utt.reply_to == "c0"
        assert utt.timestamp == 1200.0
        assert utt.text.startswith("I don't think")
        assert utt.file_index == 1

    def test_root_utterance_has_no_reply_to(self):
        corpus = read_corpus(MODERN)
        assert corpus.utterances["c0"].reply_to is None

    def test_conversation_metadata_is_unwrapped(self):
        """conversations.json values may be {"meta": ...} or the meta dict itself."""
        corpus = read_corpus(MODERN)
        assert corpus.conversations["c0"].meta["page_title"] == "Talk:Example"
        assert corpus.conversations["c0"].meta["derailed"] is False
        # d0 uses the bare form.
        assert corpus.conversations["d0"].meta["page_title"] == "Talk:Another"
        assert corpus.conversations["d0"].meta["derailed"] is True

    def test_speaker_metadata_is_unwrapped_both_forms(self):
        corpus = read_corpus(MODERN)
        assert corpus.speakers["alice"] == {"editor_since": 2004}   # wrapped
        assert corpus.speakers["bob"] == {"editor_since": 2011}     # bare

    def test_missing_speaker_is_synthesized_with_a_warning(self):
        corpus = read_corpus(MODERN)
        assert corpus.speakers["erin"] == {}
        assert any("erin" in w for w in corpus.warnings)

    def test_corpus_metadata(self):
        corpus = read_corpus(MODERN)
        assert corpus.meta["source"] == "synthetic"
        assert corpus.version == 3

    def test_utterances_of_helper(self):
        corpus = read_corpus(MODERN)
        texts = [u.id for u in corpus.utterances_of("c0")]
        assert texts == ["c0", "c1", "c2", "c3"]


class TestDroppedMetadata:
    def test_parsed_is_dropped_by_default(self):
        corpus = read_corpus(MODERN)
        assert "parsed" not in corpus.utterances["c0"].meta
        assert "parsed" in corpus.dropped_meta_fields

    def test_parsed_can_be_kept_explicitly(self):
        corpus = read_corpus(MODERN, keep_meta=["parsed"])
        assert "parsed" in corpus.utterances["c0"].meta

    def test_other_meta_survives(self):
        corpus = read_corpus(MODERN)
        meta = corpus.utterances["c0"].meta
        assert meta["is_section_header"] is True
        assert meta["stance"] == "support"

    def test_custom_drop_list(self):
        corpus = read_corpus(MODERN, drop_meta=["stance"])
        assert "stance" not in corpus.utterances["c0"].meta
        # parsed is no longer dropped, since drop_meta replaces the default
        assert "parsed" in corpus.utterances["c0"].meta


class TestLegacyFormat:
    def test_legacy_keys_are_detected(self):
        corpus = read_corpus(LEGACY)
        assert corpus.legacy is True
        assert any("legacy key names" in w for w in corpus.warnings)

    def test_user_maps_to_speaker_and_root_to_conversation_id(self):
        corpus = read_corpus(LEGACY)
        assert corpus.utterances["c1"].speaker == "bob"
        assert corpus.utterances["c1"].conversation_id == "c0"
        assert set(corpus.speakers) == {"alice", "bob", "carol"}

    def test_users_json_is_read(self):
        corpus = read_corpus(LEGACY)
        assert "alice" in corpus.speakers
        assert not any("No metadata for speaker" in w for w in corpus.warnings)

    def test_string_typed_index_is_normalized_to_lists(self):
        corpus = read_corpus(LEGACY)
        assert corpus.index.types_for("utterance", "Binary") == ["<class 'int'>"]
        assert corpus.index.legacy_speaker_key is True


class TestReplyToKeyVariants:
    def test_hyphenated_reply_to(self):
        corpus = read_corpus(MODERN)
        assert corpus.utterances["c3"].reply_to == "c1"

    def test_underscored_reply_to(self):
        """Reddit-derived corpora use reply_to; upstream has a workaround for it."""
        corpus = read_corpus(UNDERSCORE)
        assert corpus.utterances["u1"].reply_to == "u0"
        assert corpus.utterances["u0"].reply_to is None


class TestBinaryMetadata:
    def test_binary_fields_are_skipped_by_default(self):
        corpus = read_corpus(BIN)
        assert corpus.utterances["b0"].meta["Annotations"] is None
        assert "utterance.Annotations" in corpus.skipped_binary_fields
        assert any("pickle sidecar" in w for w in corpus.warnings)

    def test_non_binary_meta_alongside_it_survives(self):
        corpus = read_corpus(BIN)
        assert corpus.utterances["b0"].meta["Binary"] == 1

    def test_binary_fields_load_when_opted_in(self):
        corpus = read_corpus(BIN, load_binary_meta=True)
        assert corpus.utterances["b0"].meta["Annotations"] == {"annotator": "a1", "score": 3}
        assert corpus.utterances["b1"].meta["Annotations"] == {"annotator": "a2", "score": 5}
        assert corpus.skipped_binary_fields == []

    def test_index_reports_binary_fields(self):
        corpus = read_corpus(BIN)
        assert corpus.index.is_binary("utterance", "Annotations") is True
        assert corpus.index.is_binary("utterance", "Binary") is False
        assert corpus.index.binary_fields("utterance") == ["Annotations"]

    def test_out_of_range_marker_is_survivable(self, tmp_path):
        src = tmp_path / "corpus"
        src.mkdir()
        (src / "utterances.jsonl").write_text(
            json.dumps(
                {
                    "id": "z0",
                    "conversation_id": "z0",
                    "text": "hi",
                    "speaker": "a",
                    "meta": {"Blob": f"{BIN_DELIM_L}99{BIN_DELIM_R}"},
                    "reply-to": None,
                    "timestamp": 1,
                }
            )
            + "\n"
        )
        with open(src / "Blob-bin.p", "wb") as f:
            pickle.dump(["only-one"], f)

        corpus = read_corpus(str(src), load_binary_meta=True)
        assert corpus.utterances["z0"].meta["Blob"] is None
        assert any("out of range" in w for w in corpus.warnings)

    def test_unpickled_values_are_json_serializable(self, tmp_path):
        """Unpickled meta must survive json.dumps — real corpora store numpy types.

        wikipedia-politeness-corpus stores its per-annotator ratings as
        numpy.int64, which json.dumps rejects far from the cause.
        """
        src = tmp_path / "corpus"
        src.mkdir()
        (src / "utterances.jsonl").write_text(
            json.dumps(
                {
                    "id": "z0",
                    "conversation_id": "z0",
                    "text": "hi",
                    "speaker": "a",
                    "meta": {"Ratings": f"{BIN_DELIM_L}0{BIN_DELIM_R}"},
                    "reply-to": None,
                    "timestamp": 1,
                }
            )
            + "\n"
        )
        with open(src / "Ratings-bin.p", "wb") as f:
            pickle.dump(
                [{"w1": FakeNumpyScalar(), "w2": FakeNumpyArray(), "w3": Opaque()}], f
            )

        corpus = read_corpus(str(src), load_binary_meta=True)
        ratings = corpus.utterances["z0"].meta["Ratings"]
        assert ratings == {"w1": 13, "w2": [1, 2], "w3": "<opaque>"}
        json.dumps(ratings)   # the actual guarantee

    def test_missing_sidecar_is_survivable(self, tmp_path):
        src = tmp_path / "corpus"
        src.mkdir()
        (src / "utterances.jsonl").write_text(
            json.dumps(
                {
                    "id": "z0",
                    "conversation_id": "z0",
                    "text": "hi",
                    "speaker": "a",
                    "meta": {"Gone": f"{BIN_DELIM_L}0{BIN_DELIM_R}"},
                    "reply-to": None,
                    "timestamp": 1,
                }
            )
            + "\n"
        )
        corpus = read_corpus(str(src), load_binary_meta=True)
        assert corpus.utterances["z0"].meta["Gone"] is None
        assert any("No binary sidecar" in w for w in corpus.warnings)


class TestInfoOverlays:
    def test_info_files_are_not_loaded_unless_requested(self):
        corpus = read_corpus(MODERN)
        assert "extra_score" not in corpus.utterances["c1"].meta

    def test_info_overlay_merges_into_utterance_meta(self):
        corpus = read_corpus(MODERN, info_fields=["extra_score"])
        assert corpus.utterances["c1"].meta["extra_score"] == 0.9
        assert corpus.utterances["c3"].meta["extra_score"] == 0.1

    def test_unmatched_ids_are_counted_not_fatal(self):
        corpus = read_corpus(MODERN, info_fields=["extra_score"])
        assert any("matched no object" in w for w in corpus.warnings)

    def test_explicit_object_type_is_honored(self):
        corpus = read_corpus(MODERN, info_fields=["extra_score:utterance"])
        assert corpus.utterances["c1"].meta["extra_score"] == 0.9

    def test_unknown_object_type_warns(self):
        corpus = read_corpus(MODERN, info_fields=["extra_score:banana"])
        assert any("Unknown object type" in w for w in corpus.warnings)

    def test_missing_info_file_warns(self):
        corpus = read_corpus(MODERN, info_fields=["nope"])
        assert any("No info file" in w for w in corpus.warnings)


class TestBrokenCorpus:
    def test_reads_despite_everything(self):
        corpus = read_corpus(BROKEN)
        assert set(corpus.utterances) == {"x0", "x1", "x2"}

    def test_duplicate_id_keeps_the_first(self):
        corpus = read_corpus(BROKEN)
        assert corpus.utterances["x0"].text == "Orphan reply."
        assert any("Duplicate utterance id" in w for w in corpus.warnings)

    def test_null_timestamp_becomes_none(self):
        corpus = read_corpus(BROKEN)
        assert corpus.utterances["x0"].timestamp is None
        assert corpus.utterances["x2"].timestamp == 5.0

    def test_dangling_reply_to_is_preserved_verbatim(self):
        """Resolving dangling parents is the item builder's job, not the reader's."""
        corpus = read_corpus(BROKEN)
        assert corpus.utterances["x0"].reply_to == "missing"

    def test_missing_speakers_file_synthesizes_all_speakers(self):
        corpus = read_corpus(BROKEN)
        assert set(corpus.speakers) == {"alice", "bob"}

    def test_missing_index_is_tolerated(self):
        corpus = read_corpus(BROKEN)
        assert corpus.index.present is False
        assert corpus.index.types_for("utterance", "anything") == []


class TestResolveCorpusDir:
    def test_direct_corpus_directory(self):
        assert resolve_corpus_dir(MODERN) == MODERN

    def test_parent_directory_with_one_corpus(self, tmp_path):
        parent = tmp_path / "wrapper"
        parent.mkdir()
        inner = parent / "mini-modern"
        inner.mkdir()
        (inner / "utterances.jsonl").write_text("{}\n")
        assert resolve_corpus_dir(str(parent)) == str(inner)

    def test_parent_with_several_corpora_is_ambiguous(self, tmp_path):
        parent = tmp_path / "wrapper"
        parent.mkdir()
        for name in ("a", "b"):
            inner = parent / name
            inner.mkdir()
            (inner / "utterances.jsonl").write_text("{}\n")
        with pytest.raises(ConvoKitReadError, match="contains 2 corpus directories"):
            resolve_corpus_dir(str(parent))

    def test_directory_without_a_corpus(self, tmp_path):
        with pytest.raises(ConvoKitReadError, match="does not look like a ConvoKit corpus"):
            resolve_corpus_dir(str(tmp_path))

    def test_missing_path(self, tmp_path):
        with pytest.raises(ConvoKitReadError, match="No such corpus path"):
            resolve_corpus_dir(str(tmp_path / "nope"))

    def test_zip_input(self, tmp_path):
        corpus = read_corpus(MODERN_ZIP, name="mini-modern")
        assert len(corpus.utterances) == 6
        assert corpus.name == "mini-modern"


class TestZipSafety:
    def _corpus_member(self):
        return json.dumps(
            {
                "id": "a",
                "conversation_id": "a",
                "text": "t",
                "speaker": "s",
                "meta": {},
                "reply-to": None,
                "timestamp": 1,
            }
        )

    def test_path_traversal_member_is_rejected(self, tmp_path):
        bad = tmp_path / "bad.zip"
        with zipfile.ZipFile(bad, "w") as zf:
            zf.writestr("../escaped/utterances.jsonl", self._corpus_member())
        with pytest.raises(ConvoKitReadError, match="path traversal"):
            resolve_corpus_dir(str(bad), extract_to=str(tmp_path / "out"))

    def test_absolute_member_is_rejected(self, tmp_path):
        bad = tmp_path / "bad.zip"
        with zipfile.ZipFile(bad, "w") as zf:
            zf.writestr("/etc/utterances.jsonl", self._corpus_member())
        with pytest.raises(ConvoKitReadError, match="absolute member path"):
            resolve_corpus_dir(str(bad), extract_to=str(tmp_path / "out"))

    def test_symlink_member_is_rejected(self, tmp_path):
        bad = tmp_path / "bad.zip"
        with zipfile.ZipFile(bad, "w") as zf:
            info = zipfile.ZipInfo("link")
            info.external_attr = (0xA1FF) << 16   # symlink mode bits
            zf.writestr(info, "/etc/passwd")
        with pytest.raises(ConvoKitReadError, match="symlink member"):
            resolve_corpus_dir(str(bad), extract_to=str(tmp_path / "out"))

    def test_zip_bomb_is_rejected(self, tmp_path, monkeypatch):
        from potato.convokit import reader as reader_mod

        monkeypatch.setattr(reader_mod, "MAX_ZIP_UNCOMPRESSED_BYTES", 10)
        bad = tmp_path / "big.zip"
        with zipfile.ZipFile(bad, "w") as zf:
            zf.writestr("mini/utterances.jsonl", "x" * 1000)
        with pytest.raises(ConvoKitReadError, match="uncompressed size exceeds"):
            resolve_corpus_dir(str(bad), extract_to=str(tmp_path / "out"))


class TestMaxConversations:
    def test_bounds_the_conversation_count(self):
        corpus = read_corpus(MODERN, max_conversations=1)
        assert set(corpus.conversations) == {"c0"}
        assert set(corpus.utterances) == {"c0", "c1", "c2", "c3"}


class TestIterUtteranceLines:
    def test_streams_jsonl(self):
        rows = list(iter_utterance_lines(os.path.join(MODERN, "utterances.jsonl")))
        assert len(rows) == 6
        assert rows[0]["id"] == "c0"

    def test_blank_lines_are_skipped(self, tmp_path):
        path = tmp_path / "utterances.jsonl"
        path.write_text('{"id": "a"}\n\n{"id": "b"}\n')
        assert [r["id"] for r in iter_utterance_lines(str(path))] == ["a", "b"]

    def test_malformed_line_names_the_line_number(self, tmp_path):
        path = tmp_path / "utterances.jsonl"
        path.write_text('{"id": "a"}\nnot json\n')
        with pytest.raises(ConvoKitReadError, match=r":2:"):
            list(iter_utterance_lines(str(path)))

    def test_json_array_variant(self, tmp_path):
        path = tmp_path / "utterances.json"
        path.write_text(json.dumps([{"id": "a"}, {"id": "b"}]))
        assert [r["id"] for r in iter_utterance_lines(str(path))] == ["a", "b"]


class TestCorpusIndex:
    def test_normalizes_string_and_list_values(self):
        idx = CorpusIndex.from_dict(
            {
                "utterances-index": {"a": "<class 'int'>", "b": ["<class 'str'>"]},
                "speakers-index": {},
                "conversations-index": {},
                "overall-index": {},
                "version": 4,
            }
        )
        assert idx.types_for("utterance", "a") == ["<class 'int'>"]
        assert idx.types_for("utterance", "b") == ["<class 'str'>"]
        assert idx.version == 4

    def test_users_index_alias(self):
        idx = CorpusIndex.from_dict({"users-index": {"gender": "<class 'str'>"}})
        assert idx.types_for("speaker", "gender") == ["<class 'str'>"]
        assert idx.legacy_speaker_key is True

    def test_binary_detection_uses_the_first_entry(self):
        idx = CorpusIndex.from_dict(
            {"utterances-index": {"blob": ["bin", "<class 'list'>"]}}
        )
        assert idx.is_binary("utterance", "blob") is True

    def test_round_trips_to_modern_list_form(self):
        idx = CorpusIndex.from_dict({"utterances-index": {"a": "<class 'int'>"}, "version": 2})
        out = idx.to_dict()
        assert out["utterances-index"] == {"a": ["<class 'int'>"]}
        assert out["version"] == 2
        assert "speakers-index" in out

    def test_legacy_speaker_key_on_write(self):
        idx = CorpusIndex.from_dict({"users-index": {}})
        assert "users-index" in idx.to_dict(legacy_speaker_key=True)
        assert "speakers-index" in idx.to_dict(legacy_speaker_key=False)

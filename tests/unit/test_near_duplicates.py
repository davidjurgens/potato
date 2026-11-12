"""
Near-duplicate detection.

Dedup is described as surprisingly fiddly and re-hand-rolled per project, and
the concrete case named is consecutive video frames: a thousand items that are
one item, eating a thousand annotations' worth of budget and inflating
agreement, because two annotators trivially agree about the same picture shown
twice.

The choice of measure is the whole design, and the tests that matter are the
ones that pin it. Embeddings put two frames of the same scene close together
*by design* -- that is what makes them good at "find me more like this" and
exactly wrong for "is this the same picture". A perceptual hash compares
pixel gradients, so it survives re-encoding and brightness shifts while still
telling two different scenes apart.
"""

from __future__ import annotations

import pytest

from potato.curation import duplicates as dup

PIL = pytest.importorskip("PIL", reason="perceptual hashing needs Pillow")


def make_image(pattern, size=64):
    """A small image built from a callable(x, y) -> 0..255."""
    from PIL import Image

    img = Image.new("L", (size, size))
    img.putdata([pattern(x, y, size) for y in range(size) for x in range(size)])
    return img


# Patterns defined as a PROPORTION of the image, so the same pattern at two
# sizes really is the same picture rescaled. A fixed pixel period (x // 8)
# would give a different number of stripes at each size, and the two images
# would be genuinely different once downsampled to the hash grid -- a test
# failure that looks like a hash defect and is an artefact of the fixture.
GRADIENT = lambda x, y, n=64: (x * 256) // n
STRIPES = lambda x, y, n=64: 255 if (x * 8 // n) % 2 else 0
BLOCKS = lambda x, y, n=64: 255 if ((x * 4 // n) + (y * 4 // n)) % 2 else 0


class TestHashing:
    def test_the_same_image_hashes_the_same(self):
        assert dup.dhash(make_image(GRADIENT)) == dup.dhash(make_image(GRADIENT))

    def test_different_images_hash_differently(self):
        assert dup.dhash(make_image(STRIPES)) != dup.dhash(make_image(BLOCKS))

    def test_a_brightness_shift_stays_near(self):
        """
        dHash encodes gradients, not absolute values. Re-encoding and exposure
        changes are exactly what a near-duplicate scan has to see through.
        """
        base = dup.dhash(make_image(STRIPES))
        brighter = dup.dhash(make_image(
            lambda x, y, n: min(255, STRIPES(x, y, n) + 20)))
        assert dup.hamming(base, brighter) <= dup.DEFAULT_MAX_DISTANCE

    def test_rescaling_stays_near(self):
        small = dup.dhash(make_image(STRIPES, size=32))
        large = dup.dhash(make_image(STRIPES, size=128))
        assert dup.hamming(small, large) <= dup.DEFAULT_MAX_DISTANCE

    def test_two_unrelated_images_are_far_apart(self):
        assert dup.hamming(dup.dhash(make_image(STRIPES)),
                           dup.dhash(make_image(BLOCKS))) > dup.DEFAULT_MAX_DISTANCE

    def test_hamming_counts_differing_bits(self):
        assert dup.hamming(0b1010, 0b1010) == 0
        assert dup.hamming(0b1010, 0b0101) == 4

    def test_an_unreadable_file_costs_its_own_row_not_the_scan(self, tmp_path):
        bad = tmp_path / "corrupt.png"
        bad.write_bytes(b"not an image at all")
        assert dup.dhash_path(str(bad)) is None
        assert dup.dhash_path(str(tmp_path / "missing.png")) is None


class TestGrouping:
    def test_identical_hashes_group(self):
        groups = dup.group_by_hash({"a": 0b1111, "b": 0b1111, "c": 0b0000},
                                   max_distance=1)
        assert len(groups) == 1
        assert groups[0].members == ["a", "b"]

    def test_a_singleton_is_not_a_group(self):
        assert dup.group_by_hash({"only": 0b1010}, max_distance=1) == []

    def test_grouping_is_transitive_along_a_chain(self):
        """
        A slow pan produces frames each close to the next and far from the
        first. Splitting that into overlapping pairs hands a reviewer the same
        frames several times.
        """
        groups = dup.group_by_hash(
            {"f0": 0b0000, "f1": 0b0001, "f2": 0b0011, "f3": 0b0111},
            max_distance=1)
        assert len(groups) == 1
        assert groups[0].members == ["f0", "f1", "f2", "f3"]

    def test_the_keeper_is_stable_across_runs(self):
        """
        An unstable keeper means re-running the scan proposes excluding a
        different item each time.
        """
        hashes = {"z": 0b1111, "a": 0b1111, "m": 0b1111}
        first = dup.group_by_hash(hashes, 0)[0].keeper
        second = dup.group_by_hash(dict(reversed(list(hashes.items()))), 0)[0].keeper
        assert first == second == "a"

    def test_the_biggest_group_comes_first(self):
        groups = dup.group_by_hash(
            {"a": 0, "b": 0, "c": 0, "x": 0b1111000011110000,
             "y": 0b1111000011110000}, max_distance=0)
        assert [g.size for g in groups] == [3, 2]

    def test_the_threshold_is_respected(self):
        hashes = {"a": 0b0000, "b": 0b0111}   # distance 3
        assert dup.group_by_hash(hashes, max_distance=2) == []
        assert len(dup.group_by_hash(hashes, max_distance=3)) == 1

    def test_the_method_is_recorded_on_the_group(self):
        """
        The two measures mean different things; a reviewer needs to know which
        one grouped what they are looking at.
        """
        assert dup.group_by_hash({"a": 0, "b": 0}, 0)[0].method == "phash"


class FakeIndex:
    def __init__(self, vectors):
        self._vectors = vectors

    def get(self, instance_id):
        return self._vectors.get(str(instance_id))


class TestEmbeddingMode:
    def test_near_identical_vectors_group(self):
        index = FakeIndex({"a": [1.0, 0.0], "b": [0.999, 0.01],
                           "far": [0.0, 1.0]})
        groups = dup.group_by_embedding(index, ["a", "b", "far"],
                                        min_similarity=0.99)
        assert len(groups) == 1
        assert groups[0].members == ["a", "b"]
        assert groups[0].method == "embedding"

    def test_the_default_threshold_is_far_above_a_retrieval_one(self):
        """
        At a typical retrieval threshold an index returns things that are
        merely RELATED. A duplicate group full of related items costs a
        reviewer more than no grouping at all.
        """
        assert dup.DEFAULT_MIN_SIMILARITY >= 0.95

    def test_related_but_not_duplicate_vectors_stay_apart(self):
        index = FakeIndex({"a": [1.0, 0.0], "related": [0.9, 0.44]})
        assert dup.group_by_embedding(
            index, ["a", "related"], dup.DEFAULT_MIN_SIMILARITY) == []

    def test_items_absent_from_the_index_are_skipped(self):
        index = FakeIndex({"a": [1.0, 0.0]})
        assert dup.group_by_embedding(index, ["a", "never_indexed"], 0.9) == []


class TestSummary:
    def test_it_counts_duplicates_not_group_members(self):
        """
        A group of three costs TWO wasted annotations, not three -- one of
        them is the item you meant to annotate.
        """
        groups = dup.group_by_hash({"a": 0, "b": 0, "c": 0}, 0)
        report = dup.summarize(groups, n_items=10)
        assert report["n_groups"] == 1
        assert report["n_duplicates"] == 2
        assert report["duplicate_rate"] == pytest.approx(0.2)
        assert report["largest_group"] == 3

    def test_the_note_names_both_costs(self):
        """Budget AND inflated agreement; the second is the one people miss."""
        report = dup.summarize(dup.group_by_hash({"a": 0, "b": 0}, 0), 4)
        assert "budget" in report["note"]
        assert "agreement" in report["note"]

    def test_a_clean_project_says_so_plainly(self):
        assert dup.summarize([], 10)["note"] == "No near-duplicates found."
        assert dup.summarize([], 10)["duplicate_rate"] == 0.0

    def test_no_items_does_not_divide_by_zero(self):
        assert dup.summarize([], 0)["duplicate_rate"] == 0.0


class FakeItem:
    def __init__(self, data):
        self._data = data

    def get_data(self):
        return self._data


class FakeISM:
    def __init__(self, items):
        self.items = items

    def iter_items(self):
        return list(self.items.items())


class TestProjectScan:
    @pytest.fixture
    def project(self, tmp_path):
        media = tmp_path / "media"
        media.mkdir()
        make_image(STRIPES).save(media / "frame1.png")
        make_image(STRIPES).save(media / "frame2.png")
        make_image(BLOCKS).save(media / "other.png")
        ism = FakeISM({
            "f1": FakeItem({"image_url": "/media/frame1.png"}),
            "f2": FakeItem({"image_url": "/media/frame2.png"}),
            "other": FakeItem({"image_url": "/media/other.png"}),
        })
        return ism, {"task_dir": str(tmp_path)}

    def test_duplicate_frames_are_found(self, project):
        ism, config = project
        report = dup.find_duplicates(ism, config)
        assert report["n_groups"] == 1
        assert report["groups"][0]["members"] == ["f1", "f2"]
        assert report["n_hashed"] == 3

    def test_a_project_with_no_hashable_items_says_so_loudly(self, tmp_path):
        """
        The dangerous failure. Reporting "no duplicates" for a project nothing
        could be read from would be believed, and the report is exactly the
        kind of thing people believe.
        """
        ism = FakeISM({"t1": FakeItem({"text": "just words"})})
        report = dup.find_duplicates(ism, {"task_dir": str(tmp_path)})
        assert report["n_groups"] == 0
        assert "NOT a finding of zero duplicates" in report["note"]

    def test_remote_urls_are_skipped_not_downloaded(self, tmp_path):
        """
        Downloading a dataset in order to deduplicate it turns a local scan
        into an unbounded network job nobody asked for.
        """
        ism = FakeISM({"r": FakeItem({"image_url": "https://example.org/a.png"})})
        report = dup.find_duplicates(ism, {"task_dir": str(tmp_path)})
        assert report["n_hashed"] == 0

    def test_embedding_mode_without_an_index_explains_itself(self, project):
        ism, config = project
        report = dup.find_duplicates(ism, config, method="embedding")
        assert report["n_groups"] == 0
        assert "curation index" in report["note"]

"""
Episode readers, the manifest, and the export conversion.

The failure this file is written against is a **frame/time mismatch**. Every
part of the pipeline has a plausible-looking answer when the frame rate is
wrong: the timeline draws, the phases land somewhere, the export writes rows.
Nothing errors, and the labels are silently attached to different frames than
the annotator saw. So the conversions are asserted against hand-computed frame
indices rather than against each other.
"""

import json
import math
import struct
from pathlib import Path

import pytest

from potato.episodes.models import (Episode, EpisodeError, Series, Stream,
                                    downsample, flatten_vector_column)
from potato.episodes import simple
from potato.episodes.registry import detect_format, list_episodes, read_episode


def write_manifest(directory: Path, **overrides):
    payload = {
        "episode_id": "ep_test",
        "fps": 20,
        "num_frames": 4,
        "instruction": "pick up the block",
        "streams": [{"name": "wrist", "url": "video/wrist.webm",
                     "kind": "wrist"}],
        "series": [{"name": "gripper", "unit": "m",
                    "values": [0.06, 0.03, 0.01, 0.06]}],
    }
    payload.update(overrides)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "episode.json").write_text(json.dumps(payload),
                                            encoding="utf-8")
    return directory


# ---------------------------------------------------------------------------
# The model
# ---------------------------------------------------------------------------

class TestEpisodeModel:
    def test_frames_and_seconds_round_trip(self):
        ep = Episode(episode_id="e", num_frames=100, fps=20.0)
        assert ep.seconds(40) == pytest.approx(2.0)
        assert ep.frame_at(2.0) == 40
        assert ep.duration == pytest.approx(5.0)

    def test_frame_at_rounds_rather_than_truncates(self):
        # A click at 1.999 s on a 1 fps episode means frame 2. Truncation would
        # place every boundary one frame early, consistently and invisibly.
        ep = Episode(episode_id="e", num_frames=10, fps=1.0)
        assert ep.frame_at(1.999) == 2
        assert ep.frame_at(1.4) == 1

    def test_frame_at_clamps_into_range(self):
        ep = Episode(episode_id="e", num_frames=10, fps=1.0)
        assert ep.frame_at(-5) == 0
        assert ep.frame_at(1000) == 9

    def test_a_ragged_series_is_reported_not_raised(self):
        # A log that dropped samples is still mostly usable; raising loses the
        # whole episode, and silence produces lanes that disagree about where
        # frame 400 is.
        ep = Episode(episode_id="e", num_frames=10, fps=1.0,
                     series=[Series(name="a", values=[1.0] * 7)])
        issues = ep.validate()
        assert any("7 samples" in i and "10 frames" in i for i in issues)

    def test_a_constant_series_still_has_a_drawable_range(self):
        # A gripper that never opens is a real and informative state. A
        # zero-height lane says nothing; a flat line in the middle says it.
        s = Series(name="g", values=[0.5] * 20)
        lo, hi = s.range()
        assert hi > lo

    def test_declared_bounds_win_over_the_data(self):
        s = Series(name="g", values=[0.1, 0.2], minimum=0.0, maximum=1.0)
        assert s.range() == (0.0, 1.0)

    def test_flatten_names_components_from_the_dataset(self):
        # `joint_0` tells an annotator nothing; `shoulder_pan` tells them where
        # to look.
        out = flatten_vector_column("state", [[1, 2], [3, 4]],
                                    names=["shoulder_pan", "elbow"])
        assert [s.name for s in out] == ["shoulder_pan", "elbow"]
        assert out[0].values == [1.0, 3.0]
        assert all(s.group == "state" for s in out)

    def test_flatten_falls_back_to_indices(self):
        out = flatten_vector_column("state", [[1, 2]])
        assert [s.name for s in out] == ["state[0]", "state[1]"]

    def test_a_short_row_becomes_nan_not_zero(self):
        out = flatten_vector_column("state", [[1, 2], [3]])
        assert math.isnan(out[1].values[1])


class TestDownsample:
    def test_short_series_are_untouched(self):
        assert downsample([1, 2, 3], 100) == [1.0, 2.0, 3.0]

    def test_a_spike_survives(self):
        # The whole point. A one-frame force spike is the most diagnostic
        # event in a manipulation log; plain striding drops it and averaging
        # buries it, and either way a collision becomes invisible in the very
        # lane drawn to show it.
        values = [0.0] * 1000
        values[500] = 9.9
        out = downsample(values, 100)
        assert max(out) == pytest.approx(9.9)

    def test_a_trough_survives_too(self):
        values = [1.0] * 1000
        values[500] = -4.0
        assert min(downsample(values, 100)) == pytest.approx(-4.0)

    def test_order_within_a_bucket_is_preserved(self):
        # A rising edge must not come back as a falling one.
        values = list(range(1000))
        out = downsample(values, 100)
        assert out == sorted(out)

    def test_the_result_is_near_the_requested_size(self):
        out = downsample(list(range(10000)), 200)
        assert 100 <= len(out) <= 220

    def test_an_all_nan_bucket_stays_nan(self):
        nan = float("nan")
        out = downsample([nan] * 200, 20)
        assert all(math.isnan(v) for v in out)


# ---------------------------------------------------------------------------
# The Potato manifest reader
# ---------------------------------------------------------------------------

class TestSimpleReader:
    def test_reads_a_manifest(self, tmp_path):
        directory = write_manifest(tmp_path / "ep")
        ep = simple.read(directory)
        assert ep.episode_id == "ep_test"
        assert ep.fps == 20
        assert ep.num_frames == 4
        assert ep.instruction.startswith("pick up")
        assert [s.name for s in ep.series] == ["gripper"]
        assert ep.streams[0].kind == "wrist"

    def test_frame_count_defaults_to_the_longest_series(self, tmp_path):
        # The frame count is a property of the data; repeating it in the
        # manifest is one more thing to get out of step.
        directory = write_manifest(tmp_path / "ep")
        payload = json.loads((directory / "episode.json").read_text())
        del payload["num_frames"]
        (directory / "episode.json").write_text(json.dumps(payload))
        assert simple.read(directory).num_frames == 4

    def test_relative_stream_urls_get_the_media_prefix(self, tmp_path):
        directory = write_manifest(tmp_path / "ep")
        ep = simple.read(directory, media_prefix="/media/episodes/ep")
        assert ep.streams[0].url == "/media/episodes/ep/video/wrist.webm"

    def test_absolute_urls_are_left_alone(self, tmp_path):
        # Prefixing one produces a URL that 404s in a way that looks like a
        # missing file rather than a mangled path.
        directory = write_manifest(
            tmp_path / "ep",
            streams=[{"name": "w", "url": "https://example.org/a.webm"},
                     {"name": "x", "url": "/media/other.webm"}])
        ep = simple.read(directory, media_prefix="/media/ep")
        assert ep.streams[0].url == "https://example.org/a.webm"
        assert ep.streams[1].url == "/media/other.webm"

    def test_a_non_numeric_sample_becomes_nan_not_zero(self, tmp_path):
        # A missing sample is not a measurement of zero, and the lane draws a
        # gap rather than a line through the origin.
        directory = write_manifest(
            tmp_path / "ep",
            series=[{"name": "g", "values": [1.0, None, "x", 2.0]}])
        values = simple.read(directory).series[0].values
        assert math.isnan(values[1]) and math.isnan(values[2])

    def test_malformed_json_names_the_file(self, tmp_path):
        directory = tmp_path / "ep"
        directory.mkdir()
        (directory / "episode.json").write_text("{not json")
        with pytest.raises(EpisodeError, match="episode.json"):
            simple.read(directory)

    def test_round_trips_through_write(self, tmp_path):
        directory = write_manifest(tmp_path / "ep")
        original = simple.read(directory)
        simple.write(original, tmp_path / "copy" / "episode.json")
        again = simple.read(tmp_path / "copy")
        assert again.num_frames == original.num_frames
        assert again.series[0].values == original.series[0].values


class TestRegistry:
    def test_detects_a_potato_manifest(self, tmp_path):
        assert detect_format(write_manifest(tmp_path / "ep")) == "potato_episode"

    def test_a_missing_path_says_so(self, tmp_path):
        with pytest.raises(EpisodeError, match="does not exist"):
            detect_format(tmp_path / "nope")

    def test_an_unrecognised_directory_lists_what_was_looked_for(self, tmp_path):
        (tmp_path / "empty").mkdir()
        with pytest.raises(EpisodeError, match="LeRobot"):
            detect_format(tmp_path / "empty")

    def test_a_single_episode_source_lists_one(self, tmp_path):
        assert list_episodes(write_manifest(tmp_path / "ep")) == [0]

    def test_read_episode_dispatches(self, tmp_path):
        ep = read_episode(write_manifest(tmp_path / "ep"))
        assert ep.source_format == "potato_episode"


# ---------------------------------------------------------------------------
# LeRobot
# ---------------------------------------------------------------------------

class TestLeRobot:
    def _dataset(self, tmp_path, chunks_size=1000, total=2):
        from potato.episodes import lerobot
        pq = pytest.importorskip("pyarrow.parquet")
        pa = pytest.importorskip("pyarrow")

        root = tmp_path / "ds"
        (root / "meta").mkdir(parents=True)
        (root / "meta" / "info.json").write_text(json.dumps({
            "fps": 20, "chunks_size": chunks_size, "total_episodes": total,
            "robot_type": "so100",
            "data_path": ("data/chunk-{episode_chunk:03d}/"
                          "episode_{episode_index:06d}.parquet"),
            "video_path": ("videos/chunk-{episode_chunk:03d}/{video_key}/"
                           "episode_{episode_index:06d}.mp4"),
            "features": {
                "observation.state": {"dtype": "float32", "shape": [2],
                                      "names": ["shoulder", "gripper"]},
                "action": {"dtype": "float32", "shape": [2]},
                "next.reward": {"dtype": "float32", "shape": [1]},
                "observation.images.wrist": {"dtype": "video",
                                             "shape": [120, 160, 3]},
            },
        }))
        (root / "meta" / "tasks.jsonl").write_text(
            json.dumps({"task_index": 0, "task": "pick the block"}) + "\n")

        for index in range(total):
            chunk = index // chunks_size
            data_dir = root / "data" / f"chunk-{chunk:03d}"
            data_dir.mkdir(parents=True, exist_ok=True)
            table = pa.table({
                "observation.state": [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]],
                "action": [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]],
                "next.reward": [0.0, 0.0, 1.0],
                "frame_index": [0, 1, 2],
                "task_index": [0, 0, 0],
            })
            pq.write_table(table, data_dir / f"episode_{index:06d}.parquet")

            video_dir = (root / "videos" / f"chunk-{chunk:03d}"
                         / "observation.images.wrist")
            video_dir.mkdir(parents=True, exist_ok=True)
            (video_dir / f"episode_{index:06d}.mp4").write_bytes(b"\x00")
        return root, lerobot

    def test_detects_and_reads(self, tmp_path):
        root, lerobot = self._dataset(tmp_path)
        assert lerobot.detect(root)
        assert detect_format(root) == "lerobot_v2"

        ep = lerobot.read(root, 0)
        assert ep.fps == 20
        assert ep.num_frames == 3
        assert ep.source_format == "lerobot_v2"

    def test_vector_columns_are_named_from_the_features(self, tmp_path):
        root, lerobot = self._dataset(tmp_path)
        names = [s.name for s in lerobot.read(root, 0).series]
        assert "shoulder" in names and "gripper" in names
        # No names declared for `action`, so it falls back to indices — honest
        # about not knowing rather than inventing labels.
        assert "action[0]" in names

    def test_index_columns_do_not_become_lanes(self, tmp_path):
        # `frame_index` is a straight line by construction and would waste the
        # only vertical space the annotator has.
        root, lerobot = self._dataset(tmp_path)
        names = [s.name for s in lerobot.read(root, 0).series]
        assert "frame_index" not in names
        assert "task_index" not in names

    def test_the_instruction_comes_from_tasks_jsonl(self, tmp_path):
        root, lerobot = self._dataset(tmp_path)
        assert lerobot.read(root, 0).instruction == "pick the block"

    def test_video_streams_are_relative_to_the_dataset(self, tmp_path):
        root, lerobot = self._dataset(tmp_path)
        stream = lerobot.read(root, 0, media_prefix="/media/ds").streams[0]
        assert stream.url.startswith("/media/ds/videos/")
        assert stream.kind == "wrist"

    def test_the_chunk_template_is_honoured(self, tmp_path):
        # Chunk size is configurable, and a dataset with more than `chunks_size`
        # episodes really does put the next one in chunk-001. A hardcoded path
        # reads the right file for episode 0 and nothing after it.
        root, lerobot = self._dataset(tmp_path, chunks_size=1, total=2)
        assert (root / "data" / "chunk-001" / "episode_000001.parquet").exists()
        assert lerobot.read(root, 1).num_frames == 3

    def test_a_missing_episode_says_which_and_where(self, tmp_path):
        root, lerobot = self._dataset(tmp_path)
        with pytest.raises(EpisodeError, match="episode 99"):
            lerobot.read(root, 99)

    def test_list_episodes_uses_the_declared_total(self, tmp_path):
        root, _lerobot = self._dataset(tmp_path)
        assert list_episodes(root) == [0, 1]


# ---------------------------------------------------------------------------
# HDF5
# ---------------------------------------------------------------------------

class TestHdf5:
    def _aloha(self, tmp_path):
        h5py = pytest.importorskip("h5py")
        np = pytest.importorskip("numpy")
        path = tmp_path / "episode.hdf5"
        with h5py.File(path, "w") as fh:
            obs = fh.create_group("observations")
            obs.create_dataset("qpos", data=np.zeros((5, 3)))
            images = obs.create_group("images")
            images.create_dataset("top", data=np.zeros((5, 4, 4, 3),
                                                       dtype="uint8"))
            fh.create_dataset("action", data=np.ones((5, 3)))
        return path

    def _robomimic(self, tmp_path):
        h5py = pytest.importorskip("h5py")
        np = pytest.importorskip("numpy")
        path = tmp_path / "dataset.hdf5"
        with h5py.File(path, "w") as fh:
            data = fh.create_group("data")
            for name in ("demo_0", "demo_2", "demo_10"):
                demo = data.create_group(name)
                demo.create_dataset("actions", data=np.zeros((4, 2)))
                demo.create_dataset("rewards", data=np.arange(4.0))
        return path

    def test_reads_the_aloha_layout(self, tmp_path):
        from potato.episodes import hdf5
        ep = hdf5.read(self._aloha(tmp_path))
        assert ep.num_frames == 5
        assert ep.source_format == "hdf5_aloha"
        names = [s.name for s in ep.series]
        assert any("qpos" in n for n in names)
        assert any("action" in n for n in names)

    def test_image_datasets_are_reported_not_drawn(self, tmp_path):
        # Frames stay in the file: extracting 500 RGB frames into an MP4 is an
        # ffmpeg job with its own failure modes, and doing it inside a reader
        # makes opening an episode arbitrarily slow with no progress shown.
        from potato.episodes import hdf5
        ep = hdf5.read(self._aloha(tmp_path))
        assert any("images/top" in name
                   for name in ep.metadata["image_datasets"])
        assert not any("images" in s.name for s in ep.series)

    def test_reads_the_robomimic_layout(self, tmp_path):
        from potato.episodes import hdf5
        ep = hdf5.read(self._robomimic(tmp_path), demo="demo_2")
        assert ep.episode_id == "demo_2"
        assert ep.source_format == "hdf5_robomimic"
        assert ep.num_frames == 4

    def test_demo_keys_sort_numerically_not_lexically(self, tmp_path):
        # demo_10 must not come between demo_1 and demo_2, and the keys are not
        # necessarily contiguous — a filtered dataset has holes, so treating
        # the key as an index reads the wrong demonstration.
        from potato.episodes import hdf5
        assert hdf5.list_episodes(self._robomimic(tmp_path)) == [
            "demo_0", "demo_2", "demo_10"]

    def test_an_unknown_demo_lists_the_real_ones(self, tmp_path):
        from potato.episodes import hdf5
        with pytest.raises(EpisodeError, match="demo_0"):
            hdf5.read(self._robomimic(tmp_path), demo="demo_999")


# ---------------------------------------------------------------------------
# RLDS
# ---------------------------------------------------------------------------

class TestRlds:
    def test_absence_names_the_install_and_the_alternative(self):
        from potato.episodes import rlds
        if rlds.available():
            pytest.skip("tensorflow_datasets is installed")
        with pytest.raises(EpisodeError) as exc:
            rlds.read("bridge")
        message = str(exc.value)
        assert "pip install" in message
        assert "LeRobot" in message, (
            "the error should name the offline alternative, not just the "
            "500 MB dependency")

    def test_available_does_not_import_tensorflow(self):
        # Importing it to find out whether it is importable would defeat the
        # entire point of the lazy path: TensorFlow is hundreds of megabytes
        # and pulls CUDA on many platforms.
        #
        # Asserted as a DIFFERENCE, not as an absolute. `tensorflow not in
        # sys.modules` passes in isolation and fails in the full suite the
        # moment any other test imports it — which says nothing about this
        # function and is exactly the kind of assertion that gets deleted for
        # being flaky rather than fixed.
        import sys
        from potato.episodes import rlds

        before = {m for m in sys.modules if m.startswith("tensorflow")}
        rlds.available()
        after = {m for m in sys.modules if m.startswith("tensorflow")}
        assert after == before, f"available() imported {after - before}"


# ---------------------------------------------------------------------------
# The manifest the browser receives
# ---------------------------------------------------------------------------

class TestManifest:
    def test_series_are_downsampled_for_transport(self):
        ep = Episode(episode_id="e", num_frames=30000, fps=50,
                     series=[Series(name="a",
                                    values=[float(i) for i in range(30000)])])
        payload = ep.to_json(max_samples=400)
        assert len(payload["series"][0]["values"]) < 500
        assert payload["series"][0]["num_frames"] == 30000

    def test_warnings_travel_with_the_manifest(self, ):
        ep = Episode(episode_id="e", num_frames=10, fps=20,
                     series=[Series(name="a", values=[1.0] * 5)])
        assert ep.to_json()["warnings"]

    def test_the_range_is_precomputed_for_the_lane(self):
        ep = Episode(episode_id="e", num_frames=3, fps=1,
                     series=[Series(name="a", values=[1.0, 5.0, 3.0])])
        payload = ep.to_json()["series"][0]
        assert payload["min"] == 1.0 and payload["max"] == 5.0

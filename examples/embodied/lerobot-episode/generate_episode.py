#!/usr/bin/env python3
"""
Generate the synthetic robot episodes this example annotates.

A generator rather than committed fixtures, for the same reason the point cloud
and depth examples use one: a reviewer can read what the demonstration
contains, and the repository does not carry opaque binaries.

Two episodes of a pick-and-place, at 20 Hz:

- **episode_0000** succeeds. Reach, grasp, transport, place, retract.
- **episode_0001** fails: the gripper closes on nothing, and the force trace
  stays flat where episode 0 shows a contact spike. The failure is visible in
  the series *before* it is obvious in the video, which is the case dense
  time-series annotation exists for.

Video is written with ffmpeg when it is on PATH, as **WebM/VP9** — Chromium
ships without an H.264 decoder, so an MP4 example silently shows a black
rectangle in exactly the browser most people test in. Without ffmpeg the
episode is written state-only, which is a normal kind of robot dataset and is
what the timeline degrades to.

Run from the repository root:

    python examples/embodied/lerobot-episode/generate_episode.py
"""

from __future__ import annotations

import json
import math
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
EPISODES = HERE / "media" / "episodes"

FPS = 20
DURATION = 6.0
NUM_FRAMES = int(FPS * DURATION)

WIDTH, HEIGHT = 240, 180

#: Phase boundaries in seconds, used to shape the signals. The annotator is
#: asked to find these, so they are NOT written into the episode.
PHASES = [
    ("reach", 0.0, 1.4),
    ("grasp", 1.4, 2.2),
    ("transport", 2.2, 4.0),
    ("place", 4.0, 4.8),
    ("retract", 4.8, 6.0),
]

JOINT_NAMES = ["shoulder_pan", "shoulder_lift", "elbow", "wrist_flex",
               "wrist_roll", "gripper"]


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

def phase_at(t: float) -> str:
    for name, start, end in PHASES:
        if start <= t < end:
            return name
    return PHASES[-1][0]


def joint_trace(index: int, succeed: bool):
    """A joint trajectory shaped by the phase schedule."""
    values = []
    for frame in range(NUM_FRAMES):
        t = frame / FPS
        phase = phase_at(t)
        base = {
            "reach": 0.2 + 0.5 * (t / 1.4),
            "grasp": 0.7,
            "transport": 0.7 - 0.4 * ((t - 2.2) / 1.8),
            "place": 0.3,
            "retract": 0.3 - 0.3 * ((t - 4.8) / 1.2),
        }[phase]
        # Each joint gets its own phase offset so the lanes are distinguishable
        # rather than six copies of one line.
        offset = 0.15 * math.sin(index * 1.1 + t * 1.7)
        values.append(round(base + offset, 4))
    return values


def gripper_trace(succeed: bool):
    """
    Gripper opening in metres. Closes at the grasp, opens at the place.

    In the failing episode it closes to zero rather than to the block's width —
    the single most diagnostic channel, and the reason the failure is findable
    in the data before it is obvious in the picture.
    """
    closed = 0.028 if succeed else 0.002
    values = []
    for frame in range(NUM_FRAMES):
        t = frame / FPS
        phase = phase_at(t)
        if phase in ("reach",):
            v = 0.06
        elif phase == "grasp":
            v = 0.06 + (closed - 0.06) * min(1.0, (t - 1.4) / 0.6)
        elif phase == "transport":
            v = closed
        elif phase == "place":
            v = closed + (0.06 - closed) * min(1.0, (t - 4.0) / 0.5)
        else:
            v = 0.06
        values.append(round(v, 5))
    return values


def force_trace(succeed: bool):
    """Wrist force. A contact spike at the grasp, flat when nothing is held."""
    values = []
    for frame in range(NUM_FRAMES):
        t = frame / FPS
        v = 0.4 + 0.15 * math.sin(t * 5.0)
        if succeed and 1.5 <= t <= 1.9:
            v += 6.0 * math.exp(-((t - 1.65) ** 2) / 0.004)
        if succeed and 2.2 <= t <= 4.0:
            v += 2.2                      # carrying the block
        values.append(round(v, 4))
    return values


def reward_trace(succeed: bool):
    """
    The environment's own reward, if any. Not the annotator's — that is the
    thing being collected, and shipping a reference would anchor it.
    """
    values = []
    for frame in range(NUM_FRAMES):
        t = frame / FPS
        values.append(1.0 if (succeed and t >= 4.8) else 0.0)
    return values


# ---------------------------------------------------------------------------
# Video
# ---------------------------------------------------------------------------

def png_chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def write_png(path: Path, rows):
    raw = b"".join(b"\x00" + row for row in rows)
    header = struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 2, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", header)
        + png_chunk(b"IDAT", zlib.compress(raw, 6))
        + png_chunk(b"IEND", b""))


def render_frame(t: float, succeed: bool, view: str):
    """
    One frame: a gripper moving over a table, with a block.

    Crude on purpose. The point of the example is the annotation surface, and a
    photorealistic renderer would be a much larger thing to review for no gain.
    """
    phase = phase_at(t)
    gripper_x = {
        "reach": 40 + 90 * (t / 1.4),
        "grasp": 130,
        "transport": 130 + 60 * ((t - 2.2) / 1.8),
        "place": 190,
        "retract": 190 - 60 * ((t - 4.8) / 1.2),
    }[phase]
    gripper_y = 40 if phase in ("transport",) else 80

    held = succeed and phase in ("transport", "place")
    block_x = gripper_x if held else (130 if t < 4.0 else 190)
    block_y = gripper_y + 22 if held else 110

    # Wrist view is a zoomed crop centred on the gripper.
    zoom = 2.0 if view == "wrist" else 1.0
    cx = gripper_x if view == "wrist" else WIDTH / 2

    rows = []
    for y in range(HEIGHT):
        row = bytearray()
        for x in range(WIDTH):
            wx = cx + (x - WIDTH / 2) / zoom
            wy = (gripper_y + (y - HEIGHT / 2) / zoom) if view == "wrist" else y
            colour = (222, 220, 214) if wy < 130 else (150, 128, 96)
            if abs(wx - gripper_x) < 12 and abs(wy - gripper_y) < 9:
                colour = (60, 70, 95)
            elif abs(wx - block_x) < 9 and abs(wy - block_y) < 9:
                colour = (200, 70, 60)
            row += bytes(colour)
        rows.append(bytes(row))
    return rows


def write_video(target: Path, succeed: bool, view: str) -> bool:
    """Encode one stream. Returns False when ffmpeg is unavailable."""
    if not shutil.which("ffmpeg"):
        return False

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        for frame in range(NUM_FRAMES):
            write_png(tmp_path / f"f_{frame:04d}.png",
                      render_frame(frame / FPS, succeed, view))
        target.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error",
             "-framerate", str(FPS),
             "-i", str(tmp_path / "f_%04d.png"),
             # VP9, not H.264: Chromium ships without an H.264 decoder, and an
             # MP4 here would show a black rectangle in the browser most people
             # test in, with no error anywhere.
             "-c:v", "libvpx-vp9", "-b:v", "300k", "-pix_fmt", "yuv420p",
             str(target)],
            capture_output=True)
        if result.returncode != 0:
            print(f"  ffmpeg failed for {target.name}: "
                  f"{result.stderr.decode('utf-8', 'replace')[:200]}",
                  file=sys.stderr)
            return False
    return True


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def build(index: int, succeed: bool):
    name = f"episode_{index:04d}"
    directory = EPISODES / name
    directory.mkdir(parents=True, exist_ok=True)

    streams = []
    for view in ("overhead", "wrist"):
        target = directory / "video" / f"{view}.webm"
        if write_video(target, succeed, view):
            streams.append({"name": view, "url": f"video/{view}.webm",
                            "kind": view, "width": WIDTH, "height": HEIGHT})

    series = []
    for i, joint in enumerate(JOINT_NAMES[:-1]):
        series.append({"name": joint, "unit": "rad", "group": "joint_position",
                       "values": joint_trace(i, succeed)})
    series.append({"name": "gripper", "unit": "m", "group": "joint_position",
                   "values": gripper_trace(succeed)})
    series.append({"name": "wrist_force", "unit": "N", "group": "force",
                   "values": force_trace(succeed)})
    series.append({"name": "env_reward", "unit": "", "group": "reward",
                   "values": reward_trace(succeed)})

    manifest = {
        "episode_id": name,
        "fps": FPS,
        "num_frames": NUM_FRAMES,
        "instruction": "pick up the red block and place it on the right",
        "streams": streams,
        "series": series,
        "metadata": {"robot_type": "synthetic_6dof",
                     "note": "generated by generate_episode.py"},
    }
    (directory / "episode.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return name, bool(streams)


def main():
    items = []
    any_video = False
    for index, succeed in enumerate([True, False]):
        name, has_video = build(index, succeed)
        any_video = any_video or has_video
        items.append({
            "id": name,
            "episode": f"episodes/{name}/episode.json",
            "note": ("Pick and place. Mark the phases, say whether it worked, "
                     "and draw how well it was going."),
        })

    data_dir = HERE / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "episodes.json").write_text(
        json.dumps(items, indent=2) + "\n", encoding="utf-8")

    print(f"Wrote {len(items)} episodes to {EPISODES}")
    if not any_video:
        print("ffmpeg was not found, so the episodes are state-only. "
              "The timeline still works; install ffmpeg and re-run for video.")


if __name__ == "__main__":
    main()

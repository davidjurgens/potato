#!/usr/bin/env python3
"""
Generate the synthetic rollout sets this example annotates.

A generator rather than committed fixtures, for the same reason the episode,
point cloud and depth examples use one: a reviewer can read what each clip
contains, and the repository does not carry opaque binaries.

## What each set contains

Three scenarios, each with a real recording and two "model rollouts". The
rollouts are wrong in *specific, findable ways*, and the frame at which each
goes wrong is known here and deliberately **not** written into the data — that
is the thing the annotator is being asked to find, and shipping the answer
would anchor them.

| Scenario | Model A | Model B |
|---|---|---|
| `ball_drop` | the ball stops mid-air at 2.0 s (gravity_violation) | correct |
| `block_push` | the block passes through the wall at 2.6 s (interpenetration) | the block vanishes at 3.4 s (object_permanence) |
| `two_balls` | correct | the two balls swap colour at 3.0 s (identity_flicker) |

`block_push` also carries an **intervention** — "the wall was moved left at
1.5 s" — so the counterfactual layer has something to judge. That is the layer
that separates a world model from a video generator: a rollout that produces a
beautiful continuation while ignoring the intervention has failed at the thing
world models are for, and no plausibility rating detects it, because the video
is plausible.

Video is written with ffmpeg as **WebM/VP9** — Chromium ships without an H.264
decoder, so an MP4 example silently shows a black rectangle in exactly the
browser most people test in.

Run from the repository root:

    python examples/agent-traces/world-model-rollouts/generate_rollouts.py
"""

from __future__ import annotations

import json
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
MEDIA = HERE / "media" / "rollouts"

FPS = 25
DURATION = 5.0
NUM_FRAMES = int(FPS * DURATION)
WIDTH, HEIGHT = 320, 240

GROUND_Y = 200
SKY = (232, 236, 244)
GROUND = (176, 168, 150)
WALL = (90, 96, 110)


# ---------------------------------------------------------------------------
# PNG writing (no Pillow dependency, matching the other example generators)
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


def render(objects, wall_x=None):
    """
    One frame: a ground line, an optional wall, and some discs.

    ``objects`` is a list of ``(x, y, radius, colour)``. Crude on purpose — the
    point of the example is the annotation surface, and a physics renderer
    would be a much larger thing to review for no gain.
    """
    rows = []
    for y in range(HEIGHT):
        row = bytearray()
        for x in range(WIDTH):
            colour = SKY if y < GROUND_Y else GROUND
            if wall_x is not None and abs(x - wall_x) < 5 and y > GROUND_Y - 70:
                colour = WALL
            for ox, oy, radius, oc in objects:
                if (x - ox) ** 2 + (y - oy) ** 2 <= radius * radius:
                    colour = oc
                    break
            row += bytes(colour)
        rows.append(bytes(row))
    return rows


# ---------------------------------------------------------------------------
# The scenarios
# ---------------------------------------------------------------------------

RED = (206, 66, 54)
BLUE = (58, 92, 186)


def ball_drop(t: float, variant: str):
    """A ball falls and bounces once. Model A freezes it in mid-air."""
    freeze_at = 2.0
    if variant == "freeze" and t >= freeze_at:
        t = freeze_at
    # Fall, bounce at 1.6 s, settle.
    if t < 1.6:
        y = 40 + 120 * (t / 1.6) ** 2
    else:
        bounce = t - 1.6
        y = GROUND_Y - 12 - max(0.0, 70 * bounce * (1.2 - bounce))
    return [(160, min(GROUND_Y - 12, y), 12, RED)], None


def block_push(t: float, variant: str):
    """
    A block slides right into a wall and stops.

    The wall's position is the *intervention*: it was moved from x=250 to
    x=200 at 1.5 s, so a correct rollout stops the block earlier than the
    real recording does.
    """
    wall_x = 200 if variant != "real" else 250
    stop_x = wall_x - 20

    x = 40 + 60 * t
    if variant == "through":
        # Ignores the wall entirely from 2.6 s.
        pass
    elif variant == "vanish":
        if t >= 3.4:
            return [], wall_x
        x = min(x, stop_x)
    else:
        x = min(x, stop_x)
    return [(min(x, WIDTH - 10), GROUND_Y - 14, 14, RED)], wall_x


def two_balls(t: float, variant: str):
    """Two balls cross. Model B swaps their colours as they pass."""
    left = 40 + 50 * t
    right = 280 - 50 * t
    swap = variant == "swap" and t >= 3.0
    a_colour = BLUE if swap else RED
    b_colour = RED if swap else BLUE
    return [(left, 120, 13, a_colour), (right, 150, 13, b_colour)], None


SCENARIOS = {
    "ball_drop": {
        "fn": ball_drop,
        "prompt": "A ball is dropped onto a table and bounces once.",
        "intervention": "",
        "intervention_t": None,
        "variants": {"real": "real", "gen_a": "freeze", "gen_b": "real"},
    },
    "block_push": {
        "fn": block_push,
        "prompt": "A block slides to the right and hits a wall.",
        "intervention": "The wall was moved 50 px to the left at 1.5 s.",
        "intervention_t": 1.5,
        "variants": {"real": "real", "gen_a": "through", "gen_b": "vanish"},
    },
    "two_balls": {
        "fn": two_balls,
        "prompt": "A red ball and a blue ball pass each other.",
        "intervention": "",
        "intervention_t": None,
        "variants": {"real": "real", "gen_a": "real", "gen_b": "swap"},
    },
}


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------

def write_video(target: Path, scenario: str, variant: str) -> bool:
    """Encode one rollout. Returns False when ffmpeg is unavailable."""
    if not shutil.which("ffmpeg"):
        return False

    fn = SCENARIOS[scenario]["fn"]
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        for frame in range(NUM_FRAMES):
            objects, wall_x = fn(frame / FPS, variant)
            write_png(tmp_path / f"f_{frame:04d}.png", render(objects, wall_x))
        target.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error",
             "-framerate", str(FPS),
             "-i", str(tmp_path / "f_%04d.png"),
             # VP9, not H.264: Chromium ships without an H.264 decoder, and an
             # MP4 here would show a black rectangle in the browser most people
             # test in, with no error anywhere.
             "-c:v", "libvpx-vp9", "-b:v", "250k", "-pix_fmt", "yuv420p",
             str(target)],
            capture_output=True)
        if result.returncode != 0:
            print(f"  ffmpeg failed for {target.name}: "
                  f"{result.stderr.decode('utf-8', 'replace')[:200]}",
                  file=sys.stderr)
            return False
    return True


def main():
    items = []
    any_video = False

    for scenario, spec in SCENARIOS.items():
        directory = MEDIA / scenario
        urls = {}
        for role, variant in spec["variants"].items():
            target = directory / f"{role}.webm"
            if write_video(target, scenario, variant):
                any_video = True
                urls[role] = f"rollouts/{scenario}/{role}.webm"

        items.append({
            "id": scenario,
            "prompt": spec["prompt"],
            "intervention": spec["intervention"],
            "intervention_t": spec["intervention_t"],
            "real": urls.get("real", ""),
            "gen_a": urls.get("gen_a", ""),
            "gen_b": urls.get("gen_b", ""),
            "note": ("Find the frame where each rollout stops making sense. "
                     "Mark a panel as having no breaks if it is coherent "
                     "throughout."),
        })

    data_dir = HERE / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "rollouts.json").write_text(
        json.dumps(items, indent=2) + "\n", encoding="utf-8")

    print(f"Wrote {len(items)} rollout sets to {MEDIA}")
    if not any_video:
        print("ffmpeg was not found, so no video was written. Install ffmpeg "
              "and re-run — this example has nothing to show without it.")


if __name__ == "__main__":
    main()

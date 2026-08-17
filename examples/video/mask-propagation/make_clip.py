#!/usr/bin/env python3
"""
Render the short clip this example tracks through.

A synthetic clip on purpose: you can see exactly where the object is on every
frame, so you can judge the tracker's answer instead of taking it on trust. The
disc passes behind a bar halfway through, which is the interesting part — a
tracker with a memory picks the object up again on the other side, and one that
carries a mask forward by re-prompting usually does not.

Needs ffmpeg, which server-side propagation needs anyway to read frames:

    python examples/video/mask-propagation/make_clip.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
MEDIA = os.path.join(HERE, "media")
OUTPUT = os.path.join(MEDIA, "occlusion.webm")

WIDTH, HEIGHT = 480, 320
FRAMES = 48
FPS = 12
RADIUS = 30
#: The bar the disc passes behind, in x. Wide enough to hide it completely.
BAR = (210, 0, 275, HEIGHT)


def main() -> int:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        sys.exit("This needs Pillow:  pip install Pillow")

    if shutil.which("ffmpeg") is None:
        sys.exit("This needs ffmpeg, which server-side propagation also uses "
                 "to read frames. Install it and run this again.")

    os.makedirs(MEDIA, exist_ok=True)
    temp_dir = tempfile.mkdtemp(prefix="potato-clip-")
    try:
        for index in range(FRAMES):
            image = Image.new("RGB", (WIDTH, HEIGHT), (236, 236, 232))
            draw = ImageDraw.Draw(image)

            # A second object that never moves, so "track the only thing that
            # moves" is not enough to pass.
            draw.ellipse([40, 230, 100, 290], fill=(80, 130, 90))

            x = 40 + index * (WIDTH - 120) / (FRAMES - 1)
            y = HEIGHT / 2 + 30 * (index / FRAMES)
            draw.ellipse([x - RADIUS, y - RADIUS, x + RADIUS, y + RADIUS],
                         fill=(210, 70, 60))

            # Drawn last so it covers the disc as it passes.
            draw.rectangle(list(BAR), fill=(60, 70, 90))
            image.save(os.path.join(temp_dir, f"frame_{index:04d}.png"))

        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-framerate", str(FPS),
            "-i", os.path.join(temp_dir, "frame_%04d.png"),
            "-c:v", "libvpx-vp9", "-pix_fmt", "yuv420p", OUTPUT,
        ], check=True)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    print(f"  {OUTPUT}")
    print(f"  {FRAMES} frames at {FPS} fps, {WIDTH}x{HEIGHT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
Build the sample scenes for the region-captioning example.

Coloured shapes rather than photographs, for a reason specific to *this*
example. Region captioning is annotated freely — nobody is told what to write —
so agreement between two annotators is exactly what the example demonstrates.
Photographs would make the captions vary because the scene is rich and
ambiguous, which measures the photograph. Distinct shapes give annotators an
obvious thing to describe and a genuine choice of *words* for it, which is what
caption agreement is about.

Each scene deliberately contains a couple of objects that invite different
vocabulary for the same thing — a shape most people would call either a "box" or
a "rectangle", a colour between red and orange — so `token` and `embedding`
agreement come out visibly different on real annotations.

    python generate_images.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MEDIA = os.path.join(HERE, "media")

WIDTH, HEIGHT = 720, 520
BACKGROUND = "#f4f1ea"

#: (shape, box, colour). "ellipse" and "rectangle" only — the point is the
#: caption, not the rendering.
SCENES = {
    "desk_scene.png": [
        ("rectangle", (70, 90, 300, 250), "#b03a2e"),    # red-ish: "red"/"crimson"
        ("ellipse", (380, 110, 560, 290), "#f0c419"),    # yellow circle
        ("rectangle", (250, 330, 470, 450), "#2e6da4"),  # blue box
    ],
    "street_scene.png": [
        ("rectangle", (60, 320, 660, 470), "#6b7a8f"),   # wide grey band: road
        ("rectangle", (140, 120, 260, 320), "#7d5a3c"),  # tall brown: post/pole
        ("ellipse", (450, 90, 590, 230), "#e07b39"),     # orange: sun/ball
    ],
    "shelf_scene.png": [
        ("rectangle", (80, 140, 180, 400), "#3f7d4f"),
        ("rectangle", (200, 190, 300, 400), "#8e5aa8"),
        ("rectangle", (320, 110, 420, 400), "#c0721f"),
        ("ellipse", (500, 220, 650, 370), "#3b3b3b"),
    ],
}


def main():
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        sys.exit("This needs Pillow:  pip install Pillow")

    os.makedirs(MEDIA, exist_ok=True)
    for name, shapes in SCENES.items():
        image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
        draw = ImageDraw.Draw(image)
        for kind, box, colour in shapes:
            if kind == "ellipse":
                draw.ellipse(box, fill=colour)
            else:
                draw.rectangle(box, fill=colour)
        path = os.path.join(MEDIA, name)
        image.save(path)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()

"""
Build the sample scenes for the grounding example.

Simple coloured shapes rather than photographs: the referring expressions have
to have unambiguous answers, or the example measures the annotator's guess at
what the phrase means rather than the interface. "the red square on the left"
is either right or wrong.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MEDIA = os.path.join(HERE, "media")

SCENES = {
    "scene_a.png": [
        ((60, 80, 240, 300), "#c0392b"),     # red, left
        ((420, 120, 620, 340), "#2980b9"),   # blue, right
        ((260, 380, 380, 480), "#27ae60"),   # green, bottom middle
    ],
    "scene_b.png": [
        ((100, 100, 300, 260), "#8e44ad"),   # purple, upper left
        ((380, 300, 600, 460), "#d35400"),   # orange, lower right
    ],
}


def main():
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        sys.exit("This needs Pillow:  pip install Pillow")

    os.makedirs(MEDIA, exist_ok=True)
    for name, shapes in SCENES.items():
        image = Image.new("RGB", (700, 520), "#f4f1ea")
        draw = ImageDraw.Draw(image)
        for box, colour in shapes:
            draw.rectangle(box, fill=colour)
        image.save(os.path.join(MEDIA, name))
        print(f"Wrote {os.path.join(MEDIA, name)}")


if __name__ == "__main__":
    main()

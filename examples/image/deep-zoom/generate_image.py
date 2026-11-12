"""
Build the large sample image this example annotates.

Not committed: a 6000x4000 PNG is ~9 MB of repository for a picture that can be
regenerated in a second, and the point of the example is the *viewer*, not the
particular pixels. The pattern is deliberately fine-grained so that zooming in
shows detail that is genuinely invisible at fit-to-screen — which is the whole
claim deep zoom makes and the only way to see whether it is working.
"""

import os
import sys

WIDTH, HEIGHT = 6000, 4000
TARGET = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "media", "survey.png")


def main():
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        sys.exit("This needs Pillow:  pip install Pillow")

    image = Image.new("RGB", (WIDTH, HEIGHT), "#f4f1ea")
    draw = ImageDraw.Draw(image)

    # A coarse grid, readable at fit-to-screen.
    for x in range(0, WIDTH, 500):
        draw.line([(x, 0), (x, HEIGHT)], fill="#c8c2b4", width=3)
    for y in range(0, HEIGHT, 500):
        draw.line([(0, y), (WIDTH, y)], fill="#c8c2b4", width=3)

    # A fine grid, invisible until you zoom. If you can see this without
    # zooming, the viewer is not showing you full resolution.
    for x in range(0, WIDTH, 20):
        draw.line([(x, 0), (x, HEIGHT)], fill="#e8e4da", width=1)
    for y in range(0, HEIGHT, 20):
        draw.line([(0, y), (WIDTH, y)], fill="#e8e4da", width=1)

    # Scattered "structures" to annotate, sized so several are sub-pixel at
    # fit-to-screen and only become distinguishable at magnification.
    palette = ["#c0392b", "#27ae60", "#2980b9", "#8e44ad", "#d35400"]
    for index in range(400):
        # A deterministic scatter: no RNG, so the file is reproducible.
        x = (index * 977) % (WIDTH - 120) + 40
        y = (index * 613) % (HEIGHT - 120) + 40
        size = 6 + (index % 7) * 4
        colour = palette[index % len(palette)]
        if index % 3 == 0:
            draw.ellipse([x, y, x + size, y + size], fill=colour)
        else:
            draw.rectangle([x, y, x + size, y + size], fill=colour)

    os.makedirs(os.path.dirname(TARGET), exist_ok=True)
    image.save(TARGET)
    print(f"Wrote {TARGET} ({WIDTH}x{HEIGHT})")


if __name__ == "__main__":
    main()

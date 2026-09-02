#!/usr/bin/env python3
"""
Fetch the three photographs this example labels.

WHY THE IMAGES ARE NOT COMMITTED
--------------------------------
They are photographs from the COCO val2017 set, hosted publicly by the COCO
consortium. Potato does not redistribute them: this script downloads them into
`media/` on request, which keeps the repository small and leaves the images
under their own terms rather than under Potato's.

Run it before starting the server:

    python examples/image/text-prompt-labeling/fetch_images.py

WITHOUT A NETWORK
-----------------
Pass --synthetic to draw three plain scenes instead. The example still runs and
the interface behaves identically; the detector simply has less to find, which
is worth seeing too — a model that returns nothing should say so rather than
invent something.
"""

from __future__ import annotations

import argparse
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
MEDIA = os.path.join(HERE, "media")

#: COCO val2017 images, chosen because each has an unambiguous subject that a
#: reader can check against the model's answer by eye.
PHOTOS = {
    "cats.jpg": "http://images.cocodataset.org/val2017/000000039769.jpg",
    "bus.jpg": "http://images.cocodataset.org/val2017/000000001584.jpg",
    "stop-sign.jpg": "http://images.cocodataset.org/val2017/000000000724.jpg",
}

SYNTHETIC = {
    "cats.jpg": ((640, 480), (238, 238, 234), (60, 90, 300, 400), (224, 123, 57)),
    "bus.jpg": ((640, 480), (226, 232, 238), (80, 120, 520, 380), (70, 110, 190)),
    "stop-sign.jpg": ((640, 480), (240, 240, 236), (220, 120, 420, 320), (190, 40, 40)),
}


def download() -> int:
    os.makedirs(MEDIA, exist_ok=True)
    for name, url in PHOTOS.items():
        target = os.path.join(MEDIA, name)
        if os.path.exists(target):
            print(f"  {name} already present")
            continue
        try:
            urllib.request.urlretrieve(url, target)
        except Exception as exc:  # noqa: BLE001 - reported, not handled
            print(f"could not download {name}: {exc}", file=sys.stderr)
            print("Try again, or run with --synthetic to draw plain scenes.",
                  file=sys.stderr)
            return 1
        print(f"  {name} <- {url}")
    print("\nImages are from COCO val2017 and remain under their own terms.")
    return 0


def synthesize() -> int:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        sys.exit("This needs Pillow:  pip install Pillow")

    os.makedirs(MEDIA, exist_ok=True)
    for name, (size, background, box, colour) in SYNTHETIC.items():
        image = Image.new("RGB", size, background)
        ImageDraw.Draw(image).rectangle(list(box), fill=colour)
        image.save(os.path.join(MEDIA, name))
        print(f"  {name} (synthetic)")
    print("\nThese are plain rectangles. The detector will find little in them, "
          "which is the honest behaviour to see.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic", action="store_true",
                        help="Draw plain scenes instead of downloading photos")
    args = parser.parse_args()
    return synthesize() if args.synthetic else download()


if __name__ == "__main__":
    sys.exit(main())

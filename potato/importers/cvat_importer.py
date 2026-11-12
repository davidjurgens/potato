"""
CVAT XML 1.1 importer.

CVAT is the most common open-source annotation tool, so it is the most common
thing to be migrating *from*. Its XML carries more shape types than COCO::

    <annotations>
      <meta><task><labels>
        <label><name>car</name><color>#ff0000</color></label>
      </labels></task></meta>
      <image id="0" name="img.jpg" width="640" height="480">
        <box label="car" xtl="10" ytl="20" xbr="100" ybr="200" occluded="0">
          <attribute name="model">sedan</attribute>
        </box>
        <polygon  label="road" points="10,20;30,40;50,60"/>
        <polyline label="lane" points="10,20;30,40"/>
        <points   label="tip"  points="10,20"/>
        <ellipse  label="cell" cx="50" cy="50" rx="20" ry="10" rotation="30"/>
      </image>
    </annotations>

Every one of those maps onto a primitive Potato now has, which is the payoff for
adding polyline, ellipse and keypoint sets: a CVAT project imports without
anything being flattened into a bounding box.

Three things to know:

* **Boxes are corners** (``xtl ytl xbr ybr``), like VOC and unlike COCO.
* **Video tasks use ``<track>``, not ``<image>``.** A track is one object across
  frames, which is a spatio-temporal annotation Potato's image schema cannot
  express. Tracks are reported in a warning rather than silently flattened into
  their first frame.
* **``rotation`` is degrees**, and CVAT applies it about the shape's centre —
  the same convention as our ellipse type, so it passes through unchanged.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional

from potato.export.cv_utils import to_client_object

from ._common import apply_url_prefix
from .base import BaseAnnotationImporter, ImportedImage, ImportResult

logger = logging.getLogger(__name__)


def _points(raw: Optional[str]) -> List[List[float]]:
    """CVAT point lists are ``x,y;x,y;...``."""
    out: List[List[float]] = []
    for pair in (raw or "").split(";"):
        pair = pair.strip()
        if not pair:
            continue
        try:
            x, y = pair.split(",")
            out.append([float(x), float(y)])
        except ValueError:
            continue
    return out


def _f(node, attr: str, default: float = 0.0) -> float:
    try:
        return float(node.get(attr))
    except (TypeError, ValueError):
        return default


class CVATImporter(BaseAnnotationImporter):
    format_name = "cvat"
    description = "CVAT XML 1.1 (images; tracks are reported, not flattened)"
    file_extensions = [".xml"]

    #: CVAT element name -> the Potato tool it becomes.
    SHAPE_TOOLS = {
        "box": "bbox",
        "polygon": "polygon",
        "polyline": "polyline",
        "points": "landmark",
        "ellipse": "ellipse",
    }

    def detect(self, data: Any) -> bool:
        root = self._as_root(data)
        if root is None or root.tag != "annotations":
            return False
        # <annotations> alone is too generic; CVAT always carries a version or
        # at least one <image>/<track>.
        return (root.find("version") is not None
                or root.find("image") is not None
                or root.find("track") is not None
                or root.find("meta") is not None)

    @staticmethod
    def _as_root(data: Any):
        if isinstance(data, ET.Element):
            return data
        if isinstance(data, ET.ElementTree):
            return data.getroot()
        if isinstance(data, (str, bytes)):
            try:
                return ET.fromstring(data)
            except ET.ParseError:
                return None
        return None

    def parse_directory(self, root: str,
                        options: Optional[dict] = None) -> ImportResult:
        base = Path(root)
        candidates = ([base] if base.is_file()
                      else sorted(base.glob("*.xml")) or
                      sorted(base.glob("annotations.xml")))
        if not candidates:
            raise ValueError(f"No CVAT .xml found under {base}")
        # A CVAT export is one file, so take the first that actually parses.
        for path in candidates:
            try:
                doc = ET.parse(path).getroot()
            except ET.ParseError:
                continue
            if self.detect(doc):
                return self.parse(doc, options)
        raise ValueError(f"No file under {base} looks like a CVAT export")

    def parse(self, data: Any, options: Optional[dict] = None) -> ImportResult:
        options = options or {}
        root = self._as_root(data)
        if root is None or not self.detect(root):
            raise ValueError("Not a CVAT XML 1.1 document")

        result = ImportResult()
        declared = self._declared_labels(root)
        used: Dict[str, dict] = {}
        tools: set = set()

        for image in root.findall("image"):
            name = image.get("name") or f"image_{image.get('id', '0')}"
            width = int(_f(image, "width", 0))
            height = int(_f(image, "height", 0))
            if width <= 0 or height <= 0:
                result.warnings.append(
                    f"{name}: no width/height, so coordinates cannot be "
                    f"normalized; skipped.")
                continue

            objects: List[dict] = []
            for node in image:
                tool = self.SHAPE_TOOLS.get(node.tag)
                if tool is None:
                    continue
                obj = self._convert(node, width, height, name, result.warnings)
                if obj is None:
                    continue
                self._attach_attributes(node, obj)
                objects.append(obj)
                tools.add(tool)
                label = obj["label"]
                used.setdefault(label, declared.get(label, {"name": label}))

            result.images.append(ImportedImage(
                instance_id=Path(name).stem,
                file_name=name,
                width=width,
                height=height,
                objects=objects,
                extra={"image_url": apply_url_prefix(name, options)},
            ))

        # Video tracks are a spatio-temporal object the image schema cannot
        # express. Say so rather than silently importing frame 0 and losing the
        # rest, which would look like a successful import of a broken dataset.
        tracks = root.findall("track")
        if tracks:
            result.warnings.append(
                f"{len(tracks)} <track> element(s) were not imported. CVAT "
                f"tracks are one object across video frames; Potato's image "
                f"schema has no equivalent, and flattening a track to its "
                f"first frame would silently discard the rest.")

        result.labels = [used[n] for n in sorted(used)]
        result.tools = sorted(tools)
        result.summarize(num_warnings=len(result.warnings))
        return result

    @staticmethod
    def _declared_labels(root) -> Dict[str, dict]:
        """Label names and colours from <meta>, so colours survive the move."""
        out: Dict[str, dict] = {}
        for label in root.findall(".//meta//labels/label"):
            name_node = label.find("name")
            if name_node is None or not name_node.text:
                continue
            entry = {"name": name_node.text.strip()}
            colour = label.find("color")
            if colour is not None and colour.text:
                entry["color"] = colour.text.strip()
            out[entry["name"]] = entry
        return out

    def _convert(self, node, width: int, height: int,
                 image_name: str, warnings: List[str]) -> Optional[dict]:
        label = node.get("label")
        if not label:
            warnings.append(f"{image_name}: <{node.tag}> with no label")
            return None
        colour = ""

        if node.tag == "box":
            # Corners, like VOC -- not origin plus size.
            xtl, ytl = _f(node, "xtl"), _f(node, "ytl")
            xbr, ybr = _f(node, "xbr"), _f(node, "ybr")
            if xbr <= xtl or ybr <= ytl:
                warnings.append(
                    f"{image_name}: degenerate box for '{label}'")
                return None
            return to_client_object("bbox", label, colour, img_w=width,
                                    img_h=height,
                                    bbox=[xtl, ytl, xbr - xtl, ybr - ytl])

        if node.tag == "ellipse":
            rx, ry = _f(node, "rx"), _f(node, "ry")
            if rx <= 0 or ry <= 0:
                warnings.append(f"{image_name}: degenerate ellipse for '{label}'")
                return None
            return to_client_object(
                "ellipse", label, colour, img_w=width, img_h=height,
                # CVAT's `rotation` is degrees about the centre, the same
                # convention as ours, so it passes through unchanged.
                ellipse={"cx": _f(node, "cx"), "cy": _f(node, "cy"),
                         "rx": rx, "ry": ry,
                         "angle": _f(node, "rotation", 0.0)})

        points = _points(node.get("points"))
        if not points:
            warnings.append(
                f"{image_name}: <{node.tag}> '{label}' has no usable points")
            return None

        if node.tag == "polygon":
            if len(points) < 3:
                warnings.append(
                    f"{image_name}: polygon '{label}' has {len(points)} points")
                return None
            return to_client_object("polygon", label, colour, img_w=width,
                                    img_h=height, points=points)

        if node.tag == "polyline":
            if len(points) < 2:
                warnings.append(
                    f"{image_name}: polyline '{label}' has {len(points)} points")
                return None
            return to_client_object("polyline", label, colour, img_w=width,
                                    img_h=height, points=points)

        if node.tag == "points":
            # CVAT's <points> is a loose set, not an ordered skeleton, so a
            # multi-point element becomes a keypoint_set only when it clearly
            # is one; a single point stays a landmark.
            if len(points) == 1:
                return to_client_object("landmark", label, colour, img_w=width,
                                        img_h=height, points=points)
            return to_client_object(
                "keypoint_set", label, colour, img_w=width, img_h=height,
                keypoints=[[p[0], p[1], 2] for p in points])

        return None

    @staticmethod
    def _attach_attributes(node, obj: dict) -> None:
        """
        Carry CVAT's per-shape attributes and flags across.

        Dropping them is lossy in a way that is invisible: a project whose
        labels depend on an attribute ("truncated", "vehicle_type") looks like
        it imported cleanly and is missing half its information.
        """
        for flag in ("occluded", "outside", "keyframe"):
            value = node.get(flag)
            if value not in (None, ""):
                try:
                    obj[flag] = int(value)
                except ValueError:
                    pass
        attributes = {}
        for attr in node.findall("attribute"):
            name = attr.get("name")
            if name:
                attributes[name] = (attr.text or "").strip()
        if attributes:
            obj["attributes"] = attributes

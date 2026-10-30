"""Train an instance-segmentation model on the outlines annotators drew.

For ``image_annotation`` schemes with polygons, ellipses, freeform outlines or
brush masks. Fine-tunes a torchvision Mask R-CNN from its COCO weights, with
box and mask heads sized to the scheme's labels. Boxes are left out: a box
does not say which pixels belong to the object.

Each predicted mask is traced into a polygon (OpenCV when it is installed,
Potato's own tracer otherwise) and simplified to at most 64 vertices, so the
prelabel is a polygon the annotator can edit point by point. Where a mask
comes out in several pieces, the largest piece is kept.

On a Mac it trains on the CPU: Mask R-CNN hangs on Apple's Metal (mps)
with the torch this was built against. A GPU server is the place for it.

Same licence position as ``torchvision-detect``: torchvision is BSD-3-Clause,
and the COCO-pretrained weights carry COCO's image licences.
"""

from __future__ import annotations

from typing import Any, ClassVar, Dict, List, Tuple

from potato.training.trainers import _segmentation as seg
from potato.training.trainers.torchvision_detect import (INSTALL_HINT,
                                                         TorchvisionDetectTrainer)

ARCHITECTURES = {
    "maskrcnn_resnet50_fpn": "MaskRCNN_ResNet50_FPN_Weights",
    "maskrcnn_resnet50_fpn_v2": "MaskRCNN_ResNet50_FPN_V2_Weights",
}


def _area(ring: List[List[float]]) -> float:
    return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1)
                   in zip(ring, ring[1:] + ring[:1]))) / 2.0


class TorchvisionSegmentTrainer(TorchvisionDetectTrainer):
    name: ClassVar[str] = "torchvision-segment"
    description: ClassVar[str] = (
        "Instance segmentation: fine-tunes a torchvision Mask R-CNN on the "
        "annotated outlines (polygons, ellipses, masks) and predicts polygons.")
    kinds: ClassVar[Tuple[str, ...]] = ("geometry",)
    modalities: ClassVar[Tuple[str, ...]] = ("image",)
    install_hint: ClassVar[str] = INSTALL_HINT
    architectures: ClassVar[Dict[str, str]] = ARCHITECTURES
    default_arch: ClassVar[str] = "maskrcnn_resnet50_fpn"
    unit: ClassVar[str] = "outlines"
    # Measured with torch 2.8 and torchvision 0.23: one Mask R-CNN forward
    # pass took 40 s on mps and the backward pass had not finished a minute
    # later (a full run sat in Metal's waitUntilCompleted for 20 minutes).
    # torchvision-detect is off mps too, for speed.
    mps_ok: ClassVar[bool] = False

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        # Mask R-CNN keeps second guesses for an object at 0.25-0.6 that
        # Faster R-CNN does not; as prelabels they are shapes to delete.
        return {**super().default_params(), "score_threshold": 0.5}

    @classmethod
    def params_schema(cls) -> Dict[str, Any]:
        schema = super().params_schema()
        schema["properties"]["score_threshold"] = dict(
            schema["properties"]["score_threshold"], default=0.5)
        return schema

    def _replace_heads(self, model, n_classes: int) -> None:
        from torchvision.models.detection.mask_rcnn import MaskRCNNPredictor

        predictor = model.roi_heads.mask_predictor
        if predictor.mask_fcn_logits.out_channels != n_classes:
            model.roi_heads.mask_predictor = MaskRCNNPredictor(
                predictor.conv5_mask.in_channels, 256, n_classes)

    def _row_target(self, objects, width: int, height: int,
                    index: Dict[str, int]) -> Dict[str, Any]:
        boxes, classes, outlines = [], [], []
        for obj in objects or []:
            label = str(obj.get("label", ""))
            if label not in index:
                continue
            rings = seg.outline_polygons(obj, width, height)
            if not rings:
                continue
            xs = [p[0] for r in rings for p in r]
            ys = [p[1] for r in rings for p in r]
            x0, y0 = max(0.0, min(xs)), max(0.0, min(ys))
            x1, y1 = min(float(width), max(xs)), min(float(height), max(ys))
            if x1 - x0 < 1 or y1 - y0 < 1:
                continue
            boxes.append([x0, y0, x1, y1])
            classes.append(index[label] + 1)
            outlines.append(rings)
        return {"boxes": boxes, "classes": classes, "outlines": outlines}

    def _target_tensors(self, target: Dict[str, Any], width: int, height: int,
                        flip: bool, device: str) -> Dict[str, Any]:
        import numpy
        import torch

        tensors = super()._target_tensors(target, width, height, flip, device)
        masks = numpy.stack([seg.rasterize(rings, width, height)
                             for rings in target["outlines"]])
        if flip:
            masks = masks[:, :, ::-1].copy()
        tensors["masks"] = torch.from_numpy(masks).to(device)
        return tensors

    def _payload(self, out, keep, labels: List[str], width: int, height: int,
                 version: str) -> List[Dict[str, Any]]:
        masks = (out["masks"][keep][:, 0] > 0.5).cpu().numpy()
        scores = out["scores"][keep].cpu().tolist()
        classes = out["labels"][keep].cpu().tolist()
        shapes = []
        for mask, score, cls in sorted(zip(masks, scores, classes),
                                       key=lambda t: -t[1]):
            if not 1 <= int(cls) <= len(labels):
                continue
            rings = seg.mask_polygons(mask)
            if not rings:
                continue
            shape = seg.client_polygon(max(rings, key=_area), labels[int(cls) - 1],
                                       score, width, height, version)
            if shape:
                shapes.append(shape)
        return shapes

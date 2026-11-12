"""
Exporters for ``geo_annotation`` schemes.

``geojson``
    Every feature every annotator drew, as RFC 7946 GeoJSON in EPSG:4326,
    normalised again on the way out (closed rings, right-hand winding,
    coordinates in range). Each feature's properties gain ``item_id``,
    ``user_id`` and ``schema``. classify_region answers get their region's
    geometry back from the basemap outline. ``--option layout=per_item``
    (default) writes ``geojson/<item>.geojson``; ``layout=single`` writes one
    ``geo_annotations.geojson``.

``geo_overlap``
    The draw-a-map aggregate (see :mod:`potato.geo.overlap`): for each item,
    scheme and label (``group_by=label``, the default) or typed name
    (``group_by=text`` / ``label_text``), a grid of cells holding the share of
    participants whose polygons cover each cell, as GeoJSON cell polygons and
    a PNG preview, plus:

    * ``geo_overlap_summary.csv`` -- one row per heat map;
    * ``geo_names.csv`` -- every drawn feature with its label, typed name,
      area and label point;
    * ``geo_name_counts.csv`` -- how many participants used each name;
    * ``geo_regions.csv`` (classify_region schemes) -- per region and label,
      how many participants chose it and the share.

    Options: ``cell_size`` (degrees), ``cells`` (cells along the longer side
    of the extent, default 100), ``extent=min_lon,min_lat,max_lon,max_lat``,
    ``group_by``, ``schema`` (one scheme only).
"""

from __future__ import annotations

import csv
import json
import os
import re
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult


def _geo_schemes(context: ExportContext) -> Dict[str, dict]:
    return {s["name"]: s for s in context.schemas or []
            if isinstance(s, dict) and s.get("annotation_type") == "geo_annotation"}


def _records(context: ExportContext, schemes: Dict[str, dict]) -> Iterable[Tuple[str, str, str, Any, Dict]]:
    """``(user_id, item_id, schema, labels_entry, extra_properties)`` for every stored answer."""
    for ann in context.annotations or []:
        labels = ann.get("labels") or {}
        for name in schemes:
            if name in labels:
                yield (str(ann.get("user_id", "")), str(ann.get("instance_id", "")), name,
                       labels[name], {})
    for rec in context.phase_responses or []:
        name = rec.get("schema")
        if name in schemes and rec.get("value") and not rec.get("superseded"):
            item = f"{rec.get('phase', '')}/{rec.get('page', '')}"
            yield (str(rec.get("user_id", "")), item, name, rec.get("value"),
                   {"phase": rec.get("phase"), "page": rec.get("page")})


def _slug(text: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", str(text)).strip("-.")
    return s[:80] or "x"


def _norm_name(text: Any) -> str:
    return " ".join(str(text or "").split()).casefold()


class _Regions:
    """Region outlines per (scheme, item), read once."""

    def __init__(self, context: ExportContext, warnings: List[str]):
        self.context = context
        self.warnings = warnings
        self._scheme: Dict[str, Optional[dict]] = {}

    def get(self, scheme: dict, item_id: str) -> Optional[dict]:
        from potato.geo.scheme import item_basemap_regions, scheme_regions
        item = (self.context.items or {}).get(item_id)
        per_item = item_basemap_regions(scheme, item)
        if per_item:
            return per_item
        name = scheme["name"]
        if name not in self._scheme:
            task_dir = (self.context.config or {}).get("task_dir") or os.getcwd()
            try:
                self._scheme[name] = scheme_regions(scheme, task_dir)
            except Exception as e:  # missing or unreadable outline
                self.warnings.append(f"{name}: basemap outline not read ({e})")
                self._scheme[name] = None
        return self._scheme[name]


def _features(context: ExportContext, schemes: Dict[str, dict], warnings: List[str],
              regions: _Regions) -> List[Dict[str, Any]]:
    """Every stored feature, normalised, with item/user/schema properties."""
    from potato.geo.scheme import answer_features
    out = []
    for uid, iid, name, entry, extra in _records(context, schemes):
        scheme = schemes[name]
        feats, why = answer_features(entry, name)
        warnings.extend(f"{name} / {uid} / {iid}: {w}" for w in why)
        task = scheme.get("task", "draw")
        outline = regions.get(scheme, iid) if task == "classify_region" else None
        by_region = {f["id"]: f for f in (outline or {}).get("features", [])}
        for i, f in enumerate(feats):
            props = dict(f.get("properties") or {})
            fid = f.get("id", f"f{i + 1}")
            geometry = f.get("geometry")
            if task == "classify_region":
                region = by_region.get(str(props.get("region")))
                geometry = region["geometry"] if region else None
                if region is None:
                    warnings.append(f"{name}: region {props.get('region')!r} is not in the basemap outline")
            props.update({"item_id": iid, "user_id": uid, "schema": name, "feature_id": fid}, **{
                k: v for k, v in extra.items() if v is not None})
            out.append({"type": "Feature", "id": f"{uid}:{iid}:{name}:{fid}",
                        "geometry": geometry, "properties": props})
    return out


class GeoJSONExporter(BaseExporter):
    format_name = "geojson"
    description = "Map annotations (geo_annotation) as RFC 7946 GeoJSON, per item or in one file"
    file_extensions = [".geojson"]

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        if not _geo_schemes(context):
            return False, "No geo_annotation scheme in this project"
        if not context.annotations and not context.phase_responses:
            return False, "No annotations to export"
        return True, ""

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        options = options or {}
        layout = options.get("layout", "per_item")
        if layout not in ("per_item", "single"):
            return ExportResult(success=False, format_name=self.format_name,
                                errors=["layout must be per_item or single"])
        schemes = _geo_schemes(context)
        warnings: List[str] = []
        feats = _features(context, schemes, warnings, _Regions(context, warnings))
        os.makedirs(output_path, exist_ok=True)
        files = []
        if layout == "single":
            path = os.path.join(output_path, "geo_annotations.geojson")
            _write_fc(path, feats)
            files.append(path)
        else:
            by_item: Dict[str, List[dict]] = defaultdict(list)
            for f in feats:
                by_item[f["properties"]["item_id"]].append(f)
            folder = os.path.join(output_path, "geojson")
            os.makedirs(folder, exist_ok=True)
            used = set()
            for iid, group in sorted(by_item.items()):
                base = _slug(iid)
                stem, n = base, 2
                while stem in used:
                    stem, n = f"{base}-{n}", n + 1
                used.add(stem)
                path = os.path.join(folder, f"{stem}.geojson")
                _write_fc(path, group)
                files.append(path)
        return ExportResult(success=True, format_name=self.format_name, files_written=files,
                            warnings=sorted(set(warnings)),
                            stats={"num_features": len(feats),
                                   "num_items": len({f["properties"]["item_id"] for f in feats})})


def _write_fc(path: str, features: List[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f, ensure_ascii=False)


def _write_csv(path: str, columns: List[str], rows: Iterable[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _parse_extent(text: str) -> List[float]:
    parts = [float(p) for p in str(text).split(",")]
    if len(parts) != 4:
        raise ValueError("extent must be min_lon,min_lat,max_lon,max_lat")
    return parts


class GeoOverlapExporter(BaseExporter):
    format_name = "geo_overlap"
    description = ("Draw-a-map heat maps: share of participants whose polygons cover each grid cell "
                   "(GeoJSON + PNG), with CSVs of the typed names")
    file_extensions = [".geojson", ".png", ".csv"]

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        return GeoJSONExporter().can_export(context)

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        from potato.geo.geojson import area_km2, bbox, centroid, polygons_of
        from potato.geo.overlap import coverage, grid_features, make_grid, render_preview
        from potato.geo.png import write_png

        options = options or {}
        group_by = options.get("group_by", "label")
        if group_by not in ("label", "text", "label_text"):
            return ExportResult(success=False, format_name=self.format_name,
                                errors=["group_by must be label, text or label_text"])
        try:
            cell_size = float(options["cell_size"]) if options.get("cell_size") else None
            cells = int(options.get("cells", 100))
            fixed_extent = _parse_extent(options["extent"]) if options.get("extent") else None
        except (TypeError, ValueError) as e:
            return ExportResult(success=False, format_name=self.format_name, errors=[str(e)])

        schemes = _geo_schemes(context)
        if options.get("schema"):
            schemes = {k: v for k, v in schemes.items() if k == options["schema"]}
            if not schemes:
                return ExportResult(success=False, format_name=self.format_name,
                                    errors=[f"no geo_annotation scheme named {options['schema']!r}"])
        warnings: List[str] = []
        regions = _Regions(context, warnings)
        feats = _features(context, schemes, warnings, regions)
        os.makedirs(output_path, exist_ok=True)
        files: List[str] = []

        # --- names -----------------------------------------------------------
        name_rows = []
        name_counts: Dict[Tuple[str, str, str], Dict[str, set]] = defaultdict(lambda: {"users": set(), "n": set()})
        for f in feats:
            p = f["properties"]
            if schemes[p["schema"]].get("task", "draw") == "classify_region":
                continue
            c = centroid(f["geometry"])
            name_rows.append({
                "user_id": p["user_id"], "item_id": p["item_id"], "schema": p["schema"],
                "feature_id": p["feature_id"], "label": p.get("label", ""), "text": p.get("text", ""),
                "normalised_text": _norm_name(p.get("text")),
                "geometry_type": (f["geometry"] or {}).get("type", ""),
                "area_km2": round(area_km2(f["geometry"]), 3),
                "label_lon": round(c[0], 6) if c else "", "label_lat": round(c[1], 6) if c else "",
                "source": p.get("source", "")})
            key = (p["schema"], p.get("label", ""), _norm_name(p.get("text")))
            name_counts[key]["users"].add(p["user_id"])
            name_counts[key]["n"].add(f["id"])
        path = os.path.join(output_path, "geo_names.csv")
        _write_csv(path, ["user_id", "item_id", "schema", "feature_id", "label", "text", "normalised_text",
                          "geometry_type", "area_km2", "label_lon", "label_lat", "source"], name_rows)
        files.append(path)
        path = os.path.join(output_path, "geo_name_counts.csv")
        _write_csv(path, ["schema", "label", "normalised_text", "participants", "features"], [
            {"schema": s, "label": l, "normalised_text": t, "participants": len(v["users"]),
             "features": len(v["n"])}
            for (s, l, t), v in sorted(name_counts.items(), key=lambda kv: (kv[0][0], -len(kv[1]["users"]), kv[0]))])
        files.append(path)

        # --- heat maps ---------------------------------------------------------
        polys: Dict[Tuple[str, str], List[dict]] = defaultdict(list)    # (item, schema) -> polygon features
        for f in feats:
            p = f["properties"]
            if schemes[p["schema"]].get("task", "draw") == "classify_region":
                continue
            if polygons_of(f["geometry"]):
                polys[(p["item_id"], p["schema"])].append(f)
        folder = os.path.join(output_path, "geo_overlap")
        summary = []
        used = set()
        for (iid, name), group_feats in sorted(polys.items()):
            scheme = schemes[name]
            respondents = len({f["properties"]["user_id"] for f in group_feats})
            outline = regions.get(scheme, iid)
            extent = fixed_extent or self._extent(scheme, context.items.get(iid), outline,
                                                  [f["geometry"] for f in group_feats])
            try:
                grid = make_grid(extent, cell_size=cell_size, cells=cells)
            except ValueError as e:
                warnings.append(f"{name} / {iid}: {e}")
                continue
            if grid.nx * grid.ny > 4_000_000:
                warnings.append(f"{name} / {iid}: grid of {grid.nx}x{grid.ny} cells is too large; "
                                "raise cell_size or lower cells")
                continue
            groups: Dict[str, Dict[str, List[dict]]] = defaultdict(lambda: defaultdict(list))
            for f in group_feats:
                p = f["properties"]
                key = {"label": p.get("label", ""), "text": _norm_name(p.get("text")),
                       "label_text": f"{p.get('label', '')} | {_norm_name(p.get('text'))}"}[group_by]
                groups[key][p["user_id"]].append(f["geometry"])
            os.makedirs(folder, exist_ok=True)
            for key, by_user in sorted(groups.items()):
                counts = coverage(by_user, grid)
                share = counts / respondents if respondents else counts * 0.0
                stem = base = _slug(f"{iid}__{name}__{key or 'unnamed'}")
                n = 2
                while stem in used:
                    stem, n = f"{base}-{n}", n + 1
                used.add(stem)
                gpath = os.path.join(folder, stem + ".geojson")
                _write_fc(gpath, grid_features(counts, respondents, grid, {
                    "item_id": iid, "schema": name, "group_by": group_by, "group": key}))
                ppath = os.path.join(folder, stem + ".png")
                outlines = [f["geometry"] for f in (outline or {}).get("features", [])]
                write_png(ppath, render_preview(share, grid, outlines))
                files += [gpath, ppath]
                summary.append({
                    "item_id": iid, "schema": name, "group_by": group_by, "group": key,
                    "respondents": respondents, "participants_in_group": len(by_user),
                    "polygons": sum(len(polygons_of(g)) for gs in by_user.values() for g in gs),
                    "cells_covered": int((counts > 0).sum()),
                    "max_share": round(float(share.max()), 6) if counts.size else 0.0,
                    "cell_size_deg": round(grid.dx, 9), "grid": f"{grid.nx}x{grid.ny}",
                    "extent": ",".join(str(round(v, 7)) for v in grid.extent),
                    "geojson": os.path.relpath(gpath, output_path), "png": os.path.relpath(ppath, output_path)})
        path = os.path.join(output_path, "geo_overlap_summary.csv")
        _write_csv(path, ["item_id", "schema", "group_by", "group", "respondents", "participants_in_group",
                          "polygons", "cells_covered", "max_share", "cell_size_deg", "grid", "extent",
                          "geojson", "png"], summary)
        files.append(path)

        # --- classify_region shares --------------------------------------------
        region_rows = self._region_shares(feats, schemes)
        if region_rows:
            path = os.path.join(output_path, "geo_regions.csv")
            _write_csv(path, ["item_id", "schema", "region", "region_name", "label", "count",
                              "respondents", "share"], region_rows)
            files.append(path)

        return ExportResult(success=True, format_name=self.format_name, files_written=files,
                            warnings=sorted(set(warnings)),
                            stats={"num_heatmaps": len(summary), "num_features": len(name_rows),
                                   "num_region_rows": len(region_rows)})

    @staticmethod
    def _extent(scheme: dict, item: Optional[dict], outline: Optional[dict],
                geoms: List[dict]) -> List[float]:
        from potato.geo.geojson import bbox
        if outline and outline.get("features"):
            b = bbox(f["geometry"] for f in outline["features"])
            if b:
                return b
        for source in ((scheme.get("basemap") or {}),
                       (item or {}).get(scheme.get("basemap_field") or "") if item else None):
            if isinstance(source, dict) and source.get("image") and source.get("extent"):
                return list(source["extent"])
        b = bbox(geoms)
        if b is None:
            raise ValueError("no polygons")
        pad_x = (b[2] - b[0]) * 0.02 or 0.01
        pad_y = (b[3] - b[1]) * 0.02 or 0.01
        return [max(-180, b[0] - pad_x), max(-90, b[1] - pad_y), min(180, b[2] + pad_x), min(90, b[3] + pad_y)]

    @staticmethod
    def _region_shares(feats: List[dict], schemes: Dict[str, dict]) -> List[dict]:
        votes: Dict[Tuple[str, str], Dict[Tuple[str, str], set]] = defaultdict(lambda: defaultdict(set))
        names: Dict[Tuple[str, str, str], str] = {}
        respondents: Dict[Tuple[str, str], set] = defaultdict(set)
        for f in feats:
            p = f["properties"]
            if schemes[p["schema"]].get("task", "draw") != "classify_region":
                continue
            key = (p["item_id"], p["schema"])
            region = str(p.get("region", ""))
            votes[key][(region, p.get("label", ""))].add(p["user_id"])
            names[(p["item_id"], p["schema"], region)] = p.get("region_name", "")
            respondents[key].add(p["user_id"])
        rows = []
        for key, by in sorted(votes.items()):
            n = len(respondents[key])
            for (region, label), users in sorted(by.items()):
                rows.append({"item_id": key[0], "schema": key[1], "region": region,
                             "region_name": names.get((key[0], key[1], region), ""), "label": label,
                             "count": len(users), "respondents": n,
                             "share": round(len(users) / n, 6) if n else 0.0})
        return rows

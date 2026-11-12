"""
Point clustering for ``image_annotation`` landmarks.

Each label's points on an item, from every annotator, are clustered with
DBSCAN. This is the algorithm scikit-learn's ``DBSCAN`` implements and
``panoptes_aggregation.point_reducer_dbscan`` calls, written here with numpy so
it has no extra dependency:

* a point is a *core* point when at least ``min_samples`` points (itself
  included) lie within ``eps`` of it;
* clusters are the connected groups of core points plus the non-core points
  within ``eps`` of one of them (a border point next to two clusters joins the
  one found first, scanning points in input order);
* everything else is noise.

Distances are Euclidean, either in pixels or in image fractions (x divided by
the width, y by the height). For each cluster this reports the centre (mean),
the number of points, the number of distinct annotators, the spread (root mean
squared distance from the centre) and, like panoptes, the sample variance of x
and y and their covariance (``None`` for a one-point cluster).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple


def dbscan_labels(coords: Sequence[Sequence[float]], eps: float,
                  min_samples: int) -> List[int]:
    """Cluster index per point, ``-1`` for noise. Indices follow the order in
    which clusters are found."""
    import numpy as np

    pts = np.asarray(coords, dtype=float).reshape(-1, 2)
    n = len(pts)
    if n == 0:
        return []
    diff = pts[:, None, :] - pts[None, :, :]
    within = np.sqrt((diff ** 2).sum(axis=2)) <= eps
    neighbours = [np.flatnonzero(row) for row in within]
    core = np.array([len(nb) >= min_samples for nb in neighbours])
    labels = np.full(n, -1, dtype=int)
    cluster = 0
    for start in range(n):
        if labels[start] != -1 or not core[start]:
            continue
        labels[start] = cluster
        stack = [start]
        while stack:
            i = stack.pop()
            if not core[i]:
                continue
            for j in neighbours[i]:
                if labels[j] == -1:
                    labels[j] = cluster
                    if core[j]:
                        stack.append(j)
        cluster += 1
    return labels.tolist()


def _stats(points, users) -> Dict[str, Any]:
    import numpy as np

    arr = np.asarray(points, dtype=float).reshape(-1, 2)
    centre = arr.mean(axis=0)
    spread = float(np.sqrt(((arr - centre) ** 2).sum(axis=1).mean()))
    if len(arr) > 1:
        cov = np.cov(arr.T)
        var_x, var_y, cov_xy = float(cov[0, 0]), float(cov[1, 1]), float(cov[0, 1])
    else:
        var_x = var_y = cov_xy = None
    return {"x": float(centre[0]), "y": float(centre[1]), "spread": spread,
            "var_x": var_x, "var_y": var_y, "cov_xy": cov_xy}


def cluster_points(points: Sequence[Tuple[str, float, float]], *,
                   eps: float, eps_unit: str, min_samples: int,
                   size: Optional[Tuple[float, float]]) -> Dict[str, Any]:
    """Cluster one label's points on one item.

    Args:
        points: ``(annotator, x_fraction, y_fraction)`` per point.
        eps, eps_unit, min_samples: see the module docstring.
        size: ``(width, height)`` in pixels, or None when unknown. Required for
            ``eps_unit == "pixels"``.

    Returns:
        ``{"n_points", "n_annotators", "noise", "clusters": [...]}``. Each
        cluster has ``x``/``y`` (fractions), ``x_px``/``y_px`` (None without a
        size), ``size``, ``n_annotators``, ``annotators``, ``spread``
        (fraction units), ``spread_px``, and ``var_x``/``var_y``/``cov_xy`` in
        pixels when the size is known, otherwise in fraction units.

    Raises:
        ValueError: ``eps_unit`` is ``pixels`` and ``size`` is None.
    """
    width, height = size if size else (None, None)
    if eps_unit == "pixels" and not size:
        raise ValueError("pixel eps needs the image size")
    frac = [(float(x), float(y)) for _, x, y in points]
    users = [str(u) for u, _, _ in points]
    space = ([(x * width, y * height) for x, y in frac] if eps_unit == "pixels" else frac)
    labels = dbscan_labels(space, eps, min_samples)
    clusters: List[Dict[str, Any]] = []
    for k in range(max(labels, default=-1) + 1):
        idx = [i for i, label in enumerate(labels) if label == k]
        members = sorted({users[i] for i in idx})
        f_stats = _stats([frac[i] for i in idx], members)
        entry: Dict[str, Any] = {
            "cluster": k,
            "x": f_stats["x"], "y": f_stats["y"],
            "x_px": None, "y_px": None,
            "size": len(idx),
            "n_annotators": len(members),
            "annotators": members,
            "spread": f_stats["spread"],
            "spread_px": None,
            "var_x": f_stats["var_x"], "var_y": f_stats["var_y"], "cov_xy": f_stats["cov_xy"],
        }
        if size:
            p_stats = _stats([(frac[i][0] * width, frac[i][1] * height) for i in idx], members)
            entry.update(x_px=p_stats["x"], y_px=p_stats["y"], spread_px=p_stats["spread"],
                         var_x=p_stats["var_x"], var_y=p_stats["var_y"],
                         cov_xy=p_stats["cov_xy"])
        clusters.append(entry)
    return {
        "n_points": len(frac),
        "n_annotators": len(set(users)),
        "noise": sum(1 for label in labels if label == -1),
        "clusters": clusters,
        "labels": labels,
    }

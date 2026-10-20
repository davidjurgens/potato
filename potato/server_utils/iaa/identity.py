"""
Identity agreement between two annotators' tracks: MOTA, IDF1, ID switches.

Frame-by-frame matching (the spatial and video reports) says whether two
annotators boxed the same things on each frame. It cannot see an identity
error: annotator A tracks two pedestrians who cross, B swaps their ids where
they cross, and every frame still matches. The multi-object-tracking
measures can, and here they are computed between two annotators:

* **MOTA** = 1 - (misses + extra objects + ID switches) / reference
  object-frames. Matching is per frame at the report's IoU threshold. A pair
  matched on an earlier frame stays matched while it still clears the
  threshold (CLEAR MOT, Bernardin and Stiefelhagen 2008), and a reference
  track matched to a different track than last time is an ID switch.
* **IDF1** = 2 IDTP / (A's object-frames + B's object-frames), where IDTP is
  the number of object-frames matched under the one-to-one assignment of A's
  tracks to B's that maximizes it (Ristani et al. 2016).

Neither annotator is ground truth. MOTA and the ID switch count depend on
which side is the reference, so both directions are counted and pooled. IDF1
is the same either way.

A track's objects are given per frame, already interpolated between
keyframes, as ``{frame: [(track_id, object), ...]}``.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

Frames = Dict[int, List[Tuple[str, Any]]]
Similarity = Callable[[Any, Any], float]


def _frame_scores(a: Frames, b: Frames, similarity: Similarity) -> Dict[int, List[List[float]]]:
    """Every frame's a-by-b similarity matrix, computed once.

    The two CLEAR MOT directions and IDTP all read these; computing the
    similarity in each of them tripled the cost, which at KITTI scale (a
    hundred frames of forty cars) is seconds per annotator pair.
    """
    return {frame: [[similarity(obj_a, obj_b) for _tb, obj_b in b[frame]]
                    for _ta, obj_a in a[frame]]
            for frame in set(a) & set(b)}


def _transpose(scores: Dict[int, List[List[float]]], rows: Frames) -> Dict[int, List[List[float]]]:
    out = {}
    for frame, matrix in scores.items():
        width = len(rows.get(frame, []))
        out[frame] = [list(column) for column in zip(*matrix)] if matrix else [[] for _ in range(width)]
    return out


def clear_mot(reference: Frames, other: Frames, similarity: Similarity,
              threshold: float, scores: Optional[Dict[int, List[List[float]]]] = None
              ) -> Dict[str, int]:
    """Misses, extra objects and ID switches with ``reference`` as the truth.

    ``scores``: precomputed reference-by-other matrices (``_frame_scores``).
    """
    from potato.server_utils.iaa.geometry import match_instances

    if scores is None:
        scores = _frame_scores(reference, other, similarity)
    partner: Dict[str, str] = {}
    counts = {"reference": 0, "misses": 0, "extra": 0, "id_switches": 0}
    for frame in sorted(set(reference) | set(other)):
        ref_here, other_here = reference.get(frame, []), other.get(frame, [])
        counts["reference"] += len(ref_here)
        matrix = scores.get(frame)
        index_of = {track: j for j, (track, _obj) in enumerate(other_here)}
        matched: Dict[int, int] = {}
        for i, (track, _obj) in enumerate(ref_here):
            j = index_of.get(partner.get(track))
            if (j is not None and j not in matched.values()
                    and matrix[i][j] >= threshold):
                matched[i] = j
        rest_ref = [i for i in range(len(ref_here)) if i not in matched]
        taken = set(matched.values())
        rest_other = [j for j in range(len(other_here)) if j not in taken]
        pairs, _a, _b = match_instances(rest_ref, rest_other, threshold,
                                        sim_fn=lambda i, j: matrix[i][j])
        for a, b, _score in pairs:
            i, j = rest_ref[a], rest_other[b]
            track, other_track = ref_here[i][0], other_here[j][0]
            if track in partner and partner[track] != other_track:
                counts["id_switches"] += 1
            partner[track] = other_track
            matched[i] = j
        counts["misses"] += len(ref_here) - len(matched)
        counts["extra"] += len(other_here) - len(matched)
    return counts


def _max_assignment(weights: List[List[int]]) -> int:
    """The largest total weight of a one-to-one assignment of rows to columns."""
    if not weights or not weights[0]:
        return 0
    try:
        from scipy.optimize import linear_sum_assignment  # type: ignore
        rows, cols = linear_sum_assignment([[-w for w in row] for row in weights])
        return int(sum(weights[r][c] for r, c in zip(rows.tolist(), cols.tolist())))
    except ImportError:
        order = sorted(((w, r, c) for r, row in enumerate(weights)
                        for c, w in enumerate(row) if w > 0), reverse=True)
        used_r, used_c, total = set(), set(), 0
        for w, r, c in order:
            if r not in used_r and c not in used_c:
                used_r.add(r)
                used_c.add(c)
                total += w
        return total


def id_true_positives(a: Frames, b: Frames, similarity: Similarity, threshold: float,
                      scores: Optional[Dict[int, List[List[float]]]] = None) -> int:
    """IDTP: object-frames matched under the best track-to-track assignment."""
    if scores is None:
        scores = _frame_scores(a, b, similarity)
    tracks_a = sorted({t for objs in a.values() for t, _o in objs})
    tracks_b = sorted({t for objs in b.values() for t, _o in objs})
    row = {t: i for i, t in enumerate(tracks_a)}
    col = {t: j for j, t in enumerate(tracks_b)}
    weights = [[0] * len(tracks_b) for _ in tracks_a]
    for frame, matrix in scores.items():
        for i, (track_a, _oa) in enumerate(a[frame]):
            for j, (track_b, _ob) in enumerate(b[frame]):
                if matrix[i][j] >= threshold:
                    weights[row[track_a]][col[track_b]] += 1
    return _max_assignment(weights)


def pair_counts(a: Frames, b: Frames, similarity: Similarity,
                threshold: float) -> Dict[str, Any]:
    """Everything the report pools, for one pair of annotators on one item.

    The similarity runs once per object pair on a shared frame.
    """
    scores = _frame_scores(a, b, similarity)
    return {"a_as_reference": clear_mot(a, b, similarity, threshold, scores),
            "b_as_reference": clear_mot(b, a, similarity, threshold, _transpose(scores, b)),
            "idtp": id_true_positives(a, b, similarity, threshold, scores),
            "object_frames": (sum(len(v) for v in a.values())
                              + sum(len(v) for v in b.values()))}


def identity_report(pairs: Iterable[Dict[str, Any]], threshold: float) -> Dict[str, Any]:
    """MOTA, IDF1 and ID switches pooled over annotator pairs.

    Pooled over object-frames, as the tracking benchmarks pool over
    sequences, so a long sequence weighs more than a short one. ``id_switches``
    is per direction (the two directions' total halved).
    """
    pairs = list(pairs)
    reference = errors = switches = idtp = object_frames = 0
    for pair in pairs:
        for side in ("a_as_reference", "b_as_reference"):
            counts = pair[side]
            reference += counts["reference"]
            errors += counts["misses"] + counts["extra"] + counts["id_switches"]
            switches += counts["id_switches"]
        idtp += pair["idtp"]
        object_frames += pair["object_frames"]
    if not pairs or not object_frames:
        return {"n_pairs": len(pairs), "match_iou": threshold,
                "note": "No pair of annotators has tracks on the same item yet."}
    return {"mota": 1.0 - errors / reference if reference else None,
            "idf1": 2.0 * idtp / object_frames,
            "id_switches": switches / 2.0,
            "n_pairs": len(pairs),
            "n_object_frames": object_frames,
            "match_iou": threshold}


def video_track_frames(tracks: List[dict]) -> Frames:
    """A video_annotation value's tracks as normalized boxes on every frame."""
    from potato.server_utils.iaa.attribute_agreement import _box_at, track_canonical

    out: Frames = {}
    for index, track in enumerate(tracks):
        canonical = track_canonical(track)
        if canonical is None:
            continue
        # Position as well as id: two tracks saved under one id (a hand-edited
        # or merged file) are still two tracks, and keyed by id alone each
        # frame would count an ID switch between them.
        track_id = f"{index}:{track.get('id') or ''}"
        for frame in range(canonical["start"], canonical["end"] + 1):
            box = _box_at(canonical["frames"], frame)
            if box:
                out.setdefault(frame, []).append((track_id, box))
    return out


def video_identity(rows: Dict[str, Dict[str, Any]], threshold: float = 0.5
                   ) -> Optional[Dict[str, Any]]:
    """The identity report for a video_annotation scheme, or None with no tracks."""
    import itertools
    from potato.server_utils.iaa.attribute_agreement import _iou, track_objects

    pairs = []
    any_tracks = False
    for per_user in rows.values():
        frames = {uid: video_track_frames(track_objects(v)) for uid, v in per_user.items()}
        # An annotator with no tracks on an item someone else tracked is
        # paired too: every one of the other's object-frames is a miss.
        if not any(frames.values()):
            continue
        any_tracks = True
        for (_ua, a), (_ub, b) in itertools.combinations(sorted(frames.items()), 2):
            pairs.append(pair_counts(a, b, _iou, threshold))
    if not any_tracks:
        return None
    return identity_report(pairs, threshold)

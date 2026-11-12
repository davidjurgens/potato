"""
Near-duplicate detection: which items are the same item twice.

Practitioners describe dedup as surprisingly fiddly and re-hand-roll it per
project, and the concrete case they name is consecutive video frames -- a
thousand items that are one item, eating a thousand annotations' worth of
budget and inflating agreement, because two annotators trivially agree about
the same picture shown twice.

This is data curation, not model training. It is the one piece of the
annotate-train-export pipeline that is legitimately ours.

Two modes, and the choice between them is not a detail
------------------------------------------------------
**Perceptual hash (dHash)** for images. Cheap, model-free, and *correct* for
near-identical frames: dHash compares adjacent-pixel gradients, so it is
robust to re-encoding, mild scaling and small brightness shifts, and it
distinguishes two similar-looking scenes that differ in layout. Embeddings do
not: two different frames of the same scene sit close in embedding space by
design, which is what you want for "find me more like this" and exactly wrong
for "is this the same picture".

**Embeddings** for the semantic case -- same scene from a different angle,
same sentence reworded -- where a hash is useless because the pixels or
characters genuinely differ.

The default is the hash. Reaching for the embedding index first is the mistake
that makes dedup "surprisingly tricky": it produces groups that are related
rather than duplicated, and a human has to unpick every one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

#: Side length of the dHash grid. 8 gives a 64-bit hash, which is the standard
#: choice: small enough to compare in one integer operation, large enough that
#: unrelated images collide vanishingly rarely.
HASH_SIZE = 8

#: Default Hamming distance under which two hashes are called duplicates.
#: 5/64 bits is the conventional near-duplicate threshold -- 0 catches only
#: byte-identical re-encodings, and past ~10 unrelated images start joining.
DEFAULT_MAX_DISTANCE = 5

#: Default cosine similarity for the semantic mode. Deliberately high: at 0.9
#: an embedding index returns things that are *related*, and a duplicate group
#: full of merely-related items is worse than no grouping at all, because
#: someone has to check each one.
DEFAULT_MIN_SIMILARITY = 0.97


@dataclass
class DuplicateGroup:
    """Items judged to be the same item."""

    #: The item kept if the group is collapsed. First by id, so the choice is
    #: stable across runs rather than an artefact of iteration order.
    keeper: str
    duplicates: List[str] = field(default_factory=list)
    #: "phash" or "embedding" -- which measure grouped them, because the two
    #: mean different things and a reviewer needs to know which they are
    #: looking at.
    method: str = "phash"

    @property
    def size(self) -> int:
        return 1 + len(self.duplicates)

    @property
    def members(self) -> List[str]:
        return [self.keeper] + list(self.duplicates)

    def to_dict(self) -> dict:
        return {
            "keeper": self.keeper,
            "duplicates": list(self.duplicates),
            "members": self.members,
            "size": self.size,
            "method": self.method,
        }


# ---------------------------------------------------------------- hashing


def dhash(image, hash_size: int = HASH_SIZE) -> Optional[int]:
    """
    Difference hash of a PIL image, as an integer.

    Compares each pixel with its right-hand neighbour on a small greyscale
    grid, so the hash encodes *gradients* rather than absolute values. That is
    what makes it survive re-encoding and brightness shifts while still
    telling two different scenes apart -- the property an embedding does not
    have.

    Returns None if the image cannot be read; a corrupt file in a dataset
    should cost its own row, not the whole scan.
    """
    try:
        from PIL import Image

        # LANCZOS by name, not by the integer 1. Pillow's resampling constants
        # have moved between releases, and a wrong one silently changes every
        # hash -- which turns a duplicate scan into a differently-wrong
        # duplicate scan rather than an error anyone would notice.
        resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
        grid = image.convert("L").resize((hash_size + 1, hash_size),
                                         resample=resample)
        # tobytes() rather than getdata(): for mode "L" it is the same pixel
        # sequence, and getdata() is deprecated for removal in Pillow 14.
        pixels = list(grid.tobytes())
    except Exception:
        logger.debug("Could not hash an image", exc_info=True)
        return None

    bits = 0
    for row in range(hash_size):
        offset = row * (hash_size + 1)
        for col in range(hash_size):
            bits <<= 1
            if pixels[offset + col] > pixels[offset + col + 1]:
                bits |= 1
    return bits


def dhash_path(path: str, hash_size: int = HASH_SIZE) -> Optional[int]:
    """dHash the image at ``path``, or None if it cannot be opened."""
    try:
        from PIL import Image
    except ImportError:
        logger.warning(
            "Near-duplicate detection needs Pillow for perceptual hashing. "
            "Install it with `pip install Pillow`, or use the embedding mode.")
        return None
    try:
        with Image.open(path) as image:
            return dhash(image, hash_size)
    except Exception:
        logger.debug("Could not open %s for hashing", path, exc_info=True)
        return None


def hamming(a: int, b: int) -> int:
    """Number of differing bits. The distance dHash groups on."""
    return bin(a ^ b).count("1")


# --------------------------------------------------------------- grouping


def group_by_hash(hashes: Dict[str, int],
                  max_distance: int = DEFAULT_MAX_DISTANCE
                  ) -> List[DuplicateGroup]:
    """
    Group items whose hashes are within ``max_distance`` bits.

    Transitive by construction: A near B and B near C puts all three in one
    group even when A and C are further apart than the threshold. That is the
    right behaviour for the case this exists for -- a slow pan across a video
    produces a chain of frames each close to the next, and splitting it into
    overlapping pairs would hand a reviewer the same frames several times.

    Comparison is all-pairs, which is quadratic. Fine for the tens of
    thousands of items a Potato project holds, and the honest limit to state
    rather than to hide behind an approximate index that changes the answer.
    """
    ids = sorted(hashes)
    parent = {i: i for i in ids}

    def find(node):
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for index, left in enumerate(ids):
        for right in ids[index + 1:]:
            if hamming(hashes[left], hashes[right]) <= max_distance:
                union(left, right)

    clusters: Dict[str, List[str]] = {}
    for i in ids:
        clusters.setdefault(find(i), []).append(i)

    groups = []
    for members in clusters.values():
        if len(members) < 2:
            continue
        members.sort()
        groups.append(DuplicateGroup(keeper=members[0],
                                     duplicates=members[1:],
                                     method="phash"))
    # Biggest first: a group of forty frames is the one worth acting on.
    return sorted(groups, key=lambda g: (-g.size, g.keeper))


def group_by_embedding(index, ids: Sequence[str],
                       min_similarity: float = DEFAULT_MIN_SIMILARITY
                       ) -> List[DuplicateGroup]:
    """
    Group items whose embeddings are at least ``min_similarity`` apart.

    The semantic mode: same scene from another angle, same sentence reworded.
    Use it when the pixels or characters genuinely differ, and keep the
    threshold high -- at a typical retrieval threshold this returns things
    that are merely *related*, and a duplicate group full of related items
    costs a reviewer more than no grouping at all.
    """
    from potato.curation.index import cosine

    vectors = {}
    for instance_id in ids:
        vector = index.get(instance_id)
        if vector is not None:
            vectors[str(instance_id)] = vector

    ordered = sorted(vectors)
    parent = {i: i for i in ordered}

    def find(node):
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for position, left in enumerate(ordered):
        for right in ordered[position + 1:]:
            if cosine(vectors[left], vectors[right]) >= min_similarity:
                ra, rb = find(left), find(right)
                if ra != rb:
                    parent[max(ra, rb)] = min(ra, rb)

    clusters: Dict[str, List[str]] = {}
    for i in ordered:
        clusters.setdefault(find(i), []).append(i)

    groups = [DuplicateGroup(keeper=sorted(m)[0], duplicates=sorted(m)[1:],
                             method="embedding")
              for m in clusters.values() if len(m) >= 2]
    return sorted(groups, key=lambda g: (-g.size, g.keeper))


# ------------------------------------------------------------------ report


def summarize(groups: Sequence[DuplicateGroup], n_items: int) -> Dict[str, Any]:
    """
    The numbers that make the case for acting on a duplicate report.

    ``wasted_budget`` is the point: every duplicate is an annotation someone
    will pay for twice, and it also inflates agreement, because two annotators
    trivially agree about the same item shown twice.
    """
    duplicates = sum(len(g.duplicates) for g in groups)
    return {
        "n_items": n_items,
        "n_groups": len(groups),
        "n_duplicates": duplicates,
        "duplicate_rate": (duplicates / n_items) if n_items else 0.0,
        "largest_group": max((g.size for g in groups), default=0),
        "groups": [g.to_dict() for g in groups],
        "note": (
            f"{duplicates} of {n_items} item(s) duplicate another. Each is an "
            f"annotation budget paid twice, and each also inflates agreement: "
            f"two annotators trivially agree about the same item shown twice."
        ) if duplicates else "No near-duplicates found.",
    }


def find_duplicates(item_state_manager, config: Dict[str, Any],
                    method: str = "phash",
                    max_distance: int = DEFAULT_MAX_DISTANCE,
                    min_similarity: float = DEFAULT_MIN_SIMILARITY,
                    media_root: Optional[str] = None,
                    index=None) -> Dict[str, Any]:
    """
    Scan a project for near-duplicates.

    Args:
        method: ``"phash"`` (default, images) or ``"embedding"`` (semantic).
        media_root: Directory the item paths are relative to. Defaults to the
            project's ``task_dir``.

    Returns a :func:`summarize` report. A project whose items cannot be hashed
    -- text with no images, or Pillow absent -- reports zero groups and says
    why, rather than silently reporting "no duplicates" and being believed.
    """
    import os

    items = list(item_state_manager.iter_items())
    n_items = len(items)

    if method == "embedding":
        if index is None:
            return dict(summarize([], n_items),
                        note="Embedding mode needs a built curation index. "
                             "Build it from /admin/catalog first.")
        return summarize(
            group_by_embedding(index, [iid for iid, _ in items],
                               min_similarity),
            n_items)

    root = media_root or config.get("task_dir", ".")
    source_keys = _source_keys(config)

    hashes: Dict[str, int] = {}
    unreadable = 0
    for instance_id, item in items:
        data = item.get_data() if hasattr(item, "get_data") else {}
        path = _local_path(data, source_keys, root)
        if path is None:
            continue
        digest = dhash_path(path)
        if digest is None:
            unreadable += 1
            continue
        hashes[str(instance_id)] = digest

    report = summarize(group_by_hash(hashes, max_distance), n_items)
    report["n_hashed"] = len(hashes)
    report["n_unreadable"] = unreadable
    if not hashes:
        report["note"] = (
            "No item could be perceptually hashed -- the project may hold no "
            "local images, or Pillow may not be installed. This is NOT a "
            "finding of zero duplicates.")
    return report


def _source_keys(config: Dict[str, Any]) -> List[str]:
    """Which item fields might hold an image path."""
    keys = []
    for scheme in config.get("annotation_schemes", []) or []:
        for key in ("source_field", "image_key", "video_key"):
            value = scheme.get(key)
            if isinstance(value, str) and value:
                keys.append(value)
    item_props = config.get("item_properties", {}) or {}
    for key in ("image_key", "media_key", "text_key"):
        value = item_props.get(key)
        if isinstance(value, str) and value:
            keys.append(value)
    keys.extend(["image_url", "file_name", "image", "path", "media"])
    seen, ordered = set(), []
    for key in keys:
        if key not in seen:
            seen.add(key)
            ordered.append(key)
    return ordered


def _local_path(data: Dict[str, Any], keys: Iterable[str],
                root: str) -> Optional[str]:
    """
    Resolve an item's image to a readable local path, or None.

    Remote URLs are skipped rather than fetched. Downloading a dataset to
    deduplicate it would turn a local scan into an unbounded network job, and
    nothing about the request suggests the user wants that.
    """
    import os

    if not isinstance(data, dict):
        return None
    for key in keys:
        value = data.get(key)
        if not isinstance(value, str) or not value:
            continue
        if value.startswith(("http://", "https://", "data:")):
            continue
        candidate = value if os.path.isabs(value) else os.path.join(root,
                                                                    value.lstrip("/"))
        if os.path.isfile(candidate):
            return candidate
        # /media/x.png is served from <task_dir>/media/x.png
        alternative = os.path.join(root, "media",
                                   os.path.basename(value))
        if os.path.isfile(alternative):
            return alternative
    return None

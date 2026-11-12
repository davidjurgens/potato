"""
Consensus aggregation across annotators, in the style citizen-science projects
(Zooniverse and others) use after many volunteers have labelled each subject.

* :mod:`.questions` -- vote counts and fractions per answer for radio, select,
  likert and multiselect questions, the top answer, and an agreement flag
  ("retired" / "needs_review"); summary statistics for slider and number.
* :mod:`.points` -- DBSCAN clustering of ``image_annotation`` landmarks per
  label, implemented with numpy (the same algorithm as scikit-learn's DBSCAN,
  which ``panoptes_aggregation`` calls).
* :mod:`.boxes` -- grouping of bounding boxes across annotators by IoU, with a
  median consensus box per group.
* :mod:`.config` -- the ``consensus_aggregation`` config block.

The ``consensus`` exporter (potato/export/consensus_exporter.py) runs all three
and writes CSV and JSON. Nothing here touches server state: every function
takes plain annotation records.
"""

from .config import ConsensusSettings, parse_consensus_config  # noqa: F401

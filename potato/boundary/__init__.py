"""
Boundary Lab: counterfactual boundary probing.

Instead of collecting only point labels (item X -> label Y), Boundary Lab
captures each annotator's *decision boundary*. When a label is committed,
Potato generates minimal counterfactual edits of the text and asks whether
the label survives each edit. Byproducts of ordinary annotation:

- Contrast sets / counterfactually-augmented data (Gardner et al. 2020;
  Kaushik et al. 2020) collected for free during labeling
- Boundary rationales ("what crossed the line") for codebook refinement
- Invariance-probe consistency scores: paraphrases should never flip, so
  flips on invariance probes are a quality-control signal that doesn't
  feel like an attention check
"""

from potato.boundary.config import BoundaryConfig, parse_boundary_config
from potato.boundary.generator import Probe, ProbeGenerator
from potato.boundary.manager import (
    BoundaryManager,
    clear_boundary_manager,
    get_boundary_manager,
    init_boundary_manager,
)
from potato.boundary.routes import boundary_bp

__all__ = [
    "BoundaryConfig",
    "parse_boundary_config",
    "Probe",
    "ProbeGenerator",
    "BoundaryManager",
    "init_boundary_manager",
    "get_boundary_manager",
    "clear_boundary_manager",
    "boundary_bp",
]

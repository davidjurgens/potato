"""
Annotation Importer Base

Defines the contract every annotation-format importer implements, mirroring
``potato/export/base.py`` on the other side of the round trip.

Potato had an export registry, a document format-handler registry, and a trace
converter registry, but no way to read an existing annotation file back in.
That made it impossible to correct model output or migrate off another
platform without preprocessing the data by hand.

Importers produce objects in the shape ``ImageAnnotationManager`` consumes --
built via :func:`potato.export.cv_utils.to_client_object`, never by hand -- so
that anything imported can be rendered, edited, and exported without a
translation layer in between.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ImportedImage:
    """One image and every annotation on it."""

    instance_id: str
    file_name: str
    width: int
    height: int
    #: Client-shaped annotation objects (see cv_utils.to_client_object)
    objects: List[dict] = field(default_factory=list)
    #: Extra per-item fields to carry into the generated data file
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ImportResult:
    """Everything an importer recovered from a source file."""

    images: List[ImportedImage] = field(default_factory=list)
    #: Label definitions for the generated schema config. Each carries at least
    #: ``name``; COCO also supplies ``label_id`` and ``supercategory`` so the
    #: original (often sparse) category IDs survive a round trip.
    labels: List[dict] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)

    #: Tools the generated schema needs, derived from what the file contains.
    tools: List[str] = field(default_factory=list)

    @property
    def num_objects(self) -> int:
        return sum(len(img.objects) for img in self.images)


class BaseAnnotationImporter(ABC):
    """Base class for annotation format importers."""

    #: Short name used on the CLI and in the registry, e.g. "coco"
    format_name: str = ""
    #: Human-readable description shown by --list-formats
    description: str = ""
    #: File extensions this format typically uses
    file_extensions: List[str] = []

    @abstractmethod
    def parse(self, data: Any,
              options: Optional[dict] = None) -> ImportResult:
        """
        Parse already-loaded source data into an :class:`ImportResult`.

        Args:
            data: Parsed source document (usually a dict from json.load)
            options: Format-specific options

        Returns:
            ImportResult

        Raises:
            ValueError: If the data is malformed in a way the caller must fix
        """
        raise NotImplementedError

    @abstractmethod
    def detect(self, data: Any) -> bool:
        """
        Return True if ``data`` looks like this format.

        Must be cheap and side-effect free; the registry calls it against every
        registered importer in turn.
        """
        raise NotImplementedError

    def get_format_info(self) -> Dict[str, Any]:
        """Metadata for --list-formats."""
        return {
            "name": self.format_name,
            "description": self.description,
            "file_extensions": list(self.file_extensions),
        }

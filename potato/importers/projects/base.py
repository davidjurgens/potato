"""
Whole-project imports: several questions, several annotators, model suggestions.

The CV and text importers each produce one scheme over one kind of item, with
the source's annotations as a starting point. A Label Studio or Argilla
project is a different shape: a set of questions defined by the tool's own
config, answered by several named people, often with a model's suggestion
beside each answer. Moving such a project means carrying all three across --
the questions as schemes, the people's answers as those people's saved work,
and the suggestions as pre-annotations with the model and score attached.

Answers are held in one canonical shape per scheme type, used for both
suggestions and people's responses, so the writer converts each type in one
place:

    radio        str            the option name
    select       str            the option name
    multiselect  list[str]      option names
    likert       int            the scale point, 1-based
    text         str
    number       int | float
    slider       int | float
    span         list[dict]     {"start", "end", "label"}, code points
    image_annotation list[dict] client-shaped objects (cv_utils.to_client_object)
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


#: Scheme types the writer can store a person's answer for. Anything else is
#: reported by the importer and left out rather than half-written.
SUPPORTED_TYPES = frozenset({
    "radio", "multiselect", "select", "likert", "text", "number", "slider", "span",
    "image_annotation",
})


@dataclass
class ProjectItem:
    instance_id: str
    #: The item's own data columns, written to the data file as they are.
    fields: Dict[str, Any] = field(default_factory=dict)
    #: scheme name -> canonical answer, written as pre-annotations.
    predictions: Dict[str, Any] = field(default_factory=dict)
    #: scheme name -> {"model": ..., "score": ...}: who made each suggestion.
    #: Written beside the predictions so the provenance survives the move even
    #: for scheme types whose stored answer has nowhere to keep it.
    prediction_sources: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    #: annotator -> scheme name -> canonical answer.
    responses: Dict[str, Dict[str, Any]] = field(default_factory=dict)


@dataclass
class ProjectImportResult:
    source_format: str
    schemes: List[dict] = field(default_factory=list)
    items: List[ProjectItem] = field(default_factory=list)
    #: The data column item_properties.text_key points at.
    text_key: str = "text"
    #: An instance_display block, when the item has more than one field to show.
    instance_display: Optional[dict] = None
    #: The source's annotator guidelines, carried into the README.
    guidelines: str = ""
    #: How many people the source study meant each item to get (Argilla's
    #: distribution.min_submitted; for Label Studio, which does not export its
    #: overlap setting, the most annotators any task has). Becomes
    #: max_annotations_per_item when annotators are kept, which is what makes
    #: the items the source study finished count as complete.
    annotations_per_item: Optional[int] = None
    #: annotator name in Potato -> how the source identified them.
    annotator_ids: Dict[str, str] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    #: What was left out and how often, for the summary.
    skipped: Counter = field(default_factory=Counter)
    #: Files to copy into the project: path under the project -> source path
    #: (a TextGrid's audio, say, served from media/).
    media_files: Dict[str, str] = field(default_factory=dict)
    #: Folders media_files may come from. The writer refuses a source whose
    #: real path (symlinks resolved) is outside them; empty means the input
    #: folder (the input itself when it is a folder, else its parent).
    media_roots: List[str] = field(default_factory=list)

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    @property
    def num_responses(self) -> int:
        return sum(len(answers) for item in self.items
                   for answers in item.responses.values())

    @property
    def num_predictions(self) -> int:
        """Model suggestions: each box, region or label, not each item.

        A scheme's suggestion is a list (boxes, species) or one value. Counting
        items reported "4 model suggestion(s)" for 621 BirdNET boxes.
        """
        return sum(len(value) if isinstance(value, list) else 1
                   for item in self.items for value in item.predictions.values())

    @property
    def num_predicted_items(self) -> int:
        return sum(1 for item in self.items if item.predictions)

    def summarize(self) -> Dict[str, Any]:
        return {
            "format": self.source_format,
            "num_items": len(self.items),
            "num_schemes": len(self.schemes),
            "num_annotators": len(self.annotator_ids),
            "num_responses": self.num_responses,
            "num_predictions": self.num_predictions,
            "num_predicted_items": self.num_predicted_items,
            "skipped": dict(self.skipped),
            "warnings": list(self.warnings),
        }


def humanize(name: str) -> str:
    """`overall_quality` -> `Overall quality`, for descriptions a source omits."""
    text = str(name).replace("_", " ").replace("-", " ").strip()
    return text[:1].upper() + text[1:] if text else str(name)


def utf16_to_code_points(text: str, offset: int) -> int:
    """Convert a JavaScript (UTF-16) string offset into a Python one.

    Browser tools count characters in UTF-16 units, so every character outside
    the Basic Multilingual Plane (most emoji) counts twice. Potato stores code
    points, so an unconverted offset lands one character late after each such
    character.
    """
    units = 0
    for index, char in enumerate(text):
        if units >= offset:
            return index
        units += 2 if ord(char) > 0xFFFF else 1
    return len(text)

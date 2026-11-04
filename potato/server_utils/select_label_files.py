"""
Options for a ``select`` from a text file, one per line.

``labels: options/languages.txt`` replaces the list with the file's lines when
the config loads, so everything that reads ``labels`` afterwards (the page,
presentation order, exports, agreement) sees an ordinary list. The file is read
once, at load: editing it takes a restart.

The path is relative to ``task_dir``, then to the config file's directory, and
must resolve inside ``task_dir``. Lines are stripped, blank and
whitespace-only lines are skipped, and a byte-order mark or Windows line
endings are not kept as part of a label. An empty file is refused, and so is a
file that lists one option twice: the scheme stores the option's text, so the
two would be one answer.

The select generator used to read a string ``labels`` itself, relative to the
working directory and with no path check, but validation refused every string
first, so that branch never ran.
"""

from __future__ import annotations

import os
from collections import Counter
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple


def read_label_file(path: str) -> List[str]:
    """The options in a label file, in order. Raises ValueError naming `path`."""
    with open(path, encoding="utf-8-sig") as handle:
        labels = [line.strip() for line in handle]
    labels = [label for label in labels if label]
    if not labels:
        raise ValueError(f"{path} has no options (one per line)")
    repeated = sorted(label for label, n in Counter(labels).items() if n > 1)
    if repeated:
        raise ValueError(
            f"{path} lists these options more than once, so they would be one "
            f"answer: {', '.join(repeated)}")
    return labels


def resolve_select_label_files(schemes: Iterable[Tuple[str, Dict[str, Any]]],
                               task_dir: str,
                               config_file_dir: Optional[str] = None) -> None:
    """Replace a string ``labels`` on each select in `schemes` with the file's lines.

    `schemes` yields (config path, scheme), as in ``annotation_schemes[0]``.
    """
    from potato.server_utils.config_module import (
        ConfigSecurityError, ConfigValidationError, validate_path_security)
    for where, scheme in schemes:
        if (not isinstance(scheme, dict) or scheme.get("annotation_type") != "select"
                or not isinstance(scheme.get("labels"), str)):
            continue
        rel = scheme["labels"]
        if os.path.isabs(rel):
            candidates = [rel]
        else:
            candidates = [os.path.join(base, rel) for base in (task_dir, config_file_dir) if base]
        found = next((p for p in candidates if os.path.isfile(p)), None)
        if found is None:
            raise ConfigValidationError(
                f"{where}.labels: no label file at {rel!r} (looked in "
                f"{', '.join(os.path.abspath(p) for p in candidates)}). Give a list of "
                f"options, or the path of a text file with one option per line.")
        try:
            resolved = validate_path_security(os.path.abspath(found), task_dir)
        except ConfigSecurityError as e:
            raise ConfigSecurityError(f"{where}.labels: {e}") from None
        try:
            scheme["labels"] = read_label_file(resolved)
        except (OSError, UnicodeDecodeError, ValueError) as e:
            raise ConfigValidationError(f"{where}.labels: {e}") from None


def config_schemes(config_data: Dict[str, Any]) -> Iterator[Tuple[str, Dict[str, Any]]]:
    """(path, scheme) for every scheme written in the config itself.

    The places validate_single_annotation_scheme is called from: the top
    level, phases, training, scheme_sets, batch_assignment groups, and the
    segment_schemes nested in any of them.
    """
    def from_list(schemes, prefix):
        for i, scheme in enumerate(schemes if isinstance(schemes, list) else []):
            if not isinstance(scheme, dict):
                continue
            where = f"{prefix}[{i}]"
            yield where, scheme
            yield from from_list(scheme.get("segment_schemes"), f"{where}.segment_schemes")

    yield from from_list(config_data.get("annotation_schemes"), "annotation_schemes")
    phases = config_data.get("phases")
    if isinstance(phases, list):
        for i, phase in enumerate(phases):
            if isinstance(phase, dict):
                yield from from_list(phase.get("annotation_schemes"),
                                     f"phases[{i}].annotation_schemes")
    elif isinstance(phases, dict):
        for name, phase in phases.items():
            if isinstance(phase, dict):
                yield from from_list(phase.get("annotation_schemes"),
                                     f"phases.{name}.annotation_schemes")
    training = config_data.get("training")
    if isinstance(training, dict):
        yield from from_list(training.get("annotation_schemes"), "training.annotation_schemes")
    scheme_sets = config_data.get("scheme_sets")
    if isinstance(scheme_sets, dict):
        for name, members in scheme_sets.items():
            yield from from_list(members, f"scheme_sets['{name}']")
    batch = config_data.get("batch_assignment")
    if isinstance(batch, dict):
        for i, group in enumerate(batch.get("groups") or []):
            if isinstance(group, dict):
                yield from from_list(group.get("schemes"),
                                     f"batch_assignment.groups[{i}].schemes")


def file_schemes(schemes: Any, source: str) -> Iterator[Tuple[str, Dict[str, Any]]]:
    """(path, scheme) for the questions in a phase file."""
    for i, scheme in enumerate(schemes if isinstance(schemes, list) else []):
        if isinstance(scheme, dict):
            yield f"{source}[{i}]", scheme
            for j, sub in enumerate(scheme.get("segment_schemes") or []):
                yield f"{source}[{i}].segment_schemes[{j}]", sub

"""
One parser for every way a data file reaches the item pool.

``data_files``, ``data_sources`` (local, URL, S3, Google Drive, Dropbox) and
``data_directory`` each used to parse files their own way, so one file loaded
differently depending on which config key named it: pandas turned ``007`` into
``7`` and ``NA`` into ``nan`` on one path and not on the other, a malformed
JSONL line raised on one path and was skipped on the others, and a UTF-8 byte
order mark raised on one and silently dropped the first row on another.

The rules here:

- Every CSV/TSV cell is kept exactly as written, as a string. Nothing is
  guessed as a number or a missing value.
- CSV follows RFC 4180 (double quotes, embedded commas and newlines). TSV
  follows the IANA text/tab-separated-values registration, which has no
  quoting: a ``"`` in a TSV cell is part of the text.
- A row with more cells than the header is an error; a short row gets ``""``
  for the missing cells.
- A malformed JSON line is an error that names the line.
- A UTF-8 byte order mark at the start is ignored.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any, Dict, List, Optional

FORMATS = ("json", "jsonl", "csv", "tsv")


class SourceDataError(ValueError):
    """The data itself is malformed (as opposed to the source being unreachable)."""


def strip_bom(text: str) -> str:
    return text[1:] if text.startswith("﻿") else text


def read_text(path: str, encoding: str = "utf-8") -> str:
    """Read a file as text, dropping a UTF-8 byte order mark."""
    if encoding.lower().replace("_", "-") in ("utf-8", "utf8"):
        encoding = "utf-8-sig"
    with open(path, "r", encoding=encoding, newline="") as f:
        return strip_bom(f.read())


def format_for(name: str) -> Optional[str]:
    """The format implied by a file name's extension, or None."""
    ext = name.lower().rsplit(".", 1)[-1] if "." in name else ""
    return ext if ext in FORMATS else None


def parse_json_records(text: str, name: str = "data", json_array: bool = True) -> List[Any]:
    """Parse a JSON array (when ``json_array``) or JSON Lines text.

    A JSON Lines line that holds an array contributes each of its elements.
    """
    text = strip_bom(text)
    if json_array:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        else:
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict):
                return [parsed]
    records: List[Any] = []
    for line_no, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as e:
            raise SourceDataError(f"Invalid JSON at line {line_no} in {name}: {e}") from e
        if isinstance(value, list):
            records.extend(value)
        else:
            records.append(value)
    return records


def parse_delimited(text: str, delimiter: str, name: str = "data") -> List[Dict[str, str]]:
    """Parse CSV (``,``) or TSV (``\\t``) text into rows of verbatim strings."""
    text = strip_bom(text)
    if delimiter == "\t":
        reader = csv.reader(io.StringIO(text, newline=""), delimiter="\t",
                            quoting=csv.QUOTE_NONE)
    else:
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    try:
        header = next(reader)
    except StopIteration:
        return []
    rows: List[Dict[str, str]] = []
    for row in reader:
        if not row or row == [""]:
            continue
        if len(row) > len(header):
            raise SourceDataError(
                f"Row at line {reader.line_num} in {name} has {len(row)} cells "
                f"but the header has {len(header)}"
            )
        row = row + [""] * (len(header) - len(row))
        rows.append(dict(zip(header, row)))
    return rows


def parse_records(text: str, fmt: Optional[str], name: str = "data") -> List[Any]:
    """Parse text in ``fmt`` (json, jsonl, csv, tsv), or detect it when None.

    Detection: a whole-text JSON document, then JSON Lines when the first
    non-blank line is JSON, then CSV.
    """
    text = strip_bom(text)
    if fmt == "csv":
        return parse_delimited(text, ",", name)
    if fmt == "tsv":
        return parse_delimited(text, "\t", name)
    if fmt in ("json", "jsonl"):
        return parse_json_records(text, name, json_array=True)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        pass
    else:
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return [parsed]
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if first.startswith(("{", "[")):
        return parse_json_records(text, name, json_array=False)
    return parse_delimited(text, ",", name)

"""Complete input preflight, independent of renderer dependencies and filesystem writes.

Copyright (c) 2026 Shyam Sridhar and contributors.
SPDX-License-Identifier: Apache-2.0
"""
from __future__ import annotations

import re
from typing import Any

from .charts import validate_chart
from .diagrams import validate_diagram
from .section_schema import SECTION_SCHEMA
from .stories import validate_story


def validate_input(input_data: dict[str, Any]) -> None:
    """Pure preflight: raise ValueError with an input location, without any I/O.

    Validate every supplied rendering field, including nested sections, before
    dispatch can discard unknown content. Optional fields and normal input-mode
    precedence remain supported; arbitrary top-level data can still use the
    JSON fallback. Section field names come from the existing section schema.
    """
    def record(value: Any, where: str, allowed=None) -> dict:
        if not isinstance(value, dict):
            raise ValueError(f"{where}: expected a mapping")
        for key in value:
            if not isinstance(key, str):
                raise ValueError(f"{where}: field names must be strings")
            if allowed is not None and key not in allowed:
                raise ValueError(f"{where}.{key}: unsupported field; content would not be rendered")
        return value

    def sequence(value: Any, where: str) -> list:
        if not isinstance(value, list):
            raise ValueError(f"{where}: expected a list")
        return value

    def text(value: Any, where: str, key: str = "") -> None:
        if key == "num" and type(value) is int:
            return
        if key in ("default", "value") and (value is None or type(value) in (int, float, bool)):
            return
        if not isinstance(value, str):
            expected = "a string or integer" if key == "num" else "a string"
            raise ValueError(f"{where}: expected {expected}")

    def row_list(value: Any, where: str, allowed=None) -> None:
        rows = sequence(value, where)
        for index, row in enumerate(rows):
            location = f"{where}[{index}]"
            record(row, location, allowed)
            if allowed is None:
                # Tables take their columns from the first row. Reject later
                # extra columns rather than silently losing their cell values.
                record(row, location, rows[0])
                for key, cell in row.items():
                    if cell is not None and not isinstance(cell, (str, int, float, bool)):
                        raise ValueError(f"{location}.{key}: expected a scalar table cell")
            else:
                for key, cell in row.items():
                    text(cell, f"{location}.{key}", key)

    active_sections: set[int] = set()

    def sections(value: Any, where: str) -> None:
        for index, section in enumerate(sequence(value, where)):
            location = f"{where}[{index}]"
            record(section, location)
            kind = section.get("kind")
            if not isinstance(kind, str) or kind not in SECTION_SCHEMA:
                raise ValueError(f"{location}.kind: unknown section kind {kind!r}")
            if kind == "diagram":
                validate_diagram(section, location)
                continue
            if kind == "chart":
                validate_chart(section, location)
                continue
            record(section, location, {"kind", *SECTION_SCHEMA[kind]["fields"]})
            if id(section) in active_sections:
                raise ValueError(f"{location}: cyclic section nesting")
            active_sections.add(id(section))
            try:
                for key, item in section.items():
                    field = f"{location}.{key}"
                    if key == "kind":
                        continue
                    if kind == "sec" and key == "body":
                        sections(item, field)
                    elif key == "rows":
                        row_list(item, field, SECTION_SCHEMA[kind].get("row_fields"))
                    elif key in ("meta", "colors"):
                        allowed = ("label", "value") if key == "meta" else ("hex", "name", "role")
                        row_list(item, field, allowed)
                        if key == "colors":
                            for n, color in enumerate(item):
                                _validate_color(color.get("hex", "#000000"), f"{field}[{n}].hex")
                    elif key in ("items", "headers"):
                        for n, entry in enumerate(sequence(item, field)):
                            entry_path = f"{field}[{n}]"
                            if kind == "fit-row" and isinstance(entry, dict):
                                record(entry, entry_path, ("label", "avoid"))
                                if "label" in entry:
                                    text(entry["label"], f"{entry_path}.label")
                                if "avoid" in entry and type(entry["avoid"]) is not bool:
                                    raise ValueError(f"{entry_path}.avoid: expected a boolean")
                            else:
                                text(entry, entry_path)
                    elif key in ("zebra", "tight"):
                        if type(item) is not bool:
                            raise ValueError(f"{field}: expected a boolean")
                    else:
                        text(item, field, key)
            finally:
                active_sections.remove(id(section))

    record(input_data, "input")
    kind = input_data.get("kind")
    if kind == "story":
        validate_story(input_data)
        return
    if kind == "diagram":
        validate_diagram(input_data, "input")
        return
    if kind == "chart":
        validate_chart(input_data, "input")
        return
    for key in ("title", "subtitle", "brand", "breadcrumb", "status_tag", "body_md", "body_html"):
        if key in input_data:
            text(input_data[key], f"input.{key}")
    if "sections" in input_data:
        sections(input_data["sections"], "input.sections")
    if "rows" in input_data:
        row_list(input_data["rows"], "input.rows")


def _validate_color(value: Any, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})", value):
        raise ValueError(f"{field}: expected a hexadecimal CSS color")
    return value

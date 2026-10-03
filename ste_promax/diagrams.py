"""Native, offline technical diagrams with plain-text equivalents (stdlib only).

Layout follows input order, not topological order: cycles are first-class edges.
Dense flow graphs can have crossing lines; numbered edges and the adjacency list
retain their exact meaning. No source text is interpreted as markup or a URL.
"""
from __future__ import annotations

from html import escape
import math
from typing import Any
import unicodedata


DIAGRAM_SCHEMA: dict[str, Any] = {
    "description": (
        "Native directed flow or ordered sequence diagram with accessible inline SVG "
        "and a visible, complete text equivalent. Input order is preserved. "
        "Cycles, feedback, parallel edges, and self-links are supported. "
        "Dense flows may have crossing lines; edge numbers identify relationships. "
        "Unknown fields are rejected. Bounds: 1–16 flow nodes, 0–32 edges, "
        "at most 16 incident edge ends per node (self-links count twice); "
        "1–12 sequence participants and 1–32 messages. IDs: 1–128 characters; "
        "node/participant/message labels: 1–256; optional edge labels: 0–256; "
        "detail/note: up to 512; title/description/caption: up to 4096. "
        "Required text must not be blank. Text must be XML 1.0 compatible. "
        "SVG dimensions must not exceed 32768 CSS pixels on either axis. "
        "Edge/message style is 'solid' (default) or 'dashed': presentation only, "
        "not an evidence classification."
    ),
    "fields": {
        "kind": "Optional literal 'diagram'.",
        "type": "Required: 'flow' or 'sequence'.",
        "title": "Required plain-text accessible name (nonblank, at most 4096 characters).",
        "description": "Required plain-text description (nonblank, at most 4096 characters).",
        "caption": "Optional plain-text caption (at most 4096 characters).",
        "direction": "Flow only: 'LR' (default) or 'TB'; supplied node order sets placement.",
        "nodes": "Flow only, required: 1–16 {id, label, detail?} objects with unique IDs.",
        "edges": (
            "Flow only, required: 0–32 {from, to, label?, style?} objects. Endpoints "
            "must match node IDs. Each node permits at most 16 incident edge ends."
        ),
        "participants": "Sequence only, required: 1–12 {id, label} objects with unique IDs.",
        "messages": (
            "Sequence only, required: 1–32 {from, to, label, note?, style?} objects "
            "in temporal order. Endpoints must match participant IDs."
        ),
    },
    "example": {
        "kind": "diagram",
        "type": "flow",
        "title": "Review feedback",
        "description": "A draft moves to review and can return for revision.",
        "nodes": [{"id": "draft", "label": "Draft"}, {"id": "review", "label": "Review"}],
        "edges": [
            {"from": "draft", "to": "review", "label": "Submit"},
            {"from": "review", "to": "draft", "label": "Revise", "style": "dashed"},
        ],
    },
}

_BG = "#191817"
_PANEL = "#252321"
_TEXT = "#f4f0e8"
_MUTED = "#cbc3b8"
_LINE = "#dcac87"
_BOX = 360
_GAP = 32
_MARGIN = 32
_MAX_EXTENT = 32768


def _object(value: Any, allowed: set[str], required: set[str], location: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{location}: expected an object")
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"{location}: unknown fields {', '.join(sorted(map(repr, unknown)))}")
    missing = required - set(value)
    if missing:
        raise ValueError(f"{location}: missing fields {', '.join(sorted(missing))}")


def _text(value: Any, location: str, maximum: int, required: bool = False) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{location}: expected plain text")
    if len(value) > maximum or (required and not value.strip()):
        raise ValueError(f"{location}: expected {'1' if required else '0'}–{maximum} characters"
                         + (" of nonblank text" if required else ""))
    for char in value:
        code = ord(char)
        if not (code in (9, 10, 13) or 0x20 <= code <= 0xD7FF
                or 0xE000 <= code <= 0xFFFD or 0x10000 <= code <= 0x10FFFF):
            raise ValueError(f"{location}: invalid XML control/code point U+{code:04X}")


def _choice(value: Any, choices: tuple[str, ...], location: str) -> None:
    if not isinstance(value, str) or value not in choices:
        raise ValueError(f"{location}: expected {' or '.join(choices)}")


def _items(value: Any, minimum: int, maximum: int, location: str) -> None:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ValueError(f"{location}: expected a list of {minimum}–{maximum} objects")


def validate_diagram(spec: Any, location: str = "diagram") -> None:
    """Pure preflight, returning None or raising a location-qualified ValueError."""
    common = {"kind", "type", "title", "description", "caption"}
    _object(spec, common | {"direction", "nodes", "edges", "participants", "messages"},
            {"type", "title", "description"}, location)
    _choice(spec["type"], ("flow", "sequence"), f"{location}.type")
    flow = spec["type"] == "flow"
    entities_key, links_key = ("nodes", "edges") if flow else ("participants", "messages")
    _object(spec, common | {entities_key, links_key} | ({"direction"} if flow else set()),
            {"type", "title", "description", entities_key, links_key}, location)
    if "kind" in spec:
        _choice(spec["kind"], ("diagram",), f"{location}.kind")
    for key in ("title", "description", "caption"):
        if key in spec:
            _text(spec[key], f"{location}.{key}", 4096, key != "caption")
    if "direction" in spec:
        _choice(spec["direction"], ("LR", "TB"), f"{location}.direction")
    _items(spec[entities_key], 1, 16 if flow else 12, f"{location}.{entities_key}")
    _items(spec[links_key], 0 if flow else 1, 32, f"{location}.{links_key}")
    ids: set[str] = set()
    for i, entity in enumerate(spec[entities_key]):
        here = f"{location}.{entities_key}[{i}]"
        _object(entity, {"id", "label"} | ({"detail"} if flow else set()), {"id", "label"}, here)
        _text(entity["id"], f"{here}.id", 128, True)
        _text(entity["label"], f"{here}.label", 256, True)
        if "detail" in entity:
            _text(entity["detail"], f"{here}.detail", 512)
        if entity["id"] in ids:
            raise ValueError(f"{here}.id: duplicate ID {entity['id']!r}")
        ids.add(entity["id"])
    degree = dict.fromkeys(ids, 0)
    for i, link in enumerate(spec[links_key]):
        here = f"{location}.{links_key}[{i}]"
        _object(link, {"from", "to", "label", "style"} | (set() if flow else {"note"}),
                {"from", "to"} | (set() if flow else {"label"}), here)
        for key in ("from", "to"):
            _text(link[key], f"{here}.{key}", 128, True)
            if link[key] not in ids:
                raise ValueError(f"{here}.{key}: unknown endpoint {link[key]!r}")
            degree[link[key]] += 1
        if "label" in link:
            _text(link["label"], f"{here}.label", 256, not flow)
        if "note" in link:
            _text(link["note"], f"{here}.note", 512)
        if "style" in link:
            _choice(link["style"], ("solid", "dashed"), f"{here}.style")
    if flow and any(count > 16 for count in degree.values()):
        raise ValueError(f"{location}.edges: at most 16 incident edge ends per node")
    width, height, _ = _layout(spec)
    if max(width, height) > _MAX_EXTENT:
        raise ValueError(f"{location}: layout exceeds {_MAX_EXTENT} CSS pixels per axis")


def _esc(text: str) -> str:
    # Character references retain tabs/newlines in XML attributes and CR in text.
    return escape(text, quote=True).replace("\r", "&#13;").replace("\n", "&#10;").replace("\t", "&#9;")


def _wrap(text: str, columns: int = 20) -> list[str]:
    """Wrap without truncation, including unspaced names and wide Unicode glyphs."""
    lines: list[str] = []
    for paragraph in text.expandtabs(4).splitlines() or [""]:
        line = ""
        width = 0
        for char in paragraph:
            units = 0 if unicodedata.combining(char) else (
                2 if unicodedata.east_asian_width(char) in ("W", "F") else 1)
            if width + units > columns and line:
                # Prefer a word boundary; hard-wrap long technical identifiers.
                split = line.rfind(" ")
                if split > columns // 2:
                    lines.append(line[:split])
                    line = line[split + 1:]
                    width = sum(0 if unicodedata.combining(c) else (
                        2 if unicodedata.east_asian_width(c) in ("W", "F") else 1) for c in line)
                else:
                    lines.append(line)
                    line, width = "", 0
            line += char
            width += units
        lines.append(line)
    return lines


def _block(label: str, detail: str = "") -> tuple[list[str], list[str], int]:
    label_lines = _wrap(label)
    detail_lines = _wrap(detail, 24) if detail else []
    return label_lines, detail_lines, 24 + 22 * len(label_lines) + 20 * len(detail_lines)


def _text_svg(lines: list[str], x: float, y: float, *, small: bool = False) -> str:
    size, step, color = (14, 20, _MUTED) if small else (16, 22, _TEXT)
    return (
        f'<text x="{x:g}" y="{y:g}" font-size="{size}" fill="{color}">'
        + "".join(f'<tspan x="{x:g}" dy="{0 if i == 0 else step}">{_esc(line)}</tspan>'
                  for i, line in enumerate(lines))
        + "</text>"
    )


def _box_svg(entity: dict[str, Any], x: float, y: float, height: int) -> str:
    labels, details, _ = _block(entity["label"], entity.get("detail", ""))
    return (
        f'<g data-entity="{_esc(entity["id"])}"><title>{_esc(entity["label"])}</title>'
        f'<rect x="{x:g}" y="{y:g}" width="{_BOX}" height="{height}" rx="6" '
        f'fill="{_PANEL}" stroke="{_MUTED}" stroke-width="1.5"/>'
        + _text_svg(labels, x + 16, y + 28)
        + (_text_svg(details, x + 16, y + 28 + 22 * len(labels), small=True) if details else "")
        + "</g>"
    )


def _arrow(points: list[tuple[float, float]], style: str) -> str:
    """Polyline plus explicit triangle: no marker IDs or reference collisions."""
    x, y = points[-1]
    px, py = points[-2]
    distance = math.hypot(x - px, y - py)
    ux, uy = (x - px) / distance, (y - py) / distance
    bx, by = x - 10 * ux, y - 10 * uy
    triangle = [(x, y), (bx - 5 * uy, by + 5 * ux), (bx + 5 * uy, by - 5 * ux)]
    path = " ".join(f"{a:g},{b:g}" for a, b in points[:-1] + [(bx, by)])
    head = " ".join(f"{a:g},{b:g}" for a, b in triangle)
    dash = ' stroke-dasharray="7 5"' if style == "dashed" else ""
    return (f'<polyline points="{path}" fill="none" stroke="{_LINE}" stroke-width="2"{dash}/>'
            f'<polygon points="{head}" fill="{_LINE}"/>')


def _link_group(link: dict[str, Any], index: int, content: str) -> str:
    return (
        f'<g data-edge="{index}" data-from="{_esc(link["from"])}" '
        f'data-to="{_esc(link["to"])}" data-style="{link.get("style", "solid")}">'
        f'<title>{_esc(link.get("label", ""))}</title>{content}</g>'
    )


def _label_svg(lines: list[str], x: float, y: float, details: list[str] | None = None) -> str:
    details = details or []
    height = 22 * len(lines) + 20 * len(details) + 12
    return (
        f'<rect x="{x - 6:g}" y="{y - 18:g}" width="336" height="{height}" fill="{_BG}"/>'
        + _text_svg(lines, x, y)
        + (_text_svg(details, x, y + 22 * len(lines), small=True) if details else "")
    )


def _flow_layout(spec: dict[str, Any]) -> tuple[int, int, str]:
    nodes, edges = spec["nodes"], spec["edges"]
    horizontal = spec.get("direction", "LR") == "LR"
    counts = {node["id"]: 0 for node in nodes}
    for edge in edges:
        for key in ("from", "to"):
            counts[edge[key]] += 1
    box_height = max(_block(n["label"], n.get("detail", ""))[2] + 16 for n in nodes)
    if not horizontal:
        # Keep ten-pixel arrowheads apart even at the maximum supported degree.
        box_height = max(box_height, 32 + 14 * (max(counts.values()) + 1))
    edge_lines = [_wrap(f"{i + 1}. {e.get('label', '')}") for i, e in enumerate(edges)]
    lane_heights = [22 * len(lines) + 40 for lines in edge_lines]
    lane_total = sum(lane_heights)
    width = 2 * _MARGIN + (len(nodes) * (_BOX + _GAP) - _GAP if horizontal
                           else _BOX + _GAP + len(edges) * (_BOX + _GAP))
    height = 2 * _MARGIN + (lane_total + box_height if horizontal
                            else len(nodes) * (box_height + _GAP) - _GAP)
    positions = {
        node["id"]: (_MARGIN + i * (_BOX + _GAP), _MARGIN + lane_total) if horizontal
        else (_MARGIN, _MARGIN + i * (box_height + _GAP))
        for i, node in enumerate(nodes)
    }
    # Assign a distinct endpoint port to every incident end, including parallel edges.
    used = dict.fromkeys(positions, 0)

    def port(node_id: str) -> tuple[float, float]:
        used[node_id] += 1
        ratio = used[node_id] / (counts[node_id] + 1)
        x, y = positions[node_id]
        return (x + 16 + ratio * (_BOX - 32), y) if horizontal else (
            x + _BOX, y + 16 + ratio * (box_height - 32))

    paths, labels = [], []
    lane_y = _MARGIN
    for i, edge in enumerate(edges):
        start, end = port(edge["from"]), port(edge["to"])
        if horizontal:
            track = lane_y + lane_heights[i] - 12
            points = [start, (start[0], track), (end[0], track), end]
            label_x = max(_MARGIN, min(width - 352, (start[0] + end[0]) / 2 - 160))
            label_y = lane_y + 18
            lane_y += lane_heights[i]
        else:
            track = _MARGIN + _BOX + _GAP + i * (_BOX + _GAP)
            points = [start, (track, start[1]), (track, end[1]), end]
            label_x, label_y = track + 14, min(start[1], end[1]) + 24
            height = max(height, math.ceil(label_y + lane_heights[i] + _MARGIN))
        paths.append(_link_group(edge, i + 1, _arrow(points, edge.get("style", "solid"))))
        labels.append(f'<g data-edge-label="{i + 1}">'
                      + _label_svg(edge_lines[i], label_x, label_y) + "</g>")
    boxes = [_box_svg(n, *positions[n["id"]], box_height) for n in nodes]
    return width, height, "".join(paths + boxes + labels)


def _sequence_layout(spec: dict[str, Any]) -> tuple[int, int, str]:
    participants, messages = spec["participants"], spec["messages"]
    header_height = max(_block(p["label"])[2] + 16 for p in participants)
    # The extra right gutter holds labels and loops for the final participant.
    width = 2 * _MARGIN + (len(participants) + 1) * (_BOX + _GAP)
    centers = {p["id"]: _MARGIN + _BOX / 2 + i * (_BOX + _GAP)
               for i, p in enumerate(participants)}
    y = _MARGIN + header_height + 40
    rows = []
    for i, message in enumerate(messages):
        lines, notes, block_height = _block(f"{i + 1}. {message['label']}", message.get("note", ""))
        sx, tx = centers[message["from"]], centers[message["to"]]
        line_y = y + block_height
        points: list[tuple[float, float]]
        if sx == tx:
            points = [(sx, line_y), (sx + 140, line_y), (sx + 140, line_y + 28), (sx, line_y + 28)]
        else:
            points = [(sx, line_y), (tx, line_y)]
        label = _label_svg(lines, min(sx, tx) + 16, y + 18, notes)
        rows.append(_link_group(message, i + 1, label + _arrow(points, message.get("style", "solid"))))
        y = line_y + 68
    height = math.ceil(y + _MARGIN)
    lifelines = [
        f'<line data-lifeline="{_esc(p["id"])}" x1="{centers[p["id"]]:g}" '
        f'x2="{centers[p["id"]]:g}" y1="{_MARGIN + header_height}" y2="{height - _MARGIN}" '
        f'stroke="{_MUTED}" stroke-width="1.5" stroke-dasharray="4 6"/>'
        for p in participants
    ]
    boxes = [_box_svg(p, centers[p["id"]] - _BOX / 2, _MARGIN, header_height) for p in participants]
    return width, height, "".join(lifelines + boxes + rows)


def _layout(spec: dict[str, Any]) -> tuple[int, int, str]:
    return _flow_layout(spec) if spec["type"] == "flow" else _sequence_layout(spec)


def diagram_svg(spec: dict[str, Any]) -> str:
    """Return validated standalone SVG; identical inputs produce identical bytes."""
    validate_diagram(spec)
    width, height, content = _layout(spec)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-label="{_esc(spec["title"])}" aria-description="{_esc(spec["description"])}" '
        f'width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'style="display:block;width:{width}px;min-width:{width}px;max-width:none;'
        f'height:{height}px;background:{_BG};font-family:system-ui,sans-serif">'
        f'<title>{_esc(spec["title"])}</title><desc>{_esc(spec["description"])}</desc>'
        f'<rect width="{width}" height="{height}" fill="{_BG}"/>'
        f"{content}</svg>"
    )


def render_diagram(spec: dict[str, Any]) -> str:
    """Safe figure HTML with contained keyboard scrolling and complete visible text."""
    svg = diagram_svg(spec)
    flow = spec["type"] == "flow"
    entities = spec["nodes" if flow else "participants"]
    links = spec["edges" if flow else "messages"]
    by_id = {entity["id"]: entity["label"] for entity in entities}
    entity_rows = []
    for entity in entities:
        detail = f' — {_esc(entity["detail"])}' if "detail" in entity else ""
        entity_rows.append(f'<li><strong>{_esc(entity["label"])}</strong> '
                           f'(<span>{_esc(entity["id"])}</span>){detail}</li>')
    link_rows = []
    for link in links:
        source = f'{_esc(by_id[link["from"]])} ({_esc(link["from"])})'
        target = f'{_esc(by_id[link["to"]])} ({_esc(link["to"])})'
        label = f': <span>{_esc(link["label"])}</span>' if "label" in link else ""
        note = f' — <span>{_esc(link["note"])}</span>' if "note" in link else ""
        style = link.get("style", "solid")
        link_rows.append(f"<li>{source} → {target}{label}{note} [{style} line]</li>")
    caption = f'<p>{_esc(spec["caption"])}</p>' if "caption" in spec else ""
    return (
        '<figure class="ste-diagram" style="margin:1.5rem 0;min-width:0;max-width:100%;'
        'overflow-wrap:anywhere;white-space:pre-wrap">'
        f'<figcaption><strong>{_esc(spec["title"])}</strong>'
        f'<p>{_esc(spec["description"])}</p>{caption}</figcaption>'
        f'<div role="region" tabindex="0" aria-label="{_esc(spec["title"])} — scrollable diagram" '
        'style="max-width:100%;min-width:0;max-height:70vh;overflow:auto;'
        f'border:1px solid {_MUTED};border-radius:4px">'
        f'{svg}</div><div class="ste-diagram-equivalent">'
        '<p>Text equivalent. Numbered relationships match the diagram. '
        'Solid and dashed lines are presentation styles, not evidence classifications.</p>'
        f'<p>{"Nodes" if flow else "Participants"} (supplied order)</p><ul>{"".join(entity_rows)}</ul>'
        f'<p>{"Directed relationships" if flow else "Messages (temporal order)"}</p>'
        + (f'<ol>{"".join(link_rows)}</ol>' if links else "<p>No directed relationships supplied.</p>")
        + "</div></figure>"
    )

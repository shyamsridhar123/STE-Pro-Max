"""Standalone, offline quantitative figures. SPDX-License-Identifier: Apache-2.0.

Limits: 1–40 categories, 1–6 series; category labels 120 characters, other
labels/titles 160, descriptions/captions 1200, uncertainty labels 240.
Numbers are finite built-in int/float values within binary64 magnitude; domain
spans must also fit that magnitude. Decimal coordinates avoid overflow and
underflow for tiny values. Geometry is rounded to 0.001 SVG units, never source
data. Tables preserve Python's lossless numeric string representations.

Interval arrays may contain paired nulls (unavailable bounds), never one null
bound or bounds for a missing value. They are source-provided uncertainty, not
an inferred confidence interval. Categories are discrete, equally spaced even
for line charts; a category that happens to name a date is not a time scale.
"""
from __future__ import annotations

from decimal import Context, Decimal, localcontext
from html import escape
import math
import sys
import unicodedata
from typing import Any


CHART_SCHEMA = {
    "description": (
        "Faithful offline bar or line chart with an accessible SVG and visible "
        "exact-value table. Limits: 40 categories, 6 series. Null means missing, "
        "not zero. Categories are equally spaced, not a continuous time axis."
    ),
    "fields": {
        "type": "Required: bar or line.",
        "title": "Required plain text, 1–160 characters.",
        "description": "Required plain-text explanation, 1–1200 characters.",
        "categories": "Required list of 1–40 strings, each 1–120 characters.",
        "series": (
            "Required list of 1–6 {label, values, lower?, upper?} objects. "
            "Unique labels, 1–160 characters. Each array matches categories. "
            "Values are finite int/float or null; bounds must be paired and "
            "enclose the value. A missing value must have missing bounds. "
            "Finite numbers and domain spans must fit binary64 magnitude."
        ),
        "y_label": "Required axis label including units, 1–160 characters.",
        "x_label": "Optional category-axis label, 1–160 characters.",
        "caption": "Optional source/context caption, 1–1200 characters.",
        "uncertainty_label": (
            "Required when any interval arrays are supplied; 1–240 characters. "
            "Explain the source-provided bounds; no statistical CI is inferred."
        ),
        "domain": (
            "Optional [min, max], finite numbers with min < max; must contain "
            "every value and bound. Bar domains must include zero."
        ),
    },
    "example": {
        "kind": "chart", "type": "bar", "title": "Illustrative output",
        "description": "An illustrative comparison, not measured results.",
        "categories": ["Baseline", "Revision"],
        "series": [{"label": "Output", "values": [12, 18]}],
        "y_label": "Output (items)", "x_label": "Configuration",
        "caption": "Illustrative data.",
    },
}

_MAX_NUMBER = Decimal.from_float(sys.float_info.max)
_COLORS = ("#edba94", "#d9e0e4", "#97c9c0", "#d1b5e5", "#e5d08e", "#9abfe8")
_DASHES = ("none", "9 4", "2 4", "9 3 2 3", "14 4", "4 3")


def _decimal(value: int | float) -> Decimal:
    return Decimal(str(value))


def _record(value: Any, allowed: set[str], location: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{location}: expected a mapping")
    for key in value:
        if not isinstance(key, str) or key not in allowed:
            raise ValueError(f"{location}: unsupported field {key!r}")


def _text(value: Any, limit: int, location: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{location}: expected nonempty text of at most {limit} characters")
    if any(not (c in "\t\n\r" or 0x20 <= ord(c) <= 0xD7FF
                or 0xE000 <= ord(c) <= 0xFFFD or 0x10000 <= ord(c) <= 0x10FFFF)
           for c in value):
        raise ValueError(f"{location}: text contains an invalid XML character")


def _number(value: Any, location: str) -> None:
    if type(value) not in (int, float):
        raise ValueError(f"{location}: expected a finite number (not a boolean)")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite or _decimal(value).copy_abs() > _MAX_NUMBER:
        raise ValueError(f"{location}: number exceeds finite representable magnitude")


def _domain(spec: dict) -> tuple[Decimal, Decimal]:
    if "domain" in spec:
        return _decimal(spec["domain"][0]), _decimal(spec["domain"][1])
    values = [_decimal(v) for series in spec["series"]
              for field in ("values", "lower", "upper")
              for v in series.get(field, []) if v is not None]
    lo, hi = (min(values), max(values)) if values else (Decimal(0), Decimal(1))
    if spec["type"] == "bar" or lo == hi:
        lo, hi = min(lo, Decimal(0)), max(hi, Decimal(0))
    if lo == hi:
        hi = Decimal(1)
    return lo, hi


def validate_chart(spec: Any, location: str = "chart") -> None:
    """Pure preflight; return None or raise a location-bearing ValueError."""
    _record(spec, {"kind", *CHART_SCHEMA["fields"]}, location)
    if "kind" in spec and spec["kind"] != "chart":
        raise ValueError(f"{location}.kind: expected chart")
    if not isinstance(spec.get("type"), str) or spec["type"] not in ("bar", "line"):
        raise ValueError(f"{location}.type: expected bar or line")
    for field, limit in (("title", 160), ("description", 1200), ("y_label", 160)):
        _text(spec.get(field), limit, f"{location}.{field}")
    for field, limit in (("x_label", 160), ("caption", 1200), ("uncertainty_label", 240)):
        if field in spec:
            _text(spec[field], limit, f"{location}.{field}")
    categories = spec.get("categories")
    if not isinstance(categories, list) or not 1 <= len(categories) <= 40:
        raise ValueError(f"{location}.categories: expected 1–40 categories")
    for i, category in enumerate(categories):
        _text(category, 120, f"{location}.categories[{i}]")
    series = spec.get("series")
    if not isinstance(series, list) or not 1 <= len(series) <= 6:
        raise ValueError(f"{location}.series: expected 1–6 series")
    labels = set()
    points = []
    for i, item in enumerate(series):
        where = f"{location}.series[{i}]"
        _record(item, {"label", "values", "lower", "upper"}, where)
        _text(item.get("label"), 160, f"{where}.label")
        if item["label"] in labels:
            raise ValueError(f"{where}.label: duplicate series label")
        labels.add(item["label"])
        intervals = "lower" in item or "upper" in item
        if intervals and not ("lower" in item and "upper" in item):
            raise ValueError(f"{where}: both lower and upper arrays are required")
        if intervals and "uncertainty_label" not in spec:
            raise ValueError(f"{location}.uncertainty_label: required for source-provided intervals")
        for field in (("values", "lower", "upper") if intervals else ("values",)):
            values = item.get(field)
            if not isinstance(values, list) or len(values) != len(categories):
                raise ValueError(f"{where}.{field}: array must match categories")
            for j, value in enumerate(values):
                if value is not None:
                    _number(value, f"{where}.{field}[{j}]")
                    points.append(_decimal(value))
        if intervals:
            for j, (value, lower, upper) in enumerate(zip(item["values"], item["lower"], item["upper"])):
                if (lower is None) != (upper is None):
                    raise ValueError(f"{where}[{j}]: interval bounds must both be present or both missing")
                if lower is not None and (
                    value is None or not _decimal(lower) <= _decimal(value) <= _decimal(upper)
                ):
                    raise ValueError(f"{where}[{j}]: interval must enclose a present value")
    if "domain" in spec:
        bounds = spec["domain"]
        if not isinstance(bounds, list) or len(bounds) != 2:
            raise ValueError(f"{location}.domain: expected [min, max]")
        for i, bound in enumerate(bounds):
            _number(bound, f"{location}.domain[{i}]")
        if bounds[0] >= bounds[1]:
            raise ValueError(f"{location}.domain: minimum must be less than maximum")
    lo, hi = _domain(spec)
    with localcontext(Context(prec=800)):
        if hi - lo > _MAX_NUMBER or hi <= lo:
            raise ValueError(f"{location}.domain: unrepresentable range")
    if spec["type"] == "bar" and not lo <= 0 <= hi:
        raise ValueError(f"{location}.domain: bar axis must include zero")
    if any(value < lo or value > hi for value in points):
        raise ValueError(f"{location}.domain: clips a value or interval")


def _wrap(text: str, width: int) -> list[str]:
    """Wrap on words, breaking long words; budget wide Unicode as two columns."""
    lines, line, used = [], "", 0
    for word in text.split():
        word_width = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in word)
        if line and used + 1 + word_width <= width:
            line += " " + word
            used += word_width + 1
            continue
        if line:
            lines.append(line)
            line, used = "", 0
        for char in word:
            size = 2 if unicodedata.east_asian_width(char) in "WF" else 1
            if used + size > width:
                lines.append(line)
                line, used = "", 0
            line += char
            used += size
    if line:
        lines.append(line)
    return lines


def _coord(value: Any) -> str:
    return f"{value:.3f}"


def _svg_text(x: Any, y: Any, text: str, *, anchor: str = "start",
              size: int = 13, fill: str = "#efece6") -> str:
    return (f'<text x="{_coord(x)}" y="{_coord(y)}" text-anchor="{anchor}" '
            f'font-size="{size}" fill="{fill}">{escape(text)}</text>')


def _marker(x: Any, y: Any, index: int, color: str) -> str:
    x, y = float(x), float(y)
    attrs = f'fill="#171717" stroke="{color}" stroke-width="2"'
    if index == 0:
        return f'<circle cx="{_coord(x)}" cy="{_coord(y)}" r="4" {attrs}/>'
    if index == 1:
        return f'<rect x="{_coord(x-4)}" y="{_coord(y-4)}" width="8" height="8" {attrs}/>'
    if index in (2, 3):
        points = ([(x, y-5), (x+5, y), (x, y+5), (x-5, y)] if index == 2
                  else [(x, y-5), (x+5, y+4), (x-5, y+4)])
        return f'<polygon points="{" ".join(f"{a:.3f},{b:.3f}" for a, b in points)}" {attrs}/>'
    d = (f"M{x-4:.3f},{y-4:.3f} L{x+4:.3f},{y+4:.3f} M{x-4:.3f},{y+4:.3f} L{x+4:.3f},{y-4:.3f}"
         if index == 4 else f"M{x-5:.3f},{y:.3f} L{x+5:.3f},{y:.3f} M{x:.3f},{y-5:.3f} L{x:.3f},{y+5:.3f}")
    return f'<path d="{d}" {attrs}/>'


def _tick(value: Decimal) -> str:
    if value == 0:
        return "0"
    # Axis ticks are guide labels, not the authoritative data equivalent.
    return format(value, ".6g")


def _chart_svg(spec: dict) -> str:
    """Internal rendering under a fixed decimal context after validation."""
    lo, hi = _domain(spec)
    span = hi - lo
    offset = lo if lo != 0 and abs(lo) / span >= 10000 else Decimal(0)
    ticks = [lo + span * Decimal(i) / 4 for i in range(5)]
    labels = [_tick(tick - offset) for tick in ticks]
    left = max(105, max(len(label) for label in labels) * 8 + 25)
    count, series_count = len(spec["categories"]), len(spec["series"])
    slot = max(150, 62 * series_count + 20) if spec["type"] == "bar" else 150
    plot_width = max(540, slot * count)
    slot = plot_width / count
    width = left + plot_width + 30
    parts = []
    cursor = 30
    for line in _wrap(spec["title"], min(70, int((width-40)//18))):
        parts.append(_svg_text(20, cursor, line, size=18))
        cursor += 24
    for index, series in enumerate(spec["series"]):
        color = _COLORS[index]
        parts.append(f'<path d="M20,{cursor-4} H55" stroke="{color}" stroke-width="2" '
                     f'stroke-dasharray="{_DASHES[index]}"/>')
        parts.append(_marker(37, cursor-4, index, color))
        for line in _wrap(f'S{index+1}: {series["label"]}', min(65, int((width-88)//13))):
            parts.append(_svg_text(68, cursor, line))
            cursor += 18
        cursor += 7
    for line in _wrap(spec["y_label"], min(70, int((width-40)//13))):
        parts.append(_svg_text(20, cursor, line))
        cursor += 18
    if offset:
        for line in _wrap(f"Y tick labels are offsets from {lo}; add this base to each tick.",
                          min(70, int((width-40)//12))):
            parts.append(_svg_text(20, cursor, line, size=12))
            cursor += 17
    top = cursor + 20
    bottom = top + 300

    def y(value: int | float | Decimal) -> Decimal:
        value = value if isinstance(value, Decimal) else _decimal(value)
        return Decimal(bottom) - (value - lo) / span * 300

    def x(category: int, series: int = 0) -> float:
        center = left + slot * (category + .5)
        if spec["type"] == "bar":
            center += (series - (series_count - 1) / 2) * 62
        return center

    for tick, label in zip(ticks, labels):
        yy = y(tick)
        parts.append(f'<path d="M{left},{_coord(yy)} H{left+plot_width}" stroke="#51504d"/>')
        parts.append(_svg_text(left-12, yy+4, label, anchor="end", fill="#d2cdc5"))
    if lo <= 0 <= hi:
        parts.append(f'<path class="chart-zero" d="M{left},{_coord(y(0))} H{left+plot_width}" '
                     'stroke="#efece6" stroke-width="2"/>')
    parts.append(f'<path d="M{left},{top} V{bottom}" stroke="#d2cdc5"/>')
    for index, series in enumerate(spec["series"]):
        color, dash = _COLORS[index], _DASHES[index]
        if spec["type"] == "line":
            path, connected = [], False
            for j, value in enumerate(series["values"]):
                if value is None:
                    connected = False
                    continue
                path.append(f'{"L" if connected else "M"}{_coord(x(j))},{_coord(y(value))}')
                connected = True
            if path:
                parts.append(f'<path class="chart-line" data-series="{index+1}" d="{" ".join(path)}" '
                             f'fill="none" stroke="{color}" stroke-width="2" stroke-dasharray="{dash}"/>')
        for j, value in enumerate(series["values"]):
            xx = x(j, index)
            if value is None:
                # A separate missing-data row never implies a zero observation.
                yy = bottom + 23 + (index * 18 if spec["type"] == "line" else 0)
                parts.append(_svg_text(xx, yy, f"S{index+1} missing", anchor="middle", size=12))
                continue
            yy = y(value)
            label = f'{series["label"]}; {spec["categories"][j]}: {value}'
            parts.append(f'<g class="chart-point" data-series="{index+1}" data-category="{j}">'
                         f'<title>{escape(label)}</title>')
            if spec["type"] == "bar":
                baseline = y(0)
                parts.append(f'<rect class="chart-bar" x="{_coord(xx-19)}" y="{_coord(min(yy, baseline))}" '
                             f'width="38" height="{_coord(abs(yy-baseline))}" fill="{color}" '
                             f'fill-opacity=".25" stroke="{color}" stroke-width="2" '
                             f'stroke-dasharray="{dash}"/>')
            if "lower" in series and series["lower"][j] is not None:
                lower, upper = series["lower"][j], series["upper"][j]
                a, b = y(lower), y(upper)
                parts.append(f'<path class="chart-interval" d="M{xx:.3f},{a:.3f} V{b:.3f} '
                             f'M{xx-7:.3f},{a:.3f} H{xx+7:.3f} M{xx-7:.3f},{b:.3f} H{xx+7:.3f}" '
                             f'stroke="{color}" stroke-width="2" fill="none">'
                             f'<title>{escape(f"Source-provided bounds: {lower} to {upper}")}</title></path>')
            parts.append(_marker(xx, yy, index, color))
            parts.append("</g>")
            if spec["type"] == "bar":
                parts.append(_svg_text(xx, bottom+23, f"S{index+1}", anchor="middle", size=12))
    label_top = bottom + 32 + (series_count * 18 if spec["type"] == "line" else 18)
    wrapped = [_wrap(category, min(40, int(slot // 14))) for category in spec["categories"]]
    for j, lines in enumerate(wrapped):
        for row, line in enumerate(lines):
            parts.append(_svg_text(left+slot*(j+.5), label_top+row*18, line, anchor="middle"))
    cursor = label_top + max(map(len, wrapped)) * 18 + 12
    if "x_label" in spec:
        for line in _wrap(spec["x_label"], min(70, int((width-left-30)//13))):
            parts.append(_svg_text(left, cursor, line))
            cursor += 18
    notes = [
        f"Y-axis domain: {lo} to {hi}. Tick labels are rounded guides.",
        "Categories are equally spaced. Missing means unavailable, never zero.",
    ]
    if not any(value is not None for series in spec["series"] for value in series["values"]):
        notes.append("No observed values are available; the axis is only a display domain.")
    if "uncertainty_label" in spec:
        notes.append(f'Source-provided uncertainty: {spec["uncertainty_label"]}. '
                     'No confidence interval is inferred.')
        if not any("lower" in series for series in spec["series"]):
            notes.append("No interval arrays were supplied.")
    if "caption" in spec:
        notes.append(spec["caption"])
    for note in notes:
        for line in _wrap(note, min(75, int((width-40)//12))):
            parts.append(_svg_text(20, cursor, line, size=12, fill="#d2cdc5"))
            cursor += 17
        cursor += 5
    description = (spec["description"] + " " + " ".join(notes)
                   + " Series use distinct markers, dash patterns, and S-number labels.")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{cursor+12}" '
            f'viewBox="0 0 {width} {cursor+12}" role="img" aria-label="{escape(spec["title"], quote=True)}" '
            f'aria-description="{escape(description, quote=True)}" '
            'style="display:block;max-width:none" font-family="system-ui, sans-serif">'
            f'<title>{escape(spec["title"])}</title><desc>{escape(description)}</desc>'
            f'<rect width="{width}" height="{cursor+12}" fill="#171717"/>'
            + "".join(parts) + "</svg>")


def chart_svg(spec: dict) -> str:
    """Return deterministic, standalone SVG; no IDs, I/O, scripts or assets."""
    validate_chart(spec)
    with localcontext(Context(prec=800)):
        return _chart_svg(spec)


_CSS = """
.ste-chart{margin:1.5rem 0;max-width:100%;min-width:0;color:#efece6;background:#171717;
font-family:system-ui,sans-serif;overflow-wrap:anywhere;border:1px solid #51504d}
.ste-chart>figcaption,.ste-chart>.chart-note{padding:.8rem 1rem;margin:0}
.ste-chart>figcaption>strong{display:block;font-size:1.2rem;margin-bottom:.5rem}
.ste-chart>.chart-scroll{overflow:auto;max-width:100%;min-width:0;overscroll-behavior-inline:contain}
.ste-chart>.chart-scroll:focus-visible{outline:3px solid #edba94;outline-offset:-3px}
.ste-chart .chart-data{border-collapse:collapse;width:100%;min-width:540px;table-layout:fixed}
.ste-chart .chart-data caption{text-align:left;padding:1rem;color:#efece6}
.ste-chart .chart-data th,.ste-chart .chart-data td{padding:.6rem;text-align:left;vertical-align:top;
border:1px solid #51504d;white-space:normal;overflow-wrap:anywhere;color:#efece6;background:#171717}
.ste-chart .chart-data td{font-family:ui-monospace,monospace}
"""


def render_chart(spec: dict) -> str:
    """Safe figure HTML with scoped styles, inline SVG and exact visible data."""
    svg = chart_svg(spec)
    has_intervals = any("lower" in series for series in spec["series"])
    parts = [f'<style>{_CSS}</style><figure class="ste-chart">',
             f'<figcaption><strong>{escape(spec["title"])}</strong>{escape(spec["description"])}']
    if "caption" in spec:
        parts.append(f'<p>{escape(spec["caption"])}</p>')
    parts.append("</figcaption>")
    parts.append('<p class="chart-note">Scroll the chart or data region horizontally when needed. '
                 'Missing means unavailable, never zero. Values below are not rounded.</p>')
    if "uncertainty_label" in spec:
        parts.append(f'<p class="chart-note">Source-provided uncertainty: '
                     f'{escape(spec["uncertainty_label"])}. No confidence interval is inferred. '
                     'Missing bounds mean unavailable; not supplied means this series has no interval arrays.</p>')
        if not has_intervals:
            parts.append('<p class="chart-note">No interval arrays were supplied.</p>')
    name = escape(spec["title"], quote=True)
    parts.append(f'<div class="chart-scroll" tabindex="0" role="region" aria-label="{name} — chart">{svg}</div>')
    parts.append(f'<div class="chart-scroll" tabindex="0" role="region" aria-label="{name} — exact data">'
                 '<table class="chart-data"><caption>Exact source data — '
                 f'{escape(spec["y_label"])}'
                 '</caption><thead><tr><th scope="col">'
                 f'{escape(spec.get("x_label", "Category"))}</th><th scope="col">Series</th>'
                 '<th scope="col">Value</th>')
    if has_intervals:
        parts.append('<th scope="col">Lower bound</th><th scope="col">Upper bound</th>')
    parts.append("</tr></thead><tbody>")
    for j, category in enumerate(spec["categories"]):
        for index, series in enumerate(spec["series"]):
            parts.append(f'<tr><th scope="row">{escape(category)}</th>'
                         f'<td>{escape(f"S{index+1}: " + series["label"])}</td>')
            fields = ("values", "lower", "upper") if has_intervals else ("values",)
            for field in fields:
                value = ("Not supplied" if field not in series else
                         "Missing" if series[field][j] is None else str(series[field][j]))
                parts.append(f"<td>{escape(value)}</td>")
            parts.append("</tr>")
    parts.append("</tbody></table></div></figure>")
    return "".join(parts)

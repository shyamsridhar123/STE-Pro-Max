"""Native offline renderer, modified for STE-Pro-Max from ATV-PaperBoard.

Copyright (c) 2026 All-The-Vibes / atv-paperboard contributors.
SPDX-License-Identifier: Apache-2.0
Source: core/render.py at 4b068bcab8e4dc105f0ef975ee224564f5d63383.
Modified: offline ATV only, local DESIGN validation, escaped metadata/sections,
safer Markdown, exclusive artifact triples. No Node, harness, server or browser.
Only explicit body_html is caller-trusted; it is not sanitized here.
"""
from __future__ import annotations

from contextlib import ExitStack
import datetime
import html as _html_lib
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit

import yaml
from jinja2 import Environment, FileSystemLoader

from .charts import render_chart, validate_chart
from .diagrams import render_diagram, validate_diagram
from .section_schema import SECTION_SCHEMA
from .stories import render_story, validate_story

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_DEFAULT_DESIGN = Path(__file__).parent / "designs" / "paperboard.DESIGN.md"
_GENERATOR = "ste-promax/native-atv"
_LINT_ENGINE = "ste-promax.local-design-v1"
_TRIPLE_SUFFIXES = (".html", ".DESIGN.md", ".meta.yaml")


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
            if not isinstance(kind, str) or kind not in SECTION_SCHEMA or kind not in _SECTION_EMITTERS:
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


def render_artifact(
    input_data: dict[str, Any],
    design_path: Path | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Render a new HTML/DESIGN/meta triple; propagate validation and I/O errors.

    body_html is explicitly trusted HTML. All other text inputs are escaped.
    Local lint validates supported token syntax, not design quality or STE.
    """
    validate_input(input_data)
    design_path = Path(design_path) if design_path is not None else _DEFAULT_DESIGN
    design_content = design_path.read_bytes().decode("utf-8")
    tokens = _design_tokens(design_content)
    title = str(input_data.get("title", "Untitled Artifact"))
    output_dir = Path(output_dir) if output_dir is not None else Path.cwd() / "artifacts" / "ste-promax"
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = _unique_slug(_slugify(title), output_dir)
    paths = [output_dir / f"{slug}{suffix}" for suffix in _TRIPLE_SUFFIXES]
    env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)), autoescape=True)
    html_content = env.get_template("atv-tier.html.j2").render(
        title=title, tokens=tokens, body_html=_default_body_html(input_data),
        design_md_path=paths[1].name,
        brand=str(input_data.get("brand", "STE-Pro-Max")),
        breadcrumb=str(input_data.get("breadcrumb", "")),
        status_tag=str(input_data.get("status_tag", "rendered")),
    )
    meta = {
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "generator": _GENERATOR,
        "title": title,
        "design": paths[1].name,
        "tier": "atv",
        "slug": slug,
        "lint_passed": True,
        "lint_engine": _LINT_ENGINE,
        "lint_scope": "Supported local DESIGN token syntax only; no Node lint or STE/semantic compliance.",
        "lint_findings": [],
    }
    contents = (html_content, design_content, yaml.safe_dump(meta, sort_keys=True))
    created: list[Path] = []
    try:
        with ExitStack() as stack:
            streams = []
            for path in paths:
                streams.append(stack.enter_context(path.open("x", encoding="utf-8", newline="")))
                created.append(path)
            for stream, content in zip(streams, contents):
                stream.write(content)
    except Exception:
        # Only paths this call exclusively created; never delete a collision.
        for path in created:
            path.unlink()
        raise
    return dict(zip(("html_path", "design_path", "meta_path"), paths), slug=slug)


def _validate_color(value: Any, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})", value):
        raise ValueError(f"{field}: expected a hexadecimal CSS color")
    return value


def _design_tokens(text: str) -> dict[str, str]:
    """Validate the documented local subset and emit safe CSS variables.

    Supports scalar semantic colors; body/heading/mono typography; spacing and
    rounded scales. Rejects unsupported fields rather than silently ignoring them.
    All values are constrained before they enter a CSS raw-text context.
    """
    match = re.match(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", text, re.DOTALL)
    if not match:
        raise ValueError("DESIGN requires YAML frontmatter bounded by --- lines")
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid DESIGN YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("DESIGN frontmatter must be a mapping")

    def fields(block: Any, allowed: set[str], where: str) -> dict:
        if not isinstance(block, dict):
            raise ValueError(f"{where} must be a mapping")
        unknown = set(block) - allowed
        if unknown:
            raise ValueError(f"Unsupported {where} fields: {', '.join(map(str, unknown))}")
        return block

    fields(data, {"version", "name", "description", "colors", "typography", "rounded", "spacing"}, "DESIGN")
    for name in ("version", "name", "description"):
        if name in data and not isinstance(data[name], str):
            raise ValueError(f"{name} must be text")
    colors = fields(data.get("colors"), {"primary", "secondary", "accent", "background", "surface",
                                       "border", "foreground", "muted", "danger", "success"}, "colors")
    if not colors:
        raise ValueError("DESIGN colors must not be empty")
    tokens = {f"--color-{key}": _validate_color(value, f"colors.{key}") for key, value in colors.items()}

    def length(value: Any, where: str, signed: bool = False) -> str:
        pattern = r"(?:0|(?:\d+(?:\.\d+)?|\.\d+)(?:px|rem|em|%))"
        if not isinstance(value, str) or not re.fullmatch(("-?" if signed else "") + pattern, value):
            raise ValueError(f"{where}: expected a CSS length (px, rem, em or %)")
        return value

    typography = fields(data.get("typography", {}), {"body", "heading", "mono"}, "typography")
    for role, block in typography.items():
        fields(block, {"fontFamily", "fontSize", "fontWeight", "lineHeight", "letterSpacing"}, f"typography.{role}")
        for key, value in block.items():
            where = f"typography.{role}.{key}"
            if key == "fontFamily":
                if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9 ,\"'_-]+", value):
                    raise ValueError(f"{where}: expected a local font-family list")
                value = ", ".join(part.strip().strip("\"'") for part in value.split(","))
                if any(not part.strip() for part in value.split(",")):
                    raise ValueError(f"{where}: empty font family")
            elif key in ("fontSize", "letterSpacing"):
                value = length(value, where, signed=key == "letterSpacing")
            elif isinstance(value, bool) or not isinstance(value, (int, float)) or not (
                1 <= value <= 1000 if key == "fontWeight" else 0 < value <= 10
            ):
                raise ValueError(f"{where}: invalid numeric value")
            css_key = re.sub(r"([A-Z])", lambda m: "-" + m.group(1).lower(), key)
            tokens[f"--{css_key}-{role}"] = str(value)
    for group in ("spacing", "rounded"):
        for key, value in fields(data.get(group, {}), {"xs", "sm", "md", "lg", "xl"}, group).items():
            tokens[f"--{group}-{key}"] = length(value, f"{group}.{key}")
    return tokens


def _safe_url(value: str, image: bool = False) -> str | None:
    """Allow ordinary links; images must be relative local files (offline default)."""
    value = _html_lib.unescape(value)
    if not value or re.search(r"[\x00-\x20\x7f\\]", value) or value.startswith("//"):
        return None
    try:
        scheme = urlsplit(value).scheme.lower()
    except ValueError:
        return None
    return value if scheme in (("",) if image else ("", "http", "https", "mailto")) else None


def _default_body_html(input_data: dict[str, Any]) -> str:
    """Convert input_data to an HTML body string.

    Explicit story, diagram, and chart documents use their native validated
    renderer. Otherwise preserve the ordinary input-mode priority:
      1. sections   — rich atv-tier section graph, including diagrams and charts
      2. body_html  — returned as-is.
      3. body_md    — converted via tiny built-in markdown converter.
      4. rows       — rendered as an HTML <table>.
      5. fallback   — <pre><code> with JSON dump.

    A header section (h1 title + h2 subtitle) is always prepended UNLESS
    `sections` is supplied (those sections own their own headers via the hero kind).
    """
    validate_input(input_data)
    kind = input_data.get("kind")
    if kind == "story":
        return render_story(input_data)
    if kind in ("diagram", "chart"):
        visual = render_diagram(input_data) if kind == "diagram" else render_chart(input_data)
        return f'<h1>{_html_lib.escape(input_data["title"])}</h1>\n{visual}'
    parts: list[str] = []

    # Rich section graph (atv tier)
    sections = input_data.get("sections")
    if sections:
        for section in sections:
            parts.append(_SECTION_EMITTERS[section["kind"]](section))
        return "\n".join(parts)

    title = input_data.get("title")
    subtitle = input_data.get("subtitle")
    has_body_md = "body_md" in input_data
    # When body_md is supplied, the markdown body carries its own H1; skip the
    # standalone title injection so we don't double-render the heading.
    if title and not has_body_md:
        parts.append(f"<h1>{_html_lib.escape(str(title))}</h1>")
    if subtitle and not has_body_md:
        parts.append(f"<h2>{_html_lib.escape(str(subtitle))}</h2>")

    if "body_html" in input_data:
        parts.append(str(input_data["body_html"]))
        return "\n".join(parts)

    if "body_md" in input_data:
        parts.append(_md_to_html(str(input_data["body_md"])))
        return "\n".join(parts)

    rows = input_data.get("rows")
    if rows and isinstance(rows, list) and len(rows) > 0 and isinstance(rows[0], dict):
        parts.append(_table_scroll(_rows_to_table(rows)))
        return "\n".join(parts)

    # Fallback: JSON dump
    parts.append(f"<pre><code>{_html_lib.escape(json.dumps(input_data, indent=2))}</code></pre>")
    return "\n".join(parts)


# ── Section emitters for the atv tier ─────��──────────────────────────────────


def _e(s: Any) -> str:
    """Shorthand for HTML-escape with str-coercion."""
    return _html_lib.escape(str(s)) if s is not None else ""


def _classes(*xs: str) -> str:
    return " ".join(x for x in xs if x)


def _emit_hero(s: dict[str, Any]) -> str:
    """`hero` section: eyebrow + h1 + sub + meta strip."""
    eyebrow = s.get("eyebrow", "")
    title = s.get("title", "")
    title_into = s.get("title_into", "")  # optional grayed-out continuation
    sub = s.get("sub", "")
    meta = s.get("meta", [])  # list of {label, value}

    title_html = _e(title)
    if title_into:
        title_html = f'{title_html} <span class="into">{_e(title_into)}</span>'

    meta_html = ""
    if meta:
        items = "".join(
            f'<div class="item">{_e(m.get("label", ""))} <span class="v">{_e(m.get("value", ""))}</span></div>'
            for m in meta
        )
        meta_html = f'<div class="hero-meta">{items}</div>'

    eyebrow_html = (
        f'<div class="eyebrow"><span class="bar"></span>{_e(eyebrow)}</div>'
        if eyebrow else ""
    )
    sub_html = f'<p class="sub">{_e(sub)}</p>' if sub else ""

    return (
        f'<section class="hero">'
        f'{eyebrow_html}'
        f'<h1>{title_html}</h1>'
        f'{sub_html}'
        f'{meta_html}'
        f'</section>'
    )


def _emit_section(s: dict[str, Any]) -> str:
    """`sec` wrapper: numbered section head with eyebrow + h2 + lede + inner content."""
    num = s.get("num", "")
    eyebrow = s.get("eyebrow", "")
    title = s.get("title", "")
    aside = s.get("aside", "")
    lede = s.get("lede", "")
    zebra = s.get("zebra", False)
    tight = s.get("tight", False)
    inner_sections = s.get("body", [])  # list of nested sub-kinds

    sec_classes = _classes("sec", "zebra" if zebra else "", "tight" if tight else "")

    head_parts = []
    if num:     head_parts.append(f'<span class="num mono">{_e(num)}</span>')
    if eyebrow: head_parts.append(f'<span class="eyebrow">{_e(eyebrow)}</span>')
    if title:   head_parts.append(f'<h2>{_e(title)}</h2>')
    if aside:   head_parts.append(f'<span class="aside">{_e(aside)}</span>')

    head_html = f'<div class="sec-head">{"".join(head_parts)}</div>' if head_parts else ""
    lede_html = f'<p class="sec-lede">{_e(lede)}</p>' if lede else ""

    inner_html = ""
    for child in inner_sections:
        inner_html += _SECTION_EMITTERS[child["kind"]](child)

    return f'<section class="{sec_classes}">{head_html}{lede_html}{inner_html}</section>'


def _emit_stack_list(s: dict[str, Any]) -> str:
    """`stack-list`: three-column list (name+tag / why / fix). Rows: [{name, tag, tag_kind, why, fix}]."""
    rows = s.get("rows", [])
    row_html = []
    tag_class_map = {"shadcn": "stack-tag-shadcn", "tailwind": "stack-tag-tailwind", "typescript": "stack-tag-typescript"}
    for r in rows:
        name = r.get("name", "")
        tag = r.get("tag", "")
        tag_kind = r.get("tag_kind", "")
        why = r.get("why", "")
        fix = r.get("fix", "")
        tag_html = ""
        if tag:
            extra = tag_class_map.get(tag_kind, "")
            tag_html = f'<span class="stack-tag {extra}">{_e(tag)}</span>'
        row_html.append(
            f'<div class="stack-row">'
            f'<div class="stack-name"><span class="mono">{_e(name)}</span>{tag_html}</div>'
            f'<div class="stack-why">{_e(why)}</div>'  # section text is escaped
            f'<div class="stack-fix muted">{_e(fix)}</div>'
            f'</div>'
        )
    return f'<div class="stack-list">{"".join(row_html)}</div>'


def _emit_dep_list(s: dict[str, Any]) -> str:
    """`dep-list`: four-column list (name+tag / role / why / version)."""
    rows = s.get("rows", [])
    row_html = []
    for r in rows:
        name = r.get("name", "")
        tag = r.get("tag", "")  # required | transitive | (any)
        role = r.get("role", "")
        why = r.get("why", "")
        version = r.get("version", "")
        tag_class = "dep-tag-required" if tag == "required" else ("dep-tag-transitive" if tag == "transitive" else "")
        tag_html = f'<span class="dep-tag {tag_class}">{_e(tag)}</span>' if tag else ""
        row_html.append(
            f'<div class="dep-row">'
            f'<div class="dep-col-name"><span class="mono dep-name">{_e(name)}</span>{tag_html}</div>'
            f'<div class="dep-col-role">{_e(role)}</div>'
            f'<div class="dep-col-why">{_e(why)}</div>'
            f'<div class="dep-col-ver mono">{_e(version)}</div>'
            f'</div>'
        )
    return f'<div class="dep-list">{"".join(row_html)}</div>'


def _emit_q_list(s: dict[str, Any]) -> str:
    """`q-list`: numbered Q&A list. Rows: [{num, title, body}]."""
    rows = s.get("rows", [])
    row_html = []
    for i, r in enumerate(rows, start=1):
        num = r.get("num", f"{i:02d}")
        title = r.get("title", "")
        body = r.get("body", "")
        row_html.append(
            f'<div class="q-row">'
            f'<span class="q-num mono">{_e(num)}</span>'
            f'<div class="q-body"><h4>{_e(title)}</h4><p>{_e(body)}</p></div>'
            f'</div>'
        )
    return f'<div class="q-list">{"".join(row_html)}</div>'


def _emit_steps(s: dict[str, Any]) -> str:
    """`steps`: timeline of numbered steps. Rows: [{num, title, desc}]."""
    rows = s.get("rows", [])
    row_html = []
    for i, r in enumerate(rows, start=0):
        num = r.get("num", f"{i:02d}")
        title = r.get("title", "")
        desc = r.get("desc", "")
        row_html.append(
            f'<div class="step-row">'
            f'<span class="step-num mono">{_e(num)}</span>'
            f'<div class="step-body"><div class="step-title">{_e(title)}</div><div class="step-desc">{_e(desc)}</div></div>'
            f'</div>'
        )
    return f'<div class="steps">{"".join(row_html)}</div>'


def _emit_code_shell(s: dict[str, Any]) -> str:
    """`code-shell`: macOS-style code block with traffic dots + language tag."""
    lang = s.get("lang", "")
    code = s.get("code", "")
    path = s.get("path", "")
    path_html = f'<div class="file-path">{_e(path)}</div>' if path else ""
    return (
        f'{path_html}'
        f'<div class="code-shell">'
        f'<div class="code-bar">'
        f'<span class="code-dots"><i style="background:#ff5f57"></i><i style="background:#febc2e"></i><i style="background:#28c840"></i></span>'
        f'<span class="code-lang">{_e(lang)}</span>'
        f'</div>'
        f'<pre class="code"><code>{_e(code)}</code></pre>'
        f'</div>'
    )


def _emit_color_strip(s: dict[str, Any]) -> str:
    """`color-strip`: grid of color swatches. Colors: [{hex, name, role}]."""
    colors = s.get("colors", [])
    cells = []
    for c in colors:
        hex_value = _validate_color(c.get("hex", "#000000"), "color-strip.hex")
        name = c.get("name", "")
        role = c.get("role", "")
        cells.append(
            f'<div class="color-cell">'
            f'<div class="color-swatch" style="background:{_e(hex_value)};"></div>'
            f'<div class="color-meta">'
            f'<span class="color-hex mono">{_e(hex_value)}</span>'
            f'<span class="color-name">{_e(name)}</span>'
            f'<span class="color-role">{_e(role)}</span>'
            f'</div>'
            f'</div>'
        )
    return f'<div class="color-strip">{"".join(cells)}</div>'


def _emit_fit_row(s: dict[str, Any]) -> str:
    """`fit-row`: pill list with leading status dots. Items: [{label, avoid?}]."""
    items = s.get("items", [])
    chip_html = []
    for it in items:
        if isinstance(it, dict):
            label = it.get("label", "")
            avoid = bool(it.get("avoid", False))
        else:
            label = str(it)
            avoid = False
        cls = "fit avoid" if avoid else "fit"
        chip_html.append(f'<span class="{cls}">{_e(label)}</span>')
    return f'<div class="fit-row">{"".join(chip_html)}</div>'


def _emit_anti(s: dict[str, Any]) -> str:
    """`anti`: anti-pattern block with DO NOT label and bullet list."""
    items = s.get("items", [])
    li = "".join(f'<li>{_e(x)}</li>' for x in items)
    return f'<div class="anti"><ul>{li}</ul></div>'


def _emit_checklist(s: dict[str, Any]) -> str:
    """`checklist`: single-column list with mono `·` markers."""
    items = s.get("items", [])
    rows = "".join(
        f'<div class="chk"><span class="chk-mark">·</span><span>{_e(x)}</span></div>'
        for x in items
    )
    return f'<div class="check-list">{rows}</div>'


def _emit_callout(s: dict[str, Any]) -> str:
    """`callout`: accent-tinted advisory block. Items: [...] (li bullets)."""
    title = s.get("title", "")
    items = s.get("items", [])
    body = s.get("body", "")
    title_html = f'<h4>{_e(title)}</h4>' if title else ""
    list_html = ""
    if items:
        list_html = "<ul>" + "".join(f"<li>{_e(x)}</li>" for x in items) + "</ul>"
    body_html = f"<p>{_e(body)}</p>" if body else ""
    return f'<div class="callout">{title_html}{list_html}{body_html}</div>'


def _emit_subhead(s: dict[str, Any]) -> str:
    return f'<div class="subhead">{_e(s.get("text", ""))}</div>'


def _table_scroll(table_html: str) -> str:
    """Wrap a generated table without changing its cells or native semantics."""
    from html.parser import HTMLParser

    class Headers(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.cells: list[list[str]] = []
            self.in_header = False

        def handle_starttag(self, tag, attrs):
            if tag == "th":
                self.cells.append([])
                self.in_header = True
            elif tag == "img" and self.in_header:
                self.cells[-1].append(dict(attrs).get("alt") or "")

        def handle_endtag(self, tag):
            if tag == "th":
                self.in_header = False

        def handle_data(self, data):
            if self.in_header:
                self.cells[-1].append(data)

    headers = Headers()
    headers.feed(table_html)
    labels = ["".join(cell).strip() for cell in headers.cells]
    labels = [label for label in labels if label]
    label = "Table: " + ", ".join(labels) if labels else "Table data"
    return (f'<div class="table-scroll" role="region" tabindex="0" aria-label="{_e(label)}">'
            f'{table_html}</div>')


def _emit_props_table(s: dict[str, Any]) -> str:
    """`props-table`: classic prop/type/default/notes table."""
    headers = s.get("headers", ["Prop", "Type", "Default", "Notes"])
    rows = s.get("rows", [])
    th = "".join(f"<th>{_e(h)}</th>" for h in headers)
    tr = []
    for r in rows:
        name = r.get("name", "")
        type_ = r.get("type", "")
        default = r.get("default", "")
        notes = r.get("notes", "")
        tr.append(
            f'<tr>'
            f'<td class="mono prop-name">{_e(name)}</td>'
            f'<td><span class="type-pill mono">{_e(type_)}</span></td>'
            f'<td class="mono small muted">{_e(default)}</td>'
            f'<td class="muted">{_e(notes)}</td>'
            f'</tr>'
        )
    return _table_scroll(
        f'<table class="props"><thead><tr>{th}</tr></thead><tbody>{"".join(tr)}</tbody></table>'
    )


def _emit_status_table(s: dict[str, Any]) -> str:
    """`status-table`: typed table where the status column becomes a colored badge.

    Auto-detects a status column from headers matching status|state|result.
    Values like DONE / PASS get green badges, FAIL / ERROR red, IN_PROGRESS indigo, etc.
    Rows: list of dicts (column-name -> value).
    """
    rows = s.get("rows", [])
    if not rows:
        return ""
    headers = list(rows[0].keys())
    status_col = None
    for h in headers:
        if h.lower() in ("status", "state", "result"):
            status_col = h
            break

    th = "".join(f"<th>{_e(h)}</th>" for h in headers)
    tr = []
    for r in rows:
        cells = []
        for h in headers:
            v = str(r.get(h, ""))
            if h == status_col:
                badge_class = re.sub(r"[^a-z0-9-]", "-", v.lower())
                cells.append(f'<td><span class="badge {badge_class}">{_e(v)}</span></td>')
            else:
                cells.append(f'<td>{_e(v)}</td>')
        tr.append(f'<tr>{"".join(cells)}</tr>')
    return _table_scroll(
        f'<table class="props"><thead><tr>{th}</tr></thead><tbody>{"".join(tr)}</tbody></table>'
    )


# Registry of section kinds → emitter functions
_SECTION_EMITTERS: dict[str, Any] = {
    "hero": _emit_hero,
    "sec": _emit_section,
    "stack-list": _emit_stack_list,
    "dep-list": _emit_dep_list,
    "q-list": _emit_q_list,
    "steps": _emit_steps,
    "code-shell": _emit_code_shell,
    "color-strip": _emit_color_strip,
    "fit-row": _emit_fit_row,
    "anti": _emit_anti,
    "checklist": _emit_checklist,
    "callout": _emit_callout,
    "subhead": _emit_subhead,
    "props-table": _emit_props_table,
    "status-table": _emit_status_table,
    "diagram": render_diagram,
    "chart": render_chart,
}


def _md_to_html(md: str) -> str:
    """Markdown → HTML converter using ``re`` only (no runtime deps).

    Supports the subset of GitHub-Flavored Markdown needed to render the
    repo's own docs (README, CHANGELOG, CONTRIBUTING, etc.):

    * Headings ``#`` … ``######``
    * ``**bold**``, ``*italic*``, `` `inline code` ``
    * ``[link](url)`` and ``![alt](url)`` images
    * Unordered (``-`` / ``*``) and ordered (``1.``) lists
    * Blockquotes (``> …``) with multi-line content
    * Horizontal rules (``---``, ``***``, ``___``)
    * Fenced code blocks with optional language tag (```` ```lang ````)
    * GFM tables (header row + ``|---|`` separator), with escaped literal pipes
    * Backslash-escaped ASCII punctuation outside code spans
    * Bare http(s) URL auto-linking
    * Raw HTML is escaped; only the explicit body_html input is trusted.

    Output is wrapped in ``<div class="prose">`` so the atv tier's prose
    stylesheet can style it without colliding with section-based renders.
    """
    lines = md.replace("\x00", "\ufffd").split("\n")
    html_lines: list[str] = []
    state: dict[str, Any] = {
        "in_p": False, "in_ul": False, "in_ol": False,
        "in_bq": False, "_bq_kind": "",
    }

    def close_p() -> None:
        if state["in_p"]:
            html_lines.append("</p>")
            state["in_p"] = False

    def close_ul() -> None:
        if state["in_ul"]:
            html_lines.append("</ul>")
            state["in_ul"] = False

    def close_ol() -> None:
        if state["in_ol"]:
            html_lines.append("</ol>")
            state["in_ol"] = False

    def close_bq() -> None:
        if state["in_bq"]:
            if state.get("_bq_kind"):
                html_lines.append("</div></aside>")
                state["_bq_kind"] = ""  # type: ignore[assignment]
            else:
                html_lines.append("</blockquote>")
            state["in_bq"] = False

    def close_all() -> None:
        close_p(); close_ul(); close_ol(); close_bq()

    def inline(text: str) -> str:
        # Protect escaped punctuation and code, then HTML-escape source text
        # so user content can't inject HTML; then re-introduce
        # the small set of markdown-derived tags. After escaping we restore
        # well-known HTML entity sequences (``&amp;mdash;`` → ``&mdash;``)
        # so authors can write ``&mdash;`` / ``&#8212;`` / ``&#x2014;``
        # directly in prose and have the browser render the actual glyph.
        # This is safe because the restored shape is strictly
        # ``&<named-entity>;`` or ``&#<digits>;`` or ``&#x<hex>;`` — none of
        # which can encode a tag, attribute, or script.
        #
        # Code spans must NOT have their entities restored — backticks mean
        # "show me the source as typed", which on GitHub means an author who
        # writes ``\u0060&mdash;\u0060`` sees the literal characters, not the
        # em-dash glyph. We park code spans behind opaque placeholders before
        # the entity restoration pass and put them back at the end.
        code_spans: list[str] = []

        def protect_literal(m: re.Match[str]) -> str:
            if m.group(1) is not None:
                # An entity stays text through all Markdown regex passes,
                # including escaped brackets, backticks, and ampersands.
                return f"&#{ord(m.group(1))};"
            # The alternation consumes each code span whole: backslashes and
            # entities inside actual code must not undergo prose unescaping.
            code_spans.append(_html_lib.escape(m.group(2)))
            return f"\x00CODE{len(code_spans) - 1}\x00"

        text = _html_lib.escape(re.sub(
            r"""\\([!"#$%&'()*+,\-./:;<=>?@\[\]\\^_`{|}~])|`([^`]+)`""",
            protect_literal, text,
        ))
        # Now restore HTML entities outside code spans.
        text = re.sub(
            r"&amp;(#\d+|#x[0-9a-fA-F]+|[a-zA-Z][a-zA-Z0-9]*);",
            r"&\1;",
            text,
        )
        links: list[str] = []

        def stash_link(value: str) -> str:
            links.append(value)
            return f"\x00LINK{len(links) - 1}\x00"

        literals: list[str] = []

        def stash_literal(m: re.Match[str]) -> str:
            literals.append(m.group(0))
            return f"\x00LITERAL{len(literals) - 1}\x00"

        # Protect literal tag-shaped text and escaped link notation before
        # other markup passes. Attribute URLs and literal destinations are
        # source text, not requests to synthesize links or emphasis.
        text = re.sub(
            r"&lt;[^\n]*?&gt;|(?:&#91;[^\n]*?(?:&#93;|\])|\[[^\n]*?&#93;)\([^)\n]*\)",
            stash_literal, text,
        )

        def image(m: re.Match[str]) -> str:
            url = _safe_url(m.group(2), image=True)
            alt = _html_lib.escape(_html_lib.unescape(m.group(1)))
            if url is None:
                return alt
            return stash_link(f'<img alt="{alt}" src="{_e(url)}" loading="lazy" />')

        text = re.sub(
            r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+&quot;[^&]*&quot;)?\)", image, text,
        )
        # Bold then italic so ``**foo**`` doesn't get eaten by the italic rule.
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"__(.+?)__", r"<strong>\1</strong>", text)
        text = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"<em>\1</em>", text)
        # Underscore italics — require word boundaries so we don't mangle
        # snake_case identifiers like ``opencode_config``.
        text = re.sub(r"(?<![\w_])_([^_\n]+?)_(?![\w_])", r"<em>\1</em>", text)
        def link(m: re.Match[str]) -> str:
            url = _safe_url(m.group(2))
            if url is None:
                return stash_link(m.group(1))
            return stash_link(f'<a href="{_e(url)}">{m.group(1)}</a>')

        text = re.sub(
            r"\[([^\]]+)\]\(([^)\s]+)(?:\s+&quot;[^&]*&quot;)?\)", link, text,
        )
        # Stashed links and images cannot acquire nested auto-links.
        text = re.sub(
            r'https?://[^\s<>"\'\x00]+',
            lambda m: stash_link(f'<a href="{_e(_html_lib.unescape(m.group(0)))}">{m.group(0)}</a>'),
            text,
        )
        text = re.sub(r"\x00LINK(\d+)\x00", lambda m: links[int(m.group(1))], text)
        # Literal labels can live inside generated links or image alt text;
        # restore them after links, but before any embedded code-span tokens.
        text = re.sub(r"\x00LITERAL(\d+)\x00", lambda m: literals[int(m.group(1))], text)
        # Restore code spans last so their literal contents (including any
        # ``&amp;mdash;`` source) are preserved as the author typed them.
        if code_spans:
            def _unstash(m: re.Match[str]) -> str:
                return f"<code>{code_spans[int(m.group(1))]}</code>"

            text = re.sub(r"\x00CODE(\d+)\x00", _unstash, text)
        return text

    def table_cells(line: str) -> list[str] | None:
        """Split structural pipes only; consume a pipe escape at table level.

        Paired backslashes remain for inline parsing. Only the backslash
        escaping a pipe is removed here, including inside table code spans.
        """
        row = line.strip()
        cells: list[str] = []
        cell: list[str] = []
        index = 0
        delimiter = last_delimiter = False
        while index < len(row):
            char = row[index]
            last_delimiter = False
            if char == "\\" and index + 1 < len(row):
                following = row[index + 1]
                cell.extend(["|"] if following == "|" else [char, following])
                index += 2
                continue
            if char == "|":
                cells.append("".join(cell).strip())
                cell = []
                delimiter = last_delimiter = True
            else:
                cell.append(char)
            index += 1
        if not delimiter:
            return None
        cells.append("".join(cell).strip())
        if row.startswith("|"):
            cells.pop(0)
        if last_delimiter:
            cells.pop()
        return cells

    i = 0
    n = len(lines)
    table_sep_re = re.compile(
        r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$"
    )

    while i < n:
        line = lines[i]

        # Fenced code block (```lang … ```)
        fence = re.match(r"^```(\w*)\s*$", line)
        if fence:
            close_all()
            lang = fence.group(1) or ""
            i += 1
            code_lines: list[str] = []
            while i < n and not re.match(r"^```\s*$", lines[i]):
                code_lines.append(lines[i])
                i += 1
            i += 1  # skip closing fence (if present)
            code_html = _html_lib.escape("\n".join(code_lines))
            lang_attr = f' data-lang="{_html_lib.escape(lang)}"' if lang else ""
            html_lines.append(
                f'<pre class="code-block"{lang_attr}><code>{code_html}</code></pre>'
            )
            continue

        # GFM table — header row immediately followed by ``|---|`` separator.
        headers = table_cells(line)
        if headers is not None and i + 1 < n and table_sep_re.match(lines[i + 1]):
            close_all()
            table_start = len(html_lines)
            html_lines.append('<table class="md">')
            html_lines.append("<thead><tr>")
            for h in headers:
                html_lines.append(f"<th>{inline(h)}</th>")
            html_lines.append("</tr></thead>")
            i += 2  # skip header and separator
            html_lines.append("<tbody>")
            while i < n and lines[i].strip():
                cells = table_cells(lines[i])
                if cells is None:
                    break
                html_lines.append("<tr>")
                for c in cells:
                    html_lines.append(f"<td>{inline(c)}</td>")
                html_lines.append("</tr>")
                i += 1
            html_lines.append("</tbody></table>")
            html_lines[table_start:] = [_table_scroll("\n".join(html_lines[table_start:]))]
            continue

        # Horizontal rule (---, ***, ___, optionally spaced).
        if re.match(r"^\s*(?:-\s*){3,}$|^\s*(?:\*\s*){3,}$|^\s*(?:_\s*){3,}$", line):
            close_all()
            html_lines.append("<hr />")
            i += 1
            continue

        # ATX headings ``# `` … ``###### ``
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading:
            close_all()
            level = len(heading.group(1))
            # Optional closing hashes need a preceding space. A literal \#
            # at the end of a source title must reach inline() intact.
            content = re.sub(r"\s+#+$", "", heading.group(2))
            html_lines.append(
                f"<h{level}>{inline(content)}</h{level}>"
            )
            i += 1
            continue

        # Blockquote (``> …``), possibly with empty ``>`` line as separator.
        # GFM alert syntax (``> [!NOTE]`` etc.) renders as a typed callout
        # panel instead of a plain blockquote.
        bq = re.match(r"^>\s?(.*)$", line)
        if bq:
            close_p(); close_ul(); close_ol()
            content = bq.group(1)
            alert_m = re.match(
                r"^\s*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*(.*)$",
                content,
            )
            if alert_m and not state["in_bq"]:
                kind = alert_m.group(1).lower()
                rest = alert_m.group(2).strip()
                html_lines.append(
                    f'<aside class="callout callout-{kind}">'
                    f'<div class="callout-label">{kind.upper()}</div>'
                    f'<div class="callout-body">'
                )
                state["in_bq"] = True
                state["_bq_kind"] = kind  # type: ignore[assignment]
                if rest:
                    html_lines.append(inline(rest) + "<br />")
                i += 1
                continue
            if not state["in_bq"]:
                html_lines.append("<blockquote>")
                state["in_bq"] = True
            if content.strip():
                html_lines.append(inline(content) + "<br />")
            else:
                html_lines.append("<br />")
            i += 1
            continue

        # Unordered list
        ul = re.match(r"^[-*+]\s+(.+)$", line)
        if ul:
            close_p(); close_ol(); close_bq()
            if not state["in_ul"]:
                html_lines.append("<ul>")
                state["in_ul"] = True
            html_lines.append(f"<li>{inline(ul.group(1))}</li>")
            i += 1
            continue

        # Ordered list
        ol = re.match(r"^\d+\.\s+(.+)$", line)
        if ol:
            close_p(); close_ul(); close_bq()
            if not state["in_ol"]:
                html_lines.append("<ol>")
                state["in_ol"] = True
            html_lines.append(f"<li>{inline(ol.group(1))}</li>")
            i += 1
            continue

        # Blank line → close any open block.
        if line.strip() == "":
            close_all()
            i += 1
            continue

        # Default: paragraph continuation. Blockquote takes precedence so it
        # absorbs multi-line content.
        if state["in_bq"]:
            html_lines.append(inline(line) + " ")
            i += 1
            continue
        if not state["in_p"]:
            html_lines.append("<p>")
            state["in_p"] = True
        html_lines.append(inline(line))
        i += 1

    close_all()
    return '<div class="prose">\n' + "\n".join(html_lines) + "\n</div>"


def _rows_to_table(rows: list[dict]) -> str:
    """Keep first-row column order; reject later extras rather than drop cells."""
    validate_input({"rows": rows})
    headers = list(rows[0].keys())
    th_cells = "".join(f"<th>{_html_lib.escape(str(h))}</th>" for h in headers)
    thead = f"<thead><tr>{th_cells}</tr></thead>"
    tbody_rows: list[str] = []
    for row in rows:
        td_cells = "".join(
            f"<td>{_html_lib.escape(str(row.get(h, '')))}</td>" for h in headers
        )
        tbody_rows.append(f"<tr>{td_cells}</tr>")
    tbody = f"<tbody>{''.join(tbody_rows)}</tbody>"
    return f"<table>{thead}{tbody}</table>"


def _slugify(title: str) -> str:
    """Convert a title to a bounded, cross-platform filename-safe slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:100].rstrip("-") or "artifact"
    if slug == "gallery" or re.fullmatch(r"con|prn|aux|nul|com[0-9]|lpt[0-9]", slug):
        slug = "artifact-" + slug
    return slug


def _unique_slug(base: str, output_dir: Path) -> str:
    """Check every triple suffix, including orphaned sidecars and symlinks."""
    candidate = base
    index = 1
    while any((output_dir / f"{candidate}{suffix}").exists() or
              (output_dir / f"{candidate}{suffix}").is_symlink() for suffix in _TRIPLE_SUFFIXES):
        candidate = f"{base}-{index}"
        index += 1
    return candidate

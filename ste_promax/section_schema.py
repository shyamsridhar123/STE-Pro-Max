"""Native STE-Pro-Max resources.
Copyright (c) 2026 Shyam Sridhar and contributors.
SPDX-License-Identifier: Apache-2.0
Source commit: 4b068bcab8e4dc105f0ef975ee224564f5d63383.
Changes: offline system fonts, safe metadata, native STE-Pro-Max branding.
Native STE section schema; section fields are plain text, not trusted HTML.
Keep this registry aligned with ste_promax.render._SECTION_EMITTERS.
row_fields lists the fixed-column row keys used by renderer input preflight.
status-table instead derives its permitted columns from the first supplied row.
"""
from __future__ import annotations

from typing import Any

from .charts import CHART_SCHEMA
from .diagrams import DIAGRAM_SCHEMA

SECTION_SCHEMA: dict[str, dict[str, Any]] = {
    "hero": {
        "description": (
            "Top-of-page eyebrow + headline + sub + meta strip. "
            "Use exactly one per artifact, as the first section."
        ),
        "fields": {
            "eyebrow": "Small uppercase label above the headline. Optional.",
            "title": "Main H1 headline.",
            "title_into": "Optional grayed-out continuation rendered after the title.",
            "sub": "Lede paragraph below the headline. Optional.",
            "meta": "List of {label, value} pairs rendered as a horizontal strip below the sub. Optional.",
        },
        "example": {
            "kind": "hero",
            "eyebrow": "Release report",
            "title": "An illustrative release note.",
            "title_into": "not a release approval.",
            "sub": "Example content for a local document. Review its evidence and limitations before acting.",
            "meta": [
                {"label": "Example", "value": "Fictional"},
                {"label": "Tier", "value": "ste"},
            ],
        },
    },
    "sec": {
        "description": (
            "Numbered section wrapper with eyebrow + h2 + lede + nested body. "
            "Contains other section kinds as children via the body array."
        ),
        "fields": {
            "num": "Section number, monospaced. Optional. Convention: '01', '02', ...",
            "eyebrow": "Small label above the h2. Optional.",
            "title": "Section h2 headline.",
            "aside": "Right-aligned pill in the section head. Optional.",
            "lede": "Lede paragraph below the head. Optional.",
            "zebra": "Boolean; if true, alternates background tint. Optional.",
            "tight": "Boolean; if true, reduces vertical padding. Optional.",
            "body": "List of child sections (kinds: stack-list, dep-list, q-list, steps, etc.).",
        },
        "example": {
            "kind": "sec",
            "num": "01",
            "eyebrow": "Status",
            "title": "Pipeline health.",
            "lede": "Build, lint, and tests after the v0.2.0 changes.",
            "body": [
                {"kind": "status-table", "rows": [{"check": "build", "status": "PASS"}]},
            ],
        },
    },
    "stack-list": {
        "row_fields": ("name", "tag", "tag_kind", "why", "fix"),
        "description": (
            "Three-column hairline list: name + tag on the left, why in the middle, "
            "fix/recommendation on the right. Best for item/why/fix tables."
        ),
        "fields": {
            "rows": (
                "List of {name, tag, tag_kind, why, fix}. "
                "tag_kind ∈ {shadcn, tailwind, typescript} controls the tag color. "
                "why and fix are plain text; HTML is escaped."
            ),
        },
        "example": {
            "kind": "stack-list",
            "rows": [
                {
                    "name": "hero",
                    "tag": "layout",
                    "tag_kind": "shadcn",
                    "why": "Top-of-page eyebrow, headline, sub, meta strip.",
                    "fix": "{kind: hero, title, sub, meta}",
                },
            ],
        },
    },
    "dep-list": {
        "row_fields": ("name", "tag", "role", "why", "version"),
        "description": (
            "Four-column list (name+tag / role / why / version). "
            "Best for dependency audits and package inventories."
        ),
        "fields": {
            "rows": (
                "List of {name, tag, role, why, version}. "
                "tag ∈ {required, transitive} controls the tag color."
            ),
        },
        "example": {
            "kind": "dep-list",
            "rows": [
                {
                    "name": "jinja2",
                    "tag": "required",
                    "role": "templating",
                    "why": "Renders the ste-tier template.",
                    "version": ">=3.1.0",
                },
            ],
        },
    },
    "q-list": {
        "row_fields": ("num", "title", "body"),
        "description": (
            "Numbered Q&A list. Renders each row with a left-side number gutter "
            "and an h4 question + paragraph body. Best for intake checklists."
        ),
        "fields": {
            "rows": (
                "List of {num, title, body}. "
                "num is optional and auto-derived from row index (zero-padded). "
                "body are plain text; HTML is escaped."
            ),
        },
        "example": {
            "kind": "q-list",
            "rows": [
                {"num": "01", "title": "What is the target tier?", "body": "Default is ste."},
                {"num": "02", "title": "Where does input come from?", "body": "Agent-constructed JSON via stdin."},
            ],
        },
    },
    "steps": {
        "row_fields": ("num", "title", "desc"),
        "description": (
            "Vertical timeline with monospaced number markers. "
            "Best for sequential procedures or onboarding flows."
        ),
        "fields": {
            "rows": (
                "List of {num, title, desc}. "
                "num is optional and auto-derived (zero-padded, starts at 00). "
                "desc are plain text; HTML is escaped."
            ),
        },
        "example": {
            "kind": "steps",
            "rows": [
                {"num": "01", "title": "Install", "desc": "Use the local STE-Pro-Max package"},
                {"num": "02", "title": "Render", "desc": "Render report.json with STE-Pro-Max"},
            ],
        },
    },
    "code-shell": {
        "description": (
            "macOS-style code block with traffic-light dots and a language tag. "
            "Best for code samples in documentation."
        ),
        "fields": {
            "lang": "Language label shown in the title bar (e.g. 'json', 'python').",
            "code": "Raw code body. Newlines preserved; HTML-escaped on render.",
            "path": "Optional file-path label rendered above the code block.",
        },
        "example": {
            "kind": "code-shell",
            "lang": "json",
            "path": "report.json",
            "code": '{\n  "title": "Pipeline Report",\n  "sections": []\n}',
        },
    },
    "color-strip": {
        "description": (
            "Grid of color swatch cards (hex / name / role). "
            "Best for palette documentation."
        ),
        "fields": {
            "colors": "List of {hex, name, role}. hex is the swatch fill (e.g. '#f59e0b').",
        },
        "example": {
            "kind": "color-strip",
            "colors": [
                {"hex": "#f59e0b", "name": "amber", "role": "accent"},
                {"hex": "#0a0a0a", "name": "ink", "role": "background"},
            ],
        },
    },
    "fit-row": {
        "description": (
            "Pill row with leading green/rose dots. "
            "Best for fit / avoid signal pairs ('Use for X', 'Avoid for Y')."
        ),
        "fields": {
            "items": (
                "List of {label, avoid?} dicts OR plain strings. "
                "avoid=true renders a rose dot; default is green."
            ),
        },
        "example": {
            "kind": "fit-row",
            "items": [
                {"label": "Dashboards"},
                {"label": "Single-page reports"},
                {"label": "Marketing pages", "avoid": True},
            ],
        },
    },
    "anti": {
        "description": (
            "Anti-pattern block with implicit 'DO NOT' label and bulleted list. "
            "Best for don'ts lists in design-system docs."
        ),
        "fields": {
            "items": "List of strings (plain text; HTML is escaped). Rendered as <li> bullets.",
        },
        "example": {
            "kind": "anti",
            "items": [
                "Use drop shadows instead of borders.",
                "Hard-code colors outside the token system.",
            ],
        },
    },
    "checklist": {
        "description": (
            "Single-column list with mono '·' markers. "
            "Best for verification checklists and acceptance criteria."
        ),
        "fields": {
            "items": "List of strings (plain text; HTML is escaped).",
        },
        "example": {
            "kind": "checklist",
            "items": [
                "All tests pass.",
                "ruff clean.",
                "CHANGELOG updated.",
            ],
        },
    },
    "callout": {
        "description": (
            "Accent-tinted advisory block with optional title and bullet list. "
            "Use sparingly — at most one or two per artifact."
        ),
        "fields": {
            "title": "Optional h4 title.",
            "items": "Optional list of strings rendered as <li> bullets.",
            "body": "Optional paragraph body (plain text; HTML is escaped).",
        },
        "example": {
            "kind": "callout",
            "title": "Heads up",
            "items": [
                "The sections array bypasses rows/body_md when present.",
                "Pick one input mode per artifact.",
            ],
        },
    },
    "subhead": {
        "description": (
            "Mono uppercase label inside a section. Use for sub-grouping inside a sec body."
        ),
        "fields": {
            "text": "Label text. Rendered uppercase via CSS.",
        },
        "example": {"kind": "subhead", "text": "Inputs"},
    },
    "props-table": {
        "row_fields": ("name", "type", "default", "notes"),
        "description": (
            "Classic prop/type/default/notes table. "
            "Best for API surfaces and configuration references."
        ),
        "fields": {
            "headers": "Optional list of column headers. Defaults to ['Prop', 'Type', 'Default', 'Notes'].",
            "rows": "List of {name, type, default, notes}. notes are plain text; HTML is escaped.",
        },
        "example": {
            "kind": "props-table",
            "rows": [
                {
                    "name": "tier",
                    "type": "string",
                    "default": "ste",
                    "notes": "The native offline STE template.",
                },
            ],
        },
    },
    "status-table": {
        "description": (
            "Typed table where the status / state / result column auto-renders as a colored badge. "
            "DONE/PASS green, FAIL/ERROR red, IN_PROGRESS indigo. "
            "Best for build matrices and CI dashboards."
        ),
        "fields": {
            "rows": (
                "List of dicts. Column headers are inferred from the first row's keys. "
                "Any column named status / state / result is rendered as a badge."
            ),
        },
        "example": {
            "kind": "status-table",
            "rows": [
                {"check": "build", "status": "PASS"},
                {"check": "lint", "status": "PASS"},
                {"check": "tests", "status": "FAIL"},
            ],
        },
    },
    "diagram": DIAGRAM_SCHEMA,
    "chart": CHART_SCHEMA,
}


def list_kinds() -> list[str]:
    """Return the section kinds in registration order."""
    return list(SECTION_SCHEMA.keys())


def get_kind(name: str) -> dict[str, Any] | None:
    """Return the schema entry for a single kind, or None if unknown."""
    return SECTION_SCHEMA.get(name)

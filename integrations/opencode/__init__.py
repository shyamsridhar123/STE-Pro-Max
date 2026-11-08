"""OpenCode V2 STE-Pro-Max host adapter and bounded CLI JSON dispatcher."""
from __future__ import annotations

from pathlib import Path

from integrations.opencode.dispatch import (
    BUNDLE_ROOT,
    OPENCODE_PLUGIN_ID,
    STE_SKILL_IDS,
    STE_TOOL_NAMES,
    dispatch_operation,
    main,
    resolve_bundle_root,
)

PLUGIN_DIR: Path = Path(__file__).resolve().parent
SERVER_JS_PATH: Path = PLUGIN_DIR / "server.js"
INDEX_JS_PATH: Path = PLUGIN_DIR / "index.js"
PACKAGE_JSON_PATH: Path = PLUGIN_DIR / "package.json"

__all__ = [
    "BUNDLE_ROOT",
    "INDEX_JS_PATH",
    "OPENCODE_PLUGIN_ID",
    "PACKAGE_JSON_PATH",
    "PLUGIN_DIR",
    "SERVER_JS_PATH",
    "STE_SKILL_IDS",
    "STE_TOOL_NAMES",
    "dispatch_operation",
    "main",
    "resolve_bundle_root",
]

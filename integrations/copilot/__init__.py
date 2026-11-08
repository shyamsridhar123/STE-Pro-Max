"""GitHub Copilot CLI workspace-binding hook adapter for STE-Pro-Max."""
from __future__ import annotations

from .hook_entry import dispatch_hook, main
from .scope import (
    STE_AGENT_IDS,
    STE_PLUGIN_ID,
    STE_SKILL_IDS,
    bind_session_workspace,
    is_ste_mcp_tool_name,
    load_session_record,
    resolve_session_workspace,
    save_session_record,
)

__all__ = [
    "STE_AGENT_IDS",
    "STE_PLUGIN_ID",
    "STE_SKILL_IDS",
    "bind_session_workspace",
    "dispatch_hook",
    "is_ste_mcp_tool_name",
    "load_session_record",
    "main",
    "resolve_session_workspace",
    "save_session_record",
]

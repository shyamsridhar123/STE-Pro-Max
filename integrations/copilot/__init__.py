"""GitHub Copilot CLI hook and session-scope adapter for STE-Pro-Max."""
from __future__ import annotations

from .hook_entry import dispatch_hook, main
from .scope import (
    STE_AGENT_IDS,
    STE_PLUGIN_ID,
    STE_SKILL_IDS,
    activate_session_scope,
    deactivate_session_scope,
    is_exact_ste_skill_md_path,
    is_explicit_user_ste_off,
    is_ste_agent_identifier,
    is_ste_skill_identifier,
    resolve_session_scope,
)

__all__ = [
    "STE_AGENT_IDS",
    "STE_PLUGIN_ID",
    "STE_SKILL_IDS",
    "activate_session_scope",
    "deactivate_session_scope",
    "dispatch_hook",
    "is_exact_ste_skill_md_path",
    "is_explicit_user_ste_off",
    "is_ste_agent_identifier",
    "is_ste_skill_identifier",
    "main",
    "resolve_session_scope",
]

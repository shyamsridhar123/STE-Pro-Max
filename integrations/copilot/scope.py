"""Session workspace bookkeeping for GitHub Copilot CLI and the STE-Pro-Max MCP server.

Binds exact trusted host workspace directories (`workingDirectory` / `cwd`) to
Copilot CLI `sessionId` records so `preMcpToolCall` can attach `ste_session_id`
to `ste-promax/*` MCP calls (`metaToUse.ste_session_id -> ctx.request_context.meta`),
and `integrations.mcp.operations.resolve_trusted_workspace(session_id=...)` can
resolve the exact saved session workspace without CWD or latest-session mtime
guessing. Does not activate or enforce session-wide host tool restrictions.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import time
from typing import Any

from integrations.mcp.operations import STE_MCP_TOOL_NAMES
from ste_promax.policy_runtime import (
    PolicyError,
    check_safe_lexical_path,
    is_link_or_reparse,
    resolve_state_root,
)

STE_PLUGIN_ID = "ste-pro-max"

STE_SKILL_IDS: frozenset[str] = frozenset({
    "ste-promax",
    "ste-visual-docs",
    "ste-storytelling",
    "ste-line-studio",
})

STE_AGENT_IDS: frozenset[str] = frozenset({
    "ste-author",
})


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def is_ste_mcp_tool_name(raw: Any) -> tuple[bool, str]:
    if not isinstance(raw, str) or not raw.strip():
        return False, ""
    text = raw.strip()
    if text in STE_MCP_TOOL_NAMES:
        return True, text
    for prefix in (
        "ste-promax/",
        "ste-promax.",
        "ste-promax:",
        "ste-promax-",
        "ste-promax_",
        "ste_promax/",
        "mcp__ste-promax__",
        "mcp__ste_promax__",
    ):
        if text.startswith(prefix):
            candidate = text[len(prefix):]
            if candidate in STE_MCP_TOOL_NAMES:
                return True, candidate
    return False, ""


def _sessions_state_dir() -> Path:
    root = resolve_state_root()
    target = root / "copilot-sessions"
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    return target


def _session_record_path(session_id: str) -> Path:
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:32]
    return _sessions_state_dir() / f"session-{digest}.json"


def load_session_record(session_id: str) -> dict[str, Any] | None:
    if not isinstance(session_id, str) or not session_id.strip():
        return None
    path = _session_record_path(session_id.strip())
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if is_link_or_reparse(info) or not stat.S_ISREG(info.st_mode):
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def save_session_record(session_id: str, record: dict[str, Any]) -> dict[str, Any]:
    clean_id = session_id.strip()
    path = _session_record_path(clean_id)
    payload = {
        "schema": "ste-promax.copilot-session-workspace.v1",
        "session_id": clean_id,
        "working_directory": record.get("working_directory"),
        "updated_at": _utc_now(),
    }
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{secrets.token_hex(4)}")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
        for attempt in range(6):
            try:
                tmp.replace(path)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.015 * (attempt + 1))
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
    return payload


def bind_session_workspace(
    session_id: str,
    *,
    working_directory: str | Path | None = None,
) -> dict[str, Any]:
    """Bind or update a session's saved working_directory record."""
    existing = load_session_record(session_id) or {}
    wd_str = str(working_directory).strip() if working_directory is not None else ""
    merged = {
        **existing,
        "working_directory": wd_str or existing.get("working_directory"),
    }
    return save_session_record(session_id, merged)


def resolve_session_workspace(
    payload: dict[str, Any],
    *,
    hook_name: str = "",
) -> dict[str, Any]:
    """Resolve and persist the trusted session workspace directory for Copilot CLI hooks.

    - For `preMcpToolCall` targeting `ste-promax`: requires a valid `sessionId` and an
      existing local `workingDirectory`/`cwd`, failing closed without authorizing any
      older session workspace record if missing or invalid.
    - For `sessionStart`: best-effort binds `working_directory` when valid; never raises
      or restricts.
    - For any other hook or foreign MCP call: pure no-op without state access or writes.
    """
    session_id = str(payload.get("sessionId") or "").strip()
    raw_wd = str(payload.get("workingDirectory") or payload.get("cwd") or "").strip() or None

    server_name = str(payload.get("serverName") or "").strip()
    tool_name = str(payload.get("toolName") or "").strip()
    is_ste_mcp, _ = is_ste_mcp_tool_name(tool_name)
    is_ste_pre_mcp = hook_name == "preMcpToolCall" and (
        server_name == "ste-promax" or (not server_name and is_ste_mcp)
    )

    if is_ste_pre_mcp:
        if not raw_wd:
            raise PolicyError(
                "preMcpToolCall requires a non-empty host workingDirectory/cwd for STE workspace binding.",
                code="policy_refusal",
            )
        _, res_wd = check_safe_lexical_path(
            raw_wd,
            "preMcpToolCall workingDirectory",
            require_absolute=True,
            code="policy_refusal",
        )
        if not res_wd.is_dir():
            raise PolicyError(
                f"preMcpToolCall workingDirectory is not an existing local directory: {res_wd}",
                code="policy_refusal",
            )
        if not session_id:
            raise PolicyError(
                "preMcpToolCall requires a non-empty sessionId for STE workspace binding.",
                code="policy_refusal",
            )
        saved = bind_session_workspace(
            session_id,
            working_directory=str(res_wd),
        )
        return {
            "session_id": session_id,
            "workspace_root": saved.get("working_directory"),
        }

    if hook_name == "sessionStart":
        workspace_root: Path | None = None
        if raw_wd:
            try:
                _, res_wd = check_safe_lexical_path(raw_wd, "hook workingDirectory")
                if res_wd.is_dir():
                    workspace_root = res_wd
            except PolicyError:
                workspace_root = None
        if not session_id:
            return {
                "session_id": "",
                "workspace_root": str(workspace_root) if workspace_root else None,
            }
        try:
            existing = load_session_record(session_id) or {}
            if workspace_root is not None:
                saved = bind_session_workspace(
                    session_id,
                    working_directory=str(workspace_root),
                )
                return {
                    "session_id": session_id,
                    "workspace_root": saved.get("working_directory"),
                }
            return {
                "session_id": session_id,
                "workspace_root": existing.get("working_directory"),
            }
        except Exception:
            return {
                "session_id": session_id,
                "workspace_root": str(workspace_root) if workspace_root else None,
            }

    return {
        "session_id": session_id,
        "workspace_root": None,
    }

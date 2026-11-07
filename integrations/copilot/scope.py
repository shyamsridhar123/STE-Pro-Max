"""Session scope tracking, parent/child inheritance, and events.jsonl recovery for Copilot CLI.

Rules enforced:
- Non-STE sessions remain unchanged.
- STE scope activates from:
  1. `skill` tool invocation with `toolArgs.skill` naming an STE skill (`ste-promax`,
     `ste-visual-docs`, `ste-storytelling`, `ste-line-studio`).
  2. Typed `skill.invoked` or `skill.invoked_ref` events in the session's `events.jsonl`.
  3. Typed `subagent.selected` or `subagent.started` events, or `subagentStart`/`preToolUse`
     hook metadata for the `ste-author` custom agent.
  4. Viewing an exact known installed STE `SKILL.md` file path via `view`/`read`.
  5. Invoking a `ste-promax/*` MCP tool.
  6. Parent-to-child subagent inheritance (`parentAgentId` -> child `sessionId`/`agentId`).
- Prompt text is NEVER keyword-matched to activate STE scope.
- Only an explicit user `/ste-off` command ends STE scope; no model-callable tool can disable it.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import time
from typing import Any

from integrations.mcp.operations import BUNDLE_ROOT, STE_MCP_TOOL_NAMES
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

_STE_OFF_RE = re.compile(r"\A\s*/ste-off(?:\s+.*)?\Z", re.I | re.S)


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _normalize_identifier(raw: Any) -> str:
    if not isinstance(raw, str):
        return ""
    text = raw.strip().lower()
    if not text:
        return ""
    if text.startswith(("/", "@")):
        text = text[1:].strip()
    for sep in (":", "/"):
        if sep in text:
            prefix, rest = text.split(sep, 1)
            if prefix in {STE_PLUGIN_ID, "ste_pro_max", "ste-promax"} and rest:
                return rest.strip()
    return text


def is_ste_skill_identifier(raw: Any) -> bool:
    norm = _normalize_identifier(raw)
    return norm in STE_SKILL_IDS


def is_ste_agent_identifier(raw: Any) -> bool:
    norm = _normalize_identifier(raw)
    return norm in STE_AGENT_IDS


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


def is_exact_ste_skill_md_path(raw: Any, workspace_root: Path | None = None) -> bool:
    """Return True only when `raw` points to an exact known STE `SKILL.md` file."""
    if not isinstance(raw, str) or not raw.strip() or "\x00" in raw:
        return False
    text = raw.strip()
    try:
        p = Path(text)
    except Exception:
        return False
    if p.name.lower() != "skill.md":
        return False

    candidates: list[Path] = []
    if p.is_absolute():
        candidates.append(p)
    else:
        if workspace_root is not None:
            candidates.append(workspace_root / p)
        candidates.append(BUNDLE_ROOT / p)

    for cand in candidates:
        try:
            abs_c, resolved = check_safe_lexical_path(cand, "SKILL.md candidate")
        except PolicyError:
            continue
        if not abs_c.is_file() or resolved.name.lower() != "skill.md":
            continue
        parts_lower = [part.lower() for part in resolved.parts]
        parent_name = resolved.parent.name.lower()
        grandparent_name = resolved.parent.parent.name.lower() if resolved.parent.parent else ""
        if parent_name in STE_SKILL_IDS and grandparent_name == "skills":
            return True
        if parent_name == "ste-promax" and (
            resolved.is_relative_to(BUNDLE_ROOT)
            or (workspace_root is not None and resolved.is_relative_to(workspace_root))
        ):
            if "skills" in parts_lower or resolved.parent == BUNDLE_ROOT / "ste-promax":
                return True
    return False


def is_explicit_user_ste_off(prompt: Any) -> bool:
    if not isinstance(prompt, str):
        return False
    return bool(_STE_OFF_RE.match(prompt))


def parse_tool_args(raw_args: Any) -> dict[str, Any]:
    if isinstance(raw_args, dict):
        return raw_args
    if isinstance(raw_args, str) and raw_args.strip():
        try:
            parsed = json.loads(raw_args)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
    return {}


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
        "schema": "ste-promax.copilot-session-scope.v1",
        "session_id": clean_id,
        "active": bool(record.get("active", False)),
        "reason": str(record.get("reason") or ""),
        "parent_session_id": record.get("parent_session_id"),
        "agent_id": record.get("agent_id"),
        "agent_type": record.get("agent_type"),
        "working_directory": record.get("working_directory"),
        "transcript_path": record.get("transcript_path"),
        "events_min_line": int(record.get("events_min_line", 0)),
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


def _copilot_home_candidates() -> list[Path]:
    homes: list[Path] = []
    env_home = os.environ.get("COPILOT_HOME", "").strip()
    if env_home:
        try:
            _, resolved = check_safe_lexical_path(env_home, "COPILOT_HOME")
            if resolved.is_dir():
                homes.append(resolved)
        except PolicyError:
            pass
    default_home = Path.home() / ".copilot"
    try:
        if default_home.is_dir() and not is_link_or_reparse(default_home.lstat()):
            resolved_def = default_home.resolve()
            if resolved_def not in homes:
                homes.append(resolved_def)
    except OSError:
        pass
    return homes


def find_session_events_file(
    session_id: str,
    *,
    transcript_path: str | None = None,
) -> Path | None:
    """Locate a session's `events.jsonl` without ever reading `~/.copilot/config.json`."""
    candidates: list[Path] = []
    if isinstance(transcript_path, str) and transcript_path.strip():
        try:
            _, res_tp = check_safe_lexical_path(transcript_path.strip(), "transcriptPath")
            if res_tp.is_file() and res_tp.name.endswith(".jsonl"):
                candidates.append(res_tp)
            elif res_tp.is_dir() and (res_tp / "events.jsonl").is_file():
                candidates.append(res_tp / "events.jsonl")
        except PolicyError:
            pass

    if isinstance(session_id, str) and session_id.strip() and ".." not in session_id and "/" not in session_id and "\\" not in session_id:
        sid = session_id.strip()
        for home in _copilot_home_candidates():
            candidates.extend([
                home / "session-state" / sid / "events.jsonl",
                home / "sessions" / sid / "events.jsonl",
                home / "session-state" / f"{sid}.jsonl",
            ])

    for cand in candidates:
        try:
            info = cand.lstat()
        except FileNotFoundError:
            continue
        if not is_link_or_reparse(info) and stat.S_ISREG(info.st_mode):
            return cand.resolve()
    return None


def scan_events_jsonl(
    events_file: Path | None,
    *,
    min_line_index: int = 0,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    """Scan `events.jsonl` chronologically for typed STE activation or explicit user `/ste-off`."""
    if events_file is None or not events_file.is_file():
        return {"found_transition": False, "active": None, "reason": None, "line_count": 0}
    try:
        raw_lines = events_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {"found_transition": False, "active": None, "reason": None, "line_count": 0}

    found_transition = False
    active_state: bool | None = None
    reason: str | None = None

    for idx, line in enumerate(raw_lines):
        if idx < min_line_index or not line.strip():
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        ev_type = ev.get("type")
        data = ev.get("data")
        if not isinstance(data, dict):
            continue

        if ev_type in {"skill.invoked", "skill.invoked_ref"}:
            s_name = data.get("name")
            p_name = data.get("pluginName")
            s_path = data.get("path")
            if (
                is_ste_skill_identifier(s_name)
                or (isinstance(p_name, str) and p_name.strip().lower() == STE_PLUGIN_ID)
                or is_exact_ste_skill_md_path(s_path, workspace_root)
            ):
                found_transition = True
                active_state = True
                reason = f"event:{ev_type}:{s_name or s_path}"

        elif ev_type in {"subagent.selected", "subagent.started"}:
            a_name = data.get("agentName")
            if is_ste_agent_identifier(a_name):
                found_transition = True
                active_state = True
                reason = f"event:{ev_type}:{a_name}"

        elif ev_type == "tool.execution_start":
            t_name = str(data.get("toolName") or "")
            t_args = parse_tool_args(data.get("arguments"))
            if t_name in {"skill", "Skill"}:
                skill_arg = t_args.get("skill") or t_args.get("name") or t_args.get("id")
                if is_ste_skill_identifier(skill_arg):
                    found_transition = True
                    active_state = True
                    reason = f"event:tool.skill:{skill_arg}"
            elif t_name in {"view", "read", "Read"}:
                path_arg = t_args.get("path") or t_args.get("file_path") or t_args.get("filePath")
                if is_exact_ste_skill_md_path(path_arg, workspace_root):
                    found_transition = True
                    active_state = True
                    reason = "event:tool.view:SKILL.md"
            else:
                is_ste_mcp, canonical_mcp = is_ste_mcp_tool_name(t_name)
                if is_ste_mcp:
                    found_transition = True
                    active_state = True
                    reason = f"event:tool.mcp:{canonical_mcp}"

        elif ev_type == "user.message":
            msg_source = data.get("source")
            if msg_source in {None, "user", "cli", "interactive", "prompt"}:
                if is_explicit_user_ste_off(data.get("content")):
                    found_transition = True
                    active_state = False
                    reason = "event:user:/ste-off"

    return {
        "found_transition": found_transition,
        "active": active_state,
        "reason": reason,
        "line_count": len(raw_lines),
    }


def activate_session_scope(
    session_id: str,
    reason: str,
    *,
    parent_session_id: str | None = None,
    agent_id: str | None = None,
    agent_type: str | None = None,
    working_directory: str | None = None,
    transcript_path: str | None = None,
) -> dict[str, Any]:
    existing = load_session_record(session_id) or {}
    merged = {
        **existing,
        "active": True,
        "reason": reason,
        "parent_session_id": parent_session_id or existing.get("parent_session_id"),
        "agent_id": agent_id or existing.get("agent_id"),
        "agent_type": agent_type or existing.get("agent_type"),
        "working_directory": working_directory or existing.get("working_directory"),
        "transcript_path": transcript_path or existing.get("transcript_path"),
    }
    saved = save_session_record(session_id, merged)
    if agent_id and agent_id.strip() and agent_id.strip() != session_id.strip():
        save_session_record(
            agent_id.strip(),
            {
                **merged,
                "parent_session_id": session_id.strip(),
            },
        )
    return saved


def deactivate_session_scope(
    session_id: str,
    reason: str = "user:/ste-off",
    *,
    working_directory: str | None = None,
    transcript_path: str | None = None,
) -> dict[str, Any]:
    existing = load_session_record(session_id) or {}
    events_file = find_session_events_file(
        session_id,
        transcript_path=transcript_path or existing.get("transcript_path"),
    )
    line_count = 0
    if events_file is not None and events_file.is_file():
        try:
            line_count = len(events_file.read_text(encoding="utf-8", errors="replace").splitlines())
        except OSError:
            line_count = 0
    merged = {
        **existing,
        "active": False,
        "reason": reason,
        "working_directory": working_directory or existing.get("working_directory"),
        "transcript_path": transcript_path or existing.get("transcript_path"),
        "events_min_line": line_count,
    }
    return save_session_record(session_id, merged)


def _is_ancestor_scoped(
    parent_id: str | None,
    *,
    workspace_root: Path | None = None,
    visited: set[str] | None = None,
) -> tuple[bool, str | None]:
    if not isinstance(parent_id, str) or not parent_id.strip():
        return False, None
    seen = visited if visited is not None else set()
    pid = parent_id.strip()
    if pid in seen or len(seen) >= 8:
        return False, None
    seen.add(pid)

    rec = load_session_record(pid)
    min_line = int(rec.get("events_min_line", 0)) if isinstance(rec, dict) else 0
    ev_file = find_session_events_file(
        pid,
        transcript_path=rec.get("transcript_path") if isinstance(rec, dict) else None,
    )
    ev_scan = scan_events_jsonl(ev_file, min_line_index=min_line, workspace_root=workspace_root)
    if ev_scan["found_transition"]:
        if ev_scan["active"] is True:
            return True, f"inherited_from:{pid}({ev_scan['reason']})"
        return False, None

    if isinstance(rec, dict) and rec.get("active") is True:
        return True, f"inherited_from:{pid}({rec.get('reason') or 'persisted'})"

    next_parent = rec.get("parent_session_id") if isinstance(rec, dict) else None
    if isinstance(next_parent, str) and next_parent.strip():
        return _is_ancestor_scoped(next_parent, workspace_root=workspace_root, visited=seen)
    return False, None


def resolve_session_scope(
    payload: dict[str, Any],
    *,
    hook_name: str = "",
) -> dict[str, Any]:
    """Determine whether the current Copilot CLI session or subagent is in STE scope."""
    session_id = str(payload.get("sessionId") or "").strip()
    agent_id = str(payload.get("agentId") or "").strip() or None
    parent_agent_id = str(payload.get("parentAgentId") or "").strip() or None
    agent_type = str(payload.get("agentType") or payload.get("agentName") or "").strip() or None
    raw_wd = str(payload.get("workingDirectory") or payload.get("cwd") or "").strip() or None
    transcript_path = str(payload.get("transcriptPath") or "").strip() or None

    server_name = str(payload.get("serverName") or "").strip()
    tool_name = str(payload.get("toolName") or "").strip()
    is_ste_mcp, _ = is_ste_mcp_tool_name(tool_name)
    is_ste_pre_mcp = hook_name == "preMcpToolCall" and (
        server_name == "ste-promax" or (not server_name and is_ste_mcp)
    )

    workspace_root: Path | None = None
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
        workspace_root = res_wd
    elif raw_wd:
        try:
            _, res_wd = check_safe_lexical_path(raw_wd, "hook workingDirectory")
            if res_wd.is_dir():
                workspace_root = res_wd
        except PolicyError:
            workspace_root = None

    if not session_id:
        if is_ste_pre_mcp:
            raise PolicyError(
                "preMcpToolCall requires a non-empty sessionId for STE workspace binding.",
                code="policy_refusal",
            )
        return {
            "session_id": "",
            "active": False,
            "reason": "missing_session_id",
            "workspace_root": str(workspace_root) if workspace_root else None,
        }

    if hook_name == "preMcpToolCall" and not is_ste_pre_mcp:
        return {
            "session_id": session_id,
            "active": False,
            "reason": "non-ste-mcp",
            "workspace_root": str(workspace_root) if workspace_root else None,
        }

    existing = load_session_record(session_id) or {}
    if raw_wd or parent_agent_id or agent_id or agent_type or transcript_path:
        save_session_record(
            session_id,
            {
                **existing,
                "parent_session_id": parent_agent_id or existing.get("parent_session_id"),
                "agent_id": agent_id or existing.get("agent_id"),
                "agent_type": agent_type or existing.get("agent_type"),
                "working_directory": str(workspace_root) if workspace_root else existing.get("working_directory"),
                "transcript_path": transcript_path or existing.get("transcript_path"),
            },
        )
        existing = load_session_record(session_id) or existing

    # 1. Explicit user /ste-off in userPromptSubmitted
    if hook_name == "userPromptSubmitted":
        prompt_text = payload.get("prompt")
        if is_explicit_user_ste_off(prompt_text):
            deactivated = deactivate_session_scope(
                session_id,
                "user:/ste-off",
                working_directory=str(workspace_root) if workspace_root else None,
                transcript_path=transcript_path,
            )
            return {
                "session_id": session_id,
                "active": False,
                "reason": deactivated["reason"],
                "workspace_root": str(workspace_root) if workspace_root else None,
                "explicit_ste_off": True,
            }

    # 2. Check events.jsonl for this session
    min_line = int(existing.get("events_min_line", 0))
    ev_file = find_session_events_file(
        session_id,
        transcript_path=transcript_path or existing.get("transcript_path"),
    )
    ev_scan = scan_events_jsonl(ev_file, min_line_index=min_line, workspace_root=workspace_root)
    if ev_scan["found_transition"]:
        if ev_scan["active"] is False:
            deactivated = deactivate_session_scope(
                session_id,
                str(ev_scan["reason"] or "event:user:/ste-off"),
                working_directory=str(workspace_root) if workspace_root else None,
                transcript_path=transcript_path,
            )
            return {
                "session_id": session_id,
                "active": False,
                "reason": deactivated["reason"],
                "workspace_root": str(workspace_root) if workspace_root else None,
            }
        if ev_scan["active"] is True:
            activated = activate_session_scope(
                session_id,
                str(ev_scan["reason"] or "event:skill.invoked"),
                parent_session_id=parent_agent_id,
                agent_id=agent_id,
                agent_type=agent_type,
                working_directory=str(workspace_root) if workspace_root else None,
                transcript_path=transcript_path,
            )
            return {
                "session_id": session_id,
                "active": True,
                "reason": activated["reason"],
                "workspace_root": str(workspace_root) if workspace_root else None,
            }

    # 3. Check live agentType / agentName (e.g., ste-author custom agent)
    if is_ste_agent_identifier(agent_type):
        activated = activate_session_scope(
            session_id,
            f"agent:{agent_type}",
            parent_session_id=parent_agent_id,
            agent_id=agent_id,
            agent_type=agent_type,
            working_directory=str(workspace_root) if workspace_root else None,
            transcript_path=transcript_path,
        )
        return {
            "session_id": session_id,
            "active": True,
            "reason": activated["reason"],
            "workspace_root": str(workspace_root) if workspace_root else None,
        }

    # 4. Check live preToolUse entry signals (skill tool, exact STE SKILL.md view, ste-promax MCP tool)
    if hook_name == "preToolUse":
        tool_name = str(payload.get("toolName") or "").strip()
        tool_args = parse_tool_args(payload.get("toolArgs"))
        if tool_name in {"skill", "Skill"}:
            skill_arg = tool_args.get("skill") or tool_args.get("name") or tool_args.get("id")
            if is_ste_skill_identifier(skill_arg):
                activated = activate_session_scope(
                    session_id,
                    f"tool.skill:{skill_arg}",
                    parent_session_id=parent_agent_id,
                    agent_id=agent_id,
                    agent_type=agent_type,
                    working_directory=str(workspace_root) if workspace_root else None,
                    transcript_path=transcript_path,
                )
                return {
                    "session_id": session_id,
                    "active": True,
                    "reason": activated["reason"],
                    "workspace_root": str(workspace_root) if workspace_root else None,
                }
        elif tool_name in {"view", "read", "Read"}:
            path_arg = tool_args.get("path") or tool_args.get("file_path") or tool_args.get("filePath")
            if is_exact_ste_skill_md_path(path_arg, workspace_root):
                activated = activate_session_scope(
                    session_id,
                    "tool.view:SKILL.md",
                    parent_session_id=parent_agent_id,
                    agent_id=agent_id,
                    agent_type=agent_type,
                    working_directory=str(workspace_root) if workspace_root else None,
                    transcript_path=transcript_path,
                )
                return {
                    "session_id": session_id,
                    "active": True,
                    "reason": activated["reason"],
                    "workspace_root": str(workspace_root) if workspace_root else None,
                }
        else:
            is_ste_mcp, canonical_mcp = is_ste_mcp_tool_name(tool_name)
            if is_ste_mcp:
                activated = activate_session_scope(
                    session_id,
                    f"tool.mcp:{canonical_mcp}",
                    parent_session_id=parent_agent_id,
                    agent_id=agent_id,
                    agent_type=agent_type,
                    working_directory=str(workspace_root) if workspace_root else None,
                    transcript_path=transcript_path,
                )
                return {
                    "session_id": session_id,
                    "active": True,
                    "reason": activated["reason"],
                    "workspace_root": str(workspace_root) if workspace_root else None,
                }

    if hook_name == "preMcpToolCall":
        server_name = str(payload.get("serverName") or "").strip()
        tool_name = str(payload.get("toolName") or "").strip()
        is_ste_mcp, canonical_mcp = is_ste_mcp_tool_name(tool_name)
        if server_name == "ste-promax" or is_ste_mcp:
            activated = activate_session_scope(
                session_id,
                f"preMcpToolCall:{canonical_mcp or tool_name}",
                parent_session_id=parent_agent_id,
                agent_id=agent_id,
                agent_type=agent_type,
                working_directory=str(workspace_root) if workspace_root else None,
                transcript_path=transcript_path,
            )
            return {
                "session_id": session_id,
                "active": True,
                "reason": activated["reason"],
                "workspace_root": str(workspace_root) if workspace_root else None,
            }

    # 5. Check persisted session record (handles resume, reload, and subsequent turns)
    if existing.get("active") is True:
        return {
            "session_id": session_id,
            "active": True,
            "reason": str(existing.get("reason") or "persisted"),
            "workspace_root": str(workspace_root) if workspace_root else existing.get("working_directory"),
        }

    # 6. Check parent/child inheritance via parentAgentId or persisted parent_session_id
    candidate_parent = parent_agent_id or existing.get("parent_session_id")
    if isinstance(candidate_parent, str) and candidate_parent.strip():
        parent_active, parent_reason = _is_ancestor_scoped(
            candidate_parent,
            workspace_root=workspace_root,
        )
        if parent_active:
            activated = activate_session_scope(
                session_id,
                parent_reason or f"inherited_from:{candidate_parent}",
                parent_session_id=candidate_parent,
                agent_id=agent_id,
                agent_type=agent_type,
                working_directory=str(workspace_root) if workspace_root else None,
                transcript_path=transcript_path,
            )
            return {
                "session_id": session_id,
                "active": True,
                "reason": activated["reason"],
                "workspace_root": str(workspace_root) if workspace_root else None,
            }

    return {
        "session_id": session_id,
        "active": False,
        "reason": str(existing.get("reason") or "non-ste-session"),
        "workspace_root": str(workspace_root) if workspace_root else existing.get("working_directory"),
    }

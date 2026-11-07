"""GitHub Copilot CLI command-hook dispatcher for STE-Pro-Max.

Handles:
- `sessionStart`
- `userPromptSubmitted`
- `preToolUse`
- `postToolUse`
- `postToolUseFailure`
- `subagentStart`
- `subagentStop`
- `agentStop`
- `sessionEnd`

Key safety properties:
1. Outer Copilot command-hook timeouts fail open (`timeoutSec: 120`), so this entry point
   arms a shorter internal watchdog timer (default 25s, configurable via
   `STE_COPILOT_WATCHDOG_SEC`) that prints a denial JSON payload and exits with code 2
   before the outer timeout can ever be reached.
2. Non-STE sessions pass through unchanged (`{}` and exit 0), leaving the host's own
   permission prompts and safety rules intact.
3. While STE-scoped, raw file mutations (`create`, `edit`, `apply_patch`, `write`),
   raw shells (`powershell`, `bash`, `local_shell`, `write_*`), dynamic extension/workflow
   management, and opaque GUI/external agents are refused cheaply without waiting for the
   SkillC backend (`{"permissionDecision": "deny", ...}` and exit 2).
4. Allowed read/discovery and guarded `ste-promax/*` MCP calls return `{}` (exit 0)
   without emitting `permissionDecision: "allow"`, preserving the host's permission flow.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import threading
import time
from typing import Any


def _ensure_bundle_sys_path() -> Path:
    bundle_root = Path(__file__).resolve().parents[2]
    root_str = str(bundle_root)
    cleaned_path: list[str] = [root_str]
    for entry in sys.path:
        if not entry:
            continue
        try:
            res_entry = Path(entry).resolve()
        except OSError:
            continue
        if res_entry == bundle_root:
            continue
        if (res_entry / "integrations" / "mcp" / "operations.py").is_file() and res_entry != bundle_root:
            continue
        cleaned_path.append(entry)
    sys.path[:] = cleaned_path
    return bundle_root


BUNDLE_ROOT = _ensure_bundle_sys_path()

from integrations.copilot.scope import (  # noqa: E402
    activate_session_scope,
    is_ste_agent_identifier,
    is_ste_mcp_tool_name,
    parse_tool_args,
    resolve_session_scope,
)
from integrations.mcp.operations import (  # noqa: E402
    validate_host_target_path,
)
from ste_promax import gate  # noqa: E402
from ste_promax.policy_runtime import PolicyError, check_safe_lexical_path  # noqa: E402

DEFAULT_WATCHDOG_SECONDS = 25.0

RAW_MUTATION_TOOLS: frozenset[str] = frozenset({
    "apply_patch",
    "patch",
    "create",
    "create_file",
    "edit",
    "edit_file",
    "write",
    "write_file",
    "insert",
    "delete",
    "delete_file",
    "remove_file",
    "move_file",
    "rename_file",
    "str_replace",
    "str_replace_editor",
    "str_replace_based_edit_tool",
    "multiedit",
    "notebookedit",
})

RAW_SHELL_AND_STREAM_TOOLS: frozenset[str] = frozenset({
    "powershell",
    "read_powershell",
    "write_powershell",
    "stop_powershell",
    "list_powershell",
    "bash",
    "read_bash",
    "write_bash",
    "stop_bash",
    "list_bash",
    "write_agent",
    "local_shell",
    "shell",
    "sh",
    "cmd",
    "pwsh",
    "terminal",
    "exec",
    "execute",
    "pty_spawn",
    "pty_write",
    "pty_read",
    "pty_list",
    "pty_kill",
})

OPAQUE_EXTENSION_AND_WORKFLOW_TOOLS: frozenset[str] = frozenset({
    "extensions_manage",
    "extensions_reload",
    "workflow",
    "workflows",
    "run_dynamic_workflow",
    "dynamic_workflows_manage",
    "mcp_manage",
    "plugin_manage",
    "catalog_select",
    "sql",
    "session_store_sql",
})

OPAQUE_AGENT_PREFIXES: tuple[str, ...] = (
    "computer-use/",
    "computer_use",
    "browser-use/",
    "browser_use",
    "cua-driver/",
    "cua_driver",
    "playwright/",
    "acp",
    "dsh",
)

BLOCKED_SUBAGENT_NAMES: frozenset[str] = frozenset({
    "acp",
    "dsh",
    "computer-use",
    "browser-use",
    "cua-driver",
    "configure-copilot",
})

SAFE_READ_AND_NAVIGATION_TOOLS: frozenset[str] = frozenset({
    "view",
    "read",
    "grep",
    "glob",
    "rg",
    "lsp",
    "skill",
    "web_fetch",
    "web_search",
    "webfetch",
    "websearch",
    "fetch_copilot_cli_documentation",
    "read_agent",
    "list_agents",
    "ask_user",
    "report_intent",
    "todo_write",
    "update_todo",
    "think",
    "catalog_search",
})

SAFE_READONLY_MCP_TOOLS: frozenset[str] = frozenset({
    "github-mcp-server/get_commit",
    "github-mcp-server/get_file_contents",
    "github-mcp-server/issue_read",
    "github-mcp-server/get_copilot_space",
    "github-mcp-server/list_copilot_spaces",
    "github-mcp-server/get_pull_request",
    "github-mcp-server/get_pull_request_comments",
    "github-mcp-server/get_pull_request_files",
    "github-mcp-server/get_pull_request_reviews",
    "github-mcp-server/get_pull_request_status",
    "github-mcp-server/get_tag",
    "github-mcp-server/list_branches",
    "github-mcp-server/list_commits",
    "github-mcp-server/list_issues",
    "github-mcp-server/list_pull_requests",
    "github-mcp-server/list_tags",
    "github-mcp-server/search_code",
    "github-mcp-server/search_issues",
    "github-mcp-server/search_repositories",
})


def _deny_response(reason: str) -> tuple[dict[str, Any], int]:
    return (
        {
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        },
        2,
    )


def _allow_passthrough(extra: dict[str, Any] | None = None) -> tuple[dict[str, Any], int]:
    # Never emit permissionDecision="allow" on normal allowed routes so the host's
    # own permission prompts and safety rules remain intact.
    return (dict(extra) if extra else {}, 0)


def _is_blocked_credential_read(tool_args: dict[str, Any]) -> str | None:
    raw_path = tool_args.get("path") or tool_args.get("file_path") or tool_args.get("filePath")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    norm = raw_path.replace("\\", "/").lower()
    parts = [p for p in norm.split("/") if p]
    name = parts[-1] if parts else ""
    if ".copilot" in parts and name == "config.json":
        return "Reading ~/.copilot/config.json is blocked by STE-Pro-Max policy."
    if any(seg in parts for seg in (".ssh", ".gnupg", ".aws", ".azure", ".kube")):
        return "Reading private credential directories is blocked by STE-Pro-Max policy."
    if name in {".env", "approval_reference.json", "approvals.sqlite3"} or name.startswith(".env."):
        return f"Reading protected secret/policy file {name!r} is blocked by STE-Pro-Max policy."
    return None


def _prevalidate_ste_mcp_call(
    canonical_tool: str,
    tool_args: dict[str, Any],
    workspace_root: Path | None,
) -> str | None:
    forbidden_present = sorted(set(tool_args.keys()) & gate.FORBIDDEN_INPUT_KEYS)
    if forbidden_present:
        return (
            f"STE-Pro-Max MCP tool {canonical_tool!r} rejected forbidden model arguments: "
            f"{', '.join(forbidden_present)}."
        )
    if "workspace_root" in tool_args:
        return f"STE-Pro-Max MCP tool {canonical_tool!r} does not accept workspace_root from model arguments."

    if workspace_root is not None:
        try:
            if canonical_tool == "ste_write_artifact" and "target_path" in tool_args:
                validate_host_target_path(
                    tool_args["target_path"],
                    workspace_root,
                    "target_path",
                    is_directory=False,
                    require_document_extension=True,
                )
            elif canonical_tool in {"ste_render_bundle", "ste_render_artifact", "ste_prepare_story_media", "ste_export_bundle"} and "output_dir" in tool_args:
                validate_host_target_path(
                    tool_args["output_dir"],
                    workspace_root,
                    "output_dir",
                    is_directory=True,
                    require_document_extension=False,
                )
            elif canonical_tool == "ste_regenerate_gallery" and "artifact_dir" in tool_args:
                validate_host_target_path(
                    tool_args["artifact_dir"],
                    workspace_root,
                    "artifact_dir",
                    is_directory=True,
                    require_document_extension=False,
                )
            elif canonical_tool == "ste_synthesize_wav" and "audio_path" in tool_args:
                validate_host_target_path(
                    tool_args["audio_path"],
                    workspace_root,
                    "audio_path",
                    is_directory=False,
                    require_document_extension=False,
                )
        except PolicyError as exc:
            return f"STE-Pro-Max policy refused {canonical_tool} target path ({exc.code}): {exc.message}"

    if canonical_tool != "ste_status":
        status = gate.get_policy_status()
        if not status.get("available", False):
            err = status.get("error") or {}
            msg = err.get("message") if isinstance(err, dict) else "SkillC policy backend is unavailable."
            return f"STE-Pro-Max policy backend unavailable ({err.get('code', 'dependency_missing')}): {msg}"

    return None


def _extract_tool_invocation(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    raw_name = str(payload.get("toolName") or "").strip()
    raw_args = payload.get("toolArgs")
    if not raw_name and isinstance(payload.get("toolCalls"), list) and payload["toolCalls"]:
        first = payload["toolCalls"][0]
        if isinstance(first, dict):
            raw_name = str(first.get("name") or first.get("toolName") or "").strip()
            raw_args = first.get("args") if "args" in first else first.get("toolArgs")
    return raw_name, parse_tool_args(raw_args)


def _handle_pre_tool_use(payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    raw_tool_name, tool_args = _extract_tool_invocation(payload)
    normalized_payload = (
        {**payload, "toolName": raw_tool_name, "toolArgs": tool_args}
        if raw_tool_name and not payload.get("toolName")
        else payload
    )
    scope = resolve_session_scope(normalized_payload, hook_name="preToolUse")
    if not scope.get("active", False):
        return _allow_passthrough()

    tool_lower = raw_tool_name.lower()

    ws_root: Path | None = None
    raw_ws = scope.get("workspace_root") or payload.get("workingDirectory") or payload.get("cwd")
    if isinstance(raw_ws, str) and raw_ws.strip():
        try:
            _, res_ws = check_safe_lexical_path(raw_ws.strip(), "workspace_root")
            if res_ws.is_dir():
                ws_root = res_ws
        except PolicyError:
            ws_root = None

    # 1. Cheaply refuse generic native file mutations without waiting for backend
    if tool_lower in RAW_MUTATION_TOOLS:
        return _deny_response(
            f"STE-Pro-Max policy refuses raw file mutation tool {raw_tool_name!r} while in STE scope. "
            "Use guarded ste-promax MCP tools (`ste_write_artifact`, `ste_render_bundle`, "
            "`ste_render_artifact`, `ste_regenerate_gallery`, `ste_export_bundle`)."
        )

    # 2. Cheaply refuse raw shells and interactive stream writes without waiting for backend
    if tool_lower in RAW_SHELL_AND_STREAM_TOOLS:
        return _deny_response(
            f"STE-Pro-Max policy refuses raw shell/stream tool {raw_tool_name!r} while in STE scope. "
            "Use guarded ste-promax MCP tools instead of shell commands."
        )

    # 3. Cheaply refuse dynamic extension/workflow/plugin management
    if tool_lower in OPAQUE_EXTENSION_AND_WORKFLOW_TOOLS:
        return _deny_response(
            f"STE-Pro-Max policy refuses dynamic extension/workflow tool {raw_tool_name!r} while in STE scope."
        )

    # 4. Cheaply refuse GUI / browser / external opaque agent tools
    if any(tool_lower.startswith(prefix) for prefix in OPAQUE_AGENT_PREFIXES):
        return _deny_response(
            f"STE-Pro-Max policy refuses opaque/GUI tool {raw_tool_name!r} while in STE scope. "
            "Use `ste_inspect_artifact` for bounded local inspection."
        )

    # 5. Guarded ste-promax MCP tools
    is_ste_mcp, canonical_mcp = is_ste_mcp_tool_name(raw_tool_name)
    if is_ste_mcp:
        refusal = _prevalidate_ste_mcp_call(canonical_mcp, tool_args, ws_root)
        if refusal is not None:
            return _deny_response(refusal)
        return _allow_passthrough()

    # 6. Subagent / task spawning check
    if tool_lower in {"task", "subagent", "delegate"}:
        target_agent = str(
            tool_args.get("agent")
            or tool_args.get("agent_type")
            or tool_args.get("agentName")
            or tool_args.get("subagent_type")
            or ""
        ).strip().lower()
        if target_agent in BLOCKED_SUBAGENT_NAMES or any(
            target_agent.startswith(p) for p in OPAQUE_AGENT_PREFIXES
        ):
            return _deny_response(
                f"STE-Pro-Max policy refuses spawning opaque subagent {target_agent!r} while in STE scope."
            )
        return _allow_passthrough()

    # 7. Safe read / discovery / navigation tools
    if tool_lower in SAFE_READ_AND_NAVIGATION_TOOLS or tool_lower in SAFE_READONLY_MCP_TOOLS:
        if tool_lower in {"view", "read"}:
            cred_err = _is_blocked_credential_read(tool_args)
            if cred_err is not None:
                return _deny_response(cred_err)
        return _allow_passthrough()

    # 8. Unknown or unclassified tool in STE scope -> fail closed
    return _deny_response(
        f"STE-Pro-Max policy refuses unguarded tool {raw_tool_name!r} while in STE scope."
    )


def _handle_subagent_start(payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    scope = resolve_session_scope(payload, hook_name="subagentStart")
    agent_name = str(payload.get("agentName") or "").strip()
    session_id = str(payload.get("sessionId") or "").strip()
    transcript_path = str(payload.get("transcriptPath") or "").strip() or None
    raw_wd = str(payload.get("workingDirectory") or payload.get("cwd") or "").strip() or None

    if is_ste_agent_identifier(agent_name) and session_id:
        activate_session_scope(
            session_id,
            f"subagentStart:{agent_name}",
            agent_type=agent_name,
            working_directory=raw_wd,
            transcript_path=transcript_path,
        )
        return _allow_passthrough(
            {
                "additionalContext": (
                    "STE-Pro-Max automatic local policy is active for this agent. "
                    "Use ste-promax MCP tools for all artifact rendering, writing, media preparation, "
                    "inspection, and export."
                )
            }
        )

    if scope.get("active", False):
        return _allow_passthrough(
            {
                "additionalContext": (
                    "Inherited STE-Pro-Max session scope from parent session. "
                    "Raw file mutations and shell tools are disabled; use ste-promax MCP tools."
                )
            }
        )

    return _allow_passthrough()


def _handle_user_prompt_submitted(payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    scope = resolve_session_scope(payload, hook_name="userPromptSubmitted")
    if scope.get("explicit_ste_off"):
        return _allow_passthrough(
            {
                "additionalContext": "STE-Pro-Max session scope has been ended by explicit user /ste-off command."
            }
        )
    return _allow_passthrough()


def _validate_pre_mcp_workspace_root(payload: dict[str, Any]) -> Path:
    raw_wd = payload.get("workingDirectory") or payload.get("cwd")
    if not isinstance(raw_wd, str) or not raw_wd.strip():
        raise PolicyError(
            "preMcpToolCall requires a non-empty host workingDirectory/cwd for STE workspace binding.",
            code="policy_refusal",
        )
    _, res_wd = check_safe_lexical_path(
        raw_wd.strip(),
        "preMcpToolCall workingDirectory",
        require_absolute=True,
        code="policy_refusal",
    )
    if not res_wd.is_dir():
        raise PolicyError(
            f"preMcpToolCall workingDirectory is not an existing local directory: {res_wd}",
            code="policy_refusal",
        )
    return res_wd


def _handle_pre_mcp_tool_call(payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    session_id = str(payload.get("sessionId") or "").strip()
    server_name = str(payload.get("serverName") or "").strip()
    tool_name = str(payload.get("toolName") or "").strip()
    is_ste_mcp, _ = is_ste_mcp_tool_name(tool_name)
    if server_name == "ste-promax" or (not server_name and is_ste_mcp):
        if not session_id:
            return _deny_response(
                "STE-Pro-Max preMcpToolCall requires a non-empty sessionId for STE MCP workspace binding."
            )
        try:
            ws_root = _validate_pre_mcp_workspace_root(payload)
            # A failed binding update must not authorize use of an old session workspace.
            scope = resolve_session_scope(payload, hook_name="preMcpToolCall")
        except PolicyError as exc:
            return _deny_response(
                f"STE-Pro-Max preMcpToolCall refused workspace binding ({exc.code}): {exc.message}"
            )
        if not isinstance(scope, dict) or scope.get("workspace_root") != str(ws_root):
            return _deny_response(
                "STE-Pro-Max preMcpToolCall failed to bind current host workingDirectory."
            )
        existing_meta = payload.get("_meta")
        meta_to_use = dict(existing_meta) if isinstance(existing_meta, dict) else {}
        meta_to_use["ste_session_id"] = session_id
        return ({"metaToUse": meta_to_use}, 0)
    return _allow_passthrough()


def dispatch_hook(hook_name: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Dispatch a single Copilot CLI hook event and return `(response_dict, exit_code)`."""
    test_delay_raw = os.environ.get("STE_COPILOT_TEST_DELAY_SEC", "").strip()
    if test_delay_raw:
        try:
            delay_s = float(test_delay_raw)
            if delay_s > 0:
                time.sleep(delay_s)
        except ValueError:
            pass

    if hook_name == "preToolUse":
        return _handle_pre_tool_use(payload)
    if hook_name == "preMcpToolCall":
        return _handle_pre_mcp_tool_call(payload)
    if hook_name == "userPromptSubmitted":
        return _handle_user_prompt_submitted(payload)
    if hook_name == "subagentStart":
        return _handle_subagent_start(payload)
    if hook_name in {"sessionStart", "postToolUse", "postToolUseFailure", "subagentStop", "agentStop", "sessionEnd"}:
        resolve_session_scope(payload, hook_name=hook_name)
        return _allow_passthrough()
    return _deny_response(f"Unsupported STE-Pro-Max hook event: {hook_name!r}")


def _resolve_watchdog_seconds() -> float:
    raw = os.environ.get("STE_COPILOT_WATCHDOG_SEC", "").strip()
    if raw:
        try:
            val = float(raw)
            if 0.05 <= val <= 115.0:
                return val
        except ValueError:
            pass
    return DEFAULT_WATCHDOG_SECONDS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ste-copilot-hook")
    parser.add_argument("--hook", required=True, help="Copilot hook event name.")
    args = parser.parse_args(argv)
    hook_name = str(args.hook).strip()

    watchdog_sec = _resolve_watchdog_seconds()

    def _on_watchdog_timeout() -> None:
        denial = {
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"STE-Pro-Max hook internal watchdog deadline ({watchdog_sec}s) exceeded "
                "before outer command-hook timeout; failing closed."
            ),
        }
        try:
            sys.stdout.write(json.dumps(denial, ensure_ascii=True) + "\n")
            sys.stdout.flush()
        except Exception:
            pass
        os._exit(2)

    timer = threading.Timer(watchdog_sec, _on_watchdog_timeout)
    timer.daemon = True
    timer.start()
    try:
        raw_stdin = sys.stdin.read()
        if not raw_stdin.strip():
            payload: dict[str, Any] = {}
        else:
            parsed = json.loads(raw_stdin)
            if not isinstance(parsed, dict):
                raise ValueError("Hook stdin payload must be a JSON object.")
            payload = parsed

        response, code = dispatch_hook(hook_name, payload)
        if response:
            sys.stdout.write(json.dumps(response, ensure_ascii=True) + "\n")
            sys.stdout.flush()
        return code
    except Exception as exc:
        if hook_name in {"preToolUse", "preMcpToolCall"}:
            denial = {
                "permissionDecision": "deny",
                "permissionDecisionReason": f"STE-Pro-Max {hook_name} hook failed closed: {type(exc).__name__}: {exc}",
            }
            sys.stdout.write(json.dumps(denial, ensure_ascii=True) + "\n")
            sys.stdout.flush()
            return 2
        return 0
    finally:
        timer.cancel()


if __name__ == "__main__":
    raise SystemExit(main())

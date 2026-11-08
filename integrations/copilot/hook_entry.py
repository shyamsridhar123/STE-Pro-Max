"""GitHub Copilot CLI command-hook dispatcher for STE-Pro-Max workspace plumbing.

Handles:
- `sessionStart`: best-effort records the initial session `working_directory`
  when available; never denies or restricts any session or tool.
- `preMcpToolCall`: first identifies whether the target MCP request is for
  `ste-promax`. Foreign or unidentifiable MCP requests exit 0 with no output
  before any state access, test delay, or watchdog timer (never emitting a
  blanket `allow` or `deny`). Only positively identified `ste-promax` MCP tool
  calls are subject to fail-closed workspace/session validation and the internal
  watchdog timer, injecting `metaToUse.ste_session_id` on success.
- Any other or unknown Copilot hook event: pure passthrough (`{}` and exit 0)
  with no state writes or permission decisions.
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
    is_ste_mcp_tool_name,
    resolve_session_workspace,
)
from ste_promax.policy_runtime import PolicyError, check_safe_lexical_path  # noqa: E402

DEFAULT_WATCHDOG_SECONDS = 25.0


def _deny_response(reason: str) -> tuple[dict[str, Any], int]:
    return (
        {
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        },
        2,
    )


def _allow_passthrough(extra: dict[str, Any] | None = None) -> tuple[dict[str, Any], int]:
    # Never emit permissionDecision="allow" so the host's own permission prompts
    # and safety rules remain intact.
    return (dict(extra) if extra else {}, 0)


def _is_ste_pre_mcp_request(hook_name: str, payload: Any) -> bool:
    """Return True only when `hook_name == 'preMcpToolCall'` and `payload` positively identifies `ste-promax`."""
    if hook_name != "preMcpToolCall" or not isinstance(payload, dict):
        return False
    server_name = str(payload.get("serverName") or "").strip()
    tool_name = str(payload.get("toolName") or "").strip()
    is_ste_mcp, _ = is_ste_mcp_tool_name(tool_name)
    return bool(server_name == "ste-promax" or (not server_name and is_ste_mcp))


def _maybe_apply_test_delay() -> None:
    test_delay_raw = os.environ.get("STE_COPILOT_TEST_DELAY_SEC", "").strip()
    if test_delay_raw:
        try:
            delay_s = float(test_delay_raw)
            if delay_s > 0:
                time.sleep(delay_s)
        except ValueError:
            pass


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


def _handle_ste_pre_mcp_tool_call(payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    _maybe_apply_test_delay()
    session_id = str(payload.get("sessionId") or "").strip()
    if not session_id:
        return _deny_response(
            "STE-Pro-Max preMcpToolCall requires a non-empty sessionId for STE MCP workspace binding."
        )
    try:
        ws_root = _validate_pre_mcp_workspace_root(payload)
        # A failed binding update must not authorize use of an old session workspace.
        bound = resolve_session_workspace(payload, hook_name="preMcpToolCall")
    except PolicyError as exc:
        return _deny_response(
            f"STE-Pro-Max preMcpToolCall refused workspace binding ({exc.code}): {exc.message}"
        )
    if not isinstance(bound, dict) or bound.get("workspace_root") != str(ws_root):
        return _deny_response(
            "STE-Pro-Max preMcpToolCall failed to bind current host workingDirectory."
        )
    existing_meta = payload.get("_meta")
    meta_to_use = dict(existing_meta) if isinstance(existing_meta, dict) else {}
    meta_to_use["ste_session_id"] = session_id
    return ({"metaToUse": meta_to_use}, 0)


def dispatch_hook(hook_name: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Dispatch a single Copilot CLI hook event and return `(response_dict, exit_code)`."""
    if hook_name == "preMcpToolCall":
        if not _is_ste_pre_mcp_request(hook_name, payload):
            return _allow_passthrough()
        return _handle_ste_pre_mcp_tool_call(payload)
    if hook_name == "sessionStart":
        if isinstance(payload, dict):
            resolve_session_workspace(payload, hook_name="sessionStart")
        return _allow_passthrough()
    return _allow_passthrough()


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

    try:
        raw_stdin = sys.stdin.read()
        if not raw_stdin.strip():
            payload: dict[str, Any] = {}
        else:
            parsed = json.loads(raw_stdin)
            if not isinstance(parsed, dict):
                return 0
            payload = parsed
    except Exception:
        # Malformed or unidentifiable hook payloads never receive metaToUse
        # and never emit a global MCP denial that could block unrelated tools.
        return 0

    if hook_name == "preMcpToolCall":
        if not _is_ste_pre_mcp_request(hook_name, payload):
            return 0

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
            response, code = _handle_ste_pre_mcp_tool_call(payload)
            if response:
                sys.stdout.write(json.dumps(response, ensure_ascii=True) + "\n")
                sys.stdout.flush()
            return code
        except Exception as exc:
            denial = {
                "permissionDecision": "deny",
                "permissionDecisionReason": f"STE-Pro-Max preMcpToolCall hook failed closed: {type(exc).__name__}: {exc}",
            }
            sys.stdout.write(json.dumps(denial, ensure_ascii=True) + "\n")
            sys.stdout.flush()
            return 2
        finally:
            timer.cancel()

    if hook_name == "sessionStart":
        try:
            resolve_session_workspace(payload, hook_name="sessionStart")
        except Exception:
            pass
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Bounded JSON stdin/stdout dispatcher for the OpenCode V2 STE-Pro-Max host adapter.

Consumes `integrations.mcp.operations.dispatch_host_operation` and its CLI contract
(`--workspace`/`--workspace-root`, `--action` or stdin `action`/`op`), resolving the
installed bundle root from `__file__` (never `runtime.json.ste_root`) and compatible
with Python `-I -B` isolated execution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any


def resolve_bundle_root() -> Path:
    """Resolve the installed STE-Pro-Max bundle root from `__file__` and isolate `sys.path`."""
    file_root = Path(__file__).resolve().parents[2]
    for env_key in ("STE_PROMAX_PLUGIN_ROOT", "OPENCODE_PLUGIN_ROOT", "COPILOT_PLUGIN_ROOT", "PLUGIN_ROOT"):
        raw = os.environ.get(env_key, "").strip()
        if not raw or "${" in raw:
            continue
        try:
            candidate = Path(raw).resolve(strict=True)
        except OSError:
            continue
        if (candidate / "ste_promax" / "__init__.py").is_file() and candidate == file_root:
            file_root = candidate
            break
    os.environ["STE_PROMAX_PLUGIN_ROOT"] = str(file_root)
    root_str = str(file_root)
    cleaned_path: list[str] = [root_str]
    for entry in sys.path:
        if not entry:
            continue
        try:
            res_entry = Path(entry).resolve()
        except OSError:
            continue
        if res_entry == file_root:
            continue
        if (res_entry / "integrations" / "mcp" / "operations.py").is_file() and res_entry != file_root:
            continue
        cleaned_path.append(entry)
    sys.path[:] = cleaned_path
    return file_root


BUNDLE_ROOT: Path = resolve_bundle_root()

from integrations.mcp import operations  # noqa: E402
from ste_promax import gate, writing  # noqa: E402
from ste_promax.policy_runtime import (  # noqa: E402
    ERROR_INVALID_INPUT,
    ERROR_POLICY_REFUSAL,
    PolicyError,
)

OPENCODE_PLUGIN_ID = "ste-promax"

STE_SKILL_IDS: frozenset[str] = frozenset({
    "ste-promax",
    "ste-visual-docs",
    "ste-storytelling",
    "ste-line-studio",
})

STE_TOOL_NAMES: frozenset[str] = operations.STE_MCP_TOOL_NAMES


def _reject_forbidden_model_args(op_name: str, args: dict[str, Any]) -> None:
    forbidden = sorted(set(args.keys()) & (gate.FORBIDDEN_INPUT_KEYS | {"workspace_root"}))
    if forbidden:
        raise PolicyError(
            f"STE-Pro-Max tool {op_name!r} rejected forbidden model arguments: {', '.join(forbidden)}.",
            code=ERROR_POLICY_REFUSAL,
        )


def _require_explicit_host_workspace(workspace_root: str | Path | None) -> Path:
    """Require an explicit workspace root from OpenCode host context; never infer from Python CWD or bundle root."""
    candidate = workspace_root
    if candidate is None or (isinstance(candidate, str) and not candidate.strip()):
        env_ws = os.environ.get("STE_TRUSTED_WORKSPACE", "").strip()
        if env_ws:
            candidate = env_ws
    if candidate is None or (isinstance(candidate, str) and not str(candidate).strip()):
        raise PolicyError(
            "Trusted host workspace_root is required for OpenCode dispatcher; "
            "refusing to infer workspace from Python process CWD or installed bundle.",
            code=ERROR_INVALID_INPUT,
        )
    return operations.resolve_trusted_workspace(candidate)


def _handle_preflight_turn(
    *,
    prompt_text: str | None = None,
    profile: str = "relaxed",
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    """Run turn preflight for an active STE session without blocking read-only prose help if runtime is missing."""
    try:
        ws = _require_explicit_host_workspace(workspace_root)
        status = gate.get_policy_status()
        prompt_str = prompt_text if isinstance(prompt_text, str) else ""
        prompt_sha = hashlib.sha256(prompt_str.encode("utf-8")).hexdigest()
        return {
            "ok": True,
            "result": {
                "schema": "ste-promax.opencode-turn-preflight.v1",
                "status": "preflight_ok" if status.get("available", False) else "degraded_readonly_only",
                "policy_available": bool(status.get("available", False)),
                "policy_mode": status.get("mode", "unavailable"),
                "policy_error": status.get("error"),
                "bundle_root": str(BUNDLE_ROOT),
                "workspace_root": str(ws),
                "profile": profile if profile in writing.LIMITS else "relaxed",
                "prompt_sha256": prompt_sha,
                "readonly_help_permitted": True,
                "effectful_tools_permitted": bool(status.get("available", False)),
            },
        }
    except Exception as exc:
        return operations._format_error_response(exc)


def _handle_postprocess_prose(
    *,
    text: str,
    profile: str = "relaxed",
    assistant_message_id: str | None = None,
    ordinal: int = 0,
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    """Postprocess streamed assistant text (`session.text.ended`) via real `ste.prose` / `writing.check_text`.

    Streamed text has already been displayed by `session.text.ended`; this records honest
    post-delivery diagnostics and never claims pre-display interception. If the SkillC
    runtime is missing, read-only prose turns degrade gracefully without failing the turn.
    """
    try:
        ws = _require_explicit_host_workspace(workspace_root)
        if not isinstance(text, str) or not text.strip():
            return {
                "ok": True,
                "result": {
                    "schema": "ste-promax.opencode-prose-postprocess.v1",
                    "status": "skipped_empty",
                    "delivery_timing": "post_stream_advisory",
                    "pre_display_guaranteed": False,
                },
            }
        status = gate.get_policy_status()
        if not status.get("available", False):
            report = writing.check_text(text, profile if profile in writing.LIMITS else "relaxed")
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            return {
                "ok": True,
                "result": {
                    "schema": "ste-promax.opencode-prose-postprocess.v1",
                    "status": "checked_without_skillc_backend",
                    "delivery_timing": "post_stream_advisory",
                    "pre_display_guaranteed": False,
                    "assistant_message_id": assistant_message_id,
                    "ordinal": ordinal,
                    "text_sha256": digest,
                    "profile": report.get("profile"),
                    "sentence_count": report.get("sentence_count", 0),
                    "finding_count": len(report.get("findings", [])),
                    "findings": list(report.get("findings", []))[:5],
                    "limitations": list(report.get("limitations", [])),
                    "policy_receipt": None,
                    "policy_error": status.get("error"),
                },
            }

        guarded = operations.dispatch_host_operation(
            "ste_check_prose",
            {
                "text": text,
                "profile": profile if profile in writing.LIMITS else "relaxed",
            },
            workspace_root=ws,
        )
        if not guarded.get("ok", False):
            return guarded
        res = guarded["result"]
        return {
            "ok": True,
            "result": {
                "schema": "ste-promax.opencode-prose-postprocess.v1",
                "status": "checked",
                "delivery_timing": "post_stream_advisory",
                "pre_display_guaranteed": False,
                "assistant_message_id": assistant_message_id,
                "ordinal": ordinal,
                "text_sha256": res.get("text_sha256"),
                "profile": res.get("profile"),
                "sentence_count": res.get("sentence_count", 0),
                "finding_count": len(res.get("findings", [])),
                "findings": list(res.get("findings", []))[:5],
                "limitations": list(res.get("limitations", [])),
                "policy_receipt": res.get("policy_receipt"),
            },
        }
    except Exception as exc:
        return operations._format_error_response(exc)


def dispatch_operation(
    request: dict[str, Any],
    *,
    cli_workspace_root: str | Path | None = None,
    cli_action: str | None = None,
) -> dict[str, Any]:
    """Dispatch a single bounded OpenCode host operation via `integrations.mcp.operations.dispatch_host_operation`."""
    try:
        if not isinstance(request, dict):
            raise PolicyError("Dispatcher request must be a JSON object.", code=ERROR_INVALID_INPUT)
        op = str(
            cli_action
            or request.get("action")
            or request.get("tool")
            or request.get("op")
            or ""
        ).strip()
        if not op:
            raise PolicyError("Dispatcher request is missing 'action' / 'op'.", code=ERROR_INVALID_INPUT)

        if "args" in request:
            raw_args = request["args"]
        elif "arguments" in request:
            raw_args = request["arguments"]
        elif "payload" in request:
            raw_args = request["payload"]
        elif "inputs" in request:
            raw_args = request["inputs"]
        else:
            raw_args = {
                k: v
                for k, v in request.items()
                if k not in {"action", "tool", "op", "workspace_root", "session_id"}
            }

        if raw_args is None:
            args: dict[str, Any] = {}
        elif isinstance(raw_args, dict):
            args = dict(raw_args)
        else:
            raise PolicyError("Dispatcher 'args' must be a JSON object.", code=ERROR_INVALID_INPUT)

        _reject_forbidden_model_args(op, args)

        raw_workspace_root = cli_workspace_root if cli_workspace_root is not None else request.get("workspace_root")
        ws = _require_explicit_host_workspace(raw_workspace_root)

        if op == "ste_preflight_turn":
            return _handle_preflight_turn(
                prompt_text=args.get("prompt_text"),
                profile=str(args.get("profile") or "relaxed"),
                workspace_root=ws,
            )

        if op == "ste_postprocess_prose":
            return _handle_postprocess_prose(
                text=str(args.get("text") or ""),
                profile=str(args.get("profile") or "relaxed"),
                assistant_message_id=args.get("assistant_message_id"),
                ordinal=int(args.get("ordinal") or 0),
                workspace_root=ws,
            )

        res = operations.dispatch_host_operation(
            op,
            args,
            workspace_root=ws,
        )
        if op in {"ste_status", "status", "ste.status"} and res.get("ok") and isinstance(res.get("result"), dict):
            res["result"]["bundle_root"] = str(BUNDLE_ROOT)
            res["result"]["host_adapter"] = OPENCODE_PLUGIN_ID
        return res
    except Exception as exc:
        return operations._format_error_response(exc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ste-opencode-dispatch")
    parser.add_argument(
        "--workspace",
        "--workspace-root",
        dest="workspace",
        default=None,
        help="Trusted host workspace root directory.",
    )
    parser.add_argument(
        "--action",
        default=None,
        help="Optional operation name when stdin carries the JSON request or args object.",
    )
    parsed_args = parser.parse_args(argv)

    try:
        raw_stdin = sys.stdin.read()
        if not raw_stdin.strip():
            payload: dict[str, Any] = {}
        else:
            try:
                loaded = json.loads(raw_stdin)
            except ValueError as exc:
                raise PolicyError(f"Malformed JSON request on stdin: {exc}", code=ERROR_INVALID_INPUT) from exc
            if not isinstance(loaded, dict):
                raise PolicyError("Dispatcher stdin must be a JSON object.", code=ERROR_INVALID_INPUT)
            payload = loaded
        response = dispatch_operation(
            payload,
            cli_workspace_root=parsed_args.workspace,
            cli_action=parsed_args.action,
        )
    except Exception as exc:
        response = operations._format_error_response(exc)

    serialized = json.dumps(response, ensure_ascii=True)
    if len(serialized) > operations._MAX_CLI_OUTPUT_CHARS:
        response = {
            "ok": False,
            "error": {
                "code": operations.ERROR_POSTCONDITION_FAILURE,
                "message": f"Operation output exceeded {operations._MAX_CLI_OUTPUT_CHARS}-character bound.",
            },
        }
        serialized = json.dumps(response, ensure_ascii=True)
    sys.stdout.write(serialized + "\n")
    sys.stdout.flush()
    return 0 if response.get("ok", False) else 2


if __name__ == "__main__":
    raise SystemExit(main())

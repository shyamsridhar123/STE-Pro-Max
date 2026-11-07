"""Closed-action local SkillC worker bridge for STE-Pro-Max automatic policy.

Reads one JSON request from stdin, executes the requested automatic policy action
in-process (`guard_pre`, `guard_post`, `guard_fail`, `guard_status`), and writes
one JSON response to stdout. No network, model, or shell calls.
"""
from __future__ import annotations

import json
import sys
from typing import Any

from ste_promax.gate import _dispatch_inprocess_action
from ste_promax.policy_runtime import (
    ERROR_DEPENDENCY_MISSING,
    ERROR_INVALID_INPUT,
    ERROR_POLICY_REFUSAL,
    ERROR_UNSUPPORTED_OPERATION,
    PolicyError,
)

CLOSED_ACTIONS = frozenset({
    "guard_pre",
    "guard_post",
    "guard_fail",
    "guard_status",
})


def _format_failure(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, PolicyError):
        return {"ok": False, "error": exc.to_error_dict()}
    if isinstance(exc, (ImportError, ModuleNotFoundError)):
        return {
            "ok": False,
            "error": {"code": ERROR_DEPENDENCY_MISSING, "message": str(exc)},
        }
    if isinstance(exc, ValueError):
        return {
            "ok": False,
            "error": {"code": ERROR_INVALID_INPUT, "message": str(exc)},
        }
    return {
        "ok": False,
        "error": {"code": ERROR_POLICY_REFUSAL, "message": str(exc)},
    }


def main() -> int:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            raise PolicyError("Worker stdin request is empty.", code=ERROR_INVALID_INPUT)
        try:
            request = json.loads(raw)
        except ValueError as exc:
            raise PolicyError(f"Worker request is not valid JSON: {exc}", code=ERROR_INVALID_INPUT) from exc
        if not isinstance(request, dict) or set(request.keys()) != {"action", "payload"}:
            raise PolicyError(
                "Worker request must be a JSON object with 'action' and 'payload'.",
                code=ERROR_INVALID_INPUT,
            )
        action = request.get("action")
        payload = request.get("payload")
        if not isinstance(action, str) or action not in CLOSED_ACTIONS:
            raise PolicyError(
                f"Unsupported worker action: {action!r}",
                code=ERROR_UNSUPPORTED_OPERATION,
            )
        if not isinstance(payload, dict):
            raise PolicyError("Worker payload must be a JSON object.", code=ERROR_INVALID_INPUT)
        result = _dispatch_inprocess_action(action, payload)
        sys.stdout.write(json.dumps({"ok": True, "result": result}, ensure_ascii=True) + "\n")
        sys.stdout.flush()
        return 0
    except Exception as exc:
        sys.stdout.write(json.dumps(_format_failure(exc), ensure_ascii=True) + "\n")
        sys.stdout.flush()
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

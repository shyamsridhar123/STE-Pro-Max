"""Focused tests for Copilot preMcpToolCall metadata boundary and workspace binding.

Verifies:
1. Actual `integrations/copilot/hook_entry.py` subprocess behavior for `preMcpToolCall` on:
   - malformed stdin JSON payload -> exit 2 with denial JSON and no `metaToUse`.
   - missing `cwd` / `workingDirectory` -> exit 2, no `metaToUse`, no fallback to stale session record.
   - invalid / relative / nonexistent / file / symlink-or-reparse `cwd` -> exit 2, no `metaToUse`,
     and no workspace authority from a pre-existing stale session record.
   - missing `sessionId` for STE MCP call -> exit 2, no `metaToUse`.
2. Forced record update failure (I/O error or exception during `resolve_session_scope` /
   `save_session_record`) via `main()` and subprocess -> exit 2 with denial JSON, no `metaToUse`,
   and no authorization of old session workspace.
3. Non-STE MCP server `preMcpToolCall` passes through unchanged (`{}` / empty stdout, exit 0).
4. Valid STE `preMcpToolCall` context preserves existing `_meta` fields, sets `ste_session_id`,
   and binds the exact current workspace directory (overwriting any older workspace record).
5. Normal post-hooks and resume semantics remain intact for non-`preMcpToolCall` hooks.
6. Uses owned temporary fake profiles under `C:\\Users\\shyamsridhar\\AppData\\Local\\Temp\\opencode`
   and never reads, copies, or hashes `~/.copilot/config.json`.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any
import unittest
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from integrations.copilot import (  # noqa: E402
    activate_session_scope,
    dispatch_hook,
    main as hook_main,
    resolve_session_scope,
)
from integrations.copilot.scope import load_session_record  # noqa: E402
from integrations.mcp.operations import resolve_trusted_workspace  # noqa: E402
from ste_promax.policy_runtime import PolicyError  # noqa: E402

HOOK_SCRIPT = REPO_ROOT / "integrations" / "copilot" / "hook_entry.py"
APPROVED_TEMP_BASE = Path(r"C:\Users\shyamsridhar\AppData\Local\Temp\opencode")


def _temp_parent() -> str | None:
    if APPROVED_TEMP_BASE.is_dir():
        return str(APPROVED_TEMP_BASE)
    return None


class CopilotPreMcpMetadataBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(
            prefix="ste-pre-mcp-boundary-",
            dir=_temp_parent(),
        )
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.stale_workspace = self.root / "stale-workspace"
        self.stale_workspace.mkdir(parents=True, exist_ok=True)
        self.current_workspace = self.root / "current-workspace"
        self.current_workspace.mkdir(parents=True, exist_ok=True)
        self.state_root = self.root / "policy-state"
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.copilot_home = self.root / "fake-copilot-home"
        self.copilot_home.mkdir(parents=True, exist_ok=True)

        self.env_overrides = {
            "STE_SKILLC_STATE_ROOT": str(self.state_root),
            "COPILOT_HOME": str(self.copilot_home),
            "STE_TRUSTED_WORKSPACE": "",
            "PYTHONPATH": str(REPO_ROOT),
        }
        self.env_patch = patch.dict(os.environ, self.env_overrides, clear=False)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def _run_hook_subprocess(
        self,
        hook_name: str,
        raw_stdin: str,
        *,
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env.update(self.env_overrides)
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [sys.executable, "-B", str(HOOK_SCRIPT), "--hook", hook_name],
            input=raw_stdin,
            capture_output=True,
            text=True,
            env=env,
            cwd=str(self.root),
            timeout=15,
            check=False,
        )

    def test_subprocess_malformed_payload_fails_closed_for_pre_mcp_tool_call(self) -> None:
        for bad_stdin in ("{not-valid-json", '["array-not-object"]', "42"):
            proc = self._run_hook_subprocess("preMcpToolCall", bad_stdin)
            self.assertEqual(proc.returncode, 2, f"Expected exit 2 for stdin={bad_stdin!r}")
            out = json.loads(proc.stdout.strip().splitlines()[-1])
            self.assertEqual(out.get("permissionDecision"), "deny")
            self.assertIn("preMcpToolCall hook failed closed", out.get("permissionDecisionReason", ""))
            self.assertNotIn("metaToUse", out)

    def test_subprocess_missing_or_invalid_cwd_refuses_and_does_not_authorize_stale_record(self) -> None:
        sid = "session-stale-guard-001"
        activate_session_scope(
            sid,
            "tool.skill:ste-promax",
            working_directory=str(self.stale_workspace),
        )
        initial_rec = load_session_record(sid)
        self.assertIsNotNone(initial_rec)
        assert initial_rec is not None
        initial_updated_at = initial_rec["updated_at"]

        regular_file = self.root / "not-a-dir.txt"
        regular_file.write_text("file\n", encoding="utf-8")
        missing_dir = self.root / "does-not-exist-dir"

        invalid_payloads: list[dict[str, Any]] = [
            {
                "sessionId": sid,
                "serverName": "ste-promax",
                "toolName": "ste_status",
                "_meta": {"progressToken": 1},
            },
            {
                "sessionId": sid,
                "cwd": "   ",
                "serverName": "ste-promax",
                "toolName": "ste_status",
            },
            {
                "sessionId": sid,
                "cwd": "relative/workspace/path",
                "serverName": "ste-promax",
                "toolName": "ste_status",
            },
            {
                "sessionId": sid,
                "cwd": str(missing_dir),
                "serverName": "ste-promax",
                "toolName": "ste_status",
            },
            {
                "sessionId": sid,
                "cwd": str(regular_file),
                "serverName": "ste-promax",
                "toolName": "ste_status",
            },
            {
                "sessionId": sid,
                "cwd": str(self.current_workspace) + "\\..\\current-workspace",
                "serverName": "ste-promax",
                "toolName": "ste_status",
            },
            {
                "sessionId": "",
                "cwd": str(self.current_workspace),
                "serverName": "ste-promax",
                "toolName": "ste_status",
            },
        ]

        # Also test directory junction / symlink when available on the host OS
        link_dir = self.root / "linked-workspace"
        created_link = False
        try:
            os.symlink(self.current_workspace, link_dir, target_is_directory=True)
            created_link = True
        except OSError:
            if os.name == "nt":
                mklink = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(link_dir), str(self.current_workspace)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                created_link = mklink.returncode == 0 and link_dir.exists()
        if created_link:
            invalid_payloads.append(
                {
                    "sessionId": sid,
                    "cwd": str(link_dir),
                    "serverName": "ste-promax",
                    "toolName": "ste_status",
                }
            )

        for bad_payload in invalid_payloads:
            proc = self._run_hook_subprocess("preMcpToolCall", json.dumps(bad_payload))
            self.assertEqual(proc.returncode, 2, f"Expected exit 2 for payload={bad_payload!r}")
            out = json.loads(proc.stdout.strip().splitlines()[-1])
            self.assertEqual(out.get("permissionDecision"), "deny")
            self.assertNotIn("metaToUse", out)
            # Stale record was not refreshed or re-bound by the rejected preMcpToolCall
            after_rec = load_session_record(sid)
            assert after_rec is not None
            self.assertEqual(after_rec["updated_at"], initial_updated_at)

            # Direct resolve_session_scope for preMcpToolCall also refuses rather than falling back
            with self.assertRaises(PolicyError):
                resolve_session_scope(bad_payload, hook_name="preMcpToolCall")

    def test_forced_record_update_failure_exits_2_without_meta_or_old_workspace_authority(self) -> None:
        sid = "session-io-failure-002"
        activate_session_scope(
            sid,
            "tool.skill:ste-promax",
            working_directory=str(self.stale_workspace),
        )
        payload = {
            "sessionId": sid,
            "cwd": str(self.current_workspace),
            "serverName": "ste-promax",
            "toolName": "ste_write_artifact",
            "_meta": {"progressToken": 99},
        }

        # 1. Inject I/O failure into save_session_record during hook_entry.main("preMcpToolCall")
        stdout_buf = io.StringIO()
        with (
            patch("integrations.copilot.scope.save_session_record", side_effect=OSError("disk full saving session")),
            patch.object(sys, "stdin", io.StringIO(json.dumps(payload))),
            patch.object(sys, "stdout", stdout_buf),
        ):
            rc = hook_main(["--hook", "preMcpToolCall"])

        self.assertEqual(rc, 2)
        out = json.loads(stdout_buf.getvalue().strip().splitlines()[-1])
        self.assertEqual(out.get("permissionDecision"), "deny")
        self.assertIn("OSError", out.get("permissionDecisionReason", ""))
        self.assertNotIn("metaToUse", out)

        # 2. Subprocess test where STE_SKILLC_STATE_ROOT points to a regular file so directory creation fails
        blocked_state_root = self.root / "state-root-is-a-file"
        blocked_state_root.write_text("not-a-directory\n", encoding="utf-8")
        proc = self._run_hook_subprocess(
            "preMcpToolCall",
            json.dumps(payload),
            extra_env={"STE_SKILLC_STATE_ROOT": str(blocked_state_root)},
        )
        self.assertEqual(proc.returncode, 2)
        sub_out = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertEqual(sub_out.get("permissionDecision"), "deny")
        self.assertNotIn("metaToUse", sub_out)

    def test_non_ste_server_passthrough_and_valid_ste_binding_overwrites_stale_workspace(self) -> None:
        sid = "session-valid-bind-003"
        activate_session_scope(
            sid,
            "tool.skill:ste-promax",
            working_directory=str(self.stale_workspace),
        )
        self.assertEqual(resolve_trusted_workspace(session_id=sid), self.stale_workspace.resolve())

        # 1. Non-STE MCP server passes through unchanged even without valid cwd
        non_ste_payload = {
            "sessionId": sid,
            "cwd": "",
            "serverName": "github-mcp-server",
            "toolName": "get_pull_request",
            "_meta": {"progressToken": 11},
        }
        for tool_name in ("get_pull_request", "ste_status"):
            with self.subTest(foreign_server_tool=tool_name):
                proc_non_ste = self._run_hook_subprocess(
                    "preMcpToolCall", json.dumps({**non_ste_payload, "toolName": tool_name})
                )
                self.assertEqual(proc_non_ste.returncode, 0)
                self.assertEqual(proc_non_ste.stdout.strip(), "")

        # 2. Valid STE preMcpToolCall preserves _meta, injects ste_session_id, and updates workspace to current_workspace
        ste_payload = {
            "sessionId": sid,
            "cwd": str(self.current_workspace),
            "serverName": "ste-promax",
            "toolName": "ste_status",
            "_meta": {"progressToken": 42, "clientTag": "copilot-cli"},
        }
        proc_ste = self._run_hook_subprocess("preMcpToolCall", json.dumps(ste_payload))
        self.assertEqual(proc_ste.returncode, 0, proc_ste.stderr)
        out_ste = json.loads(proc_ste.stdout.strip())
        self.assertEqual(
            out_ste,
            {
                "metaToUse": {
                    "progressToken": 42,
                    "clientTag": "copilot-cli",
                    "ste_session_id": sid,
                }
            },
        )
        self.assertEqual(resolve_trusted_workspace(session_id=sid), self.current_workspace.resolve())
        self.assertNotEqual(resolve_trusted_workspace(session_id=sid), self.stale_workspace.resolve())

        # 3. Normal postToolUse / session resume semantics preserve existing working_directory when cwd is omitted
        post_resp, post_code = dispatch_hook(
            "postToolUse",
            {
                "sessionId": sid,
                "toolName": "view",
            },
        )
        self.assertEqual(post_code, 0)
        self.assertEqual(post_resp, {})
        rec_after_post = load_session_record(sid)
        assert rec_after_post is not None
        self.assertEqual(Path(rec_after_post["working_directory"]).resolve(), self.current_workspace.resolve())


if __name__ == "__main__":
    unittest.main()

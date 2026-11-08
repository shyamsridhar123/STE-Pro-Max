"""Focused tests for Copilot preMcpToolCall metadata boundary and workspace binding.

Verifies:
1. Actual `integrations/copilot/hook_entry.py` subprocess behavior for `preMcpToolCall`:
   - malformed or unidentifiable stdin JSON payload -> exit 0 with empty stdout (never grants
     `metaToUse` or refreshes stale session records, and never emits a global MCP denial that
     could block unrelated MCP tools).
   - confirmed `ste-promax` `preMcpToolCall` with missing `cwd` / `workingDirectory` -> exit 2,
     no `metaToUse`, no fallback to stale session record.
   - confirmed `ste-promax` `preMcpToolCall` with invalid / relative / nonexistent / file /
     symlink-or-reparse `cwd` -> exit 2, no `metaToUse`, and no workspace authority from a
     pre-existing stale session record.
   - confirmed `ste-promax` `preMcpToolCall` with missing `sessionId` -> exit 2, no `metaToUse`.
2. Forced record update failure (I/O error or exception during `resolve_session_workspace` /
   `save_session_record`) on confirmed `ste-promax` `preMcpToolCall` via `main()` and subprocess ->
   exit 2 with denial JSON, no `metaToUse`, and no authorization of old session workspace.
3. Foreign MCP server `preMcpToolCall` exits 0 with no output BEFORE state access, test delay,
   or watchdog timer (even with `STE_COPILOT_WATCHDOG_SEC=0.2` and `STE_COPILOT_TEST_DELAY_SEC=3`
   or corrupt state root), while confirmed `ste-promax` `preMcpToolCall` still hits the watchdog
   with exit 2 and denial JSON.
4. Valid STE `preMcpToolCall` context preserves existing `_meta` fields, sets `ste_session_id`,
   and binds the exact current workspace directory (overwriting any older workspace record).
5. `sessionStart` binds best-effort when `cwd` is valid and preserves existing `working_directory`
   when `cwd` is omitted; all other or unknown hook names are pure passthrough (`{}` and exit 0)
   with no state writes or permission decisions.
6. Uses owned temporary fake profiles under `C:\\Users\\shyamsridhar\\AppData\\Local\\Temp\\opencode`
   and never reads, copies, or hashes `~/.copilot/config.json`.
"""
from __future__ import annotations

import datetime
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
    bind_session_workspace,
    dispatch_hook,
    load_session_record,
    main as hook_main,
    resolve_session_workspace,
)
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

    def test_subprocess_malformed_or_unidentifiable_payload_grants_no_authority_and_does_not_deny_foreign_mcp(self) -> None:
        sid = "session-malformed-no-auth-001"
        bind_session_workspace(sid, working_directory=str(self.stale_workspace))
        before_rec = load_session_record(sid)
        assert before_rec is not None
        before_updated = before_rec["updated_at"]

        for bad_stdin in ("{not-valid-json", '["array-not-object"]', "42", ""):
            proc = self._run_hook_subprocess(
                "preMcpToolCall",
                bad_stdin,
                extra_env={"STE_COPILOT_WATCHDOG_SEC": "0.2", "STE_COPILOT_TEST_DELAY_SEC": "3.0"},
            )
            self.assertEqual(proc.returncode, 0, f"Expected non-interfering exit 0 for stdin={bad_stdin!r}")
            self.assertEqual(proc.stdout.strip(), "", f"Expected no output (no metaToUse or blanket allow/deny) for stdin={bad_stdin!r}")
            after_rec = load_session_record(sid)
            assert after_rec is not None
            self.assertEqual(after_rec["updated_at"], before_updated)

    def test_subprocess_missing_or_invalid_cwd_refuses_and_does_not_authorize_stale_record(self) -> None:
        sid = "session-stale-guard-001"
        bind_session_workspace(
            sid,
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

            # Direct resolve_session_workspace for preMcpToolCall also refuses rather than falling back
            with self.assertRaises(PolicyError):
                resolve_session_workspace(bad_payload, hook_name="preMcpToolCall")

    def test_forced_record_update_failure_exits_2_without_meta_or_old_workspace_authority(self) -> None:
        sid = "session-io-failure-002"
        bind_session_workspace(
            sid,
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

        # 3. Unrelated MCP server and non-MCP hooks must NOT deny even when state root is corrupt/unwritable
        proc_unrelated_mcp = self._run_hook_subprocess(
            "preMcpToolCall",
            json.dumps({
                "sessionId": sid,
                "cwd": str(self.current_workspace),
                "serverName": "github-mcp-server",
                "toolName": "get_pull_request",
            }),
            extra_env={"STE_SKILLC_STATE_ROOT": str(blocked_state_root)},
        )
        self.assertEqual(proc_unrelated_mcp.returncode, 0)
        self.assertEqual(proc_unrelated_mcp.stdout.strip(), "")

        proc_session_start = self._run_hook_subprocess(
            "sessionStart",
            json.dumps({"sessionId": sid, "cwd": str(self.current_workspace)}),
            extra_env={"STE_SKILLC_STATE_ROOT": str(blocked_state_root)},
        )
        self.assertEqual(proc_session_start.returncode, 0)
        self.assertEqual(proc_session_start.stdout.strip(), "")

    def test_foreign_pre_mcp_skips_delay_and_watchdog_while_confirmed_ste_enforces_watchdog(self) -> None:
        delay_env = {
            "STE_COPILOT_WATCHDOG_SEC": "0.2",
            "STE_COPILOT_TEST_DELAY_SEC": "3.0",
        }
        # 1. Foreign MCP server exits 0 promptly with no output before test delay or watchdog
        start_foreign = datetime.datetime.now(datetime.timezone.utc)
        proc_foreign = self._run_hook_subprocess(
            "preMcpToolCall",
            json.dumps({
                "sessionId": "session-foreign-fast-001",
                "cwd": str(self.current_workspace),
                "serverName": "github-mcp-server",
                "toolName": "get_pull_request",
            }),
            extra_env=delay_env,
        )
        elapsed_foreign = (datetime.datetime.now(datetime.timezone.utc) - start_foreign).total_seconds()
        self.assertEqual(proc_foreign.returncode, 0)
        self.assertEqual(proc_foreign.stdout.strip(), "")
        self.assertLess(elapsed_foreign, 1.5)
        self.assertIsNone(load_session_record("session-foreign-fast-001"))

        # 2. Confirmed STE preMcpToolCall still enforces the internal watchdog (exit 2 + deny)
        start_ste = datetime.datetime.now(datetime.timezone.utc)
        proc_ste = self._run_hook_subprocess(
            "preMcpToolCall",
            json.dumps({
                "sessionId": "session-ste-watchdog-001",
                "cwd": str(self.current_workspace),
                "serverName": "ste-promax",
                "toolName": "ste_status",
            }),
            extra_env=delay_env,
        )
        elapsed_ste = (datetime.datetime.now(datetime.timezone.utc) - start_ste).total_seconds()
        self.assertEqual(proc_ste.returncode, 2)
        self.assertLess(elapsed_ste, 2.0)
        out_ste = json.loads(proc_ste.stdout.strip().splitlines()[-1])
        self.assertEqual(out_ste.get("permissionDecision"), "deny")
        self.assertIn("watchdog deadline", out_ste.get("permissionDecisionReason", ""))

    def test_non_ste_server_passthrough_and_valid_ste_binding_overwrites_stale_workspace(self) -> None:
        sid = "session-valid-bind-003"
        bind_session_workspace(
            sid,
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

        # 3. Other and unknown hook names are pure passthrough with no state writes or permission decisions
        untracked_sid = "session-untracked-other-hooks-004"
        for other_hook in ("postToolUse", "preToolUse", "userPromptSubmitted", "subagentStart", "unknownFutureHook"):
            other_resp, other_code = dispatch_hook(
                other_hook,
                {
                    "sessionId": untracked_sid,
                    "cwd": str(self.current_workspace),
                    "toolName": "view",
                },
            )
            self.assertEqual(other_code, 0)
            self.assertEqual(other_resp, {})
            self.assertIsNone(load_session_record(untracked_sid))

            proc_other = self._run_hook_subprocess(
                other_hook,
                json.dumps({"sessionId": untracked_sid, "cwd": str(self.current_workspace)}),
            )
            self.assertEqual(proc_other.returncode, 0)
            self.assertEqual(proc_other.stdout.strip(), "")
            self.assertIsNone(load_session_record(untracked_sid))

        # 4. sessionStart preserves existing working_directory when cwd is omitted
        start_resp, start_code = dispatch_hook(
            "sessionStart",
            {
                "sessionId": sid,
            },
        )
        self.assertEqual(start_code, 0)
        self.assertEqual(start_resp, {})
        rec_after_start = load_session_record(sid)
        assert rec_after_start is not None
        self.assertEqual(Path(rec_after_start["working_directory"]).resolve(), self.current_workspace.resolve())


if __name__ == "__main__":
    unittest.main()

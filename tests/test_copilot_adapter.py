"""Focused integration and release-gate tests for the GitHub Copilot CLI adapter and STE MCP server.

Covers:
1. Schema & manifest validation for root `mcp.json`, `com.github.copilot/hooks/hooks.json`,
   and `com.github.copilot/agents/ste-author.agent.md`.
2. Installed-bundle isolation (`resolve_bundle_root` loads from installed bundle copy, not
   the dev checkout in `runtime.json`).
3. Watchdog deadline enforcement (exits with code 2 and `permissionDecision: "deny"` before
   the outer command-hook timeout can fail open).
4. Session scope activation, non-STE passthrough, parent/child subagent inheritance,
   `events.jsonl` recovery across resume, exact `SKILL.md` view entry signal, no prompt
   keyword-matching, and explicit user `/ste-off` deactivation.
5. Guarded MCP operations (`ste_status`, `ste_check_prose`, `ste_write_artifact`,
   `ste_render_bundle`, `ste_render_artifact`, `ste_regenerate_gallery`,
   `ste_prepare_story_media`, `ste_inspect_artifact`, `ste_export_bundle`) over stdio MCP
   and direct host executors, including pre-write denial of out-of-root targets, protected
   paths, untrusted raw HTML, and missing SkillC backend before any sentinel write.
6. End-to-end real GitHub Copilot CLI (`copilot` / `copilot.exe`) execution against a local loopback
   stub OpenAI provider in an isolated `COPILOT_HOME` (never reading `~/.copilot/config.json`),
   retaining full stdout/stderr/events.jsonl/receipt/sentinel evidence under `artifacts/`.
   `CopilotAdapterUnitAndContractTests` always runs unconditionally in CI and local runs.
   `CopilotCliLoopbackReleaseGateTests` resolves the CLI from `STE_COPILOT_CLI_EXE` (or
   `COPILOT_CLI_EXE`), `PATH`, or the known Windows VS Code shim fallback, and runs only when
   `STE_RUN_HOST_CLI_TESTS=1` and the Copilot CLI executable is available.
"""
from __future__ import annotations

import datetime
import hashlib
import http.server
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
from typing import Any
import unittest
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from integrations.copilot import (  # noqa: E402
    STE_SKILL_IDS,
    activate_session_scope,
    dispatch_hook,
    is_exact_ste_skill_md_path,
    is_explicit_user_ste_off,
    resolve_session_scope,
)
from integrations.mcp import (  # noqa: E402
    MCP_SERVER_NAME,
    STE_MCP_TOOL_NAMES,
    host_check_prose,
    host_export_bundle,
    host_inspect_artifact,
    host_prepare_story_media,
    host_regenerate_gallery,
    host_render_artifact,
    host_render_bundle,
    host_status,
    host_write_artifact,
    resolve_mcp_python,
)

def _resolve_copilot_cli() -> Path | None:
    for env_key in ("STE_COPILOT_CLI_EXE", "COPILOT_CLI_EXE"):
        raw = os.environ.get(env_key, "").strip()
        if raw:
            candidate = Path(raw).expanduser()
            if candidate.is_file():
                return candidate
    for bin_name in ("copilot.exe", "copilot") if os.name == "nt" else ("copilot", "copilot.exe"):
        found = shutil.which(bin_name)
        if found:
            candidate = Path(found)
            if candidate.is_file():
                return candidate
    if os.name == "nt" or sys.platform == "win32":
        fallback = Path(r"C:\Program Files\Microsoft VS Code\bin\copilot-shim\copilot.exe")
        if fallback.is_file():
            return fallback
    return None


def _host_cli_tests_enabled() -> bool:
    return os.environ.get("STE_RUN_HOST_CLI_TESTS", "").strip() == "1"


COPILOT_EXE: Path | None = _resolve_copilot_cli()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _valid_pcm_wav_bytes() -> bytes:
    sample_rate = 8000
    samples = [0, 12000, -12000, 6000, -6000, 18000, -18000, 3000] * 125
    pcm_frames = struct.pack(f"<{len(samples)}h", *samples)
    fmt_chunk = struct.pack("<4sIHHIIHH", b"fmt ", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16)
    data_chunk = struct.pack("<4sI", b"data", len(pcm_frames)) + pcm_frames
    riff_size = 4 + len(fmt_chunk) + len(data_chunk)
    return struct.pack("<4sI4s", b"RIFF", riff_size, b"WAVE") + fmt_chunk + data_chunk


def _find_mcp_python() -> str:
    resolved = resolve_mcp_python()
    if resolved is not None:
        return str(resolved)
    return sys.executable


class CopilotAdapterUnitAndContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="ste-copilot-unit-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.workspace = self.root / "workspace"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.state_root = self.root / "policy-state"
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.copilot_home = self.root / "copilot-home"
        self.copilot_home.mkdir(parents=True, exist_ok=True)
        self.env_patch = patch.dict(
            os.environ,
            {
                "STE_SKILLC_STATE_ROOT": str(self.state_root),
                "COPILOT_HOME": str(self.copilot_home),
                "STE_TRUSTED_WORKSPACE": str(self.workspace),
            },
            clear=False,
        )
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def test_failed_workspace_binding_does_not_issue_mcp_metadata(self) -> None:
        payload = {"sessionId": "session-binding-failure", "cwd": str(self.workspace),
                   "serverName": "ste-promax", "toolName": "ste_status"}
        with patch("integrations.copilot.hook_entry.resolve_session_scope",
                   side_effect=RuntimeError("Binding record could not be updated")) as bind:
            with self.assertRaisesRegex(RuntimeError, "Binding record"):
                dispatch_hook("preMcpToolCall", payload)
            self.assertEqual(dispatch_hook("preMcpToolCall", {
                **payload, "serverName": "unrelated", "toolName": "unrelated_read"}), ({}, 0))
            self.assertEqual(bind.call_count, 1)

    def test_manifests_and_strict_agent_schema(self) -> None:
        plugin_json = json.loads((REPO_ROOT / "plugin.json").read_text(encoding="utf-8"))
        self.assertNotIn("hooks", plugin_json)
        self.assertNotIn("mcpServers", plugin_json)

        mcp_json = json.loads((REPO_ROOT / "mcp.json").read_text(encoding="utf-8"))
        self.assertEqual(mcp_json.get("$schema"), "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json")
        servers = mcp_json.get("mcpServers", {})
        self.assertIn(MCP_SERVER_NAME, servers)
        ste_srv = servers[MCP_SERVER_NAME]
        self.assertEqual(ste_srv.get("type"), "stdio")
        self.assertEqual(ste_srv.get("command"), "python")
        self.assertEqual(ste_srv.get("args")[:2], ["-I", "-B"])
        self.assertIn("${PLUGIN_ROOT}/integrations/mcp/server.py", ste_srv.get("args", []))
        self.assertEqual(ste_srv.get("env", {}).get("STE_PROMAX_PLUGIN_ROOT"), "${PLUGIN_ROOT}")
        self.assertEqual(ste_srv.get("env", {}).get("STE_PROMAX_PLUGIN_DATA"), "${PLUGIN_DATA}")

        hooks_path = REPO_ROOT / "com.github.copilot" / "hooks" / "hooks.json"
        self.assertTrue(hooks_path.is_file())
        hooks_json = json.loads(hooks_path.read_text(encoding="utf-8"))
        self.assertEqual(hooks_json.get("version"), 1)
        expected_hooks = {
            "sessionStart",
            "userPromptSubmitted",
            "preToolUse",
            "preMcpToolCall",
            "postToolUse",
            "postToolUseFailure",
            "subagentStart",
            "subagentStop",
            "agentStop",
            "sessionEnd",
        }
        self.assertEqual(set(hooks_json.get("hooks", {}).keys()), expected_hooks)
        for hook_name, entries in hooks_json["hooks"].items():
            self.assertEqual(len(entries), 1)
            entry = entries[0]
            self.assertEqual(entry.get("type"), "command")
            self.assertEqual(entry.get("timeoutSec"), 120)
            self.assertIn("python3 -I -B", entry.get("bash", ""))
            self.assertIn("python -I -B", entry.get("powershell", ""))
            self.assertIn(f"--hook {hook_name}", entry.get("bash", ""))
            self.assertIn(f"--hook {hook_name}", entry.get("powershell", ""))
            self.assertEqual(entry.get("env", {}).get("STE_PROMAX_PLUGIN_ROOT"), "${PLUGIN_ROOT}")

        agent_path = REPO_ROOT / "com.github.copilot" / "agents" / "ste-author.agent.md"
        self.assertTrue(agent_path.is_file())
        agent_text = agent_path.read_text(encoding="utf-8")
        self.assertTrue(agent_text.startswith("---\n"))
        frontmatter = agent_text.split("---\n", 2)[1]
        self.assertIn("strictToolsList: true", frontmatter)
        self.assertIn("strict-tools-list: true", frontmatter)
        for skill_id in STE_SKILL_IDS:
            self.assertIn(f"- {skill_id}", frontmatter)
        for tool_name in STE_MCP_TOOL_NAMES:
            self.assertIn(f"- ste-promax/{tool_name}", frontmatter)
        for forbidden_tool in ("powershell", "bash", "local_shell", "create", "edit", "apply_patch", "extensions_manage"):
            self.assertNotIn(f"- {forbidden_tool}", frontmatter)

    def test_non_ste_passthrough_and_no_prompt_keyword_matching(self) -> None:
        sid = "session-non-ste-001"
        # Mentioning STE in a user prompt must NEVER activate STE scope
        resp, code = dispatch_hook(
            "userPromptSubmitted",
            {
                "sessionId": sid,
                "cwd": str(self.workspace),
                "prompt": "Please explain STE-ProMAX and ste-visual-docs in plain text.",
            },
        )
        self.assertEqual(code, 0)
        self.assertEqual(resp, {})

        # preToolUse on powershell in a non-STE session passes through without blanket allow
        resp, code = dispatch_hook(
            "preToolUse",
            {
                "sessionId": sid,
                "cwd": str(self.workspace),
                "toolName": "powershell",
                "toolArgs": {"command": "Write-Output ok"},
            },
        )
        self.assertEqual(code, 0)
        self.assertEqual(resp, {})
        self.assertNotIn("permissionDecision", resp)

    def test_ste_scope_activation_denial_inheritance_resume_and_ste_off(self) -> None:
        parent_sid = "session-ste-parent-001"
        # Activate via skill tool (toolArgs.skill)
        resp, code = dispatch_hook(
            "preToolUse",
            {
                "sessionId": parent_sid,
                "cwd": str(self.workspace),
                "toolName": "skill",
                "toolArgs": {"skill": "ste-promax"},
            },
        )
        self.assertEqual(code, 0)
        self.assertEqual(resp, {})

        # Raw mutations and opaque tools (including sql, session_store_sql, and bluebird/*) are denied cheaply
        for blocked_tool in (
            "powershell",
            "bash",
            "write_powershell",
            "create",
            "edit",
            "apply_patch",
            "extensions_manage",
            "run_dynamic_workflow",
            "computer-use/click",
            "sql",
            "session_store_sql",
            "bluebird/mutate_index",
            "bluebird/code_read",
        ):
            resp, code = dispatch_hook(
                "preToolUse",
                {
                    "sessionId": parent_sid,
                    "cwd": str(self.workspace),
                    "toolName": blocked_tool,
                    "toolArgs": {},
                },
            )
            self.assertEqual(code, 2, f"Expected exit 2 for {blocked_tool}")
            self.assertEqual(resp.get("permissionDecision"), "deny")

        # Read/discovery tools remain allowed without overriding host permission flow
        resp, code = dispatch_hook(
            "preToolUse",
            {
                "sessionId": parent_sid,
                "cwd": str(self.workspace),
                "toolName": "view",
                "toolArgs": {"path": str(self.workspace / "README.md")},
            },
        )
        self.assertEqual(code, 0)
        self.assertEqual(resp, {})

        # Reading blocked ~/.copilot/config.json is denied even via view
        resp, code = dispatch_hook(
            "preToolUse",
            {
                "sessionId": parent_sid,
                "cwd": str(self.workspace),
                "toolName": "view",
                "toolArgs": {"path": r"C:\Users\someone\.copilot\config.json"},
            },
        )
        self.assertEqual(code, 2)
        self.assertEqual(resp.get("permissionDecision"), "deny")

        # Child subagent inherits STE scope via parentAgentId (child sessionId == agentId)
        child_sid = "subagent-child-001"
        resp, code = dispatch_hook(
            "preToolUse",
            {
                "sessionId": child_sid,
                "agentId": child_sid,
                "parentAgentId": parent_sid,
                "cwd": str(self.workspace),
                "toolName": "edit",
                "toolArgs": {"path": str(self.workspace / "file.txt")},
            },
        )
        self.assertEqual(code, 2)
        self.assertEqual(resp.get("permissionDecision"), "deny")

        # Subsequent child tool call without parentAgentId still remembers persisted inheritance
        resp, code = dispatch_hook(
            "preToolUse",
            {
                "sessionId": child_sid,
                "cwd": str(self.workspace),
                "toolName": "powershell",
                "toolArgs": {"command": "dir"},
            },
        )
        self.assertEqual(code, 2)
        self.assertEqual(resp.get("permissionDecision"), "deny")

        # Explicit user /ste-off ends STE scope
        self.assertTrue(is_explicit_user_ste_off("/ste-off"))
        self.assertTrue(is_explicit_user_ste_off("  /ste-off now "))
        self.assertFalse(is_explicit_user_ste_off("Please run /ste-off"))
        resp, code = dispatch_hook(
            "userPromptSubmitted",
            {
                "sessionId": parent_sid,
                "cwd": str(self.workspace),
                "prompt": "/ste-off",
            },
        )
        self.assertEqual(code, 0)
        self.assertIn("additionalContext", resp)

        # After /ste-off, powershell passes through again
        resp, code = dispatch_hook(
            "preToolUse",
            {
                "sessionId": parent_sid,
                "cwd": str(self.workspace),
                "toolName": "powershell",
                "toolArgs": {"command": "Write-Output ok"},
            },
        )
        self.assertEqual(code, 0)
        self.assertEqual(resp, {})

    def test_events_jsonl_recovery_and_exact_skill_md_view_signal(self) -> None:
        sid = "session-events-recovery-002"
        session_dir = self.copilot_home / "session-state" / sid
        session_dir.mkdir(parents=True, exist_ok=True)
        events_file = session_dir / "events.jsonl"
        events_file.write_text(
            json.dumps({
                "id": "11111111-1111-4111-8111-111111111111",
                "timestamp": "2026-11-06T20:00:00Z",
                "parentId": None,
                "type": "skill.invoked_ref",
                "data": {
                    "name": "ste-visual-docs",
                    "path": str(REPO_ROOT / "skills" / "ste-visual-docs" / "SKILL.md"),
                    "contentId": "sha256:" + "a" * 64,
                    "contentLength": 120,
                },
            })
            + "\n",
            encoding="utf-8",
        )
        scope = resolve_session_scope({"sessionId": sid, "cwd": str(self.workspace)}, hook_name="preToolUse")
        self.assertTrue(scope["active"])
        self.assertIn("skill.invoked_ref", scope["reason"])

        # Exact installed STE SKILL.md view path is recognized, arbitrary markdown is not
        self.assertTrue(
            is_exact_ste_skill_md_path(str(REPO_ROOT / "skills" / "ste-line-studio" / "SKILL.md"), self.workspace)
        )
        other_md = self.workspace / "STE-notes.md"
        other_md.write_text("# STE notes\n", encoding="utf-8")
        self.assertFalse(is_exact_ste_skill_md_path(str(other_md), self.workspace))

    def test_watchdog_deadline_exits_2_before_outer_timeout(self) -> None:
        env = dict(os.environ)
        env["STE_COPILOT_WATCHDOG_SEC"] = "0.2"
        env["STE_COPILOT_TEST_DELAY_SEC"] = "3.0"
        payload = json.dumps({
            "sessionId": "watchdog-session",
            "cwd": str(self.workspace),
            "toolName": "view",
            "toolArgs": {"path": "README.md"},
        })
        start = datetime.datetime.now(datetime.timezone.utc)
        proc = subprocess.run(
            [sys.executable, "-B", str(REPO_ROOT / "integrations" / "copilot" / "hook_entry.py"), "--hook", "preToolUse"],
            input=payload,
            capture_output=True,
            text=True,
            env=env,
            timeout=5,
            check=False,
        )
        elapsed = (datetime.datetime.now(datetime.timezone.utc) - start).total_seconds()
        self.assertEqual(proc.returncode, 2)
        self.assertLess(elapsed, 2.0)
        out_json = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertEqual(out_json.get("permissionDecision"), "deny")
        self.assertIn("watchdog deadline", out_json.get("permissionDecisionReason", ""))

    def test_installed_bundle_root_isolation_and_guarded_operations(self) -> None:
        # Copy bundle to an isolated directory to verify installed-bundle execution
        installed_bundle = self.root / "installed-plugin-bundle"
        installed_bundle.mkdir(parents=True, exist_ok=True)
        for rel_dir in ("ste_promax", "integrations", "com.github.copilot"):
            shutil.copytree(REPO_ROOT / rel_dir, installed_bundle / rel_dir)
        for rel_file in ("plugin.json", "mcp.json"):
            shutil.copy2(REPO_ROOT / rel_file, installed_bundle / rel_file)

        probe = subprocess.run(
            [
                sys.executable,
                "-B",
                "-c",
                (
                    "import json, sys; "
                    f"sys.path.insert(0, {str(installed_bundle)!r}); "
                    "from integrations.mcp.operations import resolve_bundle_root; "
                    "import ste_promax; "
                    "print(json.dumps({'bundle_root': str(resolve_bundle_root()), 'ste_file': ste_promax.__file__}))"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        info = json.loads(probe.stdout.strip())
        self.assertEqual(Path(info["bundle_root"]).resolve(), installed_bundle.resolve())
        self.assertTrue(Path(info["ste_file"]).resolve().is_relative_to(installed_bundle.resolve()))

        # 1. Status & prose check
        st = host_status(workspace_root=self.workspace)
        self.assertTrue(st["ok"], st)
        self.assertTrue(st["result"]["available"])

        prose_res = host_check_prose(
            text="Keep every sentence clear and below twenty words. Verify all output hashes.",
            profile="relaxed",
            workspace_root=self.workspace,
        )
        self.assertTrue(prose_res["ok"], prose_res)
        self.assertEqual(prose_res["result"]["policy_receipt"]["verdict"], "ALLOW")

        # 2. Guarded host write (including legitimate interactive HTML/SVG with <script>)
        interactive_html = (
            "<!doctype html><html><head><meta charset='utf-8'><title>Interactive SVG</title></head>"
            "<body><h1>Retry Mechanism</h1><svg viewBox='0 0 100 50'><rect width='90' height='40'/></svg>"
            "<script>document.documentElement.dataset.ready = '1';</script></body></html>\n"
        )
        write_res = host_write_artifact(
            target_path="artifacts/custom/interactive.html",
            content=interactive_html,
            source_kind="host_content",
            workspace_root=self.workspace,
        )
        self.assertTrue(write_res["ok"], write_res)
        written_path = Path(write_res["result"]["target_path"])
        self.assertTrue(written_path.is_file())
        self.assertEqual(_sha256_file(written_path), write_res["result"]["sha256"])
        self.assertEqual(write_res["result"]["js_verification"], "structural-and-integrity-only")

        # Imported raw_html without trusted_html=True is refused before write
        untrusted_sentinel = self.workspace / "artifacts" / "custom" / "untrusted-raw.html"
        raw_res = host_write_artifact(
            target_path="artifacts/custom/untrusted-raw.html",
            content="<!doctype html><html><body>Raw import</body></html>\n",
            source_kind="raw_html",
            trusted_html=False,
            workspace_root=self.workspace,
        )
        self.assertFalse(raw_res["ok"])
        self.assertEqual(raw_res["error"]["code"], "policy_refusal")
        self.assertFalse(untrusted_sentinel.exists())

        # Out-of-root target is refused before sentinel write, and stale ALLOW receipt is cleared
        outside_sentinel = self.root / "outside-sentinel.md"
        out_res = host_write_artifact(
            target_path=str(outside_sentinel),
            content="# Should never be written\n",
            workspace_root=self.workspace,
        )
        self.assertFalse(out_res["ok"])
        self.assertEqual(out_res["error"]["code"], "policy_refusal")
        self.assertNotIn("receipt", out_res["error"])
        self.assertFalse(outside_sentinel.exists())
        from ste_promax import gate as ste_gate
        self.assertIsNone(ste_gate.get_last_receipt())

        # Protected workspace directory is refused before sentinel write
        protected_sentinel = self.workspace / "ste_promax" / "evil.md"
        prot_res = host_write_artifact(
            target_path="ste_promax/evil.md",
            content="# Blocked\n",
            workspace_root=self.workspace,
        )
        self.assertFalse(prot_res["ok"])
        self.assertEqual(prot_res["error"]["code"], "policy_refusal")
        self.assertFalse(protected_sentinel.exists())

        # 3. Native render_bundle with bound evidence, inspect_artifact, export_bundle, and tamper refusal
        source_md = self.workspace / "docs" / "note.md"
        source_md.parent.mkdir(parents=True, exist_ok=True)
        source_md.write_text("# Retry Queue Note\n\nBound retry queues to prevent cascading overload.\n", encoding="utf-8")
        ev_bound = self.workspace / "docs" / "evidence-metric.txt"
        ev_bound.write_text("Queue latency p99 = 42ms.\n", encoding="utf-8")

        bundle_dir = self.workspace / "artifacts" / "bundle-01"
        bundle_res = host_render_bundle(
            input_path=str(source_md),
            output_dir=str(bundle_dir),
            evidence=[str(ev_bound)],
            workspace_root=self.workspace,
        )
        self.assertTrue(bundle_res["ok"], bundle_res)
        self.assertEqual(bundle_res["result"]["status"], "complete")
        self.assertEqual(bundle_res["result"]["policy_receipt"]["verdict"], "ALLOW")
        self.assertTrue((bundle_dir / "manifest.json").is_file())
        self.assertTrue((bundle_dir / "gallery.html").is_file())
        self.assertEqual(len(bundle_res["result"].get("evidence_files", [])), 1)

        inspect_res = host_inspect_artifact(
            target_path=str(bundle_dir),
            headless_browser=False,
            workspace_root=self.workspace,
        )
        self.assertTrue(inspect_res["ok"], inspect_res)
        self.assertFalse(inspect_res["result"]["in_app_preview"])
        self.assertEqual(inspect_res["result"]["inspection_mode"], "static-local-analysis")

        export_dir = self.workspace / "artifacts" / "exported-01"
        export_res = host_export_bundle(
            input_dir=str(bundle_dir),
            output_dir=str(export_dir),
            workspace_root=self.workspace,
        )
        self.assertTrue(export_res["ok"], export_res)
        self.assertEqual(export_res["result"]["status"], "exported")
        self.assertTrue((export_dir / "manifest.json").is_file())

        # Mutating bound evidence after render causes host_export_bundle to refuse export
        ev_orig_bytes = ev_bound.read_bytes()
        ev_bound.write_text("TAMPERED METRIC\n", encoding="utf-8")
        try:
            tampered_export = host_export_bundle(
                input_dir=str(bundle_dir),
                output_dir=str(self.workspace / "artifacts" / "exported-tampered"),
                workspace_root=self.workspace,
            )
            self.assertFalse(tampered_export["ok"])
            self.assertFalse((self.workspace / "artifacts" / "exported-tampered").exists())
        finally:
            ev_bound.write_bytes(ev_orig_bytes)

        triple_dir = self.workspace / "artifacts" / "triple-01"
        triple_res = host_render_artifact(
            output_dir=str(triple_dir),
            input_path=str(source_md),
            workspace_root=self.workspace,
        )
        self.assertTrue(triple_res["ok"], triple_res)
        self.assertTrue(Path(triple_res["result"]["html_path"]).is_file())

        gal_res = host_regenerate_gallery(
            artifact_dir=str(triple_dir),
            workspace_root=self.workspace,
        )
        self.assertTrue(gal_res["ok"], gal_res)
        self.assertTrue(Path(gal_res["result"]["gallery_path"]).is_file())

        # 4. Story media preparation with local PCM WAV
        ev_file = self.workspace / "docs" / "incident.txt"
        ev_file.write_text("Queue depth reached 5000 requests at 02:14 UTC.\n", encoding="utf-8")
        story_data = {
            "kind": "story",
            "version": 1,
            "title": "Queue Overload Brief",
            "audience": "Operations engineers reviewing ingress stability",
            "question": "What caused the ingress queue saturation at 02:14 UTC?",
            "purpose": "incident-review",
            "summary": "Evidence-linked review of queue overload.",
            "context": "Internal incident review based on recorded telemetry.",
            "sources": [
                {
                    "id": "src-1",
                    "title": "Incident Log",
                    "locator": "incident.txt",
                    "note": "Direct queue depth log from primary ingress.",
                }
            ],
            "claims": [
                {
                    "id": "claim-1",
                    "type": "observation",
                    "text": "Queue depth reached 5000 requests at 02:14 UTC.",
                    "source_ids": ["src-1"],
                    "attributed_to": "Incident Log",
                    "basis": "Direct telemetry observation",
                    "scope": "Primary ingress",
                    "uncertainty": "None",
                }
            ],
            "beats": [
                {
                    "id": "beat-1",
                    "title": "Ingress Saturation",
                    "role": "Observed queue spike",
                    "text": "Ingress queue depth spiked to 5000 requests.",
                    "claim_ids": ["claim-1"],
                    "narration": "Ingress queue depth spiked to five thousand requests.",
                }
            ],
        }
        story_file = self.workspace / "docs" / "story.json"
        story_file.write_text(json.dumps(story_data, indent=2) + "\n", encoding="utf-8")
        audio_dir = self.workspace / "docs" / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        (audio_dir / "beat-1.wav").write_bytes(_valid_pcm_wav_bytes())

        media_out = self.workspace / "artifacts" / "media-01"
        media_res = host_prepare_story_media(
            input_path=str(story_file),
            output_dir=str(media_out),
            audio_dir=str(audio_dir),
            workspace_root=self.workspace,
        )
        self.assertTrue(media_res["ok"], media_res)
        self.assertEqual(media_res["result"]["status"], "prepared_not_rendered")
        self.assertTrue((media_out / "video" / "index.html").is_file())

        # 5. Missing backend fails closed BEFORE any sentinel file is created
        missing_sentinel = self.workspace / "artifacts" / "missing-backend-sentinel.md"
        with patch.dict(
            os.environ,
            {
                "STE_SKILLC_RUNTIME_CONFIG": str(self.root / "nonexistent-runtime.json"),
                "STE_SKILLC_FORCE_WORKER": "1",
            },
            clear=False,
        ):
            missing_res = host_write_artifact(
                target_path="artifacts/missing-backend-sentinel.md",
                content="# Should fail closed\n",
                workspace_root=self.workspace,
            )
            self.assertFalse(missing_res["ok"])
            self.assertEqual(missing_res["error"]["code"], "dependency_missing")
            self.assertFalse(missing_sentinel.exists())

    def test_mcp_stdio_server_protocol_and_reexec(self) -> None:
        mcp_py = _find_mcp_python()
        # Plant a workspace shadow mcp.py to prove -I -B + sys.path isolation prevents importing it
        shadow_mcp = self.workspace / "mcp.py"
        shadow_mcp.write_text("raise RuntimeError('WORKSPACE_SHADOW_MCP_IMPORTED')\n", encoding="utf-8")
        script = (
            "import asyncio, json, os, sys\n"
            "from mcp import ClientSession, StdioServerParameters\n"
            "from mcp.client.stdio import stdio_client\n"
            "async def run():\n"
            "    params = StdioServerParameters(\n"
            "        command=sys.executable,\n"
            f"        args=['-I', '-B', {str(REPO_ROOT / 'integrations' / 'mcp' / 'server.py')!r}],\n"
            "        env=dict(os.environ),\n"
            f"        cwd={str(self.workspace)!r},\n"
            "    )\n"
            "    async with stdio_client(params) as (read_stream, write_stream):\n"
            "        async with ClientSession(read_stream, write_stream) as session:\n"
            "            init_res = await session.initialize()\n"
            "            tools_res = await session.list_tools()\n"
            "            tool_names = sorted(t.name for t in tools_res.tools)\n"
            "            tool_schemas = {t.name: t.inputSchema for t in tools_res.tools}\n"
            "            status_call = await session.call_tool('ste_status', {})\n"
            "            write_call = await session.call_tool('ste_write_artifact', {\n"
            "                'target_path': 'artifacts/mcp-stdio/hello.md',\n"
            "                'content': '# MCP Stdio Write\\n\\nVerified over stdio.\\n',\n"
            "            })\n"
            "            deny_call = await session.call_tool('ste_write_artifact', {\n"
            "                'target_path': '../outside-stdio-sentinel.md',\n"
            "                'content': '# Denied\\n',\n"
            "            })\n"
            "            print(json.dumps({\n"
            "                'server_name': init_res.serverInfo.name,\n"
            "                'tool_names': tool_names,\n"
            "                'has_workspace_arg': any('workspace_root' in s.get('properties', {}) for s in tool_schemas.values()),\n"
            "                'status_is_error': status_call.isError,\n"
            "                'write_is_error': write_call.isError,\n"
            "                'deny_is_error': deny_call.isError,\n"
            "                'deny_text': deny_call.content[0].text if deny_call.content else '',\n"
            "            }))\n"
            "asyncio.run(run())\n"
        )
        env = dict(os.environ)
        env["STE_MCP_PYTHON"] = mcp_py
        proc = subprocess.run(
            [mcp_py, "-I", "-B", "-c", script],
            cwd=str(self.workspace),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        data = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertEqual(data["server_name"], MCP_SERVER_NAME)
        self.assertEqual(set(data["tool_names"]), STE_MCP_TOOL_NAMES)
        self.assertFalse(data["has_workspace_arg"])
        self.assertFalse(data["status_is_error"])
        self.assertFalse(data["write_is_error"])
        self.assertTrue((self.workspace / "artifacts" / "mcp-stdio" / "hello.md").is_file())
        self.assertTrue(data["deny_is_error"])
        self.assertIn("policy_refusal", data["deny_text"])
        self.assertFalse((self.root / "outside-stdio-sentinel.md").exists())

    def test_host_operations_json_cli_dispatch(self) -> None:
        cli_script = REPO_ROOT / "integrations" / "mcp" / "operations.py"
        # 1. Valid write via JSON stdin + trusted --workspace flag
        req_ok = json.dumps({
            "action": "ste_write_artifact",
            "args": {
                "target_path": "artifacts/cli-dispatch/doc.md",
                "content": "# CLI Dispatch\n\nVerified shared host CLI dispatch.\n",
            },
        })
        proc_ok = subprocess.run(
            [sys.executable, "-B", str(cli_script), "--workspace", str(self.workspace)],
            input=req_ok,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(proc_ok.returncode, 0, proc_ok.stderr)
        res_ok = json.loads(proc_ok.stdout.strip())
        self.assertTrue(res_ok["ok"])
        self.assertTrue((self.workspace / "artifacts" / "cli-dispatch" / "doc.md").is_file())

        # 2. Untrusted workspace_root in args is refused with exit 2
        req_bad = json.dumps({
            "action": "ste_write_artifact",
            "args": {
                "workspace_root": str(self.root),
                "target_path": "artifacts/cli-dispatch/bad.md",
                "content": "# Blocked\n",
            },
        })
        proc_bad = subprocess.run(
            [sys.executable, "-B", str(cli_script), "--workspace", str(self.workspace)],
            input=req_bad,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(proc_bad.returncode, 2)
        res_bad = json.loads(proc_bad.stdout.strip())
        self.assertFalse(res_bad["ok"])
        self.assertEqual(res_bad["error"]["code"], "policy_refusal")

    def test_workspace_binding_root_uri_and_dep_path_security(self) -> None:
        from integrations.mcp import operations as mcp_ops
        from ste_promax.policy_runtime import PolicyBackendError, PolicyError

        # 1. Seed an unrelated session record with recent mtime; must NEVER be picked by mtime
        other_ws = self.root / "unrelated-other-session-workspace"
        other_ws.mkdir(parents=True, exist_ok=True)
        activate_session_scope(
            "unrelated-session-999",
            "tool.skill:ste-promax",
            working_directory=str(other_ws),
        )
        with patch.dict(os.environ, {"STE_TRUSTED_WORKSPACE": ""}, clear=False):
            # When _INITIAL_CWD is BUNDLE_ROOT (or an ancestor/descendant of BUNDLE_ROOT) and no
            # trusted session/roots/env context exists, resolve_trusted_workspace and host_write_artifact
            # MUST fail closed before writing inside the bundle!
            with patch.object(mcp_ops, "_INITIAL_CWD", mcp_ops.BUNDLE_ROOT):
                with self.assertRaises(PolicyError) as ctx_bundle_cwd:
                    mcp_ops.resolve_trusted_workspace()
                self.assertEqual(ctx_bundle_cwd.exception.code, "policy_refusal")

                bundle_sentinel = mcp_ops.BUNDLE_ROOT / "artifacts" / "bundle-pollution-sentinel.md"
                bundle_write_res = host_write_artifact(
                    target_path="artifacts/bundle-pollution-sentinel.md",
                    content="# Must never write into bundle\n",
                )
                self.assertFalse(bundle_write_res["ok"])
                self.assertEqual(bundle_write_res["error"]["code"], "policy_refusal")
                self.assertFalse(bundle_sentinel.exists())

            with patch.object(mcp_ops, "_INITIAL_CWD", mcp_ops.BUNDLE_ROOT.parent):
                with self.assertRaises(PolicyError) as ctx_ancestor_cwd:
                    mcp_ops.resolve_trusted_workspace()
                self.assertEqual(ctx_ancestor_cwd.exception.code, "policy_refusal")

            # When _INITIAL_CWD is an external workspace directory, it never picks other_ws by mtime
            with patch.object(mcp_ops, "_INITIAL_CWD", self.workspace):
                resolved_default = mcp_ops.resolve_trusted_workspace()
                self.assertEqual(resolved_default, self.workspace.resolve())
                self.assertNotEqual(resolved_default, other_ws)

            # With an unknown session_id, must fail closed rather than falling back to other_ws
            with self.assertRaises(PolicyError) as ctx_unknown:
                mcp_ops.resolve_trusted_workspace(session_id="unknown-session-id")
            self.assertEqual(ctx_unknown.exception.code, "policy_refusal")

            # preMcpToolCall binds sessionId and working_directory and injects ste_session_id into metaToUse
            pre_mcp_resp, pre_mcp_code = dispatch_hook(
                "preMcpToolCall",
                {
                    "sessionId": "mcp-bound-session-123",
                    "cwd": str(self.workspace),
                    "serverName": "ste-promax",
                    "toolName": "ste_status",
                    "_meta": {"progressToken": 7},
                },
            )
            self.assertEqual(pre_mcp_code, 0)
            self.assertEqual(
                pre_mcp_resp,
                {"metaToUse": {"progressToken": 7, "ste_session_id": "mcp-bound-session-123"}},
            )
            self.assertEqual(
                mcp_ops.resolve_trusted_workspace(session_id="mcp-bound-session-123"),
                self.workspace.resolve(),
            )

            # With exact bound session_id, returns that session's workspace
            resolved_bound = mcp_ops.resolve_trusted_workspace(session_id="unrelated-session-999")
            self.assertEqual(resolved_bound, other_ws.resolve())

        # 2. _file_uri_to_path rejects remote netloc on BOTH Windows and POSIX, plus query/fragment
        self.assertIsNone(mcp_ops._file_uri_to_path("file://evil.example.com/tmp/ws"))
        with patch.object(mcp_ops.os, "name", "posix"):
            self.assertIsNone(mcp_ops._file_uri_to_path("file://evil.example.com/tmp/ws"))
            self.assertIsNone(mcp_ops._file_uri_to_path("file://192.168.1.10/share/ws"))
        self.assertIsNone(mcp_ops._file_uri_to_path(self.workspace.as_uri() + "?query=1"))
        self.assertIsNone(mcp_ops._file_uri_to_path(self.workspace.as_uri() + "#frag"))
        self.assertEqual(mcp_ops._file_uri_to_path(self.workspace.as_uri()), self.workspace.resolve())

        # Ambiguous multiple MCP roots or remote MCP root must fail closed
        ws_two = self.root / "workspace-two"
        ws_two.mkdir(parents=True, exist_ok=True)
        with self.assertRaises(PolicyError) as ctx_ambig:
            mcp_ops.resolve_trusted_workspace(mcp_roots=[self.workspace.as_uri(), ws_two.as_uri()])
        self.assertEqual(ctx_ambig.exception.code, "policy_refusal")

        with self.assertRaises(PolicyError) as ctx_remote:
            mcp_ops.resolve_trusted_workspace(mcp_roots=["file://evil.example.com/workspace"])
        self.assertEqual(ctx_remote.exception.code, "policy_refusal")

        self.assertEqual(
            mcp_ops.resolve_trusted_workspace(mcp_roots=[self.workspace.as_uri()]),
            self.workspace.resolve(),
        )

        # 3. _ensure_render_deps_on_path rejects incompatible pyvenv.cfg version without probing sys.path
        fake_venv = self.root / "fake-venv"
        fake_scripts = fake_venv / "Scripts"
        fake_scripts.mkdir(parents=True, exist_ok=True)
        fake_py = fake_scripts / "python.exe"
        fake_py.write_bytes(b"MZ-fake-python")
        (fake_venv / "pyvenv.cfg").write_text("version = 3.11.9\n", encoding="utf-8")
        fake_sp = fake_venv / "Lib" / "site-packages"
        fake_sp.mkdir(parents=True, exist_ok=True)

        fake_runtime_cfg = {
            "schema": "ste-promax.runtime.v1",
            "managed_by": "ste-promax",
            "python": str(fake_py),
            "skillc_root": str(self.root),
            "ste_root": str(REPO_ROOT),
            "state_root": str(self.state_root),
            "skillc_commit": "25cc63bf82e968da7d01e204dc6d99879b76c45b",
            "versions": {"Jinja2": "3.1.6", "PyYAML": "6.0.3"},
        }
        with (
            patch.dict(sys.modules, {"jinja2": None, "yaml": None}),
            patch.object(mcp_ops, "load_runtime_config", return_value=fake_runtime_cfg),
        ):
            with self.assertRaises(PolicyBackendError):
                mcp_ops._ensure_render_deps_on_path()
            self.assertNotIn(str(fake_sp), sys.path)

    def test_inspect_confinement_spy_bounds_and_headless_unsupported(self) -> None:
        from integrations.mcp import operations as mcp_ops
        from integrations.mcp import host_synthesize_wav

        # 1. headless_browser=True must immediately return unsupported_operation without launching anything
        hl_res = host_inspect_artifact(
            target_path="docs",
            headless_browser=True,
            workspace_root=self.workspace,
        )
        self.assertFalse(hl_res["ok"])
        self.assertEqual(hl_res["error"]["code"], "unsupported_operation")

        # 2. Bundle manifest.files[*].path pointing to an outside sentinel must be rejected BEFORE open/read
        outside_inspect_sentinel = self.root / "outside-inspect-sentinel.html"
        outside_inspect_sentinel.write_text("<!doctype html><html><body>SECRET</body></html>\n", encoding="utf-8")
        evil_bundle = self.workspace / "artifacts" / "evil-bundle"
        evil_bundle.mkdir(parents=True, exist_ok=True)
        (evil_bundle / "manifest.json").write_text(
            json.dumps({
                "status": "complete",
                "lint_passed": True,
                "files": {
                    "html": {
                        "path": str(outside_inspect_sentinel),
                        "sha256": _sha256_file(outside_inspect_sentinel),
                    }
                },
            }),
            encoding="utf-8",
        )

        opened_paths: list[Path] = []
        orig_open = Path.open

        def _spy_open(path_self: Path, *args: Any, **kwargs: Any):
            opened_paths.append(path_self.resolve())
            return orig_open(path_self, *args, **kwargs)

        with patch.object(Path, "open", _spy_open):
            evil_res = host_inspect_artifact(
                target_path=str(evil_bundle),
                headless_browser=False,
                workspace_root=self.workspace,
            )
        self.assertFalse(evil_res["ok"])
        self.assertEqual(evil_res["error"]["code"], "policy_refusal")
        self.assertNotIn(outside_inspect_sentinel.resolve(), opened_paths)

        # 3. Size bound on inspected file
        big_html = self.workspace / "artifacts" / "big.html"
        big_html.parent.mkdir(parents=True, exist_ok=True)
        big_html.write_text("<html><body>x</body></html>\n", encoding="utf-8")
        with patch.object(mcp_ops, "MAX_INSPECT_FILE_BYTES", 8):
            big_res = host_inspect_artifact(
                target_path=str(big_html),
                headless_browser=False,
                workspace_root=self.workspace,
            )
            self.assertFalse(big_res["ok"])
            self.assertEqual(big_res["error"]["code"], "invalid_input")

        # 4. host_synthesize_wav must NOT create parent directories on rejected inputs
        txt_file = self.workspace / "artifacts" / "line.txt"
        txt_file.write_text("Check the pressure gauge.\n", encoding="utf-8")
        nonexistent_parent = self.workspace / "artifacts" / "no-such-audio-dir"
        wav_res = host_synthesize_wav(
            text_path=str(txt_file),
            audio_path=str(nonexistent_parent / "beat.wav"),
            workspace_root=self.workspace,
        )
        self.assertFalse(wav_res["ok"])
        self.assertEqual(wav_res["error"]["code"], "invalid_input")
        self.assertFalse(nonexistent_parent.exists())

    def test_mcp_python_config_validation_and_source_mutation_regression(self) -> None:
        from ste_promax.policy_runtime import PolicyBackendError, PolicyError

        # 1. Explicit relative or missing STE_MCP_PYTHON must fail closed without falling back
        with patch.dict(os.environ, {"STE_MCP_PYTHON": "relative/python.exe"}, clear=False):
            with self.assertRaises(PolicyError) as ctx_rel:
                resolve_mcp_python(probe_mcp=False)
            self.assertEqual(ctx_rel.exception.code, "dependency_missing")

        with patch.dict(os.environ, {"STE_MCP_PYTHON": str(self.root / "missing-py.exe")}, clear=False):
            with self.assertRaises(PolicyBackendError):
                resolve_mcp_python(probe_mcp=True)

        # 2. Explicit invalid STE_SKILLC_RUNTIME_CONFIG must fail closed without falling back to default config
        bad_cfg_path = self.root / "bad-runtime.json"
        bad_cfg_path.write_text(json.dumps({"schema": "wrong"}), encoding="utf-8")
        with patch.dict(
            os.environ,
            {"STE_MCP_PYTHON": "", "STE_SKILLC_RUNTIME_CONFIG": str(bad_cfg_path)},
            clear=False,
        ):
            with self.assertRaises(PolicyBackendError):
                resolve_mcp_python(probe_mcp=False)

        # 3. Source mutation during host_render_artifact must fail with postcondition_failure, DENY receipt, and retain partial files
        from ste_promax import gate as ste_gate
        from ste_promax import render as ste_render
        src_md = self.workspace / "artifacts" / "mutable-source.md"
        src_md.parent.mkdir(parents=True, exist_ok=True)
        src_md.write_text("# Original Title\n\nOriginal body.\n", encoding="utf-8")
        out_triple_dir = self.workspace / "artifacts" / "mutated-triple-out"

        orig_render_artifact = ste_render.render_artifact

        def _mutating_render(
            input_data: dict[str, Any],
            design_path: Path | None = None,
            output_dir: Path | None = None,
            *,
            trusted_html: bool = False,
        ):
            triple_res = orig_render_artifact(
                input_data,
                design_path=design_path,
                output_dir=output_dir,
                trusted_html=trusted_html,
            )
            src_md.write_text("# Mutated Title\n\nTampered during render.\n", encoding="utf-8")
            return triple_res

        with patch.object(ste_render, "render_artifact", side_effect=_mutating_render):
            mut_res = host_render_artifact(
                output_dir=str(out_triple_dir),
                input_path=str(src_md),
                workspace_root=self.workspace,
            )
        self.assertFalse(mut_res["ok"])
        self.assertEqual(mut_res["error"]["code"], "postcondition_failure")
        self.assertEqual(mut_res["error"].get("receipt", {}).get("verdict"), "DENY")
        last_rec = ste_gate.get_last_receipt()
        self.assertIsNotNone(last_rec)
        assert last_rec is not None
        self.assertEqual(last_rec.get("verdict"), "DENY")
        self.assertTrue(out_triple_dir.is_dir())
        self.assertTrue(list(out_triple_dir.glob("*.html")))


@unittest.skipUnless(
    _host_cli_tests_enabled() and COPILOT_EXE is not None and COPILOT_EXE.is_file(),
    "Real Copilot CLI loopback tests require STE_RUN_HOST_CLI_TESTS=1 and an available Copilot CLI binary.",
)
class CopilotCliLoopbackReleaseGateTests(unittest.TestCase):
    """Real GitHub Copilot CLI (`copilot` / `copilot.exe`) end-to-end validation with retained evidence."""

    def test_real_copilot_cli_end_to_end_with_retained_artifacts(self) -> None:
        assert COPILOT_EXE is not None
        self.assertTrue(COPILOT_EXE.is_file(), f"Copilot CLI executable not found: {COPILOT_EXE}")
        _find_mcp_python()

        # Create a fresh owned retained evidence directory under repo artifacts/
        import secrets
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        retained_dir = REPO_ROOT / "artifacts" / f"copilot-cli-validation-{ts}-{secrets.token_hex(4)}"
        retained_dir.mkdir(parents=True, exist_ok=False)

        sandbox_root = retained_dir / "sandbox"
        workspace = sandbox_root / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        copilot_home = sandbox_root / "copilot-home"
        copilot_home.mkdir(parents=True, exist_ok=True)
        policy_state = sandbox_root / "policy-state"
        policy_state.mkdir(parents=True, exist_ok=True)

        # Create an installed bundle copy inside the sandbox so tests run against an installed bundle
        installed_plugin = sandbox_root / "installed-plugin" / "ste-pro-max"
        installed_plugin.mkdir(parents=True, exist_ok=True)
        for rel_dir in ("ste_promax", "integrations", "com.github.copilot", "skills", "examples", "docs", "ste-promax"):
            shutil.copytree(REPO_ROOT / rel_dir, installed_plugin / rel_dir)
        for rel_file in ("plugin.json", "mcp.json", "__main__.py", "quickstart.py", "pyproject.toml", "README.md", "DESIGN.md", "LICENSE", "NOTICE"):
            shutil.copy2(REPO_ROOT / rel_file, installed_plugin / rel_file)

        # Seed a source document in the sandbox workspace
        source_doc = workspace / "source-note.md"
        source_doc.write_text(
            "# Hydraulic Pressure Check\n\nCheck the pressure gauge before opening the relief valve.\n",
            encoding="utf-8",
        )

        # Sentinels that must NEVER be created
        raw_shell_sentinel = workspace / "sentinel-raw-shell.txt"
        apply_patch_sentinel = workspace / "sentinel-apply-patch.txt"
        out_of_root_sentinel = sandbox_root / "sentinel-outside-root.md"
        missing_backend_sentinel = workspace / "artifacts" / "sentinel-missing-backend.md"

        # Scripted loopback OpenAI stub server driving multi-turn tool calls through real copilot.exe
        scenario_state: dict[str, Any] = {
            "mode": "non_ste",
            "turn": 0,
            "requests": [],
        }

        class LoopbackStubHandler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", 0))
                raw_body = self.rfile.read(length).decode("utf-8", errors="replace")
                body = json.loads(raw_body) if raw_body.startswith("{") else {}
                scenario_state["turn"] += 1
                turn = scenario_state["turn"]
                mode = scenario_state["mode"]
                tools_offered = [
                    t.get("function", {}).get("name") or t.get("name") or t.get("type")
                    for t in body.get("tools", [])
                ]
                scenario_state["requests"].append({
                    "mode": mode,
                    "turn": turn,
                    "tools_offered": tools_offered,
                    "messages_tail": body.get("messages", [])[-2:],
                })

                if mode == "non_ste":
                    if turn == 1:
                        msg = {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_non_ste_ps",
                                    "type": "function",
                                    "function": {
                                        "name": "powershell",
                                        "arguments": json.dumps({
                                            "command": "Write-Output NON_STE_PASSTHROUGH_OK",
                                            "description": "Verify non-STE passthrough",
                                        }),
                                    },
                                }
                            ],
                        }
                        finish = "tool_calls"
                    else:
                        msg = {"role": "assistant", "content": "NON_STE_COMPLETE", "tool_calls": None}
                        finish = "stop"

                elif mode == "ste_workflow_and_denials":
                    if turn == 1:
                        # 1. Activate STE scope via skill tool
                        msg = {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_activate_ste",
                                    "type": "function",
                                    "function": {
                                        "name": "skill",
                                        "arguments": json.dumps({"skill": "ste-promax"}),
                                    },
                                }
                            ],
                        }
                        finish = "tool_calls"
                    elif turn == 2:
                        # 2. Attempt apply_patch sentinel write (gpt-6.1-sol mutation tool; must be denied!)
                        msg = {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_blocked_patch",
                                    "type": "function",
                                    "function": {
                                        "name": "apply_patch",
                                        "arguments": json.dumps({
                                            "input": (
                                                "*** Begin Patch\n"
                                                f"*** Add File: {apply_patch_sentinel.name}\n"
                                                "+PATCH_PWNED\n"
                                                "*** End Patch"
                                            )
                                        }),
                                    },
                                }
                            ],
                        }
                        finish = "tool_calls"
                    elif turn == 3:
                        # 3. Attempt raw powershell sentinel write (must be denied by preToolUse hook!)
                        msg = {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_blocked_ps",
                                    "type": "function",
                                    "function": {
                                        "name": "powershell",
                                        "arguments": json.dumps({
                                            "command": f"Set-Content -Path '{raw_shell_sentinel}' -Value 'PWNED'",
                                            "description": "Attempt raw shell write in STE scope",
                                        }),
                                    },
                                }
                            ],
                        }
                        finish = "tool_calls"
                    elif turn == 4:
                        # 4. Attempt out-of-root write via ste_write_artifact (must be denied!)
                        msg = {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_blocked_out_of_root",
                                    "type": "function",
                                    "function": {
                                        "name": "ste-promax-ste_write_artifact",
                                        "arguments": json.dumps({
                                            "target_path": str(out_of_root_sentinel),
                                            "content": "# Out of root\n",
                                        }),
                                    },
                                }
                            ],
                        }
                        finish = "tool_calls"
                    elif turn == 5:
                        # 5. Execute valid guarded ste_write_artifact + ste_render_bundle automatically!
                        msg = {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_valid_write",
                                    "type": "function",
                                    "function": {
                                        "name": "ste-promax-ste_write_artifact",
                                        "arguments": json.dumps({
                                            "target_path": "artifacts/authored/valve-procedure.md",
                                            "content": "# Valve Procedure\n\nVerify zero pressure before opening the valve.\n",
                                        }),
                                    },
                                },
                                {
                                    "id": "call_valid_render",
                                    "type": "function",
                                    "function": {
                                        "name": "ste-promax-ste_render_bundle",
                                        "arguments": json.dumps({
                                            "input_path": str(source_doc),
                                            "output_dir": "artifacts/rendered-bundle",
                                        }),
                                    },
                                },
                            ],
                        }
                        finish = "tool_calls"
                    else:
                        msg = {"role": "assistant", "content": "STE_WORKFLOW_COMPLETE", "tool_calls": None}
                        finish = "stop"

                elif mode == "ste_resume_denial":
                    if turn == 1:
                        # On resumed STE session, immediately try powershell without calling skill again
                        msg = {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_resumed_ps",
                                    "type": "function",
                                    "function": {
                                        "name": "powershell",
                                        "arguments": json.dumps({
                                            "command": f"Set-Content -Path '{raw_shell_sentinel}' -Value 'RESUMED_PWN'",
                                            "description": "Attempt raw shell write on resumed STE session",
                                        }),
                                    },
                                }
                            ],
                        }
                        finish = "tool_calls"
                    else:
                        msg = {"role": "assistant", "content": "STE_RESUME_COMPLETE", "tool_calls": None}
                        finish = "stop"

                elif mode == "ste_author_agent":
                    if turn == 1:
                        msg = {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_agent_status",
                                    "type": "function",
                                    "function": {
                                        "name": "ste-promax-ste_status",
                                        "arguments": json.dumps({}),
                                    },
                                }
                            ],
                        }
                        finish = "tool_calls"
                    else:
                        msg = {"role": "assistant", "content": "STE_AUTHOR_AGENT_COMPLETE", "tool_calls": None}
                        finish = "stop"

                elif mode == "missing_backend":
                    if turn == 1:
                        msg = {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_missing_backend_write",
                                    "type": "function",
                                    "function": {
                                        "name": "ste-promax-ste_write_artifact",
                                        "arguments": json.dumps({
                                            "target_path": "artifacts/sentinel-missing-backend.md",
                                            "content": "# Missing backend sentinel\n",
                                        }),
                                    },
                                }
                            ],
                        }
                        finish = "tool_calls"
                    else:
                        msg = {"role": "assistant", "content": "MISSING_BACKEND_COMPLETE", "tool_calls": None}
                        finish = "stop"
                else:
                    msg = {"role": "assistant", "content": "OK", "tool_calls": None}
                    finish = "stop"

                resp = {
                    "id": f"chatcmpl-{mode}-{turn}",
                    "object": "chat.completion",
                    "created": 1700000000,
                    "model": "gpt-4o",
                    "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
                    "usage": {"prompt_tokens": 25, "completion_tokens": 10, "total_tokens": 35},
                }
                payload_bytes = json.dumps(resp).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload_bytes)))
                self.end_headers()
                self.wfile.write(payload_bytes)

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), LoopbackStubHandler)
        port = server.server_address[1]
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        base_env = dict(os.environ)
        base_env["COPILOT_HOME"] = str(copilot_home)
        base_env["COPILOT_OFFLINE"] = "true"
        base_env["COPILOT_PROVIDER_BASE_URL"] = f"http://127.0.0.1:{port}/v1"
        base_env["COPILOT_PROVIDER_TYPE"] = "openai"
        base_env["COPILOT_PROVIDER_API_KEY"] = "mock-ste-loopback-token"
        base_env["COPILOT_MODEL"] = "gpt-4o"
        base_env["COPILOT_ALLOW_ALL"] = "true"
        base_env.pop("STE_MCP_PYTHON", None)
        base_env.pop("STE_TRUSTED_WORKSPACE", None)
        base_env["STE_SKILLC_STATE_ROOT"] = str(policy_state)

        def _run_cli(
            run_name: str,
            mode: str,
            extra_args: list[str],
            env_overrides: dict[str, str] | None = None,
        ) -> subprocess.CompletedProcess[str]:
            scenario_state["mode"] = mode
            scenario_state["turn"] = 0
            env = dict(base_env)
            if env_overrides:
                env.update(env_overrides)
            cmd = [
                str(COPILOT_EXE),
                "--no-auto-update",
                "--disable-builtin-mcps",
                "--stream",
                "off",
                "--plugin-dir",
                str(installed_plugin),
                "-C",
                str(workspace),
                *extra_args,
            ]
            proc = subprocess.run(
                cmd,
                cwd=str(sandbox_root),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                check=False,
            )
            (retained_dir / f"{run_name}.stdout.txt").write_text(proc.stdout or "", encoding="utf-8")
            (retained_dir / f"{run_name}.stderr.txt").write_text(proc.stderr or "", encoding="utf-8")
            return proc

        # Run 1: Non-STE passthrough
        non_ste_sid = "11111111-2222-4333-8444-555555555551"
        p1 = _run_cli(
            "01-non-ste-passthrough",
            "non_ste",
            ["--session-id", non_ste_sid, "-p", "Run non-STE diagnostic command"],
        )
        self.assertEqual(p1.returncode, 0, p1.stderr)
        self.assertIn("NON_STE_COMPLETE", p1.stdout)

        # Run 2: STE workflow activation + raw shell denial + out-of-root denial + automatic write & render_bundle
        ste_sid = "11111111-2222-4333-8444-555555555552"
        p2 = _run_cli(
            "02-ste-workflow-and-denials",
            "ste_workflow_and_denials",
            ["--session-id", ste_sid, "-p", "Use ste-promax to author and render the valve procedure"],
        )
        self.assertEqual(p2.returncode, 0, p2.stderr)
        self.assertIn("STE_WORKFLOW_COMPLETE", p2.stdout)
        self.assertFalse(apply_patch_sentinel.exists(), "apply_patch sentinel must never be created!")
        self.assertFalse(raw_shell_sentinel.exists(), "Raw shell sentinel must never be created!")
        self.assertFalse(out_of_root_sentinel.exists(), "Out-of-root sentinel must never be created!")

        authored_file = workspace / "artifacts" / "authored" / "valve-procedure.md"
        rendered_manifest = workspace / "artifacts" / "rendered-bundle" / "manifest.json"
        rendered_gallery = workspace / "artifacts" / "rendered-bundle" / "gallery.html"
        self.assertTrue(authored_file.is_file(), "Guarded ste_write_artifact file should exist")
        self.assertTrue(rendered_manifest.is_file(), "Guarded ste_render_bundle manifest.json should exist")
        self.assertTrue(rendered_gallery.is_file(), "Guarded ste_render_bundle gallery.html should exist")

        # Run 3: Resume STE session (--resume=<ste_sid>) and verify raw shell is STILL denied without re-invoking skill
        p3 = _run_cli(
            "03-ste-resume-denial",
            "ste_resume_denial",
            ["--resume", ste_sid, "-p", "Continue the STE session"],
        )
        self.assertEqual(p3.returncode, 0, p3.stderr)
        self.assertIn("STE_RESUME_COMPLETE", p3.stdout)
        self.assertFalse(raw_shell_sentinel.exists(), "Resumed session raw shell sentinel must not exist!")

        # Run 4: Dedicated ste-author custom agent (--agent ste-pro-max:ste-author)
        author_sid = "11111111-2222-4333-8444-555555555554"
        p4 = _run_cli(
            "04-ste-author-agent",
            "ste_author_agent",
            ["--session-id", author_sid, "--agent", "ste-pro-max:ste-author", "-p", "Check STE status"],
        )
        self.assertEqual(p4.returncode, 0, p4.stderr)
        self.assertIn("STE_AUTHOR_AGENT_COMPLETE", p4.stdout)

        # Verify ste-author agent tool allowlist from captured model request
        author_reqs = [r for r in scenario_state["requests"] if r["mode"] == "ste_author_agent"]
        self.assertTrue(author_reqs)
        offered = set(author_reqs[0]["tools_offered"])
        self.assertIn("ste-promax-ste_status", offered)
        self.assertIn("ste-promax-ste_write_artifact", offered)
        self.assertIn("ste-promax-ste_render_bundle", offered)
        for excluded_opaque in ("apply_patch", "edit", "create", "powershell", "read_powershell", "list_powershell", "run_dynamic_workflow", "write_agent"):
            self.assertNotIn(excluded_opaque, offered)

        # Run 5: Missing backend fail-closed before sentinel write
        missing_sid = "11111111-2222-4333-8444-555555555555"
        p5 = _run_cli(
            "05-missing-backend-denial",
            "missing_backend",
            ["--session-id", missing_sid, "--agent", "ste-pro-max:ste-author", "-p", "Attempt write with missing backend"],
            env_overrides={
                "STE_SKILLC_RUNTIME_CONFIG": str(sandbox_root / "missing-runtime.json"),
                "STE_SKILLC_FORCE_WORKER": "1",
            },
        )
        self.assertEqual(p5.returncode, 0, p5.stderr)
        self.assertFalse(missing_backend_sentinel.exists(), "Missing-backend sentinel must never be created!")

        # Discover actual tool dispatch and outcomes from retained events.jsonl (never rely on exit 0 alone)
        def _parse_session_tool_outcomes(sid: str) -> dict[str, dict[str, Any]]:
            ev_path = copilot_home / "session-state" / sid / "events.jsonl"
            self.assertTrue(ev_path.is_file(), f"Missing events.jsonl for session {sid}")
            outcomes: dict[str, dict[str, Any]] = {}
            for line in ev_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                ev = json.loads(line)
                if ev.get("type") == "tool.execution_complete":
                    d = ev.get("data", {})
                    cid = d.get("toolCallId")
                    if cid:
                        outcomes[cid] = {
                            "success": d.get("success"),
                            "error": d.get("error"),
                            "content": (d.get("result") or {}).get("content") if isinstance(d.get("result"), dict) else None,
                        }
            return outcomes

        non_ste_outcomes = _parse_session_tool_outcomes(non_ste_sid)
        self.assertTrue(non_ste_outcomes["call_non_ste_ps"]["success"])

        ste_outcomes = _parse_session_tool_outcomes(ste_sid)
        self.assertTrue(ste_outcomes["call_activate_ste"]["success"])
        self.assertFalse(ste_outcomes["call_blocked_patch"]["success"])
        self.assertEqual(ste_outcomes["call_blocked_patch"]["error"]["code"], "denied")
        self.assertFalse(ste_outcomes["call_blocked_ps"]["success"])
        self.assertEqual(ste_outcomes["call_blocked_ps"]["error"]["code"], "denied")
        self.assertFalse(ste_outcomes["call_blocked_out_of_root"]["success"])
        self.assertTrue(ste_outcomes["call_valid_write"]["success"])
        self.assertTrue(ste_outcomes["call_valid_render"]["success"])
        self.assertFalse(ste_outcomes["call_resumed_ps"]["success"])
        self.assertEqual(ste_outcomes["call_resumed_ps"]["error"]["code"], "denied")

        author_outcomes = _parse_session_tool_outcomes(author_sid)
        self.assertTrue(author_outcomes["call_agent_status"]["success"])
        raw_status_content = (author_outcomes["call_agent_status"]["content"] or "{}").lstrip()
        status_payload, _ = json.JSONDecoder().raw_decode(raw_status_content)
        self.assertEqual(
            Path(status_payload["result"]["workspace_root"]).resolve(),
            workspace.resolve(),
        )
        self.assertEqual(
            Path(status_payload["result"]["bundle_root"]).resolve(),
            installed_plugin.resolve(),
        )
        self.assertNotEqual(
            Path(status_payload["result"]["workspace_root"]).resolve(),
            Path(status_payload["result"]["bundle_root"]).resolve(),
        )
        self.assertFalse((installed_plugin / "artifacts").exists())

        missing_outcomes = _parse_session_tool_outcomes(missing_sid)
        self.assertFalse(missing_outcomes["call_missing_backend_write"]["success"])

        # Retain summary manifest and SHA-256 hashes of all session events.jsonl and generated artifacts
        events_records: dict[str, dict[str, Any]] = {}
        for ev_path in sorted(copilot_home.rglob("events.jsonl")):
            rel_ev = ev_path.relative_to(retained_dir).as_posix()
            events_records[rel_ev] = {
                "sha256": _sha256_file(ev_path),
                "size": ev_path.stat().st_size,
            }
        self.assertGreaterEqual(len(events_records), 4)

        evidence_summary = {
            "schema": "ste-promax.copilot-cli-validation-evidence.v1",
            "timestamp": ts,
            "copilot_exe": str(COPILOT_EXE),
            "plugin_loading_mode": "session-plugin-dir-copy-not-persistent-install",
            "session_plugin_dir": str(installed_plugin),
            "workspace": str(workspace),
            "sentinels_absent": {
                "apply_patch_sentinel": not apply_patch_sentinel.exists(),
                "raw_shell_sentinel": not raw_shell_sentinel.exists(),
                "out_of_root_sentinel": not out_of_root_sentinel.exists(),
                "missing_backend_sentinel": not missing_backend_sentinel.exists(),
            },
            "verified_tool_outcomes": {
                "non_ste": non_ste_outcomes,
                "ste_workflow_and_resume": ste_outcomes,
                "ste_author_agent": author_outcomes,
                "missing_backend": missing_outcomes,
            },
            "generated_artifacts": {
                "valve_procedure_md": {
                    "path": str(authored_file),
                    "sha256": _sha256_file(authored_file),
                },
                "rendered_bundle_manifest": {
                    "path": str(rendered_manifest),
                    "sha256": _sha256_file(rendered_manifest),
                },
                "rendered_bundle_gallery": {
                    "path": str(rendered_gallery),
                    "sha256": _sha256_file(rendered_gallery),
                },
            },
            "session_events_jsonl": events_records,
            "captured_requests": scenario_state["requests"],
        }
        (retained_dir / "validation-summary.json").write_text(
            json.dumps(evidence_summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()

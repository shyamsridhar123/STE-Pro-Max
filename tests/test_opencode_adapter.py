"""Focused unit, contract, and real OpenCode 2.2.6 end-to-end tests for the OpenCode V2 STE host adapter.

Covers:
1. Package & manifest contract (`integrations/opencode/package.json`, `server.js`, `core.js`, `index.js`, `dispatch.py`).
2. Installed-bundle isolation (`resolve_bundle_root` and `resolveBundleRoot` use the installed plugin copy,
   never `runtime.json.ste_root`).
3. Bounded CLI JSON dispatcher (`integrations/opencode/dispatch.py`) and guarded host operations
   (`ste_status`, `ste_check_prose`, `ste_write_artifact`, `ste_render_bundle`, `ste_render_artifact`,
   `ste_regenerate_gallery`, `ste_prepare_story_media`, `ste_inspect_artifact`, `ste_export_bundle`,
   `ste_preflight_turn`, `ste_postprocess_prose`), including pre-mutation denial of out-of-workspace targets,
   protected paths, untrusted raw HTML, forbidden model keys, and missing SkillC runtime.
4. JS Effect plugin & scope unit boundaries (`createSteOpenCodePlugin`, `createScopeManager`,
   `evaluateSteToolIntercept`, `scanContextMessagesForScope`), proving:
   - V2 Effect `execute.before` hook + typed `Tool.Error` refusal.
   - Top-level `ste_*` tool registration with `options: { codemode: false }`.
   - Scope activation from `skill(id)`, `prompt.skills`, `session.skill.activated`, typed `SessionMessage`
     context records (`type: "skill"`, `User.skills`), exact `SKILL.md` read, and `ste_*` tools.
   - No false activation from random prompt words.
   - Parent-to-child inheritance via `ctx.session.get` `parentID` for new and resumed native children,
     while blocking external ACP subagents (`dsh`, `acp`).
   - Explicit user `/ste-off` deactivation and no model-callable bypass.
   - Post-stream `session.text.ended` prose diagnostics and graceful read-only degradation when runtime is missing.
5. Real OpenCode 2.2.6 (`opencode-cli` / `opencode-cli.exe --standalone`) end-to-end execution against a local loopback
   OpenAI-compatible mock provider in an isolated home/config/workspace (zero billable model calls),
   retaining full evidence under `artifacts/`.
   `OpenCodeAdapterDispatcherAndBoundaryTests` always runs unconditionally in CI and local runs.
   `OpenCodeV2LiveLoopbackTests` resolves the CLI from `STE_OPENCODE_CLI_EXE` (or `OPENCODE_CLI_EXE`),
   `PATH`, or the known Windows desktop CLI fallback, and runs only when `STE_RUN_HOST_CLI_TESTS=1`
   and the OpenCode CLI executable is available.
"""
from __future__ import annotations

import datetime
import hashlib
import http.server
import json
import os
from pathlib import Path
import secrets
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

from integrations.opencode import (  # noqa: E402
    BUNDLE_ROOT,
    INDEX_JS_PATH,
    OPENCODE_PLUGIN_ID,
    PACKAGE_JSON_PATH,
    PLUGIN_DIR,
    SERVER_JS_PATH,
    STE_SKILL_IDS,
    STE_TOOL_NAMES,
    dispatch_operation,
    resolve_bundle_root,
)

def _resolve_opencode_cli() -> Path | None:
    for env_key in ("STE_OPENCODE_CLI_EXE", "OPENCODE_CLI_EXE"):
        raw = os.environ.get(env_key, "").strip()
        if raw:
            candidate = Path(raw).expanduser()
            if candidate.is_file():
                return candidate
    names = (
        ("opencode-cli.exe", "opencode-cli", "opencode.exe", "opencode")
        if os.name == "nt"
        else ("opencode-cli", "opencode", "opencode-cli.exe", "opencode.exe")
    )
    for bin_name in names:
        found = shutil.which(bin_name)
        if found:
            candidate = Path(found)
            if candidate.is_file():
                return candidate
    if os.name == "nt" or sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "").strip()
        candidates = []
        if appdata:
            candidates.append(Path(appdata) / "ai.opencode.desktop" / "cli" / "2.2.6-x64" / "opencode-cli.exe")
        candidates.append(Path.home() / "AppData" / "Roaming" / "ai.opencode.desktop" / "cli" / "2.2.6-x64" / "opencode-cli.exe")
        for fallback in candidates:
            if fallback.is_file():
                return fallback
    return None


def _host_cli_tests_enabled() -> bool:
    return os.environ.get("STE_RUN_HOST_CLI_TESTS", "").strip() == "1"


def _resolve_portable_temp_base() -> Path:
    base = Path(tempfile.gettempdir()).resolve() / "opencode"
    base.mkdir(parents=True, exist_ok=True)
    return base


OPENCODE_CLI_EXE: Path | None = _resolve_opencode_cli()
APPROVED_TEMP_BASE: Path = _resolve_portable_temp_base()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _valid_pcm_wav_bytes() -> bytes:
    sample_rate = 8000
    samples = [0, 12000, -12000, 6000, -6000, 18000, -18000, 3000] * 125
    pcm_frames = struct.pack(f"<{len(samples)}h", *samples)
    fmt_chunk = struct.pack("<4sIHHIIHH", b"fmt ", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16)
    data_chunk = struct.pack("<4sI", b"data", len(pcm_frames)) + pcm_frames
    riff_size = 4 + len(fmt_chunk) + len(data_chunk)
    return struct.pack("<4sI4s", b"RIFF", riff_size, b"WAVE") + fmt_chunk + data_chunk


def _make_tool_call_sse(call_id: str, name: str, args_dict: dict[str, Any]) -> bytes:
    chunk1 = {
        "id": f"chatcmpl-{call_id}",
        "object": "chat.completion.chunk",
        "choices": [
            {
                "index": 0,
                "delta": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(args_dict),
                            },
                        }
                    ],
                },
                "finish_reason": None,
            }
        ],
    }
    chunk2 = {
        "id": f"chatcmpl-{call_id}",
        "object": "chat.completion.chunk",
        "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
        "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
    }
    return f"data: {json.dumps(chunk1)}\n\ndata: {json.dumps(chunk2)}\n\ndata: [DONE]\n\n".encode("utf-8")


def _make_text_sse(text: str) -> bytes:
    chunk1 = {
        "id": "chatcmpl-txt",
        "object": "chat.completion.chunk",
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant", "content": text},
                "finish_reason": None,
            }
        ],
    }
    chunk2 = {
        "id": "chatcmpl-txt",
        "object": "chat.completion.chunk",
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
    }
    return f"data: {json.dumps(chunk1)}\n\ndata: {json.dumps(chunk2)}\n\ndata: [DONE]\n\n".encode("utf-8")


class OpenCodeAdapterDispatcherAndBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        APPROVED_TEMP_BASE.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="ste-oc-unit-", dir=str(APPROVED_TEMP_BASE))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.workspace = self.root / "workspace"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.state_root = self.root / "policy-state"
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.env_patch = patch.dict(
            os.environ,
            {
                "STE_SKILLC_STATE_ROOT": str(self.state_root),
                "STE_TRUSTED_WORKSPACE": str(self.workspace),
            },
            clear=False,
        )
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def test_package_layout_and_installed_bundle_isolation(self) -> None:
        self.assertTrue(PACKAGE_JSON_PATH.is_file())
        self.assertTrue(SERVER_JS_PATH.is_file())
        self.assertTrue(INDEX_JS_PATH.is_file())
        self.assertTrue((PLUGIN_DIR / "core.js").is_file())
        self.assertTrue((PLUGIN_DIR / "dispatch.py").is_file())

        pkg = json.loads(PACKAGE_JSON_PATH.read_text(encoding="utf-8"))
        root_manifest = json.loads((REPO_ROOT / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(pkg.get("version"), root_manifest.get("version"))
        self.assertEqual(pkg.get("type"), "module")
        self.assertEqual(pkg.get("main"), "server.js")
        self.assertNotIn("exports", pkg)
        self.assertEqual(BUNDLE_ROOT, REPO_ROOT)
        self.assertEqual(resolve_bundle_root(), REPO_ROOT)
        self.assertEqual(
            STE_SKILL_IDS,
            frozenset({"ste-promax", "ste-visual-docs", "ste-storytelling", "ste-line-studio"}),
        )

        # Copy bundle into an isolated installed directory and verify both Python and JS
        # resolve the installed bundle root rather than runtime.json.ste_root.
        installed_root = self.root / "installed-bundle" / "ste-pro-max"
        installed_root.mkdir(parents=True, exist_ok=True)
        for rel_dir in ("ste_promax", "integrations", "skills", "examples"):
            shutil.copytree(REPO_ROOT / rel_dir, installed_root / rel_dir)

        installed_dispatch = installed_root / "integrations" / "opencode" / "dispatch.py"
        proc = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                str(installed_dispatch),
                "--workspace-root",
                str(self.workspace),
                "--action",
                "ste_status",
            ],
            input="{}",
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        status_payload = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertTrue(status_payload["ok"])
        self.assertEqual(
            Path(status_payload["result"]["bundle_root"]).resolve(),
            installed_root.resolve(),
        )
        self.assertEqual(status_payload["result"]["host_adapter"], OPENCODE_PLUGIN_ID)

    def test_python_dispatcher_guarded_workflows_and_refusals(self) -> None:
        # 1. ste_status
        st = dispatch_operation({"op": "ste_status", "args": {}, "workspace_root": str(self.workspace)})
        self.assertTrue(st["ok"], st)
        self.assertTrue(st["result"]["available"])
        self.assertEqual(st["result"]["host_adapter"], OPENCODE_PLUGIN_ID)

        # 1b. Missing explicit workspace_root (and no STE_TRUSTED_WORKSPACE) must fail closed
        # rather than inferring workspace from Python process CWD or installed bundle root.
        with patch.dict(os.environ, {"STE_TRUSTED_WORKSPACE": ""}, clear=False):
            missing_ws_res = dispatch_operation({"op": "ste_status", "args": {}})
            self.assertFalse(missing_ws_res["ok"])
            self.assertEqual(missing_ws_res["error"]["code"], "invalid_input")
            self.assertIn("refusing to infer workspace", missing_ws_res["error"]["message"])
        for bad_arg in ("workspace_root", "state_dir", "runtime_config", "bypass", "python", "command"):
            bad_res = dispatch_operation(
                {
                    "op": "ste_write_artifact",
                    "args": {
                        "target_path": "artifacts/bad.md",
                        "content": "# Bad\n",
                        bad_arg: "injected",
                    },
                    "workspace_root": str(self.workspace),
                }
            )
            self.assertFalse(bad_res["ok"])
            self.assertEqual(bad_res["error"]["code"], "policy_refusal")

        # 3. Pre-write refusal for out-of-workspace, protected dirs, and forbidden extensions
        outside_sentinel = self.root / "outside-sentinel.md"
        out_res = dispatch_operation(
            {
                "op": "ste_write_artifact",
                "args": {"target_path": "../outside-sentinel.md", "content": "# Escape\n"},
                "workspace_root": str(self.workspace),
            }
        )
        self.assertFalse(out_res["ok"])
        self.assertEqual(out_res["error"]["code"], "policy_refusal")
        self.assertFalse(outside_sentinel.exists())

        for protected_rel in ("ste_promax/injected.md", ".opencode/injected.json", "pyproject.toml", "artifacts/hack.py"):
            prot_res = dispatch_operation(
                {
                    "op": "ste_write_artifact",
                    "args": {"target_path": protected_rel, "content": "# Blocked\n"},
                    "workspace_root": str(self.workspace),
                }
            )
            self.assertFalse(prot_res["ok"])
            self.assertEqual(prot_res["error"]["code"], "policy_refusal")
            self.assertFalse((self.workspace / protected_rel).exists())

        # 4. Guarded ste_write_artifact (new file + update with expected_before_sha256)
        write_res = dispatch_operation(
            {
                "op": "ste_write_artifact",
                "args": {
                    "target_path": "artifacts/doc-01/procedure.md",
                    "content": "# Pump Isolation\n\nClose the main inlet valve before maintenance.\n",
                },
                "workspace_root": str(self.workspace),
            }
        )
        self.assertTrue(write_res["ok"], write_res)
        written_file = self.workspace / "artifacts" / "doc-01" / "procedure.md"
        self.assertTrue(written_file.is_file())
        first_sha = write_res["result"]["sha256"]
        self.assertEqual(write_res["result"]["policy_receipt"]["verdict"], "ALLOW")

        # Updating without expected_before_sha256 is refused
        no_sha_res = dispatch_operation(
            {
                "op": "ste_write_artifact",
                "args": {
                    "target_path": "artifacts/doc-01/procedure.md",
                    "content": "# Updated\n",
                },
                "workspace_root": str(self.workspace),
            }
        )
        self.assertFalse(no_sha_res["ok"])
        self.assertEqual(no_sha_res["error"]["code"], "policy_refusal")

        # Updating with matching expected_before_sha256 succeeds
        upd_res = dispatch_operation(
            {
                "op": "ste_write_artifact",
                "args": {
                    "target_path": "artifacts/doc-01/procedure.md",
                    "content": "# Pump Isolation\n\nClose the main inlet valve and bleed residual pressure.\n",
                    "expected_before_sha256": first_sha,
                },
                "workspace_root": str(self.workspace),
            }
        )
        self.assertTrue(upd_res["ok"], upd_res)

        # 5. Guarded ste_render_bundle, ste_inspect_artifact, ste_export_bundle, and ste_check_prose
        bundle_res = dispatch_operation(
            {
                "op": "ste_render_bundle",
                "args": {
                    "input_path": "artifacts/doc-01/procedure.md",
                    "output_dir": "artifacts/bundle-01",
                    "title": "Pump Isolation Procedure",
                },
                "workspace_root": str(self.workspace),
            }
        )
        self.assertTrue(bundle_res["ok"], bundle_res)
        self.assertTrue((self.workspace / "artifacts" / "bundle-01" / "manifest.json").is_file())

        inspect_res = dispatch_operation(
            {
                "op": "ste_inspect_artifact",
                "args": {
                    "target_path": "artifacts/bundle-01",
                    "headless_browser": False,
                },
                "workspace_root": str(self.workspace),
            }
        )
        self.assertTrue(inspect_res["ok"], inspect_res)
        self.assertEqual(inspect_res["result"]["manifest_status"], "complete")
        self.assertEqual(inspect_res["result"]["inspection_mode"], "static-local-analysis")
        self.assertEqual(inspect_res["result"]["network_access"], "none-static-file-parse-only")
        self.assertFalse(inspect_res["result"]["in_app_preview"])

        # Headless browser option is explicitly rejected with unsupported_operation
        headless_res = dispatch_operation(
            {
                "op": "ste_inspect_artifact",
                "args": {
                    "target_path": "artifacts/bundle-01",
                    "headless_browser": True,
                },
                "workspace_root": str(self.workspace),
            }
        )
        self.assertFalse(headless_res["ok"])
        self.assertEqual(headless_res["error"]["code"], "unsupported_operation")

        export_res = dispatch_operation(
            {
                "op": "ste_export_bundle",
                "args": {
                    "input_dir": "artifacts/bundle-01",
                    "output_dir": "artifacts/exported-01",
                },
                "workspace_root": str(self.workspace),
            }
        )
        self.assertTrue(export_res["ok"], export_res)
        self.assertTrue((self.workspace / "artifacts" / "exported-01" / "manifest.json").is_file())

        prose_res = dispatch_operation(
            {
                "op": "ste_check_prose",
                "args": {
                    "text": "Close the inlet valve before removing the filter housing.",
                    "profile": "procedure",
                },
                "workspace_root": str(self.workspace),
            }
        )
        self.assertTrue(prose_res["ok"], prose_res)
        self.assertEqual(prose_res["result"]["policy_receipt"]["verdict"], "ALLOW")

        # 6. Missing SkillC runtime fails effectful operations closed before sentinel creation,
        # while turn preflight and post-stream prose diagnostics degrade gracefully for read-only help.
        missing_sentinel = self.workspace / "artifacts" / "missing-runtime-sentinel.md"
        with patch.dict(
            os.environ,
            {
                "STE_SKILLC_RUNTIME_CONFIG": str(self.root / "nonexistent-runtime.json"),
                "STE_SKILLC_FORCE_WORKER": "1",
            },
            clear=False,
        ):
            missing_write = dispatch_operation(
                {
                    "op": "ste_write_artifact",
                    "args": {
                        "target_path": "artifacts/missing-runtime-sentinel.md",
                        "content": "# Must Not Write\n",
                    },
                    "workspace_root": str(self.workspace),
                }
            )
            self.assertFalse(missing_write["ok"])
            self.assertEqual(missing_write["error"]["code"], "dependency_missing")
            self.assertFalse(missing_sentinel.exists())

            degraded_preflight = dispatch_operation(
                {
                    "op": "ste_preflight_turn",
                    "args": {"prompt_text": "Explain ASD-STE100 active voice rules."},
                    "workspace_root": str(self.workspace),
                }
            )
            self.assertTrue(degraded_preflight["ok"], degraded_preflight)
            self.assertEqual(degraded_preflight["result"]["status"], "degraded_readonly_only")
            self.assertTrue(degraded_preflight["result"]["readonly_help_permitted"])
            self.assertFalse(degraded_preflight["result"]["effectful_tools_permitted"])

            degraded_post = dispatch_operation(
                {
                    "op": "ste_postprocess_prose",
                    "args": {
                        "text": "Use active voice in procedural instructions.",
                        "profile": "procedure",
                    },
                    "workspace_root": str(self.workspace),
                }
            )
            self.assertTrue(degraded_post["ok"], degraded_post)
            self.assertEqual(degraded_post["result"]["status"], "checked_without_skillc_backend")
            self.assertFalse(degraded_post["result"]["pre_display_guaranteed"])

    def test_js_effect_plugin_scope_inheritance_and_hook_boundaries(self) -> None:
        node_bin = shutil.which("node") or shutil.which("bun")
        self.assertIsNotNone(node_bin, "Node or Bun is required to run JS plugin boundary tests.")

        core_url = (PLUGIN_DIR / "core.js").resolve().as_uri()
        js_test_script = f"""
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import {{
  STE_SKILL_IDS,
  STE_TOOL_NAMES,
  STE_TOOL_SCHEMAS,
  buildSteToolResultMetadata,
  createScopeManager,
  createSteOpenCodePlugin,
  evaluateSteToolIntercept,
  isExactSteSkillMdPath,
  isExplicitUserSteOff,
  isSteSkillIdentifier,
  readBundleSkills,
  scanContextMessagesForScope,
}} from {json.dumps(core_url)};

const ws = {json.dumps(str(self.workspace))};
const stateRoot = {json.dumps(str(self.state_root))};
const cleanEnv = {{ ...process.env, STE_SKILLC_STATE_ROOT: stateRoot }};
delete cleanEnv.STE_TRUSTED_WORKSPACE;

// 1. Bundled skills and top-level tool schema checks (options.codemode = false)
const skills = readBundleSkills();
assert.equal(skills.length, 4);
for (const id of STE_SKILL_IDS) {{
  assert.ok(skills.some((s) => s.id === id), `Missing bundled skill ${{id}}`);
}}
for (const toolName of STE_TOOL_NAMES) {{
  const schema = STE_TOOL_SCHEMAS[toolName];
  assert.ok(schema, `Missing schema for ${{toolName}}`);
  assert.equal(schema.input.additionalProperties, false);
  assert.ok(!("workspace_root" in (schema.input.properties || {{}})));
}}

// 1b. Honest tool result metadata verdict (never fabricate ALLOW when policy_receipt is absent/unavailable)
assert.deepEqual(
  buildSteToolResultMetadata("ste_status", {{ ok: true, result: {{ available: false, mode: "unavailable" }} }}),
  {{ ste_op: "ste_status", verdict: "unverified" }},
);
assert.deepEqual(
  buildSteToolResultMetadata("ste_status", {{ ok: true, result: {{ available: true, mode: "inprocess" }} }}),
  {{ ste_op: "ste_status", verdict: "not_applicable" }},
);
assert.deepEqual(
  buildSteToolResultMetadata("ste_write_artifact", {{ ok: true, result: {{ policy_receipt: {{ verdict: "ALLOW" }} }} }}),
  {{ ste_op: "ste_write_artifact", verdict: "ALLOW" }},
);

// 2. Scope manager: non-STE passthrough and no prompt keyword activation
const sessionInfos = new Map();
const sessionContexts = new Map();
const storageMap = new Map();

const mgr = createScopeManager({{
  defaultWorkspaceRoot: ws,
  env: cleanEnv,
  getSessionInfo: async (sid) => sessionInfos.get(sid) || null,
  getSessionContext: async (sid) => sessionContexts.get(sid) || [],
  storageGet: async (k) => storageMap.get(k),
  storageSet: async (k, v) => storageMap.set(k, v),
}});

// Random prompt words mentioning STE skills must NOT activate STE scope
const nonStePrompt = await mgr.handlePromptHook({{
  sessionID: "ses_non_ste",
  prompt: {{ text: "Please compare ste-promax and ste-visual-docs in plain prose." }},
}});
assert.equal(nonStePrompt.active, false);

const nonSteWrite = await mgr.handleExecuteBefore({{
  sessionID: "ses_non_ste",
  tool: "write",
  input: {{ path: "allowed.txt", content: "ok" }},
}});
assert.equal(nonSteWrite.allow, true);

// Non-STE parent spawning an external dsh/acp child must remain non-STE (unchanged passthrough)
sessionInfos.set("ses_non_ste_dsh_child", {{
  id: "ses_non_ste_dsh_child",
  parentID: "ses_non_ste",
  agent: "dsh",
  location: {{ directory: ws }},
}});
const nonSteExtScope = await mgr.isSessionScoped("ses_non_ste_dsh_child");
assert.equal(nonSteExtScope.active, false);
assert.ok(!nonSteExtScope.blockedExternalChild);
const nonSteExtShell = await mgr.handleExecuteBefore({{
  sessionID: "ses_non_ste_dsh_child",
  tool: "shell",
  input: {{ command: "echo allowed_in_non_ste" }},
}});
assert.equal(nonSteExtShell.allow, true);

// 3. Activate via prompt.skills and verify raw shell/write/edit/execute/PTY/GUI/ACP are refused
const stePrompt = await mgr.handlePromptHook({{
  sessionID: "ses_ste_parent",
  prompt: {{
    text: "Write a procedure.",
    skills: [{{ id: "ste-promax" }}],
  }},
}});
assert.equal(stePrompt.active, true);

for (const blockedTool of ["shell", "bash", "powershell", "execute", "write", "edit", "apply_patch", "pty_spawn", "cua-driver_snapshot", "opencode_worktree_remove", "res_add", "unknown_custom_tool"]) {{
  const dec = await mgr.handleExecuteBefore({{
    sessionID: "ses_ste_parent",
    tool: blockedTool,
    input: {{}},
  }});
  assert.equal(dec.allow, false, `Expected ${{blockedTool}} to be refused in STE scope`);
  assert.equal(dec.code, "policy_refusal");
}}

// Credential read is refused while normal read is allowed
const credRead = await mgr.handleExecuteBefore({{
  sessionID: "ses_ste_parent",
  tool: "read",
  input: {{ path: "~/.copilot/config.json" }},
}});
assert.equal(credRead.allow, false);

const normalRead = await mgr.handleExecuteBefore({{
  sessionID: "ses_ste_parent",
  tool: "read",
  input: {{ path: "README.md" }},
}});
assert.equal(normalRead.allow, true);

// Headless browser inspection is refused with unsupported_operation in execute.before
const headlessInspect = await mgr.handleExecuteBefore({{
  sessionID: "ses_ste_parent",
  tool: "ste_inspect_artifact",
  input: {{ target_path: "artifacts/bundle-01", headless_browser: true }},
}});
assert.equal(headlessInspect.allow, false);
assert.equal(headlessInspect.code, "unsupported_operation");

// 4. Parent-to-child inheritance via session.get(parentID) and resumed subagent child
sessionInfos.set("ses_native_child", {{
  id: "ses_native_child",
  parentID: "ses_ste_parent",
  agent: "fixer",
  location: {{ directory: ws }},
}});
const childScope = await mgr.isSessionScoped("ses_native_child");
assert.equal(childScope.active, true);
assert.match(childScope.reason, /inherited_from:ses_ste_parent/);

const childShell = await mgr.handleExecuteBefore({{
  sessionID: "ses_native_child",
  tool: "shell",
  input: {{ command: "echo child" }},
}});
assert.equal(childShell.allow, false);

// External ACP subagent spawn is refused and cannot masquerade as a native child
const acpSpawn = await mgr.handleExecuteBefore({{
  sessionID: "ses_ste_parent",
  tool: "subagent",
  input: {{ agent: "dsh", prompt: "run external acp", sessionID: "ses_fake_child" }},
}});
assert.equal(acpSpawn.allow, false);

// STE-scoped parent with an external dsh/acp child session is blocked
sessionInfos.set("ses_ste_dsh_child", {{
  id: "ses_ste_dsh_child",
  parentID: "ses_ste_parent",
  agent: "dsh",
  location: {{ directory: ws }},
}});
const steExtScope = await mgr.isSessionScoped("ses_ste_dsh_child");
assert.equal(steExtScope.active, true);
assert.equal(steExtScope.blockedExternalChild, true);
const steExtRead = await mgr.handleExecuteBefore({{
  sessionID: "ses_ste_dsh_child",
  tool: "read",
  input: {{ path: "README.md" }},
}});
assert.equal(steExtRead.allow, false);

// Native subagent resume binds STE scope to the resumed child session
const nativeResume = await mgr.handleExecuteBefore({{
  sessionID: "ses_ste_parent",
  tool: "subagent",
  input: {{ agent: "explorer", prompt: "inspect files", sessionID: "ses_resumed_child" }},
}});
assert.equal(nativeResume.allow, true);
const resumedScope = await mgr.isSessionScoped("ses_resumed_child");
assert.equal(resumedScope.active, true);

// 4b. Malformed parent cycle and deep ancestor chain (>8 hops from STE ancestor)
// must fail closed for effectful tools while keeping read-only diagnosis available
sessionInfos.set("ses_cycle_a", {{ id: "ses_cycle_a", parentID: "ses_cycle_b", location: {{ directory: ws }} }});
sessionInfos.set("ses_cycle_b", {{ id: "ses_cycle_b", parentID: "ses_cycle_a", location: {{ directory: ws }} }});
const cycleScope = await mgr.isSessionScoped("ses_cycle_a");
assert.equal(cycleScope.active, true);
assert.equal(cycleScope.uncertainScope, true);
assert.match(cycleScope.reason, /ancestor_cycle_detected/);

const cycleWrite = await mgr.handleExecuteBefore({{
  sessionID: "ses_cycle_a",
  tool: "write",
  input: {{ path: "cycle-write.md", content: "blocked" }},
}});
assert.equal(cycleWrite.allow, false);
const cycleSteWrite = await mgr.handleExecuteBefore({{
  sessionID: "ses_cycle_a",
  tool: "ste_write_artifact",
  input: {{ target_path: "artifacts/cycle.md", content: "blocked" }},
}});
assert.equal(cycleSteWrite.allow, false);
const cycleStatus = await mgr.handleExecuteBefore({{
  sessionID: "ses_cycle_a",
  tool: "ste_status",
  input: {{}},
}});
assert.equal(cycleStatus.allow, true);
const cycleRead = await mgr.handleExecuteBefore({{
  sessionID: "ses_cycle_a",
  tool: "read",
  input: {{ path: "README.md" }},
}});
assert.equal(cycleRead.allow, true);

// Deep native descendant chain (10 hops from ses_ste_parent)
let prevId = "ses_ste_parent";
for (let i = 1; i <= 10; i++) {{
  const curId = `ses_deep_${{i}}`;
  sessionInfos.set(curId, {{ id: curId, parentID: prevId, agent: "fixer", location: {{ directory: ws }} }});
  prevId = curId;
}}
const deepScope = await mgr.isSessionScoped("ses_deep_10");
assert.equal(deepScope.active, true);
assert.equal(deepScope.uncertainScope, true);
assert.match(deepScope.reason, /ancestor_depth_limit_exceeded/);
const deepWrite = await mgr.handleExecuteBefore({{
  sessionID: "ses_deep_10",
  tool: "write",
  input: {{ path: "deep-write.md", content: "blocked" }},
}});
assert.equal(deepWrite.allow, false);
const deepShell = await mgr.handleExecuteBefore({{
  sessionID: "ses_deep_10",
  tool: "shell",
  input: {{ command: "echo blocked" }},
}});
assert.equal(deepShell.allow, false);
const deepStatus = await mgr.handleExecuteBefore({{
  sessionID: "ses_deep_10",
  tool: "ste_status",
  input: {{}},
}});
assert.equal(deepStatus.allow, true);

// 5. Reload recovery from typed ctx.session.context records (SessionMessage.Skill / User.skills)
const freshMgr = createScopeManager({{
  defaultWorkspaceRoot: ws,
  env: cleanEnv,
  getSessionInfo: async (sid) => sessionInfos.get(sid) || null,
  getSessionContext: async (sid) => sessionContexts.get(sid) || [],
}});

// Disk recovery for ses_ste_parent
const recoveredDisk = await freshMgr.isSessionScoped("ses_ste_parent");
assert.equal(recoveredDisk.active, true);

// Typed context message recovery for a session whose disk record was not yet written
sessionContexts.set("ses_context_recovery", [
  {{ type: "user", id: "msg_1", text: "Help with diagram", time: {{ created: 1 }} }},
  {{ type: "skill", id: "msg_2", skill: "ste-line-studio", name: "ste-line-studio", text: "...", time: {{ created: 2 }} }},
]);
const recoveredCtx = await freshMgr.isSessionScoped("ses_context_recovery");
assert.equal(recoveredCtx.active, true);
assert.equal(recoveredCtx.reason, "context:skill:ste-line-studio");

// 6. Post-stream session.text.ended prose diagnostic
const diag = await freshMgr.handleServerEvent({{
  type: "session.text.ended",
  data: {{
    sessionID: "ses_ste_parent",
    assistantMessageID: "msg_asst_1",
    ordinal: 0,
    text: "Close the inlet valve before removing the filter housing.",
  }},
}});
assert.ok(diag);
assert.equal(diag.status, "checked");
assert.equal(diag.delivery_timing, "post_stream_advisory");
assert.equal(diag.pre_display_guaranteed, false);
assert.equal(diag.policy_receipt.verdict, "ALLOW");

// 7. Explicit user /ste-off ends scope
await freshMgr.handlePromptHook({{
  sessionID: "ses_ste_parent",
  prompt: {{ text: "/ste-off" }},
}});
const afterOff = await freshMgr.isSessionScoped("ses_ste_parent");
assert.equal(afterOff.active, false);

// 8. Verify createSteOpenCodePlugin Effect registration & Tool.Error failure channel
class MockToolError extends Error {{
  constructor(opts) {{
    super(opts.message);
    this._tag = "Tool.Error";
    this.metadata = opts.metadata;
  }}
}}
const makeEffect = (val) => ({{
  val,
  *[Symbol.iterator]() {{
    return yield val;
  }},
}});
const mockEffectApi = {{
  gen: (genFn) => () => {{
    const it = genFn();
    let step = it.next();
    while (!step.done) {{
      step = it.next(step.value);
    }}
    return step.value;
  }},
  context: () => makeEffect({{ _mockRuntime: true }}),
  runPromiseWith: () => (val) => Promise.resolve(val),
  tryPromise: ({{ try: tryFn, catch: catchFn }}) => ({{
    pipe: (fn) => fn({{ tryFn, catchFn }}),
  }}),
  flatMap: (mapper) => async (src) => {{
    try {{
      const val = await src.tryFn();
      return await mapper(val);
    }} catch (err) {{
      return {{ _failed: true, error: src.catchFn(err) }};
    }}
  }},
  succeed: (val) => ({{ _failed: false, value: val }}),
  fail: (err) => ({{ _failed: true, error: err }}),
  void: {{ _failed: false, value: undefined }},
  promise: (fn) => fn,
  ignore: (x) => x,
  forkScoped: (x) => x,
}};
const addedTools = new Map();
const addedCommands = new Map();
const addedSkills = new Map();
const toolHooks = new Map();

const pluginDef = createSteOpenCodePlugin({{
  PluginApi: {{ define: (x) => x }},
  ToolErrorClass: MockToolError,
  EffectApi: mockEffectApi,
  StreamApi: {{}},
}});
assert.equal(pluginDef.id, "ste-promax");
pluginDef.effect({{
  location: {{ directory: ws }},
  skill: {{ transform: (cb) => makeEffect(cb({{ get: (id) => addedSkills.get(id), add: (s) => addedSkills.set(s.id, s) }})) }},
  tool: {{
    transform: (cb) => makeEffect(cb({{ add: (t) => addedTools.set(t.name, t) }})),
    hook: (name, cb) => makeEffect(toolHooks.set(name, cb)),
  }},
  command: {{ transform: (cb) => makeEffect(cb({{ add: (c) => addedCommands.set(c.name, c) }})) }},
  session: {{
    get: async (inp) => sessionInfos.get(inp.sessionID) || null,
    context: async (inp) => sessionContexts.get(inp.sessionID) || [],
    hook: () => makeEffect({{}}),
  }},
}})();

assert.equal(addedSkills.size, 4);
assert.equal(addedTools.size, 10);
for (const [tName, tDef] of addedTools.entries()) {{
  assert.deepEqual(tDef.options, {{ codemode: false }}, `Tool ${{tName}} must set codemode: false`);
}}
assert.ok(addedCommands.has("ste-off"));
assert.ok(toolHooks.has("execute.before"));

const execBefore = toolHooks.get("execute.before");
// Activate ses_plugin_hook via skill(id: "ste-promax")
const skillHookRes = await execBefore({{
  sessionID: "ses_plugin_hook",
  tool: "skill",
  input: {{ id: "ste-promax" }},
}});
assert.equal(skillHookRes._failed, false);

// Now shell must fail with MockToolError (_tag === "Tool.Error")
const shellHookRes = await execBefore({{
  sessionID: "ses_plugin_hook",
  tool: "shell",
  input: {{ command: "echo blocked" }},
}});
assert.equal(shellHookRes._failed, true);
assert.ok(shellHookRes.error instanceof MockToolError);
assert.equal(shellHookRes.error._tag, "Tool.Error");

// Verify ste_status tool execution when runtime is missing does NOT fabricate verdict: "ALLOW"
const prevCfg = process.env.STE_SKILLC_RUNTIME_CONFIG;
process.env.STE_SKILLC_RUNTIME_CONFIG = path.join(ws, "nonexistent-runtime.json");
try {{
  const statusTool = addedTools.get("ste_status");
  const statusExecRes = await statusTool.execute({{}}, {{ sessionID: "ses_plugin_hook" }});
  assert.equal(statusExecRes._failed, false);
  assert.equal(statusExecRes.value.metadata.ste_op, "ste_status");
  assert.equal(statusExecRes.value.metadata.verdict, "unverified");
  assert.notEqual(statusExecRes.value.metadata.verdict, "ALLOW");
}} finally {{
  if (prevCfg === undefined) {{
    delete process.env.STE_SKILLC_RUNTIME_CONFIG;
  }} else {{
    process.env.STE_SKILLC_RUNTIME_CONFIG = prevCfg;
  }}
}}

console.log("JS_BOUNDARY_TESTS_OK");
"""
        js_file = self.root / "boundary_test.mjs"
        js_file.write_text(js_test_script, encoding="utf-8")
        proc = subprocess.run(
            [str(node_bin), str(js_file)],
            cwd=str(self.workspace),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=45,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
        self.assertIn("JS_BOUNDARY_TESTS_OK", proc.stdout)


@unittest.skipUnless(
    _host_cli_tests_enabled() and OPENCODE_CLI_EXE is not None and OPENCODE_CLI_EXE.is_file(),
    "Real OpenCode CLI loopback tests require STE_RUN_HOST_CLI_TESTS=1 and an available OpenCode CLI binary.",
)
class OpenCodeV2LiveLoopbackTests(unittest.TestCase):
    """Real OpenCode 2.2.6 (`opencode-cli` / `opencode-cli.exe --standalone`) end-to-end validation with retained evidence."""

    def test_real_opencode_v2_end_to_end_with_retained_artifacts(self) -> None:
        assert OPENCODE_CLI_EXE is not None
        self.assertTrue(
            OPENCODE_CLI_EXE.is_file(),
            f"OpenCode 2.2.6 CLI executable not found: {OPENCODE_CLI_EXE}",
        )

        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        retained_dir = REPO_ROOT / "artifacts" / f"opencode-v2-validation-{ts}-{secrets.token_hex(4)}"
        retained_dir.mkdir(parents=True, exist_ok=False)

        # Keep the OpenCode runtime home under the approved short temp directory so Windows
        # named pipes / SQLite paths stay compact, and copy all logs/evidence into retained_dir.
        APPROVED_TEMP_BASE.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="oc-live-", dir=str(APPROVED_TEMP_BASE)) as tmp_home:
            sandbox_root = Path(tmp_home).resolve()
            workspace = sandbox_root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            policy_state = sandbox_root / "policy-state"
            policy_state.mkdir(parents=True, exist_ok=True)

            # Create an installed bundle copy inside the sandbox (never loading from dev repo path)
            installed_bundle = sandbox_root / "installed-plugin" / "ste-pro-max"
            installed_bundle.mkdir(parents=True, exist_ok=True)
            for rel_dir in ("ste_promax", "integrations", "skills", "examples", "docs", "ste-promax"):
                shutil.copytree(REPO_ROOT / rel_dir, installed_bundle / rel_dir)
            for rel_file in ("plugin.json", "mcp.json", "__main__.py", "quickstart.py", "pyproject.toml", "README.md", "DESIGN.md", "LICENSE", "NOTICE"):
                shutil.copy2(REPO_ROOT / rel_file, installed_bundle / rel_file)

            installed_opencode_plugin_dir = installed_bundle / "integrations" / "opencode"

            # Seed workspace source file
            source_doc = workspace / "source-note.md"
            source_doc.write_text(
                "# Hydraulic Pressure Check\n\nCheck the pressure gauge before opening the relief valve.\n",
                encoding="utf-8",
            )

            # Sentinels that must NEVER exist
            sentinel_raw_shell = workspace / "sentinel-raw-shell.txt"
            sentinel_raw_write = workspace / "sentinel-raw-write.md"
            sentinel_outside = sandbox_root / "sentinel-outside-root.md"
            sentinel_after_reload = workspace / "sentinel-after-reload.md"

            scenario_state: dict[str, Any] = {
                "mode": "non_ste",
                "step": 0,
                "requests": [],
            }

            class LoopbackOpenAIHandler(http.server.BaseHTTPRequestHandler):
                def log_message(self, *args: Any) -> None:
                    pass

                def do_POST(self) -> None:
                    length = int(self.headers.get("Content-Length", 0))
                    raw_body = self.rfile.read(length).decode("utf-8", errors="replace")
                    body = json.loads(raw_body) if raw_body.startswith("{") else {}

                    # Auxiliary title requests carry no tools
                    if not body.get("tools"):
                        self.send_response(200)
                        self.send_header("Content-Type", "text/event-stream")
                        self.end_headers()
                        self.wfile.write(_make_text_sse("STE Validation Session"))
                        self.wfile.flush()
                        return

                    scenario_state["step"] += 1
                    step = scenario_state["step"]
                    mode = scenario_state["mode"]
                    tools_offered = [
                        t.get("function", {}).get("name")
                        for t in body.get("tools", [])
                    ]
                    tool_messages = [
                        m.get("content", "")
                        for m in body.get("messages", [])
                        if isinstance(m, dict) and m.get("role") == "tool"
                    ]
                    scenario_state["requests"].append(
                        {
                            "mode": mode,
                            "step": step,
                            "tools_offered": tools_offered,
                            "last_message": body.get("messages", [])[-1] if body.get("messages") else None,
                            "tool_messages": tool_messages,
                        }
                    )

                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()

                    if mode == "non_ste":
                        if step == 1:
                            payload = _make_tool_call_sse(
                                "call_non_ste_write",
                                "write",
                                {
                                    "path": str(workspace / "non-ste-allowed.txt"),
                                    "content": "NON_STE_PASSTHROUGH_OK\n",
                                },
                            )
                        else:
                            payload = _make_text_sse("NON_STE_COMPLETE")

                    elif mode == "ste_main":
                        if step == 1:
                            # 1. Activate STE scope via real `skill` tool
                            payload = _make_tool_call_sse(
                                "call_ste_skill",
                                "skill",
                                {"id": "ste-promax"},
                            )
                        elif step == 2:
                            # 2. Check ste_status to verify workspace_root is bound from OpenCode session/location (not bundle root)
                            payload = _make_tool_call_sse(
                                "call_ste_status",
                                "ste_status",
                                {},
                            )
                        elif step == 3:
                            # 3. Attempt raw shell -> must be denied by V2 Effect execute.before
                            payload = _make_tool_call_sse(
                                "call_raw_shell",
                                "shell",
                                {"command": f"echo PWNED > {sentinel_raw_shell}"},
                            )
                        elif step == 4:
                            # 4. Attempt raw write -> must be denied by V2 Effect execute.before
                            payload = _make_tool_call_sse(
                                "call_raw_write",
                                "write",
                                {"path": str(sentinel_raw_write), "content": "PWNED\n"},
                            )
                        elif step == 5:
                            # 5. Attempt raw edit -> must be denied by V2 Effect execute.before
                            payload = _make_tool_call_sse(
                                "call_raw_edit",
                                "edit",
                                {
                                    "path": str(source_doc),
                                    "oldString": "Check",
                                    "newString": "PWNED",
                                },
                            )
                        elif step == 6:
                            # 6. Attempt Code Mode `execute` -> must be denied by V2 Effect execute.before
                            payload = _make_tool_call_sse(
                                "call_code_mode",
                                "execute",
                                {"code": "return 'bypass'"},
                            )
                        elif step == 7:
                            # 7. Attempt out-of-workspace ste_write_artifact -> must be denied before write
                            payload = _make_tool_call_sse(
                                "call_ste_outside",
                                "ste_write_artifact",
                                {
                                    "target_path": "../sentinel-outside-root.md",
                                    "content": "# Escaped\n",
                                },
                            )
                        elif step == 8:
                            # 8. Valid guarded ste_write_artifact -> must succeed automatically
                            payload = _make_tool_call_sse(
                                "call_ste_write",
                                "ste_write_artifact",
                                {
                                    "target_path": "artifacts/oc-live-doc/valve-procedure.md",
                                    "content": (
                                        "# Relief Valve Inspection\n\n"
                                        "Check the pressure gauge before opening the relief valve.\n"
                                    ),
                                },
                            )
                        elif step == 9:
                            # 9. Valid guarded ste_render_bundle -> must succeed automatically
                            payload = _make_tool_call_sse(
                                "call_ste_render",
                                "ste_render_bundle",
                                {
                                    "input_path": "source-note.md",
                                    "output_dir": "artifacts/oc-live-bundle",
                                    "title": "Hydraulic Pressure Check",
                                },
                            )
                        elif step == 10:
                            # 10. Valid guarded ste_inspect_artifact -> must succeed automatically
                            payload = _make_tool_call_sse(
                                "call_ste_inspect",
                                "ste_inspect_artifact",
                                {
                                    "target_path": "artifacts/oc-live-bundle",
                                    "headless_browser": False,
                                },
                            )
                        else:
                            payload = _make_text_sse(
                                "Check the pressure gauge before opening the relief valve."
                            )

                    elif mode == "ste_reload_resume":
                        if step == 1:
                            # In a brand new process continuing the same session ID,
                            # raw write must STILL be denied without re-calling `skill`!
                            payload = _make_tool_call_sse(
                                "call_reload_write",
                                "write",
                                {"path": str(sentinel_after_reload), "content": "PWNED_AFTER_RELOAD\n"},
                            )
                        elif step == 2:
                            payload = _make_tool_call_sse(
                                "call_reload_prose",
                                "ste_check_prose",
                                {
                                    "text": "Check the pressure gauge before opening the relief valve.",
                                    "profile": "procedure",
                                },
                            )
                        else:
                            payload = _make_text_sse("RELOAD_VERIFIED")
                    else:
                        payload = _make_text_sse("DONE")

                    self.wfile.write(payload)
                    self.wfile.flush()

            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), LoopbackOpenAIHandler)
            port = server.server_address[1]
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)

            cfg_dir = sandbox_root / ".config" / "opencode"
            cfg_dir.mkdir(parents=True, exist_ok=True)
            opencode_cfg = {
                "model": "mock-local/ste-test-model",
                "plugins": [str(installed_opencode_plugin_dir)],
                "providers": {
                    "mock-local": {
                        "name": "Mock Local",
                        "package": "@opencode/ai/providers/openai-compatible",
                        "settings": {"baseURL": f"http://127.0.0.1:{port}/v1"},
                        "models": {
                            "ste-test-model": {
                                "name": "STE Test Model",
                                "capabilities": {
                                    "tools": True,
                                    "input": ["text"],
                                    "output": ["text"],
                                },
                            }
                        },
                    }
                },
            }
            (cfg_dir / "opencode.json").write_text(json.dumps(opencode_cfg, indent=2), encoding="utf-8")

            env = dict(os.environ)
            env["USERPROFILE"] = str(sandbox_root)
            env["HOME"] = str(sandbox_root)
            env["OPENCODE_TEST_HOME"] = str(sandbox_root)
            env["OPENCODE_CONFIG_DIR"] = str(cfg_dir)
            env["XDG_CONFIG_HOME"] = str(sandbox_root / ".config")
            env["XDG_DATA_HOME"] = str(sandbox_root / ".local" / "share")
            env["XDG_STATE_HOME"] = str(sandbox_root / ".local" / "state")
            env["XDG_CACHE_HOME"] = str(sandbox_root / ".cache")
            env["STE_SKILLC_STATE_ROOT"] = str(policy_state)
            # Do NOT set STE_TRUSTED_WORKSPACE here: real OpenCode loopback tests must
            # exercise genuine ctx.session.get(sessionID).location.directory / ctx.location.directory binding!
            env.pop("STE_TRUSTED_WORKSPACE", None)

            # --- Run 1: Non-STE passthrough (prompt mentions STE-ProMAX in text, must NOT activate STE) ---
            scenario_state["mode"] = "non_ste"
            scenario_state["step"] = 0
            proc_non_ste = subprocess.run(
                [
                    str(OPENCODE_CLI_EXE),
                    "run",
                    "--standalone",
                    "--auto",
                    "--format",
                    "json",
                    "Hello, we might discuss STE-ProMAX later, please write non-ste-allowed.txt.",
                ],
                cwd=str(workspace),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                check=False,
            )
            (retained_dir / "run1-non-ste.stdout.jsonl").write_text(proc_non_ste.stdout, encoding="utf-8")
            (retained_dir / "run1-non-ste.stderr.log").write_text(proc_non_ste.stderr, encoding="utf-8")
            self.assertEqual(proc_non_ste.returncode, 0, proc_non_ste.stderr)
            self.assertTrue((workspace / "non-ste-allowed.txt").is_file())

            # --- Run 2: STE workflow + Effect execute.before denials + guarded write/render/inspect ---
            scenario_state["mode"] = "ste_main"
            scenario_state["step"] = 0
            proc_ste = subprocess.run(
                [
                    str(OPENCODE_CLI_EXE),
                    "run",
                    "--standalone",
                    "--auto",
                    "--format",
                    "json",
                    "Execute STE workflow.",
                ],
                cwd=str(workspace),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=90,
                check=False,
            )
            (retained_dir / "run2-ste-main.stdout.jsonl").write_text(proc_ste.stdout, encoding="utf-8")
            (retained_dir / "run2-ste-main.stderr.log").write_text(proc_ste.stderr, encoding="utf-8")
            self.assertEqual(proc_ste.returncode, 0, proc_ste.stderr)

            # Extract sessionID from Run 2 JSON output
            ste_session_id = None
            for line in proc_ste.stdout.splitlines():
                if not line.strip().startswith("{"):
                    continue
                ev = json.loads(line)
                if isinstance(ev.get("sessionID"), str):
                    ste_session_id = ev["sessionID"]
                    break
            self.assertIsNotNone(ste_session_id, "Failed to extract sessionID from OpenCode JSON output.")

            # Verify sentinels were NEVER created
            self.assertFalse(sentinel_raw_shell.exists(), "Raw shell sentinel must not exist!")
            self.assertFalse(sentinel_raw_write.exists(), "Raw write sentinel must not exist!")
            self.assertFalse(sentinel_outside.exists(), "Outside-workspace sentinel must not exist!")
            self.assertIn(
                "Check the pressure gauge",
                source_doc.read_text(encoding="utf-8"),
                "Raw edit must not have modified source-note.md!",
            )

            # Verify guarded artifact write and bundle render succeeded
            written_doc = workspace / "artifacts" / "oc-live-doc" / "valve-procedure.md"
            bundle_dir = workspace / "artifacts" / "oc-live-bundle"
            self.assertTrue(written_doc.is_file())
            self.assertTrue((bundle_dir / "manifest.json").is_file())
            self.assertTrue((bundle_dir / "gallery.html").is_file())

            # --- Run 3: Reload / resume recovery in a new `--standalone` process (`--session <ste_session_id>`) ---
            scenario_state["mode"] = "ste_reload_resume"
            scenario_state["step"] = 0
            proc_reload = subprocess.run(
                [
                    str(OPENCODE_CLI_EXE),
                    "run",
                    "--standalone",
                    "--auto",
                    "--format",
                    "json",
                    "--session",
                    str(ste_session_id),
                    "Continue STE session after reload.",
                ],
                cwd=str(workspace),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                check=False,
            )
            (retained_dir / "run3-ste-reload.stdout.jsonl").write_text(proc_reload.stdout, encoding="utf-8")
            (retained_dir / "run3-ste-reload.stderr.log").write_text(proc_reload.stderr, encoding="utf-8")
            self.assertEqual(proc_reload.returncode, 0, proc_reload.stderr)
            self.assertFalse(
                sentinel_after_reload.exists(),
                "Raw write after reload must be denied by recovered STE scope!",
            )

            # Save full request log and copy artifacts/policy-state into retained_dir
            (retained_dir / "mock-provider-requests.json").write_text(
                json.dumps(scenario_state["requests"], indent=2),
                encoding="utf-8",
            )
            shutil.copytree(workspace / "artifacts", retained_dir / "workspace-artifacts")
            shutil.copytree(policy_state, retained_dir / "policy-state")

            # Verify Tool.Error messages were received by the model for each denied tool
            ste_reqs = [r for r in scenario_state["requests"] if r["mode"] == "ste_main"]
            self.assertGreaterEqual(len(ste_reqs), 11)
            # Top-level STE tools must be offered in tool definitions
            for tool_name in STE_TOOL_NAMES:
                self.assertIn(tool_name, ste_reqs[0]["tools_offered"])

            # Verify ste_status returned actual caller workspace_root (from ctx.session.get / ctx.location)
            # and bundle_root from installed_bundle (never confusing the two!)
            status_tool_outputs = []
            for r in ste_reqs:
                for raw_msg in r.get("tool_messages", []):
                    if isinstance(raw_msg, str) and '"host_adapter": "ste-promax"' in raw_msg:
                        status_tool_outputs.append(json.loads(raw_msg))
            self.assertTrue(status_tool_outputs, "Expected ste_status tool output in ste_main transcript.")
            status_res = status_tool_outputs[0]["result"]
            self.assertEqual(Path(status_res["workspace_root"]).resolve(), workspace.resolve())
            self.assertEqual(Path(status_res["bundle_root"]).resolve(), installed_bundle.resolve())
            self.assertNotEqual(
                Path(status_res["workspace_root"]).resolve(),
                Path(status_res["bundle_root"]).resolve(),
            )

            combined_feedback = "\n".join(
                str(msg)
                for r in ste_reqs
                for msg in r.get("tool_messages", [])
            )
            self.assertIn('STE-Pro-Max policy refuses raw shell/Code Mode/PTY tool \\"shell\\"', combined_feedback)
            self.assertIn('STE-Pro-Max policy refuses raw file mutation tool \\"write\\"', combined_feedback)
            self.assertIn('STE-Pro-Max policy refuses raw file mutation tool \\"edit\\"', combined_feedback)
            self.assertIn('STE-Pro-Max policy refuses raw shell/Code Mode/PTY tool \\"execute\\"', combined_feedback)
            self.assertIn("must not contain '..' traversal segments", combined_feedback)

            reload_reqs = [r for r in scenario_state["requests"] if r["mode"] == "ste_reload_resume"]
            self.assertGreaterEqual(len(reload_reqs), 3)
            reload_feedback = "\n".join(
                str(msg)
                for r in reload_reqs
                for msg in r.get("tool_messages", [])
            )
            self.assertIn('STE-Pro-Max policy refuses raw file mutation tool \\"write\\"', reload_feedback)
            self.assertIn("prose_advisory_checked", reload_feedback)


if __name__ == "__main__":
    unittest.main()

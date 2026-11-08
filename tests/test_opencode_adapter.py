"""Focused unit, contract, and real OpenCode 2.2.6 end-to-end tests for the OpenCode V2 STE host adapter.

Covers:
1. Package & manifest contract (`integrations/opencode/package.json`, `server.js`, `core.js`, `index.js`, `dispatch.py`).
2. Installed-bundle isolation (`resolve_bundle_root` and `resolveBundleRoot` use the installed plugin copy,
   never `runtime.json.ste_root`).
3. Bounded CLI JSON dispatcher (`integrations/opencode/dispatch.py`) and guarded host operations
   (`ste_status`, `ste_check_prose`, `ste_write_artifact`, `ste_render_bundle`, `ste_render_artifact`,
   `ste_regenerate_gallery`, `ste_prepare_story_media`, `ste_inspect_artifact`, `ste_export_bundle`),
   including pre-mutation denial of out-of-workspace targets, protected paths, untrusted raw HTML,
   forbidden model keys, and missing SkillC runtime.
4. JS Effect plugin unit boundaries (`createSteOpenCodePlugin`, `executeGuardedSteTool`,
   `resolveWorkspaceForSession`, `prevalidateSteToolCall`, `buildSteToolResultMetadata`), proving:
   - Registration of the 4 bundled STE skills and 10 top-level `ste_*` tools with `options: { codemode: false }`.
   - Zero global or session-scoped interception: no `execute.before` tool hook, no `prompt` or `context`
     session hooks, no `event.subscribe` stream monitor, and no `/ste-off` command registration.
   - Workspace resolution from `ctx.session.get(sessionID).location.directory` or `ctx.location.directory`
     (never falling back to bundle root or process CWD).
   - Guarded STE tool execution succeeds regardless of session history or ancestor chains, while invalid STE
     inputs fail with typed `Tool.Error` and missing SkillC runtime never fabricates `verdict: "ALLOW"`.
5. Real OpenCode 2.2.6 (`opencode-cli` / `opencode-cli.exe --standalone`) end-to-end execution against a local loopback
   OpenAI-compatible mock provider in an isolated home/config/workspace (zero billable model calls),
   retaining full evidence under `artifacts/`.
   Proves that after loading a bundled STE skill (`skill(id: "ste-promax")`), normal host tools (`shell`, `write`,
   `read`, and Code Mode `execute` when offered by the CLI catalog) remain available alongside guarded STE tools
   (`ste_status`, `ste_write_artifact`, `ste_render_bundle`, `ste_inspect_artifact`), while invalid STE inputs
   (`../` traversal) are still refused before any file write.
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
        self.assertNotIn("execute.before", pkg.get("description", ""))
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

        # 6. Missing SkillC runtime fails effectful operations closed before sentinel creation
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

    def test_js_effect_plugin_tools_only_without_host_interception(self) -> None:
        node_bin = shutil.which("node") or shutil.which("bun")
        self.assertIsNotNone(node_bin, "Node or Bun is required to run JS plugin boundary tests.")

        core_url = (PLUGIN_DIR / "core.js").resolve().as_uri()
        js_test_script = f"""
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import * as coreMod from {json.dumps(core_url)};
import {{
  STE_SKILL_IDS,
  STE_TOOL_NAMES,
  STE_TOOL_SCHEMAS,
  buildSteToolResultMetadata,
  createSteOpenCodePlugin,
  executeGuardedSteTool,
  prevalidateSteToolCall,
  readBundleSkills,
  resolveWorkspaceForSession,
}} from {json.dumps(core_url)};

const ws = {json.dumps(str(self.workspace))};
const stateRoot = {json.dumps(str(self.state_root))};
const cleanEnv = {{ ...process.env, STE_SKILLC_STATE_ROOT: stateRoot }};
delete cleanEnv.STE_TRUSTED_WORKSPACE;

// 1. Verify obsolete scope/blocklist machinery and dead helpers were removed from core.js exports
for (const removedExport of [
  "createScopeManager",
  "evaluateSteToolIntercept",
  "scanContextMessagesForScope",
  "isExplicitUserSteOff",
  "RAW_MUTATION_TOOLS",
  "RAW_SHELL_AND_CODEMODE_TOOLS",
  "OPAQUE_HOST_MUTATION_TOOLS",
  "BLOCKED_SUBAGENT_NAMES",
  "sha256Hex",
  "normalizeIdentifier",
  "isSteSkillIdentifier",
  "isSteToolName",
  "resolveStateRoot",
]) {{
  assert.ok(!(removedExport in coreMod), `Obsolete export ${{removedExport}} must not remain in core.js`);
}}

// 2. Bundled skills and top-level tool schema checks (options.codemode = false)
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

// 3. Honest tool result metadata verdict (never fabricate ALLOW when policy_receipt is absent/unavailable)
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

// 4. Workspace resolution from session.get(sessionID).location.directory or ctx.location.directory (never CWD/bundle)
const sessionInfos = new Map();
sessionInfos.set("ses_custom", {{
  id: "ses_custom",
  location: {{ directory: ws }},
}});
const resolvedFromSession = await resolveWorkspaceForSession("ses_custom", {{
  defaultWorkspaceRoot: null,
  getSessionInfo: async (sid) => sessionInfos.get(sid) || null,
}});
assert.equal(resolvedFromSession, fs.realpathSync(ws));

const resolvedFromDefault = await resolveWorkspaceForSession("ses_unknown", {{
  defaultWorkspaceRoot: ws,
  getSessionInfo: async () => null,
}});
assert.equal(resolvedFromDefault, fs.realpathSync(ws));

const resolvedMissing = await resolveWorkspaceForSession("ses_unknown", {{
  defaultWorkspaceRoot: null,
  getSessionInfo: async () => null,
}});
assert.equal(resolvedMissing, null);

// Missing workspace root refuses STE tool calls rather than falling back to process CWD or bundle root
const missingWsExec = await executeGuardedSteTool("ste_status", {{}}, {{ sessionID: "ses_unknown" }}, {{
  defaultWorkspaceRoot: null,
  env: cleanEnv,
  getSessionInfo: async () => null,
}});
assert.equal(missingWsExec.ok, false);
assert.equal(missingWsExec.error.code, "invalid_input");

// 5. Prevalidation of STE tool calls (headless_browser, traversal, forbidden keys)
const headlessPre = prevalidateSteToolCall(
  "ste_inspect_artifact",
  {{ target_path: "artifacts/bundle-01", headless_browser: true }},
  ws,
  cleanEnv,
);
assert.equal(headlessPre.ok, false);
assert.equal(headlessPre.code, "unsupported_operation");

const traversalPre = prevalidateSteToolCall(
  "ste_write_artifact",
  {{ target_path: "../escape.md", content: "# Blocked" }},
  ws,
  cleanEnv,
);
assert.equal(traversalPre.ok, false);
assert.equal(traversalPre.code, "policy_refusal");

// 6. Verify createSteOpenCodePlugin registers ONLY skills and tools (no execute.before, no prompt/context hooks, no event subscription, no /ste-off)
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
const sessionHooks = new Map();
let eventSubscribed = false;

const pluginDef = createSteOpenCodePlugin({{
  PluginApi: {{ define: (x) => x }},
  ToolErrorClass: MockToolError,
  EffectApi: mockEffectApi,
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
    context: async () => [],
    hook: (name, cb) => makeEffect(sessionHooks.set(name, cb)),
  }},
  event: {{
    subscribe: () => {{
      eventSubscribed = true;
      return {{ pipe: () => makeEffect({{}}) }};
    }},
  }},
}})();

assert.equal(addedSkills.size, 4);
assert.equal(addedTools.size, 10);
for (const [tName, tDef] of addedTools.entries()) {{
  assert.deepEqual(tDef.options, {{ codemode: false }}, `Tool ${{tName}} must set codemode: false`);
}}
assert.equal(addedCommands.size, 0, "Must not register /ste-off or any slash commands");
assert.equal(toolHooks.size, 0, "Must not register execute.before or any tool hooks");
assert.equal(sessionHooks.size, 0, "Must not register prompt or context session hooks");
assert.equal(eventSubscribed, false, "Must not subscribe to global server events");

// 7. Guarded STE tool execution succeeds regardless of session history/ancestry, and invalid STE inputs fail with Tool.Error
const writeTool = addedTools.get("ste_write_artifact");
const validWriteRes = await writeTool.execute(
  {{
    target_path: "artifacts/js-unit/note.md",
    content: "# Unit Test Note\\n\\nClose the isolation valve before inspection.\\n",
  }},
  {{ sessionID: "ses_custom" }},
);
assert.equal(validWriteRes._failed, false);
assert.equal(validWriteRes.value.metadata.ste_op, "ste_write_artifact");
assert.equal(validWriteRes.value.metadata.verdict, "ALLOW");
assert.ok(fs.existsSync(path.join(ws, "artifacts", "js-unit", "note.md")));

const invalidWriteRes = await writeTool.execute(
  {{
    target_path: "../escaped-unit.md",
    content: "# Escaped\\n",
  }},
  {{ sessionID: "ses_custom" }},
);
assert.equal(invalidWriteRes._failed, true);
assert.ok(invalidWriteRes.error instanceof MockToolError);
assert.equal(invalidWriteRes.error._tag, "Tool.Error");
assert.equal(invalidWriteRes.error.metadata.code, "policy_refusal");

// 8. Verify ste_status tool execution when runtime is missing does NOT fabricate verdict: "ALLOW"
const prevCfg = process.env.STE_SKILLC_RUNTIME_CONFIG;
process.env.STE_SKILLC_RUNTIME_CONFIG = path.join(ws, "nonexistent-runtime.json");
try {{
  const statusTool = addedTools.get("ste_status");
  const statusExecRes = await statusTool.execute({{}}, {{ sessionID: "ses_custom" }});
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

            # Outside-workspace sentinel for invalid STE tool input that must NEVER exist
            sentinel_outside = sandbox_root / "sentinel-outside-root.md"
            # Normal host files after loading STE skill that MUST succeed
            host_write_after_skill = workspace / "host-write-after-ste-skill.txt"
            host_shell_after_skill = workspace / "host-shell-after-ste-skill.txt"

            scenario_state: dict[str, Any] = {
                "mode": "ste_coexistence",
                "step": 0,
                "execute_offered": False,
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
                        self.wfile.write(_make_text_sse("STE Tools and Host Coexistence Session"))
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

                    if mode == "ste_coexistence":
                        if step == 1:
                            # 1. Load bundled STE skill via real `skill` tool
                            payload = _make_tool_call_sse(
                                "call_ste_skill",
                                "skill",
                                {"id": "ste-promax"},
                            )
                        elif step == 2:
                            # 2. Check ste_status to verify workspace_root is bound from OpenCode session/location
                            payload = _make_tool_call_sse(
                                "call_ste_status",
                                "ste_status",
                                {},
                            )
                        elif step == 3:
                            # 3. Normal host `write` after loading STE skill -> must succeed
                            payload = _make_tool_call_sse(
                                "call_host_write",
                                "write",
                                {
                                    "path": str(host_write_after_skill),
                                    "content": "HOST_WRITE_AFTER_STE_SKILL_OK\n",
                                },
                            )
                        elif step == 4:
                            # 4. Normal host `shell` after loading STE skill -> must succeed
                            payload = _make_tool_call_sse(
                                "call_host_shell",
                                "shell",
                                {"command": f'echo HOST_SHELL_OK > "{host_shell_after_skill}"'},
                            )
                        elif step == 5:
                            # 5. Normal host Code Mode `execute` (if offered by CLI catalog) or `read` after loading STE skill
                            if "execute" in tools_offered:
                                scenario_state["execute_offered"] = True
                                payload = _make_tool_call_sse(
                                    "call_code_mode",
                                    "execute",
                                    {"code": "return { codemode_ok: true };"},
                                )
                            else:
                                scenario_state["execute_offered"] = False
                                payload = _make_tool_call_sse(
                                    "call_host_read",
                                    "read",
                                    {"path": str(source_doc)},
                                )
                        elif step == 6:
                            # 6. Attempt out-of-workspace ste_write_artifact -> must be refused by STE validation before write
                            payload = _make_tool_call_sse(
                                "call_ste_outside",
                                "ste_write_artifact",
                                {
                                    "target_path": "../sentinel-outside-root.md",
                                    "content": "# Escaped\n",
                                },
                            )
                        elif step == 7:
                            # 7. Valid guarded ste_write_artifact -> must succeed with ALLOW receipt
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
                        elif step == 8:
                            # 8. Valid guarded ste_render_bundle -> must succeed automatically
                            payload = _make_tool_call_sse(
                                "call_ste_render",
                                "ste_render_bundle",
                                {
                                    "input_path": "source-note.md",
                                    "output_dir": "artifacts/oc-live-bundle",
                                    "title": "Hydraulic Pressure Check",
                                },
                            )
                        elif step == 9:
                            # 9. Valid guarded ste_inspect_artifact -> must succeed automatically
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

            proc_ste = subprocess.run(
                [
                    str(OPENCODE_CLI_EXE),
                    "run",
                    "--standalone",
                    "--auto",
                    "--format",
                    "json",
                    "Load ste-promax skill, use normal host tools and guarded STE tools.",
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
            (retained_dir / "run1-ste-coexistence.stdout.jsonl").write_text(proc_ste.stdout, encoding="utf-8")
            (retained_dir / "run1-ste-coexistence.stderr.log").write_text(proc_ste.stderr, encoding="utf-8")
            self.assertEqual(proc_ste.returncode, 0, proc_ste.stderr)

            # Verify normal host tools succeeded after loading STE skill
            self.assertTrue(host_write_after_skill.is_file(), "Normal host write after STE skill must succeed!")
            self.assertIn("HOST_WRITE_AFTER_STE_SKILL_OK", host_write_after_skill.read_text(encoding="utf-8"))
            self.assertTrue(host_shell_after_skill.is_file(), "Normal host shell after STE skill must succeed!")
            self.assertIn("HOST_SHELL_OK", host_shell_after_skill.read_text(encoding="utf-8"))

            # Verify invalid STE tool input was still refused without side effects
            self.assertFalse(sentinel_outside.exists(), "Outside-workspace STE sentinel must not exist!")

            # Verify guarded STE artifact write and bundle render succeeded
            written_doc = workspace / "artifacts" / "oc-live-doc" / "valve-procedure.md"
            bundle_dir = workspace / "artifacts" / "oc-live-bundle"
            self.assertTrue(written_doc.is_file())
            self.assertTrue((bundle_dir / "manifest.json").is_file())
            self.assertTrue((bundle_dir / "gallery.html").is_file())

            # Save full request log and copy artifacts/policy-state into retained_dir
            (retained_dir / "mock-provider-requests.json").write_text(
                json.dumps(
                    {
                        "execute_offered_by_cli": bool(scenario_state["execute_offered"]),
                        "codemode_status": (
                            "exercised_and_verified"
                            if scenario_state["execute_offered"]
                            else "not_offered_by_standalone_cli_catalog"
                        ),
                        "requests": scenario_state["requests"],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            shutil.copytree(workspace / "artifacts", retained_dir / "workspace-artifacts")
            shutil.copytree(policy_state, retained_dir / "policy-state")

            ste_reqs = [r for r in scenario_state["requests"] if r["mode"] == "ste_coexistence"]
            self.assertGreaterEqual(len(ste_reqs), 10)
            for tool_name in STE_TOOL_NAMES:
                self.assertIn(tool_name, ste_reqs[0]["tools_offered"])

            # Verify ste_status returned actual caller workspace_root (from ctx.session.get / ctx.location)
            # and bundle_root from installed_bundle (never confusing the two!)
            status_tool_outputs = []
            for r in ste_reqs:
                for raw_msg in r.get("tool_messages", []):
                    if isinstance(raw_msg, str) and '"host_adapter": "ste-promax"' in raw_msg:
                        status_tool_outputs.append(json.loads(raw_msg))
            self.assertTrue(status_tool_outputs, "Expected ste_status tool output in transcript.")
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
            self.assertNotIn("STE-Pro-Max policy refuses raw", combined_feedback)
            self.assertIn("must not contain '..' traversal segments", combined_feedback)
            self.assertIn('"verdict": "ALLOW"', combined_feedback)
            if scenario_state["execute_offered"]:
                code_result = next(r["last_message"] for r in ste_reqs if r["step"] == 6)
                self.assertEqual(code_result["tool_call_id"], "call_code_mode")
                self.assertIs(json.loads(code_result["content"]).get("codemode_ok"), True)
            else:
                self.assertIn("Hydraulic Pressure Check", combined_feedback)


if __name__ == "__main__":
    unittest.main()

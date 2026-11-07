// Core implementation for the OpenCode V2 STE-Pro-Max automatic host adapter.
// Uses only Node.js built-ins so unit boundaries and real OpenCode V2 runtime
// execution share the exact same enforcement, scope, and dispatcher logic.

import { execFile } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

export const OPENCODE_PLUGIN_ID = "ste-promax";
export const RUNTIME_SCHEMA = "ste-promax.runtime.v1";
export const MANAGED_BY = "ste-promax";

export const ERROR_DEPENDENCY_MISSING = "dependency_missing";
export const ERROR_UNSUPPORTED_OPERATION = "unsupported_operation";
export const ERROR_INVALID_INPUT = "invalid_input";
export const ERROR_POLICY_REFUSAL = "policy_refusal";
export const ERROR_POSTCONDITION_FAILURE = "postcondition_failure";

export const STE_SKILL_IDS = new Set([
  "ste-promax",
  "ste-visual-docs",
  "ste-storytelling",
  "ste-line-studio",
]);

export const STE_AGENT_IDS = new Set([
  "ste-author",
]);

export const STE_TOOL_NAMES = new Set([
  "ste_status",
  "ste_check_prose",
  "ste_write_artifact",
  "ste_render_bundle",
  "ste_render_artifact",
  "ste_regenerate_gallery",
  "ste_prepare_story_media",
  "ste_synthesize_wav",
  "ste_inspect_artifact",
  "ste_export_bundle",
]);

export const FORBIDDEN_INPUT_KEYS = new Set([
  "python",
  "python_exe",
  "interpreter",
  "skillc_root",
  "skillc_src",
  "plugin_path",
  "state_dir",
  "state_root",
  "runtime_config",
  "bypass",
  "skip_policy",
  "skip_check",
  "force_allow",
  "approved",
  "approval",
  "approval_token",
  "token",
  "reviewer",
  "approver",
  "review_method",
  "user_conversation",
  "ask_user",
  "command",
  "shell",
  "script",
  "eval",
  "exec",
]);

export const ALLOWED_HOST_WRITE_EXTENSIONS = new Set([
  ".html",
  ".svg",
  ".md",
  ".json",
  ".yaml",
  ".yml",
  ".txt",
  ".vtt",
  ".css",
]);

export const FORBIDDEN_HOST_WRITE_EXTENSIONS = new Set([
  ".py",
  ".pyc",
  ".pyo",
  ".ps1",
  ".psm1",
  ".psd1",
  ".sh",
  ".bash",
  ".zsh",
  ".cmd",
  ".bat",
  ".vbs",
  ".exe",
  ".dll",
  ".so",
  ".dylib",
  ".node",
  ".mjs",
  ".cjs",
  ".js",
  ".ts",
  ".tsx",
  ".jsx",
]);

export const EXTRA_PROTECTED_WORKSPACE_DIRS = new Set([
  "ste_promax",
  "integrations",
  "skills",
  "ste-promax",
  "com.github.copilot",
  "tools",
  "tests",
  ".git",
  ".github",
  ".copilot",
  ".opencode",
  ".claude",
  ".agents",
  ".claude-plugin",
  ".vscode",
  ".skillc",
  ".slim",
  ".venv",
  ".ste-env",
  "node_modules",
]);

export const PROTECTED_WORKSPACE_ROOT_FILES = new Set([
  "mcp.json",
  ".mcp.json",
  "plugin.json",
  "pyproject.toml",
  "__main__.py",
  "quickstart.py",
  "license",
  "notice",
  "ste-promax.zip",
  "agents.md",
  "claude.md",
]);

export const RAW_MUTATION_TOOLS = new Set([
  "create",
  "edit",
  "apply_patch",
  "patch",
  "write",
  "write_file",
  "insert",
  "delete",
  "delete_file",
  "move_file",
  "rename_file",
  "str_replace_editor",
  "str_replace_based_edit_tool",
  "multiedit",
  "notebookedit",
  "ast_grep_replace",
]);

export const RAW_SHELL_AND_CODEMODE_TOOLS = new Set([
  "shell",
  "bash",
  "read_bash",
  "write_bash",
  "stop_bash",
  "list_bash",
  "powershell",
  "read_powershell",
  "write_powershell",
  "stop_powershell",
  "list_powershell",
  "pwsh",
  "sh",
  "cmd",
  "local_shell",
  "terminal",
  "exec",
  "execute",
  "codemode",
  "code_mode",
  "write_agent",
  "pty_spawn",
  "pty_write",
  "pty_read",
  "pty_list",
  "pty_kill",
  "persistent_pty",
]);

export const OPAQUE_HOST_MUTATION_TOOLS = new Set([
  "extensions_manage",
  "extensions_reload",
  "workflow",
  "workflows",
  "run_dynamic_workflow",
  "dynamic_workflows_manage",
  "mcp_manage",
  "plugin_manage",
  "catalog_select",
  "opencode_worktree_create",
  "opencode_worktree_remove",
  "opencode_session_move",
  "opencode_session_rename",
  "worktree_create",
  "worktree_remove",
  "session_move",
  "session_rename",
  "res_add",
  "res_forget",
  "superagent_control",
  "superagent_prompts",
  "superagent_settings",
]);

export const OPAQUE_AGENT_PREFIXES = [
  "computer-use/",
  "computer_use",
  "browser-use/",
  "browser_use",
  "cua-driver",
  "cua_driver",
  "playwright",
  "acp",
  "dsh",
  "superagent_",
  "pty_",
];

export const BLOCKED_SUBAGENT_NAMES = new Set([
  "acp",
  "dsh",
  "computer-use",
  "browser-use",
  "cua-driver",
  "configure-copilot",
]);

export const SAFE_READ_AND_NAVIGATION_TOOLS = new Set([
  "view",
  "read",
  "grep",
  "glob",
  "rg",
  "ast_grep_search",
  "lsp",
  "skill",
  "web_fetch",
  "web_search",
  "webfetch",
  "websearch",
  "ask_user",
  "question",
  "report_intent",
  "todo_write",
  "todowrite",
  "todoread",
  "update_todo",
  "think",
  "catalog_search",
  "opencode_list_mcp_resources",
  "opencode_read_mcp_resource",
  "opencode_worktree_list",
  "res_status",
  "res_search",
  "res_profile",
  "context7",
  "gh_grep",
  "superagent_state",
  "superagent_sources",
]);

const MAX_ANCESTOR_DEPTH = 8;

const UNCERTAIN_SCOPE_READONLY_TOOLS = new Set([
  "ste_status",
  "read",
  "view",
  "glob",
  "grep",
  "rg",
  "ast_grep_search",
  "lsp",
  "question",
  "ask_user",
  "think",
  "todoread",
]);

export function buildSteToolResultMetadata(toolName, response) {
  const receiptVerdict = response?.result?.policy_receipt?.verdict;
  if (typeof receiptVerdict === "string" && receiptVerdict.trim()) {
    return {
      ste_op: toolName,
      verdict: receiptVerdict.trim(),
    };
  }
  const unavailable =
    response?.result?.available === false ||
    response?.result?.policy_available === false ||
    response?.result?.mode === "unavailable";
  return {
    ste_op: toolName,
    verdict: unavailable ? "unverified" : "not_applicable",
  };
}

export const SAFE_READONLY_MCP_PREFIXES = [
  "github-mcp-server/get_",
  "github-mcp-server/list_",
  "github-mcp-server/search_",
  "github-mcp-server/issue_read",
  "bluebird/",
];

const STE_OFF_RE = /^\s*\/ste-off(?:\s+[\s\S]*)?$/i;
const RESERVED_DEVICE_NAMES = new Set([
  "CON",
  "PRN",
  "AUX",
  "NUL",
  "COM1",
  "COM2",
  "COM3",
  "COM4",
  "COM5",
  "COM6",
  "COM7",
  "COM8",
  "COM9",
  "LPT1",
  "LPT2",
  "LPT3",
  "LPT4",
  "LPT5",
  "LPT6",
  "LPT7",
  "LPT8",
  "LPT9",
]);

const MODULE_DIR = path.dirname(fileURLToPath(import.meta.url));

export function resolveBundleRoot(pluginFileUrl = import.meta.url) {
  const dir = path.dirname(fileURLToPath(pluginFileUrl));
  return path.resolve(dir, "..", "..");
}

export const BUNDLE_ROOT = resolveBundleRoot();
export const DISPATCH_PY_PATH = path.join(MODULE_DIR, "dispatch.py");

export function sha256Hex(input) {
  return crypto.createHash("sha256").update(String(input), "utf8").digest("hex");
}

export function normalizeIdentifier(raw) {
  if (typeof raw !== "string") return "";
  let text = raw.trim().toLowerCase();
  if (!text) return "";
  if (text.startsWith("/") || text.startsWith("@")) {
    text = text.slice(1).trim();
  }
  for (const sep of [":", "/"]) {
    const idx = text.indexOf(sep);
    if (idx > 0) {
      const prefix = text.slice(0, idx);
      const rest = text.slice(idx + 1).trim();
      if ((prefix === "ste-pro-max" || prefix === "ste_pro_max" || prefix === "ste-promax") && rest) {
        return rest;
      }
    }
  }
  return text;
}

export function isSteSkillIdentifier(raw) {
  return STE_SKILL_IDS.has(normalizeIdentifier(raw));
}

export function isSteAgentIdentifier(raw) {
  return STE_AGENT_IDS.has(normalizeIdentifier(raw));
}

export function isSteToolName(raw) {
  if (typeof raw !== "string" || !raw.trim()) {
    return { matched: false, canonical: "" };
  }
  const text = raw.trim();
  if (STE_TOOL_NAMES.has(text)) {
    return { matched: true, canonical: text };
  }
  const prefixes = [
    "ste-promax/",
    "ste-promax.",
    "ste-promax:",
    "ste-promax-",
    "ste-promax_",
    "ste_promax/",
    "ste_promax_",
    "mcp__ste-promax__",
    "mcp__ste_promax__",
  ];
  for (const prefix of prefixes) {
    if (text.startsWith(prefix)) {
      const candidate = text.slice(prefix.length);
      if (STE_TOOL_NAMES.has(candidate)) {
        return { matched: true, canonical: candidate };
      }
    }
  }
  return { matched: false, canonical: "" };
}

export function isExplicitUserSteOff(text) {
  if (typeof text !== "string") return false;
  return STE_OFF_RE.test(text);
}

export function checkSafeLexicalPath(rawPath, label = "Path", { requireAbsolute = false, allowLeafSymlink = false } = {}) {
  if (typeof rawPath !== "string" || !rawPath.trim()) {
    return { ok: false, code: ERROR_INVALID_INPUT, message: `${label} must not be empty.` };
  }
  const text = rawPath.trim();
  if (text.includes("\0")) {
    return { ok: false, code: ERROR_INVALID_INPUT, message: `${label} must not contain null bytes.` };
  }
  if (text.startsWith("\\\\") || text.startsWith("//")) {
    return { ok: false, code: ERROR_INVALID_INPUT, message: `${label} must not use UNC or network share paths.` };
  }
  const rawSegments = text.split(/[\\/]+/);
  if (rawSegments.includes("..")) {
    return { ok: false, code: ERROR_POLICY_REFUSAL, message: `${label} must not contain '..' traversal segments.` };
  }
  if (process.platform === "win32" && /^[A-Za-z]:(?![\\/])/.test(text)) {
    return { ok: false, code: ERROR_POLICY_REFUSAL, message: `${label} must not use a drive-relative path.` };
  }
  if (requireAbsolute && !path.isAbsolute(text)) {
    return { ok: false, code: ERROR_INVALID_INPUT, message: `${label} must be an absolute path: ${text}` };
  }

  const absolute = path.resolve(text);
  const parsed = path.parse(absolute);
  const relAfterRoot = absolute.slice(parsed.root.length);
  const parts = relAfterRoot ? relAfterRoot.split(path.sep).filter(Boolean) : [];
  for (const part of parts) {
    if (part.includes(":") || part.endsWith(" ") || part.endsWith(".")) {
      return {
        ok: false,
        code: ERROR_INVALID_INPUT,
        message: `${label} must not use alternate streams or trailing-dot/space components.`,
      };
    }
    const stem = part.split(".")[0].toUpperCase();
    if (RESERVED_DEVICE_NAMES.has(stem)) {
      return {
        ok: false,
        code: ERROR_INVALID_INPUT,
        message: `${label} must not reference a reserved device name: ${part}`,
      };
    }
  }

  let cur = absolute;
  const chain = [];
  while (true) {
    chain.push(cur);
    const parent = path.dirname(cur);
    if (parent === cur) break;
    cur = parent;
  }
  for (const item of chain) {
    let st;
    try {
      st = fs.lstatSync(item);
    } catch {
      continue;
    }
    if (st.isSymbolicLink()) {
      if (allowLeafSymlink && item === absolute) continue;
      return {
        ok: false,
        code: ERROR_POLICY_REFUSAL,
        message: `${label} and its parents must not be symbolic links: ${item}`,
      };
    }
    if (item !== absolute && !st.isDirectory()) {
      return {
        ok: false,
        code: ERROR_INVALID_INPUT,
        message: `${label} parent must be a directory, not a file: ${item}`,
      };
    }
  }

  let resolved = absolute;
  try {
    resolved = fs.realpathSync(absolute);
  } catch {
    let ancestor = path.dirname(absolute);
    while (true) {
      try {
        const realAncestor = fs.realpathSync(ancestor);
        resolved = path.join(realAncestor, path.relative(ancestor, absolute));
        break;
      } catch {
        const next = path.dirname(ancestor);
        if (next === ancestor) {
          resolved = absolute;
          break;
        }
        ancestor = next;
      }
    }
  }
  return { ok: true, absolute, resolved };
}

export function isExactSteSkillMdPath(rawPath, workspaceRoot = null, bundleRoot = BUNDLE_ROOT) {
  if (typeof rawPath !== "string" || !rawPath.trim() || rawPath.includes("\0")) {
    return false;
  }
  const text = rawPath.trim();
  if (path.basename(text).toLowerCase() !== "skill.md") {
    return false;
  }
  const candidates = [];
  if (path.isAbsolute(text)) {
    candidates.push(text);
  } else if (workspaceRoot) {
    candidates.push(path.join(workspaceRoot, text));
  }
  for (const cand of candidates) {
    const check = checkSafeLexicalPath(cand, "SKILL.md candidate");
    if (!check.ok) continue;
    let st;
    try {
      st = fs.lstatSync(check.absolute);
    } catch {
      continue;
    }
    if (!st.isFile() || st.isSymbolicLink()) continue;
    const parentName = path.basename(path.dirname(check.resolved)).toLowerCase();
    const grandParentName = path.basename(path.dirname(path.dirname(check.resolved))).toLowerCase();
    if (STE_SKILL_IDS.has(parentName) && grandParentName === "skills") {
      return true;
    }
    if (parentName === "ste-promax") {
      const normRes = check.resolved.toLowerCase();
      const normBundle = bundleRoot ? path.resolve(bundleRoot).toLowerCase() : "";
      const normWs = workspaceRoot ? path.resolve(workspaceRoot).toLowerCase() : "";
      if ((normBundle && normRes.startsWith(normBundle)) || (normWs && normRes.startsWith(normWs))) {
        return true;
      }
    }
  }
  return false;
}

export function readBundleSkills(bundleRoot = BUNDLE_ROOT) {
  const skills = [];
  for (const skillId of STE_SKILL_IDS) {
    const skillPath = path.join(bundleRoot, "skills", skillId, "SKILL.md");
    try {
      const st = fs.lstatSync(skillPath);
      if (!st.isFile() || st.isSymbolicLink()) continue;
      const raw = fs.readFileSync(skillPath, "utf8");
      let name = skillId;
      let description = `STE-Pro-Max ${skillId} skill`;
      let body = raw;
      const fmMatch = raw.match(/^\ufeff?---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/);
      if (fmMatch) {
        const fm = fmMatch[1];
        body = fmMatch[2].trim() || raw;
        const nameMatch = fm.match(/^name:\s*(.+)$/m);
        if (nameMatch) {
          name = nameMatch[1].trim().replace(/^["']|["']$/g, "");
        }
        const descMatch = fm.match(/^description:\s*(.+)$/m);
        if (descMatch) {
          description = descMatch[1].trim().replace(/^["']|["']$/g, "");
        }
      }
      skills.push({
        id: skillId,
        name,
        description,
        path: path.resolve(skillPath),
        content: body,
      });
    } catch {
      continue;
    }
  }
  return skills;
}

export function defaultRuntimeConfigPath(env = process.env) {
  if (process.platform === "win32") {
    const localAppData = (env.LOCALAPPDATA || "").trim();
    const base = localAppData || path.join(os.homedir(), "AppData", "Local");
    return path.join(base, "STE-Pro-Max", "skillc-runtime", "runtime.json");
  }
  const xdgData = (env.XDG_DATA_HOME || "").trim();
  const base = xdgData || path.join(os.homedir(), ".local", "share");
  return path.join(base, "ste-promax", "skillc-runtime", "runtime.json");
}

export function resolveTrustedRuntime(env = process.env) {
  const rawPy = (env.STE_SKILLC_PYTHON || "").trim();
  const rawRoot = (env.STE_SKILLC_ROOT || "").trim();
  const rawCfgOverride = (env.STE_SKILLC_RUNTIME_CONFIG || "").trim();

  if (rawPy || rawRoot) {
    if (!rawPy || !rawRoot) {
      return {
        available: false,
        error: {
          code: ERROR_DEPENDENCY_MISSING,
          message: "SkillC backend is misconfigured: STE_SKILLC_PYTHON and STE_SKILLC_ROOT must both be set.",
        },
      };
    }
    const pyCheck = checkSafeLexicalPath(rawPy, "STE_SKILLC_PYTHON", {
      requireAbsolute: true,
      allowLeafSymlink: true,
    });
    if (!pyCheck.ok) {
      return { available: false, error: { code: ERROR_DEPENDENCY_MISSING, message: pyCheck.message } };
    }
    const rootCheck = checkSafeLexicalPath(rawRoot, "STE_SKILLC_ROOT", {
      requireAbsolute: true,
      allowLeafSymlink: true,
    });
    if (!rootCheck.ok) {
      return { available: false, error: { code: ERROR_DEPENDENCY_MISSING, message: rootCheck.message } };
    }
    try {
      const pyStat = fs.statSync(pyCheck.absolute);
      if (!pyStat.isFile() || pyStat.size === 0) {
        return {
          available: false,
          error: {
            code: ERROR_DEPENDENCY_MISSING,
            message: `STE_SKILLC_PYTHON is not a non-empty file: ${pyCheck.absolute}`,
          },
        };
      }
      const rootStat = fs.statSync(rootCheck.absolute);
      if (!rootStat.isDirectory()) {
        return {
          available: false,
          error: {
            code: ERROR_DEPENDENCY_MISSING,
            message: `STE_SKILLC_ROOT is not a directory: ${rootCheck.absolute}`,
          },
        };
      }
    } catch (err) {
      return {
        available: false,
        error: {
          code: ERROR_DEPENDENCY_MISSING,
          message: `SkillC backend path does not exist: ${err instanceof Error ? err.message : String(err)}`,
        },
      };
    }
    return {
      available: true,
      pythonExe: pyCheck.absolute,
      skillcRoot: rootCheck.absolute,
      configPath: rawCfgOverride || defaultRuntimeConfigPath(env),
      runtimeConfig: null,
    };
  }

  const cfgPath = rawCfgOverride || defaultRuntimeConfigPath(env);
  const cfgCheck = checkSafeLexicalPath(cfgPath, "STE_SKILLC_RUNTIME_CONFIG", {
    requireAbsolute: true,
    allowLeafSymlink: false,
  });
  if (!cfgCheck.ok) {
    return { available: false, error: { code: ERROR_DEPENDENCY_MISSING, message: cfgCheck.message } };
  }

  let st;
  try {
    st = fs.lstatSync(cfgCheck.absolute);
  } catch {
    return {
      available: false,
      error: {
        code: ERROR_DEPENDENCY_MISSING,
        message: `Runtime configuration file does not exist: ${cfgCheck.absolute}`,
      },
    };
  }
  if (!st.isFile() || st.isSymbolicLink()) {
    return {
      available: false,
      error: {
        code: ERROR_DEPENDENCY_MISSING,
        message: `Runtime configuration must be a regular file, not a link: ${cfgCheck.absolute}`,
      },
    };
  }

  let parsed;
  try {
    parsed = JSON.parse(fs.readFileSync(cfgCheck.absolute, "utf8"));
  } catch (err) {
    return {
      available: false,
      error: {
        code: ERROR_DEPENDENCY_MISSING,
        message: `Malformed runtime configuration in ${cfgCheck.absolute}: ${err instanceof Error ? err.message : String(err)}`,
      },
    };
  }

  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    return {
      available: false,
      error: { code: ERROR_DEPENDENCY_MISSING, message: "runtime.json must be a JSON object." },
    };
  }
  if (parsed.schema !== RUNTIME_SCHEMA || parsed.managed_by !== MANAGED_BY) {
    return {
      available: false,
      error: {
        code: ERROR_DEPENDENCY_MISSING,
        message: `runtime.json schema/managed_by invalid in ${cfgCheck.absolute}.`,
      },
    };
  }

  for (const reqKey of ["python", "skillc_root", "ste_root", "state_root"]) {
    const val = parsed[reqKey];
    const check = checkSafeLexicalPath(val, `runtime.json.${reqKey}`, {
      requireAbsolute: true,
      allowLeafSymlink: reqKey === "python",
    });
    if (!check.ok) {
      return { available: false, error: { code: ERROR_DEPENDENCY_MISSING, message: check.message } };
    }
  }

  try {
    const pyStat = fs.statSync(parsed.python);
    if (!pyStat.isFile() || pyStat.size === 0) {
      return {
        available: false,
        error: {
          code: ERROR_DEPENDENCY_MISSING,
          message: `runtime.json python executable is missing or empty: ${parsed.python}`,
        },
      };
    }
    const rootStat = fs.statSync(parsed.skillc_root);
    if (!rootStat.isDirectory()) {
      return {
        available: false,
        error: {
          code: ERROR_DEPENDENCY_MISSING,
          message: `runtime.json skillc_root is not a directory: ${parsed.skillc_root}`,
        },
      };
    }
  } catch (err) {
    return {
      available: false,
      error: {
        code: ERROR_DEPENDENCY_MISSING,
        message: `runtime.json backend target missing: ${err instanceof Error ? err.message : String(err)}`,
      },
    };
  }

  return {
    available: true,
    pythonExe: parsed.python,
    skillcRoot: parsed.skillc_root,
    stateRoot: parsed.state_root,
    configPath: cfgCheck.absolute,
    runtimeConfig: parsed,
  };
}

export function resolveStateRoot(env = process.env) {
  const envState = (env.STE_SKILLC_STATE_ROOT || "").trim();
  if (envState) {
    const check = checkSafeLexicalPath(envState, "STE_SKILLC_STATE_ROOT", { requireAbsolute: true });
    if (check.ok) return check.resolved;
  }
  const rt = resolveTrustedRuntime(env);
  if (rt.available && rt.stateRoot) {
    return rt.stateRoot;
  }
  const cfgPath = defaultRuntimeConfigPath(env);
  return path.join(path.dirname(cfgPath), "state");
}

function isSubpath(childPath, parentPath) {
  const rel = path.relative(parentPath, childPath);
  return Boolean(rel) && !rel.startsWith("..") && !path.isAbsolute(rel);
}

function isSameOrSubpath(childPath, parentPath) {
  const rel = path.relative(parentPath, childPath);
  return rel === "" || (!rel.startsWith("..") && !path.isAbsolute(rel));
}

export function validateHostTargetPath(
  rawPath,
  workspaceRoot,
  label = "target_path",
  { isDirectory = false, requireDocumentExtension = false } = {},
) {
  if (typeof rawPath !== "string" || !rawPath.trim()) {
    return { ok: false, code: ERROR_INVALID_INPUT, message: `${label} must be a non-empty string.` };
  }
  const wsCheck = checkSafeLexicalPath(workspaceRoot, "Trusted workspace root", { requireAbsolute: true });
  if (!wsCheck.ok) {
    return wsCheck;
  }
  const text = rawPath.trim();
  if (text.includes("\0")) {
    return { ok: false, code: ERROR_INVALID_INPUT, message: `${label} must not contain null bytes.` };
  }
  const rawSegments = text.split(/[\\/]+/);
  if (rawSegments.includes("..")) {
    return {
      ok: false,
      code: ERROR_POLICY_REFUSAL,
      message: `${label} must not contain '..' traversal segments.`,
    };
  }
  const candidate = path.isAbsolute(text) ? text : path.join(wsCheck.resolved, text);
  const check = checkSafeLexicalPath(candidate, label);
  if (!check.ok) return check;

  if (!isSubpath(check.resolved, wsCheck.resolved)) {
    return {
      ok: false,
      code: ERROR_POLICY_REFUSAL,
      message: `${label} must reside strictly inside workspace root ${wsCheck.resolved}: ${check.resolved}`,
    };
  }

  const rel = path.relative(wsCheck.resolved, check.resolved);
  const relParts = rel.split(path.sep).filter(Boolean);
  if (relParts.length === 0) {
    return {
      ok: false,
      code: ERROR_POLICY_REFUSAL,
      message: `${label} cannot target workspace root itself.`,
    };
  }

  const topLower = relParts[0].toLowerCase();
  if (EXTRA_PROTECTED_WORKSPACE_DIRS.has(topLower)) {
    return {
      ok: false,
      code: ERROR_POLICY_REFUSAL,
      message: `${label} targets protected workspace directory ${relParts[0]}: ${check.resolved}`,
    };
  }
  if (relParts.length === 1 && PROTECTED_WORKSPACE_ROOT_FILES.has(topLower)) {
    return {
      ok: false,
      code: ERROR_POLICY_REFUSAL,
      message: `${label} targets protected workspace root file ${relParts[0]}: ${check.resolved}`,
    };
  }
  if (
    relParts.length >= 2 &&
    relParts[0].toLowerCase() === "artifacts" &&
    relParts[1].toLowerCase() === "skillc-native-20261106"
  ) {
    return {
      ok: false,
      code: ERROR_POLICY_REFUSAL,
      message: `${label} references protected historical manual stage package skillc-native-20261106.`,
    };
  }

  if (!isDirectory && requireDocumentExtension) {
    const ext = path.extname(check.resolved).toLowerCase();
    if (FORBIDDEN_HOST_WRITE_EXTENSIONS.has(ext) || !ALLOWED_HOST_WRITE_EXTENSIONS.has(ext)) {
      return {
        ok: false,
        code: ERROR_POLICY_REFUSAL,
        message: `${label} has unsupported host artifact extension ${JSON.stringify(ext)}; allowed extensions: ${Array.from(ALLOWED_HOST_WRITE_EXTENSIONS).sort().join(", ")}.`,
      };
    }
  }

  return { ok: true, resolved: check.resolved };
}

export function isBlockedCredentialRead(toolArgs) {
  if (!toolArgs || typeof toolArgs !== "object") return null;
  const rawPath = toolArgs.path ?? toolArgs.file_path ?? toolArgs.filePath;
  if (typeof rawPath !== "string" || !rawPath.trim()) return null;
  const norm = rawPath.replaceAll("\\", "/").toLowerCase();
  const parts = norm.split("/").filter(Boolean);
  const name = parts.at(-1) || "";
  if (parts.includes(".copilot") && name === "config.json") {
    return "Reading ~/.copilot/config.json is blocked by STE-Pro-Max policy.";
  }
  if (parts.includes(".opencode") && (name === "opencode.json" || name === "opencode.jsonc")) {
    return "Reading OpenCode global/project configuration is blocked by STE-Pro-Max policy.";
  }
  if (parts.some((seg) => [".ssh", ".gnupg", ".aws", ".azure", ".kube"].includes(seg))) {
    return "Reading private credential directories is blocked by STE-Pro-Max policy.";
  }
  if (
    ["runtime.json", ".env", "approval_reference.json", "approvals.sqlite3"].includes(name) ||
    name.startsWith(".env.")
  ) {
    return `Reading protected secret/policy file ${JSON.stringify(name)} is blocked by STE-Pro-Max policy.`;
  }
  return null;
}

export function prevalidateSteToolCall(canonicalTool, toolArgs, workspaceRoot, env = process.env) {
  const args = toolArgs && typeof toolArgs === "object" && !Array.isArray(toolArgs) ? toolArgs : {};
  const forbidden = Object.keys(args).filter((k) => FORBIDDEN_INPUT_KEYS.has(k)).sort();
  if (forbidden.length > 0) {
    return {
      ok: false,
      code: ERROR_POLICY_REFUSAL,
      message: `STE-Pro-Max tool ${JSON.stringify(canonicalTool)} rejected forbidden model arguments: ${forbidden.join(", ")}.`,
    };
  }
  if ("workspace_root" in args) {
    return {
      ok: false,
      code: ERROR_POLICY_REFUSAL,
      message: `STE-Pro-Max tool ${JSON.stringify(canonicalTool)} does not accept workspace_root from model arguments.`,
    };
  }

  if (workspaceRoot) {
    if (canonicalTool === "ste_write_artifact" && "target_path" in args) {
      const check = validateHostTargetPath(args.target_path, workspaceRoot, "target_path", {
        isDirectory: false,
        requireDocumentExtension: true,
      });
      if (!check.ok) return check;
    } else if (
      ["ste_render_bundle", "ste_render_artifact", "ste_prepare_story_media", "ste_export_bundle"].includes(canonicalTool) &&
      "output_dir" in args
    ) {
      const check = validateHostTargetPath(args.output_dir, workspaceRoot, "output_dir", {
        isDirectory: true,
        requireDocumentExtension: false,
      });
      if (!check.ok) return check;
    } else if (canonicalTool === "ste_regenerate_gallery" && "artifact_dir" in args) {
      const check = validateHostTargetPath(args.artifact_dir, workspaceRoot, "artifact_dir", {
        isDirectory: true,
        requireDocumentExtension: false,
      });
      if (!check.ok) return check;
    } else if (canonicalTool === "ste_synthesize_wav" && "audio_path" in args) {
      const check = validateHostTargetPath(args.audio_path, workspaceRoot, "audio_path", {
        isDirectory: false,
        requireDocumentExtension: false,
      });
      if (!check.ok) return check;
      if (path.extname(check.resolved).toLowerCase() !== ".wav") {
        return {
          ok: false,
          code: ERROR_INVALID_INPUT,
          message: "audio_path must end with .wav.",
        };
      }
    }
  }

  if (canonicalTool === "ste_inspect_artifact" && "headless_browser" in args) {
    if (typeof args.headless_browser !== "boolean") {
      return {
        ok: false,
        code: ERROR_INVALID_INPUT,
        message: "headless_browser must be a boolean.",
      };
    }
    if (args.headless_browser === true) {
      return {
        ok: false,
        code: ERROR_UNSUPPORTED_OPERATION,
        message:
          "Headless browser inspection is not supported in this local adapter because an isolated no-network browser sandbox is not provisioned; use static local inspection (headless_browser=false).",
      };
    }
  }

  if (canonicalTool !== "ste_status") {
    const rt = resolveTrustedRuntime(env);
    if (!rt.available) {
      return {
        ok: false,
        code: rt.error?.code || ERROR_DEPENDENCY_MISSING,
        message: `STE-Pro-Max policy backend unavailable (${rt.error?.code || ERROR_DEPENDENCY_MISSING}): ${rt.error?.message || "SkillC runtime is unavailable."}`,
      };
    }
  }

  return { ok: true };
}

export function evaluateSteToolIntercept({
  toolName,
  toolInput,
  workspaceRoot,
  env = process.env,
}) {
  const rawName = String(toolName || "").trim();
  const lower = rawName.toLowerCase();
  const args = toolInput && typeof toolInput === "object" && !Array.isArray(toolInput) ? toolInput : {};

  // 1. Raw file mutations refused cheaply before execution
  if (RAW_MUTATION_TOOLS.has(lower)) {
    return {
      allow: false,
      code: ERROR_POLICY_REFUSAL,
      message:
        `STE-Pro-Max policy refuses raw file mutation tool ${JSON.stringify(rawName)} while in STE scope. ` +
        "Use guarded STE-Pro-Max tools (`ste_write_artifact`, `ste_render_bundle`, `ste_render_artifact`, `ste_regenerate_gallery`, `ste_export_bundle`).",
    };
  }

  // 2. Raw shells, Code Mode execute, and PTY tools refused cheaply without regex whitelisting
  if (RAW_SHELL_AND_CODEMODE_TOOLS.has(lower)) {
    return {
      allow: false,
      code: ERROR_POLICY_REFUSAL,
      message:
        `STE-Pro-Max policy refuses raw shell/Code Mode/PTY tool ${JSON.stringify(rawName)} while in STE scope. ` +
        "Use top-level guarded STE-Pro-Max tools (`ste_write_artifact`, `ste_render_bundle`, `ste_render_artifact`, `ste_inspect_artifact`, `ste_check_prose`).",
    };
  }

  // 3. Host/worktree/memory mutations refused cheaply
  if (OPAQUE_HOST_MUTATION_TOOLS.has(lower)) {
    return {
      allow: false,
      code: ERROR_POLICY_REFUSAL,
      message: `STE-Pro-Max policy refuses host/worktree/store mutation tool ${JSON.stringify(rawName)} while in STE scope.`,
    };
  }

  // 4. Opaque GUI / browser / external ACP tools refused cheaply
  if (OPAQUE_AGENT_PREFIXES.some((prefix) => lower.startsWith(prefix))) {
    return {
      allow: false,
      code: ERROR_POLICY_REFUSAL,
      message:
        `STE-Pro-Max policy refuses opaque/GUI/ACP tool ${JSON.stringify(rawName)} while in STE scope. ` +
        "Use `ste_inspect_artifact` for bounded local inspection.",
    };
  }

  // 5. Guarded STE tools
  const steMatch = isSteToolName(rawName);
  if (steMatch.matched) {
    const pre = prevalidateSteToolCall(steMatch.canonical, args, workspaceRoot, env);
    if (!pre.ok) {
      return {
        allow: false,
        code: pre.code || ERROR_POLICY_REFUSAL,
        message: pre.message,
      };
    }
    return { allow: true, canonicalSteTool: steMatch.canonical };
  }

  // 6. Subagent / task delegation
  if (lower === "subagent" || lower === "task" || lower === "delegate") {
    const targetAgent = String(
      args.agent ?? args.agent_type ?? args.agentName ?? args.subagent_type ?? "",
    )
      .trim()
      .toLowerCase();
    if (
      BLOCKED_SUBAGENT_NAMES.has(targetAgent) ||
      OPAQUE_AGENT_PREFIXES.some((prefix) => targetAgent.startsWith(prefix))
    ) {
      return {
        allow: false,
        code: ERROR_POLICY_REFUSAL,
        message: `STE-Pro-Max policy refuses spawning external ACP or opaque subagent ${JSON.stringify(targetAgent)} while in STE scope.`,
      };
    }
    return {
      allow: true,
      resumedChildSessionID: typeof args.sessionID === "string" && args.sessionID.trim() ? args.sessionID.trim() : null,
      targetAgent,
    };
  }

  // 7. Safe read / discovery / navigation tools
  if (
    SAFE_READ_AND_NAVIGATION_TOOLS.has(lower) ||
    SAFE_READONLY_MCP_PREFIXES.some((prefix) => lower.startsWith(prefix))
  ) {
    if (lower === "read" || lower === "view" || lower === "grep" || lower === "glob") {
      const credErr = isBlockedCredentialRead(args);
      if (credErr) {
        return {
          allow: false,
          code: ERROR_POLICY_REFUSAL,
          message: credErr,
        };
      }
    }
    return { allow: true };
  }

  // 8. Unknown or unclassified tool in STE scope -> fail closed
  return {
    allow: false,
    code: ERROR_POLICY_REFUSAL,
    message: `STE-Pro-Max policy refuses unguarded tool ${JSON.stringify(rawName)} while in STE scope.`,
  };
}

// ---------------------------------------------------------------------------
// Session Scope Persistence, Context Recovery, and Parent Inheritance
// ---------------------------------------------------------------------------

function sessionsStateDir(env = process.env) {
  const dir = path.join(resolveStateRoot(env), "opencode-sessions");
  fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
  return dir;
}

function sessionRecordPath(sessionID, env = process.env) {
  const digest = sha256Hex(sessionID).slice(0, 32);
  return path.join(sessionsStateDir(env), `session-${digest}.json`);
}

export function loadDiskSessionRecord(sessionID, env = process.env) {
  if (typeof sessionID !== "string" || !sessionID.trim()) return null;
  const filePath = sessionRecordPath(sessionID.trim(), env);
  try {
    const st = fs.lstatSync(filePath);
    if (!st.isFile() || st.isSymbolicLink()) return null;
    const parsed = JSON.parse(fs.readFileSync(filePath, "utf8"));
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export function saveDiskSessionRecord(sessionID, record, env = process.env) {
  if (typeof sessionID !== "string" || !sessionID.trim()) return null;
  const cleanID = sessionID.trim();
  const filePath = sessionRecordPath(cleanID, env);
  const payload = {
    schema: "ste-promax.opencode-session-scope.v1",
    session_id: cleanID,
    active: Boolean(record?.active),
    reason: String(record?.reason || ""),
    parent_session_id: record?.parent_session_id || null,
    agent_id: record?.agent_id || null,
    working_directory: record?.working_directory || null,
    context_min_index: Number.isInteger(record?.context_min_index) ? record.context_min_index : 0,
    last_preflight: record?.last_preflight || null,
    last_prose_diagnostic: record?.last_prose_diagnostic || null,
    prose_diagnostic_count: Number.isInteger(record?.prose_diagnostic_count) ? record.prose_diagnostic_count : 0,
    updated_at: new Date().toISOString(),
  };
  const tmpPath = path.join(path.dirname(filePath), `.${path.basename(filePath)}.tmp-${process.pid}-${Date.now()}`);
  fs.writeFileSync(tmpPath, JSON.stringify(payload, null, 2) + "\n", { encoding: "utf8", mode: 0o600 });
  fs.renameSync(tmpPath, filePath);
  return payload;
}

export function scanContextMessagesForScope(
  messages,
  { minIndex = 0, workspaceRoot = null, bundleRoot = BUNDLE_ROOT } = {},
) {
  if (!Array.isArray(messages)) {
    return { foundTransition: false, active: null, reason: null, messageCount: 0 };
  }
  let foundTransition = false;
  let active = null;
  let reason = null;

  for (let idx = 0; idx < messages.length; idx++) {
    if (idx < minIndex) continue;
    const msg = messages[idx];
    if (!msg || typeof msg !== "object") continue;
    const msgType = msg.type;

    if (msgType === "skill") {
      const skillId = msg.skill ?? msg.id ?? msg.name;
      if (isSteSkillIdentifier(skillId) || isSteSkillIdentifier(msg.name)) {
        foundTransition = true;
        active = true;
        reason = `context:skill:${skillId || msg.name}`;
      }
    } else if (msgType === "agent-switched") {
      if (isSteAgentIdentifier(msg.agent)) {
        foundTransition = true;
        active = true;
        reason = `context:agent:${msg.agent}`;
      }
    } else if (msgType === "user") {
      if (isExplicitUserSteOff(msg.text)) {
        foundTransition = true;
        active = false;
        reason = "context:user:/ste-off";
        continue;
      }
      if (Array.isArray(msg.skills)) {
        for (const sk of msg.skills) {
          const sid = sk?.id ?? sk?.name ?? sk;
          if (isSteSkillIdentifier(sid) || isSteSkillIdentifier(sk?.name)) {
            foundTransition = true;
            active = true;
            reason = `context:user.skills:${sid}`;
          }
        }
      }
      if (Array.isArray(msg.agents)) {
        for (const ag of msg.agents) {
          const aName = ag?.name ?? ag;
          if (isSteAgentIdentifier(aName)) {
            foundTransition = true;
            active = true;
            reason = `context:user.agents:${aName}`;
          }
        }
      }
    } else if (msgType === "assistant" && Array.isArray(msg.content)) {
      for (const part of msg.content) {
        if (!part || typeof part !== "object" || part.type !== "tool") continue;
        const tName = String(part.name || "").trim();
        const rawInput = part.state?.input;
        let tInput = {};
        if (rawInput && typeof rawInput === "object" && !Array.isArray(rawInput)) {
          tInput = rawInput;
        } else if (typeof rawInput === "string" && rawInput.trim().startsWith("{")) {
          try {
            tInput = JSON.parse(rawInput);
          } catch {
            tInput = {};
          }
        }
        if (tName === "skill" || tName === "Skill") {
          const sArg = tInput.id ?? tInput.skill ?? tInput.name;
          if (isSteSkillIdentifier(sArg)) {
            foundTransition = true;
            active = true;
            reason = `context:tool.skill:${sArg}`;
          }
        } else if (tName === "read" || tName === "view" || tName === "Read") {
          const pArg = tInput.path ?? tInput.file_path ?? tInput.filePath;
          if (isExactSteSkillMdPath(pArg, workspaceRoot, bundleRoot)) {
            foundTransition = true;
            active = true;
            reason = "context:tool.read:SKILL.md";
          }
        } else {
          const steTool = isSteToolName(tName);
          if (steTool.matched) {
            foundTransition = true;
            active = true;
            reason = `context:tool.ste:${steTool.canonical}`;
          }
        }
      }
    }
  }

  return {
    foundTransition,
    active,
    reason,
    messageCount: messages.length,
  };
}

// ---------------------------------------------------------------------------
// Bounded CLI JSON Dispatcher Client (`dispatch.py`)
// ---------------------------------------------------------------------------

export async function runPythonDispatcher(
  op,
  args = {},
  {
    workspaceRoot,
    sessionID = null,
    bundleRoot = BUNDLE_ROOT,
    dispatchPyPath = DISPATCH_PY_PATH,
    env = process.env,
    timeoutMs = 60000,
  } = {},
) {
  const wsCheck = checkSafeLexicalPath(workspaceRoot, "Trusted workspace root", { requireAbsolute: true });
  if (!wsCheck.ok) {
    return { ok: false, error: { code: wsCheck.code || ERROR_INVALID_INPUT, message: wsCheck.message } };
  }

  const rt = resolveTrustedRuntime(env);
  if (!rt.available) {
    if (op === "ste_status") {
      return {
        ok: true,
        result: {
          schema: "ste-promax.policy-status.v1",
          available: false,
          mode: "unavailable",
          authority_model: "automatic-local-policy",
          manual_approval_required: false,
          host_adapter: OPENCODE_PLUGIN_ID,
          bundle_root: bundleRoot,
          workspace_root: wsCheck.resolved,
          error: rt.error,
        },
      };
    }
    if (op === "ste_preflight_turn") {
      return {
        ok: true,
        result: {
          schema: "ste-promax.opencode-turn-preflight.v1",
          status: "degraded_readonly_only",
          policy_available: false,
          policy_mode: "unavailable",
          policy_error: rt.error,
          bundle_root: bundleRoot,
          workspace_root: wsCheck.resolved,
          readonly_help_permitted: true,
          effectful_tools_permitted: false,
        },
      };
    }
    if (op === "ste_postprocess_prose") {
      return {
        ok: true,
        result: {
          schema: "ste-promax.opencode-prose-postprocess.v1",
          status: "skipped_missing_runtime",
          delivery_timing: "post_stream_advisory",
          pre_display_guaranteed: false,
          policy_error: rt.error,
        },
      };
    }
    return {
      ok: false,
      error: rt.error || {
        code: ERROR_DEPENDENCY_MISSING,
        message: "STE-Pro-Max SkillC runtime is unavailable.",
      },
    };
  }

  const payloadStr = JSON.stringify({
    action: op,
    op,
    args,
    session_id: sessionID,
  });

  const childEnv = {
    ...env,
    STE_PROMAX_PLUGIN_ROOT: bundleRoot,
    STE_TRUSTED_WORKSPACE: wsCheck.resolved,
    PYTHONIOENCODING: "utf-8",
  };

  return await new Promise((resolve) => {
    const child = execFile(
      rt.pythonExe,
      ["-I", "-B", dispatchPyPath, "--workspace-root", wsCheck.resolved, "--action", op],
      {
        cwd: wsCheck.resolved,
        env: childEnv,
        timeout: timeoutMs,
        maxBuffer: 16 * 1024 * 1024,
        windowsHide: true,
        shell: false,
      },
      (error, stdout, stderr) => {
        const outText = String(stdout || "").trim();
        if (outText) {
          const lastLine = outText.split(/\r?\n/).at(-1) || outText;
          try {
            const parsed = JSON.parse(lastLine);
            if (parsed && typeof parsed === "object") {
              resolve(parsed);
              return;
            }
          } catch {
            // Fall through to error formatting below
          }
        }
        const errMsg = String(stderr || error?.message || "Python dispatcher failed without JSON output.").trim();
        resolve({
          ok: false,
          error: {
            code: ERROR_POLICY_REFUSAL,
            message: errMsg,
          },
        });
      },
    );

    if (child.stdin) {
      child.stdin.on("error", () => {});
      child.stdin.end(payloadStr, "utf8");
    }
  });
}

// ---------------------------------------------------------------------------
// Tool Definitions (`options: { codemode: false }`)
// ---------------------------------------------------------------------------

export const STE_TOOL_SCHEMAS = {
  ste_status: {
    description:
      "Return current STE-Pro-Max automatic SkillC policy status, installed bundle root, trusted workspace root, and latest policy receipt.",
    input: {
      type: "object",
      properties: {},
      additionalProperties: false,
    },
  },
  ste_check_prose: {
    description:
      "Run guarded STE-Pro-Max advisory prose diagnostics on inline text or a workspace file. Preserves source and semantic limitations as warnings.",
    input: {
      type: "object",
      properties: {
        text: { type: "string", description: "Inline UTF-8 prose text to check." },
        source_path: { type: "string", description: "Workspace-relative path to a markdown/text file to check." },
        profile: {
          type: "string",
          enum: ["relaxed", "procedure", "description"],
          description: "STE prose profile (default: relaxed).",
        },
      },
      additionalProperties: false,
    },
  },
  ste_write_artifact: {
    description:
      "Write or update a host-authored STE-Pro-Max UTF-8 artifact or document (.html, .svg, .md, .json, .yaml, .yml, .txt, .vtt, .css) inside the workspace under automatic SkillC precondition and postcondition verification.",
    input: {
      type: "object",
      properties: {
        target_path: { type: "string", description: "Workspace-confined target file path." },
        content: { type: "string", description: "Full UTF-8 text content to write." },
        expected_before_sha256: {
          type: ["string", "null"],
          description: "Required 64-char SHA-256 hex digest of existing file when updating; omit or null for a new file.",
        },
        source_paths: {
          type: "array",
          items: { type: "string" },
          description: "Optional read-only source file paths inside the workspace.",
        },
        evidence_paths: {
          type: "array",
          items: { type: "string" },
          description: "Optional explicit evidence file paths.",
        },
        evidence_root: { type: ["string", "null"], description: "Optional explicit evidence root directory." },
        source_kind: {
          type: "string",
          enum: ["host_content", "raw_html", "structured", "markdown", "story"],
          description: "Artifact source kind (default: host_content).",
        },
        trusted_html: {
          type: "boolean",
          description: "Explicit trust flag required only when source_kind is raw_html.",
        },
      },
      required: ["target_path", "content"],
      additionalProperties: false,
    },
  },
  ste_render_bundle: {
    description:
      "Render a complete native STE-Pro-Max artifact bundle (.html, .DESIGN.md, .meta.yaml, gallery.html, manifest.json) into a workspace directory.",
    input: {
      type: "object",
      properties: {
        input_path: { type: "string", description: "Path to source input file inside the workspace or bundle examples." },
        output_dir: { type: "string", description: "Target bundle output directory inside the workspace." },
        title: { type: ["string", "null"], description: "Optional artifact title override." },
        design_path: { type: ["string", "null"], description: "Optional DESIGN.md path." },
        evidence: {
          type: "array",
          items: { type: "string" },
          description: "Optional explicit evidence file paths.",
        },
        evidence_root: { type: ["string", "null"], description: "Optional explicit evidence root directory." },
        trusted_html: { type: "boolean", description: "Explicit trust flag for imported raw HTML inputs." },
      },
      required: ["input_path", "output_dir"],
      additionalProperties: false,
    },
  },
  ste_render_artifact: {
    description:
      "Render a direct STE-Pro-Max HTML/DESIGN/meta triple into a workspace directory from a source file or structured input_data.",
    input: {
      type: "object",
      properties: {
        output_dir: { type: "string", description: "Target artifact directory inside the workspace." },
        input_path: { type: ["string", "null"], description: "Source file path (mutually exclusive with input_data)." },
        input_data: { type: ["object", "null"], description: "Structured JSON input data (mutually exclusive with input_path)." },
        title: { type: ["string", "null"], description: "Optional artifact title." },
        design_path: { type: ["string", "null"], description: "Optional DESIGN.md path." },
        trusted_html: { type: "boolean", description: "Explicit trust flag for raw HTML inputs." },
      },
      required: ["output_dir"],
      additionalProperties: false,
    },
  },
  ste_regenerate_gallery: {
    description: "Regenerate gallery.html for an artifact directory inside the workspace.",
    input: {
      type: "object",
      properties: {
        artifact_dir: { type: "string", description: "Artifact directory inside the workspace." },
      },
      required: ["artifact_dir"],
      additionalProperties: false,
    },
  },
  ste_prepare_story_media: {
    description:
      "Prepare local evidence-linked story media (composition, captions, transcript, review.html, and verified non-silent PCM WAV audio) inside a workspace directory.",
    input: {
      type: "object",
      properties: {
        input_path: { type: "string", description: "Path to story JSON input file." },
        output_dir: { type: "string", description: "Target output directory inside the workspace." },
        voice: { type: ["string", "null"], description: "Optional TTS voice name." },
        audio_dir: { type: ["string", "null"], description: "Optional pre-rendered WAV directory." },
      },
      required: ["input_path", "output_dir"],
      additionalProperties: false,
    },
  },
  ste_synthesize_wav: {
    description: "Synthesize a verified non-silent PCM WAV file from a workspace text file.",
    input: {
      type: "object",
      properties: {
        text_path: { type: "string", description: "Source text file inside the workspace." },
        audio_path: { type: "string", description: "Target .wav file path inside the workspace." },
        voice: { type: ["string", "null"], description: "Optional TTS voice name." },
      },
      required: ["text_path", "audio_path"],
      additionalProperties: false,
    },
  },
  ste_inspect_artifact: {
    description:
      "Perform bounded static local inspection of an artifact file or bundle directory inside the workspace. Never accepts arbitrary code; does not perform browser QA or claim a network sandbox (headless_browser=true is rejected as unsupported_operation).",
    input: {
      type: "object",
      properties: {
        target_path: { type: "string", description: "Target artifact file or bundle directory inside the workspace." },
        headless_browser: {
          type: "boolean",
          description: "Must be false or omitted. Headless browser execution is rejected as unsupported_operation.",
        },
      },
      required: ["target_path"],
      additionalProperties: false,
    },
  },
  ste_export_bundle: {
    description:
      "Automatically verify a fresh native STE-Pro-Max bundle and export it into a new destination directory inside the workspace without manual approval.",
    input: {
      type: "object",
      properties: {
        input_dir: { type: "string", description: "Source bundle directory inside the workspace." },
        output_dir: { type: "string", description: "New destination directory inside the workspace." },
        evidence: {
          type: "array",
          items: { type: "string" },
          description: "Optional explicit evidence file paths.",
        },
        evidence_root: { type: ["string", "null"], description: "Optional explicit evidence root directory." },
      },
      required: ["input_dir", "output_dir"],
      additionalProperties: false,
    },
  },
};

// ---------------------------------------------------------------------------
// Session Scope Manager (wires in-memory cache, disk state, storage, session API)
// ---------------------------------------------------------------------------

export function createScopeManager({
  defaultWorkspaceRoot,
  bundleRoot = BUNDLE_ROOT,
  dispatchPyPath = DISPATCH_PY_PATH,
  env = process.env,
  getSessionInfo = async () => null,
  getSessionContext = async () => [],
  storageGet = async () => undefined,
  storageSet = async () => {},
} = {}) {
  const memoryRecords = new Map();
  const processedTextEnded = new Set();

  function getCachedOrDisk(sessionID) {
    if (!sessionID) return null;
    const mem = memoryRecords.get(sessionID);
    if (mem) return mem;
    const disk = loadDiskSessionRecord(sessionID, env);
    if (disk) {
      memoryRecords.set(sessionID, disk);
      return disk;
    }
    return null;
  }

  async function persistRecord(sessionID, partial) {
    const existing = getCachedOrDisk(sessionID) || {};
    const merged = {
      ...existing,
      ...partial,
      session_id: sessionID,
    };
    const saved = saveDiskSessionRecord(sessionID, merged, env) || merged;
    memoryRecords.set(sessionID, saved);
    try {
      await storageSet(`ste:session:${sessionID}`, saved);
    } catch {
      // Storage errors must not break scope persistence
    }
    return saved;
  }

  async function resolveWorkspaceForSession(sessionID) {
    if (sessionID) {
      try {
        const info = await getSessionInfo(sessionID);
        const dir = info?.location?.directory ?? info?.directory;
        if (typeof dir === "string" && dir.trim()) {
          const check = checkSafeLexicalPath(dir.trim(), "session.location.directory", {
            requireAbsolute: true,
          });
          if (check.ok) return check.resolved;
        }
      } catch {
        // Ignore session.get failure and fall back to persisted session / location directory
      }
    }
    const rec = getCachedOrDisk(sessionID);
    if (rec?.working_directory) {
      const check = checkSafeLexicalPath(rec.working_directory, "session working_directory", {
        requireAbsolute: true,
      });
      if (check.ok) return check.resolved;
    }
    if (typeof defaultWorkspaceRoot === "string" && defaultWorkspaceRoot.trim()) {
      const check = checkSafeLexicalPath(defaultWorkspaceRoot.trim(), "ctx.location.directory", {
        requireAbsolute: true,
      });
      if (check.ok) return check.resolved;
    }
    return null;
  }

  async function activateScope(sessionID, reason, extra = {}) {
    if (typeof sessionID !== "string" || !sessionID.trim()) return null;
    const cleanID = sessionID.trim();
    const ws = extra.working_directory || (await resolveWorkspaceForSession(cleanID));
    return await persistRecord(cleanID, {
      ...extra,
      active: true,
      reason,
      working_directory: ws,
    });
  }

  async function deactivateScope(sessionID, reason = "user:/ste-off", { contextMessageCount = null } = {}) {
    if (typeof sessionID !== "string" || !sessionID.trim()) return null;
    const cleanID = sessionID.trim();
    let minIndex = contextMessageCount;
    if (!Number.isInteger(minIndex)) {
      try {
        const msgs = await getSessionContext(cleanID);
        minIndex = Array.isArray(msgs) ? msgs.length : 0;
      } catch {
        minIndex = 0;
      }
    }
    return await persistRecord(cleanID, {
      active: false,
      reason,
      context_min_index: minIndex,
    });
  }

  async function bindParentSession(childSessionID, parentSessionID, extra = {}) {
    if (!childSessionID || !parentSessionID || childSessionID === parentSessionID) return null;
    const existing = getCachedOrDisk(childSessionID) || {};
    return await persistRecord(childSessionID, {
      ...existing,
      ...extra,
      parent_session_id: parentSessionID,
    });
  }

  async function isSessionScoped(sessionID, visited = new Set()) {
    if (typeof sessionID !== "string" || !sessionID.trim()) {
      return { active: false, reason: "missing_session_id", workspaceRoot: defaultWorkspaceRoot };
    }
    const cleanID = sessionID.trim();
    if (visited.has(cleanID)) {
      return {
        active: true,
        uncertainScope: true,
        reason: `ancestor_cycle_detected:${cleanID}`,
        workspaceRoot: defaultWorkspaceRoot,
      };
    }
    if (visited.size >= MAX_ANCESTOR_DEPTH) {
      return {
        active: true,
        uncertainScope: true,
        reason: `ancestor_depth_limit_exceeded:${cleanID}`,
        workspaceRoot: defaultWorkspaceRoot,
      };
    }
    visited.add(cleanID);

    const ws = await resolveWorkspaceForSession(cleanID);
    let rec = getCachedOrDisk(cleanID);
    if (!rec) {
      try {
        const stored = await storageGet(`ste:session:${cleanID}`);
        if (stored && typeof stored === "object" && !Array.isArray(stored)) {
          rec = stored;
          memoryRecords.set(cleanID, rec);
        }
      } catch {
        rec = null;
      }
    }

    // 1. Scan typed session context messages (`ctx.session.context`)
    const minIndex = Number.isInteger(rec?.context_min_index) ? rec.context_min_index : 0;
    try {
      const messages = await getSessionContext(cleanID);
      if (Array.isArray(messages) && messages.length > 0) {
        const scan = scanContextMessagesForScope(messages, {
          minIndex,
          workspaceRoot: ws,
          bundleRoot,
        });
        if (scan.foundTransition) {
          if (scan.active === false) {
            const deactivated = await deactivateScope(cleanID, scan.reason || "context:user:/ste-off", {
              contextMessageCount: scan.messageCount,
            });
            return { active: false, reason: deactivated.reason, workspaceRoot: ws };
          }
          if (scan.active === true) {
            const activated = await activateScope(cleanID, scan.reason || "context:skill", {
              working_directory: ws,
            });
            return { active: true, reason: activated.reason, workspaceRoot: ws };
          }
        }
      }
    } catch {
      // Ignore context fetch errors and fall back to persisted state / parent inheritance
    }

    // 2. Check persisted active flag
    if (rec?.active === true) {
      return { active: true, reason: rec.reason || "persisted", workspaceRoot: ws };
    }

    // 3. Check session info (`agent` and `parentID` / `fork.sessionID`)
    let parentID = rec?.parent_session_id || null;
    let sessionAgent = rec?.agent_id || null;
    try {
      const info = await getSessionInfo(cleanID);
      if (info && typeof info === "object") {
        if (typeof info.agent === "string" && info.agent.trim()) {
          sessionAgent = info.agent.trim();
        }
        const candidateParent = info.parentID ?? info.fork?.sessionID ?? null;
        if (typeof candidateParent === "string" && candidateParent.trim()) {
          parentID = candidateParent.trim();
        }
      }
    } catch {
      // Ignore session.get failure
    }

    if (sessionAgent && isSteAgentIdentifier(sessionAgent)) {
      const activated = await activateScope(cleanID, `session.agent:${sessionAgent}`, {
        agent_id: sessionAgent,
        parent_session_id: parentID,
        working_directory: ws,
      });
      return { active: true, reason: activated.reason, workspaceRoot: ws };
    }

    // 4. Inherit from parent session (including resumed children)
    if (parentID && parentID !== cleanID) {
      const parentScope = await isSessionScoped(parentID, visited);
      if (parentScope.uncertainScope) {
        return {
          active: true,
          uncertainScope: true,
          reason: `inherited_uncertain_from:${parentID}(${parentScope.reason})`,
          workspaceRoot: ws,
        };
      }
      if (parentScope.active) {
        // Only block an external ACP child when its ancestor scope is actually STE-active
        if (sessionAgent && BLOCKED_SUBAGENT_NAMES.has(sessionAgent.toLowerCase())) {
          return {
            active: true,
            reason: `blocked_external_child_from:${parentID}`,
            workspaceRoot: ws,
            blockedExternalChild: true,
          };
        }
        const inheritedReason = `inherited_from:${parentID}(${parentScope.reason})`;
        const activated = await activateScope(cleanID, inheritedReason, {
          parent_session_id: parentID,
          agent_id: sessionAgent,
          working_directory: ws,
        });
        return { active: true, reason: activated.reason, workspaceRoot: ws };
      }
    }

    return { active: false, reason: rec?.reason || "non-ste-session", workspaceRoot: ws };
  }

  async function handlePromptHook(event) {
    const sessionID = String(event?.sessionID || "").trim();
    if (!sessionID) return { active: false };
    const prompt = event?.prompt;
    if (!prompt || typeof prompt !== "object") return await isSessionScoped(sessionID);

    // Explicit user /ste-off in user prompt
    if (isExplicitUserSteOff(prompt.text)) {
      await deactivateScope(sessionID, "prompt:user:/ste-off");
      return { active: false, reason: "prompt:user:/ste-off", explicitSteOff: true };
    }

    // Check attached skills on user prompt
    if (Array.isArray(prompt.skills)) {
      for (const item of prompt.skills) {
        const sid = item?.id ?? item?.name ?? item;
        if (isSteSkillIdentifier(sid)) {
          await activateScope(sessionID, `prompt.skill:${sid}`);
          return { active: true, reason: `prompt.skill:${sid}` };
        }
      }
    }

    // Check attached agents on user prompt
    if (Array.isArray(prompt.agents)) {
      for (const item of prompt.agents) {
        const aName = item?.name ?? item;
        if (isSteAgentIdentifier(aName)) {
          await activateScope(sessionID, `prompt.agent:${aName}`);
          return { active: true, reason: `prompt.agent:${aName}` };
        }
      }
    }

    return await isSessionScoped(sessionID);
  }

  async function handleContextHook(event) {
    const sessionID = String(event?.sessionID || "").trim();
    if (!sessionID) return { active: false };
    const scope = await isSessionScoped(sessionID);
    if (!scope.active) return scope;

    // Extract latest user prompt text for turn preflight
    let lastUserText = "";
    if (Array.isArray(event.messages)) {
      for (let i = event.messages.length - 1; i >= 0; i--) {
        const m = event.messages[i];
        if (m && m.role === "user") {
          if (typeof m.content === "string") {
            lastUserText = m.content;
          } else if (Array.isArray(m.content)) {
            lastUserText = m.content
              .filter((p) => p && p.type === "text" && typeof p.text === "string")
              .map((p) => p.text)
              .join("\n");
          }
          break;
        }
      }
    }

    const promptSha = sha256Hex(lastUserText);
    const existing = getCachedOrDisk(sessionID) || {};
    let preflightResult = existing.last_preflight;
    if (!preflightResult || preflightResult.prompt_sha256 !== promptSha) {
      const preflight = await runPythonDispatcher(
        "ste_preflight_turn",
        { prompt_text: lastUserText, profile: "relaxed" },
        {
          workspaceRoot: scope.workspaceRoot,
          sessionID,
          bundleRoot,
          dispatchPyPath,
          env,
        },
      );
      preflightResult = preflight.result || preflight.error || null;
      await persistRecord(sessionID, {
        ...existing,
        active: true,
        last_preflight: preflightResult,
      });
    }

    if (Array.isArray(event.system)) {
      const marker = "<!-- ste-promax:automatic-local-policy -->";
      const alreadyPresent = event.system.some(
        (part) => part && typeof part.text === "string" && part.text.includes(marker),
      );
      if (!alreadyPresent) {
        const backendNote =
          preflightResult?.policy_available === false
            ? "SkillC policy runtime is currently unavailable: read-only prose assistance remains available, while effectful artifact tools will fail closed."
            : "SkillC automatic precondition/execution/postcondition policy is active with no manual approval steps.";
        event.system.push({
          type: "text",
          text:
            `${marker}\n` +
            `STE-Pro-Max session scope is active (${scope.reason}). ${backendNote}\n` +
            "Raw file mutation tools (`write`, `edit`, `apply_patch`), raw shells (`shell`, `bash`, `powershell`), Code Mode (`execute`), PTY, GUI, and external ACP tools are refused in STE scope. " +
            "Use top-level guarded STE tools (`ste_write_artifact`, `ste_render_bundle`, `ste_render_artifact`, `ste_regenerate_gallery`, `ste_prepare_story_media`, `ste_synthesize_wav`, `ste_inspect_artifact`, `ste_export_bundle`, `ste_check_prose`, `ste_status`).",
        });
      }
    }

    return { ...scope, preflight: preflightResult };
  }

  async function handleExecuteBefore(event) {
    const sessionID = String(event?.sessionID || "").trim();
    const rawTool = String(event?.tool || "").trim();
    const rawInput = event?.input;
    const toolArgs =
      rawInput && typeof rawInput === "object" && !Array.isArray(rawInput) ? rawInput : {};

    const ws = await resolveWorkspaceForSession(sessionID);
    let scope = await isSessionScoped(sessionID);

    if (scope.blockedExternalChild) {
      return {
        allow: false,
        code: ERROR_POLICY_REFUSAL,
        message: "STE-Pro-Max policy refuses external ACP target masquerading as a child session.",
      };
    }

    if (scope.uncertainScope) {
      const lowerTool = rawTool.toLowerCase();
      const steTool = isSteToolName(rawTool);
      const effectiveTool = steTool.matched ? steTool.canonical : lowerTool;
      if (UNCERTAIN_SCOPE_READONLY_TOOLS.has(effectiveTool)) {
        if (effectiveTool === "read" || effectiveTool === "view" || effectiveTool === "grep" || effectiveTool === "glob") {
          const credErr = isBlockedCredentialRead(toolArgs);
          if (credErr) {
            return {
              allow: false,
              code: ERROR_POLICY_REFUSAL,
              message: credErr,
            };
          }
        }
        return { allow: true, uncertainScope: true };
      }
      return {
        allow: false,
        code: ERROR_POLICY_REFUSAL,
        message:
          `STE-Pro-Max policy refuses effectful tool ${JSON.stringify(rawTool)} because session ancestor scope is unresolved (${scope.reason}). ` +
          "Read-only diagnosis (`ste_status`, `read`, `glob`, `grep`) remains available.",
      };
    }

    // Check if this tool call itself activates STE scope
    if (rawTool === "skill" || rawTool === "Skill") {
      const skillArg = toolArgs.id ?? toolArgs.skill ?? toolArgs.name;
      if (isSteSkillIdentifier(skillArg)) {
        await activateScope(sessionID, `tool.skill:${skillArg}`, { working_directory: ws });
        return { allow: true, activated: true };
      }
    } else if (rawTool === "read" || rawTool === "view" || rawTool === "Read") {
      const pathArg = toolArgs.path ?? toolArgs.file_path ?? toolArgs.filePath;
      if (isExactSteSkillMdPath(pathArg, ws, bundleRoot)) {
        await activateScope(sessionID, "tool.read:SKILL.md", { working_directory: ws });
        scope = await isSessionScoped(sessionID);
      }
    } else {
      const steTool = isSteToolName(rawTool);
      if (steTool.matched) {
        await activateScope(sessionID, `tool.ste:${steTool.canonical}`, { working_directory: ws });
        scope = await isSessionScoped(sessionID);
      }
    }

    if (!scope.active) {
      return { allow: true, active: false };
    }

    const decision = evaluateSteToolIntercept({
      toolName: rawTool,
      toolInput: toolArgs,
      workspaceRoot: scope.workspaceRoot || ws,
      env,
    });

    if (decision.allow && decision.resumedChildSessionID) {
      await activateScope(
        decision.resumedChildSessionID,
        `inherited_from:${sessionID}(resumed_subagent)`,
        {
          parent_session_id: sessionID,
          agent_id: decision.targetAgent || null,
          working_directory: scope.workspaceRoot || ws,
        },
      );
    }

    return decision;
  }

  async function handleServerEvent(event) {
    if (!event || typeof event !== "object") return null;
    const type = event.type;
    const data = event.data && typeof event.data === "object" ? event.data : {};

    if (type === "session.skill.activated") {
      const sessionID = String(data.sessionID || "").trim();
      const skillID = data.id ?? data.name;
      if (sessionID && (isSteSkillIdentifier(skillID) || isSteSkillIdentifier(data.name))) {
        return await activateScope(sessionID, `event:session.skill.activated:${skillID}`);
      }
      return null;
    }

    if (type === "session.created" || type === "session.forked") {
      const sessionID = String(data.sessionID || "").trim();
      const parentID = String(data.parentID || "").trim();
      const dir = data.location?.directory;
      if (sessionID && parentID) {
        await bindParentSession(sessionID, parentID, {
          agent_id: typeof data.agent === "string" ? data.agent : null,
          working_directory: typeof dir === "string" ? dir : null,
        });
        const parentScope = await isSessionScoped(parentID);
        if (parentScope.active) {
          return await activateScope(sessionID, `inherited_from:${parentID}(${parentScope.reason})`, {
            parent_session_id: parentID,
            agent_id: typeof data.agent === "string" ? data.agent : null,
            working_directory: typeof dir === "string" ? dir : parentScope.workspaceRoot,
          });
        }
      }
      return null;
    }

    if (type === "session.moved") {
      const sessionID = String(data.sessionID || "").trim();
      const dir = data.location?.directory;
      if (sessionID && typeof dir === "string" && dir.trim()) {
        const check = checkSafeLexicalPath(dir.trim(), "session.moved.location.directory", {
          requireAbsolute: true,
        });
        if (check.ok) {
          const existing = getCachedOrDisk(sessionID) || {};
          return await persistRecord(sessionID, {
            ...existing,
            working_directory: check.resolved,
          });
        }
      }
      return null;
    }

    if (type === "session.agent.selected") {
      const sessionID = String(data.sessionID || "").trim();
      if (sessionID && isSteAgentIdentifier(data.agent)) {
        return await activateScope(sessionID, `event:session.agent.selected:${data.agent}`, {
          agent_id: String(data.agent),
        });
      }
      return null;
    }

    if (type === "session.inbox.enqueued") {
      const sessionID = String(data.sessionID || "").trim();
      const item = data.item;
      if (!sessionID || !item || typeof item !== "object" || item.type !== "user") return null;
      const payload = item.payload && typeof item.payload === "object" ? item.payload : {};
      if (isExplicitUserSteOff(payload.text)) {
        return await deactivateScope(sessionID, "event:inbox.user:/ste-off");
      }
      if (Array.isArray(payload.skills)) {
        for (const sk of payload.skills) {
          const sid = sk?.id ?? sk?.name ?? sk;
          if (isSteSkillIdentifier(sid) || isSteSkillIdentifier(sk?.name)) {
            return await activateScope(sessionID, `event:inbox.skill:${sid}`);
          }
        }
      }
      if (Array.isArray(payload.agents)) {
        for (const ag of payload.agents) {
          const aName = ag?.name ?? ag;
          if (isSteAgentIdentifier(aName)) {
            return await activateScope(sessionID, `event:inbox.agent:${aName}`);
          }
        }
      }
      return null;
    }

    if (type === "session.text.ended") {
      const sessionID = String(data.sessionID || "").trim();
      const text = typeof data.text === "string" ? data.text : "";
      const assistantMessageID = String(data.assistantMessageID || "").trim();
      const ordinal = Number.isInteger(data.ordinal) ? data.ordinal : 0;
      if (!sessionID || !text.trim()) return null;

      const dedupKey = `${sessionID}:${assistantMessageID}:${ordinal}`;
      if (processedTextEnded.has(dedupKey)) return null;

      const scope = await isSessionScoped(sessionID);
      if (!scope.active) return null;

      processedTextEnded.add(dedupKey);
      const existing = getCachedOrDisk(sessionID) || {};
      const count = Number.isInteger(existing.prose_diagnostic_count) ? existing.prose_diagnostic_count : 0;
      if (count >= 25) {
        return null;
      }

      // Immediately persist a synchronous preliminary record so short-lived CLI processes
      // never lose the observation if the server exits right after `session.text.ended`.
      const textSha = sha256Hex(text);
      const preliminaryRecord = {
        schema: "ste-promax.opencode-prose-postprocess.v1",
        status: "pending_guarded_check",
        delivery_timing: "post_stream_advisory",
        pre_display_guaranteed: false,
        assistant_message_id: assistantMessageID || null,
        ordinal,
        text_sha256: textSha,
      };
      await persistRecord(sessionID, {
        ...existing,
        active: true,
        last_prose_diagnostic: preliminaryRecord,
        prose_diagnostic_count: count + 1,
      });

      const diagRes = await runPythonDispatcher(
        "ste_postprocess_prose",
        {
          text,
          profile: "relaxed",
          assistant_message_id: assistantMessageID || null,
          ordinal,
        },
        {
          workspaceRoot: scope.workspaceRoot,
          sessionID,
          bundleRoot,
          dispatchPyPath,
          env,
        },
      );

      const diagnosticRecord = diagRes.result || {
        status: "error",
        delivery_timing: "post_stream_advisory",
        pre_display_guaranteed: false,
        text_sha256: textSha,
        error: diagRes.error || null,
      };

      const latest = getCachedOrDisk(sessionID) || existing;
      await persistRecord(sessionID, {
        ...latest,
        active: true,
        last_prose_diagnostic: diagnosticRecord,
        prose_diagnostic_count: count + 1,
      });
      try {
        await storageSet(`ste:prose:${sessionID}`, diagnosticRecord);
      } catch {
        // Ignore storage errors
      }
      return diagnosticRecord;
    }

    return null;
  }

  async function executeGuardedSteTool(toolName, input, context) {
    const sessionID = String(context?.sessionID || "").trim();
    const ws = await resolveWorkspaceForSession(sessionID);
    await activateScope(sessionID, `tool.execute:${toolName}`, { working_directory: ws });

    const pre = prevalidateSteToolCall(toolName, input, ws, env);
    if (!pre.ok) {
      return {
        ok: false,
        error: {
          code: pre.code || ERROR_POLICY_REFUSAL,
          message: pre.message,
        },
      };
    }

    return await runPythonDispatcher(toolName, input || {}, {
      workspaceRoot: ws,
      sessionID,
      bundleRoot,
      dispatchPyPath,
      env,
    });
  }

  return {
    activateScope,
    deactivateScope,
    bindParentSession,
    isSessionScoped,
    resolveWorkspaceForSession,
    handlePromptHook,
    handleContextHook,
    handleExecuteBefore,
    handleServerEvent,
    executeGuardedSteTool,
    getCachedOrDisk,
  };
}

function runHostEffectOrPromise(EffectApi, runtime, value) {
  if (value === null || value === undefined) {
    return Promise.resolve(value);
  }
  if (typeof value?.then === "function") {
    return value;
  }
  if (runtime && typeof value === "object" && typeof EffectApi?.runPromiseWith === "function") {
    try {
      return EffectApi.runPromiseWith(runtime)(value);
    } catch {
      return Promise.resolve(undefined);
    }
  }
  return Promise.resolve(value);
}

export function createSteOpenCodePlugin({
  PluginApi,
  ToolErrorClass,
  EffectApi,
  StreamApi,
  bundleRoot = BUNDLE_ROOT,
  dispatchPyPath = DISPATCH_PY_PATH,
} = {}) {
  return PluginApi.define({
    id: OPENCODE_PLUGIN_ID,
    effect: (ctx) =>
      EffectApi.gen(function* () {
        const runtime = yield* EffectApi.context();
        const defaultWorkspaceRoot =
          ctx?.location?.directory ||
          ctx?.location?.project?.directory ||
          null;

        const manager = createScopeManager({
          defaultWorkspaceRoot,
          bundleRoot,
          dispatchPyPath,
          env: process.env,
          getSessionInfo: async (sessionID) => {
            if (!ctx?.session?.get) return null;
            return await runHostEffectOrPromise(
              EffectApi,
              runtime,
              ctx.session.get({ sessionID }),
            );
          },
          getSessionContext: async (sessionID) => {
            if (!ctx?.session?.context) return [];
            const res = await runHostEffectOrPromise(
              EffectApi,
              runtime,
              ctx.session.context({ sessionID }),
            );
            return Array.isArray(res) ? res : [];
          },
          storageGet: async (key) => {
            if (!ctx?.storage?.get) return undefined;
            return await runHostEffectOrPromise(EffectApi, runtime, ctx.storage.get(key));
          },
          storageSet: async (key, value) => {
            if (!ctx?.storage?.set) return;
            await runHostEffectOrPromise(EffectApi, runtime, ctx.storage.set(key, value));
          },
        });

        // 1. Register bundled STE skills (`ste-promax`, `ste-visual-docs`, `ste-storytelling`, `ste-line-studio`)
        if (ctx?.skill?.transform) {
          const bundledSkills = readBundleSkills(bundleRoot);
          if (bundledSkills.length > 0) {
            yield* ctx.skill.transform((editor) => {
              for (const sk of bundledSkills) {
                if (typeof editor?.get === "function" && editor.get(sk.id)) continue;
                editor.add(sk);
              }
            });
          }
        }

        // 2. Register top-level guarded STE tools with `options: { codemode: false }`
        if (ctx?.tool?.transform) {
          yield* ctx.tool.transform((editor) => {
            for (const [toolName, spec] of Object.entries(STE_TOOL_SCHEMAS)) {
              editor.add({
                name: toolName,
                description: spec.description,
                input: spec.input,
                options: { codemode: false },
                execute: (input, context) =>
                  EffectApi.tryPromise({
                    try: () => manager.executeGuardedSteTool(toolName, input, context),
                    catch: (err) =>
                      new ToolErrorClass({
                        message: `STE-Pro-Max tool ${toolName} failed closed: ${
                          err instanceof Error ? err.message : String(err)
                        }`,
                        metadata: { code: ERROR_POLICY_REFUSAL, tool: toolName },
                      }),
                  }).pipe(
                    EffectApi.flatMap((response) =>
                      response?.ok
                        ? EffectApi.succeed({
                            content: JSON.stringify(response, null, 2),
                            metadata: buildSteToolResultMetadata(toolName, response),
                          })
                        : EffectApi.fail(
                            new ToolErrorClass({
                              message:
                                response?.error?.message ||
                                `STE-Pro-Max tool ${toolName} refused by policy.`,
                              metadata: response?.error || { code: ERROR_POLICY_REFUSAL },
                            }),
                          ),
                    ),
                  ),
              });
            }
          });
        }

        // 3. Register user-only `/ste-off` slash command
        if (ctx?.command?.transform) {
          yield* ctx.command.transform((editor) => {
            editor.add({
              name: "ste-off",
              description: "Deactivate STE-Pro-Max session scope for the current session",
              execute: (input) =>
                EffectApi.promise(async () => {
                  await manager.deactivateScope(input.sessionID, "command:/ste-off");
                  if (ctx?.session?.synthetic) {
                    await runHostEffectOrPromise(
                      EffectApi,
                      runtime,
                      ctx.session.synthetic({
                        sessionID: input.sessionID,
                        text: "STE-Pro-Max session scope has been ended by explicit user /ste-off command.",
                        resume: false,
                        delivery: "queue",
                      }),
                    ).catch(() => {});
                  }
                }),
            });
          });
        }

        // 4. Register V2 Effect `execute.before` hook with typed `Tool.Error` refusal
        if (ctx?.tool?.hook) {
          yield* ctx.tool.hook("execute.before", (event) =>
            EffectApi.tryPromise({
              try: () => manager.handleExecuteBefore(event),
              catch: (err) =>
                new ToolErrorClass({
                  message: `STE-Pro-Max execute.before hook failed closed: ${
                    err instanceof Error ? err.message : String(err)
                  }`,
                  metadata: { code: ERROR_POLICY_REFUSAL },
                }),
            }).pipe(
              EffectApi.flatMap((decision) =>
                decision.allow
                  ? EffectApi.void
                  : EffectApi.fail(
                      new ToolErrorClass({
                        message: decision.message,
                        metadata: { code: decision.code || ERROR_POLICY_REFUSAL },
                      }),
                    ),
              ),
            ),
          );
        }

        // 5. Register session `prompt` and `context` hooks
        if (ctx?.session?.hook) {
          yield* ctx.session.hook("prompt", (event) =>
            EffectApi.promise(() => manager.handlePromptHook(event).catch(() => {})),
          );
          yield* ctx.session.hook("context", (event) =>
            EffectApi.promise(() => manager.handleContextHook(event).catch(() => {})),
          );
        }

        // 6. Subscribe to server events (`session.skill.activated`, `session.created`, `session.text.ended`, etc.)
        if (ctx?.event?.subscribe && StreamApi?.runForEach) {
          yield* ctx.event.subscribe().pipe(
            StreamApi.runForEach((event) =>
              EffectApi.promise(() => manager.handleServerEvent(event).catch(() => {})),
            ),
            EffectApi.ignore,
            EffectApi.forkScoped,
          );
        }
      }),
  });
}

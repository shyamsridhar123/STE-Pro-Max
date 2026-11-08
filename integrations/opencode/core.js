// Core implementation for the OpenCode V2 STE-Pro-Max host adapter.
// Registers the 4 bundled STE skills and 10 top-level guarded STE tools
// (`options: { codemode: false }`), validating STE tool inputs and routing them
// through the shared Python dispatcher (`dispatch.py`). Does not intercept or
// restrict other host tools, sessions, prompts, or events.

import { execFile } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

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

function isSubpath(childPath, parentPath) {
  const rel = path.relative(parentPath, childPath);
  return Boolean(rel) && !rel.startsWith("..") && !path.isAbsolute(rel);
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
// Workspace Resolution and Guarded STE Tool Executor
// ---------------------------------------------------------------------------

export async function resolveWorkspaceForSession(
  sessionID,
  {
    defaultWorkspaceRoot = null,
    getSessionInfo = async () => null,
  } = {},
) {
  if (typeof sessionID === "string" && sessionID.trim()) {
    try {
      const info = await getSessionInfo(sessionID.trim());
      const dir = info?.location?.directory ?? info?.directory;
      if (typeof dir === "string" && dir.trim()) {
        const check = checkSafeLexicalPath(dir.trim(), "session.location.directory", {
          requireAbsolute: true,
        });
        if (check.ok) return check.resolved;
      }
    } catch {
      // Ignore session.get failure and fall back to ctx.location.directory
    }
  }
  if (typeof defaultWorkspaceRoot === "string" && defaultWorkspaceRoot.trim()) {
    const check = checkSafeLexicalPath(defaultWorkspaceRoot.trim(), "ctx.location.directory", {
      requireAbsolute: true,
    });
    if (check.ok) return check.resolved;
  }
  return null;
}

export async function executeGuardedSteTool(
  toolName,
  input,
  context,
  {
    defaultWorkspaceRoot = null,
    bundleRoot = BUNDLE_ROOT,
    dispatchPyPath = DISPATCH_PY_PATH,
    env = process.env,
    getSessionInfo = async () => null,
  } = {},
) {
  const sessionID = String(context?.sessionID || "").trim();
  const ws = await resolveWorkspaceForSession(sessionID, {
    defaultWorkspaceRoot,
    getSessionInfo,
  });

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

        const getSessionInfo = async (sessionID) => {
          if (!ctx?.session?.get) return null;
          return await runHostEffectOrPromise(
            EffectApi,
            runtime,
            ctx.session.get({ sessionID }),
          );
        };

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
                    try: () =>
                      executeGuardedSteTool(toolName, input, context, {
                        defaultWorkspaceRoot,
                        bundleRoot,
                        dispatchPyPath,
                        env: process.env,
                        getSessionInfo,
                      }),
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
      }),
  });
}

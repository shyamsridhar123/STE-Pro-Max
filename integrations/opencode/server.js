// OpenCode V2 Effect plugin entry point for STE-Pro-Max automatic local policy.
// Uses actual V2 Effect `ctx.tool.hook("execute.before")` + typed `Tool.Error`
// refusal, registers top-level guarded STE tools (`options: { codemode: false }`),
// recovers and inherits STE session scope across turns/reloads/child sessions,
// and runs turn preflight + post-stream `session.text.ended` prose diagnostics.

import { Plugin } from "@opencode/plugin/effect";
import { Error as ToolError } from "@opencode/plugin/promise/tool";
import { Effect, Stream } from "effect";

import {
  BUNDLE_ROOT,
  DISPATCH_PY_PATH,
  OPENCODE_PLUGIN_ID,
  STE_SKILL_IDS,
  STE_TOOL_NAMES,
  STE_TOOL_SCHEMAS,
  createSteOpenCodePlugin,
} from "./core.js";

const stePlugin = createSteOpenCodePlugin({
  PluginApi: Plugin,
  ToolErrorClass: ToolError,
  EffectApi: Effect,
  StreamApi: Stream,
  bundleRoot: BUNDLE_ROOT,
  dispatchPyPath: DISPATCH_PY_PATH,
});

export {
  BUNDLE_ROOT,
  DISPATCH_PY_PATH,
  OPENCODE_PLUGIN_ID,
  STE_SKILL_IDS,
  STE_TOOL_NAMES,
  STE_TOOL_SCHEMAS,
  createSteOpenCodePlugin,
  stePlugin,
};
export default stePlugin;

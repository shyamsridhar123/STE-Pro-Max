"""Official Python MCP SDK stdio server (`ste-promax`) for STE-Pro-Max.

Exposes typed guarded tools backed by `ste_promax.gate.run_guarded_operation`:
- `ste_status`
- `ste_check_prose`
- `ste_write_artifact`
- `ste_render_bundle`
- `ste_render_artifact`
- `ste_regenerate_gallery`
- `ste_prepare_story_media`
- `ste_synthesize_wav`
- `ste_inspect_artifact`
- `ste_export_bundle`

Never accepts `workspace_root`, `state_dir`, `runtime_config`, interpreter paths,
or policy bypass flags from model tool arguments.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


def _ensure_bundle_sys_path() -> Path:
    bundle_root = Path(__file__).resolve().parents[2]
    root_str = str(bundle_root)
    cleaned_path: list[str] = [root_str]
    for entry in sys.path:
        if not entry:
            continue
        try:
            res_entry = Path(entry).resolve()
        except OSError:
            continue
        if res_entry == bundle_root:
            continue
        if (res_entry / "integrations" / "mcp" / "operations.py").is_file() and res_entry != bundle_root:
            continue
        cleaned_path.append(entry)
    sys.path[:] = cleaned_path
    return bundle_root


BUNDLE_ROOT = _ensure_bundle_sys_path()

from integrations.mcp.operations import (  # noqa: E402
    MCP_SERVER_NAME,
    host_check_prose,
    host_export_bundle,
    host_inspect_artifact,
    host_prepare_story_media,
    host_regenerate_gallery,
    host_render_artifact,
    host_render_bundle,
    host_status,
    host_synthesize_wav,
    host_write_artifact,
    resolve_mcp_python,
    resolve_trusted_workspace,
)
from ste_promax.policy_runtime import PolicyError  # noqa: E402


def _has_local_fastmcp() -> bool:
    try:
        spec = importlib.util.find_spec("mcp.server.fastmcp")
        return spec is not None
    except (ImportError, ValueError):
        return False


def _maybe_reexec_with_mcp_python() -> int | None:
    if os.environ.get("_STE_MCP_REEXEC") == "1":
        return None
    has_local = _has_local_fastmcp()
    explicit_override = bool(
        os.environ.get("STE_MCP_PYTHON", "").strip()
        or os.environ.get("STE_SKILLC_RUNTIME_CONFIG", "").strip()
    )
    if has_local and not explicit_override:
        return None

    try:
        candidate = resolve_mcp_python(probe_mcp=True)
    except PolicyError as exc:
        sys.stderr.write(json.dumps({"ok": False, "error": exc.to_error_dict()}) + "\n")
        sys.stderr.flush()
        return 2

    if candidate is None:
        if has_local:
            return None
        sys.stderr.write(
            json.dumps({
                "ok": False,
                "error": {
                    "code": "dependency_missing",
                    "message": "MCP SDK ('mcp.server.fastmcp') is not available and no runtime.json/STE_MCP_PYTHON is configured.",
                },
            })
            + "\n"
        )
        sys.stderr.flush()
        return 2

    current_exe = Path(sys.executable)
    if has_local and (candidate == current_exe or candidate.resolve() == current_exe.resolve()):
        return None

    env = dict(os.environ)
    env["_STE_MCP_REEXEC"] = "1"
    proc = subprocess.run(
        [str(candidate), "-I", "-B", str(Path(__file__).resolve()), *sys.argv[1:]],
        stdin=sys.stdin,
        stdout=sys.stdout,
        stderr=sys.stderr,
        env=env,
        cwd=os.getcwd(),
        shell=False,
        check=False,
    )
    return int(proc.returncode)


_reexec_rc = _maybe_reexec_with_mcp_python()
if _reexec_rc is not None:
    raise SystemExit(_reexec_rc)

from mcp.server.fastmcp import Context, FastMCP  # noqa: E402


def _extract_meta_session_id(ctx: Context | None) -> str | None:
    if ctx is None:
        return None
    try:
        rc = getattr(ctx, "request_context", None)
        meta = getattr(rc, "meta", None)
        if meta is None:
            return None
        if hasattr(meta, "model_dump"):
            dumped = meta.model_dump()
            if isinstance(dumped, dict):
                sid = dumped.get("ste_session_id") or dumped.get("sessionId")
                if isinstance(sid, str) and sid.strip():
                    return sid.strip()
        extra = getattr(meta, "model_extra", None)
        if isinstance(extra, dict):
            sid = extra.get("ste_session_id") or extra.get("sessionId")
            if isinstance(sid, str) and sid.strip():
                return sid.strip()
        for attr in ("ste_session_id", "sessionId"):
            val = getattr(meta, attr, None)
            if isinstance(val, str) and val.strip():
                return val.strip()
    except Exception:
        return None
    return None


async def _resolve_context_workspace(ctx: Context | None) -> Path:
    session_id = _extract_meta_session_id(ctx)
    if session_id is not None:
        ws = resolve_trusted_workspace(session_id=session_id)
    else:
        roots: list[str] = []
        if ctx is not None:
            try:
                session = getattr(ctx, "session", None)
                if session is not None and hasattr(session, "list_roots"):
                    roots_result = await asyncio.wait_for(session.list_roots(), timeout=1.5)
                    raw_roots = getattr(roots_result, "roots", None) or []
                    for item in raw_roots:
                        uri = getattr(item, "uri", None)
                        if uri is not None:
                            roots.append(str(uri))
            except Exception:
                roots = []
        ws = resolve_trusted_workspace(mcp_roots=roots or None)
    if ws == BUNDLE_ROOT or ws.is_relative_to(BUNDLE_ROOT) or BUNDLE_ROOT.is_relative_to(ws):
        raise PolicyError(
            f"Refusing to use plugin bundle root or its ancestors as MCP workspace: {ws}",
            code="policy_refusal",
        )
    return ws


def _finalize_mcp_response(response: dict[str, Any]) -> str:
    payload = json.dumps(response, ensure_ascii=False, indent=2)
    if not response.get("ok", False):
        raise ValueError(payload)
    return payload


def create_mcp_server() -> FastMCP:
    server = FastMCP(
        MCP_SERVER_NAME,
        instructions=(
            "STE-Pro-Max guarded MCP server. All workflows execute automatically under "
            "SkillC precondition, execution, and postcondition verification with no manual "
            "approval steps. Workspace root is determined from trusted host context."
        ),
    )

    @server.tool(
        name="ste_status",
        description=(
            "Return current STE-Pro-Max automatic SkillC policy status, bundle root, "
            "trusted workspace root, and latest policy receipt."
        ),
    )
    async def ste_status(ctx: Context | None = None) -> str:
        ws = await _resolve_context_workspace(ctx)
        res = host_status(workspace_root=ws)
        return _finalize_mcp_response(res)

    @server.tool(
        name="ste_check_prose",
        description=(
            "Run guarded STE-Pro-Max advisory prose diagnostics on inline text or a "
            "workspace file. Preserves source and semantic limitations as warnings."
        ),
    )
    async def ste_check_prose(
        text: str | None = None,
        source_path: str | None = None,
        profile: str = "relaxed",
        ctx: Context | None = None,
    ) -> str:
        ws = await _resolve_context_workspace(ctx)
        res = host_check_prose(
            text=text,
            source_path=source_path,
            profile=profile,
            workspace_root=ws,
        )
        return _finalize_mcp_response(res)

    @server.tool(
        name="ste_write_artifact",
        description=(
            "Write or update a host-authored STE-Pro-Max artifact or document inside the "
            "workspace under automatic SkillC precondition and postcondition verification. "
            "Prevalidates candidate UTF-8 content, target confinement, and expected_before_sha256."
        ),
    )
    async def ste_write_artifact(
        target_path: str,
        content: str,
        expected_before_sha256: str | None = None,
        source_paths: list[str] | None = None,
        evidence_paths: list[str] | None = None,
        evidence_root: str | None = None,
        source_kind: str = "host_content",
        trusted_html: bool = False,
        ctx: Context | None = None,
    ) -> str:
        ws = await _resolve_context_workspace(ctx)
        res = host_write_artifact(
            target_path=target_path,
            content=content,
            expected_before_sha256=expected_before_sha256,
            source_paths=source_paths,
            evidence_paths=evidence_paths,
            evidence_root=evidence_root,
            source_kind=source_kind,
            trusted_html=trusted_html,
            workspace_root=ws,
        )
        return _finalize_mcp_response(res)

    @server.tool(
        name="ste_render_bundle",
        description=(
            "Render a complete native STE-Pro-Max artifact bundle (.html, .DESIGN.md, "
            ".meta.yaml, gallery.html, manifest.json) into a new or empty workspace directory."
        ),
    )
    async def ste_render_bundle(
        input_path: str,
        output_dir: str,
        title: str | None = None,
        design_path: str | None = None,
        evidence: list[str] | None = None,
        evidence_root: str | None = None,
        trusted_html: bool = False,
        ctx: Context | None = None,
    ) -> str:
        ws = await _resolve_context_workspace(ctx)
        res = host_render_bundle(
            input_path=input_path,
            output_dir=output_dir,
            title=title,
            design_path=design_path,
            evidence=evidence,
            evidence_root=evidence_root,
            trusted_html=trusted_html,
            workspace_root=ws,
        )
        return _finalize_mcp_response(res)

    @server.tool(
        name="ste_render_artifact",
        description=(
            "Render a direct STE-Pro-Max HTML/DESIGN/meta triple into a workspace directory "
            "from a source file or structured input_data."
        ),
    )
    async def ste_render_artifact(
        output_dir: str,
        input_path: str | None = None,
        input_data: dict[str, Any] | None = None,
        title: str | None = None,
        design_path: str | None = None,
        trusted_html: bool = False,
        ctx: Context | None = None,
    ) -> str:
        ws = await _resolve_context_workspace(ctx)
        res = host_render_artifact(
            output_dir=output_dir,
            input_path=input_path,
            input_data=input_data,
            title=title,
            design_path=design_path,
            trusted_html=trusted_html,
            workspace_root=ws,
        )
        return _finalize_mcp_response(res)

    @server.tool(
        name="ste_regenerate_gallery",
        description="Regenerate gallery.html for an artifact directory inside the workspace.",
    )
    async def ste_regenerate_gallery(
        artifact_dir: str,
        ctx: Context | None = None,
    ) -> str:
        ws = await _resolve_context_workspace(ctx)
        res = host_regenerate_gallery(
            artifact_dir=artifact_dir,
            workspace_root=ws,
        )
        return _finalize_mcp_response(res)

    @server.tool(
        name="ste_prepare_story_media",
        description=(
            "Prepare local evidence-linked story media (composition, captions, transcript, "
            "review.html, and verified non-silent PCM WAV audio) inside a new workspace directory."
        ),
    )
    async def ste_prepare_story_media(
        input_path: str,
        output_dir: str,
        voice: str | None = None,
        audio_dir: str | None = None,
        ctx: Context | None = None,
    ) -> str:
        ws = await _resolve_context_workspace(ctx)
        res = host_prepare_story_media(
            input_path=input_path,
            output_dir=output_dir,
            voice=voice,
            audio_dir=audio_dir,
            workspace_root=ws,
        )
        return _finalize_mcp_response(res)

    @server.tool(
        name="ste_synthesize_wav",
        description="Synthesize a verified non-silent PCM WAV file from a workspace text file.",
    )
    async def ste_synthesize_wav(
        text_path: str,
        audio_path: str,
        voice: str | None = None,
        ctx: Context | None = None,
    ) -> str:
        ws = await _resolve_context_workspace(ctx)
        res = host_synthesize_wav(
            text_path=text_path,
            audio_path=audio_path,
            voice=voice,
            workspace_root=ws,
        )
        return _finalize_mcp_response(res)

    @server.tool(
        name="ste_inspect_artifact",
        description=(
            "Perform bounded static local inspection of an artifact file or bundle directory "
            "inside the workspace. Never accepts arbitrary code; headless_browser=True is "
            "unsupported in this local adapter."
        ),
    )
    async def ste_inspect_artifact(
        target_path: str,
        headless_browser: bool = False,
        ctx: Context | None = None,
    ) -> str:
        ws = await _resolve_context_workspace(ctx)
        res = host_inspect_artifact(
            target_path=target_path,
            headless_browser=headless_browser,
            workspace_root=ws,
        )
        return _finalize_mcp_response(res)

    @server.tool(
        name="ste_export_bundle",
        description=(
            "Automatically verify a fresh native STE-Pro-Max bundle and export it into a "
            "new destination directory inside the workspace without manual approval."
        ),
    )
    async def ste_export_bundle(
        input_dir: str,
        output_dir: str,
        evidence: list[str] | None = None,
        evidence_root: str | None = None,
        ctx: Context | None = None,
    ) -> str:
        ws = await _resolve_context_workspace(ctx)
        res = host_export_bundle(
            input_dir=input_dir,
            output_dir=output_dir,
            evidence=evidence,
            evidence_root=evidence_root,
            workspace_root=ws,
        )
        return _finalize_mcp_response(res)

    return server


def main() -> int:
    server = create_mcp_server()
    server.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

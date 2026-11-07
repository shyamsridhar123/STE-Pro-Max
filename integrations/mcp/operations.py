"""Guarded host operations for the STE-Pro-Max MCP server and Copilot CLI adapter.

All operations execute package code from the installed bundle root (derived from
`__file__` / `PLUGIN_ROOT`), resolve the workspace from trusted host context
(never from model arguments), enforce `caller_kind="host"` workspace confinement,
and run real SkillC precondition/execution/postcondition verification via
`ste_promax.gate.run_guarded_operation`.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from typing import Any
from urllib.parse import unquote, urlparse, urlsplit


def resolve_bundle_root() -> Path:
    """Resolve the installed STE-Pro-Max bundle root from `__file__` and isolate `sys.path`."""
    file_root = Path(__file__).resolve().parents[2]
    for env_key in ("STE_PROMAX_PLUGIN_ROOT", "COPILOT_PLUGIN_ROOT", "PLUGIN_ROOT"):
        raw = os.environ.get(env_key, "").strip()
        if not raw or "${" in raw:
            continue
        try:
            candidate = Path(raw).resolve(strict=True)
        except OSError:
            continue
        if (candidate / "ste_promax" / "__init__.py").is_file() and candidate == file_root:
            file_root = candidate
            break
    root_str = str(file_root)
    cleaned_path: list[str] = [root_str]
    for entry in sys.path:
        if not entry:
            continue
        try:
            res_entry = Path(entry).resolve()
        except OSError:
            continue
        if res_entry == file_root:
            continue
        if (res_entry / "integrations" / "mcp" / "operations.py").is_file() and res_entry != file_root:
            continue
        cleaned_path.append(entry)
    sys.path[:] = cleaned_path
    return file_root


BUNDLE_ROOT: Path = resolve_bundle_root()
_INITIAL_CWD: Path = Path.cwd().resolve()

from ste_promax import cli, gate, writing  # noqa: E402
from ste_promax.json_input import loads_json  # noqa: E402
from ste_promax.policy_runtime import (  # noqa: E402
    ERROR_DEPENDENCY_MISSING,
    ERROR_INVALID_INPUT,
    ERROR_POLICY_REFUSAL,
    ERROR_POSTCONDITION_FAILURE,
    ERROR_UNSUPPORTED_OPERATION,
    PolicyBackendError,
    PolicyError,
    check_safe_lexical_path,
    check_sensitive_read_path,
    is_link_or_reparse,
    load_runtime_config,
    resolve_state_root,
)


def _probe_mcp_interpreter(python_exe: Path, label: str) -> Path:
    try:
        resolved = python_exe.resolve(strict=True)
    except FileNotFoundError as exc:
        raise PolicyBackendError(f"{label} does not exist: {python_exe}") from exc
    if not resolved.is_file() or resolved.stat().st_size == 0:
        raise PolicyBackendError(f"{label} must resolve to a non-empty regular file: {resolved}")
    probe = subprocess.run(
        [str(python_exe), "-I", "-B", "-c", "from mcp.server.fastmcp import FastMCP"],
        cwd=str(BUNDLE_ROOT),
        capture_output=True,
        text=True,
        timeout=10,
        shell=False,
        check=False,
    )
    if probe.returncode != 0:
        raise PolicyBackendError(
            f"{label} does not provide 'mcp.server.fastmcp': {(probe.stderr or probe.stdout or '').strip()}"
        )
    return python_exe


def resolve_mcp_python(*, probe_mcp: bool = True) -> Path | None:
    """Resolve the configured MCP Python interpreter from STE_MCP_PYTHON or validated runtime.json.

    Fails closed on an explicit invalid STE_MCP_PYTHON, invalid STE_SKILLC_RUNTIME_CONFIG,
    or invalid runtime.json.mcp_python without falling back to another interpreter.
    Preserves the configured venv executable path rather than its symlink target.
    """
    raw_env = os.environ.get("STE_MCP_PYTHON", "")
    if raw_env.strip():
        abs_env, _ = check_safe_lexical_path(
            raw_env.strip(),
            "STE_MCP_PYTHON",
            require_absolute=True,
            allow_leaf_symlink=True,
            code=ERROR_DEPENDENCY_MISSING,
        )
        return _probe_mcp_interpreter(abs_env, "STE_MCP_PYTHON") if probe_mcp else abs_env

    cfg = load_runtime_config()
    if cfg is None:
        return None

    if "mcp_python" in cfg and cfg["mcp_python"] is not None:
        raw_mcp_py = cfg.get("mcp_python")
        if not isinstance(raw_mcp_py, str) or not raw_mcp_py.strip():
            raise PolicyBackendError("runtime.json field 'mcp_python' must be a non-empty string.")
        abs_mcp_py, _ = check_safe_lexical_path(
            raw_mcp_py.strip(),
            "runtime.json.mcp_python",
            require_absolute=True,
            allow_leaf_symlink=True,
            code=ERROR_DEPENDENCY_MISSING,
        )
        return _probe_mcp_interpreter(abs_mcp_py, "runtime.json.mcp_python") if probe_mcp else abs_mcp_py

    raw_py = cfg.get("python")
    if not isinstance(raw_py, str) or not raw_py.strip():
        raise PolicyBackendError("runtime.json field 'python' must be a non-empty string.")
    abs_py, _ = check_safe_lexical_path(
        raw_py.strip(),
        "runtime.json.python",
        require_absolute=True,
        allow_leaf_symlink=True,
        code=ERROR_DEPENDENCY_MISSING,
    )
    return _probe_mcp_interpreter(abs_py, "runtime.json.python") if probe_mcp else abs_py


def _ensure_render_deps_on_path() -> None:
    """Bind validated site-packages from trusted runtime.json python only when version-compatible."""
    try:
        import jinja2  # noqa: F401
        import yaml  # noqa: F401
        return
    except ImportError:
        pass
    cfg = load_runtime_config()
    if not isinstance(cfg, dict):
        raise PolicyBackendError("Rendering dependencies unavailable and runtime.json is not configured.")
    versions = cfg.get("versions")
    if not isinstance(versions, dict) or "Jinja2" not in versions or "PyYAML" not in versions:
        raise PolicyBackendError("runtime.json does not declare required Jinja2 and PyYAML versions.")
    raw_py = cfg.get("python")
    if not isinstance(raw_py, str) or not raw_py.strip():
        raise PolicyBackendError("runtime.json is missing a valid 'python' path.")
    abs_py, _ = check_safe_lexical_path(
        raw_py.strip(),
        "runtime.json.python",
        require_absolute=True,
        allow_leaf_symlink=True,
        code=ERROR_DEPENDENCY_MISSING,
    )
    venv_root = abs_py.parent.parent
    pyvenv_cfg = venv_root / "pyvenv.cfg"
    try:
        cfg_info = pyvenv_cfg.lstat()
    except FileNotFoundError as exc:
        raise PolicyBackendError(f"Runtime environment is missing pyvenv.cfg: {pyvenv_cfg}") from exc
    if is_link_or_reparse(cfg_info) or not stat.S_ISREG(cfg_info.st_mode):
        raise PolicyBackendError(f"Runtime pyvenv.cfg must be a regular file: {pyvenv_cfg}")

    expected_mm = f"{sys.version_info.major}.{sys.version_info.minor}"
    observed_version = ""
    for line in pyvenv_cfg.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line:
            k, v = (part.strip() for part in line.split("=", 1))
            if k in {"version", "version_info"} and v:
                observed_version = v
                break
    if not observed_version.startswith(f"{expected_mm}."):
        raise PolicyBackendError(
            f"Runtime Python version ({observed_version or 'unknown'}) is incompatible with "
            f"running interpreter ({expected_mm})."
        )

    if os.name == "nt" or sys.platform == "win32":
        sp_candidate = venv_root / "Lib" / "site-packages"
    else:
        sp_candidate = venv_root / "lib" / f"python{expected_mm}" / "site-packages"

    _, resolved_sp = check_safe_lexical_path(
        sp_candidate,
        "runtime site-packages",
        require_absolute=True,
        code=ERROR_DEPENDENCY_MISSING,
    )
    if not resolved_sp.is_dir():
        raise PolicyBackendError(f"Runtime site-packages directory does not exist: {resolved_sp}")
    for req_pkg in ("yaml", "jinja2"):
        pkg_init = resolved_sp / req_pkg / "__init__.py"
        if not pkg_init.is_file() or pkg_init.is_symlink():
            raise PolicyBackendError(
                f"Runtime site-packages is missing verified package {req_pkg!r}: {resolved_sp}"
            )
    sp_str = str(resolved_sp)
    if sp_str not in sys.path:
        sys.path.append(sp_str)

MCP_SERVER_NAME = "ste-promax"

STE_MCP_TOOL_NAMES: frozenset[str] = frozenset({
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
})

ALLOWED_HOST_WRITE_EXTENSIONS: frozenset[str] = frozenset({
    ".html",
    ".svg",
    ".md",
    ".json",
    ".yaml",
    ".yml",
    ".txt",
    ".vtt",
    ".css",
})

FORBIDDEN_HOST_WRITE_EXTENSIONS: frozenset[str] = frozenset({
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
})

EXTRA_PROTECTED_WORKSPACE_DIRS: frozenset[str] = frozenset({
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
})

PROTECTED_WORKSPACE_ROOT_FILES: frozenset[str] = frozenset({
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
})

_HEX64 = re.compile(r"[0-9a-f]{64}\Z")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


@contextmanager
def _TemporaryWorkingDirectory(target: Path):
    prev = Path.cwd()
    try:
        os.chdir(target)
        yield
    finally:
        try:
            os.chdir(prev)
        except OSError:
            pass


def _file_uri_to_path(uri: str) -> Path | None:
    if not isinstance(uri, str) or not uri.startswith("file://"):
        return None
    parsed = urlparse(uri)
    if parsed.scheme.lower() != "file":
        return None
    if parsed.netloc and parsed.netloc.lower() not in {"", "localhost"}:
        return None
    if parsed.query or parsed.fragment:
        return None
    raw_path = unquote(parsed.path or "")
    if not raw_path or raw_path.startswith("//") or raw_path.startswith("\\\\"):
        return None
    if os.name == "nt":
        if raw_path.startswith("/") and len(raw_path) >= 3 and raw_path[2] == ":":
            raw_path = raw_path[1:]
    try:
        _, resolved = check_safe_lexical_path(
            raw_path,
            "MCP root URI",
            require_absolute=True,
        )
    except PolicyError:
        return None
    if resolved.is_dir():
        return resolved
    return None


def _lookup_session_workspace(session_id: str) -> Path:
    if not isinstance(session_id, str) or not session_id.strip():
        raise PolicyError(
            "Session ID must be non-empty for session workspace lookup.",
            code=ERROR_POLICY_REFUSAL,
        )
    clean_sid = session_id.strip()
    state_root = resolve_state_root()
    sessions_dir = state_root / "copilot-sessions"
    digest = hashlib.sha256(clean_sid.encode("utf-8")).hexdigest()[:32]
    record_path = sessions_dir / f"session-{digest}.json"
    try:
        info = record_path.lstat()
    except FileNotFoundError as exc:
        raise PolicyError(
            f"No trusted session record exists for session_id {clean_sid!r}; refusing unverified workspace lookup.",
            code=ERROR_POLICY_REFUSAL,
        ) from exc
    if is_link_or_reparse(info) or not stat.S_ISREG(info.st_mode):
        raise PolicyError(
            f"Session record for {clean_sid!r} is not a regular file.",
            code=ERROR_POLICY_REFUSAL,
        )
    try:
        data = json.loads(record_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PolicyError(
            f"Malformed session record for {clean_sid!r}: {exc}",
            code=ERROR_POLICY_REFUSAL,
        ) from exc
    if not isinstance(data, dict) or data.get("session_id") != clean_sid:
        raise PolicyError(
            f"Session record identity mismatch for {clean_sid!r}.",
            code=ERROR_POLICY_REFUSAL,
        )
    raw_wd = data.get("working_directory")
    if not isinstance(raw_wd, str) or not raw_wd.strip():
        raise PolicyError(
            f"Session record for {clean_sid!r} does not contain a trusted working_directory.",
            code=ERROR_POLICY_REFUSAL,
        )
    _, resolved = check_safe_lexical_path(
        raw_wd.strip(),
        "Session working_directory",
        require_absolute=True,
        code=ERROR_POLICY_REFUSAL,
    )
    if not resolved.is_dir():
        raise PolicyError(
            f"Session working_directory for {clean_sid!r} does not exist: {resolved}",
            code=ERROR_POLICY_REFUSAL,
        )
    return resolved


def resolve_trusted_workspace(
    explicit_workspace: str | Path | None = None,
    *,
    session_id: str | None = None,
    mcp_roots: list[str] | None = None,
) -> Path:
    """Determine the workspace directory from trusted host context, never model arguments or mtime guessing."""
    if explicit_workspace is not None:
        _, resolved = check_safe_lexical_path(
            explicit_workspace,
            "Trusted workspace root",
            code=ERROR_INVALID_INPUT,
        )
        if not resolved.is_dir():
            raise PolicyError(
                f"Trusted workspace root is not an existing directory: {resolved}",
                code=ERROR_INVALID_INPUT,
            )
        return resolved

    if mcp_roots is not None:
        if not isinstance(mcp_roots, list) or not mcp_roots:
            raise PolicyError(
                "MCP roots list must be a non-empty list of file:// URIs when provided.",
                code=ERROR_POLICY_REFUSAL,
            )
        resolved_roots: list[Path] = []
        for uri in mcp_roots:
            root_path = _file_uri_to_path(uri)
            if root_path is None:
                raise PolicyError(
                    f"Invalid, non-local, or non-directory MCP root URI: {uri!r}",
                    code=ERROR_POLICY_REFUSAL,
                )
            if root_path not in resolved_roots:
                resolved_roots.append(root_path)
        if len(resolved_roots) != 1:
            raise PolicyError(
                f"Ambiguous MCP workspace roots ({len(resolved_roots)} distinct roots); failing closed.",
                code=ERROR_POLICY_REFUSAL,
            )
        return resolved_roots[0]

    if session_id is not None:
        return _lookup_session_workspace(session_id)

    env_ws = os.environ.get("STE_TRUSTED_WORKSPACE", "").strip()
    if env_ws:
        _, resolved = check_safe_lexical_path(
            env_ws,
            "STE_TRUSTED_WORKSPACE",
            require_absolute=True,
            code=ERROR_INVALID_INPUT,
        )
        if not resolved.is_dir():
            raise PolicyError(
                f"STE_TRUSTED_WORKSPACE is not an existing directory: {resolved}",
                code=ERROR_INVALID_INPUT,
            )
        return resolved

    _, resolved_cwd = check_safe_lexical_path(_INITIAL_CWD, "Process working directory")
    if not resolved_cwd.is_dir():
        raise PolicyError("Trusted workspace directory is unavailable.", code=ERROR_INVALID_INPUT)
    if (
        resolved_cwd == BUNDLE_ROOT
        or resolved_cwd.is_relative_to(BUNDLE_ROOT)
        or BUNDLE_ROOT.is_relative_to(resolved_cwd)
    ):
        raise PolicyError(
            f"Trusted workspace root could not be determined from host context; refusing to fall back "
            f"to plugin bundle root or its ancestors ({resolved_cwd}).",
            code=ERROR_POLICY_REFUSAL,
        )
    return resolved_cwd


def _resolve_under_workspace(raw_path: str | Path, workspace_root: Path, label: str) -> tuple[Path, Path]:
    text = gate._require_nonempty_arg(raw_path, label)
    if "\x00" in text:
        raise PolicyError(f"{label} must not contain null bytes.", code=ERROR_INVALID_INPUT)
    raw_obj = Path(text)
    if ".." in raw_obj.parts or (raw_obj.drive and not raw_obj.root):
        raise PolicyError(f"{label} must not contain '..' or a drive-relative path.", code=ERROR_POLICY_REFUSAL)
    candidate = raw_obj if raw_obj.is_absolute() else (workspace_root / raw_obj)
    return check_safe_lexical_path(candidate, label, code=ERROR_INVALID_INPUT)


def validate_host_target_path(
    raw_path: str | Path,
    workspace_root: Path,
    label: str = "Target path",
    *,
    is_directory: bool = False,
    require_document_extension: bool = False,
) -> Path:
    """Validate that a host mutation target is confined to the workspace and not protected."""
    if type(is_directory) is not bool:
        raise PolicyError("is_directory must be a boolean.", code=ERROR_INVALID_INPUT)
    if type(require_document_extension) is not bool:
        raise PolicyError("require_document_extension must be a boolean.", code=ERROR_INVALID_INPUT)
    _, resolved = _resolve_under_workspace(raw_path, workspace_root, label)
    gate._check_not_protected_target(
        resolved,
        label,
        workspace_root=workspace_root,
        caller="host",
    )
    if resolved == workspace_root or not resolved.is_relative_to(workspace_root):
        raise PolicyError(
            f"{label} must reside strictly inside workspace root {workspace_root}: {resolved}",
            code=ERROR_POLICY_REFUSAL,
        )
    if workspace_root != BUNDLE_ROOT and (
        resolved == BUNDLE_ROOT or resolved.is_relative_to(BUNDLE_ROOT)
    ):
        raise PolicyError(
            f"{label} cannot target installed plugin bundle root {BUNDLE_ROOT}: {resolved}",
            code=ERROR_POLICY_REFUSAL,
        )
    rel = resolved.relative_to(workspace_root)
    rel_parts = rel.parts
    if not rel_parts:
        raise PolicyError(f"{label} cannot target workspace root itself.", code=ERROR_POLICY_REFUSAL)
    top_lower = rel_parts[0].lower()
    if top_lower in {d.lower() for d in EXTRA_PROTECTED_WORKSPACE_DIRS}:
        raise PolicyError(
            f"{label} targets protected workspace directory {rel_parts[0]!r}: {resolved}",
            code=ERROR_POLICY_REFUSAL,
        )
    if len(rel_parts) == 1 and rel_parts[0].lower() in PROTECTED_WORKSPACE_ROOT_FILES:
        raise PolicyError(
            f"{label} targets protected workspace root file {rel_parts[0]!r}: {resolved}",
            code=ERROR_POLICY_REFUSAL,
        )
    if not is_directory and require_document_extension:
        suffix = resolved.suffix.lower()
        if suffix in FORBIDDEN_HOST_WRITE_EXTENSIONS or suffix not in ALLOWED_HOST_WRITE_EXTENSIONS:
            raise PolicyError(
                f"{label} has unsupported host artifact extension {suffix!r}; "
                f"allowed extensions: {', '.join(sorted(ALLOWED_HOST_WRITE_EXTENSIONS))}.",
                code=ERROR_POLICY_REFUSAL,
            )
    return resolved


def _resolve_host_read_path(
    raw_path: str | Path,
    workspace_root: Path,
    label: str = "Input path",
    *,
    allow_bundle_examples: bool = True,
) -> Path:
    """Resolve a read-only source or evidence path inside the workspace or installed bundle examples."""
    _, resolved = _resolve_under_workspace(raw_path, workspace_root, label)
    gate._check_not_historical_manual_stage(resolved, label)
    in_workspace = resolved == workspace_root or resolved.is_relative_to(workspace_root)
    in_bundle_examples = allow_bundle_examples and (
        resolved.is_relative_to(BUNDLE_ROOT / "examples")
        or resolved.is_relative_to(BUNDLE_ROOT / "ste_promax" / "data")
        or resolved.is_relative_to(BUNDLE_ROOT / "ste_promax" / "designs")
    )
    if not (in_workspace or in_bundle_examples):
        raise PolicyError(
            f"{label} must reside inside workspace root {workspace_root}: {resolved}",
            code=ERROR_POLICY_REFUSAL,
        )
    check_sensitive_read_path(resolved, label, code=ERROR_POLICY_REFUSAL)
    return resolved


def _clear_stale_receipt() -> None:
    gate._set_last_receipt(None)


def _format_error_response(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, PolicyError):
        err: dict[str, Any] = {"code": exc.code, "message": exc.message}
        receipt = exc.receipt
        if isinstance(receipt, dict) and receipt.get("verdict") == "DENY":
            err["receipt"] = {
                "verdict": receipt.get("verdict"),
                "op": receipt.get("op"),
                "plan_digest": receipt.get("plan_digest"),
            }
        return {"ok": False, "error": err}
    if isinstance(exc, (ImportError, ModuleNotFoundError)):
        return {
            "ok": False,
            "error": {"code": ERROR_DEPENDENCY_MISSING, "message": str(exc)},
        }
    if isinstance(exc, ValueError):
        msg = str(exc)
        code = ERROR_POLICY_REFUSAL if "trusted-html" in msg or "unowned" in msg else ERROR_INVALID_INPUT
        return {
            "ok": False,
            "error": {"code": code, "message": msg},
        }
    return {
        "ok": False,
        "error": {"code": ERROR_POLICY_REFUSAL, "message": str(exc)},
    }


def _attach_receipt_summary(payload: dict[str, Any]) -> dict[str, Any]:
    receipt = gate.get_last_receipt()
    if isinstance(receipt, dict):
        payload["policy_receipt"] = {
            "schema": receipt.get("schema"),
            "op": receipt.get("op"),
            "verdict": receipt.get("verdict"),
            "plan_digest": receipt.get("plan_digest"),
            "source_closure_sha256": receipt.get("source_closure_sha256"),
            "authority_model": receipt.get("authority_model"),
            "checks": receipt.get("checks", []),
        }
    return payload


def host_status(*, workspace_root: str | Path | None = None) -> dict[str, Any]:
    """Return automatic SkillC policy status, bundle root, workspace root, and last receipt."""
    try:
        ws = resolve_trusted_workspace(workspace_root)
        status = gate.get_policy_status()
        last_receipt = gate.get_last_receipt()
        return {
            "ok": True,
            "result": {
                **status,
                "mcp_server": MCP_SERVER_NAME,
                "bundle_root": str(BUNDLE_ROOT),
                "workspace_root": str(ws),
                "authority_disclosure": gate.AUTHORITY_DISCLOSURE,
                "last_receipt": last_receipt,
            },
        }
    except Exception as exc:
        return _format_error_response(exc)


def host_check_prose(
    *,
    text: str | None = None,
    source_path: str | None = None,
    profile: str = "relaxed",
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    """Run guarded STE-Pro-Max advisory prose diagnostics on text or a workspace file."""
    _clear_stale_receipt()
    try:
        ws = resolve_trusted_workspace(workspace_root)
        if not isinstance(profile, str) or profile not in writing.LIMITS:
            raise PolicyError(
                f"Unsupported prose profile {profile!r}; choose from {sorted(writing.LIMITS)}.",
                code=ERROR_INVALID_INPUT,
            )
        if (text is None and source_path is None) or (text is not None and source_path is not None):
            raise PolicyError(
                "Provide exactly one of 'text' or 'source_path' for ste_check_prose.",
                code=ERROR_INVALID_INPUT,
            )

        resolved_source: Path | None = None
        if source_path is not None:
            resolved_source = _resolve_host_read_path(source_path, ws, "source_path")
            resolved_source = gate._safe_existing_file(resolved_source, "source_path")
            prose_text = resolved_source.read_bytes().decode("utf-8-sig")
        else:
            if not isinstance(text, str) or not text.strip():
                raise PolicyError("text must be a non-empty string.", code=ERROR_INVALID_INPUT)
            prose_text = text

        digest = _sha256_text(prose_text)
        guard_inputs: dict[str, Any] = {
            "caller_kind": "host",
            "workspace_root": str(ws),
            "source_paths": [str(resolved_source)] if resolved_source else [],
            "source_digest": digest,
            "text_sha256": digest,
            "source_kind": "markdown" if resolved_source else "prose",
            "profile": profile,
        }

        def _effect() -> dict[str, Any]:
            return writing.check_text(prose_text, profile)

        def _validate(report: dict[str, Any]) -> dict[str, Any]:
            if not isinstance(report, dict) or "findings" not in report or "limitations" not in report:
                raise PolicyError("Invalid prose check report.", code=ERROR_POSTCONDITION_FAILURE)
            return {
                "status": "checked",
                "native_status": "checked",
                "outputs": {},
                "checks": ["prose_advisory_checked", "limitations_preserved"],
                "warnings": list(report.get("limitations", [])),
            }

        report = gate.run_guarded_operation(
            "ste.prose",
            guard_inputs,
            _effect,
            validate_result=_validate,
        )
        result = _attach_receipt_summary({
            **report,
            "source_path": str(resolved_source) if resolved_source else None,
            "text_sha256": digest,
        })
        return {"ok": True, "result": result}
    except Exception as exc:
        return _format_error_response(exc)


def host_write_artifact(
    *,
    target_path: str,
    content: str,
    expected_before_sha256: str | None = None,
    source_paths: list[str] | None = None,
    evidence_paths: list[str] | None = None,
    evidence_root: str | None = None,
    source_kind: str = "host_content",
    trusted_html: bool = False,
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    """Write or update a host-authored STE artifact/document inside the workspace under SkillC policy."""
    _clear_stale_receipt()
    try:
        ws = resolve_trusted_workspace(workspace_root)
        target = validate_host_target_path(
            target_path,
            ws,
            "target_path",
            is_directory=False,
            require_document_extension=True,
        )
        if not isinstance(content, str) or not content.strip() or "\x00" in content:
            raise PolicyError(
                "content must be a non-empty UTF-8 string without null bytes.",
                code=ERROR_INVALID_INPUT,
            )
        if type(trusted_html) is not bool:
            raise PolicyError("trusted_html must be a boolean.", code=ERROR_INVALID_INPUT)
        if not isinstance(source_kind, str) or source_kind not in {"host_content", "raw_html", "structured", "markdown", "story"}:
            raise PolicyError(
                f"Unsupported source_kind {source_kind!r}; use 'host_content' for generated/authored artifacts "
                "or 'raw_html' for imported raw HTML.",
                code=ERROR_INVALID_INPUT,
            )
        if source_kind == "raw_html" and not trusted_html:
            raise PolicyError(
                "Raw HTML requires explicit --trusted-html consent; review the authored content first.",
                code=ERROR_POLICY_REFUSAL,
            )

        if target.exists():
            if expected_before_sha256 is None:
                raise PolicyError(
                    f"Target file already exists ({target}); supply expected_before_sha256 to update an existing file.",
                    code=ERROR_POLICY_REFUSAL,
                )
            if not isinstance(expected_before_sha256, str) or not _HEX64.fullmatch(expected_before_sha256):
                raise PolicyError(
                    "expected_before_sha256 must be a 64-character lowercase hex SHA-256 digest.",
                    code=ERROR_INVALID_INPUT,
                )
        else:
            if expected_before_sha256 is not None:
                raise PolicyError(
                    f"Target file does not exist ({target}), but expected_before_sha256 was provided.",
                    code=ERROR_POLICY_REFUSAL,
                )

        if source_paths is not None and (
            not isinstance(source_paths, list) or not all(isinstance(item, str) for item in source_paths)
        ):
            raise PolicyError("source_paths must be a list of strings.", code=ERROR_INVALID_INPUT)
        resolved_sources: list[str] = []
        for idx, sp in enumerate(source_paths or []):
            res_sp = _resolve_host_read_path(sp, ws, f"source_paths[{idx}]")
            resolved_sources.append(str(gate._safe_existing_file(res_sp, f"source_paths[{idx}]")))

        if evidence_paths is not None and (
            not isinstance(evidence_paths, list) or not all(isinstance(item, str) for item in evidence_paths)
        ):
            raise PolicyError("evidence_paths must be a list of strings.", code=ERROR_INVALID_INPUT)
        resolved_evidence: list[str] = []
        for idx, ep in enumerate(evidence_paths or []):
            res_ep = _resolve_host_read_path(ep, ws, f"evidence_paths[{idx}]")
            resolved_evidence.append(str(gate._safe_existing_file(res_ep, f"evidence_paths[{idx}]")))

        resolved_ev_root: str | None = None
        if evidence_root is not None:
            res_er = _resolve_host_read_path(evidence_root, ws, "evidence_root")
            resolved_ev_root = str(gate._safe_existing_dir(res_er, "evidence_root"))

        content_bytes = content.encode("utf-8")
        content_sha = _sha256_bytes(content_bytes)
        has_script = bool(re.search(r"<script\b", content, re.I))

        guard_inputs: dict[str, Any] = {
            "caller_kind": "host",
            "workspace_root": str(ws),
            "target_paths": [str(target)],
            "source_paths": resolved_sources,
            "source_digest": content_sha,
            "content_sha256": content_sha,
            "source_kind": source_kind,
            "trusted_html": trusted_html,
            "has_raw_html": source_kind == "raw_html",
            "proposed_contents": {str(target): content},
            "expected_before": {str(target): expected_before_sha256},
        }
        if resolved_evidence:
            guard_inputs["evidence_paths"] = resolved_evidence
        if resolved_ev_root is not None:
            guard_inputs["evidence_root"] = resolved_ev_root

        def _effect() -> dict[str, Any]:
            target.parent.mkdir(parents=True, exist_ok=True)
            for parent in (target.parent, *target.parent.parents):
                if parent.is_relative_to(ws) or parent == ws:
                    if is_link_or_reparse(parent.lstat()):
                        raise PolicyError(
                            f"Unsafe link detected in target directory ancestry: {parent}",
                            code=ERROR_POSTCONDITION_FAILURE,
                        )
            if expected_before_sha256 is None:
                with target.open("xb") as stream:
                    stream.write(content_bytes)
            else:
                if target.is_symlink() or not target.is_file():
                    raise PolicyError("Target is not a regular file.", code=ERROR_POSTCONDITION_FAILURE)
                with target.open("wb") as stream:
                    stream.write(content_bytes)
            return {
                "path": str(target),
                "sha256": content_sha,
                "size": len(content_bytes),
            }

        def _validate(write_res: dict[str, Any]) -> dict[str, Any]:
            if target.is_symlink() or not target.is_file():
                raise PolicyError("Written target file is missing or unsafe.", code=ERROR_POSTCONDITION_FAILURE)
            disk_bytes = target.read_bytes()
            disk_sha = _sha256_bytes(disk_bytes)
            if disk_sha != content_sha or len(disk_bytes) != len(content_bytes):
                raise PolicyError(
                    "Written target file does not match proposed_contents.",
                    code=ERROR_POSTCONDITION_FAILURE,
                )
            warnings = [
                "Structural, path, and SHA-256 integrity checks passed; semantic/visual quality review remains manual."
            ]
            if has_script:
                warnings.append(
                    "Interactive HTML/SVG contains <script>; structural and hash integrity were verified, "
                    "not general JavaScript behavior or sandbox safety."
                )
            if source_kind == "raw_html" and trusted_html:
                warnings.append("Imported raw HTML was explicitly trusted, not sanitized.")
            return {
                "status": "written",
                "native_status": "written",
                "outputs": {
                    str(target): {
                        "sha256": disk_sha,
                        "size": len(disk_bytes),
                    }
                },
                "checks": [
                    "host_artifact_written",
                    "workspace_target_confined",
                    "utf8_valid",
                    "proposed_contents_matched",
                ],
                "warnings": warnings,
            }

        write_res = gate.run_guarded_operation(
            "ste.host_write_artifact",
            guard_inputs,
            _effect,
            validate_result=_validate,
        )
        result = _attach_receipt_summary({
            "status": "written",
            "target_path": write_res["path"],
            "sha256": write_res["sha256"],
            "size": write_res["size"],
            "source_kind": source_kind,
            "js_verification": "structural-and-integrity-only" if has_script else "not-applicable",
        })
        return {"ok": True, "result": result}
    except Exception as exc:
        return _format_error_response(exc)


def host_render_bundle(
    *,
    input_path: str,
    output_dir: str,
    title: str | None = None,
    design_path: str | None = None,
    evidence: list[str] | None = None,
    evidence_root: str | None = None,
    trusted_html: bool = False,
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    """Render a complete native STE-Pro-Max bundle (.html, .DESIGN.md, .meta.yaml, gallery.html, manifest.json)."""
    _clear_stale_receipt()
    try:
        ws = resolve_trusted_workspace(workspace_root)
        resolved_source = _resolve_host_read_path(input_path, ws, "input_path")
        resolved_source = gate._safe_existing_file(resolved_source, "input_path")
        resolved_out = validate_host_target_path(
            output_dir,
            ws,
            "output_dir",
            is_directory=True,
            require_document_extension=False,
        )
        if title is not None and (not isinstance(title, str) or not title.strip()):
            raise PolicyError("Title must not be empty.", code=ERROR_INVALID_INPUT)

        resolved_design: Path | None = None
        if design_path is not None:
            resolved_design = _resolve_host_read_path(design_path, ws, "design_path")
            resolved_design = gate._safe_existing_file(resolved_design, "design_path")

        if evidence is not None and (
            not isinstance(evidence, list) or not all(isinstance(item, str) for item in evidence)
        ):
            raise PolicyError("evidence must be a list of strings.", code=ERROR_INVALID_INPUT)
        resolved_evidence: list[str] = []
        for idx, ev_item in enumerate(evidence or []):
            res_ev = _resolve_host_read_path(ev_item, ws, f"evidence[{idx}]")
            resolved_evidence.append(str(gate._safe_existing_file(res_ev, f"evidence[{idx}]")))

        resolved_ev_root: str | None = None
        if evidence_root is not None:
            res_er = _resolve_host_read_path(evidence_root, ws, "evidence_root")
            resolved_ev_root = str(gate._safe_existing_dir(res_er, "evidence_root"))

        if type(trusted_html) is not bool:
            raise PolicyError("trusted_html must be a boolean.", code=ERROR_INVALID_INPUT)

        source_paths_list = [str(resolved_source)]
        if resolved_design is not None:
            source_paths_list.append(str(resolved_design))

        host_inputs: dict[str, Any] = {
            "caller_kind": "host",
            "workspace_root": str(ws),
            "output_root": str(resolved_out),
            "target_paths": [str(resolved_out / "manifest.json")],
            "source_paths": source_paths_list,
            "trusted_html": trusted_html,
        }
        if title is not None:
            host_inputs["title"] = title
        if resolved_design is not None:
            host_inputs["design_path"] = str(resolved_design)
        if resolved_evidence:
            host_inputs["evidence_paths"] = resolved_evidence
        if resolved_ev_root is not None:
            host_inputs["evidence_root"] = resolved_ev_root

        args = argparse.Namespace(
            input=str(resolved_source),
            output_dir=str(resolved_out),
            title=title,
            design=str(resolved_design) if resolved_design is not None else None,
            evidence=resolved_evidence,
            evidence_root=resolved_ev_root,
            trusted_html=trusted_html,
        )

        def _effect() -> dict[str, Any]:
            _ensure_render_deps_on_path()
            with _TemporaryWorkingDirectory(ws):
                manifest = cli.render(args)
            if not isinstance(manifest, dict) or manifest.get("status") != "complete":
                warnings_msg = (
                    "; ".join(str(w) for w in manifest.get("warnings", []))
                    if isinstance(manifest, dict)
                    else "Native render bundle failed."
                )
                raise PolicyError(
                    warnings_msg or "Native render bundle failed.",
                    code=ERROR_POSTCONDITION_FAILURE,
                    partial_result=manifest,
                )
            return manifest

        manifest = gate.run_guarded_operation("ste.render_bundle", host_inputs, _effect)
        result = _attach_receipt_summary(dict(manifest))
        return {"ok": True, "result": result}
    except Exception as exc:
        return _format_error_response(exc)


def host_render_artifact(
    *,
    output_dir: str,
    input_path: str | None = None,
    input_data: dict[str, Any] | None = None,
    title: str | None = None,
    design_path: str | None = None,
    trusted_html: bool = False,
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    """Render a native HTML/DESIGN/meta triple directly into an artifact directory inside the workspace."""
    _clear_stale_receipt()
    try:
        ws = resolve_trusted_workspace(workspace_root)
        resolved_out = validate_host_target_path(
            output_dir,
            ws,
            "output_dir",
            is_directory=True,
            require_document_extension=False,
        )
        if (input_path is None and input_data is None) or (input_path is not None and input_data is not None):
            raise PolicyError(
                "Provide exactly one of 'input_path' or 'input_data' for ste_render_artifact.",
                code=ERROR_INVALID_INPUT,
            )
        if type(trusted_html) is not bool:
            raise PolicyError("trusted_html must be a boolean.", code=ERROR_INVALID_INPUT)
        if title is not None and (not isinstance(title, str) or not title.strip()):
            raise PolicyError("Title must not be empty.", code=ERROR_INVALID_INPUT)

        _ensure_render_deps_on_path()
        from ste_promax import render  # noqa: E402

        resolved_src: Path | None = None
        orig_src_bytes: bytes | None = None
        src_sha: str | None = None
        norm_sha: str | None = None
        if input_path is not None:
            resolved_src = _resolve_host_read_path(input_path, ws, "input_path")
            resolved_src = gate._safe_existing_file(resolved_src, "input_path")
            orig_src_bytes, norm_bytes, parsed_data = cli.normalized_input(resolved_src, title, trusted_html)
            src_sha = _sha256_bytes(orig_src_bytes)
            norm_sha = _sha256_bytes(norm_bytes)
            source_digest = norm_sha
        else:
            if not isinstance(input_data, dict):
                raise PolicyError("input_data must be a JSON object.", code=ERROR_INVALID_INPUT)
            parsed_data = dict(input_data)
            if title is not None:
                parsed_data["title"] = title
            canonical_payload = json.dumps(
                parsed_data,
                ensure_ascii=False,
                sort_keys=True,
                allow_nan=False,
            ).encode("utf-8")
            source_digest = _sha256_bytes(canonical_payload)

        if isinstance(parsed_data, dict) and parsed_data.get("kind") == "story":
            for idx, src_entry in enumerate(parsed_data.get("sources", [])):
                if isinstance(src_entry, dict) and "locator" in src_entry:
                    check_sensitive_read_path(
                        src_entry["locator"],
                        f"story.sources[{idx}].locator",
                        code=ERROR_POLICY_REFUSAL,
                    )

        resolved_design: Path | None = None
        orig_design_bytes: bytes | None = None
        design_sha: str | None = None
        if design_path is not None:
            resolved_design = _resolve_host_read_path(design_path, ws, "design_path")
            resolved_design = gate._safe_existing_file(resolved_design, "design_path")
            orig_design_bytes = resolved_design.read_bytes()
            if not orig_design_bytes:
                raise PolicyError(f"design_path must not be empty: {resolved_design}", code=ERROR_INVALID_INPUT)
            design_sha = _sha256_bytes(orig_design_bytes)

        has_raw_html = bool(render._has_raw_html(parsed_data))
        source_kind = (
            "raw_html"
            if has_raw_html
            else ("story" if isinstance(parsed_data, dict) and parsed_data.get("kind") == "story" else "structured")
        )
        source_paths_list: list[str] = []
        if resolved_src is not None:
            source_paths_list.append(str(resolved_src))
        if resolved_design is not None and str(resolved_design) not in source_paths_list:
            source_paths_list.append(str(resolved_design))

        host_inputs: dict[str, Any] = {
            "caller_kind": "host",
            "workspace_root": str(ws),
            "output_root": str(resolved_out),
            "source_paths": source_paths_list,
            "source_digest": source_digest,
            "source_kind": source_kind,
            "trusted_html": trusted_html,
            "has_raw_html": has_raw_html,
        }
        if src_sha is not None and norm_sha is not None:
            host_inputs["source_sha256"] = src_sha
            host_inputs["normalized_input_sha256"] = norm_sha
        if resolved_design is not None and design_sha is not None:
            host_inputs["design_path"] = str(resolved_design)
            host_inputs["design_sha256"] = design_sha
        if title is not None:
            host_inputs["title"] = title

        def _effect() -> dict[str, Any]:
            if resolved_src is not None and orig_src_bytes is not None:
                if (
                    resolved_src.is_symlink()
                    or not resolved_src.is_file()
                    or resolved_src.read_bytes() != orig_src_bytes
                ):
                    raise PolicyError(
                        f"Original input file changed before rendering: {resolved_src}",
                        code=ERROR_POSTCONDITION_FAILURE,
                    )
            if resolved_design is not None and orig_design_bytes is not None:
                if (
                    resolved_design.is_symlink()
                    or not resolved_design.is_file()
                    or resolved_design.read_bytes() != orig_design_bytes
                ):
                    raise PolicyError(
                        f"Design file changed before rendering: {resolved_design}",
                        code=ERROR_POSTCONDITION_FAILURE,
                    )
            with _TemporaryWorkingDirectory(ws):
                return render.render_artifact(
                    parsed_data,
                    design_path=resolved_design,
                    output_dir=resolved_out,
                    trusted_html=trusted_html,
                )

        triple = gate.run_guarded_operation("ste.render_artifact", host_inputs, _effect)

        serialized_triple = {
            "html_path": str(Path(triple["html_path"]).resolve()),
            "design_path": str(Path(triple["design_path"]).resolve()),
            "meta_path": str(Path(triple["meta_path"]).resolve()),
            "slug": str(triple["slug"]),
            "status": "complete",
        }
        result = _attach_receipt_summary(serialized_triple)
        return {"ok": True, "result": result}
    except Exception as exc:
        return _format_error_response(exc)


def host_regenerate_gallery(
    *,
    artifact_dir: str,
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    """Regenerate gallery.html for an artifact directory inside the workspace."""
    _clear_stale_receipt()
    try:
        ws = resolve_trusted_workspace(workspace_root)
        resolved_dir = validate_host_target_path(
            artifact_dir,
            ws,
            "artifact_dir",
            is_directory=True,
            require_document_extension=False,
        )
        _ensure_render_deps_on_path()
        from ste_promax import gallery  # noqa: E402

        if resolved_dir.is_symlink():
            raise PolicyError("Refusing to use a symlink as artifact directory.", code=ERROR_POLICY_REFUSAL)
        resolved_gallery = resolved_dir / "gallery.html"
        if resolved_gallery.is_symlink():
            raise PolicyError("Refusing to replace a symlink at gallery.html", code=ERROR_POLICY_REFUSAL)
        expected_before_hash: str | None = None
        if resolved_gallery.exists():
            if not resolved_gallery.is_file():
                raise PolicyError("gallery.html is not a regular file.", code=ERROR_INVALID_INPUT)
            existing_bytes = resolved_gallery.read_bytes()
            try:
                existing_text = existing_bytes.decode("utf-8").replace("\r\n", "\n")
            except UnicodeDecodeError as exc:
                raise PolicyError("Refusing to overwrite an unowned gallery.html", code=ERROR_POLICY_REFUSAL) from exc
            if not existing_text.startswith(gallery._GALLERY_PREFIX):
                raise PolicyError("Refusing to overwrite an unowned gallery.html", code=ERROR_POLICY_REFUSAL)
            expected_before_hash = _sha256_bytes(existing_bytes)

        bound_sources: list[str] = []
        bound_evidence: list[str] = []
        manifest_file = resolved_dir / "manifest.json"
        if manifest_file.exists():
            if manifest_file.is_symlink() or not manifest_file.is_file():
                raise PolicyError("Bundle manifest.json is not a regular file.", code=ERROR_POLICY_REFUSAL)
            manifest_obj = loads_json(manifest_file.read_bytes().decode("utf-8"))
            if isinstance(manifest_obj, dict):
                raw_sp = manifest_obj.get("source_path")
                if isinstance(raw_sp, str) and raw_sp.strip():
                    res_sp = _resolve_host_read_path(raw_sp, ws, "manifest.source_path")
                    res_sp = gate._safe_existing_file(res_sp, "manifest.source_path")
                    if not res_sp.is_relative_to(resolved_dir) and resolved_dir != res_sp.parent:
                        bound_sources.append(str(res_sp))
                ev_list = manifest_obj.get("evidence_files")
                if isinstance(ev_list, list):
                    for idx, ev_entry in enumerate(ev_list):
                        if isinstance(ev_entry, dict) and isinstance(ev_entry.get("source_path"), str):
                            res_ev = _resolve_host_read_path(
                                ev_entry["source_path"],
                                ws,
                                f"manifest.evidence_files[{idx}].source_path",
                            )
                            res_ev = gate._safe_existing_file(
                                res_ev,
                                f"manifest.evidence_files[{idx}].source_path",
                            )
                            if (
                                not res_ev.is_relative_to(resolved_dir)
                                and resolved_dir != res_ev.parent
                                and str(res_ev) not in bound_sources
                                and str(res_ev) not in bound_evidence
                            ):
                                bound_evidence.append(str(res_ev))

        sidecar_hasher = hashlib.sha256()
        if resolved_dir.exists() and resolved_dir.is_dir():
            for meta_file in sorted(resolved_dir.glob("*.meta.yaml"), key=lambda p: p.name):
                if meta_file.is_symlink() or not meta_file.is_file():
                    continue
                sidecar_hasher.update(meta_file.name.encode("utf-8") + b"\x00" + meta_file.read_bytes() + b"\x00")

        host_inputs: dict[str, Any] = {
            "caller_kind": "host",
            "workspace_root": str(ws),
            "output_root": str(resolved_dir),
            "target_paths": [str(resolved_gallery)],
            "source_paths": bound_sources,
            "source_digest": sidecar_hasher.hexdigest(),
            "source_kind": "structured",
            "trusted_html": False,
            "expected_before": {str(resolved_gallery): expected_before_hash},
        }
        if bound_evidence:
            host_inputs["evidence_paths"] = bound_evidence

        def _effect() -> Path:
            with _TemporaryWorkingDirectory(ws):
                return gallery.regenerate_gallery(resolved_dir)

        gallery_path = gate.run_guarded_operation("ste.regenerate_gallery", host_inputs, _effect)
        resolved_gallery_out = Path(gallery_path).resolve()
        raw = resolved_gallery_out.read_bytes()
        result = _attach_receipt_summary({
            "status": "complete",
            "gallery_path": str(resolved_gallery_out),
            "sha256": _sha256_bytes(raw),
            "size": len(raw),
        })
        return {"ok": True, "result": result}
    except Exception as exc:
        return _format_error_response(exc)


def host_prepare_story_media(
    *,
    input_path: str,
    output_dir: str,
    voice: str | None = None,
    audio_dir: str | None = None,
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    """Prepare local evidence-linked story media (composition, captions, transcript, review.html, WAVs)."""
    _clear_stale_receipt()
    try:
        ws = resolve_trusted_workspace(workspace_root)
        resolved_source = _resolve_host_read_path(input_path, ws, "input_path")
        resolved_source = gate._safe_existing_file(resolved_source, "input_path")
        resolved_out = validate_host_target_path(
            output_dir,
            ws,
            "output_dir",
            is_directory=True,
            require_document_extension=False,
        )
        if voice is not None and (not isinstance(voice, str) or not voice.strip() or "\x00" in voice):
            raise PolicyError("Voice must be a nonempty name.", code=ERROR_INVALID_INPUT)
        resolved_audio: Path | None = None
        if audio_dir is not None:
            res_ad = _resolve_host_read_path(audio_dir, ws, "audio_dir")
            resolved_audio = gate._safe_existing_dir(res_ad, "audio_dir")
        if resolved_audio is not None and voice is not None:
            raise PolicyError(
                "Choose audio_dir OR local speech; do not combine audio_dir with voice/speaker.",
                code=ERROR_INVALID_INPUT,
            )

        _ensure_render_deps_on_path()
        from ste_promax import media  # noqa: E402

        orig_story_bytes = resolved_source.read_bytes()
        if not orig_story_bytes:
            raise PolicyError(f"input_path must not be empty: {resolved_source}", code=ERROR_INVALID_INPUT)
        story_obj = loads_json(orig_story_bytes.decode("utf-8-sig"))
        if isinstance(story_obj, dict) and not gate._is_builtin_quickstart_source(resolved_source):
            for idx, src_entry in enumerate(story_obj.get("sources", [])):
                if isinstance(src_entry, dict) and "locator" in src_entry:
                    check_sensitive_read_path(
                        src_entry["locator"],
                        f"story.sources[{idx}].locator",
                        code=ERROR_POLICY_REFUSAL,
                    )
        gate.validate_story(story_obj)
        assert isinstance(story_obj, dict)

        ev_root = gate._default_evidence_root_for_source(resolved_source)
        if not gate._is_builtin_quickstart_source(resolved_source):
            for idx, src_entry in enumerate(story_obj.get("sources", [])):
                if isinstance(src_entry, dict) and "locator" in src_entry:
                    res_loc, _ = gate._validate_relative_locator(
                        src_entry["locator"],
                        f"story.sources[{idx}]",
                        ev_root,
                    )
                    _resolve_host_read_path(res_loc, ws, f"story.sources[{idx}].locator")

        source_paths_list = [str(resolved_source)]
        if resolved_audio is not None:
            companions = media.story_companions(story_obj)
            cues = json.loads(companions["narration.json"])["cues"]
            for cue in cues:
                wav_candidate = _resolve_host_read_path(
                    resolved_audio / f"{cue['id']}.wav",
                    ws,
                    f"audio_dir/{cue['id']}.wav",
                )
                wav_file = gate._safe_existing_file(wav_candidate, f"audio_dir/{cue['id']}.wav")
                if str(wav_file) not in source_paths_list:
                    source_paths_list.append(str(wav_file))

        speech_ok = True if resolved_audio is not None else bool(
            media.shutil.which("powershell.exe") and media.NARRATOR.is_file()
        )
        host_inputs: dict[str, Any] = {
            "caller_kind": "host",
            "workspace_root": str(ws),
            "output_root": str(resolved_out),
            "source_paths": source_paths_list,
            "source_sha256": _sha256_bytes(orig_story_bytes),
            "source_kind": "story",
            "audio_dir": str(resolved_audio) if resolved_audio is not None else None,
            "voice": voice,
            "speech_available": speech_ok,
        }

        def _effect() -> dict[str, Any]:
            if (
                resolved_source.is_symlink()
                or not resolved_source.is_file()
                or resolved_source.read_bytes() != orig_story_bytes
            ):
                raise PolicyError(
                    f"Original story source file changed before media preparation: {resolved_source}",
                    code=ERROR_POSTCONDITION_FAILURE,
                )
            with _TemporaryWorkingDirectory(ws):
                return media.prepare_story_media(
                    resolved_source,
                    resolved_out,
                    voice=voice,
                    audio_dir=resolved_audio,
                )

        manifest = gate.run_guarded_operation("ste.prepare_story_media", host_inputs, _effect)
        result = _attach_receipt_summary(dict(manifest))
        return {"ok": True, "result": result}
    except Exception as exc:
        return _format_error_response(exc)


def host_synthesize_wav(
    *,
    text_path: str,
    audio_path: str,
    voice: str | None = None,
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    """Synthesize a verified non-silent PCM WAV file from a local text file inside the workspace."""
    _clear_stale_receipt()
    try:
        ws = resolve_trusted_workspace(workspace_root)
        resolved_text = _resolve_host_read_path(text_path, ws, "text_path")
        resolved_text = gate._safe_existing_file(resolved_text, "text_path")
        resolved_audio = validate_host_target_path(
            audio_path,
            ws,
            "audio_path",
            is_directory=False,
            require_document_extension=False,
        )
        if resolved_audio.suffix.lower() != ".wav":
            raise PolicyError("audio_path must end with .wav.", code=ERROR_INVALID_INPUT)
        if not resolved_audio.parent.is_dir():
            raise PolicyError(
                "The audio_path parent directory must already exist.",
                code=ERROR_INVALID_INPUT,
            )
        if voice is not None and (not isinstance(voice, str) or not voice.strip() or "\x00" in voice):
            raise PolicyError("Voice must be a nonempty name.", code=ERROR_INVALID_INPUT)

        _ensure_render_deps_on_path()
        from ste_promax import media  # noqa: E402

        host_inputs: dict[str, Any] = {
            "caller_kind": "host",
            "workspace_root": str(ws),
            "source_paths": [str(resolved_text)],
            "target_paths": [str(resolved_audio)],
            "source_kind": "text",
            "text_path": str(resolved_text),
            "audio_path": str(resolved_audio),
            "audio_dir": None,
            "voice": voice,
            "speaker_injected": False,
            "speech_available": bool(media.shutil.which("powershell.exe") and media.NARRATOR.is_file()),
            "expected_before": {str(resolved_audio): None},
        }

        def _effect() -> None:
            with _TemporaryWorkingDirectory(ws):
                return media.synthesize(resolved_text, resolved_audio, voice)

        gate.run_guarded_operation("ste.synthesize_wav", host_inputs, _effect)
        raw_wav = resolved_audio.read_bytes()
        pcm_meta = gate._validate_pcm_wav(raw_wav)
        result = _attach_receipt_summary({
            "status": "synthesized",
            "audio_path": str(resolved_audio),
            "sha256": _sha256_bytes(raw_wav),
            "size": len(raw_wav),
            "pcm": pcm_meta,
        })
        return {"ok": True, "result": result}
    except Exception as exc:
        return _format_error_response(exc)


class _BoundedHtmlInspector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title: str = ""
        self._in_title = False
        self.headings: list[str] = []
        self._current_heading: list[str] | None = None
        self.links: list[str] = []
        self.svg_count = 0
        self.script_count = 0
        self.table_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        if t == "title":
            self._in_title = True
        elif t in {"h1", "h2", "h3"}:
            self._current_heading = []
        elif t == "a":
            for k, v in attrs:
                if k.lower() == "href" and v:
                    self.links.append(v)
        elif t == "svg":
            self.svg_count += 1
        elif t == "script":
            self.script_count += 1
        elif t == "table":
            self.table_count += 1

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t == "title":
            self._in_title = False
        elif t in {"h1", "h2", "h3"} and self._current_heading is not None:
            text = "".join(self._current_heading).strip()
            if text:
                self.headings.append(text)
            self._current_heading = None

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        if self._current_heading is not None:
            self._current_heading.append(data)


def _inspect_html_text(html_text: str, base_dir: Path, workspace_root: Path) -> dict[str, Any]:
    parser = _BoundedHtmlInspector()
    parser.feed(html_text)
    external_refs: list[str] = []
    local_links_resolved: list[str] = []
    local_links_missing: list[str] = []
    for href in parser.links:
        if href.startswith("#") or href.lower().startswith("mailto:"):
            continue
        split = urlsplit(href)
        if split.scheme or href.startswith("//"):
            external_refs.append(href)
            continue
        rel_part = unquote(split.path)
        if not rel_part:
            continue
        candidate = (base_dir / rel_part).resolve()
        alt_candidate = (workspace_root / rel_part).resolve()
        if candidate.exists() or alt_candidate.exists():
            local_links_resolved.append(href)
        else:
            local_links_missing.append(href)
    return {
        "title": parser.title.strip(),
        "headings": parser.headings[:25],
        "svg_count": parser.svg_count,
        "script_count": parser.script_count,
        "table_count": parser.table_count,
        "link_count": len(parser.links),
        "local_links_resolved": local_links_resolved,
        "local_links_missing": local_links_missing,
        "external_references": sorted(set(external_refs)),
    }


MAX_INSPECT_FILE_BYTES = 8 * 1024 * 1024
MAX_INSPECT_FILES = 64


def _read_bounded_inspect_file(
    raw_path: str | Path,
    label: str,
    *,
    allowed_root: Path,
    workspace_root: Path,
) -> tuple[Path, bytes]:
    """Validate path confinement inside `allowed_root` and `workspace_root` BEFORE stat/open, then read bounded bytes."""
    abs_p, resolved_p = check_safe_lexical_path(raw_path, label, code=ERROR_POLICY_REFUSAL)
    gate._check_not_historical_manual_stage(resolved_p, label)
    if not resolved_p.is_relative_to(workspace_root):
        raise PolicyError(
            f"{label} escapes workspace_root {workspace_root}: {resolved_p}",
            code=ERROR_POLICY_REFUSAL,
        )
    if resolved_p == allowed_root or not resolved_p.is_relative_to(allowed_root):
        raise PolicyError(
            f"{label} escapes inspected directory {allowed_root}: {resolved_p}",
            code=ERROR_POLICY_REFUSAL,
        )
    check_sensitive_read_path(resolved_p, label, code=ERROR_POLICY_REFUSAL)
    try:
        info = abs_p.lstat()
    except FileNotFoundError as exc:
        raise PolicyError(f"{label} does not exist: {abs_p}", code=ERROR_INVALID_INPUT) from exc
    if is_link_or_reparse(info) or not stat.S_ISREG(info.st_mode):
        raise PolicyError(f"{label} must be a regular file, not a link: {abs_p}", code=ERROR_POLICY_REFUSAL)
    if info.st_size == 0:
        raise PolicyError(f"{label} must not be empty: {abs_p}", code=ERROR_INVALID_INPUT)
    if info.st_size > MAX_INSPECT_FILE_BYTES:
        raise PolicyError(
            f"{label} exceeds the {MAX_INSPECT_FILE_BYTES}-byte inspection limit: {resolved_p.name}",
            code=ERROR_INVALID_INPUT,
        )
    with resolved_p.open("rb") as handle:
        if os.fstat(handle.fileno()).st_size > MAX_INSPECT_FILE_BYTES:
            raise PolicyError(
                f"{label} exceeds the {MAX_INSPECT_FILE_BYTES}-byte inspection limit: {resolved_p.name}",
                code=ERROR_INVALID_INPUT,
            )
        data = handle.read(MAX_INSPECT_FILE_BYTES + 1)
    if len(data) > MAX_INSPECT_FILE_BYTES:
        raise PolicyError(
            f"{label} exceeds the {MAX_INSPECT_FILE_BYTES}-byte inspection limit: {resolved_p.name}",
            code=ERROR_INVALID_INPUT,
        )
    return resolved_p, data


def host_inspect_artifact(
    *,
    target_path: str,
    headless_browser: bool = False,
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    """Perform bounded static local inspection of an artifact file or bundle directory inside the workspace.

    Never accepts arbitrary shell, Node, or JS code. `headless_browser=True` is refused with
    `unsupported_operation` because an isolated no-network browser sandbox is not provisioned.
    """
    _clear_stale_receipt()
    try:
        ws = resolve_trusted_workspace(workspace_root)
        if type(headless_browser) is not bool:
            raise PolicyError("headless_browser must be a boolean.", code=ERROR_INVALID_INPUT)
        if headless_browser:
            raise PolicyError(
                "Headless browser inspection is not supported in this local adapter because an "
                "isolated no-network browser sandbox is not provisioned; use static local "
                "inspection (headless_browser=False).",
                code=ERROR_UNSUPPORTED_OPERATION,
            )
        resolved = _resolve_host_read_path(target_path, ws, "target_path", allow_bundle_examples=False)
        if not resolved.exists():
            raise PolicyError(f"target_path does not exist: {resolved}", code=ERROR_INVALID_INPUT)
        info = resolved.lstat()
        if is_link_or_reparse(info):
            raise PolicyError(f"target_path must not be a link: {resolved}", code=ERROR_POLICY_REFUSAL)

        is_dir = stat.S_ISDIR(info.st_mode)
        raw_single_bytes: bytes | None = None
        if is_dir:
            gate._reject_if_legacy_manual_stage(resolved, "target_path")
            dir_entries: list[Path] = []
            for idx, entry_p in enumerate(resolved.iterdir()):
                if idx >= MAX_INSPECT_FILES:
                    raise PolicyError(
                        f"Inspected directory exceeds the {MAX_INSPECT_FILES}-entry inspection limit: {resolved}",
                        code=ERROR_INVALID_INPUT,
                    )
                if is_link_or_reparse(entry_p.lstat()):
                    raise PolicyError(
                        f"Inspected directory contains a symbolic link or reparse point: {entry_p}",
                        code=ERROR_POLICY_REFUSAL,
                    )
                dir_entries.append(entry_p)
            guard_inputs: dict[str, Any] = {
                "caller_kind": "host",
                "workspace_root": str(ws),
                "input_dir": str(resolved),
                "target_paths": [str(resolved)],
            }
        else:
            _, raw_single_bytes = _read_bounded_inspect_file(
                resolved,
                "target_path",
                allowed_root=ws,
                workspace_root=ws,
            )
            guard_inputs = {
                "caller_kind": "host",
                "workspace_root": str(ws),
                "source_paths": [str(resolved)],
                "target_paths": [str(resolved)],
                "source_digest": _sha256_bytes(raw_single_bytes),
            }

        def _effect() -> dict[str, Any]:
            summary: dict[str, Any] = {
                "target_path": str(resolved),
                "kind": "directory" if is_dir else "file",
                "inspection_mode": "static-local-analysis",
                "in_app_preview": False,
                "network_access": "none-static-file-parse-only",
                "warnings": [
                    "Bounded static local inspection verifies structure and file integrity only; "
                    "no browser execution, in-app preview, or general JavaScript verification was performed."
                ],
            }
            if is_dir:
                html_target: tuple[Path, bytes] | None = None
                manifest_candidate = resolved / "manifest.json"
                if manifest_candidate.exists():
                    _, manifest_bytes = _read_bounded_inspect_file(
                        manifest_candidate,
                        "manifest.json",
                        allowed_root=resolved,
                        workspace_root=ws,
                    )
                    manifest_data = loads_json(manifest_bytes.decode("utf-8"))
                    if not isinstance(manifest_data, dict):
                        raise PolicyError("manifest.json must be a JSON object.", code=ERROR_INVALID_INPUT)
                    summary["manifest_status"] = manifest_data.get("status")
                    summary["lint_passed"] = manifest_data.get("lint_passed")
                    files_verified: dict[str, bool] = {}
                    files_map = manifest_data.get("files", {})
                    if not isinstance(files_map, dict):
                        raise PolicyError("manifest.files must be a JSON object.", code=ERROR_INVALID_INPUT)
                    if len(files_map) > MAX_INSPECT_FILES:
                        raise PolicyError(
                            f"manifest.files exceeds the {MAX_INSPECT_FILES}-entry inspection limit.",
                            code=ERROR_INVALID_INPUT,
                        )
                    for role, entry in sorted(files_map.items()):
                        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                            raise PolicyError(
                                f"Malformed manifest.files[{role!r}] entry.",
                                code=ERROR_INVALID_INPUT,
                            )
                        res_fp, fp_bytes = _read_bounded_inspect_file(
                            entry["path"],
                            f"manifest.files[{role}]",
                            allowed_root=resolved,
                            workspace_root=ws,
                        )
                        if res_fp.parent != resolved:
                            raise PolicyError(
                                f"manifest.files[{role}] must be a direct file in {resolved}: {res_fp}",
                                code=ERROR_POLICY_REFUSAL,
                            )
                        ok = _sha256_bytes(fp_bytes) == entry.get("sha256")
                        files_verified[role] = ok
                        if role == "html" and ok:
                            html_target = (res_fp, fp_bytes)
                    ev_list = manifest_data.get("evidence_files")
                    if ev_list is not None:
                        if not isinstance(ev_list, list) or len(ev_list) > MAX_INSPECT_FILES:
                            raise PolicyError("Invalid manifest.evidence_files list.", code=ERROR_INVALID_INPUT)
                        for idx, ev_entry in enumerate(ev_list):
                            if not isinstance(ev_entry, dict):
                                raise PolicyError(f"Malformed manifest.evidence_files[{idx}].", code=ERROR_INVALID_INPUT)
                            if "source_path" in ev_entry:
                                _, res_ev_src = check_safe_lexical_path(
                                    ev_entry["source_path"],
                                    f"manifest.evidence_files[{idx}].source_path",
                                    code=ERROR_POLICY_REFUSAL,
                                )
                                gate._check_origin_confinement(
                                    res_ev_src,
                                    f"manifest.evidence_files[{idx}].source_path",
                                    workspace_root=ws,
                                    caller="host",
                                )
                    summary["files_verified"] = files_verified
                if html_target is None:
                    for child in sorted(resolved.iterdir(), key=lambda p: p.name):
                        if child.suffix.lower() == ".html" and child.name != "gallery.html":
                            res_html, html_bytes = _read_bounded_inspect_file(
                                child,
                                f"bundle html ({child.name})",
                                allowed_root=resolved,
                                workspace_root=ws,
                            )
                            html_target = (res_html, html_bytes)
                            break
                if html_target is not None:
                    html_text = html_target[1].decode("utf-8")
                    summary["html_inspection"] = _inspect_html_text(html_text, resolved, ws)
            else:
                assert raw_single_bytes is not None
                summary["sha256"] = _sha256_bytes(raw_single_bytes)
                summary["size"] = len(raw_single_bytes)
                suffix = resolved.suffix.lower()
                if suffix in {".html", ".svg"}:
                    text = raw_single_bytes.decode("utf-8")
                    summary["html_inspection"] = _inspect_html_text(text, resolved.parent, ws)
                elif suffix == ".json":
                    parsed = loads_json(raw_single_bytes.decode("utf-8-sig"))
                    summary["json_valid"] = True
                    if isinstance(parsed, dict):
                        summary["keys"] = sorted(parsed.keys())
            return summary

        inspection = gate.run_guarded_operation("ste.inspect_artifact", guard_inputs, _effect)
        result = _attach_receipt_summary(inspection)
        return {"ok": True, "result": result}
    except Exception as exc:
        return _format_error_response(exc)


def host_export_bundle(
    *,
    input_dir: str,
    output_dir: str,
    evidence: list[str] | None = None,
    evidence_root: str | None = None,
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    """Automatically verify a fresh native STE-Pro-Max bundle and export it to a new workspace directory."""
    _clear_stale_receipt()
    try:
        ws = resolve_trusted_workspace(workspace_root)
        resolved_in = _resolve_host_read_path(input_dir, ws, "input_dir", allow_bundle_examples=False)
        resolved_in = gate._safe_existing_dir(resolved_in, "input_dir")
        gate._reject_if_legacy_manual_stage(resolved_in, "input_dir")
        resolved_out = validate_host_target_path(
            output_dir,
            ws,
            "output_dir",
            is_directory=True,
            require_document_extension=False,
        )

        if evidence is not None and (
            not isinstance(evidence, list) or not all(isinstance(item, str) for item in evidence)
        ):
            raise PolicyError("evidence must be a list of strings.", code=ERROR_INVALID_INPUT)
        resolved_evidence: list[str] = []
        for idx, ev_item in enumerate(evidence or []):
            res_ev = _resolve_host_read_path(ev_item, ws, f"evidence[{idx}]")
            resolved_evidence.append(str(gate._safe_existing_file(res_ev, f"evidence[{idx}]")))

        resolved_ev_root: Path | None = None
        if evidence_root is not None:
            res_er = _resolve_host_read_path(evidence_root, ws, "evidence_root")
            resolved_ev_root = gate._safe_existing_dir(res_er, "evidence_root")

        manifest_candidate = resolved_in / "manifest.json"
        if manifest_candidate.is_file() and not manifest_candidate.is_symlink():
            try:
                raw_manifest = loads_json(manifest_candidate.read_bytes().decode("utf-8"))
            except Exception:
                raw_manifest = None
            if isinstance(raw_manifest, dict):
                raw_src_p = raw_manifest.get("source_path")
                if isinstance(raw_src_p, str) and raw_src_p.strip():
                    _resolve_host_read_path(raw_src_p, ws, "manifest.source_path")
                raw_ev_r = raw_manifest.get("evidence_root")
                if isinstance(raw_ev_r, str) and raw_ev_r.strip():
                    _resolve_host_read_path(raw_ev_r, ws, "manifest.evidence_root")
                raw_ev_list = raw_manifest.get("evidence_files")
                if isinstance(raw_ev_list, list):
                    for idx, ev_entry in enumerate(raw_ev_list):
                        if (
                            isinstance(ev_entry, dict)
                            and isinstance(ev_entry.get("source_path"), str)
                            and ev_entry["source_path"].strip()
                        ):
                            _resolve_host_read_path(
                                ev_entry["source_path"],
                                ws,
                                f"manifest.evidence_files[{idx}].source_path",
                            )

        manifest, _, _, ev_records, _ = gate._validate_native_bundle_for_export(
            resolved_in,
            explicit_evidence_root=resolved_ev_root,
            explicit_evidence_files=resolved_evidence or None,
            workspace_root=ws,
            caller="host",
        )
        resolved_manifest_src = _resolve_host_read_path(manifest["source_path"], ws, "manifest.source_path")
        bound_ev_paths = list(dict.fromkeys([
            *(str(_resolve_host_read_path(item["source_path"], ws, "manifest.evidence_files")) for item in ev_records),
            *resolved_evidence,
        ]))

        host_inputs: dict[str, Any] = {
            "caller_kind": "host",
            "workspace_root": str(ws),
            "input_dir": str(resolved_in),
            "output_root": str(resolved_out),
            "source_paths": [str(resolved_manifest_src)],
            "source_digest": str(manifest["source_sha256"]),
            "source_kind": "bundle",
            "trusted_html": bool(manifest["trusted_html"]),
        }
        if resolved_ev_root is not None:
            host_inputs["evidence_root"] = str(resolved_ev_root)
        elif isinstance(manifest.get("evidence_root"), str) and manifest["evidence_root"].strip():
            host_inputs["evidence_root"] = str(
                _resolve_host_read_path(manifest["evidence_root"], ws, "manifest.evidence_root")
            )
        if bound_ev_paths:
            host_inputs["evidence_paths"] = bound_ev_paths

        def _effect() -> dict[str, Any]:
            with _TemporaryWorkingDirectory(ws):
                return gate.export_bundle(
                    resolved_in,
                    resolved_out,
                    evidence_root=str(resolved_ev_root) if resolved_ev_root is not None else None,
                    evidence=resolved_evidence or None,
                )

        def _validate_export(export_res: dict[str, Any]) -> dict[str, Any]:
            if not isinstance(export_res, dict) or export_res.get("status") != "exported":
                raise PolicyError("Export bundle failed.", code=ERROR_POSTCONDITION_FAILURE)
            outputs_map: dict[str, dict[str, Any]] = {}
            files_dict = export_res.get("files")
            if not isinstance(files_dict, dict) or not files_dict:
                raise PolicyError("Export bundle result is missing files.", code=ERROR_POSTCONDITION_FAILURE)
            for rel_key, meta in sorted(files_dict.items()):
                if not isinstance(meta, dict) or not isinstance(meta.get("path"), str):
                    raise PolicyError(f"Malformed export file entry {rel_key!r}.", code=ERROR_POSTCONDITION_FAILURE)
                res_file = gate._safe_existing_file(
                    meta["path"],
                    f"Exported file {rel_key}",
                    code=ERROR_POSTCONDITION_FAILURE,
                )
                raw_bytes = res_file.read_bytes()
                outputs_map[str(res_file)] = {
                    "sha256": _sha256_bytes(raw_bytes),
                    "size": len(raw_bytes),
                }
            return {
                "native_status": "exported",
                "status": "exported",
                "outputs": outputs_map,
                "checks": [
                    "bundle_manifest_verified",
                    "retained_source_verified",
                    "exported_bytes_immutable",
                ],
                "warnings": list(export_res.get("warnings", [])),
            }

        export_res = gate.run_guarded_operation(
            "ste.export_bundle",
            host_inputs,
            _effect,
            validate_result=_validate_export,
        )
        result = _attach_receipt_summary(dict(export_res))
        return {"ok": True, "result": result}
    except Exception as exc:
        return _format_error_response(exc)


_ACTION_ALIASES: dict[str, str] = {
    "ste_status": "ste_status",
    "status": "ste_status",
    "ste.status": "ste_status",
    "ste_check_prose": "ste_check_prose",
    "check_prose": "ste_check_prose",
    "prose": "ste_check_prose",
    "ste.prose": "ste_check_prose",
    "ste_write_artifact": "ste_write_artifact",
    "write_artifact": "ste_write_artifact",
    "host_write_artifact": "ste_write_artifact",
    "ste.host_write_artifact": "ste_write_artifact",
    "ste_render_bundle": "ste_render_bundle",
    "render_bundle": "ste_render_bundle",
    "ste.render_bundle": "ste_render_bundle",
    "ste_render_artifact": "ste_render_artifact",
    "render_artifact": "ste_render_artifact",
    "ste.render_artifact": "ste_render_artifact",
    "ste_regenerate_gallery": "ste_regenerate_gallery",
    "regenerate_gallery": "ste_regenerate_gallery",
    "ste.regenerate_gallery": "ste_regenerate_gallery",
    "ste_prepare_story_media": "ste_prepare_story_media",
    "prepare_story_media": "ste_prepare_story_media",
    "ste.prepare_story_media": "ste_prepare_story_media",
    "ste_synthesize_wav": "ste_synthesize_wav",
    "synthesize_wav": "ste_synthesize_wav",
    "ste.synthesize_wav": "ste_synthesize_wav",
    "ste_inspect_artifact": "ste_inspect_artifact",
    "inspect_artifact": "ste_inspect_artifact",
    "ste.inspect_artifact": "ste_inspect_artifact",
    "ste_export_bundle": "ste_export_bundle",
    "export_bundle": "ste_export_bundle",
    "ste.export_bundle": "ste_export_bundle",
    "ste_validate_target": "ste_validate_target",
    "validate_target": "ste_validate_target",
}

_ACCEPTED_TOOL_ARGS: dict[str, frozenset[str]] = {
    "ste_status": frozenset(),
    "ste_validate_target": frozenset({
        "target_path",
        "output_dir",
        "path",
        "is_directory",
        "require_document_extension",
    }),
    "ste_check_prose": frozenset({
        "text",
        "source_path",
        "input_path",
        "profile",
    }),
    "ste_write_artifact": frozenset({
        "target_path",
        "path",
        "content",
        "expected_before_sha256",
        "source_paths",
        "evidence_paths",
        "evidence_root",
        "source_kind",
        "trusted_html",
    }),
    "ste_render_bundle": frozenset({
        "input_path",
        "source_path",
        "input",
        "output_dir",
        "output_root",
        "title",
        "design_path",
        "design",
        "evidence",
        "evidence_paths",
        "evidence_root",
        "trusted_html",
    }),
    "ste_render_artifact": frozenset({
        "output_dir",
        "output_root",
        "input_path",
        "source_path",
        "input_data",
        "title",
        "design_path",
        "design",
        "trusted_html",
    }),
    "ste_regenerate_gallery": frozenset({
        "artifact_dir",
        "output_dir",
    }),
    "ste_prepare_story_media": frozenset({
        "input_path",
        "source_path",
        "output_dir",
        "output_root",
        "voice",
        "audio_dir",
    }),
    "ste_synthesize_wav": frozenset({
        "text_path",
        "source_path",
        "audio_path",
        "target_path",
        "voice",
    }),
    "ste_inspect_artifact": frozenset({
        "target_path",
        "input_dir",
        "path",
        "headless_browser",
    }),
    "ste_export_bundle": frozenset({
        "input_dir",
        "output_dir",
        "output_root",
        "evidence",
        "evidence_paths",
        "evidence_root",
    }),
}

_MAX_CLI_OUTPUT_CHARS = 131072


def _pick_arg(call_args: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in call_args:
            return call_args[key]
    return default


def _require_strict_bool(call_args: dict[str, Any], key: str, default: bool) -> bool:
    if key not in call_args:
        return default
    val = call_args[key]
    if type(val) is not bool:
        raise PolicyError(f"{key} must be a boolean.", code=ERROR_INVALID_INPUT)
    return val


def dispatch_host_operation(
    action: str,
    args: dict[str, Any] | None = None,
    *,
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    """Dispatch a single guarded host operation by action/tool name with trusted workspace_root."""
    try:
        if not isinstance(action, str) or not action.strip():
            raise PolicyError("Operation action must be a non-empty string.", code=ERROR_INVALID_INPUT)
        canonical = _ACTION_ALIASES.get(action.strip())
        if canonical is None:
            raise PolicyError(
                f"Unsupported host operation action: {action!r}",
                code=ERROR_UNSUPPORTED_OPERATION,
            )
        if canonical != "ste_status":
            _clear_stale_receipt()
        if args is not None and not isinstance(args, dict):
            raise PolicyError("Operation args must be a JSON object.", code=ERROR_INVALID_INPUT)
        call_args = dict(args) if isinstance(args, dict) else {}

        forbidden_present = sorted(set(call_args.keys()) & (gate.FORBIDDEN_INPUT_KEYS | {"workspace_root"}))
        if forbidden_present:
            raise PolicyError(
                f"Forbidden model/untrusted argument keys in {canonical}: {', '.join(forbidden_present)}",
                code=ERROR_POLICY_REFUSAL,
            )

        accepted_keys = _ACCEPTED_TOOL_ARGS.get(canonical, frozenset())
        unknown_keys = sorted(str(k) for k in set(call_args.keys()) - accepted_keys)
        if unknown_keys:
            raise PolicyError(
                f"Unsupported argument keys for {canonical}: {', '.join(unknown_keys)}",
                code=ERROR_INVALID_INPUT,
            )

        ws = resolve_trusted_workspace(workspace_root)

        if canonical == "ste_status":
            return host_status(workspace_root=ws)
        if canonical == "ste_validate_target":
            target_raw = _pick_arg(call_args, "target_path", "output_dir", "path", default="")
            is_dir = _require_strict_bool(call_args, "is_directory", False)
            req_ext = _require_strict_bool(call_args, "require_document_extension", not is_dir)
            resolved_t = validate_host_target_path(
                target_raw,
                ws,
                "target_path",
                is_directory=is_dir,
                require_document_extension=req_ext,
            )
            status = gate.get_policy_status()
            if not status.get("available", False):
                err = status.get("error") or {}
                raise PolicyBackendError(
                    str(err.get("message") or "SkillC policy backend is unavailable.")
                )
            return {
                "ok": True,
                "result": {
                    "target_path": str(resolved_t),
                    "workspace_root": str(ws),
                    "bundle_root": str(BUNDLE_ROOT),
                    "policy_available": True,
                },
            }
        if canonical == "ste_check_prose":
            return host_check_prose(
                text=_pick_arg(call_args, "text"),
                source_path=_pick_arg(call_args, "source_path", "input_path"),
                profile=_pick_arg(call_args, "profile", default="relaxed"),
                workspace_root=ws,
            )
        if canonical == "ste_write_artifact":
            return host_write_artifact(
                target_path=_pick_arg(call_args, "target_path", "path", default=""),
                content=_pick_arg(call_args, "content", default=""),
                expected_before_sha256=_pick_arg(call_args, "expected_before_sha256"),
                source_paths=_pick_arg(call_args, "source_paths"),
                evidence_paths=_pick_arg(call_args, "evidence_paths"),
                evidence_root=_pick_arg(call_args, "evidence_root"),
                source_kind=_pick_arg(call_args, "source_kind", default="host_content"),
                trusted_html=_require_strict_bool(call_args, "trusted_html", False),
                workspace_root=ws,
            )
        if canonical == "ste_render_bundle":
            return host_render_bundle(
                input_path=_pick_arg(call_args, "input_path", "source_path", "input", default=""),
                output_dir=_pick_arg(call_args, "output_dir", "output_root", default=""),
                title=_pick_arg(call_args, "title"),
                design_path=_pick_arg(call_args, "design_path", "design"),
                evidence=_pick_arg(call_args, "evidence", "evidence_paths"),
                evidence_root=_pick_arg(call_args, "evidence_root"),
                trusted_html=_require_strict_bool(call_args, "trusted_html", False),
                workspace_root=ws,
            )
        if canonical == "ste_render_artifact":
            return host_render_artifact(
                output_dir=_pick_arg(call_args, "output_dir", "output_root", default=""),
                input_path=_pick_arg(call_args, "input_path", "source_path"),
                input_data=_pick_arg(call_args, "input_data"),
                title=_pick_arg(call_args, "title"),
                design_path=_pick_arg(call_args, "design_path", "design"),
                trusted_html=_require_strict_bool(call_args, "trusted_html", False),
                workspace_root=ws,
            )
        if canonical == "ste_regenerate_gallery":
            return host_regenerate_gallery(
                artifact_dir=_pick_arg(call_args, "artifact_dir", "output_dir", default=""),
                workspace_root=ws,
            )
        if canonical == "ste_prepare_story_media":
            return host_prepare_story_media(
                input_path=_pick_arg(call_args, "input_path", "source_path", default=""),
                output_dir=_pick_arg(call_args, "output_dir", "output_root", default=""),
                voice=_pick_arg(call_args, "voice"),
                audio_dir=_pick_arg(call_args, "audio_dir"),
                workspace_root=ws,
            )
        if canonical == "ste_synthesize_wav":
            return host_synthesize_wav(
                text_path=_pick_arg(call_args, "text_path", "source_path", default=""),
                audio_path=_pick_arg(call_args, "audio_path", "target_path", default=""),
                voice=_pick_arg(call_args, "voice"),
                workspace_root=ws,
            )
        if canonical == "ste_inspect_artifact":
            return host_inspect_artifact(
                target_path=_pick_arg(call_args, "target_path", "input_dir", "path", default=""),
                headless_browser=_require_strict_bool(call_args, "headless_browser", False),
                workspace_root=ws,
            )
        if canonical == "ste_export_bundle":
            return host_export_bundle(
                input_dir=_pick_arg(call_args, "input_dir", default=""),
                output_dir=_pick_arg(call_args, "output_dir", "output_root", default=""),
                evidence=_pick_arg(call_args, "evidence", "evidence_paths"),
                evidence_root=_pick_arg(call_args, "evidence_root"),
                workspace_root=ws,
            )
        raise PolicyError(f"Unhandled action: {canonical!r}", code=ERROR_UNSUPPORTED_OPERATION)
    except Exception as exc:
        return _format_error_response(exc)


def main(argv: list[str] | None = None) -> int:
    """Narrow JSON stdin/stdout CLI entry point for host adapters (OpenCode V2 and Copilot)."""
    parser = argparse.ArgumentParser(prog="ste-host-operations")
    parser.add_argument(
        "--workspace",
        "--workspace-root",
        dest="workspace",
        default=None,
        help="Trusted host workspace root directory.",
    )
    parser.add_argument(
        "--action",
        default=None,
        help="Optional operation name when stdin carries only the args JSON object.",
    )
    parsed_args = parser.parse_args(argv)

    try:
        raw_stdin = sys.stdin.read()
        if not raw_stdin.strip():
            req_obj: dict[str, Any] = {}
        else:
            loaded = json.loads(raw_stdin)
            if not isinstance(loaded, dict):
                raise PolicyError("Host operation stdin must be a JSON object.", code=ERROR_INVALID_INPUT)
            req_obj = loaded

        action = (
            parsed_args.action
            or req_obj.get("action")
            or req_obj.get("tool")
            or req_obj.get("op")
        )
        if not isinstance(action, str) or not action.strip():
            raise PolicyError(
                "Missing 'action' (or 'tool'/'op') in JSON request or --action CLI flag.",
                code=ERROR_INVALID_INPUT,
            )

        envelope_key: str | None = None
        for cand_key in ("args", "arguments", "payload", "inputs"):
            if cand_key in req_obj:
                envelope_key = cand_key
                break

        if envelope_key is not None:
            extra_top = sorted(
                str(k)
                for k in set(req_obj.keys()) - {"action", "tool", "op", envelope_key}
            )
            if extra_top:
                raise PolicyError(
                    f"Unsupported top-level request keys alongside {envelope_key!r}: {', '.join(extra_top)}",
                    code=ERROR_INVALID_INPUT,
                )
            op_args = req_obj[envelope_key]
            if not isinstance(op_args, dict):
                raise PolicyError(
                    f"Request {envelope_key!r} must be a JSON object.",
                    code=ERROR_INVALID_INPUT,
                )
        else:
            op_args = {
                k: v
                for k, v in req_obj.items()
                if k not in {"action", "tool", "op"}
            }

        response = dispatch_host_operation(
            action,
            op_args,
            workspace_root=parsed_args.workspace,
        )
    except Exception as exc:
        response = _format_error_response(exc)

    serialized = json.dumps(response, ensure_ascii=True)
    if len(serialized) > _MAX_CLI_OUTPUT_CHARS:
        response = {
            "ok": False,
            "error": {
                "code": ERROR_POSTCONDITION_FAILURE,
                "message": f"Operation output exceeded {_MAX_CLI_OUTPUT_CHARS}-character bound.",
            },
        }
        serialized = json.dumps(response, ensure_ascii=True)
    sys.stdout.write(serialized + "\n")
    sys.stdout.flush()
    return 0 if response.get("ok") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())

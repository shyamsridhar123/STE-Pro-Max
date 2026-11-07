"""Trusted runtime configuration and backend resolution for automatic STE-Pro-Max policy.

Never discovers interpreters or SkillC paths from CWD or untrusted artifact data.
Supports in-process SkillC when available, process environment overrides
(`STE_SKILLC_PYTHON`, `STE_SKILLC_ROOT`, `STE_SKILLC_STATE_ROOT`,
`STE_SKILLC_RUNTIME_CONFIG`), and the user-scoped `ste-promax.runtime.v1` JSON file.
"""
from __future__ import annotations

import os
from pathlib import Path
import stat
import sys
from typing import Any

from ste_promax.json_input import loads_json

RUNTIME_SCHEMA = "ste-promax.runtime.v1"
MANAGED_BY = "ste-promax"

ERROR_DEPENDENCY_MISSING = "dependency_missing"
ERROR_UNSUPPORTED_OPERATION = "unsupported_operation"
ERROR_INVALID_INPUT = "invalid_input"
ERROR_POLICY_REFUSAL = "policy_refusal"
ERROR_POSTCONDITION_FAILURE = "postcondition_failure"

VALID_ERROR_CODES = frozenset({
    ERROR_DEPENDENCY_MISSING,
    ERROR_UNSUPPORTED_OPERATION,
    ERROR_INVALID_INPUT,
    ERROR_POLICY_REFUSAL,
    ERROR_POSTCONDITION_FAILURE,
})

SENSITIVE_READ_SEGMENTS: frozenset[str] = frozenset({
    ".ssh",
    ".gnupg",
    ".aws",
    ".azure",
    ".kube",
    ".copilot",
    ".opencode",
    ".claude",
    ".skillc",
    ".git",
})

SENSITIVE_READ_FILENAMES: frozenset[str] = frozenset({
    ".env",
    ".mcp.json",
    "mcp.json",
    "config.json",
    "runtime.json",
    "opencode.json",
    "oh-my-opencode-slim.json",
    "settings.json",
    "settings.local.json",
    "claude_desktop_config.json",
    "config.toml",
    "authorized_keys",
    "sudoers",
    ".bashrc",
    ".zshrc",
    ".profile",
})


class PolicyError(ValueError):
    """Typed automatic policy error carrying a deterministic error code."""

    def __init__(
        self,
        message: str,
        *,
        code: str = ERROR_POLICY_REFUSAL,
        partial_result: Any = None,
        receipt: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code if code in VALID_ERROR_CODES else ERROR_POLICY_REFUSAL
        self.message = str(message)
        self.partial_result = partial_result
        self.receipt = receipt

    def to_error_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


class PolicyBackendError(PolicyError, RuntimeError):
    """Raised when the required SkillC policy backend is missing or invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code=ERROR_DEPENDENCY_MISSING)


def is_link_or_reparse(info: os.stat_result) -> bool:
    return bool(
        stat.S_ISLNK(info.st_mode)
        or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def require_nonempty_str(value: Any, label: str, *, code: str = ERROR_INVALID_INPUT) -> str:
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise PolicyError(f"{label} must not be empty.", code=code)
    return str(value)


def check_sensitive_read_path(
    path: str | Path,
    label: str = "Input path",
    *,
    code: str = ERROR_POLICY_REFUSAL,
) -> Path:
    """Reject known credential, configuration, and private control origins before reading."""
    text = require_nonempty_str(path, label, code=code)
    if "\x00" in text:
        raise PolicyError(f"{label} must not contain null bytes.", code=code)
    p = Path(text)
    lower_parts = {part.lower() for part in p.parts}
    for secret_seg in SENSITIVE_READ_SEGMENTS:
        if secret_seg.lower() in lower_parts:
            raise PolicyError(
                f"{label} references protected credential/config/control directory {secret_seg!r}.",
                code=code,
            )
    name_lower = p.name.lower()
    if (
        name_lower in {n.lower() for n in SENSITIVE_READ_FILENAMES}
        or name_lower.startswith(".env.")
        or "secret" in name_lower
        or "credential" in name_lower
    ):
        raise PolicyError(
            f"{label} references protected file {p.name!r}.",
            code=code,
        )
    return p


def check_safe_lexical_path(
    raw: str | Path,
    label: str,
    *,
    require_absolute: bool = False,
    allow_leaf_symlink: bool = False,
    code: str = ERROR_INVALID_INPUT,
) -> tuple[Path, Path]:
    text = require_nonempty_str(raw, label, code=code)
    if "\x00" in text:
        raise PolicyError(f"{label} must not contain null bytes.", code=code)
    path = Path(text).expanduser() if allow_leaf_symlink else Path(text)
    if ".." in path.parts or (path.drive and not path.root):
        raise PolicyError(f"{label} must not contain '..' or a drive-relative path.", code=code)
    if str(path).startswith(("\\\\", "//")):
        raise PolicyError(f"{label} must not use UNC or network share paths.", code=code)
    if require_absolute and not path.is_absolute():
        raise PolicyError(f"{label} must be an absolute path: {path}", code=code)
    absolute = path.absolute()
    for part in absolute.parts[1:]:
        if ":" in part or part.endswith((" ", ".")):
            raise PolicyError(
                f"{label} must not use alternate streams or trailing-dot/space components.",
                code=code,
            )
        stem = part.split(".")[0].upper()
        if stem in {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10)),
        }:
            raise PolicyError(f"{label} must not reference a reserved device name: {part}", code=code)
    for current in (absolute, *absolute.parents):
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if is_link_or_reparse(info):
            if allow_leaf_symlink and current == absolute:
                continue
            raise PolicyError(
                f"{label} and its parents must not be symbolic links or Windows reparse points: {current}",
                code=code,
            )
        if current != absolute and not stat.S_ISDIR(info.st_mode):
            raise PolicyError(f"{label} parent must be a directory, not a file: {current}", code=code)
    return absolute, absolute.resolve()


def default_runtime_config_path() -> Path:
    if os.name == "nt" or sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        base = Path(local_app_data) if local_app_data else (Path.home() / "AppData" / "Local")
        return base / "STE-Pro-Max" / "skillc-runtime" / "runtime.json"
    xdg_data_home = os.environ.get("XDG_DATA_HOME", "").strip()
    base = Path(xdg_data_home) if xdg_data_home else (Path.home() / ".local" / "share")
    return base / "ste-promax" / "skillc-runtime" / "runtime.json"


def resolve_runtime_config_path() -> Path:
    override = os.environ.get("STE_SKILLC_RUNTIME_CONFIG", "").strip()
    if override:
        absolute, _ = check_safe_lexical_path(
            override,
            "STE_SKILLC_RUNTIME_CONFIG",
            require_absolute=True,
            code=ERROR_DEPENDENCY_MISSING,
        )
        return absolute
    return default_runtime_config_path()


def validate_runtime_config_dict(data: Any, source_label: str = "runtime.json") -> dict[str, Any]:
    if not isinstance(data, dict):
        raise PolicyBackendError(f"{source_label} must be a JSON object.")
    if data.get("schema") != RUNTIME_SCHEMA:
        raise PolicyBackendError(
            f"{source_label} schema must be {RUNTIME_SCHEMA!r}, got {data.get('schema')!r}."
        )
    if data.get("managed_by") != MANAGED_BY:
        raise PolicyBackendError(
            f"{source_label} managed_by must be {MANAGED_BY!r}, got {data.get('managed_by')!r}."
        )
    required_paths = ("python", "skillc_root", "ste_root", "state_root")
    for key in required_paths:
        val = data.get(key)
        if not isinstance(val, str) or not val.strip():
            raise PolicyBackendError(f"{source_label} field {key!r} must be a non-empty string.")
        check_safe_lexical_path(
            val,
            f"{source_label}.{key}",
            require_absolute=True,
            allow_leaf_symlink=(key == "python"),
            code=ERROR_DEPENDENCY_MISSING,
        )
    skillc_commit = data.get("skillc_commit")
    if not isinstance(skillc_commit, str) or not skillc_commit.strip():
        raise PolicyBackendError(f"{source_label} field 'skillc_commit' must be a non-empty string.")
    versions = data.get("versions")
    if not isinstance(versions, dict):
        raise PolicyBackendError(f"{source_label} field 'versions' must be a JSON object.")
    return dict(data)


def load_runtime_config(config_path: Path | None = None) -> dict[str, Any] | None:
    explicit_env = bool(os.environ.get("STE_SKILLC_RUNTIME_CONFIG", "").strip())
    path = config_path if config_path is not None else resolve_runtime_config_path()
    try:
        info = path.lstat()
    except FileNotFoundError:
        if explicit_env or config_path is not None:
            raise PolicyBackendError(f"Runtime configuration file does not exist: {path}") from None
        return None
    if is_link_or_reparse(info) or not stat.S_ISREG(info.st_mode):
        raise PolicyBackendError(f"Runtime configuration must be a regular file, not a link: {path}")
    try:
        raw_text = path.read_text(encoding="utf-8")
        parsed = loads_json(raw_text)
    except Exception as exc:
        raise PolicyBackendError(f"Malformed runtime configuration in {path}: {exc}") from exc
    return validate_runtime_config_dict(parsed, str(path))


def resolve_state_root(runtime_cfg: dict[str, Any] | None = None) -> Path:
    env_state = os.environ.get("STE_SKILLC_STATE_ROOT", "").strip()
    if env_state:
        _, resolved = check_safe_lexical_path(
            env_state,
            "STE_SKILLC_STATE_ROOT",
            require_absolute=True,
            code=ERROR_INVALID_INPUT,
        )
        return resolved
    cfg = runtime_cfg
    if cfg is None:
        try:
            cfg = load_runtime_config()
        except PolicyError:
            cfg = None
    if isinstance(cfg, dict) and isinstance(cfg.get("state_root"), str):
        _, resolved = check_safe_lexical_path(
            cfg["state_root"],
            "runtime.json.state_root",
            require_absolute=True,
            code=ERROR_DEPENDENCY_MISSING,
        )
        return resolved
    cfg_path = default_runtime_config_path()
    return (cfg_path.parent / "state").absolute()


def has_inprocess_skillc() -> bool:
    if os.environ.get("STE_SKILLC_FORCE_WORKER", "").strip() == "1":
        return False
    try:
        from skillc.checker import check  # noqa: F401
        from skillc.frontend.ce import parse_ce_detailed  # noqa: F401
        from skillc.frontend.runtime import Runtime, bind_runtime  # noqa: F401
        from skillc.frontend.toolpolicy import load_library  # noqa: F401
        from skillc.monitor import ALLOW, Config, Monitor  # noqa: F401
        return True
    except ImportError:
        pass

    # If z3 is available in this interpreter and a trusted skillc_root is configured,
    # bind skillc_src into sys.path for in-process execution.
    try:
        import z3  # noqa: F401
        _, skillc_src = resolve_worker_backend()
        src_str = str(skillc_src)
        if src_str not in sys.path:
            sys.path.insert(0, src_str)
        from skillc.checker import check  # noqa: F401
        from skillc.frontend.ce import parse_ce_detailed  # noqa: F401
        from skillc.frontend.runtime import Runtime, bind_runtime  # noqa: F401
        from skillc.frontend.toolpolicy import load_library  # noqa: F401
        from skillc.monitor import ALLOW, Config, Monitor  # noqa: F401
        return True
    except (ImportError, PolicyError):
        return False


def _resolve_trusted_backend_pair(raw_py: str, raw_root: str, source_label: str) -> tuple[Path, Path]:
    try:
        abs_py, _ = check_safe_lexical_path(
            raw_py,
            f"{source_label} python",
            require_absolute=True,
            allow_leaf_symlink=True,
            code=ERROR_DEPENDENCY_MISSING,
        )
    except PolicyError as exc:
        raise PolicyBackendError(exc.message) from exc
    try:
        resolved_python = abs_py.resolve(strict=True)
    except FileNotFoundError as exc:
        raise PolicyBackendError(f"STE_SKILLC_PYTHON does not exist: {abs_py}") from exc
    if not resolved_python.is_file() or resolved_python.stat().st_size == 0:
        raise PolicyBackendError(
            f"STE_SKILLC_PYTHON must resolve to a non-empty regular file: {resolved_python}"
        )
    # Preserve the configured venv path rather than its base-interpreter symlink target.
    python_exe = abs_py

    try:
        abs_root, _ = check_safe_lexical_path(
            raw_root,
            f"{source_label} skillc_root",
            require_absolute=True,
            allow_leaf_symlink=True,
            code=ERROR_DEPENDENCY_MISSING,
        )
    except PolicyError as exc:
        raise PolicyBackendError(exc.message) from exc
    try:
        root_dir = abs_root.resolve(strict=True)
    except FileNotFoundError as exc:
        raise PolicyBackendError(f"STE_SKILLC_ROOT does not exist: {abs_root}") from exc
    if not root_dir.is_dir():
        raise PolicyBackendError(f"STE_SKILLC_ROOT must resolve to an existing directory: {root_dir}")
    if (root_dir / "skillc" / "__init__.py").is_file():
        skillc_src = root_dir
    elif (root_dir / "src" / "skillc" / "__init__.py").is_file():
        skillc_src = (root_dir / "src").resolve(strict=True)
    else:
        raise PolicyBackendError(
            f"STE_SKILLC_ROOT does not contain skillc/__init__.py or src/skillc/__init__.py: {root_dir}"
        )
    return python_exe, skillc_src


def resolve_worker_backend() -> tuple[Path, Path]:
    raw_py = os.environ.get("STE_SKILLC_PYTHON", "").strip()
    raw_root = os.environ.get("STE_SKILLC_ROOT", "").strip()
    if raw_py or raw_root:
        if not raw_py or not raw_root:
            raise PolicyBackendError(
                "SkillC backend is misconfigured: STE_SKILLC_PYTHON and STE_SKILLC_ROOT "
                "must both be set when using environment overrides."
            )
        return _resolve_trusted_backend_pair(raw_py, raw_root, "STE_SKILLC")

    cfg = load_runtime_config()
    if cfg is not None:
        return _resolve_trusted_backend_pair(cfg["python"], cfg["skillc_root"], "runtime.json")

    raise PolicyBackendError(
        "SkillC backend is unavailable: package 'skillc' (with 'z3') is not installed "
        "in the current Python environment, STE_SKILLC_PYTHON / STE_SKILLC_ROOT are not "
        f"configured, and no runtime.json exists at {resolve_runtime_config_path()}."
    )

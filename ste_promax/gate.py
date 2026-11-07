"""Automatic STE-Pro-Max SkillC policy controller and bundle exporter.

Single-user automatic local policy model:
- Functional roles (`ste-validator`, `ste-executor`) enforce static plan admissibility,
  explicit precondition checks, bounded execution, and independent postcondition
  file/hash/domain verification through SkillC (`skillc.checker.check`,
  `parse_ce_detailed`, `bind_runtime`, and strict `Monitor`).
- All supported STE workflows execute automatically without human approval prompts
  or review tokens.
- Same-user local shell or filesystem access outside STE policy hooks can bypass
  in-process or helper state; source truth and prose entailment remain domain limits.
"""
from __future__ import annotations

import argparse
from collections.abc import Callable
from contextvars import ContextVar
import copy
from dataclasses import dataclass, field
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import struct
import subprocess
import typing
from typing import Any, TypeVar
from urllib.parse import urlsplit

from ste_promax import __version__
from ste_promax import cli
from ste_promax.input_validation import validate_input
from ste_promax.json_input import loads_json
from ste_promax.policy_runtime import (
    ERROR_DEPENDENCY_MISSING,
    ERROR_INVALID_INPUT,
    ERROR_POLICY_REFUSAL,
    ERROR_POSTCONDITION_FAILURE,
    ERROR_UNSUPPORTED_OPERATION,
    PolicyBackendError,
    PolicyError,
    check_safe_lexical_path,
    check_sensitive_read_path,
    default_runtime_config_path,
    has_inprocess_skillc,
    is_link_or_reparse,
    load_runtime_config,
    require_nonempty_str,
    resolve_runtime_config_path,
    resolve_state_root,
    resolve_worker_backend,
)
from ste_promax.stories import validate_story
from ste_promax.writing import LIMITS, check_text

T = TypeVar("T")

TENANT_ID = "local-single-user"
ROLE_VALIDATOR = "ste-validator"
ROLE_EXECUTOR = "ste-executor"
ROLE_MSG_PRECONDITIONS_OK = "preconditions_ok"
ROLE_MSG_EFFECT_DONE = "effect_done"

SKILLC_DIRNAME = ".skillc"
BUNDLE_DIRNAME = "bundle"
STAGE_RECORD_FILE = "stage.json"
APPROVAL_SECRET_FILE = "approval_reference.json"
APPROVAL_DB_FILE = "approvals.sqlite3"
PLAN_FILE = "plan.ce"
STATE_FILE = "state.json"
GUARD_STATE_FILE = "guard-state.json"
RECEIPT_FILE = "receipt.json"
HISTORICAL_MANUAL_STAGE_DIRNAME = "skillc-native-20261106"

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SUITE_EXAMPLES_DIR = (_REPO_ROOT / "examples" / "suite").resolve()
_HISTORICAL_MANUAL_ARTIFACT_ROOT = (_REPO_ROOT / "artifacts" / HISTORICAL_MANUAL_STAGE_DIRNAME).resolve()

_GALLERY_PREFIX = "<!DOCTYPE html>\n<!-- STE-Pro-Max generated gallery -->\n"
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_WORKER_TIMEOUT_SECONDS = 30
_SAFE_ENV_KEYS = (
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
    "TEMP",
    "TMP",
    "TMPDIR",
    "HOME",
    "USERPROFILE",
    "LOCALAPPDATA",
    "APPDATA",
    "XDG_DATA_HOME",
    "PATH",
    "LANG",
    "LC_ALL",
    "PYTHONIOENCODING",
    "STE_SKILLC_RUNTIME_CONFIG",
    "STE_SKILLC_STATE_ROOT",
)

SUPPORTED_OPERATIONS: frozenset[str] = frozenset({
    "ste.render_bundle",
    "ste.render_artifact",
    "ste.regenerate_gallery",
    "ste.prepare_story_media",
    "ste.synthesize_wav",
    "ste.host_write_artifact",
    "ste.inspect_artifact",
    "ste.prose",
    "ste.export_bundle",
})

FILE_PRODUCING_OPERATIONS: frozenset[str] = frozenset({
    "ste.render_bundle",
    "ste.render_artifact",
    "ste.regenerate_gallery",
    "ste.prepare_story_media",
    "ste.synthesize_wav",
    "ste.host_write_artifact",
    "ste.export_bundle",
})

PERMITTED_NESTED_OPERATIONS: dict[str, frozenset[str]] = {
    "ste.render_bundle": frozenset({
        "ste.render_artifact",
        "ste.regenerate_gallery",
        "ste.render_bundle",
    }),
    "ste.prepare_story_media": frozenset({
        "ste.prepare_story_media",
        "ste.synthesize_wav",
    }),
    "ste.render_artifact": frozenset({
        "ste.render_artifact",
    }),
    "ste.regenerate_gallery": frozenset({
        "ste.regenerate_gallery",
    }),
    "ste.synthesize_wav": frozenset({
        "ste.synthesize_wav",
    }),
    "ste.export_bundle": frozenset({
        "ste.export_bundle",
    }),
    "ste.host_write_artifact": frozenset(),
    "ste.inspect_artifact": frozenset(),
    "ste.prose": frozenset(),
}

FORBIDDEN_INPUT_KEYS: frozenset[str] = frozenset({
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
})

ALLOWED_INPUT_KEYS: frozenset[str] = frozenset({
    "caller_kind",
    "caller",
    "workspace_root",
    "output_root",
    "output_dir",
    "output",
    "artifact_dir",
    "input_dir",
    "target_paths",
    "target_path",
    "source_paths",
    "source_path",
    "source",
    "source_digest",
    "source_sha256",
    "normalized_input_sha256",
    "content_sha256",
    "prompt_sha256",
    "text_sha256",
    "source_kind",
    "input_kind",
    "title",
    "design_path",
    "design",
    "design_sha256",
    "trusted_html",
    "has_raw_html",
    "evidence_root",
    "evidence_paths",
    "evidence_files",
    "evidence",
    "evidence_locators",
    "relative_locators",
    "availability",
    "dependencies_ready",
    "render_dependencies_ready",
    "speech_available",
    "speaker_injected",
    "proposed_contents",
    "expected_before",
    "audio_dir",
    "text_path",
    "audio_path",
    "voice",
    "profile",
    "tool_name",
    "session_id",
    "metadata",
})

PROTECTED_PATH_SEGMENTS: frozenset[str] = frozenset({
    ".git",
    ".ssh",
    ".gnupg",
    ".aws",
    ".azure",
    ".kube",
    ".skillc",
    ".opencode",
    ".claude",
    ".copilot",
    ".github",
    ".vscode",
    ".venv",
    ".ste-env",
    "node_modules",
})

PROTECTED_WORKSPACE_DIRS: frozenset[str] = frozenset({
    "ste_promax",
    "integrations",
    "skills",
    "ste-promax",
    "tests",
    "tools",
    "docs",
})

PROTECTED_FILENAMES: frozenset[str] = frozenset({
    ".env",
    ".mcp.json",
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
    "STE-ProMAX.zip",
})

STE_AUTOMATIC_RUNTIME_MANIFEST: dict[str, Any] = {
    "name": "ste-automatic-local-policy",
    "description": (
        "Automatic local STE-Pro-Max policy runtime enforcing precondition, "
        "execution, and postcondition verification with no network, model, or "
        "human approval steps."
    ),
    "tools": {
        "read": "Read and validate local source, design, evidence, and generated artifact files.",
        "write": "Write or update local STE-Pro-Max artifact files inside validated output roots.",
    },
    "grants": [
        "local_filesystem",
    ],
    "lacks": [
        "network access, remote APIs, or model calls",
        "human approval prompts or interactive review tokens",
        "multi-user cryptographic authentication or hardware isolation",
    ],
    "forbid_effects": [
        "reads_external",
        "writes_external",
        "publishes",
    ],
    "software": "preinstalled",
}

STE_LOCAL_RUNTIME_MANIFEST = STE_AUTOMATIC_RUNTIME_MANIFEST

STE_AUTOMATIC_PLAN_CE = """Skill `ste-promax-automatic-policy`.
Roles: `ste-validator`, `ste-executor`.
Tool `validate_preconditions` (owner `ste-validator`): via `read`; needs `local_filesystem`; effect `local`; adds `preconditions_verified`.
Tool `execute_operation` (owner `ste-executor`): via `write`; needs `local_filesystem`; effect `local`; requires `preconditions_verified`; adds `operation_executed`.
Tool `verify_postconditions` (owner `ste-validator`): via `read`; needs `local_filesystem`; effect `local`; requires `preconditions_verified` and `operation_executed`; adds `postconditions_verified`.
Initially true: none.
Goal: `postconditions_verified`.
Protocol:
  - `ste-validator` uses `validate_preconditions`.
  - `ste-validator` tells `ste-executor` `preconditions_ok`.
  - `ste-executor` uses `execute_operation`.
  - `ste-executor` tells `ste-validator` `effect_done`.
  - `ste-validator` uses `verify_postconditions`.
Behaviour of `ste-validator`:
  - use `validate_preconditions`.
  - send `preconditions_ok` to `ste-executor`.
  - receive `effect_done` from `ste-executor`.
  - use `verify_postconditions`.
Behaviour of `ste-executor`:
  - receive `preconditions_ok` from `ste-validator`.
  - use `execute_operation`.
  - send `effect_done` to `ste-validator`.
"""

STE_GATE_PLAN_CE = STE_AUTOMATIC_PLAN_CE

AUTHORITY_DISCLOSURE: dict[str, Any] = {
    "model": "automatic-local-policy",
    "functional_roles": [ROLE_VALIDATOR, ROLE_EXECUTOR],
    "manual_approval_required": False,
    "authenticated_multi_user": False,
    "disclosure": (
        "Functional component IDs (ste-validator, ste-executor) represent automatic "
        "local policy roles, not human approvers. POSIX mode 0700/0600 is applied to "
        ".skillc control state where supported; Windows chmod does not create a private "
        "multi-user ACL. Same-user local shell or filesystem access can bypass in-process "
        "or helper policy."
    ),
}


@dataclass
class _ActiveGuardFrame:
    op: str
    state_dir: Path
    plan_digest: str
    source_closure_sha256: str
    canonical_inputs: dict[str, Any] = field(default_factory=dict)
    nested_observations: list[dict[str, Any]] = field(default_factory=list)
    nested_failures: list[str] = field(default_factory=list)


_ACTIVE_GUARD_STACK: ContextVar[tuple[_ActiveGuardFrame, ...]] = ContextVar(
    "_ACTIVE_GUARD_STACK",
    default=(),
)
_LAST_RECEIPT: ContextVar[dict[str, Any] | None] = ContextVar(
    "_LAST_RECEIPT",
    default=None,
)
_MODULE_LAST_RECEIPT: dict[str, Any] | None = None


def _set_last_receipt(receipt: dict[str, Any] | None) -> None:
    global _MODULE_LAST_RECEIPT
    copied = copy.deepcopy(receipt) if receipt is not None else None
    _LAST_RECEIPT.set(copied)
    _MODULE_LAST_RECEIPT = copy.deepcopy(copied) if copied is not None else None


def get_last_receipt() -> dict[str, Any] | None:
    """Return a copy of the most recent automatic policy receipt (or failure receipt)."""
    ctx_val = _LAST_RECEIPT.get()
    if ctx_val is not None:
        return copy.deepcopy(ctx_val)
    if _MODULE_LAST_RECEIPT is not None:
        return copy.deepcopy(_MODULE_LAST_RECEIPT)
    return None


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _utc_compact() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _is_link_or_reparse(info: os.stat_result) -> bool:
    return is_link_or_reparse(info)


def _require_nonempty_arg(value: Any, label: str, *, code: str = ERROR_INVALID_INPUT) -> str:
    return require_nonempty_str(value, label, code=code)


def _check_safe_path(
    raw: str | Path,
    label: str,
    *,
    code: str = ERROR_INVALID_INPUT,
) -> tuple[Path, Path]:
    return check_safe_lexical_path(raw, label, code=code)


def _check_not_historical_manual_stage(path: Path, label: str) -> None:
    resolved = path.resolve() if not path.is_absolute() else path
    if resolved == _HISTORICAL_MANUAL_ARTIFACT_ROOT or resolved.is_relative_to(_HISTORICAL_MANUAL_ARTIFACT_ROOT):
        raise PolicyError(
            f"{label} references immutable historical manual stage package "
            f"{_HISTORICAL_MANUAL_ARTIFACT_ROOT}; operation refused.",
            code=ERROR_POLICY_REFUSAL,
        )


def _check_not_protected_target(
    target: Path,
    label: str,
    *,
    workspace_root: Path | None = None,
    caller: str = "native",
) -> None:
    _check_not_historical_manual_stage(target, label)
    lower_parts = {part.lower() for part in target.parts}
    for seg in PROTECTED_PATH_SEGMENTS:
        if seg.lower() in lower_parts:
            raise PolicyError(
                f"{label} targets protected policy/configuration/version-control path segment {seg!r}: {target}",
                code=ERROR_POLICY_REFUSAL,
            )
    name_lower = target.name.lower()
    if (
        name_lower in {n.lower() for n in PROTECTED_FILENAMES}
        or name_lower.startswith(".env.")
        or "secret" in name_lower
        or "credential" in name_lower
    ):
        raise PolicyError(
            f"{label} targets protected configuration or credential file {target.name!r}: {target}",
            code=ERROR_POLICY_REFUSAL,
        )
    if caller == "host":
        if workspace_root is None:
            raise PolicyError(
                f"{label} for host caller requires an explicit workspace_root confinement boundary.",
                code=ERROR_POLICY_REFUSAL,
            )
        if not target.is_relative_to(workspace_root) or target == workspace_root:
            raise PolicyError(
                f"{label} escapes workspace root {workspace_root}: {target}",
                code=ERROR_POLICY_REFUSAL,
            )
        rel_parts = target.relative_to(workspace_root).parts
        if rel_parts and rel_parts[0].lower() in {d.lower() for d in PROTECTED_WORKSPACE_DIRS}:
            raise PolicyError(
                f"{label} targets protected repository directory {rel_parts[0]!r}: {target}",
                code=ERROR_POLICY_REFUSAL,
            )


def _safe_existing_file(
    raw: str | Path,
    label: str,
    *,
    code: str = ERROR_INVALID_INPUT,
) -> Path:
    absolute, resolved = _check_safe_path(raw, label, code=code)
    _check_not_historical_manual_stage(resolved, label)
    try:
        info = absolute.lstat()
    except FileNotFoundError as exc:
        raise PolicyError(f"{label} does not exist: {absolute}", code=code) from exc
    if _is_link_or_reparse(info) or not stat.S_ISREG(info.st_mode):
        raise PolicyError(f"{label} must be a regular file: {absolute}", code=code)
    if info.st_size == 0:
        raise PolicyError(f"{label} must not be empty: {absolute}", code=code)
    return resolved


def _safe_existing_dir(
    raw: str | Path,
    label: str,
    *,
    code: str = ERROR_INVALID_INPUT,
) -> Path:
    absolute, resolved = _check_safe_path(raw, label, code=code)
    _check_not_historical_manual_stage(resolved, label)
    try:
        info = absolute.lstat()
    except FileNotFoundError as exc:
        raise PolicyError(f"{label} does not exist: {absolute}", code=code) from exc
    if _is_link_or_reparse(info) or not stat.S_ISDIR(info.st_mode):
        raise PolicyError(f"{label} must be an existing directory: {absolute}", code=code)
    return resolved


def _safe_new_or_empty_dir(
    raw: str | Path,
    label: str = "Output directory",
    *,
    workspace_root: Path | None = None,
    caller: str = "native",
) -> Path:
    absolute, resolved = _check_safe_path(raw, label)
    _check_not_protected_target(resolved, label, workspace_root=workspace_root, caller=caller)
    if absolute.exists():
        info = absolute.lstat()
        if _is_link_or_reparse(info) or not stat.S_ISDIR(info.st_mode):
            raise PolicyError(f"{label} must be a directory, not a file or link.")
        if any(resolved.iterdir()):
            raise PolicyError(f"{label} must be new or empty; existing work was not changed.")
    return resolved


def _safe_export_dir_for_create(
    raw: str | Path,
    label: str = "Export destination",
    *,
    workspace_root: Path | None = None,
    caller: str = "native",
) -> Path:
    absolute, resolved = _check_safe_path(raw, label)
    _check_not_protected_target(resolved, label, workspace_root=workspace_root, caller=caller)
    if absolute.exists() or resolved.exists():
        raise PolicyError(
            f"{label} must be a new path; existing files or directories are never overwritten."
        )
    return resolved


def _check_no_overlap(
    primary_dir: Path,
    secondary_dir: Path | None,
    inputs: list[Path],
    evidence_root: Path | None = None,
) -> None:
    if secondary_dir is not None:
        if (
            primary_dir == secondary_dir
            or primary_dir.is_relative_to(secondary_dir)
            or secondary_dir.is_relative_to(primary_dir)
        ):
            raise PolicyError("Input directory and output destination must not overlap.")
    for item in inputs:
        if item == primary_dir or (secondary_dir is not None and item == secondary_dir):
            raise PolicyError(f"Output directory collides with input file: {item}")
        if item.is_relative_to(primary_dir) or (
            secondary_dir is not None and item.is_relative_to(secondary_dir)
        ):
            raise PolicyError(f"Output directory must not contain input or evidence file: {item}")
        if primary_dir == item.parent or (secondary_dir is not None and secondary_dir == item.parent):
            raise PolicyError(
                f"Output directory must not be an input parent directory: {item.parent}"
            )
    if evidence_root is not None:
        if primary_dir == evidence_root or (secondary_dir is not None and secondary_dir == evidence_root):
            raise PolicyError("Output directory must not equal the evidence root directory.")


def _validate_relative_locator(locator: Any, where: str, evidence_root: Path) -> tuple[Path, str]:
    if not isinstance(locator, str) or not locator.strip():
        raise PolicyError(f"{where}: locator must be a non-empty string", code=ERROR_INVALID_INPUT)
    parsed_url = urlsplit(locator)
    if parsed_url.scheme or "://" in locator or locator.startswith("//"):
        raise PolicyError(
            f"{where}: remote or URI locators are not allowed for local evidence: {locator!r}",
            code=ERROR_INVALID_INPUT,
        )
    if "\\" in locator:
        raise PolicyError(
            f"{where}: use forward slashes in relative locator {locator!r}",
            code=ERROR_INVALID_INPUT,
        )
    rel_path = Path(locator)
    if rel_path.is_absolute() or rel_path.drive or rel_path.root:
        raise PolicyError(
            f"{where}: locator must be relative to evidence root: {locator!r}",
            code=ERROR_INVALID_INPUT,
        )
    if not rel_path.parts or any(part in ("", ".", "..") for part in rel_path.parts):
        raise PolicyError(
            f"{where}: locator must not contain '.' or '..' segments: {locator!r}",
            code=ERROR_INVALID_INPUT,
        )
    check_sensitive_read_path(rel_path, where, code=ERROR_POLICY_REFUSAL)
    current = evidence_root
    for part in rel_path.parts:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError as exc:
            raise PolicyError(
                f"{where}: local evidence file does not exist under evidence root: {locator!r}",
                code=ERROR_INVALID_INPUT,
            ) from exc
        if _is_link_or_reparse(info):
            raise PolicyError(
                f"{where}: symbolic links and reparse points are not allowed: {locator!r}",
                code=ERROR_INVALID_INPUT,
            )
    final_info = current.lstat()
    if not stat.S_ISREG(final_info.st_mode) or final_info.st_size == 0:
        raise PolicyError(
            f"{where}: local evidence must be a non-empty regular file: {locator!r}",
            code=ERROR_INVALID_INPUT,
        )
    resolved = current.resolve(strict=True)
    if not resolved.is_relative_to(evidence_root):
        raise PolicyError(f"{where}: locator escapes evidence root: {locator!r}", code=ERROR_INVALID_INPUT)
    check_sensitive_read_path(resolved, where, code=ERROR_POLICY_REFUSAL)
    return resolved, resolved.relative_to(evidence_root).as_posix()


def _default_evidence_root_for_source(source: Path, explicit_root: Path | None = None) -> Path:
    if explicit_root is not None:
        return explicit_root
    if _SUITE_EXAMPLES_DIR.is_dir() and source.is_relative_to(_SUITE_EXAMPLES_DIR):
        return _REPO_ROOT
    return source.parent


def _is_builtin_quickstart_source(source: Path) -> bool:
    quickstart_data = (Path(__file__).resolve().parent / "data" / "quickstart.json").resolve()
    return source == quickstart_data


def _validate_confined_bundle_filepath(
    raw_path: Any,
    bundle_dir: Path,
    label: str,
    *,
    code: str = ERROR_POSTCONDITION_FAILURE,
) -> Path:
    abs_entry, resolved_entry = _check_safe_path(raw_path, label, code=code)
    if abs_entry.parent != bundle_dir or resolved_entry.parent != bundle_dir or not resolved_entry.is_relative_to(bundle_dir):
        raise PolicyError(
            f"{label} points outside bundle directory {bundle_dir}: {raw_path}",
            code=code,
        )
    return resolved_entry


def _validate_confined_media_audio_relpath(
    raw_rel: Any,
    output_dir: Path,
    *,
    code: str = ERROR_POSTCONDITION_FAILURE,
) -> Path:
    if not isinstance(raw_rel, str) or not raw_rel.strip():
        raise PolicyError("Media audio file entry must be a non-empty relative path.", code=code)
    if "\\" in raw_rel or ":" in raw_rel or "\x00" in raw_rel:
        raise PolicyError(f"Media audio file entry must use clean POSIX relative syntax: {raw_rel!r}", code=code)
    rel = Path(raw_rel)
    if rel.is_absolute() or rel.drive or rel.root:
        raise PolicyError(f"Media audio file entry must not be an absolute path: {raw_rel!r}", code=code)
    if len(rel.parts) != 2 or rel.parts[0] != "video" or any(p in ("", ".", "..") for p in rel.parts):
        raise PolicyError(
            f"Media audio file entry must reside directly under video/: {raw_rel!r}",
            code=code,
        )
    filename = rel.parts[1]
    if not filename.endswith(".wav"):
        raise PolicyError(f"Media audio file entry must be a .wav file under video/: {raw_rel!r}", code=code)
    candidate = output_dir / rel
    abs_wav, resolved_wav = _check_safe_path(candidate, f"Media audio {raw_rel}", code=code)
    video_dir = (output_dir / "video").resolve()
    if abs_wav.parent != video_dir or resolved_wav.parent != video_dir or not resolved_wav.is_relative_to(output_dir):
        raise PolicyError(
            f"Media audio file entry escapes video/ directory: {raw_rel!r}",
            code=code,
        )
    return resolved_wav


def _validate_pcm_wav(data: bytes) -> dict[str, Any]:
    """Pure stdlib RIFF/WAVE non-silent PCM validator matching media._pcm_info."""
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise PolicyError("Expected a RIFF/WAVE PCM file.", code=ERROR_POSTCONDITION_FAILURE)
    if struct.unpack_from("<I", data, 4)[0] != len(data) - 8:
        raise PolicyError(
            "Truncated or inconsistent RIFF/WAVE length.",
            code=ERROR_POSTCONDITION_FAILURE,
        )
    offset = 12
    fmt: tuple[int, ...] | None = None
    frames: bytes | None = None
    while offset < len(data):
        if offset + 8 > len(data):
            raise PolicyError("Truncated WAV chunk header.", code=ERROR_POSTCONDITION_FAILURE)
        kind, size = struct.unpack_from("<4sI", data, offset)
        start, end = offset + 8, offset + 8 + size
        if end + size % 2 > len(data):
            raise PolicyError("Truncated WAV chunk.", code=ERROR_POSTCONDITION_FAILURE)
        if kind == b"fmt ":
            if fmt is not None or size < 16:
                raise PolicyError("Invalid or duplicate PCM format.", code=ERROR_POSTCONDITION_FAILURE)
            fmt = struct.unpack_from("<HHIIHH", data, start)
        elif kind == b"data":
            if frames is not None or fmt is None:
                raise PolicyError(
                    "Expected one PCM data chunk after its format.",
                    code=ERROR_POSTCONDITION_FAILURE,
                )
            frames = data[start:end]
        offset = end + size % 2
    if fmt is None or frames is None:
        raise PolicyError("Missing PCM format or data.", code=ERROR_POSTCONDITION_FAILURE)
    tag, channels, rate, byte_rate, block, bits = fmt
    if (
        tag != 1
        or channels not in (1, 2)
        or bits not in (8, 16, 24, 32)
        or not 8000 <= rate <= 192000
        or block != channels * bits // 8
        or byte_rate != rate * block
    ):
        raise PolicyError(
            "Use integer PCM, mono/stereo, 8–32 bits, 8000–192000 Hz.",
            code=ERROR_POSTCONDITION_FAILURE,
        )
    if len(frames) < 2 * block or len(frames) % block:
        raise PolicyError(
            "Empty, truncated or misaligned PCM frames.",
            code=ERROR_POSTCONDITION_FAILURE,
        )
    if not any(frames[i:i + block] != frames[:block] for i in range(block, len(frames), block)):
        raise PolicyError("Silent or constant PCM audio.", code=ERROR_POSTCONDITION_FAILURE)
    duration = len(frames) / byte_rate
    if duration < 0.001:
        raise PolicyError(
            "Audio is shorter than the one-millisecond caption resolution.",
            code=ERROR_POSTCONDITION_FAILURE,
        )
    if duration > 600:
        raise PolicyError(
            "Audio exceeds the 600-second per-beat limit.",
            code=ERROR_POSTCONDITION_FAILURE,
        )
    return {
        "duration": duration,
        "frames": len(frames) // block,
        "sample_rate": rate,
        "channels": channels,
        "sample_width": bits // 8,
        "non_silent_pcm": True,
    }


def _has_inprocess_skillc() -> bool:
    return has_inprocess_skillc()


def _resolve_worker_backend() -> tuple[Path, Path]:
    return resolve_worker_backend()


def _restrict_control_dir(control_dir: Path) -> None:
    control_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix":
        os.chmod(control_dir, 0o700)


def _worker_command(python_exe: Path) -> list[str]:
    return [str(python_exe), "-B", "-m", "ste_promax._skillc_worker"]


def _worker_environment(skillc_src: Path) -> dict[str, str]:
    ste_root = Path(__file__).resolve().parents[1]
    env: dict[str, str] = {}
    for key in _SAFE_ENV_KEYS:
        val = os.environ.get(key)
        if val:
            env[key] = val
    env["PYTHONPATH"] = os.pathsep.join([str(ste_root), str(skillc_src)])
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUTF8"] = "1"
    return env


def _invoke_skillc_action(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    if action not in {"guard_pre", "guard_post", "guard_fail", "guard_status"}:
        raise PolicyError(
            f"Unsupported SkillC policy action: {action!r}",
            code=ERROR_UNSUPPORTED_OPERATION,
        )
    if _has_inprocess_skillc():
        return _dispatch_inprocess_action(action, payload)
    python_exe, skillc_src = _resolve_worker_backend()
    request = {"action": action, "payload": payload}
    proc = subprocess.run(
        _worker_command(python_exe),
        input=json.dumps(request, ensure_ascii=False),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_worker_environment(skillc_src),
        cwd=str(Path(__file__).resolve().parents[1]),
        shell=False,
        check=False,
        timeout=_WORKER_TIMEOUT_SECONDS,
    )
    if proc.returncode != 0:
        err_text = (proc.stderr or proc.stdout or "").strip()
        try:
            parsed_err = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else None
        except ValueError:
            parsed_err = None
        if isinstance(parsed_err, dict) and parsed_err.get("error"):
            err_obj = parsed_err["error"]
            if isinstance(err_obj, dict):
                code = str(err_obj.get("code") or ERROR_POLICY_REFUSAL)
                msg = str(err_obj.get("message") or "SkillC worker failed.")
                if code == ERROR_DEPENDENCY_MISSING:
                    raise PolicyBackendError(msg)
                raise PolicyError(msg, code=code)
            raise PolicyError(str(err_obj), code=ERROR_POLICY_REFUSAL)
        raise PolicyBackendError(
            err_text or f"SkillC worker exited with status {proc.returncode}."
        )
    try:
        response = json.loads(proc.stdout)
    except ValueError as exc:
        raise PolicyBackendError("SkillC worker returned malformed JSON output.") from exc
    if not isinstance(response, dict) or response.get("ok") is not True:
        err_obj = (response if isinstance(response, dict) else {}).get("error")
        if isinstance(err_obj, dict):
            code = str(err_obj.get("code") or ERROR_POLICY_REFUSAL)
            msg = str(err_obj.get("message") or "SkillC worker failed.")
            if code == ERROR_DEPENDENCY_MISSING:
                raise PolicyBackendError(msg)
            raise PolicyError(msg, code=code)
        raise PolicyError(str(err_obj or "SkillC worker failed."), code=ERROR_POLICY_REFUSAL)
    result = response.get("result")
    if not isinstance(result, dict):
        raise PolicyBackendError("SkillC worker returned an invalid result payload.")
    return result


def _check_static_plan_inprocess(plan_text: str | None = None) -> dict[str, Any]:
    from skillc.checker import check
    from skillc.frontend.ce import parse_ce_detailed
    from skillc.frontend.runtime import Runtime, bind_runtime
    from skillc.frontend.toolpolicy import load_library

    active_plan = STE_GATE_PLAN_CE if plan_text is None else plan_text
    try:
        parsed = parse_ce_detailed(active_plan)
        pure = check(parsed.pack)
        runtime = Runtime.from_dict(STE_AUTOMATIC_RUNTIME_MANIFEST)
        bound = bind_runtime(
            parsed.pack,
            parsed.bindings,
            runtime,
            prune=True,
            library=load_library(),
            software=True,
        )
        verdict = check(bound.pack)
    except Exception as exc:
        raise PolicyError(f"SkillC static plan check failed: {exc}", code=ERROR_POLICY_REFUSAL) from exc

    if (
        not pure.admissible
        or not verdict.admissible
        or verdict.label != "ACHIEVABLE"
        or verdict.protocol != "WELL_TYPED"
        or bound.withdrawn
        or bound.blocked
    ):
        raise PolicyError(
            f"SkillC static gate rejected workflow plan: label={verdict.label}, "
            f"reason={verdict.reason}, protocol={verdict.protocol} ({verdict.protocol_reason}).",
            code=ERROR_POLICY_REFUSAL,
        )
    return {
        "plan_name": parsed.pack["name"],
        "runtime": runtime.name,
        "pure_verdict": pure.label,
        "bound_verdict": verdict.label,
        "protocol": verdict.protocol,
        "admissible": verdict.admissible,
        "pack_digest": verdict.pack_digest,
        "assumed_conformant": list(verdict.assumed_conformant),
    }


def _open_monitor_inprocess(root: Path, plan_text: str | None = None):
    from skillc.frontend.runtime import Runtime
    from skillc.monitor import ALLOW, Config, Monitor

    active_plan = STE_GATE_PLAN_CE if plan_text is None else plan_text
    runtime = Runtime.from_dict(STE_AUTOMATIC_RUNTIME_MANIFEST)
    cfg = Config(
        runtime=runtime.name,
        plan_file=f"{SKILLC_DIRNAME}/{PLAN_FILE}",
        state_file=f"{SKILLC_DIRNAME}/{STATE_FILE}",
        thinking="off",
        require_plan=True,
        plan_conformance=True,
        free_tools=(),
        strict=True,
    )
    monitor = Monitor(cfg, root=root, runtime=runtime)
    plan_path = root / SKILLC_DIRNAME / PLAN_FILE
    _restrict_control_dir(plan_path.parent)
    if plan_path.exists():
        existing_plan = plan_path.read_text(encoding="utf-8")
        if existing_plan != active_plan:
            raise PolicyError(
                "Persisted SkillC plan text does not match the automatic policy plan.",
                code=ERROR_POLICY_REFUSAL,
            )
    else:
        plan_path.write_text(active_plan, encoding="utf-8", newline="\n")
    decision = monitor.load_plan(active_plan)
    if decision.action != ALLOW:
        monitor.save()
        raise PolicyError(f"SkillC monitor refused plan: {decision.reason}", code=ERROR_POLICY_REFUSAL)
    return monitor


def _run_monitored_pre_inprocess(monitor, tool: str, step_meta: dict[str, str], role: str) -> None:
    from skillc.monitor import ALLOW

    decision = monitor.pre_action(tool, step_meta, role=role)
    if decision.action != ALLOW:
        monitor.save()
        raise PolicyError(
            f"SkillC monitor denied {tool} for role {role}: {decision.reason}",
            code=ERROR_POLICY_REFUSAL,
        )


def _run_monitored_post_inprocess(
    monitor,
    tool: str,
    step_meta: dict[str, str],
    result: dict[str, Any],
    role: str,
    *,
    expected_fact: str | None = None,
) -> None:
    from skillc.monitor import ALLOW

    decision = monitor.post_action(tool, step_meta, result, role=role)
    monitor.save()
    if decision.action != ALLOW:
        raise PolicyError(
            f"SkillC monitor post_action denied {tool}: {decision.reason}",
            code=ERROR_POLICY_REFUSAL,
        )
    if expected_fact is not None and expected_fact not in monitor.state.facts:
        raise PolicyError(
            f"SkillC monitor did not establish required postcondition fact {expected_fact!r}.",
            code=ERROR_POSTCONDITION_FAILURE,
        )


def _check_no_forbidden_keys(obj: Any, where: str = "inputs") -> None:
    if isinstance(obj, dict):
        for key, val in obj.items():
            if not isinstance(key, str):
                raise PolicyError(f"{where} keys must be strings.", code=ERROR_INVALID_INPUT)
            if key in FORBIDDEN_INPUT_KEYS:
                raise PolicyError(
                    f"Forbidden policy/execution control field {key!r} in {where}.",
                    code=ERROR_POLICY_REFUSAL,
                )
            _check_no_forbidden_keys(val, f"{where}.{key}")
    elif isinstance(obj, (list, tuple)):
        for idx, item in enumerate(obj):
            _check_no_forbidden_keys(item, f"{where}[{idx}]")


def _serialize_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    """Convert Path values to strings for JSON transport while preserving booleans/types."""
    def convert(val: Any) -> Any:
        if isinstance(val, Path):
            return str(val)
        if isinstance(val, dict):
            return {str(k): convert(v) for k, v in val.items()}
        if isinstance(val, (list, tuple)):
            return [convert(v) for v in val]
        return val

    if not isinstance(inputs, dict):
        raise PolicyError("Operation inputs must be a dict.", code=ERROR_INVALID_INPUT)
    return convert(inputs)


def _reject_if_legacy_manual_stage(directory: Path, label: str = "Bundle directory") -> None:
    _check_not_historical_manual_stage(directory, label)
    legacy_markers = (
        directory / SKILLC_DIRNAME / STAGE_RECORD_FILE,
        directory / STAGE_RECORD_FILE,
        directory / SKILLC_DIRNAME / APPROVAL_DB_FILE,
        directory / SKILLC_DIRNAME / APPROVAL_SECRET_FILE,
        directory / BUNDLE_DIRNAME / "manifest.json",
        directory.parent / SKILLC_DIRNAME / STAGE_RECORD_FILE,
    )
    for marker in legacy_markers:
        try:
            if marker.exists() or marker.is_symlink():
                raise PolicyError(
                    f"{label} contains legacy manual stage/approval state ({marker.name}); "
                    "legacy manual stage records cannot be migrated or automatically exported.",
                    code=ERROR_POLICY_REFUSAL,
                )
        except OSError:
            continue


def _collect_native_bundle_files(bundle_dir: Path) -> dict[str, Path]:
    info = bundle_dir.lstat()
    if _is_link_or_reparse(info) or not stat.S_ISDIR(info.st_mode):
        raise PolicyError(f"Bundle directory is unsafe or not a directory: {bundle_dir}", code=ERROR_INVALID_INPUT)
    _reject_if_legacy_manual_stage(bundle_dir, "Input bundle directory")

    files: dict[str, Path] = {}

    def walk(current: Path) -> None:
        cur_info = current.lstat()
        if _is_link_or_reparse(cur_info):
            raise PolicyError(
                f"Symbolic link or reparse point is not allowed in bundle directory: {current}",
                code=ERROR_INVALID_INPUT,
            )
        for child in sorted(current.iterdir()):
            child_info = child.lstat()
            if _is_link_or_reparse(child_info):
                raise PolicyError(
                    f"Symbolic link or reparse point is not allowed in bundle directory: {child}",
                    code=ERROR_INVALID_INPUT,
                )
            if child.name == SKILLC_DIRNAME:
                raise PolicyError(
                    f"Legacy control directory {SKILLC_DIRNAME!r} is not allowed in export input bundle: {child}",
                    code=ERROR_POLICY_REFUSAL,
                )
            if stat.S_ISDIR(child_info.st_mode):
                walk(child)
            elif stat.S_ISREG(child_info.st_mode):
                if child_info.st_size == 0:
                    raise PolicyError(
                        f"Bundle payload file must not be empty: {child}",
                        code=ERROR_INVALID_INPUT,
                    )
                rel = child.relative_to(bundle_dir).as_posix()
                files[rel] = child
            else:
                raise PolicyError(
                    f"Unsupported non-regular file in bundle directory: {child}",
                    code=ERROR_INVALID_INPUT,
                )

    walk(bundle_dir)
    return files


def _check_origin_confinement(
    origin: Path,
    label: str,
    *,
    workspace_root: Path | None,
    caller: str,
    is_directory: bool = False,
) -> None:
    _check_not_historical_manual_stage(origin, label)
    if not (is_directory or origin.is_dir()):
        check_sensitive_read_path(origin, label, code=ERROR_POLICY_REFUSAL)
    else:
        for secret_seg in (".ssh", ".gnupg", ".aws", ".azure", ".kube", ".copilot", ".opencode", ".claude", ".skillc", ".git"):
            if secret_seg in {p.lower() for p in origin.parts}:
                raise PolicyError(
                    f"{label} references protected credential/config/control directory {secret_seg!r}.",
                    code=ERROR_POLICY_REFUSAL,
                )
    if caller == "host" and workspace_root is not None:
        if not origin.is_relative_to(workspace_root) and not origin.is_relative_to(_REPO_ROOT):
            raise PolicyError(
                f"{label} escapes workspace_root {workspace_root}: {origin}",
                code=ERROR_POLICY_REFUSAL,
            )


def _validate_native_bundle_for_export(
    bundle_dir: Path,
    *,
    explicit_evidence_root: Path | None = None,
    explicit_evidence_files: list[str] | None = None,
    workspace_root: Path | None = None,
    caller: str = "native",
) -> tuple[dict[str, Any], dict[str, bytes], dict[str, dict[str, Any]], list[dict[str, Any]], str]:
    collected = _collect_native_bundle_files(bundle_dir)
    if "manifest.json" not in collected:
        raise PolicyError("Input bundle is missing manifest.json.", code=ERROR_INVALID_INPUT)

    snapshots: dict[str, bytes] = {}
    payload_records: dict[str, dict[str, Any]] = {}
    for rel, path in sorted(collected.items()):
        raw = path.read_bytes()
        if not raw:
            raise PolicyError(f"Bundle file is empty: {rel}", code=ERROR_INVALID_INPUT)
        snapshots[rel] = raw
        payload_records[rel] = {"sha256": _sha256_bytes(raw), "size": len(raw)}

    try:
        manifest_text = snapshots["manifest.json"].decode("utf-8")
        manifest = loads_json(manifest_text)
    except Exception as exc:
        raise PolicyError(f"Invalid manifest.json in bundle directory: {exc}", code=ERROR_INVALID_INPUT) from exc
    if not isinstance(manifest, dict):
        raise PolicyError("manifest.json must be a JSON object.", code=ERROR_INVALID_INPUT)
    if manifest.get("schema") == "ste-promax.stage-record.v1" or "fingerprint" in manifest:
        raise PolicyError(
            "Legacy manual stage record cannot be exported as a native bundle.",
            code=ERROR_POLICY_REFUSAL,
        )
    if manifest.get("status") != "complete":
        raise PolicyError("Native render manifest status is not 'complete'.", code=ERROR_INVALID_INPUT)
    if manifest.get("renderer") != "ste_promax.render":
        raise PolicyError("Manifest renderer must be 'ste_promax.render'.", code=ERROR_INVALID_INPUT)
    if type(manifest.get("trusted_html")) is not bool:
        raise PolicyError("Manifest trusted_html flag must be a boolean.", code=ERROR_INVALID_INPUT)
    trusted_html = manifest["trusted_html"]
    if manifest.get("lint_passed") is not True:
        raise PolicyError("Manifest lint_passed must be boolean True for export.", code=ERROR_INVALID_INPUT)
    if manifest.get("offline_verified") is not False:
        raise PolicyError("Manifest must not claim offline_verified certification.", code=ERROR_INVALID_INPUT)

    manifest_files = manifest.get("files")
    if not isinstance(manifest_files, dict):
        raise PolicyError("Manifest files table is missing or invalid.", code=ERROR_INVALID_INPUT)
    required_keys = {"source", "input", "html", "design", "meta", "gallery"}
    if not required_keys <= set(manifest_files):
        missing = sorted(required_keys - set(manifest_files))
        raise PolicyError(
            f"Manifest is missing required artifact entries: {', '.join(missing)}",
            code=ERROR_INVALID_INPUT,
        )

    expected_bundle_rels: set[str] = {"manifest.json"}
    for key, entry in manifest_files.items():
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("path"), str)
            or not isinstance(entry.get("sha256"), str)
        ):
            raise PolicyError(f"Manifest file entry {key!r} is malformed.", code=ERROR_INVALID_INPUT)
        entry_resolved = _validate_confined_bundle_filepath(
            entry["path"],
            bundle_dir,
            f"Manifest file entry {key!r}",
            code=ERROR_INVALID_INPUT,
        )
        rel_name = entry_resolved.name
        if rel_name not in snapshots:
            raise PolicyError(
                f"Manifest file {rel_name!r} is missing from bundle directory.",
                code=ERROR_INVALID_INPUT,
            )
        actual_sha = payload_records[rel_name]["sha256"]
        if actual_sha != entry["sha256"]:
            raise PolicyError(
                f"Bundle artifact hash mismatch for {rel_name}: expected {entry['sha256']}, got {actual_sha}.",
                code=ERROR_POSTCONDITION_FAILURE,
            )
        try:
            snapshots[rel_name].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PolicyError(f"Bundle artifact is not valid UTF-8: {rel_name}", code=ERROR_INVALID_INPUT) from exc
        expected_bundle_rels.add(rel_name)

    meta_rel = Path(manifest_files["meta"]["path"]).name
    try:
        meta_lint = cli.lint_status(snapshots[meta_rel].decode("utf-8"))
    except ModuleNotFoundError as exc:
        raise PolicyBackendError("Bundle metadata verification requires PyYAML.") from exc
    if meta_lint is not True:
        raise PolicyError(
            "Bundle metadata sidecar does not have unambiguous YAML lint_passed: true.",
            code=ERROR_INVALID_INPUT,
        )

    raw_source_path = manifest.get("source_path")
    if not isinstance(raw_source_path, str) or not raw_source_path.strip():
        raise PolicyError("Manifest source_path is missing or invalid.", code=ERROR_INVALID_INPUT)
    _, candidate_source = _check_safe_path(raw_source_path, "Original source file")
    _check_origin_confinement(
        candidate_source,
        "Original source file",
        workspace_root=workspace_root,
        caller=caller,
    )
    resolved_source = _safe_existing_file(raw_source_path, "Original source file")

    saved_input_data = loads_json(snapshots["input.json"].decode("utf-8"))
    if not isinstance(saved_input_data, dict):
        raise PolicyError("Retained input.json must be a JSON object.", code=ERROR_INVALID_INPUT)
    title_in_input = saved_input_data.get("title")
    title_arg = title_in_input if isinstance(title_in_input, str) else None

    original_bytes, normalized_bytes, parsed_data = cli.normalized_input(
        resolved_source,
        title_arg,
        trusted_html,
    )
    validate_input(parsed_data)
    source_sha256 = _sha256_bytes(original_bytes)
    if source_sha256 != manifest.get("source_sha256"):
        raise PolicyError(
            "Original source file changed after rendering; re-render before exporting.",
            code=ERROR_POSTCONDITION_FAILURE,
        )
    saved_source_rel = Path(manifest_files["source"]["path"]).name
    if snapshots[saved_source_rel] != original_bytes:
        raise PolicyError(
            "Retained source copy in bundle does not match original source bytes.",
            code=ERROR_POSTCONDITION_FAILURE,
        )
    if snapshots["input.json"] != normalized_bytes:
        raise PolicyError(
            "Retained input.json in bundle does not match normalized source input.",
            code=ERROR_POSTCONDITION_FAILURE,
        )

    expected_visuals = list(cli.visual_inputs(parsed_data))
    if len(manifest.get("visuals", [])) != len(expected_visuals):
        raise PolicyError(
            "Bundle visual count does not match structured input.",
            code=ERROR_INVALID_INPUT,
        )
    for index, _ in enumerate(expected_visuals, 1):
        stem = f"visual-{index:02}"
        if stem not in manifest_files:
            raise PolicyError(f"Manifest is missing visual entry {stem!r}.", code=ERROR_INVALID_INPUT)

    required_story_locators: list[tuple[int, str, str | None]] = []
    if parsed_data.get("kind") == "story":
        for companion_stem in ("story", "storyboard", "narration", "evidence"):
            if companion_stem not in manifest_files:
                raise PolicyError(
                    f"Story manifest is missing companion {companion_stem!r}.",
                    code=ERROR_INVALID_INPUT,
                )
        evidence_ledger = loads_json(snapshots["evidence.json"].decode("utf-8"))
        review_block = evidence_ledger.get("review") if isinstance(evidence_ledger, dict) else None
        if (
            not isinstance(review_block, dict)
            or review_block.get("source_verification") != "not_performed"
            or review_block.get("semantic_review") != "required"
        ):
            raise PolicyError(
                "Story evidence.json lost required review disclaimers.",
                code=ERROR_POSTCONDITION_FAILURE,
            )
        narration_ledger = loads_json(snapshots["narration.json"].decode("utf-8"))
        if not isinstance(narration_ledger, dict) or narration_ledger.get("review_required") is not True:
            raise PolicyError(
                "Story narration.json lost review_required flag.",
                code=ERROR_POSTCONDITION_FAILURE,
            )
        if not _is_builtin_quickstart_source(resolved_source):
            for idx, src_item in enumerate(parsed_data.get("sources", [])):
                if isinstance(src_item, dict) and "locator" in src_item:
                    required_story_locators.append((idx, str(src_item["locator"]), src_item.get("id")))

    design_sha256: str | None = None
    if "input_design" in manifest_files:
        design_sha256 = payload_records["input-design.md"]["sha256"]

    # Validate render-time evidence bindings & snapshots (never bless newly discovered files at export time).
    bundle_evidence_rels = {k for k in snapshots if k.startswith("evidence/")}
    explicit_ev_resolved = [
        _safe_existing_file(raw_ev, f"--evidence[{i}]")
        for i, raw_ev in enumerate(explicit_evidence_files or [])
    ]
    recorded_ev_raw = manifest.get("evidence_files")
    manifest_ev_root_raw = manifest.get("evidence_root")

    has_required_evidence = bool(
        required_story_locators or explicit_ev_resolved or bundle_evidence_rels or recorded_ev_raw
    )
    verified_ev_records: list[dict[str, Any]] = []
    resolved_ev_root: Path | None = None

    if has_required_evidence:
        if not isinstance(recorded_ev_raw, list) or not isinstance(manifest_ev_root_raw, str) or not manifest_ev_root_raw.strip():
            raise PolicyError(
                "Bundle is missing render-time evidence bindings (evidence_root / evidence_files) in manifest.json; "
                "re-render the bundle so evidence snapshots are captured at render time.",
                code=ERROR_INVALID_INPUT,
            )
        _, candidate_ev_root = _check_safe_path(manifest_ev_root_raw, "Manifest evidence_root")
        _check_origin_confinement(
            candidate_ev_root,
            "Manifest evidence_root",
            workspace_root=workspace_root,
            caller=caller,
        )
        resolved_ev_root = _safe_existing_dir(manifest_ev_root_raw, "Manifest evidence_root")
        if explicit_evidence_root is not None and explicit_evidence_root != resolved_ev_root:
            raise PolicyError(
                f"Export evidence_root {explicit_evidence_root} does not match render-time "
                f"manifest evidence_root {resolved_ev_root}.",
                code=ERROR_INVALID_INPUT,
            )

        by_source_path: dict[Path, dict[str, Any]] = {}
        by_locator: dict[str, dict[str, Any]] = {}
        for idx, rec in enumerate(recorded_ev_raw):
            where = f"manifest.evidence_files[{idx}]"
            if not isinstance(rec, dict):
                raise PolicyError(f"{where} must be an object.", code=ERROR_INVALID_INPUT)
            rel_key = rec.get("rel_path")
            src_str = rec.get("source_path")
            rec_sha = rec.get("sha256")
            rec_size = rec.get("size")
            if (
                not isinstance(rel_key, str)
                or not rel_key.startswith("evidence/")
                or len(Path(rel_key).parts) != 2
                or any(p in ("", ".", "..") for p in Path(rel_key).parts)
            ):
                raise PolicyError(f"{where}.rel_path is invalid: {rel_key!r}", code=ERROR_INVALID_INPUT)
            if not isinstance(src_str, str) or not src_str.strip():
                raise PolicyError(f"{where}.source_path is invalid.", code=ERROR_INVALID_INPUT)
            if not isinstance(rec_sha, str) or not _HEX64.fullmatch(rec_sha) or type(rec_size) is not int or rec_size <= 0:
                raise PolicyError(f"{where} has invalid sha256 or size.", code=ERROR_INVALID_INPUT)

            if "path" in rec and rec["path"] is not None:
                snap_abs, snap_res = _check_safe_path(rec["path"], f"{where}.path")
                expected_snap = (bundle_dir / Path(rel_key)).resolve()
                if snap_abs != expected_snap and snap_res != expected_snap:
                    raise PolicyError(
                        f"{where}.path points outside bundle evidence snapshot {expected_snap}: {rec['path']}",
                        code=ERROR_INVALID_INPUT,
                    )

            if rel_key not in snapshots:
                raise PolicyError(
                    f"Render-time evidence snapshot {rel_key!r} is missing from bundle directory.",
                    code=ERROR_INVALID_INPUT,
                )
            if payload_records[rel_key]["sha256"] != rec_sha or payload_records[rel_key]["size"] != rec_size:
                raise PolicyError(
                    f"Captured bundle evidence snapshot {rel_key!r} does not match manifest hash/size.",
                    code=ERROR_POSTCONDITION_FAILURE,
                )

            _, cand_src = _check_safe_path(src_str, f"{where}.source_path")
            _check_origin_confinement(cand_src, f"{where}.source_path", workspace_root=workspace_root, caller=caller)
            orig_ev_file = _safe_existing_file(src_str, f"{where}.source_path", code=ERROR_POSTCONDITION_FAILURE)
            orig_ev_bytes = orig_ev_file.read_bytes()
            if _sha256_bytes(orig_ev_bytes) != rec_sha or len(orig_ev_bytes) != rec_size:
                raise PolicyError(
                    f"Original evidence file changed after rendering ({rel_key}): {orig_ev_file}",
                    code=ERROR_POSTCONDITION_FAILURE,
                )

            loc_val = rec.get("locator")
            if loc_val is not None:
                res_loc, norm_loc = _validate_relative_locator(loc_val, f"{where}.locator", resolved_ev_root)
                if res_loc != orig_ev_file:
                    raise PolicyError(
                        f"{where}.locator resolves to {res_loc}, which does not match recorded source_path {orig_ev_file}.",
                        code=ERROR_INVALID_INPUT,
                    )
                by_locator[norm_loc] = rec

            by_source_path[orig_ev_file] = rec
            expected_bundle_rels.add(rel_key)
            verified_ev_records.append({
                "rel_path": rel_key,
                "source_path": str(orig_ev_file),
                "sha256": rec_sha,
                "size": rec_size,
                "source_ids": list(rec.get("source_ids", [])) if isinstance(rec.get("source_ids"), list) else [],
                "explicit": bool(rec.get("explicit", False)),
            })

        # Verify no required story locator was omitted at render time
        for idx, raw_loc, _ in required_story_locators:
            res_loc, norm_loc = _validate_relative_locator(
                raw_loc,
                f"story.sources[{idx}]",
                resolved_ev_root,
            )
            if res_loc not in by_source_path and norm_loc not in by_locator:
                raise PolicyError(
                    f"Story source locator {raw_loc!r} was not bound in render-time manifest evidence_files.",
                    code=ERROR_INVALID_INPUT,
                )

        # Verify any explicit --evidence passed at export time was already bound at render time
        for exp_ev in explicit_ev_resolved:
            if exp_ev not in by_source_path:
                raise PolicyError(
                    f"Explicit evidence file {exp_ev} was not bound in render-time manifest evidence_files; "
                    "export never silently binds new evidence.",
                    code=ERROR_INVALID_INPUT,
                )
    else:
        resolved_ev_root = _default_evidence_root_for_source(resolved_source, explicit_evidence_root)

    if set(snapshots.keys()) != expected_bundle_rels:
        extra = sorted(set(snapshots.keys()) - expected_bundle_rels)
        missing = sorted(expected_bundle_rels - set(snapshots.keys()))
        raise PolicyError(
            f"Bundle payload file set mismatch (extra={extra}, missing={missing}).",
            code=ERROR_INVALID_INPUT,
        )

    closure = {
        "source_path": str(resolved_source),
        "source_sha256": source_sha256,
        "normalized_input_sha256": _sha256_bytes(normalized_bytes),
        "title": title_arg,
        "design_sha256": design_sha256,
        "trusted_html": trusted_html,
        "evidence_root": str(resolved_ev_root),
        "evidence_files": verified_ev_records,
        "payload_files": payload_records,
    }
    source_closure_digest = _sha256_text(_canonical_json(closure))
    return manifest, snapshots, payload_records, verified_ev_records, source_closure_digest


def _validate_and_snapshot_inputs(op: str, raw_inputs: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(op, str) or op not in SUPPORTED_OPERATIONS:
        raise PolicyError(f"Unsupported guarded operation: {op!r}", code=ERROR_UNSUPPORTED_OPERATION)
    if not isinstance(raw_inputs, dict):
        raise PolicyError("Operation inputs must be a JSON object.", code=ERROR_INVALID_INPUT)

    _check_no_forbidden_keys(raw_inputs, "inputs")
    unknown_keys = set(raw_inputs.keys()) - ALLOWED_INPUT_KEYS
    if unknown_keys:
        raise PolicyError(
            f"Unsupported input fields for {op}: {', '.join(sorted(unknown_keys))}",
            code=ERROR_INVALID_INPUT,
        )

    inputs = _serialize_inputs(raw_inputs)
    try:
        _canonical_json(inputs)
    except (TypeError, ValueError) as exc:
        raise PolicyError(f"Operation inputs must be JSON-serializable: {exc}", code=ERROR_INVALID_INPUT) from exc

    caller_kind = inputs.get("caller_kind", inputs.get("caller", "native"))
    if caller_kind not in {"native", "host"}:
        raise PolicyError(
            f"caller_kind must be 'native' or 'host', got {caller_kind!r}.",
            code=ERROR_INVALID_INPUT,
        )

    source_kind = inputs.get("source_kind", inputs.get("input_kind"))
    if source_kind is not None and (not isinstance(source_kind, str) or not source_kind.strip()):
        raise PolicyError("source_kind must be a non-empty string.", code=ERROR_INVALID_INPUT)

    trusted_html = inputs.get("trusted_html", False)
    if type(trusted_html) is not bool:
        raise PolicyError("trusted_html must be a boolean.", code=ERROR_INVALID_INPUT)

    has_raw_html = inputs.get("has_raw_html", False)
    if type(has_raw_html) is not bool:
        raise PolicyError("has_raw_html must be a boolean.", code=ERROR_INVALID_INPUT)

    # Distinguish imported raw_html from generated host_content:
    # interactive generated HTML (source_kind == "host_content") is not an untrusted HTML import.
    if (source_kind == "raw_html" or (has_raw_html and source_kind != "host_content")) and not trusted_html:
        raise PolicyError(
            "Raw HTML requires explicit --trusted-html consent; review the authored content first.",
            code=ERROR_POLICY_REFUSAL,
        )

    # Availability facts check
    for bool_flag in ("dependencies_ready", "render_dependencies_ready", "speech_available", "speaker_injected"):
        if bool_flag in inputs and inputs[bool_flag] is not None and type(inputs[bool_flag]) is not bool:
            raise PolicyError(f"{bool_flag} must be a boolean.", code=ERROR_INVALID_INPUT)
    availability = inputs.get("availability")
    if availability is not None:
        if not isinstance(availability, dict) or not all(
            isinstance(k, str) and type(v) is bool for k, v in availability.items()
        ):
            raise PolicyError("availability must map string keys to booleans.", code=ERROR_INVALID_INPUT)
        missing_avail = [k for k, v in sorted(availability.items()) if not v]
        if missing_avail:
            raise PolicyError(
                f"Required dependencies/capabilities unavailable: {', '.join(missing_avail)}",
                code=ERROR_DEPENDENCY_MISSING,
            )
    if inputs.get("dependencies_ready") is False or inputs.get("render_dependencies_ready") is False:
        raise PolicyError(
            "Rendering requires the Python dependencies Jinja2 and PyYAML. "
            "Plugin installation does not install them automatically; use an approved "
            "Python environment with these dependencies. Nothing was installed.",
            code=ERROR_DEPENDENCY_MISSING,
        )
    if op == "ste.synthesize_wav" and inputs.get("speech_available") is False:
        raise PolicyError(
            "Local System.Speech helper unavailable; provide --audio-dir with PCM WAV files.",
            code=ERROR_DEPENDENCY_MISSING,
        )

    workspace_root: Path | None = None
    if inputs.get("workspace_root") is not None:
        workspace_root = _safe_existing_dir(inputs["workspace_root"], "Workspace root")

    title = inputs.get("title")
    if title is not None and (not isinstance(title, str) or not title.strip()):
        raise PolicyError("Title must not be empty.", code=ERROR_INVALID_INPUT)

    pre_snapshots: dict[str, dict[str, Any]] = {}

    def record_snapshot(path: Path, role: str) -> tuple[str, int, bytes]:
        raw = path.read_bytes()
        if not raw:
            raise PolicyError(f"{role} file must not be empty: {path}", code=ERROR_INVALID_INPUT)
        sha = _sha256_bytes(raw)
        pre_snapshots[str(path)] = {"sha256": sha, "size": len(raw), "role": role}
        return sha, len(raw), raw

    # Validate digest fields
    source_digest: str | None = inputs.get("source_digest")
    source_sha256: str | None = inputs.get("source_sha256")
    normalized_input_sha256: str | None = inputs.get("normalized_input_sha256")
    for sha_field in (
        "source_digest",
        "source_sha256",
        "normalized_input_sha256",
        "content_sha256",
        "prompt_sha256",
        "text_sha256",
        "design_sha256",
    ):
        val = inputs.get(sha_field)
        if val is not None and (not isinstance(val, str) or not _HEX64.fullmatch(val)):
            raise PolicyError(f"{sha_field} must be a 64-character lowercase hex digest.", code=ERROR_INVALID_INPUT)

    # Resolve source_paths (read-only origins) and legacy source_path / design_path
    raw_source_paths = inputs.get("source_paths")
    if raw_source_paths is not None and not isinstance(raw_source_paths, list):
        raise PolicyError("source_paths must be a list of path strings.", code=ERROR_INVALID_INPUT)

    resolved_source_paths: list[Path] = []
    resolved_source_dirs: list[Path] = []
    if raw_source_paths:
        for idx, sp_item in enumerate(raw_source_paths):
            abs_sp, res_sp = _check_safe_path(sp_item, f"source_paths[{idx}]")
            _check_origin_confinement(
                res_sp,
                f"source_paths[{idx}]",
                workspace_root=workspace_root,
                caller=caller_kind,
            )
            try:
                sp_info = abs_sp.lstat()
            except FileNotFoundError as exc:
                raise PolicyError(f"source_paths[{idx}] does not exist: {abs_sp}", code=ERROR_INVALID_INPUT) from exc
            if _is_link_or_reparse(sp_info):
                raise PolicyError(f"source_paths[{idx}] must not be a link: {abs_sp}", code=ERROR_INVALID_INPUT)
            if stat.S_ISDIR(sp_info.st_mode):
                if op not in {"ste.export_bundle", "ste.inspect_artifact", "ste.prepare_story_media", "ste.regenerate_gallery"}:
                    raise PolicyError(
                        f"source_paths[{idx}] must be a regular file for {op}: {abs_sp}",
                        code=ERROR_INVALID_INPUT,
                    )
                _reject_if_legacy_manual_stage(res_sp, f"source_paths[{idx}]")
                resolved_source_dirs.append(res_sp)
            elif stat.S_ISREG(sp_info.st_mode):
                if sp_info.st_size == 0:
                    raise PolicyError(f"source_paths[{idx}] must not be empty: {abs_sp}", code=ERROR_INVALID_INPUT)
                record_snapshot(res_sp, f"source_paths[{idx}]")
                resolved_source_paths.append(res_sp)
            else:
                raise PolicyError(f"source_paths[{idx}] must be a regular file: {abs_sp}", code=ERROR_INVALID_INPUT)

    raw_source = inputs.get("source_path") if "source_path" in inputs else inputs.get("source")
    resolved_source: Path | None = None
    parsed_source_data: dict[str, Any] | None = None

    if raw_source is not None:
        resolved_source = _safe_existing_file(raw_source, "Input source")
        _check_origin_confinement(
            resolved_source,
            "Input source",
            workspace_root=workspace_root,
            caller=caller_kind,
        )
        if resolved_source not in resolved_source_paths:
            resolved_source_paths.insert(0, resolved_source)
    elif resolved_source_paths and op in {"ste.render_bundle", "ste.prepare_story_media", "ste.render_artifact", "ste.prose", "ste.inspect_artifact"}:
        resolved_source = resolved_source_paths[0]

    if resolved_source is not None:
        actual_sha, _, _ = record_snapshot(resolved_source, "source")
        if source_sha256 is not None and source_sha256 != actual_sha:
            raise PolicyError(
                f"Input source_sha256 mismatch for {resolved_source}: expected {source_sha256}, got {actual_sha}.",
                code=ERROR_INVALID_INPUT,
            )
        source_sha256 = actual_sha
        if op == "ste.render_bundle":
            try:
                _, norm_bytes, parsed_source_data = cli.normalized_input(
                    resolved_source,
                    title,
                    trusted_html,
                )
                validate_input(parsed_source_data)
            except ValueError as exc:
                raise PolicyError(str(exc), code=ERROR_INVALID_INPUT) from exc
            normalized_input_sha256 = _sha256_bytes(norm_bytes)
        elif op == "ste.prepare_story_media":
            try:
                raw_story_text = resolved_source.read_bytes().decode("utf-8-sig")
                story_obj = loads_json(raw_story_text)
                validate_story(story_obj)
                parsed_source_data = typing.cast(dict[str, Any], story_obj)
            except ValueError as exc:
                raise PolicyError(str(exc), code=ERROR_INVALID_INPUT) from exc
        if source_digest is not None and source_digest not in {actual_sha, normalized_input_sha256}:
            raise PolicyError(
                f"Input source_digest mismatch for {resolved_source}: got {source_digest}.",
                code=ERROR_INVALID_INPUT,
            )

    if source_digest is None:
        source_digest = (
            normalized_input_sha256
            or source_sha256
            or inputs.get("content_sha256")
            or inputs.get("prompt_sha256")
            or inputs.get("text_sha256")
        )

    # Resolve design_path if supplied (or second file in source_paths for render_bundle/render_artifact)
    raw_design = inputs.get("design_path") if "design_path" in inputs else inputs.get("design")
    resolved_design: Path | None = None
    design_sha256: str | None = inputs.get("design_sha256")
    if raw_design is not None:
        resolved_design = _safe_existing_file(raw_design, "Design file")
        _check_origin_confinement(
            resolved_design,
            "Design file",
            workspace_root=workspace_root,
            caller=caller_kind,
        )
        if resolved_design not in resolved_source_paths:
            resolved_source_paths.append(resolved_design)
    elif len(resolved_source_paths) >= 2 and op in {"ste.render_bundle", "ste.render_artifact"}:
        resolved_design = resolved_source_paths[1]

    if resolved_design is not None:
        actual_d_sha, _, d_bytes = record_snapshot(resolved_design, "design")
        try:
            d_text = d_bytes.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise PolicyError("Design file must be valid UTF-8.", code=ERROR_INVALID_INPUT) from exc
        if not d_text.strip():
            raise PolicyError("Design file is empty.", code=ERROR_INVALID_INPUT)
        if design_sha256 is not None and design_sha256 != actual_d_sha:
            raise PolicyError("Design SHA-256 does not match file on disk.", code=ERROR_INVALID_INPUT)
        design_sha256 = actual_d_sha

    # Resolve output_root / output_dir / input_dir / target_paths
    raw_output_dir = (
        inputs.get("output_root")
        if "output_root" in inputs
        else (inputs.get("output_dir") if "output_dir" in inputs else inputs.get("output"))
    )
    if raw_output_dir is None and op == "ste.regenerate_gallery" and "artifact_dir" in inputs:
        raw_output_dir = inputs.get("artifact_dir")
    raw_input_dir = inputs.get("input_dir")
    if raw_input_dir is None and op == "ste.inspect_artifact" and "artifact_dir" in inputs:
        raw_input_dir = inputs.get("artifact_dir")
    if raw_input_dir is None and resolved_source_dirs and op in {"ste.export_bundle", "ste.inspect_artifact"}:
        raw_input_dir = str(resolved_source_dirs[0])
    if raw_output_dir is None and resolved_source_dirs and op == "ste.regenerate_gallery":
        raw_output_dir = str(resolved_source_dirs[0])

    resolved_input_dir: Path | None = None
    if raw_input_dir is not None:
        resolved_input_dir = _safe_existing_dir(raw_input_dir, "Input directory")
        _check_origin_confinement(
            resolved_input_dir,
            "Input directory",
            workspace_root=workspace_root,
            caller=caller_kind,
        )
        _reject_if_legacy_manual_stage(resolved_input_dir, "Input directory")

    resolved_output_dir: Path | None = None
    if raw_output_dir is not None:
        if op == "ste.render_bundle":
            resolved_output_dir = _safe_new_or_empty_dir(
                raw_output_dir,
                "Output directory",
                workspace_root=workspace_root,
                caller=caller_kind,
            )
        elif op in {"ste.prepare_story_media", "ste.export_bundle"}:
            resolved_output_dir = _safe_export_dir_for_create(
                raw_output_dir,
                "Output directory",
                workspace_root=workspace_root,
                caller=caller_kind,
            )
            if op == "ste.prepare_story_media" and not resolved_output_dir.parent.is_dir():
                raise PolicyError(
                    "The output parent directory must already exist.",
                    code=ERROR_INVALID_INPUT,
                )
        else:
            _, resolved_output_dir = _check_safe_path(raw_output_dir, "Output directory")
            _check_not_protected_target(
                resolved_output_dir,
                "Output directory",
                workspace_root=workspace_root,
                caller=caller_kind,
            )
            if resolved_output_dir.exists() and not resolved_output_dir.is_dir():
                raise PolicyError("Output directory must not be a regular file.", code=ERROR_INVALID_INPUT)
            if op == "ste.regenerate_gallery":
                gallery_candidate = resolved_output_dir / "gallery.html"
                if gallery_candidate.is_symlink():
                    raise PolicyError(
                        "Refusing to replace a symlink at gallery.html",
                        code=ERROR_POLICY_REFUSAL,
                    )
                if gallery_candidate.exists():
                    if not gallery_candidate.is_file():
                        raise PolicyError("gallery.html is not a regular file.", code=ERROR_INVALID_INPUT)
                    raw_prefix = gallery_candidate.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
                    if not raw_prefix.startswith(_GALLERY_PREFIX):
                        raise PolicyError(
                            "Refusing to overwrite an unowned gallery.html",
                            code=ERROR_POLICY_REFUSAL,
                        )

    # Target paths
    raw_targets: list[Any] = []
    if inputs.get("target_paths") is not None:
        if not isinstance(inputs["target_paths"], list):
            raise PolicyError("target_paths must be a list of paths.", code=ERROR_INVALID_INPUT)
        raw_targets.extend(inputs["target_paths"])
    if inputs.get("target_path") is not None:
        raw_targets.append(inputs["target_path"])

    resolved_targets: list[Path] = []
    for idx, item in enumerate(raw_targets):
        label = f"target_paths[{idx}]"
        abs_t, res_t = _check_safe_path(item, label)
        if op != "ste.inspect_artifact":
            _check_not_protected_target(res_t, label, workspace_root=workspace_root, caller=caller_kind)
            if resolved_output_dir is not None and not res_t.is_relative_to(resolved_output_dir):
                raise PolicyError(
                    f"{label} points outside declared output_root {resolved_output_dir}: {res_t}",
                    code=ERROR_POLICY_REFUSAL,
                )
        else:
            _check_origin_confinement(res_t, label, workspace_root=workspace_root, caller=caller_kind)
            if not abs_t.exists():
                raise PolicyError(f"{label} does not exist: {abs_t}", code=ERROR_INVALID_INPUT)
            if res_t.is_file():
                record_snapshot(res_t, f"inspect[{idx}]")
        if res_t not in resolved_targets:
            resolved_targets.append(res_t)

    # Evidence root & evidence files / locators
    explicit_ev_root: Path | None = None
    if inputs.get("evidence_root") is not None:
        explicit_ev_root = _safe_existing_dir(inputs["evidence_root"], "Evidence root")
        _check_origin_confinement(
            explicit_ev_root,
            "Evidence root",
            workspace_root=workspace_root,
            caller=caller_kind,
        )
    resolved_ev_root: Path | None = explicit_ev_root
    if resolved_ev_root is None and resolved_source is not None:
        resolved_ev_root = _default_evidence_root_for_source(resolved_source)
    elif resolved_ev_root is None and workspace_root is not None:
        resolved_ev_root = workspace_root

    raw_ev_list: list[Any] = []
    for ev_key in ("evidence_paths", "evidence_files", "evidence"):
        if inputs.get(ev_key) is not None:
            if not isinstance(inputs[ev_key], list):
                raise PolicyError(f"{ev_key} must be a list.", code=ERROR_INVALID_INPUT)
            raw_ev_list.extend(inputs[ev_key])

    resolved_evidence_files: list[dict[str, Any]] = []
    seen_ev_paths: set[Path] = set()
    for idx, ev_item in enumerate(raw_ev_list):
        ev_raw_path = ev_item.get("source_path") if isinstance(ev_item, dict) else ev_item
        res_ev = _safe_existing_file(ev_raw_path, f"evidence[{idx}]")
        _check_origin_confinement(res_ev, f"evidence[{idx}]", workspace_root=workspace_root, caller=caller_kind)
        if res_ev in (resolved_source, resolved_design) or res_ev in resolved_source_paths:
            raise PolicyError(
                f"evidence[{idx}] collides with source or design file: {res_ev}",
                code=ERROR_INVALID_INPUT,
            )
        if resolved_output_dir is not None and res_ev.is_relative_to(resolved_output_dir):
            raise PolicyError(
                f"evidence[{idx}] must not reside inside output_root: {res_ev}",
                code=ERROR_INVALID_INPUT,
            )
        if res_ev in seen_ev_paths:
            raise PolicyError(f"Duplicate evidence file: {res_ev}", code=ERROR_INVALID_INPUT)
        seen_ev_paths.add(res_ev)
        ev_sha, ev_size, _ = record_snapshot(res_ev, f"evidence[{idx}]")
        resolved_evidence_files.append({
            "rel_path": f"evidence/{res_ev.name}",
            "source_path": str(res_ev),
            "sha256": ev_sha,
            "size": ev_size,
        })

    raw_locators = (
        inputs.get("evidence_locators")
        if "evidence_locators" in inputs
        else inputs.get("relative_locators")
    )
    if raw_locators is not None:
        if not isinstance(raw_locators, list):
            raise PolicyError("evidence_locators must be a list of strings.", code=ERROR_INVALID_INPUT)
        if resolved_ev_root is None:
            raise PolicyError(
                "evidence_root is required when evidence_locators are provided.",
                code=ERROR_INVALID_INPUT,
            )
        for idx, loc in enumerate(raw_locators):
            res_loc, norm_loc = _validate_relative_locator(
                loc,
                f"evidence_locators[{idx}]",
                resolved_ev_root,
            )
            _check_origin_confinement(
                res_loc,
                f"evidence_locators[{idx}]",
                workspace_root=workspace_root,
                caller=caller_kind,
            )
            loc_sha, loc_size, _ = record_snapshot(res_loc, f"locator[{norm_loc}]")
            if res_loc not in seen_ev_paths:
                seen_ev_paths.add(res_loc)
                resolved_evidence_files.append({
                    "rel_path": norm_loc,
                    "source_path": str(res_loc),
                    "sha256": loc_sha,
                    "size": loc_size,
                })

    if parsed_source_data is not None and parsed_source_data.get("kind") == "story" and resolved_source is not None:
        if not _is_builtin_quickstart_source(resolved_source) and resolved_ev_root is not None:
            for idx, src_entry in enumerate(parsed_source_data.get("sources", [])):
                if isinstance(src_entry, dict) and "locator" in src_entry:
                    res_loc, norm_loc = _validate_relative_locator(
                        src_entry["locator"],
                        f"story.sources[{idx}]",
                        resolved_ev_root,
                    )
                    _check_origin_confinement(
                        res_loc,
                        f"story.sources[{idx}]",
                        workspace_root=workspace_root,
                        caller=caller_kind,
                    )
                    if res_loc not in seen_ev_paths:
                        seen_ev_paths.add(res_loc)
                        loc_sha, loc_size, _ = record_snapshot(res_loc, f"story_locator[{norm_loc}]")
                        resolved_evidence_files.append({
                            "rel_path": norm_loc,
                            "source_path": str(res_loc),
                            "sha256": loc_sha,
                            "size": loc_size,
                        })

    # Audio/speech fields
    resolved_audio_dir: Path | None = None
    if inputs.get("audio_dir") is not None:
        resolved_audio_dir = _safe_existing_dir(inputs["audio_dir"], "audio_dir")
        _check_origin_confinement(resolved_audio_dir, "audio_dir", workspace_root=workspace_root, caller=caller_kind)
    elif op == "ste.prepare_story_media" and resolved_source_dirs:
        resolved_audio_dir = resolved_source_dirs[0]

    if resolved_audio_dir is not None and (
        inputs.get("voice") is not None or inputs.get("speaker_injected") is True
    ):
        raise PolicyError(
            "Choose audio_dir OR local speech; do not combine audio_dir with voice/speaker.",
            code=ERROR_INVALID_INPUT,
        )
    voice = inputs.get("voice")
    if voice is not None and (not isinstance(voice, str) or not voice.strip() or "\x00" in voice):
        raise PolicyError("Voice must be a nonempty name.", code=ERROR_INVALID_INPUT)

    resolved_text_path: Path | None = None
    if inputs.get("text_path") is not None:
        resolved_text_path = _safe_existing_file(inputs["text_path"], "text_path")
        _check_origin_confinement(resolved_text_path, "text_path", workspace_root=workspace_root, caller=caller_kind)
        record_snapshot(resolved_text_path, "text_path")
        if resolved_text_path not in resolved_source_paths:
            resolved_source_paths.append(resolved_text_path)
    elif op == "ste.synthesize_wav" and resolved_source_paths:
        resolved_text_path = resolved_source_paths[0]

    resolved_audio_path: Path | None = None
    if inputs.get("audio_path") is not None:
        _, resolved_audio_path = _check_safe_path(inputs["audio_path"], "audio_path")
        _check_not_protected_target(
            resolved_audio_path,
            "audio_path",
            workspace_root=workspace_root,
            caller=caller_kind,
        )
        if resolved_audio_path not in resolved_targets:
            resolved_targets.append(resolved_audio_path)
    elif op == "ste.synthesize_wav" and resolved_targets:
        resolved_audio_path = resolved_targets[0]

    # Enforce that read-only origins (source_paths, evidence_paths) are NEVER edited targets
    read_only_origins = set(resolved_source_paths) | seen_ev_paths
    if op != "ste.inspect_artifact":
        overlap_targets = read_only_origins.intersection(resolved_targets)
        if overlap_targets:
            raise PolicyError(
                f"source_paths and evidence_paths are read-only origins and must not be edited targets: "
                f"{sorted(str(p) for p in overlap_targets)}",
                code=ERROR_POLICY_REFUSAL,
            )

    # Validate expected_before (maps edited/created target path -> current 64-hex SHA-256 or None for new file)
    raw_expected_before = inputs.get("expected_before")
    normalized_expected_before: dict[str, str | None] = {}
    if raw_expected_before is not None:
        if not isinstance(raw_expected_before, dict):
            raise PolicyError("expected_before must be a dict mapping target path to sha256 or null.", code=ERROR_INVALID_INPUT)
        for raw_eb_path, exp_sha in sorted(raw_expected_before.items()):
            abs_eb, res_eb = _check_safe_path(raw_eb_path, f"expected_before[{raw_eb_path!r}]")
            _check_not_protected_target(
                res_eb,
                f"expected_before[{raw_eb_path!r}]",
                workspace_root=workspace_root,
                caller=caller_kind,
            )
            if res_eb in read_only_origins:
                raise PolicyError(
                    f"Read-only origin {res_eb} cannot be an edited target in expected_before.",
                    code=ERROR_POLICY_REFUSAL,
                )
            if resolved_output_dir is not None and not res_eb.is_relative_to(resolved_output_dir):
                raise PolicyError(
                    f"expected_before target {res_eb} points outside output_root {resolved_output_dir}.",
                    code=ERROR_POLICY_REFUSAL,
                )
            if exp_sha is None:
                if abs_eb.exists() or res_eb.exists():
                    raise PolicyError(
                        f"Target file expected to be new (expected_before=null) already exists: {res_eb}",
                        code=ERROR_POLICY_REFUSAL,
                    )
                normalized_expected_before[str(res_eb)] = None
            else:
                if not isinstance(exp_sha, str) or not _HEX64.fullmatch(exp_sha):
                    raise PolicyError(
                        f"expected_before[{raw_eb_path!r}] must be a 64-char hex SHA-256 or null.",
                        code=ERROR_INVALID_INPUT,
                    )
                existing_eb = _safe_existing_file(
                    abs_eb,
                    f"expected_before[{raw_eb_path!r}]",
                    code=ERROR_POLICY_REFUSAL,
                )
                current_eb_sha = _sha256_bytes(existing_eb.read_bytes())
                if current_eb_sha != exp_sha:
                    raise PolicyError(
                        f"expected_before SHA-256 mismatch for {existing_eb}: "
                        f"expected {exp_sha}, found {current_eb_sha}.",
                        code=ERROR_POLICY_REFUSAL,
                    )
                normalized_expected_before[str(existing_eb)] = exp_sha
            if res_eb not in resolved_targets:
                resolved_targets.append(res_eb)

    # Validate proposed_contents (maps target path -> proposed UTF-8 text)
    raw_proposed = inputs.get("proposed_contents")
    expected_after_contents: dict[str, dict[str, Any]] = {}
    if raw_proposed is not None:
        if not isinstance(raw_proposed, dict):
            raise PolicyError("proposed_contents must map target paths to UTF-8 strings.", code=ERROR_INVALID_INPUT)
        for raw_pc_path, pc_text in sorted(raw_proposed.items()):
            if not isinstance(pc_text, str) or "\x00" in pc_text:
                raise PolicyError(
                    f"proposed_contents[{raw_pc_path!r}] must be a valid UTF-8 string without null bytes.",
                    code=ERROR_INVALID_INPUT,
                )
            try:
                pc_bytes = pc_text.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise PolicyError(
                    f"proposed_contents[{raw_pc_path!r}] is not valid UTF-8: {exc}",
                    code=ERROR_INVALID_INPUT,
                ) from exc
            if not pc_bytes:
                raise PolicyError(
                    f"proposed_contents[{raw_pc_path!r}] must not be empty.",
                    code=ERROR_INVALID_INPUT,
                )
            _, res_pc = _check_safe_path(raw_pc_path, f"proposed_contents[{raw_pc_path!r}]")
            _check_not_protected_target(
                res_pc,
                f"proposed_contents[{raw_pc_path!r}]",
                workspace_root=workspace_root,
                caller=caller_kind,
            )
            if res_pc in read_only_origins:
                raise PolicyError(
                    f"Read-only origin {res_pc} cannot be overwritten via proposed_contents.",
                    code=ERROR_POLICY_REFUSAL,
                )
            if resolved_output_dir is not None and not res_pc.is_relative_to(resolved_output_dir):
                raise PolicyError(
                    f"proposed_contents target {res_pc} points outside output_root {resolved_output_dir}.",
                    code=ERROR_POLICY_REFUSAL,
                )
            expected_after_contents[str(res_pc)] = {
                "sha256": _sha256_bytes(pc_bytes),
                "size": len(pc_bytes),
            }
            if res_pc not in resolved_targets:
                resolved_targets.append(res_pc)

    # Overlap checks
    if resolved_output_dir is not None:
        bound_inputs = list(resolved_source_paths) + [
            Path(item["source_path"]) for item in resolved_evidence_files
        ]
        _check_no_overlap(resolved_output_dir, resolved_input_dir, bound_inputs, explicit_ev_root)

    # Operation-specific required field checks
    if op == "ste.render_bundle":
        if resolved_output_dir is None or (resolved_source is None and source_digest is None):
            raise PolicyError(
                "ste.render_bundle requires output_root and source_paths (or source_digest).",
                code=ERROR_INVALID_INPUT,
            )
    elif op == "ste.render_artifact":
        if resolved_output_dir is None or (resolved_source is None and source_digest is None):
            raise PolicyError(
                "ste.render_artifact requires output_root and source_digest/source_paths.",
                code=ERROR_INVALID_INPUT,
            )
    elif op == "ste.regenerate_gallery":
        if resolved_output_dir is None:
            raise PolicyError("ste.regenerate_gallery requires output_root.", code=ERROR_INVALID_INPUT)
    elif op == "ste.prepare_story_media":
        if resolved_output_dir is None or (resolved_source is None and source_digest is None):
            raise PolicyError(
                "ste.prepare_story_media requires output_root and source_paths.",
                code=ERROR_INVALID_INPUT,
            )
        if (
            resolved_audio_dir is None
            and not inputs.get("speaker_injected")
            and inputs.get("speech_available") is False
        ):
            raise PolicyError(
                "Local System.Speech helper unavailable; provide --audio-dir with PCM WAV files.",
                code=ERROR_DEPENDENCY_MISSING,
            )
    elif op == "ste.synthesize_wav":
        if resolved_text_path is None or resolved_audio_path is None:
            raise PolicyError(
                "ste.synthesize_wav requires source_paths/text_path and target_paths/audio_path.",
                code=ERROR_INVALID_INPUT,
            )
        if str(resolved_audio_path) not in normalized_expected_before:
            if resolved_audio_path.exists():
                raise PolicyError(
                    f"Target audio_path expected to be new (expected_before=null) already exists: {resolved_audio_path}",
                    code=ERROR_POLICY_REFUSAL,
                )
            normalized_expected_before[str(resolved_audio_path)] = None
    elif op == "ste.host_write_artifact":
        if not resolved_targets and resolved_output_dir is None:
            raise PolicyError(
                "ste.host_write_artifact requires target_paths or output_root.",
                code=ERROR_INVALID_INPUT,
            )
    elif op == "ste.inspect_artifact":
        if resolved_input_dir is None and resolved_source is None and not resolved_targets:
            raise PolicyError(
                "ste.inspect_artifact requires source_paths, input_dir, or target_paths.",
                code=ERROR_INVALID_INPUT,
            )
    elif op == "ste.prose":
        profile = inputs.get("profile", "relaxed")
        if profile not in LIMITS:
            raise PolicyError(f"Unsupported prose profile: {profile!r}", code=ERROR_INVALID_INPUT)
    elif op == "ste.export_bundle":
        if resolved_input_dir is None or resolved_output_dir is None:
            raise PolicyError(
                "ste.export_bundle requires input_dir/source_paths and output_root/output_dir.",
                code=ERROR_INVALID_INPUT,
            )
        manifest_obj, _, bundle_payload_records, bundle_ev_records, bundle_closure = _validate_native_bundle_for_export(
            resolved_input_dir,
            explicit_evidence_root=explicit_ev_root,
            explicit_evidence_files=[item["source_path"] for item in resolved_evidence_files],
            workspace_root=workspace_root,
            caller=caller_kind,
        )
        # Always snapshot the original source file even when export inputs only supplied input_dir
        bundle_orig_source = _safe_existing_file(manifest_obj["source_path"], "Original source file")
        record_snapshot(bundle_orig_source, "bundle_origin_source")
        if bundle_orig_source not in resolved_source_paths:
            resolved_source_paths.append(bundle_orig_source)
        if resolved_source is None:
            resolved_source = bundle_orig_source
        if source_sha256 is None:
            source_sha256 = str(manifest_obj["source_sha256"])

        for rel, rec in sorted(bundle_payload_records.items()):
            candidate_file = resolved_input_dir / Path(rel)
            if candidate_file.is_file():
                pre_snapshots[str(candidate_file.resolve())] = {
                    "sha256": rec["sha256"],
                    "size": rec["size"],
                    "role": f"bundle:{rel}",
                }
        for ev_rec in bundle_ev_records:
            pre_snapshots[ev_rec["source_path"]] = {
                "sha256": ev_rec["sha256"],
                "size": ev_rec["size"],
                "role": f"bundle_evidence:{ev_rec['rel_path']}",
            }
        # Re-check overlap with the discovered original source and evidence paths
        _check_no_overlap(
            resolved_output_dir,
            resolved_input_dir,
            list(resolved_source_paths) + [Path(r["source_path"]) for r in bundle_ev_records],
            explicit_ev_root,
        )
        normalized_input_sha256 = bundle_closure
        if source_digest is None:
            source_digest = bundle_closure

    canonical_inputs: dict[str, Any] = {
        "op": op,
        "caller_kind": caller_kind,
        "caller": caller_kind,
        "workspace_root": str(workspace_root) if workspace_root else None,
        "output_root": str(resolved_output_dir) if resolved_output_dir else None,
        "output_dir": str(resolved_output_dir) if resolved_output_dir else None,
        "input_dir": str(resolved_input_dir) if resolved_input_dir else None,
        "target_paths": [str(p) for p in resolved_targets],
        "source_paths": [str(p) for p in resolved_source_paths],
        "source_path": str(resolved_source) if resolved_source else None,
        "source_digest": source_digest,
        "source_sha256": source_sha256,
        "normalized_input_sha256": normalized_input_sha256,
        "source_kind": source_kind,
        "title": title,
        "design_path": str(resolved_design) if resolved_design else None,
        "design_sha256": design_sha256,
        "trusted_html": trusted_html,
        "has_raw_html": has_raw_html,
        "evidence_root": str(resolved_ev_root) if resolved_ev_root else None,
        "evidence_files": sorted(resolved_evidence_files, key=lambda x: x["source_path"]),
        "expected_before": normalized_expected_before,
        "expected_after_contents": expected_after_contents,
        "audio_dir": str(resolved_audio_dir) if resolved_audio_dir else None,
        "text_path": str(resolved_text_path) if resolved_text_path else None,
        "audio_path": str(resolved_audio_path) if resolved_audio_path else None,
        "voice": voice,
        "profile": inputs.get("profile"),
    }
    closure_payload = {
        **canonical_inputs,
        "pre_snapshots": {
            path_key: pre_snapshots[path_key]
            for path_key in sorted(pre_snapshots.keys())
        },
    }
    source_closure_sha256 = _sha256_text(_canonical_json(closure_payload))
    inputs_sha256 = _sha256_text(_canonical_json(inputs))
    return {
        "canonical_inputs": canonical_inputs,
        "raw_inputs_sha256": inputs_sha256,
        "source_closure_sha256": source_closure_sha256,
        "pre_snapshots": pre_snapshots,
    }


def _enforce_parent_bounds_on_child(
    parent_inputs: dict[str, Any],
    child_inputs: dict[str, Any],
) -> None:
    """Reject nested child operations whose output_root, workspace_root, or target_paths escape parent bounds."""
    parent_op = parent_inputs.get("op")
    child_op = child_inputs.get("op")

    parent_ws = Path(parent_inputs["workspace_root"]).resolve() if parent_inputs.get("workspace_root") else None
    child_ws = Path(child_inputs["workspace_root"]).resolve() if child_inputs.get("workspace_root") else None
    if parent_ws is not None and child_ws is not None:
        if not child_ws.is_relative_to(parent_ws):
            raise PolicyError(
                f"Nested operation {child_op!r} workspace_root {child_ws} escapes parent {parent_op!r} workspace_root {parent_ws}.",
                code=ERROR_POLICY_REFUSAL,
            )

    parent_out_raw = parent_inputs.get("output_root") or parent_inputs.get("output_dir")
    child_out_raw = child_inputs.get("output_root") or child_inputs.get("output_dir")
    parent_out = Path(parent_out_raw).resolve() if parent_out_raw else None
    child_out = Path(child_out_raw).resolve() if child_out_raw else None

    if parent_out is not None:
        if child_out is not None and not child_out.is_relative_to(parent_out):
            raise PolicyError(
                f"Nested operation {child_op!r} output_root {child_out} escapes parent {parent_op!r} output_root {parent_out}.",
                code=ERROR_POLICY_REFUSAL,
            )
        for child_target_str in child_inputs.get("target_paths", []):
            child_target = Path(child_target_str).resolve()
            if not child_target.is_relative_to(parent_out) or child_target == parent_out:
                raise PolicyError(
                    f"Nested operation {child_op!r} target {child_target} escapes parent {parent_op!r} output_root {parent_out}.",
                    code=ERROR_POLICY_REFUSAL,
                )
        if child_op == "ste.synthesize_wav" and parent_op == "ste.prepare_story_media":
            text_p = Path(child_inputs["text_path"]).resolve() if child_inputs.get("text_path") else None
            audio_p = Path(child_inputs["audio_path"]).resolve() if child_inputs.get("audio_path") else None
            if text_p is not None and not text_p.is_relative_to(parent_out):
                raise PolicyError(
                    f"Nested ste.synthesize_wav text_path {text_p} escapes parent media output_root {parent_out}.",
                    code=ERROR_POLICY_REFUSAL,
                )
            if audio_p is not None and audio_p.parent != (parent_out / "video").resolve():
                raise PolicyError(
                    f"Nested ste.synthesize_wav audio_path {audio_p} must reside inside {parent_out / 'video'}.",
                    code=ERROR_POLICY_REFUSAL,
                )
    elif parent_inputs.get("target_paths"):
        allowed_parent_targets = {Path(p).resolve() for p in parent_inputs["target_paths"]}
        for child_target_str in child_inputs.get("target_paths", []):
            child_target = Path(child_target_str).resolve()
            if child_target not in allowed_parent_targets:
                raise PolicyError(
                    f"Nested operation {child_op!r} target {child_target} is not in parent {parent_op!r} target_paths.",
                    code=ERROR_POLICY_REFUSAL,
                )

    parent_origins = {Path(p).resolve() for p in parent_inputs.get("source_paths", [])} | {
        Path(item["source_path"]).resolve() for item in parent_inputs.get("evidence_files", [])
    }
    for child_target_str in child_inputs.get("target_paths", []):
        if Path(child_target_str).resolve() in parent_origins:
            raise PolicyError(
                f"Nested operation {child_op!r} target {child_target_str} collides with parent read-only origin.",
                code=ERROR_POLICY_REFUSAL,
            )


def _default_validate_result(op: str, inputs: dict[str, Any], result: Any) -> dict[str, Any]:
    """Built-in post-observation builder when caller does not supply validate_result."""
    outputs: dict[str, dict[str, Any]] = {}
    checks: list[str] = []
    warnings: list[str] = []
    status = "complete"

    def observe_file(path: Path) -> None:
        resolved = _safe_existing_file(path, f"{op} output file", code=ERROR_POSTCONDITION_FAILURE)
        raw = resolved.read_bytes()
        outputs[str(resolved)] = {"sha256": _sha256_bytes(raw), "size": len(raw)}

    if op in {"ste.render_bundle", "ste.export_bundle"}:
        if not isinstance(result, dict):
            raise PolicyError(f"{op} result must be a manifest dict.", code=ERROR_POSTCONDITION_FAILURE)
        status = str(result.get("status") or "")
        if status not in {"complete", "exported"}:
            raise PolicyError(
                f"{op} returned non-success status {status!r}.",
                code=ERROR_POSTCONDITION_FAILURE,
            )
        raw_out = inputs.get("output_root") or inputs.get("output_dir") or inputs.get("output")
        if not raw_out:
            raise PolicyError(f"Missing output_root for {op}.", code=ERROR_POSTCONDITION_FAILURE)
        out_dir = _safe_existing_dir(raw_out, "Output directory", code=ERROR_POSTCONDITION_FAILURE)
        manifest_file = out_dir / "manifest.json"
        if manifest_file.is_file():
            observe_file(manifest_file)
        files_map = result.get("files")
        if isinstance(files_map, dict):
            for role, entry in files_map.items():
                if isinstance(entry, dict) and isinstance(entry.get("path"), str):
                    confined_p = _validate_confined_bundle_filepath(
                        entry["path"],
                        out_dir,
                        f"manifest.files[{role}]",
                        code=ERROR_POSTCONDITION_FAILURE,
                    )
                    observe_file(confined_p)
        for ev_rec in result.get("evidence_files", []) or []:
            if isinstance(ev_rec, dict) and isinstance(ev_rec.get("rel_path"), str):
                ev_rel = Path(ev_rec["rel_path"])
                if len(ev_rel.parts) == 2 and ev_rel.parts[0] == "evidence":
                    observe_file(out_dir / ev_rel)
        if isinstance(result.get("warnings"), list):
            warnings.extend(str(w) for w in result["warnings"])
        checks.extend(["manifest_complete", "bundle_files_recorded"])
    elif op == "ste.render_artifact":
        if not isinstance(result, dict) or not {"html_path", "design_path", "meta_path", "slug"} <= set(result.keys()):
            raise PolicyError(
                "ste.render_artifact must return a dict with html_path, design_path, meta_path, and slug.",
                code=ERROR_POSTCONDITION_FAILURE,
            )
        for key in ("html_path", "design_path", "meta_path"):
            observe_file(Path(result[key]))
        checks.extend(["triple_complete", "meta_sidecar_present"])
    elif op == "ste.regenerate_gallery":
        if not isinstance(result, (str, Path)):
            raise PolicyError(
                "ste.regenerate_gallery must return the gallery.html Path.",
                code=ERROR_POSTCONDITION_FAILURE,
            )
        observe_file(Path(result))
        checks.append("gallery_generated")
    elif op == "ste.prepare_story_media":
        if not isinstance(result, dict) or result.get("status") != "prepared_not_rendered":
            raise PolicyError(
                "ste.prepare_story_media must return a manifest with status 'prepared_not_rendered'.",
                code=ERROR_POSTCONDITION_FAILURE,
            )
        status = "prepared_not_rendered"
        raw_out = (
            inputs.get("output_root")
            or inputs.get("output_dir")
            or inputs.get("output")
            or result.get("output")
        )
        if not raw_out:
            raise PolicyError("Missing media output directory.", code=ERROR_POSTCONDITION_FAILURE)
        out_dir = _safe_existing_dir(raw_out, "Media output directory", code=ERROR_POSTCONDITION_FAILURE)
        for rel in ("manifest.json", "source.json", "story.json", "review.html", "timeline.json", "transcript.txt", "captions.vtt", "video/index.html"):
            candidate = out_dir / rel
            if candidate.exists():
                observe_file(candidate)
        for audio_entry in result.get("audio", []):
            if not isinstance(audio_entry, dict):
                raise PolicyError("Malformed audio record in media manifest.", code=ERROR_POSTCONDITION_FAILURE)
            confined_wav = _validate_confined_media_audio_relpath(
                audio_entry.get("file"),
                out_dir,
                code=ERROR_POSTCONDITION_FAILURE,
            )
            observe_file(confined_wav)
        if isinstance(result.get("warnings"), list):
            warnings.extend(str(w) for w in result["warnings"])
        checks.extend(["media_manifest_prepared", "video_composition_confined"])
    elif op == "ste.synthesize_wav":
        if result is not None:
            raise PolicyError("ste.synthesize_wav must return None.", code=ERROR_POSTCONDITION_FAILURE)
        status = "synthesized"
        raw_audio = inputs.get("audio_path") or (
            inputs["target_paths"][0]
            if isinstance(inputs.get("target_paths"), list) and inputs.get("target_paths")
            else None
        )
        if not raw_audio:
            raise PolicyError("Missing audio_path/target_paths for ste.synthesize_wav.", code=ERROR_POSTCONDITION_FAILURE)
        observe_file(Path(raw_audio))
        checks.append("pcm_wav_synthesized")
    elif op == "ste.host_write_artifact":
        status = "written"
        targets = list(
            inputs.get("target_paths")
            or ([inputs["target_path"]] if inputs.get("target_path") else [])
        )
        for extra_map in ("expected_before", "proposed_contents"):
            if isinstance(inputs.get(extra_map), dict):
                for k in inputs[extra_map]:
                    if k not in targets:
                        targets.append(k)
        for t in targets:
            observe_file(Path(t))
        checks.append("host_artifact_written")
    elif op == "ste.inspect_artifact":
        status = "inspected"
        checks.append("artifact_inspected")
    elif op == "ste.prose":
        status = "checked"
        if isinstance(result, str) and result.strip():
            profile = str(inputs.get("profile") or "relaxed")
            report = check_text(result, profile if profile in LIMITS else "relaxed")
            warnings.extend(report.get("limitations", []))
        elif isinstance(result, dict) and isinstance(result.get("limitations"), list):
            warnings.extend(str(w) for w in result["limitations"])
        checks.append("prose_advisory_checked")

    return {
        "native_status": status,
        "status": status,
        "outputs": outputs,
        "checks": checks,
        "warnings": warnings,
    }


def _verify_operation_postconditions(
    op: str,
    canonical_inputs: dict[str, Any],
    pre_snapshots: dict[str, dict[str, Any]],
    post_facts: Any,
    *,
    result: Any = None,
) -> dict[str, Any]:
    if not isinstance(post_facts, dict):
        raise PolicyError(
            "Post-validation facts must be a JSON object.",
            code=ERROR_POSTCONDITION_FAILURE,
        )
    _check_no_forbidden_keys(post_facts, "post_facts")

    # Never accept a caller-supplied boolean `check=true` in place of real output records.
    if post_facts.get("check") is True and "outputs" not in post_facts:
        raise PolicyError(
            "Caller-supplied check=true is not accepted as postcondition evidence; "
            "provide observed output file hashes and sizes.",
            code=ERROR_POSTCONDITION_FAILURE,
        )

    if isinstance(result, dict) and result.get("status") in {
        "failed",
        "error",
        "partial_failure_not_rendered",
        "pending_approval",
        "denied",
    }:
        raise PolicyError(
            f"Operation returned failure status {result.get('status')!r}; postcondition verification failed.",
            code=ERROR_POSTCONDITION_FAILURE,
        )

    status = (
        post_facts.get("native_status")
        if "native_status" in post_facts
        else post_facts.get("status", "complete")
    )
    if not isinstance(status, str) or not status.strip() or status in {
        "failed",
        "error",
        "partial_failure_not_rendered",
        "pending_approval",
        "denied",
    }:
        raise PolicyError(
            f"Post-validation reported non-success status {status!r}.",
            code=ERROR_POSTCONDITION_FAILURE,
        )

    # 1. Verify source and evidence immutability (before vs after)
    for snap_path_str, snap_meta in sorted(pre_snapshots.items()):
        snap_path = _safe_existing_file(
            snap_path_str,
            f"Retained input ({snap_meta['role']})",
            code=ERROR_POSTCONDITION_FAILURE,
        )
        current_bytes = snap_path.read_bytes()
        current_sha = _sha256_bytes(current_bytes)
        if current_sha != snap_meta["sha256"] or len(current_bytes) != snap_meta["size"]:
            raise PolicyError(
                f"Input or evidence file changed during operation ({snap_meta['role']}): {snap_path}",
                code=ERROR_POSTCONDITION_FAILURE,
            )

    # 2. Validate declared outputs against actual disk bytes
    raw_outputs = post_facts.get("outputs")
    if op in FILE_PRODUCING_OPERATIONS:
        if not isinstance(raw_outputs, dict) or not raw_outputs:
            raise PolicyError(
                f"Operation {op} must declare non-empty outputs mapping paths to sha256/size.",
                code=ERROR_POSTCONDITION_FAILURE,
            )
    elif raw_outputs is None:
        raw_outputs = {}
    elif not isinstance(raw_outputs, dict):
        raise PolicyError("post_facts.outputs must be a JSON object.", code=ERROR_POSTCONDITION_FAILURE)

    raw_canon_out = canonical_inputs.get("output_root") or canonical_inputs.get("output_dir")
    resolved_output_dir = Path(raw_canon_out).resolve() if raw_canon_out else None
    declared_targets = {Path(p).resolve() for p in canonical_inputs.get("target_paths", [])}
    workspace_root = (
        Path(canonical_inputs["workspace_root"]).resolve()
        if canonical_inputs.get("workspace_root")
        else None
    )
    caller = str(canonical_inputs.get("caller_kind") or canonical_inputs.get("caller") or "native")

    verified_outputs: dict[str, dict[str, Any]] = {}
    disk_bytes_by_path: dict[Path, bytes] = {}

    for raw_path_str, claimed in sorted(raw_outputs.items()):
        if not isinstance(raw_path_str, str) or not raw_path_str.strip():
            raise PolicyError("Output path key must be a non-empty string.", code=ERROR_POSTCONDITION_FAILURE)
        if not isinstance(claimed, dict):
            raise PolicyError(
                f"Output entry for {raw_path_str!r} must be an object with sha256 and size.",
                code=ERROR_POSTCONDITION_FAILURE,
            )
        claimed_sha = claimed.get("sha256")
        claimed_size = claimed.get("size")
        if not isinstance(claimed_sha, str) or not _HEX64.fullmatch(claimed_sha):
            raise PolicyError(
                f"Output entry for {raw_path_str!r} has an invalid sha256 digest.",
                code=ERROR_POSTCONDITION_FAILURE,
            )
        if type(claimed_size) is not int or claimed_size <= 0:
            raise PolicyError(
                f"Output entry for {raw_path_str!r} must have a positive integer size.",
                code=ERROR_POSTCONDITION_FAILURE,
            )

        # Confinement check BEFORE reading bytes from disk
        _, candidate_out = _check_safe_path(
            raw_path_str,
            f"Output file {raw_path_str}",
            code=ERROR_POSTCONDITION_FAILURE,
        )
        if op != "ste.inspect_artifact":
            _check_not_protected_target(
                candidate_out,
                f"Output file {candidate_out.name}",
                workspace_root=workspace_root,
                caller=caller,
            )
        if resolved_output_dir is not None and op != "ste.inspect_artifact":
            if not candidate_out.is_relative_to(resolved_output_dir) or candidate_out == resolved_output_dir:
                raise PolicyError(
                    f"Output file {candidate_out} escapes declared output_root {resolved_output_dir}.",
                    code=ERROR_POSTCONDITION_FAILURE,
                )
        elif declared_targets and op == "ste.host_write_artifact":
            if candidate_out not in declared_targets:
                raise PolicyError(
                    f"Output file {candidate_out} was not declared in target_paths.",
                    code=ERROR_POSTCONDITION_FAILURE,
                )

        resolved_file = _safe_existing_file(
            raw_path_str,
            f"Output file {raw_path_str}",
            code=ERROR_POSTCONDITION_FAILURE,
        )
        actual_bytes = resolved_file.read_bytes()
        actual_sha = _sha256_bytes(actual_bytes)
        actual_size = len(actual_bytes)
        if actual_sha != claimed_sha or actual_size != claimed_size:
            raise PolicyError(
                f"Output file verification failed for {resolved_file}: "
                f"claimed (sha256={claimed_sha}, size={claimed_size}), "
                f"observed (sha256={actual_sha}, size={actual_size}).",
                code=ERROR_POSTCONDITION_FAILURE,
            )
        verified_outputs[str(resolved_file)] = {
            "sha256": actual_sha,
            "size": actual_size,
        }
        disk_bytes_by_path[resolved_file] = actual_bytes

    if declared_targets and op != "ste.inspect_artifact":
        missing_targets = [str(t) for t in sorted(declared_targets) if str(t) not in verified_outputs]
        if missing_targets:
            raise PolicyError(
                f"Declared target_paths were not produced or verified: {', '.join(missing_targets)}",
                code=ERROR_POSTCONDITION_FAILURE,
            )

    expected_after_contents = canonical_inputs.get("expected_after_contents") or {}
    for target_str, expected_meta in sorted(expected_after_contents.items()):
        actual_meta = verified_outputs.get(target_str)
        if actual_meta is None:
            raise PolicyError(
                f"proposed_contents target {target_str} is missing from verified outputs.",
                code=ERROR_POSTCONDITION_FAILURE,
            )
        if (
            actual_meta["sha256"] != expected_meta["sha256"]
            or actual_meta["size"] != expected_meta["size"]
        ):
            raise PolicyError(
                f"Written file {target_str} does not match prechecked proposed_contents.",
                code=ERROR_POSTCONDITION_FAILURE,
            )

    # 3. Operation-specific independent disk checks
    independent_checks: list[str] = [
        "pre_inputs_verified",
        "source_immutability_verified",
    ]
    if op in FILE_PRODUCING_OPERATIONS:
        independent_checks.extend(["output_hashes_verified", "output_paths_confined"])

    if op == "ste.synthesize_wav":
        audio_target = Path(canonical_inputs["audio_path"]).resolve()
        if str(audio_target) not in verified_outputs:
            raise PolicyError(
                f"Synthesized WAV {audio_target} is missing from verified outputs.",
                code=ERROR_POSTCONDITION_FAILURE,
            )
        _validate_pcm_wav(disk_bytes_by_path[audio_target])
        independent_checks.append("pcm_wav_verified")

    elif op == "ste.regenerate_gallery":
        assert resolved_output_dir is not None
        gallery_file = (resolved_output_dir / "gallery.html").resolve()
        if str(gallery_file) not in verified_outputs:
            raise PolicyError("gallery.html is missing from verified outputs.", code=ERROR_POSTCONDITION_FAILURE)
        try:
            gallery_text = disk_bytes_by_path[gallery_file].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PolicyError("gallery.html is not valid UTF-8.", code=ERROR_POSTCONDITION_FAILURE) from exc
        if "<html" not in gallery_text.lower():
            raise PolicyError(
                "gallery.html is not valid HTML output.",
                code=ERROR_POSTCONDITION_FAILURE,
            )
        independent_checks.append("gallery_output_verified")

    elif op == "ste.render_artifact":
        html_files = [p for p in disk_bytes_by_path if p.name.endswith(".html") and p.name != "gallery.html"]
        design_files = [p for p in disk_bytes_by_path if p.name.endswith(".DESIGN.md")]
        meta_files = [p for p in disk_bytes_by_path if p.name.endswith(".meta.yaml")]
        if not html_files or not design_files or not meta_files:
            raise PolicyError(
                "ste.render_artifact outputs must include the complete .html, .DESIGN.md, and .meta.yaml triple.",
                code=ERROR_POSTCONDITION_FAILURE,
            )
        for p in (*html_files, *design_files, *meta_files):
            try:
                disk_bytes_by_path[p].decode("utf-8")
            except UnicodeDecodeError as exc:
                raise PolicyError(f"Triple artifact is not valid UTF-8: {p.name}", code=ERROR_POSTCONDITION_FAILURE) from exc
        independent_checks.append("triple_files_verified")

    elif op == "ste.render_bundle":
        assert resolved_output_dir is not None
        manifest_path = (resolved_output_dir / "manifest.json").resolve()
        if str(manifest_path) not in verified_outputs:
            raise PolicyError("Render bundle is missing manifest.json in outputs.", code=ERROR_POSTCONDITION_FAILURE)
        try:
            manifest_data = loads_json(disk_bytes_by_path[manifest_path].decode("utf-8"))
        except Exception as exc:
            raise PolicyError(f"Invalid manifest.json in render output: {exc}", code=ERROR_POSTCONDITION_FAILURE) from exc
        if not isinstance(manifest_data, dict) or manifest_data.get("status") != "complete":
            raise PolicyError("Render bundle manifest status is not 'complete'.", code=ERROR_POSTCONDITION_FAILURE)
        if manifest_data.get("offline_verified") is not False:
            raise PolicyError("Render bundle manifest must have offline_verified=False.", code=ERROR_POSTCONDITION_FAILURE)
        if manifest_data.get("trusted_html") != canonical_inputs["trusted_html"]:
            raise PolicyError("Render bundle manifest trusted_html mismatch.", code=ERROR_POSTCONDITION_FAILURE)
        m_files = manifest_data.get("files")
        if not isinstance(m_files, dict) or not {"source", "input", "html", "design", "meta", "gallery"} <= set(m_files):
            raise PolicyError("Render bundle manifest is missing required files entries.", code=ERROR_POSTCONDITION_FAILURE)
        for key, entry in m_files.items():
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or not isinstance(entry.get("sha256"), str):
                raise PolicyError(f"Malformed manifest file entry {key!r}.", code=ERROR_POSTCONDITION_FAILURE)
            f_path = _validate_confined_bundle_filepath(
                entry["path"],
                resolved_output_dir,
                f"manifest.files[{key}]",
                code=ERROR_POSTCONDITION_FAILURE,
            )
            if str(f_path) not in verified_outputs or f_path not in disk_bytes_by_path:
                raise PolicyError(
                    f"Manifest entry {key!r} ({f_path}) is missing from declared verified outputs.",
                    code=ERROR_POSTCONDITION_FAILURE,
                )
            f_sha = verified_outputs[str(f_path)]["sha256"]
            if f_sha != entry["sha256"]:
                raise PolicyError(
                    f"Manifest hash mismatch for {key!r}: manifest={entry['sha256']}, disk={f_sha}.",
                    code=ERROR_POSTCONDITION_FAILURE,
                )
        meta_file_path = _validate_confined_bundle_filepath(
            m_files["meta"]["path"],
            resolved_output_dir,
            "manifest.files[meta]",
            code=ERROR_POSTCONDITION_FAILURE,
        )
        meta_text = disk_bytes_by_path[meta_file_path].decode("utf-8")
        try:
            observed_lint = cli.lint_status(meta_text)
        except ModuleNotFoundError as exc:
            raise PolicyBackendError(
                "Postcondition verification of render metadata requires PyYAML."
            ) from exc
        if manifest_data.get("lint_passed") is not observed_lint:
            raise PolicyError(
                f"Manifest lint_passed ({manifest_data.get('lint_passed')!r}) does not match "
                f"meta sidecar lint_passed ({observed_lint!r}).",
                code=ERROR_POSTCONDITION_FAILURE,
            )
        if (resolved_output_dir / SKILLC_DIRNAME).exists():
            raise PolicyError(
                "Policy control directory must not be written inside native render bundle output_dir.",
                code=ERROR_POSTCONDITION_FAILURE,
            )
        independent_checks.append("render_bundle_manifest_verified")

    elif op == "ste.prepare_story_media":
        assert resolved_output_dir is not None
        manifest_path = (resolved_output_dir / "manifest.json").resolve()
        video_index = (resolved_output_dir / "video" / "index.html").resolve()
        if str(manifest_path) not in verified_outputs or str(video_index) not in verified_outputs:
            raise PolicyError(
                "Story media outputs must include manifest.json and video/index.html.",
                code=ERROR_POSTCONDITION_FAILURE,
            )
        manifest_data = loads_json(disk_bytes_by_path[manifest_path].decode("utf-8"))
        if not isinstance(manifest_data, dict) or manifest_data.get("status") != "prepared_not_rendered":
            raise PolicyError(
                "Story media manifest status must be 'prepared_not_rendered'.",
                code=ERROR_POSTCONDITION_FAILURE,
            )
        expected_video_files = {"index.html"}
        for audio_rec in manifest_data.get("audio", []):
            if not isinstance(audio_rec, dict) or not isinstance(audio_rec.get("file"), str):
                raise PolicyError("Malformed audio record in media manifest.", code=ERROR_POSTCONDITION_FAILURE)
            wav_path = _validate_confined_media_audio_relpath(
                audio_rec["file"],
                resolved_output_dir,
                code=ERROR_POSTCONDITION_FAILURE,
            )
            if str(wav_path) not in verified_outputs or wav_path not in disk_bytes_by_path:
                raise PolicyError(
                    f"Media audio {audio_rec['file']!r} is missing from declared verified outputs.",
                    code=ERROR_POSTCONDITION_FAILURE,
                )
            wav_bytes = disk_bytes_by_path[wav_path]
            _validate_pcm_wav(wav_bytes)
            if verified_outputs[str(wav_path)]["sha256"] != audio_rec.get("sha256"):
                raise PolicyError(f"Audio SHA-256 mismatch for {wav_path.name}.", code=ERROR_POSTCONDITION_FAILURE)
            if "bytes" in audio_rec and len(wav_bytes) != audio_rec.get("bytes"):
                raise PolicyError(f"Audio byte length mismatch for {wav_path.name}.", code=ERROR_POSTCONDITION_FAILURE)
            expected_video_files.add(wav_path.name)
        video_dir = resolved_output_dir / "video"
        actual_video_files = {item.name for item in video_dir.iterdir()}
        if actual_video_files != expected_video_files:
            raise PolicyError(
                f"Media video/ directory contains unexpected files: {sorted(actual_video_files - expected_video_files)}",
                code=ERROR_POSTCONDITION_FAILURE,
            )
        independent_checks.append("story_media_composition_verified")

    elif op == "ste.export_bundle":
        assert resolved_output_dir is not None
        exported_collected = _collect_native_bundle_files(resolved_output_dir)
        for _, snap_meta in sorted(pre_snapshots.items()):
            role = snap_meta["role"]
            if role.startswith("bundle:"):
                rel = role.removeprefix("bundle:")
                if rel not in exported_collected:
                    raise PolicyError(
                        f"Exported bundle is missing required payload file {rel!r}.",
                        code=ERROR_POSTCONDITION_FAILURE,
                    )
                exp_file = exported_collected[rel].resolve()
                if str(exp_file) not in verified_outputs or exp_file not in disk_bytes_by_path:
                    raise PolicyError(
                        f"Exported file {rel!r} is missing from declared verified outputs.",
                        code=ERROR_POSTCONDITION_FAILURE,
                    )
                exp_bytes = disk_bytes_by_path[exp_file]
                exp_sha = verified_outputs[str(exp_file)]["sha256"]
                if exp_sha != snap_meta["sha256"] or len(exp_bytes) != snap_meta["size"]:
                    raise PolicyError(
                        f"Exported file {rel!r} does not match verified input bundle bytes.",
                        code=ERROR_POSTCONDITION_FAILURE,
                    )
        independent_checks.append("export_bundle_immutability_verified")

    # Normalize caller checks + independent checks
    raw_checks = post_facts.get("checks", [])
    caller_checks: list[str] = []
    if isinstance(raw_checks, dict):
        for k, v in sorted(raw_checks.items()):
            if not isinstance(k, str) or not k.strip() or v is not True:
                raise PolicyError(
                    f"Post-validation check {k!r} did not pass (value={v!r}).",
                    code=ERROR_POSTCONDITION_FAILURE,
                )
            caller_checks.append(k)
    elif isinstance(raw_checks, list):
        for item in raw_checks:
            if not isinstance(item, str) or not item.strip():
                raise PolicyError("Check labels must be non-empty strings.", code=ERROR_POSTCONDITION_FAILURE)
            caller_checks.append(item)
    else:
        raise PolicyError("post_facts.checks must be a list of strings or dict of booleans.", code=ERROR_POSTCONDITION_FAILURE)

    merged_checks = list(dict.fromkeys([*independent_checks, *caller_checks]))

    raw_warnings = post_facts.get("warnings", [])
    if not isinstance(raw_warnings, list) or not all(isinstance(w, str) for w in raw_warnings):
        raise PolicyError("post_facts.warnings must be a list of strings.", code=ERROR_POSTCONDITION_FAILURE)

    return {
        "native_status": status,
        "status": status,
        "outputs": verified_outputs,
        "checks": merged_checks,
        "warnings": list(raw_warnings),
    }


def _validate_state_dir(raw_state_dir: Any, canonical_inputs: dict[str, Any] | None = None) -> Path:
    _, resolved = _check_safe_path(raw_state_dir, "Policy state_dir")
    _check_not_historical_manual_stage(resolved, "Policy state_dir")
    if canonical_inputs is not None:
        raw_out = canonical_inputs.get("output_root") or canonical_inputs.get("output_dir")
        if raw_out:
            out_dir = Path(raw_out).resolve()
            if resolved == out_dir or resolved.is_relative_to(out_dir) or out_dir.is_relative_to(resolved):
                raise PolicyError(
                    "Policy state_dir must stay outside artifact output directories.",
                    code=ERROR_POLICY_REFUSAL,
                )
    return resolved


def _guard_state_path(state_dir: Path) -> Path:
    return state_dir / SKILLC_DIRNAME / GUARD_STATE_FILE


def _receipt_path(state_dir: Path) -> Path:
    return state_dir / SKILLC_DIRNAME / RECEIPT_FILE


def _save_json_atomic(target: Path, data: dict[str, Any]) -> None:
    _restrict_control_dir(target.parent)
    tmp = target.with_name(f"{target.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    if os.name == "posix":
        os.chmod(tmp, 0o600)
    os.replace(tmp, target)


def _load_guard_state(state_dir: Path) -> dict[str, Any]:
    path = _guard_state_path(state_dir)
    if not path.is_file():
        raise PolicyError(
            f"Policy state directory has no active guard_pre record: {state_dir}",
            code=ERROR_POLICY_REFUSAL,
        )
    try:
        record = loads_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PolicyError(f"Corrupted policy guard state in {path}: {exc}", code=ERROR_POLICY_REFUSAL) from exc
    if not isinstance(record, dict) or record.get("schema") != "ste-promax.guard-state.v1":
        raise PolicyError("Unsupported or corrupted policy guard state record.", code=ERROR_POLICY_REFUSAL)
    return record


def _guard_pre_inprocess(payload: dict[str, Any]) -> dict[str, Any]:
    op = payload.get("op")
    raw_inputs = payload.get("inputs")
    if "state_dir" not in payload:
        raise PolicyError("guard_pre payload requires state_dir.", code=ERROR_INVALID_INPUT)

    pre_info = _validate_and_snapshot_inputs(op, raw_inputs)
    state_dir = _validate_state_dir(payload["state_dir"], pre_info["canonical_inputs"])
    guard_state_file = _guard_state_path(state_dir)
    if guard_state_file.exists() or (state_dir / SKILLC_DIRNAME / STATE_FILE).exists():
        raise PolicyError(
            f"Policy state_dir has already been used and cannot be replayed: {state_dir}",
            code=ERROR_POLICY_REFUSAL,
        )

    static_report = _check_static_plan_inprocess()
    monitor = _open_monitor_inprocess(state_dir)
    if monitor.state.actions or monitor.state.facts:
        raise PolicyError(
            "SkillC monitor state is non-empty on guard_pre; refusing state reuse.",
            code=ERROR_POLICY_REFUSAL,
        )

    pre_meta = {
        "step": "validate_preconditions",
        "op": str(op),
        "source_closure_sha256": pre_info["source_closure_sha256"],
    }
    _run_monitored_pre_inprocess(monitor, "validate_preconditions", pre_meta, ROLE_VALIDATOR)
    _run_monitored_post_inprocess(
        monitor,
        "validate_preconditions",
        pre_meta,
        {"status": "preconditions_verified"},
        ROLE_VALIDATOR,
        expected_fact="preconditions_verified",
    )

    exec_meta = {
        "step": "execute_operation",
        "op": str(op),
        "source_closure_sha256": pre_info["source_closure_sha256"],
    }
    _run_monitored_pre_inprocess(monitor, "execute_operation", exec_meta, ROLE_EXECUTOR)
    monitor.save()

    guard_state = {
        "schema": "ste-promax.guard-state.v1",
        "phase": "pre",
        "op": op,
        "state_dir": str(state_dir),
        "started_at": _utc_now(),
        "plan_digest": static_report["pack_digest"],
        "static_check": static_report,
        "raw_inputs_sha256": pre_info["raw_inputs_sha256"],
        "canonical_inputs": pre_info["canonical_inputs"],
        "source_closure_sha256": pre_info["source_closure_sha256"],
        "pre_snapshots": pre_info["pre_snapshots"],
    }
    _save_json_atomic(guard_state_file, guard_state)

    return {
        "phase": "pre",
        "op": op,
        "state_dir": str(state_dir),
        "allowed": True,
        "plan_digest": static_report["pack_digest"],
        "source_closure_sha256": pre_info["source_closure_sha256"],
    }


def _guard_fail_inprocess(payload: dict[str, Any]) -> dict[str, Any]:
    op = payload.get("op")
    if not isinstance(op, str) or op not in SUPPORTED_OPERATIONS:
        raise PolicyError(f"Unsupported guarded operation: {op!r}", code=ERROR_UNSUPPORTED_OPERATION)
    if "state_dir" not in payload:
        raise PolicyError("guard_fail payload requires state_dir.", code=ERROR_INVALID_INPUT)
    state_dir = _validate_state_dir(payload["state_dir"])
    guard_state = _load_guard_state(state_dir)
    if guard_state.get("op") != op:
        raise PolicyError(
            f"Operation mismatch in guard_fail: expected {guard_state.get('op')!r}, got {op!r}.",
            code=ERROR_POLICY_REFUSAL,
        )
    if guard_state.get("phase") != "pre":
        raise PolicyError(
            f"Cannot transition to guard_fail from phase {guard_state.get('phase')!r}.",
            code=ERROR_POLICY_REFUSAL,
        )
    if "inputs" in payload and payload["inputs"] is not None:
        supplied_sha = _sha256_text(_canonical_json(_serialize_inputs(payload["inputs"])))
        if supplied_sha != guard_state.get("raw_inputs_sha256"):
            raise PolicyError(
                "Operation inputs in guard_fail do not match bound guard_pre inputs.",
                code=ERROR_POLICY_REFUSAL,
            )

    error_message = str(payload.get("error") or "operation failed")
    partial_effects = payload.get("partial_effects")
    if not isinstance(partial_effects, dict):
        partial_effects = {}

    monitor = _open_monitor_inprocess(state_dir)
    exec_meta = {
        "step": "execute_operation",
        "op": op,
        "source_closure_sha256": guard_state["source_closure_sha256"],
    }
    monitor.post_action("execute_operation", exec_meta, {"error": error_message}, role=ROLE_EXECUTOR)
    monitor.save()

    failure_receipt = {
        "schema": "ste-promax.automatic-receipt.v1",
        "phase": "failed",
        "op": op,
        "verdict": "DENY",
        "plan_digest": guard_state["plan_digest"],
        "source_closure_sha256": guard_state["source_closure_sha256"],
        "outputs": {},
        "partial_effects": partial_effects,
        "checks": ["pre_inputs_verified"],
        "warnings": [error_message],
        "error": error_message,
        "authority_model": "automatic-local-policy",
        "state_dir": str(state_dir),
        "recorded_at": _utc_now(),
        "skillc": {
            "static_check": guard_state["static_check"],
            "facts": list(monitor.state.facts),
            "actions": list(monitor.state.actions),
            "goal_satisfied": "postconditions_verified" in monitor.state.facts,
        },
    }
    guard_state["phase"] = "failed"
    guard_state["failed_at"] = failure_receipt["recorded_at"]
    guard_state["error"] = error_message
    guard_state["partial_effects"] = partial_effects
    _save_json_atomic(_guard_state_path(state_dir), guard_state)
    _save_json_atomic(_receipt_path(state_dir), failure_receipt)
    return failure_receipt


def _guard_post_inprocess(payload: dict[str, Any]) -> dict[str, Any]:
    op = payload.get("op")
    if not isinstance(op, str) or op not in SUPPORTED_OPERATIONS:
        raise PolicyError(f"Unsupported guarded operation: {op!r}", code=ERROR_UNSUPPORTED_OPERATION)
    if "state_dir" not in payload:
        raise PolicyError("guard_post payload requires state_dir.", code=ERROR_INVALID_INPUT)
    raw_inputs = payload.get("inputs")
    if not isinstance(raw_inputs, dict):
        raise PolicyError("guard_post payload requires inputs object.", code=ERROR_INVALID_INPUT)

    state_dir = _validate_state_dir(payload["state_dir"])
    guard_state = _load_guard_state(state_dir)

    if guard_state.get("phase") != "pre":
        raise PolicyError(
            f"Replay or invalid phase transition in guard_post: current phase is {guard_state.get('phase')!r}, expected 'pre'.",
            code=ERROR_POLICY_REFUSAL,
        )
    if guard_state.get("op") != op:
        raise PolicyError(
            f"Operation mismatch between guard_pre ({guard_state.get('op')!r}) and guard_post ({op!r}).",
            code=ERROR_POLICY_REFUSAL,
        )

    supplied_inputs_sha = _sha256_text(_canonical_json(_serialize_inputs(raw_inputs)))
    if supplied_inputs_sha != guard_state.get("raw_inputs_sha256"):
        raise PolicyError(
            "Operation inputs in guard_post do not match the inputs bound in guard_pre.",
            code=ERROR_POLICY_REFUSAL,
        )

    monitor = _open_monitor_inprocess(state_dir)
    if monitor.state.facts != ["preconditions_verified"] or monitor.state.actions != ["validate_preconditions"]:
        raise PolicyError(
            "SkillC monitor state was tampered with or does not match guard_pre transition.",
            code=ERROR_POLICY_REFUSAL,
        )

    source_closure_sha256 = str(guard_state["source_closure_sha256"])
    exec_meta = {
        "step": "execute_operation",
        "op": op,
        "source_closure_sha256": source_closure_sha256,
    }
    _run_monitored_post_inprocess(
        monitor,
        "execute_operation",
        exec_meta,
        {"status": "operation_executed"},
        ROLE_EXECUTOR,
        expected_fact="operation_executed",
    )

    post_meta = {
        "step": "verify_postconditions",
        "op": op,
        "source_closure_sha256": source_closure_sha256,
    }
    _run_monitored_pre_inprocess(monitor, "verify_postconditions", post_meta, ROLE_VALIDATOR)

    post_facts = payload.get("post_facts")
    try:
        verified = _verify_operation_postconditions(
            op,
            guard_state["canonical_inputs"],
            guard_state["pre_snapshots"],
            post_facts,
        )
    except Exception as exc:
        err_msg = f"{type(exc).__name__}: {exc}"
        monitor.post_action("verify_postconditions", post_meta, {"error": err_msg}, role=ROLE_VALIDATOR)
        monitor.save()
        partial = _collect_partial_effects(guard_state["canonical_inputs"])
        failure_receipt = {
            "schema": "ste-promax.automatic-receipt.v1",
            "phase": "failed",
            "op": op,
            "verdict": "DENY",
            "plan_digest": guard_state["plan_digest"],
            "source_closure_sha256": source_closure_sha256,
            "outputs": {},
            "partial_effects": partial,
            "checks": ["pre_inputs_verified"],
            "warnings": [err_msg],
            "error": str(exc),
            "authority_model": "automatic-local-policy",
            "state_dir": str(state_dir),
            "recorded_at": _utc_now(),
            "skillc": {
                "static_check": guard_state["static_check"],
                "facts": list(monitor.state.facts),
                "actions": list(monitor.state.actions),
                "goal_satisfied": "postconditions_verified" in monitor.state.facts,
            },
        }
        guard_state["phase"] = "failed"
        guard_state["failed_at"] = failure_receipt["recorded_at"]
        guard_state["error"] = str(exc)
        guard_state["partial_effects"] = partial
        _save_json_atomic(_guard_state_path(state_dir), guard_state)
        _save_json_atomic(_receipt_path(state_dir), failure_receipt)
        if isinstance(exc, PolicyError):
            exc.receipt = failure_receipt
            raise
        raise PolicyError(str(exc), code=ERROR_POSTCONDITION_FAILURE, receipt=failure_receipt) from exc

    _run_monitored_post_inprocess(
        monitor,
        "verify_postconditions",
        post_meta,
        {"status": "postconditions_verified"},
        ROLE_VALIDATOR,
        expected_fact="postconditions_verified",
    )

    nested_obs = post_facts.get("nested_operations", []) if isinstance(post_facts, dict) else []
    receipt: dict[str, Any] = {
        "schema": "ste-promax.automatic-receipt.v1",
        "phase": "post",
        "op": op,
        "verdict": "ALLOW",
        "plan_digest": guard_state["plan_digest"],
        "source_closure_sha256": source_closure_sha256,
        "outputs": verified["outputs"],
        "checks": verified["checks"],
        "native_status": verified["native_status"],
        "warnings": verified["warnings"],
        "authority_model": "automatic-local-policy",
        "state_dir": str(state_dir),
        "recorded_at": _utc_now(),
        "nested_operations": list(nested_obs) if isinstance(nested_obs, list) else [],
        "skillc": {
            "static_check": guard_state["static_check"],
            "facts": list(monitor.state.facts),
            "actions": list(monitor.state.actions),
            "goal_satisfied": "postconditions_verified" in monitor.state.facts,
        },
    }
    guard_state["phase"] = "post"
    guard_state["completed_at"] = receipt["recorded_at"]
    _save_json_atomic(_guard_state_path(state_dir), guard_state)
    _save_json_atomic(_receipt_path(state_dir), receipt)
    return receipt


def _guard_status_inprocess(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    _ = payload
    static_report = _check_static_plan_inprocess()
    return {
        "schema": "ste-promax.policy-status.v1",
        "phase": "status",
        "available": True,
        "authority_model": "automatic-local-policy",
        "manual_approval_required": False,
        "supported_operations": sorted(SUPPORTED_OPERATIONS),
        "plan_digest": static_report["pack_digest"],
        "static_check": static_report,
    }


def _dispatch_inprocess_action(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    if action == "guard_pre":
        return _guard_pre_inprocess(payload)
    if action == "guard_post":
        return _guard_post_inprocess(payload)
    if action == "guard_fail":
        return _guard_fail_inprocess(payload)
    if action == "guard_status":
        return _guard_status_inprocess(payload)
    raise PolicyError(f"Unknown worker action: {action!r}", code=ERROR_UNSUPPORTED_OPERATION)


def _collect_partial_effects(inputs: dict[str, Any], result: Any = None) -> dict[str, Any]:
    partial_files: dict[str, dict[str, Any]] = {}
    out_raw = inputs.get("output_root") or inputs.get("output_dir") or inputs.get("output")
    if isinstance(out_raw, (str, Path)):
        out_path = Path(out_raw)
        if out_path.is_dir() and not out_path.is_symlink():
            for child in sorted(out_path.rglob("*")):
                try:
                    info = child.lstat()
                    if not _is_link_or_reparse(info) and stat.S_ISREG(info.st_mode):
                        raw = child.read_bytes()
                        partial_files[str(child.resolve())] = {
                            "sha256": _sha256_bytes(raw),
                            "size": len(raw),
                        }
                except OSError:
                    continue
    for t_raw in inputs.get("target_paths", []) or []:
        if isinstance(t_raw, (str, Path)):
            t_path = Path(t_raw)
            try:
                if t_path.is_file() and not t_path.is_symlink():
                    raw = t_path.read_bytes()
                    partial_files[str(t_path.resolve())] = {
                        "sha256": _sha256_bytes(raw),
                        "size": len(raw),
                    }
            except OSError:
                continue
    summary: dict[str, Any] = {"files": partial_files}
    if isinstance(result, dict) and "status" in result:
        summary["native_status"] = result.get("status")
    return summary


def _is_genuinely_failed_native_result(result: Any) -> bool:
    return (
        isinstance(result, dict)
        and result.get("status") in {"failed", "error", "partial_failure_not_rendered"}
    )


def _allocate_state_dir(op: str) -> Path:
    state_root = resolve_state_root()
    runs_dir = state_root / "runs"
    _restrict_control_dir(runs_dir)
    slug = op.replace(".", "-")
    state_dir = runs_dir / f"{_utc_compact()}-{slug}-{secrets.token_hex(8)}"
    _restrict_control_dir(state_dir)
    return state_dir


def get_policy_status() -> dict[str, Any]:
    """Return current automatic SkillC policy availability, runtime config, and static plan status."""
    cfg_path = resolve_runtime_config_path()
    cfg_loaded = False
    cfg_data: dict[str, Any] | None = None
    try:
        cfg_data = load_runtime_config()
        cfg_loaded = cfg_data is not None
    except PolicyError as exc:
        return {
            "schema": "ste-promax.policy-status.v1",
            "available": False,
            "mode": "unavailable",
            "authority_model": "automatic-local-policy",
            "manual_approval_required": False,
            "supported_operations": sorted(SUPPORTED_OPERATIONS),
            "runtime_config_path": str(cfg_path),
            "runtime_config_loaded": False,
            "state_root": str(default_runtime_config_path().parent / "state"),
            "plan_digest": None,
            "error": {"code": exc.code, "message": exc.message},
        }

    state_root = resolve_state_root(cfg_data)
    mode = "inprocess" if _has_inprocess_skillc() else "worker"
    try:
        status_res = _invoke_skillc_action("guard_status", {})
        return {
            **status_res,
            "available": True,
            "mode": mode,
            "runtime_config_path": str(cfg_path),
            "runtime_config_loaded": cfg_loaded,
            "state_root": str(state_root),
            "error": None,
        }
    except PolicyError as exc:
        return {
            "schema": "ste-promax.policy-status.v1",
            "available": False,
            "mode": "unavailable",
            "authority_model": "automatic-local-policy",
            "manual_approval_required": False,
            "supported_operations": sorted(SUPPORTED_OPERATIONS),
            "runtime_config_path": str(cfg_path),
            "runtime_config_loaded": cfg_loaded,
            "state_root": str(state_root),
            "plan_digest": None,
            "error": {"code": exc.code, "message": exc.message},
        }


def run_guarded_operation(
    op: str,
    inputs: dict[str, Any],
    effect_fn: Callable[[], T],
    *,
    validate_result: Callable[[T], dict[str, Any]] | None = None,
) -> T:
    """Execute `effect_fn` under automatic SkillC pre/post policy enforcement and return `T` unchanged."""
    if not isinstance(op, str) or op not in SUPPORTED_OPERATIONS:
        raise PolicyError(f"Unsupported guarded operation: {op!r}", code=ERROR_UNSUPPORTED_OPERATION)
    if not isinstance(inputs, dict):
        raise PolicyError("Operation inputs must be a dict.", code=ERROR_INVALID_INPUT)
    if not callable(effect_fn):
        raise PolicyError("effect_fn must be callable.", code=ERROR_INVALID_INPUT)
    if validate_result is not None and not callable(validate_result):
        raise PolicyError("validate_result must be callable when provided.", code=ERROR_INVALID_INPUT)

    active_stack = _ACTIVE_GUARD_STACK.get()
    if active_stack:
        parent_frame = active_stack[-1]
        permitted = PERMITTED_NESTED_OPERATIONS.get(parent_frame.op, frozenset())
        if op not in permitted:
            raise PolicyError(
                f"Operation {op!r} is not permitted as a nested call inside {parent_frame.op!r}; "
                "unexpected nested operations do not inherit a policy bypass.",
                code=ERROR_POLICY_REFUSAL,
            )
        # Permitted nested operation: validate inputs AND enforce parent bounds before effect.
        pre_info = _validate_and_snapshot_inputs(op, inputs)
        _enforce_parent_bounds_on_child(parent_frame.canonical_inputs, pre_info["canonical_inputs"])
        child_frame = _ActiveGuardFrame(
            op=op,
            state_dir=parent_frame.state_dir,
            plan_digest=parent_frame.plan_digest,
            source_closure_sha256=pre_info["source_closure_sha256"],
            canonical_inputs=pre_info["canonical_inputs"],
        )
        token = _ACTIVE_GUARD_STACK.set((*active_stack, child_frame))
        try:
            result = effect_fn()
            post_facts = (
                validate_result(result)
                if validate_result is not None
                else _default_validate_result(op, inputs, result)
            )
            verified = _verify_operation_postconditions(
                op,
                pre_info["canonical_inputs"],
                pre_info["pre_snapshots"],
                post_facts,
                result=result,
            )
        except Exception as exc:
            parent_frame.nested_failures.append(f"{op}: {type(exc).__name__}: {exc}")
            raise
        finally:
            _ACTIVE_GUARD_STACK.reset(token)

        parent_frame.nested_observations.append({
            "op": op,
            "source_closure_sha256": pre_info["source_closure_sha256"],
            "outputs": verified["outputs"],
            "checks": verified["checks"],
            "warnings": verified["warnings"],
        })
        return result

    # Top-level guarded operation
    serialized_inputs = _serialize_inputs(inputs)
    parent_pre_info = _validate_and_snapshot_inputs(op, serialized_inputs)
    state_dir = _allocate_state_dir(op)
    pre_res = _invoke_skillc_action(
        "guard_pre",
        {
            "op": op,
            "state_dir": str(state_dir),
            "inputs": serialized_inputs,
        },
    )

    frame = _ActiveGuardFrame(
        op=op,
        state_dir=state_dir,
        plan_digest=str(pre_res["plan_digest"]),
        source_closure_sha256=str(pre_res["source_closure_sha256"]),
        canonical_inputs=parent_pre_info["canonical_inputs"],
    )
    token = _ACTIVE_GUARD_STACK.set((frame,))
    try:
        try:
            result = effect_fn()
        except Exception as exc:
            partial = _collect_partial_effects(serialized_inputs)
            try:
                fail_receipt = _invoke_skillc_action(
                    "guard_fail",
                    {
                        "op": op,
                        "state_dir": str(state_dir),
                        "inputs": serialized_inputs,
                        "error": f"{type(exc).__name__}: {exc}",
                        "partial_effects": partial,
                    },
                )
                _set_last_receipt(fail_receipt)
            except Exception:
                pass
            raise

        try:
            post_facts = (
                validate_result(result)
                if validate_result is not None
                else _default_validate_result(op, serialized_inputs, result)
            )
            if not isinstance(post_facts, dict):
                raise PolicyError(
                    "validate_result must return a dict.",
                    code=ERROR_POSTCONDITION_FAILURE,
                )
            post_facts = dict(post_facts)
            if frame.nested_observations:
                post_facts["nested_operations"] = list(frame.nested_observations)
        except Exception as val_exc:
            partial = _collect_partial_effects(serialized_inputs, result)
            fail_receipt = None
            try:
                fail_receipt = _invoke_skillc_action(
                    "guard_fail",
                    {
                        "op": op,
                        "state_dir": str(state_dir),
                        "inputs": serialized_inputs,
                        "error": f"{type(val_exc).__name__}: {val_exc}",
                        "partial_effects": partial,
                    },
                )
                _set_last_receipt(fail_receipt)
            except Exception:
                pass
            if isinstance(val_exc, PolicyError):
                val_exc.partial_result = result if _is_genuinely_failed_native_result(result) else None
                val_exc.receipt = fail_receipt
            raise

        try:
            receipt = _invoke_skillc_action(
                "guard_post",
                {
                    "op": op,
                    "state_dir": str(state_dir),
                    "inputs": serialized_inputs,
                    "post_facts": post_facts,
                },
            )
        except PolicyError as post_exc:
            post_exc.partial_result = result if _is_genuinely_failed_native_result(result) else None
            if post_exc.receipt is not None:
                _set_last_receipt(post_exc.receipt)
            elif _receipt_path(state_dir).is_file():
                try:
                    _set_last_receipt(loads_json(_receipt_path(state_dir).read_text(encoding="utf-8")))
                except Exception:
                    pass
            raise
    finally:
        _ACTIVE_GUARD_STACK.reset(token)

    _set_last_receipt(receipt)
    return result


def export_bundle(
    input_dir: str | Path,
    output_dir: str | Path,
    *,
    evidence_root: str | Path | None = None,
    evidence: list[str] | None = None,
) -> dict[str, Any]:
    """Automatically verify a fresh native STE-Pro-Max bundle and copy it to a new destination."""
    _require_nonempty_arg(input_dir, "input-dir")
    _require_nonempty_arg(output_dir, "output-dir")
    resolved_input = _safe_existing_dir(input_dir, "Input bundle directory")
    _reject_if_legacy_manual_stage(resolved_input, "Input bundle directory")
    resolved_output = _safe_export_dir_for_create(output_dir, "Export destination")
    resolved_ev_root = (
        _safe_existing_dir(evidence_root, "Evidence root") if evidence_root is not None else None
    )
    evidence_list = [str(item) for item in (evidence or [])]

    manifest, snapshots, payload_records, ev_records, source_closure_digest = (
        _validate_native_bundle_for_export(
            resolved_input,
            explicit_evidence_root=resolved_ev_root,
            explicit_evidence_files=evidence_list,
        )
    )

    op_inputs: dict[str, Any] = {
        "caller_kind": "native",
        "workspace_root": str(Path.cwd().resolve()),
        "input_dir": str(resolved_input),
        "output_root": str(resolved_output),
        "source_paths": [str(manifest["source_path"])],
        "source_digest": str(manifest["source_sha256"]),
        "source_kind": "bundle",
        "trusted_html": bool(manifest["trusted_html"]),
    }
    if resolved_ev_root is not None:
        op_inputs["evidence_root"] = str(resolved_ev_root)
    if evidence_list:
        op_inputs["evidence_paths"] = evidence_list

    def _copy_verified_bundle() -> dict[str, Any]:
        resolved_output.mkdir(parents=True, exist_ok=False)
        for ancestor in (resolved_output, *resolved_output.parents):
            if _is_link_or_reparse(ancestor.lstat()):
                raise PolicyError(
                    f"Unsafe link detected in export directory ancestry: {ancestor}",
                    code=ERROR_POSTCONDITION_FAILURE,
                )
        exported_files: dict[str, dict[str, Any]] = {}
        for rel_path, file_bytes in sorted(snapshots.items()):
            target = resolved_output / Path(rel_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            for parent in (target.parent, *target.parent.parents):
                if parent.is_relative_to(resolved_output) or parent == resolved_output:
                    if _is_link_or_reparse(parent.lstat()):
                        raise PolicyError(
                            f"Unsafe link detected in export directory tree: {parent}",
                            code=ERROR_POSTCONDITION_FAILURE,
                        )
            with target.open("xb") as stream:
                stream.write(file_bytes)
            disk_bytes = target.read_bytes()
            disk_sha = _sha256_bytes(disk_bytes)
            if (
                disk_sha != payload_records[rel_path]["sha256"]
                or len(disk_bytes) != payload_records[rel_path]["size"]
            ):
                raise PolicyError(
                    f"Exported file verification failed for {rel_path}.",
                    code=ERROR_POSTCONDITION_FAILURE,
                )
            exported_files[rel_path] = {
                "path": str(target.resolve()),
                "sha256": disk_sha,
                "size": len(disk_bytes),
            }

        return {
            "schema": "ste-promax.export-result.v1",
            "status": "exported",
            "version": __version__,
            "exported_at": _utc_now(),
            "input_dir": str(resolved_input),
            "output_dir": str(resolved_output),
            "source_path": manifest["source_path"],
            "source_sha256": manifest["source_sha256"],
            "source_closure_sha256": source_closure_digest,
            "trusted_html": bool(manifest["trusted_html"]),
            "lint_passed": True,
            "files": exported_files,
            "evidence_files": [
                {
                    "rel_path": item["rel_path"],
                    "exported_path": str((resolved_output / Path(item["rel_path"])).resolve()),
                    "source_path": item["source_path"],
                    "sha256": item["sha256"],
                    "size": item["size"],
                    "source_ids": list(item.get("source_ids", [])),
                    "explicit": bool(item.get("explicit", False)),
                }
                for item in ev_records
            ],
            "warnings": list(manifest.get("warnings", [])),
            "authority_model": "automatic-local-policy",
        }

    def _validate_export(export_res: dict[str, Any]) -> dict[str, Any]:
        outputs_map = {
            meta["path"]: {"sha256": meta["sha256"], "size": meta["size"]}
            for meta in export_res["files"].values()
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

    result = run_guarded_operation(
        "ste.export_bundle",
        op_inputs,
        _copy_verified_bundle,
        validate_result=_validate_export,
    )
    receipt = get_last_receipt()
    if receipt is not None:
        result["plan_digest"] = receipt.get("plan_digest")
        result["skillc"] = receipt.get("skillc")
    return result


def run_gate_command(args: argparse.Namespace) -> int:
    if args.command == "export":
        in_dir = getattr(args, "input_dir", None) or getattr(args, "stage_dir", None)
        out_dir = getattr(args, "output_dir", None) or getattr(args, "export_dir", None)
        result = export_bundle(
            in_dir,
            out_dir,
            evidence_root=getattr(args, "evidence_root", None),
            evidence=getattr(args, "evidence", None),
        )
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0 if result.get("status") == "exported" else 2
    raise PolicyError(
        f"Unsupported or removed manual gate command: {args.command!r}; "
        "STE-Pro-Max workflows now execute under automatic local policy without stage/approve.",
        code=ERROR_UNSUPPORTED_OPERATION,
    )

"""Write and verify an owned temporary STE-Pro-Max runtime.json for CI or isolated test runs.

Inspects real installed distributions and SkillC module locations without installing
packages or weakening policy checks. Optionally exports STE_SKILLC_RUNTIME_CONFIG to GITHUB_ENV.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SKILLC_COMMIT = "25cc63bf82e968da7d01e204dc6d99879b76c45b"
EXPECTED_RUNTIME_VERSIONS = {
    "Jinja2": "3.1.6",
    "MarkupSafe": "3.0.4",
    "PyYAML": "6.0.3",
    "z3-solver": "5.3.3.0",
}
EXPECTED_MCP_VERSION = "1.30.0"

RUNTIME_PROBE = r"""
import importlib.metadata as m
import json
import sys
from pathlib import Path

extra_root = sys.argv[1]
if extra_root:
    root_path = Path(extra_root).resolve(strict=True)
    candidate = root_path / "src" if (root_path / "src" / "skillc" / "__init__.py").is_file() else root_path
    sys.path.insert(0, str(candidate))

import jinja2
import markupsafe
import yaml
import z3
import skillc
from skillc.checker import check
from skillc.frontend.ce import parse_ce_detailed

plan = (
    "Skill `ci-runtime-self-check`.\n"
    "Roles: `Engine`.\n"
    "Tool `finish` (owner `Engine`): adds `done`.\n"
    "Initially true: none.\n"
    "Goal: `done`.\n"
    "Protocol:\n"
    "  - `Engine` uses `finish`.\n"
)
verdict = check(parse_ce_detailed(plan).pack)
if verdict.label != "ACHIEVABLE" or verdict.protocol != "WELL_TYPED" or not verdict.admissible:
    raise RuntimeError(f"Unexpected SkillC self-check verdict: {verdict}")

skillc_init = Path(skillc.__file__).resolve(strict=True)
skillc_root = skillc_init.parents[1]
versions = {
    name: m.version(name)
    for name in ("Jinja2", "MarkupSafe", "PyYAML", "z3-solver")
}
try:
    skillc_dist_version = m.version("skillc")
except m.PackageNotFoundError:
    skillc_dist_version = None

print(json.dumps({
    "python": sys.executable,
    "skillc_root": str(skillc_root),
    "skillc_version": skillc_dist_version,
    "versions": versions,
    "verdict": verdict.label,
    "protocol": verdict.protocol,
}))
"""

MCP_PROBE = r"""
import importlib.metadata as m
import json
import sys
from mcp.server.fastmcp import FastMCP

assert FastMCP is not None
print(json.dumps({
    "mcp_python": sys.executable,
    "mcp_version": m.version("mcp"),
}))
"""


def _canonical_executable(raw: str | Path) -> Path:
    path = Path(raw).expanduser().absolute()
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size == 0:
        raise ValueError(f"Interpreter must resolve to a non-empty file: {path}")
    return path.parent.resolve(strict=True) / path.name


def _run_probe(python_exe: Path, code: str, *extra_args: str) -> dict[str, Any]:
    proc = subprocess.run(
        [str(python_exe), "-I", "-B", "-c", code, *extra_args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        shell=False,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise ValueError(f"Interpreter probe failed ({python_exe}): {detail}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def configure_ci_runtime(
    *,
    runtime_dir: str | Path,
    ste_root: str | Path = ROOT,
    python_exe: str | Path | None = None,
    mcp_python_exe: str | Path | None = None,
    skillc_root: str | Path | None = None,
    skillc_commit: str = SKILLC_COMMIT,
    github_env_file: str | Path | None = None,
) -> dict[str, Any]:
    resolved_ste_root = Path(ste_root).expanduser().resolve(strict=True)
    if not (resolved_ste_root / "ste_promax" / "__init__.py").is_file():
        raise ValueError(f"ste_root does not contain ste_promax/__init__.py: {resolved_ste_root}")

    target_dir = Path(runtime_dir).expanduser().absolute()
    if ".." in target_dir.parts:
        raise ValueError(f"runtime_dir must not contain '..': {target_dir}")
    target_parent = target_dir.parent
    target_parent.mkdir(parents=True, exist_ok=True)
    resolved_target = target_parent.resolve(strict=True) / target_dir.name
    if resolved_target.exists() or resolved_target.is_symlink():
        raise ValueError(f"runtime_dir must be a new directory: {resolved_target}")
    if (
        resolved_target == resolved_ste_root
        or resolved_target.is_relative_to(resolved_ste_root)
        or resolved_ste_root.is_relative_to(resolved_target)
    ):
        raise ValueError(
            f"runtime_dir must reside outside the STE repository checkout ({resolved_ste_root}): "
            f"{resolved_target}"
        )

    py_path = _canonical_executable(python_exe or sys.executable)
    mcp_py_path = _canonical_executable(mcp_python_exe or py_path)

    explicit_skillc = ""
    if skillc_root is not None and str(skillc_root).strip():
        explicit_skillc = str(Path(skillc_root).expanduser().resolve(strict=True))

    runtime_info = _run_probe(py_path, RUNTIME_PROBE, explicit_skillc)
    observed_versions = runtime_info["versions"]
    for pkg_name, expected_ver in EXPECTED_RUNTIME_VERSIONS.items():
        actual_ver = observed_versions.get(pkg_name)
        if actual_ver != expected_ver:
            raise ValueError(
                f"Expected {pkg_name}=={expected_ver} in {py_path}, got {actual_ver!r}."
            )

    mcp_info = _run_probe(mcp_py_path, MCP_PROBE)
    actual_mcp_version = mcp_info["mcp_version"]
    if actual_mcp_version != EXPECTED_MCP_VERSION:
        raise ValueError(
            f"Expected mcp=={EXPECTED_MCP_VERSION} in {mcp_py_path}, got {actual_mcp_version!r}."
        )

    resolved_skillc_root = Path(runtime_info["skillc_root"]).resolve(strict=True)
    if not (
        (resolved_skillc_root / "skillc" / "__init__.py").is_file()
        or (resolved_skillc_root / "src" / "skillc" / "__init__.py").is_file()
    ):
        raise ValueError(f"Resolved skillc_root does not contain skillc package: {resolved_skillc_root}")

    if not isinstance(skillc_commit, str) or not skillc_commit.strip():
        raise ValueError("skillc_commit must be a non-empty string.")

    resolved_target.mkdir(parents=False, exist_ok=False)
    state_root = resolved_target / "state"
    state_root.mkdir(mode=0o700, exist_ok=False)

    versions_map = {
        **observed_versions,
        "mcp": actual_mcp_version,
    }
    if runtime_info.get("skillc_version"):
        versions_map["skillc"] = runtime_info["skillc_version"]

    runtime_config = {
        "schema": "ste-promax.runtime.v1",
        "managed_by": "ste-promax",
        "status": "ready",
        "python": str(py_path),
        "mcp_python": str(mcp_py_path),
        "mcp_version": actual_mcp_version,
        "skillc_root": str(resolved_skillc_root),
        "ste_root": str(resolved_ste_root),
        "state_root": str(state_root),
        "skillc_commit": skillc_commit.strip(),
        "versions": versions_map,
    }

    runtime_json_path = resolved_target / "runtime.json"
    with runtime_json_path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(runtime_config, stream, ensure_ascii=False, indent=2)
        stream.write("\n")

    # Verify with STE-Pro-Max's own runtime loader and worker status check.
    verify_code = (
        "import json, os, sys; "
        "sys.path.insert(0, sys.argv[1]); "
        "os.environ['STE_SKILLC_RUNTIME_CONFIG'] = sys.argv[2]; "
        "from ste_promax.policy_runtime import load_runtime_config; "
        "from ste_promax.gate import get_policy_status; "
        "from integrations.mcp.operations import resolve_mcp_python; "
        "cfg = load_runtime_config(); "
        "st = get_policy_status(); "
        "mcp_py = resolve_mcp_python(probe_mcp=True); "
        "assert st.get('available') is True, st; "
        "assert mcp_py is not None; "
        "print(json.dumps({'available': st['available'], 'mode': st['mode'], 'mcp_python': str(mcp_py)}))"
    )
    verify_info = _run_probe(py_path, verify_code, str(resolved_ste_root), str(runtime_json_path))

    if github_env_file is not None and str(github_env_file).strip():
        env_path = Path(github_env_file).expanduser().resolve()
        with env_path.open("a", encoding="utf-8", newline="\n") as env_stream:
            env_stream.write(f"STE_SKILLC_RUNTIME_CONFIG={runtime_json_path}\n")

    return {
        "status": "configured",
        "runtime_config_path": str(runtime_json_path),
        "runtime_config": runtime_config,
        "verification": verify_info,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runtime-dir",
        required=True,
        help="New directory outside the repository checkout where runtime.json and state/ will be written.",
    )
    parser.add_argument("--ste-root", default=str(ROOT), help="Path to STE-Pro-Max checkout.")
    parser.add_argument(
        "--python",
        default=None,
        help="SkillC/renderer Python interpreter (defaults to sys.executable).",
    )
    parser.add_argument("--mcp-python", default=None, help="MCP Python interpreter (defaults to --python).")
    parser.add_argument(
        "--skillc-root",
        default=None,
        help="Optional SkillC source root if not installed in site-packages.",
    )
    parser.add_argument("--skillc-commit", default=SKILLC_COMMIT, help="Pinned SkillC commit hash.")
    parser.add_argument("--github-env", default=None, help="Explicit GITHUB_ENV file path.")
    parser.add_argument(
        "--write-github-env",
        action="store_true",
        help="Append STE_SKILLC_RUNTIME_CONFIG to the GITHUB_ENV file when present.",
    )
    args = parser.parse_args(argv)
    gh_env = args.github_env or (os.environ.get("GITHUB_ENV", "") if args.write_github_env else None)
    try:
        report = configure_ci_runtime(
            runtime_dir=args.runtime_dir,
            ste_root=args.ste_root,
            python_exe=args.python,
            mcp_python_exe=args.mcp_python,
            skillc_root=args.skillc_root,
            skillc_commit=args.skillc_commit,
            github_env_file=gh_env,
        )
    except Exception as exc:
        print(f"Error configuring CI runtime: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

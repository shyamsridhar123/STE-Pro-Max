"""Provision an owned SkillC runtime from hash-checked installed distributions.

This offline developer installer never downloads packages, repairs an existing
environment, changes global Python, or copies files not listed in package RECORDs.
Run without --apply to inspect the exact plan first.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import zipfile

SKILLC_COMMIT = "25cc63bf82e968da7d01e204dc6d99879b76c45b"
VERSIONS = {"Jinja2": "3.1.6", "MarkupSafe": "3.0.4", "PyYAML": "6.0.3", "z3-solver": "5.3.3.0"}
PROBE = r'''
import base64, hashlib, importlib.metadata as m, json, sys, sysconfig
from pathlib import Path
rows = []
for name in sys.argv[1:]:
    d = m.distribution(name)
    entries = []
    for item in d.files or []:
        source = Path(d.locate_file(item)).resolve(strict=True)
        if not source.is_relative_to(Path(sys.prefix).resolve()) or not source.is_file():
            raise ValueError(f"Distribution entry escapes its interpreter: {item}")
        raw = source.read_bytes()
        if item.hash:
            digest = hashlib.new(item.hash.mode, raw).digest()
            actual = base64.urlsafe_b64encode(digest).decode().rstrip('=')
            if actual != item.hash.value:
                raise ValueError(f"Installed RECORD hash mismatch: {name}/{item}")
        elif not str(item).endswith('.dist-info/RECORD'):
            raise ValueError(f"Unexpected unhashed distribution entry: {name}/{item}")
        entries.append({'relative': str(item), 'source': str(source),
                        'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)})
    if not entries:
        raise ValueError(f"No installed RECORD entries: {name}")
    rows.append({'name': name, 'version': d.version,
                 'tags': [line[5:].strip() for line in (d.read_text('WHEEL') or '').splitlines()
                          if line.startswith('Tag: ')], 'files': entries})
print(json.dumps({'python': sys.executable, 'version': list(sys.version_info[:2]),
                  'implementation': sys.implementation.name,
                  'platform': sysconfig.get_platform().replace('-', '_').replace('.', '_'),
                  'distributions': rows}))
'''
SELF_CHECK = r'''
import importlib.metadata as m, json, sys
from pathlib import Path
import jinja2, markupsafe, yaml, z3, skillc
from skillc.checker import check
from skillc.frontend.ce import parse_ce_detailed
root = Path(sys.argv[1]).resolve()
modules = {name: str(Path(module.__file__).resolve()) for name, module in
           [('jinja2', jinja2), ('markupsafe', markupsafe), ('yaml', yaml), ('z3', z3), ('skillc', skillc)]}
assert all(Path(path).is_relative_to(root) for path in modules.values()), modules
plan = ('Skill `runtime-self-check`.\nRoles: `Engine`.\n'
        'Tool `finish` (owner `Engine`): adds `done`.\n'
        'Initially true: none.\nGoal: `done`.\nProtocol:\n  - `Engine` uses `finish`.\n')
verdict = check(parse_ce_detailed(plan).pack)
assert verdict.label == 'ACHIEVABLE' and verdict.protocol == 'WELL_TYPED' and verdict.admissible
print(json.dumps({'python': sys.executable, 'modules': modules,
                  'versions': {name: m.version(name) for name in ['Jinja2','MarkupSafe','PyYAML','z3-solver']},
                  'skillc_check': {'verdict': verdict.label, 'protocol': verdict.protocol}}))
'''


def run_json(python: Path, code: str, *args: str) -> dict:
    result = subprocess.run([str(python), "-I", "-B", "-c", code, *args],
                            capture_output=True, text=True, encoding="utf-8", timeout=60, check=True)
    return json.loads(result.stdout)


def checked_file(raw: str) -> Path:
    path = Path(raw).expanduser().absolute()
    if not path.resolve(strict=True).is_file():
        raise ValueError(f"Not a file: {path}")
    return path  # Preserve the configured virtual-environment interpreter path.


def target_entry(site_packages: Path, environment: Path, relative: str) -> Path:
    target = (site_packages / relative).resolve()
    if not target.is_relative_to(environment.resolve()):
        raise ValueError(f"Distribution entry escapes destination environment: {relative}")
    return target


def extract_source(archive_bytes: bytes, destination: Path) -> int:
    count = 0
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        for item in archive.infolist():
            if item.is_dir():
                continue
            path = Path(item.filename)
            if path.is_absolute() or path.drive or ".." in path.parts or stat.S_ISLNK(item.external_attr >> 16):
                raise ValueError(f"Unsafe source archive entry: {item.filename}")
            target = destination / path
            if not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError(f"Source archive escape: {item.filename}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(archive.read(item))
            count += 1
    return count


def provision(args: argparse.Namespace) -> dict:
    renderer_python, solver_python = checked_file(args.renderer_python), checked_file(args.solver_python)
    ste_root = Path(args.ste_root).resolve(strict=True)
    skillc_repository = Path(args.skillc_source).resolve(strict=True)
    runtime_root = Path(args.runtime_root).expanduser().absolute()
    if runtime_root.exists() or runtime_root.is_symlink():
        raise FileExistsError(f"Runtime target already exists; nothing was overwritten: {runtime_root}")
    if not (ste_root / "ste_promax" / "__init__.py").is_file():
        raise ValueError("ste-root must identify the native STE source checkout.")
    renderer = run_json(renderer_python, PROBE, "Jinja2", "MarkupSafe", "PyYAML")
    solver = run_json(solver_python, PROBE, "z3-solver")
    if renderer["implementation"] != "cpython" or tuple(renderer["version"]) < (3, 10):
        raise ValueError("An approved CPython 3.10+ renderer interpreter is required.")
    tag = "cp" + "".join(map(str, renderer["version"]))
    accepted_tags = {"py3-none-any", f"py3-none-{renderer['platform']}", f"{tag}-{tag}-{renderer['platform']}"}
    distributions = renderer["distributions"] + solver["distributions"]
    for distribution in distributions:
        if distribution["version"] != VERSIONS[distribution["name"]]:
            raise ValueError(f"Unreviewed dependency version: {distribution['name']} {distribution['version']}")
        if not accepted_tags.intersection(distribution["tags"]):
            raise ValueError(f"Incompatible installed wheel tags: {distribution['name']}")
    commit = subprocess.check_output(
        ["git", "-C", str(skillc_repository), "rev-parse", "--verify", SKILLC_COMMIT + "^{commit}"],
        text=True, timeout=30,
    ).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit) or commit != SKILLC_COMMIT:
        raise ValueError("The inspected SkillC revision is unavailable.")
    plan = {"status": "planned", "runtime_root": str(runtime_root), "skillc_commit": commit,
            "target_python": renderer["version"], "platform": renderer["platform"],
            "distribution_files": sum(len(d["files"]) for d in distributions),
            "versions": VERSIONS, "network_downloads": False}
    if not args.apply:
        return plan

    runtime_root.mkdir(parents=True, exist_ok=False)
    (runtime_root / "provisioning.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    environment = runtime_root / "python"
    subprocess.run([str(renderer_python), "-I", "-B", "-m", "venv", "--without-pip", str(environment)],
                   check=True, timeout=120)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    site = Path(run_json(python, "import json,sysconfig; print(json.dumps({'site':sysconfig.get_path('purelib')}))")["site"])
    copied = []
    for distribution in distributions:
        for item in distribution["files"]:
            target = target_entry(site, environment, item["relative"])
            raw = Path(item["source"]).read_bytes()
            if hashlib.sha256(raw).hexdigest() != item["sha256"]:
                raise ValueError(f"Installed source changed after inspection: {item['source']}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(raw)
            if hashlib.sha256(target.read_bytes()).hexdigest() != item["sha256"]:
                raise ValueError(f"Copied dependency hash mismatch: {target}")
            copied.append({"distribution": distribution["name"], "path": str(target), "sha256": item["sha256"]})

    archive = subprocess.check_output(
        ["git", "-C", str(skillc_repository), "archive", "--format=zip", commit, "--",
         "src/skillc", "LICENSE", "CITATION.cff", "pyproject.toml", "README.md"], timeout=60)
    skillc_root = runtime_root / "skillc-source"
    source_files = extract_source(archive, skillc_root)
    with (site / "ste-skillc-source.pth").open("x", encoding="utf-8") as stream:
        stream.write(str(skillc_root / "src") + "\n")
    verification = run_json(python, SELF_CHECK, str(runtime_root))
    state_root = runtime_root / "state"
    state_root.mkdir(mode=0o700)
    config = {"schema": "ste-promax.runtime.v1", "managed_by": "ste-promax", "status": "ready",
              "python": str(python), "skillc_root": str(skillc_root), "ste_root": str(ste_root),
              "state_root": str(state_root), "skillc_commit": commit, "versions": VERSIONS,
              "provisioning": "offline-record-verified-installed-distributions",
              "source_archive_sha256": hashlib.sha256(archive).hexdigest()}
    (runtime_root / "provenance.json").write_text(
        json.dumps({"files": copied, "skillc_source_files": source_files, "verification": verification}, indent=2) + "\n",
        encoding="utf-8")
    with (runtime_root / "runtime.json").open("x", encoding="utf-8") as stream:
        json.dump(config, stream, indent=2)
        stream.write("\n")
    return {**plan, "status": "ready", "python": str(python), "source_files": source_files,
            "self_check": verification["skillc_check"]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--renderer-python", required=True)
    parser.add_argument("--solver-python", required=True)
    parser.add_argument("--skillc-source", required=True)
    parser.add_argument("--ste-root", required=True)
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--apply", action="store_true", help="Create the new owned runtime after inspecting the plan.")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(provision(args), indent=2))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Runtime provisioning failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

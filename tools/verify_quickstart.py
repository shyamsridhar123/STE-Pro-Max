"""Exercise real first-time setup and a no-install repeat in an isolated directory."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_hashes():
    return {
        str(path.relative_to(ROOT)): digest(path)
        for path in (ROOT / "ste_promax").rglob("*")
        if path.is_file() and path.suffix in {".py", ".json", ".j2", ".md", ".ps1"}
    }


def verify(evidence_dir):
    output = Path(evidence_dir).absolute()
    if output.exists() or output.is_symlink() or ".." in output.parts:
        raise ValueError("Choose a new evidence directory without parent traversal.")
    output.mkdir(parents=True)
    workspace = output / "workspace"
    workspace.mkdir()
    before = source_hashes()
    commands = []

    def run(name, args):
        result = subprocess.run(
            args, cwd=workspace, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=480, check=False,
        )
        (output / f"{name}.stdout.txt").write_text(result.stdout, encoding="utf-8")
        (output / f"{name}.stderr.txt").write_text(result.stderr, encoding="utf-8")
        commands.append({"name": name, "args": args, "exit_code": result.returncode})
        if result.returncode:
            raise RuntimeError(f"{name} failed with exit {result.returncode}; see {output}.\n{result.stderr}")
        return result.stdout

    clean = output / "clean-python"
    run("clean-python", [sys.executable, "-I", "-B", "-m", "venv", "--copies", str(clean)])
    python = clean / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    run("no-render-deps", [
        str(python), "-I", "-B", "-c",
        "import importlib.util; assert importlib.util.find_spec('jinja2') is None; "
        "assert importlib.util.find_spec('yaml') is None",
    ])
    base = [str(python), "-I", "-B", str(ROOT / "quickstart.py")]
    first = json.loads(run("first-start", [*base, "--no-open", "--json"]))
    assert first["status"] == "complete"
    environment = workspace / ".ste-env"
    marker = environment / ".ste-quickstart-owner"
    assert marker.is_file()
    config = (environment / "pyvenv.cfg").read_text()
    assert "include-system-site-packages = false" in config.lower()
    environment_before = {
        str(path.relative_to(environment)): digest(path) for path in environment.rglob("*") if path.is_file()
    }
    source = workspace / "reviewed notes.md"
    original = b"# Readiness\n\nThe checks passed. Approval remains pending.\n"
    source.write_bytes(original)
    repeated = json.loads(run("repeat-no-install", [
        *base, str(source), "--no-install", "--no-open", "--json",
    ]))
    assert repeated["status"] == "complete"
    assert Path(first["files"]["html"]["path"]).parent != Path(repeated["files"]["html"]["path"]).parent
    assert source.read_bytes() == original
    assert Path(repeated["files"]["source"]["path"]).read_bytes() == original
    checked = 0
    for manifest in (first, repeated):
        for item in manifest["files"].values():
            path = Path(item["path"])
            assert path.is_relative_to(workspace / "artifacts")
            assert digest(path) == item["sha256"]
            checked += 1
    assert environment_before == {
        str(path.relative_to(environment)): digest(path) for path in environment.rglob("*") if path.is_file()
    }, "Repeat modified the prepared environment"
    assert source_hashes() == before, "Source bundle changed"
    record = {
        "status": "passed", "version": first["version"], "commands": commands,
        "initial_interpreter": "No renderer dependencies installed",
        "first_setup": "Created isolated workspace environment and installed runtime requirements",
        "repeat": "No installation; environment bytes unchanged; new output directory",
        "artifact_hashes_checked": checked,
        "source_bundle_unchanged": True, "source_document_unchanged": True,
    }
    (output / "result.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", required=True)
    verify(parser.parse_args().evidence_dir)

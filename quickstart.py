"""Run the native bundle, optionally preparing a private caller-workspace venv."""
from __future__ import annotations

import argparse
import importlib
from importlib import metadata
import os
from pathlib import Path
import re
import stat
import subprocess
import sys


ENV_NAME = ".ste-env"
MARKER_NAME = ".ste-quickstart-owner"
MARKER = "STE-Pro Max quickstart environment v1\n"
# Keep these stable-release bounds aligned with pyproject.toml.
REQUIREMENTS = (("jinja2", "Jinja2", (3, 1, 6), 4), ("yaml", "PyYAML", (6, 0, 3), 7))


def dependencies_ready() -> bool:
    """Check actual imports and declared versions without writing bytecode."""
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        for module, distribution, minimum, next_major in REQUIREMENTS:
            version = metadata.version(distribution)
            match = re.fullmatch(r"(\d+)\.(\d+)(?:\.(\d+))?", version)
            if not match:
                return False
            release = tuple(int(part or 0) for part in match.groups())
            if not minimum <= release < (next_major, 0, 0):
                return False
            importlib.import_module(module)
        return True
    except (ImportError, metadata.PackageNotFoundError, ValueError, OSError):
        return False
    finally:
        sys.dont_write_bytecode = previous


def safe_path(path: Path, *, directory: bool = False, required: bool = False) -> Path:
    """Inspect lexical ancestors before resolving; reject redirected paths."""
    if ".." in path.parts or (path.drive and not path.root):
        raise ValueError(f"Path must not contain traversal or be drive-relative: {path}")
    absolute = path.absolute()
    for item in (absolute, *absolute.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            if item == absolute and required:
                raise ValueError(f"Required path does not exist: {absolute}") from None
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError(f"Symbolic links and Windows reparse points are not allowed: {item}")
        if item != absolute or directory:
            if not stat.S_ISDIR(info.st_mode):
                raise ValueError(f"Expected a directory, not a path collision: {item}")
        elif not stat.S_ISREG(info.st_mode):
            raise ValueError(f"Expected a regular file: {item}")
    return absolute


def bundle_root() -> Path:
    launcher = safe_path(Path(__file__), required=True)
    root = safe_path(launcher.parent, directory=True, required=True)
    for name in ("__main__.py", "pyproject.toml", "README.md", "LICENSE"):
        safe_path(root / name, required=True)
    package = safe_path(root / "ste_promax", directory=True, required=True)
    # Check runtime code/resources too, before executing or copying any of them.
    pending = [package]
    while pending:
        for entry in pending.pop().iterdir():
            info = entry.lstat()
            is_directory = stat.S_ISDIR(info.st_mode)
            safe_path(entry, directory=is_directory, required=True)
            if is_directory:
                pending.append(entry)
    return root


def setup_command(command: list[str], workspace: Path, timeout: int) -> None:
    # --isolated alone still permits system pip config. Disable config files and
    # inherited pip options for this child only, including its build subprocesses.
    child_env = {key: value for key, value in os.environ.items() if not key.upper().startswith("PIP_")}
    child_env["PIP_CONFIG_FILE"] = os.devnull
    child_env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(command, cwd=workspace, shell=False, timeout=timeout,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            errors="replace", check=False, env=child_env)
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n", file=sys.stderr)
    if result.returncode:
        phase = "dependency installation" if "pip" in command else "environment creation"
        raise ValueError(f"Setup {phase} failed (exit {result.returncode}).")


def env_python(environment: Path) -> Path:
    return environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def probe_python(python: str, root: Path, workspace: Path) -> bool:
    # -I ignores host PYTHONPATH/user-site; -B leaves an existing env read-only.
    code = (
        "import runpy,sys; "
        "check=runpy.run_path(sys.argv[1])['dependencies_ready']; "
        "sys.exit(0 if check() else 1)"
    )
    result = subprocess.run(
        [python, "-I", "-B", "-c", code, str(root / "quickstart.py")],
        cwd=workspace, shell=False, timeout=30, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False,
    )
    return result.returncode == 0


def current_ready(root: Path, workspace: Path) -> bool:
    return probe_python(sys.executable, root, workspace)


def env_ready(python: Path, root: Path, workspace: Path) -> bool:
    safe_path(python)
    return python.is_file() and probe_python(str(python), root, workspace)


def preflight_source(source: Path, root: Path) -> None:
    if source.suffix.lower() not in {".md", ".json"}:
        raise ValueError("Quickstart accepts .md or .json, not raw .html or other formats. "
                         "For reviewed HTML use native start with explicit --trusted-html.")
    # The bundle's normalizer is standard-library-only. Reuse its strict JSON,
    # empty-input and raw-HTML gates rather than introducing another parser.
    previous = sys.dont_write_bytecode
    previous_path = sys.path[:]
    sys.dont_write_bytecode = True
    # Isolated Python omits a script's directory. Use only the already-checked
    # bundle root, never caller cwd/PYTHONPATH or an unrelated installed copy.
    sys.path.insert(0, str(root))
    try:
        from ste_promax.cli import normalized_input
        from ste_promax.input_validation import validate_input
        _, _, data = normalized_input(source)
        validate_input(data)
    finally:
        sys.path[:] = previous_path
        sys.dont_write_bytecode = previous


def runtime(root: Path, workspace: Path, no_install: bool) -> str:
    if current_ready(root, workspace):
        return sys.executable

    environment = safe_path(workspace / ENV_NAME, directory=True)
    python = env_python(environment)
    if environment.exists():
        marker = safe_path(environment / MARKER_NAME)
        config = safe_path(environment / "pyvenv.cfg")
        if not marker.is_file() or marker.read_text(encoding="utf-8") != MARKER:
            raise ValueError(f"Refusing unowned existing {environment}; it was not changed. "
                             "Use a ready Python interpreter or a different clean workspace.")
        if not config.is_file() or not re.search(
            r"(?mi)^include-system-site-packages\s*=\s*false\s*$",
            config.read_text(encoding="utf-8"),
        ) or not env_ready(python, root, workspace):
            raise ValueError(f"Existing {environment} is not ready; it was not changed. "
                             "Use a ready Python interpreter or a different clean workspace.")
        return str(python)
    if no_install:
        raise ValueError("Jinja2 >=3.1.6,<4 and PyYAML >=6.0.3,<7 are required. Nothing was installed. "
                         "Run quickstart.py again without --no-install to prepare a private .ste-env, "
                         "or use a Python interpreter with the declared dependencies.")

    # mkdir is exclusive: a concurrent invocation cannot claim or alter this env.
    safe_path(workspace, directory=True, required=True)
    environment.mkdir()
    try:
        safe_path(environment, directory=True, required=True)
        print(f"Preparing private environment: {environment}", file=sys.stderr)
        setup_command([sys.executable, "-I", "-B", "-m", "venv", "--copies", str(environment)],
                      workspace, 120)
        safe_path(python, required=True)
        # No pip at all if the newly created environment is already ready.
        if not env_ready(python, root, workspace):
            # Execute the existing source bundle: only its declared runtime
            # requirements need installation, not a copied engine/build backend.
            requirements = [
                f"{distribution}>={'.'.join(map(str, minimum))},<{major}"
                for _, distribution, minimum, major in REQUIREMENTS
            ]
            setup_command(
                [str(python), "-I", "-B", "-m", "pip", "--isolated", "--require-virtualenv", "install",
                 "--disable-pip-version-check", "--no-input", "--no-cache-dir",
                 "--only-binary=:all:", *requirements],
                workspace, 300,
            )
            if not env_ready(python, root, workspace):
                raise ValueError("Installed environment still cannot import the declared dependencies.")
        safe_path(environment, directory=True, required=True)
        with (environment / MARKER_NAME).open("x", encoding="utf-8") as stream:
            stream.write(MARKER)
        return str(python)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"{exc} Partial environment preserved at {environment}; nothing was deleted. "
                         "Inspect it manually, or retry in a different clean workspace.") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?")
    parser.add_argument("--open", action="store_true", help="Open the finished local artifact.")
    parser.add_argument("--no-open", action="store_true", help="Never open a browser (overrides --open).")
    parser.add_argument("--no-install", action="store_true", help="Use ready environments only.")
    parser.add_argument("--json", action="store_true", help="Pass through native start JSON unchanged.")
    parser.add_argument("--output-dir")
    args = parser.parse_args(argv)
    try:
        if sys.version_info < (3, 10):
            raise ValueError("Quickstart requires Python 3.10 or newer; nothing was installed.")
        for name in ("source", "output_dir"):
            value = getattr(args, name)
            if value is not None and not value.strip():
                raise ValueError(f"{name.replace('_', '-')} must not be blank; nothing was installed.")
        root = bundle_root()
        workspace = safe_path(Path.cwd(), directory=True, required=True)
        source = safe_path(Path(args.source), required=True) if args.source is not None else None
        if source is not None:
            preflight_source(source, root)
        output = None
        if args.output_dir:
            output = safe_path(Path(args.output_dir), directory=True)
            environment = workspace / ENV_NAME
            if output.exists() or output.is_relative_to(environment):
                raise ValueError("Output must be a new directory outside .ste-env; existing paths were not changed.")
        else:
            safe_path(workspace / "artifacts", directory=True)
        python = runtime(root, workspace, args.no_install)
        command = [python, "-I", "-B", str(root), "start"]
        if source is not None:
            command.append(str(source))
        if args.open and not args.no_open:
            command.append("--open")
        if args.json:
            command.append("--json")
        if output is not None:
            command.extend(["--output-dir", str(output)])
        result = subprocess.run(command, cwd=workspace, shell=False, timeout=120, check=False)
        if result.returncode == 0 and not args.json:
            print("Ready. Open the local HTML above, or add --open next time.", file=sys.stderr)
        return result.returncode
    except subprocess.TimeoutExpired:
        print("Quickstart timed out; any environment and output files were preserved.", file=sys.stderr)
        return 2
    except (OSError, ValueError, ImportError) as exc:
        print(f"Quickstart: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

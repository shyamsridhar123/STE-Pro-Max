"""Local first-run UX. Rendering stays in cli.render; diagnostics use stdlib only."""
from __future__ import annotations

import argparse
from importlib import metadata, resources, util
import json
from pathlib import Path
import platform
import re
import secrets
import shutil
import stat
import sys
from typing import Any, TextIO
import unicodedata
import webbrowser


# Stable numeric bounds match pyproject.toml and quickstart.dependencies_ready.
# MarkupSafe is transitive: discovery is required, but no independent bound is declared.
_RENDER_REQUIREMENTS = (
    ("jinja2", "Jinja2", (3, 1, 6), 4),
    ("yaml", "PyYAML", (6, 0, 3), 7),
    ("markupsafe", "MarkupSafe", None, None),
)


def doctor_report() -> dict[str, Any]:
    """Discover packages without importing them or probing tools by execution."""
    required = []
    for module, distribution, minimum, next_major in _RENDER_REQUIREMENTS:
        try:
            available = util.find_spec(module) is not None
        except (ImportError, ValueError):
            available = False
        try:
            version = metadata.version(distribution)
        except metadata.PackageNotFoundError:
            version = None
        compatible = None
        requirement = None
        if minimum is not None and next_major is not None:
            requirement = f">={'.'.join(map(str, minimum))},<{next_major}"
            match = re.fullmatch(r"(\d+)\.(\d+)(?:\.(\d+))?", version or "")
            release = tuple(int(part or 0) for part in match.groups()) if match else None
            compatible = release is not None and minimum <= release < (next_major, 0, 0)
        required.append({
            "name": distribution, "module": module, "available": available, "version": version,
            "metadata_available": version is not None, "required_version": requirement,
            "version_compatible": compatible,
        })
    python_ok = sys.version_info >= (3, 10)
    windows = platform.system() == "Windows"
    ready = python_ok and all(item["available"] and item["version_compatible"] is not False for item in required)
    return {
        "status": "ready" if ready else "missing_requirements",
        "python": {"executable": sys.executable, "version": platform.python_version(),
                   "supported": python_ok, "minimum": "3.10"},
        "platform": platform.platform(),
        "required_render": required,
        "optional": [
            {"name": "Windows System.Speech", "purpose": "Local voice narration",
             "platform_supported": windows,
             "path": shutil.which("powershell.exe") if windows else None,
             "note": "Optional. Installed voices are not probed; supplied PCM audio is also supported."},
            {"name": "Node.js", "purpose": "Optional video composition tooling", "path": shutil.which("node")},
            {"name": "Hyperframes", "purpose": "Optional video preview/export", "path": shutil.which("hyperframes"),
             "note": "Not needed for start/render. Video tooling and review remain separate."},
            {"name": "FFmpeg", "purpose": "Optional video encoding tooling", "path": shutil.which("ffmpeg")},
        ],
        "hints": [
            "Use Python 3.10 or newer. Run doctor with the same interpreter used for start.",
            "Required stable versions: Jinja2 >=3.1.6,<4 and PyYAML >=6.0.3,<7. "
            "Missing metadata or non-stable version strings cannot establish compatibility. "
            "MarkupSafe is transitive; its discovery is required, with no separate version bound.",
            "In your chosen Python environment, install this local bundle with: "
            'python -m pip install "/path/to/STE-Pro-Max". Its dependencies include Jinja2 and PyYAML.',
            "Discovery only: packages were not imported and tools were not executed. "
            "A ready report is not a render, voice, or video verification. Nothing was installed.",
        ],
    }


def _safe_output(path: Path, source: Path, design: str | None) -> Path:
    """Reject redirection before resolving paths, including Windows junction parents."""
    if ".." in path.parts or (path.drive and not path.root):
        raise ValueError("Output directory must not contain '..' or a drive-relative path.")
    absolute = path.absolute()
    for parent in (absolute, *absolute.parents):
        try:
            info = parent.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError("Output directory and parents must not be symbolic links or Windows reparse points.")
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError("Output directory and parents must be directories, not source files.")
    output = absolute.resolve()
    for input_path in (source, Path(design) if design else None):
        if input_path is not None and input_path.resolve().is_relative_to(output):
            raise ValueError("Output directory must not contain or collide with an input source or design.")
    if output.exists():
        raise ValueError("Start requires a new output directory; existing files and directories were not changed.")
    return output


def _slug(title: str) -> str:
    plain = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")[:56].rstrip("-")
    # Prefix also protects Windows device names such as CON, NUL and COM1.
    return "brief-" + (slug or "untitled")


def start(args: argparse.Namespace) -> dict[str, Any]:
    from ste_promax import cli

    for name in ("input", "output_dir", "design"):
        value = getattr(args, name)
        if value is not None and not value.strip():
            raise ValueError(f"{name.replace('_', '-')} must not be empty.")

    def render_source(source: Path) -> dict[str, Any]:
        # Reuse normalization to choose a title, with no writes or inferred trust.
        _, _, data = cli.normalized_input(source, args.title, args.trusted_html)
        title = data["title"]
        assert isinstance(title, str)  # normalized_input validates this boundary.
        if args.design:
            # The low-level renderer retains failed-render evidence. Start rejects
            # malformed authored design tokens before creating its output folder.
            design_text = Path(args.design).read_bytes().decode("utf-8-sig")
            if not design_text.strip():
                raise ValueError("Design file is empty.")
            try:
                from ste_promax.render import _design_tokens
            except ModuleNotFoundError as exc:
                if exc.name not in {"yaml", "jinja2", "markupsafe"}:
                    raise
                raise ValueError("Rendering requires Jinja2 and PyYAML; run doctor for installation hints.") from exc
            _design_tokens(design_text)
        requested = (Path(args.output_dir) if args.output_dir is not None else
                     Path.cwd() / "artifacts" / f"{_slug(title)}-{secrets.token_hex(8)}")
        output = _safe_output(requested, source, args.design)
        render_args = argparse.Namespace(input=str(source), output_dir=str(output), title=args.title,
                                         design=args.design, trusted_html=args.trusted_html)
        # cli.render validates input, design and render dependencies before mkdir.
        return cli.render(render_args)

    if args.input is not None:
        return render_source(Path(args.input).resolve(strict=True))
    sample = resources.files("ste_promax").joinpath("data").joinpath("quickstart.json")
    with resources.as_file(sample) as source:
        return render_source(source)


def _print_human(message: str, *, file: TextIO | None = None) -> None:
    """Escape only unencodable display text; leave streams and source data intact."""
    stream = sys.stdout if file is None else file
    encoding = getattr(stream, "encoding", None)
    if encoding:
        message = message.encode(encoding, errors="backslashreplace").decode(encoding)
    print(message, file=stream)


def run(args: argparse.Namespace) -> int:
    if args.command == "doctor":
        report = doctor_report()
        if args.json:
            print(json.dumps(report, ensure_ascii=True, indent=2))
        else:
            _print_human(f"Local environment: {report['status']}")
            _print_human(f"Python {report['python']['version']}: {report['python']['executable']}")
            _print_human(f"Platform: {report['platform']}")
            for item in report["required_render"]:
                state = "found" if item["available"] else "MISSING"
                if item["required_version"]:
                    state += f"; version {item['version'] or 'metadata missing'}; requires {item['required_version']}"
                    state += "; compatible" if item["version_compatible"] else "; NOT compatible/verified"
                else:
                    state += "; transitive, no separate version bound"
                _print_human(f"Required render: {item['name']} — {state}")
            for item in report["optional"]:
                _print_human(f"Optional: {item['name']} — {item.get('path') or 'not found/not applicable'}")
                if item.get("note"):
                    _print_human(item["note"])
            _print_human("\n".join(report["hints"]))
        return 0 if report["status"] == "ready" else 2

    result = start(args)
    if args.json:
        print(json.dumps(result, ensure_ascii=True, indent=2))
    else:
        _print_human(f"Local artifact: {result['status']}")
        for key in ("html", "gallery"):
            if key in result["files"]:
                _print_human(f"{'Open' if key == 'html' else 'Gallery'}: {result['files'][key]['path']}")
        for warning in result["warnings"]:
            _print_human(f"Warning: {warning}")
    if result["status"] != "complete":
        return 2
    if args.open:
        path = Path(result["files"]["html"]["path"])
        try:
            if not webbrowser.open(path.as_uri()):
                raise RuntimeError("No browser accepted the request.")
        except Exception as exc:
            _print_human(f"Error: Browser launch failed: {exc}. Output preserved; open {path}", file=sys.stderr)
            return 2
    return 0

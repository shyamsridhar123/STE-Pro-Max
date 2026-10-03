"""Build one deterministic source plugin bundle; never install or fetch dependencies."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[1]
NAME = "ste-pro-max"
ROOT_FILES = (
    "__main__.py", "quickstart.py", "pyproject.toml", "README.md", "LICENSE", "NOTICE", "plugin.json",
    ".claude-plugin/plugin.json", ".claude-plugin/marketplace.json",
    ".github/plugin/marketplace.json", ".agents/plugins/marketplace.json", "STE-ProMAX.zip",
)
# Runtime/source trees only; no tests, generated artifacts, or repository state.
TREES = {
    "ste_promax": {".py", ".j2", ".md", ".ps1", ".json"},
    "skills": {".md", ".yaml", ".yml", ".json", ".py", ".ps1", ".sh"},
    "examples": {".md", ".json", ".py", ".ps1", ".html", ".css", ".js", ".svg", ".txt"},
    "docs": {".md", ".txt", ".svg", ".png", ".webp", ".gif"},
    "ste-promax": {".md", ".yaml", ".yml"},
}
REQUIRED_PAYLOAD = (
    "ste_promax/__init__.py", "ste_promax/__main__.py", "ste_promax/cli.py",
    "ste_promax/render.py", "ste_promax/gallery.py", "ste_promax/writing.py",
    "ste_promax/section_schema.py", "ste_promax/json_input.py", "ste_promax/diagrams.py", "ste_promax/charts.py",
    "ste_promax/stories.py", "ste_promax/media.py", "ste_promax/scripts/narrate.ps1",
    "ste_promax/templates/document.html.j2", "ste_promax/templates/gallery.html.j2",
    "ste_promax/templates/story.html.j2", "ste_promax/templates/story-video.html.j2",
    "ste_promax/designs/ste.DESIGN.md", "skills/ste-promax/SKILL.md",
    "skills/ste-visual-docs/SKILL.md", "skills/ste-storytelling/SKILL.md", "ste-promax/SKILL.md",
    "docs/AUTHORING.md", "ste_promax/onboarding.py", "ste_promax/data/quickstart.json",
    "ste_promax/input_validation.py",
    "docs/assets/hero.png", "docs/assets/showcase.webp",
    "examples/showcase/README.md", "examples/showcase/retry-lab.html",
    "examples/showcase/release-brief.html", "examples/showcase/rate-lab.html",
    "docs/assets/retry-lab.gif", "docs/assets/retry-lab.png",
    "docs/assets/release-brief.png", "docs/assets/rate-lab.png",
)
EXCLUDED_NAMES = {
    "artifacts", "tests", "node_modules", "venv", "__pycache__", "omx_wiki", "memory.md",
    "build", "dist", "site-packages",
}
PRIVATE_STEMS = {
    "secret", "secrets", "credential", "credentials", "token", "tokens",
    "api_key", "apikey", "access_token", "refresh_token", "password", "passwords",
}


def reject_links(path):
    """Reject symlinks and Windows reparse points without following them."""
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        raise ValueError(f"Symlinks/reparse points are not allowed: {path}")
    return info


def check_ancestors(path):
    for ancestor in (path, *path.parents):
        if ancestor.exists() or ancestor.is_symlink():
            reject_links(ancestor)


def collect_payload(source_root):
    """Read a stable byte snapshot of the explicit source whitelist before writing."""
    root = Path(os.path.abspath(source_root))
    check_ancestors(root)
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"Source root is not a directory: {root}")
    payload = {}

    def read_file(path):
        info = reject_links(path)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"Payload must contain regular files only: {path}")
        payload[path.relative_to(root).as_posix()] = path.read_bytes()

    def walk(directory, suffixes):
        reject_links(directory)
        for child in sorted(directory.iterdir()):
            name = child.name.lower()
            # Hidden state and known credential names are never payload.
            stem = name.split(".", 1)[0].replace("-", "_")
            if name.startswith(".") or name in EXCLUDED_NAMES or stem in PRIVATE_STEMS:
                continue
            info = reject_links(child)
            if stat.S_ISDIR(info.st_mode):
                walk(child, suffixes)
            elif child.suffix.lower() in suffixes:
                read_file(child)

    for relative in ROOT_FILES:
        path = root / relative
        check_ancestors(path)
        read_file(path)
    for directory, suffixes in TREES.items():
        path = root / directory
        if path.exists() or path.is_symlink():
            walk(path, suffixes)
    missing = [name for name in REQUIRED_PAYLOAD if name not in payload]
    if missing:
        raise ValueError(f"Missing required source payload: {', '.join(missing)}")
    identity = json.loads(payload["plugin.json"])
    if identity.get("name") != NAME or not isinstance(identity.get("version"), str):
        raise ValueError("Root plugin identity must name ste-pro-max and supply a version.")
    return dict(sorted(payload.items())), identity


def record(contents):
    return {"sha256": hashlib.sha256(contents).hexdigest(), "size": len(contents)}


def build_plugin(output_dir, source_root=ROOT):
    output = Path(os.path.abspath(output_dir))
    check_ancestors(output)
    output = output.resolve()
    if output.exists():
        raise ValueError("Output directory must be new; existing directories are never overwritten or deleted.")
    if not output.parent.is_dir():
        raise ValueError("Output parent directory must already exist; no paths outside the target are created.")
    source_root = Path(os.path.abspath(source_root))
    check_ancestors(source_root)
    source_root = source_root.resolve()
    if any(output.is_relative_to(source_root / tree) for tree in TREES):
        raise ValueError("Output must not be inside a whitelisted source tree.")
    payload, identity = collect_payload(source_root)
    output.mkdir()  # Exclusive creation also refuses a racing builder.
    bundle = output / NAME
    bundle.mkdir()
    for relative, contents in payload.items():
        target = bundle / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(contents)

    archive = output / f"{NAME}.zip"
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zipped:
        for relative, contents in payload.items():
            info = zipfile.ZipInfo(f"{NAME}/{relative}", date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zipped.writestr(info, contents, compresslevel=9)
    manifest = {
        "name": NAME, "version": identity["version"], "bundle_type": "source",
        "bundle_dir": NAME,
        "runtime": "Requires Python and the dependencies declared in pyproject.toml; nothing is auto-installed.",
        "archive": {"path": archive.name, **record(archive.read_bytes())},
        "files": {relative: record(contents) for relative, contents in payload.items()},
    }
    with (output / "hashes.json").open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, help="New directory under an existing parent.")
    args = parser.parse_args(argv)
    try:
        manifest = build_plugin(args.output_dir)
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Native prose checking and artifact rendering. No external renderer process."""
import argparse
import hashlib
import html
import json
from pathlib import Path
import re
import sys

from ste_promax import __version__
from ste_promax.writing import LIMITS, check_text, strip_frontmatter


def has_raw_html(value):
    """Identify explicit HTML payloads, including nested structured input."""
    if isinstance(value, dict):
        return any(
            key == "html" or key.endswith("_html")
            or (key == "breadcrumb" and isinstance(item, str) and re.search(r"<[^>]+>", item))
            or has_raw_html(item)
            for key, item in value.items()
            if key != "trusted_html"
        )
    if isinstance(value, list):
        return any(has_raw_html(item) for item in value)
    return False


def normalized_input(source, title=None, trusted_html=False):
    """Validate before filesystem writes; keep the original bytes separately."""
    original = source.read_bytes()
    text = original.decode("utf-8-sig")
    if not text.strip():
        raise ValueError("Input is empty.")
    suffix = source.suffix.lower()
    if suffix == ".json":
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("JSON input must be an object.")
        for key in ("title", "body_html", "body_md"):
            if key in data and not isinstance(data[key], str):
                raise ValueError(f"JSON {key} must be a string.")
    elif suffix == ".html":
        data = {"body_html": text}
    elif suffix == ".md":
        body = strip_frontmatter(text)
        heading = re.search(r"^#\s+(.+?)\s*#*\s*$", body, re.M)
        data = {"body_md": body}
        if heading:
            data["title"] = heading[1]
    else:
        raise ValueError("Render input must be .html, .md, or .json.")
    if has_raw_html(data) and not trusted_html:
        raise ValueError("Raw HTML requires explicit --trusted-html consent; review the authored content first.")
    data["title"] = title if title is not None else data.get("title", source.stem)
    if not data["title"].strip():
        raise ValueError("Title must not be empty.")
    normalized = (json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    return original, normalized, data


def file_record(path):
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def lint_status(text):
    """Read only an unambiguous top-level YAML boolean, never a truthy string."""
    import yaml

    try:
        nodes = yaml.compose(text, Loader=yaml.SafeLoader)
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    if not isinstance(nodes, yaml.MappingNode) or not isinstance(data, dict):
        return None
    keys = [key.value for key, _ in nodes.value if isinstance(key, yaml.ScalarNode)]
    value = data.get("lint_passed")
    return value if keys.count("lint_passed") == 1 and type(value) is bool else None


def render(args):
    source = Path(args.input).resolve(strict=True)
    original, normalized, data = normalized_input(source, args.title, args.trusted_html)
    design = Path(args.design).resolve(strict=True) if args.design else None
    design_bytes = design.read_bytes() if design else None
    if design_bytes is not None and not design_bytes.decode("utf-8-sig").strip():
        raise ValueError("Design file is empty.")
    requested_output = Path(args.output_dir)
    if requested_output.is_symlink():
        raise ValueError("Output directory must not be a symbolic link.")
    output = requested_output.resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Output directory must be new or empty; existing artifacts were not changed.")

    # Import the copied native implementation, never an installed CLI or fallback.
    try:
        from ste_promax.render import render_artifact, validate_input
        from ste_promax.gallery import regenerate_gallery
    except ModuleNotFoundError as exc:
        if exc.name not in {"yaml", "jinja2", "markupsafe"}:
            raise
        raise ValueError(
            "Rendering requires the Python dependencies Jinja2 and PyYAML. "
            "Plugin installation does not install them automatically; use an approved "
            "Python environment with these dependencies. Nothing was installed."
        ) from exc

    validate_input(data)
    output.mkdir(parents=True, exist_ok=True)
    saved_source = output / ("source" + source.suffix.lower())
    input_path = output / "input.json"
    for path, contents in ((saved_source, original), (input_path, normalized)):
        with path.open("xb") as stream:
            stream.write(contents)
    files = {"source": file_record(saved_source), "input": file_record(input_path)}
    saved_design = None
    if design:
        saved_design = output / "input-design.md"
        with saved_design.open("xb") as stream:
            stream.write(design_bytes)
        files["input_design"] = file_record(saved_design)

    warnings = [
        "Semantic and visual review remain manual; artifact presence is not quality certification.",
        "External-reference detection is a conservative text scan including navigation URLs. "
        "Dynamic and relative assets require manual review; offline operation is not verified.",
    ]
    if args.trusted_html:
        warnings.append("Raw HTML was explicitly trusted, not sanitized.")
    expected = {"gallery": output / "gallery.html"}
    complete = False
    try:
        triple = render_artifact(data, design_path=saved_design, output_dir=output)
        expected.update({name: Path(triple[name + "_path"]) for name in ("html", "design", "meta")})
        complete = True
    except Exception as exc:
        # Persist evidence of native renderer failures without claiming success.
        warnings.append(f"Native renderer failed: {type(exc).__name__}: {exc}")
    if complete:
        try:
            gallery = Path(regenerate_gallery(output))
            if gallery.resolve() != expected["gallery"]:
                complete = False
                warnings.append("Native gallery did not return the required gallery.html path.")
        except Exception as exc:
            complete = False
            warnings.append(f"Native gallery failed: {type(exc).__name__}: {exc}")

    lint = None
    external = set()
    protected = {saved_source, input_path, saved_design, output / "manifest.json"}
    artifact_paths = [path.resolve() for path in expected.values()]
    if len(set(artifact_paths)) != len(artifact_paths):
        complete = False
        warnings.append("Artifact paths collide, including a possible gallery.html collision.")
    for name, path in expected.items():
        if (path.is_symlink() or path.resolve().parent != output or path.resolve() in protected
                or not path.is_file() or path.stat().st_size == 0):
            complete = False
            warnings.append(f"Missing, empty, or unsafe artifact: {path.name}")
            continue
        files[name] = file_record(path)
        try:
            text = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            complete = False
            warnings.append(f"Artifact is not valid UTF-8: {path.name}")
            continue
        if name == "meta":
            lint = lint_status(text)
        if name in ("html", "gallery"):
            external.update(html.unescape(ref) for ref in
                            re.findall(r"""(?:https?://|(?<!:)//)[^\s"'<>`)\]}]+""", text))
    if lint is not True:
        warnings.append("Design metadata lint_passed is false." if lint is False
                        else "Design metadata lint status is unknown.")
    if external:
        warnings.append("External references remain; full offline operation has not been established.")
    # The renderer must not mutate the saved, repeatable input or authored source.
    for name, path, content in (("source", saved_source, original), ("input", input_path, normalized)):
        if path.is_symlink() or not path.is_file():
            complete = False
            warnings.append(f"Native renderer removed or replaced saved {name}.")
            files.pop(name, None)
            continue
        if path.read_bytes() != content:
            complete = False
            warnings.append(f"Native renderer unexpectedly changed saved {name}.")
        files[name] = file_record(path)
    manifest = {
        "status": "complete" if complete else "failed", "version": __version__,
        "renderer": "ste_promax.render", "source_path": str(source),
        "source_sha256": hashlib.sha256(original).hexdigest(), "files": files,
        "trusted_html": args.trusted_html, "lint_passed": lint,
        "external_references": sorted(external), "offline_verified": False, "warnings": warnings,
    }
    with (output / "manifest.json").open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(prog="ste-promax", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="Advisory prose-length diagnostics; no certification.")
    check.add_argument("input")
    check.add_argument("--profile", choices=LIMITS, default="relaxed")
    check.add_argument("--json", action="store_true")
    check.add_argument("--fail-on-findings", action="store_true")
    renderer = commands.add_parser("render", help="Render through the native STE-Pro Max implementation.")
    renderer.add_argument("input")
    renderer.add_argument("--output-dir", required=True)
    renderer.add_argument("--title")
    renderer.add_argument("--design", help="Local design file, archived with the input.")
    renderer.add_argument("--trusted-html", action="store_true",
                          help="Explicitly trust reviewed authored HTML; never inferred from input metadata.")
    args = parser.parse_args(argv)
    try:
        if args.command == "render":
            result = render(args)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["status"] == "complete" else 2
        result = check_text(Path(args.input).read_text(encoding="utf-8-sig"), args.profile)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"{result['word_count']} words; {result['sentence_count']} sentences; "
                  f"{len(result['findings'])} advisory findings ({args.profile}).")
            for finding in result["findings"]:
                print(json.dumps(finding, ensure_ascii=False))
            print("\n".join(result["limitations"]))
        return 1 if args.fail_on_findings and result["findings"] else 0
    except (OSError, ValueError, ImportError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

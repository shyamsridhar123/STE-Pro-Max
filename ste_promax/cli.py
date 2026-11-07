"""Native prose checking and artifact rendering. No external renderer process."""
import argparse
import hashlib
import html
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from typing import Any
from urllib.parse import urlsplit

from ste_promax import __version__
from ste_promax.json_input import loads_json
from ste_promax.policy_runtime import (
    ERROR_POSTCONDITION_FAILURE,
    PolicyError,
    check_sensitive_read_path,
)
from ste_promax.writing import LIMITS, check_text, strip_frontmatter

_PACKAGE_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _PACKAGE_DIR.parent
_SUITE_EXAMPLES_DIR = (_REPO_ROOT / "examples" / "suite").resolve()
_QUICKSTART_SAMPLE = (_PACKAGE_DIR / "data" / "quickstart.json").resolve()


def _is_link_or_reparse(info: os.stat_result) -> bool:
    return bool(
        stat.S_ISLNK(info.st_mode)
        or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def _safe_existing_file(raw: str | Path, label: str) -> Path:
    if not isinstance(raw, (str, Path)) or not str(raw).strip():
        raise ValueError(f"{label} must not be empty.")
    path = Path(raw)
    if ".." in path.parts or (path.drive and not path.root):
        raise ValueError(f"{label} must not contain '..' or a drive-relative path.")
    check_sensitive_read_path(path, label)
    absolute = path.absolute()
    check_sensitive_read_path(absolute, label)
    for current in (absolute, *absolute.parents):
        try:
            info = current.lstat()
        except FileNotFoundError as exc:
            if current == absolute:
                raise ValueError(f"{label} does not exist: {raw}") from exc
            continue
        if _is_link_or_reparse(info):
            raise ValueError(f"{label} must not be a symbolic link or Windows reparse point: {current}")
    final_info = absolute.lstat()
    if not stat.S_ISREG(final_info.st_mode) or final_info.st_size == 0:
        raise ValueError(f"{label} must be a non-empty regular file: {raw}")
    resolved = absolute.resolve(strict=True)
    check_sensitive_read_path(resolved, label)
    return resolved


def _safe_existing_dir(raw: str | Path, label: str) -> Path:
    if not isinstance(raw, (str, Path)) or not str(raw).strip():
        raise ValueError(f"{label} must not be empty.")
    path = Path(raw)
    if ".." in path.parts or (path.drive and not path.root):
        raise ValueError(f"{label} must not contain '..' or a drive-relative path.")
    absolute = path.absolute()
    for current in (absolute, *absolute.parents):
        try:
            info = current.lstat()
        except FileNotFoundError as exc:
            if current == absolute:
                raise ValueError(f"{label} does not exist: {raw}") from exc
            continue
        if _is_link_or_reparse(info):
            raise ValueError(f"{label} must not be a symbolic link or Windows reparse point: {current}")
    final_info = absolute.lstat()
    if not stat.S_ISDIR(final_info.st_mode):
        raise ValueError(f"{label} must be an existing directory: {raw}")
    return absolute.resolve(strict=True)


def _validate_relative_locator(locator: Any, where: str, evidence_root: Path) -> tuple[Path, str]:
    if not isinstance(locator, str) or not locator.strip():
        raise ValueError(f"{where}: locator must be a non-empty string")
    parsed_url = urlsplit(locator)
    if parsed_url.scheme or "://" in locator or locator.startswith("//"):
        raise ValueError(f"{where}: remote or URI locators are not allowed for local evidence: {locator!r}")
    if "\\" in locator:
        raise ValueError(f"{where}: use forward slashes in relative locator {locator!r}")
    rel_path = Path(locator)
    if rel_path.is_absolute() or rel_path.drive or rel_path.root:
        raise ValueError(f"{where}: locator must be relative to evidence root: {locator!r}")
    if not rel_path.parts or any(part in ("", ".", "..") for part in rel_path.parts):
        raise ValueError(f"{where}: locator must not contain '.' or '..' segments: {locator!r}")
    check_sensitive_read_path(rel_path, where)
    current = evidence_root
    for part in rel_path.parts:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError as exc:
            raise ValueError(f"{where}: local evidence file does not exist under evidence root: {locator!r}") from exc
        if _is_link_or_reparse(info):
            raise ValueError(f"{where}: symbolic links and reparse points are not allowed: {locator!r}")
    final_info = current.lstat()
    if not stat.S_ISREG(final_info.st_mode) or final_info.st_size == 0:
        raise ValueError(f"{where}: local evidence must be a non-empty regular file: {locator!r}")
    resolved = current.resolve(strict=True)
    if not resolved.is_relative_to(evidence_root):
        raise ValueError(f"{where}: locator escapes evidence root: {locator!r}")
    check_sensitive_read_path(resolved, where)
    return resolved, resolved.relative_to(evidence_root).as_posix()


def _resolve_evidence_inputs(
    data: dict[str, Any],
    *,
    source: Path,
    design: Path | None,
    output: Path,
    evidence_args: list[str],
    evidence_root_arg: str | None,
) -> tuple[Path, list[Path], list[str], dict[Path, bytes], list[dict[str, Any]]]:
    if evidence_root_arg is not None:
        ev_root = _safe_existing_dir(evidence_root_arg, "Evidence root")
    elif _SUITE_EXAMPLES_DIR.is_dir() and source.is_relative_to(_SUITE_EXAMPLES_DIR):
        ev_root = _REPO_ROOT
    else:
        ev_root = source.parent
    if output == ev_root:
        raise ValueError("Output directory must not equal the evidence root directory.")

    evidence_paths: list[Path] = []
    evidence_locators: list[str] = []
    evidence_snapshots: dict[Path, bytes] = {}
    evidence_records: list[dict[str, Any]] = []
    seen_resolved: dict[Path, str] = {}
    seen_basenames: dict[str, Path] = {}

    def register(
        resolved_path: Path,
        origin_label: str,
        *,
        locator_posix: str | None = None,
        source_id: str | None = None,
        explicit: bool = False,
    ) -> None:
        if resolved_path == source or (design is not None and resolved_path == design):
            raise ValueError(f"{origin_label} collides with primary input or design file: {resolved_path}")
        if resolved_path.is_relative_to(output):
            raise ValueError(f"{origin_label} must not reside inside output directory: {resolved_path}")
        if resolved_path in seen_resolved:
            raise ValueError(
                f"Duplicate evidence dependency {resolved_path} (already bound via {seen_resolved[resolved_path]})."
            )
        basename = resolved_path.name
        if not basename or basename in (".", "..") or "/" in basename or "\\" in basename:
            raise ValueError(f"{origin_label} has an invalid filename: {basename!r}")
        if basename in seen_basenames:
            raise ValueError(
                f"Duplicate or ambiguous evidence basename {basename!r}: "
                f"{resolved_path} collides with {seen_basenames[basename]}."
            )
        raw = resolved_path.read_bytes()
        if not raw:
            raise ValueError(f"{origin_label} is empty: {resolved_path}")
        rel_key = f"evidence/{basename}"
        seen_resolved[resolved_path] = origin_label
        seen_basenames[basename] = resolved_path
        evidence_paths.append(resolved_path)
        evidence_snapshots[resolved_path] = raw
        evidence_records.append({
            "rel_path": rel_key,
            "path": str((output / rel_key).resolve()),
            "source_path": str(resolved_path),
            "locator": locator_posix,
            "source_ids": [source_id] if source_id else [],
            "explicit": explicit,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size": len(raw),
        })

    if data.get("kind") == "story" and not (source == _QUICKSTART_SAMPLE and evidence_root_arg is None):
        for index, item in enumerate(data.get("sources", [])):
            where = f"story.sources[{index}]"
            if "locator" in item:
                resolved_loc, rel_posix = _validate_relative_locator(item["locator"], where, ev_root)
                register(
                    resolved_loc,
                    f"{where}.locator",
                    locator_posix=rel_posix,
                    source_id=item.get("id"),
                    explicit=False,
                )
                evidence_locators.append(rel_posix)

    for index, raw_ev in enumerate(evidence_args):
        label = f"--evidence[{index}]"
        resolved_ev = _safe_existing_file(raw_ev, label)
        register(resolved_ev, label, locator_posix=None, source_id=None, explicit=True)

    evidence_records.sort(key=lambda r: r["rel_path"])
    return ev_root, evidence_paths, evidence_locators, evidence_snapshots, evidence_records


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


def normalized_input(source: Path, title: str | None = None, trusted_html: bool = False):
    """Validate before filesystem writes; keep the original bytes separately."""
    if type(trusted_html) is not bool:
        raise ValueError("trusted_html must be a boolean.")
    check_sensitive_read_path(source, "Input source")
    original = source.read_bytes()
    text = original.decode("utf-8-sig")
    if not text.strip():
        raise ValueError("Input is empty.")
    suffix = source.suffix.lower()
    if suffix == ".json":
        data = loads_json(text)
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
    resolved_title = title if title is not None else data.get("title", source.stem)
    if not isinstance(resolved_title, str) or not resolved_title.strip():
        raise ValueError("Title must not be empty.")
    data["title"] = resolved_title
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


def visual_inputs(data):
    """Walk validated structured visuals in source order; never parse raw HTML."""
    def sections(items, prefix):
        for index, item in enumerate(items):
            location = f"{prefix}[{index}]"
            if item["kind"] in ("diagram", "chart"):
                yield location, item
            elif item["kind"] == "sec":
                yield from sections(item.get("body", []), location + ".body")
    kind = data.get("kind")
    if kind in ("diagram", "chart"):
        yield "input", data
    elif kind == "story":
        for index, beat in enumerate(data["beats"]):
            if beat.get("visual"):
                yield f"beats[{index}].visual", beat["visual"]
    else:
        yield from sections(data.get("sections", []), "sections")


def render(args):
    source = _safe_existing_file(args.input, "Input source")
    original, normalized, data = normalized_input(source, args.title, args.trusted_html)
    design = _safe_existing_file(args.design, "Design file") if args.design else None
    design_bytes = design.read_bytes() if design else None
    if design_bytes is not None and not design_bytes.decode("utf-8-sig").strip():
        raise ValueError("Design file is empty.")
    requested_output = Path(args.output_dir)
    if requested_output.is_symlink():
        raise ValueError("Output directory must not be a symbolic link.")
    output = requested_output.resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Output directory must be new or empty; existing artifacts were not changed.")
    for in_path in (source, design):
        if in_path is not None and (in_path == output or in_path.is_relative_to(output)):
            raise ValueError("Output directory must not contain or collide with an input source or design.")

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
    evidence_args = list(getattr(args, "evidence", None) or [])
    evidence_root_arg = getattr(args, "evidence_root", None)
    ev_root, evidence_paths, evidence_locators, evidence_snapshots, evidence_records = _resolve_evidence_inputs(
        data,
        source=source,
        design=design,
        output=output,
        evidence_args=evidence_args,
        evidence_root_arg=evidence_root_arg,
    )
    companions = {}
    if data.get("kind") == "story":
        from ste_promax.stories import story_companions
        companions = story_companions(data)
    visuals = []
    for index, (location, visual) in enumerate(visual_inputs(data), 1):
        from ste_promax.charts import chart_svg
        from ste_promax.diagrams import diagram_svg
        name = f"visual-{index:02}.svg"
        companions[name] = diagram_svg(visual) if visual["kind"] == "diagram" else chart_svg(visual)
        visuals.append({"file": name, "source": location, "kind": visual["kind"]})

    saved_source = output / ("source" + source.suffix.lower())
    input_path = output / "input.json"
    retained = [("source", saved_source, original), ("input", input_path, normalized)]
    retained.extend((Path(name).stem, output / name, text.encode("utf-8"))
                    for name, text in companions.items())
    saved_design = output / "input-design.md" if (design is not None and design_bytes is not None) else None
    manifest_path = output / "manifest.json"
    gallery_target = output / "gallery.html"
    retained_evidence = [
        (rec["rel_path"], output / Path(rec["rel_path"]), evidence_snapshots[Path(rec["source_path"])])
        for rec in evidence_records
    ]

    target_paths = [str(path) for _, path, _ in retained]
    if saved_design is not None:
        target_paths.append(str(saved_design))
    target_paths.extend(str(path) for _, path, _ in retained_evidence)
    target_paths.extend((str(gallery_target), str(manifest_path)))

    proposed_contents = {
        str(input_path): normalized.decode("utf-8"),
        **{str(output / name): text for name, text in companions.items()},
    }
    if has_raw_html(data):
        source_kind = "raw_html"
    elif data.get("kind") == "story":
        source_kind = "story"
    elif source.suffix.lower() == ".md":
        source_kind = "markdown"
    else:
        source_kind = "structured"

    guard_inputs: dict[str, Any] = {
        "caller_kind": "native",
        "workspace_root": str(Path.cwd().resolve()),
        "output_root": str(output),
        "target_paths": target_paths,
        "source_paths": [str(source), *([str(design)] if design is not None else [])],
        "source_digest": hashlib.sha256(original).hexdigest(),
        "source_kind": source_kind,
        "trusted_html": bool(args.trusted_html),
        "evidence_root": str(ev_root),
        "evidence_paths": [str(p) for p in evidence_paths],
        "evidence_locators": evidence_locators,
        "availability": {"render_dependencies": True},
        "proposed_contents": proposed_contents,
        "expected_before": {p: None for p in target_paths},
    }

    failed_manifest: dict[str, Any] | None = None

    def _execute_render_bundle() -> dict[str, Any]:
        nonlocal failed_manifest
        output.mkdir(parents=True, exist_ok=True)
        for _, path, contents in retained:
            with path.open("xb") as stream:
                stream.write(contents)
        files = {name: file_record(path) for name, path, _ in retained}
        if saved_design is not None and design_bytes is not None:
            with saved_design.open("xb") as stream:
                stream.write(design_bytes)
            files["input_design"] = file_record(saved_design)
        for _, ev_target, ev_bytes in retained_evidence:
            ev_target.parent.mkdir(parents=True, exist_ok=True)
            with ev_target.open("xb") as stream:
                stream.write(ev_bytes)

        warnings = [
            "Semantic and visual review remain manual; artifact presence is not quality certification.",
            "External-reference detection is a conservative text scan including navigation URLs. "
            "Dynamic and relative assets require manual review; offline operation is not verified.",
        ]
        if args.trusted_html:
            warnings.append("Raw HTML was explicitly trusted, not sanitized.")
        expected = {"gallery": gallery_target}
        complete = False
        try:
            triple = render_artifact(
                data,
                design_path=saved_design,
                output_dir=output,
                trusted_html=bool(args.trusted_html),
            )
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
        protected = {path for _, path, _ in retained} | {saved_design, manifest_path}
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
        for name, path, content in retained:
            if path.is_symlink() or not path.is_file():
                complete = False
                warnings.append(f"Native renderer removed or replaced saved {name}.")
                files.pop(name, None)
                continue
            if path.read_bytes() != content:
                complete = False
                warnings.append(f"Native renderer unexpectedly changed saved {name}.")
            files[name] = file_record(path)
        for rel_label, ev_target, ev_bytes in retained_evidence:
            if ev_target.is_symlink() or not ev_target.is_file() or ev_target.read_bytes() != ev_bytes:
                complete = False
                warnings.append(f"Native renderer removed or modified saved {rel_label}.")
        manifest = {
            "status": "complete" if complete else "failed", "version": __version__,
            "renderer": "ste_promax.render", "source_path": str(source),
            "source_sha256": hashlib.sha256(original).hexdigest(), "files": files,
            "trusted_html": bool(args.trusted_html), "lint_passed": lint,
            "external_references": sorted(external), "offline_verified": False, "warnings": warnings,
            "visuals": visuals,
        }
        if evidence_records or evidence_root_arg is not None or data.get("kind") == "story":
            manifest["evidence_root"] = str(ev_root)
            manifest["evidence_files"] = evidence_records
        with manifest_path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(manifest, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        if not complete:
            failed_manifest = manifest
        return manifest

    def _validate_render_bundle(manifest: dict[str, Any]) -> dict[str, Any]:
        nonlocal failed_manifest
        if source.is_symlink() or not source.is_file() or source.read_bytes() != original:
            failed_manifest = None
            raise PolicyError(
                "Original source file changed during or after rendering.",
                code=ERROR_POSTCONDITION_FAILURE,
            )
        if design is not None and design_bytes is not None:
            if design.is_symlink() or not design.is_file() or design.read_bytes() != design_bytes:
                failed_manifest = None
                raise PolicyError(
                    "Design file changed during or after rendering.",
                    code=ERROR_POSTCONDITION_FAILURE,
                )
        for ev_path, expected_ev_bytes in evidence_snapshots.items():
            try:
                ev_info = ev_path.lstat()
            except FileNotFoundError as exc:
                failed_manifest = None
                raise PolicyError(
                    f"Evidence source file disappeared during or after rendering: {ev_path}",
                    code=ERROR_POSTCONDITION_FAILURE,
                ) from exc
            if _is_link_or_reparse(ev_info) or not stat.S_ISREG(ev_info.st_mode):
                failed_manifest = None
                raise PolicyError(
                    f"Evidence source file became unsafe during or after rendering: {ev_path}",
                    code=ERROR_POSTCONDITION_FAILURE,
                )
            if ev_path.read_bytes() != expected_ev_bytes:
                failed_manifest = None
                raise PolicyError(
                    f"Evidence source file changed during or after rendering: {ev_path}",
                    code=ERROR_POSTCONDITION_FAILURE,
                )
        if not isinstance(manifest, dict) or manifest.get("status") != "complete":
            raise PolicyError(
                "; ".join(manifest.get("warnings", [])) if isinstance(manifest, dict) else "Native render failed.",
                code=ERROR_POSTCONDITION_FAILURE,
                partial_result=manifest if (isinstance(manifest, dict) and manifest.get("status") == "failed") else None,
            )
        outputs: dict[str, dict[str, Any]] = {}
        files_map = manifest.get("files")
        if not isinstance(files_map, dict):
            raise PolicyError("Render manifest is missing files map.", code=ERROR_POSTCONDITION_FAILURE)
        for role, rec in files_map.items():
            if not isinstance(rec, dict) or "path" not in rec or "sha256" not in rec:
                raise PolicyError(f"Malformed manifest file record for {role!r}.", code=ERROR_POSTCONDITION_FAILURE)
            p = Path(rec["path"])
            if p.is_symlink() or not p.is_file():
                raise PolicyError(f"Missing or unsafe output file for {role!r}: {p}", code=ERROR_POSTCONDITION_FAILURE)
            resolved_p = p.resolve()
            if resolved_p.parent != output:
                raise PolicyError(
                    f"Output file for {role!r} escaped output directory: {p}",
                    code=ERROR_POSTCONDITION_FAILURE,
                )
            raw = p.read_bytes()
            if not raw:
                raise PolicyError(f"Empty output file for {role!r}: {p}", code=ERROR_POSTCONDITION_FAILURE)
            digest = hashlib.sha256(raw).hexdigest()
            if digest != rec["sha256"]:
                raise PolicyError(
                    f"Output file hash mismatch for {role!r}: {p}",
                    code=ERROR_POSTCONDITION_FAILURE,
                )
            outputs[str(resolved_p)] = {"sha256": digest, "size": len(raw)}
        for rec in evidence_records:
            ev_target = output / Path(rec["rel_path"])
            if ev_target.is_symlink() or not ev_target.is_file():
                raise PolicyError(
                    f"Render-time evidence snapshot missing or unsafe: {ev_target}",
                    code=ERROR_POSTCONDITION_FAILURE,
                )
            resolved_ev_target = ev_target.resolve()
            if resolved_ev_target.parent != (output / "evidence").resolve():
                raise PolicyError(
                    f"Render-time evidence snapshot escaped output/evidence/: {ev_target}",
                    code=ERROR_POSTCONDITION_FAILURE,
                )
            ev_raw = ev_target.read_bytes()
            ev_digest = hashlib.sha256(ev_raw).hexdigest()
            if ev_digest != rec["sha256"] or len(ev_raw) != rec["size"]:
                raise PolicyError(
                    f"Render-time evidence snapshot hash mismatch: {ev_target}",
                    code=ERROR_POSTCONDITION_FAILURE,
                )
            outputs[str(resolved_ev_target)] = {"sha256": ev_digest, "size": len(ev_raw)}
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise PolicyError("Render manifest.json is missing or unsafe.", code=ERROR_POSTCONDITION_FAILURE)
        manifest_raw = manifest_path.read_bytes()
        if not manifest_raw:
            raise PolicyError("Render manifest.json is empty.", code=ERROR_POSTCONDITION_FAILURE)
        outputs[str(manifest_path.resolve())] = {
            "sha256": hashlib.sha256(manifest_raw).hexdigest(),
            "size": len(manifest_raw),
        }
        return {
            "status": manifest["status"],
            "native_status": manifest["status"],
            "outputs": outputs,
            "checks": [
                "manifest_complete",
                "retained_inputs_verified",
                "artifacts_verified",
                "source_closure_unchanged",
            ],
            "warnings": list(manifest.get("warnings", [])),
        }

    from ste_promax.gate import run_guarded_operation

    try:
        return run_guarded_operation(
            "ste.render_bundle",
            guard_inputs,
            _execute_render_bundle,
            validate_result=_validate_render_bundle,
        )
    except PolicyError as exc:
        if isinstance(exc.partial_result, dict) and exc.partial_result.get("status") == "failed":
            return exc.partial_result
        if isinstance(failed_manifest, dict) and failed_manifest.get("status") == "failed":
            return failed_manifest
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(prog="ste-promax", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command")
    starter = commands.add_parser("start", help="Make a local artifact from a source or the fictional demo.")
    starter.add_argument("input", nargs="?", help="Local .md, .json, or reviewed .html source.")
    starter.add_argument("--output-dir", help="New directory; defaults to a fresh folder under ./artifacts/.")
    starter.add_argument("--title")
    starter.add_argument("--design", help="Local design file, archived with the input.")
    starter.add_argument("--evidence", action="append", default=[], metavar="FILE",
                         help="Local evidence file to bind and verify with the artifact (repeatable).")
    starter.add_argument("--evidence-root",
                         help="Directory for resolving relative structured source locators (default: INPUT parent).")
    starter.add_argument("--trusted-html", action="store_true",
                         help="Explicitly trust reviewed authored HTML; never inferred.")
    starter.add_argument("--json", action="store_true", help="Print the unmodified render manifest.")
    starter.add_argument("--open", action="store_true", help="Open the result only after successful rendering.")
    doctor = commands.add_parser("doctor", help="Read-only local dependency and platform diagnostics.")
    doctor.add_argument("--json", action="store_true")
    check = commands.add_parser("check", help="Advisory prose-length diagnostics; no certification.")
    check.add_argument("input")
    check.add_argument("--profile", choices=LIMITS, default="relaxed")
    check.add_argument("--json", action="store_true")
    check.add_argument("--fail-on-findings", action="store_true")
    schema = commands.add_parser("schema", help="Describe native input shapes with usable examples; outputs JSON.")
    schema.add_argument("kind", nargs="?", help="story, diagram, chart, or another section kind; omit for all.")
    renderer = commands.add_parser("render", help="Render through the native STE-Pro Max implementation.")
    renderer.add_argument("input")
    renderer.add_argument("--output-dir", required=True)
    renderer.add_argument("--title")
    renderer.add_argument("--design", help="Local design file, archived with the input.")
    renderer.add_argument("--evidence", action="append", default=[], metavar="FILE",
                          help="Local evidence file to bind and verify with the artifact (repeatable).")
    renderer.add_argument("--evidence-root",
                          help="Directory for resolving relative structured source locators (default: INPUT parent).")
    renderer.add_argument("--trusted-html", action="store_true",
                          help="Explicitly trust reviewed authored HTML; never inferred from input metadata.")
    narrator = commands.add_parser("narrate", help="Prepare story media from local speech or PCM audio; never export a movie.")
    narrator.add_argument("input")
    narrator.add_argument("--output-dir", required=True, help="New directory with an existing parent.")
    audio_source = narrator.add_mutually_exclusive_group()
    audio_source.add_argument("--voice", help="Installed Windows System.Speech voice.")
    audio_source.add_argument("--audio-dir", type=Path, help="Local directory of <beat-id>.wav files.")
    exporter = commands.add_parser(
        "export",
        help="Automatically verify and export a fresh native render bundle into a new destination.",
    )
    exporter.add_argument("--input-dir", required=True, help="Existing fresh native render bundle directory.")
    exporter.add_argument("--output-dir", required=True, help="New export destination directory.")
    exporter.add_argument("--evidence", action="append", default=[], metavar="FILE",
                          help="Local evidence file to verify with the bundle (repeatable).")
    exporter.add_argument("--evidence-root",
                          help="Directory for resolving relative structured source locators.")
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        print("\nFirst result: start          Environment check: doctor\n"
              "Local files only; no API or model calls. Browser opens only with start --open.")
        return 0
    try:
        # ASCII-escaped JSON survives legacy host pipes; artifact files remain UTF-8.
        if args.command in {"start", "doctor"}:
            from ste_promax.onboarding import run
            return run(args)
        if args.command == "export":
            from ste_promax.gate import export_bundle
            export_kwargs: dict[str, Any] = {}
            if getattr(args, "evidence_root", None) is not None:
                export_kwargs["evidence_root"] = args.evidence_root
            if getattr(args, "evidence", None):
                export_kwargs["evidence"] = list(args.evidence)
            result = export_bundle(args.input_dir, args.output_dir, **export_kwargs)
            print(json.dumps(result, ensure_ascii=True, indent=2))
            return 0 if result.get("status", "exported") in {"exported", "complete"} else 2
        if args.command == "schema":
            from ste_promax.section_schema import SECTION_SCHEMA
            from ste_promax.stories import STORY_SCHEMA
            result = {"format": "ste-promax.schema-catalog.v1", "story": STORY_SCHEMA, "sections": SECTION_SCHEMA}
            if args.kind:
                result = STORY_SCHEMA if args.kind == "story" else SECTION_SCHEMA.get(args.kind)
                if result is None:
                    raise ValueError(f"Unknown schema {args.kind!r}; run 'schema' to list the supported shapes.")
            print(json.dumps(result, ensure_ascii=True, indent=2))
            return 0
        if args.command == "render":
            result = render(args)
            print(json.dumps(result, ensure_ascii=True, indent=2))
            return 0 if result["status"] == "complete" else 2
        if args.command == "narrate":
            from ste_promax.media import prepare_story_media
            result = prepare_story_media(Path(args.input), Path(args.output_dir),
                                         voice=args.voice, audio_dir=args.audio_dir)
            print(json.dumps(result, ensure_ascii=True, indent=2))
            return 0 if result["status"] == "prepared_not_rendered" else 2
        result = check_text(Path(args.input).read_text(encoding="utf-8-sig"), args.profile)
        if args.json:
            print(json.dumps(result, ensure_ascii=True, indent=2))
        else:
            print(f"{result['word_count']} words; {result['sentence_count']} sentences; "
                  f"{len(result['findings'])} advisory findings ({args.profile}).")
            for finding in result["findings"]:
                print(json.dumps(finding, ensure_ascii=False))
            print("\n".join(result["limitations"]))
        return 1 if args.fail_on_findings and result["findings"] else 0
    except (OSError, ValueError, ImportError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
